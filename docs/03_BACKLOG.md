# Tendia : backlog des chantiers

Un chantier = une session Claude Code, un objectif, un critère de fin vérifiable, un rapport dans `archive/RAPPORT_<n>.md`. Mettre à jour l'état ici à chaque chantier terminé. Ordre aligné sur le produit (00_PRODUIT.md) et sur l'ordre de construction recommandé du rapport d'architecture (§10.9).

## Tableau de bord

| # | Chantier | État | Dépend de |
|---|---|---|---|
| 0a | Dépôt propre : git, archive, tests regroupés | **Terminé le 2026-11-10** (902 → 313 fichiers) | |
| 0b | Structure `src/tendia/`, `CLAUDE.md`, branche `main`, 2 régressions de 0a | À faire | 0a |
| 1 | Redémarrer la chaîne LLM : classification dans le pipeline, rattrapage BTP d'octobre | À faire | 0b |
| 2 | Promouvoir le mode document en prod (lecture exhaustive des DCE) | À faire, **en attente d'une décision** (cf. questions ouvertes) | 1 |
| 3 | Dossier manuel sur un marché BTP réel, puis agent d'assemblage | À faire | 2 |
| 4 | Coffre-fort entreprise | À faire | 3 |
| 5 | Test Scrapling sur les 3 plateformes où le plus de DCE sont perdus | À faire | 0b |
| 6 | Tri et sauvegarde de `data/dce` (124 Go) | À faire | |
| 7 | Fiabiliser le matching (état « inconnu », signaux structurés, clés BTP) | À faire | 2 |
| P | Prospection : 30 PME BTP contactées, 5 démos | En cours en parallèle, hors Claude Code | 3 pour les démos |

## Détail

### 0b : structure et outillage
- Corriger les deux régressions de 0a : fixture `.har` déplacée dans `tests/fixtures/` avec chemin adapté ; `tests/test_grille_notation.py` → `scripts/maintenance/prototype_grille_notation.py`.
- Créer `main` depuis `feat/decp-sprint-3`, la définir comme branche par défaut sur GitHub ; arrêter les branches par sprint.
- Ranger les 44 modules racine sous `src/tendia/<agent>/` selon la table du 01_ARCHITECTURE.md §3, avec `pyproject.toml` (`pip install -e .`), imports corrigés, scripts d'entrée conservés (`tendia_pipeline`, `tendia_ui` via `python -m tendia.ui`).
- Supprimer `place_downloader.py` au profit d'`atexo_downloader` (vérifier l'import dans `tendia_pipeline`).
- Ajouter les dépendances manquantes à `requirements.txt` (`beautifulsoup4`, `python-dotenv`) ; `curl_cffi` optionnel documenté.
- Déposer `CLAUDE.md`, `.claude/agents/audit-code.md`, `.claude/agents/audit-design.md`, `.claude/commands/chantier.md`.
- Archiver `docs/passation_claude.md` et `docs/cron_windows.md` (périmés).
- Critère de fin : tous les tests passent (`python tests/test_*.py`), l'UI démarre, `git ls-files | wc -l` stable, rapport `archive/RAPPORT_0b.md`.

### 1 : redémarrer la chaîne LLM
- Intégrer `tendia_classification` comme étape du pipeline (après la récup, avant la résolution DCE), avec `--skip-llm` respecté.
- Classifier les 1 992 marchés d'octobre (Haiku, ~12 €).
- Sélectionner le BTP pertinent (preset `btp` + profil démo BTP) et ne lancer le brief que sur ceux dont le DCE est complet. Budget plafonné via `data/budget.json`.
- Journaliser tous les appels LLM dans `llm_appels` (classification, mémoire, calibration), pas seulement l'extraction.
- Critère de fin : 0 marché BTP d'octobre sans classification ; N briefs BTP récents disponibles pour les démos ; coût réel dans le rapport.

### 2 : lecture exhaustive des DCE
- Promouvoir `exp_gemini/pieces.py` (inventaire récursif, conversion .doc/.xls/.odt/.rtf, pages) et `mode_document.py` dans `src/tendia/analyse/`.
- Promouvoir `llm_router.py` comme client LLM unique (remplacer les 6 `Anthropic()` directs).
- Décider du modèle d'analyse par défaut (cf. questions ouvertes).
- Critère de fin : sur 5 DCE BTP de référence, 100 % des pièces lues, brief avec sources pièce + page, coût par DCE mesuré.

### 3 : le dossier
- D'abord à la main : prendre un marché BTP réel ouvert, faire tourner les modules existants, assembler le dossier avec Claude (chat), noter ce qui manque. Ce dossier sert de pièce de démo.
- Puis l'agent d'assemblage : à partir du brief (`pieces_a_fournir`), du profil, du mémoire et de l'estimation, produire un zip nommé selon le RC + une fiche de dépôt (plateforme, lien, format, date limite). Formulaires DC1/DC2/AE pré-remplis à partir du profil (modèles officiels à ajouter au dépôt).
- Critère de fin : un dossier généré en moins de 10 minutes sur un marché jamais vu, relu par Younes, jugé déposable.

### 4 : coffre-fort entreprise
- Table SQL `coffre_pieces` (type normalisé, date d'émission, validité, fichier, SHA-256), upload dans l'UI, lecture de la validité par LLM léger, référentiel de pièces avec liens d'obtention (URSSAF, impots.gouv, Kbis, Qualibat).
- Alerte d'expiration locale d'abord (pas de mail tant que pas d'hébergement).
- Critère de fin : les pièces de candidature d'un profil sont injectées automatiquement dans le dossier du chantier 3.

### 5 : Scrapling
- Mesurer d'abord : `scripts/audit/audit_plateformes_dce.py` pour identifier les 3 plateformes avec le plus de DCE perdus.
- Réécrire ces 3 downloaders avec `StealthyFetcher` et sélecteurs adaptatifs ; comparer le taux de récupération sur une semaine de marchés BTP.
- Critère de fin : taux avant/après par plateforme. Généraliser seulement si le gain dépasse 5 points.

### 6 : `data/dce`
- Trier : ne garder que les DCE des marchés classés BTP ou déjà briefés ; archiver le reste.
- Sauvegarder le résultat hors disque principal (disque externe ou stockage objet).

### 7 : matching fiable
- État « inconnu » distinct de « non détenu » dans les verrous.
- Lecture du montant dans `montant_3_voies` et `marches.montant_estime_eur`.
- Clés canoniques BTP dans `matching_exigences` (Qualibat <code>, RGE, décennale, `ca_min_<montant>`), classement des questions d'éligibilité par nombre de marchés débloqués.
- Tests `matching` et `preset` (0 couverture aujourd'hui).

## Questions ouvertes (à trancher par Younes)

1. **Modèle d'analyse par défaut en prod** : Sonnet 4.6 (prod actuelle, incomplète), Gemini 4 argon (meilleur sur les données publiques selon les tests d'octobre, 2 $/10 $ par M jusqu'au 30/11 puis tarif doublé) ou Opus 5.5 (20 € pour 78 appels en exp). Le chantier 2 ne peut pas démarrer sans cette réponse.
2. **`exp_gemini/`** : expérimentation à archiver ou code à promouvoir ? Le rapport d'architecture recommande la promotion de `pieces.py`, `mode_document.py` et `llm_router.py`.
3. **Branche par défaut** : `main` créée depuis `feat/decp-sprint-3` ? (recommandé)
4. **Hébergement** : rien n'est planifié ; le coffre-fort (chantier 4) suppose un serveur. Linux chez Hetzner comme pour BOTBILLET ?
