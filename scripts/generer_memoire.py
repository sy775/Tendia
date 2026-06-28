# -*- coding: utf-8 -*-
"""
CLI runner — GÉNÉRATION D'UNE MÉMOIRE TECHNIQUE .docx (Sprint B).

Orchestration : appel 1 (extraction contexte → plan) + appel 2 (rédaction) +
assemblage .docx + stockage en base (collection memoires_techniques). LAZY :
aucune intégration au pipeline batch d'extraction.

Exemples :
  # Génération complète
  python scripts/generer_memoire.py --id-marche BOAMP-26-56995 --numero-lot 2 --id-user demo_btp
  # Dry-run (estimation des coûts des 2 appels, aucun appel LLM)
  python scripts/generer_memoire.py --id-marche BOAMP-26-56995 --numero-lot 2 --id-user demo_btp --dry-run
  # Cap budget total (€)
  python scripts/generer_memoire.py --id-marche ... --numero-lot 2 --id-user demo_btp --max-cout 6.00
  # Forcer la régénération si une mémoire existe déjà
  python scripts/generer_memoire.py --id-marche ... --numero-lot 2 --id-user demo_btp --force
  # Batch de validation (3 mémoires stratifiées → data/memoires/ + data/validation_memoires/)
  python scripts/generer_memoire.py --batch-validation
"""
import argparse
import glob
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
from services import _memoire_commun as commun  # noqa: E402
# Orchestration mutualisée CLI + UI (source unique).
from services.pipeline_memoire import (  # noqa: E402
    generer_memoire,
    cle_memoire_existante as _memoire_existante,
)

REPERTOIRE_VALIDATION = os.path.join("data", "validation_memoires")
REPERTOIRE_PROFILS_DEMO = commun.REPERTOIRE_PROFILS_DEMO

# Échantillon stratifié (cf. spec). (catégorie, id_marche, numero_lot, id_user)
ECHANTILLON_VALIDATION = [
    ("BTP gros œuvre",   "BOAMP-26-56995", 2, "demo_btp"),
    ("IT infogérance",   "BOAMP-26-56097", 1, "demo_it"),
    ("Ingénierie / MOE", "BOAMP-26-56090", 1, "demo_ing"),
]


# ---------------------------------------------------------------------------
# Utilitaires batch / stockage
# ---------------------------------------------------------------------------

def _backup_sqlite() -> str:
    db = stockage.chemin_db()
    horod = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = f"{db}.bak_avant_memoire_{horod}"
    shutil.copy2(db, dest)
    print(f"  💾 Backup SQLite : {dest}")
    return dest


def _ingester_profils_demo():
    """Charge les profils fictifs data/profils_demo/*.json dans la collection
    'organisme' (idempotent). Procédure de fin de sprint, étape 2."""
    fichiers = sorted(glob.glob(os.path.join(REPERTOIRE_PROFILS_DEMO, "*.json")))
    for chemin in fichiers:
        with open(chemin, encoding="utf-8") as f:
            prof = json.load(f)
        pid = prof.get("id") or os.path.splitext(os.path.basename(chemin))[0]
        stockage.ecrire("organisme", pid, prof)
        print(f"  ➕ Profil démo ingéré en base (organisme/{pid}).")


def _dump_validation(memoire: dict) -> str:
    os.makedirs(REPERTOIRE_VALIDATION, exist_ok=True)
    nom = f"{memoire['id_marche']}_lot_{memoire['numero_lot']}_{memoire['id_user']}.json"
    chemin = os.path.join(REPERTOIRE_VALIDATION, nom)
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(memoire, f, ensure_ascii=False, indent=2)
    return chemin


# ---------------------------------------------------------------------------
# Batch de validation
# ---------------------------------------------------------------------------

