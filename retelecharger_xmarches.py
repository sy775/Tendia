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
# Un échec captcha est transitoire (2captcha se trompe parfois). On retente les
# marchés qui échouent SUR LE CAPTCHA sur plusieurs passes, sans bloquer.
MAX_PASSES_CAPTCHA = 4


def _est_echec_captcha(res: dict) -> bool:
    return "captcha" in str(res.get("erreur") or "").lower()


def _traiter(mid, marche, api_key):
    """Télécharge + qualifie + persiste un marché. Retourne (ok, res)."""
    dossier = os.path.join(str(T.REPERTOIRE_DCE), mid)
    try:
        res = X.telecharger_dce_pour_marche(marche, str(T.REPERTOIRE_DCE),
                                            api_key_2captcha=api_key, verbose=False)
    except Exception as e:
        return False, {"ok": False, "erreur": f"{type(e).__name__}: {e}"}
    if res.get("ok"):
        qual = tendia_dce.qualifier_dce(dossier)
        marche["dce_contenu"] = qual["qualite"]
        marche["dce_pieces_contractuelles"] = qual["pieces_contractuelles"]
        marche["dce_raison_contenu"] = qual["raison"]
        marche["dce_telecharge_le"] = datetime.now().isoformat()
        stockage.ecrire("marches", mid, marche)
    return bool(res.get("ok")), res


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

    ok_total = 0
    echec_dur = []          # échecs non-captcha (structurels) : on n'insiste pas
    a_traiter = list(cibles)
    for passe in range(1, MAX_PASSES_CAPTCHA + 1):
        if not a_traiter:
            break
        if passe > 1:
            print(f"\n--- Passe {passe}/{MAX_PASSES_CAPTCHA} : "
                  f"{len(a_traiter)} échec(s) captcha à retenter ---")
        retry = []
        for i, (mid, marche) in enumerate(a_traiter, 1):
            ancien = marche.get("dce_contenu") or "?"
            ok, res = _traiter(mid, marche, api_key)
            if ok:
                ok_total += 1
                print(f"  [{i}/{len(a_traiter)}] {mid} : {ancien} → {marche.get('dce_contenu')}")
            elif _est_echec_captcha(res):
                retry.append((mid, marche))   # transitoire → on retentera
                print(f"  [{i}/{len(a_traiter)}] {mid} : échec captcha (sera retenté)")
            else:
                echec_dur.append((mid, str(res.get("erreur"))[:50]))
                print(f"  [{i}/{len(a_traiter)}] {mid} : échec {str(res.get('erreur'))[:45]}")
            if i < len(a_traiter):
                time.sleep(RATE_LIMIT_SEC)
        a_traiter = retry

    print(f"\nBilan : {ok_total} complet · {len(a_traiter)} échec captcha persistant · "
          f"{len(echec_dur)} échec structurel")
    for mid, err in echec_dur:
        print(f"  ✗ {mid} : {err}")
    if a_traiter:
        print(f"  ⚠ captcha non résolu après {MAX_PASSES_CAPTCHA} passes : "
              f"{[mid for mid, _ in a_traiter]} (relancer le script)")


if __name__ == "__main__":
    main()
