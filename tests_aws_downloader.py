"""
tests_aws_downloader.py
-----------------------
Tests HORS-LIGNE de aws_downloader (aucun réseau, captcha mocké).
Couvre les helpers purs + le workflow complet via une fausse Session.

Lancement : python tests_aws_downloader.py
"""
import io
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import aws_downloader as A

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
# _extraire_idm_depuis_url
# ===========================================================================
print("=== _extraire_idm_depuis_url ===")
check("IDM simple",
      A._extraire_idm_depuis_url(
          "https://www.marches-publics.info/mpiaws/index.cfm?fuseaction=dematEnt.choixDCE&IDM=1832151") == "1832151")
check("IDM avec autres params",
      A._extraire_idm_depuis_url(
          "https://www.marches-publics.info/?IDS=25&IDM=999&CFID=1") == "999")
check("IDM en http (pas https)",
      A._extraire_idm_depuis_url("http://www.marches-publics.info/x?IDM=42") == "42")
check("URL sans IDM -> None",
      A._extraire_idm_depuis_url("https://www.marches-publics.info/x?foo=bar") is None)


# ===========================================================================
# _extraire_cfid_cftoken_depuis_html
# ===========================================================================
print("\n=== _extraire_cfid_cftoken_depuis_html ===")
HTML_CFID = '''
<a href="index.cfm?fuseaction=dce.avertissement&IDM=1832151&IDS=25&CFID=12345678&CFTOKEN=abcdef0123456789">Retirer</a>
'''
cfid, cftoken = A._extraire_cfid_cftoken_depuis_html(HTML_CFID)
check("CFID extrait", cfid == "12345678")
check("CFTOKEN extrait", cftoken == "abcdef0123456789")
c2, t2 = A._extraire_cfid_cftoken_depuis_html("<html>aucun token</html>")
check("HTML sans token -> (None, None)", c2 is None and t2 is None)


# ===========================================================================
# _extraire_str_nom_image_et_hashval
# ===========================================================================
print("\n=== _extraire_str_nom_image_et_hashval ===")
HASH64 = "a" * 64
HTML_CAPTCHA = f'''
<form action="index.cfm?fuseaction=dce.cnxAnonyme">
  <input type="hidden" name="strNomImage" value="1718000000123" />
  <input type="hidden" name="hashVal" value="{HASH64}" />
  <input type="text" name="captchaVal" value="" />
</form>
'''
sni, hv = A._extraire_str_nom_image_et_hashval(HTML_CAPTCHA)
check("strNomImage extrait", sni == "1718000000123")
check("hashVal (64 hex) extrait", hv == HASH64)
# Ordre inverse des attributs (value avant name)
HTML_CAPTCHA_INV = f'<input value="999" name="strNomImage"><input value="{HASH64}" name="hashVal">'
sni2, hv2 = A._extraire_str_nom_image_et_hashval(HTML_CAPTCHA_INV)
check("attributs en ordre inverse gérés", sni2 == "999" and hv2 == HASH64)
sni3, hv3 = A._extraire_str_nom_image_et_hashval("<html>rien</html>")
check("HTML sans captcha -> (None, None)", sni3 is None and hv3 is None)


# ===========================================================================
# _extraire_lots_depuis_verif_lots_dce
# ===========================================================================
print("\n=== _extraire_lots_depuis_verif_lots_dce ===")
check("0 checkbox -> []",
      A._extraire_lots_depuis_verif_lots_dce("<form>pas de lots</form>") == [])
HTML_1LOT = '<input type="checkbox" name="lots" value="1">'
check("1 checkbox -> ['1']",
      A._extraire_lots_depuis_verif_lots_dce(HTML_1LOT) == ["1"])
HTML_5LOTS = "".join(
    f'<input type="checkbox" name="lots" value="{i}">' for i in range(1, 6))
check("5 checkboxes -> ['1'..'5']",
      A._extraire_lots_depuis_verif_lots_dce(HTML_5LOTS) == ["1", "2", "3", "4", "5"])
# Doublons ignorés
check("doublons dédupliqués",
      A._extraire_lots_depuis_verif_lots_dce(HTML_1LOT + HTML_1LOT) == ["1"])


