# -*- coding: utf-8 -*-
"""
tests/test_ui_routes.py
-----------------------
Tests HORS-LIGNE des routes Flask (chantier 1b) : client de test Flask sur une
base temporaire (tests/base_temporaire.py), profil `profil_btp_demo` actif,
marchés synthétiques. Aucun appel réseau, aucun LLM, rien n'est écrit dans
data/tendia.db.

Lancement : python tests/test_ui_routes.py
"""
import os
import re
import sys
from datetime import date, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from base_temporaire import isoler_stockage

isoler_stockage()

from tendia.core import stockage  # noqa: E402
from tendia.eligibilite import organisme  # noqa: E402
from tendia.ui.app import app  # noqa: E402

ok = ko = 0


def check(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}  {detail}")


ID_DEMO = "profil_btp_demo"
res = organisme.activer_profil(ID_DEMO, "exemple")
check("profil démo activé dans la base temporaire", res["ok"], res)
client = app.test_client()


def formulaire_profil(profil: dict, references: list) -> dict:
    """Champs POST minimaux pour réenregistrer le profil démo BTP à l'identique,
    avec la liste de références donnée (dicts de champs bruts)."""
    btp = profil["profils_sectoriels"]["btp"]
    form = {
        "presets_couverts": profil.get("presets_couverts") or ["btp"],
        "zones_intervention": profil.get("zones_intervention") or [],
        "domaines_couverts": profil.get("domaines_couverts") or [],
    }
    for cle in ("corps_de_metier", "types_ouvrages", "types_clients_publics"):
        form[f"sect.btp.{cle}"] = btp.get(cle) or []
    for i, ref in enumerate(references):
        for champ, val in ref.items():
            form[f"references_chantiers[{i}].{champ}"] = val
    return form


print("=== étape 1 : profil BTP enregistrable ===")
r = client.get("/profil")
check("GET /profil → 200", r.status_code == 200, r.status_code)

r = client.get(f"/profil/bibliotheque/{ID_DEMO}/edit")
html = r.get_data(as_text=True)
check("GET édition → 200", r.status_code == 200, r.status_code)
m = re.search(r'name="references_chantiers\[0\]\.type_ouvrage".*?</select>', html, re.S)
options = re.findall(r'<option value="([^"]+)"', m.group(0)) if m else []
check("select « Type ouvrage » alimenté (≥ 10 valeurs)", len(options) >= 10, options)
check("valeur du schéma BTP proposée (etablissement_scolaire)",
      "etablissement_scolaire" in options, options)
ref0 = organisme.lire_profil_bibliotheque(ID_DEMO)["profils_sectoriels"]["btp"]["references_chantiers"][0]
check("valeur enregistrée présélectionnée",
      bool(m) and f'value="{ref0["type_ouvrage"]}" selected' in m.group(0), ref0.get("type_ouvrage"))

profil = organisme.lire_profil_bibliotheque(ID_DEMO)
nouvelle = {"annee": "2025", "client": "Commune test", "ouvrage": "Réfection cour école test 1b",
            "type_ouvrage": "etablissement_scolaire", "montant_eur_ht": "180000",
            "duree_mois": "3", "statut": "livre", "corps_etat": "vrd", "notes": ""}
r = client.post(f"/profil/bibliotheque/{ID_DEMO}/edit",
                data=formulaire_profil(profil, [nouvelle]))
check("POST référence valide → 302", r.status_code in (200, 302), r.status_code)
relu = organisme.lire_profil_bibliotheque(ID_DEMO)["profils_sectoriels"]["btp"]["references_chantiers"]
check("référence relue en base", any(x.get("ouvrage") == "Réfection cour école test 1b"
                                     and x.get("type_ouvrage") == "etablissement_scolaire"
                                     and x.get("montant_eur_ht") == 180000 for x in relu), relu)
actif = organisme.charger_actif()
check("profil actif mis à jour aussi", any(x.get("ouvrage") == "Réfection cour école test 1b"
                                           for x in actif["profils_sectoriels"]["btp"]["references_chantiers"]))

invalide = dict(nouvelle, type_ouvrage="", ouvrage="Référence sans type")
r = client.post(f"/profil/bibliotheque/{ID_DEMO}/edit",
                data=formulaire_profil(profil, [invalide]))
html = r.get_data(as_text=True)
check("POST invalide → 200 (formulaire réaffiché)", r.status_code == 200, r.status_code)
check("le message nomme le champ fautif", "« Type d&#39;ouvrage » est obligatoire" in html
      or "« Type d'ouvrage » est obligatoire" in html)
