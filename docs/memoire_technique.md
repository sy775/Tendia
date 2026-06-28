# Mémoire technique .docx — générateur à la demande (Sprint B)

## Objectif

Générer **à la demande** une mémoire technique de candidature (30–60 pages, `.docx`)
pour **un lot précis** d'un marché public, à partir des données **déjà extraites**
(brief, barème, DCE sur disque) et du **digest mémoire** du lot produit au Sprint A.

Trigger **lazy** : rien n'est branché sur le pipeline d'extraction batch. Tout
passe par les deux CLI dédiés. Aucun module du Sprint A n'est modifié (le
générateur réutilise en lecture seule `services/digest_memoire.py`).

## Architecture — 2 appels LLM séquentiels + assemblage `.docx`

```
digest (Sprint A) ─┐
profil organisme ──┤
barème + critères ─┼─► APPEL 1 (extraction contexte) ─► plan_redaction (JSON)
DCE sur disque ────┘                                          │
cadre acheteur .docx? (détection) ───────────────────────────┘
                                                              ▼
profil + plan + digest + DCE ─► APPEL 2 (rédaction) ─► sections_redigees (JSON)
                                                              ▼
                               ASSEMBLAGE ─► .docx (template Tendia OU cadre acheteur)
```

### Grille d'actions (barème) — matière transverse

En plus du digest et du DCE, les deux appels s'appuient sur la **grille d'actions**
extraite dans le brief (`bareme_notation.sous_criteres_techniques[*].grille_actions`
et `grille_actions_par_domaine`). `_memoire_commun.grille_redaction_lot(brief, lot)`
sélectionne, pour chaque sous-critère, les actions **filtrées sur le domaine du
lot** (ex. `btp_gros_oeuvre`), avec leur type (`livrable` / `levier`), poids % et
source (RC/CCTP). L'appel 1 doit **prévoir une section par action** ; l'appel 2
doit **démontrer chaque action** (les `livrable` en priorité). Repli sur la
`grille_actions` générique si le domaine n'est pas couvert. Prompts en **v1.1**.

### Appel 1 — Extraction du contexte mémoire
`services/extraction_contexte_memoire.py` + `prompts/extraction_contexte_memoire_v1.py`

- **Entrées** : digest du lot, DCE complet sur disque, profil organisme, barème,
  **grille d'actions filtrée par domaine**.
- **Sortie JSON** (`plan_redaction`) :
  - `cadre_reponse_impose` — `{detecte, fichier_template, structure_resumee}`
  - `posture_redaction` — `respecter_cadre_imposé | construire_selon_critères | hybride`
  - `plan_sections` — liste ordonnée `{section_id, titre, niveau (1-3), longueur_cible_pages, objectif, elements_a_couvrir, criteres_lies, contraintes}`
  - `elements_a_reprendre_verbatim` — `[{formulation, source}]`
  - `points_attention_specifiques` — `[...]`
- `MAX_TOKENS_REPONSE = 32000` (la spec prévoyait 16000 ; relevé après constat de
  troncature du plan sur les gros lots — output facturé au token réel, impact
  négligeable). Coût loggé **séparément** (`_meta.cout_appel_1_eur`).

### Appel 2 — Rédaction
`services/redaction_memoire.py` + `prompts/redaction_memoire_v1.py`

- **Entrées** : digest, `plan_redaction`, profil organisme, DCE (citations).
- **Sortie JSON** : `{section_id: texte_section}` couvrant **toutes** les sections du plan.
- Insère `[À COMPLÉTER : description précise]` là où le profil manque d'info
  (références nominatives, CV, certifications). **Aucune invention.**
- `MAX_TOKENS_REPONSE = 40000`. Coût loggé **séparément** (`_meta.cout_appel_2_eur`).

### Assemblage `.docx`
`services/assemblage_docx.py`

- **Si** un cadre de réponse acheteur `.docx` est détecté **et** confirmé par l'appel 1 :
  injection des sections sous les titres correspondants du template, **sans toucher**
  à ses styles/polices/en-têtes/pieds. Sections non rattachées → ajoutées en fin (H1).