def _batch_validation(args):
    print("=" * 74)
    print("  MÉMOIRE TECHNIQUE — BATCH DE VALIDATION (audit manuel Younes)")
    print("=" * 74)
    if not args.dry_run:
        _backup_sqlite()
        print("\n  Ingestion des profils organisme fictifs :")
        _ingester_profils_demo()

    cibles = ECHANTILLON_VALIDATION
    if args.limite:
        cibles = cibles[: args.limite]

    t0 = time.time()
    faits, cout_total, c1_total, c2_total = 0, 0.0, 0.0, 0.0
    recap = []
    for i, (categorie, mid, lot, id_user) in enumerate(cibles, 1):
        print("\n" + "-" * 74)
        print(f"  [{i}/{len(cibles)}] {categorie} — {mid} lot {lot} — {id_user}")
        if not stockage.lire("briefs_extraits", mid):
            print(f"  ⚠ WARNING : brief absent pour {mid} — '{categorie}' skippée.")
            continue
        if not os.path.isdir(os.path.join("data", "dce", mid)):
            print(f"  ⚠ WARNING : DCE absent pour {mid} — '{categorie}' skippée.")
            continue
        try:
            m = generer_memoire(mid, lot, id_user, force=args.force,
                                max_cout_eur=args.max_cout, dry_run=args.dry_run,
                                verbose=True)
        except Exception as e:
            print(f"  ❌ ERREUR {mid} lot {lot} : {type(e).__name__}: {e}")
            continue
        if m and not args.dry_run:
            faits += 1
            meta = m.get("_meta") or {}
            cout_total += meta.get("cout_total_eur") or 0
            c1_total += meta.get("cout_appel_1_eur") or 0
            c2_total += meta.get("cout_appel_2_eur") or 0
            chemin_json = _dump_validation(m)
            recap.append((categorie, m["chemin_docx"], chemin_json))

    duree = round(time.time() - t0, 1)
    print("\n" + "=" * 74)
    print(f"  RÉSUMÉ : {faits} mémoire(s) · {cout_total:.3f} € "
          f"(appel 1 : {c1_total:.3f} € · appel 2 : {c2_total:.3f} €) · {duree}s")
    if recap:
        print("\n  Livrables pour audit :")
        for cat, docx, js in recap:
            print(f"    • {cat}")
            print(f"        .docx : {docx}")
            print(f"        JSON  : {js}")
        print("\n  Ouvrir un .docx (Windows) :  start \"\" \"<chemin .docx>\"")
        print("  (À l'ouverture, accepter « Mettre à jour les champs » pour le sommaire.)")
    print("=" * 74)


def _unitaire(args):
    if not args.id_marche or args.numero_lot is None or not args.id_user:
        print("❌ --id-marche, --numero-lot et --id-user sont requis (hors --batch-validation).")
        sys.exit(2)
    generer_memoire(args.id_marche, args.numero_lot, args.id_user, force=args.force,
                    max_cout_eur=args.max_cout, dry_run=args.dry_run, verbose=True)


def main():
    p = argparse.ArgumentParser(description="Génération d'une mémoire technique .docx (Sprint B).")
    p.add_argument("--id-marche", type=str, default=None)
    p.add_argument("--numero-lot", type=int, default=None)
    p.add_argument("--id-user", type=str, default=None, help="Profil organisme (base 'organisme' ou data/profils_demo/).")
    p.add_argument("--dry-run", action="store_true", help="Estime le coût des 2 appels sans appel LLM.")
    p.add_argument("--force", action="store_true", help="Régénère même si une mémoire existe.")
    p.add_argument("--max-cout", type=float, default=None, help="Plafond € total (abort si l'estimation dépasse).")
    p.add_argument("--limite", type=int, default=None, help="Cap du nombre de mémoires en batch.")
    p.add_argument("--batch-validation", action="store_true", help="Génère l'échantillon stratifié de validation.")
    args = p.parse_args()

    if args.batch_validation:
        _batch_validation(args)
    else:
        _unitaire(args)


if __name__ == "__main__":
    main()
