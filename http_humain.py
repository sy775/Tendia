"""
http_humain.py
--------------
Helpers pour faire des requêtes HTTP qui ressemblent à un usage humain
(rate-limit randomisé, User-Agent tournant, plages horaires, pauses
cumulatives) afin d'éviter les bans IP sur les plateformes DCE.

Utilisé par atexo_downloader, achatpublic_downloader, aws_downloader et les
futurs downloaders. Sans dépendance externe (stdlib + requests existant).

Contexte : le 13/06/2026, un batch AWS-Achat a déclenché un ban IP après
~10-15 sessions ColdFusion enchaînées en 1h (rythme fixe 3 s, UA unique).
Ce module rend le trafic indistinguable d'un usage humain raisonnable.
"""
import os
import random
import re
import time
import uuid
from datetime import datetime, time as dtime
from typing import Optional

# Charge .env / .env.txt à l'import : http_humain est le point central qui lit
# TENDIA_PROXY_URL ET les flags TENDIA_PROXY_FOR_<PLATEFORME>. Sans ça, un process
# qui ne charge pas l'env (worker, sous-process pipeline) ne voyait pas le proxy
# (→ IP réelle) ni les désactivations par plateforme (→ proxy actif à tort).
try:
    from dotenv import load_dotenv
    load_dotenv(".env")
    load_dotenv(".env.txt")
except Exception:
    pass

# Backend HTTP unifié (curl_cffi si dispo, sinon requests). Voir http_client.
import http_client as http_lib

# Pool de User-Agents Chrome/Firefox/Edge/Safari récents (mi-2026).
# Mélange Windows / macOS pour varier le fingerprint d'en-tête.
USER_AGENTS_POOL = [
    # Chrome Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    # Firefox Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
    # Edge Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36 Edg/149.0.0.0",
    # Chrome macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    # Safari macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
]

# Plage horaire crédible (heures de bureau)
HEURE_DEBUT_BUREAU = dtime(8, 0)
HEURE_FIN_BUREAU = dtime(19, 0)

# Patterns trahissant une page de ban / page d'accueil servie au lieu de la
# page applicative attendue (HTML5/Bootstrap moderne au lieu du ColdFusion
# classique). Source : ban AWS-Achat du 13/06/2026.
_PATTERNS_BAN = (
    "acheteurs.htm",
    "fournisseurs.htm",
    "bootstrap",
    "blocked",
    "access denied",
    "trop de requ"        # "trop de requêtes"
)


def _nettoyer_session_id(brut: str) -> str:
    """Réduit un identifiant à [a-z0-9] (Bright Data n'accepte pas les tirets
    dans le session-id, sinon le découpage `-session-` du username casse).
    Ex : "BOAMP-26-56599" -> "boamp2656599". Tronqué à 24 chars."""
    propre = re.sub(r"[^a-z0-9]", "", (brut or "").lower())
    return propre[:24]


def _injecter_session_id(proxy_url: str, session_id: str) -> str:
    """Injecte un session-id dans l'URL proxy Bright Data.

    http://user-zone-X:pass@host:port
        -> http://user-zone-X-session-SID:pass@host:port
    Une session-id différente = une IP différente du pool résidentiel.
    """
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(proxy_url)
    userinfo = parsed.username or ""
    new_userinfo = f"{userinfo}-session-{session_id}"
    if parsed.password is not None:
        new_userinfo += f":{parsed.password}"
    new_netloc = new_userinfo + "@" + (parsed.hostname or "")
    if parsed.port:
        new_netloc += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=new_netloc))


# Plateformes à ACCÈS ANONYME (pas de quota par IP, pas de ban connu) : le proxy
# résidentiel (payant au Go) y est INUTILE et même nuisible (latence, troncatures,
# coût). Proxy OFF par défaut pour elles — encodé en CODE (et pas seulement via
# .env) pour rester correct en checkout frais / cron sans .env.
# À l'inverse, proxy NÉCESSAIRE : aws_achat (ban historique), dematis (captcha/ban),
# marches_securises (rotation d'IP = seul contournement du quota par IP).
PLATEFORMES_SANS_PROXY = {"place", "boamp", "data_gouv", "atexo", "achatpublic"}


def _proxy_pour_plateforme(plateforme: Optional[str]) -> bool:
    """
    Décide si le proxy résidentiel doit être utilisé pour une plateforme.

    Politique : proxy ON par défaut (anti-ban), SAUF pour les plateformes à accès
    anonyme listées dans PLATEFORMES_SANS_PROXY (proxy inutile). Surcharge possible
    dans les deux sens via `TENDIA_PROXY_FOR_<PLATEFORME>=0/1` dans l'environnement.

    Args:
        plateforme: identifiant court (ex: "place", "dematis", "aws_achat").
            None → proxy activé (comportement historique).

    Returns:
        True si le proxy doit être appliqué, False sinon.
    """
    if not plateforme:
        return True
    flag = os.environ.get(f"TENDIA_PROXY_FOR_{plateforme.upper()}")
    if flag is not None:
        if flag.strip() in ("0", "false", "False", "no", "off"):
            return False
        if flag.strip() in ("1", "true", "True", "yes", "on"):
            return True
    return plateforme.lower() not in PLATEFORMES_SANS_PROXY


