"""
tests/test_decp_matching.py — Lancement : python tests/test_decp_matching.py
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decp.matching import (score_cpv, score_acheteur, score_periode,
                           score_montant, scorer_match)

ok = ko = 0


def check(nom, cond):
    global ok, ko
    if cond:
        ok += 1; print(f"  ✓ {nom}")
    else:
        ko += 1; print(f"  ✗ ÉCHEC {nom}")


def approx(a, b, eps=1e-3):
    return a is not None and abs(a - b) < eps


print("score_cpv")
check("identique → 1.0", score_cpv("45211000", "45211000") == 1.0)
check("5 premiers → 0.7", score_cpv("45211000", "45211999") == 0.7)
check("3 premiers → 0.4", score_cpv("45211000", "45299000") == 0.4)
check("2 premiers → 0.2", score_cpv("45211000", "45911000") == 0.2)
check("rien → 0.0", score_cpv("45211000", "72000000") == 0.0)
check("vide → 0.0", score_cpv(None, "45211000") == 0.0)
check("CPV mal formaté toléré", score_cpv("45211000-9", "45211000") == 1.0)

print("score_acheteur")
check("SIRET identique → 1.0", score_acheteur("13000548100010", "13000548100010") == 1.0)
check("SIREN identique → 0.6", score_acheteur("13000548100010", "13000548100028") == 0.6)
check("SIRET différent → 0.0", score_acheteur("13000548100010", "33071536800297") == 0.0)
check("SIRET court → repli nom (vide) 0.0", score_acheteur("123", "456") == 0.0)
check("repli nom exact → 0.9",
      score_acheteur(None, None, "Commune de Metz", "COMMUNE DE METZ") == 0.9)
check("repli nom partiel → 0.6",
      0.5 < score_acheteur(None, None, "Ville de Lyon Metropole", "Metropole de Lyon") <= 0.9)
check("repli nom sans rapport → 0.0",
      score_acheteur(None, None, "Mairie de Brest", "Hopital de Nice") == 0.0)

print("score_periode")
check("DECP avant Tendia → 0.0", score_periode("2026-05-01", "2026-04-01") == 0.0)
check("0-30j → 0.5", score_periode("2026-05-01", "2026-05-20") == 0.5)
check("30-540j → 1.0", score_periode("2025-01-01", "2025-09-01") == 1.0)
check("décroissance > 18 mois", 0.0 < score_periode("2024-01-01", "2025-08-01") < 1.0)
check("> 36 mois → 0.0", score_periode("2022-01-01", "2026-01-01") == 0.0)
check("date invalide → 0.0", score_periode("xxxx", "2026-01-01") == 0.0)

print("score_montant")
check("ratio 1 → 1.0", score_montant(100000, 100000) == 1.0)
check("ratio 2 → 1.0", score_montant(100000, 200000) == 1.0)
check("ratio 3 → 0.5", score_montant(100000, 300000) == 0.5)
check("ratio 5 → 0.0", score_montant(100000, 500000) == 0.0)
check("estimé absent → None", score_montant(None, 100000) is None)
check("estimé 0 → None", score_montant(0, 100000) is None)

print("scorer_match (intégration)")
# Cas fort : CPV identique, même SIRET, période idéale, montant cohérent
fort = scorer_match(
    {"cpv_principal": "45211000", "acheteur_siret": "13000548100010",
     "date_publication": "2025-01-01", "montant_estime": 100000},
    {"cpv_principal": "45211000", "acheteur_siret": "13000548100010",
     "date_notification": "2025-06-01", "montant_eur": 120000})
check("match fort ≥ 0.85", fort["score_total"] >= 0.85)
check("score_montant présent", fort["score_montant"] == 1.0)

# Cas montant absent → redistribution (pas de None qui casse le total)
sans_m = scorer_match(
    {"cpv_principal": "45211000", "acheteur_siret": "13000548100010",
     "date_publication": "2025-01-01"},
    {"cpv_principal": "45211000", "acheteur_siret": "13000548100010",
     "date_notification": "2025-06-01", "montant_eur": 120000})
check("montant absent → score_montant None", sans_m["score_montant"] is None)
check("redistribution → total = 1.0 (3 scores parfaits)", approx(sans_m["score_total"], 1.0))

# Cas Tendia sans SIRET (réalité BOAMP) → repli nom
reel = scorer_match(
    {"cpv_principal": "45211000", "acheteur_siret": None,
     "acheteur_nom": "Commune de Metz", "date_publication": "2025-01-01"},
    {"cpv_principal": "45211000", "acheteur_siret": "20003986500106",
     "acheteur_nom": "COMMUNE DE METZ", "date_notification": "2025-06-01",
     "montant_eur": 120000})
check("Tendia sans SIRET : match via nom franchit le seuil candidat",
      reel["score_total"] >= 0.70)

print(f"\n=== {ok} OK / {ko} KO ===")
sys.exit(1 if ko else 0)
