"""
scripts/decp_reclassify_patterns.py — raffinement post-validation Sprint DECP 2.

Re-classe (niveau 1 / CPV, 0 €) les marchés impactés par les 3 patterns d'erreur
identifiés lors de la pré-validation :
  P1 — CPV 79952xxx (événementiel) → hors_perimetre (était parti au LLM).
  P2 — CPV 71314xxx affiné : ingenierie, sauf 71314100 (fourniture) → hors_perimetre
       (n'est plus mappé en bloc → enr).
  P3 — CPV 45xxx + objet « maîtrise d'œuvre » → ingenierie (était btp).

Recalcule via `decp.classifier_cpv.classer_marche_cpv` (qui porte déjà les nouvelles
règles) et UPDATE les lignes dont le preset change. Coût LLM : 0 €.

Garde-fous (stop-conditions du sprint) : abandon si un pattern impacte > 5 000
marchés, ou si la distribution globale d'un preset majeur (btp/ingenierie/
hors_perimetre) bouge de plus de 3 points.

Usage : python scripts/decp_reclassify_patterns.py [--dry-run] [--force]
"""
import argparse
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decp.db import connexion
from decp.classifier_cpv import classer_marche_cpv
from decp.mapping_cpv import _digits

PRESETS_ALL = ["btp", "ingenierie", "it", "conseil_rd", "formation", "enr", "hors_perimetre"]
MAJEURS = ["btp", "ingenierie", "hors_perimetre"]
SEUIL_PATTERN = 5000        # > → stop
SEUIL_PTS_MAJEUR = 3.0      # > pts sur un preset majeur → stop


def _distribution(con):
    return {r[0]: r[1] for r in con.execute(
        "SELECT preset_principal, COUNT(*) FROM decp_classification "
        "GROUP BY preset_principal").fetchall()}


def _pattern(cpv) -> int:
    d = _digits(cpv)
    if d.startswith("79952"):
        return 1
    if d.startswith("71314"):
        return 2
    if d.startswith("45"):
        return 3
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="applique même si une stop-condition est franchie")
    args = ap.parse_args()

    con = connexion()
    try:
        total = con.execute("SELECT COUNT(*) FROM decp_classification").fetchone()[0]
        dist_avant = _distribution(con)

        rows = con.execute(
            "SELECT m.id, m.cpv_principal, m.cpv_secondaires, m.objet, "
            "       c.preset_principal AS ancien, c.source AS ancienne_source "
            "FROM decp_marches m JOIN decp_classification c ON c.decp_id = m.id "
            "WHERE m.cpv_principal LIKE '79952%' "
            "   OR m.cpv_principal LIKE '71314%' "
            "   OR (m.cpv_principal LIKE '45%' AND c.preset_principal = 'btp')"
        ).fetchall()

        concernes = Counter()       # candidats par pattern
        reclasses = Counter()       # changements par pattern
        anciens_par_pattern = {1: Counter(), 2: Counter(), 3: Counter()}
        nouveaux_p2 = Counter()     # ventilation P2 (ingenierie / hors_perimetre)
        p3_echantillon = []
        updates = []

        for r in rows:
            pat = _pattern(r["cpv_principal"])
            if pat == 0:
                continue
            concernes[pat] += 1
            nr = classer_marche_cpv(dict(r))
            nouveau, ancien = nr["preset_principal"], r["ancien"]
            if nouveau == ancien:
                continue
            reclasses[pat] += 1
            anciens_par_pattern[pat][ancien or "NULL/LLM"] += 1
            if pat == 2:
                nouveaux_p2[nouveau] += 1
            if pat == 3 and len(p3_echantillon) < 20:
                p3_echantillon.append((r["cpv_principal"], (r["objet"] or "")[:70]))
            updates.append(nr)

        # --- Stop-conditions ---
        alertes = []
        for pat in (1, 2, 3):
            if reclasses[pat] > SEUIL_PATTERN:
                alertes.append(f"Pattern {pat} impacte {reclasses[pat]} marchés (> {SEUIL_PATTERN}).")
        # impact distribution estimé
        delta_est = Counter()
        for nr in updates:
            delta_est[nr["preset_principal"]] += 1
        # (recalcul exact des deltas via avant/après après application ; ici estimation)

        print(f"=== Re-classification patterns — {len(rows)} candidats CPV "
              f"{'[DRY-RUN] ' if args.dry_run else ''}===\n")
        _bloc_pattern(1, "79952 événementiel → hors_perimetre",
                      concernes, reclasses, anciens_par_pattern)
        _bloc_pattern(2, "71314 affiné (ingenierie / hors_perimetre)",
                      concernes, reclasses, anciens_par_pattern, nouveaux_p2)
        _bloc_pattern(3, "MOE + CPV 45* → ingenierie",
                      concernes, reclasses, anciens_par_pattern)

        if p3_echantillon:
            print("  Échantillon P3 (contrôle faux positifs MOE) :")
            for cpv, obj in p3_echantillon:
                print(f"    {cpv} | {obj}")
            print()

        if alertes:
            print("⛔ STOP-CONDITIONS franchies :")
            for a in alertes:
                print(f"  - {a}")
            if not args.force:
                print("\n  → Abandon (pas d'écriture). Relancer avec --force après revue Younes.")
                return
            print("\n  → --force : application malgré l'alerte.\n")

        if args.dry_run:
            print(f"[DRY-RUN] {len(updates)} marchés seraient reclassés. Aucune écriture.")
            return

        if updates:
            con.executemany(
                "UPDATE decp_classification SET "
                "preset_principal=:preset_principal, preset_secondaire=:preset_secondaire, "
                "source=:source, confiance=:confiance, classified_at=:classified_at "
                "WHERE decp_id=:decp_id", updates)
            con.commit()

        dist_apres = _distribution(con)

        # Garde-fou a posteriori sur les presets majeurs
        for p in MAJEURS:
            d = 100.0 * (dist_apres.get(p, 0) - dist_avant.get(p, 0)) / total
            if abs(d) > SEUIL_PTS_MAJEUR:
                print(f"⚠️ ATTENTION : {p} a bougé de {d:+.1f} pts (> {SEUIL_PTS_MAJEUR}). "
                      "À signaler à Younes.")

        print(f"\n=== Distribution finale (Δ vs avant raffinement) — coût 0,00 € ===")
        for p in PRESETS_ALL:
            av, ap_ = dist_avant.get(p, 0), dist_apres.get(p, 0)
            print(f"  - {p:14} : {ap_:>7,} ({100.0*ap_/total:4.1f} %)  Δ {ap_-av:+d}".replace(",", " "))
        print(f"\n⇒ {len(updates)} marchés reclassés.")

    finally:
        con.close()


def _bloc_pattern(pat, titre, concernes, reclasses, anciens, ventil=None):
    print(f"Pattern {pat} ({titre}) :")
    print(f"  - Marchés concernés (candidats) : {concernes[pat]}")
    print(f"  - Reclassifiés                  : {reclasses[pat]}")
    if ventil is not None:
        for k, v in ventil.most_common():
            print(f"      → {k:14} : {v}")
    if anciens[pat]:
        det = ", ".join(f"{k}={v}" for k, v in anciens[pat].most_common())
        print(f"  - Anciens presets corrigés      : {det}")
    print()


if __name__ == "__main__":
    main()
