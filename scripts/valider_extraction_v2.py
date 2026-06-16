"""
scripts/valider_extraction_v2.py — Refonte pipeline v2, Étape 7 (validation manuelle).

Tirage stratifié de 20 briefs v2 (10 ayant GAGNÉ en DCE-complet via le fix B12 +
10 déjà complet avant, avec comparaison brief_v1_backup). Affichage interactif :
4 questions o/n/? par brief. Verdicts → data/validation_extraction_v2_<ts>.csv.

Critère GO Sprint DECP 3 : précision globale ≥ 85 % (sur 4 questions × 20 briefs).

Usage : python scripts/valider_extraction_v2.py [--dump]
"""
import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stockage
import tendia_telecharger_dce as T

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def _a_gagne_b12(mid):
    """Le marché a gagné en complet via le re-download B12 (présence du backup)."""
    return os.path.isdir(os.path.join(str(T.REPERTOIRE_DCE), f"{mid}.bak_avant_b12"))


def _echantillon():
    be = stockage.charger("briefs_extraits") or {}
    v2 = [(mid, b) for mid, b in sorted(be.items())
          if str(b.get("version_extraction_llm")) == "2"]
    gagnes = [(mid, b) for mid, b in v2 if _a_gagne_b12(mid)]
    deja = [(mid, b) for mid, b in v2 if not _a_gagne_b12(mid)]
    sample = gagnes[:10] + deja[:10]
    # complète à 20 si une catégorie manque
    if len(sample) < 20:
        reste = [x for x in v2 if x not in sample]
        sample += reste[:20 - len(sample)]
    return sample[:20], set(mid for mid, _ in gagnes)


def _montant_v1(b):
    mm = (b.get("brief_v1_backup") or {}).get("montant_marche") or b.get("montant_marche") or {}
    return mm.get("valeur_estimee_euros"), mm.get("type")


def _afficher(mid, b, est_gagne):
    m = stockage.charger("marches").get(mid, {})
    print("=" * 72)
    tag = "🟢 GAGNÉ via B12" if est_gagne else "🔵 déjà complet (v1→v2)"
    print(f"[{mid}] {tag}")
    print(f"  Objet   : {(m.get('objet') or '')[:100]}")
    print(f"  CPV     : {m.get('cpv_principal')} | Acheteur : {m.get('acheteur_nom')}")
    print(f"  SIREN BOAMP : {m.get('acheteur_siren')} | nature : {m.get('nature')}")
    # Montant 3 voies
    m3 = b.get("montant_3_voies") or {}
    if b.get("montant_voie_1_eur"):
        print(f"  💶 Voie 1 (publié) : {b['montant_voie_1_eur']:,} € "
              f"(source : {b.get('montant_voie_1_source')})".replace(",", " "))
    if b.get("montant_voie_2_disponible"):
        print(f"  💶 Voie 2 (estimation) : {m3.get('voie_2_min_eur')} – {m3.get('voie_2_max_eur')} €")
        for h in (m3.get("voie_2_hypotheses") or [])[:5]:
            print(f"       • {h.get('hypothese')} = {h.get('valeur')}")
    if not b.get("montant_au_moins_une_voie"):
        print(f"  💶 Aucune voie : {m3.get('voie_2_raison_indisponible')}")
    # Critères plat
    print("  📊 Critères :")
    for c in (b.get("criteres_attribution_plat") or []):
        print(f"       [{c.get('famille')}] {c.get('libelle')} = {c.get('ponderation_pct')}% "
              f"({c.get('source_texte')})")
    flags = [k for k in ("criteres_alerte_pas_de_prix", "criteres_alerte_somme_incorrecte",
                         "criteres_alerte_non_classes", "montant_alerte_coherence")
             if b.get(k)]
    if flags:
        print(f"  ⚠️ alertes : {', '.join(flags)}")
    if not est_gagne and b.get("brief_v1_backup"):
        v1m, v1t = _montant_v1(b)
        print(f"  ↩ v1 (backup) : montant = {v1m} ({v1t})")


def _demander(q):
    r = ""
    while r not in ("o", "n", "?", "s", "q"):
        r = input(f"     {q} [o/n/? | s=skip, q=quit] : ").strip().lower()
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true", help="affiche sans interaction")
    args = ap.parse_args()

    sample, _ = _echantillon()
    gagnes_ids = {mid for mid, _ in sample if _a_gagne_b12(mid)}
    print(f"=== Validation extraction v2 — {len(sample)} briefs "
          f"({len(gagnes_ids)} gagnés B12 + {len(sample)-len(gagnes_ids)} déjà complet) ===\n")

    if args.dump:
        for mid, b in sample:
            _afficher(mid, b, mid in gagnes_ids)
        return

    print("Pour chaque brief, 4 questions. o=correct, n=incorrect, ?=incertain (compté correct).\n")
    verdicts = []
    for mid, b in sample:
        _afficher(mid, b, mid in gagnes_ids)
        rep = {}
        rep["criteres_classes"] = _demander("Critères correctement classés ?")
        if rep["criteres_classes"] == "q":
            break
        if b.get("montant_voie_1_eur"):
            rep["voie1_coherente"] = _demander("Voie 1 cohérente avec le DCE ?")
        if b.get("montant_voie_2_disponible"):
            rep["voie2_credible"] = _demander("Voie 2 hypothèses crédibles ?")
        rep["preset_bon"] = _demander("Preset toujours bon ?")
        verdicts.append((mid, rep))

    # Agrégats
    total = bon = 0
    par_q = defaultdict(lambda: [0, 0])
    for mid, rep in verdicts:
        for q, v in rep.items():
            if v in ("o", "n", "?"):
                par_q[q][1] += 1
                par_q[q][0] += (v in ("o", "?"))
                total += 1
                bon += (v in ("o", "?"))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(DATA, f"validation_extraction_v2_{ts}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "question", "verdict"])
        for mid, rep in verdicts:
            for q, v in rep.items():
                w.writerow([mid, q, v])

    print(f"\n=== Validation v2 — {len(verdicts)} briefs jugés ===")
    for q, (b_, t_) in par_q.items():
        print(f"  {q:18} : {b_}/{t_} ({100.0*b_/t_:.0f} %)" if t_ else f"  {q} : —")
    prec = 100.0 * bon / total if total else 0
    print(f"  PRÉCISION GLOBALE : {bon}/{total} ({prec:.0f} %)")
    verdict = ("GO ferme" if prec >= 85 else "GO conditionnel" if prec >= 70 else "STOP")
    print(f"  → Seuil DECP 3 : {verdict} (≥85 GO ferme / 70-85 conditionnel / <70 STOP)")
    print(f"  CSV : {path}")


if __name__ == "__main__":
    main()
