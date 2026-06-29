"""
resolution_reference.py
-----------------------
Résout l'`url_dce` des avis qui n'ont PAS de lien direct dans la donnée BOAMP,
en exploitant deux champs présents dans le raw avis :
  - `urlProfilAch` / `cbc:URI` : le SITE de la plateforme (homepage)
  - `identifiantInterne`       : la RÉFÉRENCE acheteur de la consultation

Sur les moteurs Atexo (marques blanches), une recherche anonyme par référence
(`_chercher_url_dce_via_atexo`) retrouve la consultation → on en déduit l'url_dce.
L'accès est anonyme (garanti réglementairement pour les marchés publics).

Helpers réutilisables + chaîne testable :
    extraire_plateforme_reference(marche) -> (base, reference)
    resoudre_url_via_reference(marche)     -> url_dce | None
"""
import json
import re
from typing import Optional

import requests
import dce_finder

# Moteurs Atexo (marques blanches + PLACE) où la recherche GET fonctionne.
HOSTS_ATEXO_SEARCH = (
    "marches-publics.gouv", "megalis", "demat-ampa", "ternum", "maximilien",
    "596280", "marchespublics.eure", "marchespublics.ain", "alsacemarchespublics",
    "marchespublics.aude", "nantesmetropole", "adullact", "marches.rhone",
    "auvergnerhonealpes", "muretain", "sictiam", "profilacheteur", "agglo-muretain",
    "ternum-bfc", "marches.rennes",
)

# Hôtes de plateformes DCE connus (au-delà des moteurs Atexo) : sert à récupérer
# la plateforme citée DANS LE CORPS de l'avis quand urlProfilAch est absent. La
# plateforme est presque toujours mentionnée (URL en clair, section communication).
HOSTS_PLATEFORMES = HOSTS_ATEXO_SEARCH + (
    "marches-publics.info", "aws-achat", "e-marchespublics", "achatpublic",
    "marches-securises", "klekoon", "safetender", "demat", "marchesonline",
    "synapse-entreprises", "agysoft", "recia", "mpe7", "local-trust",
    "centraledesmarches", "marchespublics.",
)

# Le raw avis est une chaîne JSON échappée → on tolère le `\"`.
_RE_PROFIL = re.compile(r'urlProfilAch\\?"\s*:\s*\\?"([^"\\]+)')
_RE_URI = re.compile(r'cbc:URI[^h]{0,40}(https?://[^"\\ ]+)', re.I)
_RE_REF = re.compile(r'identifiantInterne\\?"\s*:\s*\\?"([^"\\]+)')
_RE_URL = re.compile(r'https?://[A-Za-z0-9._~:/?#@!$&()*+,;=%-]+')
_RE_CONSULT = re.compile(
    r'(consultation|detailconsultation|idm?=|fuseaction=dematent|refconsultation)', re.I)
_EXCLURE_URL = ("boamp", "journal-officiel", "data.gouv", "europa.eu")


def _urls_plateforme(t: str):
    """URLs de plateformes DCE connues présentes dans le raw (hors BOAMP/JO)."""
    out = []
    for u in _RE_URL.findall((t or "").replace("\\/", "/")):
        u = u.rstrip('",\\')
        ul = u.lower()
        if any(x in ul for x in _EXCLURE_URL):
            continue
        if any(h in ul for h in HOSTS_PLATEFORMES):
            out.append(u)
    return out


def extraire_url_consultation(marche: dict):
    """URL de consultation DIRECTE (plateforme connue + motif consultation) citée
    dans le raw de l'avis, utilisable telle quelle comme url_dce, ou None."""
    brut = marche.get("donnees_boamp_brut")
    t = brut if isinstance(brut, str) else json.dumps(brut, ensure_ascii=False)
    for u in _urls_plateforme(t):
        if _RE_CONSULT.search(u):
            return u
    return None


def extraire_plateforme_reference(marche: dict):
    """Retourne (base_plateforme, reference) depuis le raw avis, ou (None, None).
    Si `urlProfilAch`/`cbc:URI` sont absents, on retombe sur l'ORIGINE (scheme+host)
    de la 1re URL de plateforme connue citée dans le corps de l'avis."""
    from urllib.parse import urlsplit
    brut = marche.get("donnees_boamp_brut")
    t = brut if isinstance(brut, str) else json.dumps(brut, ensure_ascii=False)
    mp = _RE_PROFIL.search(t) or _RE_URI.search(t)
    base = mp.group(1).rstrip("/") if mp else None
    if not base:
        urls = _urls_plateforme(t)
        if urls:
            sp = urlsplit(urls[0])
            base = f"{sp.scheme}://{sp.netloc}" if sp.netloc else None
    mr = _RE_REF.search(t)
    ref = (mr.group(1).strip() if mr else None) or None
    return base, ref


