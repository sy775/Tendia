"""
atexo_downloader.py
-------------------
Téléchargement automatique anonyme du DCE sur les plateformes Atexo MPE / Prado
(PLACE marches-publics.gouv.fr + forks régionaux/municipaux), sans formulaire à
remplir manuellement, sans captcha. Que du `requests`.

Dérivé du `place_downloader.py` Apptia, GÉNÉRALISÉ : `url_base` est détecté
dynamiquement depuis l'URL DCE du marché (au lieu d'être codé en dur sur PLACE),
car 5+ plateformes partagent le même moteur Atexo/Prado — seul l'host change.

Technique : enchaînement de 2 POST sur le formulaire Prado/Atexo :
  1. GET formulaire identité
  2. POST "Télécharger anonymement" + accepte CGU → page téléchargement
  3. Postback Prado PRADO_POSTBACK_TARGET=completeDownload → zip DCE

API :
    telecharger_dce(id_atexo, org_acronyme, destination, url_base) -> dict
    telecharger_dce_pour_marche(marche, repertoire_dce) -> dict
    _detecter_url_base(url_dce) -> str | None
"""

import os
import re
import time
from typing import Optional
from urllib.parse import urlparse

import http_client as http_lib   # backend curl_cffi (TLS Chrome) ou requests
import http_humain
import tendia_logs


# Conservé pour compat (scripts diagnostic lisant atexo_downloader.USER_AGENT).
# Le workflow utilise désormais http_humain.creer_session_humaine() (anti-ban).
USER_AGENT = http_humain.USER_AGENTS_POOL[0]

# Hosts Atexo MPE / Prado connus (PLACE + forks). La détection accepte aussi
# tout host portant la signature Atexo (orgAcronyme + page Entreprise.),
# ce qui rattrape les forks municipaux non listés.
HOSTS_ATEXO = (
    "marches-publics.gouv.fr",          # PLACE
    "marches.ternum-bfc.fr",
    "demat-ampa.fr",
    "marches.megalis.bretagne.bzh",
    "marches.maximilien.fr",
    "marches.rhone.fr",
    "marchespublics.nantesmetropole.fr",
    "mpe.mairie-marseille.fr",
    "xmarches.fr",
    "profilacheteur.meuse.fr",
)

# Hosts à NE PAS router vers Atexo (autre moteur ou auth).
_HOSTS_EXCLUS = ("e-marchespublics.com", "marches-publics.info",
                 "achatpublic.com", "marches-securises.fr")


def _detecter_url_base(url_dce: str) -> Optional[str]:
    """
    Retourne `scheme://host` si l'URL DCE est une plateforme Atexo, sinon None.
    Reconnaît par host connu OU par signature Atexo (orgAcronyme + Entreprise.),
    en excluant explicitement e-marchespublics et les plateformes auth.
    """
    if not url_dce:
        return None
    low = url_dce.lower()
    if any(h in low for h in _HOSTS_EXCLUS):
        return None
    parsed = urlparse(url_dce)
    if not parsed.netloc:
        return None
    host_connu = any(h in low for h in HOSTS_ATEXO)
    signature = ("orgacronyme=" in low) and ("entreprise." in low)
    if host_connu or signature:
        return f"{parsed.scheme}://{parsed.netloc}"
    return None


def _construire_url_formulaire(id_atexo, org_acronyme: str, url_base: str) -> str:
    return (
        f"{url_base}/index.php"
        f"?page=Entreprise.EntrepriseDemandeTelechargementDce"
        f"&id={id_atexo}&orgAcronyme={org_acronyme}"
    )


def _extraire_inputs_form(html: str) -> dict:
    """
    Extrait tous les inputs nommés d'un formulaire HTML (y compris cachés-par-style
    type PRADO_PAGESTATE). Radio/checkbox inclus seulement si `checked`. Ignore
    les boutons submit.
    """
    fields = {}
    for m in re.finditer(r'<input([^>]+)>', html, re.IGNORECASE):
        inp = m.group(1)
        type_m = re.search(r'type\s*=\s*["\']?([^"\'\s>]+)', inp, re.IGNORECASE)
        name_m = re.search(r'name\s*=\s*["\']?([^"\'\s>]+)', inp, re.IGNORECASE)
        value_m = re.search(r'value\s*=\s*["\']([^"\']*)["\']', inp, re.IGNORECASE)
        type_v = type_m.group(1) if type_m else "text"
        name_v = name_m.group(1) if name_m else ""
        value_v = value_m.group(1) if value_m else ""
        if not name_v or type_v == "submit":
            continue
        if type_v in ("radio", "checkbox"):
            if "checked" in inp.lower():
                fields[name_v] = value_v or "on"
        else:
            fields[name_v] = value_v
    return fields


def _trouver_event_target(html: str, mot_cle: str = "completeDownload") -> Optional[str]:
    """Extrait le EventTarget Prado (ex 'ctl0$...$completeDownload') depuis le JS."""
    m = re.search(rf"'EventTarget':\s*\"([^\"]*{re.escape(mot_cle)}[^\"]*)\"", html)
    return m.group(1) if m else None


