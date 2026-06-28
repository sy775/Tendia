"""
http_utils.py
-------------
Utilitaires HTTP partagés par les connecteurs Tendia.

Session requests unique avec User-Agent identifié, politesse entre requêtes,
retry sur erreurs transitoires, timeout par défaut.

Aucun état persistant. Module utilitaire pur.
"""

import random
import time
import requests
from typing import Optional

# SSL : sur ce poste Windows, le magasin certifi ne contient pas tous les CA
# intermédiaires de BOAMP/OpenDataSoft (et e-marchespublics, etc.). `truststore`
# fait pointer Python sur le magasin de certificats système. Sans cette injection,
# `get_json` échoue en CERTIFICATE_VERIFY_FAILED (dette technique B4). L'injection
# est globale au process et idempotente.
try:
    import truststore as _truststore
    _truststore.inject_into_ssl()
except Exception:
    pass


USER_AGENT = (
    "Tendia/0.1 (veille marches publics formation France Travail; "
    "contact via projet local)"
)
DELAI_POLITESSE_SEC = 0.5
NB_TENTATIVES = 5
# Backoff exponentiel + jitter : 3 → 6 → 12 → 24 s (plafonné à DELAI_MAX_SEC).
# Indispensable face au soft rate-limiting d'OpenDataSoft/BOAMP, qui se traduit
# par des resets TLS (SSLError, sous-classe de ConnectionError) sur les rafales
# de pagination : un backoff court de 2 s ne laissait pas le throttle retomber.
DELAI_BASE_SEC = 3.0
DELAI_MAX_SEC = 30.0
DELAI_ENTRE_TENTATIVES_SEC = DELAI_BASE_SEC  # conservé pour compat (imports tiers)
TIMEOUT_DEFAUT = 30


def _dormir_backoff(tentative: int, reponse=None) -> None:
    """Attente avant retry : respecte `Retry-After` si présent, sinon backoff
    exponentiel (DELAI_BASE × 2^(n-1), plafonné) avec jitter ±30 %."""
    if reponse is not None:
        retry_after = reponse.headers.get("Retry-After")
        if retry_after:
            try:
                time.sleep(min(float(retry_after), DELAI_MAX_SEC))
                return
            except (ValueError, TypeError):
                pass
    base = min(DELAI_BASE_SEC * (2 ** (tentative - 1)), DELAI_MAX_SEC)
    time.sleep(base + random.uniform(0, base * 0.3))


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
            # 429 (rate-limit) et 5xx : ré-essayables avec backoff.
            if reponse.status_code == 429 or reponse.status_code >= 500:
                derniere_erreur = requests.HTTPError(
                    f"HTTP {reponse.status_code} : {reponse.text[:200]}"
                )
                if tentative < NB_TENTATIVES:
                    if verbose:
                        print(f"    -> HTTP {reponse.status_code}, backoff...")
                    _dormir_backoff(tentative, reponse)
                    continue
            # Autres 4xx : erreur définitive, pas de retry.
            if 400 <= reponse.status_code < 500:
                try:
                    detail = reponse.json()
                except ValueError:
                    detail = reponse.text[:500]
                raise requests.HTTPError(
                    f"HTTP {reponse.status_code} sur {url} : {detail}"
                )
            reponse.raise_for_status()
            return reponse.json()
        except (requests.ConnectionError, requests.Timeout) as e:
            derniere_erreur = e
            if tentative < NB_TENTATIVES:
                if verbose:
                    print(f"    -> erreur réseau ({type(e).__name__}), backoff...")
                _dormir_backoff(tentative)
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
            # 429 (rate-limit) et 5xx : ré-essayables avec backoff.
            if reponse.status_code == 429 or reponse.status_code >= 500:
                derniere_erreur = requests.HTTPError(
                    f"HTTP {reponse.status_code} : {reponse.text[:200]}"
                )
                if tentative < NB_TENTATIVES:
                    if verbose:
                        print(f"    -> HTTP {reponse.status_code}, backoff...")
                    _dormir_backoff(tentative, reponse)
                    continue
            # Autres 4xx : erreur définitive, pas de retry.
            if 400 <= reponse.status_code < 500:
                try:
                    detail = reponse.json()
                except ValueError:
                    detail = reponse.text[:500]
                raise requests.HTTPError(
                    f"HTTP {reponse.status_code} sur {url} : {detail}"
                )
            reponse.raise_for_status()
            return reponse.json()
        except (requests.ConnectionError, requests.Timeout) as e:
            derniere_erreur = e
            if tentative < NB_TENTATIVES:
                if verbose:
                    print(f"    -> erreur réseau ({type(e).__name__}), backoff...")
                _dormir_backoff(tentative)
                continue
        except ValueError as e:
            raise RuntimeError(f"Réponse non-JSON depuis {url} : {e}")
    raise RuntimeError(
        f"Échec après {NB_TENTATIVES} tentatives sur {url} : {derniere_erreur}"
    )
