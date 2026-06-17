"""
decp_comparables.py — Voie 3 : comparables DECP pour calibrer le montant d'un marché.

Pour un marché Tendia (CPV + géo + preset), interroge la table SQL `decp_marches`
(≈142k contrats publics exécutés, indexée CPV/dept/montant) et renvoie une estimation
de montant calibrée sur des données RÉELLES + les titulaires historiques.

C'est la « Voie 3 » du modèle montant : là où Voie 1 = montant publié au DCE et Voie 2 =
estimation bottom-up LLM, la Voie 3 ancre la fourchette sur des marchés comparables
réellement attribués → c'est la calibration la plus précise quand elle est disponible.

Élargissement progressif jusqu'à atteindre N_MIN comparables :
  CPV8+dépt → CPV5+dépt → CPV3+dépt → CPV5 national → CPV3 national → preset+dépt → preset national

0 € (pas de LLM). Lecture seule sur decp_marches / decp_classification.
"""
import re
import statistics
from typing import Optional

import stockage

N_MIN = 8           # comparables minimum pour une estimation crédible
N_VISE = 30         # au-delà, inutile d'élargir davantage
RATIO_ABERRANT = 15  # écarte montants > médiane×ratio ou < médiane/ratio (anti-aberrant)
LIMITE_SQL = 4000   # garde-fou sur les requêtes larges

# Tendia preset → preset_principal DECP (decp_classification)
_PRESET_VERS_DECP = {
    "energie_renouvelable": "enr", "enr": "enr",
    "conseil": "conseil_rd", "conseil_rd": "conseil_rd",
    "btp": "btp", "ingenierie": "ingenierie", "it": "it", "formation": "formation",
}


