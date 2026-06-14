# Module analyse

Documentation factuelle de `analyse.py`, rédigée par lecture intégrale du source.
Toute citation de ligne renvoie au fichier `analyse.py` dans son état lu.

## Rôle

`analyse.py` est le **moteur de matching preset × marché** du pipeline Tendia.
Le docstring de tête (lignes 1-53) et le code confirment deux responsabilités :

1. **Étape 5a — matching déterministe (gratuit, sans LLM)** : pour chaque marché
   stocké en base, déterminer s'il est pertinent pour au moins un preset installé,
   et persister le résultat dans la collection `scores_matching`. Cf.
   `analyser_tous_les_marches()` (ligne 436).

2. **Étape 5b — orchestration de l'enrichissement LLM** : pour les marchés jugés
   pertinents, déclencher la génération d'un brief LIGHT via `auto_brief`, en
   respectant un budget. Cf. `enrichir_marches_pertinents()` (ligne 648).

Deux logiques de matching coexistent dans le code :

- **Matching keyword/CPV** (déterministe) : `matcher_preset_marche()` (ligne 122).
  Un marché matche si au moins un mot-clé d'inclusion apparaît (word boundary) dans
  `titre+objet` OU si `cpv_principal` matche un pattern `cpv_inclusion`, ET qu'aucun
  mot-clé d'exclusion n'est présent (lignes 150-165).
- **Matching par classification IA** (Sprint 2) : `matcher_preset_marche_par_ia()`
  (ligne 242). Un marché matche si son domaine principal classifié appartient aux
  `domaines_acceptes` (niveau `principal`) ou `domaines_optionnels` (niveau
  `optionnel`) du preset.

Dans `analyser_tous_les_marches()`, **la classification IA prime** quand elle existe ;
sinon le verdict keyword sert de fallback (lignes 497-505). Le score keyword est
toujours calculé et stocké pour traçabilité (ligne 493, 512-517).

## Constantes

| Constante | Valeur | Ligne | Usage |
|-----------|--------|-------|-------|
| `COLLECTION_SCORES` | `"scores_matching"` | 66 | Collection des scores marché×preset |
| `COLLECTION_CLASSIFICATIONS_IA` | `"classifications_ia"` | 194 | Classifications IA chargées en entrée |
| `COLLECTION_BRIEFS_EXTRAITS` | `"briefs_extraits"` | 195 | Briefs complets (prioritaires sur la classif IA) |
| `COLLECTION_BRIEFS` | `"briefs_extraits"` | 635 | Collection des briefs (même valeur que `COLLECTION_BRIEFS_EXTRAITS`) écrite par l'étape 5b |

Note : `COLLECTION_BRIEFS` (ligne 635) et `COLLECTION_BRIEFS_EXTRAITS` (ligne 195)
pointent toutes deux sur `"briefs_extraits"` ; ce sont deux noms pour la même
collection.

## API publique

Les fonctions préfixées par `_` sont privées (normalisation, chargement interne,
etc.) et ne sont pas listées ici, à l'exception de `_ids_marches_pertinents()` qui
**est appelée par d'autres modules** (voir Exemples d'usage).

### `matcher_preset_marche(preset_def: dict, marche: dict) -> dict` — ligne 122
Évalue un marché contre un preset par mots-clés/CPV/exclusion.
Retourne un dict :
`{ matche: bool, mots_cles_matches: list[str], cpv_pattern_matche: str|None,
exclu_par_mot_negatif: str|None, score_brut: int, raison: str }`
(`score_brut` = nombre de mots-clés trouvés + 1 si CPV matche, ligne 185).

### `matcher_preset_marche_par_ia(preset_def: dict, marche_id: str, classifs_ia: dict, briefs: dict) -> dict` — ligne 242
Évalue un marché selon sa classification IA (domaine principal vs
`domaines_acceptes` / `domaines_optionnels` du preset).
Retourne :
`{ matche: bool, niveau: 'principal'|'optionnel'|'hors'|'non_classifie',
domaine_classifie: str|None, source_classification: 'brief_complet'|'classification_ia'|None,
raison: str }`.
Le brief complet est privilégié sur la classification IA comme source (cf.
`_classification_pour_marche`, lignes 216-239).

### `est_pertinent_strict(preset_def: dict, marche_id: str, marche: dict, classifs_ia: Optional[dict]=None, briefs: Optional[dict]=None, fallback_keyword: bool=True) -> dict` — ligne 314
Décide la pertinence en mode strict (priorité IA). Si pas de classification :
fallback keyword si `fallback_keyword=True`, sinon non pertinent.
Charge `classifs_ia` / `briefs` depuis le stockage s'ils valent `None` (lignes 340-343).
Retourne le dict de `matcher_preset_marche_par_ia` enrichi d'un champ
`mode: 'classification_ia'|'keyword_fallback'`.
(Aucun appelant externe trouvé pour cette fonction — à confirmer.)

