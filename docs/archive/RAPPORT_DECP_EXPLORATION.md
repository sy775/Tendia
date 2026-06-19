# Rapport d'exploration DECP — Sprint DECP 1, Étape 0

_Généré par `scripts/decp_explorer.py`. 0 LLM, lecture seule. À valider par Younes avant l'Étape 1._

## ⚠️ Découvertes structurelles (impactent le design du sprint)

1. **La DECP n'est PAS publiée en fichiers JSON mensuels.** La source de référence est la **DECP consolidée** (Colin Maudry / Colmo), un dataset unique mis à jour **quotidiennement**, requêtable via l'**API tabulaire** data.gouv.fr (pagination + filtres `__greater`/`__less`/`__contains`/`__exact`). → L'Étape 1 ne peut pas s'appuyer sur `telecharger_decp(annee_mois)` qui télécharge un fichier mensuel ; il faut **soit** paginer l'API tabulaire filtrée par date+CPV, **soit** télécharger le fichier consolidé (Parquet) et filtrer localement (pyarrow).
   - Ressource : `22847056-61df-452d-837d-8b8ceadbfc52` — API : `https://tabular-api.data.gouv.fr/api/resources/22847056-61df-452d-837d-8b8ceadbfc52/data/`
   - Connecteur Tendia existant à réutiliser : `connecteurs/decp_consolidee.py`.

