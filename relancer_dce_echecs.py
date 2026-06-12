"""
relancer_dce_echecs.py
----------------------
Relance le téléchargement DCE uniquement sur les marchés en statut `echec`,
en excluant par défaut les "murs" connus (login requis, captcha, faux succès
déjà nettoyés). Utile après un patch du téléchargeur pour récolter le gain
sans re-traîter tous les marchés.

Filtres possibles :
  --filtre-domaine SUBSTRING   ne relance que les url_dce contenant SUBSTRING
                                (ex : --filtre-domaine e-marchespublics)
  --exclure-raison SUBSTRING   exclut les marchés dont la raison contient SUBSTRING
                                (cumulable, défaut: login + captcha + faux_succes)

Usage typique après le patch Phase 2a :
    python relancer_dce_echecs.py --filtre-domaine e-marchespublics --verbose
    python relancer_dce_echecs.py --dry-run            # voir ce qui serait fait
    python relancer_dce_echecs.py                       # tous les échecs hors murs
"""

import argparse
import io
import sys
import time
from datetime import datetime, timezone

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import requests

import stockage
import tendia_telecharger_dce as tdce


# Murs connus à exclure par défaut (pour éviter de re-tenter inutilement).
# `dossier_vide_nettoye` est volontairement absent : ces marchés avec url_dce
# sont d'anciens échecs qui méritent une nouvelle tentative après un patch.
# `dossier_vide_apres_test` = nom propre après réparation (cf reparer_statuts.py).
EXCLUSIONS_PAR_DEFAUT = (
    "login requis",
    "captcha",
    "faux_succes",
    "espace acheteur",   # url_dce côté agent (filtrée maintenant en amont)
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--filtre-domaine", default=None,
                    help="Ne relance que les url_dce contenant cette chaîne.")
    ap.add_argument("--exclure-raison", action="append", default=[],
                    help="Exclut les raisons matchant (cumulable). "
                         f"Défaut : {EXCLUSIONS_PAR_DEFAUT}")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap le nombre de marchés relancés.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Affiche seulement les cibles, ne télécharge pas.")
    ap.add_argument("--verbose", action="store_true",
                    help="Détail HTTP par marché.")
    args = ap.parse_args()

    exclusions = tuple(args.exclure_raison) if args.exclure_raison else EXCLUSIONS_PAR_DEFAUT

    print("=" * 70)
    print("  Relance ciblée des téléchargements DCE en échec")
    print("=" * 70)
    if args.filtre_domaine:
        print(f"  Filtre domaine    : {args.filtre_domaine}")
    print(f"  Exclusions raison : {', '.join(exclusions)}")
    if args.dry_run:
        print(f"  MODE DRY-RUN : aucun téléchargement.")
    print()

    marches = stockage.charger("marches")
    cibles = []
    nb_total_echec = 0
    for id_m, m in marches.items():
        if m.get("dce_telechargement_statut") != "echec":
            continue
        nb_total_echec += 1
        if not m.get("url_dce"):
            continue
        if args.filtre_domaine and args.filtre_domaine not in (m.get("url_dce") or ""):
            continue
        raison = (m.get("dce_telechargement_raison") or "").lower()
        if any(excl.lower() in raison for excl in exclusions):
            continue
        cibles.append((id_m, m))

    if args.limit:
        cibles = cibles[:args.limit]

    print(f"  Marchés en échec total : {nb_total_echec}")
    print(f"  Cibles éligibles ce run : {len(cibles)}")
    print()

    if not cibles:
        print("  Rien à faire.")
        return

    if args.dry_run:
        print("  Aperçu (max 30) :")
        for id_m, m in cibles[:30]:
            url = (m.get("url_dce") or "")[:75]
            print(f"    {id_m}  {url}")
        return

    # Session HTTP partagée
    session = requests.Session()
    session.headers.update({
        "User-Agent": tdce.USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
    })

    horodatage = datetime.now(timezone.utc).isoformat()
    stats = {}
    debut = time.time()

    for i, (id_m, m) in enumerate(cibles, 1):
        titre = (m.get("titre") or m.get("objet") or "?")[:50]
        print(f"  [{i:3d}/{len(cibles)}] {id_m}  · {titre}")
        result = tdce._telecharger_marche(
            m, session, force=True, dry_run=False, verbose=args.verbose
        )
        statut = result.get("statut", "?")
        nb_f = result.get("nb_fichiers", 0)
        raison = result.get("raison", "")
        stats[statut] = stats.get(statut, 0) + 1

        if statut == "ok":
            print(f"            ✓ {nb_f} fichiers")
        elif statut == "manuel_requis":
            print(f"            ⚠ manuel requis : {raison[:60]}")
        else:
            print(f"            ❌ {statut} : {raison[:60]}")

        # MAJ marché
        m["dce_telechargement_statut"] = statut
        m["dce_telechargement_raison"] = raison
        m["dce_telechargement_nb_fichiers"] = nb_f
        m["dce_telechargement_date"] = horodatage

    # Sauve une fois à la fin
    stockage.sauver("marches", marches)

    duree = time.time() - debut
    print()
    print("-" * 70)
    print("  Résumé")
    print("-" * 70)
    for k, v in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"    {k:<18} : {v}")
    print(f"    Durée            : {duree:.0f} s")


if __name__ == "__main__":
    main()
