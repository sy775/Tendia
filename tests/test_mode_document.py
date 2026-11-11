# -*- coding: utf-8 -*-
"""
tests/test_mode_document.py
---------------------------
Tests HORS-LIGNE (chantier 2, étape 4) de tendia.analyse.mode_document : lecture d'un
DCE pièce par pièce, fusion, contrôle de complétude, _sources vérifiées sans LLM,
_lecture et pct_non_lu, estimation de coût avant appel.

  - decouper : découpage aux marqueurs de page, concaténation exacte, page géante ;
  - normaliser_extrait / verifier_extrait : casse, espaces, ligatures, apostrophes ;
  - tableau_lecture : une ligne par pièce retenue et par fichier écarté, pct_non_lu exact ;
  - construire_sources : 6 champs critiques, ordre des sources (relance, modèle, analyses),
    extrait ≤ 200 caractères, extrait inventé ou page fausse → verifie False ;
  - estimer_cout : croît avec le volume, double au 2026-12-01 pour gemini-4-argon ;
  - lire_dce : un appel par pièce, une fusion, recherche ciblée des champs absents ;
    coût estimé au-delà du plafond → DCE sauté, AUCUN appel ; dry_run ; pièce en échec ;
    fusion en échec ; task="analyse", type_appel="extraction", marche_id, model None.

Faux llm_router.call_llm (posé AVANT l'import de mode_document), base temporaire,
P.DIR_PIECES temporaire, réseau coupé (socket) : aucun SDK, aucun appel payant.

Lancement : python tests/test_mode_document.py
"""
import contextlib
import copy
import hashlib
import inspect
import io
import json
import math
import os
import re
import socket
import sys
import tempfile
import threading
import types
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from base_temporaire import isoler_stockage
dossier = isoler_stockage()

VARIABLES_MODELES = ("GEMINI_MODEL_ANALYSE", "GEMINI_MODEL_CLASSIF",
                     "CLAUDE_MODEL_ANALYSE", "CLAUDE_MODEL_CLASSIF", "OPUS_MODEL")
for _v in VARIABLES_MODELES:
    os.environ.pop(_v, None)


def _reseau_interdit(*_a, **_k):
    raise OSError("réseau interdit dans tests/test_mode_document.py")


socket.socket.connect = _reseau_interdit
socket.create_connection = _reseau_interdit
socket.getaddrinfo = _reseau_interdit

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


def terminer():
    print()
    print("=" * 60)
    print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
    sys.exit(1 if ko else 0)


from tendia.core import budget, stockage
from tendia.core.chemins import DATA
from tendia.analyse import llm_router as R

# .env ne doit pas être relu ; fausses clés ; backends réels remplacés par un refus.
R.charger_env = lambda *a, **k: None
for _v in VARIABLES_MODELES:
    os.environ.pop(_v, None)
for _v in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
    os.environ[_v] = "cle-de-test-hors-ligne"


def _backend_interdit(*_a, **_k):
    raise AssertionError("appel fournisseur réel interdit dans tests/test_mode_document.py")


R._appel_gemini = _backend_interdit
R._appel_claude = _backend_interdit
R._respecter_rate_limit = lambda modele: None

_conf_budget = dict(budget.DEFAUT_BUDGET)
_conf_budget["kill_switch_global"] = False
_conf_budget["plafond_global_eur_mois"] = 1e12
budget.FICHIER_BUDGET.write_text(json.dumps(_conf_budget, ensure_ascii=False), encoding="utf-8")

ARGON = "gemini-4-argon"
SONNET = "claude-sonnet-4-6"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
MIXTE = FIXTURES / "dce_mixte"
NOMS_PIECES = ("RC.pdf", "CCAP.pdf", "CCTP.pdf", "BPU.xlsx")
CHAMPS = ("criteres_ponderations", "date_limite", "pieces_exigees", "visite", "montant", "lots")

# Extraits réellement présents dans les fixtures (cf. tests/fixtures/generer_dce_mixte.py)
EX_CRIT = "Les critères sont pondérés : prix des prestations 40 %, valeur technique 60 %."
EX_DATE = "Date limite de remise des offres : 15 décembre 2026 à 12 h 00."
EX_VISITE = "Une visite du site est obligatoire avant la remise de l'offre."
EX_LOTS = "Lot unique : couverture en tuiles de terre cuite, 420 m2."
EX_CCAP = "Pénalités de retard : 150 euros par jour calendaire."
EX_BPU = "Fourniture et pose de tuiles de terre cuite"
# Extraits inventés (absents de toute page)
EX_INVENTE = "Le candidat fournit obligatoirement les formulaires DC1 et DC2 signés."
EX_MONTANT_INVENTE = "Le montant estimé du marché est de 120 000 euros hors taxes."


def norm(s) -> str:
    return " ".join(str(s or "").lower().split())


def base(nom) -> str:
    return str(nom or "").replace("\\", "/").rsplit("/", 1)[-1]


# --- Faux call_llm -----------------------------------------------------------
VERROU = threading.Lock()
APPELS = []          # un dict par appel au faux call_llm
COUT_OK = 0.01       # cout_total_eur d'un appel réussi (cout_eur : 0,004, pour distinguer les deux)
COUT_KO = 0.002      # cout_total_eur d'un appel en échec (tentatives facturées)
SCEN = types.SimpleNamespace()


def scenario(sans=(), echec_pieces=(), echec_fusion=False, modele_fusion=ARGON,
             controle_trouve=True, ccap_sans_montant=False):
    """Programme le faux call_llm. sans : champs absents de la fusion ; echec_pieces :
    noms des pièces dont l'appel échoue ; controle_trouve : la recherche ciblée aboutit."""
    SCEN.sans = set(sans)
    SCEN.echec_pieces = set(echec_pieces)
    SCEN.echec_fusion = echec_fusion
    SCEN.modele_fusion = modele_fusion
    SCEN.controle_trouve = controle_trouve
    SCEN.ccap_sans_montant = ccap_sans_montant


scenario()


def genre(appel) -> str:
    pv = str(appel.get("prompt_version") or "")
    for g in ("piece", "fusion", "controle"):
        if pv.endswith(":" + g):
            return g
    return "inconnu"


def nom_piece(prompt) -> str:
    """Nom de la pièce d'un appel « PIÈCE : <nom> » (1re ligne du prompt)."""
    premiere = str(prompt or "").split("\n", 1)[0]
    for nom in NOMS_PIECES:
        if nom in premiere:
            return nom
    return premiere


def info(valeur, pages, extrait):
    return {"valeur": valeur, "pages": pages, "extrait": extrait}


def json_piece(nom) -> dict:
    if nom == "RC.pdf":
        infos = {
            "criteres_attribution": info({"prix": 40, "valeur_technique": 60}, [2], EX_CRIT),
            "date_limite_remise": info("2026-12-15 12:00", [2], EX_DATE),
            "visite": info("obligatoire", [2], EX_VISITE),
            "pieces_candidature": info(["DC1", "DC2"], [1], EX_INVENTE),
        }
        type_ = "RC"
    elif nom == "CCAP.pdf":
        infos = {} if SCEN.ccap_sans_montant else {"montant_estime": info(120000, [1], EX_MONTANT_INVENTE)}
        type_ = "CCAP"
    elif nom == "CCTP.pdf":
        infos = {"lots": info(["Lot unique : couverture"], [1], EX_LOTS)}
        type_ = "CCTP"
    else:
        infos = {}
        type_ = "BPU_DPGF_DQE"
    return {"type_confirme": type_, "informations": infos, "autres_informations_importantes": []}


def json_fusion() -> dict:
    """Brief au schéma de prod, avec les sources au format rendu par le modèle."""
    b = {
        "synthese_marche": "Réfection de la toiture de l'école Jean Moulin, marché de travaux en procédure adaptée.",
        "bareme_notation": {"valeur_technique_pct": 60, "valeur_prix_pct": 40},
        "calendrier": {"date_limite_offres": "2026-12-15 12:00"},
        "dossier_candidature": {"pieces_a_fournir": [
            {"libelle": "Lettre de candidature DC1", "phase": "candidature", "obligatoire": True, "source": None},
            {"libelle": "Déclaration du candidat DC2", "phase": "candidature", "obligatoire": True, "source": None}]},
        "complements_dce": {"visite": {"obligatoire": True, "modalites": "Visite du site avant la remise de l'offre."}},
        "montant_marche": {"valeur_estimee_euros": 120000},
        "lots": [{"numero": 1, "intitule": "Couverture en tuiles de terre cuite"}],
        "_sources": {
            "bareme_notation": [{"document": "RC.pdf", "page": 2}],
            "calendrier.date_limite_offres": [{"document": "RC.pdf", "page": 2}],
            "dossier_candidature.pieces_a_fournir": [{"document": "RC.pdf", "page": 1}],
            "complements_dce.visite": [{"document": "RC.pdf", "page": 2}],
            "montant_marche": [{"document": "CCAP.pdf", "page": 1}],
            "lots": [{"document": "CCTP.pdf", "page": 1}],
        },
    }
    if "date_limite" in SCEN.sans:
        b["calendrier"] = {}
        b["_sources"].pop("calendrier.date_limite_offres")
    if "montant" in SCEN.sans:
        b["montant_marche"] = {"valeur_estimee_euros": None}
        b["_sources"].pop("montant_marche")
    return b


def json_controle(appel) -> dict:
    """Recherche ciblée : trouvée seulement si l'appel porte sur le RC."""
    contenu = norm(appel["prompt"]) + " " + norm(repr(appel["documents"]))
    if SCEN.controle_trouve and ("rc.pdf" in contenu or "15 décembre 2026" in contenu):
        return {"trouve": True, "valeur": "2026-12-15 12:00", "pages": [2], "extrait": EX_DATE}
    return {"trouve": False, "valeur": None, "pages": [], "extrait": None}


def faux_call_llm(task=None, prompt=None, documents=None, model=None, **kw):
    appel = {"task": task, "prompt": prompt, "documents": documents, "model": model,
             "type_appel": kw.get("type_appel", "<absent>"), "marche_id": kw.get("marche_id", "<absent>"),
             "system": kw.get("system"), "max_tokens": kw.get("max_tokens"),
             "prompt_version": kw.get("prompt_version"), "kw": sorted(kw)}
    g = genre(appel)
    appel["genre"] = g
    echec, modele, js = False, ARGON, None
    if g == "piece":
        appel["piece"] = nom_piece(prompt)
        echec = appel["piece"] in SCEN.echec_pieces
        js = None if echec else json_piece(appel["piece"])
    elif g == "fusion":
        echec, modele = SCEN.echec_fusion, SCEN.modele_fusion
        js = None if echec else json_fusion()
    elif g == "controle":
        js = json_controle(appel)
    else:
        echec = True
    appel["cout_total_eur"] = COUT_KO if echec else COUT_OK
    with VERROU:
        APPELS.append(appel)
    fournisseur = "claude" if modele.startswith("claude") else "gemini"
    if echec:
        return R.LLMResult(ok=False, task="analyse", fournisseur=fournisseur, modele=modele, json=None,
                           erreur="X", tokens_in=1000, tokens_out=0, cout_eur=0.001,
                           cout_total_eur=COUT_KO, prompt_version=kw.get("prompt_version"))
    return R.LLMResult(ok=True, task="analyse", fournisseur=fournisseur, modele=modele,
                       texte=json.dumps(js, ensure_ascii=False), json=js, tokens_in=1000, tokens_out=200,
                       cout_eur=0.004, cout_total_eur=COUT_OK, prompt_version=kw.get("prompt_version"))


