"""
auto_brief.py
-------------
Génération d'un brief LIGHT pour un marché à partir uniquement de
l'avis BOAMP (titre + objet + métadonnées), sans accès au DCE complet.

Ce brief est destiné à donner du contenu à TOUTES les fiches marchés
dès l'ingestion, même sans téléchargement du DCE. Il sera remplacé
automatiquement par un brief COMPLET quand le DCE sera téléchargé et
`tendia_extraire.py` lancé.

Différenciation light vs complet :
- LIGHT  : _meta.type = "light"     (depuis l'avis seulement)
- COMPLET : _meta.type absent ou ≠ "light"  (depuis le DCE complet)

Coût : ~3-5 cents par marché avec Sonnet 4.6.
"""

import json
import re
import time
from datetime import datetime, timezone
from typing import Optional

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

# Réutilise la logique de clé API éprouvée de llm_extract.py
# (gère le BOM UTF-8 Notepad, fallback .env.txt sous Windows)
from llm_extract import _obtenir_cle_api


# Sonnet 4.6 — qualité maximale pour un brief décisionnel
MODELE = "claude-sonnet-4-6"
MAX_TOKENS_REPONSE = 2000


PROMPT_SYSTEME = """Tu es un expert en marchés publics français de \
formation professionnelle et d'insertion (France Travail / ex-Pôle Emploi).

Tu analyses UNIQUEMENT l'avis publié au BOAMP (titre + objet + \
métadonnées de l'avis), SANS accès au Dossier de Consultation des \
Entreprises (DCE).

Ta mission : produire un brief LIGHT qui permet à un organisme de \
formation de :
1. Comprendre rapidement ce que vise le marché
2. Identifier les points-clés (public, prestation probable, durée)
3. Lister ce qu'il devra vérifier dans le DCE pour candidater
4. Anticiper les alertes typiques de ce type de marché

Tu NE PEUX PAS inventer ce qui n'est pas dans l'avis. Si un champ n'est \
pas renseigné par l'avis seul (volumes précis, barème, formule prix, \
références exigées, etc.), tu mets null ou [] et tu signales explicitement \
dans `elements_a_verifier_dans_dce` ce qu'il faut chercher.

Réponds UNIQUEMENT en JSON valide, sans préambule, sans bloc markdown, \
sans commentaire."""


