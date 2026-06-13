"""
audit_briefs.py — qualité des briefs COMPLET en cache

Pour chaque brief stocké en collection 'briefs_extraits' avec _meta.type=complet :
- Indique si bareme_notation a été extrait (valeur_technique_pct rempli)
- Indique si montant_marche a été extrait (type != non_communique)
- Affiche la liste des PDFs traités et leur taille totale en chars
- Verdict : utile / partiel / vide
"""

import io
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage


def main():
    briefs = stockage.charger("briefs_extraits")

    complets = []
    for mid, b in briefs.items():
        meta = b.get("_meta") or {}
        # Heuristique : type=complet OU présence d'un bareme_notation au top-level
        if meta.get("type") == "complet" or "bareme_notation" in b:
            complets.append((mid, b))

    print(f"=== Audit qualité des briefs COMPLET ({len(complets)} en cache) ===\n")

    n_utiles = 0
    n_partiels = 0
    n_vides = 0

    for mid, b in complets:
        bareme = b.get("bareme_notation") or {}
        montant = b.get("montant_marche") or {}
        meta = b.get("_meta") or {}

        bareme_rempli = (bareme.get("valeur_technique_pct") is not None
                          or bareme.get("valeur_prix_pct") is not None)
        montant_rempli = montant.get("type") not in (None, "non_communique")

        pdfs = meta.get("pdfs_traites") or []
        noms_pdfs = [p.get("nom", "?") for p in pdfs]
        taille_totale = sum((p.get("taille_chars") or 0) for p in pdfs)

        if bareme_rempli and montant_rempli:
            verdict = "✓ UTILE"
            n_utiles += 1
        elif bareme_rempli or montant_rempli:
            verdict = "~ PARTIEL"
            n_partiels += 1
        else:
            verdict = "✗ VIDE"
            n_vides += 1

        print(f"[{mid}]  {verdict}")
        print(f"  bareme.valeur_technique_pct = {bareme.get('valeur_technique_pct')}")
        print(f"  bareme.valeur_prix_pct      = {bareme.get('valeur_prix_pct')}")
        print(f"  montant.type                = {montant.get('type')}")
        print(f"  montant.valeur_estimee_eur  = {montant.get('valeur_estimee_euros')}")
        print(f"  pdfs traités                = {noms_pdfs}")
        print(f"  taille totale (chars)       = {taille_totale:,}")
        print()

    print("─" * 78)
    print(f"  Synthèse : {n_utiles} utile(s), {n_partiels} partiel(s), {n_vides} vide(s)")
    if complets:
        pct_utile = 100 * n_utiles / len(complets)
        pct_au_moins_partiel = 100 * (n_utiles + n_partiels) / len(complets)
        print(f"  Taux utile          : {pct_utile:.0f}%")
        print(f"  Taux au moins partiel : {pct_au_moins_partiel:.0f}%")


if __name__ == "__main__":
    main()
