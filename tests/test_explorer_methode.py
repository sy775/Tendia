# -*- coding: utf-8 -*-
"""
tests/test_explorer_methode.py
------------------------------
Tests HORS-LIGNE (chantier 2, étape 1) de la route GET /explorer face aux paramètres
réservés de url_for, avec plus d'une page de résultats (par_page=1, 3 marchés ouverts) :
  - ?_method=XYZ (inconnu) → 400 (auparavant 500 dès qu'il y avait une pagination) ;
  - ?_method=GET → 200 ; ?_anchor=abc → 200 ;
  - les liens de pagination ne contiennent ni _method ni _anchor et conservent
    les autres filtres.
Client de test Flask, base temporaire, profil `profil_btp_demo`, aucun réseau ni LLM.

Lancement : python tests/test_explorer_methode.py
"""
import html as html_lib
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


res = organisme.activer_profil("profil_btp_demo", "exemple")
check("profil démo activé dans la base temporaire", res["ok"], res)
app.config["PROPAGATE_EXCEPTIONS"] = False   # une erreur interne doit se lire comme un 500
client = app.test_client()

AUJ = date.today()
IDS = ["TEST-METH-1", "TEST-METH-2", "TEST-METH-3"]
for i, id_m in enumerate(IDS):
    titre = f"Réfection voirie test méthode {i}"
    stockage.ecrire("marches", id_m, {
        "id": id_m, "titre": titre, "objet": titre, "acheteur_nom": "Commune de Test",
        "date_publication": (AUJ - timedelta(days=20)).isoformat(),
        "date_limite_depot": (AUJ + timedelta(days=10 + i)).isoformat(),
        "type_marche": "TRAVAUX", "nature": "APPEL_OFFRE", "notice_type": "5 | 1",
        "perimetre_geographique": "Dept 75", "acheteur_code_postal": "75001",
        "code_departement": ["75"], "cpv": ["45233140"]})
    stockage.ecrire("classifications_ia", id_m, {
        "domaines_metier": [{"code": "btp_voirie_reseaux", "poids": 1.0}],
        "synthese_marche": f"Synthèse de test {id_m}", "raison_classification": None})
stockage.invalider_cache()


def obtenir(url):
    """(code HTTP, html) ; une exception non gérée par Flask est rendue comme un 500."""
    try:
        r = client.get(url)
        return r.status_code, r.get_data(as_text=True)
    except Exception as e:  # noqa: BLE001
        return 500, f"exception {type(e).__name__}: {e}"


def liens_pagination(page_html):
    """href (désencodés) qui portent un paramètre page=N."""
    hrefs = [html_lib.unescape(h) for h in re.findall(r'href="([^"]*)"', page_html)]
    return [h for h in hrefs if re.search(r"[?&]page=\d+", h)]


def cartes(page_html):
    return page_html.count('class="marche-card')


print("=== témoin : pagination sans paramètre réservé ===")
code, page = obtenir("/explorer?par_page=1&etat=tous")
liens = liens_pagination(page)
check("GET /explorer?par_page=1 → 200", code == 200, code)
check("1 carte par page, plus d'une page", cartes(page) == 1 and any("page=2" in h for h in liens),
      (cartes(page), liens))

print("=== _method inconnu → 400 ===")
code, page = obtenir("/explorer?par_page=1&etat=tous&_method=XYZ")
check("?_method=XYZ avec plusieurs pages → 400 (pas 500)", code == 400, code)
code, page = obtenir("/explorer?_method=XYZ&par_page=1")
check("?_method=XYZ en premier paramètre → 400", code == 400, code)
code, page = obtenir("/explorer?par_page=1&page=2&_method=XYZ")
check("?_method=XYZ en page 2 → 400", code == 400, code)
code, page = obtenir("/explorer?_method=XYZ")
check("?_method=XYZ avec une seule page → 400 aussi", code == 400, code)
code, page = obtenir("/explorer?par_page=1&_method=" + "Z" * 2000)
check("?_method très long → 400", code == 400, code)

print("=== _method=GET → 200 ===")
code, page = obtenir("/explorer?par_page=1&etat=tous&_method=GET")
liens = liens_pagination(page)
check("?_method=GET avec plusieurs pages → 200", code == 200, code)
check("la page est rendue (1 carte) avec des liens de pagination",
      cartes(page) == 1 and any("page=2" in h for h in liens), (cartes(page), liens))
check("liens de pagination sans _method", liens and not any("_method" in h for h in liens), liens)
check("liens de pagination : filtre etat=tous conservé",
      liens and all("etat=tous" in h for h in liens), liens)
check("liens de pagination : par_page=1 conservé",
      liens and all(re.search(r"[?&]par_page=1(&|$)", h) for h in liens), liens)
code, page = obtenir("/explorer?par_page=1&etat=tous&_method=GET&page=2")
liens = liens_pagination(page)
check("?_method=GET en page 2 → 200, liens sans _method",
      code == 200 and liens and not any("_method" in h for h in liens), (code, liens))

print("=== _anchor=abc → 200 ===")
code, page = obtenir("/explorer?par_page=1&etat=tous&_anchor=abc")
liens = liens_pagination(page)
check("?_anchor=abc avec plusieurs pages → 200", code == 200, code)
check("la page est rendue (1 carte) avec des liens de pagination",
      cartes(page) == 1 and any("page=2" in h for h in liens), (cartes(page), liens))
check("liens de pagination sans _anchor", liens and not any("_anchor" in h for h in liens), liens)
check("l'ancre n'est pas recopiée en fragment (#abc)",
      liens and not any(h.endswith("#abc") for h in liens), liens)
check("liens de pagination : filtres conservés",
      liens and all("etat=tous" in h and re.search(r"[?&]par_page=1(&|$)", h) for h in liens),
      liens)

print("=== les deux ensemble, et les autres filtres ===")
code, page = obtenir("/explorer?par_page=1&etat=ouverts&_method=GET&_anchor=abc")
liens = liens_pagination(page)
check("?_method=GET&_anchor=abc → 200", code == 200, code)
check("liens sans _method ni _anchor",
      liens and not any("_method" in h or "_anchor" in h for h in liens), liens)
check("filtre etat=ouverts conservé", liens and all("etat=ouverts" in h for h in liens), liens)
code, page = obtenir("/explorer?par_page=1&etat=tous&_method=XYZ&_anchor=abc")
check("_method inconnu + _anchor → 400", code == 400, code)

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
