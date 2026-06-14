# Module stockage

## Rôle

Couche d'abstraction de persistance unique de Tendia : tout accès aux données passe par ce module, qui stocke toutes les collections sous forme JSON dans une base SQLite générique de type clé/valeur (`stockage.py:1-38`). Il expose une API stable (`charger`, `sauver`, `lire`, `ecrire`, `supprimer`, `lister_ids`, `invalider_cache`) doublée d'un cache mémoire.

## Modèle de stockage

### Emplacement de la base

- La base est un fichier SQLite unique : `data/tendia.db` (`DATA_DIR` et `DB_FILENAME`, lignes 48-50 ; `chemin_db()`, ligne 76-78).
- `DATA_DIR` est calculé à partir du dossier du fichier `stockage.py` (`_BASE_DIR`, ligne 48). Le dossier `data/` est créé à la demande par `_assurer_data_dir()` (ligne 81-82).

### Table `kv_storage` (schéma SQL réel)

Créée par `_init_db()` (ligne 114-129), de façon idempotente (`CREATE TABLE IF NOT EXISTS`) :

```sql
CREATE TABLE IF NOT EXISTS kv_storage (
    collection      TEXT NOT NULL,
    id              TEXT NOT NULL,
    contenu_json    TEXT NOT NULL,
    cree_le         TEXT NOT NULL,
    mis_a_jour_le   TEXT NOT NULL,
    PRIMARY KEY (collection, id)
)
```

Un index est aussi créé sur la colonne `collection` :

```sql
CREATE INDEX IF NOT EXISTS idx_kv_collection ON kv_storage(collection)
```

Chaque ligne représente un objet : `contenu_json` contient l'objet sérialisé via `json.dumps(..., ensure_ascii=False)`. Les dates `cree_le` / `mis_a_jour_le` sont au format ISO UTC produit par `_maintenant_iso()` (ligne 150-151, format `%Y-%m-%dT%H:%M:%S.%fZ`).

Remarque : `ecrire()` met bien à jour `mis_a_jour_le` lors d'un conflit mais conserve le `cree_le` d'origine (ligne 248-254). En revanche `sauver()` réécrit `cree_le` et `mis_a_jour_le` à la valeur courante pour toutes les lignes, puisqu'il supprime puis réinsère tout (ligne 199-208).

### Connexion, WAL et pragmas

