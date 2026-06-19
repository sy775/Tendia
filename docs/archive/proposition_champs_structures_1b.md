# Sous-chantier 1B.1 — Proposition des champs structurés sectoriels

> Jalon de validation. Aucune modification appliquée. À valider avant 1B.2 (édition + few-shot).

## 0. Clarifications préalables (vs prompt 1B)

- **Piège #1 corrigé** : `_schema.json` sert au **profil ORGANISME** (`organisme.py`), PAS à l'extraction du brief. **Aucune validation des champs du brief contre `_schema.json`** au stockage. → ajouter des champs à `prompt_extraction.bloc_schema_specifique` est sûr ; **pas besoin de synchroniser `_schema.json`**. Seule contrainte : un NOUVEAU bloc top-level doit figurer dans `bloc_schema_specifique` (le filtre anti-hallucination l'autorise alors automatiquement, via regex). Auto-satisfait puisqu'on l'y ajoute.
- **Les blocs sectoriels existants sont DÉJÀ riches** (plus que le prompt 1B ne supposait). 1B = compléter les manques ciblés, pas tout réécrire.
- **Drift de nommage IT** : les briefs en base utilisent `caracteristiques_si`/`qualifications_si` (63 briefs), mais le preset IT actuel déclare `caracteristiques_mission_it`/`qualifications_it`. Ma baseline Chantier A mesurait `qualifications_si.iso_27001` → 0% : c'était le bon bloc dans les vieux briefs mais le sous-champ n'existait pas. **Décision de nommage requise (voir IT).**

## 1. État actuel des blocs structurés (par preset)

| Preset | Blocs top-level actuels | Bloc « qualifications » présent ? |
|---|---|---|
| btp | `caracteristiques_techniques_chantier`, `allotissement`, `qualifications_requises` | ✅ `qualifications_requises` |
| ingenierie | `caracteristiques_mission_moe`, `qualifications_moe` | ✅ `qualifications_moe` |
| it | `caracteristiques_mission_it`, `qualifications_it` | ✅ `qualifications_it` |
| formation | `publics_cibles`, `volumes`, `modalites` | ❌ **absent** |
| energie_renouvelable | `caracteristiques_techniques_chantier` ⚠️, `volumes_techniques`, `modalites_execution_chantier` | ❌ **absent** |
| conseil | `caracteristiques_mission`, `profils_intervenants` | ❌ **absent** |

⚠️ **Collision** : EnR réutilise le nom de bloc `caracteristiques_techniques_chantier` (identique à BTP). Le routage l'isole en prod (un seul preset injecté/marché) mais c'est fragile.

## 2. Champs proposés par preset (ajouts uniquement)

### BTP — bloc `qualifications_requises` (existe)
Présent : `qualibat`, `rge`, `opqibi`, `autres_certifications`.
- **Affiner `qualibat`** → forcer une **liste de codes 4 chiffres** (ex. `["5413","6112"]`) ; règle de double-remplissage (liste + `references_exigees.certifications_obligatoires`).
- **Scinder `rge`** → `rge` (bool) + **`rge_specialites`** (liste).
- **Ajouter** : `mase` (bool), `iso_9001` (bool), `iso_14001` (bool), `iso_45001` (bool).

### Ingénierie — bloc `qualifications_moe` (existe, déjà complet)
Présent : `opqibi` (liste), `opqcm`, `bim`, `autres` ; `caracteristiques_mission_moe.phases_couvertes` (= `phases_moe`).
- **Quasi rien à faire** : confirmer `opqibi`/`opqcm` typés **liste**. `phases_moe` déjà couvert par `phases_couvertes`. Règle double-remplissage OPQIBI.

### IT — blocs `caracteristiques_mission_it` / `qualifications_it`
Présent (qualif) : `certifications_securite`, `certifications_technologiques`, `autres`.
- **DÉCISION nommage** (cf §0) : **garder `qualifications_it` / `caracteristiques_mission_it`** (cohérent avec `_requises`/`_moe`) — NE PAS revenir à `_si`. (Recommandé.)
- **Ajouter à `qualifications_it`** (booléens structurés à côté du texte libre) : `iso_27001`, `hds`, `secnumcloud`, `rgs`, `referencement_anssi`.
- **Ajouter à `caracteristiques_mission_it`** : `typologie_systeme` (enum : web/mobile/ERP/BI/TMA/infra_cloud/infogerance/autre), `cloud_ou_on_premise`, `niveau_securite`.

### Formation — **créer bloc `qualifications_formation`**
- `qualiopi` (bool, obligatoire formation pro), `rncp` (bool) + `rncp_titres` (liste de n°), `cpf` (bool).
- `publics_cibles` : **déjà un bloc** (description + criteres_eligibilite). Le prompt 1B demande une « liste » → je garde le bloc existant (plus riche) et n'ajoute pas de doublon. À confirmer.

### EnR — **créer bloc `qualifications_enr`** + résoudre la collision
- `qualifications_enr` : `qualipv`, `qualisol`, `qualipac`, `qualibois`, `qualifelec` (bool).
- **DÉCISION collision** : renommer `caracteristiques_techniques_chantier` → **`caracteristiques_techniques_enr`** (supprime la collision BTP). Champs puissance/productible/nb_sites déjà présents (`puissance_totale_kwc`, `productible_annuel_estime_mwh`, `nb_sites`). (Recommandé.)

### Conseil — **créer bloc `qualifications_conseil`**
- `qualifications_conseil` : `opqcm` (liste), `certifications_methodologiques` (liste : SCRUM, PRINCE2, ITIL, ISO 20000…).
- `volumes_intervention.nb_jours_total` / `nb_intervenants_min` : déjà couverts par `caracteristiques_mission.jours_consultant_estimes` + `profils_intervenants.consultants`. → pas de nouveau bloc, mapping sur l'existant. À confirmer.

## 3. Décisions à valider (jalon)

| # | Décision | Recommandation |
|---|---|---|
| D1 | Nommage IT : `_it` (actuel) vs `_si` (vieux briefs) | **Garder `_it`** |
| D2 | EnR : renommer `caracteristiques_techniques_chantier` → `caracteristiques_techniques_enr` | **Oui** (supprime collision BTP) |
| D3 | Créer `qualifications_formation`, `qualifications_enr`, `qualifications_conseil` | **Oui** (absents) |
| D4 | `qualibat`/`opqibi`/`opqcm`/`rncp_titres` typés **liste** + règle double-remplissage | **Oui** |
| D5 | Ne PAS dupliquer `publics_cibles` (formation) ni `volumes_intervention` (conseil) — réutiliser l'existant | **Oui** |
| D6 | Ne PAS toucher `_schema.json` (profil organisme, hors-scope brief) | **Oui** |

## 4. Impact / risques
- Nouveaux blocs top-level (`qualifications_formation/enr/conseil`) auto-autorisés par le filtre (regex sur `bloc_schema_specifique`). ✅
- Renommage EnR : les anciens briefs EnR ont `caracteristiques_techniques_chantier` ; après 1G ils auront `caracteristiques_techniques_enr`. Cohérent (re-extraction prévue).
- Aucun test impacté (aucun test ne lit ces sous-champs).
