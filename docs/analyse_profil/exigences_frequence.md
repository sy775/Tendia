# Fréquence des pièces et exigences demandées aux candidats

Produit par `scripts/audit/analyse_exigences.py` le 2026-11-11 à 14:07 (lecture seule, sans LLM, sans réseau). Relancer le script régénère ce fichier et les CSV voisins.

## Base de mesure

| Mesure | Valeur |
|---|---|
| Briefs courants dans `briefs_extraits` (sauvegardes `.bak_*` et `.grille_brute` exclues) | 253 |
| Briefs portant au moins une exigence (base des pourcentages) | 236 |
| dont BTP (preset `btp` ou domaine `btp_*`) | 80 |
| dont autres secteurs | 156 |
| Mois de génération des briefs | 2026-06 : 229, 2026-11 : 14, sans date : 10 |
| Libellés libres analysés (sources P, C, A, Q) | 4099 |
| Libellés rangés dans au moins un type | 4012 (97.9 %) |
| Libellés non reconnus | 87 (86 libellés distincts) |
| Marchés actifs en base / dont classés BTP | 1757 / 509 |
| Marchés BTP actifs disposant d'un brief | 9 |

Sources : P = `dossier_candidature.pieces_a_fournir`, C = `references_exigees.certifications_obligatoires`, A = `references_exigees.autres_exigences`, Q = listes des blocs `qualifications_*`, S = champs structurés (codes Qualibat, booléens, expérience), exclus du taux de typage.

### Limites à garder en tête

- Les libellés sont ceux rédigés par le LLM d'extraction, pas le texte du règlement de consultation. Deux briefs disent la même chose avec des mots différents ; le dictionnaire de motifs absorbe ces variantes.
- La plupart des briefs datent de juin 2026 (lecture partielle du DCE : pièces de premier niveau, troncature à 400 000 caractères). Une pièce absente du brief n'est pas forcément absente du DCE : les pourcentages sont des planchers.
- Un libellé peut porter plusieurs types (« DC2 avec Kbis de moins de 3 mois et pouvoirs » compte pour DC2, Kbis et pouvoir). Un mémoire technique qui énumère son contenu ne compte que pour le mémoire.
- Le DUME et le couple DC1 + DC2 sont interchangeables : un marché qui cite « DC1 ou DUME » compte dans les deux lignes.
- La phase vient du champ `phase` des pièces (source P) ; les exigences des sources C, A, Q n'ont pas de phase.
- La colonne « marchés BTP actifs (estimation) » applique le pourcentage BTP aux 509 marchés BTP actifs du jour ; seuls 9 d'entre eux ont un brief, le chiffre exact n'est donc pas mesurable aujourd'hui.

## Fréquence par type

Pourcentages = part des marchés de la colonne qui portent au moins une exigence du type. Trié par fréquence BTP.

