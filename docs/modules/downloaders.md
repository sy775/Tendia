# Téléchargeurs DCE

Résumé des 4 téléchargeurs DCE anonymes du dépôt. Chaque module récupère le
Dossier de Consultation des Entreprises (DCE) d'un marché sans inscription
manuelle, puis le range dans `<repertoire_dce>/<id_marche>/`.

Source documentée (chemins absolus) :

- `C:\Users\sai-y\Tendia\dematis_downloader.py`
- `C:\Users\sai-y\Tendia\aws_downloader.py`
- `C:\Users\sai-y\Tendia\atexo_downloader.py`
- `C:\Users\sai-y\Tendia\achatpublic_downloader.py`

> Méthode : ce document décrit uniquement ce que le code fait, avec renvois aux
> fonctions et numéros de ligne. Les points non confirmés par le code sont
> signalés « (à confirmer) ».

---

## Vue d'ensemble

| Plateforme | Host | Captcha | Mécanisme | Proxy par défaut |
|---|---|---|---|---|
| Dematis (e-marchespublics) | `e-marchespublics.com` (`HOST_DEMATIS`, ligne 82) ; pièces servies par `private.e-marchespublics.com` | Oui (image, 2captcha) | Workflow HAR : annonce → lien anonyme token SHA-1 40 hex → page captcha (form `inscriptionEntreprise`) → POST → 302 `acces_dce` → `getfile.php` | ON (`plateforme="dematis"`, ligne 547) |
| AWS-Achat (marches-publics.info) | `www.marches-publics.info` (`URL_BASE`, ligne 54) ; CDN `downloads.awsolutions.fr` (`URL_CDN`, ligne 56) | Oui (image custom, 2captcha) | ColdFusion (CFID/CFTOKEN en query string, pas de cookie) : `choixDCE` → `avertissement` → `cnxAnonyme` → `verifLotsDCE` → `actDCE2` → URL CDN | ON (`plateforme="aws_achat"`, ligne 426) ; CDN téléchargé SANS proxy (`_session_sans_proxy`, ligne 752) |
| Atexo (PLACE + forks) | `marches-publics.gouv.fr` + forks listés `HOSTS_ATEXO` (lignes 41-52) | Non | 2 POST Prado/Atexo : GET formulaire → POST anonyme + CGU → postback `completeDownload` → ZIP | ON pour `atexo` ; pour `place` (gouv.fr) désactivable via `TENDIA_PROXY_FOR_PLACE=0` (lignes 152-155) |
| achatpublic.com | `www.achatpublic.com` (`URL_BASE_ACHATPUBLIC`, ligne 33) | Non | GET `ent_detail.do` (parse `dceId`/`cycNum`) → POST `telechargerDCE.action` → ZIP → décompression imbriquée | ON (`plateforme="achatpublic"`, ligne 178) |

Le « proxy par défaut » dépend de `http_humain._proxy_pour_plateforme` :
proxy ON sauf si `TENDIA_PROXY_FOR_<PLATEFORME>=0` (http_humain.py lignes 87-108).

---

## API commune

