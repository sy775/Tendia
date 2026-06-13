"""
tester_profils.py
-----------------
Charge un profil organisme depuis profils_test/, lance le matching personnel
sur les marchés pertinents, et affiche un comparatif des verdicts.

Le matching multi-preset (qui détermine les 27 pertinents) ne dépend pas du
profil. Mais le matching personnel via matching.evaluer() utilise le profil
pour calculer un verdict (très_pertinent / pertinent / à_vérifier /
non_pertinent) et un score, qui pilotent le tri du dashboard.

Usage :
    python tester_profils.py                       # liste les profils
    python tester_profils.py 1                     # charge le profil #1
    python tester_profils.py --comparer            # teste TOUS les profils
                                                    # sans persistance, juste
                                                    # affichage comparatif
    python tester_profils.py --backup              # sauve le profil actuel
    python tester_profils.py --restaurer           # restaure le backup
"""

import argparse
import io
import json
import sys
from collections import Counter
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import organisme
import matching
import stockage


REPERTOIRE_PROFILS = Path(__file__).parent / "profils_test"
CHEMIN_BACKUP = REPERTOIRE_PROFILS / "_backup_profil_actuel.json"


def lister_profils() -> list:
    """Retourne la liste triée des fichiers profil JSON (hors backup)."""
    if not REPERTOIRE_PROFILS.exists():
        return []
    return sorted(p for p in REPERTOIRE_PROFILS.glob("*.json")
                  if not p.name.startswith("_"))


def afficher_liste():
    print("\n  ── Profils disponibles ──\n")
    profils = lister_profils()
    if not profils:
        print(f"  Aucun profil dans {REPERTOIRE_PROFILS}")
        return
    for i, chemin in enumerate(profils, 1):
        try:
            data = json.loads(chemin.read_text(encoding="utf-8"))
            nom = data.get("identite", {}).get("nom") or "(sans nom)"
            them = data.get("thematiques_metiers", [])
            them_short = ", ".join(them[:3])
            if len(them) > 3:
                them_short += f" (+{len(them) - 3})"
            print(f"    [{i}] {chemin.name}")
            print(f"        nom         : {nom}")
            print(f"        thématiques : {them_short or '—'}")
            print()
        except Exception as e:
            print(f"    [{i}] {chemin.name}  ⚠ erreur : {e}")
    print(f"  Usage : python tester_profils.py <numéro>")
    print(f"          python tester_profils.py --comparer\n")


def charger_profil_n(n: int) -> dict | None:
    """Charge le profil n° N (1-indexé) depuis profils_test/."""
    profils = lister_profils()
    if not (1 <= n <= len(profils)):
        print(f"  ❌ Numéro {n} invalide. Profils disponibles : 1-{len(profils)}")
        return None
    chemin = profils[n - 1]
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ❌ Erreur lecture {chemin.name} : {e}")
        return None


def appliquer_profil(profil: dict):
    """Sauvegarde le profil en base et affiche un récap."""
    organisme.ecrire_profil(profil)
    iden = profil.get("identite", {})
    print(f"\n  ✓ Profil appliqué : {iden.get('nom') or '(sans nom)'}")
    print(f"    Siège        : {iden.get('siege_ville') or '—'} "
          f"({iden.get('siege_code_postal') or '?'})")
    print(f"    Effectif     : {iden.get('effectif_total') or '—'}")
    print(f"    Régions      : {', '.join(profil.get('directions_regionales_couvertes') or []) or '—'}")
    print(f"    Thématiques  : {len(profil.get('thematiques_metiers') or [])}")
    print(f"    Mots-clés    : {len(profil.get('mots_cles_catalogue') or [])}")


def stats_verdicts(profil: dict, marches: dict, ids_pertinents: set) -> dict:
    """
    Calcule la distribution des verdicts pour un profil donné, sur les
    marchés pertinents (ceux qui matchent au moins un preset).
    """
    verdicts = Counter()
    top_3 = []
    for id_m in ids_pertinents:
        m = marches.get(id_m)
        if not m:
            continue
        try:
            eval_r = matching.evaluer(profil, m)
        except Exception:
            verdicts["erreur"] += 1
            continue
        v = (eval_r or {}).get("verdict") or "non_pertinent"
        score = (eval_r or {}).get("score") or 0
        verdicts[v] += 1
        top_3.append((score, m.get("titre") or "?", v))
    top_3.sort(reverse=True)
    return {"verdicts": dict(verdicts), "top_3": top_3[:3]}


