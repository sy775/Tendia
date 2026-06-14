"""
preset.py
---------
Module central de Tendia : charge le preset (secteur d'activité) actif et
expose son vocabulaire, ses règles et son schéma au reste du code.

ARCHITECTURE
============

Un "preset" Tendia = un secteur d'activité prêt à l'emploi, livré par Tendia.
Exemples : formation_ft, energie_renouvelable, btp_travaux, conseil_audit,
it_numerique, etc. Chaque preset regroupe tout ce qui est métier-spécifique :

    presets/<code_preset>/_schema.json   ← structure du profil organisme
    presets/<code_preset>/_preset.json   ← vocabulaire LLM, mots-clés veille,
                                            barèmes horaires, règles matching
    presets/_actif.json                  ← pointe vers le preset chargé

L'utilisateur de Tendia choisit un preset à l'inscription (son secteur), puis
renseigne son profil organisme à l'intérieur de ce preset. Il ne crée pas de
nouveau preset : la collection de presets est maintenue par Tendia.

L'idée : aucun code Python (matching.py, llm_extract.py, llm_calibration.py…)
ne mentionne plus directement "Qualiopi", "France Travail", "RGE" ou tout
autre terme métier. Tout passe par ce module.

INTERFACE PUBLIQUE
==================
    charger_actif() -> dict             : charge le preset actif (cache)
    code_actif() -> str                 : code du preset actif
                                          (ex: "formation_ft")
    vocabulaire_llm() -> dict           : termes pour injecter dans les prompts
    prompt_extraction() -> dict         : sections paramétrées du prompt extract
    prompt_calibration() -> dict        : sections paramétrées du prompt calibration
    mots_cles_veille() -> list[str]     : mots-clés d'inclusion BOAMP
    cpv_inclusion() -> list[str]        : CPV cibles pour filtrage veille
    baremes_horaires() -> dict          : barèmes €/h pour bottom-up LLM
    regles_matching() -> list[dict]     : alertes critiques paramétrées
    acheteur_vers_zone(nom) -> str|None : détection zone géo depuis acheteur
    seuils_score() -> dict              : seuils des verdicts matching
    valider_profil(profil) -> list[str] : retourne erreurs de validation
    schema_profil() -> dict             : JSON-Schema du profil pour ce preset
    recharger() -> None                 : invalide le cache (utile en dev)
    info() -> dict                      : résumé du preset actif
    lister_presets_disponibles() -> list: liste des presets installés
    basculer_preset(code) -> None       : change le preset actif

USAGE
=====
    import preset
    voc = preset.vocabulaire_llm()
    prompt = PROMPT_TEMPLATE.format(secteur=voc["secteur_libelle"], ...)
"""

import hashlib
import json
import os
import unicodedata
from pathlib import Path
from typing import Optional

# Racine du projet (le module est à la racine, comme matching.py)
RACINE = Path(__file__).resolve().parent
PRESETS_DIR = RACINE / "presets"
FICHIER_ACTIF = PRESETS_DIR / "_actif.json"

# Cache en mémoire pour éviter les relectures
_CACHE: dict = {}


# ---------------------------------------------------------------------------
# Chargement de bas niveau
# ---------------------------------------------------------------------------

def _lire_json(chemin: Path) -> dict:
    """Lit un fichier JSON et retourne un dict. Lève si fichier absent."""
    if not chemin.exists():
        raise FileNotFoundError(f"Fichier preset manquant : {chemin}")
    with chemin.open("r", encoding="utf-8") as f:
        return json.load(f)


