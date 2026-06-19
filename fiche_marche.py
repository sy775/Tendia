"""
fiche_marche.py
---------------
Helpers de rendu preset-aware de la fiche marché (Sprint UI fiche marché).

Toute la logique métier de la fiche vit ici (pas dans Jinja) : résolution des
presets du marché, KPI cards, verdict 90 secondes, verrous go/no-go, blocs
sectoriels, richesse du brief, détail lots/tranches. Les templates ne font que
rendre les structures retournées.

Codé DÉFENSIVEMENT contre la structure réelle des briefs (Phase 3a/3b), qui
diffère parfois des noms supposés : ex `caracteristiques_techniques_chantier`
= {description, typologie_ouvrage, surface_volume} ; `calendrier.duree_marche`
est une string ; les volumes sont au niveau lot. Tout accès manquant retombe
proprement sur "—" plutôt que de planter.

Tous les helpers sont purs (zéro effet de bord) et idempotents.
"""

import re

import preset as _preset


# Libellés UX (exception assumée au "pas de hardcoding" : pure présentation).
_PRESET_LABEL = {
    "btp": "BTP", "ingenierie": "Ingénierie", "formation": "Formation",
    "conseil": "Conseil", "it": "IT", "energie_renouvelable": "Énergie",
}
_PRESETS_IMPLEMENTES = {"btp", "ingenierie", "formation", "energie_renouvelable"}
_PRESETS_STUB = {"conseil", "it"}

# Mots-clés d'alertes critiques (verdict 90s / vigilance).
_ALERTES_CRITIQUES = ["visite obligatoire", "attestation", "ss4", "ss3",
                      "dpgf verrouill", "delai court", "delai serre",
                      "reference obligatoire", "experience exigee", "irrecevab"]


# ===========================================================================
# Résolution des presets du marché
# ===========================================================================

def resolve_preset_codes(brief):
    """
    Retourne [(code_preset, pourcentage)] trié par poids décroissant.

    Source : brief.domaines_metier = [{code, poids, lots_concernes}]. Chaque
    code domaine est mappé INDIVIDUELLEMENT vers son preset (mapper la liste
    entière élargit à tort), et les poids sont agrégés par preset puis
    normalisés en %. Au moins un preset si des domaines existent.
    """
    dm = (brief or {}).get("domaines_metier") or []
    poids = {}
    for d in dm:
        if isinstance(d, dict):
            code, p = d.get("code"), d.get("poids")
        else:
            code, p = d, None
        if not code:
            continue
        presets = _preset.presets_pour_domaines([code]) or []
        if not presets:
            continue
        ps = presets[0]
        poids[ps] = poids.get(ps, 0.0) + (p or 0.0)

    if not poids:
        return []
    total = sum(poids.values())
    items = sorted(poids.items(), key=lambda kv: -kv[1])
    if total <= 0:  # poids absents : répartition égale
        n = len(items)
        return [(c, round(100 / n)) for c, _ in items]
    return [(c, round(100 * w / total)) for c, w in items]


def _codes(presets):
    """Liste des codes depuis une liste [(code, pct)] ou [code]."""
    out = []
    for p in presets or []:
        out.append(p[0] if isinstance(p, (list, tuple)) else p)
    return out


# ===========================================================================
# Helpers d'accès brief (défensifs)
# ===========================================================================

def _get(d, *chemin):
    cur = d
    for k in chemin:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _non_vide(v):
    return v is not None and not (isinstance(v, (list, dict, str)) and len(v) == 0)


def _jours_restants(date_limite):
    from datetime import date
    if not date_limite or len(str(date_limite)) < 10:
        return None
    try:
        d = date.fromisoformat(str(date_limite)[:10])
        return (d - date.today()).days
    except ValueError:
        return None


def _duree_compacte(brief):
    # Priorité au nombre de mois propre (volumes.duree_marche_mois) — le champ
    # calendrier.duree_marche est souvent une phrase longue (« ~3,5 mois + 3
    # reconductions de 12 mois ») incohérente en KPI.
    vol = _get(brief, "volumes") or {}
    dmm = vol.get("duree_marche_mois")
    if isinstance(dmm, (int, float)) and dmm > 0:
        return f"{int(dmm)} mois"
    cal = _get(brief, "calendrier") or {}
    dm = cal.get("duree_mois")
    if dm:
        return f"{dm} mois"
    dm = cal.get("duree_marche")
    if dm:
        m = re.search(r"(\d+)\s*mois", str(dm))
        return f"{m.group(1)} mois" if m else str(dm)[:18]
    return None


def montant_estime(brief):
    """Valeur estimée € (valeur directe ou milieu de fourchette), sinon None."""
    mm = _get(brief, "montant_marche") or {}
    v = mm.get("valeur_estimee_euros")
    if isinstance(v, (int, float)) and v > 0:
        return float(v)
    fmin, fmax = mm.get("fourchette_min_euros"), mm.get("fourchette_max_euros")
    if all(isinstance(x, (int, float)) and x > 0 for x in (fmin, fmax)):
        return (float(fmin) + float(fmax)) / 2
    return None


