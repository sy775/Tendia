# -*- coding: utf-8 -*-
"""
tests/test_champs_critiques.py
------------------------------
Tests HORS-LIGNE (chantier 2b, étape 1) de tendia.analyse.champs_critiques : les 6 champs
critiques choisis par le code dans les notes par pièce, sans LLM.

  - lecture des notes : critères (texte libre, dict, liste), date et heure, montants en
    euros (une année n'est pas un montant), visite, lots, pièces exigées ;
  - choix : RC > AE > CCAP > autres, puis la note la plus explicite (heure présente) ;
  - désaccords dans _conflits ; source = note retenue, page corrigée si l'extrait est sur
    une autre page de la même pièce ;
  - valeur contrôlée : date, heure, pondérations, montant publié présents dans la page,
    sinon valeur_verifiee = False ;
  - montant publié et estimation séparés : la voie 2 ne remplit jamais le montant publié,
    « non communiqué » sans montant dans les notes RC / AE ; lignes de la fiche.

Lancement : python tests/test_champs_critiques.py
"""
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from base_temporaire import isoler_stockage
dossier = isoler_stockage()

from tendia.analyse import champs_critiques as CC
from tendia.analyse import pieces as P
from tendia.ui import fiche_marche as F

ok = ko = 0


def check(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}  {str(detail)[:400]}")


FIXTURES = Path(__file__).resolve().parent / "fixtures"
spec = importlib.util.spec_from_file_location("generateur_fixtures_cc", FIXTURES / "generer_dce_mixte.py")
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

# =====================================================================================
print("=== lecture des notes ===")
cr = CC.criteres_de("1) CRITERE PRIX : 60 points\n- Sous-critère 1 : forfait (30 points)\n"
                    "- Sous-critère 2 : DQE (30 points)\nFormule : 60 x (offre moins disante / offre)\n"
                    "2) CRITERE TECHNIQUE : 40 points\n- Sous-critère n°1 : moyens (10 points)")
check("texte libre : 2 critères de premier niveau, sous-critères rattachés",
      [c["ponderation"] for c in cr] == [60, 40] and len(cr[0]["sous_criteres"]) == 2, cr)
cr = CC.criteres_de({"criteres": [{"nom": "Prix", "ponderation_points": 60},
                                  {"nom": "Valeur technique", "ponderation_points": 30,
                                   "sous_criteres": [{"nom": "Méthode", "ponderation_points": 20}]},
                                  {"nom": "Environnement", "ponderation_points": 10}]})
b = CC.bareme_depuis_criteres(cr)
check("dict : prix 60, technique 30, environnement en autre critère (pas fondu dans la technique)",
      b["valeur_prix_pct"] == 60 and b["valeur_technique_pct"] == 30
      and b["autres_criteres"] == [{"libelle": "Environnement", "ponderation_pct": 10}], b)
b = CC.bareme_depuis_criteres(CC.criteres_de("Prix : 12 points ; Valeur technique : 8 points"))
check("points ramenés en % quand le total n'est pas 100 (12/8 → 60/40)",
      b["valeur_prix_pct"] == 60 and b["valeur_technique_pct"] == 40, b)
cr = CC.criteres_de("Pour l'ensemble des lots, les deux critères principaux sont : 1. Valeur technique de "
                    "l'offre : 65 points ; 2. Prix de l'offre : 35 points. Méthode B : Excellente = 100% des "
                    "points ; Satisfaisant = 60% des points ; Non traité = 0% des points.")
b = CC.bareme_depuis_criteres(cr)
check("texte sur une ligne avec grille de notation : 65 / 35 seulement (constat 102749)",
      [c["ponderation"] for c in cr] == [65, 35] and b["valeur_technique_pct"] == 65 and b["valeur_prix_pct"] == 35
      and cr[0]["libelle"] == "Valeur technique de l'offre", cr)
check("avis OJS typé RC : passe après le vrai RC",
      CC.choisir("montant", [{"piece": "2026-OJS206-0073-fr-ts.pdf", "type": "RC", "valeur": "35 000 000 EUR", "ordre": 0},
                             {"piece": "2026ACM013 RC.pdf", "type": "RC", "valeur": "12.6 M€ HT", "ordre": 1}])["piece"]
      == "2026ACM013 RC.pdf")
