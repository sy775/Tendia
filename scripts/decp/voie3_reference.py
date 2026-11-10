"""
scripts/decp/voie3_reference.py — référence figée des estimations Voie 3 (Sprint DECP-R).

Reproduit exactement le calcul de la fiche marché (tendia_ui.detail_marche) :
  preset  = fiche_marche.resolve_preset_codes(brief)[0]
  ancre   = brief.revenu_eur ou fiche_marche.montant_estime(brief)
  voie3   = decp_comparables.comparables_pour_marche(marche, preset, montant_ancre=ancre)

Lecture seule (aucune écriture en base).

Usage :
  # 1. Avant la reprise : sélectionne 20 briefs BTP stratifiés et fige leurs estimations
  python scripts/decp/voie3_reference.py figer --sortie data/decp_reprise/voie3_avant.json
  # 2. Après la reprise : relance sur LA MÊME sélection
  python scripts/decp/voie3_reference.py figer --selection data/decp_reprise/voie3_avant.json \
         --sortie data/decp_reprise/voie3_apres.json
  # 3. Compare (écart par brief, signale > 15 %)
  python scripts/decp/voie3_reference.py comparer data/decp_reprise/voie3_avant.json \
         data/decp_reprise/voie3_apres.json
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tendia.core import stockage
import fiche_marche
from tendia.prix import decp_comparables

N_BRIEFS = 20
# Strates de montant d'ancrage (€ HT) : 4 briefs par strate
STRATES = [("sans_ancre", None, None), ("<100k", 0, 100_000), ("100k-500k", 100_000, 500_000),
           ("500k-2M", 500_000, 2_000_000), (">2M", 2_000_000, float("inf"))]


def _preset(brief):
    p = fiche_marche.resolve_preset_codes(brief or {})
    p = p[0] if p else None
    return p[0] if isinstance(p, (list, tuple)) else p


def _ancre(brief):
    return (brief or {}).get("revenu_eur") or fiche_marche.montant_estime(brief or {})


def _calculer(mid):
    marche = stockage.lire("marches", mid) or {}
    brief = stockage.lire("briefs_extraits", mid) or {}
    preset, ancre = _preset(brief), _ancre(brief)
    v3 = decp_comparables.comparables_pour_marche(marche, preset, montant_ancre=ancre)
    return {"id": mid, "preset": preset, "ancre": ancre,
            "objet": (marche.get("objet") or marche.get("titre") or "")[:100],
            "dept": decp_comparables._dept_de(marche), "voie3": v3}


def _selection_btp():
    """20 briefs BTP, 4 par strate d'ancre, ordre déterministe (hash de l'id)."""
    ids = stockage.lister_ids("briefs_extraits")
    par_strate = {s[0]: [] for s in STRATES}
    for mid in sorted(ids, key=lambda i: hashlib.sha1(i.encode()).hexdigest()):
        if ".bak" in mid or not stockage.lire("marches", mid):
            continue
        brief = stockage.lire("briefs_extraits", mid) or {}
        if _preset(brief) != "btp":
            continue
        a = _ancre(brief)
        for nom, lo, hi in STRATES:
            ok = (a in (None, 0)) if lo is None else (a and lo <= a < hi)
            if ok and len(par_strate[nom]) < N_BRIEFS // len(STRATES):
                par_strate[nom].append(mid)
                break
    sel = [m for s in STRATES for m in par_strate[s[0]]]
    # Strates incomplètes (peu de petits marchés BTP) : complète jusqu'à N_BRIEFS avec les
    # briefs BTP suivants (même ordre déterministe), toutes strates confondues.
    stats = {k: len(v) for k, v in par_strate.items()}
    if len(sel) < N_BRIEFS:
        for mid in sorted(ids, key=lambda i: hashlib.sha1(i.encode()).hexdigest()):
            if len(sel) >= N_BRIEFS:
                break
            if mid in sel or ".bak" in mid or not stockage.lire("marches", mid):
                continue
            if _preset(stockage.lire("briefs_extraits", mid) or {}) == "btp":
                sel.append(mid)
        stats["complement"] = len(sel) - sum(len(v) for v in par_strate.values())
    return sel, stats


def cmd_figer(args):
    if args.selection:
        ids = [r["id"] for r in json.load(open(args.selection, encoding="utf-8"))["resultats"]]
        strates = None
    else:
        ids, strates = _selection_btp()
    res = [_calculer(m) for m in ids]
    out = {"cree_le": datetime.now().isoformat(timespec="seconds"),
           "strates": strates, "resultats": res}
    os.makedirs(os.path.dirname(args.sortie) or ".", exist_ok=True)
    with open(args.sortie, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    print(f"{len(res)} briefs figés → {args.sortie}  (strates : {strates})")
    for r in res:
        v = r["voie3"]
        print(f"  {r['id']:<22} ancre={r['ancre'] or '-':>12}  dispo={v.get('disponible')}  "
              f"n={v.get('n')}  méd={v.get('montant_median')}  strat={v.get('strategie')}")


def cmd_comparer(args):
    a = {r["id"]: r for r in json.load(open(args.avant, encoding="utf-8"))["resultats"]}
    b = {r["id"]: r for r in json.load(open(args.apres, encoding="utf-8"))["resultats"]}
    print(f"{'id':<22} {'méd. avant':>12} {'méd. après':>12} {'écart':>8}  n avant→après  stratégie")
    for mid, ra in a.items():
        va, vb = ra["voie3"], (b.get(mid) or {}).get("voie3") or {}
        ma, mb = va.get("montant_median"), vb.get("montant_median")
        ecart = (mb - ma) / ma * 100 if ma and mb else None
        flag = "  ⚠ >15 %" if ecart is not None and abs(ecart) > 15 else ""
        print(f"{mid:<22} {ma or '-':>12} {mb or '-':>12} "
              f"{(f'{ecart:+.0f} %' if ecart is not None else '-'):>8}  "
              f"{va.get('n')}→{vb.get('n')}  {va.get('strategie')} → {vb.get('strategie')}{flag}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("figer")
    f.add_argument("--sortie", required=True)
    f.add_argument("--selection", default=None)
    f.set_defaults(func=cmd_figer)
    c = sub.add_parser("comparer")
    c.add_argument("avant")
    c.add_argument("apres")
    c.set_defaults(func=cmd_comparer)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
