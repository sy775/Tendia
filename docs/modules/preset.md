# Module preset

> Documentation du fichier `preset.py` (racine du projet). Basée uniquement sur la lecture du code source. Les numéros de ligne renvoient à l'état actuel de `preset.py`.

## Rôle

`preset.py` est le module central qui charge le **preset actif** (le secteur d'activité de l'organisme) et expose son vocabulaire, ses règles, son schéma de profil et ses paramètres métier au reste du code (docstring d'en-tête, lignes 1-53).

L'objectif déclaré dans la docstring : « aucun code Python (matching.py, llm_extract.py, llm_calibration.py…) ne mentionne plus directement "Qualiopi", "France Travail", "RGE" ou tout autre terme métier. Tout passe par ce module » (lignes 23-25).

Un preset = un secteur d'activité livré par Tendia, matérialisé par un dossier `presets/<code>/` contenant `_schema.json` et `_preset.json`, plus un pointeur global `presets/_actif.json` (lignes 14-21). Les presets installés (constatés sur disque) : `btp`, `conseil`, `energie_renouvelable`, `formation`, `ingenierie`, `it`.

Deux régimes coexistent dans le module :

- **Mono-preset (legacy)** : un seul preset actif, lu via `charger_actif()` / `code_actif()` et les accesseurs `*()` simples (`vocabulaire_llm`, `mots_cles_veille`, `calibration_llm`…).
- **Multi-presets / brief mutualisé (Sprints 2bis & 3)** : pour un marché donné, on route vers les presets pertinents déduits de la classification IA (`presets_pour_domaines`), puis on agrège leurs blocs via les fonctions `*_pour_presets(...)` (commentaires lignes 223-235 et 277-290).

## Structure des presets sur disque

Le module lit deux fichiers par preset (lignes 122-136) :

- `presets/<code>/_schema.json` : JSON-Schema du profil organisme. Chargé dans `charger_actif()["schema"]` (ligne 129) et renvoyé par `schema_profil()` (ligne 673).
- `presets/<code>/_preset.json` : tout le reste. Chargé dans `charger_actif()["preset"]` (ligne 136). Compatibilité ascendante : si `_preset.json` est absent, le module retombe sur un ancien `_domaine.json` (lignes 131-135, 258-259, 783-784, 808-809).
- `presets/_actif.json` : descripteur pointant sur le preset chargé via le champ `preset` (lignes 65, 119-120). Champ `domaine` toléré pour compat (lignes 98-100).

### Clés réelles de `_preset.json`

Lues effectivement par le code (constatées via les accesseurs et un exemple réel, `presets/it/_preset.json`) :

- **`meta`** — lu par `etiquette_courte()` (ligne 166), `_charger_tous_les_presets()` (ligne 267), `info()` (ligne 760), `lister_presets_disponibles()` (ligne 789).
  - clés exploitées par le code : `etiquette_courte` (ligne 167), `nom` (lignes 763, 789), `version` (ligne 764), `qualite` (lignes 765, 790). Autres clés présentes dans le fichier exemple (`code`, `description`, `_notes`) non lues par `preset.py` (à confirmer côté autres modules).
- **`veille`** — lu par `mots_cles_veille()` (ligne 614), `mots_cles_exclusion()` (ligne 620), `cpv_inclusion()` (ligne 626), `presets_pour_domaines()` (ligne 322), `_charger_tous_les_presets()` (ligne 268).
  - `domaines_acceptes` (ligne 322), `domaines_optionnels` (ligne 323) : codes de la taxonomie domaines, utilisés pour le routage.
  - `mots_cles_inclusion` (ligne 615), `mots_cles_exclusion` (ligne 621).
  - `cpv_inclusion` (ligne 627) : peut contenir des wildcards `*` (ex. `"72*"`, docstring ligne 625).
- **`vocabulaire_llm`** — lu par `vocabulaire_llm()` (ligne 187), `vocabulaire_llm_pour_presets()` (lignes 508, 511-520), `_charger_tous_les_presets()` (ligne 269). Clés typiques documentées dans la docstring (lignes 178-185) : `secteur_libelle`, `type_pieces_dce_typiques`, `type_repondant`, `unite_principale_facturation`, `references_attendues`, `alertes_typiques`, `exemples_synthese`.
- **`prompt_extraction`** — lu par `prompt_extraction()` (ligne 202) et par toutes les fonctions d'agrégation. Sous-clés effectivement extraites :
  - `bloc_schema_specifique` (lignes 360-361, 433, 541-542) — portion JSON injectée dans le schéma de sortie LLM.
  - `regles_specifiques` (lignes 375-376, 564-565).
  - `exemples_elements_a_chiffrer` (lignes 387-388, 583-584).
  - `hints_calcul_montant` (lignes 399-400, 603-604).
  - `few_shot_examples` (ligne 486).
- **`prompt_calibration`** — lu par `prompt_calibration()` (ligne 220). Clés typiques documentées (lignes 210-216) : `secteur_libelle_court`, `section_qualification_intervenants`, `section_duree_effective`, `section_coefficient_complexite`, `section_re_pricing`, `section_top_down`.
- **`calibration_llm`** — lu par `baremes_horaires()` (ligne 632), `coefficients_complexite()` (ligne 638), `calibration_llm()` (ligne 648).
  - `baremes_horaires_eur` (ligne 633).
  - clé de coefficients à nom variable : `coefficients_complexite_public`, `coefficients_complexite_chantier` ou `coefficients_complexite` (lignes 640-643).
- **`matching`** — lu par `regles_matching()` (ligne 653), `seuils_score()` (ligne 659), `acheteur_vers_zone()` (ligne 699).
  - `alertes_critiques` (ligne 654).
  - `seuils_score` (ligne 660) avec défauts `tres_pertinent: 75`, `pertinent: 50`, `a_verifier: 20` (lignes 661-664).
  - `acheteur_vers_zone` (ligne 700) contenant `regles` (liste de `{indice, code}`, lignes 703-706) et `fallback_acheteur_central` (`{indices, code}`, lignes 708-712).
- **`taxonomie`** — lu par `categories_metier()` (ligne 669) via la sous-clé `categories_metier` (ligne 670).

## Cache (`_CACHE`, `_CACHE_UNION`) et invalidation (`recharger()`)

Deux caches en mémoire (au niveau module) :

- **`_CACHE`** (ligne 68) : dict du preset actif. Rempli par `charger_actif()` au premier appel (lignes 116-117, 138-144) ; tous les appels suivants renvoient le même dict tant qu'il est non vide.
- **`_CACHE_UNION`** (ligne 237) : cache des agrégations multi-presets. Stocke `tous` (liste de tous les presets, ligne 273), `schema` (ligne 550), `regles` (ligne 569), `elements` (ligne 589), `hints` (ligne 608) et `hashes` (sous-dict, ligne 443).

**Invalidation** : `recharger()` (ligne 147) vide les deux caches (`_CACHE.clear()` ligne 149, `_CACHE_UNION.clear()` ligne 150). `basculer_preset()` appelle `recharger()` après écriture (ligne 818).

Conséquence importante : les fonctions `*_pour_presets`, `schema_union`, etc. lisent les `_preset.json` **une seule fois** puis servent le cache. Après édition d'un `_preset.json`, il faut appeler `recharger()` pour voir le changement.

## API publique

Signatures, retours et lignes (les fonctions préfixées `_` sont internes mais incluses ici car citées dans la consigne).

### Routage et filtrage

- **`presets_pour_domaines(domaines_metier_codes: list) -> list`** (ligne 293). Pour une liste de codes de domaines IA (taxonomie), renvoie les codes presets pertinents, triés par pertinence (`domaines_acceptes` d'abord, puis `domaines_optionnels`), dédupliqués. Renvoie `[]` si l'argument est vide/None ou si aucun élément n'est une str non vide (lignes 312-317) ou si aucun preset ne matche.
- **`_filtrer_presets(codes_presets: Optional[list]) -> list`** (ligne 338, interne). Renvoie les dicts presets correspondant aux codes, en préservant l'ordre passé (lignes 347-349). **Si `codes_presets` est None/vide → renvoie TOUS les presets** (`_charger_tous_les_presets()`, lignes 343-345) : c'est le ressort du fallback union.

### Agrégation pour prompt LLM (mode ciblé)

Toutes prennent `codes_presets: Optional[list]` et s'appuient sur `_filtrer_presets`.

- **`schema_pour_presets(...) -> str`** (ligne 352). Concatène les `bloc_schema_specifique` (trailing commas retirés) avec `",\n"`. None/vide → équivaut à `schema_union()` (via `_filtrer_presets`).
- **`regles_specifiques_pour_presets(...) -> str`** (ligne 370). Concatène les `regles_specifiques` préfixés `**Règles <code>** :` avec `"\n\n"`.
- **`exemples_elements_a_chiffrer_pour_presets(...) -> str`** (ligne 382). Joint les `exemples_elements_a_chiffrer` avec `",\n        "`.
- **`hints_calcul_montant_pour_presets(...) -> str`** (ligne 394). Joint les `hints_calcul_montant` avec `" "`.
- **`few_shot_examples_pour_presets(...) -> str`** (ligne 476). Joint les `few_shot_examples` avec `"\n\n"`. **None/[] → `""`** (lignes 481-482), pas de fallback union.
- **`blocs_sectoriels_pour_presets(...) -> list`** (ligne 406). Renvoie les noms de blocs top-level (clés JSON) déclarés dans `bloc_schema_specifique`, extraits par regex `^  "([a-z_][a-z_0-9]*)"\s*:\s*[\{\[]` (ligne 431), dédupliqués et triés. **None/[] → `[]`** (lignes 426-427) : AUCUN bloc sectoriel autorisé (anti-pollution). Utilisé comme filtre anti-hallucination dans llm_extract.
- **`vocabulaire_llm_pour_presets(...) -> dict`** (ligne 492). 1 preset → son `vocabulaire_llm` ; plusieurs presets → vocabulaire neutre multi-secteurs (`secteur_libelle` = "marchés publics français (multi-secteurs)", lignes 511-520) ; None/vide ou aucun preset trouvé → fallback `vocabulaire_llm()` du preset actif (lignes 502-506).

### Versioning des prompts (hash)

- **`hash_preset(code: str) -> Optional[str]`** (ligne 439). SHA-256 (16 premiers hex) de `presets/<code>/_preset.json`. `None` si le fichier est absent (lignes 447-450). Mis en cache dans `_CACHE_UNION["hashes"]`, vidé par `recharger()`.
- **`hashes_presets_installes() -> dict`** (ligne 454). `{code: "sha256:<16hex>"}` pour tous les presets ayant un `_preset.json` (lignes 457-462).
- **`prompts_versions_pour_presets(codes_presets: Optional[list]) -> dict`** (ligne 465). `{"<code>/_preset.json": "sha256:<16hex>"}` pour les codes ciblés. **`{}` si `codes_presets` vide** (boucle sur `codes_presets or []`, ligne 469).

### Agrégation union (legacy, tous presets)

- **`schema_union() -> str`** (ligne 523) — cache `_CACHE_UNION["schema"]`.
- **`regles_specifiques_union() -> str`** (ligne 554) — cache `["regles"]`.
- **`exemples_elements_a_chiffrer_union() -> str`** (ligne 573) — cache `["elements"]`.
- **`hints_calcul_montant_union() -> str`** (ligne 593) — cache `["hints"]`.

### Accesseurs du preset actif

- **`charger_actif() -> dict`** (ligne 108). Charge (avec cache `_CACHE`) le preset actif. Renvoie `{code, schema, preset, descripteur}` (lignes 138-143). Lève `FileNotFoundError` si le dossier (lignes 123-127) ou les fichiers (`_lire_json`, lignes 77-78) sont absents.
  - Remarque : la consigne mentionne `lire_profil` — **aucune fonction `lire_profil` n'existe** dans `preset.py` ; l'entrée d'accès au preset actif est `charger_actif()` (à confirmer si un alias existe ailleurs).
- **`recharger() -> None`** (ligne 147). Voir section Cache.
- **`code_actif() -> str`** (ligne 153). Code du preset actif (ex. `"formation_ft"`).
- **`etiquette_courte() -> str`** (ligne 158). `meta.etiquette_courte`, fallback sur le code (ligne 167).
- **`vocabulaire_llm() -> dict`** (ligne 174). Bloc `vocabulaire_llm` du preset actif.
- **`prompt_extraction() -> dict`** (ligne 190).
- **`prompt_calibration() -> dict`** (ligne 205).
- **`mots_cles_veille() -> list`** (ligne 612) → `veille.mots_cles_inclusion`.
- **`mots_cles_exclusion() -> list`** (ligne 618) → `veille.mots_cles_exclusion`.
- **`cpv_inclusion() -> list`** (ligne 624).
- **`baremes_horaires() -> dict`** (ligne 630) → `calibration_llm.baremes_horaires_eur`.
- **`coefficients_complexite() -> dict`** (ligne 636) — clé à nom variable (lignes 640-643).
- **`calibration_llm() -> dict`** (ligne 646).
- **`regles_matching() -> list`** (ligne 651) → `matching.alertes_critiques`.
- **`seuils_score() -> dict`** (ligne 657) → `matching.seuils_score` (défauts si absent).
- **`categories_metier() -> list`** (ligne 667) → `taxonomie.categories_metier`.
- **`schema_profil() -> dict`** (ligne 673) → `charger_actif()["schema"]`.
- **`acheteur_vers_zone(acheteur_nom: str) -> Optional[str]`** (ligne 689). Détecte le code de zone géographique depuis le nom d'acheteur, selon `matching.acheteur_vers_zone` (règles par sous-chaîne `indice` normalisée, puis fallback). Renvoie `None` si rien ne matche.

### Validation et introspection

- **`valider_profil(profil: dict) -> list`** (ligne 720). Valide `profil` contre le JSON-Schema du preset actif. Renvoie une liste de messages d'erreur (vide si OK). Utilise `jsonschema.Draft7Validator` si la lib est installée (lignes 731-735) ; sinon validation minimale custom : champs `required` racine + `properties.identite.required` (lignes 737-746).
- **`info() -> dict`** (ligne 755). Résumé : `code`, `nom`, `version`, `qualite`, `nb_mots_cles_inclusion`, `nb_cpv`, `nb_alertes_critiques`, `nb_categories` (lignes 761-770).
- **`lister_presets_disponibles() -> list`** (ligne 773). Liste `[{code, nom, qualite}]` des presets installés (tolère `_domaine.json`). En cas d'erreur de lecture d'un preset : `qualite: "erreur"` (ligne 796).
- **`basculer_preset(code: str) -> None`** (ligne 800). Écrit `presets/_actif.json` (champ `preset`), supprime l'ancien champ `domaine`, puis `recharger()`. Lève `ValueError` si le preset est inconnu (lignes 810-811).

### Fonctions internes

- **`_lire_json(chemin: Path) -> dict`** (ligne 75) — lève `FileNotFoundError` si absent.
- **`_lire_actif_descripteur() -> dict`** (ligne 83) — crée `_actif.json` par défaut (`{"preset": "formation_ft"}`) si absent (lignes 91-96).
- **`_charger_tous_les_presets() -> list`** (ligne 240) — liste `[{code, meta, prompt_extraction, veille, vocabulaire_llm}]` triée par code, mise en cache `_CACHE_UNION["tous"]`. Les presets illisibles sont silencieusement ignorés (`except Exception: continue`, lignes 271-272).
- **`_normaliser(texte: str) -> str`** (ligne 682) — minuscules + suppression des accents (NFKD).

### Bloc `__main__`

`python preset.py` (lignes 821-837) affiche les presets disponibles, le preset actif (`info()`), un aperçu du vocabulaire LLM et un extrait des mots-clés de veille.

## Dépendances + variables d'environnement

Imports standard uniquement (lignes 55-60) : `hashlib`, `json`, `os`, `unicodedata`, `pathlib.Path`, `typing.Optional`.

Dépendance optionnelle : **`jsonschema`** — importé localement dans `valider_profil()` (ligne 731) ; son absence (`ImportError`) bascule sur une validation minimale (lignes 736-746).

**Aucune variable d'environnement** n'est lue dans `preset.py` (le module `os` est importé mais aucun `os.getenv`/`os.environ` n'apparaît dans le source — à confirmer). Les chemins sont dérivés de l'emplacement du fichier : `RACINE = Path(__file__).resolve().parent` (ligne 63), `PRESETS_DIR = RACINE / "presets"` (ligne 64), `FICHIER_ACTIF = PRESETS_DIR / "_actif.json"` (ligne 65).

## Exemples d'usage (appelants réels)

### llm_extract.py — construction des prompts ciblés

```python
# llm_extract.py:215  (prompt système adapté au(x) preset(s) du marché)
voc = _preset.vocabulaire_llm_pour_presets(codes_presets)

# llm_extract.py:279-283  (blocs injectés dans le prompt utilisateur)
union_schema   = _preset.schema_pour_presets(codes_presets)
union_exemples = _preset.exemples_elements_a_chiffrer_pour_presets(codes_presets)
union_hints    = _preset.hints_calcul_montant_pour_presets(codes_presets)
union_regles   = _preset.regles_specifiques_pour_presets(codes_presets)
union_few_shot = _preset.few_shot_examples_pour_presets(codes_presets)

# llm_extract.py:624  (filtre anti-hallucination sur les blocs de sortie)
blocs_autorises = set(_preset.blocs_sectoriels_pour_presets(codes_presets))

# llm_extract.py:672  (routage classif IA → presets)
return _preset.presets_pour_domaines(codes_domaines)
```

### fiche_marche.py — pondération des presets par domaine

```python
# fiche_marche.py:61
presets = _preset.presets_pour_domaines([code]) or []
```

### matching.py — presets pertinents pour un marché

```python
# matching.py:230
return _preset.presets_pour_domaines(codes) if codes else []
```

### tendia_extraire.py — versioning des prompts dans la sortie

```python
# tendia_extraire.py:346
"prompts_versions": preset.prompts_versions_pour_presets(codes_presets),
```

### tendia_ui.py — méta du preset actif

```python
# tendia_ui.py:70
meta = preset.charger_actif()["preset"].get("meta", {})
```

### Scripts d'audit / tests — invalidation du cache

```python
# identifier_briefs_pollues.py:36, relancer_extraction_chantier1.py:22, tests_*.py
preset.recharger()
```

## Pièges connus

- **`_filtrer_presets([])` renvoie TOUS les presets** (lignes 343-345). Donc les fonctions `*_pour_presets` qui passent directement par `_filtrer_presets` retombent sur l'union complète quand on leur donne `None`/`[]` : c'est le cas de `schema_pour_presets`, `regles_specifiques_pour_presets`, `exemples_elements_a_chiffrer_pour_presets`, `hints_calcul_montant_pour_presets`. **Exceptions** qui court-circuitent avant `_filtrer_presets` :
  - `blocs_sectoriels_pour_presets([]) → []` (lignes 426-427).
  - `few_shot_examples_pour_presets([]) → ""` (lignes 481-482).
  - `prompts_versions_pour_presets([]) → {}` (boucle vide, ligne 469).
  - `vocabulaire_llm_pour_presets([]) → vocabulaire_llm()` du preset actif (lignes 502-503).

  Ces comportements asymétriques sont voulus (anti-pollution / hors-périmètre) et couverts par `tests_llm_extract_routage.py` (lignes 98-102) et `tests_briefs_versioning.py` (ligne 43). Côté appelant, llm_extract gère explicitement le cas `codes_presets` vide en n'injectant aucun bloc et en retombant sur des fallbacks neutres (llm_extract.py:267-293), donc il ne s'appuie PAS sur le fallback union de `_filtrer_presets` pour ces deux fonctions.

- **Le mapping domaine → presets est dérivé des fichiers, pas un dict statique.** `presets_pour_domaines` lit `veille.domaines_acceptes`/`domaines_optionnels` de chaque `_preset.json` (lignes 320-327). Ajouter/retirer un domaine se fait dans le JSON, pas dans le code.

- **`recharger()` est obligatoire après édition d'un `_preset.json`** (ou `_schema.json` / `_actif.json`). Les deux caches (`_CACHE`, `_CACHE_UNION`, incl. hashes) servent des valeurs figées au premier accès (sections Cache). En process long (UI, batch), oublier `recharger()` = données périmées.

- **Aucune fonction `lire_profil`.** L'accès au preset actif passe par `charger_actif()` (ligne 108) ; le sous-dict du profil organisme renseigné par l'utilisateur n'est pas chargé par ce module (à confirmer : il vit ailleurs, ex. `organisme.py`).

- **Coefficients de complexité à clé variable** : `coefficients_complexite()` essaie successivement `coefficients_complexite_public`, `coefficients_complexite_chantier`, `coefficients_complexite` et renvoie `{}` si aucune n'existe (lignes 640-643). Ne pas supposer un nom de clé fixe.

- **Compatibilité ascendante diffuse** : `_domaine.json` (ancien nom de `_preset.json`) et le champ `domaine` (ancien `preset`) sont tolérés à plusieurs endroits (lignes 99-100, 131-135, 258-259, 783-784, 808-809). Les nouveaux presets doivent utiliser `_preset.json` et le champ `preset`.

- **Erreurs de lecture silencieuses dans l'agrégation** : `_charger_tous_les_presets()` ignore tout preset dont le JSON lève une exception (`except Exception: continue`, lignes 271-272). Un `_preset.json` malformé disparaît de l'union/du routage sans message — n'apparaît qu'en `qualite: "erreur"` via `lister_presets_disponibles()` (ligne 796).