def _lire_actif_descripteur() -> dict:
    """
    Lit presets/_actif.json. Si absent, crée un fichier par défaut pointant
    sur formation_ft.

    Compatibilité ascendante : si le fichier contient encore l'ancien champ
    "domaine" (avant le renommage), on le lit aussi.
    """
    if not FICHIER_ACTIF.exists():
        defaut = {"preset": "formation_ft"}
        FICHIER_ACTIF.parent.mkdir(parents=True, exist_ok=True)
        with FICHIER_ACTIF.open("w", encoding="utf-8") as f:
            json.dump(defaut, f, ensure_ascii=False, indent=2)
        return defaut
    descripteur = _lire_json(FICHIER_ACTIF)
    # Compatibilité : ancien champ "domaine" toléré
    if "preset" not in descripteur and "domaine" in descripteur:
        descripteur["preset"] = descripteur["domaine"]
    return descripteur


# ---------------------------------------------------------------------------
# API publique — chargement
# ---------------------------------------------------------------------------

def charger_actif() -> dict:
    """
    Charge le preset actif (avec cache). Retourne un dict avec les clés :
        code             : str (ex: "formation_ft")
        schema           : dict (JSON-Schema du profil)
        preset           : dict (vocabulaire_llm, veille, calibration_llm…)
        descripteur      : dict (contenu de _actif.json)
    """
    if _CACHE:
        return _CACHE

    descripteur = _lire_actif_descripteur()
    code = descripteur.get("preset", "formation_ft")

    dossier = PRESETS_DIR / code
    if not dossier.is_dir():
        raise FileNotFoundError(
            f"Dossier de preset manquant : {dossier}. "
            f"Vérifiez le champ 'preset' dans presets/_actif.json."
        )

    schema = _lire_json(dossier / "_schema.json")
    # Compatibilité ascendante : tolère un ancien _domaine.json
    fichier_preset = dossier / "_preset.json"
    if not fichier_preset.exists():
        ancien = dossier / "_domaine.json"
        if ancien.exists():
            fichier_preset = ancien
    preset_def = _lire_json(fichier_preset)

    _CACHE.update({
        "code": code,
        "schema": schema,
        "preset": preset_def,
        "descripteur": descripteur,
    })
    return _CACHE


def recharger() -> None:
    """Invalide le cache. À appeler après modification d'un fichier preset."""
    _CACHE.clear()
    _CACHE_UNION.clear()


def code_actif() -> str:
    """Retourne le code du preset actif (ex: 'formation_ft')."""
    return charger_actif()["code"]


def etiquette_courte() -> str:
    """
    Retourne l'étiquette UI courte du preset actif (ex: "France Travail",
    "Énergies renouvelables"). Utilisée comme sous-titre dans le sidebar
    et dans les libellés contextuels (ex: "Marchés <étiquette> similaires").

    Fallback sur le code du preset si l'étiquette n'est pas définie.
    """
    meta = charger_actif()["preset"].get("meta", {})
    return meta.get("etiquette_courte") or charger_actif()["code"]


# ---------------------------------------------------------------------------
# API publique — accès aux blocs métier
# ---------------------------------------------------------------------------

def vocabulaire_llm() -> dict:
    """
    Retourne le bloc 'vocabulaire_llm' du preset actif.

    Clés typiques :
        secteur_libelle              : str (utilisé en début de prompt système)
        type_pieces_dce_typiques     : str
        type_repondant               : str
        unite_principale_facturation : str
        references_attendues         : str
        alertes_typiques             : list[str]
        exemples_synthese            : list[str]
    """
    return charger_actif()["preset"].get("vocabulaire_llm", {})


def prompt_extraction() -> dict:
    """
    Retourne le bloc 'prompt_extraction' du preset actif.

    Clés typiques :
        bloc_schema_specifique       : str (portion JSON injectée dans le schéma)
        regles_specifiques           : str (règles métier additionnelles)
        exemples_elements_a_chiffrer : str (hints pour bareme_notation.prix)
        hints_calcul_montant         : str (hints pour la règle de calcul du montant)

    Si le preset n'a pas de bloc prompt_extraction, retourne un dict vide.
    """
    return charger_actif()["preset"].get("prompt_extraction", {})