def calibration_marche(id_marche):
    """Charge la calibration bottom-up disque si elle existe, sinon None."""
    try:
        import llm_calibration
        return llm_calibration.charger_si_existe(id_marche)
    except Exception:
        return None


def _fmt_eur(v):
    try:
        return f"{int(round(v)):,}".replace(",", " ") + " €"
    except (TypeError, ValueError):
        return "—"


def _fourchette_calibration(calib):
    """Extrait une fourchette lisible d'une calibration, ou None."""
    if not calib:
        return None
    for cle in ("fourchette", "estimation", "bottom_up", "resultat"):
        bloc = calib.get(cle) if isinstance(calib, dict) else None
        if isinstance(bloc, dict):
            lo = bloc.get("min_euros") or bloc.get("min") or bloc.get("bas")
            hi = bloc.get("max_euros") or bloc.get("max") or bloc.get("haut")
            if lo and hi:
                return f"{_fmt_eur(lo)} – {_fmt_eur(hi)} HT"
    lo = calib.get("montant_min_euros") if isinstance(calib, dict) else None
    hi = calib.get("montant_max_euros") if isinstance(calib, dict) else None
    if lo and hi:
        return f"{_fmt_eur(lo)} – {_fmt_eur(hi)} HT"
    return None


# ===========================================================================
# KPI cards (toujours 4, preset-aware)
# ===========================================================================

def kpi_cards_pour_marche(brief, marche, presets, calib=None):
    """Retourne 4 cards {icone, label, valeur, hint, classe}."""
    codes = _codes(presets)
    cards = []

    # 1) Valeur — affiche la FOURCHETTE quand c'est une estimation LLM (Voie 2 :
    # type 'calcule_volumes' avec min/max), sinon la valeur publiée unique.
    mm = _get(brief, "montant_marche") or {}
    fmin, fmax = mm.get("fourchette_min_euros"), mm.get("fourchette_max_euros")
    a_fourchette = (all(isinstance(x, (int, float)) and x > 0 for x in (fmin, fmax))
                    and float(fmax) > float(fmin))
    est_estimation = mm.get("type") == "calcule_volumes"
    m = montant_estime(brief)
    if a_fourchette and est_estimation:
        cards.append({"icone": "€", "label": "Valeur estimée",
                      "valeur": f"{_fmt_eur(fmin)} – {_fmt_eur(fmax)}",
                      "hint": "estimation Tendia", "classe": "val"})
    elif m:
        cards.append({"icone": "€", "label": "Valeur estimée", "valeur": _fmt_eur(m),
                      "hint": "estimation Tendia" if est_estimation else "", "classe": "val"})
    else:
        cards.append({"icone": "€", "label": "Valeur estimée", "valeur": "—",
                      "hint": "non communiqué dans le DCE", "classe": "val muet"})

    # 2) Card sectorielle
    if "formation" in codes:
        nb = (_get(brief, "caracteristiques_formation", "nb_beneficiaires_estime")
              or _get(brief, "volumes", "nb_beneficiaires"))
        cards.append({"icone": "◍", "label": "Bénéficiaires",
                      "valeur": str(nb) if _non_vide(nb) else "—", "hint": "", "classe": ""})
    elif "btp" in codes:
        n = len(_get(brief, "lots") or [])
        cards.append({"icone": "▥", "label": "Lots",
                      "valeur": (f"{n} lots" if n != 1 else "1 lot") if n else "—",
                      "hint": "", "classe": ""})
    elif "ingenierie" in codes:
        phases = _get(brief, "caracteristiques_mission_moe", "phases_couvertes") or []
        if phases:
            val = f"{phases[0]}→{phases[-1]}" if len(phases) > 1 else phases[0]
            cards.append({"icone": "◇", "label": "Phases MOE", "valeur": val,
                          "hint": f"{len(phases)} phases", "classe": ""})
        else:
            cards.append({"icone": "◇", "label": "Phases MOE", "valeur": "—", "hint": "", "classe": ""})
    else:
        cards.append({"icone": "○", "label": "Périmètre", "valeur": "—",
                      "hint": "enrichissement à venir", "classe": "muet"})

    # 3) Durée
    duree = _duree_compacte(brief)
    cards.append({"icone": "⏱", "label": "Durée", "valeur": duree or "—", "hint": "", "classe": ""})

    # 4) Date limite (J-X)
    dl = (marche or {}).get("date_limite_depot") or _get(brief, "calendrier", "date_limite_offres")
    j = _jours_restants(dl)
    if j is not None:
        val = f"J-{j}" if j >= 0 else "clôturé"
        classe = "urgent" if 0 <= j < 20 else ""
        cards.append({"icone": "⚑", "label": "Date limite", "valeur": val,
                      "hint": str(dl)[:10] if dl else "", "classe": classe})
    else:
        cards.append({"icone": "⚑", "label": "Date limite", "valeur": "—", "hint": "", "classe": ""})

    return cards


# ===========================================================================
# Verrous go/no-go
# ===========================================================================

