"""
regenerer_briefs_md.py
----------------------
Re-rend les briefs markdown (rapports/brief_<id>.md) à partir des JSON
d'extraction déjà en cache. NE FAIT AUCUN APPEL LLM (donc gratuit).

Utile après modification du template markdown dans `tendia_extraire._generer_brief()`
pour propager le changement aux briefs existants sans payer le re-LLM.

Usage :
    python regenerer_briefs_md.py                    # tous les briefs en cache
    python regenerer_briefs_md.py --type COMPLET     # uniquement les COMPLET
    python regenerer_briefs_md.py --id BOAMP-26-56729  # un brief précis
    python regenerer_briefs_md.py --dry-run          # sans écrire
"""

import argparse
import io
import json
import sys
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import stockage
import tendia_extraire


REPERTOIRE_BASE = Path(__file__).parent
REPERTOIRE_RAPPORTS = REPERTOIRE_BASE / "rapports"
REPERTOIRE_EXTRACTIONS = REPERTOIRE_BASE / "data" / "extractions"


def _charger_briefs() -> dict:
    """Charge briefs SQLite + fallback disque."""
    briefs = {}
    try:
        briefs = dict(stockage.charger("briefs_extraits") or {})
    except Exception as e:
        print(f"  ⚠ Erreur SQLite : {e}")
    if REPERTOIRE_EXTRACTIONS.exists():
        for f in REPERTOIRE_EXTRACTIONS.glob("*.json"):
            id_m = f.stem
            if id_m not in briefs:
                try:
                    briefs[id_m] = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    pass
    return briefs


def _type_brief(brief: dict) -> str:
    meta = brief.get("_meta") or {}
    t = (meta.get("type") or "").upper()
    if t in ("COMPLET", "LIGHT"):
        return t
    if any(k in brief for k in ("criteres_attribution", "modalites_consultation",
                                  "duree_estimee", "volume_estime")):
        return "COMPLET"
    return "INCONNU"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", help="Re-rend un brief précis")
    ap.add_argument("--type", choices=["COMPLET", "LIGHT", "INCONNU"],
                    help="Filtre par type de brief")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    marches = stockage.charger("marches") or {}
    briefs = _charger_briefs()

    print(f"  Marchés en base : {len(marches)}")
    print(f"  Briefs en cache : {len(briefs)}")

    REPERTOIRE_RAPPORTS.mkdir(parents=True, exist_ok=True)

    # Sélection des briefs à re-rendre
    if args.id:
        if args.id not in briefs:
            print(f"\n  ⚠ Aucun brief pour {args.id}")
            return
        a_rendre = {args.id: briefs[args.id]}
    elif args.type:
        a_rendre = {k: v for k, v in briefs.items()
                    if _type_brief(v) == args.type}
        print(f"  Filtre type={args.type} : {len(a_rendre)} brief(s)")
    else:
        a_rendre = briefs

    if not a_rendre:
        print("  Rien à faire.")
        return

    print(f"\n  Re-rendu de {len(a_rendre)} brief(s) markdown...")
    if args.dry_run:
        print("  (mode dry-run : aucune écriture)")

    nb_ok = 0
    nb_skip = 0
    nb_erreur = 0

    for id_m, brief in sorted(a_rendre.items()):
        marche = marches.get(id_m)
        if not marche:
            print(f"    ⊘ {id_m} : marché absent en base, skip")
            nb_skip += 1
            continue

        try:
            md = tendia_extraire._generer_brief(marche, brief)
        except Exception as e:
            print(f"    ❌ {id_m} : {type(e).__name__}: {e}")
            nb_erreur += 1
            continue

        chemin = REPERTOIRE_RAPPORTS / f"brief_{id_m}.md"
        if args.dry_run:
            print(f"    ⊘ {id_m} : {len(md)} chars (dry-run)")
        else:
            chemin.write_text(md, encoding="utf-8")
            print(f"    ✓ {id_m} : {chemin.name} ({len(md)} chars)")
        nb_ok += 1

    print(f"\n  Résultats : {nb_ok} OK, {nb_skip} skip, {nb_erreur} erreurs")


if __name__ == "__main__":
    main()
