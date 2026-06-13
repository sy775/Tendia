"""
tests_parseur_dce.py
--------------------
Tests HORS-LIGNE du téléchargeur profond (parsing HTML mocké + fake session).
Ne fait aucun appel réseau. Lancement : python tests_parseur_dce.py
"""
import io
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tendia_telecharger_dce as T

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


# --- Fakes pour simuler le réseau ---
class FakeResp:
    def __init__(self, status=200, contenu=b"PDFDATA" * 500, headers=None):
        self.status_code = status
        self._contenu = contenu
        self.headers = headers or {}

    def iter_content(self, n):
        for i in range(0, len(self._contenu), n):
            yield self._contenu[i:i + n]


class FakeSession:
    """session.get(url) renvoie une réponse selon un mapping url->FakeResp."""
    def __init__(self, mapping, defaut=None):
        self.mapping = mapping
        self.defaut = defaut or FakeResp(404, b"")
        self.headers = {}
        self.cookies = {}
        self.appels = []

    def get(self, url, **kw):
        self.appels.append(url)
        for cle, resp in self.mapping.items():
            if cle in url:
                return resp
        return self.defaut


HTML_DCE = """
<html><body>
  <h1>Dossier de consultation</h1>
  <a href="/dce/RC_consultation.pdf">Règlement de consultation</a>
  <a href="/dce/CCAP_v2.pdf">CCAP</a>
  <a href="/dce/CCTP.pdf">Cahier des clauses techniques</a>
  <a href="/dce/DPGF.xlsx">Décomposition du prix global</a>
  <a href="/dce/telecharger_dossier_complet.zip">Télécharger tout le dossier</a>
  <a href="#">ancre</a>
  <a href="javascript:void(0)">js</a>
  <a href="/contact">contact (pas un doc)</a>
</body></html>
"""

print("=== _pieces_depuis_html (parsing pur) ===")
pieces = T._pieces_depuis_html(HTML_DCE, "https://exemple.fr/page?id=1")
types = {p["type_detecte"] for p in pieces}
noms = [p["nom"] for p in pieces]
print("  pièces:", [(p["type_detecte"], p["nom"]) for p in pieces])
check("5 pièces documents détectées (ancre/js/contact exclus)", len(pieces) == 5)
check("RC détecté", "RC" in types)
check("CCAP détecté", "CCAP" in types)
check("CCTP détecté", "CCTP" in types)
check("DPGF détecté", "DPGF" in types)
check("ZIP_GLOBAL détecté", "ZIP_GLOBAL" in types)
check("URLs absolues", all(p["url"].startswith("https://exemple.fr/") for p in pieces))

print("\n=== trouver_parseur ===")
check("PLACE/Atexo reconnu", isinstance(T.trouver_parseur("https://www.marches-publics.gouv.fr/?x"), T.ParseurAtexo))
check("e-marchespublics reconnu", isinstance(T.trouver_parseur("https://x.e-marchespublics.com/y"), T.ParseurEMarchesPublics))
check("AWS-Achat (marches-publics.info) -> ParseurAWS", isinstance(T.trouver_parseur("https://www.marches-publics.info/?z"), T.ParseurAWS))
check("plateforme auth restante (marches-securises) -> None", T.trouver_parseur("https://www.marches-securises.fr/?z") is None)
check("plateforme inconnue -> générique", isinstance(T.trouver_parseur("https://mairie-xyz.fr/dce"), T.ParseurGenerique))
check("url vide -> None", T.trouver_parseur("") is None)

print("\n=== _telecharger_avec_retry ===")
d = tempfile.mkdtemp(prefix="dl_")
sess = FakeSession({"ok.pdf": FakeResp(200, b"%PDF" + b"x" * 3000,
                                       {"Content-Disposition": 'attachment; filename="RC.pdf"'})})
okdl, info = T._telecharger_avec_retry(sess, {"url": "http://h/ok.pdf", "nom": "ok.pdf", "type_detecte": "RC"}, d)
check("DL OK (taille>0, fichier écrit)", okdl and info["taille"] > 0 and os.path.exists(info["chemin"]))

