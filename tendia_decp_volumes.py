"""
tendia_decp_volumes.py
----------------------
Rétro-extraction LLM des volumes manquants sur les marchés DECP historiques.

Pour chaque marché DECP (`data/marches_notifies.json`), on a déjà via les
métadonnées : montant_eur, duree_mois, objet (texte libre), categorie_metier.
Ce qui manque pour faire du KNN propre dans Phase C : nb_bénéficiaires,
durée parcours en heures, prestation précise, public cible, modalité.

Ce script :
1. Lit data/marches_notifies.json (typiquement 700+ marchés FT)
2. Pour chaque marché sans champ `volumes_extraits` (ou avec --force), envoie
   l'objet + le contexte à Claude Haiku 4.5 (modèle économique, ~0,1 cent
   par marché) pour extraire les volumes.
3. Enregistre dans le marché un nouveau champ `volumes_extraits` avec les
   valeurs et la trace de l'extraction.
4. Sauvegarde au fur et à mesure (toutes les 20 entrées) pour ne rien perdre
   en cas d'interruption.

Usage :
    python tendia_decp_volumes.py                  # tous les marchés sans extraction
    python tendia_decp_volumes.py --force          # re-extrait tout
    python tendia_decp_volumes.py --limit 20       # test sur 20 marchés
    python tendia_decp_volumes.py --dry-run        # compte sans appeler l'API
    python tendia_decp_volumes.py --marche DECP-X  # un seul marché

Coût estimé : ~0,50 € pour 735 marchés avec Haiku 4.5.
Pas de coût en re-exécution (skip auto des marchés déjà traités).
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Import différé pour autoriser --dry-run sans le SDK
try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPERTOIRE_BASE = Path(__file__).parent
FICHIER_DECP = REPERTOIRE_BASE / "data" / "marches_notifies.json"
FICHIER_ENV = REPERTOIRE_BASE / ".env"

# Sonnet 4.6 — meilleure qualité sur les cas limites (classification fine,
# inférences subtiles, adhésion stricte aux listes fermées). Coût marginal
# trivial (~$3 vs $0.85 avec Haiku) pour une extraction batch unique sur
# de la donnée permanente.
MODELE = "claude-sonnet-4-6"
MAX_TOKENS_REPONSE = 600          # ample, on attend ~150-200 tokens JSON
SAUVEGARDE_INTERVALLE = 20        # sauve sur disque toutes les N extractions

# Prix Sonnet 4.6 : ~$3/MTok input, ~$15/MTok output
PRIX_IN_PAR_MTOK = 3.0
PRIX_OUT_PAR_MTOK = 15.0


# ---------------------------------------------------------------------------
# Filtre de pertinence métier
# ---------------------------------------------------------------------------
# Tendia cible la formation + les prestations aux demandeurs d'emploi.
# La base DECP contient TOUS les marchés FT (travaux BTP, déménagement,
# IT, maintenance, etc.) — pour le KNN sur les prix, seuls les marchés
# de notre univers métier ont du sens comme comparables. On filtre donc
# AVANT d'envoyer à l'API pour ne pas payer à qualifier du bruit.

# Catégories métier déjà identifiées comme pertinentes
CATEGORIES_PERTINENTES = {"formation", "insertion"}

# Préfixes CPV pertinents pour rattraper les marchés mal catégorisés.
# Sources : nomenclature CPV publique + analyse de la base actuelle.
CPV_PERTINENTS_PREFIXES = (
    "80",          # 80XXXXXX = Services d'enseignement et de formation
    "85312",       # Services d'orientation et conseil (insertion DE)
    "85310",       # Services d'action sociale
    "85320",       # Services sociaux
    "79634",       # Services d'orientation professionnelle
    "79411100",    # Conseil en développement commercial (Creascope, AGIL_Cadres)
)


def _est_pertinent(marche: dict) -> bool:
    """
    Retourne True si le marché est dans le périmètre métier (formation +
    prestations DE). Sinon False (= sera marqué exclu_filtre sans appel API).
    """
    cat = (marche.get("categorie_metier") or "").strip().lower()
    if cat in CATEGORIES_PERTINENTES:
        return True
    cpv = (marche.get("cpv_principal") or "").strip()
    if any(cpv.startswith(p) for p in CPV_PERTINENTS_PREFIXES):
        return True
    return False


# ---------------------------------------------------------------------------
# Clé API — on réutilise la logique éprouvée de llm_extract.py qui gère
# correctement le BOM UTF-8 (Notepad) et le fallback .env.txt sous Windows.
# ---------------------------------------------------------------------------

from llm_extract import _obtenir_cle_api


# ---------------------------------------------------------------------------
# Prompt d'extraction
# ---------------------------------------------------------------------------

PROMPT_SYSTEME = """Tu es un expert en marchés publics français de \
formation et d'insertion (France Travail). Tu extrais des volumes \
chiffrés et des classifications depuis l'objet d'un marché DECP.

