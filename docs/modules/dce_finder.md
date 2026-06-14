# Module dce_finder

Documentation du fichier `dce_finder.py` (en-tête : « dce_finder.py v3 »).

Cette documentation décrit uniquement le comportement réel du code. Chaque
affirmation renvoie à la fonction et aux lignes du source. Les points
incertains sont signalés par « (à confirmer) ».

---

## Rôle

Résoudre l'URL DCE (dossier de consultation des entreprises) d'un marché à
partir des champs structurés eForms renvoyés par les API sources BOAMP
(Opendatasoft) et TED v3.

Le module ne télécharge pas le DCE ; il se contente d'identifier l'URL la
plus exploitable (idéalement une URL « spécifique » menant directement à la
consultation), avec à défaut une URL de recherche PLACE pré-remplie en
fallback (constante `URL_PLACE_RECHERCHE`, lignes 32-35).

Le docstring de tête (lignes 1-21) documente la découverte centrale : le
champ eForms contenant l'URL DCE pour BOAMP est
`donnees.EFORMS.ContractNotice.cac:TenderingTerms.cac:CallForTendersDocumentReference.cac:Attachment.cac:ExternalReference.cbc:URI`
(chemin repris dans `_extraire_uri_lot`, lignes 224-234, mais relatif à un
objet *lot* — voir cascade).

---

## Fonction principale `trouver_urls_dce(marche, verbose)`

Définie lignes 639-732. Point d'entrée public unique.

Entrée : un dict `marche` dont sont lus `source` et `reference_externe`
(lignes 658-659). `verbose` (défaut `False`) active des `print` de debug en
fin de fonction (lignes 721-731).

Initialise un dict `base` (lignes 661-673) avec les clés :

```
url_dce, url_recherche, qualite, buyer_profile, champ_source,
reference_ft, api_recuperee, urls_dce, html_fallback,
n_plateformes_trouvees, incidents
```

Comportement (ordre exact du code) :

1. Si `source` ou `ref` manquant → retourne `base` tel quel (lignes 675-676),
   c'est-à-dire `qualite="absente"`, `api_recuperee=False`, `url_recherche`
   pré-remplie avec `ref or ""`.
2. Si `source == "BOAMP"` (lignes 678-683) : appelle `_fetch_record_boamp(ref)`.
   Si un record est renvoyé, met `api_recuperee=True` et fusionne le résultat
   de `_extraire_dce_boamp(record, ref)` (seules les clés déjà présentes dans
   `base` sont copiées — `base.update({k: v ... if k in base})`, ligne 683).
3. Si `source == "TED"` (lignes 684-689) : appelle `_fetch_notice_ted(ref)`
   puis `_extraire_dce_ted(notice, ref)`, même logique de fusion filtrée.
   (Toute autre valeur de `source` laisse `api_recuperee=False`.)
4. Garde-fou final côté agent (lignes 691-698) : si `url_dce` est non vide ET
   `_est_url_cote_agent(url_dce)` est vrai, l'URL est écartée — on ajoute un
   incident `{"raison": "url_cote_agent_non_reecrivable", "url": ...}`, puis
   `url_dce=None`, `qualite="absente"`, `champ_source=None`. Couvre aussi TED.
5. Journalisation des incidents (lignes 700-710) : pour chaque incident,
   appel à `tendia_logs.logger_evenement_marche("dce-finder", mid, {"incident_url_agent": inc})`
   où `mid = marche.get("id") or ref`. L'import et l'appel sont enveloppés
   dans un `try/except: pass` — « le logging ne doit jamais casser la
   recherche d'URL » (ligne 710).
6. Compat ancienne API (lignes 712-719) : si `url_dce` présent, reconstitue
   `urls_dce = [{"plateforme": "PLACE", "url": url_dce, "source_extraction": "api_eforms"}]`
   et met `n_plateformes_trouvees = 1`.
7. Retourne `base` (ligne 732).

Note : le docstring de retour (lignes 645-656) liste `qualite` comme
`"directe" | "racine" | "absente"`, mais la cascade BOAMP produit aussi
`"via_keyword"` (voir `_extraire_dce_boamp`). La valeur `html_fallback`
reste toujours `False` (jamais réécrite dans le code).

