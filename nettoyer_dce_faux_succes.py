"""
nettoyer_dce_faux_succes.py
---------------------------
Script one-shot d'hygiène pour la collection `data/dce/` et la base SQLite.

Contexte : un premier batch de tendia_telecharger_dce.py a créé 86 dossiers DCE
contenant uniquement des fichiers génériques servis par les plateformes
(guide AW Solutions / DEMATIS `depot-pli.pdf`, formulaire `DUME Acheteur.zip`,
`cgu_*.pdf`), sans le vrai règlement de consultation. Ces dossiers sont
référencés `dce_telechargement_statut = 'ok'` en base, ce qui pollue le
pipeline aval (analyse, extraction LLM).

Ce script :
1. Parcourt tous les dossiers `data/dce/<id>/`
2. Pour chaque dossier, classifie les fichiers présents :
     - fichiers utiles    : ni guide générique, ni DUME seul, ni CGU
     - fichiers bruit     : dans la liste noire `FICHIERS_BRUIT`
3. Si AUCUN fichier utile et au moins un fichier bruit :
     - Supprime le dossier
     - Met à jour le marché en base : statut = 'faux_succes_<motif>',
       raison = liste des fichiers bruit trouvés
4. Si le dossier est vide :
     - Le supprime
     - Met à jour le marché : statut = 'echec', raison = 'dossier vide'
5. Mode --dry-run pour prévisualiser sans rien toucher.

Usage :
    python nettoyer_dce_faux_succes.py --dry-run    # diagnostic
    python nettoyer_dce_faux_succes.py              # vrai nettoyage
"""

import argparse
import io
import re
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 sur stdout (Windows cp1252)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import stockage


REPERTOIRE_DCE = Path(__file__).parent / "data" / "dce"

# Fichiers exacts à considérer comme bruit (servis avant l'accès au vrai DCE).
# Source : analyse du batch du 10/06/2026 sur 499 dossiers, dont 86 ne
# contenaient que ces fichiers (80 depot-pli, 4 DUME seul, 2 CGU).
FICHIERS_BRUIT_EXACT = {
    "depot-pli.pdf",          # Guide AW Solutions / DEMATIS (servi avant captcha)
    "DUME Acheteur.zip",      # Formulaire DUME européen générique
}

# Patterns regex (sur le nom de fichier) considérés comme bruit
PATTERNS_BRUIT = (
    re.compile(r"^cgu[_\-]", re.IGNORECASE),  # cgu_1-1.pdf, cgu-conditions.pdf, etc.
)


def _est_fichier_bruit(nom: str) -> bool:
    """True si le nom de fichier correspond à un fichier générique sans valeur DCE."""
    if nom in FICHIERS_BRUIT_EXACT:
        return True
    return any(p.search(nom) for p in PATTERNS_BRUIT)


def _classifier_dossier(dossier: Path):
    """
    Retourne (fichiers_utiles, fichiers_bruit) pour un dossier DCE.

    fichiers_utiles : list[str] des noms qui ne sont pas du bruit
    fichiers_bruit  : list[str] des noms classés comme bruit
    """
    utiles, bruit = [], []
    if not dossier.is_dir():
        return utiles, bruit
    for f in dossier.iterdir():
        if not f.is_file():
            continue
        if _est_fichier_bruit(f.name):
            bruit.append(f.name)
        else:
            utiles.append(f.name)
    return utiles, bruit


