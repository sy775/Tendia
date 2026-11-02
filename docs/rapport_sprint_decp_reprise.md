# Rapport — Sprint DECP-R (reprise des DECP et rapprochements)

> Branche `feat/decp-reprise` (depuis `feat/decp-sprint-3`), 02/11/2026. **Non fusionnée** :
> l'estimation voie 3 affichée dans l'UI change (point 8) — fusion après validation de Younes.
> Sauvegarde de la base avant le sprint : `data/tendia.db.bak_avant_decp_reprise_20261102`.
> Détails chiffrés : `data/decp_reprise/*.json` (non versionné).

## 1. Ce qui a changé dans la base

| Table | Avant | Après |
|---|---|---|
| `decp_marches` | 142 735 lignes, PK `id` (numéro **interne** à l'acheteur, non unique), 12 mois | **1 254 035 contrats**, PK `uid` (= acheteur + id + _CPV), notifiés du 01/01/2022 au 26/10/2026 ; table v1 conservée en `decp_marches_v1_id` |
| `decp_classification` | 7 codes larges (v1 conservée en `decp_classification_v1_id`) | `famille` (= preset officiel) + `domaine` (taxonomie classifications_ia + `btp_maintenance_exploitation`) |
| `decp_titulaires` | — | 1 379 040 lignes (contrat, rang, SIRET, SIREN, nom, NAF, catégorie, rôle), index `siren` |
| `sirene_unites_legales` | — | 863 413 unités légales (stock du 01/10/2026) avec adresse du siège |
| `marche_attribution_link` | 0 | 428 liens (195 « objet confirmé ») |
| `marches.acheteur_siren` | 1 341 / 3 039 (44,1 %) | 1 862 / 3 039 (61,3 %) |

Source historique : `decp.csv` (2,63 Go, instantané data.gouv du 26/10/2026), lu en flux.
Mises à jour : API tabulaire (même ressource), toutes versions, relances des pages en échec.

## 2. Défauts trouvés et corrigés

1. **Clé `id` non unique** : la v1 écrasait les contrats de même numéro chez des acheteurs
   différents et fusionnait leurs titulaires. Sur la période de la v1 (notifications du 15/06/2025
   au 15/06/2026, contrats uniques déjà publiés le 16/06/2026) : **68 353 contrats sur 195 066
   absents de la v1 (35 %)**, dont 18 901 contrats modifiés (cf. point 2). Sur les 16 562 contrats
   v1 « à plusieurs titulaires », **7 625 (46 %) portaient des titulaires d'autres contrats**
   (ex. un accord-cadre à 1 titulaire réel en affichait 60).
2. **Filtre `modification_id = 0`** : il excluait tout contrat dont la version actuelle est une
   modification (290 955 contrats depuis 2022). Désormais : version actuelle + informations de la
   version initiale (`montant_initial`, `duree_initiale`, `nb_modifications`).
3. **`dateNotification` d'une modification = date de la modification** (vérifié sur 235 790
   contrats) : `date_notification` vient toujours de la version initiale.
4. **Titulaires** : `titulaire_nom` (97 %), NAF, catégorie, type de groupement étaient ignorés par
   le parseur (le rapport d'architecture §8ter.2 disait le nom absent : c'était faux).