- La connexion est un singleton **thread-local** : `_LOCAL = threading.local()` (ligne 73), récupérée/ouverte par `_conn()` (ligne 85-111). Une connexion est créée une fois par thread (sqlite3 n'autorise pas le partage entre threads par défaut).
- Connexion ouverte en mode autocommit (`isolation_level=None`, ligne 99).
- Pragmas activés à l'ouverture (lignes 101-104) :
  - `PRAGMA journal_mode=WAL` (concurrence lecture/écriture)
  - `PRAGMA synchronous=NORMAL`
  - `PRAGMA foreign_keys=ON`
  - `PRAGMA temp_store=MEMORY`
- `conn.row_factory = sqlite3.Row` (ligne 106), donc les lignes sont accessibles par nom de colonne.
- Le schéma est initialisé au premier accès de chaque thread via l'appel `_init_db(conn)` en fin de `_conn()` (ligne 110).

### Cache mémoire

- `_CACHE_MEMOIRE` est un dict de module au format `{collection: (timestamp_lecture, dict)}` (ligne 145-147).
- `charger()` peuple le cache et le renvoie directement aux appels suivants (ligne 164-165, 182).
- `lire()` et `lister_ids()` utilisent le cache **si la collection y est déjà** présente, sans déclencher de lecture SQL (ligne 221-222, 275-276).
- Toute écriture (`sauver`, `ecrire`, `supprimer`) invalide l'entrée de cache de la collection concernée (`_CACHE_MEMOIRE.pop(collection, None)`, lignes 215, 257, 269). Pour `supprimer`, l'invalidation n'a lieu que si une ligne a effectivement été supprimée (ligne 268-269).
- Le cache n'a **pas** de durée d'expiration : le timestamp stocké n'est jamais relu pour invalider (à confirmer : aucun usage du timestamp ailleurs dans le module).

## API publique

Toutes les signatures ci-dessous sont reprises littéralement du code.

### `charger(collection: str) -> dict` (ligne 158)
Retourne tout le contenu d'une collection sous forme `{id: objet}`. Retourne `{}` si la collection est vide ou inexistante. Sert le cache si présent, sinon lit toutes les lignes de la collection et désérialise chaque `contenu_json`. En cas de JSON corrompu, l'objet est remplacé par `{"_erreur_parse_json": <texte brut>}` au lieu de lever (ligne 177-180). Peuple le cache avant de retourner.

### `sauver(collection: str, donnees: dict) -> None` (ligne 186)
Remplace **tout** le contenu de la collection par `donnees` (overwrite complet, équivalent à réécrire un fichier JSON entier). Opère dans une transaction explicite `BEGIN` / `COMMIT` (`DELETE` de la collection puis `INSERT` de chaque entrée) avec `ROLLBACK` + `raise` en cas d'erreur (ligne 197-212). Les ids sont convertis en `str(id_objet)`. Invalide le cache de la collection (ligne 215). Ne retourne rien.

### `lire(collection: str, id_objet: str) -> Optional[dict]` (ligne 218)
Retourne l'objet identifié par `id_objet`, ou `None` s'il n'existe pas. Utilise le cache si la collection y est, sinon une requête ciblée (`WHERE collection = ? AND id = ?`). Même tolérance au JSON corrompu que `charger` (renvoie `{"_erreur_parse_json": ...}`, ligne 233-234). L'id est comparé en `str(id_objet)`.

### `ecrire(collection: str, id_objet: str, objet: dict) -> None` (ligne 237)
Insère ou met à jour un seul objet via un upsert atomique `INSERT ... ON CONFLICT(collection, id) DO UPDATE` (ligne 248-254). Plus efficace que `charger` + modifier + `sauver` pour modifier un seul objet. Met à jour uniquement `contenu_json` et `mis_a_jour_le` en cas de conflit (le `cree_le` reste celui de la première insertion). Invalide le cache de la collection (ligne 257). Ne retourne rien.

### `supprimer(collection: str, id_objet: str) -> bool` (ligne 260)
Supprime l'objet. Retourne `True` si une ligne a été supprimée, `False` si l'objet n'existait pas (basé sur `curseur.rowcount`, ligne 267). N'invalide le cache que si la suppression a eu lieu (ligne 268-269).

### `lister_ids(collection: str) -> list` (ligne 273)
Retourne la liste des ids de la collection (liste vide si inexistante). Sert depuis le cache si présent (renvoie `list(...keys())`), sinon `SELECT id`.

### `invalider_cache(collection: Optional[str] = None) -> None` (ligne 286)
Vide le cache mémoire. Sans argument (ou `None`), vide tout le cache (`_CACHE_MEMOIRE.clear()`) ; avec un nom de collection, ne retire que cette entrée.

### Fonctions backend (optionnelles)

- `chemin_db() -> str` (ligne 76) : chemin absolu du fichier `.db`.
- `initialiser_db() -> None` (ligne 132) : force la création des tables (utile pour tests/scripts) en appelant `_init_db(_conn())`.
- `migrer_depuis_json(forcer: bool = False) -> dict` (ligne 298) : migre les anciens fichiers `data/<collection>.json` listés dans `COLLECTIONS` vers `kv_storage`. Idempotent. Sans `forcer`, ne migre que les collections vides côté SQLite (les autres sont marquées `deja_migre`). Cas spécial pour `organisme` : si le JSON est un dict racine avec une clé `id`, il est enveloppé en `{id: objet}` (ligne 340-341). Retourne un rapport `{collection: {statut, migres, ...}}` avec des statuts comme `pas_de_fichier_json`, `deja_migre`, `erreur_lecture`, `format_inattendu`, `migre`.
- `rechercher_json(collection: str, chemin_json: str, valeur: str, operateur: str = "=") -> list` (ligne 360) : recherche les ids dont un sous-champ JSON (via `json_extract`) correspond à `valeur`. Valide `operateur` contre la liste `=, LIKE, >, <, >=, <=, !=` et lève `ValueError` sinon (ligne 380-381). Exemple : `rechercher_json('marches', '$.cpv_principal', '80%', 'LIKE')`.

### Constante `COLLECTIONS`
Dict de référence des collections connues et de leur ancien nom de fichier JSON (lignes 55-66). Sert à la validation et à la migration. Une collection **inconnue** de cette liste reste tolérée (le K/V est générique) : c'est une simple référence, pas une contrainte.

## Dépendances

Imports de la bibliothèque standard uniquement (lignes 40-45) :

- `json`
- `os`
- `sqlite3`
- `threading`
- `datetime` (`datetime`, `timezone`)
- `typing` (`Optional`)

Aucune dépendance tierce ni interne au projet.

## Variables d'environnement

Aucune. Le module ne lit aucune variable d'environnement ; l'emplacement de la base est dérivé de `_BASE_DIR` (chemin du fichier source) et n'est pas configurable (à confirmer : pas d'override prévu dans le code).

