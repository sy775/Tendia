"""
dematis_downloader.py
---------------------
Téléchargement anonyme du DCE complet sur les plateformes Dematis
(`*.e-marchespublics.com`, sous-domaines acheteurs variables).

Workflow STRICT, calé sur le HAR de référence (BOAMP-26-57070,
`dematis exemple/hautsdeseine-habitat.e-marchespublics.com.har`) :

  1. GET page annonce  : /pack/annonce_marche_public_<id1>_<id2>.html
                         La page expose DEUX liens d'accès anonyme :
                           - token 32 hex (MD5)  → LEURRE, redirige vers l'accueil
                           - token 40 hex (SHA-1) → le BON lien
                         → on ne retient QUE le token 40 hex.
  2. GET page dossier  : /dossier_de_consultation_marche_public_anonyme_<token40>
                         → 200, page captcha : form `inscriptionEntreprise`,
                           hidden `captcha[id]` (32 hex), texte `captcha[input]`,
                           submit `submit`, image `/captcha/<captcha_id>.png`.
                         (le champ `captchaResult` est un leurre — NE PAS soumettre)
  3. POST captcha      : sur la MÊME URL dossier, body
                           captcha[id]=<id>&captcha[input]=<solution>&submit=
                         → 302 Location: /acces_dce_marche_public_anonyme_<token40>
                         (un captcha refusé renvoie 200 = re-render du captcha)
  4. GET acces_dce     : /acces_dce_marche_public_anonyme_<token40>
                         → liste des pièces servies par
                           https://private.e-marchespublics.com/dce/getfile.php
                             ?id=<n>&anonyme=<token40>&fromnew
                         → tout télécharger (le libellé de l'ancre = vrai nom de
                           fichier), décompresser les ZIP imbriqués
                         → data/dce/<marche_id>/

SESSION PHP (quirk critique) : la solution du captcha est stockée côté serveur
dans la session PHP, identifiée par le cookie `PHPSESSID`. Or Dematis pose ce
cookie avec un attribut `Domain=` VIDE (malformé) que `http.cookiejar`/requests
rejette → sans correctif, le POST captcha renvoie systématiquement « code de
vérification incorrect » même avec la BONNE solution. `_installer_fix_cookies_
domaine_vide` ré-injecte le cookie sur le bon hôte (cf BOAMP-26-57070).

SSL : sur ce poste, le bundle `certifi` ne contient pas le CA intermédiaire du
magasin Windows → `SSLCertVerificationError` sur *.e-marchespublics.com ET
2captcha.com. Fix propre en place : `truststore` (cf requirements.txt) est
injecté au chargement de `http_client.py` et fait utiliser le magasin de
certificats système → la vérification fonctionne pour tous les hôtes,
`verify_ssl=True` par défaut. Le paramètre `verify_ssl=False` reste un dernier
recours ponctuel (journalisé via `ssl_verify_desactive`), à ne pas activer par
défaut.

API publique :
    telecharger_dce(url_dce, dossier_destination, api_key_2captcha=None, ...) -> dict
    telecharger_dce_pour_marche(marche, repertoire_dce, api_key_2captcha=None) -> dict
"""

import os
import re
import time
import uuid
from typing import Optional
from urllib.parse import urljoin, urlparse

import http_humain
import tendia_logs

# Réutilisation DRY des briques éprouvées d'aws_downloader (import = pas de
# modification du module). Solveur 2captcha, helpers noms de fichiers,
# retry réseau, décompression ZIP imbriqué (qui délègue à achatpublic).
from aws_downloader import (
    ErreurSolde2Captcha,
    _resoudre_captcha_2captcha,
    _nom_fichier_depuis_headers,
    _sanitiser_nom,
    _request_avec_retry,
    _decompresser_zip_imbrique,
)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


HOST_DEMATIS = "e-marchespublics.com"

# Extensions de pièces réelles d'un DCE (pour le harvest de la liste de fichiers).
EXTENSIONS_DOC = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                  ".zip", ".7z", ".rar", ".odt", ".ods", ".dwg", ".txt", ".csv")

# Mots d'URL suggérant un lien de téléchargement DCE. Réel Dematis (HAR) :
# les pièces sont servies par https://private.e-marchespublics.com/dce/getfile.php?id=…&anonyme=…
MOTIFS_URL_TELECHARGEMENT = (
    "telechargement", "telecharger", "download", "getdocument", "getfile",
    "fichier", "document", "pieces", "dossier_de_consultation", "retirer",
)

TWOCAPTCHA_MAX_TENTATIVES = 3
RATE_LIMIT_FICHIERS_SEC = 1
DL_MAX_ESSAIS = 3


# ===========================================================================
# Helpers purs (testables hors ligne)
# ===========================================================================

def est_url_dematis(url: str) -> bool:
    """True si l'URL est servie par une plateforme Dematis (e-marchespublics)."""
    try:
        return HOST_DEMATIS in urlparse(url or "").netloc.lower()
    except Exception:
        return HOST_DEMATIS in (url or "").lower()