R.call_llm = faux_call_llm          # AVANT l'import de mode_document

try:
    from tendia.analyse import pieces as P
except Exception as e:  # noqa: BLE001
    check("import tendia.analyse.pieces", False, f"{type(e).__name__}: {e}")
    terminer()

DIR_PIECES_PROD = getattr(P, "DIR_PIECES", None)
TMP = Path(tempfile.mkdtemp(prefix="tendia_test_mode_document_"))
DIR_TEST = TMP / "pieces"
DIR_TEST.mkdir()
P.DIR_PIECES = DIR_TEST             # AVANT tout appel

try:
    from tendia.analyse import mode_document as MD
except Exception as e:  # noqa: BLE001
    check("import tendia.analyse.mode_document", False, f"{type(e).__name__}: {e}")
    terminer()


# --- Outils ------------------------------------------------------------------
def appeler(fonction, *args, **kwargs):
    """(résultat, exception) ; la sortie console de la fonction est absorbée."""
    tampon = io.StringIO()
    try:
        with contextlib.redirect_stdout(tampon), contextlib.redirect_stderr(tampon):
            return fonction(*args, **kwargs), None
    except Exception as e:  # noqa: BLE001
        return None, e


def proche(a, b, tol=1e-6):
    try:
        return a is not None and b is not None and abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def empreinte(racine: Path) -> dict:
    etat = {}
    for p in sorted(racine.rglob("*")):
        rel = p.relative_to(racine).as_posix()
        etat[rel] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "<dossier>"
    return etat


EMPREINTE_MIXTE = empreinte(MIXTE)
_INV = {}


def inventaire() -> dict:
    """Inventaire réel de dce_mixte (une fois), pour les fonctions qui relisent les pages."""
    if not _INV:
        inv, exc = appeler(P.inventorier, "TEST-MD-INVENTAIRE", str(MIXTE), verbose=False)
        if exc is not None or not isinstance(inv, dict):
            raise RuntimeError(f"inventaire de dce_mixte impossible : {exc!r}")
        _INV.update(inv)
    return _INV


def piece_inv(inv, nom):
    for p in inv.get("pieces") or []:
        if base(p.get("nom")) == nom:
            return p
    return None


def piece_synth(nom, type_="annexe", unite="page", nb_pages=1, chars=500):
    return {"nom": nom, "chemin_original": "", "chemin_lu": "", "type": type_, "unite": unite,
            "nb_pages": nb_pages, "chars": chars, "lecture_visuelle": False, "parties_pdf": [],
            "texte_fichier": ""}


def inv_synth(pieces=(), ecartes=(), doublons=()):
    pieces = list(pieces)
    return {"marche_id": "SYNTH", "pieces": pieces, "ecartes": list(ecartes), "doublons": list(doublons),
            "chars_total": sum(p["chars"] for p in pieces),
            "nb_pages_total": sum(p["nb_pages"] for p in pieces if p["unite"] == "page"), "erreurs": []}


def ecarte_synth(nom, statut, detail="motif de test"):
    return {"nom": nom, "statut": statut, "detail": detail}


def analyse(nom, type_="annexe", infos=None, nb_pages=1, oks=(True,)):
    """Analyse d'une pièce, une entrée « resultats » par partie (oks : réussite de chaque partie)."""
    resultats = []
    for i, reussi in enumerate(oks, 1):
        resultats.append({"partie": i, "ok": reussi, "erreur": None if reussi else "X",
                          "json": {"type_confirme": type_, "informations": dict(infos or {}),
                                   "autres_informations_importantes": []} if reussi else None})
    return {"piece": nom, "type": type_, "nb_pages": nb_pages, "resultats": resultats}


def inv_mixte_synth():
    return inv_synth(
        pieces=[piece_synth("RC.pdf", "RC", nb_pages=2, chars=1000), piece_synth("CCAP.pdf", "CCAP", chars=800),
                piece_synth("CCTP.pdf", "CCTP", chars=700),
                piece_synth("BPU.xlsx", "BPU_DPGF_DQE", unite="feuille", chars=300)],
        ecartes=[ecarte_synth("plan_masse.pdf", "plan_ignore"), ecarte_synth("photo_chantier.jpg", "plan_ignore"),
                 ecarte_synth("pieces_complementaires.rar", "format_non_gere"),
                 ecarte_synth("maquette.xyz", "format_non_gere")],
        doublons=[{"nom": "RC_copie.pdf", "doublon_de": "RC.pdf"},
                  {"nom": "RC_copie_zip.pdf", "doublon_de": "RC.pdf"}])


def analyses_ok(inv):
    return [analyse(p["nom"], p["type"], nb_pages=p["nb_pages"]) for p in inv["pieces"]]


def ligne(tab, nom):
    for l in (tab or {}).get("pieces") or []:
        if base(l.get("nom")) == nom:
            return l
    return None


# =============================================================================
def test_contrat():
    check("CHAMPS_SOURCES == les 6 champs critiques, dans l'ordre",
          getattr(MD, "CHAMPS_SOURCES", None) == CHAMPS, repr(getattr(MD, "CHAMPS_SOURCES", None)))
    check("P.DIR_PIECES (prod) == DATA / 'pieces'",
          DIR_PIECES_PROD is not None and Path(DIR_PIECES_PROD) == Path(DATA) / "pieces", repr(DIR_PIECES_PROD))
    check("mode_document passe par l'attribut llm_router.call_llm (faux en place)",
          R.call_llm is faux_call_llm)
    params = inspect.signature(MD.lire_dce).parameters
    check("lire_dce : max_cout_par_dce vaut 2,5 € par défaut",
          "max_cout_par_dce" in params and params["max_cout_par_dce"].default == 2.5,
          repr(params.get("max_cout_par_dce")))
    check("lire_dce : dry_run False par défaut",
          "dry_run" in params and params["dry_run"].default is False, repr(params.get("dry_run")))


# =============================================================================
def test_decouper():
    d = MD.decouper

    def page(i, n, car="x"):
        return f"\n[[Page {i}]]\n" + car * n

    court = page(1, 50) + page(2, 50)
    r, exc = appeler(d, court, 10_000)
    check("texte plus court que max_chars → un seul morceau, identique", exc is None and r == [court],
          f"{exc!r} {len(r or [])} morceau(x)")

    texte = "".join(page(i, 100) for i in range(1, 11))          # 10 pages de 112 ou 113 caractères
    r, exc = appeler(d, texte, 250)
    r = r or []
    check("10 pages, max 250 : rend une liste de chaînes",
          exc is None and isinstance(r, list) and all(isinstance(m, str) for m in r), repr(exc))
    check("concaténation des morceaux = texte exact", "".join(r) == texte)
    check("chaque morceau ≤ max_chars", bool(r) and all(len(m) <= 250 for m in r), str([len(m) for m in r]))
    check("plusieurs morceaux, pas plus que de pages (entre 5 et 10)", 5 <= len(r) <= 10, str(len(r)))
    check("chaque morceau après le premier commence par « \\n[[ »",
          len(r) > 1 and all(m.startswith("\n[[") for m in r[1:]), str([m[:12] for m in r]))
    check("aucune page coupée en deux (chaque morceau = des pages entières de 100 caractères)",
          bool(r) and all(m.count("[[Page ") > 0
                          and len(re.sub(r"\n\[\[Page \d+\]\]\n", "", m)) == 100 * m.count("[[Page ") for m in r),
          str([(m.count("[[Page "), len(m)) for m in r]))
    check("aucun morceau vide", bool(r) and all(m for m in r))

    r, exc = appeler(d, texte, len(texte) + 1)
    check("max_chars juste au-dessus de la longueur → un seul morceau", exc is None and r == [texte], repr(exc))

    intro = "Préambule sans marqueur. " + texte
    r, exc = appeler(d, intro, 250)
    r = r or []
    check("texte avant le premier marqueur : concaténation exacte, morceaux ≤ max",
          exc is None and "".join(r) == intro and all(len(m) <= 250 for m in r), repr(exc))
    check("texte avant le premier marqueur : morceaux suivants sur un marqueur",
          len(r) > 1 and all(m.startswith("\n[[") for m in r[1:]))

    geante = page(1, 1000)
    r, exc = appeler(d, geante, 100)
    r = r or []
    check("page plus longue que max_chars : coupée, morceaux ≤ max_chars",
          exc is None and len(r) >= 10 and all(0 < len(m) <= 100 for m in r), f"{exc!r} {[len(m) for m in r][:5]}")
    check("page géante : concaténation exacte (rien de perdu, rien de tronqué)", "".join(r) == geante)

    mixte = page(1, 50) + page(2, 50) + page(3, 700, "G") + page(4, 50) + page(5, 50)
    r, exc = appeler(d, mixte, 200)
    r = r or []
    check("pages normales + page géante : concaténation exacte, morceaux ≤ max_chars",
          exc is None and "".join(r) == mixte and bool(r) and all(len(m) <= 200 for m in r),
          f"{exc!r} {[len(m) for m in r]}")
    check("autour d'une page géante, les pages normales (1, 4, 5) ne sont pas coupées",
          page(1, 50) in "|".join(r) and page(4, 50) in "|".join(r) and page(5, 50) in "|".join(r),
          str([m[:14] for m in r]))

    sans_marqueur = "z" * 1000
    r, exc = appeler(d, sans_marqueur, 300)
    r = r or []
    check("texte sans marqueur plus long que max_chars : coupé, concaténation exacte",
          exc is None and "".join(r) == sans_marqueur and all(len(m) <= 300 for m in r), repr(exc))

    feuilles = "".join(f"\n[[Feuille F{i}]]\n" + "c" * 80 for i in range(6))
    r, exc = appeler(d, feuilles, 200)
    r = r or []
    check("marqueurs de feuille : découpe aux « \\n[[ », concaténation exacte",
          exc is None and "".join(r) == feuilles and len(r) > 1
          and all(len(m) <= 200 for m in r) and all(m.startswith("\n[[") for m in r[1:]), repr(exc))

    r, exc = appeler(d, "", 100)
    check("texte vide : aucune exception, concaténation vide", exc is None and "".join(r or []) == "",
          f"{r!r} {exc!r}")

    grand = "".join(page(i, 400) for i in range(1, 3001))        # 1,24 million de caractères
    r, exc = appeler(d, grand, 10_000)
    r = r or []
    check("très grand texte (3000 pages) : concaténation exacte, morceaux ≤ max, coupes aux marqueurs",
          exc is None and "".join(r) == grand and all(len(m) <= 10_000 for m in r)
          and all(m.startswith("\n[[") for m in r[1:]) and len(r) >= 124, f"{exc!r} {len(r)}")
    accents = "\n[[Page 1]]\nÉté œuvre ﬁn\n[[Page 2]]\nça"
    r, exc = appeler(d, accents, 20)
    check("accents et caractères non ASCII conservés", exc is None and "".join(r or []) == accents, repr(exc))


