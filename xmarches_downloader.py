"""
xmarches_downloader.py
----------------------
Téléchargement anonyme du DCE depuis xmarches.fr (moteur custom PHP, distinct
d'Atexo/Dematis/AWS).

Flux (reverse-engineeré via HAR `HAR/www.xmarches.fr*.har`) :
  1. GET  /entreprise/detailConsultation.php?key=<KEY>   (cookies de session)
  2. GET  /entreprise/redirect.php?dl&key=<KEY>&us=&id=0&prov=XMAR&telequoi=DCE&rectifid=
          → 302/redirige vers /entreprise/saisir-captcha.php?url=...
  3. Parse la page captcha : champ caché `SECU` (token) + image
          /captcha/captcha.php?id=<HASH>
  4. Résout le captcha via 2captcha (réutilise aws_downloader).
  5. POST /entreprise/telec_aac.php  body :
          email=&mdp=&SECU=<token>&TELEQUOI=DCE&captcha=<solution>
  6. Le DCE est servi en GET /entreprise/telec_aac.php?SECU=<token validé>
          → application/octet-stream, attachment filename=<...>_DCE_<id>.zip

Interface :
    est_url_xmarches(url) -> bool
    telecharger_dce(url_dce, dossier_destination, api_key_2captcha=None, ...) -> dict
    telecharger_dce_pour_marche(marche, repertoire_dce, api_key_2captcha=None) -> dict
"""
import os
import re
import sys
import time
import zipfile
from urllib.parse import urljoin, urlparse, parse_qs

import requests

try:
    import truststore as _truststore
    _truststore.inject_into_ssl()
except Exception:
    pass

from aws_downloader import _resoudre_captcha_2captcha

HOST_XMARCHES = "xmarches.fr"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
CAPTCHA_MAX_ESSAIS = 3


def est_url_xmarches(url: str) -> bool:
    return HOST_XMARCHES in (url or "").lower()


def _extraire_key(url: str):
    qs = parse_qs(urlparse(url or "").query)
    return (qs.get("key") or [None])[0]


def telecharger_dce(url_dce: str, dossier_destination: str,
                    api_key_2captcha: str = None, verbose: bool = True,
                    timeout: int = 90) -> dict:
    out = {"ok": False, "fichiers_telecharges": [], "taille_octets_total": 0,
           "erreur": None, "nb_captcha_resolus": 0}
    key = _extraire_key(url_dce)
    if not key:
        out["erreur"] = "key introuvable dans l'URL xmarches"
        return out
    base = f"{urlparse(url_dce).scheme}://{urlparse(url_dce).netloc}"
    api_key = api_key_2captcha or os.environ.get("TWOCAPTCHA_API_KEY")
    if not api_key:
        out["erreur"] = "clé 2captcha absente (TWOCAPTCHA_API_KEY)"
        return out

    s = requests.Session()
    s.headers.update({"User-Agent": _UA, "Accept-Language": "fr-FR,fr;q=0.9"})

    try:
        # 1) page détail (cookies)
        s.get(url_dce, timeout=timeout)
        # 2) redirect download DCE → page captcha
        url_redir = (f"{base}/entreprise/redirect.php?dl&key={key}"
                     f"&us=&id=0&prov=XMAR&telequoi=DCE&rectifid=")
        rc = s.get(url_redir, timeout=timeout, allow_redirects=True)
        html = rc.text
    except requests.RequestException as e:
        out["erreur"] = f"réseau (détail/redirect) : {type(e).__name__}: {e}"
        return out

    if "saisir-captcha" not in rc.url and "captcha" not in html.lower():
        # peut-être déjà le fichier (rare) — sinon échec
        if "attachment" in (rc.headers.get("content-disposition") or "").lower():
            return _ecrire_zip(rc, dossier_destination, out, verbose)
        out["erreur"] = "page captcha non atteinte"
        return out

    for essai in range(1, CAPTCHA_MAX_ESSAIS + 1):
        # 3) parse SECU + image
        m_secu = re.search(r'name=["\']SECU["\'][^>]*value=["\']([^"\']+)', html, re.I)
        m_img = re.search(r'src=["\']([^"\']*captcha\.php[^"\']*)', html, re.I)
        if not (m_secu and m_img):
            out["erreur"] = "SECU/image captcha introuvables sur la page"
            return out
        secu = m_secu.group(1)
        url_img = urljoin(rc.url, m_img.group(1).replace("&amp;", "&"))
        try:
            img = s.get(url_img, timeout=timeout).content
        except requests.RequestException as e:
            out["erreur"] = f"réseau (image captcha) : {e}"
            return out
        if verbose:
            print(f"    [xmarches] captcha essai {essai}/{CAPTCHA_MAX_ESSAIS} "
                  f"(image {len(img)}o)")
        solution = _resoudre_captcha_2captcha(img, api_key, verbose=verbose)
        out["nb_captcha_resolus"] += 1
        if not solution:
            continue

        # 5) Soumission du captcha : GET telec_aac.php?SECU&TELEQUOI=DCE&captcha
        #    (le formulaire est en méthode GET ; champs SECU + TELEQUOI + captcha,
        #     PAS de email/mdp). Réponse = directement le zip (attachment).
        try:
            rg = s.get(f"{base}/entreprise/telec_aac.php",
                       params={"SECU": secu, "TELEQUOI": "DCE", "captcha": solution},
                       timeout=timeout, allow_redirects=True,
                       headers={"Referer": rc.url})
        except requests.RequestException as e:
            out["erreur"] = f"réseau (GET fichier) : {e}"
            return out
        cdg = (rg.headers.get("content-disposition") or "").lower()
        if "attachment" in cdg:
            return _ecrire_zip(rg, dossier_destination, out, verbose)

        # captcha probablement refusé → on recharge la page captcha et on retente
        if verbose:
            print("    [xmarches] captcha refusé, nouvelle tentative")
        try:
            rc = s.get(url_redir, timeout=timeout, allow_redirects=True)
            html = rc.text
        except requests.RequestException:
            break

    out["erreur"] = f"captcha non résolu après {CAPTCHA_MAX_ESSAIS} tentatives"
    return out