def est_moteur_atexo(base: str) -> bool:
    return any(h in (base or "").lower() for h in HOSTS_ATEXO_SEARCH)


def normaliser_base(base: str) -> str:
    """Corrige les `urlProfilAch` mal formés (sous-domaine/point manquants) vers
    l'hôte de recherche canonique. Sinon la recherche échoue à tort."""
    low = (base or "").lower()
    if "megalis" in low:               # www.megalis / megalisbretagne (sans point)…
        return "https://marches.megalis.bretagne.bzh"
    return base


def resoudre_url_via_reference(marche: dict) -> Optional[str]:
    """Cherche l'url_dce d'un avis sans lien direct via plateforme + référence.
    Phase 1 : moteurs Atexo uniquement (recherche GET prouvée)."""
    base, ref = extraire_plateforme_reference(marche)
    if not (base and ref and est_moteur_atexo(base)):
        return None
    try:
        return dce_finder._chercher_url_dce_via_atexo(ref, normaliser_base(base),
                                                      verbose=False)
    except Exception:
        return None


try:
    import truststore as _truststore
    _truststore.inject_into_ssl()
except Exception:
    pass

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
# Ancien format Atexo (Prado) et NOUVEAU format (PLACE v2 / marques blanches
# récentes : /entreprise/consultation/<id>?orgAcronyme=<org>).
_RE_DETAIL = re.compile(r"EntrepriseDetailsConsultation[^\"']*id=(\d+)[^\"']*orgAcronyme=(\w+)")
_RE_DETAIL_NEW = re.compile(r"/entreprise/consultation/(\d+)\?orgAcronyme=(\w+)")


def _chercher_consultations(base: str, keyword: str) -> list:
    """Liste des URLs de consultation uniques pour une recherche keyword (Atexo /
    PLACE). Gère l'ancien format Prado ET le nouveau /entreprise/consultation/."""
    base = base.rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base
    url = (f"{base}/?page=Entreprise.EntrepriseAdvancedSearch&searchAnnCons"
           f"&keyWord={requests.utils.quote(keyword)}")
    try:
        h = requests.get(url, timeout=25, headers={"User-Agent": _UA,
                         "Accept-Language": "fr-FR"}).text.replace("&amp;", "&")
    except Exception:
        return []
    vus, out = set(), []
    for mid_, org in _RE_DETAIL.findall(h):
        if mid_ not in vus:
            vus.add(mid_)
            out.append(f"{base}/?page=Entreprise.EntrepriseDetailsConsultation"
                       f"&id={mid_}&orgAcronyme={org}")
    for mid_, org in _RE_DETAIL_NEW.findall(h):
        if mid_ not in vus:
            vus.add(mid_)
            out.append(f"{base}/entreprise/consultation/{mid_}?orgAcronyme={org}")
    return out


def _mots_cles_objet(objet: str, n: int = 3) -> str:
    mots = [w for w in re.findall(r"[A-Za-zÀ-ÿ]{5,}", objet or "")
            if w.lower() not in ("marche", "marché", "public", "prestation",
                                 "prestations", "travaux", "fourniture", "service",
                                 "services", "consultation")][:n]
    return " ".join(mots)


def resoudre_url_via_objet(marche: dict) -> Optional[str]:
    """Fallback recherche par mots-clés d'OBJET sur Atexo/PLACE. CONSERVATEUR :
    ne résout que si la recherche renvoie UN SEUL résultat (haute confiance), pour
    éviter d'attacher un mauvais DCE. Tenté même si une référence existe : sur
    PLACE la recherche par référence échoue (réf BOAMP non indexée)."""
    base, ref = extraire_plateforme_reference(marche)
    if not (base and est_moteur_atexo(base)):
        return None
    kw = _mots_cles_objet(marche.get("objet") or "")
    if len(kw) < 6:
        return None
    res = _chercher_consultations(normaliser_base(base), kw)
    return res[0] if len(res) == 1 else None
