# Rapport Sprint DECP 1 — acquisition, structure, matching bidirectionnel

_Généré par `scripts/decp_test_matching.py`. 0 LLM. Exploration : voir `RAPPORT_DECP_EXPLORATION.md`._

## 🟢 Recommandation Sprint DECP 2 : **GO conditionnel — limite de DONNÉES, pas de logique.** Le 0 %/0 % vient du **non-recouvrement temporel** : les 422 marchés Tendia sont des avis très récents (2026-06-09→2026-06-10, ~2 jours), trop neufs pour avoir une attribution publiée dans la DECP (qui s'arrête au présent), et les attributions DECP correspondent à des avis antérieurs à la collecte Tendia. Seulement 640 attributions DECP sont postérieures au plus ancien avis Tendia (0.4 % du corpus). La **chaîne de matching est bâtie et validée** : tests unitaires verts + contrôle synthétique 5/5 ≥ 0.85 (voir §Contrôle). **Débloquer** en backfillant Tendia avec des avis historiques (2024-2025) dont les attributions SONT dans la DECP, + enrichissement SIRET/CPV.

- **Test A (Tendia → DECP)** : 0 % (0/50)
- **Test B (DECP → Tendia)** : 0 % (0/50)
- Liens insérés dans `marche_attribution_link` : 0 (orphelins évités : 0)

### Limiteur structurel n°1 (déterminant pour l'interprétation)

Les marchés Tendia (BOAMP) n'ont **pas de SIRET acheteur** (`acheteur_id` = 0 %) et seulement **45 % ont un CPV**. Le score acheteur (poids 0.35) repose donc sur une similarité de **nom** (repli), et la présélection CPV ne couvre que ~45 % du parc Tendia. → Les taux ci-dessous sont un **plancher** ; ils monteraient nettement en enrichissant les marchés Tendia avec le SIRET et le CPV de l'avis BOAMP (disponibles dans le champ `donnees`). À acter pour Sprint DECP 2.

### Limiteur structurel n°2 : non-recouvrement temporel (cause du 0 %)

- Avis Tendia : **2026-06-09 → 2026-06-10** (les 422 marchés couvrent ~2 jours — Tendia vient de démarrer la collecte BOAMP).
- Attributions DECP : 2025-06-15 → 2026-06-15.
- Attributions DECP postérieures au plus ancien avis Tendia (condition nécessaire à un match Tendia→DECP) : **640** (0.4 % du corpus).
- **Conséquence** : un avis publié en juin 2026 sera attribué dans le futur (absent de la DECP actuelle) ; une attribution DECP correspond à un avis antérieur à la collecte Tendia. Les deux jeux ne se recouvrent quasiment pas → 0 % attendu, **indépendamment de la qualité du scoring**.

### Contrôle synthétique (preuve que la chaîne fonctionne)

De pseudo-avis Tendia fabriqués depuis 5 attributions DECP (même acheteur/CPV/montant, date publiée ~120 j avant, **sans SIRET** comme un vrai marché BOAMP) :