def _codes_4ch(v):
    """Liste de codes à 4 chiffres depuis une valeur brief (liste ou None)."""
    if not isinstance(v, list):
        return []
    return [str(x).strip() for x in v
            if isinstance(x, str) and str(x).strip().isdigit() and len(str(x).strip()) == 4]


def _profil_sectoriel(profil, code):
    return _get(profil, "profils_sectoriels", code) or {}


def detecter_verrous(brief, profil):
    """
    Retourne [{type, severite, libelle, satisfait, motif}] : verrous go/no-go
    croisés avec le profil actif. severite ∈ {bloquant, vigilance}.
    """
    verrous = []
    qr = _get(brief, "qualifications_requises") or {}
    qm = _get(brief, "qualifications_moe") or {}

    # Qualibat (BTP)
    qualibat_exig = _codes_4ch(qr.get("qualibat"))
    if qualibat_exig:
        detenus = _profil_sectoriel(profil, "btp").get("qualifications", {}).get("qualibat") or []
        manquants = [c for c in qualibat_exig if c not in detenus]
        verrous.append({
            "type": "Qualibat", "severite": "bloquant",
            "libelle": f"Codes exigés : {', '.join(qualibat_exig)}",
            "satisfait": not manquants,
            "motif": "" if not manquants else f"manquant(s) : {', '.join(manquants)}"})

    # OPQIBI (ingénierie)
    opqibi_exig = _codes_4ch(qm.get("opqibi"))
    if opqibi_exig:
        detenus = _profil_sectoriel(profil, "ingenierie").get("qualifications", {}).get("opqibi") or []
        manquants = [c for c in opqibi_exig if c not in detenus]
        verrous.append({
            "type": "OPQIBI", "severite": "bloquant",
            "libelle": f"Codes exigés : {', '.join(opqibi_exig)}",
            "satisfait": not manquants,
            "motif": "" if not manquants else f"manquant(s) : {', '.join(manquants)}"})

    # Références exigées
    refs = _get(brief, "references_exigees") or {}
    vol_min = refs.get("volume_min_references_similaires")
    blob_alertes = " ".join(s for s in (_get(brief, "alertes_candidat") or []) if isinstance(s, str)).lower()
    ref_exigee = bool(vol_min) or any(k in blob_alertes for k in
                                      ("reference obligatoire", "référence obligatoire", "experience exigee", "expérience exigée"))
    if ref_exigee:
        secteur = (refs.get("secteur_experience") or "").lower()
        # match token sur les références du profil (chantiers + études)
        toks_exig = _tokens(secteur)
        couvert = False
        for code in ("btp", "ingenierie"):
            for cle in ("references_chantiers", "references_etudes"):
                for r in (_profil_sectoriel(profil, code).get(cle) or []):
                    blob = _tokens(" ".join(str(r.get(c, "")) for c in
                                            ("type_ouvrage", "ouvrage", "projet")))
                    if toks_exig & blob:
                        couvert = True
        verrous.append({
            "type": "Références", "severite": "vigilance",
            "libelle": refs.get("secteur_experience") or f"≥ {vol_min} référence(s) similaire(s)",
            "satisfait": couvert,
            "motif": "" if couvert else "aucune référence transposable dans le profil"})

    return verrous


# ===========================================================================
# Verdict 90 secondes
# ===========================================================================

def _tokens(s):
    if not s:
        return set()
    import unicodedata
    norm = unicodedata.normalize("NFKD", str(s).lower())
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    norm = re.sub(r"[^a-z0-9]+", " ", norm)
    stop = {"des", "les", "une", "pour", "dans", "avec", "marche", "type", "sur"}
    return {t for t in norm.split() if len(t) >= 4 and t not in stop}


def verdict_90_secondes(brief, eval_result, profil, verrous=None):
    """
    Retourne [{icone, texte, source}] : 3-5 lignes synthétiques, priorité
    ✗ (bloquant) > ⚠ (vigilance) > ✓ (positif). Max 5 lignes.
    """
    motifs = (eval_result or {}).get("motifs") or []
    lignes_x, lignes_warn, lignes_ok = [], [], []

    # ✗ : verrou non satisfait (forcé) puis motif bloquant
    for v in (verrous or []):
        if v.get("severite") == "bloquant" and v.get("satisfait") is False:
            lignes_x.append({"icone": "✗", "texte": f"Verrou {v['type']} : {v['motif'] or 'non couvert'} — irrecevabilité probable",
                             "source": "verrou"})
            break
    if not lignes_x:
        bloquants = [m for m in motifs if m.get("satisfait") is False and m.get("points", 0) <= -20]
        if bloquants:
            m = min(bloquants, key=lambda x: x["points"])
            lignes_x.append({"icone": "✗", "texte": _texte_motif(m), "source": "matching"})

    # ⚠ : alertes critiques + délai serré
    for s in (_get(brief, "alertes_candidat") or []):
        if isinstance(s, str) and any(k in s.lower() for k in _ALERTES_CRITIQUES):
            lignes_warn.append({"icone": "⚠", "texte": s.split(":")[0].strip()[:90] if ":" in s else s[:90],
                                "source": "alerte"})
            if len(lignes_warn) >= 2:
                break
    j = _jours_restants((_get(brief, "calendrier", "date_limite_offres")))
    if j is not None and 0 <= j < 20 and len(lignes_warn) < 2:
        lignes_warn.append({"icone": "⚠", "texte": f"Délai serré : {j} jours pour répondre", "source": "calendrier"})

    # ✓ : top motifs positifs
    positifs = sorted([m for m in motifs if m.get("points", 0) > 0],
                      key=lambda x: -x["points"])[:2]
    for m in positifs:
        lignes_ok.append({"icone": "✓", "texte": _texte_motif(m), "source": "matching"})

    return (lignes_x[:1] + lignes_warn[:2] + lignes_ok[:2])[:5]


