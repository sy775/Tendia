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

print("=== étape 3 : pagination de l'explorer ===")
for i in range(55):
    marche_test(f"TEST-PAGE-{i:02d}", f"Marché pagination {i:02d}", iso(40 + i))
    classer(f"TEST-PAGE-{i:02d}")
stockage.invalider_cache()


def cartes(html):
    return html.count('class="marche-card')


html = client.get("/explorer").get_data(as_text=True)
check("50 cartes par page par défaut", cartes(html) == 50, cartes(html))
check("total affiché (57 ouverts)", "<strong>57</strong> marchés" in html)
check("lien vers la page 2", "page=2" in html)
html = client.get("/explorer?page=2").get_data(as_text=True)
check("page 2 : 7 cartes restantes", cartes(html) == 7, cartes(html))
html = client.get("/explorer?page=99").get_data(as_text=True)
check("page hors bornes ramenée à la dernière", cartes(html) == 7, cartes(html))
html = client.get("/explorer?par_page=10&etat=tous&page=2").get_data(as_text=True)
check("par_page=10 respecté", cartes(html) == 10, cartes(html))
check("filtres conservés dans les liens de pagination",
      re.search(r'href="[^"]*etat=tous[^"]*page=3|href="[^"]*page=3[^"]*etat=tous', html) is not None)
html = client.get("/explorer?par_page=5000&etat=tous").get_data(as_text=True)
check("par_page plafonné à 200 (59 marchés → 1 page)", cartes(html) == 59 and "page=2" not in html,
      cartes(html))
html = client.get("/explorer?par_page=abc&page=-4").get_data(as_text=True)
check("paramètres invalides tolérés", cartes(html) == 50, cartes(html))

print("=== étape 4 : verdict non_classe ===")
marche_test("TEST-NON-CLASSE", "Marché pas encore classé", iso(12))
stockage.invalider_cache()
r = client.get("/")
html = r.get_data(as_text=True)
check("GET / → 200", r.status_code == 200, r.status_code)
check("dashboard : marché BTP classé visible", "TEST-OUVERT-PROCHE" in html)
check("dashboard : marché non classé listé", "TEST-NON-CLASSE" in html)
m = re.search(r'>(\d+)</div>\s*<div class="apt-label"[^>]*>À classer<', html)
check("dashboard : compteur « À classer » séparé = 1", bool(m) and m.group(1) == "1",
      m.group(1) if m else "absent")
check("dashboard : badge « À classer » sur la ligne", "Classification en attente" in html)
h1 = re.search(r'apt-display"[^>]*>\s*(\d+)<span', html)
check("dashboard : le titre ne compte pas les « à classer »",
      bool(h1) and int(h1.group(1)) == html.count('href="/marche/') - 1,
      (h1.group(1) if h1 else None, html.count('href="/marche/')))

html = client.get("/marche/TEST-NON-CLASSE").get_data(as_text=True)
check("fiche non classée : bandeau « Classification en attente »", "bandeau-a-classer" in html)
check("fiche non classée : pas d'anneau de score", '<div class="score-ring' not in html)
html = client.get("/marche/TEST-OUVERT-PROCHE").get_data(as_text=True)
check("fiche classée : pas de bandeau d'attente", "bandeau-a-classer" not in html)

print("=== étape 5 : bloc de décision ===")
from tendia.eligibilite import matching  # noqa: E402

marche_test("TEST-HORS-ZONE", "Réfection voirie test hors zone", iso(20),
            perimetre_geographique="Dept 13", acheteur_code_postal="13001", code_departement=["13"])
classer("TEST-HORS-ZONE")
stockage.invalider_cache()
ev = matching.evaluer(organisme.lire_profil(), stockage.lire("marches", "TEST-OUVERT-PROCHE"))
check("marché de test pertinent pour le profil démo",
      ev["verdict"] in ("tres_pertinent", "pertinent", "a_verifier"), (ev["verdict"], ev["score"]))
html = client.get("/marche/TEST-OUVERT-PROCHE").get_data(as_text=True)
i_bloc, i_titre = html.find('class="bloc-decision'), html.find('class="fiche-title"')
check("fiche pertinente : bloc de décision présent", i_bloc >= 0)
check("bloc avant le titre (en tête de fiche)", 0 <= i_bloc < i_titre, (i_bloc, i_titre))
libelle = {"tres_pertinent": "Très pertinent", "pertinent": "Pertinent", "a_verifier": "À vérifier"}[ev["verdict"]]
check("bloc : verdict et score", f'bd-verdict">{libelle}<' in html and f"Score {ev['score']} / 100" in html)
check("bloc : date limite et jours restants", "5 jours restants" in html)
check("bloc : « Préparer le dossier » inactif, infobulle chantier 3",
      re.search(r'<button[^>]*disabled[^>]*title="[^"]*chantier 3[^"]*"[^>]*>Préparer le dossier<', html) is not None)
check("bloc : rubrique « Ce qui vous manque »", "Ce qui vous manque" in html)