sess404 = FakeSession({}, defaut=FakeResp(404, b""))
ok404, info404 = T._telecharger_avec_retry(sess404, {"url": "http://h/x.pdf", "nom": "x"}, d, max_essais=2)
check("404 -> échec immédiat", (not ok404) and "404" in info404["erreur"])

sess500 = FakeSession({}, defaut=FakeResp(500, b""))
ok500, _ = T._telecharger_avec_retry(sess500, {"url": "http://h/y.pdf", "nom": "y"}, d, max_essais=2)
check("500 -> retry puis échec (2 essais)", (not ok500) and len(sess500.appels) == 2)

sess0 = FakeSession({"z.pdf": FakeResp(200, b"", {})})
ok0, _ = T._telecharger_avec_retry(sess0, {"url": "http://h/z.pdf", "nom": "z"}, d, max_essais=2)
check("0 octet -> échec", not ok0)

print("\n=== telecharger_pieces_dce (best-effort) ===")
# 3 pièces unitaires, la CCTP échoue (404). Pas de zip global.
html_unit = ('<a href="/RC.pdf">RC</a>'
             '<a href="/CCAP.pdf">CCAP</a>'
             '<a href="/CCTP.pdf">CCTP</a>')


class ParseurMock(T.ParseurGenerique):
    def lister_pieces(self, session, url):
        return T._pieces_depuis_html(html_unit, "https://mairie-xyz.fr/")


# Monkeypatch trouver_parseur le temps du test
_orig = T.trouver_parseur
T.trouver_parseur = lambda url: ParseurMock()
try:
    sess3 = FakeSession({
        "RC.pdf": FakeResp(200, b"%PDF" + b"a" * 2000, {}),
        "CCAP.pdf": FakeResp(200, b"%PDF" + b"b" * 2000, {}),
        "CCTP.pdf": FakeResp(404, b""),
    })
    d2 = tempfile.mkdtemp(prefix="dl2_")
    res = T.telecharger_pieces_dce({"url_dce": "https://mairie-xyz.fr/dce"}, d2, session=sess3)
    print("  récupérées:", len(res["pieces_recuperees"]), "| manquantes:", len(res["pieces_manquantes"]))
    check("2 pièces récupérées", len(res["pieces_recuperees"]) == 2)
    check("1 pièce manquante (CCTP)", len(res["pieces_manquantes"]) == 1
          and any("CCTP" in (m.get("nom") or "").upper() or m.get("type_detecte") == "CCTP"
                  for m in res["pieces_manquantes"]))
    check("raison d'échec présente", res["pieces_manquantes"][0].get("raison_echec"))
finally:
    T.trouver_parseur = _orig

print("\n=== telecharger_pieces_dce branche Atexo (mock réseau) ===")
import atexo_downloader as _ad
_orig_dl = _ad.telecharger_dce
try:
    # Cas succès simulé
    _ad.telecharger_dce = lambda *a, **k: {"ok": True, "chemin": a[2],
                                           "taille_octets": 12345, "duree_secondes": 1.0}
    url_atexo = "https://www.marches-publics.gouv.fr/?page=Entreprise.x&id=3003304&orgAcronyme=h8j"
    res_a = T.telecharger_pieces_dce({"url_dce": url_atexo}, tempfile.mkdtemp(prefix="atx_"))
    check("Atexo succès -> 1 pièce ZIP récupérée", len(res_a["pieces_recuperees"]) == 1
          and res_a["pieces_recuperees"][0]["taille"] == 12345)
    # Cas échec simulé
    _ad.telecharger_dce = lambda *a, **k: {"ok": False, "erreur": "POST 2 HTTP 500",
                                           "duree_secondes": 0.5}
    res_b = T.telecharger_pieces_dce({"url_dce": url_atexo}, tempfile.mkdtemp(prefix="atx2_"))
    check("Atexo échec -> manquante avec raison", len(res_b["pieces_recuperees"]) == 0
          and res_b["pieces_manquantes"] and res_b["pieces_manquantes"][0]["raison_echec"] == "POST 2 HTTP 500")
finally:
    _ad.telecharger_dce = _orig_dl

print(f"\n=== {ok} OK / {ko} KO ===")
sys.exit(1 if ko else 0)
