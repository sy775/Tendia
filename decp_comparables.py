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
BANDE_MONTANT = (0.5, 2.0)  # bande [×0,5 ; ×2] autour du montant d'ancrage (pairs même taille)
SEUIL_BOAMP_EUR = 90_000    # seuil légal de publicité obligatoire au BOAMP (HT)

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


def _cle_marche(r) -> tuple:
    """Clé d'un marché LOGIQUE (r = montant, titulaire, objet, date). Un accord-cadre
    multi-attributaires apparaît en N lignes (une par titulaire) ne différant que par le
    titulaire → cette clé les regroupe (montant + objet + date)."""
    return (r[0], (r[2] or "")[:80], r[3])


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


def comparables_pour_marche(marche: dict, preset: Optional[str] = None,
                            exclure_id: Optional[str] = None,
                            montant_ancre: Optional[float] = None) -> dict:
    """Renvoie l'estimation Voie 3 + l'échantillon de comparables DECP, ou {disponible: False}.

    exclure_id : écarte ce marché DECP des comparables (backtest = ne pas se prédire soi-même).
    montant_ancre : si fourni, restreint les comparables à une BANDE de montant
        [×0,5 ; ×2] autour de cette valeur → pairs de même TAILLE (et plus seulement même
        secteur). Le backtest a montré que CPV+géo+objet ne prédisent pas le montant
        (~70% d'erreur) ; on assume donc de faire confiance à l'estimation pour cibler la
        taille, au prix d'une légère circularité (acceptée), afin d'obtenir un vrai jeu de
        pairs (intel concurrentielle, benchmark de coût). Ancre = montant officiel si publié,
        sinon estimation Voie 2.
    """
    conn = stockage._conn()
    preset_decp = _PRESET_VERS_DECP.get((preset or "").lower())
    bande_sql, bande_p = "", []
    if montant_ancre and montant_ancre > 0:
        bande_sql = " AND m.montant_eur BETWEEN ? AND ?"
        bande_p = [montant_ancre * BANDE_MONTANT[0], montant_ancre * BANDE_MONTANT[1]]

    meilleur = None
    for libelle, where, params, join_classif in _strategies(marche, preset_decp):
        # NB : decp_marches n'a pas de colonne nom titulaire (titulaires_json = SIRET).
        # On remonte le SIRET ; l'enrichissement nom (SIRENE) est un chantier séparé.
        base = ("SELECT m.montant_eur, m.titulaire_siret, m.objet, m.date_notification "
                "FROM decp_marches m ")
        if join_classif:
            base += "JOIN decp_classification c ON c.decp_id = m.id "
        excl = " AND m.id != ?" if exclure_id else ""
        p = list(params) + ([exclure_id] if exclure_id else []) + bande_p
        sql = base + f"WHERE {where} AND m.montant_eur > 0{excl}{bande_sql} LIMIT {LIMITE_SQL}"
        try:
            rows = conn.execute(sql, p).fetchall()
        except Exception:
            continue
        rows_raw = _filtrer_aberrants([tuple(r) for r in rows])
        # Dédup par marché LOGIQUE (un accord-cadre multi-attributaires = N lignes
        # identiques sauf le titulaire) → ne pas sur-pondérer le compte ni les stats.
        uniq = {}
        for r in rows_raw:
            uniq.setdefault(_cle_marche(r), r)
        rows_u = list(uniq.values())
        if len(rows_u) >= N_MIN:
            meilleur = (libelle, rows_u, rows_raw)
            break
        # garde la plus large tentative comme repli si aucune n'atteint N_MIN
        if meilleur is None or len(rows_u) > len(meilleur[1]):
            meilleur = (libelle, rows_u, rows_raw)

    if not meilleur or len(meilleur[1]) < 3:
        return {"disponible": False, "n": len(meilleur[1]) if meilleur else 0}

    libelle, rows, rows_raw = meilleur
    stats = _percentiles([r[0] for r in rows])

    # Titulaires fréquents (intel) : nb de marchés DISTINCTS gagnés par SIRET (un
    # groupement ne compte pas N fois le même marché). Sur les lignes brutes.
    from collections import defaultdict
    tit_marches = defaultdict(set)
    tit_montants = defaultdict(list)
    for mont, tit, objet, dt in rows_raw:
        if tit:
            tit_marches[tit].add(_cle_marche((mont, tit, objet, dt)))
            tit_montants[tit].append(mont)
    titulaires = sorted(
        ({"siret": t, "n": len(m), "montant_median": round(statistics.median(tit_montants[t]))}
         for t, m in tit_marches.items() if len(m) >= 2),
        key=lambda x: x["n"], reverse=True)[:5]

    # Échantillon : marchés logiques DISTINCTS, les plus proches de la médiane.
    # html.unescape : les objets DECP contiennent des entités (&#8211;, &amp;…).
    import html as _html
    med = stats.get("mediane", 0)
    ech = sorted(rows, key=lambda r: abs(r[0] - med))[:6]
    echantillon = [{"objet": _html.unescape(o or "")[:90], "montant": mt, "titulaire": ti,
                    "annee": (dt or "")[:4]} for mt, ti, o, dt in ech]

    return {
        "disponible": stats["n"] >= N_MIN,
        "fiabilite": "haute" if stats["n"] >= N_VISE else ("moyenne" if stats["n"] >= N_MIN else "faible"),
        "strategie": libelle,
        "ancre_montant": bool(montant_ancre),
        "n": stats["n"],
        "montant_median": stats["mediane"],
        "montant_p25": stats["p25"],
        "montant_p75": stats["p75"],
        "montant_min": stats["min"],
        "montant_max": stats["max"],
        "titulaires_frequents": titulaires,
        "echantillon": echantillon,
    }


