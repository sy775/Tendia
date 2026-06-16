# Rapport — Enrichissement marché BOAMP v2

Chantier déclenché par un constat lors de la préparation de Sprint DECP 3 : les briefs
Tendia n'avaient ni preset DECP, ni SIRET acheteur, ni montant estimé, et seulement 45 %
de CPV — alors que **l'avis BOAMP brut porte tout cela** (bloc `donnees` eForms), jeté à
l'ingestion. Ce chantier extrait ~31 champs supplémentaires et backfille les 422 marchés
existants. **0 € LLM.**

## Décisions actées

| # | Décision | Mise en œuvre |
|---|---|---|
| 1 | **Matching acheteur au niveau SIREN** (la DECP a du SIRET 14, BOAMP du SIREN 9 ; on ne reconstitue pas de SIRET) | `decp/matching.score_acheteur` compare SIREN ↔ `substr(acheteur_siret,1,9)`. Même SIREN → 0.9, SIRET exact → 1.0. |
| 2 | **`cbc:EndpointID` → `url_consultation_dce_directe`** (URL directe + PCSLID), priorité downloader | Champ extrait ; note B12 « devient marginal » ajoutée à `dette_technique.md`. Câblage downloader = reste à faire. |
| 3 | **Montant estimé non bloquant** ; logguer la couverture ; **si < 30 %**, tranche montant non utilisée | Couverture mesurée : **16,6 % → tranche montant écartée** de la triangulation (limitation actée). |
| + | **Amendements** : `donnees_boamp_brut` (payload intégral) ; `lots_json` enrichi (`description_complete`, `criteres_specifiques`) | Implémentés et testés. |

## Champs ajoutés (31)

`extraire_champs_enrichissement(avis)` dans `connecteurs/boamp.py`, câblé dans
`_normaliser` (tous les futurs crawls) :

- **🔴 Trio critique** : `url_consultation_dce_directe`, `acheteur_siren`, `montant_estime_eur`
- **🟠 Priorité 1** : `url_profil_acheteur`, `acheteur_ville`, `acheteur_code_postal`, `acheteur_nuts`, `nombre_lots`, `lots_json`
- **🟡 Priorité 2** : `cpv_secondaires`, `nature`, `nature_libelle`, `procedure_libelle`, `criteres_attribution`, `est_europeen`, `acheteur_adresse`, `acheteur_pays`
- **🟢 Priorité 3** : `dce_consultation_id`, `annonces_anterieures`, `annonce_lie`, `date_fin_diffusion`, `duree_marche_mois`, `etat`, `type_avis_detail`
- **⚙️ Méta** : `enrichissement_version`, `enrichissement_le`, `enrichissement_source`, `enrichissement_champs_absents`, `source_schema_eforms`, `donnees_boamp_brut`

Détail des sources eForms/ODS : `docs/modules/marche.md` SECTION 1.

## Backfill — couverture (422 marchés, 0 échec, 0,4 min)

`scripts/backfill_enrichissement_boamp.py` (re-fetch via `www.boamp.fr`, l'API datadila
du connecteur étant indisponible) :

| Champ | Renseigné | % |
|---|---|---|
| `nature` / `procedure_libelle` | 422 | **100 %** |
| `acheteur_ville` / `_code_postal` / `_nuts` / `dce_consultation_id` | 190 | 45,0 % |
| `acheteur_siren` | 189 | **44,8 %** |
| `duree_marche_mois` | 184 | 43,6 % |
| `url_consultation_dce_directe` | 182 | 43,1 % |
| `acheteur_adresse` | 182 | 43,1 % |
| `criteres_attribution` | 166 | 39,3 % |
| `url_profil_acheteur` | 158 | 37,4 % |
| `cpv_secondaires` | 82 | 19,4 % |
| **`montant_estime_eur > 0`** | **70** | **16,6 %** |

**Lecture** : les champs eForms plafonnent à ~45 % = la part d'avis eForms récents
(les ~55 % restants sont legacy, sans bloc `donnees` structuré). Ce plafond **coïncide
exactement** avec les 190 briefs porteurs d'un CPV → c'est le même sous-corpus eForms qui
porte CPV + SIREN + géo + URL DCE. Schéma eForms : `3.2.5` sur 100 % des avis trouvés.
Détail : `data/couverture_enrichissement_boamp.csv`.

## Conséquences

### 🟢 Matching acheteur (DECP & triangulation) — débloqué
`acheteur_siren` à 44,8 % rend le rapprochement Tendia↔DECP **fiable** (entité juridique)
là où il reposait sur un nom flou (≈ 12 %). `decp/matching.score_acheteur` matche au
niveau SIREN ; repli nom pour le legacy.

### 🟢 Acquisition DCE / bug B12 — quasi-résolu
`url_consultation_dce_directe` (43,1 %, avec PCSLID) donne au downloader l'URL exacte de
la consultation. **B12 devient marginal** une fois le downloader câblé pour la lire en
priorité (noté dans `dette_technique.md`).

### 🟠 Tranche de montant — écartée (couverture insuffisante)
`montant_estime_eur > 0` à **16,6 % (< 30 %)** : conformément à la décision 3, la **tranche
de montant ne sera pas un critère de triangulation**. Elle reste extraite (et alimentera
les agrégats DECP côté similaires). À ré-évaluer quand le corpus grossira.

## Tests

- `tests/test_boamp_enrichissement.py` (**33 OK**) : extraction eForms (trio, géo, lots
  enrichis, méta) + dégradation gracieuse legacy + tracking `champs_absents`.
- `tests/test_decp_matching.py` (**32 OK**) : matching niveau SIREN (SIREN 9 ↔ SIRET 14).
- **Suite globale : 193 OK / 0 KO.**

## Dette / suite

- **`acheteur_type`** (collectivité/État/hôpital/bailleur…) à dériver post-v2 depuis
  `acheteur_nom` + `acheteur_siren` (règles déterministes, ~30 min, filtre UI). Noté B13
  dans `dette_technique.md`.
- **Câblage downloader** : faire lire `url_consultation_dce_directe` en priorité par
  `tendia_telecharger_dce` (clôt B12 en pratique).
- **Sprint DECP 3 (triangulation)** : **débloqué**. Clé retenue = CPV (8→5→3) + géo
  (dept→région→national) + acheteur SIREN pour les flags ; **sans** tranche de montant
  (couverture < 30 %). Couverture triangulable attendue ≈ 45 % des briefs (les eForms).

## Recommandation

**GO** pour reprendre Sprint DECP 3 sur la base enrichie. L'enrichissement transforme le
matching acheteur (flous → SIREN fiable) et l'acquisition DCE (B12). La seule limitation
actée est la tranche de montant (corpus encore jeune, 16,6 %), non bloquante.
