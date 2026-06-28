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


def _identite_telechargement() -> dict:
    """Identité utilisée pour les consultations PLACE qui refusent l'anonyme.
    Configurable via .env (TENDIA_DL_*), sinon valeurs génériques de veille."""
    return {
        "nom": os.environ.get("TENDIA_DL_NOM", "Veille"),
        "prenom": os.environ.get("TENDIA_DL_PRENOM", "Tendia"),
        "email": os.environ.get("TENDIA_DL_EMAIL", "contact@tendia.fr"),
        "raison_sociale": os.environ.get("TENDIA_DL_RAISON_SOCIALE", "Tendia"),
        "adresse": os.environ.get("TENDIA_DL_ADRESSE", "1 rue de la Republique"),
        "cp": os.environ.get("TENDIA_DL_CP", "75001"),
        "ville": os.environ.get("TENDIA_DL_VILLE", "Paris"),
        "tel": os.environ.get("TENDIA_DL_TEL", "0100000000"),
        # SIRET/SIREN : certaines consultations PLACE valident le checksum → un faux
        # échoue. À renseigner dans .env (TENDIA_DL_SIRET) avec un SIRET RÉEL pour
        # débloquer le téléchargement identifié de ces consultations.
        "siret": os.environ.get("TENDIA_DL_SIRET", ""),
        "siren": os.environ.get("TENDIA_DL_SIREN", os.environ.get("TENDIA_DL_SIRET", "")[:9]),
    }


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

    # ----- Étape 2 : POST 1 — anonyme d'abord, puis identifié si refusé -----
    # Certaines consultations PLACE (France Travail notamment) REFUSENT le
    # téléchargement anonyme et exigent une identité (nom/prénom/email/raison
    # sociale). On tente l'anonyme, et si la page de téléchargement n'est pas
    # atteinte, on bascule automatiquement sur le téléchargement identifié.
    try:
        # --- Champs communs au formulaire (CGU, bouton Valider, action, radios) ---
        cb_cgu = None
        for m in re.finditer(r'<input[^>]+type=["\']?checkbox[^>]*>', html1, re.IGNORECASE):
            name_m = re.search(r'name=["\']([^"\']+)["\']', m.group(0))
            if name_m and "accepterConditions" in name_m.group(1):
                cb_cgu = name_m.group(1)
                break
        submit_field = None
        for m in re.finditer(r'<input[^>]+type=["\']?submit[^>]*>', html1, re.IGNORECASE):
            name_m = re.search(r'name=["\']([^"\']+)["\']', m.group(0))
            value_m = re.search(r'value=["\']([^"\']+)["\']', m.group(0))
            if name_m and value_m and value_m.group(1).lower() == "valider":
                submit_field = (name_m.group(1), value_m.group(1))
                break
        # Radios disponibles : groupe principal (anonyme / téléchargement identifié)
        # + établissement (france / étranger).
        radios = {}
        for m in re.finditer(r'<input[^>]+type=["\']?radio[^>]*>', html1, re.IGNORECASE):
            name_m = re.search(r'name=["\']([^"\']+)["\']', m.group(0))
            value_m = re.search(r'value=["\']([^"\']*)["\']', m.group(0))
            if name_m and value_m:
                radios.setdefault(name_m.group(1), []).append(value_m.group(1))
        grp = next((n for n in radios if n.endswith("$RadioGroup")), None)
        val_anon = next((v for v in radios.get(grp, []) if "choixAnonyme" in v), None)
        val_dl = next((v for v in radios.get(grp, []) if "choixTelechargement" in v), None)
        etab = next((n for n in radios if n.endswith("$etablissementEntreprise")), None)
        val_fr = next((v for v in radios.get(etab, []) if v.endswith("$france")), None)

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

        def _construire_payload(mode):
            p = _extraire_inputs_form(html1)
            if cb_cgu:
                p[cb_cgu] = "on"
            if submit_field:
                p[submit_field[0]] = submit_field[1]
            if mode == "anonyme" and grp and val_anon:
                p[grp] = val_anon
            elif mode == "identifie" and grp and val_dl:
                p[grp] = val_dl
                ident = _identite_telechargement()
                base = grp.rsplit("$", 1)[0]  # …$EntrepriseFormulaireDemande
                p[base + "$nom"] = ident["nom"]
                p[base + "$prenom"] = ident["prenom"]
                p[base + "$email"] = ident["email"]
                p[base + "$raisonSocial"] = ident["raison_sociale"]
                p[base + "$address"] = ident["adresse"]
                p[base + "$cp"] = ident["cp"]
                p[base + "$ville"] = ident["ville"]
                p[base + "$tel"] = ident["tel"]
                if ident.get("siret"):
                    p[base + "$siret"] = ident["siret"]
                if ident.get("siren"):
                    p[base + "$siren"] = ident["siren"]
                if etab and val_fr:
                    p[etab] = val_fr
            return p

        html2 = None
        r2 = None
        for mode in ("anonyme", "identifie"):
            if mode == "anonyme" and not val_anon:
                continue
            if mode == "identifie" and not val_dl:
                break
            if verbose:
                print(f"    [2/3] POST 1 : {mode} + CGU...")
            r2 = session.post(action_url, data=_construire_payload(mode), timeout=timeout,
                              allow_redirects=True, headers={"Referer": url_form})
            if r2.status_code != 200:
                out["erreur"] = f"POST 1 ({mode}) HTTP {r2.status_code}"
                continue
            if "completeDownload" in r2.text:
                html2 = r2.text
                if verbose and mode == "identifie":
                    print("        ↳ bascule téléchargement identifié (anonyme refusé)")
                break
        if not html2:
            out["erreur"] = "POST 1 : page téléchargement non atteinte (anonyme et identifié refusés)"
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
# Extraction de l'id PLACE + acronyme depuis l'URL DCE d'un marché Tendia
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
    Wrapper pratique : prend un marché Tendia et télécharge son DCE
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
