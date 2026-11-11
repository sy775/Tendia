# -*- coding: utf-8 -*-
"""
tests/test_rattrapage_max_cout_zero.py
--------------------------------------
Tests HORS-LIGNE (chantier 2, étape 1) de scripts/maintenance/rattrapage_btp_octobre.py :
  main(["briefs", "--max-cout", "0", "--max", "5"]) n'appelle jamais
  extraire.traiter_marche (remplacé par un espion), même avec des marchés à briefer.
Base et dossier data/ temporaires, aucun réseau, aucun LLM.

Lancement : python tests/test_rattrapage_max_cout_zero.py
"""
import contextlib
import io
import os
import sys
import time
from datetime import date, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from base_temporaire import isoler_stockage
dossier = isoler_stockage()

from tendia.core import chemins, stockage
chemins.DATA = dossier  # le fichier d'ids s'écrit dans le dossier temporaire
sys.path.insert(0, str(chemins.RACINE_DEPOT / "scripts" / "maintenance"))
import rattrapage_btp_octobre as R
from tendia.analyse import extraire as E

time.sleep = lambda *_a, **_k: None

ok = ko = 0


def check(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}  {detail}")


# --- extraire : dossiers redirigés, traiter_marche espionné -------------------
E.REPERTOIRE_DCE = str(dossier / "dce")
E.REPERTOIRE_EXTRACTIONS = str(dossier / "extractions")
E.FICHIER_ETAT = os.path.join(E.REPERTOIRE_EXTRACTIONS, "_etat.json")
os.makedirs(E.REPERTOIRE_DCE, exist_ok=True)
os.makedirs(E.REPERTOIRE_EXTRACTIONS, exist_ok=True)

APPELS_TRAITER = []


def _espion_traiter_marche(id_marche, *args, **kwargs):
    APPELS_TRAITER.append(id_marche)
    return {"statut": "ok", "extraction": {"_meta": {"cout_eur": 0.5, "type": "complet"}}}


E.traiter_marche = _espion_traiter_marche

# --- données : trois marchés BTP d'octobre à DCE complet, sans brief complet --
J = lambda n: (date.today() + timedelta(days=n)).isoformat()
IDS = ["M-COMPLET-A", "M-COMPLET-B", "M-COMPLET-C"]
for i, mid in enumerate(IDS):
    stockage.ecrire("marches", mid, {
        "id": mid, "date_publication": f"2026-10-1{i}", "nature": "APPEL_OFFRE",
        "type_marche": "TRAVAUX", "date_limite_depot": J(20 + i), "dce_contenu": "complet",
        "url_dce": f"https://x/{mid}", "dce_telechargement_statut": "ok"})
    os.makedirs(os.path.join(E.REPERTOIRE_DCE, mid), exist_ok=True)
stockage.invalider_cache()


def lancer(argv):
    sortie = io.StringIO()
    erreur = None
    with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(sortie):
        try:
            R.main(argv)
        except SystemExit as e:
            if e.code not in (0, None):
                erreur = e
        except Exception as e:  # noqa: BLE001
            erreur = e
    stockage.invalider_cache()
    return sortie.getvalue(), erreur


print("=== précondition : il y a des marchés à briefer ===")
sortie, erreur = lancer(["cibles"])
check("cibles : fichier d'ids écrit dans le dossier temporaire",
      erreur is None and R.fichier_ids().exists() and R.fichier_ids().parent == dossier,
      repr(erreur))
a_briefer = R.selectionner_briefs(R.lire_ids(), stockage.charger("marches"),
                                  stockage.charger("briefs_extraits") or {})
check("3 marchés à DCE complet sans brief", set(a_briefer) == set(IDS), str(a_briefer))

print("=== briefs --max-cout 0 --max 5 ===")
marches_avant = {k: dict(v) for k, v in stockage.charger("marches").items()}
sortie, erreur = lancer(["briefs", "--max-cout", "0", "--max", "5"])
check("main se termine sans exception", erreur is None, repr(erreur))
check("extraire.traiter_marche jamais appelé", APPELS_TRAITER == [], str(APPELS_TRAITER))
check("aucune entrée llm_appels", not stockage.charger("llm_appels"))
check("aucun brief écrit", not stockage.charger("briefs_extraits"),
      str(list((stockage.charger("briefs_extraits") or {}).keys())))
check("marchés inchangés en base", stockage.charger("marches") == marches_avant)
check("état d'extraction non écrit", not os.path.exists(E.FICHIER_ETAT))

print("=== briefs --max-cout 0.0 (écriture décimale) et --max 1 ===")
sortie, erreur = lancer(["briefs", "--max-cout", "0.0", "--max", "1"])
check("0.0 bloque comme 0", erreur is None and APPELS_TRAITER == [],
      f"{erreur!r} {APPELS_TRAITER}")

print("=== témoin : avec des PDF lisibles, seul le plafond décide ===")
# Lecture des PDF remplacée (ajout du relecteur d'étape) : sans cela les dossiers vides
# n'atteignent jamais traiter_marche et le test passerait même sans la garde.
from tendia.analyse import pdf_extract
pdf_extract.extraire_dossier = lambda dossier, verbose=False: {"rc.pdf": "Règlement de consultation " * 50}
E._dezipper_dossier = lambda dossier, verbose=True: 0

sortie, erreur = lancer(["briefs", "--max-cout", "0", "--max", "5"])
check("PDF lisibles, --max-cout 0 : traiter_marche jamais appelé",
      erreur is None and APPELS_TRAITER == [], f"{erreur!r} {APPELS_TRAITER}")
sortie, erreur = lancer(["briefs", "--max-cout", "5", "--max", "5"])
check("PDF lisibles, --max-cout 5 : traiter_marche appelé (le test distingue la garde)",
      erreur is None and len(APPELS_TRAITER) == 3, f"{erreur!r} {APPELS_TRAITER}")
APPELS_TRAITER.clear()
sortie, erreur = lancer(["briefs", "--max-cout", "0.6", "--max", "5"])
check("--max-cout 0.6 à 0,5 € le brief : arrêt après 2 briefs",
      erreur is None and len(APPELS_TRAITER) == 2, f"{erreur!r} {APPELS_TRAITER}")

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
