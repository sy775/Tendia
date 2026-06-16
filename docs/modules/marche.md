# Module marché Tendia — schéma & enrichissement BOAMP

Le marché Tendia (collection KV `marches`, clé `BOAMP-<idweb>`) est produit par
`connecteurs/boamp.py` (`_normaliser`). Le schéma v1 ne capte qu'une fraction de
l'avis BOAMP ; le **schéma v2** (ce document) enrichit le marché avec ~30 champs
déjà présents dans l'avis brut (`donnees` eForms + champs ODS top-niveau) mais
jusque-là jetés.

> **STATUT : VALIDÉ + IMPLÉMENTÉ (16/06).** SECTION 1 validée par Younes (ajout
> `donnees_boamp_brut`, `lots_json` enrichi). Patch `connecteurs/boamp.py`
> (`extraire_champs_enrichissement`) + backfill des 422 marchés effectués.
> **Couverture backfill** (422 marchés, 0 échec) : `acheteur_siren` **44,8 %**,
> `url_consultation_dce_directe` **43,1 %**, géo (ville/CP/NUTS) **45,0 %**,
> `nature`/`procedure_libelle` **100 %**, `montant_estime_eur > 0` **16,6 %**.
> Les champs eForms plafonnent à ~45 % = part des avis eForms récents (le reste est
> legacy, sans bloc `donnees`). **`montant_estime > 0` < 30 % → la tranche de montant
> n'est PAS utilisée comme critère de triangulation** (précision 3). Cf.
> `RAPPORT_ENRICHISSEMENT_BOAMP.md`.

---

## SECTION 1 — Schéma v2 (champs d'enrichissement)

### Décisions techniques actées

1. **Matching acheteur au niveau SIREN.** L'avis BOAMP fournit un **SIREN** (9
   chiffres, `cbc:CompanyID`), la DECP stocke un **SIRET** (14). Le rapprochement
   acheteur Tendia↔DECP se fait au **niveau SIREN** = les **9 premiers chiffres**
   du `decp_marches.acheteur_siret`. C'est métier-juste (le SIREN identifie
   l'entité juridique, le SIRET l'établissement). **On ne reconstitue pas** de
   SIRET côté BOAMP. → champ `acheteur_siren`.
2. **`cbc:EndpointID` ≈ résolution B12.** Ce champ porte l'**URL directe de la
   consultation** (avec sa `PCSLID`). Extrait dans `url_consultation_dce_directe`,
   il sera utilisé **en priorité** par le downloader DCE, avant son code actuel de
   reconstruction d'URL. Le bug B12 (PLACE/Atexo) devient **marginal** une fois
   l'enrichissement déployé (à noter dans `dette_technique.md` lors du patch).
3. **Montant estimé non bloquant.** `cbc:EstimatedOverallContractAmount` est
   **extrait systématiquement** mais vaut souvent `0.00` (non publié, ex. sur les
   avis JOUE). Il **n'est jamais un critère bloquant**. Après backfill, on **logue
   la couverture réelle** (% de briefs avec `montant_estime_eur > 0`). **Si < 30 %**,
   la tranche de montant **ne sera pas utilisée** comme critère de triangulation et
   la limitation est documentée. → champ `montant_estime_eur`.

> **Couverture par origine d'avis.** Champs marqués *eForms* = fiables sur les avis
> eForms récents (post-2024), souvent absents des avis legacy → renseignés au
> mieux, `None` sinon. Champs *ODS* = champ top-niveau du record BOAMP, fiables.

### 🔴 Trio critique

| Champ Tendia | Type | Source | Notes |
|---|---|---|---|
| `url_consultation_dce_directe` | str\|None | *eForms* `cbc:EndpointID` | URL directe consultation + `PCSLID`. **Priorité downloader DCE** (≈ fix B12). |
| `acheteur_siren` | str(9)\|None | *eForms* `cbc:CompanyID` | Clé de matching acheteur ↔ DECP (= 9 premiers chiffres du SIRET DECP). |
| `montant_estime_eur` | float\|None | *eForms* `cbc:EstimatedOverallContractAmount` (`#text`) | Extrait toujours ; souvent 0/None. **Jamais bloquant.** Couverture loggée au backfill. |

### 🟠 Priorité 1 — fort impact

