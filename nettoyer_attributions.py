"""
nettoyer_attributions.py
------------------------
Script one-shot : identifie et purge les marchés ContractAwardNotice
(avis d'attribution) déjà en base.

Ces marchés ne sont pas exploitables côté Tendia (ils sont déjà attribués,
plus rien à candidater). Le filtre `_est_avis_ouvert` actuel de
connecteurs/boamp.py les laissait passer (~24% de la base = ~120 entrées
sur 500). Ce script :

1. Ré-interroge BOAMP pour chaque marché en base
2. Identifie les ContractAwardNotice via la branche eForms
3. Affiche le compte (dry-run par défaut)
4. Avec --appliquer : supprime de `marches` ET de `scores_matching`
   (qui contient 2 scores par marché — un par preset)
5. (Optionnel --vers-attribution) : marque comme "exclu_attribution"
   au lieu de supprimer, pour audit

Usage :
    python nettoyer_attributions.py --dry-run        # voir le compte
    python nettoyer_attributions.py --appliquer      # supprimer
    python nettoyer_attributions.py --appliquer --vers-attribution
                                                      # marquer au lieu de supprimer

Pré-requis : patch boamp.py déjà appliqué (sinon les nouveaux ContractAwardNotice
ingérés ré-apparaîtront).
"""

import argparse
import io
import sys
import time
from collections import Counter

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import dce_finder


def _branche_eforms_from_record(record: dict) -> str:
    """Détermine la branche eForms depuis le payload BOAMP."""
    if not record:
        return "(404)"
    donnees = dce_finder._parser_donnees(record)
    eforms = donnees.get("EFORMS") or {}
    for branche in ("ContractAwardNotice", "ContractNotice",
                     "PriorInformationNotice"):
        if branche in eforms:
            return branche
    return "(aucune)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", default=True,
                    help="Affiche sans modifier (défaut)")
    ap.add_argument("--appliquer", action="store_true",
                    help="Applique réellement les suppressions")
    ap.add_argument("--vers-attribution", action="store_true",
                    help="Au lieu de supprimer, marque les marchés comme "
                         "'exclu_attribution' (pour audit)")
    ap.add_argument("--limite", type=int, default=None,
                    help="Cap le nombre de marchés analysés")
    args = ap.parse_args()

    # Si --appliquer, désactive le dry-run par défaut
    if args.appliquer:
        args.dry_run = False

    print("=" * 78)
    print("  Nettoyage des avis d'attribution (ContractAwardNotice) en base")
    print("=" * 78)
    if args.dry_run:
        print("  Mode DRY-RUN : aucune modification.")

    marches = stockage.charger("marches") or {}
    scores = stockage.charger("scores_matching") or {}

    boamp_marches = {id_m: m for id_m, m in marches.items()
                     if m.get("source") == "BOAMP"}
    print(f"\n  Marchés BOAMP en base : {len(boamp_marches)}")

    if args.limite:
        ids = sorted(boamp_marches.keys())[:args.limite]
        boamp_marches = {id_m: boamp_marches[id_m] for id_m in ids}
        print(f"  (limité à {args.limite})")

    print()
    print("  Interrogation BOAMP marché par marché (peut prendre quelques minutes)...")

    branches = Counter()
    a_supprimer = []  # IDs des ContractAwardNotice
    erreurs = 0
    t0 = time.time()

    for i, (id_m, m) in enumerate(sorted(boamp_marches.items()), 1):
        if i % 20 == 0:
            elapsed = time.time() - t0
            eta = elapsed / i * (len(boamp_marches) - i)
            print(f"    ... {i}/{len(boamp_marches)}  ({elapsed:.0f}s écoulé, "
                  f"ETA {eta:.0f}s)")

        ref = m.get("reference_externe", "")
        try:
            record = dce_finder._fetch_record_boamp(ref)
            branche = _branche_eforms_from_record(record)
        except Exception as e:
            branches["(erreur)"] += 1
            erreurs += 1
            continue

        branches[branche] += 1
        if branche == "ContractAwardNotice":
            a_supprimer.append(id_m)

    # Synthèse
    print()
    print("-" * 78)
    print(f"  Résultats sur {sum(branches.values())} marchés ré-interrogés")
    print("-" * 78)
    for b, n in branches.most_common():
        pct = n * 100 / sum(branches.values())
        marker = " ⚠ à purger" if b == "ContractAwardNotice" else ""
        print(f"    {b:<28} : {n:4d} ({pct:5.1f}%){marker}")
    if erreurs:
        print(f"    {'(erreurs reseau)':<28} : {erreurs}")

    if not a_supprimer:
        print(f"\n  ✓ Aucun ContractAwardNotice à purger.")
        return

    # Comptage des scores impactés
    scores_impactes = []
    for id_m in a_supprimer:
        for cle, sc in scores.items():
            if not isinstance(sc, dict):
                continue
            # Plusieurs formats possibles selon historique
            cle_match = (
                cle == id_m or
                cle.startswith(id_m + "_") or
                (isinstance(sc, dict) and sc.get("marche_id") == id_m)
            )
            if cle_match:
                scores_impactes.append(cle)

    print(f"\n  ── Plan ──")
    print(f"  Marchés ContractAwardNotice à traiter : {len(a_supprimer)}")
    print(f"  Scores matching associés              : {len(scores_impactes)}")

    if args.dry_run:
        print()
        print("  Aperçu (15 premiers IDs) :")
        for id_m in a_supprimer[:15]:
            m = boamp_marches[id_m]
            titre = (m.get("titre") or "?")[:55]
            print(f"    {id_m}  {titre}")
        if len(a_supprimer) > 15:
            print(f"    ... +{len(a_supprimer) - 15}")
        print()
        print("  → Pour appliquer : python nettoyer_attributions.py --appliquer")
        print("    (ajoute --vers-attribution pour MARQUER au lieu de supprimer)")
        return

    # Application
    print()
    if args.vers_attribution:
        print(f"  → Marquage en cours (exclu_attribution)...")
        for id_m in a_supprimer:
            marches[id_m]["statut_tendia"] = "exclu_attribution"
            marches[id_m]["date_exclusion"] = time.strftime("%Y-%m-%d %H:%M:%S")
        stockage.sauver("marches", marches)
        # Note : on garde les scores aussi pour audit, ils n'apparaitront
        # plus dans le dashboard via le filtre statut_tendia.
        print(f"  ✓ {len(a_supprimer)} marchés marqués 'exclu_attribution'.")
    else:
        print(f"  → Suppression en cours...")
        for id_m in a_supprimer:
            del marches[id_m]
        for cle in scores_impactes:
            if cle in scores:
                del scores[cle]
        stockage.sauver("marches", marches)
        stockage.sauver("scores_matching", scores)
        print(f"  ✓ {len(a_supprimer)} marchés supprimés.")
        print(f"  ✓ {len(scores_impactes)} scores de matching purgés.")

    print()
    print(f"  Distribution finale :")
    statuts = Counter()
    for m in marches.values():
        statuts[m.get("statut_tendia") or "(actif)"] += 1
    for s, n in statuts.most_common():
        print(f"    {s:<28} : {n}")

    print()
    print(f"  ── Prochaine étape ──")
    print(f"  Relancer le matching pour mise à jour des stats pertinentes :")
    print(f"    python analyse.py")


if __name__ == "__main__":
    main()
