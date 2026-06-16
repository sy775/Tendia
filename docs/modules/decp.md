# Module `decp/` — Données Essentielles de la Commande Publique

Acquisition, parsing, stockage et matching de la DECP (attributions publiques
françaises). Livré au **Sprint DECP 1**. 0 LLM dans ce module.

## Source

**DECP consolidée** (Colin Maudry / Colmo), mise à jour quotidienne, exposée par
l'**API tabulaire** data.gouv.fr — ressource `22847056-61df-452d-837d-8b8ceadbfc52`.
Ce n'est PAS une série de fichiers mensuels : c'est un dataset unique (~3 M lignes,
66 colonnes plates) requêté par pagination + filtres (`__greater`/`__less`/`__exact`).
`page_size` plafonné à **100**. Accès direct (pas de proxy). Voir
`RAPPORT_DECP_EXPLORATION.md`.

## Fichiers

| Fichier | Rôle |
|---|---|
| `decp/telecharger.py` | Fetch parallèle de l'API (filtres `modification_id=0` + `donneesActuelles=true`, pagination 100/page × 12 workers). Wrapper au-dessus de `connecteurs/decp_consolidee.py`. |
| `decp/parser.py` | Normalisation record brut → schéma `decp_marches`. `valider_siret` (Luhn + exception La Poste), `normaliser_cpv`, `agreger_multi_titulaires` (dédup par `id`). |
| `decp/db.py` | Schéma SQLite (3 tables, dans `data/tendia.db`), `init_schema`, `inserer_marches` (INSERT OR REPLACE), `inserer_lien`, `compter_marches`. |
| `decp/matching.py` | `scorer_match` (CPV 0.30 / acheteur 0.35 / période 0.20 / montant 0.15, redistribution si montant absent) + `verifier_marche_tendia_existe`. |
| `decp/audit.py` | `auditer()` → bloc chiffré (couverture, distributions, anomalies). |
| `decp/cli.py` | `python -m decp.cli ingest \| ingest-annee \| audit`. |
| `scripts/decp_explorer.py` | Étape 0 — exploration → `RAPPORT_DECP_EXPLORATION.md`. |
| `scripts/decp_test_matching.py` | Étape 3+4 — test bidirectionnel + audit → `RAPPORT_DECP_SPRINT1.md`. |
| `tests/test_decp_*.py` | Tests unitaires (parser, db, matching). |

## Schéma SQLite (dans `data/tendia.db`)

- **`decp_marches`** — 1 ligne = 1 attribution (déduplication multi-titulaires par `id`).
- **`marche_attribution_link`** — lien marché Tendia ↔ attribution DECP (DECP 4).
  `marche_tendia_id` = **id KV-JSON** de la collection `marches` (ex. `BOAMP-26-57070`) ;
  **pas de contrainte FK SQL** (la cible est une ligne JSON de `kv_storage`).
  `decp.matching.verifier_marche_tendia_existe` garde contre les liens orphelins.
- **`decp_classification`** — preset par marché DECP (FK réelle vers `decp_marches`).
  Vide au Sprint 1, alimentée au Sprint 2.

## Pipeline d'ingestion (pattern progressif)

```bash
python -m decp.cli ingest --dry-run --limite 500   # parse + stats, 0 écriture
python -m decp.cli ingest --limite 100             # 100 lignes en DB
python -m decp.cli ingest                           # 12 derniers mois (~196k lignes)
python -m decp.cli audit                            # audit chiffré
python scripts/decp_test_matching.py                # test matching + rapport final
```

## Décisions actées (Sprint 1)

- **Stratégie A** : pagination API filtrée par date (CPV filtré en SQL local), repli
  Parquet (B) non implémenté (à activer si limites API non récupérables).
