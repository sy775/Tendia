# Module tendia_extraire

Documentation du fichier `tendia_extraire.py`. Rédigée d'après lecture intégrale
du source. Les numéros de ligne renvoient à la version documentée.

## Rôle

`tendia_extraire.py` est l'**orchestrateur d'extraction LLM des DCE**. Il
enchaîne : dossier DCE déposé par l'utilisateur → texte combiné des pièces →
appel LLM (Claude) → brief structuré complet stocké (JSON disque + base SQLite +
brief markdown).

Le workflow décrit dans le docstring du module (lignes 1-21) :

1. Scrute `data/dce/<id_marche>/` pour les PDFs déposés.
2. Pour chaque marché avec PDFs non encore traités (tracking par signature de
   hashs MD5) : extrait le texte, combine les pièces, envoie à Claude, stocke
   `data/extractions/<id>.json`, génère `rapports/brief_<id>.md`.
3. Met à jour `data/extractions/_etat.json` (tracking).

Chemins fixes calculés depuis l'emplacement du script (lignes 36-42) :

- `REPERTOIRE_BASE` = répertoire du script.
- `REPERTOIRE_DCE` = `data/dce`.
- `REPERTOIRE_EXTRACTIONS` = `data/extractions`.
- `REPERTOIRE_RAPPORTS` = `rapports`.
- `FICHIER_ETAT` = `data/extractions/_etat.json`.
- `COLLECTION_MARCHES = "marches"`.

## Fonction `traiter_marche(id_marche, dossier, pdfs, dry_run=False, verbose=True)`

Définie lignes 256-410. C'est le cœur de l'orchestration : extraction texte →
LLM → stockage. Retourne un dict
`{"ok": bool, "extraction": dict|None, "erreur": str|None, "raison": str|None}`
(docstring lignes 259-268). Les `raison` possibles : `"pdfs_non_dce"`,
`"extraction_llm"`, ou absente.

Étapes exactes :

1. **Affichage** (si `verbose`) du marché, du dossier et de la liste des PDFs
   avec total de caractères (lignes 270-274).

2. **Filtre des PDFs non-DCE** (« Sprint 3 », lignes 276-297). Pour chaque PDF,
   appelle `_est_pdf_non_dce(nom, taille_chars)` (lignes 73-93) qui rejette :
   - un nom contenant un motif de `PATTERNS_PDF_NON_DCE` (guides de dépôt, DUME
     acheteur, etc. — lignes 55-62),
   - une taille `< 1000` chars (PDF corrompu / OCR raté),
   - une taille `< 10000` chars sans motif métier reconnu de
     `PATTERNS_PDF_DCE_VALIDE` (lignes 64-70).

   Les rejetés sont listés ; si **aucun** PDF valide ne reste, retourne
   `{"ok": False, ..., "raison": "pdfs_non_dce"}` (lignes 291-297).

3. **Chargement du marché en base** pour le contexte (lignes 299-305) :
   `stockage.charger(COLLECTION_MARCHES)` puis `.get(id_marche)`. Si le marché
   est absent, continue avec un contexte minimal `{"id": id_marche}`.

4. **Construction du contexte** via `_construire_contexte(marche)` (ligne 307),
   qui inclut notamment la clé `'id'` (voir helper plus bas).

5. **Combinaison des textes** via `_combiner_textes(pdfs_valides)` (ligne 308).