def _dept_de(marche: dict) -> Optional[str]:
    """Extrait le code département du marché Tendia (perimetre_geographique ou CP)."""
    perim = marche.get("perimetre_geographique") or ""
    m = re.search(r"Dept\s+([0-9]{2,3}[AB]?)", perim, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    cp = marche.get("acheteur_code_postal")
    if cp and len(str(cp)) >= 2:
        return str(cp)[:2]
    return None


def _percentiles(vals: list) -> dict:
    vals = sorted(v for v in vals if isinstance(v, (int, float)) and v > 0)
    n = len(vals)
    if not n:
        return {"n": 0}

    def pct(p):
        if n == 1:
            return vals[0]
        k = (n - 1) * p
        f = int(k)
        c = min(f + 1, n - 1)
        return vals[f] + (vals[c] - vals[f]) * (k - f)

    return {"n": n, "min": vals[0], "max": vals[-1],
            "mediane": round(pct(0.5)), "p25": round(pct(0.25)), "p75": round(pct(0.75))}


def _filtrer_aberrants(rows: list) -> list:
    """rows = [(montant, titulaire, objet, date)]. Écarte les montants aberrants."""
    montants = [r[0] for r in rows if isinstance(r[0], (int, float)) and r[0] > 0]
    if len(montants) < 4:
        return [r for r in rows if isinstance(r[0], (int, float)) and r[0] > 0]
    med = statistics.median(montants)
    lo, hi = med / RATIO_ABERRANT, med * RATIO_ABERRANT
    return [r for r in rows if isinstance(r[0], (int, float)) and lo <= r[0] <= hi]


def _strategies(marche: dict, preset_decp: Optional[str]):
    """Liste ordonnée (libellé, where_sql, params, join_classif) du plus précis au plus large."""
    cpv = str(marche.get("cpv_principal") or "")
    dept = _dept_de(marche)
    S = []
    if len(cpv) >= 8 and dept:
        S.append(("CPV exact + département", "m.cpv_principal = ? AND m.departement = ?", [cpv, dept], False))
    if len(cpv) >= 5:
        if dept:
            S.append(("CPV 5 + département", "m.cpv_principal LIKE ? AND m.departement = ?", [cpv[:5] + "%", dept], False))
        S.append(("CPV 5 (national)", "m.cpv_principal LIKE ?", [cpv[:5] + "%"], False))
    if len(cpv) >= 3:
        if dept:
            S.append(("CPV 3 + département", "m.cpv_principal LIKE ? AND m.departement = ?", [cpv[:3] + "%", dept], False))
        S.append(("CPV 3 (national)", "m.cpv_principal LIKE ?", [cpv[:3] + "%"], False))
    if preset_decp:
        if dept:
            S.append(("Secteur + département", "c.preset_principal = ? AND m.departement = ?", [preset_decp, dept], True))
        S.append(("Secteur (national)", "c.preset_principal = ?", [preset_decp], True))
    return S


def comparables_pour_marche(marche: dict, preset: Optional[str] = None) -> dict:
    """Renvoie l'estimation Voie 3 + l'échantillon de comparables DECP, ou {disponible: False}."""
    conn = stockage._conn()
    preset_decp = _PRESET_VERS_DECP.get((preset or "").lower())

    meilleur = None
    for libelle, where, params, join_classif in _strategies(marche, preset_decp):
        # NB : decp_marches n'a pas de colonne nom titulaire (titulaires_json = SIRET).
        # On remonte le SIRET ; l'enrichissement nom (SIRENE) est un chantier séparé.
        base = ("SELECT m.montant_eur, m.titulaire_siret, m.objet, m.date_notification "
                "FROM decp_marches m ")
        if join_classif:
            base += "JOIN decp_classification c ON c.decp_id = m.id "
        sql = base + f"WHERE {where} AND m.montant_eur > 0 LIMIT {LIMITE_SQL}"
        try:
            rows = conn.execute(sql, params).fetchall()
        except Exception:
            continue
        rows = _filtrer_aberrants([tuple(r) for r in rows])
        if len(rows) >= N_MIN:
            meilleur = (libelle, rows)
            break
        # garde la plus large tentative comme repli si aucune n'atteint N_MIN
        if meilleur is None or len(rows) > len(meilleur[1]):
            meilleur = (libelle, rows)

    if not meilleur or len(meilleur[1]) < 3:
        return {"disponible": False, "n": len(meilleur[1]) if meilleur else 0}

    libelle, rows = meilleur
    stats = _percentiles([r[0] for r in rows])

    # Titulaires fréquents (intel concurrentielle) — par SIRET (nom via SIRENE ultérieurement)
    from collections import Counter
    cnt = Counter()
    mont_par_tit = {}
    for mont, tit, _, _ in rows:
        if tit:
            cnt[tit] += 1
            mont_par_tit.setdefault(tit, []).append(mont)
    titulaires = [{"siret": t, "n": c, "montant_median": round(statistics.median(mont_par_tit[t]))}
                  for t, c in cnt.most_common(5) if c >= 2]

    # Échantillon (les plus proches de la médiane, pour illustrer)
    med = stats.get("mediane", 0)
    ech = sorted(rows, key=lambda r: abs(r[0] - med))[:6]
    echantillon = [{"objet": (o or "")[:90], "montant": mt, "titulaire": ti,
                    "annee": (dt or "")[:4]} for mt, ti, o, dt in ech]

    return {
        "disponible": stats["n"] >= N_MIN,
        "fiabilite": "haute" if stats["n"] >= N_VISE else ("moyenne" if stats["n"] >= N_MIN else "faible"),
        "strategie": libelle,
        "n": stats["n"],
        "montant_median": stats["mediane"],
        "montant_p25": stats["p25"],
        "montant_p75": stats["p75"],
        "montant_min": stats["min"],
        "montant_max": stats["max"],
        "titulaires_frequents": titulaires,
        "echantillon": echantillon,
    }


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ma = stockage.charger("marches") or {}
    classifs = stockage.charger("classifications_ia") or {}
    # test sur quelques marchés avec CPV
    testes = 0
    for mid, mk in ma.items():
        if not mk.get("cpv_principal"):
            continue
        cl = classifs.get(mid) or {}
        dom = (cl.get("domaines_metier") or [{}])
        preset = None  # le test ne mappe pas finement; CPV suffit
        res = comparables_pour_marche(mk, preset)
        if res.get("disponible"):
            print(f"{mid} (CPV {mk['cpv_principal']}, {mk.get('perimetre_geographique','')[:20]}) "
                  f"→ {res['strategie']} | n={res['n']} | "
                  f"médiane {res['montant_median']:,} € [{res['montant_p25']:,}–{res['montant_p75']:,}]")
            testes += 1
        if testes >= 8:
            break
