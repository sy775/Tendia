"""
cycle_marche.py
---------------
Cycle de vie d'un appel d'offre dans Tendia.

Statuts possibles (graphe simplifié) :
    - a_evaluer  : nouveau marché détecté, pas encore décidé
    - candidate  : offre déposée, en attente du résultat
    - gagne      : marché remporté (alimente la base ✦ Tendia)
    - perdu      : marché attribué à un concurrent
    - abandonne  : NO-GO ou hors délai

Transitions valides :
    a_evaluer -> candidate | abandonne
    candidate -> gagne | perdu | a_evaluer (reset)
    gagne, perdu, abandonne -> reset autorisé en cas d'erreur

Le statut + l'historique des transitions sont stockés dans
`marches[id]['cycle']` directement.
"""

from datetime import datetime, timezone
from typing import Optional

import stockage


# -----------------------------------------------------------------------------
# Statuts et transitions
# -----------------------------------------------------------------------------

STATUT_A_EVALUER = "a_evaluer"
STATUT_CANDIDATE = "candidate"
STATUT_GAGNE = "gagne"
STATUT_PERDU = "perdu"
STATUT_ABANDONNE = "abandonne"

STATUT_DEFAUT = STATUT_A_EVALUER

# Mapping legacy : si un ancien marché a "a_candidater", on le lit comme "a_evaluer"
# (ou candidate selon les transitions précédentes). On le considère comme "candidate"
# par défaut puisqu'une décision GO avait été prise.
STATUTS_LEGACY = {
    "a_candidater": STATUT_CANDIDATE,
}

# Métadonnées d'affichage
STATUT_META = {
    STATUT_A_EVALUER: {"label": "À évaluer", "couleur": "stone", "icone": "○"},
    STATUT_CANDIDATE: {"label": "Candidaté", "couleur": "blue",  "icone": "✎"},
    STATUT_GAGNE:     {"label": "Gagné",     "couleur": "green", "icone": "✓"},
    STATUT_PERDU:     {"label": "Perdu",     "couleur": "rose",  "icone": "✕"},
    STATUT_ABANDONNE: {"label": "Abandonné", "couleur": "stone", "icone": "—"},
}

# Statuts considérés "actifs" (= candidature en cours, visibles sur le pilotage)
STATUTS_ACTIFS = (STATUT_A_EVALUER, STATUT_CANDIDATE)

# Statuts terminaux (alimentent les stats post-mortem)
STATUTS_TERMINAUX = (STATUT_GAGNE, STATUT_PERDU, STATUT_ABANDONNE)

# Graphe des transitions valides
_TRANSITIONS_VALIDES = {
    STATUT_A_EVALUER: {STATUT_CANDIDATE, STATUT_ABANDONNE},
    STATUT_CANDIDATE: {STATUT_GAGNE, STATUT_PERDU, STATUT_A_EVALUER},
    STATUT_GAGNE:     {STATUT_CANDIDATE},
    STATUT_PERDU:     {STATUT_CANDIDATE},
    STATUT_ABANDONNE: {STATUT_A_EVALUER},
}


def _ts_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normaliser_statut(s: str) -> str:
    """Convertit les statuts legacy vers les statuts actuels."""
    if s in STATUTS_LEGACY:
        return STATUTS_LEGACY[s]
    if s in STATUT_META:
        return s
    return STATUT_DEFAUT


# -----------------------------------------------------------------------------
# Lecture
# -----------------------------------------------------------------------------

def lire_cycle(marche: dict) -> dict:
    """Retourne le bloc cycle d'un marché, en initialisant si absent."""
    cycle = marche.get("cycle")
    if not cycle or not isinstance(cycle, dict):
        return {"statut": STATUT_DEFAUT, "transitions": []}
    cycle["statut"] = _normaliser_statut(cycle.get("statut", STATUT_DEFAUT))
    if "transitions" not in cycle:
        cycle["transitions"] = []
    return cycle


def statut(marche: dict) -> str:
    return lire_cycle(marche).get("statut", STATUT_DEFAUT)


def meta(statut_code: str) -> dict:
    return STATUT_META.get(_normaliser_statut(statut_code), STATUT_META[STATUT_DEFAUT])


