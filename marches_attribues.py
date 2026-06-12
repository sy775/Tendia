"""
marches_attribues.py
--------------------
Gestion de la collection `marches_tendia_attribues` : marchés qu'on a vus
passer ouverts, dont on a (ou pas) le brief LLM enrichi, et dont l'attribution
DECP a été capturée ex-post.

C'est notre base de référence haute qualité. Elle reste petite (quelques
dizaines à quelques centaines d'entrées maximum) mais chaque entrée est
densément documentée :
    - le marché actif (titre, acheteur, dates, périmètre, catégorie)
    - le brief LLM (volumes, durée, complexité, qualification, public, ...)
    - l'attribution DECP (titulaire, montant, offres reçues, ...)
    - les ratios validés calculés depuis les 3 sources : €/bénéficiaire,
      €/mois, €/heure effective le cas échéant.

Cette base est utilisée prioritairement par `concurrence.py` pour calibrer
l'estimation de prix. Quand elle est vide ou maigre, le système retombe sur
DECP brut (avec moins de confiance) ou sur le bottom-up seul.

API publique :
    lire_tous()       -> dict {id: entrée}
    lire(id)          -> entrée | None
    ecrire(id, data)  -> None
    supprimer(id)     -> bool
    compter()         -> int
    schema_entree()   -> dict (exemple de schéma pour documentation/init)
    construire_entree(marche_actif, brief, attribution_decp, matching_meta)
                      -> entrée (avec ratios calculés)
"""

from datetime import datetime, timezone
from typing import Optional

import stockage


COLLECTION = "marches_tendia_attribues"


# ---------------------------------------------------------------------------
# Schéma de référence
# ---------------------------------------------------------------------------

