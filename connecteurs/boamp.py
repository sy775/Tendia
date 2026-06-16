"""
connecteurs/boamp.py
--------------------
Connecteur BOAMP — marchés publics France Travail.

VERSION 3 — ÉLARGISSEMENT des mots-clés positifs :
- Ajout de termes génériques manquants (stage, session, parcours, cycle,
  habilitation, titre professionnel, CCP, etc.)
- Ajout de programmes FT spécifiques manquants (AIJ, Activ Projet,
  Activ Boost, Cap Emploi, FAJ, etc.)
- Ajout d'approches (découverte métiers, immersion, mise en situation,
  PMSMP, lever les freins...)
- Ajout de publics spécifiques (BRSA, jeunes en insertion, publics
  éloignés...)

Le but : ne plus rater de marchés formation/insertion à la source.
Le tri fin selon le métier de l'organisme se fait dans matching.py.

Les mots-clés négatifs (IT/RGPD/maintenance SI/fournitures) restent
inchangés.
"""

import sys
from datetime import date, timedelta
from typing import Optional

from http_utils import get_json


SOURCE = "BOAMP"
DOMAINES = ["boamp.fr", "boamp-datadila.opendatasoft.com"]

BOAMP_URL = (
    "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/"
    "catalog/datasets/boamp/records"
)

TAILLE_PAGE = 100
MAX_RESULTATS_TOTAL = 3000

MOTS_CLES_ACHETEUR = [
    "france travail",
    "pole emploi",
    "pôle emploi",
]

# === Classification métier — mots-clés positifs ÉLARGIS ===

MOTS_CLES_FORMATION = [
    # Termes principaux
    "formation", "formations",
    "parcours de formation", "parcours pédagogique", "parcours pedagogique",
    "cycle de formation", "session de formation", "sessions de formation",
    "stage de formation", "stages de formation",
    # Diplômes et certifications
    "diplôme", "diplome", "diplomant", "diplomante", "diplômant", "diplômante",
    "certifiant", "certifiante", "certification",
    "titre professionnel", "titre pro", "tp ", " tp",
    "ccp ", " ccp", "ccs ",
    "cqp", "certificat de qualification",
    "habilitation",
    # France Travail spécifique formation
    "afc ", " afc", "afpr ", " afpr",
    "poec", "poei",
    "professionnalisation",
    "préparation opérationnelle", "preparation operationnelle",
    "préparation à l'emploi", "preparation a l emploi",
    # Pédagogie / contenu
    "module pédagogique", "module pedagogique",
    "remise à niveau", "remise a niveau",
    "alphabétisation", "alphabetisation",
    "compétences clés", "competences cles",
    "savoirs de base", "savoirs fondamentaux",
    "français langue", "francais langue", "fle ", " fle",
    "illettrisme",
    "vae ", " vae", "validation des acquis",
    "apprentissage", "apprentis",
    "tutorat", "tuteur",
    "e-learning", "elearning",
]

MOTS_CLES_INSERTION = [
    # Insertion générique
    "insertion professionnelle", "insertion sociale", "insertion ",
    "intégration professionnelle", "integration professionnelle",
    "reclassement", "transition professionnelle",
    "reconversion professionnelle", "reconversion",
    # Public demandeurs d'emploi
    "demandeur d'emploi", "demandeurs d'emploi",
    "retour à l'emploi", "retour a l'emploi", "retour a l emploi",
    "accès à l'emploi", "acces a l emploi",
    # Programmes France Travail
    "activ ", " activ", "activ'",
    "agil cadres", "agil'cadres", "agil ",
    "mile ", " mile",
    "creascope", "créascope",
    "cap emploi", "cap-emploi",
    "aij ", "globalize",
    "faj ", "fonds d'aide aux jeunes",
    "actif ", " actif", "act'pro",
    # Accompagnement (ciblé emploi)
    "accompagnement vers l'emploi", "accompagnement vers l emploi",
    "accompagnement des demandeurs", "accompagnement personnalisé",
    "accompagnement personnalise",
    "accompagnement à la création", "accompagnement a la creation",
    "accompagnement vers la création", "accompagnement vers la creation",
    "accompagnement renforcé", "accompagnement renforce",
    "accompagnement global",
    # Orientation et bilan
    "orientation professionnelle", "réorientation", "reorientation",
    "bilan de compétences", "bilan de competences",
    "bilan professionnel",
    "coaching", "coach",
    # Immersion / mise en situation
    "immersion professionnelle", "immersion en entreprise",
    "essai en entreprise", "période d'immersion", "periode d immersion",
    "mise en situation professionnelle", "mise en situation",
    "pmsmp", "stage en entreprise",
    "découverte des métiers", "decouverte des metiers",
    "découverte sectorielle", "decouverte sectorielle",
    # Remobilisation / projet
    "remobilisation",
    "définition de projet professionnel", "definition de projet professionnel",
    "construction de projet", "construire un projet",
    "construire son projet", "élaboration de projet", "elaboration de projet",
    "lever les freins", "lever des freins",
    "freins à l'emploi", "freins a l emploi",
    # Ateliers ciblés emploi
    "atelier emploi", "atelier de recherche", "atelier d'orientation",
    "atelier d orientation", "atelier numérique", "atelier numerique",
    "atelier collectif",
    # Publics spécifiques
    "brsa", "bénéficiaire du rsa", "beneficiaire du rsa",
    "jeunes en difficulté", "jeunes en difficulte",
    "jeunes en insertion",
    "publics éloignés", "publics eloignes",
    "personnes éloignées", "personnes eloignees",
    "personnes en reconversion",
    "seniors en recherche", "personnes en situation de handicap",
    # Prestations d'aide
    "prestation d'aide à la recherche", "prestation d aide a la recherche",
    "aide à la recherche d'emploi", "aide a la recherche d emploi",
    "recherche d'emploi",
]

