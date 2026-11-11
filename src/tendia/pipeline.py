"""
tendia.pipeline
---------------
Orchestrateur du pipeline Tendia COMPLET et AUTOMATIQUE.

Une seule commande :
    python -m tendia            (shim : python tendia_pipeline.py)

Enchainement (7 étapes) :
1. veille/recup            : récupère les nouveaux avis BOAMP
2. veille/classification   : classification Haiku des marchés non classés (pré-filtre
                             gratuit d'abord), plafonnée par --max-cout-classification
3. dce/resolution          : résout les URLs DCE (eForms + PLACE keyWord)
4. dce/telecharger         : DCE connecteurs anonymes (PLACE, Atexo, achatpublic,
                             e-marchespublics) — dossier complet via chemin profond
5. connecteurs dédiés      : AWS-Achat + Dematis + xmarches (captcha 2captcha + anti-ban),
                             auto-limités aux heures de bureau et au cap --max-dedies ;
                             marches-securises (anonyme)
6. analyse/extraire        : auto-dézip + extraction LLM (Claude Sonnet 4.6)
7. génération rapport final marches_actifs_<date>.md

Aucune intervention humaine. Le proxy résidentiel est autorisé (TENDIA_PROXY_ACTIF=1).

Options :
    --skip-recup       : passe l'étape récupération (utilise la base actuelle)
    --skip-llm         : passe les étapes LLM (2 classification et 6 extraction)
    --max-cout-classification EUR : plafond de coût de l'étape 2 (défaut: 5.0)
    --skip-download    : passe l'étape téléchargement DCE anonyme
    --skip-dedies      : passe les connecteurs dédiés à captcha (AWS, Dematis)
    --max-dedies N     : cap de marchés par connecteur dédié captcha (défaut: 15)
    --ignorer-heures   : lance les dédiés hors heures de bureau (tests)
    --jours N          : fenêtre marchés sans date limite (défaut: 60)
"""

import os
import argparse
import subprocess
import sys
import time
from datetime import date, datetime

from tendia.core.chemins import DATA, RACINE_DEPOT
from tendia.core.etat_marche import est_actif

REPERTOIRE_BASE = RACINE_DEPOT
REPERTOIRE_DCE = DATA / "dce"


# Marché actif : définition unique dans tendia.core.etat_marche (chantier 1b).
_est_actif = est_actif


def _print_etape(num: int, titre: str, total: int = 7):
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
        result = subprocess.run(cmd, check=False, cwd=RACINE_DEPOT)
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


