# -*- coding: utf-8 -*-
"""
audit_matching_n2.py
====================
Audit du scoring de pertinence V2 (matching.py) sur la base Tendia.

Usage (depuis le repo Tendia, avec venv active) :

  # Mode par defaut (organisme principal, AVEC injection N1->V2)
  python audit_matching_n2.py

  # Profil specifique
  python audit_matching_n2.py --profil data/exemples/profil_btp_demo.json
  python audit_matching_n2.py --profil data/exemples/profil_ingenierie_demo.json

  # Comparaison SANS vs AVEC injection N1
  python audit_matching_n2.py --comparer

  # Export CSV pour annotation manuelle
  python audit_matching_n2.py --csv audit_btp.csv

  # Tout combine
  python audit_matching_n2.py --profil data/exemples/profil_btp_demo.json --comparer --csv audit_btp.csv

Pre-requis (deja dans le repo) :
  - matching.py
  - stockage.py
  - data/tendia.db avec collections : marches, briefs_extraits, scores_matching, organisme
"""

import argparse
import csv
import json
import os
import sqlite3
import sys
from collections import Counter, defaultdict


# Force UTF-8 stdout sur Windows (cp1252 par defaut)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


DB_PATH = os.path.join("data", "tendia.db")


# ---------------------------------------------------------------------------
# Chargement
# ---------------------------------------------------------------------------

def charger_db(path):
    if not os.path.exists(path):
        sys.exit(f"[FAIL] DB introuvable : {path}")
    con = sqlite3.connect(path)
    cur = con.cursor()

    marches = {}
    for id_, ct in cur.execute(
            "SELECT id, contenu_json FROM kv_storage WHERE collection='marches'"):
        marches[id_] = json.loads(ct)

    briefs = {}
    for id_, ct in cur.execute(
            "SELECT id, contenu_json FROM kv_storage WHERE collection='briefs_extraits'"):
        briefs[id_] = json.loads(ct)

    presets_n1 = defaultdict(list)
    for ct, in cur.execute(
            "SELECT contenu_json FROM kv_storage WHERE collection='scores_matching'"):
        d = json.loads(ct)
        if d.get('matche'):
            presets_n1[d['marche_id']].append(d['preset_code'])

    organisme = None
    row = cur.execute(
        "SELECT contenu_json FROM kv_storage WHERE collection='organisme'"
        ).fetchone()
    if row:
        organisme = json.loads(row[0])

    con.close()
    return marches, briefs, dict(presets_n1), organisme


def charger_profil(chemin):
    if not os.path.exists(chemin):
        sys.exit(f"[FAIL] Profil introuvable : {chemin}")
    return json.load(open(chemin, encoding="utf-8"))


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluer_base(profil, marches, briefs, presets_n1, injection_n1):
    """Lance matching.evaluer sur tous les marches.
    injection_n1=True -> passe les presets via argument presets_marche.
    """
    import matching  # import tardif pour eviter erreur si script lance hors du repo

    resultats = []
    for m_id, m in marches.items():
        brief = briefs.get(m_id)
        kwargs = {"brief": brief}
        if injection_n1:
            pm = presets_n1.get(m_id)
            if pm:
                kwargs["presets_marche"] = list(pm)
        e = matching.evaluer(profil, m, **kwargs)
        e["_id"] = m_id
        e["_marche"] = m
        resultats.append(e)
    return resultats


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

VERDICTS = ("tres_pertinent", "pertinent", "a_verifier", "non_pertinent")


