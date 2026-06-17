"""
scripts/requalifier_faux_complet.py — corrige les DCE marqués 'complet' à tort.

`qualifier_dce` marquait un dossier 'complet' d'après les TYPES de pièces cités dans
le RC (AE, CCAP, CCTP, DPGF…), même quand un SEUL fichier (le RC) avait été téléchargé
(reste auth-gated / zip non extrait). Résultat : brief extrait du RC seul = pauvre, mais
affiché 'complet'.

Ce script re-qualifie en 'incomplet' tout dossier `dce_contenu='complet'` ne contenant
en réalité qu'**≤ 1 document DCE** (hors guides/DUME). 0 € LLM.

Usage : python scripts/requalifier_faux_complet.py [--dry-run]
"""
import argparse
import os
import sys
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stockage
import tendia_extraire as TE

EXT_DCE = {".pdf", ".docx", ".doc", ".xlsx", ".xls"}
MOTS_NON_DCE = ("guide", "dume", "aide", "notice_depot", "manuel", "tuto")
RAISON = ("RC seul — autres pièces du DCE (CCAP/CCTP/DPGF…) non récupérées "
          "(accès restreint plateforme ou non extraites)")


def _nb_documents_dce(mid: str) -> int:
    dossier = os.path.join(str(TE.REPERTOIRE_DCE), mid)
    if not os.path.isdir(dossier):
        return 0
    n = 0
    for f in os.listdir(dossier):
        bas = f.lower()
        if os.path.splitext(bas)[1] in EXT_DCE and not any(k in bas for k in MOTS_NON_DCE):
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    m = stockage.charger("marches") or {}
    complet = [(mid, mk) for mid, mk in m.items() if mk.get("dce_contenu") == "complet"]
    faux = [(mid, mk) for mid, mk in complet if _nb_documents_dce(mid) <= 1]

    print(f"=== Re-qualification faux-complet (RC seul){' [DRY-RUN]' if args.dry_run else ''} ===")
    print(f"complet examinés : {len(complet)} | faux-complet (≤1 doc) : {len(faux)}")
    if args.dry_run:
        print("exemples :", [mid for mid, _ in faux[:8]])
        print("[DRY-RUN] aucune écriture.")
        return

    horo = datetime.now().isoformat()
    for mid, mk in faux:
        mk["dce_contenu"] = "incomplet"
        mk["dce_raison_contenu"] = RAISON
        mk["dce_requalifie_le"] = horo
        stockage.ecrire("marches", mid, mk)

    m2 = stockage.charger("marches") or {}
    print(f"\n⇒ {len(faux)} marchés re-qualifiés 'complet' → 'incomplet'.")
    print("dce_contenu après :", dict(Counter(mk.get("dce_contenu") for mk in m2.values())))


if __name__ == "__main__":
    main()
