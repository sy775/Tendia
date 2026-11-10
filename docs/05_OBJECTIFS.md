# Tendia : objectifs (lu en premier par toute nouvelle session)

Dernière mise à jour : 2026-11-10, par Younes. Ces objectifs ordonnent le backlog (03_BACKLOG.md). Quand une session hésite entre deux tâches, elle choisit celle qui sert l'objectif le plus haut dans cette liste.

## Objectif 1 : un agent qui intègre toute la procédure, jusqu'à la réponse

Ce que ça veut dire : pour un marché BTP donné, l'outil enchaîne sans intervention humaine la lecture complète du DCE, l'analyse d'éligibilité, l'estimation de prix, le mémoire technique, le remplissage des pièces de candidature et l'assemblage d'un dossier déposable, puis une fiche de dépôt. L'humain relit, ajuste, dépose.

Étapes dans l'ordre (chaque étape est un chantier du backlog) :
1. Relancer la chaîne LLM arrêtée depuis juin, classification dans le pipeline (chantier 1).
2. Lecture exhaustive des DCE en prod, à partir de `exp_gemini/pieces.py` et `mode_document.py` (chantier 2).
3. Un dossier produit à la main sur un marché réel, puis l'agent d'assemblage (chantier 3).
4. Préremplissage DC1, DC2, DUME, AE à partir du profil ; pack de dépôt nommé selon le RC.
5. Dépôt assisté (navigateur piloté, confirmation humaine écran par écran) en dernier.

Mesure : temps entre « marché choisi » et « dossier relu et déposable ». Cible : sous 30 minutes de travail humain, contre ~2 jours aujourd'hui.

## Objectif 2 : un coffre-fort où l'IA puise les pièces et les certificats

Ce que ça veut dire : l'entreprise dépose une fois ses pièces (Kbis, attestations URSSAF et fiscale, assurances RC et décennale, Qualibat, RGE, bilans, références de chantiers, CV, moyens matériels). L'agent les lit, en extrait les dates de validité et les informations utiles, et les injecte dans chaque dossier sans que l'entreprise les ressaisisse. Il alerte avant expiration.

Étapes :
1. Table `coffre_pieces` (type normalisé, date d'émission, validité, fichier, empreinte), upload dans l'UI, référentiel des pièces avec lien d'obtention officiel (chantier 4).
2. Lecture de chaque pièce par un LLM léger : validité, montant de garantie, codes de qualification, journalisée dans `llm_appels`.
3. Alimentation automatique du profil entreprise depuis les pièces (avec source, date, confiance), remplacement progressif de la saisie manuelle.
4. Injection dans le dossier (objectif 1, étape 3) et dans les formulaires DC1/DC2.
5. Alertes d'expiration (locales d'abord, mail quand un hébergement existe).

Mesure : part des pièces d'un dossier fournies par le coffre sans action humaine. Cible : 100 % des pièces de candidature.

## Objectif 3 : un outil beau et intuitif, en particulier la partie entreprise

Ce que ça veut dire : un dirigeant de PME BTP qui ouvre l'outil comprend en 30 secondes où il en est et quoi faire ensuite. La partie entreprise (profil, pièces, exigences) est aujourd'hui un formulaire technique hérité du secteur formation ; elle doit devenir un espace « mon entreprise » lisible, guidé, avec des états vides utiles et des réponses oui/non qui débloquent des marchés.

Étapes :
1. Audit par l'agent `audit-design` des écrans profil, fiche marché, dashboard, explorer (captures 1440 et 390 px, rapport par écran).
2. Sortir les styles inline de `marche.html` (~1 700 lignes) en classes communes ; chaîne de build Tailwind dans le dépôt.
3. Refonte de l'espace entreprise : profil en sections courtes, coffre-fort intégré, questions d'éligibilité classées par nombre de marchés débloqués.
4. Fiche marché orientée décision : verdict, ce qui manque, bouton « préparer le dossier ».
5. Dashboard orienté action : marchés à traiter cette semaine, dossiers en cours, pièces qui expirent.

Mesure : un prospect en démo réalise seul, sans explication, les trois actions de base (compléter son profil, lire un marché, lancer un dossier).

## Objectifs de soutien (ajoutés par Claude, à valider)

4. **Matching fiable pour le BTP** : état « inconnu » distinct de « non détenu », clés canoniques BTP (Qualibat, RGE, décennale, CA minimum), signaux structurés plutôt que texte libre, tests sur `matching` et `preset`. Sans ça, l'objectif 3 affiche de faux verdicts.
5. **Coût LLM maîtrisé et tracé** : tous les appels dans `llm_appels`, plafond par batch, coût par dossier connu. Le prix de 299 €/mois dépend d'un coût de revient sous 30 € par client et par mois.
6. **Actif protégé** : `data/dce` (124 Go) trié et sauvegardé hors du disque principal ; base de prod sauvegardée avant tout script de masse.
7. **Suivi des dossiers et des attributions** : table des dossiers de réponse (déposé, attribué, rejeté), rapprochement BOAMP↔DECP relancé, détection des renouvellements. C'est ce qui rend l'outil indispensable après le premier dossier.
8. **Hébergement et comptes** : serveur Linux, authentification, un espace par entreprise. Prérequis à toute démo en ligne et au coffre-fort partagé avec des cotraitants.
9. **Cinq démos avant le 2027-01-09** : 30 PME BTP contactées, un dossier réel montré. Les chantiers techniques servent les démos, pas l'inverse.

## Ce qui n'est pas un objectif

- Un nouveau secteur avant que le BTP fonctionne de bout en bout.
- Un nouveau produit ou une nouvelle idée de projet avant le 2027-01-09.
- Le dépôt automatique sans confirmation humaine, à aucune échéance.
