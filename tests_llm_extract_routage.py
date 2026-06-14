"""
tests_llm_extract_routage.py
----------------------------
Tests HORS-LIGNE du routage de prompt par preset (Sous-chantier 1D).

Vérifie :
- preset ciblé      → seuls SES blocs sectoriels dans le prompt + few-shot ;
- HORS-PÉRIMÈTRE ([])→ AUCUN bloc sectoriel, seulement le bloc neutre
                       `caracteristiques_metier`, pas de few-shot ;
- multi-preset      → blocs des presets concernés ;
- _filtrer_hallucinations cohérent (strip total en hors-périmètre).

Lancement : python tests_llm_extract_routage.py
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import preset
import llm_extract as L

preset.recharger()

ok = 0
ko = 0


def check(nom, cond):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}")


CTX = "Marché test"
TXT = "Contenu DCE de test."


def prompt(codes):
    return L._construire_prompt_utilisateur(CTX, TXT, codes)


# ===========================================================================
print("=== Prompt ciblé (btp) ===")
p_btp = prompt(["btp"])
check("contient le bloc BTP", "caracteristiques_techniques_chantier" in p_btp)
check("contient qualifications_requises", "qualifications_requises" in p_btp)
check("NE contient PAS le bloc ingénierie", "caracteristiques_mission_moe" not in p_btp)
check("NE contient PAS le bloc IT", "qualifications_it" not in p_btp)
check("contient le bloc neutre caracteristiques_metier ? NON (preset ciblé)",
      "caracteristiques_metier" not in p_btp)
check("contient les few-shot (section EXEMPLES D'EXTRACTION)",
      "EXEMPLES D'EXTRACTION" in p_btp)

print("\n=== Prompt HORS-PÉRIMÈTRE (codes_presets=[]) ===")
p_hp = prompt([])
check("contient le bloc neutre caracteristiques_metier", "caracteristiques_metier" in p_hp)
check("NE contient AUCUN bloc BTP", "caracteristiques_techniques_chantier" not in p_hp)
check("NE contient AUCUN bloc ingénierie", "caracteristiques_mission_moe" not in p_hp)
check("NE contient AUCUN bloc IT", "qualifications_it" not in p_hp)
check("NE contient AUCUN bloc formation", "qualifications_formation" not in p_hp)
check("PAS de few-shot en hors-périmètre", "EXEMPLES D'EXTRACTION" not in p_hp)
# None doit se comporter comme []
check("codes_presets=None == comportement hors-périmètre",
      "caracteristiques_techniques_chantier" not in prompt(None))

print("\n=== Prompt multi-preset (btp + ingenierie) ===")
p_multi = prompt(["btp", "ingenierie"])
check("contient le bloc BTP", "caracteristiques_techniques_chantier" in p_multi)
check("contient le bloc ingénierie", "caracteristiques_mission_moe" in p_multi)
check("NE contient PAS le bloc IT", "qualifications_it" not in p_multi)

print("\n=== _filtrer_hallucinations ===")
# preset ciblé btp : garde btp + universels, supprime un bloc étranger
data = {"synthese_marche": "x", "qualifications_requises": {}, "qualifications_si": {},
        "caracteristiques_techniques_chantier": {}, "bareme_notation": {}}
out = L._filtrer_hallucinations(dict(data), ["btp"])
check("btp ciblé : garde qualifications_requises", "qualifications_requises" in out)
check("btp ciblé : supprime qualifications_si (étranger)", "qualifications_si" not in out)
check("btp ciblé : garde champ universel bareme_notation", "bareme_notation" in out)

# hors-périmètre : supprime TOUS les blocs sectoriels, garde universels + neutre
data2 = {"synthese_marche": "x", "caracteristiques_metier": {}, "bareme_notation": {},
         "qualifications_requises": {}, "caracteristiques_techniques_chantier": {},
         "qualifications_si": {}}
out2 = L._filtrer_hallucinations(dict(data2), [])
check("hors-périmètre : garde caracteristiques_metier (neutre)", "caracteristiques_metier" in out2)
check("hors-périmètre : garde synthese_marche (universel)", "synthese_marche" in out2)
check("hors-périmètre : supprime qualifications_requises", "qualifications_requises" not in out2)
check("hors-périmètre : supprime caracteristiques_techniques_chantier",
      "caracteristiques_techniques_chantier" not in out2)
check("hors-périmètre : supprime qualifications_si", "qualifications_si" not in out2)

# few_shot_examples_pour_presets
check("few_shot([]) == '' ", preset.few_shot_examples_pour_presets([]) == "")
check("few_shot(['btp']) non vide", len(preset.few_shot_examples_pour_presets(["btp"])) > 0)
check("blocs_sectoriels_pour_presets([]) == []", preset.blocs_sectoriels_pour_presets([]) == [])
check("blocs_sectoriels_pour_presets(['btp']) non vide",
      len(preset.blocs_sectoriels_pour_presets(["btp"])) > 0)


print(f"\n{'='*56}")
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
