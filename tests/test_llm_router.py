# -*- coding: utf-8 -*-
"""
tests/test_llm_router.py
------------------------
Tests HORS-LIGNE (chantier 2, étape 2) de tendia.analyse.llm_router : call_llm
journalisé (llm_appels) et plafonné (kill switch, plafond mensuel).

  - type_appel obligatoire et validé avant tout appel fournisseur ;
  - verifier_kill_switch avant CHAQUE tentative (1er appel, relance JSON, relance
    MAX_TOKENS, repli) ; plafond mensuel atteint → BudgetDepasseError ;
  - une entrée llm_appels par tentative (ok / erreur / repli), chacune avec son coût ;
  - relance JSON = deux appels, deux entrées, deux coûts ;
  - repli analyse vers claude-sonnet-4-6, journalisé « repli » ; modèle explicite respecté ;
  - tarif gemini-4-argon daté (avant / à partir du 2026-12-01), taux 0,92 unique ;
  - plus rien dans exp_appels.

Faux backends (R._appel_gemini / R._appel_claude), base et budget temporaires,
réseau coupé (socket) : aucun SDK, aucun appel payant.

Lancement : python tests/test_llm_router.py
"""
import contextlib
import datetime
import io
import json
import os
import socket
import sys
import time
import types

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from base_temporaire import isoler_stockage
dossier = isoler_stockage()

VARIABLES_MODELES = ("GEMINI_MODEL_ANALYSE", "GEMINI_MODEL_CLASSIF",
                     "CLAUDE_MODEL_ANALYSE", "CLAUDE_MODEL_CLASSIF", "OPUS_MODEL")
for _v in VARIABLES_MODELES:
    os.environ.pop(_v, None)

from tendia.core import budget, stockage
from tendia.analyse import llm_router as R

# .env ne doit pas être relu, et ce qu'il a pu poser à l'import est retiré.
R.charger_env = lambda *a, **k: None
for _v in VARIABLES_MODELES:
    os.environ.pop(_v, None)
# Fausses clés : si la couture des faux backends n'était pas respectée, aucun appel payant.
for _v in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
    os.environ[_v] = "cle-de-test-hors-ligne"


def _reseau_interdit(*_a, **_k):
    raise OSError("réseau interdit dans tests/test_llm_router.py")


socket.socket.connect = _reseau_interdit
socket.create_connection = _reseau_interdit
socket.getaddrinfo = _reseau_interdit

time.sleep = lambda *_a, **_k: None            # pas d'attente entre deux tentatives
R._respecter_rate_limit = lambda modele: None  # pas de limitation de débit

ARGON = "gemini-4-argon"
SONNET = "claude-sonnet-4-6"
HAIKU = "claude-haiku-4-5"
TAUX = 0.92

ok = ko = 0


def check(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}  {detail}")


def section(titre, fonction):
    """Une section qui plante compte pour un échec, sans arrêter les suivantes."""
    print(f"=== {titre} ===")
    try:
        fonction()
    except Exception as e:  # noqa: BLE001
        check(f"{titre} : section exécutée jusqu'au bout", False, f"{type(e).__name__}: {e}")
    finally:
        ecrire_budget()


# --- Budget temporaire -------------------------------------------------------
def ecrire_budget(**cles):
    """Réécrit le budget.json temporaire. Plafond mensuel très haut par défaut pour que
    le cumul des tests ne bloque pas les sections suivantes."""
    conf = dict(budget.DEFAUT_BUDGET)
    conf["kill_switch_global"] = False
    conf["plafond_global_eur_mois"] = 1e12
    conf.update(cles)
    budget.FICHIER_BUDGET.write_text(json.dumps(conf, ensure_ascii=False), encoding="utf-8")


ecrire_budget()


# --- Faux backends -----------------------------------------------------------
APPELS = []          # un dict par appel à un faux backend
JSON_OK = '{"objet": "Travaux de voirie", "montant": 125000}'
JSON_OK_DICT = {"objet": "Travaux de voirie", "montant": 125000}
NON_JSON = "Désolé, voici une réponse en prose sans aucun objet."
PROMPT = "Analyse ce DCE et rends un objet JSON."


def rep(texte=JSON_OK, tin=100000, tout=10000, finish="STOP", apres=None):
    """Réponse d'un faux backend. apres : fonction exécutée pendant l'appel (ex. activer
    le kill switch avant la tentative suivante)."""
    return {"texte": texte, "tin": tin, "tout": tout, "finish": finish, "apres": apres}


class FauxBackend:
    """Remplace R._appel_gemini / R._appel_claude. File de réponses : dict rep(...) ou
    exception. Une exception en fin de file est rejouée (retries) ; une file de réponses
    épuisée lève « appel inattendu »."""

    def __init__(self, nom):
        self.nom = nom
        self.file = []

    def __call__(self, res, prompt, system, documents, max_tokens, json_mode, timeout_s,
                 verbose, budget_tokens_entree=None, reflexion=None, options=None, **_kw):
        APPELS.append({"backend": self.nom, "modele": getattr(res, "modele", None),
                       "prompt": prompt, "system": system, "documents": documents,
                       "max_tokens": max_tokens, "json_mode": json_mode,
                       "budget_tokens_entree": budget_tokens_entree,
                       "reflexion": reflexion, "options": options})
        if not self.file:
            raise AssertionError(f"appel inattendu au faux backend {self.nom}")
        element = self.file[0]
        if not (isinstance(element, BaseException) and len(self.file) == 1):
            self.file.pop(0)
        if isinstance(element, BaseException):
            raise element
        res.texte = element["texte"]
        res.tokens_in = element["tin"]
        res.tokens_out = element["tout"]
        res.finish_reason = element["finish"]
        if element["apres"]:
            element["apres"]()
        return None


FAUX_GEMINI = FauxBackend("gemini")
FAUX_CLAUDE = FauxBackend("claude")
R._appel_gemini = FAUX_GEMINI
R._appel_claude = FAUX_CLAUDE


# --- Outils ------------------------------------------------------------------
def journal_brut(collection="llm_appels"):
    stockage.invalider_cache()
    return dict(stockage.charger(collection) or {})


def appeler(fonction, *args, **kwargs):
    """(résultat, exception) ; la sortie console de la fonction est absorbée."""
    tampon = io.StringIO()
    try:
        with contextlib.redirect_stdout(tampon), contextlib.redirect_stderr(tampon):
            return fonction(*args, **kwargs), None
    except Exception as e:  # noqa: BLE001
        return None, e


def lancer(gemini=(), claude=(), **kwargs):
    """Programme les faux backends, appelle call_llm, rend res / exc / appels / entrees
    (nouvelles entrées llm_appels de cet appel)."""
    APPELS.clear()
    FAUX_GEMINI.file = list(gemini)
    FAUX_CLAUDE.file = list(claude)
    avant = set(journal_brut())
    kwargs.setdefault("task", "analyse")
    kwargs.setdefault("prompt", PROMPT)
    kwargs.setdefault("type_appel", "extraction")
    if kwargs["type_appel"] is ABSENT:
        del kwargs["type_appel"]
    res, exc = appeler(R.call_llm, **kwargs)
    apres = journal_brut()
    return types.SimpleNamespace(
        res=res, exc=exc, appels=list(APPELS),
        entrees=[v for k, v in apres.items() if k not in avant],
        gemini=[a for a in APPELS if a["backend"] == "gemini"],
        claude=[a for a in APPELS if a["backend"] == "claude"])


ABSENT = object()


def champ(res, nom, defaut=None):
    return getattr(res, nom, defaut) if res is not None else defaut


def proche(a, b, tol=1e-4):
    try:
        return a is not None and b is not None and abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def aujourd_hui_utc():
    return datetime.datetime.now(datetime.timezone.utc).date()


def cout_attendu(modele, tin, tout, jour=None):
    """Coût recalculé indépendamment du module testé (tarifs de la spécification)."""
    jour = jour or aujourd_hui_utc()
    if modele == ARGON:
        f = 2 if jour >= datetime.date(2026, 12, 1) else 1
        usd = (tin * 2.0 * f + tout * 10.0 * f) / 1_000_000
    elif modele == SONNET:
        usd = (tin * 3.0 + tout * 15.0) / 1_000_000
    elif modele == HAIKU:
        usd = (tin * 1.0 + tout * 5.0) / 1_000_000
    else:
        return None
    return usd * TAUX


def statuts(entrees):
    return sorted(str(e.get("statut")) for e in entrees)


def somme_couts(entrees):
    return sum(float(e.get("cout_eur") or 0) for e in entrees)


def activer_kill_switch():
    ecrire_budget(kill_switch_global=True)


COUT_ARGON = cout_attendu(ARGON, 100000, 10000)      # 0,276 € avant le 01/12/2026
COUT_SONNET = cout_attendu(SONNET, 100000, 10000)    # 0,414 €