def _ecrire_zip(resp, dossier_destination: str, out: dict, verbose: bool) -> dict:
    os.makedirs(dossier_destination, exist_ok=True)
    cd = resp.headers.get("content-disposition") or ""
    m = re.search(r'filename="?([^"\r\n;]+)', cd)
    nom = (m.group(1).strip() if m else "dce_xmarches.zip")
    chemin = os.path.join(dossier_destination, nom)
    taille = 0
    with open(chemin, "wb") as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)
            taille += len(chunk)
    out["taille_octets_total"] = taille
    if taille < 512:
        out["erreur"] = f"fichier trop petit ({taille}o) — probablement pas le DCE"
        return out
    fichiers = [chemin]
    # décompression si zip
    if zipfile.is_zipfile(chemin):
        try:
            with zipfile.ZipFile(chemin) as z:
                z.extractall(dossier_destination)
                fichiers = [os.path.join(dossier_destination, n)
                            for n in z.namelist() if not n.endswith("/")]
        except Exception:
            pass
    out.update(ok=True, fichiers_telecharges=fichiers)
    if verbose:
        print(f"    [xmarches] ✅ {nom} ({taille/1000:.0f}ko, {len(fichiers)} pièces)")
    return out


def telecharger_dce_pour_marche(marche: dict, repertoire_dce: str,
                                api_key_2captcha: str = None,
                                verbose: bool = True) -> dict:
    id_marche = marche.get("id", "?")
    url_dce = marche.get("url_dce") or ""
    dossier = os.path.join(repertoire_dce, id_marche)
    res = telecharger_dce(url_dce, dossier, api_key_2captcha=api_key_2captcha,
                          verbose=verbose)
    res["id_marche"] = id_marche
    res["chemin"] = dossier
    res["taille_octets"] = res.get("taille_octets_total", 0)
    res["nb_fichiers"] = len(res.get("fichiers_telecharges") or [])
    return res


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    u = sys.argv[1] if len(sys.argv) > 1 else \
        "https://www.xmarches.fr/entreprise/detailConsultation.php?key=40675"
    d = sys.argv[2] if len(sys.argv) > 2 else "data/test_xmarches"
    print(telecharger_dce(u, d, verbose=True))
