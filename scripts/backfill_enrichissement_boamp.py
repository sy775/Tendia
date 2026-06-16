"""
scripts/backfill_enrichissement_boamp.py — Sprint enrichissement BOAMP v2, Étape 3.

Re-fetch les avis BOAMP des 422 marchés Tendia existants (via www.boamp.fr — host
fiable, l'API datadila du connecteur étant indisponible) et applique
`extraire_champs_enrichissement` pour renseigner les ~31 champs v2. Met à jour la
collection KV `marches`. Logue la couverture par champ (dont % montant_estime > 0).

0 € LLM. Idempotent (ré-exécutable). Pattern progressif : --dry-run → --limite N → complet.

Usage : python scripts/backfill_enrichissement_boamp.py [--dry-run] [--limite N] [--workers 6]
"""
import argparse
import csv
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import truststore
truststore.inject_into_ssl()  # SSL Windows (convention Tendia)
import requests

import stockage
from connecteurs.boamp import extraire_champs_enrichissement, _CHAMPS_SUIVIS

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
API = "https://www.boamp.fr/api/explore/v2.1/catalog/datasets/boamp/records"


def _idweb(mid: str, mk: dict) -> str:
    return mk.get("reference_externe") or mid.replace("BOAMP-", "")


def _fetch_avis(idweb: str, timeout=30):
    try:
        r = requests.get(API, params={"where": f'idweb="{idweb}"'}, timeout=timeout)
        res = r.json().get("results") or []
        return res[0] if res else None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limite", type=int, default=None)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    marches = stockage.charger("marches") or {}
    items = sorted(marches.items())
    if args.limite:
        items = items[:args.limite]
    n = len(items)
    print(f"=== Backfill enrichissement BOAMP v2 — {n} marchés"
          f"{' [DRY-RUN]' if args.dry_run else ''} ===")
    if args.dry_run:
        print(f"  Re-fetch de {n} avis via {API} puis enrichissement (0 € LLM).")
        print("  [DRY-RUN] aucun appel réseau ni écriture.")
        return

    t0 = time.time()
    couverture = Counter()       # champs suivis renseignés
    montant_positif = 0
    fetch_ko = 0
    enrichis = 0
    schemas = Counter()

    def _traiter(item):
        mid, mk = item
        avis = _fetch_avis(_idweb(mid, mk))
        return mid, mk, avis

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, (mid, mk, avis) in enumerate(ex.map(_traiter, items), 1):
            if avis is None:
                fetch_ko += 1
            else:
                enr = extraire_champs_enrichissement(avis, source="boamp_refetch")
                mk.update(enr)
                stockage.ecrire("marches", mid, mk)
                enrichis += 1
                schemas[enr.get("source_schema_eforms") or "—"] += 1
                for c in _CHAMPS_SUIVIS:
                    if mk.get(c):
                        couverture[c] += 1
                if (mk.get("montant_estime_eur") or 0) > 0:
                    montant_positif += 1
            if i % 50 == 0:
                print(f"  …{i}/{n} (enrichis {enrichis}, fetch KO {fetch_ko})")

    dt = time.time() - t0
    pct_montant = 100.0 * montant_positif / enrichis if enrichis else 0.0

    print(f"\n=== Backfill terminé ({dt/60:.1f} min) ===")
    print(f"Marchés enrichis     : {enrichis}/{n}")
    print(f"Avis introuvables    : {fetch_ko}")
    print(f"\nCouverture par champ (renseigné / enrichis) :")
    for c in _CHAMPS_SUIVIS:
        v = couverture.get(c, 0)
        print(f"  {c:30} : {v:>4} ({100.0*v/enrichis if enrichis else 0:5.1f} %)")
    print(f"\nMontant estimé > 0   : {montant_positif}/{enrichis} ({pct_montant:.1f} %)")
    if pct_montant < 30:
        print(f"  ⚠ < 30 % → la tranche de montant NE sera PAS utilisée comme critère "
              "de triangulation (limitation documentée, cf. RAPPORT_ENRICHISSEMENT_BOAMP.md).")
    else:
        print(f"  ✓ ≥ 30 % → tranche de montant exploitable pour la triangulation.")
    print(f"\nVersions schéma eForms : " + ", ".join(f"{k}={v}" for k, v in schemas.most_common()))

    # Dump couverture pour le rapport
    path = os.path.join(DATA, "couverture_enrichissement_boamp.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["champ", "renseignes", "total_enrichis", "pct"])
        for c in _CHAMPS_SUIVIS:
            v = couverture.get(c, 0)
            w.writerow([c, v, enrichis, round(100.0*v/enrichis, 1) if enrichis else 0])
        w.writerow(["montant_estime_eur>0", montant_positif, enrichis, round(pct_montant, 1)])
    print(f"\nCouverture détaillée : {path}")


if __name__ == "__main__":
    main()
