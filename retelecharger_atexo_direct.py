"""
retelecharger_atexo_direct.py
-----------------------------
Re-télécharge EN DIRECT (sans proxy) les DCE des avis Atexo / PLACE non-complets.

Contexte : le proxy résidentiel tronquait les gros DCE Atexo (zip coupé → faux
« vide ») et coûtait de la bande passante inutile sur des plateformes à accès
anonyme. Depuis que le proxy est désactivé pour ces plateformes (cf
http_humain.PLATEFORMES_SANS_PROXY), les downloads Atexo passent en direct et
aboutissent complets. Ce script rattrape les anciens dossiers tronqués / mal
qualifiés via le chemin profond completeDownload.

Usage : python retelecharger_atexo_direct.py [--oui] [--max N]
"""
import argparse
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import tendia_dce
import atexo_downloader
import tendia_telecharger_dce as T


def _cibles(max_n: int):
    marches = stockage.charger("marches") or {}
    out = []
    for mid, m in sorted(marches.items()):
        if not (isinstance(m, dict) and m.get("nature_libelle") == "Avis de marché"
                and m.get("dce_contenu") != "complet"):
            continue
        u = m.get("url_dce") or ""
        try:
            base = atexo_downloader._detecter_url_base(u)
        except Exception:
            base = None
        if base:
            out.append((mid, m))
    return out[:max(0, max_n)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--oui", action="store_true")
    ap.add_argument("--max", type=int, default=50)
    args = ap.parse_args()

    cibles = _cibles(args.max)
    print("=== RE-TÉLÉCHARGEMENT ATEXO / PLACE EN DIRECT (sans proxy) ===")
    print(f"Cibles non-complet : {len(cibles)}\n")
    if not cibles:
        print("Rien à faire.")
        return
    if not args.oui:
        try:
            input("Entrée pour lancer (Ctrl+C annuler)... ")
        except (EOFError, KeyboardInterrupt):
            print("\nAnnulé.")
            return

    ok = 0
    for i, (mid, m) in enumerate(cibles, 1):
        ancien = m.get("dce_contenu") or "?"
        dossier = str(T.REPERTOIRE_DCE / mid)
        try:
            res = atexo_downloader.telecharger_dce_pour_marche(m, str(T.REPERTOIRE_DCE),
                                                               verbose=True)
        except Exception as e:
            res = {"ok": False, "erreur": f"{type(e).__name__}: {e}"}
        if res.get("ok"):
            q = tendia_dce.qualifier_dce(dossier)
            m["dce_contenu"] = q["qualite"]
            m["dce_pieces_contractuelles"] = q["pieces_contractuelles"]
            m["dce_raison_contenu"] = q["raison"]
            m["dce_telecharge_le"] = datetime.now().isoformat()
            stockage.ecrire("marches", mid, m)
            ok += q["qualite"] == "complet"
            print(f"  [{i}/{len(cibles)}] {mid} : {ancien} → {q['qualite']}")
        else:
            print(f"  [{i}/{len(cibles)}] {mid} : échec ({str(res.get('erreur'))[:55]})")

    print(f"\n⇒ {ok} marchés passés à complet")


if __name__ == "__main__":
    main()
