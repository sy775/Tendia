"""
scripts/ingester_profil_tee27.py — ingère le profil TEE27 (SEML Transition Euroise
Énergies) dans la bibliothèque de profils, puis l'active.

Profil : AMO/BE EnR (principal) + ingénierie énergétique bâtiment (secondaire) +
conseil stratégique collectivités (tertiaire). Zone STRICTE Eure (27).
Le profil actif précédent (Tridyne) reste en bibliothèque (profil_ingenierie_demo).

Usage : python scripts/ingester_profil_tee27.py
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import organisme


def construire_profil():
    p = organisme.template_profil_complet(["energie_renouvelable", "ingenierie", "conseil"])

    # --- Socle / identité ---
    idt = p["identite"]
    idt["raison_sociale"] = "SEML Transition Euroise Énergies"
    idt["forme_juridique"] = "SEML (Société d'Économie Mixte Locale)"
    idt["siren"] = ""        # à compléter via Sirene/INPI
    idt["siret_siege"] = ""
    idt["site_web"] = "https://tee27.fr"
    idt["adresse_siege"] = {"rue": "12 rue Concorde", "code_postal": "27930",
                             "ville": "Guichainville", "departement": "27"}
    idt["contact_AO"] = {"nom": "", "fonction": "", "email": "",
                          "telephone": "02 32 39 82 01"}
    # Estimations à confirmer (petite SEML départementale EnR récente).
    idt["annee_creation"] = 2021
    idt["effectif_salaries"] = 8
    idt["naf_principal"] = "7112B"  # ingénierie, études techniques

    # --- Capacité globale (matching financier) — ESTIMATIONS à confirmer ---
    p["capacite_globale"] = {
        "ca_annuel_n_moins_1": 1800000,
        "ca_annuel_n_moins_2": 1300000,
        "ca_annuel_n_moins_3": 800000,
        "fonds_propres": 1500000,        # SEML capitalisée par actionnaires publics
        "effectif_total_etp": 8,
        "capacite_engagement_simultane": 2500000,
        "seuil_minimum_marche_eur": 15000,
    }
    p["economie"] = {
        "marge_brute_cible_pct": 15,
        "taux_journalier_moyen_eur": 600,
        "frais_de_structure_pct": 22,
        "agressivite_commerciale": "neutre",
    }

    p["_description"] = (
        "TEE27 (nom commercial) — SEML départementale de la transition énergétique de l'Eure (27). "
        "AMO/BE EnR + ingénierie énergétique bâtiment + conseil stratégique aux collectivités. "
        "Zone STRICTE : Eure (27), acteur de proximité. "
        "Adresse postale : CS 30289 27002 Evreux Cedex. "
        "LinkedIn : linkedin.com/company/seml-transition-euroise-energies. "
        "Actionnariat mixte public-privé majoritairement public (caractère public). "
        "AMBIVALENCE à clarifier : peut être répondant (AMO/développement) ET émetteur d'AO (acheteur public). "
        "À COMPLÉTER : SIREN/SIRET, effectif, CA, certifications (OPQIBI/AFAQ ?), références projets. "
        "EXCLUSIONS : fourniture pure électricité/gaz, hors Eure et limitrophes, "
        "grands projets nationaux EnR (offshore), marchés purement BTP sans dimension énergétique."
    )

    # --- Priorités presets (pondération matching) : enr principal, ingénierie 2nd, conseil 3e ---
    p["presets_priorites"] = {"energie_renouvelable": 1, "ingenierie": 2, "conseil": 3}

    # --- Domaines précis couverts (matching FIN) : EnR + énergie + MOE ÉNERGÉTIQUE +
    #     conseil stratégique. PAS moe_architecte_urbanisme ni formation → filtre les
    #     faux positifs (MOE bâtiment générique, formation softskills…). ---
    p["domaines_couverts"] = [
        "energie_pv_solaire", "energie_eolien", "energie_biomasse_methanisation",
        "energie_geothermie", "energie_hydroelectrique", "energie_stockage_reseau",
        "energie_amo_developpement", "energie_amo_etudes", "energie_renovation_thermique",
        "moe_energetique_batiment", "ingenierie_fluides_climatique",
        "conseil_transition_energetique",
    ]

    # --- Zones : Eure + Normandie + Pays de la Loire (élargies par l'utilisateur) ---
    p["zones_intervention"] = ["14", "27", "50", "61", "76", "44", "49", "53", "72", "85"]
    p["zones_strict"] = True

    # --- Mots-clés catalogue (matching thématique) — variantes pour matcher davantage d'objets ---
    p["mots_cles_catalogue"] = [
        "photovoltaïque", "panneaux solaires", "solaire", "centrale photovoltaïque",
        "ombrière", "autoconsommation", "éolien", "méthanisation", "biomasse",
        "bois énergie", "chaufferie biomasse", "réseau de chaleur", "géothermie",
        "pompe à chaleur", "stockage énergie", "amo", "assistance maîtrise d'ouvrage",
        "maîtrise d'ouvrage", "énergies renouvelables", "enr", "transition énergétique",
        "cee", "certificat économie énergie", "étude de faisabilité", "audit énergétique",
        "schéma directeur énergie", "rénovation énergétique", "rénovation thermique",
        "performance énergétique", "friche", "efficacité énergétique", "sobriété énergétique",
    ]

    # --- Sectoriel : énergies renouvelables (preset principal) ---
    enr = p["profils_sectoriels"]["energie_renouvelable"]
    enr["id"] = "energie_renouvelable"
    enr["identite"] = {
        "nom": "TEE27", "siren": "", "forme_juridique": "SEML",
        "annee_creation": 2021, "effectif_total": 8,
        "siege_ville": "Guichainville", "siege_code_postal": "27930",
        "site_web": "https://tee27.fr",
    }
    enr["capacite"] = {
        "mwc_installes_cumules": None, "mwc_installes_par_an": None,
        "sites_en_maintenance": None, "ca_annuel_eur": 1800000,
    }
    enr["technologies_maitrisees"] = ["photovoltaique", "eolien", "methanisation", "stockage_energie"]
    enr["types_prestations"] = [
        "developpement_projets_enr", "etudes_faisabilite_enr", "identification_potentiel_enr_friches",
        "structuration_juridique_enr", "concertation_acceptabilite_enr", "amo_projets_energetiques",
        "accompagnement_cee", "animation_territoriale", "ateliers_pedagogiques",
    ]
    enr["segments_clients"] = ["collectivites_locales", "epci", "conseil_departemental_27",
                                "bailleurs_sociaux", "patrimoine_public", "partenaires_prives_enr"]
    enr["zones_intervention"] = ["27"]
    enr["mots_cles_catalogue"] = list(p["mots_cles_catalogue"])

    # --- Sectoriel : ingénierie (AMO bâtiment énergétique) ---
    ing = p["profils_sectoriels"]["ingenierie"]
    ing["typologies_couvertes"] = ["amo_batiment_energetique", "amo_projet_enr"]
    ing["competences_specialisees"] = ["amo_energie", "etudes_faisabilite_enr", "audit_energetique",
                                        "conseil_cee", "structuration_juridique_projet"]
    ing["types_clients_publics"] = ["collectivites", "epci", "conseil_departemental", "bailleurs_sociaux"]

    # --- Sectoriel : conseil (stratégique collectivités) — schéma libre ---
    p["profils_sectoriels"]["conseil"] = {
        "types_prestations": ["conseil_strategique_collectivites", "transition_energetique_territoriale",
                               "animation_territoriale", "sensibilisation_transition"],
        "segments_clients": ["collectivites_locales", "epci", "conseil_departemental_27"],
    }
    return p


def main():
    p = construire_profil()
    rap = organisme.valider_profil(p)
    print("valide:", rap["valide"])
    if rap["erreurs"]:
        print("erreurs:", rap["erreurs"])
        sys.exit(1)
    if rap["warnings"]:
        print("warnings:", rap["warnings"])
    res = organisme.enregistrer_profil_bibliotheque("tee27", p)
    print("enregistrement bibliothèque:", res)
    if res.get("ok"):
        act = organisme.activer_profil("tee27", "bibliotheque")
        print("activation:", act)


if __name__ == "__main__":
    main()
