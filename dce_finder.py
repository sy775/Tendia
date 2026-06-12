"""
dce_finder.py v3
-----------------
Extraction directe de l'URL DCE depuis les champs eForms BOAMP.

DÉCOUVERTE : le champ eForms qui contient l'URL DCE est :
  donnees.EFORMS.ContractNotice.cac:TenderingTerms
        .cac:CallForTendersDocumentReference
        .cac:Attachment.cac:ExternalReference.cbc:URI

Pour les marchés où l'acheteur a correctement rempli le champ
(~30% en pratique), c'est l'URL DCE spécifique :
   https://www.marches-publics.gouv.fr/?page=...&id=2981873&orgAcronyme=h8j

Pour les autres (~70%), c'est juste l'URL racine de PLACE. Dans ce cas
on retombe sur l'URL de recherche PLACE pré-remplie avec la référence.

Pour TED v3, l'API est plus complexe (1830 champs valides, requête à
optimiser). On la traite séparément avec les champs corrects identifiés
en diagnostic : document-url-lot, document-url-part, buyer-profile.
"""

import json
import re
from typing import Optional, List, Dict

import requests

from http_utils import get_json, post_json


URL_PLACE_RECHERCHE = (
    "https://www.marches-publics.gouv.fr/"
    "?page=Entreprise.EntrepriseAdvancedSearch&AllCons&refConsultation={ref}"
)


# ---------------------------------------------------------------------------
# Récupération + parsing du record BOAMP
# ---------------------------------------------------------------------------

def _fetch_record_boamp(idweb: str) -> Optional[dict]:
    """Récupère le record COMPLET d'un avis BOAMP via l'API Opendatasoft."""
    url = ("https://boamp-datadila.opendatasoft.com/api/explore/v2.1/"
           "catalog/datasets/boamp/records")
    params = {"where": f'idweb="{idweb}"', "limit": 1}
    try:
        reponse = get_json(url, params=params, verbose=False)
    except Exception:
        return None
    results = reponse.get("results") or []
    return results[0] if results else None


def _parser_donnees(record: dict) -> dict:
    """Le champ 'donnees' est un JSON string imbriqué. On le parse."""
    donnees = record.get("donnees")
    if isinstance(donnees, str):
        try:
            return json.loads(donnees)
        except json.JSONDecodeError:
            return {}
    return donnees or {}


def _get_chemin(obj, chemin: List[str]):
    """Navigue dans un dict imbriqué via une liste de clés. None si absent."""
    cur = obj
    for cle in chemin:
        if isinstance(cur, dict) and cle in cur:
            cur = cur[cle]
        else:
            return None
    return cur


def _est_url_specifique(url: str) -> bool:
    """
    Détermine si une URL PLACE est SPÉCIFIQUE (mène à une consultation
    précise) ou GÉNÉRIQUE (juste la racine du site).

    Critères de spécificité : présence d'un id= ou d'un paramètre significatif.
    """
    if not url:
        return False
    url_low = url.lower()
    # Présence d'un id de consultation
    if re.search(r"(?:[?&])(?:id|idconsultation|refconsultation)=\w+",
                  url_low):
        return True
    # Path significatif (au-delà de "/" ou "/entreprise")
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        query = parsed.query
        if query and len(query) >= 10:
            return True
        # Path qui n'est pas juste "entreprise" ou vide
        if path and path not in ("entreprise", "fr", "fr/entreprise"):
            return True
    except Exception:
        pass
    return False


