"""
tests_dematis_workflow_har.py
-----------------------------
Tests HORS-LIGNE du workflow Dematis, MOCKÉS À PARTIR DU HAR de référence
(BOAMP-26-57070, `dematis exemple/hautsdeseine-habitat.e-marchespublics.com.har`).

Le HAR fige la vérité terrain du chemin anonyme :
  1. page annonce : 2 liens anonymes (token 32 hex LEURRE + token 40 hex BON)
  2. GET  /dossier_de_consultation_marche_public_anonyme_<token40>   → 200 captcha
       form `inscriptionEntreprise` : captcha[id] (32 hex) + captcha[input]
       + submit + LEURRE captchaResult ; image /captcha/<captcha_id>.png
  3. POST (même URL) captcha[id]+captcha[input]+submit
       → 302 Location: /acces_dce_marche_public_anonyme_<token40>
  4. GET  /acces_dce_marche_public_anonyme_<token40>
       → 17 pièces servies par private.e-marchespublics.com/dce/getfile.php

La FakeSession ci-dessous rejoue EXACTEMENT cette séquence (statuts, 302,
Location, leurres) ; le solveur 2captcha et les délais humains sont neutralisés.

Lancement : python tests_dematis_workflow_har.py
"""
import json
import os
import re
import shutil
import sys
import tempfile
from urllib.parse import urljoin, urlparse, parse_qs

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import dematis_downloader as D

ok = 0
ko = 0


def check(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}" + (f"  ({detail})" if detail else ""))


# ===========================================================================
# Fixtures issues du HAR / des captures réelles
# ===========================================================================
# Valeurs RÉELLES du HAR (consultation BOAMP-26-57070). Le token 32 hex (leurre)
# est synthétique : la page annonce n'est pas dans le HAR, on la reconstruit.
HOST = "https://hautsdeseine-habitat.e-marchespublics.com"
TOKEN40 = "0a4132fe52e8f0dc27494ab7a9993c8e71690db0"   # SHA-1 (HAR) : le BON
TOKEN32 = "711623512b14a4f6e6492b7301560384"           # MD5 : LEURRE (synthétique)
CAPTCHA_ID = "9532147cd6a1edbf99b0260579da213c"        # captcha[id] (HAR)
SOLUTION = "sun3tu"                                     # solution réelle (HAR)

URL_ANNONCE = f"{HOST}/pack/annonce_marche_public_6038_1162351.html"
URL_DOSSIER40 = f"{HOST}/dossier_de_consultation_marche_public_anonyme_{TOKEN40}"
URL_DOSSIER32 = f"{HOST}/dossier_de_consultation_marche_public_anonyme_{TOKEN32}"
URL_ACCES40 = f"{HOST}/acces_dce_marche_public_anonyme_{TOKEN40}"
URL_IMG = f"{HOST}/captcha/{CAPTCHA_ID}.png"

# Page annonce : expose les DEUX liens (leurre 32 hex listé EN PREMIER dans le
# HTML, exprès, pour vérifier qu'on ne le suit jamais en premier).
HTML_ANNONCE = f"""<html><body>
  <a href="/dossier_de_consultation_marche_public_anonyme_{TOKEN32}">Accédez (leurre)</a>
  <a href="/dossier_de_consultation_marche_public_anonyme_{TOKEN40}">Accédez au dossier anonyme</a>
</body></html>"""

# Page captcha (corps vide dans le HAR → reconstruit fidèlement depuis la
# capture _dematis_captcha_47e28118.html : form inscriptionEntreprise).
HTML_CAPTCHA = f"""<html><body>
 <form method="post" id="inscriptionEntreprise" name="inscriptionEntreprise">
   <input type="hidden" name="captcha[id]" value="{CAPTCHA_ID}" id="captcha-id"/>
   <img src="/captcha/{CAPTCHA_ID}.png" alt="captcha"/>
   <input type="text" name="captcha[input]" class="txt-form" id="captcha-input" />
   <input type="submit" name="submit" id="submit" value="" />
   <input id="captchaTxt" type="text" name="captchaResult" size="10" />
 </form>
</body></html>"""

# Page d'accueil (ce que renvoie le LEURRE 32 hex après redirection).
HTML_ACCUEIL = "<html><body><h1>Bienvenue</h1></body></html>"


