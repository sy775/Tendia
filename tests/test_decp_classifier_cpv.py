"""
tests/test_decp_classifier_cpv.py — Lancement : python tests/test_decp_classifier_cpv.py

Couvre la règle texte MOE (raffinement pattern 3) : objet « maîtrise d'œuvre »
+ CPV travaux (45xxx) → ingenierie (override le mapping CPV).
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decp.classifier_cpv import classer_marche_cpv

ok = ko = 0


def check(nom, cond):
    global ok, ko
    if cond:
        ok += 1; print(f"  ✓ {nom}")
    else:
        ko += 1; print(f"  ✗ ÉCHEC {nom}")


def cl(cpv, objet):
    return classer_marche_cpv({"id": "X", "cpv_principal": cpv, "objet": objet})


print("Pattern 3 — MOE + CPV 45* → ingenierie (override)")
r = cl("45100000", "Marché de maîtrise d'œuvre pour la réhabilitation du groupe scolaire")
check("« maîtrise d'œuvre » + 45 → ingenierie", r["preset_principal"] == "ingenierie")
check("source = cpv_moe_override", r["source"] == "cpv_moe_override")
check("confiance 0.85", r["confiance"] == 0.85)
check("« MOE » + 45200000 → ingenierie",
      cl("45200000", "MOE phase exécution - extension du centre de secours")["preset_principal"] == "ingenierie")
check("« mission de conception » + 45000000 → ingenierie",
      cl("45000000", "Mission de conception du futur pôle culturel")["preset_principal"] == "ingenierie")
check("« maitrise d'oeuvre » (sans accents) + 45230000 → ingenierie",
      cl("45230000", "Marche de maitrise d'oeuvre - requalification du quai")["preset_principal"] == "ingenierie")
check("« mission de maîtrise d'œuvre » + 45 → ingenierie",
      cl("45000000", "Mission de maîtrise d'œuvre réhabilitation thermique")["preset_principal"] == "ingenierie")

print("Pattern 3 — pas de faux positifs")
check("« construction école » + 45200000 → btp (pas de MOE)",
      cl("45200000", "Construction de l'école primaire et de ses abords")["preset_principal"] == "btp")
check("MOE hors CPV 45 inchangé : + 72000000 → it",
      cl("72000000", "Maîtrise d'œuvre du système d'information")["preset_principal"] == "it")
check("MOE + 71 reste ingenierie (déjà ing, pas d'override hors 45)",
      cl("71200000", "Maîtrise d'œuvre urbaine et paysagère")["preset_principal"] == "ingenierie")
check("« commande » ne déclenche pas MOE (mot 'moe' borné)",
      cl("45200000", "Travaux de rénovation, commande groupée de matériaux")["preset_principal"] == "btp")

print(f"\n=== {ok} OK / {ko} KO ===")
sys.exit(1 if ko else 0)
