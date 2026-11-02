"""
scripts/decp/voie3_propositions.py — Sprint DECP-R : PROPOSITIONS (non appliquées) pour la
voie 3, sur les comparables antérieurs à 2025.

  P1 « ancienneté » : médiane pondérée, poids = 0,5 ^ (âge en années / DEMI_VIE_ANS).
  P2 « BT01 »       : montant × BT01(dernier mois connu) / BT01(mois de notification) pour
                      les comparables notifiés avant 2025 (index du bâtiment tous corps
                      d'état, INSEE série 001710986, base 2010).

Mesures : (a) écart de la médiane sur les 20 briefs de référence (même sélection que
voie3_reference.py) ; (b) mini-backtest (contrats DECP récents dont on cache le montant)
pour juger la justesse (MdAPE, biais). Lecture seule.

Usage : python scripts/decp/voie3_propositions.py [--n-backtest 400]
"""
import argparse
import json
import os
import random
import re
import statistics
import sys
from datetime import date

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import decp_comparables as DC
import stockage

DEMI_VIE_ANS = 2.0
SERIE_BT01 = "data/decp_reprise/brut/insee/bt01_sdmx.xml"


def charger_bt01():
    t = open(SERIE_BT01, encoding="utf-8").read()
    s = {p: float(v) for p, v in re.findall(r'<Obs TIME_PERIOD="([0-9-]+)" OBS_VALUE="([0-9.]+)"', t)}
    dernier = max(s)
    return s, dernier


def _mediane_ponderee(vals_poids):
    vp = sorted((v, w) for v, w in vals_poids if v and v > 0 and w > 0)
    if not vp:
        return None
    tot = sum(w for _, w in vp)
    acc = 0
    for v, w in vp:
        acc += w
        if acc >= tot / 2:
            return v
    return vp[-1][0]


def comparables_bruts(marche, preset, montant_ancre, exclure_id=None):
    """Rejoue la stratégie retenue par comparables_pour_marche et renvoie (résultat prod,
    lignes [(montant, date_notification)]) après filtre anti-aberrants et dédoublonnage logique."""
    res = DC.comparables_pour_marche(marche, preset, exclure_id=exclure_id, montant_ancre=montant_ancre)
    if not res.get("disponible") and not res.get("strategie"):
        return res, []
    conn = stockage._conn()
    preset_decp = DC._PRESET_VERS_DECP.get((preset or "").lower())
    for libelle, where, params, join_classif in DC._strategies(marche, preset_decp):
        if libelle != res.get("strategie"):
            continue
        base = ("SELECT m.montant_eur, m.titulaire_siret, m.objet, m.date_notification, m.acheteur_siret, "
                "m.duree_mois FROM decp_marches m ")
        if join_classif:
            base += "JOIN decp_classification c ON c.decp_id = m.uid "
        p = list(params)
        bande = ""
        if montant_ancre and montant_ancre > 0:
            bande = " AND m.montant_eur BETWEEN ? AND ?"
            p += [montant_ancre * DC.BANDE_MONTANT[0], montant_ancre * DC.BANDE_MONTANT[1]]
        excl = ""
        if exclure_id:
            excl = " AND m.uid != ?"
            p.insert(len(params), exclure_id)
        rows = conn.execute(base + f"WHERE {where} AND m.montant_eur > 0 AND m.doublon_de IS NULL{excl}{bande} "
                            f"LIMIT {DC.LIMITE_SQL}", p).fetchall()
        rows = DC._filtrer_aberrants([tuple(r) for r in rows])
        uniq = {}
        for r in rows:
            uniq.setdefault(DC._cle_marche(r), r)
        return res, [(r[0], r[3]) for r in uniq.values()]
    return res, []


