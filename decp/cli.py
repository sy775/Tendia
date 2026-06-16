"""
decp/cli.py — orchestrateur du pipeline DECP (Sprint DECP 1).

Pattern de test progressif :
  python -m decp.cli ingest --depuis 2025-06-16 --dry-run        # parse + stats, 0 écriture
  python -m decp.cli ingest --depuis 2025-06-16 --limite 100     # 100 lignes en DB
  python -m decp.cli ingest --depuis 2025-06-16                  # complet (12 mois)
  python -m decp.cli ingest-annee --depuis 2025-06 --jusqua 2026-06
  python -m decp.cli audit
"""
import argparse
import sys
from collections import Counter
from datetime import date

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from decp import db as decp_db
from decp import telecharger
from decp.parser import parser_marche, agreger_multi_titulaires


def _12_mois_avant() -> str:
    t = date.today()
    return f"{t.year - 1:04d}-{t.month:02d}-{t.day:02d}"


def cmd_ingest(args):
    depuis = args.depuis or _12_mois_avant()
    jusqua = args.jusqua  # exclusif, optionnel
    print(f"=== INGEST DECP — depuis {depuis}"
          f"{' jusqu’à ' + jusqua if jusqua else ''}"
          f"{' [DRY-RUN]' if args.dry_run else ''}"
          f"{f' [LIMITE {args.limite}]' if args.limite else ''} ===")

    bruts = telecharger.fetch_decp(depuis, date_fin=jusqua, limite=args.limite)
    if not bruts:
        print("⚠ Aucune ligne reçue — API indisponible ou filtre vide. STOP.")
        sys.exit(2)

    parses, rejets, warn = [], 0, 0
    for raw in bruts:
        p = parser_marche(raw)
        if p is None:
            rejets += 1
            continue
        if p.get("parse_warnings"):
            warn += 1
        parses.append(p)

    avant = len(parses)
    parses = agreger_multi_titulaires(parses)
    multi = sum(1 for p in parses if p.get("titulaires_json"))

    taux_rejet = 100.0 * rejets / max(len(bruts), 1)
    print(f"  Lignes brutes      : {len(bruts):,}".replace(",", " "))
    print(f"  Parsées            : {avant} (rejets durs : {rejets} = {taux_rejet:.1f} %)")
    print(f"  Avec parse_warnings: {warn}")
    print(f"  Après dédup multi-titulaires : {len(parses)} marchés uniques "
          f"({multi} multi-attributaires)")

    if taux_rejet > 30:
        print(f"⛔ Taux de rejet {taux_rejet:.1f} % > 30 % — signal de problème de "
              "format. STOP, prévenir Younes (stop-condition du sprint).")
        sys.exit(3)

    if args.dry_run:
        # Aperçu distribution CPV (2 chiffres) sans écrire
        cpv2 = Counter(str(p["cpv_principal"])[:2] for p in parses if p.get("cpv_principal"))
        print("  [DRY-RUN] Top CPV (2 ch.) :",
              ", ".join(f"{c}:{n}" for c, n in cpv2.most_common(8)))
        print("  [DRY-RUN] Aucune écriture en base.")
        return

    decp_db.init_schema()
    n = decp_db.inserer_marches(parses, source_fichier=f"decp_consolidee_api:{depuis}")
    print(f"  ✅ {n} marchés écrits dans decp_marches.")
    stats = decp_db.compter_marches()
    print(f"  Total en base : {stats['total']} (montant>0 : {stats['avec_montant']}, "
          f"CPV : {stats['avec_cpv']}, acheteur SIRET : {stats['avec_acheteur']})")


def cmd_ingest_annee(args):
    # depuis/jusqua au format AAAA-MM → bornes de jour
    debut = f"{args.depuis}-01"
    y, m = int(args.jusqua[:4]), int(args.jusqua[5:7])
    fin_y, fin_m = (y + 1, 1) if m == 12 else (y, m + 1)
    fin = f"{fin_y:04d}-{fin_m:02d}-01"  # exclusif
    args.depuis, args.jusqua = debut, fin
    cmd_ingest(args)


def cmd_audit(args):
    from decp.audit import auditer
    print(auditer())


def main():
    ap = argparse.ArgumentParser(prog="decp.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest", help="download + parse + insert (date de début ISO)")
    pi.add_argument("--depuis", default=None, help="AAAA-MM-JJ (défaut: il y a 12 mois)")
    pi.add_argument("--jusqua", default=None, help="AAAA-MM-JJ exclusif (optionnel)")
    pi.add_argument("--dry-run", action="store_true")
    pi.add_argument("--limite", type=int, default=None)
    pi.set_defaults(func=cmd_ingest)

    pa = sub.add_parser("ingest-annee", help="12 mois consécutifs (AAAA-MM)")
    pa.add_argument("--depuis", required=True, help="AAAA-MM")
    pa.add_argument("--jusqua", required=True, help="AAAA-MM")
    pa.add_argument("--dry-run", action="store_true")
    pa.add_argument("--limite", type=int, default=None)
    pa.set_defaults(func=cmd_ingest_annee)

    pau = sub.add_parser("audit", help="audit qualité de la base DECP")
    pau.set_defaults(func=cmd_audit)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
