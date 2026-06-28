"""
retelecharger_xmarches.py
-------------------------
Batch de récupération du DCE sur xmarches.fr (moteur custom + 2captcha), sur le
modèle des autres connecteurs dédiés. Cible les marchés xmarches non-complet,
télécharge via xmarches_downloader, re-qualifie et persiste dce_contenu.

Usage : python retelecharger_xmarches.py [--oui] [--max N]
"""
import argparse
import os
import sys
import time
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from dotenv import load_dotenv
    load_dotenv(".env"); load_dotenv(".env.txt")
except Exception:
    pass

import stockage
import tendia_dce
import xmarches_downloader as X
import tendia_telecharger_dce as T

MAX_MARCHES_PAR_RUN = 30
RATE_LIMIT_SEC = 4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--oui", action="store_true", help="Pas de confirmation.")
    ap.add_argument("--max", type=int, default=MAX_MARCHES_PAR_RUN)
    args = ap.parse_args()

    api_key = os.environ.get("TWOCAPTCHA_API_KEY")
    if not api_key:
        print("❌ TWOCAPTCHA_API_KEY absente."); return

    marches = stockage.charger("marches") or {}
    cibles = [(mid, m) for mid, m in sorted(marches.items())
              if X.est_url_xmarches(m.get("url_dce") or "")
              and m.get("dce_contenu") != "complet"]
    total = len(cibles)
    cibles = cibles[:max(0, args.max)]
    print(f"=== RE-TÉLÉCHARGEMENT XMARCHES ===")
    print(f"Cibles non-complet : {total}  · traités ce run : {len(cibles)}")
    print(f"Coût 2captcha estimé : ~{len(cibles) * 0.001:.3f} €\n")
    if not cibles:
        print("Rien à faire."); return
    if not args.oui:
        try:
            input("Entrée pour lancer (Ctrl+C annuler)... ")
        except (EOFError, KeyboardInterrupt):
            print("\nAnnulé."); return

    bilan = Counter()
    for i, (mid, marche) in enumerate(cibles, 1):
        ancien = marche.get("dce_contenu") or "?"
        dossier = os.path.join(str(T.REPERTOIRE_DCE), mid)
        try:
            res = X.telecharger_dce_pour_marche(marche, str(T.REPERTOIRE_DCE),
                                                api_key_2captcha=api_key, verbose=False)
        except Exception as e:
            res = {"ok": False, "erreur": f"{type(e).__name__}: {e}"}
        if res.get("ok"):
            qual = tendia_dce.qualifier_dce(dossier)
            nouveau = qual["qualite"]
            marche["dce_contenu"] = nouveau
            marche["dce_pieces_contractuelles"] = qual["pieces_contractuelles"]
            marche["dce_raison_contenu"] = qual["raison"]
            marche["dce_telecharge_le"] = datetime.now().isoformat()
            stockage.ecrire("marches", mid, marche)
        else:
            nouveau = f"échec ({str(res.get('erreur'))[:40]})"
        bilan[f"{ancien} → {marche.get('dce_contenu') if res.get('ok') else 'échec'}"] += 1
        print(f"  [{i}/{len(cibles)}] {mid} : {ancien} → {nouveau}")
        if i < len(cibles):
            time.sleep(RATE_LIMIT_SEC)

    print("\nBilan :")
    for k, n in bilan.most_common():
        print(f"  {k} : {n}")
    nb_complet = sum(n for k, n in bilan.items() if k.endswith("complet"))
    print(f"\n⇒ {nb_complet} marchés passés à complet")


if __name__ == "__main__":
    main()
