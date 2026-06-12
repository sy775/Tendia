"""
connecteurs/decp_consolidee.py
------------------------------
Connecteur DECP via l'API tabulaire de data.gouv.fr.

Source : DECP consolidée maintenue par Colin Maudry (Colmo),
mise à jour quotidienne. Ressource ID Parquet :
22847056-61df-452d-837d-8b8ceadbfc52.

Remplace l'ancien connecteur DECP Opendatasoft (devenu
connecteurs/decp_opendatasoft.py.bak).

Pourquoi ce switch :
- 66 colonnes vs ~30 dans Opendatasoft
- titulaire_nom natif (plus besoin de l'enrichissement SIRENE pour les
  nouveaux marchés DECP)
- acheteur_region_code/nom → DR du marché directement
- titulaire_categorie (GE / PME / TPE) → analyse concurrentielle plus fine
- idAccordCadre → regroupement accord-cadre ↔ marchés subséquents
- offresRecues → nombre de candidats par marché
- considerationsSociales/Environnementales → critères RSE
- modification_id + donneesActuelles → gestion propre des avenants
- anomalies → filtrage des marchés problématiques

Limites de l'API :
- __startswith non supporté → on utilise __contains + filtre local strict
- Tarification : 100 req/sec, suffisant pour notre usage
"""

import sys
from collections import Counter
from datetime import date, timedelta
from typing import Optional

from http_utils import get_json

# Reprise des règles de classification depuis BOAMP pour cohérence
from connecteurs.boamp import (
    MOTS_CLES_FORMATION, MOTS_CLES_INSERTION, MOTS_CLES_NEGATIFS,
)


SOURCE = "DECP"
DOMAINES = ["data.gouv.fr", "tabular-api.data.gouv.fr"]

RESSOURCE_ID = "22847056-61df-452d-837d-8b8ceadbfc52"
URL_BASE = f"https://tabular-api.data.gouv.fr/api/resources/{RESSOURCE_ID}/data/"

SIREN_FRANCE_TRAVAIL = "13000548"
TAILLE_PAGE = 100
MAX_RESULTATS_TOTAL = 5000
FENETRE_ANNEES_DEFAUT = 2


# ---------------------------------------------------------------------------
# Helpers de conversion robuste
# ---------------------------------------------------------------------------

def _str_or_none(v) -> Optional[str]:
    if v is None or v == "":
        return None
    s = str(v).strip()
    return s or None


def _int_or_none(v) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _float_or_none(v) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _date_iso(v) -> Optional[str]:
    s = _str_or_none(v)
    return s[:10] if s else None


def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("true", "1", "oui", "yes")
    return bool(v)


# ---------------------------------------------------------------------------
# Classification métier (mêmes règles que BOAMP)
# ---------------------------------------------------------------------------