check("date et heure ISO", CC.date_heure("2026-12-14 12:00") == ((2026, 12, 14), (12, 0)))
check("date en lettres, heure 16h", CC.date_heure("7 janvier 2027 à 16h") == ((2027, 1, 7), (16, 0)))
check("date sans heure", CC.date_heure("2026-12-10") == ((2026, 12, 10), None))
check("dates d'une page : « LUNDI 14 DECEMBRE 2026 », « 10/12/26 »",
      {(2026, 12, 14), (2026, 12, 10)} <= CC.dates_dans("Date : LUNDI 14 DECEMBRE 2026 ; ou 10/12/26"))
check("heures d'une page : 12H00, 9 h 30", {(12, 0), (9, 30)} <= CC.heures_dans("à 12H00 puis 9 h 30"))
m = CC.montants_euros("Montant annuel estimé : 305 000 € TTC ; marché 2026 ; 1,2 M€ HT ; 45 k€")
check("montants en euros : 305 000 € TTC, 1,2 M€, 45 k€ ; l'année 2026 n'est pas un montant",
      [(v, t) for v, t, _p in m] == [(305000.0, "TTC"), (1200000.0, "HT"), (45000.0, None)], m)
check("visite non obligatoire", CC.visite_obligatoire("Une visite des lieux n'est pas obligatoire.") is False)
check("visite obligatoire", CC.visite_obligatoire("Obligatoire. Date prévue : 17/11") is True)
check("visite facultative", CC.visite_obligatoire("Visite facultative") is False)
check("non alloti", CC.lots_de("Marché non alloti (marché unique)")[0] is False)
al, lots = CC.lots_de("Lot 1 : Gros œuvre ; Lot 2 : Charpente ; Lot 3 : Couverture")
check("alloti : 3 lots numérotés", al is True and [l["numero"] for l in lots] == [1, 2, 3], lots)
check("pièces : intitulés « … : » écartés, puces retirées",
      CC.liste_pieces("Hors dispositif DUME :\n- Lettre DC1\n2) Déclaration DC2") == ["Lettre DC1", "Déclaration DC2"])

# =====================================================================================
print("=== choix dans les notes, sources, contrôle des valeurs (inventaire réel) ===")
TMP = Path(tempfile.mkdtemp(prefix="tendia_cc_"))
P.DIR_PIECES = TMP / "pieces"
P.DIR_PIECES.mkdir()
racine = TMP / "dce" / "CC"
racine.mkdir(parents=True)
(racine / "RC.pdf").write_bytes(gen.pdf([
    ["RÈGLEMENT DE LA CONSULTATION", "Allotissement : le marché n'est pas alloti."] + gen.remplir(8),
    ["Article 5 : critère prix des prestations 60 points, critère valeur technique 40 points.",
     "Date limite de réception des offres : LUNDI 14 DECEMBRE 2026 à 12H00.",
     "Une visite des lieux n'est pas obligatoire."] + gen.remplir(8)]))
(racine / "AE.pdf").write_bytes(gen.pdf([["ACTE D'ENGAGEMENT", "Montant maximum annuel : 600 000 euros TTC.",
                                          "Date limite : 14/12/2026."] + gen.remplir(8)]))
(racine / "CCAP.pdf").write_bytes(gen.pdf([["CCAP", "Date de remise : 15 décembre 2026 à 10h00."] + gen.remplir(8)]))
inv = P.inventorier("CC", str(racine), verbose=False)
types = {"RC.pdf": "RC", "AE.pdf": "AE", "CCAP.pdf": "CCAP"}
for p in inv["pieces"]:
    p["type"] = types[p["nom"]]


def note(piece, **infos):
    return {"piece": piece, "type": types[piece], "resultats": [{"partie": 1, "ok": True, "json": {"informations": infos}}]}