# =============================================================================
def test_config_et_tarifs():
    conf = R.config()
    check("config() rend un dict", isinstance(conf, dict), type(conf).__name__)
    check("config()['taux_usd_eur'] == 0.92", conf.get("taux_usd_eur") == 0.92,
          repr(conf.get("taux_usd_eur")))
    check("budget.TAUX_USD_EUR == 0.92", getattr(budget, "TAUX_USD_EUR", None) == 0.92,
          repr(getattr(budget, "TAUX_USD_EUR", None)))
    check("même taux dans budget et config_llm.yaml",
          getattr(budget, "TAUX_USD_EUR", None) == conf.get("taux_usd_eur"))
    check("config : repli analyse = claude-sonnet-4-6",
          (conf.get("repli") or {}).get("analyse") == SONNET, repr(conf.get("repli")))

    e = R.estimer_cout_eur
    v, exc = appeler(e, ARGON, 1_000_000, 100_000, date="2026-11-30")
    check("argon 1M in + 100k out le 2026-11-30 → 2,76 €", proche(v, 2.76, 1e-6), f"{v!r} {exc!r}")
    v, exc = appeler(e, ARGON, 1_000_000, 100_000, date="2026-12-01")
    check("argon 1M in + 100k out le 2026-12-01 → 5,52 €", proche(v, 5.52, 1e-6), f"{v!r} {exc!r}")
    v, exc = appeler(e, ARGON, 1_000_000, 0, date="2026-11-30")
    check("argon entrée seule avant : 2 $/M × 0,92 = 1,84 €", proche(v, 1.84, 1e-6), f"{v!r} {exc!r}")
    v, exc = appeler(e, ARGON, 0, 1_000_000, date="2026-11-30")
    check("argon sortie seule avant : 10 $/M × 0,92 = 9,20 €", proche(v, 9.20, 1e-6), f"{v!r} {exc!r}")
    v, exc = appeler(e, ARGON, 1_000_000, 0, date="2026-12-01")
    check("argon entrée seule après : 4 $/M × 0,92 = 3,68 €", proche(v, 3.68, 1e-6), f"{v!r} {exc!r}")
    v, exc = appeler(e, ARGON, 0, 1_000_000, date="2026-12-01")
    check("argon sortie seule après : 20 $/M × 0,92 = 18,40 €", proche(v, 18.40, 1e-6), f"{v!r} {exc!r}")

    v, exc = appeler(e, ARGON, 1_000_000, 100_000, date=datetime.date(2026, 11, 30))
    check("date en datetime.date (30/11) → 2,76 €", proche(v, 2.76, 1e-6), f"{v!r} {exc!r}")
    v, exc = appeler(e, ARGON, 1_000_000, 100_000, date=datetime.date(2026, 12, 1))
    check("date en datetime.date (01/12) → 5,52 €", proche(v, 5.52, 1e-6), f"{v!r} {exc!r}")
    v, exc = appeler(e, ARGON, 1_000_000, 100_000, date=datetime.datetime(2026, 11, 30, 23, 59, 59))
    check("datetime le 30/11 à 23:59:59 → ancien tarif", proche(v, 2.76, 1e-6), f"{v!r} {exc!r}")
    v, exc = appeler(e, ARGON, 1_000_000, 100_000, date=datetime.datetime(2026, 12, 1, 0, 0, 0))
    check("datetime le 01/12 à 00:00:00 → nouveau tarif", proche(v, 5.52, 1e-6), f"{v!r} {exc!r}")
    v, exc = appeler(e, ARGON, 1_000_000, 100_000, date="2026-01-15")
    check("date bien antérieure (2026-01-15) → ancien tarif", proche(v, 2.76, 1e-6), f"{v!r} {exc!r}")
    v, exc = appeler(e, ARGON, 1_000_000, 100_000, date="2027-06-01")
    check("date bien postérieure (2027-06-01) → nouveau tarif", proche(v, 5.52, 1e-6), f"{v!r} {exc!r}")

    jour_avant = aujourd_hui_utc()
    v, exc = appeler(e, ARGON, 1_000_000, 100_000)
    v_none, exc_none = appeler(e, ARGON, 1_000_000, 100_000, date=None)
    jour_apres = aujourd_hui_utc()
    attendus = {round(cout_attendu(ARGON, 1_000_000, 100_000, j), 6) for j in (jour_avant, jour_apres)}
    check("date absente = tarif du jour (UTC)", any(proche(v, a, 1e-6) for a in attendus),
          f"{v!r} attendu {attendus} {exc!r}")
    check("date=None = tarif du jour (UTC)", any(proche(v_none, a, 1e-6) for a in attendus),
          f"{v_none!r} attendu {attendus} {exc_none!r}")

    v, exc = appeler(e, ARGON, 0, 0, date="2026-12-01")
    check("zéro token → 0 €", exc is None and v == 0, f"{v!r} {exc!r}")
    v, exc = appeler(e, ARGON, 10**9, 10**9, date="2026-11-30")
    check("très grand volume (1 milliard in/out, avant) → 11 040 €", proche(v, 11040.0, 1e-3),
          f"{v!r} {exc!r}")
    v, exc = appeler(e, ARGON, 10**9, 10**9, date="2026-12-01")
    check("très grand volume (1 milliard in/out, après) → 22 080 €", proche(v, 22080.0, 1e-3),
          f"{v!r} {exc!r}")

    v1, exc1 = appeler(e, SONNET, 1_000_000, 100_000, date="2026-11-30")
    v2, exc2 = appeler(e, SONNET, 1_000_000, 100_000, date="2026-12-01")
    check("sonnet 4.6 : 3 / 15 → 4,14 € avant le 01/12", proche(v1, 4.14, 1e-6), f"{v1!r} {exc1!r}")
    check("sonnet 4.6 : tarif sans date, identique après le 01/12", proche(v2, 4.14, 1e-6),
          f"{v2!r} {exc2!r}")
    v, exc = appeler(e, SONNET, 1_000_000, 100_000)
    check("sonnet 4.6 sans date → 4,14 €", proche(v, 4.14, 1e-6), f"{v!r} {exc!r}")

    v, exc = appeler(e, "modele-inconnu-xyz", 1000, 1000)
    check("modèle inconnu → None", exc is None and v is None, f"{v!r} {exc!r}")
    v, exc = appeler(e, "modele-inconnu-xyz", 1000, 1000, date="2026-12-01")
    check("modèle inconnu avec date → None", exc is None and v is None, f"{v!r} {exc!r}")

    b, exc = appeler(budget.estimer_cout_eur, 1_000_000, 100_000)
    check("budget.estimer_cout_eur : Sonnet 3 / 15 au taux 0,92 → 4,14 €", proche(b, 4.14, 1e-4),
          f"{b!r} {exc!r}")
    check("budget.estimer_cout_eur == R.estimer_cout_eur(sonnet)", proche(b, v1, 1e-4), f"{b!r} / {v1!r}")
    b0, exc = appeler(budget.estimer_cout_eur, 0, 0)
    check("budget.estimer_cout_eur(0, 0) == 0", exc is None and b0 == 0, f"{b0!r} {exc!r}")


# =============================================================================
def test_type_appel():
    r = lancer(gemini=[rep()], claude=[rep()], type_appel=ABSENT)
    check("type_appel absent → TypeError", isinstance(r.exc, TypeError), f"{r.exc!r} / {r.res!r}")
    check("type_appel absent : aucun appel fournisseur, aucune entrée",
          r.appels == [] and r.entrees == [], f"{len(r.appels)} appel(s), {len(r.entrees)} entrée(s)")

    for inconnu in ("inconnu", "Extraction", "exp", ""):
        r = lancer(gemini=[rep()], claude=[rep()], type_appel=inconnu)
        check(f"type_appel {inconnu!r} → ValueError",
              isinstance(r.exc, ValueError), f"{r.exc!r} / {r.res!r}")
        check(f"type_appel {inconnu!r} : aucun appel fournisseur, aucune entrée",
              r.appels == [] and r.entrees == [],
              f"{len(r.appels)} appel(s), {len(r.entrees)} entrée(s)")

    r = lancer(gemini=[rep()], claude=[rep()], type_appel=None)
    check("type_appel=None refusé (TypeError ou ValueError)",
          isinstance(r.exc, (TypeError, ValueError)), f"{r.exc!r} / {r.res!r}")
    check("type_appel=None : aucun appel fournisseur, aucune entrée",
          r.appels == [] and r.entrees == [], f"{len(r.appels)} appel(s), {len(r.entrees)} entrée(s)")

    r = lancer(gemini=[rep()], claude=[rep()], model=SONNET, type_appel="inconnu")
    check("type inconnu avec modèle explicite Claude → ValueError avant tout appel",
          isinstance(r.exc, ValueError) and r.appels == [] and r.entrees == [], f"{r.exc!r}")

    check("TYPES_VALIDES = les six types de la spécification",
          set(budget.TYPES_VALIDES) == {"classification", "extraction", "memoire", "digest",
                                        "calibration", "decp"}, str(budget.TYPES_VALIDES))
    for t in sorted(budget.TYPES_VALIDES):
        r = lancer(gemini=[rep(tin=1000, tout=100)], task="classif", model="gemini",
                   type_appel=t, marche_id=f"M-TYPE-{t}")
        check(f"type_appel {t!r} accepté : 1 appel, 1 entrée de ce type, statut ok",
              r.exc is None and champ(r.res, "ok") is True and len(r.appels) == 1
              and len(r.entrees) == 1 and r.entrees[0].get("type") == t
              and r.entrees[0].get("statut") == "ok"
              and r.entrees[0].get("marche_id") == f"M-TYPE-{t}",
              f"{r.exc!r} appels={len(r.appels)} entrees={r.entrees}")


