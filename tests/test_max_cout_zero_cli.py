# -*- coding: utf-8 -*-
"""
tests/test_max_cout_zero_cli.py
-------------------------------
Tests HORS-LIGNE (ajoutés après la relecture de l'étape 1 du chantier 2) :
  - extraire.main(["--max-cout", "0"]) ne traite aucun marché, même s'il y en a ;
    avec un plafond positif, il traite jusqu'au plafond ;
  - pipeline.main transmet --max-cout-classification et --max-cout-extraction aux
    scripts des étapes 2 et 6 (0 compris) ;
  - llm_router.charger_env ne pose jamais TENDIA_PROXY_ACTIF lu dans .env.

Lancement : python tests/test_max_cout_zero_cli.py
"""
import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from base_temporaire import isoler_stockage
dossier = isoler_stockage()

from tendia import pipeline as P
from tendia.analyse import extraire as E
from tendia.analyse import llm_router as R
from tendia.core import stockage

ok = ko = 0


def check(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}  {detail}")


def silencieux(fn, *a, **k):
    """Lance fn sans rien afficher. Flux texte réel (les CLI appellent stdout.reconfigure)."""
    erreur = None
    with io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="replace") as sortie:
        with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(sortie):
            try:
                fn(*a, **k)
            except SystemExit as e:
                erreur = e if e.code not in (0, None) else None
            except Exception as e:  # noqa: BLE001
                erreur = e
    return "", erreur


# --- extraire.main -------------------------------------------------------------
print("=== extraire.main --max-cout ===")
E.REPERTOIRE_EXTRACTIONS = str(dossier / "extractions")
E.FICHIER_ETAT = os.path.join(E.REPERTOIRE_EXTRACTIONS, "_etat.json")
os.makedirs(E.REPERTOIRE_EXTRACTIONS, exist_ok=True)
A_TRAITER = [(f"M-{i}", str(dossier / "dce" / f"M-{i}"), {"rc.pdf": {"hash": f"h{i}", "texte": "texte"}}, "nouveau") for i in range(3)]
E.REPERTOIRE_DCE = str(dossier / "dce")     # jamais le vrai data/dce
E._scanner_dossiers_dce = lambda *a, **k: list(A_TRAITER)
E.llm_extract._obtenir_cle_api = lambda: "sk-ant-fausse-cle-de-test"
TRAITES = []


def _faux_traiter(id_marche, dossier_dce, pdfs, **kw):
    TRAITES.append(id_marche)
    return {"ok": True, "extraction": {"_meta": {"cout_eur": 0.5}}}


E.traiter_marche = _faux_traiter

_, err = silencieux(E.main, ["--max-cout", "0"])
check("--max-cout 0 : aucun marché traité", err is None and TRAITES == [], f"{err!r} {TRAITES}")
check("--max-cout 0 : état d'extraction non écrit", not os.path.exists(E.FICHIER_ETAT))
check("--max-cout 0 : aucune entrée llm_appels", not stockage.charger("llm_appels"))
_, err = silencieux(E.main, ["--max-cout", "0.0"])
check("--max-cout 0.0 bloque comme 0", err is None and TRAITES == [], f"{err!r} {TRAITES}")
_, err = silencieux(E.main, ["--max-cout", "0.6"])
check("--max-cout 0.6 à 0,5 € le brief : 2 marchés puis arrêt", err is None and TRAITES == ["M-0", "M-1"],
      f"{err!r} {TRAITES}")
TRAITES.clear()
_, err = silencieux(E.main, [])
check("sans --max-cout : les 3 marchés sont traités", err is None and len(TRAITES) == 3, f"{err!r} {TRAITES}")

# --- pipeline.main : transmission des plafonds -----------------------------------
print("=== pipeline.main : plafonds transmis aux étapes 2 et 6 ===")
LANCES = []
P._executer_script = lambda script, args=None: LANCES.append((Path(script).name, list(args or []))) or True


def args_de(nom):
    return next((a for s, a in LANCES if s == nom), None)


LANCES.clear()
_, err = silencieux(P.main, ["--skip-recup", "--skip-download", "--skip-dedies",
                             "--max-cout-classification", "0", "--max-cout-extraction", "0"])
check("pipeline : se termine sans exception", err is None, repr(err))
a = args_de("classification.py")
check("étape 2 : --max-cout 0 transmis à classification",
      a is not None and "--max-cout" in a and float(a[a.index("--max-cout") + 1]) == 0.0, str(a))
a = args_de("extraire.py")
check("étape 6 : --max-cout 0 transmis à extraire",
      a is not None and "--max-cout" in a and float(a[a.index("--max-cout") + 1]) == 0.0, str(a))

LANCES.clear()
silencieux(P.main, ["--skip-recup", "--skip-download", "--skip-dedies"])
a = args_de("classification.py")
check("défaut : classification plafonnée à 5 €",
      a is not None and float(a[a.index("--max-cout") + 1]) == 5.0, str(a))
a = args_de("extraire.py")
check("défaut : extraction plafonnée à 5 € elle aussi (étape 5 du chantier 2)",
      a is not None and "--max-cout" in a and float(a[a.index("--max-cout") + 1]) == 5.0, str(a))
check("le pipeline ne force pas le mode : extraire applique son défaut (document)", a is not None and "--mode" not in a, str(a))

LANCES.clear()
silencieux(P.main, ["--skip-recup", "--skip-download", "--skip-dedies", "--skip-llm",
                    "--max-cout-extraction", "3"])
check("--skip-llm : ni classification ni extraction lancées",
      args_de("classification.py") is None and args_de("extraire.py") is None, str(LANCES))

LANCES.clear()
silencieux(P.main, ["--skip-recup", "--skip-download", "--skip-dedies", "--max-cout-extraction", "2.5"])
a = args_de("extraire.py")
check("--max-cout-extraction 2.5 transmis",
      a is not None and "--max-cout" in a and float(a[a.index("--max-cout") + 1]) == 2.5, str(a))

# --- llm_router.charger_env : TENDIA_PROXY_ACTIF du fichier ignoré ---------------
print("=== llm_router.charger_env ===")
racine_avant, env_avant = R.RACINE, dict(os.environ)
try:
    faux = Path(tempfile.mkdtemp(prefix="tendia_test_env_"))
    (faux / ".env").write_text("TENDIA_PROXY_ACTIF=1\nTENDIA_CLE_DE_TEST_ROUTEUR=abc\n", encoding="utf-8")
    os.environ.pop("TENDIA_PROXY_ACTIF", None)
    os.environ.pop("TENDIA_CLE_DE_TEST_ROUTEUR", None)
    R.RACINE = faux
    R.charger_env()
    check("la clé ordinaire du fichier est chargée", os.environ.get("TENDIA_CLE_DE_TEST_ROUTEUR") == "abc")
    check("TENDIA_PROXY_ACTIF du fichier n'est pas posé", "TENDIA_PROXY_ACTIF" not in os.environ)
    os.environ["TENDIA_PROXY_ACTIF"] = "1"
    R.charger_env()
    check("TENDIA_PROXY_ACTIF du lanceur est conservé", os.environ.get("TENDIA_PROXY_ACTIF") == "1")
finally:
    R.RACINE = racine_avant
    os.environ.clear()
    os.environ.update(env_avant)

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