check("message affiché sous le champ", 'class="ref-erreur' in html)
relu = organisme.lire_profil_bibliotheque(ID_DEMO)["profils_sectoriels"]["btp"]["references_chantiers"]
check("base inchangée après POST invalide",
      not any(x.get("ouvrage") == "Référence sans type" for x in relu))

r = client.post(f"/profil/bibliotheque/{ID_DEMO}/edit",
                data=formulaire_profil(profil, [dict(nouvelle, montant_eur_ht="abc")]))
check("montant non numérique : message nommant « Montant € HT »",
      "« Montant € HT » doit être un nombre" in r.get_data(as_text=True))

print("=== étape 2 : marchés clos ===")
AUJ = date.today()


def iso(jours: int) -> str:
    return (AUJ + timedelta(days=jours)).isoformat()


def marche_test(id_m, titre, limite, **extra):
    m = {"id": id_m, "titre": titre, "objet": titre, "acheteur_nom": "Commune de Test",
         "date_publication": iso(-20), "date_limite_depot": limite,
         "type_marche": "TRAVAUX", "nature": "APPEL_OFFRE", "notice_type": "5 | 1",
         "perimetre_geographique": "Dept 75", "acheteur_code_postal": "75001",
         "code_departement": ["75"], "cpv": ["45233140"]}
    m.update(extra)
    stockage.ecrire("marches", id_m, m)
    return m


def classer(id_m, code="btp_voirie_reseaux"):
    stockage.ecrire("classifications_ia", id_m, {
        "domaines_metier": [{"code": code, "poids": 1.0}],
        "synthese_marche": f"Synthèse de test {id_m}", "raison_classification": None})


marche_test("TEST-OUVERT-LOIN", "Réfection voirie test ouvert loin", iso(30))
marche_test("TEST-OUVERT-PROCHE", "Réfection voirie test ouvert proche", iso(5))
marche_test("TEST-CLOS-DATE", "Réfection voirie test clos par date", iso(-3))
marche_test("TEST-CLOS-ATTRIB", "Réfection voirie test attribué", iso(10),
            nature="ATTRIBUTION", notice_type="10 | 6")
for i in ("TEST-OUVERT-LOIN", "TEST-OUVERT-PROCHE", "TEST-CLOS-DATE", "TEST-CLOS-ATTRIB"):
    classer(i)
stockage.invalider_cache()

r = client.get("/explorer")
html = r.get_data(as_text=True)
check("GET /explorer → 200 (raison_classification None toléré)", r.status_code == 200, r.status_code)
check("explorer par défaut : marché ouvert présent", "TEST-OUVERT-LOIN" in html)
check("explorer par défaut : clos par date absent", "TEST-CLOS-DATE" not in html)
check("explorer par défaut : avis d'attribution absent", "TEST-CLOS-ATTRIB" not in html)
check("explorer : tri par date limite croissante (proche avant loin)",
      0 <= html.find("TEST-OUVERT-PROCHE") < html.find("TEST-OUVERT-LOIN"))
r = client.get("/explorer?etat=clos")
html = r.get_data(as_text=True)
check("explorer ?etat=clos : clos par date présent", "TEST-CLOS-DATE" in html)
check("explorer ?etat=clos : attribution présente", "TEST-CLOS-ATTRIB" in html)
check("explorer ?etat=clos : ouvert absent", "TEST-OUVERT-LOIN" not in html)
check("explorer ?etat=clos : libellé « clos le … »", "clos le " in html)
html = client.get("/explorer?etat=tous").get_data(as_text=True)
check("explorer ?etat=tous : ouverts et clos", "TEST-OUVERT-LOIN" in html and "TEST-CLOS-DATE" in html)

r = client.get("/")
html = r.get_data(as_text=True)
check("GET / → 200", r.status_code == 200, r.status_code)
check("dashboard : aucun clos dans la liste", "TEST-CLOS-DATE" not in html and "TEST-CLOS-ATTRIB" not in html)
check("dashboard : lien vers les clos de l'explorer", "etat=clos" in html)

r = client.get("/marche/TEST-CLOS-DATE")
html = r.get_data(as_text=True)
check("fiche d'un clos → 200", r.status_code == 200, r.status_code)
check("fiche : bandeau « Marché clos le … »", "Marché clos le " in html)
check("fiche : plus de « J−- »", "J−-" not in html)
html = client.get("/marche/TEST-OUVERT-LOIN").get_data(as_text=True)
check("fiche d'un ouvert : pas de bandeau clos", "bandeau-clos" not in html)

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