### `analyser_marche(marche: dict, presets_charges: Optional[dict]=None) -> dict` — ligne 397
Matche un marché contre tous les presets installés (matching keyword uniquement,
via `matcher_preset_marche`, ligne 415).
Retourne :
`{ marche_id: str, presets_qui_matchent: list[str],
details_par_preset: {code: matcher_result}, au_moins_un_match: bool }`.
Si `presets_charges` est `None`, charge tous les presets depuis le disque
(`_charger_tous_les_presets`, ligne 371).

### `analyser_tous_les_marches(verbose: bool=True, force: bool=False) -> dict` — ligne 436
Pour chaque couple (marché × preset), calcule keyword + IA, décide le verdict
final (IA prime), et persiste dans `scores_matching` (clé de cache
`f"{mid}__{preset_code}"`, ligne 485). Avec `force=False`, réutilise les entrées
déjà en cache (ligne 486).
Retourne des stats :
`{ total_marches, analyses_nouvelles, deja_en_cache, pertinents_global,
pertinents_par_preset }` (initialisé lignes 466-472).

### `marches_pertinents_pour_preset(preset_code: str) -> list` — ligne 563
Liste les marchés pertinents pour un preset depuis le cache `scores_matching`,
enrichis depuis la collection `marches`.
Retourne `list[dict]` :
`{ marche_id, titre (tronqué à 120), acheteur_nom, cpv_principal, type_marche,
score_brut, mots_cles_matches, cpv_pattern_matche, raison, date_publication }`.
Tri par score décroissant puis date (lignes 598-599).

### `statistiques() -> dict` — ligne 603
Vue agrégée des scores.
Retourne :
`{ scores_total, marches_total, par_preset: {code: {total, pertinents}},
marches_pertinents_au_moins_un_preset }`.
(Le docstring mentionne « par type_marche, par CPV » à la ligne 604, mais le code
ne calcule que `par_preset` et les totaux — détail du docstring non implémenté.)

### `enrichir_marches_pertinents(limite: Optional[int]=None, dry_run: bool=False, forcer: bool=False, verbose: bool=True) -> dict` — ligne 648
Pour chaque marché pertinent (matche au moins un preset), génère un brief LIGHT via
`auto_brief.generer_brief_light` (ligne 746) et le stocke dans `briefs_extraits`
(ligne 766). Garde-fous : skip si brief déjà en cache (sauf `forcer`, ligne 716),
skip si `objet` < 30 caractères (ligne 723), arrêt sur `budget.BudgetDepasseError`
(lignes 747-752).
Retourne des stats :
`{ traites, enrichis_nouveaux, deja_en_cache, echecs, bloques_budget,
skip_objet_trop_court, cout_total_eur, dry_run }` (initialisé lignes 688-697).

### `main() -> None` — ligne 794
Point d'entrée CLI (voir section CLI).

## CLI (argparse)

Définie dans `main()` (lignes 794-861). Exécutée si `__name__ == "__main__"`
(lignes 864-865).

| Argument | Type | Effet |
|----------|------|-------|
| `--force` | flag | Recalcule tous les scores, ignore le cache (ligne 799) |
| `--montrer PRESET` | str | Affiche les top 10 marchés pertinents pour ce preset (ligne 801) |
| `--stats` | flag | Affiche uniquement les stats agrégées, sans relancer l'analyse (ligne 803) |
| `--enrichir` | flag | Mode étape 5b : génère un brief LIGHT par marché pertinent via LLM (ligne 805) |
| `--limite N` | int | Limite le nombre de marchés enrichis par passe (ligne 809) |
| `--dry-run` | flag | Avec `--enrichir` : simule sans appel LLM, affiche l'estimation de coût (ligne 811) |
| `--forcer-brief` | flag | Avec `--enrichir` : regénère même si un brief LIGHT existe (ligne 814) |

Ordre de priorité des branches dans `main()` : `--enrichir` (ligne 820) →
`--stats` (829) → `--montrer` (844) → sinon analyse complète (861).

Usage observé :
```
python analyse.py                 # lance l'analyse multi-preset (mode défaut)
python analyse.py --force         # recalcule tous les scores
python analyse.py --stats         # stats agrégées
python analyse.py --montrer it    # top 10 marchés pertinents du preset 'it'
python analyse.py --enrichir --dry-run        # estimation de coût LLM
python analyse.py --enrichir --limite 20      # enrichit 20 marchés max
```

## Dépendances + variables d'env

Imports en tête (lignes 55-63) :
- Bibliothèque standard : `re`, `sys`, `unicodedata`, `datetime`, `pathlib.Path`,
  `typing.Optional`. (`json` et `argparse` sont importés tardivement, lignes 379 et 795.)
