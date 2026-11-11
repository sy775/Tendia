# Référentiel des pièces demandées aux candidats

Une ligne par type mesuré à l'étape 1 (`exigences_frequence.md`). Fréquences : part des 80 briefs BTP (et des 236 briefs tous secteurs) qui portent le type.

Règle de rédaction : toute affirmation réglementaire (validité, article, organisme) renvoie à une source officielle **consultée le 2026-11-11**, notée [Sn] et listée en fin de document. Ce qui n'a pas pu être lu sur une source officielle est écrit « à vérifier ». Les pages d'economie.gouv.fr (DAJ) et d'infogreffe.fr ont refusé la lecture automatique (HTTP 403), urssaf.fr a coupé la connexion : leurs liens sont donnés comme lieux d'obtention, sans qu'aucune règle n'en soit tirée.

## 1. Ce que dit le droit, en six règles utiles au coffre

| # | Règle | Source |
|---|---|---|
| 1 | À la candidature, le candidat fournit une déclaration sur l'honneur (absence de cas d'exclusion) et les renseignements demandés par l'acheteur. | R2143-3 [S1] |
| 2 | L'acheteur accepte une candidature sous forme de DUME à la place de cette déclaration et de ces renseignements. | R2143-4 [S1] |
| 3 | Les preuves fiscales et sociales sont des certificats des administrations compétentes : administration fiscale, attestation de l'article L. 243-15 du code de la sécurité sociale (Urssaf), caisses de congés payés et chômage intempéries. | R2143-7 [S1], arrêté du 22 mars 2019 [S4] |
| 4 | Pour l'inscription au registre, le candidat produit son numéro unique d'identification (SIREN) ; en redressement judiciaire, la copie du ou des jugements. | R2143-9, modifié par le décret 2021-631, en vigueur depuis le 2021-11-01 [S1] |
| 5 | Le candidat n'est pas tenu de fournir ce que l'acheteur obtient gratuitement par un système électronique officiel ou un espace de stockage numérique dont l'accès figure au dossier, ni ce qu'il a déjà transmis au même acheteur et qui reste valable. | R2143-13, R2143-14 [S1] |
| 6 | La liste des justificatifs de capacité technique est limitative (hors défense) ; le chiffre d'affaires minimal exigible est plafonné à 1,5 fois le montant estimé du marché ou du lot depuis le 2026-01-01. | Arrêté du 22 mars 2019, art. 3 [S3] ; R2142-7, modifié par le décret 2025-1383 [S2] |

Conséquences pour Tendia :

| Constat | Conséquence |
|---|---|
| La règle 5 vise explicitement un « espace de stockage numérique » gratuit. | Le coffre peut, à terme, être l'espace que le candidat indique dans son dossier. À trancher (synthèse, question 8). |
| La règle 4 rend le Kbis non exigible en candidature, et pourtant 16 % des briefs BTP le demandent encore. | Le coffre garde un Kbis à jour (gratuit pour le dirigeant) plutôt que d'argumenter avec l'acheteur. |
| Aucune règle d'ancienneté maximale des certificats n'apparaît dans les articles R2143-1 à R2143-16 [S1]. | Les « moins de 3 mois » et « moins de 6 mois » viennent du règlement de consultation de chaque marché : le coffre compare la date de la pièce à l'exigence du marché, pas à une règle fixe. |
| Attestations fiscale et de vigilance ne sont dues que par l'entreprise retenue ; à la candidature, une déclaration sur l'honneur suffit [S5]. | Statut « à fournir si vous êtes retenu » distinct de « à joindre au dossier ». |

## 2. Pièces de candidature

Colonne « Lecture automatique » : ce que Tendia peut extraire du document déposé. Colonne « BTP / Tous » : fréquence mesurée.

### 2.1 Formulaires (produits par Tendia à partir du profil)

