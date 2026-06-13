"""
aws_downloader.py
-----------------
Téléchargement automatique anonyme du DCE sur www.marches-publics.info
(AWS-Achat / AW Solutions / Avenue Web Systèmes / moteur ColdFusion).

Conforme à l'arrêté du 14/12/2009 — utilise l'option « Retrait anonyme »
exposée par la plateforme + résolution du captcha custom (OCR ~6 caractères)
via le service 2captcha.

Workflow (validé via HAR DevTools sur IDM=1832151) :
  1. GET dematEnt.choixDCE → établit la session ColdFusion (CFID/CFTOKEN)
  2. GET dce.avertissement → page captcha (parse strNomImage + hashVal)
  3. GET /captcha/Captcha_<strNomImage>.png → image captcha
  4. 2captcha → résolution OCR (~5-15 s)
  5. POST dce.cnxAnonyme avec captcha résolu → 302 vers verifLotsDCE
     (si 200 = captcha refusé → on retente, max TWOCAPTCHA_MAX_TENTATIVES)
  6. GET dce.verifLotsDCE → page sélection lots (parse les checkboxes)
  7. POST dce.actDCE2 avec tous les lots → HTML avec URL CDN signées
  8. Parse HTML → URL downloads.awsolutions.fr/dce/attachment/<TOKEN>
  9. Téléchargement de chaque ZIP / PDF (nom = Content-Disposition fileName)
 10. Décompression auto des ZIP imbriqués (réutilise achatpublic_downloader)

Particularité ColdFusion : PAS de cookies HTTP. La session est portée par
CFID + CFTOKEN passés en query string sur TOUTES les requêtes.

API publique :
    telecharger_dce(idm, dossier_destination, api_key_2captcha=None, ...) -> dict
    telecharger_dce_pour_marche(marche, repertoire_dce, api_key_2captcha=None) -> dict
"""

import html as html_lib
import os
import re
import time
import tempfile
from typing import Optional
from urllib.parse import urlparse, parse_qs, urljoin

try:
    import requests
except ImportError:
    raise RuntimeError("La lib 'requests' est requise. Lance : pip install requests")

import http_humain

# python-dotenv : lecture transparente de la clé 2captcha depuis .env.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # facultatif : on lira quand même os.environ si la lib est absente


URL_BASE = "https://www.marches-publics.info"
URL_PATH = "/mpiaws/index.cfm"
URL_CDN = "https://downloads.awsolutions.fr"

# Conservé pour compat (diagnostic_actdce2.py, diagnostic_etape5.py… lisent
# aws_downloader.USER_AGENT). Le workflow utilise désormais
# http_humain.creer_session_humaine() (UA tournant) pour l'anti-ban.
USER_AGENT = http_humain.USER_AGENTS_POOL[0]

# Constantes workflow (observées empiriquement, fallback si absentes du HTML)
IDS_DEFAUT = "25"
XFAOK_DEFAUT = "dce.verifLotsDCE"
TYPE_DEFAUT = "DCE"
SOUMISSION_DEFAUT = "0"     # 0 = retrait DCE (opposé à dépôt offre)

# Captcha 2captcha
TWOCAPTCHA_MAX_TENTATIVES = 3      # captchas OCR parfois faux, on retente
TWOCAPTCHA_TIMEOUT_SEC = 90        # résolution typique 5-30 s

# Téléchargement CDN
RATE_LIMIT_FICHIERS_SEC = 1        # entre 2 fichiers d'un même marché
CDN_MAX_ESSAIS = 3                 # retry téléchargement CDN (timeout/5xx)

# Labels de ressources à NE PAS télécharger (génériques, sans rapport marché)
LABELS_IGNORER = {
    "conditions d'acces a aw solutions",
    "conditions d'acces",
}


# ===========================================================================
# Exceptions
# ===========================================================================

class ErreurSolde2Captcha(Exception):
    """Levée quand 2captcha retourne ERROR_ZERO_BALANCE (plus de crédit)."""


# ===========================================================================
# Helpers purs (testables hors ligne)
# ===========================================================================

