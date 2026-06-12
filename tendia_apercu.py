"""
tendia_apercu.py
----------------
Lit data/marches.json et affiche un aperçu lisible : volumétrie par
source / catégorie / mois, top acheteurs, état d'ouverture des marchés
(par date limite de dépôt), et liste les 15 marchés les plus récents
pour vérification manuelle.

Aucune écriture, aucun appel réseau. Outil de lecture pur.

Usage :
    python tendia_apercu.py
    python tendia_apercu.py --categorie insertion    # filtre une catégorie
    python tendia_apercu.py --liste-tout             # liste tous les marchés
    python tendia_apercu.py --doute                  # uniquement les "limites"
"""

import argparse
from collections import Counter, defaultdict
from datetime import date

import stockage


COLLECTION = "marches"

# Marqueurs heuristiques de classification "douteuse" — pour audit manuel.
# Mots qui apparaissent souvent dans des marchés mal classés (ex: "atelier
# graphique" classé "insertion" à cause de "atelier").
MOTS_DOUTEUX = [
    "graphique", "communication", "impression", "événement", "evenement",
    "studio", "vidéo", "video", "informatique", "logiciel", "site internet",
    "logistique", "nettoyage", "déménagement", "demenagement", "transport",
    "fourniture", "abonnement", "publication", "édition", "edition",
    "audit", "conseil", "stratégie", "strategie",
]


def _est_ouvert(marche: dict) -> str:
    """Retourne 'ouvert' / 'clos' / 'sans_date' selon la date limite."""
    dl = marche.get("date_limite_depot")
    if not dl or len(dl) < 10:
        return "sans_date"
    try:
        return "ouvert" if dl[:10] >= date.today().isoformat() else "clos"
    except Exception:
        return "sans_date"


def _est_douteux(marche: dict) -> list:
    """Liste les mots-clés douteux trouvés dans l'objet."""
    obj = (marche.get("objet") or marche.get("titre") or "").lower()
    return [m for m in MOTS_DOUTEUX if m in obj]


def _formater_marche(m: dict, num: int = None) -> str:
    """Une ligne synthétique pour un marché."""
    prefix = f"  [{num}] " if num is not None else "  "
    titre = (m.get("titre") or m.get("objet") or "(sans titre)")[:90]
    cat = m.get("categorie_metier", "?")
    src = m.get("source", "?")
    ach = (m.get("acheteur_nom") or "?")[:40]
    date_pub = m.get("date_publication", "?")
    date_lim = m.get("date_limite_depot") or "(pas de date limite)"
    etat = _est_ouvert(m)
    return (
        f"{prefix}[{src:5}|{cat:9}|{etat:9}] {titre}\n"
        f"      Acheteur: {ach} | Publié: {date_pub} | Limite: {date_lim}"
    )


def _resume_global(marches: dict) -> None:
    print()
    print("=" * 78)
    print(f"  APERÇU — {len(marches)} marchés en base (data/marches.json)")
    print("=" * 78)

    par_source = Counter(m.get("source", "?") for m in marches.values())
    par_categorie = Counter(m.get("categorie_metier", "?") for m in marches.values())
    par_etat = Counter(_est_ouvert(m) for m in marches.values())
    par_mois = Counter((m.get("date_publication") or "")[:7] for m in marches.values())

    print(f"\n  Par source :")
    for k, v in par_source.most_common():
        print(f"    {k:<10} : {v}")

    print(f"\n  Par catégorie métier :")
    for k, v in par_categorie.most_common():
        print(f"    {k:<12} : {v}")

    print(f"\n  Par état (selon date limite de dépôt) :")
    for k, v in par_etat.most_common():
        print(f"    {k:<10} : {v}")

    print(f"\n  Distribution par mois de publication :")
    for mois in sorted(par_mois.keys()):
        if mois:
            print(f"    {mois} : {par_mois[mois]}")


def _top_acheteurs(marches: dict, n: int = 15) -> None:
    par_acheteur = Counter(
        (m.get("acheteur_nom") or "?").lower() for m in marches.values()
    )
    print(f"\n  Top {n} acheteurs :")
    for k, v in par_acheteur.most_common(n):
        print(f"    [{v:3}] {k}")


def _marches_recents(marches: dict, n: int = 15,
                      filtre_categorie: str = None) -> None:
    lst = list(marches.values())
    if filtre_categorie:
        lst = [m for m in lst if m.get("categorie_metier") == filtre_categorie]
    lst.sort(key=lambda m: m.get("date_publication", ""), reverse=True)
    print()
    print("─" * 78)
    print(f"  {n} marchés les plus récents"
          + (f" (catégorie='{filtre_categorie}')" if filtre_categorie else ""))
    print("─" * 78)
    for i, m in enumerate(lst[:n], 1):
        print(_formater_marche(m, i))


def _marches_douteux(marches: dict) -> None:
    """Liste les marchés contenant des mots-clés suspects pour audit."""
    douteux = []
    for m in marches.values():
        mots = _est_douteux(m)
        if mots:
            douteux.append((m, mots))

    print()
    print("─" * 78)
    print(f"  {len(douteux)} marchés à AUDITER (mots-clés suspects)")
    print("─" * 78)
    print("  Ces marchés contiennent des mots qui suggèrent qu'ils ne sont")
    print("  peut-être PAS pertinents (graphique, logistique, IT, etc.).")
    print("  À vérifier un par un — si beaucoup sont effectivement des faux")
    print("  positifs, il faut affiner les mots-clés de classification dans")
    print("  connecteurs/boamp.py.")
    print()
    for i, (m, mots) in enumerate(douteux, 1):
        print(_formater_marche(m, i))
        print(f"      ⚠ Mots suspects : {', '.join(mots)}")


def _liste_tout(marches: dict) -> None:
    lst = sorted(marches.values(),
                   key=lambda m: m.get("date_publication", ""), reverse=True)
    print()
    print("─" * 78)
    print(f"  Tous les marchés ({len(lst)})")
    print("─" * 78)
    for i, m in enumerate(lst, 1):
        print(_formater_marche(m, i))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Aperçu de data/marches.json")
    parser.add_argument("--categorie", choices=["formation", "insertion", "autre"],
                        default=None)
    parser.add_argument("--liste-tout", action="store_true")
    parser.add_argument("--doute", action="store_true",
                        help="Liste les marchés à mots-clés suspects pour audit.")
    parser.add_argument("--top-acheteurs", type=int, default=15)
    parser.add_argument("--recents", type=int, default=15)
    args = parser.parse_args()

    marches = stockage.charger(COLLECTION)
    if not marches:
        print("Aucun marché en base. Lance d'abord : python tendia_recup.py")
        return

    _resume_global(marches)
    _top_acheteurs(marches, n=args.top_acheteurs)

    if args.liste_tout:
        _liste_tout(marches)
    elif args.doute:
        _marches_douteux(marches)
    else:
        _marches_recents(marches, n=args.recents,
                         filtre_categorie=args.categorie)


if __name__ == "__main__":
    main()
