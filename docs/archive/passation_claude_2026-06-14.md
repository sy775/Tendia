# Passation Claude — Tendia — État au 14 juin 2026 (~02h30)

## Pour le prochain Claude

Ce document te briefe sur l'état exact de Tendia. **Lis-le en entier avant de répondre à Younes.** Tendia est un projet complexe en plusieurs strates, et perdre le contexte fait perdre des heures.

Si Younes te pose une question, vérifie d'abord ici si la réponse est déjà connue avant de demander.

---

## Identité du projet

**Tendia** = SaaS de veille marchés publics français multi-sectoriels (BTP, ingénierie, formation, conseil, IT, EnR, etc.). Forké de **Apptia** (mono-secteur formation France Travail).

- **Stack** : Python 3.12 + SQLite + Flask (UI basique). Windows + PowerShell.
- **Repo** : `C:\Users\sai-y\Tendia\`
- **Storage** : `data/tendia.db` avec `kv_storage(collection, id, contenu_json)` (single table architecture)
- **Branding** : Apptia → Tendia complété
- **Philosophy** : "qualité maximale même si plus lent"
- **Stade** : POC en cours de transition vers MVP commercial. Pas encore de client payant.

---

## État de la base au 14 juin 2026 02h30

| État DCE | Nombre | % |
|---|---|---|
| `complet` | **131** (en cours d'augmentation, batch tournant) | 31% |
| `incomplet` | 38 | 9% |
| `auth_requise` | ~60 (en cours de diminution) | 14% |
| `vide` | 190 | 45% |
| **Total** | **422** | 100% |

**Détail des 131 `complet`** :
- 66 marchés Atexo (`atexo_downloader.py`)
- 40 marchés Achatpublic (`achatpublic_downloader.py`)
- 25+ marchés AWS-Achat (`aws_downloader.py`) — chiffre à confirmer après batch nocturne

---

## Sprints livrés aujourd'hui (13 juin 2026)

### Sprint AWS-Achat (commit 2c9a1f2)
Downloader complet pour `marches-publics.info`. Workflow 7 étapes ColdFusion + 2captcha + multi-fichiers + décompression. La stack la plus complexe des 3 downloaders.

Patches appliqués au cours de la journée :
- `patch_aws_unescape.py` (décodage `&amp;` URLs)
- `patch_aws_unescape_html.py` (décodage `&amp;` HTML)
- `patch_aws_cfid_refresh.py` (récupération CFID régénéré après cnxAnonyme)
- `patch_aws_lots_mono.py` (`lots=0` pour mono-lot)

### Sprint Anti-Ban v1 (commit 43e296f)
Module `http_humain.py` partagé entre les 3 downloaders :
- Rate-limit gaussien (75 sec ± 30 entre marchés, 3-6 sec inter-étapes)
- 5 User-Agents Chrome/Firefox tournants
- Plages horaires bureau (8h-19h lun-ven, override `--ignorer-heures`)
- Pauses cumulatives toutes les 20 marchés (15-30 min)
- Détection ban auto, arrêt batch après 3 bans consécutifs
- Backoff sur erreurs réseau

### Sprint Industrialisation v2 (commit c6d9472)
16 fichiers, +1226 lignes :
- `http_client.py` : wrapper backend HTTP (curl_cffi avec fallback requests) — **DÉSACTIVÉ ce soir** (voir Décisions techniques)
- `tendia_logs.py` : logs JSONL structurés non bloquants dans `logs/`
- `tendia_monitoring.py` : dashboard console
- `docs/production.md` : guide production
- Session-ID Bright Data dans `http_humain.py` (rotation IP automatique par marché)
- Retry IP automatique sur ban dans `aws_downloader.py` (3 IPs tentées avant abandon)
- Backoff exponentiel 1/2/4s sur erreurs réseau
- Estimation coût en temps réel (bande passante + 2captcha)
- **137 tests passants** (37 + 43 + 25 + 22 + 10)

### Patches du soir (debug stack proxy)
- `patch_http_humain_proxy.py` : intégration proxy via `TENDIA_PROXY_URL` env (déjà appliqué)
- `patch_disable_curl_cffi.py` : désactivation curl_cffi (créé mais matching foiré sur le fichier)
- `http_client.py` réécrit manuellement en backend `requests` pur (suite au patch raté)

---

## Décisions techniques majeures de la journée

### 1. curl_cffi DÉSACTIVÉ
`curl_cffi` impose une lecture stricte UTF-8 du body alors qu'AWS-Achat sert son HTML en ISO-8859-1 (déclaration uniquement dans `<meta http-equiv>`, pas dans le header HTTP). Résultat : `UnicodeDecodeError 0xe9 in position 1`.

`requests` (le backend standard) gère ça correctement via `apparent_encoding` (chardet fallback).

Donc `http_client.py` a été manuellement réécrit pour utiliser `requests` directement. Tu peux toujours voir le code curl_cffi désactivé dans `http_client.py.bak_avant_disable_curl_cffi`.

**Impact** : on perd le TLS fingerprint Chrome. Mais on a déjà 4 autres couches d'imitation humaine (proxy résidentiel + UA + rate-limit + retry IP). Suffisant pour AWS-Achat.

### 2. Bright Data ISP → ASN banni globalement
Bright Data Shared ISP utilise un seul ASN (213541 "WS Telecom Inc"). AWS-Achat a fini par blacklister l'ASN entier après ~50 requêtes éparses du soir. Toutes les 10000 "IPs rotatives" du pool sont en fait du même ASN.

**Impact** : Bright Data ISP est inutilisable pour AWS-Achat dans l'état. La zone reste créée mais inactive en pratique.

### 3. IPRoyal Residential KYC validé
Younes a basculé sur **IPRoyal Residential** avec KYC particulier (carte d'identité). IPRoyal a une vraie diversification ASN (Free SAS, Orange, SFR, Bouygues) → AWS-Achat ne peut pas blacklister l'ensemble.

- 1ère validation : `81.65.143.49` (IP Free SAS, range box résidentielle française)
- Test AWS-Achat sur autre IDM : ✅ OK (page ColdFusion + captcha présent)
- Achat : 2 GB initial à $1.75-6/GB + top-up

**Coût observé en pratique** :
- Test 1 marché : ~700 Mo (DCE lourd)
- Batch 5 marchés : 11.6 Mo seulement (DCE légers)
- Variance énorme selon contenu des marchés (gros zip vs PDF seul)

### 4. Le CDN externe `downloads.awsolutions.fr` est le gros consommateur
Dans le rapport IPRoyal : sur 2003 Mo consommés, 2003 Mo venaient du CDN externe (3 fichiers DCE), et 0.33 Mo seulement de `www.marches-publics.info`.

**Optimisation à faire (pas encore implémentée)** : exclure `downloads.awsolutions.fr` du proxy IPRoyal. Le CDN ne ban pas les IPs (sinon les vrais users seraient bloqués). On peut passer en direct via IP fixe pour les téléchargements, et garder IPRoyal pour les 7 requêtes ColdFusion AWS-Achat.

Économie attendue : 99.95% des coûts IPRoyal AWS.

---

## Configuration actuelle

### `.env`
```
ANTHROPIC_API_KEY=sk-ant-api03-...
TWOCAPTCHA_API_KEY=0df7338fae65c51d554721a9ddb5a685 (à régénérer suite exposition)
TENDIA_PROXY_URL=http://IPRoyal_USER:IPRoyal_PASS_country-fr@geo.iproyal.com:12321
```

**Notation format IPRoyal** : `_country-fr` se colle au PASSWORD, pas au username (contrairement à Bright Data). Format final :
```
http://USERNAME:PASSWORD_country-fr@geo.iproyal.com:12321
```

### Bright Data
2 zones existent dans le dashboard :
- `tendia_aws` (Shared unlimited $2/mois — ASN banni, inutilisable)
- `tendia-aws-paygb` (Pay-per-GB $8/GB — ASN banni aussi en pratique)

**Pas réutilisable pour AWS-Achat sur le court terme.** Garder en backup en cas de souci IPRoyal.

### IPRoyal
- Compte créé, KYC particulier validé
- Plan Residential Pay-per-GB ($1.75-6/GB selon volume)
- Crédit actuel : ~2 GB (à vérifier en temps réel sur dashboard)

---

## Incidents sécurité ce soir

Younes a **exposé des credentials en chat 4 fois** durant la session :
1. Clé Anthropic API (probablement révoquée)
2. Clé 2captcha `0df7338...` (à régénérer)
3. Bright Data ISP `cqx3tec4i575` (à régénérer)
4. **IPRoyal Residential `7ar2t7b0kFlGeFgt`** (à régénérer urgent)

**Important** : Younes connaît le problème. Si jamais il colle encore des credentials, rappelle-lui mais sans lui faire la morale (il l'a entendue 4 fois). Demande simplement de reset le mot de passe.

---

## En cours actuellement

**Batch nocturne tournant** : `python retelecharger_aws_achat_anti_ban.py --max 63 --oui --ignorer-heures`

Lancé vers 02h. Estimation 145 min affichée, mais réel ~2-3h avec pauses. Devrait finir vers 04h-05h.

**Important** : le batch peut **sembler bloqué** pendant 10-15 min lorsqu'il télécharge un gros DCE (500+ Mo). Younes a Ctrl+C un téléchargement légitime tout à l'heure en pensant que ça plantait. Si tu vois apparemment un blocage, **ne pas couper** sans vérifier qu'IPRoyal répond toujours via un test rapide.

Trace de l'incident : `aws_downloader.py:736 _telecharger_fichier_cdn → r.iter_content(chunk_size=65536)`. C'est le streaming du gros fichier qui ne loggue rien chunk par chunk.

---

## Stack technique production-ready

```
INGESTION
  ├── BOAMP, TED, futur PLACE
  ↓