def main():
    parser = argparse.ArgumentParser(
        description="Nettoie les dossiers DCE contenant uniquement des fichiers génériques.",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Affiche ce qui serait fait sans rien modifier.")
    parser.add_argument("--verbose", action="store_true",
                        help="Liste chaque marché traité.")
    args = parser.parse_args()

    print("=" * 78)
    print("  Tendia · Nettoyage des faux succès DCE")
    print("=" * 78)
    if args.dry_run:
        print("  Mode dry-run : aucun fichier ne sera supprimé, aucune écriture en base.")
    print()

    if not REPERTOIRE_DCE.is_dir():
        print(f"  ❌ Répertoire introuvable : {REPERTOIRE_DCE}")
        sys.exit(1)

    marches = stockage.charger("marches")
    print(f"  Marchés en base       : {len(marches)}")

    dossiers = sorted(d for d in REPERTOIRE_DCE.iterdir() if d.is_dir())
    print(f"  Dossiers DCE sur disque : {len(dossiers)}")
    print()

    stats = Counter()
    a_marquer_en_base = []  # list[(id, nouveau_statut, raison)]
    a_supprimer = []        # list[Path]

    for dossier in dossiers:
        id_m = dossier.name
        utiles, bruit = _classifier_dossier(dossier)

        if utiles:
            # Au moins un fichier utile : on garde tout
            stats["conserve_avec_fichiers_utiles"] += 1
            if args.verbose:
                print(f"  ✓ KEEP  {id_m} : {len(utiles)} utile(s), {len(bruit)} bruit")
            continue

        if not bruit:
            # Dossier vide
            stats["supprime_dossier_vide"] += 1
            a_supprimer.append(dossier)
            a_marquer_en_base.append(
                (id_m, "echec", "dossier_vide_nettoye")
            )
            if args.verbose:
                print(f"  ✗ EMPTY {id_m} : dossier vide")
            continue

        # Que du bruit : faux succès à nettoyer
        # Identifie le motif principal pour le statut
        if "depot-pli.pdf" in bruit:
            motif = "faux_succes_depot_pli"
        elif "DUME Acheteur.zip" in bruit:
            motif = "faux_succes_dume_seul"
        else:
            motif = "faux_succes_cgu_ou_generique"

        stats[motif] += 1
        a_supprimer.append(dossier)
        a_marquer_en_base.append(
            (id_m, "echec", f"{motif}: {', '.join(bruit)}")
        )
        if args.verbose:
            print(f"  ✗ {motif[:25]:<25} {id_m} : {', '.join(bruit)}")

    print()
    print("-" * 78)
    print("  Bilan diagnostic")
    print("-" * 78)
    for k, v in stats.most_common():
        print(f"    {k:<35} : {v}")
    print()

    if args.dry_run:
        print("  → Dry-run terminé. Pour appliquer :")
        print("      python nettoyer_dce_faux_succes.py")
        return

    if not a_supprimer:
        print("  ✓ Rien à nettoyer. Tout est propre.")
        return

    # --- Application ---
    print(f"  Suppression de {len(a_supprimer)} dossier(s) DCE...")
    nb_supp_ok = 0
    erreurs_supp = []
    for d in a_supprimer:
        try:
            shutil.rmtree(d)
            nb_supp_ok += 1
        except OSError as e:
            erreurs_supp.append((d.name, str(e)))
    print(f"    ✓ {nb_supp_ok} dossiers supprimés")
    if erreurs_supp:
        print(f"    ⚠ {len(erreurs_supp)} erreurs de suppression :")
        for nom, err in erreurs_supp[:5]:
            print(f"        · {nom} : {err}")

    print()
    print(f"  Mise à jour de {len(a_marquer_en_base)} marché(s) en base...")
    horodatage = datetime.now(timezone.utc).isoformat()
    nb_maj = 0
    for id_m, statut, raison in a_marquer_en_base:
        m = marches.get(id_m)
        if not m:
            continue
        m["dce_telechargement_statut"] = statut
        m["dce_telechargement_raison"] = raison
        m["dce_telechargement_nb_fichiers"] = 0
        m["dce_telechargement_date"] = horodatage
        nb_maj += 1
    stockage.sauver("marches", marches)
    print(f"    ✓ {nb_maj} marchés mis à jour en SQLite")

    print()
    print("  Terminé. Tu peux maintenant relancer le pipeline aval sur une base propre.")
    print()


if __name__ == "__main__":
    main()
