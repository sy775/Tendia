"""
tests/test_decp_mapping_cpv.py — Lancement : python tests/test_decp_mapping_cpv.py
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decp.mapping_cpv import classer_par_cpv
from decp.classifier_cpv import classer_marche_cpv

ok = ko = 0


def check(nom, cond):
    global ok, ko
    if cond:
        ok += 1; print(f"  ✓ {nom}")
    else:
        ko += 1; print(f"  ✗ ÉCHEC {nom}")


def p(cpv):
    return classer_par_cpv(cpv)[0]


def src(cpv):
    return classer_par_cpv(cpv)[1]


print("Préfixe 2 chiffres")
check("45 → btp", p("45000000") == "btp")
check("45421000 → btp (préfixe)", p("45421000") == "btp")
check("71 → ingenierie", p("71300000") == "ingenierie")
check("72 → it", p("72253000") == "it")
check("80 → formation", p("80530000") == "formation")
check("48 → it (progiciels)", p("48000000") == "it" and src("48780000") == "cpv_prefixe_2")

print("Exact")
check("45000000 exact", src("45000000") == "cpv_exact")

print("Sous-codes ciblés (EnR / conseil_rd)")
check("0933x → enr", p("09331000") == "enr")
check("45251 → enr (centrales)", p("45251200") == "enr")
check("731 → conseil_rd", p("73100000") == "conseil_rd")
check("732 → conseil_rd", p("73200000") == "conseil_rd")
check("794 → conseil_rd (conseil gestion)", p("79400000") == "conseil_rd")
check("79212 → conseil_rd (audit)", p("79212000") == "conseil_rd")
check("sous-code prioritaire sur ambigu 79", p("79212100") == "conseil_rd")
check("sous-code prioritaire sur ambigu 09", p("09332000") == "enr")

print("Pattern 1 — événementiel 79952 → hors_perimetre")
check("79952000 → hors_perimetre", p("79952000") == "hors_perimetre")
check("79952100 → hors_perimetre (sous-code)", p("79952100") == "hors_perimetre")
check("79952xxx prioritaire sur ambigu 79", src("79952000") == "cpv_prefixe_5")
check("79951 (hors 79952) reste ambigu → None", p("79951000") is None)

print("Pattern 2 — 71314 affiné (ingenierie sauf fourniture)")
check("71314000 → ingenierie (exact)", p("71314000") == "ingenierie" and src("71314000") == "cpv_exact")
check("71314100 → hors_perimetre (fourniture élec)", p("71314100") == "hors_perimetre")
check("71314300 → ingenierie (audit énergie)", p("71314300") == "ingenierie")
check("71314 n'est PLUS enr", p("71314000") != "enr" and p("71314100") != "enr")
check("71314xxx non listé → ingenierie (préfixe 71)",
      p("71314900") == "ingenierie" and src("71314900") == "cpv_prefixe_2")

print("Ambigus → LLM (None)")
check("79 générique → None", p("79110000") is None and src("79110000") == "cpv_ambigu_explicite")
check("50 maintenance → None", p("50700000") is None)
check("09 énergie générique → None", p("09100000") is None)

print("Hors périmètre")
check("33 médical → hors", p("33140000") == "hors_perimetre")
check("55 restauration → hors", p("55000000") == "hors_perimetre")
check("60 transport → hors", p("60000000") == "hors_perimetre")
check("34 véhicules → hors", p("34100000") == "hors_perimetre")

print("Inconnu")
check("00000000 → inconnu (mapping)", p("00000000") is None and src("00000000") == "inconnu")
check("CPV vide → inconnu", p("") is None)

print("classer_marche_cpv (règles marché)")
check("CPV bidon + objet vide → hors_perimetre 0.7",
      (lambda r: r["preset_principal"] == "hors_perimetre" and r["source"] == "cpv_donnees_insuffisantes"
       and r["confiance"] == 0.7)(classer_marche_cpv({"id": "X", "cpv_principal": "00000000", "objet": ""})))
check("CPV bidon + objet exploitable → LLM",
      classer_marche_cpv({"id": "X", "cpv_principal": "00000000",
                          "objet": "Travaux de réfection de la toiture du gymnase"})["preset_principal"] is None)
check("btp confiance 0.75 (préfixe 2)",
      classer_marche_cpv({"id": "X", "cpv_principal": "45421000", "objet": "x"})["confiance"] == 0.75)
check("repli CPV secondaire (×0.8)",
      (lambda r: r["preset_principal"] == "btp" and r["source"] == "cpv_secondaire")(
          classer_marche_cpv({"id": "X", "cpv_principal": "79110000", "cpv_secondaires": "45000000", "objet": "x"})))

print(f"\n=== {ok} OK / {ko} KO ===")
sys.exit(1 if ko else 0)
