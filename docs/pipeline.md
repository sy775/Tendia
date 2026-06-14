# Pipeline détaillé (avis → brief → verdict)

Chaque étape, son module, son entrée/sortie, et le script CLI qui la déclenche.
Doc ancrée sur le code réel.

## Étape 1 — Ingestion des avis (BOAMP / TED)

- **Module** : `connecteurs/boamp.py`, orchestré par `tendia_veille.py`.
- **Entrée** : API BOAMP/TED (via `http_utils`, sans proxy).
- **Sortie** : collection `marches` (1 objet par marché, clé `BOAMP-26-XXXXX`).
- Champs : id, source, titre, objet, acheteur, dates, CPV, périmètre, etc.

## Étape 2 — Classification sectorielle (LLM Haiku)

- **Module** : `tendia_classification.py`.
- **Entrée** : métadonnées du marché (titre, objet, CPV).
- **Sortie** : collection `classifications_ia` → `domaines_metier` (liste de
  `{code, poids}`), `raison_classification`, `synthese_courte`.
- Les codes appartiennent à la taxonomie `presets/_taxonomie_domaines.json` (56 codes).
- Le mapping domaine → preset(s) se fait ensuite via `preset.presets_pour_domaines`.

## Étape 3 — Résolution de l'URL DCE

- **Module** : `dce_finder.py` (appelé par `tendia_dce.py`).
- **Entrée** : le record eForms BOAMP/TED du marché.
- **Sortie** : `marche.url_dce` + `marche.dce_qualite`
  (`directe` / `via_keyword` / `racine` / `absente`).
- Cascade : URL UBL standard → recherche récursive dans le payload → recherche
  PLACE/Atexo par mot-clé (référence interne) → URL racine.
- Fix `/agent/` : les URLs côté acheteur sont réécrites en `/entreprise/` si
  possible, sinon écartées (incident loggué) — cf [modules/dce_finder.md](modules/dce_finder.md).
- **CLI** : `python tendia_dce.py` (recherche d'URL pour les marchés actifs).

## Étape 4 — Téléchargement du DCE (anonyme)

- **Modules** : `*_downloader.py` selon la plateforme, via
  `http_humain.creer_session_humaine(plateforme=...)`.
  - Dematis (`e-marchespublics.com`), AWS-Achat (`marches-publics.info`),
    Atexo/PLACE (`marches-publics.gouv.fr` + forks), achatpublic.com.
- **Entrée** : `marche.url_dce`.
- **Sortie** : `data/dce/<id>/` (PDF + ZIP décompressés) + maj `dce_contenu`.
- Captcha résolu via 2captcha (Dematis/AWS). Proxy par plateforme (PLACE en direct).
- **CLI** (batchs anti-ban) : `retelecharger_dematis_anti_ban.py`,
  `retelecharger_aws_achat_anti_ban.py`, `relancer_dce_echecs.py`.
- Cf [modules/downloaders.md](modules/downloaders.md).

## Étape 4bis — Qualification du contenu DCE

- **Module** : `tendia_dce.qualifier_dce` (+ backfill `backfill_dce_qualite.py`).
- **Sortie** : `marche.dce_contenu` ∈ {`complet, incomplet, candidature, vide,
  auth_requise, erreur`} + `dce_pieces_contractuelles`. Lit aussi les ZIP imbriqués
  et archives .7z/.rar.
- Garde-fou : pas d'extraction LLM sur `vide`/`auth_requise`/`erreur`.

## Étape 5 — Extraction du brief (LLM Sonnet)

- **Modules** : `tendia_extraire.traiter_marche` → `llm_extract.extraire_via_llm`.
- **Entrée** : texte combiné des pièces (`pdf_extract.extraire_dossier`).
- **Routage** : `_resoudre_presets_pour_marche(marche_id)` lit `classifications_ia`
  → `presets_pour_domaines` → prompt + schéma **ciblés** sur le(s) preset(s).
  Hors-périmètre → schéma neutre (`caracteristiques_metier`).
- **Filtre** : `_filtrer_hallucinations` supprime les blocs sectoriels non
  autorisés AVANT le stockage.
- **Sortie** : collection `briefs_extraits` (brief **complet**) +
  `data/extractions/<id>.json`. `_meta` porte le versioning preset
  (`preset_utilise`, `presets_matches`, `prompts_versions`).
- **CLI** : `python tendia_extraire.py --marche <id>` ;
  re-extraction de masse : `reextraire_briefs_complet.py`.
- Variante **light** (depuis l'avis seul, sans DCE) : `auto_brief.py`.
- Cf [modules/tendia_extraire.md](modules/tendia_extraire.md),
  [modules/llm_extract.md](modules/llm_extract.md).

## Étape 6 — Matching marché × profil (à la volée)

- **Module** : `matching.evaluer(profil, marche, brief)` (+ `matching_exigences`
  pour l'éligibilité).
- **Entrée** : profil organisme actif (`organisme` collection) + brief.
- **Sortie** (NON persistée, recalculée à chaque affichage) :
  `{score 0-100, verdict, motifs}` + `verdict_eligibilite`.
- Seuils : `tres_pertinent ≥ 75`, `pertinent ≥ 50`, `a_verifier ≥ 20`, sinon
  `non_pertinent` (ou non_pertinent dur si verrou go/no-go non satisfait).
- `analyse.py` produit séparément le pré-filtrage `scores_matching` (booléen
  `matche` par preset, keyword/CPV/IA) — utilisé pour restreindre la liste.
- **CLI** : `python tendia_matcher.py` / `python analyse.py`.

## Étape 7 — Présentation (UI Flask)

- **Module** : `tendia_ui.py` + helpers `fiche_marche.py`.
- **Vues** :
  - **Dashboard** (`/`) : marchés pertinents (pré-filtrés par secteur du profil)
    triés par verdict/score.
  - **Explorer** (`/explorer`) : TOUS les marchés classifiés, filtrables par
    secteur, brief, et **pertinence/éligibilité/score** (multi-sélection).
  - **Fiche marché** (`/marche/<id>`) : détail complet (verdict 90s, KPI, barème,
    blocs sectoriels, éligibilité, concurrents).
- **CLI** : `python tendia_ui.py` → http://localhost:5000.

## Étapes annexes

- **Calibration des montants** : `llm_calibration.py` / `calibrer_briefs.py`
  (comparables DECP, écrits sur disque `data/extractions_calibrees/`).
- **Concurrence / attributions** : `concurrence.py`, `tendia_decp*.py`,
  `marches_attribues.py` (DECP, titulaires historiques).
- **Budget LLM** : `budget.py` (kill-switch + journal `llm_appels`).
