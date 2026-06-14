# Module http_humain

> Source documenté : `http_humain.py` (254 lignes). Cette doc décrit
> uniquement ce que le code fait réellement, avec renvois aux numéros de
> ligne. Les points incertains sont marqués « (à confirmer) ».

## Rôle (sessions HTTP « humaines » anti-ban + stratégie proxy par plateforme)

Le module fournit des helpers pour émettre des requêtes HTTP qui ressemblent
à un usage humain raisonnable, afin d'éviter les bans IP sur les plateformes
DCE (docstring lignes 1-14). Concrètement il offre :

- une fabrique de session HTTP « humaine » : User-Agent tournant, headers
  réalistes, et application conditionnelle d'un proxy résidentiel selon la
  plateforme (`creer_session_humaine`, lignes 111-158) ;
- une politique de proxy ciblée par plateforme (`_proxy_pour_plateforme`,
  lignes 87-108) : proxy ON par défaut, OFF via variable d'environnement ;
- des helpers de temporisation aléatoire (`attendre_humain`,
  `attendre_inter_etapes`, `attendre_pause_cumulative`, `jitter`) ;
- un garde-fou horaire (`heure_actuelle_est_bureau`) ;
- une heuristique de détection de page de ban (`ressemble_a_page_ban`) ;
- des helpers internes Bright Data (`_injecter_session_id`,
  `_nettoyer_session_id`) et un pool de User-Agents (`USER_AGENTS_POOL`).

Le commentaire d'en-tête (lignes 11-13) précise le contexte d'origine : un
batch AWS-Achat a déclenché un ban IP le 13/06/2026 après ~10-15 sessions
ColdFusion enchaînées en 1h (rythme fixe de 3 s, UA unique).

Le module dépend de `http_client` (importé sous l'alias `http_lib`,
ligne 24) et de la stdlib (`os`, `random`, `re`, `time`, `uuid`,
`datetime`, lignes 15-21). Pas de dépendance externe directe.

## creer_session_humaine(ua_fixe, proxy_url, session_id, plateforme) : headers réalistes, UA tournant, application proxy

Définie lignes 111-158. Tous les arguments sont optionnels et valent `None`
par défaut.

1. **Création de la session** : `session = http_lib.Session()` (ligne 131).
   La nature exacte de l'objet renvoyé dépend du backend de `http_client`
   (voir section Dépendances).
2. **User-Agent** (ligne 132) : si `ua_fixe` est fourni, il est utilisé tel
   quel (utile pour la reproductibilité des tests) ; sinon un UA est tiré au
   hasard dans `USER_AGENTS_POOL` via `random.choice`.
3. **Headers réalistes** (lignes 133-145) : `session.headers.update(...)`
   pose `User-Agent`, `Accept` (text/html…), `Accept-Language`
   (`fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7`), `Accept-Encoding`
   (`gzip, deflate, br, zstd`), `DNT: 1`, les en-têtes `Sec-Fetch-*`
   (`Dest: document`, `Mode: navigate`, `Site: none`, `User: ?1`) et
   `Upgrade-Insecure-Requests: 1`.
4. **Résolution du proxy** (lignes 149-150) : **seulement si**
   `proxy_url is None` ET `_proxy_pour_plateforme(plateforme)` renvoie `True`,
   `proxy_url` est lu depuis la variable d'environnement `TENDIA_PROXY_URL`.
   Si `proxy_url` est passé explicitement, cette résolution est sautée — le
   flag plateforme est alors ignoré (voir Pièges connus).
5. **Application du proxy** (lignes 151-157) : si `proxy_url` est non vide :
   - si l'URL contient `brd.superproxy.io` et ne contient pas déjà
     `-session-` (lignes 152-156), un session-id Bright Data est injecté :
     `session_id` nettoyé via `_nettoyer_session_id` s'il est fourni, sinon
     un `uuid.uuid4().hex[:8]` (8 caractères hexadécimaux), puis injection
     via `_injecter_session_id` ;
   - dans tous les cas, `session.proxies = {"http": proxy_url, "https": proxy_url}`
     (ligne 157).
