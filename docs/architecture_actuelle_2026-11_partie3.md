# Tendia : architecture actuelle (état au 2 novembre 2026), partie 3/3

> **Note (02/11/2026)** : §8ter.2 : le nom du titulaire est bien présent dans la DECP (titulaire_nom, 97 %), voir docs/rapport_sprint_decp_reprise.md

> Suite des parties 1 et 2. Contenu : §8 Configuration et exploitation, §8bis Mails,
> notifications et tâches planifiées, §8ter Historique DECP, attributions et suivi des dossiers,
> §9 Dette et ménage, §10 Points d'accroche du compagnon.

---

## 8. Configuration et exploitation

### 8.1 Variables d'environnement (noms seulement)

| Variable | Usage | Lue par |
|---|---|---|
| `ANTHROPIC_API_KEY` | API Claude | SDK `anthropic` ; `llm_extract._obtenir_cle_api` (lit aussi `.env` à la main) |
| `TWOCAPTCHA_API_KEY` | captchas | aws, dematis, xmarches… |
| `GEMINI_API_KEY`, `GEMINI_MODEL_CLASSIF`, `GEMINI_MODEL_ANALYSE` | [EXP] | `llm_router` |
| `TENDIA_PROXY_URL` | proxy résidentiel | `http_humain` |
| `TENDIA_PROXY_FOR_<PLATEFORME>` (`PLACE`, `DATA_GOUV`, `BOAMP`, `ATEXO`, `ACHATPUBLIC`, `DEMATIS`, `AWS_ACHAT`) | `=0` désactive le proxy pour une plateforme | `http_humain._proxy_pour_plateforme` |
| `TENDIA_DL_RAISON_SOCIALE`, `TENDIA_DL_SIRET`, `TENDIA_DL_SIREN`, `TENDIA_DL_NOM`, `TENDIA_DL_PRENOM`, `TENDIA_DL_EMAIL`, `TENDIA_DL_TEL`, `TENDIA_DL_ADRESSE`, `TENDIA_DL_CP`, `TENDIA_DL_VILLE` | identité déclarée dans les formulaires de téléchargement | downloaders (absentes de `.env` → valeurs par défaut du code, à confirmer) |
| `TENDIA_CONVERSION` | `office` / `libreoffice` | [EXP] `exp_gemini/pieces.py` |
| `PYTHONUTF8=1` | requis selon `docs/operations.md` | environnement |

