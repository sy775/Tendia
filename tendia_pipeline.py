"""
tendia_pipeline.py
------------------
Orchestrateur du pipeline Tendia COMPLET et AUTOMATIQUE.

Une seule commande :
    python tendia_pipeline.py

Enchainement :
1. tendia_recup        : récupère les nouveaux avis BOAMP + TED
2. tendia_dce          : résout les URLs DCE (eForms + PLACE keyWord)
3. place_downloader    : télécharge anonymement les zips DCE depuis PLACE
4. tendia_extraire     : auto-dézip + extraction LLM (Claude Sonnet 4.6)
5. génération rapport final marches_actifs_<date>.md

Aucune intervention humaine.

Options :
    --skip-recup       : passe l'étape récupération (utilise la base actuelle)
    --skip-download    : passe l'étape téléchargement PLACE (PDFs déjà déposés)
    --skip-llm         : passe l'étape extraction LLM (économiser des appels API)
    --jours N          : fenêtre marchés sans date limite (défaut: 60)
"""

import argparse
import os
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

REPERTOIRE_BASE = Path(__file__).parent
REPERTOIRE_DCE = REPERTOIRE_BASE / "data" / "dce"


def _est_actif(marche: dict, fenetre_jours: int = 60) -> bool:
    date_lim = marche.get("date_limite_depot")
    today = date.today().isoformat()
    if date_lim and len(date_lim) >= 10:
        return date_lim[:10] >= today
    date_pub = marche.get("date_publication")
    if not date_pub or len(date_pub) < 10:
        return False
    try:
        d = date.fromisoformat(date_pub[:10])
        return (date.today() - d).days <= fenetre_jours
    except ValueError:
        return False


def _print_etape(num: int, titre: str, total: int = 5):
    print()
    print("─" * 78)
    print(f"  [{num}/{total}]  {titre}")
    print("─" * 78)


def _executer_script(script_name: str, args: list[str] = None) -> bool:
    """Lance un script Tendia comme sous-processus. Retourne True si OK."""
    args = args or []
    cmd = [sys.executable, script_name] + args
    print(f"\n  → Exécution : python {script_name} {' '.join(args)}")
    print()
    debut = time.time()
    try:
        result = subprocess.run(cmd, check=False)
        duree = round(time.time() - debut, 1)
        if result.returncode == 0:
            print(f"\n  ✅ {script_name} terminé en {duree}s")
            return True
        else:
            print(f"\n  ⚠ {script_name} terminé avec code {result.returncode} "
                  f"en {duree}s")
            return False
    except Exception as e:
        print(f"\n  ❌ Erreur lancement {script_name} : {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Tendia — Pipeline complet automatique",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--skip-recup", action="store_true",
                        help="Passe l'étape récupération BOAMP/TED")
    parser.add_argument("--skip-download", action="store_true",
                        help="Passe l'étape téléchargement PLACE")
    parser.add_argument("--skip-llm", action="store_true",
                        help="Passe l'étape extraction LLM")
    parser.add_argument("--force", action="store_true",
                        help="Force la re-extraction LLM même si déjà fait")
    parser.add_argument("--jours", type=int, default=60,
                        help="Fenêtre marchés sans date limite (défaut: 60)")
    args = parser.parse_args()

    debut_global = time.time()

    print("=" * 78)
    print()
    print("           A P P T I A   —   P I P E L I N E   C O M P L E T")
    print()
    print(f"           {datetime.now().strftime('%A %d %B %Y · %Hh%M').lower()}")
    print()
    print("=" * 78)

    # === Étape 1 : Récupération BOAMP + TED ===
    if args.skip_recup:
        print("\n  [1/5]  Récupération BOAMP/TED  →  SKIPPÉ (--skip-recup)")
    else:
        _print_etape(1, "Récupération avis BOAMP + TED")
        _executer_script("tendia_recup.py")

    # === Étape 2 : Résolution URLs DCE ===
    _print_etape(2, "Résolution URLs DCE (eForms + PLACE keyWord)")
    _executer_script("tendia_dce.py", ["--jours", str(args.jours)])

    # === Étape 3 : Téléchargement automatique des DCE depuis PLACE ===
    if args.skip_download:
        print("\n  [3/5]  Téléchargement DCE PLACE  →  SKIPPÉ (--skip-download)")
    else:
        _print_etape(3, "Téléchargement automatique des DCE depuis PLACE")
        _telecharger_dce_marches_actifs(args.jours)

    # === Étape 4 : Extraction LLM ===
    if args.skip_llm:
        print("\n  [4/5]  Extraction LLM  →  SKIPPÉ (--skip-llm)")
    else:
        _print_etape(4, "Extraction LLM des DCE (Claude Sonnet 4.6)")
        args_extract = ["--force"] if args.force else []
        _executer_script("tendia_extraire.py", args_extract)

    # === Étape 5 : Rapport final ===
    _print_etape(5, "Génération du rapport final")
    _executer_script("tendia_dce.py", ["--jours", str(args.jours),
                                         "--rapport-seul"])

    duree_totale = round(time.time() - debut_global, 1)
    duree_min = int(duree_totale // 60)
    duree_sec = int(duree_totale % 60)

    print()
    print("=" * 78)
    print()
    print(f"           ✅  PIPELINE TERMINÉ  ·  durée totale : {duree_min}m{duree_sec}s")
    print()
    print(f"           Rapport : rapports\\marches_actifs_{date.today()}.md")
    print(f"           UI      : python tendia_ui.py  →  http://localhost:5000")
    print()
    print("=" * 78)


def _telecharger_dce_marches_actifs(fenetre_jours: int):
    """Télécharge le zip DCE pour chaque marché actif avec URL résolue."""
    try:
        import stockage
        import place_downloader
    except ImportError as e:
        print(f"\n  ❌ Modules manquants : {e}")
        return

    marches = stockage.charger("marches")
    if not marches:
        print("\n  ⚠ Aucun marché en base.")
        return

    actifs = [m for m in marches.values() if _est_actif(m, fenetre_jours)]
    actifs_avec_url = [m for m in actifs if m.get("url_dce")
                          and m.get("dce_qualite") in ("directe", "via_keyword")]

    if not actifs_avec_url:
        print("\n  ℹ Aucun marché actif avec URL DCE résolue.")
        return

    print(f"\n  {len(actifs_avec_url)} marché(s) actif(s) avec URL DCE :")
    for m in actifs_avec_url:
        titre = (m.get("titre") or m.get("objet") or "?")[:65]
        print(f"    - {m['id']:<25} {titre}")

    print()
    stats = {"ok": 0, "skip": 0, "echec": 0}
    for marche in actifs_avec_url:
        resultat = place_downloader.telecharger_dce_pour_marche(
            marche, str(REPERTOIRE_DCE), verbose=True
        )
        if resultat.get("ok"):
            if resultat.get("skip"):
                stats["skip"] += 1
            else:
                stats["ok"] += 1
        else:
            stats["echec"] += 1
            print(f"    ⚠ {resultat.get('id_marche')} : "
                  f"{resultat.get('erreur')}")

    print()
    print(f"  Bilan téléchargement PLACE :")
    print(f"    Nouveaux zips     : {stats['ok']}")
    print(f"    Déjà présents     : {stats['skip']}")
    print(f"    Échecs            : {stats['echec']}")


if __name__ == "__main__":
    main()
