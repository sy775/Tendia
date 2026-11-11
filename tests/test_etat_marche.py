# -*- coding: utf-8 -*-
"""
tests/test_etat_marche.py
-------------------------
Tests HORS-LIGNE de tendia.core.etat_marche (chantier 1b) : est_attribution,
est_clos, est_actif, date_cloture, et unicité de la définition dans le dépôt.

Lancement : python tests/test_etat_marche.py
"""
import re
import sys
from datetime import date

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tendia.core import etat_marche as E
from tendia.core.chemins import RACINE_DEPOT

ok = ko = 0


def check(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}  {detail}")


J = date(2026, 11, 11)

print("=== est_attribution ===")
check("nature ATTRIBUTION", E.est_attribution({"nature": "ATTRIBUTION", "notice_type": "10 | 6"}))
check("nature_marche (ancien nom)", E.est_attribution({"nature_marche": "Avis d'attribution"}))
check("ContractAwardNotice à la racine", E.est_attribution({"notice_type": "ContractAwardNotice"}))
check("ContractAwardNotice dans donnees (dict)",
      E.est_attribution({"donnees": {"notice_type": "ContractAwardNotice"}}))
check("ContractAwardNotice dans donnees (JSON texte)",
      E.est_attribution({"donnees": '{"notice_type": "ContractAwardNotice"}'}))
check("notice_type BOAMP « 10|6 » sans nature", E.est_attribution({"notice_type": "10|6"}))
check("appel d'offres ≠ attribution", not E.est_attribution({"nature": "APPEL_OFFRE", "notice_type": "5 | 1"}))
check("notice_type 100 ≠ 10", not E.est_attribution({"notice_type": "100 | 1"}))
check("rectificatif ≠ attribution", not E.est_attribution({"nature": "RECTIFICATIF"}))
check("donnees illisibles tolérées", not E.est_attribution({"donnees": "{pas du json"}))

print("=== est_clos / est_actif ===")
ouvert = {"date_limite_depot": "2026-12-01T12:00:00", "date_publication": "2026-10-01"}
du_jour = {"date_limite_depot": "2026-11-11", "date_publication": "2026-10-01"}
expire = {"date_limite_depot": "2026-11-10", "date_publication": "2026-09-01"}
attrib = {"nature": "ATTRIBUTION", "date_limite_depot": "2026-12-01", "date_publication": "2026-11-05"}
sans_date_recent = {"date_publication": "2026-10-01"}
sans_date_ancien = {"date_publication": "2026-08-01"}
check("date limite future → ouvert", not E.est_clos(ouvert, J) and E.est_actif(ouvert, aujourdhui=J))
check("date limite du jour → encore ouvert", not E.est_clos(du_jour, J) and E.est_actif(du_jour, aujourdhui=J))
check("date limite d'hier → clos", E.est_clos(expire, J) and not E.est_actif(expire, aujourdhui=J))
check("attribution avec date future → clos", E.est_clos(attrib, J) and not E.est_actif(attrib, aujourdhui=J))
check("sans date, publié il y a 41 j → actif, pas clos",
      E.est_actif(sans_date_recent, aujourdhui=J) and not E.est_clos(sans_date_recent, J))
check("sans date, publié il y a 102 j → ni actif ni clos",
      not E.est_actif(sans_date_ancien, aujourdhui=J) and not E.est_clos(sans_date_ancien, J))
check("fenêtre paramétrable", E.est_actif(sans_date_ancien, fenetre_jours=120, aujourdhui=J))
check("rien du tout → ni actif ni clos", not E.est_actif({}, aujourdhui=J) and not E.est_clos({}, J))

print("=== date_cloture ===")
check("expiré → date limite", E.date_cloture(expire, J) == date(2026, 11, 10))
check("attribution → date de publication de l'avis", E.date_cloture(attrib, J) == date(2026, 11, 5))
check("ouvert → None", E.date_cloture(ouvert, J) is None)

print("=== définition unique dans le dépôt ===")
motifs = re.compile(r"^\s*def (_?est_actif|est_attribution|est_clos)\(", re.M)
doublons = []
for dossier in ("src", "scripts"):
    for f in (RACINE_DEPOT / dossier).rglob("*.py"):
        if "_archive" in f.parts or f.name == "etat_marche.py":
            continue
        if motifs.search(f.read_text(encoding="utf-8", errors="replace")):
            doublons.append(str(f.relative_to(RACINE_DEPOT)))
check("aucune autre définition de est_actif / est_attribution / est_clos", not doublons, doublons)

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
