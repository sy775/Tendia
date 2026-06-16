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

## Hors-scope Sprint 1 (→ Sprint 2/3)

Classification preset (LLM), triangulation par brief, job mensuel automatisé, intégration UI.
