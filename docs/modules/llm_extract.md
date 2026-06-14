# Module llm_extract

Fichier source : `llm_extract.py`

Documentation établie par lecture intégrale du source. Les numéros de ligne
renvoient à l'état du fichier au moment de la rédaction.

## Rôle (extraction LLM d'un brief structuré depuis le texte d'un DCE)

Le module prend en entrée le texte concaténé des pièces d'un DCE (RC + CCTP +
autres pièces) et appelle l'API Claude (SDK `anthropic`) pour en extraire un
brief JSON structuré : synthèse, classification métier, barème de notation,
montant, révision des prix, références exigées, lots, calendrier, alertes et
points différenciants.

Le docstring du module (lignes 1-15) décrit l'API publique :
`extraire_via_llm(texte, contexte) -> dict`.

L'API est exposée par la fonction `extraire_via_llm` (ligne 677). Le reste du
module est constitué de helpers privés (préfixe `_`) et de constantes.

## Constantes

Définies lignes 41-43 :

- `MODELE = "claude-sonnet-4-6"` (ligne 41) — identifiant de modèle passé à
  `client.messages.create(model=MODELE, ...)` (ligne 745). Commentaire source :
  « Sonnet 4.6 — canonical ID ».
- `MAX_TOKENS_REPONSE = 16000` (ligne 42) — passé en `max_tokens` à l'appel API
  (ligne 746). Commentaire source : « Sonnet 4.6 supporte jusqu'à 16384 ; 8000
  tronquait les briefs riches ».
- `MAX_CHARS_INPUT = 400_000` (ligne 43) — seuil de tronquage du texte d'entrée
  appliqué dans `extraire_via_llm` (lignes 713-716).

`_CHAMPS_UNIVERSELS_BRIEF` (lignes 579-598) — `set` des clés top-level toujours
préservées par le filtre anti-hallucination, quel que soit le secteur. Contient
les blocs métier universels (`synthese_marche`, `domaines_metier`,
`raison_classification`, `bareme_notation`, `montant_marche`, `revision_prix`,
`alertes_prix`, `references_exigees`, `lots`, `calendrier`, `alertes_candidat`,
`points_differenciants_attendus`), le bloc neutre `caracteristiques_metier`
(injecté pour les marchés hors-périmètre), ainsi que les méta techniques
`_appel_llm` et `_meta`.

Autres constantes / globales notables :

- `PROMPT_SYSTEME` (ligne 241) — prompt système évalué une fois à l'import via
  `_construire_prompt_systeme()` sans argument (preset actif). Conservé pour
  rétro-compatibilité ; pour un prompt sectoriellement ciblé, le code appelle
  `_construire_prompt_systeme(codes_presets=[...])` à chaque appel LLM (cf.
  ligne 732).
- `PROMPT_UTILISATEUR_TEMPLATE` (lignes 322-552) — gabarit du prompt
  utilisateur. Voir section dédiée plus bas.
- `_TAXONOMIE_CACHE` (ligne 119) — cache du JSON de taxonomie (chargement lazy).

## Chargement clé API + injection truststore SSL au chargement du module

### Injection truststore (lignes 29-33)

Au chargement du module, le code tente `import truststore as _truststore` puis
`_truststore.inject_into_ssl()`, le tout dans un `try/except Exception: pass`
(idempotent et silencieux). Le commentaire (lignes 25-28) explique : sur ce
poste, `certifi` ne peut pas bâtir la chaîne TLS (interception TLS) →
l'appel HTTPS du SDK `anthropic` échouerait en « Connection error ».
`truststore` force l'usage du magasin de certificats système. L'injection est
faite ici parce que le SDK `anthropic` n'importe PAS `http_client.py` (où
truststore est aussi injecté).

Juste après (lignes 35-38), import du SDK : `from anthropic import Anthropic`,
avec fallback `Anthropic = None` si le SDK n'est pas installé.

### `_charger_cle_depuis_env_file()` (lignes 50-83)

