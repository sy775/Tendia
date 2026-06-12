"""
profil_widgets.py
-----------------
Référentiels de présentation pour les formulaires de profil (Sprint P bis).

Groupages d'enums (familles UX), libellés régions/départements, et helpers qui
transforment une valeur enum + une sélection en structure prête pour les macros
Jinja (checkboxes groupées, zones d'intervention par région).

IMPORTANT : ces groupages sont une convention UX en LECTURE SEULE, jamais
persistée. Toute valeur d'enum non rattachée à un groupe tombe dans « Autres »
(groupage défensif vis-à-vis de l'évolution des schémas). Ils vivent ici (pas
dans les presets) car ils relèvent de la présentation, pas de la configuration
sectorielle (cf Décision 4 : templates explicites, pas de méta-schéma).

Source du mapping département → région : matching.DEPARTEMENT_VERS_REGION.
"""

import matching


# ===========================================================================
# Libellés
# ===========================================================================

REGION_LIBELLE = {
    "IDF": "Île-de-France", "ARA": "Auvergne-Rhône-Alpes",
    "BFC": "Bourgogne-Franche-Comté", "BRE": "Bretagne",
    "CVL": "Centre-Val de Loire", "COR": "Corse", "GES": "Grand Est",
    "HDF": "Hauts-de-France", "NOR": "Normandie",
    "NAQ": "Nouvelle-Aquitaine", "OCC": "Occitanie",
    "PDL": "Pays de la Loire", "PACA": "Provence-Alpes-Côte d'Azur",
    "GUA": "Guadeloupe", "MAR": "Martinique", "GUY": "Guyane",
    "REU": "La Réunion", "MAY": "Mayotte",
}

# Ordre d'affichage des régions (métropole puis Outre-mer).
REGION_ORDRE = ["IDF", "ARA", "BFC", "BRE", "CVL", "COR", "GES", "HDF",
                "NOR", "NAQ", "OCC", "PDL", "PACA",
                "GUA", "MAR", "GUY", "REU", "MAY"]

DEPARTEMENT_LIBELLE = {
    "01": "Ain", "02": "Aisne", "03": "Allier", "04": "Alpes-de-Haute-Provence",
    "05": "Hautes-Alpes", "06": "Alpes-Maritimes", "07": "Ardèche",
    "08": "Ardennes", "09": "Ariège", "10": "Aube", "11": "Aude",
    "12": "Aveyron", "13": "Bouches-du-Rhône", "14": "Calvados", "15": "Cantal",
    "16": "Charente", "17": "Charente-Maritime", "18": "Cher", "19": "Corrèze",
    "2A": "Corse-du-Sud", "2B": "Haute-Corse", "21": "Côte-d'Or",
    "22": "Côtes-d'Armor", "23": "Creuse", "24": "Dordogne", "25": "Doubs",
    "26": "Drôme", "27": "Eure", "28": "Eure-et-Loir", "29": "Finistère",
    "30": "Gard", "31": "Haute-Garonne", "32": "Gers", "33": "Gironde",
    "34": "Hérault", "35": "Ille-et-Vilaine", "36": "Indre",
    "37": "Indre-et-Loire", "38": "Isère", "39": "Jura", "40": "Landes",
    "41": "Loir-et-Cher", "42": "Loire", "43": "Haute-Loire",
    "44": "Loire-Atlantique", "45": "Loiret", "46": "Lot", "47": "Lot-et-Garonne",
    "48": "Lozère", "49": "Maine-et-Loire", "50": "Manche", "51": "Marne",
    "52": "Haute-Marne", "53": "Mayenne", "54": "Meurthe-et-Moselle",
    "55": "Meuse", "56": "Morbihan", "57": "Moselle", "58": "Nièvre",
    "59": "Nord", "60": "Oise", "61": "Orne", "62": "Pas-de-Calais",
    "63": "Puy-de-Dôme", "64": "Pyrénées-Atlantiques", "65": "Hautes-Pyrénées",
    "66": "Pyrénées-Orientales", "67": "Bas-Rhin", "68": "Haut-Rhin",
    "69": "Rhône", "70": "Haute-Saône", "71": "Saône-et-Loire", "72": "Sarthe",
    "73": "Savoie", "74": "Haute-Savoie", "75": "Paris", "76": "Seine-Maritime",
    "77": "Seine-et-Marne", "78": "Yvelines", "79": "Deux-Sèvres", "80": "Somme",
    "81": "Tarn", "82": "Tarn-et-Garonne", "83": "Var", "84": "Vaucluse",
    "85": "Vendée", "86": "Vienne", "87": "Haute-Vienne", "88": "Vosges",
    "89": "Yonne", "90": "Territoire de Belfort", "91": "Essonne",
    "92": "Hauts-de-Seine", "93": "Seine-Saint-Denis", "94": "Val-de-Marne",
    "95": "Val-d'Oise", "971": "Guadeloupe", "972": "Martinique",
    "973": "Guyane", "974": "La Réunion", "976": "Mayotte",
}