def _texte_motif(m):
    """Transforme un motif de matching en phrase courte."""
    c = m.get("critere", "")
    p = m.get("points", 0)
    libelles = {
        "preset_compatibilite": "Secteur compatible avec le profil",
        "thematique": "Thématique alignée au catalogue",
        "geographie": "Zone géographique couverte",
        "ing_typologies": "Typologie de mission au cœur du positionnement",
        "ing_competences": "Disciplines exigées couvertes",
        "ing_types_ouvrages": "Type d'ouvrage maîtrisé",
        "ing_opqibi": "Qualifications OPQIBI exigées non détenues",
        "ing_capacite_etudes": "Montant travaux dans la capacité",
        "btp_qualibat": "Qualifications Qualibat",
        "btp_corps_metier": "Corps d'état couverts",
        "btp_types_ouvrages": "Type d'ouvrage maîtrisé",
    }
    base = libelles.get(c, (m.get("commentaire") or c)[:60])
    signe = f"+{p}" if p > 0 else str(p)
    return f"{base} (score {signe})"


# ===========================================================================
# Blocs sectoriels preset-aware
# ===========================================================================

def _libelle_domaine_court(code):
    """Libellé lisible d'un code domaine via la taxonomie, sinon prettify."""
    try:
        import llm_extract
        taxo = (llm_extract._charger_taxonomie() or {}).get("domaines", {})
        d = taxo.get(code)
        if isinstance(d, dict) and d.get("libelle"):
            return d["libelle"]
    except Exception:
        pass
    return str(code or "").replace("_", " ").strip().capitalize()


def _fallback_sectoriel(brief, preset_code):
    """Repli quand un preset est détecté mais sans données sectorielles extraites
    (brief établi sur le preset dominant). On affiche l'info qu'on a vraiment :
    sous-domaine(s) concerné(s) + lots, depuis `domaines_metier`."""
    dm = (brief or {}).get("domaines_metier") or []
    labels, lots_all = [], []
    for d in dm:
        code = d.get("code") if isinstance(d, dict) else d
        if not code:
            continue
        ps = (_preset.presets_pour_domaines([code]) or [None])[0]
        if ps != preset_code:
            continue
        labels.append(_libelle_domaine_court(code))
        for lot in (d.get("lots_concernes") or []) if isinstance(d, dict) else []:
            m = re.search(r"(\d+)", str(lot))
            lots_all.append(str(int(m.group(1))) if m else str(lot))
    if not labels:
        return []
    sections = [{"label": "Composante", "valeur": " · ".join(labels), "type": "text"}]
    if lots_all:
        sections.append({"label": "Lots concernés",
                         "valeur": "Lot " + ", ".join(dict.fromkeys(lots_all)),
                         "type": "text"})
    sections.append({"label": "", "type": "text", "valeur":
                     "Détail sectoriel non extrait (brief établi sur le préset dominant). "
                     "Les exigences communes figurent ci-dessus et dans « Vérifiez votre éligibilité »."})
    return sections


def bloc_sectoriel_pour_marche(brief, presets, profil):
    """
    Retourne [{preset_code, label, pct, implemente, sections}] dans l'ordre de
    poids décroissant. sections = [{label, valeur, type}] (type ∈ text/list/
    table/badge/verrou).
    """
    blocs = []
    for item in (presets or []):
        code, pct = (item if isinstance(item, (list, tuple)) else (item, None))
        if code == "btp":
            blocs.append(_bloc_btp(brief, profil, pct))
        elif code == "ingenierie":
            blocs.append(_bloc_ingenierie(brief, profil, pct))
        elif code == "formation":
            blocs.append(_bloc_formation(brief, pct))
        elif code == "energie_renouvelable":
            blocs.append(_bloc_energie_renouvelable(brief, profil, pct))
        elif code in _PRESETS_STUB:
            blocs.append({"preset_code": code, "label": _PRESET_LABEL.get(code, code),
                          "pct": pct, "implemente": False,
                          "sections": [{"label": "", "valeur":
                                        f"Preset {code} détecté — sections sectorielles à venir (Sprint D).",
                                        "type": "stub"}]})
        # Repli : preset implémenté mais sans données → afficher l'info disponible
        # (sous-domaine + lots) plutôt qu'une section vide.
        if blocs and blocs[-1].get("implemente") and not blocs[-1].get("sections"):
            blocs[-1]["sections"] = _fallback_sectoriel(brief, blocs[-1]["preset_code"])
    return blocs