Cherche un fichier `.env` à la racine du projet (`Path(__file__).parent`), avec
fallback `.env.txt` (cas Notepad sous Windows, ligne 63). Lit le fichier en
`encoding="utf-8-sig"` pour gérer le BOM UTF-8 (ligne 69). Parse les lignes au
format `CLE=valeur` : ignore les lignes vides et celles commençant par `#`,
strippe les guillemets simples/doubles autour de la valeur (ligne 78). Retourne
la valeur de `ANTHROPIC_API_KEY` si trouvée et non vide, sinon `None`. Toute
exception de lecture est avalée (`continue` / `return None`).

### `_obtenir_cle_api()` (lignes 86-100)

Priorité : (1) variable d'environnement `ANTHROPIC_API_KEY` (ligne 92), sinon
(2) fichier `.env` via `_charger_cle_depuis_env_file()`. Si la clé vient du
fichier, elle est injectée dans `os.environ["ANTHROPIC_API_KEY"]` (ligne 98)
pour que le SDK `Anthropic()` (instancié sans argument, ligne 734) la retrouve.
Retourne `None` si aucune clé.

### `_check_anthropic()` (lignes 559-573)

Lève `RuntimeError` si le SDK n'est pas installé (`Anthropic is None`,
lignes 560-564) ou si `_obtenir_cle_api()` ne renvoie pas de clé
(lignes 565-573). Les messages d'erreur expliquent comment installer le SDK
(`pip install anthropic`) et comment fournir la clé.

## Routage par preset

Le module sélectionne dynamiquement quels blocs sectoriels injecter dans les
prompts, en fonction des presets pertinents pour le marché. Il s'appuie sur le
module `preset` (importé ligne 112 comme `_preset`).

### `_resoudre_presets_pour_marche(marche_id)` (lignes 637-674)

Pour un `marche_id` donné, lit la classification IA du marché et retourne la
liste des codes presets pertinents :

1. Si `marche_id` est falsy → `[]` (ligne 653-654).
2. Importe `stockage` et charge la collection `classifications_ia`
   (ligne 656-657).
3. Récupère `classif["domaines_metier"]`, extrait les codes (dict avec clé
   `code`, ou chaîne directe — lignes 663-669).
4. Retourne `_preset.presets_pour_domaines(codes_domaines)` (ligne 672).

Retourne `[]` (silencieusement, via `except Exception` ligne 673-674) en cas
d'erreur, d'absence de classification, ou de domaines ne mappant vers aucun
preset installé. Pas de `raise` : l'extraction n'est pas bloquée par un détail
d'environnement.

### `_construire_prompt_systeme(codes_presets=None)` (lignes 204-235)

Construit le prompt système. Récupère le vocabulaire via
`_preset.vocabulaire_llm_pour_presets(codes_presets)` (ligne 215) et l'injecte
dans un texte fixe (secteur, type de pièces DCE, type de répondant). Concatène
en fin la section taxonomie produite par `_section_taxonomie_prompt()`
(ligne 234).

Comportements documentés dans le docstring (lignes 205-214) :
- un seul preset → prompt orienté secteur ;
- plusieurs presets → prompt neutre multi-secteurs ;
- `None` ou `[]` → fallback vocabulaire du preset actif (legacy).

#### Helpers taxonomie

- `_charger_taxonomie()` (lignes 122-135) — charge
  `presets/_taxonomie_domaines.json` avec cache (`_TAXONOMIE_CACHE`). Retourne
  `{"domaines": {}}` si fichier absent ou JSON invalide.
- `_section_taxonomie_prompt()` (lignes 138-201) — construit la section
  « RÈGLES DE CLASSIFICATION DOMAINE MÉTIER » injectée dans le prompt système :
  format de classification, liste compacte des codes (code + libellé +
  description tronquée ~120 chars, ligne 170), et une liste de
  « FRONTIÈRES PIÉGEUSES » de désambiguïsation. Retourne `""` si aucun domaine.

### `_construire_prompt_utilisateur(contexte_str, texte, codes_presets=None)` (lignes 244-319)

Compose le prompt utilisateur final via
`PROMPT_UTILISATEUR_TEMPLATE.format(...)` (lignes 311-319).