html = client.get("/marche/TEST-HORS-ZONE").get_data(as_text=True)
check("hors zone : manque « Zone d'intervention »", "Zone d&#39;intervention" in html or "Zone d'intervention" in html)
check("hors zone : lien vers la section zones du profil",
      f'href="/profil/bibliotheque/{ID_DEMO}/edit#zones"' in html)

html = client.get("/marche/TEST-NON-CLASSE").get_data(as_text=True)
check("non classé : bandeau d'attente dans le bloc", 'class="bandeau-a-classer"' in html
      and 'bd-verdict">À classer<' in html)
html = client.get("/marche/TEST-CLOS-DATE").get_data(as_text=True)
check("clos : verdict « Clos » prioritaire", 'bd-verdict">Clos<' in html and "Marché clos le " in html)
html = client.get(f"/profil/bibliotheque/{ID_DEMO}/edit").get_data(as_text=True)
check("profil : l'ancre #zones est gérée (data-section)", 'data-section="zones"' in html
      and "location.hash" in html)

organisme.supprimer_profil()
stockage.invalider_cache()
html = client.get("/").get_data(as_text=True)
check("dashboard sans profil : pas de commande CLI", "python -m" not in html)
organisme.activer_profil(ID_DEMO, "bibliotheque")

# --- chantier 2, étape 6 : sources et taux de lecture sur la fiche (détail : test_ui_fiche_sources.py)
print("=== fiche : sources et taux de lecture (brief du mode document) ===")
marche_test("M-SOURCES", "Réfection de toiture", iso(30))
classer("M-SOURCES", "btp_gros_oeuvre")
stockage.ecrire("briefs_extraits", "M-SOURCES", {
    "_meta": {"type": "complet", "mode": "document"}, "synthese_marche": "Réfection de la toiture de l'école.",
    "domaines_metier": [{"code": "btp_gros_oeuvre", "poids": 1.0}],
    "bareme_notation": {"valeur_technique_pct": 60, "valeur_prix_pct": 40},
    "calendrier": {"date_limite_offres": "2026-12-15 12:00"},
    "dossier_candidature": {"pieces_a_fournir": [{"libelle": "DC1", "phase": "candidature"}]},
    "complements_dce": {"visite": {"obligatoire": True, "modalites": "sur rendez-vous"}},
    "montant_marche": {"valeur_estimee_euros": 120000}, "allotissement": {"nb_lots": 2},
    "_sources": {
        "criteres_ponderations": {"piece": "RC.pdf", "page": 7, "extrait": "prix 40 %", "verifie": True},
        "date_limite": {"piece": "RC.pdf", "page": 2, "extrait": "15 décembre 2026", "verifie": True},
        "pieces_exigees": {"piece": "RC.pdf", "page": 5, "extrait": "DC1", "verifie": False},
        "visite": {"piece": "CCTP.pdf", "page": 3, "extrait": "visite obligatoire", "verifie": True},
        "montant": {"piece": "BPU.xlsx", "page": "BPU", "extrait": "total", "verifie": True},
        "lots": None},
    "_lecture": {"pieces": [
        {"nom": "RC.pdf", "type": "RC", "statut": "lu", "pages": 9, "caracteres": 20000, "detail": None},
        {"nom": "plan_masse.pdf", "type": None, "statut": "plan_ignore", "pages": None, "caracteres": None, "detail": "plan"},
        {"nom": "annexes.rar", "type": None, "statut": "format_non_gere", "pages": None, "caracteres": None,
         "detail": "archive .rar non décompressée"}],
        "nb_pieces_texte": 2, "nb_lues": 1, "pct_non_lu": 50.0}})
stockage.invalider_cache()
rep = client.get("/marche/M-SOURCES")
html = " ".join(rep.get_data(as_text=True).split())
check("fiche avec _sources et _lecture : 200", rep.status_code == 200, rep.status_code)
check("source des critères : « Source : RC.pdf p. 7 »", 'data-champ="criteres_ponderations"' in html and "Source : RC.pdf p. 7" in html)
check("source non vérifiée signalée (pièces exigées)",
      "non vérifiée" in html.split('data-champ="pieces_exigees"', 1)[-1].split("</div>", 1)[0])
check("source vérifiée : pas de mention « non vérifiée »",
      "non vérifiée" not in html.split('data-champ="date_limite"', 1)[-1].split("</div>", 1)[0])
check("feuille de tableur : « feuille BPU »", "feuille BPU" in html.split('data-champ="montant"', 1)[-1].split("</div>", 1)[0])
check("champ sans source : rien d'affiché (lots)", 'data-champ="lots"' not in html)
check("taux de lecture en tête du brief : « 1/2 pièces lues »", "1/2 pièces lues" in html)
check("pièce non lue listée avec son statut, plan ignoré non listé",
      "annexes.rar" in html and "format non géré" in html
      and "plan_masse.pdf" not in html.split('class="brief-lecture"', 1)[-1].split("</ul>", 1)[0])

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
