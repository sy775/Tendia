"""
scripts/decp_classify_llm.py — Sprint DECP 2, Étape 3 (classification niveau 2, LLM Haiku 4.5).

Classe les marchés DECP NULL (ambigus/inconnus du niveau 1) avec Haiku 4.5,
en parallèle par chunks, sous un plafond budgétaire dur (arrêt net). Les marchés
non traités (budget atteint) sont marqués 'non_classifie_budget'.

Usage : python scripts/decp_classify_llm.py --plafond 50.0 [--limite N] [--dry-run]
Pattern progressif : --dry-run → --limite 100 → --limite 1000 → complet.
"""
import argparse
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decp.db import connexion
from decp.classifier_llm import classer_llm, BudgetTracker

CHUNK = 200
WORKERS = 10
COUT_ESTIME_PAR_MARCHE = 0.0005  # ~430 tok Haiku


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plafond", type=float, default=50.0)
    ap.add_argument("--limite", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    con = connexion()
    sql = ("SELECT m.id, m.objet, m.cpv_principal, m.acheteur_nom "
           "FROM decp_marches m JOIN decp_classification c ON c.decp_id=m.id "
           "WHERE c.preset_principal IS NULL")
    if args.limite:
        sql += f" LIMIT {int(args.limite)}"
    marches = [dict(r) for r in con.execute(sql).fetchall()]
    con.close()
    n = len(marches)

    print(f"=== Classification niveau 2 (LLM Haiku 4.5) — {n} marchés ambigus "
          f"| plafond {args.plafond:.0f} €{' [DRY-RUN]' if args.dry_run else ''} ===")
    if args.dry_run:
        print(f"  Coût estimé si tous traités : ~{n*COUT_ESTIME_PAR_MARCHE:.2f} € "
              f"(~{COUT_ESTIME_PAR_MARCHE} €/marché)")
        print("  [DRY-RUN] aucun appel LLM.")
        return
    if not n:
        print("  Rien à classer (niveau 1 a tout résolu, ou déjà fait).")
        return

    tracker = BudgetTracker(args.plafond)
    dist = Counter()
    faible_conf = erreurs = traites = 0
    budget_atteint = False
    con = connexion()
    try:
        for i in range(0, n, CHUNK):
            if not tracker.peut_continuer():
                budget_atteint = True
                break
            lot = marches[i:i + CHUNK]
            with ThreadPoolExecutor(max_workers=WORKERS) as ex:
                resultats = list(ex.map(classer_llm, lot))
            maj = []
            for m, r in zip(lot, resultats):
                tracker.ajouter_cout(r["cout_eur"])
                if not r["ok"]:
                    erreurs += 1
                    continue  # laissé NULL, retraité au prochain run
                dist[r["preset"]] += 1
                if (r["confiance"] or 0) < 0.6:
                    faible_conf += 1
                traites += 1
                maj.append((r["preset"], r["confiance"],
                            datetime.now(timezone.utc).isoformat(), m["id"]))
            if maj:
                con.executemany(
                    "UPDATE decp_classification SET preset_principal=?, source='llm', "
                    "confiance=?, classified_at=? WHERE decp_id=?", maj)
                con.commit()
            tracker.log()

        # Marchés non ATTAQUÉS (budget atteint avant de les traiter) = marches[i:].
        # Les erreurs (attaquées mais en échec) restent NULL → retraitées au prochain run.
        non_traites = 0
        if budget_atteint:
            restants = [(datetime.now(timezone.utc).isoformat(), m["id"]) for m in marches[i:]]
            if restants:
                con.executemany(
                    "UPDATE decp_classification SET preset_principal='non_classifie_budget', "
                    "source='budget', confiance=NULL, classified_at=? WHERE decp_id=?", restants)
                con.commit()
                non_traites = len(restants)
    finally:
        con.close()

    dt = (time.time() - tracker.start_time) / 60
    print(f"\n=== Niveau 2 LLM terminé ===")
    print(f"Marchés ambigus initiaux : {n}")
    print(f"Traités par LLM          : {traites} ({_pct(traites, n)})")
    print(f"Non traités (budget)     : {non_traites} ({_pct(non_traites, n)})")
    print(f"Erreurs (laissés NULL)   : {erreurs}")
    print("Distribution LLM :")
    for p, c in dist.most_common():
        print(f"  - {p:16} : {c} ({_pct(c, traites)})")
    print(f"Confiance < 0.6          : {faible_conf}")
    print(f"Budget consommé : {tracker.consomme_eur:.3f} € / {args.plafond:.0f} €")
    print(f"Appels LLM      : {tracker.nb_appels}")
    moy = tracker.consomme_eur / tracker.nb_appels if tracker.nb_appels else 0
    print(f"Coût moyen      : {moy:.6f} €/marché | Temps {dt:.1f} min")


def _pct(n, d):
    return f"{100.0*n/d:.1f} %" if d else "—"


if __name__ == "__main__":
    main()
