# Tendia

Veille et analyse intelligente des marchés publics français. Tendia ingère les
avis de marché (BOAMP, TED), télécharge et lit les dossiers de consultation (DCE),
en extrait des **briefs** structurés via LLM, puis **matche** chaque marché contre
le profil d'un organisme pour produire un verdict de pertinence et une fiche d'aide
à la décision.

> Projet solo, en préparation de commercialisation (SaaS multi-tenant visé).
> Code et docs en français.

## En deux phrases

1. **Pipeline data** : BOAMP/TED → classification sectorielle (LLM) → recherche de
   l'URL du DCE → téléchargement anonyme du DCE → extraction LLM d'un brief riche.
2. **Pipeline décision** : brief × profil organisme → score + verdict
   (`très pertinent` / `pertinent` / `à vérifier` / `non pertinent`) + éligibilité,
   exposés dans une UI Flask (dashboard, explorer, fiche marché).

## Prérequis

- **Python 3.12**
- **SQLite** (intégré à Python — base `data/tendia.db`)
- Une clé **Anthropic** (extraction LLM) et une clé **2captcha** (téléchargement
  DCE anonyme sur plateformes à captcha).
- Optionnel : un **proxy résidentiel** (IPRoyal) pour l'anti-ban des downloaders.

## Démarrage rapide

```bash
# 1. Dépendances
pip install -r requirements.txt

# 2. Configuration (copier le modèle et remplir les clés)
cp .env.example .env
#   → ANTHROPIC_API_KEY, TWOCAPTCHA_API_KEY, TENDIA_PROXY_URL

# 3. Lancer l'interface web
python tendia_ui.py
#   → http://localhost:5000
```

La base `data/tendia.db` (SQLite, ~80 Mo) contient déjà les marchés ingérés, les
classifications, les briefs et les profils. Les fichiers `data/` et `.env` sont
gitignorés.

## Documentation

| Doc | Contenu |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Vue d'ensemble, pipeline, modules, base de données |
| [docs/pipeline.md](docs/pipeline.md) | Le pipeline étape par étape (BOAMP → brief) |
| [docs/data_model.md](docs/data_model.md) | Schéma des collections SQLite |
| [docs/modules/](docs/modules/) | Doc par module critique (stockage, preset, llm_extract, …) |
| [docs/operations.md](docs/operations.md) | Manuel d'opération (batchs, monitoring, backup) |
| [docs/cli_scripts.md](docs/cli_scripts.md) | Inventaire des scripts CLI |
| [docs/cost.md](docs/cost.md) | Économique LLM & proxy |
| [docs/extending.md](docs/extending.md) | Ajouter une plateforme / un preset / un champ |
| [docs/conventions.md](docs/conventions.md) | Conventions de code |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Erreurs connues et résolutions |
| [docs/passation_claude.md](docs/passation_claude.md) | Briefing de reprise (état du projet, sprints) |
| [dette_technique.md](dette_technique.md) | Inventaire de la dette technique |

## Structure du dépôt (haut niveau)

```
tendia_ui.py            Application web Flask (dashboard, explorer, fiche marché)
stockage.py             Couche de persistance (collections KV sur SQLite)
preset.py               Presets sectoriels (vocabulaire LLM, mapping domaines, schémas)
dce_finder.py           Résolution de l'URL DCE depuis les champs eForms BOAMP/TED
tendia_extraire.py      Orchestration extraction DCE → brief complet
llm_extract.py          Appel LLM d'extraction (prompt par preset, filtre anti-hallucination)
matching.py             Évaluation marché × profil → score + verdict
fiche_marche.py         Helpers de présentation de la fiche marché
http_humain.py          Sessions HTTP « humaines » + proxy par plateforme (anti-ban)
*_downloader.py         Téléchargeurs DCE par plateforme (dematis, aws, atexo, achatpublic)
presets/<code>/         Config de chaque preset (_preset.json, _schema.json)
ui/templates/           Templates Jinja
ui/static/              CSS (Tailwind compilé + utilitaires)
data/                   Base SQLite + DCE téléchargés (gitignoré)
docs/                   Documentation
```

## Conventions essentielles

- **UTF-8** partout, `sys.stdout.reconfigure(encoding="utf-8")` en tête des scripts CLI.
- Persistance via `stockage` (jamais d'accès SQLite direct dans le métier).
- Tests hors-ligne : `python tests_<module>.py` (style maison `check()`, pas pytest).
- Cf [docs/conventions.md](docs/conventions.md).