# === Mots-clés NÉGATIFS — exclusion stricte (inchangés) ===
MOTS_CLES_NEGATIFS = [
    # IT / SI
    "rgpd", "ria ", " ria", "ria/", "ria,",
    "homologation des system", "homologation système", "homologation systeme",
    "maintenance si", "maintenance du si", "système d'information",
    "systeme d information", "systèmes d'information", "systemes d information",
    "infrastructure informatique",
    "outil de veille", "outil informatique",
    "logiciel", "logicielle",
    "site internet", "site web", "application mobile", "application web",
    "cybersécurité", "cybersecurite", "sécurité informatique",
    "hébergement", "hebergement",
    # Conformité / juridique
    "conformité juridique", "conformite juridique",
    # Fournitures / travaux / services généraux
    "fourniture d'équipement", "fourniture d equipement",
    "fourniture de matériel", "fourniture de materiel",
    "collecte et traitement des déchets", "collecte et traitement des dechets",
    "nettoyage", "ménage",
    "fontaine à eau", "fontaine a eau",
    "sûreté bâtimentaire", "surete batimentaire",
    "déménagement", "demenagement",
    "abonnement à des publications", "abonnement a des publications",
    "fourniture d'ouvrages", "fourniture d ouvrages",
    "prestations logistiques",
    "travaux de", "marché de travaux", "marche de travaux",
    "marché de maintenance et location", "marche de maintenance et location",
]


# ---------------------------------------------------------------------------
# Helpers d'extraction
# ---------------------------------------------------------------------------

def _premier_present(d: dict, cles: list) -> str:
    for c in cles:
        v = d.get(c)
        if v not in (None, "", []):
            if isinstance(v, list):
                return " | ".join(str(x) for x in v if x)[:600]
            return str(v)[:600]
    return ""


def _texte_objet(avis: dict) -> str:
    return _premier_present(avis, [
        "objet", "objet_complet", "intitule", "titre",
    ])


def _texte_acheteur(avis: dict) -> str:
    return _premier_present(avis, [
        "nomacheteur", "organisme", "nom_acheteur",
    ])


def _date_publication(avis: dict) -> str:
    return _premier_present(avis, ["dateparution", "date_parution"])[:10]


def _date_limite(avis: dict) -> Optional[str]:
    v = _premier_present(avis, ["datelimitereponse", "date_limite_reponse",
                                  "datelimite"])
    return v[:10] if v else None


def _famille(avis: dict) -> Optional[str]:
    v = _premier_present(avis, ["famille_libelle", "famille"])
    return v[:120] if v else None


def _perimetre(avis: dict) -> Optional[str]:
    parts = []
    dep = _premier_present(avis, ["code_departement_prestation",
                                    "code_departement"])
    if dep:
        parts.append(f"Dept {dep}")
    perim = _premier_present(avis, ["perimetre"])
    if perim:
        parts.append(perim)
    return " | ".join(parts) if parts else None