def prompt_calibration() -> dict:
    """
    Retourne le bloc 'prompt_calibration' du preset actif (utilisé par
    llm_calibration.py pour adapter le prompt au secteur).

    Clés typiques :
        secteur_libelle_court              : str (ex: "France Travail")
        section_qualification_intervenants : str (paragraphe a. du prompt LLM)
        section_duree_effective            : str (paragraphe b.)
        section_coefficient_complexite     : str (paragraphe c.)
        section_re_pricing                 : str (ÉTAPE 1bis)
        section_top_down                   : str (ÉTAPE 1 top-down)

    Si le preset n'a pas de bloc prompt_calibration, retourne un dict vide.
    """
    return charger_actif()["preset"].get("prompt_calibration", {})


# ---------------------------------------------------------------------------
# Schéma union pour brief LLM mutualisé (Sprint 3)
# ---------------------------------------------------------------------------
#
# Le brief LLM est désormais MUTUALISÉ entre tous les presets installés :
# pour un marché donné, on extrait UN brief contenant TOUS les champs métier
# de TOUS les presets (publics_cibles + volumes formation + caracteristiques
# chantier + volumes_techniques EnR + ...). Le LLM remplit les champs qui
# font sens pour le marché qu'il lit, et laisse les autres à null.
#
# Cache au démarrage : les fonctions _union_*() lisent tous les _preset.json
# une fois, mettent le résultat en mémoire, et le réutilisent ensuite. Pour
# invalider (ex: ajout d'un preset), appeler recharger().

_CACHE_UNION: dict = {}


def _charger_tous_les_presets() -> list:
    """
    Liste tous les presets installés avec les blocs nécessaires aux prompts
    LLM et au routage par classification IA.

    Résultat : liste de dicts {code, meta, prompt_extraction, veille,
    vocabulaire_llm}, triée alphabétiquement par code.
    """
    if "tous" in _CACHE_UNION:
        return _CACHE_UNION["tous"]
    tous = []
    if not PRESETS_DIR.is_dir():
        _CACHE_UNION["tous"] = []
        return []
    for sous in sorted(PRESETS_DIR.iterdir()):
        if not sous.is_dir():
            continue
        fichier = sous / "_preset.json"
        if not fichier.exists():
            fichier = sous / "_domaine.json"  # compat ascendante
        if not fichier.exists():
            continue
        try:
            d = _lire_json(fichier)
            tous.append({
                "code": sous.name,
                "meta": d.get("meta", {}),
                "prompt_extraction": d.get("prompt_extraction", {}),
                "veille": d.get("veille", {}),
                "vocabulaire_llm": d.get("vocabulaire_llm", {}),
            })
        except Exception:
            continue
    _CACHE_UNION["tous"] = tous
    return tous


# ---------------------------------------------------------------------------
# Routage classification IA → presets pertinents (Sprint 2bis)
# ---------------------------------------------------------------------------
#
# Idée : en mode brief mutualisé, on n'envoie au LLM que les blocs sectoriels
# des presets pertinents pour CE marché (déduits de sa classification IA),
# pas l'union complète. Avantages :
#   - résout la collision de clés JSON (ex: `caracteristiques_techniques_
#     chantier` défini à la fois en BTP et énergie_renouvelable)
#   - supprime la pollution lexicale formation pour un brief BTP/IT
#   - prompt 2-3x plus court → focus du LLM sur les bons champs
#
# Fallback : si pas de classification IA disponible, on retombe sur
# l'union complète (comportement legacy).


