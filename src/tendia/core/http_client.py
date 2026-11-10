"""
http_client.py
--------------
Wrapper HTTP utilisant requests (curl_cffi désactivé suite à un bug
d'encodage avec AWS-Achat : header HTTP déclare UTF-8 mais le body est
en réalité en ISO-8859-1, curl_cffi plante en mode strict).

Garde l'API du Sprint Industrialisation v2 pour compat des autres modules
(Session, get, post, exceptions).

Tout le reste du Sprint Industrialisation v2 reste actif :
- Proxy Bright Data + session-id (rotation IP)
- Anti-Ban v1 (rate-limit, UA tournants, plages horaires)
- Retry sur ban
- Logs structurés
- Monitoring
"""
import logging

logger = logging.getLogger(__name__)

# SSL : sur certains postes (Windows, interception TLS antivirus/proxy), le
# bundle `certifi` ne contient pas le CA intermédiaire nécessaire et toute
# requête HTTPS échoue (SSLCertVerificationError) — y compris vers 2captcha.com
# et *.e-marchespublics.com. `truststore` fait utiliser à Python le magasin de
# certificats du SYSTÈME (qui, lui, possède le CA), ce qui répare la
# vérification pour TOUS les hôtes sans jamais désactiver verify. Injecté ici
# (module HTTP central importé partout) avant toute connexion. No-op si absent.
try:
    import truststore as _truststore
    _truststore.inject_into_ssl()
    logger.info("SSL : truststore actif (magasin de certificats systeme)")
except Exception as _e:  # pragma: no cover - dépend de l'environnement
    logger.info("SSL : truststore indisponible (%s) - certifi par defaut", _e)

# PATCH disable_curl_cffi : on force le backend requests, qui est plus
# tolérant sur les encodages (gère ISO-8859-1 automatiquement via le
# meta http-equiv du HTML).
import requests as _requests

_curl = None
BACKEND = "requests"
DEFAULT_IMPERSONATE = None
logger.info("HTTP backend : requests (curl_cffi desactive par patch encoding)")


def Session(*args, **kwargs):
    """Crée une Session HTTP requests standard."""
    kwargs.pop("impersonate", None)  # ignorer si fourni
    return _requests.Session(*args, **kwargs)


def get(*args, **kwargs):
    """GET via requests."""
    kwargs.pop("impersonate", None)
    return _requests.get(*args, **kwargs)


def post(*args, **kwargs):
    """POST via requests."""
    kwargs.pop("impersonate", None)
    return _requests.post(*args, **kwargs)


# Exceptions, unifiées
RequestException = _requests.exceptions.RequestException
Timeout = _requests.exceptions.Timeout
ConnectionError = _requests.exceptions.ConnectionError