def _trouver_recursivement(obj, cle_cible: str, max_profondeur: int = 8):
    """Cherche récursivement la première valeur d'une clé dans un dict/liste imbriqué."""
    if max_profondeur <= 0:
        return None
    if isinstance(obj, dict):
        if cle_cible in obj:
            return obj[cle_cible]
        for v in obj.values():
            r = _trouver_recursivement(v, cle_cible, max_profondeur - 1)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for elt in obj:
            r = _trouver_recursivement(elt, cle_cible, max_profondeur - 1)
            if r is not None:
                return r
    return None


def _extraire_cpv_principal(avis: dict) -> Optional[str]:
    """
    Extrait le CPV principal d'un avis BOAMP.

    Stratégie : le CPV n'est pas exposé à la racine. Il est imbriqué dans
    le champ `donnees` (chaîne JSON eForms UBL). On parse ce JSON, on cherche
    récursivement la première occurrence de `cbc:ItemClassificationCode`
    (norme UBL), qui contient le CPV principal sous `#text`.

    Retourne le code CPV à 8 chiffres (ex: "80530000") ou None si absent.
    """
    donnees_str = avis.get("donnees")
    if not donnees_str or not isinstance(donnees_str, str):
        return None
    import json as _json
    try:
        donnees = _json.loads(donnees_str)
    except (ValueError, TypeError):
        return None

    # 1. Tente le chemin UBL standard pour le CPV principal
    item = _trouver_recursivement(donnees, "cbc:ItemClassificationCode")
    if item is None:
        return None
    # ItemClassificationCode est typiquement {"@listName": "cpv", "#text": "80530000"}
    if isinstance(item, dict):
        val = item.get("#text")
        if isinstance(val, str) and val.strip().isdigit():
            return val.strip()
    elif isinstance(item, str) and item.strip().isdigit():
        return item.strip()
    return None


def _texte_simple(v) -> str:
    """Aplatit une valeur BOAMP (str / liste / nœud UBL {'#text': ...}) en str."""
    if v is None:
        return ""
    if isinstance(v, dict):
        v = v.get("#text", "")
    if isinstance(v, list):
        v = v[0] if v else ""
    return str(v).strip()


def _extraire_contact(avis: dict) -> Optional[dict]:
    """
    Extrait le contact (correspondant) parfois renseigné dans l'avis BOAMP.

    Deux schémas possibles dans le champ `donnees` (chaîne JSON) :
    - legacy (3.2.5) : `.../organisme/correspondantPRM` (civilite/nom/pren/fonc)
      + `.../organisme/coord` (tel/mel). La racine varie selon le type d'avis
      (MAPA, AAPC, AVIS…), d'où la recherche récursive plutôt qu'un chemin fixe.
    - eForms (UBL) : `cac:Contact` (cbc:Name / cbc:ElectronicMail / cbc:Telephone).

    Retourne un dict {nom, civilite, fonction, email, telephone} (clés non vides
    seulement) ou None si aucun contact exploitable. Info « parfois renseignée » :
    un avis sur deux environ n'a pas de contact.
    """
    donnees_str = avis.get("donnees")
    if not donnees_str or not isinstance(donnees_str, str):
        return None
    import json as _json
    try:
        donnees = _json.loads(donnees_str)
    except (ValueError, TypeError):
        return None

    candidats = []

    # --- Variante A (legacy) : correspondantPRM (identité) + coord (coordonnées) ---
    a = {}
    corr = _trouver_recursivement(donnees, "correspondantPRM")
    if isinstance(corr, dict):
        nom_complet = " ".join(p for p in (_texte_simple(corr.get("pren")),
                                           _texte_simple(corr.get("nom"))) if p)
        if nom_complet:
            a["nom"] = nom_complet[:160]
        civ = _texte_simple(corr.get("civilite"))
        if civ:
            a["civilite"] = civ[:20]
        fonc = _texte_simple(corr.get("fonc"))
        if fonc:
            a["fonction"] = fonc[:200]
    coord = _trouver_recursivement(donnees, "coord")
    if isinstance(coord, dict):
        mel = _texte_simple(coord.get("mel"))
        if mel and "@" in mel:
            a["email"] = mel[:160]
        tel = _texte_simple(coord.get("tel"))
        if tel:
            a["telephone"] = tel[:40]
    if a:
        candidats.append(a)

    # --- Variante B (legacy) : bloc communication (nomContact/adresseMailContact/telContact) ---
    b = {}
    nomc = _texte_simple(_trouver_recursivement(donnees, "nomContact"))
    if nomc:
        b["nom"] = nomc[:160]
    melc = (_texte_simple(_trouver_recursivement(donnees, "adresseMailContact"))
            or _texte_simple(_trouver_recursivement(donnees, "courrielContact")))
    if melc and "@" in melc:
        b["email"] = melc[:160]
    telc = _texte_simple(_trouver_recursivement(donnees, "telContact"))
    if telc:
        b["telephone"] = telc[:40]
    if b:
        candidats.append(b)

    # --- Variante C (eForms UBL) : cac:Contact ---
    # Profondeur élevée : en eForms le contact est imbriqué à ~10 niveaux
    # (EFORMS/…/efac:Organization[0]/efac:Company/cac:Contact). Organization[0]
    # = acheteur ; les suivantes = organes de recours (tribunal) → le premier
    # match en profondeur d'abord est le bon.
    c = {}
    ct = _trouver_recursivement(donnees, "cac:Contact", max_profondeur=15)
    if isinstance(ct, dict):
        nom = _texte_simple(ct.get("cbc:Name"))
        if nom:
            c["nom"] = nom[:160]
        mel = _texte_simple(ct.get("cbc:ElectronicMail"))
        if mel and "@" in mel:
            c["email"] = mel[:160]
        tel = _texte_simple(ct.get("cbc:Telephone"))
        if tel:
            c["telephone"] = tel[:40]
    if c:
        candidats.append(c)

    # Cas fréquent de saisie : un email mis dans le champ « nom » (ex.
    # nomContact = "servicedesmarches@maregionsud.fr"). On le promeut en email.
    import re as _re
    _EMAIL = _re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
    for cand in candidats:
        if not cand.get("email") and _EMAIL.match(cand.get("nom", "")):
            cand["email"] = cand["nom"][:160]

    if not candidats:
        return None
    # On privilégie le candidat porteur d'un email (le plus actionnable pour
    # le démarchage) ; à défaut, le premier bloc trouvé (souvent juste un nom).
    avec_email = [cand for cand in candidats if cand.get("email")]
    return avec_email[0] if avec_email else candidats[0]