2. **Stockage Tendia = clé-valeur JSON, pas relationnel.** Les marchés Tendia vivent dans `kv_storage(collection='marches', id='BOAMP-26-…', contenu_json=…)` — il n'existe **pas de table relationnelle des marchés**. Le DDL du sprint (`-- FK vers la table marchés Tendia`) doit donc être résolu ainsi : `marche_attribution_link.marche_tendia_id` = l'`id` de la collection `marches` (ex. `BOAMP-26-57070`), **sans contrainte FK SQL réelle** (la cible est une ligne JSON d'une table KV). Les collections `marches_notifies` et `marches_tendia_attribues` sont déjà réservées (vides) pour la DECP.

## 1. Source identifiée

- **Dataset** : Données Essentielles de la Commande Publique (DECP) — consolidée.
- **Ressource (id)** : `22847056-61df-452d-837d-8b8ceadbfc52` (format Parquet côté data.gouv.fr).
- **API tabulaire** : `https://tabular-api.data.gouv.fr/api/resources/22847056-61df-452d-837d-8b8ceadbfc52/data/`
- **Métadonnées ressource** : {"created_at": "2026-06-15T07:26:52.616477+02:00"}
- **MAJ** : quotidienne (source Colmo).
- **Volume total dataset** : **3 081 020** lignes (actes/attributions).
- **Volume 12 derniers mois** (`dateNotification ≥ 2025-06-16`) : **517 586** lignes.
- **Opérateur `__less` supporté** : oui

## 2. Mois échantillonné

- Mois : **2026-05** — total réel sur le mois : **7 565** lignes.
- Échantillon analysé : **2359** lignes (pagination API).

## 3. Structure & formats (sur l'échantillon)

- **Premier niveau JSON** : `{ "data": [ {record plat}, … ], "meta": {total,…}, "links": {…} }`. Chaque record est **plat** (pas d'imbrication) — ~66 colonnes.
- **Format SIRET acheteur** (`acheteur_id`) : 14 chiffres, sans espaces. Valides Luhn : **100.0 %**.
- **Format SIRET titulaire** (`titulaire_id`) : selon `titulaire_typeIdentifiant` (SIRET le plus souvent). Valides Luhn : **97.9 %**.
- **Format montant** (`montant`) : numérique HT (peut être négatif/0/aberrant). Médiane ≈ 98 102 €  min 0  max 47 991 540.
- **Format date** (`dateNotification`, `datePublicationDonnees`) : ISO 8601 (`AAAA-MM-JJ`).
- **Format CPV** (`codeCPV`) : 8 chiffres sans séparateur. Mal formés : 0 / 2359.
- **Multi-titulaires** : un marché multi-attributaires = **plusieurs lignes même `id`** (à dédupliquer/agréger). Détectés : 158 id(s) en doublon sur 2094 id(s) uniques de l'échantillon.
- **Révisions / avenants** : `modification_id > 0` → 0 ; `donneesActuelles = false` → 0. (Le sprint a acté : versioning DECP = non → filtrer `modification_id=0` + `donneesActuelles=true`.)

## 4. Couverture des champs clés (échantillon)

| Champ | Rempli |
|---|---|
| montant > 0 | 99.5 % |
| codeCPV | 100.0 % |
| acheteur SIRET valide (Luhn) | 100.0 % |
| titulaire SIRET valide (Luhn) | 97.9 % |
| dateNotification | 100.0 % |
| lieuExecution_code | 100.0 % |

## 5. Distribution CPV (top 20, préfixe 2 chiffres)

| CPV (2) | Occurrences | % | Preset probable |
|---|---|---|---|
| 45 | 932 | 39.5 % | btp |
| 33 | 274 | 11.6 % | — |
| 71 | 203 | 8.6 % | ingenierie |
| 79 | 99 | 4.2 % | — |
| 77 | 75 | 3.2 % | — |
| 50 | 68 | 2.9 % | — |
| 34 | 65 | 2.8 % | — |
| 44 | 60 | 2.5 % | — |
| 39 | 50 | 2.1 % | — |
| 90 | 48 | 2.0 % | — |
| 92 | 43 | 1.8 % | — |
| 72 | 39 | 1.7 % | it |
| 30 | 28 | 1.2 % | — |
| 75 | 28 | 1.2 % | — |
| 09 | 28 | 1.2 % | enr |
| 15 | 25 | 1.1 % | — |
| 42 | 24 | 1.0 % | — |
| 18 | 24 | 1.0 % | — |
| 35 | 23 | 1.0 % | — |
| 85 | 23 | 1.0 % | — |

## 6. Distribution des montants (échantillon, montants > 0)

| Tranche | Nb | % |
|---|---|---|
| 0-50k€ | 635 | 27.0 % |
| 50k-500k€ | 1379 | 58.7 % |
| 500k-5M€ | 289 | 12.3 % |
| 5M-50M€ | 45 | 1.9 % |
| >50M€ | 0 | 0.0 % |

## 7. Anomalies détectées (échantillon)

- SIRETs acheteur invalides Luhn : 0 (0.0 %)
- Montants à 0 : 4  ·  négatifs : 0  ·  > 100 M€ : 0
- CPV mal formés : 0

## 8. Échantillon de 5 marchés

- **Travaux de mise en service du navire océanographique « SEPIA III »** — acheteur « INSTITUT FRANCAIS DE RECHERCHE POUR L EXPLOITATION DE LA MER » (SIRET 33071536800297), titulaire « DELAVERGNE NAVAL SERVICES », montant 142179.5 €, CPV 34500000, notifié 2026-05-31.
- **MS00 LOT 1 - PLATRERIE - PARTIE A BDC SUR BPU** — acheteur « EURO-METROPOLE DE METZ » (SIRET 20003986500106), titulaire « SOC D EXPL ENTREPRISE NESPOLA », montant 304124 €, CPV 45410000, notifié 2026-05-30.
- **RAVALEMENT DE FACADE ET TRAVAUX DIVERS 119 - RESIDENCE SAINT JACQUES A CLISSON** — acheteur « LOGEMENT ET GESTION IMMOBILIERE POUR LA REGION DE L OUEST » (SIRET 05820153400078), titulaire « BOISSEAU BATIMENT », montant 21000 €, CPV 45262690, notifié 2026-05-29.
- **GRIFOLS: Fourniture de réactifs, consommables et maintenance pour automates.** — acheteur « GROUPEMENT COOPERATION SANITAIRE - UNION DES HOPITAUX POUR LES ACHATS » (SIRET 13000222300027), titulaire « GRIFOLS FRANCE », montant 250876 €, CPV 33696500, notifié 2026-05-29.
- ** Le présent marché a pour objet la fourniture d’éléments de signalétique destinés à la réc** — acheteur « FRANCE TRAVAIL (DIRECTION GENERALE) » (SIRET 13000548100010), titulaire « ATELIERS DE CHEVREUSE SAS », montant 6249988.9 €, CPV 30195600, notifié 2026-05-29.

## 9. Recommandations parseur (Étape 1)

- **Réutiliser `connecteurs/decp_consolidee.py`** (mapping des 66 colonnes déjà écrit et testé en prod) plutôt que repartir de zéro ; en extraire la logique de normalisation vers `decp/parser.py`.
- **Champs à mapper** vers `decp_marches` : `id`→id, `codeCPV`→cpv_principal, `acheteur_id`→acheteur_siret, `titulaire_id`→titulaire_siret, `montant`→montant_eur, `dateNotification`→date_notification, `dureeMois`→duree_mois, `procedure`→procedure, `lieuExecution_code`→lieu_execution_code, `acheteur_departement_code`→departement, `acheteur_region_code`→region (géo native, **pas besoin de `ref_geo.py` ni de dérivation code postal** — déjà fourni par la consolidée).
- **Multi-titulaires** : agréger les lignes de même `id` (cf `_dedupliquer_co_titulaires`), stocker le 1er dans `titulaire_siret` et la liste dans `titulaires_json`.
- **Filtrer à l'ingestion** : `modification_id=0` ET `donneesActuelles=true` (versioning = non).
- **Rejets parseur** : pas d'`id` ; montant < 0 ou > 1 Md€ ; date non ISO. Garder un `parse_warnings` par marché.
- **Stratégie de téléchargement** : filtrer côté API par `dateNotification` (12 mois) + préfiltre CPV par preset (`codeCPV__contains` ou plage), pour ne PAS rapatrier les 3 M lignes. Alternative si volume trop gros : télécharger le Parquet consolidé et filtrer en local.

## 10. Stop-conditions — état

- Format fondamentalement différent de l'attendu : **OUI** sur la forme (API consolidée ≠ fichiers mensuels), mais la donnée est riche et exploitable — **pas un blocage**, juste une adaptation du plan de téléchargement (voir §9).
- Taux de rejet parsing estimé : faible (CPV mal formés 0.0 %, montants négatifs 0) — **< 30 %**, OK.
- Couverture des champs de matching (CPV/SIRET/date) : élevée — **viable** pour l'Étape 3.

---

**Checkpoint** : valider ce rapport avant de lancer l'Étape 1 (parseur + ingestion 12 mois). Décision attendue de Younes sur la stratégie de téléchargement (API tabulaire filtrée vs Parquet).
