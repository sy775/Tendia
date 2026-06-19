# Exploration DECP préliminaire

_Tâche 5 — exploration légère, 0 appel LLM. Source : API tabulaire data.gouv.fr (DECP consolidée, ressource `22847056-…`). **NE PAS confondre avec le sprint DECP complet (non lancé).**_

- **Volume total DECP** : 3,080,553 lignes (marchés attribués / actes).
- Échantillon analysé : **1000 records** (10 pages × 100, ordre API).
- Connecteur existant : `connecteurs/decp_consolidee.py` (même ressource).

## Structure des données (champs)

Champs présents (record type) :
```
__id, uid, id, nature, acheteur_id, acheteur_nom, titulaire_id, titulaire_typeIdentifiant, titulaire_nom, objet, montant, type, codeCPV, procedure, techniques, dureeMois, dureeRestanteMois, offresRecues, dateNotification, datePublicationDonnees, formePrix, typesPrix, attributionAvance, tauxAvance, marcheInnovant, modalitesExecution, considerationsSociales, considerationsEnvironnementales, ccag, sousTraitanceDeclaree, typeGroupementOperateurs, origineUE, origineFrance, lieuExecution_code, lieuExecution_typeCode, idAccordCadre, titulaire_distance, acheteur_categorie, acheteur_commune_code, acheteur_commune_nom, acheteur_departement_code, acheteur_departement_nom, acheteur_region_code, acheteur_region_nom, acheteur_latitude, acheteur_longitude, titulaire_categorie, titulaire_commune_code, titulaire_commune_nom, titulaire_departement_code, titulaire_departement_nom, titulaire_region_code, titulaire_region_nom, titulaire_latitude, titulaire_longitude, modification_id, donneesActuelles, sourceDataset, sourceFile
```

## Qualité (taux de remplissage sur l'échantillon)

| Champ | % rempli |
|---|---|
| `acheteur_id` | 100% |
| `codeCPV` | 100% |
| `objet` | 100% |
| `dateNotification` | 100% |
| `lieuExecution_code` | 100% |
| `nature` | 100% |
| `acheteur_nom` | 99% |
| `titulaire_id` | 99% |
| `titulaire_nom` | 99% |
| `montant` | 99% |
| `dureeMois` | 99% |
| `procedure` | 99% |
| `offresRecues` | 71% |

- Montant exploitable : **99%** des records, médiane ≈ 288,203 €, min -855 / max 111,938,436.

## Top 20 codes CPV (échantillon)

| CPV (8) | Occurrences |
|---|---|
| 45000000 | 56 |
| 45112500 | 23 |
| 77310000 | 22 |
| 71000000 | 22 |
| 45312200 | 22 |
| 45210000 | 20 |
| 45233140 | 20 |
| 45214200 | 17 |
| 45232420 | 15 |
| 71300000 | 14 |
| 45233141 | 13 |
| 71241000 | 13 |
| 45421000 | 13 |
| 45214000 | 13 |
| 45330000 | 11 |
| 45453000 | 11 |
| 45232410 | 9 |
| 45331000 | 9 |
| 45200000 | 8 |
| 45220000 | 8 |

## 5 exemples de marchés

- **Maintenance et entretien des onduleurs de puissance inférieure à 50 kVA** — acheteur « COMMUNAUTE D'UNIVERSITES ET ETABLISSEMEN » (SIRET 13002132200016), titulaire « SPELEM (SID) », montant 15000 €, CPV 50711000, notifié 2026-06-13.
- **CONFECTION ET LIVRAISON DE REPAS EN LIAISON FROIDE PORTAGE** — acheteur « COMMUNE DE BRUNOY (MAIRIE) » (SIRET 21910114400018), titulaire « ELIOR RESTAURATION FRANCE », montant 300000 €, CPV 55521100, notifié 2026-06-13.
- **Le présent marché a pour objet d’assurer la chaîne complète de support aux utilisateurs, d** — acheteur « MINISTERE DE LA CULTURE » (SIRET 11004601800013), titulaire « GROUPE VITAL », montant 111938436.4 €, CPV 72253000, notifié 2026-06-12.
- **MAINTENANCE PREVENTIVE ET CORRECTIVE DES SYSTEMES DE SECURITE INCENDIE DES BATIMENTS IGBMC** — acheteur « UNIVERSITE DE STRASBOURG » (SIRET 13000545700010), titulaire « CHUBB FRANCE », montant 29040.22 €, CPV 31625200, notifié 2026-06-12.
- **Rénovation de 20 coins cuisines de la résidence étudiante Bonnamour de l’ENS de Lyon.** — acheteur « ECOLE NORMALE SUPERIEURE DE LYON » (SIRET 13000812100019), titulaire « DAVID FOURNEL », montant 52500 €, CPV 45421151, notifié 2026-06-12.

## Faisabilité technique (matching / calibration)

- **Calibration des montants** : `montant` + `codeCPV` + `dureeMois` exploitables → comparables par CPV pour estimer les fourchettes (cf `llm_calibration`). Faisable.
- **Analyse concurrentielle** : `titulaire_id/nom` + `acheteur_id/nom` → attributaires historiques par acheteur/secteur (cf `concurrence.py`). Faisable.
- **Volume** : 3 M+ lignes → ne PAS tout charger en mémoire ; filtrer par CPV/acheteur/date via l'API tabulaire (paginée) ou un téléchargement de fichier filtré.
- **Clé de jointure** : `acheteur_id` (SIRET) + `codeCPV` permettent de relier aux marchés Tendia (qui ont `cpv_principal` + acheteur). Qualité SIRET à confirmer sur un échantillon plus large.

> Reste à faire (sprint DECP complet, non lancé) : connecteur de masse, indexation par CPV/SIRET, intégration calibration + concurrence, fraîcheur des données.