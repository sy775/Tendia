"""
veille_concurrence.py
---------------------
Agrégateur de statistiques pour la page Veille concurrentielle.

Lit `marches_notifies` (DECP brut) + `marches_tendia_attribues` (base interne
validée) et calcule :
    - Stats globales (nb marchés, médianes globales)
    - Médianes par catégorie métier
    - Médianes par DR / région
    - Top titulaires
    - Distribution durée / montant

Filtre les outliers avant agrégation :
    - Montants < 1 000 € (placeholders DECP, erreurs d'extraction, marchés à 1€)
    - Montants > 50 M€ (consolidations nationales, pas comparables au niveau
      d'un organisme régional typique)

Le tableau marchés exclut aussi ces outliers, avec mention du nombre exclu.
"""

import statistics
from collections import Counter, defaultdict
from typing import Optional

import marches_attribues
import stockage


# Seuil minimum d'observations pour publier une médiane par segment
SEUIL_OBSERVATIONS_MIN = 3

# Bornes d'éligibilité d'un marché pour entrer dans les stats
MONTANT_MIN_VALIDE = 1_000        # exclut les 0€/1€/placeholders DECP
MONTANT_MAX_VALIDE = 50_000_000   # exclut les consolidations nationales (titres restau etc.)


def _est_montant_valide(m: float) -> bool:
    """True si le montant entre dans la plage exploitable pour les stats."""
    return m is not None and MONTANT_MIN_VALIDE <= m <= MONTANT_MAX_VALIDE


def _filtrer_marches_valides(marches_notifies: dict) -> dict:
    """Retourne un nouveau dict ne contenant que les marchés au montant valide."""
    return {
        id_m: m for id_m, m in marches_notifies.items()
        if _est_montant_valide(m.get("montant_eur"))
    }


def compter_outliers(marches_notifies: dict) -> dict:
    """Décompte des marchés exclus, pour transparence dans l'UI."""
    nb_total = len(marches_notifies)
    nb_trop_bas = sum(
        1 for m in marches_notifies.values()
        if m.get("montant_eur") is not None
        and 0 <= m.get("montant_eur") < MONTANT_MIN_VALIDE
    )
    nb_trop_haut = sum(
        1 for m in marches_notifies.values()
        if m.get("montant_eur") and m.get("montant_eur") > MONTANT_MAX_VALIDE
    )
    nb_sans_montant = sum(
        1 for m in marches_notifies.values()
        if m.get("montant_eur") is None
    )
    return {
        "total_base": nb_total,
        "exclus_trop_bas": nb_trop_bas,
        "exclus_trop_haut": nb_trop_haut,
        "exclus_sans_montant": nb_sans_montant,
        "valides": nb_total - nb_trop_bas - nb_trop_haut - nb_sans_montant,
        "borne_bas": MONTANT_MIN_VALIDE,
        "borne_haut": MONTANT_MAX_VALIDE,
    }


def _stats_basiques(montants: list) -> dict:
    """Q1, médiane, Q3 sur une liste de montants. Retourne {} si <3 obs."""
    montants = sorted([m for m in montants if m and m > 0])
    n = len(montants)
    if n < SEUIL_OBSERVATIONS_MIN:
        return {"n": n}
    return {
        "n": n,
        "q1": int(statistics.quantiles(montants, n=4)[0]) if n >= 4 else int(montants[0]),
        "mediane": int(statistics.median(montants)),
        "q3": int(statistics.quantiles(montants, n=4)[2]) if n >= 4 else int(montants[-1]),
        "min": int(montants[0]),
        "max": int(montants[-1]),
    }


def agreger_stats_globales(marches_notifies: dict) -> dict:
    """Stats globales sur l'ensemble de la base DECP."""
    montants = [m.get("montant_eur") for m in marches_notifies.values()]
    return _stats_basiques(montants) | {"total": len(marches_notifies)}


def agreger_par_categorie(marches_notifies: dict) -> list:
    """Stats par catégorie métier, triées par nb décroissant."""
    par_cat = defaultdict(list)
    for m in marches_notifies.values():
        cat = m.get("categorie_metier") or "autre"
        montant = m.get("montant_eur")
        if montant and montant > 0:
            par_cat[cat].append(montant)

    rows = []
    for cat, montants in par_cat.items():
        stats = _stats_basiques(montants)
        if stats.get("n", 0) >= SEUIL_OBSERVATIONS_MIN:
            stats["categorie"] = cat
            rows.append(stats)
    rows.sort(key=lambda r: -r["n"])
    return rows


