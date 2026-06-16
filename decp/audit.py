"""
decp/audit.py — audit qualité chiffré de la base DECP (Étape 4 du sprint).

Produit un bloc texte (Markdown) résumant couverture, distributions et anomalies,
intégré dans RAPPORT_DECP_SPRINT1.md.
"""
import time
from collections import Counter

from decp.db import connexion, DB_PATH_DEFAUT
from decp.parser import valider_siret


def _pct(n, d):
    return f"{100.0 * n / d:.1f} %" if d else "—"


def auditer(db_path=DB_PATH_DEFAUT) -> str:
    con = connexion(db_path)
    L = []
    w = L.append
    try:
        r = con.execute("""
            SELECT COUNT(*) total,
                   SUM(CASE WHEN montant_eur > 0 THEN 1 ELSE 0 END) m_pos,
                   SUM(CASE WHEN cpv_principal IS NOT NULL THEN 1 ELSE 0 END) c_cpv,
                   SUM(CASE WHEN acheteur_siret IS NOT NULL THEN 1 ELSE 0 END) c_ach,
                   SUM(CASE WHEN titulaire_siret IS NOT NULL THEN 1 ELSE 0 END) c_tit,
                   SUM(CASE WHEN date_notification IS NOT NULL THEN 1 ELSE 0 END) c_date,
                   SUM(CASE WHEN lieu_execution_code IS NOT NULL THEN 1 ELSE 0 END) c_lieu,
                   SUM(CASE WHEN montant_eur = 0 THEN 1 ELSE 0 END) m_zero,
                   SUM(CASE WHEN montant_eur > 100000000 THEN 1 ELSE 0 END) m_gros,
                   MIN(date_notification) dmin, MAX(date_notification) dmax
            FROM decp_marches""").fetchone()
        n = r["total"] or 0
        if not n:
            return "_(base DECP vide — lancer l'ingestion)_\n"

        w("```")
        w("=== AUDIT DECP — Sprint 1 ===")
        w(f"Période ingérée : {r['dmin']} à {r['dmax']}")
        w(f"Total marchés DECP : {n:,}".replace(",", " "))
        w("")
        w("Couverture champs :")
        w(f"- avec montant > 0     : {_pct(r['m_pos'], n)}")
        w(f"- avec CPV principal   : {_pct(r['c_cpv'], n)}")
        w(f"- avec acheteur SIRET  : {_pct(r['c_ach'], n)}")
        w(f"- avec titulaire SIRET : {_pct(r['c_tit'], n)}")
        w(f"- avec date notif      : {_pct(r['c_date'], n)}")
        w(f"- avec lieu exécution  : {_pct(r['c_lieu'], n)}")
        w("")

        # Distribution CPV (2 chiffres)
        cpv2 = Counter()
        for (c,) in con.execute(
                "SELECT cpv_principal FROM decp_marches WHERE cpv_principal IS NOT NULL"):
            cpv2[str(c)[:2]] += 1
        libelle = {"45": "BTP", "71": "Ingénierie", "72": "IT", "73": "Conseil R&D",
                   "80": "Formation", "09": "EnR", "33": "Médical", "79": "Services"}
        w("Distribution CPV (top 20, préfixe 2 chiffres) :")
        for code, cnt in cpv2.most_common(20):
            lab = libelle.get(code, "")
            w(f"{code} {lab:14}: {cnt:>7,} ({_pct(cnt, n)})".replace(",", " "))
        w("")

        # Distribution montants
        tr = {"0-50k": 0, "50k-500k": 0, "500k-5M": 0, "5M-50M": 0, ">50M": 0}
        for (m,) in con.execute(
                "SELECT montant_eur FROM decp_marches WHERE montant_eur > 0"):
            if m < 50_000:
                tr["0-50k"] += 1
            elif m < 500_000:
                tr["50k-500k"] += 1
            elif m < 5_000_000:
                tr["500k-5M"] += 1
            elif m < 50_000_000:
                tr["5M-50M"] += 1
            else:
                tr[">50M"] += 1
        mp = r["m_pos"] or 1
        w("Distribution montants :")
        for k, v in tr.items():
            w(f"- {k+'€':<14}: {_pct(v, mp)}")
        w("")

        # Anomalies
        siret_invalides = 0
        for (s,) in con.execute(
                "SELECT acheteur_siret FROM decp_marches WHERE acheteur_siret IS NOT NULL"):
            if not valider_siret(s):
                siret_invalides += 1
        cpv_mal = con.execute(
            "SELECT COUNT(*) FROM decp_marches WHERE cpv_principal IS NOT NULL "
            "AND LENGTH(cpv_principal) <> 8").fetchone()[0]
        dates_ab = con.execute(
            "SELECT COUNT(*) FROM decp_marches WHERE date_notification IS NOT NULL "
            "AND (date_notification < '2000-01-01' OR date_notification > '2100-01-01')"
        ).fetchone()[0]
        avec_warn = con.execute(
            "SELECT COUNT(*) FROM decp_marches WHERE parse_warnings IS NOT NULL").fetchone()[0]
        w("Anomalies détectées :")
        w(f"- SIRETs acheteur invalides Luhn : {siret_invalides:,} ({_pct(siret_invalides, r['c_ach'] or 1)})".replace(",", " "))
        w(f"- Montants à 0                    : {r['m_zero']:,}".replace(",", " "))
        w(f"- Montants > 100M€               : {r['m_gros']:,}".replace(",", " "))
        w(f"- CPV mal formés (≠ 8 chiffres)   : {cpv_mal:,}".replace(",", " "))
        w(f"- Dates aberrantes                : {dates_ab:,}".replace(",", " "))
        w(f"- Marchés avec parse_warnings     : {avec_warn:,}".replace(",", " "))
        w("")

        # Volumétrie par mois
        w("Volumétrie par mois :")
        for mois, cnt in con.execute(
                "SELECT substr(date_notification,1,7) m, COUNT(*) FROM decp_marches "
                "WHERE date_notification IS NOT NULL GROUP BY m ORDER BY m"):
            w(f"{mois} : {cnt:>7,}".replace(",", " "))
        w("")

        # Taille DB + perf requête
        try:
            from pathlib import Path
            taille = Path(db_path).stat().st_size / 1e6
        except OSError:
            taille = 0
        t0 = time.time()
        con.execute("SELECT COUNT(*) FROM decp_marches WHERE cpv_principal LIKE '45%' "
                    "AND date_notification > '2025-06-01'").fetchone()
        dt = (time.time() - t0) * 1000
        w(f"Taille DB SQLite : {taille:.0f} Mo (base Tendia complète)")
        w(f"Temps requête (filtre CPV + date) : {dt:.0f} ms")
        w("```")
        return "\n".join(L) + "\n"
    finally:
        con.close()