def classifier(brut: dict) -> str:
    """Retourne 'formation' | 'insertion' | 'autre'."""
    objet = (brut.get("objet") or "").lower()
    if not objet:
        return "autre"
    if any(mc in objet for mc in MOTS_CLES_NEGATIFS):
        return "autre"
    if any(mc in objet for mc in MOTS_CLES_FORMATION):
        return "formation"
    if any(mc in objet for mc in MOTS_CLES_INSERTION):
        return "insertion"
    cpv = (brut.get("codeCPV") or "")
    if cpv.startswith("80"):
        return "formation"
    if cpv.startswith("85312"):
        return "insertion"
    return "autre"


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def _normaliser(brut: dict, categorie: str) -> Optional[dict]:
    """
    Convertit un enregistrement DECP consolidée brut en format unifié Tendia.

    Conserve les clés historiques (rétrocompatibilité avec concurrence.py et
    le reste du code) et ajoute les nouveaux champs enrichis disponibles.

    Retourne None si l'enregistrement n'a pas d'id (cas pathologique).
    """
    id_brut = _str_or_none(brut.get("id"))
    if not id_brut:
        return None

    return {
        # === Identifiants (compatibles avec ancien format) ===
        "id": f"DECP-{id_brut}",
        "source": "DECP",
        "reference_externe": id_brut,
        # FT ne publie pas sa ref interne au format 2605-DRFT-...
        # On laisse None ; le module jointure.py l'ignore proprement.
        "reference_acheteur": None,
        "uid_decp": _str_or_none(brut.get("uid")),

        # === Acheteur (enrichi : géolocalisation native) ===
        "acheteur_id": _str_or_none(brut.get("acheteur_id")),
        "acheteur_nom": _str_or_none(brut.get("acheteur_nom")),
        "acheteur_region_code": _str_or_none(brut.get("acheteur_region_code")),
        "acheteur_region_nom": _str_or_none(brut.get("acheteur_region_nom")),
        "acheteur_departement_code": _str_or_none(
            brut.get("acheteur_departement_code")),
        "acheteur_departement_nom": _str_or_none(
            brut.get("acheteur_departement_nom")),
        "acheteur_commune_nom": _str_or_none(brut.get("acheteur_commune_nom")),

        # === Description marché ===
        "objet": _str_or_none(brut.get("objet")),
        "cpv_principal": _str_or_none(brut.get("codeCPV")),
        "procedure": _str_or_none(brut.get("procedure")),
        "nature": _str_or_none(brut.get("nature")),
        "modalites_execution": _str_or_none(brut.get("modalitesExecution")),
        "lieu_execution": _str_or_none(brut.get("lieuExecution_code")),
        "lieu_execution_type": _str_or_none(brut.get("lieuExecution_typeCode")),
        "type_marche": _str_or_none(brut.get("type")),

        # === Financier ===
        "montant_eur": _float_or_none(brut.get("montant")),
        "duree_mois": _int_or_none(brut.get("dureeMois")),
        "duree_restante_mois": _float_or_none(brut.get("dureeRestanteMois")),
        "forme_prix": _str_or_none(brut.get("formePrix")),
        "types_prix": _str_or_none(brut.get("typesPrix")),
        "ccag": _str_or_none(brut.get("ccag")),

        # === Dates ===
        "date_notification": _date_iso(brut.get("dateNotification")),
        "date_publication_donnees": _date_iso(
            brut.get("datePublicationDonnees")),

        # === Titulaire (enrichi : nom natif + catégorie + géo) ===
        "titulaire_siret": _str_or_none(brut.get("titulaire_id")),
        "titulaire_nom": _str_or_none(brut.get("titulaire_nom")),
        "titulaire_categorie": _str_or_none(brut.get("titulaire_categorie")),
        "titulaire_commune": _str_or_none(brut.get("titulaire_commune_nom")),
        "titulaire_departement": _str_or_none(
            brut.get("titulaire_departement_nom")),
        "titulaire_region": _str_or_none(brut.get("titulaire_region_nom")),
        "titulaire_type_identifiant": _str_or_none(
            brut.get("titulaire_typeIdentifiant")),
        # Pour les co-titulaires : la consolidée les met sur des lignes
        # séparées avec le même `id`. La dédup côté tendia_decp les gère.
        "co_titulaires_sirets": [],

        # === Concurrence ===
        "offres_recues": _int_or_none(brut.get("offresRecues")),
        "type_groupement_operateurs": _str_or_none(
            brut.get("typeGroupementOperateurs")),

        # === Accord-cadre parent ===
        "id_accord_cadre": _str_or_none(brut.get("idAccordCadre")),

        # === RSE ===
        "considerations_sociales": _str_or_none(
            brut.get("considerationsSociales")),
        "considerations_environnementales": _str_or_none(
            brut.get("considerationsEnvironnementales")),
        "marche_innovant": _bool(brut.get("marcheInnovant")),

        # === Versioning DECP (avenants) ===
        "modification_id": _int_or_none(brut.get("modification_id")) or 0,
        "donnees_actuelles": _bool(brut.get("donneesActuelles")),

        # === Qualité / source ===
        "anomalies": _str_or_none(brut.get("anomalies")),
        "score_qualite": _float_or_none(brut.get("score")),
        "source_dataset": _str_or_none(brut.get("sourceDataset")),
        "source_systeme": _str_or_none(brut.get("source")),

        # === Classification (calculée par Tendia) ===
        "categorie_metier": categorie,
    }


# ---------------------------------------------------------------------------
# Récupération paginée
# ---------------------------------------------------------------------------

def _appeler_page(params: dict, verbose: bool = False) -> Optional[dict]:
    """Un appel à l'API. Retourne le dict de réponse, None sur erreur."""
    try:
        return get_json(URL_BASE, params=params, verbose=verbose)
    except Exception as e:
        if verbose:
            print(f"  ⚠ Erreur API : {e}", file=sys.stderr)
        return None


