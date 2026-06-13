"""
diagnostic_dce_pertinents.py
----------------------------
Pour les marchés pertinents (matchent au moins un preset), on regarde :
- Combien ont une url_dce exploitable (directe / via_keyword)
- Combien ont url_dce mais en mode "racine" (page d'accueil, peu utile)
- Combien n'ont rien
- Distribution par plateforme

Sortie : on saura si filtrer "sans DCE" est tenable, et sur quelles
plateformes concentrer l'effort.
"""

import io
import sys
from collections import Counter
from urllib.parse import urlparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import analyse


def _domaine(url: str) -> str:
    if not url:
        return ""
    try:
        d = urlparse(url).netloc.lower().removeprefix("www.")
        return d
    except Exception:
        return ""


def main():
    marches = stockage.charger("marches")
    pertinents_ids = analyse._ids_marches_pertinents()

    print("=" * 78)
    print("  DIAGNOSTIC URL DCE — marchés PERTINENTS uniquement")
    print("=" * 78)
    print(f"  Marchés en base       : {len(marches)}")
    print(f"  Marchés pertinents    : {len(pertinents_ids)}")
    print()

    par_qualite = Counter()
    par_domaine = Counter()
    sans_url_titres = []  # liste des marchés sans url, pour inspection

    for mid in sorted(pertinents_ids):
        m = marches.get(mid)
        if not m:
            continue

        qualite = m.get("dce_qualite", "non_recherchee")  # rempli par tendia_dce.py
        url = m.get("url_dce")

        par_qualite[qualite] += 1

        if url:
            par_domaine[_domaine(url)] += 1
        else:
            sans_url_titres.append((mid, (m.get("titre") or "")[:80],
                                     m.get("acheteur_nom") or ""))

    print(f"  Distribution par qualité :")
    for q, n in par_qualite.most_common():
        pct = 100 * n / max(1, len(pertinents_ids))
        print(f"    {q:20} : {n:3} ({pct:.0f}%)")
    print()

    # Verdict métier
    exploitables = par_qualite.get("directe", 0) + par_qualite.get("via_keyword", 0)
    pct_expl = 100 * exploitables / max(1, len(pertinents_ids))
    print(f"  → URL DCE EXPLOITABLE (directe / via_keyword) : {exploitables} "
          f"({pct_expl:.0f}%)")
    print(f"  → SANS URL EXPLOITABLE                        : "
          f"{len(pertinents_ids) - exploitables} "
          f"({100 - pct_expl:.0f}%)")
    print()

    if par_domaine:
        print(f"  Plateformes ciblées (top) :")
        for d, n in par_domaine.most_common(10):
            print(f"    {d:45} : {n}")
        print()

    # Échantillon des marchés sans URL — peut-être qu'on rate quelque chose
    if sans_url_titres:
        print(f"  Échantillon de marchés pertinents SANS url_dce (max 10) :")
        for mid, titre, acheteur in sans_url_titres[:10]:
            print(f"    [{mid}] {acheteur[:40]}")
            print(f"        {titre}")


if __name__ == "__main__":
    main()
