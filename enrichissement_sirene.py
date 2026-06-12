"""
enrichissement_sirene.py
------------------------
Enrichit les SIRET avec le nom de l'organisme via l'API publique
recherche-entreprises.api.gouv.fr (gratuite, sans authentification).

Cache : les noms d'entreprises sont stockés dans la collection `titulaires`
de stockage, pour éviter de re-interroger l'API à chaque lancement.

Limite de l'API : 7 requêtes/seconde. Le module respecte cette limite via
http_utils (politesse 0.5s entre appels = 2/s, bien en dessous).

Doc API : https://recherche-entreprises.api.gouv.fr/docs/
"""

import sys
from datetime import datetime, timezone
from typing import Optional

from http_utils import get_json
import stockage


SIRENE_URL = "https://recherche-entreprises.api.gouv.fr/search"
COLLECTION_TITULAIRES = "titulaires"


# ---------------------------------------------------------------------------
# Cache via stockage
# ---------------------------------------------------------------------------

def _lire_cache(siret: str) -> Optional[dict]:
    """Retourne l'entrée cache pour un SIRET, ou None."""
    return stockage.lire(COLLECTION_TITULAIRES, siret)


def _ecrire_cache(siret: str, donnees: dict) -> None:
    donnees_finale = dict(donnees)
    donnees_finale["siret"] = siret
    donnees_finale["date_enrichissement"] = datetime.now(timezone.utc).isoformat()
    stockage.ecrire(COLLECTION_TITULAIRES, siret, donnees_finale)


# ---------------------------------------------------------------------------
# Appel API
# ---------------------------------------------------------------------------

def _appeler_api(siret: str) -> Optional[dict]:
    """Appelle l'API SIRENE pour un SIRET donné. Retourne None si échec."""
    try:
        reponse = get_json(SIRENE_URL, params={"q": siret, "per_page": 1},
                            verbose=False)
    except Exception as e:
        print(f"  [SIRENE] ⚠ Erreur sur {siret} : {str(e)[:150]}",
              file=sys.stderr)
        return None
    results = reponse.get("results") or []
    if not results:
        return None
    res = results[0]
    # Trouver l'établissement correspondant au SIRET exact
    etablissements = res.get("matching_etablissements") or []
    etablissement = next(
        (e for e in etablissements if e.get("siret") == siret),
        etablissements[0] if etablissements else {}
    )
    return {
        "nom_complet": res.get("nom_complet") or res.get("nom_raison_sociale"),
        "nom_raison_sociale": res.get("nom_raison_sociale"),
        "siren": res.get("siren"),
        "categorie_entreprise": res.get("categorie_entreprise"),
        "tranche_effectif": (res.get("tranche_effectif_salarie")
                              or res.get("tranche_effectif")),
        "date_creation": res.get("date_creation"),
        "activite_principale": res.get("activite_principale"),
        "section_activite_principale": res.get("section_activite_principale"),
        "etat_administratif": res.get("etat_administratif"),
        # Établissement spécifique au SIRET interrogé
        "etablissement_siret": etablissement.get("siret"),
        "etablissement_commune": (etablissement.get("libelle_commune")
                                    or etablissement.get("commune")),
        "etablissement_code_postal": etablissement.get("code_postal"),
        "etablissement_departement": etablissement.get("departement"),
        "etablissement_region": etablissement.get("region"),
    }


# ---------------------------------------------------------------------------
# Interface publique
# ---------------------------------------------------------------------------

def enrichir(siret: str, force_refresh: bool = False) -> Optional[dict]:
    """
    Retourne les infos enrichies d'un SIRET, avec cache.

    Args:
        siret: SIRET (14 chiffres).
        force_refresh: si True, ignore le cache et re-interroge l'API.

    Returns:
        dict avec nom_complet, nom_raison_sociale, commune, etc., ou None
        si le SIRET n'existe pas.
    """
    if not siret or len(siret) != 14 or not siret.isdigit():
        return None

    if not force_refresh:
        cache = _lire_cache(siret)
        if cache is not None:
            return cache

    donnees = _appeler_api(siret)
    if donnees is None:
        return None

    _ecrire_cache(siret, donnees)
    return donnees


def enrichir_batch(sirets: list, verbose: bool = True) -> dict:
    """
    Enrichit une liste de SIRET. Retourne un dict {siret: donnees}.

    Avantage : déduplique avant de taper l'API, utilise le cache.
    """
    sirets_uniques = list({s for s in sirets if s})
    resultats: dict = {}
    n_total = len(sirets_uniques)
    n_cache = 0
    n_api = 0
    n_erreurs = 0

    for i, siret in enumerate(sirets_uniques, 1):
        if verbose and i % 20 == 0:
            print(f"  [SIRENE] Progression : {i}/{n_total} "
                  f"(cache: {n_cache}, API: {n_api}, erreurs: {n_erreurs})")
        # Vérifie le cache avant d'appeler
        cache = _lire_cache(siret)
        if cache is not None:
            resultats[siret] = cache
            n_cache += 1
            continue
        donnees = _appeler_api(siret)
        if donnees is None:
            n_erreurs += 1
            continue
        _ecrire_cache(siret, donnees)
        resultats[siret] = donnees
        n_api += 1

    if verbose:
        print(f"  [SIRENE] Bilan : {n_cache} depuis cache, {n_api} appels API, "
              f"{n_erreurs} erreurs sur {n_total} SIRET uniques.")
    return resultats


def nom_pour_siret(siret: str) -> Optional[str]:
    """Helper : retourne juste le nom d'un SIRET (depuis cache si dispo)."""
    if not siret:
        return None
    cache = _lire_cache(siret)
    if cache is not None:
        return cache.get("nom_complet") or cache.get("nom_raison_sociale")
    donnees = enrichir(siret)
    if donnees:
        return donnees.get("nom_complet") or donnees.get("nom_raison_sociale")
    return None


if __name__ == "__main__":
    import json
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("siret", type=str)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    donnees = enrichir(args.siret, force_refresh=args.force)
    if donnees is None:
        print(f"❌ SIRET {args.siret} introuvable.")
    else:
        print(json.dumps(donnees, ensure_ascii=False, indent=2))