- Filtres systématiques `modification_id=0` + `donneesActuelles=true` (versioning DECP = non).
- Géo **native** (`acheteur_departement_code`/`region_code`) — pas de `ref_geo.py`.
- **Limiteur connu** : les marchés Tendia (BOAMP) n'ont ni SIRET acheteur (0 %) ni CPV
  systématique (45 %). Le score acheteur tombe en repli sur le nom. Levier Sprint 2 :
  enrichir Tendia avec SIRET+CPV depuis l'avis BOAMP (`donnees`).

## Classification preset (Sprint DECP 2)

Affecte un preset Tendia à chacun des **142 735** marchés DECP via un pipeline à 2 niveaux
(CPV d'abord, LLM Haiku 4.5 sur le reliquat ambigu). Plafond budget LLM **50 €** —
consommé : **6,80 €**. Voir `RAPPORT_DECP_SPRINT2.md`.

| Fichier | Rôle |
|---|---|
| `decp/mapping_cpv.py` | `classer_par_cpv(cpv) → (preset, source)`. Ordre : exact → sous-codes (5/4/3 chiffres) → ambigus explicites (`09`/`50`/`79` → LLM) → préfixe 2 → hors-périmètre → inconnu. Préfixes : `45`→btp, `71`→ingenierie, `72`/`48`→it, `80`→formation. Sous-codes EnR (`0933x`, `45251`, `71314`), conseil_rd (`731`/`732`/sous-codes `79`). |
| `decp/classifier_cpv.py` | `classer_marche_cpv` — applique le mapping + table de **confiance** (cpv_exact 1.0, préfixe_5/4/3 0.9, préfixe_2 0.75, hors 1.0, données_insuffisantes 0.7). Cas spécial `00000000` : objet < 10 car. → `hors_perimetre` (0.7), sinon → LLM. |
| `decp/classifier_llm.py` | `classer_llm` (Haiku 4.5, `max_tokens=50`, 7 presets), `BudgetTracker` thread-safe (Lock), `_cout_eur` ($1/$5 × 0,95). Parallélisé par chunks (ThreadPoolExecutor). |
| `scripts/decp_classify_cpv.py` | Niveau 1 — classification CPV de masse (écrit `decp_classification`, source `cpv*`). |
| `scripts/decp_classify_llm.py` | Niveau 2 — LLM sur les ambigus (source `llm`), arrêt au plafond budget. |
| `scripts/decp_valider_classif.py` | Échantillon stratifié 50 marchés (7/preset, 50/50 cpv/llm), mode interactif o/n/? + `--dump` CSV. |
| `scripts/decp_rapport_sprint2.py` | Audit final + génération `RAPPORT_DECP_SPRINT2.md` (distributions, cohérence vs Sprint 1, coût). |
| `scripts/decp_explore_cpv.py` | Distribution CPV brute → `data/decp_cpv_distribution.csv` (calibrage du mapping). |
| `scripts/decp_reclassify_patterns.py` | Raffinement post-validation (3 patterns), re-classification CPV 0 € avec garde-fous. |
| `scripts/decp_verifier_raffinement.py` | v2 Étape 1 — vérifie en base l'application du raffinement v1 (5 marchés témoins). |
| `scripts/decp_reclassify_pattern4.py` | v2 Étape 3 — re-classification LLM des CPV 79* (frontière conseil_rd ↔ ingenierie), plafond + garde-fous. |
| `scripts/decp_valider_classif_v2.py` | v2 Étape 4 — tirage 30 marchés `--focus-fixes` (sur-représente MOE / Pattern 4 / CPV 79*). |
| `tests/test_decp_mapping_cpv.py`, `tests/test_decp_classifier_cpv.py`, `tests/test_decp_classifier_llm.py` | Tests unitaires (mapping + règle MOE/apostrophes + budget/coût LLM). |

**Résultats** : 127 685 classés par CPV (niveau 1, 89,5 %), 15 050 par LLM (10,5 %), 0 reliquat
budget. Distribution : hors_perimetre 47 %, btp 35,7 %, ingenierie 8,4 %, it 5,0 %, conseil_rd 1,9 %,
formation 1,6 %, enr 0,3 %. Pré-validation indicative **~86-90 %** (≥ seuil 85 %) →
**GO conditionnel** Sprint 3, sous réserve de la validation manuelle formelle.

**Raffinement post-validation (appliqué, 0 €)** — 290 marchés reclassés via
`decp_reclassify_patterns.py` : (1) `79952xxx` événementiel → hors_perimetre ;
(2) `71314` affiné (ingenierie sauf `71314100` fourniture → hors_perimetre, plus de bloc
`71314`→enr) ; (3) règle texte MOE (`mapping_cpv.py` / `classifier_cpv.py`) → ingenierie
même si CPV `45xxx` (source `cpv_moe_override`). Distribution finale : btp 35,6 %,
ingenierie 8,5 %, enr 0,2 %, hors_perimetre 47,1 % (deltas < 0,2 pt).

**Raffinement v2 (suite audit Younes)** — vérifié que v1 était bien appliqué (audit fait
sur l'export pré-raffinement → précision réelle ~92 %). Durcissement regex MOE (apostrophes
typographiques) et **Pattern 4** : retrait `79415`→conseil_rd + prompt LLM enrichi
(distinction ingenierie/conseil_rd, `enr` profil 1+3) + re-classification LLM des CPV 79*
(356/2867 reclassés, **2,38 €**). Prompt versionné (`PROMPT_VERSION`). Voir
`RAPPORT_DECP_SPRINT2.md` § Raffinement v2.

## Définitions des presets

Cette section documente les frontières métier de chaque preset Tendia, telles
qu'elles s'appliquent au pipeline de classification DECP. À mettre à jour à
chaque décision frontière prise pendant un sprint.

### enr — Énergies renouvelables (validé Sprint DECP 2 raffinement v2)

**Cible** : installateurs, intégrateurs, EPC (Engineering Procurement Construction),
bureaux d'études et AMO d'installations d'énergies renouvelables (profils 1 + 3).

**Inclus** :
- Travaux d'installation EnR (photovoltaïque, éolien, biomasse, géothermie, hydraulique)
- Études techniques EnR (faisabilité, dimensionnement, audits)
- AMO sur projets EnR
- Maintenance d'installations EnR
- Marchés mixtes incluant pose d'équipements EnR

**Exclus (vont en hors_perimetre)** :
- Fourniture/achat d'énergie (même renouvelable), y compris contrats PPA et autoconsommation collective (profil 2)
- Services de gestion énergétique pure (sans EnR spécifique → ingenierie selon cas)

**Justification** : Tendia cible des fournisseurs de services/travaux, pas des
producteurs/fournisseurs de commodités. Cohérent avec les 5 autres presets.
Mise en œuvre : `71314100` (fourniture élec/gaz) → hors_perimetre ; le prompt LLM
exclut explicitement la fourniture pure d'énergie.

### ingenierie vs conseil_rd — frontière (validé raffinement v2, Pattern 4)

Confusion fréquente sur les CPV `79xxx`. Règle tranchée :
- **ingenierie** : étude *technique* (thermique, environnement/PPRN, structure, fluides,
  géotechnique), maîtrise d'œuvre, AMO bâtiment/aménagement, programmation technique de
  projet, audit technique/énergétique, géomètre, topographie.
- **conseil_rd** : conseil *stratégique*/organisationnel, conseil/AMO juridique ou
  financière, évaluation de politiques publiques, études de marché/socio-économiques,
  R&D scientifique, AMO foncier.

Mise en œuvre : retrait du mapping CPV `79415`→conseil_rd (trop large : recouvrait l'AMO
programmation) → renvoyé au LLM ; prompt LLM enrichi d'une section « DISTINCTION CRITIQUE ».

### Autres presets

btp, it, formation : voir le prompt système (`decp/classifier_llm.py`) et le mapping
CPV (`decp/mapping_cpv.py`). À documenter au fil des décisions frontière.

## Hors-scope Sprint 2 (→ Sprint 3)

Triangulation par brief, job mensuel automatisé, intégration UI, validation manuelle formelle.
