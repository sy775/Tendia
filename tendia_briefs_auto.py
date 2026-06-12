"""
tendia_briefs_auto.py
---------------------
Génération automatique de briefs LIGHT pour les marchés en base.

Workflow :
1. Lit data/marches.json
2. Pour chaque marché sans brief existant (ou avec brief LIGHT si --force),
   appelle auto_brief.generer_brief_light() qui interroge Sonnet 4.6 sur
   l'avis BOAMP.
3. Sauvegarde le brief dans data/extractions/<id>.json
4. Tag le brief avec _meta.type = "light" pour le distinguer des briefs
   COMPLETS produits par tendia_extraire.py sur le DCE.

PROTECTION ABSOLUE : un brief COMPLET (issu du DCE) ne sera JAMAIS
écrasé par ce script, même avec --force. Pour re-extraire un brief
complet, utiliser `tendia_extraire.py --force --marche <id>`.

Usage :
    python tendia_briefs_auto.py                 # tous les marchés sans brief
    python tendia_briefs_auto.py --force          # re-génère les briefs LIGHT
                                                  # (COMPLETS protégés)
    python tendia_briefs_auto.py --limit 5        # test sur 5 marchés
    python tendia_briefs_auto.py --marche <id>    # un seul (utile pour debug)
    python tendia_briefs_auto.py --dry-run        # compte sans appeler l'API

Coût estimé : ~3-5 cents par marché avec Sonnet 4.6.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

import auto_brief


REPERTOIRE_BASE = Path(__file__).parent
FICHIER_MARCHES = REPERTOIRE_BASE / "data" / "marches.json"
REPERTOIRE_EXTRACTIONS = REPERTOIRE_BASE / "data" / "extractions"

# Prix Sonnet 4.6 (à actualiser si changement)
PRIX_IN_PAR_MTOK = 3.0
PRIX_OUT_PAR_MTOK = 15.0
SAUVEGARDE_INTERVALLE = 1  # chaque brief est sauvegardé immédiatement


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _charger_marches() -> dict:
    if not FICHIER_MARCHES.is_file():
        raise FileNotFoundError(f"Fichier marchés introuvable : {FICHIER_MARCHES}")
    with open(FICHIER_MARCHES, encoding="utf-8") as f:
        return json.load(f)


def _charger_brief_existant(id_marche: str) -> Optional[dict]:
    chemin = REPERTOIRE_EXTRACTIONS / f"{id_marche}.json"
    if not chemin.is_file():
        return None
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _sauver_brief(id_marche: str, brief: dict):
    REPERTOIRE_EXTRACTIONS.mkdir(parents=True, exist_ok=True)
    chemin = REPERTOIRE_EXTRACTIONS / f"{id_marche}.json"
    tmp = chemin.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(brief, f, ensure_ascii=False, indent=2)
    tmp.replace(chemin)


# ---------------------------------------------------------------------------
# Boucle principale
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Génération automatique de briefs LIGHT pour les marchés.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--force", action="store_true",
                        help="Re-génère les briefs LIGHT existants. "
                             "Les briefs COMPLETS sont TOUJOURS protégés.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limite le nombre de marchés traités (test).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compte sans appeler l'API.")
    parser.add_argument("--marche", type=str, default=None,
                        help="Traite uniquement ce marché.")
    args = parser.parse_args()

    print("=" * 70)
    print(f"  Tendia · Génération automatique de briefs LIGHT")
    print(f"  Modèle : {auto_brief.MODELE}")
    print("=" * 70)
    print()

    marches = _charger_marches()
    print(f"  Marchés en base : {len(marches)}")

    # Filtrer la liste à traiter
    if args.marche:
        if args.marche not in marches:
            print(f"  ❌ Marché {args.marche} introuvable.")
            sys.exit(1)
        brief = _charger_brief_existant(args.marche)
        if brief and auto_brief.est_brief_complet(brief):
            print(f"  ⚠ Le marché {args.marche} a un brief COMPLET (depuis le DCE).")
            print(f"  Pour re-extraire un brief complet, utiliser :")
            print(f"      python tendia_extraire.py --force --marche {args.marche}")
            sys.exit(0)
        a_traiter = [args.marche]
    else:
        a_traiter = []
        nb_skip_complet = 0
        nb_skip_light = 0
        for id_m in marches:
            brief = _charger_brief_existant(id_m)
            if brief and auto_brief.est_brief_complet(brief):
                # COMPLET : toujours protégé, même avec --force
                nb_skip_complet += 1
                continue
            if brief and not args.force:
                # LIGHT existant, pas de --force → skip
                nb_skip_light += 1
                continue
            a_traiter.append(id_m)
        if args.limit:
            a_traiter = a_traiter[:args.limit]
        print(f"    ├─ briefs COMPLETS protégés    : {nb_skip_complet}")
        print(f"    ├─ briefs LIGHT skippés        : {nb_skip_light}  (relance avec --force)")
        print(f"    └─ à traiter ce run            : {len(a_traiter)}")

    if not a_traiter:
        print()
        print("  ✓ Rien à faire. Tous les marchés sont couverts.")
        return

    # Dry-run : décompte + estimation coût, on s'arrête
    if args.dry_run:
        # ~800 tokens in (avec objet moyen) + ~600 tokens out
        cout_estime = (len(a_traiter) * 800 * PRIX_IN_PAR_MTOK
                       + len(a_traiter) * 600 * PRIX_OUT_PAR_MTOK) / 1_000_000
        print()
        print(f"  [dry-run] {len(a_traiter)} briefs LIGHT seraient générés.")
        print(f"  Coût estimé : ~{cout_estime:.2f} $")
        return

    # Boucle d'extraction
    print()
    print("-" * 70)
    debut = time.time()
    nb_ok = 0
    nb_fail = 0
    total_in = 0
    total_out = 0

    for i, id_m in enumerate(a_traiter, 1):
        marche = marches[id_m]
        titre_court = (marche.get("titre") or marche.get("objet") or "")[:55].replace("\n", " ")
        progress = f"[{i:3d}/{len(a_traiter)}]"

        brief = auto_brief.generer_brief_light(marche, verbose=True)
        if brief is None:
            nb_fail += 1
            print(f"  {progress} ❌ {id_m}  échec  | {titre_court}")
            continue

        meta = brief.get("_meta", {})
        total_in += meta.get("tokens_in", 0)
        total_out += meta.get("tokens_out", 0)

        prest = brief.get("prestation_inferee", "?")
        synth = (brief.get("synthese_marche") or "")[:60].replace("\n", " ")

        _sauver_brief(id_m, brief)
        nb_ok += 1

        cout_courant = (total_in * PRIX_IN_PAR_MTOK
                        + total_out * PRIX_OUT_PAR_MTOK) / 1_000_000
        print(f"  {progress} ✓ {id_m}  prest={prest:<25s} | {synth}...")
        print(f"         tokens in/out: {meta.get('tokens_in')}/{meta.get('tokens_out')}  "
              f"cumul: ~{cout_courant:.3f}$")

    # Résumé
    duree_totale = time.time() - debut
    cout_total = (total_in * PRIX_IN_PAR_MTOK
                  + total_out * PRIX_OUT_PAR_MTOK) / 1_000_000

    print()
    print("-" * 70)
    print("  Résumé")
    print("-" * 70)
    print(f"    Marchés traités    : {len(a_traiter)}")
    print(f"      ✓ générés        : {nb_ok}")
    print(f"      ❌ échecs         : {nb_fail}")
    print(f"    Tokens consommés    : in {total_in:,} / out {total_out:,}")
    print(f"    Coût total          : ~{cout_total:.3f} $")
    print(f"    Durée               : {duree_totale:.0f} s "
          f"({duree_totale/max(1, nb_ok):.1f} s/marché)")
    print()
    print(f"  Briefs sauvegardés dans : {REPERTOIRE_EXTRACTIONS}")
    print()


if __name__ == "__main__":
    main()
