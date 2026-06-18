"""
scripts/backtest_voie3.py — mesure objective (non-circulaire) de la qualité du
matching de comparables Voie 3.

Principe : la DECP = 142k contrats RÉELS avec leur montant exécuté = vérité terrain.
Pour un échantillon de marchés DECP, on CACHE le montant, on prédit via les comparables
(même logique que la prod : CPV+géo, exclusion de soi-même), puis on mesure l'écart entre
la médiane prédite et le vrai montant. Aucune circularité : on tune sur des prix réels qu'on
n'a pas inventés.

Métriques :
  - MdAPE = médiane de l'erreur absolue en % (|pred − vrai| / vrai). Plus bas = mieux.
  - Couverture IQR = % des cas où le vrai montant tombe dans [p25, p75] prédit (idéal ~50%).
  - Biais = médiane de l'erreur signée (pred − vrai)/vrai (>0 = on surestime).
  - Tout ventilé PAR STRATÉGIE (CPV8+dépt → secteur national) pour voir où ça décroche.

Usage : python scripts/backtest_voie3.py [--n 800] [--seed 42]
"""
import argparse
import os
import random
import statistics
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stockage
import decp_comparables as DC


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=800, help="taille échantillon")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    conn = stockage._conn()
    # Échantillon aléatoire reproductible de marchés DECP avec montant + CPV.
    rng = random.Random(args.seed)
    total = conn.execute("SELECT COUNT(*) FROM decp_marches WHERE montant_eur > 0").fetchone()[0]
    # On tire des offsets aléatoires (la table n'a pas d'id séquentiel exploitable simplement).
    ids = conn.execute(
        "SELECT id, cpv_principal, departement, montant_eur FROM decp_marches "
        "WHERE montant_eur > 0 AND cpv_principal IS NOT NULL").fetchall()
    print(f"Univers : {len(ids)} marchés DECP avec montant+CPV (sur {total} avec montant).")
    echantillon = rng.sample(ids, min(args.n, len(ids)))

    # Preset par decp_classification (pour le repli secteur)
    presets = dict(conn.execute("SELECT decp_id, preset_principal FROM decp_classification").fetchall())

    par_strat = defaultdict(lambda: {"ape": [], "signed": [], "iqr": 0, "n": 0})
    globaux = {"ape": [], "signed": [], "iqr": 0, "n": 0, "indispo": 0}

    for did, cpv, dept, vrai in echantillon:
        pseudo = {"cpv_principal": cpv,
                  "perimetre_geographique": (f"Dept {dept}" if dept else "")}
        preset = presets.get(did)
        # mappe le preset DECP en preset Tendia attendu par comparables (inverse du map interne)
        res = DC.comparables_pour_marche(pseudo, _preset_tendia(preset), exclure_id=did)
        if not res.get("disponible"):
            globaux["indispo"] += 1
            continue
        pred = res["montant_median"]
        if not vrai or vrai <= 0:
            continue
        ape = abs(pred - vrai) / vrai
        signed = (pred - vrai) / vrai
        in_iqr = res["montant_p25"] <= vrai <= res["montant_p75"]
        for bucket in (globaux, par_strat[res["strategie"]]):
            bucket["ape"].append(ape)
            bucket["signed"].append(signed)
            bucket["iqr"] += 1 if in_iqr else 0
            bucket["n"] += 1

    def _ligne(nom, b):
        if not b["n"]:
            return f"  {nom:24} : n=0"
        mdape = statistics.median(b["ape"]) * 100
        biais = statistics.median(b["signed"]) * 100
        couv = 100 * b["iqr"] / b["n"]
        return (f"  {nom:24} : n={b['n']:4} | MdAPE {mdape:5.0f}% | "
                f"couv.IQR {couv:4.0f}% | biais {biais:+5.0f}%")

    print(f"\n=== Backtest Voie 3 — {globaux['n']} prédictions "
          f"({globaux['indispo']} sans comparables suffisants) ===")
    print(_ligne("GLOBAL", globaux))
    print("\nPar stratégie (du + précis au + large) :")
    ordre = ["CPV exact + département", "CPV 5 + département", "CPV 5 (national)",
             "CPV 3 + département", "CPV 3 (national)", "Secteur + département", "Secteur (national)"]
    for s in ordre:
        if s in par_strat:
            print(_ligne(s, par_strat[s]))

    print("\nLecture : MdAPE = erreur médiane |pred−vrai|/vrai. Couv.IQR idéale ≈ 50% "
          "(si <50%, fourchette trop étroite ; si >50%, trop large).")


def _preset_tendia(preset_decp):
    """Inverse partiel de _PRESET_VERS_DECP pour réinjecter le preset dans comparables."""
    inv = {"enr": "energie_renouvelable", "conseil_rd": "conseil"}
    return inv.get(preset_decp, preset_decp)


if __name__ == "__main__":
    main()