# =============================================================================
def test_extraits():
    n, v = MD.normaliser_extrait, MD.verifier_extrait

    def nz(s):
        r, exc = appeler(n, s)
        return (r or "").strip() if exc is None else f"<exception {exc!r}>"

    check("normaliser : minuscules", nz("Date LIMITE") == "date limite", repr(nz("Date LIMITE")))
    check("normaliser : suites d'espaces réduites à une espace", nz("date     limite") == "date limite",
          repr(nz("date     limite")))
    check("normaliser : retours à la ligne et tabulations réduits à une espace",
          nz("date\n\nlimite\r\n\tde   remise") == "date limite de remise",
          repr(nz("date\n\nlimite\r\n\tde   remise")))
    check("normaliser : ligature ﬁ décomposée", nz("justiﬁcatif") == "justificatif", repr(nz("justiﬁcatif")))
    check("normaliser : ligature ﬂ décomposée", nz("réﬂexion") == "réflexion", repr(nz("réﬂexion")))
    check("normaliser : œ décomposé", nz("main-d'œuvre") == "main-d'oeuvre", repr(nz("main-d'œuvre")))
    check("normaliser : Œ majuscule → oe", nz("Œuvre") == "oeuvre", repr(nz("Œuvre")))
    check("normaliser : apostrophe typographique ’ → '", nz("l’offre") == "l'offre", repr(nz("l’offre")))
    check("normaliser : accents conservés", nz("Décembre À Noël") == "décembre à noël", repr(nz("Décembre À Noël")))
    check("normaliser : chaîne vide → vide", nz("") == "", repr(nz("")))
    check("normaliser : espaces seuls → vide (après retrait des bords)", nz("  \n\t ") == "", repr(nz("  \n\t ")))
    r1 = appeler(n, "  L’Œuvre   ﬁnale\nﬂottante ")[0]
    check("normaliser : idempotente", r1 is not None and appeler(n, r1)[0] == r1, repr(r1))
    check("normaliser : rend une chaîne", isinstance(appeler(n, "abc")[0], str))

    page = ("Article 6 : remise des offres\nDate limite de remise des offres : 15 décembre 2026\n"
            "à 12 h 00.   Une visite du site est obligatoire avant la remise de l’offre.\n"
            "Le justiﬁcatif de visite et le coût de la main-d’œuvre sont joints. Réﬂexion faite.")

    def vz(extrait, texte=page):
        r, exc = appeler(v, extrait, texte)
        return r if exc is None else f"<exception {exc!r}>"

    check("verifier : extrait exact présent → True", vz("Article 6 : remise des offres") is True)
    check("verifier : casse différente → True", vz("DATE LIMITE DE REMISE DES OFFRES") is True)
    check("verifier : extrait à cheval sur un retour à la ligne → True",
          vz("15 décembre 2026 à 12 h 00.") is True, repr(vz("15 décembre 2026 à 12 h 00.")))
    check("verifier : espaces multiples dans l'extrait → True", vz("Date   limite  de\nremise") is True)
    check("verifier : espaces multiples dans la page → True", vz("12 h 00. Une visite du site") is True)
    check("verifier : ligature dans la page, pas dans l'extrait (ﬁ) → True", vz("justificatif de visite") is True)
    check("verifier : ligature dans l'extrait, pas dans la page (ﬁ) → True",
          vz("justiﬁcatif", "Le justificatif est joint.") is True)
    check("verifier : ﬂ → True", vz("Réflexion faite") is True)
    check("verifier : œ dans la page, oe dans l'extrait → True", vz("main-d'oeuvre") is True)
    check("verifier : apostrophe droite dans l'extrait, typographique dans la page → True",
          vz("la remise de l'offre") is True)
    check("verifier : apostrophe typographique dans l'extrait, droite dans la page → True",
          vz("l’offre", "Remise de l'offre avant midi.") is True)
    check("verifier : rend un booléen", isinstance(vz("Article 6"), bool) and isinstance(vz("absent du texte"), bool))
    check("verifier : extrait inventé → False", vz("Date limite de remise des offres : 20 janvier 2027") is False)
    check("verifier : mêmes mots dans un autre ordre → False", vz("offres des remise de limite Date") is False)
    check("verifier : extrait plus long que ce que contient la page → False",
          vz("Article 6 : remise des offres et des candidatures") is False)
    check("verifier : extrait vide → False", vz("") is False, repr(vz("")))
    check("verifier : extrait None → False", vz(None) is False, repr(vz(None)))
    check("verifier : extrait d'espaces seuls → False", vz("  \n ") is False, repr(vz("  \n ")))
    check("verifier : texte de page vide → False", vz("Article 6", "") is False, repr(vz("Article 6", "")))
    check("verifier : extrait vide et texte vide → False", vz("", "") is False)
    long_texte = "a b " * 300_000 + "La clause finale est ici."
    check("verifier : très grande page (1,2 million de caractères), extrait en fin → True",
          vz("la clause   finale est ici", long_texte) is True)
    check("verifier : très grande page, extrait absent → False", vz("clause initiale", long_texte) is False)

    inv = inventaire()
    rc = piece_inv(inv, "RC.pdf")
    check("verifier sur la fixture : date limite du RC trouvée en page 2",
          vz(EX_DATE, P.texte_page(rc, 2)) is True, repr(P.texte_page(rc, 2)[:120]))
    check("verifier sur la fixture : même extrait cherché en page 1 → False", vz(EX_DATE, P.texte_page(rc, 1)) is False)
    check("verifier sur la fixture : critères trouvés en page 2", vz(EX_CRIT, P.texte_page(rc, 2)) is True)


# =============================================================================
def test_tableau_lecture():
    t = MD.tableau_lecture
    inv = inv_mixte_synth()
    copie_inv = copy.deepcopy(inv)
    tab, exc = appeler(t, inv, analyses_ok(inv))
    check("tableau_lecture : aucune exception, un dict", exc is None and isinstance(tab, dict), repr(exc))
    tab = tab if isinstance(tab, dict) else {}
    check("clés : pieces, nb_pieces_texte, nb_lues, pct_non_lu",
          {"pieces", "nb_pieces_texte", "nb_lues", "pct_non_lu"} <= set(tab), str(sorted(tab)))
    lignes = tab.get("pieces") or []
    check("une ligne par pièce retenue et par fichier écarté : 8 lignes", len(lignes) == 8, str(len(lignes)))
    check("chaque ligne : nom, type, statut, pages, caracteres, detail",
          bool(lignes) and all({"nom", "type", "statut", "pages", "caracteres", "detail"} <= set(l) for l in lignes),
          str([sorted(l) for l in lignes[:1]]))
    check("les doublons n'ont pas de ligne",
          ligne(tab, "RC_copie.pdf") is None and ligne(tab, "RC_copie_zip.pdf") is None)
    check("une seule ligne par nom", len({base(l.get("nom")) for l in lignes}) == len(lignes))
    for nom in NOMS_PIECES:
        check(f"{nom} : statut lu", (ligne(tab, nom) or {}).get("statut") == "lu", repr(ligne(tab, nom)))
    rc = ligne(tab, "RC.pdf") or {}
    check("RC.pdf : type RC, 2 pages, 1000 caractères",
          rc.get("type") == "RC" and rc.get("pages") == 2 and rc.get("caracteres") == 1000, repr(rc))
    for nom, statut in (("plan_masse.pdf", "plan_ignore"), ("photo_chantier.jpg", "plan_ignore"),
                        ("pieces_complementaires.rar", "format_non_gere"), ("maquette.xyz", "format_non_gere")):
        check(f"{nom} : statut de l'inventaire ({statut})", (ligne(tab, nom) or {}).get("statut") == statut,
              repr(ligne(tab, nom)))
    check("nb_pieces_texte == 6 (tout sauf plan_ignore)", tab.get("nb_pieces_texte") == 6,
          repr(tab.get("nb_pieces_texte")))
    check("nb_lues == 4", tab.get("nb_lues") == 4, repr(tab.get("nb_lues")))
    check("pct_non_lu == 33.3 (2 non lues sur 6, arrondi à 1 décimale)", tab.get("pct_non_lu") == 33.3,
          repr(tab.get("pct_non_lu")))
    check("pct_non_lu est un float", isinstance(tab.get("pct_non_lu"), float), type(tab.get("pct_non_lu")).__name__)
    check("l'inventaire n'est pas modifié", inv == copie_inv)

    def pct(inv_, analyses_):
        r, exc_ = appeler(t, inv_, analyses_)
        return (r or {}).get("pct_non_lu") if exc_ is None else f"<exception {exc_!r}>"

    # une pièce dont une partie échoue
    analyses = analyses_ok(inv)
    analyses[2] = analyse("CCTP.pdf", "CCTP", oks=(True, False, True))
    tab, exc = appeler(t, inv, analyses)
    tab = tab or {}
    check("une partie en échec sur trois → pièce echec_lecture",
          exc is None and (ligne(tab, "CCTP.pdf") or {}).get("statut") == "echec_lecture", repr(ligne(tab, "CCTP.pdf")))
    check("les autres pièces restent lues",
          all((ligne(tab, n) or {}).get("statut") == "lu" for n in ("RC.pdf", "CCAP.pdf", "BPU.xlsx")))
    check("pièce en échec : nb_lues 3, pct_non_lu 50.0",
          tab.get("nb_lues") == 3 and tab.get("nb_pieces_texte") == 6 and tab.get("pct_non_lu") == 50.0,
          f"{tab.get('nb_lues')!r} / {tab.get('pct_non_lu')!r}")

    # pièce absente des analyses
    tab, exc = appeler(t, inv, analyses_ok(inv)[:3])
    tab = tab or {}
    check("pièce absente des analyses → echec_lecture",
          exc is None and (ligne(tab, "BPU.xlsx") or {}).get("statut") == "echec_lecture", repr(ligne(tab, "BPU.xlsx")))
    check("pièce absente des analyses : pct_non_lu 50.0", tab.get("pct_non_lu") == 50.0, repr(tab.get("pct_non_lu")))

    tab, exc = appeler(t, inv, [])
    tab = tab or {}
    check("analyses vides : 4 pièces echec_lecture, nb_lues 0, pct_non_lu 100.0",
          exc is None and all((ligne(tab, n) or {}).get("statut") == "echec_lecture" for n in NOMS_PIECES)
          and tab.get("nb_lues") == 0 and tab.get("pct_non_lu") == 100.0, f"{exc!r} {tab.get('pct_non_lu')!r}")
    check("analyses vides : toujours 8 lignes", len(tab.get("pieces") or []) == 8)

    # aucune pièce de texte
    vide = inv_synth()
    tab, exc = appeler(t, vide, [])
    check("inventaire vide : pct_non_lu 0.0, aucune ligne, aucune division par zéro",
          exc is None and (tab or {}).get("pct_non_lu") == 0.0 and (tab or {}).get("pieces") == []
          and (tab or {}).get("nb_pieces_texte") == 0 and (tab or {}).get("nb_lues") == 0, f"{exc!r} {tab!r}")
    plans = inv_synth(ecartes=[ecarte_synth("plan1.pdf", "plan_ignore"), ecarte_synth("plan2.dwg", "plan_ignore")])
    tab, exc = appeler(t, plans, [])
    check("que des plans ignorés : aucune pièce de texte, pct_non_lu 0.0, 2 lignes",
          exc is None and (tab or {}).get("pct_non_lu") == 0.0 and (tab or {}).get("nb_pieces_texte") == 0
          and len((tab or {}).get("pieces") or []) == 2, f"{exc!r} {tab!r}")

    # échec de conversion = pièce de texte non lue
    conv = inv_synth(pieces=[piece_synth("RC.pdf", "RC")], ecartes=[ecarte_synth("AE.doc", "echec_conversion")])
    tab, exc = appeler(t, conv, analyses_ok(conv))
    tab = tab or {}
    check("echec_conversion compte comme pièce de texte non lue : 1 lue sur 2 → 50.0",
          exc is None and tab.get("pct_non_lu") == 50.0 and tab.get("nb_pieces_texte") == 2
          and (ligne(tab, "AE.doc") or {}).get("statut") == "echec_conversion", f"{exc!r} {tab.get('pct_non_lu')!r}")
    tout_lu = inv_synth(pieces=[piece_synth("RC.pdf", "RC")], ecartes=[ecarte_synth("plan.pdf", "plan_ignore")])
    check("tout lu, un plan ignoré : pct_non_lu 0.0 (le plan ne compte pas)",
          pct(tout_lu, analyses_ok(tout_lu)) == 0.0, repr(pct(tout_lu, analyses_ok(tout_lu))))

    # arrondi à 1 décimale
    for total, lues, attendu in ((3, 2, 33.3), (3, 1, 66.7), (7, 6, 14.3), (6, 5, 16.7), (8, 7, 12.5), (9, 1, 88.9)):
        inv_n = inv_synth(pieces=[piece_synth(f"P{i}.pdf") for i in range(total)])
        an = analyses_ok(inv_n)[:lues]
        check(f"arrondi : {total - lues} non lue(s) sur {total} → {attendu}", pct(inv_n, an) == attendu,
              repr(pct(inv_n, an)))

    gros = inv_synth(pieces=[piece_synth(f"P{i:04d}.pdf") for i in range(1000)])
    an = analyses_ok(gros)
    an[0] = analyse("P0000.pdf", oks=(False,))
    an[1] = analyse("P0001.pdf", oks=(False,))
    tab, exc = appeler(t, gros, an)
    check("très grand inventaire (1000 pièces, 2 en échec) : 1000 lignes, 998 lues, pct_non_lu 0.2",
          exc is None and len((tab or {}).get("pieces") or []) == 1000 and (tab or {}).get("nb_lues") == 998
          and (tab or {}).get("pct_non_lu") == 0.2, f"{exc!r} {(tab or {}).get('pct_non_lu')!r}")

    # sur l'inventaire réel de la fixture
    reel = inventaire()
    an = [analyse(p["nom"], p["type"], nb_pages=p["nb_pages"]) for p in reel["pieces"]]
    tab, exc = appeler(t, reel, an)
    tab = tab or {}
    check("dce_mixte réel, 4 pièces lues : 6 pièces de texte, 4 lues, pct_non_lu 33.3",
          exc is None and tab.get("nb_pieces_texte") == 6 and tab.get("nb_lues") == 4
          and tab.get("pct_non_lu") == 33.3 and len(tab.get("pieces") or []) == 8,
          f"{exc!r} {tab.get('nb_pieces_texte')!r} {tab.get('nb_lues')!r} {tab.get('pct_non_lu')!r}")
    rc = ligne(tab, "RC.pdf") or {}
    rc_inv = piece_inv(reel, "RC.pdf") or {}
    check("dce_mixte réel : pages et caractères du RC repris de l'inventaire",
          rc.get("pages") == rc_inv.get("nb_pages") == 2 and rc.get("caracteres") == rc_inv.get("chars"), repr(rc))


