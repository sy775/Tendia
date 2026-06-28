# -*- coding: utf-8 -*-
"""
Réextraction d'un ÉCHANTILLON varié avec le prompt v3 (grille_actions intégrée).
Force la réextraction (ignore le SHA) pour valider la qualité avant le parc complet.

Usage : python reextraire_echantillon_grille.py
"""
import os
import sys

# stdout/stderr en UTF-8 : sans ça, un print contenant un caractère spécial
# (ex. « Σ ») plante en cp1252 sur Windows et interrompt la ré-extraction.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import pdf_extract
import tendia_extraire
import stockage

ECHANTILLON = [
    "BOAMP-26-51023",  # insertion, 1 lot (mono)
    "BOAMP-26-56310",  # formation, barème profond (sous-critères)
    "BOAMP-26-56090",  # ingénierie / MOE, 2 lots
    "BOAMP-26-56326",  # BTP + ingénierie, 2 lots / 2 domaines
    "BOAMP-26-56995",  # énergie + BTP, 9 lots / 5 domaines (hétérogène)
    "BOAMP-26-55979",  # BTP, 15 lots / 4 domaines (gros multi-lot)
]


def _feuilles_avec_grille(noeuds):
    """(nb feuilles, nb feuilles avec grille_actions, somme poids cohérente)."""
    nb = nb_g = nb_ok = 0
    for n in noeuds or []:
        if not isinstance(n, dict):
            continue
        enfants = [c for c in (n.get("sous_criteres") or []) if isinstance(c, dict)]
        if enfants:
            a, b, c = _feuilles_avec_grille(enfants)
            nb += a; nb_g += b; nb_ok += c
        else:
            nb += 1
            ga = n.get("grille_actions") or []
            if ga:
                nb_g += 1
                if sum(int(x.get("poids_pct") or 0) for x in ga) == 100:
                    nb_ok += 1
    return nb, nb_g, nb_ok


def main():
    ids = sys.argv[1:] or ECHANTILLON
    print(f"=== Réextraction échantillon (prompt v3 grille) — {len(ids)} marchés ===\n")
    for i, mid in enumerate(ids, 1):
        dossier = os.path.join("data", "dce", mid)
        if not os.path.isdir(dossier):
            print(f"[{i}/{len(ids)}] {mid} : SKIP (pas de DCE)")
            continue
        try:
            tendia_extraire._dezipper_dossier(dossier, verbose=False)
            pdfs = pdf_extract.extraire_dossier(dossier, verbose=False)
            if not pdfs:
                print(f"[{i}/{len(ids)}] {mid} : SKIP (aucun PDF)")
                continue
            # backup
            old = stockage.lire("briefs_extraits", mid)
            if old:
                stockage.ecrire("briefs_extraits", f"{mid}.bak_avant_v3grille", old)
            r = tendia_extraire.traiter_marche(mid, dossier, pdfs, dry_run=False, verbose=False)
            if not r.get("ok"):
                print(f"[{i}/{len(ids)}] {mid} : ECHEC {r.get('erreur') or r.get('raison')}")
                continue
            b = stockage.lire("briefs_extraits", mid)
            sc = (b.get("bareme_notation") or {}).get("sous_criteres_techniques") or []
            nb, nb_g, nb_ok = _feuilles_avec_grille(sc)
            cout = float((b.get("_meta") or {}).get("cout_eur") or 0)
            print(f"[{i}/{len(ids)}] {mid} : OK ({cout:.2f} €) — "
                  f"feuilles {nb} | avec grille {nb_g} | Σpoids=100 : {nb_ok}")
        except Exception as e:
            print(f"[{i}/{len(ids)}] {mid} : EXCEPTION {type(e).__name__}: {e}")
    print("\n=== Fin échantillon ===")


if __name__ == "__main__":
    main()
