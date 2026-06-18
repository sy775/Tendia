"""
scripts/backtest_objet.py — teste si un matching affiné par SIMILARITÉ D'OBJET (+durée)
bat le baseline CPV+géo (MdAPE 73%) — de façon NON-CIRCULAIRE (on ne filtre jamais sur le
montant, seulement sur des descripteurs du travail : texte de l'objet, durée).

Pour chaque marché DECP échantillonné (montant réel = vérité), on compare 4 prédicteurs :
  A. baseline prod         : médiane du meilleur pool CPV+géo (logique actuelle).
  B. pool CPV5 → top-K objet      : re-classement du pool par similarité d'objet (IDF-cosinus).
  C. pool CPV5 → top-K objet+durée: idem + proximité de durée.
  D. pool CPV5 médiane brute      : témoin (pool large sans re-classement).

Aucun n'utilise le montant pour sélectionner → pas de biais circulaire.

Usage : python scripts/backtest_objet.py [--n 600] [--seed 42] [--topk 25]
"""
import argparse
import math
import os
import random
import re
import statistics
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stockage
import decp_comparables as DC

_STOP = set("de la le les des du un une et en a au aux pour sur par dans avec ou "
            "marche marches prestation prestations service services travaux fourniture "
            "fournitures lot lots l d n the".split())


def _tokens(txt):
    toks = re.findall(r"[a-zàâäéèêëîïôöùûüç]{3,}", (txt or "").lower())
    return [t for t in toks if t not in _STOP]


def _vec_idf(tokens, idf):
    v = defaultdict(float)
    for t in tokens:
        v[t] += idf.get(t, 0.0)
    return v


def _cos(a, b):
    if not a or not b:
        return 0.0
    inter = set(a) & set(b)
    num = sum(a[t] * b[t] for t in inter)
    na = math.sqrt(sum(x * x for x in a.values()))
    nb = math.sqrt(sum(x * x for x in b.values()))
    return num / (na * nb) if na and nb else 0.0


def _sim_duree(dq, dc):
    if not dq or not dc or dq <= 0 or dc <= 0:
        return 0.5  # neutre si inconnu
    return 1.0 / (1.0 + abs(math.log(dc / dq)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=600)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--topk", type=int, default=25)
    args = ap.parse_args()
    conn = stockage._conn()
    rng = random.Random(args.seed)

    ids = conn.execute(
        "SELECT id, cpv_principal, departement, montant_eur, objet, duree_mois "
        "FROM decp_marches WHERE montant_eur > 0 AND cpv_principal IS NOT NULL "
        "AND objet IS NOT NULL").fetchall()
    print(f"Univers : {len(ids)} marchés (montant+CPV+objet).")
    echantillon = rng.sample(ids, min(args.n, len(ids)))

    res = {k: {"ape": [], "n": 0} for k in ("A_baseline", "B_objet", "C_objet_duree", "D_pool_brut")}
    indispo = 0

    for did, cpv, dept, vrai, objet_q, duree_q in echantillon:
        if not vrai or vrai <= 0:
            continue
        # A — baseline prod (CPV+géo, exclusion self)
        pseudo = {"cpv_principal": cpv, "perimetre_geographique": (f"Dept {dept}" if dept else "")}
        a = DC.comparables_pour_marche(pseudo, None, exclure_id=did)
        if a.get("disponible"):
            _add(res["A_baseline"], a["montant_median"], vrai)

        # Pool CPV5 national pour le re-classement (objet a besoin d'un large pool)
        if not cpv or len(str(cpv)) < 5:
            indispo += 1
            continue
        pool = conn.execute(
            "SELECT montant_eur, objet, duree_mois FROM decp_marches "
            "WHERE cpv_principal LIKE ? AND montant_eur > 0 AND id != ? LIMIT 4000",
            [str(cpv)[:5] + "%", did]).fetchall()
        pool = [(m, o, d) for m, o, d in pool if m and m > 0]
        if len(pool) < 8:
            indispo += 1
            continue

        # D — pool brut (témoin)
        _add(res["D_pool_brut"], statistics.median([m for m, _, _ in pool]), vrai)

        # IDF local au pool
        df = defaultdict(int)
        pool_tok = []
        for m, o, d in pool:
            tk = _tokens(o)
            pool_tok.append(tk)
            for t in set(tk):
                df[t] += 1
        N = len(pool)
        idf = {t: math.log(N / c) for t, c in df.items()}
        vq = _vec_idf(_tokens(objet_q), idf)

        scored = []
        for (m, o, d), tk in zip(pool, pool_tok):
            so = _cos(vq, _vec_idf(tk, idf))
            scored.append((so, _sim_duree(duree_q, d), m))

        # B — top-K par objet
        topB = sorted(scored, key=lambda x: x[0], reverse=True)[:args.topk]
        _add(res["B_objet"], statistics.median([m for _, _, m in topB]), vrai)

        # C — top-K par objet+durée (0.7 / 0.3)
        topC = sorted(scored, key=lambda x: 0.7 * x[0] + 0.3 * x[1], reverse=True)[:args.topk]
        _add(res["C_objet_duree"], statistics.median([m for _, _, m in topC]), vrai)

    print(f"\n=== Backtest objet vs baseline — échantillon {args.n}, top-K {args.topk} "
          f"({indispo} écartés faute de pool) ===")
    for k in ("A_baseline", "D_pool_brut", "B_objet", "C_objet_duree"):
        b = res[k]
        if b["n"]:
            mdape = statistics.median(b["ape"]) * 100
            print(f"  {k:16} : n={b['n']:4} | MdAPE {mdape:5.0f}%")
    print("\nSi B/C < A : la similarité d'objet améliore le matching (non-biaisé).")


def _add(bucket, pred, vrai):
    bucket["ape"].append(abs(pred - vrai) / vrai)
    bucket["n"] += 1


if __name__ == "__main__":
    main()