def presets_pour_domaines(domaines_metier_codes: list) -> list:
    """
    Pour une liste de codes de domaines IA (issus de la taxonomie 56 domaines),
    retourne la liste des codes presets pertinents — triée par ordre de
    pertinence (presets où le domaine est dans `domaines_acceptes` d'abord,
    puis ceux où il est dans `domaines_optionnels`).

    Exemple :
        >>> presets_pour_domaines(["btp_voirie_reseaux"])
        ["btp", "ingenierie"]   # btp en acceptes, ingenierie en optionnels

    Args:
        domaines_metier_codes : liste de strings (codes taxonomie).
                                Vide ou None → []

    Returns:
        list[str] : codes presets, dédupliquée, ordonnée par pertinence.
                    Vide si aucun preset ne matche.
    """
    if not domaines_metier_codes:
        return []
    # Normalisation
    codes_in = [c for c in domaines_metier_codes if isinstance(c, str) and c]
    if not codes_in:
        return []
    presets_acceptes = []  # rang 1
    presets_optionnels = []  # rang 2
    for p in _charger_tous_les_presets():
        veille = p.get("veille", {}) or {}
        da = set(veille.get("domaines_acceptes", []) or [])
        do = set(veille.get("domaines_optionnels", []) or [])
        if any(c in da for c in codes_in):
            presets_acceptes.append(p["code"])
        elif any(c in do for c in codes_in):
            presets_optionnels.append(p["code"])
    # Dédup en conservant l'ordre (acceptes prioritaires)
    vu = set()
    resultat = []
    for c in presets_acceptes + presets_optionnels:
        if c not in vu:
            vu.add(c)
            resultat.append(c)
    return resultat


def _filtrer_presets(codes_presets: Optional[list]) -> list:
    """
    Retourne les dicts presets correspondant aux codes passés.
    Si codes_presets est None/vide, retourne TOUS les presets (fallback union).
    """
    tous = _charger_tous_les_presets()
    if not codes_presets:
        return tous
    set_codes = set(codes_presets)
    # On préserve l'ordre passé en argument (pertinence)
    par_code = {p["code"]: p for p in tous}
    return [par_code[c] for c in codes_presets if c in par_code]


def schema_pour_presets(codes_presets: Optional[list]) -> str:
    """
    Comme schema_union() mais filtré aux presets passés en argument.
    Si codes_presets est None/vide : équivaut à schema_union() (fallback).
    """
    presets = _filtrer_presets(codes_presets)
    blocs = []
    for p in presets:
        bloc = (p.get("prompt_extraction", {})
                 .get("bloc_schema_specifique", "")).strip()
        if not bloc:
            continue
        while bloc.endswith(","):
            bloc = bloc[:-1].rstrip()
        blocs.append(bloc)
    return ",\n".join(blocs)


def regles_specifiques_pour_presets(codes_presets: Optional[list]) -> str:
    """Comme regles_specifiques_union() mais filtré aux presets passés."""
    presets = _filtrer_presets(codes_presets)
    blocs = []
    for p in presets:
        bloc = (p.get("prompt_extraction", {})
                 .get("regles_specifiques", "")).strip()
        if bloc:
            blocs.append(f"**Règles {p['code']}** :\n{bloc}")
    return "\n\n".join(blocs)


def exemples_elements_a_chiffrer_pour_presets(codes_presets: Optional[list]) -> str:
    """Comme exemples_elements_a_chiffrer_union() mais filtré."""
    presets = _filtrer_presets(codes_presets)
    blocs = []
    for p in presets:
        bloc = (p.get("prompt_extraction", {})
                 .get("exemples_elements_a_chiffrer", "")).strip()
        if bloc:
            blocs.append(bloc)
    return ",\n        ".join(blocs)


def hints_calcul_montant_pour_presets(codes_presets: Optional[list]) -> str:
    """Comme hints_calcul_montant_union() mais filtré."""
    presets = _filtrer_presets(codes_presets)
    blocs = []
    for p in presets:
        bloc = (p.get("prompt_extraction", {})
                 .get("hints_calcul_montant", "")).strip()
        if bloc:
            blocs.append(bloc)
    return " ".join(blocs)