---

## Cascade d'extraction BOAMP `_extraire_dce_boamp`

Définie lignes 382-531. Reçoit `record` (record BOAMP brut) et `reference`.

Préparation (lignes 403-443) :
- `donnees = _parser_donnees(record)` (le champ `donnees` est un JSON string
  imbriqué, parsé par `_parser_donnees`, lignes 55-63).
- Initialise `out` avec `qualite="absente"`, `url_recherche` pré-remplie,
  `incidents=[]`.
- Buyer profile : lu via `_get_chemin` au chemin
  `EFORMS > ContractNotice > cac:ContractingParty > cbc:BuyerProfileURI`
  (lignes 415-421).
- Référence interne acheteur : `reference_ft = _extraire_reference_ft(donnees)`
  (lignes 424-426).
- Lots : `EFORMS > ContractNotice > cac:ProcurementProjectLot` (lignes 429-432),
  normalisé en liste `lots` (dict unique ou liste, lignes 433-438).
- `uris_trouvees` : pour chaque lot, `_extraire_uri_lot(lot)` (lignes 439-443).

### Niveau 1 — URL spécifique dans eForms (chemin UBL standard)

Lignes 445-459. Pour chaque URI de `uris_trouvees` qui passe
`_est_url_specifique` : applique `_corriger_url_agent`. Si incident → ajouté à
`out["incidents"]` et on continue (URL écartée). Sinon → `url_dce`,
`qualite="directe"`, `champ_source="cac:CallForTendersDocumentReference"`
(suffixé `" (réécrite agent→entreprise)"` si l'URL a été réécrite,
lignes 456-458), et **retour immédiat**.

### Niveau 1bis — recherche récursive dans tout le payload eForms

Lignes 461-494. Si le chemin standard n'a rien donné :
- `urls_eforms = _chercher_urls_dans_eforms(donnees)` collecte récursivement
  toutes les URLs string pointant vers une plateforme MP connue (ligne 466).
- Filtre `_est_url_specifique` → `urls_specifiques` (ligne 469).
- Chaque URL passe `_corriger_url_agent` ; incidents ajoutés, URLs écartées
  ou réécrites (lignes 472-479).
- Heuristique de priorité (lignes 484-490) : on préfère les URLs contenant
  l'un de `consultation`, `detail`, `annonce`, `id=`, `pcslid=`, `csl_` ;
  sinon la première URL spécifique.
- Si une URL est choisie → `url_dce`, `qualite="directe"`,
  `champ_source="recherche récursive eForms"`, **retour** (lignes 491-494).

### Niveau 2 — recherche par référence interne acheteur (mot-clé)

Lignes 496-521. Deux sous-étapes :
- **2a — PLACE en priorité** (lignes 498-504) : si `reference_ft`, appelle
  `_chercher_url_dce_via_place(reference_ft)`. Si trouvé → `url_dce`,
  `qualite="via_keyword"`, `champ_source=f"PLACE keyWord={reference_ft}"`,
  retour.
- **2b — plateforme Atexo blanche du BuyerProfile** (lignes 506-521) : si
  `reference_ft` ET `buyer_profile`, et que le buyer_profile est un domaine
  plateforme MP (`_domaine_est_plateforme_mp`) **mais pas** une URL spécifique
  (`not _est_url_specifique(bp)`), appelle
  `_chercher_url_dce_via_atexo(reference_ft, bp)`. Si trouvé →
  `qualite="via_keyword"`, `champ_source=f"Atexo keyWord={reference_ft} sur {bp}"`,
  retour.

### Niveau 3 — URL racine seulement

Lignes 523-531. On ne déclare `qualite="racine"` que s'il existait au moins
une URI eForms **exploitable** non côté agent :
`if any(not _est_url_cote_agent(u) for u in uris_trouvees)` →
`qualite="racine"`, `champ_source="cac:CallForTendersDocumentReference (racine)"`.
Sinon `qualite` reste `"absente"`. Note : à ce niveau, `out["url_dce"]` n'est
**pas** renseigné — seule la qualité change (le fallback exploitable est
`url_recherche`). (à confirmer : intention métier d'une qualité « racine »
sans `url_dce` ; le code laisse bien `url_dce=None`.)

