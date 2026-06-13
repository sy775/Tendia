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
import random
import time
from datetime import datetime, time as dtime
from typing import Optional

import requests

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


def creer_session_humaine(ua_fixe: Optional[str] = None) -> requests.Session:
    """Crée une requests.Session avec User-Agent aléatoire et headers réalistes.

    Args:
        ua_fixe: si fourni, force ce User-Agent (reproductibilité tests).
                 Sinon tirage aléatoire dans USER_AGENTS_POOL.
    """
    session = requests.Session()
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