def creer_session_humaine(ua_fixe: Optional[str] = None,
                          proxy_url: Optional[str] = None,
                          session_id: Optional[str] = None,
                          plateforme: Optional[str] = None):
    """Crée une session HTTP « humaine » : User-Agent aléatoire, headers
    réalistes, fingerprint TLS Chrome (via http_client/curl_cffi) et, si un
    proxy résidentiel est configuré ET activé pour la plateforme, une IP dédiée.

    Args:
        ua_fixe: force ce User-Agent (reproductibilité tests). Sinon aléatoire.
        proxy_url: URL proxy. Si None, lit TENDIA_PROXY_URL dans l'environnement.
        session_id: identifiant de session Bright Data. Si fourni (ex : un
            id de marché), force une IP stable pour ce marché. Si None et que
            le proxy est Bright Data, un UUID court est généré → nouvelle IP à
            chaque appel.
        plateforme: identifiant court de la plateforme cible (ex: "place",
            "dematis", "aws_achat"). Le proxy est ON par défaut ; il est
            DÉSACTIVÉ pour cette plateforme si `TENDIA_PROXY_FOR_<PLATEFORME>=0`
            (cf `_proxy_pour_plateforme`). None → proxy ON (rétro-compat).
    """
    session = http_lib.Session()
    ua = ua_fixe if ua_fixe else random.choice(USER_AGENTS_POOL)
    session.headers.update({
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "DNT": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    })
    # Proxy résidentiel anti-ban : TENDIA_PROXY_URL par défaut. Désactivé pour
    # les plateformes sans ban (place/boamp/data_gouv) via TENDIA_PROXY_FOR_*=0.
    # Sur Bright Data, on injecte un session-id pour piloter la rotation d'IP.
    if proxy_url is None and _proxy_pour_plateforme(plateforme):
        proxy_url = os.environ.get("TENDIA_PROXY_URL")
    if proxy_url:
        if "brd.superproxy.io" in proxy_url and "-session-" not in proxy_url:
            sid = _nettoyer_session_id(session_id) if session_id else ""
            if not sid:
                sid = uuid.uuid4().hex[:8]
            proxy_url = _injecter_session_id(proxy_url, sid)
        session.proxies = {"http": proxy_url, "https": proxy_url}
    return session


def attendre_humain(min_sec: float = 30, max_sec: float = 180,
                    mu: Optional[float] = None, sigma: Optional[float] = None,
                    verbose: bool = False) -> float:
    """Attendre un délai aléatoire entre min_sec et max_sec.

    Si mu et sigma fournis, distribution gaussienne (mu = moyenne, bornée par
    [min_sec, max_sec]). Sinon distribution uniforme.

    Retourne le délai effectif attendu (utile pour logs).
    """
    if mu is not None and sigma is not None:
        delay = random.gauss(mu, sigma)
        delay = max(min_sec, min(max_sec, delay))
    else:
        delay = random.uniform(min_sec, max_sec)
    if verbose:
        print(f"  [http_humain] Attente {delay:.1f} sec...")
    time.sleep(delay)
    return delay


def attendre_inter_etapes(min_sec: float = 1.5, max_sec: float = 4.0,
                          verbose: bool = False) -> float:
    """Petit délai entre les étapes d'un même workflow (1.5-4 s par défaut).

    Mime le temps qu'un humain met à lire une page avant de cliquer.
    """
    delay = random.uniform(min_sec, max_sec)
    if verbose:
        print(f"  [http_humain] +{delay:.1f}s")
    time.sleep(delay)
    return delay


def heure_actuelle_est_bureau(verbose: bool = False) -> bool:
    """Retourne True si l'heure actuelle est dans une plage de bureau crédible.

    8h00 - 19h00 du lundi au vendredi. Le week-end, retourne False.
    """
    now = datetime.now()
    if now.weekday() >= 5:  # 5 = samedi, 6 = dimanche
        if verbose:
            print(f"  [http_humain] Week-end ({now.strftime('%A')}), pas crédible.")
        return False
    if not (HEURE_DEBUT_BUREAU <= now.time() <= HEURE_FIN_BUREAU):
        if verbose:
            print(f"  [http_humain] Hors heures bureau ({now.strftime('%H:%M')}).")
        return False
    return True


def attendre_pause_cumulative(compteur: int, seuil: int = 20,
                              pause_min_sec: float = 900,
                              pause_max_sec: float = 1800,
                              verbose: bool = False) -> Optional[float]:
    """Pause longue tous les N marchés pour simuler une activité humaine.

    Tous les `seuil` marchés (par défaut 20), dort entre pause_min_sec et
    pause_max_sec (15-30 min par défaut). Retourne le délai attendu, ou None
    si pas de pause à ce compteur.
    """
    if compteur > 0 and compteur % seuil == 0:
        delay = random.uniform(pause_min_sec, pause_max_sec)
        if verbose:
            print(f"  [http_humain] Pause cumulative après {compteur} marchés : "
                  f"{delay/60:.1f} min")
        time.sleep(delay)
        return delay
    return None


def jitter(delay: float, jitter_pct: float = 0.2) -> float:
    """Ajoute du jitter (variabilité) sur un délai fixe.

    Ex : jitter(60, 0.2) -> valeur entre 48 et 72 s. Ne dort PAS (renvoie juste
    la valeur à utiliser ensuite).
    """
    j = delay * jitter_pct
    return random.uniform(delay - j, delay + j)


def ressemble_a_page_ban(html: str) -> bool:
    """Heuristique de détection de ban / page d'accueil servie à la place.

    Retourne True si le HTML reçu ressemble à une page d'accueil moderne
    (Bootstrap, liens acheteurs/fournisseurs) ou contient un message de
    blocage, au lieu de la page applicative attendue. Utilisé par les
    downloaders pour distinguer un ban d'un simple échec de parsing.
    """
    if not html:
        return False
    low = html.lower()
    return any(p in low for p in _PATTERNS_BAN)
