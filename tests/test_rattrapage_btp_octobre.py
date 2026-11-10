# -*- coding: utf-8 -*-
"""
tests/test_rattrapage_btp_octobre.py
------------------------------------
Tests HORS-LIGNE de la sélection de scripts/maintenance/rattrapage_btp_octobre.py
(base et dossier data/ temporaires, aucun réseau, aucun LLM) :
cibles (BTP d'octobre, hors attribution, date limite à venir), tri, fichier d'ids,
sélections dce et briefs, tableau par plateforme, sous-commandes en --dry-run.

Lancement : python tests/test_rattrapage_btp_octobre.py
"""
import contextlib
import io
import sys
from datetime import date, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from base_temporaire import isoler_stockage
dossier = isoler_stockage()

from tendia.core import chemins, stockage
chemins.DATA = dossier  # le fichier d'ids s'écrit dans le dossier temporaire
sys.path.insert(0, str(chemins.RACINE_DEPOT / "scripts" / "maintenance"))
import rattrapage_btp_octobre as R

ok = ko = 0


def check(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}  {detail}")


J = lambda n: (date.today() + timedelta(days=n)).isoformat()
MARCHES = {
    # cibles
    "M-CLASSE-BTP": {"date_publication": "2026-10-03", "nature": "APPEL_OFFRE", "type_marche": "SERVICES",
                     "date_limite_depot": J(30), "url_profil_acheteur": "https://www.achatpublic.com/x",
                     "url_dce": "https://www.achatpublic.com/dce/1"},
    "M-TRAVAUX": {"date_publication": "2026-10-20", "nature": "APPEL_OFFRE", "type_marche": "TRAVAUX",
                  "date_limite_depot": J(10) + "T12:00:00", "url_profil_acheteur": "marches-securises.fr"},
    "M-COMPLET": {"date_publication": "2026-10-11", "nature": "APPEL_OFFRE", "type_marche": "TRAVAUX",
                  "date_limite_depot": J(20), "dce_contenu": "complet",
                  "url_dce": "https://x/y", "dce_telechargement_statut": "ok"},
    "M-COMPLET-BRIEFE": {"date_publication": "2026-10-12", "nature": "APPEL_OFFRE", "type_marche": "TRAVAUX",
                         "date_limite_depot": J(25), "dce_contenu": "complet"},
    # exclus
    "M-ATTRIBUTION": {"date_publication": "2026-10-05", "nature": "ATTRIBUTION", "type_marche": "TRAVAUX",
                      "date_limite_depot": J(30)},
    "M-EXPIRE": {"date_publication": "2026-10-05", "nature": "APPEL_OFFRE", "type_marche": "TRAVAUX",
                 "date_limite_depot": J(-1)},
    "M-NOVEMBRE": {"date_publication": "2026-11-02", "nature": "APPEL_OFFRE", "type_marche": "TRAVAUX",
                   "date_limite_depot": J(30)},
    "M-SERVICES": {"date_publication": "2026-10-07", "nature": "APPEL_OFFRE", "type_marche": "SERVICES",
                   "date_limite_depot": J(30)},
}
for mid, m in MARCHES.items():
    stockage.ecrire("marches", mid, dict(m, id=mid))
stockage.ecrire("classifications_ia", "M-CLASSE-BTP",
                {"domaines_metier": [{"code": "btp_gros_oeuvre"}]})
stockage.ecrire("classifications_ia", "M-SERVICES",
                {"domaines_metier": [{"code": "formation_pro_continue"}]})
stockage.ecrire("briefs_extraits", "M-COMPLET-BRIEFE", {"_meta": {"type": "complet"}})
stockage.ecrire("briefs_extraits", "M-COMPLET", {"_meta": {"type": "light"}})

print("=== sélection des cibles ===")
marches = stockage.charger("marches")
classifs = stockage.charger("classifications_ia")
cibles = R.selectionner_cibles(marches, classifs, date.today().isoformat())
check("4 cibles (btp_* ou TRAVAUX, octobre, à venir, hors attribution)",
      set(cibles) == {"M-CLASSE-BTP", "M-TRAVAUX", "M-COMPLET", "M-COMPLET-BRIEFE"}, str(cibles))
check("tri par date limite décroissante",
      cibles == ["M-CLASSE-BTP", "M-COMPLET-BRIEFE", "M-COMPLET", "M-TRAVAUX"], str(cibles))
check("attribution exclue (nature=ATTRIBUTION)", R.est_attribution(MARCHES["M-ATTRIBUTION"]))
check("ContractAwardNotice exclu", R.est_attribution({"notice_type": "ContractAwardNotice"}))
check("plateforme sans www", R.plateforme(MARCHES["M-CLASSE-BTP"]) == "achatpublic.com")
check("plateforme sans schéma", R.plateforme(MARCHES["M-TRAVAUX"]) == "marches-securises.fr")
check("plateforme absente", R.plateforme({}) == "(aucune)")

print("=== sélections dce et briefs ===")
check("dce : sans DCE complet, date limite décroissante",
      R.selectionner_dce(cibles, marches) == ["M-CLASSE-BTP", "M-TRAVAUX"])
check("dce : --max respecté", R.selectionner_dce(cibles, marches, 1) == ["M-CLASSE-BTP"])
briefs = stockage.charger("briefs_extraits")
check("briefs : DCE complet sans brief complet (brief light compris)",
      R.selectionner_briefs(cibles, marches, briefs) == ["M-COMPLET"])
check("briefs : --max 0", R.selectionner_briefs(cibles, marches, briefs, 0) == [])

print("=== tableau par plateforme ===")
tab = R.tableau_plateformes(cibles, marches)
check("achatpublic : 1 cible, url résolue",
      tab["achatpublic.com"]["cibles"] == 1 and tab["achatpublic.com"]["url_resolue"] == 1)
check("repli sur url_dce : x (1 cible complète, url résolue)",
      tab["x"]["cibles"] == 1 and tab["x"]["complet"] == 1 and tab["x"]["url_resolue"] == 1,
      str(dict(tab.get("x", {}))))
check("(aucune) : 1 cible complète", tab["(aucune)"]["cibles"] == 1 and tab["(aucune)"]["complet"] == 1,
      str(dict(tab["(aucune)"])))

print("=== sous-commandes (sans réseau ni LLM) ===")
sortie = io.StringIO()
with contextlib.redirect_stdout(sortie):
    R.main(["cibles", "--dry-run"])
check("cibles --dry-run : pas de fichier", not R.fichier_ids().exists())
with contextlib.redirect_stdout(sortie):
    R.main(["cibles"])
lus = R.lire_ids()
check("cibles : fichier d'ids écrit dans DATA", lus == cibles, str(lus))
check("fichier sous le dossier temporaire", R.fichier_ids().parent == dossier)
avant = {k: dict(v) for k, v in stockage.charger("marches").items()}
with contextlib.redirect_stdout(sortie):
    R.main(["dce", "--max", "60", "--max-dedies", "15", "--dry-run"])
    R.main(["briefs", "--max-cout", "7", "--max", "20", "--dry-run"])
stockage.invalider_cache()
check("dce/briefs --dry-run : base inchangée", stockage.charger("marches") == avant)
check("dry-run dce liste la passe", "M-CLASSE-BTP" in sortie.getvalue())
check("pas de llm_appels", not stockage.charger("llm_appels"))

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
