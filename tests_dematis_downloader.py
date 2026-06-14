"""
tests_dematis_downloader.py
---------------------------
Tests HORS-LIGNE de dematis_downloader (aucun réseau, captcha mocké).
Couvre les parsers purs + le workflow complet via une fausse Session.

Lancement : python tests_dematis_downloader.py
"""
import os
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import dematis_downloader as D

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


# ===========================================================================
# est_url_dematis
# ===========================================================================
print("=== est_url_dematis ===")
check("sous-domaine acheteur",
      D.est_url_dematis("https://hautsdeseine-habitat.e-marchespublics.com/pack/annonce_marche_public_1_2.html"))
check("racine e-marchespublics",
      D.est_url_dematis("https://www.e-marchespublics.com/x"))
check("autre plateforme -> False",
      not D.est_url_dematis("https://www.marches-publics.info/x?IDM=1"))
check("vide -> False", not D.est_url_dematis(""))


# ===========================================================================
# _extraire_lien_anonyme (2 variantes)
# ===========================================================================
print("\n=== _extraire_lien_anonyme ===")
BASE = "https://sdis13.e-marchespublics.com/pack/annonce_marche_public_100_200.html"
H1 = '<a href="/dossier_de_consultation_marche_public_anonyme_abc123DEF456ghi789jkl0">Accès anonyme</a>'
url1, var1 = D._extraire_lien_anonyme(H1, BASE)
check("variante dossier_de_consultation détectée", var1 == "dossier_de_consultation")
check("URL absolue construite",
      url1 == "https://sdis13.e-marchespublics.com/dossier_de_consultation_marche_public_anonyme_abc123DEF456ghi789jkl0")

H2 = '<a href="https://x.e-marchespublics.com/acces_dce_marche_public_anonyme_TOKEN999.html">DCE</a>'
url2, var2 = D._extraire_lien_anonyme(H2, BASE)
check("variante acces_dce détectée", var2 == "acces_dce")
check("URL absolue déjà complète conservée", url2.endswith("acces_dce_marche_public_anonyme_TOKEN999.html"))

check("aucun lien -> (None, None)",
      D._extraire_lien_anonyme("<a href='/autre.html'>x</a>", BASE) == (None, None))

# entités HTML (&amp;) décodées
H3 = '<a href="/dossier_de_consultation_marche_public_anonyme_ZZ?a=1&amp;b=2">x</a>'
url3, _ = D._extraire_lien_anonyme(H3, BASE)
check("entités HTML gérées", url3 is not None and "anonyme_ZZ" in url3)

# RÉEL : 2 liens (token court 32-hex invalide + token long 40-hex valide) →
# le plus long doit être essayé en 1er.
H_MULTI = (
    '<a href="/dossier_de_consultation_marche_public_anonyme_711623512b14a4f6e6492b7301560384">ACCÈS</a>'
    '<a href="/dossier_de_consultation_marche_public_anonyme_47e281181057def02529b1562c99c10787b7ac87">ACCÈS</a>')
liens = D._extraire_liens_anonymes(H_MULTI, BASE)
check("2 candidats extraits", len(liens) == 2)
check("token le plus long en premier", liens[0][0].endswith("47e281181057def02529b1562c99c10787b7ac87"))


# ===========================================================================
# _extraire_lien_onglet_dossier
# ===========================================================================
print("\n=== _extraire_lien_onglet_dossier ===")
H_ONGLETS = '''
<ul><li><a href="/pack/avis_1.html">Avis</a></li>
<li><a href="/pack/reglement_1.html">Règlement</a></li>
<li><a href="/pack/dossier_consultation_1.html">Dossier de consultation</a></li></ul>'''
od = D._extraire_lien_onglet_dossier(H_ONGLETS, BASE)
check("onglet dossier trouvé", od is not None and "dossier" in od.lower())
check("n'attrape pas le lien anonyme",
      D._extraire_lien_onglet_dossier('<a href="/x_anonyme_1">y</a>', BASE) is None)


# ===========================================================================
# _extraire_captcha_img
# ===========================================================================
print("\n=== _extraire_captcha_img ===")
H_IMG = '<form><img src="/securimage/captcha_show.php?ts=12"></form>'
img = D._extraire_captcha_img(H_IMG, BASE)
check("image captcha détectée (securimage/captcha)", img is not None and "captcha" in img.lower())
check("pas d'image captcha -> None",
      D._extraire_captcha_img('<img src="/logo.png">', BASE) is None)


# ===========================================================================
# _extraire_form_captcha
# ===========================================================================
print("\n=== _extraire_form_captcha ===")
H_FORM = '''
<form method="POST" action="/pack/recherche/avisdetails/telecharger_anonyme">
  <input type="hidden" name="csrf" value="TOK42">
  <input type="hidden" name="id_consultation" value="555">
  <img src="/captcha/c.png">
  <input type="text" name="saisie_captcha" value="">
  <input type="submit" name="envoyer" value="ENVOYEZ">
</form>'''
form = D._extraire_form_captcha(H_FORM, BASE)
check("form détecté", form is not None)
check("action absolue", form and form["action"].endswith("/telecharger_anonyme"))
check("method post", form and form["method"] == "post")
check("hidden conservés", form and form["champs"].get("csrf") == "TOK42" and form["champs"].get("id_consultation") == "555")
check("submit inclus dans champs (réel HAR : submit='')", form and "envoyer" in form["champs"])
check("champ captcha détecté", form and form["champs_captcha"] == ["saisie_captcha"])


