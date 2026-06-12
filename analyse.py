"""
analyse.py
----------
Moteur d'analyse multi-preset des marchés ingérés (Sprint 3).

OBJECTIF
========
Pour chaque marché de la base SQLite, déterminer s'il est pertinent pour
au moins un preset installé. Le matching est DÉTERMINISTE (mots-clés + CPV
+ exclusion), donc gratuit. Il ne déclenche aucun appel LLM.

L'extraction LLM (étape 5b) sera déclenchée séparément sur les marchés
identifiés comme pertinents par au moins un preset.

PIPELINE
========
    marches ingérés
        ↓
    matcher_preset_marche()         ← cette étape (déterministe, gratuit)
        ↓
    scores_matching (cache SQLite)
        ↓
    marches pertinents (au moins un preset matche)
        ↓
    [étape 5b] téléchargement DCE + llm_extract  → briefs_extraits

LOGIQUE DE MATCHING PRESET-MARCHE
==================================
Un marché matche un preset si :
  - au moins un mot-clé de inclusion apparaît dans titre+objet (word boundary)
    OU le cpv_principal commence par un pattern listé dans cpv_inclusion
  - ET aucun mot-clé d'exclusion n'apparaît dans titre+objet

Le résultat est BINAIRE (matche ou pas), mais on conserve le détail
(mots-clés trouvés, CPV matché, etc.) pour audit et debug.

INTERFACE PUBLIQUE
==================
    matcher_preset_marche(preset_def, marche) -> dict
        Évalue un marché contre un preset chargé.

    analyser_marche(marche, presets_charges=None) -> dict
        Pour un marché, retourne le matching contre tous les presets.

    analyser_tous_les_marches(verbose=True, force=False) -> dict
        Pour tous les marchés en base, calcule et stocke les matchings.

    marches_pertinents_pour_preset(preset_code, verdict_min='matche') -> list
        Liste des marchés pertinents pour un preset donné (depuis le cache).

    statistiques() -> dict
        Vue agrégée : pour chaque preset, combien de marchés matchent.
"""

import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import preset
import stockage


COLLECTION_SCORES = "scores_matching"


# ---------------------------------------------------------------------------
# Normalisation textuelle (sans accents, lowercase)
# ---------------------------------------------------------------------------