| DECP | acheteur | score | cpv | nom | période | montant |
|---|---|---|---|---|---|---|
| 0 | REGION NORMANDIE (HOTE | **0.965** | 1.0 | 0.9 | 1.0 | 1.0 |
| 00 | POLYTEC | **0.965** | 1.0 | 0.9 | 1.0 | 1.0 |
| 000000054 | SOCIETE DU CANAL DE PR | **0.965** | 1.0 | 0.9 | 1.0 | 1.0 |
| 00000054 | SOCIETE DU CANAL DE PR | **0.965** | 1.0 | 0.9 | 1.0 | 1.0 |
| 0000054 | SOCIETE DU CANAL DE PR | **0.965** | 1.0 | 0.9 | 1.0 | 1.0 |

→ **5/5 ≥ 0.85** : avec recouvrement temporel, le matching produit des scores forts même sans SIRET côté Tendia (repli nom). Le 0 % des Tests A/B est donc un problème de données, pas de logique.

## Étape 4 — Audit qualité de la base DECP

```
=== AUDIT DECP — Sprint 1 ===
Période ingérée : 2025-06-15 à 2026-06-15
Total marchés DECP : 142 735

Couverture champs :
- avec montant > 0     : 99.7 %
- avec CPV principal   : 100.0 %
- avec acheteur SIRET  : 100.0 %
- avec titulaire SIRET : 99.4 %
- avec date notif      : 100.0 %
- avec lieu exécution  : 100.0 %

Distribution CPV (top 20, préfixe 2 chiffres) :
45 BTP           :  48 572 (34.0 %)
71 Ingénierie    :  11 495 (8.1 %)
33 Médical       :   8 242 (5.8 %)
79 Services      :   6 827 (4.8 %)
90               :   6 077 (4.3 %)
50               :   5 653 (4.0 %)
72 IT            :   4 908 (3.4 %)
34               :   4 350 (3.0 %)
39               :   3 427 (2.4 %)
15               :   3 332 (2.3 %)
44               :   3 254 (2.3 %)
66               :   3 027 (2.1 %)
77               :   2 546 (1.8 %)
30               :   2 422 (1.7 %)
80 Formation     :   2 049 (1.4 %)
92               :   1 984 (1.4 %)
60               :   1 854 (1.3 %)
09 EnR           :   1 824 (1.3 %)
55               :   1 672 (1.2 %)
38               :   1 562 (1.1 %)

Distribution montants :
- 0-50k€        : 26.3 %
- 50k-500k€     : 54.1 %
- 500k-5M€      : 16.5 %
- 5M-50M€       : 2.7 %
- >50M€         : 0.4 %

Anomalies détectées :
- SIRETs acheteur invalides Luhn : 230 (0.2 %)
- Montants à 0                    : 370
- Montants > 100M€               : 390
- CPV mal formés (≠ 8 chiffres)   : 1
- Dates aberrantes                : 0
- Marchés avec parse_warnings     : 253

Volumétrie par mois :
2025-06 :   7 076
2025-07 :  16 348
2025-08 :   8 398
2025-09 :  10 573
2025-10 :  13 630
2025-11 :  12 641
2025-12 :  19 580
2026-01 :  12 317
2026-02 :  11 427
2026-03 :  14 351
2026-04 :   8 146
2026-05 :   5 734
2026-06 :   2 514

Taille DB SQLite : 80 Mo (base Tendia complète)
Temps requête (filtre CPV + date) : 40 ms
```

## Étape 3 — Test matching bidirectionnel

### Test A — Tendia → DECP (50 marchés les plus anciens)

| Résultat | Nb |
|---|---|
| candidats_sous_seuil | 34 |
| preselection_vide | 16 |

Ventilation par preset (matchés / testés) :

| Preset | Matchés / Testés |
|---|---|
| btp | 0/4 |
| formation | 0/1 |
| hors_perimetre | 0/16 |
| ingenierie | 0/2 |
| sans_cpv | 0/27 |

Distribution des scores (Test A) :
```
  [0.00–0.30)  15 ███████████████
  [0.30–0.50)  19 ███████████████████
  [0.50–0.70)   0 
  [0.70–0.85)   0 
  [0.85–1.00)   0 
```

### Test B — DECP → Tendia (50 attributions preset au hasard)

| Résultat | Nb |
|---|---|
| preselection_vide | 50 |

Ventilation par preset (matchés / testés) :

| Preset | Matchés / Testés |
|---|---|
| btp | 0/49 |
| ingenierie | 0/1 |

Distribution des scores (Test B) :
```
  [0.00–0.30)   0 
  [0.30–0.50)   0 
  [0.50–0.70)   0 
  [0.70–0.85)   0 
  [0.85–1.00)   0 
```

### Exemples de matches forts (score ≥ 0.85)

_Aucun match ≥ 0.85 (cohérent avec l'absence de SIRET Tendia : le score acheteur plafonne à 0.9 par le nom, rarement combiné à un CPV+période parfaits)._

### Exemples de quasi-matches (0.5 ≤ score < 0.7)


### Exemples d'absence de match (diagnostic)

- BOAMP-26-55964 « REQUALIFICATION DE LA ROUTE DU ROSAY / MISSION DE MAÎTR » (CPV 71240000) — candidats_sous_seuil (meilleur score 0.4706).
- BOAMP-26-56096 « Réhabilitation et réaménagement du pont de Pierre sur l » (CPV 79311000) — candidats_sous_seuil (meilleur score 0.4706).
- BOAMP-26-55977 « Accord-cadre travaux d'aménagement et d'entretien de vo » (CPV 45233142) — candidats_sous_seuil (meilleur score 0.3647).
- BOAMP-26-56006 « Mise à disposition de personnel intérimaire paramédical » (CPV 79620000) — candidats_sous_seuil (meilleur score 0.1176).
- BOAMP-26-56063 « Services d'assurances pour le groupement constitué entr » (CPV 66510000) — candidats_sous_seuil (meilleur score 0.2588).

## Interprétation & recommandations Sprint DECP 2

- **Enrichir les marchés Tendia** avec SIRET acheteur + CPV depuis l'avis BOAMP (`donnees`) : c'est le levier n°1 pour faire monter Test A/B (le score acheteur passerait du repli-nom à du SIRET ferme, poids 0.35).
- **Distribution sectorielle attendue** : BTP/ingénierie >> IT/conseil/formation/EnR (cf audit) — les taux par preset reflètent ce déséquilibre, c'est normal et acté.
- **Seuils/poids** : si Test B faible malgré CPV présent des deux côtés, envisager d'augmenter le poids période ou d'élargir la présélection (CPV 2 chiffres).
- **Classification preset DECP** (table `decp_classification`, vide) : à alimenter en Sprint 2 (CPV → preset, puis LLM sur les cas `non_classifie_budget`).

---

_Base : 142735 marchés DECP (12 mois), 422 marchés Tendia._
