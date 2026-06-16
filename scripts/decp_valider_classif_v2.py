"""
scripts/decp_valider_classif_v2.py — raffinement v2, Étape 4 (validation ciblée).

Tirage stratifié de 30 marchés (5 par preset principal : btp, it, ingenierie,
conseil_rd, formation, enr) avec --focus-fixes : sur-représente les marchés touchés
par les correctifs v2 pour valider les fixes plutôt que re-tester tout le pipeline.

Garanties focus (si le stock le permet) :
  - ≥ 2 marchés CPV 45* passés par la règle MOE (source cpv_moe_override)
  - ≥ 2 marchés issus de la re-classification Pattern 4 (log reclassif_pattern4_*.csv)
  - ≥ 4 marchés CPV 79xxx (frontière conseil_rd ↔ ingenierie)
  - mix ~60 % CPV / 40 % LLM

Modes : --dump (CSV + affichage) ou interactif (o/n/?). Déterministe (ORDER BY id).

Usage : python scripts/decp_valider_classif_v2.py --n 30 --focus-fixes [--dump]
"""
import argparse
import csv
import glob
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decp.db import connexion

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
PRESETS = ["btp", "it", "ingenierie", "conseil_rd", "formation", "enr"]
SEL = ("SELECT m.id, m.objet, m.cpv_principal, m.acheteur_nom, c.preset_principal, "
       "c.source, c.confiance FROM decp_classification c "
       "JOIN decp_marches m ON m.id = c.decp_id ")


def _ids_pattern4():
    """IDs reclassés par le dernier run Pattern 4 (pour les sur-représenter)."""
    logs = sorted(glob.glob(os.path.join(DATA, "reclassif_pattern4_*.csv")))
    if not logs:
        return set()
    with open(logs[-1], encoding="utf-8") as f:
        return {r["id"] for r in csv.DictReader(f)}


def _echantillon(con, n=30, focus=True):
    par_preset = n // len(PRESETS)              # 5
    ids_p4 = _ids_pattern4() if focus else set()

    # pools par preset, déterministes
    pools = {}
    for p in PRESETS:
        pools[p] = [dict(r) for r in con.execute(SEL + "WHERE c.preset_principal=? ORDER BY m.id", (p,)).fetchall()]

    choisis, vus = [], set()

    def prendre(row):
        if row and row["id"] not in vus:
            choisis.append(row); vus.add(row["id"]); return True
        return False

    if focus:
        # focus 1 — règle MOE (≥2), comptent dans ingenierie
        moe = [r for r in pools["ingenierie"] if (r["source"] or "") == "cpv_moe_override"]
        for r in moe[:2]:
            prendre(r)
        # focus 2 — Pattern 4 (≥2) : marchés dont l'id est dans le log, preset courant ingenierie/conseil_rd/it
        for p in ("ingenierie", "conseil_rd", "it"):
            for r in pools[p]:
                if len([x for x in choisis if x["id"] in ids_p4]) >= 2:
                    break
                if r["id"] in ids_p4:
                    prendre(r)
        # focus 3 — CPV 79* (≥4) depuis ingenierie/conseil_rd
        for p in ("conseil_rd", "ingenierie"):
            for r in pools[p]:
                if sum(1 for x in choisis if (x["cpv_principal"] or "").startswith("79")) >= 4:
                    break
                if (r["cpv_principal"] or "").startswith("79"):
                    prendre(r)

    # remplissage par preset à 5, en visant ~60 % cpv / 40 % llm
    for p in PRESETS:
        deja = [x for x in choisis if x["preset_principal"] == p]
        besoin = par_preset - len(deja)
        if besoin <= 0:
            continue
        cpv = [r for r in pools[p] if (r["source"] or "").startswith("cpv") and r["id"] not in vus]
        llm = [r for r in pools[p] if (r["source"] or "") == "llm" and r["id"] not in vus]
        n_cpv = round(besoin * 0.6)
        pris = cpv[:n_cpv] + llm[:besoin - n_cpv]
        if len(pris) < besoin:  # complète si une source manque
            reste = [r for r in pools[p] if r["id"] not in vus and r not in pris]
            pris += reste[:besoin - len(pris)]
        for r in pris[:besoin]:
            prendre(r)

    return choisis[:n]


