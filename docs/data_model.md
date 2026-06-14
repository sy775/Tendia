# Modèle de données

Toutes les données vivent dans `data/tendia.db` (SQLite), table unique
`kv_storage(collection, id, contenu_json)` — cf [architecture.md](architecture.md) §4.
Chaque « collection » est un namespace logique ; `id` est la clé d'objet.

État observé (juin 2026). Les collections marquées *(vide)* existent mais ne sont
pas encore alimentées.

## marches (422) — clé : `BOAMP-26-57070`

Le marché brut + enrichissements de pipeline.

Champs principaux : `id, source` (BOAMP/TED), `reference_externe, url_source,
url_avis, titre, objet, acheteur_nom, acheteur_id, perimetre_geographique,
date_publication, date_limite_depot, cpv_principal, type_marche,
descripteur_code/libelle, categorie_metier, famille_boamp`.

Enrichissements ajoutés par le pipeline :
- `url_dce` + `dce_qualite` (résolution URL, par `tendia_dce`/`dce_finder`) ;
- `dce_contenu` ∈ {`complet, incomplet, candidature, vide, auth_requise, erreur`}
  (qualification du contenu téléchargé) + `dce_pieces_contractuelles`,
  `dce_raison_contenu`, `dce_telecharge_le` ;
- `reference_ft` (référence interne acheteur, pour la recherche PLACE).

⚠️ `dce_qualite` (résolution de l'URL) ≠ `dce_contenu` (richesse du DCE lu) — à ne
pas confondre (deux champs distincts lus par des étapes différentes).

## classifications_ia (421) — clé : `marche_id`

Classification sectorielle LLM (Haiku) du marché.
- `domaines_metier` : liste de `{code, poids?, lots_concernes?}` (codes de la
  taxonomie `presets/_taxonomie_domaines.json`).
- `raison_classification`, `synthese_courte`, `_meta` (modèle, coût, date), `marche_id`.

C'est la SOURCE du mapping vers les presets : `preset.presets_pour_domaines(codes)`.

## briefs_extraits (102, croît) — clé : `marche_id`

Le brief structuré. Deux types via `_meta.type` :

**complet** (lu depuis le DCE) — `_meta` : `id_marche, type:"complet", date_generation,
extraction_le` (alias), `modele, preset_utilise, presets_matches, prompts_versions,
tokens_input, tokens_output, cout_eur, duree_sec, pdfs_traites[]`.
Champs métier : `synthese_marche, bareme_notation, montant_marche, revision_prix,
alertes_prix, references_exigees, lots, calendrier, alertes_candidat,
points_differenciants_attendus` + blocs sectoriels selon le(s) preset(s) :
`caracteristiques_techniques_chantier`/`allotissement`/`qualifications_requises` (btp),
`caracteristiques_mission_moe`/`qualifications_moe` (ingénierie),
`caracteristiques_mission_it`/`qualifications_it` (it),
`qualifications_formation`, `caracteristiques_techniques_enr`/`qualifications_enr`,
`qualifications_conseil`, etc. Marché hors-périmètre → bloc neutre `caracteristiques_metier`.

**light** (depuis l'avis seul) — `_meta` : `type:"light", modele, date_generation,
tokens_in, tokens_out, cout_eur, duree_sec, source_avis_seulement:true`.
Champs réduits : `synthese_marche, publics_cibles, prestation_inferee, volumes,
calendrier, montant_marche, revision_prix, alertes_candidat,
elements_a_verifier_dans_dce, points_differenciants_probables`.

⚠️ Schéma `_meta` divergent light vs complet (`tokens_in`/`tokens_input`,
`date_generation` vs `extraction_le`) — convention canonique = `tokens_input` +
`date_generation` (le complet pose les deux ; le versioning `prompts_versions` n'existe
que sur le complet). Cf Chantier 1E.

## organisme (1) — clé : `principal`

Le profil de l'organisme actif (un seul). Champs : `id, identite,
zones_intervention, capacite_globale, economie, mots_cles_catalogue,
presets_couverts, profils_sectoriels` (1 sous-objet par preset, suit
`presets/<code>/_schema.json`), `auto_reponses_exigences` (réponses Oui/Non
mémorisées aux exigences). La bibliothèque de profils est dans une collection
séparée `profils_bibliotheque`.

## scores_matching (2532) — clé : `<marche_id>__<preset_code>`

Pré-classification marché × preset (PAS le verdict). Champs : `marche_id,
preset_code, matche` (bool), `mode_decision, score_brut` (0/1), `mots_cles_matches,
cpv_pattern_matche, matche_keyword, matche_ia, niveau_ia, domaine_classifie,
source_classification, raison, evalue_le`.
Sert au **pré-filtrage par secteur** (booléen `matche`). **Aucun champ `verdict`
ni `score` 0-100** — ceux-ci sont calculés à la volée par `matching.evaluer`.

## llm_appels (226) — clé : id d'appel

Journal des appels LLM (audit budget). Champs : `id, type, marche_id, preset_code,
cout_eur, tokens_input, tokens_output, duree_ms, modele, statut, erreur, appele_le,
jour, mois`. Alimenté par `budget.enregistrer_appel`.

## Collections vides (prévues)

- `matchings` *(vide)* — verdicts matching persistés (actuellement recalculés à la volée).
- `briefs_calibres` *(vide)* — briefs avec calibration de montant intégrée.
- `titulaires` *(vide)* — titulaires/attributaires.
- `marches_notifies` *(vide)* — marchés notifiés (DECP, attributions).
- `marches_tendia_attribues` *(vide)* — attributions captées.
- `profils_bibliotheque` — bibliothèque de profils (créée par l'UI profils).

## Données HORS base (sur disque)

- `data/dce/<id>/` — pièces DCE téléchargées (PDF/ZIP décompressés).
- `data/extractions/<id>.json` — copie disque des briefs complet (compat historique).
- `data/extractions_calibrees/<id>.json` — calibrations de montant (PAS une
  collection KV ; lues via `llm_calibration.charger_si_existe`).
- `logs/<downloader>_<date>.jsonl` — journaux d'événements.
