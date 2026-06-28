# Digest mémoire — Sprint A

## Objectif
Préalable à la future feature « génération de mémoire technique (.docx, 30-60 pages) ».
Le **digest mémoire** est une matière première **narrative par lot**, plus riche que les
champs structurés du brief (qui s'arrêtent à `particularites`, 2-5 phrases). Il croise le
**CCTP du lot** avec le **barème publié du marché** pour produire un JSON structuré
exploitable par le générateur de mémoire (Sprint B).

## Trigger LAZY
Le digest d'un lot n'est **pas** généré par le pipeline batch. Il est généré **à la
demande**, la première fois qu'un user demande une mémoire sur ce lot, puis **stocké et
mutualisé** pour tous les users suivants. Pour le Sprint A, on l'appelle **uniquement
depuis le CLI**.

## Stockage
- Base : SQLite `data/tendia.db`, table `kv_storage`, collection **`digests_memoire`**
  (aucune nouvelle table, pattern existant).
- Clé : `digest_memoire__<id_marche>__lot_<numero>`
- Valeur : `{id_marche, numero_lot, intitule_lot, domaine_lot, version_prompt,
  genere_le, digest{...}, _meta{cout_eur, tokens_*, modele, duree_s, cctp_*}}`

## Structure du digest (`digest`)
- `synthese_lot` — 3-5 phrases.
- `objet_et_perimetre` — narratif détaillé (15-25 lignes).
- `exigences_techniques_detaillees[]` — `{categorie, exigence, source_cctp, criticite}`.
- `livrables_attendus_lot[]`
- `contraintes_specifiques[]`
- `moyens_attendus` — `{humains, materiels, organisationnels}`.
- `criteres_publics_adaptes_lot[]` — `{critere, ponderation_publiee, applicabilite_lot,
  elements_a_demontrer_dans_memoire[]}`.
- `points_attention_redaction[]` — inclut les hypothèses structurelles (« Hypothèse : … »).
- `elements_manquants_dans_DCE[]` — alimente les `[À COMPLÉTER]` de la mémoire finale.

Posture : on ne suppose **aucune** pondération non publiée (l'acheteur ne publie pas sa
grille interne), et on est **honnête** sur ce qui manque.

## Modules
- `prompts/digest_memoire_v1.py` — prompt système + gabarit utilisateur + `VERSION_PROMPT`.
- `services/digest_memoire.py` — `generer_digest_memoire_lot(...)` (cœur, lazy, cache,
  filtrage CCTP par lot avec cap d'entrée 80k tokens).
- `scripts/generer_digest_memoire.py` — CLI runner.

## Filtrage CCTP par lot
Les pièces du DCE (`data/dce/<id_marche>/`) sont filtrées par lot via heuristique sur le
nom de fichier (`lot_N`, `lot N`, `lotN`, ou tokens de l'intitulé). À défaut de filtre
clair → **fallback : tout le DCE du marché**. Cap d'entrée **80 000 tokens** (tronqué avec
alerte au-delà).

## Lancer

```bash
# Unitaire
python scripts/generer_digest_memoire.py --id-marche BOAMP-26-56326 --numero-lot 1

# Dry-run (estimation coût, aucun appel LLM)
python scripts/generer_digest_memoire.py --id-marche BOAMP-26-56326 --numero-lot 1 --dry-run

# Forcer la régénération
python scripts/generer_digest_memoire.py --id-marche BOAMP-26-56326 --numero-lot 1 --force

# Cap budget par digest
python scripts/generer_digest_memoire.py --id-marche XXX --numero-lot 1 --max-cout 0.50

# Batch de validation (5 digests stratifiés → data/validation_digests/)
python scripts/generer_digest_memoire.py --batch-validation
```

Guards CLI : `--dry-run`, `--force`, `--max-cout`, `--limite`, `--batch-validation`.

## Batch de validation
`--batch-validation` génère 5 digests stratifiés (BTP gros œuvre · BTP multi-corps · IT ·
Ingénierie/MOE · Conseil/services), choisis parmi les marchés briefés en base, et les dump
dans `data/validation_digests/` pour audit manuel. Un **backup SQLite** est fait avant le
run. Si une cible manque (brief/DCE absent), elle est skippée avec un warning.

Relire un digest :
```bash
python -c "import json; print(json.dumps(json.load(open('data/validation_digests/BOAMP-26-56995_lot_2.json',encoding='utf-8'))['digest'],ensure_ascii=False,indent=2))"
```

## Notes
- Modèle : `claude-sonnet-4-6`. Coût loggé dans `_meta` + console.
- N'INTÈGRE RIEN au pipeline d'extraction existant (`llm_extract.py`, `tendia_pipeline.py`).
- Le générateur de mémoire `.docx` est le **Sprint B** (hors périmètre ici).
