"""
scripts/rederiver_criteres_plat.py — re-dérive `criteres_attribution_plat` + flags
depuis le `bareme_notation` DÉJÀ STOCKÉ (0 € : aucun appel LLM).

Corrige l'effet des bugs de dérivation D1 (sous-critères absolus écrasés par un
`valeur_technique_pct` sous-renseigné) et D2 (partie technique évaporée quand les
sous-critères ne sont pas pondérés). Mesure les alertes somme/pas_de_prix avant/après.

Usage : python scripts/rederiver_criteres_plat.py [--dry-run]
"""
import argparse
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stockage
import llm_extract as L


def _flags(b):
    return (bool(b.get("criteres_alerte_somme_incorrecte")),
            bool(b.get("criteres_alerte_pas_de_prix")),
            bool(b.get("criteres_alerte_non_classes")),
            bool(b.get("extraction_v2_a_verifier")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    be = stockage.charger("briefs_extraits") or {}
    v2 = [(mid, b) for mid, b in be.items() if str(b.get("version_extraction_llm")) == "2"]
    print(f"=== Re-dérivation critères plat — {len(v2)} briefs v2"
          f"{' [DRY-RUN]' if args.dry_run else ''} ===")

    avant = Counter()
    apres = Counter()
    changed = []
    for mid, b in v2:
        s0, p0, n0, v0 = _flags(b)
        avant["somme"] += s0; avant["pas_de_prix"] += p0
        avant["non_classe"] += n0; avant["a_verifier"] += v0

        # Re-dérive depuis le barème stocké (non destructif sur bareme_notation).
        L.post_traiter_extraction_v2(b)

        s1, p1, n1, v1 = _flags(b)
        apres["somme"] += s1; apres["pas_de_prix"] += p1
        apres["non_classe"] += n1; apres["a_verifier"] += v1
        if (s0, p0, v0) != (s1, p1, v1):
            changed.append((mid, (s0, p0, v0), (s1, p1, v1)))

        if not args.dry_run:
            stockage.ecrire("briefs_extraits", mid, b)

    def _ligne(k):
        return f"  {k:14} : {avant[k]:3} → {apres[k]:3}  (Δ {apres[k]-avant[k]:+d})"
    print("\nAlertes (avant → après) :")
    for k in ("somme", "pas_de_prix", "non_classe", "a_verifier"):
        print(_ligne(k))
    print(f"\nBriefs dont les flags changent : {len(changed)}")
    for mid, av, ap_ in changed[:15]:
        print(f"  {mid} : somme/prix/verif {av} → {ap_}")
    if len(changed) > 15:
        print(f"  … +{len(changed)-15} autres")
    if args.dry_run:
        print("\n[DRY-RUN] aucune écriture.")


if __name__ == "__main__":
    main()
