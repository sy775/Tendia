"""
diagnostic_natures_boamp.py
---------------------------
Re-interroge l'API BOAMP pour 20 marchés sans url_dce et regarde leur
nature : avis de marché (DCE attendu) vs avis d'attribution (DCE non
pertinent, marché déjà attribué).

Si la majorité sont des avis d'attribution, ça confirme que les 239 sans
url_dce ne sont pas une "perte" mais un état NORMAL du pipeline. La
Phase 4 d'extraction d'URL devient alors caduque sur ce flux.

Usage :
    python diagnostic_natures_boamp.py            # 20 marchés
    python diagnostic_natures_boamp.py --n 50     # plus large
"""

import argparse
import io
import sys
from collections import Counter

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import stockage
import dce_finder


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20, help="Taille échantillon")
    args = ap.parse_args()

    marches = stockage.charger("marches")
    sans_url = [m for m in marches.values()
                if not m.get("url_dce") and m.get("source") == "BOAMP"]
    echantillon = sans_url[:args.n]

    print("=" * 70)
    print(f"  Re-interroge BOAMP pour {len(echantillon)} marchés sans url_dce")
    print(f"  (sur {len(sans_url)} marchés sans url_dce au total)")
    print("=" * 70)
    print()

    natures = Counter()
    branches_eforms = Counter()
    api_404 = 0
    exemples_par_nature = {}

    for i, m in enumerate(echantillon, 1):
        ref = m.get("reference_externe", "")
        record = dce_finder._fetch_record_boamp(ref)
        if not record:
            api_404 += 1
            continue

        nature = record.get("nature_libelle") or "(nature non renseignée)"
        natures[nature] += 1
        exemples_par_nature.setdefault(nature, []).append(
            f"{m['id']} ({(m.get('acheteur_nom') or '')[:35]})"
        )

        # Branches EFORMS rencontrées
        donnees = dce_finder._parser_donnees(record)
        eforms = donnees.get("EFORMS") or {}
        for k in eforms.keys():
            branches_eforms[k] += 1

        if i % 5 == 0:
            print(f"  ... {i}/{len(echantillon)} marchés interrogés")

    print()
    print("-" * 70)
    print("  Distribution par nature (BOAMP nature_libelle)")
    print("-" * 70)
    for nat, n in natures.most_common():
        pct = 100 * n / max(1, sum(natures.values()))
        print(f"  {n:3d} ({pct:4.0f}%)  {nat}")

    print()
    print("-" * 70)
    print("  Branches EFORMS rencontrées")
    print("-" * 70)
    for br, n in branches_eforms.most_common():
        print(f"  {n:3d}  {br}")

    print()
    if api_404:
        print(f"  ⚠ {api_404} marchés non retrouvés via l'API (404)")
    print()

    # Verdict
    nb_attribution = sum(n for nat, n in natures.items()
                         if "attribution" in (nat or "").lower())
    nb_marche = sum(n for nat, n in natures.items()
                    if "attribution" not in (nat or "").lower()
                    and nat != "(nature non renseignée)")

    print("-" * 70)
    print("  VERDICT")
    print("-" * 70)
    if nb_attribution > nb_marche:
        print(f"  ✓ Hypothèse confirmée : {nb_attribution} avis d'attribution vs {nb_marche} avis de marché.")
        print(f"    Les marchés sans url_dce sont essentiellement des marchés DÉJÀ ATTRIBUÉS.")
        print(f"    Pas de gain attendu côté Phase 4 (extraction URL DCE).")
        print(f"    → Si tu veux les utiliser pour de l'analyse concurrence (titulaires,")
        print(f"      montants), c'est l'objet de marches_attribues.py / decp.py.")
    else:
        print(f"  ⚠ Pas d'avis d'attribution majoritaire : {nb_attribution} attribution vs {nb_marche} marché.")
        print(f"    La Phase 4 (extraction URL DCE améliorée) reste potentiellement utile.")
        print(f"    À investiguer : pourquoi des avis de marché actifs n'ont-ils pas d'URL eForms ?")


if __name__ == "__main__":
    main()