def stats(label, evals):
    n = len(evals)
    verdicts = Counter(e["verdict"] for e in evals)
    score_moy = sum(e["score"] for e in evals) / max(1, n)

    motifs_par_crit = defaultdict(lambda: {"n": 0, "pts": 0,
                                            "ok": 0, "ko": 0, "neutre": 0})
    for e in evals:
        for m in e["motifs"]:
            c = m["critere"]
            motifs_par_crit[c]["n"] += 1
            motifs_par_crit[c]["pts"] += m["points"]
            if m["satisfait"] is True:
                motifs_par_crit[c]["ok"] += 1
            elif m["satisfait"] is False:
                motifs_par_crit[c]["ko"] += 1
            else:
                motifs_par_crit[c]["neutre"] += 1

    # marches avec un motif sectoriel
    sect_btp = {"btp_qualibat", "btp_rge", "btp_amiante",
                "btp_corps_metier", "btp_types_ouvrages", "btp_capacite_chantier"}
    sect_ing = {"ing_opqibi", "ing_assurances", "ing_typologies_mission",
                "ing_competences_specialisees", "ing_types_ouvrages",
                "ing_capacite_etudes"}
    n_sect_btp = sum(1 for e in evals
                     if any(s in {m["critere"] for m in e["motifs"]}
                            for s in sect_btp))
    n_sect_ing = sum(1 for e in evals
                     if any(s in {m["critere"] for m in e["motifs"]}
                            for s in sect_ing))

    print()
    print(f"=== {label} ===")
    print(f"  Total marches : {n}")
    print(f"  Score moyen   : {score_moy:.2f}")
    print(f"  Marches avec sectoriel BTP actif        : {n_sect_btp}")
    print(f"  Marches avec sectoriel ingenierie actif : {n_sect_ing}")
    print("  Distribution verdicts :")
    for v in VERDICTS:
        c = verdicts.get(v, 0)
        pct = 100 * c / max(1, n)
        bar = "#" * (c // 5)
        print(f"    {v:18} {c:>4}  ({pct:5.1f}%)  {bar}")

    # Buckets de score
    buckets = Counter((e["score"] // 10) * 10 for e in evals)
    print("  Distribution scores (tranches de 10) :")
    for b in sorted(buckets):
        print(f"    [{b:>3}-{b+9:>3}]  {buckets[b]:>4}")

    # Motifs : moyenne points par critere
    print("  Motifs (moyenne points, OK/KO/neutre) :")
    print(f"    {'CRITERE':32} {'N':>4} {'AVG':>7}   OK    KO    --")
    for c in sorted(motifs_par_crit):
        d = motifs_par_crit[c]
        avg = d["pts"] / d["n"]
        print(f"    {c:32} {d['n']:>4} {avg:>+7.2f} {d['ok']:>4} {d['ko']:>4} "
              f"{d['neutre']:>5}")


# ---------------------------------------------------------------------------
# Export CSV pour annotation
# ---------------------------------------------------------------------------

def exporter_csv(evals, chemin):
    """CSV stratifie 5/5/10/10 (par verdict, completes par ordre de score).
    Colonnes : id_marche, score, verdict, presets_marche, titre, acheteur,
               url_avis, motifs_resume, annotation_humaine, commentaire
    """
    # Tri par score desc dans chaque verdict
    par_v = defaultdict(list)
    for e in evals:
        par_v[e["verdict"]].append(e)
    for v in par_v:
        par_v[v].sort(key=lambda e: -e["score"])

    cibles = {"tres_pertinent": 5, "pertinent": 5,
              "a_verifier": 10, "non_pertinent": 10}

    selection = []
    for v in VERDICTS:
        pool = par_v.get(v, [])
        selection.extend(pool[:cibles[v]])

    with open(chemin, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow([
            "id_marche", "score", "verdict", "presets_marche_utilises",
            "titre", "acheteur", "url_avis",
            "motifs_positifs", "motifs_negatifs",
            "annotation_humaine", "commentaire"
        ])
        for e in selection:
            m = e["_marche"]
            titre = (m.get("titre") or m.get("objet") or "")[:120]
            ach = (m.get("acheteur_nom") or "")[:80]
            url = m.get("url_avis") or ""
            pos = " | ".join(
                f"{x['critere']}+{x['points']}" for x in e["motifs"]
                if x["points"] > 0)
            neg = " | ".join(
                f"{x['critere']}{x['points']}" for x in e["motifs"]
                if x["points"] < 0)
            w.writerow([e["_id"], e["score"], e["verdict"],
                        ",".join(e.get("presets_marche") or []),
                        titre, ach, url, pos, neg, "", ""])

    print(f"\n[OK] CSV ecrit : {chemin}  ({len(selection)} marches selectionnes)")
    print(f"     Stratification : {dict((v, min(len(par_v.get(v,[])), cibles[v])) for v in VERDICTS)}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Audit scoring matching V2")
    p.add_argument("--db", default=DB_PATH,
                   help=f"Chemin DB SQLite (defaut : {DB_PATH})")
    p.add_argument("--profil", default=None,
                   help="Chemin profil JSON (defaut : organisme actuel en base)")
    p.add_argument("--comparer", action="store_true",
                   help="Compare SANS vs AVEC injection N1->V2")
    p.add_argument("--sans-injection", action="store_true",
                   help="Force le mode SANS injection N1 (utile pour iso etat actuel)")
    p.add_argument("--csv", default=None,
                   help="Export CSV stratifie pour annotation manuelle")
    args = p.parse_args()

    # Chargement DB
    print(f"[INFO] Lecture {args.db} ...")
    marches, briefs, presets_n1, organisme_db = charger_db(args.db)
    print(f"[INFO] Marches : {len(marches)}  |  Briefs : {len(briefs)}  |  "
          f"Marches classifies N1 : {len(presets_n1)}")

    # Profil
    if args.profil:
        profil = charger_profil(args.profil)
        print(f"[INFO] Profil : {args.profil}")
    elif organisme_db:
        profil = organisme_db
        print(f"[INFO] Profil : organisme actuel en base "
              f"(presets_couverts={profil.get('presets_couverts')})")
    else:
        sys.exit("[FAIL] Aucun profil disponible. Utiliser --profil.")

    # Sanity check : V1 ou V2 ?
    try:
        import matching
        if matching._est_format_legacy_formation(profil):
            print("[WARN] Profil detecte au format legacy V1 (formation Apptia).")
            print("[WARN] Le matching sera route via _evaluer_legacy, pas V2.")
            print("[WARN] Pour V2, ajoute presets_couverts + profils_sectoriels au profil.")
    except Exception:
        pass

    # Evaluations
    if args.comparer:
        evals_sans = evaluer_base(profil, marches, briefs, presets_n1,
                                   injection_n1=False)
        stats("SANS injection N1 (etat actuel pipeline)", evals_sans)
        evals_avec = evaluer_base(profil, marches, briefs, presets_n1,
                                   injection_n1=True)
        stats("AVEC injection N1->V2 (cible si on repare la propagation)",
              evals_avec)
        evals_a_exporter = evals_avec  # CSV sur le scenario cible
    elif args.sans_injection:
        evals_sans = evaluer_base(profil, marches, briefs, presets_n1,
                                   injection_n1=False)
        stats("SANS injection N1", evals_sans)
        evals_a_exporter = evals_sans
    else:
        evals_avec = evaluer_base(profil, marches, briefs, presets_n1,
                                   injection_n1=True)
        stats("AVEC injection N1->V2 (defaut)", evals_avec)
        evals_a_exporter = evals_avec

    if args.csv:
        exporter_csv(evals_a_exporter, args.csv)


if __name__ == "__main__":
    main()