# ===========================================================================
# _extraire_fichiers_telechargeables
# ===========================================================================
print("\n=== _extraire_fichiers_telechargeables ===")
H_LISTE = '''
<a href="/download/RC.pdf">Règlement de consultation</a>
<a href="/download/CCAP.pdf">CCAP</a>
<a href="/telechargement/getdocument?id=9">Acte d'engagement</a>
<a href="/dce_complet.zip">DCE complet</a>
<a href="#">ancre vide</a>
<a href="javascript:void(0)">js</a>
<a href="/page.html">page non-doc</a>'''
fichiers = D._extraire_fichiers_telechargeables(H_LISTE, BASE)
urls = [f["url"] for f in fichiers]
check("PDF récupérés", any(u.endswith("RC.pdf") for u in urls) and any(u.endswith("CCAP.pdf") for u in urls))
check("lien par mot-clé (getdocument) récupéré", any("getdocument" in u for u in urls))
check("zip récupéré", any(u.endswith("dce_complet.zip") for u in urls))
check("ancre vide / js ignorées", not any("void" in u for u in urls))
check("page.html non-doc ignorée", not any(u.endswith("/page.html") for u in urls))
check("4 pièces au total", len(fichiers) == 4)


# ===========================================================================
# Workflow complet (FakeSession + 2captcha mocké)
# ===========================================================================
print("\n=== telecharger_dce (workflow complet, mocké) ===")

URL_DCE = "https://sdis13.e-marchespublics.com/pack/annonce_marche_public_100_200.html"
HTML_ANNONCE = (
    '<html><body><h1>Annonce</h1>'
    '<a href="/dossier_de_consultation_marche_public_anonyme_TOK1234567890ABCDEFghij">'
    'Accès anonyme au dossier</a></body></html>')
HTML_ANONYME = (
    '<html><body><form method="post" action="/pack/recherche/avisdetails/dl">'
    '<input type="hidden" name="csrf" value="ZZZ">'
    '<img src="/captcha/show.png">'
    '<input type="text" name="captcha_input">'
    '<input type="submit" value="ENVOYEZ"></form></body></html>')
HTML_FICHIERS = (
    '<html><body>'
    '<a href="/download/RC.pdf">RC</a>'
    '<a href="/download/CCAP.pdf">CCAP</a>'
    '<a href="/download/CCTP.pdf">CCTP</a>'
    '</body></html>')


class FakeResponse:
    def __init__(self, status_code=200, text="", content=b"", url="", headers=None):
        self.status_code = status_code
        self.text = text
        self.content = content
        self.url = url
        self.headers = headers or {}
        self.encoding = "utf-8"

    def iter_content(self, chunk_size=65536):
        yield self.content


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.proxies = {}

    def get(self, url, **kwargs):
        low = url.lower()
        if "annonce_marche_public" in low:
            return FakeResponse(200, text=HTML_ANNONCE, url=url)
        if "anonyme" in low:
            return FakeResponse(200, text=HTML_ANONYME, url=url)
        if "captcha" in low:
            return FakeResponse(200, content=b"\x89PNG\r\nfakeimg", url=url)
        if "/download/" in low:
            nom = os.path.basename(url)
            return FakeResponse(200, content=b"%PDF-1.4 fake pdf bytes", url=url,
                                headers={"Content-Disposition": f'attachment; filename="{nom}"'})
        return FakeResponse(404, url=url)

    def post(self, url, **kwargs):
        # POST captcha → page liste des fichiers
        return FakeResponse(200, text=HTML_FICHIERS, url=url)


# Monkeypatch : session factice, pas de sleep, captcha résolu, pas de ban.
D.http_humain.creer_session_humaine = lambda *a, **k: FakeSession()
D.http_humain.attendre_inter_etapes = lambda *a, **k: None
D.http_humain.ressemble_a_page_ban = lambda html: False
D._resoudre_captcha_2captcha = lambda *a, **k: "ab12cd"

_tmp = tempfile.mkdtemp(prefix="test_dematis_")
try:
    res = D.telecharger_dce(URL_DCE, _tmp, api_key_2captcha="TEST_KEY", verbose=False)
    check("workflow ok", res.get("ok") is True)
    check("3 fichiers téléchargés", len(res.get("fichiers_telecharges", [])) == 3)
    check("1 captcha résolu", res.get("nb_captcha_resolus") == 1)
    check("variante lien renseignée", res.get("variante_lien") == "dossier_de_consultation")
    noms = sorted(os.path.basename(f) for f in res.get("fichiers_telecharges", []))
    check("noms de fichiers corrects", noms == ["CCAP.pdf", "CCTP.pdf", "RC.pdf"])
finally:
    shutil.rmtree(_tmp, ignore_errors=True)


# Workflow : lien anonyme introuvable -> erreur étape dossier
print("\n=== telecharger_dce : lien anonyme absent ===")

class FakeSessionSansLien(FakeSession):
    def get(self, url, **kwargs):
        if "annonce_marche_public" in url.lower():
            return FakeResponse(200, text="<html><body>aucun lien</body></html>", url=url)
        return super().get(url, **kwargs)


D.http_humain.creer_session_humaine = lambda *a, **k: FakeSessionSansLien()
_tmp2 = tempfile.mkdtemp(prefix="test_dematis_")
try:
    res2 = D.telecharger_dce(URL_DCE, _tmp2, api_key_2captcha="TEST_KEY", verbose=False)
    check("échec propre (pas d'exception)", res2.get("ok") is False)
    check("étape erreur = dossier", res2.get("etape_erreur") == "dossier")
finally:
    shutil.rmtree(_tmp2, ignore_errors=True)


# ===========================================================================
print(f"\n=== {ok} OK / {ko} KO ===")
sys.exit(1 if ko else 0)
