# -*- coding: utf-8 -*-
"""
tests/test_appels_migres.py
---------------------------
Tests HORS-LIGNE des appels migrés vers llm_router au chantier 2 (ajoutés après la
relecture de l'étape 3), faux SDK Anthropic :
  - llm_router.appeler_modele : modèle explicite, ErreurLLM sur panne, réponse non JSON
    rendue avec json=None, parsing strict (pas de réparation), enveloppe et extra au journal ;
  - llm_extract.extraire_via_llm : modèle, system et max_tokens transmis, relance JSON
    journalisée, coût et tokens cumulés, kill switch qui remonte ;
  - auto_brief.generer_brief_light : idem, brief light, réponse non JSON, panne ;
  - débit : le routeur ne freine pas les appels Haiku lancés en parallèle.

Lancement : python tests/test_appels_migres.py
"""
import json
import sys
import threading
import time
import types

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from base_temporaire import isoler_stockage
dossier = isoler_stockage()

from tendia.analyse import auto_brief, llm_extract
from tendia.analyse import llm_router as R
from tendia.core import budget, stockage

ok = ko = 0


def check(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}  {str(detail)[:400]}")


R.charger_env = lambda: None
_rate_limit_reel = R._respecter_rate_limit
R._respecter_rate_limit = lambda modele: None
_sleep_reel = time.sleep
time.sleep = lambda s: None
llm_extract._check_anthropic = lambda: None
llm_extract._obtenir_cle_api = lambda: "sk-ant-fausse-cle-de-test"
auto_brief._obtenir_cle_api = lambda: "sk-ant-fausse-cle-de-test"

APPELS = []
SCENARIO = []     # réponses successives : texte, ou exception à lever
VERROU = threading.Lock()


class _Flux:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


def _stream(**kw):
    with VERROU:
        APPELS.append(kw)
        etape = SCENARIO.pop(0) if SCENARIO else '{"ok": true}'
    if isinstance(etape, BaseException):
        raise etape
    return _Flux(types.SimpleNamespace(
        usage=types.SimpleNamespace(input_tokens=10_000, output_tokens=1_000), stop_reason="end_turn",
        content=[types.SimpleNamespace(type="text", text=etape)]))


R._client_claude = lambda timeout_s: types.SimpleNamespace(messages=types.SimpleNamespace(stream=_stream))


def budget_fichier(**cles):
    config = dict(budget.DEFAUT_BUDGET)
    config.update({"plafond_global_eur_mois": 1e12, "extraction_max_par_jour": 10_000})
    config.update(cles)
    budget.FICHIER_BUDGET.write_text(json.dumps(config), encoding="utf-8")


def journal(marche_id):
    stockage.invalider_cache("llm_appels")
    return sorted((a for a in stockage.charger("llm_appels").values() if a.get("marche_id") == marche_id),
                  key=lambda a: a["appele_le"])


def scenario(*etapes):
    APPELS.clear()
    SCENARIO[:] = list(etapes)


budget_fichier()
SONNET = "claude-sonnet-4-6"
COUT = (10_000 * 3 + 1_000 * 15) / 1e6 * 0.92      # un appel Sonnet de ce faux client

# =====================================================================================
print("=== llm_router.appeler_modele ===")
scenario("bonjour")
r = R.appeler_modele("classif", "question", model="claude-haiku-4-5", type_appel="decp", marche_id="AM-1",
                     system="consigne", max_tokens=50, enveloppe="decp_reprise", extra_journal={"etiquette": "t1"})
j = journal("AM-1")
check("texte rendu tel quel, pas de JSON demandé", r.ok and r.texte == "bonjour" and r.json is None)
check("modèle explicite, system et max_tokens transmis au SDK",
      APPELS[0]["model"] == "claude-haiku-4-5" and APPELS[0]["system"] == "consigne"
      and APPELS[0]["max_tokens"] == 50, APPELS[0])
check("enveloppe et extra de l'appelant au journal",
      len(j) == 1 and j[0].get("enveloppe") == "decp_reprise" and j[0]["extra"].get("etiquette") == "t1", j)
check("la dépense de l'enveloppe voit l'appel", budget.depense_enveloppe("decp_reprise")["n"] == 1)

scenario(RuntimeError("panne simulée"))
leve = None
try:
    R.appeler_modele("analyse", "q", model=SONNET, type_appel="memoire", marche_id="AM-2")
except R.ErreurLLM as e:
    leve = e
j = journal("AM-2")
check("panne → ErreurLLM (RuntimeError) portant le résultat",
      isinstance(leve, RuntimeError) and leve.resultat.erreur and "panne simulée" in str(leve), repr(leve))
check("un seul appel (modèle explicite : pas de repli), une entrée erreur à 0 €",
      len(APPELS) == 1 and [(a["statut"], a["cout_eur"]) for a in j] == [("erreur", 0.0)], j)