# Domaines connus de plateformes de marchés publics françaises. Utilisé pour
# filtrer les URLs trouvées récursivement dans le payload eForms : on garde
# uniquement celles qui pointent vers une vraie plateforme de marchés.
DOMAINES_PLATEFORMES_MP = (
    "marches-publics.gouv.fr",
    "marches-publics.info",
    "achatpublic.com",
    "e-marchespublics.com",
    "marchespublics.com",
    "marchespublics-",
    "marchespublics.",
    "demat-ampa.fr",
    "klekoon.com",
    "marches.maximilien.fr",
    "marches.ternum-bfc.fr",
    "marchespublics.nantesmetropole.fr",
    "marchespublics596280.fr",
    "profilacheteur.",
    "mpe.",
    "webmarche.adullact.org",
    "xmarches.fr",
    "marches-securises.fr",
    "marches.megalis",
    "megalis.bretagne.bzh",
    "mairie-",
    "departement",
    "region-",
    "metropole.",
    "ville-",
    "musee-",
    "publication.marchesonline.com",
    "achatpublic",
    # Ajouts Phase 4 : communautés d'agglo + sous-domaines marches.*
    "agglo-",
    "marches.",
)


def _domaine_est_plateforme_mp(url: str) -> bool:
    """True si le netloc de l'URL semble être une plateforme de marchés publics."""
    if not url:
        return False
    try:
        from urllib.parse import urlparse
        netloc = urlparse(url).netloc.lower()
    except Exception:
        return False
    return any(pat in netloc for pat in DOMAINES_PLATEFORMES_MP)


def _chercher_urls_dans_eforms(obj, max_profondeur: int = 12) -> list:
    """
    Parcourt récursivement un objet (dict/list) et retourne toutes les
    URLs string trouvées qui ressemblent à des liens de plateforme de
    marchés publics.
    """
    urls = []

    def _visiter(o, profondeur):
        if profondeur > max_profondeur:
            return
        if isinstance(o, str):
            if o.startswith(("http://", "https://")):
                if _domaine_est_plateforme_mp(o):
                    urls.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                _visiter(v, profondeur + 1)
        elif isinstance(o, list):
            for elt in o:
                _visiter(elt, profondeur + 1)

    _visiter(obj, 0)
    return urls


# ---------------------------------------------------------------------------
# Extraction pour BOAMP
# ---------------------------------------------------------------------------

def _extraire_uri_lot(lot: dict) -> Optional[str]:
    """Extrait l'URI du DCE depuis un objet 'lot' eForms."""
    if not isinstance(lot, dict):
        return None
    return _get_chemin(lot, [
        "cac:TenderingTerms",
        "cac:CallForTendersDocumentReference",
        "cac:Attachment",
        "cac:ExternalReference",
        "cbc:URI",
    ])


def _extraire_reference_ft(donnees: dict) -> Optional[str]:
    """
    Extrait la référence INTERNE de l'acheteur (côté agent / PLACE)
    depuis le champ eForms cac:ProcurementProject.cbc:ID.

    Format typique : "2604-DRFT-NA-FOP-108" (ancien format France Travail)
    ou "009-26" (formats variés selon l'acheteur).
    Le champ peut être soit une string directe, soit un dict
    {"@schemeName": "InternalID", "#text": "2604-DRFT-NA-FOP-108"}.

    Note : le nom de fonction garde le suffixe `_ft` pour compatibilité
    historique avec le reste de la base de code (le champ persisté en
    base s'appelle aussi `reference_ft`). Ce nom n'apparaît pas dans
    les briefs utilisateur.
    """
    pp = _get_chemin(donnees, [
        "EFORMS", "ContractNotice", "cac:ProcurementProject",
    ])
    if not isinstance(pp, dict):
        return None
    ref = pp.get("cbc:ID")
    if isinstance(ref, str):
        return ref.strip()
    if isinstance(ref, dict):
        # Forme {"@schemeName": "InternalID", "#text": "..."}
        texte = ref.get("#text")
        if isinstance(texte, str):
            return texte.strip()
    return None


