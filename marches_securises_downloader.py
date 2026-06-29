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
import uuid
import zipfile

import requests
import http_humain

try:
    import truststore as _truststore
    _truststore.inject_into_ssl()
except Exception:
    pass

# Charge .env / .env.txt à l'import : le connecteur DOIT voir TENDIA_PROXY_URL
# (sinon il tape sur l'IP réelle, vite sur-quota → « token introuvable »). Couvre
# le worker --un-marche lancé en sous-process, qui ne charge pas l'env autrement.
try:
    from dotenv import load_dotenv
    load_dotenv(".env")
    load_dotenv(".env.txt")
except Exception:
    pass


def _session():
    """Session proxifiée (IP résidentielle FRAÎCHE, headers humains). marches-securises
    applique un QUOTA DE TÉLÉCHARGEMENTS PAR IP ; une IP fraîche est sous quota →
    la rotation d'IP (proxy résidentiel) EST le moyen de contourner le quota.
    ⚠️ Le proxy doit être chargé (TENDIA_PROXY_URL) sinon on tape sur l'IP réelle,
    vite sur-quota (cf load_dotenv en tête de module)."""
    return http_humain.creer_session_humaine(session_id=uuid.uuid4().hex[:8],
                                              plateforme="marches_securises")

HOST_MS = "marches-securises.fr"
_BASE = "https://www.marches-securises.fr/entreprise/"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

_RE_CLE = re.compile(r"cle_dce=([A-Za-z0-9]+)")
_RE_TOKEN = re.compile(r"dl_dc_s[^A-Za-z0-9]+token=([A-Za-z0-9]+)")
_RE_TAG = re.compile(r"<[^>]+>")
_RE_WS = re.compile(r"\s+")
# Page « quota IP atteint » : le lien de DL anonyme est remplacé par ce message.
# C'est un quota PAR ADRESSE IP → une IP fraîche (proxy rotatif) est sous quota.
_RE_QUOTA = re.compile(r"nombre maximum de t[ée]l[ée]chargement", re.I)

MAX_ESSAIS_IP = 12   # nb d'IP fraîches à essayer pour trouver une IP sous quota

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
    lignes = _lignes_consultations(reference, timeout)
    if verbose:
        print(f"    [marches-securises] réf '{reference}' → {len(lignes)} consultation(s)")
    if not lignes:
        out["erreur"] = "aucune consultation trouvée pour la référence"
        return out

    # Désambiguïsation SUR LA LISTE (avant toute page détail) : chaque ligne de
    # résultat contient la Référence + la zone géo de l'acheteur. On classe les
    # cle_dce par correspondance acheteur et on ne tente QUE le(s) meilleur(s).
    # → Réfs génériques (« 03/2026 » = 10 résultats) : 1 requête au lieu de 10,
    #   ce qui évite le burst qui faisait throttler le batch entier.
    cles = _ordonner_par_acheteur(lignes, acheteur, verbose)
    if not cles:
        out["erreur"] = (f"référence générique non résoluble "
                         f"({len(lignes)} résultats, acheteur non apparié)")
        return out

    # Quirk : le lien de téléchargement anonyme (avec token) n'apparaît qu'à la
    # PREMIÈRE visite d'une page détail dans une session. On traite chaque cle_dce
    # dans une SESSION FRAÎCHE → chaque détail est une « première visite ».
    # 2e filet : désambiguïsation par nom de fichier (qui contient l'acheteur),
    # vérifiée AVANT d'écrire le corps : on n'attache jamais le mauvais DCE.
    # marches-securises applique un QUOTA DE TÉLÉCHARGEMENTS PAR IP : sous le
    # quota, le lien anonyme (dl_dc_s&token=) est servi ; au-dessus, il est
    # remplacé par « Le nombre maximum de téléchargement a été atteint ». Le quota
    # est PAR ADRESSE IP → on RETENTE avec des IP fraîches (proxy rotatif) jusqu'à
    # tomber sur une IP sous quota. C'est le vrai levier (la rotation BAT le quota).
    # « no_token » sans message de quota = pas d'accès anonyme (structurel) → stop.
    vu_attachment = [False]
    quota_vu = [False]
    for cle in cles:
        for essai in range(1, MAX_ESSAIS_IP + 1):
            res = _tenter_cle(reference, cle, dossier_destination, acheteur,
                              timeout, verbose, vu_attachment, quota_vu)
            if res is True or res == "no_token":   # acheteur ≠ / pas d'accès anonyme
                break
            if isinstance(res, dict) and res.get("ok"):
                res["cle_dce"] = cle
                return res
            # "quota" (IP sur quota) ou None (réseau) → retry IP fraîche
            if verbose and essai < MAX_ESSAIS_IP:
                motif = "IP sur quota" if res == "quota" else "échec réseau"
                print(f"    [marches-securises] {motif} → IP fraîche "
                      f"{essai+1}/{MAX_ESSAIS_IP}")
    if vu_attachment[0]:
        out["erreur"] = "acheteur non apparié parmi les résultats"
    elif quota_vu[0]:
        out["erreur"] = f"quota IP épuisé sur {MAX_ESSAIS_IP} IP (réessayer plus tard)"
    else:
        out["erreur"] = "pas d'accès anonyme (consultation restreinte ?)"
    return out