# =============================================================================
def test_plafond_mensuel():
    check("journal vide au départ", journal_brut() == {}, str(len(journal_brut())))
    ecrire_budget(plafond_global_eur_mois=0.01)
    r = lancer(gemini=[rep()], marche_id="M-PLAFOND-1")
    check("plafond 0,01 €, journal vide : le premier appel passe",
          r.exc is None and champ(r.res, "ok") is True and len(r.gemini) == 1, f"{r.exc!r}")
    check("première entrée payante (coût > 0,01 €)",
          len(r.entrees) == 1 and (r.entrees[0].get("cout_eur") or 0) > 0.01, str(r.entrees))
    r2 = lancer(gemini=[rep()], claude=[rep()], marche_id="M-PLAFOND-2")
    check("plafond mensuel atteint → BudgetDepasseError",
          isinstance(r2.exc, budget.BudgetDepasseError), f"{r2.exc!r} / {r2.res!r}")
    check("plafond atteint : aucun appel fournisseur", r2.appels == [], str(len(r2.appels)))
    check("plafond atteint : aucune entrée llm_appels", r2.entrees == [], str(r2.entrees))
    r3 = lancer(gemini=[rep()], claude=[rep()], model=SONNET, marche_id="M-PLAFOND-3")
    check("plafond atteint : modèle explicite Claude bloqué aussi",
          isinstance(r3.exc, budget.BudgetDepasseError) and r3.appels == [] and r3.entrees == [],
          f"{r3.exc!r}")
    ecrire_budget()
    r4 = lancer(gemini=[rep()], marche_id="M-PLAFOND-4")
    check("plafond relevé : l'appel repasse", r4.exc is None and champ(r4.res, "ok") is True
          and len(r4.entrees) == 1, f"{r4.exc!r}")


# =============================================================================
def test_nominal():
    r = lancer(gemini=[rep()], marche_id="M-NOM-1")
    res = r.res
    check("aucune exception", r.exc is None, repr(r.exc))
    check("rend un LLMResult", isinstance(res, R.LLMResult), type(res).__name__)
    check("un seul appel fournisseur, côté Gemini", len(r.gemini) == 1 and r.claude == [],
          f"gemini={len(r.gemini)} claude={len(r.claude)}")
    check("modèle par défaut de la tâche analyse = gemini-4-argon",
          bool(r.gemini) and r.gemini[0]["modele"] == ARGON, str([a["modele"] for a in r.appels]))
    check("prompt transmis", bool(r.gemini) and r.gemini[0]["prompt"] == PROMPT)
    check("json_mode=True par défaut transmis au backend",
          bool(r.gemini) and r.gemini[0]["json_mode"] is True)
    check("premier appel : reflexion None", bool(r.gemini) and r.gemini[0]["reflexion"] is None)
    check("res.ok", champ(res, "ok") is True, repr(champ(res, "erreur")))
    check("res.task == 'analyse'", champ(res, "task") == "analyse", repr(champ(res, "task")))
    check("res.fournisseur == 'gemini'", champ(res, "fournisseur") == "gemini")
    check("res.modele == gemini-4-argon", champ(res, "modele") == ARGON, repr(champ(res, "modele")))
    check("res.modele_demande == gemini-4-argon", champ(res, "modele_demande") == ARGON,
          repr(champ(res, "modele_demande")))
    check("res.repli False", champ(res, "repli", "absent") is False, repr(champ(res, "repli", "absent")))
    check("res.json = objet décodé", champ(res, "json") == JSON_OK_DICT, repr(champ(res, "json")))
    check("res.texte = texte du fournisseur", champ(res, "texte") == JSON_OK)
    check("res.tokens_in / tokens_out", champ(res, "tokens_in") == 100000
          and champ(res, "tokens_out") == 10000)
    check("res.erreur vide", not champ(res, "erreur"), repr(champ(res, "erreur")))
    check("res.finish_reason == 'STOP'", champ(res, "finish_reason") == "STOP")
    check("res.cout_eur = tarif argon du jour", proche(champ(res, "cout_eur"), COUT_ARGON),
          f"{champ(res, 'cout_eur')!r} attendu {COUT_ARGON}")
    check("res.cout_total_eur == res.cout_eur (une seule tentative)",
          proche(champ(res, "cout_total_eur"), COUT_ARGON), repr(champ(res, "cout_total_eur")))
    appels = champ(res, "appels") or []
    check("res.appels : une tentative", len(appels) == 1, repr(appels))
    check("res.appels[0] : modele, statut, cout_eur, tokens_in, tokens_out",
          len(appels) == 1 and appels[0].get("modele") == ARGON and appels[0].get("statut") == "ok"
          and proche(appels[0].get("cout_eur"), COUT_ARGON) and appels[0].get("tokens_in") == 100000
          and appels[0].get("tokens_out") == 10000, repr(appels))

    check("une entrée llm_appels", len(r.entrees) == 1, str(len(r.entrees)))
    e = r.entrees[0] if r.entrees else {}
    check("entrée : type = type_appel", e.get("type") == "extraction", repr(e.get("type")))
    check("entrée : marche_id", e.get("marche_id") == "M-NOM-1", repr(e.get("marche_id")))
    check("entrée : modele réellement appelé", e.get("modele") == ARGON, repr(e.get("modele")))
    check("entrée : tokens_input / tokens_output",
          e.get("tokens_input") == 100000 and e.get("tokens_output") == 10000,
          f"{e.get('tokens_input')!r} / {e.get('tokens_output')!r}")
    check("entrée : cout_eur = tarif argon du jour", proche(e.get("cout_eur"), COUT_ARGON),
          f"{e.get('cout_eur')!r} attendu {COUT_ARGON}")
    check("entrée : duree_ms numérique >= 0",
          isinstance(e.get("duree_ms"), (int, float)) and e.get("duree_ms") >= 0,
          repr(e.get("duree_ms")))
    check("entrée : statut ok", e.get("statut") == "ok", repr(e.get("statut")))
    check("entrée ok : champ erreur vide", not e.get("erreur"), repr(e.get("erreur")))

    r = lancer(gemini=[rep()], model="gemini", marche_id="M-NOM-ALIAS")
    check("alias 'gemini' → modèle par défaut de la tâche (argon)",
          champ(r.res, "ok") is True and len(r.gemini) == 1 and r.gemini[0]["modele"] == ARGON
          and r.claude == [] and len(r.entrees) == 1 and r.entrees[0].get("modele") == ARGON,
          f"{r.exc!r} {[a['modele'] for a in r.appels]}")

    # options et system transmis tels quels
    options = {"temperature": 0.2}
    r = lancer(gemini=[rep()], options=options, system="Tu es un économiste du BTP.",
               marche_id="M-NOM-OPT")
    check("options transmises telles quelles au backend Gemini",
          len(r.gemini) == 1 and r.gemini[0]["options"] == {"temperature": 0.2},
          repr([a["options"] for a in r.appels]))
    check("options de l'appelant non modifiées", options == {"temperature": 0.2}, repr(options))
    check("system (chaîne) transmis tel quel",
          len(r.gemini) == 1 and r.gemini[0]["system"] == "Tu es un économiste du BTP.",
          repr([a["system"] for a in r.appels]))

    blocs = [{"type": "text", "text": "Contexte long du DCE", "cache_control": {"type": "ephemeral"}},
             {"type": "text", "text": "Consignes"}]
    copie = json.loads(json.dumps(blocs))
    options_c = {"temperature": 0.0, "top_p": 0.9}
    r = lancer(claude=[rep(finish="end_turn")], model=SONNET, system=blocs, options=options_c,
               marche_id="M-NOM-CACHE")
    check("system en liste de blocs (cache de prompt) transmis tel quel au backend Claude",
          len(r.claude) == 1 and r.claude[0]["system"] == copie and r.gemini == [],
          repr([a["system"] for a in r.appels]))
    check("blocs system de l'appelant non modifiés", blocs == copie)
    check("options transmises telles quelles au backend Claude",
          len(r.claude) == 1 and r.claude[0]["options"] == {"temperature": 0.0, "top_p": 0.9},
          repr([a["options"] for a in r.appels]))

    r = lancer(gemini=[rep()], max_tokens=1234, budget_tokens_entree=50000, marche_id="M-NOM-MAX")
    check("max_tokens explicite transmis au backend",
          len(r.gemini) == 1 and r.gemini[0]["max_tokens"] == 1234,
          repr([a["max_tokens"] for a in r.appels]))
    check("budget_tokens_entree transmis au backend",
          len(r.gemini) == 1 and r.gemini[0]["budget_tokens_entree"] == 50000,
          repr([a["budget_tokens_entree"] for a in r.appels]))


