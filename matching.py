"""
matching.py
-----------
Moteur de matching organisme x marche pour Tendia.

VERSION 4 (Sprint B) : multi-secteurs.

Detecte le format du profil organisme et route :
  - Format legacy formation -> code V1 historique.
  - Nouveau format multi-secteurs (presets_couverts + profils_sectoriels)
    -> code V2 avec evaluateurs sectoriels.

Pour V2 :
  - Universels : preset_compatibilite, thematique (mots-cles catalogue),
    geographie (zones_intervention via mapping dept/region), capacite
    financiere (socle).
  - Sectoriels (V1 implemente : BTP) : qualifications go/no-go,
    corps_de_metier, types_ouvrages, capacite chantier.
  - Sprint C : evaluateurs sectoriels ingenierie, conseil, IT, EnR.

Signature publique (compat ascendante) :
    evaluer(organisme, marche, brief=None, presets_marche=None) -> dict
    evaluer_tous(organisme, marches, briefs=None) -> list

`brief` est indispensable pour le scoring sectoriel BTP (qualifications_
requises, caracteristiques_techniques_chantier, montant_marche).
"""

import re
import unicodedata
from typing import Optional, List

import preset as _preset


VERDICTS = ("tres_pertinent", "pertinent", "a_verifier", "non_pertinent")

SEUIL_TRES_PERTINENT = 75
SEUIL_PERTINENT = 50
SEUIL_A_VERIFIER = 20

# Pondération multi-preset (entreprises diversifiées) — décote « équilibrée ».
# Rang 1 = activité principale (référence pleine), 2 = secondaire, 3 = tertiaire.
# La source du rang est `presets_priorites` du profil, sinon l'ordre de `presets_couverts`.
PRESET_COMPAT_POINTS = {1: 20, 2: 13, 3: 7}   # points de compat selon le rang du preset matché
PRESET_COMPAT_DEFAULT = 7                       # rang > 3
PRESET_FACTEUR_SECTORIEL = {1: 1.0, 2: 0.6, 3: 0.35}  # atténue les signaux sectoriels POSITIFS
PRESET_FACTEUR_DEFAULT = 0.35
_LIBELLE_RANG = {1: "principal", 2: "secondaire", 3: "tertiaire"}


def _rang_preset(organisme: dict, code: str) -> int:
    """Rang de priorité d'un preset (1 = principal). Source : `presets_priorites`
    si présent, sinon l'ordre de `presets_couverts` (index + 1). Inconnu → 99."""
    prio = organisme.get("presets_priorites") or {}
    if code in prio:
        try:
            return max(1, int(prio[code]))
        except (TypeError, ValueError):
            pass
    couverts = organisme.get("presets_couverts") or []
    if code in couverts:
        return couverts.index(code) + 1
    return 99


def rang_preset_matche(organisme: dict, presets_marche: list) -> int:
    """Meilleur rang de priorité (1 = principal) parmi les presets du marché couverts
    par le profil. Retourne 99 si aucune intersection (marché hors activités).
    Utilisé pour trier le dashboard par activité prioritaire."""
    couverts = organisme.get("presets_couverts") or []
    inter = [p for p in (presets_marche or []) if p in couverts]
    if not inter:
        return 99
    return min(_rang_preset(organisme, c) for c in inter)


def _ponderer_motifs_sectoriels(motifs: list, facteur: float) -> list:
    """Atténue les points POSITIFS des motifs sectoriels par `facteur` (préserve les
    pénalités go/no-go négatives, par prudence)."""
    if facteur >= 1.0:
        return motifs
    out = []
    for m in motifs:
        if (m.get("points") or 0) > 0:
            m = dict(m)
            m["points"] = int(round(m["points"] * facteur))
        out.append(m)
    return out


# ===========================================================================
# REFERENTIELS GEOGRAPHIQUES
# ===========================================================================

ACHETEUR_VERS_REGION = [
    ("auvergne", "ARA"), ("rhone alpes", "ARA"), ("rhône-alpes", "ARA"),
    (" ara", "ARA"),
    ("bourgogne", "BFC"), ("franche-comte", "BFC"), ("franche comté", "BFC"),
    ("bretagne", "BRE"),
    ("centre-val", "CVL"), ("centre val", "CVL"), (" cvl", "CVL"),
    ("corse", "COR"),
    ("grand est", "GES"),
    ("hauts-de-france", "HDF"), ("hauts de france", "HDF"),
    ("npdc", "HDF"), ("picardie", "HDF"),
    ("ile-de-france", "IDF"), ("ile de france", "IDF"),
    ("île de france", "IDF"), ("idf", "IDF"),
    ("normandie", "NOR"),
    ("nouvelle-aquitaine", "NAQ"), ("nouvelle aquitaine", "NAQ"),
    ("alpc", "NAQ"),
    ("occitanie", "OCC"),
    ("pays de la loire", "PDL"),
    ("provence-alpes", "PACA"), ("provence alpes", "PACA"), (" paca", "PACA"),
    ("guadeloupe", "GUA"), ("martinique", "MAR"), ("guyane", "GUY"),
    ("la reunion", "REU"), ("la réunion", "REU"), ("mayotte", "MAY"),
    (" dg", "DG"), ("dsi france travail", "DG"), ("dga tech", "DG"),
]

DEPARTEMENT_VERS_REGION = {
    "75": "IDF", "77": "IDF", "78": "IDF", "91": "IDF",
    "92": "IDF", "93": "IDF", "94": "IDF", "95": "IDF",
    "02": "HDF", "59": "HDF", "60": "HDF", "62": "HDF", "80": "HDF",
    "16": "NAQ", "17": "NAQ", "19": "NAQ", "23": "NAQ", "24": "NAQ",
    "33": "NAQ", "40": "NAQ", "47": "NAQ", "64": "NAQ", "79": "NAQ",
    "86": "NAQ", "87": "NAQ",
    "01": "ARA", "03": "ARA", "07": "ARA", "15": "ARA", "26": "ARA",
    "38": "ARA", "42": "ARA", "43": "ARA", "63": "ARA", "69": "ARA",
    "73": "ARA", "74": "ARA",
    "21": "BFC", "25": "BFC", "39": "BFC", "58": "BFC", "70": "BFC",
    "71": "BFC", "89": "BFC", "90": "BFC",
    "22": "BRE", "29": "BRE", "35": "BRE", "56": "BRE",
    "18": "CVL", "28": "CVL", "36": "CVL", "37": "CVL", "41": "CVL", "45": "CVL",
    "2A": "COR", "2B": "COR",
    "08": "GES", "10": "GES", "51": "GES", "52": "GES", "54": "GES",
    "55": "GES", "57": "GES", "67": "GES", "68": "GES", "88": "GES",
    "14": "NOR", "27": "NOR", "50": "NOR", "61": "NOR", "76": "NOR",
    "09": "OCC", "11": "OCC", "12": "OCC", "30": "OCC", "31": "OCC",
    "32": "OCC", "34": "OCC", "46": "OCC", "48": "OCC", "65": "OCC",
    "66": "OCC", "81": "OCC", "82": "OCC",
    "44": "PDL", "49": "PDL", "53": "PDL", "72": "PDL", "85": "PDL",
    "04": "PACA", "05": "PACA", "06": "PACA", "13": "PACA",
    "83": "PACA", "84": "PACA",
    "971": "GUA", "972": "MAR", "973": "GUY", "974": "REU", "976": "MAY",
}

