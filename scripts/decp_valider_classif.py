"""
scripts/decp_valider_classif.py — Sprint DECP 2, Étape 4 (validation manuelle).

Tire un échantillon STRATIFIÉ de 50 marchés (par preset, 50/50 cpv/llm si possible),
puis :
- mode interactif (défaut) : tu saisis o (correct) / n (incorrect) / ? (incertain=correct),
  verdicts écrits dans data/validation_decp_classif_<ts>.csv + agrégats ;
- mode --dump : écrit l'échantillon dans un CSV et l'affiche (revue hors-ligne).

Stratification (assouplissement conseil_rd quasi absent du CPV) :
  btp 7, ingenierie 7, it 7, conseil_rd 7 (4-5 LLM + 2-3 CPV), formation 7, enr 7,
  hors_perimetre 5, non_classifie_budget 3 (sinon complété sur btp/ingenierie).

Usage : python scripts/decp_valider_classif.py [--dump]
"""
import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decp.db import connexion

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
QUOTAS = {"btp": 7, "ingenierie": 7, "it": 7, "conseil_rd": 7,
          "formation": 7, "enr": 7, "hors_perimetre": 5, "non_classifie_budget": 3}


def _echantillon(con):
    """Stratifié par preset, 50/50 cpv/llm si possible. Déterministe (ORDER BY id)."""
    sample = []
    for preset, quota in QUOTAS.items():
        rows = con.execute(
            "SELECT m.id, m.objet, m.cpv_principal, m.acheteur_nom, c.preset_principal, "
            "c.source, c.confiance FROM decp_classification c "
            "JOIN decp_marches m ON m.id=c.decp_id WHERE c.preset_principal=? ORDER BY m.id",
            (preset,)).fetchall()
        if not rows:
            continue
        cpv = [r for r in rows if (r["source"] or "").startswith("cpv")]
        llm = [r for r in rows if r["source"] == "llm"]
        moitie = quota // 2
        pris = llm[:quota - moitie] + cpv[:moitie]
        # complète si une source manque
        if len(pris) < quota:
            reste = [r for r in rows if r not in pris]
            pris += reste[:quota - len(pris)]
        sample += [dict(r) for r in pris[:quota]]
    # complète à 50 si des strates étaient vides (ex. non_classifie_budget absent)
    if len(sample) < 50:
        manque = 50 - len(sample)
        deja = {s["id"] for s in sample}
        extra = con.execute(
            "SELECT m.id, m.objet, m.cpv_principal, m.acheteur_nom, c.preset_principal, "
            "c.source, c.confiance FROM decp_classification c JOIN decp_marches m ON m.id=c.decp_id "
            "WHERE c.preset_principal IN ('btp','ingenierie') ORDER BY m.id DESC").fetchall()
        for r in extra:
            if r["id"] not in deja:
                sample.append(dict(r)); deja.add(r["id"])
                if len(sample) >= 50:
                    break
    return sample[:50]


def _ts():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true", help="écrit+affiche l'échantillon sans interaction")
    args = ap.parse_args()

    con = connexion()
    sample = _echantillon(con)
    con.close()
    ts = _ts()

    if args.dump:
        path = os.path.join(DATA, f"validation_decp_sample_{ts}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", "preset_pipeline", "source", "confiance", "cpv", "acheteur", "objet"])
            for s in sample:
                w.writerow([s["id"], s["preset_principal"], s["source"], s["confiance"],
                            s["cpv_principal"], s["acheteur_nom"], (s["objet"] or "")[:160]])
        print(f"Échantillon ({len(sample)}) écrit : {path}\n")
        for i, s in enumerate(sample, 1):
            print(f"[{i:2}] {s['preset_principal']:18} ({s['source']}, conf={s['confiance']}) "
                  f"CPV {s['cpv_principal']} — {(s['objet'] or '')[:80]}")
        return

    # Mode interactif
    print(f"=== Validation manuelle — {len(sample)} marchés ===")
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

    path = os.path.join(DATA, f"validation_decp_classif_{ts}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "preset_pipeline", "source", "ton_verdict"])
        for s, rep in verdicts:
            w.writerow([s["id"], s["preset_principal"], s["source"], rep])

    corrects = sum(1 for _, r in verdicts if r in ("o", "?"))
    n = len(verdicts)
    par_src = defaultdict(lambda: [0, 0])
    par_preset = defaultdict(lambda: [0, 0])
    for s, r in verdicts:
        bon = r in ("o", "?")
        src = "llm" if s["source"] == "llm" else "cpv"
        par_src[src][1] += 1; par_src[src][0] += bon
        par_preset[s["preset_principal"]][1] += 1; par_preset[s["preset_principal"]][0] += bon

    print(f"\n=== Validation manuelle — {n} marchés ===")
    print(f"Précision globale     : {corrects}/{n} ({_pct(corrects, n)})")
    for src in ("cpv", "llm"):
        b, t = par_src[src]
        print(f"Précision {src:3}         : {b}/{t} ({_pct(b, t)})")
    print("Détail par preset :")
    for p, (b, t) in sorted(par_preset.items()):
        print(f"  - {p:18} : {b}/{t}")
    print(f"\nCSV : {path}")


def _pct(n, d):
    return f"{100.0*n/d:.0f} %" if d else "—"


if __name__ == "__main__":
    main()
