# -*- coding: utf-8 -*-
"""
tests/test_llm_router_backends.py
---------------------------------
Tests HORS-LIGNE des backends réels de tendia.analyse.llm_router, avec de faux SDK
(ajoutés après la relecture de l'étape 2 du chantier 2 : test_llm_router.py s'arrête
à la couture _appel_gemini / _appel_claude) :
  - options et system reçus tels quels par le SDK (Claude et Gemini) ;
  - essai interne rejoué (429) : kill switch relu avant le nouvel essai, essai échoué
    journalisé ;
  - tokens de cache de prompt comptés dans le coût ;
  - modèle sans tarif et option réservée refusés avant tout appel ;
  - repli : options non transmises à l'autre fournisseur, pas de repli sur erreur locale ;
  - interruption journalisée ; 4 threads : une entrée par appel.

Lancement : python tests/test_llm_router_backends.py
"""
import json
import os
import sys
import threading
import time
import types

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from base_temporaire import isoler_stockage
dossier = isoler_stockage()

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


# --- environnement hors ligne -----------------------------------------------------
R.charger_env = lambda: None
R._respecter_rate_limit = lambda modele: None
time.sleep = lambda s: None
for var in ("GEMINI_MODEL_ANALYSE", "GEMINI_MODEL_CLASSIF", "CLAUDE_MODEL_ANALYSE", "CLAUDE_MODEL_CLASSIF"):
    os.environ.pop(var, None)
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-fausse-cle-de-test"
os.environ["GEMINI_API_KEY"] = "fausse-cle-de-test"


def ecrire_budget(**cles):
    config = dict(budget.DEFAUT_BUDGET)
    config.update({"plafond_global_eur_mois": 1e12, "kill_switch_global": False})
    config.update(cles)
    budget.FICHIER_BUDGET.write_text(json.dumps(config), encoding="utf-8")


def journal(marche_id):
    stockage.invalider_cache("llm_appels")
    return sorted((a for a in stockage.charger("llm_appels").values() if a.get("marche_id") == marche_id),
                  key=lambda a: a["appele_le"])


class Erreur429(Exception):
    status_code = 429


# --- faux SDK Anthropic -------------------------------------------------------------
class FauxClaude:
    """messages.stream(**kw) : rejoue `scenario` (exceptions ou dicts d'usage), puis répond."""

    def __init__(self, scenario=None, texte='{"a": 1}'):
        self.appels = []
        self.scenario = list(scenario or [])
        self.texte = texte
        self.verrou = threading.Lock()
        self.messages = types.SimpleNamespace(stream=self._stream)

    def _stream(self, **kw):
        with self.verrou:
            self.appels.append(kw)
            etape = self.scenario.pop(0) if self.scenario else {}
        if callable(etape):
            etape = etape()
        if isinstance(etape, BaseException):
            raise etape
        usage = types.SimpleNamespace(input_tokens=1000, output_tokens=100)
        for k, v in (etape or {}).items():
            setattr(usage, k, v)
        message = types.SimpleNamespace(
            usage=usage, stop_reason="end_turn",
            content=[types.SimpleNamespace(type="text", text=self.texte)])
        return _Flux(message)


class _Flux:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


def brancher_claude(faux):
    R._client_claude = lambda timeout_s: faux
    return faux


# --- faux SDK Gemini ----------------------------------------------------------------
class FauxGemini:
    def __init__(self, scenario=None, texte='{"a": 1}'):
        self.appels = []
        self.scenario = list(scenario or [])
        self.texte = texte
        self.models = types.SimpleNamespace(generate_content=self._generer)

    def _generer(self, model=None, contents=None, config=None):
        self.appels.append({"model": model, "contents": contents, "config": config})
        etape = self.scenario.pop(0) if self.scenario else None
        if isinstance(etape, BaseException):
            raise etape
        return types.SimpleNamespace(
            usage_metadata=types.SimpleNamespace(prompt_token_count=2000, candidates_token_count=300,
                                                 thoughts_token_count=200),
            candidates=[types.SimpleNamespace(finish_reason=types.SimpleNamespace(name="STOP"))],
            text=self.texte)


def brancher_gemini(faux):
    R._CLIENT_GEMINI = faux
    return faux


