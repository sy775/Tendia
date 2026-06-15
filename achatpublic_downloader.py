"""
achatpublic_downloader.py
-------------------------
Téléchargement automatique anonyme du DCE sur achatpublic.com, conforme à
l'arrêté du 14/12/2009. Avec décompression automatique du ZIP imbriqué.

Workflow (validé via HAR DevTools) :
  1. GET la page détail consultation (ent_detail.do?PCSLID=...)
     → renvoie un HTML contenant submitFormeDownload('<dceId>') et
       getDceDetails('<dceId>', '<cycNum>') dans des onclick JS.
  2. POST telechargerDCE.action?PCSLID=...&cycNum=<n> avec body URL-encoded
     {PCSLID, cycNum, dceId, nomEntiteContact='', nomPointContact='',
      mailPointContact=''}
     → renvoie un ZIP achatpublic en streaming (Content-Type: application/zip).
  3. Le ZIP achatpublic contient typiquement un ZIP imbriqué `DCE/DCE.zip`
     contenant les vraies pièces. On le décompresse automatiquement pour que
     qualifier_dce voie le contenu réel.

Pas de captcha. Pas d'auth. Pas de session/cookie. Que `requests` + `zipfile`.
"""
import os
import re
import time
import zipfile
from typing import Optional
from urllib.parse import urlparse, parse_qs

import http_client as http_lib   # backend curl_cffi (TLS Chrome) ou requests
import http_humain
import tendia_logs


URL_BASE_ACHATPUBLIC = "https://www.achatpublic.com"
URL_DETAIL_PATH = "/sdm/ent/gen/ent_detail.do"
URL_DOWNLOAD_PATH = "/sdm/ent2/gen/telechargerDCE.action"

# Conservé pour compat. Le workflow utilise http_humain.creer_session_humaine().
USER_AGENT = http_humain.USER_AGENTS_POOL[0]


def _construire_url_detail(pcslid: str) -> str:
    return f"{URL_BASE_ACHATPUBLIC}{URL_DETAIL_PATH}?PCSLID={pcslid}"


def _construire_url_download(pcslid: str, cyc_num: str = "0") -> str:
    return f"{URL_BASE_ACHATPUBLIC}{URL_DOWNLOAD_PATH}?PCSLID={pcslid}&cycNum={cyc_num}"


