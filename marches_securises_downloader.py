"""
marches_securises_downloader.py
-------------------------------
Téléchargement anonyme du DCE sur marches-securises.fr (moteur custom, distinct
d'Atexo/Dematis/AWS/xmarches). PAS de captcha.

Flux (reverse-engineeré via HAR `HAR/www.marches-securises.fr.har`) :
  1. GET  /entreprise/?module=recherche_consultations          (cookies de session)
  2. POST /entreprise/?module=consultation|script|selection_consultation_s
          body: module=liste_consultations&submit.x=0&submit.y=0&mots_cles=<REF>
                &presta_au=1&presta_et=1&presta_se=1&presta_tx=1&presta_fo=1
                &date_cloture_type=0&date_cloture=
          → 302 → liste des consultations
  3. GET  /entreprise/?module=liste_consultations...           (résultats)
          → liens `?module=consultation|details&cle_dce=<CLE>`
  4. GET  page détail (cle_dce) → token de téléchargement `dl_dc_s&token=<TOKEN>`
  5. GET  /entreprise/?module=script|dl_dc_s&token=<TOKEN>     → zip DCE

Interface :
    est_url_marches_securises(url) -> bool
    telecharger_dce(reference, dossier_destination, acheteur=None, ...) -> dict
    telecharger_dce_pour_marche(marche, repertoire_dce) -> dict
"""
import os
import re
import sys
import zipfile

import requests

try:
    import truststore as _truststore
    _truststore.inject_into_ssl()
except Exception:
    pass

HOST_MS = "marches-securises.fr"
_BASE = "https://www.marches-securises.fr/entreprise/"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

_RE_CLE = re.compile(r"cle_dce=([A-Za-z0-9]+)")
_RE_TOKEN = re.compile(r"dl_dc_s[^A-Za-z0-9]+token=([A-Za-z0-9]+)")

_GENERIQUES = {"communaute", "communes", "commune", "ville", "conseil", "syndicat",
               "departement", "departemental", "mairie", "pays", "region",
               "metropole", "agglomeration", "agglo", "etablissement", "office",
               "centre", "groupement", "公", "des", "les", "du", "de", "la", "et"}


def _normaliser(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower())


def _tokens_distinctifs(acheteur: str):
    return [w for w in _normaliser(acheteur).split()
            if len(w) >= 4 and w not in _GENERIQUES]


def _acheteur_correspond(acheteur_avis: str, nom_fichier: str) -> bool:
    """Vrai si un token distinctif de l'acheteur apparaît dans le nom de fichier
    (qui contient l'acheteur, ex. CC-Pays-de-Fontenay-Vendee_85...)."""
    if not acheteur_avis:
        return True  # pas d'acheteur pour filtrer → on ne bloque pas
    fich = _normaliser(nom_fichier)
    toks = _tokens_distinctifs(acheteur_avis)
    return any(t in fich for t in toks) if toks else True


def est_url_marches_securises(url: str) -> bool:
    return HOST_MS in (url or "").lower()