6. **Court-circuit `dry_run`** (lignes 310-315) : si `dry_run` est vrai, pas
   d'appel API ; retourne `{"ok": True, "extraction": None, "erreur": None,
   "dry_run": True}`.

7. **Appel LLM** : `llm_extract.extraire_via_llm(texte_combine, contexte,
   verbose=verbose)` (lignes 317-320). Si le retour est falsy, retourne
   `{"ok": False, ..., "raison": "extraction_llm"}` (lignes 321-326).

8. **Récupération des méta d'appel** (lignes 328-331) : `extraction.pop(
   "_appel_llm", None)` (injecté par `extraire_via_llm`), d'où `codes_presets`.
   Horodatage UTC ISO via `datetime.now(timezone.utc).isoformat()`.

9. **Construction du bloc `_meta` complet** (« Chantier 1E : versioning prompts »,
   lignes 333-355). Champs écrits :
   - `id_marche`, `type: "complet"`,
   - `date_generation` (champ canonique) **et** `extraction_le` (alias
     rétro-compat) — tous deux = même horodatage (lignes 340-341),
   - `modele` = `appel_meta.get("modele")` sinon `llm_extract.MODELE`,
   - `preset_utilise` = premier code de `codes_presets` (ou `None`),
   - `presets_matches` = liste complète `codes_presets`,
   - `prompts_versions` = `preset.prompts_versions_pour_presets(codes_presets)`,
   - `tokens_input`, `tokens_output`, `cout_eur`, `duree_sec` (depuis
     `appel_meta`),
   - `pdfs_traites` = liste `{nom, hash, taille_chars}` pour **tous** les PDFs
     (`pdfs`, pas seulement les valides — lignes 351-354).

10. **Écriture JSON disque** : `data/extractions/<id_marche>.json`
    (lignes 357-363), `ensure_ascii=False, indent=2`.

11. **Écriture SQLite** : `stockage.ecrire("briefs_extraits", id_marche,
    extraction)` (lignes 365-374). Remplace un éventuel brief LIGHT précédent
    sur la même clé, de sorte que l'UI affiche le brief COMPLET. Échec capturé
    et seulement loggé.

12. **Sync de la classif IA** (« Sprint 2bis », lignes 376-399) : si
    `extraction["domaines_metier"]` est non vide et que les codes diffèrent de
    `classifications_ia[id_marche]`, met à jour cette collection (`source =
    "brief_complet"`, `mis_a_jour_le`). Échec capturé et loggé.

13. **Génération du brief markdown** via `_generer_brief(marche, extraction)`
    (ligne 402) puis écriture `rapports/brief_<id_marche>.md` (lignes 401-408).

14. Retourne `{"ok": True, "extraction": extraction, "erreur": None}`
    (ligne 410).

## Helpers

### `_scanner_dossiers_dce(force=False, verbose=True)` — lignes 183-224

Retourne `[(id_marche, dossier, pdfs_dict, raison), ...]` pour les marchés ayant
des PDFs à traiter. Pour chaque sous-dossier de `data/dce` :

1. `_dezipper_dossier(dossier, verbose)` — auto-décompression des zips déposés
   (ligne 208).
2. `pdf_extract.extraire_dossier(dossier, verbose=False)` — extraction du texte
   de **toutes** les pièces (ligne 212). Si vide, ignore le dossier.
3. Calcule `_signature_pdfs(pdfs)` et la compare à l'état précédent
   (`data/extractions/_etat.json`). Si identique **et** `force` faux, ignore
   (lignes 215-218).
4. `raison` ∈ `{"re-traitement forcé", "nouvelle extraction",
   "nouveaux PDFs détectés"}` (lignes 219-221).

Note : `extraire_dossier` traite `.pdf`, `.docx`, `.xlsx` (docstring de
`pdf_extract.extraire_dossier`), donc le scan n'est pas limité aux seuls PDFs
malgré le nom des variables.

### `_dezipper_dossier(dossier, verbose=True)` — lignes 100-150

Si des `.zip` sont présents dans le dossier, les extrait **à plat** (basename
seulement, pas de sous-dossier ; ignore les entrées en `/` ou commençant par
`.`). N'écrase pas un fichier cible existant. Après extraction, déplace le zip
dans `<dossier>/_zip_archives/` pour ne pas le re-traiter. Retourne le nombre de
zips traités. Erreurs capturées et loggées par zip.

### `_combiner_textes(pdfs)` — lignes 248-253

Concatène le texte de chaque pièce en un seul corpus, chaque bloc préfixé par
`\n\n=== PIÈCE : <nom> ===\n\n` suivi de `info['texte']`.

### `_construire_contexte(marche)` — lignes 231-245

Réduit le dict marché à un contexte pour le LLM. Clés produites : `id`,
`source`, `reference_externe`, `reference_ft_interne` (depuis `reference_ft`),
`titre`, `objet`, `acheteur` (depuis `acheteur_nom`), `date_publication`,
`date_limite_depot`, `categorie_metier`, `cpv_principal`. La clé `'id'` est bien
incluse (ligne 234).

### `_detecter_schema_chantier(ctc)` — lignes 536-554

Détermine le schéma de `caracteristiques_techniques_chantier` :
- `"btp"` si présence de `typologie_ouvrage` / `corps_etat` / `site_occupe`,
- `"enr"` si `technologies_concernees` / `type_de_sites` /
  `contraintes_site_signalees`,
- `"inconnu"` sinon (et si `ctc` n'est pas un dict).

Conservé pour les briefs antérieurs au routage par classif IA qui mélangeaient
les deux schémas.

### `_signature_pdfs(pdfs)` — lignes 173-176

Signature unique d'un ensemble de pièces : concaténation par `_` des hashs
triés (`info["hash"]`). Sert au tracking d'idempotence.

### Autres helpers

- `_charger_etat()` / `_sauver_etat(etat)` (lignes 157-170) : lecture/écriture
  de `_etat.json`.
- `_est_pdf_non_dce` (lignes 73-93) : détaillé plus haut.
- Helpers de rendu markdown : `_fmt_val`, `_item_label`, `_join_safe`,
  `_fmt_montant_euros`, `_bloc_non_vide`, `_fmt_bool`, `_kv_ligne`, `_liste_kv`
  (lignes 417-533).
- Sections sectorielles preset-aware du brief : `_section_chantier_btp`,
  `_section_chantier_enr`, `_section_moe`, `_section_conseil`, `_section_si`,
  `_section_formation` (lignes 559-1000) — chacune s'auto-skippe si son bloc est
  vide.
- `_generer_brief(marche, extraction)` (lignes 1003-1177) : assemble le brief
  markdown 1-page (identifiants, synthèse, sections sectorielles, montant,
  barème, références, lots, alertes, points différenciants).

## CLI (argparse)

`main()` (lignes 1184-1276). Arguments :

- `--marche <id>` : ne traiter qu'un marché précis (filtre appliqué après le
  scan, lignes 1230-1231).
- `--force` : re-extraire même si la signature PDF est inchangée.
- `--dry-run` : pas d'appel API, scan + extraction texte seulement.

Comportement : affiche un en-tête (dossiers, `llm_extract.MODELE`). Hors
`dry_run`, vérifie la clé API via `llm_extract._obtenir_cle_api()` ; si absente,
affiche les instructions `.env` et `sys.exit(1)` (lignes 1205-1221). Scanne via
`_scanner_dossiers_dce(force=args.force)`, traite chaque marché via
`traiter_marche`, et **après un succès hors dry-run** met à jour `_etat.json`
avec `signature_pdfs`, `extrait_le` (UTC ISO) et la liste des noms de PDFs
(lignes 1253-1261). Affiche un bilan succès/échec.

Point d'entrée : `if __name__ == "__main__": main()` (lignes 1278-1279).

## Dépendances et variables d'environnement

Modules internes importés (lignes 30-33) :

- `stockage` : `charger(collection)`, `lire(collection, id)`,
  `ecrire(collection, id, valeur)` — collections `marches`, `briefs_extraits`,
  `classifications_ia`.
- `pdf_extract` : `extraire_dossier(dossier, verbose)` → `{nom: {hash, texte,
  taille_chars, format}}`.
- `llm_extract` : `extraire_via_llm(texte, contexte, verbose)`, constante
  `MODELE` (= `"claude-sonnet-4-6"` dans le source lu), `_obtenir_cle_api()`.
- `preset` : `prompts_versions_pour_presets(codes_presets)`.

Modules standard : `argparse`, `json`, `os`, `sys`, `zipfile`, `datetime`.

Variables d'environnement : aucune lue directement dans ce fichier. La clé API
(`ANTHROPIC_API_KEY`, lisible via `.env`) est gérée par
`llm_extract._obtenir_cle_api()` (les instructions affichées par `main` citent
`ANTHROPIC_API_KEY`).

## Exemples d'usage (appelants réels)

### `reextraire_briefs_complet.py`

Importe `tendia_extraire` (ligne 33). Appelle
`tendia_extraire._scanner_dossiers_dce(force=True, verbose=False)` (ligne 75)
puis `tendia_extraire.traiter_marche(mid, _dossier_scan, pdfs, ...)` (ligne 106),
et ré-ouvre ensuite le brief que `traiter_marche` a stocké en base.

### `relancer_extraction_chantier1.py`

Importe `stockage, preset, tendia_extraire, pdf_extract` (ligne 21). Appelle
`tendia_extraire._dezipper_dossier(dossier, verbose=False)` (ligne 136) puis
`tendia_extraire.traiter_marche(mid, dossier, pdfs, dry_run=False,
verbose=False)` (ligne 140).

### En ligne de commande

```bash
python tendia_extraire.py                  # tous les marchés avec PDFs
python tendia_extraire.py --marche <id>    # un marché spécifique
python tendia_extraire.py --force          # re-extraire même si déjà fait
python tendia_extraire.py --dry-run        # pas d'appel API, juste scan
```

Autres modules du dépôt référençant `tendia_extraire` (par `grep`) : `auto_brief.py`,
`diag_gros_dce.py`, `enrichir_complet.py`, `regenerer_briefs_md.py`,
`regenerer_md.py`, `tendia_briefs_auto.py`, `tendia_pipeline.py`,
`tendia_reextraire_batch.py`, `tendia_telecharger_dce.py`, `tendia_veille.py`
(usages non détaillés ici).

## Pièges connus

- **`_scanner_dossiers_dce(force=True)` re-décompresse et ré-extrait TOUS les
  dossiers de `data/dce`** : il itère sur l'ensemble des sous-dossiers, appelle
  `_dezipper_dossier` puis `pdf_extract.extraire_dossier` pour chacun, avant de
  filtrer par signature. Avec `force=True` (cas de `reextraire_briefs_complet.py`),
  le filtre de signature est court-circuité et **tous** les marchés sont remis à
  traiter — lent sur de gros DCE.

- **`_meta` porte deux horodatages redondants** : `date_generation` (canonique)
  et `extraction_le` (alias rétro-compat utilisé par
  `identifier_briefs_pollues.py`), tous deux égaux (lignes 340-341).

- **Champs de routage ajoutés à `_meta`** : `preset_utilise` (premier preset),
  `presets_matches` (tous les presets ciblés) et `prompts_versions` (versions de
  prompt par preset). Ces champs dépendent de `_appel_llm` injecté par
  `extraire_via_llm` ; s'il est absent, `codes_presets` est vide et
  `preset_utilise` vaut `None` (lignes 329-346).

- **`pdfs_traites` liste TOUS les PDFs, pas seulement les valides** (`pdfs` et
  non `pdfs_valides`, lignes 351-354), alors que l'appel LLM ne porte que sur
  les pièces valides. Le contenu transmis au LLM et la liste tracée peuvent donc
  diverger. (à confirmer si c'est intentionnel)

- **Le tracking `_etat.json` n'est mis à jour que par `main()`**, pas par
  `traiter_marche`. Les appelants externes qui invoquent directement
  `traiter_marche` (les deux scripts ci-dessus) ne mettent donc pas à jour
  `_etat.json` eux-mêmes.

- **Écritures SQLite et sync classif IA sont silencieuses en cas d'échec** :
  exceptions capturées et seulement loggées (lignes 372-374, 397-399) ; le JSON
  disque, lui, n'est pas protégé par un `try`.
