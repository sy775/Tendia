"""
stockage.py
-----------
Couche d'abstraction de persistance pour Tendia.

VERSION 3 — backend SQLite (Sprint 3) :
- Base SQLite unique : data/tendia.db
- Table unique 'kv_storage(collection, id, contenu_json)' qui stocke toutes
  les collections sous forme JSON. Approche K/V générique.
- API publique INCHANGÉE par rapport à la v2 (backend JSON) : tout le code
  aval (organisme.py, matching.py, tendia_recup.py, etc.) continue à
  fonctionner sans modification.
- Migration JSON → SQLite : appel à migrer_depuis_json() une fois pour
  reprendre une base existante (transparent si la base est déjà migrée).

INTÉRÊT par rapport à la v2 :
- Écritures atomiques natives (transactions SQL)
- Concurrence lecture/écriture (WAL mode)
- Recherches sur sous-champs JSON via json_extract() de SQLite
- Préparation à l'ingestion brute large (10k-100k marchés) sans dégradation

INTERFACE PUBLIQUE (identique à v2) :
    charger(collection)             -> dict { id: objet }
    sauver(collection, donnees)     -> None
    lire(collection, id)            -> objet | None
    ecrire(collection, id, objet)   -> None
    supprimer(collection, id)       -> bool
    lister_ids(collection)          -> list[str]
    invalider_cache(collection)     -> None

FONCTIONS BACKEND (nouvelles, optionnelles) :
    chemin_db()                     -> str (chemin du fichier .db)
    initialiser_db()                -> None (force la création des tables)
    migrer_depuis_json()            -> dict (rapport de migration)
    rechercher_json(coll, chemin_json, valeur, operateur) -> list[id]

Principe : tout accès aux données passe par ce module.
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional


_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_BASE_DIR, "data")
DB_FILENAME = "tendia.db"

# Collections connues — utilisé pour la validation et la migration depuis JSON.
# Une collection inconnue est tolérée (le K/V est générique), mais cette liste
# sert de référence et de "documentation vivante".
COLLECTIONS = {
    "marches": "marches.json",                       # avis ouverts BOAMP
    "marches_notifies": "marches_notifies.json",     # marchés gagnés DECP
    "marches_tendia_attribues": "marches_tendia_attribues.json",  # base interne haute qualité
    "organisme": "organisme.json",                   # profil actif
    "matchings": "matchings.json",                   # résultats de matching
    "titulaires": "titulaires.json",                 # cache enrichissement SIRENE
    "briefs_extraits": "briefs_extraits.json",       # briefs LLM mutualisés (Sprint 3)
    "briefs_calibres": "briefs_calibres.json",       # calibrations LLM par preset
    "scores_matching": "scores_matching.json",       # cache des scores par marché × preset
    "llm_appels": "llm_appels.json",                 # log audit appels LLM (budget)
}


# ---------------------------------------------------------------------------
# Connexion SQLite (singleton thread-local)
# ---------------------------------------------------------------------------

_LOCAL = threading.local()


def chemin_db() -> str:
    """Retourne le chemin absolu du fichier de base SQLite."""
    return os.path.join(DATA_DIR, DB_FILENAME)


def _assurer_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def _conn() -> sqlite3.Connection:
    """
    Retourne la connexion SQLite du thread courant. Connexion ouverte
    à la demande, créée une fois par thread (sqlite3 n'accepte pas de
    partage de connexion entre threads par défaut).

    Active WAL mode et autres pragmas dès l'ouverture.
    """
    conn = getattr(_LOCAL, "conn", None)
    if conn is not None:
        return conn

    _assurer_data_dir()
    db_path = chemin_db()
    conn = sqlite3.connect(db_path, isolation_level=None)  # autocommit
    # Pragmas perf + cohérence
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA temp_store=MEMORY")
    # Retourner les rows en dicts-like via Row
    conn.row_factory = sqlite3.Row
    _LOCAL.conn = conn

    # Initialise le schéma au premier accès
    _init_db(conn)
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    """Crée les tables si elles n'existent pas. Idempotent."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kv_storage (
            collection      TEXT NOT NULL,
            id              TEXT NOT NULL,
            contenu_json    TEXT NOT NULL,
            cree_le         TEXT NOT NULL,
            mis_a_jour_le   TEXT NOT NULL,
            PRIMARY KEY (collection, id)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_kv_collection
            ON kv_storage(collection)
    """)


def initialiser_db() -> None:
    """Force la création des tables (utile pour tests / scripts)."""
    _init_db(_conn())


# ---------------------------------------------------------------------------
# Cache mémoire (préserve le comportement v2 pour les lectures fréquentes)
# ---------------------------------------------------------------------------
#
# Le cache mémoire reste utile même avec SQLite : il évite N requêtes SQL
# successives quand un code fait charger() puis itère. La cohérence est
# garantie en invalidant le cache à chaque écriture (sauver/ecrire/supprimer).
#
# Format : {collection: (timestamp_lecture, dict)}

_CACHE_MEMOIRE: dict = {}


def _maintenant_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# ---------------------------------------------------------------------------
# API publique — identique à la v2
# ---------------------------------------------------------------------------

def charger(collection: str) -> dict:
    """Retourne tout le contenu d'une collection sous forme dict {id: objet}.
    
    Retourne {} si la collection est vide ou inexistante.
    """
    # Cache mémoire : retourne directement si présent
    if collection in _CACHE_MEMOIRE:
        return _CACHE_MEMOIRE[collection][1]

    conn = _conn()
    rows = conn.execute(
        "SELECT id, contenu_json FROM kv_storage WHERE collection = ?",
        (collection,)
    ).fetchall()

    donnees = {}
    for row in rows:
        try:
            donnees[row["id"]] = json.loads(row["contenu_json"])
        except json.JSONDecodeError:
            # Tolère un contenu corrompu : on retourne la string brute,
            # le code aval pourra logger l'anomalie.
            donnees[row["id"]] = {"_erreur_parse_json": row["contenu_json"]}

    _CACHE_MEMOIRE[collection] = (_maintenant_iso(), donnees)
    return donnees


def sauver(collection: str, donnees: dict) -> None:
    """Remplace TOUT le contenu d'une collection par 'donnees' (replace
    complet, équivalent à un overwrite du fichier JSON dans la v2).
    
    Atomicité via transaction SQL : si une écriture échoue, la collection
    reste dans son état précédent.
    """
    conn = _conn()
    maintenant = _maintenant_iso()

    # Transaction : DELETE + INSERTs en bloc
    conn.execute("BEGIN")
    try:
        conn.execute(
            "DELETE FROM kv_storage WHERE collection = ?",
            (collection,)
        )
        for id_objet, objet in donnees.items():
            contenu = json.dumps(objet, ensure_ascii=False)
            conn.execute("""
                INSERT INTO kv_storage (collection, id, contenu_json, cree_le, mis_a_jour_le)
                VALUES (?, ?, ?, ?, ?)
            """, (collection, str(id_objet), contenu, maintenant, maintenant))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    # Invalide le cache pour cette collection
    _CACHE_MEMOIRE.pop(collection, None)


def lire(collection: str, id_objet: str) -> Optional[dict]:
    """Retourne un objet par son id, ou None s'il n'existe pas."""
    # Si la collection entière est en cache, on l'utilise
    if collection in _CACHE_MEMOIRE:
        return _CACHE_MEMOIRE[collection][1].get(id_objet)

    conn = _conn()
    row = conn.execute(
        "SELECT contenu_json FROM kv_storage WHERE collection = ? AND id = ?",
        (collection, str(id_objet))
    ).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["contenu_json"])
    except json.JSONDecodeError:
        return {"_erreur_parse_json": row["contenu_json"]}


def ecrire(collection: str, id_objet: str, objet: dict) -> None:
    """Insère ou met à jour un objet dans une collection.
    
    Plus efficace que charger+modifier+sauver pour modifier UN objet :
    pas de relecture/réécriture du reste de la collection.
    """
    conn = _conn()
    maintenant = _maintenant_iso()
    contenu = json.dumps(objet, ensure_ascii=False)

    # INSERT ON CONFLICT pour upsert atomique
    conn.execute("""
        INSERT INTO kv_storage (collection, id, contenu_json, cree_le, mis_a_jour_le)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(collection, id) DO UPDATE SET
            contenu_json = excluded.contenu_json,
            mis_a_jour_le = excluded.mis_a_jour_le
    """, (collection, str(id_objet), contenu, maintenant, maintenant))

    # Invalide le cache
    _CACHE_MEMOIRE.pop(collection, None)


def supprimer(collection: str, id_objet: str) -> bool:
    """Supprime un objet. Retourne True si supprimé, False s'il n'existait pas."""
    conn = _conn()
    curseur = conn.execute(
        "DELETE FROM kv_storage WHERE collection = ? AND id = ?",
        (collection, str(id_objet))
    )
    supprime = curseur.rowcount > 0
    if supprime:
        _CACHE_MEMOIRE.pop(collection, None)
    return supprime


def lister_ids(collection: str) -> list:
    """Retourne la liste des ids d'une collection (vide si inexistante)."""
    if collection in _CACHE_MEMOIRE:
        return list(_CACHE_MEMOIRE[collection][1].keys())

    conn = _conn()
    rows = conn.execute(
        "SELECT id FROM kv_storage WHERE collection = ?",
        (collection,)
    ).fetchall()
    return [row["id"] for row in rows]


