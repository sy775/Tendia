"""
tendia_reextraire_batch.py
--------------------------
Ré-extrait tous les marchés qui ont un dossier DCE local.

Usage typique : après une modification du prompt LLM (`llm_extract.py`),
relancer pour bénéficier des nouveaux champs sur les briefs existants.

Workflow :
    1. Scanne data/dce/ pour trouver les dossiers de marchés
    2. Demande confirmation avec une estimation du coût API
    3. Pour chaque marché, lance `tendia_extraire.py --marche <id> --force`

Usage :
    python tendia_reextraire_batch.py             # interactif (confirmation)
    python tendia_reextraire_batch.py --oui       # sans confirmation (batch script)
    python tendia_reextraire_batch.py --dry-run   # liste seulement, n'extrait rien
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


_BASE_DIR = Path(__file__).resolve().parent
REPERTOIRE_DCE = _BASE_DIR / "data" / "dce"


def lister_marches_avec_dce() -> list:
    """Retourne les ids de marchés qui ont au moins un PDF dans leur dossier DCE."""
    if not REPERTOIRE_DCE.is_dir():
        return []
    marches = []
    for d in sorted(os.listdir(REPERTOIRE_DCE)):
        chemin = REPERTOIRE_DCE / d
        if not chemin.is_dir():
            continue
        # Vérifier qu'il y a au moins un PDF
        pdfs = [f for f in os.listdir(chemin) if f.lower().endswith(".pdf")]
        if pdfs:
            marches.append((d, len(pdfs)))
    return marches


def main():
    parser = argparse.ArgumentParser(
        description="Ré-extrait en batch tous les marchés avec DCE local."
    )
    parser.add_argument("--oui", action="store_true",
                        help="Pas de prompt de confirmation (batch script).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Liste les marchés sans appeler l'API.")
    args = parser.parse_args()

    marches = lister_marches_avec_dce()

    print()
    print("=" * 78)
    print("  TENDIA — Ré-extraction batch")
    print("=" * 78)

    if not marches:
        print(f"  Aucun marché avec DCE local trouvé dans {REPERTOIRE_DCE}")
        print(f"  Dépose les PDF dans data/dce/<id_marche>/ puis relance.")
        return

    print(f"  Marchés trouvés : {len(marches)}")
    for mid, nb_pdfs in marches:
        print(f"    - {mid} ({nb_pdfs} PDF)")

    # Estimation très approximative
    print()
    print(f"  Estimation coût : ~{0.05 * len(marches):.2f} $ "
          f"(1 appel API Anthropic par marché, ~5¢ chacun)")
    print(f"  Chaque extraction prend ~20-60 secondes.")

    if args.dry_run:
        print()
        print(f"  Mode dry-run : aucune extraction lancée.")
        return

    if not args.oui:
        print()
        confirm = input("  Continuer ? [o/N] : ").strip().lower()
        if confirm not in ("o", "oui", "y", "yes"):
            print("  Annulé.")
            return

    # Exécution
    print()
    print("=" * 78)
    succes = 0
    echecs = 0
    for i, (mid, _) in enumerate(marches, 1):
        print()
        print(f"  [{i}/{len(marches)}] Ré-extraction de {mid}")
        print("─" * 78)
        try:
            r = subprocess.run(
                [sys.executable, "tendia_extraire.py", "--marche", mid, "--force"],
                check=False,
            )
            if r.returncode == 0:
                succes += 1
            else:
                echecs += 1
                print(f"  ⚠ Code retour non nul : {r.returncode}")
        except Exception as e:
            echecs += 1
            print(f"  ❌ Exception : {type(e).__name__}: {e}")

    print()
    print("=" * 78)
    print(f"  TERMINÉ : {succes} succès, {echecs} échec(s) sur {len(marches)} marchés")
    print("=" * 78)


if __name__ == "__main__":
    main()
