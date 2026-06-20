"""
profil_form.py
--------------
Parsing des formulaires d'édition de profil (Sprint P) : convertit les champs
HTML POST en dict profil, par MERGE sur le profil existant (les champs non
rendus dans le formulaire sont préservés tels quels — zéro perte de données).

Conventions de nommage des champs HTML :
  - scalaires       : dot-notation du chemin profil, ex `identite.raison_sociale`
  - sous-objets     : dot-notation, ex `identite.adresse_siege.code_postal`
  - arrays string   : suffixe `__lignes` (textarea, 1 valeur/ligne)
  - arrays enum     : name répété (checkboxes), lu via getlist
  - arrays d'objets : suffixe `__json` (textarea JSON inline)
  - booleens        : checkbox (présent = True)
  - presets         : `presets_couverts` (checkboxes, getlist)
  - auto-réponses   : `ar_cle` / `ar_val` répétés (getlist), zippés

Les champs sectoriels sont préfixés `sect.<code>.` côté HTML et rangés dans
`profils_sectoriels.<code>.` côté profil.

Testable sans Flask : `parse(form, profil_existant)` accepte tout objet
exposant `.get(name)` et `.getlist(name)` (werkzeug MultiDict ou shim de test).
"""

import copy
import json
import re


# ---------------------------------------------------------------------------
# Helpers bas niveau
# ---------------------------------------------------------------------------

def _set(d: dict, path: str, value) -> None:
    """Pose `value` au chemin dot-notation, créant les sous-dicts au besoin."""
    keys = path.split(".")
    cur = d
    for k in keys[:-1]:
        if not isinstance(cur.get(k), dict):
            cur[k] = {}
        cur = cur[k]
    cur[keys[-1]] = value


def _lignes(texte) -> list:
    """Textarea -> liste de strings (trim, lignes vides retirées)."""
    if not texte:
        return []
    return [l.strip() for l in str(texte).replace("\r", "").split("\n") if l.strip()]


def _to_int(s):
    """('', None) -> None ; '42' -> 42 ; invalide -> ValueError."""
    s = (s or "").strip().replace(" ", "")
    if s == "":
        return None
    return int(s)


def _to_num(s):
    """Nombre (int si entier). Accepte virgule décimale et espaces milliers."""
    s = (s or "").strip().replace(" ", "").replace(" ", "").replace(",", ".")
    if s == "":
        return None
    f = float(s)
    return int(f) if f.is_integer() else f


# ---------------------------------------------------------------------------
# Descripteurs de champs (par section). Format : (form_name, profil_path, type)
# Types : text | int | num | bool | date | lignes | json
# (les `enum`/checkbox-multi et presets sont traités à part via getlist)
# ---------------------------------------------------------------------------

_SOCLE = [
    ("identite.raison_sociale", "identite.raison_sociale", "text"),
    ("identite.forme_juridique", "identite.forme_juridique", "text"),
    ("identite.siren", "identite.siren", "text"),
    ("identite.siret_siege", "identite.siret_siege", "text"),
    ("identite.naf_principal", "identite.naf_principal", "text"),
    ("identite.effectif_salaries", "identite.effectif_salaries", "int"),
    ("identite.annee_creation", "identite.annee_creation", "int"),
    ("identite.tva_intracom", "identite.tva_intracom", "text"),
    ("identite.site_web", "identite.site_web", "text"),
    ("identite.adresse_siege.rue", "identite.adresse_siege.rue", "text"),
    ("identite.adresse_siege.code_postal", "identite.adresse_siege.code_postal", "text"),
    ("identite.adresse_siege.ville", "identite.adresse_siege.ville", "text"),
    ("identite.adresse_siege.departement", "identite.adresse_siege.departement", "text"),
    ("identite.contact_AO.nom", "identite.contact_AO.nom", "text"),
    ("identite.contact_AO.fonction", "identite.contact_AO.fonction", "text"),
    ("identite.contact_AO.email", "identite.contact_AO.email", "text"),
    ("identite.contact_AO.telephone", "identite.contact_AO.telephone", "text"),
    ("capacite_globale.ca_annuel_n_moins_1", "capacite_globale.ca_annuel_n_moins_1", "num"),
    ("capacite_globale.ca_annuel_n_moins_2", "capacite_globale.ca_annuel_n_moins_2", "num"),
    ("capacite_globale.ca_annuel_n_moins_3", "capacite_globale.ca_annuel_n_moins_3", "num"),
    ("capacite_globale.fonds_propres", "capacite_globale.fonds_propres", "num"),
    ("capacite_globale.effectif_total_etp", "capacite_globale.effectif_total_etp", "int"),
    ("capacite_globale.capacite_engagement_simultane", "capacite_globale.capacite_engagement_simultane", "num"),
    ("capacite_globale.seuil_minimum_marche_eur", "capacite_globale.seuil_minimum_marche_eur", "num"),
    ("economie.marge_brute_cible_pct", "economie.marge_brute_cible_pct", "num"),
    ("economie.taux_journalier_moyen_eur", "economie.taux_journalier_moyen_eur", "num"),
    ("economie.frais_de_structure_pct", "economie.frais_de_structure_pct", "num"),
    ("economie.agressivite_commerciale", "economie.agressivite_commerciale", "text"),
    ("mots_cles_catalogue", "mots_cles_catalogue", "lignes"),
    ("zones_strict", "zones_strict", "bool"),
]
# zones_intervention est rendu en checkboxes (départements) -> getlist, pas textarea.

