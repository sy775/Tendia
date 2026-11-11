# -*- coding: utf-8 -*-
"""
tests/base_temporaire.py
------------------------
Isolation des tests : redirige stockage (data/tendia.db), budget (data/budget.json)
et journaux (logs/) vers un dossier temporaire, pour qu'aucun test n'écrive dans la base de production
(llm_appels, classifications_ia...). À appeler AVANT le premier accès à stockage.

    from base_temporaire import isoler_stockage
    dossier = isoler_stockage()                     # budget par défaut
    dossier = isoler_stockage({"kill_switch_global": True})
"""
import json
import tempfile
from pathlib import Path


def isoler_stockage(config_budget: dict = None) -> Path:
    """Base SQLite et budget.json temporaires. Retourne le dossier temporaire."""
    from tendia.core import budget, stockage

    dossier = Path(tempfile.mkdtemp(prefix="tendia_test_"))
    stockage.DATA_DIR = str(dossier)
    # connexion déjà ouverte dans ce thread sur la vraie base : on la ferme
    conn = getattr(stockage._LOCAL, "conn", None)
    if conn is not None:
        conn.close()
        stockage._LOCAL.conn = None
    stockage.invalider_cache()
    budget.FICHIER_BUDGET = dossier / "budget.json"
    config = dict(budget.DEFAUT_BUDGET)
    config.update(config_budget or {})
    budget.FICHIER_BUDGET.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    isoler_logs(dossier / "logs")
    return dossier


def isoler_logs(dossier_logs: Path = None) -> Path:
    """Journaux JSONL (tendia.core.logs) redirigés vers un dossier temporaire : la
    suite de tests n'écrit jamais dans logs/. Retourne le dossier utilisé."""
    from tendia.core import logs

    if dossier_logs is None:
        dossier_logs = Path(tempfile.mkdtemp(prefix="tendia_test_logs_"))
    dossier_logs.mkdir(parents=True, exist_ok=True)
    logs.LOG_DIR = dossier_logs
    return dossier_logs
