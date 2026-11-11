# -*- coding: utf-8 -*-
"""
tests/test_budget_plafond_date.py
---------------------------------
Tests HORS-LIGNE (chantier 2b, étape 0) : plafond_global_eur_mois et alerte_seuil_eur_mois
acceptent un nombre ou un dictionnaire daté {"AAAA-MM": valeur, "defaut": valeur}, résolus
selon le mois de l'appel (kill switch, peut_appeler_llm, statistiques_mois).

Lancement : python tests/test_budget_plafond_date.py
"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from base_temporaire import isoler_stockage
dossier = isoler_stockage()

from tendia.core import budget, stockage

ok = ko = 0


def check(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}  {detail}")


def ecrire_budget(**cles):
    conf = dict(budget.DEFAUT_BUDGET)
    conf["kill_switch_global"] = False
    conf.update(cles)
    budget.FICHIER_BUDGET.write_text(json.dumps(conf, ensure_ascii=False), encoding="utf-8")


print("=== valeur_du_mois ===")
V = budget.valeur_du_mois
check("nombre", V(45, "2026-11") == 45.0)
check("mois listé", V({"2026-11": 65, "defaut": 30}, "2026-11") == 65.0)
check("mois non listé → defaut", V({"2026-11": 65, "defaut": 30}, "2026-12") == 30.0)
check("mois non listé sans defaut → None", V({"2026-11": 65}, "2027-01") is None)
check("absent → None", V(None) is None)
check("chaîne numérique acceptée", V({"defaut": "30"}, "2026-12") == 30.0)

print("=== plafond appliqué selon le mois de l'appel ===")
MOIS = budget._mois_iso()
stockage.ecrire(budget.COLLECTION_APPELS, "a1", {"mois": MOIS, "jour": MOIS + "-01",
                                                  "type": "extraction", "cout_eur": 40.0, "statut": "ok"})
stockage.invalider_cache()
ecrire_budget(plafond_global_eur_mois={MOIS: 65, "defaut": 30}, alerte_seuil_eur_mois={MOIS: 60, "defaut": 25})
check("plafond du mois courant (65) non atteint à 40 € : autorisé",
      budget.peut_appeler_llm("extraction").autorise)
try:
    budget.verifier_kill_switch("extraction")
    check("kill switch : passe sous le plafond daté", True)
except budget.BudgetDepasseError as e:
    check("kill switch : passe sous le plafond daté", False, e)
st = budget.statistiques_mois(MOIS)
check("alerte datée : seuil 60, pas d'alerte à 40 €", st["seuil_alerte"] == 60.0 and not st["alerte_active"], st)
check("statistiques d'un autre mois : seuil par défaut 25", budget.statistiques_mois("1999-01")["seuil_alerte"] == 25.0)

ecrire_budget(plafond_global_eur_mois={"1999-01": 65, "defaut": 30})
check("mois courant non listé → défaut 30 : bloqué à 40 €", not budget.peut_appeler_llm("extraction").autorise)
try:
    budget.verifier_kill_switch("extraction")
    check("kill switch bloque au plafond par défaut", False)
except budget.BudgetDepasseError:
    check("kill switch bloque au plafond par défaut", True)
check("plafond_mois() résout le mois courant", budget.plafond_mois() == 30.0)

ecrire_budget(plafond_global_eur_mois=35)
check("nombre simple toujours accepté (bloqué à 40 € ≥ 35)", not budget.peut_appeler_llm("extraction").autorise)

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