# Champs sectoriels BTP. Chemin profil relatif au bloc profils_sectoriels.btp
_BTP = [
    ("qualifications.qualibat", "lignes"),
    ("qualifications.opqibi", "lignes"),
    ("qualifications.autres", "lignes"),
    ("qualifications.iso_9001", "bool"),
    ("qualifications.iso_14001", "bool"),
    ("qualifications.iso_45001", "bool"),
    ("qualifications.rge.detenue", "bool"),
    ("qualifications.rge.specialites", "lignes"),
    ("qualifications.rge.validite_jusqu", "date"),
    ("qualifications.mase.detenue", "bool"),
    ("qualifications.mase.validite_jusqu", "date"),
    ("qualifications.amiante.ss3", "bool"),
    ("qualifications.amiante.ss4", "bool"),
    ("qualifications.amiante.validite_jusqu", "date"),
    ("capacite_chantiers.ca_btp_annuel", "num"),
    ("capacite_chantiers.montant_max_par_chantier", "num"),
    ("capacite_chantiers.nb_chantiers_simultanes_max", "int"),
    ("capacite_chantiers.effectif_chantier_etp", "int"),
    ("capacite_chantiers.rayon_intervention_km", "int"),
    ("rh_chantier.encadrement.conducteurs_travaux", "int"),
    ("rh_chantier.encadrement.chefs_chantier", "int"),
    ("rh_chantier.encadrement.chefs_equipe", "int"),
    ("rh_chantier.operationnels.compagnons_qualifies", "int"),
    ("rh_chantier.operationnels.ouvriers_non_qualifies", "int"),
    ("rh_chantier.operationnels.apprentis", "int"),
    ("rh_chantier.habilitations_diverses", "lignes"),
    ("moyens_materiels", "lignes"),
    ("pratiques_specifiques.clause_insertion_sociale.pratiquee", "bool"),
    ("pratiques_specifiques.clause_insertion_sociale.heures_realisees_annee", "int"),
    ("pratiques_specifiques.clause_insertion_sociale.partenaires", "lignes"),
    ("pratiques_specifiques.demarche_environnementale.label_rse", "text"),
    ("pratiques_specifiques.demarche_environnementale.bilan_carbone_realise", "bool"),
    ("pratiques_specifiques.demarche_environnementale.filieres_dechets_tracees", "bool"),
    ("pratiques_specifiques.demarche_environnementale.materiaux_biosources_pratiques", "bool"),
    ("pratiques_specifiques.bim.pratique", "bool"),
    ("pratiques_specifiques.bim.niveau_max", "text"),
]