def _extraire_descripteur(avis: dict) -> dict:
    """Extrait code et libellé du descripteur BOAMP (taxonomie maison)."""
    code = avis.get("descripteur_code")
    libelle = avis.get("descripteur_libelle")
    return {
        "code": code[0] if isinstance(code, list) and code else None,
        "libelle": libelle[0] if isinstance(libelle, list) and libelle else None,
    }


def _extraire_type_marche(avis: dict) -> Optional[str]:
    """Retourne 'SERVICES' | 'TRAVAUX' | 'FOURNITURES' ou None."""
    v = avis.get("type_marche")
    if isinstance(v, list) and v:
        return str(v[0])
    if isinstance(v, str):
        return v
    return None


def _url_avis(avis: dict) -> str:
    direct = _premier_present(avis, ["url_avis", "url"])
    if direct:
        return direct
    idweb = _premier_present(avis, ["idweb", "id"])
    if idweb:
        return f"https://www.boamp.fr/pages/avis/?q=idweb:{idweb}"
    return ""


def _notice_type(avis: dict) -> Optional[str]:
    v = _premier_present(avis, ["type_avis", "type", "notice_type", "typeavis"])
    return v[:50] if v else None


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classifier(avis: dict) -> str:
    objet = _texte_objet(avis).lower()
    if not objet:
        return "autre"
    if any(mc in objet for mc in MOTS_CLES_NEGATIFS):
        return "autre"
    if any(mc in objet for mc in MOTS_CLES_FORMATION):
        return "formation"
    if any(mc in objet for mc in MOTS_CLES_INSERTION):
        return "insertion"
    return "autre"


def _branche_eforms(avis: dict) -> Optional[str]:
    """
    Parse avis['donnees'] (JSON string) et retourne la branche eForms
    racine : 'ContractNotice' / 'ContractAwardNotice' / 'PriorInformationNotice'
    ou None si absent / non parsable.

    Signal fiable pour distinguer un avis ouvert (ContractNotice) d'un avis
    d'attribution (ContractAwardNotice). Plus fiable que les heuristiques
    texte sur type_avis/objet utilisées par _est_avis_ouvert historiquement.
    """
    donnees_str = avis.get("donnees")
    if not donnees_str or not isinstance(donnees_str, str):
        return None
    import json as _json
    try:
        donnees = _json.loads(donnees_str)
    except (ValueError, TypeError):
        return None
    eforms = donnees.get("EFORMS") if isinstance(donnees, dict) else None
    if not isinstance(eforms, dict):
        return None
    for branche in ("ContractAwardNotice", "ContractNotice",
                     "PriorInformationNotice"):
        if branche in eforms:
            return branche
    return None