def _charger_acces_dce_depuis_har():
    """Corps réel de la page acces_dce extrait du HAR (liste des 17 getfile.php)."""
    har_path = os.path.join("dematis exemple",
                            "hautsdeseine-habitat.e-marchespublics.com.har")
    if not os.path.exists(har_path):
        return None
    har = json.load(open(har_path, encoding="utf-8"))
    for e in har["log"]["entries"]:
        u = e["request"]["url"]
        if "acces_dce_marche_public_anonyme" in u and e["request"]["method"] == "GET":
            txt = e["response"].get("content", {}).get("text") or ""
            if txt:
                return txt
    return None


HTML_ACCES_DCE = _charger_acces_dce_depuis_har()


# ===========================================================================
# Fake HTTP (rejoue le HAR)
# ===========================================================================
class FakeResponse:
    def __init__(self, status_code, text="", content=b"", url="", headers=None):
        self.status_code = status_code
        self.text = text
        self.content = content if content else (text.encode("utf-8") if text else b"")
        self.url = url
        self.headers = headers or {}
        self.encoding = "utf-8"

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]


class FakeSession:
    """Rejoue la séquence HAR. Compteurs pour les assertions du test."""
    def __init__(self, captcha_echecs_avant_succes=0):
        self.captcha_echecs_avant_succes = captcha_echecs_avant_succes
        self.posts = []            # (url, data)
        self.gets = []             # url
        self.tentatives_post = 0
        self.urls_dossier_vues = []

    # --- GET ---
    def get(self, url, **kw):
        self.gets.append(url)
        path = urlparse(url).path

        if url == URL_ANNONCE:
            return FakeResponse(200, text=HTML_ANNONCE, url=url)

        if url == URL_DOSSIER40:
            self.urls_dossier_vues.append(url)
            return FakeResponse(200, text=HTML_CAPTCHA, url=url)

        # LEURRE 32 hex : redirige vers l'accueil (allow_redirects=True → url='/').
        if url == URL_DOSSIER32:
            return FakeResponse(200, text=HTML_ACCUEIL, url=f"{HOST}/")

        if url == URL_IMG:
            return FakeResponse(200, content=b"\x89PNG\r\nfakecaptcha", url=url)

        if url == URL_ACCES40:
            return FakeResponse(200, text=HTML_ACCES_DCE, url=url)

        if "getfile.php" in url:
            qs = parse_qs(urlparse(url).query)
            # le token anonyme doit être propagé dans chaque getfile.php
            assert qs.get("anonyme", [""])[0] == TOKEN40, "token anonyme manquant/incorrect"
            return FakeResponse(200, content=b"%PDF-1.4 contenu factice", url=url,
                                headers={"Content-Type": "application/pdf"})

        return FakeResponse(404, url=url)

    # --- POST ---
    def post(self, url, data=None, **kw):
        self.posts.append((url, data or {}))
        self.tentatives_post += 1
        data = data or {}

        # Le POST DOIT viser la même URL dossier 40 hex.
        if url != URL_DOSSIER40:
            return FakeResponse(404, url=url)

        bonne_solution = data.get("captcha[input]") == SOLUTION
        encore_echec = self.tentatives_post <= self.captcha_echecs_avant_succes

        if bonne_solution and not encore_echec:
            # 302 vers acces_dce (allow_redirects=False → on lit Location).
            return FakeResponse(302, url=url,
                                headers={"Location": f"/acces_dce_marche_public_anonyme_{TOKEN40}"})
        # captcha refusé → re-render de la page captcha (200, pas de 302).
        return FakeResponse(200, text=HTML_CAPTCHA, url=url)


def _neutraliser_delais_et_captcha(solution=SOLUTION):
    D.http_humain.attendre_inter_etapes = lambda *a, **k: 0.0
    D.http_humain.attendre_humain = lambda *a, **k: 0.0
    D.http_humain.ressemble_a_page_ban = lambda html: False
    D._resoudre_captcha_2captcha = lambda image_bytes, api_key, verbose=False: solution


# ===========================================================================
# Fixtures chargées ?
# ===========================================================================
print("=== fixtures HAR ===")
check("HAR acces_dce chargé", bool(HTML_ACCES_DCE),
      "HAR introuvable ou corps acces_dce vide")
if HTML_ACCES_DCE:
    check("HAR contient bien des getfile.php", "getfile.php" in HTML_ACCES_DCE)


# ===========================================================================
# Parsers purs sur fixtures HAR
# ===========================================================================
print("\n=== parsers (fixtures HAR) ===")
liens = D._extraire_liens_anonymes(HTML_ANNONCE, URL_ANNONCE)
check("2 liens anonymes détectés", len(liens) == 2, f"{len(liens)}")
check("token 40 hex (SHA-1) essayé EN PREMIER",
      liens and liens[0][0].rsplit("anonyme_", 1)[-1] == TOKEN40,
      liens[0][0] if liens else "vide")