def _chercher_url_dce_via_atexo(reference_acheteur: str,
                                 base_url: str,
                                 verbose: bool = False) -> Optional[str]:
    """
    Cherche l'URL DCE spécifique sur une plateforme Atexo (PLACE et marques
    blanches : marches.megalis.bretagne.bzh, marches.maximilien.fr,
    marches.ternum-bfc.fr, demat-ampa.fr, marches-publics.info, etc.).

    Toutes ces plateformes utilisent le même moteur MPE/Atexo, donc la même
    URL de recherche `?page=Entreprise.EntrepriseAdvancedSearch&keyWord=`
    et les mêmes liens `EntrepriseDetailsConsultation&id=XXX&orgAcronyme=YYY`.

    Args:
        reference_acheteur: la référence interne acheteur (typiquement extraite
            via _extraire_reference_ft, mais peut venir de n'importe quel
            cac:ProcurementProject.cbc:ID).
        base_url: URL racine de la plateforme (ex: "https://marches.megalis.bretagne.bzh").
        verbose: log debug.

    Returns:
        URL DCE complète avec id=XXX&orgAcronyme=YYY, ou None si introuvable.
    """
    import requests
    if not reference_acheteur or not base_url:
        return None

    # Normalisation base_url : pas de trailing slash, garde le schéma
    base_url = base_url.rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        base_url = "https://" + base_url

    url_recherche = (
        f"{base_url}/"
        "?page=Entreprise.EntrepriseAdvancedSearch"
        f"&searchAnnCons&keyWord={reference_acheteur}"
    )
    try:
        r = requests.get(
            url_recherche, timeout=20, allow_redirects=True,
            headers={
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/120.0.0.0 Safari/537.36"),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "fr-FR,fr;q=0.9",
            },
        )
        if r.status_code != 200:
            if verbose:
                print(f"    Atexo keyWord HTTP {r.status_code} sur {base_url}")
            return None
        html = r.text.replace("&amp;", "&")

        def _normaliser_url(u: str) -> str:
            if u.startswith(("http://", "https://")):
                return u
            if u.startswith("/"):
                return base_url + u
            return base_url + "/" + u.lstrip("./")

        # Priorité 1 : lien EntrepriseDetailsConsultation
        matches = re.findall(
            r'href=["\']([^"\']*EntrepriseDetailsConsultation'
            r'[^"\']*id=\d+[^"\']*orgAcronyme=\w+[^"\']*)["\']',
            html, re.IGNORECASE
        )
        if matches:
            return _normaliser_url(matches[0])

        # Priorité 2 : tout lien avec id=NNN&orgAcronyme=
        matches2 = re.findall(
            r'[?&]id=(\d+)[^"\']*orgAcronyme=(\w+)',
            html
        )
        if matches2:
            id_consultation, org = matches2[0]
            return (f"{base_url}/"
                    f"?page=Entreprise.EntrepriseDetailsConsultation"
                    f"&id={id_consultation}&orgAcronyme={org}")

        # Priorité 3 : nouveau format Atexo /entreprise/consultation/NNN?orgAcronyme=
        matches3 = re.findall(
            r'href=["\']([^"\']*/entreprise/consultation/\d+[^"\']*'
            r'orgAcronyme=\w+[^"\']*)["\']',
            html, re.IGNORECASE
        )
        if matches3:
            return _normaliser_url(matches3[0])

        if verbose:
            print(f"    Atexo keyWord '{reference_acheteur}' sur {base_url} : "
                  f"aucun id trouvé")
        return None
    except Exception as e:
        if verbose:
            print(f"    Erreur Atexo keyWord ({base_url}) : {e}")
        return None


def _chercher_url_dce_via_place(reference_ft: str,
                                  verbose: bool = False) -> Optional[str]:
    """
    Alias historique : recherche sur PLACE (`marches-publics.gouv.fr`).
    Conservé pour compatibilité ascendante. Pour les autres plateformes
    Atexo blanche, utiliser `_chercher_url_dce_via_atexo()` directement avec
    leur base_url.
    """
    return _chercher_url_dce_via_atexo(
        reference_ft,
        "https://www.marches-publics.gouv.fr",
        verbose=verbose,
    )


