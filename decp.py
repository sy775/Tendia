"""
connecteurs/decp.py
-------------------
Connecteur DECP — Données Essentielles de la Commande Publique.

Différent des connecteurs BOAMP : DECP contient les marchés DÉJÀ
NOTIFIÉS (gagnés), avec le SIRET du titulaire et le montant payé. C'est
notre source d'intelligence concurrentielle.

API : Opendatasoft v2.1, dataset `decp-2022-marches-valides`.
Filtre : `startswith(acheteur_id, "13000548")` (SIREN France Travail).

Différences vs BOAMP :
- Pas appelé par tendia_recup.py (qui ne gère que les marchés ouverts)
- Stocké dans la collection séparée `marches_notifies`
- Schéma enrichi : titulaire_siret, montant_eur, duree_mois, etc.
"""

import sys
from datetime import date, timedelta
from typing import Optional

from http_utils import get_json


SOURCE = "DECP"
DOMAINES = ["data.economie.gouv.fr"]

DECP_URL = (
    "https://data.economie.gouv.fr/api/explore/v2.1/"
    "catalog/datasets/decp-2022-marches-valides/records"
)

SIREN_FRANCE_TRAVAIL = "13000548"
TAILLE_PAGE = 100
MAX_RESULTATS_TOTAL = 5000
FENETRE_ANNEES_DEFAUT = 2

# Reprise des mots-clés du connecteur BOAMP pour cohérence de classification
from connecteurs.boamp import (
    MOTS_CLES_FORMATION, MOTS_CLES_INSERTION, MOTS_CLES_NEGATIFS,
)


# ---------------------------------------------------------------------------
# Helpers d'extraction
# ---------------------------------------------------------------------------

def _premier_present(d: dict, cles: list) -> str:
    for c in cles:
        v = d.get(c)
        if v not in (None, "", []):
            if isinstance(v, list):
                return " | ".join(str(x) for x in v if x)[:600]
            return str(v)[:600]
    return ""


def _acheteur_id(m: dict) -> str:
    return _premier_present(m, ["acheteur_id", "acheteur"])


def _acheteur_nom(m: dict) -> str:
    return _premier_present(m, ["acheteur_nom", "nom_acheteur"])


def _objet(m: dict) -> str:
    return _premier_present(m, ["objet", "objet_complet"])


def _cpv(m: dict) -> Optional[str]:
    v = _premier_present(m, ["codecpv", "code_cpv", "cpv"])
    return v[:10] if v else None


def _montant(m: dict) -> Optional[float]:
    v = m.get("montant") or m.get("amount") or m.get("valeur_marche")
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _duree_mois(m: dict) -> Optional[int]:
    v = m.get("dureemois") or m.get("duree_mois")
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _titulaires_sirets(m: dict) -> list:
    """Retourne la liste non-vide des SIRET titulaires (filtre 'CDL' placeholder)."""
    sirets = []
    for i in range(1, 4):
        sid = m.get(f"titulaire_id_{i}")
        if sid and str(sid).strip() not in ("CDL", "", "null", "None"):
            sid_str = str(sid).strip()
            # Filtrer aussi les 'CDL' encore présents avec d'autres caractères
            if sid_str.upper() != "CDL" and sid_str.isdigit():
                sirets.append(sid_str)
    return sirets


def _date_notification(m: dict) -> str:
    return _premier_present(m, ["datenotification", "date_notification"])[:10]


def _lieu_execution(m: dict) -> Optional[str]:
    return _premier_present(m, ["lieuexecution_nom", "lieuexecution_code",
                                  "lieu_execution"]) or None


def _procedure(m: dict) -> Optional[str]:
    return _premier_present(m, ["procedure", "type_procedure"]) or None


def _reference_acheteur(m: dict) -> Optional[str]:
    """
    Référence interne de l'acheteur (ex: '2605-DRFT-NA-FOP-110' pour FT).
    Clé de jointure naturelle avec BOAMP (qui la stocke sous `reference_ft`).

    Différent de `reference_externe` qui est l'ID technique du marché DECP
    (ex: '2948093'), généré par l'Opendatasoft.

    Liste de champs candidats large car le schéma DECP a évolué et le nom
    exact diffère selon les jeux de données (decp-2022, decp-2019…).
    """
    return _premier_present(m, [
        "id_marche", "idMarche",
        "reference_marche", "reference_acheteur", "referenceAcheteur",
        "numero_marche", "numeroMarche", "numero",
        "identifiant_marche", "identifiantMarche",
        "id_acheteur_marche",
    ]) or None


# ---------------------------------------------------------------------------
# Classification métier (mêmes règles que BOAMP, avec mots-clés négatifs)
# ---------------------------------------------------------------------------