def telecharger_dce(reference: str, dossier_destination: str,
                    acheteur: str = None, verbose: bool = True,
                    timeout: int = 60) -> dict:
    out = {"ok": False, "fichiers_telecharges": [], "taille_octets_total": 0,
           "erreur": None}
    if not reference:
        out["erreur"] = "référence absente"
        return out
    cles = _chercher_cles(reference, timeout)
    if verbose:
        print(f"    [marches-securises] réf '{reference}' → {len(cles)} consultation(s)")
    if not cles:
        out["erreur"] = "aucune consultation trouvée pour la référence"
        return out

    # Quirk : le lien de téléchargement anonyme (avec token) n'apparaît qu'à la
    # PREMIÈRE visite d'une page détail dans une session. Pour gérer plusieurs
    # résultats (réf partagée par plusieurs acheteurs), on traite chaque cle_dce
    # dans une SESSION FRAÎCHE → chaque détail est une « première visite ».
    # Désambiguïsation OBLIGATOIRE par acheteur (le nom de fichier le contient),
    # vérifiée AVANT d'écrire le corps : on n'attache jamais le mauvais DCE.
    vu_attachment = False
    for cle in cles:
        s = requests.Session()
        s.headers.update({"User-Agent": _UA, "Accept-Language": "fr-FR,fr;q=0.9"})
        try:
            s.get(_BASE + "?module=recherche_consultations", timeout=timeout)
            s.post(_BASE + "?module=consultation|script|selection_consultation_s",
                   data=_form_recherche(reference), timeout=timeout)
            rd = s.get(_BASE + f"?module=consultation|details&cle_dce={cle}&version=",
                       timeout=timeout)
            mt = _RE_TOKEN.search(rd.text)
            if not mt:
                continue
            rz = s.get(_BASE + f"?module=script|dl_dc_s&token={mt.group(1)}",
                       timeout=timeout, stream=True, headers={"Referer": rd.url})
        except requests.RequestException:
            continue
        cd = rz.headers.get("content-disposition") or ""
        if "attachment" not in cd.lower():
            rz.close()
            continue
        vu_attachment = True
        nom = (re.search(r'filename="?([^"\r\n;]+)', cd) or [None, ""])[1]
        if not _acheteur_correspond(acheteur, nom):
            if verbose:
                print(f"    [marches-securises] ⊘ {nom[:40]} ≠ acheteur '{(acheteur or '')[:28]}'")
            rz.close()
            continue
        res = _ecrire_zip(rz, dossier_destination, out, verbose)
        if res.get("ok"):
            res["cle_dce"] = cle
            return res
    out["erreur"] = ("acheteur non apparié parmi les résultats"
                     if vu_attachment else "token de téléchargement introuvable")
    return out


def _form_recherche(reference: str) -> dict:
    return {"module": "liste_consultations", "submit.x": "0", "submit.y": "0",
            "mots_cles": reference, "presta_au": "1", "presta_et": "1",
            "presta_se": "1", "presta_tx": "1", "presta_fo": "1",
            "date_cloture_type": "0", "date_cloture": ""}


def _chercher_cles(reference: str, timeout: int = 60) -> list:
    s = requests.Session()
    s.headers.update({"User-Agent": _UA, "Accept-Language": "fr-FR"})
    try:
        s.get(_BASE + "?module=recherche_consultations", timeout=timeout)
        r = s.post(_BASE + "?module=consultation|script|selection_consultation_s",
                   data=_form_recherche(reference), timeout=timeout,
                   allow_redirects=True)
        return list(dict.fromkeys(_RE_CLE.findall(r.text)))
    except requests.RequestException:
        return []


def _ecrire_zip(resp, dossier_destination: str, out: dict, verbose: bool) -> dict:
    os.makedirs(dossier_destination, exist_ok=True)
    cd = resp.headers.get("content-disposition") or ""
    m = re.search(r'filename="?([^"\r\n;]+)', cd)
    nom = (m.group(1).strip() if m else "dce_marches_securises.zip")
    chemin = os.path.join(dossier_destination, nom)
    taille = 0
    with open(chemin, "wb") as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)
            taille += len(chunk)
    out["taille_octets_total"] = taille
    if taille < 512:
        out["erreur"] = f"fichier trop petit ({taille}o)"
        return out
    fichiers = [chemin]
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
        print(f"    [marches-securises] ✅ {nom} ({taille/1000:.0f}ko, {len(fichiers)} pièces)")
    return out


def telecharger_dce_pour_marche(marche: dict, repertoire_dce: str,
                                verbose: bool = True) -> dict:
    import resolution_reference as RR
    _, reference = RR.extraire_plateforme_reference(marche)
    id_marche = marche.get("id", "?")
    dossier = os.path.join(repertoire_dce, id_marche)
    res = telecharger_dce(reference, dossier,
                          acheteur=marche.get("acheteur_nom"), verbose=verbose)
    res["id_marche"] = id_marche
    res["chemin"] = dossier
    res["taille_octets"] = res.get("taille_octets_total", 0)
    res["nb_fichiers"] = len(res.get("fichiers_telecharges") or [])
    return res


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ref = sys.argv[1] if len(sys.argv) > 1 else "202607"
    print(telecharger_dce(ref, "data/test_ms", verbose=True))
