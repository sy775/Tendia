"""
decp/db.py — schéma SQLite DECP + helpers.

Les tables DECP vivent dans la base Tendia existante (`data/tendia.db`), à côté
de la table KV `kv_storage`. Pas de base séparée.

Décision schéma (validée) : `marche_attribution_link.marche_tendia_id` référence
l'`id` KV-JSON d'un marché Tendia (ex. 'BOAMP-26-57070') — PAS de contrainte FK
SQL (la cible est une ligne JSON de `kv_storage`, pas une table relationnelle).
`decp/matching.verifier_marche_tendia_existe` vérifie l'existence avant insert.
"""
import json
import sqlite3
from pathlib import Path

DB_PATH_DEFAUT = Path("data/tendia.db")

DDL = """
CREATE TABLE IF NOT EXISTS decp_marches (
    id              TEXT PRIMARY KEY,
    source_fichier  TEXT NOT NULL,
    objet           TEXT,
    cpv_principal   TEXT,
    cpv_secondaires TEXT,
    acheteur_siret  TEXT,
    acheteur_nom    TEXT,
    titulaire_siret TEXT,
    titulaires_json TEXT,
    montant_eur     REAL,
    date_notification TEXT,
    duree_mois      INTEGER,
    procedure       TEXT,
    lieu_execution_code TEXT,
    departement     TEXT,
    region          TEXT,
    parsed_at       TEXT NOT NULL,
    parse_warnings  TEXT
);
CREATE INDEX IF NOT EXISTS idx_decp_cpv ON decp_marches(cpv_principal);
CREATE INDEX IF NOT EXISTS idx_decp_acheteur ON decp_marches(acheteur_siret);
CREATE INDEX IF NOT EXISTS idx_decp_titulaire ON decp_marches(titulaire_siret);
CREATE INDEX IF NOT EXISTS idx_decp_date ON decp_marches(date_notification);
CREATE INDEX IF NOT EXISTS idx_decp_dept ON decp_marches(departement);
CREATE INDEX IF NOT EXISTS idx_decp_montant ON decp_marches(montant_eur);

-- marche_tendia_id = id KV-JSON (collection 'marches'), pas de FK SQL réelle.
CREATE TABLE IF NOT EXISTS marche_attribution_link (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    marche_tendia_id TEXT NOT NULL,
    decp_id         TEXT NOT NULL,
    score_total     REAL NOT NULL,
    score_cpv       REAL,
    score_acheteur  REAL,
    score_periode   REAL,
    score_montant   REAL,
    statut          TEXT NOT NULL DEFAULT 'auto',
    created_at      TEXT NOT NULL,
    UNIQUE(marche_tendia_id, decp_id)
);
CREATE INDEX IF NOT EXISTS idx_link_tendia ON marche_attribution_link(marche_tendia_id);
CREATE INDEX IF NOT EXISTS idx_link_decp ON marche_attribution_link(decp_id);

CREATE TABLE IF NOT EXISTS decp_classification (
    decp_id         TEXT PRIMARY KEY,
    preset_principal TEXT,
    preset_secondaire TEXT,
    source          TEXT NOT NULL,
    confiance       REAL,
    classified_at   TEXT NOT NULL,
    FOREIGN KEY(decp_id) REFERENCES decp_marches(id)
);
CREATE INDEX IF NOT EXISTS idx_classif_preset ON decp_classification(preset_principal);
"""

_COLS = ["id", "source_fichier", "objet", "cpv_principal", "cpv_secondaires",
         "acheteur_siret", "acheteur_nom", "titulaire_siret", "titulaires_json",
         "montant_eur", "date_notification", "duree_mois", "procedure",
         "lieu_execution_code", "departement", "region", "parsed_at",
         "parse_warnings"]


def connexion(db_path=DB_PATH_DEFAUT) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_schema(db_path=DB_PATH_DEFAUT) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = connexion(db_path)
    try:
        con.executescript(DDL)
        con.commit()
    finally:
        con.close()


def inserer_marches(marches: list, db_path=DB_PATH_DEFAUT,
                    source_fichier: str = "decp_consolidee_api") -> int:
    """Batch insert (INSERT OR REPLACE sur l'id). parse_warnings sérialisé JSON.
    Retourne le nombre de lignes écrites."""
    if not marches:
        return 0
    con = connexion(db_path)
    n = 0
    try:
        rows = []
        for m in marches:
            if not m or not m.get("id"):
                continue
            m = dict(m)
            m.setdefault("source_fichier", source_fichier)
            pw = m.get("parse_warnings")
            if isinstance(pw, (list, dict)):
                m["parse_warnings"] = json.dumps(pw, ensure_ascii=False)
            rows.append(tuple(m.get(c) for c in _COLS))
        ph = ",".join("?" * len(_COLS))
        con.executemany(
            f"INSERT OR REPLACE INTO decp_marches ({','.join(_COLS)}) VALUES ({ph})",
            rows)
        con.commit()
        n = len(rows)
    finally:
        con.close()
    return n


def inserer_lien(lien: dict, db_path=DB_PATH_DEFAUT) -> bool:
    """Insère un lien marché↔attribution (INSERT OR IGNORE sur l'unicité)."""
    con = connexion(db_path)
    try:
        cur = con.execute(
            """INSERT OR IGNORE INTO marche_attribution_link
               (marche_tendia_id, decp_id, score_total, score_cpv, score_acheteur,
                score_periode, score_montant, statut, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (lien["marche_tendia_id"], lien["decp_id"], lien["score_total"],
             lien.get("score_cpv"), lien.get("score_acheteur"),
             lien.get("score_periode"), lien.get("score_montant"),
             lien.get("statut", "auto"), lien["created_at"]))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def compter_marches(db_path=DB_PATH_DEFAUT) -> dict:
    con = connexion(db_path)
    try:
        q = con.execute("""
            SELECT COUNT(*) total,
                   SUM(CASE WHEN montant_eur > 0 THEN 1 ELSE 0 END) avec_montant,
                   SUM(CASE WHEN cpv_principal IS NOT NULL THEN 1 ELSE 0 END) avec_cpv,
                   SUM(CASE WHEN acheteur_siret IS NOT NULL THEN 1 ELSE 0 END) avec_acheteur,
                   SUM(CASE WHEN titulaire_siret IS NOT NULL THEN 1 ELSE 0 END) avec_titulaire,
                   SUM(CASE WHEN date_notification IS NOT NULL THEN 1 ELSE 0 END) avec_date,
                   SUM(CASE WHEN lieu_execution_code IS NOT NULL THEN 1 ELSE 0 END) avec_lieu,
                   MIN(date_notification) date_min, MAX(date_notification) date_max
            FROM decp_marches""").fetchone()
        return dict(q)
    finally:
        con.close()