PROMPT_UTILISATEUR_TEMPLATE = """Voici l'avis d'un marché public.

MÉTADONNÉES DU MARCHÉ :
{contexte}

TITRE :
{titre}

OBJET (texte intégral de l'avis BOAMP) :
---
{objet}
---

Produis le brief LIGHT dans ce schéma JSON :

{{
  "synthese_marche": "Résumé du marché en 2-3 phrases factuelles, qui répondent à : que demande l'acheteur, à quel public, pour quelle prestation. Ne paraphrase pas trivialement l'objet, donne du sens.",

  "publics_cibles": {{
    "description": "Description courte du public visé SI elle apparaît dans l'avis. Sinon null.",
    "criteres_eligibilite": ["liste des critères d'éligibilité explicitement mentionnés dans l'avis, sinon []"],
    "publics_specifiques_signales": ["tags courts : RQTH, BRSA, jeunes, seniors, allophones, QPV, etc. — uniquement si explicites dans l'avis"]
  }},

  "prestation_inferee": "Choisis EXACTEMENT une valeur parmi cette liste fermée si l'objet correspond clairement : AFC, AFPR, POEI, POEC, ACTIV_Seniors, ACTIV_Decouverte, ACTIV_Crea, ACTIV_Emergence, AGIL_Cadres, MILE, Creascope, Bilan_competences, VAE, formation_diplomante, formation_certifiante, formation_continue, prestation_intellectuelle, autre. Si l'objet est vague, mets 'autre'. Ne devine pas trop fort.",

  "volumes": {{
    "nb_beneficiaires_total": "nombre uniquement si chiffré explicitement dans l'avis, sinon null",
    "duree_marche_mois": "nombre uniquement si chiffré, sinon null",
    "commentaire_volumes": "À vérifier dans le DCE — l'avis BOAMP ne précise généralement pas les volumes."
  }},

  "calendrier": {{
    "date_limite_offres": "YYYY-MM-DD si dans l'avis, sinon null",
    "date_demarrage_prevue": "YYYY-MM-DD si dans l'avis, sinon null",
    "duree_marche": "Ex: '24 mois reconductibles' si dans l'avis, sinon null"
  }},

  "montant_marche": {{
    "valeur_estimee_euros": "nombre uniquement si l'avis donne explicitement le montant estimé, sinon null",
    "fourchette_min_euros": null,
    "fourchette_max_euros": null,
    "type": "estime_explicite | plafond | non_communique",
    "commentaire": "Texte court expliquant ce que tu as trouvé dans l'avis."
  }},

  "revision_prix": {{
    "type": "non_communique",
    "indices_utilises": [],
    "ponderation": null,
    "periodicite": null,
    "formule_revision": null,
    "commentaire": "À vérifier dans le CCAP (Cahier des Clauses Administratives Particulières) du DCE — l'indice de révision n'est quasi jamais mentionné dans l'avis BOAMP."
  }},

  "alertes_candidat": [
    "Liste de 3-5 alertes pertinentes. Distingue clairement :",
    "(1) Les alertes EXPLICITES tirées de l'avis (ex: 'Qualiopi mentionnée dans l'avis')",
    "(2) Les alertes PROBABLES typiques de ce type de marché FT (ex: 'Probablement Qualiopi obligatoire à peine d'irrecevabilité'). Commence ces dernières par 'Probablement' pour les distinguer."
  ],

  "elements_a_verifier_dans_dce": [
    "Liste de 4-7 points CONCRETS à chercher dans le DCE. Sois précis : ne mets pas 'lire le RC'. Exemples : 'Barème exact technique/prix (souvent 60/40 ou 70/30 pour ce type de marché)', 'CA minimum exigé sur 3 derniers exercices', 'Expérience minimum requise (souvent 3 ans pour les marchés FT)', 'Certifications obligatoires précises', 'Sites d'exécution obligatoires vs additionnels', 'Formule de notation prix (moins-disant, écart-type, etc.)', 'Volumes précis (nb bénéficiaires × durée parcours)', 'Indice de révision des prix dans le CCAP (SYNTEC, ILC, formule de pondération) — crucial pour anticiper la rentabilité sur marchés longs'"
  ],

  "points_differenciants_probables": [
    "Liste de 2-4 axes de différenciation probables pour ce type de marché, basés sur le contexte FT formation/insertion. Sois pratique : 'Réseau d'entreprises locales pour mise en relation', 'Approche RSE chiffrée (énergie renouvelable, équipements reconditionnés)', 'Méthodologie éprouvée sur public similaire avec références chiffrées', 'Outils numériques propriétaires'."
  ]
}}

RÈGLES STRICTES :
- N'INVENTE PAS de chiffres. Si non visible dans l'avis, mets null. Aucune valeur faite au pifomètre.
- Pour `synthese_marche` : 2-3 phrases maximum, factuel, qui apportent du sens (pas de paraphrase plate).
- Pour `prestation_inferee` : si l'objet contient le mot clé exact (AFC, ACTIV Seniors, MILE...), prends-le. Sinon "autre".
- Pour `alertes_candidat` : distingue clairement le SAU (sûr, depuis l'avis) du PROBABLE (typique FT). Ne mélange pas.
- Pour `elements_a_verifier_dans_dce` : sois opérationnel — quels champs PRÉCIS chercher dans quel document du DCE ?
- Pour `points_differenciants_probables` : reste générique mais utile. Pas de "fournir une bonne prestation" qui est creux.

Réponds UNIQUEMENT avec le JSON, sans aucun texte autour."""


