# -*- coding: utf-8 -*-
"""
tests/test_chemins.py
---------------------
Tests HORS-LIGNE de tendia.core.chemins (chantier 0b) : la racine du dépôt est
calculée depuis le paquet, indépendamment du répertoire courant, et les modules
qui en dépendent (stockage, budget, logs, preset) pointent bien dessous.

Lancement : python tests/test_chemins.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tendia.core import chemins

ok = ko = 0


def check(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}  {detail}")


print("=== constantes ===")
R = chemins.RACINE_DEPOT
check("RACINE_DEPOT absolue", R.is_absolute(), str(R))
check("RACINE_DEPOT contient pyproject.toml", (R / "pyproject.toml").is_file(), str(R))
check("RACINE_DEPOT contient src/tendia", (R / "src" / "tendia" / "__init__.py").is_file())
for nom, attendu in (("DATA", "data"), ("LOGS", "logs"), ("PRESETS", "presets"),
                     ("RAPPORTS", "rapports"), ("ARCHIVE", "archive")):
    check(f"{nom} = racine/{attendu}", getattr(chemins, nom) == R / attendu)
check("presets/ présent", chemins.PRESETS.is_dir())

print("=== modules qui en dépendent ===")
from tendia.core import budget, logs, stockage
from tendia.veille import preset

check("stockage.DATA_DIR = DATA", Path(stockage.DATA_DIR) == chemins.DATA, stockage.DATA_DIR)
check("stockage.chemin_db sous DATA", Path(stockage.chemin_db()).parent == chemins.DATA)
check("budget.FICHIER_BUDGET sous DATA", budget.FICHIER_BUDGET == chemins.DATA / "budget.json")
check("logs.LOG_DIR = LOGS", logs.LOG_DIR == chemins.LOGS)
check("preset.PRESETS_DIR = PRESETS", preset.PRESETS_DIR == chemins.PRESETS)

print("=== indépendance du répertoire courant ===")
with tempfile.TemporaryDirectory() as autre:
    r = subprocess.run([sys.executable, "-c",
                        "from tendia.core.chemins import RACINE_DEPOT; print(RACINE_DEPOT)"],
                       cwd=autre, capture_output=True, text=True, encoding="utf-8")
    check("même racine depuis un autre répertoire",
          r.returncode == 0 and Path(r.stdout.strip()) == R, r.stdout.strip() or r.stderr[-200:])

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
