# -*- coding: utf-8 -*-
"""
tests/test_plafond_cout.py
--------------------------
Tests HORS-LIGNE (chantier 2, étape 1) du plafond de coût et de la lecture du coût :
  - tendia.core.budget.plafond_atteint(cout_cumule, max_cout) :
      None = pas de plafond ; 0 = tout est bloqué dès le premier appel ;
      sinon True quand cout_cumule >= max_cout ;
  - tendia.analyse.extraire.plafond_atteint : même contrat (délègue) ;
  - tendia.analyse.extraire.cout_du_resultat(resultat) : coût lu dans
      resultat["extraction"]["_meta"]["cout_eur"], 0.0 dans tous les cas dégradés.
Base et budget temporaires, aucun réseau, aucun LLM.

Lancement : python tests/test_plafond_cout.py
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from base_temporaire import isoler_stockage
dossier = isoler_stockage()

from tendia.core import budget
from tendia.analyse import extraire

ok = ko = 0


def check(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}  {detail}")


def appel(fonction, *args):
    """Résultat de la fonction, ou l'exception rendue comme valeur (jamais levée)."""
    try:
        return fonction(*args)
    except Exception as e:  # noqa: BLE001
        return e


# (cout_cumule, max_cout, attendu, libellé)
CAS_PLAFOND = [
    (0.0, None, False, "None : pas de plafond à cumul 0"),
    (12.5, None, False, "None : pas de plafond à cumul 12,5"),
    (1e12, None, False, "None : pas de plafond même à cumul très grand"),
    (0.0, 0, True, "0 : bloqué dès le premier appel (cumul 0)"),
    (0, 0, True, "0 : bloqué avec cumul entier 0"),
    (0.0, 0.0, True, "0.0 (flottant, comme argparse type=float) : bloqué à cumul 0"),
    (3.2, 0, True, "0 : bloqué à cumul 3,2"),
    (0.0, 5, False, "plafond 5 : cumul 0 passe"),
    (4.99, 5, False, "plafond 5 : cumul 4,99 passe"),
    (5.0, 5, True, "plafond 5 : cumul 5 bloque (>=)"),
    (5, 5.0, True, "plafond 5.0 : cumul entier 5 bloque"),
    (5.01, 5, True, "plafond 5 : cumul 5,01 bloque"),
    (0.0, 0.01, False, "petit plafond 0,01 : cumul 0 passe"),
    (0.01, 0.01, True, "petit plafond 0,01 : cumul 0,01 bloque"),
    (999_999.0, 1e9, False, "très grand plafond : cumul inférieur passe"),
    (1e9, 1e9, True, "très grand plafond : cumul égal bloque"),
    (1e12, 7.0, True, "cumul très grand : bloque"),
]

for nom_module, fonction in (("budget", budget.plafond_atteint),
                             ("extraire", extraire.plafond_atteint)):
    print(f"=== {nom_module}.plafond_atteint ===")
    for cumul, plafond, attendu, libelle in CAS_PLAFOND:
        res = appel(fonction, cumul, plafond)
        check(f"{nom_module} — {libelle}", res is attendu, repr(res))

print("=== extraire.plafond_atteint : même contrat que budget ===")
divergences = [(c, p) for c, p, _, _ in CAS_PLAFOND
               if appel(extraire.plafond_atteint, c, p) != appel(budget.plafond_atteint, c, p)]
check("mêmes réponses sur tous les cas", not divergences, str(divergences))
check("les réponses sont des bool",
      all(isinstance(appel(f, c, p), bool) for c, p, _, _ in CAS_PLAFOND
          for f in (budget.plafond_atteint, extraire.plafond_atteint)))

print("=== extraire.cout_du_resultat ===")
CAS_COUT = [
    (None, 0.0, "resultat None"),
    ({}, 0.0, "resultat vide"),
    ({"statut": "ok"}, 0.0, "extraction absente"),
    ({"extraction": None}, 0.0, "extraction None"),
    ({"extraction": {}}, 0.0, "extraction vide (_meta absent)"),
    ({"extraction": {"objet": "x"}}, 0.0, "_meta absent"),
    ({"extraction": {"_meta": {}}}, 0.0, "cout_eur absent"),
    ({"extraction": {"_meta": {"cout_eur": None}}}, 0.0, "cout_eur None"),
    ({"extraction": {"_meta": {"cout_eur": 0}}}, 0.0, "cout_eur 0"),
    ({"extraction": {"_meta": {"cout_eur": 0.1234}}}, 0.1234, "cout_eur 0,1234"),
    ({"extraction": {"_meta": {"cout_eur": 2}}}, 2.0, "cout_eur entier 2"),
    ({"extraction": {"_meta": {"cout_eur": 123456.789}}}, 123456.789, "cout_eur très grand"),
    ({"extraction": {"_meta": {"cout_eur": 0.42, "modele": "m"}}, "autre": 1}, 0.42,
     "autres champs ignorés"),
]
for resultat, attendu, libelle in CAS_COUT:
    res = appel(extraire.cout_du_resultat, resultat)
    check(f"{libelle} → {attendu}",
          isinstance(res, (int, float)) and not isinstance(res, bool) and abs(res - attendu) < 1e-9,
          repr(res))
res = appel(extraire.cout_du_resultat, {"extraction": {"_meta": {"cout_eur": 2}}})
check("le coût rendu est un float", isinstance(res, float), repr(res))
res = appel(extraire.cout_du_resultat, None)
check("0.0 rendu en float pour None", isinstance(res, float) and res == 0.0, repr(res))

print("=== enchaînement coût → plafond ===")
cumul = 0.0
bloque_a = None
for i, cout in enumerate([0.4, 0.4, 0.4, 0.4]):
    if extraire.plafond_atteint(cumul, 1.0):
        bloque_a = i
        break
    cumul += extraire.cout_du_resultat({"extraction": {"_meta": {"cout_eur": cout}}})
check("plafond 1 € avec des appels à 0,40 € : 3 appels puis arrêt", bloque_a == 3,
      f"bloqué à {bloque_a}, cumul {cumul}")
check("plafond 0 : aucun appel", extraire.plafond_atteint(0.0, 0.0) is True)

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