def _bloc_btp(brief, profil, pct):
    ctc = _get(brief, "caracteristiques_techniques_chantier") or {}
    qr = _get(brief, "qualifications_requises") or {}
    sections = []
    if _non_vide(ctc.get("description")):
        sections.append({"label": "Travaux", "valeur": ctc["description"], "type": "text"})
    if _non_vide(ctc.get("typologie_ouvrage")):
        sections.append({"label": "Typologie d'ouvrage", "valeur": ctc["typologie_ouvrage"], "type": "text"})
    if _non_vide(ctc.get("surface_volume")):
        sections.append({"label": "Surface / volume", "valeur": ctc["surface_volume"], "type": "text"})
    if _non_vide(qr.get("description")):
        sections.append({"label": "Qualifications requises", "valeur": qr["description"], "type": "text"})
    autres = qr.get("autres_certifications") or []
    libelles = [a.get("libelle") if isinstance(a, dict) else a for a in autres if a]
    if libelles:
        sections.append({"label": "Certifications", "valeur": libelles, "type": "list"})
    # Verrou
    for v in detecter_verrous(brief, profil):
        if v["type"] == "Qualibat" and not v["satisfait"]:
            sections.append({"label": "Verrou Qualibat", "valeur": v["motif"], "type": "verrou"})
    return {"preset_code": "btp", "label": "BTP", "pct": pct, "implemente": True, "sections": sections}


def _bloc_ingenierie(brief, profil, pct):
    moe = _get(brief, "caracteristiques_mission_moe") or {}
    qm = _get(brief, "qualifications_moe") or {}
    sections = []
    if _non_vide(moe.get("typologie")):
        sections.append({"label": "Mission MOE", "valeur": moe["typologie"], "type": "text"})
    phases = moe.get("phases_couvertes") or []
    if phases:
        sections.append({"label": "Phases", "valeur": "→".join(phases), "type": "text"})
    if _non_vide(moe.get("complexite_technique")):
        sections.append({"label": "Complexité", "valeur": moe["complexite_technique"], "type": "text"})
    if _non_vide(moe.get("taux_remuneration_moe_pct")):
        sections.append({"label": "Taux MOE", "valeur": moe["taux_remuneration_moe_pct"], "type": "text"})
    if _non_vide(moe.get("bim_niveau")):
        sections.append({"label": "BIM", "valeur": moe["bim_niveau"], "type": "text"})
    if _non_vide(moe.get("montant_travaux_estime")):
        sections.append({"label": "Coût travaux estimé", "valeur": _fmt_eur(moe["montant_travaux_estime"]), "type": "text"})
    # Livrables par phase (souvent l'info la plus actionnable pour chiffrer la mission)
    livrables = moe.get("livrables_par_phase") or []
    items_liv = []
    for lp in livrables:
        if isinstance(lp, dict):
            ph = lp.get("phase") or "?"
            livs = lp.get("livrables") or []
            if livs:
                items_liv.append(f"{ph} : {', '.join(str(x) for x in livs)}")
    if items_liv:
        sections.append({"label": "Livrables par phase", "valeur": items_liv, "type": "list"})
    # Coordinations associées (OPC / SPS / SSI inclus ou exclus) — enjeu de périmètre
    coords = moe.get("coordinations_associees") or []
    if coords:
        sections.append({"label": "Coordinations (OPC/SPS/SSI)", "valeur": coords, "type": "list"})
    indices = moe.get("indices_revision") or []
    if indices:
        sections.append({"label": "Indices de révision", "valeur": indices, "type": "list"})
    # Organigramme attendu + couverture profil
    org = moe.get("organigramme_attendu") or []
    if org:
        comp = set()
        for c in (_profil_sectoriel(profil, "ingenierie").get("competences_specialisees") or []):
            comp |= _tokens(c)
        lignes = []
        for o in org:
            prof = o.get("profil") if isinstance(o, dict) else str(o)
            couvert = bool(_tokens(prof) & comp)
            lignes.append({"profil": prof, "couvert": couvert,
                           "nombre": (o.get("nombre") if isinstance(o, dict) else None)})
        sections.append({"label": "Organigramme attendu", "valeur": lignes, "type": "organigramme"})
    # Qualifications
    if _non_vide(qm.get("opqibi")):
        sections.append({"label": "OPQIBI exigés", "valeur": qm["opqibi"], "type": "list"})
    for v in detecter_verrous(brief, profil):
        if v["type"] in ("OPQIBI",) and not v["satisfait"]:
            sections.append({"label": f"Verrou {v['type']}", "valeur": v["motif"], "type": "verrou"})
    return {"preset_code": "ingenierie", "label": "Ingénierie", "pct": pct, "implemente": True, "sections": sections}