# ===========================================================================
# _extraire_url_cdn_depuis_actdce2
# ===========================================================================
print("\n=== _extraire_url_cdn_depuis_actdce2 ===")
HTML_ACTDCE2 = '''
<p>
  <label class="gaucheTableau">12/06/26 à 10h00</label>
  <span class="droiteTableauTiers">DCE (Pièces communes)</span>
  <span class="petitDroiteTableau">
    <a href="https://downloads.awsolutions.fr/dce/attachment/TOKEN_DCE"><img src="img/btn-telecharger.png"></a>
  </span>
</p>
<p>
  <label class="gaucheTableau">12/06/26 à 10h00</label>
  <span class="droiteTableauTiers">LOT-1</span>
  <span class="petitDroiteTableau">
    <a href="https://downloads.awsolutions.fr/dce/attachment/TOKEN_LOT1"><img src="img/btn-telecharger.png"></a>
  </span>
</p>
<p>
  <label class="gaucheTableau">12/06/26 à 10h00</label>
  <span class="droiteTableauTiers">Conditions d'accès à AW Solutions</span>
  <span class="petitDroiteTableau">
    <a href="https://downloads.awsolutions.fr/dce/attachment/TOKEN_CGU"><img src="img/btn-telecharger.png"></a>
  </span>
</p>
<p>
  <label class="gaucheTableau">12/06/26 à 10h00</label>
  <span class="droiteTableauTiers">AAPC</span>
  <span class="petitDroiteTableau">
    <a href="index.cfm?fuseaction=dce.TDoc&amp;IDM=1832151&amp;PDF=true&amp;Id_Groupe=3"><img src="img/btn-telecharger.png"></a>
  </span>
</p>
'''
ressources = A._extraire_url_cdn_depuis_actdce2(HTML_ACTDCE2, idm="1832151")
urls = [r["url"] for r in ressources]
labels = [r["label"] for r in ressources]
check("URL CDN DCE conservée",
      "https://downloads.awsolutions.fr/dce/attachment/TOKEN_DCE" in urls)
check("URL CDN LOT-1 conservée",
      "https://downloads.awsolutions.fr/dce/attachment/TOKEN_LOT1" in urls)
check("URL 'Conditions d'accès' filtrée",
      "https://downloads.awsolutions.fr/dce/attachment/TOKEN_CGU" not in urls)
check("URL AAPC relative convertie en absolue",
      any("https://www.marches-publics.info/mpiaws/index.cfm?fuseaction=dce.TDoc" in u
          for u in urls))
check("3 ressources retenues (CGU exclue)", len(ressources) == 3)
check("label DCE présent", any("DCE" in l for l in labels))
check("URL vide -> []", A._extraire_url_cdn_depuis_actdce2("") == [])


# ===========================================================================
# _nom_fichier_depuis_headers + _sanitiser_nom
# ===========================================================================
print("\n=== _nom_fichier_depuis_headers / _sanitiser_nom ===")
check("fileName Content-Disposition",
      A._nom_fichier_depuis_headers(
          {"Content-Disposition": 'attachment; fileName="AWS-MPI-1832151-DCE.zip"; size=1000'})
      == "AWS-MPI-1832151-DCE.zip")
check("fallback sur basename URL",
      A._nom_fichier_depuis_headers({}, "https://x/dce/attachment/doc.pdf") == "doc.pdf")
check("défaut si rien",
      A._nom_fichier_depuis_headers({}, "https://x/dce/attachment/TOKEN", defaut="piece.bin")
      == "piece.bin")
check("sanitisation chars invalides",
      A._sanitiser_nom('a/b:c*d?.zip') == "a_b_c_d_.zip")


# ===========================================================================
# _construire_url
# ===========================================================================
print("\n=== _construire_url ===")
u = A._construire_url("dce.avertissement", IDM="1832151", IDS="25",
                      CFID="111", CFTOKEN="222")
check("URL construite avec params",
      u == "https://www.marches-publics.info/mpiaws/index.cfm?fuseaction=dce.avertissement&IDM=1832151&IDS=25&CFID=111&CFTOKEN=222")
check("params vides ignorés",
      "vide=" not in A._construire_url("dce.x", IDM="1", vide=""))


# ===========================================================================
# Workflow complet : fausse Session + captcha mocké
# ===========================================================================
print("\n=== Workflow complet (fausse Session + captcha mocké) ===")


class FakeResponse:
    def __init__(self, status_code=200, text="", content=b"", headers=None, url=""):
        self.status_code = status_code
        self.text = text
        self.content = content
        self.headers = headers or {}
        self.url = url

    def iter_content(self, chunk_size=65536):
        data = self.content
        for i in range(0, len(data), chunk_size):
            yield data[i:i + chunk_size]


ZIP_MAGIQUE = b"PK\x03\x04" + b"0" * 200  # pas un vrai zip mais suffit pour DL


