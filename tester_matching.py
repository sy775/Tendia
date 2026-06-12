"""
tester_matching.py
------------------
Lance le matching V2 sur tous les marches en base et affiche :
- les top N marches pertinents (avec details des motifs)
- l'histogramme des verdicts par categorie

Aucun appel LLM. Utilise le profil organisme actif et les briefs deja
extraits.

Usage PowerShell :
    python tester_matching.py
    python tester_matching.py --top 20
    python tester_matching.py --details BOAMP-26-XXXXX
"""
import argparse
import io
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import matching
import organisme


def charger_tout():
    """Retourne (profil, marches_dict, briefs_dict)."""
    profil = organisme.charger_actif()
    if profil is None:
        print("Aucun profil organisme. Lance d'abord : python init_profil.py")
        sys.exit(1)
    db = Path("data/tendia.db")
    conn = sqlite3.connect(str(db)); cur = conn.cursor()
    cur.execute("SELECT id, contenu_json FROM kv_storage WHERE collection='marches'")
    marches = {r[0]: json.loads(r[1]) for r in cur.fetchall()}
    cur.execute("SELECT id, contenu_json FROM kv_storage WHERE collection='briefs_extraits'")
    briefs = {r[0]: json.loads(r[1]) for r in cur.fetchall()}
    return profil, marches, briefs


def afficher_motif(mot):
    points = mot["points"]
    symb = "+" if points > 0 else ("-" if points < 0 else "=")
    return f"    [{symb}{abs(points):>3}] {mot['critere']:<28} : {mot['commentaire'][:90]}"


def cmd_top(top_n: int):
    profil, marches, briefs = charger_tout()
    legacy = organisme.est_format_legacy(profil)
    presets_p = profil.get("presets_couverts") or []
    print(f"Profil : {profil.get('identite', {}).get('raison_sociale') or '(sans nom)'}")
    print(f"Format : {'legacy formation' if legacy else 'nouveau multi-secteurs'}")
    print(f"Presets couverts : {presets_p}")
    print(f"Zones : {profil.get('zones_intervention') or []}")
    print()

    evaluations = matching.evaluer_tous(profil, marches, briefs)
    n = len(evaluations)

    # Histogramme verdicts
    hist = Counter(e["verdict"] for e in evaluations)
    print(f"=== Verdicts sur {n} marches ===")
    for v in ("tres_pertinent", "pertinent", "a_verifier", "non_pertinent"):
        nb = hist.get(v, 0)
        pct = 100*nb/n if n else 0
        print(f"  {v:<18} : {nb:>4}  ({pct:5.1f}%)")

    # Top N
    print()
    print(f"=== Top {top_n} marches par score ===")
    for i, e in enumerate(evaluations[:top_n], 1):
        mid = e["id_marche"]
        m = marches.get(mid, {})
        titre = (m.get("titre") or m.get("objet") or "")[:80]
        print(f"\n  [{i:>2}] score={e['score']:>3}  verdict={e['verdict']:<16} {mid}")
        print(f"       {titre}")
        if "presets_marche" in e:
            print(f"       presets_marche : {e['presets_marche']}")
        # Motifs significatifs uniquement
        for mot in e["motifs"]:
            if mot["points"] == 0 and mot.get("satisfait") is None:
                continue
            print(afficher_motif(mot))


def cmd_details(mid: str):
    profil, marches, briefs = charger_tout()
    m = marches.get(mid)
    if not m:
        print(f"Marche {mid} introuvable.")
        sys.exit(1)
    b = briefs.get(mid)
    res = matching.evaluer(profil, m, brief=b)
    print(f"Marche : {mid}")
    print(f"  titre : {(m.get('titre') or '')[:120]}")
    print(f"  acheteur : {m.get('acheteur_nom')}")
    print(f"  presets_marche resolu : {res.get('presets_marche')}")
    print(f"  presets_profil : {res.get('presets_profil')}")
    print()
    print(f"SCORE : {res['score']}/100   VERDICT : {res['verdict']}")
    print(f"Version moteur : {res.get('_version')}")
    print()
    print("Tous les motifs :")
    for mot in res["motifs"]:
        print(afficher_motif(mot))
        if mot.get("valeur_organisme"):
            print(f"           organisme: {mot['valeur_organisme']}")
        if mot.get("valeur_marche"):
            print(f"           marche   : {mot['valeur_marche']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10,
                    help="Nombre de marches a afficher (defaut 10)")
    ap.add_argument("--details", metavar="ID_MARCHE",
                    help="Details d'un marche specifique")
    args = ap.parse_args()
    if args.details:
        cmd_details(args.details)
    else:
        cmd_top(args.top)


if __name__ == "__main__":
    main()