# Libellés lisibles pour les valeurs enum dont la dérivation auto est imparfaite.
_LABEL_OVERRIDES = {
    "vrd": "VRD", "cvc": "CVC", "opc": "OPC", "sps": "SPS", "gtb_gtc": "GTB/GTC",
    "bim_management": "BIM management",
    "electricite_cfo": "Électricité CFO", "electricite_cfa": "Électricité CFA",
    "moe_complete_batiment": "MOE complète — bâtiment",
    "moe_partielle_batiment": "MOE partielle — bâtiment",
    "moe_complete_infrastructure": "MOE complète — infrastructure",
    "moe_partielle_infrastructure": "MOE partielle — infrastructure",
    "bet_structure": "BET structure", "bet_fluides_cvc": "BET fluides/CVC",
    "bet_thermique_energie": "BET thermique/énergie",
    "bet_environnement": "BET environnement", "bet_geotechnique": "BET géotechnique",
    "bet_acoustique": "BET acoustique", "bet_vrd": "BET VRD",
    "amo_technique": "AMO technique", "amo_programmation": "AMO programmation",
    "etude_impact": "Étude d'impact", "etude_diagnostic": "Étude / diagnostic",
    "ouvrage_art": "Ouvrage d'art", "ouvrages_art": "Ouvrages d'art",
    "reseaux_humides": "Réseaux humides", "reseaux_secs": "Réseaux secs",
    "economie_construction": "Économie de la construction",
    "sem_sapl": "SEM / SPL", "bailleur_social_OPH": "Bailleur social / OPH",
    "epa": "EPA (ét. public d'aménagement)", "concessionnaire_reseaux": "Concessionnaire réseaux",
    "sante_chu_chr": "CHU / CHR", "sante_etablissement_local": "Ét. de santé local",
    "etat_administration_centrale": "État — administration centrale",
    "etat_service_deconcentre": "État — service déconcentré",
    "etablissement_public_local": "Ét. public local",
    "etablissement_public_national": "Ét. public national",
    "isolation_thermique_exterieure": "Isolation thermique extérieure",
    "signalisation_horizontale": "Signalisation horizontale",
}


def _label(valeur: str) -> str:
    """Libellé lisible d'une valeur enum (override sinon dérivation auto)."""
    if valeur in _LABEL_OVERRIDES:
        return _LABEL_OVERRIDES[valeur]
    return str(valeur).replace("_", " ").capitalize()


# ===========================================================================
# Groupages d'enums (familles UX, ordre lecteur gros -> fin)
# ===========================================================================

GROUPAGES_BTP_CORPS_METIER = {
    "Gros œuvre / structure": ["gros_oeuvre", "vrd", "terrassement", "demolition",
                               "charpente_bois", "charpente_metallique"],
    "Enveloppe / clos couvert": ["couverture", "etancheite", "menuiseries_exterieures",
                                 "isolation_thermique_exterieure"],
    "Second œuvre / aménagement": ["cloisons_doublages", "menuiseries_interieures",
                                   "sols_durs", "sols_souples", "peinture"],
    "Lots techniques": ["plomberie", "cvc", "electricite_cfo", "electricite_cfa", "ascenseurs"],
    "Aménagements extérieurs": ["espaces_verts", "signalisation_horizontale"],
}

