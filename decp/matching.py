"""
decp/matching.py — scoring de correspondance marché Tendia ↔ attribution DECP.

Pondérations (cf prompt sprint) : CPV 0.30, acheteur 0.35, période 0.20, montant 0.15.
Le score montant est optionnel : s'il est absent côté Tendia, son poids est
redistribué proportionnellement sur les 3 autres.

ADAPTATION (documentée) : les marchés Tendia (BOAMP) n'ont PAS de SIRET acheteur
(`acheteur_id` toujours None). Le score acheteur tombe donc en repli sur une
similarité de NOM normalisé quand le SIRET manque d'un côté. C'est le principal
limiteur du matching — à lever en enrichissant les marchés Tendia avec le SIRET
de l'avis BOAMP (champ `donnees`).
"""
import re
import unicodedata
from typing import Optional

POIDS = {"cpv": 0.30, "acheteur": 0.35, "periode": 0.20, "montant": 0.15}
SEUIL_CANDIDAT = 0.70
SEUIL_FORT = 0.85

_MOTS_VIDES = {
    "DE", "DU", "DES", "LA", "LE", "LES", "ET", "D", "L", "A", "AU", "AUX",
    "SA", "SAS", "SARL", "EURL", "SCI", "EPIC", "GIP", "SEM", "COMMUNE",
    "MAIRIE", "VILLE", "DEPARTEMENT", "REGION", "COMMUNAUTE", "ETABLISSEMENT",
    "CENTRE", "SYNDICAT", "OFFICE", "AGENCE", "DIRECTION", "GENERALE",
    "PUBLIC", "PUBLICS", "SERVICE", "SERVICES",
}


def _normaliser_nom(nom) -> set:
    if not nom:
        return set()
    s = unicodedata.normalize("NFKD", str(nom))
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return {t for t in s.split() if len(t) > 1 and t not in _MOTS_VIDES}


def score_cpv(cpv_a, cpv_b) -> float:
    a = "".join(c for c in str(cpv_a or "") if c.isdigit())[:8]
    b = "".join(c for c in str(cpv_b or "") if c.isdigit())[:8]
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a[:5] == b[:5]:
        return 0.7
    if a[:3] == b[:3]:
        return 0.4
    if a[:2] == b[:2]:
        return 0.2
    return 0.0


def score_acheteur(siret_a, siret_b, nom_a=None, nom_b=None) -> float:
    """SIRET si dispo des deux côtés ; sinon repli sur similarité de nom."""
    a = "".join(c for c in str(siret_a or "") if c.isdigit())
    b = "".join(c for c in str(siret_b or "") if c.isdigit())
    if len(a) == 14 and len(b) == 14:
        if a == b:
            return 1.0
        if a[:9] == b[:9]:  # même SIREN
            return 0.6
        return 0.0
    # Repli nom (SIRET absent d'au moins un côté)
    ta, tb = _normaliser_nom(nom_a), _normaliser_nom(nom_b)
    if not ta or not tb:
        return 0.0
    jac = len(ta & tb) / len(ta | tb)
    if ta == tb or jac >= 0.85:
        return 0.9      # quasi-certain mais < SIRET (pas d'identifiant ferme)
    if jac >= 0.6:
        return 0.6
    if jac >= 0.4:
        return 0.3
    return 0.0


def _jours_entre(date_tendia, date_decp) -> Optional[int]:
    from datetime import date
    try:
        d1 = date.fromisoformat(str(date_tendia)[:10])
        d2 = date.fromisoformat(str(date_decp)[:10])
        return (d2 - d1).days
    except (TypeError, ValueError):
        return None


def score_periode(date_publication_tendia, date_notification_decp) -> float:
    """L'avis Tendia doit précéder l'attribution DECP de 1 à 18 mois (idéal)."""
    delta = _jours_entre(date_publication_tendia, date_notification_decp)
    if delta is None:
        return 0.0
    if delta < 0:
        return 0.0
    if delta <= 30:
        return 0.5
    if delta <= 540:
        return 1.0
    if delta <= 1095:  # décroissance linéaire 540j (1.0) → 1095j/36mois (0.0)
        return max(0.0, 1.0 - (delta - 540) / (1095 - 540))
    return 0.0


def score_montant(montant_estime_tendia, montant_decp) -> Optional[float]:
    """None si pas d'estimation Tendia (le poids sera redistribué)."""
    try:
        mt = float(montant_estime_tendia)
        md = float(montant_decp)
    except (TypeError, ValueError):
        return None
    if mt <= 0 or md <= 0:
        return None
    ratio = md / mt
    if 0.5 <= ratio <= 2.0:
        return 1.0
    if 0.3 <= ratio < 0.5 or 2.0 < ratio <= 3.5:
        return 0.5
    return 0.0


def scorer_match(marche_tendia: dict, attribution_decp: dict) -> dict:
    s_cpv = score_cpv(marche_tendia.get("cpv_principal"),
                      attribution_decp.get("cpv_principal"))
    s_ach = score_acheteur(marche_tendia.get("acheteur_siret"),
                           attribution_decp.get("acheteur_siret"),
                           marche_tendia.get("acheteur_nom"),
                           attribution_decp.get("acheteur_nom"))
    s_per = score_periode(marche_tendia.get("date_publication"),
                          attribution_decp.get("date_notification"))
    s_mon = score_montant(marche_tendia.get("montant_estime"),
                          attribution_decp.get("montant_eur"))

    if s_mon is None:
        # Redistribution proportionnelle du poids montant sur les 3 autres.
        base = POIDS["cpv"] + POIDS["acheteur"] + POIDS["periode"]
        total = (s_cpv * POIDS["cpv"] + s_ach * POIDS["acheteur"]
                 + s_per * POIDS["periode"]) / base
    else:
        total = (s_cpv * POIDS["cpv"] + s_ach * POIDS["acheteur"]
                 + s_per * POIDS["periode"] + s_mon * POIDS["montant"])

    return {
        "score_total": round(total, 4),
        "score_cpv": round(s_cpv, 4),
        "score_acheteur": round(s_ach, 4),
        "score_periode": round(s_per, 4),
        "score_montant": None if s_mon is None else round(s_mon, 4),
    }


def verifier_marche_tendia_existe(id_kv: str, db_path=None) -> bool:
    """Vérifie qu'un marché Tendia (collection KV 'marches') existe avant tout
    insert dans marche_attribution_link (évite les liens orphelins)."""
    from decp.db import connexion, DB_PATH_DEFAUT
    con = connexion(db_path or DB_PATH_DEFAUT)
    try:
        row = con.execute(
            "SELECT 1 FROM kv_storage WHERE collection='marches' AND id=? LIMIT 1",
            (id_kv,)).fetchone()
        return row is not None
    finally:
        con.close()