Comportement hors-périmètre (clé du routage, lignes 267-275) : **si
`codes_presets` vaut `None` ou est vide (`len == 0`), AUCUN bloc sectoriel
n'est injecté** — toutes les variables `union_*` sont mises à `""`. Les
fallbacks neutres ci-dessous produisent alors un schéma générique. Le
commentaire (lignes 267-270) précise explicitement que l'union complète de
tous les presets n'est PLUS injectée (elle polluait ~50% des marchés).

> Note : le docstring de la fonction (lignes 254-256) mentionne encore un
> « fallback sur l'union complète » pour `None`/`[]`, mais le code effectif
> (lignes 271-276) met les blocs à vide dans ce cas. Le commentaire inline
> (lignes 267-270) fait foi sur le comportement réel : pas d'union. (le
> docstring semble obsolète sur ce point — à confirmer)

Si `codes_presets` est non vide (mode ciblé, lignes 277-283), les blocs sont
récupérés pour ces presets uniquement via :
- `_preset.schema_pour_presets`
- `_preset.exemples_elements_a_chiffrer_pour_presets`
- `_preset.hints_calcul_montant_pour_presets`
- `_preset.regles_specifiques_pour_presets`
- `_preset.few_shot_examples_pour_presets`

Fallbacks neutres (lignes 285-304) : si `union_schema` / `union_exemples` /
`union_hints` sont vides après extraction, des valeurs par défaut génériques
sont utilisées — notamment un bloc `caracteristiques_metier` minimal
(lignes 288-293). Les blocs `regles_specifiques` et `few_shot_examples` ne sont
formatés (avec lignes blanches) que s'ils sont non vides (lignes 307-309).

### `PROMPT_UTILISATEUR_TEMPLATE` et ses placeholders (lignes 322-552)

Gabarit `str.format` décrivant le schéma JSON de sortie attendu et les règles
d'extraction. Placeholders injectés par `_construire_prompt_utilisateur`
(lignes 311-318) :

- `{contexte}` — `contexte_str` (JSON du contexte marché).
- `{texte}` — texte du DCE (déjà tronqué).
- `{bloc_schema_specifique}` — schéma sectoriel (`union_schema`), inséré dans le
  corps du schéma JSON (ligne 345).
- `{exemples_elements_a_chiffrer}` — `union_exemples`, dans `bareme_notation.prix`
  (ligne 385).
- `{hints_calcul_montant}` — `union_hints`, dans les règles « MONTANT DU MARCHÉ »
  (ligne 512).
- `{few_shot_examples}` — `fs_formate` (ligne 550).
- `{regles_specifiques}` — `rs_formate` (ligne 551).

Le template contient également une règle « RESPECT STRICT DU SCHÉMA »
(ligne 459) demandant au LLM de ne produire aucun bloc hors-schéma — règle
renforcée a posteriori par le filtre anti-hallucination côté code.

## Filtre anti-hallucination

### `_filtrer_hallucinations(data, codes_presets, verbose=False)` (lignes 601-634)

Supprime de la sortie LLM les clés **top-level** qui ne sont pas autorisées.
Calcule l'ensemble autorisé comme l'union de `_CHAMPS_UNIVERSELS_BRIEF` et des
blocs sectoriels des presets ciblés
(`_preset.blocs_sectoriels_pour_presets(codes_presets)`, lignes 624-625). Toute
clé de `data` absente de cet ensemble est supprimée via `data.pop(k, None)`
(lignes 626-633). Mutation in-place + retour du dict pour chaînage.

Le commentaire (lignes 608-612) cite le cas réel ayant motivé le filtre (marché
56164 : le LLM avait halluciné `caracteristiques_techniques_chantier`,
`volumes`, `publics_cibles` alors que le schéma envoyé ne contenait que
`caracteristiques_si` / `qualifications_si`).

Le filtre s'exécute **AVANT le stockage** des données : dans `extraire_via_llm`,
il est appelé (lignes 784-786) immédiatement après le parsing JSON réussi et
avant l'ajout du bloc `_appel_llm` (lignes 790-797) et le `return`. C'est le
caller (`tendia_extraire`) qui persiste ensuite le dict retourné.