GROUPAGES_BTP_TYPES_OUVRAGES = {
    "Bâtiment public": ["batiment_administratif", "etablissement_sante",
                        "etablissement_scolaire", "etablissement_sportif", "equipement_culturel"],
    "Logement": ["logement_social", "logement_prive"],
    "Infrastructure / VRD": ["voirie_communale", "ouvrage_art", "reseaux_humides",
                             "reseaux_secs", "espaces_publics"],
    "Spécifique": ["patrimoine_classe", "datacenter", "industriel", "agricole"],
}

GROUPAGES_ING_TYPOLOGIES = {
    "Maîtrise d'œuvre bâtiment": ["moe_complete_batiment", "moe_partielle_batiment"],
    "Maîtrise d'œuvre infra": ["moe_complete_infrastructure", "moe_partielle_infrastructure"],
    "Bureaux d'études spécialisés": ["bet_structure", "bet_fluides_cvc", "bet_thermique_energie",
                                     "bet_environnement", "bet_geotechnique", "bet_acoustique", "bet_vrd"],
    "AMO / études amont": ["amo_technique", "amo_programmation", "etude_impact", "etude_diagnostic"],
    "Topographie / mesure": ["topographie", "geometre"],
}

GROUPAGES_ING_COMPETENCES = {
    "Structure": ["structure_beton", "structure_beton_precontraint", "structure_bois",
                  "structure_acier", "structure_mixte"],
    "Fluides / Thermique": ["fluides_cvc", "plomberie_sanitaire", "electricite_cfo",
                            "electricite_cfa", "gtb_gtc", "thermique_dynamique"],
    "Acoustique / Géotechnique": ["acoustique_batiment", "acoustique_environnement", "geotechnique"],
    "Hydraulique": ["hydraulique_eau_potable", "hydraulique_assainissement", "hydraulique_pluvial"],
    "Environnement / réglementaire": ["environnement_etudes_impact", "environnement_icpe", "environnement_loi_eau"],
    "Infrastructure": ["vrd", "ouvrages_art"],
    "Transverse / pilotage": ["economie_construction", "opc", "sps", "bim_management"],
}

GROUPAGES_ING_TYPES_OUVRAGES = GROUPAGES_BTP_TYPES_OUVRAGES  # même vocabulaire

GROUPAGES_TYPES_CLIENTS_PUBLICS = {
    "Territoriaux": ["commune", "communaute_communes", "communaute_agglo", "metropole",
                     "conseil_departemental", "conseil_regional", "syndicat_mixte"],
    "État": ["etat_administration_centrale", "etat_service_deconcentre", "defense_armees", "justice"],
    "Établissements publics": ["etablissement_public_local", "etablissement_public_national",
                               "epa", "concessionnaire_reseaux", "sem_sapl"],
    "Santé": ["sante_chu_chr", "sante_etablissement_local"],
    "Logement social": ["bailleur_social_OPH"],
}


# ===========================================================================
# Helpers de construction des structures pour Jinja
# ===========================================================================

def widget_checkboxes_groupees(valeurs_actuelles, groupages, enum_complet=None) -> list:
    """
    Construit la structure de checkboxes groupées.

    Retourne [{"famille": str, "options": [{"value","label","checked"}]}].
    Le groupe « Autres » capture les valeurs de `enum_complet` non rattachées,
    ainsi que toute valeur sélectionnée inconnue (robustesse évolution schéma).
    """
    selection = set(valeurs_actuelles or [])
    vus = set()
    out = []
    for famille, valeurs in groupages.items():
        options = []
        for v in valeurs:
            vus.add(v)
            options.append({"value": v, "label": _label(v), "checked": v in selection})
        out.append({"famille": famille, "options": options})

    autres = []
    for v in (enum_complet or []):
        if v not in vus:
            autres.append(v)
    for v in selection:
        if v not in vus and v not in autres:
            autres.append(v)
    if autres:
        out.append({"famille": "Autres", "options": [
            {"value": v, "label": _label(v), "checked": v in selection} for v in autres]})
    return out


def _depts_par_region() -> dict:
    """Inverse DEPARTEMENT_VERS_REGION -> {region: [codes triés]}."""
    out = {}
    for dept, region in matching.DEPARTEMENT_VERS_REGION.items():
        out.setdefault(region, []).append(dept)
    def _cle(code):
        if code.isdigit():
            return (0, int(code))
        return (1, code)  # 2A, 2B après les numériques courts
    for region in out:
        out[region].sort(key=_cle)
    return out