def _est_avis_ouvert(avis: dict) -> bool:
    # 1. Signal fort : branche eForms racine. Si ContractAwardNotice, c'est
    #    un avis d'attribution, on rejette à coup sûr (le filtre historique
    #    sur type_avis/objet laissait passer ~24% d'attributions).
    branche = _branche_eforms(avis)
    if branche == "ContractAwardNotice":
        return False

    # 2. Fallback heuristique texte pour les avis sans branche eForms
    #    (anciens formats, certaines notices spéciales)
    type_avis = (_notice_type(avis) or "").lower()
    objet = _texte_objet(avis).lower()
    indices_clos = [
        "avis d'attribution", "avis d attribution",
        "résultat de marché", "resultat de marche",
        "marché conclu", "marche conclu",
        "avis de modification",
    ]
    if any(ind in objet for ind in indices_clos):
        return False
    if "attribution" in type_avis:
        return False
    return True


# ---------------------------------------------------------------------------
# Enrichissement v2 (schéma marché — cf. docs/modules/marche.md SECTION 1)
# ---------------------------------------------------------------------------

# Champs d'enrichissement suivis pour la couverture (enrichissement_champs_absents).
_CHAMPS_SUIVIS = [
    "url_consultation_dce_directe", "acheteur_siren", "montant_estime_eur",
    "url_profil_acheteur", "acheteur_ville", "acheteur_code_postal", "acheteur_nuts",
    "cpv_secondaires", "nature", "procedure_libelle", "criteres_attribution",
    "acheteur_adresse", "dce_consultation_id", "duree_marche_mois",
]


def _parse_donnees(avis: dict):
    """Parse le bloc `donnees` (chaîne JSON eForms/legacy) → dict, ou None."""
    d = avis.get("donnees")
    if isinstance(d, dict):
        return d
    if not isinstance(d, str):
        return None
    import json as _json
    try:
        return _json.loads(d)
    except (ValueError, TypeError):
        return None


def _trouver_tous(obj, cle_cible: str, max_profondeur: int = 20) -> list:
    """Toutes les valeurs d'une clé dans un dict/liste imbriqué (≠ première seule)."""
    out = []
    if max_profondeur <= 0:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == cle_cible:
                out.append(v)
            else:
                out.extend(_trouver_tous(v, cle_cible, max_profondeur - 1))
    elif isinstance(obj, list):
        for elt in obj:
            out.extend(_trouver_tous(elt, cle_cible, max_profondeur - 1))
    return out


def _noeud(donnees, cle, prof=20) -> Optional[str]:
    """Texte aplati de la première occurrence d'une clé eForms, ou None."""
    if donnees is None:
        return None
    v = _texte_simple(_trouver_recursivement(donnees, cle, prof))
    return v or None


def _siren(donnees) -> Optional[str]:
    """SIREN acheteur (9 chiffres) depuis cbc:CompanyID. Si SIRET (14), garde le SIREN."""
    v = _noeud(donnees, "cbc:CompanyID") or ""
    digits = "".join(c for c in v if c.isdigit())
    return digits[:9] if len(digits) >= 9 else None


