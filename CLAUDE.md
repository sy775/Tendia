# Tendia : consignes pour Claude Code

Lis ce fichier entièrement avant de toucher au code. Version longue : `docs/04_CONVENTIONS.md` et `docs/03_BACKLOG.md`. Architecture : `docs/01_ARCHITECTURE.md`.

## Le produit
Tendia produit pour une PME BTP un dossier de réponse à appel d'offres prêt à déposer : DCE lu en entier, prix estimé (déterministe), mémoire technique, pièces de candidature assemblées. Le client dépose lui-même. Tendia ne dépose pas, ne stocke aucun identifiant de plateforme, ne signe rien.

## Structure du dépôt
```
src/tendia/            paquet installé par pip install -e . (imports : from tendia.core import stockage)
  core/        stockage (persistance kv_storage SQLite), chemins (RACINE_DEPOT, DATA, ...), logs, http_*, budget LLM
  veille/      recup (ingestion BOAMP), classification, preset, connecteurs/
  dce/         resolution (URL DCE), telecharger, dce_finder, resolution_reference, *_downloader
  analyse/     extraire (brief), mode_document + pieces + sources_lecture (lecture exhaustive), llm_router (client LLM unique), llm_extract, llm_calibration, pdf_extract, auto_brief
  prix/        decp/ (DECP), decp_comparables, marches_attribues, fourchette_scenarios, jointure
  memoire/     services/ (digest, rédaction, docx), prompts/
  eligibilite/ matching, matching_exigences, organisme, pertinence
  ui/          app (routes Flask), fiche_marche, profil_*, cycle_marche, concurrence, templates/, static/
  pipeline.py  pipeline complet (python -m tendia)
  dossier/, coffre/   à créer (chantiers 3 et 4)
tendia_ui.py, tendia_pipeline.py   shims racine de 5 lignes
scripts/{audit,maintenance,decp,memoire}   outils CLI, jamais importés par src/
tests/         hors ligne, python tests/lancer_tous.py ; fixtures dans tests/fixtures/
presets/       14 presets, socle profil, taxonomie
docs/          doc ; le rapport docs/architecture_actuelle_2026-11_* fait foi
archive/       mis de côté, hors git ; jamais supprimé sans validation
data/, logs/   hors git ; data/dce = 124 Go sur un 2e disque, jamais sauvegardé, en lecture seule pour le mode document ; data/pieces = dossiers de travail de la lecture (zips décompressés, conversions, textes)
```
Chemins vers `data/`, `logs/`, `presets/`, `rapports/`, `archive/` : toujours via `tendia.core.chemins`, jamais de `os.path.dirname(__file__)` empilé ni de chemin relatif au répertoire courant.

## Interdits
- Lancer `Tendia.bat` : il déclenche téléchargements et appels LLM payants. Pour vérifier l'app : `python -m tendia.ui` (ou `python tendia_ui.py`).
- Appel LLM sans plafond (`--max-cost` ou `data/budget.json`) et sans journalisation dans `llm_appels`.
- `stockage.sauver(collection)` pour une écriture unitaire (réécrit toute la collection, 58 Mo sur `marches`). Utiliser `stockage.ecrire`.
- `sqlite3.connect` dans le code métier : tout passe par `stockage`.
- `Anthropic(` ou un SDK LLM hors de `analyse/llm_router.py` : tout appel passe par `call_llm` / `appeler_modele` (kill switch, plafond, journal `llm_appels`).
- Écrire dans `data/dce` : la lecture travaille dans `data/pieces/<id>`.
- Supprimer un fichier : on déplace dans `archive/<chemin d'origine>`.
- Script `diagnostic_*`, `debug_*`, `patch_*` à la racine.
- Modifier `data/tendia.db` en masse sans `.bak_<objet>_<date>` préalable dans `archive/`.
- Décider seul d'un changement d'architecture ou de schéma : le proposer dans le rapport.