- **Sinon** : template **Tendia** stylé (cf. ci-dessous).
- Sortie : `data/memoires/<id_marche>/<id_user>_lot<n>_<timestamp>.docx`

## Détection du cadre de réponse acheteur

Scan de `data/dce/<id_marche>/` pour un `.docx` dont le nom contient :
`cadre`+(`reponse`|`memoire`|`technique`), `annexe`+(`memoire`|`technique`),
`modele`+(`memoire`|`technique`), `trame`+(`reponse`|`memoire`).
Plusieurs candidats → le plus volumineux. L'appel 1 confirme/infirme en lisant
le fichier ; le chemin n'est retenu pour l'injection que si `cadre_reponse_impose.detecte = true`.

## Template Tendia (`.docx`)

- Titres **Cambria**, corps **Calibri** ; navy `#0F1B3D` (H1/H2/H3), gold `#C9A961` (filets, en-tête).
- Page de garde (placeholder logo, titre marché, lot, candidat, date).
- Sommaire auto (champ `TOC`, mis à jour à l'ouverture / `F9`).
- En-tête : marché abrégé + n° lot. Pied : `Page X / Y` + `Mémoire technique — <organisme>`.
- Marges 2,5 cm, A4 portrait, hiérarchie H1/H2/H3.
- `[À COMPLÉTER]` : encadré jaune clair (`#FFF6CC`), bordure pointillée dorée, texte
  surligné jaune → repérables en masse via **Ctrl+F « À COMPLÉTER »** dans Word.

## Stockage

Collection kv_storage : **`memoires_techniques`**
Clé : `memoire__<id_marche>__lot_<numero>__<id_user>__<timestamp>`

```json
{
  "id_marche", "numero_lot", "id_user", "intitule_lot",
  "timestamp", "template_acheteur",
  "version_prompt_extraction", "version_prompt_redaction", "genere_le",
  "plan_redaction": { ...sortie appel 1... },
  "sections_redigees": { "section_id": "texte", ... },
  "chemin_docx": "data/memoires/<id_marche>/<filename>.docx",
  "regenerations": [ {section_id, instruction_user, regenere_le, cout_eur, ...} ],
  "_meta": {
    "cout_total_eur", "cout_appel_1_eur", "cout_appel_2_eur",
    "tokens_entree_appel_1", "tokens_sortie_appel_1",
    "tokens_entree_appel_2", "tokens_sortie_appel_2",
    "modele", "duree_totale_s",
    "cctp_fichiers", "cctp_mode_filtre", "cctp_tronque",
    "sections_manquantes", "sections_hors_plan"
  }
}
```

## Commandes CLI

### Génération complète
```bash
python scripts/generer_memoire.py --id-marche BOAMP-26-56995 --numero-lot 2 --id-user demo_btp
```
Guards : `--dry-run` (estime le coût des 2 appels, aucun appel LLM),
`--max-cout 6.00` (plafond € total, abort si l'estimation dépasse),
`--force` (régénère même si une mémoire existe déjà),
`--batch-validation`, `--limite N`.

> Le profil `--id-user` est résolu d'abord dans la collection `organisme`, puis
> dans `data/profils_demo/<id_user>.json`.
> Le **digest** du lot doit exister au préalable (sinon erreur avec la commande à lancer) :
> `python scripts/generer_digest_memoire.py --id-marche <...> --numero-lot <n>`.

### Régénération d'une section
```bash
python scripts/regenerer_section.py \
  --memoire-id memoire__BOAMP-26-56995__lot_2__demo_btp__20260621T140000 \
  --section-id moyens_humains \
  --instruction "Insiste davantage sur notre expérience en zone urbaine dense"
```
Recharge la mémoire, relance l'appel 2 sur **cette seule section**, met à jour le
JSON en base, **ré-assemble le `.docx` complet** (même chemin), logue la
régénération dans `regenerations[]` et cumule le coût dans `_meta.cout_total_eur`.
Guards : `--dry-run`, `--max-cout`.

### Batch de validation (audit Younes)
```bash
python scripts/generer_memoire.py --batch-validation
```
1. Backup SQLite (`data/tendia.db.bak_avant_memoire_<horod>`).
2. Ingestion des 3 profils fictifs `data/profils_demo/*.json` → collection `organisme`.
3. Génère 3 mémoires stratifiées (BTP `56995/2`, IT `56097/1`, ingénierie `56090/1`).
4. `.docx` dans `data/memoires/<id_marche>/`, JSON dans `data/validation_memoires/`.

## Intégration UI (bouton sur la fiche marché)

> Initialement « sprint suivant » dans la spec ; ajouté à la demande de Younes.

Source d'orchestration mutualisée : `services/pipeline_memoire.py`
(`generer_memoire(...)`, accepte un `profil` déjà résolu ou un `id_user`),
utilisée par le CLI **et** l'UI.

Dans `tendia_ui.py`, fiche marché → section **« Comment candidater ? »** →
carte **« 2. Mémoire technique »** : un bouton **✍ Générer** par lot.

- **`POST /marche/<id>/generer-memoire/<numero_lot>`** : lance la génération dans
  un **thread de fond** (le serveur tourne en `threaded=True`). Génère d'abord le
  digest du lot s'il manque (lazy), puis la mémoire. Profil candidat = profil
  organisme **actif** (`organisme.lire_profil()`, id = clé `id_user`).
- **`GET /marche/<id>/memoire-statut/<numero_lot>`** : statut JSON
  (`absent | en_cours | pret | erreur`) pour le **polling** de la fiche (toutes
  les 5 s tant que `en_cours`). Rend ⏳ pendant la génération, puis ⬇ + coût.
- **`GET /marche/<id>/memoire/<numero_lot>/download`** : sert le `.docx` de la
  version **la plus récente** (`cle_memoire_existante` = max timestamp).
- Registre des jobs en mémoire (`_MEMOIRE_JOBS` + lock). Bouton **↻ Régénérer**
  (force) une fois la mémoire disponible.

## Garde-fous (rappel)

- Logging `cout_eur` **strict et séparé** sur les 2 appels ; cumul par mémoire dans `_meta`.
- Aucune réparation JSON automatique : si le parsing échoue (y compris réponse
  tronquée à `max_tokens`), **log clair + abort**. Younes traite.
- Pas de hardcoding sectoriel : le vocabulaire métier vient du digest / du profil
  (presets disponibles via `preset.py` si besoin d'enrichir un prompt).
- `stdout` UTF-8 forcé ; backup SQLite avant tout batch.
- Pas d'auto-régénération en cas d'erreur ; pas d'intégration UI/Flask (sprint suivant).

## Fichiers du sprint

| Fichier | Rôle |
|---|---|
| `services/_memoire_commun.py` | Helpers partagés (chargement entrées, appel LLM, parsing strict, contexte, coût) |
| `services/extraction_contexte_memoire.py` | Appel 1 — plan de rédaction + détection cadre acheteur |
| `services/redaction_memoire.py` | Appel 2 — rédaction des sections |
| `services/assemblage_docx.py` | Template Tendia + injection cadre acheteur |
| `services/regeneration_section.py` | Régénération d'une section |
| `prompts/extraction_contexte_memoire_v1.py` | Prompt appel 1 (v1) |
| `prompts/redaction_memoire_v1.py` | Prompts appel 2 + régénération (v1) |
| `scripts/generer_memoire.py` | Runner orchestrateur (unitaire / dry-run / batch) |
| `scripts/regenerer_section.py` | Runner régénération section |
| `data/profils_demo/` | 3 profils organisme fictifs (batch validation) |
| `data/memoires/` | Sorties `.docx` |
| `data/validation_memoires/` | Dumps JSON pour audit |
```
