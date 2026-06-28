# -*- coding: utf-8 -*-
"""
Chaîne DCE → extraction → grille pour les marchés France Travail ingérés.
Scopé aux IDs France Travail en base (acheteur « France Travail »).

Étapes par marché :
  1. dce_finder.trouver_urls_dce      → url_dce + qualité (persisté)
  2. telecharger_pieces_dce           → data/dce/<id>/
  3. tendia_extraire.traiter_marche   → brief LLM (SQLite briefs_extraits)
  4. test_grille_notation.generer_grille → grille d'actions pondérées

Résilient : continue au marché suivant en cas d'échec. Proxy IPRoyal actif
(contourne le throttle BOAMP/résolution).

Usage : python pipeline_france_travail.py            (tous les FT sans brief)
        python pipeline_france_travail.py BOAMP-26-40954   (un seul)
"""
import os
import sys
import traceback
from pathlib import Path

import stockage
import dce_finder
import tendia_telecharger_dce as tdl
import pdf_extract
import tendia_extraire

REPERTOIRE_DCE = os.path.join("data", "dce")


def _proxy():
    for line in Path(".env").read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip().startswith("TENDIA_PROXY_URL="):
            return line.split("=", 1)[1].strip()
    return None


def _ids_france_travail():
    marches = stockage.charger("marches") or {}
    ids = []
    for mid, m in marches.items():
        if not isinstance(m, dict):
            continue
        ach = (m.get("acheteur_nom") or "").lower()
        if "france travail" in ach or "pole emploi" in ach or "pôle emploi" in ach:
            ids.append(mid)
    return ids


def traiter_un(mid: str) -> dict:
    res = {"id": mid, "url": None, "dce": None, "brief": None, "grille": None, "err": None}
    marche = stockage.lire("marches", mid)
    if not marche:
        res["err"] = "introuvable en base"
        return res

    # 1) Résolution URL DCE
    try:
        r = dce_finder.trouver_urls_dce(marche, verbose=False)
        marche["url_dce"] = r.get("url_dce")
        marche["reference_ft"] = r.get("reference_ft")
        marche["url_recherche_place"] = r.get("url_recherche")
        marche["dce_qualite"] = r.get("qualite", "absente")
        stockage.ecrire("marches", mid, marche)
        res["url"] = marche["url_dce"]
        print(f"  [{mid}] URL DCE : {r.get('qualite')} — {str(marche['url_dce'])[:80]}")
    except Exception as e:
        res["err"] = f"résolution URL: {e}"
        print(f"  [{mid}] ❌ résolution URL : {e}")
        return res

    if not marche.get("url_dce"):
        res["err"] = "pas d'URL DCE résolue"
        print(f"  [{mid}] ⊘ pas d'URL DCE")
        return res

    # 2) Téléchargement DCE
    dossier = os.path.join(REPERTOIRE_DCE, mid)
    try:
        dl = tdl.telecharger_pieces_dce(marche, dossier)
        res["dce"] = dl.get("statut") if isinstance(dl, dict) else dl
        print(f"  [{mid}] DCE : {res['dce']}")
    except Exception as e:
        res["err"] = f"téléchargement: {e}"
        print(f"  [{mid}] ❌ téléchargement : {e}")
        return res

    # 3) Extraction brief
    try:
        tendia_extraire._dezipper_dossier(dossier, verbose=False)
        pdfs = pdf_extract.extraire_dossier(dossier, verbose=False)
        if not pdfs:
            res["err"] = "aucun PDF exploitable"
            print(f"  [{mid}] ⊘ aucun PDF")
            return res
        rr = tendia_extraire.traiter_marche(mid, dossier, pdfs, dry_run=False, verbose=False)
        if not rr.get("ok"):
            res["err"] = f"extraction: {rr.get('erreur') or rr.get('raison')}"
            print(f"  [{mid}] ❌ extraction : {res['err']}")
            return res
        res["brief"] = "ok"
        print(f"  [{mid}] brief : ok")
    except Exception as e:
        res["err"] = f"extraction: {e}"
        print(f"  [{mid}] ❌ extraction : {e}")
        return res

    # 4) Grille
    try:
        import test_grille_notation
        data = test_grille_notation.generer_grille(mid)
        res["grille"] = len(data.get("grille", []))
        print(f"  [{mid}] grille : {res['grille']} critères")
    except SystemExit as e:
        res["err"] = f"grille: {e}"
        print(f"  [{mid}] ⊘ grille : {e}")
    except Exception as e:
        res["err"] = f"grille: {e}"
        print(f"  [{mid}] ❌ grille : {e}")
    return res


def main():
    proxy = _proxy()
    if proxy:
        import http_utils
        http_utils._session.proxies = {"http": proxy, "https": proxy}
        print(f"  Proxy actif : {proxy[:22]}...")

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        ids = args
    else:
        ids = [mid for mid in _ids_france_travail()
               if not stockage.lire("briefs_extraits", mid)]
    print(f"  À traiter : {len(ids)} marché(s) France Travail\n")

    resultats = []
    for mid in ids:
        print("─" * 70)
        try:
            resultats.append(traiter_un(mid))
        except Exception as e:
            print(f"  [{mid}] ❌❌ crash : {e}")
            traceback.print_exc()
            resultats.append({"id": mid, "err": str(e)})

    print("\n" + "=" * 70 + "\n  BILAN")
    for r in resultats:
        statut = "✓ grille" if r.get("grille") else ("✓ brief" if r.get("brief") else "✗")
        print(f"  {r['id']:<18} {statut:<10} {r.get('err') or ''}")


if __name__ == "__main__":
    main()