| Champ Tendia | Type | Source | Notes |
|---|---|---|---|
| `url_profil_acheteur` | str\|None | *eForms* `cbc:BuyerProfileURI` | Identifie la plateforme (ATEXO/achatpublic/Dematis) sans deviner. |
| `acheteur_ville` | str\|None | *eForms* `cbc:CityName` | Géo acheteur. |
| `acheteur_code_postal` | str\|None | *eForms* `cbc:PostalZone` | Géo fine. |
| `acheteur_nuts` | str\|None | *eForms* `cbc:CountrySubentityCode` (`#text`, listName=nuts) | Code NUTS (ex. `FR101`) — géo + fallback région. |
| `nombre_lots` | int | *eForms* count `cac:ProcurementProjectLot` | 0/1 = mono-lot. |
| `lots_json` | json\|None | *eForms* `cac:ProcurementProjectLot[]` | Par lot : `{numero, intitule, cpv, montant_estime, duree}`. |

### 🟡 Priorité 2 — géo & qualification

| Champ Tendia | Type | Source | Notes |
|---|---|---|---|
| `cpv_secondaires` | json list | *eForms* `cbc:ItemClassificationCode` (hors principal) | Complète `cpv_principal`. |
| `nature` | str\|None | *ODS* `nature` | Ex. `APPEL_OFFRE`. |
| `nature_libelle` | str\|None | *ODS* `nature_libelle` | Ex. `Avis de marché`. |
| `procedure_libelle` | str\|None | *ODS* `procedure_libelle` | Ouverte/restreinte/négociée. |
| `criteres_attribution` | json list | *ODS* `criteres` | Flags (`["sociaux","environnementaux"]`) — indice de barème RSE. |
| `est_europeen` | bool | dérivé *ODS* `famille`/`famille_libelle` | `JOUE`/« Marchés européens » → seuil européen. |
| `acheteur_adresse` | str\|None | *eForms* `cac:PostalAddress` (`cbc:StreetName`) | Adresse postale acheteur. |
| `acheteur_pays` | str | *eForms* `cac:Country/cbc:IdentificationCode` | Défaut `FR`. |

### 🟢 Priorité 3 — contexte & liens

| Champ Tendia | Type | Source | Notes |
|---|---|---|---|
| `dce_consultation_id` | str\|None | *ODS* `contractfolderid` | Id dossier de consultation. |
| `annonces_anterieures` | json\|None | *ODS* `annonces_anterieures` | Avis antérieurs liés. |
| `annonce_lie` | str\|None | *ODS* `annonce_lie` | Avis lié (rectificatif/modif). |
| `date_fin_diffusion` | str\|None | *ODS* `datefindiffusion` | Fin de diffusion. |
| `duree_marche_mois` | int\|None | *eForms* `cbc:DurationMeasure` | Durée si publiée (partielle). |
| `etat` | str\|None | *ODS* `etat` | `INITIAL`/… |
| `type_avis_detail` | json\|None | *ODS* `type_avis` | Type(s) d'avis. |

### ⚙️ Méta — traçabilité de l'enrichissement

| Champ Tendia | Type | Source | Notes |
|---|---|---|---|
| `enrichissement_version` | str | constant | `"v2"`. |
| `enrichissement_le` | str ISO | `datetime.now()` | Horodatage du backfill/crawl enrichi. |
| `enrichissement_source` | str | constant | `"boamp_refetch"` (backfill) \| `"crawl"` (flux normal). |
| `enrichissement_champs_absents` | json list | calculé | Champs non trouvés dans l'avis (suivi de couverture). |
| `source_schema_eforms` | str\|None | *ODS* `source_schema` | Version eForms (ex. `3.2.5`). |
| `donnees_boamp_brut` | json string | avis intégral | **Payload BOAMP complet** (avis brut sérialisé) → ré-extraction future sans re-fetch. |

**Total : 31 champs** (3 trio + 6 P1 + 8 P2 + 7 P3 + 6 méta + 1 dérivé `est_europeen`).

`lots_json` (amendement) — par lot : `{numero, intitule, cpv, montant_estime, duree,
description_complete, criteres_specifiques}` (les 2 derniers si présents, non bloquants).

### Conventions

- Nommage snake_case français, cohérent avec l'existant (`acheteur_nom`,
  `cpv_principal`, `perimetre_geographique`, `dce_qualite`…).
- `acheteur_id` (v1, toujours `None`) est **conservé** pour rétrocompat mais
  **déprécié** au profit de `acheteur_siren`.
- `url_consultation_dce_directe` est distinct de `url_dce` (v1, reconstruite/
  scrapée) : la première a priorité quand présente.
- Tous les champs *eForms* peuvent être `None` (avis legacy) → aucun n'est requis.

---

## SECTION 2 — Plan d'implémentation (Étapes 2-6, post-validation)

_À dérouler sans interruption une fois la SECTION 1 validée :_

2. **Patch `connecteurs/boamp.py`** : helpers d'extraction des 30 champs +
   câblage dans `_normaliser`. Parse PCSLID depuis `cbc:EndpointID`. Note B12 dans
   `dette_technique.md`.
