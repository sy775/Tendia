"""
retelecharger_incomplet.py
--------------------------
Re-télécharge les marchés `dce_contenu == "incomplet"` via le téléchargeur
profond (toutes les pièces), puis re-qualifie. Backup du dossier DCE avant
écrasement. Idempotent (ne traite que les `incomplet`).

Nécessite réseau. Usage : python retelecharger_incomplet.py
Rate-limit : 2 s entre marchés.
"""
import io
import os
import shutil
import sys
import time
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import tendia_dce
import http_humain
import tendia_telecharger_dce as T

# Rate-limit randomisé (anti-ban léger, uniformisation). Atexo n'a pas montré
# de ban : ~10 s en moyenne.
RATE_LIMIT_MOYEN_SEC = 10
RATE_LIMIT_MIN_SEC = 5
RATE_LIMIT_MAX_SEC = 25


def main():
    marches = stockage.charger("marches") or {}
    cibles = [(mid, m) for mid, m in sorted(marches.items())
              if m.get("dce_contenu") == "incomplet"]

    print("=== RE-TÉLÉCHARGEMENT CIBLÉ (téléchargeur profond) ===")
    print(f"Cibles : {len(cibles)} marchés incomplet\n")
    if not cibles:
        print("Rien à faire.")
        return

    bilan = Counter()
    gains = []  # (mid, pieces avant, pieces après)

    for i, (mid, marche) in enumerate(cibles, 1):
        dossier = os.path.join(str(T.REPERTOIRE_DCE), mid)
        bak = os.path.join(str(T.REPERTOIRE_DCE), f"{mid}.bak_avant_reprofond")
        pieces_avant = marche.get("dce_pieces_contractuelles") or []
        if os.path.isdir(dossier) and not os.path.isdir(bak):
            try:
                shutil.copytree(dossier, bak)
            except Exception as e:
                print(f"  ⚠ backup {mid} échoué : {e}")

        res = T.telecharger_pieces_dce(marche, dossier)
        qual = tendia_dce.qualifier_dce(dossier)
        nouveau = qual["qualite"]
        bilan[f"incomplet → {nouveau}"] += 1
        if nouveau == "complet":
            gains.append((mid, pieces_avant, qual["pieces_contractuelles"]))

        marche["dce_contenu"] = nouveau
        marche["dce_pieces_contractuelles"] = qual["pieces_contractuelles"]
        marche["dce_pieces_manquantes"] = res.get("pieces_manquantes", [])
        marche["dce_raison_contenu"] = qual["raison"]
        marche["dce_telecharge_le"] = datetime.now().isoformat()
        stockage.ecrire("marches", mid, marche)

        print(f"  [{i}/{len(cibles)}] {mid} : incomplet → {nouveau} "
              f"({len(res.get('pieces_recuperees', []))} pièces récupérées, "
              f"{len(res.get('pieces_manquantes', []))} manquantes)")
        if i < len(cibles):
            http_humain.attendre_humain(
                RATE_LIMIT_MIN_SEC, RATE_LIMIT_MAX_SEC,
                mu=RATE_LIMIT_MOYEN_SEC, sigma=4, verbose=True)

    print("\nBilan :")
    for b, n in bilan.most_common():
        print(f"  {b:<26} : {n}")

    if gains:
        print(f"\nMarchés ayant gagné des pièces ({len(gains)}) :")
        for mid, av, ap in gains[:30]:
            print(f"  {mid} : {av or ['RC']} → {ap}")

    print(f"\n⇒ {bilan.get('incomplet → complet', 0)} marchés passés à complet "
          f"(briefs à re-extraire : python reextraire_briefs_complet.py)")


if __name__ == "__main__":
    main()
