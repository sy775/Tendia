# Architecture Tendia

Vue d'ensemble du système, du pipeline de données, de la base et des modules.
Doc ancrée sur le code réel (juin 2026).

## 1. Vue d'ensemble

Tendia est un monolithe Python organisé autour de **deux pipelines** partageant
une base SQLite unique (`data/tendia.db`) :

- **Pipeline DATA** (ingestion → brief) : récupère les avis, classe le secteur,
  trouve et télécharge le DCE, en extrait un brief structuré par LLM.
- **Pipeline DÉCISION** (brief → verdict) : évalue chaque marché contre le profil
  d'un organisme et produit un verdict + une fiche d'aide à la décision, exposés
  par une UI Flask.

Aucun framework lourd : Flask (UI), `requests`/`curl_cffi` (HTTP), SQLite via une
couche K/V maison (`stockage.py`), SDK `anthropic` (LLM), `2captcha-python` (captcha).

## 2. Pipeline DATA (BOAMP/TED → brief)

```
┌─────────────┐   connecteurs/boamp.py        ┌──────────────────────┐
│ BOAMP / TED │ ───────────────────────────▶  │ collection: marches  │
│   (API)     │   (tendia_veille.py)          └──────────┬───────────┘
└─────────────┘                                          │
                          tendia_classification.py       │  (LLM Haiku : domaine sectoriel)
                          ───────────────────────────▶   ▼
                                                ┌──────────────────────────┐
                                                │ collection:               │
                                                │ classifications_ia        │  domaines_metier[]
                                                └──────────┬────────────────┘
                          dce_finder.py                     │  (URL DCE depuis eForms)
                          ───────────────────────────────▶  ▼
                                                marche.url_dce + dce_qualite
                                                           │
            *_downloader.py (dematis/aws/atexo/achatpublic)│  (téléchargement anonyme + captcha)
            via http_humain.creer_session_humaine          ▼
                                                data/dce/<id>/  (PDF, ZIP décompressés)
                                                           │
                          tendia_extraire.traiter_marche   │  (pdf_extract → texte combiné)
                          ───────────────────────────────▶ ▼
                          llm_extract.extraire_via_llm      (LLM Sonnet : prompt routé par preset)
                                                           │  + _filtrer_hallucinations
                                                           ▼
                                                ┌──────────────────────────┐
                                                │ collection: briefs_extraits│  brief complet/light
                                                └───────────────────────────┘
```

Étapes détaillées : [pipeline.md](pipeline.md).

## 3. Pipeline DÉCISION (brief → verdict)

```
profil organisme (collection: organisme)              brief (briefs_extraits)
            │                                                   │
            └──────────────┬────────────────────────────────────┘
                           ▼  matching.evaluer(profil, marche, brief)   (À LA VOLÉE, non caché)
                  { score 0-100, verdict, motifs }
                           │
            matching_exigences (alertes_candidat × profil) → verdict_eligibilite
                           │
                           ▼
              tendia_ui.py + fiche_marche.py
              ┌───────────────┬───────────────┬──────────────────┐
              │ Dashboard     │ Explorer      │ Fiche marché     │
              │ (pertinents)  │ (tout classé) │ (détail + verdict)│
              └───────────────┴───────────────┴──────────────────┘
```

Note importante : `scores_matching` (collection) ne contient PAS le verdict ni le
score 0-100. Il sert au **pré-filtrage** par secteur (booléen `matche` par preset).
Le score + verdict sont **recalculés à chaque affichage** via `matching.evaluer`.

## 4. Base de données

Persistance : `stockage.py`, table SQLite **unique** générique :

```sql
CREATE TABLE kv_storage (
  collection   TEXT NOT NULL,   -- ex "marches", "briefs_extraits"
  id           TEXT NOT NULL,   -- ex "BOAMP-26-57070"
  contenu_json TEXT NOT NULL,   -- l'objet sérialisé en JSON
  cree_le, mis_a_jour_le,
  PRIMARY KEY (collection, id)
);
```

- **K/V générique** : n'importe quel nom de collection est accepté (d'où
  `classifications_ia` qui n'est pas listée dans `stockage.COLLECTIONS`).
