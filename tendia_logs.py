"""
tendia_logs.py
--------------
Logs structurés JSONL pour les downloaders DCE (production).

Chaque événement marché (succès, échec, ban, retry IP) est ajouté en une ligne
JSON dans logs/<downloader>_<YYYY-MM-DD>.jsonl. Ces logs alimentent ensuite
tendia_monitoring.py (dashboard console) et le calcul de coûts.

Conçu pour ne JAMAIS faire planter un downloader : toute erreur d'écriture est
silencieusement ignorée (le log est secondaire vs le téléchargement).
"""
import json
import os
from datetime import datetime
from pathlib import Path

LOG_DIR = Path("logs")


def _aujourdhui() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def chemin_log(downloader: str, jour: str = None) -> Path:
    """Chemin du fichier de log JSONL d'un downloader pour un jour donné."""
    return LOG_DIR / f"{downloader}_{jour or _aujourdhui()}.jsonl"


def logger_evenement_marche(downloader: str, id_marche: str,
                            evenement: dict) -> None:
    """Ajoute une ligne JSON dans logs/<downloader>_<YYYY-MM-DD>.jsonl.

    Args:
        downloader: nom court ("aws-achat", "atexo", "achatpublic"...).
        id_marche: identifiant du marché traité.
        evenement: dict libre (ok, etape_erreur, taille_octets, nb_captcha,
                   duree_secondes, tentative_ip, ...).
    """
    try:
        LOG_DIR.mkdir(exist_ok=True)
        ligne = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "downloader": downloader,
            "id_marche": id_marche,
            **(evenement or {}),
        }
        with open(chemin_log(downloader), "a", encoding="utf-8") as f:
            f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    except Exception:
        # Le logging ne doit jamais interrompre un téléchargement.
        pass


def lire_evenements(depuis_jours: int = 7) -> list:
    """Relit tous les événements JSONL des `depuis_jours` derniers jours.

    Retourne une liste de dicts (ordre chronologique de lecture des fichiers).
    Tolérant : ignore les lignes corrompues et les fichiers illisibles.
    """
    evenements = []
    if not LOG_DIR.is_dir():
        return evenements
    from datetime import date, timedelta
    jours_ok = {(date.today() - timedelta(days=i)).isoformat()
                for i in range(max(0, depuis_jours))}
    for fichier in sorted(LOG_DIR.glob("*.jsonl")):
        # nom = <downloader>_<YYYY-MM-DD>.jsonl ; on filtre par date du nom.
        jour = fichier.stem.rsplit("_", 1)[-1]
        if depuis_jours and jour not in jours_ok:
            continue
        try:
            with open(fichier, encoding="utf-8") as f:
                for ligne in f:
                    ligne = ligne.strip()
                    if not ligne:
                        continue
                    try:
                        evenements.append(json.loads(ligne))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue
    return evenements