def blocs_sectoriels_pour_presets(codes_presets: Optional[list]) -> list:
    """
    Retourne la liste des noms de blocs top-level (clés JSON) déclarés par
    les presets passés en argument.

    Utilisé par le filtre anti-hallucination dans llm_extract : on supprime
    de la sortie LLM tout bloc sectoriel qui n'est pas dans cette liste
    (le LLM peut halluciner des noms de blocs depuis son entraînement).

    Args:
        codes_presets : liste de codes de presets. **None/[] (hors-périmètre) →
                        [] : AUCUN bloc sectoriel autorisé** (le brief ne garde
                        que les champs universels + le bloc neutre). Ne PAS
                        renvoyer l'union complète, sinon les marchés sans preset
                        conserveraient tous les blocs sectoriels (pollution).

    Returns:
        Liste de strings (clés top-level), dédupliquée.
    """
    import re
    if not codes_presets:
        return []
    presets = _filtrer_presets(codes_presets)
    cles = set()
    # Pattern : clé top-level indentée de 2 espaces dans bloc_schema_specifique
    pattern = re.compile(r'^  "([a-z_][a-z_0-9]*)"\s*:\s*[\{\[]', re.MULTILINE)
    for p in presets:
        bss = p.get("prompt_extraction", {}).get("bloc_schema_specifique", "")
        for cle in pattern.findall(bss):
            cles.add(cle)
    return sorted(cles)


def hash_preset(code: str) -> Optional[str]:
    """SHA-256 (16 premiers hex) du fichier `presets/<code>/_preset.json`.
    Sert au versioning des prompts (cf _meta.prompts_versions). None si absent.
    Mis en cache (vidé par `recharger()`)."""
    cache = _CACHE_UNION.setdefault("hashes", {})
    if code in cache:
        return cache[code]
    f = PRESETS_DIR / code / "_preset.json"
    h = None
    if f.is_file():
        h = hashlib.sha256(f.read_bytes()).hexdigest()[:16]
    cache[code] = h
    return h


def hashes_presets_installes() -> dict:
    """{code: 'sha256:<16hex>'} pour tous les presets installés."""
    out = {}
    for sous in sorted(PRESETS_DIR.iterdir()):
        if (sous / "_preset.json").is_file():
            h = hash_preset(sous.name)
            if h:
                out[sous.name] = f"sha256:{h}"
    return out


def prompts_versions_pour_presets(codes_presets: Optional[list]) -> dict:
    """{'<code>/_preset.json': 'sha256:<16hex>'} pour les presets ciblés.
    {} si codes_presets vide (hors-périmètre : aucun preset utilisé)."""
    out = {}
    for c in (codes_presets or []):
        h = hash_preset(c)
        if h:
            out[f"{c}/_preset.json"] = f"sha256:{h}"
    return out


def few_shot_examples_pour_presets(codes_presets: Optional[list]) -> str:
    """
    Concatène les `prompt_extraction.few_shot_examples` des presets ciblés.
    None/[] (hors-périmètre) → "" : pas d'exemple sectoriel injecté.
    """
    if not codes_presets:
        return ""
    presets = _filtrer_presets(codes_presets)
    exs = []
    for p in presets:
        ex = (p.get("prompt_extraction", {}).get("few_shot_examples", "") or "").strip()
        if ex:
            exs.append(ex)
    return "\n\n".join(exs)