def _extraire_dce_boamp(record: dict, reference: str) -> Dict:
    """
    Extrait les infos DCE depuis un record BOAMP.

    Stratégie en cascade :
    1. Si cac:CallForTendersDocumentReference.cbc:URI contient une URL spécifique
       (avec id=XXX) → on l'utilise directement.
    2. Sinon, si on a la référence interne FT (cac:ProcurementProject.cbc:ID),
       on cherche sur PLACE par keyWord → récupère l'URL spécifique.
    3. Sinon, fallback URL de recherche pré-remplie.

    Returns:
        {
          "url_dce": str | None,
          "url_recherche": str,
          "qualite": "directe" | "via_keyword" | "racine" | "absente",
          "buyer_profile": str | None,
          "champ_source": str,
          "reference_ft": str | None,
        }
    """
    donnees = _parser_donnees(record)
    out: Dict = {
        "url_dce": None,
        "url_recherche": URL_PLACE_RECHERCHE.format(ref=reference),
        "qualite": "absente",
        "buyer_profile": None,
        "champ_source": None,
        "reference_ft": None,
    }

    # Buyer profile
    buyer_profile = _get_chemin(donnees, [
        "EFORMS", "ContractNotice",
        "cac:ContractingParty",
        "cbc:BuyerProfileURI",
    ])
    if buyer_profile:
        out["buyer_profile"] = buyer_profile

    # Référence interne acheteur (utile pour la recherche par mot-clé Atexo)
    reference_ft = _extraire_reference_ft(donnees)
    if reference_ft:
        out["reference_ft"] = reference_ft

    # Récupère le(s) lot(s) pour chercher l'URL DCE eForms
    lot_data = _get_chemin(donnees, [
        "EFORMS", "ContractNotice",
        "cac:ProcurementProjectLot",
    ])
    lots = []
    if isinstance(lot_data, dict):
        lots = [lot_data]
    elif isinstance(lot_data, list):
        lots = lot_data

    uris_trouvees = []
    for lot in lots:
        uri = _extraire_uri_lot(lot)
        if uri:
            uris_trouvees.append(uri)

    # === Niveau 1 : URL spécifique dans eForms (chemin standard UBL) ===
    for uri in uris_trouvees:
        if _est_url_specifique(uri):
            out["url_dce"] = uri
            out["qualite"] = "directe"
            out["champ_source"] = "cac:CallForTendersDocumentReference"
            return out

    # === Niveau 1bis : recherche récursive dans tout le payload eForms ===
    # Pour les marchés où le chemin UBL standard n'a rien donné, on cherche
    # toute URL qui pointe vers une plateforme de marchés publics connue.
    # Couvre les cas où l'URL DCE est dans un champ non standard (BuyerProfileURI,
    # EndpointID, etc.) ou imbriquée différemment selon la plateforme.
    urls_eforms = _chercher_urls_dans_eforms(donnees)
    # Garde uniquement celles qui sont "spécifiques" (avec id=, etc.) — sinon
    # on tomberait sur des liens d'accueil.
    urls_specifiques = [u for u in urls_eforms if _est_url_specifique(u)]
    if urls_specifiques:
        # Filtre les URLs visiblement non-DCE (liens vers buyer profile,
        # CGU, etc.). Heuristique simple : on préfère les URLs qui contiennent
        # 'consultation', 'detail', 'annonce', ou un id= dans la query.
        prioritaires = [
            u for u in urls_specifiques
            if any(kw in u.lower()
                   for kw in ("consultation", "detail", "annonce",
                              "id=", "pcslid=", "csl_"))
        ]
        choisie = (prioritaires[0] if prioritaires else urls_specifiques[0])
        out["url_dce"] = choisie
        out["qualite"] = "directe"
        out["champ_source"] = "recherche récursive eForms"
        return out

    # === Niveau 2 : recherche par référence interne acheteur ===
    # 2a — PLACE en priorité (le cas le plus fréquent historiquement)
    if reference_ft:
        url_via_keyword = _chercher_url_dce_via_place(reference_ft)
        if url_via_keyword:
            out["url_dce"] = url_via_keyword
            out["qualite"] = "via_keyword"
            out["champ_source"] = f"PLACE keyWord={reference_ft}"
            return out

    # 2b — Phase 4 : recherche sur la plateforme du BuyerProfile si c'est
    # une plateforme Atexo blanche connue (Megalis, Maximilien, demat-ampa,
    # ternum-bfc, agglo-muretain, marches-publics.info, etc.).
    # Beaucoup d'avis de marché actifs n'ont pas d'URL DCE spécifique dans
    # eForms mais ont buyer_profile + reference_acheteur dans cac:ProcurementProject.cbc:ID.
    if reference_ft and out["buyer_profile"]:
        bp = out["buyer_profile"]
        if _domaine_est_plateforme_mp(bp) and not _est_url_specifique(bp):
            # bp est une URL racine de plateforme MP → on tente la keyword search
            url_via_atexo = _chercher_url_dce_via_atexo(reference_ft, bp)
            if url_via_atexo:
                out["url_dce"] = url_via_atexo
                out["qualite"] = "via_keyword"
                out["champ_source"] = (f"Atexo keyWord={reference_ft} "
                                       f"sur {bp}")
                return out

    # === Niveau 3 : URL racine seulement ===
    if uris_trouvees:
        out["qualite"] = "racine"
        out["champ_source"] = "cac:CallForTendersDocumentReference (racine)"

    return out


