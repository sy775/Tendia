# Tendia : architecture actuelle (état au 2 novembre 2026), partie 1/3

> **Objet** : fournir à Claude (web), qui n'a pas accès au repo, l'état **réel et vérifié** du
> code pour cadrer le **« compagnon » de réponse aux AO (BTP, V1)**. Son parcours :
> 1. SIREN → profil pré-rempli (données publiques + historique DECP) ;
> 2. marchés à cibler ;
> 3. questions d'éligibilité et verdict ;
> 4. matrice pièce × porteur × phase × lot ;
> 5. coffre-fort de pièces et relances ;
> 6. préremplissage DC1/DC2/DUME/AE et pack de dépôt ;
> 7. suivi des dossiers et des attributions.
>
> En continu, le profil est alimenté par la discussion, avec source, date et confiance.
> Le §10 (partie 3) fait le bilan **existant / réutilisable / à créer / risques / ordre**
> pour chacun de ces points.
>
> **Méthode** : lecture seule du repo, de `data/tendia.db` (ouverte en `mode=ro`) et de
> `data/exp_gemini/tendia_exp.db`. Aucun appel LLM ni réseau. Les tests ont été lancés sur une
> **copie** du code (`git archive HEAD`) avec les sockets bloqués. Aucun secret ne figure ici :
> seuls les **noms** des variables sont cités. Les exemples sont anonymisés.
>
> **Légende** : **[PROD]** = code exécuté par `Tendia.bat` / `tendia_ui.py` ;
> **[EXP]** = expérimentation (branche `exp/gemini-batiment`, `exp_gemini/`, `data/exp_gemini/`) ;
> **[MORT]** = code non appelé ou obsolète ; **à confirmer** = non vérifiable en lecture seule.

## Sommaire

**Partie 1 (ce fichier)**
1. Vue d'ensemble : arborescence, stack, points d'entrée, branches
2. Base de données : tables SQL, `kv_storage` (interface, collections prod + EXP), relations,
   avis SQL/KV pour les nouvelles entités
3. Pipeline d'acquisition : BOAMP / DECP, plateformes BTP, downloaders (technique et taux),
   extraction du texte
4. Analyse IA : classification, brief (prompt, schéma exact, exemple complet), matching
   (instabilité, profil minimal), client LLM, tool use

**Partie 2** (`architecture_actuelle_2026-11_partie2.md`)

5. Profils entreprise (schémas, exemple complet, données publiques, provenance, champs lus)
6. Mémoires techniques
7. Interface et API (chat, composants réutilisables)

**Partie 3** (`architecture_actuelle_2026-11_partie3.md`)

8. Configuration et exploitation (tests)
- 8bis. Mails, notifications et tâches planifiées
- 8ter. Historique DECP, attributions et suivi des dossiers

9. Dette et ménage (dont les incohérences avec la passation)
10. Points d'accroche : les 7 étapes du compagnon et l'alimentation du profil par la discussion

### Les 17 faits à retenir

1. **Il n'y a qu'une table métier SQL : `kv_storage`**, un clé/valeur JSON générique (la clé
   primaire est le couple `(collection, id)`), plus 3 tables SQL DECP. Tout le reste
   (marchés, briefs, profils, mémoires) est stocké en collections JSON.
2. **Le code en prod est celui de `feat/decp-sprint-3`** (commit `4584427`). La branche courante
   `exp/gemini-batiment` ne lui ajoute qu'**un commit purement additif** (16 fichiers nouveaux,
   aucun fichier de prod modifié). La branche `feat/decp-sprint-1`, déclarée « main », a
   **191 commits de retard**.
3. **Le brief LLM ne contient ni « visite », ni « groupement / cotraitance », ni
   « sous-traitance » structurés.** Il contient en revanche une liste `dossier_candidature.pieces_a_fournir`
   (libellé, phase, obligatoire, source), remplie sur 209 des 239 briefs (2 440 pièces au total).
   Rien n'est ventilé par lot ni par porteur. Seule l'EXP ajoute `complements_dce.visite`.
4. **L'extraction de texte en prod ne lit que `.pdf`, `.docx` et `.xlsx` au premier niveau du
   dossier DCE**, avec une troncature à 400 000 caractères. Les `.doc` (922 fichiers), `.xls`
   (296), `.odt`, `.rtf` et les scans ne sont pas lus, ni le contenu des ~3 000 sous-dossiers. Sur un
   DCE mesuré en EXP, **49 % du texte n'était pas lu** par le mode prod.
