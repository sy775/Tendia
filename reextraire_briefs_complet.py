"""
reextraire_briefs_complet.py
----------------------------
Re-génère le brief LLM des marchés passés à `dce_contenu == "complet"` dont le
brief n'a pas encore été produit avec le DCE complet. Backup du brief existant.

Nécessite réseau + API (coût LLM ~0,05€/brief). Confirmation interactive.
Usage : python reextraire_briefs_complet.py [--oui] [--limite N]
"""
import argparse
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import stockage
import enrichir_complet


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--oui", action="store_true", help="Pas de confirmation interactive.")
    ap.add_argument("--limite", type=int, default=None, help="Max de marchés à re-extraire.")
    args = ap.parse_args()

    marches = stockage.charger("marches") or {}
    briefs = stockage.charger("briefs_extraits") or {}

    cibles = []
    for mid, m in sorted(marches.items()):
        if m.get("dce_contenu") != "complet":
            continue
        b = briefs.get(mid)
        if b and b.get("genere_avec_dce_complet"):
            continue  # déjà à jour
        cibles.append(mid)

    if args.limite:
        cibles = cibles[:args.limite]

    print("=== RE-EXTRACTION (briefs depuis DCE complet) ===")
    print(f"Cibles : {len(cibles)} marchés")
    cout = len(cibles) * 0.05
    print(f"Coût LLM estimé : ~{cout:.2f} €")
    if not cibles:
        return
    if not args.oui:
        try:
            input("Appuie sur Entrée pour lancer (Ctrl+C pour annuler)... ")
        except (EOFError, KeyboardInterrupt):
            print("\nAnnulé.")
            return

    refait = 0
    for mid in cibles:
        if mid in briefs:
            stockage.ecrire("briefs_extraits", f"{mid}.bak_avant_complet", briefs[mid])
        # Re-extraction via le pipeline standard (DL + qualif + brief, force).
        enrichir_complet.enrichir(ids=[mid], force=True, verbose=True)
        b = stockage.lire("briefs_extraits", mid)
        if b:
            b["genere_avec_dce_complet"] = True
            stockage.ecrire("briefs_extraits", mid, b)
            refait += 1

    print(f"\n⇒ {refait} briefs re-générés avec DCE complet.")
    print("Compare avant/après : briefs_extraits/<id> vs briefs_extraits/<id>.bak_avant_complet")


if __name__ == "__main__":
    main()
