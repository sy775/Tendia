"""
diagnostic_desync_dce.py
------------------------
Vérifie la cohérence entre les marqueurs `dce_telechargement_statut='ok'`
en base SQLite et la réalité du disque dans data/dce/<id>/.

Affiche pour chaque catégorie :
  - ok_et_coherent           : statut OK + dossier présent avec fichiers utiles
  - ok_mais_dossier_absent   : statut OK mais le dossier a disparu du disque
  - ok_mais_dossier_vide     : statut OK mais dossier vide
  - ok_mais_que_bruit        : statut OK mais ne reste que des fichiers génériques
"""

import io
import sys
from collections import Counter
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import stockage
import tendia_telecharger_dce as t


REP_DCE = Path(__file__).parent / "data" / "dce"


def main():
    marches = stockage.charger("marches")
    print(f"Marchés en base : {len(marches)}")

    desync = Counter()
    exemples = {k: [] for k in (
        "ok_mais_dossier_absent",
        "ok_mais_dossier_vide",
        "ok_mais_que_bruit",
    )}

    for id_m, m in marches.items():
        statut = m.get("dce_telechargement_statut")
        if statut != "ok":
            continue
        dossier = REP_DCE / id_m
        if not dossier.is_dir():
            desync["ok_mais_dossier_absent"] += 1
            if len(exemples["ok_mais_dossier_absent"]) < 5:
                exemples["ok_mais_dossier_absent"].append(id_m)
            continue
        fichiers = [f.name for f in dossier.iterdir() if f.is_file()]
        if not fichiers:
            desync["ok_mais_dossier_vide"] += 1
            if len(exemples["ok_mais_dossier_vide"]) < 5:
                exemples["ok_mais_dossier_vide"].append(id_m)
            continue
        utiles = [n for n in fichiers if not t._est_fichier_bruit(n)]
        if not utiles:
            desync["ok_mais_que_bruit"] += 1
            if len(exemples["ok_mais_que_bruit"]) < 5:
                exemples["ok_mais_que_bruit"].append((id_m, fichiers))
            continue
        desync["ok_et_coherent"] += 1

    print()
    print("=== Bilan ===")
    for k, v in desync.most_common():
        print(f"  {v:4d}  {k}")

    print()
    if exemples["ok_mais_dossier_absent"]:
        print("Exemples ok_mais_dossier_absent :")
        for e in exemples["ok_mais_dossier_absent"]:
            print(f"  · {e}")
    if exemples["ok_mais_dossier_vide"]:
        print("Exemples ok_mais_dossier_vide :")
        for e in exemples["ok_mais_dossier_vide"]:
            print(f"  · {e}")
    if exemples["ok_mais_que_bruit"]:
        print("Exemples ok_mais_que_bruit :")
        for e, f in exemples["ok_mais_que_bruit"]:
            print(f"  · {e} -> {f}")


if __name__ == "__main__":
    main()
