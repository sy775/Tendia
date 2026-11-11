# Tendia : état des lieux et dette technique (2026-11-10)

Fusion de `dette_technique.md` (juin), du rapport d'architecture du 2 novembre (§9) et du rapport du chantier 0a. Priorisé par rapport au produit (fiche 00_PRODUIT.md), pas par ancienneté.

## 1. Ce qui marche

- Ingestion BOAMP différentielle (~1 000 marchés/mois), 3 039 marchés en base.
- Résolution d'URL DCE et téléchargement anonyme sur 7 plateformes (AWS-Achat, Atexo/PLACE, Dematis, achatpublic, marchés-sécurisés, xmarches), avec rotation IP sur AWS et Dematis.
- Brief LLM structuré (schéma v3 avec `dossier_candidature.pieces_a_fournir` sur 209 briefs, 2 440 pièces).
- Matching déterministe profil × marché, verdict à 4 niveaux, UI dashboard / explorer / fiche marché / profils.
- Mémoire technique : plan, rédaction par section en parallèle, détection du cadre de réponse acheteur `.docx`, export `.docx`.
- Ingestion DECP (142 735 contrats) classée par preset, comparables de prix.
- Expérimentation « mode document » : inventaire exhaustif des pièces (récursif, ZIP imbriqués, conversion .doc/.xls/.odt/.rtf, scans), questions par type de pièce, sources pièce + page, contrôle de complétude. Mesuré : 0,9 à 1,2 € par DCE, lecture complète là où la prod rate jusqu'à 49 % du texte.

## 2. Bloquants pour vendre (à traiter avant les démos)

| # | Problème | Impact | Chantier |
|---|---|---|---|
| S1 | Pipeline LLM arrêté depuis le 22/06 : 1 992 marchés d'octobre sans classification ni brief ; `tendia_classification` n'est pas appelée par le pipeline | Aucun marché récent n'est analysable en démo | 1 |
| S2 | Lecture des DCE lacunaire en prod (formats non lus, sous-dossiers, troncature) | Un brief faux ou incomplet en démo tue la crédibilité | 2 |
| S3 | Pas d'agent d'assemblage : rien ne produit « le dossier » | Le livrable vendu n'existe pas encore | 3 |
| S4 | `data/dce` (124 Go) sans sauvegarde | Perte sèche possible du seul actif non reconstructible | 6 |

## 3. Dette technique priorisée

### 3.1 Cœur de données
- `stockage.sauver("marches")` global (58 Mo réécrits) dans `tendia_telecharger_dce.py` et `cycle_marche.py`. Remplacer par `ecrire` unitaire.
- Cache par processus : UI et scripts désynchronisés. Ajouter une invalidation sur timestamp de fichier, ou lire sans cache dans l'UI.
- 235 sauvegardes de briefs stockées **dans** `briefs_extraits` (`.bak_avant_*`, `.grille_brute`) et `brief_v1_backup` dans 115 briefs : à purger après export.
- `decp/db.py` : chemin de base en dur, pas de `busy_timeout`.
- Codes `conseil_rd` / `enr` dans `decp_classification` ≠ `conseil` / `energie_renouvelable` des presets.

### 3.2 Analyse et matching
- Fait au chantier 2 (2026-11-11) : `llm_router` est le client unique (plus d'`Anthropic()` direct), tous les appels sont journalisés dans `llm_appels`.
- `post_traiter_extraction_v2` jamais appelé par `tendia_extraire`.
- Le matching confond « inconnu » et « non détenu » : un profil minimal est pénalisé à tort.
- Score instable (57/39/32 sur le même marché) : le moteur est déterministe mais lit des champs LLM variables (`synthese_marche` texte libre, montant lu dans un seul champ).
- `matching_exigences` : heuristiques orientées formation / France Travail, à normaliser BTP (Qualibat, RGE, décennale, CA ≥ X).
- `acheteur_siren` absent sur 56 % des marchés (82 % des travaux) : bloque tout rapprochement DECP.

### 3.3 Code et tests
- `tendia_ui.py` 2 154 lignes, `llm_extract.py` 1 525, `tendia_telecharger_dce.py` 1 423, `matching.py` 1 379 : candidats au découpage.
- Modules critiques sans test : `matching`, `matching_exigences`, `preset`, `tendia_extraire`, `organisme`, `tendia_ui`.
- Tests : style maison `check()`, pas de pytest, pas de CI. Après 0a : `test_dematis_workflow_har.py` cassé (fixture archivée), `test_grille_notation.py` n'est pas un test (prototype qui appelle l'API et écrit en base).
- Signatures `telecharger_dce(...)` différentes par plateforme ; seule `telecharger_dce_pour_marche(marche, repertoire, ...)` est homogène.
- Dépendances absentes : `beautifulsoup4`, `curl_cffi`, `python-dotenv`.

### 3.4 UI
- `ui/templates/marche.html` : ~1 700 lignes de styles inline. Refonte en classes avant toute amélioration d'écran.
- Tailwind compilé sans chaîne de build dans le dépôt.
- Jobs mémoire tenus en mémoire du processus : perdus au redémarrage.

### 3.5 Mort ou fantôme
- `pipeline_france_travail.py`, `jointure.py` + `data/jointure.json` (391 entrées, 0 DECP), collection `matchings`, `presets/_actif.json`, `docs/cron_windows.md`.
- Collections déclarées jamais alimentées : `marches_notifies`, `marches_tendia_attribues`, `titulaires`, `briefs_calibres`.
- `analyse.py` : plus importé par l'UI ; `scores_matching` figé.

## 4. Écarts doc / code à garder en tête

`docs/passation_claude.md` (15/06) est périmé sur une dizaine de points (TED annoncé mais sans connecteur, DECP « à la volée » alors que 142 735 contrats sont ingérés, chemins de profils JSON inexistants, branche principale erronée). Le rapport du 2 novembre fait foi ; `passation_claude.md` est à archiver au chantier 0b.

## 5. Coûts LLM mesurés

| Poste | Coût |
|---|---|
| Brief complet Sonnet 4.6 | 0,33 à 0,65 € |
| Mode document (exp) par DCE | 0,9 à 1,2 € |
| Classification Haiku | ~0,006 € par marché |
| Mémoire technique | ~2 appels Sonnet, coût dans `_meta.cout_total_eur` |
| Total journalisé juin 2026 | 429,58 € (extraction seule) |
| Expérimentation Gemini/Opus | ~30 € |

Rattraper les 1 992 marchés d'octobre en brief complet coûterait 650 à 1 300 € : d'où l'importance de classer d'abord (Haiku, ~12 €) et de ne « briefer » que le BTP pertinent.