def widget_zones_intervention(valeurs_actuelles) -> list:
    """
    Structure des zones d'intervention groupées par région.

    Retourne [{"region", "label", "departements": [{"code","nom","checked"}]}].
    """
    selection = set(valeurs_actuelles or [])
    depts_region = _depts_par_region()
    out = []
    for region in REGION_ORDRE:
        depts = depts_region.get(region, [])
        if not depts:
            continue
        out.append({
            "region": region,
            "label": REGION_LIBELLE.get(region, region),
            "departements": [
                {"code": d, "nom": DEPARTEMENT_LIBELLE.get(d, d), "checked": d in selection}
                for d in depts
            ],
        })
    return out


def options_enum(code_preset: str, propriete: str) -> list:
    """Liste brute des valeurs enum d'une propriété array d'un schéma sectoriel."""
    import organisme
    sch = organisme.schema_sectoriel(code_preset) or {}
    spec = (sch.get("properties") or {}).get(propriete) or {}
    if spec.get("type") == "array":
        return (spec.get("items") or {}).get("enum") or []
    return []


def options_select(valeurs, selection_courante=None) -> list:
    """[{value,label,selected}] pour un <select> simple depuis une liste enum."""
    return [{"value": v, "label": _label(v), "selected": v == selection_courante}
            for v in valeurs]


# Enum des phases de réalisation (références études) — repris du schéma ingénierie.
PHASES_ETUDES = ["ESQ", "APS", "APD", "PRO", "DCE", "ACT", "EXE", "OPC", "AOR", "DIAG"]
STATUTS_REFERENCE = ["livre", "en_cours", "abandonne"]


def contexte_widgets(profil: dict) -> dict:
    """
    Pré-calcule toutes les structures de widgets nécessaires à l'édition d'un
    profil (zones + checkboxes groupées par preset couvert). Garde la route
    Flask légère.
    """
    presets = profil.get("presets_couverts") or []
    sect = profil.get("profils_sectoriels") or {}
    ctx = {"zones": widget_zones_intervention(profil.get("zones_intervention"))}

    if "btp" in presets:
        b = sect.get("btp") or {}
        ctx["btp"] = {
            "corps_de_metier": widget_checkboxes_groupees(
                b.get("corps_de_metier"), GROUPAGES_BTP_CORPS_METIER,
                options_enum("btp", "corps_de_metier")),
            "types_ouvrages": widget_checkboxes_groupees(
                b.get("types_ouvrages"), GROUPAGES_BTP_TYPES_OUVRAGES,
                options_enum("btp", "types_ouvrages")),
            "types_clients_publics": widget_checkboxes_groupees(
                b.get("types_clients_publics"), GROUPAGES_TYPES_CLIENTS_PUBLICS,
                options_enum("btp", "types_clients_publics")),
            "ref_types_ouvrages": options_enum("btp", "types_ouvrages"),
        }

    if "ingenierie" in presets:
        g = sect.get("ingenierie") or {}
        ctx["ingenierie"] = {
            "typologies_couvertes": widget_checkboxes_groupees(
                g.get("typologies_couvertes"), GROUPAGES_ING_TYPOLOGIES,
                options_enum("ingenierie", "typologies_couvertes")),
            "competences_specialisees": widget_checkboxes_groupees(
                g.get("competences_specialisees"), GROUPAGES_ING_COMPETENCES,
                options_enum("ingenierie", "competences_specialisees")),
            "types_ouvrages_etudies": widget_checkboxes_groupees(
                g.get("types_ouvrages_etudies"), GROUPAGES_ING_TYPES_OUVRAGES,
                options_enum("ingenierie", "types_ouvrages_etudies")),
            "types_clients_publics": widget_checkboxes_groupees(
                g.get("types_clients_publics"), GROUPAGES_TYPES_CLIENTS_PUBLICS,
                options_enum("ingenierie", "types_clients_publics")),
            "ref_types_ouvrages": options_enum("ingenierie", "types_ouvrages_etudies"),
            "ref_typologies": options_enum("ingenierie", "typologies_couvertes"),
            "ref_competences": options_enum("ingenierie", "competences_specialisees"),
        }

    return ctx
