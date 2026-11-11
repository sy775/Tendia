# -*- coding: utf-8 -*-
"""
tests/test_env_proxy_actif.py
-----------------------------
Tests HORS-LIGNE (chantier 2, étape 1) de tendia.core.http_humain.charger_env_fichier :
  - TENDIA_PROXY_ACTIF présent dans un fichier .env n'est JAMAIS posé dans os.environ ;
    la clé est renvoyée dans la liste des clés ignorées ;
  - avertissement sur stderr contenant « TENDIA_PROXY_ACTIF », une seule fois par
    processus (drapeau http_humain._AVERTISSEMENT_PROXY_EMIS) ;
  - la variable déjà posée par un lanceur (os.environ) est conservée ;
  - les autres clés du fichier sont chargées, sans écraser l'existant ;
  - _proxy_pour_plateforme reste False tant que la variable n'est pas à 1/true/on
    dans os.environ.
Fichiers .env écrits dans un dossier temporaire ; os.environ sauvegardé et restauré.

Lancement : python tests/test_env_proxy_actif.py
"""
import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tendia.core import http_humain as H

ok = ko = 0


def check(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}  {detail}")


CLE = "TENDIA_PROXY_ACTIF"
PROXY = "http://user:pass@geo.iproyal.com:12321"
ENV_INITIAL = dict(os.environ)
DOSSIER = Path(tempfile.mkdtemp(prefix="tendia_test_env_"))
_n = 0


def fichier_env(contenu: str, nom: str = None) -> Path:
    global _n
    _n += 1
    chemin = DOSSIER / (nom or f"env_{_n}.env")
    chemin.write_text(contenu, encoding="utf-8")
    return chemin


def env_propre(**variables):
    """Repart de l'environnement initial, sans aucune variable TENDIA_PROXY_* ni
    TENDIA_TEST_*, puis pose celles demandées."""
    os.environ.clear()
    os.environ.update({k: v for k, v in ENV_INITIAL.items()
                       if not k.startswith(("TENDIA_PROXY_", "TENDIA_TEST_"))})
    os.environ.update(variables)


def charger(chemins, rearmer=True):
    """(clés ignorées, texte stderr, exception éventuelle)."""
    if rearmer:
        H._AVERTISSEMENT_PROXY_EMIS = False
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            res = H.charger_env_fichier(chemins)
        return res, err.getvalue(), None
    except Exception as e:  # noqa: BLE001
        return None, err.getvalue(), e


