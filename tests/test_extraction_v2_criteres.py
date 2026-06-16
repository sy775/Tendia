"""
tests/test_extraction_v2_criteres.py — Lancement : python tests/test_extraction_v2_criteres.py

Couvre la dérivation du schéma plat critères + classification prix/valeur_technique via
unite_evaluation (résout le bug RSE €/CO2) + validation post-LLM (somme=100, ≥1 prix>0).
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_extract import (deriver_criteres_attribution_plat, valider_criteres_plat,
                         _famille_depuis_unite, post_traiter_extraction_v2)

ok = ko = 0


def check(nom, cond):
    global ok, ko
    if cond:
        ok += 1; print(f"  ✓ {nom}")
    else:
        ko += 1; print(f"  ✗ ÉCHEC {nom}")


print("famille depuis unite_evaluation")
check("euro → prix", _famille_depuis_unite("euro") == "prix")
check("points → valeur_technique", _famille_depuis_unite("points") == "valeur_technique")
check("delai_jours → valeur_technique", _famille_depuis_unite("delai_jours") == "valeur_technique")
check("None → valeur_technique (défaut)", _famille_depuis_unite(None) == "valeur_technique")

print("Dérivation plat — cas standard")
bareme = {"valeur_prix_pct": 40, "valeur_technique_pct": 60, "prix": {"source": "RC 5.3"},
          "sous_criteres_techniques": [
              {"libelle": "Mémoire technique", "ponderation_pct": 45, "unite_evaluation": "points", "source": "RC 5.1"},
              {"libelle": "Délai", "ponderation_pct": 15, "unite_evaluation": "delai_jours", "source": "RC 5.2"}]}
plat = deriver_criteres_attribution_plat(bareme)
check("3 critères (Prix + 2 techniques)", len(plat) == 3)
check("Prix → famille prix, pct 40", plat[0]["famille"] == "prix" and plat[0]["ponderation_pct"] == 40)
check("Mémoire → valeur_technique", plat[1]["famille"] == "valeur_technique")
check("Délai → valeur_technique", plat[2]["famille"] == "valeur_technique")
check("source_texte propagée", plat[0]["source_texte"] == "RC 5.3")

print("Bug RSE €/CO2 résolu")
bareme_rse = {"valeur_prix_pct": 30, "valeur_technique_pct": 70,
              "sous_criteres_techniques": [
                  {"libelle": "Valeur technique", "ponderation_pct": 50, "unite_evaluation": "points"},
                  {"libelle": "Bilan carbone €/tonne CO2", "ponderation_pct": 20, "unite_evaluation": "euro"}]}
plat_rse = deriver_criteres_attribution_plat(bareme_rse)
carbone = [c for c in plat_rse if "carbone" in (c["libelle"] or "").lower()][0]
check("Bilan carbone €/CO2 → famille PRIX (pas technique)", carbone["famille"] == "prix")

print("Validation post-LLM")
v = valider_criteres_plat(plat)
check("somme = 100", v["criteres_somme_ponderations"] == 100)
check("pas d'alerte somme", v["criteres_alerte_somme_incorrecte"] is False)
check("pas d'alerte prix", v["criteres_alerte_pas_de_prix"] is False)

plat_sans_prix = [{"libelle": "X", "famille": "valeur_technique", "ponderation_pct": 100}]
check("aucun prix → alerte_pas_de_prix", valider_criteres_plat(plat_sans_prix)["criteres_alerte_pas_de_prix"] is True)

plat_somme_ko = [{"libelle": "Prix", "famille": "prix", "ponderation_pct": 40},
                 {"libelle": "T", "famille": "valeur_technique", "ponderation_pct": 50}]
check("somme 90 → alerte_somme", valider_criteres_plat(plat_somme_ko)["criteres_alerte_somme_incorrecte"] is True)

plat_nc = [{"libelle": "Prix", "famille": "prix", "ponderation_pct": 60},
           {"libelle": "?", "famille": "non_classe", "ponderation_pct": 40}]
check("non_classe → alerte_non_classes", valider_criteres_plat(plat_nc)["criteres_alerte_non_classes"] is True)

check("tolérance ±2 (somme 101 OK)", valider_criteres_plat(
    [{"famille": "prix", "ponderation_pct": 101}])["criteres_alerte_somme_incorrecte"] is False)

print("post_traiter_extraction_v2 (intégration)")
data = post_traiter_extraction_v2({"bareme_notation": bareme})
check("version_extraction_llm = 2", data["version_extraction_llm"] == "2")
check("prompt_version_sha présent", bool(data.get("prompt_version_sha")))
check("criteres_attribution_plat ajouté", len(data["criteres_attribution_plat"]) == 3)
check("flags critères présents", "criteres_alerte_pas_de_prix" in data)

print(f"\n=== {ok} OK / {ko} KO ===")
sys.exit(1 if ko else 0)