def schema_entree() -> dict:
    """Schéma documentaire d'une entrée. Utile pour rédiger des tests, des
    exports, ou pour onboarding. N'est PAS appelé en runtime.
    """
    return {
        # Identité
        "id": "APTIA-<hash>",
        "id_marche_actif": "BOAMP-26-51011",   # null si attribution récupérée sans avoir vu l'avis ouvert
        "id_decp": "DECP-2948093",             # référence du marché DECP source de l'attribution
        "id_brief": "BOAMP-26-51011",          # référence du brief LLM (= clé de data/extractions/)

        # Marché — projection légère (les détails complets restent dans marches.json)
        "marche": {
            "titre": "...",
            "objet": "...",
            "acheteur_nom": "FRANCE TRAVAIL",
            "acheteur_siret": "13000548...",
            "date_publication": "2025-04-15",
            "date_limite_depot": "2025-06-15",
            "date_notification": "2025-09-10",
            "dr": "NAQ",
            "lieu_execution": "33",
            "categorie_metier": "insertion",
            "cpv_principal": "85312300-2",
            "perimetre_geographique": "Bordeaux métropole",
        },

        # Brief LLM — projection légère (les détails complets restent dans data/extractions/)
        "brief": {
            "duree_mois": 48,
            "nb_beneficiaires_total": 140,
            "qualification_intervenants": "BAC+3/5",
            "complexite": 1.2,
            "publics_tags": ["seniors", "DELD"],
            "prestation_precise": "Accompagnement Activ Seniors 50+",
            "public_cible": "DE 50 ans et plus, non-cadres",
            "forme_prix": "Unitaire",
            "attend_rse": True,
        },

        # Attribution DECP — données ex-post
        "attribution": {
            "titulaire_nom": "ENVERGURE",
            "titulaire_siret": "...",
            "titulaire_categorie": "ETI",
            "co_titulaires_sirets": [],
            "montant_eur": 720000.0,
            "duree_mois": 48,
            "offres_recues": 6,
            "forme_prix": "Unitaire",
            "procedure": "Appel d'offres ouvert",
            "considerations_sociales": True,
            "considerations_environnementales": False,
        },

        # Ratios validés (calculés depuis brief + attribution)
        "ratios": {
            "prix_total_eur": 720000.0,
            "prix_mensuel_eur": 15000.0,
            "prix_par_beneficiaire_eur": 5142.86,
            "prix_par_heure_effective_eur": None,
            "prix_par_session_eur": None,
        },

        # Métadonnées de capture / matching
        "_meta": {
            "matching_confiance": "haute",      # haute | moyenne | a_valider | manuel
            "matching_methode": "reference_externe_exacte",
            "matching_score": 0.95,
            "ts_capture": "2026-06-07T12:00:00Z",
            "valide_manuellement": False,
            "notes": None,
        },
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def lire_tous() -> dict:
    """Retourne toute la collection {id: entrée}."""
    return stockage.charger(COLLECTION)


def lire(id_entree: str) -> Optional[dict]:
    """Retourne une entrée ou None."""
    return stockage.lire(COLLECTION, id_entree)


def ecrire(id_entree: str, entree: dict) -> None:
    """Crée ou écrase une entrée."""
    stockage.ecrire(COLLECTION, id_entree, entree)


def supprimer(id_entree: str) -> bool:
    """Supprime une entrée. Retourne True si supprimée, False si absente."""
    return stockage.supprimer(COLLECTION, id_entree)


def compter() -> int:
    """Nombre d'entrées dans la collection."""
    return len(lire_tous())


# ---------------------------------------------------------------------------
# Construction d'une entrée
# ---------------------------------------------------------------------------

def construire_entree(marche_actif: Optional[dict],
                       brief: Optional[dict],
                       attribution_decp: dict,
                       matching_meta: Optional[dict] = None) -> dict:
    """Compose une entrée à partir des 3 sources.

    Args:
        marche_actif: dict du marché ouvert tel qu'on l'avait collecté (BOAMP).
                       Peut être None si l'attribution est capturée
                       rétroactivement sans avoir vu l'avis ouvert.
        brief: dict du brief LLM (peut être None si extraction non faite).
        attribution_decp: dict du marché notifié DECP (source de vérité ex-post).
                          OBLIGATOIRE.
        matching_meta: dict {confiance, methode, score} sur le matching.
                       Optionnel — défauts raisonnables sinon.

    Returns:
        Entrée prête à être persistée.
    """
    if not attribution_decp:
        raise ValueError("attribution_decp est obligatoire")

    # Identifiants
    id_decp = attribution_decp.get("id")
    id_marche_actif = marche_actif.get("id") if marche_actif else None
    id_brief = (brief or {}).get("_id_marche") or id_marche_actif

    # Projection légère du marché actif
    marche_proj = {}
    if marche_actif:
        marche_proj = {
            "titre": marche_actif.get("titre"),
            "objet": marche_actif.get("objet"),
            "acheteur_nom": marche_actif.get("acheteur_nom"),
            "acheteur_siret": marche_actif.get("acheteur_siret"),
            "date_publication": marche_actif.get("date_publication"),
            "date_limite_depot": marche_actif.get("date_limite_depot"),
            "dr": marche_actif.get("dr") or marche_actif.get("region_code"),
            "lieu_execution": marche_actif.get("lieu_execution"),
            "categorie_metier": marche_actif.get("categorie_metier"),
            "cpv_principal": marche_actif.get("cpv_principal"),
            "perimetre_geographique": marche_actif.get("perimetre_geographique"),
        }
    # Compléter depuis DECP si marché actif absent
    if not marche_proj.get("acheteur_nom"):
        marche_proj["acheteur_nom"] = attribution_decp.get("acheteur_nom")
    if not marche_proj.get("acheteur_siret"):
        marche_proj["acheteur_siret"] = attribution_decp.get("acheteur_id")
    if not marche_proj.get("objet"):
        marche_proj["objet"] = attribution_decp.get("objet")
    if not marche_proj.get("categorie_metier"):
        marche_proj["categorie_metier"] = attribution_decp.get("categorie_metier")
    if not marche_proj.get("cpv_principal"):
        marche_proj["cpv_principal"] = attribution_decp.get("cpv_principal")
    if not marche_proj.get("lieu_execution"):
        marche_proj["lieu_execution"] = attribution_decp.get("lieu_execution")

    # Date de notification depuis DECP
    marche_proj["date_notification"] = attribution_decp.get("date_notification")

    # Projection légère du brief
    brief_proj = {}
    if brief:
        vol = brief.get("volumes") or {}
        dm = brief.get("duree_marche") or {}
        brief_proj = {
            "duree_mois": (dm.get("nb_mois_total_max")
                            or dm.get("nb_mois_periode_ferme")),
            "nb_beneficiaires_total": vol.get("nb_beneficiaires_total"),
            "qualification_intervenants": (brief.get("qualification_intervenants")
                                            or vol.get("qualification_intervenants")),
            "complexite": brief.get("complexite_coef"),
            "publics_tags": _publics_tags_from_brief(brief),
            "prestation_precise": brief.get("prestation_precise"),
            "public_cible": (brief.get("publics_cibles") or {}).get("description"),
            "forme_prix": (brief.get("bareme_notation") or {}).get("prix", {}).get("type_formule"),
            "attend_rse": _attend_rse_from_brief(brief),
        }

    # Attribution — copie des champs utiles
    attr_proj = {
        "titulaire_nom": attribution_decp.get("titulaire_nom"),
        "titulaire_siret": attribution_decp.get("titulaire_siret"),
        "titulaire_categorie": attribution_decp.get("titulaire_categorie"),
        "co_titulaires_sirets": attribution_decp.get("co_titulaires_sirets") or [],
        "montant_eur": attribution_decp.get("montant_eur"),
        "duree_mois": attribution_decp.get("duree_mois"),
        "offres_recues": attribution_decp.get("offres_recues"),
        "forme_prix": attribution_decp.get("forme_prix"),
        "procedure": attribution_decp.get("procedure"),
        "considerations_sociales": _bool_decp(
            attribution_decp.get("considerations_sociales")
        ),
        "considerations_environnementales": _bool_decp(
            attribution_decp.get("considerations_environnementales")
        ),
    }

    # Ratios calculés
    ratios = _calculer_ratios(brief_proj, attr_proj)

    # Meta de matching (défauts si absents)
    meta_in = matching_meta or {}
    meta = {
        "matching_confiance": meta_in.get("confiance", "a_valider"),
        "matching_methode": meta_in.get("methode", "non_specifie"),
        "matching_score": meta_in.get("score"),
        "ts_capture": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "valide_manuellement": False,
        "notes": meta_in.get("notes"),
    }

    return {
        "id": id_decp or id_marche_actif,
        "id_marche_actif": id_marche_actif,
        "id_decp": id_decp,
        "id_brief": id_brief,
        "marche": marche_proj,
        "brief": brief_proj,
        "attribution": attr_proj,
        "ratios": ratios,
        "_meta": meta,
    }


def _calculer_ratios(brief_proj: dict, attr_proj: dict) -> dict:
    """Calcule les ratios validés à partir des données ex-post.

    Quand une donnée est manquante (ex: pas de nb_beneficiaires_total), le
    ratio correspondant est None — pas d'extrapolation à la louche.
    """
    montant = attr_proj.get("montant_eur") or 0
    duree = attr_proj.get("duree_mois") or 0
    nb_benef = (brief_proj or {}).get("nb_beneficiaires_total") or 0

    ratios = {
        "prix_total_eur": float(montant) if montant else None,
        "prix_mensuel_eur": None,
        "prix_par_beneficiaire_eur": None,
        "prix_par_heure_effective_eur": None,
        "prix_par_session_eur": None,
    }

    if montant > 0 and duree > 0:
        ratios["prix_mensuel_eur"] = round(float(montant) / float(duree), 2)

    if montant > 0 and nb_benef > 0:
        ratios["prix_par_beneficiaire_eur"] = round(
            float(montant) / float(nb_benef), 2
        )

    return ratios


def _publics_tags_from_brief(brief: dict) -> list:
    """Extrait une liste de tags publics depuis le brief (très tolérant)."""
    if not brief:
        return []
    pc = brief.get("publics_cibles") or {}
    tags = pc.get("publics_specifiques_signales") or []
    if isinstance(tags, list):
        return tags
    return []


def _attend_rse_from_brief(brief: dict) -> bool:
    """True si le brief mentionne des attentes RSE/sociales/environnementales."""
    if not brief:
        return False
    bareme = brief.get("bareme_notation") or {}
    scs = bareme.get("sous_criteres_techniques") or []
    for sc in scs:
        if not isinstance(sc, dict):
            continue
        lib = (sc.get("libelle") or "").lower()
        if any(mc in lib for mc in ("rse", "environnement", "social", "gaz à effet", "ges")):
            return True
    # Vérif alertes_candidat
    alertes = brief.get("alertes_candidat") or []
    for a in alertes:
        al = (a or "").lower()
        if "insertion sociale" in al or "clause d'insertion" in al:
            return True
    return False


def _bool_decp(val) -> bool:
    """Normalise un champ DECP qui peut être 'Sans objet', None, True/False."""
    if val is True:
        return True
    if val is False or val is None:
        return False
    s = str(val).strip().lower()
    return s not in ("", "sans objet", "non", "false", "0")


# ---------------------------------------------------------------------------
# Filtrage / recherche pour le KNN concurrence
# ---------------------------------------------------------------------------

def lister_pour_knn() -> list:
    """Retourne la liste des entrées formatées comme des marchés notifiés DECP
    pour pouvoir être directement consommées par `concurrence.zone_prix_marche`.

    Chaque entrée Tendia est convertie en dict avec la même structure qu'un
    `marches_notifies[id]` (id, montant_eur, duree_mois, titulaire_nom, etc.)
    + un flag `_source = 'tendia'` qui permet à l'UI de les distinguer.
    """
    entrees = lire_tous()
    resultats = []
    for id_e, e in entrees.items():
        attr = e.get("attribution") or {}
        marche = e.get("marche") or {}
        # Conversion bool → string (format DECP attendu par _calculer_similarite)
        cs = attr.get("considerations_sociales")
        cs_str = "oui" if cs is True else ("non" if cs is False else (cs or ""))
        ce = attr.get("considerations_environnementales")
        ce_str = "oui" if ce is True else ("non" if ce is False else (ce or ""))
        # Pseudo-marché DECP enrichi
        pseudo = {
            "id": e.get("id") or id_e,
            "_source": "tendia",
            "montant_eur": attr.get("montant_eur"),
            "duree_mois": attr.get("duree_mois"),
            "titulaire_nom": attr.get("titulaire_nom"),
            "titulaire_siret": attr.get("titulaire_siret"),
            "titulaire_categorie": attr.get("titulaire_categorie"),
            "co_titulaires_sirets": attr.get("co_titulaires_sirets") or [],
            "offres_recues": attr.get("offres_recues"),
            "forme_prix": attr.get("forme_prix"),
            "procedure": attr.get("procedure"),
            "considerations_sociales": cs_str,
            "considerations_environnementales": ce_str,
            "acheteur_nom": marche.get("acheteur_nom"),
            "acheteur_id": marche.get("acheteur_siret"),
            "categorie_metier": marche.get("categorie_metier"),
            "cpv_principal": marche.get("cpv_principal"),
            "lieu_execution": marche.get("lieu_execution"),
            "objet": marche.get("objet"),
            "date_notification": marche.get("date_notification"),
            # On expose la projection brief pour que le KNN dispose des
            # features fines (volumes, qualification, publics tags...)
            "_brief_proj": e.get("brief") or {},
        }
        if pseudo["montant_eur"] and pseudo["duree_mois"]:
            resultats.append(pseudo)
    return resultats