- **WAL mode** + cache mémoire par collection (lecture concurrente sûre pendant
  les écritures — un batch d'extraction n'empêche pas l'UI de lire).
- API : `charger(coll)→{id:obj}`, `lire(coll,id)`, `ecrire(coll,id,obj)`,
  `sauver(coll,dict)` (remplace tout), `supprimer`, `lister_ids`, `invalider_cache`.

Schéma des collections : [data_model.md](data_model.md).

## 5. Modules (par domaine)

### Pipeline data
| Module | Rôle |
|---|---|
| `connecteurs/boamp.py` | Connecteur API BOAMP (récupération des avis) |
| `tendia_veille.py` | Orchestration de la veille (ingestion marchés) |
| `tendia_classification.py` | Classification sectorielle LLM (Haiku) → `classifications_ia` |
| `dce_finder.py` | Résolution de l'URL DCE depuis les champs eForms |
| `tendia_dce.py` | Pipeline de recherche d'URL DCE + qualification `dce_contenu` |
| `*_downloader.py` | Téléchargeurs DCE par plateforme (cf [modules/downloaders.md](modules/downloaders.md)) |
| `tendia_telecharger_dce.py` | Téléchargeur profond / parseur DCE multi-pièces |
| `pdf_extract.py` | Extraction texte des PDF/docx/xlsx d'un dossier |
| `tendia_extraire.py` | Orchestration extraction DCE → brief complet |
| `llm_extract.py` | Appel LLM d'extraction (prompt routé preset + filtre) |
| `auto_brief.py` | Génération du brief « light » (depuis l'avis seul) |

### Pipeline décision
| Module | Rôle |
|---|---|
| `preset.py` | Presets sectoriels : vocabulaire LLM, mapping domaines→presets, schémas |
| `matching.py` | Évaluation marché × profil → score + verdict |
| `matching_exigences.py` | Évaluation des exigences/alertes → éligibilité |
| `fiche_marche.py` | Helpers de présentation (verdict 90s, richesse, KPI) |
| `organisme.py` | Profil organisme (CRUD, validation, schéma sectoriel) |
| `profil_form.py` / `profil_widgets.py` | Formulaires/widgets d'édition de profil |
| `llm_calibration.py` / `calibrer_briefs.py` | Calibration des montants (comparables DECP) |
| `concurrence.py` / `tendia_decp*.py` | Analyse concurrentielle (DECP, attributaires) |

### Transverse
| Module | Rôle |
|---|---|
| `stockage.py` | Persistance K/V SQLite |
| `http_humain.py` | Sessions HTTP « humaines » + proxy par plateforme |
| `http_client.py` | Backend HTTP (requests, + injection truststore SSL) |
| `http_utils.py` | Helpers API JSON (BOAMP/TED, sans proxy) |
| `budget.py` | Garde-fou budget LLM (kill-switch, comptage) |
| `tendia_logs.py` | Logs JSONL d'événements (downloaders, dce-finder) |
| `tendia_ui.py` | Application web Flask |

## 6. Stratégie proxy par plateforme

Le proxy résidentiel (IPRoyal, via `TENDIA_PROXY_URL`) est **activé par défaut**
pour toutes les sessions `http_humain.creer_session_humaine`, et **désactivable
par plateforme** via `TENDIA_PROXY_FOR_<PLATEFORME>=0` :

- Désactivé (confirmé sans ban) : `place` (marches-publics.gouv.fr), `boamp`, `data_gouv`.
- Activé (ban agressif) : `dematis`, `aws_achat`, `achatpublic`, forks `atexo`.

Les récupérations d'avis BOAMP/TED et la recherche PLACE passent par `http_utils`
(requests simple, **sans proxy**) — elles ne sont donc pas concernées.

## 7. Configuration (variables d'environnement)

| Variable | Rôle |
|---|---|
| `ANTHROPIC_API_KEY` | Clé LLM (extraction briefs, classification, calibration) |
| `TWOCAPTCHA_API_KEY` | Résolution captcha (downloaders DCE anonymes) |
| `TENDIA_PROXY_URL` | URL du proxy résidentiel (anti-ban) |
| `TENDIA_PROXY_FOR_<P>` | `0` pour désactiver le proxy sur la plateforme `<P>` |

Cf [`.env.example`](../.env.example).