# Champs sectoriels INGENIERIE
_ING = [
    ("qualifications.opqibi", "lignes"),
    ("qualifications.opqcm", "lignes"),
    ("qualifications.autres", "lignes"),
    ("qualifications.iso_9001", "bool"),
    ("qualifications.iso_14001", "bool"),
    ("qualifications.iso_45001", "bool"),
    ("assurances.decennale_ingenierie.detenue", "bool"),
    ("assurances.decennale_ingenierie.plafond_eur", "num"),
    ("assurances.decennale_ingenierie.validite_jusqu", "date"),
    ("assurances.rc_pro.detenue", "bool"),
    ("assurances.rc_pro.plafond_eur", "num"),
    ("assurances.rc_pro.validite_jusqu", "date"),
    ("capacite_etudes.ca_ingenierie_annuel", "num"),
    ("capacite_etudes.montant_travaux_max_supervisable", "num"),
    ("capacite_etudes.nb_missions_simultanees_max", "int"),
    ("capacite_etudes.effectif_etudes_etp", "int"),
    ("rh_etudes.encadrement.directeur_etudes", "int"),
    ("rh_etudes.encadrement.chef_projet", "int"),
    ("rh_etudes.encadrement.ingenieur_senior", "int"),
    ("rh_etudes.production.ingenieur_confirme", "int"),
    ("rh_etudes.production.ingenieur_junior", "int"),
    ("rh_etudes.production.technicien_be", "int"),
    ("rh_etudes.production.dessinateur_projeteur", "int"),
    ("rh_etudes.architectes_hmonp", "int"),
    ("outils_logiciels", "lignes"),
    ("pratiques_specifiques.bim.pratique", "bool"),
    ("pratiques_specifiques.bim.niveau_max", "text"),
    ("pratiques_specifiques.bim.certifications_team", "lignes"),
    ("pratiques_specifiques.demarche_environnementale.label_rse", "text"),
    ("pratiques_specifiques.demarche_environnementale.bilan_carbone_realise", "bool"),
    ("pratiques_specifiques.demarche_environnementale.hqe_certification", "text"),
    ("pratiques_specifiques.clause_insertion_sociale.pratiquee", "bool"),
    ("pratiques_specifiques.clause_insertion_sociale.heures_realisees_annee", "int"),
    ("pratiques_specifiques.clause_insertion_sociale.partenaires", "lignes"),
]

# Arrays d'enum rendus en checkboxes groupées (lus via getlist).
# (form_name_court, path_rel)
_BTP_ENUM_ARRAYS = [
    ("corps_de_metier", "corps_de_metier"),
    ("types_ouvrages", "types_ouvrages"),
    ("types_clients_publics", "types_clients_publics"),
]
_ING_ENUM_ARRAYS = [
    ("typologies_couvertes", "typologies_couvertes"),
    ("competences_specialisees", "competences_specialisees"),
    ("types_ouvrages_etudies", "types_ouvrages_etudies"),
    ("types_clients_publics", "types_clients_publics"),
]

# ---------------------------------------------------------------------------
# Sous-formulaires "arrays d'objets" (références). Champs nommés
# `references_chantiers[N].champ` / `references_etudes[N].champ`.
# Descripteurs : scalaires (champ, type) ; listes (champ, mode) où mode ∈
# {"checkbox" (getlist), "lignes" (textarea 1/ligne)} ; requis = champs
# obligatoires si le bloc est non vide.
# ---------------------------------------------------------------------------

_REF_BTP = {
    "prefix": "references_chantiers",
    "scalaires": [("annee", "int"), ("client", "text"), ("ouvrage", "text"),
                  ("type_ouvrage", "text"), ("montant_eur_ht", "num"),
                  ("duree_mois", "int"), ("statut", "text"), ("notes", "text")],
    "listes": [("corps_etat", "lignes")],
    "requis": ["annee", "ouvrage", "type_ouvrage"],
}
_REF_ING = {
    "prefix": "references_etudes",
    "scalaires": [("annee", "int"), ("client", "text"), ("projet", "text"),
                  ("type_ouvrage", "text"), ("montant_travaux_eur_ht", "num"),
                  ("honoraires_eur_ht", "num"), ("duree_mois", "int"),
                  ("statut", "text"), ("notes", "text")],
    "listes": [("typologies_mission", "checkbox"), ("competences_mobilisees", "checkbox"),
               ("phases_realisees", "checkbox")],
    "requis": ["annee", "projet", "type_ouvrage"],
}

# Champs sectoriels FORMATION (legacy). Chemins relatifs au profil RACINE
# (le legacy ne range pas sous profils_sectoriels).
_FORMATION = [
    ("thematiques_metiers", "thematiques_metiers", "lignes"),
    ("certifications.qualiopi_actions_formation", "certifications.qualiopi_actions_formation", "bool"),
    ("certifications.qualiopi_apprentissage", "certifications.qualiopi_apprentissage", "bool"),
    ("certifications.qualiopi_bilans", "certifications.qualiopi_bilans", "bool"),
]