Les 4 modules exposent deux fonctions, mais les **signatures diffèrent** (pas
d'interface strictement uniforme). Le wrapper `telecharger_dce_pour_marche`
prend partout un `marche: dict` (clés lues : `marche["id"]`, `marche["url_dce"]`)
et un `repertoire_dce`, et renvoie un contrat enrichi
(`{id_marche, ok, skip, erreur, chemin, duree_secondes, ...}`).

### dematis_downloader

```python
telecharger_dce(url_dce, dossier_destination, api_key_2captcha=None,
                verbose=True, timeout=120, decompresser=True,
                session_id=None, verify_ssl=True) -> dict          # ligne 497
telecharger_dce_pour_marche(marche, repertoire_dce, api_key_2captcha=None,
                            verbose=True, max_retries_ban=2,
                            verify_ssl=True) -> dict               # ligne 795
```

Entrée : `url_dce` = URL de la page annonce (ou directement la page anonyme).
`telecharger_dce` renvoie notamment `fichiers_telecharges`, `taille_octets_total`,
`nb_captcha_resolus`, `variante_lien`, `nb_zip_internes_decompressed`,
`ssl_verify_desactive`, `doublons`, `nb_doublons_ecartes` (lignes 522-526, 744-745).

### aws_downloader

```python
telecharger_dce(idm, dossier_destination, api_key_2captcha=None,
                verbose=True, timeout=180, decompresser=True,
                session_id=None) -> dict                          # ligne 383
telecharger_dce_pour_marche(marche, repertoire_dce, api_key_2captcha=None,
                            verbose=True, max_retries_ban=3) -> dict  # ligne 772
```

Entrée : `idm` = identifiant marché AWS-Achat. Le wrapper extrait l'IDM depuis
`marche["url_dce"]` via `_extraire_idm_depuis_url` (ligne 96, lit le paramètre
`IDM=`). `timeout` par défaut 180 s (plus que Dematis). Pas de paramètre
`verify_ssl`.

### atexo_downloader

```python
telecharger_dce(id_atexo, org_acronyme, chemin_destination, url_base,
                verbose=True, timeout=120, session_id=None) -> dict   # ligne 131
telecharger_dce_pour_marche(marche, repertoire_dce, verbose=True) -> dict  # ligne 296
```

Particularités : signature SANS `api_key_2captcha` ni `decompresser` (pas de
captcha, le résultat est un seul ZIP non décompressé ici) ; le 3ᵉ argument est
`chemin_destination` (chemin **du fichier ZIP**, pas un dossier), et un 4ᵉ
argument obligatoire `url_base`. Le wrapper construit
`<repertoire_dce>/<id>/dce_<id_atexo>.zip` (ligne 323) et déduit `id_atexo` /
`org_acronyme` / `url_base` depuis `marche["url_dce"]`.

### achatpublic_downloader

```python
telecharger_dce(pcslid, chemin_destination, verbose=True, timeout=120,
                decompresser=True, session_id=None) -> dict           # ligne 159
telecharger_dce_pour_marche(marche, repertoire_dce, verbose=True) -> dict  # ligne 292
```

Entrée : `pcslid` (extrait par `_extraire_pcslid_depuis_url`, ligne 49).
`chemin_destination` = chemin du ZIP ; le wrapper construit
`<repertoire_dce>/<id>/dce_<pcslid>.zip` (ligne 315). Pas de captcha.

---

## Dematis (e-marchespublics)

Module `dematis_downloader.py`. Workflow calé sur un HAR de référence
(docstring lignes 1-51).

### Workflow réseau (`telecharger_dce`, ligne 497)

1. **GET page annonce** (étape 1, lignes 554-569). Forçage encodage UTF-8 si
   `encoding` absent ou `ISO-8859-1` (ligne 558, « piège connu : Dematis sert de
   l'UTF-8 »). Détection de ban via `ressemble_a_page_ban` (ligne 571).
2. **Extraction des liens anonymes** (`_extraire_liens_anonymes`, ligne 183 ;
   appel ligne 576). La page annonce expose deux liens : un token **32 hex (MD5)
   = leurre** qui redirige vers l'accueil, et un token **40 hex (SHA-1) = le bon**.
   La regex `_RE_TOKEN_40` (ligne 180) reconnaît le SHA-1 ; le tri (ligne 209)
   place les tokens 40 hex en tête. Repli : onglet « dossier »
   (`_extraire_lien_onglet_dossier`, ligne 219) ou entrée directe si l'URL porte
   déjà `_marche_public_anonyme_` ou un form captcha (lignes 593-598).
3. **GET page dossier → captcha** (lignes 619-651). Form `inscriptionEntreprise`
   parsé par `_extraire_form_captcha` (ligne 253) : hidden `captcha[id]` (32 hex),
   champ texte `captcha[input]`, submit `submit`. Le champ `captchaResult` est un
   **leurre exclu** (lignes 19, 293, 676-677). Image captcha via
   `_extraire_captcha_img` (ligne 240). Un candidat redirigé vers la racine `/`
   est jugé invalide (lignes 636-638). Le captcha est régénéré à chaque GET de la
   page dossier (commentaire ligne 610).
4. **Résolution 2captcha** (`_resoudre_captcha_2captcha`, importé d'aws_downloader,
   ligne 665). `ErreurSolde2Captcha` → arrêt avec `solde_2captcha_epuise=True`
   (lignes 666-669).
5. **POST captcha** sur la même URL, `allow_redirects=False` (lignes 678-693).
   Payload = champs du form + solution dans chaque `champs_captcha`. **Succès =
   302** avec `Location` contenant `acces_dce_marche_public_anonyme` (ligne 704) ;
   un captcha refusé renvoie 200 (re-render) → nouvelle tentative. Repli tolérant :
   200 contenant déjà des `getfile.php` accepté (lignes 722-729).
6. **GET acces_dce** (lignes 707-715) → liste des pièces servies par
   `private.e-marchespublics.com/dce/getfile.php?id=<n>&anonyme=<token40>&fromnew`
   (`_extraire_fichiers_telechargeables`, ligne 359, priorité absolue aux liens
   `getfile.php`).
7. **Téléchargement** par pièce (`_telecharger_fichier`, ligne 459 ; retry sur
   timeout/5xx, `DL_MAX_ESSAIS=3`), puis décompression ZIP imbriqué (étape 6,
   lignes 773-784).

### Fix cookie PHPSESSID `Domain=` vide

`_installer_fix_cookies_domaine_vide` (ligne 137, installé ligne 550). Dematis
pose `PHPSESSID` avec un attribut `Domain=` **vide/malformé** que
`http.cookiejar`/requests rejette ; or la solution du captcha est stockée dans la
session PHP. Sans le correctif, le POST renvoie « code de vérification incorrect »
même avec la bonne solution. Le hook réponse (`_RE_DOMAIN_VIDE`, ligne 133)
ré-injecte le cookie sur l'hôte de la requête (lignes 148-169).

### Normalisation mojibake

`_normaliser_nom_mojibake` (ligne 309) répare les noms de fichiers en mojibake
(UTF-8 relu en latin-1 : `rÃ©seaux` → `réseaux`), jusqu'à 3 passes pour le
mojibake double, idempotente. La page `acces_dce` est décodée en **latin-1 sans
perte** (`_decoder_liste_sans_perte`, ligne 342) car elle mêle octets UTF-8 et
latin-1. Le nom retenu (`_nom_fichier`, ligne 441) applique systématiquement la
normalisation, y compris sur `Content-Disposition` (souvent en mojibake).

### Dédoublonnage getfile

`_dedupliquer_fichiers` (ligne 409) : le serveur liste parfois le même fichier 2×
sous des `id` getfile.php différents. Clé de dédup = (nom normalisé en minuscules,
taille). La page n'expose pas de taille → dédup de fait par nom (lignes 417-418).
Première occurrence conservée ; les doublons sont remontés dans `out["doublons"]`
et `nb_doublons_ecartes`, et tracés en log (lignes 744-745, 867-871).

### verify_ssl

Paramètre `verify_ssl=True` par défaut (lignes 505, 801). Le poste Windows a un
bundle `certifi` incomplet (CA intermédiaire absent) → `truststore` est injecté
dans `http_client.py` pour utiliser le magasin Windows (docstring lignes 39-46).
`verify_ssl=False` reste un contournement ponctuel, journalisé via
`ssl_verify_desactive` (lignes 536-545). C'est le seul des 4 modules à exposer ce
paramètre.

---

## AWS-Achat (marches-publics.info)

Module `aws_downloader.py`, moteur **ColdFusion**. Particularité : **pas de
cookie HTTP**, la session est portée par `CFID` + `CFTOKEN` passés en query
string sur toutes les requêtes (docstring lignes 24-25).

### Workflow (`telecharger_dce`, ligne 383)

1. **GET `dematEnt.choixDCE`** (étape 1, lignes 432-447) → établit la session.
   `CFID`/`CFTOKEN` extraits par `_extraire_cfid_cftoken_depuis_html` (ligne 117),
   avec repli sur l'URL finale (lignes 451-454). Absence → suspicion ban si
   `ressemble_a_page_ban` (lignes 455-462).
2. **GET `dce.avertissement`** (étape 2, lignes 473-506) → page captcha. Parse
   `strNomImage` (timestamp ms) et `hashVal` (SHA-256, 64 hex) via
   `_extraire_str_nom_image_et_hashval` (ligne 141).
3. **GET image captcha** `/captcha/Captcha_<strNomImage>.png` (étape 3, lignes
   508-522).
4. **2captcha** (étape 4, lignes 524-538, `_resoudre_captcha_2captcha` ligne 288).
5. **POST `dce.cnxAnonyme`** (étape 5, lignes 540-582), `allow_redirects=False`.
   Payload : `type`, `XFAOK`, `strNomImage`, `hashVal`, `captchaVal=<solution>`.
   **302 = succès**, 200 = captcha refusé → retry (max `TWOCAPTCHA_MAX_TENTATIVES`
   = 3). Patch `cfid_refresh` : ColdFusion **régénère CFID/CFTOKEN** après ce POST,
   les nouveaux sont extraits du header `Location` et propagés aux étapes 6-7
   (lignes 564-578).
6. **GET `dce.verifLotsDCE`** (étape 6, lignes 592-615) → page sélection des lots.
   `_extraire_lots_depuis_verif_lots_dce` (ligne 168) lit les checkboxes `lots`.
7. **POST `dce.actDCE2`** (étape 7, lignes 621-647) avec tous les lots. Patch
   `lots_mono` : en mono-lot, envoyer explicitement `lots=0` sinon « ANOMALIE
   12164096 » (lignes 626-634).
8. **Parse URL CDN** (`_extraire_url_cdn_depuis_actdce2`, ligne 199 ; appel ligne
   650). Conserve `downloads.awsolutions.fr/dce/attachment/<TOKEN>` et les liens
   AAPC `fuseaction=dce.TDoc`. Filtre `LABELS_IGNORER` (« Conditions d'accès… »,
   lignes 78-81).
9. **Téléchargement CDN** (`_telecharger_fichier_cdn`, ligne 711 ; retry
   `CDN_MAX_ESSAIS=3`), nom = `Content-Disposition`.
10. **Décompression** ZIP imbriqués (étape 10, lignes 686-698).

### Patch cdn_bypass (CDN sans proxy)

`_session_sans_proxy` (ligne 752), appelé par `_telecharger_fichier_cdn`
(ligne 720). Les téléchargements depuis `downloads.awsolutions.fr` (CDN externe
non protégé) se font **sans proxy** : on copie les en-têtes de la session source
mais on vide `proxies` (lignes 763-770). Objectif déclaré : économiser ~99 % des
coûts proxy ; le CDN ne banne pas les IP (commentaire lignes 755-758).

---

## Atexo (PLACE marches-publics.gouv.fr + forks)

Module `atexo_downloader.py`. Moteur Prado/Atexo, **sans captcha**, généralisé à
5+ plateformes partageant le même moteur (docstring lignes 4-21). Détection de la
plateforme : `place` si `marches-publics.gouv.fr` dans l'URL base, sinon `atexo`
(ligne 153).

### Détection de l'URL base

`_detecter_url_base` (ligne 59) : renvoie `scheme://host` si l'URL DCE est Atexo,
sinon `None`. Reconnaît par host connu (`HOSTS_ATEXO`, lignes 41-52) **ou** par
signature Atexo (`orgacronyme=` + `entreprise.` dans l'URL, ligne 74). Exclut
explicitement `_HOSTS_EXCLUS` : e-marchespublics, marches-publics.info,
achatpublic, marches-securises (lignes 55-57, 68-69).

### Workflow 2-POST (`telecharger_dce`, ligne 131)

1. **GET formulaire identité** (`Entreprise.EntrepriseDemandeTelechargementDce`,
   `_construire_url_formulaire` ligne 80 ; étape 1 lignes 161-175). Vérifie la
   présence de `EntrepriseFormulaireDemande` dans le HTML (ligne 170).
2. **POST 1 : anonyme + CGU** (étape 2, lignes 177-240). Champs cachés Prado
   collectés par `_extraire_inputs_form` (ligne 88, incluant `PRADO_PAGESTATE`),
   plus : la radio dont la valeur contient `choixAnonyme` (lignes 186-196), la
   checkbox `accepterConditions` mise à `on` (lignes 198-206), le submit
   `valider` (lignes 208-214). Action lue depuis le `<form name="main_form">`
   (lignes 216-227). Succès = présence de `completeDownload` dans la réponse
   (ligne 235).
3. **POST 2 : postback Prado `completeDownload`** (étape 3, lignes 242-291).
   `event_target` extrait par `_trouver_event_target` (ligne 113). Payload =
   champs du form + `PRADO_POSTBACK_TARGET=<event_target>` +
   `PRADO_POSTBACK_PARAMETER=""`. Réponse streamée vers le ZIP ; **validation
   magic bytes `PK`** (lignes 277-281) sinon erreur. Aucun captcha, aucune
   décompression dans ce module.

---

## achatpublic.com

Module `achatpublic_downloader.py`. **Pas de captcha, pas d'auth, pas de
cookie/session** (docstring ligne 19). Workflow (`telecharger_dce`, ligne 159) :

1. **GET page détail** `ent_detail.do?PCSLID=…` (étape 1, lignes 185-196).
2. **Extraction `dceId` / `cycNum`** (`_extraire_dce_id_et_cyc_num`, ligne 65) :
   parse les onclick JS `getDceDetails('<dceId>','<cycNum>')`, repli
   `submitFormeDownload('<dceId>')` (cycNum=0), repli `jqDownloadWrappGroup_<id>`
   (lignes 69-84).
3. **POST `telechargerDCE.action?PCSLID=…&cycNum=<n>`** (étape 2, lignes 206-266).
   Body : `PCSLID`, `cycNum`, `dceId`, `nomEntiteContact=''`, `nomPointContact=''`,
   `mailPointContact=''`. Réponse HTML sans `Content-Disposition` → erreur (marché
   clos/restreint, lignes 240-243). ZIP streamé puis **validation magic bytes
   `PK`** (lignes 253-258).
4. **Décompression ZIP imbriqué** (étape 3, lignes 268-284). Le ZIP achatpublic
   contient typiquement `DCE/DCE.zip` à dézipper.

`_decompresser_zip_imbrique` (ligne 87) est l'implémentation **partagée** :
décompresse le ZIP externe puis tous les ZIP imbriqués trouvés, max 3 niveaux de
profondeur (lignes 117-150), tolère les ZIP corrompus (`BadZipFile`). C'est cette
fonction qu'`aws_downloader._decompresser_zip_imbrique` (aws ligne 342) et
`dematis_downloader` (import ligne 72) délèguent.

---

## Solveur captcha commun

`aws_downloader._resoudre_captcha_2captcha` (ligne 288) est la brique partagée :
envoie l'image à 2captcha (lib `twocaptcha.TwoCaptcha`, `solver.normal`),
`defaultTimeout=TWOCAPTCHA_TIMEOUT_SEC=90`, `pollingInterval=3`. Lève
`ErreurSolde2Captcha` sur `ZERO_BALANCE`, renvoie `None` sur autre échec.

`dematis_downloader` **réutilise** ce solveur (ainsi que `ErreurSolde2Captcha`,
`_nom_fichier_depuis_headers`, `_sanitiser_nom`, `_request_avec_retry`,
`_decompresser_zip_imbrique`) par import direct depuis aws_downloader
(dematis lignes 66-73). Atexo et achatpublic n'utilisent pas de captcha.

---

## Anti-ban

Tous les modules créent leur session via `http_humain.creer_session_humaine`
(http_humain.py ligne 111) :

- **User-Agent tournant** : pool Chrome/Firefox/Edge/Safari (`USER_AGENTS_POOL`,
  lignes 28-41), choisi aléatoirement par session.
- **Fingerprint TLS Chrome** via `http_client` (backend curl_cffi si dispo, sinon
  requests).
- **Rotation IP** par session-id Bright Data : `_injecter_session_id` insère
  `-session-<sid>` dans l'URL proxy (lignes 68-84). session-id stable = IP stable.
  Les wrappers `telecharger_dce_pour_marche` d'aws et dematis utilisent
  `id_marche` à la tentative 0 puis un UUID à chaque retry ban
  (aws lignes 832-833, dematis lignes 829-830).
- **Délais « humains »** : `attendre_inter_etapes` (1,5-4 s par défaut, ligne 182)
  entre étapes ; aussi `attendre_humain`, `attendre_pause_cumulative` (pause
  longue tous les N marchés, ligne 212), `heure_actuelle_est_bureau` (ligne 195),
  `jitter` (ligne 232).
- **Détection de ban** : `ressemble_a_page_ban` (ligne 242) repère une page
  d'accueil moderne / message de blocage (`_PATTERNS_BAN`, lignes 50-57). Utilisé
  par Dematis (ligne 571) et AWS (lignes 456, 499). Sur ban détecté, les wrappers
  aws/dematis bouclent avec une nouvelle IP jusqu'à `max_retries_ban`, puis
  `etape_erreur="ban_persistant"` (aws lignes 832-850, dematis lignes 829-846).
  **Atexo et achatpublic n'ont PAS de boucle de rotation IP sur ban** (à confirmer
  côté besoin métier).
- **Logs JSONL** : `tendia_logs.logger_evenement_marche(downloader, id, evt)`
  écrit une ligne JSON dans `logs/<downloader>_<YYYY-MM-DD>.jsonl`
  (tendia_logs.py lignes 18, 25-32). Noms de downloader employés : `dematis`,
  `aws-achat`, `atexo`, `achatpublic`.

---

## Variables d'environnement

Toutes lues via `os.environ` (et `.env` via python-dotenv quand présent).

| Variable | Rôle | Lue dans |
|---|---|---|
| `TWOCAPTCHA_API_KEY` | Clé 2captcha (fallback si `api_key_2captcha` non passé) | dematis ligne 531, aws ligne 418 |
| `TENDIA_PROXY_URL` | URL du proxy résidentiel (Bright Data) | http_humain ligne 150 |
| `TENDIA_PROXY_FOR_<PLATEFORME>` | `=0`/`false`/`no`/`off` désactive le proxy pour cette plateforme | http_humain lignes 105-107 |

Plateformes (suffixe de `TENDIA_PROXY_FOR_*`) telles que passées dans le code :
`DEMATIS`, `AWS_ACHAT`, `PLACE`, `ATEXO`, `ACHATPUBLIC`. La désactivation est
documentée comme prévue pour `place`, `boamp`, `data_gouv` (sans ban, http_humain
lignes 92-93) ; `TENDIA_PROXY_FOR_PLACE=0` est explicitement mentionné côté Atexo
(atexo lignes 152-153).

---

## Pièges connus par plateforme

- **Dematis** : ban IP agressif (rotation IP + délais nécessaires) ; cookie
  `PHPSESSID` à `Domain=` vide à ré-injecter sinon captcha toujours « incorrect » ;
  noms de fichiers en mojibake (UTF-8/latin-1 mélangés) ; doublons serveur
  (même fichier sous 2 `id` getfile.php) ; token MD5 32 hex = leurre, ne suivre
  que le SHA-1 40 hex ; SSL `certifi` incomplet sur le poste Windows
  (cf `verify_ssl`). Gros DCE possibles (ex. cité dans le code : ZIP de 325 Mo,
  ligne 414-415) → téléchargements lents.
- **AWS-Achat** : ban IP agressif observé le 13/06/2026 après ~10-15 sessions
  ColdFusion enchaînées (http_humain lignes 11-13) ; CFID/CFTOKEN régénérés après
  `cnxAnonyme` (à repropager) ; mono-lot exige `lots=0` ; CDN externe téléchargé
  sans proxy (patch cdn_bypass).
- **PLACE / Atexo** : PLACE confirmé **sans ban** → proxy désactivable
  (`TENDIA_PROXY_FOR_PLACE=0`) pour économiser ; forks municipaux non listés
  rattrapés par signature `orgAcronyme`+`Entreprise.` ; pas de rotation IP sur
  ban dans ce module ; résultat = ZIP brut non décompressé (validation magic `PK`).
- **achatpublic** : ZIP imbriqué (`DCE/DCE.zip`) à décompresser sinon le qualifier
  ne voit pas les pièces ; réponse HTML au lieu de ZIP = marché clos/restreint ;
  pas de captcha ni de rotation IP.
