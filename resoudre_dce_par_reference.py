"""
resoudre_dce_par_reference.py
-----------------------------
Batch : pour les avis de marché SANS url_dce, tente de résoudre la consultation
via plateforme + référence (cf resolution_reference). Persiste url_dce +
url_dce_source='recherche_reference'. Les marchés résolus sont ensuite
téléchargeables par le pipeline DCE normal.

Usage : python resoudre_dce_par_reference.py [--limite N] [--dry-run]
"""
import argparse
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import resolution_reference as RR

RATE_LIMIT_SEC = 1.5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    marches = stockage.charger("marches") or {}
    cibles = [(mid, m) for mid, m in sorted(marches.items())
              if isinstance(m, dict)
              and m.get("nature_libelle") == "Avis de marché"
              and not m.get("url_dce")
              and RR.est_moteur_atexo(RR.extraire_plateforme_reference(m)[0] or "")]
    if args.limite:
        cibles = cibles[:args.limite]

    print(f"=== RÉSOLUTION url_dce PAR RÉFÉRENCE (moteur Atexo) ===")
    print(f"Avis sans-URL sur moteur Atexo : {len(cibles)}\n")

    resolus = 0
    for i, (mid, m) in enumerate(cibles, 1):
        base, ref = RR.extraire_plateforme_reference(m)
        url = RR.resoudre_url_via_reference(m)
        if url:
            resolus += 1
            print(f"  [{i}/{len(cibles)}] {mid} : {base} (réf {ref}) → ✅ {url[:60]}")
            if not args.dry_run:
                m["url_dce"] = url
                m["url_dce_source"] = "recherche_reference"
                stockage.ecrire("marches", mid, m)
        else:
            print(f"  [{i}/{len(cibles)}] {mid} : {base} (réf {ref}) → introuvable")
        if i < len(cibles):
            time.sleep(RATE_LIMIT_SEC)

    print(f"\n⇒ {resolus}/{len(cibles)} url_dce résolues"
          f"{' (dry-run, non persisté)' if args.dry_run else ''}")
    if resolus and not args.dry_run:
        print("⇒ Télécharger : python tendia_telecharger_dce.py  (ou retelecharger_incomplet.py)")


if __name__ == "__main__":
    main()