Réponds UNIQUEMENT en JSON valide, sans préambule, sans bloc markdown."""


PROMPT_UTILISATEUR_TEMPLATE = """Voici l'objet d'un marché historique attribué par France Travail.

CONTEXTE :
- ID : {id_marche}
- Montant total attribué : {montant} €
- Durée du marché : {duree} mois
- Catégorie métier : {categorie}
- Lieu d'exécution : {lieu}
- Acheteur : {acheteur}

OBJET (texte libre du marché) :
---
{objet}
---

Extrais ces 6 informations dans ce schéma JSON :

{{
  "nb_beneficiaires": null,
  "duree_heures_parcours": null,
  "prestation_precise": null,
  "public_cible": null,
  "modalite": null,
  "confiance": "haute"
}}

RÈGLES STRICTES :

- `nb_beneficiaires` : NOMBRE de bénéficiaires sur toute la durée du marché \
(ex: 1500). Si l'objet dit "200 par an sur 2 ans" → 400. Si non chiffré → null.

- `duree_heures_parcours` : nombre d'heures par PARCOURS individuel (par \
bénéficiaire), pas heures totales. Si l'objet dit "parcours de 90 jours" sans \
heures, mets null. Si "35h par bénéficiaire" → 35. Si non chiffré → null.

- `prestation_precise` : choisis EXACTEMENT une valeur parmi cette liste \
fermée si l'objet correspond clairement :
  "AFC" "AFPR" "POEI" "POEC" "ACTIV_Seniors" "ACTIV_Decouverte" "ACTIV_Crea" \
"ACTIV_Emergence" "AGIL_Cadres" "MILE" "Creascope" "Bilan_competences" "VAE" \
"formation_diplomante" "formation_certifiante" "formation_continue" \
"prestation_intellectuelle" "autre"
  Si l'objet ne correspond à aucune de ces prestations standards, mets "autre".
  Ne fais PAS du fuzzy matching : si l'objet dit "Activ' Seniors" → \
"ACTIV_Seniors", si l'objet dit juste "marché de prestations intellectuelles" \
→ "prestation_intellectuelle", si rien de spécifique → "autre".

- `public_cible` : courte étiquette parmi cette liste fermée si claire :
  "DELD" "demandeurs_emploi" "jeunes" "seniors" "cadres" "RQTH" "BRSA" \
"publics_eloignes" "allophones" "creation_entreprise" "tous_publics" "autre"
  Si non précisé → null.

- `modalite` : "presentiel" / "distanciel" / "mixte" si précisé, sinon null.

- `confiance` : ton niveau de certitude sur les valeurs extraites :
  "haute" : l'objet est explicite sur la plupart des champs
  "moyenne" : tu déduis raisonnablement de l'objet
  "faible" : objet vague, beaucoup de null

NE PAS INVENTER. Si l'objet est trop vague pour un champ, mets null pour ce \
champ. Mieux vaut null que faux.

