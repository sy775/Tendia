"""
diagnostic_attributions_en_base.py
----------------------------------
Mesure combien de marchés en base sont en réalité des avis d'attribution
(ContractAwardNotice / "Résultat de marché"), qui ont passé le filtre
_est_avis_ouvert mais auraient dû être exclus.

Le filtre actuel dans connecteurs/boamp.py utilise des heuristiques texte
(type_avis, objet) qui laissent passer pas mal de marchés clos. La branche
eForms est un signal plus fiable mais nécessite un appel API par marché
pour la vérifier.

Ce script échantillonne et extrapole pour estimer l'ampleur du problème :
1. Sur N marchés au hasard de la base, ré-interroge BOAMP
2. Compte branches eForms ContractAwardNotice vs ContractNotice vs autres
3. Croise avec la pertinence (scores_matching)
4. Donne une estimation du volume à filtrer

Usage :
    python diagnostic_attributions_en_base.py --n 50
    python diagnostic_attributions_en_base.py --n 50 --pertinents-seulement
"""

import argparse
import io
import random
import sys
from collections import Counter, defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import dce_finder


def _pertinents_set(scores: dict) -> set:
    pertinents = set()
    for cle, score in scores.items():
        if not isinstance(score, dict):
            continue
        if "preset_code" in score and "matche" in score:
            if score.get("matche"):
                id_m = score.get("marche_id") or score.get("id") or cle.rsplit("_", 1)[0]
                pertinents.add(id_m)
        else:
            for preset_c, sub in score.items():
                if isinstance(sub, dict) and sub.get("matche"):
                    pertinents.add(cle)
    return pertinents


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50,
                    help="Taille de l'échantillon (défaut 50)")
    ap.add_argument("--pertinents-seulement", action="store_true",
                    help="Échantillonne uniquement parmi les marchés pertinents")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    marches = stockage.charger("marches") or {}
    scores = stockage.charger("scores_matching") or {}
    pertinents = _pertinents_set(scores)

    print("=" * 78)
    print("  Mesure du volume de ContractAwardNotice (avis d'attribution) en base")
    print("=" * 78)
    print(f"  Marchés en base    : {len(marches)}")
    print(f"  Pertinents (≥1 preset matche) : {len(pertinents)}")

    # Échantillonnage
    candidats = list(marches.keys())
    if args.pertinents_seulement:
        candidats = [id_m for id_m in candidats if id_m in pertinents]
        print(f"  Sélection : pertinents seulement ({len(candidats)} candidats)")

    random.seed(args.seed)
    if len(candidats) > args.n:
        echantillon = random.sample(candidats, args.n)
    else:
        echantillon = candidats
    print(f"  Échantillon        : {len(echantillon)}")
    print()

    # Pour chaque, ré-interroge BOAMP
    branches = Counter()
    natures_boamp = Counter()
    pertinents_par_branche = defaultdict(int)
    boamp_404 = 0
    sources_non_boamp = Counter()

    for i, id_m in enumerate(echantillon, 1):
        if i % 10 == 0:
            print(f"    ... {i}/{len(echantillon)}")
        m = marches[id_m]
        if m.get("source") != "BOAMP":
            sources_non_boamp[m.get("source") or "?"] += 1
            continue
        ref = m.get("reference_externe", "")
        record = dce_finder._fetch_record_boamp(ref)
        if not record:
            boamp_404 += 1
            continue
        donnees = dce_finder._parser_donnees(record)
        eforms = donnees.get("EFORMS") or {}
        branche = next((k for k in eforms.keys()
                        if k in ("ContractNotice", "ContractAwardNotice",
                                  "PriorInformationNotice")), "(aucune)")
        branches[branche] += 1
        if id_m in pertinents:
            pertinents_par_branche[branche] += 1
        natures_boamp[record.get("nature_libelle") or "?"] += 1

    # Synthèse
    n_boamp = sum(branches.values())
    print()
    print("=" * 78)
    print(f"  RÉSULTATS sur {n_boamp} marchés BOAMP échantillonnés")
    print("=" * 78)
    if sources_non_boamp:
        print(f"\n  Sources non-BOAMP dans l'échantillon :")
        for s, n in sources_non_boamp.most_common():
            print(f"    {s:<20} : {n}")
    if boamp_404:
        print(f"\n  API BOAMP 404      : {boamp_404}")

    print(f"\n  Branches eForms :")
    for b, n in branches.most_common():
        pct = n * 100 / n_boamp if n_boamp else 0
        marker = " ⚠ ATTRIBUTION (devrait être filtré)" if b == "ContractAwardNotice" else ""
        print(f"    {b:<25} : {n:3d} ({pct:5.1f}%){marker}")

    print(f"\n  Natures BOAMP :")
    for nat, n in natures_boamp.most_common(8):
        print(f"    {nat:<40} : {n}")

    if pertinents_par_branche:
        print(f"\n  Croisement Branche × Pertinence :")
        for b, n in branches.most_common():
            n_pert = pertinents_par_branche[b]
            print(f"    {b:<25} : {n:3d} total, dont {n_pert} pertinents")

    # Extrapolation
    n_award = branches.get("ContractAwardNotice", 0)
    if n_boamp > 0 and n_award > 0:
        ratio_award = n_award / n_boamp
        # Sur toute la base
        n_award_total_estime = int(len(marches) * ratio_award)
        print()
        print(f"  ── Extrapolation à la base entière ──")
        print(f"  Ratio ContractAwardNotice : {ratio_award:.1%}")
        print(f"  Estimation sur {len(marches)} marchés en base : "
              f"~{n_award_total_estime} avis d'attribution")
        print(f"  → soit ~{n_award_total_estime} entrées de pollution dans la base")

    # Verdict patch
    print(f"\n  ── Verdict patch ──")
    if n_award == 0:
        print(f"  ✓ Le filtre _est_avis_ouvert actuel suffit, pas d'attribution résiduelle.")
    elif n_award / n_boamp > 0.1:
        print(f"  ⚠ {n_award/n_boamp:.0%} des marchés BOAMP en base sont des attributions.")
        print(f"  → Patch recommandé : ajouter un check sur la branche eForms dans")
        print(f"    connecteurs/boamp.py / _est_avis_ouvert()")
        print(f"  → Et nettoyer la base existante (script one-shot)")
    else:
        print(f"  Quelques attributions résiduelles ({n_award}/{n_boamp}). "
              f"Patch utile mais pas urgent.")


if __name__ == "__main__":
    main()