# ---------------------------------------------------------------------------
# Application d'un descripteur
# ---------------------------------------------------------------------------

def _appliquer(cible: dict, form, form_name: str, path: str, typ: str, erreurs: dict):
    """Applique un champ form au dict cible au chemin `path`. Remplit `erreurs`
    sur valeur invalide (et préserve alors l'existant)."""
    if typ == "bool":
        # checkbox : présent (toute valeur) = True, absent = False
        _set(cible, path, form.get(form_name) is not None)
        return
    # Champ non-booléen totalement absent du POST (None) = non rendu -> on
    # préserve l'existant. Un champ rendu mais vide renvoie "" (distinct de None).
    if form.get(form_name) is None:
        return
    if typ == "lignes":
        _set(cible, path, _lignes(form.get(form_name)))
        return
    if typ in ("text", "date"):
        _set(cible, path, (form.get(form_name) or "").strip())
        return
    if typ in ("int", "num"):
        brut = form.get(form_name)
        try:
            val = _to_int(brut) if typ == "int" else _to_num(brut)
        except (ValueError, TypeError):
            erreurs[form_name] = f"Valeur numérique invalide : {brut!r}"
            return  # préserve l'existant
        _set(cible, path, val)
        return
    if typ == "json":
        brut = (form.get(form_name) or "").strip()
        if brut == "":
            _set(cible, path, [])
            return
        try:
            val = json.loads(brut)
        except json.JSONDecodeError as e:
            erreurs[form_name] = f"JSON invalide : {e}"
            return  # préserve l'existant
        _set(cible, path, val)
        return


def _getlist(form, name) -> list:
    """getlist robuste (werkzeug MultiDict ou shim de test)."""
    if hasattr(form, "getlist"):
        return form.getlist(name)
    v = form.get(name)
    return v if isinstance(v, list) else ([v] if v else [])


def _parse_references(form, descr: dict, erreurs: dict) -> list:
    """
    Reconstruit une liste d'objets « références » depuis les champs indexés
    `prefix[N].champ`. Filtre les blocs entièrement vides. Valide les champs
    requis des blocs non vides (erreur ciblée par champ). Tolère les trous
    d'index (suppression d'un bloc côté UI sans réindexation).
    """
    prefix = descr["prefix"]
    pat = re.compile(r"^" + re.escape(prefix) + r"\[(\d+)\]\.")
    idxs = set()
    for cle in form.keys():
        m = pat.match(cle)
        if m:
            idxs.add(int(m.group(1)))

    refs = []
    for i in sorted(idxs):
        base = f"{prefix}[{i}]."
        obj = {}
        vide = True
        for champ, typ in descr["scalaires"]:
            brut = form.get(base + champ)
            if brut is None:
                continue
            brut_s = str(brut).strip()
            if typ in ("int", "num"):
                if brut_s == "":
                    obj[champ] = None
                    continue
                try:
                    obj[champ] = _to_int(brut_s) if typ == "int" else _to_num(brut_s)
                    vide = False
                except (ValueError, TypeError):
                    erreurs[base + champ] = f"Valeur numérique invalide : {brut_s!r}"
                    vide = False
            else:
                obj[champ] = brut_s
                if brut_s:
                    vide = False
        for champ, mode in descr["listes"]:
            vals = _getlist(form, base + champ) if mode == "checkbox" else _lignes(form.get(base + champ))
            obj[champ] = vals
            if vals:
                vide = False
        if vide:
            continue
        for r in descr["requis"]:
            if obj.get(r) in (None, "", []):
                erreurs[base + r] = "Champ requis manquant dans cette référence."
        refs.append(obj)
    return refs


# ---------------------------------------------------------------------------
# Parse principal
# ---------------------------------------------------------------------------

