"""
scripts/decp_explore_cpv.py — Sprint DECP 2, Étape 0 (exploration CPV, BLOQUANTE).

Distribution complète des codes CPV principaux des 142 735 marchés DECP en base.
Base du mapping CPV→preset (Étape 1). 0 LLM, lecture seule.

Produit `data/decp_cpv_distribution.csv` + un résumé console / Markdown.
Usage : python scripts/decp_explore_cpv.py
"""
import csv
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decp.db import connexion

CSV_OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "decp_cpv_distribution.csv")

# Libellés des divisions CPV (2 chiffres) — suffisant pour l'analyse stratégique.
DIVISIONS = {
    "03": "Agriculture/sylviculture", "09": "Pétrole/électricité/énergie",
    "14": "Produits minéraux", "15": "Alimentation/boissons", "16": "Machines agricoles",
    "18": "Habillement/cuir", "19": "Cuir/textiles", "22": "Imprimés",
    "24": "Produits chimiques", "30": "Bureautique/informatique (matériel)",
    "31": "Machines/appareils électriques", "32": "Radio/TV/télécom (équip.)",
    "33": "Médical/pharmacie", "34": "Transport (véhicules)", "35": "Sécurité/défense",
    "37": "Instruments musique/sport", "38": "Instruments labo/optique",
    "39": "Mobilier/nettoyage", "41": "Eau", "42": "Machines industrielles",
    "43": "Machines extraction/BTP", "44": "Matériaux construction/structures",
    "45": "TRAVAUX DE CONSTRUCTION (BTP)", "48": "Logiciels (paquets)",
    "50": "Réparation/maintenance", "51": "Installation (sauf logiciels)",
    "55": "Hôtellerie/restauration", "60": "Transports", "63": "Services transport annexes",
    "64": "Postes/télécommunications", "65": "Services publics (eau/énergie distrib.)",
    "66": "Services financiers/assurance", "70": "Immobilier", "71": "ARCHITECTURE/INGÉNIERIE",
    "72": "SERVICES INFORMATIQUES (IT)", "73": "R&D/conseil scientifique",
    "75": "Administration publique", "76": "Pétrole/gaz (services)",
    "77": "Agriculture/horticulture (services)", "79": "Services entreprise/juridique/RH",
    "80": "ÉDUCATION/FORMATION", "85": "Santé/action sociale", "90": "Environnement/déchets",
    "92": "Loisirs/culture/sport", "98": "Autres services collectifs",
}

# Mapping 2 chiffres → preset « propre » (pour estimer le volume résolvable niveau 1).
PREFIXE2_PRESET = {"45": "btp", "71": "ingenierie", "72": "it",
                   "73": "conseil_rd", "80": "formation"}
# Hors-périmètre « évidents » (gros volumes non Tendia).
PREFIXE2_HORS = {"15", "55", "60", "33", "34", "50", "39", "85", "66", "90",
                 "44", "30", "31", "32", "24", "18", "22", "03", "77", "98"}


def main():
    con = connexion()
    try:
        total = con.execute("SELECT COUNT(*) FROM decp_marches").fetchone()[0]
        rows = con.execute(
            "SELECT cpv_principal, COUNT(*) n FROM decp_marches "
            "WHERE cpv_principal IS NOT NULL GROUP BY cpv_principal ORDER BY n DESC"
        ).fetchall()
    finally:
        con.close()

    print(f"=== Exploration CPV DECP — {total:,} marchés, "
          f"{len(rows)} codes CPV uniques ===".replace(",", " "))

    # CSV + cumulatif
    os.makedirs(os.path.dirname(CSV_OUT), exist_ok=True)
    cumul = 0
    lignes_csv = []
    for code, n in rows:
        cumul += n
        lignes_csv.append((code, DIVISIONS.get(str(code)[:2], ""), n,
                           round(100 * n / total, 4), round(100 * cumul / total, 3)))
    with open(CSV_OUT, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["cpv", "division_libelle", "volume", "pct", "pct_cumule"])
        wr.writerows(lignes_csv)
    print(f"CSV écrit : {CSV_OUT}")

    # Pareto
    def cumul_top(k):
        return round(100 * sum(n for _, n in rows[:k]) / total, 1)
    print(f"\n% cumulé : top30={cumul_top(30)}% | top100={cumul_top(100)}% | "
          f"top500={cumul_top(500)}%")

    # Codes ≥ 0,5 % (à mapper exhaustivement)
    seuil = 0.005 * total
    principaux = [(c, n) for c, n in rows if n >= seuil]
    print(f"\nCodes ≥ 0,5 % du volume (à mapper exhaustivement) : {len(principaux)} codes, "
          f"{round(100*sum(n for _,n in principaux)/total,1)} % du volume cumulé")

    # Top 30
    print("\n=== TOP 30 CPV ===")
    print(f"{'CPV':>9} {'vol':>7} {'%':>6}  division")
    for code, n in rows[:30]:
        print(f"{code:>9} {n:>7} {100*n/total:>5.1f}%  {DIVISIONS.get(str(code)[:2],'?')}")

    # Volume théorique résolvable par préfiltrage 2 chiffres
    par_div = Counter()
    for code, n in rows:
        par_div[str(code)[:2]] += n
    vol_presets = sum(par_div[d] for d in PREFIXE2_PRESET)
    vol_hors = sum(par_div[d] for d in PREFIXE2_HORS)
    vol_resolu = vol_presets + vol_hors
    print(f"\n=== Estimation préfiltrage niveau 1 (préfixe 2 ch.) ===")
    print("Presets (45/71/72/73/80) :")
    for d, p in PREFIXE2_PRESET.items():
        print(f"  {d} {p:12} : {par_div[d]:>7} ({100*par_div[d]/total:.1f} %)")
    print(f"Hors-périmètre évidents ({len(PREFIXE2_HORS)} divisions) : "
          f"{vol_hors:>7} ({100*vol_hors/total:.1f} %)")
    print(f"  → 09 (énergie, EnR partiel)  : {par_div['09']:>7} ({100*par_div['09']/total:.1f} %)")
    print(f"\nVOLUME RÉSOLVABLE NIVEAU 1 (préfixe 2 ch.) : {vol_resolu:,} / {total:,} "
          f"= {100*vol_resolu/total:.1f} %".replace(",", " "))
    ambigus = total - vol_resolu
    print(f"AMBIGUS / inconnus (→ LLM ou mapping exact) : {ambigus:,} = {100*ambigus/total:.1f} %"
          .replace(",", " "))
    cout_llm = ambigus * 0.0008
    print(f"Coût LLM estimé si tous les ambigus passent en Haiku : ~{cout_llm:.1f} € "
          f"(plafond 50 €)")

    # Stop-condition : ambigus > 50 % ?
    if ambigus > 0.5 * total:
        print("\n⚠ STOP-CONDITION : ambigus > 50 % — mapping CPV à enrichir (codes exacts).")
    else:
        print(f"\n✓ Ambigus < 50 % — mapping niveau 1 viable (couverture {100*vol_resolu/total:.0f} %).")


if __name__ == "__main__":
    main()
