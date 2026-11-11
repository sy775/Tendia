# -*- coding: utf-8 -*-
"""
tests/test_classification_max_cout.py
-------------------------------------
Tests HORS-LIGNE (chantier 2, étape 1) de tendia.veille.classification.main :
  - --max-cout 0 bloque tout appel : aucun appel API, aucune entrée llm_appels,
    aucune classification écrite, même s'il y a des marchés à classer ;
  - --max-cout 1 : le marché est classé (appel journalisé, classification écrite).
Faux client Anthropic, base et budget temporaires (jamais data/tendia.db).

Lancement : python tests/test_classification_max_cout.py
"""
import contextlib
import io
import json
import sys
import time
import types

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from base_temporaire import isoler_stockage
dossier = isoler_stockage()

import anthropic
from tendia.core import stockage
from tendia.veille import classification as C

time.sleep = lambda *_a, **_k: None   # pas d'attente entre deux marchés

ok = ko = 0


def check(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}  {detail}")


# --- Faux client Anthropic ---------------------------------------------------
APPELS_API = []
REPONSE = json.dumps({"domaines_metier": [{"code": "btp_gros_oeuvre"}],
                      "raison_classification": "test", "synthese_courte": "test"})


class _FauxMessages:
    def create(self, **kw):
        APPELS_API.append(kw)
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(type="text", text=REPONSE)],
            usage=types.SimpleNamespace(input_tokens=1000, output_tokens=100))


class _FauxClient:
    def __init__(self, *a, **k):
        self.messages = _FauxMessages()


anthropic.Anthropic = _FauxClient
C._check_anthropic = lambda: None

MARCHE = {"titre": "Travaux de gros oeuvre", "objet": "Construction",
          "cpv_principal": "45210000", "acheteur_nom": "Commune de Test",
          "date_limite_depot": "2099-12-31"}
IDS = ["BOAMP-MAXCOUT-1", "BOAMP-MAXCOUT-2"]
for mid in IDS:
    stockage.ecrire("marches", mid, dict(MARCHE, id=mid))
stockage.invalider_cache()


def lancer(argv):
    """C.main(argv) sans bruit ; retourne (sortie, exception éventuelle)."""
    sortie = io.StringIO()
    erreur = None
    with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(sortie):
        try:
            C.main(argv)
        except SystemExit as e:
            if e.code not in (0, None):
                erreur = e
        except Exception as e:  # noqa: BLE001
            erreur = e
    stockage.invalider_cache()
    return sortie.getvalue(), erreur


def etat():
    stockage.invalider_cache()
    return (len(APPELS_API), len(stockage.charger("llm_appels") or {}),
            sorted((stockage.charger("classifications_ia") or {}).keys()))


print("=== précondition : les marchés sont à classer ===")
check("le pré-filtre ne rejette pas le marché de test",
      not C.pre_filtre_rejette(dict(MARCHE, id=IDS[0]))[0])
check("aucune classification au départ", etat() == (0, 0, []), str(etat()))

print("=== --max-cout 0 avec --id ===")
sortie, erreur = lancer(["--id", IDS[0], "--id", IDS[1], "--max-cout", "0"])
check("main se termine sans exception", erreur is None, repr(erreur))
check("aucun appel API", len(APPELS_API) == 0, str(len(APPELS_API)))
check("aucune entrée llm_appels", not stockage.charger("llm_appels"),
      str(stockage.charger("llm_appels")))
check("aucune classification écrite",
      all(stockage.lire("classifications_ia", mid) is None for mid in IDS),
      str(etat()))

print("=== --max-cout 0 sans sélection explicite ===")
sortie, erreur = lancer(["--max-cout", "0"])
check("main se termine sans exception", erreur is None, repr(erreur))
check("toujours aucun appel API, journal ni classification", etat() == (0, 0, []), str(etat()))

print("=== --max-cout 0 avec --force et --limite ===")
sortie, erreur = lancer(["--id", IDS[0], "--force", "--limite", "5", "--max-cout", "0"])
check("main se termine sans exception", erreur is None, repr(erreur))
check("--force ne contourne pas le plafond 0", etat() == (0, 0, []), str(etat()))

print("=== --max-cout 0.0 (écriture décimale) ===")
sortie, erreur = lancer(["--id", IDS[0], "--max-cout", "0.0"])
check("0.0 bloque comme 0", erreur is None and etat() == (0, 0, []), f"{erreur!r} {etat()}")

print("=== --max-cout 1 : le marché est classé ===")
sortie, erreur = lancer(["--id", IDS[0], "--max-cout", "1"])
check("main se termine sans exception", erreur is None, repr(erreur))
check("1 appel API", len(APPELS_API) == 1, str(len(APPELS_API)))
classif = stockage.lire("classifications_ia", IDS[0])
check("classification écrite pour le marché demandé", classif is not None)
check("l'autre marché n'est pas classé", stockage.lire("classifications_ia", IDS[1]) is None)
appels = list((stockage.charger("llm_appels") or {}).values())
check("1 entrée llm_appels de type classification, statut ok, coût > 0",
      len(appels) == 1 and appels[0].get("type") == "classification"
      and appels[0].get("statut") == "ok" and (appels[0].get("cout_eur") or 0) > 0
      and appels[0].get("marche_id") == IDS[0], str(appels))

print("=== après un classement, --max-cout 0 bloque toujours ===")
avant = etat()
sortie, erreur = lancer(["--id", IDS[1], "--max-cout", "0"])
check("main se termine sans exception", erreur is None, repr(erreur))
check("aucun nouvel appel, aucune nouvelle écriture", etat() == avant, f"{avant} → {etat()}")

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