---

## Extraction TED `_extraire_dce_ted`

Définie lignes 587-632. Reçoit `notice` et `publication_number`.

- Initialise `out` (lignes 589-595) — **sans** clés `reference_ft` ni
  `incidents` (contrairement à la branche BOAMP).
- Candidats (lignes 597-608) : agrège les champs `document-url-lot`,
  `document-url-part`, `submission-url-lot` (gère str, list, autre via `str()`).
- Premier candidat passant `_est_url_specifique` → `url_dce`,
  `qualite="directe"`, `champ_source="document-url"` (lignes 610-615).
- Buyer profile (lignes 617-626) : lit `buyer-profile` (str ou premier élément
  de liste). Si pas d'`url_dce` et que le buyer profile est spécifique →
  l'utilise comme `url_dce`, `champ_source="buyer-profile"`.
- Sinon, s'il y avait des candidats mais aucun spécifique →
  `qualite="racine"`, `champ_source="document-url (racine)"` (lignes 628-630).

Les champs TED ciblés sont listés dans la constante `TED_FIELDS_DCE`
(lignes 539-554), identifiés « par diagnostic » selon le commentaire.

---

## Helpers

- **`_est_url_specifique(url)`** (lignes 77-104) : True si l'URL mène à une
  consultation précise. Critères : présence d'un paramètre
  `id=`/`idconsultation=`/`refconsultation=` (regex, lignes 88-89) ; sinon
  query de longueur ≥ 10 ; sinon path non vide et hors de l'ensemble
  `{"entreprise", "fr", "fr/entreprise"}` (lignes 92-101). Toute exception
  d'`urlparse` est silencieusement ignorée → retourne `False`.

- **`_domaine_est_plateforme_mp(url)`** (lignes 182-191) : True si le `netloc`
  (minuscule) contient l'un des motifs de `DOMAINES_PLATEFORMES_MP`
  (lignes 147-179 : marches-publics.gouv.fr, achatpublic.com, megalis,
  maximilien, klekoon, demat-ampa, etc., plus des motifs génériques comme
  `mairie-`, `metropole.`, `ville-`, `marches.`). Attention : ces motifs
  larges peuvent matcher des domaines non-MP (à confirmer côté faux positifs).

- **`_chercher_urls_dans_eforms(obj, max_profondeur=12)`** (lignes 194-217) :
  parcours récursif (dict/list) bornée à 12 niveaux ; collecte les strings
  commençant par `http://`/`https://` et passant `_domaine_est_plateforme_mp`.

- **`_chercher_url_dce_via_place(reference_ft, verbose)`** (lignes 367-379) :
  alias historique qui appelle `_chercher_url_dce_via_atexo` avec
  `base_url="https://www.marches-publics.gouv.fr"`.

- **`_chercher_url_dce_via_atexo(reference_acheteur, base_url, verbose)`**
  (lignes 268-364) : effectue une vraie requête HTTP de recherche par mot-clé
  sur une plateforme Atexo/MPE. Construit
  `{base_url}/?page=Entreprise.EntrepriseAdvancedSearch&searchAnnCons&keyWord={reference}`
  (lignes 299-303), fait un `requests.get` **direct** (timeout 20,
  `allow_redirects=True`, User-Agent navigateur Chrome simulé, lignes 304-314).
  Si statut ≠ 200 → `None`. Remplace `&amp;` par `&` dans le HTML (ligne 319),
  puis cherche par priorité décroissante :
  1. lien `EntrepriseDetailsConsultation...id=...orgAcronyme=...` (lignes 328-335) ;
  2. tout couple `id=NNN&orgAcronyme=YYY`, reconstruit en URL canonique
     `EntrepriseDetailsConsultation` (lignes 337-346) ;
  3. nouveau format `/entreprise/consultation/NNN?...orgAcronyme=` (lignes 348-355).
  Retourne `None` si rien trouvé ou sur exception. Les URLs relatives sont
  normalisées par la closure `_normaliser_url` (lignes 321-326).

