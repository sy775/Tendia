"""
retelecharger_marches_securises.py
----------------------------------
Batch : récupère le DCE sur marches-securises.fr pour les avis SANS url_dce dont
l'avis cite cette plateforme + une référence. Recherche anonyme par référence
(arrêté du 22/03/2019) + désambiguïsation OBLIGATOIRE par acheteur.

⚠️ marches-securises rate-limite les requêtes rapprochées (le lien de
téléchargement anonyme n'apparaît plus si l'IP est throttlée). Pacing intégré ;
un proxy résidentiel (TENDIA_PROXY_URL) aide pour les gros volumes.

Usage : python retelecharger_marches_securises.py [--oui] [--max N]
"""
import argparse
import sys
import time
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import tendia_dce
import resolution_reference as RR
import marches_securises_downloader as MS
import tendia_telecharger_dce as T

RATE_LIMIT_SEC = 8   # marches-securises throttle vite → on espace


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--oui", action="store_true")
    ap.add_argument("--max", type=int, default=30)
    args = ap.parse_args()

    marches = stockage.charger("marches") or {}
    cibles = []
    for mid, m in sorted(marches.items()):
        if not (isinstance(m, dict) and m.get("nature_libelle") == "Avis de marché"
                and m.get("dce_contenu") != "complet"):
            continue
        base, ref = RR.extraire_plateforme_reference(m)
        if base and "marches-securises" in base.lower() and ref:
            cibles.append((mid, m))
    cibles = cibles[:max(0, args.max)]

    print("=== RE-TÉLÉCHARGEMENT MARCHES-SECURISES (recherche par référence) ===")
    print(f"Cibles (plateforme + référence) : {len(cibles)}\n")
    if not cibles:
        print("Rien à faire.")
        return
    if not args.oui:
        try:
            input("Entrée pour lancer (Ctrl+C annuler)... ")
        except (EOFError, KeyboardInterrupt):
            print("\nAnnulé.")
            return

    bilan = Counter()
    ok = 0
    for i, (mid, m) in enumerate(cibles, 1):
        ancien = m.get("dce_contenu") or "?"
        dossier = str(T.REPERTOIRE_DCE / mid)
        try:
            res = MS.telecharger_dce_pour_marche(m, str(T.REPERTOIRE_DCE), verbose=True)
        except Exception as e:
            res = {"ok": False, "erreur": f"{type(e).__name__}: {e}"}
        if res.get("ok"):
            q = tendia_dce.qualifier_dce(dossier)
            m["dce_contenu"] = q["qualite"]
            m["dce_pieces_contractuelles"] = q["pieces_contractuelles"]
            m["dce_raison_contenu"] = q["raison"]
            m["dce_telecharge_le"] = datetime.now().isoformat()
            m["url_dce_source"] = "marches_securises_reference"
            stockage.ecrire("marches", mid, m)
            ok += q["qualite"] == "complet"
            bilan[f"{ancien} → {q['qualite']}"] += 1
            print(f"  [{i}/{len(cibles)}] {mid} : {ancien} → {q['qualite']}")
        else:
            bilan["échec"] += 1
            print(f"  [{i}/{len(cibles)}] {mid} : échec ({str(res.get('erreur'))[:45]})")
        if i < len(cibles):
            time.sleep(RATE_LIMIT_SEC)

    print("\nBilan :")
    for k, n in bilan.most_common():
        print(f"  {k} : {n}")
    print(f"\n⇒ {ok} marchés passés à complet")


if __name__ == "__main__":
    main()