ACHETEUR_VERS_DEPARTEMENT = [
    ("guadeloupe", "971"), ("martinique", "972"), ("guyane", "973"),
    ("la reunion", "974"), ("mayotte", "976"),
    ("ville de paris", "75"), ("mairie de paris", "75"),
    ("ville de marseille", "13"), ("ville de lyon", "69"),
    ("ville de toulouse", "31"), ("ville de bordeaux", "33"),
    ("ville de lille", "59"), ("ville de nantes", "44"),
    ("ville de strasbourg", "67"), ("ville de nice", "06"),
    ("ville de saint-denis", "93"), ("ville de sallanches", "74"),
    ("lot-et-garonne", "47"),
    # Organismes nationaux dont le siège est en Île-de-France.
    # Heuristique : à défaut d'info précise, on présume Paris/IDF.
    ("ofpra", "75"),
    ("rectorat", None),  # rectorat ambigu, dépend de l'académie ; skip
    ("cnaf", "75"), ("cnam", "75"),
    ("acoss", "92"),
    ("ademe", "49"),  # siège Angers
    ("dila", "75"),  # Direction de l'Information Légale, Paris
    ("dgfip", "75"),
    ("vnf", "62"),  # Voies Navigables de France, siège Béthune
    ("ministere", "75"),  # ministères = Paris par défaut
    ("secretariat general", "75"),
    ("conseil constitutionnel", "75"),
    ("conseil d'etat", "75"),
    ("assemblee nationale", "75"),
    ("senat", "75"),
]


# ===========================================================================
# UTILITAIRES
# ===========================================================================

