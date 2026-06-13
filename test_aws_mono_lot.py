"""
test_aws_mono_lot.py
--------------------
Teste les 2 marchés AWS-Achat qui avaient échoué en mono-lot avant le
patch lots_mono. Nettoie les dossiers DCE existants pour éviter le skip.

Coût : ~0.002€ (2 captchas).

Lance : python test_aws_mono_lot.py
"""
import io
import os
import sys
import shutil
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import aws_downloader as A


CIBLES = ["BOAMP-26-56599", "BOAMP-26-57188"]


def main():
    marches = stockage.charger("marches")
    resultats = []

    for mid in CIBLES:
        marche = marches.get(mid)
        if not marche:
            print(f"  {mid} : non trouve en base, skip")
            continue

        print()
        print("=" * 60)
        print(f"TEST : {mid}")
        print(f"  Titre : {(marche.get('titre') or '')[:80]}")
        print("=" * 60)

        # Nettoyer le dossier existant pour ne pas skip
        dossier = os.path.join("data", "dce", mid)
        if os.path.isdir(dossier):
            print(f"  Nettoyage dossier existant : {dossier}")
            shutil.rmtree(dossier)

        # Tenter le téléchargement
        try:
            res = A.telecharger_dce_pour_marche(marche, "data/dce", verbose=True)
        except Exception as e:
            res = {"ok": False, "erreur": f"{type(e).__name__}: {e}",
                   "etape_erreur": "exception"}

        resultats.append((mid, res))

        statut = "OK" if res.get("ok") else "ECHEC"
        nb_fichiers = res.get("fichiers_telecharges", 0)
        if isinstance(nb_fichiers, list):
            nb_fichiers = len(nb_fichiers)
        print()
        print(f"  >>> {statut} : fichiers={nb_fichiers}, "
              f"taille={res.get('taille_octets_total', 0):,} octets, "
              f"etape_erreur={res.get('etape_erreur', '-')}")
        if res.get("erreur"):
            print(f"  >>> erreur : {res['erreur'][:200]}")

        # Pause entre marchés
        if mid != CIBLES[-1]:
            print()
            print("  Pause 5 sec entre marches...")
            time.sleep(5)

    # Bilan
    print()
    print("=" * 60)
    print("BILAN")
    print("=" * 60)
    for mid, res in resultats:
        statut = "OK" if res.get("ok") else f"ECHEC ({res.get('etape_erreur','?')})"
        print(f"  {mid} : {statut}")


if __name__ == "__main__":
    main()
