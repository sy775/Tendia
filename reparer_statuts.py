"""
reparer_statuts.py
------------------
Correction d'un bug introduit par nettoyer_dce_faux_succes.py (premier run) :
les 238 marchés SANS url_dce ont été marqués `dce_telechargement_statut=echec`
avec raison `dossier_vide_nettoye`. Or, ils n'ont jamais été testés par le
téléchargeur (qui skip les marchés sans url_dce). Ils devraient être en
`jamais_tente` (statut absent).

Ce script :
1. Trouve les marchés en `dossier_vide_nettoye` SANS url_dce → réinitialise leur
   statut (supprime tous les champs `dce_telechargement_*`).
2. Renomme la raison `dossier_vide_nettoye` en `dossier_vide_apres_test` pour
   les marchés AVEC url_dce (statut echec préservé, raison plus parlante).

Sans risque, idempotent.

Usage :
    python reparer_statuts.py --dry-run    # voir ce qui serait fait
    python reparer_statuts.py              # appliquer
"""

import argparse
import io
import sys
from collections import Counter

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage


CHAMPS_DCE_TELECHARGEMENT = (
    "dce_telechargement_statut",
    "dce_telechargement_raison",
    "dce_telechargement_nb_fichiers",
    "dce_telechargement_date",
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    marches = stockage.charger("marches")

    nb_reinit = 0
    nb_renomme = 0

    for id_m, m in marches.items():
        if m.get("dce_telechargement_statut") != "echec":
            continue
        raison = m.get("dce_telechargement_raison") or ""
        if "dossier_vide_nettoye" not in raison:
            continue

        if not m.get("url_dce"):
            # Cas 1 : sans url_dce → réinitialiser complètement
            for champ in CHAMPS_DCE_TELECHARGEMENT:
                if champ in m:
                    del m[champ]
            nb_reinit += 1
        else:
            # Cas 2 : avec url_dce → renommer la raison
            m["dce_telechargement_raison"] = "dossier_vide_apres_test"
            nb_renomme += 1

    print("=" * 70)
    print("  Réparation des statuts de téléchargement DCE")
    print("=" * 70)
    print(f"  Marchés réinitialisés (sans url_dce → jamais_tente) : {nb_reinit}")
    print(f"  Marchés raison renommée (avec url_dce, echec gardé) : {nb_renomme}")

    if args.dry_run:
        print()
        print("  Mode dry-run : aucune écriture en base.")
        return

    stockage.sauver("marches", marches)
    print()
    print("  ✓ Base SQLite mise à jour.")

    # Bilan final
    print()
    print("  Distribution finale des statuts :")
    statuts = Counter()
    for m in marches.values():
        statuts[m.get("dce_telechargement_statut") or "(jamais_tente)"] += 1
    for s, n in statuts.most_common():
        print(f"    {n:4d}  {s}")


if __name__ == "__main__":
    main()