# ---------------------------------------------------------------------------
# Extraction pour TED
# ---------------------------------------------------------------------------

# Champs TED v3 ciblés pour le DCE, identifiés par diagnostic
TED_FIELDS_DCE = [
    "publication-number",
    "notice-title",
    "buyer-name",
    "buyer-profile",
    "document-url-lot",
    "document-url-part",
    "document-restricted-url-lot",
    "document-restricted-url-part",
    "submission-url-lot",
    "organisation-internet-address-buyer",
    "organisation-internet-address-docprovider-lot",
    "organisation-internet-address-docprovider-part",
    "touchpoint-internet-address-docprovider-lot",
    "touchpoint-internet-address-docprovider-part",
]


def _fetch_notice_ted(publication_number: str) -> Optional[dict]:
    """Récupère un notice TED avec les champs DCE ciblés."""
    body = {
        "query": f"publication-number={publication_number}",
        "fields": TED_FIELDS_DCE,
        "limit": 1,
        "scope": "ALL",
        "checkQuerySyntax": False,
        "paginationMode": "PAGE_NUMBER",
    }
    try:
        reponse = post_json(
            "https://api.ted.europa.eu/v3/notices/search",
            body, verbose=False,
        )
    except Exception:
        # Retry avec moins de champs (au cas où un champ pose problème)
        body["fields"] = ["publication-number", "notice-title",
                           "document-url-lot", "buyer-profile"]
        try:
            reponse = post_json(
                "https://api.ted.europa.eu/v3/notices/search",
                body, verbose=False,
            )
        except Exception:
            return None
    notices = reponse.get("notices") or reponse.get("results") or []
    return notices[0] if notices else None


