"""
http_client.py
--------------
Wrapper HTTP qui utilise curl_cffi (fingerprint TLS Chrome via
libcurl-impersonate) si disponible, et retombe sur `requests` standard sinon.

But : rendre Tendia indistinguable d'un Chrome réel côté serveur (handshake
TLS + ordre des en-têtes), sans navigateur réel — en complément du comportement
humain de http_humain (rate-limit, UA tournant, proxy résidentiel).

API : Session(), get(), post(), et les exceptions RequestException / Timeout /
ConnectionError, compatibles quel que soit le backend. Si curl_cffi est absent
ou si une requête impersonate échoue, on dégrade proprement sur requests.

    Robustesse > furtivité absolue.
"""
import logging

logger = logging.getLogger(__name__)

# Backend curl_cffi (préféré) avec fallback requests. On garde TOUJOURS une
# référence vers requests pour le fallback par-requête (cf get/post ci-dessous).
import requests as _requests

try:
    from curl_cffi import requests as _curl
    BACKEND = "curl_cffi"
    # Cible d'imitation : Chrome 131 (présent dans curl_cffi 0.13).
    DEFAULT_IMPERSONATE = "chrome131"
    logger.info("HTTP backend : curl_cffi (TLS fingerprint Chrome %s)",
                DEFAULT_IMPERSONATE)
except Exception as _e:  # ImportError ou échec de chargement natif
    _curl = None
    BACKEND = "requests"
    DEFAULT_IMPERSONATE = None
    logger.warning("HTTP backend : requests standard (curl_cffi indisponible : %s)",
                   _e)


def Session(*args, **kwargs):
    """Crée une Session HTTP.

    Avec curl_cffi, injecte impersonate=chrome par défaut (sauf si l'appelant
    fournit le sien). Avec requests, on retire un éventuel `impersonate` (non
    supporté) pour rester compatible.
    """
    if BACKEND == "curl_cffi":
        kwargs.setdefault("impersonate", DEFAULT_IMPERSONATE)
        return _curl.Session(*args, **kwargs)
    kwargs.pop("impersonate", None)
    return _requests.Session(*args, **kwargs)


def get(*args, **kwargs):
    """GET via le backend actif, avec fallback requests si l'impersonate casse."""
    if BACKEND == "curl_cffi":
        kwargs.setdefault("impersonate", DEFAULT_IMPERSONATE)
        try:
            return _curl.get(*args, **kwargs)
        except Exception as e:
            logger.warning("curl_cffi GET a échoué (%s), fallback requests", e)
            kwargs.pop("impersonate", None)
    else:
        kwargs.pop("impersonate", None)
    return _requests.get(*args, **kwargs)


def post(*args, **kwargs):
    """POST via le backend actif, avec fallback requests si l'impersonate casse."""
    if BACKEND == "curl_cffi":
        kwargs.setdefault("impersonate", DEFAULT_IMPERSONATE)
        try:
            return _curl.post(*args, **kwargs)
        except Exception as e:
            logger.warning("curl_cffi POST a échoué (%s), fallback requests", e)
            kwargs.pop("impersonate", None)
    else:
        kwargs.pop("impersonate", None)
    return _requests.post(*args, **kwargs)


# --- Exceptions, unifiées quel que soit le backend ---
# Les classes curl_cffi héritent de noms identiques à requests (RequestException,
# Timeout, ConnectionError) ; on les ré-exporte pour que les downloaders fassent
# `except http_client.Timeout` sans connaître le backend.
if BACKEND == "curl_cffi":
    from curl_cffi.requests import exceptions as _ex
    RequestException = _ex.RequestException
    Timeout = _ex.Timeout
    ConnectionError = _ex.ConnectionError
else:
    RequestException = _requests.exceptions.RequestException
    Timeout = _requests.exceptions.Timeout
    ConnectionError = _requests.exceptions.ConnectionError