check("token 32 hex (leurre) relégué en dernier",
      liens and liens[-1][0].rsplit("anonyme_", 1)[-1] == TOKEN32)

form = D._extraire_form_captcha(HTML_CAPTCHA, URL_DOSSIER40)
check("form captcha trouvé", form is not None)
check("captcha[id] présent dans les champs",
      form and form["champs"].get("captcha[id]") == CAPTCHA_ID)
check("submit présent (vide)", form and "submit" in form["champs"])
check("champ à remplir = captcha[input]",
      form and form["champs_captcha"] == ["captcha[input]"])
check("captchaResult (leurre) NON soumis",
      form and "captchaResult" not in form["champs_captcha"]
      and "captchaResult" not in form["champs"])
check("POST sur la même URL dossier (pas d'action externe)",
      form and form["action"] == URL_DOSSIER40)

img = D._extraire_captcha_img(HTML_CAPTCHA, URL_DOSSIER40)
check("image captcha = /captcha/<id>.png", img == URL_IMG, str(img))

if HTML_ACCES_DCE:
    fichiers = D._extraire_fichiers_telechargeables(HTML_ACCES_DCE, URL_ACCES40)
    check("17 pièces extraites de acces_dce", len(fichiers) == 17, f"{len(fichiers)}")
    check("toutes via getfile.php",
          all("getfile.php" in f["url"] for f in fichiers))
    check("aucun leurre acces_membre",
          all("acces_membre" not in f["url"] for f in fichiers))
    check("libellés = vrais noms de fichiers",
          any(f["label"].lower().endswith((".pdf", ".docx", ".doc", ".xlsx", ".zip"))
              for f in fichiers))


# ===========================================================================
# Workflow complet (FakeSession rejouant le HAR)
# ===========================================================================
print("\n=== telecharger_dce : workflow HAR complet ===")
_neutraliser_delais_et_captcha()
sess = FakeSession()
D.http_humain.creer_session_humaine = lambda *a, **k: sess

tmp = tempfile.mkdtemp(prefix="dematis_har_")
try:
    res = D.telecharger_dce(URL_ANNONCE, tmp, api_key_2captcha="TEST",
                            verbose=False, decompresser=False)
    check("workflow OK", res["ok"], res.get("erreur"))
    check("17 fichiers téléchargés",
          len(res.get("fichiers_telecharges", [])) == 17,
          str(len(res.get("fichiers_telecharges", []))))
    check("variante_lien = acces_dce", res.get("variante_lien") == "acces_dce")
    check("1 captcha résolu", res.get("nb_captcha_resolus") == 1)
    # Le leurre 32 hex ne doit JAMAIS avoir été visité.
    check("leurre 32 hex jamais GET", URL_DOSSIER32 not in sess.gets)
    # POST sur la bonne URL avec exactement les bons champs.
    check("exactement 1 POST", len(sess.posts) == 1, str(len(sess.posts)))
    if sess.posts:
        u_post, d_post = sess.posts[0]
        check("POST sur URL dossier 40 hex", u_post == URL_DOSSIER40)
        check("POST contient captcha[id]", d_post.get("captcha[id]") == CAPTCHA_ID)
        check("POST contient captcha[input]=solution",
              d_post.get("captcha[input]") == SOLUTION)
        check("POST NE contient PAS captchaResult", "captchaResult" not in d_post)
    # 302 → GET acces_dce effectué.
    check("GET acces_dce effectué", URL_ACCES40 in sess.gets)
finally:
    shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# Workflow : captcha refusé 2× puis accepté (re-GET captcha frais à chaque fois)
# ===========================================================================
print("\n=== telecharger_dce : captcha refusé puis accepté ===")
_neutraliser_delais_et_captcha()
sess2 = FakeSession(captcha_echecs_avant_succes=2)
D.http_humain.creer_session_humaine = lambda *a, **k: sess2

tmp2 = tempfile.mkdtemp(prefix="dematis_har2_")
try:
    res2 = D.telecharger_dce(URL_DOSSIER40, tmp2, api_key_2captcha="TEST",
                             verbose=False, decompresser=False)
    check("workflow OK après retries", res2["ok"], res2.get("erreur"))
    check("3 POST (2 refus + 1 succès)", len(sess2.posts) == 3, str(len(sess2.posts)))
    # Le captcha est re-GETé avant chaque POST (id/image régénérés) : au moins
    # 3 chargements de la page dossier (un par tentative).
    check("page dossier re-GETée à chaque tentative",
          sess2.gets.count(URL_DOSSIER40) >= 3,
          str(sess2.gets.count(URL_DOSSIER40)))