SONNET, HAIKU, ARGON = "claude-sonnet-4-6", "claude-haiku-4-5", "gemini-4-argon"
TAUX = 0.92
ecrire_budget()
stockage.charger("llm_appels")   # base ouverte dans le thread principal

# =====================================================================================
print("=== A. Claude : options et system reçus tels quels par le SDK ===")
faux = brancher_claude(FauxClaude())
blocs = [{"type": "text", "text": "consigne", "cache_control": {"type": "ephemeral"}}]
res = R.call_llm("analyse", "bonjour", model=SONNET, type_appel="extraction", marche_id="M-A",
                 system=blocs, max_tokens=1234, options={"temperature": 0.2})
kw = faux.appels[0] if faux.appels else {}
check("un appel SDK, résultat ok", len(faux.appels) == 1 and res.ok, res.erreur)
check("model et max_tokens transmis", kw.get("model") == SONNET and kw.get("max_tokens") == 1234, kw)
check("system en blocs transmis tel quel (même objet)", kw.get("system") is blocs, kw.get("system"))
check("option temperature transmise telle quelle", kw.get("temperature") == 0.2, kw)
check("prompt dans le dernier bloc utilisateur",
      kw.get("messages", [{}])[0].get("content", [{}])[-1] == {"type": "text", "text": "bonjour"}, kw.get("messages"))
j = journal("M-A")
check("une entrée ok, modèle Sonnet, coût 3/15 au taux 0,92",
      len(j) == 1 and j[0]["statut"] == "ok" and j[0]["modele"] == SONNET
      and abs(j[0]["cout_eur"] - (1000 * 3 + 100 * 15) / 1e6 * TAUX) < 1e-6, j)

print("=== B. essai interne rejoué (429 puis succès) ===")
faux = brancher_claude(FauxClaude(scenario=[Erreur429("rate limit")]))
res = R.call_llm("classif", "x", model=HAIKU, type_appel="classification", marche_id="M-B", json_mode=False)
j = journal("M-B")
check("2 requêtes SDK, résultat ok", len(faux.appels) == 2 and res.ok, f"{len(faux.appels)} {res.erreur}")
check("2 entrées : l'essai échoué (erreur, 0 €) puis le succès",
      [a["statut"] for a in j] == ["erreur", "ok"] and j[0]["cout_eur"] == 0 and j[1]["cout_eur"] > 0, j)
check("l'essai échoué est marqué essai_interne=1", (j[0].get("extra") or {}).get("essai_interne") == 1, j[0])
check("res.appels détaille les 2 essais", len(res.appels) == 2, res.appels)

print("=== C. kill switch activé pendant un essai interne ===")


def _activer_kill_switch():
    ecrire_budget(kill_switch_global=True)
    return Erreur429("rate limit")


faux = brancher_claude(FauxClaude(scenario=[_activer_kill_switch]))
leve = None
try:
    R.call_llm("classif", "x", model=HAIKU, type_appel="classification", marche_id="M-C", json_mode=False)
except budget.BudgetDepasseError as e:
    leve = e
ecrire_budget()
j = journal("M-C")
check("BudgetDepasseError levée avant le 2e essai", leve is not None)
check("une seule requête SDK est partie", len(faux.appels) == 1, len(faux.appels))
check("l'essai déjà parti est journalisé (erreur)", [a["statut"] for a in j] == ["erreur"], j)

print("=== D. tokens de cache de prompt comptés ===")
faux = brancher_claude(FauxClaude(scenario=[{"cache_creation_input_tokens": 100_000,
                                             "cache_read_input_tokens": 50_000}]))
res = R.call_llm("analyse", "x", model=SONNET, type_appel="memoire", marche_id="M-D", json_mode=False)
attendu = (1000 * 3 + 100 * 15 + 100_000 * 3 * 1.25 + 50_000 * 3 * 0.1) / 1e6 * TAUX
j = journal("M-D")
check("coût = entrée + sortie + écriture cache ×1,25 + lecture cache ×0,1",
      abs((res.cout_eur or 0) - attendu) < 1e-6 and abs(j[0]["cout_eur"] - attendu) < 1e-6,
      f"{res.cout_eur} / {attendu}")
