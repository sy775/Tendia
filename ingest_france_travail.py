# -*- coding: utf-8 -*-
"""
Ingestion CIBLÉE France Travail (5 marchés) — avec proxy IPRoyal pour
contourner le throttle d'IP de l'API BOAMP OpenDataSoft.

Étape 1 ici : récupère + persiste les AVIS (collection marches).
La récupération DCE et l'extraction LLM se font ensuite (étapes séparées).

Usage : python ingest_france_travail.py
"""
from pathlib import Path


def _charger_proxy():
    for line in Path(".env").read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip().startswith("TENDIA_PROXY_URL="):
            return line.split("=", 1)[1].strip()
    return None


def main():
    proxy = _charger_proxy()
    if not proxy:
        raise SystemExit("Pas de TENDIA_PROXY_URL dans .env")
    import http_utils
    http_utils._session.proxies = {"http": proxy, "https": proxy}
    print(f"  Proxy BOAMP actif : {proxy[:22]}...")

    import tendia_recup
    stats = tendia_recup.recuperer_tout(
        fenetre_mois=3,
        limite_par_source=20,      # ~5 marchés FT après classification
        mode_large=False,          # legacy = filtre France Travail
        differentiel=False,
        dry_run=False,
        verbose=True,
    )
    print("\n=== STATS ===")
    print("récupérés :", stats.get("nb_recuperes"),
          "| nouveaux :", stats.get("nb_nouveaux"),
          "| maj :", stats.get("nb_mis_a_jour"))
    print("par catégorie :", dict(stats.get("par_categorie") or {}))


if __name__ == "__main__":
    main()