def _bloc_formation(brief, pct):
    sections = []
    pc = _get(brief, "publics_cibles")
    if _non_vide(pc):
        if isinstance(pc, dict):
            # publics_cibles est un objet {description, criteres_eligibilite,
            # publics_specifiques_signales} → on l'aplatit (sinon le template affiche
            # le dict brut). Le détail complet est déjà rendu plus bas dans la fiche.
            desc = pc.get("description")
            if desc:
                sections.append({"label": "Publics cibles", "valeur": desc, "type": "text"})
            specs = pc.get("publics_specifiques_signales") or []
            if specs:
                sections.append({"label": "Publics spécifiques", "valeur": specs, "type": "list"})
        elif isinstance(pc, list):
            sections.append({"label": "Publics cibles", "valeur": pc, "type": "list"})
        else:
            sections.append({"label": "Publics cibles", "valeur": str(pc), "type": "text"})
    return {"preset_code": "formation", "label": "Formation", "pct": pct, "implemente": True, "sections": sections}


def _bloc_energie_renouvelable(brief, profil, pct):
    enr = _get(brief, "caracteristiques_techniques_enr") or {}
    vol = _get(brief, "volumes_techniques") or {}
    qenr = _get(brief, "qualifications_enr") or {}
    mod = _get(brief, "modalites_execution_chantier") or {}
    sections = []
    if _non_vide(enr.get("description")):
        sections.append({"label": "Projet EnR", "valeur": enr["description"], "type": "text"})
    techs = enr.get("technologies_concernees") or []
    if techs:
        sections.append({"label": "Technologies", "valeur": techs, "type": "list"})
    if _non_vide(enr.get("type_de_sites")):
        sections.append({"label": "Type de sites", "valeur": enr["type_de_sites"], "type": "text"})
    # Volumes chiffrés (les plus actionnables pour dimensionner / chiffrer la mission)
    vlignes = []
    if _non_vide(vol.get("puissance_totale_kwc")):
        vlignes.append(f"Puissance totale : {vol['puissance_totale_kwc']} kWc")
    if _non_vide(vol.get("nb_sites")):
        vlignes.append(f"Nombre de sites : {vol['nb_sites']}")
    if _non_vide(vol.get("surface_panneaux_m2")):
        vlignes.append(f"Surface panneaux : {vol['surface_panneaux_m2']} m²")
    if _non_vide(vol.get("productible_annuel_estime_mwh")):
        vlignes.append(f"Productible estimé : {vol['productible_annuel_estime_mwh']} MWh/an")
    if _non_vide(vol.get("duree_marche_mois")):
        vlignes.append(f"Durée marché : {vol['duree_marche_mois']} mois")
    if _non_vide(vol.get("duree_maintenance_om_annees")):
        vlignes.append(f"Maintenance O&M : {vol['duree_maintenance_om_annees']} ans")
    if vlignes:
        sections.append({"label": "Volumes techniques", "valeur": vlignes, "type": "list"})
    if _non_vide(vol.get("commentaire_volumes")):
        sections.append({"label": "Détail dimensionnement", "valeur": vol["commentaire_volumes"], "type": "text"})
    # Qualifications RGE EnR détenues / exigées par le marché
    labels_q = {"qualipv": "QualiPV", "qualisol": "QualiSol",
                "qualipac": "QualiPAC", "qualibois": "Qualibois"}
    exigees = [lbl for k, lbl in labels_q.items() if qenr.get(k)]
    if exigees:
        sections.append({"label": "Qualifications RGE exigées", "valeur": exigees, "type": "list"})
    autres_q = qenr.get("autres_certifications") or []
    if autres_q:
        sections.append({"label": "Autres certifications", "valeur": autres_q, "type": "list"})
    # Modalités d'exécution : périmètre (raccordement / études) et contraintes
    mlignes = []
    if mod.get("raccordement_reseau_inclus") is not None:
        mlignes.append("Raccordement réseau inclus" if mod["raccordement_reseau_inclus"]
                       else "Raccordement réseau NON inclus")
    if mod.get("etudes_techniques_incluses") is not None:
        mlignes.append("Études techniques incluses" if mod["etudes_techniques_incluses"]
                       else "Études techniques NON incluses")
    if mlignes:
        sections.append({"label": "Périmètre", "valeur": mlignes, "type": "list"})
    if _non_vide(mod.get("calendrier_chantier_contraint")):
        sections.append({"label": "Contrainte calendaire", "valeur": mod["calendrier_chantier_contraint"], "type": "text"})
    sites = mod.get("sites_execution") or []
    if sites:
        sections.append({"label": "Sites d'exécution", "valeur": sites, "type": "list"})
    if _non_vide(mod.get("engagement_productible")):
        sections.append({"label": "Engagement productible", "valeur": mod["engagement_productible"], "type": "text"})
    if _non_vide(mod.get("engagement_disponibilite_om")):
        sections.append({"label": "Engagement disponibilité O&M", "valeur": mod["engagement_disponibilite_om"], "type": "text"})
    # Critères d'éligibilité par lot (souvent les verrous certif / référence)
    crits = enr.get("criteres_eligibilite") or []
    libelles = [c.get("libelle") if isinstance(c, dict) else c for c in crits if c]
    if libelles:
        sections.append({"label": "Critères d'éligibilité", "valeur": libelles, "type": "list"})
    return {"preset_code": "energie_renouvelable", "label": "Énergie", "pct": pct,
            "implemente": True, "sections": sections}