| Type | Nom usuel | À quoi elle sert pour l'acheteur | Qui la délivre | Où l'obtenir | Validité habituelle | Lecture automatique | Périmètre | BTP / Tous |
|---|---|---|---|---|---|---|---|---|
| `dc1` | DC1, lettre de candidature | Identifier le candidat ou le groupement, désigner le mandataire, porter la déclaration sur l'honneur (R2143-3 [S1]) | Le candidat (formulaire DAJ) | https://www.economie.gouv.fr/daj/les-formulaires-de-declaration-du-candidat (non lue, 403) | Un par consultation. Caractère facultatif du formulaire : à vérifier | Sans objet (généré) | Général | 71 % / 80 % |
| `dc2` | DC2, déclaration du candidat | Porter les renseignements de capacité : chiffre d'affaires, effectifs, références, moyens (arrêté du 22 mars 2019 [S3]) | Le candidat (formulaire DAJ) | Même page DAJ (non lue) | Un par consultation, un par membre du groupement : à vérifier | Sans objet (généré) | Général | 64 % / 75 % |
| `dume` | DUME | Remplacer DC1 et DC2 : l'acheteur « accepte » ce format (R2143-4 [S1]) ; réutilisable si les informations restent valables | Le candidat | Service DUME de Chorus Pro, https://dume.chorus-pro.gouv.fr/ (page vide à la lecture) : à vérifier | Réutilisable tant que les informations sont valables [S1] | Sans objet (généré) | Général | 31 % / 34 % |
| `attestation_honneur` | Déclaration sur l'honneur | Attester l'absence de cas d'exclusion et le respect de l'obligation d'emploi des travailleurs handicapés (R2143-3 [S1]) ; preuve suffisante pour les exclusions L2141-1, L2141-4, L2141-5 (R2143-6, version du 2025-01-01 [S1]) | Le candidat | Incluse dans le DC1 ou le DUME ; sinon texte libre signé | Une par consultation | Sans objet (généré) | Général | 54 % / 58 % |
| `dc4` | DC4, déclaration de sous-traitance | Présenter un sous-traitant et ses conditions de paiement | Le candidat et le sous-traitant | Page DAJ ci-dessus (non lue). Règles de déclaration et seuil de paiement direct : à vérifier | Une par sous-traitant et par marché | Sans objet (généré), 90 % des occurrences sont facultatives (« le cas échéant ») | Général | 50 % / 47 % |
| `groupement` | Pièces de groupement, capacités d'un tiers | Prouver que le candidat disposera des capacités d'un autre opérateur, « par tout moyen approprié » (R2143-12 [S1]) | Les cotraitants | Texte libre (engagement écrit, convention) | Par consultation | Noms et SIRET des cotraitants | Général | 20 % / 25 % |

### 2.2 Situation juridique, fiscale et sociale (coffre)