def _entetes_set_cookie(resp) -> list:
    """Toutes les valeurs Set-Cookie d'une réponse (raw urllib3 si dispo, sinon
    l'en-tête agrégé de requests)."""
    raw = getattr(resp, "raw", None)
    if raw is not None and getattr(raw, "headers", None) is not None:
        for meth in ("get_all", "getlist"):
            if hasattr(raw.headers, meth):
                try:
                    vals = getattr(raw.headers, meth)("Set-Cookie")
                    if vals:
                        return list(vals)
                except Exception:
                    pass
    try:
        v = resp.headers.get("Set-Cookie")
        return [v] if v else []
    except Exception:
        return []


# Domaine vide : `Domain=` suivi de `;` ou de la fin de chaîne.
_RE_DOMAIN_VIDE = re.compile(r";\s*domain=\s*(?:;|$)", re.IGNORECASE)
_RE_COOKIE_NV = re.compile(r"\s*([^=;\s]+)=([^;]*)")


def _installer_fix_cookies_domaine_vide(session) -> None:
    """
    Quirk Dematis : le serveur pose `PHPSESSID` (et parfois d'autres cookies)
    avec un attribut `Domain=` VIDE (malformé). `http.cookiejar` (donc requests)
    rejette silencieusement ces cookies → la session PHP est perdue à chaque
    requête. Or la solution du captcha est stockée DANS la session PHP : sans le
    cookie, le POST renvoie « Le code de vérification rentré n'est pas le bon »
    même quand la solution est correcte (les navigateurs, eux, tolèrent le
    Domain vide). On installe un hook de réponse qui ré-injecte tout cookie à
    domaine vide en le rattachant à l'hôte de la requête.
    """
    def _hook(resp, *args, **kwargs):
        try:
            host = urlparse(getattr(resp, "url", "") or "").hostname
            if not host:
                return
            for sc in _entetes_set_cookie(resp):
                if not _RE_DOMAIN_VIDE.search(sc):
                    continue  # domaine non vide → requests gère déjà
                m = _RE_COOKIE_NV.match(sc)
                if m and m.group(1):
                    session.cookies.set(m.group(1), m.group(2).strip(),
                                        domain=host, path="/")
        except Exception:
            pass  # un cookie mal formé ne doit jamais casser le téléchargement

    # Sessions factices des tests : pas de hooks/cookies → no-op silencieux.
    hooks = getattr(session, "hooks", None)
    if not isinstance(hooks, dict) or not hasattr(session, "cookies"):
        return
    liste = hooks.setdefault("response", [])
    if _hook not in liste:
        liste.append(_hook)


_RE_LIEN_ANONYME = re.compile(
    r'((?:https?://[^"\'\s]+)?/?(?:dossier_de_consultation|acces_dce)'
    r'_marche_public_anonyme_[A-Za-z0-9]+(?:\.html)?[^"\'\s<>]*)',
    re.IGNORECASE)

# Token d'accès anonyme valide = SHA-1 (40 hex). Le HAR montre qu'une même page
# annonce expose aussi un token 32 hex (MD5) qui est un LEURRE (redirige vers
# l'accueil). On distingue les deux pour ne suivre que le 40 hex.
_RE_TOKEN_40 = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


def _extraire_liens_anonymes(html: str, base_url: str) -> list:
    """
    Liens d'accès anonyme au DCE présents sur la page, dédupliqués et CLASSÉS :
    les tokens SHA-1 (40 hex) d'abord (seuls valides selon le HAR), puis les
    autres en repli (token le plus long d'abord). Le token 32 hex (MD5) observé
    sur la page annonce est un leurre qui redirige vers l'accueil — il est donc
    relégué en fin de liste, jamais essayé en premier. Retourne [(url, variante)].
    """
    if not html:
        return []
    import html as _h
    txt = _h.unescape(html)
    vus, cands = set(), []
    for m in _RE_LIEN_ANONYME.finditer(txt):
        lien = m.group(1).strip()
        url_abs = urljoin(base_url, lien)
        if url_abs in vus:
            continue
        vus.add(url_abs)
        variante = ("acces_dce" if "acces_dce_marche_public_anonyme" in lien.lower()
                    else "dossier_de_consultation")
        tok = lien.rsplit("anonyme_", 1)[-1]
        token = re.split(r"[^A-Za-z0-9]", tok)[0]
        est_sha1 = bool(_RE_TOKEN_40.match(token))
        # tri : (token 40 hex valide d'abord, puis longueur décroissante)
        cands.append((url_abs, variante, est_sha1, len(token)))
    cands.sort(key=lambda c: (not c[2], -c[3]))
    return [(u, v) for u, v, _, _ in cands]


def _extraire_lien_anonyme(html: str, base_url: str):
    """Meilleur lien anonyme (token le plus long), ou (None, None)."""
    liens = _extraire_liens_anonymes(html, base_url)
    return liens[0] if liens else (None, None)