Réponds UNIQUEMENT avec le JSON, sans aucun texte autour."""


# ---------------------------------------------------------------------------
# Extraction d'un marché
# ---------------------------------------------------------------------------

def _extraire_un_marche(client, marche: dict, verbose: bool = False) -> Optional[dict]:
    """
    Appelle Claude Haiku pour extraire les volumes d'un marché DECP.
    Retourne le dict des volumes ou None si échec.
    """
    objet = (marche.get("objet") or "").strip()
    if not objet or len(objet) < 30:
        # Objet trop court ou absent → on ne tente même pas
        return {
            "nb_beneficiaires": None,
            "duree_heures_parcours": None,
            "prestation_precise": None,
            "public_cible": None,
            "modalite": None,
            "confiance": "faible",
            "_meta": {
                "raison_skip": "objet trop court ou absent",
                "date_extraction": datetime.now(timezone.utc).isoformat(),
            },
        }

    # Tronque l'objet à 4000 chars pour limiter les tokens
    if len(objet) > 4000:
        objet = objet[:4000] + " [...]"

    prompt = PROMPT_UTILISATEUR_TEMPLATE.format(
        id_marche=marche.get("id", "?"),
        montant=marche.get("montant_eur") or "?",
        duree=marche.get("duree_mois") or "?",
        categorie=marche.get("categorie_metier") or "?",
        lieu=marche.get("lieu_execution") or "?",
        acheteur=marche.get("acheteur_nom") or "?",
        objet=objet,
    )

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
                print(f"    ⚠ JSON invalide, ignoré")
            return None

        # Ajoute la trace de l'extraction
        data["_meta"] = {
            "modele": MODELE,
            "date_extraction": datetime.now(timezone.utc).isoformat(),
            "tokens_in": in_tokens,
            "tokens_out": out_tokens,
        }
        return data
    except Exception as e:
        if verbose:
            print(f"    ⚠ Erreur API : {e}")
        return None


# ---------------------------------------------------------------------------
# Boucle principale
# ---------------------------------------------------------------------------

def _charger_decp() -> dict:
    if not FICHIER_DECP.is_file():
        raise FileNotFoundError(f"Fichier DECP introuvable : {FICHIER_DECP}")
    with open(FICHIER_DECP, encoding="utf-8") as f:
        return json.load(f)


def _sauver_decp(data: dict):
    """Sauvegarde atomique via fichier temporaire."""
    tmp = FICHIER_DECP.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(FICHIER_DECP)


def main():
    parser = argparse.ArgumentParser(
        description="Rétro-extraction LLM des volumes DECP via Haiku.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--force", action="store_true",
                        help="Re-extrait même les marchés déjà traités.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limite le nombre de marchés traités (test).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compte sans appeler l'API.")
    parser.add_argument("--marche", type=str, default=None,
                        help="Traite uniquement ce marché DECP-XXX (test).")
    parser.add_argument("--no-filtre", action="store_true",
                        help="Désactive le filtre métier (formation/insertion). "
                             "Par défaut, les marchés BTP/IT/transport/etc. "
                             "sont marqués 'exclu_filtre' sans appel API.")
    args = parser.parse_args()

    print("=" * 70)
    print(f"  Tendia · Rétro-extraction volumes DECP via {MODELE}")
    print("=" * 70)
    print()

    # Charge la base DECP
    decp = _charger_decp()
    print(f"  Base DECP chargée : {len(decp)} marchés")

    # Filtre les marchés à traiter
    if args.marche:
        if args.marche not in decp:
            print(f"  ❌ Marché {args.marche} introuvable dans la base DECP.")
            sys.exit(1)
        a_traiter = [args.marche]
        print(f"  Mode --marche : un seul marché ({args.marche})")
    else:
        a_traiter = []
        for id_m, marche in decp.items():
            if args.force or "volumes_extraits" not in marche:
                a_traiter.append(id_m)
        if args.limit:
            a_traiter = a_traiter[:args.limit]
        deja_fait = len(decp) - len([m for m in decp.values()
                                        if "volumes_extraits" not in m])
        print(f"  Déjà extraits : {deja_fait} / {len(decp)}")
        print(f"  À évaluer ce run : {len(a_traiter)}")

        # Stats du filtre métier
        if not args.no_filtre:
            nb_pertinents = sum(1 for id_m in a_traiter
                                if _est_pertinent(decp[id_m]))
            nb_exclus_filtre = len(a_traiter) - nb_pertinents
            print(f"    ├─ filtrés métier (sans API) : {nb_exclus_filtre}")
            print(f"    └─ envoyés à l'API           : {nb_pertinents}")
        else:
            print(f"    (filtre métier désactivé via --no-filtre)")

    if not a_traiter:
        print()
        print("  ✓ Rien à faire. Tous les marchés ont déjà été traités.")
        print("  (Relance avec --force pour tout re-extraire.)")
        return

    # Dry-run : on s'arrête là après le décompte
    if args.dry_run:
        print()
        nb_api = sum(1 for id_m in a_traiter
                     if args.no_filtre or _est_pertinent(decp[id_m]))
        # Estimation coût pour les marchés réellement envoyés à l'API
        cout_estime = (nb_api * 400 * PRIX_IN_PAR_MTOK
                       + nb_api * 150 * PRIX_OUT_PAR_MTOK) / 1_000_000
        print(f"  [dry-run] {nb_api} marchés seraient envoyés à l'API.")
        print(f"  Coût estimé : ~{cout_estime:.2f} $")
        return

    # Vérification SDK + clé API
    if Anthropic is None:
        print()
        print("  ❌ SDK anthropic absent. Lance : pip install anthropic")
        sys.exit(1)
    if not _obtenir_cle_api():
        print()
        print("  ❌ Clé API absente. Définis ANTHROPIC_API_KEY dans .env "
              "ou comme variable d'environnement.")
        sys.exit(1)

    client = Anthropic()
    print(f"  Modèle : {MODELE}")
    print(f"  Sauvegarde sur disque toutes les {SAUVEGARDE_INTERVALLE} extractions")
    print()
    print("-" * 70)

    # Boucle principale
    debut = time.time()
    total_in = 0
    total_out = 0
    nb_ok = 0
    nb_skip = 0
    nb_fail = 0
    nb_filtre_metier = 0

    for i, id_m in enumerate(a_traiter, 1):
        marche = decp[id_m]
        objet_court = (marche.get("objet") or "").strip()[:60].replace("\n", " ")
        progress = f"[{i:4d}/{len(a_traiter)}]"

        # FILTRE MÉTIER : si hors périmètre (formation/insertion), on marque
        # exclu sans appeler l'API.
        if not args.no_filtre and not _est_pertinent(marche):
            cat = marche.get("categorie_metier") or "?"
            cpv = marche.get("cpv_principal") or "?"
            marche["volumes_extraits"] = {
                "nb_beneficiaires": None,
                "duree_heures_parcours": None,
                "prestation_precise": None,
                "public_cible": None,
                "modalite": None,
                "confiance": "exclu_filtre",
                "_meta": {
                    "raison_skip": (
                        f"hors périmètre métier "
                        f"(categorie_metier='{cat}', cpv='{cpv}' hors whitelist "
                        f"formation/insertion)"
                    ),
                    "filtre_version": "v1",
                    "date_extraction": datetime.now(timezone.utc).isoformat(),
                },
            }
            nb_filtre_metier += 1
            if i <= 20 or i % 50 == 0:  # limite le bruit terminal
                print(f"  {progress} ⊘ {id_m}  exclu filtre  (cat={cat}, cpv={cpv})")
            if i % SAUVEGARDE_INTERVALLE == 0:
                _sauver_decp(decp)
            continue

        # APPEL API
        result = _extraire_un_marche(client, marche, verbose=True)
        if result is None:
            nb_fail += 1
            print(f"  {progress} ❌ {id_m}  échec")
            continue

        meta = result.get("_meta", {})
        if "raison_skip" in meta:
            nb_skip += 1
            print(f"  {progress} ⊘ {id_m}  {meta['raison_skip']}")
        else:
            nb_ok += 1
            total_in += meta.get("tokens_in", 0)
            total_out += meta.get("tokens_out", 0)
            conf = result.get("confiance", "?")
            nb = result.get("nb_beneficiaires")
            pr = result.get("prestation_precise")
            print(f"  {progress} ✓ {id_m}  conf={conf:<7s}  "
                  f"nb_benef={str(nb):<6s}  prest={pr}  | {objet_court}")

        # Insère dans la base
        marche["volumes_extraits"] = result

        # Sauvegarde périodique
        if i % SAUVEGARDE_INTERVALLE == 0:
            _sauver_decp(decp)
            cout_courant = (total_in * PRIX_IN_PAR_MTOK
                            + total_out * PRIX_OUT_PAR_MTOK) / 1_000_000
            print(f"    💾 Sauvegarde ({i} traités · "
                  f"~{cout_courant:.2f}$ cumulé)")

    # Sauvegarde finale
    _sauver_decp(decp)

    duree_totale = time.time() - debut
    cout_total = (total_in * PRIX_IN_PAR_MTOK
                  + total_out * PRIX_OUT_PAR_MTOK) / 1_000_000

    print()
    print("-" * 70)
    print("  Résumé")
    print("-" * 70)
    print(f"    Marchés évalués        : {len(a_traiter)}")
    print(f"      ⊘ filtrés métier      : {nb_filtre_metier}  (sans appel API)")
    print(f"      ✓ extraits via API    : {nb_ok}")
    print(f"      ⊘ objets trop courts  : {nb_skip}")
    print(f"      ❌ échecs API          : {nb_fail}")
    print(f"    Tokens consommés       : in {total_in:,} / out {total_out:,}")
    print(f"    Coût total             : ~{cout_total:.3f} $")
    print(f"    Durée                  : {duree_totale:.0f} s "
          f"({duree_totale/max(1, nb_ok):.1f} s/marché extrait API)")
    print()
    print(f"  Base DECP enrichie : {FICHIER_DECP}")
    print(f"  Champ ajouté à chaque marché : volumes_extraits")
    print()


if __name__ == "__main__":
    main()