def generer_brief_light(marche: dict,
                          verbose: bool = False) -> Optional[dict]:
    """
    Génère un brief LIGHT pour un marché à partir de son avis BOAMP.

    Args:
        marche: dict du marché (depuis marches.json)
        verbose: True pour afficher les détails d'appel API

    Returns:
        dict du brief avec _meta.type = "light", ou None en cas d'échec.

    Raises:
        budget.BudgetDepasseError : si le quota budget LLM est atteint.
    """
    if Anthropic is None:
        if verbose:
            print("    ⚠ SDK anthropic absent")
        return None
    if not _obtenir_cle_api():
        if verbose:
            print("    ⚠ Clé API absente")
        return None

    marche_id = marche.get("id")

    # === Garde-fou budget (Sprint 3) ===
    import budget as _budget
    decision = _budget.peut_appeler_llm("extraction", marche_id=marche_id)
    if not decision.autorise:
        if verbose:
            print(f"    ⛔ Budget : {decision.raison}")
        _budget.enregistrer_appel(
            type_appel="extraction",
            cout_eur=0.0,
            statut="bloque_budget",
            marche_id=marche_id,
            erreur=decision.raison,
        )
        raise _budget.BudgetDepasseError(decision.raison)

    # Contexte = métadonnées clés du marché
    contexte = {
        "id": marche.get("id"),
        "source": marche.get("source"),
        "acheteur_nom": marche.get("acheteur_nom"),
        "cpv_principal": marche.get("cpv_principal"),
        "categorie_metier": marche.get("categorie_metier"),
        "lieu_execution": (marche.get("lieu_execution")
                           or marche.get("perimetre_geographique")),
        "date_publication": marche.get("date_publication"),
        "date_limite_depot": marche.get("date_limite_depot"),
    }

    titre = (marche.get("titre") or "").strip()
    objet = (marche.get("objet") or "").strip()

    # Garde-fou : objet trop court → on n'envoie pas
    if not objet or len(objet) < 30:
        if verbose:
            print(f"    ⊘ Objet trop court ({len(objet)} chars)")
        return None

    # Tronque pour limiter l'input (8k chars ≈ 2k tokens, largement assez)
    if len(objet) > 8000:
        objet = objet[:8000] + " [...tronqué]"

    prompt = PROMPT_UTILISATEUR_TEMPLATE.format(
        contexte=json.dumps(contexte, ensure_ascii=False, indent=2),
        titre=titre,
        objet=objet,
    )

    client = Anthropic()
    debut = time.time()

    try:
        message = client.messages.create(
            model=MODELE,
            max_tokens=MAX_TOKENS_REPONSE,
            system=PROMPT_SYSTEME,
            messages=[{"role": "user", "content": prompt}],
        )
        reponse_text = message.content[0].text if message.content else ""
        in_tokens = message.usage.input_tokens
        out_tokens = message.usage.output_tokens
        cout_eur = _budget.estimer_cout_eur(in_tokens, out_tokens)
        duree = time.time() - debut

        # Parse JSON
        data = None
        try:
            data = json.loads(reponse_text)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", reponse_text, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
        if not data:
            if verbose:
                print(f"    ⚠ JSON invalide")
                print(f"    Début réponse : {reponse_text[:300]}")
            _budget.enregistrer_appel(
                type_appel="extraction",
                cout_eur=cout_eur,
                statut="erreur",
                marche_id=marche_id,
                tokens_input=in_tokens,
                tokens_output=out_tokens,
                duree_ms=int(duree * 1000),
                modele=MODELE,
                erreur="reponse_non_json",
            )
            return None

        # Tag _meta : c'est ce qui distingue ce brief light d'un complet
        data["_meta"] = {
            "type": "light",
            "modele": MODELE,
            "date_generation": datetime.now(timezone.utc).isoformat(),
            "tokens_in": in_tokens,
            "tokens_out": out_tokens,
            "cout_eur": cout_eur,
            "duree_sec": round(duree, 1),
            "source_avis_seulement": True,
        }

        # Log appel OK pour audit budget
        _budget.enregistrer_appel(
            type_appel="extraction",
            cout_eur=cout_eur,
            statut="ok",
            marche_id=marche_id,
            tokens_input=in_tokens,
            tokens_output=out_tokens,
            duree_ms=int(duree * 1000),
            modele=MODELE,
        )
        return data

    except _budget.BudgetDepasseError:
        raise
    except Exception as e:
        if verbose:
            print(f"    ⚠ Erreur API : {e}")
        _budget.enregistrer_appel(
            type_appel="extraction",
            cout_eur=0.0,
            statut="erreur",
            marche_id=marche_id,
            modele=MODELE,
            erreur=f"{type(e).__name__}: {e}",
        )
        return None


def est_brief_light(brief: Optional[dict]) -> bool:
    """
    True si le brief est un LIGHT (généré depuis l'avis seul).
    False si COMPLET (généré depuis le DCE par tendia_extraire.py),
    ou si brief est None.
    """
    if not brief:
        return False
    meta = brief.get("_meta") or {}
    return meta.get("type") == "light"


def est_brief_complet(brief: Optional[dict]) -> bool:
    """
    True si le brief est COMPLET (vient du DCE via tendia_extraire.py).
    Détection : absence de _meta.type=="light", ET présence d'au moins
    un signal du brief complet (bareme_notation rempli, references_exigees,
    etc. — les choses qu'on ne peut PAS extraire depuis un avis seul).
    """
    if not brief:
        return False
    meta = brief.get("_meta") or {}
    if meta.get("type") == "light":
        return False
    # Signal positif : présence de données impossibles à inférer depuis l'avis
    bareme = brief.get("bareme_notation") or {}
    has_bareme = bool(bareme.get("sous_criteres_techniques"))
    has_refs = bool(brief.get("references_exigees", {}).get("certifications_obligatoires"))
    return has_bareme or has_refs


if __name__ == "__main__":
    # Test rapide en CLI : python auto_brief.py <chemin_marche.json>
    import sys

    if len(sys.argv) < 2:
        print("Usage : python auto_brief.py <id_marche>")
        print("        (charge data/marches.json et génère le brief)")
        sys.exit(1)

    from pathlib import Path
    REPERTOIRE_BASE = Path(__file__).parent
    chemin = REPERTOIRE_BASE / "data" / "marches.json"
    marches = json.load(open(chemin, encoding="utf-8"))
    id_m = sys.argv[1]
    if id_m not in marches:
        print(f"Marché {id_m} introuvable.")
        sys.exit(1)

    print(f"Génération brief light pour {id_m}...")
    brief = generer_brief_light(marches[id_m], verbose=True)
    if brief:
        print()
        print(json.dumps(brief, ensure_ascii=False, indent=2))
    else:
        print("Échec.")