class FakeSession:
    """Rejoue le workflow AWS-Achat sans réseau."""
    def __init__(self):
        self.headers = {}
        self.calls = []

    def get(self, url, timeout=None, allow_redirects=True, stream=False):
        self.calls.append(("GET", url))
        low = url.lower()
        if "dematent.choixdce" in low:
            return FakeResponse(
                200,
                text='<a href="index.cfm?fuseaction=dce.avertissement&IDM=1832151&IDS=25&CFID=12345678&CFTOKEN=abcdef0123456789">Retrait anonyme</a>',
                url=url)
        if "dce.avertissement" in low:
            return FakeResponse(200, text=HTML_CAPTCHA, url=url)
        if "/captcha/captcha_" in low:
            return FakeResponse(200, content=b"\x89PNG\r\n fake image bytes", url=url)
        if "dce.veriflotsdce" in low:
            return FakeResponse(200, text=HTML_1LOT, url=url)
        if "downloads.awsolutions.fr" in low:
            return FakeResponse(
                200, content=ZIP_MAGIQUE,
                headers={"Content-Disposition": 'attachment; fileName="AWS-MPI-1832151-DCE.zip"'},
                url=url)
        return FakeResponse(404, url=url)

    def post(self, url, data=None, timeout=None, allow_redirects=True, headers=None):
        self.calls.append(("POST", url, data))
        low = url.lower()
        if "dce.cnxanonyme" in low:
            return FakeResponse(
                302,
                headers={"Location": "index.cfm?fuseaction=dce.verifLotsDCE&IDM=1832151&IDS=25&CFID=12345678&CFTOKEN=abcdef0123456789"},
                url=url)
        if "dce.actdce2" in low:
            return FakeResponse(200, text=HTML_ACTDCE2, url=url)
        return FakeResponse(404, url=url)


import tempfile, os, types

# Monkeypatch : session humaine factice + captcha + décompression + délais
# anti-ban neutralisés (sinon les attendre_inter_etapes ajoutent de vrais
# time.sleep dans les tests).
_orig_session = A.http_humain.creer_session_humaine
_orig_attente = A.http_humain.attendre_inter_etapes
_orig_captcha = A._resoudre_captcha_2captcha
_orig_decomp = A._decompresser_zip_imbrique
A.http_humain.creer_session_humaine = lambda *a, **k: FakeSession()
A.http_humain.attendre_inter_etapes = lambda *a, **k: 0.0
A._resoudre_captcha_2captcha = lambda image_bytes, api_key, verbose=True: "ABC123"
A._decompresser_zip_imbrique = lambda chemin, dest, verbose=False: {
    "nb_zip_internes_decompressed": 0, "nb_fichiers_extraits": 0, "erreur": None}

try:
    dossier_test = tempfile.mkdtemp(prefix="aws_test_")
    res = A.telecharger_dce("1832151", dossier_test,
                            api_key_2captcha="FAKEKEY", verbose=False)
    check("workflow ok=True", res.get("ok") is True)
    check("1 captcha résolu", res.get("nb_captcha_resolus") == 1)
    check("fichiers téléchargés (DCE + LOT-1, CGU filtrée)",
          len(res.get("fichiers_telecharges", [])) == 2)
    check("taille_octets_total > 0", res.get("taille_octets_total", 0) > 0)
    check("pas d'étape_erreur", res.get("etape_erreur") is None)
finally:
    A.http_humain.creer_session_humaine = _orig_session
    A.http_humain.attendre_inter_etapes = _orig_attente
    A._resoudre_captcha_2captcha = _orig_captcha
    A._decompresser_zip_imbrique = _orig_decomp


# Workflow : captcha toujours refusé (200 sur cnxAnonyme) -> échec propre
print("\n=== Workflow captcha refusé 3x ===")


class FakeSessionCaptchaKO(FakeSession):
    def post(self, url, data=None, timeout=None, allow_redirects=True, headers=None):
        low = url.lower()
        if "dce.cnxanonyme" in low:
            return FakeResponse(200, text=HTML_CAPTCHA, url=url)  # refusé
        return super().post(url, data, timeout, allow_redirects, headers)


A.http_humain.creer_session_humaine = lambda *a, **k: FakeSessionCaptchaKO()
A.http_humain.attendre_inter_etapes = lambda *a, **k: 0.0
A._resoudre_captcha_2captcha = lambda image_bytes, api_key, verbose=True: "WRONG1"
try:
    res_ko = A.telecharger_dce("1832151", tempfile.mkdtemp(prefix="aws_ko_"),
                               api_key_2captcha="FAKEKEY", verbose=False)
    check("ok=False quand captcha refusé", res_ko.get("ok") is False)
    check("etape_erreur=captcha", res_ko.get("etape_erreur") == "captcha")
    check("erreur mentionne le refus", "efus" in (res_ko.get("erreur") or ""))
finally:
    A.http_humain.creer_session_humaine = _orig_session
    A.http_humain.attendre_inter_etapes = _orig_attente
    A._resoudre_captcha_2captcha = _orig_captcha


# Workflow : ban IP (page d'accueil Bootstrap au lieu de la page captcha)
print("\n=== Workflow détection ban IP ===")