def _extraire_lien_onglet_dossier(html: str, base_url: str) -> Optional[str]:
    """
    Lien de l'onglet « dossier » de la page annonce (si l'accès anonyme n'est
    pas directement sur la page courante). Heuristique : 1ʳᵉ ancre dont l'URL
    ou le libellé évoque le dossier de consultation. # VALIDER
    """
    if not html:
        return None
    import html as _h
    txt = _h.unescape(html)
    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                         txt, re.IGNORECASE | re.DOTALL):
        href, libelle = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2)).lower()
        low = href.lower()
        if "anonyme" in low:
            continue  # déjà géré par _extraire_lien_anonyme
        if "dossier" in low or "dossier de consultation" in libelle or "dce" in libelle:
            return urljoin(base_url, href.replace("&amp;", "&"))
    return None


def _extraire_captcha_img(html: str, base_url: str) -> Optional[str]:
    """URL absolue de l'image captcha (1ʳᵉ <img> dont le src évoque un captcha)."""
    if not html:
        return None
    import html as _h
    txt = _h.unescape(html)
    for m in re.finditer(r'<img\b[^>]*src=["\']([^"\']+)["\']', txt, re.IGNORECASE):
        src = m.group(1)
        if re.search(r"captcha|securimage|kcaptcha", src, re.IGNORECASE):
            return urljoin(base_url, src.replace("&amp;", "&"))
    return None


def _extraire_form_captcha(html: str, base_url: str) -> Optional[dict]:
    """
    Repère le <form> de saisie du captcha (réel Dematis : form
    `inscriptionEntreprise`, sans action → POST sur l'URL courante, champ
    `captcha[input]` + hidden `captcha[id]`). Choisit le form qui contient
    réellement un champ captcha (et non un form de connexion).

    Retourne {action, method, champs (hidden+submit name->value),
    champs_captcha (liste des champs texte à remplir avec la solution)} ou None.
    """
    if not html:
        return None
    import html as _h
    txt = _h.unescape(html)
    meilleur = None
    for fm in re.finditer(r'<form\b([^>]*)>(.*?)</form>', txt, re.IGNORECASE | re.DOTALL):
        attrs, corps = fm.group(1), fm.group(2)
        action_m = re.search(r'action=["\']([^"\']*)["\']', attrs, re.IGNORECASE)
        method_m = re.search(r'method=["\']([^"\']*)["\']', attrs, re.IGNORECASE)
        champs, champs_captcha, autres_textes = {}, [], []
        for inp in re.finditer(r'<input\b[^>]*>', corps, re.IGNORECASE):
            tag = inp.group(0)
            name_m = re.search(r'name=["\']([^"\']+)["\']', tag, re.IGNORECASE)
            if not name_m:
                continue
            name = name_m.group(1)
            type_m = re.search(r'type=["\']([^"\']+)["\']', tag, re.IGNORECASE)
            typ = (type_m.group(1) if type_m else "text").lower()
            val_m = re.search(r'value=["\']([^"\']*)["\']', tag, re.IGNORECASE)
            val = val_m.group(1) if val_m else ""
            if typ in ("hidden", "submit", "image"):
                champs[name] = val  # hidden (captcha[id]...) + submit (name=value)
            elif typ in ("text", "tel", "password", ""):
                if "captcha" in name.lower() or "captcharesult" in name.lower():
                    champs_captcha.append(name)
                else:
                    autres_textes.append(name)
        # Le form du captcha contient un champ dont le name mentionne 'captcha'.
        if not champs_captcha:
            continue
        # Réel Dematis : seul `captcha[input]` est soumis (pas `captchaResult`).
        # On privilégie les champs « input » s'il y en a.
        inputs_pref = [n for n in champs_captcha if "input" in n.lower()]
        if inputs_pref:
            champs_captcha = inputs_pref
        action_brut = (action_m.group(1) if action_m else "").replace("&amp;", "&")
        meilleur = {
            "action": urljoin(base_url, action_brut) if action_brut else base_url,
            "method": (method_m.group(1) if method_m else "post").lower(),
            "champs": champs,
            "champs_captcha": champs_captcha,
        }
        break  # 1er form portant un champ captcha = le bon
    return meilleur


def _normaliser_nom_mojibake(nom: str) -> str:
    """
    Répare un nom de fichier en MOJIBAKE (texte UTF-8 relu comme latin-1/cp1252) :
    'rÃ©seaux' → 'réseaux', 'RÃ¨glement' → 'Règlement'.

    Contexte Dematis : la page `acces_dce` mêle, selon les fichiers, des octets
    UTF-8 et des octets latin-1 bruts. Pour ne RIEN perdre, on décode la page en
    latin-1 (sans perte), ce qui transforme les accents d'origine UTF-8 en
    mojibake (ex. 'é' → 'Ã©') tout en gardant intacts les accents d'origine
    latin-1 (ex. 'è' resté 'è'). Cette fonction répare le mojibake et laisse les
    noms déjà corrects inchangés (idempotente). Les marqueurs 'Ã'/'Â' signalent
    le mojibake utf8-vu-comme-latin1 ; un nom sans eux est renvoyé tel quel.
    """
    if not nom:
        return nom
    # Itération : certains acheteurs ré-encodent les noms DEUX fois (mojibake
    # double, ex. 'mémoire' → 'mÃ©moire' → 'mÃƒÂ©moire'). On répare couche par
    # couche tant qu'un passage retire des marqueurs 'Ã'/'Â' (max 3 passes).
    for _ in range(3):
        if "Ã" not in nom and "Â" not in nom:
            break
        try:
            repare = nom.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            break  # mélange irréparable → on garde l'état courant
        # Garde-fou : ne valider que si la réparation retire des marqueurs
        # (sinon on casserait un nom légitimement porteur de 'Ã').
        if repare.count("Ã") + repare.count("Â") >= nom.count("Ã") + nom.count("Â"):
            break
        nom = repare
    return nom


