# Tendia : consignes pour Claude Code

Lis ce fichier entièrement avant de toucher au code. Version longue : `docs/CONVENTIONS.md` et `docs/BACKLOG.md`.

## Le produit
Tendia produit pour une PME BTP un dossier de réponse à appel d'offres prêt à déposer : DCE lu en entier, prix estimé (déterministe), mémoire technique, pièces de candidature assemblées. Le client dépose lui-même. Tendia ne dépose pas, ne stocke aucun identifiant de plateforme, ne signe rien.

## Structure du dépôt (après le chantier 0b)
```
src/tendia/
  core/        stockage (persistance kv_storage SQLite), logs, http, anti-ban, budget LLM
  veille/      ingestion BOAMP, classification, presets sectoriels
  dce/         résolution d'URL et downloaders par plateforme
  analyse/     extraction texte, inventaire des pièces, appel LLM, brief
  prix/        DECP, comparables, estimation (déterministe)
  memoire/     mémoire technique (digest, rédaction, docx)
  eligibilite/ profil entreprise, matching, exigences
  dossier/     assemblage du dossier de réponse (à créer)
  coffre/      pièces entreprise réutilisables (à créer)
  ui/          Flask, templates Jinja, static
scripts/{audit,maintenance,decp,memoire}   outils CLI, jamais importés par src/
tests/         hors ligne, python tests/test_<module>.py ; fixtures dans tests/fixtures/
presets/       14 presets, socle profil, taxonomie
docs/          doc ; le rapport docs/architecture_actuelle_2026-11_* fait foi
archive/       mis de côté, hors git ; jamais supprimé sans validation
data/, logs/   hors git ; data/dce = 124 Go sur un 2e disque, jamais sauvegardé
```
Tant que 0b n'est pas fait, les modules sont à la racine : voir la table de correspondance dans `docs/ARCHITECTURE.md`.

## Interdits
- Lancer `Tendia.bat` : il déclenche téléchargements et appels LLM payants. Pour vérifier l'app : `python tendia_ui.py`.
- Appel LLM sans plafond (`--max-cost` ou `data/budget.json`) et sans journalisation dans `llm_appels`.
- `stockage.sauver(collection)` pour une écriture unitaire (réécrit toute la collection, 58 Mo sur `marches`). Utiliser `stockage.ecrire`.
- `sqlite3.connect` dans le code métier : tout passe par `stockage`.
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
- Avant de terminer : tous les tests passent, l'UI démarre, puis sous-agent `audit-code`.

## Pièges connus
- `stockage.charger` lit toute la collection ; cache mémoire par processus (UI et scripts peuvent diverger).
- Lecture DCE prod : `.pdf/.docx/.xlsx` au 1er niveau seulement, troncature 400 000 caractères. Le code exhaustif est dans `exp_gemini/pieces.py` et `mode_document.py`.
- `tendia_classification` n'est pas dans le pipeline ; la chaîne LLM est arrêtée depuis le 22/06/2026.
- `place_downloader.py` est un doublon d'`atexo_downloader.py` encore importé par `tendia_pipeline`.
- Dépendances non listées : `beautifulsoup4`, `python-dotenv` ; `curl_cffi` absent (repli `requests`).
- Tests cassés connus : `test_dematis_workflow_har.py` (fixture déplacée), `test_grille_notation.py` (n'est pas un test).
- Branche de travail : `feat/decp-sprint-3` jusqu'à la création de `main` (0b). `origin/HEAD` est périmé.

## Commandes utiles
```
python tendia_ui.py                       UI sur 127.0.0.1:5000
python tendia_pipeline.py --skip-llm      pipeline sans appels payants
python tests/test_<module>.py             un test
python scripts/audit/stats_pipeline_dce.py   état du pipeline DCE
python -m decp.cli audit                  état DECP
```