def lister_decp(q=None, preset=None, dept=None, montant_min=None, montant_max=None,
                page=1, par_page=50) -> dict:
    """Liste paginée des marchés DECP (filtres : recherche, preset, dépt, montant)."""
    conn = stockage._conn()
    where = ["m.montant_eur > 0"]
    params = []
    join = ""
    if preset:
        pdecp = _PRESET_VERS_DECP.get(str(preset).lower(), preset)
        join = "JOIN decp_classification c ON c.decp_id = m.id "
        where.append("c.preset_principal = ?")
        params.append(pdecp)
    if dept:
        where.append("m.departement = ?")
        params.append(str(dept).upper())
    if montant_min:
        where.append("m.montant_eur >= ?")
        params.append(float(montant_min))
    if montant_max:
        where.append("m.montant_eur <= ?")
        params.append(float(montant_max))
    if q:
        where.append("(m.objet LIKE ? OR m.acheteur_nom LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    wsql = " AND ".join(where)
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM decp_marches m {join} WHERE {wsql}",
                             params).fetchone()[0]
    except Exception:
        return {"items": [], "total": 0, "page": 1, "pages": 0, "par_page": par_page}
    page = max(1, int(page))
    off = (page - 1) * par_page
    sel = ("m.id, m.objet, m.acheteur_nom, m.titulaire_siret, m.montant_eur, "
           "m.date_notification, m.cpv_principal, m.departement, m.duree_mois")
    rows = conn.execute(
        f"SELECT {sel} FROM decp_marches m {join} WHERE {wsql} "
        f"ORDER BY m.date_notification DESC LIMIT ? OFFSET ?",
        params + [par_page, off]).fetchall()
    cles = ["id", "objet", "acheteur_nom", "titulaire_siret", "montant_eur",
            "date_notification", "cpv_principal", "departement", "duree_mois"]
    import html as _html
    lignes = []
    for r in rows:
        d = dict(zip(cles, r))
        d["objet"] = _html.unescape(d.get("objet") or "")
        d["acheteur_nom"] = _html.unescape(d.get("acheteur_nom") or "")
        lignes.append(d)
    # clé 'lignes' (pas 'items') : en Jinja `res.items` résout la méthode dict.items().
    return {"lignes": lignes, "total": total, "page": page, "par_page": par_page,
            "pages": (total + par_page - 1) // par_page}


def get_decp(id_decp: str) -> Optional[dict]:
    """Charge un marché DECP complet (decp_marches + sa classification preset)."""
    conn = stockage._conn()
    cols = [c[1] for c in conn.execute("PRAGMA table_info(decp_marches)").fetchall()]
    row = conn.execute("SELECT * FROM decp_marches WHERE id = ?", [id_decp]).fetchone()
    if not row:
        return None
    d = dict(zip(cols, tuple(row)))
    cl = conn.execute("SELECT preset_principal FROM decp_classification WHERE decp_id = ?",
                      [id_decp]).fetchone()
    d["preset"] = cl[0] if cl else None
    return d


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
