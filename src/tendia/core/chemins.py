"""
tendia.core.chemins
-------------------
Chemins de la racine du dépôt. Tout chemin vers data/, logs/, presets/, rapports/
ou archive/ passe par ces constantes : aucun os.path.dirname(__file__) empilé ailleurs.
"""
from pathlib import Path

# src/tendia/core/chemins.py -> parents[3] = racine du dépôt
RACINE_DEPOT = Path(__file__).resolve().parents[3]
DATA = RACINE_DEPOT / "data"
LOGS = RACINE_DEPOT / "logs"
PRESETS = RACINE_DEPOT / "presets"
RAPPORTS = RACINE_DEPOT / "rapports"
ARCHIVE = RACINE_DEPOT / "archive"
