"""
tendia_monitoring.py
--------------------
Dashboard console de l'état des téléchargements DCE Tendia (production).

Lit la base SQLite (état DCE des marchés) + les logs JSONL (logs/*.jsonl écrits
par tendia_logs) et affiche : couverture DCE, derniers batchs, coûts du mois,
marchés en échec à reprendre. Pas de Flask, juste la console.

Usage : python tendia_monitoring.py [--jours N]
"""
import argparse
import sys
from collections import Counter, defaultdict
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import tendia_logs

# Tarifs (cohérents avec retelecharger_aws_achat_anti_ban).
COUT_BRIGHTDATA_USD_PAR_GB = 8.0
COUT_2CAPTCHA_USD_PAR_CAPTCHA = 0.001

ORDRE_CONTENU = ["complet", "incomplet", "auth_requise", "vide", "erreur"]


def _bloc_etat_dce(marches: dict) -> None:
    total = len(marches)
    par_contenu = Counter((m.get("dce_contenu") or "non_qualifie")
                          for m in marches.values())
    print(f"\nÉtat DCE de la base ({total} marchés)")
    cles = ORDRE_CONTENU + sorted(k for k in par_contenu if k not in ORDRE_CONTENU)
    for cle in cles:
        n = par_contenu.get(cle, 0)
        if n == 0 and cle not in ORDRE_CONTENU:
            continue
        pct = (100 * n / total) if total else 0
        print(f"  {cle:<14} : {n:<5} ({pct:.1f}%)")


def _bloc_batchs(evenements: list, jours: int) -> None:
    print(f"\nDerniers batchs ({jours} derniers jours)")
    # Agrège par (jour, downloader) : total, ok, ban.
    agg = defaultdict(lambda: {"total": 0, "ok": 0, "ban": 0})
    for e in evenements:
        jour = (e.get("timestamp") or "")[:10]
        cle = (jour, e.get("downloader") or "?")
        a = agg[cle]
        a["total"] += 1
        if e.get("ok"):
            a["ok"] += 1
        if str(e.get("etape_erreur") or "").startswith("ban"):
            a["ban"] += 1
    if not agg:
        print("  (aucun événement loggé — lance un batch puis reviens)")
        return
    for (jour, downloader), a in sorted(agg.items(), reverse=True):
        ban_txt = f"  ({a['ban']} ban)" if a["ban"] else ""
        print(f"  {jour}  {downloader:<12} {a['ok']}/{a['total']}{ban_txt}")


def _bloc_couts(jours: int) -> None:
    """Coûts du mois en cours, recalculés depuis les logs (bande + captchas)."""
    mois = datetime.now().strftime("%Y-%m")
    evts = tendia_logs.lire_evenements(depuis_jours=31)
    bw = sum((e.get("taille_octets") or 0) for e in evts
             if (e.get("timestamp") or "").startswith(mois))
    captchas = sum((e.get("nb_captcha_resolus") or 0) for e in evts
                   if (e.get("timestamp") or "").startswith(mois))
    cout_bd = bw / 1_000_000_000 * COUT_BRIGHTDATA_USD_PAR_GB
    cout_cap = captchas * COUT_2CAPTCHA_USD_PAR_CAPTCHA
    print(f"\nCoûts du mois en cours ({mois})")
    print(f"  Bright Data : ~${cout_bd:.2f} (estimé sur {bw / 1_000_000:.1f} Mo)")
    print(f"  2captcha    : ~${cout_cap:.2f} ({captchas} captchas)")
    print(f"  Total       : ~${cout_bd + cout_cap:.2f}")


def _bloc_echecs(evenements: list) -> None:
    """Marchés dont le dernier événement loggé est un échec (à reprendre)."""
    dernier = {}
    for e in evenements:
        mid = e.get("id_marche")
        if not mid:
            continue
        ts = e.get("timestamp") or ""
        if mid not in dernier or ts >= dernier[mid].get("timestamp", ""):
            dernier[mid] = e
    echecs = [(mid, e) for mid, e in dernier.items()
              if not e.get("ok") and not e.get("skip")]
    print(f"\nMarchés en échec à reprendre ({len(echecs)})")
    if not echecs:
        print("  (aucun)")
        return
    for mid, e in sorted(echecs)[:20]:
        print(f"  {mid} ({e.get('etape_erreur') or '?'})")
    if len(echecs) > 20:
        print(f"  ... +{len(echecs) - 20} autres")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jours", type=int, default=7,
                    help="Fenêtre (jours) pour les batchs/échecs récents.")
    args = ap.parse_args()

    print("=" * 62)
    print(f"  TENDIA MONITORING — {datetime.now().strftime('%d %B %Y %H:%M')}")
    print("=" * 62)

    marches = stockage.charger("marches") or {}
    evenements = tendia_logs.lire_evenements(depuis_jours=args.jours)

    _bloc_etat_dce(marches)
    _bloc_batchs(evenements, args.jours)
    _bloc_couts(args.jours)
    _bloc_echecs(evenements)
    print()


if __name__ == "__main__":
    main()