def _tenter_cle(reference, cle, dossier_destination, acheteur, timeout, verbose,
                vu_attachment, quota_vu):
    """Tente une consultation sur une IP fraîche. Retourne dict(ok) si DCE écrit,
    True si l'acheteur ne correspond pas (cle à abandonner), 'quota' si l'IP a
    atteint son quota de téléchargements (retry IP fraîche), 'no_token' si pas
    d'accès anonyme du tout (structurel), None si échec réseau (à retenter)."""
    s = _session()
    try:
        s.get(_BASE + "?module=recherche_consultations", timeout=timeout)
        rp = s.post(_BASE + "?module=consultation|script|selection_consultation_s",
                    data=_form_recherche(reference), timeout=timeout,
                    allow_redirects=True)
        # Le lien de téléchargement anonyme n'est servi QUE si la page détail est
        # demandée avec version=QR ET un Referer = la page liste de résultats
        # (anti-hotlink). Session fraîche par cle = quirk « 1re visite » contourné.
        rd = s.get(_BASE + f"?module=consultation|details&cle_dce={cle}&version=QR",
                   timeout=timeout, headers={"Referer": rp.url})
        mt = _RE_TOKEN.search(rd.text)
        if not mt:
            # Quota IP atteint → retry IP fraîche ; sinon pas d'accès anonyme.
            if _RE_QUOTA.search(rd.text):
                quota_vu[0] = True
                return "quota"
            return "no_token"
        rz = s.get(_BASE + f"?module=script|dl_dc_s&token={mt.group(1)}",
                   timeout=timeout, stream=True, headers={"Referer": rd.url})
    except requests.RequestException:
        return None
    cd = rz.headers.get("content-disposition") or ""
    if "attachment" not in cd.lower():
        # Token présent mais le serveur ne renvoie pas de fichier : DCE anonyme
        # indisponible (consultation restreinte / token périmé) = STRUCTUREL.
        # Pas de retry IP (sinon burst de requêtes qui throttle la recherche
        # du marché suivant) → on abandonne ce cle.
        rz.close()
        return "no_token"
    vu_attachment[0] = True
    nom = (re.search(r'filename="?([^"\r\n;]+)', cd) or [None, ""])[1]
    if not _acheteur_correspond(acheteur, nom):
        if verbose:
            print(f"    [marches-securises] ⊘ {nom[:40]} ≠ acheteur '{(acheteur or '')[:28]}'")
        rz.close()
        return True
    out = {"ok": False, "fichiers_telecharges": [], "taille_octets_total": 0,
           "erreur": None}
    try:
        return _ecrire_zip(rz, dossier_destination, out, verbose)
    except Exception as e:        # IncompleteRead / ChunkedEncodingError…
        if verbose:
            print(f"    [marches-securises] download interrompu : {type(e).__name__}")
        return None


def _form_recherche(reference: str) -> dict:
    return {"module": "liste_consultations", "submit.x": "0", "submit.y": "0",
            "mots_cles": reference, "presta_au": "1", "presta_et": "1",
            "presta_se": "1", "presta_tx": "1", "presta_fo": "1",
            "date_cloture_type": "0", "date_cloture": ""}


def _lignes_consultations(reference: str, timeout: int = 60) -> list:
    """Retourne [(cle_dce, contexte_texte)] — le contexte est le texte de la ligne
    de résultat (Référence + zone géo + objet), servant à désambiguïser par
    acheteur SANS visiter la page détail (donc sans requête supplémentaire)."""
    s = _session()
    try:
        s.get(_BASE + "?module=recherche_consultations", timeout=timeout)
        r = s.post(_BASE + "?module=consultation|script|selection_consultation_s",
                   data=_form_recherche(reference), timeout=timeout,
                   allow_redirects=True)
        h = r.text
    except requests.RequestException:
        return []
    out, vus = [], set()
    for m in _RE_CLE.finditer(h):
        cle = m.group(1)
        if cle in vus:
            continue
        vus.add(cle)
        # Fenêtre AVANT le lien = la ligne de résultat (Référence, objet, zone géo).
        seg = _RE_WS.sub(" ", _RE_TAG.sub(" ", h[max(0, m.start() - 1400):m.start()]))
        out.append((cle, seg))
    return out


def _ordonner_par_acheteur(lignes: list, acheteur: str, verbose: bool) -> list:
    """Classe les cle_dce par correspondance acheteur (tokens distinctifs présents
    dans le contexte de la ligne). Si au moins une ligne matche, on ne renvoie QUE
    les lignes qui matchent (best-first) → on évite de visiter les 10 résultats.
    Sans acheteur ou sans match : ordre d'origine (filet aval = nom de fichier)."""
    cles = [c for c, _ in lignes]
    toks = _tokens_distinctifs(acheteur or "")
    if not toks:
        return cles
    scores = []
    for cle, ctx in lignes:
        n = sum(1 for t in toks if t in _normaliser(ctx))
        scores.append((n, cle))
    matches = [c for n, c in sorted(scores, key=lambda x: -x[0]) if n > 0]
    if matches:
        if verbose:
            print(f"    [marches-securises] acheteur apparié sur la liste "
                  f"→ {len(matches)} cle(s) retenue(s) / {len(cles)}")
        return matches
    # Aucun appariement acheteur sur la liste.
    #  • 1 seul résultat → on tente (l'acheteur peut juste être absent du libellé) ;
    #    filet aval = nom de fichier. Coût : 1 vue.
    #  • plusieurs résultats → réf trop générique : la vraie consultation n'est
    #    pas identifiable et n'est probablement même pas dans la liste. On SKIPPE
    #    (renvoie []) au lieu de griller des vues détail anonymes : ce quota (limité
    #    par fenêtre/ASN, cf RATE_LIMIT_SEC) est réservé aux marchés résolubles.
    if len(cles) == 1:
        return cles
    if verbose:
        print(f"    [marches-securises] aucun acheteur apparié / {len(cles)} "
              f"résultats (réf générique) → non résoluble, skip (quota préservé)")
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
