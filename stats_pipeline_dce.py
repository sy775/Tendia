# -*- coding: utf-8 -*-
"""
stats_pipeline_dce.py
=====================
Compte les avis ingeres, les DCE par etat, et les briefs LLM extraits.

Usage :
  python stats_pipeline_dce.py
  python stats_pipeline_dce.py --db data\tendia.db
"""

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter


# Force UTF-8 stdout sur Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


DB_PATH = os.path.join("data", "tendia.db")


def detecter_plateforme(url):
    if not url:
        return "sans URL DCE"
    u = url.lower()
    if "marches-publics.info" in u:        return "AWS-Achat"
    if "marches-publics.gouv.fr" in u:     return "PLACE"
    if "achatpublic" in u:                 return "Achatpublic"
    if "e-marchespublics" in u or "emarchespublics" in u: return "Dematis"
    if any(x in u for x in ("megalis", "maximilien", "atexo", "mamp", "ternum")):
        return "Atexo whitelabel"
    return "autre"


def barre(n, total, largeur=40):
    if total == 0:
        return ""
    return "#" * int(largeur * n / total)


def main():
    p = argparse.ArgumentParser(description="Stats pipeline recuperation DCE")
    p.add_argument("--db", default=DB_PATH, help=f"Chemin DB (defaut: {DB_PATH})")
    args = p.parse_args()

    if not os.path.exists(args.db):
        sys.exit(f"[FAIL] DB introuvable : {args.db}")

    con = sqlite3.connect(args.db)
    cur = con.cursor()

    # IDs des marches avec brief extrait
    briefs_ids = {id_ for id_, in cur.execute(
        "SELECT id FROM kv_storage WHERE collection='briefs_extraits'")}

    # Comptage marches
    total = 0
    par_contenu = Counter()
    avec_url = 0
    avec_brief = 0
    par_pf_contenu = {}

    for id_, ct in cur.execute(
            "SELECT id, contenu_json FROM kv_storage WHERE collection='marches'"):
        d = json.loads(ct)
        total += 1
        contenu = d.get("dce_contenu") or "non_evalue"
        par_contenu[contenu] += 1
        url = d.get("url_dce") or ""
        if url:
            avec_url += 1
        if id_ in briefs_ids:
            avec_brief += 1
        pf = detecter_plateforme(url)
        key = (pf, contenu)
        par_pf_contenu[key] = par_pf_contenu.get(key, 0) + 1

    con.close()

    # ----- FUNNEL PRINCIPAL -----
    complet = par_contenu.get("complet", 0)
    print()
    print("=" * 70)
    print("FUNNEL PIPELINE")
    print("=" * 70)
    print(f"  {total:>4}  avis BOAMP ingeres")
    print(f"  {avec_url:>4}  avec URL DCE renseignee       "
          f"({100*avec_url/total:.0f}% des avis)")
    print(f"  {complet:>4}  DCE complet                   "
          f"({100*complet/total:.0f}% des avis, "
          f"{100*complet/max(1,avec_url):.0f}% des avis avec URL)")
    print(f"  {avec_brief:>4}  briefs LLM extraits           "
          f"({100*avec_brief/max(1,complet):.0f}% des complets)")

    # ----- DISTRIBUTION ETAT -----
    print()
    print("=" * 70)
    print("ETAT DCE (champ dce_contenu)")
    print("=" * 70)
    ordre = ["complet", "incomplet", "auth_requise", "vide", "non_evalue"]
    etats_presents = [e for e in ordre if e in par_contenu] + \
                     [e for e in par_contenu if e not in ordre]
    for e in etats_presents:
        n = par_contenu[e]
        pct = 100 * n / total
        print(f"  {e:15} {n:>4}  ({pct:5.1f}%)  {barre(n, total)}")

    # ----- PLATEFORME x ETAT -----
    print()
    print("=" * 70)
    print("PLATEFORME x ETAT DCE")
    print("=" * 70)
    plateformes = sorted({k[0] for k in par_pf_contenu},
                         key=lambda pf: -sum(n for (p, e), n in par_pf_contenu.items()
                                              if p == pf))
    etats = ["complet", "incomplet", "auth_requise", "vide"]
    # Header
    print(f"  {'PLATEFORME':22}", *(f"{e:>13}" for e in etats),
          f"{'TOTAL':>7}", f"{'%cplt':>7}")
    print("  " + "-" * 76)
    for pf in plateformes:
        row = [par_pf_contenu.get((pf, e), 0) for e in etats]
        tot = sum(row)
        pct = 100 * row[0] / tot if tot else 0
        print(f"  {pf:22}", *(f"{n:>13}" for n in row),
              f"{tot:>7}", f"{pct:>6.0f}%")
    # Totaux
    print("  " + "-" * 76)
    totaux = [sum(par_pf_contenu.get((pf, e), 0) for pf in plateformes)
              for e in etats]
    tot_all = sum(totaux)
    print(f"  {'TOTAL':22}",
          *(f"{n:>13}" for n in totaux),
          f"{tot_all:>7}",
          f"{100*totaux[0]/tot_all:>6.0f}%" if tot_all else "")

    # ----- GOULOT BRIEFS -----
    print()
    print("=" * 70)
    print("GOULOT EXTRACTION LLM")
    print("=" * 70)
    a_extraire = complet - avec_brief
    print(f"  Briefs extraits        : {avec_brief}")
    print(f"  DCE complets sans brief: {a_extraire}")
    if a_extraire > 0:
        print(f"  -> python reextraire_briefs_complet.py")
    print()


if __name__ == "__main__":
    main()
