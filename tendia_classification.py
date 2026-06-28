"""
tendia_classification.py
------------------------
Classification IA des marchés publics — Sprint 2 nouvelle architecture.

Pour CHAQUE marché ingéré (avec ou sans DCE), génère une étiquette métier
fiable à partir de titre + objet + CPV + acheteur. Ce n'est PAS un brief
d'analyse de marché (qui reste le rôle du brief COMPLET sur DCE), c'est
un tag de pré-tri qui remplace le matching keyword/CPV statique.

Coût : ~0,003 €/marché avec Haiku 4.5 (modèle par défaut).
       Pour 1000 marchés/mois : ~3 €/mois.

Schéma de sortie :
{
  "domaines_metier": [{"code": "...", "poids": 0.5?, "lots_concernes": [...]?}],
  "raison_classification": "1-2 phrases expliquant le choix",
  "synthese_courte": "1-2 phrases factuelles sur l'objet du marché"
}

Pipeline :
  1. Pré-filtre statique (gratuit) : rejette ContractAwardNotice, marchés expirés,
     CPV catastrophiques
  2. Appel LLM si non rejeté
  3. Stockage SQLite dans collection 'classifications_ia'

CLI :
    python tendia_classification.py                  # nouveaux marchés non classifiés
    python tendia_classification.py --backfill       # tous les marchés
    python tendia_classification.py --force          # recalcule même si déjà classifié
    python tendia_classification.py --id BOAMP-...   # test sur 1 marché
    python tendia_classification.py --limite 10      # max 10 marchés
    python tendia_classification.py --dry-run        # liste sans appeler le LLM
    python tendia_classification.py --modele sonnet  # force Sonnet (plus cher mais plus précis)
"""

import argparse
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPERTOIRE_BASE = Path(__file__).parent
CHEMIN_TAXONOMIE = REPERTOIRE_BASE / "presets" / "_taxonomie_domaines.json"
COLLECTION_CLASSIFICATIONS = "classifications_ia"

# Modèles supportés
# Haiku 4.5 : ~1$/5$ par M tokens → ~0,003 €/marché (suffisant pour classification)
# Sonnet 4.6 : ~3$/15$ par M tokens → ~0,01 €/marché (plus précis, pour cas litigieux)
MODELES = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-6",
}
MODELE_PAR_DEFAUT = "haiku"

# Pricing en USD per million tokens (pour estimer le coût)
PRICING = {
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
}

MAX_TOKENS_REPONSE = 800  # Largement suffisant pour la classification


# ---------------------------------------------------------------------------
# Pré-filtre statique (gratuit)
# ---------------------------------------------------------------------------

def pre_filtre_rejette(marche: dict) -> tuple:
    """
    Applique des règles statiques rapides pour rejeter les marchés clairement
    inutiles, AVANT toute analyse LLM.

    Returns:
        (True, "raison") si le marché doit être rejeté
        (False, "") sinon
    """
    # Règle 1 : avis d'attribution (ContractAwardNotice)
    # Ces marchés sont déjà attribués, aucun intérêt de candidater dessus
    donnees = marche.get("donnees") or {}
    if isinstance(donnees, str):
        try:
            donnees = json.loads(donnees)
        except Exception:
            donnees = {}
    type_notice = donnees.get("notice_type") or marche.get("type_notice") or ""
    if "ContractAwardNotice" in str(type_notice):
        return True, "ContractAwardNotice (avis d'attribution, marché déjà attribué)"

    # Aussi : nature_marche indique attribution
    nature = (marche.get("nature_marche") or "").lower()
    if "attribution" in nature or "award" in nature:
        return True, f"nature_marche = '{nature}'"

    # Règle 2 : date limite dépôt déjà passée
    date_limite = marche.get("date_limite_depot")
    if date_limite:
        try:
            # Tolère les formats avec/sans timezone
            if isinstance(date_limite, str):
                d = datetime.fromisoformat(date_limite.replace("Z", "+00:00"))
                if d.tzinfo is None:
                    d = d.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                if d < now:
                    return True, f"date_limite_depot expirée ({date_limite[:10]})"
        except Exception:
            # Format inattendu, on laisse passer
            pass

    return False, ""