# =============================================================================
def test_construire_sources():
    c = MD.construire_sources
    inv = inventaire()
    n_appels = len(APPELS)

    a_rc = analyse("RC.pdf", "RC", nb_pages=2, infos={
        "criteres_attribution": info({"prix": 40, "technique": 60}, [2], EX_CRIT),
        "date_limite_remise": info("2026-12-15 12:00", [2], EX_DATE),
        "visite": info("obligatoire", [2], EX_VISITE),
        "pieces_candidature": info(["DC1", "DC2"], [1], EX_INVENTE)})
    a_ccap = analyse("CCAP.pdf", "CCAP", infos={"montant_estime": info(120000, [1], EX_CCAP)})
    a_cctp = analyse("CCTP.pdf", "CCTP", infos={"lots": info(["Lot unique"], [1], EX_LOTS)})
    a_bpu = analyse("BPU.xlsx", "BPU_DPGF_DQE", infos={})
    analyses = [a_rc, a_ccap, a_cctp, a_bpu]
    sources_modele = {
        "bareme_notation": [{"document": "RC.pdf", "page": 2}],
        "calendrier.date_limite_offres": [{"document": "RC.pdf", "page": 2}],
        "dossier_candidature.pieces_a_fournir": [{"document": "RC.pdf", "page": 1}],
        "complements_dce.visite": [{"document": "RC.pdf", "page": 2}],
        "montant_marche": [{"document": "CCAP.pdf", "page": 1}],
        "lots": [{"document": "CCTP.pdf", "page": 1}],
    }

    def src(brief, analyses_, inv_=inv):
        r, exc = appeler(c, brief, analyses_, inv_)
        if exc is not None:
            return {"<exception>": repr(exc)}
        return r if isinstance(r, dict) else {"<type>": type(r).__name__}

    def conforme(s, piece, page, verifie, extrait=None):
        return (isinstance(s, dict) and s.get("piece") == piece and str(s.get("page")) == str(page)
                and s.get("verifie") is verifie and (extrait is None or s.get("extrait") == extrait))

    # --- (2) sources rendues par le modèle ---
    brief = {"_sources_modele": copy.deepcopy(sources_modele)}
    copie_brief, copie_an = copy.deepcopy(brief), copy.deepcopy(analyses)
    s = src(brief, analyses)
    check("une clé par champ de CHAMPS_SOURCES, et seulement celles-là", set(s) == set(CHAMPS), str(sorted(s)))
    check("chaque source : piece, page, extrait, verifie (booléen)",
          all(isinstance(s.get(k), dict) and {"piece", "page", "extrait", "verifie"} <= set(s[k])
              and isinstance(s[k]["verifie"], bool) for k in CHAMPS), repr(s))
    check("criteres_ponderations ← bareme_notation / criteres_attribution : RC.pdf p. 2, vérifié",
          conforme(s.get("criteres_ponderations"), "RC.pdf", 2, True, EX_CRIT), repr(s.get("criteres_ponderations")))
    check("date_limite ← calendrier.date_limite_offres / date_limite_remise : RC.pdf p. 2, vérifié",
          conforme(s.get("date_limite"), "RC.pdf", 2, True, EX_DATE), repr(s.get("date_limite")))
    check("visite ← complements_dce.visite / visite : RC.pdf p. 2, vérifié",
          conforme(s.get("visite"), "RC.pdf", 2, True, EX_VISITE), repr(s.get("visite")))
    check("lots ← lots / lots : CCTP.pdf p. 1, vérifié",
          conforme(s.get("lots"), "CCTP.pdf", 1, True, EX_LOTS), repr(s.get("lots")))
    check("montant ← montant_marche / montant_estime : CCAP.pdf p. 1, extrait cherché dans la page",
          conforme(s.get("montant"), "CCAP.pdf", 1, True, EX_CCAP), repr(s.get("montant")))
    check("pieces_exigees ← dossier_candidature.pieces_a_fournir / pieces_candidature : extrait inventé → verifie False",
          conforme(s.get("pieces_exigees"), "RC.pdf", 1, False, EX_INVENTE), repr(s.get("pieces_exigees")))
    check("brief et analyses non modifiés", brief == copie_brief and analyses == copie_an)
    check("aucun appel LLM pour construire les sources", len(APPELS) == n_appels)

    # variantes de questions : pieces_offre, montant, lot
    variantes = [
        analyse("RC.pdf", "RC", nb_pages=2, infos={"pieces_offre": info(["mémoire"], [2], EX_VISITE)}),
        analyse("CCAP.pdf", "CCAP", infos={"montant": info(1, [1], EX_CCAP)}),
        analyse("CCTP.pdf", "CCTP", infos={"lot": info("unique", [1], EX_LOTS)})]
    sm = copy.deepcopy(sources_modele)
    sm["dossier_candidature.pieces_a_fournir"] = [{"document": "RC.pdf", "page": 2}]
    s = src({"_sources_modele": sm}, variantes)
    check("question pieces_offre acceptée pour pieces_exigees",
          conforme(s.get("pieces_exigees"), "RC.pdf", 2, True, EX_VISITE), repr(s.get("pieces_exigees")))
    check("question montant acceptée pour montant", conforme(s.get("montant"), "CCAP.pdf", 1, True, EX_CCAP),
          repr(s.get("montant")))
    check("question lot acceptée pour lots", conforme(s.get("lots"), "CCTP.pdf", 1, True, EX_LOTS), repr(s.get("lots")))

    # page citée fausse
    sm = copy.deepcopy(sources_modele)
    sm["bareme_notation"] = [{"document": "RC.pdf", "page": 1}]
    sm["calendrier.date_limite_offres"] = [{"document": "RC.pdf", "page": 7}]
    s = src({"_sources_modele": sm}, analyses)
    # Attente ajustée après l'écriture du code (décision notée au rapport du chantier 2) :
    # quand la fusion cite une page et que l'analyse de la pièce en relève une autre, la
    # source rendue porte la page de l'analyse, celle où l'extrait est effectivement
    # cherché. La citation affichée est donc soit juste et vérifiée, soit non vérifiée.
    check("fusion p. 1, analyse p. 2 : la source cite la page de l'analyse, vérifiée",
          conforme(s.get("criteres_ponderations"), "RC.pdf", 2, True), repr(s.get("criteres_ponderations")))
    check("fusion p. 7 (inexistante), analyse p. 2 : idem, sans exception",
          conforme(s.get("date_limite"), "RC.pdf", 2, True), repr(s.get("date_limite", s)))
    # l'analyse de la pièce cite elle-même une mauvaise page : rien ne la rattrape
    a_rc_page_fausse = analyse("RC.pdf", "RC", nb_pages=2, infos={
        "criteres_attribution": info("40/60", [1], EX_CRIT), "date_limite_remise": info("2026-12-15", [7], EX_DATE)})
    s_faux = src({"_sources_modele": sm}, [a_rc_page_fausse])
    # Attente ajustée à l'étape 7 (constat sur les DCE réels : le modèle se trompe souvent d'une
    # page) : un extrait absent de la page citée mais présent ailleurs dans la MÊME pièce voit
    # sa page corrigée ; la page citée par le modèle est gardée dans "page_citee".
    check("analyse p. 1 au lieu de p. 2 → page corrigée en 2, vérifiée, page citée conservée",
          conforme(s_faux.get("criteres_ponderations"), "RC.pdf", 2, True)
          and s_faux["criteres_ponderations"].get("page_citee") == 1, repr(s_faux.get("criteres_ponderations")))
    check("analyse p. 7 (inexistante) → page corrigée en 2, sans exception",
          conforme(s_faux.get("date_limite"), "RC.pdf", 2, True)
          and s_faux["date_limite"].get("page_citee") == 7, repr(s_faux.get("date_limite")))
    a_rc_invente = analyse("RC.pdf", "RC", nb_pages=2, infos={
        "criteres_attribution": info("40/60", [1], "Les critères sont pondérés : prix 55 %, valeur technique 45 %.")})
    s_inv = src({"_sources_modele": sm}, [a_rc_invente])
    check("extrait absent de toute la pièce → verifie False, page citée affichée, pas de page_citee",
          conforme(s_inv.get("criteres_ponderations"), "RC.pdf", 1, False)
          and "page_citee" not in s_inv["criteres_ponderations"], repr(s_inv.get("criteres_ponderations")))
    check("les autres champs restent vérifiés", conforme(s.get("visite"), "RC.pdf", 2, True), repr(s.get("visite")))

    # mauvaise pièce citée : l'extrait du RC cherché dans le CCAP
    sm = copy.deepcopy(sources_modele)
    sm["complements_dce.visite"] = [{"document": "CCAP.pdf", "page": 1}]
    faux_ccap = analyse("CCAP.pdf", "CCAP", infos={"visite": info("obligatoire", [1], EX_VISITE)})
    s = src({"_sources_modele": sm}, [a_rc, faux_ccap, a_cctp])
    check("extrait absent de la pièce citée (CCAP au lieu du RC) → verifie False",
          conforme(s.get("visite"), "CCAP.pdf", 1, False), repr(s.get("visite")))

    # page en chaîne
    sm = copy.deepcopy(sources_modele)
    sm["bareme_notation"] = [{"document": "RC.pdf", "page": "2"}]
    s = src({"_sources_modele": sm}, analyses)
    check("page en chaîne \"2\" → vérifié", conforme(s.get("criteres_ponderations"), "RC.pdf", 2, True),
          repr(s.get("criteres_ponderations")))

    # feuille de tableur
    sm = {"lots": [{"document": "BPU.xlsx", "page": "BPU"}]}
    a_bpu_lots = analyse("BPU.xlsx", "BPU_DPGF_DQE", infos={"lots": info(["couverture"], ["BPU"], EX_BPU)})
    s = src({"_sources_modele": sm}, [a_bpu_lots])
    check("source sur une feuille de tableur : page = nom de feuille, vérifié",
          conforme(s.get("lots"), "BPU.xlsx", "BPU", True, EX_BPU), repr(s.get("lots")))
    check("champs sans aucune source → None",
          all(s.get(k) is None for k in CHAMPS if k != "lots") and set(s) == set(CHAMPS), repr(s))

    # document inconnu de l'inventaire
    sm = {"bareme_notation": [{"document": "Inconnu.pdf", "page": 2}]}
    s = src({"_sources_modele": sm}, [a_rc])
    check("document cité absent de l'inventaire : pas d'exception, jamais verifie True",
          "<exception>" not in s and (s.get("criteres_ponderations") is None
                                      or not (s["criteres_ponderations"].get("piece") == "Inconnu.pdf"
                                              and s["criteres_ponderations"].get("verifie") is True)), repr(s))

    # --- extrait de plus de 200 caractères ---
    rc = piece_inv(inv, "RC.pdf")
    long_ = " ".join(P.texte_page(rc, 2).split())[:300]          # texte réel de la page, espaces simples
    check("(préparation) la page 2 du RC fait plus de 250 caractères", len(long_) > 250, str(len(long_)))
    sm_visite = {"complements_dce.visite": [{"document": "RC.pdf", "page": 2}]}
    a_long = analyse("RC.pdf", "RC", nb_pages=2, infos={"visite": info("oui", [2], long_)})
    s = src({"_sources_modele": sm_visite}, [a_long])
    e = (s.get("visite") or {}).get("extrait") or ""
    check("extrait de 300 caractères : coupé à 200 au plus", 0 < len(e) <= 200, str(len(e)))
    check("extrait coupé = les 200 premiers caractères", e.rstrip() == long_[:200].rstrip(), repr(e[-40:]))
    check("extrait coupé : toujours vérifié dans la page", (s.get("visite") or {}).get("verifie") is True,
          repr(s.get("visite")))
    a_200 = analyse("RC.pdf", "RC", nb_pages=2, infos={"visite": info("oui", [2], long_[:200])})
    s = src({"_sources_modele": sm_visite}, [a_200])
    e = (s.get("visite") or {}).get("extrait") or ""
    check("extrait de 200 caractères exactement : conservé entier, vérifié",
          e.rstrip() == long_[:200].rstrip() and len(e) <= 200 and (s.get("visite") or {}).get("verifie") is True,
          str(len(e)))
    a_invente_long = analyse("RC.pdf", "RC", nb_pages=2, infos={"visite": info("oui", [2], "Phrase inventée. " * 40)})
    s = src({"_sources_modele": sm_visite}, [a_invente_long])
    check("extrait inventé de 680 caractères : coupé à 200 au plus, verifie False",
          0 < len((s.get("visite") or {}).get("extrait") or "") <= 200
          and (s.get("visite") or {}).get("verifie") is False, repr(s.get("visite")))

    # --- (3) à défaut : première analyse qui renseigne la question avec une valeur non nulle ---
    a_ccap_nul = analyse("CCAP.pdf", "CCAP", infos={"date_limite_remise": info(None, [1], EX_CCAP)})
    s = src({}, [a_ccap_nul, a_rc, a_cctp])
    check("sans _sources_modele : la première analyse à valeur non nulle fait la source (CCAP à valeur nulle ignoré)",
          conforme(s.get("date_limite"), "RC.pdf", 2, True, EX_DATE), repr(s.get("date_limite")))
    check("sans _sources_modele : page prise dans « pages » de l'analyse (lots : CCTP p. 1)",
          conforme(s.get("lots"), "CCTP.pdf", 1, True, EX_LOTS), repr(s.get("lots")))
    check("sans _sources_modele : champ que personne ne renseigne → None", s.get("montant") is None, repr(s.get("montant")))
    a_ccap_date = analyse("CCAP.pdf", "CCAP", infos={"date_limite_remise": info("2026-12-01", [1], EX_CCAP)})
    s = src({}, [a_ccap_date, a_rc])
    check("sans _sources_modele : c'est la PREMIÈRE analyse renseignée qui est retenue",
          conforme(s.get("date_limite"), "CCAP.pdf", 1, True, EX_CCAP), repr(s.get("date_limite")))
    s = src({"_sources_modele": {"bareme_notation": []}}, [a_rc])
    check("_sources_modele vide pour un champ → repli sur les analyses",
          conforme(s.get("criteres_ponderations"), "RC.pdf", 2, True, EX_CRIT), repr(s.get("criteres_ponderations")))
    s = src({"_sources_modele": None}, [a_rc])
    check("_sources_modele None : pas d'exception, repli sur les analyses",
          conforme(s.get("visite"), "RC.pdf", 2, True, EX_VISITE), repr(s))

    # --- aucune source ---
    s = src({}, [])
    check("brief vide, aucune analyse : les 6 clés, toutes None",
          set(s) == set(CHAMPS) and all(s[k] is None for k in CHAMPS), repr(s))
    s = src({}, [], inv_synth())
    check("inventaire vide : les 6 clés, toutes None", set(s) == set(CHAMPS) and all(s[k] is None for k in CHAMPS),
          repr(s))
    s = src({}, [analyse("RC.pdf", "RC", nb_pages=2, oks=(False,))])
    check("analyse en échec (json None) : pas d'exception, toutes None",
          set(s) == set(CHAMPS) and all(s[k] is None for k in CHAMPS), repr(s))

    # --- (1) recherche ciblée du contrôle de complétude : prioritaire ---
    sm = copy.deepcopy(sources_modele)
    sm["calendrier.date_limite_offres"] = [{"document": "CCAP.pdf", "page": 1}]
    brief = {"_sources_modele": sm,
             "_controle_completude": {
                 "date_limite": {"statut": "trouve_par_relance", "piece": "RC.pdf", "pages": [2], "extrait": EX_DATE},
                 "visite": {"statut": "present", "piece": "CCAP.pdf", "pages": [1], "extrait": EX_CCAP}}}
    s = src(brief, analyses)
    check("trouve_par_relance : la recherche ciblée prime sur _sources_modele (RC.pdf p. 2, vérifié)",
          conforme(s.get("date_limite"), "RC.pdf", 2, True, EX_DATE), repr(s.get("date_limite")))
    check("statut « present » : l'entrée du contrôle n'est pas une source (on garde _sources_modele)",
          conforme(s.get("visite"), "RC.pdf", 2, True, EX_VISITE), repr(s.get("visite")))
    brief = {"_controle_completude": {
        "montant": {"statut": "trouve_par_relance", "piece": "CCAP.pdf", "pages": [1], "extrait": EX_MONTANT_INVENTE}}}
    s = src(brief, [])
    check("trouve_par_relance avec un extrait inventé → verifie False",
          conforme(s.get("montant"), "CCAP.pdf", 1, False, EX_MONTANT_INVENTE), repr(s.get("montant")))
    brief = {"_controle_completude": {
        "date_limite": {"statut": "trouve_par_relance", "piece": "RC.pdf", "pages": [1], "extrait": EX_DATE}}}
    s = src(brief, [])
    check("trouve_par_relance avec une page fausse → page corrigée dans la même pièce (étape 7)",
          conforme(s.get("date_limite"), "RC.pdf", 2, True) and s["date_limite"].get("page_citee") == 1,
          repr(s.get("date_limite")))
    check("fixtures intactes après construire_sources", empreinte(MIXTE) == EMPREINTE_MIXTE)


