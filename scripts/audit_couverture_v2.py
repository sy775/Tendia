"""
scripts/audit_couverture_v2.py — Refonte pipeline v2, Étape 6 (audit couverture).

Compare briefs v1/v2, couverture des 3 voies de montant, des critères (plat + alertes),
distribution preset v1 vs v2, top hypothèses Voie 2. Ajoute la section Étape 6 au
RAPPORT_REFONTE_PIPELINE_V2.md. Lecture seule, 0 €.

Usage : python scripts/audit_couverture_v2.py
"""
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stockage
from decp.classifier_cpv import classer_marche_cpv

RAPPORT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "RAPPORT_REFONTE_PIPELINE_V2.md")


def _preset(mk):
    if not mk or not mk.get("cpv_principal"):
        return "(sans cpv)"
    return classer_marche_cpv({"id": mk.get("id"), "cpv_principal": mk["cpv_principal"],
                               "objet": mk.get("objet", "")})["preset_principal"] or "?"


def _pct(n, d):
    return f"{100.0*n/d:.0f} %" if d else "—"


def main():
    m = stockage.charger("marches") or {}
    be = stockage.charger("briefs_extraits") or {}
    v2 = {mid: b for mid, b in be.items() if str(b.get("version_extraction_llm")) == "2"}
    complet = {mid for mid, mk in m.items() if mk.get("dce_contenu") == "complet"}
    v1_restants = complet - set(v2.keys())
    nv2 = len(v2)

    voie1 = sum(1 for b in v2.values() if b.get("montant_voie_1_eur"))
    voie2 = sum(1 for b in v2.values() if b.get("montant_voie_2_disponible"))
    une = sum(1 for b in v2.values() if b.get("montant_au_moins_une_voie"))
    crit = sum(1 for b in v2.values() if b.get("criteres_attribution_plat"))
    alertes = sum(1 for b in v2.values() if b.get("extraction_v2_a_verifier")
                  or b.get("criteres_alerte_pas_de_prix") or b.get("criteres_alerte_somme_incorrecte")
                  or b.get("criteres_alerte_non_classes") or b.get("montant_alerte_coherence"))

    presets_v2 = Counter(_preset(m.get(mid)) for mid in v2)
    presets_v1 = Counter(_preset(m.get(mid)) for mid in v1_restants)

    hypos = Counter()
    for b in v2.values():
        for h in ((b.get("montant_3_voies") or {}).get("voie_2_hypotheses") or []):
            lib = (h.get("hypothese") or "")[:48]
            if lib:
                hypos[lib] += 1

    L = ["", "## Étape 6 — Audit couverture v2", "", "```"]
    L.append("=== AUDIT POST-EXTRACTION v2 ===")
    L.append(f"Briefs en v2                  : {nv2}")
    L.append(f"Briefs complet encore en v1   : {len(v1_restants)}")
    L.append("")
    L.append("Couverture montants (briefs v2) :")
    L.append(f"  Voie 1 (publié)             : {voie1} ({_pct(voie1, nv2)})")
    L.append(f"  Voie 2 (estimation)         : {voie2} ({_pct(voie2, nv2)})")
    L.append(f"  Au moins une voie           : {une} ({_pct(une, nv2)})  [cible ≥80%]")
    L.append(f"  Aucune voie                 : {nv2-une} ({_pct(nv2-une, nv2)})")
    L.append("")
    L.append("Couverture critères (briefs v2) :")
    L.append(f"  Critères extraits           : {crit} ({_pct(crit, nv2)})")
    L.append(f"  Avec ≥1 alerte              : {alertes} ({_pct(alertes, nv2)})")
    L.append("")
    L.append("Distribution preset (v2 vs v1 restant) :")
    for p in sorted(set(presets_v2) | set(presets_v1)):
        L.append(f"  {p:14} : v2 {presets_v2.get(p,0):>3} | v1 {presets_v1.get(p,0):>3}")
    L.append("")
    L.append("Top hypothèses Voie 2 :")
    for lib, c in hypos.most_common(10):
        L.append(f"  {c:>3}× {lib}")
    L.append("```")
    L.append("")

    # Append à la suite du rapport existant (créé par audit_etat_pipeline)
    contenu = ""
    if os.path.exists(RAPPORT):
        with open(RAPPORT, encoding="utf-8") as f:
            contenu = f.read()
    # éviter les doublons de section
    marqueur = "## Étape 6 — Audit couverture v2"
    if marqueur in contenu:
        contenu = contenu.split(marqueur)[0].rstrip() + "\n"
    with open(RAPPORT, "w", encoding="utf-8") as f:
        f.write(contenu + "\n".join(L) + "\n")

    print(f"=== Étape 6 — couverture v2 ===")
    print(f"Briefs v2 : {nv2} | au moins une voie montant : {_pct(une, nv2)} | "
          f"critères : {_pct(crit, nv2)} | alertes : {alertes}")
    print(f"Section ajoutée à {RAPPORT}")


if __name__ == "__main__":
    main()