| Type | Tous (236) | BTP (80) | Autres (156) | Phase (marchés : candidature / offre / non précisée) | Obligatoire (pièces : oui / non) | Validité ou ancienneté exigée | Marchés BTP actifs (estimation) |
|---|---|---|---|---|---|---|---|
| BPU / DPGF / DQE / pièces de prix | 87 % (205) | 91 % (73) | 85 % (132) | 5 / 204 / 21 | 329 / 7 | sans objet | 464 |
| Mémoire technique / cadre de réponse | 89 % (209) | 89 % (71) | 88 % (138) | 9 / 206 / 14 | 274 / 10 | sans objet | 452 |
| Acte d'engagement (AE, ATTRI1) | 83 % (196) | 85 % (68) | 82 % (128) | 2 / 196 / 4 | 247 / 17 | sans objet | 433 |
| DC1 / lettre de candidature | 80 % (189) | 71 % (57) | 85 % (132) | 189 / 0 / 5 | 185 / 18 | sans objet | 363 |
| Références de chantiers / prestations | 76 % (179) | 64 % (51) | 82 % (128) | 154 / 7 / 170 | 174 / 9 | 3 dernières années ou exercices (162) ; 5 dernières années ou exercices (52) ; moins de 3 ans (4) | 324 |
| DC2 / déclaration du candidat | 75 % (177) | 64 % (51) | 81 % (126) | 175 / 1 / 29 | 183 / 17 | sans objet | 324 |
| Attestation d'assurance RC professionnelle | 62 % (146) | 64 % (51) | 61 % (95) | 107 / 12 / 132 | 110 / 12 | en cours de validité (69) ; de l'année en cours (ou au 31 décembre N-1) (4) ; à jour (3) | 324 |
| Chiffre d'affaires, bilans | 70 % (166) | 58 % (46) | 77 % (120) | 144 / 1 / 160 | 148 / 12 | 3 dernières années ou exercices (29) ; 2 dernières années ou exercices (2) | 293 |
| Déclaration sur l'honneur (interdictions de soumissionner) | 58 % (137) | 54 % (43) | 60 % (94) | 132 / 6 / 24 | 151 / 7 | sans objet | 274 |
| DC4 / déclaration de sous-traitance | 47 % (110) | 50 % (40) | 45 % (70) | 33 / 75 / 14 | 11 / 98 | sans objet | 254 |
| Déclaration des effectifs | 54 % (128) | 48 % (38) | 58 % (90) | 115 / 1 / 118 | 113 / 6 | 3 dernières années ou exercices (188) ; 5 dernières années ou exercices (1) ; de l'année en cours (ou au 31 décembre N-1) (1) | 242 |
| Attestation d'assurance décennale | 18 % (42) | 42 % (34) | 5 % (8) | 15 / 6 / 38 | 19 / 2 | en cours de validité (9) ; à jour (1) | 216 |
| Attestation / certificat de visite | 22 % (53) | 39 % (31) | 14 % (22) | 9 / 36 / 34 | 39 / 6 | sans objet | 197 |
| Outillage, matériel, moyens techniques | 41 % (96) | 38 % (30) | 42 % (66) | 82 / 8 / 79 | 89 / 4 | sans objet | 191 |
| Habilitations du personnel (AIPR, électrique, CACES, SST…) | 28 % (66) | 35 % (28) | 24 % (38) | 24 / 4 / 60 | 30 / 0 | en cours de validité (9) ; 5 dernières années ou exercices (2) | 178 |
| Autres labels et certifications nommés | 25 % (59) | 32 % (26) | 21 % (33) | 21 / 3 / 56 | 23 / 4 | en cours de validité (2) | 165 |
| Environnement, déchets (SOGED, SOSED), RSE | 23 % (55) | 32 % (26) | 19 % (29) | 16 / 30 / 26 | 45 / 6 | sans objet | 165 |
| DUME | 34 % (80) | 31 % (25) | 35 % (55) | 80 / 0 / 4 | 100 / 14 | sans objet | 159 |
| Condition d'exécution ou de moyens (délai d'intervention, présence locale, astreinte) | 21 % (50) | 31 % (25) | 16 % (25) | 1 / 8 / 45 | 8 / 3 | sans objet | 159 |
| Attestations de bonne exécution / certificats de capacité | 25 % (60) | 30 % (24) | 23 % (36) | 39 / 0 / 44 | 38 / 1 | 3 dernières années ou exercices (5) ; 5 dernières années ou exercices (3) | 153 |
| Pièces du marché à accepter ou signer (CCAP, CCTP, RC, charte) | 26 % (62) | 25 % (20) | 27 % (42) | 11 / 51 / 7 | 85 / 5 | sans objet | 127 |
| Attestation URSSAF (régularité sociale, vigilance) | 20 % (47) | 25 % (20) | 17 % (27) | 31 / 4 / 21 | 27 / 9 | moins de 6 mois (15) ; à jour (3) ; de l'année en cours (ou au 31 décembre N-1) (2) | 127 |
| Certificats de qualification professionnelle (sans label nommé) | 19 % (44) | 25 % (20) | 15 % (24) | 37 / 0 / 32 | 24 / 14 | en cours de validité (1) | 127 |
| Planning, calendrier, délais | 14 % (33) | 25 % (20) | 8 % (13) | 0 / 25 / 9 | 26 / 0 | sans objet | 127 |
| Pouvoir / délégation de signature | 28 % (66) | 24 % (19) | 30 % (47) | 53 / 12 / 4 | 52 / 14 | non précisée | 121 |
| Attestation de régularité fiscale | 19 % (45) | 24 % (19) | 17 % (26) | 31 / 4 / 22 | 27 / 8 | moins de 6 mois (6) ; de l'année en cours (ou au 31 décembre N-1) (4) ; moins de 3 mois (2) | 121 |
| Fiches techniques, échantillons, documentation produit | 15 % (36) | 24 % (19) | 11 % (17) | 1 / 30 / 11 | 36 / 5 | sans objet | 121 |
| RIB | 19 % (45) | 22 % (18) | 17 % (27) | 7 / 38 / 0 | 40 / 6 | sans objet | 115 |
| Pièces de groupement, capacités d'un tiers | 25 % (60) | 20 % (16) | 28 % (44) | 46 / 17 / 5 | 53 / 20 | sans objet | 102 |
| Jugement de redressement judiciaire | 21 % (50) | 20 % (16) | 22 % (34) | 50 / 0 / 1 | 4 / 44 | sans objet | 102 |
| Obligation d'emploi des travailleurs handicapés | 18 % (42) | 19 % (15) | 17 % (27) | 38 / 0 / 8 | 38 / 0 | sans objet | 95 |
| Qualibat | 7 % (16) | 19 % (15) | 1 % (1) | 10 / 0 / 16 | 9 / 1 | non précisée | 95 |
| Renvoi générique aux capacités (aucune pièce nommée) | 14 % (33) | 18 % (14) | 12 % (19) | 23 / 4 / 10 | 21 / 6 | sans objet | 89 |
| Extrait Kbis / inscription au registre | 20 % (48) | 16 % (13) | 22 % (35) | 39 / 3 / 16 | 41 / 5 | moins de 3 mois (15) ; moins de 6 mois (4) ; à jour (1) | 83 |
| CV, équipe, moyens humains | 19 % (45) | 16 % (13) | 21 % (32) | 16 / 12 / 36 | 29 / 2 | 3 dernières années ou exercices (3) ; moins de 3 ans (1) ; à jour (1) | 83 |
| Engagement d'insertion / clause sociale | 9 % (21) | 16 % (13) | 5 % (8) | 1 / 13 / 10 | 14 / 1 | sans objet | 83 |
| Titres d'études et professionnels, diplômes | 18 % (42) | 15 % (12) | 19 % (30) | 32 / 0 / 29 | 30 / 2 | sans objet | 76 |
| Sécurité et qualité (PPSPS, PAQ, plan de prévention) | 11 % (27) | 15 % (12) | 10 % (15) | 4 / 9 / 21 | 12 / 2 | sans objet | 76 |
| Certification ou habilitation amiante (SS3 / SS4) | 5 % (12) | 15 % (12) | 0 % (0) | 3 / 2 / 12 | 6 / 0 | en cours de validité (2) | 76 |
| Déclaration de banque / garantie financière | 19 % (45) | 12 % (10) | 22 % (35) | 37 / 1 / 37 | 35 / 3 | sans objet | 64 |
| Autorisation d'exercer (licence, agrément, carte professionnelle, ordre) | 28 % (67) | 10 % (8) | 38 % (59) | 35 / 5 / 67 | 45 / 2 | en cours de validité (17) ; à jour (2) ; de l'année en cours (ou au 31 décembre N-1) (2) | 51 |
| RGPD, confidentialité, cybersécurité | 13 % (31) | 10 % (8) | 15 % (23) | 11 / 14 / 11 | 27 / 2 | sans objet | 51 |
| Présentation de l'entreprise / fiche de renseignements | 11 % (27) | 8 % (6) | 13 % (21) | 17 / 10 / 7 | 28 / 2 | sans objet | 38 |
| Pièces de lutte contre le travail dissimulé (D.8222-5) | 6 % (13) | 8 % (6) | 4 % (7) | 4 / 3 / 9 | 6 / 1 | à renouveler tous les 6 mois (3) | 38 |
| Variantes, PSE, options | 4 % (9) | 8 % (6) | 2 % (3) | 0 / 9 / 1 | 6 / 4 | sans objet | 38 |
| Qualifelec | 3 % (6) | 6 % (5) | 1 % (1) | 2 / 0 / 6 | 2 / 0 | non précisée | 32 |
| RGE (Reconnu garant de l'environnement) | 3 % (6) | 6 % (5) | 1 % (1) | 4 / 0 / 6 | 4 / 0 | en cours de validité (2) | 32 |
| Contrôle d'accès au site (liste nominative, pièces d'identité, enquête) | 6 % (15) | 5 % (4) | 7 % (11) | 1 / 2 / 14 | 3 / 0 | sans objet | 25 |
| Liste nominative des travailleurs étrangers (LNTE) | 3 % (7) | 5 % (4) | 2 % (3) | 6 / 0 / 2 | 6 / 0 | non précisée | 25 |
| OPQIBI / OPQTECC / OPQCM (ingénierie, conseil) | 3 % (6) | 5 % (4) | 1 % (2) | 1 / 0 / 6 | 1 / 0 | non précisée | 25 |
| Identification professionnelle FNTP / Canalisateurs | 2 % (5) | 5 % (4) | 1 % (1) | 4 / 0 / 5 | 3 / 1 | non précisée | 25 |
| Attestation de non-soumission aux sanctions (Russie) | 5 % (11) | 4 % (3) | 5 % (8) | 4 / 5 / 3 | 9 / 0 | sans objet | 19 |
| Certification ISO (9001, 14001, 45001…) | 4 % (10) | 2 % (2) | 5 % (8) | 6 / 0 / 10 | 3 / 3 | non précisée | 13 |
| Déclaration d'absence de conflit d'intérêts / indépendance | 4 % (9) | 2 % (2) | 4 % (7) | 5 / 1 / 4 | 6 / 0 | sans objet | 13 |
| Signature électronique, copie de sauvegarde, modalités de dépôt | 2 % (5) | 2 % (2) | 2 % (3) | 1 / 4 / 0 | 4 / 2 | sans objet | 13 |
| Dépôt des attestations sur une plateforme tierce (e-Attestations, Provigis) | 2 % (4) | 2 % (2) | 1 % (2) | 1 / 0 / 3 | 1 / 0 | non précisée | 13 |
| Égalité professionnelle, index, parité | 1 % (3) | 1 % (1) | 1 % (2) | 0 / 3 / 0 | 0 / 3 | sans objet | 6 |

## Détail par type : exemples de libellés

### Candidature : formulaires