> Portée : le filtre n'agit qu'au niveau top-level des clés du dict ; il ne
> nettoie pas les sous-champs imbriqués.

## Fonction principale `extraire_via_llm(texte, contexte, verbose, max_retries)`

Définie lignes 677-848.

### Signature

```python
def extraire_via_llm(texte: str, contexte: dict,
                     verbose: bool = True,
                     max_retries: int = 2) -> Optional[dict]:
```

- `texte` : texte combiné RC + CCTP + autres pièces.
- `contexte` : dict de méta du marché (`id`, `titre`, `acheteur`, `source`, …).
- `verbose` : par défaut `True` (affiche presets ciblés, tokens, coût, durée).
- `max_retries` : par défaut `2` (relance sur erreur API ou JSON invalide).

### Déroulé

1. **Garde-fou budget** (lignes 696-710) : importe `budget`, récupère
   `marche_id = contexte.get("id")` (ligne 698), appelle
   `_budget.peut_appeler_llm("extraction", marche_id=...)`. Si non autorisé,
   enregistre un appel `statut="bloque_budget"` puis **lève
   `budget.BudgetDepasseError`** (ligne 710).
2. `_check_anthropic()` (ligne 712) — valide SDK + clé.
3. **Tronquage** (lignes 713-716) : si `len(texte) > MAX_CHARS_INPUT`, tronque à
   `MAX_CHARS_INPUT`.
4. **Routage** : `codes_presets = _resoudre_presets_pour_marche(marche_id)`
   (ligne 724).
5. Sérialise le contexte (`json.dumps`, ligne 730), construit prompt utilisateur
   (ligne 731) et prompt système (ligne 732) avec `codes_presets`.
6. Instancie `client = Anthropic()` (ligne 734).
7. **Boucle de tentatives** (lignes 738-847) : appelle
   `client.messages.create(model=MODELE, max_tokens=MAX_TOKENS_REPONSE,
   system=prompt_systeme, messages=[{"role": "user", "content": prompt_user}])`
   (lignes 744-749). Lit le texte de réponse (`message.content[0].text`,
   ligne 751), les tokens (`message.usage.input_tokens` / `output_tokens`,
   lignes 753-754). Calcule un coût USD indicatif
   `(in*3 + out*15) / 1_000_000` (ligne 755) et un coût EUR via
   `_budget.estimer_cout_eur(...)` (ligne 756).
8. **Parsing JSON** (lignes 763-776) : `json.loads` direct ; en cas d'échec,
   recherche d'un bloc `{...}` par regex `re.search(r"\{.*\}", ..., re.DOTALL)`
   (ligne 769) et re-parse.
9. **Si parsing OK** : applique `_filtrer_hallucinations` (lignes 784-786),
   ajoute le bloc `_appel_llm` (lignes 790-797), enregistre l'appel
   `statut="ok"` via `_budget.enregistrer_appel` (lignes 799-808), puis retourne
   le dict (ligne 809).
10. **JSON invalide** : retente tant que `tentative < max_retries`, sinon log
    `statut="erreur"` (`erreur="reponse_non_json"`) et retourne `None`
    (lignes 811-829).
11. **Exception API** : capturée (lignes 830-847), retente après
    `time.sleep(2)` (ligne 835) tant que possible, sinon log `statut="erreur"`
    avec coût 0 et retourne `None`.

### Valeur de retour

Un `dict` (la réponse JSON parsée et filtrée) enrichi de la clé `_appel_llm`
(lignes 790-797) :

```python
"_appel_llm": {
    "modele": MODELE,
    "tokens_input": in_tokens,
    "tokens_output": out_tokens,
    "cout_eur": cout_eur,
    "duree_sec": round(duree, 1),
    "codes_presets": codes_presets,
}
```

Retourne `None` en cas d'échec définitif (JSON non parsable après retries, ou
exception API persistante).

### Où `marche_id` est pris

`marche_id = contexte.get("id") if contexte else None` (ligne 698). Il sert au
garde-fou budget, au routage presets (`_resoudre_presets_pour_marche`) et au
logging des appels budget.

## Dépendances + variables d'env

