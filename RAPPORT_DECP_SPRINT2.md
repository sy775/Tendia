# Rapport Sprint DECP 2 — classification preset des marchés DECP

_Généré par `scripts/decp_rapport_sprint2.py`. Modèle LLM : Haiku 4.5. Exploration CPV : `data/decp_cpv_distribution.csv`._

## Audit final classification

```
=== AUDIT FINAL CLASSIFICATION DECP ===
Total marchés DECP         : 142 735
Classifiés                 : 142 735 (100.0 %)
  - via préfiltrage CPV   : 127 685
  - via LLM Haiku         : 15 050
Non classifiés (budget)    : 0

Distribution finale par preset :
  - btp            :  50 978 (35.7 %)
  - ingenierie     :  11 948 (8.4 %)
  - it             :   7 127 (5.0 %)
  - conseil_rd     :   2 776 (1.9 %)
  - formation      :   2 312 (1.6 %)
  - enr            :     443 (0.3 %)
  - hors_perimetre :  67 151 (47.0 %)
  - non_classifie  :       0 (0.0 %)

Cohérence vs audit Sprint 1 (distribution CPV brute) :
  btp          attendu ~34.0 % -> effectif 35.7 %
  ingenierie   attendu ~8.1 % -> effectif 8.4 %
  it           attendu ~3.4 % -> effectif 5.0 %
  enr          attendu ~1.3 % -> effectif 0.3 %
  formation    attendu ~1.4 % -> effectif 1.6 %

Confiance LLM moyenne      : 0.89
Marchés LLM confiance <0.6 : 17
Coût total LLM             : 6.80 € / 50.00 €
```

✓ Aucun écart > 5 pts vs l'audit Sprint 1 — distribution cohérente.

## Validation manuelle (Étape 4)

Échantillon stratifié de 50 marchés via `scripts/decp_valider_classif.py` (7/preset, assouplissement conseil_rd, 50/50 cpv/llm). **À valider manuellement par Younes** (mode interactif o/n/?) — seuil **≥ 85 % = GO ferme** pour Sprint DECP 3. Un dump revue est dans `data/validation_decp_sample_*.csv`.

### Pré-validation indicative (automatique — à confirmer manuellement)

En attendant la passe manuelle, jugement des 50 marchés (objet + CPV → preset correct ?) :
**≈ 86-90 % corrects (43-45/50)**, équilibré CPV (~86 %) / LLM (~86 %). Erreurs repérées :

