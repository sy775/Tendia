# -*- coding: utf-8 -*-
"""
tests/test_llm_calibration_journal.py
-------------------------------------
Tests HORS-LIGNE (chantier 2, étape 1) de la journalisation de
tendia.analyse.llm_calibration : chaque appel API de calibrer_bottom_up_seul (et de
calibrer, en best effort) produit une entrée llm_appels de type "calibration" :
  - statut "ok", coût > 0, modèle et marche_id quand l'API répond ;
  - statut "erreur", coût 0 quand l'API lève.
Faux client Anthropic, base et budget temporaires (jamais data/tendia.db).

Lancement : python tests/test_llm_calibration_journal.py
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
from tendia.analyse import llm_extract
from tendia.analyse import llm_calibration as LC

time.sleep = lambda *_a, **_k: None        # pas d'attente entre deux tentatives
LC.REPERTOIRE_CALIBRATIONS = dossier / "extractions_calibrees"

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
REPONSE = json.dumps({
    "fourchette_basse": 100000, "fourchette_haute": 150000, "fourchette_centrale": 125000,
    "fourchette": {"basse": 100000, "centrale": 125000, "haute": 150000},
    "confiance": "moyenne", "methode": "bottom_up", "analyse": "test", "hypotheses": [],
    "postes": [], "points_attention": []})


class _FauxMessages:
    def create(self, **kw):
        APPELS_API.append(kw)
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(type="text", text=REPONSE)],
            usage=types.SimpleNamespace(input_tokens=1000, output_tokens=100))


class _FauxClient:
    def __init__(self, *a, **k):
        self.messages = _FauxMessages()


class _MessagesEnErreur:
    def create(self, **kw):
        APPELS_API.append(kw)
        raise RuntimeError("panne simulée")


def _client_en_erreur(*a, **k):
    return types.SimpleNamespace(messages=_MessagesEnErreur())


anthropic.Anthropic = _FauxClient
llm_extract._check_anthropic = lambda: None

BRIEF = {
    "synthese_marche": "Réfection de la voirie communale et des réseaux d'eaux pluviales.",
    "objet": "Travaux de voirie et réseaux divers",
    "prestation_precise": "Reprise de 800 m de chaussée, bordures et assainissement pluvial",
    "acheteur": "Commune de Test", "lieu_execution": "Paris (75)",
    "duree_mois": 4, "type_marche": "TRAVAUX",
}


def journal(marche_id="__tous__"):
    stockage.invalider_cache()
    entrees = list((stockage.charger("llm_appels") or {}).values())
    if marche_id == "__tous__":
        return entrees
    return [e for e in entrees if e.get("marche_id") == marche_id]


def appeler(fonction, *args, **kwargs):
    """(résultat, exception) ; la sortie console de la fonction est absorbée."""
    tampon = io.StringIO()
    try:
        with contextlib.redirect_stdout(tampon), contextlib.redirect_stderr(tampon):
            return fonction(*args, **kwargs), None
    except Exception as e:  # noqa: BLE001
        return None, e


print("=== calibrer_bottom_up_seul : appel journalisé ===")
check("journal vide au départ", journal() == [])
n_avant = len(APPELS_API)
res, exc = appeler(LC.calibrer_bottom_up_seul, BRIEF, marche_id="M-CAL-1")
nb_appels = len(APPELS_API) - n_avant
entrees = journal("M-CAL-1")
check("au moins un appel API (faux client)", nb_appels >= 1, f"{nb_appels} appel(s), {exc!r}")
check("une entrée llm_appels par appel API", len(entrees) == nb_appels >= 1,
      f"{len(entrees)} entrée(s) pour {nb_appels} appel(s)")
check("type calibration", bool(entrees) and all(e.get("type") == "calibration" for e in entrees),
      str([e.get("type") for e in entrees]))
check("statut ok", bool(entrees) and all(e.get("statut") == "ok" for e in entrees),
      str([e.get("statut") for e in entrees]))
check("coût > 0", bool(entrees) and all((e.get("cout_eur") or 0) > 0 for e in entrees),
      str([e.get("cout_eur") for e in entrees]))
check("modèle renseigné", bool(entrees) and all(e.get("modele") for e in entrees),
      str([e.get("modele") for e in entrees]))
check("modèle journalisé = modèle envoyé à l'API",
      bool(entrees) and nb_appels >= 1
      and all(e.get("modele") == APPELS_API[n_avant].get("model") for e in entrees),
      f"{[e.get('modele') for e in entrees]} / {APPELS_API[n_avant].get('model') if nb_appels else None}")
check("marche_id renseigné", bool(entrees) and all(e.get("marche_id") == "M-CAL-1" for e in entrees))
check("tokens journalisés (1000 / 100)",
      bool(entrees) and all(e.get("tokens_input") == 1000 and e.get("tokens_output") == 100
                            for e in entrees),
      str([(e.get("tokens_input"), e.get("tokens_output")) for e in entrees]))
check("aucune entrée parasite (autre marché, autre type)", len(journal()) == len(entrees),
      str(len(journal())))

print("=== calibrer_bottom_up_seul : marche_id par défaut (None) ===")
n_journal = len(journal())
n_avant = len(APPELS_API)
res, exc = appeler(LC.calibrer_bottom_up_seul, BRIEF)
nb_appels = len(APPELS_API) - n_avant
nouvelles = [e for e in journal() if e.get("marche_id") != "M-CAL-1"]
check("appel sans marche_id journalisé quand même",
      nb_appels >= 1 and len(nouvelles) == nb_appels
      and all(e.get("type") == "calibration" and e.get("statut") == "ok"
              and (e.get("cout_eur") or 0) > 0 for e in nouvelles),
      f"{nb_appels} appel(s), {len(nouvelles)} entrée(s), {exc!r}")

print("=== calibrer_bottom_up_seul : brief vide ===")
n_journal = len(journal())
n_avant = len(APPELS_API)
res, exc = appeler(LC.calibrer_bottom_up_seul, {}, marche_id="M-CAL-VIDE")
nb_appels = len(APPELS_API) - n_avant
check("brief vide : autant d'entrées que d'appels API (0 ou plus)",
      len(journal("M-CAL-VIDE")) == nb_appels and len(journal()) - n_journal == nb_appels,
      f"{nb_appels} appel(s), {len(journal('M-CAL-VIDE'))} entrée(s), {exc!r}")

print("=== calibrer_bottom_up_seul : erreur API journalisée ===")
anthropic.Anthropic = _client_en_erreur
n_avant = len(APPELS_API)
res, exc = appeler(LC.calibrer_bottom_up_seul, BRIEF, marche_id="M-CAL-ERR")
nb_appels = len(APPELS_API) - n_avant
erreurs = journal("M-CAL-ERR")
check("au moins une tentative API", nb_appels >= 1, f"{nb_appels} appel(s), {exc!r}")
check("chaque tentative en erreur journalisée", len(erreurs) == nb_appels >= 1,
      f"{len(erreurs)} entrée(s) pour {nb_appels} appel(s)")
check("type calibration, statut erreur",
      bool(erreurs) and all(e.get("type") == "calibration" and e.get("statut") == "erreur"
                            for e in erreurs),
      str([(e.get("type"), e.get("statut")) for e in erreurs]))
check("coût 0 € en erreur", bool(erreurs) and all(e.get("cout_eur") == 0 for e in erreurs),
      str([e.get("cout_eur") for e in erreurs]))
check("pas de résultat de calibration quand l'API lève", not res, repr(res))

n_avant = len(APPELS_API)
res, exc = appeler(LC.calibrer_bottom_up_seul, BRIEF, max_retries=1, marche_id="M-CAL-ERR-1")
nb_appels = len(APPELS_API) - n_avant
erreurs1 = journal("M-CAL-ERR-1")
check("max_retries=1 : toujours une entrée erreur par tentative",
      nb_appels >= 1 and len(erreurs1) == nb_appels
      and all(e.get("statut") == "erreur" and e.get("cout_eur") == 0 for e in erreurs1),
      f"{nb_appels} appel(s), {len(erreurs1)} entrée(s), {exc!r}")
anthropic.Anthropic = _FauxClient

print("=== calibrer (best effort) ===")
COMPARABLES = [
    {"id": f"NOTIF-{i}", "similarite": 0.9, "score": 0.9, "montant": 100000 + 10000 * i,
     "montant_ht": 100000 + 10000 * i, "objet": "Travaux de voirie et réseaux divers",
     "titre": "Travaux de voirie", "acheteur": "Commune voisine", "acheteur_nom": "Commune voisine",
     "date_notification": "2025-06-01", "titulaire": "Entreprise Test"}
    for i in range(5)]
NOTIFIES = {c["id"]: dict(c, cpv=["45233140"], code_departement=["75"]) for c in COMPARABLES}

n_avant = len(APPELS_API)
res, exc = appeler(LC.calibrer, BRIEF, COMPARABLES, NOTIFIES, marche_id="M-CAL-2")
nb_appels = len(APPELS_API) - n_avant
entrees = journal("M-CAL-2")
if nb_appels >= 1:
    check("calibrer : une entrée llm_appels par appel API", len(entrees) == nb_appels,
          f"{len(entrees)} entrée(s) pour {nb_appels} appel(s)")
    check("calibrer : type calibration, statut ok, coût > 0, modèle, marche_id",
          bool(entrees) and all(e.get("type") == "calibration" and e.get("statut") == "ok"
                                and (e.get("cout_eur") or 0) > 0 and e.get("modele")
                                and e.get("marche_id") == "M-CAL-2" for e in entrees),
          str(entrees))
    anthropic.Anthropic = _client_en_erreur
    n_avant = len(APPELS_API)
    res, exc = appeler(LC.calibrer, BRIEF, COMPARABLES, NOTIFIES, marche_id="M-CAL-2-ERR")
    nb_err = len(APPELS_API) - n_avant
    erreurs = journal("M-CAL-2-ERR")
    check("calibrer : erreur API journalisée (statut erreur, 0 €)",
          nb_err >= 1 and len(erreurs) == nb_err
          and all(e.get("type") == "calibration" and e.get("statut") == "erreur"
                  and e.get("cout_eur") == 0 for e in erreurs),
          f"{nb_err} appel(s), {erreurs}")
    anthropic.Anthropic = _FauxClient
else:
    print(f"    (calibrer n'a fait aucun appel API avec ces comparables — non compté ; "
          f"résultat {type(res).__name__}, exception {exc!r})")
    check("calibrer sans appel API : aucune entrée llm_appels", entrees == [], str(entrees))

print("=== calibrer : sans comparables, ni appel ni journal ===")
n_avant = len(APPELS_API)
n_journal = len(journal())
res, exc = appeler(LC.calibrer, BRIEF, [], {}, marche_id="M-CAL-3")
check("aucun appel API, aucune entrée",
      len(APPELS_API) == n_avant and len(journal()) == n_journal, f"{exc!r}")
faibles = [dict(c, similarite=0.01) for c in COMPARABLES]
res, exc = appeler(LC.calibrer, BRIEF, faibles, NOTIFIES, marche_id="M-CAL-4")
check("comparables trop peu similaires : ni appel API ni entrée",
      len(APPELS_API) == n_avant and len(journal()) == n_journal,
      f"{len(APPELS_API) - n_avant} appel(s), {exc!r}")

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