def vocabulaire_llm_pour_presets(codes_presets: Optional[list]) -> dict:
    """
    Retourne un vocabulaire LLM agrégé pour les presets passés.

    - 1 seul preset → son vocabulaire_llm direct.
    - Plusieurs presets → vocabulaire neutre multi-secteurs (secteur_libelle
      = "marchés publics français", type_pieces générique, type_repondant
      générique).
    - Aucun (None/vide) → fallback sur vocabulaire_llm() du preset actif.
    """
    if not codes_presets:
        return vocabulaire_llm()
    presets = _filtrer_presets(codes_presets)
    if not presets:
        return vocabulaire_llm()
    if len(presets) == 1:
        return presets[0].get("vocabulaire_llm", {}) or vocabulaire_llm()
    # Multi-presets : on renvoie un vocabulaire neutre pour ne pas biaiser
    # le LLM vers un secteur particulier.
    return {
        "secteur_libelle": "marchés publics français (multi-secteurs)",
        "type_pieces_dce_typiques": (
            "Règlement de Consultation (RC), Cahier des Clauses Techniques "
            "Particulières (CCTP), Cahier des Clauses Administratives "
            "Particulières (CCAP), Bordereau des Prix Unitaires (BPU) ou "
            "Décomposition du Prix Global Forfaitaire (DPGF)"
        ),
        "type_repondant": "candidat à un marché public",
    }


def schema_union() -> str:
    """
    Retourne la portion JSON 'union' à injecter dans le schéma de sortie LLM.
    Concatène les bloc_schema_specifique de tous les presets installés
    pour produire un schéma multi-secteurs.

    Exemple si formation + energie_renouvelable installés :
        "publics_cibles": {...},
        "volumes": {...},
        "modalites": {...},
        "caracteristiques_techniques_chantier": {...},
        "volumes_techniques": {...},
        "modalites_execution_chantier": {...}
    """
    if "schema" in _CACHE_UNION:
        return _CACHE_UNION["schema"]
    blocs = []
    for p in _charger_tous_les_presets():
        bloc = (p.get("prompt_extraction", {})
                 .get("bloc_schema_specifique", "")).strip()
        if not bloc:
            continue
        # Nettoyer un éventuel trailing comma
        while bloc.endswith(","):
            bloc = bloc[:-1].rstrip()
        blocs.append(bloc)
    union = ",\n".join(blocs)
    _CACHE_UNION["schema"] = union
    return union


def regles_specifiques_union() -> str:
    """
    Union des regles_specifiques de tous les presets installés.
    Le LLM reçoit toutes les règles métier connues ; il appliquera celles
    qui font sens pour le marché analysé.
    """
    if "regles" in _CACHE_UNION:
        return _CACHE_UNION["regles"]
    blocs = []
    for p in _charger_tous_les_presets():
        bloc = (p.get("prompt_extraction", {})
                 .get("regles_specifiques", "")).strip()
        if bloc:
            blocs.append(f"**Règles {p['code']}** :\n{bloc}")
    union = "\n\n".join(blocs)
    _CACHE_UNION["regles"] = union
    return union


def exemples_elements_a_chiffrer_union() -> str:
    """
    Union des exemples_elements_a_chiffrer de tous les presets.
    Le LLM voit des exemples couvrant tous les secteurs et reconnaît ceux
    pertinents au marché analysé.
    """
    if "elements" in _CACHE_UNION:
        return _CACHE_UNION["elements"]
    blocs = []
    for p in _charger_tous_les_presets():
        bloc = (p.get("prompt_extraction", {})
                 .get("exemples_elements_a_chiffrer", "")).strip()
        if bloc:
            blocs.append(bloc)
    # On joint avec virgules — c'est un fragment de liste JSON
    union = ",\n        ".join(blocs)
    _CACHE_UNION["elements"] = union
    return union


def hints_calcul_montant_union() -> str:
    """
    Union des hints_calcul_montant de tous les presets.
    Couvre les multiples conventions de prix unitaire (par bénéficiaire,
    par kWc, par m², etc.) pour que le LLM reconnaisse celle qui s'applique.
    """
    if "hints" in _CACHE_UNION:
        return _CACHE_UNION["hints"]
    blocs = []
    for p in _charger_tous_les_presets():
        bloc = (p.get("prompt_extraction", {})
                 .get("hints_calcul_montant", "")).strip()
        if bloc:
            blocs.append(bloc)
    union = " ".join(blocs)
    _CACHE_UNION["hints"] = union
    return union


