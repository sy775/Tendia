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

# None = base Tendia résolue par stockage.chemin_db() (chemin absolu, indépendant du cwd).
# Les tests passent un chemin explicite (base temporaire).
DB_PATH_DEFAUT = None
BUSY_TIMEOUT_MS = 30_000


def _resoudre(db_path) -> str:
    if db_path is None:
        from tendia.core import stockage
        return stockage.chemin_db()
    return str(db_path)

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
-- Sprint DECP-R : seuls les liens confirmés par l'objet sont exploitables (UI, compagnon).
-- Les liens 'auto_a_verifier' (scorer_match sans comparaison d'objet, ~1 sur 2 faux) restent
-- en base mais ne doivent pas être lus ailleurs que par cette vue.
CREATE VIEW IF NOT EXISTS v_attributions_exploitables AS
    SELECT * FROM marche_attribution_link WHERE statut = 'auto_confirme_objet';

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
    con = sqlite3.connect(_resoudre(db_path), timeout=BUSY_TIMEOUT_MS / 1000)
    con.row_factory = sqlite3.Row
    con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_schema(db_path=DB_PATH_DEFAUT) -> None:
    Path(_resoudre(db_path)).parent.mkdir(parents=True, exist_ok=True)
    con = connexion(db_path)
    try:
        con.executescript(DDL)
        con.commit()
    finally:
        con.close()


def inserer_marches(marches: list, db_path=DB_PATH_DEFAUT,
                    source_fichier: str = "decp_consolidee_api") -> int:
    """Batch UPSERT sur l'id (INSERT … ON CONFLICT DO UPDATE), limité aux colonnes
    venant de la source (_COLS) : les colonnes dérivées ajoutées ensuite (doublon_de…)
    ne sont jamais écrasées. parse_warnings sérialisé JSON.
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
        maj = ",".join(f"{c}=excluded.{c}" for c in _COLS if c != "id")
        con.executemany(
            f"INSERT INTO decp_marches ({','.join(_COLS)}) VALUES ({ph}) "
            f"ON CONFLICT(id) DO UPDATE SET {maj}",
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


# ===========================================================================
# Schéma v2 — clé `uid` (Sprint DECP-R)
# ===========================================================================
# `id` DECP = numéro interne à l'acheteur (non unique) → la v1 (PK id) écrasait des
# contrats et fusionnait les titulaires entre acheteurs. La v1 est CONSERVÉE sous le
# nom decp_marches_v1_id (et decp_classification_v1_id), jamais supprimée.

DDL_V2 = """
CREATE TABLE IF NOT EXISTS decp_marches (
    uid             TEXT PRIMARY KEY,
    id              TEXT,
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
    parse_warnings  TEXT,
    nature          TEXT,
    type_marche     TEXT,
    lieu_execution_type_code TEXT,
    titulaire_nom   TEXT,
    titulaire_activite_code TEXT,
    titulaire_categorie TEXT,
    titulaire_type_identifiant TEXT,
    nb_titulaires   INTEGER,
    type_groupement TEXT,
    sous_traitance_declaree INTEGER,
    offres_recues   INTEGER,
    id_accord_cadre TEXT,
    source_dataset  TEXT,
    date_publication_donnees TEXT,
    montant_rationalise REAL,
    montant_anomalie TEXT,
    modification_id INTEGER,            -- version actuelle retenue
    montant_initial REAL,               -- version initiale (modification_id = 0)
    montant_actuel  REAL,               -- version actuelle (= montant_eur)
    duree_initiale  INTEGER,
    duree_actuelle  INTEGER,            -- (= duree_mois)
    nb_modifications INTEGER,
    -- ⚠ Champs PEU FIABLES avant 2024 (formats DECP antérieurs à l'arrêté 2024) :
    --   type_groupement (renseigné ~20 % en 2022, ~31 % en 2023), offres_recues
    --   (~17 % / ~25 %), sous_traitance_declaree (~19 % / ~29 %). Contrats sans titulaire :
    --   ~13,5 % en 2024. Mesures : data/decp_reprise/arret1.json.
    -- date_notification = date de notification du contrat INITIAL (jamais celle d'une modification).
    -- colonnes DÉRIVÉES (jamais écrasées par l'UPSERT source)
    doublon_de      TEXT,
    doublon_regle   TEXT,
    -- doublon POSSIBLE (groupes ambigus, validé Sprint DECP-R) : simple indicateur, SANS
    -- effet sur decp_comparables ni historique_decp (seul doublon_de exclut).
    doublon_possible INTEGER,
    doublon_groupe  TEXT
);
CREATE INDEX IF NOT EXISTS idx_dm2_id ON decp_marches(acheteur_siret, id);
CREATE INDEX IF NOT EXISTS idx_dm2_cpv ON decp_marches(cpv_principal);
CREATE INDEX IF NOT EXISTS idx_dm2_acheteur ON decp_marches(acheteur_siret);
CREATE INDEX IF NOT EXISTS idx_dm2_titulaire ON decp_marches(titulaire_siret);
CREATE INDEX IF NOT EXISTS idx_dm2_date ON decp_marches(date_notification);
CREATE INDEX IF NOT EXISTS idx_dm2_dept ON decp_marches(departement);
CREATE INDEX IF NOT EXISTS idx_dm2_montant ON decp_marches(montant_eur);
CREATE INDEX IF NOT EXISTS idx_dm2_doublon ON decp_marches(doublon_de);

CREATE TABLE IF NOT EXISTS decp_titulaires (
    decp_id         TEXT NOT NULL,          -- = decp_marches.uid
    rang            INTEGER NOT NULL,
    siret           TEXT,
    siren           TEXT,
    siret_brut      TEXT,
    type_identifiant TEXT,
    nom             TEXT,
    activite_code   TEXT,
    categorie       TEXT,
    role            TEXT,
    valide          INTEGER NOT NULL DEFAULT 0,
    motif_rejet     TEXT,
    PRIMARY KEY (decp_id, rang)
);
CREATE INDEX IF NOT EXISTS idx_dt_siren ON decp_titulaires(siren);
CREATE INDEX IF NOT EXISTS idx_dt_siret ON decp_titulaires(siret);

CREATE TABLE IF NOT EXISTS decp_classification (
    decp_id         TEXT PRIMARY KEY,       -- = decp_marches.uid
    preset_principal TEXT,                  -- = famille (compat decp_comparables / UI)
    preset_secondaire TEXT,
    source          TEXT NOT NULL,
    confiance       REAL,
    classified_at   TEXT NOT NULL,
    domaine         TEXT,                   -- code fin classifications_ia (btp_*, …)
    famille         TEXT,                   -- btp, ingenierie, it, conseil_rd, formation, enr, hors_perimetre
    modele          TEXT,
    prompt_version  TEXT
);
CREATE INDEX IF NOT EXISTS idx_dc2_preset ON decp_classification(preset_principal);
CREATE INDEX IF NOT EXISTS idx_dc2_domaine ON decp_classification(domaine);
"""


def _tables(con) -> set:
    return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def migrer_v2(db_path=DB_PATH_DEFAUT) -> dict:
    """Renomme les tables v1 (conservées) et crée le schéma v2. Idempotent."""
    con = connexion(db_path)
    try:
        con.execute("PRAGMA foreign_keys=OFF")
        t = _tables(con)
        fait = []
        cols = {r[1] for r in con.execute("PRAGMA table_info(decp_marches)")} if "decp_marches" in t else set()
        if "decp_marches" in t and "uid" not in cols:
            if "decp_marches_v1_id" in t:
                raise RuntimeError("decp_marches_v1_id existe déjà alors que decp_marches est en v1")
            con.execute("ALTER TABLE decp_classification RENAME TO decp_classification_v1_id")
            con.execute("ALTER TABLE decp_marches RENAME TO decp_marches_v1_id")
            fait.append("v1 renommées")
        con.executescript(DDL_V2)
        cols = {r[1] for r in con.execute("PRAGMA table_info(decp_marches)")}
        for col, typ in (("doublon_possible", "INTEGER"), ("doublon_groupe", "TEXT")):
            if col not in cols:   # base migrée avant l'ajout de ces colonnes dérivées
                con.execute(f"ALTER TABLE decp_marches ADD COLUMN {col} {typ}")
                fait.append(f"colonne {col} ajoutée")
        con.commit()
        fait.append("schéma v2 créé")
        return {"actions": fait, "tables": sorted(_tables(con))}
    finally:
        con.close()


def upsert_contrats(con, contrats: list) -> int:
    """UPSERT decp_marches v2 limité aux colonnes source (parser_v2.COLS_MARCHE)."""
    from decp.parser_v2 import COLS_MARCHE
    if not contrats:
        return 0
    from decp.parser_v2 import COLS_INITIALES
    maj = ",".join((f"{c}=COALESCE(excluded.{c}, decp_marches.{c})" if c in COLS_INITIALES
                    else f"{c}=excluded.{c}") for c in COLS_MARCHE if c != "uid")
    con.executemany(
        f"INSERT INTO decp_marches ({','.join(COLS_MARCHE)}) VALUES ({','.join('?' * len(COLS_MARCHE))}) "
        f"ON CONFLICT(uid) DO UPDATE SET {maj}",
        [tuple(c.get(k) for k in COLS_MARCHE) for c in contrats])
    return len(contrats)


def upsert_titulaires(con, titulaires: list) -> int:
    """UPSERT decp_titulaires sur (decp_id, rang). Les rangs au-delà du nombre actuel de
    titulaires d'un contrat (titulaire retiré à la source) sont supprimés : ce sont des
    données source, pas des données dérivées."""
    from decp.parser_v2 import COLS_TITULAIRE
    if not titulaires:
        return 0
    maj = ",".join(f"{c}=excluded.{c}" for c in COLS_TITULAIRE if c not in ("decp_id", "rang"))
    con.executemany(
        f"INSERT INTO decp_titulaires ({','.join(COLS_TITULAIRE)}) VALUES ({','.join('?' * len(COLS_TITULAIRE))}) "
        f"ON CONFLICT(decp_id, rang) DO UPDATE SET {maj}",
        [tuple(t.get(k) for k in COLS_TITULAIRE) for t in titulaires])
    nmax = {}
    for t in titulaires:
        nmax[t["decp_id"]] = max(nmax.get(t["decp_id"], 0), t["rang"])
    con.executemany("DELETE FROM decp_titulaires WHERE decp_id=? AND rang>?", list(nmax.items()))
    return len(titulaires)