def invalider_cache(collection: Optional[str] = None) -> None:
    """Vide le cache mémoire. Sans argument : vide tout."""
    if collection is None:
        _CACHE_MEMOIRE.clear()
    else:
        _CACHE_MEMOIRE.pop(collection, None)


# ---------------------------------------------------------------------------
# Migration JSON → SQLite (idempotent)
# ---------------------------------------------------------------------------

def migrer_depuis_json(forcer: bool = False) -> dict:
    """
    Migre les anciennes collections JSON (data/<collection>.json) vers la
    table SQLite kv_storage. Idempotent : peut être appelée plusieurs fois
    sans danger.

    Args:
        forcer: si True, écrase les collections SQLite existantes même si
                elles ont déjà du contenu. Sinon, n'écrase que les collections
                vides côté SQLite.

    Retourne un rapport {collection: {migres, ignores, statut}}.
    """
    rapport = {}
    _conn()  # assure DB initialisée

    for collection, fichier_json in COLLECTIONS.items():
        chemin = os.path.join(DATA_DIR, fichier_json)
        if not os.path.exists(chemin):
            rapport[collection] = {"statut": "pas_de_fichier_json", "migres": 0}
            continue

        # Si la collection SQLite contient déjà des données, skip (sauf forcer)
        ids_existants = lister_ids(collection)
        if ids_existants and not forcer:
            rapport[collection] = {
                "statut": "deja_migre",
                "migres": 0,
                "ids_deja_en_base": len(ids_existants),
            }
            continue

        # Lire le JSON et migrer
        try:
            with open(chemin, "r", encoding="utf-8") as f:
                donnees = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            rapport[collection] = {"statut": "erreur_lecture", "erreur": str(e)}
            continue

        # Cas particulier : profil organisme peut être stocké comme dict
        # racine (pas dict de dicts). On le wrap.
        if collection == "organisme" and isinstance(donnees, dict) and "id" in donnees:
            donnees = {donnees.get("id", "principal"): donnees}

        if not isinstance(donnees, dict):
            rapport[collection] = {
                "statut": "format_inattendu",
                "type_trouve": type(donnees).__name__,
            }
            continue

        sauver(collection, donnees)
        rapport[collection] = {"statut": "migre", "migres": len(donnees)}

    return rapport


