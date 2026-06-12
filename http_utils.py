"""
http_utils.py
-------------
Utilitaires HTTP partagés par les connecteurs Tendia.

Session requests unique avec User-Agent identifié, politesse entre requêtes,
retry sur erreurs transitoires, timeout par défaut.

Aucun état persistant. Module utilitaire pur.
"""

import time
import requests
from typing import Optional


USER_AGENT = (
    "Tendia/0.1 (veille marches publics formation France Travail; "
    "contact via projet local)"
)
DELAI_POLITESSE_SEC = 0.5
NB_TENTATIVES = 3
DELAI_ENTRE_TENTATIVES_SEC = 2.0
TIMEOUT_DEFAUT = 30


_session = requests.Session()
_session.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": "application/json, */*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
})

_dernier_appel: dict = {}


def _attendre_si_besoin(url: str) -> None:
    """Politesse : pas plus d'une requête toutes les 0.5s sur le même hôte."""
    from urllib.parse import urlparse
    hote = urlparse(url).netloc
    if hote in _dernier_appel:
        ecoule = time.time() - _dernier_appel[hote]
        if ecoule < DELAI_POLITESSE_SEC:
            time.sleep(DELAI_POLITESSE_SEC - ecoule)
    _dernier_appel[hote] = time.time()


def get_json(url: str, params: Optional[dict] = None,
             timeout: int = TIMEOUT_DEFAUT,
             verbose: bool = False) -> dict:
    """GET avec retry sur erreurs transitoires (réseau, 5xx). 4xx = pas de retry."""
    derniere_erreur: Optional[Exception] = None
    for tentative in range(1, NB_TENTATIVES + 1):
        _attendre_si_besoin(url)
        try:
            if verbose:
                print(f"  GET {url} (tentative {tentative}/{NB_TENTATIVES})")
            reponse = _session.get(url, params=params, timeout=timeout)
            if 400 <= reponse.status_code < 500:
                try:
                    detail = reponse.json()
                except ValueError:
                    detail = reponse.text[:500]
                raise requests.HTTPError(
                    f"HTTP {reponse.status_code} sur {url} : {detail}"
                )
            if reponse.status_code >= 500:
                derniere_erreur = requests.HTTPError(
                    f"HTTP {reponse.status_code} : {reponse.text[:200]}"
                )
                if tentative < NB_TENTATIVES:
                    time.sleep(DELAI_ENTRE_TENTATIVES_SEC * tentative)
                    continue
            reponse.raise_for_status()
            return reponse.json()
        except (requests.ConnectionError, requests.Timeout) as e:
            derniere_erreur = e
            if tentative < NB_TENTATIVES:
                if verbose:
                    print(f"    -> erreur réseau, retry...")
                time.sleep(DELAI_ENTRE_TENTATIVES_SEC * tentative)
                continue
        except ValueError as e:
            raise RuntimeError(f"Réponse non-JSON depuis {url} : {e}")
    raise RuntimeError(
        f"Échec après {NB_TENTATIVES} tentatives sur {url} : {derniere_erreur}"
    )


def post_json(url: str, body: dict, timeout: int = TIMEOUT_DEFAUT,
              verbose: bool = False) -> dict:
    """POST JSON avec retry."""
    derniere_erreur: Optional[Exception] = None
    for tentative in range(1, NB_TENTATIVES + 1):
        _attendre_si_besoin(url)
        try:
            if verbose:
                print(f"  POST {url} (tentative {tentative}/{NB_TENTATIVES})")
            reponse = _session.post(
                url, json=body, timeout=timeout,
                headers={"Content-Type": "application/json"}
            )
            if 400 <= reponse.status_code < 500:
                try:
                    detail = reponse.json()
                except ValueError:
                    detail = reponse.text[:500]
                raise requests.HTTPError(
                    f"HTTP {reponse.status_code} sur {url} : {detail}"
                )
            if reponse.status_code >= 500:
                derniere_erreur = requests.HTTPError(
                    f"HTTP {reponse.status_code} : {reponse.text[:200]}"
                )
                if tentative < NB_TENTATIVES:
                    time.sleep(DELAI_ENTRE_TENTATIVES_SEC * tentative)
                    continue
            reponse.raise_for_status()
            return reponse.json()
        except (requests.ConnectionError, requests.Timeout) as e:
            derniere_erreur = e
            if tentative < NB_TENTATIVES:
                if verbose:
                    print(f"    -> erreur réseau, retry...")
                time.sleep(DELAI_ENTRE_TENTATIVES_SEC * tentative)
                continue
        except ValueError as e:
            raise RuntimeError(f"Réponse non-JSON depuis {url} : {e}")
    raise RuntimeError(
        f"Échec après {NB_TENTATIVES} tentatives sur {url} : {derniere_erreur}"
    )