# ---------------------------------------------------------------------------
# Chargement taxonomie
# ---------------------------------------------------------------------------

_TAXONOMIE_CACHE: Optional[dict] = None


def charger_taxonomie() -> dict:
    """Charge la taxonomie (cachée en mémoire)."""
    global _TAXONOMIE_CACHE
    if _TAXONOMIE_CACHE is not None:
        return _TAXONOMIE_CACHE
    if not CHEMIN_TAXONOMIE.is_file():
        raise FileNotFoundError(
            f"Taxonomie introuvable : {CHEMIN_TAXONOMIE}\n"
            f"Le fichier doit être déposé dans presets/_taxonomie_domaines.json."
        )
    _TAXONOMIE_CACHE = json.loads(CHEMIN_TAXONOMIE.read_text(encoding="utf-8"))
    return _TAXONOMIE_CACHE


# ---------------------------------------------------------------------------
# Construction du prompt
# ---------------------------------------------------------------------------

def _prompt_systeme() -> str:
    """
    Prompt système court ciblé classification.
    Inclut la taxonomie + règles + frontières piégeuses.
    """
    tax = charger_taxonomie()
    domaines = tax.get("domaines", {})

    lignes = [
        "Tu es un expert en analyse de marchés publics français.",
        "",
        "Ta SEULE mission ici : classer un marché public dans une taxonomie de "
        "domaines métier, à partir de son titre, objet, CPV et acheteur.",
        "",
        "Tu réponds UNIQUEMENT en JSON valide, sans préambule, sans bloc markdown.",
        "",
        "## TAXONOMIE DES DOMAINES MÉTIER",
        "",
        "Format de sortie pour `domaines_metier` :",
        "- Cas majoritaire (~80%) : UN SEUL domaine, sans poids ni lots_concernes.",
        "  Exemple : `[{\"code\": \"formation_pro_continue\"}]`",
        "- Marché multi-lots de métiers différents OU marché mixant explicitement "
        "plusieurs métiers : 2-3 domaines avec poids ∈ [0.05, 1.0], somme = 1.0.",
        "  Exemple : `[{\"code\": \"btp_gros_oeuvre\", \"poids\": 0.6, \"lots_concernes\": [1,2]}, "
        "{\"code\": \"btp_voirie_reseaux\", \"poids\": 0.4, \"lots_concernes\": [3]}]`",
        "- JAMAIS plus de 3 domaines. Si vraiment hors taxonomie, un seul : `autre`.",
        "- **CODES EXACTS — RÈGLE STRICTE** : le `code` doit être RECOPIÉ caractère pour "
        "caractère depuis la liste ci-dessous. N'invente AUCUNE variante orthographique "
        "(écris `energie_...`, JAMAIS `energia_...` ni `energy_...`), ne traduis pas, "
        "n'abrège pas, ne change pas les accents/underscores. Tout code absent de la "
        "liste est INVALIDE et sera rejeté.",
        "",
        "Liste des codes disponibles :",
        "",
    ]

    for code, info in domaines.items():
        libelle = info.get("libelle", code)
        desc = info.get("description", "")
        desc_court = desc.split('.')[0][:120] if desc else ""
        lignes.append(f"- `{code}` — {libelle}. {desc_court}.")

    lignes.extend([
        "",
        "## FRONTIÈRES PIÉGEUSES — ATTENTION PARTICULIÈRE",
        "",
        "- \"qualification\" : `formation_pro_continue` si qualification professionnelle ; "
        "`services_environnement_analyses` si qualification de zones (salles propres, environnement maîtrisé) ; "
        "`btp_renovation_rehabilitation` si requalification fonctionnelle d'espaces.",
        "- \"accompagnement\" : `formation_pro_continue` ou `insertion_professionnelle` si vers l'emploi ; "
        "`conseil_juridique` si juridique ; `conseil_strategie_organisation` si conseil stratégique ; "
        "`insertion_sociale_mediation` si action sociale.",
        "- \"rénovation\" : `energie_renovation_thermique` si dominante isolation/thermique ; "
        "`btp_renovation_rehabilitation` si rénovation patrimoniale sans dimension énergétique forte.",
        "- \"AMO\" : `energie_amo_etudes` si AMO énergétique ; `moe_architecte_urbanisme` si programmation/MOE ; "
        "`ingenierie_structure_genie_civil` si ingénierie technique pure.",
        "- \"analyses\" : `services_environnement_analyses` pour eau/air/sols/salles propres ; "
        "`services_sante_medical` pour biologie médicale HUMAINE uniquement.",
        "- \"médiation\" : `insertion_sociale_mediation` (action sociale).",
        "- \"chèques d'accompagnement / cartes cadeau\" : `prestations_speciales_titres_cheques`.",
        "- \"gardiennage\" : `securite_gardiennage` même si le bâtiment fait l'objet de rénovation énergétique.",
        "- \"restauration\" : `restauration_collective_prestations` si prestation déléguée ; "
        "`restauration_fournitures_alimentaires` si achat de denrées en gros sans prestation.",
        "- \"espaces verts\" : `amenagement_paysager_creation` si création/aménagement ; "
        "`amenagement_paysager_entretien` si entretien courant (tonte, taille, etc.).",
        "- **TRAVAUX vs ÉTUDES (distinction structurante)** : des TRAVAUX techniques "
        "(installation/pose de CVC, électricité, plomberie, courants faibles, fluides, génie "
        "climatique) relèvent du **BTP** (corps d'état), PAS d'un code `ingenierie_*`/`moe_*`. "
        "Les codes `ingenierie_*`/`moe_*` sont RÉSERVÉS aux missions D'ÉTUDES/CONCEPTION "
        "(maîtrise d'œuvre, bureau d'études, AMO études) SANS exécution de travaux. Indices "
        "BOAMP : « travaux de… / réalisation / fourniture et pose » → BTP ; « mission de "
        "maîtrise d'œuvre / étude / conception / AMO » → ingénierie/MOE. Si « nature = "
        "Travaux » dans l'avis, ne classe PAS en ingénierie sauf mission d'études explicite.",
        "- **ÉNERGIE — projet/AMO vs fourniture vs rénovation** : `energie_amo_developpement` "
        "(AMO/montage/développement de projet ENR), `energie_amo_etudes` (études techniques), "
        "`energie_pv_solaire`/`energie_eolien`/… (réalisation). FOURNITURE pure d'électricité/gaz "
        "(même « verte ») → `fourniture_*`/`autre`. Rénovation énergétique (travaux) = "
        "`energie_renovation_thermique` ; sa maîtrise d'œuvre = `moe_energetique_batiment`.",
        "- **MOE — quel type ?** : dimension ÉNERGÉTIQUE dominante → `moe_energetique_batiment` ; "
        "URBANISME/PLU/SCOT → `moe_urbanisme_amenagement` ; INFRASTRUCTURE/VRD/ouvrage d'art → "
        "`moe_infrastructure_vrd` ; MOE architecturale bâtiment classique → `moe_architecte_urbanisme`.",
        "- **INGÉNIERIE environnementale** : EAU/assainissement/GEMAPI → `ingenierie_eau_milieux` ; "
        "FAUNE-FLORE/biodiversité/Natura 2000 → `ingenierie_ecologie_biodiversite` ; étude "
        "d'IMPACT/ICPE/sites pollués/carbone → `ingenierie_environnementale`.",
        "- **BTP réseaux** : travaux de réseaux HUMIDES/SECS → `btp_reseaux_divers` ; "
        "voirie/chaussées → `btp_voirie_reseaux`.",
        "- **CONSEIL énergie** : conseil/stratégie/planification énergétique territoriale "
        "(PCAET, schéma directeur énergie) → `conseil_transition_energetique` ; AMO de projet "
        "ENR → `energie_amo_developpement` ; conseil organisation sans énergie → `conseil_strategie_organisation`.",
        "",
        "## IMPORTANT",
        "",
        "Tu n'as PAS accès au DCE — uniquement aux métadonnées BOAMP. C'est NORMAL.",
        "Si l'objet est vague ou ambigu, fais ta meilleure estimation et signale-le dans "
        "`raison_classification` (\"objet vague, classification incertaine\").",
        "N'invente PAS de détails que tu ne vois pas.",
    ])
    return "\n".join(lignes)


