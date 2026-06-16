"""
decp/telecharger.py — acquisition DECP consolidée (Stratégie A validée).

Wrapper léger au-dessus de l'API tabulaire data.gouv.fr (même ressource que
`connecteurs/decp_consolidee.py`). Pagination parallèle (page_size plafonné à 100
par l'API) avec filtres systématiques `modification_id=0` + `donneesActuelles=true`.

data.gouv.fr est en accès DIRECT (pas de proxy). Truststore injecté (SSL Windows).
Repli Parquet (Stratégie B) non implémenté ici : à activer si l'API montre des
limites non récupérables (décision technique au runtime).
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from math import ceil

import truststore
truststore.inject_into_ssl()
import requests

from connecteurs.decp_consolidee import RESSOURCE_ID, URL_BASE  # réutilisation

PAGE_SIZE = 100          # plafond dur de l'API tabulaire
WORKERS_DEFAUT = 12
TIMEOUT = 60
RETRIES = 3

_session = requests.Session()
_session.headers.update({
    "User-Agent": "Tendia/0.1 (veille marches publics; sprint DECP)",
    "Accept": "application/json",
})


def _veille(jour: str) -> str:
    return (date.fromisoformat(jour) - timedelta(days=1)).isoformat()


def _params(date_debut: str, page: int) -> dict:
    p = {
        "modification_id__exact": "0",
        "donneesActuelles__exact": "True",
        "page": str(page),
        "page_size": str(PAGE_SIZE),
    }
    if date_debut:
        p["dateNotification__greater"] = _veille(date_debut)
    return p


def _get(params: dict) -> dict:
    derniere = None
    for tentative in range(1, RETRIES + 1):
        try:
            r = _session.get(URL_BASE, params=params, timeout=TIMEOUT)
            if r.status_code >= 500:
                derniere = RuntimeError(f"HTTP {r.status_code}")
                time.sleep(1.0 * tentative)
                continue
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.Timeout) as e:
            derniere = e
            time.sleep(1.0 * tentative)
    raise RuntimeError(f"Échec API après {RETRIES} tentatives : {derniere}")


def compter(date_debut: str) -> int:
    """Nombre de lignes correspondant au filtre (meta.total)."""
    rep = _get(dict(_params(date_debut, 1), page_size="1"))
    return int((rep.get("meta") or {}).get("total") or 0)


def fetch_decp(date_debut: str, date_fin: str = None, limite: int = None,
               workers: int = WORKERS_DEFAUT, verbose: bool = True) -> list:
    """
    Récupère les lignes DECP brutes avec dateNotification ≥ date_debut (ISO),
    filtrées mod=0 + actuelles. `date_fin` (exclusif) filtré localement (l'API
    ignore __less sur la date). `limite` borne le nombre de lignes (test progressif).

    Retourne une liste de dicts bruts (à passer au parser).
    """
    total = compter(date_debut)
    cible = min(total, limite) if limite else total
    n_pages = ceil(cible / PAGE_SIZE)
    if verbose:
        print(f"  [DECP] total disponible depuis {date_debut} : {total:,} lignes"
              .replace(",", " "))
        print(f"  [DECP] à récupérer : {cible:,} ({n_pages} pages × {PAGE_SIZE}, "
              f"{workers} workers)".replace(",", " "))

    out = []
    t0 = time.time()
    erreurs = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_get, _params(date_debut, p)): p
                for p in range(1, n_pages + 1)}
        faits = 0
        for fut in as_completed(futs):
            faits += 1
            try:
                out.extend(fut.result().get("data") or [])
            except Exception as e:
                erreurs += 1
                if verbose:
                    print(f"  [DECP] ⚠ page {futs[fut]} : {e}", file=sys.stderr)
            if verbose and faits % 100 == 0:
                print(f"  [DECP] {faits}/{n_pages} pages  "
                      f"({len(out):,} lignes, {time.time()-t0:.0f}s)".replace(",", " "))

    if date_fin:
        out = [r for r in out if str(r.get("dateNotification") or "")[:10] < date_fin]
    if limite:
        out = out[:limite]
    if verbose:
        print(f"  [DECP] reçu {len(out):,} lignes en {time.time()-t0:.0f}s "
              f"({erreurs} pages en erreur)".replace(",", " "))
    return out
