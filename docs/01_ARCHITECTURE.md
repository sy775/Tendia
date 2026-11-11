# Tendia : architecture (état réel au 2026-11-10, après le chantier 0a)

Source : dépôt GitHub `sy775/Tendia`, branche `feat/decp-sprint-3` (313 fichiers suivis), et le rapport `docs/architecture_actuelle_2026-11_partie{1,2,3}.md` (2 nov. 2026, lecture seule, vérifié). Ce document en est la version courte ; pour un détail (schéma exact d'un brief, routes Flask, prompts), ouvrir le rapport.

## 1. Stack

| Élément | Réalité |
|---|---|
| Langage | Python 3.12, Python système (pas de venv actif) |
| Web | Flask 3.1, Jinja2, Tailwind compilé statique, JS inline. Serveur de dev sur `127.0.0.1:5000` |
| Base | SQLite `data/tendia.db` (169 Mo, WAL). Une seule table métier `kv_storage` (clé/valeur JSON) + 3 tables SQL DECP |
| LLM prod | SDK `anthropic` : Sonnet 4.6 (briefs, mémoires, calibration), Haiku 4.5 (classification, DECP). 6 instanciations `Anthropic()` directes, pas d'abstraction |
| LLM exp | `llm_router.py` + `config_llm.yaml` : Claude / Gemini (argon, flash-lite) / Opus 5.5, retries, coûts. **Importé uniquement par l'expérimentation** |
| Captcha / proxy | 2captcha ; proxy résidentiel activable par plateforme (`http_humain.py`) |
| Hébergement | Poste Windows local. Aucune tâche planifiée, aucun serveur distant, aucun mail |
| Dépendances | `requirements.txt` (dont `beautifulsoup4`, `python-dotenv` depuis 0b) ; `curl_cffi` absent (repli `requests` forcé). Paquet `tendia` installé par `pip install -e .` (`pyproject.toml`) |

## 2. Points d'entrée

| Commande | Rôle |
|---|---|
| `Tendia.bat` | Pipeline complet puis UI. **Lance des téléchargements et des appels LLM payants** : ne jamais l'exécuter pour « vérifier que ça marche » |
| `python -m tendia [--skip-llm] [--skip-download] ...` (shim : `python tendia_pipeline.py`) | 7 étapes : récup BOAMP → classification Haiku (plafonnée) → résolution URL DCE → téléchargement anonyme → connecteurs dédiés anti-ban → extraction LLM → rapport |
| `python -m tendia.ui` (shim : `python tendia_ui.py`) | UI Flask, lecture seule côté données sauf cycle/exigences/mémoires |
| `python -m tendia.veille.classification` | Classification Haiku seule (c'est aussi l'étape 2 du pipeline) ; `--max-cout 0` bloque tout appel |
| `python -m tendia.analyse.extraire [--marche ID]` | Brief LLM d'un dossier `data/dce/<id>/` |
| `python -m tendia.prix.decp.cli ingest` | Ingestion DECP data.gouv → tables SQL |
| `python scripts/memoire/generer_memoire.py` | Mémoire technique (aussi depuis l'UI) |
| `python tests/lancer_tous.py` ou `python tests/test_<module>.py` | Tests hors ligne, style maison `check()`, sans pytest |

## 3. Arborescence et correspondance avec la chaîne d'agents

Depuis le chantier 0b, les 44 anciens modules racine (26 500 lignes) sont sous `src/tendia/<agent>/` (table origine → destination : `archive/RAPPORT_0b.md`). Correspondance :

| Dossier cible | Modules actuels | Rôle |
|---|---|---|
| `core/` | `stockage` (66 imports : le cœur), `chemins`, `logs`, `http_client`, `http_utils`, `http_humain`, `budget` | Persistance, HTTP, anti-ban, garde-fou LLM |
| `veille/` | `recup`, `connecteurs/boamp`, `classification`, `preset` | Ingestion BOAMP, classification, presets sectoriels |
| `dce/` | `dce_finder`, `resolution_reference`, `resolution`, `telecharger`, `aws_downloader`, `atexo_downloader`, `dematis_downloader`, `achatpublic_downloader`, `marches_securises_downloader`, `xmarches_downloader` | Trouver et télécharger le DCE |
| `analyse/` | `llm_extract`, `llm_router`, `llm_calibration`, `pdf_extract`, `extraire`, `auto_brief`, `briefs_versioning` ; à venir : `exp_gemini/*` (pieces, mode_document) | Lire le DCE, produire le brief |
| `prix/` | `decp/` (17 modules + `decp_consolidee`), `marches_attribues`, `decp_comparables`, `fourchette_scenarios`, `jointure` | Comparables DECP, estimation |
| `memoire/` | `services/` (digest, extraction contexte, rédaction, assemblage docx, pipeline, régénération), `prompts/` | Mémoire technique |
| `eligibilite/` | `matching`, `matching_exigences`, `organisme`, `pertinence` (ex-`analyse.py`) | Profil entreprise × marché → verdict |
| `ui/` | `app` (2 150 lignes, toutes les routes), `fiche_marche`, `profil_form`, `profil_widgets`, `cycle_marche`, `concurrence`, `veille_concurrence`, `templates/`, `static/` | Flask |
| `dossier/`, `coffre/` | rien | À créer (chantiers 3 et 4) |

Autres dossiers : `presets/` (14 presets, socle profil, taxonomie 64 domaines), `scripts/{audit,maintenance,decp,memoire,_archive}`, `tests/` (25 scripts), `docs/`, `archive/` (hors git sauf README et rapport), `data/` (hors git sauf `exemples/` et `profils_demo/`), `logs/` (hors git).

## 4. Données

### 4.1 `kv_storage` : collections vivantes

| Collection | Clé | Volume | État |
|---|---|---|---|
| `marches` | `BOAMP-26-<idweb>` | 3 039 (jusqu'à 1,1 Mo par objet à cause de `donnees_boamp_brut`) | vivante, ingestion jusqu'au 30/10 |
| `classifications_ia` | `<id_marche>` | 1 037 | figée au 01/07 ; 1 992 marchés d'octobre non classés |
| `briefs_extraits` | `<id_marche>` + suffixes `.bak_avant_*`, `.grille_brute` | 239 vrais briefs + 235 sauvegardes dans la collection | figée au 22/06 |
| `llm_appels` | `<date>-<type>-<hex>` | 1 274 | seule l'extraction y est tracée (429,58 € en juin) |
| `organisme` / `profils_bibliotheque` | `principal`, slugs | 4 / 6 | profil actif + démos (btp, ing, it) |
| `memoires_techniques` / `digests_memoire` | `memoire__<id>__lot_<n>__...` | 8 / 6 | fonctionnel |
| `scores_matching`, `matchings` | | 2 532 / 422 | caches figés depuis juin, `matchings` sans lecteur : mort |

Collections déclarées mais absentes (lues par l'UI, reviennent vides) : `marches_notifies`, `marches_tendia_attribues`, `titulaires`, `briefs_calibres`.

### 4.2 Tables SQL DECP

`decp_marches` (142 735 contrats, 15/06/2025 → 15/06/2026, 99 % avec SIRET titulaire), `decp_classification` (preset par contrat : btp 50 888, hors périmètre 67 323 ; codes `conseil_rd`/`enr` ≠ codes presets), `marche_attribution_link` (vide : le rapprochement BOAMP↔DECP n'a jamais fonctionné, 4 matchs sur 2 792).

### 4.3 Comportements de `stockage.py` à connaître avant d'écrire du code

- `charger(collection)` lit **toute** la collection et la parse en Python ; le filtrage se fait en Python. Pas d'index JSON utilisé.
- Cache mémoire **par processus** : l'UI Flask peut servir des données périmées si un script écrit à côté.
- `ecrire` = last-write-wins sur l'objet entier, sans verrou. `sauver(collection)` = DELETE + réinsertion de toute la collection : encore utilisé sur `marches` (58 Mo) par `tendia.dce.telecharger` et `tendia.ui.cycle_marche`. **À ne plus jamais utiliser pour une écriture unitaire.**
- Aucun versioning : les versions sont des suffixes de clé faits à la main.
- `src/tendia/prix/decp/db.py` code le chemin de la base en dur et crée ses tables lui-même.

### 4.4 Données sur disque

- `data/dce/<id_marche>/` : 1 193 dossiers, 124 Go, jonction vers un 2ᵉ disque. **Jamais sauvegardé.** Lecture prod : `.pdf/.docx/.xlsx` au premier niveau seulement, troncature à 400 000 caractères. Non lus : `.doc` (922 fichiers), `.xls` (296), `.odt`, `.rtf`, scans, ~3 000 sous-dossiers.
- `data/extractions/<id>.json` : copie disque des briefs.
- `data/exp_gemini/` : base d'expérimentation `tendia_exp.db` (copie de prod + 14 collections `exp_*`), isolée par monkeypatch de `sqlite3.connect`.
- Sauvegarde du 2026-11-10 : `D:\Projects\tendia_backup_2026-11-10.zip` (21,5 Go, sans `data/dce`).

## 5. Flux de production actuel

```
BOAMP (API ODS)  →  marches
                 →  [manuel] tendia_classification  →  classifications_ia
                 →  tendia_dce (url_dce, qualité)   →  downloaders par plateforme  →  data/dce/<id>/
                 →  tendia_extraire (pdf_extract → llm_extract Sonnet)  →  briefs_extraits (+ rapports/brief_*.md)
UI : matching.evaluer(profil, brief) calculé à la volée (déterministe, sans LLM) → verdict
UI : services/pipeline_memoire (Sonnet ×2) → memoires_techniques → .docx
```

Le flux est **arrêté à l'étape LLM depuis le 22/06/2026** : aucun brief ni classification depuis.

## 6. Branches git

Historique linéaire sans merge. La branche de travail réelle et poussée est `feat/decp-sprint-3`. `origin/HEAD` pointe encore sur `feat/decp-sprint-1` (191 commits de retard) et `master` est à juin. Depuis le chantier 0b : `main` (créée depuis `feat/decp-sprint-3`) est la branche par défaut sur GitHub ; les branches ne sont plus nommées par sprint (`chantier/<n>-<slug>`).