def _extraire_idm_depuis_url(url: str) -> Optional[str]:
    """Extrait l'IDM depuis n'importe quelle URL marches-publics.info.

    Decode au prealable les entites HTML (&amp; -> &) car certaines URLs
    de la base contiennent &amp; au lieu de & (bug d'ingestion BOAMP qui
    ne fait pas d'html.unescape sur les URLs).
    """
    if not url:
        return None
    url = html_lib.unescape(url)  # &amp; -> &, &lt; -> <, etc.
    try:
        qs = parse_qs(urlparse(url).query)
        v = qs.get("IDM") or qs.get("idm")
        if v and v[0].strip():
            return v[0].strip()
    except Exception:
        pass
    m = re.search(r"[?&]IDM=(\d+)", url, re.IGNORECASE)
    return m.group(1) if m else None


def _extraire_cfid_cftoken_depuis_html(html: str):
    """
    Cherche le 1er couple (CFID, CFTOKEN) dans un lien/formulaire du HTML.
    ColdFusion les pose après la 1ère requête (pas de Set-Cookie).
    Retourne (cfid, cftoken) ou (None, None).
    """
    if not html:
        return None, None
    html = html_lib.unescape(html)  # &amp; -> &
    cfid = re.search(r"[?&]CFID=(\d+)", html, re.IGNORECASE)
    cftoken = re.search(r"[?&]CFTOKEN=([0-9a-fA-F]+)", html, re.IGNORECASE)
    return (cfid.group(1) if cfid else None,
            cftoken.group(1) if cftoken else None)


def _extraire_ids_depuis_html(html: str) -> str:
    """Extrait l'IDS du marché s'il apparaît en query string, sinon IDS_DEFAUT."""
    if html:
        m = re.search(r"[?&]IDS=(\d+)", html, re.IGNORECASE)
        if m:
            return m.group(1)
    return IDS_DEFAUT


def _extraire_str_nom_image_et_hashval(html: str):
    """
    Parse le formulaire captcha pour récupérer strNomImage (timestamp ms) et
    hashVal (SHA-256, 64 hex). Retourne (strNomImage, hashVal) ou (None, None).
    """
    if not html:
        return None, None
    html = html_lib.unescape(html)  # &amp; -> &
    html = html_lib.unescape(html)  # &amp; -> &
    nom = re.search(
        r'name=["\']strNomImage["\'][^>]*value=["\']([^"\']+)["\']', html,
        re.IGNORECASE)
    if not nom:
        nom = re.search(
            r'value=["\']([^"\']+)["\'][^>]*name=["\']strNomImage["\']', html,
            re.IGNORECASE)
    hashv = re.search(
        r'name=["\']hashVal["\'][^>]*value=["\']([0-9a-fA-F]{64})["\']', html,
        re.IGNORECASE)
    if not hashv:
        hashv = re.search(
            r'value=["\']([0-9a-fA-F]{64})["\'][^>]*name=["\']hashVal["\']', html,
            re.IGNORECASE)
    return (nom.group(1) if nom else None,
            hashv.group(1) if hashv else None)


def _extraire_lots_depuis_verif_lots_dce(html: str) -> list:
    """
    Parse la page de sélection des lots → liste des values des checkboxes
    name="lots". Retourne [] si marché mono-lot (le POST actDCE2 fonctionne
    quand même sans lots).
    """
    if not html:
        return []
    html = html_lib.unescape(html)  # &amp; -> &
    lots = []
    for m in re.finditer(r'<input[^>]+>', html, re.IGNORECASE):
        inp = m.group(0)
        name_m = re.search(r'name=["\']?lots["\']?', inp, re.IGNORECASE)
        if not name_m:
            continue
        val_m = re.search(r'value=["\']([^"\']+)["\']', inp, re.IGNORECASE)
        if val_m:
            v = val_m.group(1).strip()
            if v and v not in lots:
                lots.append(v)
    return lots