def _extraire_id_org_depuis_url(url: str):
    """Extrait (id, orgAcronyme) depuis une URL DCE Atexo, ou (None, None)."""
    if not url:
        return None, None
    id_m = re.search(r'[?&]id=(\d+)', url)
    id_m2 = re.search(r'/consultation/(\d+)', url)
    org_m = re.search(r'[?&]orgAcronyme=([a-zA-Z0-9]+)', url)
    id_v = (id_m.group(1) if id_m else id_m2.group(1) if id_m2 else None)
    org_v = org_m.group(1) if org_m else None
    return id_v, org_v


def telecharger_dce(id_atexo, org_acronyme: str, chemin_destination: str,
                    url_base: str, verbose: bool = True, timeout: int = 120,
                    session_id: str = None) -> dict:
    """
    Télécharge le zip DCE d'un marché Atexo en mode anonyme (2 POST Prado).

    Args:
        id_atexo: identifiant interne de la consultation (ex 3003304)
        org_acronyme: acronyme de l'organisme acheteur
        chemin_destination: chemin complet du fichier zip à créer
        url_base: scheme://host de la plateforme (voir _detecter_url_base)
        session_id: identifiant de session proxy (rotation IP Bright Data).

    Returns: {ok, chemin, taille_octets, erreur, duree_secondes}.
    """
    debut = time.time()
    out = {"ok": False, "chemin": None, "taille_octets": 0, "erreur": None,
           "duree_secondes": 0.0}

    # Session « humaine » : UA tournant + TLS Chrome + IP dédiée (anti-ban).
    # PLACE (marches-publics.gouv.fr) est confirmé sans ban → proxy désactivable
    # via TENDIA_PROXY_FOR_PLACE=0 ; les forks Atexo restent en proxy par défaut.
    _plateforme = "place" if "marches-publics.gouv.fr" in (url_base or "").lower() else "atexo"
    session = http_humain.creer_session_humaine(session_id=session_id or str(id_atexo),
                                                plateforme=_plateforme)

    url_form = _construire_url_formulaire(id_atexo, org_acronyme, url_base)
    if verbose:
        print(f"  [Atexo] DCE id={id_atexo} acronyme={org_acronyme} base={url_base}")

    # ----- Étape 1 : GET formulaire identité -----
    try:
        if verbose:
            print("    [1/3] GET formulaire identité...")
        r1 = session.get(url_form, timeout=timeout, allow_redirects=True)
        if r1.status_code != 200:
            out["erreur"] = f"GET HTTP {r1.status_code}"
            return out
        html1 = r1.text
        if "EntrepriseFormulaireDemande" not in html1:
            out["erreur"] = "Page inattendue (pas de formulaire identité détecté)"
            return out
    except Exception as e:
        out["erreur"] = f"Erreur GET étape 1 : {e}"
        return out

    # ----- Étape 2 : POST 1 (anonyme + CGU) -----
    try:
        # Délai « humain » : temps de remplir le formulaire identité.
        http_humain.attendre_inter_etapes(verbose=verbose)
        if verbose:
            print("    [2/3] POST 1 : anonyme + CGU...")
        payload1 = _extraire_inputs_form(html1)

        radio_anon = None
        for m in re.finditer(r'<input[^>]+type=["\']?radio[^>]*>', html1, re.IGNORECASE):
            inp = m.group(0)
            value_m = re.search(r'value=["\']([^"\']*)["\']', inp)
            name_m = re.search(r'name=["\']([^"\']+)["\']', inp)
            if value_m and name_m and "choixAnonyme" in value_m.group(1):
                radio_anon = (name_m.group(1), value_m.group(1))
                break
        if not radio_anon:
            out["erreur"] = "Radio 'choixAnonyme' introuvable"
            return out
        payload1[radio_anon[0]] = radio_anon[1]

        cb_cgu = None
        for m in re.finditer(r'<input[^>]+type=["\']?checkbox[^>]*>', html1, re.IGNORECASE):
            inp = m.group(0)
            name_m = re.search(r'name=["\']([^"\']+)["\']', inp)
            if name_m and "accepterConditions" in name_m.group(1):
                cb_cgu = name_m.group(1)
                break
        if cb_cgu:
            payload1[cb_cgu] = "on"

        for m in re.finditer(r'<input[^>]+type=["\']?submit[^>]*>', html1, re.IGNORECASE):
            inp = m.group(0)
            name_m = re.search(r'name=["\']([^"\']+)["\']', inp)
            value_m = re.search(r'value=["\']([^"\']+)["\']', inp)
            if name_m and value_m and value_m.group(1).lower() == "valider":
                payload1[name_m.group(1)] = value_m.group(1)
                break

        action_url = url_form
        for m_form in re.finditer(r'<form([^>]*)>', html1, re.IGNORECASE):
            attrs = m_form.group(1)
            if 'name="main_form"' in attrs or "name='main_form'" in attrs:
                action_m = re.search(r'action=["\']([^"\']+)["\']', attrs)
                if action_m:
                    action_attr = action_m.group(1).replace("&amp;", "&")
                    if action_attr.startswith("http"):
                        action_url = action_attr
                    elif action_attr.startswith("/"):
                        action_url = url_base + action_attr
                break

        r2 = session.post(action_url, data=payload1, timeout=timeout,
                          allow_redirects=True, headers={"Referer": url_form})
        if r2.status_code != 200:
            out["erreur"] = f"POST 1 HTTP {r2.status_code}"
            return out
        html2 = r2.text
        if "completeDownload" not in html2:
            out["erreur"] = "POST 1 : page téléchargement non atteinte"
            return out
    except Exception as e:
        out["erreur"] = f"Erreur POST 1 : {e}"
        return out

    # ----- Étape 3 : POST 2 (Prado postback completeDownload) -----
    try:
        # Délai « humain » : temps de cliquer sur « Télécharger ».
        http_humain.attendre_inter_etapes(verbose=verbose)
        if verbose:
            print("    [3/3] POST 2 : Prado postback (download)...")
        event_target = _trouver_event_target(html2, "completeDownload")
        if not event_target:
            out["erreur"] = "EventTarget 'completeDownload' introuvable"
            return out

        payload2 = _extraire_inputs_form(html2)
        payload2["PRADO_POSTBACK_TARGET"] = event_target
        payload2["PRADO_POSTBACK_PARAMETER"] = ""

        r3 = session.post(action_url, data=payload2, timeout=timeout,
                          allow_redirects=True, headers={"Referer": r2.url},
                          stream=True)
        if r3.status_code != 200:
            out["erreur"] = f"POST 2 HTTP {r3.status_code}"
            return out

        cd = r3.headers.get("Content-Disposition", "")
        ct = r3.headers.get("Content-Type", "")
        if not cd and "html" in ct.lower():
            out["erreur"] = "POST 2 : pas de fichier retourné, juste du HTML"
            return out

        os.makedirs(os.path.dirname(chemin_destination), exist_ok=True)
        with open(chemin_destination, "wb") as f:
            for chunk in r3.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)

        taille = os.path.getsize(chemin_destination)
        with open(chemin_destination, "rb") as f:
            magic = f.read(2)
        if magic != b"PK":
            out["erreur"] = f"Fichier téléchargé n'est pas un ZIP (magic : {magic!r})"
            return out

        out["ok"] = True
        out["chemin"] = chemin_destination
        out["taille_octets"] = taille
        if verbose:
            print(f"    ✅ Zip téléchargé : {taille:,} octets")
        return out
    except Exception as e:
        out["erreur"] = f"Erreur POST 2 : {e}"
        return out
    finally:
        out["duree_secondes"] = round(time.time() - debut, 2)