finally:
    shutil.rmtree(tmp2, ignore_errors=True)


# ===========================================================================
# Workflow : entrée directe par l'URL dossier (sans page annonce)
# ===========================================================================
print("\n=== telecharger_dce : entrée directe URL dossier ===")
_neutraliser_delais_et_captcha()
sess3 = FakeSession()
D.http_humain.creer_session_humaine = lambda *a, **k: sess3
tmp3 = tempfile.mkdtemp(prefix="dematis_har3_")
try:
    res3 = D.telecharger_dce(URL_DOSSIER40, tmp3, api_key_2captcha="TEST",
                             verbose=False, decompresser=False)
    check("workflow OK (entrée dossier directe)", res3["ok"], res3.get("erreur"))
    check("17 fichiers", len(res3.get("fichiers_telecharges", [])) == 17)
finally:
    shutil.rmtree(tmp3, ignore_errors=True)


# ===========================================================================
# _normaliser_nom_mojibake (cas du HAR : réseaux mojibake + Règlement)
# ===========================================================================
print("\n=== _normaliser_nom_mojibake ===")
# 'é' = U+00C3 U+00A9 quand des octets UTF-8 sont relus en latin-1 (mojibake).
MOJ_E = "r" + chr(0xC3) + chr(0xA9) + "seaux"          # 'rÃ©seaux'
MOJ_EG = "R" + chr(0xC3) + chr(0xA8) + "glement de consultation.pdf"  # 'RÃ¨glement...'
LATIN_EG = "R" + chr(0xE8) + "glement de consultation.pdf"            # 'Règlement...' (déjà bon)
check("mojibake 'rÃ©seaux' -> 'réseaux'",
      D._normaliser_nom_mojibake(MOJ_E) == "r" + chr(0xE9) + "seaux")
check("mojibake 'RÃ¨glement' -> 'Règlement'",
      D._normaliser_nom_mojibake(MOJ_EG) == "R" + chr(0xE8) + "glement de consultation.pdf")
check("nom latin-1 déjà correct inchangé",
      D._normaliser_nom_mojibake(LATIN_EG) == LATIN_EG)
check("nom sans accent inchangé",
      D._normaliser_nom_mojibake("03_CCAP.pdf") == "03_CCAP.pdf")
check("idempotence (nom déjà réparé)",
      D._normaliser_nom_mojibake("r" + chr(0xE9) + "seaux") == "r" + chr(0xE9) + "seaux")
check("None/vide toléré", D._normaliser_nom_mojibake("") == "")
# Mojibake DOUBLE (cas réel SDIS13 'mémoire' ré-encodé 2×) → doit converger.
double_moj = ("m" + chr(0xC3) + chr(0xA9) + "moire").encode("utf-8").decode("latin-1")
check("mojibake double 'mÃƒÂ©moire' -> 'mémoire'",
      D._normaliser_nom_mojibake(double_moj) == "m" + chr(0xE9) + "moire")

# Décodage sans perte : un octet latin-1 brut (0xE8) ne doit pas être détruit.
class _RespBytes:
    def __init__(self, content):
        self.content = content
        self.text = content.decode("utf-8", "replace")
# 'Règlement' avec è en octet latin-1 brut (0xE8) au milieu d'une page UTF-8.
brut = ("<a href='https://private.e-marchespublics.com/dce/getfile.php?id=1&anonyme=x'>"
        "R" + chr(0xE8) + "glement.pdf</a>").encode("latin-1")
html_sansperte = D._decoder_liste_sans_perte(_RespBytes(brut))
fichiers_sp = D._extraire_fichiers_telechargeables(html_sansperte, "https://x.e-marchespublics.com/")
check("octet latin-1 brut préservé (pas de caractère de remplacement)",
      fichiers_sp and "�" not in fichiers_sp[0]["label"]
      and fichiers_sp[0]["label"] == "R" + chr(0xE8) + "glement.pdf",
      fichiers_sp[0]["label"] if fichiers_sp else "aucun")