Imports standard (lignes 17-23) : `json`, `os`, `re`, `sys`, `time`,
`pathlib.Path`, `typing.Optional`.

Imports tiers :
- `truststore` (lignes 30-31) — injection SSL au chargement (try/except).
- `anthropic.Anthropic` (lignes 35-38) — SDK Claude (try/except, fallback
  `None`).

Imports projet :
- `preset` (alias `_preset`, ligne 112) — vocabulaire, schémas, blocs
  sectoriels, mapping domaines→presets.
- `budget` (import local dans `extraire_via_llm`, ligne 697) — garde-fou,
  estimation de coût, journalisation des appels.
- `stockage` (import local dans `_resoudre_presets_pour_marche`, ligne 656) —
  lecture de la collection `classifications_ia`.

Variable d'environnement : **`ANTHROPIC_API_KEY`** — lue par `_obtenir_cle_api`
(ligne 92), avec fallback sur fichier `.env` / `.env.txt` à la racine du projet.

Fichiers de données lus : `presets/_taxonomie_domaines.json` (ligne 127),
`.env` / `.env.txt` (lignes 63-69).

## Exemples d'usage

### Appelant réel : `tendia_extraire.traiter_marche`

Dans `tendia_extraire.py` (lignes 317-320) :

```python
extraction = llm_extract.extraire_via_llm(
    texte_combine, contexte, verbose=verbose
)
```

Le caller construit `contexte` via `_construire_contexte(marche)` (ligne 307) et
`texte_combine` via `_combiner_textes(pdfs_valides)` (ligne 308). Après l'appel,
il extrait les méta avec `extraction.pop("_appel_llm", None)` (ligne 329),
récupère `codes_presets` (ligne 330), puis construit son propre bloc `_meta`
(lignes 334-355) et persiste le dict en JSON dans `REPERTOIRE_EXTRACTIONS`
(lignes 357-361).

### Bloc de test `__main__` (lignes 851-882)

Le module exécuté directement envoie un texte de RC fictif (« Activ Seniors »,
lignes 853-870) avec un contexte minimal (`id`, `titre`, `acheteur`,
lignes 871-875), appelle `extraire_via_llm(..., verbose=True)` et imprime le
JSON résultant.

## Pièges connus

- **`truststore` requis sur ce poste** : sans l'injection SSL (lignes 29-33),
  l'appel HTTPS du SDK `anthropic` échoue en « Connection error » à cause de
  l'interception TLS (le magasin `certifi` ne peut pas bâtir la chaîne). Le SDK
  `anthropic` n'important pas `http_client.py`, l'injection doit être faite
  dans ce module (cf. commentaire lignes 25-28).
- **Tronquage silencieux à `MAX_CHARS_INPUT = 400_000`** : au-delà, le texte
  est coupé (lignes 713-716). Sur un gros DCE, des pièces peuvent donc être
  partiellement ignorées. Le tronquage n'est signalé que si `verbose=True`.
- **Filtre anti-hallucination top-level uniquement** : `_filtrer_hallucinations`
  ne supprime que les clés de premier niveau hors-schéma (lignes 624-633). Des
  sous-champs hallucinés à l'intérieur de blocs autorisés ne sont pas nettoyés.
- **Coût réel** : sur un gros DCE, le coût observé est de l'ordre de ~0,4 €
  par marché. Le coût USD calculé ligne 755 utilise des tarifs codés en dur
  (3 $/Mtok input, 15 $/Mtok output) ; le coût EUR de référence passe par
  `_budget.estimer_cout_eur` (ligne 756). (ordre de grandeur ~0,4€ — à confirmer
  selon la taille effective du DCE)
- **Divergence docstring / code sur le fallback presets** : le docstring de
  `_construire_prompt_utilisateur` (lignes 254-256) évoque une union complète
  pour `codes_presets` vide, alors que le code (lignes 271-276) n'injecte aucun
  bloc sectoriel dans ce cas et s'appuie sur les fallbacks neutres. Le commentaire
  inline (lignes 267-270) confirme le comportement réel. (docstring vraisemblablement
  obsolète — à confirmer)