6. **Retour** : la session configurée (ligne 158).

Notes de comportement vérifiées dans le code :
- Si `proxy_url=""` (chaîne vide) est passé explicitement : la condition
  `proxy_url is None` est fausse (donc pas de lecture de `TENDIA_PROXY_URL`)
  et `if proxy_url:` est faux (chaîne vide) → aucun proxy n'est appliqué.
- L'injection de session-id ne concerne **que** les URL `brd.superproxy.io`.
  Tout autre proxy reçoit l'URL telle quelle, `session_id` étant alors
  ignoré pour la construction d'IP.
- Le commentaire « fingerprint TLS Chrome (via http_client/curl_cffi) »
  (lignes 116-117) décrit l'intention historique ; l'effet réel dépend du
  backend actif de `http_client` (voir Dépendances et Pièges connus).

## _proxy_pour_plateforme(plateforme) : proxy ON par défaut, OFF si TENDIA_PROXY_FOR_<P>=0 ; plateformes désactivées : place, boamp, data_gouv

Définie lignes 87-108. Décide si le proxy résidentiel doit être appliqué
pour une plateforme.

- Si `plateforme` est falsy (`None` ou chaîne vide) → renvoie `True`
  (proxy ON, comportement historique ; lignes 103-104).
- Sinon, lit la variable d'environnement
  `TENDIA_PROXY_FOR_<PLATEFORME en majuscules>` (ligne 105 :
  `f"TENDIA_PROXY_FOR_{plateforme.upper()}"`).
- Si cette variable existe et que sa valeur (après `.strip()`) appartient à
  `("0", "false", "False", "no", "off")` → renvoie `False` (proxy OFF ;
  lignes 106-107).
- Dans tous les autres cas → renvoie `True` (lignes 108).

Donc : **proxy activé par défaut**, désactivation explicite uniquement.
La docstring (lignes 93-94) cite les plateformes confirmées sans ban à
désactiver : `place` (marches-publics.gouv.fr), `boamp`, `data_gouv`
(DECP). À noter : ces noms sont une convention documentaire ; le code ne
contient aucune liste codée en dur — la désactivation passe toujours par la
variable d'environnement correspondante (ex. `TENDIA_PROXY_FOR_PLACE=0`).

## Helpers anti-ban

### attendre_humain(min_sec=30, max_sec=180, mu=None, sigma=None, verbose=False)
Lignes 161-179. Dort un délai aléatoire et le renvoie.
- Si `mu` ET `sigma` sont fournis : tirage gaussien `random.gauss(mu, sigma)`
  borné dans `[min_sec, max_sec]` (lignes 171-173).
- Sinon : tirage uniforme `random.uniform(min_sec, max_sec)` (ligne 175).
- `time.sleep(delay)` puis retourne `delay` (lignes 178-179). `verbose=True`
  imprime `  [http_humain] Attente {delay:.1f} sec...`.

### attendre_inter_etapes(min_sec=1.5, max_sec=4.0, verbose=False)
Lignes 182-192. Petit délai entre étapes d'un même workflow :
`random.uniform(min_sec, max_sec)`, `time.sleep`, renvoie le délai. Mime le
temps de lecture d'une page avant un clic.

### attendre_pause_cumulative(compteur, seuil=20, pause_min_sec=900, pause_max_sec=1800, verbose=False)
Lignes 212-229. Pause longue périodique :
- si `compteur > 0` ET `compteur % seuil == 0` (ligne 222), dort
  `random.uniform(pause_min_sec, pause_max_sec)` (900-1800 s = 15-30 min par
  défaut) et renvoie le délai (lignes 223-228) ;
- sinon renvoie `None` (ligne 229).

### jitter(delay, jitter_pct=0.2)
Lignes 232-239. Renvoie `random.uniform(delay - j, delay + j)` avec
`j = delay * jitter_pct`. **Ne dort pas** : renvoie seulement la valeur à
utiliser ensuite (ex. `jitter(60, 0.2)` → valeur entre 48 et 72).

