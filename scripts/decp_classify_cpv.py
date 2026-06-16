"""
scripts/decp_classify_cpv.py — Sprint DECP 2, Étape 2 (classification niveau 1, CPV-only, 0 €).

Classe tous les marchés DECP non encore classifiés via le mapping CPV. Les marchés
ambigus/inconnus reçoivent preset_principal=NULL (repris par le LLM en niveau 2).

Usage : python scripts/decp_classify_cpv.py [--dry-run] [--limite N]
"""
import argparse
import sys
import time
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(
    __import__("os").path.abspath(__file__))))

from decp.db import connexion
from decp.classifier_cpv import classer_marche_cpv

PRESETS = ["btp", "it", "ingenierie", "conseil_rd", "formation", "enr"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limite", type=int, default=None)
    args = ap.parse_args()

    con = connexion()
    t0 = time.time()
    try:
        sql = ("SELECT m.id, m.cpv_principal, m.cpv_secondaires, m.objet "
               "FROM decp_marches m LEFT JOIN decp_classification c ON c.decp_id=m.id "
               "WHERE c.decp_id IS NULL")
        if args.limite:
            sql += f" LIMIT {int(args.limite)}"
        marches = con.execute(sql).fetchall()
        total = len(marches)
        print(f"=== Classification niveau 1 (CPV) — {total} marchés à traiter"
              f"{' [DRY-RUN]' if args.dry_run else ''} ===")

        presets = Counter()
        hors = a_llm = 0
        causes_llm = Counter()
        rows = []
        for i, m in enumerate(marches, 1):
            r = classer_marche_cpv(dict(m))
            p = r["preset_principal"]
            if p in PRESETS:
                presets[p] += 1
            elif p == "hors_perimetre":
                hors += 1
            else:  # None → LLM
                a_llm += 1
                causes_llm[r["source"]] += 1
            rows.append(r)
            if i % 20000 == 0:
                print(f"  …{i}/{total}")

        if not args.dry_run and rows:
            con.executemany(
                "INSERT OR REPLACE INTO decp_classification "
                "(decp_id, preset_principal, preset_secondaire, source, confiance, classified_at) "
                "VALUES (:decp_id,:preset_principal,:preset_secondaire,:source,:confiance,:classified_at)",
                rows)
            con.commit()
    finally:
        con.close()

    classes = sum(presets.values()) + hors
    print(f"\n=== Niveau 1 terminé ({(time.time()-t0)/60:.1f} min, coût 0,00 €) ===")
    print(f"Total traités     : {total}")
    print(f"Classés (preset)  : {sum(presets.values())} ({_pct(sum(presets.values()), total)})")
    for p in PRESETS:
        print(f"  - {p:12} : {presets.get(p,0)}")
    print(f"Hors périmètre    : {hors} ({_pct(hors, total)})")
    print(f"À envoyer au LLM  : {a_llm} ({_pct(a_llm, total)})")
    for c, n in causes_llm.most_common():
        print(f"  - {c:24} : {n}")
    if args.dry_run:
        print("[DRY-RUN] aucune écriture.")


def _pct(n, d):
    return f"{100.0*n/d:.1f} %" if d else "—"


if __name__ == "__main__":
    main()
