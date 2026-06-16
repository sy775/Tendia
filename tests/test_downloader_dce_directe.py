"""
tests/test_downloader_dce_directe.py — Lancement : python tests/test_downloader_dce_directe.py

Couvre le wrapper de priorité d'URL DCE (Étape 2 refonte v2) : url_consultation_dce_directe
prioritaire, repli sur url_dce reconstruite. Monkeypatch de l'impl → 0 réseau.
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tendia_telecharger_dce as T

ok = ko = 0


def check(nom, cond):
    global ok, ko
    if cond:
        ok += 1; print(f"  ✓ {nom}")
    else:
        ko += 1; print(f"  ✗ ÉCHEC {nom}")


# Monkeypatch de l'impl : enregistre les URL tentées, succès si l'URL contient 'OK'.
_impl_original = T._telecharger_pieces_dce_impl
_appels = []


def _fake_impl(marche, dossier, session=None):
    url = marche.get("url_dce")
    _appels.append(url)
    if url and "OK" in url:
        return {"pieces_recuperees": [{"nom": "RC.pdf"}], "pieces_manquantes": []}
    return {"pieces_recuperees": [], "pieces_manquantes": [{"nom": "x"}]}


T._telecharger_pieces_dce_impl = _fake_impl
PCSLID = "https://www.achatpublic.com/sdm/ent/gen/ent_detail.do?PCSLID=CSL_2026_OK"

try:
    print("Priorité URL directe")
    _appels.clear()
    r = T.telecharger_pieces_dce(
        {"url_consultation_dce_directe": PCSLID, "url_dce": "https://reconstruite.fr/OK"}, "/tmp")
    check("URL directe utilisée en priorité", _appels[0] == PCSLID)
    check("url_source = directe", r.get("url_source") == "directe")
    check("succès → 1 seule tentative", len(_appels) == 1)
    check("PCSLID conservé dans url_utilisee", "PCSLID=CSL_2026_OK" in (r.get("url_utilisee") or ""))

    print("Champ directe absent → repli reconstruite")
    _appels.clear()
    r = T.telecharger_pieces_dce({"url_dce": "https://reconstruite.fr/OK"}, "/tmp")
    check("reconstruite utilisée", _appels == ["https://reconstruite.fr/OK"])
    check("url_source = reconstruite", r.get("url_source") == "reconstruite")

    print("URL directe échoue → fallback reconstruite")
    _appels.clear()
    r = T.telecharger_pieces_dce(
        {"url_consultation_dce_directe": "https://directe.fr/FAIL",
         "url_dce": "https://reconstruite.fr/OK"}, "/tmp")
    check("ordre : directe puis reconstruite",
          _appels == ["https://directe.fr/FAIL", "https://reconstruite.fr/OK"])
    check("repli réussi → url_source reconstruite", r.get("url_source") == "reconstruite")
    check("pièces récupérées via le repli", bool(r.get("pieces_recuperees")))

    print("Cas limites")
    _appels.clear()
    r = T.telecharger_pieces_dce({}, "/tmp")
    check("aucune URL → raison + 0 tentative", "aucune URL" in (r.get("raison") or "") and not _appels)
    _appels.clear()
    r = T.telecharger_pieces_dce(
        {"url_consultation_dce_directe": "https://x.fr/OK", "url_dce": "https://x.fr/OK"}, "/tmp")
    check("directe == reconstruite → 1 seule tentative", len(_appels) == 1)
    _appels.clear()
    r = T.telecharger_pieces_dce(
        {"url_consultation_dce_directe": "https://d.fr/FAIL", "url_dce": "https://r.fr/FAIL"}, "/tmp")
    check("toutes échouent → 2 tentatives, dernier résultat retourné",
          len(_appels) == 2 and not r.get("pieces_recuperees"))
finally:
    T._telecharger_pieces_dce_impl = _impl_original

print(f"\n=== {ok} OK / {ko} KO ===")
sys.exit(1 if ko else 0)