# _nom_fichier doit normaliser le mojibake du Content-Disposition (getfile.php).
cd_moj = {"Content-Disposition": 'attachment; filename="m' + chr(0xC3) + chr(0xA9) + 'moire.xlsx"'}
check("_nom_fichier répare le mojibake du Content-Disposition",
      D._nom_fichier(cd_moj, "https://x/dce/getfile.php?id=1") == "m" + chr(0xE9) + "moire.xlsx",
      D._nom_fichier(cd_moj, "https://x/dce/getfile.php?id=1"))


# ===========================================================================
# _dedupliquer_fichiers (cas réel RATP : même fichier listé 2× sous des ids ≠)
# ===========================================================================
print("\n=== _dedupliquer_fichiers ===")
B = "https://private.e-marchespublics.com/dce/getfile.php"
liste_avec_doublons = [
    {"label": "Pièces écrites.zip", "url": f"{B}?id=111&anonyme=tok&fromnew"},
    {"label": "CCAP.pdf", "url": f"{B}?id=222&anonyme=tok&fromnew"},
    {"label": "Pièces écrites.zip", "url": f"{B}?id=333&anonyme=tok&fromnew"},  # doublon de 111
    {"label": "pièces écrites.zip", "url": f"{B}?id=444&anonyme=tok&fromnew"},  # doublon (casse)
    {"label": "CCTP.pdf", "url": f"{B}?id=555&anonyme=tok&fromnew"},
]
uniques, doublons = D._dedupliquer_fichiers(liste_avec_doublons)
check("3 pièces uniques conservées (5 - 2 doublons)", len(uniques) == 3, str(len(uniques)))
check("première occurrence gardée (id=111)",
      any("id=111" in u["url"] for u in uniques)
      and not any("id=333" in u["url"] or "id=444" in u["url"] for u in uniques))
check("dédup insensible à la casse", not any("id=444" in u["url"] for u in uniques))
check("1 groupe de doublons signalé", len(doublons) == 1, str(len(doublons)))
check("ids_doublons = [111, 333, 444]",
      doublons and doublons[0]["ids_doublons"] == ["111", "333", "444"],
      str(doublons[0]["ids_doublons"]) if doublons else "aucun")
check("nom du doublon renseigné",
      doublons and doublons[0]["nom"] == "Pièces écrites.zip")
# Liste sans doublon → aucun doublon signalé, tout conservé.
uniques2, doublons2 = D._dedupliquer_fichiers(
    [{"label": "A.pdf", "url": f"{B}?id=1"}, {"label": "B.pdf", "url": f"{B}?id=2"}])
check("aucun doublon sur liste propre", doublons2 == [] and len(uniques2) == 2)


# ===========================================================================
# Fix cookie PHPSESSID à Domain= vide (quirk Dematis)
# ===========================================================================
print("\n=== fix cookie PHPSESSID (Domain= vide) ===")
import requests


class _FakeRaw:
    def __init__(self, set_cookies):
        self.headers = self  # joue le rôle de HTTPHeaderDict
        self._sc = set_cookies

    def get_all(self, name):
        return self._sc if name.lower() == "set-cookie" else []


class _FakeRespCookie:
    def __init__(self, url, set_cookies):
        self.url = url
        self.raw = _FakeRaw(set_cookies)
        self.headers = {}


sess_ck = requests.Session()
D._installer_fix_cookies_domaine_vide(sess_ck)
hook = sess_ck.hooks["response"][-1]
# Cookie malformé tel que posé par Dematis (Domain= vide, SameSite=None; Secure).
resp_ck = _FakeRespCookie(
    URL_DOSSIER40,
    ["PHPSESSID=de5369be0589300483f61d8be0ec64d3;Domain=;Path=/;Expires=Session;SameSite=None; Secure"])
hook(resp_ck)
check("PHPSESSID ré-injecté malgré Domain= vide",
      sess_ck.cookies.get("PHPSESSID") == "de5369be0589300483f61d8be0ec64d3",
      str(sess_ck.cookies.get_dict()))
check("cookie rattaché au bon hôte",
      any(c.domain.endswith("e-marchespublics.com") for c in sess_ck.cookies))

# Un cookie à domaine NON vide ne doit pas être doublé par le hook.
sess_ck2 = requests.Session()
D._installer_fix_cookies_domaine_vide(sess_ck2)
hook2 = sess_ck2.hooks["response"][-1]
hook2(_FakeRespCookie(URL_DOSSIER40,
                      ["autre=1;Domain=e-marchespublics.com;Path=/"]))
check("cookie à domaine renseigné ignoré par le hook",
      sess_ck2.cookies.get("autre") is None)


# ===========================================================================
print(f"\n{'='*60}")
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
