# Tendia : fiche produit (référence, relue à chaque chantier)

Dernière mise à jour : 2026-11-10. Si une ligne de ce document change, le changement est une décision produit, pas un détail technique.

## Le produit en une phrase

Tendia produit, pour une PME du BTP, un **dossier de réponse à appel d'offres prêt à déposer** : DCE lu en entier, prix estimé, mémoire technique rédigé, pièces de candidature assemblées, fiche de dépôt.

## Ce que le client achète

| Élément | Contenu |
|---|---|
| Client | Dirigeant ou chargé d'affaires d'une PME BTP de 10 à 50 salariés, 2 à 5 réponses par mois |
| Travail remplacé | Lire le DCE, calculer le prix, rédiger le mémoire technique, rassembler les pièces : environ 2 jours par réponse aujourd'hui |
| Livrable | Un dossier structuré (zip) nommé comme le règlement de consultation l'exige, livré en 24 h, prêt à relire et déposer |
| Prix de référence | 299 €/mois (option annuelle 2 990 €). À l'unité possible pendant la phase de test |
| Promesse secondaire | Le coffre-fort entreprise : pièces de candidature saisies une fois, réutilisées à chaque marché |

## Ce que le produit ne fait pas (limites volontaires)

- Il ne dépose pas sur le profil d'acheteur : le client dépose avec son propre compte, en 10 minutes.
- Il ne gère aucun identifiant client sur les plateformes.
- Il ne signe rien : la signature électronique reste au représentant légal.
- Il ne décide pas à la place du client : le prix et le mémoire sont des propositions à valider.

Le dépôt assisté (agent navigateur avec confirmation humaine écran par écran) est une version 2, après les premiers clients.

## La chaîne d'agents derrière le livrable

| Agent | Rôle | État au 2026-11-10 |
|---|---|---|
| Veille | BOAMP → classification sectorielle | En prod ; la classification est l'étape 2 du pipeline depuis le chantier 1 (2026-11-10) |
| Récupération DCE | Résolution d'URL + téléchargement sur 7 plateformes | En prod, ~80 % de couverture |
| Analyse DCE | Lecture complète du dossier → brief structuré | Prod : lacunaire (jusqu'à 49 % du texte non lu). Expérimentation « mode document » (Gemini/Opus) : complète |
| Prix | Estimation à partir des comparables DECP, déterministe | Partiel (comparables ok, rapprochement BOAMP↔DECP quasi nul) |
| Mémoire technique | Plan + rédaction par section + .docx | Fonctionnel (8 mémoires produites) |
| Assemblage du dossier | Pièces + prix + mémoire → dossier déposable | **Absent**, c'est la brique qui manque pour vendre |
| Coffre-fort entreprise | Pièces administratives réutilisables | Absent |

Le client ne voit jamais les agents. Il voit le dossier.

## Marché et positionnement

- Marchés publics français, BOAMP (TED non connecté malgré la doc).
- Entrée par le BTP : 50 888 contrats DECP classés BTP sur 142 735, le volume est là.
- Concurrents AO + IA repérés : Maître AO, Remporte, Nextend.ai, marchespublics.ai. Différenciateur revendiqué : récupération automatique du DCE (les autres demandent au client de l'uploader) et lecture exhaustive.

## Règle des 60 jours

Jusqu'au 2027-01-09 : aucun nouveau brainstorm produit, aucune nouvelle idée de projet. Objectif : 30 PME BTP contactées, 5 démos, un dossier réel produit à la main avant toute automatisation de l'assemblage. Si après 5 démos personne ne veut payer même 99 €/mois, on change d'idée, avec une donnée en main.
