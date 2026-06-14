# Audit — mapping domaine → presets (avant Chantier 1)

_Lecture seule. `preset.py` NON modifié. Le mapping vient des `presets/<code>/_preset.json` (`veille.domaines_acceptes/optionnels`)._

## 1. Configuration actuelle des presets

| Preset | domaines_acceptes | domaines_optionnels |
|---|---|---|
| btp | btp_gros_oeuvre, btp_second_oeuvre, btp_voirie_reseaux, btp_renovation_rehabilitation, btp_demolition | ingenierie_structure_genie_civil, moe_architecte_urbanisme, energie_renovation_thermique |
| conseil | conseil_strategie_organisation, conseil_juridique, conseil_financier_audit, conseil_communication, conseil_si_data | formation_management_softskills, moe_architecte_urbanisme |
| energie_renouvelable | energie_pv_solaire, energie_eolien, energie_biomasse_methanisation, energie_geothermie, energie_hydroelectrique, energie_stockage_reseau, energie_amo_etudes, energie_renovation_thermique | ingenierie_environnementale, ingenierie_fluides_climatique |
| formation | formation_pro_continue, formation_management_softskills, formation_metiers_techniques, formation_linguistique, formation_securite_obligatoire, insertion_professionnelle, bilan_competences_vae | insertion_sociale_mediation, prestations_speciales_titres_cheques |
| ingenierie | ingenierie_structure_genie_civil, ingenierie_fluides_climatique, ingenierie_environnementale, moe_architecte_urbanisme, topographie_geometre | energie_amo_etudes, btp_renovation_rehabilitation |
| it | it_developpement_web_app, it_infrastructure_cloud, it_cybersecurite, it_progiciels_erp, it_maintenance_support | conseil_si_data |

Taxonomie : **56 codes** définis. Codes réellement présents en base : **51** (sur 449 occurrences, 422 marchés classés).

## 2. Reverse mapping : combien de presets par code domaine ?

Trié par nb de presets décroissant, puis par nb de marchés.

| Code domaine | # presets | Presets déclenchés | Marchés | Verdict |
|---|---|---|---|---|
| moe_architecte_urbanisme | 3 | ingenierie, btp, conseil | 26 | 🔴 trop large |
| btp_renovation_rehabilitation | 2 | btp, ingenierie | 33 | 🟡 acceptable |
| ingenierie_structure_genie_civil | 2 | ingenierie, btp | 13 | 🟡 acceptable |
| ingenierie_environnementale | 2 | ingenierie, energie_renouvelable | 13 | 🟡 acceptable |
| formation_management_softskills | 2 | formation, conseil | 5 | 🟡 acceptable |
| ingenierie_fluides_climatique | 2 | ingenierie, energie_renouvelable | 4 | 🟡 acceptable |
| conseil_si_data | 2 | conseil, it | 3 | 🟡 acceptable |
| energie_renovation_thermique | 2 | energie_renouvelable, btp | 2 | 🟡 acceptable |
| energie_amo_etudes | 2 | energie_renouvelable, ingenierie | 1 | 🟡 acceptable |
| btp_voirie_reseaux | 1 | btp | 50 | ✅ propre |
| btp_second_oeuvre | 1 | btp | 33 | ✅ propre |
| btp_gros_oeuvre | 1 | btp | 19 | ✅ propre |
| conseil_strategie_organisation | 1 | conseil | 16 | ✅ propre |
| btp_demolition | 1 | btp | 12 | ✅ propre |
| it_infrastructure_cloud | 1 | it | 8 | ✅ propre |
| conseil_communication | 1 | conseil | 7 | ✅ propre |
| formation_pro_continue | 1 | formation | 5 | ✅ propre |
| it_progiciels_erp | 1 | it | 4 | ✅ propre |
| energie_pv_solaire | 1 | energie_renouvelable | 4 | ✅ propre |
| formation_securite_obligatoire | 1 | formation | 4 | ✅ propre |
| it_maintenance_support | 1 | it | 4 | ✅ propre |
| insertion_professionnelle | 1 | formation | 3 | ✅ propre |
| insertion_sociale_mediation | 1 | formation | 3 | ✅ propre |
| topographie_geometre | 1 | ingenierie | 3 | ✅ propre |
| prestations_speciales_titres_cheques | 1 | formation | 2 | ✅ propre |
| conseil_financier_audit | 1 | conseil | 2 | ✅ propre |
| energie_geothermie | 1 | energie_renouvelable | 2 | ✅ propre |
| conseil_juridique | 1 | conseil | 2 | ✅ propre |
| energie_biomasse_methanisation | 1 | energie_renouvelable | 2 | ✅ propre |
| energie_stockage_reseau | 1 | energie_renouvelable | 1 | ✅ propre |
| it_developpement_web_app | 1 | it | 1 | ✅ propre |
| formation_metiers_techniques | 1 | formation | 1 | ✅ propre |
| transport_logistique_vehicules | 0 | — | 18 | hors-périmètre |
| evenementiel_culture | 0 | — | 17 | hors-périmètre |
| services_dechets_proprete | 0 | — | 16 | hors-périmètre |
| entretien_proprete_locaux | 0 | — | 15 | hors-périmètre |
| fourniture_materiel | 0 | — | 15 | hors-périmètre |
| assurance | 0 | — | 14 | hors-périmètre |
| amenagement_paysager_creation | 0 | — | 10 | hors-périmètre |
| restauration_collective_prestations | 0 | — | 9 | hors-périmètre |
| amenagement_paysager_entretien | 0 | — | 9 | hors-périmètre |
| securite_gardiennage | 0 | — | 9 | hors-périmètre |
| services_environnement_analyses | 0 | — | 8 | hors-périmètre |
| autre | 0 | — | 7 | hors-périmètre |
| services_sante_medical | 0 | — | 5 | hors-périmètre |
| fourniture_consommables | 0 | — | 2 | hors-périmètre |
| restauration_fournitures_alimentaires | 0 | — | 2 | hors-périmètre |
| gestion_archives_documentaire | 0 | — | 2 | hors-périmètre |
| traduction_interpretariat | 0 | — | 1 | hors-périmètre |
| energia_amo_etudes | 0 | — | 1 | hors-périmètre |
| petite_enfance_periscolaire | 0 | — | 1 | hors-périmètre |

