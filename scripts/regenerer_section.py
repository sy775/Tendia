# -*- coding: utf-8 -*-
"""
CLI runner — RÉGÉNÉRATION D'UNE SECTION (Sprint B).

Recharge une mémoire existante, relance l'appel 2 sur une seule section avec
une instruction d'ajustement, met à jour le JSON en base et ré-assemble le .docx.

Exemple :
  python scripts/regenerer_section.py \
    --memoire-id memoire__BOAMP-26-56995__lot_2__demo_btp__20260621T140000 \
    --section-id moyens_humains \
    --instruction "Insiste davantage sur notre expérience en zone urbaine dense"

  # Estimation du coût sans appel LLM
  python scripts/regenerer_section.py --memoire-id ... --section-id ... \
    --instruction "..." --dry-run
"""
import argparse
import os
import sys

# --- Standards Tendia : stdout UTF-8 forcé + racine projet importable ---
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import regeneration_section  # noqa: E402


def main():
    p = argparse.ArgumentParser(description="Régénération d'une section de mémoire (Sprint B).")
    p.add_argument("--memoire-id", type=str, required=True, help="Clé de la mémoire en base (collection memoires_techniques).")
    p.add_argument("--section-id", type=str, required=True, help="section_id à régénérer (doit exister dans le plan).")
    p.add_argument("--instruction", type=str, required=True, help="Instruction d'ajustement du candidat.")
    p.add_argument("--dry-run", action="store_true", help="Estime le coût sans appel LLM.")
    p.add_argument("--max-cout", type=float, default=None, help="Plafond € pour la régénération (abort si dépassé).")
    args = p.parse_args()

    try:
        regeneration_section.regenerer_section(
            args.memoire_id, args.section_id, args.instruction,
            dry_run=args.dry_run, max_cout_eur=args.max_cout, verbose=True)
    except Exception as e:
        print(f"❌ {type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