def variantes(lignes, bt01, dernier, auj):
    base = statistics.median([m for m, _ in lignes]) if lignes else None
    def age(d):
        try:
            return max(0.0, (auj - date.fromisoformat(d[:10])).days / 365.25)
        except (TypeError, ValueError):
            return 0.0
    p1 = _mediane_ponderee([(m, 0.5 ** (age(d) / DEMI_VIE_ANS)) for m, d in lignes])
    idx = []
    for m, d in lignes:
        if d and d[:4] < "2025" and d[:7] in bt01:
            idx.append(m * bt01[dernier] / bt01[d[:7]])
        else:
            idx.append(m)
    p2 = statistics.median(idx) if idx else None
    part_avant_2025 = sum(1 for _, d in lignes if d and d[:4] < "2025") / len(lignes) if lignes else 0
    return base, p1, p2, part_avant_2025


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-backtest", type=int, default=400)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    bt01, dernier = charger_bt01()
    auj = date.today()
    ref = json.load(open("data/decp_reprise/voie3_avant.json", encoding="utf-8"))["resultats"]
    import fiche_marche
    print(f"BT01 : {len(bt01)} mois, dernier {dernier} = {bt01[dernier]}")
    print(f"\n(a) 20 briefs — médiane prod actuelle vs propositions")
    out_b = []
    for r in ref:
        marche = stockage.lire("marches", r["id"]) or {}
        brief = stockage.lire("briefs_extraits", r["id"]) or {}
        p = fiche_marche.resolve_preset_codes(brief)
        preset = (p[0][0] if p and isinstance(p[0], (list, tuple)) else (p[0] if p else None))
        ancre = brief.get("revenu_eur") or fiche_marche.montant_estime(brief)
        res, lignes = comparables_bruts(marche, preset, ancre)
        base, p1, p2, part = variantes(lignes, bt01, dernier, auj)
        e1 = (p1 - base) / base * 100 if base and p1 else None
        e2 = (p2 - base) / base * 100 if base and p2 else None
        out_b.append({"id": r["id"], "n": len(lignes), "part_avant_2025": round(part, 2), "mediane": base,
                      "p1_anciennete": p1, "p2_bt01": p2, "ecart_p1_%": e1, "ecart_p2_%": e2})
        print(f"  {r['id']:<16} n={len(lignes):>4} avant2025={part:4.0%}  méd {base or 0:>12,.0f}  "
              f"P1 {('%+.1f %%' % e1) if e1 is not None else '-':>8}  P2 {('%+.1f %%' % e2) if e2 is not None else '-':>8}"
              .replace(",", " "))
    # (b) mini-backtest : contrats DECP 2026 (on cache le montant), comparables avec ancre = vrai montant
    print(f"\n(b) mini-backtest ({args.n_backtest} contrats DECP 2026, montant caché)")
    conn = stockage._conn()
    rng = random.Random(args.seed)
    univers = conn.execute("SELECT m.uid, m.cpv_principal, m.departement, m.montant_eur, c.famille FROM decp_marches m "
                           "LEFT JOIN decp_classification c ON c.decp_id = m.uid WHERE m.doublon_de IS NULL "
                           "AND m.montant_eur > 0 AND m.cpv_principal IS NOT NULL AND m.date_notification >= '2026-01-01'").fetchall()
    ech = rng.sample(univers, min(args.n_backtest, len(univers)))
    err = {"prod": [], "P1": [], "P2": []}
    for uid, cpv, dept, vrai, fam in ech:
        pseudo = {"cpv_principal": cpv, "perimetre_geographique": f"Dept {dept}" if dept else ""}
        _, lignes = comparables_bruts(pseudo, fam, None, exclure_id=uid)
        if len(lignes) < DC.N_MIN:
            continue
        base, p1, p2, _ = variantes(lignes, bt01, dernier, auj)
        for k, v in (("prod", base), ("P1", p1), ("P2", p2)):
            if v:
                err[k].append((v - vrai) / vrai)
    bt = {}
    for k, e in err.items():
        if e:
            bt[k] = {"n": len(e), "mdape_%": round(statistics.median(abs(x) for x in e) * 100, 1),
                     "biais_%": round(statistics.median(e) * 100, 1)}
            print(f"  {k:<5} n={bt[k]['n']}  MdAPE {bt[k]['mdape_%']} %  biais {bt[k]['biais_%']:+} %")
    json.dump({"briefs": out_b, "backtest": bt, "demi_vie_ans": DEMI_VIE_ANS, "bt01_dernier": [dernier, bt01[dernier]]},
              open("data/decp_reprise/voie3_propositions.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("→ data/decp_reprise/voie3_propositions.json")


if __name__ == "__main__":
    main()
