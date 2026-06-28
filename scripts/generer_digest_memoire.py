# -*- coding: utf-8 -*-
"""
CLI runner — DIGEST MÉMOIRE (Sprint A).

Génère à la demande un digest narratif par lot (matière première du futur
générateur de mémoire technique). LAZY : aucune intégration au pipeline batch.

Exemples :
  # Unitaire
  python scripts/generer_digest_memoire.py --id-marche BOAMP-26-56326 --numero-lot 1
  # Dry-run (estimation coût, aucun appel LLM)
  python scripts/generer_digest_memoire.py --id-marche BOAMP-26-56326 --numero-lot 1 --dry-run
  # Forcer la régénération
  python scripts/generer_digest_memoire.py --id-marche BOAMP-26-56326 --numero-lot 1 --force
  # Cap budget par digest
  python scripts/generer_digest_memoire.py --id-marche XXX --numero-lot 1 --max-cout 0.50
  # Batch de validation (5 digests stratifiés → data/validation_digests/)
  python scripts/generer_digest_memoire.py --batch-validation
"""
import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone

# --- Standards Tendia : stdout UTF-8 forcé + racine projet importable ---
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stockage  # noqa: E402
from services import digest_memoire  # noqa: E402

REPERTOIRE_VALIDATION = os.path.join("data", "validation_digests")

# Échantillon stratifié pour la validation manuelle de Younes.
# Hardcodé (cf. spec) mais validé à l'exécution (brief + lot + DCE présents) ;
# si une cible manque, on la skippe avec un warning.
ECHANTILLON_VALIDATION = [
    ("BTP gros œuvre",       "BOAMP-26-56995", 2),
    ("BTP multi-corps",      "BOAMP-26-55979", 1),
    ("IT infogérance",       "BOAMP-26-56097", 1),
    ("Ingénierie / MOE",     "BOAMP-26-56090", 1),
    ("Conseil / services",   "BOAMP-26-56280", 1),
]


def _backup_sqlite() -> str:
    """Backup du fichier SQLite avant un run batch (standard Tendia)."""
    db = stockage.chemin_db()
    horod = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = f"{db}.bak_avant_digest_{horod}"
    shutil.copy2(db, dest)
    print(f"  💾 Backup SQLite : {dest}")
    return dest


def _dump_validation(digest: dict):
    os.makedirs(REPERTOIRE_VALIDATION, exist_ok=True)
    nom = f"{digest['id_marche']}_lot_{digest['numero_lot']}.json"
    chemin = os.path.join(REPERTOIRE_VALIDATION, nom)
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(digest, f, ensure_ascii=False, indent=2)
    return chemin


def _batch_validation(args):
    print("=" * 74)
    print("  DIGEST MÉMOIRE — BATCH DE VALIDATION (audit manuel Younes)")
    print("=" * 74)
    if not args.dry_run:
        _backup_sqlite()

    cibles = ECHANTILLON_VALIDATION
    if args.limite:
        cibles = cibles[: args.limite]

    t0 = time.time()
    faits, cout_total, chemins = 0, 0.0, []
    for i, (categorie, mid, lot) in enumerate(cibles, 1):
        print("\n" + "-" * 74)
        print(f"  [{i}/{len(cibles)}] {categorie} — {mid} lot {lot}")
        # Garde-fou : cible réellement disponible ?
        b = stockage.lire("briefs_extraits", mid)
        if not b:
            print(f"  ⚠ WARNING : brief absent pour {mid} — catégorie '{categorie}' skippée.")
            continue
        if not os.path.isdir(os.path.join("data", "dce", mid)):
            print(f"  ⚠ WARNING : DCE absent pour {mid} — catégorie '{categorie}' skippée.")
            continue
        try:
            d = digest_memoire.generer_digest_memoire_lot(
                mid, lot, force=args.force, max_cout_eur=args.max_cout,
                dry_run=args.dry_run, verbose=True)
        except Exception as e:
            print(f"  ❌ ERREUR {mid} lot {lot} : {type(e).__name__}: {e}")
            continue
        if d and not args.dry_run:
            faits += 1
            cout_total += (d.get("_meta") or {}).get("cout_eur") or 0
            chemins.append(_dump_validation(d))

    duree = round(time.time() - t0, 1)
    print("\n" + "=" * 74)
    print(f"  RÉSUMÉ : {faits} digest(s) généré(s) · {cout_total:.3f} € · {duree}s")
    if chemins:
        print(f"  Dumps pour audit ({REPERTOIRE_VALIDATION}/) :")
        for c in chemins:
            print(f"    - {c}")
        print("\n  Pour relire un digest en console :")
        ex = chemins[0]
        print(f"    python -c \"import json,sys; "
              f"print(json.dumps(json.load(open(r'{ex}',encoding='utf-8'))['digest'],"
              f"ensure_ascii=False,indent=2))\"")
    print("=" * 74)


def _unitaire(args):
    if not args.id_marche or args.numero_lot is None:
        print("❌ --id-marche et --numero-lot sont requis (hors --batch-validation).")
        sys.exit(2)
    d = digest_memoire.generer_digest_memoire_lot(
        args.id_marche, args.numero_lot, force=args.force,
        max_cout_eur=args.max_cout, dry_run=args.dry_run, verbose=True)
    if d and not args.dry_run:
        print(f"\n  Digest prêt : {digest_memoire.cle_digest(args.id_marche, args.numero_lot)}")


def main():
    p = argparse.ArgumentParser(description="Génération d'un digest mémoire par lot (Sprint A).")
    p.add_argument("--id-marche", type=str, default=None)
    p.add_argument("--numero-lot", type=int, default=None)
    p.add_argument("--dry-run", action="store_true", help="Estime le coût sans appel LLM.")
    p.add_argument("--force", action="store_true", help="Régénère même si un digest existe.")
    p.add_argument("--max-cout", type=float, default=None, help="Plafond € par digest (abort si dépassé).")
    p.add_argument("--limite", type=int, default=None, help="Cap du nombre de digests en batch.")
    p.add_argument("--batch-validation", action="store_true",
                   help="Génère l'échantillon stratifié de validation.")
    args = p.parse_args()

    if args.batch_validation:
        _batch_validation(args)
    else:
        _unitaire(args)


if __name__ == "__main__":
    main()