def _decoder_liste_sans_perte(resp) -> str:
    """
    Décode le corps de la page `acces_dce` en latin-1 (chaque octet → 1 codepoint,
    JAMAIS de perte). Indispensable car la page mêle octets UTF-8 et latin-1 dans
    les noms de fichiers : un décodage UTF-8 « perdrait » les octets latin-1
    (caractère de remplacement irréversible). Les noms d'origine UTF-8 deviennent
    du mojibake récupérable, réparé ensuite par `_normaliser_nom_mojibake`.
    """
    contenu = getattr(resp, "content", None)
    if isinstance(contenu, (bytes, bytearray)) and contenu:
        try:
            return contenu.decode("latin-1")
        except Exception:
            pass
    return getattr(resp, "text", "") or ""


def _extraire_fichiers_telechargeables(html: str, base_url: str) -> list:
    """
    Liste [{label, url}] des pièces téléchargeables de la page `acces_dce`.

    Vérité HAR : les pièces sont servies par
    `https://private.e-marchespublics.com/dce/getfile.php?id=…&anonyme=…&fromnew`,
    le libellé de l'ancre portant le vrai nom de fichier (ex. « 03_CCAP.pdf »).
    On retient en PRIORITÉ ces liens `getfile.php` (canal réel) ; en leur absence
    on retombe sur l'heuristique générique (extension document OU mot-clé URL),
    ce qui évite d'aspirer les leurres de la page (« SE CONNECTER » →
    acces_membre_*, « Mot de passe oublié », etc.). Déduplique sur l'URL absolue.
    """
    if not html:
        return []
    import html as _h
    txt = _h.unescape(html)
    getfile, generiques, vus_g, vus_gen = [], [], set(), set()
    for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                         txt, re.IGNORECASE | re.DOTALL):
        href = (m.group(1) or "").replace("&amp;", "&").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        low = href.lower()
        chemin = urlparse(low).path
        url_abs = urljoin(base_url, href)
        label = (re.sub(r"<[^>]+>", " ", m.group(2)).strip()
                 or os.path.basename(chemin) or "piece")
        label = _normaliser_nom_mojibake(label)
        # Canal réel Dematis : getfile.php (priorité absolue).
        if "getfile.php" in low or "/dce/getfile" in low:
            if url_abs not in vus_g:
                vus_g.add(url_abs)
                getfile.append({"label": label[:160], "url": url_abs})
            continue
        # Repli heuristique (utilisé seulement si aucun getfile.php).
        est_doc = chemin.endswith(EXTENSIONS_DOC)
        est_motif = any(mot in low for mot in MOTIFS_URL_TELECHARGEMENT)
        if (est_doc or est_motif) and url_abs not in vus_gen:
            vus_gen.add(url_abs)
            generiques.append({"label": label[:160], "url": url_abs})
    return getfile if getfile else generiques


def _id_getfile(url: str) -> str:
    """Identifiant de la pièce (`id=` de getfile.php), pour tracer les doublons.
    Repli : l'URL complète si pas de paramètre id."""
    m = re.search(r"[?&]id=(\d+)", url or "")
    return m.group(1) if m else (url or "")


def _dedupliquer_fichiers(fichiers: list) -> tuple:
    """
    Dédoublonne la liste de pièces : le serveur Dematis liste parfois le MÊME
    fichier 2× sous des `id` getfile.php différents (cf RATP BOAMP-26-56469, où
    « Pièces écrites.zip » 325 Mo apparaît deux fois). On télécharge alors en
    double inutilement.

    Clé de dédup : (nom_normalisé.lower(), taille_estimée_si_dispo). La page
    acces_dce n'expose PAS de taille → `taille` vaut None en pratique, la dédup
    se fait donc par nom de fichier normalisé. On garde la PREMIÈRE occurrence.

    Retourne (uniques, doublons) où doublons = [{nom, ids_doublons}] (≥ 2 ids).
    """
    uniques, vus = [], {}
    for f in fichiers:
        nom = _normaliser_nom_mojibake(f.get("label", "") or "").strip().lower()
        cle = (nom, f.get("taille"))
        fid = _id_getfile(f.get("url", ""))
        if cle in vus:
            vus[cle]["ids"].append(fid)  # doublon : on ne le re-télécharge pas
            continue
        vus[cle] = {"nom": f.get("label"), "ids": [fid]}
        uniques.append(f)
    doublons = [{"nom": v["nom"], "ids_doublons": v["ids"]}
                for v in vus.values() if len(v["ids"]) > 1]
    return uniques, doublons


# ===========================================================================
# Workflow réseau
# ===========================================================================