try:
    print("=== clé du fichier ignorée, autres clés chargées ===")
    env_propre(TENDIA_PROXY_URL=PROXY)
    f1 = fichier_env("TENDIA_PROXY_ACTIF=1\nTENDIA_TEST_CLE_A=valeur_a\n")
    ignorees, err, exc = charger([f1])
    check("pas d'exception", exc is None, repr(exc))
    check("renvoie une liste de chaînes",
          isinstance(ignorees, list) and all(isinstance(k, str) for k in ignorees), repr(ignorees))
    check("TENDIA_PROXY_ACTIF dans les clés ignorées", ignorees is not None and CLE in ignorees,
          repr(ignorees))
    check("TENDIA_PROXY_ACTIF absent de os.environ", CLE not in os.environ, os.environ.get(CLE))
    check("autre clé du fichier chargée", os.environ.get("TENDIA_TEST_CLE_A") == "valeur_a",
          repr(os.environ.get("TENDIA_TEST_CLE_A")))
    check("la clé chargée n'est pas listée comme ignorée",
          ignorees is not None and "TENDIA_TEST_CLE_A" not in ignorees, repr(ignorees))
    check("avertissement sur stderr nommant TENDIA_PROXY_ACTIF", CLE in err, repr(err))
    check("drapeau _AVERTISSEMENT_PROXY_EMIS levé", H._AVERTISSEMENT_PROXY_EMIS is True)
    check("proxy coupé pour dematis (valeur du fichier ignorée)",
          H._proxy_pour_plateforme("dematis") is False)
    check("proxy coupé pour plateforme None", H._proxy_pour_plateforme(None) is False)
    check("session dematis sans proxy",
          not H.creer_session_humaine(plateforme="dematis", session_id="t").proxies)

    print("=== avertissement unique par processus ===")
    ignorees2, err2, exc = charger([f1], rearmer=False)
    check("2e chargement : aucun nouvel avertissement", exc is None and CLE not in err2, repr(err2))
    check("2e chargement : clé toujours signalée ignorée",
          ignorees2 is not None and CLE in ignorees2, repr(ignorees2))
    check("2e chargement : toujours absente de os.environ", CLE not in os.environ)
    f1b = fichier_env("TENDIA_PROXY_ACTIF=true\n")
    _, err3, exc = charger([f1b], rearmer=False)
    check("autre fichier, même processus : toujours pas d'avertissement",
          exc is None and CLE not in err3, repr(err3))
    _, err4, exc = charger([f1])
    check("drapeau remis à False : l'avertissement revient", exc is None and CLE in err4, repr(err4))

    print("=== toutes les écritures de la valeur sont ignorées ===")
    for valeur in ("1", "true", "on", "ON", "0", ""):
        env_propre(TENDIA_PROXY_URL=PROXY)
        f = fichier_env(f"TENDIA_PROXY_ACTIF={valeur}\n")
        ign, _, exc = charger([f])
        check(f"valeur {valeur!r} dans le fichier : jamais posée, proxy coupé",
              exc is None and CLE not in os.environ and ign is not None and CLE in ign
              and H._proxy_pour_plateforme("dematis") is False,
              f"{exc!r} env={os.environ.get(CLE)!r} ignorées={ign!r}")

    print("=== la variable d'un lanceur est conservée ===")
    env_propre(TENDIA_PROXY_URL=PROXY, TENDIA_PROXY_ACTIF="1")
    f2 = fichier_env("TENDIA_PROXY_ACTIF=0\nTENDIA_TEST_CLE_C=valeur_c\n")
    _, _, exc = charger([f2])
    check("lanceur à 1, fichier à 0 : la valeur 1 est conservée",
          exc is None and os.environ.get(CLE) == "1", repr(os.environ.get(CLE)))
    check("lanceur à 1 : proxy actif pour dematis", H._proxy_pour_plateforme("dematis") is True)
    check("lanceur à 1 : les autres clés du fichier sont chargées",
          os.environ.get("TENDIA_TEST_CLE_C") == "valeur_c")
    env_propre(TENDIA_PROXY_URL=PROXY, TENDIA_PROXY_ACTIF="0")
    f3 = fichier_env("TENDIA_PROXY_ACTIF=1\n")
    _, _, exc = charger([f3])
    check("lanceur à 0, fichier à 1 : la valeur 0 est conservée, proxy coupé",
          exc is None and os.environ.get(CLE) == "0"
          and H._proxy_pour_plateforme("dematis") is False, repr(os.environ.get(CLE)))
    for valeur in ("true", "on"):
        env_propre(TENDIA_PROXY_URL=PROXY, **{CLE: valeur})
        charger([f2])
        check(f"lanceur à {valeur!r} : conservé, proxy actif",
              os.environ.get(CLE) == valeur and H._proxy_pour_plateforme("dematis") is True,
              repr(os.environ.get(CLE)))

    print("=== sans écraser l'existant ===")
    env_propre(TENDIA_TEST_CLE_B="existant")
    f4 = fichier_env("TENDIA_TEST_CLE_B=du_fichier\nTENDIA_TEST_CLE_D=valeur_d\n")
    ign, err, exc = charger([f4])
    check("variable déjà présente non écrasée",
          exc is None and os.environ.get("TENDIA_TEST_CLE_B") == "existant",
          repr(os.environ.get("TENDIA_TEST_CLE_B")))
    check("variable nouvelle chargée", os.environ.get("TENDIA_TEST_CLE_D") == "valeur_d")
    check("fichier sans TENDIA_PROXY_ACTIF : rien d'ignoré, pas d'avertissement",
          ign == [] and CLE not in err, f"{ign!r} {err!r}")
    check("fichier sans la clé : drapeau non levé", H._AVERTISSEMENT_PROXY_EMIS is False)

    print("=== plusieurs fichiers (.env et .env.txt) ===")
    env_propre()
    fa = fichier_env("TENDIA_PROXY_ACTIF=1\nTENDIA_TEST_CLE_E=premier\n", ".env")
    fb = fichier_env("TENDIA_PROXY_ACTIF=on\nTENDIA_TEST_CLE_E=second\nTENDIA_TEST_CLE_F=valeur_f\n",
                     ".env.txt")
    ign, err, exc = charger([fa, fb])
    check("deux fichiers avec la clé : jamais posée", exc is None and CLE not in os.environ,
          repr(exc))
    check("deux fichiers : clé signalée ignorée, avertissement émis",
          ign is not None and CLE in ign and CLE in err, f"{ign!r} {err!r}")
    check("le premier fichier l'emporte (le second n'écrase pas)",
          os.environ.get("TENDIA_TEST_CLE_E") == "premier", repr(os.environ.get("TENDIA_TEST_CLE_E")))
    check("clé propre au second fichier chargée", os.environ.get("TENDIA_TEST_CLE_F") == "valeur_f")

    print("=== cas limites ===")
    env_propre()
    ign, err, exc = charger([])
    check("liste vide : [] sans exception ni avertissement",
          exc is None and ign == [] and CLE not in err, f"{exc!r} {ign!r}")
    ign, err, exc = charger([DOSSIER / "absent.env"])
    check("fichier absent : [] sans exception", exc is None and ign == [], f"{exc!r} {ign!r}")
    ign, err, exc = charger([fichier_env("")])
    check("fichier vide : [] sans exception", exc is None and ign == [], f"{exc!r} {ign!r}")
    ign, err, exc = charger([fichier_env("# commentaire\n\nTENDIA_TEST_CLE_G=g\n")])
    check("commentaires et lignes vides tolérés",
          exc is None and ign == [] and os.environ.get("TENDIA_TEST_CLE_G") == "g", repr(exc))
    ign, err, exc = charger([DOSSIER / "absent.env", f1])
    check("fichier absent puis fichier présent : le second est lu",
          exc is None and ign is not None and CLE in ign and CLE not in os.environ,
          f"{exc!r} {ign!r}")
    env_propre()
    ign, err, exc = charger(None)
    check("chemins par défaut (racine du dépôt) : liste rendue, clé jamais posée",
          exc is None and isinstance(ign, list) and CLE not in os.environ, f"{exc!r} {ign!r}")

    print("=== _proxy_pour_plateforme lit os.environ seulement ===")
    env_propre(TENDIA_PROXY_URL=PROXY)
    check("variable absente → False", H._proxy_pour_plateforme("dematis") is False)
    for valeur, attendu in (("1", True), ("true", True), ("on", True),
                            ("0", False), ("false", False), ("off", False), ("", False)):
        os.environ[CLE] = valeur
        check(f"os.environ à {valeur!r} → {attendu}",
              H._proxy_pour_plateforme("dematis") is attendu)
finally:
    os.environ.clear()
    os.environ.update(ENV_INITIAL)
    H._AVERTISSEMENT_PROXY_EMIS = False

check("os.environ restauré", dict(os.environ) == ENV_INITIAL)

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