def classifier(marche: dict) -> str:
    """Retourne 'formation' | 'insertion' | 'autre'."""
    objet = _objet(marche).lower()
    if not objet:
        return "autre"
    if any(mc in objet for mc in MOTS_CLES_NEGATIFS):
        return "autre"
    if any(mc in objet for mc in MOTS_CLES_FORMATION):
        return "formation"
    if any(mc in objet for mc in MOTS_CLES_INSERTION):
        return "insertion"
    # En complément : si le CPV commence par 80 (formation) ou 85312300
    # (action sociale), on classe quand même
    cpv = _cpv(marche) or ""
    if cpv.startswith("80"):
        return "formation"
    if cpv.startswith("85312"):
        return "insertion"
    return "autre"


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def _normaliser(marche: dict, categorie: str) -> Optional[dict]:
    """Transforme un marché DECP brut en dict au format unifié 'marché notifié'."""
    ref = (marche.get("id") or marche.get("uid") or marche.get("identifiant")
           or _premier_present(marche, ["id_marche", "id_lot"]))
    if not ref:
        return None
    ref = str(ref)

    sirets = _titulaires_sirets(marche)
    titulaire_principal = sirets[0] if sirets else None
    co_titulaires = sirets[1:] if len(sirets) > 1 else []

    return {
        "id": f"DECP-{ref}",
        "source": "DECP",
        "reference_externe": ref,
        "reference_acheteur": _reference_acheteur(marche),
        "objet": _objet(marche),
        "acheteur_id": _acheteur_id(marche),
        "acheteur_nom": _acheteur_nom(marche) or None,
        "titulaire_siret": titulaire_principal,
        "titulaire_nom": None,  # à enrichir via SIRENE plus tard
        "co_titulaires_sirets": co_titulaires,
        "montant_eur": _montant(marche),
        "duree_mois": _duree_mois(marche),
        "date_notification": _date_notification(marche) or None,
        "cpv_principal": _cpv(marche),
        "lieu_execution": _lieu_execution(marche),
        "categorie_metier": categorie,
        "procedure": _procedure(marche),
    }


# ---------------------------------------------------------------------------
# Récupération avec stratégie de filtre en cascade
# ---------------------------------------------------------------------------

def _appeler(where_clause: str, offset: int = 0) -> Optional[dict]:
    params = {
        "where": where_clause,
        "limit": TAILLE_PAGE,
        "offset": offset,
        "order_by": "datenotification DESC",
    }
    try:
        return get_json(DECP_URL, params=params, verbose=False)
    except Exception:
        params.pop("order_by", None)
        try:
            return get_json(DECP_URL, params=params, verbose=False)
        except Exception:
            return None


def _trouver_strategie(verbose: bool = True) -> str:
    """Trouve la première stratégie de filtre qui marche.

    Retourne la clause WHERE, ou lève RuntimeError si aucune ne fonctionne.
    """
    strategies = [
        f'startswith(acheteur_id, "{SIREN_FRANCE_TRAVAIL}")',
        f'acheteur_id="{SIREN_FRANCE_TRAVAIL}100010"',
    ]
    for where in strategies:
        if verbose:
            print(f"  [DECP] Test stratégie : {where}")
        reponse = _appeler(where, 0)
        if reponse is not None and reponse.get("total_count", 0) > 0:
            if verbose:
                print(f"  [DECP] ✓ {reponse.get('total_count')} marchés disponibles")
            return where
    raise RuntimeError(
        "Aucune stratégie de filtre DECP n'a fonctionné. "
        "Vérifie la disponibilité de l'API."
    )


def _recuperer_bruts(annees: int = FENETRE_ANNEES_DEFAUT,
                     verbose: bool = True) -> list:
    where = _trouver_strategie(verbose=verbose)
    date_seuil = (date.today() - timedelta(days=annees * 365)).isoformat()
    tous: list = []
    offset = 0
    while True:
        if verbose:
            print(f"  [DECP] Appel offset={offset} (cumul reçu : {len(tous)})")
        reponse = _appeler(where, offset)
        if reponse is None:
            print(f"  [DECP] ❌ Échec à offset={offset}", file=sys.stderr)
            break
        marches = reponse.get("results") or []
        if not marches:
            break
        tous.extend(marches)

        # Court-circuit date — DECP est trié par date desc
        date_derniere = _premier_present(marches[-1],
                                          ["datenotification", "date_notification"])
        if date_derniere and date_derniere[:10] < date_seuil:
            if verbose:
                print(f"  [DECP] Date {date_derniere[:10]} < {date_seuil}, arrêt.")
            break

        offset += len(marches)
        if len(tous) >= MAX_RESULTATS_TOTAL or offset + TAILLE_PAGE > 9900:
            if verbose:
                print(f"  [DECP] Plafond atteint.")
            break
    return tous


# ---------------------------------------------------------------------------
# Interface publique
# ---------------------------------------------------------------------------

def lister_marches_notifies(annees: int = FENETRE_ANNEES_DEFAUT,
                             limite: Optional[int] = None,
                             verbose: bool = True) -> list:
    """
    Liste les marchés notifiés France Travail dans la fenêtre.

    Tous les marchés sont retournés (formation, insertion ET autre),
    pas de filtrage à la source. Le tri se fait dans concurrence.py.
    """
    bruts = _recuperer_bruts(annees=annees, verbose=verbose)

    marches: list = []
    stats = {"formation": 0, "insertion": 0, "autre": 0}
    for m in bruts:
        cat = classifier(m)
        stats[cat] = stats.get(cat, 0) + 1
        norm = _normaliser(m, cat)
        if norm is not None:
            marches.append(norm)
        if limite and len(marches) >= limite:
            break

    if verbose:
        print(f"  [DECP] Classification :")
        for cat, n in sorted(stats.items(), key=lambda kv: -kv[1]):
            print(f"    {cat:<10} : {n}")

    return marches


if __name__ == "__main__":
    import json
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--annees", type=int, default=FENETRE_ANNEES_DEFAUT)
    parser.add_argument("--limite", type=int, default=None)
    args = parser.parse_args()
    marches = lister_marches_notifies(annees=args.annees, limite=args.limite,
                                        verbose=True)
    print(f"\n=== {len(marches)} marchés notifiés DECP ===")
    for m in marches[:3]:
        print(json.dumps(m, ensure_ascii=False, indent=2))