### heure_actuelle_est_bureau(verbose=False)
Lignes 195-209. Renvoie `True` si l'instant courant est une plage de bureau
crédible :
- `False` le week-end (`now.weekday() >= 5`, samedi/dimanche ; lignes 201-204) ;
- `False` hors de `[HEURE_DEBUT_BUREAU, HEURE_FIN_BUREAU]` =
  `[08:00, 19:00]` (constantes lignes 44-45 ; test ligne 205) ;
- `True` sinon.

### ressemble_a_page_ban(html)
Lignes 242-253. Heuristique de détection de ban / page d'accueil servie à la
place de la page attendue.
- Renvoie `False` si `html` est falsy (vide/`None` ; lignes 250-251).
- Sinon `True` si la version minuscule du HTML contient l'un des
  `_PATTERNS_BAN` (ligne 253). Les patterns (lignes 50-57) sont :
  `acheteurs.htm`, `fournisseurs.htm`, `bootstrap`, `blocked`,
  `access denied`, `trop de requ` (= « trop de requêtes »).

### _injecter_session_id(proxy_url, session_id)
Lignes 68-84. Helper interne. Insère un session-id dans une URL proxy Bright
Data en transformant `user-zone-X` en `user-zone-X-session-SID` dans la
partie userinfo (parsing via `urllib.parse.urlparse`/`urlunparse`).
Reconstruit netloc avec mot de passe (s'il existe), hostname et port.
Une session-id différente = une IP différente du pool résidentiel.

### _nettoyer_session_id(brut)
Lignes 60-65. Helper interne. Réduit un identifiant à `[a-z0-9]` (mise en
minuscules + suppression de tout autre caractère via regex), tronqué à 24
caractères. Ex. `"BOAMP-26-56599"` → `"boamp2656599"`. Raison : Bright Data
n'accepte pas les tirets dans le session-id (sinon le découpage
`-session-` du username casse).

### USER_AGENTS_POOL
Lignes 28-41. Liste de 7 User-Agents Chrome/Firefox/Edge/Safari récents
(annoncés mi-2026), mélangeant Windows et macOS pour varier le fingerprint
d'en-tête. Utilisée par `creer_session_humaine` (tirage aléatoire) et
référencée par les downloaders comme UA « par défaut » (`USER_AGENTS_POOL[0]`).

## Dépendances (http_client) + variables d'env

### http_client (alias http_lib)
Importé ligne 24. Le module n'utilise que `http_lib.Session()` (ligne 131).
D'après `http_client.py`, le backend est `requests` : `BACKEND = "requests"`
et `Session(...)` renvoie un `requests.Session` standard (curl_cffi étant
désactivé par patch d'encodage, cf. en-tête et lignes 36-50 de
`http_client.py`). Le fingerprint TLS Chrome évoqué dans la docstring de
`creer_session_humaine` n'est donc pas garanti avec ce backend (à confirmer
selon la configuration déployée).

### Variables d'environnement
- `TENDIA_PROXY_URL` (ligne 150) : URL du proxy résidentiel lue quand
  `proxy_url is None` et que la plateforme autorise le proxy.
- `TENDIA_PROXY_FOR_<PLATEFORME>` (ligne 105) : désactive le proxy pour une
  plateforme si sa valeur (strippée) ∈ `{0, false, False, no, off}`.
  Exemples cités dans le code : `TENDIA_PROXY_FOR_PLACE=0`,
  `TENDIA_PROXY_FOR_BOAMP=0`, `TENDIA_PROXY_FOR_DATA_GOUV=0`.

## Exemples d'usage (appelants réels)

Tous passent l'argument `plateforme=` pour piloter la politique proxy.

### dematis_downloader (`dematis_downloader.py:547`)
```python
session = http_humain.creer_session_humaine(session_id=session_id, plateforme="dematis")
```
Utilise aussi `ressemble_a_page_ban` (ligne 571) et `attendre_inter_etapes`
(lignes 580, 618, 681, 706).

