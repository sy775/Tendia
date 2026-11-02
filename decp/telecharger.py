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


def _params(date_debut: str, page: int, toutes_versions: bool = False) -> dict:
    """toutes_versions=True (ingestion v2) : pas de filtre modification_id/donneesActuelles
    — la version actuelle et la version initiale sont choisies par parser_v2."""
    p = {"page": str(page), "page_size": str(PAGE_SIZE)}
    if not toutes_versions:
        p["modification_id__exact"] = "0"
        p["donneesActuelles__exact"] = "True"
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


def fetch_vers_fichier(date_debut: str, chemin_gz: str, limite: int = None,
                       workers: int = WORKERS_DEFAUT, paquet_pages: int = 200,
                       verbose: bool = True) -> dict:
    """
    Variante en flux de `fetch_decp` pour les gros volumes (historique) : les pages sont
    récupérées par paquets de `paquet_pages` et écrites au fil de l'eau dans un JSONL gzip
    (1 ligne brute par enregistrement), sans tout garder en mémoire. Le fichier brut sert
    ensuite au parsing (2ᵉ passe) et aux analyses (doublons, formats) sans re-télécharger.
    Retourne {total_annonce, lignes_ecrites, pages_en_erreur}.
    """
    import gzip
    import json as _json
    import os as _os
    total = compter(date_debut)
    cible = min(total, limite) if limite else total
    n_pages = ceil(cible / PAGE_SIZE)
    if verbose:
        print(f"  [DECP] {total:,} lignes depuis {date_debut} → {n_pages} pages vers {chemin_gz}"
              .replace(",", " "), flush=True)
    _os.makedirs(_os.path.dirname(chemin_gz) or ".", exist_ok=True)
    tmp = chemin_gz + ".part"
    ecrites, erreurs, t0 = 0, [], time.time()
    with gzip.open(tmp, "wt", encoding="utf-8") as f, ThreadPoolExecutor(max_workers=workers) as ex:
        for debut in range(1, n_pages + 1, paquet_pages):
            pages = range(debut, min(debut + paquet_pages, n_pages + 1))
            futs = {ex.submit(_get, _params(date_debut, p)): p for p in pages}
            for fut in as_completed(futs):
                try:
                    for r in fut.result().get("data") or []:
                        f.write(_json.dumps(r, ensure_ascii=False) + "\n")
                        ecrites += 1
                except Exception as e:
                    erreurs.append(futs[fut])
                    print(f"  [DECP] ⚠ page {futs[fut]} : {e}", file=sys.stderr, flush=True)
            if verbose:
                print(f"  [DECP] {min(debut + paquet_pages - 1, n_pages)}/{n_pages} pages, "
                      f"{ecrites:,} lignes, {time.time()-t0:.0f}s".replace(",", " "), flush=True)
    _os.replace(tmp, chemin_gz)
    return {"total_annonce": total, "lignes_ecrites": ecrites, "pages_en_erreur": sorted(erreurs)}


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


def fetch_toutes_versions(date_debut: str, workers: int = 4, passes_relance: int = 4,
                          pause_relance_s: float = 30.0, verbose: bool = True) -> dict:
    """
    Ingestion v2 (rattrapage / hebdomadaire) : toutes les versions avec
    dateNotification ≥ date_debut, MOINS de requêtes parallèles (4) et RELANCE des pages
    en échec (HTTP 503…) en plusieurs passes espacées. Retourne
    {lignes, total_annonce, pages, pages_en_echec_final}.
    """
    total = int((_get(dict(_params(date_debut, 1, True), page_size="1")).get("meta") or {}).get("total") or 0)
    n_pages = ceil(total / PAGE_SIZE)
    if verbose:
        print(f"  [DECP v2] {total:,} lignes (toutes versions) depuis {date_debut}, {n_pages} pages"
              .replace(",", " "), flush=True)
    lignes, restantes = {}, list(range(1, n_pages + 1))
    for passe in range(passes_relance + 1):
        if not restantes:
            break
        if passe:
            if verbose:
                print(f"  [DECP v2] relance passe {passe} : {len(restantes)} pages", flush=True)
            time.sleep(pause_relance_s * passe)
        echecs = []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_get, _params(date_debut, p, True)): p for p in restantes}
            for fut in as_completed(futs):
                try:
                    lignes[futs[fut]] = fut.result().get("data") or []
                except Exception:
                    echecs.append(futs[fut])
        restantes = sorted(echecs)
    out = [r for p in sorted(lignes) for r in lignes[p]]
    if verbose:
        print(f"  [DECP v2] reçu {len(out):,} lignes, pages en échec : {restantes}"
              .replace(",", " "), flush=True)
    return {"lignes": out, "total_annonce": total, "pages": n_pages,
            "pages_en_echec_final": restantes}