def _nom_fichier(headers: dict, url: str, nom_suggere: str = "") -> str:
    """Nom de fichier : Content-Disposition > libellé du lien > basename URL.
    (L'URL Dematis `getfile.php?id=…` ne donne pas de nom exploitable → le
    libellé de l'ancre porte le vrai nom, ex. '03_CCAP.pdf'.)

    Le `Content-Disposition` de getfile.php porte souvent le nom en MOJIBAKE
    (requests décode les en-têtes en latin-1) → on applique systématiquement
    `_normaliser_nom_mojibake` au nom retenu, quelle que soit sa source."""
    cd = headers.get("Content-Disposition") or headers.get("content-disposition") or ""
    m = re.search(r'file[nN]ame\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd)
    if m and m.group(1).strip():
        return _sanitiser_nom(_normaliser_nom_mojibake(m.group(1)))
    if nom_suggere and "." in nom_suggere:
        return _sanitiser_nom(_normaliser_nom_mojibake(nom_suggere))
    return _sanitiser_nom(_normaliser_nom_mojibake(
        _nom_fichier_depuis_headers(headers, url, defaut="piece.bin")))


def _telecharger_fichier(session, url: str, dossier: str, timeout: int,
                          verbose: bool = False, nom_suggere: str = "",
                          verify: bool = True):
    """Télécharge une pièce (retry timeout/5xx). Retourne (ok, chemin, taille, err)."""
    derniere = ""
    for essai in range(1, DL_MAX_ESSAIS + 1):
        try:
            r = session.get(url, timeout=timeout, stream=True, allow_redirects=True,
                            verify=verify)
            code = getattr(r, "status_code", 0)
            if code >= 500:
                derniere = f"HTTP {code}"
                time.sleep(2 * essai)
                continue
            if code != 200:
                return False, None, 0, f"HTTP {code}"
            nom = _nom_fichier(getattr(r, "headers", {}) or {}, url, nom_suggere)
            chemin = os.path.join(dossier, nom)
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
                time.sleep(1)
                continue
            return True, chemin, taille, None
        except Exception as e:
            derniere = f"{type(e).__name__}: {e}"
            time.sleep(2 * essai)
    return False, None, 0, derniere or "échec"


def telecharger_dce(
    url_dce: str,
    dossier_destination: str,
    api_key_2captcha: Optional[str] = None,
    verbose: bool = True,
    timeout: int = 120,
    decompresser: bool = True,
    session_id: Optional[str] = None,
    verify_ssl: bool = True,
) -> dict:
    """
    Workflow anonyme complet de retrait du DCE Dematis, calé sur le HAR.

    Args:
        verify_ssl: vérification du certificat TLS. Laisser True par défaut.
            Workaround documenté (cf docstring module) : le bundle certifi du
            poste Windows manque l'intermédiaire CA de *.e-marchespublics.com
            → passer False PONCTUELLEMENT pour contourner (le bypass est alors
            journalisé via `ssl_verify_desactive`).

    Retourne {ok, fichiers_telecharges, taille_octets_total, dossier, erreur,
    duree_secondes, nb_captcha_resolus, etape_erreur, variante_lien,
    nb_zip_internes_decompressed, ssl_verify_desactive}.
    """
    debut = time.time()
    out = {"ok": False, "fichiers_telecharges": [], "taille_octets_total": 0,
           "dossier": dossier_destination, "erreur": None, "duree_secondes": 0.0,
           "nb_captcha_resolus": 0, "etape_erreur": None, "variante_lien": None,
           "nb_zip_internes_decompressed": 0,
           "ssl_verify_desactive": not verify_ssl}

    if not url_dce:
        out.update(erreur="URL DCE manquante", etape_erreur="session")
        return out
    api_key = api_key_2captcha or os.environ.get("TWOCAPTCHA_API_KEY")
    if not api_key:
        out.update(erreur="Clé 2captcha absente (TWOCAPTCHA_API_KEY)", etape_erreur="captcha")
        return out

    if not verify_ssl:
        # Bypass SSL ponctuel : on neutralise aussi l'avertissement urllib3 pour
        # ne pas polluer les logs (le bypass est tracé via ssl_verify_desactive).
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass
        if verbose:
            print("  [Dematis] ⚠ vérification SSL désactivée (workaround certifi/CA Windows)")

    session = http_humain.creer_session_humaine(session_id=session_id, plateforme="dematis")
    # Quirk Dematis : récupérer le PHPSESSID malgré le Domain= vide (sinon la
    # session PHP — qui porte la solution du captcha — est perdue).
    _installer_fix_cookies_domaine_vide(session)
    if verbose:
        print(f"  [Dematis] DCE {url_dce[:90]}")

    # ----- Étape 1 : page annonce -----
    try:
        r1 = _request_avec_retry(session, "GET", url_dce, timeout=timeout,
                                 allow_redirects=True, verify=verify_ssl)
        if getattr(r1, "encoding", None) in (None, "ISO-8859-1"):
            try:
                r1.encoding = "utf-8"  # piège connu : Dematis sert de l'UTF-8
            except Exception:
                pass
        if r1.status_code != 200:
            out.update(erreur=f"GET annonce HTTP {r1.status_code}", etape_erreur="session")
            return out
        html1, url1 = r1.text, getattr(r1, "url", url_dce)
    except Exception as e:
        out.update(erreur=f"GET annonce : {type(e).__name__}: {e}", etape_erreur="session")
        return out

    if http_humain.ressemble_a_page_ban(html1):
        out.update(erreur="Suspicion ban IP (page inattendue)", etape_erreur="ban_detecte")
        return out

    # ----- Étape 2 : liens d'accès anonyme candidats (page annonce + onglet) -----
    candidats = _extraire_liens_anonymes(html1, url1)
    if not candidats:
        url_dossier = _extraire_lien_onglet_dossier(html1, url1)
        if url_dossier:
            http_humain.attendre_inter_etapes(2, 4, verbose=verbose)
            try:
                r_d = _request_avec_retry(session, "GET", url_dossier, timeout=timeout,
                                          allow_redirects=True, headers={"Referer": url1},
                                          verify=verify_ssl)
                candidats = _extraire_liens_anonymes(r_d.text, getattr(r_d, "url", url_dossier))
            except Exception as e:
                out.update(erreur=f"GET onglet dossier : {type(e).__name__}: {e}",
                           etape_erreur="dossier")
                return out
    # Entrée directe : url_dce est DÉJÀ la page dossier/acces anonyme (elle porte
    # le token dans son chemin et expose un form captcha) → la page courante EST
    # le candidat, pas besoin de lien.
    if not candidats and (
            "_marche_public_anonyme_" in urlparse(url1).path.lower()
            or _extraire_form_captcha(html1, url1)):
        variante = ("acces_dce" if "acces_dce_marche_public_anonyme" in url1.lower()
                    else "dossier_de_consultation")
        candidats = [(url1, variante)]
    if not candidats:
        out.update(erreur="Lien d'accès anonyme introuvable", etape_erreur="dossier")
        return out
    if verbose:
        print(f"    {len(candidats)} lien(s) anonyme(s) candidat(s)")

    # ----- Étapes 3-4 : page dossier → captcha → POST → 302 acces_dce (HAR) -----
    # Workflow HAR strict :
    #   GET  /dossier_de_consultation_marche_public_anonyme_<token40>   → 200 captcha
    #   POST (même URL) captcha[id]+captcha[input]+submit               → 302
    #   Location: /acces_dce_marche_public_anonyme_<token40>            → GET → liste
    # Le captcha (id + image) est régénéré à chaque chargement de la page dossier :
    # on re-GET la page à chaque tentative. Un mauvais token redirige vers
    # l'accueil (path '/') ; un captcha refusé renvoie 200 (re-render), pas de 302.
    html_liste = url3_liste = None
    erreur_captcha = "aucun lien anonyme valide (tous redirigent vers l'accueil)"
    for lien_anonyme, variante in candidats:
        if html_liste is not None:
            break
        http_humain.attendre_inter_etapes(2, 5, verbose=verbose)
        for tentative in range(1, TWOCAPTCHA_MAX_TENTATIVES + 1):
            # --- GET page dossier (captcha frais) ---
            try:
                r3 = _request_avec_retry(session, "GET", lien_anonyme, timeout=timeout,
                                         allow_redirects=True, headers={"Referer": url1},
                                         verify=verify_ssl)
                if getattr(r3, "encoding", None) in (None, "ISO-8859-1"):
                    try:
                        r3.encoding = "utf-8"
                    except Exception:
                        pass
                html3, url3 = r3.text, getattr(r3, "url", lien_anonyme)
            except Exception as e:
                erreur_captcha = f"GET page anonyme : {type(e).__name__}: {e}"
                break

            # Candidat invalide : redirigé vers la racine (accueil).
            if urlparse(url3).path.strip("/") == "":
                erreur_captcha = "lien anonyme invalide (redirigé vers l'accueil)"
                break

            form = _extraire_form_captcha(html3, url3)
            img_url = _extraire_captcha_img(html3, url3)
            if not form or not img_url:
                # Cas dégénéré : la page expose déjà la liste (pas de captcha).
                html3_liste = _decoder_liste_sans_perte(r3)
                fichiers_directs = _extraire_fichiers_telechargeables(html3_liste, url3)
                if fichiers_directs:
                    html_liste, url3_liste = html3_liste, url3
                    out["variante_lien"] = variante
                    break
                erreur_captcha = "formulaire captcha ou image introuvable"
                break

            # --- image captcha + résolution 2captcha ---
            try:
                r_img = _request_avec_retry(session, "GET", img_url, timeout=timeout,
                                            headers={"Referer": url3}, verify=verify_ssl)
                image_bytes = getattr(r_img, "content", b"")
            except Exception as e:
                erreur_captcha = f"GET image captcha : {type(e).__name__}: {e}"
                break

            if verbose:
                print(f"    [captcha {tentative}/{TWOCAPTCHA_MAX_TENTATIVES}] ({variante}) résolution 2captcha...")
            try:
                solution = _resoudre_captcha_2captcha(image_bytes, api_key, verbose=verbose)
            except ErreurSolde2Captcha as e:
                out.update(erreur=f"2captcha solde épuisé : {e}", etape_erreur="captcha",
                           solde_2captcha_epuise=True)
                return out
            if not solution:
                continue
            out["nb_captcha_resolus"] += 1

            # --- POST captcha sur la MÊME URL, SANS suivre la redirection ---
            # On envoie exactement les champs du form (captcha[id], captcha[input],
            # submit) — le champ leurre `captchaResult` est volontairement exclu
            # par _extraire_form_captcha.
            payload = dict(form["champs"])
            for champ in form["champs_captcha"]:
                payload[champ] = solution
            http_humain.attendre_inter_etapes(1, 3, verbose=verbose)
            try:
                if form["method"] == "get":
                    r4 = _request_avec_retry(session, "GET", form["action"], params=payload,
                                             timeout=timeout, allow_redirects=False,
                                             headers={"Referer": url3}, verify=verify_ssl)
                else:
                    r4 = _request_avec_retry(session, "POST", form["action"], data=payload,
                                             timeout=timeout, allow_redirects=False,
                                             headers={"Referer": url3}, verify=verify_ssl)
            except Exception as e:
                erreur_captcha = f"POST captcha : {type(e).__name__}: {e}"
                break

            code4 = getattr(r4, "status_code", 0)
            location = ""
            try:
                location = (r4.headers.get("Location")
                            or r4.headers.get("location") or "")
            except Exception:
                location = ""

            # Succès HAR = 302 vers /acces_dce_marche_public_anonyme_<token40>.
            if code4 in (301, 302, 303, 307, 308) and "acces_dce_marche_public_anonyme" in location.lower():
                url_acces = urljoin(url3, location)
                http_humain.attendre_inter_etapes(1, 3, verbose=verbose)
                try:
                    r5 = _request_avec_retry(session, "GET", url_acces, timeout=timeout,
                                             allow_redirects=True, headers={"Referer": url3},
                                             verify=verify_ssl)
                    # Décodage latin-1 sans perte (noms de fichiers mixtes UTF-8/
                    # latin-1) ; le mojibake est réparé par _normaliser_nom_mojibake.
                    html_liste = _decoder_liste_sans_perte(r5)
                    url3_liste = getattr(r5, "url", url_acces)
                    out["variante_lien"] = "acces_dce"
                except Exception as e:
                    erreur_captcha = f"GET acces_dce : {type(e).__name__}: {e}"
                break

            # Repli tolérant : certaines variantes renvoient 200 avec la liste
            # directement (pas de redirection). On accepte si des getfile.php y sont.
            if code4 == 200:
                html4 = _decoder_liste_sans_perte(r4)
                url4 = getattr(r4, "url", form["action"])
                fichiers = _extraire_fichiers_telechargeables(html4, url4)
                if fichiers:
                    html_liste, url3_liste = html4, url4
                    out["variante_lien"] = variante
                    break

            if verbose:
                print(f"        captcha refusé (HTTP {code4}, pas de 302 acces_dce), on retente")

    if html_liste is None:
        out.update(erreur=f"Captcha non validé : {erreur_captcha}", etape_erreur="captcha")
        return out

    # ----- Étape 5 : liste des fichiers → dédoublonnage → téléchargement -----
    ressources_brutes = _extraire_fichiers_telechargeables(html_liste, url3_liste)
    if not ressources_brutes:
        out.update(erreur="Aucune pièce listée après déverrouillage", etape_erreur="fichiers")
        return out
    ressources, doublons = _dedupliquer_fichiers(ressources_brutes)
    out["doublons"] = doublons
    out["nb_doublons_ecartes"] = len(ressources_brutes) - len(ressources)
    if verbose:
        if doublons:
            print(f"    {out['nb_doublons_ecartes']} doublon(s) serveur écarté(s) : "
                  + ", ".join(d["nom"] for d in doublons))
        print(f"    {len(ressources)} pièce(s) à télécharger")

    os.makedirs(dossier_destination, exist_ok=True)
    fichiers, taille_totale, erreurs_dl = [], 0, []
    for i, res in enumerate(ressources, 1):
        ok_f, chemin_f, taille_f, err_f = _telecharger_fichier(
            session, res["url"], dossier_destination, timeout, verbose=verbose,
            nom_suggere=res.get("label", ""), verify=verify_ssl)
        if ok_f:
            fichiers.append(chemin_f)
            taille_totale += taille_f
            if verbose:
                print(f"        ✓ [{i}/{len(ressources)}] {os.path.basename(chemin_f)} ({taille_f:,} o)")
        else:
            erreurs_dl.append(f"{res['label']}: {err_f}")
        if i < len(ressources):
            time.sleep(RATE_LIMIT_FICHIERS_SEC)

    if not fichiers:
        out.update(erreur="Aucun fichier téléchargé : " + "; ".join(erreurs_dl[:3]),
                   etape_erreur="dl", duree_secondes=round(time.time() - debut, 2))
        return out

    # ----- Étape 6 : décompression des ZIP imbriqués -----
    if decompresser:
        for chemin_f in list(fichiers):
            if chemin_f.lower().endswith(".zip"):
                try:
                    res_dec = _decompresser_zip_imbrique(chemin_f, dossier_destination,
                                                         verbose=verbose)
                    out["nb_zip_internes_decompressed"] += res_dec.get(
                        "nb_zip_internes_decompressed", 0)
                except Exception as e:
                    if verbose:
                        print(f"        décompression {os.path.basename(chemin_f)} échouée : {e}")

    out.update(ok=True, fichiers_telecharges=fichiers, taille_octets_total=taille_totale,
               duree_secondes=round(time.time() - debut, 2))
    if erreurs_dl:
        out["erreurs_non_critiques"] = erreurs_dl[:5]
    if verbose:
        print(f"  [Dematis] ✅ {len(fichiers)} fichier(s), {taille_totale:,} o, {out['duree_secondes']}s")
    return out


def telecharger_dce_pour_marche(
    marche: dict,
    repertoire_dce: str,
    api_key_2captcha: Optional[str] = None,
    verbose: bool = True,
    max_retries_ban: int = 2,
    verify_ssl: bool = True,
) -> dict:
    """
    Wrapper : télécharge le DCE Dematis d'un marché dans <repertoire_dce>/<id>/.
    Idempotent (skip si fichiers déjà présents), rotation d'IP sur ban, logs JSONL.
    `verify_ssl` : cf telecharger_dce (workaround certifi/CA Windows ponctuel).
    """
    id_marche = marche.get("id", "?")
    url_dce = marche.get("url_dce")
    out = {"id_marche": id_marche, "ok": False, "skip": False, "erreur": None,
           "chemin": None, "duree_secondes": 0.0, "taille_octets": 0}

    if not url_dce or not est_url_dematis(url_dce):
        out["erreur"] = "URL DCE absente ou non-Dematis"
        return out

    dossier_cible = os.path.join(repertoire_dce, id_marche)
    if os.path.isdir(dossier_cible):
        utiles = [f for f in os.listdir(dossier_cible)
                  if os.path.isfile(os.path.join(dossier_cible, f))
                  and not f.lower().endswith((".bak", ".tmp", ".xml"))]
        if utiles:
            out.update(ok=True, skip=True, chemin=dossier_cible)
            tendia_logs.logger_evenement_marche("dematis", id_marche,
                                                {"ok": True, "skip": True})
            return out

    res, tentatives_ip = {}, 0
    for tentative in range(max_retries_ban + 1):
        session_id = id_marche if tentative == 0 else uuid.uuid4().hex[:8]
        tentatives_ip = tentative + 1
        if tentative > 0 and verbose:
            print(f"    [retry IP {tentative}/{max_retries_ban}] session-id {session_id}")
        try:
            res = telecharger_dce(url_dce, dossier_cible,
                                  api_key_2captcha=api_key_2captcha,
                                  verbose=verbose, session_id=session_id,
                                  verify_ssl=verify_ssl)
        except Exception as e:
            res = {"ok": False, "erreur": f"{type(e).__name__}: {e}",
                   "etape_erreur": "exception"}
        if res.get("etape_erreur") != "ban_detecte":
            break
    else:
        res["etape_erreur"] = "ban_persistant"
        res["erreur"] = f"Ban persistant après {max_retries_ban} rotations d'IP"

    out.update(res)
    out["id_marche"] = id_marche
    out["chemin"] = dossier_cible
    out["taille_octets"] = res.get("taille_octets_total", 0)
    out["tentatives_ip"] = tentatives_ip
    # Expose nb_fichiers dans le retour (le batch/qualif n'en dépend pas, mais le
    # dict ne le portait pas → reporting trompeur « nb_fichiers=None »).
    out["nb_fichiers"] = len(out.get("fichiers_telecharges") or [])

    evt = {
        "ok": out.get("ok"),
        "etape_erreur": out.get("etape_erreur"),
        "erreur": (out.get("erreur") or "")[:200],
        "nb_fichiers": len(res.get("fichiers_telecharges") or []),
        "taille_octets": out.get("taille_octets", 0),
        "nb_captcha_resolus": res.get("nb_captcha_resolus", 0),
        "variante_lien": res.get("variante_lien"),
        "tentatives_ip": tentatives_ip,
        "duree_secondes": res.get("duree_secondes", 0.0),
        "nb_doublons_ecartes": res.get("nb_doublons_ecartes", 0),
    }
    # Trace explicite des doublons serveur écartés (nom + ids getfile.php).
    for d in (res.get("doublons") or []):
        tendia_logs.logger_evenement_marche("dematis", id_marche, {
            "doublon_detecte": {"nom": d.get("nom"),
                                "ids_doublons": d.get("ids_doublons")},
        })
    tendia_logs.logger_evenement_marche("dematis", id_marche, evt)
    return out


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = [a for a in sys.argv[1:] if a != "--no-verify-ssl"]
    verify_ssl = "--no-verify-ssl" not in sys.argv
    if not args:
        print("Usage : python dematis_downloader.py <url_dce> [dossier_destination] [--no-verify-ssl]")
        sys.exit(1)
    url_arg = args[0]
    dossier = args[1] if len(args) > 1 else "data/test_dematis"
    r = telecharger_dce(url_arg, dossier, verbose=True, verify_ssl=verify_ssl)
    print("\nRésultat :", {k: v for k, v in r.items() if k != "fichiers_telecharges"})
    for f in r.get("fichiers_telecharges", []):
        print("  -", f)
