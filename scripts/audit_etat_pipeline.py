"""
scripts/audit_etat_pipeline.py — Refonte pipeline v2, Étape 1 (audit état).

Distribution dce_contenu, candidats re-download (url_consultation_dce_directe + dce_contenu
!= complet), cible re-extraction (dce_contenu='complet' & version != 2) + coût estimé.
Initialise RAPPORT_REFONTE_PIPELINE_V2.md. Lecture seule, 0 €.

NB : le champ de complétude est `dce_contenu` ('complet'/'vide'/'incomplet'/…). `dce_qualite`
code la MÉTHODE de découverte d'URL (directe/via_keyword/racine/absente), pas la complétude.

Usage : python scripts/audit_etat_pipeline.py
"""
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stockage

RAPPORT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "RAPPORT_REFONTE_PIPELINE_V2.md")
COUT_FULL_MOY = 0.312    # € (mesuré sur 147 extractions full Sonnet 4.6)
COUT_V2_MAJORE = 0.40    # € (prompt v2 plus long : contexte BOAMP + 3 voies)


def main():
    m = stockage.charger("marches") or {}
    be = stockage.charger("briefs_extraits") or {}
    n = len(m)

    contenu = Counter(mk.get("dce_contenu") for mk in m.values())
    candidats = [mid for mid, mk in m.items()
                 if mk.get("url_consultation_dce_directe") and mk.get("dce_contenu") != "complet"]
    complet = {mid for mid, mk in m.items() if mk.get("dce_contenu") == "complet"}
    deja_v2 = {mid for mid, b in be.items() if str(b.get("version_extraction_llm")) == "2"}
    cible_reextraction = complet - deja_v2

    cout_min = len(cible_reextraction) * COUT_FULL_MOY
    cout_max = len(cible_reextraction) * COUT_V2_MAJORE

    L = []
    w = L.append
    w("# Rapport — Refonte Pipeline d'Extraction v2\n")
    w("_Généré progressivement par les scripts `audit_etat_pipeline` / `retenter_download_dce` "
      "/ `audit_couverture_v2`. Modèle LLM : Sonnet 4.6. Diagnostic Phase A : Scénario C "
      "(logique montant multi-preset neutre, pas de purge)._\n")
    w("## Étape 1 — Audit état actuel\n")
    w("```")
    w(f"Briefs Tendia                 : {n}")
    w("Distribution dce_contenu (complétude du DCE téléchargé) :")
    for k, v in contenu.most_common():
        w(f"  {str(k):14} : {v}")
    w("")
    w(f"Candidats re-download         : {len(candidats)}")
    w("  (url_consultation_dce_directe présent ET dce_contenu != 'complet')")
    w("")
    w(f"Cible re-extraction LLM v2     : {len(cible_reextraction)}")
    w(f"  - dce_contenu='complet'      : {len(complet)}")
    w(f"  - déjà en v2 (skip)          : {len(deja_v2)}")
    w(f"Coût estimé re-extraction      : {cout_min:.1f} € (prompt actuel) "
      f"à {cout_max:.1f} € (prompt v2 majoré) / cap 100 €")
    w("```")
    w("")
    seuil_ok = len(candidats) >= 5 and cout_max <= 100
    if not seuil_ok:
        w("> ⚠️ **Stop-condition** : candidats < 5 ou coût > 100 € — à arbitrer.\n")
    else:
        w(f"> ✓ {len(candidats)} candidats (≥ 5), coût estimé ≤ 100 € → poursuite Phase B.\n")

    with open(RAPPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")

    print(f"=== Étape 1 — audit ===")
    print(f"dce_contenu : " + ", ".join(f"{k}={v}" for k, v in contenu.most_common()))
    print(f"Candidats re-download : {len(candidats)}")
    print(f"Cible re-extraction v2 : {len(cible_reextraction)} "
          f"(complet {len(complet)} - déjà v2 {len(deja_v2)})")
    print(f"Coût estimé : {cout_min:.1f}–{cout_max:.1f} € / 100 €")
    print(f"Rapport initialisé : {RAPPORT}")


if __name__ == "__main__":
    main()