class FakeSessionBan(FakeSession):
    def get(self, url, timeout=None, allow_redirects=True, stream=False):
        low = url.lower()
        if "dce.avertissement" in low:
            # Page d'accueil HTML5 servie au lieu de la page captcha applicative
            return FakeResponse(
                200,
                text='<html><head><link href="css/bootstrap.min.css"></head>'
                     '<body><a href="acheteurs.htm">Acheteurs</a>'
                     '<a href="fournisseurs.htm">Fournisseurs</a></body></html>',
                url=url)
        return super().get(url, timeout, allow_redirects, stream)


A.http_humain.creer_session_humaine = lambda *a, **k: FakeSessionBan()
A.http_humain.attendre_inter_etapes = lambda *a, **k: 0.0
A._resoudre_captcha_2captcha = lambda image_bytes, api_key, verbose=True: "ABC123"
try:
    res_ban = A.telecharger_dce("1832151", tempfile.mkdtemp(prefix="aws_ban_"),
                                api_key_2captcha="FAKEKEY", verbose=False)
    check("ok=False quand ban", res_ban.get("ok") is False)
    check("etape_erreur=ban_detecte", res_ban.get("etape_erreur") == "ban_detecte")
finally:
    A.http_humain.creer_session_humaine = _orig_session
    A.http_humain.attendre_inter_etapes = _orig_attente
    A._resoudre_captcha_2captcha = _orig_captcha


# Wrapper : rotation IP automatique sur ban (1er essai banni -> 2e essai OK)
print("\n=== Rotation IP automatique sur ban (wrapper) ===")

_compteur_sessions = {"n": 0}


def _session_factory_ban_puis_ok(*a, **k):
    # 1er appel (tentative 0, session-id = id marché) -> session bannie.
    # Appels suivants (retry IP) -> session qui réussit.
    _compteur_sessions["n"] += 1
    return FakeSessionBan() if _compteur_sessions["n"] == 1 else FakeSession()


_orig_logs = A.tendia_logs.logger_evenement_marche
A.http_humain.creer_session_humaine = _session_factory_ban_puis_ok
A.http_humain.attendre_inter_etapes = lambda *a, **k: 0.0
A._resoudre_captcha_2captcha = lambda image_bytes, api_key, verbose=True: "ABC123"
A._decompresser_zip_imbrique = lambda chemin, dest, verbose=False: {
    "nb_zip_internes_decompressed": 0, "nb_fichiers_extraits": 0, "erreur": None}
A.tendia_logs.logger_evenement_marche = lambda *a, **k: None
try:
    marche = {"id": "TEST-IP",
              "url_dce": "https://www.marches-publics.info/mpiaws/index.cfm?IDM=1832151"}
    res_rot = A.telecharger_dce_pour_marche(
        marche, tempfile.mkdtemp(prefix="aws_rot_"),
        api_key_2captcha="FAKEKEY", verbose=False, max_retries_ban=3)
    check("rotation IP : succès après retry", res_rot.get("ok") is True)
    check("rotation IP : 2 tentatives (1 ban + 1 OK)",
          res_rot.get("tentatives_ip") == 2)
finally:
    A.http_humain.creer_session_humaine = _orig_session
    A.http_humain.attendre_inter_etapes = _orig_attente
    A._resoudre_captcha_2captcha = _orig_captcha
    A._decompresser_zip_imbrique = _orig_decomp
    A.tendia_logs.logger_evenement_marche = _orig_logs


# Wrapper : ban persistant -> etape_erreur=ban_persistant
print("\n=== Ban persistant (wrapper) ===")
A.http_humain.creer_session_humaine = lambda *a, **k: FakeSessionBan()
A.http_humain.attendre_inter_etapes = lambda *a, **k: 0.0
A._resoudre_captcha_2captcha = lambda image_bytes, api_key, verbose=True: "ABC123"
A.tendia_logs.logger_evenement_marche = lambda *a, **k: None
try:
    marche = {"id": "TEST-BAN-PERSIST",
              "url_dce": "https://www.marches-publics.info/mpiaws/index.cfm?IDM=1832151"}
    res_bp = A.telecharger_dce_pour_marche(
        marche, tempfile.mkdtemp(prefix="aws_bp_"),
        api_key_2captcha="FAKEKEY", verbose=False, max_retries_ban=2)
    check("ban persistant : ok=False", res_bp.get("ok") is False)
    check("ban persistant : etape_erreur=ban_persistant",
          res_bp.get("etape_erreur") == "ban_persistant")
    check("ban persistant : 3 tentatives (1 + 2 retries)",
          res_bp.get("tentatives_ip") == 3)
finally:
    A.http_humain.creer_session_humaine = _orig_session
    A.http_humain.attendre_inter_etapes = _orig_attente
    A._resoudre_captcha_2captcha = _orig_captcha
    A.tendia_logs.logger_evenement_marche = _orig_logs


print(f"\n=== {ok} OK / {ko} KO ===")
sys.exit(1 if ko else 0)