def _prompt_utilisateur(marche: dict) -> str:
    """Prompt utilisateur compact à partir des métadonnées BOAMP."""
    titre = marche.get("titre") or ""
    objet = marche.get("objet") or ""
    cpv = marche.get("cpv_principal") or ""
    cpv_secondaires = marche.get("cpv_secondaires") or []
    acheteur = marche.get("acheteur_nom") or ""
    perimetre = marche.get("perimetre_geographique") or ""
    nb_lots = marche.get("nb_lots")

    parts = ["Voici les métadonnées d'un marché public à classifier.", ""]
    if titre:
        parts.append(f"**TITRE** : {titre}")
    if objet and objet.strip() != titre.strip():
        parts.append(f"**OBJET** : {objet}")
    if cpv:
        parts.append(f"**CPV principal** : {cpv}")
    if cpv_secondaires:
        cpv_secs = ", ".join(cpv_secondaires[:5])
        parts.append(f"**CPV secondaires** : {cpv_secs}")
    if acheteur:
        parts.append(f"**ACHETEUR** : {acheteur}")
    if perimetre:
        parts.append(f"**PÉRIMÈTRE** : {perimetre}")
    if nb_lots and nb_lots > 1:
        parts.append(f"**NB LOTS** : {nb_lots}")

    parts.extend([
        "",
        "Retourne UNIQUEMENT ce JSON (pas de bloc markdown, pas de commentaire) :",
        "",
        "{",
        '  "domaines_metier": [',
        "    {",
        '      "code": "code_du_domaine_principal"',
        "    }",
        "  ],",
        '  "raison_classification": "1-2 phrases expliquant le choix du/des domaine(s), '
        'en citant les éléments qui ont guidé ta décision (objet, CPV, vocabulaire).",',
        '  "synthese_courte": "1-2 phrases factuelles décrivant ce que demande le marché."',
        "}",
    ])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Appel LLM