FILTRAGE PRESET (Sprint 5 à faire)
  ├── Multi-preset matching
  ↓
DCE DOWNLOAD (livré aujourd'hui)
  ├── atexo_downloader.py         ✅ (66 complet)
  ├── achatpublic_downloader.py   ✅ (40 complet)
  ├── aws_downloader.py           ✅ (25+ complet) + 4 patches du jour
  ├── http_humain.py              ✅ Anti-Ban v1 + session-id Bright Data
  ├── http_client.py              ✅ backend requests (curl_cffi désactivé)
  ↓
LOGGING & MONITORING (livré aujourd'hui)
  ├── tendia_logs.py    → logs/aws-achat_YYYY-MM-DD.jsonl
  ├── tendia_monitoring.py → dashboard console (DCE coverage, batchs, coûts, échecs)
  ↓
ENRICHISSEMENT LLM (Sprint Sprint 3 partiellement complet)
  ├── llm_extract.py             (extracteur de briefs)
  ├── llm_calibration.py
  ↓
UI (Sprint UI à venir)
  ├── tendia_ui.py
```

---

## Le sujet du moment — amélioration des briefs

**Younes a posé en fin de session une question stratégique majeure** :

> "Comment peut-on améliorer les briefs maintenant qu'on a plus de DCE ? Il faut que les briefs permettent de prendre une décision rapide avec tous les éléments clés en étant sourcé. Faut-il des prompts différents par secteur ?"

C'est **LA** vraie question commerciale de Tendia. Plus important stratégiquement que finir les 63 marchés AWS-Achat restants.

J'ai reporté la réponse approfondie à demain matin pour qu'on creuse à tête reposée. Hypothèses initiales données :

1. **Le brief doit répondre "go/no-go en 30 sec"** : montant, pondération technique/prix, capacités min, références exigées, durée, pénalités dures, profil acheteur, compétition probable
2. **Sourçage indispensable** : chaque assertion doit pointer vers le fichier source (RC §3.2, CCAP §12, DPGF ligne 47) — différencie un brief "joli" d'un brief "actionnable"
3. **Pas 6 prompts différents** : 1 prompt cœur commun + 6 add-ons sectoriels activables selon preset (BTP→Qualibat, formation→RNCP, IT→RGPD/CNIL, ingénierie→OPQIBI, etc.)
4. **Triage automatique** : scoring composite 0-100 + flags rouges/verts + résumé 3 lignes pour tier 1 + brief complet pour tier 2/3

**Pour le sprint demain, prochain Claude, tu auras besoin d'inspecter** :
- `llm_extract.py` (prompt actuel, schéma de sortie, logique de découpe DCE)
- `llm_calibration.py` (logique de fallback)
- `presets/*/[_preset.json,_schema.json]` (schémas spécifiques par secteur)
- 5-10 briefs récents en SQLite pour qualité actuelle vs cible
- 1-2 marchés exemples par secteur (BTP, formation, IT, conseil, ingénierie, EnR)
- Idéalement le marché BOAMP-26-56539 dont Younes parle (gain ['RC'] → ['AE','CCAP','CCTG','CCTP','DPGF','RC'])

Workflow attendu pour le sprint "Briefs v2" :
1. 30 min d'inspection code + briefs existants
2. 1h d'atelier "brief idéal" avec Younes sur 1 marché précis
3. 30 min rédaction prompt Sprint Claude Code
4. 4-5h Claude Code livre
5. 30 min validation + ajustements

Total : ~1 journée de focus si Younes est disponible.

---

## Plan de reprise (par priorité)

### Court terme (cette semaine)

1. **Vérifier bilan batch nocturne** : combien des 63 marchés AWS-Achat sont passés en `complet`, coûts IPRoyal consommés
2. **Sprint "Briefs v2"** : le sujet qu'on n'a pas pu attaquer ce soir (atelier + prompt + Claude Code)
3. **Patch CDN sans proxy** : exclure `downloads.awsolutions.fr` du proxy IPRoyal → économise 99% des coûts
4. **Reset passwords exposés** : 2captcha + IPRoyal (Younes va le faire normalement)

### Moyen terme (semaine prochaine)

1. **Sprint e-marchespublics** : 15 marchés Dematis, méthode similaire AWS, ~3-4h Claude Code
2. **Sprint Hygiène** :
   - Cleanup `.bak_*` qui se sont accumulés (au moins 8 backups pendant la nuit)
   - Cron Windows pour batch quotidien
   - Backfill URLs `&amp;` (41/422 en base)
   - Fix anomalies `qualifier_dce`
3. **Atelier multi-secteurs** : tester 1 marché par preset (BTP / ingénierie / formation / conseil / IT / EnR) avec les nouveaux briefs v2

### Long terme (mois suivants)

1. **Sprint UI fiche marché complet** : prompt déjà rédigé dans `sprint_ui_fiche_marche_prompt.txt`, 14-18h
2. **PLACE scraping** : 15 marchés, complexe
3. **Refonte enrichir_complet**
4. **Multi-tenants Tendia** : auth + isolation tenant (quand premiers clients payants)
5. **Migration SQLite → PostgreSQL** (multi-tenant)

---

## Pour interagir avec Younes

**Style** : il aime quand on est direct, structuré, sans bullshit. Il valorise les avis honnêtes même critiques. Il déteste les disclaimers et les "let me know if...".

**Format préférences** :
- Réponses structurées avec sections
- Code blocks PowerShell explicites avec commentaires (`# 1.`, `# 2.`, etc.)
- Pas de paste Python en `python -c` quand guillemets imbriqués → fichier `.py` externe
- Fichiers livrés via `create_file` + `present_files` (jamais zip)

**Pièges à éviter** :
1. **BOM UTF-8** casse python-dotenv → toujours UTF-8 sans BOM
2. **Guillemets imbriqués PowerShell** → toujours fichier `.py` externe pour scripts complexes
3. **Backup SQLite WAL** : `PRAGMA wal_checkpoint(TRUNCATE)` avant Copy-Item
4. **curl Windows** = alias Invoke-WebRequest → utiliser `curl.exe` si besoin
5. **AWS-Achat ban par ASN entier**, pas par IP individuelle
6. **Encodage AWS-Achat** : header dit UTF-8 mais body en ISO-8859-1 (curl_cffi plante)
7. **Téléchargement gros DCE silencieux** : `r.iter_content` ne log pas par chunk, peut sembler bloqué 10-15 min

**État émotionnel à la fin de session** : Younes a fait 12-13h de coding/debug intense. Il était à 02h30. **A coupé à 03h** (à confirmer). Reprise probablement dimanche matin ou lundi.

---

## Outils & ressources

- **Languages** : Python 3.12
- **OS** : Windows 11 (PowerShell)
- **Storage** : SQLite `kv_storage` single-table
- **HTTP** : `requests` (curl_cffi désactivé)
- **Proxy** : IPRoyal Residential (primaire), Bright Data (backup banni)
- **Captcha** : 2captcha ($0.001/captcha)
- **LLM** : Claude API (extraction briefs) via `llm_extract.py`
- **Claude Code** : forfait Anthropic, utilisé pour sprints majeurs

### Endpoints proxy
- IPRoyal : `geo.iproyal.com:12321`
- Bright Data : `brd.superproxy.io:33335`

### Fichiers livrés ce soir (dans /mnt/user-data/outputs si tu as accès)
- `passation_claude_2026-06-13_v2.md`
- `passation_claude_2026-06-13_v3.md` (à mettre à jour par ce doc)
- `sprint_anti_ban_v1_prompt.txt`
- `sprint_industrialisation_v2_prompt.txt`
- `addendum_passation_anti_ban.md`
- `recap_fin_journee.md`
- `patch_http_humain_proxy.py` (appliqué)
- `patch_aws_encoding.py`, `patch_aws_encoding_v2.py`, `patch_aws_encoding_chir.py`, `patch_aws_decoder_manuel.py`, `patch_disable_curl_cffi.py` (cascade debug encoding, finalement résolu via réécriture http_client.py)
- `patch_cftoken_regex.py` (généré mais Younes ne l'a probablement pas appliqué — pas nécessaire en pratique)
- `http_client.py` (version corrigée sans curl_cffi)
- `test_proxy_brightdata.py`, `diagnostic_etape2_simple.py`, `diagnostic_autre_idm.py` (jetables, à mettre dans `scripts/` ou supprimer)

---

## Architecture des briefs (état actuel pour préparer le sprint v2)

Pour t'aider à comprendre ce qui existe avant l'atelier "briefs v2" :

- Brief = JSON produit par `llm_extract.py` à partir des fichiers DCE
- Un brief par marché (mutualisé entre presets — c'est une décision architecturale prise au sprint 3 step 1A/1B/1C)
- Schéma = union des `bloc_schema_specifique` de tous les presets installés (calculée au démarrage en mémoire — "Option 1")
- Sections universelles : `_synthese_brief`, identifiants marché, montant estimé, durée, etc.
- Sections sectorielles : selon preset (`bloc_schema_specifique`)
- Extraction trigger : à l'ingestion, sur tous les marchés matching au moins 1 preset installé
- Pas de scoring threshold gate à l'extraction

Champs généralisés au passage Apptia → Tendia :
- `volume_min_references_similaires`
- `volume_estime` (avec units)
- `domaine` → `preset`
- `formation_ft` → `formation`

---

## Note de fin

Cette doc est verbeuse. C'est volontaire : Tendia est complexe et perdre du contexte coûte du temps. Lis-la en entier au premier message de la nouvelle session.

Si Younes te pose une question dont tu ne trouves pas la réponse ici, demande-lui mais cite ce doc dans ta question ("D'après la passation tu travaillais sur X, mais je ne vois pas Y précisé — peux-tu confirmer ?").

Bon courage. Tendia avance bien.

— Le Claude qui a vécu la session du 13 juin 2026 (intense)