def mode_comparer():
    """Teste tous les profils sans modifier la base, affiche comparatif."""
    print("\n  ── Mode comparaison ──")
    print("  (Aucune modification de la base — affichage seulement)\n")

    marches = stockage.charger("marches") or {}
    scores = stockage.charger("scores_matching") or {}

    # Identifie les pertinents (matche ≥1 preset)
    pertinents = set()
    for cle, sc in scores.items():
        if isinstance(sc, dict) and sc.get("matche"):
            id_m = sc.get("marche_id") or cle
            pertinents.add(id_m)
    print(f"  Marchés en base       : {len(marches)}")
    print(f"  Pertinents (multi-preset, indépendant du profil) : {len(pertinents)}\n")

    profils = lister_profils()
    if not profils:
        print(f"  Aucun profil dans {REPERTOIRE_PROFILS}")
        return

    # En-tête tableau
    print(f"  {'Profil':<45}  {'TP':>3}  {'P':>3}  {'AV':>3}  {'NP':>3}")
    print(f"  {'-' * 45}  {'---':>3}  {'-':>3}  {'--':>3}  {'--':>3}")

    resultats = []
    for chemin in profils:
        try:
            profil = json.loads(chemin.read_text(encoding="utf-8"))
        except Exception:
            continue
        nom = (profil.get("identite", {}).get("nom") or chemin.stem)[:43]
        s = stats_verdicts(profil, marches, pertinents)
        v = s["verdicts"]
        print(f"  {nom:<45}  "
              f"{v.get('tres_pertinent', 0):>3}  "
              f"{v.get('pertinent', 0):>3}  "
              f"{v.get('a_verifier', 0):>3}  "
              f"{v.get('non_pertinent', 0):>3}")
        resultats.append((nom, s))

    print(f"\n  Légende : TP=très_pertinent, P=pertinent, AV=à_vérifier, NP=non_pertinent")
    print()

    # Top 3 par profil
    print(f"  ── Top 3 marchés (par score) pour chaque profil ──\n")
    for nom, s in resultats:
        print(f"  • {nom}")
        for score, titre, v in s["top_3"]:
            titre_short = (titre[:80] + "…") if len(titre) > 80 else titre
            print(f"      [{score:>3}] {v:<16}  {titre_short}")
        if not s["top_3"]:
            print(f"      (aucun marché évaluable)")
        print()


def backup_profil_actuel() -> bool:
    """Sauve le profil actuel dans _backup_profil_actuel.json."""
    actuel = organisme.lire_profil()
    if not actuel:
        print(f"  ⚠ Aucun profil en base, rien à sauvegarder.")
        return False
    REPERTOIRE_PROFILS.mkdir(parents=True, exist_ok=True)
    CHEMIN_BACKUP.write_text(
        json.dumps(actuel, ensure_ascii=False, indent=2),
        encoding="utf-8")
    nom = actuel.get("identite", {}).get("nom") or "(sans nom)"
    print(f"  ✓ Profil actuel sauvegardé : {nom}")
    print(f"    → {CHEMIN_BACKUP}")
    return True


def restaurer_backup() -> bool:
    """Restaure le profil depuis _backup_profil_actuel.json."""
    if not CHEMIN_BACKUP.is_file():
        print(f"  ❌ Aucun backup trouvé : {CHEMIN_BACKUP}")
        return False
    try:
        data = json.loads(CHEMIN_BACKUP.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ❌ Backup illisible : {e}")
        return False
    organisme.ecrire_profil(data)
    nom = data.get("identite", {}).get("nom") or "(sans nom)"
    print(f"  ✓ Profil restauré : {nom}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("numero", nargs="?", type=int,
                    help="Numéro du profil à charger")
    ap.add_argument("--comparer", action="store_true",
                    help="Affiche un comparatif de tous les profils "
                         "(sans modifier la base)")
    ap.add_argument("--backup", action="store_true",
                    help="Sauvegarde le profil actuel dans "
                         "profils_test/_backup_profil_actuel.json")
    ap.add_argument("--restaurer", action="store_true",
                    help="Restaure le profil depuis le backup")
    args = ap.parse_args()

    if args.backup:
        backup_profil_actuel()
        return

    if args.restaurer:
        restaurer_backup()
        return

    if args.comparer:
        mode_comparer()
        return

    if args.numero is None:
        afficher_liste()
        return

    # Chargement d'un profil
    profil = charger_profil_n(args.numero)
    if profil is None:
        return

    # Backup auto avant écrasement si un profil existe
    existant = organisme.lire_profil()
    if existant and not CHEMIN_BACKUP.is_file():
        print(f"  ℹ Backup automatique du profil actuel avant écrasement")
        backup_profil_actuel()

    appliquer_profil(profil)
    print()
    print(f"  ── Prochaine étape ──")
    print(f"  Ouvrir le dashboard pour voir les marchés triés selon ce profil :")
    print(f"    python tendia_ui.py")
    print(f"  ou comparer tous les profils en une commande :")
    print(f"    python tester_profils.py --comparer")


if __name__ == "__main__":
    main()
