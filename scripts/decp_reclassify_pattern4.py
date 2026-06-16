"""
scripts/decp_reclassify_pattern4.py — raffinement v2, Étape 3 (Pattern 4).

Re-classifie au LLM (Haiku 4.5, nouveau prompt) les marchés CPV 79xxx (hors 79952
déjà fixé en Pattern 1) actuellement en conseil_rd / ingenierie / non_classifie_*,
pour corriger la confusion conseil_rd ↔ ingenierie. UPDATE uniquement si le preset
change. Log ligne-à-ligne pour audit + version de prompt (SHA).

Pattern progressif OBLIGATOIRE :
  --dry-run                 # compte + coût estimé, 0 appel
  --limite 100              # ~0,08 €, validation prompt
  --limite 1000             # ~0,80 €, validation distribution
  (complet) --plafond 10.0  # arrêt automatique au plafond

Garde-fous (stop-conditions) : > 30 % des CPV 79* re-classifiés, ou > 5 % bascule
en hors_perimetre → anomalie signalée (revue Younes).

Usage : python scripts/decp_reclassify_pattern4.py [--dry-run] [--limite N] [--plafond 10.0]
"""
import argparse
import csv
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decp.db import connexion
from decp.classifier_llm import classer_llm, BudgetTracker, PROMPT_VERSION

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CHUNK = 200
WORKERS = 10
COUT_ESTIME = 0.0006  # nouveau prompt plus long (~550 tok)
SEUIL_RECLASS_PCT = 30.0   # > → dérive du prompt
SEUIL_HORS_PCT = 5.0       # > → prompt trop strict


def _candidats(con, limite=None):
    sql = ("SELECT m.id, m.objet, m.cpv_principal, m.acheteur_nom, "
           "c.preset_principal AS ancien "
           "FROM decp_marches m JOIN decp_classification c ON c.decp_id = m.id "
           "WHERE m.cpv_principal LIKE '79%' AND m.cpv_principal NOT LIKE '79952%' "
           "AND (c.preset_principal IN ('conseil_rd','ingenierie') "
           "     OR c.preset_principal LIKE 'non_classifie%')")
    if limite:
        sql += f" LIMIT {int(limite)}"
    return [dict(r) for r in con.execute(sql).fetchall()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limite", type=int, default=None)
    ap.add_argument("--plafond", type=float, default=10.0)
    args = ap.parse_args()

    con = connexion()
    # base totale CPV 79* (hors 79952) pour les ratios garde-fous
    total_79 = con.execute(
        "SELECT COUNT(*) FROM decp_marches "
        "WHERE cpv_principal LIKE '79%' AND cpv_principal NOT LIKE '79952%'").fetchone()[0]
    marches = _candidats(con, args.limite)
    con.close()
    n = len(marches)

    print(f"=== Reclassification Pattern 4 (CPV 79*, prompt v{PROMPT_VERSION}) ===")
    print(f"CPV 79* hors 79952 en base       : {total_79}")
    print(f"Éligibles (conseil_rd/ingenierie/non_classifie) : {n}"
          f"{' [LIMITE '+str(args.limite)+']' if args.limite else ''}")
    if args.dry_run:
        print(f"Coût estimé si tous traités       : ~{n*COUT_ESTIME:.2f} € (~{COUT_ESTIME} €/marché)")
        print("[DRY-RUN] aucun appel LLM.")
        return
    if not n:
        print("Rien à re-classifier.")
        return

    tracker = BudgetTracker(args.plafond)
    transitions = Counter()
    inchange = erreurs = 0
    changements = []  # (id, cpv, objet, ancien, nouveau, confiance)
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
                    continue
                nouveau, ancien = r["preset"], m["ancien"]
                if nouveau == ancien:
                    inchange += 1
                    continue
                transitions[f"{ancien} → {nouveau}"] += 1
                changements.append((m["id"], m["cpv_principal"], (m["objet"] or "")[:120],
                                    ancien, nouveau, r["confiance"]))
                maj.append((nouveau, r["confiance"],
                            datetime.now(timezone.utc).isoformat(), m["id"]))
            if maj:
                con.executemany(
                    "UPDATE decp_classification SET preset_principal=?, source='llm', "
                    "confiance=?, classified_at=? WHERE decp_id=?", maj)
                con.commit()
            tracker.log()
    finally:
        con.close()

    traites = sum(transitions.values()) + inchange
    reclasses = sum(transitions.values())
    vers_hors = sum(v for k, v in transitions.items() if k.endswith("→ hors_perimetre"))

    # --- Log CSV des changements ---
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(DATA, f"reclassif_pattern4_{ts}.csv")
    with open(log_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "cpv", "objet", "ancien", "nouveau", "confiance", "prompt_version"])
        for c in changements:
            w.writerow(list(c) + [PROMPT_VERSION])

    print(f"\n=== Reclassification Pattern 4 — terminée ===")
    print(f"Éligibles examinés   : {n}")
    print(f"Traités par LLM      : {traites}  (erreurs LLM : {erreurs})")
    print(f"Re-classifiés        : {reclasses}")
    print(f"Inchangés            : {inchange}")
    print("Transitions :")
    for k, v in transitions.most_common():
        print(f"  - {k:34} : {v}")
    if budget_atteint:
        print(f"⚠ Budget atteint avant la fin ({n - i} marchés non traités).")
    print(f"Budget consommé : {tracker.consomme_eur:.3f} € / {args.plafond:.0f} €")
    moy = tracker.consomme_eur / tracker.nb_appels if tracker.nb_appels else 0
    print(f"Coût moyen      : {moy:.6f} €/marché | {tracker.nb_appels} appels")
    print(f"Log changements : {log_path}")

    # --- Garde-fous (sur l'ensemble examiné) ---
    pct_reclass = 100.0 * reclasses / traites if traites else 0
    pct_hors = 100.0 * vers_hors / traites if traites else 0
    print(f"\nGarde-fous : {pct_reclass:.1f} % re-classifiés, {pct_hors:.1f} % → hors_perimetre")
    if pct_reclass > SEUIL_RECLASS_PCT:
        print(f"⛔ ALERTE : {pct_reclass:.1f} % > {SEUIL_RECLASS_PCT} % re-classifiés — "
              "dérive possible du prompt. À signaler à Younes.")
    if pct_hors > SEUIL_HORS_PCT:
        print(f"⛔ ALERTE : {pct_hors:.1f} % > {SEUIL_HORS_PCT} % → hors_perimetre — "
              "prompt potentiellement trop strict. À signaler à Younes.")


if __name__ == "__main__":
    main()