def mots_cles_veille() -> list:
    """Mots-clés d'inclusion pour le filtrage BOAMP."""
    veille = charger_actif()["preset"].get("veille", {})
    return veille.get("mots_cles_inclusion", [])


def mots_cles_exclusion() -> list:
    """Mots-clés rejetant immédiatement un marché."""
    veille = charger_actif()["preset"].get("veille", {})
    return veille.get("mots_cles_exclusion", [])


def cpv_inclusion() -> list:
    """CPV cibles pour filtrage (peuvent contenir * pour wildcards)."""
    veille = charger_actif()["preset"].get("veille", {})
    return veille.get("cpv_inclusion", [])


def baremes_horaires() -> dict:
    """Barèmes horaires €/h pour la calibration LLM bottom-up."""
    calib = charger_actif()["preset"].get("calibration_llm", {})
    return calib.get("baremes_horaires_eur", {})


def coefficients_complexite() -> dict:
    """Coefficients de complexité (public / chantier / contexte)."""
    calib = charger_actif()["preset"].get("calibration_llm", {})
    # Le nom de la clé varie selon le preset
    for cle in ("coefficients_complexite_public", "coefficients_complexite_chantier", "coefficients_complexite"):
        if cle in calib:
            return calib[cle]
    return {}


def calibration_llm() -> dict:
    """Bloc complet calibration_llm (barèmes + coefficients + marges + unités)."""
    return charger_actif()["preset"].get("calibration_llm", {})


def regles_matching() -> list:
    """Liste des alertes critiques paramétrées pour le preset."""
    m = charger_actif()["preset"].get("matching", {})
    return m.get("alertes_critiques", [])


def seuils_score() -> dict:
    """Seuils des verdicts (très_pertinent / pertinent / a_verifier)."""
    m = charger_actif()["preset"].get("matching", {})
    return m.get("seuils_score", {
        "tres_pertinent": 75,
        "pertinent": 50,
        "a_verifier": 20,
    })


def categories_metier() -> list:
    """Taxonomie de catégorisation des marchés pour ce preset."""
    tax = charger_actif()["preset"].get("taxonomie", {})
    return tax.get("categories_metier", [])


def schema_profil() -> dict:
    """JSON-Schema du profil organisme pour ce preset."""
    return charger_actif()["schema"]


# ---------------------------------------------------------------------------
# Détection géographique (remplace ACHETEUR_VERS_DR de matching.py)
# ---------------------------------------------------------------------------