def parse(form, profil_existant: dict):
    """
    Reconstruit un dict profil depuis le formulaire, par merge sur l'existant.

    Retourne (profil, erreurs_champs) où erreurs_champs = {form_name: message}.
    La validation métier (valider_profil) est faite par l'appelant.
    """
    profil = copy.deepcopy(profil_existant or {})
    erreurs = {}

    # 1) Socle
    for form_name, path, typ in _SOCLE:
        _appliquer(profil, form, form_name, path, typ, erreurs)

    # 1bis) zones d'intervention (checkboxes département -> getlist)
    profil["zones_intervention"] = _getlist(form, "zones_intervention")

    # 2) presets_couverts (checkboxes)
    presets = _getlist(form, "presets_couverts")
    profil["presets_couverts"] = presets
    sectoriels = profil.setdefault("profils_sectoriels", {})
    # crée un bloc vide pour un preset nouvellement coché
    for code in presets:
        sectoriels.setdefault(code, {})

    # 2bis) presets_priorites (1=principal…) — champ `preset_priorite.<code>` par preset
    # coché. À défaut, l'ordre de cochage sert de priorité (1er = principal).
    priorites = {}
    for i, code in enumerate(presets, 1):
        brut = form.get(f"preset_priorite.{code}")
        try:
            priorites[code] = max(1, int(brut)) if brut else i
        except (TypeError, ValueError):
            priorites[code] = i
    profil["presets_priorites"] = priorites

    # 2ter) domaines_couverts (cases taxonomie) — pilote le matching fin généralisé.
    profil["domaines_couverts"] = _getlist(form, "domaines_couverts")

    # 3) auto_reponses_exigences (paires clé/valeur)
    cles = _getlist(form, "ar_cle")
    vals = _getlist(form, "ar_val")
    auto = {}
    for c, v in zip(cles, vals):
        c = (c or "").strip()
        if c:
            auto[c] = (v or "").strip()
    # Ne touche l'existant QUE si le bloc Avancé/auto-réponses est dans le form
    # (sinon retirer l'onglet Avancé effacerait les valeurs au save).
    if cles:
        profil["auto_reponses_exigences"] = auto

    # 4) Sectoriel BTP
    if "btp" in presets:
        bloc = sectoriels.setdefault("btp", {})
        for path_rel, typ in _BTP:
            _appliquer(bloc, form, f"sect.btp.{path_rel}", path_rel, typ, erreurs)
        for form_court, path_rel in _BTP_ENUM_ARRAYS:
            _set(bloc, path_rel, _getlist(form, f"sect.btp.{form_court}"))
        _set(bloc, "references_chantiers", _parse_references(form, _REF_BTP, erreurs))

    # 5) Sectoriel INGENIERIE
    if "ingenierie" in presets:
        bloc = sectoriels.setdefault("ingenierie", {})
        for path_rel, typ in _ING:
            _appliquer(bloc, form, f"sect.ingenierie.{path_rel}", path_rel, typ, erreurs)
        for form_court, path_rel in _ING_ENUM_ARRAYS:
            _set(bloc, path_rel, _getlist(form, f"sect.ingenierie.{form_court}"))
        _set(bloc, "references_etudes", _parse_references(form, _REF_ING, erreurs))

    # 5bis) Sectoriel ÉNERGIES RENOUVELABLES (enum arrays : technologies / prestations / segments)
    if "energie_renouvelable" in presets:
        bloc = sectoriels.setdefault("energie_renouvelable", {})
        # Garde-fous schéma (id + identite requis) — préservés si déjà présents.
        bloc.setdefault("id", "energie_renouvelable")
        if not bloc.get("identite"):
            bloc["identite"] = {"nom": (profil.get("identite") or {}).get("raison_sociale", "")}
        for champ in ("technologies_maitrisees", "types_prestations", "segments_clients"):
            _set(bloc, champ, _getlist(form, f"sect.energie_renouvelable.{champ}"))

    # 6) Formation legacy (chemins racine)
    legacy = any(form.get(f"sect.formation.{n}") is not None or _getlist(form, f"sect.formation.{n}")
                 for n, _, _ in _FORMATION)
    # Seulement si le form contient réellement des champs formation (panel présent) —
    # sinon on préserve l'existant (l'onglet Avancé/Formation legacy a été retiré).
    if legacy:
        for form_name, path, typ in _FORMATION:
            _appliquer(profil, form, f"sect.formation.{form_name}", path, typ, erreurs)
        profil["directions_regionales_couvertes"] = _getlist(form, "sect.formation.directions_regionales_couvertes")
        profil["prestations_maitrisees"] = _getlist(form, "sect.formation.prestations_maitrisees")

    return profil, erreurs
