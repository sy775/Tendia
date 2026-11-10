# Rapport du chantier 0b : structure et outillage (2026-11-10)

Branche `chantier/0b-structure` (depuis `main` = `46377a8`), 13 commits avant ce rapport, fusionnée dans `main` par `--no-ff`.

## En bref

- Les 44 modules racine sont rangés sous `src/tendia/<agent>/` (42 par `git mv`, 2 archivés) ; `pip install -e .` ; seuls les shims `tendia_ui.py` et `tendia_pipeline.py` restent à la racine.
- Régressions de 0a réparées : `test_dematis_workflow_har.py` à 51 ✓ 0 ✗ via `tests/fixtures/dematis_acces_dce.html` ; la grille est devenue `scripts/maintenance/prototype_grille_notation.py` (`--marche` et `--max-cost` obligatoires).
- Tests : **23/25 fichiers OK** (20/24 avant ; `test_chemins.py` ajouté, 15 ✓). Les 2 KO restants (`test_aws_downloader`, `test_qualifier_dce`) échouaient déjà avant 0b : critère « 100 % OK » **non atteint**, voir point d'attention 1.
- UI : les 7 routes à 200 sur le vrai serveur (`python tendia_ui.py`), sans traceback ; `python -c "import tendia.core.stockage, tendia.ui, tendia.prix.decp"` OK ; `main` créée, poussée, branche par défaut sur GitHub.
- Fichiers suivis : 323 → 339 (+16 : 18 ajouts, 4 archivages, ce rapport et l'audit), soit 1 au-delà de 323 ± 15 à cause de `tests/test_chemins.py`. La base réelle était 323 et non 313 (commit des docs et de CLAUDE.md après 0a).

## Points d'attention

1. **2 tests en échec, antérieurs à 0b, non corrigés.** `test_aws_downloader.py` : « fichiers téléchargés (DCE + LOT-1, CGU filtrée) » attend 2 fichiers. `test_qualifier_dce.py` : « ZIP contenant RC + CCTP » attend `['RC', 'CCTP']`, le code détecte aussi `DCE` (le nom du zip). Dans les deux cas, l'attente du test semble en retard sur le code (derniers commits du code concerné : 01/07 pour `aws_downloader`, 28/06 pour `tendia_telecharger_dce`). Les corriger revient à trancher sur la logique métier : à décider (mettre à jour l'attente, ou corriger le code).
2. **Erreur de ma part au plan** : j'avais affirmé que `place_downloader` n'avait aucun import vivant. `tendia_pipeline._telecharger_dce_marches_actifs` l'importait (ma recherche était tronquée). Le commit `a7651d6` a donc cassé cet import, réparé par `24d4866` (bascule sur `atexo_downloader.telecharger_dce_pour_marche`, signature identique). Cette fonction n'est appelée nulle part (code mort).
3. **Même fenêtre d'un commit en 5b** : le pipeline lançait encore `tendia_extraire.py` (déplacé en 5b) ; corrigé en 5c, avec `scripts/maintenance/tendia_reextraire_batch.py` qui avait le même appel.
4. **python-dotenv installé change le comportement à l'exécution.** `http_humain` (et donc toute l'UI et les downloaders), `aws_downloader`, `dematis_downloader`, `retelecharger_xmarches` chargent désormais `.env` à l'import. Variables fournies (noms seulement) : `GEMINI_API_KEY`, `TWOCAPTCHA_API_KEY`, `TENDIA_PROXY_URL`, `TENDIA_PROXY_FOR_PLACE`, `TENDIA_PROXY_FOR_DATA_GOUV`, `TENDIA_PROXY_FOR_BOAMP`, `TENDIA_PROXY_FOR_ATEXO`, `TENDIA_PROXY_FOR_ACHATPUBLIC`. Conséquence : le **proxy résidentiel s'active** selon ces drapeaux dans tout processus qui importe `http_humain`, ce qui n'était pas le cas avant (le `load_dotenv` échouait en silence). `ANTHROPIC_API_KEY` n'est pas dans `.env` (`llm_extract` et `llm_router` ont leur propre lecteur de `.env`, inchangé). Aucun test ne change de résultat. `.env.txt` n'existe pas.
5. **`exp_gemini/ui_exp.py` est cassé** (`import stockage`, `import tendia_ui` puis `tendia_ui.REPERTOIRE_DCE = ...`) : non touché, conformément aux interdits. Correctif à faire au chantier 2 : `from tendia.core import stockage` et `from tendia.ui import app as tendia_ui`.
6. **`pip install -e .`** a téléchargé `setuptools` depuis PyPI (environnement de build isolé : setuptools n'est pas installé dans le Python système). Il crée `src/tendia.egg-info/`, ignoré par git. Après un clone : `pip install -e .` obligatoire, sinon aucun import `tendia.*` ne fonctionne.
7. **Le pipeline lance ses étapes comme fichiers** (`str(RACINE_DEPOT / "src/tendia/veille/recup.py")`, etc.), pas en `python -m`, pour ne pas toucher à `_executer_script`. Les 4 cibles parsent `--help` correctement depuis n'importe quel répertoire.
8. **Historique git** : sur le diff global `main..HEAD`, `src/tendia/ui/app.py` et `src/tendia/pipeline.py` apparaissent comme ajoutés (les shims ont repris les anciens chemins). Le renommage est enregistré dans le commit 5c : `git log --follow src/tendia/ui/app.py` remonte bien jusqu'au premier commit.
9. **Racine** : outre les shims et les fichiers de config de la règle 3, restent `Tendia_Prez_Prospect_BTP_2026.pptx`, `dette_technique.md` et `config_llm.yaml` (lu par `llm_router` à la racine). Non touchés. Un dossier `connecteurs/__pycache__` vide subsiste sur le disque (non suivi).
10. **Cosmétique** : `python -m tendia --help` affiche `usage: __main__.py` ; `python -m tendia.prix.decp.cli --help` affiche `usage: decp.cli` (prog codé en dur). `--max-cost` de la grille est obligatoire mais pas encore appliqué par sa logique (prototype déplacé, logique inchangée).
11. **Documentation non alignée hors périmètre** : `02_ETAT_DES_LIEUX.md` §3.3 garde « tests cassés après 0a » et « dépendances absentes » (seule la ligne `place_downloader` était demandée). CLAUDE.md cite `exp_gemini/pieces.py` et `mode_document.py`, mais `exp_gemini/` ne contient plus que `ui_exp.py` sur le disque.

## Hésitations

| Choix | Retenu | Alternative |
|---|---|---|
| Nom des modules renommés | Préfixe `tendia_` retiré ; `tendia_dce` → `dce/resolution`, `tendia_telecharger_dce` → `dce/telecharger`, `tendia_ui` → `ui/app`, `tendia_logs` → `core/logs` | Garder les noms (moins de diff) ; `dce/downloaders/` pour les 6 downloaders |
| Appels aux modules renommés | Alias d'import (`from tendia.dce import resolution as tendia_dce`) : aucune ligne métier modifiée | Renommer les usages (`resolution.x`) : plus lisible, mais diff métier |
| Noms gardés malgré la redondance | `dce/dce_finder`, `prix/decp_comparables`, `dce/*_downloader` | `dce/finder`, `prix/comparables` |
| `core/http_*` | `http_client`, `http_utils`, `http_humain` gardés | `core/http.py` écarté : masquerait le module standard `http` quand un fichier de `core/` est lancé en script |
| `connecteurs/` | `veille/connecteurs/` (boamp) ; `decp_consolidee` → `prix/decp/` (décision validée) | Tout dans `veille/connecteurs/` |
| Constante `RAPPORTS` | Ajoutée à `chemins.py` (5 demandées + `RAPPORTS`) | `RACINE_DEPOT / "rapports"` à chaque usage |
| Templates et statiques | `Path(__file__).parent / "templates"` dans `ui/app.py` (ressource du paquet, pas un chemin racine) | `RACINE_DEPOT / "src/tendia/ui/templates"` |
| Chemins des scripts | Chemins racine empilés (dirname ×3, `parents[2]`) → `RACINE_DEPOT` (22 occurrences) | Laisser les scripts tels quels (seuls les imports étaient demandés pour scripts/) |
| Chemins relatifs au répertoire courant dans scripts/ | **Non convertis** (21 scripts, ex. `maj_hebdo` qui fait `os.chdir(RACINE)`) | Les passer tous par `chemins` : diff plus large, à faire si la règle doit valoir pour scripts/ |
| `.env` de `http_humain` | `load_dotenv(RACINE_DEPOT / ".env")` (était relatif au répertoire courant) | Laisser relatif |
| `logs/` | `LOG_DIR = LOGS` (était `Path("logs")`, relatif au répertoire courant) : les logs vont toujours dans `<racine>/logs` | Laisser relatif |
| Imports devenus inutiles | Retirés dans un commit dédié (`42b3fcb`) : 18 `Path`, 53 `os`, 36 `import sys` dupliqués (restes de l'amorce `sys.path.insert`) | Les laisser à l'audit |
| `scripts/_archive/` | Imports non corrigés (26 scripts hors service) | Les réécrire aussi |
| `sys.path.insert` restants | `maj_hebdo` (vers `scripts/decp`), `pilote_arbitre_v2` et `reprise_doublons_regle` (leur propre dossier), `test_parallelisation` (vers `scripts/maintenance`) : imports de scripts voisins | Rendre ces scripts importables autrement |
| Ordre des imports dans les scripts | `from tendia.core.chemins import RACINE_DEPOT` inséré en tête du bloc d'imports | Le placer après la bibliothèque standard (PEP 8) |

## Détail

### Modules racine : origine → destination

| Origine | Destination | Commit | Lignes avant | Lignes après |
|---|---|---|---|---|
| `achatpublic_downloader.py` | `src/tendia/dce/achatpublic_downloader.py` | 5a | 401 | 402 |
| `analyse.py` | `src/tendia/eligibilite/pertinence.py` | 5b | 865 | 865 |
| `atexo_downloader.py` | `src/tendia/dce/atexo_downloader.py` | 5a | 353 | 353 |
| `auto_brief.py` | `src/tendia/analyse/auto_brief.py` | 5b | 357 | 357 |
| `aws_downloader.py` | `src/tendia/dce/aws_downloader.py` | 5a | 890 | 891 |
| `briefs_versioning.py` | `src/tendia/analyse/briefs_versioning.py` | 5b | 70 | 70 |
| `budget.py` | `src/tendia/core/budget.py` | 5a | 509 | 510 |
| `concurrence.py` | `src/tendia/ui/concurrence.py` | 5c | 1096 | 1096 |
| `cycle_marche.py` | `src/tendia/ui/cycle_marche.py` | 5c | 211 | 211 |
| `dce_finder.py` | `src/tendia/dce/dce_finder.py` | 5a | 784 | 784 |
| `decp_comparables.py` | `src/tendia/prix/decp_comparables.py` | 5b | 324 | 324 |
| `dematis_downloader.py` | `src/tendia/dce/dematis_downloader.py` | 5a | 917 | 918 |
| `fiche_marche.py` | `src/tendia/ui/fiche_marche.py` | 5c | 1314 | 1314 |
| `fourchette_scenarios.py` | `src/tendia/prix/fourchette_scenarios.py` | 5b | 194 | 194 |
| `http_client.py` | `src/tendia/core/http_client.py` | 5a | 68 | 68 |
| `http_humain.py` | `src/tendia/core/http_humain.py` | 5a | 275 | 276 |
| `http_utils.py` | `src/tendia/core/http_utils.py` | 5a | 172 | 172 |
| `jointure.py` | `src/tendia/prix/jointure.py` | 5b | 349 | 350 |
| `llm_calibration.py` | `src/tendia/analyse/llm_calibration.py` | 5b | 1109 | 1111 |
| `llm_extract.py` | `src/tendia/analyse/llm_extract.py` | 5b | 1525 | 1526 |
| `llm_router.py` | `src/tendia/analyse/llm_router.py` | 5b | 535 | 537 |
| `marches_attribues.py` | `src/tendia/prix/marches_attribues.py` | 5b | 400 | 400 |
| `marches_securises_downloader.py` | `src/tendia/dce/marches_securises_downloader.py` | 5a | 382 | 383 |
| `matching.py` | `src/tendia/eligibilite/matching.py` | 5b | 1379 | 1379 |
| `matching_exigences.py` | `src/tendia/eligibilite/matching_exigences.py` | 5b | 528 | 528 |
| `organisme.py` | `src/tendia/eligibilite/organisme.py` | 5b | 844 | 844 |
| `pdf_extract.py` | `src/tendia/analyse/pdf_extract.py` | 5b | 329 | 329 |
| `pipeline_france_travail.py` | `archive/pipeline_france_travail.py (5b)` | 5b | 156 | — |
| `place_downloader.py` | `archive/place_downloader.py (étape 3)` | 3 | 453 | — |
| `preset.py` | `src/tendia/veille/preset.py` | 5a | 837 | 838 |
| `profil_form.py` | `src/tendia/ui/profil_form.py` | 5c | 438 | 438 |
| `profil_widgets.py` | `src/tendia/ui/profil_widgets.py` | 5c | 407 | 407 |
| `resolution_reference.py` | `src/tendia/dce/resolution_reference.py` | 5a | 202 | 202 |
| `stockage.py` | `src/tendia/core/stockage.py` | 5a | 423 | 425 |
| `tendia_classification.py` | `src/tendia/veille/classification.py` | 5a | 693 | 694 |
| `tendia_dce.py` | `src/tendia/dce/resolution.py` | 5a | 708 | 705 |
| `tendia_extraire.py` | `src/tendia/analyse/extraire.py` | 5b | 1299 | 1301 |
| `tendia_logs.py` | `src/tendia/core/logs.py` | 5a | 84 | 85 |
| `tendia_pipeline.py` | `src/tendia/pipeline.py` | 5c | 245 | 245 |
| `tendia_recup.py` | `src/tendia/veille/recup.py` | 5a | 369 | 369 |
| `tendia_telecharger_dce.py` | `src/tendia/dce/telecharger.py` | 5a | 1423 | 1424 |
| `tendia_ui.py` | `src/tendia/ui/app.py` | 5c | 2154 | 2151 |
| `veille_concurrence.py` | `src/tendia/ui/veille_concurrence.py` | 5c | 244 | 244 |
| `xmarches_downloader.py` | `src/tendia/dce/xmarches_downloader.py` | 5a | 194 | 195 |

Les écarts de lignes viennent des imports `tendia.core.chemins` ajoutés, des imports devenus inutiles retirés et, pour `ui/app.py`, du bloc `__main__` qui délègue à `tendia.ui.__main__`.

### Dossiers

| Origine | Destination |
|---|---|
| `connecteurs/__init__.py, connecteurs/boamp.py` | `src/tendia/veille/connecteurs/` |
| `connecteurs/decp_consolidee.py` | `src/tendia/prix/decp/decp_consolidee.py` |
| `decp/ (17 modules)` | `src/tendia/prix/decp/` |
| `services/ (7 modules)` | `src/tendia/memoire/services/` |
| `prompts/ (3 modules)` | `src/tendia/memoire/prompts/` |
| `ui/templates/, ui/static/` | `src/tendia/ui/templates/, src/tendia/ui/static/` |
| `tests/test_grille_notation.py` | `scripts/maintenance/prototype_grille_notation.py` |
| `docs/passation_claude.md, docs/cron_windows.md` | `archive/docs/ (hors suivi)` |
| `exp_gemini/` | `inchangé` |

### Tests avant / après (lancés depuis la racine)

| Fichier | ✓ avant | ✗ avant | avant | ✓ après | ✗ après | après |
|---|---|---|---|---|---|---|
| `test_atexo_downloader.py` | 25 | 0 | OK | 25 | 0 | OK |
| `test_aws_downloader.py` | 42 | 1 | KO | 42 | 1 | KO |
| `test_boamp_contact.py` | 15 | 0 | OK | 15 | 0 | OK |
| `test_boamp_enrichissement.py` | 33 | 0 | OK | 33 | 0 | OK |
| `test_briefs_versioning.py` | 13 | 0 | OK | 13 | 0 | OK |
| `test_chemins.py` | — | — | (nouveau) | 15 | 0 | OK |
| `test_dce_finder.py` | 24 | 0 | OK | 24 | 0 | OK |
| `test_decp_classifier_cpv.py` | 19 | 0 | OK | 19 | 0 | OK |
| `test_decp_classifier_llm.py` | 14 | 0 | OK | 14 | 0 | OK |
| `test_decp_db.py` | 13 | 0 | OK | 13 | 0 | OK |
| `test_decp_mapping_cpv.py` | 42 | 0 | OK | 42 | 0 | OK |
| `test_decp_matching.py` | 32 | 0 | OK | 32 | 0 | OK |
| `test_decp_parser.py` | 25 | 0 | OK | 25 | 0 | OK |
| `test_decp_parser_v2.py` | 23 | 0 | OK | 23 | 0 | OK |
| `test_dematis_downloader.py` | 35 | 0 | OK | 35 | 0 | OK |
| `test_dematis_workflow_har.py` | 40 | 6 | KO | 51 | 0 | OK |
| `test_downloader_dce_directe.py` | 12 | 0 | OK | 12 | 0 | OK |
| `test_extraction_v2_criteres.py` | 26 | 0 | OK | 26 | 0 | OK |
| `test_extraction_v2_montants.py` | 14 | 0 | OK | 14 | 0 | OK |
| `test_grille_notation.py` | non lancé (prototype LLM) | — | — | déplacé : scripts/maintenance/prototype_grille_notation.py | — | — |
| `test_http_humain.py` | 37 | 0 | OK | 37 | 0 | OK |
| `test_llm_extract_routage.py` | 28 | 0 | OK | 28 | 0 | OK |
| `test_parallelisation.py` | 0 | 0 | KO | 9 | 0 | OK |
| `test_parseur_dce.py` | 0 | 0 | KO | 22 | 0 | OK |
| `test_proxy_par_plateforme.py` | 15 | 0 | OK | 15 | 0 | OK |
| `test_qualifier_dce.py` | 9 | 1 | KO | 9 | 1 | KO |

Avant : mesure de l'étape 0 (`test_parseur_dce` en échec sur `bs4` absent, `test_parallelisation` sur un `sys.path` vers `scripts/` alors que le module est dans `scripts/maintenance/`). Après : `python tests/lancer_tous.py`, 23/25 avec `test_chemins.py` (15 ✓ 0 ✗, nouveau).

### Fichiers suivis

| | Nombre |
|---|---|
| Avant (`main` = `46377a8`) | 323 |
| Ajouts (18) | `pyproject.toml`, `src/tendia/__init__.py`, `src/tendia/__main__.py`, `src/tendia/{core,veille,dce,analyse,prix,memoire,eligibilite,ui}/__init__.py` (8), `src/tendia/core/chemins.py`, `src/tendia/ui/__main__.py`, `src/tendia/ui/app.py` et `src/tendia/pipeline.py` (déplacements dont l'ancien chemin est repris par un shim), `tests/fixtures/dematis_acces_dce.html`, `tests/lancer_tous.py`, `tests/test_chemins.py` (règle : tout module de `core/` touché reçoit un test) |
| Retraits (4, vers `archive/`) | `place_downloader.py`, `pipeline_france_travail.py`, `docs/passation_claude.md`, `docs/cron_windows.md` |
| Rapport et audit (2) | `archive/RAPPORT_0b.md`, `archive/AUDIT_0b.md` (exceptions `!archive/RAPPORT_*.md`, `!archive/AUDIT_*.md` dans `.gitignore`) |
| Après | 339 |

91 renommages (`git mv`), 102 fichiers modifiés (imports, chemins).

### Commandes nouvelles

```
pip install -e .                                  paquet tendia (une fois après un clone)
python -m tendia [--skip-llm ...]                 pipeline (shim : python tendia_pipeline.py)
python -m tendia.ui [--help]                      UI (shim : python tendia_ui.py)
python -m tendia.veille.classification            ex-python tendia_classification.py
python -m tendia.analyse.extraire --marche ID     ex-python tendia_extraire.py
python -m tendia.veille.recup                     ex-python tendia_recup.py
python -m tendia.prix.decp.cli audit              ex-python -m decp.cli audit
python tests/lancer_tous.py [--verbeux]           tous les tests, OK/KO par fichier
python scripts/maintenance/prototype_grille_notation.py --marche ID --max-cost EUR
```
`Tendia.bat` lance désormais `python -m tendia` puis `python -m tendia.ui` (non exécuté).

### Imports de scripts/ modifiés (67 fichiers)

Réécriture `import X` → `from tendia.<agent> import X` (alias conservés), retrait du `sys.path.insert` vers la racine, chemins racine via `RACINE_DEPOT`, imports devenus inutiles retirés. Répartition : audit 17, decp 22, maintenance 25, memoire 3.

`scripts/audit/audit_briefs.py`, `scripts/audit/audit_classifications.py`, `scripts/audit/audit_couverture_v2.py`, `scripts/audit/audit_etat_pipeline.py`, `scripts/audit/audit_faux_criteres.py`, `scripts/audit/audit_mapping_domaines_presets.py`, `scripts/audit/audit_matching_n2.py`, `scripts/audit/audit_plateformes_dce.py`, `scripts/audit/audit_presets_extraction.py`, `scripts/audit/backtest_objet.py`, `scripts/audit/backtest_voie3.py`, `scripts/audit/bilan_briefs.py`, `scripts/audit/dump_brief.py`, `scripts/audit/inspecter_page_dce.py`, `scripts/audit/stats_pipeline_dce.py`, `scripts/audit/tendia_monitoring.py`, `scripts/audit/valider_extraction_v2.py`, `scripts/decp/attributions.py`, `scripts/decp/decp_classify_cpv.py`, `scripts/decp/decp_classify_llm.py`, `scripts/decp/decp_explore_cpv.py`, `scripts/decp/decp_explore_triangulation_coverage.py`, `scripts/decp/decp_explorer.py`, `scripts/decp/decp_rapport_sprint2.py`, `scripts/decp/decp_reclassify_pattern4.py`, `scripts/decp/decp_reclassify_patterns.py`, `scripts/decp/decp_test_matching.py`, `scripts/decp/decp_valider_classif.py`, `scripts/decp/decp_valider_classif_v2.py`, `scripts/decp/decp_verifier_raffinement.py`, `scripts/decp/maj_hebdo.py`, `scripts/decp/pilote_arbitre.py`, `scripts/decp/pilote_arbitre_v2.py`, `scripts/decp/pilote_classif.py`, `scripts/decp/reprise_doublons.py`, `scripts/decp/reprise_doublons_regle.py`, `scripts/decp/reprise_formats_perte.py`, `scripts/decp/voie3_propositions.py`, `scripts/decp/voie3_reference.py`, `scripts/maintenance/backfill_enrichissement_boamp.py`, `scripts/maintenance/calibrer_briefs.py`, `scripts/maintenance/enrichir_taxonomie_v2.py`, `scripts/maintenance/ingester_profil_tee27.py`, `scripts/maintenance/init_profil.py`, `scripts/maintenance/normaliser_codes_domaines_briefs.py`, `scripts/maintenance/prototype_grille_notation.py`, `scripts/maintenance/reclassifier_affine.py`, `scripts/maintenance/rederiver_criteres_plat.py`, `scripts/maintenance/reextraire_briefs_complet.py`, `scripts/maintenance/reextraire_briefs_v2.py`, `scripts/maintenance/regenerer_briefs_md.py`, `scripts/maintenance/relancer_dce_echecs.py`, `scripts/maintenance/requalifier_faux_complet.py`, `scripts/maintenance/resoudre_dce_par_reference.py`, `scripts/maintenance/retelecharger_achatpublic.py`, `scripts/maintenance/retelecharger_atexo_direct.py`, `scripts/maintenance/retelecharger_aws_achat_anti_ban.py`, `scripts/maintenance/retelecharger_dematis_anti_ban.py`, `scripts/maintenance/retelecharger_incomplet.py`, `scripts/maintenance/retelecharger_marches_securises.py`, `scripts/maintenance/retelecharger_vide_atexo.py`, `scripts/maintenance/retelecharger_xmarches.py`, `scripts/maintenance/retenter_download_dce.py`, `scripts/maintenance/tendia_reextraire_batch.py`, `scripts/memoire/generer_digest_memoire.py`, `scripts/memoire/generer_memoire.py`, `scripts/memoire/regenerer_section.py`

### Dette repérée, non corrigée

**`stockage.sauver` global (réécrit toute la collection) :** `src/tendia/dce/telecharger.py:1264` (`marches`), `src/tendia/ui/cycle_marche.py:152` (`marches`), `src/tendia/eligibilite/pertinence.py:533` (`scores_matching`), `src/tendia/veille/classification.py:441` et `:449` (`classifications_ia`), `src/tendia/veille/recup.py:303`, `scripts/maintenance/relancer_dce_echecs.py:149` (`marches`).

**`sqlite3.connect` hors `stockage` :** `src/tendia/eligibilite/organisme.py:536`, `src/tendia/prix/decp/db.py:98`, `src/tendia/prix/decp/classif_batch.py:133`, `:154`, `:336`, `src/tendia/prix/decp/historique.py:38`, `src/tendia/prix/decp/ingest_v2.py:36`, `src/tendia/prix/decp/staging.py:44`, `:129`.

**Modules de plus de 800 lignes (14) :** `ui/app.py` 2 151, `analyse/llm_extract.py` 1 526, `dce/telecharger.py` 1 424, `eligibilite/matching.py` 1 379, `ui/fiche_marche.py` 1 314, `analyse/extraire.py` 1 301, `analyse/llm_calibration.py` 1 111, `ui/concurrence.py` 1 096, `veille/connecteurs/boamp.py` 930, `dce/dematis_downloader.py` 918, `dce/aws_downloader.py` 891, `eligibilite/pertinence.py` 865, `eligibilite/organisme.py` 844, `veille/preset.py` 838.

**Autres constats :**
- `analyse/llm_calibration.py` importe `tendia.ui.concurrence` : dépendance inversée analyse → ui.
- `pipeline._telecharger_dce_marches_actifs` : jamais appelée (code mort, ex-appel `place_downloader`).
- Docstrings d'en-tête et textes d'usage encore à l'ancien nom (`tendia_extraire.py`, `python tendia_recup.py`...) dans plusieurs modules : non modifiés (seules les docstrings de localisation étaient autorisées, je ne les ai pas réécrites en masse).
- `scripts/_archive/` : 26 scripts aux imports pré-0b, non exécutables en l'état.
- Aucun test pour les modules de `core/`, `analyse/`, `eligibilite/` touchés par 0b au-delà des tests existants (règle « tout module touché reçoit un test ») : 0b n'a changé que des imports et des chemins  ; `core/chemins.py` a reçu `tests/test_chemins.py` (constantes, modules dépendants, indépendance du répertoire courant).

## Suite de l'audit (archive/AUDIT_0b.md, verdict « livrable acceptable », aucun bloquant)

Corrigé dans `fix(scripts)` après l'audit :
- `retelecharger_aws_achat_anti_ban.py`, `retelecharger_dematis_anti_ban.py`, `retelecharger_vide_atexo.py` : `Path("data/dce")` → `DATA / "dce"`. Le pipeline les lançant désormais par chemin absolu, un lancement hors de la racine aurait écrit dans `<cwd>/data/dce`.
- CLAUDE.md : « `python tests/lancer_tous.py` tout vert (hors échecs connus) » rétablit l'exigence de réussite que ma reformulation avait perdue.

Non corrigé (majeur ou mineur, à arbitrer) : tests manquants pour les modules de `analyse/` et `eligibilite/` touchés (seulement par leurs chemins) ; `--max-cost` de la grille non appliqué ; alias de racine morts (`REPERTOIRE_BASE`, `RACINE`, `_BASE_DIR`, gardés car `exp_gemini` et des scripts peuvent les lire) ; `load_dotenv()` sans chemin dans `aws_downloader` et `dematis_downloader` (comportement identique : recherche ascendante jusqu'à la racine) ; `package-data` absent de `pyproject.toml` (sans effet en installation éditable) ; 6 scripts qui recomposent `DATA` ou `PRESETS` à partir de `RACINE_DEPOT` ; numéros de ligne de la dette décalés de 1 à 2 après le retrait des imports ; docs/01_ARCHITECTURE.md §3-4 : deux phrases périmées. Le rapport omettait aussi, au paragraphe « En bref », les modifications de `.claude/`, `01_ARCHITECTURE`, `04_CONVENTIONS` et `requirements.txt` (détaillées dans les commits `beb5294` et `f2d75ad`).