# =============================================================================
def test_relance_json():
    r = lancer(gemini=[rep(NON_JSON, tin=100000, tout=10000), rep(JSON_OK, tin=120000, tout=20000)],
               marche_id="M-RJ-1", options={"temperature": 0.2}, system="Consigne système")
    res = r.res
    c1 = cout_attendu(ARGON, 100000, 10000)
    c2 = cout_attendu(ARGON, 120000, 20000)
    check("aucune exception", r.exc is None, repr(r.exc))
    check("non JSON puis JSON : 2 appels fournisseur", len(r.appels) == 2, str(len(r.appels)))
    check("relance avec le même modèle, aucun appel Claude",
          [a["modele"] for a in r.gemini] == [ARGON, ARGON] and r.claude == [],
          str([(a["backend"], a["modele"]) for a in r.appels]))
    check("prompt de relance = prompt initial complété d'un rappel de format",
          len(r.gemini) == 2 and r.gemini[0]["prompt"] == PROMPT
          and PROMPT in r.gemini[1]["prompt"] and len(r.gemini[1]["prompt"]) > len(PROMPT),
          repr(r.gemini[1]["prompt"][:200]) if len(r.gemini) == 2 else "")
    check("options retransmises telles quelles à la relance",
          len(r.gemini) == 2 and r.gemini[1]["options"] == {"temperature": 0.2},
          repr([a["options"] for a in r.appels]))
    check("system retransmis tel quel à la relance",
          len(r.gemini) == 2 and r.gemini[1]["system"] == "Consigne système")
    check("résultat ok après relance", champ(res, "ok") is True, repr(champ(res, "erreur")))
    check("res.json = réponse de la relance", champ(res, "json") == JSON_OK_DICT)
    check("pas de repli", champ(res, "repli", "absent") is False and champ(res, "modele") == ARGON)
    check("2 entrées llm_appels", len(r.entrees) == 2, str(len(r.entrees)))
    check("statuts : une erreur puis un ok", statuts(r.entrees) == ["erreur", "ok"], str(statuts(r.entrees)))
    err = [e for e in r.entrees if e.get("statut") == "erreur"]
    bon = [e for e in r.entrees if e.get("statut") == "ok"]
    check("entrée erreur : coût de la 1re tentative (> 0, facturée)",
          len(err) == 1 and proche(err[0].get("cout_eur"), c1) and err[0].get("cout_eur") > 0,
          f"{[e.get('cout_eur') for e in err]} attendu {c1}")
    check("entrée erreur : champ erreur renseigné", len(err) == 1 and bool(err[0].get("erreur")),
          repr([e.get("erreur") for e in err]))
    check("entrée erreur : tokens de la 1re tentative",
          len(err) == 1 and err[0].get("tokens_input") == 100000 and err[0].get("tokens_output") == 10000)
    check("entrée ok : coût de la 2e tentative",
          len(bon) == 1 and proche(bon[0].get("cout_eur"), c2),
          f"{[e.get('cout_eur') for e in bon]} attendu {c2}")
    check("entrée ok : tokens de la 2e tentative",
          len(bon) == 1 and bon[0].get("tokens_input") == 120000 and bon[0].get("tokens_output") == 20000)
    check("les deux entrées : type, marche_id, modele",
          all(e.get("type") == "extraction" and e.get("marche_id") == "M-RJ-1"
              and e.get("modele") == ARGON for e in r.entrees) and len(r.entrees) == 2)
    check("deux coûts : somme du journal = c1 + c2", proche(somme_couts(r.entrees), c1 + c2),
          f"{somme_couts(r.entrees)} attendu {c1 + c2}")
    check("res.cout_eur = dernière tentative", proche(champ(res, "cout_eur"), c2),
          repr(champ(res, "cout_eur")))
    check("res.cout_total_eur = somme des deux tentatives",
          proche(champ(res, "cout_total_eur"), c1 + c2), repr(champ(res, "cout_total_eur")))
    appels = champ(res, "appels") or []
    check("res.appels : erreur puis ok, dans l'ordre",
          [a.get("statut") for a in appels] == ["erreur", "ok"], repr(appels))
    check("res.appels : coûts et tokens par tentative",
          len(appels) == 2 and proche(appels[0].get("cout_eur"), c1)
          and proche(appels[1].get("cout_eur"), c2)
          and appels[0].get("tokens_in") == 100000 and appels[1].get("tokens_out") == 20000,
          repr(appels))

    # réponses qui ne sont pas un objet JSON : vide, liste
    for nom, texte in (("réponse vide", ""), ("liste JSON (pas un objet)", "[1, 2, 3]")):
        r = lancer(gemini=[rep(texte), rep(JSON_OK)], marche_id="M-RJ-LIM")
        check(f"{nom} → une relance, puis ok",
              r.exc is None and len(r.gemini) == 2 and r.claude == []
              and champ(r.res, "ok") is True and statuts(r.entrees) == ["erreur", "ok"],
              f"{r.exc!r} appels={len(r.appels)} statuts={statuts(r.entrees)}")

    # relance_json par défaut désactivée pour classif
    r = lancer(claude=[rep(NON_JSON, tin=1000, tout=100, finish="end_turn"), rep(finish="end_turn")],
               task="classif", model=HAIKU, type_appel="classification", marche_id="M-RJ-CLASSIF")
    check("classif, relance_json=None : pas de relance (1 appel)",
          r.exc is None and len(r.claude) == 1 and r.gemini == [],
          f"{r.exc!r} claude={len(r.claude)} gemini={len(r.gemini)}")
    check("classif non JSON : res.ok False, erreur renseignée, res.json None",
          champ(r.res, "ok") is False and bool(champ(r.res, "erreur")) and champ(r.res, "json") is None,
          f"ok={champ(r.res, 'ok')!r} erreur={champ(r.res, 'erreur')!r}")
    check("classif non JSON : 1 entrée erreur, coût > 0 (facturée), erreur renseignée",
          len(r.entrees) == 1 and r.entrees[0].get("statut") == "erreur"
          and proche(r.entrees[0].get("cout_eur"), cout_attendu(HAIKU, 1000, 100), 1e-5)
          and (r.entrees[0].get("cout_eur") or 0) > 0 and bool(r.entrees[0].get("erreur"))
          and r.entrees[0].get("type") == "classification" and r.entrees[0].get("modele") == HAIKU,
          str(r.entrees))

    # relance_json=True force la relance pour classif
    r = lancer(claude=[rep(NON_JSON, tin=1000, tout=100, finish="end_turn"),
                       rep(JSON_OK, tin=1000, tout=100, finish="end_turn")],
               task="classif", model=HAIKU, type_appel="classification", relance_json=True,
               marche_id="M-RJ-CLASSIF-T")
    check("classif, relance_json=True : relance forcée (2 appels, même modèle)",
          r.exc is None and [a["modele"] for a in r.claude] == [HAIKU, HAIKU] and r.gemini == [],
          f"{r.exc!r} {[(a['backend'], a['modele']) for a in r.appels]}")
    check("classif relancée : ok, 2 entrées (erreur, ok)",
          champ(r.res, "ok") is True and statuts(r.entrees) == ["erreur", "ok"], str(statuts(r.entrees)))

    # relance_json=False force l'absence de relance pour analyse (modèle explicite : pas de repli)
    r = lancer(gemini=[rep(NON_JSON), rep(JSON_OK)], claude=[rep()], model=ARGON, relance_json=False,
               marche_id="M-RJ-F")
    check("analyse, relance_json=False : pas de relance (1 appel)",
          r.exc is None and len(r.gemini) == 1 and r.claude == [],
          f"{r.exc!r} gemini={len(r.gemini)} claude={len(r.claude)}")
    check("analyse sans relance : res.ok False, 1 entrée erreur à coût > 0",
          champ(r.res, "ok") is False and len(r.entrees) == 1
          and r.entrees[0].get("statut") == "erreur" and proche(r.entrees[0].get("cout_eur"), COUT_ARGON),
          str(r.entrees))

    # une seule relance : deux réponses non JSON, modèle explicite → 2 appels, pas 3
    r = lancer(gemini=[rep(NON_JSON), rep(NON_JSON), rep(JSON_OK)], claude=[rep()], model=ARGON,
               marche_id="M-RJ-2X")
    check("UNE seule relance JSON (2 appels, pas 3)", r.exc is None and len(r.gemini) == 2,
          f"{r.exc!r} gemini={len(r.gemini)}")
    check("JSON invalide après relance : res.ok False, erreur renseignée",
          champ(r.res, "ok") is False and bool(champ(r.res, "erreur")))
    check("JSON invalide après relance : 2 entrées erreur, chacune facturée",
          statuts(r.entrees) == ["erreur", "erreur"]
          and all(proche(e.get("cout_eur"), COUT_ARGON) and e.get("erreur") for e in r.entrees),
          str(r.entrees))
    check("res.cout_total_eur = 2 tentatives facturées",
          proche(champ(r.res, "cout_total_eur"), 2 * COUT_ARGON), repr(champ(r.res, "cout_total_eur")))


