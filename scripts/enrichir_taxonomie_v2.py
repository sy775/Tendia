"""
scripts/enrichir_taxonomie_v2.py — enrichit la taxonomie de domaines (granularité fine)
et câble les nouveaux codes dans les presets (veille.domaines_acceptes/optionnels).

Ajoute 7 codes (MOE énergétique/urbanisme/infra, ingénierie eau/écologie, AMO dev ENR,
réseaux BTP) et recentre 4 descriptions de fourre-tout. Idempotent.

Usage : python scripts/enrichir_taxonomie_v2.py
"""
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RACINE = Path(__file__).resolve().parent.parent
TAXO = RACINE / "presets" / "_taxonomie_domaines.json"

# --- Nouveaux domaines (libellé, description, exemples) ---
NOUVEAUX = {
    "moe_energetique_batiment": {
        "libelle": "MOE / conception énergétique du bâtiment",
        "description": "Maîtrise d'œuvre et conception de rénovation énergétique, bâtiment performant ou bas-carbone, audit énergétique opérationnel, CPE (contrat de performance énergétique), AMO énergie sur bâtiment.",
        "exemples_oui": [
            "Maîtrise d'œuvre pour la rénovation énergétique d'un groupe scolaire",
            "Conception bas-carbone d'un bâtiment public",
            "Mission d'audit énergétique et de maîtrise d'œuvre thermique",
        ],
        "exemples_non": [
            "Travaux de rénovation thermique (→ energie_renovation_thermique)",
            "MOE architecturale sans dimension énergétique (→ moe_architecte_urbanisme)",
        ],
    },
    "moe_urbanisme_amenagement": {
        "libelle": "Urbanisme et aménagement",
        "description": "Urbanisme opérationnel et réglementaire (PLU, SCOT, ZAC), études urbaines, programmation urbaine, conception d'aménagement d'espaces publics (études amont, hors travaux).",
        "exemples_oui": [
            "Élaboration du PLU intercommunal",
            "Étude pré-opérationnelle d'aménagement urbain",
            "Programmation d'un éco-quartier",
        ],
        "exemples_non": [
            "MOE de bâtiment (→ moe_architecte_urbanisme)",
            "Travaux d'aménagement de voirie (→ btp_voirie_reseaux)",
        ],
    },
    "moe_infrastructure_vrd": {
        "libelle": "MOE infrastructure et VRD",
        "description": "Maîtrise d'œuvre et études d'infrastructures : voirie, réseaux divers (VRD), ouvrages d'art, aménagements routiers. Conception/études, sans exécution de travaux.",
        "exemples_oui": [
            "Maîtrise d'œuvre pour la requalification d'une voirie communale",
            "MOE d'un ouvrage d'art",
            "Conception d'un réseau d'assainissement",
        ],
        "exemples_non": [
            "Travaux de voirie / réseaux (→ btp_voirie_reseaux ou btp_reseaux_divers)",
            "MOE de bâtiment (→ moe_architecte_urbanisme)",
        ],
    },
    "ingenierie_eau_milieux": {
        "libelle": "Ingénierie eau et milieux",
        "description": "Ingénierie de l'eau (eau potable, assainissement, eaux pluviales, hydraulique) et des milieux aquatiques (rivières, GEMAPI, zones humides) — études et maîtrise d'œuvre.",
        "exemples_oui": [
            "Étude de schéma directeur d'assainissement",
            "Maîtrise d'œuvre d'une station d'épuration",
            "Étude hydraulique et restauration de cours d'eau (GEMAPI)",
        ],
        "exemples_non": [
            "Travaux de réseaux humides (→ btp_reseaux_divers)",
            "Étude d'impact réglementaire globale (→ ingenierie_environnementale)",
        ],
    },
    "ingenierie_ecologie_biodiversite": {
        "libelle": "Écologie et biodiversité",
        "description": "Génie écologique, expertises faune-flore, biodiversité, Natura 2000, mesures ERC (éviter-réduire-compenser), trame verte et bleue.",
        "exemples_oui": [
            "Inventaire faune-flore et dossier Natura 2000",
            "Étude écologique et mesures compensatoires",
            "Diagnostic biodiversité d'un site",
        ],
        "exemples_non": [
            "Étude d'impact globale / ICPE (→ ingenierie_environnementale)",
            "Entretien d'espaces verts (→ amenagement_paysager_entretien)",
        ],
    },
    "energie_amo_developpement": {
        "libelle": "AMO et développement de projets ENR",
        "description": "Assistance à maîtrise d'ouvrage, montage, faisabilité, structuration juridique/financière et développement de projets d'énergies renouvelables (PV, éolien, méthanisation, réseaux de chaleur).",
        "exemples_oui": [
            "AMO pour le développement d'une centrale photovoltaïque",
            "Étude de faisabilité et montage d'un projet de méthanisation",
            "Structuration d'un projet ENR sur friche",
        ],
        "exemples_non": [
            "Études techniques énergie pures (→ energie_amo_etudes)",
            "Travaux d'installation ENR (→ energie_pv_solaire, etc.)",
        ],
    },
    "conseil_transition_energetique": {
        "libelle": "Conseil & stratégie énergétique territoriale",
        "description": "Conseil stratégique aux collectivités sur la transition énergétique : planification (PCAET, schéma directeur énergie/chaleur), stratégie territoriale bas-carbone, animation/sensibilisation, accompagnement de politiques énergie. HORS AMO de projet ENR (→ energie_amo_developpement) et HORS conseil généraliste (→ conseil_strategie_organisation).",
        "exemples_oui": [
            "Élaboration du Plan Climat-Air-Énergie Territorial (PCAET)",
            "Schéma directeur des énergies / réseaux de chaleur d'une collectivité",
            "Conseil en stratégie de transition énergétique territoriale",
        ],
        "exemples_non": [
            "AMO pour développer une centrale PV (→ energie_amo_developpement)",
            "Conseil en organisation sans dimension énergie (→ conseil_strategie_organisation)",
        ],
    },
    "btp_reseaux_divers": {
        "libelle": "Travaux de réseaux (humides et secs)",
        "description": "Travaux de réseaux humides (eau potable, assainissement, pluvial) et secs (électricité, télécom, éclairage public, fibre) : pose et génie civil de réseaux.",
        "exemples_oui": [
            "Travaux d'extension du réseau d'assainissement",
            "Pose de réseaux secs et éclairage public",
            "Renouvellement de canalisations d'eau potable",
        ],
        "exemples_non": [
            "Voirie / chaussées (→ btp_voirie_reseaux)",
            "Études / MOE de réseaux (→ moe_infrastructure_vrd ou ingenierie_eau_milieux)",
        ],
    },
}

