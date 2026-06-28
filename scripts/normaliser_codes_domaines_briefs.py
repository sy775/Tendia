"""Normalise les préfixes de codes domaine dans les briefs (typos LLM).

Le LLM écrit parfois `energia_...` au lieu de `energie_...` (ou `energy_...`).
Ce code n'existe pas dans la taxonomie → il est silencieusement ignoré par le
matching (`_eval_domaines_couverts` compare le code brut aux domaines_couverts).
Conséquence mesurée sur BOAMP-26-56995 : le domaine dominant (biomasse 45 %)
était perdu → score 64 au lieu de 100.

Corrige `domaines_metier[].code` ET `lots[].domaine` dans la collection SQLite
`briefs_extraits` et la copie disque `data/extractions/<id>.json` si présente.

Usage :
    python scripts/normaliser_codes_domaines_briefs.py            # dry-run (défaut)
    python scripts/normaliser_codes_domaines_briefs.py --apply    # écrit
"""
import sys
import io
import json
import os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stockage

# Préfixes de typo fréquents produits par le LLM → préfixe canonique.
TYPO_PREFIXE = {"energia": "energie", "energy": "energie"}

REP_EXTRACTIONS = os.path.join("data", "extractions")


def _normaliser_code(code):
    """Corrige le préfixe (avant le 1er '_') si c'est une typo connue."""
    if not code or not isinstance(code, str):
        return code, False
    prefix, sep, reste = code.partition("_")
    corrige = TYPO_PREFIXE.get(prefix)
    if corrige and corrige != prefix:
        return (f"{corrige}{sep}{reste}" if sep else corrige), True
    return code, False


def _normaliser_brief(brief):
    """Retourne (changements:list[(ancien,nouveau)]). Mute `brief` en place."""
    chg = []
    for d in (brief.get("domaines_metier") or []):
        if isinstance(d, dict):
            nouveau, modif = _normaliser_code(d.get("code"))
            if modif:
                chg.append((d["code"], nouveau))
                d["code"] = nouveau
    for lot in (brief.get("lots") or []):
        if isinstance(lot, dict) and lot.get("domaine"):
            nouveau, modif = _normaliser_code(lot.get("domaine"))
            if modif:
                chg.append((lot["domaine"], nouveau))
                lot["domaine"] = nouveau
    return chg


def main():
    apply = "--apply" in sys.argv
    briefs = stockage.charger("briefs_extraits")
    total = 0
    touches = 0
    for mid, brief in briefs.items():
        chg = _normaliser_brief(brief)
        if not chg:
            continue
        touches += 1
        total += len(chg)
        print(f"{mid} :")
        for ancien, nouveau in chg:
            print(f"    {ancien}  ->  {nouveau}")
        if apply:
            stockage.ecrire("briefs_extraits", mid, brief)
            disque = os.path.join(REP_EXTRACTIONS, f"{mid}.json")
            if os.path.isfile(disque):
                try:
                    with open(disque, encoding="utf-8") as f:
                        bd = json.load(f)
                    if _normaliser_brief(bd):
                        with open(disque, "w", encoding="utf-8") as f:
                            json.dump(bd, f, ensure_ascii=False, indent=2)
                        print(f"    (copie disque {disque} mise à jour)")
                except Exception as e:
                    print(f"    !! disque non corrigé : {e}")

    mode = "APPLIQUÉ" if apply else "DRY-RUN (rien écrit ; relancer avec --apply)"
    print(f"\n{touches} brief(s), {total} code(s) corrigé(s). [{mode}]")


if __name__ == "__main__":
    main()
