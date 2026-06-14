# Baseline qualité des briefs — avant Chantier 1

_Lecture seule. 102 briefs analysés (94 complet, 8 light)._

> Référence figée pour mesurer l'amélioration post-optimisation des prompts.

## 1. Répartition des briefs par preset (classification du marché)

| Preset | Nb briefs |
|---|---|
| btp | 19 |
| ingenierie | 15 |
| it | 4 |
| conseil | 7 |
| formation | 5 |
| hors-périmètre | 52 |
| **Total** | **102** |

## 2. Remplissage des champs critiques (transverses), par preset

| Preset | n | synthese_marche | bareme.valeur_technique_pct | montant.valeur_estimee_euros | refs.experience_minimale_annees | refs.certifications_obligatoires | points_differenciants_attendus | alertes_candidat |
|---|---|---|---|---|---|---|---|---|
| btp | 19 | 100% (19) | 100% (19) | 15% (3) | 57% (11) | 57% (11) | 100% (19) | 100% (19) |
| ingenierie | 15 | 100% (15) | 100% (15) | 0% (0) | 66% (10) | 40% (6) | 100% (15) | 100% (15) |
| it | 4 | 100% (4) | 75% (3) | 50% (2) | 50% (2) | 0% (0) | 100% (4) | 100% (4) |
| conseil | 7 | 100% (7) | 85% (6) | 28% (2) | 14% (1) | 28% (2) | 100% (7) | 100% (7) |
| formation | 5 | 100% (5) | 100% (5) | 40% (2) | 60% (3) | 60% (3) | 100% (5) | 100% (5) |
| hors-périmètre | 52 | 100% (52) | 75% (39) | 34% (18) | 34% (18) | 40% (21) | 84% (44) | 100% (52) |

## 3. Remplissage des champs SECTORIELS attendus (preset identifié)

_Mesuré uniquement sur les briefs dont le preset attend ce bloc._

| Preset | n | Champ sectoriel | Taux rempli |
|---|---|---|---|
| btp | 19 | qualifications_requises.qualibat | 31% (6/19) |
| ingenierie | 15 | qualifications_moe.opqibi | 0% (0/15) |
| it | 4 | qualifications_si.iso_27001 | 0% (0/4) |
| it | 4 | caracteristiques_si.typologie_systeme | 0% (0/4) |
| conseil | 7 | _(aucun bloc sectoriel dédié)_ | — |
| formation | 5 | qualifications_formation.qualiopi | 0% (0/5) |
| formation | 5 | publics_cibles | 100% (5/5) |
| enr | 0 | qualifications_enr.qualipv | 0% (0/0) |

## 4. Blocs sectoriels HORS-SUJET

_Bloc rempli alors qu'il n'appartient pas au preset du marché (symptôme d'un schéma LLM non routé vers le bon secteur)._

| Preset du brief | n | Briefs avec ≥1 bloc HS | Blocs HS les plus fréquents |
|---|---|---|---|
| btp | 19 | 2 | caracteristiques_mission_moe×2, qualifications_moe×1 |
| ingenierie | 15 | 15 | caracteristiques_techniques_chantier×15, volumes_techniques×9, modalites_execution_chantier×9 |
| it | 4 | 4 | volumes_techniques×4, modalites_execution_chantier×4, caracteristiques_techniques_chantier×1 |
| conseil | 7 | 5 | volumes_techniques×5, modalites_execution_chantier×5, caracteristiques_techniques_chantier×2 |
| formation | 5 | 4 | volumes_techniques×4, modalites_execution_chantier×4, caracteristiques_techniques_chantier×3 |
| hors-périmètre | 52 | 42 | modalites_execution_chantier×39, volumes_techniques×37, caracteristiques_techniques_chantier×36 |

**72 briefs** présentent au moins un bloc sectoriel hors-sujet.

## 5. Incohérences titre ↔ synthèse

_Synthèse ne partageant aucun mot signifiant (>3 car.) avec le titre du marché._

- Briefs testés (titre + synthèse présents) : **94**
- Incohérents (0 mot commun) : **8** (8%)

| Marché | Titre (extrait) | Synthèse (extrait) |
|---|---|---|
| BOAMP-26-56061 | Entretien des grilles et avaloirs, réseau d'eaux pluviales,  | Accord-cadre mono-attributaire portant sur des prestations d |
| BOAMP-26-56134 | Mission de maîtrise d'oeuvre - Travaux sur le clos et couver | L'ENS Paris-Saclay lance un accord-cadre à bons de commande  |
| BOAMP-26-56170 | DTEM2026-134AO_MaintGpeElectro | Le CHU d'Angers, en tant qu'établissement support du GHT 49  |
| BOAMP-26-56482 | RESEAU D'EXPERT 3.0 | Martinique Développement lance un accord-cadre multi-attribu |
| BOAMP-26-56510 | Marché de prestations d'agence de voyage pour les élus et ag | Ce DCE concerne la fourniture, l'installation et la mise en  |
| BOAMP-26-56558 | Prise en charge et traitement des déchets type « résidus de  | Ce marché concerne la fourniture et la livraison de denrées  |
| BOAMP-26-56575 | Nettoyage du groupe scolaire de Mezzana 
2026-2029 - Sarrola | Ce DCE concerne un Système d'Acquisition Dynamique (SAD) pou |
| BOAMP-26-56732 | Suivi hydrométrique des bassins versants Aude, Berre et Rieu | Le CHU Dijon Bourgogne (établissement support du GHT 21-52)  |

## 6. Coût LLM & tokens, par preset

| Preset | n (avec coût) | Coût moyen € | Coût médian € | Tokens_in moyen | Tokens_in médian |
|---|---|---|---|---|---|
| btp | 19 | 0.1770 | 0.1733 | 26806 | 24879 |
| ingenierie | 15 | 0.1654 | 0.1637 | 25167 | 24191 |
| it | 4 | 0.1489 | 0.1507 | 24060 | 24611 |
| conseil | 7 | 0.1547 | 0.1636 | 25348 | 23421 |
| formation | 5 | 0.1757 | 0.1750 | 26591 | 27505 |
| hors-périmètre | 52 | 0.1458 | 0.1555 | 22121 | 24224 |

**Coût total briefs** : 15.98 € sur 102 briefs (moyen 0.1567 €, médian 0.1637 €).

- Quartile BAS tokens_in (~13494 tok) → coût moyen 0.0987 €
- Quartile HAUT tokens_in (~33287 tok) → coût moyen 0.1975 €
  (les gros DCE produisent bien des briefs plus chers)

## 7. Datation des briefs & schéma `_meta`

> Les 2 pipelines n'utilisent PAS les mêmes clés `_meta` : brief **light** → `date_generation` + `tokens_in/out` ; brief **complet** → `extraction_le` + `tokens_input/output` (+ `pdfs_traites`). À harmoniser (impacte tout outil qui lit `_meta`).

- Sans `date_generation` (champ light) : **94** (dont la plupart ont `extraction_le`)
- Sans AUCUNE date (`date_generation` ni `extraction_le`) : **0**
- Sans tokens_in exploitables : **0**

Modèles LLM utilisés : `claude-sonnet-4-6`×102
