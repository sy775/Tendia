"""
tests/test_extraction_v2_montants.py — Lancement : python tests/test_extraction_v2_montants.py

Couvre l'aplatissement + validation des 3 voies de montant par post_traiter_extraction_v2.
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_extract import post_traiter_extraction_v2

ok = ko = 0


def check(nom, cond):
    global ok, ko
    if cond:
        ok += 1; print(f"  ✓ {nom}")
    else:
        ko += 1; print(f"  ✗ ÉCHEC {nom}")


def pt(m3):
    return post_traiter_extraction_v2({"bareme_notation": {}, "montant_3_voies": m3})


print("Voie 1 (montant publié)")
d = pt({"voie_1_eur": 250000, "voie_1_source": "RC §3.2", "voie_2_disponible": False})
check("voie_1_eur propagé", d["montant_voie_1_eur"] == 250000)
check("voie_1_source propagé", d["montant_voie_1_source"] == "RC §3.2")
check("au moins une voie", d["montant_au_moins_une_voie"] is True)
check("pas d'alerte cohérence", d["montant_alerte_coherence"] is False)

print("Voie 1 incohérente (montant sans source)")
d = pt({"voie_1_eur": 100000, "voie_1_source": None})
check("alerte cohérence (montant sans source)", d["montant_alerte_coherence"] is True)

print("Voie 2 (estimation bottom-up)")
d = pt({"voie_1_eur": None, "voie_2_disponible": True, "voie_2_min_eur": 80000,
        "voie_2_max_eur": 120000, "voie_2_hypotheses": [{"hypothese": "300 j-h", "valeur": "300"}]})
check("voie_2_disponible", d["montant_voie_2_disponible"] is True)
check("au moins une voie (via voie 2)", d["montant_au_moins_une_voie"] is True)
check("pas d'alerte (min<max + hypothèses)", d["montant_alerte_coherence"] is False)

print("Voie 2 incohérente")
d = pt({"voie_1_eur": None, "voie_2_disponible": True, "voie_2_min_eur": 200000,
        "voie_2_max_eur": 100000, "voie_2_hypotheses": [{"hypothese": "x", "valeur": "1"}]})
check("min > max → alerte", d["montant_alerte_coherence"] is True)
d = pt({"voie_1_eur": None, "voie_2_disponible": True, "voie_2_min_eur": 1, "voie_2_max_eur": 2,
        "voie_2_hypotheses": []})
check("voie 2 dispo sans hypothèses → alerte", d["montant_alerte_coherence"] is True)

print("Aucune voie")
d = pt({"voie_1_eur": None, "voie_2_disponible": False,
        "voie_2_raison_indisponible": "DCE sans volume chiffrable"})
check("aucune voie disponible", d["montant_au_moins_une_voie"] is False)
check("pas d'alerte (cas légitime non_communique)", d["montant_alerte_coherence"] is False)

print("Bloc montant_3_voies absent (rétro-compat)")
d = post_traiter_extraction_v2({"bareme_notation": {}})
check("montant_voie_1_eur = None", d["montant_voie_1_eur"] is None)
check("au moins une voie = False", d["montant_au_moins_une_voie"] is False)

print(f"\n=== {ok} OK / {ko} KO ===")
sys.exit(1 if ko else 0)
