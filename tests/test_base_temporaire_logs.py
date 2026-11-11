# -*- coding: utf-8 -*-
"""
tests/test_base_temporaire_logs.py
----------------------------------
Tests HORS-LIGNE (chantier 2, étape 1) de tests/base_temporaire.isoler_stockage :
l'isolation redirige aussi tendia.core.logs.LOG_DIR vers <dossier temporaire>/logs,
pour que la suite n'écrive plus dans logs/.

Lancement : python tests/test_base_temporaire_logs.py
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tendia.core import chemins
from tendia.core import logs as tendia_logs

ok = ko = 0


def check(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}  {detail}")


def empreinte(dossier_logs: Path) -> dict:
    """{nom: (taille, mtime_ns)} des fichiers du dossier (vide s'il n'existe pas)."""
    if not dossier_logs.exists():
        return {}
    return {p.name: (p.stat().st_size, p.stat().st_mtime_ns)
            for p in dossier_logs.iterdir() if p.is_file()}


LOGS_REELS = Path(chemins.LOGS)
avant = empreinte(LOGS_REELS)

from base_temporaire import isoler_stockage
dossier = isoler_stockage()

print("=== redirection de LOG_DIR ===")
check("isoler_stockage retourne un dossier temporaire existant",
      isinstance(dossier, Path) and dossier.is_dir(), repr(dossier))
check("LOG_DIR = <dossier temporaire>/logs", Path(tendia_logs.LOG_DIR) == dossier / "logs",
      str(tendia_logs.LOG_DIR))
check("LOG_DIR n'est plus le dossier logs/ du dépôt",
      Path(tendia_logs.LOG_DIR).resolve() != LOGS_REELS.resolve())
check("chemins.LOGS inchangé (seul le module logs est redirigé)", Path(chemins.LOGS) == LOGS_REELS)
check("chemin_log pointe sous le dossier temporaire",
      dossier in Path(tendia_logs.chemin_log("extraction")).parents,
      str(tendia_logs.chemin_log("extraction")))

print("=== un événement s'écrit sous le dossier temporaire ===")
tendia_logs.logger_evenement_marche("extraction", "M1", {"evenement": "x"})
fichier = Path(tendia_logs.chemin_log("extraction"))
check("fichier de log créé sous <dossier temporaire>/logs",
      fichier.exists() and fichier.parent == dossier / "logs", str(fichier))
lignes = fichier.read_text(encoding="utf-8").splitlines() if fichier.exists() else []
check("une ligne écrite", len(lignes) == 1, str(len(lignes)))
try:
    evt = json.loads(lignes[0]) if lignes else {}
except ValueError:
    evt = {}
check("la ligne est du JSON qui porte le marché et l'événement",
      "M1" in json.dumps(evt, ensure_ascii=False) and evt.get("evenement") == "x", str(evt))
check("rien d'écrit dans le dossier logs/ du dépôt", empreinte(LOGS_REELS) == avant,
      str(set(empreinte(LOGS_REELS).items()) ^ set(avant.items())))

tendia_logs.logger_evenement_marche("extraction", "M2", {"evenement": "y"})
lignes = fichier.read_text(encoding="utf-8").splitlines() if fichier.exists() else []
check("un 2e événement s'ajoute au même fichier temporaire", len(lignes) == 2, str(len(lignes)))
check("toujours rien dans logs/ du dépôt", empreinte(LOGS_REELS) == avant)

print("=== nouvelle isolation : nouveau dossier, logs suivis ===")
dossier2 = isoler_stockage({"kill_switch_global": True})
check("dossier différent du premier", dossier2 != dossier)
check("LOG_DIR suit la nouvelle isolation", Path(tendia_logs.LOG_DIR) == dossier2 / "logs",
      str(tendia_logs.LOG_DIR))
tendia_logs.logger_evenement_marche("aws-achat", "M3", {"evenement": "z"})
f2 = Path(tendia_logs.chemin_log("aws-achat"))
check("événement écrit sous le 2e dossier", f2.exists() and f2.parent == dossier2 / "logs", str(f2))
check("le 1er dossier n'a pas reçu l'événement",
      not (dossier / "logs" / f2.name).exists())
check("toujours rien dans logs/ du dépôt", empreinte(LOGS_REELS) == avant)

print("=== l'isolation de la base et du budget reste en place ===")
from tendia.core import budget, stockage
check("budget.json sous le dossier temporaire", Path(budget.FICHIER_BUDGET) == dossier2 / "budget.json")
check("config_budget appliquée",
      json.loads(Path(budget.FICHIER_BUDGET).read_text(encoding="utf-8")).get("kill_switch_global") is True)
check("stockage sous le dossier temporaire", Path(stockage.DATA_DIR) == dossier2)
stockage.ecrire("marches", "M-ISOLE", {"id": "M-ISOLE"})
check("écriture lue dans la base temporaire", stockage.lire("marches", "M-ISOLE") == {"id": "M-ISOLE"})
check("base créée dans le dossier temporaire", Path(stockage.chemin_db()).parent == dossier2,
      stockage.chemin_db())

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
