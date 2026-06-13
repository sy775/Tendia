"""
tester_sprint2bis.py
--------------------
Validation a blanc du routage par classification IA (Sprint 2bis).

Aucun appel LLM. Pour chaque marche cible, affiche :
- la classification IA actuelle
- les presets cibles deduits (routage)
- la taille du prompt utilisateur en mode legacy union vs routage cible
- la presence ou absence de vestiges formation/France Travail

Usage PowerShell :
    python tester_sprint2bis.py
    python tester_sprint2bis.py --id BOAMP-26-56096
    python tester_sprint2bis.py --tous

Pas d'unicode dans les prints (compat cp1252 PowerShell).
"""
import argparse
import io
import sys

# Force UTF-8 stdout pour eviter les soucis cp1252 quand on print du JSON
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json

import llm_extract
import preset as _preset
import stockage


# 3 marches cibles representatifs de secteurs differents
CIBLES_DEFAUT = [
    ("BOAMP-26-56096", "MOE rehabilitation pont Lot-et-Garonne (ingenierie/BTP)"),
    ("BOAMP-26-56164", "Diffusion numerique DILA (IT classifie)"),
    ("BOAMP-26-56055", "Concession baches publicitaires Centre Pompidou (conseil)"),
    ("BOAMP-26-56170", "Maintenance groupes electrogenes CHU Angers (IT par defaut)"),
    ("BOAMP-26-56172", "Veille medias CNAF (conseil_communication)"),
    ("BOAMP-26-56116", "Maquettage stats Ministere Interieur (conseil)"),
]

# Vestiges formation/France Travail a tracker dans le prompt
VESTIGES_KEYS = [
    "Methodologie pedagogique",
    "Approche pedagogique",
    "Suivi individualise",
    "Qualiopi (art",
    "Nouvelle-Aquitaine",
    "200 DE accompagn",
    "Partenariat formalise avec 15",
    "employeurs locaux",
    "insertion DE seniors",
    "MWc installes cumules",
    "stagiaire",
    "Activ Seniors",
]


def _normaliser(t: str) -> str:
    """Approximation ASCII pour matcher les vestiges (le prompt contient
    accents, le tracker ASCII)."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", t)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def analyser_marche(marche_id: str, label: str = ""):
    print()
    print("=" * 80)
    print(f"  {marche_id}")
    if label:
        print(f"  {label}")
    print("=" * 80)

    # 1. Classification IA
    classifs = stockage.charger("classifications_ia") or {}
    classif = classifs.get(marche_id) or {}
    domaines = classif.get("domaines_metier") or []
    codes_dom = [d.get("code") for d in domaines if isinstance(d, dict)]
    print(f"  Classif IA      : {codes_dom}")
    if classif.get("raison_classification"):
        rc = classif["raison_classification"].replace("\n", " ")
        print(f"    raison        : {rc[:160]}")

    # 2. Resolution presets
    presets_cibles = llm_extract._resoudre_presets_pour_marche(marche_id)
    print(f"  Presets cibles  : {presets_cibles if presets_cibles else '[]  -> fallback union complete'}")

    # 3. Construction prompts (sans appel LLM)
    contexte_str = '{"id": "' + marche_id + '"}'
    texte_dummy = "DCE texte de test " * 100  # ~1800 chars, juste pour le rendu

    pu_legacy = llm_extract._construire_prompt_utilisateur(contexte_str, texte_dummy, None)
    pu_cible = llm_extract._construire_prompt_utilisateur(contexte_str, texte_dummy, presets_cibles)
    ps_legacy = llm_extract._construire_prompt_systeme(None)
    ps_cible = llm_extract._construire_prompt_systeme(presets_cibles)

    print()
    print(f"  Prompt utilisateur :")
    print(f"    legacy union complete : {len(pu_legacy):>6} chars (~ {len(pu_legacy)//4:>5} tokens)")
    print(f"    routage cible         : {len(pu_cible):>6} chars (~ {len(pu_cible)//4:>5} tokens)")
    delta_pu = len(pu_legacy) - len(pu_cible)
    pct_pu = (100.0 * delta_pu / len(pu_legacy)) if len(pu_legacy) else 0
    print(f"    delta                 : {delta_pu:>+6} chars  ({pct_pu:+.1f}%)")

    print(f"  Prompt systeme :")
    print(f"    legacy preset actif   : {len(ps_legacy):>6} chars")
    print(f"    routage cible         : {len(ps_cible):>6} chars")
    # Ligne d'orientation du prompt systeme
    premiere_ligne_cible = ps_cible.split("\n")[0]
    print(f"    orientation cible     : {premiere_ligne_cible[:120]}")

    # 4. Vestiges formation
    pu_cible_norm = _normaliser(pu_cible).lower()
    pu_legacy_norm = _normaliser(pu_legacy).lower()
    detectes_cible = []
    detectes_legacy = []
    for v in VESTIGES_KEYS:
        v_norm = _normaliser(v).lower()
        if v_norm in pu_cible_norm:
            detectes_cible.append(v)
        if v_norm in pu_legacy_norm:
            detectes_legacy.append(v)

    print()
    print(f"  Vestiges formation/FT dans prompt utilisateur :")
    print(f"    legacy union : {len(detectes_legacy)} -> {detectes_legacy if detectes_legacy else 'aucun'}")
    print(f"    routage cible: {len(detectes_cible)} -> {detectes_cible if detectes_cible else 'aucun'}")


def main():
    ap = argparse.ArgumentParser(description="Test a blanc du routage par classif IA")
    ap.add_argument("--id", help="ID d'un marche specifique a analyser")
    ap.add_argument("--tous", action="store_true",
                    help="Analyse les 6 marches cibles par defaut")
    args = ap.parse_args()

    if args.id:
        analyser_marche(args.id, label="(marche specifie en CLI)")
    else:
        # Par defaut : les 6 cibles representatives
        for mid, label in CIBLES_DEFAUT:
            analyser_marche(mid, label=label)

    print()
    print("=" * 80)
    print("  RESUME")
    print("=" * 80)
    print("  - Si presets cibles non vide -> routage actif, prompt allege")
    print("  - Si presets cibles vide -> fallback union complete (marche")
    print("    classifie en domaine hors-preset : autre, fourniture_materiel,")
    print("    assurance, entretien_proprete_locaux, etc.)")
    print()
    print("  Prochain pas : regen reelle via")
    print("    python enrichir_complet.py --id BOAMP-26-XXXX --force --max-cout 1.0")


if __name__ == "__main__":
    main()