def agreger_par_duree(marches_notifies: dict) -> list:
    """Stats par tranche de durée."""
    tranches = [
        ("< 12 mois", lambda d: d < 12),
        ("12-23 mois", lambda d: 12 <= d < 24),
        ("24-35 mois", lambda d: 24 <= d < 36),
        ("36-47 mois", lambda d: 36 <= d < 48),
        ("48+ mois", lambda d: d >= 48),
    ]
    rows = []
    for label, cond in tranches:
        montants = [
            m.get("montant_eur") for m in marches_notifies.values()
            if m.get("duree_mois") and cond(m["duree_mois"]) and m.get("montant_eur")
        ]
        stats = _stats_basiques(montants)
        if stats.get("n", 0) >= SEUIL_OBSERVATIONS_MIN:
            stats["tranche"] = label
            rows.append(stats)
    return rows


def top_titulaires(marches_notifies: dict, n: int = 10) -> list:
    """Top N titulaires par nombre de marchés gagnés, avec montant total."""
    par_titulaire = defaultdict(lambda: {"nb": 0, "total_eur": 0, "categories": Counter()})
    for m in marches_notifies.values():
        t = (m.get("titulaire_nom") or "").strip()
        if not t:
            continue
        par_titulaire[t]["nb"] += 1
        par_titulaire[t]["total_eur"] += m.get("montant_eur") or 0
        cat = m.get("categorie_metier") or "autre"
        par_titulaire[t]["categories"][cat] += 1

    rows = []
    for nom, data in par_titulaire.items():
        cat_dominante = data["categories"].most_common(1)[0][0] if data["categories"] else None
        rows.append({
            "titulaire": nom,
            "nb_marches": data["nb"],
            "total_eur": int(data["total_eur"]),
            "categorie_dominante": cat_dominante,
        })
    rows.sort(key=lambda r: -r["nb_marches"])
    return rows[:n]


def lister_marches_avec_meta(marches_notifies: dict, limit: Optional[int] = None) -> list:
    """Liste des marchés DECP formatée pour le tableau de la page veille.

    Args:
        marches_notifies: dict de marchés DECP
        limit: nombre maximum d'entrées à retourner (None = tout)

    Returns:
        liste triée par date_notification décroissante, prête à rendre dans
        le template (id, titre, acheteur, titulaire, catégorie, dr,
        montant_eur, duree_mois, annee_notification).
    """
    rows = []
    for id_m, m in marches_notifies.items():
        date_n = m.get("date_notification") or ""
        annee = date_n[:4] if len(date_n) >= 4 else ""
        rows.append({
            "id": id_m,
            "objet": (m.get("objet") or m.get("titre") or "")[:120],
            "acheteur": m.get("acheteur_nom") or "",
            "titulaire": m.get("titulaire_nom") or "",
            "categorie": m.get("categorie_metier") or "autre",
            "dr": m.get("acheteur_region_code") or m.get("acheteur_departement_nom") or "",
            "montant_eur": m.get("montant_eur") or 0,
            "duree_mois": m.get("duree_mois") or 0,
            "annee": annee,
            "date_notification": date_n,
            "offres_recues": m.get("offres_recues") or 0,
        })
    rows.sort(key=lambda r: r["date_notification"], reverse=True)
    if limit:
        rows = rows[:limit]
    return rows


def lister_marches_tendia() -> list:
    """Liste des marchés Tendia validés (base interne) avec leur scoring."""
    entrees = marches_attribues.lire_tous()
    rows = []
    for id_e, e in entrees.items():
        attr = e.get("attribution") or {}
        marche = e.get("marche") or {}
        ratios = e.get("ratios") or {}
        meta = e.get("_meta") or {}
        rows.append({
            "id": id_e,
            "id_decp": e.get("id_decp"),
            "id_marche_actif": e.get("id_marche_actif"),
            "objet": (marche.get("objet") or marche.get("titre") or "")[:120],
            "acheteur": marche.get("acheteur_nom") or "",
            "titulaire": attr.get("titulaire_nom") or "",
            "montant_eur": attr.get("montant_eur") or 0,
            "duree_mois": attr.get("duree_mois") or 0,
            "categorie": marche.get("categorie_metier") or "autre",
            "ratio_par_beneficiaire": ratios.get("prix_par_beneficiaire_eur"),
            "ratio_mensuel": ratios.get("prix_mensuel_eur"),
            "matching_confiance": meta.get("matching_confiance"),
        })
    rows.sort(key=lambda r: -(r["montant_eur"] or 0))
    return rows


def agreger_tout(marches_notifies: dict) -> dict:
    """Agrège toutes les stats utiles à la page veille en un seul appel.

    Applique le filtre outliers avant agrégation. Le bilan des exclusions
    est inclus dans le retour pour transparence côté UI.
    """
    outliers = compter_outliers(marches_notifies)
    marches_filtres = _filtrer_marches_valides(marches_notifies)
    return {
        "outliers": outliers,
        "globales": agreger_stats_globales(marches_filtres),
        "par_categorie": agreger_par_categorie(marches_filtres),
        "par_duree": agreger_par_duree(marches_filtres),
        "top_titulaires": top_titulaires(marches_filtres, n=10),
        "marches_tendia": lister_marches_tendia(),
        "marches_decp": lister_marches_avec_meta(marches_filtres, limit=500),
    }
