"""
tests/test_decp_db.py — Lancement : python tests/test_decp_db.py
Utilise une base SQLite temporaire (jamais data/tendia.db).
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decp import db as decp_db
from decp.parser import parser_marche

ok = ko = 0


def check(nom, cond):
    global ok, ko
    if cond:
        ok += 1; print(f"  ✓ {nom}")
    else:
        ko += 1; print(f"  ✗ ÉCHEC {nom}")


tmp = tempfile.mktemp(suffix=".db")
try:
    decp_db.init_schema(tmp)
    con = decp_db.connexion(tmp)
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    print("init_schema")
    check("table decp_marches", "decp_marches" in tables)
    check("table marche_attribution_link", "marche_attribution_link" in tables)
    check("table decp_classification", "decp_classification" in tables)

    print("inserer_marches / compter_marches")
    marches = [
        parser_marche({"id": "D1", "codeCPV": "45211000",
                       "acheteur_id": "13000548100010", "montant": "100000",
                       "dateNotification": "2026-05-01", "lieuExecution_code": "75056",
                       "titulaire_id": "33071536800297"}),
        parser_marche({"id": "D2", "codeCPV": "72000000", "montant": "0",
                       "dateNotification": "2026-05-02"}),
    ]
    n = decp_db.inserer_marches(marches, tmp)
    check("2 marchés insérés", n == 2)
    stats = decp_db.compter_marches(tmp)
    check("total = 2", stats["total"] == 2)
    check("avec_montant = 1", stats["avec_montant"] == 1)
    check("avec_cpv = 2", stats["avec_cpv"] == 2)
    check("avec_acheteur = 1", stats["avec_acheteur"] == 1)

    print("idempotence (INSERT OR REPLACE)")
    decp_db.inserer_marches(marches, tmp)
    check("toujours 2 après ré-insertion", decp_db.compter_marches(tmp)["total"] == 2)

    print("inserer_lien + unicité")
    lien = {"marche_tendia_id": "BOAMP-26-1", "decp_id": "D1", "score_total": 0.9,
            "score_cpv": 1.0, "score_acheteur": 1.0, "score_periode": 1.0,
            "score_montant": None, "created_at": "2026-06-16T00:00:00Z"}
    check("1er insert OK", decp_db.inserer_lien(lien, tmp) is True)
    check("doublon ignoré (UNIQUE)", decp_db.inserer_lien(lien, tmp) is False)
    con = decp_db.connexion(tmp)
    nb_liens = con.execute("SELECT COUNT(*) FROM marche_attribution_link").fetchone()[0]
    con.close()
    check("1 seul lien en base", nb_liens == 1)

    print("parse_warnings sérialisé JSON")
    decp_db.inserer_marches([parser_marche({"id": "D3", "montant": "-5",
                                            "dateNotification": "2026-05-03"})], tmp)
    con = decp_db.connexion(tmp)
    pw = con.execute("SELECT parse_warnings FROM decp_marches WHERE id='D3'").fetchone()[0]
    con.close()
    check("warnings stockés en JSON texte", pw and "montant_negatif" in pw)

finally:
    try:
        os.remove(tmp)
    except OSError:
        pass

print(f"\n=== {ok} OK / {ko} KO ===")
sys.exit(1 if ko else 0)