def transitions_possibles(statut_actuel: str) -> list:
    """Liste des transitions valides depuis un statut donné."""
    statut_actuel = _normaliser_statut(statut_actuel)
    cibles = _TRANSITIONS_VALIDES.get(statut_actuel, set())
    return [{"statut": s, **meta(s)} for s in cibles]


# -----------------------------------------------------------------------------
# Écriture
# -----------------------------------------------------------------------------

def changer_statut(id_marche: str, nouveau_statut: str, note: str = "") -> dict:
    """Change le statut d'un marché et historise la transition."""
    nouveau_statut = _normaliser_statut(nouveau_statut)
    if nouveau_statut not in STATUT_META:
        return {"ok": False, "erreur": f"Statut inconnu : {nouveau_statut}",
                "ancien": None, "nouveau": None}

    marches = stockage.charger("marches")
    marche = marches.get(id_marche)
    if not marche:
        return {"ok": False, "erreur": f"Marché {id_marche} introuvable",
                "ancien": None, "nouveau": None}

    cycle = lire_cycle(marche)
    ancien = cycle["statut"]

    cibles_valides = _TRANSITIONS_VALIDES.get(ancien, set())
    if nouveau_statut != ancien and nouveau_statut not in cibles_valides:
        return {"ok": False,
                "erreur": f"Transition {ancien} → {nouveau_statut} non autorisée",
                "ancien": ancien, "nouveau": None}

    if nouveau_statut == ancien:
        return {"ok": True, "erreur": None, "ancien": ancien,
                "nouveau": nouveau_statut, "no_op": True}

    cycle["statut"] = nouveau_statut
    cycle["transitions"].append({
        "de": ancien, "vers": nouveau_statut,
        "ts": _ts_iso(), "note": (note or "")[:300],
    })
    marche["cycle"] = cycle
    marches[id_marche] = marche
    stockage.sauver("marches", marches)

    return {"ok": True, "erreur": None, "ancien": ancien, "nouveau": nouveau_statut}


# -----------------------------------------------------------------------------
# Stats agrégées
# -----------------------------------------------------------------------------

def kpis_pipeline(marches: dict = None, ids_actifs: list = None) -> dict:
    """KPIs commerciaux.

    Args:
        marches: dict de tous les marchés (par défaut, chargé depuis le stockage)
        ids_actifs: liste des IDs de marchés considérés actifs (date_limite future).
            Si fourni, on ne compte que ceux-ci pour les statuts NON-TERMINAUX.
            Les statuts terminaux (gagne, perdu, abandonne) sont comptés sur tous
            les marchés (historique commercial).

    Returns:
        Dict avec compteurs + taux de conversion + nb_actifs + nb_clos.
    """
    if marches is None:
        marches = stockage.charger("marches")
    ids_actifs_set = set(ids_actifs) if ids_actifs is not None else None

    # Compteurs par statut, ventilés actifs/terminaux
    nb_a_evaluer_actifs = 0
    nb_candidate_actifs = 0
    nb_gagne = 0
    nb_perdu = 0
    nb_abandonne = 0

    for mid, m in marches.items():
        s = statut(m)
        is_actif = (ids_actifs_set is None) or (mid in ids_actifs_set)
        if s == STATUT_A_EVALUER and is_actif:
            nb_a_evaluer_actifs += 1
        elif s == STATUT_CANDIDATE and is_actif:
            nb_candidate_actifs += 1
        elif s == STATUT_GAGNE:
            nb_gagne += 1
        elif s == STATUT_PERDU:
            nb_perdu += 1
        elif s == STATUT_ABANDONNE:
            nb_abandonne += 1

    denom = nb_gagne + nb_perdu
    taux = (nb_gagne / denom) if denom > 0 else None
    return {
        "nb_a_evaluer":    nb_a_evaluer_actifs,
        "nb_candidate":    nb_candidate_actifs,
        "nb_gagne":        nb_gagne,
        "nb_perdu":        nb_perdu,
        "nb_abandonne":    nb_abandonne,
        "nb_actifs":       nb_a_evaluer_actifs + nb_candidate_actifs,
        "nb_clos":         nb_gagne + nb_perdu + nb_abandonne,
        "taux_conversion":     taux,
        "taux_conversion_pct": int(round(taux * 100)) if taux is not None else None,
    }