def _montant(node_txt) -> Optional[float]:
    """Convertit un montant texte en float (None si absent/illisible ; 0.0 conservé)."""
    if not node_txt:
        return None
    try:
        return float(str(node_txt).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def _duree_en_mois(donnees) -> Optional[int]:
    """cbc:DurationMeasure (@unitCode MONTH/DAY/ANN) → mois entiers, best-effort."""
    node = _trouver_recursivement(donnees, "cbc:DurationMeasure", 20)
    if not isinstance(node, dict):
        return None
    txt = node.get("#text")
    unit = (node.get("@unitCode") or "").upper()
    try:
        n = float(txt)
    except (TypeError, ValueError):
        return None
    if unit in ("MON", "MONTH"):
        return int(round(n))
    if unit in ("DAY", "DAILY"):
        return int(round(n / 30.0))
    if unit in ("ANN", "YEAR"):
        return int(round(n * 12))
    if unit in ("WEEK",):
        return int(round(n / 4.345))
    return int(round(n)) if n else None


def _extraire_lots(donnees) -> list:
    """Liste des lots : {numero, intitule, cpv, montant_estime, duree, description_complete,
    criteres_specifiques} (champs présents seulement). Best-effort, robuste aux malformés."""
    brut = _trouver_recursivement(donnees, "cac:ProcurementProjectLot", 20)
    if brut is None:
        return []
    lots = brut if isinstance(brut, list) else [brut]
    out = []
    for i, lot in enumerate(lots, 1):
        try:
            proj = _trouver_recursivement(lot, "cac:ProcurementProject", 6) or lot
            d = {"numero": _noeud(lot, "cbc:ID", 4) or str(i)}
            intit = _noeud(proj, "cbc:Name", 6)
            if intit:
                d["intitule"] = intit[:300]
            desc = _noeud(proj, "cbc:Description", 6)
            if desc:
                d["description_complete"] = desc[:1000]
            cpv = _noeud(proj, "cbc:ItemClassificationCode", 8)
            if cpv and cpv.isdigit():
                d["cpv"] = cpv
            mtt = _montant(_noeud(lot, "cbc:EstimatedOverallContractAmount", 10))
            if mtt is not None:
                d["montant_estime"] = mtt
            dur = _duree_en_mois(lot)
            if dur:
                d["duree"] = dur
            crit = (_trouver_recursivement(lot, "cac:AwardingCriterion", 12)
                    or _trouver_recursivement(lot, "efac:AwardCriterionParameter", 12))
            if crit is not None:
                noms = [n for n in (_texte_simple(x) for x in _trouver_tous(crit, "cbc:Name", 6)) if n]
                if noms:
                    d["criteres_specifiques"] = noms[:8]
            out.append(d)
        except Exception:
            out.append({"numero": str(i)})
    return out


def _champ_ods(avis: dict, cle):
    """Champ ODS top-niveau : scalaire aplati (None si vide), liste conservée si multi."""
    v = avis.get(cle)
    if v in (None, "", []):
        return None
    if isinstance(v, list):
        return v[0] if len(v) == 1 else v
    return v


def extraire_champs_enrichissement(avis: dict, source: str = "crawl") -> dict:
    """
    Extrait les ~31 champs d'enrichissement v2 d'un avis BOAMP brut (cf.
    docs/modules/marche.md SECTION 1). Réutilisable par le crawl (_normaliser) et
    le backfill. Tous les champs eForms peuvent être None (avis legacy).
    """
    import json as _json
    import re as _re
    from datetime import datetime, timezone

    d = _parse_donnees(avis)

    # --- Trio critique ---
    endpoint = _noeud(d, "cbc:EndpointID")
    url_dce_directe = endpoint if (endpoint and endpoint.lower().startswith("http")) else None
    montant_estime = _montant(_noeud(d, "cbc:EstimatedOverallContractAmount"))

    # --- CPV secondaires (toutes occurrences hors principal) ---
    principal = _extraire_cpv_principal(avis)
    cpv_sec = []
    for it in _trouver_tous(d, "cbc:ItemClassificationCode"):
        code = _texte_simple(it)
        if code and code.isdigit() and code != principal and code not in cpv_sec:
            cpv_sec.append(code)

    famille = _champ_ods(avis, "famille")
    famille_lib = (_champ_ods(avis, "famille_libelle") or "")
    est_europeen = (str(famille).upper() == "JOUE"
                    or "europ" in str(famille_lib).lower())

    enr = {
        # 🔴 Trio critique
        "url_consultation_dce_directe": url_dce_directe,
        "acheteur_siren": _siren(d),
        "montant_estime_eur": montant_estime,
        # 🟠 Priorité 1
        "url_profil_acheteur": _noeud(d, "cbc:BuyerProfileURI"),
        "acheteur_ville": _noeud(d, "cbc:CityName"),
        "acheteur_code_postal": _noeud(d, "cbc:PostalZone"),
        "acheteur_nuts": _noeud(d, "cbc:CountrySubentityCode"),
        "nombre_lots": 0,
        "lots_json": None,
        # 🟡 Priorité 2
        "cpv_secondaires": cpv_sec or None,
        "nature": _champ_ods(avis, "nature"),
        "nature_libelle": _champ_ods(avis, "nature_libelle"),
        "procedure_libelle": _champ_ods(avis, "procedure_libelle"),
        "criteres_attribution": _champ_ods(avis, "criteres"),
        "est_europeen": bool(est_europeen),
        "acheteur_adresse": _noeud(d, "cbc:StreetName"),
        "acheteur_pays": _noeud(d, "cbc:IdentificationCode") or "FR",
        # 🟢 Priorité 3
        "dce_consultation_id": _champ_ods(avis, "contractfolderid"),
        "annonces_anterieures": _champ_ods(avis, "annonces_anterieures"),
        "annonce_lie": _champ_ods(avis, "annonce_lie"),
        "date_fin_diffusion": _champ_ods(avis, "datefindiffusion"),
        "duree_marche_mois": _duree_en_mois(d),
        "etat": _champ_ods(avis, "etat"),
        "type_avis_detail": _champ_ods(avis, "type_avis"),
    }

    lots = _extraire_lots(d)
    if lots:
        enr["nombre_lots"] = len(lots)
        enr["lots_json"] = lots

    # --- ⚙️ Méta ---
    absents = [c for c in _CHAMPS_SUIVIS if not enr.get(c)]
    enr["enrichissement_version"] = "v2"
    enr["enrichissement_le"] = datetime.now(timezone.utc).isoformat()
    enr["enrichissement_source"] = source
    enr["enrichissement_champs_absents"] = absents
    enr["source_schema_eforms"] = _champ_ods(avis, "source_schema")
    enr["donnees_boamp_brut"] = _json.dumps(avis, ensure_ascii=False)
    return enr


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def _normaliser(avis: dict, categorie: str) -> Optional[dict]:
    idweb = _premier_present(avis, ["idweb", "id"])
    if not idweb:
        return None
    objet = _texte_objet(avis)
    descripteur = _extraire_descripteur(avis)
    base = {
        "id": f"BOAMP-{idweb}",
        "source": "BOAMP",
        "reference_externe": idweb,
        "url_source": _url_avis(avis),
        "url_avis": _url_avis(avis),
        "titre": objet[:200],
        "objet": objet,
        "acheteur_nom": _texte_acheteur(avis)[:200],
        "acheteur_id": None,  # déprécié v2 → cf. acheteur_siren (docs/modules/marche.md)
        "contact": _extraire_contact(avis),
        "perimetre_geographique": _perimetre(avis),
        "date_publication": _date_publication(avis),
        "date_limite_depot": _date_limite(avis),
        "cpv_principal": _extraire_cpv_principal(avis),
        "type_marche": _extraire_type_marche(avis),
        "descripteur_code": descripteur["code"],
        "descripteur_libelle": descripteur["libelle"],
        "categorie_metier": categorie,
        "famille_boamp": _famille(avis),
        "notice_type": _notice_type(avis),
    }
    # Enrichissement v2 (~31 champs : SIREN, montant, URL DCE directe, lots, géo…).
    base.update(extraire_champs_enrichissement(avis, source="crawl"))
    return base


# ---------------------------------------------------------------------------
# Récupération
# ---------------------------------------------------------------------------

def _construire_where_acheteur() -> str:
    clauses = [f'search(nomacheteur, "{m}")' for m in MOTS_CLES_ACHETEUR]
    return " OR ".join(clauses)


def _recuperer_bruts(date_debut: date, date_fin: date,
                     max_total: int = MAX_RESULTATS_TOTAL,
                     filtre_acheteur: bool = True,
                     verbose: bool = True) -> list:
    """
    Récupère les avis BOAMP bruts entre 2 dates.

    Args:
        filtre_acheteur: si True, filtre côté API par MOTS_CLES_ACHETEUR
                          (mode legacy FT). Si False, capte TOUS les avis
                          de la fenêtre (mode Sprint 3 ingestion large).
    """
    # Filtre date côté API (syntaxe ODS) : limite drastiquement le volume
    # 1.6M -> ~60k pour fenêtre 6 mois
    clauses_where = [f"dateparution >= date'{date_debut.isoformat()}'"]
    if filtre_acheteur:
        clauses_where.append(f"({_construire_where_acheteur()})")
    where_clause = " AND ".join(clauses_where)

    tous: list = []
    offset = 0
    seuil_date_str = date_debut.isoformat()

    while True:
        params = {
            "where": where_clause,
            "limit": TAILLE_PAGE,
            "offset": offset,
            "order_by": "dateparution DESC",
        }
        if verbose:
            mode = "filtré acheteur" if filtre_acheteur else "TOUS"
            print(f"  [BOAMP] Appel offset={offset} (cumul reçu : {len(tous)}, mode : {mode})")

        try:
            reponse = get_json(BOAMP_URL, params=params, verbose=False)
        except Exception as e:
            print(f"  [BOAMP] ⚠ Erreur : {str(e)[:200]}", file=sys.stderr)
            params.pop("order_by", None)
            try:
                reponse = get_json(BOAMP_URL, params=params, verbose=False)
            except Exception as e2:
                print(f"  [BOAMP] ❌ Échec : {str(e2)[:200]}", file=sys.stderr)
                break

        avis_page = reponse.get("results") or []
        if offset == 0 and verbose:
            total = reponse.get("total_count")
            print(f"  [BOAMP] Total matchant côté API : {total}")
        if not avis_page:
            break

        tous.extend(avis_page)
        date_derniere = _date_publication(avis_page[-1])
        if date_derniere and date_derniere[:10] < seuil_date_str:
            if verbose:
                print(f"  [BOAMP] Date dépassée, arrêt.")
            break

        offset += len(avis_page)
        if len(tous) >= max_total or offset + TAILLE_PAGE > 9900:
            if verbose:
                print(f"  [BOAMP] Plafond atteint.")
            break

    return tous


# ---------------------------------------------------------------------------
# Interface publique
# ---------------------------------------------------------------------------

def lister_marches(fenetre_mois: int = 6, limite: Optional[int] = None,
                    filtre_acheteur: bool = True,
                    inclure_autre: bool = False,
                    verbose: bool = True) -> list:
    """
    Liste les marchés BOAMP de la fenêtre demandée.

    Args:
        fenetre_mois: profondeur en mois.
        limite: cap par source (debug).
        filtre_acheteur: True = filtre côté API par France Travail/Pôle Emploi
                          (mode legacy). False = capte TOUS les acheteurs
                          (mode Sprint 3 ingestion large).
        inclure_autre: True = inclut les marchés catégorisés "autre"
                       (mode large). False = exclut (mode legacy).
        verbose: affichage console.
    """
    date_fin = date.today()
    date_debut = date_fin - timedelta(days=fenetre_mois * 30)
    avis_bruts = _recuperer_bruts(date_debut, date_fin,
                                   filtre_acheteur=filtre_acheteur,
                                   verbose=verbose)

    marches: list = []
    stats = {"formation": 0, "insertion": 0, "autre": 0,
             "autre_ignores": 0, "clos_ignores": 0,
             "exclus_negatifs": 0,
             "exclus_fournitures": 0}

    for a in avis_bruts:
        if not _est_avis_ouvert(a):
            stats["clos_ignores"] += 1
            continue
        cat = classifier(a)
        if cat == "autre":
            if not inclure_autre:
                # Mode legacy : on filtre encore par mots-clés négatifs
                objet = _texte_objet(a).lower()
                if any(mc in objet for mc in MOTS_CLES_NEGATIFS):
                    stats["exclus_negatifs"] += 1
                else:
                    stats["autre_ignores"] += 1
                continue
            # Mode large : on garde les "autre" SAUF les fournitures pures
            # (la philosophie β = services + travaux publics, hors fournitures)
            type_m = _extraire_type_marche(a)
            if type_m == "FOURNITURES":
                stats["exclus_fournitures"] += 1
                continue
            stats["autre"] += 1
        else:
            stats[cat] += 1
        m = _normaliser(a, cat)
        if m is not None:
            marches.append(m)
        if limite and len(marches) >= limite:
            break

    if verbose:
        print(f"  [BOAMP] Classification :")
        print(f"    formation        : {stats['formation']}")
        print(f"    insertion        : {stats['insertion']}")
        if inclure_autre:
            print(f"    autre (inclus)   : {stats['autre']}")
            print(f"    exclus fournitures : {stats['exclus_fournitures']}")
        else:
            print(f"    autre (hors thème) : {stats['autre_ignores']}")
            print(f"    exclus négatifs  : {stats['exclus_negatifs']}")
        print(f"    clos ignorés     : {stats['clos_ignores']}")

    return marches


if __name__ == "__main__":
    import json
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mois", type=int, default=6)
    parser.add_argument("--limite", type=int, default=None)
    args = parser.parse_args()
    marches = lister_marches(fenetre_mois=args.mois, limite=args.limite,
                              verbose=True)
    print(f"\n=== {len(marches)} marchés ===")
    for m in marches[:5]:
        print(json.dumps(m, ensure_ascii=False, indent=2))