scenario("Désolé, pas de JSON.")
r = R.appeler_modele("analyse", "q", model=SONNET, type_appel="extraction", marche_id="AM-3", json_mode=True)
j = journal("AM-3")
check("réponse non JSON : rendue sans exception, json None, pas de relance dans le routeur",
      r.json is None and not r.ok and len(APPELS) == 1, r.erreur)
check("réponse non JSON journalisée « erreur » avec son coût",
      len(j) == 1 and j[0]["statut"] == "erreur" and abs(j[0]["cout_eur"] - COUT) < 1e-6, j)

elide = '{"lots": [{"numero": 1}, ...], "montant": ...,}'
scenario(elide)
r = R.appeler_modele("analyse", "q", model=SONNET, type_appel="extraction", marche_id="AM-4", json_mode=True)
check("JSON élidé (« ... », virgule finale) rejeté par défaut : aucune réparation", r.json is None, r.json)
scenario(elide)
r = R.appeler_modele("analyse", "q", model=SONNET, type_appel="extraction", marche_id="AM-5", json_mode=True,
                     json_strict=False)
check("json_strict=False : le même texte est réparé", isinstance(r.json, dict), r.erreur)
scenario('```json\n{"a": 1}\n```')
r = R.appeler_modele("analyse", "q", model=SONNET, type_appel="extraction", marche_id="AM-6", json_mode=True)
check("bloc markdown toléré en strict", r.json == {"a": 1}, r.erreur)
scenario('Voici : {"a": 1} Fin.')
r = R.appeler_modele("analyse", "q", model=SONNET, type_appel="extraction", marche_id="AM-7", json_mode=True)
check("texte autour du JSON toléré en strict", r.json == {"a": 1}, r.erreur)

# =====================================================================================
print("=== llm_extract.extraire_via_llm ===")
BRIEF = json.dumps({"synthese_marche": "Réfection de toiture", "domaines_metier": []})
contexte = {"id": "EX-1", "titre": "Toiture de l'école"}
scenario(BRIEF)
data = llm_extract.extraire_via_llm("Règlement de consultation. " * 20, contexte, verbose=False)
j = journal("EX-1")
check("brief rendu", isinstance(data, dict) and data.get("synthese_marche") == "Réfection de toiture", data)
check("un appel : Sonnet 4.6, max_tokens du module, system = prompt système du module",
      len(APPELS) == 1 and APPELS[0]["model"] == llm_extract.MODELE == SONNET
      and APPELS[0]["max_tokens"] == llm_extract.MAX_TOKENS_REPONSE
      and isinstance(APPELS[0]["system"], str) and len(APPELS[0]["system"]) > 500, APPELS[0].get("model"))
check("le texte du DCE est dans le prompt utilisateur",
      "Règlement de consultation." in APPELS[0]["messages"][0]["content"][-1]["text"])
check("une entrée extraction ok", [(a["type"], a["statut"]) for a in j] == [("extraction", "ok")], j)
meta = (data or {}).get("_appel_llm") or {}
check("_appel_llm : modèle, coût, 1 tentative",
      meta.get("modele") == SONNET and abs(meta.get("cout_eur", 0) - COUT) < 1e-6
      and meta.get("nb_tentatives") == 1, meta)

contexte = {"id": "EX-2", "titre": "Relance"}
scenario("Voici le brief demandé, sans JSON.", BRIEF)
data = llm_extract.extraire_via_llm("texte " * 50, contexte, verbose=False)
j = journal("EX-2")
meta = (data or {}).get("_appel_llm") or {}
check("réponse non JSON puis JSON : 2 appels, brief rendu", len(APPELS) == 2 and isinstance(data, dict))
check("2 entrées llm_appels : erreur (payée) puis ok",
      [a["statut"] for a in j] == ["erreur", "ok"] and all(abs(a["cout_eur"] - COUT) < 1e-6 for a in j), j)
check("coût et tokens du brief cumulés sur les 2 tentatives",
      abs(meta.get("cout_eur", 0) - 2 * COUT) < 1e-6 and meta.get("tokens_input") == 20_000
      and meta.get("tokens_output") == 2_000 and meta.get("nb_tentatives") == 2, meta)

contexte = {"id": "EX-3", "titre": "Jamais de JSON"}
scenario("non", "toujours non")
data = llm_extract.extraire_via_llm("texte " * 50, contexte, verbose=False)
j = journal("EX-3")
check("2 réponses non JSON : None, 2 appels, 2 entrées erreur payées",
      data is None and len(APPELS) == 2 and [a["statut"] for a in j] == ["erreur", "erreur"]
      and abs(sum(a["cout_eur"] for a in j) - 2 * COUT) < 1e-6, j)

contexte = {"id": "EX-4", "titre": "Panne"}
scenario(RuntimeError("panne 1"), RuntimeError("panne 2"))
data = llm_extract.extraire_via_llm("texte " * 50, contexte, verbose=False)
j = journal("EX-4")
check("2 pannes : None, 2 entrées erreur à 0 €",
      data is None and [(a["statut"], a["cout_eur"]) for a in j] == [("erreur", 0.0)] * 2, j)