5. **Aucun brief ni aucune classification n'a été produit depuis le 22 juin 2026** : il n'y a
   aucune entrée `llm_appels` après cette date. Les 1 992 marchés ingérés le 30 octobre n'ont ni
   classification ni brief. La cause est à confirmer (pipeline lancé sans l'étape LLM ?).
6. **Le profil entreprise est un document JSON** (socle + `profils_sectoriels[preset]`), dans
   les collections `organisme` (profil actif `principal`) et `profils_bibliotheque`.
   **Aucun document (Kbis, attestations…) n'est rattaché ni stocké.** Il existe un embryon de
   « réponses types » : `auto_reponses_exigences` (clé → « oui »/« non »/texte).
7. **Il n'y a ni authentification, ni multi-tenant, ni upload de fichiers**, à l'exception de
   l'import d'un profil JSON. L'UI est un Flask local sur `127.0.0.1:5000`.
8. **Les mémoires techniques sont fonctionnelles** : 2 appels Sonnet 4.6 (plan, puis rédaction
   parallèle par section) et un `.docx`. Elles détectent un cadre de réponse acheteur `.docx`.
   8 mémoires et 6 digests sont en base.
9. **Le client LLM de prod n'est pas abstrait** : on trouve 6 instanciations `Anthropic()`
   directes. `llm_router.py` (Claude/Gemini, retries, timeouts, coûts) est **[EXP] uniquement**.
10. **Coût LLM tracé** : 429,58 € journalisés dans `llm_appels` (extraction seulement, juin 2026).
    `_meta.cout_eur` est présent sur les briefs (98,26 € pour les 239 briefs actuels), les
    classifications (6,33 €) et les digests (2,51 €). Pour les mémoires, il est stocké sous
    `_meta.cout_total_eur`.
11. **Le matching (`matching.evaluer`) est déterministe, sans LLM, et calculé à la volée** par
    l'UI. Les collections `matchings` et `scores_matching` sont des caches figés depuis juin.
12. **Tests** : 23 scripts (sans pytest). 19 passent, 3 échouent (dépendance `bs4` absente,
    import cassé par le refactor, 1 attente périmée) et 1 se bloque (`test_aws_downloader`).
13. **Aucune intégration de données publiques entreprise en prod** (Sirene, RGE ADEME, INPI) :
    il n'existe qu'un script archivé `enrichissement_sirene.py` (recherche-entreprises, nom
    seulement). Aucun champ du profil n'a de **source, de date ni de niveau de confiance**.
    Aucun mécanisme n'extrait d'information structurée d'un texte libre vers le profil.
14. **Historique DECP par SIREN : faisable dès aujourd'hui.** Une requête par plage sur
    `titulaire_siret` est indexée (0,1 ms). Inclure les groupements (`titulaires_json`) impose un
    scan complet (~33 ms). La fenêtre DECP couvre le 15/06/2025 → 15/06/2026 ; 16 226 SIREN
    titulaires BTP distincts.
15. **Aucun mail, aucune notification, aucune tâche planifiée, aucun chat, aucun tool use** :
    rien n'existe dans le code.
16. **Le rapprochement BOAMP↔DECP est quasi nul** (4 « matchs probables » sur 2 792 avis, 0 en
    travaux) : les fenêtres temporelles ne se recouvrent pas. `marche_attribution_link` est
    vide et `data/jointure.json` contient 391 entrées sans aucune entrée DECP. Les 247 avis
    d'attribution BOAMP ingérés ne sont pas exploités (le nom du titulaire n'est renseigné que
    sur 30 d'entre eux).
17. **L'instabilité du score (57/39/32 sur BOAMP-26-56456) vient du brief, pas du moteur** :
    `matching.evaluer` est déterministe, mais il lit des champs extraits par le LLM (montant,
    RGE, `synthese_marche`) qui varient d'un modèle à l'autre (§4.3).

---

## 1. Vue d'ensemble

### 1.1 Arborescence commentée (2 à 3 niveaux)

```
D:\projects\tendia\
├── Tendia.bat                 [PROD] lanceur : pipeline puis UI Flask
├── tendia_pipeline.py         [PROD] orchestrateur (sous-processus, 6 étapes)
├── tendia_recup.py            [PROD] ingestion BOAMP (connecteurs/)
├── tendia_dce.py              [PROD] résolution url_dce + qualifier_dce (dce_contenu) + rapport
├── tendia_telecharger_dce.py  [PROD] orchestration des downloaders (Parseur*), ZIP global
├── tendia_extraire.py         [PROD] dézip + extraction texte + appel LLM brief + rendu .md
├── tendia_classification.py   [PROD, CLI manuel] classification Haiku (hors pipeline !)
├── tendia_ui.py               [PROD] Flask (2 154 l.), toutes les routes
├── tendia_logs.py             [PROD] logs JSONL logs/<downloader>_<date>.jsonl
├── stockage.py                [PROD] couche de persistance (kv_storage SQLite)
├── llm_extract.py             [PROD] prompt + appel Sonnet du brief (1 525 l.)
├── preset.py                  [PROD] chargement presets/, routage des schémas par preset
├── matching.py                [PROD] score organisme × marché (V2 multi-secteurs, 1 379 l.)
├── matching_exigences.py      [PROD] alertes du brief ↔ profil (couvert / non couvert…)
├── fiche_marche.py            [PROD] helpers purs de la fiche marché
├── organisme.py               [PROD] profils (socle + sectoriels), bibliothèque
├── profil_form.py / profil_widgets.py  [PROD] parsing et widgets des formulaires de profil
├── budget.py                  [PROD] garde-fou LLM + journal llm_appels
├── pdf_extract.py             [PROD] extraction texte .pdf/.docx/.xlsx
├── auto_brief.py              [PROD] « brief light » depuis l'avis seul (Sonnet)
├── llm_calibration.py         [PROD, à la demande] calibration prix (Sonnet)
├── concurrence.py, veille_concurrence.py, marches_attribues.py, decp_comparables.py,
│   fourchette_scenarios.py, cycle_marche.py   [PROD] modules de la fiche / de la veille
├── jointure.py                [PROD?] index BOAMP↔DECP par référence → data/jointure.json
├── http_client.py, http_humain.py, http_utils.py   [PROD] HTTP (curl_cffi→requests), anti-ban, proxy
├── *_downloader.py            [PROD] atexo, achatpublic, aws, dematis, marches_securises,
│                               xmarches, place (place_downloader = ancienne version Apptia)
├── dce_finder.py, resolution_reference.py  [PROD] résolution des URL DCE
├── analyse.py                 [PROD?] matching multi-preset + scores_matching (seul import actuel : batch_gemini)
├── pipeline_france_travail.py, test_grille_notation.py  [MORT/proto] (cf. §9)
├── llm_router.py, config_llm.yaml, batch_gemini_batiment.py, compare_models.py  [EXP]
├── exp_gemini/                [EXP] isolation, pieces, mode_document, analyse, couts, dce, ui_exp
├── connecteurs/               [PROD] boamp.py (API ODS DILA), decp_consolidee.py (data.gouv)
├── decp/                      [PROD, CLI] ingestion DECP → tables SQL (db, parser, classifier_*, matching)
├── services/                  [PROD] mémoire technique (digest, extraction contexte, rédaction, docx)
├── prompts/                   [PROD] prompts versionnés des mémoires (digest/extraction/rédaction v1)
├── presets/                   [PROD] 14 presets sectoriels + socle profil + taxonomie (64 domaines)
│   ├── _socle_profil_organisme.json   schéma JSON du profil (socle)
│   ├── _taxonomie_domaines.json       64 domaines métier
│   ├── _actif.json                    preset « actif » legacy (= formation)
│   └── <code>/_preset.json (+ _schema.json pour btp, ingenierie, energie_renouvelable, formation)
├── ui/templates/              [PROD] Jinja (base, dashboard, explorer, marche, profil/*, decp…)
├── ui/static/                 tailwind.css, apptia-utilities.css
├── scripts/
│   ├── maintenance/           re-téléchargements, ré-extractions, backfills, init_profil
│   ├── audit/                 bilans, monitoring, audits, mesures [EXP : mesurer_taille_dce, selectionner_validation_argon]
│   ├── decp/                  classification / validation DECP
│   ├── memoire/               CLI mémoires (generer_memoire, generer_digest_memoire, regenerer_section)
│   └── _archive/              [MORT] anciens scripts (enrichir_complet, tendia_matcher, tendia_veille…)
├── tests/                     23 scripts de test (sans pytest)
├── docs/                      doc (passation, architecture, pipeline, data_model, modules/…)
├── rapports/                  briefs .md générés + rapports marches_actifs_<date>.md (244 fichiers)
├── data/                      (en grande partie gitignoré)
│   ├── tendia.db (+ -wal/-shm)    base SQLite 169 Mo, mode WAL
│   ├── tendia.db.backup_* / .bak_*   ~20 sauvegardes manuelles (juin)
│   ├── dce/ → jonction Windows vers un 2ᵉ disque : 1 193 dossiers <id_marche>/
│   ├── extractions/<id>.json      copie disque des briefs (231 fichiers)
│   ├── extractions_calibrees/     calibrations prix (lues via llm_calibration)
│   ├── memoires/<id>/*.docx       mémoires générées (4 marchés)
│   ├── exemples/, profils_demo/   profils démo JSON
│   ├── jointure.json              index BOAMP↔DECP (modifié, non commité)
│   ├── budget.json                limites LLM
│   └── exp_gemini/                [EXP] tendia_exp.db, dce/, pieces/, logs/, rapports
├── logs/                      JSONL des downloaders et logs de batchs (gitignoré)
├── HAR/                       captures HAR, vidéos et une COPIE de 11 tests (gitignoré)
├── backups/, dematis exemple/, Tendia_Prez_Prospect_BTP_2026.pptx, venv/ (vide, non utilisé)
└── dette_technique.md, README.md, requirements.txt, .env (secrets), .env.example
```

### 1.2 Stack

| Élément | Réalité |
|---|---|
| Langage | **Python 3.12.10** (Python système, pas de venv : `venv/` ne contient que pip) |
| Web | **Flask 3.1.3** (Werkzeug 3.1.9, Jinja2 3.1.6), serveur de dev `app.run(127.0.0.1:5000, threaded=True)` |
| UI | Templates Jinja + Tailwind (CSS compilé statique) + JS inline (polling AJAX des mémoires) |
| Base de données | **SQLite** `data/tendia.db` (WAL, `synchronous=NORMAL`, `foreign_keys=ON`), 169 Mo |
| Ordonnanceur | **Aucun.** Pas de tâche planifiée Windows trouvée (`schtasks` ne contient aucune entrée tendia/python). `docs/cron_windows.md` décrit une procédure qui n'est pas en place. Lancement manuel (`Tendia.bat` ou scripts). |
| Hébergement | **Poste local Windows 11** (`D:\projects\tendia`), DCE sur un 2ᵉ disque via une jonction. Pas de serveur distant. |
| LLM prod | SDK `anthropic` 2.3.0 : **Sonnet 4.6** (briefs, mémoires, calibration, brief light), **Haiku 4.5** (classification, DECP) |
| LLM exp | `google-genai` 2.34.0 (Gemini « argon », flash-lite) + Opus 5.5, via `llm_router.py` |
| Captcha | `2captcha-python` 2.1.2 |
| Proxy | proxy résidentiel (`TENDIA_PROXY_URL`), activable par plateforme |

**Dépendances (`requirements.txt`, contraintes `>=`), avec la version installée :**

| Paquet | Contrainte | Installé | Remarque |
|---|---|---|---|
| requests | >=2.31.0 | 2.34.2 | |
| truststore | >=0.9 | 0.10.5 | indispensable au SSL sur ce poste |
| 2captcha-python | >=1.2.0 | 2.1.2 | |
| flask | >=3.0.0 | 3.1.3 | |
| pypdf | >=4.0.0 | 6.21.4 | |
| python-docx | >=1.0.0 | 1.2.0 | |
| openpyxl | >=3.1.0 | 3.1.5 | |
| py7zr | >=0.20.0 | 1.1.4 | |
| anthropic | >=0.18.0 | 2.3.0 | |
| google-genai | >=1.0.0 | 2.34.0 | [EXP] |
| pyyaml | >=6.0 | 6.0.3 | [EXP] |
| **curl_cffi** | (absent) | **non installé** | `http_client.py` retombe sur `requests` (empreinte TLS non imitée) |
| **beautifulsoup4** | (absent) | **non installé** | importé par `tendia_telecharger_dce.py:854` → la branche générique plante si elle est appelée |
| **python-dotenv** | (absent) | **non installé** | `aws_downloader`/`dematis_downloader` ont un import optionnel → la clé 2captcha doit être dans l'environnement ou être lue autrement (à confirmer) |
| rarfile | optionnel | non installé | `.rar` ignorés |

### 1.3 Points d'entrée

| Point d'entrée | Commande | Rôle |
|---|---|---|
| Lanceur complet | `Tendia.bat` | `python tendia_pipeline.py` puis ouverture du navigateur puis `python tendia_ui.py` |
| Pipeline | `python tendia_pipeline.py [--skip-recup] [--skip-download] [--skip-dedies] [--max-dedies N] [--ignorer-heures] [--skip-llm] [--force] [--jours N]` | 1. `tendia_recup.py --large --differentiel` · 2. `tendia_dce.py --jours N` · 3. DL anonyme (in-process) · 4. `scripts/maintenance/retelecharger_{aws_achat_anti_ban,dematis_anti_ban,xmarches,marches_securises}.py` · 5. `tendia_extraire.py` (LLM) · 6. `tendia_dce.py --rapport-seul` |
| UI | `python tendia_ui.py` | Flask `127.0.0.1:5000` |
| UI expérimentale | `python -m exp_gemini.ui_exp [--variante argon_document] [--port 5001]` | [EXP] même UI sur la base copie (**fichier non suivi par git**) |
| Classification | `python tendia_classification.py [--backfill] [--force] [--id] [--limite] [--dry-run] [--modele haiku\|sonnet]` | **Pas appelée par le pipeline** |
| Extraction LLM seule | `python tendia_extraire.py [--marche ID] [--force] [--dry-run]` | brief des dossiers `data/dce/<id>/` |
| Ré-extraction | `python scripts/maintenance/reextraire_briefs_complet.py --oui [--limite N]`, `reextraire_briefs_v2.py`, `tendia_reextraire_batch.py` | |
| DECP | `python -m decp.cli ingest [--depuis YYYY-MM-DD] [--dry-run] [--limite]`, `ingest-annee`, `audit` | ingestion data.gouv vers les tables SQL |
| Mémoire | `python scripts/memoire/generer_memoire.py`, `generer_digest_memoire.py --id-marche X --numero-lot N [--dry-run] [--max-cout]`, `regenerer_section.py` | (UI : bouton par lot) |
| Profil | `python scripts/maintenance/init_profil.py --status \| --template <preset> \| --depuis <json> \| --purger --confirmer` ; `ingester_profil_tee27.py` (profil réel actif) | |
| Monitoring | `python scripts/audit/tendia_monitoring.py`, `stats_pipeline_dce.py`, `bilan_briefs.py` | |
| Expérimentation | `python batch_gemini_batiment.py [--since] [--limit] [--mode-analyse document] [--max-cost]`, `python compare_models.py` | [EXP] |
| Tâches planifiées | **aucune** | |

### 1.4 Branches git

**Branche courante** : `exp/gemini-batiment` (HEAD `3ba9a4b`, 2026-10-31).

| Branche | Dernier commit | Position |
|---|---|---|
| `exp/gemini-batiment` | `3ba9a4b` 2026-10-31 feat(exp) : Gemini (Argon) vs Claude | = `feat/decp-sprint-3` + 1 commit |
| `feat/decp-sprint-3` | `4584427` 2026-10-30 docs : aligner la doc… | **branche de travail réelle** ; `origin/feat/decp-sprint-3` est à `2914a81` (3 commits non poussés) |
| `feat/decp-sprint-2-raffinement-v2` | `73dad77` 2026-06-16 | ancêtre |
| `feat/decp-sprint-2-raffinement` | `224c99d` 2026-06-16 | ancêtre |
| `feat/decp-sprint-2` | `652a2bc` 2026-06-16 | ancêtre |
| `feat/decp-sprint-1` | `c6add13` 2026-06-16 | **déclarée branche principale** (`origin/HEAD`), **191 commits de retard** |
| `master` | `1ee9412` 2026-06-15 | 192 commits de retard |

L'historique est **linéaire** (aucun merge) : chaque branche est un ancêtre de la suivante.

#### Quelle branche tourne réellement ?

**La prod est le contenu de `feat/decp-sprint-3` (4584427).** Éléments :
1. `git rev-list --left-right --count feat/decp-sprint-3...exp/gemini-batiment` donne `0 1` :
   exp n'a qu'un commit de plus.
2. Ce commit (`3ba9a4b`) **n'ajoute que des fichiers** (16 fichiers, +3 916 lignes, 0 suppression).
   Les seuls fichiers existants touchés sont `.env.example`, `.gitignore` et `requirements.txt`
   (ajouts). Aucun module importé par `tendia_ui.py` ou `tendia_pipeline.py` n'est modifié.
3. `grep` confirme que `llm_router` et `config_llm` ne sont importés **que** par `batch_gemini_batiment.py`,
   `compare_models.py`, `exp_gemini/*` et 2 scripts d'audit.
4. Le reflog montre que le travail courant (refactor, doc, `Tendia.bat`) a été fait sur
   `feat/decp-sprint-3` avant le checkout vers `exp/gemini-batiment`.
5. Comme `Tendia.bat` lance les fichiers du working tree, le code exécuté aujourd'hui est
   celui de la branche courante, qui est fonctionnellement identique à `feat/decp-sprint-3`.

⚠️ `feat/decp-sprint-1` (« main » dans la config) **ne reflète pas** la prod : il lui manque
les connecteurs xmarches/marches-securises, les mémoires, les services, l'extraction v2/v3,
le refactor de l'arborescence, etc. (`git diff --stat` : 1 361 fichiers).

#### Modifications non commitées (exp/gemini-batiment)

```
 M data/jointure.json        926 lignes modifiées (+544 / −382) : resynchronisation BOAMP↔DECP
?? .claude/                  (dossier de config Claude Code local)
?? exp_gemini/ui_exp.py      [EXP] lanceur UI sur la base d'expérimentation (port 5001)
?? docs/architecture_actuelle_2026-11_partie{1,2,3}.md   (ce rapport)
```
`git diff --stat` : `data/jointure.json | 926 ++++++++++-------- (544 insertions, 382 suppressions)`.
Aucune autre modification de fichier suivi.

#### Diff exp/gemini-batiment vs prod (feat/decp-sprint-3)

| Fichier | Nature |
|---|---|
| `llm_router.py` (+535) | client multi-fournisseurs `call_llm(task, prompt, documents, model)` : Claude/Gemini, retries + backoff, rate limit, timeout, PDF natifs, relance si `MAX_TOKENS` Gemini |
| `config_llm.yaml` (+83) | modèles par défaut, tarifs, rate limits, retries, timeouts par tâche, paramètres du mode document |
| `exp_gemini/isolation.py` (+135) | copie de la base de prod → `tendia_exp.db`, monkeypatch de `sqlite3.connect` (écriture sur la prod **interdite**), redirection de DCE/logs |
| `exp_gemini/pieces.py` (+443) | inventaire complet des pièces : récursif, ZIP imbriqués, conversion `.doc/.odt/.rtf/.xls/.ods` via Word COM ou LibreOffice, texte page par page `[[Page N]]`, scans en lecture visuelle (PDF natif), typage RC/CCAP/CCTP/BPU/AE/annexe |
| `exp_gemini/mode_document.py` (+436) | modes « global sans troncature » et « document » (questions par type de pièce, fusion dans le schéma prod, contrôle de complétude, `_sources`, `complements_dce`) |
| `exp_gemini/analyse.py` (+290), `couts.py` (+100), `dce.py` (+186) | variantes d'analyse, mesure 2captcha/proxy, récupération DCE via les fonctions prod |
| `batch_gemini_batiment.py` (+535) | sélection BTP, classification Haiku + Flash-Lite, variantes, `--max-cost`, reprise |
| `compare_models.py` (+760) | rapport Excel de comparaison champ par champ, « vérité terrain » sur 6 champs critiques |
| `scripts/audit/mesurer_taille_dce.py` (+237), `selectionner_validation_argon.py` (+159) | mesures |
| `requirements.txt` (+4), `.env.example` (+5), `.gitignore` (+3) | `google-genai`, `pyyaml`, variables `GEMINI_*`, ignorer `data/exp_gemini/` |

#### 15 derniers commits

```
3ba9a4b feat(exp): expérimentation Gemini (Argon) vs Claude sur les DCE du bâtiment
4584427 docs: aligner la doc sur la nouvelle arborescence + réparer Tendia.bat
997f191 refactor: ranger la racine — tests/ et scripts/{maintenance,audit,decp,memoire,_archive}
b561d86 chore: supprimer 21 scripts obsolètes (one-shot terminés, diagnostics, doublons)
51adb18 chore: sortir venv/ de git (ne contenait que pip, Python système utilisé)
2914a81 feat: travaux memoire technique sprint A et B + maj jointure   (ne touche en fait que data/jointure.json)
66c4ebe Tendia V3                                                    (rapports + jointure.json seulement)
5a2f78f doc : coverage DCE réel + fixes 2026-07 (PRADO/ban/resolver) + stockage D:
f1f8a05 tendia_dce : ne pas écraser une url_dce existante par None à la re-résolution
c6ff445 recup : flag --differentiel (borne à la dernière date en base) + pipeline l'utilise
38e1e90 pipeline : ingestion large par défaut (retire le filtre France Travail)
a4a60b7 dematis : détecter « Accès non autorisé » au niveau fichier → rotation IP
452224f aws_downloader : rotation IP sur CDN vide (symptôme de ban)
92aad6f achatpublic : resolver url_dce par référence (recherche → PCSLID)
180bfc7 atexo_downloader : POST 1 PRADO_POSTBACK_TARGET (même fix que place_downloader)
```

Note : le code des services mémoire, de `matching_exigences` et des presets récents a été commité en
bloc le 2026-06-28 (`07ff129 code : sprint en cours — pipeline France Travail, presets, services,
prompts…`).

---

## 2. Base de données

### 2.1 Vue d'ensemble

`data/tendia.db` : SQLite, `journal_mode=WAL`, page de 4 096 octets, 43 157 pages (~169 Mo).

| Table | Lignes | Rôle |
|---|---:|---|
| `kv_storage` | **8 802** | **tout le métier** (10 collections JSON) |
| `decp_marches` | 142 735 | contrats DECP notifiés (12 mois, data.gouv) |
| `decp_classification` | 142 735 | preset par contrat DECP (CPV ou LLM Haiku) |
| `marche_attribution_link` | **0** | lien marché BOAMP ↔ contrat DECP (créée, jamais remplie) |
| `sqlite_sequence` | 0 | interne (AUTOINCREMENT) |

**Base EXP** `data/exp_gemini/tendia_exp.db` : copie de la prod faite le 2026-10-31 (mêmes
tables), `kv_storage` = 9 086 lignes (14 collections `exp_*` en plus, cf. §2.4).

### 2.2 Tables SQL : CREATE TABLE exacts, index, volumes, exemples

#### `kv_storage`

```sql
CREATE TABLE kv_storage (
    collection      TEXT NOT NULL,
    id              TEXT NOT NULL,
    contenu_json    TEXT NOT NULL,
    cree_le         TEXT NOT NULL,
    mis_a_jour_le   TEXT NOT NULL,
    PRIMARY KEY (collection, id)
);
CREATE INDEX idx_kv_collection ON kv_storage(collection);
-- + sqlite_autoindex_kv_storage_1 (clé primaire)
```
8 802 lignes. Les exemples par collection sont au §2.3.

#### `decp_marches`

```sql
CREATE TABLE decp_marches (
    id              TEXT PRIMARY KEY,
    source_fichier  TEXT NOT NULL,
    objet           TEXT,
    cpv_principal   TEXT,
    cpv_secondaires TEXT,
    acheteur_siret  TEXT,
    acheteur_nom    TEXT,
    titulaire_siret TEXT,
    titulaires_json TEXT,
    montant_eur     REAL,
    date_notification TEXT,
    duree_mois      INTEGER,
    procedure       TEXT,
    lieu_execution_code TEXT,
    departement     TEXT,
    region          TEXT,
    parsed_at       TEXT NOT NULL,
    parse_warnings  TEXT
);
CREATE INDEX idx_decp_acheteur  ON decp_marches(acheteur_siret);
CREATE INDEX idx_decp_cpv       ON decp_marches(cpv_principal);
CREATE INDEX idx_decp_date      ON decp_marches(date_notification);
CREATE INDEX idx_decp_dept      ON decp_marches(departement);
CREATE INDEX idx_decp_montant   ON decp_marches(montant_eur);
CREATE INDEX idx_decp_titulaire ON decp_marches(titulaire_siret);
```
142 735 lignes. `source_fichier` vaut toujours `decp_consolidee_api`. `cpv_secondaires` est
toujours NULL. 366 dates de notification distinctes (12 mois). `parse_warnings` est non nul
sur 253 lignes (`acheteur_siret_invalide` ×230, `montant_aberrant_>1Md` ×19…).
Procédures : MAPA 71 231, AOO 53 384, sans publicité 9 470, AOR 5 235…

Exemple (SIRET masqués) :
```json
{"id": "C2026", "source_fichier": "decp_consolidee_api",
 "objet": "TRAVAUX 2026 DE MISE AUX NORMES DANS LES BATIMENTS COMMUNAUX (ERP ECOLES ET GYMNASE)/ Lot n° 01 : DEMOLITIONS GROS OEUVRE - CARRELAGE - FAIENCE",
 "cpv_principal": "45223220", "cpv_secondaires": null, "acheteur_siret": "<SIRET>",
 "acheteur_nom": "COMMUNE D'ANDEVILLE (MAIRIE)", "titulaire_siret": "<SIRET>", "titulaires_json": null,
 "montant_eur": 35059.92, "date_notification": "2026-06-08", "duree_mois": 4,
 "procedure": "Procédure adaptée", "lieu_execution_code": "60570", "departement": "60", "region": "32",
 "parsed_at": "2026-06-15T23:07:29.787624+00:00", "parse_warnings": null}
```

#### `decp_classification`

```sql
CREATE TABLE decp_classification (
    decp_id         TEXT PRIMARY KEY,
    preset_principal TEXT,
    preset_secondaire TEXT,
    source          TEXT NOT NULL,
    confiance       REAL,
    classified_at   TEXT NOT NULL,
    FOREIGN KEY(decp_id) REFERENCES decp_marches(id)
);
CREATE INDEX idx_classif_preset ON decp_classification(preset_principal);
```
142 735 lignes. `preset_principal` : hors_perimetre 67 323, btp 50 888, ingenierie 12 202,
it 7 139, conseil_rd 2 567, formation 2 311, enr 305. `source` : cpv_prefixe_2 59 178,
cpv_hors_perimetre 58 140, llm 15 113, cpv_exact 9 207… `preset_secondaire` est toujours NULL.
⚠️ Les codes `conseil_rd` et `enr` **diffèrent** des codes de presets (`conseil`, `energie_renouvelable`).

```json
{"decp_id": "C2026", "preset_principal": "btp", "preset_secondaire": null,
 "source": "cpv_prefixe_2", "confiance": 0.75, "classified_at": "2026-06-16T17:09:40.891113+00:00"}
```

#### `marche_attribution_link`

```sql
CREATE TABLE marche_attribution_link (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    marche_tendia_id TEXT NOT NULL,
    decp_id         TEXT NOT NULL,
    score_total     REAL NOT NULL,
    score_cpv       REAL,
    score_acheteur  REAL,
    score_periode   REAL,
    score_montant   REAL,
    statut          TEXT NOT NULL DEFAULT 'auto',
    created_at      TEXT NOT NULL,
    UNIQUE(marche_tendia_id, decp_id)
);
CREATE INDEX idx_link_decp   ON marche_attribution_link(decp_id);
CREATE INDEX idx_link_tendia ON marche_attribution_link(marche_tendia_id);
```
**0 ligne.** Prévue par `decp/matching.py` (Sprint DECP 1) et jamais remplie. Il n'y a pas de FK
déclarée vers `kv_storage` (impossible : la clé de `kv_storage` est composite).

Ces 3 tables sont créées par `decp/db.py`, qui code le chemin de la base en dur. Ce n'est pas
`stockage.py` qui les crée.

### 2.3 `kv_storage` : interface exacte (`stockage.py`, 423 lignes)

#### API publique

```python
charger(collection: str) -> dict                 # {id: objet} : SELECT de TOUTE la collection + json.loads
sauver(collection: str, donnees: dict) -> None   # REMPLACE la collection : BEGIN ; DELETE ; N INSERT ; COMMIT
lire(collection: str, id_objet: str) -> dict|None   # SELECT par PK (ou lecture du cache si la collection y est)
ecrire(collection: str, id_objet: str, objet: dict) -> None
        # INSERT … ON CONFLICT(collection,id) DO UPDATE SET contenu_json, mis_a_jour_le   (upsert)
supprimer(collection: str, id_objet: str) -> bool
lister_ids(collection: str) -> list[str]
invalider_cache(collection: str|None = None) -> None
# Backend
chemin_db() -> str                    # data/tendia.db (relatif à __file__, sans variable d'env)
initialiser_db() -> None              # CREATE TABLE IF NOT EXISTS kv_storage + index
migrer_depuis_json(forcer=False) -> dict   # ancienne migration data/<coll>.json → SQLite
rechercher_json(collection, chemin_json, valeur, operateur="=") -> list[id]
        # SELECT id … WHERE collection=? AND json_extract(contenu_json, ?) <op> ?
        # op ∈ {=, LIKE, >, <, >=, <=, !=}
```

#### Comportement réel

- **Connexion** : une connexion par thread (`threading.local`), en `isolation_level=None`
  (autocommit), avec les PRAGMA `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`,
  `temp_store=MEMORY`. `row_factory=sqlite3.Row`.
- **Filtrage / recherche** : **en pratique, un scan complet en Python.** Le code aval fait
  `stockage.charger("marches")` (3 039 objets, 58 Mo de JSON parsés) puis filtre en Python.
  Le seul index est `idx_kv_collection` (et la PK). `rechercher_json` existe (`json_extract`) mais
  **n'est appelée par aucun module de prod** (grep), et elle ne s'appuie sur aucun index
  d'expression : c'est donc aussi un scan de la collection côté SQLite.
- **Cache mémoire** : `_CACHE_MEMOIRE = {collection: (horodatage, dict)}`, rempli par `charger()`
  et **par processus**. Il est invalidé par `sauver/ecrire/supprimer` du **même** processus.
  Rien ne propage l'invalidation entre processus : l'UI Flask (longue durée) peut servir une
  collection périmée si un script externe écrit dans la base, jusqu'au prochain `ecrire` côté
  UI dans cette collection (risque d'incohérence, à confirmer en usage).
- **Versions** : **aucun versioning** des objets. On ne trouve que `cree_le` / `mis_a_jour_le`
  (et `stockage.lire` ne remonte pas `mis_a_jour_le` : `organisme._timestamps_bibliotheque`
  ouvre une connexion `sqlite3` directe pour le lire). Les « versions » sont gérées
  **à la main dans les clés**, par des suffixes : `briefs_extraits` contient
  `<id>.bak_avant_v9` (214), `.bak_avant_v9grille` (9), `.bak_avant_grille` (6), `.grille_brute` (6),
  et des champs `brief_v1_backup` + `brief_v1_backup_expire_le` (115) sont stockés **dans** le brief.
- **Écritures concurrentes** : WAL autorise N lecteurs et 1 écrivain. Il n'y a **aucun
  `busy_timeout` explicite** (le défaut du module `sqlite3` est de 5 s). Pas de verrou optimiste,
  pas de compare-and-swap : `ecrire` est un **last-write-wins sur l'objet entier**. Un
  read-modify-write concurrent (par exemple l'UI qui modifie `auto_reponses_exigences` pendant
  qu'un script réécrit le profil) **perd silencieusement** une des deux écritures. `sauver()`
  (DELETE + réinsertion de toute la collection) est dangereux en concurrence et il est encore
  utilisé par `tendia_telecharger_dce.py` sur `marches`.
- **Parse** : un JSON corrompu est rendu sous la forme `{"_erreur_parse_json": "<texte brut>"}`.

#### Collections : clé, volume, taille, auteurs (qui écrit / qui lit)

Tailles = longueur de `contenu_json` en caractères.

| Collection | N | Forme de la clé | Taille moy. / max | Créée / dernière MAJ |
|---|---:|---|---|---|
| `marches` | 3 039 | `BOAMP-26-<idweb>` | 19 118 / **1 136 527** | 2026-07-02 … 2026-10-30 |
| `scores_matching` | 2 532 | `<id_marche>__<preset>` (422 × 6) | 494 / 566 | figée au 2026-06-11 |
| `llm_appels` | 1 274 | `<AAAA-MM-JJ>-<type>-<hex8>` | 352 / 467 | 2026-06-10 … 2026-06-22 |
| `classifications_ia` | 1 037 | `<id_marche>` | 888 / 1 581 | réécrite en bloc le 2026-07-01 |
| `briefs_extraits` | 474 | `<id_marche>` (239) + `<id>.bak_avant_v9`, `.bak_avant_v9grille`, `.bak_avant_grille`, `.grille_brute` (235) | 31 252 / 92 986 | 2026-06-11 … 2026-06-22 |
| `matchings` | 422 | `<id_marche>` | 1 755 / 3 243 | figée au 2026-06-20 |
| `memoires_techniques` | 8 | `memoire__<id_marche>__lot_<n>__<id_user>__<AAAAMMJJTHHMMSS>` | 148 979 / 252 141 | 2026-06-21/22 |
| `digests_memoire` | 6 | `digest_memoire__<id_marche>__lot_<n>` | 44 280 / 69 984 | 2026-06-21 |
| `profils_bibliotheque` | 6 | slug (`profil_btp_demo`, `formatix`, …) | 5 130 / 8 134 | 2026-06-12 … 06-20 |
| `organisme` | 4 | `principal` (actif) + `demo_btp`, `demo_ing`, `demo_it` | 3 937 / 8 213 | 2026-06-12 … 06-21 |

Les collections déclarées dans `stockage.COLLECTIONS` mais **absentes** de la base sont
`marches_notifies`, `marches_tendia_attribues`, `titulaires` et `briefs_calibres`. Elles sont
pourtant lues par l'UI (`/concurrence`, `/decp`) et par `llm_calibration` : elles reviennent vides.

**Écrivains et lecteurs (grep `stockage.<fn>("<collection>")` + constantes `COLLECTION*`, hors `_archive`) :**

| Collection | Écrit par | Lu par |
|---|---|---|
| `marches` | `tendia_recup.py` (ingestion, `COLLECTION="marches"`), `cycle_marche.py` (**`sauver`** global), `tendia_dce.py` (url_dce, `dce_*`), `tendia_telecharger_dce.py` (**`sauver`** global), `tendia_ui.py` (re-tenter DCE, cycle), `scripts/maintenance/retelecharger_*` (aws, dematis, xmarches, marches_securises, incomplet, vide_atexo), `retenter_download_dce`, `backfill_enrichissement_boamp` | `tendia_ui.py` (×7), `analyse.py`, `tendia_pipeline.py`, `tendia_classification.py`, `tendia_extraire.py`, `cycle_marche.py`, `matching` (via les appelants), scripts d'audit |
| `classifications_ia` | `tendia_classification.py`, `tendia_extraire.py` (resynchronisation depuis le brief), `reclassifier_affine.py`, [EXP] `batch_gemini_batiment.py` | `llm_extract._resoudre_presets_pour_marche` (routage), `tendia_ui.py`, `analyse.py`, `decp_comparables.py`, audits |
| `briefs_extraits` | `tendia_extraire.traiter_marche`, `analyse.py` (brief light produit par `auto_brief.generer_brief_light`, qui ne persiste pas lui-même), `reextraire_briefs_complet.py`, `reextraire_briefs_v2.py`, `rederiver_criteres_plat.py`, `normaliser_codes_domaines_briefs.py`, `test_grille_notation.py` (proto, écrit les clés `.grille_*`) | `tendia_ui.py`, `tendia_dce.py`, `services/digest_memoire.py`, `services/_memoire_commun.py`, `scripts/memoire/*`, `calibrer_briefs.py`, audits |
| `scores_matching` | `analyse.py` (`COLLECTION_SCORES`) | `calibrer_briefs.py`, `bilan_briefs.py`, `audit_classifications.py` (l'UI ne la lit pas) |
| `matchings` | **aucun écrivain actuel** (héritage de `scripts/_archive/tendia_matcher.py`) | aucun lecteur actuel → **[MORT]** |
| `llm_appels` | `budget.enregistrer_appel` (appelé **uniquement** par `llm_extract.extraire_via_llm`) | `budget.statistiques_*`, `tendia_monitoring.py` |
| `organisme` | `organisme.ecrire_profil / activer_profil / enregistrer_profil_bibliotheque / migrer_bibliotheque_au_demarrage`, `tendia_ui /exigence/repondre` (via `ecrire_profil`), `init_profil.py`, `ingester_profil_tee27.py`, `scripts/memoire/generer_memoire.py` (profils démo) | `organisme.charger_actif/lire_profil`, `matching` (via l'UI), `matching_exigences`, `services/_memoire_commun.charger_profil_organisme`, [EXP] `compare_models.py` |
| `profils_bibliotheque` | `organisme.py` (enregistrer, importer, dupliquer, créer, migrer) | `organisme.lister_profils_bibliotheque/lire_profil_bibliotheque`, UI `/profil*`, [EXP] `compare_models.py` |
| `memoires_techniques` | `services/pipeline_memoire.generer_memoire / reviser_memoire`, `services/regeneration_section.py` | `tendia_ui.py` (statut, téléchargement), `pipeline_memoire.cle_memoire_existante` |
| `digests_memoire` | `services/digest_memoire.generer_digest_memoire_lot` | `services/_memoire_commun.charger_digest` |

#### Structure des valeurs par collection

Clés de premier niveau, avec la fréquence de présence et les types observés.

**`marches`** (avis BOAMP normalisés + état du DCE) : clés communes à 3 039 ou 3 038 objets :
`id, source (toujours "BOAMP"), reference_externe, url_source, url_avis, titre, objet, acheteur_nom,
acheteur_id (toujours null), perimetre_geographique, date_publication, date_limite_depot, cpv_principal,
type_marche, descripteur_code, descripteur_libelle, categorie_metier, famille_boamp, notice_type,
meta_recuperation{date_premiere_recuperation, date_derniere_recuperation, version, source_connecteur},
contact{…}, url_consultation_dce_directe, acheteur_siren, montant_estime_eur, url_profil_acheteur,
acheteur_ville, acheteur_code_postal, acheteur_nuts, nombre_lots (int), lots_json (list|null),
cpv_secondaires, nature, nature_libelle, procedure_libelle, criteres_attribution (list|str|null),
est_europeen, acheteur_adresse, acheteur_pays, dce_consultation_id, annonces_anterieures, annonce_lie,
date_fin_diffusion, duree_marche_mois, etat, type_avis_detail, enrichissement_{version,le,source,
champs_absents}, source_schema_eforms, donnees_boamp_brut (str : JSON brut de l'avis, la cause des
valeurs de 1 Mo)`.
Champs d'état du DCE (partiels) : `url_dce` (1 058), `reference_ft`, `url_recherche_place`,
`dce_qualite` (1 055), `dce_recherche_le`, `dce_contenu` (813), `dce_pieces_contractuelles` (813),
`dce_raison_contenu`, `dce_telecharge_le`, `dce_telechargement_{statut,raison,date,nb_fichiers}` (561),
`dce_pieces_manquantes` (487), `dce_qualifie_le`, `url_dce_source`, `dce_requalifie_le`, `dce_relance_le`.
Champ `cycle` (optionnel, non compté ci-dessus car rare) : suivi de candidature écrit par
`cycle_marche.py` (route `POST /marche/<id>/cycle`). Statuts : `a_evaluer`, `candidate`, `gagne`,
`perdu`, `abandonne`, avec un graphe de transitions et un historique. ⚠️ L'écriture passe par
`stockage.sauver("marches", …)`, c'est-à-dire **la réécriture complète de la collection
`marches` (58 Mo)** à chaque changement de statut. Il n'y a aucun autre suivi de dossier de réponse.

Exemple tronqué (champs `dce_*` coupés) :
```json
{"id": "BOAMP-26-57070", "source": "BOAMP", "reference_externe": "26-57070",
 "url_source": "https://www.boamp.fr/pages/avis/?q=idweb:26-57070",
 "titre": "Rénovation de la production et distribution ECS 1035 - Résidence … - LA GARENNE COLOMBES",
 "acheteur_nom": "Hauts-de-Seine Habitat - OPH", "acheteur_id": null,
 "perimetre_geographique": "Dept 92 | FNSimple", "date_publication": "2026-06-10",
 "date_limite_depot": "2026-07-17", "cpv_principal": null, "type_marche": "TRAVAUX",
 "descripteur_code": "306", "descripteur_libelle": "Réseaux divers", "categorie_metier": "autre",
 "famille_boamp": "Marchés entre 90 k€ et seuils européens", "notice_type": "5 | 1",
 "meta_recuperation": {"date_premiere_recuperation": "2026-06-10T13:07:48Z", "version": 1, "source_connecteur": "BOAMP"},
 "url_dce": "https://hautsdeseine-habitat.e-marchespublics.com/pack/annonce_marche_public_….html",
 "dce_qualite": "directe", "dce_telechargement_statut": "ok", "dce_contenu": "complet", "…": "…"}
```

**`classifications_ia`** : `domaines_metier [{code, poids?, lots_concernes?}]`, `raison_classification`,
`synthese_courte` (1 034), `_meta{modele, date, input_tokens, output_tokens, cout_eur, duree_s}` (1 034),
`marche_id` (1 034), `source` + `mis_a_jour_le` (96, = `"brief_complet"` quand la classification a été resynchronisée depuis le brief).
```json
{"domaines_metier": [{"code": "prestations_speciales_titres_cheques"}],
 "raison_classification": "Le titre mentionne explicitement « chèques d'accompagnement personnalisé » …",
 "synthese_courte": "Marché de fourniture de chèques d'accompagnement personnalisé …",
 "_meta": {"modele": "claude-haiku-4-5", "date": "2026-06-19T02:02:18Z", "input_tokens": 5430,
           "output_tokens": 240, "cout_eur": 0.0061, "duree_s": 2.66},
 "marche_id": "BOAMP-26-56729"}
```

**`briefs_extraits`** : schéma complet au §4.2. Répartition `_meta.type` : `complet` 231,
`light` 8 (brief issu de l'avis seul, `auto_brief.py`). `genere_avec_dce_complet=true` : 211.
`_meta.preset_utilise` : null 96 (anciens briefs ou hors-périmètre), btp 70, ingenierie 30,
conseil 21, formation 11, it 7, sante/proprete/paysager/energie_renouvelable 1 chacun.

**`scores_matching`** : `marche_id, preset_code, matche, mode_decision (classification_ia|keyword_fallback),
score_brut, mots_cles_matches[], cpv_pattern_matche, exclu_par_mot_negatif, matche_keyword, matche_ia,
niveau_ia, domaine_classifie, source_classification, raison, evalue_le`.
```json
{"marche_id": "BOAMP-26-56129", "preset_code": "it", "matche": false, "mode_decision": "classification_ia",
 "score_brut": 0, "mots_cles_matches": [], "cpv_pattern_matche": null, "exclu_par_mot_negatif": null,
 "matche_keyword": false, "matche_ia": false, "niveau_ia": "hors", "domaine_classifie": "autre",
 "source_classification": "brief_complet", "raison": "Domaine 'autre' hors du périmètre du preset",
 "evalue_le": "2026-06-11T22:11:19.465053Z"}
```

**`matchings`** [MORT] : `id_marche, score, verdict, motifs[{critere, satisfait, points, commentaire,
valeur_organisme, valeur_marche}], presets_marche, presets_profil, _version ("v2")`.

**`llm_appels`** : `id, type ("extraction"), marche_id, preset_code (toujours null), cout_eur,
tokens_input, tokens_output, duree_ms, modele, statut (ok|erreur|bloque_budget), erreur,
appele_le, jour, mois`.
```json
{"id": "2026-06-10-extraction-01f172d4", "type": "extraction", "marche_id": "BOAMP-26-56214",
 "preset_code": null, "cout_eur": 0.03, "tokens_input": 2219, "tokens_output": 1658, "duree_ms": 31718,
 "modele": "claude-sonnet-4-6", "statut": "ok", "erreur": null,
 "appele_le": "2026-06-10T13:20:15.459770Z", "jour": "2026-06-10", "mois": "2026-06"}
```

**`memoires_techniques`** : `id_marche, numero_lot, id_user, intitule_lot, timestamp,
template_acheteur (chemin|null), version_prompt_extraction, version_prompt_redaction, genere_le,
plan_redaction{cadre_reponse_impose{detecte, fichier_template, structure_resumee}, posture_redaction,
plan_sections[{section_id, titre, niveau, longueur_cible_pages, objectif, elements_a_couvrir,
criteres_lies, contraintes}], elements_a_reprendre_verbatim[{formulation, source}],
points_attention_specifiques[str]}, sections_redigees{section_id: texte}, chemin_docx,
regenerations[], revisions[] (1/8), _meta{cout_total_eur, cout_appel_1_eur, cout_appel_2_eur,
tokens_entree_appel_1, tokens_sortie_appel_1, tokens_entree_appel_2, tokens_sortie_appel_2, modele,
duree_totale_s, cctp_fichiers[], cctp_mode_filtre, cctp_tronque, sections_manquantes, sections_hors_plan}`.
```json
{"id_marche": "BOAMP-26-51023", "numero_lot": 1, "id_user": "principal",
 "intitule_lot": "MARCHE DE SERVICES D'INSERTION PROFESSIONNELLE …", "timestamp": "20260621T221021",
 "template_acheteur": "data\\dce\\BOAMP-26-51023\\3_Cadre de reponse.docx",
 "version_prompt_extraction": "v1.1", "version_prompt_redaction": "v1.2",
 "genere_le": "2026-06-21T22:10:21Z", "plan_redaction": "<dict 5 clés>", "sections_redigees": "<dict 6 clés>",
 "chemin_docx": "data\\memoires\\BOAMP-26-51023\\principal_lot1_20260621T221021.docx",
 "regenerations": [], "_meta": "<dict 14 clés>"}
```

**`digests_memoire`** : `id_marche, numero_lot, intitule_lot, domaine_lot, version_prompt, genere_le,
digest{synthese_lot, objet_et_perimetre, exigences_techniques_detaillees[{categorie, exigence,
source_cctp, criticite}], livrables_attendus_lot, contraintes_specifiques, moyens_attendus{humains,
materiels, organisationnels}, criteres_publics_adaptes_lot[…], points_attention_redaction,
elements_manquants_dans_DCE}, _meta{cout_eur, tokens_entree, tokens_sortie, modele, duree_s,
cctp_fichiers, cctp_mode_filtre, cctp_tronque}`.

**`organisme` / `profils_bibliotheque`** : décrits en détail au §5 (partie 2).

### 2.4 Collections expérimentales (`tendia_exp.db` uniquement) [EXP]

| Collection | N | Contenu |
|---|---:|---|
| `exp_appels` | 220 | journal par appel `call_llm` : `task, fournisseur, modele, tokens_in/out/reflexion, cout_eur, duree_s, erreur, ok, prompt_version, marche_id, etape, variante, run_id, date` |
| `exp_analyses` | 13 | `<id>:<variante>` : modèle, coût, durée, **couverture** (`chars_lus/chars_total`, `tronque`, `pct_non_lu`, `pieces_non_lues`) |
| `exp_runs` | 9 | paramètres et coûts d'un run du batch |
| `exp_traces_document` | 5 | traces du mode document (analyses par pièce), ~235 Ko chacune |
| `exp_classif_claude` / `exp_classif_gemini` | 4 / 4 | classifications comparées |
| `exp_dce`, `exp_etat` | 4 / 4 | statut de récupération du DCE et avancement par marché |
| `exp_brief_{claude_prod, opus_global, opus_document, argon_global, argon_document}` | 3/2/2/2/3 | briefs par variante (schéma prod + `_sources`, `complements_dce`, `_controle_completude`) |
| `exp_briefs_extraits_avant_ui` | 1 | sauvegarde avant injection pour `ui_exp` |

**Clés, tailles, écrivains et lecteurs (EXP)** : les constantes sont dans `batch_gemini_batiment.py`
(`C_ETAT="exp_etat"`, `C_DCE`, `C_ANALYSES`, `C_TRACES`, `C_APPELS`, `C_RUNS`, `C_CLASSIF`, `c_brief(v)`).

| Collection | Clé | Taille moy. / max | Écrit par | Lu par |
|---|---|---|---|---|
| `exp_appels` | `<mid>:<etape>:<variante>:<hex8>` | 569 / 968 | `batch_gemini_batiment` (callback `journal` de `llm_router.call_llm`) | `compare_models` |
| `exp_analyses` | `<mid>:<variante>` | 945 / 2 363 | `batch_gemini_batiment` | `batch_gemini_batiment` (reprise), `compare_models` |
| `exp_runs` | `<AAAAMMJJ_HHMMSS_pid>` | 588 / 701 | `batch_gemini_batiment` | (consultation) |
| `exp_traces_document` | `<mid>:<variante>` | 234 690 / 338 883 | `batch_gemini_batiment` | `batch_gemini_batiment` (`trace_precedente`) |
| `exp_classif_claude` / `_gemini` | `<mid>` | 935 / 1 089 · 659 / 734 | `batch_gemini_batiment` | `batch_gemini_batiment`, `compare_models` |
| `exp_dce` | `<mid>` | 555 / 673 | `batch_gemini_batiment` | idem |
| `exp_etat` | `<mid>` | 353 / 425 | `batch_gemini_batiment` | idem + `compare_models` |
| `exp_brief_<variante>` | `<mid>` | 40 à 62 k | `batch_gemini_batiment` | `compare_models`, `exp_gemini/ui_exp` |
| `exp_briefs_extraits_avant_ui` | `<mid>` | 36 382 | `exp_gemini/ui_exp` | `exp_gemini/ui_exp` |
| (collections prod copiées) `marches`, `classifications_ia`, `briefs_extraits`, `llm_appels` | — | — | `exp_gemini/dce.py` (marches), `batch_gemini_batiment` (classifications_ia), `ui_exp` (briefs_extraits), `llm_extract` via la variante `claude_prod` (3 entrées `llm_appels` le 31/10) | UI EXP |

`exp_gemini/isolation.activer()` monkeypatche `sqlite3.connect` : une ouverture en écriture de
`data/tendia.db` lève `PermissionError` ou est redirigée vers `tendia_exp.db`. La base de prod
n'est jamais modifiée par l'expérimentation.

Coût cumulé de l'expérimentation (`exp_appels`) : Opus 5.5 en analyse 78 appels / 20,05 € ;
gemini-4-argon en analyse 131 appels / 8,15 € ; Sonnet 4.6 en analyse 3 / 2,15 € ;
classification Haiku 4 / 0,025 €, Flash-Lite 4 / 0,005 €.

### 2.5 Relations entre données (toutes implicites)

```
kv_storage[marches/<id_marche>]  (id = "BOAMP-26-<idweb>")
   ├─ 1:1  kv_storage[classifications_ia/<id_marche>]
   ├─ 1:1  kv_storage[briefs_extraits/<id_marche>]  (+ clés <id>.bak_* = anciennes versions)
   ├─ 1:6  kv_storage[scores_matching/<id_marche>__<preset>]           (cache figé)
   ├─ 1:1  kv_storage[matchings/<id_marche>]                           (mort)
   ├─ 1:N  kv_storage[llm_appels/*]           via contenu.marche_id
   ├─ 1:N  kv_storage[digests_memoire/digest_memoire__<id>__lot_<n>]   (lot = brief.lots[].numero)
   ├─ 1:N  kv_storage[memoires_techniques/memoire__<id>__lot_<n>__<id_user>__<ts>]
   │          └─ id_user = organisme.id du profil actif (« principal », « demo_btp »…)
   ├─ 1:1  disque data/dce/<id_marche>/            (pièces téléchargées)
   ├─ 1:1  disque data/extractions/<id_marche>.json (copie du brief)
   ├─ 1:1  disque rapports/brief_<id_marche>.md
   ├─ 0:N  data/memoires/<id_marche>/*.docx
   ├─ 0:N  table marche_attribution_link.marche_tendia_id  (vide)
   └─ 0:1  data/jointure.json (clé = référence acheteur normalisée ; boamp.id ↔ decp)

decp_marches.id ──1:1── decp_classification.decp_id   (FK déclarée)
decp_marches.id ──0:N── marche_attribution_link.decp_id

kv_storage[organisme/principal]  ← copie de → kv_storage[profils_bibliotheque/<slug>]
   (« invariant lien actif » : organisme/principal.id == slug de la bibliothèque)
```

Aucune contrainte d'intégrité n'existe côté `kv_storage` : supprimer un marché ne supprime ni
son brief, ni sa classification, ni ses mémoires. 231 des 239 briefs ont leur marché en base ;
**8 briefs sont orphelins** (marché absent de `marches`, probablement à cause de la purge de juin, à confirmer).

### 2.6 Avis : nouvelles tables SQL ou nouvelles collections KV ?

**Recommandation globale : des tables SQL relationnelles pour toutes les nouvelles entités
du compagnon, avec des colonnes JSON d'appoint** (JSONB sur Postgres) là où la forme est
variable. Le brief, les digests et les mémoires restent en KV (documents produits par un LLM,
lus en bloc) jusqu'à la migration.

| Entité | Choix | Raison principale |
|---|---|---|
| **Profil entreprise avec provenance champ par champ** | **SQL hybride** : table `entreprises` (identité, SIREN unique, tenant) + table `profil_faits(entreprise_id, chemin, valeur JSON, source, source_ref, date_obs, confiance, statut confirme/propose/rejete, auteur, cree_le)` + **vue ou matérialisation JSON** au format actuel du socle et des sectoriels | Le matching et les mémoires lisent un **document JSON** (§5.8) qu'il faut garder compatible. La provenance (source, date, confiance, confirmation) est par nature une **ligne par fait**, historisable. Le recalcul des verdicts à chaque fait est déclenché par des événements sur la table. En KV, la provenance devrait être dupliquée dans chaque objet (`{valeur, source, date…}` partout), ce qui casse les lecteurs actuels. |
| **Matrice de conformité** | **SQL** (exigences, entités du dossier, cellules) | relationnelle N:N, requêtes transverses, mises à jour atomiques par cellule (voir ci-dessous) |
| **Coffre-fort** | **SQL (métadonnées) + stockage objet (fichiers)** | dates de validité requêtables (« ce qui expire sous 30 jours »), empreinte SHA-256, FK entreprise. Sur Scaleway : Object Storage compatible S3, fichiers hors base |
| **Dossiers de réponse** (déposé, attribué, rejeté, notes, motifs) | **SQL** + table d'historique des transitions | remplace `marches.cycle` (aujourd'hui une réécriture de 58 Mo à chaque changement de statut) ; statistiques post-mortem |
| **Historique de discussion** | **SQL** : `conversations` + `messages(role, contenu, blocs JSONB pour tool_use/tool_result, tokens, coût)` | append-only, paginé, rattaché à une entreprise et à un dossier ; à rejouer pour le LLM ; la rétention/RGPD exige des suppressions ciblées |
| **Actions de l'agent** (mails envoyés, relances, mises à jour de profil proposées ou confirmées, appels d'outils) | **SQL** : `actions_agent` (journal d'audit, statut, idempotence) | traçabilité, re-exécution, et les « cartes de confirmation » sont des actions en attente |
| **Attributions** (DECP, avis d'attribution BOAMP) | **SQL** : `decp_marches` existe déjà ; il faut ajouter une table de titulaires normalisée (`attribution_titulaires(decp_id, siret, siren, rang, role)`) + `marche_attribution_link` | requêtes par SIREN (historique, concurrents, renouvellements) ; `titulaires_json` en texte force aujourd'hui un scan complet |

**Pourquoi pas des collections KV** : `kv_storage` ne fournit ni index secondaire, ni contrainte,
ni écriture partielle ; tout `charger()` désérialise toute la collection (§2.3). Ajouter 7
collections, ce serait 7 entités à éclater lors de la migration Postgres.

**Spécificités Postgres (Scaleway Managed Database for PostgreSQL)** — à confirmer côté offre
et versions disponibles :
- types natifs : `JSONB` (blocs de messages, valeurs de faits), `TIMESTAMPTZ`, `UUID`,
  `GENERATED … AS IDENTITY` ;
- **multi-tenant** : une colonne `entreprise_id`/`tenant_id` partout, éventuellement avec
  Row-Level Security ;
- fichiers du coffre dans Object Storage (S3), avec URL présignées ;
- une couche d'accès commune (connexion injectée, SQL standard) dès SQLite, pour une migration
  mécanique. **Ne pas** reproduire le chemin codé en dur de `decp/db.py`.

Le détail ci-dessous (matrice) reste valable.

#### Détail : la matrice

Arguments :

1. **La forme des données est relationnelle par nature.** Une matrice « exigence × porteur
   (mandataire / cotraitant / sous-traitant) × phase × lot × pièce » est un graphe N:N avec des
   statuts par cellule (exigé, fourni, valide, expiré, à relire). En KV, il faudrait soit un
   gros document par dossier (contention à l'écriture, last-write-wins sur tout le dossier,
   aucune requête transverse), soit une clé par cellule avec des clés composites encodées en
   chaîne (`<marche>__<lot>__<entite>__<exigence>`) : c'est réinventer un index à la main.
2. **Les requêtes nécessaires sont transverses** : « toutes les attestations URSSAF qui expirent
   dans 30 jours, tous dossiers confondus », « quels lots sont encore bloqués par une pièce
   manquante d'un cotraitant », « réutiliser la pièce X déjà validée sur le dossier Y ». Avec
   `kv_storage`, c'est un `charger()` complet plus un filtre Python (déjà 58 Mo pour `marches`).
3. **La concurrence et l'intégrité** comptent pour un relecteur et un agent qui écrivent en
   parallèle. Une table permet des mises à jour atomiques **par cellule** (`UPDATE … WHERE
   id=? AND version=?`), des FK (pièce → entreprise → coffre) et des contraintes `UNIQUE`.
   `kv_storage` n'offre que l'écrasement de l'objet entier.
4. **La migration Postgres prévue** : du SQL classique (tables, FK, index, `TEXT`/`REAL`/`INTEGER`,
   `JSON` en colonne d'appoint) se transpose quasiment tel quel (`JSONB`, `TIMESTAMPTZ`,
   `SERIAL/IDENTITY`). Le KV générique devra de toute façon être éclaté en tables pour profiter
   de Postgres (index, RLS multi-tenant par `entreprise_id`). Créer maintenant des collections
   KV, c'est **ajouter de la dette à migrer**.
5. **Le précédent existe** : les tables `decp_*` sont déjà du SQL relationnel à côté de
   `kv_storage`, avec leur propre module (`decp/db.py`). Le pattern « module + tables
   dédiées » est donc déjà accepté dans le code.

Garde-fous recommandés pour que la migration Postgres soit triviale :
- un module d'accès dédié (par exemple `conformite/db.py`) **sans chemin codé en dur**, qui
  réutilise `stockage.chemin_db()` ou une connexion injectée, contrairement à `decp/db.py`.
  Il faut prévoir une abstraction minimale de connexion (SQLite aujourd'hui, psycopg demain) ;
- des identifiants `TEXT` (UUID) plutôt qu'`AUTOINCREMENT` ; des dates en ISO 8601 UTC ;
  aucun type SQLite exotique ; aucun `json_extract` dans les requêtes métier critiques ;
- une colonne `entreprise_id` (ou `tenant_id`) **dès maintenant** sur toutes les nouvelles
  tables, même en mono-utilisateur ;
- les fichiers (pièces du coffre) **hors base** (disque ou objet), la base ne stockant que les
  métadonnées et l'empreinte SHA-256 ;
- garder le brief en KV, mais **référencer** l'exigence source par un chemin stable
  (`brief_version_sha` + chemin JSON) pour la traçabilité.

---

## 3. Pipeline d'acquisition

### 3.1 Ingestion des avis

| Source | État | Fichiers | Détail |
|---|---|---|---|
| **BOAMP** | [PROD] | `connecteurs/boamp.py`, `tendia_recup.py` | API Opendatasoft DILA (`boamp-datadila.opendatasoft.com/api/explore/v2.1/`), pages de 100. Mode `--large` (sans filtre acheteur) `--differentiel` (borné à la dernière date en base). Dédoublonnage par `id`, sinon `meta_recuperation.version += 1`. Enrichissement eForms (contact, lots, SIREN, NUTS…). |
| **TED** | **inexistant** | — | Annoncé dans `Tendia.bat`, dans la docstring de `tendia_pipeline.py` et dans la passation, mais **il n'existe aucun connecteur TED**. `marches.source` vaut `"BOAMP"` pour les 3 039 marchés. |
| **DECP** | [PROD, CLI manuel] | `connecteurs/decp_consolidee.py` (API tabulaire data.gouv), `decp/{telecharger,parser,db,classifier_cpv,classifier_llm,matching,audit,cli}.py` | Ingestion des 12 derniers mois vers `decp_marches` (142 735) + classification CPV / Haiku → `decp_classification`. Exploité par `decp_comparables.py` (« voie 3 » de calibration du montant, page `/decp`). Pas dans le pipeline. |

**Fréquence** : manuelle (aucune tâche planifiée). Volumes par mois de publication dans
`marches` : 2026-06 708, 2026-07 329, **2026-10 1 992** (ingérés le 30/10), quelques avis
antérieurs. **Trou août–septembre** : aucune ingestion. `notice_type` : `5 | 1` (avis de marché)
2 596, `10 | 6` (attribution) 247, null 178.

### 3.2 Récupération des DCE

**Chaîne** : `tendia_dce.py` (résolution de `url_dce` : lien eForms direct, recherche keyWord
PLACE, `resolution_reference.py` par référence ou objet, `dce_finder.py`), puis
`tendia_telecharger_dce.telecharger_pieces_dce` (parseurs), puis les connecteurs dédiés avec
captcha (scripts `retelecharger_*`), puis `tendia_dce.qualifier_dce` → `dce_contenu`.

**Downloaders par plateforme** (taux = `dce_contenu == "complet"` parmi les marchés de la base
ayant une `url_dce` sur cette plateforme, **mesuré aujourd'hui en base**) :

| Plateforme | Module | Mécanisme | url_dce | complet |
|---|---|---|---:|---:|
| marches-publics.info (AWS-Achat) | `aws_downloader.py` | ColdFusion 7 étapes + 2captcha, rotation IP sur ban | 223 | **95 %** |
| PLACE (marches-publics.gouv.fr) | `atexo_downloader.py` (+ ancien `place_downloader.py`) | Atexo/PRADO 2-POST anonyme | 139 | 92 % |
| achatpublic | `achatpublic_downloader.py` | resolver par référence (PCSLID) + DL | 101 | 86 % |
| e-marchespublics (Dematis) | `dematis_downloader.py` | lien anonyme SHA-1 + captcha + fix cookie/mojibake | 69 | 56 % |
| maximilien / megalis / ternum / demat-ampa | `atexo_downloader.py` (forks Atexo) | idem PLACE | 22/21/14/9 | 85 à 95 % |
| xmarches | `xmarches_downloader.py` | moteur custom + 2captcha | 17 | 88 % |
| autres hôtes (forks Atexo municipaux, etc.) | atexo (signature) ou générique | | 66 | 54 % |
| marches-securises | `marches_securises_downloader.py` | recherche par référence/objet, sous-processus tuable | 2 | 0 % |
| safetender, klekoon… | aucun | | — | — |

Répartition globale `dce_contenu` (3 039 marchés) : **non qualifié 2 226**, complet 649,
vide 92, `rien` 45 (valeur **non documentée** dans la passation), incomplet 26, auth_requise 1.
`dce_qualite` (résolution de l'URL) : null 1 984, directe 588, absente 326, via_keyword 78, racine 63.
→ Les 1 992 marchés d'octobre n'ont, pour la plupart, **pas encore** de DCE résolu ni téléchargé.
La doc (`docs/operations.md`, juillet) annonce ~73 % de DCE complets sur les avis de marché.

#### 3.2.1 Marchés BTP par plateforme acheteur (données réelles)

**Définition BTP retenue** : `marches.type_marche == "TRAVAUX"` (nature BOAMP, disponible sur les
3 039 marchés) **ou** une classification avec un domaine `btp_*`, hors avis d'attribution.
On obtient **912 marchés BTP**. La plateforme est déduite de `url_dce`, ou à défaut de
`url_profil_acheteur`.

Les **545 marchés BTP d'octobre** n'ont jamais été soumis à la résolution d'URL
(`dce_recherche_le` absent). La répartition significative porte donc sur les **367 marchés BTP
dont la résolution a été tentée** :

| Plateforme | Marchés BTP (résolution tentée) | % | « complet » / tentés |
|---|---:|---:|---:|
| (aucune URL résolue) | 112 | 30,5 % | — |
| marches-publics.info (AWS-Achat) | 105 | 28,6 % | 100 / 105 (95 %) |
| marches-publics.gouv.fr (PLACE) | 35 | 9,5 % | 33 / 35 (94 %) |
| achatpublic | 27 | 7,4 % | 24 / 27 (89 %) |
| e-marchespublics (Dematis) | 23 | 6,3 % | 16 / 23 (70 %) |
| megalis | 10 | 2,7 % | 8 / 10 |
| xmarches | 10 | 2,7 % | 9 / 10 |
| marches-securises | 8 | 2,2 % | 2 / 5 tentés |
| marchespublics596280.fr (fork Atexo) | 6 | 1,6 % | 5 / 5 |
| ternum, maximilien, demat-ampa | 5 / 5 / 3 | ~3,5 % | 100 % des tentés |
| safetender, klekoon | 3 / 1 | ~1 % | 0 |
| ~28 autres hôtes | 37 (sur les 912) | — | — |

Sur l'ensemble des 912 marchés BTP : 63 % n'ont pas d'URL (essentiellement le stock d'octobre),
13,4 % AWS, 5,8 % PLACE, 3,4 % achatpublic, 2,9 % Dematis, 2,2 % marches-securises.
**AWS-Achat est la première plateforme BTP.**

#### 3.2.2 Taux de succès des downloaders (journaux JSONL réels)

Source : `logs/<downloader>_2026-*.jsonl`, période du 13/06 au 03/07/2026. Il n'y a **aucun
journal depuis juillet**. `xmarches` et `marches_securises` n'écrivent pas de JSONL.

| Downloader | Tentatives | Réussies | Taux par tentative | Marchés distincts réussis au moins une fois | Captchas résolus | Erreurs principales |
|---|---:|---:|---:|---:|---:|---|
| aws-achat | 246 (+31 skip) | 204 | 83 % | 203 / 205 (99 %) | 224 | cdn 15, session 14, ban_persistant 7, captcha 6 |
| atexo (PLACE + forks) | 235 | 143 | 61 % | 133 / 152 (88 %) | 0 | non typées (92) |
| achatpublic | 167 | 91 | 54 % | 90 / 101 (89 %) | 0 | non typées (76) |
| dematis | 109 (+10 skip) | 62 | 57 % | 43 / 62 (69 %) | 87 | session 32, ban_persistant 12 |
| dce-finder (générique) | 17 | 0 | 0 % | 0 / 2 | 0 | — |

Champs du journal : `downloader, id_marche, ok, etape_erreur, erreur, nb_fichiers, taille_octets,
duree_secondes, nb_captcha_resolus, nb_doublons_ecartes, tentatives_ip, variante_lien, skip, timestamp`.

#### 3.2.3 Technique de chaque downloader (base du futur dépôt assisté)

Tous fonctionnent en HTTP « brut », **sans navigateur headless** : ni Playwright, ni Selenium
(`tendia_telecharger_dce.py` le note : « Sites avec JS dynamique → non gérés »). Tous sont
**anonymes** : **aucun ne s'authentifie** avec un compte entreprise. L'identité déclarée dans
certains formulaires vient des variables `TENDIA_DL_*`.

| Module | Plateforme | Accès | Technique | Protections contournées |
|---|---|---|---|---|
| `atexo_downloader.py` (+ `place_downloader.py`, ancien) | PLACE + forks Atexo MPE/PRADO (megalis, maximilien, ternum, demat-ampa, municipaux) | anonyme (option « télécharger anonymement » + CGU) | GET formulaire → POST anonyme → postback PRADO `completeDownload` (ViewState/`PRADO_PAGESTATE`) ; détection du fork par signature HTML ; vérification `PK` | état de page PRADO, `PRADO_POSTBACK_TARGET` ; proxy désactivable (`TENDIA_PROXY_FOR_PLACE=0`) |
| `aws_downloader.py` | marches-publics.info (AWS-Achat, ColdFusion) | anonyme | 7 étapes (CFID/CFTOKEN dans l'URL), parsing des lots, CDN `downloads.awsolutions.fr` | **captcha image (2captcha)**, **ban IP** (détection de page de ban + rotation d'IP par session-id proxy, `max_retries_ban=3`), retries avec backoff, rythme « humain » |
| `dematis_downloader.py` | e-marchespublics | anonyme | lien anonyme SHA-1 (leurre MD5 ignoré) → page captcha → POST → `getfile.php` | **captcha (2captcha)**, cookie `PHPSESSID` à domaine vide (hook), noms mojibake, dédoublonnage, « Accès non autorisé » → rotation d'IP |
| `achatpublic_downloader.py` | achatpublic.com | anonyme | GET détail `PCSLID` → POST `telechargerDCE.action` ; resolver par référence | aucun captcha ni session ; décompression des ZIP imbriqués |
| `xmarches_downloader.py` | xmarches.fr | anonyme | GET détail → redirection captcha → POST avec jeton `SECU` | **captcha (2captcha)**, cookies de session, retries multi-passes |
| `marches_securises_downloader.py` | marches-securises.fr | anonyme | recherche par référence ou objet (POST), désambiguïsation acheteur, **sous-processus tuable par marché** | **quota par IP** (rotation proxy), `Referer`, anti-blocage `IncompleteRead` |
| `dce_finder.py` / `ParseurGenerique` | autres | anonyme | recherche de liens `href` | — (nécessite `bs4`, absent) |

Couche commune : `http_client.py` (curl_cffi avec empreinte TLS Chrome si installé, **sinon
`requests`** ; aujourd'hui `requests`, car curl_cffi est absent), `http_humain.py` (UA tournants,
en-têtes `Sec-Fetch`, délais gaussiens, heures de bureau, session-id proxy), `truststore`.

**Pour le dépôt assisté** : ces modules ne savent que **télécharger anonymement**. Le dépôt exige
un **compte entreprise authentifié**, la **signature électronique** et des flux JavaScript (applets,
horodatage), donc un navigateur piloté (Playwright) ou l'usage des API de dépôt quand elles
existent (à confirmer par plateforme). Le code réutilisable se limite aux parseurs de pages, au
pilotage des formulaires PRADO, aux sessions, au proxy, aux captchas et aux journaux.

**ZIP imbriqués** :
- `tendia_dce.qualifier_dce` lit en mémoire les noms dans les ZIP (1 niveau imbriqué) et dans
  les `.7z` / `.rar` (via `py7zr` ; `rarfile` est absent, donc les `.rar` sont ignorés) pour
  **qualifier** le DCE.
- Les downloaders dédiés décompressent les ZIP imbriqués (`achatpublic_downloader._decompresser_zip_imbrique`,
  réutilisé par aws et dematis).
- `tendia_extraire._dezipper_dossier` : extrait **à plat** (basename) les `.zip` **du premier niveau**
  de `data/dce/<id>/`, puis déplace le zip dans `_zip_archives/`. Un zip contenu dans un zip
  arrive comme `.zip` dans le dossier et n'est traité qu'à un passage suivant (à confirmer).
  Les fichiers de même nom sont ignorés (« déjà présent »).

**Stockage** : `data/dce/<id_marche>/` (jonction Windows vers un 2ᵉ disque, sans variable
d'environnement de chemin). 1 193 dossiers ; 341 dossiers `*.bak_*` (sauvegardes avant
re-téléchargement). Extensions présentes (comptage de fichiers) : pdf 12 326, **dwg 2 932**,
docx 1 734, xlsx 1 693, zip 1 622, jpg 954, **doc 922**, shx 337, **xls 296**, tif 284, png 231…
On compte **2 996 sous-dossiers** (les DCE livrés en arborescence). Exemple de structure :

```
data/dce/BOAMP-26-56539/
  00-DCE-ATTRI1 - ACTE ENGAGEMENT 02-2026.doc   ← .doc : NON LU par l'extraction prod
  00-DCE-CCAP-MARCHE 02-2026.pdf
  00-DCE-RC-MARCHE 02-2026 V2.pdf
  01-CCTP_Lots1a7_19-05-2026_Ind2.pdf
  02-01_INSTAL_CHANTIER.pdf …
  04-DPGF_Lots1a7_19-05-2026_Ind1.XLSX
  _zip_archives/…
```

### 3.3 Extraction du texte

**[PROD] `pdf_extract.py` + `tendia_extraire.py`**

| Aspect | Réalité prod |
|---|---|
| Formats lus | `.pdf` (pypdf), `.docx` (python-docx, paragraphes et tableaux), `.xlsx` (openpyxl, toutes les feuilles) : `EXTENSIONS_SUPPORTEES = (".pdf", ".docx", ".xlsx")` |
| Formats ignorés | `.doc`, `.xls`, `.xlsm`, `.odt`, `.ods`, `.rtf`, images, CAO… : **silencieusement** |
| Sous-dossiers | **non parcourus** : `extraire_dossier` fait un `os.listdir(dossier)` sans récursion |
| Scans / OCR | **aucun OCR.** Un PDF sans texte donne moins de 1 000 caractères et est **rejeté** par `_est_pdf_non_dce` (« taille trop petite ») |
| Filtre « non-DCE » | `_est_pdf_non_dce` : noms de guide/DUME, moins de 1 000 caractères, ou moins de 10 000 sans nom métier → exclu |
| LibreOffice | **absent en prod** |
| Assemblage | concaténation `=== PIÈCE : <nom> ===` dans l'ordre alphabétique |
| Troncature | `llm_extract.MAX_CHARS_INPUT = 400_000` caractères : **coupe brute** de la fin (les dernières pièces par ordre alphabétique sont perdues) |
| « Mode document » | **inexistant en prod** : un seul appel avec tout le texte |

Mesure en EXP (`exp_analyses`, variante `claude_prod`, BOAMP-26-102054) : 2 558 790 caractères
rassemblés, 400 000 envoyés, `pct_non_lu = 49,2 %`. Pièces non lues : les annexes `.xls` du CCTP,
les DQE de 3 lots, le BPU lu à 28 %, DC1…

**[EXP] `exp_gemini/pieces.py` + `mode_document.py`**
- Inventaire récursif (sous-dossiers et ZIP imbriqués décompressés dans `data/exp_gemini/pieces/<id>/`,
  jamais dans `data/dce/`). `.rar`/`.7z` sont marqués non gérés.
- Conversion `.doc/.docx/.odt/.rtf/.docm/.dot/.dotx` → PDF et `.xls/.xlsm/.ods/.xlsb` → `.xlsx` via
  **Word/Excel COM** si Office est installé, sinon **LibreOffice headless** (`soffice --convert-to`,
  profil isolé), avec repli croisé ; forçable par `TENDIA_CONVERSION=office|libreoffice`.
- Plans et CAO ignorés (extensions et regex sur le nom : plan, coupe, façade…). Dédoublonnage par empreinte.
- Texte **page par page** (`[[Page N]]`, `[[Feuille X]]`). PDF scanné → **lecture visuelle**
  (PDF natif découpé en parties de 100 pages et 20 Mo au plus).
- Typage des pièces : RC, CCAP, CCTP, BPU_DPGF_DQE, AE, annexe (nom de fichier, puis premières lignes).
- Mode « global sans troncature » : tout en un appel, avec les marqueurs de page et une consigne de sources.
- Mode « document » : 1) un appel par pièce avec des **questions propres au type** (cf. §4.2.4),
  chaque réponse étant sourcée (pages et extrait) ; 2) fusion dans le **schéma de prod**
  (prompt prod, les notes remplaçant le texte brut) ; 3) **contrôle de complétude** de 6 champs
  critiques (critères/pondérations, date limite, pièces exigées, visite, montant, lots) avec une
  recherche ciblée dans les pièces concernées.
- Découpage d'une pièce au-delà de 350 000 tokens par appel, aux marqueurs de page (aucune
  troncature). 4 pièces en parallèle.

---

## 4. Analyse IA

### 4.1 Classification et presets

**Presets** (`presets/<code>/_preset.json`) : clés `meta, veille, vocabulaire_llm,
prompt_extraction{description, bloc_schema_specifique, regles_specifiques, exemples_elements_a_chiffrer,
hints_calcul_montant, few_shot_examples}, prompt_calibration, calibration_llm, matching, taxonomie`.

| Preset | `_schema.json` (profil sectoriel) | Bloc sectoriel du brief |
|---|---|---|
| btp | ✅ | `caracteristiques_techniques_chantier`, `allotissement`, `qualifications_requises` |
| ingenierie | ✅ | `caracteristiques_mission_moe`, `qualifications_moe` (…) |
| energie_renouvelable | ✅ | `caracteristiques_techniques_enr`, `qualifications_enr` (…) |
| formation | ✅ | `publics_cibles`, `volumes`, `modalites`, `qualifications_formation` (…) |
| conseil, it | ❌ | `caracteristiques_mission`, `profils_intervenants`, `qualifications_conseil` / `caracteristiques_mission_it`, `qualifications_it` |
| assurance, evenementiel, fourniture, paysager, proprete, restauration, sante, transport | ❌ | blocs `caracteristiques_<x>` / `qualifications_<x>` (ajoutés après la passation) |

`presets/_taxonomie_domaines.json` : **64 domaines** (la passation en annonce 56).
`presets/_actif.json` = `formation` (preset « actif » legacy, utilisé en repli du vocabulaire).

**Classification** (`tendia_classification.py`) [PROD, mais **hors pipeline**] :
- Entrée : titre, objet, CPV, acheteur. Pré-filtre gratuit (avis d'attribution, marchés expirés, CPV exclus).
- Modèle : `claude-haiku-4-5` (par défaut) ou `claude-sonnet-4-6` ; `max_tokens=800` ;
  `client.messages.create` sans timeout explicite.
- Sortie : `{domaines_metier:[{code, poids?, lots_concernes?}], raison_classification, synthese_courte}`
  + `_meta{modele, date, input_tokens, output_tokens, cout_eur, duree_s}` → `classifications_ia`.
- 1 037 classifications (coût cumulé 6,33 €). **Aucune** pour les 1 992 marchés d'octobre.
- Resynchronisation : après un brief complet, `tendia_extraire` remplace `domaines_metier`
  si le brief diffère (`source="brief_complet"`, 96 cas).

**Routage du brief** : `llm_extract._resoudre_presets_pour_marche(id)` lit
`classifications_ia[id].domaines_metier`, puis `preset.presets_pour_domaines(codes)` donne la liste
de presets. Seuls les blocs de ces presets sont injectés. Une liste vide donne le bloc neutre
`caracteristiques_metier`. Après l'appel, `_filtrer_hallucinations` supprime tout bloc de
premier niveau hors de `_CHAMPS_UNIVERSELS_BRIEF` et des blocs autorisés.

### 4.2 Analyse des DCE : le brief

**Fichiers** : `llm_extract.py` (prompt, appel, post-traitement), `tendia_extraire.py`
(orchestration, stockage, rendu Markdown), `preset.py` (blocs sectoriels).
**Modèle** : `claude-sonnet-4-6`, `MAX_TOKENS_REPONSE = 32000`, **streaming**
(`client.messages.stream`), `max_retries=2` (pause de 2 s), pas de timeout explicite (le
streaming garde la connexion ouverte).
**Stockage** : `kv_storage[briefs_extraits/<id_marche>]` **et** `data/extractions/<id>.json`
**et** `rapports/brief_<id>.md` (rendu).

#### 4.2.1 Prompt

- **Système** : `llm_extract._construire_prompt_systeme(codes_presets)`, l.244-275 : rôle
  d'expert, secteur/pièces/répondant tirés de `vocabulaire_llm` des presets, « JSON
  uniquement », plus une section taxonomie (`_section_taxonomie_prompt`, l.142).
- **Utilisateur** : `PROMPT_UTILISATEUR_TEMPLATE`, **`llm_extract.py` l.363-682**. Placeholders :
  `{contexte}` (JSON du marché : id, titre, acheteur, champs BOAMP…), `{texte}` (DCE concaténé),
  `{bloc_schema_specifique}`, `{exemples_elements_a_chiffrer}`, `{hints_calcul_montant}`,
  `{few_shot_examples}`, `{regles_specifiques}`, `{regles_v2}`.
- **Règles v2/v3** : `REGLES_V2`, **l.686-893** (montant en 3 voies, coût/CA/marge par lot,
  `unite_evaluation`, poids prix obligatoire, cohérence finale, dossier de candidature, tranches,
  certifications bloquantes avec codes, contexte BOAMP). Version : `PROMPT_V2_SHA` =
  sha256(REGLES_V2)[:12], stocké dans `prompt_version_sha`.
- **Blocs sectoriels** : `presets/<code>/_preset.json → prompt_extraction.bloc_schema_specifique`
  (versionné par `preset.hash_preset` → `_meta.prompts_versions`).

#### 4.2.2 Schéma JSON de sortie EXACT demandé au LLM (prod)

Universel, tel qu'il est écrit dans le template (valeurs = consignes ou valeurs par défaut) :

```jsonc
{
  "synthese_marche": "str",
  "domaines_metier": [{"code": "str", "poids": null, "lots_concernes": null}],
  "raison_classification": "str",
  /* {bloc_schema_specifique} : blocs sectoriels des presets routés, ex. BTP ci-dessous */
  "bareme_notation": {
    "valeur_technique_pct": null, "valeur_prix_pct": null,
    "sous_criteres_techniques": [{
      "libelle": "str", "ponderation_pct": 50, "description": "str",
      "elements_attendus": ["str"], "exemple_reponse_forte": "str", "source": "str|null",
      "unite_evaluation": "euro|delai_jours|points",
      "sous_criteres": [{ /* récursif */ "libelle": "", "ponderation_pct": 30, "description": "",
        "elements_attendus": [], "exemple_reponse_forte": "", "source": "",
        "grille_actions": [{"action": "str", "type": "livrable|levier", "poids_pct": 60, "source": "str|estimé"}]
      }]
    }],
    "prix": {
      "type_formule": "moins_disant|lineaire|ecart_type|seuil|prix_reference|autre",
      "formule_explicite": "str", "source": "str|null",
      "elements_a_chiffrer": ["str"]
    },
    "modalite_calcul_prix": "str"
  },
  "montant_marche": {"valeur_estimee_euros": null, "fourchette_min_euros": null, "fourchette_max_euros": null,
    "type": "estime_explicite|plafond|calcule_volumes|non_communique",
    "duree_couverte": null, "source_extraction": null, "commentaire": null},
  "montant_3_voies": {"voie_1_eur": null, "voie_1_source": null, "voie_2_disponible": false,
    "voie_2_min_eur": null, "voie_2_max_eur": null,
    "voie_2_hypotheses": [{"hypothese": "str", "valeur": "str"}], "voie_2_raison_indisponible": null},
  "cout_realisation": {"cout_total_eur": null, "cout_min_eur": null, "cout_max_eur": null,
    "postes": [{"poste": "str", "detail": "str", "montant_eur": null}],
    "taux_journaliers_retenus": "str", "commentaire": "str"},
  "revision_prix": {"type": "indexation|actualisation|ferme|non_communique", "indices_utilises": ["str"],
    "ponderation": "str", "periodicite": "str", "formule_revision": "str",
    "source_extraction": "str", "commentaire": "str"},
  "alertes_prix": ["str"],
  "references_exigees": {
    "experience_minimale_annees": null, "experience_source": "str|null",
    "volume_min_references_similaires": null, "volume_min_references_unite": "str|null",
    "secteur_experience": "str", "secteur_source": "str|null",
    "certifications_obligatoires": [{"libelle": "str", "codes": ["5413"], "bloquante": true, "source": "str"}],
    "autres_exigences": [{"libelle": "str", "source": "str|null"}]
  },
  "dossier_candidature": {
    "pieces_a_fournir": [{"libelle": "str", "phase": "candidature|offre", "obligatoire": true, "source": "str|null"}],
    "mode_remise": "str|null", "plateforme_depot": "str|null",
    "signature_electronique_exigee": "bool|null", "format_signature": "str|null",
    "nombre_exemplaires": "int|null", "langue": "str|null",
    "duree_validite_offres_jours": "int|null", "modalites_source": "str|null"
  },
  "lots": [{"numero": 1, "intitule": "str", "domaine": "code taxonomie|null", "zone_geographique": "str|null",
    "volume_estime": null, "volume_estime_unite": "str|null",
    "cout_estime_min_eur": null, "cout_estime_max_eur": null,
    "ca_estime_min_eur": null, "ca_estime_max_eur": null, "marge_brute_pct": null,
    "particularites": "str"}],
  "tranches": [{"type": "ferme|optionnelle|conditionnelle", "numero": "str|int|null", "intitule": "str",
    "objet": "str", "montant_estime_eur": "num|null", "condition_affermissement": "str|null", "source": "str|null"}],
  "calendrier": {"date_limite_offres": "YYYY-MM-DD", "date_demarrage_prevue": "YYYY-MM-DD", "duree_marche": "str"},
  "alertes_candidat": ["str"],
  "points_differenciants_attendus": [{"libelle": "str", "exemple": "str", "source": "str|null"}]
}
```

**Bloc sectoriel BTP** (`presets/btp/_preset.json`, injecté si le preset btp est routé) :

```jsonc
"caracteristiques_techniques_chantier": {"description": "", "typologie_ouvrage": "", "surface_volume": "",
   "site_occupe": "bool + précisions", "corps_etat": [""], "contraintes_specifiques": [""]},
"allotissement": {"description": "", "nb_lots": null,
   "lots_detailles": [{"numero": 1, "intitule": "", "corps_etat": "", "montant_estime": null, "description": ""}]},
"qualifications_requises": {"description": "", "qualibat": ["codes à 4 chiffres"], "rge": "bool",
   "rge_specialites": [""], "mase": "bool", "iso_9001": "bool", "iso_14001": "bool", "iso_45001": "bool",
   "opqibi": "", "autres_certifications": []}
```
Règles BTP : détailler chaque lot ; extraire les indices Qualibat ; signaler un site occupé ;
distinguer neuf et réhabilitation ; **double remplissage** des certifications dans
`qualifications_requises` ET dans `references_exigees.certifications_obligatoires`.

**Champs ajoutés par le code après le LLM** :
- par `tendia_extraire.traiter_marche` : `_meta{id_marche, type:"complet", date_generation,
  extraction_le, modele, preset_utilise, presets_matches[], prompts_versions{"btp/_preset.json":"sha256:…"},
  tokens_input, tokens_output, cout_eur, duree_sec, pdfs_traites[{nom, hash(md5), taille_chars}]}` ;
- par `_filtrer_hallucinations` et `_normaliser_codes_domaines` : nettoyage ;
- par `post_traiter_extraction_v2` (**appelé seulement par les scripts `reextraire_briefs_v2.py` et
  `rederiver_criteres_plat.py`, pas par `tendia_extraire`**) : `criteres_attribution_plat[{libelle,
  famille, ponderation_pct, unite_evaluation, source_texte}]`, `criteres_somme_ponderations`,
  `criteres_alerte_{somme_incorrecte,pas_de_prix,non_classes}`, `montant_voie_1_{eur,source}`,
  `montant_voie_2_disponible`, `montant_au_moins_une_voie`, `montant_alerte_coherence`,
  `revenu_{eur,min_eur,max_eur,source}`, `cout_realisation_eur`, `cout_{min,max}_eur`,
  `marge_{eur,pct,alerte}`, `revenu_sous_seuil_boamp`, `extraction_v2_a_verifier`,
  `version_extraction_llm="2"`, `prompt_version_sha` (présents sur 134 briefs) ;
- par les scripts de ré-extraction : `genere_avec_dce_complet`, `_reextrait_v3`,
  `brief_v1_backup`, `brief_v1_backup_expire_le`, `extraction_v2_le`.

**Union des clés de premier niveau réellement présentes** dans les 474 entrées (sauvegardes
comprises) : voir le §2.3. Les blocs sectoriels inattendus (`btp_gros_oeuvre`,
`btp_voirie_reseaux`, `energie_pv_solaire`… : 1 ou 2 occurrences) sont des résidus d'anciennes versions.

#### 4.2.3 Ce que le brief extrait déjà sur les sujets de l'agent

| Sujet | Champs existants (prod) | Remplissage (239 briefs actuels) | Manques pour la matrice |
|---|---|---|---|
| **Pièces exigées** | `dossier_candidature.pieces_a_fournir[{libelle, phase (candidature/offre), obligatoire, source}]` + modalités (`mode_remise`, `plateforme_depot`, `signature_electronique_exigee`, `format_signature`, `nombre_exemplaires`, `langue`, `duree_validite_offres_jours`, `modalites_source`) | 209 briefs, **2 440 pièces** | ni **lot**, ni **porteur** (mandataire, chaque cotraitant, sous-traitant), ni **type normalisé** (DC1, DC2, Kbis, URSSAF…), ni **validité / ancienneté** exigée (« < 3 mois »), ni **format** ; libellé libre |
| **Capacités / certifications** | `references_exigees.certifications_obligatoires[{libelle, codes[], bloquante, source}]`, `autres_exigences[{libelle, source}]`, `experience_minimale_annees`, `volume_min_references_*`, `secteur_experience` ; BTP : `qualifications_requises{qualibat[], rge, mase, iso_*, …}` | certifications 143, autres exigences 213, qualifications BTP 98 | même chose : pas de porteur (capacité appréciée globalement au groupement ou par membre ?), pas de lot |
| **CA minimum** | **aucun champ numérique.** Texte libre dans `references_exigees.autres_exigences[].libelle` (ex. « Chiffre d'affaires annuel moyen … ≥ 86 100 € »). `matching_exigences` le rattrape par regex (clé canonique `ca_min_<montant>`) | — | champ `{montant_eur, periode (moyenne 3 ans / dernier exercice), perimetre (global / lot / groupement cumulé), source}` |
| **Qualifications** | `certifications_obligatoires[{libelle, codes[], bloquante, source}]` ; BTP : `qualifications_requises{qualibat[] (codes à 4 chiffres), rge, rge_specialites, mase, iso_*, autres_certifications}` | 143 / 98 | qualifications par lot, « ou équivalent », appréciation au niveau du groupement |
| **Références** | `experience_minimale_annees`, `volume_min_references_similaires` + `_unite`, `secteur_experience` (texte) | partiel | nombre, montant minimal, ancienneté (« 3 ou 5 dernières années »), attestations de bonne exécution exigées |
| **Effectif** | **aucun champ.** Texte libre (pièce « déclaration des effectifs moyens… ») | — | effectif minimal, encadrement |
| **Critères** | `bareme_notation` hiérarchique (+ `grille_actions` sur les feuilles, `unite_evaluation`) ; `criteres_attribution_plat` (v2) | barème 460/474 entrées | **un seul barème par brief** (le prompt impose la grille du lot principal si elle diffère par lot) |
| **Lots** | `lots[]` (numéro, intitulé, domaine, zone, volume, coût/CA/marge) ; BTP : `allotissement.lots_detailles[]` (corps d'état, description) | lots 201, allotissement 98 | pas de règles « nombre de lots maximum par candidat », ni de pièces / critères par lot |
| **Tranches** | `tranches[]` | 20 | — |
| **Visite** | **aucun champ.** N'apparaît qu'en texte libre (`alertes_candidat`, ou une pièce « Attestation de visite » dans `pieces_a_fournir`, ou une `certifications_obligatoires` détournée) | — | champ structuré (obligatoire, dates, contact, attestation) |
| **Groupement / cotraitance** | **aucun champ** | — | forme imposée (solidaire / conjoint), mandataire solidaire, interdiction de cumul de mandats, pièces par membre |
| **Sous-traitance** | **aucun champ** (le DC4 apparaît parfois dans `pieces_a_fournir`) | — | autorisée ou non, limites, paiement direct, DC4 |
| **Variantes / PSE** | aucun champ | — | — |

**Exemple réel** (BOAMP-26-56539, CPAM, réhabilitation en 8 lots, BTP, brief complet du 2026-06-19,
Sonnet 4.6, 163 536 tokens en entrée, 0,65 €). On notera que l'acte d'engagement `.doc` du DCE ne
figure pas dans `pdfs_traites` (format non lu).

```json
"dossier_candidature": {
  "pieces_a_fournir": [
    {"libelle": "Lettre de candidature (formulaire DC1 ou équivalent) avec déclaration sur l'honneur", "phase": "candidature", "obligatoire": true, "source": "RC article 17"},
    {"libelle": "Déclaration du candidat (formulaire DC2 ou équivalent) avec extrait K-bis < 3 mois et pouvoirs", "phase": "candidature", "obligatoire": true, "source": "RC article 17"},
    {"libelle": "Liste descriptive des travaux similaires exécutés au cours des 5 dernières années (date, lieu, montant)", "phase": "candidature", "obligatoire": true, "source": "RC article 17"},
    {"libelle": "Déclaration des effectifs moyens annuels sur les 3 dernières années", "phase": "candidature", "obligatoire": true, "source": "RC article 17"},
    {"libelle": "Certificats de qualifications professionnelles ou preuves équivalentes", "phase": "candidature", "obligatoire": false, "source": "RC article 17"},
    {"libelle": "Acte d'engagement (AE ou ATTRI1) complété et signé pour le lot concerné", "phase": "offre", "obligatoire": true, "source": "RC article 19"},
    {"libelle": "Décomposition du Prix Global et Forfaitaire (DPGF) correspondant au lot concerné, complétée sans modification du cadre", "phase": "offre", "obligatoire": true, "source": "RC article 19"},
    {"libelle": "Mémoire technique … (lots 1 à 7) ou mémoire technique VDI structuré en 9 sections (lot 8)", "phase": "offre", "obligatoire": true, "source": "RC article 19"},
    {"libelle": "Attestation de visite du site (remise lors de la visite obligatoire)", "phase": "offre", "obligatoire": true, "source": "RC article 10"},
    {"libelle": "Attestation d'assurance décennale (pour les lots concernés)", "phase": "offre", "obligatoire": true, "source": "RC article 19"},
    {"libelle": "Attestation constructeur d'éligibilité à la garantie système 25 ans cuivre et fibre (lot 8)", "phase": "offre", "obligatoire": true, "source": "RC article 19"},
    {"libelle": "DC4 ou équivalent pour chaque sous-traitant connu", "phase": "offre", "obligatoire": false, "source": "RC article 16"}
    /* … 19 pièces au total */
  ],
  "mode_remise": "dématérialisé + copie de sauvegarde",
  "plateforme_depot": "PLACE — marches-publics.gouv.fr",
  "signature_electronique_exigee": true, "format_signature": "XAdES, CAdES ou PAdES",
  "nombre_exemplaires": null, "langue": "français", "duree_validite_offres_jours": 120,
  "modalites_source": "RC articles 21 et 22"
},
"references_exigees": {
  "experience_minimale_annees": 5,
  "volume_min_references_unite": "marchés similaires (références chantiers réalisés avec date, lieu, montant)",
  "certifications_obligatoires": [
    {"libelle": "Attestation d'assurance responsabilité civile professionnelle en cours de validité", "codes": [], "bloquante": true, "source": "RC article 28 et CCAP article 37"},
    {"libelle": "Attestation CONSUEL pour le lot 6 (Électricité) — condition de réception des travaux", "codes": [], "bloquante": false, "source": "CCAP article 8 …"},
    {"libelle": "Attestation de visite du site obligatoire (remise lors de la visite aux dates fixées)", "codes": [], "bloquante": true, "source": "RC article 10 et article 19"}
  ],
  "autres_exigences": [{"libelle": "Extrait K-bis datant de moins de 3 mois", "source": "RC article 17"}, "…"]
},
"qualifications_requises": {"description": "… sans imposer de codes Qualibat spécifiques …", "qualibat": [], "rge": false, "mase": false, "iso_9001": false, "…": "…"},
"allotissement": {"nb_lots": 8, "lots_detailles": [{"numero": 1, "intitule": "Démolitions", "corps_etat": "démolition", "montant_estime": null, "description": "…"}, "…"]},
"lots": [{"numero": 1, "intitule": "Démolitions", "domaine": "btp_demolition", "zone_geographique": "Tours (37)",
          "volume_estime": 2268, "volume_estime_unite": "m² …", "cout_estime_min_eur": 70000, "cout_estime_max_eur": 110000,
          "particularites": "Démolitions obligatoirement en horaires décalés …"}, "…"],
"tranches": [{"type": "ferme", "numero": "TF", "montant_estime_eur": 1065000, "source": "CCAP article 5 ; RC article 7"},
             {"type": "conditionnelle", "numero": "TC", "montant_estime_eur": 615000,
              "condition_affermissement": "… sous réserve d'obtention de fonds nationaux …"}],
"calendrier": {"date_limite_offres": "2026-07-06", "date_demarrage_prevue": "2027-01-01", "duree_marche": "24 mois …"},
"alertes_candidat": ["Visite de site OBLIGATOIRE aux dates imposées (18/06 pour lots 1-5, 19/06 pour lots 6-8) avec attestation …", "…"]
```
On observe ici les **limites structurelles** : la visite n'est représentée que par une pièce et une
alerte en texte libre ; les pièces propres au lot 8 sont marquées « (lot 8) » dans le libellé ; la
sous-traitance n'apparaît que par le DC4 ; rien n'indique qui (mandataire ou cotraitant) fournit quoi.

#### 4.2.3bis Exemple réel complet (BTP) : `briefs_extraits/BOAMP-26-56606`

Restauration extérieure d'une église (Loiret), 3 lots, AWS-Achat, brief complet du 19/06/2026
(Sonnet 4.6, 79 920 tokens en entrée, 0,33 €). Le brief est reproduit **intégralement** ;
seuls le nom de l'architecte (personne physique) est masqué et `pdfs_traites` est réduit aux noms
de fichiers.
⚠️ Observation : `AWS-MPI-1832530-RC.pdf` figure dans `pdfs_traites`, mais le brief affirme
« le RC n'est pas disponible ». Le RC a probablement été écarté par le filtre
`_est_pdf_non_dce` (PDF scanné de moins de 1 000 caractères ?) — à confirmer. `pdfs_traites`
liste tous les PDF du dossier, y compris les rejetés. Le barème et les critères de
participation sont donc manquants.

```json
{
 "synthese_marche": "Marché de travaux de restauration extérieure de l'église Saint-Loup à Saint-Loup-des-Vignes (Loiret), portant sur la nef et le chœur avec drainage des façades nord, est et sud. Le marché est alloti en 3 lots : maçonnerie/pierre de taille (avec drainage), charpente/couverture ardoise, et vitraux. Il s'agit de travaux sur un édifice classé ou présentant un intérêt patrimonial, avec des contraintes techniques spécifiques aux monuments historiques.",
 "domaines_metier": [{"code": "btp_renovation_rehabilitation"}],
 "raison_classification": "Le marché porte sur la restauration extérieure d'une église (maçonnerie pierre de taille, charpente couverture ardoise, vitraux, drainage) sans dominante énergétique. Le CCTP mentionne explicitement les prescriptions applicables aux édifices classés Monuments Historiques, relevant du domaine réhabilitation/restauration du bâti patrimonial.",
 "caracteristiques_techniques_chantier": {
  "description": "Restauration extérieure de la nef et du chœur de l'église Saint-Loup : traitement des élévations extérieures et contreforts (biocide, rejointement chaux, remplacement pierres de taille dégradées, enduits), réfection complète de la couverture en ardoises épaisses avec charpente, restauration et protection de vitraux (grisaille, raquettes cuivre), et drainage périphérique des façades nord, est et sud.",
  "typologie_ouvrage": "Église classée/présentant un intérêt historique ou architectural particulier (code CPV 45212350)",
  "surface_volume": "Non précisé explicitement dans les pièces disponibles",
  "site_occupe": "false — aucune mention d'occupation du site pendant les travaux (article 0.6 CCTP : 'Sans objet' pour les sujétions liées à l'exploitation de l'édifice)",
  "corps_etat": [
   "Maçonnerie - Pierre de taille (échafaudages, traitement biocide, remplacement pierres, rejointement, enduits, drainage)",
   "Charpente - Couverture (révision charpente, réfection couverture ardoises épaisses, faîtage plomb, gouttières zinc)",
   "Vitraux (reprise grisaille, raquettes de protection cuivre grillagé)"
  ],
  "contraintes_specifiques": [
   "Travaux sur édifice classé ou présentant un intérêt historique ou architectural particulier — application des règles de l'art et prescriptions Monuments Historiques",
   "Utilisation obligatoire de matériaux compatibles : chaux aérienne/hydraulique naturelle, pierres de carrière identiques à l'existant, ardoises 1er choix, mortiers sans ciment",
   "Présentation préalable d'échantillons pour validation Architecte du Patrimoine avant exécution",
   "Approbation des échafaudages par organisme de contrôle agréé avec certificat de conformité",
   "Visite obligatoire sur site (prendre rendez-vous en mairie)",
   "Coordonnateur SPS à nommer — opération de 2e catégorie",
   "Période de préparation d'un mois incluse dans le délai d'exécution",
   "Maître d'œuvre : Architecte du Patrimoine (<nom masqué>)",
   "Matériaux conformes aux recommandations du LRMH (Laboratoire de Recherche sur les Monuments Historiques)"
  ]
 },
 "allotissement": {
  "description": "Marché alloti en 3 lots distincts, chaque lot faisant l'objet d'un marché séparé, en tranche unique.",
  "nb_lots": 3,
  "lots_detailles": [
   {"numero": 1, "intitule": "Maçonnerie - Pierre de Taille", "corps_etat": "Maçonnerie pierre de taille, drainage", "montant_estime": null,
    "description": "Installations de chantier communes, échafaudages extérieurs, traitement des élévations et contreforts (biocide, remplacement pierres, rejointement chaux, enduits), et drainage périphérique des façades nord, est et sud"},
   {"numero": 2, "intitule": "Charpente Couverture", "corps_etat": "Charpente, couverture ardoise", "montant_estime": null,
    "description": "Révision et confortement de la charpente (bois, renforts métalliques, entures), réfection complète de la couverture en ardoises épaisses à pureau décroissant, création arêtiers, faîtage plomb, épi de faîtage zinc, gouttières zinc"},
   {"numero": 3, "intitule": "Vitraux", "corps_etat": "Vitraux", "montant_estime": null,
    "description": "Reprise de grisaille sur vitraux (nettoyage, révision plombs, repiquage verres cassés, patine) et fourniture/pose de raquettes de protection en cuivre grillagé"}
  ]
 },
 "qualifications_requises": {
  "description": "Le RC renvoie aux critères de participation — aucune qualification Qualibat ou certification spécifique n'est mentionnée explicitement dans les pièces disponibles (CCAP, CCTP, AAPC). L'AAPC indique 'renvoi au R.C.' pour les critères de participation.",
  "qualibat": [], "rge": false, "rge_specialites": [], "mase": false, "iso_9001": false, "iso_14001": false, "iso_45001": false, "opqibi": null,
  "autres_certifications": ["Compétences en travaux sur Monuments Historiques implicitement requises (prescriptions LRMH, techniques chaux, taille de pierre)"]
 },
 "caracteristiques_mission_moe": {"typologie": null, "phases_couvertes": [], "typologie_ouvrage": null, "montant_travaux_estime": null, "complexite_technique": null,
  "livrables_par_phase": [], "taux_remuneration_moe_pct": null, "indices_revision": [], "coordinations_associees": [], "organigramme_attendu": [], "bim_niveau": null},
 "qualifications_moe": {"opqibi": [], "opqcm": [], "bim": null, "autres": []},
 "bareme_notation": {
  "valeur_technique_pct": null, "valeur_prix_pct": null,
  "sous_criteres_techniques": [
   {"libelle": "Offre économiquement la plus avantageuse", "ponderation_pct": null,
    "description": "L'AAPC mentionne 'Offre économiquement la plus avantageuse appréciée en fonction des critères énoncés dans le cahier des charges (règlement de la consultation, lettre d'invitation ou document descriptif)'. Le règlement de consultation n'est pas disponible dans les pièces fournies, empêchant l'extraction des sous-critères et pondérations.",
    "elements_attendus": [], "exemple_reponse_forte": "—", "source": "AAPC — critères d'attribution", "unite_evaluation": "points", "sous_criteres": []}
  ],
  "prix": {
   "type_formule": "autre",
   "formule_explicite": "Non précisé — le règlement de consultation n'est pas disponible dans les pièces fournies.",
   "source": null,
   "elements_a_chiffrer": [
    "DPGF (Décomposition du Prix Global Forfaitaire) par lot",
    "Lot 1 : installations chantier, échafaudages, traitement élévations, drainage (fouilles, drains PVC DN100, remblais)",
    "Lot 2 : charpente (révision bois, renforts métalliques), couverture ardoise (dépose, voligeage, ardoises, accessoires plomb/zinc)",
    "Lot 3 : reprise grisaille vitraux, raquettes de protection cuivre"
   ]
  },
  "modalite_calcul_prix": "Non précisé — règlement de consultation non disponible"
 },
 "montant_marche": {"valeur_estimee_euros": null, "fourchette_min_euros": null, "fourchette_max_euros": null, "type": "non_communique", "duree_couverte": null,
  "source_extraction": "Aucun montant publié dans les pièces disponibles (CCAP, CCTP, AAPC)",
  "commentaire": "L'AAPC ne renseigne pas de montants estimés par lot ni de montant global. Le RC n'est pas disponible dans les pièces fournies."},
 "montant_3_voies": {
  "voie_1_eur": null, "voie_1_source": null, "voie_2_disponible": true, "voie_2_min_eur": 280000, "voie_2_max_eur": 420000,
  "voie_2_hypotheses": [
   {"hypothese": "Lot 1 Maçonnerie/Pierre de taille avec drainage : chantier de restauration patrimoniale comprenant échafaudages, traitement élévations, remplacement pierres en recherche, drainage périphérique. Surface élévations estimée à 400-500 m² (nef + chœur, façades nord/est/sud). Prix moyen restauration MH maçonnerie 350-450 €/m² + drainage forfait ~40-60 k€", "valeur": "Lot 1 : 180 000 – 270 000 €"},
   {"hypothese": "Lot 2 Charpente/Couverture : réfection complète couverture ardoise épaisse (5mm) sur nef et chœur. Surface couverture estimée à 300-400 m² (église rurale). Prix réfection couverture ardoise MH : 180-250 €/m² pose incluse, + charpente révision ~30-50 k€", "valeur": "Lot 2 : 80 000 – 120 000 €"},
   {"hypothese": "Lot 3 Vitraux : reprise grisaille + raquettes cuivre. Petite église rurale, estimation 5-8 baies. Reprise grisaille ~3 000-6 000 €/vitrail, raquettes cuivre ~200-300 €/m²", "valeur": "Lot 3 : 15 000 – 30 000 €"},
   {"hypothese": "Dimension variable retenue : prix unitaire (ratio €/m² couverture et €/m² maçonnerie), quantités fixées aux valeurs centrales estimées. Rapport max/min ≈ 1,5.", "valeur": "Fourchette globale : 280 000 – 420 000 €"}
  ],
  "voie_2_raison_indisponible": null
 },
 "cout_realisation": {
  "cout_total_eur": 210000, "cout_min_eur": 168000, "cout_max_eur": 252000,
  "postes": [
   {"poste": "Lot 1 — Maçonnerie/Pierre de taille + Drainage (main d'œuvre compagnons tailleur de pierre + maçon + drain, matériaux chaux/pierres, échafaudages)", "detail": "Ratio coût de production ~60-65% du prix de vente en restauration MH. Sur une estimation lot 1 à 225 k€ central, coût ~130-145 k€", "montant_eur": 137000},
   {"poste": "Lot 2 — Charpente/Couverture (charpentier, couvreur ardoise, fournitures ardoises épaisses + plomb/zinc)", "detail": "Ratio coût production ~60-65% du prix. Sur estimation lot 2 à 100 k€ central, coût ~60-65 k€", "montant_eur": 62000},
   {"poste": "Lot 3 — Vitraux (artisan maître verrier, grisaille, plomb, cuivre raquettes)", "detail": "Ratio coût production ~55-65% du prix. Sur estimation lot 3 à 22 k€ central, coût ~12-14 k€", "montant_eur": 13000}
  ],
  "taux_journaliers_retenus": "Compagnon tailleur de pierre/maçon MH : 45-55 €/h chargé ; couvreur ardoise : 40-50 €/h chargé ; maître verrier : 60-80 €/h chargé. Ratios coût/prix en restauration MH : 60-65% pour maçonnerie et couverture, 55-65% pour vitraux. Ces taux sont des estimations marché indicatifs.",
  "commentaire": "Estimation bottom-up construite lot par lot à partir des corps d'état décrits au CCTP. Les quantités (surfaces élévations, surface couverture) sont estimées par analogie avec une église rurale de taille standard. Fourchette obtenue en faisant varier le ratio coût/prix (60% min, 65% max), quantités fixées aux valeurs centrales."
 },
 "revision_prix": {
  "type": "actualisation",
  "indices_utilises": ["BT 03 (Lot 1 Maçonnerie - Pierre de Taille)", "BT 30 (Lot 2 Charpente - Couverture)", "BT 45 (Lot 3 Vitraux)"],
  "ponderation": "Actualisation unique par lot selon l'index BTP spécifique au lot. Formule : Cn = (Id-3) / Io. Aucune révision en cours d'exécution (délais courts).",
  "periodicite": "autre",
  "formule_revision": "Cn = (Id - 3) / Io, où Io = valeur de l'index au mois zéro (mois précédant la date limite des offres) et Id = valeur au mois d début d'exécution - 3 mois. Applicable uniquement si le démarrage est postérieur de plus de 3 mois au mois zéro.",
  "source_extraction": "CCAP articles 10.3 et 10.4",
  "commentaire": "Prix fermes et actualisables une seule fois avant démarrage (pas de révision en cours d'exécution). Favorable pour le candidat si délai entre remise des offres et démarrage dépasse 3 mois — protection contre la hausse des coûts matériaux."
 },
 "alertes_prix": [
  "Aucun montant estimatif publié dans les pièces disponibles (RC absent) — le candidat doit évaluer le volume de travaux de manière autonome via visite obligatoire et quantités DPGF à vérifier",
  "Les quantités de la DPGF sont données à titre indicatif (CCTP §1.0.1) — le candidat doit les vérifier et les modifier le cas échéant ; aucun supplément ne sera accepté après remise des offres pour erreur de quantité",
  "Travaux sur monuments historiques : surcoût potentiel lié aux prescriptions matériaux (pierres carrière, chaux naturelle, ardoises 1er choix) et aux essais de convenance obligatoires — à intégrer impérativement dans la DPGF",
  "Pas de négociation possible (AAPC : 'Possibilité d'attribution sans négociation : Non') — l'offre initiale doit être définitive et compétitive"
 ],
 "references_exigees": {
  "experience_minimale_annees": null, "experience_source": null, "volume_min_references_similaires": null, "volume_min_references_unite": null,
  "secteur_experience": "Travaux de restauration sur édifices présentant un intérêt historique ou architectural (techniques chaux, taille de pierre, couverture ardoise patrimoine, vitraux)",
  "secteur_source": "CCTP §0.2 — prescriptions applicables aux édifices classés MH",
  "certifications_obligatoires": [],
  "autres_exigences": [
   {"libelle": "Visite obligatoire sur site — prendre rendez-vous en mairie avant remise des offres", "source": "AAPC — conditions de participation"},
   {"libelle": "Mémoire technique avec note méthodologique décrivant précisément les points singuliers des ouvrages de chaque lot", "source": "CCTP §1.0.1 et §2.0.1"}
  ]
 },
 "dossier_candidature": {
  "pieces_a_fournir": [
   {"libelle": "Acte d'engagement (à compléter et signer)", "phase": "offre", "obligatoire": true, "source": "CCAP article 3"},
   {"libelle": "DPGF (Décomposition du Prix Global et Forfaitaire) par lot soumissionné", "phase": "offre", "obligatoire": true, "source": "CCAP article 3 et 9.1"},
   {"libelle": "Mémoire technique avec note méthodologique décrivant les points singuliers par lot", "phase": "offre", "obligatoire": true, "source": "CCTP §1.0.1, §2.0.1, §3.0.1"},
   {"libelle": "Calendrier d'exécution des travaux par lot", "phase": "offre", "obligatoire": true, "source": "CCAP article 3"},
   {"libelle": "Pièces relatives aux capacités du candidat (renvoi au RC)", "phase": "candidature", "obligatoire": true, "source": "AAPC — critères de participation : renvoi au RC"}
  ],
  "mode_remise": "dématérialisé", "plateforme_depot": null, "signature_electronique_exigee": null, "format_signature": null,
  "nombre_exemplaires": null, "langue": "français", "duree_validite_offres_jours": null, "modalites_source": "AAPC — modalités de remise des offres"
 },
 "lots": [
  {"numero": 1, "intitule": "Maçonnerie - Pierre de Taille", "domaine": "btp_renovation_rehabilitation", "zone_geographique": "Saint-Loup-des-Vignes (45340)",
   "volume_estime": null, "volume_estime_unite": null, "cout_estime_min_eur": 108000, "cout_estime_max_eur": 175000,
   "particularites": "Lot pilote : responsable des installations de chantier communes, échafaudages pour tous les lots, panneau de chantier, fluides. Inclut le drainage périphérique (fouilles, drain PVC DN100, géotextile, remblais). Techniques Monuments Historiques obligatoires : chaux aérienne/NHL, pierres de carrière identiques à l'existant, mortiers sans ciment. Index BT 03."},
  {"numero": 2, "intitule": "Charpente Couverture", "domaine": "btp_renovation_rehabilitation", "zone_geographique": "Saint-Loup-des-Vignes (45340)",
   "volume_estime": null, "volume_estime_unite": null, "cout_estime_min_eur": 48000, "cout_estime_max_eur": 65000,
   "particularites": "Réfection complète couverture ardoises épaisses 5mm à pureau décroissant sur volige sapin. Charpente en sous-œuvre. Faîtage plomb, épi zinc, gouttières zinc. Ardoises 1er choix avec certificat d'origine. Index BT 30."},
  {"numero": 3, "intitule": "Vitraux", "domaine": "btp_renovation_rehabilitation", "zone_geographique": "Saint-Loup-des-Vignes (45340)",
   "volume_estime": null, "volume_estime_unite": null, "cout_estime_min_eur": 9000, "cout_estime_max_eur": 18000,
   "particularites": "Travaux de maître verrier : reprise grisaille (nettoyage, révision plombs, repiquage verres, patine, maquette 1/10e) et raquettes de protection cuivre grillagé. Dossier des ouvrages exécutés type n°1 requis. Index BT 45. Coordination avec lot 1 pour scellement des raquettes."}
 ],
 "tranches": [
  {"type": "ferme", "numero": "TU", "intitule": "Tranche Unique", "objet": "Restauration extérieure nef et chœur et drainage façades nord, est et sud — ensemble des 3 lots.",
   "montant_estime_eur": null, "condition_affermissement": null, "source": "CCAP article 2.2"}
 ],
 "calendrier": {"date_limite_offres": "2026-07-18", "date_demarrage_prevue": null,
  "duree_marche": "Durée non précisée — de la notification jusqu'à expiration du délai de Garantie de Parfait Achèvement (CCAP art 8.1)"},
 "alertes_candidat": [
  "Visite obligatoire sur site avant remise des offres — prendre rendez-vous en mairie (condition de recevabilité à vérifier dans le RC non disponible)",
  "Travaux sur édifice à intérêt historique/architectural : les entreprises doivent maîtriser les techniques Monuments Historiques (chaux naturelle, pierre de taille, mortiers sans ciment, prescriptions LRMH) — compétences spécialisées requises",
  "Les quantités DPGF sont indicatives et doivent être vérifiées par les entreprises après visite — aucun supplément ne sera accordé après remise des offres pour insuffisance des quantités",
  "Approbation obligatoire des échafaudages par organisme de contrôle agréé avec certificat de conformité à remettre à l'Architecte — prévoir dans l'offre",
  "Mémoire technique obligatoire décrivant précisément les 'points singuliers' par lot — document évalué dans le critère de jugement des offres (exigence CCTP §1.0.1 et §2.0.1)",
  "Lot 1 est responsable des installations communes (échafaudages mis à disposition des autres lots) — la rémunération et la location pour la durée totale doivent être intégralement chiffrées dans la DPGF lot 1"
 ],
 "points_differenciants_attendus": [
  {"libelle": "Expérience démontrée en restauration de monuments historiques et maîtrise des techniques chaux traditionnelles",
   "exemple": "Un candidat lot 1 qui présente dans son mémoire technique des références récentes de restauration sur édifices MH, avec descriptif des mortiers de chaux utilisés, des fournisseurs de pierre de carrière et des résultats d'essais de convenance LRMH, se distinguera nettement d'un maçon généraliste.",
   "source": "CCTP §0.2, §1.0.6, §1.0.8"},
  {"libelle": "Méthodologie de gestion des interfaces entre lots (échafaudages, drainage, vitraux)",
   "exemple": "Le lot 1 étant responsable des installations communes pour tous les corps d'état, un candidat qui décrit précisément le phasage d'utilisation des échafaudages par chaque lot, les modalités de mise à disposition et les procédures de réception SPS apportera une valeur technique différenciante.",
   "source": "CCTP §0.3"},
  {"libelle": "Qualité et précision de la DPGF avec identification des ouvrages en recherche et des provisions pour aléas",
   "exemple": "Sur ce type de chantier patrimonial, les travaux 'en recherche' (remplacement pierres, reprise assemblages charpente) représentent une part variable. Un candidat qui justifie ses quantités prévisionnelles par une visite approfondie et propose des provisions adaptées aux risques de découverte sera mieux positionné.",
   "source": "CCTP §1.0.1, §1.3.2.2, §2.1.3"},
  {"libelle": "Présentation d'un plan d'installation de chantier clair et conforme aux exigences du CCTP",
   "exemple": "Le CCTP exige un plan d'installation de chantier approuvé par l'Architecte du Patrimoine avant démarrage, comprenant zones de stockage, circulations et réseaux. Un candidat qui intègre dans son offre un plan schématique préliminaire d'implantation des échafaudages adapté à la morphologie de l'église démontre sa préparation.",
   "source": "CCTP §0.3.2, §1.2.1"}
 ],
 "_meta": {
  "id_marche": "BOAMP-26-56606", "type": "complet",
  "date_generation": "2026-06-19T20:58:40.361418+00:00", "extraction_le": "2026-06-19T20:58:40.361418+00:00",
  "modele": "claude-sonnet-4-6", "preset_utilise": "btp", "presets_matches": ["btp", "ingenierie"],
  "prompts_versions": {"btp/_preset.json": "sha256:055bf6f8b2c1f771", "ingenierie/_preset.json": "sha256:b924b32a088673d6"},
  "tokens_input": 79920, "tokens_output": 7089, "cout_eur": 0.3288, "duree_sec": 128.3,
  "pdfs_traites": ["AWS-MPI-1832530-RC.pdf", "CCAP Église Saint Loup St Loup des Vignes 08 25.pdf",
                   "CCTP Église Saint Loup St Loup des Vignes 08 25.pdf", "MPI1832530_AAPC.pdf", "St Loup des Vignes DCE.pdf"]
 },
 "genere_avec_dce_complet": true,
 "_reextrait_v3": true,
 "prompt_version_sha": "8bc78dcbdd57"
}
```
Lecture pour le compagnon : la **visite obligatoire** n'apparaît que dans `autres_exigences`, dans
`contraintes_specifiques` et dans `alertes_candidat`. Il n'y a **aucun porteur**, **aucune
distinction mandataire / cotraitant**, **aucun lien** entre pièce et lot. Le routage a injecté le
bloc ingénierie (`caracteristiques_mission_moe` vide), parce que `presets_matches` vaut
`[btp, ingenierie]`.

#### 4.2.4 Schéma EXP (exp/gemini-batiment) : différences

Le mode document **réutilise le schéma prod** (fusion par le prompt prod) et ajoute
(`SUPPLEMENT_SOURCES` dans `exp_gemini/mode_document.py`) :

```jsonc
"_sources": {"<chemin.du.champ>": [{"document": "nom exact de la pièce", "page": "n° ou feuille"}]},
"complements_dce": {
  "visite": {"obligatoire": true, "modalites": "str"},
  "variantes": {"autorisees": true, "pse": "str"},
  "penalites": "str", "avance": "str", "retenue_garantie": "str", "delais_execution": "str",
  "normes_certifications": ["str"], "date_limite_questions": "str",
  "allotissement": "non alloti"          /* ajouté par le contrôle de complétude */
},
"_controle_completude": { /* par champ critique : présent / trouve_par_relance / absent_confirme */ }
```
Questions par type de pièce (étape 1), extrait :
`RC` : criteres_attribution, criteres_par_lot, pieces_candidature, pieces_offre, date_limite_remise,
date_limite_questions, **visite**, variantes, lots, montant_estime, forme_marche, duree_delais,
procedure, modalites_remise, conditions_participation.
`CCAP` : penalites, delais_execution, avance, retenue_garantie, revision_prix, paiement, assurances,
**sous_traitance** (« Règles de sous-traitance / cotraitance (solidarité du mandataire…) »),
reception_garanties, clauses_particulieres.
`CCTP`, `BPU_DPGF_DQE`, `AE`, `annexe` : cf. le code.
⚠️ En EXP, `sous_traitance` est **extrait par pièce mais n'est pas remonté** dans
`complements_dce` (il reste dans les notes intermédiaires `exp_traces_document`).

Exemple EXP (BOAMP-26-102054, `argon_document`, gemini-4-argon, 28 appels, 0,94 €) :
```json
"complements_dce": {"visite": {"obligatoire": false, "modalites": "Sans objet (aucune visite sur les lieux d'exécution n'est prévue au RC art. 2-3-3)."},
                    "variantes": {"autorisees": false, "pse": "Sans objet …"},
                    "penalites": "Cumulables et sans mise en demeure préalable … retard = 10 % du montant HT du BC par jour …"},
"_sources": {"dossier_candidature.pieces_a_fournir": ["…"], "complements_dce.visite": ["…"], "lots": ["…"]}
```

### 4.3 Matching / score de pertinence (`matching.evaluer`)

- Signature : `evaluer(organisme, marche, brief=None, presets_marche=None) -> dict`,
  `evaluer_tous(organisme, marches, briefs=None)`. **Déterministe, sans LLM.**
- Routage : profil legacy formation → `_evaluer_legacy` (V1) ; sinon `_evaluer_v2`.
- **Entrées** : le profil (socle + `profils_sectoriels`, `presets_priorites`, `domaines_couverts`,
  `zones_intervention`, `zones_strict`, `capacite_globale`), le marché (titre, objet, acheteur,
  `perimetre_geographique`, montant) et le brief (blocs sectoriels, `montant_marche`,
  `references_exigees`, `lots[].domaine`). Les presets du marché sont résolus via la classification.
- Motifs universels : `preset_compatibilite` (points par rang : 14/9/5), `domaines_couverts`,
  `thematique` (mots-clés du catalogue), `geographie` (département direct, région via
  `DEPARTEMENT_VERS_REGION`, `ACHETEUR_VERS_DEPARTEMENT`), `capacite_financiere`, `synergie`.
- Sectoriels : BTP (`_eval_btp_qualifications` avec verrou Qualibat, corps de métier, types
  d'ouvrages, capacité chantier), ingénierie (OPQIBI, assurances, typologies, compétences,
  ouvrages, capacité études), énergie renouvelable (`_eval_sectoriel_energie_renouvelable`).
  Les autres presets passent par un placeholder.
- Sortie : `{score, verdict ∈ (tres_pertinent ≥75, pertinent ≥50, a_verifier ≥20, non_pertinent),
  motifs[{critere, satisfait, points, commentaire, valeur_organisme, valeur_marche}], …}`.
  Un verrou go/no-go (−50) force `non_pertinent`.
- **Appelants** : `tendia_ui.py` (à la volée, tableau de bord et fiche), `tendia_dce.py:494`,
  [EXP] `compare_models.py`, des audits. Les caches `matchings` / `scores_matching` ne sont plus mis à jour.
- **Complément `matching_exigences.py`** : transforme `alertes_candidat` (texte) en statut
  `couvert / non_couvert / a_verifier / inconnu` par heuristiques de mots-clés (Qualiopi, local
  dans une ville, CA, BAC+N, NDA…), avec une `cle_canonique` qui se reporte d'un marché à l'autre via
  `profil.auto_reponses_exigences`. Il produit `verdict_eligibilite`. **Les heuristiques sont fortement
  héritées du secteur formation / France Travail** (villes FT, Qualiopi, DR).

#### 4.3.1 Données utilisées aujourd'hui pour proposer des marchés à une entreprise

Le tableau de bord (`/`) et l'Explorer appellent `matching.evaluer(profil_actif, marche, brief)`
sur les marchés de la base, à la volée. Le tableau suivant indique, pour chaque critère, le champ
du profil lu, le champ du marché ou du brief lu, et les points en jeu.

| Critère | Profil | Marché / brief | Points |
|---|---|---|---|
| `preset_compatibilite` | `presets_couverts`, `presets_priorites` | presets dérivés de `classifications_ia.domaines_metier` (ou de `brief.domaines_metier`) | +14/+9/+5 selon le rang ; −30 sans intersection ; **−50 si `presets_couverts` est vide** |
| `domaines_couverts` | `domaines_couverts` (hors schéma) | `brief.domaines_metier` (poids) | jusqu'à +28 ; −30 si hors spécialité ; 0 si non déclaré |
| `thematique` | `mots_cles_catalogue` | `marche.objet/titre` + **`brief.synthese_marche`** (texte LLM) | +18 (≥2 mots-clés) / +11 (1) / 0 |
| `geographie` | `zones_intervention`, `zones_strict` | `perimetre_geographique`, `acheteur_nom` → `ACHETEUR_VERS_DEPARTEMENT` | jusqu'à +25 |
| `capacite` | `capacite_globale.seuil_minimum_marche_eur`, `capacite_engagement_simultane` | **`brief.montant_marche.valeur_estimee_euros` uniquement** (ni `montant_3_voies`, ni `marches.montant_estime_eur`) | +10 / −10 / −20 ; 0 si le montant est absent |
| BTP `btp_qualibat` (verrou) | `profils_sectoriels.btp.qualifications.qualibat` | `brief.qualifications_requises.qualibat` (codes à 4 chiffres) | −50 (go/no-go) |
| BTP `btp_rge` / `btp_amiante` (MASE et ISO non lus) | `qualifications.rge.detenue`, `amiante.ss3/ss4` | `qualifications_requises.rge`, mentions amiante | −25 / −20 |
| BTP `btp_corps_metier` | `corps_de_metier` | `caracteristiques_techniques_chantier.corps_etat` (tokens) | ±, −5 si aucun corps commun |
| BTP `btp_types_ouvrages` | `types_ouvrages` | `typologie_ouvrage` (tokens) | jusqu'à +10 |
| BTP `btp_capacite_chantier` | `capacite_chantiers.montant_max_par_chantier` | montant | ± |
| `synergie` | — | preset + thématique + géo alignés | +10 |

Puis `matching_exigences.verdict_eligibilite(alertes_candidat, profil)` produit le verdict
d'éligibilité affiché. **L'historique DECP de l'entreprise n'est utilisé nulle part** (ni les
acheteurs connus, ni les renouvellements). La « taille de chantier » n'est prise en compte que via
`capacite` et `btp_capacite_chantier` (montant LLM).

#### 4.3.2 Origine de l'instabilité 32 / 39 / 57

**Reproduction hors ligne** (script en lecture seule sur `tendia_exp.db`, code de
`matching.py` issu de `git archive HEAD`, profil `demo_btp` = défaut de `compare_models.py`) :

```
BOAMP-26-56456 (presets=['btp'])
  claude_prod=54 (pertinent)  opus_global=57 (pertinent)  argon_global=39 (a_verifier)  argon_document=32 (a_verifier)
  ≠ thematique : claude_prod 18 | opus_global 11 | argon_global 18 | argon_document 11
      claude_prod   : « Match catalogue : 2 mots-cles (VRD, construction neuve) »
      opus_global   : « Match catalogue partiel : construction neuve »
  ≠ capacite   : claude_prod 0 | opus_global 10 | argon_global 10 | argon_document 10
      claude_prod   : « Montant marche inconnu » ; les autres : « Montant 756 000 EUR dans la capacite »
  ≠ btp_rge    : claude_prod – | opus_global – | argon_global −25 | argon_document −25
      argon_*       : « RGE exige mais non detenue »
BOAMP-26-102098 : claude_prod=20, opus_document=0, argon_document=0
  ≠ btp_rge −25 et btp_amiante −20 (Opus et Argon les détectent, pas Sonnet) ;
    btp_types_ouvrages 0 / +10 selon la formulation de typologie_ouvrage
```

**Diagnostic** : `matching.evaluer` est **déterministe** (même entrée, même sortie). L'écart vient
**entièrement des briefs**, qui diffèrent selon le modèle et le mode :
1. **booléens d'exigence** (`qualifications_requises.rge`, amiante) lus comme des verrous à −25 / −20 :
   un seul faux positif ou faux négatif fait varier le score de 25 points ;
2. **montant** : seul `montant_marche.valeur_estimee_euros` est lu (null chez Sonnet, 756 k€
   chez Opus et Argon) ;
3. **texte libre** : `thematique` recherche les mots-clés dans `synthese_marche`, que chaque
   modèle rédige différemment (±7 points) ;
4. **tokens** de `corps_etat` / `typologie_ouvrage` (libellés libres).

Les **seuils de verdict** (50 / 75) amplifient le tout : 54 donne `pertinent`, 39 donne
`a_verifier`. La vérité terrain (le RGE est-il réellement exigé dans 56456 ?) est à confirmer
dans l'onglet « Vérité terrain » de `compare_models.py`.

#### 4.3.3 Le matching avec un profil minimal (NAF + adresse + historique DECP)

Test hors ligne sur les **92 briefs BTP de prod** (presets ⊇ btp). Les profils ont été construits
en mémoire : rien n'a été écrit.

| Profil | Contenu | Verdicts sur 92 | Score moyen |
|---|---|---|---:|
| `profil_btp_demo` (complet) | socle + BTP complet | 6 pertinent · 31 à vérifier · 55 non pertinent | 17,8 |
| **min_A** | `naf_principal`, département du siège, `presets_couverts=["btp"]`, `zones_intervention=[dépt]`, BTP vide | 0 · 13 · 79 | 8,9 |
| **min_B** | min_A + 8 départements (zones déduites, par exemple de l'historique DECP) + 5 mots-clés (déduits des objets DECP) | 2 · 23 · 67 | 13,9 |

Motifs de min_A sur un marché : preset +14, géographie +10 ; **0** pour domaines, thématique,
capacité, corps de métier, types d'ouvrages et capacité chantier (« non renseignés »).

Motifs **négatifs** de min_A sur les 92 marchés : `geographie` 76 fois (hors du seul département
du siège), `btp_qualibat` 6 (verrou −50), `btp_amiante` 6, `btp_rge` 3. **Une qualification
absente du profil est traitée comme « non détenue »** : le profil minimal est donc pénalisé par
les verrous alors que l'information est seulement inconnue. Il n'existe pas d'état « inconnu → à
confirmer », pourtant nécessaire à l'étape 2 du compagnon.

**Conclusion** : le moteur **fonctionne** avec un profil minimal (pas d'erreur) mais il
**discrimine peu** et **confond inconnu et absent**. Ce qui manque :
- **NAF → preset et corps de métier** : **aucune table de correspondance n'existe** (le NAF
  n'est lu nulle part) ;
- **historique DECP → `zones_intervention`, `mots_cles_catalogue`, `types_ouvrages`, montants
  typiques, acheteurs connus** : aucun code ne le fait. `decp_marches` contient les éléments
  (département, CPV, objet, montant, acheteur ; cf. §8ter) ;
- **CPV DECP → `corps_de_metier`** : pas de correspondance (`decp/mapping_cpv.py` ne mappe que
  CPV → preset) ;
- un **critère « acheteur connu / renouvellement »** dans `matching.py` : il n'existe pas ;
- `capacite` : il faut le CA (comptes publiés, non intégrés) et un plafond par chantier
  (déductible du maximum DECP).

#### 4.3.4 Tool use et boucle conversationnelle

**Aucun appel LLM avec outils** (`tools=`, `tool_use`, `tool_choice`, `function_call` : 0 occurrence
hors venv) et **aucune boucle conversationnelle** (pas d'historique de messages, pas de rôle
`assistant` réinjecté). Tous les appels sont « one-shot » : un prompt, une réponse JSON. Les
relances existantes sont des retries (JSON invalide, sortie tronquée), pas un dialogue.

### 4.4 Client LLM

#### Prod : pas d'abstraction

| Usage | Fichier | Modèle | Appel | Timeout | Retries | Coût tracé |
|---|---|---|---|---|---|---|
| Brief | `llm_extract.py` | Sonnet 4.6 | `messages.stream` | aucun (streaming) | 2 tentatives, pause de 2 s | `_meta.cout_eur` + `llm_appels` |
| Classification | `tendia_classification.py` | Haiku 4.5 | `messages.create` | défaut SDK | interne au module (à confirmer) | `_meta.cout_eur` (pas `llm_appels`) |
| Brief light | `auto_brief.py` | Sonnet 4.6 | `messages.create` | défaut SDK | à confirmer | `_meta` |
| Calibration | `llm_calibration.py` | Sonnet 4.6 | `messages.create` ×2 | défaut SDK | à confirmer | `_meta` |
| DECP | `decp/classifier_llm.py` | Haiku 4.5 | `messages.create`, `max_tokens=50` | défaut | — | — |
| Mémoires | `services/_memoire_commun.appeler_llm`, `digest_memoire._appeler_llm` | Sonnet 4.6 | `messages.stream` | « pas de timeout, cf. préférence Younes » | relance si la sortie est tronquée ou non parsable (rédaction) | `_meta.cout_*` (pas `llm_appels`) |

- **Calcul du coût** : `budget.estimer_cout_eur(tokens_in, tokens_out)` (tarif Sonnet fixe,
  taux USD→EUR codé en dur) ; `tendia_classification` a sa propre table `PRICING`. Le coût de
  Haiku n'est donc pas calculé par `budget`. `llm_extract` affiche aussi `cout_usd = (in*3 + out*15)/1e6`.
- **Garde-fou** : `budget.peut_appeler_llm("extraction")` (kill switch, quota par jour, alerte
  mensuelle). `data/budget.json` : `actif=true`, `extraction_max_par_jour=574`,
  `calibration_max_par_jour=100`, `alerte_seuil_eur_mois=50`, `kill_switch_global=false`.
  **Seule l'extraction du brief** passe par ce garde-fou (`TYPES_VALIDES = {"extraction", "calibration"}`).
  La classification, les mémoires et les digests n'ont pas de quota (seulement `--max-cout` en CLI).
- **`llm_appels`** : 1 274 entrées, uniquement de type `extraction`, toutes en juin 2026 :

| type | modèle | statut | N | coût € | période |
|---|---|---|---:|---:|---|
| extraction | claude-sonnet-4-6 | ok | 1 212 | 427,71 | 10/06 → 22/06 |
| extraction | (null) | bloque_budget | 34 | 0 | 17/06 |
| extraction | claude-sonnet-4-6 | erreur | 28 | 1,88 | 11/06 → 22/06 |
| **Total** | | | **1 274** | **429,58** | |

  Somme des `_meta.cout_eur` des briefs actuels : 98,26 € (les ré-extractions écrasent les
  précédentes). Classifications : 6,33 €. Digests : 2,51 €. Mémoires : `_meta.cout_total_eur`
  (exemple : 1,26 € par mémoire), non additionné dans `_meta.cout_eur`.

#### EXP : `llm_router.py` + `config_llm.yaml`

```python
call_llm(task: "classif"|"analyse", prompt, documents=None, model=None, system=None,
         prompt_version=None, max_tokens=None, json_mode=…, journal=…) -> LLMResult
# LLMResult : ok, texte, json, modele, fournisseur, tokens_in, tokens_out, tokens_reflexion,
#             cout_eur, duree_s, finish_reason, sortie_tronquee, erreur …
```
- **Routage par tâche** : `resoudre_modele(task, model)`. Modèles par défaut (repli si non surchargés
  dans l'environnement) : `CLAUDE_MODEL_CLASSIF=claude-haiku-4-5`, `CLAUDE_MODEL_ANALYSE=claude-sonnet-4-6`,
  `GEMINI_MODEL_CLASSIF=gemini-3.1-flash-lite`, `GEMINI_MODEL_ANALYSE=gemini-4-argon`, `OPUS_MODEL=claude-opus-5-5`.
  Le fournisseur se déduit du nom du modèle (`fournisseur()`).
- **Timeouts** : `classif` 60 s, `analyse` 900 s (Claude : `Anthropic(timeout=…, max_retries=0)` ;
  Gemini : `HttpOptions(timeout=…)`).
- **max_tokens** : classif 800 (Claude) / 8 192 (Gemini) ; analyse 64 000 (Claude) / 32 768 (Gemini).
  Effort Opus 5.5 : `high`. Relance Gemini sur `MAX_TOKENS` avec `thinking_budget=16000`
  (repli sur `thinking_level=LOW`).
- **Retries** : 5 tentatives, backoff exponentiel de 2 s plafonné à 90 s ; réessai sur 429, 5xx,
  timeouts et erreurs réseau, avec lecture de `retryDelay`/`retry-after` (`_est_retentable`).
  Rate limit : 60 appels par minute et par modèle (verrou global).
- **Coût** : `estimer_cout_eur(modele, tin, tout)` = tarifs USD/M (`tarifs_usd_par_million`,
  avec palier long contexte si `seuil_long_contexte`) × `taux_usd_eur` (0,92). Tarifs
  configurés : haiku-4-5 1/5, sonnet-4-6 3/15, opus-5-5 4/20, gemini-3.1-flash-lite 0,25/1,5,
  gemini-3.5-flash-lite 0,30/2,5, gemini-4-argon 2/10 (⚠️ **doublé au 01/12/2026** selon le
  commentaire), gemini-3.1-pro-preview 2/12 (4/18 au-delà de 200 k).
- PDF natifs (Files API Gemini, 50 Mo max par PDF ; blocs `document` côté Claude) pour les scans.
- Journal : `exp_appels` (cf. §2.4).
- **Non branché sur la prod.** Le brancher remplacerait les 6 appels directs (cf. §10).

*(Suite : `architecture_actuelle_2026-11_partie2.md`.)*