def _label_normalise(label: str) -> str:
    """Normalise un libellé pour comparaison avec LABELS_IGNORER."""
    import unicodedata
    s = unicodedata.normalize("NFKD", (label or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip()


def _extraire_url_cdn_depuis_actdce2(html: str, idm: str = "",
                                       cfid: str = "", cftoken: str = "") -> list:
    """
    Parse la page de résultat actDCE2 et retourne [{label, url}] pour chaque
    ressource téléchargeable.

    - Conserve les URL CDN downloads.awsolutions.fr/dce/attachment/<TOKEN>.
    - Conserve les URL relatives AAPC (fuseaction=dce.TDoc) converties en absolu.
    - Filtre les libellés dans LABELS_IGNORER ("Conditions d'accès...").
    """
    if not html:
        return []
    html = html_lib.unescape(html)  # &amp; -> &
    resultats = []
    vus = set()
    base_mpi = URL_BASE + "/mpiaws/"

    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>', html,
                         re.IGNORECASE):
        href = (m.group(1) or "").replace("&amp;", "&").strip()
        if not href:
            continue
        low = href.lower()

        est_cdn = "downloads.awsolutions.fr/dce/attachment/" in low
        est_aapc = "fuseaction=dce.tdoc" in low
        if not (est_cdn or est_aapc):
            continue

        # Label : dernier <span class="droiteTableauTiers">…</span> avant l'ancre
        debut_bloc = html.rfind("<p", 0, m.start())
        segment = html[max(debut_bloc, 0):m.start()]
        lab_m = re.search(
            r'droiteTableauTiers["\'][^>]*>(.*?)</span>', segment,
            re.IGNORECASE | re.DOTALL)
        if not lab_m:
            # fallback : libellé porté par la colonne de gauche
            lab_m = re.search(
                r'gaucheTableau["\'][^>]*>(.*?)</label>', segment,
                re.IGNORECASE | re.DOTALL)
        label = re.sub(r"<[^>]+>", " ", lab_m.group(1)).strip() if lab_m else ""

        if _label_normalise(label) in LABELS_IGNORER:
            continue

        if est_cdn:
            url_abs = href if href.startswith("http") else urljoin(base_mpi, href)
        else:  # AAPC relatif
            url_abs = href if href.startswith("http") else urljoin(base_mpi, href)

        if url_abs in vus:
            continue
        vus.add(url_abs)
        resultats.append({"label": label or "ressource", "url": url_abs})

    return resultats


def _nom_fichier_depuis_headers(headers: dict, url_fallback: str = "",
                                 defaut: str = "piece.bin") -> str:
    """Déduit le nom de fichier depuis Content-Disposition (fileName=...)."""
    cd = ""
    for cle in ("Content-Disposition", "content-disposition"):
        if headers and headers.get(cle):
            cd = headers.get(cle)
            break
    m = re.search(r'file[nN]ame\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd or "")
    if m:
        nom = m.group(1).strip().strip('"')
        if nom:
            return _sanitiser_nom(nom)
    if url_fallback:
        base = os.path.basename(urlparse(url_fallback).path)
        if base and "." in base:
            return _sanitiser_nom(base)
    return _sanitiser_nom(defaut)


def _sanitiser_nom(nom: str) -> str:
    """Nettoie un nom de fichier pour le système de fichiers."""
    nom = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", nom or "")
    nom = nom.strip(" .")
    return nom[:200] or "document.bin"


# ===========================================================================
# 2captcha
# ===========================================================================

def _resoudre_captcha_2captcha(image_bytes: bytes, api_key: str,
                                 verbose: bool = True) -> Optional[str]:
    """
    Envoie l'image captcha à 2captcha et retourne la solution texte (~6 chars).
    Lève ErreurSolde2Captcha si le compte n'a plus de crédit.
    Retourne None sur autre échec (réseau / timeout / illisible).
    """
    if not image_bytes:
        return None
    if not api_key:
        if verbose:
            print("        [2captcha] clé API absente (TWOCAPTCHA_API_KEY)")
        return None

    try:
        from twocaptcha import TwoCaptcha
    except ImportError:
        if verbose:
            print("        [2captcha] lib absente : pip install 2captcha-python")
        return None

    # La lib accepte un chemin de fichier ; on écrit l'image dans un temporaire.
    chemin_tmp = None
    try:
        fd, chemin_tmp = tempfile.mkstemp(suffix=".png", prefix="aws_captcha_")
        with os.fdopen(fd, "wb") as f:
            f.write(image_bytes)

        solver = TwoCaptcha(api_key, defaultTimeout=TWOCAPTCHA_TIMEOUT_SEC,
                            pollingInterval=3)
        resultat = solver.normal(chemin_tmp)
        code = (resultat or {}).get("code")
        if verbose and code:
            print(f"        [2captcha] résolu : {code!r}")
        return code or None
    except Exception as e:
        msg = str(e)
        if "ZERO_BALANCE" in msg.upper():
            raise ErreurSolde2Captcha(msg)
        if verbose:
            print(f"        [2captcha] échec : {type(e).__name__}: {msg[:120]}")
        return None
    finally:
        if chemin_tmp and os.path.isfile(chemin_tmp):
            try:
                os.remove(chemin_tmp)
            except OSError:
                pass


# ===========================================================================
# Décompression : réutilise l'implémentation achatpublic (DRY)
# ===========================================================================

def _decompresser_zip_imbrique(chemin_zip: str, dossier_dest: str,
                                 verbose: bool = False) -> dict:
    """Délègue à achatpublic_downloader._decompresser_zip_imbrique (DRY)."""
    import achatpublic_downloader as _ap
    return _ap._decompresser_zip_imbrique(chemin_zip, dossier_dest, verbose=verbose)


# ===========================================================================
# Workflow réseau
# ===========================================================================

def _construire_url(fuseaction: str, **params) -> str:
    """Construit une URL index.cfm?fuseaction=... avec les params query string."""
    qs = "&".join(f"{k}={v}" for k, v in params.items() if v not in (None, ""))
    url = f"{URL_BASE}{URL_PATH}?fuseaction={fuseaction}"
    return f"{url}&{qs}" if qs else url


def telecharger_dce(
    idm: str,
    dossier_destination: str,
    api_key_2captcha: Optional[str] = None,
    verbose: bool = True,
    timeout: int = 180,
    decompresser: bool = True,
) -> dict:
    """
    Workflow 7 étapes complet de retrait anonyme du DCE AWS-Achat.

    Args:
        idm: identifiant marché AWS-Achat (ex "1832151")
        dossier_destination: dossier où placer tous les fichiers du DCE
        api_key_2captcha: clé API 2captcha (sinon lue depuis TWOCAPTCHA_API_KEY)
        verbose, timeout: idem atexo/achatpublic
        decompresser: True pour décompresser auto les ZIP imbriqués

    Returns:
        {ok, fichiers_telecharges, taille_octets_total, dossier, erreur,
         duree_secondes, nb_captcha_resolus, etape_erreur,
         nb_zip_internes_decompressed}
    """
    debut = time.time()
    out = {"ok": False, "fichiers_telecharges": [], "taille_octets_total": 0,
           "dossier": dossier_destination, "erreur": None, "duree_secondes": 0.0,
           "nb_captcha_resolus": 0, "etape_erreur": None,
           "nb_zip_internes_decompressed": 0}

    if not idm:
        out["erreur"] = "IDM manquant"
        out["etape_erreur"] = "session"
        return out

    api_key = api_key_2captcha or os.environ.get("TWOCAPTCHA_API_KEY")
    if not api_key:
        out["erreur"] = "Clé 2captcha absente (api_key_2captcha / TWOCAPTCHA_API_KEY)"
        out["etape_erreur"] = "captcha"
        return out

    # Session « humaine » : User-Agent tournant + headers réalistes (anti-ban).
    session = http_humain.creer_session_humaine()

    if verbose:
        print(f"  [AWS-Achat] DCE IDM={idm}")

    # ----- Étape 1 : GET choixDCE → session ColdFusion (CFID/CFTOKEN) -----
    try:
        if verbose:
            print("    [1/7] GET choixDCE (session ColdFusion)...")
        url1 = _construire_url("dematEnt.choixDCE", IDM=idm, XFAOK=XFAOK_DEFAUT)
        r1 = session.get(url1, timeout=timeout, allow_redirects=True)
        if r1.status_code != 200:
            out.update(erreur=f"GET choixDCE HTTP {r1.status_code}",
                       etape_erreur="session")
            return out
        html1 = r1.text
    except Exception as e:
        out.update(erreur=f"GET choixDCE : {type(e).__name__}: {e}",
                   etape_erreur="session")
        return out

    cfid, cftoken = _extraire_cfid_cftoken_depuis_html(html1)
    # Fallback : CFID/CFTOKEN parfois portés par l'URL finale après redirect.
    if not cfid or not cftoken:
        c2, t2 = _extraire_cfid_cftoken_depuis_html(r1.url)
        cfid = cfid or c2
        cftoken = cftoken or t2
    if not cfid or not cftoken:
        if http_humain.ressemble_a_page_ban(html1):
            out.update(erreur="Suspicion ban IP (page d'accueil servie au lieu "
                              "de la page DCE)", etape_erreur="ban_detecte")
        else:
            out.update(erreur="CFID/CFTOKEN introuvables (page inattendue / marché clos)",
                       etape_erreur="session")
        return out
    ids = _extraire_ids_depuis_html(html1)
    if verbose:
        print(f"        CFID={cfid} CFTOKEN={cftoken} IDS={ids}")

    # ----- Étapes 2-5 : page captcha → résolution → POST cnxAnonyme -----
    location_lots = None
    for tentative in range(1, TWOCAPTCHA_MAX_TENTATIVES + 1):
        # Délai « humain » : temps de lire la page avant de demander le captcha
        # (3-6 s). En cas de retry, espace aussi les re-soumissions.
        http_humain.attendre_inter_etapes(3, 6, verbose=verbose)
        # Étape 2 : page captcha
        try:
            if verbose:
                print(f"    [2/7] GET dce.avertissement (captcha) "
                      f"[tentative {tentative}/{TWOCAPTCHA_MAX_TENTATIVES}]...")
            url2 = _construire_url("dce.avertissement", IDM=idm, type=TYPE_DEFAUT,
                                   XFAOK=XFAOK_DEFAUT, IDS=ids,
                                   CFID=cfid, CFTOKEN=cftoken)
            r2 = session.get(url2, timeout=timeout, allow_redirects=True)
            if r2.status_code == 404:
                out.update(erreur="dce.avertissement 404 (marché clos suspecté)",
                           etape_erreur="captcha")
                return out
            if r2.status_code != 200:
                out.update(erreur=f"GET avertissement HTTP {r2.status_code}",
                           etape_erreur="captcha")
                return out
            html2 = r2.text
        except Exception as e:
            out.update(erreur=f"GET avertissement : {type(e).__name__}: {e}",
                       etape_erreur="captcha")
            return out

        str_nom_image, hash_val = _extraire_str_nom_image_et_hashval(html2)
        if not str_nom_image or not hash_val:
            if http_humain.ressemble_a_page_ban(html2):
                out.update(erreur="Suspicion ban IP (page d'accueil HTML5 servie "
                                  "au lieu de la page captcha)",
                           etape_erreur="ban_detecte")
            else:
                out.update(erreur="strNomImage/hashVal introuvables sur la page captcha",
                           etape_erreur="captcha")
            return out

        # Étape 3 : image captcha
        try:
            if verbose:
                print("    [3/7] GET image captcha...")
            url_img = f"{URL_BASE}/captcha/Captcha_{str_nom_image}.png"
            r3 = session.get(url_img, timeout=timeout)
            if r3.status_code != 200 or not r3.content:
                out.update(erreur=f"GET captcha image HTTP {r3.status_code}",
                           etape_erreur="captcha")
                return out
            image_bytes = r3.content
        except Exception as e:
            out.update(erreur=f"GET captcha image : {type(e).__name__}: {e}",
                       etape_erreur="captcha")
            return out

        # Étape 4 : résolution 2captcha
        if verbose:
            print("    [4/7] Résolution captcha (2captcha)...")
        try:
            solution = _resoudre_captcha_2captcha(image_bytes, api_key, verbose=verbose)
        except ErreurSolde2Captcha as e:
            out.update(erreur=f"2captcha solde épuisé (ZERO_BALANCE) : {e}",
                       etape_erreur="captcha")
            out["solde_2captcha_epuise"] = True
            return out
        if not solution:
            if verbose:
                print("        captcha non résolu, nouvelle tentative...")
            continue
        out["nb_captcha_resolus"] += 1

        # Étape 5 : POST cnxAnonyme (302 = succès, 200 = captcha refusé)
        try:
            if verbose:
                print("    [5/7] POST dce.cnxAnonyme...")
            url5 = _construire_url("dce.cnxAnonyme", IDM=idm, IDS=ids,
                                   CFID=cfid, CFTOKEN=cftoken)
            payload5 = {
                "type": TYPE_DEFAUT,
                "XFAOK": XFAOK_DEFAUT,
                "strNomImage": str_nom_image,
                "hashVal": hash_val,
                "captchaVal": solution,
            }
            r5 = session.post(url5, data=payload5, timeout=timeout,
                              allow_redirects=False,
                              headers={"Origin": URL_BASE, "Referer": url2,
                                       "Content-Type": "application/x-www-form-urlencoded"})
        except Exception as e:
            out.update(erreur=f"POST cnxAnonyme : {type(e).__name__}: {e}",
                       etape_erreur="captcha")
            return out

        if r5.status_code in (301, 302, 303, 307):
            location_lots = r5.headers.get("Location") or ""
            # PATCH cfid_refresh : ColdFusion régénère CFID/CFTOKEN après le
            # POST cnxAnonyme. Les anciens tokens deviennent invalides.
            # On extrait les nouveaux depuis le Location header et on les
            # propage aux étapes 6 et 7.
            _location_decode = html_lib.unescape(location_lots)
            _new_cfid = re.search(r"[?&]CFID=(\d+)", _location_decode, re.IGNORECASE)
            _new_cftoken = re.search(r"[?&]CFTOKEN=([0-9a-fA-F\-]+)",
                                      _location_decode, re.IGNORECASE)
            if _new_cfid and _new_cftoken:
                cfid = _new_cfid.group(1)
                cftoken = _new_cftoken.group(1)
                if verbose:
                    print(f"        → 302 captcha accepté (CFID régénéré : {cfid})")
            elif verbose:
                print("        → 302 captcha accepté")
            break
        # 200 = captcha refusé : on boucle (nouveau captcha)
        if verbose:
            print(f"        captcha refusé (HTTP {r5.status_code}), on retente")

    if location_lots is None:
        out.update(erreur=f"Captcha refusé {TWOCAPTCHA_MAX_TENTATIVES} tentatives",
                   etape_erreur="captcha")
        return out

    # Délai « humain » : suit le redirect vers la page lots (2-4 s).
    http_humain.attendre_inter_etapes(2, 4, verbose=verbose)

    # ----- Étape 6 : GET verifLotsDCE (sélection lots) -----
    try:
        if verbose:
            print("    [6/7] GET dce.verifLotsDCE...")
        if location_lots:
            url6 = urljoin(URL_BASE + URL_PATH, location_lots.replace("&amp;", "&"))
        else:
            url6 = _construire_url("dce.verifLotsDCE", IDM=idm, IDS=ids,
                                   CFID=cfid, CFTOKEN=cftoken)
        r6 = session.get(url6, timeout=timeout, allow_redirects=True)
        if r6.status_code != 200:
            out.update(erreur=f"GET verifLotsDCE HTTP {r6.status_code}",
                       etape_erreur="lots")
            return out
        html6 = r6.text
    except Exception as e:
        out.update(erreur=f"GET verifLotsDCE : {type(e).__name__}: {e}",
                   etape_erreur="lots")
        return out

    lots = _extraire_lots_depuis_verif_lots_dce(html6)
    if verbose:
        print(f"        lots détectés : {lots or '(aucun, mono-lot)'}")

    # Délai « humain » : temps de cocher « tout sélectionner » avant de valider
    # (4-8 s).
    http_humain.attendre_inter_etapes(4, 8, verbose=verbose)

    # ----- Étape 7 : POST actDCE2 (validation tous les lots) -----
    try:
        if verbose:
            print("    [7/7] POST dce.actDCE2...")
        url7 = _construire_url("dce.actDCE2", CFID=cfid, CFTOKEN=cftoken)
        # PATCH lots_mono : Body avec lots=N par lot, OU lots=0 si mono-lot.
        # En mono-lot (verifLotsDCE n'a pas de checkboxes), AWS-Achat exige
        # explicitement `lots=0` dans le POST sinon retourne "ANOMALIE 12164096".
        champs = [("IDM", idm), ("Soumission", SOUMISSION_DEFAUT), ("selectAll", "")]
        if lots:
            for lot in lots:
                champs.append(("lots", lot))
        else:
            champs.append(("lots", "0"))  # mono-lot
        r7 = session.post(url7, data=champs, timeout=timeout, allow_redirects=True,
                          headers={"Origin": URL_BASE, "Referer": url6,
                                   "Content-Type": "application/x-www-form-urlencoded"})
        if r7.status_code != 200:
            out.update(erreur=f"POST actDCE2 HTTP {r7.status_code}",
                       etape_erreur="lots")
            return out
        html7 = r7.text
    except Exception as e:
        out.update(erreur=f"POST actDCE2 : {type(e).__name__}: {e}",
                   etape_erreur="lots")
        return out

    # ----- Étape 8 : parse URL CDN -----
    ressources = _extraire_url_cdn_depuis_actdce2(html7, idm, cfid, cftoken)
    if not ressources:
        out.update(erreur="Aucune URL CDN trouvée dans la page actDCE2",
                   etape_erreur="cdn")
        return out
    if verbose:
        print(f"        {len(ressources)} ressource(s) à télécharger")

    # ----- Étape 9 : téléchargement des fichiers -----
    os.makedirs(dossier_destination, exist_ok=True)
    fichiers = []
    taille_totale = 0
    erreurs_dl = []
    for i, res in enumerate(ressources, 1):
        url_f = res["url"]
        ok_f, chemin_f, taille_f, err_f = _telecharger_fichier_cdn(
            session, url_f, dossier_destination, timeout=timeout, verbose=verbose)
        if ok_f:
            fichiers.append(chemin_f)
            taille_totale += taille_f
            if verbose:
                print(f"        ✓ [{i}/{len(ressources)}] "
                      f"{os.path.basename(chemin_f)} ({taille_f:,} o)")
        else:
            erreurs_dl.append(f"{res['label']}: {err_f}")
            if verbose:
                print(f"        ✗ [{i}/{len(ressources)}] {res['label']} : {err_f}")
        if i < len(ressources):
            time.sleep(RATE_LIMIT_FICHIERS_SEC)

    if not fichiers:
        out.update(erreur="Aucun fichier téléchargé : " + "; ".join(erreurs_dl[:3]),
                   etape_erreur="cdn")
        out["duree_secondes"] = round(time.time() - debut, 2)
        return out

    # ----- Étape 10 : décompression auto des ZIP imbriqués -----
    if decompresser:
        for chemin_f in list(fichiers):
            if chemin_f.lower().endswith(".zip"):
                try:
                    res_dec = _decompresser_zip_imbrique(
                        chemin_f, dossier_destination, verbose=verbose)
                    out["nb_zip_internes_decompressed"] += res_dec.get(
                        "nb_zip_internes_decompressed", 0)
                except Exception as e:
                    if verbose:
                        print(f"        décompression {os.path.basename(chemin_f)} "
                              f"échouée (non bloquant) : {e}")

    out.update(ok=True, fichiers_telecharges=fichiers,
               taille_octets_total=taille_totale)
    if erreurs_dl:
        out["erreurs_non_critiques"] = erreurs_dl[:5]
    out["duree_secondes"] = round(time.time() - debut, 2)
    if verbose:
        print(f"  [AWS-Achat] ✅ {len(fichiers)} fichier(s), "
              f"{taille_totale:,} o, {out['duree_secondes']}s")
    return out


def _telecharger_fichier_cdn(session, url: str, dossier: str,
                              timeout: int = 180, verbose: bool = False):
    """
    Télécharge un fichier CDN avec retry (timeout/5xx). Nom = Content-Disposition.
    Retourne (ok, chemin, taille_octets, erreur).
    """
    derniere = ""
    for essai in range(1, CDN_MAX_ESSAIS + 1):
        try:
            r = session.get(url, timeout=timeout, stream=True, allow_redirects=True)
            code = r.status_code
            if code >= 500:
                derniere = f"HTTP {code}"
                time.sleep(2 * essai)
                continue
            if code != 200:
                return False, None, 0, f"HTTP {code}"

            nom = _nom_fichier_depuis_headers(r.headers, url, defaut="piece.bin")
            chemin = os.path.join(dossier, nom)
            # Évite l'écrasement entre ressources homonymes
            if os.path.exists(chemin):
                base, ext = os.path.splitext(nom)
                chemin = os.path.join(dossier, f"{base}_{essai}{ext}")
            taille = 0
            with open(chemin, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        taille += len(chunk)
            if taille == 0:
                derniere = "0 octet"
                time.sleep(2)
                continue
            return True, chemin, taille, None
        except Exception as e:
            derniere = f"{type(e).__name__}: {e}"
            time.sleep(2 * essai)
    return False, None, 0, derniere or "échec"


def telecharger_dce_pour_marche(
    marche: dict,
    repertoire_dce: str,
    api_key_2captcha: Optional[str] = None,
    verbose: bool = True,
) -> dict:
    """
    Wrapper : extrait l'IDM depuis marche['url_dce'] et appelle telecharger_dce
    dans <repertoire_dce>/<id_marche>/. Retourne le contrat standard enrichi
    (ok, chemin, taille_octets, erreur, duree_secondes, id_marche, skip, ...).
    """
    id_marche = marche.get("id", "?")
    url_dce = marche.get("url_dce")

    out = {"id_marche": id_marche, "ok": False, "skip": False,
           "erreur": None, "chemin": None, "duree_secondes": 0.0,
           "taille_octets": 0}

    if not url_dce:
        out["erreur"] = "Pas d'URL DCE résolue pour ce marché"
        return out

    idm = _extraire_idm_depuis_url(url_dce)
    if not idm:
        out["erreur"] = f"IDM introuvable dans l'URL : {url_dce[:100]}"
        return out

    dossier_cible = os.path.join(repertoire_dce, id_marche)

    # Idempotence : skip si des fichiers utiles sont déjà présents.
    if os.path.isdir(dossier_cible):
        fichiers_existants = [
            f for f in os.listdir(dossier_cible)
            if os.path.isfile(os.path.join(dossier_cible, f))
            and not f.lower().endswith((".bak", ".tmp"))
        ]
        if fichiers_existants:
            out.update(ok=True, skip=True, chemin=dossier_cible)
            if verbose:
                print(f"  [AWS-Achat] Skip {id_marche} ({len(fichiers_existants)} "
                      f"fichiers déjà présents)")
            return out

    if verbose:
        print(f"  [AWS-Achat] {id_marche} → IDM={idm}")

    res = telecharger_dce(idm, dossier_cible, api_key_2captcha=api_key_2captcha,
                          verbose=verbose)
    out.update(res)
    out["id_marche"] = id_marche
    out["chemin"] = dossier_cible
    out["taille_octets"] = res.get("taille_octets_total", 0)
    return out


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage : python aws_downloader.py <IDM> [dossier_destination]")
        sys.exit(1)
    idm_arg = sys.argv[1]
    dossier = sys.argv[2] if len(sys.argv) > 2 else f"data/test_aws_{idm_arg}"
    print(f"Test téléchargement DCE AWS-Achat :")
    print(f"  IDM         = {idm_arg}")
    print(f"  destination = {dossier}")
    print()
    res = telecharger_dce(idm_arg, dossier, verbose=True)
    print()
    print("Résultat :", {k: v for k, v in res.items() if k != "fichiers_telecharges"})
    for f in res.get("fichiers_telecharges", []):
        print("  -", f)