# =============================================================================
def test_relance_max_tokens():
    r = lancer(gemini=[rep("", tin=100000, tout=32768, finish="MAX_TOKENS"),
                       rep(JSON_OK, tin=100000, tout=9000, finish="STOP")],
               claude=[rep()], model=ARGON, marche_id="M-MT-1", options={"temperature": 0.1})
    c1 = cout_attendu(ARGON, 100000, 32768)
    c2 = cout_attendu(ARGON, 100000, 9000)
    check("aucune exception", r.exc is None, repr(r.exc))
    check("MAX_TOKENS sans JSON : une relance (2 appels Gemini, même modèle)",
          [a["modele"] for a in r.gemini] == [ARGON, ARGON] and r.claude == [],
          str([(a["backend"], a["modele"]) for a in r.appels]))
    check("1er appel : reflexion None ; relance : reflexion non None",
          len(r.gemini) == 2 and r.gemini[0]["reflexion"] is None
          and r.gemini[1]["reflexion"] is not None, repr([a["reflexion"] for a in r.gemini]))
    check("options retransmises à la relance MAX_TOKENS",
          len(r.gemini) == 2 and r.gemini[1]["options"] == {"temperature": 0.1})
    check("résultat ok après relance MAX_TOKENS",
          champ(r.res, "ok") is True and champ(r.res, "json") == JSON_OK_DICT,
          repr(champ(r.res, "erreur")))
    check("les deux tentatives journalisées (erreur, ok)",
          statuts(r.entrees) == ["erreur", "ok"], str(statuts(r.entrees)))
    err = [e for e in r.entrees if e.get("statut") == "erreur"]
    bon = [e for e in r.entrees if e.get("statut") == "ok"]
    check("tentative tronquée : coût > 0 (facturée) et erreur renseignée",
          len(err) == 1 and proche(err[0].get("cout_eur"), c1) and bool(err[0].get("erreur"))
          and err[0].get("tokens_output") == 32768,
          f"{[(e.get('cout_eur'), e.get('erreur')) for e in err]} attendu {c1}")
    check("relance : coût de la 2e tentative", len(bon) == 1 and proche(bon[0].get("cout_eur"), c2),
          f"{[e.get('cout_eur') for e in bon]} attendu {c2}")
    check("res.cout_total_eur = somme des deux tentatives",
          proche(champ(r.res, "cout_total_eur"), c1 + c2), repr(champ(r.res, "cout_total_eur")))
    check("res.appels : deux tentatives", len(champ(r.res, "appels") or []) == 2,
          repr(champ(r.res, "appels")))

    # MAX_TOKENS avec un JSON complet exploitable : pas de relance
    r = lancer(gemini=[rep(JSON_OK, finish="MAX_TOKENS"), rep(JSON_OK)], model=ARGON,
               marche_id="M-MT-2")
    check("MAX_TOKENS avec JSON exploitable : pas de relance (1 appel, ok)",
          r.exc is None and len(r.gemini) == 1 and champ(r.res, "ok") is True
          and statuts(r.entrees) == ["ok"],
          f"{r.exc!r} gemini={len(r.gemini)} statuts={statuts(r.entrees)}")

    # modèle par défaut (non explicite) : la relance MAX_TOKENS suffit, pas de repli
    r = lancer(gemini=[rep("", tout=32768, finish="MAX_TOKENS"), rep(JSON_OK)], claude=[rep()],
               marche_id="M-MT-3")
    check("modèle par défaut : relance MAX_TOKENS réussie → pas de repli Claude",
          r.exc is None and len(r.gemini) == 2 and r.claude == [] and champ(r.res, "ok") is True
          and champ(r.res, "repli", "absent") is False and statuts(r.entrees) == ["erreur", "ok"],
          f"{r.exc!r} gemini={len(r.gemini)} claude={len(r.claude)} statuts={statuts(r.entrees)}")


# =============================================================================
def test_kill_switch():
    ecrire_budget(kill_switch_global=True)
    for nom, kw in (("analyse, modèle par défaut", {}),
                    ("analyse, alias gemini", {"model": "gemini"}),
                    ("analyse, Sonnet explicite", {"model": SONNET}),
                    ("analyse, argon explicite", {"model": ARGON}),
                    ("classif, Haiku explicite", {"task": "classif", "model": HAIKU,
                                                  "type_appel": "classification"}),
                    ("json_mode=False", {"json_mode": False})):
        r = lancer(gemini=[rep()], claude=[rep()], marche_id="M-KS", **kw)
        check(f"kill switch ({nom}) → BudgetDepasseError",
              isinstance(r.exc, budget.BudgetDepasseError), f"{r.exc!r} / {r.res!r}")
        check(f"kill switch ({nom}) : aucun appel fournisseur, aucune entrée",
              r.appels == [] and r.entrees == [],
              f"{len(r.appels)} appel(s), {len(r.entrees)} entrée(s)")
    ecrire_budget()
    r = lancer(gemini=[rep()], marche_id="M-KS-OFF")
    check("kill switch désactivé : l'appel repasse",
          r.exc is None and champ(r.res, "ok") is True and len(r.entrees) == 1, f"{r.exc!r}")

    # kill switch activé pendant la 1re tentative : la relance JSON est bloquée
    r = lancer(gemini=[rep(NON_JSON, apres=activer_kill_switch), rep(JSON_OK)], claude=[rep()],
               marche_id="M-KS-RJ")
    check("kill switch vérifié avant la relance JSON → BudgetDepasseError",
          isinstance(r.exc, budget.BudgetDepasseError), f"{r.exc!r} / {r.res!r}")
    check("relance JSON bloquée : un seul appel fournisseur", len(r.appels) == 1, str(len(r.appels)))
    check("relance JSON bloquée : la 1re tentative facturée reste journalisée (1 entrée erreur)",
          statuts(r.entrees) == ["erreur"] and proche(r.entrees[0].get("cout_eur"), COUT_ARGON),
          str(r.entrees))
    ecrire_budget()

    # kill switch activé pendant la 1re tentative : la relance MAX_TOKENS est bloquée
    r = lancer(gemini=[rep("", tout=32768, finish="MAX_TOKENS", apres=activer_kill_switch),
                       rep(JSON_OK)], claude=[rep()], model=ARGON, marche_id="M-KS-MT")
    check("kill switch vérifié avant la relance MAX_TOKENS → BudgetDepasseError",
          isinstance(r.exc, budget.BudgetDepasseError), f"{r.exc!r} / {r.res!r}")
    check("relance MAX_TOKENS bloquée : un seul appel, une seule entrée (erreur)",
          len(r.appels) == 1 and statuts(r.entrees) == ["erreur"],
          f"appels={len(r.appels)} statuts={statuts(r.entrees)}")
    ecrire_budget()

    # kill switch activé pendant la relance : le repli Sonnet est bloqué
    r = lancer(gemini=[rep(NON_JSON), rep(NON_JSON, apres=activer_kill_switch)], claude=[rep()],
               marche_id="M-KS-REPLI")
    check("kill switch vérifié avant le repli → BudgetDepasseError",
          isinstance(r.exc, budget.BudgetDepasseError), f"{r.exc!r} / {r.res!r}")
    check("repli bloqué : aucun appel Claude", r.claude == [] and len(r.gemini) == 2,
          f"gemini={len(r.gemini)} claude={len(r.claude)}")
    check("repli bloqué : seules les 2 tentatives Gemini sont journalisées, aucune entrée repli",
          statuts(r.entrees) == ["erreur", "erreur"], str(statuts(r.entrees)))
    ecrire_budget()

    # plafond mensuel franchi par la 1re tentative : la relance est bloquée
    cumul = somme_couts(journal_brut().values())
    ecrire_budget(plafond_global_eur_mois=cumul + 0.01)
    r = lancer(gemini=[rep(NON_JSON), rep(JSON_OK)], claude=[rep()], marche_id="M-KS-PLAFOND")
    check("plafond franchi par la 1re tentative : relance JSON bloquée (BudgetDepasseError)",
          isinstance(r.exc, budget.BudgetDepasseError) and len(r.appels) == 1
          and statuts(r.entrees) == ["erreur"],
          f"{r.exc!r} appels={len(r.appels)} statuts={statuts(r.entrees)}")
    ecrire_budget()


