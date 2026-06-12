"""
concurrence.py
--------------
Moteur d'analyse concurrentielle Tendia.

Analyse les marchés notifiés (collection `marches_notifies`) pour produire
une vue de "qui gagne quoi" chez France Travail :

- Top titulaires par catégorie (formation / insertion)
- Statistiques de montants par catégorie et par titulaire
- Répartition géographique par DR
- Croisement avec les presets : pour un secteur donné, qui sont les
  vrais concurrents historiques ?

Aucune IA. Logique déterministe sur les données DECP brutes.
"""

import statistics
import unicodedata
from collections import Counter, defaultdict
from typing import Optional


def _normaliser(texte: str) -> str:
    if not texte:
        return ""
    nfkd = unicodedata.normalize("NFKD", texte.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# DR France Travail — mapping libellé acheteur → code
# Réutilise la logique de matching.py
ACHETEUR_VERS_DR = [
    ("auvergne", "ARA"), ("rhone alpes", "ARA"), ("rhône-alpes", "ARA"),
    (" ara", "ARA"),
    ("bourgogne", "BFC"), ("franche-comte", "BFC"),
    ("bretagne", "BRE"),
    ("centre-val", "CVL"), ("centre val", "CVL"), (" cvl", "CVL"),
    ("corse", "COR"),
    ("grand est", "GES"),
    ("hauts-de-france", "HDF"), ("hauts de france", "HDF"),
    ("npdc", "HDF"), ("picardie", "HDF"),
    ("ile-de-france", "IDF"), ("ile de france", "IDF"),
    ("île de france", "IDF"), (" idf", "IDF"),
    ("normandie", "NOR"),
    ("nouvelle-aquitaine", "NAQ"), ("nouvelle aquitaine", "NAQ"),
    ("alpc", "NAQ"),
    ("occitanie", "OCC"), ("pays de la loire", "PDL"),
    ("provence-alpes", "PACA"), ("provence alpes", "PACA"), (" paca", "PACA"),
    ("guadeloupe", "GUA"), ("martinique", "MAR"), ("guyane", "GUY"),
    ("la reunion", "REU"), ("la réunion", "REU"), ("mayotte", "MAY"),
]

# Pour DECP, on peut aussi déduire la DR depuis l'acheteur_id (SIRET de
# l'établissement) — mais on n'a pas de mapping fiable.
# Heuristique : on regarde le libellé acheteur_nom s'il existe, sinon on
# essaie le lieu_execution.


def deduire_dr(marche: dict) -> Optional[str]:
    """Déduit la DR France Travail d'un marché DECP.

    Priorité 1 (nouveau DECP consolidée) : `acheteur_region_code` directement
    servi par l'API. Pas de regex, déterministe, fiable.

    Fallback (compatibilité avec ancien format) : heuristique sur
    `acheteur_nom` puis `lieu_execution`.
    """
    # Mapping code région INSEE → code DR France Travail
    _CODE_REGION_VERS_DR = {
        "11": "IDF",   # Île-de-France
        "24": "CVL",   # Centre-Val de Loire
        "27": "BFC",   # Bourgogne-Franche-Comté
        "28": "NOR",   # Normandie
        "32": "HDF",   # Hauts-de-France
        "44": "GES",   # Grand Est
        "52": "PDL",   # Pays de la Loire
        "53": "BRE",   # Bretagne
        "75": "NAQ",   # Nouvelle-Aquitaine
        "76": "OCC",   # Occitanie
        "84": "ARA",   # Auvergne-Rhône-Alpes
        "93": "PACA",  # Provence-Alpes-Côte d'Azur
        "94": "COR",   # Corse
        "01": "GUA",   # Guadeloupe
        "02": "MAR",   # Martinique
        "03": "GUY",   # Guyane
        "04": "REU",   # La Réunion
        "06": "MAY",   # Mayotte
    }
    region_code = (marche.get("acheteur_region_code") or "").strip()
    if region_code in _CODE_REGION_VERS_DR:
        return _CODE_REGION_VERS_DR[region_code]

    # Fallback ancien format
    nom_norm = _normaliser(marche.get("acheteur_nom") or "")
    for indice, code in ACHETEUR_VERS_DR:
        if indice in nom_norm:
            return code
    # Sinon depuis le lieu_execution
    lieu_norm = _normaliser(marche.get("lieu_execution") or "")
    for indice, code in ACHETEUR_VERS_DR:
        if indice in lieu_norm:
            return code
    return None


# ---------------------------------------------------------------------------
# Stats utilitaires
# ---------------------------------------------------------------------------

def _stats_montants(montants: list) -> dict:
    nums = [m for m in montants if m is not None and m > 0]
    if not nums:
        return {"n": 0}
    nums.sort()
    n = len(nums)
    return {
        "n": n,
        "min": round(min(nums), 2),
        "max": round(max(nums), 2),
        "moyenne": round(sum(nums) / n, 2),
        "mediane": round(statistics.median(nums), 2),
        "total": round(sum(nums), 2),
    }


# ---------------------------------------------------------------------------
# Analyse globale
# ---------------------------------------------------------------------------

def analyser_global(marches_notifies: dict, titulaires_cache: dict = None) -> dict:
    """
    Vue d'ensemble : nombre de marchés, montants, top titulaires par catégorie.

    Args:
        marches_notifies: dict {id: marché_normalisé}
        titulaires_cache: dict {siret: infos_sirene} — optionnel, pour les noms.

    Returns:
        dict d'analyse complète.
    """
    titulaires_cache = titulaires_cache or {}

    par_cat: dict = defaultdict(list)
    par_titulaire: dict = defaultdict(list)  # SIRET → liste marchés
    par_dr: dict = defaultdict(list)
    montants_par_cat: dict = defaultdict(list)

    for m in marches_notifies.values():
        cat = m.get("categorie_metier", "?")
        par_cat[cat].append(m)
        montants_par_cat[cat].append(m.get("montant_eur"))
        dr = deduire_dr(m)
        if dr:
            par_dr[dr].append(m)
        siret = m.get("titulaire_siret")
        if siret:
            par_titulaire[siret].append(m)

    # Top titulaires (par nombre de marchés, par catégorie)
    top_global = sorted(
        par_titulaire.items(),
        key=lambda kv: (len(kv[1]), sum((m.get("montant_eur") or 0)
                                          for m in kv[1])),
        reverse=True,
    )[:20]

    def _nom(siret):
        info = titulaires_cache.get(siret) or {}
        nom = info.get("nom_complet") or info.get("nom_raison_sociale")
        return nom or f"(SIRET {siret})"

    # Stats par titulaire (top 20)
    top_titulaires_detail = []
    for siret, marches in top_global:
        montants = [m.get("montant_eur") for m in marches]
        cats = Counter(m.get("categorie_metier") for m in marches)
        drs = Counter(deduire_dr(m) for m in marches if deduire_dr(m))
        stats = _stats_montants(montants)
        top_titulaires_detail.append({
            "siret": siret,
            "nom": _nom(siret),
            "nb_marches": len(marches),
            "categories": dict(cats),
            "drs": dict(drs.most_common(5)),
            "montant_total": stats.get("total", 0),
            "montant_moyen": stats.get("moyenne", 0),
            "montant_median": stats.get("mediane", 0),
        })

    # Stats par catégorie
    stats_par_cat = {}
    for cat in par_cat:
        stats_par_cat[cat] = {
            "nb_marches": len(par_cat[cat]),
            "stats_montants_eur": _stats_montants(montants_par_cat[cat]),
        }

    # Stats par DR
    stats_par_dr = {}
    for dr in par_dr:
        montants_dr = [m.get("montant_eur") for m in par_dr[dr]]
        stats_par_dr[dr] = {
            "nb_marches": len(par_dr[dr]),
            "stats_montants_eur": _stats_montants(montants_dr),
        }

    return {
        "nb_marches_total": len(marches_notifies),
        "par_categorie": stats_par_cat,
        "par_dr": stats_par_dr,
        "top_titulaires": top_titulaires_detail,
        "nb_titulaires_uniques": len(par_titulaire),
    }


# ---------------------------------------------------------------------------
# Analyse croisée preset × marchés notifiés
# ---------------------------------------------------------------------------

def _mot_cle_present(mot_cle: str, texte_norm: str) -> bool:
    """Word boundary matching — repris de matching.py pour cohérence."""
    import re
    if not mot_cle or not texte_norm:
        return False
    mot_norm = _normaliser(mot_cle).strip()
    if not mot_norm:
        return False
    # Toujours word boundary : un mot-clé est trimé puis matché comme mot
    # entier. L'ancien bypass "si espaces explicites → in()" provoquait des
    # faux positifs comme "rge " qui matchait dans "charge", "auberge", etc.
    try:
        pattern = r'\b' + re.escape(mot_norm) + r'\b'
        return bool(re.search(pattern, texte_norm))
    except re.error:
        return mot_norm in texte_norm


def filtrer_marches_pour_profil(profil: dict, marches_notifies: dict,
                                  inclure_autre: bool = False) -> dict:
    """
    Filtre les marchés notifiés qui matchent les mots-clés d'un profil.

    Par défaut, exclut les marchés `categorie_metier == "autre"` (travaux,
    IT, fournitures...) qui pollueraient le matching. Par exemple, un profil
    "BTP" matcherait sinon les marchés de travaux gagnés par des
    constructeurs comme SOGEA BTP qui ne sont PAS des organismes de
    formation BTP. Pour inclure ces marchés, passer inclure_autre=True.

    Retourne un dict {id: marché} avec seulement les marchés où au moins
    un mot-clé du catalogue de l'organisme matche l'objet (word boundary).
    """
    mots = profil.get("mots_cles_catalogue", []) or []
    if not mots:
        return {}

    selectionnes = {}
    for mid, m in marches_notifies.items():
        if not inclure_autre and m.get("categorie_metier") == "autre":
            continue
        objet_norm = _normaliser(m.get("objet", ""))
        if any(_mot_cle_present(mc, objet_norm) for mc in mots):
            selectionnes[mid] = m
    return selectionnes


def analyser_pour_profil(profil: dict, marches_notifies: dict,
                          titulaires_cache: dict = None) -> dict:
    """
    Analyse concurrentielle ciblée selon un profil d'organisme.

    Retourne les statistiques sur le sous-ensemble des marchés notifiés
    qui matchent les mots-clés du profil.
    """
    marches_pertinents = filtrer_marches_pour_profil(profil, marches_notifies)
    if not marches_pertinents:
        return {
            "profil_nom": profil.get("_preset", "?"),
            "nb_marches_pertinents": 0,
            "concurrence": None,
        }

    analyse = analyser_global(marches_pertinents, titulaires_cache)
    analyse["profil_nom"] = profil.get("_preset", "?")
    analyse["nb_marches_pertinents"] = len(marches_pertinents)
    return analyse


# ===========================================================================
# B6 — Zone de prix FT (KNN sur comparables DECP)
# ===========================================================================
# Pour un marché actif en cours d'analyse (typiquement avec son brief LLM),
# on cherche les marchés DECP historiques les plus similaires et on calcule
# la zone de prix empirique (Q1/médiane/Q3 des €/mois reprojetés sur la
# durée du marché actuel).
#
# Architecture à 2 types de comparables :
#   1. DECP "standard" : ce qu'on a aujourd'hui (453 marchés validés par
#      le filtre métier + extractions Sonnet). Normalisation €/mois.
#   2. Brief enrichi "or" : un marché actif dont le brief LLM riche a été
#      relié à son attribution DECP plus tard. Slot prévu mais vide
#      aujourd'hui — sera rempli au fil du temps via tendia_relier_brief_decp.
#
# Quand le type "or" sera peuplé, ces comparables auront un poids supérieur
# dans le KNN (POIDS_TYPE_OR = 2.0 vs 1.0 pour DECP standard).

from datetime import datetime as _datetime
import re as _re

# Pondérations de similarité — somme = 1.0
# Affiné v3 : intègre proximité volume, forme prix, RSE, région voisine.
# Le matching public_cible passe en intersection (auparavant égalité stricte).
POIDS_SIMILARITE = {
    "categorie_metier":   0.25,
    "prestation_precise": 0.18,
    "public_cible":       0.12,  # désormais intersection de tags
    "proximite_duree":    0.10,
    "meme_dr":            0.10,
    "proximite_volume":   0.08,  # nouveau : nb bénéficiaires comparable
    "region_proche":      0.05,  # nouveau : DR voisine (consolation géo)
    "meme_forme_prix":    0.04,  # nouveau : forfaitaire vs unitaire
    "rse_aligne":         0.03,  # nouveau : considérations RSE alignées
    "recence":            0.05,
}


# Carte des DR voisines pour le bonus "région_proche" (consolation géo
# quand pas de match exact sur la DR). Inspirée des limites géo réelles.
DR_VOISINES = {
    "IDF":  {"CVL", "NOR", "HDF"},
    "CVL":  {"IDF", "NAQ", "BFC", "ARA", "PDL"},
    "BFC":  {"CVL", "ARA", "GES", "IDF"},
    "NOR":  {"IDF", "HDF", "BRE", "PDL"},
    "HDF":  {"IDF", "NOR", "GES"},
    "GES":  {"BFC", "HDF", "IDF"},
    "PDL":  {"NOR", "BRE", "CVL", "NAQ"},
    "BRE":  {"PDL", "NOR"},
    "NAQ":  {"PDL", "CVL", "OCC", "ARA"},
    "OCC":  {"NAQ", "ARA", "PACA"},
    "ARA":  {"CVL", "BFC", "OCC", "PACA", "NAQ"},
    "PACA": {"OCC", "ARA", "COR"},
    "COR":  {"PACA"},
}

# Bonus de poids quand le comparable est un brief enrichi "or" (vs DECP standard)
POIDS_TYPE_OR = 2.0
POIDS_TYPE_DECP = 1.0

# Top-N comparables à conserver pour le calcul
TOP_N_COMPARABLES = 12

# Mots-clés → prestation_precise canonique (pour inférence depuis le brief
# ou l'objet du marché actuel). Normalisés à la comparaison.
PRESTATION_KEYWORDS = {
    "afc": "AFC", "afpr": "AFPR", "poei": "POEI", "poec": "POEC",
    "activ seniors": "ACTIV_Seniors", "activ' seniors": "ACTIV_Seniors",
    "activ decouverte": "ACTIV_Decouverte", "activ découverte": "ACTIV_Decouverte",
    "activ crea": "ACTIV_Crea", "activ créa": "ACTIV_Crea",
    "activ emergence": "ACTIV_Emergence", "activ émergence": "ACTIV_Emergence",
    "agil cadres": "AGIL_Cadres",
    "mile": "MILE", "mediation interculturelle": "MILE",
    "creascope": "Creascope",
    "bilan de competences": "Bilan_competences", "bilan competences": "Bilan_competences",
    "vae": "VAE",
}

# Mots-clés → public_cible canonique
PUBLIC_KEYWORDS = {
    "seniors": "seniors", "+ 45 ans": "seniors", "+45 ans": "seniors",
    "demandeurs d emploi en reconversion": "demandeurs_emploi_reconversion",
    "jeunes": "jeunes", "neet": "jeunes",
    "cadres": "cadres",
    "rqth": "RQTH",
    "brsa": "BRSA", "beneficiaires du rsa": "BRSA",
    "allophones": "allophones", "interculturel": "allophones",
    "deld": "DELD", "longue duree": "DELD",
    "creation d entreprise": "creation_entreprise",
    "demandeurs d emploi": "demandeurs_emploi",
}

# DR France Travail → indicateurs lieu_execution DECP
# (codes département + libellés région partielle)
DR_VERS_INDICATEURS = {
    "IDF":  ("75", "77", "78", "91", "92", "93", "94", "95",
             "ile-de-france", "île-de-france", "paris"),
    "ARA":  ("01", "03", "07", "15", "26", "38", "42", "43", "63", "69", "73", "74",
             "auvergne", "rhone", "rhône"),
    "NAQ":  ("16", "17", "19", "23", "24", "33", "40", "47", "64", "79", "86", "87",
             "nouvelle-aquitaine", "aquitaine"),
    "OCC":  ("09", "11", "12", "30", "31", "32", "34", "46", "48", "65", "66", "81", "82",
             "occitanie"),
    "HDF":  ("02", "59", "60", "62", "80", "hauts-de-france", "nord"),
    "PACA": ("04", "05", "06", "13", "83", "84", "provence", "paca"),
    "BRE":  ("22", "29", "35", "56", "bretagne"),
    "PDL":  ("44", "49", "53", "72", "85", "pays de la loire"),
    "NOR":  ("14", "27", "50", "61", "76", "normandie"),
    "GES":  ("08", "10", "51", "52", "54", "55", "57", "67", "68", "88", "grand est"),
    "BFC":  ("21", "25", "39", "58", "70", "71", "89", "90",
             "bourgogne", "franche-comte", "franche-comté"),
    "CVL":  ("18", "28", "36", "37", "41", "45", "centre-val", "centre val"),
    "COR":  ("2a", "2b", "20", "corse"),
    "GUA":  ("971", "guadeloupe"),
    "MAR":  ("972", "martinique"),
    "GUY":  ("973", "guyane"),
    "REU":  ("974", "réunion", "reunion"),
    "MAY":  ("976", "mayotte"),
}


def _meme_zone_geo(dr_code: str, lieu_execution: str) -> bool:
    """Vrai si le lieu_execution DECP correspond à la DR France Travail donnée."""
    if not dr_code or not lieu_execution:
        return False
    lieu_norm = _normaliser(lieu_execution)
    indicateurs = DR_VERS_INDICATEURS.get(dr_code, ())
    for ind in indicateurs:
        if ind in lieu_norm:
            return True
    return False


def _inferer_prestation_precise(marche: dict, brief: Optional[dict]) -> Optional[str]:
    """
    Tente d'inférer prestation_precise du marché actuel depuis titre/objet/brief.
    Retourne None si rien de fiable trouvé.
    """
    sources = [marche.get("titre") or "", marche.get("objet") or ""]
    if brief:
        sources.append(brief.get("synthese_marche") or "")
        sources.append((brief.get("publics_cibles") or {}).get("description") or "")
    texte = _normaliser(" ".join(sources))
    for kw, val in PRESTATION_KEYWORDS.items():
        if _normaliser(kw) in texte:
            return val
    return None


def _inferer_public_cible(brief: Optional[dict]) -> Optional[str]:
    """Infère le public_cible depuis le brief LLM (description + signaux)."""
    if not brief:
        return None
    pub = brief.get("publics_cibles") or {}
    desc = pub.get("description") or ""
    specs = " ".join(pub.get("publics_specifiques_signales") or [])
    texte = _normaliser(desc + " " + specs)
    for kw, val in PUBLIC_KEYWORDS.items():
        if _normaliser(kw) in texte:
            return val
    return None


def _extraire_duree_mois_brief(brief: Optional[dict]) -> Optional[int]:
    """Récupère la durée du marché en mois depuis le brief."""
    if not brief:
        return None
    vol = brief.get("volumes") or {}
    if vol.get("duree_marche_mois"):
        return int(vol["duree_marche_mois"])
    # Parse fallback "24 mois reconductibles"
    duree_str = (brief.get("calendrier") or {}).get("duree_marche") or ""
    m = _re.search(r"(\d+)\s*mois", duree_str.lower())
    if m:
        return int(m.group(1))
    # Tentative depuis durée "1 an ferme reconductible 3 fois pour une période d'un an (4 ans maximum)"
    m = _re.search(r"(\d+)\s*ans?\s+maximum", duree_str.lower())
    if m:
        return int(m.group(1)) * 12
    return None


def _inferer_montant_estime(brief: Optional[dict]) -> Optional[float]:
    """
    Infère un ordre de grandeur du montant total du marché actuel.
    Sources (par ordre de fiabilité) :
      1. brief.montant_marche.valeur_estimee_euros (extrait du RC par le LLM)
      2. moyenne de fourchette_min/max si extraits
      3. None (signale qu'on n'a pas de proxy de taille)
    """
    if not brief:
        return None
    mm = brief.get("montant_marche") or {}
    v = mm.get("valeur_estimee_euros")
    if v and isinstance(v, (int, float)) and v > 0:
        return float(v)
    fmin = mm.get("fourchette_min_euros")
    fmax = mm.get("fourchette_max_euros")
    if (fmin and fmax
            and isinstance(fmin, (int, float)) and isinstance(fmax, (int, float))
            and fmin > 0 and fmax > 0):
        return (float(fmin) + float(fmax)) / 2
    return None


def _inferer_publics_tags(brief: Optional[dict]) -> set:
    """Renvoie un set de tags publics ciblés (pour matching d'intersection).

    Ex: {'allophones', 'QPV', 'demandeurs_emploi_reconversion'} si plusieurs
    publics signalés. Plus tolérant que _inferer_public_cible qui ne garde
    qu'un seul tag canonique.
    """
    if not brief:
        return set()
    tags = set()
    # Tag principal canonique (si déjà inféré)
    p = _inferer_public_cible(brief)
    if p:
        tags.add(p)
    # Tags supplémentaires depuis publics_cibles
    pc = brief.get("publics_cibles") or {}
    raw_tags = pc.get("publics_specifiques_signales") or []
    for t in raw_tags:
        t_norm = (t or "").lower().strip()
        for cle, val in PUBLIC_KEYWORDS.items():
            if cle in t_norm:
                tags.add(val)
                break
        else:
            # Tag brut normalisé (allophones, QPV, etc.)
            if t_norm:
                tags.add(t_norm.replace(" ", "_"))
    # Tags depuis la description aussi
    desc = (pc.get("description") or "").lower()
    for cle, val in PUBLIC_KEYWORDS.items():
        if cle in desc:
            tags.add(val)
    return tags


def _inferer_attend_rse(brief: Optional[dict]) -> bool:
    """True si le marché actif valorise les clauses RSE (sociales ou environnementales).

    Heuristique : présence de critères RSE dans le barème ou de tags QPV/insertion
    dans le public visé.
    """
    if not brief:
        return False
    bn = brief.get("bareme_notation") or {}
    # Sous-critères techniques mentionnant RSE / GES / social
    sous_crits = bn.get("sous_criteres_techniques") or []
    for sc in sous_crits:
        lib = (sc.get("libelle") if isinstance(sc, dict) else str(sc)).lower()
        if any(mc in lib for mc in ("rse", "gaz à effet", "ges", "environnement",
                                      "social", "carbone", "ecologique", "écologique")):
            return True
    # Public QPV / quartiers prioritaires (souvent associé à clause d'insertion)
    pc = brief.get("publics_cibles") or {}
    desc = (pc.get("description") or "").lower()
    tags = " ".join(pc.get("publics_specifiques_signales") or []).lower()
    if any(mc in desc + " " + tags for mc in ("qpv", "quartier prioritaire",
                                                "insertion socio")):
        return True
    return False


def _inferer_forme_prix(brief: Optional[dict]) -> Optional[str]:
    """Renvoie 'forfaitaire', 'unitaire', 'mixte' ou None."""
    if not brief:
        return None
    bn = brief.get("bareme_notation") or {}
    mc = brief.get("montant_marche") or {}
    # Modalité de calcul prix : forfait global vs prix unitaire vs mixte
    src = " ".join([
        (bn.get("modalite_calcul_prix") or ""),
        (mc.get("commentaire") or ""),
    ]).lower()
    if "unitaire" in src and "forfait" in src:
        return "mixte"
    if "unitaire" in src or "bordereau" in src or "bpu" in src or "/beneficiaire" in src or "par bénéficiaire" in src:
        return "unitaire"
    if "forfait" in src:
        return "forfaitaire"
    return None


def _extraire_caracteristiques_marche(profil: dict, brief: Optional[dict],
                                      marche: dict) -> dict:
    """Construit le dict de features du marché actuel à comparer."""
    vol = (brief.get("volumes") if brief else None) or {}
    return {
        "categorie_metier": marche.get("categorie_metier"),
        "prestation_precise": _inferer_prestation_precise(marche, brief),
        "public_cible": _inferer_public_cible(brief),
        "publics_tags": _inferer_publics_tags(brief),  # nouveau : set multi-tags
        "duree_mois": _extraire_duree_mois_brief(brief),
        "dr": deduire_dr(marche),
        "montant_estime_eur": _inferer_montant_estime(brief),
        "nb_beneficiaires": vol.get("nb_beneficiaires_total"),  # nouveau
        "forme_prix_attendue": _inferer_forme_prix(brief),  # nouveau
        "attend_rse": _inferer_attend_rse(brief),  # nouveau
    }


def _normaliser_prix_mensuel(comparable: dict) -> Optional[float]:
    """
    €/mois pour un comparable DECP.
    Source canonique : montant_eur / duree_mois.
    Renvoie None si données insuffisantes.
    """
    montant = comparable.get("montant_eur")
    duree = comparable.get("duree_mois")
    if not montant or not duree or montant <= 0 or duree <= 0:
        return None
    return float(montant) / float(duree)


def _calculer_similarite(features_actuel: dict, comparable: dict) -> float:
    """Score de similarité entre marché actuel et comparable DECP, dans [0, 1].

    Critères pondérés (somme = 1.0) :
    - Catégorie métier (25%)              - exacte
    - Prestation précise (18%)            - exacte
    - Public cible intersection (12%)     - tags multi
    - Proximité durée (10%)               - ratio linéaire
    - Même DR (10%)                       - lieu_execution / region_code
    - Proximité volume bénéficiaires (8%) - ratio nb
    - Région voisine (5%)                 - consolation géo (DR adjacente)
    - Même forme prix (4%)                - unitaire / forfaitaire
    - Alignement RSE (3%)                 - clauses environnementales/sociales
    - Récence (5%)                        - âge linéaire sur 3 ans
    """
    score = 0.0
    ve_comp = comparable.get("volumes_extraits") or {}

    # 25 % — Catégorie métier
    if (features_actuel.get("categorie_metier")
            and features_actuel["categorie_metier"] == comparable.get("categorie_metier")):
        score += POIDS_SIMILARITE["categorie_metier"]

    # 18 % — Prestation précise (uniquement si on l'a des deux côtés ET ≠ "autre")
    prest_actuel = features_actuel.get("prestation_precise")
    prest_comp = ve_comp.get("prestation_precise")
    if (prest_actuel and prest_comp
            and prest_actuel == prest_comp and prest_comp != "autre"):
        score += POIDS_SIMILARITE["prestation_precise"]

    # 12 % — Public cible (intersection de tags, fraction max)
    pub_tags_actuel = features_actuel.get("publics_tags") or set()
    pub_comp_single = ve_comp.get("public_cible")
    pub_comp_tags = set()
    if pub_comp_single:
        pub_comp_tags.add(pub_comp_single)
    # Le comparable peut aussi avoir d'autres tags si on les a extraits ailleurs
    # (pour l'instant on n'a que public_cible canonique côté DECP)
    if pub_tags_actuel and pub_comp_tags:
        inter = pub_tags_actuel & pub_comp_tags
        union = pub_tags_actuel | pub_comp_tags
        if inter and union:
            # Jaccard pondéré, mais maximisé à 1 quand au moins un tag commun
            score_pub = len(inter) / max(len(pub_tags_actuel),
                                          len(pub_comp_tags))
            score += POIDS_SIMILARITE["public_cible"] * score_pub
    elif features_actuel.get("public_cible") and pub_comp_single \
            and features_actuel["public_cible"] == pub_comp_single:
        # Fallback : match exact ancien format (pas de publics_tags)
        score += POIDS_SIMILARITE["public_cible"]

    # 10 % — Proximité durée (linéaire : ratio 1→full, 0.5→zéro)
    duree_actuel = features_actuel.get("duree_mois")
    duree_comp = comparable.get("duree_mois")
    if duree_actuel and duree_comp and duree_actuel > 0 and duree_comp > 0:
        ratio = min(duree_actuel, duree_comp) / max(duree_actuel, duree_comp)
        score_duree = max(0.0, (ratio - 0.5) * 2.0)
        score += POIDS_SIMILARITE["proximite_duree"] * score_duree

    # 10 % — Même DR (lieu_execution / acheteur_region_code)
    dr_actuel = features_actuel.get("dr")
    dr_comp = None
    if dr_actuel:
        if _meme_zone_geo(dr_actuel, comparable.get("lieu_execution")):
            score += POIDS_SIMILARITE["meme_dr"]
            dr_comp = dr_actuel  # match exact, pas besoin de bonus voisin
        else:
            # Fallback : utiliser la fonction deduire_dr sur le comparable pour
            # avoir une DR canonique (utilise acheteur_region_code en priorité)
            dr_comp = deduire_dr(comparable)
            if dr_comp and dr_comp == dr_actuel:
                score += POIDS_SIMILARITE["meme_dr"]

    # 5 % — Région voisine (consolation géo : DR adjacente si pas de match exact)
    if dr_actuel and dr_comp and dr_comp != dr_actuel:
        voisines = DR_VOISINES.get(dr_actuel) or set()
        if dr_comp in voisines:
            score += POIDS_SIMILARITE["region_proche"]

    # 8 % — Proximité volume bénéficiaires (ratio si connus des deux côtés)
    nb_actuel = features_actuel.get("nb_beneficiaires")
    nb_comp = (ve_comp.get("nb_beneficiaires_total")
               or ve_comp.get("nb_beneficiaires"))
    if nb_actuel and nb_comp and nb_actuel > 0 and nb_comp > 0:
        ratio = min(nb_actuel, nb_comp) / max(nb_actuel, nb_comp)
        # Même formule que durée : ratio 1→full, 0.5→zéro
        score_vol = max(0.0, (ratio - 0.5) * 2.0)
        score += POIDS_SIMILARITE["proximite_volume"] * score_vol

    # 4 % — Même forme prix (forfaitaire / unitaire / mixte)
    forme_actuel = features_actuel.get("forme_prix_attendue")
    forme_comp = (comparable.get("forme_prix") or "").lower()
    if forme_actuel and forme_comp:
        if forme_actuel in forme_comp or forme_comp in forme_actuel:
            score += POIDS_SIMILARITE["meme_forme_prix"]

    # 3 % — Alignement RSE (si marché actif valorise RSE et comparable en a aussi)
    if features_actuel.get("attend_rse"):
        cs = (comparable.get("considerations_sociales") or "").lower()
        ce = (comparable.get("considerations_environnementales") or "").lower()
        a_rse = ((cs and cs != "sans objet")
                  or (ce and ce != "sans objet"))
        if a_rse:
            score += POIDS_SIMILARITE["rse_aligne"]

    # 5 % — Récence (linéaire sur 3 ans)
    date_notif = comparable.get("date_notification") or ""
    if date_notif and len(date_notif) >= 4:
        try:
            annee_comp = int(date_notif[:4])
            anciennete = _datetime.now().year - annee_comp
            score_rec = max(0.0, (3 - anciennete) / 3.0)
            score += POIDS_SIMILARITE["recence"] * score_rec
        except ValueError:
            pass

    return score


def _euro_short(montant) -> str:
    """Format compact d'un montant en euros : 250 k€, 1.2 M€, etc."""
    if montant is None or montant == 0:
        return "—"
    if montant >= 1_000_000:
        return f"{montant/1_000_000:.2f} M€"
    if montant >= 1_000:
        return f"{montant/1_000:.0f} k€"
    return f"{montant:.0f} €"


def zone_prix_marche(profil: dict, brief: Optional[dict], marche: dict,
                     marches_notifies: dict,
                     marches_tendia: Optional[list] = None) -> dict:
    """
    Calcule la zone de prix FT empirique pour un marché actuel,
    via KNN pondéré sur les comparables historiques.

    Sources de comparables (par ordre de priorité décroissante) :
        1. `marches_tendia` : notre base interne de marchés vus + attribués
           + briefs LLM enrichis. Haute qualité, peu nombreux. Bonus de
           similarité +25% pour favoriser leur sélection.
        2. `marches_notifies` : DECP brut depuis data.gouv.fr. Beaucoup
           d'entrées mais features pauvres.

    Args:
        profil: dict du profil organisme.
        brief: dict du brief LLM (peut être None).
        marche: dict du marché actuel (depuis marches.json).
        marches_notifies: dict {id: marche_decp} (depuis marches_notifies.json).
        marches_tendia: liste optionnelle de pseudo-marchés Tendia
                        (issue de `marches_attribues.lister_pour_knn()`).
                        Quand fournie et non vide, ces entrées sont mélangées
                        aux comparables DECP avec un bonus de similarité.

    Returns:
        dict structuré :
          - confiance: "haute" / "moyenne" / "faible" / "vide"
          - n_comparables_utilises: int
          - n_comparables_tendia: int (combien viennent de la base interne)
          - similarite_moyenne: float [0-1]
          - estimation: {q1_eur, mediane_eur, q3_eur, duree_mois_utilisee}
          - strategie_recommandee: str (du profil)
          - prix_recommande_eur: float (Q1/médiane/Q3 selon stratégie)
          - top_comparables: [{id, _source, similarite, montant, durée, ...}]
          - features_marche_actuel: dict
          - estimation_rc_brief_eur: float (montant_marche extrait du brief)
          - alertes: list de strings
    """
    # 1. Caractéristiques du marché actuel
    features = _extraire_caracteristiques_marche(profil, brief, marche)

    # 2. Filtrer comparables exploitables
    #    + pré-filtre TAILLE : si on a un montant estimé pour le marché actuel,
    #      on garde uniquement les comparables dans une fenêtre de taille
    #      raisonnable [×1/4, ×4]. Sinon pas de filtre taille (et on signale
    #      l'incertitude plus loin).
    montant_estime = features.get("montant_estime_eur")
    if montant_estime and montant_estime > 0:
        BORNE_MIN = montant_estime / 4.0
        BORNE_MAX = montant_estime * 4.0
    else:
        BORNE_MIN = None
        BORNE_MAX = None

    # PRÉ-FILTRES DE COHÉRENCE D'ÉCHELLE :
    # Sans ces filtres, le KNN remonte des micro-marchés (25-60k €) qui font
    # chuter la médiane et faussent l'estimation des accords-cadres FT.
    #
    # On détecte si le marché actuel est un "gros marché" (accord-cadre FT
    # multi-annuel typique) via plusieurs signaux :
    #   - durée >= 24 mois
    #   - mention "accord-cadre" dans titre/objet/brief
    #   - volume bénéficiaires >= 50
    # Si c'est un gros marché, on applique un seuil de montant minimum aux
    # comparables (80k€) en plus du filtre durée.
    duree_actuelle = features.get("duree_mois") or 0
    nb_benef = features.get("nb_beneficiaires") or 0
    objet_actuel = ((marche.get("titre") or "") + " "
                    + (marche.get("objet") or "")).lower()
    synthese_brief = ""
    if brief:
        synthese_brief = (brief.get("synthese_marche") or "").lower()
    texte_combine = objet_actuel + " " + synthese_brief

    actuel_est_gros_marche = (
        duree_actuelle >= 24
        or nb_benef >= 50
        or "accord-cadre" in texte_combine
        or "accord cadre" in texte_combine
        or "reconductible" in texte_combine
    )

    if actuel_est_gros_marche:
        duree_min_comparable = 12
        montant_min_comparable = 80_000  # exclut les micro-marchés / BC
    else:
        duree_min_comparable = 12  # base : exclure les BC de quelques mois
        montant_min_comparable = 0

    _MARQUEURS_BC = (
        "bon de commande", "bons de commande",
        "commande subsequente", "commande subséquente",
        "marche subsequent", "marché subséquent",
        "marches subsequents", "marchés subséquents",
        "ordre de service",
    )

    comparables_utilisables = []
    nb_filtres_taille = 0
    nb_filtres_duree = 0
    nb_filtres_montant = 0
    nb_filtres_bc = 0
    for id_m, m_decp in marches_notifies.items():
        ve = m_decp.get("volumes_extraits") or {}
        # Skip si filtré métier
        if ve.get("confiance") == "exclu_filtre":
            continue
        # Skip si prix mensuel pas calculable
        if _normaliser_prix_mensuel(m_decp) is None:
            continue
        # Pré-filtre taille (si on a un montant estimé pour le marché actuel)
        if BORNE_MIN is not None:
            montant_c = m_decp.get("montant_eur") or 0
            if montant_c < BORNE_MIN or montant_c > BORNE_MAX:
                nb_filtres_taille += 1
                continue
        # Pré-filtre durée minimale
        duree_c = m_decp.get("duree_mois") or 0
        if duree_c < duree_min_comparable:
            nb_filtres_duree += 1
            continue
        # Pré-filtre montant minimum (pour les gros marchés actuels)
        montant_c = m_decp.get("montant_eur") or 0
        if montant_c < montant_min_comparable:
            nb_filtres_montant += 1
            continue
        # Pré-filtre BC : exclure si l'objet contient un marqueur explicite
        objet_c = (m_decp.get("objet") or "").lower()
        if any(mk in objet_c for mk in _MARQUEURS_BC):
            nb_filtres_bc += 1
            continue
        comparables_utilisables.append((id_m, m_decp))

    # 2bis. Comparables ISSUS DE LA BASE INTERNE TENDIA (haute qualité).
    #       Mêmes pré-filtres que DECP brut, mais on les distingue ensuite
    #       au moment du scoring pour leur appliquer un bonus de similarité.
    comparables_tendia = []
    if marches_tendia:
        for c_apt in marches_tendia:
            # On ne réapplique PAS le filtre métier (les briefs Tendia ont
            # déjà passé un contrôle de qualité au moment de la capture).
            if _normaliser_prix_mensuel(c_apt) is None:
                continue
            if BORNE_MIN is not None:
                montant_c = c_apt.get("montant_eur") or 0
                if montant_c < BORNE_MIN or montant_c > BORNE_MAX:
                    nb_filtres_taille += 1
                    continue
            duree_c = c_apt.get("duree_mois") or 0
            if duree_c < duree_min_comparable:
                nb_filtres_duree += 1
                continue
            montant_c = c_apt.get("montant_eur") or 0
            if montant_c < montant_min_comparable:
                nb_filtres_montant += 1
                continue
            objet_c = (c_apt.get("objet") or "").lower()
            if any(mk in objet_c for mk in _MARQUEURS_BC):
                nb_filtres_bc += 1
                continue
            comparables_tendia.append((c_apt.get("id"), c_apt))

    if not comparables_utilisables and not comparables_tendia:
        return {
            "confiance": "vide",
            "n_comparables_utilises": 0,
            "n_comparables_tendia": 0,
            "raison": "Aucun comparable exploitable (ni base interne Tendia ni DECP brut).",
            "features_marche_actuel": features,
            "top_comparables": [],
            "alertes": [],
        }

    # 3. Score similarité pour chacun.
    #    Les comparables issus de la base interne Tendia reçoivent un BONUS
    #    de +25% sur le score, plafonné à 1.0 — pour favoriser leur sélection
    #    quand la base devient mature, sans les forcer si vraiment hors-sujet.
    BONUS_TENDIA = 0.25
    scores = []
    for id_m, m_decp in comparables_utilisables:
        sim = _calculer_similarite(features, m_decp)
        if sim > 0:
            # Annoter la source pour permettre à l'UI de distinguer
            m_decp_annote = dict(m_decp)
            m_decp_annote.setdefault("_source", "decp")
            scores.append((sim, id_m, m_decp_annote))
    for id_a, c_apt in comparables_tendia:
        sim_base = _calculer_similarite(features, c_apt)
        if sim_base > 0:
            sim_boostee = min(1.0, sim_base * (1.0 + BONUS_TENDIA))
            scores.append((sim_boostee, id_a, c_apt))

    if not scores:
        return {
            "confiance": "vide",
            "n_comparables_utilises": 0,
            "n_comparables_tendia": 0,
            "raison": ("Aucun comparable avec similarité > 0. "
                       "Le marché actuel manque peut-être de features (catégorie, durée, DR)."),
            "features_marche_actuel": features,
            "top_comparables": [],
            "alertes": [],
        }

    # 4. Top-N
    scores.sort(key=lambda x: -x[0])
    top = scores[:TOP_N_COMPARABLES]

    # 5. Distribution €/mois sur top-N
    prix_mensuels = []
    for sim, _, m_decp in top:
        pm = _normaliser_prix_mensuel(m_decp)
        if pm is not None:
            prix_mensuels.append(pm)

    if len(prix_mensuels) < 3:
        return {
            "confiance": "vide",
            "n_comparables_utilises": len(prix_mensuels),
            "raison": "Moins de 3 comparables avec prix exploitable.",
            "features_marche_actuel": features,
            "top_comparables": [],
            "alertes": [],
        }

    prix_mensuels.sort()
    if len(prix_mensuels) >= 4:
        quartiles = statistics.quantiles(prix_mensuels, n=4)
        q1, q3 = quartiles[0], quartiles[2]
    else:
        q1, q3 = prix_mensuels[0], prix_mensuels[-1]
    mediane = statistics.median(prix_mensuels)

    # 6. Reprojection sur durée du marché actuel
    duree_actuel = features.get("duree_mois") or 24  # défaut 24 mois
    estimation = {
        "q1_eur": round(q1 * duree_actuel),
        "mediane_eur": round(mediane * duree_actuel),
        "q3_eur": round(q3 * duree_actuel),
        "duree_mois_utilisee": duree_actuel,
        "duree_inferee_par_defaut": features.get("duree_mois") is None,
    }

    # 7. Confiance globale
    sim_moy = sum(s[0] for s in top) / len(top)
    if sim_moy >= 0.6 and len(prix_mensuels) >= 8:
        confiance = "haute"
    elif sim_moy >= 0.4 and len(prix_mensuels) >= 5:
        confiance = "moyenne"
    else:
        confiance = "faible"

    # Downgrade automatique si on n'a pas pu appliquer le pré-filtre de taille :
    # la fourchette est alors potentiellement faussée par des outliers (ex:
    # accords-cadres nationaux à 10 M€ vs petit marché métropolitain à 200 k€).
    if BORNE_MIN is None and confiance == "haute":
        confiance = "moyenne"
    if BORNE_MIN is None and confiance == "moyenne":
        confiance = "faible"

    # 8. Prix recommandé selon stratégie profil
    strategie = (profil.get("economie") or {}).get("strategie_prix", "median")
    if strategie == "competitif":
        prix_reco = estimation["q1_eur"]
    elif strategie == "haut_de_gamme":
        prix_reco = estimation["q3_eur"]
    else:
        prix_reco = estimation["mediane_eur"]

    # 9. Top comparables pour affichage UI (top 5)
    top_comp_export = []
    for sim, id_m, m_decp in top[:5]:
        ve = m_decp.get("volumes_extraits") or {}
        top_comp_export.append({
            "id": id_m,
            "_source": m_decp.get("_source", "decp"),  # 'tendia' ou 'decp'
            "uid_decp": m_decp.get("uid_decp"),  # pour liens externes data.gouv.fr
            "similarite": round(sim, 2),
            "montant_eur": m_decp.get("montant_eur"),
            "duree_mois": m_decp.get("duree_mois"),
            "categorie_metier": m_decp.get("categorie_metier"),
            "prestation_precise": ve.get("prestation_precise"),
            "public_cible": ve.get("public_cible"),
            "lieu_execution": m_decp.get("lieu_execution"),
            "annee_notification": (m_decp.get("date_notification") or "")[:4],
            "titulaire": m_decp.get("titulaire_nom"),
            "prix_mensuel": round(_normaliser_prix_mensuel(m_decp), 2),
            # Nouveaux champs enrichis (DECP consolidée)
            "titulaire_categorie": m_decp.get("titulaire_categorie"),
            "acheteur_region_nom": m_decp.get("acheteur_region_nom"),
            "acheteur_departement_nom": m_decp.get("acheteur_departement_nom"),
            "offres_recues": m_decp.get("offres_recues"),
            "forme_prix": m_decp.get("forme_prix"),
            "procedure": m_decp.get("procedure"),
            "id_accord_cadre": m_decp.get("id_accord_cadre"),
            "considerations_sociales": m_decp.get("considerations_sociales"),
            "considerations_environnementales": m_decp.get("considerations_environnementales"),
        })

    # 10. Alertes contextuelles
    alertes = []
    montant_rc = None
    if brief:
        mm = brief.get("montant_marche") or {}
        montant_rc = mm.get("valeur_estimee_euros")
    if montant_rc and montant_rc > 0:
        ecart = (montant_rc - estimation["mediane_eur"]) / estimation["mediane_eur"]
        if abs(ecart) > 0.30:
            sens = "supérieure" if ecart > 0 else "inférieure"
            alertes.append(
                f"L'estimation RC ({_euro_short(montant_rc)}) est {sens} "
                f"de {abs(ecart)*100:.0f}% à la médiane des comparables DECP "
                f"({_euro_short(estimation['mediane_eur'])})."
            )
        else:
            alertes.append(
                f"L'estimation RC ({_euro_short(montant_rc)}) est cohérente "
                f"avec la zone DECP."
            )

    if confiance == "faible":
        alertes.append(
            "Confiance faible : peu de comparables DECP très similaires. "
            "Utiliser cette estimation comme orientation, pas comme référence."
        )
    if features.get("duree_mois") is None:
        alertes.append(
            "Durée du marché actuel inconnue (brief manquant ou champ vide). "
            f"Estimation reprojetée sur {duree_actuel} mois par défaut."
        )
    if BORNE_MIN is None:
        alertes.append(
            "Montant estimé du marché inconnu (le RC ne le communique pas). "
            "Le KNN inclut des comparables de toutes tailles, "
            "ce qui élargit fortement la fourchette. À interpréter avec prudence."
        )
    elif nb_filtres_taille > 0:
        alertes.append(
            f"{nb_filtres_taille} comparables écartés par le pré-filtre taille "
            f"(hors fenêtre {_euro_short(BORNE_MIN)}–{_euro_short(BORNE_MAX)})."
        )

    # Compter les comparables Tendia dans le top final (pour l'UI / debug)
    n_tendia_dans_top = sum(
        1 for _, _, m in top
        if (m.get("_source") == "tendia")
    )

    return {
        "confiance": confiance,
        "n_comparables_utilises": len(prix_mensuels),
        "n_comparables_tendia": n_tendia_dans_top,
        "similarite_moyenne": round(sim_moy, 2),
        "estimation": estimation,
        "strategie_recommandee": strategie,
        "prix_recommande_eur": prix_reco,
        "top_comparables": top_comp_export,
        "features_marche_actuel": features,
        "estimation_rc_brief_eur": montant_rc,
        "alertes": alertes,
    }