# =============================================================================
def test_estimer_cout():
    e = MD.estimer_cout
    n_appels = len(APPELS)
    reel = inventaire()

    def cout(inv_, **kw):
        r, exc = appeler(e, inv_, **kw)
        return (r or {}).get("cout_eur") if exc is None else None

    r, exc = appeler(e, reel)
    check("estimer_cout(inventaire réel) : aucune exception, un dict", exc is None and isinstance(r, dict), repr(exc))
    r = r if isinstance(r, dict) else {}
    check("clés : modele, tokens_entree, tokens_sortie, cout_eur",
          {"modele", "tokens_entree", "tokens_sortie", "cout_eur"} <= set(r), str(sorted(r)))
    check("modèle par défaut (modele=None) : gemini-4-argon", r.get("modele") == ARGON, repr(r.get("modele")))
    check("tokens_entree ≥ chars_total / 2,5",
          isinstance(r.get("tokens_entree"), (int, float)) and r["tokens_entree"] >= reel["chars_total"] / 2.5,
          f"{r.get('tokens_entree')!r} pour {reel.get('chars_total')!r} caractères")
    check("tokens_sortie ≥ 0", isinstance(r.get("tokens_sortie"), (int, float)) and r["tokens_sortie"] >= 0,
          repr(r.get("tokens_sortie")))
    check("cout_eur > 0 pour un DCE non vide", isinstance(r.get("cout_eur"), (int, float)) and r["cout_eur"] > 0,
          repr(r.get("cout_eur")))
    check("un petit DCE de test coûte moins que le plafond par défaut (2,5 €)", (r.get("cout_eur") or 99) < 2.5,
          repr(r.get("cout_eur")))
    r2, exc = appeler(e, reel, None, None)
    check("arguments positionnels (inv, None, None) : même résultat", exc is None and r2 == r, f"{exc!r}")

    # dates : tarif argon doublé à partir du 2026-12-01
    for nom, inv_ in (("inventaire réel", reel),
                      ("10 pièces de 1 million de caractères",
                       inv_synth(pieces=[piece_synth(f"P{i}.pdf", nb_pages=400, chars=1_000_000) for i in range(10)]))):
        avant, apres = cout(inv_, date="2026-11-30"), cout(inv_, date="2026-12-01")
        check(f"{nom} : coût au 2026-12-01 = 2 × coût au 2026-11-30 (gemini-4-argon)",
              avant is not None and apres is not None and avant > 0
              and math.isclose(apres, 2 * avant, rel_tol=1e-3, abs_tol=3e-6), f"{avant!r} → {apres!r}")
        ra, _ = appeler(e, inv_, date="2026-11-30")
        rb, _ = appeler(e, inv_, date="2026-12-01")
        check(f"{nom} : mêmes tokens aux deux dates (seul le tarif change)",
              isinstance(ra, dict) and isinstance(rb, dict) and ra.get("tokens_entree") == rb.get("tokens_entree")
              and ra.get("tokens_sortie") == rb.get("tokens_sortie"))
        plancher = R.estimer_cout_eur(ARGON, math.ceil(inv_["chars_total"] / 2.5), 0, date="2026-11-30")
        check(f"{nom} : coût ≥ caractères / chars_par_token × tarif d'entrée",
              avant is not None and avant >= plancher * 0.999 - 1e-6, f"{avant!r} < {plancher!r}")
    v1, v2 = cout(reel, date="2026-11-01"), cout(reel, date="2026-11-30")
    check("deux dates avant le 2026-12-01 : même coût", v1 is not None and v1 == v2, f"{v1!r} / {v2!r}")
    v1, v2 = cout(reel, date="2026-12-01"), cout(reel, date="2027-03-15")
    check("deux dates à partir du 2026-12-01 : même coût", v1 is not None and v1 == v2, f"{v1!r} / {v2!r}")

    # croissance avec le volume
    tailles = (0, 1_000, 100_000, 10_000_000, 10**9)
    couts, tokens = [], []
    for n in tailles:
        inv_ = inv_synth(pieces=[piece_synth("P.pdf", nb_pages=max(1, n // 3000), chars=n)] if n else [])
        rr, exc = appeler(e, inv_, date="2026-11-30")
        couts.append((rr or {}).get("cout_eur") if exc is None else None)
        tokens.append((rr or {}).get("tokens_entree") if exc is None else None)
    check("volume nul (aucune pièce) : aucune exception, coût ≥ 0, tokens_entree ≥ 0",
          couts[0] is not None and couts[0] >= 0 and tokens[0] is not None and tokens[0] >= 0,
          f"{couts[0]!r} / {tokens[0]!r}")
    check("cout_eur croît strictement avec chars_total (1 000 → 100 000 → 10 millions → 1 milliard)",
          all(c is not None for c in couts) and all(a < b for a, b in zip(couts[1:], couts[2:]))
          and couts[0] <= couts[1], str(couts))
    check("tokens_entree ≥ chars_total / 2,5 à chaque taille",
          all(t is not None and t >= n / 2.5 for t, n in zip(tokens, tailles)), str(tokens))
    check("très grand volume (1 milliard de caractères) : coût fini, au moins 736 € d'entrée",
          couts[-1] is not None and math.isfinite(couts[-1]) and couts[-1] >= 735.9, repr(couts[-1]))
    check("un très gros DCE (10 millions de caractères) dépasse le plafond par défaut de 2,5 €",
          couts[3] is not None and couts[3] > 2.5, repr(couts[3]))

    # modèle explicite
    gros = inv_synth(pieces=[piece_synth("P.pdf", nb_pages=300, chars=1_000_000)])
    rs, exc = appeler(e, gros, SONNET, "2026-11-30")
    rs = rs or {}
    check("modèle explicite repris dans le résultat", exc is None and rs.get("modele") == SONNET,
          f"{exc!r} {rs.get('modele')!r}")
    check("claude : tokens_entree ≥ chars_total / 2,1 (chars_par_token de config_llm.yaml)",
          (rs.get("tokens_entree") or 0) >= 1_000_000 / 2.1, repr(rs.get("tokens_entree")))
    apres_sonnet = cout(gros, modele=SONNET, date="2026-12-01")
    check("claude-sonnet-4-6 : pas de palier de date, même coût avant et après le 2026-12-01",
          rs.get("cout_eur") is not None and rs.get("cout_eur") == apres_sonnet,
          f"{rs.get('cout_eur')!r} / {apres_sonnet!r}")
    ra, _ = appeler(e, gros, ARGON, "2026-11-30")
    rn, _ = appeler(e, gros, None, "2026-11-30")
    check("modele=None équivaut à gemini-4-argon explicite", ra is not None and ra == rn, f"{ra!r} / {rn!r}")
    check("estimer_cout : AUCUN appel LLM", len(APPELS) == n_appels, str(len(APPELS) - n_appels))


# =============================================================================
def lancer(mid, **kw):
    """Remet le journal du faux à zéro, appelle lire_dce sur dce_mixte, rend res / exc / appels."""
    with VERROU:
        APPELS.clear()
    contexte = {"id": mid, "titre": "Réfection de la toiture de l'école Jean Moulin"}
    kw.setdefault("verbose", False)
    res, exc = appeler(MD.lire_dce, mid, str(MIXTE), contexte, ["btp"], **kw)
    with VERROU:
        appels = list(APPELS)
    return types.SimpleNamespace(
        res=res if isinstance(res, dict) else {}, brut=res, exc=exc, appels=appels, mid=mid,
        pieces=[a for a in appels if a["genre"] == "piece"],
        fusions=[a for a in appels if a["genre"] == "fusion"],
        controles=[a for a in appels if a["genre"] == "controle"],
        inconnus=[a for a in appels if a["genre"] == "inconnu"],
        total=sum(a["cout_total_eur"] for a in appels))


CLES_RESULTAT = {"ok", "brief", "raison", "estimation", "lecture", "cout_eur", "modele"}


def verifier_appels(r, prefixe):
    """Règles communes à tous les appels LLM d'une lecture."""
    check(f"{prefixe} : tous les appels ont task == 'analyse'",
          bool(r.appels) and all(a["task"] == "analyse" for a in r.appels), str({a["task"] for a in r.appels}))
    check(f"{prefixe} : tous les appels ont type_appel == 'extraction'",
          bool(r.appels) and all(a["type_appel"] == "extraction" for a in r.appels),
          str({a["type_appel"] for a in r.appels}))
    check(f"{prefixe} : tous les appels portent le marche_id passé",
          bool(r.appels) and all(a["marche_id"] == r.mid for a in r.appels), str({a["marche_id"] for a in r.appels}))
    check(f"{prefixe} : model None partout (modèle par défaut du routeur, repli possible)",
          bool(r.appels) and all(a["model"] is None for a in r.appels), str({a["model"] for a in r.appels}))
    check(f"{prefixe} : prompt_version terminé par :piece, :fusion ou :controle",
          bool(r.appels) and r.inconnus == [], str({a["prompt_version"] for a in r.inconnus}))


def test_lire_dce_nominal():
    scenario()
    r = lancer("TEST-MD-NOMINAL")
    res = r.res
    check("aucune exception", r.exc is None, repr(r.exc))
    check("résultat : dict avec ok, brief, raison, estimation, lecture, cout_eur, modele",
          isinstance(r.brut, dict) and CLES_RESULTAT <= set(res), f"manquantes : {sorted(CLES_RESULTAT - set(res))}")
    check("ok True", res.get("ok") is True, f"raison={res.get('raison')!r}")
    check("raison vide quand ok", not res.get("raison"), repr(res.get("raison")))
    verifier_appels(r, "nominal")

    # --- appels ---
    check("un appel par pièce retenue : 4 appels « :piece »", len(r.pieces) == 4, str([a.get("piece") for a in r.pieces]))
    check("les 4 pièces retenues, une fois chacune (ni doublon, ni plan, ni .rar)",
          sorted(a.get("piece") for a in r.pieces) == sorted(NOMS_PIECES), str([a.get("piece") for a in r.pieces]))
    check("chaque prompt de pièce commence par « PIÈCE : <nom> »",
          bool(r.pieces) and all(a["piece"] in NOMS_PIECES and str(a["prompt"]).startswith("PIÈCE : " + a["piece"])
                                 for a in r.pieces), str([str(a["prompt"])[:40] for a in r.pieces]))
    check("un seul appel de fusion", len(r.fusions) == 1, str(len(r.fusions)))
    genres = [a["genre"] for a in r.appels]
    check("la fusion vient après tous les appels de pièce",
          "fusion" in genres and all(g == "piece" for g in genres[:genres.index("fusion")])
          and "piece" not in genres[genres.index("fusion"):], str(genres))
    check("tous les champs présents dès la fusion : AUCUNE recherche ciblée", r.controles == [],
          str([str(a["prompt"])[:60] for a in r.controles]))
    rc = next((a for a in r.pieces if a.get("piece") == "RC.pdf"), None) or {}
    contenu_rc = norm(rc.get("prompt")) + " " + norm(rc.get("system"))
    check("appel du RC : questions du type RC posées (criteres_attribution, date_limite_remise)",
          "criteres_attribution" in contenu_rc and "date_limite_remise" in contenu_rc, contenu_rc[:200])
    check("appel du RC : le contenu de la pièce est transmis (texte dans le prompt, ou documents)",
          "15 décembre 2026" in norm(rc.get("prompt")) or bool(rc.get("documents")), str(rc.get("prompt"))[:120])
    if "[[Page 1]]" in str(rc.get("prompt")):
        texte_rc = P.texte_piece(piece_inv(inventaire(), "RC.pdf"))
        check("appel du RC : texte complet de la pièce dans le prompt (jamais tronqué)",
              norm(texte_rc) in norm(rc.get("prompt")))
    fusion = (r.fusions or [{}])[0]
    check("la fusion reçoit ce que les pièces ont rendu (date du RC présente dans son prompt)",
          "15 décembre 2026" in norm(fusion.get("prompt")) or "2026-12-15" in norm(fusion.get("prompt")),
          str(fusion.get("prompt"))[:200])

    # --- brief ---
    brief = res.get("brief") if isinstance(res.get("brief"), dict) else {}
    check("brief : un dict", isinstance(res.get("brief"), dict), type(res.get("brief")).__name__)
    check("brief au schéma de prod : barème repris de la fusion",
          (brief.get("bareme_notation") or {}).get("valeur_technique_pct") == 60
          and (brief.get("bareme_notation") or {}).get("valeur_prix_pct") == 40, repr(brief.get("bareme_notation")))
    check("brief : date limite reprise de la fusion",
          "2026-12-15" in str((brief.get("calendrier") or {}).get("date_limite_offres")), repr(brief.get("calendrier")))
    check("brief : synthese_marche reprise", bool(brief.get("synthese_marche")), repr(brief.get("synthese_marche")))
    check("brief : _sources, _lecture et _controle_completude présents",
          all(k in brief for k in ("_sources", "_lecture", "_controle_completude")),
          str([k for k in brief if k.startswith("_")]))

    sources = brief.get("_sources") if isinstance(brief.get("_sources"), dict) else {}
    check("_sources : exactement les 6 champs critiques", set(sources) == set(CHAMPS), str(sorted(sources)))

    def conforme(champ, piece, page, verifie):
        s = sources.get(champ)
        return (isinstance(s, dict) and s.get("piece") == piece and str(s.get("page")) == str(page)
                and s.get("verifie") is verifie and isinstance(s.get("extrait"), str) and len(s["extrait"]) <= 200)

    check("_sources.criteres_ponderations : RC.pdf p. 2, extrait vérifié dans la page",
          conforme("criteres_ponderations", "RC.pdf", 2, True), repr(sources.get("criteres_ponderations")))
    check("_sources.date_limite : RC.pdf p. 2, vérifié", conforme("date_limite", "RC.pdf", 2, True),
          repr(sources.get("date_limite")))
    check("_sources.visite : RC.pdf p. 2, vérifié", conforme("visite", "RC.pdf", 2, True), repr(sources.get("visite")))
    check("_sources.lots : CCTP.pdf p. 1, vérifié", conforme("lots", "CCTP.pdf", 1, True), repr(sources.get("lots")))
    check("_sources.pieces_exigees : extrait inventé par le modèle → verifie False",
          conforme("pieces_exigees", "RC.pdf", 1, False), repr(sources.get("pieces_exigees")))
    # chantier 2b : le montant publié vient des seules notes RC / AE ; une note du CCAP ne le source pas
    check("_sources.montant : note du CCAP seule → pas de montant publié, pas de source",
          sources.get("montant") is None and (brief.get("montant_publie") or {}).get("statut") == "non_communique",
          repr(sources.get("montant")))
    check("_sources.date_limite : l'extrait est celui de l'analyse du RC",
          (sources.get("date_limite") or {}).get("extrait") == EX_DATE, repr(sources.get("date_limite")))

    controle = brief.get("_controle_completude") if isinstance(brief.get("_controle_completude"), dict) else {}
    check("_controle_completude : les 6 champs, tous « present »",
          all((controle.get(k) or {}).get("statut") == "present" for k in CHAMPS),
          str({k: (controle.get(k) or {}).get("statut") for k in CHAMPS}))

    lecture = brief.get("_lecture") if isinstance(brief.get("_lecture"), dict) else {}
    check("_lecture : une ligne par pièce (4 retenues + 4 écartées, doublons sans ligne)",
          len(lecture.get("pieces") or []) == 8 and ligne(lecture, "RC_copie.pdf") is None
          and ligne(lecture, "RC_copie_zip.pdf") is None, str([l.get("nom") for l in lecture.get("pieces") or []]))
    check("_lecture : chaque ligne a nom, type, statut, pages, caracteres",
          bool(lecture.get("pieces")) and all({"nom", "type", "statut", "pages", "caracteres"} <= set(l)
                                              for l in lecture["pieces"]))
    check("_lecture : les 4 pièces retenues sont « lu »",
          all((ligne(lecture, n) or {}).get("statut") == "lu" for n in NOMS_PIECES),
          str({n: (ligne(lecture, n) or {}).get("statut") for n in NOMS_PIECES}))
    check("_lecture : plan_masse.pdf et photo_chantier.jpg plan_ignore ; .rar et .xyz format_non_gere",
          (ligne(lecture, "plan_masse.pdf") or {}).get("statut") == "plan_ignore"
          and (ligne(lecture, "photo_chantier.jpg") or {}).get("statut") == "plan_ignore"
          and (ligne(lecture, "pieces_complementaires.rar") or {}).get("statut") == "format_non_gere"
          and (ligne(lecture, "maquette.xyz") or {}).get("statut") == "format_non_gere")
    check("_lecture : RC.pdf, type RC, 2 pages, caractères > 0",
          (ligne(lecture, "RC.pdf") or {}).get("type") == "RC" and (ligne(lecture, "RC.pdf") or {}).get("pages") == 2
          and ((ligne(lecture, "RC.pdf") or {}).get("caracteres") or 0) > 0, repr(ligne(lecture, "RC.pdf")))
    check("_lecture : 6 pièces de texte, 4 lues", lecture.get("nb_pieces_texte") == 6 and lecture.get("nb_lues") == 4,
          f"{lecture.get('nb_pieces_texte')!r} / {lecture.get('nb_lues')!r}")
    check("_lecture : pct_non_lu exact = 33.3", lecture.get("pct_non_lu") == 33.3, repr(lecture.get("pct_non_lu")))
    check("résultat « lecture » = brief['_lecture']", bool(lecture) and res.get("lecture") == lecture)

    # --- coût, modèle, estimation ---
    check("cout_eur = somme des cout_total_eur de tous les appels (5 × 0,01 €), pas des cout_eur",
          len(r.appels) == 5 and proche(res.get("cout_eur"), r.total), f"{res.get('cout_eur')!r} attendu {r.total}")
    check("modele = modèle de l'appel de fusion", res.get("modele") == ARGON, repr(res.get("modele")))
    est = res.get("estimation") if isinstance(res.get("estimation"), dict) else {}
    check("estimation : modele, tokens_entree, tokens_sortie, cout_eur (> 0)",
          {"modele", "tokens_entree", "tokens_sortie", "cout_eur"} <= set(est) and (est.get("cout_eur") or 0) > 0,
          repr(est))
    check("estimation sous le plafond par défaut de 2,5 €", (est.get("cout_eur") or 99) <= 2.5, repr(est.get("cout_eur")))

    # --- isolation ---
    check("inventaire écrit sous P.DIR_PIECES / <id>", (DIR_TEST / r.mid / "_inventaire.json").is_file())
    check("rien d'écrit dans DATA / 'pieces' / <id> (prod)", not (Path(DATA) / "pieces" / r.mid).exists())
    check("dossier source intact (data/dce en lecture seule)", empreinte(MIXTE) == EMPREINTE_MIXTE,
          str(sorted(set(empreinte(MIXTE)) ^ set(EMPREINTE_MIXTE))))
    check("base temporaire utilisée (pas data/tendia.db)", str(stockage.DATA_DIR) == str(dossier), str(stockage.DATA_DIR))


# =============================================================================
def test_lire_dce_controle():
    """Fusion sans date limite : recherche ciblée, champ rempli, source RC.pdf p. 2 vérifiée."""
    scenario(sans=("date_limite",), modele_fusion=SONNET)
    r = lancer("TEST-MD-CONTROLE")
    res = r.res
    brief = res.get("brief") if isinstance(res.get("brief"), dict) else {}
    check("aucune exception, ok True", r.exc is None and res.get("ok") is True, f"{r.exc!r} raison={res.get('raison')!r}")
    verifier_appels(r, "contrôle")
    check("4 appels de pièce, 1 fusion", len(r.pieces) == 4 and len(r.fusions) == 1,
          f"{len(r.pieces)} / {len(r.fusions)}")
    check("champ absent de la fusion : au moins une recherche ciblée", len(r.controles) >= 1, str(len(r.controles)))
    check("chaque prompt de recherche ciblée commence par « RECHERCHE CIBLÉE »",
          bool(r.controles) and all(str(a["prompt"]).startswith("RECHERCHE CIBLÉE") for a in r.controles),
          str([str(a["prompt"])[:40] for a in r.controles]))
    genres = [a["genre"] for a in r.appels]
    check("les recherches ciblées viennent après la fusion",
          "fusion" in genres and "controle" not in genres[:genres.index("fusion")], str(genres))
    check("recherche limitée au champ manquant (pas plus d'appels que de pièces)", len(r.controles) <= 4,
          str(len(r.controles)))
    check("le champ est rempli dans le brief (calendrier.date_limite_offres)",
          "2026-12-15" in str((brief.get("calendrier") or {}).get("date_limite_offres")), repr(brief.get("calendrier")))
    controle = brief.get("_controle_completude") if isinstance(brief.get("_controle_completude"), dict) else {}
    check("_controle_completude['date_limite']['statut'] == 'trouve_par_relance'",
          (controle.get("date_limite") or {}).get("statut") == "trouve_par_relance", repr(controle.get("date_limite")))
    check("les 5 autres champs restent « present »",
          all((controle.get(k) or {}).get("statut") == "present" for k in CHAMPS if k != "date_limite"),
          str({k: (controle.get(k) or {}).get("statut") for k in CHAMPS}))
    s = (brief.get("_sources") or {}).get("date_limite")
    check("_sources['date_limite'] cite RC.pdf p. 2", isinstance(s, dict) and s.get("piece") == "RC.pdf"
          and str(s.get("page")) == "2", repr(s))
    check("_sources['date_limite'] : verifie True (extrait retrouvé dans la page, sans LLM)",
          isinstance(s, dict) and s.get("verifie") is True and s.get("extrait") == EX_DATE, repr(s))
    check("_sources : toujours les 6 clés", set(brief.get("_sources") or {}) == set(CHAMPS))
    check("les autres sources ne sont pas dégradées (critères : RC.pdf p. 2 vérifié)",
          ((brief.get("_sources") or {}).get("criteres_ponderations") or {}).get("verifie") is True)
    check("cout_eur = somme de tous les appels, recherches ciblées comprises",
          proche(res.get("cout_eur"), r.total) and len(r.appels) >= 6, f"{res.get('cout_eur')!r} attendu {r.total}")
    check("modele = modèle de l'appel de fusion (ici le repli claude-sonnet-4-6), pas celui des pièces",
          res.get("modele") == SONNET, repr(res.get("modele")))
    check("_lecture inchangée par le contrôle : pct_non_lu 33.3",
          (brief.get("_lecture") or {}).get("pct_non_lu") == 33.3, repr((brief.get("_lecture") or {}).get("pct_non_lu")))

    # champ introuvable : la recherche ciblée n'aboutit pas
    scenario(sans=("montant",), controle_trouve=False, ccap_sans_montant=True)
    r = lancer("TEST-MD-INTROUVABLE")
    res = r.res
    brief = res.get("brief") if isinstance(res.get("brief"), dict) else {}
    check("champ introuvable : aucune exception, un résultat", r.exc is None and isinstance(r.brut, dict), repr(r.exc))
    check("champ introuvable : une recherche ciblée a bien été tentée",
          len(r.controles) >= 1 and all(str(a["prompt"]).startswith("RECHERCHE CIBLÉE") for a in r.controles),
          str(len(r.controles)))
    statut = ((brief.get("_controle_completude") or {}).get("montant") or {}).get("statut")
    check("champ introuvable : statut ni « present » ni « trouve_par_relance »",
          bool(brief) and statut not in ("present", "trouve_par_relance", None), repr(statut))
    check("champ introuvable : _sources['montant'] vaut None (rien d'inventé)",
          bool(brief) and "montant" in (brief.get("_sources") or {}) and brief["_sources"]["montant"] is None,
          repr((brief.get("_sources") or {}).get("montant")))
    check("champ introuvable : le montant n'est pas inventé dans le brief",
          bool(brief) and not (brief.get("montant_marche") or {}).get("valeur_estimee_euros"),
          repr(brief.get("montant_marche")))
    check("champ introuvable : les champs présents restent « present »",
          ((brief.get("_controle_completude") or {}).get("date_limite") or {}).get("statut") == "present")
    check("champ introuvable : cout_eur = somme de tous les appels", proche(res.get("cout_eur"), r.total),
          f"{res.get('cout_eur')!r} attendu {r.total}")


# =============================================================================
def test_lire_dce_plafond_et_dry_run():
    scenario()
    r = lancer("TEST-MD-DRYRUN", dry_run=True)
    res = r.res
    check("dry_run : aucune exception", r.exc is None and isinstance(r.brut, dict), repr(r.exc))
    check("dry_run : ok False, raison 'dry_run'", res.get("ok") is False and res.get("raison") == "dry_run",
          f"{res.get('ok')!r} / {res.get('raison')!r}")
    check("dry_run : AUCUN appel LLM", r.appels == [], str(len(r.appels)))
    check("dry_run : lecture None, brief None", res.get("lecture", "absent") is None and res.get("brief", "absent") is None,
          repr(res.get("lecture", "absent"))[:80])
    est = res.get("estimation") if isinstance(res.get("estimation"), dict) else {}
    check("dry_run : estimation rendue (cout_eur > 0, tokens_entree > 0)",
          (est.get("cout_eur") or 0) > 0 and (est.get("tokens_entree") or 0) > 0, repr(est))
    check("dry_run : cout_eur 0 (rien dépensé)", res.get("cout_eur") == 0, repr(res.get("cout_eur")))
    check("dry_run : l'inventaire a bien eu lieu", (DIR_TEST / r.mid / "_inventaire.json").is_file())
    attendu, exc = appeler(MD.estimer_cout, inventaire())
    check("dry_run : estimation = MD.estimer_cout(inventaire)",
          exc is None and proche((attendu or {}).get("cout_eur"), est.get("cout_eur"), 1e-9)
          and (attendu or {}).get("tokens_entree") == est.get("tokens_entree"), f"{attendu!r} / {est!r}")
    estime = est.get("cout_eur") or 0.0

    r = lancer("TEST-MD-PLAFOND-0", max_cout_par_dce=0.0)
    res = r.res
    check("plafond 0 € : ok False, raison 'cout_estime_depasse'",
          r.exc is None and res.get("ok") is False and res.get("raison") == "cout_estime_depasse",
          f"{r.exc!r} {res.get('ok')!r} / {res.get('raison')!r}")
    check("plafond dépassé : AUCUN appel LLM (DCE sauté, pas tronqué)", r.appels == [], str(len(r.appels)))
    check("plafond dépassé : brief None, cout_eur 0", res.get("brief", "absent") is None and res.get("cout_eur") == 0,
          f"{res.get('cout_eur')!r}")
    check("plafond dépassé : l'estimation est rendue (le dépassement est noté)",
          ((res.get("estimation") or {}).get("cout_eur") or 0) > 0, repr(res.get("estimation")))

    r = lancer("TEST-MD-PLAFOND-DESSOUS", max_cout_par_dce=estime * 0.99)
    check("plafond juste sous l'estimation : sauté, aucun appel",
          estime > 0 and r.exc is None and r.res.get("raison") == "cout_estime_depasse" and r.appels == [],
          f"estimation {estime!r} raison={r.res.get('raison')!r} appels={len(r.appels)}")

    r = lancer("TEST-MD-PLAFOND-DRY", max_cout_par_dce=0.0, dry_run=True)
    check("plafond dépassé et dry_run : toujours aucun appel, ok False",
          r.exc is None and r.res.get("ok") is False and r.appels == []
          and r.res.get("raison") in ("cout_estime_depasse", "dry_run"), f"{r.exc!r} {r.res.get('raison')!r}")

    r = lancer("TEST-MD-PLAFOND-EGAL", max_cout_par_dce=estime)
    check("plafond égal à l'estimation : pas « au-delà », le DCE est lu (ok True, 4 pièces + fusion)",
          estime > 0 and r.exc is None and r.res.get("ok") is True and len(r.pieces) == 4 and len(r.fusions) == 1,
          f"{r.exc!r} raison={r.res.get('raison')!r} appels={len(r.appels)}")

    r = lancer("TEST-MD-PLAFOND-HAUT", max_cout_par_dce=10**9)
    check("plafond très grand : le DCE est lu en entier",
          r.exc is None and r.res.get("ok") is True and sorted(a.get("piece") for a in r.pieces) == sorted(NOMS_PIECES),
          f"{r.exc!r} raison={r.res.get('raison')!r}")
    check("dossier source intact après les lectures sautées", empreinte(MIXTE) == EMPREINTE_MIXTE)


# =============================================================================
def test_lire_dce_echecs():
    # --- une pièce en échec : la fusion a lieu quand même ---
    scenario(echec_pieces=("CCTP.pdf",))
    r = lancer("TEST-MD-PIECE-KO")
    res = r.res
    brief = res.get("brief") if isinstance(res.get("brief"), dict) else {}
    lecture = brief.get("_lecture") if isinstance(brief.get("_lecture"), dict) else {}
    check("pièce en échec : aucune exception", r.exc is None and isinstance(r.brut, dict), repr(r.exc))
    verifier_appels(r, "pièce en échec")
    check("pièce en échec : la fusion a lieu quand même (1 appel)", len(r.fusions) == 1, str(len(r.fusions)))
    check("pièce en échec : ok True, brief rendu", res.get("ok") is True and bool(brief), f"raison={res.get('raison')!r}")
    check("pièce en échec : CCTP.pdf a le statut echec_lecture dans _lecture",
          (ligne(lecture, "CCTP.pdf") or {}).get("statut") == "echec_lecture", repr(ligne(lecture, "CCTP.pdf")))
    check("pièce en échec : les 3 autres pièces sont « lu »",
          all((ligne(lecture, n) or {}).get("statut") == "lu" for n in ("RC.pdf", "CCAP.pdf", "BPU.xlsx")),
          str({n: (ligne(lecture, n) or {}).get("statut") for n in NOMS_PIECES}))
    check("pièce en échec : nb_lues 3 sur 6 pièces de texte, pct_non_lu passe de 33.3 à 50.0",
          lecture.get("nb_lues") == 3 and lecture.get("nb_pieces_texte") == 6 and lecture.get("pct_non_lu") == 50.0,
          f"{lecture.get('nb_lues')!r} / {lecture.get('pct_non_lu')!r}")
    check("pièce en échec : résultat « lecture » cohérent avec le brief", res.get("lecture") == lecture and bool(lecture))
    check("pièce en échec : les 4 pièces ont été tentées",
          {a.get("piece") for a in r.pieces} == set(NOMS_PIECES), str([a.get("piece") for a in r.pieces]))
    check("pièce en échec : cout_eur compte aussi les appels en échec (somme des cout_total_eur)",
          proche(res.get("cout_eur"), r.total), f"{res.get('cout_eur')!r} attendu {r.total}")
    check("pièce en échec : _sources garde ses 6 clés, celles du RC restent vérifiées",
          set(brief.get("_sources") or {}) == set(CHAMPS)
          and ((brief.get("_sources") or {}).get("date_limite") or {}).get("verifie") is True,
          repr((brief.get("_sources") or {}).get("date_limite")))
    s_lots = (brief.get("_sources") or {}).get("lots")
    check("pièce en échec : la source des lots (pièce non lue) n'est jamais donnée pour vérifiée",
          bool(brief) and (s_lots is None or (isinstance(s_lots, dict) and s_lots.get("verifie") is False)),
          repr(s_lots))

    # --- deux pièces en échec ---
    scenario(echec_pieces=("CCTP.pdf", "BPU.xlsx"))
    r = lancer("TEST-MD-2-PIECES-KO")
    lecture = (r.res.get("brief") or {}).get("_lecture") or {}
    check("deux pièces en échec : pct_non_lu 66.7 (4 non lues sur 6), fusion faite",
          r.exc is None and lecture.get("pct_non_lu") == 66.7 and lecture.get("nb_lues") == 2 and len(r.fusions) == 1,
          f"{r.exc!r} {lecture.get('pct_non_lu')!r}")

    # --- fusion en échec ---
    scenario(echec_fusion=True)
    r = lancer("TEST-MD-FUSION-KO")
    res = r.res
    check("fusion en échec : aucune exception", r.exc is None and isinstance(r.brut, dict), repr(r.exc))
    check("fusion en échec : ok False", res.get("ok") is False, repr(res.get("ok")))
    check("fusion en échec : brief None", res.get("brief", "absent") is None, repr(res.get("brief", "absent"))[:80])
    check("fusion en échec : raison renseignée (ni dry_run ni cout_estime_depasse)",
          bool(res.get("raison")) and res.get("raison") not in ("dry_run", "cout_estime_depasse"),
          repr(res.get("raison")))
    check("fusion en échec : les pièces avaient bien été lues avant (4 appels), fusion tentée",
          len(r.pieces) == 4 and len(r.fusions) >= 1, f"{len(r.pieces)} / {len(r.fusions)}")
    check("fusion en échec : les appels déjà payés sont comptés dans cout_eur",
          proche(res.get("cout_eur"), r.total) and r.total > 0, f"{res.get('cout_eur')!r} attendu {r.total}")
    check("fusion en échec : estimation toujours rendue", isinstance(res.get("estimation"), dict))
    verifier_appels(r, "fusion en échec")

    # le faux est toujours en place et rien n'a fui
    scenario()
    check("le faux call_llm est resté en place", R.call_llm is faux_call_llm)
    check("dossier source intact en fin de test", empreinte(MIXTE) == EMPREINTE_MIXTE,
          str(sorted(set(empreinte(MIXTE)) ^ set(EMPREINTE_MIXTE))))
    check("P.DIR_PIECES toujours sur le dossier temporaire", Path(P.DIR_PIECES) == DIR_TEST, repr(P.DIR_PIECES))
    check("aucun dossier de test dans DATA / 'pieces'",
          not any((Path(DATA) / "pieces" / m).exists()
                  for m in ("TEST-MD-INVENTAIRE", "TEST-MD-NOMINAL", "TEST-MD-CONTROLE", "TEST-MD-INTROUVABLE",
                            "TEST-MD-DRYRUN", "TEST-MD-PLAFOND-0", "TEST-MD-PIECE-KO", "TEST-MD-FUSION-KO")))


section("contrat : CHAMPS_SOURCES, défauts de lire_dce", test_contrat)
section("decouper : découpage aux marqueurs de page", test_decouper)
section("normaliser_extrait / verifier_extrait", test_extraits)
section("tableau_lecture : _lecture et pct_non_lu", test_tableau_lecture)
section("construire_sources : _sources vérifiées sans LLM", test_construire_sources)
section("estimer_cout : estimation avant appel", test_estimer_cout)
section("lire_dce : cas nominal (pièces, fusion, _sources, _lecture)", test_lire_dce_nominal)
section("lire_dce : contrôle de complétude et recherche ciblée", test_lire_dce_controle)
section("lire_dce : plafond de coût par DCE et dry_run", test_lire_dce_plafond_et_dry_run)
section("lire_dce : pièce en échec, fusion en échec", test_lire_dce_echecs)

terminer()
