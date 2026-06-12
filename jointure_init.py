"""
jointure_init.py
----------------
Script ONE-SHOT pour initialiser `data/jointure.json` à partir des marchés
BOAMP et DECP déjà présents dans la base.

À lancer une fois après le déploiement du module `jointure.py` et du patch
de `connecteurs/decp.py`.

Pour les marchés DECP existants en base AVANT le patch, la `reference_acheteur`
sera vide (le patch ne s'active qu'à la prochaine collecte DECP). Donc seuls
les marchés BOAMP donneront des entrées tant qu'on n'a pas relancé une collecte
DECP.

Usage :
    python jointure_init.py
    python jointure_init.py --verbose
"""

import argparse
import json
import sys
from pathlib import Path

import jointure

REPERTOIRE_BASE = Path(__file__).parent
REPERTOIRE_DATA = REPERTOIRE_BASE / "data"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    print("=" * 78)
    print("  INIT — Index de jointure BOAMP ↔ DECP")
    print("=" * 78)
    print()

    # 1. Marchés BOAMP en base
    fichier_boamp = REPERTOIRE_DATA / "marches.json"
    if fichier_boamp.is_file():
        with open(fichier_boamp, encoding="utf-8") as f:
            marches_boamp = json.load(f)
        boamp_total = sum(1 for m in marches_boamp.values()
                            if m.get("source") == "BOAMP")
        boamp_avec_ref = sum(1 for m in marches_boamp.values()
                                if m.get("source") == "BOAMP"
                                and m.get("reference_ft"))
        print(f"  Base BOAMP : {boamp_total} marchés, "
              f"{boamp_avec_ref} avec `reference_ft`")
    else:
        print(f"  ⚠ {fichier_boamp} introuvable")
        marches_boamp = {}

    # 2. Marchés DECP en base
    fichier_decp = REPERTOIRE_DATA / "marches_notifies.json"
    if fichier_decp.is_file():
        with open(fichier_decp, encoding="utf-8") as f:
            marches_decp = json.load(f)
        decp_avec_ref = sum(1 for m in marches_decp.values()
                              if m.get("reference_acheteur"))
        print(f"  Base DECP  : {len(marches_decp)} marchés, "
              f"{decp_avec_ref} avec `reference_acheteur`")
        if decp_avec_ref == 0:
            print(f"  ⚠ Aucun marché DECP n'a de `reference_acheteur` — "
                  f"normal si le patch de connecteurs/decp.py n'a pas")
            print(f"    encore été appliqué + relance `python tendia_decp.py`")
    else:
        print(f"  ⚠ {fichier_decp} introuvable")
        marches_decp = {}

    print()
    print("  → Synchronisation BOAMP…")
    stats_boamp = jointure.synchroniser_tous_boamp(marches_boamp,
                                                     verbose=args.verbose)
    print(f"    {stats_boamp['avec_ref']} entrées synchronisées, "
          f"{stats_boamp['sans_ref']} sans référence (ignorées)")

    print("  → Synchronisation DECP…")
    stats_decp = jointure.synchroniser_tous_decp(marches_decp,
                                                  verbose=args.verbose)
    print(f"    {stats_decp['avec_ref']} entrées synchronisées, "
          f"{stats_decp['sans_ref']} sans référence (ignorées)")

    print()
    print("=" * 78)
    print("  ÉTAT FINAL DE L'INDEX")
    print("=" * 78)
    s = jointure.stats()
    print(f"  Total entrées               : {s['total']}")
    print(f"  Paires complètes (B+D)      : {s['complet']}")
    print(f"  BOAMP seul (en attente DECP): {s['boamp_seul']}")
    print(f"  DECP seul (BOAMP introuvable): {s['decp_seul']}")

    if s["complet"] > 0:
        print()
        print("  Aperçu des paires complètes :")
        for entree in jointure.lister_paires_completes()[:5]:
            ref = entree.get("reference_acheteur")
            b = entree.get("boamp") or {}
            d = entree.get("decp") or {}
            print(f"    🔗 {ref}")
            print(f"       BOAMP {b.get('id')}  · publié {b.get('date_publication')}")
            print(f"       DECP  {d.get('id')}  · notifié {d.get('date_notification')}  · "
                  f"{d.get('montant_eur')} €  · {d.get('titulaire_nom')}")

    print()
    print(f"  Fichier : {jointure.FICHIER_JOINTURE}")


if __name__ == "__main__":
    main()