| Type | Nom usuel | À quoi elle sert pour l'acheteur | Qui la délivre | Où l'obtenir | Validité habituelle | Lecture automatique | Périmètre | BTP / Tous |
|---|---|---|---|---|---|---|---|---|
| `kbis` | Extrait K ou Kbis | Prouver l'existence légale. Le SIREN suffit en droit (R2143-9 [S1]) ; la candidature à un marché public est citée parmi les démarches qui ne nécessitent plus d'extrait [S7] | Greffe du tribunal de commerce ; extrait K pour l'entreprise individuelle, Kbis pour la personne morale [S7] | Gratuit pour le dirigeant sur https://monidenum.fr ; sinon Infogreffe, 3,06 € en envoi électronique [S7]. Justificatif RNE gratuit sur l'Annuaire des entreprises [S7] | « Dans la plupart des cas, l'extrait Kbis demandé doit dater de moins de 3 mois » [S7]. Mesuré : « moins de 3 mois » 15 fois, « moins de 6 mois » 4 fois | Date de délivrance, SIREN, dénomination, forme, siège, dirigeants, activité | Général | 16 % / 20 % |
| `urssaf` | Attestation de vigilance (Urssaf) | Prouver que les cotisations sociales sont déclarées et payées (R2143-7 [S1], L. 243-15 CSS [S4]) | Urssaf [S5] | Espace en ligne sur urssaf.fr [S6] | « Elle doit dater de moins de 6 mois » ; marchés d'au moins 5 000 € HT ; à renouveler tous les 6 mois pendant l'exécution [S5][S6]. Mesuré : « moins de 6 mois » 15 fois | Date de délivrance, SIREN, code de sécurité (contenu exact du document : à vérifier, urssaf.fr non lu) | Général | 25 % / 20 % |
| `fiscale` | Attestation de régularité fiscale | Prouver que les déclarations et paiements d'impôts sont à jour (R2143-7 [S1] ; IR, IS, TVA [S4]) | DGFiP [S5] | Espace professionnel impots.gouv.fr, « Consulter mon compte fiscal » puis « Attestation fiscale », pour une société à l'IS assujettie à la TVA ; formulaire 3666-SD par messagerie sécurisée pour les autres [S8][S9] | Pas de durée de validité écrite : elle « peut être obtenue tout au long de l'année », situation appréciée « au plus près du jour de la demande » [S8]. Mesuré : « moins de 6 mois » 6 fois, « année en cours » 4 fois | Date d'édition, SIREN, dénomination | Général | 24 % / 19 % |
| `travail_dissimule` | Pièces de l'article D. 8222-5 du code du travail | Obligation de vigilance du donneur d'ordre ; le candidat les produit « le cas échéant » (R2143-8 [S1]) | Le candidat (en pratique : attestation de vigilance et preuve d'immatriculation). Contenu exact de D. 8222-5 : à vérifier | Voir `urssaf` et `kbis` | Tous les 6 mois [S5] | Voir `urssaf` | Général | 8 % / 6 % |
| `lnte` | Liste nominative des salariés étrangers | Vérifier les autorisations de travail (D. 8254-2 [S10]) | Le candidat, à partir du registre unique du personnel : date d'embauche, nationalité, type et numéro du titre [S10] | Texte libre ; « néant » si aucun salarié concerné (usage : à vérifier) | Remise à la conclusion du contrat puis « tous les six mois, jusqu'à la fin de l'exécution du contrat » (D. 8254-4 [S11]) | Date du document | Général | 5 % / 3 % |
| `plateforme_attestations` | Dépôt sur une plateforme tierce (e-Attestations, Provigis) | Centraliser les attestations pendant l'exécution | Plateforme choisie par l'acheteur | Selon le marché : à vérifier au cas par cas | Tous les 6 mois (mesuré, 2 fois) | Sans objet | Général | 2 % / 2 % |
| `obligation_emploi_th` | Obligation d'emploi des travailleurs handicapés | Couverte par la déclaration sur l'honneur (R2143-3 [S1]) | Le candidat. Obligation à partir de 20 salariés, 6 % de l'effectif [S12]. Un certificat AGEFIPH figurait dans la version initiale de l'arrêté et n'apparaît plus dans le texte consolidé : à vérifier [S4] | Déclaration sur l'honneur | Par consultation | Sans objet | Général | 19 % / 18 % |
| `redressement` | Jugement de redressement judiciaire | Vérifier que l'entreprise est habilitée à poursuivre son activité : « il produit la copie du ou des jugements prononcés » (R2143-9 [S1]) | Tribunal de commerce | Greffe | Tant que la procédure dure. 92 % des occurrences sont conditionnelles (« si redressement ») | Date du jugement, durée du plan | Général | 20 % / 21 % |
| `pouvoir` | Pouvoir, délégation de signature | Prouver que le signataire peut engager l'entreprise | Le dirigeant | Texte libre signé ; inutile si le signataire est le représentant légal du Kbis (usage : à vérifier) | Jusqu'à révocation | Nom du délégant, du délégataire, date | Général | 24 % / 28 % |
| `rib` | RIB | Payer le titulaire | Banque | Espace bancaire | Tant que le compte existe | IBAN, titulaire | Général | 22 % / 19 % |
| `sanctions_russie` | Attestation de non-soumission aux sanctions (Russie) | Règlement (UE) 833/2014 cité par les libellés : à vérifier | Le candidat | Modèle fourni par l'acheteur | Par consultation | Sans objet (généré) | Général | 4 % / 5 % |
| `conflit_interets` | Déclaration d'absence de conflit d'intérêts | Indépendance vis-à-vis de tiers nommés par l'acheteur | Le candidat | Modèle fourni par l'acheteur | Par consultation | Sans objet | Général | 2 % / 4 % |
| `egalite_parite` | Égalité professionnelle | Non obligatoire dans les 3 occurrences | Le candidat | À vérifier | À vérifier | Sans objet | Général | 1 % / 1 % |
| *(non mesuré)* | Certificat de la caisse de congés payés du BTP | Prouver le versement régulier des cotisations de congés payés et de chômage intempéries (arrêté du 22 mars 2019, art. 2 III [S4]) | Caisse CIBTP de l'entreprise, si elle est à jour de ses déclarations et cotisations [S13] | Espace sécurisé de la caisse ; l'acheteur vérifie l'authenticité en ligne ou par l'API Entreprise [S13] | À vérifier | Date, identifiant de vérification | **BTP** | 2 occurrences seulement, rangées avec `urssaf` par le script (motif « congés payés ») ; à isoler au chantier coffre |

### 2.3 Assurances (coffre)

| Type | Nom usuel | À quoi elle sert pour l'acheteur | Qui la délivre | Où l'obtenir | Validité habituelle | Lecture automatique | Périmètre | BTP / Tous |
|---|---|---|---|---|---|---|---|---|
| `assurance_rc` | Attestation d'assurance responsabilité civile professionnelle | « Preuve d'une assurance des risques professionnels pertinents » (arrêté du 22 mars 2019, art. 2 I [S3]) | Assureur de l'entreprise | Espace client de l'assureur ou courtier | Période indiquée sur l'attestation (annuelle en pratique : à vérifier). Mesuré : « en cours de validité » 71 fois | Assureur, numéro de contrat, période de validité, activités garanties, plafonds | Général | 64 % / 62 % |
| `decennale` | Attestation d'assurance décennale | Obligation du constructeur (Code civil 1792 et suivants, Code des assurances L241-1 et L241-2) ; elle « doit être jointe aux devis et à la facture » ; défaut puni de 6 mois d'emprisonnement et/ou 75 000 € d'amende [S14] | Assureur | Espace client de l'assureur | Période de validité portée sur l'attestation ; le modèle prévoit dénomination, SIRET, assureur, numéro de contrat, période de validité, activités, étendue géographique, coût des opérations [S15] | Les mentions du modèle [S15] : période de validité, activités garanties, montants, SIRET | **BTP** | 42 % / 18 % |

### 2.4 Capacité financière (profil, pièces en option)

| Type | Nom usuel | À quoi elle sert pour l'acheteur | Qui la délivre | Où l'obtenir | Validité habituelle | Lecture automatique | Périmètre | BTP / Tous |
|---|---|---|---|---|---|---|---|---|
| `ca_bilans` | Chiffre d'affaires, bilans | Chiffre d'affaires global et du domaine « au maximum sur les trois derniers exercices disponibles » ; bilans « concernant les trois dernières années » (art. 2 I [S3]). Seuil plafonné à 1,5 fois le montant estimé (R2142-7 [S2]) | Le candidat (déclaration) ; expert-comptable pour les bilans | Liasse fiscale, comptes annuels. L'API Recherche d'entreprises expose `finances` (`ca`, `resultat_net` par année) quand les comptes sont publiés [S16] | 3 derniers exercices (mesuré : 29 fois sur 31). Entreprise récente ou empêchée : « tout autre moyen considéré comme approprié par l'acheteur » (art. 2 II [S3]) | Exercice, chiffre d'affaires, résultat, capitaux propres | Général | 58 % / 70 % |
| `declaration_bancaire` | Déclaration de banque | « Déclarations appropriées de banques » (art. 2 I [S3]) ; alternative à l'attestation d'assurance dans le même alinéa | Banque | Chargé de clientèle | À vérifier | Date, banque | Général | 12 % / 19 % |

### 2.5 Capacité technique et professionnelle (profil, pièces en option)

| Type | Nom usuel | À quoi elle sert pour l'acheteur | Qui la délivre | Où l'obtenir | Validité habituelle | Lecture automatique | Périmètre | BTP / Tous |
|---|---|---|---|---|---|---|---|---|
| `references` | Références de chantiers | Travaux : liste « au cours des cinq dernières années » ; services et fournitures : « trois dernières années » ; l'acheteur peut accepter plus ancien (art. 3 I 1° et 2° [S3]) | Le candidat | Profil Tendia (section Chantiers réalisés) | Glissante : 5 ans en travaux. Mesuré tous secteurs : 3 ans dans 103 marchés, 5 ans dans 38 | Sans objet (saisi) ; depuis une attestation : maître d'ouvrage, montant, dates, lieu | Général, règle 5 ans propre aux travaux | 64 % / 76 % |
| `bonne_execution` | Attestation de bonne exécution | « Pour les travaux les plus importants » (art. 3 I 1° [S3]) | Maître d'ouvrage ou maître d'œuvre du chantier | À demander à la réception du chantier (modèle : à vérifier) | Liée à la période de référence (5 ans) | Maître d'ouvrage, objet, montant, dates, lieu, mention de bonne fin, signataire | **BTP** surtout | 30 % / 25 % |
| `effectifs` | Déclaration des effectifs | Effectifs moyens annuels et encadrement « pendant les trois dernières années » (art. 3 I 3° [S3]) | Le candidat | Profil Tendia ; l'API Recherche d'entreprises donne une tranche (`tranche_effectif_salarie`) [S16] | 3 dernières années (mesuré : 188 fois sur 190) | Sans objet (saisi) | Général | 48 % / 54 % |
| `moyens_materiels` | Outillage, matériel, équipement | Art. 3 I 6° [S3] | Le candidat | Profil Tendia (section Matériel) | À tenir à jour | Sans objet (saisi) | Général | 38 % / 41 % |
| `titres_etudes` | Titres d'études et professionnels | Art. 3 I 4° [S3] | Le candidat ; organismes de formation pour les diplômes | Profil Tendia (section Équipe) | Sans expiration | Nom, diplôme, année | Général | 15 % / 18 % |
| `cv_moyens_humains` | CV, équipe | Le plus souvent dans le mémoire technique ; en candidature dans 16 marchés | Le candidat | Profil Tendia (section Équipe) | À tenir à jour | Nom, fonction, expérience, habilitations | Général | 16 % / 19 % |
| `presentation_entreprise` | Fiche de renseignements, présentation | Identifier et situer l'entreprise | Le candidat | Générée depuis le profil | Par consultation | Sans objet (généré) | Général | 8 % / 11 % |
| `capacites_generique` | Renvoi générique aux capacités | Aucune pièce nommée : le brief renvoie au règlement de consultation | Sans objet | Sans objet | Sans objet | Sans objet | Général | 18 % / 14 % |

### 2.6 Qualifications et certifications (coffre)

Règle commune : les certificats de qualification professionnelle sont une preuve admise parmi d'autres (art. 3 I 12° [S3]) ; les certificats équivalents d'autres États membres sont acceptés, et « d'autres mesures équivalentes » quand le certificat ne peut pas être obtenu dans les délais (art. 4 [S3]). Tous secteurs, 14 des 38 pièces de ce type sont marquées facultatives (6 sur 18 en BTP).

| Type | Nom usuel | À quoi elle sert pour l'acheteur | Qui la délivre | Où l'obtenir | Validité habituelle | Lecture automatique | Périmètre | BTP / Tous |
|---|---|---|---|---|---|---|---|---|
| `qualibat` | Certificat Qualibat | Prouver la compétence par métier (code à 4 chiffres) | Qualibat | https://www.qualibat.com/processus-qualification ; vérification dans l'annuaire en ligne Qualibat [S17] | Qualification « limitée à quatre ans », avec preuve annuelle du maintien des exigences ; nouveau dossier demandé huit mois avant l'échéance [S17][S18]. Durée du certificat lui-même : à vérifier | Codes de qualification, dates de validité, SIRET (contenu exact du certificat : à vérifier) | **BTP** | 19 % / 7 % |
| `rge` | Mention RGE | Travaux de rénovation énergétique | Organismes de qualification (Qualibat, Qualit'EnR, Qualifelec) ou de certification (Certibat, Cerqual) [S19] ; mention attribuée par établissement [S17] | Annuaire : https://france-renov.gouv.fr/annuaires-professionnels/artisan-rge-architecte [S20] ; l'API Recherche d'entreprises expose `liste_rge` par établissement [S16] | « Délivré pour une période de 4 ans avec un suivi annuel » [S19] | Domaines de travaux, organisme, dates | **BTP** | 6 % / 3 % |
| `mase` | Certification MASE | Sécurité, santé, environnement (sites industriels) | Association MASE locale, sur décision d'un comité de pilotage [S21] | https://mase-asso.fr | « Accordée pour une durée de 1 ou de 3 ans » ; « 1 an » pas plus de deux fois consécutives [S21] | Périmètre, dates | BTP et industrie | 0 % / 0 % (aucune occurrence) |
| `iso` | Certification ISO (9001, 14001, 45001) | Certificats de qualité et de gestion environnementale (art. 4 [S3]) | Organisme certificateur | Organisme certificateur de l'entreprise | À vérifier | Norme, périmètre, dates | Général | 2 % / 4 % |
| `qualifelec` | Qualifelec | Compétence en génie électrique | Qualifelec [S22] | https://www.qualifelec.fr ; recherche d'entreprise : https://data.qualifelec.fr/recherche/ (lien relevé, non lu) | À vérifier | Qualifications, dates | **BTP** | 6 % / 3 % |
| `fntp` | Carte professionnelle TP et identifications professionnelles | Savoir-faire en travaux publics, sur attestations de travaux signées par des maîtres d'ouvrage ou d'œuvre [S23] | FNTP, aux entreprises adhérentes en règle [S23] | https://www.fntp.fr/carte-professionnelle-ip/ [S23] | À vérifier | Numéros d'identification professionnelle | **BTP** (travaux publics) | 5 % / 2 % |
| `opqibi` | OPQIBI, OPQTECC, OPQCM | Qualification d'ingénierie (lots de maîtrise d'œuvre) | Organismes de qualification : à vérifier | À vérifier | À vérifier | Codes | Ingénierie | 5 % / 3 % |
| `amiante` | Certification amiante (sous-section 3), formation (sous-section 4) | Retrait ou encapsulage : « les entreprises doivent être certifiées par un organisme certificateur » accrédité Cofrac (R. 4412-129 du code du travail) ; sous-section 4 : formation adaptée avant la première intervention [S24] | Organisme certificateur accrédité (SS3) ; organisme de formation (SS4) | À vérifier (travail-emploi.gouv.fr non lisible) | À vérifier | Périmètre, dates, noms des salariés formés | **BTP** | 15 % / 5 % |
| `habilitations_personnel` | Habilitations du personnel (AIPR, électrique, CACES, SST) | Prouver que les intervenants sont autorisés | AIPR : l'employeur, sur un mode de preuve (CACES, diplôme BTP de moins de 5 ans, attestation de compétences par QCM de moins de 5 ans) [S25]. Autres habilitations : à vérifier | AIPR : https://www.reseaux-et-canalisations.ineris.fr/gu-presentation/construire-sans-detruire/aipr-et-examen-qcm.html [S25] | AIPR : au plus la validité de l'attestation de compétences, « elle-même de 5 ans » [S25]. Autres : à vérifier | Nom du salarié, type, date de fin | **BTP** surtout | 35 % / 28 % |
| `certificats_qualification` | Certificats de qualification sans label nommé | Formule générique de l'arrêté (art. 3 I 12° [S3]) | Tout organisme indépendant | Voir `qualibat`, `qualifelec`, `fntp` | Selon le certificat | Selon le certificat | Général | 25 % / 19 % |
| `labels_divers` | Autres labels nommés (Qualipaysage, Label PG, CONSUEL, FSC, PEFC…) | Variable | Variable | À vérifier au cas par cas | À vérifier | Nom du label, dates | Général | 32 % / 25 % |
| `autorisation_exercer` | Autorisation d'exercer (licence, agrément, carte professionnelle, ordre) | Aptitude à exercer l'activité | Variable ; presque absent du BTP | À vérifier au cas par cas | Mesuré : « en cours de validité » 17 fois | Numéro, dates | Autres secteurs | 10 % / 28 % |

## 3. Pièces de l'offre et de l'exécution (hors coffre)

Propres à chaque marché : elles ne se déposent pas une fois pour toutes. Elles sont listées pour que l'écran « Mon entreprise » ne les réclame pas au dirigeant.

| Type | Nom usuel | Produit par | BTP / Tous |
|---|---|---|---|
| `prix` | BPU, DPGF, DQE | L'entreprise, sur le cadre de l'acheteur | 91 % / 87 % |
| `memoire_technique` | Mémoire technique, cadre de réponse | Tendia (module mémoire) à partir du profil | 89 % / 89 % |
| `ae` | Acte d'engagement (AE, ATTRI1) | Tendia à partir du profil ; formulaires d'attribution DAJ (page non lue, 403) | 85 % / 83 % |
| `visite` | Attestation de visite | Remise par l'acheteur lors de la visite | 39 % / 22 % |
| `environnement_dechets` | SOGED, mesures environnementales (art. 3 I 9° [S3]) | L'entreprise, par marché ; trame réutilisable | 32 % / 23 % |
| `exigence_execution` | Conditions d'exécution (délais de remise après notification, astreinte) | Sans pièce au dépôt | 31 % / 21 % |
| `pieces_marche_signees` | CCAP, CCTP, règlement à accepter ou signer | Fournis par l'acheteur | 25 % / 26 % |
| `planning` | Planning, calendrier | L'entreprise, par marché | 25 % / 14 % |
| `fiches_techniques` | Fiches techniques, échantillons (art. 3 I 10° [S3]) | Fournisseurs | 24 % / 15 % |
| `insertion` | Engagement d'insertion | L'entreprise, sur le modèle de l'acheteur | 16 % / 9 % |
| `securite_qualite` | PPSPS, PAQ, plan de prévention | L'entreprise, après attribution le plus souvent | 15 % / 11 % |
| `donnees_confidentialite` | RGPD, confidentialité | Modèle de l'acheteur | 10 % / 13 % |
| `variantes_pse` | Variantes, prestations supplémentaires | L'entreprise | 8 % / 4 % |
| `acces_site` | Liste nominative, pièces d'identité pour l'accès au site | L'entreprise, avant intervention | 5 % / 6 % |
| `signature_depot` | Signature électronique, copie de sauvegarde | Prestataire de certificat : à vérifier | 2 % / 2 % |

## 4. Minimum vital : ce qui couvre 80 % des pièces de candidature BTP

Base : 437 pièces de phase candidature dans 80 briefs BTP (`exigences_couverture_candidature_btp.csv`). Le seuil de 80 % est atteint au 21e type. Regroupés par ce que le dirigeant doit faire :

| Ce que fait le dirigeant | Types couverts | Temps estimé (hypothèse à tester en démo) |
|---|---|---|
| **Rien : Tendia génère** depuis le profil | DC1, DC2, DUME, déclaration sur l'honneur (dont obligation d'emploi), DC4, pièces de groupement | 0 min par marché une fois le profil rempli |
| **Répondre à 4 blocs de questions** dans son profil | Chiffre d'affaires des 3 derniers exercices ; effectifs des 3 dernières années ; matériel ; diplômes et titres de l'encadrement | 15 min, une fois par an |
| **Saisir ses chantiers** | Références des 5 dernières années (montant, dates, lieu, maître d'ouvrage) | 5 min par chantier ; 3 chantiers couvrent le nombre minimum demandé dans 14 des 18 marchés qui en fixent un |
| **Déposer 7 documents** | Attestation RC professionnelle ; attestation décennale ; Kbis ; pouvoir (si le signataire n'est pas le dirigeant) ; attestations de bonne exécution ; certificats de qualification (Qualibat ou équivalent) ; habilitations du personnel (AIPR) | 10 min s'ils sont déjà sur l'ordinateur |
| **Déposer seulement si concerné** | Jugement de redressement judiciaire ; déclaration de banque | Sans objet pour la plupart |

Trois pièces sont hors du seuil de 80 % mais dues dès que l'entreprise est retenue [S5] : attestation de vigilance Urssaf, attestation de régularité fiscale, certificat de la caisse de congés payés. Elles expirent le plus vite (6 mois) : ce sont elles qui justifient les alertes du coffre.

| Rang d'usage | Pièce à déposer | Marchés BTP qui la citent | Expire | Gratuite, en ligne |
|---|---|---|---|---|
| 1 | Attestation RC professionnelle | 64 % | Selon l'attestation | Oui (assureur) |
| 2 | Attestation décennale | 42 % | Selon l'attestation [S15] | Oui (assureur) |
| 3 | Habilitations du personnel (AIPR…) | 35 % | AIPR : 5 ans au plus [S25] | Sans objet |
| 4 | Attestations de bonne exécution | 30 % | Utiles 5 ans [S3] | À demander au maître d'ouvrage |
| 5 | Attestation de vigilance Urssaf | 25 % | 6 mois [S6] | Oui |
| 6 | Attestation de régularité fiscale | 24 % | Exigence du marché | Oui [S8] |
| 7 | Pouvoir | 24 % | Jusqu'à révocation | Sans objet |
| 8 | RIB | 22 % | Non | Oui |
| 9 | Certificat Qualibat | 19 % | Qualification 4 ans, suivi annuel [S17] | Payant (ordre de 250 € par an pour moins de 5 salariés [S18]) |
| 10 | Kbis | 16 % | 3 mois en pratique [S7] | Oui pour le dirigeant [S7] |
| 11 | Certification amiante | 15 % | À vérifier | Non |
| 12 | Mention RGE | 6 % | 4 ans [S19] | Vérifiable par SIRET [S16] |

## 5. Sources consultées le 2026-11-11

| # | Source | URL | Version affichée |
|---|---|---|---|
| S1 | Code de la commande publique, articles R2143-1 à R2143-16 | https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000037701019/LEGISCTA000037724070/ | En vigueur au 11/11/2026 |
| S2 | Code de la commande publique, article R2142-7 | https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000053218157 | En vigueur depuis le 2026-01-01 (décret 2025-1383) |
| S3 | Arrêté du 22 mars 2019 fixant la liste des renseignements et des documents pouvant être demandés aux candidats (NOR ECOM1830221A) | https://www.legifrance.gouv.fr/loda/id/JORFTEXT000038318577 | En vigueur au 11/11/2026 |
| S4 | Arrêté du 22 mars 2019 fixant la liste des impôts, taxes, contributions ou cotisations sociales donnant lieu à certificats | https://www.legifrance.gouv.fr/loda/id/JORFTEXT000038318472/ | En vigueur, mise à jour du 2021-07-01 |
| S5 | Service-public, attestations fiscale et de vigilance dans un marché public | https://entreprendre.service-public.gouv.fr/vosdroits/F23384 | Vérifié le 17 juillet 2026 |
| S6 | Service-public, attestation de vigilance | https://entreprendre.service-public.gouv.fr/vosdroits/F31422 | Vérifié le 6 juillet 2026 |
| S7 | Service-public, extrait K ou Kbis | https://entreprendre.service-public.gouv.fr/vosdroits/F21000 | Vérifié le 3 avril 2026 |
| S8 | impots.gouv.fr, obtenir une attestation de régularité fiscale | https://www.impots.gouv.fr/professionnel/questions/comment-obtenir-une-attestation-de-regularite-fiscale | Modifiée le 14/10/2026 |
| S9 | impots.gouv.fr, formulaire 3666-SD | https://www.impots.gouv.fr/formulaire/3666-sd/attestation-de-regularite-fiscale | Millésime 2026 |
| S10 | Code du travail, article D8254-2 | https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000018520574 | En vigueur au 11/11/2026 |
| S11 | Code du travail, article D8254-4 | https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000018520570 | En vigueur au 11/11/2026 |
| S12 | Service-public, obligation d'emploi des travailleurs handicapés | https://entreprendre.service-public.gouv.fr/vosdroits/F23149 | Vérifié le 13 mars 2026 |
| S13 | Réseau CIBTP, attestations de marchés publics | https://www.cibtp.fr/actualite-/-presse/actualites/actualite/attestations-de-marches-publics-le-reseau-cibtp-rejoint-le-portail-api-entreprise | Article du 2024-12-05 |
| S14 | Service-public, garantie décennale | https://www.service-public.gouv.fr/particuliers/vosdroits/F2034 | Vérifié le 10 avril 2026 |
| S15 | Service-public, modèle d'attestation d'assurance décennale | https://entreprendre.service-public.gouv.fr/vosdroits/R44868 | Vérifié le 25 juin 2021 (ancien) |
| S16 | API Recherche d'entreprises, description OpenAPI | https://recherche-entreprises.api.gouv.fr/openapi.json | Lue partiellement (fichier tronqué à la lecture) |
| S17 | Qualibat, foire aux questions | https://www.qualibat.com/faq | Sans date |
| S18 | Qualibat, processus de qualification | https://www.qualibat.com/processus-qualification | Sans date |
| S19 | Ministère de la transition écologique, label RGE | https://www.ecologie.gouv.fr/politiques-publiques/label-reconnu-garant-lenvironnement-rge | Mise à jour du 11 juin 2025 |
| S20 | France Rénov', annuaire des professionnels RGE | https://france-renov.gouv.fr/annuaires-professionnels/artisan-rge-architecte | Sans date |
| S21 | MASE, référentiel 2024, § 3.2 Certification | https://mase-asso.fr/wp-content/uploads/2024/09/Referentiel-MASE-2024-V24092024-PORTRAIT.pdf | Version 7.0, 2024 |
| S22 | Qualifelec | https://www.qualifelec.fr/ | Sans date |
| S23 | FNTP, carte professionnelle et identifications professionnelles | https://www.fntp.fr/carte-professionnelle-ip/ | Sans date |
| S24 | INRS, amiante, réglementation | https://www.inrs.fr/risques/amiante/reglementation.html | Mis à jour le 06/10/2022 |
| S25 | INERIS, AIPR et examen QCM | https://www.reseaux-et-canalisations.ineris.fr/gu-presentation/construire-sans-detruire/aipr-et-examen-qcm.html | Sans date |

## 6. À vérifier (non lu sur une source officielle)

| Point | Pourquoi | Où regarder |
|---|---|---|
| Versions en vigueur et caractère facultatif des DC1, DC2, DC4, ATTRI1 | economie.gouv.fr refuse la lecture automatique (403) | https://www.economie.gouv.fr/daj/les-formulaires-de-declaration-du-candidat |
| Service de saisie du DUME | Page vide à la lecture | https://dume.chorus-pro.gouv.fr/ |
| Contenu exact de l'attestation de vigilance (code de sécurité, effectif, masse salariale) | urssaf.fr a coupé la connexion deux fois | https://www.urssaf.fr/accueil/attestation-vigilance.html |
| Conditions du Kbis gratuit MonIdenum | infogreffe.fr refuse la lecture (403) ; le fait est confirmé par service-public [S7] | https://www.infogreffe.fr/services/monidenum |
| Qui doit produire les certificats et quand (article R2144-4) | Article hors de la section lue | Légifrance, R2144-1 à R2144-7 |
| Contenu de l'article D. 8222-5 du code du travail | Non lu | Légifrance |
| Certificat AGEFIPH : supprimé ou non de l'arrêté | Absent du texte consolidé extrait, sans mention d'abrogation | [S4], texte complet |
| Durée du certificat Qualibat, contenu du certificat, qualification probatoire de 2 ans | Absent des deux pages lues | Règlement général Qualibat |
| Durée de validité Qualifelec, FNTP, ISO, OPQIBI, certification amiante | Absent des pages lues | Sites des organismes |
| Carte d'identification professionnelle du BTP | Page réduite à son titre | https://www.cartebtp.fr/ |
| Seuil de paiement direct et moment de déclaration du sous-traitant | Page service-public introuvable (404) | Code de la commande publique, R2193-1 et suivants |
| Schéma complet de l'API Recherche d'entreprises (unité légale, bloc `complements`) | Fichier tronqué à la lecture | https://recherche-entreprises.api.gouv.fr/docs/ |