def telecharger_dce_pour_marche(marche: dict, repertoire_dce: str,
                                verbose: bool = True) -> dict:
    """
    Wrapper : télécharge le DCE d'un marché Atexo dans <repertoire_dce>/<id>/.
    Détecte la plateforme (url_base) depuis l'URL DCE. Retourne le contrat
    standard {ok, chemin, taille_octets, erreur, duree_secondes, id_marche, skip}.
    """
    id_marche = marche.get("id", "?")
    url_dce = marche.get("url_dce")
    out = {"id_marche": id_marche, "ok": False, "skip": False,
           "erreur": None, "chemin": None, "duree_secondes": 0.0}

    if not url_dce:
        out["erreur"] = "Pas d'URL DCE résolue pour ce marché"
        return out

    url_base = _detecter_url_base(url_dce)
    if not url_base:
        out["erreur"] = f"Plateforme non-Atexo ou URL inexploitable : {url_dce[:90]}"
        return out

    id_atexo, org = _extraire_id_org_depuis_url(url_dce)
    if not id_atexo or not org:
        out["erreur"] = f"id/orgAcronyme introuvables dans : {url_dce[:90]}"
        return out

    dossier_cible = os.path.join(repertoire_dce, id_marche)
    chemin_zip = os.path.join(dossier_cible, f"dce_{id_atexo}.zip")

    if os.path.isfile(chemin_zip) and os.path.getsize(chemin_zip) > 1000:
        out.update(ok=True, skip=True, chemin=chemin_zip)
        if verbose:
            print(f"  [Atexo] Skip {id_marche} (zip déjà présent)")
        return out

    if verbose:
        print(f"  [Atexo] {id_marche} → id={id_atexo} acronyme={org} base={url_base}")
    resultat = telecharger_dce(id_atexo, org, chemin_zip, url_base,
                               verbose=verbose, session_id=id_marche)
    out.update(resultat)
    out["id_marche"] = id_marche
    tendia_logs.logger_evenement_marche("atexo", id_marche, {
        "ok": out.get("ok"), "skip": out.get("skip", False),
        "taille_octets": out.get("taille_octets", 0),
        "erreur": out.get("erreur"),
        "duree_secondes": out.get("duree_secondes", 0.0),
    })
    return out