- Modules internes : `preset` (importé ligne 62 mais non référencé ailleurs dans le
  fichier — à confirmer), `stockage` (ligne 63).

Imports tardifs (pour éviter les cycles, commentés dans le code) :
- `budget` (ligne 667, alias `_budget`) — utilisé pour `estimer_cout_eur` et
  `BudgetDepasseError`.
- `auto_brief` (ligne 701) — utilisé en mode réel (non dry-run).

API `stockage` utilisée : `charger(collection)`, `sauver(collection, donnees)`,
`ecrire(collection, id, objet)` (confirmé dans `stockage.py`).

Collections lues/écrites : `marches`, `scores_matching`, `classifications_ia`,
`briefs_extraits`.

Presets lus sur disque : répertoire `presets/<code>/_preset.json` (fallback
`_domaine.json`), relatif à l'emplacement de `analyse.py`
(`_charger_tous_les_presets`, lignes 376-394).

**Variables d'environnement** : aucune lue directement dans `analyse.py`. (Les coûts
LLM et le kill-switch passent par les modules `budget` / `auto_brief` — non analysés ici.)

## Exemples d'usage (appelants réels)

Recherche `import analyse` / `analyse.` sur le dépôt (hors `venv`) :

- `enrichir_complet.py:37` `import analyse` ; ligne 50 :
  `pertinents = analyse._ids_marches_pertinents()`.
- `diagnostic_dce_pertinents.py:22` `import analyse` ; ligne 37 :
  `pertinents_ids = analyse._ids_marches_pertinents()`.
- `tendia_ui.py:419` (commentaire) : la collection `scores_matching` est « calculée
  par analyse.py » ; l'UI consomme donc les scores produits ici.
- `bilan_briefs.py:163` et `nettoyer_attributions.py:202` : mentions de
  `python analyse.py` dans des messages console (invocation CLI conseillée).

Observation : les seuls appels Python externes effectifs portent sur la fonction
**privée** `_ids_marches_pertinents()` (ligne 638). Aucun appel externe trouvé pour
les fonctions publiques `matcher_preset_marche`, `analyser_marche`,
`est_pertinent_strict`, `marches_pertinents_pour_preset`, `statistiques` — elles sont
utilisées via la CLI ou en interne. (Note : `tester_sprint2bis.py` définit sa propre
fonction locale `analyser_marche`, sans rapport avec ce module.)

## Pièges connus (observés dans le code)

- **`statistiques()` n'implémente pas tout son docstring** : le docstring (ligne 604)
  promet une ventilation « par type_marche, par CPV », mais le code ne produit que
  `par_preset` et les totaux globaux (lignes 608-628).

- **Appel externe sur une fonction privée** : `_ids_marches_pertinents()` (préfixe `_`,
  donc privée par convention) est importée et appelée par `enrichir_complet.py` et
  `diagnostic_dce_pertinents.py`. Renommer ou déplacer cette fonction casserait ces
  appelants.

- **Tri potentiellement contre-intuitif** dans `marches_pertinents_pour_preset()`
  (lignes 598-599) : la clé est `(-score_brut, date)` ET `reverse=False`. Le score est
  donc trié décroissant (clé déjà négative), mais la date l'est croissant. (Comportement
  voulu ou non — à confirmer.)

- **Deux constantes pour la même collection** : `COLLECTION_BRIEFS` (ligne 635) et
  `COLLECTION_BRIEFS_EXTRAITS` (ligne 195) valent toutes deux `"briefs_extraits"`.
  Risque de confusion à la maintenance.

- **`force` ne purge pas les scores obsolètes** : `analyser_tous_les_marches` part de
  `nouveaux_scores = dict(scores_existants)` (ligne 475) et patche par couple
  marché×preset. Un preset supprimé ou un marché retiré laisse ses anciennes entrées
  dans `scores_matching`. (à confirmer)

- **Import `preset` apparemment inutilisé** : importé ligne 62 mais aucune référence
  `preset.` dans le fichier. (à confirmer — peut servir pour un effet de bord au load.)

- **Le verdict IA prime même s'il dit `hors`** : dans `analyser_tous_les_marches`
  (lignes 498-505), dès que `niveau != "non_classifie"`, la décision IA est retenue,
  y compris un `matche=False` (niveau `hors`), écartant un éventuel match keyword. Voulu
  selon le docstring (« IA = autorité si dispo », ligne 494) mais à garder en tête.

- **Le mode `dry_run` incrémente `enrichis_nouveaux`** (ligne 741) sans rien générer ;
  le compteur reflète alors le nombre de marchés *qui seraient* enrichis, pas un travail
  réel.
