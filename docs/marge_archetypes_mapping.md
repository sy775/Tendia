# Marge — archétypes & mapping des 64 codes taxonomie

But : fiabiliser la marge sans table fine ingérable. La marge est portée par un
**archétype** (la *nature* de la prestation), dérivé **déterministiquement** du code
fin `lots[].domaine`. L'IA ne choisit PAS l'archétype (imposé par la classif) ; elle
ne fait que **placer le taux dans la bande** + justifier en 1 ligne.

Routage : **distinct(archétype des lots) ≥ 2 → marge par lot ; sinon → marge globale.**

## Archétypes & bandes (marge NETTE indicative — À SOURCER)

| Code | Archétype | Bande indicative (à sourcer) |
|---|---|---|
| **A1** | Travaux / installation | 6-16 % |
| **A2** | Ingénierie & études techniques | 25-45 % |
| **A3** | Conseil & assistance intellectuelle | 30-50 % |
| **A4** | Formation & accompagnement humain | 15-35 % |
| **A5** | Services techniques spécialisés | 18-35 % |
| **A6** | Services opérationnels (main-d'œuvre) | 4-12 % |
| **A7** | Fournitures / négoce | 3-10 % |
| **A8** | Autre / variable (justif obligatoire) | 10-30 % |

## Mapping déterministe (64 codes)

### A1 — Travaux / installation
| Code | Libellé |
|---|---|
| amenagement_paysager_creation | Aménagement paysager — création |
| btp_demolition | Démolition et désamiantage |
| btp_gros_oeuvre | BTP gros œuvre et construction neuve |
| btp_renovation_rehabilitation | Rénovation et réhabilitation existant |
| btp_reseaux_divers | Travaux de réseaux (humides et secs) |
| btp_second_oeuvre | BTP second œuvre |
| btp_voirie_reseaux | VRD - voirie et réseaux divers |
| energie_biomasse_methanisation | Biomasse, méthanisation, biogaz |
| energie_eolien | Éolien |
| energie_geothermie | Géothermie et pompes à chaleur |
| energie_hydroelectrique | Hydroélectricité |
| energie_pv_solaire | Photovoltaïque et solaire |
| energie_renovation_thermique | Rénovation énergétique de bâtiments |
| energie_stockage_reseau | Stockage énergie et smart grid |

### A2 — Ingénierie & études techniques
| Code | Libellé |
|---|---|
| energie_amo_developpement | AMO et développement de projets ENR |
| energie_amo_etudes | AMO et études énergie |
| ingenierie_eau_milieux | Ingénierie eau et milieux |
| ingenierie_ecologie_biodiversite | Écologie et biodiversité |
| ingenierie_environnementale | Ingénierie environnementale |
| ingenierie_fluides_climatique | Ingénierie fluides et climatique |
| ingenierie_structure_genie_civil | Ingénierie structure et génie civil |
| moe_architecte_urbanisme | Maîtrise d'œuvre architecturale (bâtiment) |
| moe_energetique_batiment | MOE / conception énergétique du bâtiment |
| moe_infrastructure_vrd | MOE infrastructure et VRD |
| moe_urbanisme_amenagement | Urbanisme et aménagement |
| topographie_geometre | Topographie, géomètre, foncier |

### A3 — Conseil & assistance intellectuelle
| Code | Libellé |
|---|---|
| conseil_communication | Conseil en communication et marketing |
| conseil_financier_audit | Conseil financier et audit |
| conseil_juridique | Conseil et accompagnement juridique |
| conseil_si_data | Conseil SI, schéma directeur, gouvernance data |
| conseil_strategie_organisation | Conseil stratégie et organisation |
| conseil_transition_energetique | Conseil & stratégie énergétique territoriale |

### A4 — Formation & accompagnement humain
| Code | Libellé |
|---|---|
| bilan_competences_vae | Bilan de compétences, VAE, orientation |
| formation_linguistique | Formation linguistique et savoirs de base |
| formation_management_softskills | Formations management et soft skills |
| formation_metiers_techniques | Formations métiers techniques |
| formation_pro_continue | Formation professionnelle continue |
| formation_securite_obligatoire | Formations sécurité et habilitations obligatoires |
| insertion_professionnelle | Insertion et accompagnement professionnel |
| insertion_sociale_mediation | Insertion sociale et médiation |

### A5 — Services techniques spécialisés
| Code | Libellé |
|---|---|
| it_cybersecurite | Cybersécurité |
| it_developpement_web_app | Développement web et applicatif |
| it_infrastructure_cloud | Infrastructure IT, cloud, hébergement |
| it_maintenance_support | Maintenance IT et support |
| it_progiciels_erp | Intégration progiciels et ERP |
| services_environnement_analyses | Analyses environnementales et contrôles laboratoire |
| services_sante_medical | Services médicaux et biologie humaine |

### A6 — Services opérationnels (main-d'œuvre)
| Code | Libellé |
|---|---|
| amenagement_paysager_entretien | Entretien espaces verts et jardinage |
| entretien_proprete_locaux | Nettoyage et propreté de locaux |
| petite_enfance_periscolaire | Petite enfance, périscolaire et extrascolaire |
| restauration_collective_prestations | Restauration collective — prestations services |
| securite_gardiennage | Sécurité et gardiennage |
| services_dechets_proprete | Déchets, propreté urbaine, traitement |
| transport_logistique_vehicules | Transport, logistique, location véhicules |

### A7 — Fournitures / négoce
| Code | Libellé |
|---|---|
| fourniture_consommables | Fourniture de consommables |
| fourniture_materiel | Fourniture de matériel et équipement |
| prestations_speciales_titres_cheques | Titres, chèques cadeau, titres restaurant |
| restauration_fournitures_alimentaires | Fournitures alimentaires et denrées |

### A8 — Autre / variable (justif obligatoire)
| Code | Libellé |
|---|---|
| assurance | Assurances |
| autre | Autre / hors taxonomie |
| evenementiel_culture | Événementiel et culture |
| gestion_archives_documentaire | Gestion documentaire et archives |
| traduction_interpretariat | Traduction et interprétariat |
| voyage_hebergement_pro | Voyages d'affaires, agence de voyage, hébergement |

## Points de jugement à confirmer
- `petite_enfance_periscolaire` → A6 (service main-d'œuvre, marge fine) plutôt qu'A4 — animation/garde ≠ formation.
- `insertion_*` → A4, mais marges souvent fines (SIAE/assos) ; la borne basse de A4 doit en tenir compte.
- `conseil_communication` → A3 (vs A8) ; communication/marketing = conseil à VA correcte.
- `transport_logistique_vehicules` → A6 (la part « location véhicules » tirerait vers A7, mais dominante = service).
- `gestion_archives_documentaire` → A8 (mixte numérisation technique + manutention).