# ===========================================================================
# Lots / Tranches
# ===========================================================================

def tranches_ou_lots(brief, profil):
    """
    Retourne {mode, lignes} où mode ∈ {None, 'lots', 'tranches'}.
    Items lots : {numero, intitule, description, volume, exigences, compat}.
    """
    lots = _get(brief, "lots") or []
    tranches = _get(brief, "tranches") or {}
    # Données plus riches par lot (corps d'état, montant, description détaillée) depuis
    # le bloc allotissement, fusionnées par numéro de lot.
    allot_lots = ((brief or {}).get("allotissement") or {}).get("lots_detailles") or []
    _allot_by_num = {al.get("numero"): al for al in allot_lots if isinstance(al, dict)}
    if len(lots) <= 1 and len(allot_lots) > 1:
        lots = allot_lots  # si lots[] vide mais allotissement détaillé → on prend celui-ci
    if len(lots) > 1:
        import re as _re
        postes = (_get(brief, "cout_realisation", "postes")) or []

        def _poste_lot(num):
            for p in postes:
                if isinstance(p, dict) and num is not None and \
                        _re.search(r"lot\s*0*%s\b" % num, (p.get("poste") or "").lower()):
                    return p
            return None

        def _fourchette_txt(txt):
            """Extrait une fourchette monétaire TOTALE ('300-400 k€') d'un texte de poste.
            Rejette les prix UNITAIRES (suivis de '/m²', '/j'…) qui ne sont pas le coût du lot."""
            if not txt:
                return None
            m = _re.search(r"(\d[\d\s]{1,9})\s*[-–à]\s*(\d[\d\s]{1,9})\s*(k€|M€|m€|€)(?!\s*/)",
                           txt, _re.I)
            if m:
                return f"{m.group(1).replace(' ', '')}–{m.group(2).replace(' ', '')} {m.group(3)}"
            return None

        items = []
        for l in lots:
            al = _allot_by_num.get(l.get("numero")) or {}
            intit = l.get("intitule") or al.get("intitule") or l.get("numero")
            corps = l.get("corps_etat") or al.get("corps_etat")
            montant = l.get("montant_estime") or al.get("montant_estime")
            domaine = l.get("domaine")  # code taxonomie (si ré-extrait) — classification fine
            desc = l.get("description") or al.get("description") or l.get("particularites") or l.get("objet") or ""
            vol = None
            if l.get("volume_estime"):
                _v = l["volume_estime"]
                try:
                    _vf = float(_v)
                    _vs = f"{int(_vf):,}".replace(",", " ") if _vf == int(_vf) else str(_v)
                except (TypeError, ValueError):
                    _vs = str(_v)
                vol = f"{_vs} {l.get('volume_estime_unite', '')}".strip()
            # Coût du lot : fourchette structurée si re-extraite, sinon extraite du poste LLM.
            cmin, cmax = l.get("cout_estime_min_eur"), l.get("cout_estime_max_eur")
            p = _poste_lot(l.get("numero"))
            cout_detail = (p.get("detail") or p.get("poste")) if p else None
            if isinstance(cmin, (int, float)) and isinstance(cmax, (int, float)):
                cout_tag = f"{_fmt_eur(cmin)} – {_fmt_eur(cmax)}"
            else:
                cout_tag = _fourchette_txt(cout_detail)
            _niv, _kw = _compat_lot(str(intit) + " " + str(corps or ""), desc, profil, domaine)
            items.append({
                "numero": l.get("numero"), "intitule": intit, "description": desc,
                "corps_etat": corps, "montant": montant, "domaine": domaine,
                "volume": vol, "exigences": l.get("exigences_specifiques") or l.get("particularites"),
                "cout_tag": cout_tag, "cout_detail": cout_detail,
                "compat": _niv, "compat_kw": _kw})
        return {"mode": "lots", "lignes": items}
    tf = tranches.get("tranche_ferme")
    to = tranches.get("tranches_optionnelles") or []
    if tf or to:
        items = [{"type": "ferme", "libelle": _str(tf)}] if tf else []
        for t in to:
            items.append({"type": "optionnelle", "libelle": _str(t)})
        return {"mode": "tranches", "lignes": items}
    return {"mode": None, "lignes": []}


def _str(v):
    if isinstance(v, dict):
        return v.get("libelle") or v.get("description") or v.get("intitule") or str(v)
    return str(v)


def _norm_txt(s):
    import unicodedata
    norm = unicodedata.normalize("NFKD", str(s or "").lower())
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", norm)