# =============================================================================
def test_repli():
    # A. exception du modèle par défaut (après ses retries) → un appel Sonnet
    r = lancer(gemini=[RuntimeError("panne simulée Gemini")],
               claude=[rep(JSON_OK, tin=100000, tout=10000, finish="end_turn")],
               marche_id="M-REPLI-A")
    res = r.res
    n_g = len(r.gemini)
    check("A. aucune exception levée par call_llm", r.exc is None, repr(r.exc))
    check("A. au moins une tentative Gemini, toutes sur gemini-4-argon",
          n_g >= 1 and all(a["modele"] == ARGON for a in r.gemini), str([a["modele"] for a in r.gemini]))
    check("A. UN appel de repli, sur claude-sonnet-4-6",
          len(r.claude) == 1 and r.claude[0]["modele"] == SONNET,
          str([a["modele"] for a in r.claude]))
    check("A. le repli vient après les tentatives Gemini",
          bool(r.appels) and r.appels[-1]["backend"] == "claude"
          and all(a["backend"] == "gemini" for a in r.appels[:-1]))
    check("A. le repli reçoit le prompt d'origine", len(r.claude) == 1 and PROMPT in r.claude[0]["prompt"])
    check("A. res.ok après repli", champ(res, "ok") is True, repr(champ(res, "erreur")))
    check("A. res.repli True", champ(res, "repli") is True, repr(champ(res, "repli")))
    check("A. res.modele = Sonnet (réellement utilisé)", champ(res, "modele") == SONNET,
          repr(champ(res, "modele")))
    check("A. res.modele_demande = argon (modèle initial)", champ(res, "modele_demande") == ARGON,
          repr(champ(res, "modele_demande")))
    check("A. res.fournisseur = claude", champ(res, "fournisseur") == "claude",
          repr(champ(res, "fournisseur")))
    check("A. res.json = réponse du repli", champ(res, "json") == JSON_OK_DICT)
    gem = [e for e in r.entrees if e.get("modele") == ARGON]
    son = [e for e in r.entrees if e.get("modele") == SONNET]
    check("A. une entrée par tentative fournisseur", len(r.entrees) == len(r.appels),
          f"{len(r.entrees)} entrée(s) pour {len(r.appels)} appel(s)")
    check("A. tentatives Gemini en exception : statut erreur, coût 0",
          len(gem) == n_g >= 1 and all(e.get("statut") == "erreur" and e.get("cout_eur") == 0
                                       for e in gem),
          str([(e.get("statut"), e.get("cout_eur")) for e in gem]))
    check("A. repli journalisé : statut « repli », modèle Sonnet",
          len(son) == 1 and son[0].get("statut") == "repli", str([e.get("statut") for e in son]))
    check("A. entrée repli : type, marche_id, tokens, coût Sonnet",
          len(son) == 1 and son[0].get("type") == "extraction"
          and son[0].get("marche_id") == "M-REPLI-A" and son[0].get("tokens_input") == 100000
          and son[0].get("tokens_output") == 10000 and proche(son[0].get("cout_eur"), COUT_SONNET),
          str(son))
    check("A. entrée repli réussie : champ erreur vide", len(son) == 1 and not son[0].get("erreur"),
          repr([e.get("erreur") for e in son]))
    check("A. res.cout_eur = coût du repli", proche(champ(res, "cout_eur"), COUT_SONNET),
          repr(champ(res, "cout_eur")))
    check("A. res.cout_total_eur = somme des tentatives (0 + Sonnet)",
          proche(champ(res, "cout_total_eur"), COUT_SONNET), repr(champ(res, "cout_total_eur")))
    appels = champ(res, "appels") or []
    check("A. res.appels : dernière tentative = repli sur Sonnet",
          bool(appels) and appels[-1].get("statut") == "repli" and appels[-1].get("modele") == SONNET
          and all(a.get("statut") == "erreur" and a.get("modele") == ARGON for a in appels[:-1])
          and len(appels) == len(r.appels), repr(appels))

    # B. JSON invalide après la relance → repli
    r = lancer(gemini=[rep(NON_JSON), rep(NON_JSON)], claude=[rep(JSON_OK, finish="end_turn")],
               marche_id="M-REPLI-B")
    res = r.res
    check("B. JSON invalide après relance : 2 appels argon puis 1 appel Sonnet",
          r.exc is None and [(a["backend"], a["modele"]) for a in r.appels]
          == [("gemini", ARGON), ("gemini", ARGON), ("claude", SONNET)],
          f"{r.exc!r} {[(a['backend'], a['modele']) for a in r.appels]}")
    check("B. res.ok, res.repli, res.modele Sonnet, res.modele_demande argon",
          champ(res, "ok") is True and champ(res, "repli") is True and champ(res, "modele") == SONNET
          and champ(res, "modele_demande") == ARGON,
          f"ok={champ(res, 'ok')!r} repli={champ(res, 'repli')!r} modele={champ(res, 'modele')!r}")
    check("B. 3 entrées : erreur, erreur, repli",
          statuts(r.entrees) == ["erreur", "erreur", "repli"], str(statuts(r.entrees)))
    check("B. les 2 erreurs Gemini sont facturées (coût > 0) avec erreur renseignée",
          all(proche(e.get("cout_eur"), COUT_ARGON) and e.get("erreur")
              for e in r.entrees if e.get("statut") == "erreur")
          and sum(1 for e in r.entrees if e.get("statut") == "erreur" and e.get("modele") == ARGON) == 2,
          str([(e.get("modele"), e.get("cout_eur")) for e in r.entrees]))
    check("B. somme du journal = 2 × argon + Sonnet",
          proche(somme_couts(r.entrees), 2 * COUT_ARGON + COUT_SONNET),
          f"{somme_couts(r.entrees)} attendu {2 * COUT_ARGON + COUT_SONNET}")
    check("B. res.cout_total_eur = relance et repli compris",
          proche(champ(res, "cout_total_eur"), 2 * COUT_ARGON + COUT_SONNET),
          repr(champ(res, "cout_total_eur")))
    check("B. res.cout_eur = dernière tentative (Sonnet)", proche(champ(res, "cout_eur"), COUT_SONNET),
          repr(champ(res, "cout_eur")))
    check("B. res.appels : erreur, erreur, repli",
          [a.get("statut") for a in (champ(res, "appels") or [])] == ["erreur", "erreur", "repli"],
          repr(champ(res, "appels")))

    # C. alias "gemini" : modèle non explicite → repli aussi
    r = lancer(gemini=[rep(NON_JSON), rep(NON_JSON)], claude=[rep(JSON_OK, finish="end_turn")],
               model="gemini", marche_id="M-REPLI-C")
    check("C. alias 'gemini' en échec → repli Sonnet",
          r.exc is None and len(r.claude) == 1 and r.claude[0]["modele"] == SONNET
          and champ(r.res, "repli") is True and champ(r.res, "ok") is True
          and statuts(r.entrees) == ["erreur", "erreur", "repli"],
          f"{r.exc!r} claude={len(r.claude)} statuts={statuts(r.entrees)}")

    # D. le repli échoue aussi (exception) : jamais d'exception fournisseur levée
    r = lancer(gemini=[rep(NON_JSON), rep(NON_JSON)], claude=[RuntimeError("panne simulée Claude")],
               marche_id="M-REPLI-D")
    res = r.res
    son = [e for e in r.entrees if e.get("modele") == SONNET]
    check("D. repli en exception : call_llm ne lève pas", r.exc is None, repr(r.exc))
    check("D. res.ok False, res.erreur renseigné",
          champ(res, "ok") is False and bool(champ(res, "erreur")),
          f"ok={champ(res, 'ok')!r} erreur={champ(res, 'erreur')!r}")
    check("D. Claude appelé sur Sonnet uniquement, après Gemini",
          len(r.claude) >= 1 and all(a["modele"] == SONNET for a in r.claude) and len(r.gemini) == 2)
    check("D. entrée(s) repli : statut « repli », erreur renseignée, coût 0",
          len(son) == len(r.claude) >= 1
          and all(e.get("statut") == "repli" and e.get("erreur") and e.get("cout_eur") == 0
                  for e in son), str(son))
    check("D. res.cout_total_eur = les 2 tentatives Gemini facturées",
          proche(champ(res, "cout_total_eur"), 2 * COUT_ARGON), repr(champ(res, "cout_total_eur")))

    # E. le repli répond sans JSON : un seul appel de repli, facturé, en échec
    r = lancer(gemini=[rep(NON_JSON), rep(NON_JSON)],
               claude=[rep(NON_JSON, finish="end_turn"), rep(JSON_OK, finish="end_turn")],
               marche_id="M-REPLI-E")
    res = r.res
    son = [e for e in r.entrees if e.get("modele") == SONNET]
    check("E. repli non JSON : UN seul appel Sonnet (pas de relance du repli)",
          r.exc is None and len(r.claude) == 1, f"{r.exc!r} claude={len(r.claude)}")
    check("E. res.ok False, res.erreur renseigné",
          champ(res, "ok") is False and bool(champ(res, "erreur")))
    check("E. entrée repli : statut « repli », erreur renseignée, coût > 0 (facturée)",
          len(son) == 1 and son[0].get("statut") == "repli" and bool(son[0].get("erreur"))
          and proche(son[0].get("cout_eur"), COUT_SONNET), str(son))
    check("E. res.cout_total_eur = 2 × argon + Sonnet",
          proche(champ(res, "cout_total_eur"), 2 * COUT_ARGON + COUT_SONNET),
          repr(champ(res, "cout_total_eur")))

    # F. pas de repli quand le modèle par défaut réussit après relance
    r = lancer(gemini=[rep(NON_JSON), rep(JSON_OK)], claude=[rep()], marche_id="M-REPLI-F")
    check("F. relance JSON réussie → aucun repli",
          r.exc is None and r.claude == [] and champ(r.res, "repli", "absent") is False
          and "repli" not in statuts(r.entrees), f"claude={len(r.claude)} {statuts(r.entrees)}")

    # G. pas de repli pour la tâche classif
    r = lancer(gemini=[RuntimeError("panne simulée Gemini")], claude=[rep()], task="classif",
               model="gemini", type_appel="classification", marche_id="M-REPLI-G")
    check("G. classif en échec (exception) : jamais de repli Claude",
          r.exc is None and r.claude == [] and champ(r.res, "ok") is False
          and bool(champ(r.res, "erreur")) and "repli" not in statuts(r.entrees)
          and len(r.entrees) == len(r.gemini) >= 1,
          f"{r.exc!r} claude={len(r.claude)} statuts={statuts(r.entrees)}")
    r = lancer(gemini=[rep(NON_JSON, tin=1000, tout=100)], claude=[rep()], task="classif",
               model="gemini", type_appel="classification", marche_id="M-REPLI-G2")
    check("G. classif non JSON : ni relance ni repli (1 appel, 1 entrée erreur)",
          r.exc is None and len(r.gemini) == 1 and r.claude == []
          and statuts(r.entrees) == ["erreur"] and champ(r.res, "repli", "absent") is False,
          f"gemini={len(r.gemini)} claude={len(r.claude)} statuts={statuts(r.entrees)}")