# ---------------------------------------------------------------------------
# Fonction de requête sur sous-champ JSON (préparation Sprint 3 ingestion)
# ---------------------------------------------------------------------------

def rechercher_json(collection: str, chemin_json: str,
                     valeur: str, operateur: str = "=") -> list:
    """
    Recherche les ids d'une collection dont un sous-champ JSON correspond
    à une valeur. Utilise json_extract() natif de SQLite.

    Args:
        collection: nom de la collection
        chemin_json: chemin JSON style '$.cpv_principal', '$.acheteur.nom'
        valeur: valeur recherchée (string ou nombre)
        operateur: '=', 'LIKE', '>', '<', '>=', '<='

    Retourne une liste d'ids.

    Exemples :
        # Marchés ayant un CPV commençant par 80
        rechercher_json('marches', '$.cpv_principal', '80%', 'LIKE')
        # Marchés d'un acheteur particulier
        rechercher_json('marches', '$.acheteur_siret', '13002603100016', '=')
    """
    if operateur not in ("=", "LIKE", ">", "<", ">=", "<=", "!="):
        raise ValueError(f"Opérateur invalide : {operateur!r}")

    conn = _conn()
    query = f"""
        SELECT id FROM kv_storage
        WHERE collection = ?
          AND json_extract(contenu_json, ?) {operateur} ?
    """
    rows = conn.execute(query, (collection, chemin_json, valeur)).fetchall()
    return [row["id"] for row in rows]


# ---------------------------------------------------------------------------
# Diagnostic CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    print(f"Base SQLite       : {chemin_db()}")
    print(f"Existe            : {os.path.exists(chemin_db())}")
    print(f"Répertoire data   : {DATA_DIR}")
    print(f"Collections connues : {list(COLLECTIONS.keys())}")
    print()

    if len(sys.argv) > 1 and sys.argv[1] == "--migrer":
        print("=== Migration JSON → SQLite ===")
        forcer = "--forcer" in sys.argv
        rapport = migrer_depuis_json(forcer=forcer)
        for coll, r in rapport.items():
            print(f"  {coll:30} {r}")
    else:
        print("=== État des collections en base ===")
        for coll in COLLECTIONS:
            try:
                ids = lister_ids(coll)
                print(f"  {coll:30} : {len(ids)} objet(s)")
            except Exception as e:
                print(f"  {coll:30} : erreur ({e})")
        print()
        print("Usage : python stockage.py             (état des collections)")
        print("        python stockage.py --migrer     (migrer JSON → SQLite)")
        print("        python stockage.py --migrer --forcer")