`.env` contient : `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `TWOCAPTCHA_API_KEY`, `TENDIA_PROXY_URL`,
`TENDIA_PROXY_FOR_PLACE`, `TENDIA_PROXY_FOR_DATA_GOUV`, `TENDIA_PROXY_FOR_BOAMP`,
`TENDIA_PROXY_FOR_ATEXO`, `TENDIA_PROXY_FOR_ACHATPUBLIC`. Aucune variable de chemin ;
**aucune variable de mail (SMTP, API) ni de notification**.

### 8.2 Fichiers de configuration

`presets/**`, `data/budget.json`, `config_llm.yaml` [EXP], `requirements.txt`, `.gitignore`.
Constantes en dur : `llm_extract.MODELE / MAX_TOKENS_REPONSE / MAX_CHARS_INPUT`,
`tendia_classification.MODELES / PRICING`, le taux USD→EUR de `budget.py`, les seuils de `matching.py`.

### 8.3 Logs

- `logs/<downloader>_<date>.jsonl` (`tendia_logs` : achatpublic, atexo, aws-achat, dematis,
  dce-finder), le dernier datant du **03/07/2026**, plus de nombreux logs ad hoc (`ms_*.log`,
  `reprise*.log`, `ui_server.log`…).
- `data/*.log`, `rapports/` (dernier `marches_actifs_<date>.md` : **2026-07-01**).
- `print` dans la console, aucun module `logging`. Journal LLM : `kv_storage[llm_appels]` (extraction seulement).

### 8.4 Sauvegardes

Manuelles uniquement : ~20 copies `data/tendia.db.backup_*` / `.bak_*` (juin), 341 dossiers
`data/dce/*.bak_avant_*`, des sauvegardes **dans les données** (`briefs_extraits/<id>.bak_*`,
`brief_v1_backup`), `backups/`, `presets/*/_preset.json.bak_*`. Le mode WAL impose un
`PRAGMA wal_checkpoint(TRUNCATE)` avant la copie. Aucune sauvegarde automatique ni externalisée,
et `data/` est hors git.

### 8.5 Tests

23 scripts dans `tests/` (sans pytest, qui n'est pas installé). Ils ont été lancés sur une copie
(`git archive HEAD`) avec `socket.connect`, `create_connection` et `getaddrinfo` neutralisés,
les clés API retirées et un timeout de 120 s. Aucun test n'utilise la vraie base ; le LLM est
simulé par un faux client.

| Test | Résultat |
|---|---|
| atexo_downloader 25 · boamp_contact 15 · boamp_enrichissement 33 · briefs_versioning 13 · dce_finder 24 · decp_classifier_cpv 19 · decp_classifier_llm 14 (faux client) · decp_db 13 (base temporaire) · decp_mapping_cpv 42 · decp_matching 32 · decp_parser 25 · dematis_downloader 35 · dematis_workflow_har 51 · downloader_dce_directe 12 · extraction_v2_criteres 26 · extraction_v2_montants 14 · http_humain 37 · llm_extract_routage 28 · proxy_par_plateforme 14 | ✅ (19 scripts, 472 assertions) |
| **test_qualifier_dce** | ❌ 9 OK / 1 KO : « ZIP contenant RC + CCTP » attend `['CCTP','RC']`, obtient `['CCTP','DCE','RC']` (le type `DCE` consolidé ajouté au commit `1920a94` n'a pas été répercuté dans l'attente) |
| **test_parseur_dce** | ❌ `ModuleNotFoundError: bs4` |
| **test_parallelisation** | ❌ `ModuleNotFoundError: reextraire_briefs_v2` (le script a été déplacé par le refactor `997f191`) |
| **test_aws_downloader** | ⏱️ bloqué au-delà de 120 s sans réseau (le contournement CDN `_session_sans_proxy` contourne le mock) |

`HAR/tests/` contient une copie obsolète de 11 tests.

---

## 8bis. Mails, notifications et tâches planifiées

### 8bis.1 Envoi de mails

**Rien n'existe.** Aucune occurrence de `smtplib`, `email.mime`, SendGrid, Mailjet, Brevo/Sendinblue,
Gmail API, Microsoft Graph/Outlook ou OAuth dans le code (hors venv). Les seules occurrences de
« outlook »/« gmail » sont dans des **contenus extraits de DCE** (`data/extractions/…`,
`data/validation_*`). Aucune variable d'environnement ni dépendance de mail. Aucun modèle de mail.

### 8bis.2 Lecture de boîte mail

**Rien** (ni `imaplib`, ni `poplib`, ni Graph, ni Gmail API).

### 8bis.3 Notifications

**Rien** (ni Telegram, ni Slack, ni webhook, ni SMS, ni push). Les seules « notifications » sont
les messages `flash` de l'UI Flask et les `print` des scripts.

### 8bis.4 Tâches planifiées et boucles

| Élément | État réel |
|---|---|
| Planificateur de tâches Windows | **Aucune tâche Tendia/Python** dans `schtasks /query`. |
| `docs/cron_windows.md` | Procédure (interface ou `schtasks`) pour lancer `retelecharger_aws_achat_anti_ban.py --oui` le lundi, le mardi et le mercredi à 9 h. **Non appliquée.** **Chemins périmés** (`C:\Users\…\Tendia`, alors que le repo est dans `D:\projects\tendia`). |
| `Tendia.bat` | lancement manuel : pipeline puis UI |
| Boucles `while True` | uniquement de la pagination (`connecteurs/boamp.py:786`), de l'inventaire (`exp_gemini/pieces.py:283`) et du comptage de tokens Gemini (`llm_router.py:359`). **Aucun démon ni scheduler** (ni `schedule`, ni APScheduler, ni Celery/RQ, ni `threading.Timer`). |
| Threads de l'UI | seulement les jobs de génération de mémoire (`_MEMOIRE_JOBS`, en mémoire) |
| Garde-fous temporels | `http_humain.heure_actuelle_est_bureau()` (8 h-19 h lun-ven) dans les batchs anti-ban : c'est une contrainte d'exécution, pas une planification |

**Conséquence pour les étapes 5 et 7** (relances des partenaires, alertes d'expiration de pièces,
suivi des attributions et des renouvellements) : l'envoi de mails, la planification et la
file de tâches sont **entièrement à créer**.

---

## 8ter. Historique DECP, attributions et suivi des dossiers

### 8ter.1 Les marchés gagnés par un SIREN dans `decp_marches`

**Oui, c'est possible dès aujourd'hui**, avec deux limites : la fenêtre est de **12 mois**
(`date_notification` du **15/06/2025 au 15/06/2026** ; aucune ingestion depuis le 16/06/2026), et le
SIREN doit être retrouvé dans un SIRET.

**Requête 1 : titulaire principal, indexée**
```sql
-- utilise idx_decp_titulaire (plage sur le préfixe SIREN)
SELECT id, date_notification, montant_eur, cpv_principal, departement, acheteur_siret, acheteur_nom, objet
FROM decp_marches
WHERE titulaire_siret >= :siren AND titulaire_siret < :siren || '~';
-- EXPLAIN : SEARCH decp_marches USING INDEX idx_decp_titulaire (titulaire_siret>? AND titulaire_siret<?)
```
Temps mesuré : **0,0 à 0,1 ms**.

**Requête 2 : titulaire OU membre d'un groupement / multi-attributaire**
```sql
SELECT … FROM decp_marches
WHERE titulaire_siret LIKE :siren || '%' OR titulaires_json LIKE '%' || :siren || '%';
-- EXPLAIN : SCAN decp_marches   (scan complet de 142 735 lignes)
```
Temps mesuré : **~33 ms**. C'est acceptable en unitaire, mais pas pour du calcul en masse
(16 226 SIREN BTP).

**Index et structures manquants** :
- `LIKE 'xxx%'` n'utilise **pas** `idx_decp_titulaire` (LIKE est insensible à la casse) : utiliser
  la forme en plage, ou une colonne `titulaire_siren` (9 caractères) indexée ;
- `titulaires_json` (texte JSON) n'est pas indexable. Il faut une table de jointure
  `decp_titulaires(decp_id, siret, siren, rang)` indexée sur `siren` (en Postgres : table dédiée,
  ou `JSONB` + index GIN) ;
- éventuellement un index composite `(acheteur_siret, cpv_principal, date_notification)` pour les
  renouvellements.

**Résultat sur 3 SIREN BTP tirés au hasard** (graine 42, parmi les 16 226 SIREN titulaires de
marchés classés `btp`) ; SIREN masqués :

| SIREN | Requête 1 | Requête 2 | Montant cumulé | Acheteurs distincts | Départements | Exemples (date · montant · CPV · acheteur · objet) |
|---|---:|---:|---:|---:|---|---|
| 418****** | 4 | 4 | 330 036 € | 1 | 30 | 2025-12-03 · 154 818 € · 45454100 · SOC HLM « Un toit pour tous » · « Réhabilitation - résidentialisation… » (**ligne apparaissant 2 fois**) ; 2025-06-27 · 10 200 € · 45454000 · même acheteur · « Travaux avant vente – couverture tuiles – électricité » (**2 fois**) |
| 392****** | 5 | 5 | 913 702 € | 2 | 87 | 2026-05-06 · 42 915 € · 45311200 · OPH 87 · « Construction de 7 logements… » ; 2026-02-12 · 765 167 € · 45000000 · OPH 87 · « Construction de 6 pavillons PMR » (**en groupement / multi-titulaires**) ; 2026-01-27 · 7 620 € · Département de la Haute-Vienne |
| 329****** | 4 | **5** | 483 224 € | 2 | 42, 85 | 2026-06-04 · 81 547 € · 45000000 · CHU · « Sécurisation portes coupe-feu – Lot 06A Serrurerie » ; 2026-06-01 · 291 637 € · 45232410 · CC Vendée Grand Littoral · « LOT02 … » (**présent seulement via `titulaires_json`**) |

Constats : (1) la requête 2 retrouve des marchés que la requête 1 manque (groupements) ;
(2) il existe des **doublons apparents** (même date, même montant, même objet, `id` différents :
modifications ou republications de la consolidée ?), qu'il faut dédoublonner (à confirmer) ;
(3) la donnée suffit à reconstituer **références, acheteurs connus, zones et montants typiques**
(étape 1 du compagnon).

### 8ter.2 Champs DECP disponibles et taux de remplissage réel

`decp_marches` (142 735 lignes, dont 50 888 classées `btp`) :

| Champ | Total | BTP |
|---|---:|---:|
| `objet` | 100 % | 100 % |
| `cpv_principal` | 100 % | 100 % |
| `acheteur_siret` | 100 % | 100 % |
| `acheteur_nom` | 98,9 % | 98,8 % |
| `titulaire_siret` (1er titulaire) | 99,4 % | 99,3 % |
| `titulaires_json` (liste lorsqu'il y a plus d'un titulaire) | 11,6 % | 10,7 % |
| `montant_eur` | 99,9 % (89 null, 370 à zéro) | 99,9 % |
| `date_notification` | 100 % | 100 % |
| `duree_mois` | 99,9 % | 99,9 % |
| `procedure` | 100 % | 100 % |
| `lieu_execution_code` | 100 % | 100 % |
| `departement` / `region` | 98,8 % | 98,8 % |
| `cpv_secondaires` | **0 %** (toujours NULL) | 0 % |

Qualité de `titulaire_siret` : 139 784 valeurs à 14 chiffres, 1 326 à 5 caractères, 130 à 11,
119 à 13, 880 NULL. `titulaires_json` contient des valeurs parasites (`"00001"`, `"478826159franc"`,
SIREN à 9 chiffres).

**Champs absents de la table** : **nom du titulaire** (la docstring de `connecteurs/decp_consolidee.py`
évoque un `titulaire_nom` natif, mais il n'est pas stocké), **rôle dans le groupement**
(mandataire ou cotraitant ; la DECP consolidée ne distingue pas un groupement d'un accord-cadre
multi-attributaire, à confirmer), **type de groupement**, **numéro de lot**, **nature** du marché
(travaux/services/fournitures, déductible du CPV 45*), **forme de prix**, **nombre d'offres
reçues**, **modifications**, **sous-traitance déclarée**. `parse_warnings` : 253 lignes.

Volumes mensuels (notification) : de 2 514 (juin 2026, partiel) à 19 580 (décembre 2025).

### 8ter.3 `marche_attribution_link` : schéma, alimentation, pourquoi elle est vide

Schéma : partie 1 §2.2 (`marche_tendia_id`, `decp_id`, `score_total`, `score_cpv`,
`score_acheteur`, `score_periode`, `score_montant`, `statut DEFAULT 'auto'`, `created_at`,
`UNIQUE(marche_tendia_id, decp_id)`).

Code prévu :
- `decp/matching.py` : `scorer_match(marche_tendia, attribution_decp)` avec les poids
  **CPV 0,30, acheteur (SIREN) 0,35, période 0,20, montant 0,15** (redistribués si le montant est
  absent), `SEUIL_CANDIDAT=0,70`, `SEUIL_FORT=0,85`. `score_periode` vaut 0 si la notification est
  **antérieure** à la publication, 0,5 entre 0 et 30 jours, 1 entre 1 et 18 mois, puis décroît
  jusqu'à 36 mois ;
- `decp/db.inserer_lien` (INSERT OR IGNORE) ;
- **seul appelant** : `scripts/decp/decp_test_matching.py` (« Sprint DECP 1, Étape 3 (test
  bidirectionnel) »), qui insère les liens `matched` d'un **échantillon** (`--n 50`) après
  `verifier_marche_tendia_existe`.

**Pourquoi elle est vide** : (1) l'unique alimentation est un **script de test** sur échantillon,
et aucun traitement batch ni pipeline ne l'appelle ; (2) **structurellement**, les avis BOAMP en
base sont publiés **à partir de juin 2026**, alors que la DECP s'arrête au **15/06/2026**. Une
attribution DECP est donc presque toujours **antérieure** à l'avis, `score_periode = 0`, et le
seuil de 0,70 est inatteignable. Que le script ait jamais tourné reste à confirmer (aucun rapport
retrouvé dans `rapports/`).

Autre mécanisme (legacy France Travail) : `jointure.py` et `data/jointure.json`, une jointure
par **référence acheteur interne** (`reference_ft` côté BOAMP). Il compte **391 entrées, toutes en
`etat = "boamp_seul"`, 0 avec DECP**. Il est alimenté par `tendia_recup.py` (côté BOAMP) ;
l'alimentation côté DECP était dans `scripts/_archive/tendia_decp.py` (archivé). C'est le fichier
modifié non commité.

### 8ter.4 Taux de rapprochement actuel DECP ↔ BOAMP (mesuré)

Méthode : avis de marché (hors avis d'attribution) ayant un `acheteur_siren`, comparés aux lignes
DECP de même SIREN acheteur (9 premiers chiffres du SIRET). « Match probable » : notification
≥ date de publication **et** au moins 2 tokens d'objet communs **et** même division CPV (si le CPV
est connu).

| Mesure | Total | Travaux (`type_marche=TRAVAUX`) |
|---|---:|---:|
| Avis de marché | 2 792 | 887 |
| … avec `acheteur_siren` | 1 341 sur 3 039 marchés (44 %) | **183 / 1 013 (18 %)** |
| Acheteur présent dans la DECP (même SIREN) | 699 | 94 |
| DECP du même acheteur **postérieure** à l'avis | 24 | 3 |
| **Match probable (attribution retrouvée)** | **4** | **0** |
| Contrat DECP **antérieur** du même acheteur avec ≥3 tokens d'objet communs (**candidat « renouvellement / marché précédent »**) | **322** | **49** |

Lecture : **le rapprochement « attribution » est aujourd'hui inopérant** (fenêtres disjointes, et
`acheteur_siren` absent sur 82 % des travaux). En revanche, le croisement « **marché précédent du
même acheteur** » fonctionne déjà sur 322 avis (49 en travaux), ce qui sert directement à
**anticiper les renouvellements** et à identifier le **titulaire sortant** (étape 7). Pour
mesurer les attributions, il faudra **réingérer la DECP en continu** (après juin 2026) et
**compléter `acheteur_siren`** (à partir de `donnees` eForms, ou par recherche Sirene sur le nom).

### 8ter.5 Avis d'attribution BOAMP / TED

- **BOAMP : oui, ingérés par effet de bord**, dans la collection `marches`, avec
  `notice_type = "10 | 6"` (nature « ATTRIBUTION », « Résultat de marché ») : **247 avis**, dont
  **126 en travaux**. Ils sont mélangés aux avis de marché, sans traitement spécifique (ni
  filtrage systématique, ni extraction du titulaire et du montant).
- Le champ ODS `titulaire` (dans `donnees_boamp_brut`) n'est renseigné que sur **30 / 247** avis
  (et ne contient que des **noms**, par exemple `["COMEDIART"]`, sans SIRET ni montant). Le champ
  `donnees` (eForms/JSON détaillé) est présent sur tous les avis : il **contient probablement**
  les lauréats et les montants (`cac:TenderingParty`, `LegalMonetaryTotal`) pour les avis eForms,
  mais **aucun parseur ne l'exploite** (à confirmer par inspection).
- **TED : aucun connecteur** (ni avis de marché, ni avis d'attribution).

### 8ter.6 Statut de dossier client

- **`cycle_marche.py`** : champ `marches/<id>.cycle` avec les statuts `a_evaluer`, `candidate`,
  `gagne`, `perdu`, `abandonne`, un graphe de transitions et un historique. Route
  `POST /marche/<id>/cycle`. **Écriture par `stockage.sauver("marches")`** (réécriture complète).
  **Utilisation réelle : 0 marché** n'a de champ `cycle`.
- Il ne porte **pas** de notion de « déposé », de note obtenue, de motif de rejet, de lot ni
  d'entreprise (mono-profil) : c'est un suivi par marché, pas par dossier (entreprise × marché × lot).
- `marches_attribues.py` (collection `marches_tendia_attribues`, « marchés vus ouverts dont
  l'attribution DECP a été capturée ex post ») : la collection est **absente** de la base.

---

## 9. Dette et ménage (constat, rien n'a été supprimé)

### 9.1 Fichiers ou scripts morts, dupliqués ou expérimentaux

| Élément | Statut | Justification |
|---|---|---|
| `pipeline_france_travail.py` | [MORT/proto] | importé par personne ; chaîne spécifique France Travail |
| `test_grille_notation.py` (racine) | [proto] | « PROTOTYPE » ; il a écrit les clés `briefs_extraits/<id>.grille_brute` et `.bak_avant_grille` dans la base de prod (le prototype a été intégré au prompt v3 sous la forme `grille_actions`) |
| `place_downloader.py` | dupliqué | ancêtre de `atexo_downloader.py`, encore importé par `tendia_pipeline` |
| `analyse.py` | ambigu | n'est plus importé par l'UI ; `scores_matching` est figée depuis le 11/06 |
| `jointure.py` + `data/jointure.json` | legacy | jointure par `reference_ft` (France Travail) ; 391 entrées, 0 DECP |
| collection `matchings` | [MORT] | aucun écrivain ni lecteur |
| collections déclarées mais absentes (`marches_notifies`, `marches_tendia_attribues`, `titulaires`, `briefs_calibres`) | fantômes | lues par `/concurrence`, `/decp`, `llm_calibration`, qui reçoivent du vide |
| table `marche_attribution_link` | vide | §8ter.3 |
| `briefs_extraits/*.bak_*`, `.grille_brute` (235 clés) et `brief_v1_backup` (115 briefs) | sauvegardes dans les données | près de la moitié de la collection |
| `data/tendia.db.backup_*` (~20), `data/dce/*.bak_*` (341), `*.bak` de presets et de templates | sauvegardes manuelles | disque |
| `scripts/_archive/` (~35 fichiers, dont `enrichissement_sirene.py`, `tendia_decp.py`) | archivé | |
| `HAR/tests/`, `venv/`, `data/debug_*.html`, logs ad hoc | doublons, jetables | |
| `docs/cron_windows.md` | doc obsolète | chemins périmés, jamais appliquée |
| `presets/_actif.json` (= formation) | legacy | repli du vocabulaire de prompt |
| [EXP] `llm_router.py`, `config_llm.yaml`, `exp_gemini/`, `batch_gemini_batiment.py`, `compare_models.py`, 2 scripts d'audit, `exp_gemini/ui_exp.py` (non suivi) | expérimental | isolé |

### 9.2 Bugs connus et anomalies (pas de `TODO`/`FIXME` littéral dans le code)

1. **Pipeline LLM arrêté** depuis le 22/06 ; `tendia_classification` **hors pipeline** → 1 992
   marchés d'octobre sans classification ni brief.
2. **Extraction prod lacunaire** (`.doc`/`.xls`/`.odt`/`.rtf`, sous-dossiers, scans ; troncature
   à 400 000 caractères ; jusqu'à 49 % non lus). Cas observé : un RC présent mais « non
   disponible » pour le LLM (BOAMP-26-56606).
3. **Dépendances manquantes** : `beautifulsoup4`, `curl_cffi`, `python-dotenv`.
4. **`stockage.sauver("marches")`** global (58 Mo) dans `tendia_telecharger_dce` et `cycle_marche`.
5. **Cache par processus** de `stockage` : risque de données périmées dans l'UI.
6. **Lien actif du profil rompu** ; `/exigence/repondre` n'écrit pas dans la bibliothèque.
7. **Profil réel avec des valeurs estimées non marquées** (CA, fonds propres) ; `domaines_couverts` en triple.
8. **Le matching confond « inconnu » et « non détenu »** (verrous déclenchés sur un profil vide).
9. **Score sensible aux variations du LLM** (booléens d'exigence, `synthese_marche` en texte libre,
   montant lu dans un seul champ).
10. **`decp_classification`** : codes `conseil_rd` et `enr` ≠ codes de presets.
11. **DECP** : doublons apparents, `titulaires_json` sale, pas de nom de titulaire, ingestion
    arrêtée le 16/06.
12. **`acheteur_siren` absent** sur 56 % des marchés (82 % des travaux).
13. **Avis d'attribution** mêlés aux avis de marché, non exploités.
14. **`dce_contenu = "rien"`** (45) non documenté ; **8 briefs orphelins**.
15. **Coût LLM partiellement tracé** (seule l'extraction est dans `llm_appels`).
16. **`post_traiter_extraction_v2`** n'est pas appelé par `tendia_extraire`.
17. **4 tests cassés** ; pas de pytest ni de CI.
18. **`matching_exigences`** centré sur la formation / France Travail.
19. **Enum `presets_couverts`** du socle limité à 6 presets (14 existent).
20. **Jobs mémoire** en mémoire (perdus au redémarrage).
21. **`decp/db.py`** code le chemin de la base en dur ; pas de `busy_timeout`, pas de verrou optimiste.
22. **Tailwind compilé sans chaîne de build** dans le repo.

### 9.3 Incohérences entre `docs/passation_claude.md` (15/06) et le code

| Passation | Réalité au 02/11 |
|---|---|
| 422 marchés, 102/232 briefs, 6 presets, 56 domaines | 3 039 marchés, 239 briefs (+235 sauvegardes), 14 presets (4 avec `_schema.json`), 64 domaines |
| BOAMP + TED (aussi dans `Tendia.bat` et `tendia_pipeline.py`) | **aucun connecteur TED** |
| Décision 5 : DECP en requête à la volée, pas d'ingestion | **142 735 contrats ingérés** + classification |
| Piège 2 / §8 : `data/profil_organisme.json`, `data/profils/…` | profils en KV ; ces fichiers n'existent pas |
| Piège 3 : briefs disque dans `data/extractions_calibrees/` | copie des briefs dans `data/extractions/` |
| DCE dans `data/dce_archives/` | `data/dce/` (jonction) |
| `.env` = `ANTHROPIC_API_KEY` ; `budget.json` à la racine | + `TWOCAPTCHA_*`, `GEMINI_*`, `TENDIA_PROXY_*` ; `data/budget.json` |
| `enrichir_complet.py`, `tendia_matcher.py`, `tendia_veille.py` actifs | archivés |
| Scripts et `tests_*.py` à la racine | `scripts/*` et `tests/test_*.py` (refactor `997f191`) |
| curl_cffi installé | non installé |
| Timeout SDK laissé par défaut | `llm_extract` en streaming |
| Mémoires, `matching_exigences`, extraction v2/v3, `dossier_candidature`, `tranches` | absents de la passation |
| Main = `feat/decp-sprint-1` | prod = `feat/decp-sprint-3` |
| `dce_contenu` à 6 niveaux | + `rien` |
| « Section `tranches` absente » | présente (20 briefs) |

---

## 10. Points d'accroche du compagnon

Pour chaque étape : **existant** (fichiers et fonctions), **réutilisable** (tel quel / à
étendre), **à créer**, **risques**. L'ordre de construction recommandé est donné en §10.9.

### 10.1 Étape 1 : SIREN → profil pré-rempli (données publiques + historique DECP)

- **Existant** : `decp_marches` (12 mois, 99 % de SIRET titulaire, montant, CPV, département,
  acheteur) avec `idx_decp_titulaire` ; requêtes du §8ter.1 ; schéma du socle et schéma BTP
  (`presets/_socle_profil_organisme.json`, `presets/btp/_schema.json`) ;
  `organisme.template_profil_complet(["btp"])`, `creer_profil_bibliotheque`, `profil_form.parse` (fusion) ;
  `decp/mapping_cpv.py` (CPV → preset) ; `matching.DEPARTEMENT_VERS_REGION` ; script archivé
  `enrichissement_sirene.py` (appel recherche-entreprises + cache).
- **Réutilisable** : `enrichissement_sirene._appeler_api` (à étendre à tous les champs :
  activité/NAF, adresse, tranche d'effectif, dirigeants, établissements, et éventuellement les
  données RGE et finances que l'API expose, à confirmer) ; `http_utils.get_json` (politesse) ;
  `template_profil_complet` ; `scorer_match`/`siren_de` pour les identifiants.
- **À créer** : un connecteur `entreprises/` (Sirene, RGE ADEME, comptes publiés INPI/RNE, à
  confirmer selon les API disponibles) avec cache ; `historique_decp(siren)` (titulaire +
  groupements, dédoublonnage, agrégats : références, acheteurs, zones, montants, CPV) ;
  correspondances **NAF → preset et corps de métier** et **CPV 45* → corps de métier** ; table
  `entreprises` + `profil_faits` (source, date, confiance) ; projection vers le JSON du socle
  (compatibilité §5.10) ; normalisation des `titulaires_json` (table `decp_titulaires`) ; reprise
  de l'ingestion DECP en continu (`python -m decp.cli ingest --depuis 2026-06-16`, réseau).
- **Risques** : DECP sur 12 mois seulement et arrêtée le 16/06 ; doublons ; groupement et
  multi-attributaire indistinguables ; pas de nom de titulaire (Sirene nécessaire) ; RGPD sur les
  dirigeants ; limites de débit des API publiques.

### 10.2 Étape 2 : marchés à cibler (verdict « à confirmer »)

- **Existant** : `matching.evaluer` (V2, déterministe), UI tableau de bord et Explorer, presets,
  `classifications_ia`, `briefs_extraits` ; le croisement « contrat DECP antérieur du même
  acheteur » est mesuré (322 avis).
- **Réutilisable** : `_evaluer_v2` et les évaluateurs BTP ; la géographie (dépt/région) ;
  `capacite` ; le tri et les filtres de l'Explorer.
- **À étendre** : un état **« inconnu »** distinct de « non détenu » dans les verrous (sinon le profil
  minimal est pénalisé à tort, §4.3.3) ; la lecture du montant dans `montant_3_voies` et dans
  `marches.montant_estime_eur` ; des signaux **structurés** plutôt que `synthese_marche` ; des
  critères **acheteur connu** et **renouvellement** (DECP) ; un verdict à 3 états (à confirmer /
  éligible / non éligible).
- **À créer** : relancer **classification et brief** sur le stock (le pipeline LLM est arrêté depuis
  juin ; 1 992 marchés en attente) ; résolution des DCE du stock d'octobre ; calcul et cache des
  scores par entreprise (table).
- **Risques** : instabilité du score due au LLM (±25 points) ; coût de rattrapage LLM
  (~0,33-0,65 € par brief complet × N) ; `acheteur_siren` absent sur 82 % des travaux.

### 10.3 Étape 3 : questions d'éligibilité classées par nombre de marchés débloqués, puis verdict

- **Existant** : `matching_exigences.evaluer_exigence / evaluer_alertes / verdict_eligibilite`
  avec des **clés canoniques** (`ca_min_<montant>`, `local_<ville>`, `qualification_bac3`…) et
  `auto_reponses_exigences` (réponse mémorisée et reportée aux autres marchés), boutons Oui/Non
  AJAX dans la fiche (`POST /exigence/repondre`).
- **Réutilisable** : le **principe** de la clé canonique partagée entre marchés (c'est exactement
  le levier « une réponse débloque N marchés »), l'interface Oui/Non, le stockage des réponses.
- **À étendre / créer** : une extraction **structurée** des critères d'éligibilité dans le brief ou
  dans un extracteur dédié (CA minimum numérique, qualifications avec codes, références : nombre,
  montant, ancienneté ; effectif ; assurances), au lieu de regex sur `alertes_candidat` ; une
  normalisation BTP des clés (Qualibat <code>, RGE, décennale, CA ≥ X) ; un **classement des
  questions par nombre de marchés débloqués** (agrégation sur les marchés ciblés) ; un verdict
  « éligible en groupement » (règles de cumul des capacités, qualification par lot) ; une
  traçabilité (exigence → source DCE → réponse → fait du profil).
- **Risques** : heuristiques actuelles orientées formation ; critères mal extraits (RC non lu,
  cf. 56606) ; règles de groupement juridiquement délicates.

### 10.4 Étape 4 : matrice pièce × porteur × phase × lot, avec page citée et liens

- **Existant** : `dossier_candidature.pieces_a_fournir[{libelle, phase candidature/offre,
  obligatoire, source}]` (2 440 pièces sur 209 briefs), `references_exigees.certifications_obligatoires`,
  `lots`, `allotissement` ; [EXP] mode document : questions par type de pièce (`pieces_candidature`,
  `pieces_offre`, `visite`, `conditions_participation`, `criteres_par_lot`, `sous_traitance`,
  `assurances`), sources **pièce + page + extrait** (`_sources`), contrôle de complétude ;
  [EXP] `exp_gemini/pieces.py` (inventaire complet, conversion, typage, pages) ; filtrage par lot
  des mémoires (§6.3).
- **Réutilisable** : `pieces.py` et `mode_document.py` (à promouvoir en prod), `llm_router`
  (multi-fournisseurs, retries, coûts), la route de téléchargement des pièces.
- **À créer** : un extracteur « exigences » (une ligne par exigence : type normalisé, phase
  **candidature / offre / attributaire**, **porteur** candidat / mandataire / chaque membre /
  chaque sous-traitant, lots, obligatoire, éliminatoire, validité maximale, format, signature,
  source {pièce, page, extrait}) ; les blocs `visite`, `groupement`, `sous_traitance`, `variantes` ;
  les tables `exigences`, `dossier_entites`, `matrice_cellules` (SQL, partie 1 §2.6) ; un
  **référentiel de pièces** avec les **liens d'obtention** (URSSAF, impots.gouv, Kbis, Qualibat…) :
  il n'existe rien dans le repo ; l'écran de la matrice.
- **Risques** : couverture de lecture (`.doc`/`.xls`/scans) ; coût du mode document (0,9 à 1,2 €
  par DCE mesuré) ; pages citées fiables seulement en mode document ; ambiguïté « par membre »
  et « globale ».

### 10.5 Étape 5 : coffre-fort de pièces (validité) et relances par mail

- **Existant** : **rien** (ni fichier, ni table, ni upload, ni mail, ni planification) ; seulement
  des dates de validité déclaratives dans le profil BTP (`rge/mase/amiante.validite_jusqu`).
- **Réutilisable** : `pdf_extract` / `pieces.py` pour lire les pièces déposées ; `send_from_directory` ;
  le pattern des jobs asynchrones.
- **À créer** : upload multipart + glisser-déposer ; stockage objet (Scaleway Object Storage) +
  SHA-256 ; table `coffre_pieces` (type normalisé, émission, validité, statut) ; extraction de la
  validité (LLM léger, journalisée) ; envoi de mails (SMTP ou API transactionnelle, modèles,
  suivi) ; planificateur (relances, alertes d'expiration) ; gestion des **partenaires externes**
  (cotraitants, sous-traitants : contacts, liens de dépôt sécurisés sans compte ?) ;
  authentification, autorisation et chiffrement.
- **Risques** : sécurité et RGPD (attestations fiscales et sociales, RIB) ; délivrabilité des mails
  et domaine d'envoi ; rien n'est encore planifié côté serveur.

### 10.6 Étape 6 : préremplissage DC1 / DC2 / DUME / AE, pack de dépôt, puis dépôt assisté

- **Existant** : `services/assemblage_docx.injecter_template_acheteur` (remplissage d'un `.docx`
  acheteur), `assembler_tendia` (génération `.docx` stylée), `detecter_template_acheteur`
  (cadre de mémoire en `.docx`) ; ZIP à la volée (`/dce.zip`) ; downloaders anonymes (§3.2.3).
- **Réutilisable** : moteur `.docx` (python-docx), injection, ZIP ; parseurs de pages et
  sessions des downloaders.
- **À créer** : les **modèles officiels** DC1/DC2 (absents du repo), la génération du **DUME**
  (format XML/ESPD, à confirmer), le remplissage de l'AE (souvent en `.doc`, d'où la conversion
  LibreOffice) et des BPU/DPGF (`.xlsx`), le mapping profil → champs des formulaires, le pack de
  dépôt (arborescence attendue par la plateforme, nommage, signature). **Dépôt assisté** :
  comptes entreprise authentifiés, signature électronique et flux JavaScript, donc un navigateur
  piloté (Playwright, absent) ou des API, au cas par cas.
- **Risques** : responsabilité juridique (engagement de l'entreprise : confirmation obligatoire) ;
  signature électronique ; conditions d'utilisation des plateformes ; maintenance par plateforme.

### 10.7 Étape 7 : suivi des dossiers et des attributions (renouvellements)

- **Existant** : `cycle_marche.py` (statuts, transitions, historique ; inutilisé) ; `decp_marches`
  + `decp/matching.scorer_match` + `marche_attribution_link` (vide) ; 247 avis d'attribution
  BOAMP dans `marches` ; `decp_comparables.py` (comparables de prix) ; page `/decp`.
- **Réutilisable** : `scorer_match` (poids et seuils), les statuts de `cycle_marche` (à transposer
  en table), les comparables DECP pour les prix, la mesure « contrat antérieur du même acheteur »
  (322 avis).
- **À créer** : table `dossiers_reponse` + historique (déposé → attribué / rejeté, note, motif,
  lot) ; ingestion DECP continue ; parseur des avis d'attribution BOAMP (`donnees` eForms :
  lauréat, montant) et un connecteur TED si nécessaire ; alimentation batch de
  `marche_attribution_link` ; détection des renouvellements (fin de marché = notification + durée
  → alerte) ; complétion de `acheteur_siren`.
- **Risques** : délai de publication de la DECP ; qualité de l'appariement (seuil de 0,70) ;
  absence de nom de titulaire.

### 10.8 Alimentation du profil par la discussion

- **Existant** : **rien** (ni chat, ni tool use, ni extraction texte → profil, ni provenance).
  Briques voisines : `profil_form.parse` (fusion partielle sans perte), `organisme.valider_profil`,
  les schémas JSON du socle et du BTP (qui peuvent servir de **schéma d'outil**), les boutons de
  confirmation AJAX, `matching.evaluer` et `matching_exigences` (recalcul déterministe et peu
  coûteux, ~0 €).
- **À créer** : boucle conversationnelle avec **tool use** (outils `proposer_mise_a_jour_profil`,
  `rechercher_marches`, `expliquer_verdict`, `demander_piece`…) via `llm_router` étendu (aucun
  support d'outils aujourd'hui) ; tables `conversations`, `messages`, `actions_agent`,
  `profil_faits` ; règles de confirmation (champs qui engagent l'entreprise : CA, effectif,
  qualifications, références, donc carte de confirmation ; champs anodins : application directe
  avec trace) ; recalcul des verdicts sur événement ; projection JSON compatible (§5.10) ; écran
  de chat (streaming SSE).
- **Risques** : hallucination de faits (exiger source et confirmation) ; écrasement concurrent du
  profil (`kv_storage` last-write-wins, d'où le choix SQL) ; coût des conversations ; RGPD
  (rétention des messages).

### 10.9 Ordre de construction recommandé

1. **Socle données et technique (prérequis)** : tables SQL (`entreprises`, `profil_faits`, couche
   d'accès compatible Postgres/Scaleway) ; promotion de `llm_router` (+ journalisation dans
   `llm_appels` pour **tous** les appels) ; correction des dépendances (`bs4`, `curl_cffi`) et
   des 4 tests ; **redémarrage du pipeline LLM** (classification dans le pipeline, rattrapage des
   1 992 marchés, avec budget) ; reprise de l'ingestion DECP.
2. **Étape 1** (SIREN → profil) : historique DECP par SIREN (titulaires normalisés), connecteur
   Sirene/RGE, correspondances NAF/CPV → BTP, projection du profil. C'est la valeur immédiate, sans
   coût LLM.
3. **Étape 2** (ciblage) : état « inconnu » dans le matching, signaux structurés, critères
   acheteur connu et renouvellement.
4. **Alimentation du profil par la discussion** (chat + tool use + cartes de confirmation) : elle
   conditionne les étapes 3 à 5, et le recalcul des verdicts est déjà gratuit.
5. **Étape 3** (questions d'éligibilité classées) : extraction structurée des critères, clés
   canoniques BTP, verdict « en groupement ».
6. **Étape 4** (matrice) : promotion du mode document et de `pieces.py`, extracteur d'exigences,
   tables de matrice, écran.
7. **Étape 5** (coffre-fort + relances) : authentification, stockage objet, mails, planificateur.
   À faire **avant toute exposition en ligne**.
8. **Étape 7** (suivi et attributions), à mener en parallèle dès que la DECP est réingérée :
   dossiers, attributions, renouvellements.
9. **Étape 6** (préremplissage, pack de dépôt), puis le dépôt assisté en dernier : c'est le plus
   coûteux en maintenance et en responsabilité.
