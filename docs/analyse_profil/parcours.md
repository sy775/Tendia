# Parcours « Mon entreprise » : de l'arrivée au dossier d'entreprise complet

Personnage : dirigeant d'une PME du bâtiment, 55 ans, peu à l'aise avec l'informatique, seul devant l'écran, parfois sur son téléphone. Entreprise des maquettes : le profil fictif `demo_btp` (Bâti Confiance Construction, Le Mans, 84 salariés).

Sources : audit du 2026-11-10 (`docs/audit_design/2026-11-10_profil.md`), fréquences de `exigences_frequence.md`, règles de `referentiel_pieces.md`. Maquettes : `maquettes/*.html`, captures 1440 et 390 px dans `maquettes/captures/`. Les durées sont des hypothèses à mesurer en démo.

## 1. Aujourd'hui : ce qui bloque (audit du 2026-11-10)

| # | Blocage constaté | Gravité à l'audit | Réponse dans le parcours cible |
|---|---|---|---|
| 1 | 4 clics avant la première saisie utile ; aucun ordre de remplissage | majeur | Une action « À faire maintenant » en tête de la vue d'ensemble (écran 02) |
| 2 | Aucun indicateur de ce qui manque ni de ce que chaque champ apporte | majeur | Avancement par rubrique (02) ; « demandé dans N marchés » sur chaque document et chaque question (04, 05) |
| 3 | Aucun emplacement pour les pièces : ni Kbis, ni attestations, ni dates d'expiration | absent (§5.7 du rapport d'architecture) | Dépôt en vrac (03), liste par état (04), alertes (02) |
| 4 | Réponses oui/non aux exigences invisibles depuis le profil | majeur | Rubrique Questions (05), classée par marchés concernés |
| 5 | Vocabulaire interne : « Profil organisme », « matching », « presets », « Activer », identifiants techniques | mineur, mais partout | Table de vocabulaire (§5) ; plus de bibliothèque de profils pour un client |
| 6 | Plusieurs profils pour une seule entreprise, trois cartes identiques | majeur | Une entreprise, une page. La bibliothèque devient un outil interne de démonstration |
| 7 | Pastilles vertes dès qu'un bloc existe, même vide | majeur | État par critère utile : « Terminé », « Il en manque 1 », « À compléter » |
| 8 | Inutilisable à 390 px (page de 837 px de large) | majeur | Maquettes sans défilement horizontal à 390 px (mesuré : `scrollWidth` = 390 sur les 7 écrans) |
| 9 | Montants sans séparateur, dates ISO | mineur | « 14 500 000 € », « 31 décembre 2026 » |
| 10 | Pas d'alerte en quittant sans enregistrer | mineur | Enregistrement au fil de l'eau, annoncé dès le premier écran |
| 11 | Saisie de l'identité à la main, SIREN vide sur le profil réel | constat §5.4 | Préremplissage par SIRET (01) |
| 12 | Trois listes qui se recouvrent (domaines, corps de métier, types d'ouvrages) | majeur pour la compréhension | Hors périmètre de ces maquettes : les métiers sont déduits des chantiers saisis (06) et du Qualibat lu (03). À traiter au chantier matching |

## 2. Le parcours cible, écran par écran

| Écran | Maquette | Ce qu'il voit | Ce qu'il fait | Durée | Ce que ça débloque |
|---|---|---|---|---|---|
| 1. Premier accès | `01_premier_acces.html` | Trois étapes numérotées avec leur durée ; à droite : ce qu'il y gagne, où vont ses documents, un numéro de téléphone | Tape son SIRET, confirme « Oui, c'est mon entreprise » | 1 min | Identité complète sans saisie : de quoi remplir l'en-tête du DC1 et du DC2 (71 % et 64 % des marchés BTP) |
| 2. Dépôt | `03_depot_documents.html` | Une zone de dépôt, puis la liste des fichiers reçus, chacun avec ce qui a été reconnu et lu | Glisse ses fichiers en vrac, confirme ou corrige le type, enregistre | 10 min | Les pièces reconnues sont prêtes à être jointes ; les dates d'expiration alimentent les alertes |
| 3. Vue d'ensemble | `02_vue_ensemble.html` | Alerte s'il y a des documents périmés ; une seule action « À faire maintenant » ; l'avancement des 5 rubriques ; ce que Tendia sait déjà faire | Suit l'action proposée, ou choisit une rubrique | 30 s de lecture | Sait où il en est et quoi faire ensuite (objectif 3) |
| 4. Mes documents | `04_mes_documents.html` | Quatre groupes : à renouveler, expirent bientôt, manquants (du plus utile au moins utile), valables | Clique sur le lien officiel d'obtention, ou dépose | 2 min par document | Chaque ligne dit dans combien de marchés la pièce est demandée |
| 5. Questions | `05_questions.html` | Les questions restantes, classées par marchés concernés ; puis ses réponses, modifiables | Répond Oui, Non ou Je ne sais pas | 3 min pour 8 questions | Chaque réponse règle une pièce (pouvoir, liste des salariés étrangers, jugement, DC4) ou ouvre des marchés (groupement, insertion, amiante) |
| 6. Chantiers réalisés | `06_chantiers.html` | Ses chantiers, leur date limite d'utilisation (5 ans), ce qui manque à chacun ; un formulaire court | Complète, ajoute un troisième chantier, joint l'attestation du client | 5 min par chantier | Références demandées dans 64 % des marchés BTP ; attestations de bonne exécution dans 30 % |
| 7. Chiffres, équipe, matériel | `07_chiffres_equipe_materiel.html` | Chiffre d'affaires et effectifs sur 3 ans avec leur origine ; encadrement ; matériel | Corrige un chiffre, ajoute son conducteur de travaux, précise des quantités | 10 min la première fois, 5 min par an | Chiffre d'affaires 58 %, effectifs 48 %, matériel 38 % des marchés BTP |

Ordre imposé : aucun. L'ordre proposé (SIRET, documents, questions, chantiers, chiffres) va du moins coûteux au plus coûteux pour le dirigeant, et de ce qui débloque le plus à ce qui débloque le moins.

## 3. Points de conception, un par exigence

### 3.1 Premier accès et état vide utile

| Choix | Raison |
|---|---|
| Le premier écran demande un SIRET, pas un formulaire | L'identité est la seule rubrique qu'une source publique remplit seule (API Recherche d'entreprises : dénomination, siège, activité, tranche d'effectif, dirigeants, et `liste_rge`) |
| Chaque étape affiche sa durée | Le dirigeant décide de commencer s'il sait quand il aura fini |
| L'état vide liste les quatre documents les plus demandés, avec leur fréquence en clair (« 2 marchés sur 3 ») | Un état vide qui dit quoi préparer vaut mieux qu'une zone de dépôt muette |
| « Il vous en manque ? Ce n'est pas bloquant » | Sans les pièces, il peut tout de même voir les marchés |
| Encadré « Vos documents restent chez vous » | Première objection attendue. Le texte dépend de la décision d'hébergement (synthèse, question 1) |
| Numéro de téléphone | Pour ce public, l'aide humaine fait partie du produit. À confirmer par Younes |

### 3.2 Dépôt de pièces

| Cas | Comportement maquetté | Règle |
|---|---|---|
| Dépôt multiple | Glisser-déposer, bouton « Choisir des fichiers », bouton « Prendre une photo » | Le bouton fait la même chose que le glisser-déposer : certains ne glissent jamais |
| Type reconnu, date lue | « Reconnu » + ce qui a été lu, en gras la date de fin de validité | On montre toujours ce qui a été lu, jamais un simple « OK » |
| Type incertain | « À vérifier » : « Nous pensons avoir lu… Est-ce exact ? » + liste déroulante de correction | Confiance basse : la confirmation humaine est demandée et enregistrée (provenance) |
| Correction manuelle | Lien « Ce n'est pas le bon type » sur chaque fichier reconnu ; liste déroulante en mots du métier | La liste vient du référentiel (une douzaine de types pour le BTP), pas des 57 types du script |
| Doublon | « C'est le même fichier que… Nous ne l'avons pas ajouté une seconde fois. Vous n'avez rien à faire. » | Détection par empreinte du fichier (SHA-256). Même type mais fichier différent : la nouvelle pièce remplace l'ancienne, qui reste en historique |
| PDF scanné illisible | « Nous n'arrivons pas à lire ce document » + le garder en indiquant son type et sa date, ou le remplacer par une photo nette | Jamais de rejet sec : la saisie manuelle du type et de la date suffit à faire fonctionner les alertes |
| Pièce expirée | « Expirée » + date + raison (« valable 6 mois ») + lien officiel pour la renouveler | La pièce est conservée pour mémoire, jamais jointe à un dossier |
| Kbis de plus de 3 mois | « Trop ancien » plutôt qu'« expiré » | Un Kbis n'expire pas ; c'est l'exigence des acheteurs qui le périme |
| Mauvais type de fichier, fichier lourd | « Refusé » + raison chiffrée (148 Mo pour 20 Mo acceptés) + ce qui se dépose ici | La limite de 20 Mo est une proposition |
| Enregistrement | « Enregistrer les 3 documents prêts » ; les autres restent dans la liste | Rien n'est perdu si un fichier pose problème |

### 3.3 Statut par pièce

| Statut | Libellé affiché | Signe (en plus de la couleur) | Règle de calcul |
|---|---|---|---|
| Valide | « Valable jusqu'au 30 juin 2027 » | Rond plein | Date de fin lue ou calculée, à plus de 60 jours |
| Expire bientôt | « Expire dans 50 jours » | Triangle | Moins de 60 jours (seuil proposé ; 30 jours pour les attestations de 6 mois) |
| Expirée | « Expirée le 4 novembre 2026 » ou « Trop ancien (12 mars 2026) » | Carré | Date de fin dépassée, ou ancienneté supérieure à l'exigence habituelle du type |
| Manquante | « Manquant » | Rond vide | Type du référentiel sans pièce, sauf si une réponse le rend inutile |
| Pas nécessaire | « Pas nécessaire : vous signez vous-même » | Rangé avec les pièces valables | Une réponse oui/non a réglé la pièce |
| À vérifier | « À vérifier » | Losange | Lecture automatique de confiance basse, en attente de confirmation |

La validité se juge deux fois : en général (écran 04) et marché par marché (une attestation valable aujourd'hui peut expirer avant la date limite de dépôt). Le second contrôle appartient à la fiche marché et au dossier (chantier 3).

### 3.4 « Débloque N marchés »

| Élément | Formule affichée | Calcul | Limite |
|---|---|---|---|
| Fréquence | « Demandée dans 2 marchés de travaux sur 3 » | Part des briefs BTP portant le type (`exigences_types.csv`, colonne `pct_btp`), arrondie à une fraction simple | 80 briefs BTP, surtout de juin 2026 |
| Volume | « soit environ 24 de vos 38 marchés » | Part × marchés ouverts correspondant à l'entreprise, arrondi à l'unité (une seule règle d'arrondi) | Estimation tant que les marchés n'ont pas tous un brief ; « environ » obligatoire. Le volume national (part × 509 marchés BTP actifs, colonne `marches_btp_actifs_estimes`) n'est pas affiché : l'audit des maquettes a montré qu'il se lit « je rate 325 marchés » |
| Cible | Compte exact, filtré sur les métiers et les départements de l'entreprise | Exigences typées de chaque brief × réponses et pièces du profil | Suppose le typage des exigences à l'extraction et le matching fiable (chantiers B et 7) |

Volumes nationaux correspondants, pour mémoire (estimation sur 509 marchés BTP actifs, non affichés) : assurance RC 324, sous-traitance 254, décennale 216, habilitations 178, bonne exécution 153, Urssaf 127, fiscale 121, pouvoir 121, groupement 102, redressement 102, Qualibat 95, Kbis 83, insertion 83, amiante 76, RGE 32, salariés étrangers 25.

« Débloque » est réservé aux cas où la pièce ou la réponse conditionne la candidature. Pour une pièce due seulement par l'entreprise retenue (Urssaf, fiscale), les maquettes écrivent « demandée dans », pas « débloque ».

### 3.5 Questions oui/non d'éligibilité

| Question (libellé maquette) | Type mesuré | Marchés BTP | Effet de la réponse |
|---|---|---|---|
| Acceptez-vous de confier une partie des travaux à un sous-traitant ? | `dc4` | 50 % | Oui : DC4 préparé par marché |
| Vos salariés interviennent-ils près de réseaux enterrés ou aériens ? | `habilitations_personnel` | 35 % | Oui : demande des AIPR dans la rubrique équipe |
| Est-ce vous, le dirigeant, qui signez les candidatures ? | `pouvoir` | 24 % | Oui : aucun pouvoir à fournir |
| Répondez-vous parfois en groupement ? | `groupement` | 20 % | Oui : marchés au-dessus de la capacité seule proposés |
| Votre entreprise est-elle en redressement judiciaire ? | `redressement` | 20 % | Non : aucune pièce ; oui : jugement à déposer |
| *(pas de question)* Effectif de 20 salariés ou plus | `obligation_emploi_th` | 19 % | Déduit de l'effectif connu (84 salariés) et affiché comme un fait, avec un lien « Corriger » |
| Pouvez-vous réserver des heures à des personnes en insertion ? | `insertion` | 16 % | Oui : engagement préparé |
| Vos équipes sont-elles formées aux interventions sur matériaux amiantés ? | `amiante` | 15 % | Oui : attestations demandées ; non : marchés concernés signalés |
| Employez-vous des salariés étrangers soumis à autorisation de travail ? | `lnte` | 5 % | Non : mention « néant » |

Règles : trois réponses possibles (Oui, Non, Je ne sais pas), « Je ne sais pas » restant distinct de « Non » (état « inconnu » demandé par le chantier 7), sauf pour les questions de fait que le dirigeant connaît forcément (redressement, signataire) ; questions sans réponse en premier, classées par marchés concernés ; conséquence de chaque réponse écrite sous la question (« Oui : … Non : … ») ; une question n'est pas posée quand le profil donne déjà la réponse ; l'appui enregistre aussitôt, et c'est dit en tête de page ; réponses déjà données modifiables au même endroit. Les questions propres à un marché (visite obligatoire, chiffre d'affaires minimum de ce marché) restent sur la fiche marché et se reportent ici quand elles reviennent.

### 3.6 Références de chantiers

| Choix | Raison (mesure) |
|---|---|
| Objectif affiché : 3 chantiers | Quand un nombre minimum est fixé (18 marchés), il est de 3 dans 8 cas et de 3 ou moins dans 14 |
| « Utilisable jusqu'à fin 2027 » sur chaque chantier | Liste des travaux « au cours des cinq dernières années » (arrêté du 22 mars 2019, art. 3) ; un chantier livré en 2022 sort de la fenêtre fin 2027 |
| 6 champs, dont 2 facultatifs en pratique | Montant, date, lieu, client : ce que demandent les libellés (« montant, date, lieu ») |
| Métiers en cases à cocher, limités à ceux de l'entreprise | L'audit relève la saisie des corps d'état en codes (`gros_oeuvre`) |
| « Le bâtiment était-il occupé ? » | « Site occupé » est un critère récurrent des mémoires ; une question vaut mieux qu'un champ notes |
| Attestation du client rattachée au chantier, avec modèle de lettre | 30 % des marchés BTP demandent des attestations de bonne exécution ; c'est la pièce la plus difficile à obtenir après coup |
| Dépôt d'un PV de réception pour préremplir | Même mécanisme que le dépôt de pièces |

### 3.7 Moyens humains et matériels

| Bloc | Contenu | Raison |
|---|---|---|
| Chiffre d'affaires | 3 exercices, avec l'origine de chaque valeur (« saisi par vous », « lu dans vos comptes publiés ») | 3 exercices dans 29 libellés sur 31 ; l'origine rend visible la provenance par champ |
| Effectifs | 3 années, total et encadrement | « Effectifs moyens annuels et importance du personnel d'encadrement », 3 ans dans 188 libellés sur 190 |
| Encadrement | Une personne à la fois : nom, fonction, ancienneté, diplôme facultatif, habilitations en cases | Le CV complet n'est demandé en candidature que dans 16 % des marchés BTP : on commence par le minimum |
| Matériel | Liste avec quantités, « à préciser » quand le profil ne donne qu'un texte | Le profil de démonstration donne « 3 grues mobiles, banches… » en une phrase : on la découpe sans inventer de quantités |

### 3.8 Progression globale

| Choix | Raison |
|---|---|
| Titre en temps restant (« Il vous reste environ 12 minutes »), barre de remplissage, et décompte exact des rubriques terminées | Un score précis invite à le discuter ; la barre et le décompte ne doivent jamais se contredire (remarque de l'audit) |
| Cinq rubriques, les mêmes que les onglets, chacune avec un état en mots | Remplace les pastilles vertes trompeuses de l'audit |
| « Reste environ 12 minutes » | Somme des durées des rubriques incomplètes |
| Bloc « Ce que Tendia fait déjà pour vous » | La progression se lit en bénéfices acquis, pas seulement en manques |
| Une seule action « À faire maintenant » | Choisie par la règle : pièce expirée la plus demandée, puis pièce manquante la plus demandée, puis question la plus fréquente |

### 3.9 Erreurs et cas limites

| Cas | Message | Issue proposée |
|---|---|---|
| SIRET introuvable ou à 13 chiffres | « Nous ne trouvons pas ce numéro. Vérifiez les 14 chiffres. » | Recherche par le nom de l'entreprise |
| Annuaire public indisponible | « L'annuaire des entreprises ne répond pas. Vous pouvez continuer et nous réessaierons. » | Passage direct à l'étape 2 |
| Entreprise non diffusible dans l'annuaire | « Votre entreprise n'apparaît pas dans l'annuaire public. » | Saisie de 4 champs : nom, adresse, forme, activité |
| PDF protégé par mot de passe | « Ce document est protégé par un mot de passe. » | L'enregistrer sans mot de passe, ou indiquer type et date |
| Photo de travers, tronquée | « Il manque un bord du document. » | Reprendre la photo ; conseils en une ligne |
| Document de plusieurs pièces dans un seul PDF | « Ce fichier contient 3 documents : … » | Proposition de découpage, à confirmer |
| Date illisible | « Nous n'avons pas trouvé la date. » | Champ date, format jj/mm/aaaa |
| Document au nom d'une autre société (SIRET différent) | « Ce document est au nom de … Est-ce bien pour votre entreprise ? » | Garder (cotraitant, filiale) ou retirer |
| Pièce plus ancienne que celle déjà en place | « Vous avez déjà une attestation plus récente. » | Conservée en historique |
| Connexion coupée pendant le dépôt | « Le dépôt s'est interrompu à 4 fichiers sur 8. » | Reprise des 4 restants |
| Saisie interrompue | Une réponse oui/non est enregistrée à l'appui ; un formulaire (chantier, personne) l'est par son bouton, et c'est écrit à côté du bouton | Brouillon du formulaire conservé jusqu'au retour |

### 3.10 Écran de 390 px

| Élément | Comportement |
|---|---|
| Menu latéral | Devient une barre haute d'une ligne |
| Rubriques | Bandeau défilant horizontalement, la rubrique active soulignée |
| Colonnes | Une seule ; l'encadré latéral passe sous le contenu principal |
| Lignes de document | État et boutons passent sous le texte, boutons en pleine largeur |
| Tableaux | Chaque ligne devient une fiche « libellé : valeur » |
| Zones cliquables | 44 px de haut au minimum |
| Dépôt | Le bouton « Prendre une photo avec le téléphone » devient l'entrée principale |

## 4. Corrections issues de l'audit design des maquettes

Audit du 2026-11-11 par le sous-agent `audit-design`, dans le rôle d'un dirigeant de 55 ans peu à l'aise avec l'informatique : 3 bloquants, 31 majeurs, 23 mineurs sur la première version. Conforme dès la première version : contrastes (5,2:1 au minimum), états portés par une forme et un texte, labels, hiérarchie des titres, absence de défilement horizontal à 390 px.

| # | Constat de l'audit | Gravité | Correction intégrée aux maquettes |
|---|---|---|---|
| 1 | Sur mobile, l'onglet actif sort de l'écran et le titre est le nom de l'entreprise : rien ne dit où l'on est | bloquant | Titre de rubrique sous les onglets sur chaque écran ; onglet actif placé en premier à 390 px ; bord estompé pour signaler le défilement |
| 2 | Dépôt : « 3 sont prêts » alors que 2 seulement sont reconnus ; bouton « Enregistrer les 3 » | bloquant | « 2 sont prêts, 1 est à confirmer, 3 sont à remplacer, 2 ont été écartés » ; bouton « Enregistrer les 2 documents prêts » ; phrase qui nomme ce qui sera enregistré |
| 3 | Dépôt : aucune issue pour les fichiers non enregistrés | bloquant | « Retirer de la liste » sur chaque ligne ; « Garder ce document tel quel » pour l'illisible ; « Oui, c'est exact » et « Non, je corrige » pour la lecture incertaine |
| 4 | « Environ 125 marchés ouverts » calculé sur la France se lit comme une perte, et deux arrondis différents coexistent | majeur | Proportion en clair, puis « soit environ N de vos 38 marchés », une seule règle d'arrondi |
| 5 | « Tout est enregistré au fur et à mesure » contredit par des boutons « Enregistrer » et « Annuler » | majeur | Une règle, écrite partout : les réponses s'enregistrent à l'appui, les formulaires par leur bouton ; « Annuler » supprimé |
| 6 | Compteurs contradictoires entre la vue d'ensemble, Mes documents et Chiffres | majeur | « 5 valables (dont 2 expirent bientôt) · 2 à renouveler · 3 manquants » partout ; rubrique Chiffres « À compléter » avec ce qui manque ; 5 rubriques alignées sur les onglets |
| 7 | Titre « Téléchargez » et bouton « Déposer » ; ordre inverse d'un écran à l'autre | majeur | « 1. La récupérer sur urssaf.fr », « 2. Je l'ai, je la dépose », même ordre partout |
| 8 | Les liens officiels quittent la page en cours | majeur | Ouverture dans une autre fenêtre, et la phrase « Cette page reste ouverte » |
| 9 | Plusieurs boutons pleins par écran | majeur | Un seul bouton plein par écran ; contour des boutons secondaires renforcé (3,1:1) |
| 10 | « Du plus utile au moins utile » dans le désordre | majeur | Tri par fréquence : habilitations, attestations des clients, attestation fiscale |
| 11 | « L'acheteur la réclame à l'entreprise qu'il retient » incompréhensible | majeur | « Elle n'est exigée que si vous gagnez le marché, mais il faut alors la fournir en quelques jours » |
| 12 | Questions : conséquence d'un « Non » inconnue ; question sur le redressement anxiogène ; question sur les 20 salariés alors que l'effectif est connu | majeur | « Oui : … Non : … » sous chaque question ; aide rassurante et pas de « Je ne sais pas » pour le redressement ; l'effectif devient un fait affiché |
| 13 | Fichier lourd : ton de reproche, jargon (« Mo », « dossier compressé ») | majeur | « Ce fichier est trop gros pour être déposé ici », sans unité, avec la marche à suivre |
| 14 | Sort des pièces périmées flou | majeur | Urssaf expirée : non enregistrée ; Kbis ancien : gardé en attendant, jamais joint |
| 15 | « Encadrement » demandé deux fois sous deux formes | majeur | « dont cadres et chefs de chantier » pour le nombre ; « Vos conducteurs de travaux et chefs de chantier » pour les personnes |
| 16 | Aucun état d'erreur pour le SIRET ; aide téléphonique absente après le premier écran | majeur | Message d'erreur illustré sur l'écran 01 ; ligne d'aide en pied de chaque écran |
| 17 | « Sur cet ordinateur », « Glissez », « Prendre une photo » affichés sur le mauvais appareil | majeur | Libellés distincts sur ordinateur et sur téléphone |
| 18 | Focus clavier doré peu visible ; pastille d'onglet déformée par une classe partagée | majeur | Focus bleu nuit ; classe renommée |
| 19 | Sigles (DC1, DC2, DUME, DC4, code d'activité), « type », quatre noms pour l'attestation du client, « nous » et « Tendia » mêlés | mineur | Sigles développés ou retirés ; « Ce n'est pas ce document » ; « Attestation du client (bonne exécution) » partout ; « Tendia » pour l'outil, « nous » pour l'aide humaine |
| 20 | Liens d'action trop petits sur mobile ; état lu après le détail ; année 2026 présélectionnée ; champs facultatifs non signalés ; pas de suite en bas de page | mineur | Boutons de 40 px au moins ; état placé avant le texte à 390 px ; « Choisir l'année » ; « Facultatif » écrit ; lien « Continuer » en bas des rubriques |

Les maquettes corrigées n'ont pas été auditées une seconde fois.

Non repris, à arbitrer :

| Constat | Raison |
|---|---|
| Le menu des maquettes (Accueil, Marchés, Mon entreprise) diffère du menu actuel (Dashboard, Explorer, Profil organisme, Concurrence, Marchés DECP) | Voulu : la refonte renomme le menu pour le dirigeant (audit du 2026-11-10, vocabulaire). Concurrence et Marchés DECP restent à placer |
| Pages longues sur mobile (Mes documents) | Le repli des groupes « Valables » et « Manquants » est à tester avec de vrais utilisateurs avant de cacher de l'information |
| Écran Identité absent | Hors des écrans clés ; la ligne « Identité » de la vue d'ensemble n'est plus un lien |
| Liste déroulante à la place des onglets sur mobile | L'onglet actif en premier règle le repérage ; à réévaluer en test |

## 5. Vocabulaire

| Terme interne à bannir de l'écran | Terme affiché |
|---|---|
| Profil organisme, profil actif, bibliothèque de profils | Mon entreprise |
| Coffre-fort, `coffre_pieces` | Mes documents |
| Matching, score de pertinence | Les marchés qui vous correspondent |
| Preset, secteur | Vos métiers |
| Exigence, verrou, clé canonique | Question, condition du marché |
| Brief, DCE | Le résumé du marché, le dossier de consultation |
| Upload, téléverser, drag and drop | Déposer, glisser |
| Extraction, OCR, parsing, LLM | « Nous lisons le document » |
| Confiance 0,6 | « Nous pensons avoir lu… Est-ce exact ? » |
| Hash, SHA-256, doublon détecté | « C'est le même fichier que… » |
| Attributaire pressenti | L'entreprise que l'acheteur retient |
| Références | Chantiers réalisés |
| Moyens humains, moyens matériels | Équipe, matériel |
| Attestation de vigilance | Attestation Urssaf (le nom officiel entre parenthèses) |
| RC pro | Assurance responsabilité civile |
| Complétude 66 % | « Il vous reste environ 12 minutes », « 1 rubrique terminée sur 5 » |
| DC1, DC2, DUME | Gardés : ce sont les mots des acheteurs, toujours accompagnés de leur nom en clair |