# --- Recentrage des descriptions des fourre-tout ---
RECENTRAGES = {
    "moe_architecte_urbanisme": {
        "libelle": "Maîtrise d'œuvre architecturale (bâtiment)",
        "description": "Maîtrise d'œuvre architecturale du bâtiment (de l'esquisse à l'AOR), construction et réhabilitation. HORS urbanisme (→ moe_urbanisme_amenagement) et HORS dimension énergétique dominante (→ moe_energetique_batiment).",
    },
    "ingenierie_environnementale": {
        "description": "Études d'impact environnemental, ICPE, loi sur l'eau réglementaire, sites et sols pollués, bilan carbone. HORS eau/milieux opérationnels (→ ingenierie_eau_milieux) et HORS écologie/biodiversité (→ ingenierie_ecologie_biodiversite).",
    },
    "energie_amo_etudes": {
        "description": "Études techniques énergie (audit technique, instrumentation, dimensionnement, monitoring). HORS AMO/montage/développement de projet (→ energie_amo_developpement).",
    },
    "btp_voirie_reseaux": {
        "description": "Travaux de voirie et chaussées (terrassement VRD, enrobés, trottoirs, aménagements de surface). Les réseaux humides/secs vont dans btp_reseaux_divers.",
    },
}

# --- Câblage presets : code -> {preset: 'accepte'|'optionnel'} ---
CABLAGE = {
    "moe_energetique_batiment": {"ingenierie": "accepte", "energie_renouvelable": "accepte"},
    "moe_urbanisme_amenagement": {"ingenierie": "accepte"},
    "moe_infrastructure_vrd": {"ingenierie": "accepte", "btp": "optionnel"},
    "ingenierie_eau_milieux": {"ingenierie": "accepte", "btp": "optionnel"},
    "ingenierie_ecologie_biodiversite": {"ingenierie": "accepte"},
    "energie_amo_developpement": {"energie_renouvelable": "accepte", "ingenierie": "optionnel"},
    "btp_reseaux_divers": {"btp": "accepte", "ingenierie": "optionnel"},
    "conseil_transition_energetique": {"conseil": "accepte", "energie_renouvelable": "accepte"},
}


def main():
    tax = json.load(open(TAXO, encoding="utf-8"))
    dom = tax.setdefault("domaines", {})

    # 1) Ajout des nouveaux codes (idempotent)
    ajout = 0
    for code, spec in NOUVEAUX.items():
        if code not in dom:
            dom[code] = spec
            ajout += 1
    # 2) Recentrage des fourre-tout
    for code, patch in RECENTRAGES.items():
        if code in dom:
            dom[code].update(patch)
    json.dump(tax, open(TAXO, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"Taxonomie : +{ajout} codes (total {len(dom)}), {len(RECENTRAGES)} recentrés.")

    # 3) Câblage des presets
    par_preset = {}
    for code, mp in CABLAGE.items():
        for preset, niveau in mp.items():
            par_preset.setdefault(preset, []).append((code, niveau))
    for preset, items in par_preset.items():
        fp = RACINE / "presets" / preset / "_preset.json"
        d = json.load(open(fp, encoding="utf-8"))
        v = d.setdefault("veille", {})
        acc = v.setdefault("domaines_acceptes", [])
        opt = v.setdefault("domaines_optionnels", [])
        for code, niveau in items:
            cible = acc if niveau == "accepte" else opt
            if code not in acc and code not in opt:
                cible.append(code)
        json.dump(d, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"  {preset}: acceptes={len(acc)} optionnels={len(opt)}")


if __name__ == "__main__":
    main()
