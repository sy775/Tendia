"""
scripts/decp_explore_triangulation_coverage.py — Sprint DECP 3, exploration préalable.

Mesure la couverture RÉELLE d'un matching CPV + géo des briefs Tendia contre la
DECP (142k), à plusieurs niveaux d'élargissement, pour valider la viabilité de la
triangulation AVANT de coder le module. Lecture seule, 0 €.

Constat structurel (à confirmer ici) : les briefs Tendia n'ont pas de preset DECP
ni de SIRET acheteur ni de montant estimé ; seul ~45 % ont un CPV. La clé de
matching réaliste est donc le CPV (8→5→3) + la géo (dept→région→national).

Usage : python scripts/decp_explore_triangulation_coverage.py
"""
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stockage
from decp.db import connexion

SEUIL = 5


def _digits(s):
    return "".join(c for c in str(s or "") if c.isdigit())


def _depts_brief(perimetre):
    """Extrait les codes département du champ 'Dept 75 | 13 | DIRECTIVE-24'."""
    if not perimetre:
        return []
    depts = []
    for tok in str(perimetre).split("|"):
        tok = tok.strip()
        m = re.search(r"(\d{2,3}[AB]?)", tok.replace("Dept", "").strip())
        if m and "DIRECTIVE" not in tok.upper():
            depts.append(m.group(1))
    return depts


def main():
    marches = stockage.charger("marches") or {}
    con = connexion()

    avec_cpv = [(mid, mk) for mid, mk in marches.items() if mk.get("cpv_principal")]
    print(f"=== Couverture triangulation CPV+géo — {len(marches)} briefs Tendia ===")
    print(f"Briefs avec CPV : {len(avec_cpv)} ({100.0*len(avec_cpv)/len(marches):.0f} %)\n")

    # niveaux : (libellé, longueur CPV, périmètre géo)
    niveaux = [
        ("L1 cpv8+dept", 8, "dept"),
        ("L2 cpv5+dept", 5, "dept"),
        ("L3 cpv5+region", 5, "region"),
        ("L4 cpv3+region", 3, "region"),
        ("L5 cpv5+national", 5, "national"),
        ("L6 cpv3+national", 3, "national"),
    ]
    atteint_a = Counter()      # premier niveau atteignant le seuil
    jamais = 0
    sans_dept = 0

    for mid, mk in avec_cpv:
        cpv = _digits(mk.get("cpv_principal"))
        depts = _depts_brief(mk.get("perimetre_geographique"))
        if not depts:
            sans_dept += 1
        retenu = None
        for lib, L, geo in niveaux:
            if not cpv or len(cpv) < L:
                continue
            pref = cpv[:L]
            if geo == "dept":
                if not depts:
                    continue
                ph = ",".join("?" * len(depts))
                n = con.execute(
                    f"SELECT COUNT(*) FROM decp_marches WHERE substr(cpv_principal,1,{L})=? "
                    f"AND departement IN ({ph})", [pref] + depts).fetchone()[0]
            elif geo == "national":
                n = con.execute(
                    f"SELECT COUNT(*) FROM decp_marches WHERE substr(cpv_principal,1,{L})=?",
                    [pref]).fetchone()[0]
            else:  # region : sauté ici (besoin map dept→region) — approximé par national plus bas
                continue
            if n >= SEUIL:
                retenu = lib
                break
        if retenu:
            atteint_a[retenu] += 1
        else:
            jamais += 1

    con.close()
    total = len(marches)
    couverts = sum(atteint_a.values())
    print("Niveau atteint (premier niveau ≥5 marchés DECP) :")
    for lib, _, _ in niveaux:
        if atteint_a.get(lib):
            print(f"  {lib:18} : {atteint_a[lib]}")
    print(f"\nBriefs CPV couverts (≥5)   : {couverts}/{len(avec_cpv)} "
          f"({100.0*couverts/len(avec_cpv):.0f} % des briefs CPV)")
    print(f"Couverture / tous briefs   : {couverts}/{total} ({100.0*couverts/total:.0f} %)")
    print(f"Briefs CPV sans match ≥5   : {jamais}")
    print(f"Briefs CPV sans dept géo   : {sans_dept}")
    print(f"\nNB : niveau région non simulé ici (map dept→région) ; il s'intercale entre "
          f"dept et national, donc la couverture réelle est ≥ à celle mesurée.")


if __name__ == "__main__":
    main()
