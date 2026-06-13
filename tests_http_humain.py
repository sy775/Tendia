"""
tests_http_humain.py
---------------------
Tests HORS-LIGNE de http_humain (aucun réseau, time.sleep et random mockés).
Lancement : python tests_http_humain.py
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import http_humain as H

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


# On neutralise time.sleep pour que les tests soient instantanés, et on capture
# les délais demandés.
_sleeps = []
H.time.sleep = lambda d: _sleeps.append(d)


# ===========================================================================
# creer_session_humaine
# ===========================================================================
print("=== creer_session_humaine ===")
s = H.creer_session_humaine()
check("UA présent et issu du pool", s.headers.get("User-Agent") in H.USER_AGENTS_POOL)
check("Accept-Language fr", "fr-FR" in s.headers.get("Accept-Language", ""))
check("Sec-Fetch-Mode navigate", s.headers.get("Sec-Fetch-Mode") == "navigate")
s2 = H.creer_session_humaine(ua_fixe="UA-TEST/1.0")
check("ua_fixe respecté", s2.headers.get("User-Agent") == "UA-TEST/1.0")
# Le pool doit contenir plusieurs UA distincts (rotation possible)
check("pool >= 5 UA distincts", len(set(H.USER_AGENTS_POOL)) >= 5)


# ===========================================================================
# attendre_humain : bornes uniforme + gaussienne
# ===========================================================================
print("\n=== attendre_humain ===")
_orig_uniform = H.random.uniform
_orig_gauss = H.random.gauss

# Uniforme : doit retourner dans [min, max]
H.random.uniform = lambda a, b: (a + b) / 2
d = H.attendre_humain(30, 180)
check("uniforme dans les bornes", 30 <= d <= 180 and d == 105)

# Gaussienne au-delà du max -> bridée à max
H.random.gauss = lambda mu, sigma: 9999
d = H.attendre_humain(20, 180, mu=75, sigma=30)
check("gauss au-dessus du max bridée à max", d == 180)
# Gaussienne en-dessous du min -> bridée à min
H.random.gauss = lambda mu, sigma: -50
d = H.attendre_humain(20, 180, mu=75, sigma=30)
check("gauss en-dessous du min bridée à min", d == 20)
# Gaussienne dans les bornes -> valeur inchangée
H.random.gauss = lambda mu, sigma: 70
d = H.attendre_humain(20, 180, mu=75, sigma=30)
check("gauss dans les bornes inchangée", d == 70)
check("time.sleep appelé avec le délai", _sleeps and _sleeps[-1] == 70)
H.random.uniform = _orig_uniform
H.random.gauss = _orig_gauss


# ===========================================================================
# attendre_inter_etapes
# ===========================================================================
print("\n=== attendre_inter_etapes ===")
H.random.uniform = lambda a, b: a  # borne basse
d = H.attendre_inter_etapes(1.5, 4.0)
check("inter-étapes dans les bornes", 1.5 <= d <= 4.0)
H.random.uniform = _orig_uniform


# ===========================================================================
# attendre_pause_cumulative
# ===========================================================================
print("\n=== attendre_pause_cumulative ===")
check("pas de pause à compteur=0", H.attendre_pause_cumulative(0, seuil=20) is None)
check("pas de pause à compteur=5", H.attendre_pause_cumulative(5, seuil=20) is None)
H.random.uniform = lambda a, b: a
d = H.attendre_pause_cumulative(20, seuil=20, pause_min_sec=900, pause_max_sec=1800)
check("pause à compteur=20 (multiple du seuil)", d is not None and 900 <= d <= 1800)
check("pas de pause à compteur=21", H.attendre_pause_cumulative(21, seuil=20) is None)
H.random.uniform = _orig_uniform


# ===========================================================================
# jitter
# ===========================================================================
print("\n=== jitter ===")
H.random.uniform = lambda a, b: (a + b) / 2
check("jitter centré sur le délai", H.jitter(60, 0.2) == 60)
H.random.uniform = lambda a, b: a  # borne basse = delay - delay*pct
check("jitter borne basse = 48 pour (60, 0.2)", abs(H.jitter(60, 0.2) - 48) < 1e-9)
H.random.uniform = _orig_uniform


# ===========================================================================
# heure_actuelle_est_bureau (datetime mocké)
# ===========================================================================
print("\n=== heure_actuelle_est_bureau ===")
import datetime as _dt


class _FakeDateTime:
    _now = None

    @classmethod
    def now(cls):
        return cls._now


_orig_datetime = H.datetime
H.datetime = _FakeDateTime
try:
    # Mardi 10h00 -> bureau
    _FakeDateTime._now = _dt.datetime(2026, 6, 16, 10, 0)  # mardi
    check("mardi 10h00 -> True", H.heure_actuelle_est_bureau() is True)
    # Mardi 22h00 -> hors bureau
    _FakeDateTime._now = _dt.datetime(2026, 6, 16, 22, 0)
    check("mardi 22h00 -> False", H.heure_actuelle_est_bureau() is False)
    # Mardi 7h00 -> trop tôt
    _FakeDateTime._now = _dt.datetime(2026, 6, 16, 7, 0)
    check("mardi 7h00 -> False", H.heure_actuelle_est_bureau() is False)
    # Samedi 10h00 -> week-end
    _FakeDateTime._now = _dt.datetime(2026, 6, 13, 10, 0)  # samedi
    check("samedi 10h00 -> False", H.heure_actuelle_est_bureau() is False)
    # Dimanche 10h00 -> week-end
    _FakeDateTime._now = _dt.datetime(2026, 6, 14, 10, 0)  # dimanche
    check("dimanche 10h00 -> False", H.heure_actuelle_est_bureau() is False)
finally:
    H.datetime = _orig_datetime


# ===========================================================================
# ressemble_a_page_ban
# ===========================================================================
print("\n=== ressemble_a_page_ban ===")
check("page accueil Bootstrap -> ban",
      H.ressemble_a_page_ban('<html><link href="bootstrap.min.css"><a href="acheteurs.htm">') is True)
check("message blocage -> ban",
      H.ressemble_a_page_ban("<h1>Access Denied</h1>") is True)
check("page captcha ColdFusion normale -> pas ban",
      H.ressemble_a_page_ban('<input name="strNomImage" value="123">') is False)
check("html vide -> pas ban", H.ressemble_a_page_ban("") is False)
check("None -> pas ban", H.ressemble_a_page_ban(None) is False)


print(f"\n=== {ok} OK / {ko} KO ===")
sys.exit(1 if ko else 0)