## Exemples d'usage (appelants réels)

1. **`budget.py`** — journalisation des appels LLM, un objet à la fois, puis lecture de toute la collection :
   ```python
   stockage.ecrire(COLLECTION_APPELS, appel_id, entree)            # budget.py:244
   for appel in stockage.charger(COLLECTION_APPELS).values():       # budget.py:259
   ```

2. **`organisme.py`** — profil actif et bibliothèque de profils via `lire` / `ecrire` ciblés :
   ```python
   return stockage.lire(COLLECTION, ID_PROFIL)                      # organisme.py:242
   stockage.ecrire(COLLECTION, ID_PROFIL, profil_a_ecrire)          # organisme.py:254
   stockage.ecrire(COLLECTION_BIBLIOTHEQUE, id, profil)            # organisme.py:649
   ```

3. **`analyse.py`** — chargement de collections entières puis réécriture complète des scores, ou écriture ciblée d'un brief :
   ```python
   marches = stockage.charger("marches")                           # analyse.py:450
   stockage.sauver(COLLECTION_SCORES, nouveaux_scores)             # analyse.py:532
   stockage.ecrire(COLLECTION_BRIEFS, mid, brief)                  # analyse.py:766
   ```

(De nombreux scripts d'audit/diagnostic utilisent aussi `stockage.charger("marches")`, `stockage.charger("scores_matching")`, etc. — voir `audit_classifications.py`, `bilan_briefs.py`, `backfill_dce_qualite.py`.)

## Pièges connus

- **`sauver()` remplace TOUT.** Il fait un `DELETE` de toute la collection avant de réinsérer `donnees` (ligne 199-208). Tout id absent de `donnees` est définitivement perdu. Pour modifier un seul objet sans toucher au reste, utiliser `ecrire()`.
- **Cache servi tel quel, par référence.** `charger()` retourne l'objet dict stocké dans `_CACHE_MEMOIRE` (ligne 165), et `lire()` renvoie `...get(id)` sur ce même dict (ligne 222). Muter l'objet retourné mute le cache en place. Comme aucune écriture ne s'ensuit forcément, ces mutations ne sont pas persistées mais peuvent influencer les lectures suivantes du même processus jusqu'à invalidation. À traiter comme lecture seule.
- **Cohérence cache uniquement intra-process.** L'invalidation se fait par `pop` du dict de module à chaque écriture, mais un autre processus écrivant dans la même base ne videra pas ce cache. Le WAL gère la concurrence SQLite, pas la fraîcheur du cache Python.
- **Connexion thread-local.** Chaque thread ouvre sa propre connexion (ligne 73, 93-107). Le cache mémoire, lui, est un dict de module **partagé entre threads** sans verrou : possibles courses sur `_CACHE_MEMOIRE` en contexte multi-thread (à confirmer : aucun lock autour du cache).
- **JSON corrompu silencieux.** `charger()` et `lire()` ne lèvent pas sur un `contenu_json` invalide : ils renvoient `{"_erreur_parse_json": <texte brut>}` (lignes 180, 234). Le code aval doit détecter cette clé s'il veut repérer l'anomalie.
- **Collections hors `COLLECTIONS` tolérées.** Toute collection peut être écrite/lue même si elle n'est pas listée dans `COLLECTIONS` (ligne 52-66) ; la liste sert seulement de référence et de périmètre de migration. Une collection non listée ne sera donc jamais migrée par `migrer_depuis_json()`.
- **Conversion des ids en `str`.** `sauver`, `ecrire`, `lire`, `supprimer` appliquent `str(id_objet)` (lignes 208, 254, 228, 265). Un id numérique `42` et la chaîne `"42"` désignent la même ligne ; les clés retournées par `charger`/`lister_ids` sont toujours des chaînes.
- **`migrer_depuis_json` sans `forcer` n'écrase jamais.** Si la collection SQLite contient déjà des ids, la migration est ignorée (`deja_migre`, ligne 322-328). Pour réimporter par-dessus, il faut `forcer=True` (qui déclenche un `sauver`, donc un remplacement complet).