check("compteurs de cache dans extra",
      (j[0].get("extra") or {}).get("tokens_cache_ecriture") == 100_000
      and (j[0].get("extra") or {}).get("tokens_cache_lecture") == 50_000, j[0].get("extra"))
check("estimer_cout_eur sans cache inchangé",
      abs(R.estimer_cout_eur(SONNET, 1000, 100) - (1000 * 3 + 100 * 15) / 1e6 * TAUX) < 1e-9)

print("=== E. refus avant tout appel ===")
faux = brancher_claude(FauxClaude())
for nom, kwargs, exc_attendue in (
        ("modèle sans tarif", {"model": "claude-inconnu-9"}, ValueError),
        ("option réservée max_tokens", {"model": SONNET, "options": {"max_tokens": 5}}, ValueError),
        ("option réservée system", {"model": SONNET, "options": {"system": "x"}}, ValueError)):
    leve = None
    try:
        R.call_llm("analyse", "x", type_appel="extraction", marche_id="M-E", **kwargs)
    except Exception as e:  # noqa: BLE001
        leve = e
    check(f"{nom} → {exc_attendue.__name__}", isinstance(leve, exc_attendue), repr(leve))
check("aucun appel SDK, aucune entrée", not faux.appels and not journal("M-E"), journal("M-E"))

print("=== F. Gemini : options dans la config, réflexion facturée en sortie ===")
fg = brancher_gemini(FauxGemini())
res = R.call_llm("analyse", "bonjour", type_appel="extraction", marche_id="M-F",
                 system="consigne", options={"temperature": 0.1})
cfg = fg.appels[0]["config"] if fg.appels else None
check("un appel SDK sur gemini-4-argon, ok", len(fg.appels) == 1 and fg.appels[0]["model"] == ARGON and res.ok,
      res.erreur)
check("temperature et consigne système dans la config",
      cfg is not None and cfg.temperature == 0.1 and cfg.system_instruction == "consigne", cfg)
check("mode JSON demandé au SDK", cfg is not None and cfg.response_mime_type == "application/json")
check("tokens de sortie = réponse + réflexion", res.tokens_in == 2000 and res.tokens_out == 500,
      f"{res.tokens_in}/{res.tokens_out}")
j = journal("M-F")
check("une entrée ok au tarif argon du jour",
      len(j) == 1 and abs(j[0]["cout_eur"] - R.estimer_cout_eur(ARGON, 2000, 500)) < 1e-9, j)

print("=== G. repli : les options ne suivent pas vers l'autre fournisseur ===")
fg = brancher_gemini(FauxGemini(scenario=[ValueError("réponse invalide du service")]))
faux = brancher_claude(FauxClaude())
res = R.call_llm("analyse", "bonjour", type_appel="extraction", marche_id="M-G",
                 system="consigne", options={"temperature": 0.1})
kw = faux.appels[0] if faux.appels else {}
check("argon en échec puis un appel Sonnet, résultat ok",
      len(fg.appels) == 1 and len(faux.appels) == 1 and res.ok and res.repli and res.modele == SONNET, res.erreur)
check("option propre à argon absente de l'appel Sonnet", "temperature" not in kw, kw)
check("system et prompt identiques au repli",
      kw.get("system") == "consigne" and kw.get("messages", [{}])[0]["content"][-1]["text"] == "bonjour", kw)
j = journal("M-G")
check("journal : erreur (argon) puis repli (Sonnet)",
      [(a["statut"], a["modele"]) for a in j] == [("erreur", ARGON), ("repli", SONNET)], j)
n_avant = budget._compter_appels_jour("extraction")
check("un repli réussi compte dans le quota du jour", n_avant >= 2, n_avant)   # M-A, M-F... et ce repli

print("=== H. pas de repli payant sur une erreur locale ===")
R._CLIENT_GEMINI = None
cle = os.environ.pop("GEMINI_API_KEY")
faux = brancher_claude(FauxClaude())
res = R.call_llm("analyse", "bonjour", type_appel="extraction", marche_id="M-H")
os.environ["GEMINI_API_KEY"] = cle
j = journal("M-H")
check("clé Gemini absente : échec sans appel Sonnet", not res.ok and not faux.appels and not res.repli,
      f"{res.erreur} {len(faux.appels)}")
check("une entrée erreur à 0 €", [(a["statut"], a["cout_eur"]) for a in j] == [("erreur", 0.0)], j)

