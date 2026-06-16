"""
tests/test_decp_parser.py — Lancement : python tests/test_decp_parser.py
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decp.parser import (valider_siret, normaliser_cpv, parser_marche,
                         agreger_multi_titulaires)

ok = ko = 0


def check(nom, cond):
    global ok, ko
    if cond:
        ok += 1; print(f"  ✓ {nom}")
    else:
        ko += 1; print(f"  ✗ ÉCHEC {nom}")


print("valider_siret")
check("SIRET valide (FT)", valider_siret("13000548100010"))
check("SIRET valide 2", valider_siret("33071536800297"))
check("SIRET invalide (Luhn KO)", not valider_siret("13000548100011"))
check("SIRET trop court", not valider_siret("1300054810"))
check("SIRET vide/None", not valider_siret(None) and not valider_siret(""))
check("SIRET avec espaces (nettoyé)", valider_siret("130 0054 8100010"))

print("normaliser_cpv")
check("CPV avec tiret", normaliser_cpv("45211000-9") == "45211000")
check("CPV déjà 8", normaliser_cpv("72253000") == "72253000")
check("CPV vide", normaliser_cpv("") is None)
check("CPV court conservé tel quel", normaliser_cpv("451") == "451")

print("parser_marche")
raw = {"id": "DECP-X1", "objet": "Travaux", "codeCPV": "45211000-9",
       "acheteur_id": "13000548100010", "acheteur_nom": "FT",
       "titulaire_id": "33071536800297", "montant": "150000",
       "dateNotification": "2026-05-12", "dureeMois": "24",
       "procedure": "MAPA", "lieuExecution_code": "75056",
       "acheteur_departement_code": "75", "acheteur_region_code": "11"}
p = parser_marche(raw)
check("id conservé", p and p["id"] == "DECP-X1")
check("cpv normalisé 8 ch.", p["cpv_principal"] == "45211000")
check("montant float", p["montant_eur"] == 150000.0)
check("date ISO", p["date_notification"] == "2026-05-12")
check("departement natif", p["departement"] == "75")
check("region native", p["region"] == "11")
check("pas de warnings", p["parse_warnings"] is None)

check("rejet si pas d'id", parser_marche({"objet": "x"}) is None)

p_neg = parser_marche({"id": "A", "montant": "-5", "codeCPV": "45000000",
                       "dateNotification": "2026-01-01"})
check("montant négatif rejeté + warning",
      p_neg["montant_eur"] is None and "montant_negatif" in (p_neg["parse_warnings"] or []))
p_ab = parser_marche({"id": "B", "montant": "2000000000", "dateNotification": "2026-01-01"})
check("montant > 1 Md rejeté", p_ab["montant_eur"] is None
      and "montant_aberrant_>1Md" in (p_ab["parse_warnings"] or []))
p_bad = parser_marche({"id": "C", "dateNotification": "12/05/2026"})
check("date non ISO → warning", "date_non_iso:dateNotification" in (p_bad["parse_warnings"] or []))
p_si = parser_marche({"id": "D", "acheteur_id": "13000548100011",
                      "dateNotification": "2026-01-01"})
check("SIRET acheteur invalide → warning",
      "acheteur_siret_invalide" in (p_si["parse_warnings"] or []))

print("agreger_multi_titulaires")
m = [parser_marche({"id": "M1", "titulaire_id": "33071536800297",
                    "dateNotification": "2026-01-01"}),
     parser_marche({"id": "M1", "titulaire_id": "13000548100010",
                    "dateNotification": "2026-01-01"}),
     parser_marche({"id": "M2", "titulaire_id": "33071536800297",
                    "dateNotification": "2026-01-01"})]
agg = agreger_multi_titulaires(m)
check("dédup par id (3 lignes → 2 marchés)", len(agg) == 2)
m1 = next(x for x in agg if x["id"] == "M1")
check("M1 titulaires_json contient 2 SIRET",
      m1["titulaires_json"] and "33071536800297" in m1["titulaires_json"]
      and "13000548100010" in m1["titulaires_json"])
m2 = next(x for x in agg if x["id"] == "M2")
check("M2 mono-titulaire → pas de titulaires_json", m2["titulaires_json"] is None)

print(f"\n=== {ok} OK / {ko} KO ===")
sys.exit(1 if ko else 0)