- **`_extraire_reference_ft(donnees)`** (lignes 237-265) : extrait la référence
  interne acheteur depuis `EFORMS > ContractNotice > cac:ProcurementProject >
  cbc:ID`. Gère le cas string directe et le cas dict
  `{"@schemeName": "InternalID", "#text": "..."}` (lignes 257-264). Le suffixe
  `_ft` (France Travail) est conservé « pour compatibilité historique » avec le
  champ persisté `reference_ft` (docstring lignes 247-250).

- Autres helpers internes : `_fetch_record_boamp` (lignes 42-52),
  `_parser_donnees` (55-63), `_get_chemin` (66-74), `_extraire_uri_lot`
  (224-234), `_fetch_notice_ted` (557-584).

---

## Fix `/agent/` vs `/entreprise/`

Les plateformes Atexo exposent des URLs réservées aux **acheteurs** (espace
agent), inutiles et inaccessibles à un soumissionnaire. Le crawler en capture
parfois à la place de l'interface entreprise. Mécanisme de défense :

- **`RE_URL_AGENT`** (ligne 110) : regex `(?:/agent(?:/|$|\?)|[?&]page=Agent\.)`
  (insensible à la casse) qui détecte les deux formes : chemin `/agent/`
  (Atexo récent) et paramètre `?page=Agent.X` (PLACE classique).

- **`_est_url_cote_agent(url)`** (lignes 113-115) : True si `RE_URL_AGENT`
  matche (sur `url or ""`).

- **`_corriger_url_agent(url)`** (lignes 118-141) : retourne un tuple
  `(url_utilisable, incident)` :
  - URL non-agent → `(url, None)`, inchangée (ligne 133-134).
  - chemin `/agent/` → tentative de swap `/agent/` → `/entreprise/`
    (`re.sub`, `count=1`, lignes 135-137). Garde-fou : on revérifie
    `_est_url_cote_agent` sur la version réécrite ; si le marqueur a bien
    disparu → `(url_réécrite, None)` (lignes 138-139).
  - sinon (ex. PLACE `?page=Agent.X`) → **non réécrivable** : retour
    `(None, {"raison": "url_cote_agent_non_reecrivable", "url": url})`
    (ligne 141). Motif documenté lignes 126-131 : le token de page diffère
    (`Agent.DetailConsultation` ≠ `Entreprise.EntrepriseDetailsConsultation`)
    et l'`orgAcronyme` requis par les downloaders est absent.

- **Intégration dans la cascade** : Niveau 1 (lignes 448-453) et Niveau 1bis
  (lignes 473-479) appellent `_corriger_url_agent`, écartent les URLs non
  réécrivables et accumulent les incidents.

- **Garde-fou final** dans `trouver_urls_dce` (lignes 691-698) : couvre aussi
  TED — toute `url_dce` survivante côté agent est écartée + incident +
  `qualite="absente"`.

- **Log JSONL incident** (lignes 700-710) : chaque incident est journalisé via
  `tendia_logs.logger_evenement_marche("dce-finder", mid, {"incident_url_agent": inc})`,
  qui écrit une ligne JSON dans `logs/dce-finder_<YYYY-MM-DD>.jsonl`
  (cf. `tendia_logs.logger_evenement_marche`).

---

## Récupération API (BOAMP / TED via http_utils, SANS proxy)

- **BOAMP** — `_fetch_record_boamp(idweb)` (lignes 42-52) : appelle
  `http_utils.get_json` sur
  `https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records`
  avec `params={"where": 'idweb="..."', "limit": 1}`. Retourne le premier
  `results[i]` ou `None` (toute exception → `None`, lignes 47-50).

- **TED** — `_fetch_notice_ted(publication_number)` (lignes 557-584) : POST
  via `http_utils.post_json` sur `https://api.ted.europa.eu/v3/notices/search`
  avec un body `{query, fields=TED_FIELDS_DCE, limit=1, scope="ALL",
  checkQuerySyntax=False, paginationMode="PAGE_NUMBER"}`. En cas d'exception,
  **retry** avec un sous-ensemble minimal de champs
  `["publication-number", "notice-title", "document-url-lot", "buyer-profile"]`
  (lignes 573-582). Retourne `notices[0]`/`results[0]` ou `None`.