print("=== I. interruption pendant l'appel ===")
faux = brancher_claude(FauxClaude(scenario=[KeyboardInterrupt()]))
leve = None
try:
    R.call_llm("analyse", "x", model=SONNET, type_appel="extraction", marche_id="M-I")
except KeyboardInterrupt as e:
    leve = e
j = journal("M-I")
check("KeyboardInterrupt remonte", leve is not None)
check("l'appel interrompu est journalisé (erreur)",
      len(j) == 1 and j[0]["statut"] == "erreur" and "interrompu" in (j[0].get("erreur") or ""), j)

print("=== J. 4 threads : une entrée par appel ===")
faux = brancher_claude(FauxClaude())
erreurs = []


def _travail(n):
    try:
        for _ in range(10):
            r = R.call_llm("classif", "x", model=HAIKU, type_appel="classification",
                           marche_id=f"M-J-{n}", json_mode=False)
            if not r.ok:
                erreurs.append(r.erreur)
    except Exception as e:  # noqa: BLE001
        erreurs.append(repr(e))


fils = [threading.Thread(target=_travail, args=(n,)) for n in range(4)]
for f in fils:
    f.start()
for f in fils:
    f.join()
entrees = sum(len(journal(f"M-J-{n}")) for n in range(4))
check("aucune erreur dans les threads", not erreurs, erreurs[:3])
check("40 appels SDK, 40 entrées llm_appels", len(faux.appels) == 40 and entrees == 40,
      f"{len(faux.appels)} appels, {entrees} entrées")

print("=== K. Gemini : PDF joint dont le nom porte des accents ===")
# Constat de l'étape 7 du chantier 2 : « Cheminement prévisionnel….pdf » levait
# UnicodeEncodeError à l'envoi (nom affiché dans un en-tête HTTP), d'où un repli Sonnet payant.
import tempfile
from pathlib import Path as _Path


class FauxFichiersGemini:
    def __init__(self):
        self.envois = []

    def upload(self, file=None, config=None):
        config.display_name.encode("ascii")          # ce que fait la couche HTTP
        if isinstance(file, (str, os.PathLike)):
            os.path.basename(str(file)).encode("ascii")   # le SDK met aussi le nom du fichier en en-tête
            contenu = open(file, "rb").read()
        else:
            getattr(file, "name", "").encode("ascii")
            contenu = file.read()
        self.envois.append((contenu, config.display_name))
        return types.SimpleNamespace(name="files/abc", uri="https://exemple.invalid/files/abc",
                                     state=types.SimpleNamespace(name="ACTIVE"))

    def get(self, name=None):
        return types.SimpleNamespace(name=name, uri="u", state=types.SimpleNamespace(name="ACTIVE"))

    def delete(self, name=None):
        return None


fg = brancher_gemini(FauxGemini())
fg.files = FauxFichiersGemini()
pdf_accent = _Path(tempfile.mkdtemp(prefix="tendia_pdf_")) / "Cheminement prévisionnel entre nouveau PDL et poste PV – plan n°2.pdf"
pdf_accent.write_bytes(b"%PDF-1.4 faux pdf de test")
faux = brancher_claude(FauxClaude())
res = R.call_llm("analyse", "lis ce scan", documents=[str(pdf_accent)], type_appel="extraction", marche_id="M-K")
check("PDF au nom accentué : envoyé à Gemini sans erreur, pas de repli Sonnet",
      res.ok and not res.repli and len(fg.files.envois) == 1 and not faux.appels, f"{res.erreur} {len(faux.appels)}")
check("le contenu du PDF est bien celui du fichier", fg.files.envois and fg.files.envois[0][0] == b"%PDF-1.4 faux pdf de test")
check("le nom affiché est en ASCII et reste reconnaissable",
      fg.files.envois and fg.files.envois[0][1].isascii() and "Cheminement previsionnel" in fg.files.envois[0][1],
      fg.files.envois)
check("nom sans aucun caractère ASCII : nom de repli", R._nom_ascii("日本語.pdf").endswith(".pdf") and R._nom_ascii("日本語.pdf").isascii())

print("=== exp_appels reste vide ===")
check("rien dans exp_appels", not stockage.charger("exp_appels"))

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