def _ts():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _couverture(sample):
    moe = sum(1 for s in sample if (s["source"] or "") == "cpv_moe_override")
    c79 = sum(1 for s in sample if (s["cpv_principal"] or "").startswith("79"))
    p4 = len(_ids_pattern4() & {s["id"] for s in sample})
    src = Counter("llm" if (s["source"] or "") == "llm" else "cpv" for s in sample)
    print(f"Couverture focus : MOE={moe} (cible ≥2) | Pattern4={p4} (≥2) | "
          f"CPV 79*={c79} (≥4) | sources cpv={src['cpv']}/llm={src['llm']}")
    print("Par preset : " + ", ".join(f"{p}={sum(1 for s in sample if s['preset_principal']==p)}" for p in PRESETS))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--focus-fixes", action="store_true")
    ap.add_argument("--dump", action="store_true")
    args = ap.parse_args()

    con = connexion()
    sample = _echantillon(con, n=args.n, focus=args.focus_fixes)
    con.close()
    ts = _ts()

    print(f"=== Tirage validation v2 — {len(sample)} marchés"
          f"{' [focus-fixes]' if args.focus_fixes else ''} ===")
    _couverture(sample)
    print()

    if args.dump or True:  # toujours dumper le CSV pour Younes
        path = os.path.join(DATA, f"validation_decp_sample_v2_{ts}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", "preset_assigne", "source", "confiance", "cpv_principal",
                        "acheteur_nom", "objet"])
            for s in sample:
                w.writerow([s["id"], s["preset_principal"], s["source"], s["confiance"],
                            s["cpv_principal"], s["acheteur_nom"], (s["objet"] or "")[:200]])
        print(f"Échantillon écrit : {path}\n")

    if args.dump:
        for i, s in enumerate(sample, 1):
            print(f"[{i:2}] {s['preset_principal']:13} ({s['source']}, c={s['confiance']}) "
                  f"CPV {s['cpv_principal']} — {(s['objet'] or '')[:75]}")
        return

    # interactif
    print("Pour chaque marché : o = correct, n = incorrect, ? = incertain (compté correct), q = quitter\n")
    verdicts = []
    for i, s in enumerate(sample, 1):
        print(f"\n[{i}/{len(sample)}] Objet : {(s['objet'] or '')[:200]}")
        print(f"     CPV {s['cpv_principal']} | Acheteur : {s['acheteur_nom']}")
        print(f"     → preset = {s['preset_principal']}  (source {s['source']}, confiance {s['confiance']})")
        rep = ""
        while rep not in ("o", "n", "?", "q"):
            rep = input("     correct ? [o/n/?] : ").strip().lower()
        if rep == "q":
            break
        verdicts.append((s, rep))

    corrects = sum(1 for _, r in verdicts if r in ("o", "?"))
    nb = len(verdicts)
    par_src = defaultdict(lambda: [0, 0])
    for s, r in verdicts:
        bon = r in ("o", "?")
        k = "llm" if s["source"] == "llm" else "cpv"
        par_src[k][1] += 1; par_src[k][0] += bon
    path = os.path.join(DATA, f"validation_decp_verdicts_v2_{ts}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "preset_assigne", "source", "ton_verdict"])
        for s, r in verdicts:
            w.writerow([s["id"], s["preset_principal"], s["source"], r])
    print(f"\n=== Validation v2 — {corrects}/{nb} ({_pct(corrects, nb)}) ===")
    for k in ("cpv", "llm"):
        b, t = par_src[k]
        print(f"  {k} : {b}/{t} ({_pct(b, t)})")
    print(f"Seuil GO ferme DECP 3 : ≥ 85 %. Verdicts : {path}")


def _pct(n, d):
    return f"{100.0*n/d:.0f} %" if d else "—"


if __name__ == "__main__":
    main()