## Règles
- Un chantier par session, étapes numérotées, un commit par étape (`type(scope): objet`), rapport `archive/RAPPORT_<n>.md` (en bref / points d'attention / hésitations / détail).
- Plan d'abord : lire les fichiers concernés, proposer le plan, attendre la validation, puis coder.
- Code, commentaires, commits en français. UTF-8, `sys.stdout.reconfigure(encoding="utf-8")` en tête des CLI (Windows).
- Les calculs de prix et de score sont déterministes ; le LLM extrait, il ne calcule pas.
- Tout module touché dans `core/`, `analyse/`, `eligibilite/` reçoit au moins un test hors ligne.
- Un module au-delà de 800 lignes se découpe.
- Racine : fichiers de config et les deux shims `tendia_ui.py`, `tendia_pipeline.py`, rien d'autre en `.py`.
- Avant de terminer : `python tests/lancer_tous.py` passe (échecs connus listés dans Pièges connus), l'UI démarre, puis sous-agent `audit-code`.

## Sous-agents
- `Explore` pour la lecture de début de chantier (résumé seulement).
- `testeur` avant le code de chaque étape qui crée ou change un comportement.
- `relecteur-etape` après chaque commit d'étape ; un bloquant se corrige avant l'étape suivante.
- `verif-tests` pour lancer les tests.
- `verificateur-brief` sur tout brief produit par un run.
- Clôture par `audit-code`, plus `audit-design` en parallèle si `src/tendia/ui/` est touché.
- Jamais deux sous-agents qui écrivent dans le dépôt en parallèle.
- Modèles : Fable pour écrire et vérifier, Haiku pour `verif-tests`.

## Pièges connus
- `stockage.charger` lit toute la collection ; cache mémoire par processus (UI et scripts peuvent diverger).
- Lecture DCE : mode document par défaut (`analyse/mode_document.py`, toutes les pièces, Gemini argon avec repli Sonnet 4.6, `--max-cout-par-dce` 2,5 € : un DCE plus cher est sauté, jamais tronqué). L'ancien mode (`--mode classique` : PDF du 1er niveau, 400 000 caractères, Sonnet) dézippe encore à plat dans `data/dce`, comme `memoire/services/digest_memoire.py`.
- `extraire` en mode document ne reprend pas un marché clos, absent de la base ou déjà briefé (sauf `--marche` / `--force`) ; plafond de passe par défaut 5 €.
- `tendia.veille.classification` est l'étape 2 du pipeline (7 étapes) depuis le chantier 1 : `python -m tendia` et `Tendia.bat` paient la classification (plafond `--max-cout-classification`, 5 € par défaut ; `--skip-llm` la saute). `--max-cout 0` bloque tout appel.
- `python-dotenv` installé : `http_humain`, `aws_downloader`, `dematis_downloader` chargent `.env` à l'import. Le proxy résidentiel ne s'applique que si `TENDIA_PROXY_ACTIF=1` (posé par `python -m tendia`, `Tendia.bat`, `retelecharger_*`, `rattrapage_btp_octobre`) ; UI, tests et audits passent en direct. `TENDIA_PROXY_ACTIF` ne va jamais dans `.env` : `http_humain.charger_env_fichier` l'ignore avec un avertissement. `curl_cffi` absent : `http_client` force `requests`.
- Le pipeline lance ses étapes comme fichiers (`src/tendia/veille/recup.py`, ...) : déplacer un de ces modules impose de corriger `src/tendia/pipeline.py`.
- `archive/exp_gemini/ui_exp.py` (hors git) importe encore `stockage` et `tendia_ui` à l'ancienne : cassé depuis 0b, archivé tel quel au chantier 2.
- Tests en échec connus : aucun (les attentes de `test_aws_downloader` et `test_qualifier_dce` ont été alignées sur le code au chantier 1).
- Branche de travail : `main` (branche par défaut sur GitHub). Branches de chantier `chantier/<n>-<slug>`.

## Commandes utiles
```
pip install -e .                          une fois après un clone (paquet tendia)
python -m tendia.ui                       UI sur 127.0.0.1:5000 (shim : python tendia_ui.py)
python -m tendia --skip-llm               pipeline sans appels payants (shim : python tendia_pipeline.py)
python tests/lancer_tous.py               tous les tests
python tests/test_<module>.py             un test
python scripts/audit/stats_pipeline_dce.py   état du pipeline DCE
python -m tendia.prix.decp.cli audit      état DECP
python -m tendia.veille.classification    classification Haiku seule (étape 2 du pipeline, payant)
python -m tendia.analyse.extraire --marche ID --dry-run   inventaire des pièces et coût estimé (gratuit)
python -m tendia.analyse.extraire --marche ID --max-cout 3   brief LLM d'un marché, mode document (payant)
python scripts/audit/rapport_lecture_dce.py ID   pièces lues, coût réel, sources d'un brief (lecture seule)
```