### aws_downloader (`aws_downloader.py:426-427`)
```python
session = http_humain.creer_session_humaine(session_id=session_id or idm,
                                            plateforme="aws_achat")
```
`session_id` retombe sur l'identifiant marché `idm`. Utilise
`ressemble_a_page_ban` (lignes 456, 499) pour distinguer un ban d'un échec de
parsing, et `attendre_inter_etapes` (lignes 472, 590, 619).

### atexo_downloader (`atexo_downloader.py:153-155`)
```python
_plateforme = "place" if "marches-publics.gouv.fr" in (url_base or "").lower() else "atexo"
session = http_humain.creer_session_humaine(session_id=session_id or str(id_atexo),
                                            plateforme=_plateforme)
```
La plateforme est calculée dynamiquement : `"place"` si l'URL est
marches-publics.gouv.fr (proxy désactivable), sinon `"atexo"` (proxy par
défaut). `session_id` retombe sur `id_atexo`.

### achatpublic_downloader (`achatpublic_downloader.py:178-179`)
```python
session = http_humain.creer_session_humaine(session_id=session_id or pcslid,
                                            plateforme="achatpublic")
```
`session_id` retombe sur `pcslid`. Utilise `attendre_inter_etapes(2, 5, ...)`
(ligne 210).

### Autres appelants
- `diagnostic_autre_idm.py:44` : `creer_session_humaine()` sans argument
  (proxy ON, UA aléatoire).
- Scripts batch `retelecharger_*` : utilisent surtout les temporisations
  (`attendre_humain`, `attendre_pause_cumulative`) et le garde-fou
  `heure_actuelle_est_bureau` plutôt que la fabrique de session.

## Pièges connus

- **Un `proxy_url` explicite ignore le flag plateforme.** La résolution
  `TENDIA_PROXY_URL` et l'appel à `_proxy_pour_plateforme` ne se font que si
  `proxy_url is None` (ligne 149). Passer `proxy_url="http://..."` applique
  donc le proxy même pour une plateforme marquée `TENDIA_PROXY_FOR_*=0`.
  (Comportement confirmé par `tests_proxy_par_plateforme.py`, cas « override ».)
- **L'injection de session-id ne vaut que pour `brd.superproxy.io`**
  (ligne 152). Pour tout autre fournisseur de proxy, l'URL est utilisée telle
  quelle et `session_id` n'a aucun effet sur l'IP obtenue.
- **Si l'URL Bright Data contient déjà `-session-`**, aucune nouvelle
  injection n'a lieu (condition `"-session-" not in proxy_url`, ligne 152).
- **`proxy_url=""` (chaîne vide)** force une session sans proxy : ni lecture
  de `TENDIA_PROXY_URL`, ni application (cf. lignes 149-151).
- **BOAMP / TED passent par `http_utils`, pas par ce module.** `http_utils.py`
  expose une session `requests` partagée avec un User-Agent identifié
  (`Tendia/0.1 ...`) et **aucun proxy** (cf. `http_utils.py` lignes 1-30).
  Les connecteurs d'annonces (BOAMP, TED, DECP) n'utilisent donc ni le pool
  d'UA tournants ni le proxy résidentiel d'`http_humain` ; cohérent avec la
  politique de désactivation documentée pour `boamp` / `data_gouv`.
- **Fingerprint TLS Chrome non garanti.** La docstring de
  `creer_session_humaine` mentionne curl_cffi, mais `http_client` force le
  backend `requests` (curl_cffi désactivé). L'anti-ban repose alors sur les
  headers + UA tournant + proxy, pas sur l'empreinte TLS (à confirmer selon
  l'environnement de déploiement).
- **`jitter` ne dort pas** : il renvoie une valeur, l'appelant doit ensuite
  faire le `sleep` lui-même (lignes 232-239).
- **`heure_actuelle_est_bureau` utilise l'heure locale** (`datetime.now()`,
  ligne 200) : le résultat dépend du fuseau de la machine d'exécution.