| Type | Code | Occurrences | Certifications bloquantes (oui / non) | Exemples de libellés |
|---|---|---|---|---|
| DC1 / lettre de candidature | `dc1` | 208 | 0 / 0 | « Formulaire DC1 (lettre de candidature) ou Document Unique de Marché Européen (DUME) » ; « Lettre de candidature (DC1) » ; « Lettre de candidature DC1 (ou DUME) » |
| DC2 / déclaration du candidat | `dc2` | 229 | 0 / 0 | « Déclaration du candidat DC2 » ; « Formulaire DC2 (déclaration du candidat) ou DUME » ; « Déclaration du candidat DC2 (ou DUME) » |
| Déclaration sur l'honneur (interdictions de soumissionner) | `attestation_honneur` | 183 | 2 / 0 | « Déclaration sur l'honneur pour justifier que le candidat n'entre dans aucun des cas d'interdiction de soumiss… » ; « Déclaration sur l'honneur pour justifier que le candidat n'entre dans aucun cas d'interdiction de soumissionn… » ; « Déclaration sur l'honneur justifiant que le candidat n'entre dans aucun cas d'interdiction de soumissionner (… » |
| DC4 / déclaration de sous-traitance | `dc4` | 124 | 1 / 0 | « DC4 (déclaration de sous-traitance) le cas échéant » ; « Déclarations de sous-traitance (DC4) le cas échéant » ; « Déclaration de sous-traitance le cas échéant » |
| DUME | `dume` | 119 | 0 / 0 | « Formulaire DC1 (lettre de candidature) ou Document Unique de Marché Européen (DUME) » ; « Formulaire DC2 (déclaration du candidat) ou DUME » ; « Lettre de candidature DC1 (ou DUME) » |
| Pièces de groupement, capacités d'un tiers | `groupement` | 80 | 3 / 0 | « DC1 — Lettre de candidature et habilitation du mandataire par ses cotraitants » ; « Lettre de candidature – Désignation du mandataire par ses cotraitants (DC1) » ; « Lettre de candidature DC1 (Habilitation du mandataire par ses cotraitants) » |

### Candidature : situation juridique, fiscale et sociale

| Type | Code | Occurrences | Certifications bloquantes (oui / non) | Exemples de libellés |
|---|---|---|---|---|
| Attestation URSSAF (régularité sociale, vigilance) | `urssaf` | 61 | 1 / 0 | « Attestation URSSAF » ; « Attestation de régularité sociale de moins de 6 mois » ; « Attestations sociales et fiscales URSSAF » |
| Pouvoir / délégation de signature | `pouvoir` | 71 | 0 / 0 | « Documents relatifs aux pouvoirs de la personne habilitée à engager l'entreprise » ; « Délégation de pouvoir (le cas échéant) » ; « Pouvoir de la personne habilitée à engager le candidat » |
| Attestation de régularité fiscale | `fiscale` | 57 | 0 / 0 | « Attestation de régularité fiscale de l'année en cours » ; « Attestations sociales et fiscales URSSAF » ; « Attestation de régularité fiscale de moins de 3 mois (fortement recommandée) » |
| RIB | `rib` | 46 | 0 / 0 | « Relevé d'identité bancaire (RIB) » ; « RIB » ; « Relevé d'Identité Bancaire (RIB) » |
| Jugement de redressement judiciaire | `redressement` | 51 | 0 / 0 | « Copie du ou des jugements prononcés si le candidat est en redressement judiciaire » ; « Copie du ou des jugements prononcés (si redressement judiciaire) » ; « Copie du ou des jugements prononcés en cas de redressement judiciaire » |
| Obligation d'emploi des travailleurs handicapés | `obligation_emploi_th` | 47 | 1 / 0 | « Renseignements sur le respect de l'obligation d'emploi (articles L. 5212-1 à L. 5212-11 du Code du travail) » ; « Renseignements sur le respect de l'obligation d'emploi (articles L.5212-1 à L.5212-11 du Code du travail) » ; « Renseignements sur le respect de l'obligation d'emploi mentionnée aux articles L.5212-1 à L.5212-11 du Code d… » |
| Extrait Kbis / inscription au registre | `kbis` | 63 | 4 / 0 | « Numéro SIREN du candidat » ; « Attestation d'inscription au registre du commerce et des sociétés ou au répertoire des métiers » ; « K-Bis de l'entreprise de moins de 6 mois » |
| Pièces de lutte contre le travail dissimulé (D.8222-5) | `travail_dissimule` | 17 | 0 / 0 | « Déclaration relative à la lutte contre le travail dissimulé » ; « Extrait Kbis (pièces prévues aux articles D.8222-5 ou D.8222-7 et D.8222-8 du code du travail) — au stade de… » ; « Déclaration de conformité sur les motifs d'exclusion (infractions pénales, obligations sociales, travail diss… » |
| Liste nominative des travailleurs étrangers (LNTE) | `lnte` | 8 | 0 / 0 | « Transmission tous les 6 mois des attestations de régularité des cotisations sociales (< 6 mois) et de la list… » ; « Attestation travailleurs étrangers (modèle fourni dans le DCE) » ; « Attestation sur l'honneur concernant les salariés détachés et étrangers » |
| Attestation de non-soumission aux sanctions (Russie) | `sanctions_russie` | 12 | 0 / 0 | « Attestation sur l'honneur relative aux sanctions russes » ; « Attestation sur l'honneur d'absence de lien avec la Russie (Règlement UE 2022/576) » ; « Déclaration sur l'honneur d'absence de participation Russie » |
| Déclaration d'absence de conflit d'intérêts / indépendance | `conflit_interets` | 10 | 0 / 0 | « Attestation d'absence de lien d'intérêt dans le cadre de ce marché public » ; « Déclaration de conflit d'intérêt (formulaire 04d_A3_CCP_conflit_interet.docx) pour chaque membre de l'équipe » ; « Indépendance financière, technique et juridique de l'AMO programmiste A2MO » |
| Dépôt des attestations sur une plateforme tierce (e-Attestations, Provigis) | `plateforme_attestations` | 4 | 0 / 0 | « Transmission tous les 6 mois des attestations de régularité des cotisations sociales (< 6 mois) et de la list… » ; « Inscription sur la plateforme Aprovall (e-attestations) pour dépôt des pièces sociales tous les 6 mois pendan… » ; « Justificatifs articles R. 2143-6 à R. 2143-10 CCP via plateforme e-attestations.com (uniquement pour l'attrib… » |
| Égalité professionnelle, index, parité | `egalite_parite` | 3 | 0 / 0 | « Annexe 1 au CCAP — Questionnaire diversité et égalité professionnelle (peut être remis au moment de l'attribu… » ; « Questionnaire relatif aux pratiques en matière de promotion et d'égalité femmes-hommes (facultatif, usage sta… » ; « Questionnaire Égalité Professionnelle & Diversité (Annexe 1 du RC) — à renseigner en amont de la notification » |

### Assurances

| Type | Code | Occurrences | Certifications bloquantes (oui / non) | Exemples de libellés |
|---|---|---|---|---|
| Attestation d'assurance RC professionnelle | `assurance_rc` | 281 | 42 / 2 | « Déclaration appropriée de banques ou preuve d'une assurance pour les risques professionnels » ; « Attestation d'assurance responsabilité civile professionnelle en cours de validité » ; « Attestation d'assurance responsabilité civile professionnelle » |
| Attestation d'assurance décennale | `decennale` | 68 | 22 / 0 | « Attestation d'assurance responsabilité civile professionnelle décennale » ; « Attestations d'assurance responsabilité civile et décennale » ; « Qualification OPQCB ou QUALIFELEC ou équivalent (exigée pour assurance décennale) » |

### Capacité financière

| Type | Code | Occurrences | Certifications bloquantes (oui / non) | Exemples de libellés |
|---|---|---|---|---|
| Chiffre d'affaires, bilans | `ca_bilans` | 334 | 0 / 0 | « Déclaration concernant le chiffre d'affaires global et le chiffre d'affaires concernant les prestations objet… » ; « Déclaration concernant le chiffre d'affaires global et le CA concernant les prestations objet du contrat sur… » ; « Déclaration de chiffre d'affaires global sur les 3 derniers exercices disponibles » |
| Déclaration de banque / garantie financière | `declaration_bancaire` | 75 | 0 / 0 | « Déclaration appropriée de banques ou preuve d'une assurance pour les risques professionnels » ; « Déclaration appropriée de banques ou preuve d'assurance pour les risques professionnels » ; « Déclarations appropriées de banques ou preuve d'assurance des risques professionnels » |

### Capacité technique et professionnelle

| Type | Code | Occurrences | Certifications bloquantes (oui / non) | Exemples de libellés |
|---|---|---|---|---|
| Références de chantiers / prestations | `references` | 448 | 2 / 3 | « Liste des travaux exécutés au cours des cinq dernières années, appuyée d'attestations de bonne exécution pour… » ; « Liste des principales prestations effectuées au cours des 3 dernières années (montant, date, destinataire) pr… » ; « Liste des principales prestations effectuées au cours des 3 dernières années (montant, date, destinataire, at… » |
| Déclaration des effectifs | `effectifs` | 237 | 0 / 0 | « Déclaration des effectifs moyens annuels et du personnel d'encadrement sur les 3 dernières années » ; « Déclaration indiquant les effectifs moyens annuels et l'importance du personnel d'encadrement sur les 3 derni… » ; « Déclaration des effectifs moyens annuels et importance du personnel d'encadrement sur les 3 dernières années » |
| Outillage, matériel, moyens techniques | `moyens_materiels` | 181 | 7 / 2 | « Déclaration indiquant l'outillage, le matériel et l'équipement technique dont le candidat dispose » ; « Déclaration indiquant l'outillage, le matériel et l'équipement technique dont le candidat dispose pour la réa… » ; « Déclaration de l'outillage, matériel et équipement technique disponible » |
| Attestations de bonne exécution / certificats de capacité | `bonne_execution` | 83 | 0 / 0 | « Liste des travaux exécutés au cours des cinq dernières années, appuyée d'attestations de bonne exécution pour… » ; « Liste des travaux exécutés sur les 5 dernières années avec attestations de bonne exécution » ; « Liste des travaux exécutés au cours des 5 dernières années avec attestations de bonne exécution » |
| Renvoi générique aux capacités (aucune pièce nommée) | `capacites_generique` | 40 | 1 / 1 | « Déclaration sur l'honneur de l'article R2143-3 du Code de la commande publique » ; « Capacités professionnelles et financières du sous-traitant + déclaration sur l'honneur de non-interdiction d'… » ; « DC2 — Déclaration du candidat individuel ou du membre du groupement (capacités professionnelles, techniques e… » |
| CV, équipe, moyens humains | `cv_moyens_humains` | 77 | 9 / 2 | « Note sur l'organisation de l'entreprise et les moyens humains et matériels » ; « Description des moyens humains et matériels du candidat » ; « Liste des moyens humains et matériels du candidat » |
| Titres d'études et professionnels, diplômes | `titres_etudes` | 66 | 5 / 1 | « Titres d'études et professionnels des responsables de prestation » ; « Indication des titres d'études et professionnels de l'opérateur économique et/ou des cadres de l'entreprise,… » ; « Indication des titres d'études et professionnels des responsables de prestation de services de même nature » |
| Présentation de l'entreprise / fiche de renseignements | `presentation_entreprise` | 37 | 0 / 0 | « Mémoire de présentation de la société » ; « Fiche de renseignements fournisseur » ; « Annexe 4 à l'AE — Volumes horaires annuels (poste tertiaire, poste plonge) et coordonnées du personnel dédié… » |

### Qualifications et certifications

| Type | Code | Occurrences | Certifications bloquantes (oui / non) | Exemples de libellés |
|---|---|---|---|---|
| Habilitations du personnel (AIPR, électrique, CACES, SST…) | `habilitations_personnel` | 175 | 58 / 5 | « Attestation de formation CSSI (pour le coordinateur SSI) » ; « AIPR (Autorisation d'Intervention à Proximité des Réseaux) — encadrants et opérateurs » ; « CATEC (Certificat d'Aptitude au Travail en Espaces Confinés) — personnel intervenant dans les regards » |
| Autres labels et certifications nommés | `labels_divers` | 143 | 42 / 17 | « CBCP (Certified Building Commissioning Professional) » ; « Certification LNE SSP (Sites et Sols Pollués) » ; « Certification CMVP (Commissioning Management Verified Professional) - de préférence indépendant de l'EG et de… » |
| Certificats de qualification professionnelle (sans label nommé) | `certificats_qualification` | 83 | 13 / 10 | « Certificats de qualifications professionnelles de la branche BTP-Bâtiment (FFB) » ; « Justificatifs de qualification et compétences professionnelles du candidat » ; « Certificats de qualification professionnelle ou preuve de capacité » |
| Qualibat | `qualibat` | 85 | 19 / 37 | « Qualification 5912 ENR Photovoltaïque (Qualibat) — alternative à QualiPV » ; « Certificats de qualification professionnelle Qualibat 5252 et 5112 (ou équivalent) » ; « Qualibat 5252 — Installation de réseaux de chauffage ou de rafraîchissement avec centrale de traitement d'air » |
| Certification ou habilitation amiante (SS3 / SS4) | `amiante` | 38 | 13 / 2 | « Attestations de compétences SS4 (formation amiante sous-section 4) du personnel intervenant — lot 1 uniquement » ; « Qualification Qualibat 1512 — Traitement de l'amiante en place (matériaux et produits à risques particuliers… » ; « Qualification Qualibat 1513 — Traitement de l'amiante en place (matériaux et produits friables) » |
| Autorisation d'exercer (licence, agrément, carte professionnelle, ordre) | `autorisation_exercer` | 180 | 74 / 3 | « Accréditation COFRAC (ou équivalent NF EN CEI/ISO 17020) pour l'organisme de contrôle » ; « Carte professionnelle des personnels dédiés au marché » ; « Agrément officiel pour la sécurité des ouvrages hydrauliques (Journal Officiel) » |
| Qualifelec | `qualifelec` | 16 | 4 / 3 | « Qualification OPQCB ou QUALIFELEC ou équivalent (exigée pour assurance décennale) » ; « Qualification SPV2 (Qualifelec) — alternative à QualiPV » ; « Qualification Qualifelec E2 - classification 3 (lot 4 Électricité) » |
| RGE (Reconnu garant de l'environnement) | `rge` | 35 | 10 / 0 | « Qualification 5912 ENR Photovoltaïque (Qualibat) — alternative à QualiPV » ; « Qualification SPV2 (Qualifelec) — alternative à QualiPV » ; « Qualification AQPV (Certisolis) — alternative à QualiPV » |
| OPQIBI / OPQTECC / OPQCM (ingénierie, conseil) | `opqibi` | 19 | 4 / 1 | « Qualification OPQCB ou QUALIFELEC ou équivalent (exigée pour assurance décennale) » ; « OPQIBI 1333 (Etude ACV bâtiments neufs) ou qualification équivalente » ; « OPQIBI 1910 (accompagnement au commissionnement des installations techniques du bâtiment) ou qualification éq… » |
| Identification professionnelle FNTP / Canalisateurs | `fntp` | 23 | 3 / 2 | « Preuve d'une technicité équivalente à la qualification FNTP 1131 (Ouvrages de technicité courante) — certific… » ; « Qualification FNTP 1131 — Ouvrages de technicité courante (ou preuve d'équivalence par tout moyen : certifica… » ; « FNTP 1131 (Ouvrages de technicité courante) ou équivalent » |
| Certification ISO (9001, 14001, 45001…) | `iso` | 23 | 3 / 7 | « Accréditation COFRAC (ou équivalent NF EN CEI/ISO 17020) pour l'organisme de contrôle » ; « Attestations de certification développement durable/environnement (ISO 14000, HQE ou équivalent) » ; « Attestations de certification développement durable/environnement (ISO 14000, démarche HQE ou équivalent) » |

### Offre

| Type | Code | Occurrences | Certifications bloquantes (oui / non) | Exemples de libellés |
|---|---|---|---|---|
| BPU / DPGF / DQE / pièces de prix | `prix` | 360 | 3 / 0 | « Bordereau des Prix Unitaires (BPU) complété » ; « Bordereau des prix unitaires (BPU) dûment complété » ; « Bordereau des prix unitaires (BPU) complété » |
| Mémoire technique / cadre de réponse | `memoire_technique` | 304 | 0 / 0 | « Mémoire technique » ; « Mémoire justificatif des dispositions que l'entreprise se propose d'adopter pour l'exécution du contrat » ; « Mémoire technique du candidat » |
| Acte d'engagement (AE, ATTRI1) | `ae` | 268 | 0 / 0 | « Acte d'engagement (AE) et ses annexes » ; « Acte d'engagement (AE) et ses annexes — signé » ; « Acte d'engagement (AE) complété » |
| Attestation / certificat de visite | `visite` | 79 | 4 / 0 | « Attestation de visite de site (si visite effectuée — optionnelle) » ; « Attestation de visite du site (délivrée par l'acheteur) » ; « Attestation de visite du site obligatoire (visites les 25 juin 2026 à 14h00 et 7 juillet 2026 à 10h00) » |
| Pièces du marché à accepter ou signer (CCAP, CCTP, RC, charte) | `pieces_marche_signees` | 98 | 5 / 0 | « CCTP signé » ; « CCAP et CCTP dûment signés et paraphés » ; « CCAP valant acte d'engagement, dûment complété et signé » |
| Planning, calendrier, délais | `planning` | 36 | 0 / 0 | « Planning de déploiement » ; « CV des intervenants avec prestations dévolues à chacun, en cohérence avec les délais d'exécution proposés » ; « Les personnels affectés doivent justifier des capacités techniques et professionnelles conformément à l'offre… » |
| Fiches techniques, échantillons, documentation produit | `fiches_techniques` | 58 | 3 / 2 | « Fiches techniques correspondant aux produits et prestations proposés » ; « Catalogue des prix du fournisseur » ; « Fiches techniques des matériels proposés » |
| Variantes, PSE, options | `variantes_pse` | 11 | 0 / 0 | « Offre financière détaillée du candidat (système de base + PSE obligatoires et facultatives) » ; « Réponse obligatoire à la PSE N°2 (Trans-LC ou DCE) — absence = offre irrégulière éliminée » ; « Pour lot 1 — Variante : acte d'engagement variante renseigné (CDPGF variante) » |
| Signature électronique, copie de sauvegarde, modalités de dépôt | `signature_depot` | 6 | 0 / 0 | « Certificat de signature électronique conforme RGS niveau II si signature dématérialisée » ; « Pouvoir de signature de la personne habilitée (de préférence signature électronique, à défaut manuscrite) » ; « Acte d'engagement (AE) dûment complété, revêtu d'une signature électronique (XAdES, CAdES ou PAdES, niveau av… » |

### Engagements et exécution

| Type | Code | Occurrences | Certifications bloquantes (oui / non) | Exemples de libellés |
|---|---|---|---|---|
| Environnement, déchets (SOGED, SOSED), RSE | `environnement_dechets` | 82 | 4 / 3 | « Indication des mesures de gestion environnementale applicables lors de l'exécution du contrat » ; « Indication des mesures de gestion environnementale applicables lors de l'exécution » ; « Indication des mesures de gestion environnementale applicables lors de l'exécution du marché » |
| Condition d'exécution ou de moyens (délai d'intervention, présence locale, astreinte) | `exigence_execution` | 80 | 7 / 1 | « Assurance responsabilité civile professionnelle en cours de validité à produire au plus tard 15 jours après n… » ; « Annexe 7 à l'AE — Bordereau de prix des prestations habituelles de plonge (vaisselle et batterie, par tranche… » ; « Attestation de formation du personnel aux règles de bonnes pratiques d'hygiène en restauration collective (HA… » |
| Engagement d'insertion / clause sociale | `insertion` | 26 | 1 / 0 | « Annexe 3 à l'AE — Engagement clause d'insertion sociale (lots 1 et 2) » ; « Annexe 3 à l'AE — Attestation d'engagement en matière d'insertion par l'activité économique (450 h/an minimum… » ; « Engagement à réaliser minimum 450 heures d'insertion par an au profit de personnes éloignées de l'emploi (cla… » |
| Sécurité et qualité (PPSPS, PAQ, plan de prévention) | `securite_qualite` | 39 | 3 / 0 | « Certificats de contrôle qualité des fournitures établis par des instituts ou services officiels » ; « Démarche qualité documentée : procédures rédigées et appliquées, plan d'analyse défini, traçabilité réactifs/… » ; « EPI spécifiques stand de tir (combinaison, masque de protection R4321-4 code du travail) » |
| RGPD, confidentialité, cybersécurité | `donnees_confidentialite` | 49 | 4 / 0 | « Annexe 2 à l'AE — Attestation de sécurité signée (articles 413-9 à 413-12 code pénal) » ; « Attestation de sécurité signée : reconnaissance des articles 413-9 à 413-12 du code pénal, engagement de conf… » ; « Éléments de l'offre SSI : déclaration des outils utilisés, fiche d'hébergement, note de gestion des versions,… » |
| Contrôle d'accès au site (liste nominative, pièces d'identité, enquête) | `acces_site` | 19 | 2 / 0 | « Accès possible aux unités hébergeant des détenus (UHSI) : fournir préalablement noms, pièces d'identité et im… » ; « Organigramme de tous les personnels qui interviendront (directement ou indirectement) avec CNI recto/verso (l… » ; « Enquête administrative individuelle sur le personnel intervenant (lot 1 — marché sensible) : résultat sans ré… » |

## Couverture cumulée des pièces de candidature BTP

Base : 437 pièces de phase candidature dans les 80 briefs BTP. Une pièce est couverte quand tous ses types sont dans la liste. À chaque rang, le type ajouté est celui qui couvre le plus de pièces supplémentaires.

| Rang | Type ajouté | Pièces couvertes (cumul) | Part cumulée |
|---|---|---|---|
| 1 | Chiffre d'affaires, bilans | 34 | 8 % |
| 2 | Déclaration des effectifs | 61 | 14 % |
| 3 | DC2 / déclaration du candidat | 86 | 20 % |
| 4 | DC1 / lettre de candidature | 109 | 25 % |
| 5 | DUME | 137 | 31 % |
| 6 | Déclaration sur l'honneur (interdictions de soumissionner) | 164 | 38 % |
| 7 | Outillage, matériel, moyens techniques | 187 | 43 % |
| 8 | Références de chantiers / prestations | 210 | 48 % |
| 9 | Attestations de bonne exécution / certificats de capacité | 229 | 52 % |
| 10 | Attestation d'assurance RC professionnelle | 246 | 56 % |
| 11 | Jugement de redressement judiciaire | 260 | 59 % |
| 12 | Obligation d'emploi des travailleurs handicapés | 273 | 62 % |
| 13 | Attestation d'assurance décennale | 285 | 65 % |
| 14 | Pouvoir / délégation de signature | 294 | 67 % |
| 15 | Extrait Kbis / inscription au registre | 304 | 70 % |
| 16 | Pièces de groupement, capacités d'un tiers | 313 | 72 % |
| 17 | DC4 / déclaration de sous-traitance | 323 | 74 % |
| 18 | Habilitations du personnel (AIPR, électrique, CACES, SST…) | 332 | 76 % |
| 19 | Déclaration de banque / garantie financière | 340 | 78 % |
| 20 | Titres d'études et professionnels, diplômes | 347 | 79 % |
| 21 | Certificats de qualification professionnelle (sans label nommé) | 354 | 81 % |
| 22 | Renvoi générique aux capacités (aucune pièce nommée) | 360 | 82 % |
| 23 | Qualibat | 366 | 84 % |
| 24 | Autres labels et certifications nommés | 371 | 85 % |
| 25 | RGPD, confidentialité, cybersécurité | 376 | 86 % |
| 26 | Attestation URSSAF (régularité sociale, vigilance) | 380 | 87 % |
| 27 | Attestation de régularité fiscale | 389 | 89 % |
| 28 | Attestation / certificat de visite | 393 | 90 % |
| 29 | Liste nominative des travailleurs étrangers (LNTE) | 397 | 91 % |
| 30 | Autorisation d'exercer (licence, agrément, carte professionnelle, ordre) | 400 | 92 % |
| 31 | Environnement, déchets (SOGED, SOSED), RSE | 403 | 92 % |
| 32 | RIB | 406 | 93 % |
| 33 | Identification professionnelle FNTP / Canalisateurs | 409 | 94 % |
| 34 | RGE (Reconnu garant de l'environnement) | 412 | 94 % |
| 35 | Certification ou habilitation amiante (SS3 / SS4) | 414 | 95 % |
| 36 | Présentation de l'entreprise / fiche de renseignements | 416 | 95 % |

## Codes Qualibat

16 marchés citent Qualibat, 10 avec au moins un code à 4 chiffres, 48 codes distincts. Liste limitée aux 30 premiers.

| Code | Marchés | Exemple de libellé |
|---|---|---|
| 3101 | 2 | Qualibat 3101 — Charpente métallique (Lot 8) |
| 3152 | 2 | Qualibat 3152 — Couverture métallique (Lot 8) |
| 3541 | 2 | Qualibat 3541 — Serrurerie (Lots 2, 3) |
| 3811 | 2 | Qualibat 3811 — Bardage (Lot 9) |
| 4411 | 2 | Qualibat 4411 — Clôtures (Lot 3) |
| 5111 | 2 | Qualibat 5111 — Plomberie (Lot 6) |
| 5112 | 2 | Certificats de qualification professionnelle Qualibat 5252 et 5112 (ou équivalent) |
| 6111 | 2 | Qualibat 6111 — Peinture intérieure (Lot 7) |
| 1311 | 1 | Qualibat 1311 — Maçonnerie et béton armé courant (Lots 1, 5, 6) |
| 1321 | 1 | Qualibat 1321 — Gros œuvre (Lot 6) |
| 1411 | 1 | Qualibat 1411 — Maçonnerie courante (Lots 1, 2, 3, 4, 5, 7, 8, 9) |
| 1512 | 1 | Certificats de qualifications professionnelles ou preuves équivalentes (dont Qualibat 1512/1513 pour le lot 1) |
| 1513 | 1 | Certificats de qualifications professionnelles ou preuves équivalentes (dont Qualibat 1512/1513 pour le lot 1) |
| 1552 | 1 | Certification unique amiante (Qualibat 1552 ou équivalent) ou pré-certification (accusé de réception + règlement du bon de commande de cert… |
| 2111 | 1 | Lot 4 — Qualibat 2111 (Maçonnerie) |
| 2112 | 1 | Qualibat 2112 — Béton armé courant (Lot 1) |
| 2151 | 1 | Qualibat 2151 — Carrelage (Lot 1) |
| 2312 | 1 | Qualibat 2312 — Charpente bois (Lot 8) |
| 2391 | 1 | Qualibat 2391 — Couverture (Lot 8) |
| 3123 | 1 | Qualibat 3123 « Tuiles plates » |
| 3141 | 1 | Qualibat 3141 — Bardage métallique (Lot 8) |
| 3211 | 1 | Qualibat 3211 — Étanchéité bitumineuse (Lot 9) |
| 3271 | 1 | Qualibat 3271 — Étanchéité liquide (Lot 9) |
| 3512 | 1 | Qualibat 3512 — Menuiseries extérieures aluminium (Lot 2) |
| 3521 | 1 | Qualibat 3521 — Menuiseries extérieures PVC (Lot 2) |
| 3551 | 1 | Qualibat 3551 — Vitrerie (Lot 2) |
| 4112 | 1 | Qualibat 4112 — Faux plafonds (Lot 4) |
| 4131 | 1 | Lot 7 — Qualibat 4131 (Plâtrerie) + 6111 (Peinture intérieure) + 6211 (Revêtements de sol) + 6311 (Carrelage) |
| 4211 | 1 | Qualibat 4211 — Isolation thermique par l'intérieur (Lot 4) |
| 4311 | 1 | Lot 8 — Qualibat 4311 (Menuiserie intérieure bois) |

## RGE, MASE, ISO

| Certification | Marchés tous | Marchés BTP | Part des marchés BTP |
|---|---|---|---|
| Qualibat | 16 | 15 | 19 % |
| RGE (Reconnu garant de l'environnement) | 6 | 5 | 6 % |
| MASE | 0 | 0 | 0 % |
| Certification ISO (9001, 14001, 45001…) | 10 | 2 | 2 % |
| Qualifelec | 6 | 5 | 6 % |
| Identification professionnelle FNTP / Canalisateurs | 5 | 4 | 5 % |
| Certification ou habilitation amiante (SS3 / SS4) | 12 | 12 | 15 % |
| Habilitations du personnel (AIPR, électrique, CACES, SST…) | 66 | 28 | 35 % |

Normes ISO citées (en marchés) : ISO 9001 : 4, ISO 14001 : 3, ISO non précisée : 3, ISO 14000 : 1, ISO 27002 : 1, ISO 17020 : 1, ISO 27001 : 1.

## Chiffre d'affaires minimum

166 marchés (70 %) demandent le chiffre d'affaires ou les bilans ; 10 seulement (4 %) fixent un seuil chiffré, dont 5 en BTP. Marchés exprimant aussi le seuil en multiple du montant du marché : 1.

| Seuil le plus bas cité par le marché | Marchés |
|---|---|
| moins de 100 k€ | 2 |
| 100 à 500 k€ | 3 |
| 500 k€ à 1 M€ | 0 |
| 1 à 5 M€ | 2 |
| plus de 5 M€ | 3 |

| Marché | Secteur | Seuils cités (€) | Libellé |
|---|---|---|---|
| BOAMP-26-56627 | autre | 75 000 | Chiffre d'affaires dans le domaine concerné d'un montant minimum de 75 000 € pour chacun des 3 derniers exercices disponibles |
| BOAMP-26-51023 | autre | 86 100 | Chiffre d'affaires annuel global moyen sur les trois derniers exercices disponibles ≥ 86 100 € |
| BOAMP-26-56451 | BTP | 250 000, 500 000, 1 000 000 | Lot 5 — CA annuel ≥ 250 K€ (niveau CA1) ; Lots 1, 3, 4, 6, 8, 9, 10, 11, 12 — CA annuel entre 250 K€ et 500 K€ (niveau CA2) ; Lots 2, 7, 10 — CA annuel entre 5… |
| BOAMP-26-51011 | autre | 297 201 | Chiffre d'affaires annuel global moyen sur les 3 derniers exercices disponibles ≥ 297 201 € |
| BOAMP-26-56190 | autre | 400 000 | Chiffre d'affaires annuel minimum de l'équipe candidate (somme de tous les membres) sur le dernier exercice disponible : 400 000 € HT |
| BOAMP-26-56151 | autre | 1 000 000 | CA minimum de 1 000 000 € HT (moyenne 3 derniers exercices) pour les opérateurs portant la conception architecturale |
| BOAMP-26-56151 | autre | 1 000 000 | CA minimum de 1 000 000 € HT (moyenne 3 derniers exercices) pour les opérateurs portant la conception technique (BET) |
| BOAMP-26-56419 | BTP | 1 000 000 | CA minimum des cabinets de conception architecturale (seul ou cumul) : 1 000 000 € HT (moyenne 3 derniers exercices) |
| BOAMP-26-56419 | BTP | 1 000 000 | CA minimum des bureaux d'études conception technique (seul ou cumul) : 1 000 000 € HT (moyenne 3 derniers exercices) |
| BOAMP-26-56151 | autre | 20 000 000 | CA minimum de 20 M€ HT (moyenne 3 derniers exercices) pour l'entreprise générale de travaux TCE ou le cumul des entreprises de travaux du groupement |
| BOAMP-26-56238 | BTP | 20 000 000 | Chiffre d'affaires global annuel du groupement ≥ 20 000 000 € HT sur chacun des trois derniers exercices disponibles |
| BOAMP-26-56419 | BTP | 20 000 000 | CA minimum de l'entreprise générale TCE (seule ou cumul du groupement) : 20 M€ HT (moyenne 3 derniers exercices) |
| BOAMP-26-56633 | BTP | 21 900 000 | Chiffre d'affaires global du mandataire constructeur (ou groupement mandataire) : moyenne sur 3 derniers exercices ≥ 21 900 000 € HT (1,5× le montant du marché) |
| BOAMP-26-102932 | BTP | 70 000 000 | Chiffre d'affaires annuel moyen sur les 3 derniers exercices supérieur à 70 000 000 € TTC dans le domaine d'activités couvert par le marché |

## Références demandées

179 marchés (76 %) demandent des références ; 18 en fixent le nombre minimum.

| Nombre minimum de références | Marchés |
|---|---|
| 1 | 2 |
| 2 | 4 |
| 3 | 8 |
| 5 | 4 |

| Période couverte par les références (libellés) | Marchés |
|---|---|
| 3 dernières années | 103 |
| 5 dernières années | 38 |
| 10 dernières années | 1 |

| Champ `experience_minimale_annees` | Marchés |
|---|---|
| 3 ans | 46 |
| 4 ans | 1 |
| 5 ans | 31 |
| 10 ans | 2 |

Le champ `experience_minimale_annees` reprend le plus souvent la période des références (« 5 dernières années »), pas une ancienneté de l'entreprise.

## Effectifs

128 marchés (54 %) demandent une déclaration d'effectifs ; 2 fixent un effectif minimum.

| Marché | Secteur | Effectif minimum lu | Libellé |
|---|---|---|---|
| BOAMP-26-55979 | BTP | 15 | Effectifs minimum par lot : lot 1 = 15 agents, lot 2 = 8 agents, lot 3 = 4 agents, lots 4-15 = 4 à 8 agents selon lot (voir RC art. 4.1 §4) |
| BOAMP-26-57265 | BTP | 10 | Effectif minimum de 10 personnes sur l'année en cours (exigé pour les 2 lots) |

## Libellés non reconnus (100 plus fréquents)

87 occurrences sur 4099 (2.1 %). Liste complète : `exigences_non_reconnus.csv`.

| Occurrences | Libellé |
|---|---|
| 2 | Indication des systèmes de gestion et de suivi de la chaîne d'approvisionnement |
| 1 | Le mandataire du groupement doit impérativement être une entreprise générale de travaux TCE |
| 1 | Aspirateur anti-déflagration pour stand de tir (fourni par le titulaire) |
| 1 | Dimensions de l'équipement compatibles avec les contraintes de la salle blanche IEMN (zone délimitée Image 1 du CCTP) — rejet de l'offre si incompatibilité dimensionnelle |
| 1 | Vêtements de travail fournis dès le 1er jour, comportant le logo de la société, adaptés aux tâches (vêtements clairs cuisine/plonge, chaussures de sécurité). |
| 1 | Interdiction d'utiliser des outils d'IA générative non validés par le SSMSI pour traiter des contenus non publiés |
| 1 | Supports physiques (panneaux de présentation) en phase offre |
| 1 | Présentation des entreprises de travaux Électricité, Automatismes GTB et CVC (si non présentées en candidature) |
| 1 | Assurance 'constructeur' / 'contractant général' ou équivalent pour le mandataire (si entreprise de management de projet) |
| 1 | Engagement sur la date de démarrage des travaux au 05 octobre 2026 maximum |
| 1 | Mesures envisagées pour limiter les nuisances phoniques du chantier |
| 1 | Document listant les composants câblages proposés pour la solution VDI complété (lot 8 uniquement) |
| 1 | Pour lot 7 : conformité à la Directive Européenne Ascenseurs 95/16/CE — attestation de conformité requise |
| 1 | Pour lot 7 : conformité à la Directive Européenne 95/16/CE (ascenseurs) |
| 1 | Attestation d'exonération de TVA signée par la DREETS (formulaire 10219*16 / 3511-SD) si applicable |
| 1 | Justificatifs de responsabilité sociétale |
| 1 | Pour les intermédiaires (courtiers) : dossier double — un au nom de la compagnie portant le risque (ou attestation d'engagement à le produire si retenu), un au nom du cabinet de courtage |
| 1 | Conditions générales de garanties de l'assureur (si elles complètent ou remplacent celles du cahier des charges — tableau OUI/NON à renseigner) |
| 1 | Pour le lot 4 (prestations statutaires) : capacité à gérer un contrat en capitalisation (maintien des prestations après résiliation) |
| 1 | Conditions générales de garanties de la compagnie (avec tableau comparatif CG vs CCG du DCE) |
| 1 | Constitution d'une société dédiée à objet exclusif pour l'exécution du contrat, majoritairement contrôlée par le candidat ou les membres du groupement |
| 1 | Brochure A4 de vulgarisation des règles de tri pour les agents municipaux (Lot 2 uniquement) |
| 1 | Plan de circulation sur le site de traitement (Lot 2 uniquement) |
| 1 | Annexe CCAP — Modalités de recouvrement des sommes (encaissement des recettes) |
| 1 | Compétences pour les chaudières > 400 kW : possession d'un analyseur portatif des gaz de combustion et d'un déprimomètre en état de bon fonctionnement |
| 1 | Désignation d'au moins 2 personnes physiques agréées CSPS niveau 1 au sein de la société ou du groupement (titulaire + suppléant) pour assurer la continuité de la mission |
| 1 | Respect du CCSC (arrêté 18/09/2018) |
| 1 | Conformité OWASP Top 10 2025 |
| 1 | Couverture de toutes les compétences exigées : Architecture, OPC, Ingénierie restauration collective, Ingénierie des structures, Ingénierie des fluides/CVC/plomberie, Courants forts et faibles, Écono… |
| 1 | Annexe aux formulaires de déclaration dûment complétée |
| 1 | Aptitude à assurer la continuité du service public et l'égalité des usagers devant le service public |
| 1 | Compétences en travaux sur Monuments Historiques implicitement requises (prescriptions LRMH, techniques chaux, taille de pierre) |
| 1 | Bureau d'étude géotechnique qualifié et accepté par le MOE si nouvelle étude commandée (CCTP §1.30) |
| 1 | Câbles courant fort et courant faible : type C1 Euroclass C-s2,d2,a2 (ERP 5e catégorie) — mentionné comme avis défavorable Apave sur CCTP Lot électricité existant |
| 1 | Expertise dans la mise en œuvre et le déploiement de la méthode VSC sur un parc d'ouvrages portuaires |
| 1 | Compétences en inspection des parties émergées et immergées des ouvrages maritimes et portuaires |
| 1 | Chaque candidat doit être en mesure de remplir intégralement les missions des 2 lots techniques (expertise évaluation ET assistance commercialisation/cession) |
| 1 | Capacité à assurer le SSO via Azure Active Directory / Entra ID avec protocoles SAML 2.0 ou OAuth2/OIDC — exigence technique éliminatoire |
| 1 | Conformité aux référentiels ANSSI (bonnes pratiques) |
| 1 | Carnet d'entretien et de suivi des désinfections dans chaque véhicule, kit AES disponible à tout instant |
| 1 | Deux traductions (Français/Allemand et Allemand/Français) sur les textes fournis par l'acheteur dans le DCE |
| 1 | Conditions particulières du CCP complétées |
| 1 | Offre du candidat (conditions particulières additionnelles, conventions spéciales, annexes, conditions générales, etc.) |
| 1 | Une même compagnie d'assurance ne peut présenter plus d'une offre par lot ; un même intermédiaire ne peut présenter plus d'une offre par lot ; une même personne ne peut représenter plus d'un candidat… |
| 1 | Code d'accès à la plateforme de commande pour test (sous-critère organisation logistique) |
| 1 | Conformité référentiels ANSSI |
| 1 | Partenariat Microsoft / compétences Microsoft 365 appréciées |
| 1 | Cadre de candidature (fourni dans le DCE) et son annexe 1 (membres du groupement) dûment complétés |
| 1 | Conditions particulières du CCP complétées par le candidat (colonnes 'propositions du candidat' renseignées) |
| 1 | Offre du candidat : conditions particulières additionnelles, conventions spéciales, annexes, conditions générales de l'assureur |
| 1 | Une même compagnie d'assurance ne peut présenter plus d'une offre ; un même intermédiaire ne peut représenter plus d'un candidat |
| 1 | Tableau temps dédié (document fourni au DCE, à remplir obligatoirement) |
| 1 | Non précisé dans le RC |
| 1 | Annexe CCAP révision de prix lot 4 (fichier Excel complété) pour le lot 4 |
| 1 | Guide d'utilisation type du site de réservation online (avec captures d'écran, procédures administrateur, éléments techniques et juridiques) |
| 1 | Tableau de candidature complété (fichier Excel fourni dans le DCE) |
| 1 | Reprise obligatoire du personnel : le nouveau titulaire doit reprendre les 7 agents listés en annexe 1 et se conformer à la convention collective nationale du personnel des entreprises de restauratio… |
| 1 | Mission intégrant obligatoirement un bureau d'études en fontainerie |
| 1 | Bureau d'études en fontainerie (obligatoire, mentionné explicitement dans le RC et le CCTP) |
| 1 | Interdiction de recourir à un outil d'intelligence artificielle dans l'exécution des prestations |
| 1 | Capacité à conduire 6 coachings individuels, binômes ou collectifs en simultané (Lot 1) – équipe de 4 coachs titulaires + 1 suppléant |
| 1 | Pour lot 13 (distribution électrique) : installations temporaires vérifiées avant mise en service par organisme accrédité si puissance > 36 kVA, ou par technicien compétent si ≤ 36 kVA (arrêté 25/07/… |
| 1 | Pour lot 11 (sonorisation/éclairage) : respect de la réglementation travail sous tension (courants faibles et forts) et sécurité des installations scéniques (arrêté 25/07/2022 art.37 et s.) |
| 1 | Personnel maîtrisant le français (compréhension des consignes orales et écrites, règles de sécurité) |
| 1 | Certificat BPDG (Bonnes Pratiques de Distribution en Gros) en cours de validité — si le candidat effectue la distribution |
| 1 | Plan de formation annuel |
| 1 | Description des procédés de fabrication et formes pharmaceutiques maîtrisés, substances actives pouvant être prises en charge, et périmètre non faisable |
| 1 | Décomposition en jours de la prestation complétée, datée et signée |
| 1 | ACACED (Attestation de Connaissances pour les Animaux de Compagnie d'Espèces Domestiques) ou CCAD ou justificatif équivalent pour au moins 2 agents mobilisables |
| 1 | Convention ou titre juridique permettant l'utilisation d'une structure de fourrière légalement habilitée avec capacité minimale de 5 places chiens et 5 places chats |
| 1 | Justificatifs concernant les médecins partenaires (tableau de répartition géographique + protocoles d'accord ou lettres d'engagement des médecins validés par l'Ordre, classés par département) |
| 1 | Description des formes pharmaceutiques maîtrisées et périmètre non faisable |
| 1 | Copie de la carte de guide-conférencier pour chaque guide envisagé |
| 1 | Documents complémentaires jugés utiles par le candidat |
| 1 | Respect des obligations EGAlim et Climat & Résilience (taux produits bio et labellisés restauration collective) |
| 1 | Bureau d'Études Techniques (BET) spécialisé en AMO maintenance et exploitation d'infrastructures de transport public — statut de BET requis explicitement |
| 1 | Compétences obligatoires : AMO en exploitation ET en maintenance (les deux simultanément) + maîtrise des coûts en exploitation et maintenance |
| 1 | Bureau de contrôle associé : fortement apprécié (CCTP §3) |
| 1 | Étude géotechnique d'exécution G3 (phase étude + suivi) à la charge de l'entreprise de fondations spéciales — lot 1 |
| 1 | Base de données administratives complétée au format Excel |
| 1 | Base de données administratives au format Excel, dûment complétée |
| 1 | Rapport écocomparateur SEVE pour les prix BB/GB et GNT désignés (G3 2.01, 2.11, 2.14, 2.21 et D4 1.01, 1.02, 1.03, 1.07) |
| 1 | Justification de compétences et expériences avérées dans la gestion des terres et constitution de sols reconstitués pour aménagements paysagers |
| 1 | Attestation de prise de connaissance de l'IM 2004 (administrateurs de systèmes d'information) pour les intervenants sur les systèmes industriels |
| 1 | Personnel habilité pour accès à la base militaire (contrôle primaire MinArm) — CCTP §1.10.1 |
| 1 | Synoptique d'architecture A3 (minimum) pour chacun des 3 cas-types — pièce contractuelle |
