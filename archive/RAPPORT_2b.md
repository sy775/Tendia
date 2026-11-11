# Rapport du chantier 2b : fiabiliser la fusion, finir la lecture, produire les briefs

Branche `chantier/2b-fusion`, mode rapide. Date : 2026-11-11.

## En bref

**À reprendre** : 6 briefs BTP produits sur 10 au lieu des 10 visés. 4 DCE ont été sautés parce que leur coût estimé dépasse le plafond de 2,5 € par DCE. Les autres critères de fin sont atteints :

| Critère | Résultat |
|---|---|
| Tests | 52/52 fichiers verts (verif-tests après l'étape 2 et avant la fusion) |
| 5 références lues | oui : 102749 retéléchargé (zip complet) puis lu, 45/45 pièces ; les 4 autres recalculées sans LLM |
| Briefs BTP | 6 sur 10 ; 4 sautés (coût estimé au-delà de 2,5 €) |
| Montant publié et estimation séparés sur la fiche | oui, deux lignes, contrôlé sur des fiches réelles |
| Fidélité mesurée | 30/30 sur les 5 références (verificateur-brief, un par un) |
| Coût du chantier | 10,89 € (≤ 28 €) ; novembre 45,27 € (≤ 65 €) |

## Fidélité des 5 références

| DCE | Exacts /6 | Sources vérifiées /6 | Valeurs vérifiées /6 | Coût du chantier |
|---|---|---|---|---|
| BOAMP-26-102749 | 6 | 0 (RC scanné, aucun extrait vérifiable sans OCR) | 3 | 4,64 € |
| BOAMP-26-104121 | 6 | 6 | 6 | 0 € (recalcul) |
| BOAMP-26-103934 | 6 (5 à la 1re mesure : DC2 manquant, corrigé puis revérifié) | 6 | 6 | 0 € (recalcul) |
| BOAMP-26-104292 | 6 | 6 | 6 | 0 € (recalcul) |
| BOAMP-26-104768 | 6 | 5 (extrait des critères cité p. 8, il est p. 9) | 6 | 0 € (recalcul) |

Au chantier 2, la fidélité était de 18/30. Les briefs des 4 références déjà lues ont été recalculés sans LLM à partir de leurs notes par pièce. Chaque brief précédent est copié dans `archive/data/briefs/`.

## Écarts au prompt

- Étape 4 : 6 briefs produits sur 10. Les 4 sautés et leur coût estimé : 103662 (21,18 €), 104289 (3,56 €), 105950 (3,16 €) et 105174 (3,21 €). La commande imposée ne fixait pas de plafond par DCE, celui par défaut (2,5 €) s'est appliqué. Faute de consigne, je n'ai pas relancé avec un plafond plus haut : c'est le choix qui ne dépense rien. Les 11 candidats d'octobre sont épuisés, 102749 compris.
- 102749 : RC scanné. Le brief en base venait d'une version de `champs_critiques` qui lisait mal les pondérations (33,75/16,25). Je l'ai recalculé avec `--force`, alors que le nombre de sources vérifiées baisse (de 3 à 0) : les 3 sources vérifiées pointaient vers l'avis OJS et non vers le RC. Les valeurs du RC sont exactes (6/6) et restent marquées « non vérifiée » sur la fiche.
- Les vérifications et l'audit ont mis au jour des défauts de lecture des notes, que j'ai corrigés en cours de chantier :
  - avis OJS typé RC ;
  - grille de notation lue comme un critère ;
  - pièce numérotée suivie de sous-pièces ;
  - drapeau `obligatoire` ;
  - et, côté audit, les bloquants B1 (visite lue sur une annexe) et B2 (montant d'un lot pris pour celui du marché).

  Tous les briefs du chantier ont été recalculés sans LLM après ces corrections.
- Les sous-agents `testeur` et `relecteur-etape` sont archivés dans `archive/.claude/agents/`. `audit-design` passe sur opus. La section « Sous-agents » de CLAUDE.md est remplacée par le mode rapide.

## Chiffres

- Coût LLM du chantier : 10,89 €. Lecture de 102749 : 4,64 € (49 appels, aucun repli ; estimation 4,72 €). Étape 4 : 6,25 € pour 6 briefs. Le reste n'a rien coûté : recalculs, vérifications, dry-runs.
- Dépense de novembre : 45,27 € pour un plafond daté de 65 € (30 € par défaut à partir de décembre, réglé dans `data/budget.json`).
- Briefs de l'étape 4 :

  | Marché | Pièces lues | Coût |
  |---|---|---|
  | 103800 | 6/6 | 0,42 € |
  | 105600 | 14/14 | 0,75 € |
  | 103395 | 25/25 | 1,81 € |
  | 105855 | 19/19 | 1,24 € |
  | 105451 | 32/32 | 0,99 € |
  | 104894 | 17/17 | 1,05 € |

- Sources vérifiées sur les briefs de l'étape 4 :
  - 103395 : 0/6 ; ses 6 champs restent d'origine « fusion », car les notes par pièce ne les portent pas ;
  - 103800 : 1/6 ;
  - 104894 : 2/6.

  Ces briefs n'ont pas été passés au vérificateur, qui n'était demandé que sur les 5 références.
- Audit de code (`archive/AUDIT_2b.md`) : 2 bloquants corrigés (B1, B2), 7 majeurs (M1 à M6 reportés au backlog, M7 traité par ce rapport) et 17 mineurs.

## Hésitations

- Montant publié par lot sans total (104894) : statut `publie_par_lot`. Les montants par lot sont affichés et aucune somme n'est calculée à la place de l'acheteur.
- Un avis OJS ou BOAMP, et une annexe typée RC (attestation, modèle), passent après le RC du même rang. C'est une lecture de la règle « RC > AE > CCAP » : le RC fait foi.
- Pour les pièces exigées, la visite et les lots, `valeur_verifiee` vaut la vérification de l'extrait : aucune valeur chiffrée n'est à contrôler dans ces champs.