def _compat_lot(intit, desc, profil, domaine=None):
    """Retourne (niveau, mots_matchés). niveau ∈ {coeur, partielle, hors, ?}.

    - Si le lot a un `domaine` (taxonomie) → comparé directement aux domaines couverts (propre).
    - Sinon fallback SUBSTRING de mots-clés FORTS (≥6 car.) : technos EnR + corps de métier
      + compétences + mots-clés catalogue. Un mot-clé TRÈS spécifique (≥10 car., ex
      « photovoltaique ») suffit pour « cœur » ; sinon 2 mots = cœur, 1 = partielle."""
    couverts = set((profil or {}).get("domaines_couverts") or [])
    if domaine and couverts:
        return ("coeur", [domaine]) if domaine in couverts else ("hors", [])
    txt = _norm_txt(str(intit) + " " + str(desc))
    if not txt.strip():
        return ("?", [])
    kws = set()
    for k in ((profil or {}).get("mots_cles_catalogue") or []):
        n = _norm_txt(k).strip()
        if len(n) >= 6:
            kws.add(n)
    for sec, champ in (("energie_renouvelable", "technologies_maitrisees"),
                       ("btp", "corps_de_metier"),
                       ("ingenierie", "competences_specialisees")):
        for c in (_profil_sectoriel(profil, sec).get(champ) or []):
            n = _norm_txt(str(c).replace("_", " ")).strip()
            if len(n) >= 6:
                kws.add(n)
    if not kws:
        return ("?", [])
    hits = [k for k in kws if k in txt]
    if not hits:
        return ("hors", [])
    fort = any(len(k) >= 10 for k in hits)
    if len(hits) >= 2 or fort:
        return ("coeur", hits)
    return ("partielle", hits)


def synthese_lots_pertinents(brief, profil):
    """Sur un marché multi-lots, repère les lots PERTINENTS pour le profil (cœur/partielle)
    et somme leur coût estimé. Retourne {nb, total_lots, cmin, cmax, intitules} ou None.
    Rend visible qu'un marché n'est qu'une opportunité PARTIELLE (ex 1 lot PV / 14)."""
    lots = _get(brief, "lots") or []
    if len(lots) < 2:
        return None
    couverts = set((profil or {}).get("domaines_couverts") or [])
    nb, cmin, cmax, intitules, has_cout = 0, 0, 0, [], False
    for l in lots:
        intit = l.get("intitule") or l.get("numero")
        desc = l.get("description") or l.get("particularites") or ""
        dom = l.get("domaine")
        # Priorité au domaine du lot (extrait par le LLM) si dispo ; sinon fallback mots-clés.
        if dom and couverts:
            pertinent = dom in couverts
        else:
            pertinent = _compat_lot(intit, desc, profil)[0] in ("coeur", "partielle")
        if pertinent:
            nb += 1
            intitules.append(str(intit))
            a, b = l.get("cout_estime_min_eur"), l.get("cout_estime_max_eur")
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                cmin += a
                cmax += b
                has_cout = True
    if nb == 0:
        return None
    return {"nb": nb, "total_lots": len(lots), "intitules": intitules,
            "cmin": cmin if has_cout else None, "cmax": cmax if has_cout else None}


# ===========================================================================
# Richesse du brief
# ===========================================================================

_SECTORIEL_BLOC = {
    "btp": "caracteristiques_techniques_chantier",
    "ingenierie": "caracteristiques_mission_moe",
    "formation": "publics_cibles",
}


def calculer_richesse_brief(brief, presets, marche=None):
    """
    Retourne {score 0-100, niveau, details}. Pondération : socle 45%,
    sectoriel 35%, DCE complet 20%. (La calibration a été retirée du produit ;
    ses 15 pts ont été redistribués — sinon TOUS les briefs perdaient 15 pts et
    s'affichaient « partiel » à tort.)
    """
    if not brief:
        return {"score": 0, "niveau": "light", "details": {}}
    # Socle (40)
    socle_champs = {
        "objet": _non_vide((marche or {}).get("objet") or (marche or {}).get("titre") or brief.get("synthese_marche")),
        "acheteur": _non_vide((marche or {}).get("acheteur_nom")),
        "lots": _non_vide(brief.get("lots")),
        "calendrier": _non_vide(brief.get("calendrier")),
        "bareme": _non_vide(brief.get("bareme_notation")),
        "alertes": _non_vide(brief.get("alertes_candidat")),
    }
    pct_socle = sum(1 for v in socle_champs.values() if v) / len(socle_champs)

    # Sectoriel (30)
    codes = _codes(presets)
    ratios = []
    for code in codes:
        bloc_nom = _SECTORIEL_BLOC.get(code)
        if not bloc_nom:
            continue
        bloc = brief.get(bloc_nom)
        if isinstance(bloc, dict):
            feuilles = list(bloc.values())
            ratios.append(sum(1 for v in feuilles if _non_vide(v)) / max(1, len(feuilles)))
        elif _non_vide(bloc):
            ratios.append(1.0)
    pct_sect = sum(ratios) / len(ratios) if ratios else 0.0

    # DCE complet (15)
    complet = False
    try:
        import auto_brief
        complet = auto_brief.est_brief_complet(brief)
    except Exception:
        complet = _non_vide(brief.get("caracteristiques_techniques_chantier")) or \
                  _non_vide(brief.get("caracteristiques_mission_moe"))

    score = round(45 * pct_socle + 35 * pct_sect + (20 if complet else 0))
    niveau = "complet" if score >= 70 else ("partiel" if score >= 40 else "light")
    return {"score": score, "niveau": niveau,
            "details": {"socle": round(pct_socle * 100), "sectoriel": round(pct_sect * 100),
                        "dce_complet": complet}}
