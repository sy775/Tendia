# -*- coding: utf-8 -*-
"""
tests/test_matching.py
----------------------
Tests HORS-LIGNE de tendia.eligibilite.matching (chantier 1b) : verdict
`non_classe` distinct de `non_pertinent`, presets résolus depuis
classifications_ia. Base temporaire (tests/base_temporaire.py), profil
`profil_btp_demo`, aucun appel réseau ni LLM.

Lancement : python tests/test_matching.py
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from base_temporaire import isoler_stockage

isoler_stockage()

from tendia.core import stockage  # noqa: E402
from tendia.core.chemins import DATA  # noqa: E402
from tendia.eligibilite import matching  # noqa: E402

ok = ko = 0


def check(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}  {detail}")


PROFIL = json.loads((DATA / "exemples" / "profil_btp_demo.json").read_text(encoding="utf-8"))
PROFIL["id"] = "profil_btp_demo"


def marche(id_m, titre, dept="75"):
    return {"id": id_m, "titre": titre, "objet": titre, "date_limite_depot": "2099-01-01",
            "perimetre_geographique": f"Dept {dept}", "acheteur_code_postal": f"{dept}001",
            "code_departement": [dept], "type_marche": "TRAVAUX"}


CLASSIF_BTP = {"domaines_metier": [{"code": "btp_voirie_reseaux", "poids": 1.0}],
               "synthese_courte": "Travaux de voirie."}
CLASSIF_HORS = {"domaines_metier": [{"code": "prestations_speciales_titres_cheques", "poids": 1.0}],
                "synthese_courte": "Chèques cadeaux."}

print("=== non_classe ===")
m_absent = marche("T-ABSENT", "Réfection de chaussée et trottoirs")
e = matching.evaluer(PROFIL, m_absent, classification=None)
check("absent de classifications_ia → non_classe", e["verdict"] == "non_classe", e["verdict"])
check("score toujours calculé", isinstance(e["score"], int))
e = matching.evaluer(PROFIL, m_absent)  # lecture stockage : base temporaire vide
check("lecture stockage, entrée absente → non_classe", e["verdict"] == "non_classe", e["verdict"])
e = matching.evaluer(PROFIL, dict(m_absent, preset_codes=["btp"]), classification=None)
check("preset_codes posés sur le marché → classé (pas non_classe)", e["verdict"] != "non_classe", e["verdict"])
e = matching.evaluer(PROFIL, m_absent, brief={"domaines_metier": CLASSIF_BTP["domaines_metier"]},
                     classification=None)
check("domaines d'un brief → classé", e["verdict"] != "non_classe", e["verdict"])

print("=== classé : comportement inchangé ===")
m_hors = marche("T-HORS", "Fourniture de chèques cadeaux")
e = matching.evaluer(PROFIL, m_hors, classification=CLASSIF_HORS)
check("présent et non matché → non_pertinent (inchangé)", e["verdict"] == "non_pertinent", e["verdict"])
stockage.ecrire("classifications_ia", "T-HORS", CLASSIF_HORS)
e = matching.evaluer(PROFIL, m_hors)
check("même résultat en lisant classifications_ia", e["verdict"] == "non_pertinent", e["verdict"])
check("presets résolus depuis la classification", e["presets_marche"] != [], e["presets_marche"])

m_btp = marche("T-BTP", "Travaux de voirie, réfection de chaussée et réseaux")
e = matching.evaluer(PROFIL, m_btp, classification=CLASSIF_BTP)
check("classé BTP (voirie, IDF) → preset btp résolu", "btp" in e["presets_marche"], e["presets_marche"])
check("classé BTP → pertinent ou mieux, pas non_classe",
      e["verdict"] in ("tres_pertinent", "pertinent", "a_verifier"), (e["verdict"], e["score"]))

print("=== est_classe ===")
check("rien → False", not matching.est_classe({}))
check("classification → True", matching.est_classe({}, classification=CLASSIF_BTP))
check("domaines_metier sur le marché → True",
      matching.est_classe({"domaines_metier": [{"code": "btp_voirie_reseaux"}]}))

print("=== profil sans preset : inchangé ===")
e = matching.evaluer(dict(PROFIL, presets_couverts=[]), m_btp, classification=CLASSIF_BTP)
check("profil sans preset → non_pertinent", e["verdict"] == "non_pertinent", e["verdict"])

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
