"""
scripts/decp_rapport_sprint2.py — Sprint DECP 2, Étape 5 (audit final + rapport).

Génère la section audit de RAPPORT_DECP_SPRINT2.md (distributions, source, coût,
cohérence vs audit Sprint 1). La section validation manuelle (≥85% = GO) est
complétée séparément (decp_valider_classif.py + revue Younes).

Usage : python scripts/decp_rapport_sprint2.py [--cout-llm 6.8]
"""
import argparse
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decp.db import connexion

RAPPORT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "RAPPORT_DECP_SPRINT2.md")
PRESETS = ["btp", "ingenierie", "it", "conseil_rd", "formation", "enr"]
# Distribution CPV brute de l'audit Sprint 1 (référence de cohérence).
REF_SPRINT1 = {"btp": 34.0, "ingenierie": 8.1, "it": 3.4, "enr": 1.3, "formation": 1.4}


def _pct(n, d):
    return 100.0 * n / d if d else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cout-llm", type=float, default=None, help="coût LLM total mesuré (€)")
    args = ap.parse_args()

    con = connexion()
    try:
        total = con.execute("SELECT COUNT(*) FROM decp_marches").fetchone()[0]
        dist = dict(con.execute(
            "SELECT preset_principal, COUNT(*) FROM decp_classification "
            "GROUP BY preset_principal").fetchall())
        via_cpv = con.execute("SELECT COUNT(*) FROM decp_classification WHERE source LIKE 'cpv%'").fetchone()[0]
        via_llm = con.execute("SELECT COUNT(*) FROM decp_classification WHERE source='llm'").fetchone()[0]
        budget = con.execute("SELECT COUNT(*) FROM decp_classification WHERE source='budget'").fetchone()[0]
        faible = con.execute("SELECT COUNT(*) FROM decp_classification WHERE source='llm' AND confiance < 0.6").fetchone()[0]
        conf_moy = con.execute("SELECT AVG(confiance) FROM decp_classification WHERE source='llm'").fetchone()[0]
    finally:
        con.close()

    classes = sum(v for k, v in dist.items() if k in PRESETS) + dist.get("hors_perimetre", 0)
    non_classif = dist.get("non_classifie_budget", 0) + dist.get(None, 0)
    cout = args.cout_llm if args.cout_llm is not None else via_llm * 0.00046

    L = []
    w = L.append
    w("# Rapport Sprint DECP 2 — classification preset des marchés DECP\n")
    w("_Généré par `scripts/decp_rapport_sprint2.py`. Modèle LLM : Haiku 4.5. "
      "Exploration CPV : `data/decp_cpv_distribution.csv`._\n")

    w("## Audit final classification\n")
    w("```")
    w("=== AUDIT FINAL CLASSIFICATION DECP ===")
    w(f"Total marchés DECP         : {total:,}".replace(",", " "))
    w(f"Classifiés                 : {classes:,} ({_pct(classes,total):.1f} %)".replace(",", " "))
    w(f"  - via préfiltrage CPV   : {via_cpv:,}".replace(",", " "))
    w(f"  - via LLM Haiku         : {via_llm:,}".replace(",", " "))
    w(f"Non classifiés (budget)    : {non_classif:,}".replace(",", " "))
    w("")
    w("Distribution finale par preset :")
    for p in PRESETS:
        v = dist.get(p, 0)
        w(f"  - {p:14} : {v:>7,} ({_pct(v,total):.1f} %)".replace(",", " "))
    w(f"  - {'hors_perimetre':14} : {dist.get('hors_perimetre',0):>7,} "
      f"({_pct(dist.get('hors_perimetre',0),total):.1f} %)".replace(",", " "))
    w(f"  - {'non_classifie':14} : {non_classif:>7,} ({_pct(non_classif,total):.1f} %)".replace(",", " "))
    w("")
    w("Cohérence vs audit Sprint 1 (distribution CPV brute) :")
    alertes = []
    for p, ref in REF_SPRINT1.items():
        eff = _pct(dist.get(p, 0), total)
        flag = ""
        if abs(eff - ref) > 5:
            flag = "  <-- ECART > 5 pts"
            alertes.append((p, ref, eff))
        w(f"  {p:12} attendu ~{ref:.1f} % -> effectif {eff:.1f} %{flag}")
    w("")
    w(f"Confiance LLM moyenne      : {conf_moy or 0:.2f}")
    w(f"Marchés LLM confiance <0.6 : {faible}")
    w(f"Coût total LLM             : {cout:.2f} € / 50.00 €")
    w("```")
    w("")

    if alertes:
        w("⚠️ **Écarts > 5 pts** vs Sprint 1 — à noter (le LLM reclasse une partie des "
          "ambigus, ce qui peut faire monter certains presets ; un écart > 10 pts serait "
          "une stop-condition) :")
        for p, ref, eff in alertes:
            w(f"- **{p}** : {ref:.1f} % → {eff:.1f} % ({eff-ref:+.1f} pts)")
        w("")
    else:
        w("✓ Aucun écart > 5 pts vs l'audit Sprint 1 — distribution cohérente.\n")

    w("## Validation manuelle (Étape 4)\n")
    w("Échantillon stratifié de 50 marchés via `scripts/decp_valider_classif.py` "
      "(7/preset, assouplissement conseil_rd, 50/50 cpv/llm). **À valider manuellement "
      "par Younes** (mode interactif o/n/?) — seuil **≥ 85 % = GO ferme** pour Sprint DECP 3. "
      "Un dump revue est dans `data/validation_decp_sample_*.csv`.\n")
    w("_Section précision à compléter après la passe de validation manuelle._\n")

    w("## Recommandation go/no-go Sprint DECP 3\n")
    w("- **≥ 85 %** précision → GO ferme.\n- **70-85 %** → GO conditionnel (raffiner le "
      "prompt LLM sur les presets fautifs).\n- **< 70 %** → STOP (prompt trop court ou "
      "préfiltrage CPV trop agressif).\n")
    w("\n_Recommandation provisoire (sous réserve de la validation manuelle) : à compléter._\n")

    with open(RAPPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(f"Rapport écrit : {RAPPORT}")
    print(f"Classés {classes}/{total} | CPV {via_cpv} | LLM {via_llm} | budget {budget} | coût ~{cout:.2f} €")


if __name__ == "__main__":
    main()