def main(argv=None):
    os.environ.setdefault("TENDIA_PROXY_ACTIF", "1")  # proxy résidentiel autorisé (lanceur de téléchargements)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        prog="python -m tendia",
        description="Tendia — Pipeline complet automatique (7 étapes : récup, classification, "
                    "résolution DCE, téléchargement anonyme, connecteurs dédiés, extraction "
                    "LLM, rapport).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--skip-recup", action="store_true",
                        help="Passe l'étape récupération BOAMP")
    parser.add_argument("--skip-download", action="store_true",
                        help="Passe l'étape téléchargement PLACE")
    parser.add_argument("--skip-llm", action="store_true",
                        help="Passe les étapes LLM : 2 (classification) et 6 (extraction)")
    parser.add_argument("--max-cout-classification", type=float, default=5.0, metavar="EUR",
                        help="Plafond de coût de l'étape 2, transmis à classification "
                             "--max-cout (défaut: 5.0 ; 0 : aucun appel LLM)")
    parser.add_argument("--max-cout-extraction", type=float, default=None, metavar="EUR",
                        help="Plafond de coût de l'étape 6, transmis à extraire --max-cout "
                             "(défaut : aucun plafond de passe, seul data/budget.json "
                             "s'applique ; 0 : aucun appel LLM)")
    parser.add_argument("--force", action="store_true",
                        help="Force la re-extraction LLM même si déjà fait")
    parser.add_argument("--jours", type=int, default=60,
                        help="Fenêtre marchés sans date limite (défaut: 60)")
    parser.add_argument("--skip-dedies", action="store_true",
                        help="Passe les connecteurs DCE dédiés à captcha (AWS, Dematis)")
    parser.add_argument("--max-dedies", type=int, default=15,
                        help="Cap de marchés par connecteur dédié captcha (défaut: 15)")
    parser.add_argument("--ignorer-heures", action="store_true",
                        help="Lance les connecteurs dédiés hors heures de bureau (tests)")
    args = parser.parse_args(argv)

    debut_global = time.time()

    print("=" * 78)
    print()
    print("           A P P T I A   —   P I P E L I N E   C O M P L E T")
    print()
    print(f"           {datetime.now().strftime('%A %d %B %Y · %Hh%M').lower()}")
    print()
    print("=" * 78)

    # === Étape 1 : Récupération BOAMP ===
    if args.skip_recup:
        print("\n  [1/7]  Récupération BOAMP  →  SKIPPÉ (--skip-recup)")
    else:
        _print_etape(1, "Récupération avis BOAMP")
        # --large : ingestion SANS filtre acheteur (tous les avis, pas seulement
        # France Travail/Pôle Emploi, legacy du ciblage historique).
        # --differentiel : borne à la dernière date connue → on ne re-balaie pas
        # les 6 mois complets à chaque passe (sinon 60k+ avis).
        _executer_script(str(RACINE_DEPOT / "src/tendia/veille/recup.py"), ["--large", "--differentiel"])

    # === Étape 2 : Classification (Haiku, plafonnée) ===
    if args.skip_llm:
        print("\n  [2/7]  Classification LLM  →  SKIPPÉ (--skip-llm)")
    else:
        _print_etape(2, f"Classification des marchés non classés (Haiku, plafond "
                        f"{args.max_cout_classification:.2f} €)")
        _executer_script(str(RACINE_DEPOT / "src/tendia/veille/classification.py"),
                         ["--max-cout", str(args.max_cout_classification)])

    # === Étape 3 : Résolution URLs DCE ===
    _print_etape(3, "Résolution URLs DCE (eForms + PLACE keyWord)")
    _executer_script(str(RACINE_DEPOT / "src/tendia/dce/resolution.py"), ["--jours", str(args.jours)])

    # === Étape 4 : Téléchargement DCE — connecteurs anonymes (sans captcha) ===
    # Couvre PLACE, Atexo (+ marques blanches), achatpublic, e-marchespublics via
    # le chemin profond (dossier complet en une passe). AWS/Dematis sont EXCLUS ici
    # (captcha + pacing) → traités à l'étape 5.
    if args.skip_download:
        print("\n  [4/7]  Téléchargement DCE (anonyme)  →  SKIPPÉ (--skip-download)")
    else:
        _print_etape(4, "Téléchargement DCE — PLACE / Atexo / achatpublic / e-marchespublics")
        _executer_script(str(RACINE_DEPOT / "src/tendia/dce/telecharger.py"))

    # === Étape 5 : Connecteurs DCE dédiés ===
    # Deux familles :
    #  • CAPTCHA (AWS-Achat, Dematis, xmarches) : exigent 2captcha + pacing anti-ban
    #    (heures de bureau, cap --max-dedies).
    #  • ANONYME (marches-securises) : pas de captcha ; recherche réf/objet +
    #    désambiguïsation acheteur ; quota par IP battu par rotation proxy. Pas de
    #    contrainte horaire, cap plus large (cibles ~30).
    if args.skip_dedies:
        print("\n  [5/7]  Connecteurs DCE dédiés  →  SKIPPÉ (--skip-dedies)")
    else:
        _print_etape(5, "Connecteurs DCE dédiés (captcha : AWS/Dematis/xmarches ; anonyme : marches-securises)")
        extra = ["--oui", "--max", str(args.max_dedies)]
        if args.ignorer_heures:
            extra.append("--ignorer-heures")
        _executer_script(str(RACINE_DEPOT / "scripts/maintenance/retelecharger_aws_achat_anti_ban.py"), extra)
        _executer_script(str(RACINE_DEPOT / "scripts/maintenance/retelecharger_dematis_anti_ban.py"), extra)
        _executer_script(str(RACINE_DEPOT / "scripts/maintenance/retelecharger_xmarches.py"), ["--oui", "--max", str(args.max_dedies)])
        # marches-securises : anonyme, cap dédié plus large (pas de coût captcha).
        _executer_script(str(RACINE_DEPOT / "scripts/maintenance/retelecharger_marches_securises.py"),
                         ["--oui", "--max", str(max(args.max_dedies, 40))])

    # === Étape 6 : Extraction LLM ===
    if args.skip_llm:
        print("\n  [6/7]  Extraction LLM  →  SKIPPÉ (--skip-llm)")
    else:
        _print_etape(6, "Extraction LLM des DCE (Claude Sonnet 4.6)")
        args_extract = ["--force"] if args.force else []
        if args.max_cout_extraction is not None:
            args_extract += ["--max-cout", str(args.max_cout_extraction)]
        _executer_script(str(RACINE_DEPOT / "src/tendia/analyse/extraire.py"), args_extract)

    # === Étape 7 : Rapport final ===
    _print_etape(7, "Génération du rapport final")
    _executer_script(str(RACINE_DEPOT / "src/tendia/dce/resolution.py"), ["--jours", str(args.jours),
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
        from tendia.core import stockage
        from tendia.dce import atexo_downloader
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
        resultat = atexo_downloader.telecharger_dce_pour_marche(
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