5. `decp/db.py` : chemin codé en dur → `stockage.chemin_db()` ; `busy_timeout` 30 s ; UPSERT limité
   aux colonnes source (jamais d'écrasement de `doublon_de`, `doublon_possible`, classification).

## 3. Lignes ingérées, BTP, doublons

| Année | Contrats | Doublons marqués | Taux | Uniques | BTP (famille) | Part BTP |
|---|---:|---:|---:|---:|---:|---:|
| 2022 | 271 728 | 21 335 | 7,9 % | 250 393 | 102 601 | 41 % |
| 2023 | 266 306 | 26 779 | 10,1 % | 239 527 | 97 819 | 41 % |
| 2024 | 286 693 | 28 419 | 9,9 % | 258 274 | 108 591 | 42 % |
| 2025 | 271 973 | 18 993 | 7,0 % | 252 980 | 102 825 | 41 % |
| 2026 (au 26/10) | 157 335 | 13 411 | 8,5 % | 143 924 | 55 138 | 38 % |

Tableau **mois par mois** (58 mois) : `data/decp_reprise/tableau_mensuel.md`.
BTP 2022-2023 hors IA = famille issue du CPV (cf. §5). Exclus : 55 165 contrats notifiés avant 2022
puis modifiés après ; 19 628 contrats sans date de notification (répartition par source et année
de publication : arrêt n°2).

**Doublons** (règles validées R1-R4, marquage `doublon_de`, aucune suppression) : 108 937 contrats
(8,7 %) — R1 multi-source mêmes titulaires 80 081 ; R2 multi-source dont un sans titulaire 28 324 ;
R3 identifiant reformaté 525 ; R4 correction de CPV 7. Indicateur séparé `doublon_possible`
(sans effet sur comparables ni historique) : 52 964 contrats, 21 190 groupes.

**Titulaires** : SIREN valide 98,9 % (1 363 409 / 1 379 040) ; SIRET valide 98,5 % ; **avec un nom
98,4 %** (+ 5 546 noms récupérables par Sirene) ; 128 335 SIREN distincts. Rejets journalisés
(`data/decp_reprise/titulaires_rejets.tsv`) : identifiants fictifs « 00001 »… (3 944), hors UE,
TVA étrangères, longueurs anormales. Champs peu fiables avant 2024 (groupement ~20-31 %, offres
reçues ~17-25 %, sous-traitance ~19-29 %) : documentés dans le schéma (`decp/db.py`).

## 4. Sirene

863 413 unités légales retenues (diffusion partielle exclue : 3 775) : BTP actives NAF 41/42/43
personnes morales 595 386 ; personnes publiques (4xxx, 7xxx) 185 269 ; titulaires DECP 126 701
(sur 128 335) ; acheteurs DECP 20 876 (une unité peut avoir plusieurs motifs).

## 5. Classification par IA

**Pilote 1** (200 contrats, prompt v1) : Flash-Lite 83,7 % (domaine) / 76,8 % (cas sensibles) →
seuils non atteints. Causes : maintenance d'équipements (CPV 50*) sans domaine ; frontières énergie
(71314).

**Pilote 2** (prompt v2 : domaine `btp_maintenance_exploitation` propre à la DECP, règles, exemples,
sortie compacte), vérité provisoire = arbitre gemini-4-argon à l'aveugle (159 lignes dont 87 BTP) :

| Variante | BTP oui/non | Rappel BTP | Domaine fin BTP | Domaine total | Sensibles |
|---|---:|---:|---:|---:|---:|
| **Flash-Lite v2, 50/appel (retenue)** | **95,0 %** | **97,7 %** | **93,1 %** | 89,3 % | 90,1 % |
| Flash-Lite v2, 100/appel | 92,5 % | 95,4 % | 90,8 % | 87,4 % | 84,5 % |
| Flash-Lite v2 allégé, 50 | 96,9 % | 98,9 % | 87,4 % | 84,3 % | 85,9 % |
| Haiku (prompt v1) | 86,2 % | 79,3 % | 67,8 % | 73,0 % | 64,8 % |
| CPV seul | 79,9 % | 73,6 % | — | — | — |

Autres secteurs (informatif, Flash-Lite v2 50) : ingénierie 92 % (n=12), conseil 100 % (n=6),
hors périmètre 88 % (n=49), **énergie 20 % (n=5)** — faible, à revoir si l'énergie devient prioritaire.

**Classification complète** (API Batch, -50 %) : **2024-2026 en totalité (379 665 contrats)** +
2023 partiel (43 250) ; le reste de 2022-2023 garde la famille CPV (`cpv_attente_ia`, 247 297
contrats uniques). Doublons : classification du contrat conservé recopiée. Hors pré-filtre :
famille CPV définitive (`cpv_hors_prefiltre`). Quota Gemini Batch Tier 1 : 10 M tokens simultanés
(~4 lots de 15 000 contrats).

**Coût LLM total du sprint : 9,9998 € / 10 €** (dont Claude 0,039 € / 1 €) : pilotes Flash-Lite
et Haiku 0,08 €, arbitres 0,87 €, Batch 9,05 € (≈ 0,0214 € pour 1 000 contrats). Coût réel Batch
≈ 87 % de l'estimation (estimation prudente). Compléter 2022-2023 (247 297 contrats) coûterait
≈ 5,3 € de plus (non lancé : plafond).

## 6. Historique par entreprise

`decp.historique.historique_decp(siren)` : contrats (seul ou en groupement, hors doublons),
acheteurs, départements, montants (médiane, max), domaines, fins estimées. < 3 ms par SIREN.
32 588 SIREN BTP ont un historique. Exemple (5 SIREN BTP au hasard) : une entreprise d'échafaudage
du Rhône : 47 marchés 2022-2026, médiane 72 k€, 7 fins de contrat dans les 12 mois.

## 7. Comparables de prix (voie 3)

**20 briefs de référence** (avant = données v1) : 16/20 à ±15 %. Écarts > 15 % :

| Brief | Avant | Après | Écart | Explication |
|---|---:|---:|---:|---|
| BOAMP-26-57070 | 220 000 | 258 471 | +17 % | pas de CPV ni d'ancre → « secteur + département » ; 4 808 lignes possibles **tronquées à 4 000 sans ordre** (LIMIT sans ORDER BY) ; période v1 seule = 300 000 |
| BOAMP-26-56464 | 1 986 840 | 1 600 000 | -19 % | historique 2022-2024 moins cher (médianes 1,5-1,6 M€ vs 1,81 M€ en 2025) |
| BOAMP-26-57058 | 3 400 000 | 2 640 367 | -22 % | échantillon v1 minuscule (n=8, au seuil) → 43 comparables |
| BOAMP-26-55979 | 8 000 000 | 12 000 000 | +50 % | n=18 → 93 ; contrats 2022-2023 plus gros (médiane 13 M€) ; période v1 seule = 8,06 M€ |

**Backtest** (800 contrats DECP, montant caché, seed 42 ; MdAPE = erreur médiane) :

| Configuration | MdAPE | Couv. IQR | Biais |
|---|---:|---:|---:|
| Avant (v1, référence) | 74 % | 44 % | -7 % |
| Après, configuration prod | 76 % | 42 % | -5 % |
| `montant_rationalise` | 73 % | 43 % | -2 % |
| `montant_initial` | 73 % | 44 % | -3 % |
| sans accords-cadres ni anomalies | **70 %** | 43 % | -4 % |

**Propositions (non appliquées)** : P1 pondération par ancienneté (demi-vie 2 ans) : briefs -4 % à
+5 % ; mini-backtest 2026 MdAPE 74,5 → 71,4 % (biais -9,3 → -11,3 %). P2 indexation BT01 (INSEE
001710986, dernier point 08/2026 = 139,4) des comparables < 2025 : briefs +0 à +10 % (≈ +5 %) ;
MdAPE 74,5 → 73,2 %, biais -9,3 → -7,1 %. **Recommandation** : P2 + exclusion accords-cadres /
anomalies, et `ORDER BY date_notification DESC` avant le LIMIT (à valider).

### 7bis. Configuration prod finale (validée le 02/11/2026)

Appliqué : `ORDER BY date_notification DESC, uid` avant le `LIMIT 4000`. L'exclusion des
accords-cadres et des `montant_anomalie` a été appliquée puis **retirée** (voir la correction
ci-dessous) : `CONFIG_DEFAUT` les garde. P1 et P2 non appliquées. Backtest de confirmation
(config prod finale, tous contrats) : **MdAPE 76 %**, couverture IQR 42 %, biais -5 %.
**20 briefs, config prod finale** (`data/decp_reprise/voie3_final_v2.json`) : 17/20 à ±15 % ;
écarts > 15 % : 56464 -19 %, 57058 -22 %, 55979 +50 % (explications du tableau ci-dessus ;
57070 passe à +14 % grâce au tri). Le paragraphe suivant porte sur la version avec exclusion.

**20 briefs, avant (v1) → final** : 17/20 à ±15 %. Écarts > 15 % : 56464 -19 %, 56633 -16 %,
57058 -22 % ; tous trois avec 53 à 67 % de comparables antérieurs à 2025, notifiés à des prix
d'avant l'inflation. 57070 revient à -7 % (troncature réglée) et 55979 à +7 %. Fichier :
`data/decp_reprise/voie3_final.json`.

**Backtest final** (800 contrats, seed 42) :

| Échantillon testé | Comparables | MdAPE | Couv. IQR | Biais |
|---|---|---:|---:|---:|
| hors accords-cadres et anomalies | avec exclusions | 70 % | 43 % | -4 % |
| hors accords-cadres et anomalies | sans exclusions (prod finale) | 70 % | 45 % | +0 % |
| tous contrats | avec exclusions | 78 % | 38 % | -9 % |
| tous contrats | sans exclusions (prod finale) | 76 % | 42 % | -5 % |

⚠ **Correction** : le gain affiché plus haut (76 → 70 %) venait surtout de l'échantillon : retirer les
accords-cadres des contrats testés retire des cas difficiles à prédire. À échantillon égal,
exclure ces contrats des comparables ne réduit pas l'erreur : 70 % contre 70 % sur l'échantillon
filtré, 78 % contre 76 % sur l'échantillon complet (écart dans la marge de ±3 points). Le
`ORDER BY` rend en revanche le résultat déterministe.

## 8. Attributions

- `acheteur_siren` complété sur 521 marchés (nom normalisé exact + département 476, nom exact
  unique en France 37, nom proche 8) ; 1 177 non sûrs journalisés (`acheteurs_non_surs.tsv`).
  Champ de provenance ajouté : `acheteur_siren_source`.
- `scorer_match` (inchangé) sur 888 avis à date limite passée : **71 avis avec attribution
  retrouvée** (score ≥ 0,70 ; travaux 10), **dont 43 à objet confirmé** (≥ 3 mots communs ;
  travaux 3) ; distribution du meilleur score : 0,4 : 19 · 0,5 : 23 · 0,6 : 156 · 0,7 : 15 ·
  0,8 : 12 · ≥ 0,9 : 44. `scorer_match` ne compare pas les objets : ~5 liens sur 10 faux sans
  contrôle d'objet, ~6 sur 7 justes avec (statuts `auto_confirme_objet` / `auto_a_verifier`).
  10 exemples : `attributions_a_verifier.csv`. Limite : DECP au 26/10, notifications souvent
  1-3 mois après la date limite.
- **Avis avec un marché précédent du même acheteur** (méthode du rapport) : **322 → 570** ;
  travaux **49 → 86** (variante stricte, contrat notifié avant l'avis : 560 / 85).

## 9. Exploitation

- Hebdomadaire : `scripts/decp/maj_hebdo.py` (idempotent, verrou, journal
  `data/decp_reprise/maj_hebdo/`), IA sous l'enveloppe mensuelle `decp_hebdo` (2 €/mois).
- Budget : `budget.json` couvre extraction, calibration, classification, decp, memoire, digest ;
  plafond mensuel global 100 € (alerte 50 €) ; enveloppes de sprint ; kill switch vérifié partout.
- Espace : `decp.csv` 2,63 Go (à garder jusqu'à la fin du sprint), Sirene 3,9 Go, base 1,7 Go.
