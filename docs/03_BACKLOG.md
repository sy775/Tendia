# Tendia : backlog des chantiers

Un chantier = une session Claude Code, un objectif, un critère de fin vérifiable, un rapport dans `archive/RAPPORT_<n>.md`. Mettre à jour l'état ici à chaque chantier terminé. Ordre aligné sur le produit (00_PRODUIT.md) et sur l'ordre de construction recommandé du rapport d'architecture (§10.9).

## Tableau de bord

| # | Chantier | État | Dépend de |
|---|---|---|---|
| 0a | Dépôt propre : git, archive, tests regroupés | **Terminé le 2026-11-10** (902 → 313 fichiers) | |
| 0b | Structure `src/tendia/`, `CLAUDE.md`, branche `main`, 2 régressions de 0a | **Terminé le 2026-11-10**, réserve : `test_aws_downloader` et `test_qualifier_dce` périmés (antérieurs à 0b), repris en étape 1 du chantier 1 | 0a |
| 1 | Redémarrer la chaîne LLM | **Terminé le 2026-11-11**, 17,95 € (classification 10,85, briefs 7,10) ; 14 briefs BTP d'octobre ; majeurs de AUDIT_1 repris au chantier 2 (étape 1 : tests et `telecharger` ; étape 3 : journalisation de `llm_extract` par `llm_router`) | 0b |
| 1b | UI démo : corrections bloquantes de l'audit design (profil, clos, pagination, non classé, bloc décision) | **Terminé le 2026-11-11** | 1 |
| 2 | Promouvoir le mode document en prod (lecture exhaustive des DCE) | **À reprendre, voir 2b** (fidélité 18/30, fusion qui perd l'heure limite et invente des montants, BOAMP-26-102749 non lu) ; coût réel 6,43 € ; mode document en prod | 1 |
| 2b | Fiabiliser la fusion (champs critiques sans LLM, montant publié / estimé séparés), finir la lecture, produire les briefs | **En cours, plafond 28 €** | 2 |
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
- Étape 1 : aligner `test_aws_downloader` et `test_qualifier_dce` sur le comportement en prod ; constats majeurs de `AUDIT_0b.md` (chemins des scripts anti-ban, `test_chemins.py` étendu, règle tests de `CLAUDE.md` rétablie) ; `prototype_grille_notation.py` archivé.
- Proxy résidentiel conditionné à `TENDIA_PROXY_ACTIF=1`, posé par `python -m tendia`, `Tendia.bat` et les scripts `retelecharger_*` ; UI, tests et audits en direct.
- `classification.sauver_classification` en `stockage.ecrire` (règle 9).
- Reporté au chantier 7 : alias morts de 0b, numéros de ligne du rapport 0b, deux phrases de `01_ARCHITECTURE.md` (constats mineurs de `AUDIT_0b.md`).
- Intégrer `tendia_classification` comme étape du pipeline (après la récup, avant la résolution DCE), avec `--skip-llm` respecté.
- Classifier les 1 992 marchés d'octobre (Haiku, ~12 €).
- Sélectionner le BTP pertinent (preset `btp` + profil démo BTP) et ne lancer le brief que sur ceux dont le DCE est complet. Budget plafonné via `data/budget.json`.
- Journaliser tous les appels LLM dans `llm_appels` (classification, mémoire, calibration), pas seulement l'extraction.
- Critère de fin : 0 marché BTP d'octobre sans classification ; N briefs BTP récents disponibles pour les démos ; coût réel dans le rapport.
- Résultat : 1 757 marchés classés, 235 rejetés, 14 briefs BTP, coût 17,95 € (voir archive/RAPPORT_1.md).

### 1b : UI démo
- Source : docs/audit_design/2026-11-10_synthese.md (branche audit/design-2026-11 fusionnée dans main).
- Décision du 2026-11-11 : état `non_classe` distinct de `non_pertinent` ; pas de pré-classement CPV.
- Hors périmètre : mobile 390 px, refonte espace entreprise, build Tailwind (objectif 3, étapes 2-3 et 5).
- Résultat : profil BTP enregistrable, marchés clos (définition unique `core.etat_marche`) hors des listes, `matching` qui lit `classifications_ia` (dashboard démo 0 → 145 marchés) avec verdict `non_classe`, bloc de décision en tête de fiche ; explorer 6 141 Ko / 2 794 cartes / 1,32 s → 204 Ko / 50 cartes / 0,45 s à chaud ; captures dans docs/audit_design/apres/ ; 6 majeurs de AUDIT_1b reportés (voir archive/RAPPORT_1b.md).

### 2 : lecture exhaustive des DCE
- Étape 1 (hygiène post-1 et post-1b) : tests sur la journalisation de `llm_calibration` et sur `extraire.plafond_atteint` / `cout_du_resultat` ; `telecharger.main` en écriture unitaire ; `--max-cout 0` bloque au lieu de désactiver ; `TENDIA_PROXY_ACTIF` interdit dans `.env` (`.env.example`, CLAUDE.md) ; docs « 6 étapes » / « classification hors pipeline » corrigées ; tests sans écriture dans `logs/` ; `_method` inconnu → 400 sur l'explorer.
- Étapes 2 et 3 : `llm_router` journalise et plafonne chaque tentative (relances JSON comprises) ; `llm_extract` et les autres appels directs passent par lui (majeur 1 de AUDIT_1).
- Plafond mensuel novembre : 45 € (décision du 2026-11-11), retour à 30 € en décembre.
- 5 DCE de référence : les 3 marchés sans PDF lisible du rapport 1 (102749, 104121, 103934) + 2 briefs réussis à comparer.
- Reste du rattrapage BTP : 10 marchés à DCE complet sans brief, ~5 €, à lancer après la promotion du mode document.
- Promouvoir `exp_gemini/pieces.py` (inventaire récursif, conversion .doc/.xls/.odt/.rtf, pages) et `mode_document.py` dans `src/tendia/analyse/`.
- Promouvoir `llm_router.py` comme client LLM unique (remplacer les 6 `Anthropic()` directs).
- Modèle d'analyse par défaut : Gemini 4 argon, repli Sonnet 4.6 (décision du 2026-11-10).
- `exp_gemini/ui_exp.py` : corriger ses deux imports (`tendia_ui` → `tendia.ui.app`) avant de promouvoir ou d'archiver.
- Critère de fin : sur 5 DCE BTP de référence, 100 % des pièces lues, brief avec sources pièce + page, coût par DCE mesuré.
- Résultat (2026-11-11, archive/RAPPORT_2.md) : 4 DCE lus sur 5 (104121, 103934, 104292, 104768 ; 102749 sauté, 104234 et 103744 remplacés car estimés à plus de 10 €), 138/138 pièces de texte lues, sources vérifiées à juste titre 20/20, fidélité 18/24 sur les DCE lus (18/30 au critère) ; coût moyen par DCE 1,61 € au tarif argon actuel, 3,18 € au tarif du 01/12, 2,39 € en équivalent Sonnet 4.6 ; 4 briefs produits, étape 8 (10 briefs BTP) non lancée.
- À reprendre : post-traitement déterministe de la fusion (montant `non_communique` quand aucune note par pièce n'en porte, heure limite reprise de la note du RC, agrégat technique fidèle au RC) ou changement du prompt de fusion (décision Younes) ; retélécharger 102749 puis le lire (`--max-cout-par-dce 5`) ; puis l'étape 8.

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
- Reçu du chantier 1b (décisions du 2026-11-11) :
  - « à classer » : un compteur et un lien vers l'explorer, hors de la liste du dashboard ;
  - `matching.evaluer` reçoit la classification de ses appelants (le repli par lecture en base est conservé) ;
  - `types_ouvrages` en `enum` dans `presets/btp/_schema.json`.
- Modules à découper (règle des 800 lignes) : `analyse/extraire.py` (~1 700 l.), `analyse/llm_extract.py` (~1 500 l.).
- `memoire/services/digest_memoire.py` dézippe encore à plat dans `data/dce` : le faire lire via `pieces.inventorier`.
- Purge des dossiers de travail `data/pieces/<id>` des marchés clos (4,4 Go après le chantier 2) : décision à prendre, la règle actuelle est de ne rien supprimer.
- Majeurs reportés du chantier 2 : AUDIT_2 (valeur affichée à côté d'une source non contrôlée, plafond par DCE limité à l'estimation, `plan_ignore` sur le seul nom, quota journalier incohérent entre modes, écritures restantes dans `data/dce`) et audit design de la fiche (docs/audit_design/2026-11-11_fiche_sources.md : sources invisibles à l'arrivée, saut d'ancre `#sec-0`, heure limite, montant publié, visite obligatoire).
- Majeurs de AUDIT_1b non traités au chantier 2 : `scripts/audit/audit_matching_n2.py` ignore le verdict `non_classe` ; le bloc de décision peut afficher des jours restants négatifs quand la date limite vient du brief ; `ui/app.py` (2 200 lignes) à découper.

## Questions ouvertes (à trancher par Younes)

1. **Tranchée le 2026-11-10 : Gemini 4 argon via `llm_router`, repli Sonnet 4.6.** Modèle d'analyse par défaut en prod : Sonnet 4.6 (prod actuelle, incomplète), Gemini 4 argon (meilleur sur les données publiques selon les tests d'octobre, 2 $/10 $ par M jusqu'au 30/11 puis tarif doublé) ou Opus 5.5 (20 € pour 78 appels en exp).
2. **Tranchée le 2026-11-10 : promotion de `pieces.py`, `mode_document.py` et `llm_router.py`.** `exp_gemini/` : expérimentation à archiver ou code à promouvoir ? Le rapport d'architecture recommande la promotion de `pieces.py`, `mode_document.py` et `llm_router.py`.
3. **Tranchée au chantier 0b : `main` créée, branche de travail.** Branche par défaut : `main` créée depuis `feat/decp-sprint-3` ? (recommandé)
4. **Hébergement** : rien n'est planifié ; le coffre-fort (chantier 4) suppose un serveur. Linux chez Hetzner comme pour BOTBILLET ?
5. Avis `RECTIFICATIF` (121) et `ANNULATION` (3) : rejet au pré-filtre avec rattachement au marché d'origine, ou classification comme aujourd'hui (≈ 0,75 € par mois d'ingestion) ? Recommandation : rejet + rattachement, à faire au chantier 7 avec le suivi des attributions ; d'ici là, laisser classer.
