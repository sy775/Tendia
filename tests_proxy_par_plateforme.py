"""
tests_proxy_par_plateforme.py
-----------------------------
Tests du proxy ciblé par plateforme (http_humain).
- unitaire : _proxy_pour_plateforme avec différents flags ;
- session simulée : proxy ON (Dematis) / OFF (PLACE) selon flags ;
- test léger PLACE sans proxy : HEAD direct (best-effort, n'échoue pas hors-ligne).

Lancement : python tests_proxy_par_plateforme.py
"""
import os
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


def _set(env: dict):
    """Applique des variables d'env (None = supprimer), retourne l'ancien état."""
    old = {}
    for k, v in env.items():
        old[k] = os.environ.get(k)
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return old


PROXY = "http://user:pass@geo.iproyal.com:12321"

print("=== _proxy_pour_plateforme ===")
old = _set({"TENDIA_PROXY_FOR_PLACE": "0", "TENDIA_PROXY_FOR_BOAMP": "0",
            "TENDIA_PROXY_FOR_DATA_GOUV": "0", "TENDIA_PROXY_FOR_DEMATIS": None,
            "TENDIA_PROXY_FOR_AWS_ACHAT": None})
try:
    check("plateforme None → proxy ON", H._proxy_pour_plateforme(None) is True)
    check("dematis (pas de flag) → ON", H._proxy_pour_plateforme("dematis") is True)
    check("aws_achat (pas de flag) → ON", H._proxy_pour_plateforme("aws_achat") is True)
    check("place (flag=0) → OFF", H._proxy_pour_plateforme("place") is False)
    check("boamp (flag=0) → OFF", H._proxy_pour_plateforme("boamp") is False)
    check("data_gouv (flag=0) → OFF", H._proxy_pour_plateforme("data_gouv") is False)
    # casse insensible + autres valeurs falsy
    _set({"TENDIA_PROXY_FOR_PLACE": "false"})
    check("place (flag=false) → OFF", H._proxy_pour_plateforme("place") is False)
    _set({"TENDIA_PROXY_FOR_PLACE": "off"})
    check("place (flag=off) → OFF", H._proxy_pour_plateforme("place") is False)
    _set({"TENDIA_PROXY_FOR_PLACE": "1"})
    check("place (flag=1) → ON (réactivable)", H._proxy_pour_plateforme("place") is True)
finally:
    _set(old)

print("\n=== creer_session_humaine : application du proxy ===")
old = _set({"TENDIA_PROXY_URL": PROXY, "TENDIA_PROXY_FOR_PLACE": "0",
            "TENDIA_PROXY_FOR_DEMATIS": None})
try:
    s_dem = H.creer_session_humaine(plateforme="dematis", session_id="t")
    check("Dematis : session.proxies défini (IPRoyal)",
          bool(s_dem.proxies) and "iproyal" in s_dem.proxies.get("https", ""))
    s_place = H.creer_session_humaine(plateforme="place", session_id="t")
    check("PLACE : session.proxies VIDE (direct)", not s_place.proxies)
    s_none = H.creer_session_humaine(plateforme=None)
    check("plateforme None : proxy appliqué (rétro-compat)", bool(s_none.proxies))
    # override explicite : proxy_url passé → appliqué même si plateforme OFF
    s_ov = H.creer_session_humaine(plateforme="place", proxy_url=PROXY)
    check("override proxy_url explicite ignore le flag plateforme", bool(s_ov.proxies))
finally:
    _set(old)

print("\n=== Test léger PLACE sans proxy (HEAD direct, best-effort) ===")
old = _set({"TENDIA_PROXY_URL": PROXY, "TENDIA_PROXY_FOR_PLACE": "0"})
try:
    s = H.creer_session_humaine(plateforme="place")
    check("session PLACE sans proxy (proxies vide)", not s.proxies)
    url = "https://www.marches-publics.gouv.fr/"
    try:
        r = s.head(url, timeout=20, allow_redirects=True)
        print(f"    HEAD PLACE direct → HTTP {r.status_code} (réseau OK, sans proxy)")
        check("HEAD PLACE répond (chemin direct fonctionnel)", r.status_code < 500)
    except Exception as e:
        print(f"    (HEAD réseau indisponible : {type(e).__name__} — test réseau ignoré)")
finally:
    _set(old)

print(f"\n{'='*56}")
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