contexte = {"id": "EX-5", "titre": "Élidé"}
scenario('{"synthese_marche": "x", "lots": [{"numero": 1}, ...]}', BRIEF)
data = llm_extract.extraire_via_llm("texte " * 50, contexte, verbose=False)
check("brief élidé par le modèle : rejeté puis relancé (pas de lot « null » silencieux)",
      len(APPELS) == 2 and isinstance(data, dict) and None not in (data.get("lots") or []), data)

contexte = {"id": "EX-6", "titre": "Kill switch"}
scenario(BRIEF)
budget_fichier(kill_switch_global=True)
leve = None
try:
    llm_extract.extraire_via_llm("texte " * 50, contexte, verbose=False)
except budget.BudgetDepasseError as e:
    leve = e
budget_fichier()
check("kill switch : BudgetDepasseError, aucun appel API", leve is not None and not APPELS, repr(leve))

# plafond mensuel franchi par la 1re tentative : la relance ne part pas
contexte = {"id": "EX-7", "titre": "Plafond en cours de brief"}
scenario("pas de JSON", BRIEF)
stockage.invalider_cache("llm_appels")
depense = sum(float(a.get("cout_eur") or 0) for a in stockage.charger("llm_appels").values())
budget_fichier(plafond_global_eur_mois=depense + COUT / 2)
leve = None
try:
    llm_extract.extraire_via_llm("texte " * 50, contexte, verbose=False)
except budget.BudgetDepasseError as e:
    leve = e
budget_fichier()
check("plafond atteint après la 1re tentative : BudgetDepasseError remonte, pas de 2e appel",
      leve is not None and len(APPELS) == 1, f"{leve!r} {len(APPELS)}")

# =====================================================================================
print("=== auto_brief.generer_brief_light ===")
MARCHE = {"id": "AB-1", "titre": "Travaux de voirie", "acheteur_nom": "Commune de Test",
          "objet": "Réfection de la chaussée et des trottoirs de la rue principale, " * 3}
scenario(json.dumps({"synthese_marche": "Voirie"}))
data = auto_brief.generer_brief_light(dict(MARCHE), verbose=False)
j = journal("AB-1")
check("brief light rendu, marqué light", isinstance(data, dict) and (data.get("_meta") or {}).get("type") == "light", data)
check("un appel : modèle et max_tokens du module, prompt système du module",
      len(APPELS) == 1 and APPELS[0]["model"] == auto_brief.MODELE == SONNET
      and APPELS[0]["max_tokens"] == auto_brief.MAX_TOKENS_REPONSE
      and APPELS[0]["system"] == auto_brief.PROMPT_SYSTEME, APPELS[0].get("model") if APPELS else None)
check("une entrée extraction ok, coût dans _meta",
      [(a["type"], a["statut"]) for a in j] == [("extraction", "ok")]
      and abs(((data or {}).get("_meta") or {}).get("cout_eur", 0) - COUT) < 1e-4, j)

scenario("pas de JSON")
data = auto_brief.generer_brief_light(dict(MARCHE, id="AB-2"), verbose=False)
j = journal("AB-2")
check("réponse non JSON : None, une entrée erreur payée, pas de double journal",
      data is None and len(j) == 1 and j[0]["statut"] == "erreur" and j[0]["cout_eur"] > 0, j)

scenario(RuntimeError("panne"))
data = auto_brief.generer_brief_light(dict(MARCHE, id="AB-3"), verbose=False)
j = journal("AB-3")
check("panne : None, une entrée erreur à 0 €",
      data is None and [(a["statut"], a["cout_eur"]) for a in j] == [("erreur", 0.0)], j)

scenario(json.dumps({"synthese_marche": "x"}))
budget_fichier(kill_switch_global=True)
leve = None
try:
    auto_brief.generer_brief_light(dict(MARCHE, id="AB-4"), verbose=False)
except budget.BudgetDepasseError as e:
    leve = e
budget_fichier()
check("kill switch : BudgetDepasseError, aucun appel API", leve is not None and not APPELS, repr(leve))

# =====================================================================================
print("=== débit : le routeur ne freine pas Haiku en parallèle ===")
R._respecter_rate_limit = _rate_limit_reel
time.sleep = _sleep_reel
scenario()
debut = time.monotonic()
fils = [threading.Thread(target=lambda n=n: R.appeler_modele(
    "classif", "q", model="claude-haiku-4-5", type_appel="decp", marche_id=f"DEB-{n}")) for n in range(20)]
for f in fils:
    f.start()
for f in fils:
    f.join()
duree = time.monotonic() - debut
check("20 appels Haiku sur 20 threads en moins de 3 s (60 appels/min auraient pris 19 s)",
      len(APPELS) == 20 and duree < 3.0, f"{len(APPELS)} appels en {duree:.1f} s")
rpm = (R.config().get("rate_limits_rpm") or {})
check("config : débit Haiku et Sonnet au-dessus du défaut",
      rpm.get("claude-haiku-4-5", 0) >= 1000 and rpm.get("claude-sonnet-4-6", 0) > rpm.get("defaut", 60), rpm)

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
