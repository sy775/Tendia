# Audit — proxy par plateforme (Étape 1)

> Lecture seule. Objectif : proxy IPRoyal ON par défaut, OFF explicite pour PLACE, data.gouv.fr (DECP), BOAMP.

## 1. Mécanisme proxy actuel

`http_humain.creer_session_humaine(ua_fixe, proxy_url, session_id)` :
- Si `proxy_url is None` → lit **`TENDIA_PROXY_URL`** dans l'environnement (actuellement IPRoyal `geo.iproyal.com:12321`).
- Si une URL proxy existe → `session.proxies = {http, https}` (avec injection de `session-id` Bright Data si host `brd.superproxy.io` — code legacy, inactif sur IPRoyal).
- **Aucune logique par plateforme** : le proxy est appliqué à TOUTES les sessions `creer_session_humaine` de façon uniforme.

## 2. Points d'appel de `creer_session_humaine` (= sessions concernées par le proxy)

| Fichier:ligne | Plateforme | Proxy cible voulu |
|---|---|---|
| `achatpublic_downloader.py:178` | achatpublic.com | **ON** (défaut) |
| `atexo_downloader.py:151` | Atexo MPE — **PLACE (marches-publics.gouv.fr) OU forks** | **PLACE → OFF**, forks → ON ⚠️ |
| `aws_downloader.py:426` | AWS-Achat (marches-publics.info) | **ON** (ban agressif) |
| `dematis_downloader.py:547` | e-marchespublics (Dematis) | **ON** (ban agressif) |
| `diagnostic_autre_idm.py:44` | diagnostic (AWS-Achat) | ON (script de diag, mineur) |

⚠️ **Cas Atexo** : un SEUL appelant (`atexo_downloader`) sert PLACE **et** les forks régionaux/municipaux. La plateforme dépend de l'URL → `_detecter_url_base(url_dce)` donne le host. Il faut donc distinguer `marches-publics.gouv.fr` (→ `place`, OFF) des autres hosts Atexo (→ `atexo`, ON) **au moment de l'appel**.

## 3. Chemins de récupération AVIS / recherche (PAS via `creer_session_humaine`)

`BOAMP`, `TED` et la **recherche PLACE par mot-clé** passent par `http_utils` (`get_json`/`post_json`, et un `requests.get` direct dans `dce_finder`), sur un `requests.Session` **sans proxy** :
- `dce_finder._fetch_record_boamp` → `http_utils.get_json` → **pas de proxy** ✓
- `dce_finder._fetch_notice_ted` → `http_utils.post_json` → **pas de proxy** ✓
- `dce_finder` recherche PLACE (`requests.get` ligne ~305) → **pas de proxy** ✓

➡️ **BOAMP, TED et PLACE-recherche sont DÉJÀ en direct (sans proxy).** Le flag `TENDIA_PROXY_FOR_BOAMP` sera donc surtout déclaratif/futur (ce chemin n'utilise pas de proxy aujourd'hui). Idem `data.gouv.fr` (DECP) : **non implémenté à ce jour** → flag posé pour le futur.

➡️ Le SEUL point où PLACE pourrait recevoir le proxy est le **téléchargement DCE via `atexo_downloader`** → c'est là que le flag `TENDIA_PROXY_FOR_PLACE=0` agira.

## 4. Plan d'implémentation proposé (Étape 2)

1. `creer_session_humaine(..., plateforme: Optional[str] = None)` : si `plateforme` fournie, décider via `_proxy_pour_plateforme(plateforme)` :
   - défaut **True** (proxy ON) ;
   - **False** si `TENDIA_PROXY_FOR_<PLATEFORME.upper()> == "0"`.
   - Si `plateforme is None` → comportement actuel (proxy ON via `TENDIA_PROXY_URL`) — rétro-compat.
2. Propager `plateforme` dans les appelants :
   - achatpublic → `"achatpublic"` ; aws → `"aws_achat"` ; dematis → `"dematis"` ;
   - **atexo → `"place"` si `_detecter_url_base` == marches-publics.gouv.fr, sinon `"atexo"`**.
3. `.env.example` + `.env` : ajouter `TENDIA_PROXY_FOR_PLACE=0`, `TENDIA_PROXY_FOR_DATA_GOUV=0`, `TENDIA_PROXY_FOR_BOAMP=0`.
4. Tests : unitaire `_proxy_pour_plateforme` ; réel PLACE sans proxy ; simulé Dematis avec proxy (`session.proxies` défini).

## 5. Fichiers touchés (Étape 2) — AUCUN conflit avec le runner 1G

`http_humain.py`, `atexo_downloader.py`, `aws_downloader.py`, `dematis_downloader.py`, `achatpublic_downloader.py`, `.env`/`.env.example`, `tests_*`. 
Le runner 1G utilise `tendia_extraire / llm_extract / preset / analyse / reextraire / relancer_extraction_chantier1` — **disjoints**. ✅