# =============================================================================
def test_modele_explicite():
    # Sonnet explicite sur la tâche analyse : jamais Gemini
    r = lancer(gemini=[rep()], claude=[rep(JSON_OK, finish="end_turn")], model=SONNET,
               marche_id="M-EXP-1")
    res = r.res
    check("Sonnet explicite : seul le backend Claude est appelé, sur claude-sonnet-4-6",
          r.exc is None and r.gemini == [] and [a["modele"] for a in r.claude] == [SONNET],
          f"{r.exc!r} {[(a['backend'], a['modele']) for a in r.appels]}")
    check("Sonnet explicite : res.modele, res.modele_demande, fournisseur claude",
          champ(res, "modele") == SONNET and champ(res, "modele_demande") == SONNET
          and champ(res, "fournisseur") == "claude" and champ(res, "ok") is True)
    check("Sonnet explicite : ce n'est pas un repli (res.repli False, statut ok)",
          champ(res, "repli", "absent") is False and statuts(r.entrees) == ["ok"],
          f"repli={champ(res, 'repli', 'absent')!r} statuts={statuts(r.entrees)}")
    check("Sonnet explicite : entrée au modèle et au tarif Sonnet",
          len(r.entrees) == 1 and r.entrees[0].get("modele") == SONNET
          and proche(r.entrees[0].get("cout_eur"), COUT_SONNET), str(r.entrees))

    # Sonnet explicite en échec (JSON invalide après relance) : ni Gemini ni repli
    r = lancer(gemini=[rep()], claude=[rep(NON_JSON, finish="end_turn"), rep(NON_JSON, finish="end_turn"),
                                       rep(JSON_OK, finish="end_turn")],
               model=SONNET, marche_id="M-EXP-2")
    check("Sonnet explicite, JSON invalide après relance : 2 appels Claude, aucun Gemini",
          r.exc is None and r.gemini == [] and [a["modele"] for a in r.claude] == [SONNET, SONNET],
          f"{r.exc!r} {[(a['backend'], a['modele']) for a in r.appels]}")
    check("Sonnet explicite en échec : res.ok False, pas de repli, statuts erreur/erreur",
          champ(r.res, "ok") is False and champ(r.res, "repli", "absent") is False
          and statuts(r.entrees) == ["erreur", "erreur"], str(statuts(r.entrees)))

    # Sonnet explicite en exception
    r = lancer(gemini=[rep()], claude=[RuntimeError("panne simulée Claude")], model=SONNET,
               marche_id="M-EXP-3")
    check("Sonnet explicite en exception : aucun Gemini, res.ok False, erreur renseignée",
          r.exc is None and r.gemini == [] and len(r.claude) >= 1 and champ(r.res, "ok") is False
          and bool(champ(r.res, "erreur")), f"{r.exc!r} gemini={len(r.gemini)}")
    check("Sonnet explicite en exception : entrées erreur à coût 0, aucune « repli »",
          len(r.entrees) == len(r.claude) >= 1
          and all(e.get("statut") == "erreur" and e.get("cout_eur") == 0 and e.get("modele") == SONNET
                  for e in r.entrees), str(r.entrees))

    # argon explicite en échec : jamais Claude
    r = lancer(gemini=[RuntimeError("panne simulée Gemini")], claude=[rep()], model=ARGON,
               marche_id="M-EXP-4")
    check("argon explicite en exception : jamais d'appel Claude",
          r.exc is None and r.claude == [] and len(r.gemini) >= 1
          and all(a["modele"] == ARGON for a in r.gemini),
          f"{r.exc!r} claude={len(r.claude)} gemini={len(r.gemini)}")
    check("argon explicite en exception : res.ok False, res.erreur renseigné, res.repli False",
          champ(r.res, "ok") is False and bool(champ(r.res, "erreur"))
          and champ(r.res, "repli", "absent") is False and champ(r.res, "modele") == ARGON)
    check("argon explicite en exception : une entrée erreur (coût 0) par tentative, aucune « repli »",
          len(r.entrees) == len(r.gemini) >= 1
          and all(e.get("statut") == "erreur" and e.get("cout_eur") == 0 and e.get("modele") == ARGON
                  for e in r.entrees), str(r.entrees))
    check("argon explicite en exception : coût total 0",
          proche(champ(r.res, "cout_total_eur"), 0.0, 1e-9), repr(champ(r.res, "cout_total_eur")))

    r = lancer(gemini=[rep(NON_JSON), rep(NON_JSON)], claude=[rep()], model=ARGON, marche_id="M-EXP-5")
    check("argon explicite, JSON invalide après relance : jamais d'appel Claude",
          r.exc is None and r.claude == [] and len(r.gemini) == 2 and champ(r.res, "ok") is False
          and statuts(r.entrees) == ["erreur", "erreur"],
          f"claude={len(r.claude)} gemini={len(r.gemini)} statuts={statuts(r.entrees)}")

    # Haiku explicite sur classif
    r = lancer(gemini=[rep()], claude=[rep(JSON_OK, tin=1000, tout=100, finish="end_turn")],
               task="classif", model=HAIKU, type_appel="classification", marche_id="M-EXP-6")
    check("Haiku explicite (classif) : c'est bien Haiku qui est appelé et journalisé",
          r.exc is None and r.gemini == [] and [a["modele"] for a in r.claude] == [HAIKU]
          and champ(r.res, "ok") is True and champ(r.res, "modele") == HAIKU
          and len(r.entrees) == 1 and r.entrees[0].get("modele") == HAIKU
          and proche(r.entrees[0].get("cout_eur"), cout_attendu(HAIKU, 1000, 100), 1e-5),
          f"{r.exc!r} {[(a['backend'], a['modele']) for a in r.appels]} {r.entrees}")


# =============================================================================
def test_json_mode_false():
    texte = "  Mémoire technique : notre méthode en trois phases.\n"
    r = lancer(gemini=[rep(texte), rep(JSON_OK)], claude=[rep()], json_mode=False,
               type_appel="memoire", marche_id="M-TXT-1")
    res = r.res
    check("json_mode=False transmis au backend", len(r.gemini) >= 1 and r.gemini[0]["json_mode"] is False)
    check("json_mode=False : un seul appel (pas de relance JSON, pas de repli)",
          r.exc is None and len(r.gemini) == 1 and r.claude == [],
          f"{r.exc!r} gemini={len(r.gemini)} claude={len(r.claude)}")
    check("res.texte rendu tel quel", champ(res, "texte") == texte, repr(champ(res, "texte")))
    check("res.json None", champ(res, "json", "absent") is None, repr(champ(res, "json", "absent")))
    check("res.ok True (le fournisseur a répondu)", champ(res, "ok") is True, repr(champ(res, "erreur")))
    check("une entrée ok, type memoire, coût > 0",
          len(r.entrees) == 1 and r.entrees[0].get("statut") == "ok"
          and r.entrees[0].get("type") == "memoire" and proche(r.entrees[0].get("cout_eur"), COUT_ARGON),
          str(r.entrees))

    r = lancer(gemini=[rep(JSON_OK)], json_mode=False, type_appel="digest", marche_id="M-TXT-2")
    check("json_mode=False avec un texte JSON : res.json reste None, texte intact",
          r.exc is None and champ(r.res, "json", "absent") is None and champ(r.res, "texte") == JSON_OK
          and champ(r.res, "ok") is True, f"{r.exc!r} json={champ(r.res, 'json', 'absent')!r}")

    r = lancer(claude=[rep("Texte libre.", finish="end_turn")], json_mode=False, relance_json=True,
               model=SONNET, type_appel="memoire", marche_id="M-TXT-3")
    check("json_mode=False : pas de relance JSON même avec relance_json=True",
          r.exc is None and len(r.claude) == 1 and champ(r.res, "ok") is True
          and statuts(r.entrees) == ["ok"], f"{r.exc!r} claude={len(r.claude)}")

    r = lancer(gemini=[RuntimeError("panne simulée")], model=ARGON, json_mode=False,
               type_appel="memoire", marche_id="M-TXT-4")
    check("json_mode=False, exception fournisseur : res.ok False, erreur renseignée, entrées erreur à 0 €",
          r.exc is None and champ(r.res, "ok") is False and bool(champ(r.res, "erreur"))
          and len(r.entrees) == len(r.gemini) >= 1
          and all(e.get("statut") == "erreur" and e.get("cout_eur") == 0 for e in r.entrees),
          f"{r.exc!r} {r.entrees}")