Répartition : **19** codes hors-périmètre, **23** propres (1 preset), **8** acceptables (2), **1** trop larges (3+).

## 3. Codes problématiques (3+ presets) & proposition

### `moe_architecte_urbanisme` → ['ingenierie', 'btp', 'conseil'] (26 marchés)

- Apparaît dans : `btp`.optionnels, `conseil`.optionnels, `ingenierie`.acceptés
- Label taxonomie : —

**Proposition de resserrement :**

- Retirer `moe_architecte_urbanisme` de `conseil.domaines_optionnels`.

_Justification métier_ : la maîtrise d'œuvre architecture/urbanisme (`moe_architecte_urbanisme`) relève du cœur **ingénierie** (acceptés) et intéresse légitimement le **BTP** en secondaire (un marché de MOE bâtiment peut concerner une entreprise de travaux). En revanche elle n'a pas de rapport avec le **conseil** (stratégie/juridique/finance) : ce rattachement optionnel est un faux positif. Resserrer 3 → 2 presets (🟡 acceptable).

## 4. Impact estimé du resserrement

- Marchés dont le **preset principal** (1ᵉʳ) change : **0**
- Marchés dont l'**ensemble de presets** change : **26** (sur 422 classés)

> Le principal ne bouge pas : `moe_architecte_urbanisme` reste *accepté* par `ingenierie` (donc toujours 1ᵉʳ). Le resserrement retire seulement le rattachement secondaire `conseil` — un marché ne perd `conseil` que s'il n'a AUCUN autre code conseil.

| Marché | Avant | Après |
|---|---|---|
| BOAMP-26-57084 | ingenierie, btp, conseil | ingenierie, btp |
| BOAMP-26-56335 | ingenierie, btp, conseil | ingenierie, btp |
| BOAMP-26-57176 | ingenierie, btp, conseil | ingenierie, btp |
| BOAMP-26-56496 | ingenierie, btp, conseil | ingenierie, btp |
| BOAMP-26-57073 | ingenierie, btp, conseil | ingenierie, btp |
| BOAMP-26-56588 | ingenierie, btp, conseil | ingenierie, btp |
| BOAMP-26-57080 | ingenierie, btp, conseil | ingenierie, btp |
| BOAMP-26-57223 | ingenierie, btp, conseil | ingenierie, btp |
| BOAMP-26-57132 | ingenierie, btp, conseil | ingenierie, btp |
| BOAMP-26-56774 | ingenierie, btp, conseil | ingenierie, btp |

## 5. Anomalies de données repérées (hors mapping)

Codes classifiés ABSENTS de la taxonomie (→ 0 preset, à corriger côté classification, PAS côté mapping) :
- `energia_amo_etudes` (1 marché(s))