def _normaliser(texte: str) -> str:
    if not texte:
        return ""
    nfkd = unicodedata.normalize("NFKD", texte.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def acheteur_vers_zone(acheteur_nom: str) -> Optional[str]:
    """
    Détecte le code de zone géographique d'un acheteur à partir de son nom,
    selon les règles du preset actif.

    Remplace la constante ACHETEUR_VERS_DR de matching.py (qui était figée FT).
    """
    if not acheteur_nom:
        return None

    m = charger_actif()["preset"].get("matching", {})
    bloc = m.get("acheteur_vers_zone", {})
    norm = _normaliser(acheteur_nom)

    for regle in bloc.get("regles", []):
        indice = regle.get("indice", "")
        if indice and indice in norm:
            return regle.get("code")

    fallback = bloc.get("fallback_acheteur_central", {})
    for indice in fallback.get("indices", []):
        if indice in norm:
            return fallback.get("code")

    return None


# ---------------------------------------------------------------------------
# Validation de profil contre le schéma
# ---------------------------------------------------------------------------

def valider_profil(profil: dict) -> list:
    """
    Valide un profil contre le JSON-Schema du preset actif.
    Retourne une liste d'erreurs (vide si OK).

    Utilise jsonschema si disponible, sinon validation minimale custom.
    """
    erreurs = []
    schema = schema_profil()

    try:
        import jsonschema  # type: ignore
        validator = jsonschema.Draft7Validator(schema)
        for err in validator.iter_errors(profil):
            chemin = "/".join(str(p) for p in err.absolute_path) or "<root>"
            erreurs.append(f"{chemin} : {err.message}")
    except ImportError:
        # Validation minimale si jsonschema absent
        required = schema.get("required", [])
        for champ in required:
            if champ not in profil:
                erreurs.append(f"Champ obligatoire manquant : {champ}")
        identite = profil.get("identite") or {}
        sub_req = (schema.get("properties", {}).get("identite", {}).get("required", []))
        for champ in sub_req:
            if not identite.get(champ):
                erreurs.append(f"identite.{champ} : manquant ou vide")

    return erreurs


# ---------------------------------------------------------------------------
# Diagnostic / introspection
# ---------------------------------------------------------------------------

def info() -> dict:
    """
    Retourne un résumé du preset actif (utile pour debug et UI).
    """
    d = charger_actif()
    meta = d["preset"].get("meta", {})
    return {
        "code": d["code"],
        "nom": meta.get("nom", d["code"]),
        "version": meta.get("version"),
        "qualite": meta.get("qualite", "?"),
        "nb_mots_cles_inclusion": len(mots_cles_veille()),
        "nb_cpv": len(cpv_inclusion()),
        "nb_alertes_critiques": len(regles_matching()),
        "nb_categories": len(categories_metier()),
    }


def lister_presets_disponibles() -> list:
    """Liste les codes de presets installés dans presets/."""
    if not PRESETS_DIR.is_dir():
        return []
    presets = []
    for sous in PRESETS_DIR.iterdir():
        if not sous.is_dir():
            continue
        # Tolère le nom _preset.json (nouveau) ou _domaine.json (ancien)
        fichier_def = sous / "_preset.json"
        if not fichier_def.exists():
            fichier_def = sous / "_domaine.json"
        if not fichier_def.exists():
            continue
        try:
            d = _lire_json(fichier_def)
            meta = d.get("meta", {})
            presets.append({
                "code": sous.name,
                "nom": meta.get("nom", sous.name),
                "qualite": meta.get("qualite", "?"),
            })
        except Exception:
            presets.append({"code": sous.name, "nom": sous.name, "qualite": "erreur"})
    return presets


def basculer_preset(code: str) -> None:
    """
    Change le preset actif (modifie presets/_actif.json) et invalide le cache.
    Utilisé par l'UI quand l'utilisateur change de preset.
    """
    dossier = PRESETS_DIR / code
    fichier_def = dossier / "_preset.json"
    if not fichier_def.exists():
        # Tolère l'ancien nom le temps de la migration
        fichier_def = dossier / "_domaine.json"
    if not fichier_def.exists():
        raise ValueError(f"Preset inconnu : {code}")
    descripteur = _lire_actif_descripteur()
    descripteur["preset"] = code
    # On ne garde plus l'ancien champ "domaine" pour éviter l'ambiguïté
    descripteur.pop("domaine", None)
    with FICHIER_ACTIF.open("w", encoding="utf-8") as f:
        json.dump(descripteur, f, ensure_ascii=False, indent=2)
    recharger()


if __name__ == "__main__":
    # Petit test en CLI : python preset.py
    print("=== Presets disponibles ===")
    for d in lister_presets_disponibles():
        print(f"  - {d['code']:<30} {d['nom']}  [{d['qualite']}]")
    print()
    print("=== Preset actif ===")
    for cle, val in info().items():
        print(f"  {cle:<25} {val}")
    print()
    print("=== Aperçu vocabulaire LLM ===")
    voc = vocabulaire_llm()
    for cle in ("secteur_libelle", "type_repondant", "unite_principale_facturation"):
        print(f"  {cle:<32} {voc.get(cle)}")
    print()
    print(f"=== Mots-clés veille (extrait, total={len(mots_cles_veille())}) ===")
    print("  " + ", ".join(mots_cles_veille()[:10]))