# ---------------------------------------------------------------------------

def _check_anthropic():
    """Délègue à llm_extract qui gère .env, .env.txt et BOM UTF-8."""
    try:
        import llm_extract
        llm_extract._check_anthropic()
    except ImportError:
        # Fallback minimal si llm_extract indisponible
        try:
            import anthropic  # noqa
        except ImportError:
            raise RuntimeError(
                "Le SDK Anthropic n'est pas installé. Lance : pip install anthropic"
            )
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY introuvable. Place-la dans .env à la racine de Tendia, "
                "ou définis la variable d'environnement."
            )


def classifier(marche: dict,
               modele: str = MODELE_PAR_DEFAUT,
               max_retries: int = 2,
               verbose: bool = False) -> Optional[dict]:
    """
    Classifie un marché via LLM.

    Args:
        marche: dict du marché (titre, objet, cpv_principal, acheteur_nom, ...)
        modele: 'haiku' (défaut, économe) ou 'sonnet' (plus précis)
        max_retries: tentatives en cas de JSON malformé
        verbose: log API

    Returns:
        dict avec domaines_metier, raison_classification, synthese_courte, _meta
        ou None si échec.
    """
    _check_anthropic()
    from anthropic import Anthropic

    modele_id = MODELES.get(modele, MODELES[MODELE_PAR_DEFAUT])
    client = Anthropic()

    prompt_sys = _prompt_systeme()
    prompt_user = _prompt_utilisateur(marche)

    debut = time.time()
    for tentative in range(1, max_retries + 1):
        try:
            if verbose:
                print(f"  → API {modele_id} tentative {tentative}")
            msg = client.messages.create(
                model=modele_id,
                max_tokens=MAX_TOKENS_REPONSE,
                system=prompt_sys,
                messages=[{"role": "user", "content": prompt_user}],
            )
            duree = time.time() - debut
            texte = msg.content[0].text if msg.content else ""

            in_t = msg.usage.input_tokens
            out_t = msg.usage.output_tokens
            pricing = PRICING.get(modele_id, PRICING[MODELES["haiku"]])
            cout_usd = (in_t * pricing["input"] + out_t * pricing["output"]) / 1_000_000
            cout_eur = cout_usd * 0.92  # taux indicatif USD→EUR
            if verbose:
                print(f"  ← {duree:.1f}s · {in_t}+{out_t} tokens · {cout_eur:.4f} €")

            # Parser le JSON (tolérance markdown)
            texte_clean = texte.strip()
            if texte_clean.startswith("```"):
                texte_clean = re.sub(r"^```(?:json)?\n", "", texte_clean)
                texte_clean = re.sub(r"\n```$", "", texte_clean)

            try:
                resultat = json.loads(texte_clean)
            except json.JSONDecodeError:
                # Tentative d'extraction du premier objet JSON
                m = re.search(r"\{.*\}", texte_clean, re.DOTALL)
                if not m:
                    if tentative >= max_retries:
                        if verbose:
                            print(f"  ⚠ Aucun JSON trouvé après {max_retries} essais")
                            print(f"    Début : {texte[:200]}")
                        return None
                    continue
                try:
                    resultat = json.loads(m.group(0))
                except json.JSONDecodeError:
                    if tentative >= max_retries:
                        return None
                    continue

            # Validation basique : domaines_metier doit être une liste non vide
            doms = resultat.get("domaines_metier")
            if not isinstance(doms, list) or not doms:
                if verbose:
                    print(f"  ⚠ Réponse sans domaines_metier valide")
                if tentative >= max_retries:
                    return None
                continue

            # Métadonnées
            resultat["_meta"] = {
                "modele": modele_id,
                "date": datetime.now(timezone.utc).isoformat(),
                "input_tokens": in_t,
                "output_tokens": out_t,
                "cout_eur": round(cout_eur, 6),
                "duree_s": round(duree, 2),
            }
            return resultat

        except Exception as e:
            if verbose:
                print(f"  ⚠ Erreur tentative {tentative} : {type(e).__name__}: {e}")
            if tentative >= max_retries:
                return None
    return None