- **SANS proxy** : `http_utils` (`get_json` lignes 48-87, `post_json`
  lignes 90-130) utilise une `requests.Session()` partagée (lignes 27-32)
  **sans aucune configuration de proxy** ; politesse 0,5 s/hôte, 3 tentatives,
  retry sur réseau et 5xx, pas de retry sur 4xx. La recherche par mot-clé
  Atexo (`_chercher_url_dce_via_atexo`, lignes 304-314) fait un `requests.get`
  direct, lui aussi **sans proxy**. C'est volontaire : ces API publiques sont
  appelées en direct, contrairement aux downloaders DCE qui passent par proxy.

---

## Dépendances et variables d'environnement

Imports (lignes 23-29) :
- standard : `json`, `re`, `typing`.
- tiers : `requests` (au niveau module, et re-importé localement ligne 290
  dans `_chercher_url_dce_via_atexo`).
- internes : `http_utils.get_json`, `http_utils.post_json`.
- import paresseux (dans `try/except`) : `tendia_logs` (ligne 703), `urllib.parse`
  importé localement (lignes 93, 187, 39 côté http_utils).

**Aucune variable d'environnement** n'est lue par ce module (aucun
`os.environ` / `os.getenv`). Les URLs API sont codées en dur.

---

## Exemples d'usage

### Appelant réel — `tendia_dce.py`

`tendia_dce.py` importe le module (ligne 31) et appelle (ligne 416) :

```python
import dce_finder
...
resultat = dce_finder.trouver_urls_dce(marche, verbose=False)
qualite = resultat.get("qualite", "absente")
if resultat.get("reference_ft"):
    ...
if resultat.get("url_dce"):
    ...
# persistance (tendia_dce.py, lignes 434-440) :
marche["url_dce"]            = resultat.get("url_dce")
marche["reference_ft"]       = resultat.get("reference_ft")
marche["url_recherche_place"] = resultat.get("url_recherche")
marche["dce_qualite"]        = qualite
```

### CLI (`__main__`, lignes 735-748)

```
python dce_finder.py <BOAMP|TED> <reference>
```

Construit un `marche` minimal `{"source": ..., "reference_externe": ...}`
(plus une `url_avis` informative), appelle `trouver_urls_dce(..., verbose=True)`
et imprime le résultat en JSON indenté (lignes 746-748).

---

## Pièges connus

- **Qualité `racine` non déclarée si la seule URI était côté agent**
  (lignes 523-531) : `_extraire_dce_boamp` ne passe à `qualite="racine"` que
  si `uris_trouvees` contient au moins une URL **non** côté agent. Si la seule
  URI capturée était une URL acheteur (rejetée plus haut), la qualité reste
  `"absente"` — rien d'exploitable n'a été retenu.

- **PLACE `?page=Agent.X` non réécrivable** : `_corriger_url_agent`
  (lignes 140-141) ne sait réécrire que le swap de chemin `/agent/` →
  `/entreprise/`. Une URL PLACE avec `page=Agent.X` n'est pas convertible
  (token de page différent, `orgAcronyme` absent) → URL écartée + incident
  journalisé, jamais stockée.

- **`html_fallback` toujours `False`** : présent dans le dict de retour pour
  compatibilité, mais jamais positionné à `True` dans le code.

- **`qualite="racine"` sans `url_dce`** : à ces niveaux (BOAMP Niveau 3 et TED
  branche racine), `url_dce` reste `None` ; seul `url_recherche` est
  exploitable par l'appelant. (à confirmer : comportement attendu côté
  consommateur.)

- **Branche TED sans `incidents`/`reference_ft`** : `_extraire_dce_ted`
  n'initialise pas ces clés (lignes 589-595), mais elles existent dans `base`
  côté `trouver_urls_dce` ; la fusion filtrée (ligne 689) ne les écrase donc
  pas. Le garde-fou final agent (lignes 691-698) reste actif pour TED via
  `base["incidents"]`.

- **Motifs de domaines larges** dans `DOMAINES_PLATEFORMES_MP` (`mairie-`,
  `metropole.`, `ville-`, `marches.`, `region-`...) : risque de faux positifs
  lors de la recherche récursive `_chercher_urls_dans_eforms` (à confirmer).