def _normaliser(texte: str) -> str:
    if not texte:
        return ""
    nfkd = unicodedata.normalize("NFKD", texte.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _detecter_region(acheteur_nom: str) -> Optional[str]:
    if not acheteur_nom:
        return None
    norm = _normaliser(acheteur_nom)
    for indice, code in ACHETEUR_VERS_REGION:
        if indice in norm:
            return code
    if "france travail" in norm or "pole emploi" in norm:
        return "DG"
    return None


def _detecter_departement(acheteur_nom: str,
                          code_postal: Optional[str] = None) -> Optional[str]:
    if code_postal and len(code_postal) >= 2:
        cp = code_postal.strip()
        if cp.startswith("97") and len(cp) >= 3:
            return cp[:3]
        if len(cp) == 5 and cp.isdigit():
            return cp[:2]
        if cp[:2].isdigit():
            return cp[:2]
    if acheteur_nom:
        norm = _normaliser(acheteur_nom)
        for indice, dep in ACHETEUR_VERS_DEPARTEMENT:
            if dep is not None and indice in norm:
                return dep
        m = re.search(r'\((\d{2,3})\)', acheteur_nom)
        if m:
            return m.group(1)
    return None


def _mot_cle_present(mot_cle: str, texte_norm: str) -> bool:
    if not mot_cle or not texte_norm:
        return False
    mot_norm = _normaliser(mot_cle).strip()
    if not mot_norm:
        return False
    try:
        pattern = r'\b' + re.escape(mot_norm) + r'\b'
        return bool(re.search(pattern, texte_norm))
    except re.error:
        return mot_norm in texte_norm


def _motif(critere, satisfait, points, commentaire,
           valeur_organisme=None, valeur_marche=None):
    return {
        "critere": critere,
        "satisfait": satisfait,
        "points": points,
        "commentaire": commentaire,
        "valeur_organisme": valeur_organisme,
        "valeur_marche": valeur_marche,
    }


# ===========================================================================
# DETECTION DU FORMAT ET ROUTAGE
# ===========================================================================

def _est_format_legacy_formation(organisme: dict) -> bool:
    if not organisme:
        return False
    if "presets_couverts" in organisme and "profils_sectoriels" in organisme:
        return False
    legacy = ("thematiques_metiers", "publics_cibles",
              "prestations_maitrisees", "directions_regionales_couvertes")
    return any(m in organisme for m in legacy)


def _resoudre_presets_marche(marche: dict, brief: Optional[dict] = None,
                              presets_marche: Optional[List[str]] = None) -> List[str]:
    if presets_marche:
        return list(presets_marche)
    for cle in ("preset_codes", "presets_cibles"):
        v = marche.get(cle)
        if v:
            return list(v)
    sources = []
    if brief and brief.get("domaines_metier"):
        sources = brief["domaines_metier"]
    elif marche.get("domaines_metier"):
        sources = marche["domaines_metier"]
    if not sources:
        return []
    codes = []
    for d in sources:
        if isinstance(d, dict) and d.get("code"):
            codes.append(d["code"])
        elif isinstance(d, str):
            codes.append(d)
    return _preset.presets_pour_domaines(codes) if codes else []


# ===========================================================================
# EVALUATEURS UNIVERSELS V2
# ===========================================================================

def _eval_thematique_v2(organisme: dict, marche: dict,
                        brief: Optional[dict]) -> dict:
    mots = organisme.get("mots_cles_catalogue", []) or []
    if not mots:
        return _motif("thematique", None, 0,
                      "Pas de mots-cles catalogue sur le profil.")
    texte_brut = marche.get("objet") or marche.get("titre") or ""
    if brief and brief.get("synthese_marche"):
        texte_brut += " " + brief["synthese_marche"]
    objet_norm = _normaliser(texte_brut)
    if not objet_norm:
        return _motif("thematique", None, 0, "Objet du marche vide.")
    trouves = [m for m in mots if _mot_cle_present(m, objet_norm)]
    if len(trouves) >= 2:
        return _motif("thematique", True, 25,
                      f"Match catalogue : {len(trouves)} mots-cles "
                      f"({', '.join(trouves[:5])}).",
                      valeur_organisme=trouves)
    if len(trouves) == 1:
        return _motif("thematique", True, 15,
                      f"Match catalogue partiel : {trouves[0]}.",
                      valeur_organisme=trouves)
    return _motif("thematique", False, 0,
                  "Aucun mot-cle catalogue dans l'objet.")


def _eval_geographie_v2(organisme: dict, marche: dict,
                         brief: Optional[dict]) -> dict:
    zones_profil = organisme.get("zones_intervention", []) or []
    if not zones_profil:
        return _motif("geographie", None, 0,
                      "Zones d'intervention non renseignees sur le profil.")
    code_postal = None
    if brief:
        for cle in ("modalites", "modalites_execution_chantier"):
            mod = brief.get(cle) or {}
            sites = mod.get("sites_execution") or []
            for s in sites:
                if isinstance(s, str):
                    m = re.search(r'\((\d{2,3})\)', s)
                    if m:
                        code_postal = m.group(1)
                        break
            if code_postal:
                break
    # Périmètre BOAMP (ex « Dept 16 ») — source complémentaire du département.
    if not code_postal:
        mp = re.search(r"\b(\d{2,3}|2[AB])\b", str(marche.get("perimetre_geographique") or ""))
        if mp:
            code_postal = mp.group(1)
    dep_marche = _detecter_departement(marche.get("acheteur_nom", ""), code_postal)
    region_marche = _detecter_region(marche.get("acheteur_nom", ""))
    deps_profil = [z for z in zones_profil if z and (z.isdigit() or
                   (len(z) >= 2 and z[:2].isdigit()))]
    regs_profil = [z for z in zones_profil if z and not z[0].isdigit()]
    regs_via_deps = {DEPARTEMENT_VERS_REGION.get(d) for d in deps_profil}
    regs_via_deps.discard(None)
    regs_couvertes = set(regs_profil) | regs_via_deps

    if dep_marche and dep_marche in deps_profil:
        return _motif("geographie", True, 25,
                      f"Match departement direct : {dep_marche}.",
                      valeur_organisme=zones_profil,
                      valeur_marche=dep_marche)
    if dep_marche:
        reg_via_dep = DEPARTEMENT_VERS_REGION.get(dep_marche)
        if reg_via_dep and reg_via_dep in regs_couvertes:
            return _motif("geographie", True, 15,
                          f"Match region : {dep_marche} (region "
                          f"{reg_via_dep}) couvert.",
                          valeur_organisme=list(regs_couvertes),
                          valeur_marche=f"dep {dep_marche} / reg {reg_via_dep}")
    if region_marche and region_marche in regs_couvertes:
        return _motif("geographie", True, 12,
                      f"Match region : {region_marche} couverte.",
                      valeur_organisme=list(regs_couvertes),
                      valeur_marche=region_marche)
    if region_marche == "DG":
        return _motif("geographie", None, 5,
                      "Marche national (DG) — verifier dans le RC.")
    if not dep_marche and not region_marche:
        return _motif("geographie", None, 0,
                      "Zone du marche non identifiee — a verifier.",
                      valeur_marche=marche.get("acheteur_nom"))
    # Hors zone : le marché est géographiquement identifié mais non couvert. On applique
    # une pénalité MODÉRÉE (la géo est un signal, pas un poids qui écrase le score).
    # Si `zones_strict` (acteur de proximité), on ajoute un GO/NO-GO : le marché est
    # filtré en « non pertinent » via le verdict, sans gonfler artificiellement le score.
    zone_m = dep_marche or region_marche
    strict = bool(organisme.get("zones_strict"))
    mo = _motif("geographie", False, -12 if strict else -8,
                f"Hors zone{' (proximité stricte → écarté)' if strict else ''} : marché en "
                f"{zone_m}, profil couvre {zones_profil}.",
                valeur_organisme=zones_profil, valeur_marche=zone_m)
    if strict:
        mo["go_no_go"] = "hors_zone"
    return mo


def _eval_capacite_financiere(organisme: dict, marche: dict,
                               brief: Optional[dict]) -> dict:
    cap = organisme.get("capacite_globale", {}) or {}
    seuil_min = cap.get("seuil_minimum_marche_eur")
    plafond = cap.get("capacite_engagement_simultane")
    montant = None
    if brief:
        mm = brief.get("montant_marche") or {}
        montant = mm.get("valeur_estimee_euros")
    if montant is None:
        return _motif("capacite", None, 0,
                      "Montant marche inconnu — verification manuelle.")
    if seuil_min is not None and montant < seuil_min:
        return _motif("capacite", False, -10,
                      f"Marche estime a {int(montant):,} EUR < seuil minimum "
                      f"{int(seuil_min):,} EUR : pas rentable.",
                      valeur_organisme=seuil_min, valeur_marche=montant)
    if plafond is not None and montant > plafond:
        return _motif("capacite", False, -20,
                      f"Marche estime a {int(montant):,} EUR > capacite "
                      f"d'engagement simultanee {int(plafond):,} EUR : "
                      f"envisager cotraitance.",
                      valeur_organisme=plafond, valeur_marche=montant)
    return _motif("capacite", True, 10,
                  f"Montant {int(montant):,} EUR dans la capacite.",
                  valeur_marche=montant)


def _eval_preset_compatibilite(organisme: dict, marche: dict,
                                presets_marche: List[str]) -> dict:
    presets_profil = organisme.get("presets_couverts") or []
    if not presets_profil:
        return _motif("preset_compatibilite", False, -50,
                      "Profil organisme ne couvre aucun preset.",
                      valeur_organisme=[])
    if not presets_marche:
        return _motif("preset_compatibilite", None, 0,
                      "Marche non classifie sur les presets connus.",
                      valeur_organisme=presets_profil)
    intersection = [p for p in presets_marche if p in presets_profil]
    if not intersection:
        return _motif("preset_compatibilite", False, -30,
                      f"Marche sur {presets_marche}, organisme couvre "
                      f"{presets_profil} : pas d'intersection.",
                      valeur_organisme=presets_profil,
                      valeur_marche=presets_marche)
    # Meilleur preset matché = priorité la plus haute (rang minimal). On valorise selon
    # ce rang : un marché sur l'activité principale vaut plus qu'un marché périphérique.
    best = min(intersection, key=lambda c: _rang_preset(organisme, c))
    rang = _rang_preset(organisme, best)
    pts = PRESET_COMPAT_POINTS.get(rang, PRESET_COMPAT_DEFAULT)
    lib = _LIBELLE_RANG.get(rang, f"rang {rang}")
    return _motif("preset_compatibilite", True, pts,
                  f"Preset(s) commun(s) : {intersection}. Meilleur match : "
                  f"{best} ({lib}).",
                  valeur_organisme=presets_profil,
                  valeur_marche=presets_marche)


# ===========================================================================
# EVALUATEURS SECTORIELS BTP
# ===========================================================================

def _eval_btp_qualifications(profil_btp: dict, brief: Optional[dict]) -> list:
    motifs = []
    quals_profil = (profil_btp or {}).get("qualifications") or {}
    qr = (brief or {}).get("qualifications_requises") or {}

    # Qualibat — on n'évalue que si le marché expose une LISTE de CODES
    # à 4 chiffres. Si le LLM a mis du texte libre ("Non précisé dans le RC")
    # on ignore plutôt que d'itérer caractère par caractère.
    qualibat_marche_raw = qr.get("qualibat")
    qualibat_marche = []
    if isinstance(qualibat_marche_raw, list):
        qualibat_marche = [str(q).strip() for q in qualibat_marche_raw
                           if isinstance(q, str) and len(str(q).strip()) == 4
                           and str(q).strip().isdigit()]
    qualibat_profil_raw = quals_profil.get("qualibat") or []
    qualibat_profil = [str(q).strip() for q in qualibat_profil_raw
                       if isinstance(q, str)]
    if qualibat_marche:
        manquants = [q for q in qualibat_marche if q not in qualibat_profil]
        if not manquants:
            motifs.append(_motif(
                "btp_qualibat", True, 20,
                f"Qualifications Qualibat exigees toutes detenues "
                f"({', '.join(qualibat_marche)}).",
                valeur_organisme=qualibat_profil,
                valeur_marche=qualibat_marche))
        else:
            motifs.append(_motif(
                "btp_qualibat", False, -50,
                f"Qualibat manquante(s) : {', '.join(manquants)}. "
                f"Risque d'irrecevabilite.",
                valeur_organisme=qualibat_profil,
                valeur_marche=qualibat_marche))
    elif qualibat_marche_raw and isinstance(qualibat_marche_raw, str):
        # Le LLM a mis du texte libre : on note mais on ne pénalise pas.
        motifs.append(_motif(
            "btp_qualibat", None, 0,
            "Qualibat mentionnee dans le RC en texte libre (pas de code "
            "exploitable). Verifier manuellement.",
            valeur_marche=qualibat_marche_raw[:80]))

    # RGE
    rge_marche = qr.get("rge")
    rge_profil_obj = quals_profil.get("rge") or {}
    rge_profil = (bool(rge_profil_obj.get("detenue"))
                  if isinstance(rge_profil_obj, dict)
                  else bool(rge_profil_obj))
    if rge_marche:
        if rge_profil:
            motifs.append(_motif("btp_rge", True, 10,
                                 "RGE exige et detenue.",
                                 valeur_organisme=True, valeur_marche=True))
        else:
            motifs.append(_motif("btp_rge", False, -25,
                                 "RGE exige mais non detenue.",
                                 valeur_organisme=False, valeur_marche=True))

    # Amiante (depuis champ autres / autres_certifications)
    autres_exig = (qr.get("autres") or qr.get("autres_certifications") or [])
    if isinstance(autres_exig, list):
        for exig in autres_exig:
            libelle = ""
            if isinstance(exig, dict):
                libelle = (exig.get("libelle") or "").lower()
            elif isinstance(exig, str):
                libelle = exig.lower()
            if "amiante" in libelle:
                amiante = quals_profil.get("amiante") or {}
                if amiante.get("ss3") or amiante.get("ss4"):
                    motifs.append(_motif("btp_amiante", True, 10,
                                         "Habilitation amiante exigee et detenue."))
                else:
                    motifs.append(_motif("btp_amiante", False, -20,
                                         "Habilitation amiante exigee mais "
                                         "absente du profil."))
                break

    return motifs


def _tokens_metier(s: str) -> set:
    """
    Extrait les tokens significatifs d'un libellé corps de métier ou type
    d'ouvrage. Insensible aux séparateurs (_, espaces, /, virgules, tirets)
    et aux accents. Filtre les tokens < 4 caractères et les stop-words.
    Ex: 'cloisons_doublages' -> {'cloisons', 'doublages'}
        'Cloisons modulaires' -> {'cloisons', 'modulaires'}
        -> intersection non vide donc match.
    """
    if not s:
        return set()
    norm = _normaliser(str(s))
    # Découper sur séparateurs courants
    norm = re.sub(r"[_/,\-\(\)]+", " ", norm)
    tokens = norm.split()
    stop = {"des", "les", "une", "pour", "dans", "avec", "etat", "type",
            "lots", "lot", "sous", "type", "objet", "marche"}
    return {t for t in tokens if len(t) >= 4 and t not in stop}


def _eval_btp_corps_metier(profil_btp: dict, brief: Optional[dict]) -> dict:
    profil_ce = (profil_btp or {}).get("corps_de_metier") or []
    if not profil_ce:
        return _motif("btp_corps_metier", None, 0,
                      "Corps de metier non renseignes sur le profil.")
    ctc = (brief or {}).get("caracteristiques_techniques_chantier") or {}
    marche_ce = ctc.get("corps_etat") or []
    if not marche_ce or not isinstance(marche_ce, list):
        return _motif("btp_corps_metier", None, 0,
                      "Corps d'etat du marche non extraits du brief.")

    # Match par tokens partages : pour chaque corps d'etat du marche,
    # on tokenise et on cherche un token commun avec un corps du profil.
    profil_tokens = [_tokens_metier(c) for c in profil_ce]
    matches = []
    for m in marche_ce:
        m_tokens = _tokens_metier(str(m))
        if any(m_tokens & p_tokens for p_tokens in profil_tokens):
            matches.append(m)

    ratio = len(matches) / max(1, len(marche_ce))
    if ratio >= 0.7:
        return _motif("btp_corps_metier", True, 15,
                      f"Couverture corps d'etat tres bonne "
                      f"({len(matches)}/{len(marche_ce)}).",
                      valeur_organisme=profil_ce,
                      valeur_marche=marche_ce)
    if ratio >= 0.4:
        return _motif("btp_corps_metier", True, 8,
                      f"Couverture corps d'etat partielle "
                      f"({len(matches)}/{len(marche_ce)}).",
                      valeur_marche=marche_ce)
    if ratio > 0:
        return _motif("btp_corps_metier", False, 0,
                      f"Couverture corps d'etat faible "
                      f"({len(matches)}/{len(marche_ce)}).",
                      valeur_marche=marche_ce)
    return _motif("btp_corps_metier", False, -5,
                  "Aucun corps d'etat commun.",
                  valeur_marche=marche_ce)


def _eval_btp_types_ouvrages(profil_btp: dict, brief: Optional[dict]) -> dict:
    types_profil = (profil_btp or {}).get("types_ouvrages") or []
    if not types_profil:
        return _motif("btp_types_ouvrages", None, 0,
                      "Types d'ouvrages non renseignes sur le profil.")
    ctc = (brief or {}).get("caracteristiques_techniques_chantier") or {}
    typologie = ctc.get("typologie_ouvrage") or ""
    if not typologie:
        return _motif("btp_types_ouvrages", None, 0,
                      "Typologie d'ouvrage non extraite du brief.")
    # Match par tokens partagés
    tok_marche = _tokens_metier(str(typologie))
    matches = [t for t in types_profil
               if _tokens_metier(t) & tok_marche]
    if matches:
        return _motif("btp_types_ouvrages", True, 10,
                      f"Type d'ouvrage compatible : {matches[0]}.",
                      valeur_organisme=types_profil,
                      valeur_marche=typologie)
    return _motif("btp_types_ouvrages", False, 0,
                  f"Type d'ouvrage '{str(typologie)[:60]}' hors specialites.",
                  valeur_organisme=types_profil,
                  valeur_marche=typologie)


def _eval_btp_capacite_chantier(profil_btp: dict, brief: Optional[dict]) -> dict:
    cap = (profil_btp or {}).get("capacite_chantiers") or {}
    plafond = cap.get("montant_max_par_chantier")
    if plafond is None:
        return _motif("btp_capacite_chantier", None, 0,
                      "Plafond chantier non renseigne.")
    montant = None
    if brief:
        mm = brief.get("montant_marche") or {}
        montant = mm.get("valeur_estimee_euros")
    if montant is None:
        return _motif("btp_capacite_chantier", None, 0,
                      "Montant marche inconnu.")
    if montant > plafond * 1.2:
        return _motif("btp_capacite_chantier", False, -15,
                      f"Marche {int(montant):,} EUR depasse largement le "
                      f"plafond chantier {int(plafond):,} EUR. Cotraitance "
                      f"recommandee.",
                      valeur_organisme=plafond, valeur_marche=montant)
    if montant > plafond:
        return _motif("btp_capacite_chantier", None, -5,
                      f"Marche {int(montant):,} EUR au-dessus du plafond "
                      f"{int(plafond):,} EUR mais accessible.",
                      valeur_organisme=plafond, valeur_marche=montant)
    return _motif("btp_capacite_chantier", True, 5,
                  f"Montant {int(montant):,} EUR dans le plafond chantier.",
                  valeur_marche=montant)


def _eval_sectoriel_btp(profil_btp: dict, brief: Optional[dict]) -> list:
    motifs = []
    motifs.extend(_eval_btp_qualifications(profil_btp, brief))
    motifs.append(_eval_btp_corps_metier(profil_btp, brief))
    motifs.append(_eval_btp_types_ouvrages(profil_btp, brief))
    motifs.append(_eval_btp_capacite_chantier(profil_btp, brief))
    return motifs


# ===========================================================================
# EVALUATEURS SECTORIELS INGENIERIE (Sprint C)
# ===========================================================================
# Calque du bloc BTP, adapte au vocabulaire et aux champs de brief ingenierie.
# Distinction clef : on raisonne ETUDES/MOE (typologie de mission, organigramme
# de competences, montant TRAVAUX supervise) et non TRAVAUX (corps d'etat,
# montant marche). Les champs de brief lus proviennent des blocs sectoriels
# `qualifications_moe` et `caracteristiques_mission_moe` du preset ingenierie.

def _eval_ing_qualifications(profil_ing: dict, brief: Optional[dict]) -> list:
    """
    Go/no-go OPQIBI : calque de _eval_btp_qualifications restreint a l'OPQIBI.

    Meme garde-fou que Qualibat (cf piege 10 passation) : on n'evalue que si le
    marche expose une LISTE de CODES a 4 chiffres. Si le LLM a mis du texte libre
    ("qualifications OPQIBI requises"), on note en neutre plutot que d'iterer
    caractere par caractere. Retourne une liste (0 ou 1 motif) pour coherence
    avec _eval_btp_qualifications.
    """
    motifs = []
    quals_profil = (profil_ing or {}).get("qualifications") or {}
    qm = (brief or {}).get("qualifications_moe") or {}

    opqibi_marche_raw = qm.get("opqibi")
    opqibi_marche = []
    if isinstance(opqibi_marche_raw, list):
        opqibi_marche = [str(q).strip() for q in opqibi_marche_raw
                         if isinstance(q, str) and len(str(q).strip()) == 4
                         and str(q).strip().isdigit()]
    opqibi_profil_raw = quals_profil.get("opqibi") or []
    opqibi_profil = [str(q).strip() for q in opqibi_profil_raw
                     if isinstance(q, str)]
    if opqibi_marche:
        manquants = [q for q in opqibi_marche if q not in opqibi_profil]
        if not manquants:
            motifs.append(_motif(
                "ing_opqibi", True, 20,
                f"Qualifications OPQIBI exigees toutes detenues "
                f"({', '.join(opqibi_marche)}).",
                valeur_organisme=opqibi_profil,
                valeur_marche=opqibi_marche))
        else:
            motifs.append(_motif(
                "ing_opqibi", False, -50,
                f"OPQIBI manquante(s) : {', '.join(manquants)}. "
                f"Risque d'irrecevabilite.",
                valeur_organisme=opqibi_profil,
                valeur_marche=opqibi_marche))
    elif opqibi_marche_raw and isinstance(opqibi_marche_raw, str):
        motifs.append(_motif(
            "ing_opqibi", None, 0,
            "OPQIBI mentionnee en texte libre, verifier manuellement.",
            valeur_marche=opqibi_marche_raw[:80]))
    return motifs


def _eval_ing_assurances(profil_ing: dict, brief: Optional[dict]) -> list:
    """
    Decennale ingenierie + RC pro. Retourne 0 a 2 motifs : on n'evalue chaque
    assurance que si elle est explicitement exigee dans le brief (alertes
    candidat ou qualifications_moe.autres). Sinon silence.
    """
    motifs = []
    assur = (profil_ing or {}).get("assurances") or {}

    # Detection "exigee" : on scanne les alertes candidat (universel) et le
    # champ libre qualifications_moe.autres.
    textes = []
    for s in ((brief or {}).get("alertes_candidat") or []):
        if isinstance(s, str):
            textes.append(s)
    qm = (brief or {}).get("qualifications_moe") or {}
    for s in (qm.get("autres") or []):
        if isinstance(s, str):
            textes.append(s)
    blob = _normaliser(" ".join(textes))

    decennale_exigee = "decennale" in blob
    rc_exigee = ("rc pro" in blob or "rc professionnelle" in blob
                 or "responsabilite civile" in blob)

    if decennale_exigee:
        dec = assur.get("decennale_ingenierie") or {}
        if dec.get("detenue"):
            motifs.append(_motif(
                "ing_decennale", True, 10,
                "Assurance decennale ingenierie exigee et detenue."))
        else:
            motifs.append(_motif(
                "ing_decennale", False, -25,
                "Assurance decennale ingenierie exigee mais non detenue."))
    if rc_exigee:
        rc = assur.get("rc_pro") or {}
        if rc.get("detenue"):
            motifs.append(_motif(
                "ing_rc_pro", True, 5,
                "RC professionnelle exigee et detenue."))
        else:
            motifs.append(_motif(
                "ing_rc_pro", False, -15,
                "RC professionnelle exigee mais non detenue."))
    return motifs


def _eval_ing_typologies_mission(profil_ing: dict, brief: Optional[dict]) -> dict:
    """
    Adequation entre la typologie de mission du marche (string libre du brief)
    et les typologies couvertes par le cabinet. Match par tokens partages.
    Ratio = tokens partages / tokens du brief.
    """
    typ_profil = (profil_ing or {}).get("typologies_couvertes") or []
    if not typ_profil:
        return _motif("ing_typologies", None, 0,
                      "Typologies de mission non renseignees sur le profil.")
    cmm = (brief or {}).get("caracteristiques_mission_moe") or {}
    typologie = cmm.get("typologie") or ""
    if not typologie:
        return _motif("ing_typologies", None, 0,
                      "Typologie de mission non extraite du brief.")
    tok_marche = _tokens_metier(str(typologie))
    if not tok_marche:
        return _motif("ing_typologies", None, 0,
                      "Typologie de mission non exploitable (pas de token).")
    profil_tokens = set()
    for t in typ_profil:
        profil_tokens |= _tokens_metier(t)
    partages = tok_marche & profil_tokens
    ratio = len(partages) / max(1, len(tok_marche))
    if ratio >= 0.7:
        return _motif("ing_typologies", True, 15,
                      f"Typologie de mission tres bien couverte "
                      f"({len(partages)}/{len(tok_marche)} tokens).",
                      valeur_organisme=typ_profil, valeur_marche=typologie)
    if ratio >= 0.4:
        return _motif("ing_typologies", True, 8,
                      f"Typologie de mission partiellement couverte "
                      f"({len(partages)}/{len(tok_marche)} tokens).",
                      valeur_marche=typologie)
    if ratio > 0:
        return _motif("ing_typologies", False, 0,
                      f"Typologie de mission faiblement couverte "
                      f"({len(partages)}/{len(tok_marche)} tokens).",
                      valeur_marche=typologie)
    return _motif("ing_typologies", False, -5,
                  "Typologie de mission hors positionnement.",
                  valeur_organisme=typ_profil, valeur_marche=typologie)


def _eval_ing_competences_specialisees(profil_ing: dict,
                                       brief: Optional[dict]) -> dict:
    """
    Adequation entre les profils exiges dans l'organigramme attendu du marche
    et les disciplines declarees par le cabinet. Match par tokens partages.
    ratio = profils couverts / profils exiges.

    Seuil "tres bonne" a 0.8 (vs 0.7 BTP) : un BET de 30-100 ETP couvre
    rarement 100% des disciplines, 4/5 est le bon palier.
    """
    comp_profil = (profil_ing or {}).get("competences_specialisees") or []
    if not comp_profil:
        return _motif("ing_competences", None, 0,
                      "Competences specialisees non renseignees sur le profil.")
    cmm = (brief or {}).get("caracteristiques_mission_moe") or {}
    organigramme = cmm.get("organigramme_attendu") or []
    if not organigramme or not isinstance(organigramme, list):
        return _motif("ing_competences", None, 0,
                      "Organigramme attendu non extrait du brief.")
    profils_exiges = []
    for o in organigramme:
        if isinstance(o, dict) and isinstance(o.get("profil"), str):
            profils_exiges.append(o["profil"])
        elif isinstance(o, str):
            profils_exiges.append(o)
    if not profils_exiges:
        return _motif("ing_competences", None, 0,
                      "Aucun profil exploitable dans l'organigramme.")
    comp_tokens = [_tokens_metier(c) for c in comp_profil]
    couverts = 0
    for p in profils_exiges:
        p_tokens = _tokens_metier(str(p))
        if any(p_tokens & c_tokens for c_tokens in comp_tokens):
            couverts += 1
    ratio = couverts / max(1, len(profils_exiges))
    if ratio >= 0.8:
        return _motif("ing_competences", True, 20,
                      f"Couverture des disciplines exigees tres bonne "
                      f"({couverts}/{len(profils_exiges)}).",
                      valeur_organisme=comp_profil)
    if ratio >= 0.5:
        return _motif("ing_competences", True, 10,
                      f"Couverture des disciplines exigees correcte "
                      f"({couverts}/{len(profils_exiges)}).")
    if ratio > 0:
        return _motif("ing_competences", True, 5,
                      f"Couverture des disciplines exigees partielle "
                      f"({couverts}/{len(profils_exiges)}).")
    return _motif("ing_competences", False, -5,
                  "Aucune discipline exigee couverte par le cabinet.")


def _eval_ing_types_ouvrages(profil_ing: dict, brief: Optional[dict]) -> dict:
    """
    Compatibilite type d'ouvrage. Strictement calque sur
    _eval_btp_types_ouvrages, sur types_ouvrages_etudies du profil et
    caracteristiques_mission_moe.typologie_ouvrage du brief.
    """
    types_profil = (profil_ing or {}).get("types_ouvrages_etudies") or []
    if not types_profil:
        return _motif("ing_types_ouvrages", None, 0,
                      "Types d'ouvrages non renseignes sur le profil.")
    cmm = (brief or {}).get("caracteristiques_mission_moe") or {}
    typologie = cmm.get("typologie_ouvrage") or ""
    if not typologie:
        return _motif("ing_types_ouvrages", None, 0,
                      "Typologie d'ouvrage non extraite du brief.")
    tok_marche = _tokens_metier(str(typologie))
    matches = [t for t in types_profil if _tokens_metier(t) & tok_marche]
    if matches:
        return _motif("ing_types_ouvrages", True, 10,
                      f"Type d'ouvrage compatible : {matches[0]}.",
                      valeur_organisme=types_profil, valeur_marche=typologie)
    return _motif("ing_types_ouvrages", False, 0,
                  f"Type d'ouvrage '{str(typologie)[:60]}' hors specialites.",
                  valeur_organisme=types_profil, valeur_marche=typologie)


def _eval_ing_capacite_etudes(profil_ing: dict, brief: Optional[dict]) -> dict:
    """
    Capacite a superviser un projet d'un certain montant TRAVAUX. Strictement
    calque sur _eval_btp_capacite_chantier, mais sur
    capacite_etudes.montant_travaux_max_supervisable (profil) et
    caracteristiques_mission_moe.montant_travaux_estime (brief) — c'est le cout
    des travaux qui dimensionne la mission MOE, pas le montant honoraires.
    """
    cap = (profil_ing or {}).get("capacite_etudes") or {}
    plafond = cap.get("montant_travaux_max_supervisable")
    if plafond is None:
        return _motif("ing_capacite_etudes", None, 0,
                      "Plafond de montant travaux supervisable non renseigne.")
    cmm = (brief or {}).get("caracteristiques_mission_moe") or {}
    montant = cmm.get("montant_travaux_estime")
    if montant is None:
        return _motif("ing_capacite_etudes", None, 0,
                      "Montant travaux du marche inconnu.")
    if montant > plafond * 1.2:
        return _motif("ing_capacite_etudes", False, -15,
                      f"Travaux {int(montant):,} EUR depassent largement le "
                      f"plafond supervisable {int(plafond):,} EUR. Cotraitance "
                      f"recommandee.",
                      valeur_organisme=plafond, valeur_marche=montant)
    if montant > plafond:
        return _motif("ing_capacite_etudes", None, -5,
                      f"Travaux {int(montant):,} EUR au-dessus du plafond "
                      f"{int(plafond):,} EUR mais accessible.",
                      valeur_organisme=plafond, valeur_marche=montant)
    return _motif("ing_capacite_etudes", True, 5,
                  f"Travaux {int(montant):,} EUR dans le plafond supervisable.",
                  valeur_marche=montant)


def _eval_sectoriel_ingenierie(profil_ing: dict, brief: Optional[dict]) -> list:
    motifs = []
    motifs.extend(_eval_ing_qualifications(profil_ing, brief))
    motifs.extend(_eval_ing_assurances(profil_ing, brief))
    motifs.append(_eval_ing_typologies_mission(profil_ing, brief))
    motifs.append(_eval_ing_competences_specialisees(profil_ing, brief))
    motifs.append(_eval_ing_types_ouvrages(profil_ing, brief))
    motifs.append(_eval_ing_capacite_etudes(profil_ing, brief))
    return motifs


# ===========================================================================
# EVALUATEUR SECTORIEL ÉNERGIES RENOUVELABLES
# ===========================================================================

# Familles de technologies EnR → mots-clés (normalisés sans accent) repérables dans
# l'objet du marché OU dans les valeurs `technologies_maitrisees` du profil.
_ENR_FAMILLES = {
    "photovoltaïque": ("photovolta", "panneau solaire", "panneaux solaire",
                       "centrale solaire", "ombriere", "agrivolta", "solaire pv"),
    "éolien": ("eolien", "eolienne"),
    "méthanisation/biomasse": ("methanis", "biogaz", "biomasse", "bois energie",
                               "chaufferie bois"),
    "géothermie": ("geotherm",),
    "pompe à chaleur": ("pompe a chaleur", "aerothermie"),
    "solaire thermique": ("solaire thermique", "eau chaude solaire"),
    "réseau de chaleur": ("reseau de chaleur", "reseau chaleur"),
    "hydraulique": ("hydroelec", "hydrolien", "microcentrale", "micro-hydro"),
    "stockage": ("stockage", "batterie"),
    "hydrogène": ("hydrogene",),
}

# Orientation de prestation EnR (le candidat FAIT quoi ?) → mots-clés.
_ENR_PRESTA = {
    "études/AMO": ("etude", "faisabilite", "opportunite", "amo", "assistance maitrise",
                   "diagnostic", "audit", "schema directeur", "developpement",
                   "conseil", "maitrise oeuvre", "maitrise d oeuvre", "programmation"),
    "travaux/fourniture": ("installation", "fourniture et pose", "fourniture pose",
                           "travaux", "construction", "pose de", "raccordement",
                           "cle en main", "clef en main", "realisation"),
    "exploitation/maintenance": ("maintenance", "exploitation", "supervision",
                                 "monitoring", "telegestion"),
}


def _familles_depuis(textes, familles_map) -> set:
    """Familles dont au moins un mot-clé apparaît dans l'un des textes (normalisés)."""
    corpus = " ".join(_normaliser(str(t)) for t in textes if t)
    return {fam for fam, kws in familles_map.items() if any(k in corpus for k in kws)}


def _eval_sectoriel_energie_renouvelable(profil_enr: dict, brief: Optional[dict],
                                          marche: dict) -> list:
    motifs = []
    b = brief or {}
    # Corpus du marché : objet/titre + synthèse + codes domaines.
    corpus_marche = [marche.get("objet"), marche.get("titre"), b.get("synthese_marche")]
    corpus_marche += [d.get("code") for d in (b.get("domaines_metier") or [])
                      if isinstance(d, dict)]

    # ---- 1) Technologie maîtrisée ET demandée ----
    prof_fam = _familles_depuis(profil_enr.get("technologies_maitrisees") or [], _ENR_FAMILLES)
    marche_fam = _familles_depuis(corpus_marche, _ENR_FAMILLES)
    if not prof_fam:
        motifs.append(_motif("enr_technologie", None, 0,
                             "Technologies EnR non renseignees au profil."))
    elif not marche_fam:
        motifs.append(_motif("enr_technologie", None, 0,
                             "Aucune technologie EnR identifiee dans le marche."))
    else:
        commun = prof_fam & marche_fam
        if commun:
            motifs.append(_motif("enr_technologie", True, 22,
                                 f"Technologie EnR maitrisee et demandee : {', '.join(sorted(commun))}.",
                                 valeur_organisme=sorted(prof_fam),
                                 valeur_marche=sorted(marche_fam)))
        else:
            motifs.append(_motif("enr_technologie", False, -8,
                                 f"Marche EnR sur {', '.join(sorted(marche_fam))} hors "
                                 f"technologies du profil ({', '.join(sorted(prof_fam))}).",
                                 valeur_organisme=sorted(prof_fam),
                                 valeur_marche=sorted(marche_fam)))

    # ---- 2) Type de prestation (le candidat FAIT-il ce que le marché demande ?) ----
    prof_presta = _familles_depuis(profil_enr.get("types_prestations") or [], _ENR_PRESTA)
    marche_presta = _familles_depuis(corpus_marche, _ENR_PRESTA)
    if prof_presta and marche_presta:
        if prof_presta & marche_presta:
            motifs.append(_motif("enr_prestation", True, 8,
                                 f"Type de prestation couvert : {', '.join(sorted(prof_presta & marche_presta))}.",
                                 valeur_organisme=sorted(prof_presta),
                                 valeur_marche=sorted(marche_presta)))
        else:
            motifs.append(_motif("enr_prestation", False, -6,
                                 f"Le marche attend {', '.join(sorted(marche_presta))} ; "
                                 f"le profil fait {', '.join(sorted(prof_presta))} (inadequation de role).",
                                 valeur_organisme=sorted(prof_presta),
                                 valeur_marche=sorted(marche_presta)))

    # ---- 3) Segment client (bonus léger) ----
    seg = profil_enr.get("segments_clients") or []
    if seg and any("collectivite" in _normaliser(str(s)) or "etat" in _normaliser(str(s))
                   for s in seg):
        # Acheteur public probable (cas dominant) → petit alignement.
        motifs.append(_motif("enr_segment", True, 3,
                             "Cible clients publics alignee avec l'acheteur."))
    return motifs


def _eval_sectoriel_placeholder(code_preset: str, profil_sec: dict,
                                 brief: Optional[dict]) -> list:
    """Stub Sprint C pour conseil, IT, formation."""
    n_rempli = sum(1 for v in (profil_sec or {}).values() if v) if profil_sec else 0
    return [_motif(
        f"sectoriel_{code_preset}", None, 0,
        f"Motifs sectoriels {code_preset} a implementer (Sprint C). "
        f"Profil charge : {n_rempli} sections renseignees.")]


def _eval_synergie_v2(motifs: list) -> dict:
    score_them = next((m["points"] for m in motifs if m["critere"] == "thematique"), 0)
    score_geo = next((m["points"] for m in motifs if m["critere"] == "geographie"), 0)
    score_preset = next((m["points"] for m in motifs if m["critere"] == "preset_compatibilite"), 0)
    if score_them >= 15 and score_geo >= 15 and score_preset >= 20:
        return _motif("synergie", True, 10,
                      "Thematique + geographie + preset alignes — candidature "
                      "naturelle.")
    return _motif("synergie", None, 0, "")


# ===========================================================================
# VERDICT GLOBAL
# ===========================================================================

def _calculer_verdict(score: int, motifs: list) -> str:
    for m in motifs:
        # Go/no-go explicite (ex : hors zone d'un acteur de proximité stricte).
        if m.get("go_no_go"):
            return "non_pertinent"
        if m["critere"] in ("btp_qualibat", "qualiopi", "ing_opqibi") and m["satisfait"] is False and m["points"] <= -25:
            return "non_pertinent"
    if score >= SEUIL_TRES_PERTINENT:
        return "tres_pertinent"
    if score >= SEUIL_PERTINENT:
        return "pertinent"
    if score >= SEUIL_A_VERIFIER:
        return "a_verifier"
    return "non_pertinent"


# ===========================================================================
# API PUBLIQUE
# ===========================================================================

def evaluer(organisme: dict, marche: dict,
            brief: Optional[dict] = None,
            presets_marche: Optional[List[str]] = None) -> dict:
    """Evalue la pertinence d'un marche pour l'organisme."""
    if _est_format_legacy_formation(organisme):
        return _evaluer_legacy(organisme, marche)
    return _evaluer_v2(organisme, marche, brief, presets_marche)


def _evaluer_v2(organisme: dict, marche: dict,
                brief: Optional[dict],
                presets_marche: Optional[List[str]]) -> dict:
    presets_marche = _resoudre_presets_marche(marche, brief, presets_marche)
    presets_profil = organisme.get("presets_couverts") or []
    sectoriels = organisme.get("profils_sectoriels") or {}

    motifs = []
    motifs.append(_eval_preset_compatibilite(organisme, marche, presets_marche))
    motifs.append(_eval_thematique_v2(organisme, marche, brief))
    motifs.append(_eval_geographie_v2(organisme, marche, brief))
    motifs.append(_eval_capacite_financiere(organisme, marche, brief))

    intersection = [p for p in presets_marche if p in presets_profil]
    for code in intersection:
        profil_sec = sectoriels.get(code) or {}
        if code == "btp":
            secm = _eval_sectoriel_btp(profil_sec, brief)
        elif code == "ingenierie":
            secm = _eval_sectoriel_ingenierie(profil_sec, brief)
        elif code == "energie_renouvelable":
            secm = _eval_sectoriel_energie_renouvelable(profil_sec, brief, marche)
        else:
            secm = _eval_sectoriel_placeholder(code, profil_sec, brief)
        # Atténue les signaux sectoriels POSITIFS selon le rang du preset (cœur vs périphérie).
        facteur = PRESET_FACTEUR_SECTORIEL.get(_rang_preset(organisme, code),
                                               PRESET_FACTEUR_DEFAULT)
        motifs.extend(_ponderer_motifs_sectoriels(secm, facteur))

    motifs.append(_eval_synergie_v2(motifs))

    score_brut = sum(m["points"] for m in motifs)
    score = max(0, min(100, score_brut))
    # Go/no-go (ex : hors-zone d'un acteur de proximité stricte) → marché DISQUALIFIÉ.
    # On plafonne le score bas pour qu'il soit cohérent avec le verdict non_pertinent
    # (sinon un marché « non pertinent » afficherait un score élevé) et qu'il sombre au tri.
    if any(m.get("go_no_go") for m in motifs):
        score = min(score, 12)
    verdict = _calculer_verdict(score, motifs)
    return {
        "id_marche": marche.get("id", "?"),
        "score": score,
        "verdict": verdict,
        "motifs": motifs,
        "presets_marche": presets_marche,
        "presets_profil": presets_profil,
        "_version": "v2",
    }


# ===========================================================================
# CODE LEGACY V1 (formation Apptia, preserve pour compat ascendante)
# ===========================================================================

def _evaluer_legacy(organisme: dict, marche: dict) -> dict:
    motifs = [
        _eval_qualiopi_legacy(organisme, marche),
        _eval_thematique_legacy(organisme, marche),
        _eval_geographie_legacy(organisme, marche),
        _eval_categorie_legacy(organisme, marche),
    ]
    motifs.append(_eval_synergie_legacy(motifs))
    score_brut = sum(m["points"] for m in motifs)
    score = max(0, min(100, score_brut))
    verdict = _calculer_verdict(score, motifs)
    return {
        "id_marche": marche.get("id", "?"),
        "score": score,
        "verdict": verdict,
        "motifs": motifs,
        "_version": "v1_legacy",
    }


def _eval_qualiopi_legacy(organisme, marche):
    cat = (marche.get("categorie_metier") or "").lower()
    requise = cat in ("formation", "insertion")
    certs = organisme.get("certifications", {}) or {}
    qualiopi = any([certs.get("qualiopi_actions_formation"),
                    certs.get("qualiopi_apprentissage"),
                    certs.get("qualiopi_bilans")])
    if not requise:
        return _motif("qualiopi", None, 0,
                      f"Categorie '{cat or 'inconnue'}' — Qualiopi non requise.")
    if not qualiopi:
        return _motif("qualiopi", False, -100,
                      "Qualiopi absent — non eligible.",
                      valeur_organisme="aucune", valeur_marche="requise")
    return _motif("qualiopi", True, 10, "Qualiopi present.")


def _eval_thematique_legacy(organisme, marche):
    mots = organisme.get("mots_cles_catalogue", []) or []
    objet_norm = _normaliser(marche.get("objet", ""))
    if not mots or not objet_norm:
        return _motif("thematique", None, 0, "Donnees insuffisantes.")
    trouves = [m for m in mots if _mot_cle_present(m, objet_norm)]
    if len(trouves) >= 2:
        return _motif("thematique", True, 50,
                      f"Match catalogue : {len(trouves)}.", valeur_organisme=trouves)
    if len(trouves) == 1:
        return _motif("thematique", True, 30,
                      f"Match partiel : {trouves[0]}.", valeur_organisme=trouves)
    return _motif("thematique", False, 0, "Aucun mot-cle trouve.")


def _eval_geographie_legacy(organisme, marche):
    region = _detecter_region(marche.get("acheteur_nom", ""))
    dr_organisme = organisme.get("directions_regionales_couvertes", []) or []
    if not dr_organisme:
        return _motif("geographie", None, 0, "DR non renseignees.")
    if not region:
        return _motif("geographie", None, 5, "Region non identifiee.")
    if region == "DG":
        return _motif("geographie", True, 10, "Marche DG / national.",
                      valeur_organisme=dr_organisme, valeur_marche="DG")
    if region in dr_organisme:
        return _motif("geographie", True, 25,
                      f"Marche en DR {region}.",
                      valeur_organisme=dr_organisme, valeur_marche=region)
    return _motif("geographie", False, 0,
                  f"DR {region} non couverte.",
                  valeur_organisme=dr_organisme, valeur_marche=region)


def _eval_categorie_legacy(organisme, marche):
    cat = marche.get("categorie_metier", "")
    prestations = organisme.get("prestations_maitrisees", []) or []
    if not prestations:
        return _motif("categorie", None, 5, "Prestations non renseignees.")
    prestations_norm = {_normaliser(p) for p in prestations}
    formation_set = {"afc", "afpr", "poec", "poei",
                     "formation_diplomante", "formation_certifiante",
                     "formation_continue"}
    insertion_set = {"activ_seniors", "activ_decouverte", "activ_crea",
                     "activ_emergence", "agil_cadres", "mile", "creascope",
                     "bilan_competences"}
    if cat == "formation" and (prestations_norm & formation_set):
        return _motif("categorie", True, 15, "Categorie formation OK.")
    if cat == "insertion" and (prestations_norm & insertion_set):
        return _motif("categorie", True, 15, "Categorie insertion OK.")
    if cat in ("formation", "insertion"):
        return _motif("categorie", False, -5,
                      f"Categorie {cat}, prestations correspondantes absentes.")
    return _motif("categorie", None, 0, "Categorie indeterminee.")


def _eval_synergie_legacy(motifs):
    them = next((m for m in motifs if m["critere"] == "thematique"), None)
    geo = next((m for m in motifs if m["critere"] == "geographie"), None)
    if them and geo and them["points"] >= 30 and geo["points"] >= 25:
        return _motif("synergie", True, 5, "Thematique + geographie alignees.")
    return _motif("synergie", None, 0, "")


# ===========================================================================
# API BATCH
# ===========================================================================

def evaluer_tous(organisme: dict, marches, briefs: Optional[dict] = None) -> list:
    """Evalue tous les marches d'une collection."""
    if isinstance(marches, dict):
        items = marches.values()
    else:
        items = marches
    briefs = briefs or {}
    evals = []
    for m in items:
        mid = m.get("id")
        brief = briefs.get(mid) if mid else None
        evals.append(evaluer(organisme, m, brief=brief))
    evals.sort(key=lambda e: e["score"], reverse=True)
    return evals
