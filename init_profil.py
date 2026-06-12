"""
init_profil.py
--------------
Initialisation et migration du profil organisme Tendia.

Cohérent avec le positionnement POC "JSON config files manuel" : on n'a
pas de form web, on charge depuis un fichier JSON édité à la main.

Workflow typique :
    1. Générer un template pour mes secteurs :
         python init_profil.py --template btp > mon_profil.json
    2. Éditer mon_profil.json à la main (ou copier depuis l'exemple) :
         data/exemples/profil_btp_demo.json
    3. Importer dans la base :
         python init_profil.py --depuis mon_profil.json
    4. Vérifier :
         python organisme.py --check
"""

import argparse
import io
import json
import sys
from pathlib import Path

# Force UTF-8 stdout pour compat cp1252 PowerShell
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import organisme


def cmd_status():
    """Affiche l'état actuel du profil."""
    p = organisme.charger_actif()
    if p is None:
        print("Aucun profil en base.")
        print()
        print("Pour creer un profil, deux options :")
        print("  a) Generer un template + l'editer :")
        print("       python init_profil.py --template btp > mon_profil.json")
        print("       (puis editer mon_profil.json, puis --depuis)")
        print("  b) Importer un exemple existant :")
        print("       python init_profil.py --depuis data/exemples/profil_btp_demo.json")
        return
    legacy = organisme.est_format_legacy(p)
    if legacy:
        print("Profil EN PLACE (format LEGACY formation).")
        print(f"  raison_sociale : {p.get('identite', {}).get('nom') or '(vide)'}")
        print(f"  thematiques    : {len(p.get('thematiques_metiers') or [])} items")
        print(f"  prestations    : {len(p.get('prestations_maitrisees') or [])} items")
        print()
        print("Pour migrer vers le nouveau format multi-secteurs :")
        print("  1. python init_profil.py --purger --confirmer")
        print("  2. python init_profil.py --depuis <fichier_nouveau_format>.json")
    else:
        print("Profil EN PLACE (nouveau format multi-secteurs).")
        rs = p.get("identite", {}).get("raison_sociale") or "(vide)"
        print(f"  raison_sociale : {rs}")
        print(f"  presets        : {p.get('presets_couverts') or []}")
        for code in (p.get("presets_couverts") or []):
            ps = (p.get("profils_sectoriels") or {}).get(code) or {}
            n_keys = sum(1 for v in ps.values() if v not in (None, [], {}, ""))
            print(f"    - {code} : {n_keys} sections renseignees")
        rapport = organisme.valider_profil(p)
        cr = rapport["champs_remplis"]
        print(f"  remplissage socle : {cr['socle']*100:.0f}%")
        for code, r in cr["par_preset"].items():
            print(f"  remplissage {code} : {r*100:.0f}%")
        print(f"  valide : {'oui' if rapport['valide'] else 'NON (voir --check)'}")


def cmd_template(presets):
    """Affiche un template JSON pour les presets demandes."""
    try:
        tpl = organisme.template_profil_complet(presets)
    except ValueError as e:
        print(f"Erreur : {e}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(tpl, ensure_ascii=False, indent=2))


def cmd_depuis(chemin: str):
    """Importe un profil depuis un fichier JSON."""
    f = Path(chemin)
    if not f.exists():
        print(f"Fichier introuvable : {chemin}", file=sys.stderr)
        sys.exit(1)
    try:
        profil = json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"JSON invalide dans {chemin} : {e}", file=sys.stderr)
        sys.exit(1)

    existant = organisme.charger_actif()
    if existant is not None:
        legacy = organisme.est_format_legacy(existant)
        print(f"Un profil existe deja en base ({'legacy' if legacy else 'nouveau format'}).")
        print("Pour ecraser, lance d'abord :")
        print("  python init_profil.py --purger --confirmer")
        sys.exit(1)

    # Validation legere avant ecriture
    rapport = organisme.valider_profil(profil)
    if not rapport["valide"]:
        print("Le profil presente des erreurs de validation :")
        for e in rapport["erreurs"]:
            print(f"  X {e}")
        print()
        print("Pour ecrire quand meme (deconseille), ajoute --force.")
        if "--force" not in sys.argv:
            sys.exit(1)
        print("Ecriture forcee.")
    organisme.ecrire_profil(profil)
    print(f"OK Profil importe depuis {chemin}")
    cr = rapport["champs_remplis"]
    print(f"  remplissage socle : {cr['socle']*100:.0f}%")
    for code, r in cr["par_preset"].items():
        print(f"  remplissage {code} : {r*100:.0f}%")
    if rapport["warnings"]:
        print("  warnings :")
        for w in rapport["warnings"]:
            print(f"    ! {w}")


def cmd_purger():
    """Supprime le profil actuel."""
    existant = organisme.charger_actif()
    if existant is None:
        print("Aucun profil a supprimer.")
        return
    if "--confirmer" not in sys.argv:
        legacy = organisme.est_format_legacy(existant)
        print(f"Profil actuel ({'legacy' if legacy else 'nouveau format'}) :")
        rs = (existant.get("identite", {}).get("raison_sociale") or
              existant.get("identite", {}).get("nom") or "(sans nom)")
        print(f"  raison_sociale : {rs}")
        print()
        print("Pour confirmer la suppression : ajoute --confirmer")
        sys.exit(1)
    organisme.supprimer_profil()
    print("OK Profil supprime.")


def main():
    ap = argparse.ArgumentParser(
        description="Initialisation/migration du profil organisme Tendia.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--status", action="store_true",
                   help="Affiche l'etat du profil (defaut)")
    g.add_argument("--template", nargs="+", metavar="PRESET",
                   help="Genere un template JSON pour les presets (ex: --template btp)")
    g.add_argument("--depuis", metavar="FICHIER",
                   help="Importe un profil depuis un fichier JSON")
    g.add_argument("--purger", action="store_true",
                   help="Supprime le profil actuel (necessite --confirmer)")
    ap.add_argument("--confirmer", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--force", action="store_true",
                    help="(avec --depuis) Ecrire meme si validation echoue")
    args = ap.parse_args()

    if args.template:
        cmd_template(args.template)
    elif args.depuis:
        cmd_depuis(args.depuis)
    elif args.purger:
        cmd_purger()
    else:
        cmd_status()


if __name__ == "__main__":
    main()