analyses = [
    note("AE.pdf", montant={"valeur": "Montant maximum annuel : 600 000 € TTC", "pages": [1],
                            "extrait": "Montant maximum annuel : 600 000 euros TTC"},
         date_limite_remise={"valeur": "2026-12-14", "pages": [1], "extrait": "Date limite : 14/12/2026"}),
    note("CCAP.pdf", date_limite_remise={"valeur": "2026-12-15 10:00", "pages": [1],
                                         "extrait": "Date de remise : 15 décembre 2026 à 10h00"}),
    note("RC.pdf",
         criteres_attribution={"valeur": "Prix des prestations : 60 points\nValeur technique : 40 points", "pages": [1],
                               "extrait": "critère prix des prestations 60 points, critère valeur technique 40 points"},
         date_limite_remise={"valeur": "2026-12-14 12:00", "pages": [2],
                             "extrait": "Date limite de réception des offres : LUNDI 14 DECEMBRE 2026 à 12H00"},
         visite={"valeur": "Non obligatoire", "pages": [2], "extrait": "Une visite des lieux n'est pas obligatoire"},
         lots={"valeur": "Marché non alloti", "pages": [1], "extrait": "le marché n'est pas alloti"},
         pieces_candidature={"valeur": ["Lettre de candidature DC1", "Déclaration DC2"], "pages": [1],
                             "extrait": "RÈGLEMENT DE LA CONSULTATION"}),
]
brief = {
    "bareme_notation": {"valeur_prix_pct": 60, "valeur_technique_pct": 60},
    "calendrier": {"date_limite_offres": "2026-12-14"},
    "complements_dce": {"visite": {"obligatoire": True, "modalites": "inventé"}},
    "lots": [{"numero": 1, "intitule": "A"}, {"numero": 2, "intitule": "B"}],
    "montant_marche": {"valeur_estimee_euros": 350000, "type": "calcule_volumes",
                       "fourchette_min_euros": 300000, "fourchette_max_euros": 400000},
    "montant_3_voies": {"voie_1_eur": 350000, "voie_2_min_eur": 300000, "voie_2_max_eur": 400000},
    "_sources": {},
}
suivi = CC.appliquer(brief, analyses, inv)
check("date : RC retenu (priorité), avec l'heure", brief["calendrier"]["date_limite_offres"] == "2026-12-14 12:00",
      brief["calendrier"])
check("source de la date = note RC ; page citée 2", brief["_sources"]["date_limite"]["piece"] == "RC.pdf"
      and brief["_sources"]["date_limite"]["page"] == 2 and brief["_sources"]["date_limite"]["verifie"],
      brief["_sources"]["date_limite"])
check("date contrôlée dans la page (« 14 DECEMBRE 2026 à 12H00 »)", brief["_sources"]["date_limite"]["valeur_verifiee"] is True)
check("désaccord CCAP (15/12 10:00) noté dans _conflits ; AE (même jour, sans heure) non",
      [c["piece"] for c in brief["_conflits"].get("date_limite", [])] == ["CCAP.pdf"], brief["_conflits"])
check("critères : 60 / 40 depuis le RC (la fusion disait 60 / 60)",
      brief["bareme_notation"]["valeur_prix_pct"] == 60 and brief["bareme_notation"]["valeur_technique_pct"] == 40)
check("critères : page corrigée 1 → 2 (extrait sur la page 2 du RC), valeur contrôlée",
      brief["_sources"]["criteres_ponderations"]["page"] == 2
      and brief["_sources"]["criteres_ponderations"].get("page_citee") == 1
      and brief["_sources"]["criteres_ponderations"]["valeur_verifiee"] is True, brief["_sources"]["criteres_ponderations"])
check("visite : non obligatoire (la fusion disait obligatoire)", brief["complements_dce"]["visite"]["obligatoire"] is False)
check("lots : non alloti, un seul lot gardé", brief["complements_dce"]["allotissement"] == "non alloti"
      and len(brief["lots"]) == 1)
check("pièces exigées depuis la note RC",
      [p["libelle"] for p in brief["dossier_candidature"]["pieces_a_fournir"]] == ["Lettre de candidature DC1", "Déclaration DC2"])
mp = brief["montant_publie"]
check("montant publié : 600 000 € TTC (AE), plafond", mp["statut"] == "publie" and mp["valeur_eur"] == 600000
      and mp["taxe"] == "TTC" and brief["montant_marche"]["type"] == "plafond", mp)
