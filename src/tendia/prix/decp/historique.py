"""
decp/historique.py — historique DECP d'une entreprise par SIREN (Sprint DECP-R).

historique_decp(siren) → marchés gagnés depuis 2022 (titulaire seul ou en groupement),
APRÈS dédoublonnage (doublon_de IS NULL ; doublon_possible n'exclut rien), et agrégats :
acheteurs, départements, montants (médiane, maximum), domaines, dates de fin estimées
(date de notification initiale + durée actuelle, à défaut initiale).

Requête indexée : decp_titulaires(siren) → decp_marches(uid). Lecture seule.
"""
import calendar
import sqlite3
import statistics
from collections import Counter
from datetime import date
from typing import Optional

from tendia.core import stockage


def _ajouter_mois(d: str, mois: Optional[int]) -> Optional[str]:
    if not d or not mois or mois <= 0:
        return None
    try:
        y, m, j = int(d[:4]), int(d[5:7]), int(d[8:10])
    except ValueError:
        return None
    m0 = m - 1 + int(mois)
    y, m = y + m0 // 12, m0 % 12 + 1
    return date(y, m, min(j, calendar.monthrange(y, m)[1])).isoformat()


def historique_decp(siren: str, con: Optional[sqlite3.Connection] = None) -> dict:
    siren = "".join(c for c in str(siren or "") if c.isdigit())
    if len(siren) != 9:
        return {"siren": siren, "erreur": "SIREN invalide (9 chiffres attendus)", "marches": []}
    ferme = con is None
    con = con or sqlite3.connect(f"file:{stockage.chemin_db()}?mode=ro", uri=True)
    try:
        rows = con.execute("""
            SELECT m.uid, m.objet, m.acheteur_siret, m.acheteur_nom, m.departement,
                   m.montant_eur, m.montant_initial, m.date_notification, m.duree_actuelle,
                   m.duree_initiale, m.nb_modifications, m.cpv_principal, m.type_groupement,
                   m.nb_titulaires, t.rang, t.role, t.nom, c.domaine, c.famille, m.doublon_possible
            FROM decp_titulaires t
            JOIN decp_marches m ON m.uid = t.decp_id
            LEFT JOIN decp_classification c ON c.decp_id = m.uid
            WHERE t.siren = ? AND m.doublon_de IS NULL
            ORDER BY m.date_notification DESC""", (siren,)).fetchall()
        nom_sirene = con.execute("SELECT denomination, naf, departement FROM sirene_unites_legales WHERE siren=?",
                                 (siren,)).fetchone()
    finally:
        if ferme:
            con.close()
    vus, marches = set(), []
    for r in rows:
        if r[0] in vus:            # même SIREN listé deux fois sur un contrat (2 établissements)
            continue
        vus.add(r[0])
        duree = r[8] or r[9]
        marches.append({
            "uid": r[0], "objet": r[1], "acheteur_siret": r[2], "acheteur_nom": r[3], "departement": r[4],
            "montant_eur": r[5], "montant_initial": r[6], "date_notification": r[7], "duree_mois": duree,
            "nb_modifications": r[10], "cpv": r[11],
            "en_groupement": (r[13] or 1) > 1, "type_groupement": r[12], "rang": r[14], "role": r[15],
            "domaine": r[17], "famille": r[18], "doublon_possible": bool(r[19]),
            "fin_estimee": _ajouter_mois(r[7], duree),
        })
    montants = [m["montant_eur"] for m in marches if m["montant_eur"]]
    auj = date.today().isoformat()
    fins = sorted(m["fin_estimee"] for m in marches if m["fin_estimee"])
    agg = {
        "nb_marches": len(marches),
        "nb_en_groupement": sum(m["en_groupement"] for m in marches),
        "acheteurs": [{"siret": s, "nom": n, "nb": k} for (s, n), k in
                      Counter((m["acheteur_siret"], m["acheteur_nom"]) for m in marches).most_common(10)],
        "departements": dict(Counter(m["departement"] for m in marches if m["departement"]).most_common(10)),
        "montant_median": round(statistics.median(montants)) if montants else None,
        "montant_max": max(montants) if montants else None,
        "montant_total": round(sum(montants)) if montants else None,
        "domaines": dict(Counter(m["domaine"] or f"({m['famille']})" for m in marches).most_common(10)),
        "periode": [marches[-1]["date_notification"], marches[0]["date_notification"]] if marches else None,
        "fins_estimees_a_venir": [f for f in fins if f >= auj][:10],
        "nb_fins_12_mois": sum(1 for f in fins if auj <= f <= _ajouter_mois(auj, 12)),
    }
    return {"siren": siren,
            "nom": (nom_sirene[0] if nom_sirene else None) or (rows[0][16] if rows else None),
            "naf": nom_sirene[1] if nom_sirene else None,
            "departement_siege": nom_sirene[2] if nom_sirene else None,
            "agregats": agg, "marches": marches}
