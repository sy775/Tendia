"""
backfill_contacts_boamp.py
--------------------------
Backfill du champ `contact` sur les marchés BOAMP déjà en base.

Le connecteur extrait désormais le contact (correspondant) de l'avis BOAMP
(cf `connecteurs.boamp._extraire_contact`), mais les 422 marchés déjà ingérés
n'ont pas ce champ. Ce script re-récupère l'avis (champ `donnees`) par lots
via l'API ODS, en extrait le contact et met à jour chaque marché.

Réseau seul (API BOAMP publique, proxy OFF) — AUCUN coût LLM.

Usage : python backfill_contacts_boamp.py [--lot 30] [--dry-run] [--limit N]
"""
import argparse
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import truststore
truststore.inject_into_ssl()  # SSL via magasin système (sinon CERT verify fail)

import requests

import stockage
from connecteurs import boamp


def _lots(seq, taille):
    for i in range(0, len(seq), taille):
        yield seq[i:i + taille]


def _fetch_lot(idwebs):
    """Récupère {idweb: record} pour un lot d'idweb via l'API ODS."""
    where = "idweb in (" + ",".join(f"'{i}'" for i in idwebs) + ")"
    r = requests.get(boamp.BOAMP_URL,
                     params={"where": where, "limit": 100,
                             "select": "idweb,donnees,source_schema"},
                     timeout=60)
    r.raise_for_status()
    return {rec.get("idweb"): rec for rec in r.json().get("results", [])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lot", type=int, default=30, help="taille des lots API")
    ap.add_argument("--dry-run", action="store_true", help="n'écrit rien")
    ap.add_argument("--limit", type=int, default=None, help="limite (debug)")
    args = ap.parse_args()

    m = stockage.charger("marches") or {}
    cibles = [(mid, mk.get("reference_externe"))
              for mid, mk in sorted(m.items())
              if mid.startswith("BOAMP-") and mk.get("reference_externe")]
    if args.limit:
        cibles = cibles[:args.limit]

    print(f"=== BACKFILL CONTACT BOAMP — {len(cibles)} marchés "
          f"({'DRY-RUN' if args.dry_run else 'écriture'}) ===")

    maj = avec = sans = introuvable = erreurs = 0
    for lot in _lots(cibles, args.lot):
        idwebs = [idw for _, idw in lot]
        try:
            fetched = _fetch_lot(idwebs)
        except Exception as e:
            erreurs += len(lot)
            print(f"  ⚠ lot {idwebs[0]}… erreur API : {type(e).__name__}: {e}")
            time.sleep(1.0)
            continue
        for mid, idw in lot:
            rec = fetched.get(idw)
            if rec is None:
                introuvable += 1
                continue
            contact = boamp._extraire_contact(rec)
            if not args.dry_run:
                mk = stockage.lire("marches", mid) or m.get(mid)
                if mk is None:
                    continue
                mk["contact"] = contact
                stockage.ecrire("marches", mid, mk)
            maj += 1
            if contact and contact.get("email"):
                avec += 1
            else:
                sans += 1
        time.sleep(0.3)  # politesse API

    print("\n=== BILAN ===")
    print(f"Marchés traités       : {maj}")
    print(f"  avec email contact  : {avec}")
    print(f"  sans email          : {sans}")
    print(f"Avis introuvables API : {introuvable}")
    print(f"Erreurs lot           : {erreurs}")


if __name__ == "__main__":
    main()