def _normaliser(texte: str) -> str:
    if not texte:
        return ""
    nfkd = unicodedata.normalize("NFKD", texte.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _mot_cle_present(mot_cle: str, texte_norm: str) -> bool:
    """
    Word boundary matching. Évite les faux positifs comme "rge" dans
    "auberge". Repris de matching.py pour cohérence.
    """
    if not mot_cle or not texte_norm:
        return False
    mot_norm = _normaliser(mot_cle).strip()
    if not mot_norm:
        return False
    try:
        pattern = r"\b" + re.escape(mot_norm) + r"\b"
        return bool(re.search(pattern, texte_norm))
    except re.error:
        return mot_norm in texte_norm


def _cpv_matche_pattern(cpv: str, patterns: list) -> Optional[str]:
    """
    Vérifie si un cpv (str "80530000") matche au moins un pattern.
    Patterns supportés : "80*", "8053*", "80530000".
    Retourne le pattern qui a matché, ou None.
    """
    if not cpv:
        return None
    for pat in patterns:
        if not pat:
            continue
        if pat.endswith("*"):
            prefix = pat.rstrip("*")
            if cpv.startswith(prefix):
                return pat
        else:
            if cpv == pat:
                return pat
    return None


# ---------------------------------------------------------------------------
# Matching preset × marché
# ---------------------------------------------------------------------------

def matcher_preset_marche(preset_def: dict, marche: dict) -> dict:
    """
    Évalue si un marché matche un preset, en utilisant les règles de veille
    du preset (mots-clés inclusion, exclusion, CPV).

    Args:
        preset_def: dict chargé depuis _preset.json (bloc complet).
        marche: dict du marché normalisé.

    Returns:
        dict avec :
            matche                  : bool (pertinent pour ce preset ?)
            mots_cles_matches       : list[str] des mots-clés inclus trouvés
            cpv_pattern_matche      : str | None (pattern CPV qui a matché)
            exclu_par_mot_negatif   : str | None (mot-clé d'exclusion trouvé)
            score_brut              : int (nombre d'indices positifs)
            raison                  : str (verdict humain)
    """
    veille = preset_def.get("veille") or {}
    mots_inclus = veille.get("mots_cles_inclusion") or []
    mots_exclus = veille.get("mots_cles_exclusion") or []
    cpv_patterns = veille.get("cpv_inclusion") or []

    titre = marche.get("titre", "") or ""
    objet = marche.get("objet", "") or ""
    cpv = marche.get("cpv_principal", "") or ""
    texte_norm = _normaliser(titre + " " + objet)

    # Exclusion : un seul mot exclus suffit à disqualifier
    mot_excluant = None
    for mc in mots_exclus:
        if _mot_cle_present(mc, texte_norm):
            mot_excluant = mc
            break

    # Inclusion : mots-clés
    mots_trouves = [mc for mc in mots_inclus if _mot_cle_present(mc, texte_norm)]

    # Inclusion : CPV
    cpv_match = _cpv_matche_pattern(cpv, cpv_patterns)

    # Matching final
    a_indice_positif = bool(mots_trouves) or bool(cpv_match)
    matche = a_indice_positif and not mot_excluant

    if mot_excluant:
        raison = f"Exclu par le mot-clé négatif : {mot_excluant!r}"
    elif not a_indice_positif:
        raison = "Aucun mot-clé d'inclusion ni CPV ne matche"
    else:
        indices = []
        if cpv_match:
            indices.append(f"CPV {cpv} matche {cpv_match}")
        if mots_trouves:
            indices.append(f"{len(mots_trouves)} mot(s)-clé : {', '.join(mots_trouves[:3])}"
                            + ("…" if len(mots_trouves) > 3 else ""))
        raison = " + ".join(indices)

    return {
        "matche": matche,
        "mots_cles_matches": mots_trouves,
        "cpv_pattern_matche": cpv_match,
        "exclu_par_mot_negatif": mot_excluant,
        "score_brut": len(mots_trouves) + (1 if cpv_match else 0),
        "raison": raison,
    }


# ---------------------------------------------------------------------------
# Nouveau matching basé sur la classification IA (Sprint 2)
# ---------------------------------------------------------------------------

COLLECTION_CLASSIFICATIONS_IA = "classifications_ia"
COLLECTION_BRIEFS_EXTRAITS = "briefs_extraits"


def _domaine_principal(classification: dict) -> Optional[str]:
    """
    Extrait le code du domaine principal d'une classification.
    Retourne None si pas de domaines_metier valide.
    """
    if not classification:
        return None
    doms = classification.get("domaines_metier") or []
    if not isinstance(doms, list) or not doms:
        return None
    valides = [d for d in doms if isinstance(d, dict) and d.get("code")]
    if not valides:
        return None
    # Principal = poids max (ou 1er si pas de poids)
    principal = max(valides, key=lambda d: d.get("poids") or 1.0)
    return principal.get("code")


def _classification_pour_marche(marche_id: str,
                                  classifs_ia: dict,
                                  briefs: dict) -> tuple:
    """
    Retourne (classification_dict, source) en privilégiant le brief COMPLET
    (DCE lu, plus précis) sur la classification IA (métadonnées).

    Returns:
        (dict, "brief_complet"|"classification_ia"|None)
        ou (None, None) si rien trouvé.
    """
    # Brief COMPLET en priorité
    brief = briefs.get(marche_id)
    if brief:
        doms = brief.get("domaines_metier")
        if doms:
            return brief, "brief_complet"
    # Classification IA en fallback
    classif = classifs_ia.get(marche_id)
    if classif:
        doms = classif.get("domaines_metier")
        if doms:
            return classif, "classification_ia"
    return None, None


def matcher_preset_marche_par_ia(preset_def: dict,
                                   marche_id: str,
                                   classifs_ia: dict,
                                   briefs: dict) -> dict:
    """
    Évalue si un marché matche un preset selon la CLASSIFICATION IA
    (Sprint 2 — nouvelle architecture).

    Un marché matche un preset si son domaine principal classifié appartient
    aux `domaines_acceptes` du preset. S'il est dans `domaines_optionnels`,
    le matche est marqué comme "optionnel" (à afficher en "à vérifier").

    Args:
        preset_def: dict du preset (bloc complet)
        marche_id: ID du marché à évaluer
        classifs_ia: dict {id: classification} chargé depuis classifications_ia
        briefs: dict {id: brief} chargé depuis briefs_extraits

    Returns:
        dict avec :
            matche                  : bool (True si dans acceptes OU optionnels)
            niveau                  : 'principal' | 'optionnel' | 'hors' | 'non_classifie'
            domaine_classifie       : str | None (code du domaine principal)
            source_classification   : 'brief_complet' | 'classification_ia' | None
            raison                  : str (verdict humain)
    """
    veille = preset_def.get("veille") or {}
    acceptes = set(veille.get("domaines_acceptes") or [])
    optionnels = set(veille.get("domaines_optionnels") or [])

    classif, source = _classification_pour_marche(marche_id, classifs_ia, briefs)
    if not classif:
        return {
            "matche": False,
            "niveau": "non_classifie",
            "domaine_classifie": None,
            "source_classification": None,
            "raison": "Marché non encore classifié (lancer tendia_classification.py)",
        }

    code = _domaine_principal(classif)
    if not code:
        return {
            "matche": False,
            "niveau": "non_classifie",
            "domaine_classifie": None,
            "source_classification": source,
            "raison": "Classification présente mais sans domaine valide",
        }

    if code in acceptes:
        niveau = "principal"
        matche = True
        raison = f"Domaine '{code}' ∈ domaines_acceptes du preset"
    elif code in optionnels:
        niveau = "optionnel"
        matche = True
        raison = f"Domaine '{code}' ∈ domaines_optionnels (à vérifier)"
    else:
        niveau = "hors"
        matche = False
        raison = f"Domaine '{code}' hors du périmètre du preset"

    return {
        "matche": matche,
        "niveau": niveau,
        "domaine_classifie": code,
        "source_classification": source,
        "raison": raison,
    }


def est_pertinent_strict(preset_def: dict,
                          marche_id: str,
                          marche: dict,
                          classifs_ia: Optional[dict] = None,
                          briefs: Optional[dict] = None,
                          fallback_keyword: bool = True) -> dict:
    """
    Mode strict : pertinence basée sur la classification IA.

    Si pas de classification IA disponible :
    - Si fallback_keyword=True → revient au matching keyword (backward compat)
    - Sinon → pas pertinent

    Args:
        preset_def: bloc du preset
        marche_id: ID du marché
        marche: dict du marché (pour fallback keyword)
        classifs_ia: dict classifications (chargé une fois en amont)
        briefs: dict briefs COMPLET (chargé une fois en amont)
        fallback_keyword: fallback vers matching keyword si pas de classification

    Returns:
        dict identique à matcher_preset_marche_par_ia + champ 'mode' :
            'classification_ia' si pertinence décidée par LLM
            'keyword_fallback' si décidée par keyword (pas de classification dispo)
    """
    if classifs_ia is None:
        classifs_ia = stockage.charger(COLLECTION_CLASSIFICATIONS_IA) or {}
    if briefs is None:
        briefs = stockage.charger(COLLECTION_BRIEFS_EXTRAITS) or {}

    r_ia = matcher_preset_marche_par_ia(preset_def, marche_id, classifs_ia, briefs)

    if r_ia["niveau"] != "non_classifie":
        r_ia["mode"] = "classification_ia"
        return r_ia

    # Pas de classification → fallback éventuel
    if fallback_keyword:
        r_kw = matcher_preset_marche(preset_def, marche)
        return {
            "matche": r_kw["matche"],
            "niveau": "principal" if r_kw["matche"] else "hors",
            "domaine_classifie": None,
            "source_classification": None,
            "mode": "keyword_fallback",
            "raison": f"Fallback keyword : {r_kw['raison']}",
        }

    r_ia["mode"] = "classification_ia"
    return r_ia


# ---------------------------------------------------------------------------
# Analyse d'un marché contre tous les presets installés
# ---------------------------------------------------------------------------

def _charger_tous_les_presets() -> dict:
    """
    Charge tous les presets installés depuis le disque.
    Retourne {code: preset_def}.
    """
    racine = Path(__file__).resolve().parent / "presets"
    if not racine.is_dir():
        return {}
    import json
    presets = {}
    for sous in sorted(racine.iterdir()):
        if not sous.is_dir():
            continue
        fichier = sous / "_preset.json"
        if not fichier.exists():
            fichier = sous / "_domaine.json"
        if not fichier.exists():
            continue
        try:
            with fichier.open(encoding="utf-8") as f:
                presets[sous.name] = json.load(f)
        except Exception:
            continue
    return presets


def analyser_marche(marche: dict, presets_charges: Optional[dict] = None) -> dict:
    """
    Pour un marché, retourne le matching contre tous les presets installés.

    Returns:
        dict {
            marche_id: str,
            presets_qui_matchent: list[str],
            details_par_preset: { preset_code: matcher_result },
            au_moins_un_match: bool,
        }
    """
    if presets_charges is None:
        presets_charges = _charger_tous_les_presets()

    details = {}
    qui_matchent = []
    for code, p_def in presets_charges.items():
        r = matcher_preset_marche(p_def, marche)
        details[code] = r
        if r["matche"]:
            qui_matchent.append(code)

    return {
        "marche_id": marche.get("id"),
        "presets_qui_matchent": qui_matchent,
        "details_par_preset": details,
        "au_moins_un_match": bool(qui_matchent),
    }


# ---------------------------------------------------------------------------
# Analyse en lot + persistance des scores
# ---------------------------------------------------------------------------

def _maintenant_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def analyser_tous_les_marches(verbose: bool = True,
                                force: bool = False) -> dict:
    """
    Pour chaque marché en base, calcule le matching contre chaque preset
    et stocke le résultat dans la collection 'scores_matching'.

    Args:
        force: si True, recalcule même pour les marchés déjà analysés.
        verbose: affichage console.

    Returns:
        dict avec stats : { total_marches, analyses_nouvelles, deja_en_cache,
                             pertinents_global, pertinents_par_preset }
    """
    marches = stockage.charger("marches")
    presets_charges = _charger_tous_les_presets()
    scores_existants = stockage.charger(COLLECTION_SCORES)

    if verbose:
        print()
        print("=" * 78)
        print("  TENDIA — Analyse multi-preset (Sprint 3 étape 5a)")
        print("=" * 78)
        print(f"  Marchés en base       : {len(marches)}")
        print(f"  Presets installés     : {list(presets_charges.keys())}")
        print(f"  Scores déjà en cache  : {len(scores_existants)}")
        if force:
            print(f"  Mode force            : recalcul de tout")
        print()

    stats = {
        "total_marches": len(marches),
        "analyses_nouvelles": 0,
        "deja_en_cache": 0,
        "pertinents_global": 0,
        "pertinents_par_preset": {code: 0 for code in presets_charges},
    }

    maintenant = _maintenant_iso()
    nouveaux_scores = dict(scores_existants)  # on patch

    # Charge classifications IA + briefs UNE fois pour ce run
    classifs_ia = stockage.charger(COLLECTION_CLASSIFICATIONS_IA) or {}
    briefs = stockage.charger(COLLECTION_BRIEFS_EXTRAITS) or {}

    for mid, marche in marches.items():
        # Clé de cache : pour cette étape, 1 score par marche + version preset
        # On stocke un score par couple (marché × preset)
        for preset_code, p_def in presets_charges.items():
            cle_cache = f"{mid}__{preset_code}"
            if cle_cache in nouveaux_scores and not force:
                stats["deja_en_cache"] += 1
                # Compteur cumulé : on lit le cache pour les stats
                if nouveaux_scores[cle_cache].get("matche"):
                    stats["pertinents_par_preset"][preset_code] += 1
                continue
            # Matching keyword (toujours calculé pour traçabilité)
            r_kw = matcher_preset_marche(p_def, marche)
            # Matching IA (Sprint 2 — autorité si dispo)
            r_ia = matcher_preset_marche_par_ia(p_def, mid, classifs_ia, briefs)

            # Décision finale : IA prime si elle a une opinion ; sinon keyword
            if r_ia["niveau"] != "non_classifie":
                matche_final = r_ia["matche"]
                mode_decision = "classification_ia"
                raison_finale = r_ia["raison"]
            else:
                matche_final = r_kw["matche"]
                mode_decision = "keyword_fallback"
                raison_finale = r_kw["raison"]

            entree = {
                "marche_id": mid,
                "preset_code": preset_code,
                "matche": matche_final,
                "mode_decision": mode_decision,
                "score_brut": r_kw["score_brut"],
                # Détails keyword (toujours présents)
                "mots_cles_matches": r_kw["mots_cles_matches"],
                "cpv_pattern_matche": r_kw["cpv_pattern_matche"],
                "exclu_par_mot_negatif": r_kw["exclu_par_mot_negatif"],
                "matche_keyword": r_kw["matche"],
                # Détails IA (peut être null si pas classifié)
                "matche_ia": r_ia["matche"] if r_ia["niveau"] != "non_classifie" else None,
                "niveau_ia": r_ia["niveau"],
                "domaine_classifie": r_ia["domaine_classifie"],
                "source_classification": r_ia["source_classification"],
                "raison": raison_finale,
                "evalue_le": maintenant,
            }
            nouveaux_scores[cle_cache] = entree
            stats["analyses_nouvelles"] += 1
            if matche_final:
                stats["pertinents_par_preset"][preset_code] += 1

    # Persiste tous les scores en une transaction
    stockage.sauver(COLLECTION_SCORES, nouveaux_scores)

    # Compteur global (au moins un preset matche)
    marches_pertinents = set()
    for cle, entree in nouveaux_scores.items():
        if entree.get("matche"):
            marches_pertinents.add(entree["marche_id"])
    stats["pertinents_global"] = len(marches_pertinents)

    if verbose:
        print()
        print("-" * 78)
        print("  Résultats")
        print("-" * 78)
        print(f"  Nouvelles analyses       : {stats['analyses_nouvelles']}")
        print(f"  Lues depuis le cache     : {stats['deja_en_cache']}")
        print(f"  Marchés pertinents       : {stats['pertinents_global']} "
              f"sur {stats['total_marches']} "
              f"({100*stats['pertinents_global']/max(1,stats['total_marches']):.1f}%)")
        print()
        print(f"  Par preset :")
        for code, n in stats["pertinents_par_preset"].items():
            print(f"    {code:30} : {n} marchés pertinents")

    return stats


# ---------------------------------------------------------------------------
# Requêtes pratiques sur les scores
# ---------------------------------------------------------------------------

def marches_pertinents_pour_preset(preset_code: str) -> list:
    """
    Retourne la liste des marchés pertinents pour un preset donné,
    enrichis des informations de matching.

    Returns:
        list[dict] : pour chaque marché pertinent :
            { marche_id, titre, acheteur, score_brut, mots_cles_matches,
              cpv_pattern_matche, raison }
    """
    scores = stockage.charger(COLLECTION_SCORES)
    marches = stockage.charger("marches")

    resultats = []
    for cle, entree in scores.items():
        if entree.get("preset_code") != preset_code:
            continue
        if not entree.get("matche"):
            continue
        mid = entree.get("marche_id")
        marche = marches.get(mid, {})
        resultats.append({
            "marche_id": mid,
            "titre": marche.get("titre", "")[:120],
            "acheteur_nom": marche.get("acheteur_nom", ""),
            "cpv_principal": marche.get("cpv_principal"),
            "type_marche": marche.get("type_marche"),
            "score_brut": entree.get("score_brut"),
            "mots_cles_matches": entree.get("mots_cles_matches", []),
            "cpv_pattern_matche": entree.get("cpv_pattern_matche"),
            "raison": entree.get("raison"),
            "date_publication": marche.get("date_publication"),
        })

    # Tri par score décroissant puis par date
    resultats.sort(key=lambda x: (-x["score_brut"], x["date_publication"] or ""),
                    reverse=False)
    return resultats


def statistiques() -> dict:
    """Vue agrégée des scores : par preset, par type_marche, par CPV."""
    scores = stockage.charger(COLLECTION_SCORES)
    marches = stockage.charger("marches")

    stats = {
        "scores_total": len(scores),
        "marches_total": len(marches),
        "par_preset": {},
        "marches_pertinents_au_moins_un_preset": 0,
    }

    pertinents_globaux = set()
    par_preset = {}
    for cle, entree in scores.items():
        p = entree.get("preset_code")
        if p not in par_preset:
            par_preset[p] = {"total": 0, "pertinents": 0}
        par_preset[p]["total"] += 1
        if entree.get("matche"):
            par_preset[p]["pertinents"] += 1
            pertinents_globaux.add(entree["marche_id"])

    stats["par_preset"] = par_preset
    stats["marches_pertinents_au_moins_un_preset"] = len(pertinents_globaux)
    return stats


# ---------------------------------------------------------------------------
# Orchestrateur d'enrichissement LLM (Sprint 3 étape 5b)
# ---------------------------------------------------------------------------

COLLECTION_BRIEFS = "briefs_extraits"


def _ids_marches_pertinents() -> set:
    """Retourne l'ensemble des marche_id pertinents pour au moins un preset."""
    scores = stockage.charger(COLLECTION_SCORES)
    pertinents = set()
    for entree in scores.values():
        if entree.get("matche"):
            pertinents.add(entree.get("marche_id"))
    return pertinents


def enrichir_marches_pertinents(limite: Optional[int] = None,
                                  dry_run: bool = False,
                                  forcer: bool = False,
                                  verbose: bool = True) -> dict:
    """
    Pour chaque marché pertinent (matche au moins un preset), génère un
    brief LIGHT via auto_brief si pas déjà en cache. Stocke dans
    briefs_extraits (mutualisé entre presets).

    Args:
        limite: nombre max de marchés à enrichir dans cette passe (None = tous).
        dry_run: si True, simule sans appel LLM (estimation de coût).
        forcer: si True, regénère même si un brief LIGHT existe déjà.
        verbose: affichage console.

    Returns:
        dict stats : { traites, enrichis_nouveaux, deja_en_cache, echecs,
                        bloques_budget, cout_total_eur, dry_run }
    """
    import budget as _budget  # import tardif pour éviter cycle au load

    marches = stockage.charger("marches")
    briefs_existants = stockage.charger(COLLECTION_BRIEFS)
    pertinents_ids = sorted(_ids_marches_pertinents())

    if verbose:
        print()
        print("=" * 78)
        print("  TENDIA — Enrichissement LLM des marchés pertinents (étape 5b)")
        print("=" * 78)
        print(f"  Marchés pertinents en base   : {len(pertinents_ids)}")
        print(f"  Briefs déjà en cache         : {len(briefs_existants)}")
        if dry_run:
            print(f"  Mode dry-run : AUCUN appel LLM, juste estimation de coût.")
        if limite:
            print(f"  Limite par passe             : {limite}")
        if forcer:
            print(f"  Mode force                   : regénère même si en cache")
        print()

    stats = {
        "traites": 0,
        "enrichis_nouveaux": 0,
        "deja_en_cache": 0,
        "echecs": 0,
        "bloques_budget": 0,
        "skip_objet_trop_court": 0,
        "cout_total_eur": 0.0,
        "dry_run": dry_run,
    }

    # Import tardif pour éviter cycle imports
    if not dry_run:
        import auto_brief

    for i, mid in enumerate(pertinents_ids, 1):
        if limite and stats["enrichis_nouveaux"] + stats["echecs"] >= limite:
            if verbose:
                print(f"  → Limite de {limite} atteinte, arrêt.")
            break

        marche = marches.get(mid)
        if not marche:
            continue

        stats["traites"] += 1

        # Skip si brief déjà en cache (sauf forcer)
        if not forcer and mid in briefs_existants:
            stats["deja_en_cache"] += 1
            continue

        # Garde-fou objet trop court (auto_brief le fait aussi, mais on évite
        # de logger un appel inutile)
        objet = (marche.get("objet") or "").strip()
        if len(objet) < 30:
            stats["skip_objet_trop_court"] += 1
            if verbose:
                print(f"  [{i}/{len(pertinents_ids)}] {mid} : objet trop court ({len(objet)} chars), skip")
            continue

        if verbose:
            titre_court = (marche.get("titre") or "")[:60]
            print(f"  [{i}/{len(pertinents_ids)}] {mid} : {titre_court}")

        # Dry-run : on simule juste le coût estimé
        if dry_run:
            # Estimation : input ≈ 2k tokens, output ≈ 1k tokens (Sonnet 4)
            cout_estime = _budget.estimer_cout_eur(
                tokens_input=2000, tokens_output=1000)
            stats["cout_total_eur"] += cout_estime
            if verbose:
                print(f"      coût estimé : ~{cout_estime:.3f} €")
            stats["enrichis_nouveaux"] += 1
            continue

        # Mode réel : appel à auto_brief (qui passe par budget)
        try:
            brief = auto_brief.generer_brief_light(marche, verbose=False)
        except _budget.BudgetDepasseError as e:
            if verbose:
                print(f"      ⛔ Budget : {str(e)[:100]}")
                print(f"      → Arrêt de l'enrichissement.")
            stats["bloques_budget"] += 1
            break
        except Exception as e:
            if verbose:
                print(f"      ❌ Erreur : {type(e).__name__}: {str(e)[:100]}")
            stats["echecs"] += 1
            continue

        if brief is None:
            stats["echecs"] += 1
            if verbose:
                print(f"      ❌ Brief non généré (voir logs auto_brief)")
            continue

        # Stocke le brief
        stockage.ecrire(COLLECTION_BRIEFS, mid, brief)
        stats["enrichis_nouveaux"] += 1
        cout = (brief.get("_meta") or {}).get("cout_eur") or 0
        stats["cout_total_eur"] += cout
        if verbose:
            print(f"      ✅ Brief généré ({cout:.3f} €)")

    if verbose:
        print()
        print("-" * 78)
        print("  Bilan enrichissement")
        print("-" * 78)
        print(f"  Marchés traités          : {stats['traites']}")
        print(f"  Briefs déjà en cache     : {stats['deja_en_cache']}")
        print(f"  Briefs nouveaux          : {stats['enrichis_nouveaux']}")
        print(f"  Échecs                   : {stats['echecs']}")
        print(f"  Bloqués budget           : {stats['bloques_budget']}")
        print(f"  Skip objet trop court    : {stats['skip_objet_trop_court']}")
        cle_cout = "Coût estimé" if dry_run else "Coût total réel"
        print(f"  {cle_cout:24} : {stats['cout_total_eur']:.3f} €")

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Analyse multi-preset des marchés Tendia."
    )
    parser.add_argument("--force", action="store_true",
                        help="Recalcule tous les scores (ignore le cache).")
    parser.add_argument("--montrer", default=None, metavar="PRESET",
                        help="Affiche les top 10 marchés pertinents pour ce preset.")
    parser.add_argument("--stats", action="store_true",
                        help="Affiche uniquement les stats agrégées, sans analyse.")
    parser.add_argument("--enrichir", action="store_true",
                        help="Mode étape 5b : pour chaque marché pertinent, "
                             "génère un brief LIGHT via LLM (auto_brief.py). "
                             "Respecte le budget (kill-switch budget.json).")
    parser.add_argument("--limite", type=int, default=None,
                        help="Limite le nombre de marchés à enrichir par passe.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Mode --enrichir uniquement : simule sans appel LLM, "
                             "affiche juste l'estimation de coût.")
    parser.add_argument("--forcer-brief", action="store_true",
                        help="Mode --enrichir uniquement : regénère même si "
                             "un brief LIGHT existe déjà en cache.")
    args = parser.parse_args()

    # === Mode enrichir (étape 5b) ===
    if args.enrichir:
        enrichir_marches_pertinents(
            limite=args.limite,
            dry_run=args.dry_run,
            forcer=args.forcer_brief,
            verbose=True,
        )
        return

    if args.stats:
        st = statistiques()
        print()
        print("=== Stats analyse multi-preset ===")
        print(f"  Total marchés en base                : {st['marches_total']}")
        print(f"  Total scores en cache                : {st['scores_total']}")
        print(f"  Marchés pertinents (au moins 1 preset) : "
              f"{st['marches_pertinents_au_moins_un_preset']}")
        print()
        for p, n in st["par_preset"].items():
            taux = 100 * n["pertinents"] / max(1, n["total"])
            print(f"  Preset {p:30} : "
                  f"{n['pertinents']}/{n['total']} pertinents ({taux:.1f}%)")
        return

    if args.montrer:
        liste = marches_pertinents_pour_preset(args.montrer)
        print()
        print(f"=== {len(liste)} marchés pertinents pour preset '{args.montrer}' ===")
        for i, r in enumerate(liste[:10], 1):
            print()
            print(f"{i:2}. [{r['marche_id']}] (score {r['score_brut']})")
            print(f"    {r['titre']}")
            print(f"    Acheteur : {r['acheteur_nom']}")
            print(f"    CPV {r['cpv_principal']} | {r['type_marche']} | "
                  f"publié {r['date_publication']}")
            print(f"    → {r['raison']}")
        if len(liste) > 10:
            print(f"\n  ... et {len(liste) - 10} autres marchés.")
        return

    # Mode par défaut : lance l'analyse
    analyser_tous_les_marches(verbose=True, force=args.force)


if __name__ == "__main__":
    main()