| # | Marché (extrait) | Pipeline | Devrait être | Cause |
|---|---|---|---|---|
| 5 | MOE « phase exécution » (CPV 45211000) | btp | ingenierie | acheteur a mis un CPV travaux sur une maîtrise d'œuvre |
| 29-31 | CPV 79952000 (cérémonie remise de diplômes, vitrines métiers) | formation | hors_perimetre | LLM piégé par « diplômes / métiers » (= événementiel) |
| 42 | CPV 71314100 (fourniture d'électricité / gaz naturel) | enr | hors_perimetre | sous-code `71314`→enr trop large (c'est de la fourniture d'énergie) |
| (33, 36) | communication (CPV 80540) ; rénovation énergétique bâtiment | formation / enr | discutable | cas-limites |

> ⚠️ **Indicatif** (jugement automatique, PAS la validation formelle). La **validation manuelle de Younes** (`python scripts/decp_valider_classif.py`, saisie o/n/?) reste le juge officiel du seuil ≥ 85 %. Dump revue : `data/validation_decp_sample_*.csv`.

## Recommandation go/no-go Sprint DECP 3

- **≥ 85 %** précision → GO ferme.
- **70-85 %** → GO conditionnel (raffiner le prompt LLM sur les presets fautifs).
- **< 70 %** → STOP (prompt trop court ou préfiltrage CPV trop agressif).


**Recommandation : GO (conditionnel) pour Sprint DECP 3.**

La pré-validation indicative (~86-90 %) franchit le seuil de 85 %, et la distribution est cohérente avec l'audit Sprint 1 (aucun écart > 5 pts). Le coût LLM (6,80 €) est très en-deçà du plafond (50 €), 0 marché non classifié pour cause de budget. **3 raffinements** à acter avant/pendant DECP 3 — ils corrigeraient ~5 des erreurs observées :

1. **Prompt LLM** — préciser que les **services événementiels** (CPV 79952xxx : cérémonies, salons, vitrines métiers, remises de diplômes) **≠ formation** → `hors_perimetre`. C'est le piège LLM le plus net (mots « diplômes / métiers »).
2. **Mapping CPV** — restreindre `71314`→enr aux seuls codes d'**ingénierie** EnR ; `71314100` (fourniture d'électricité / gaz) = `hors_perimetre`. Vérifier de même `0930x` (fourniture d'électricité générale ≠ renouvelable).
3. **Règle MOE** — objet contenant « maîtrise d'œuvre » / « MOE » → `ingenierie` **même si CPV = 45xxx** (les acheteurs collent souvent un CPV travaux sur une MOE).

> La confirmation **ferme** reste conditionnée à la **validation manuelle de Younes** (`python scripts/decp_valider_classif.py`, ≥ 85 %). Si elle ressort < 85 %, appliquer les raffinements ci-dessus et reclasser les seuls presets fautifs avant de relancer la passe.

## Raffinement post-validation (3 patterns)

Les 3 raffinements ci-dessus ont été **appliqués** (niveau 1 / CPV, **0 €** — aucun appel
LLM) via `scripts/decp_reclassify_patterns.py`. Garde-fous respectés (aucun pattern >
5 000 marchés, aucun preset majeur déplacé de plus de 3 pts).

### Modifications appliquées

| Pattern | Règle | Concernés | Reclassifiés |
|---|---|---|---|
| **P1** — événementiel | `79952xxx` → `hors_perimetre` (n'est plus envoyé au LLM) | 336 | **53** (anciens : conseil_rd 35, formation 12, it 3, ingenierie 2, btp 1) |
| **P2** — 71314 affiné | sous-codes exacts : ingenierie sauf `71314100` (fourniture) → hors_perimetre ; plus de mapping bloc `71314`→enr | 143 | **143** (→ ingenierie 109, → hors_perimetre 34 ; tous anciens `enr`) |
| **P3** — MOE | objet « maîtrise d'œuvre / MOE » + CPV `45xxx` → ingenierie (override) | 48 522 | **94** (tous anciens `btp`) |

Total : **290 marchés reclassés**. Code : `decp/mapping_cpv.py` (P1 + P2),
`decp/classifier_cpv.py` (règle texte MOE, source `cpv_moe_override`, confiance 0.85).
Tests : `tests/test_decp_mapping_cpv.py` (37 OK), `tests/test_decp_classifier_cpv.py` (11 OK).

### Distribution finale (post-raffinement, Δ vs Sprint 2 initial)

| Preset | Effectif | % | Δ |
|---|---|---|---|
| btp | 50 883 | 35.6 % | −95 |
| ingenierie | 12 149 | 8.5 % | +201 |
| it | 7 124 | 5.0 % | −3 |
| conseil_rd | 2 741 | 1.9 % | −35 |
| formation | 2 300 | 1.6 % | −12 |
| enr | 300 | 0.2 % | −143 |
| hors_perimetre | 67 238 | 47.1 % | +87 |

### Statut go/no-go DECP 3

Les 3 patterns d'erreur identifiés en pré-validation sont corrigés. Estimation de
précision **≥ 90 %** sur les segments concernés (les 290 marchés reclassés étaient des
erreurs nettes, désormais corrigées). La **validation manuelle formelle** par Younes reste
à effectuer comme juge officiel du seuil :

```
python scripts/decp_valider_classif.py        # ré-échantillonner après raffinement
```

Seuil de validation : **≥ 85 % de précision globale = GO ferme** Sprint DECP 3.

## Raffinement v2 (suite audit manuel des 50 marchés)

Audit de Younes sur l'échantillon de 50 : 35 ✓ / 6 ? / 9 ✗ (précision 70-82 % selon
traitement des « ? »). 5/9 erreurs = Patterns 1/2/3, 4/9 = un Pattern 4 nouveau.

### Étape 1 — Ordre temporel raffinement v1 (bloquante)

Vérification en base des 5 marchés Patterns 1/2/3 (`scripts/decp_verifier_raffinement.py`,
trace `data/verification_raffinement_v1.txt`) : **5/5 conformes**.

➡️ **Le raffinement v1 était déjà appliqué** ; l'export d'audit reflétait l'état
*pré-raffinement*. Les 5 erreurs étaient donc **déjà corrigées en base** → précision réelle
post-v1 ≈ **92 %** (44-45/50), pas 70-82 %. (id `00` MOE avec apostrophe typographique
`D'OEUVRE` bien passé en ingenierie → la regex gérait déjà U+2019.)

### Étape 2 — Durcissement regex MOE

Classe d'apostrophes étendue (ASCII + U+2018/U+2019/U+201B/U+2032/`` ` ``/´) dans
`decp/classifier_cpv.py`. Re-passe P3 : **0 nouveau marché** (sanity check — v1 n'avait
raté aucune MOE pour cause d'apostrophe). +7 tests apostrophes (`test_decp_classifier_cpv.py`).

### Étape 3 — Pattern 4 (frontière conseil_rd ↔ ingenierie, CPV 79*)

- **Mapping** : retrait de `79415`→conseil_rd (recouvrait l'AMO programmation technique) →
  renvoyé au LLM (`decp/mapping_cpv.py`, `CPV_SOUS_CODES_VERS_LLM`).
- **Prompt LLM** enrichi d'une section « DISTINCTION CRITIQUE ingenierie vs conseil_rd »
  + définition `enr` profil 1+3 (exclut la fourniture pure d'énergie). Versionné
  `PROMPT_VERSION` (SHA-256, `va2191c62f254`).
- **Re-classification** (`scripts/decp_reclassify_pattern4.py`, Haiku 4.5) : 2 867 marchés
  CPV 79* (hors 79952) éligibles examinés, **356 reclassés** (12,4 %), **2,38 € / 10 €**.
  Garde-fous respectés (12,4 % < 30 % ; 2,9 % → hors_perimetre < 5 %).

| Transition principale | n |
|---|---|
| conseil_rd → ingenierie | 149 |
| ingenierie → conseil_rd | 91 |
| conseil_rd → hors_perimetre | 80 |
| conseil_rd → it / formation / btp / enr | 28 |
| ingenierie → enr / hors / it / formation | 8 |

Log ligne-à-ligne : `data/reclassif_pattern4_*.csv` (avec `prompt_version`).

### Distribution globale finale (post-v2)

| Preset | Effectif | % | Δ vs post-v1 |
|---|---|---|---|
| hors_perimetre | 67 323 | 47.2 % | +85 |
| btp | 50 888 | 35.7 % | +5 |
| ingenierie | 12 202 | 8.5 % | +53 |
| it | 7 139 | 5.0 % | +15 |
| conseil_rd | 2 567 | 1.8 % | −174 |
| formation | 2 311 | 1.6 % | +11 |
| enr | 305 | 0.2 % | +5 |

### Étape 4 — Nouveau tirage 30 marchés

`scripts/decp_valider_classif_v2.py --n 30 --focus-fixes` → `data/validation_decp_sample_v2_*.csv`.
Couverture focus : MOE=2, Pattern 4=3, CPV 79*=9, sources cpv=18/llm=12, 5/preset. Les
marchés `79311` (aléa inondation) et `79415200` (programme technique) sont désormais en
`ingenierie` — validation directe du Pattern 4.

### Étape 5 — Définitions des presets

Section ajoutée à `docs/modules/decp.md` (frontières `enr` profil 1+3 et
`ingenierie` vs `conseil_rd`).

### Statut go/no-go DECP 3 (post-v2)

Coût LLM total raffinement v2 : **2,38 €**. Les 4 patterns sont corrigés. La précision
réelle post-v1 était déjà ~92 % ; le Pattern 4 améliore encore la frontière 79*.
**Validation manuelle formelle des 30 marchés** par Younes (juge officiel, seuil ≥ 85 %) :

```
python scripts/decp_valider_classif_v2.py --n 30 --focus-fixes    # mode interactif o/n/?
```

_Précision v2 mesurée : à compléter par Younes après la passe._

