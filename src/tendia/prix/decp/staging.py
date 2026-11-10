"""
decp/staging.py — base intermédiaire (staging) pour l'ingestion DECP v2 (Sprint DECP-R).

decp.csv (2,6 Go, ~1 ligne par titulaire) est lu EN FLUX et ses lignes brutes sont
copiées dans une base SQLite SÉPARÉE (data/decp_reprise/staging.db), pour :
  - regrouper les lignes par `uid` sans tout garder en mémoire ;
  - analyser les formats par année et la perte de la table v1 sans relire le CSV ;
  - choisir le filtre de version (modification_id / donneesActuelles) après mesure.

Aucune écriture dans data/tendia.db ici.
"""
import csv
import gzip
import json
import os
import sqlite3
import sys
import time

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

DATE_MIN_DEFAUT = "2022-01-01"

DDL = """
CREATE TABLE IF NOT EXISTS lignes (
    ordre             INTEGER PRIMARY KEY,
    source            TEXT NOT NULL,
    uid               TEXT,
    modification_id   INTEGER,
    donnees_actuelles INTEGER,
    date_notification TEXT,
    date_publication  TEXT,
    data              TEXT NOT NULL
);
"""
INDEX = """
CREATE INDEX IF NOT EXISTS idx_l_uid ON lignes(uid, ordre);
CREATE INDEX IF NOT EXISTS idx_l_date ON lignes(date_notification);
"""


def connexion(chemin: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(chemin) or ".", exist_ok=True)
    con = sqlite3.connect(chemin, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=OFF")
    con.executescript(DDL)
    return con


def _mod(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _act(v):
    s = str(v).strip().lower() if v is not None else ""
    return 1 if s in ("true", "1") else (0 if s in ("false", "0") else None)


def _garder(date_notif: str, date_min: str) -> bool:
    """Garde les dates ≥ date_min ET les dates non ISO (pour les mesurer)."""
    d = (date_notif or "")[:10]
    if len(d) == 10 and d[4] == "-" and d[:4].isdigit():
        return d >= date_min
    return True


def charger_csv(chemin_csv: str, chemin_staging: str, date_min: str = DATE_MIN_DEFAUT,
                source: str = "decp_csv", lot: int = 20000) -> dict:
    con = connexion(chemin_staging)
    if con.execute("SELECT COUNT(*) FROM lignes WHERE source=?", (source,)).fetchone()[0]:
        raise RuntimeError(f"staging contient déjà la source {source} — base à recréer")
    t0, lues, gardees, buf = time.time(), 0, 0, []
    with open(chemin_csv, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            lues += 1
            dn = r.get("dateNotification") or ""
            if not _garder(dn, date_min):
                continue
            gardees += 1
            buf.append((source, r.get("uid") or None, _mod(r.get("modification_id")),
                        _act(r.get("donneesActuelles")), dn[:10] or None,
                        (r.get("datePublicationDonnees") or "")[:10] or None,
                        json.dumps(r, ensure_ascii=False, separators=(",", ":"))))
            if len(buf) >= lot:
                con.executemany("INSERT INTO lignes (source,uid,modification_id,donnees_actuelles,"
                                "date_notification,date_publication,data) VALUES (?,?,?,?,?,?,?)", buf)
                con.commit()
                buf.clear()
                if gardees % 200000 < lot:
                    print(f"  [staging] {lues:,} lues, {gardees:,} gardées, {time.time()-t0:.0f}s"
                          .replace(",", " "), flush=True)
    if buf:
        con.executemany("INSERT INTO lignes (source,uid,modification_id,donnees_actuelles,"
                        "date_notification,date_publication,data) VALUES (?,?,?,?,?,?,?)", buf)
        con.commit()
    print("  [staging] index…", flush=True)
    con.executescript(INDEX)
    con.close()
    return {"lues": lues, "gardees": gardees, "secondes": round(time.time() - t0)}


def charger_jsonl_gz(chemin_gz: str, chemin_staging: str, source: str) -> int:
    """Charge un fichier brut de l'API (decp/telecharger.fetch_vers_fichier)."""
    con = connexion(chemin_staging)
    n, buf = 0, []
    for line in gzip.open(chemin_gz, "rt", encoding="utf-8"):
        r = json.loads(line)
        dn = str(r.get("dateNotification") or "")
        buf.append((source, r.get("uid"), _mod(r.get("modification_id")),
                    _act(r.get("donneesActuelles")), dn[:10] or None,
                    str(r.get("datePublicationDonnees") or "")[:10] or None,
                    json.dumps(r, ensure_ascii=False, separators=(",", ":"))))
        n += 1
    con.executemany("INSERT INTO lignes (source,uid,modification_id,donnees_actuelles,"
                    "date_notification,date_publication,data) VALUES (?,?,?,?,?,?,?)", buf)
    con.commit()
    con.executescript(INDEX)
    con.close()
    return n


def iterer_contrats(chemin_staging: str, source: str, filtre_sql: str = "1=1"):
    """Itère (uid, [lignes brutes dans l'ordre source]) pour les lignes retenues par
    `filtre_sql` (ex. version actuelle). Lecture triée par uid via l'index."""
    con = sqlite3.connect(f"file:{chemin_staging}?mode=ro", uri=True)
    cur = con.execute(f"SELECT uid, data FROM lignes WHERE source=? AND uid IS NOT NULL "
                      f"AND ({filtre_sql}) ORDER BY uid, ordre", (source,))
    courant, paquet = None, []
    for uid, data in cur:
        if uid != courant and paquet:
            yield courant, paquet
            paquet = []
        courant = uid
        paquet.append(json.loads(data))
    if paquet:
        yield courant, paquet
    con.close()