# =============================================================================
def test_limites():
    r = lancer(gemini=[rep()])
    check("marche_id par défaut (None) : appel journalisé avec marche_id None",
          r.exc is None and len(r.entrees) == 1 and r.entrees[0].get("marche_id") is None
          and r.entrees[0].get("statut") == "ok", f"{r.exc!r} {r.entrees}")

    r = lancer(gemini=[rep()], documents=[], marche_id="M-LIM-DOCS")
    check("documents=[] : appel nominal",
          r.exc is None and champ(r.res, "ok") is True and len(r.gemini) == 1
          and not r.gemini[0]["documents"] and len(r.entrees) == 1, f"{r.exc!r}")
    r = lancer(gemini=[rep()], documents=None, marche_id="M-LIM-DOCS0")
    check("documents=None : appel nominal, backend reçoit une liste vide ou None",
          r.exc is None and champ(r.res, "ok") is True and len(r.gemini) == 1
          and not r.gemini[0]["documents"], f"{r.exc!r}")

    r = lancer(gemini=[rep(JSON_OK, tin=0, tout=0)], marche_id="M-LIM-ZERO")
    check("zéro token : résultat ok, entrée ok à 0 €",
          r.exc is None and champ(r.res, "ok") is True and len(r.entrees) == 1
          and r.entrees[0].get("statut") == "ok" and r.entrees[0].get("cout_eur") == 0
          and r.entrees[0].get("tokens_input") == 0 and r.entrees[0].get("tokens_output") == 0,
          f"{r.exc!r} {r.entrees}")
    check("zéro token : res.cout_eur et res.cout_total_eur à 0",
          proche(champ(r.res, "cout_eur"), 0.0, 1e-9) and proche(champ(r.res, "cout_total_eur"), 0.0, 1e-9),
          f"{champ(r.res, 'cout_eur')!r} / {champ(r.res, 'cout_total_eur')!r}")

    grand = cout_attendu(ARGON, 10**9, 10**8)
    r = lancer(gemini=[rep(JSON_OK, tin=10**9, tout=10**8)], marche_id="M-LIM-GRAND")
    check("très grand volume (1 milliard de tokens) : coût exact journalisé",
          r.exc is None and champ(r.res, "ok") is True and len(r.entrees) == 1
          and proche(r.entrees[0].get("cout_eur"), grand, 1e-2)
          and r.entrees[0].get("tokens_input") == 10**9,
          f"{r.exc!r} {[e.get('cout_eur') for e in r.entrees]} attendu {grand}")
    check("très grand volume : res.cout_total_eur", proche(champ(r.res, "cout_total_eur"), grand, 1e-2),
          repr(champ(r.res, "cout_total_eur")))

    long_prompt = "Pièce du DCE. " * 100000          # 1,4 million de caractères
    r = lancer(gemini=[rep()], prompt=long_prompt, marche_id="M-LIM-LONG")
    check("prompt très long transmis sans troncature",
          r.exc is None and len(r.gemini) == 1 and r.gemini[0]["prompt"] == long_prompt
          and champ(r.res, "ok") is True, f"{r.exc!r}")

    r = lancer(gemini=[rep('{"vide": null}')], marche_id="M-LIM-JSONMIN")
    check("objet JSON minimal accepté sans relance",
          r.exc is None and len(r.gemini) == 1 and champ(r.res, "json") == {"vide": None}
          and champ(r.res, "ok") is True, f"{r.exc!r} {champ(r.res, 'json')!r}")


# =============================================================================
class _PanneMaison(Exception):
    pass


def test_jamais_d_exception_fournisseur():
    for exc_f in (RuntimeError("panne simulée"), ValueError("réponse illisible"),
                  ConnectionError("connexion coupée"), TimeoutError("délai dépassé"),
                  KeyError("candidates"), _PanneMaison("erreur 500 du fournisseur")):
        nom = type(exc_f).__name__
        r = lancer(gemini=[exc_f], claude=[rep()], model=ARGON, marche_id=f"M-EXC-{nom}")
        check(f"{nom} du fournisseur : call_llm ne lève pas", r.exc is None, repr(r.exc))
        check(f"{nom} : res.ok False et res.erreur renseigné",
              champ(r.res, "ok") is False and bool(champ(r.res, "erreur")),
              f"ok={champ(r.res, 'ok')!r} erreur={champ(r.res, 'erreur')!r}")
        check(f"{nom} : une entrée erreur à 0 € par tentative, erreur renseignée",
              len(r.entrees) == len(r.gemini) >= 1
              and all(e.get("statut") == "erreur" and e.get("cout_eur") == 0 and e.get("erreur")
                      and e.get("modele") == ARGON for e in r.entrees),
              f"{len(r.entrees)} entrée(s) pour {len(r.gemini)} appel(s) : {r.entrees}")

    # exception puis succès (retry) : chaque tentative journalisée
    r = lancer(gemini=[ConnectionError("connexion coupée"), rep(JSON_OK)], claude=[rep()], model=ARGON,
               marche_id="M-EXC-RETRY")
    check("exception puis réponse : autant d'entrées que de tentatives fournisseur",
          r.exc is None and len(r.entrees) == len(r.gemini) and r.claude == [],
          f"{r.exc!r} {len(r.entrees)} entrée(s) pour {len(r.gemini)} appel(s)")
    if len(r.gemini) == 2:
        check("exception retentée avec succès : entrées erreur (0 €) puis ok (coût > 0), résultat ok",
              champ(r.res, "ok") is True and statuts(r.entrees) == ["erreur", "ok"]
              and proche(somme_couts(r.entrees), COUT_ARGON), str(r.entrees))
    else:
        print("    (ConnectionError non retentée par le routeur : cas « erreur puis ok » non compté)")


# =============================================================================
def test_exp_appels_vide():
    exp = journal_brut("exp_appels")
    check("collection exp_appels vide après tous les appels", exp == {}, f"{len(exp)} entrée(s)")
    entrees = list(journal_brut().values())
    check("le journal llm_appels a bien été alimenté", len(entrees) > 20, str(len(entrees)))
    check("toutes les entrées ont un type valide",
          all(e.get("type") in budget.TYPES_VALIDES for e in entrees),
          str({e.get("type") for e in entrees}))
    check("tous les statuts sont ok / erreur / repli",
          {e.get("statut") for e in entrees} <= {"ok", "erreur", "repli"},
          str({e.get("statut") for e in entrees}))
    check("toutes les entrées « repli » sont sur claude-sonnet-4-6",
          all(e.get("modele") == SONNET for e in entrees if e.get("statut") == "repli"),
          str({e.get("modele") for e in entrees if e.get("statut") == "repli"}))
    check("toutes les entrées ont modele, cout_eur et duree_ms",
          all(e.get("modele") and e.get("cout_eur") is not None and e.get("duree_ms") is not None
              for e in entrees),
          str([e for e in entrees if not e.get("modele") or e.get("duree_ms") is None][:2]))
    check("base temporaire utilisée (pas data/tendia.db)",
          str(stockage.DATA_DIR) == str(dossier), str(stockage.DATA_DIR))


section("config_llm.yaml : taux unique et tarif argon daté", test_config_et_tarifs)
section("plafond mensuel global", test_plafond_mensuel)
section("type_appel obligatoire et validé", test_type_appel)
section("cas nominal : appel journalisé, options transmises", test_nominal)
section("relance JSON : deux entrées, deux coûts", test_relance_json)
section("relance MAX_TOKENS (Gemini)", test_relance_max_tokens)
section("kill switch avant chaque tentative", test_kill_switch)
section("repli analyse vers Sonnet 4.6", test_repli)
section("modèle explicite respecté", test_modele_explicite)
section("json_mode=False", test_json_mode_false)
section("cas limites", test_limites)
section("call_llm ne lève jamais d'exception du fournisseur", test_jamais_d_exception_fournisseur)
section("plus rien dans exp_appels", test_exp_appels_vide)

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