check("montant publié : remplace l'estimation de la fusion, fourchettes vidées",
      brief["montant_marche"]["valeur_estimee_euros"] == 600000 and brief["montant_marche"]["fourchette_min_euros"] is None)
check("voie 2 (estimation) intacte", brief["montant_3_voies"]["voie_2_min_eur"] == 300000)
check("montant contrôlé dans la page", brief["_sources"]["montant"]["valeur_verifiee"] is True)
check("_champs_critiques garde la valeur de la fusion remplacée",
      suivi["date_limite"]["valeur_fusion"] == "2026-12-14" and suivi["date_limite"]["origine"] == "notes")

# date dont la valeur n'est pas dans la page : à vérifier
analyses_faux = [note("RC.pdf", date_limite_remise={"valeur": "2026-12-21 12:00", "pages": [2],
                                                    "extrait": "Date limite de réception des offres : LUNDI 14 DECEMBRE 2026 à 12H00"})]
b2 = {"calendrier": {}, "_sources": {}}
CC.appliquer(b2, analyses_faux, inv)
check("date absente de la page citée : valeur_verifiee False (« à vérifier »), source vérifiée quand même",
      b2["_sources"]["date_limite"]["valeur_verifiee"] is False and b2["_sources"]["date_limite"]["verifie"] is True,
      b2["_sources"]["date_limite"])

# aucun montant dans les notes RC / AE : non communiqué, l'estimation ne remplit rien
b3 = {"montant_marche": {"valeur_estimee_euros": 350000, "type": "calcule_volumes"},
      "montant_3_voies": {"voie_1_eur": 350000, "voie_2_min_eur": 300000, "voie_2_max_eur": 400000}, "_sources": {}}
CC.appliquer(b3, [note("RC.pdf", lots={"valeur": "Marché non alloti", "pages": [1], "extrait": "x"}),
                  note("CCAP.pdf", montant_estime={"valeur": "250 000 € HT", "pages": [1], "extrait": "x"})], inv)
check("sans montant RC / AE : « non communiqué » (le CCAP ne publie pas de montant)",
      b3["montant_publie"]["statut"] == "non_communique" and b3["montant_marche"]["valeur_estimee_euros"] is None
      and b3["montant_3_voies"]["voie_1_eur"] is None and b3["montant_marche"]["type"] == "non_communique", b3)
check("sans montant : pas de source de montant", b3["_sources"].get("montant") is None)
check("champ sans note (date) : valeur de la fusion gardée, origine fusion, à vérifier",
      b3["_champs_critiques"]["date_limite"]["origine"] in ("fusion", "absent")
      and b3["_champs_critiques"]["date_limite"]["valeur_verifiee"] is False)

# =====================================================================================
print("=== fiche : deux lignes, montant publié / estimation ===")
l = F.lignes_montant(b3)
check("non communiqué + estimation bottom-up (voie 2)", l["publie"] == "non communiqué"
      and l["estimation"] == "300 000 € – 400 000 €" and "bottom-up" in l["estimation_detail"], l)
l = F.lignes_montant(b3, {"disponible": True, "montant_p25": 200000, "montant_p75": 280000, "n": 14})
check("estimation par comparables DECP, avec leur nombre", l["estimation"] == "200 000 € – 280 000 €"
      and l["estimation_detail"] == "comparables DECP, 14 comparables", l)
l = F.lignes_montant(brief)
check("montant publié affiché seul, estimation distincte", l["publie"] == "600 000 € TTC (plafond)"
      and l["estimation"] == "300 000 € – 400 000 €", l)
l = F.lignes_montant({"montant_marche": {"type": "non_communique"}})
check("sans estimation : « Estimation : non calculée »", l["estimation_libelle"] == "Estimation"
      and l["estimation"] == "non calculée" and l["publie"] == "non communiqué", l)
check("ancien brief : calcule_volumes n'est pas un montant publié",
      F.montant_publie({"montant_marche": {"valeur_estimee_euros": 1, "type": "calcule_volumes"}}) is None)

shutil.rmtree(TMP, ignore_errors=True)
print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