# ---------------------------------------------------------------------------
# Stockage SQLite
# ---------------------------------------------------------------------------

def charger_classifications() -> dict:
    """Charge la collection classifications_ia depuis SQLite."""
    return stockage.charger(COLLECTION_CLASSIFICATIONS) or {}


def sauver_classification(marche_id: str, classification: dict) -> None:
    """Persiste une classification."""
    classifs = charger_classifications()
    classifs[marche_id] = classification
    stockage.sauver(COLLECTION_CLASSIFICATIONS, classifs)


def supprimer_classification(marche_id: str) -> None:
    """Supprime la classification d'un marché."""
    classifs = charger_classifications()
    if marche_id in classifs:
        del classifs[marche_id]
        stockage.sauver(COLLECTION_CLASSIFICATIONS, classifs)


# ---------------------------------------------------------------------------
# Pipeline complet (marche par marche)
# ---------------------------------------------------------------------------

def classifier_un_marche(marche_id: str,
                          marche: dict,
                          modele: str = MODELE_PAR_DEFAUT,
                          force: bool = False,
                          verbose: bool = False) -> dict:
    """
    Pipeline complet pour un marché : pré-filtre → classification → stockage.

    Returns:
        dict avec 'statut' parmi : 'classifié', 'rejeté', 'déjà_classifié', 'échec'
        + détails selon le cas.
    """
    # Cache check
    if not force:
        classifs = charger_classifications()
        if marche_id in classifs:
            return {
                "statut": "déjà_classifié",
                "classification": classifs[marche_id],
            }

    # Pré-filtre
    rejette, raison = pre_filtre_rejette(marche)
    if rejette:
        return {
            "statut": "rejeté",
            "raison_rejet": raison,
        }

    # Classification LLM
    classification = classifier(marche, modele=modele, verbose=verbose)
    if not classification:
        return {"statut": "échec"}

    # Stockage
    classification["marche_id"] = marche_id
    sauver_classification(marche_id, classification)

    return {
        "statut": "classifié",
        "classification": classification,
    }