3. **Backfill** : `scripts/backfill_enrichissement_boamp.py` (re-fetch des 422 avis
   via `www.boamp.fr`, MAJ des marchés, log couverture par champ — dont
   `montant_estime_eur > 0`). 0 € LLM.
4. **Schéma** : aucune table relationnelle (KV JSON) ; mise à jour matching DECP
   pour utiliser `acheteur_siren` ↔ `substr(decp_marches.acheteur_siret,1,9)`.
5. **Triangulation** (Sprint DECP 3) sur la base enrichie (preset+CPV+géo+montant
   si couverture ≥ 30 %, flags acheteur par SIREN).
6. **Tests** : extraction des 30 champs (avis eForms + legacy + champs absents).

---

## SECTION 3 — Extraction LLM v2 (refonte pipeline)

Diagnostic Phase A : **Scénario C** (le prompt estimait déjà le montant avec une logique
multi-preset neutre via la lib `preset` — pas de purge). Le v2 **enrichit** sans refondre.
Modèle : `claude-sonnet-4-6`.

### Champ de complétude DCE : `dce_contenu` (≠ `dce_qualite`)

⚠️ `dce_contenu` ∈ {`complet`, `vide`, `incomplet`, `candidature`, `auth_requise`} = complétude
du DCE téléchargé. `dce_qualite` ∈ {`directe`, `via_keyword`, `racine`, `absente`} = **méthode
de découverte de l'URL**, PAS la complétude. La re-extraction cible `dce_contenu='complet'`.

### Downloader — priorité URL directe (résout B12)

`tendia_telecharger_dce.telecharger_pieces_dce` est un wrapper : tente
`url_consultation_dce_directe` (avec PCSLID) **en priorité**, repli sur `url_dce` reconstruite
si absente ou échec. Ajoute `url_utilisee`/`url_source` au résultat. Re-download :
`scripts/retenter_download_dce.py` (parallèle 5 workers, écriture mono-thread).

### Montant en 3 voies (`montant_3_voies` + aplatissement)

Le prompt v2 produit `montant_3_voies` (en plus de `montant_marche`, rétro-compat) :
- **Voie 1** (`voie_1_eur`/`voie_1_source`) : montant publié dans le DCE.
- **Voie 2** (`voie_2_disponible`, `voie_2_min_eur`/`max`, `voie_2_hypotheses[]`,
  `voie_2_raison_indisponible`) : estimation bottom-up **uniquement si Voie 1 absente**, avec
  hypothèses sourcées + fourchette. Le prompt **force la Voie 2 avant `non_communique`**
  (le LLM s'y rabattait trop vite sur ingénierie/conseil).
- **Voie 3** = rapprochement DECP en aval (hors LLM, Sprint DECP 3).

`post_traiter_extraction_v2` aplatit en `montant_voie_1_eur`, `montant_voie_2_disponible`,
`montant_au_moins_une_voie`, `montant_alerte_coherence`.

### Critères : dual hiérarchique + plat, classification par `unite_evaluation`

Le bareme **hiérarchique** existant est conservé (sous-critères, exemples de réponse forte —
valeur UI). Chaque sous-critère porte désormais `unite_evaluation` ∈ {`euro`, `points`,
`delai_jours`}. Le code dérive `criteres_attribution_plat` (un par critère) avec la **famille** :
- `unite_evaluation = "euro"` → **famille prix** (⚠️ **résout le bug RSE** : un critère
  environnemental chiffré en €/tonne CO2 devient prix, plus technique).
- sinon → **famille valeur_technique**.

**Validation post-LLM** (`valider_criteres_plat`) : somme = 100 (±2), ≥ 1 critère prix > 0,
aucun `non_classe` → flags `criteres_alerte_*`. `extraction_v2_a_verifier=true` si ≥ 2 alertes.

### Contexte BOAMP injecté

`_construire_contexte` ajoute `contexte_boamp` (SIREN, NUTS, nature, procédure, est_europeen,
flags critères BOAMP, lots) → le prompt v2 l'exploite pour cohérence/complétude/Voie 2.

### Versionnement & backup

`prompt_version_sha` (SHA-256 des règles v2) + `version_extraction_llm='2'` par brief. Le brief
v1 est sauvegardé dans `brief_v1_backup` (rollback 30 j, cf. dette B14). Re-extraction :
`scripts/reextraire_briefs_v2.py` (parallèle 8 workers, `BudgetTracker` thread-safe `try_reserve`,
écriture mono-thread anti-lock, cap € dur). Cap d'appels/jour relevé automatiquement.