def _dedupliquer_co_titulaires(marches: list) -> list:
    """
    Sur la DECP consolidée, un marché multi-titulaires apparaît en plusieurs
    lignes (une par titulaire). On agrège par `id` brut : on garde la
    première ligne comme principale et on liste les autres SIRETs dans
    `co_titulaires_sirets`.
    """
    par_id = {}
    for m in marches:
        ref = m.get("reference_externe")
        if not ref:
            continue
        if ref not in par_id:
            par_id[ref] = m
        else:
            principal = par_id[ref]
            # Ajoute le SIRET du co-titulaire
            siret_co = m.get("titulaire_siret")
            if siret_co and siret_co != principal.get("titulaire_siret"):
                cotit = principal.get("co_titulaires_sirets") or []
                if siret_co not in cotit:
                    cotit.append(siret_co)
                principal["co_titulaires_sirets"] = cotit
    return list(par_id.values())


# ---------------------------------------------------------------------------
# API publique : alias compatible avec l'ancien connecteur
# ---------------------------------------------------------------------------

def lister_marches_notifies(annees: int = FENETRE_ANNEES_DEFAUT,
                              limite: Optional[int] = None,
                              verbose: bool = True) -> list:
    """
    Récupère les marchés DECP France Travail sur les N dernières années
    depuis la DECP consolidée (tabular-api data.gouv.fr).

    Signature compatible avec l'ancien connecteur Opendatasoft.

    Stratégie :
    1. Filtre côté API : acheteur_id contient SIREN FT + dernière version
       du marché + dateNotification > seuil
    2. Pagination jusqu'à plafond ou épuisement
    3. Filtre local strict (anti-faux-positifs __contains)
    4. Déduplication co-titulaires (marchés multi-attributaires)
    5. Classification métier + normalisation

    Retourne une liste de dicts normalisés.
    """
    date_seuil = (date.today() - timedelta(days=annees * 365)).isoformat()

    params_base = {
        "acheteur_id__contains": SIREN_FRANCE_TRAVAIL,
        "modification_id__exact": "0",
        "donneesActuelles__exact": "True",
        "dateNotification__greater": date_seuil,
        "page_size": str(TAILLE_PAGE),
    }

    if verbose:
        print(f"  [DECP-Cons] Source  : DECP consolidée data.gouv.fr "
              f"(ressource {RESSOURCE_ID[:8]}…)")
        print(f"  [DECP-Cons] Filtre  : acheteur contient {SIREN_FRANCE_TRAVAIL}, "
              f"notifié depuis {date_seuil}")

    bruts = []
    page = 1
    plafond = limite or MAX_RESULTATS_TOTAL
    total_disponible = None

    while len(bruts) < plafond:
        params = dict(params_base, page=str(page))
        rep = _appeler_page(params, verbose=False)
        if not rep:
            if verbose:
                print(f"  [DECP-Cons] Échec appel page {page}")
            break

        data = rep.get("data") or []
        meta = rep.get("meta") or {}

        if total_disponible is None:
            total_disponible = meta.get("total", 0)
            if verbose:
                print(f"  [DECP-Cons] Total disponible : {total_disponible} ligne(s)")

        if not data:
            break

        bruts.extend(data)
        if verbose:
            print(f"  [DECP-Cons] Page {page:>3} : +{len(data):>3}  "
                  f"(cumul {len(bruts):>4} / {total_disponible})")

        if len(bruts) >= total_disponible:
            break
        page += 1

    if verbose:
        print(f"  [DECP-Cons] Total reçu : {len(bruts)} lignes brutes")

    # Filtre strict anti-faux-positifs du __contains
    avant = len(bruts)
    bruts = [b for b in bruts
              if (b.get("acheteur_id") or "").startswith(SIREN_FRANCE_TRAVAIL)]
    if verbose and avant != len(bruts):
        print(f"  [DECP-Cons] Filtre SIREN strict : "
              f"{avant - len(bruts)} faux positifs écartés")

    # Classification + normalisation
    marches_normalises = []
    for b in bruts:
        cat = classifier(b)
        norm = _normaliser(b, cat)
        if norm:
            marches_normalises.append(norm)

    # Déduplication des co-titulaires (multi-attributaires)
    avant_dedup = len(marches_normalises)
    marches_normalises = _dedupliquer_co_titulaires(marches_normalises)
    if verbose and avant_dedup != len(marches_normalises):
        print(f"  [DECP-Cons] Dédup co-titulaires : "
              f"{avant_dedup} lignes → {len(marches_normalises)} marchés uniques")

    if verbose:
        cats = Counter(m.get("categorie_metier") for m in marches_normalises)
        print(f"  [DECP-Cons] Classification :")
        for c, n in cats.most_common():
            print(f"    {c:12} : {n}")

    return marches_normalises


# Alias pour rétrocompatibilité (ancien nom utilisé par tendia_decp.py)
recuperer = lister_marches_notifies