def _resume_classification(classif: dict) -> str:
    """Ligne synthétique pour log."""
    if not classif:
        return "(vide)"
    doms = classif.get("domaines_metier") or []
    if not doms:
        return "(pas de domaine)"
    if len(doms) == 1:
        code = doms[0].get("code", "?")
        return code
    parts = []
    for d in doms:
        c = d.get("code", "?")
        p = d.get("poids")
        if p:
            parts.append(f"{c} ({int(p*100)}%)")
        else:
            parts.append(c)
    return " + ".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Classification IA des marchés publics (Sprint 2 nouvelle archi)."
    )
    ap.add_argument("--id", action="append", dest="ids", default=None,
                    metavar="BOAMP-26-XXXXX",
                    help="Limite à un (ou plusieurs --id) marché(s) spécifique(s).")
    ap.add_argument("--backfill", action="store_true",
                    help="Traite TOUS les marchés en base (par défaut : seulement "
                         "ceux non encore classifiés).")
    ap.add_argument("--force", action="store_true",
                    help="Re-classifie même si déjà classifié (ignore le cache).")
    ap.add_argument("--limite", type=int, default=None,
                    help="Maximum de marchés à traiter dans cette passe.")
    ap.add_argument("--max-cout", type=float, default=None, metavar="EUR",
                    help="Garde-fou : stoppe si coût LLM cumulé dépasse ce montant.")
    ap.add_argument("--modele", choices=["haiku", "sonnet"],
                    default=MODELE_PAR_DEFAUT,
                    help=f"Modèle LLM (défaut: {MODELE_PAR_DEFAUT}). "
                         "haiku ≈ 0,003 €/marché, sonnet ≈ 0,01 €/marché.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Liste les cibles sans appeler le LLM.")
    ap.add_argument("--verbose", action="store_true",
                    help="Log détaillé par appel API.")
    args = ap.parse_args()

    print("=" * 78)
    print("  Tendia · Classification IA des marchés")
    print("=" * 78)

    # Chargement
    marches = stockage.charger("marches") or {}
    classifs_existantes = charger_classifications()

    print(f"\n  Marchés en base       : {len(marches)}")
    print(f"  Déjà classifiés       : {len(classifs_existantes)}")
    print(f"  Modèle                : {MODELES[args.modele]} "
          f"(coût estimé ~{0.003 if args.modele=='haiku' else 0.01:.3f} €/marché)")

    # Sélection des cibles
    if args.ids:
        cibles = [(i, marches[i]) for i in args.ids if i in marches]
        absents = [i for i in args.ids if i not in marches]
        if absents:
            print(f"  ⚠ IDs absents en base : {', '.join(absents)}")
    elif args.backfill:
        cibles = list(marches.items())
    else:
        # Par défaut : marchés non classifiés
        cibles = [(i, m) for (i, m) in marches.items()
                  if i not in classifs_existantes]

    if args.limite:
        cibles = cibles[:args.limite]

    print(f"  Cibles à traiter      : {len(cibles)}")
    if args.force:
        print(f"  Mode FORCE : recalcul même si déjà classifié")
    if args.dry_run:
        print(f"  Mode DRY-RUN : aucun appel API")

    if not cibles:
        print(f"\n  ✓ Rien à faire.")
        return

    # Estimation budgétaire
    cout_unitaire_estime = 0.003 if args.modele == "haiku" else 0.01
    cout_max_estime = len(cibles) * cout_unitaire_estime
    print(f"\n  Coût estimé maximum   : {cout_max_estime:.2f} €")
    if args.max_cout:
        print(f"  Garde-fou             : stop à {args.max_cout:.2f} €")

    if args.dry_run:
        print(f"\n  ── Cibles (DRY-RUN) ──")
        # Pré-filtre stat
        n_rejet_avant_llm = 0
        for id_m, m in cibles[:50]:  # premiers 50 pour aperçu
            rejette, raison = pre_filtre_rejette(m)
            if rejette:
                n_rejet_avant_llm += 1
        n_rejet_total = sum(
            1 for _, m in cibles
            if pre_filtre_rejette(m)[0]
        )
        n_a_classifier = len(cibles) - n_rejet_total
        cout_reel_estime = n_a_classifier * cout_unitaire_estime
        print(f"  Pré-filtre rejettera   : {n_rejet_total} marchés (gratuit)")
        print(f"  LLM sera appelé sur    : {n_a_classifier} marchés")
        print(f"  Coût réel estimé       : {cout_reel_estime:.2f} €")
        return

    # Exécution
    print(f"\n  Classification en cours...")
    print(f"  {'─' * 72}")

    nb_classifies = 0
    nb_rejetes = 0
    nb_deja = 0
    nb_echecs = 0
    cout_cumule = 0.0
    debut_run = time.time()

    for i, (id_m, m) in enumerate(cibles, 1):
        titre = (m.get("titre") or "?")[:50]

        # Garde-fou coût
        if args.max_cout and cout_cumule >= args.max_cout:
            print(f"\n  ⚠ Garde-fou coût atteint ({cout_cumule:.2f} € >= "
                  f"{args.max_cout:.2f} €), arrêt.")
            break

        # Bandeau d'avancement compact toutes les 25 entrées
        if i % 25 == 1 and i > 1:
            elapsed = time.time() - debut_run
            rate = i / elapsed if elapsed > 0 else 0
            eta_s = (len(cibles) - i) / rate if rate > 0 else 0
            print(f"  [{i}/{len(cibles)}] cumul : "
                  f"{nb_classifies}✓ {nb_rejetes}⊘ {nb_echecs}✗ · "
                  f"{cout_cumule:.2f}€ · ETA ~{int(eta_s/60)}min")

        resultat = classifier_un_marche(
            id_m, m,
            modele=args.modele,
            force=args.force,
            verbose=args.verbose,
        )

        statut = resultat["statut"]
        if statut == "classifié":
            nb_classifies += 1
            classif = resultat["classification"]
            cout = classif["_meta"]["cout_eur"]
            cout_cumule += cout
            doms_str = _resume_classification(classif)
            print(f"    ✓ [{i}/{len(cibles)}] {id_m}  {doms_str}")
        elif statut == "rejeté":
            nb_rejetes += 1
            if args.verbose:
                print(f"    ⊘ [{i}/{len(cibles)}] {id_m}  PRÉ-FILTRE: {resultat['raison_rejet']}")
        elif statut == "déjà_classifié":
            nb_deja += 1
            if args.verbose:
                classif = resultat["classification"]
                doms_str = _resume_classification(classif)
                print(f"    = [{i}/{len(cibles)}] {id_m}  déjà : {doms_str}")
        elif statut == "échec":
            nb_echecs += 1
            print(f"    ✗ [{i}/{len(cibles)}] {id_m}  {titre[:30]} (échec API)")

    # Synthèse
    duree_totale = time.time() - debut_run
    print(f"\n  {'─' * 72}")
    print(f"  Synthèse :")
    print(f"    ✓ Classifiés (nouveaux)    : {nb_classifies}")
    print(f"    ⊘ Rejetés (pré-filtre)     : {nb_rejetes}")
    print(f"    = Déjà classifiés (skip)   : {nb_deja}")
    print(f"    ✗ Échecs API               : {nb_echecs}")
    print(f"  Coût LLM cumulé             : {cout_cumule:.3f} €")
    print(f"  Durée totale                : {int(duree_totale)}s")
    if nb_classifies > 0:
        print(f"  Coût moyen par classification : "
              f"{cout_cumule/nb_classifies:.4f} €")
    print()

    if nb_classifies > 0:
        print(f"  Pour auditer les classifications obtenues :")
        print(f"    python audit_classifications.py")


if __name__ == "__main__":
    main()
