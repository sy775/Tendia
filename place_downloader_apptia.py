"""
place_downloader.py
-------------------
Téléchargement automatique anonyme du DCE depuis PLACE
(marches-publics.gouv.fr), sans formulaire à remplir, sans captcha.

Technique : enchainement de 2 POST sur le formulaire Prado/Atexo :
  1. Sélectionne "Télécharger anonymement" + accepte les CGU → page téléchargement
  2. Postback Prado avec PRADO_POSTBACK_TARGET=completeDownload → zip DCE

API :
    telecharger_dce(id_place, org_acronyme, destination) -> dict
    telecharger_dce_pour_marche(marche, repertoire_dce) -> dict
"""

import os
import re
import time
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    raise RuntimeError(
        "La lib 'requests' est requise. Lance : pip install requests"
    )


URL_BASE_PLACE = "https://www.marches-publics.gouv.fr"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _construire_url_formulaire(id_place: int | str, org_acronyme: str) -> str:
    return (
        f"{URL_BASE_PLACE}/index.php"
        f"?page=Entreprise.EntrepriseDemandeTelechargementDce"
        f"&id={id_place}&orgAcronyme={org_acronyme}"
    )


def _extraire_inputs_form(html: str) -> dict:
    """
    Extrait tous les inputs nommés d'un formulaire HTML.

    Inclut les inputs cachés-par-style (display:none) qu'on a besoin pour Prado
    (notamment PRADO_PAGESTATE de ~17KB).

    Pour les radio/checkbox : inclut seulement si checked.
    Pour les autres types : inclut systématiquement.
    Ignore les boutons submit.
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
    """
    Extrait le EventTarget Prado depuis le JS de la page.

    Cherche un pattern type :
      new Prado.WebUI.TLinkButton({'EventTarget':"ctl0$...$completeDownload",...})
    """
    m = re.search(
        rf"'EventTarget':\s*\"([^\"]*{re.escape(mot_cle)}[^\"]*)\"",
        html
    )
    return m.group(1) if m else None


def telecharger_dce(
    id_place: int | str,
    org_acronyme: str,
    chemin_destination: str,
    verbose: bool = True,
    timeout: int = 120,
) -> dict:
    """
    Télécharge le zip DCE d'un marché PLACE en mode anonyme.

    Args:
        id_place: l'identifiant interne PLACE (ex : 3003304)
        org_acronyme: l'acronyme de l'organisme acheteur (FT = "h8j")
        chemin_destination: chemin complet du fichier zip à créer
        verbose: True pour logger chaque étape
        timeout: timeout HTTP en secondes

    Returns:
        {
          "ok": bool,
          "chemin": str,           # chemin du zip si OK
          "taille_octets": int,    # taille du fichier téléchargé
          "erreur": str | None,
          "duree_secondes": float,
        }
    """
    debut = time.time()
    out = {"ok": False, "chemin": None, "taille_octets": 0, "erreur": None,
            "duree_secondes": 0.0}

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
        "Accept-Language": "fr-FR,fr;q=0.9",
    })

    url_form = _construire_url_formulaire(id_place, org_acronyme)
    if verbose:
        print(f"  [PLACE] Téléchargement DCE id={id_place} acronyme={org_acronyme}")

    # ----- Étape 1 : GET formulaire identité -----
    try:
        if verbose:
            print(f"    [1/3] GET formulaire identité...")
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
        if verbose:
            print(f"    [2/3] POST 1 : anonyme + CGU...")
        # Extrait tous les champs du formulaire
        payload1 = _extraire_inputs_form(html1)

        # Cherche la radio "choixAnonyme" (sa name + sa value)
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

        # Cherche la checkbox CGU
        cb_cgu = None
        for m in re.finditer(r'<input[^>]+type=["\']?checkbox[^>]*>', html1, re.IGNORECASE):
            inp = m.group(0)
            name_m = re.search(r'name=["\']([^"\']+)["\']', inp)
            if name_m and "accepterConditions" in name_m.group(1):
                cb_cgu = name_m.group(1)
                break
        if cb_cgu:
            payload1[cb_cgu] = "on"

        # Bouton "Valider"
        for m in re.finditer(r'<input[^>]+type=["\']?submit[^>]*>', html1, re.IGNORECASE):
            inp = m.group(0)
            name_m = re.search(r'name=["\']([^"\']+)["\']', inp)
            value_m = re.search(r'value=["\']([^"\']+)["\']', inp)
            if name_m and value_m and value_m.group(1).lower() == "valider":
                payload1[name_m.group(1)] = value_m.group(1)
                break

        # Action POST = main_form action attribute
        action_url = url_form  # par défaut
        for m_form in re.finditer(r'<form([^>]*)>', html1, re.IGNORECASE):
            attrs = m_form.group(1)
            if 'name="main_form"' in attrs or "name='main_form'" in attrs:
                action_m = re.search(r'action=["\']([^"\']+)["\']', attrs)
                if action_m:
                    action_attr = action_m.group(1).replace("&amp;", "&")
                    if action_attr.startswith("http"):
                        action_url = action_attr
                    elif action_attr.startswith("/"):
                        action_url = URL_BASE_PLACE + action_attr
                break

        r2 = session.post(
            action_url, data=payload1, timeout=timeout,
            allow_redirects=True, headers={"Referer": url_form},
        )
        if r2.status_code != 200:
            out["erreur"] = f"POST 1 HTTP {r2.status_code}"
            return out
        html2 = r2.text
        if "completeDownload" not in html2:
            out["erreur"] = "POST 1 : page téléchargement non atteinte (pas de bouton completeDownload)"
            return out
    except Exception as e:
        out["erreur"] = f"Erreur POST 1 : {e}"
        return out

    # ----- Étape 3 : POST 2 (Prado postback completeDownload) -----
    try:
        if verbose:
            print(f"    [3/3] POST 2 : Prado postback (download)...")
        event_target = _trouver_event_target(html2, "completeDownload")
        if not event_target:
            out["erreur"] = "EventTarget 'completeDownload' introuvable"
            return out

        payload2 = _extraire_inputs_form(html2)
        payload2["PRADO_POSTBACK_TARGET"] = event_target
        payload2["PRADO_POSTBACK_PARAMETER"] = ""

        r3 = session.post(
            action_url, data=payload2, timeout=timeout,
            allow_redirects=True, headers={"Referer": r2.url},
            stream=True,
        )
        if r3.status_code != 200:
            out["erreur"] = f"POST 2 HTTP {r3.status_code}"
            return out

        # Vérifie qu'on a bien un fichier (et pas une page HTML)
        cd = r3.headers.get("Content-Disposition", "")
        ct = r3.headers.get("Content-Type", "")
        if not cd and "html" in ct.lower():
            out["erreur"] = "POST 2 : pas de fichier retourné, juste du HTML"
            return out

        # Crée le dossier parent si nécessaire
        os.makedirs(os.path.dirname(chemin_destination), exist_ok=True)

        # Écrit le zip par chunks
        with open(chemin_destination, "wb") as f:
            for chunk in r3.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)

        taille = os.path.getsize(chemin_destination)

        # Vérifie la signature ZIP (magic bytes "PK")
        with open(chemin_destination, "rb") as f:
            magic = f.read(2)
        if magic != b"PK":
            out["erreur"] = (f"Fichier téléchargé n'est pas un ZIP "
                              f"(magic bytes : {magic!r})")
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


# ---------------------------------------------------------------------------
# Extraction de l'id PLACE + acronyme depuis l'URL DCE d'un marché Apptia
# ---------------------------------------------------------------------------

def _extraire_id_org_depuis_url(url: str) -> tuple[Optional[str], Optional[str]]:
    """
    Extrait id et orgAcronyme depuis une URL DCE PLACE résolue.
    Exemples acceptés :
      https://...?page=Entreprise.EntrepriseDetailsConsultation&id=3003304&orgAcronyme=h8j
      https://www.marches-publics.gouv.fr/app.php/entreprise/consultation/3003304?orgAcronyme=h8j
    """
    if not url:
        return None, None
    id_m = re.search(r'[?&]id=(\d+)', url)
    id_m2 = re.search(r'/consultation/(\d+)', url)
    org_m = re.search(r'[?&]orgAcronyme=([a-zA-Z0-9]+)', url)
    id_v = (id_m.group(1) if id_m else
            id_m2.group(1) if id_m2 else None)
    org_v = org_m.group(1) if org_m else None
    return id_v, org_v


def telecharger_dce_pour_marche(
    marche: dict,
    repertoire_dce: str,
    verbose: bool = True,
) -> dict:
    """
    Wrapper pratique : prend un marché Apptia et télécharge son DCE
    dans data/dce/<id_marche>/dce.zip.

    Args:
        marche: dict marché avec au moins {id, url_dce}
        repertoire_dce: chemin racine vers data/dce/

    Returns:
        Voir telecharger_dce() — avec en plus 'id_marche' et 'skip'.
    """
    id_marche = marche.get("id", "?")
    url_dce = marche.get("url_dce")

    out = {"id_marche": id_marche, "ok": False, "skip": False,
            "erreur": None, "chemin": None}

    if not url_dce:
        out["erreur"] = "Pas d'URL DCE résolue pour ce marché"
        return out

    id_place, org = _extraire_id_org_depuis_url(url_dce)
    if not id_place or not org:
        out["erreur"] = f"URL DCE inexploitable : {url_dce[:100]}"
        return out

    dossier_cible = os.path.join(repertoire_dce, id_marche)
    chemin_zip = os.path.join(dossier_cible, f"dce_{id_place}.zip")

    # Skip si déjà téléchargé
    if os.path.isfile(chemin_zip) and os.path.getsize(chemin_zip) > 1000:
        out["ok"] = True
        out["skip"] = True
        out["chemin"] = chemin_zip
        if verbose:
            print(f"  [PLACE] Skip {id_marche} (zip déjà présent)")
        return out

    if verbose:
        print(f"  [PLACE] {id_marche} → id_place={id_place} acronyme={org}")

    resultat = telecharger_dce(id_place, org, chemin_zip, verbose=verbose)
    out.update(resultat)
    out["id_marche"] = id_marche
    return out


# ---------------------------------------------------------------------------
# CLI pour test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    # Usage : python place_downloader.py <id_place> <org_acronyme> [chemin]
    if len(sys.argv) < 3:
        print("Usage : python place_downloader.py <id_place> <org_acronyme> [chemin_zip]")
        print()
        print("Exemple :")
        print("  python place_downloader.py 3003304 h8j data/test_dce.zip")
        sys.exit(1)
    id_p = sys.argv[1]
    org = sys.argv[2]
    chemin = sys.argv[3] if len(sys.argv) > 3 else f"data/test_dce_{id_p}.zip"
    print(f"Test téléchargement DCE :")
    print(f"  id_place    = {id_p}")
    print(f"  acronyme    = {org}")
    print(f"  destination = {chemin}")
    print()
    res = telecharger_dce(id_p, org, chemin, verbose=True)
    print()
    print("Résultat :", res)
