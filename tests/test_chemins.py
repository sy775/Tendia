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

print("=== constantes de chemin des modules déplacés en 0b (AUDIT_0b, constat 2) ===")
from tendia.analyse import extraire, llm_calibration, llm_router
from tendia.dce import resolution, telecharger
from tendia.eligibilite import matching_exigences, organisme, pertinence
from tendia.memoire.services import _memoire_commun, assemblage_docx, digest_memoire
from tendia.prix import jointure
from tendia.prix.decp import classif_ia
from tendia.veille import classification
from tendia.ui import app


def sous(chemin, base):
    """True si `chemin` (str ou Path) est `base` ou en dessous."""
    p = Path(chemin).resolve()
    return p == base.resolve() or base.resolve() in p.parents


D, P = chemins.DATA, chemins.PRESETS
for nom, valeur, base in (
    ("extraire.REPERTOIRE_DCE", extraire.REPERTOIRE_DCE, D),
    ("extraire.REPERTOIRE_EXTRACTIONS", extraire.REPERTOIRE_EXTRACTIONS, D),
    ("extraire.REPERTOIRE_RAPPORTS", extraire.REPERTOIRE_RAPPORTS, chemins.RAPPORTS),
    ("llm_calibration.REPERTOIRE_CALIBRATIONS", llm_calibration.REPERTOIRE_CALIBRATIONS, D),
    ("llm_router.CHEMIN_CONFIG", llm_router.CHEMIN_CONFIG, R),
    ("organisme._PRESETS_DIR", organisme._PRESETS_DIR, P),
    ("organisme._DOSSIER_EXEMPLES", organisme._DOSSIER_EXEMPLES, D),
    ("resolution.REPERTOIRE_DCE", resolution.REPERTOIRE_DCE, D),
    ("resolution.REPERTOIRE_RAPPORTS", resolution.REPERTOIRE_RAPPORTS, chemins.RAPPORTS),
    ("telecharger.REPERTOIRE_DCE", telecharger.REPERTOIRE_DCE, D),
    ("jointure.FICHIER_JOINTURE", jointure.FICHIER_JOINTURE, D),
    ("classif_ia.CHEMIN_TAXONOMIE", classif_ia.CHEMIN_TAXONOMIE, P),
    ("classification.CHEMIN_TAXONOMIE", classification.CHEMIN_TAXONOMIE, P),
    ("_memoire_commun.REPERTOIRE_PROFILS_DEMO", _memoire_commun.REPERTOIRE_PROFILS_DEMO, D),
    ("assemblage_docx.REPERTOIRE_MEMOIRES", assemblage_docx.REPERTOIRE_MEMOIRES, D),
    ("digest_memoire.REPERTOIRE_DCE", digest_memoire.REPERTOIRE_DCE, D),
    ("ui.app.REPERTOIRE_DATA", app.REPERTOIRE_DATA, D),
):
    check(f"{nom} sous {base.name}", sous(valeur, base), str(valeur))
check("llm_router.CHEMIN_CONFIG existe", Path(llm_router.CHEMIN_CONFIG).is_file())
check("classification.CHEMIN_TAXONOMIE existe", classification.CHEMIN_TAXONOMIE.is_file())

# Chemins calculés dans une fonction : on vérifie le comportement.
check("pertinence._charger_tous_les_presets lit presets/",
      len(pertinence._charger_tous_les_presets()) > 0)
_data_reel = chemins.DATA
with tempfile.TemporaryDirectory() as tmp:
    (Path(tmp) / "extractions").mkdir()
    (Path(tmp) / "extractions" / "TEST-0B.json").write_text(
        '{"alertes_candidat": ["Chiffre d\'affaires minimum 100 000 EUR"]}', encoding="utf-8")
    chemins.DATA = Path(tmp)
    try:
        lu = matching_exigences.calculer_verdict_pour_marche("TEST-0B", {"nom": "x"})
        absent = matching_exigences.calculer_verdict_pour_marche("ABSENT-0B", {"nom": "x"})
    finally:
        chemins.DATA = _data_reel
check("matching_exigences lit DATA/extractions/<id>.json", lu is not None)
check("matching_exigences : brief absent -> None", absent is None)

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
