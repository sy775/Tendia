# -*- coding: utf-8 -*-
"""
tests/test_classification.py
----------------------------
Tests HORS-LIGNE de tendia.veille.classification (chantier 1), faux client Anthropic,
base et budget temporaires (jamais data/tendia.db) :
  - un appel est journalisé dans llm_appels (type classification, coût Haiku) ;
  - kill_switch_global=true lève BudgetDepasseError sans appel API ;
  - le pré-filtre rejette un avis d'attribution sans appel API ;
  - la classification est écrite unitairement (stockage.ecrire), supprimable.

Lancement : python tests/test_classification.py
"""
import json
import sys
import types

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from base_temporaire import isoler_stockage
dossier = isoler_stockage()

import anthropic
from tendia.core import budget, stockage
from tendia.veille import classification as C

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

MARCHE = {"id": "BOAMP-TEST-1", "titre": "Travaux de gros oeuvre", "objet": "Construction",
          "cpv_principal": "45210000", "acheteur_nom": "Commune de Test",
          "date_limite_depot": "2099-12-31"}

print("=== appel journalisé ===")
res = C.classifier_un_marche("BOAMP-TEST-1", MARCHE)
check("statut classifié", res["statut"] == "classifié", str(res.get("statut")))
check("1 appel API", len(APPELS_API) == 1)
check("modèle Haiku par défaut", APPELS_API and APPELS_API[0]["model"] == "claude-haiku-4-5")
appels = list(stockage.charger("llm_appels").values())
check("1 entrée llm_appels", len(appels) == 1, str(len(appels)))
a = appels[0] if appels else {}
cout_attendu = (1000 * 1.0 + 100 * 5.0) / 1_000_000 * 0.92   # table PRICING Haiku, USD -> EUR
check("type classification", a.get("type") == "classification")
check("coût = tarif Haiku du module", abs((a.get("cout_eur") or 0) - cout_attendu) < 1e-9,
      str(a.get("cout_eur")))
check("marche_id, tokens, statut ok",
      a.get("marche_id") == "BOAMP-TEST-1" and a.get("tokens_input") == 1000
      and a.get("tokens_output") == 100 and a.get("statut") == "ok")
check("classification écrite unitairement",
      stockage.lire("classifications_ia", "BOAMP-TEST-1") is not None)
check("déjà classifié au 2e passage, sans appel API",
      C.classifier_un_marche("BOAMP-TEST-1", MARCHE)["statut"] == "déjà_classifié"
      and len(APPELS_API) == 1)
C.supprimer_classification("BOAMP-TEST-1")
check("suppression unitaire", stockage.lire("classifications_ia", "BOAMP-TEST-1") is None)

print("=== erreur API journalisée ===")


class _MessagesEnErreur:
    def create(self, **kw):
        APPELS_API.append(kw)
        raise RuntimeError("panne simulée")


anthropic.Anthropic = lambda *a, **k: types.SimpleNamespace(messages=_MessagesEnErreur())
n_avant = len(APPELS_API)
res_err = C.classifier_un_marche("BOAMP-TEST-2", dict(MARCHE, id="BOAMP-TEST-2"))
erreurs = [x for x in stockage.charger("llm_appels").values()
           if x.get("marche_id") == "BOAMP-TEST-2"]
check("échec rendu sans exception", res_err["statut"] == "échec")
check("chaque tentative en erreur journalisée (statut erreur, coût 0)",
      len(erreurs) == len(APPELS_API) - n_avant == 2
      and all(x["statut"] == "erreur" and x["cout_eur"] == 0.0 for x in erreurs))
anthropic.Anthropic = _FauxClient

print("=== kill switch ===")
budget.FICHIER_BUDGET.write_text(json.dumps(dict(budget.DEFAUT_BUDGET, kill_switch_global=True)),
                                 encoding="utf-8")
n_avant = len(APPELS_API)
try:
    C.classifier(dict(MARCHE, id="BOAMP-TEST-3"))
    leve = False
except budget.BudgetDepasseError:
    leve = True
check("kill_switch_global=true lève BudgetDepasseError", leve)
check("aucun appel API sous kill switch", len(APPELS_API) == n_avant)
budget.FICHIER_BUDGET.write_text(json.dumps(budget.DEFAUT_BUDGET), encoding="utf-8")

print("=== pré-filtre ===")
attribution = dict(MARCHE, id="BOAMP-TEST-4", donnees={"notice_type": "ContractAwardNotice"})
rejette, raison = C.pre_filtre_rejette(attribution)
check("avis d'attribution rejeté", rejette and "ContractAwardNotice" in raison, raison)
n_avant = len(APPELS_API)
check("rejeté sans appel API",
      C.classifier_un_marche("BOAMP-TEST-4", attribution)["statut"] == "rejeté"
      and len(APPELS_API) == n_avant)
check("avis d'attribution au format BOAMP réel (nature=ATTRIBUTION) rejeté",
      C.pre_filtre_rejette({"id": "X", "nature": "ATTRIBUTION", "notice_type": "10 | 6"})[0])
check("appel d'offre (nature=APPEL_OFFRE, date future) non rejeté",
      not C.pre_filtre_rejette({"id": "X", "nature": "APPEL_OFFRE",
                                "date_limite_depot": "2099-01-01"})[0])
check("date limite passée rejetée",
      C.pre_filtre_rejette(dict(MARCHE, date_limite_depot="2020-01-01"))[0])

print("=== journaliser_appel ne lève jamais ===")
_orig = budget.enregistrer_appel
budget.enregistrer_appel = lambda *a, **k: (_ for _ in ()).throw(OSError("disque plein"))
try:
    check("échec d'écriture du journal -> None, pas d'exception",
          budget.journaliser_appel("classification", 0.01) is None)
finally:
    budget.enregistrer_appel = _orig

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