def _extraire_dce_ted(notice: dict, publication_number: str) -> Dict:
    """Extrait l'URL DCE depuis un notice TED."""
    out: Dict = {
        "url_dce": None,
        "url_recherche": URL_PLACE_RECHERCHE.format(ref=publication_number),
        "qualite": "absente",
        "buyer_profile": None,
        "champ_source": None,
    }

    # Cherche dans les champs prioritaires
    candidats = []
    for champ in ["document-url-lot", "document-url-part",
                   "submission-url-lot"]:
        val = notice.get(champ)
        if val:
            if isinstance(val, list):
                candidats.extend([v for v in val if v])
            elif isinstance(val, str):
                candidats.append(val)
            else:
                candidats.append(str(val))

    for url in candidats:
        if _est_url_specifique(url):
            out["url_dce"] = url
            out["qualite"] = "directe"
            out["champ_source"] = "document-url"
            break

    # Buyer profile
    bp = notice.get("buyer-profile")
    if bp:
        out["buyer_profile"] = bp if isinstance(bp, str) else (
            bp[0] if isinstance(bp, list) and bp else None)
        if not out["url_dce"] and out["buyer_profile"] and \
                _est_url_specifique(out["buyer_profile"]):
            out["url_dce"] = out["buyer_profile"]
            out["qualite"] = "directe"
            out["champ_source"] = "buyer-profile"

    if not out["url_dce"] and candidats:
        out["qualite"] = "racine"
        out["champ_source"] = "document-url (racine)"

    return out


# ---------------------------------------------------------------------------
# Interface publique
# ---------------------------------------------------------------------------

def trouver_urls_dce(marche: dict, verbose: bool = False) -> Dict:
    """
    Pour un marché, identifie l'URL DCE en lisant les champs structurés
    de l'API source. Toujours fournit une URL de recherche PLACE en
    fallback (pré-remplie avec la référence du marché).

    Returns:
        {
          "url_dce": str | None,
          "url_recherche": str,
          "qualite": "directe" | "racine" | "absente",
          "buyer_profile": str | None,
          "champ_source": str | None,
          "api_recuperee": bool,
          # Compat ancienne API (tendia_dce.py)
          "urls_dce": list,
          "html_fallback": bool,
        }
    """
    source = marche.get("source")
    ref = marche.get("reference_externe")

    base = {
        "url_dce": None,
        "url_recherche": URL_PLACE_RECHERCHE.format(ref=ref or ""),
        "qualite": "absente",
        "buyer_profile": None,
        "champ_source": None,
        "reference_ft": None,
        "api_recuperee": False,
        "urls_dce": [],
        "html_fallback": False,
        "n_plateformes_trouvees": 0,
    }

    if not source or not ref:
        return base

    if source == "BOAMP":
        record = _fetch_record_boamp(ref)
        if record:
            base["api_recuperee"] = True
            data = _extraire_dce_boamp(record, ref)
            base.update({k: v for k, v in data.items() if k in base})
    elif source == "TED":
        notice = _fetch_notice_ted(ref)
        if notice:
            base["api_recuperee"] = True
            data = _extraire_dce_ted(notice, ref)
            base.update({k: v for k, v in data.items() if k in base})

    # Compat : reconstituer urls_dce avec l'URL DCE si trouvée
    if base["url_dce"]:
        base["urls_dce"] = [{
            "plateforme": "PLACE",
            "url": base["url_dce"],
            "source_extraction": "api_eforms",
        }]
        base["n_plateformes_trouvees"] = 1

    if verbose:
        print(f"  Source : {source} / Ref : {ref}")
        print(f"  Qualité : {base['qualite']}")
        if base.get("reference_ft"):
            print(f"  Référence interne acheteur : {base['reference_ft']}")
        if base["url_dce"]:
            print(f"  URL DCE : {base['url_dce'][:120]}")
        print(f"  URL recherche : {base['url_recherche'][:100]}")
        if base["buyer_profile"]:
            print(f"  Buyer profile : {base['buyer_profile'][:100]}")

    return base


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage : python dce_finder.py <BOAMP|TED> <reference>")
        sys.exit(1)
    marche = {"source": sys.argv[1].upper(), "reference_externe": sys.argv[2]}
    marche["url_avis"] = (
        f"https://www.boamp.fr/pages/avis/?q=idweb:{sys.argv[2]}"
        if sys.argv[1].upper() == "BOAMP"
        else f"https://ted.europa.eu/fr/notice/-/detail/{sys.argv[2]}"
    )
    r = trouver_urls_dce(marche, verbose=True)
    print()
    print(json.dumps(r, ensure_ascii=False, indent=2))