def _extraire_pcslid_depuis_url(url: str) -> Optional[str]:
    """Extrait le PCSLID depuis une URL achatpublic."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        v = qs.get("PCSLID") or qs.get("pcslid")
        if v:
            return v[0]
    except Exception:
        pass
    m = re.search(r"[?&]PCSLID=([A-Za-z0-9_\-]+)", url, re.IGNORECASE)
    return m.group(1) if m else None


def _extraire_dce_id_et_cyc_num(html: str) -> tuple:
    """Extrait (dceId, cycNum) depuis le HTML de la page detail."""
    if not html:
        return None, None
    m = re.search(
        r"getDceDetails\s*\(\s*['\"]?(\d+)['\"]?\s*,\s*['\"]?(\d+)['\"]?\s*\)",
        html,
    )
    if m:
        return m.group(1), m.group(2)
    m = re.search(
        r"submitFormeDownload\s*\(\s*['\"]?(\d+)['\"]?\s*\)",
        html,
    )
    if m:
        return m.group(1), "0"
    m = re.search(r'jqDownloadWrappGroup_(\d+)', html)
    if m:
        return m.group(1), "0"
    return None, None


def _decompresser_zip_imbrique(chemin_zip_externe: str, dossier_dce: str,
                                 verbose: bool = False) -> dict:
    """
    Décompresse le ZIP externe + tous les ZIP imbriqués trouvés à l'intérieur.

    Cas typique achatpublic : le ZIP externe ne contient qu'un seul fichier
    `DCE/DCE.zip` qui lui contient les vraies pièces.

    Comportement :
      - Décompresse le ZIP externe dans le dossier DCE
      - Pour chaque .zip imbriqué détecté, le décompresse dans son dossier parent
      - Les ZIP (externe + internes) restent en place après décompression
      - Aucune limite de profondeur, mais boucle de sécurité (max 3 niveaux)

    Retourne {nb_zip_internes_decompressed, nb_fichiers_extraits, erreur}
    """
    out = {"nb_zip_internes_decompressed": 0, "nb_fichiers_extraits": 0,
           "erreur": None}
    if not os.path.isfile(chemin_zip_externe):
        out["erreur"] = "ZIP externe introuvable"
        return out

    try:
        # Étape 1 : décompresser le ZIP externe directement dans le dossier DCE
        with zipfile.ZipFile(chemin_zip_externe) as z_externe:
            noms_externes = z_externe.namelist()
            z_externe.extractall(dossier_dce)
        if verbose:
            print(f"        ZIP externe décompressé : {len(noms_externes)} entrées")

        # Étape 2 : chercher et décompresser les ZIP imbriqués (max 3 niveaux)
        deja_traites = {os.path.abspath(chemin_zip_externe)}
        for niveau in range(3):
            nouveaux_zips = []
            for racine, _dirs, fichiers in os.walk(dossier_dce):
                for f in fichiers:
                    if not f.lower().endswith(".zip"):
                        continue
                    chemin_complet = os.path.abspath(os.path.join(racine, f))
                    if chemin_complet in deja_traites:
                        continue
                    nouveaux_zips.append(chemin_complet)
            if not nouveaux_zips:
                break
            for zip_int in nouveaux_zips:
                deja_traites.add(zip_int)
                try:
                    with zipfile.ZipFile(zip_int) as z_int:
                        dossier_extraction = os.path.dirname(zip_int)
                        z_int.extractall(dossier_extraction)
                        nb_entries = len(z_int.namelist())
                        out["nb_fichiers_extraits"] += nb_entries
                    out["nb_zip_internes_decompressed"] += 1
                    if verbose:
                        nom = os.path.basename(zip_int)
                        print(f"        ZIP interne {nom} : {nb_entries} entrées")
                except zipfile.BadZipFile:
                    if verbose:
                        print(f"        ZIP corrompu, skip : {zip_int}")
                    continue
                except Exception as e:
                    if verbose:
                        print(f"        Échec décompression {zip_int} : {e}")
                    continue

    except Exception as e:
        out["erreur"] = f"{type(e).__name__}: {e}"
        return out

    return out


def telecharger_dce(
    pcslid: str,
    chemin_destination: str,
    verbose: bool = True,
    timeout: int = 120,
    decompresser: bool = True,
    session_id: str = None,
) -> dict:
    """Télécharge le ZIP DCE en mode anonyme + décompresse les ZIP imbriqués.

    Returns: {ok, chemin, taille_octets, erreur, duree_secondes,
              nb_zip_internes_decompressed, nb_fichiers_extraits}
    """
    debut = time.time()
    out = {"ok": False, "chemin": None, "taille_octets": 0, "erreur": None,
           "duree_secondes": 0.0, "nb_zip_internes_decompressed": 0,
           "nb_fichiers_extraits": 0}

    # Session « humaine » : UA tournant + TLS Chrome + IP dédiée (anti-ban).
    session = http_humain.creer_session_humaine(session_id=session_id or pcslid,
                                                plateforme="achatpublic")

    url_detail = _construire_url_detail(pcslid)
    if verbose:
        print(f"  [achatpublic] DCE pcslid={pcslid}")

    # ÉTAPE 1 : GET page détail
    try:
        if verbose:
            print(f"    [1/3] GET page détail...")
        r1 = session.get(url_detail, timeout=timeout, allow_redirects=True)
        if r1.status_code != 200:
            out["erreur"] = f"GET HTTP {r1.status_code}"
            return out
        html = r1.text
    except Exception as e:
        out["erreur"] = f"Erreur GET étape 1 : {type(e).__name__}: {e}"
        return out

    dce_id, cyc_num = _extraire_dce_id_et_cyc_num(html)
    if not dce_id:
        out["erreur"] = ("dceId introuvable dans le HTML : page peut-être en mode "
                          "auth requis, marché clos, ou structure changée")
        return out
    if verbose:
        print(f"        dceId={dce_id} cycNum={cyc_num}")

    # ÉTAPE 2 : POST téléchargement
    try:
        # Délai « humain » : temps de lire la page détail avant de cliquer
        # « Télécharger le DCE » (2-5 s).
        http_humain.attendre_inter_etapes(2, 5, verbose=verbose)
        if verbose:
            print(f"    [2/3] POST telechargerDCE.action...")
        url_dl = _construire_url_download(pcslid, cyc_num)
        payload = {
            "PCSLID": pcslid,
            "cycNum": cyc_num,
            "dceId": dce_id,
            "nomEntiteContact": "",
            "nomPointContact": "",
            "mailPointContact": "",
        }
        r2 = session.post(
            url_dl,
            data=payload,
            timeout=timeout,
            allow_redirects=True,
            headers={
                "Origin": URL_BASE_ACHATPUBLIC,
                "Referer": url_detail,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            stream=True,
        )
        if r2.status_code != 200:
            out["erreur"] = f"POST HTTP {r2.status_code}"
            return out

        ct = r2.headers.get("Content-Type", "").lower()
        cd = r2.headers.get("Content-Disposition", "").lower()
        if "html" in ct and not cd:
            out["erreur"] = (f"Réponse HTML au lieu de ZIP (content-type={ct}). "
                              "Marché peut-être clos ou en mode restreint.")
            return out

        os.makedirs(os.path.dirname(chemin_destination), exist_ok=True)
        with open(chemin_destination, "wb") as f:
            for chunk in r2.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)

        taille = os.path.getsize(chemin_destination)

        with open(chemin_destination, "rb") as f:
            magic = f.read(2)
        if magic != b"PK":
            out["erreur"] = (f"Fichier téléchargé n'est pas un ZIP "
                              f"(magic bytes : {magic!r})")
            return out

        out["taille_octets"] = taille
        if verbose:
            print(f"        ZIP téléchargé : {taille:,} octets")
    except Exception as e:
        out["erreur"] = f"Erreur POST étape 2 : {type(e).__name__}: {e}"
        out["duree_secondes"] = round(time.time() - debut, 2)
        return out

    # ÉTAPE 3 : décompression ZIP imbriqué (cas achatpublic typique)
    if decompresser:
        try:
            if verbose:
                print(f"    [3/3] Décompression ZIP achatpublic...")
            dossier_dce = os.path.dirname(chemin_destination)
            res_decomp = _decompresser_zip_imbrique(chemin_destination,
                                                     dossier_dce,
                                                     verbose=verbose)
            out["nb_zip_internes_decompressed"] = res_decomp[
                "nb_zip_internes_decompressed"]
            out["nb_fichiers_extraits"] = res_decomp["nb_fichiers_extraits"]
            if res_decomp.get("erreur") and verbose:
                print(f"        Décompression avertissement : {res_decomp['erreur']}")
        except Exception as e:
            if verbose:
                print(f"        Décompression échouée (non bloquant) : {e}")

    out["ok"] = True
    out["chemin"] = chemin_destination
    out["duree_secondes"] = round(time.time() - debut, 2)
    return out


def telecharger_dce_pour_marche(
    marche: dict,
    repertoire_dce: str,
    verbose: bool = True,
) -> dict:
    """Wrapper : extrait PCSLID depuis marche['url_dce'], appelle telecharger_dce.
    """
    id_marche = marche.get("id", "?")
    url_dce = marche.get("url_dce")

    out = {"id_marche": id_marche, "ok": False, "skip": False,
           "erreur": None, "chemin": None}

    if not url_dce:
        out["erreur"] = "Pas d'URL DCE résolue pour ce marché"
        return out

    pcslid = _extraire_pcslid_depuis_url(url_dce)
    if not pcslid:
        out["erreur"] = f"PCSLID introuvable dans l'URL : {url_dce[:100]}"
        return out

    dossier_cible = os.path.join(repertoire_dce, id_marche)
    chemin_zip = os.path.join(dossier_cible, f"dce_{pcslid}.zip")

    # Skip si déjà téléchargé ET ZIP imbriqué déjà décompressé (présence d'un
    # ZIP racine seul = à reprendre)
    if os.path.isfile(chemin_zip) and os.path.getsize(chemin_zip) > 1000:
        # Vérifier qu'il y a aussi d'autres fichiers décompressés
        autres_fichiers = []
        for racine, _dirs, fichiers in os.walk(dossier_cible):
            for f in fichiers:
                if os.path.abspath(os.path.join(racine, f)) != os.path.abspath(chemin_zip):
                    autres_fichiers.append(f)
        if autres_fichiers:
            out["ok"] = True
            out["skip"] = True
            out["chemin"] = chemin_zip
            if verbose:
                print(f"  [achatpublic] Skip {id_marche} (zip + décompressé)")
            return out
        # Sinon : on a juste le ZIP mais pas décompressé, on retraite

    if verbose:
        print(f"  [achatpublic] {id_marche} → pcslid={pcslid}")

    resultat = telecharger_dce(pcslid, chemin_zip, verbose=verbose,
                               session_id=id_marche)
    out.update(resultat)
    out["id_marche"] = id_marche
    tendia_logs.logger_evenement_marche("achatpublic", id_marche, {
        "ok": out.get("ok"), "skip": out.get("skip", False),
        "taille_octets": out.get("taille_octets", 0),
        "erreur": out.get("erreur"),
        "duree_secondes": out.get("duree_secondes", 0.0),
    })
    return out


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage : python achatpublic_downloader.py <pcslid> [chemin_zip]")
        sys.exit(1)
    pcslid_arg = sys.argv[1]
    chemin = sys.argv[2] if len(sys.argv) > 2 else f"data/test_dce_{pcslid_arg}.zip"
    print(f"Test téléchargement DCE :")
    print(f"  pcslid      = {pcslid_arg}")
    print(f"  destination = {chemin}")
    print()
    res = telecharger_dce(pcslid_arg, chemin, verbose=True)
    print()
    print("Résultat :", res)
