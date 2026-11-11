# -*- coding: utf-8 -*-
"""
tests/test_extraire_mode_document.py
------------------------------------
Tests HORS-LIGNE (chantier 2, étape 5 : branchement du mode document) :

  - extraire : MODE_DEFAUT / MODES, REPERTOIRE_ARCHIVE_BRIEFS (archive/data/briefs) ;
  - archiver_brief_existant : copie exacte du brief avant écrasement, jamais dans
    briefs_extraits, deux archivages = deux fichiers, None sans brief ;
  - signature_dossier : tous les fichiers (sous-dossiers compris), noms relatifs et
    tailles, "" si vide ou absent, lecture seule ;
  - traiter_marche mode document : mode_document.lire_dce (faux) appelé avec id, dossier,
    contexte, plafond par DCE, dry_run ; _meta ; écritures ; archivage avant écrasement ;
    DCE sauté (cout_estime_depasse), autre échec, dry_run, BudgetDepasseError ;
    rien n'est écrit dans le dossier du DCE ; DCE sans aucun PDF traité ;
  - traiter_marche mode classique : llm_extract.extraire_via_llm (faux), lire_dce non appelé ;
  - extraire.main : --mode, --max-cout-par-dce, dossier sans PDF, dossier vide, état ;
  - pipeline.main : étape 6 sans --mode, plafonnée à 5 € par défaut ;
  - rattrapage_btp_octobre briefs : --mode, --max-cout-par-dce.

Base et dossiers temporaires, réseau coupé (socket), backends LLM remplacés par un refus.

Lancement : python tests/test_extraire_mode_document.py
"""
import contextlib
import copy
import inspect
import io
import json
import os
import socket
import sys
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from base_temporaire import isoler_stockage
dossier = isoler_stockage({"kill_switch_global": False, "plafond_global_eur_mois": 1e12})


def _reseau_interdit(*_a, **_k):
    raise OSError("réseau interdit dans tests/test_extraire_mode_document.py")


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


def silencieux(fn, *a, **k):
    """Lance fn sans rien afficher. Rend (résultat, erreur). Flux texte réel : les CLI
    appellent stdout.reconfigure."""
    resultat = erreur = None
    with io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="replace") as sortie:
        with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(sortie):
            try:
                resultat = fn(*a, **k)
            except SystemExit as e:
                erreur = e if e.code not in (0, None) else None
            except Exception as e:  # noqa: BLE001
                erreur = e
    return resultat, erreur


from tendia.core import budget, chemins, stockage
ARCHIVE_REELLE = Path(chemins.ARCHIVE)
chemins.DATA = dossier  # rien ne doit viser le vrai data/ (fichier d'ids du rattrapage compris)

from tendia.analyse import llm_router as R

R.charger_env = lambda *a, **k: None
for _v in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
    os.environ[_v] = "cle-de-test-hors-ligne"
os.environ.pop("TENDIA_PROXY_ACTIF", None)
APPELS_FOURNISSEUR = []


def _backend_interdit(*a, **k):
    APPELS_FOURNISSEUR.append((a, k))
    raise AssertionError("appel fournisseur réel interdit dans tests/test_extraire_mode_document.py")


R._appel_gemini = _backend_interdit
R._appel_claude = _backend_interdit
R._respecter_rate_limit = lambda modele: None

from tendia import pipeline as P
from tendia.analyse import extraire as E
from tendia.analyse import llm_extract, mode_document

# --- valeurs par défaut relevées AVANT toute redirection ---------------------------
ARCHIVE_BRIEFS_DEFAUT = getattr(E, "REPERTOIRE_ARCHIVE_BRIEFS", None)
TRAITER_REEL = getattr(E, "traiter_marche", None)
SCANNER_REEL = getattr(E, "_scanner_dossiers_dce", None)
LIRE_DCE_REEL = getattr(mode_document, "lire_dce", None)

# --- redirections vers le dossier temporaire ----------------------------------------
ARCH = dossier / "archive" / "data" / "briefs"      # volontairement pas encore créé
E.REPERTOIRE_ARCHIVE_BRIEFS = ARCH
E.REPERTOIRE_DCE = str(dossier / "dce")
E.REPERTOIRE_EXTRACTIONS = str(dossier / "extractions")
E.REPERTOIRE_RAPPORTS = str(dossier / "rapports")
E.FICHIER_ETAT = os.path.join(E.REPERTOIRE_EXTRACTIONS, "_etat.json")
for _d in (E.REPERTOIRE_DCE, E.REPERTOIRE_EXTRACTIONS, E.REPERTOIRE_RAPPORTS):
    os.makedirs(_d, exist_ok=True)
E.llm_extract._obtenir_cle_api = lambda: "sk-ant-fausse-cle-de-test"

ARGON = "gemini-4-argon"
SONNET = "claude-sonnet-4-6"
CHAMPS = ("criteres_ponderations", "date_limite", "pieces_exigees", "visite", "montant", "lots")
J = lambda n: (date.today() + timedelta(days=n)).isoformat()


# --- outils --------------------------------------------------------------------------
def instantane(racine) -> dict:
    """{chemin relatif: taille} de tous les fichiers ; les dossiers valent -1."""
    racine = str(racine)
    vu = {}
    for base, sous, fichiers in os.walk(racine):
        for d in sous:
            vu[os.path.relpath(os.path.join(base, d), racine).replace("\\", "/") + "/"] = -1
        for f in fichiers:
            chemin = os.path.join(base, f)
            vu[os.path.relpath(chemin, racine).replace("\\", "/")] = os.path.getsize(chemin)
    return vu


def archives_de(mid) -> list:
    if not ARCH.is_dir():
        return []
    return sorted(p for p in ARCH.iterdir() if p.is_file() and p.name.startswith(mid + "_"))


def cles_briefs() -> set:
    stockage.invalider_cache()
    return set((stockage.charger("briefs_extraits") or {}).keys())


def lire_brief(mid):
    stockage.invalider_cache()
    return stockage.lire("briefs_extraits", mid)


def ecrire_marche(mid, **champs):
    marche = {"id": mid, "objet": "Réfection de la couverture de l'école", "acheteur": "Commune de Test",
              "date_publication": "2026-09-01", "nature": "APPEL_OFFRE", "type_marche": "TRAVAUX",
              "date_limite_depot": J(30), "dce_contenu": "complet", "url_dce": f"https://x/{mid}",
              "dce_telechargement_statut": "ok"}
    marche.update(champs)
    stockage.ecrire("marches", mid, marche)


def creer_dce(racine, mid, docx=True, zip_=False) -> str:
    """Dossier de DCE SANS aucun PDF : un .docx, éventuellement un .zip qui contient un PDF."""
    chemin = os.path.join(str(racine), mid)
    os.makedirs(chemin, exist_ok=True)
    if docx:
        with open(os.path.join(chemin, "CCTP.docx"), "wb") as f:
            f.write(b"PK\x03\x04 faux docx de test " * 40)
    if zip_:
        with zipfile.ZipFile(os.path.join(chemin, "pieces.zip"), "w") as z:
            z.writestr("interne/RC.pdf", b"%PDF-1.4 faux pdf de test " * 30)
            z.writestr("BPU.xlsx", b"faux xlsx " * 30)
    return chemin


def ancien_brief(mid) -> dict:
    return {"synthese_marche": "Ancien brief : réfection à l'identique, délai 3 mois, pénalités 150 €",
            "domaines_metier": ["couverture"], "calendrier": {"date_limite_offres": "2026-11-30 12:00"},
            "_meta": {"id_marche": mid, "type": "complet", "modele": SONNET, "cout_eur": 0.11,
                      "date_generation": "2026-10-20T08:00:00+00:00"}}


def fichiers_ecrits(mid) -> list:
    """Fichiers de sortie de traiter_marche pour ce marché (extraction, rapport, archive)."""
    vus = []
    if os.path.isfile(os.path.join(E.REPERTOIRE_EXTRACTIONS, f"{mid}.json")):
        vus.append(f"extractions/{mid}.json")
    if os.path.isfile(os.path.join(E.REPERTOIRE_RAPPORTS, f"brief_{mid}.md")):
        vus.append(f"rapports/brief_{mid}.md")
    vus.extend(p.name for p in archives_de(mid))
    return vus


# --- faux mode_document.lire_dce -------------------------------------------------------
LECTURE = {"pieces": [{"nom": "RC.pdf", "type": "RC", "statut": "lu", "pages": 2, "caracteres": 1400,
                       "detail": None}],
           "nb_pieces_texte": 1, "nb_lues": 1, "pct_non_lu": 0.0}
SOURCES = {c: {"piece": "RC.pdf", "page": 1, "extrait": f"extrait {c}", "verifie": True} for c in CHAMPS}
ESTIMATION = {"cout_eur": 0.5, "modele": ARGON, "tokens_entree": 1000, "tokens_sortie": 100}
INVENTAIRE = {"pieces": [], "ecartes": [], "doublons": []}
BRIEF_FAUX = {"synthese_marche": "Réfection de couverture en tuiles, lot unique (mode document)",
              "domaines_metier": [], "calendrier": {"date_limite_offres": "2026-12-15 12:00"},
              "_sources": SOURCES, "_lecture": LECTURE, "_controle_completude": {}}
APPELS_LIRE = []
SCENARIO = {"cas": "ok"}


def _ref_lire_dce(marche_id, dossier_dce, contexte, codes_presets, max_cout_par_dce=2.5, dry_run=False,
                  verbose=True, modele=None, reprendre=True):
    """Même signature que mode_document.lire_dce : sert à nommer les arguments reçus."""


def faux_lire_dce(*a, **k):
    recu = inspect.signature(_ref_lire_dce).bind(*a, **k)
    recu.apply_defaults()
    recu = dict(recu.arguments)
    recu["_mots_cles"] = sorted(k)
    APPELS_LIRE.append(recu)
    base = {"ok": False, "brief": None, "raison": None, "estimation": copy.deepcopy(ESTIMATION),
            "inventaire": copy.deepcopy(INVENTAIRE), "lecture": None, "cout_eur": 0.0, "modele": ARGON,
            "appels": None, "duree_s": 0.1}
    if SCENARIO["cas"] == "budget":
        raise budget.BudgetDepasseError("kill switch actif (test)")
    if recu["dry_run"]:
        base["raison"] = "dry_run"
        return base
    if SCENARIO["cas"] == "depasse" or ESTIMATION["cout_eur"] > recu["max_cout_par_dce"]:
        base["raison"] = "cout_estime_depasse"
        return base
    if SCENARIO["cas"] == "echec":
        base.update({"raison": "echec_fusion : X", "lecture": copy.deepcopy(LECTURE), "cout_eur": 0.2,
                     "appels": {"nb_appels": 2, "nb_replis": 0, "modeles": {ARGON: 2}, "tokens_in": 500,
                                "tokens_out": 50, "cout_eur": 0.2}})
        return base
    base.update({"ok": True, "brief": copy.deepcopy(BRIEF_FAUX), "lecture": copy.deepcopy(LECTURE),
                 "cout_eur": 0.42, "duree_s": 1.5,
                 "appels": {"nb_appels": 3, "nb_replis": 0, "modeles": {ARGON: 3}, "tokens_in": 900,
                            "tokens_out": 90, "cout_eur": 0.42}})
    return base


mode_document.lire_dce = faux_lire_dce

# --- faux llm_extract.extraire_via_llm --------------------------------------------------
APPELS_CLASSIQUE = []


def faux_extraire_via_llm(*a, **k):
    APPELS_CLASSIQUE.append((a, k))
    return {"synthese_marche": "classique", "domaines_metier": [],
            "_appel_llm": {"modele": SONNET, "tokens_input": 10, "tokens_output": 5, "cout_eur": 0.3,
                           "duree_sec": 1.0, "codes_presets": []}}


llm_extract.extraire_via_llm = faux_extraire_via_llm
PDFS_CLASSIQUE = {"rc.pdf": {"hash": "h1", "taille_chars": 5000,
                             "texte": "Règlement de consultation de la commune de Test. " * 100}}


def traiter(mid, chemin, pdfs, scenario="ok", **kw):
    """Appelle le vrai traiter_marche, sans affichage. Rend (résultat, erreur, appels à lire_dce)."""
    SCENARIO["cas"] = scenario
    APPELS_LIRE.clear()
    APPELS_CLASSIQUE.clear()
    try:
        res, err = silencieux(E.traiter_marche, mid, chemin, pdfs, **kw)
    finally:
        SCENARIO["cas"] = "ok"
    return (res if isinstance(res, dict) else {}), err, list(APPELS_LIRE)


# =============================================================================
def test_constantes():
    check("MODE_DEFAUT == 'document'", getattr(E, "MODE_DEFAUT", None) == "document",
          repr(getattr(E, "MODE_DEFAUT", None)))
    check("MODES == ('document', 'classique')", getattr(E, "MODES", None) == ("document", "classique"),
          repr(getattr(E, "MODES", None)))
    check("REPERTOIRE_ARCHIVE_BRIEFS vaut ARCHIVE/data/briefs par défaut",
          ARCHIVE_BRIEFS_DEFAUT is not None
          and Path(ARCHIVE_BRIEFS_DEFAUT) == ARCHIVE_REELLE / "data" / "briefs", repr(ARCHIVE_BRIEFS_DEFAUT))
    check("l'archive des briefs n'est pas sous data/",
          ARCHIVE_BRIEFS_DEFAUT is not None
          and Path(chemins.RACINE_DEPOT) / "data" not in Path(ARCHIVE_BRIEFS_DEFAUT).parents,
          repr(ARCHIVE_BRIEFS_DEFAUT))
    params = inspect.signature(TRAITER_REEL).parameters if TRAITER_REEL else {}
    check("traiter_marche : paramètre mode, défaut None",
          "mode" in params and params["mode"].default is None, repr(params.get("mode")))
    check("traiter_marche : max_cout_par_dce, défaut 2.5",
          "max_cout_par_dce" in params and params["max_cout_par_dce"].default == 2.5,
          repr(params.get("max_cout_par_dce")))
    check("traiter_marche : dry_run False par défaut",
          "dry_run" in params and params["dry_run"].default is False, repr(params.get("dry_run")))


# =============================================================================
def test_archiver_brief_existant():
    mid = "T5-ARCH-A"
    ancien = ancien_brief(mid)
    stockage.ecrire("briefs_extraits", mid, copy.deepcopy(ancien))
    stockage.ecrire("briefs_extraits", "T5-ARCH-AUTRE", ancien_brief("T5-ARCH-AUTRE"))
    cles_avant = cles_briefs()
    autre_avant = copy.deepcopy(lire_brief("T5-ARCH-AUTRE"))

    r, err = silencieux(E.archiver_brief_existant, "T5-ARCH-INCONNU")
    check("pas de brief : None", err is None and r is None, f"{err!r} {r!r}")
    check("pas de brief : aucun fichier", archives_de("T5-ARCH-INCONNU") == []
          and (not ARCH.is_dir() or list(ARCH.iterdir()) == []), str(list(ARCH.iterdir()) if ARCH.is_dir() else ""))
    r, err = silencieux(E.archiver_brief_existant, "")
    check("id vide : None, aucun fichier", err is None and r is None
          and (not ARCH.is_dir() or list(ARCH.iterdir()) == []), f"{err!r} {r!r}")

    c1, err = silencieux(E.archiver_brief_existant, mid)
    check("brief existant : chemin rendu, sans exception (dossier d'archive créé au besoin)",
          err is None and c1 is not None, f"{err!r} {c1!r}")
    c1 = Path(c1) if c1 else None
    check("le fichier existe dans REPERTOIRE_ARCHIVE_BRIEFS",
          c1 is not None and c1.is_file() and c1.parent.resolve() == ARCH.resolve(), repr(c1))
    check("nom du fichier : <id>_<horodatage>.json",
          c1 is not None and c1.name.startswith(mid + "_") and c1.suffix == ".json"
          and len(c1.stem) > len(mid) + 1, repr(c1))
    contenu = json.loads(c1.read_text(encoding="utf-8")) if c1 and c1.is_file() else None
    check("copie exacte du brief (JSON lisible en UTF-8, accents compris)", contenu == ancien, repr(contenu)[:200])

    c2, err = silencieux(E.archiver_brief_existant, mid)
    c2 = Path(c2) if c2 else None
    check("deuxième archivage immédiat : un autre fichier", err is None and c2 is not None and c2 != c1,
          f"{err!r} {c1!r} {c2!r}")
    check("deux fichiers distincts sur disque, aucun écrasé", len(archives_de(mid)) == 2,
          str([p.name for p in archives_de(mid)]))
    check("les deux copies sont identiques au brief",
          all(json.loads(p.read_text(encoding="utf-8")) == ancien for p in archives_de(mid)))
    check("seul le marché demandé est archivé", archives_de("T5-ARCH-AUTRE") == []
          and len(list(ARCH.iterdir())) == 2, str([p.name for p in ARCH.iterdir()]))

    check("briefs_extraits garde exactement les mêmes clés (aucune clé de sauvegarde)",
          cles_briefs() == cles_avant, str(sorted(cles_briefs() ^ cles_avant)))
    check("le brief en base n'est pas modifié", lire_brief(mid) == ancien, repr(lire_brief(mid))[:200])
    check("les autres briefs ne sont pas modifiés", lire_brief("T5-ARCH-AUTRE") == autre_avant)


# =============================================================================
def test_signature_dossier():
    racine = dossier / "signatures"
    a = racine / "A"
    (a / "sous" / "profond").mkdir(parents=True)
    vide = racine / "VIDE"
    vide.mkdir()
    check("dossier absent : ''", E.signature_dossier(str(racine / "ABSENT")) == "",
          repr(E.signature_dossier(str(racine / "ABSENT"))))
    check("dossier absent : pas créé par la lecture", not (racine / "ABSENT").exists())
    check("dossier vide : ''", E.signature_dossier(str(vide)) == "", repr(E.signature_dossier(str(vide))))

    (a / "RC.pdf").write_bytes(b"x" * 100)
    (a / "CCTP.docx").write_bytes(b"y" * 250)
    avant = instantane(a)
    s1 = E.signature_dossier(str(a))
    check("dossier non vide : chaîne non vide", isinstance(s1, str) and s1 != "", repr(s1))
    check("identique tant que rien ne change", E.signature_dossier(str(a)) == s1)
    check("lecture seule : le dossier n'est pas modifié", instantane(a) == avant, str(instantane(a)))

    (a / "sous" / "profond" / "BPU.xlsx").write_bytes(b"z" * 10)
    s2 = E.signature_dossier(str(a))
    check("fichier ajouté dans un sous-dossier : signature différente", s2 != s1 and s2 != "")
    (a / "AE.docx").write_bytes(b"w" * 10)
    s3 = E.signature_dossier(str(a))
    check("fichier ajouté au premier niveau : signature différente", s3 not in (s1, s2))
    (a / "RC.pdf").write_bytes(b"x" * 101)
    s4 = E.signature_dossier(str(a))
    check("un fichier change de taille : signature différente", s4 != s3)
    (a / "sous" / "profond" / "BPU.xlsx").write_bytes(b"z" * 11)
    s5 = E.signature_dossier(str(a))
    check("un fichier de sous-dossier change de taille : signature différente", s5 != s4)
    (a / "RC.pdf").write_bytes(b"x" * 100)
    (a / "sous" / "profond" / "BPU.xlsx").write_bytes(b"z" * 10)
    check("retour aux mêmes noms et tailles : même signature", E.signature_dossier(str(a)) == s3)
    os.replace(a / "AE.docx", a / "sous" / "AE.docx")
    check("même fichier déplacé dans un sous-dossier (nom relatif différent) : signature différente",
          E.signature_dossier(str(a)) != s3)
    os.replace(a / "sous" / "AE.docx", a / "AE.docx")

    # Noms relatifs : la même arborescence ailleurs donne la même empreinte.
    b = racine / "B"
    (b / "sous" / "profond").mkdir(parents=True)
    (b / "RC.pdf").write_bytes(b"1" * 100)
    (b / "CCTP.docx").write_bytes(b"2" * 250)
    (b / "AE.docx").write_bytes(b"3" * 10)
    (b / "sous" / "profond" / "BPU.xlsx").write_bytes(b"4" * 10)
    check("mêmes noms relatifs et tailles dans un autre dossier : même signature",
          E.signature_dossier(str(b)) == s3)

    seul = racine / "SOUS_SEUL"
    (seul / "x").mkdir(parents=True)
    (seul / "x" / "CCTP.docx").write_bytes(b"d" * 5)
    check("DCE dont le seul fichier est dans un sous-dossier : signature non vide",
          E.signature_dossier(str(seul)) != "")
    gros = racine / "GROS"
    gros.mkdir()
    for i in range(300):
        (gros / f"piece_{i:03d}.pdf").write_bytes(b"p" * (i + 1))
    sg = E.signature_dossier(str(gros))
    check("300 fichiers : signature stable et non vide", sg != "" and sg == E.signature_dossier(str(gros)))


# =============================================================================
def test_document_nominal():
    mid = "T5-DOC-OK"
    ecrire_marche(mid)
    chemin = creer_dce(E.REPERTOIRE_DCE, mid, docx=True, zip_=True)
    avant = instantane(chemin)
    cles_avant = cles_briefs()
    res, err, appels = traiter(mid, chemin, {})
    check("aucune exception", err is None, repr(err))
    check("lire_dce appelé une fois", len(appels) == 1, str(len(appels)))
    a = appels[0] if appels else {}
    check("lire_dce reçoit l'id du marché", a.get("marche_id") == mid, repr(a.get("marche_id")))
    check("lire_dce reçoit le dossier du DCE",
          a.get("dossier_dce") is not None
          and os.path.normcase(os.path.abspath(str(a.get("dossier_dce")))) == os.path.normcase(os.path.abspath(chemin)),
          repr(a.get("dossier_dce")))
    ctx = a.get("contexte")
    check("lire_dce reçoit un contexte dict contenant l'id",
          isinstance(ctx, dict) and any(v == mid for v in ctx.values()), repr(ctx)[:200])
    check("lire_dce reçoit codes_presets (liste)", isinstance(a.get("codes_presets"), (list, tuple)),
          repr(a.get("codes_presets")))
    check("max_cout_par_dce par défaut : 2.5 transmis", a.get("max_cout_par_dce") == 2.5,
          repr(a.get("max_cout_par_dce")))
    check("dry_run False transmis", a.get("dry_run") is False, repr(a.get("dry_run")))
    check("extraire_via_llm (mode classique) non appelé", APPELS_CLASSIQUE == [], str(len(APPELS_CLASSIQUE)))

    check("ok True", res.get("ok") is True, repr(res.get("ok")))
    check("mode 'document' dans le résultat (mode None → MODE_DEFAUT)", res.get("mode") == "document",
          repr(res.get("mode")))
    check("erreur None, raison None", res.get("erreur", "absent") is None and res.get("raison", "absent") is None,
          f"{res.get('erreur', 'absent')!r} / {res.get('raison', 'absent')!r}")
    ext = res.get("extraction") if isinstance(res.get("extraction"), dict) else {}
    check("extraction = le brief rendu par lire_dce",
          ext.get("synthese_marche") == BRIEF_FAUX["synthese_marche"]
          and ext.get("calendrier") == BRIEF_FAUX["calendrier"], repr(ext)[:200])
    meta = ext.get("_meta") if isinstance(ext.get("_meta"), dict) else {}
    check("_meta.id_marche", meta.get("id_marche") == mid, repr(meta.get("id_marche")))
    check("_meta.type == 'complet'", meta.get("type") == "complet", repr(meta.get("type")))
    check("_meta.mode == 'document'", meta.get("mode") == "document", repr(meta.get("mode")))
    check("_meta.modele == modèle rendu par lire_dce", meta.get("modele") == ARGON, repr(meta.get("modele")))
    check("_meta.cout_eur == 0.42 (coût réel, pas l'estimation 0.5)",
          isinstance(meta.get("cout_eur"), (int, float)) and abs(meta["cout_eur"] - 0.42) < 1e-9,
          repr(meta.get("cout_eur")))
    check("_meta.date_generation renseignée", bool(meta.get("date_generation")), repr(meta.get("date_generation")))
    cout, exc = silencieux(E.cout_du_resultat, res)
    check("cout_du_resultat(resultat) == 0.42", exc is None and cout is not None and abs(cout - 0.42) < 1e-9,
          f"{exc!r} {cout!r}")
    check("_sources conservées (6 champs)", ext.get("_sources") == SOURCES, repr(ext.get("_sources"))[:200])
    check("_lecture conservée", ext.get("_lecture") == LECTURE, repr(ext.get("_lecture"))[:200])

    en_base = lire_brief(mid) or {}
    check("brief écrit dans briefs_extraits",
          en_base.get("synthese_marche") == BRIEF_FAUX["synthese_marche"]
          and (en_base.get("_meta") or {}).get("mode") == "document", repr(en_base)[:200])
    check("brief en base : _sources et _lecture présents",
          en_base.get("_sources") == SOURCES and en_base.get("_lecture") == LECTURE)
    check("briefs_extraits : une seule clé ajoutée, l'id du marché", cles_briefs() - cles_avant == {mid},
          str(sorted(cles_briefs() - cles_avant)))
    fichier = os.path.join(E.REPERTOIRE_EXTRACTIONS, f"{mid}.json")
    check("fichier REPERTOIRE_EXTRACTIONS/<id>.json écrit", os.path.isfile(fichier))
    if os.path.isfile(fichier):
        with open(fichier, encoding="utf-8") as f:
            sur_disque = json.load(f)
        check("<id>.json : même brief, _meta.mode document",
              sur_disque.get("synthese_marche") == BRIEF_FAUX["synthese_marche"]
              and (sur_disque.get("_meta") or {}).get("mode") == "document", repr(sur_disque)[:200])
    rapport = os.path.join(E.REPERTOIRE_RAPPORTS, f"brief_{mid}.md")
    check("rapport brief_<id>.md écrit dans REPERTOIRE_RAPPORTS",
          os.path.isfile(rapport) and os.path.getsize(rapport) > 0)
    check("pas de brief antérieur : rien d'archivé", archives_de(mid) == [], str(archives_de(mid)))
    check("dossier du DCE inchangé (zip non dézippé, pas de _zip_archives)", instantane(chemin) == avant,
          f"{avant} → {instantane(chemin)}")


def test_document_sans_pdf():
    for mid, pdfs in (("T5-DOC-DOCX-VIDE", {}), ("T5-DOC-DOCX-NONE", None)):
        ecrire_marche(mid)
        chemin = creer_dce(E.REPERTOIRE_DCE, mid, docx=True, zip_=False)
        avant = instantane(chemin)
        res, err, appels = traiter(mid, chemin, pdfs, mode="document")
        check(f"pdfs={pdfs!r}, un seul .docx : traité (ok True, lire_dce appelé)",
              err is None and res.get("ok") is True and len(appels) == 1,
              f"{err!r} ok={res.get('ok')!r} raison={res.get('raison')!r} erreur={res.get('erreur')!r}")
        check(f"pdfs={pdfs!r} : brief écrit", (lire_brief(mid) or {}).get("synthese_marche") == BRIEF_FAUX["synthese_marche"])
        check(f"pdfs={pdfs!r} : dossier du DCE inchangé", instantane(chemin) == avant, str(instantane(chemin)))


def test_document_brief_existant():
    mid = "T5-DOC-EXISTANT"
    ecrire_marche(mid)
    chemin = creer_dce(E.REPERTOIRE_DCE, mid, docx=True, zip_=True)
    ancien = ancien_brief(mid)
    stockage.ecrire("briefs_extraits", mid, copy.deepcopy(ancien))
    cles_avant = cles_briefs()
    avant = instantane(chemin)

    ecritures = []
    ecrire_reel = stockage.ecrire

    def espion_ecrire(collection, id_objet, objet, *a, **k):
        if collection == "briefs_extraits":
            copies = [json.loads(p.read_text(encoding="utf-8")) for p in archives_de(mid)]
            ecritures.append({"cle": id_objet, "copies_deja_la": copies})
        return ecrire_reel(collection, id_objet, objet, *a, **k)

    stockage.ecrire = espion_ecrire
    try:
        res, err, appels = traiter(mid, chemin, {})
    finally:
        stockage.ecrire = ecrire_reel
    check("ok True", err is None and res.get("ok") is True, f"{err!r} {res.get('ok')!r} {res.get('erreur')!r}")
    copies = archives_de(mid)
    check("une copie de l'ancien brief dans REPERTOIRE_ARCHIVE_BRIEFS", len(copies) == 1,
          str([p.name for p in copies]))
    check("copie identique à l'ancien brief",
          len(copies) == 1 and json.loads(copies[0].read_text(encoding="utf-8")) == ancien)
    check("le brief est écrit par stockage.ecrire('briefs_extraits', id, …)",
          any(e["cle"] == mid for e in ecritures), str([e["cle"] for e in ecritures]))
    check("la copie existe AVANT l'écrasement en base",
          bool(ecritures) and all(e["copies_deja_la"] == [ancien] for e in ecritures if e["cle"] == mid)
          and any(e["cle"] == mid for e in ecritures),
          str([(e["cle"], len(e["copies_deja_la"])) for e in ecritures]))
    check("aucune écriture dans briefs_extraits sous une autre clé (pas de clé de sauvegarde)",
          all(e["cle"] == mid for e in ecritures), str([e["cle"] for e in ecritures]))
    check("briefs_extraits garde exactement les mêmes clés", cles_briefs() == cles_avant,
          str(sorted(cles_briefs() ^ cles_avant)))
    nouveau = lire_brief(mid) or {}
    check("le brief en base est le nouveau", nouveau.get("synthese_marche") == BRIEF_FAUX["synthese_marche"]
          and (nouveau.get("_meta") or {}).get("mode") == "document", repr(nouveau)[:200])
    check("dossier du DCE inchangé", instantane(chemin) == avant)

    res, err, _ = traiter(mid, chemin, {})
    check("nouvelle extraction : une deuxième copie, la première n'est pas écrasée",
          err is None and res.get("ok") is True and len(archives_de(mid)) == 2,
          str([p.name for p in archives_de(mid)]))
    contenus = [json.loads(p.read_text(encoding="utf-8")) for p in archives_de(mid)]
    check("l'archive contient l'ancien brief ET le brief intermédiaire",
          ancien in contenus and any(c.get("synthese_marche") == BRIEF_FAUX["synthese_marche"] for c in contenus))
    check("toujours les mêmes clés dans briefs_extraits", cles_briefs() == cles_avant)


def _cas_sans_ecriture(mid, scenario, raison_attendue, avec_brief, **kw):
    ecrire_marche(mid)
    chemin = creer_dce(E.REPERTOIRE_DCE, mid, docx=True, zip_=True)
    ancien = ancien_brief(mid)
    if avec_brief:
        stockage.ecrire("briefs_extraits", mid, copy.deepcopy(ancien))
    cles_avant = cles_briefs()
    avant = instantane(chemin)
    res, err, appels = traiter(mid, chemin, {}, scenario=scenario, **kw)
    nom = f"{mid}"
    check(f"{nom} : aucune exception, lire_dce appelé une fois", err is None and len(appels) == 1,
          f"{err!r} {len(appels)}")
    check(f"{nom} : ok False", res.get("ok") is False, repr(res.get("ok")))
    check(f"{nom} : raison {raison_attendue!r}", res.get("raison") == raison_attendue, repr(res.get("raison")))
    check(f"{nom} : extraction None", res.get("extraction", "absent") is None, repr(res.get("extraction", "absent"))[:80])
    check(f"{nom} : mode 'document' dans le résultat", res.get("mode") == "document", repr(res.get("mode")))
    check(f"{nom} : rien d'archivé, aucun fichier écrit", fichiers_ecrits(mid) == [], str(fichiers_ecrits(mid)))
    check(f"{nom} : briefs_extraits garde les mêmes clés", cles_briefs() == cles_avant,
          str(sorted(cles_briefs() ^ cles_avant)))
    if avec_brief:
        check(f"{nom} : brief existant intact", lire_brief(mid) == ancien, repr(lire_brief(mid))[:200])
    check(f"{nom} : dossier du DCE inchangé", instantane(chemin) == avant)
    return res, appels


def test_document_saute_et_echecs():
    _cas_sans_ecriture("T5-DOC-DEPASSE", "depasse", "cout_estime_depasse", avec_brief=True)
    _cas_sans_ecriture("T5-DOC-DEPASSE-NEUF", "depasse", "cout_estime_depasse", avec_brief=False)
    # Plafond 0 : transmis tel quel (pas remplacé par le défaut), le DCE estimé à 0,5 € est sauté.
    res, appels = _cas_sans_ecriture("T5-DOC-PLAFOND-ZERO", "ok", "cout_estime_depasse", avec_brief=True,
                                     max_cout_par_dce=0)
    check("max_cout_par_dce=0 transmis tel quel à lire_dce",
          bool(appels) and appels[0].get("max_cout_par_dce") == 0
          and appels[0].get("max_cout_par_dce") is not None, repr(appels[0].get("max_cout_par_dce") if appels else None))
    _cas_sans_ecriture("T5-DOC-ECHEC", "echec", "echec_fusion : X", avec_brief=True)
    _cas_sans_ecriture("T5-DOC-ECHEC-NEUF", "echec", "echec_fusion : X", avec_brief=False)


def test_document_plafond_transmis():
    for mid, plafond in (("T5-DOC-PLAFOND-A", 7.25), ("T5-DOC-PLAFOND-B", 0.5), ("T5-DOC-PLAFOND-C", 1e9)):
        ecrire_marche(mid)
        chemin = creer_dce(E.REPERTOIRE_DCE, mid)
        res, err, appels = traiter(mid, chemin, {}, mode="document", max_cout_par_dce=plafond, verbose=False)
        check(f"max_cout_par_dce={plafond} transmis tel quel",
              err is None and len(appels) == 1 and appels[0].get("max_cout_par_dce") == plafond,
              f"{err!r} {appels[0].get('max_cout_par_dce') if appels else None!r}")
        check(f"max_cout_par_dce={plafond} : estimation 0,5 € sous ou au plafond, DCE traité",
              res.get("ok") is True, f"{res.get('ok')!r} {res.get('raison')!r}")
        check(f"max_cout_par_dce={plafond} : verbose=False transmis",
              bool(appels) and appels[0].get("verbose") is False, repr(appels[0].get("verbose") if appels else None))


def test_document_dry_run():
    for mid, avec_brief in (("T5-DOC-DRY", True), ("T5-DOC-DRY-NEUF", False)):
        ecrire_marche(mid)
        chemin = creer_dce(E.REPERTOIRE_DCE, mid, docx=True, zip_=True)
        ancien = ancien_brief(mid)
        if avec_brief:
            stockage.ecrire("briefs_extraits", mid, copy.deepcopy(ancien))
        cles_avant = cles_briefs()
        avant = instantane(chemin)
        res, err, appels = traiter(mid, chemin, {}, dry_run=True)
        check(f"{mid} : lire_dce appelé avec dry_run=True",
              err is None and len(appels) == 1 and appels[0].get("dry_run") is True,
              f"{err!r} {appels[0].get('dry_run') if appels else None!r}")
        check(f"{mid} : ok True", res.get("ok") is True, f"{res.get('ok')!r} {res.get('raison')!r}")
        check(f"{mid} : extraction None", res.get("extraction", "absent") is None,
              repr(res.get("extraction", "absent"))[:80])
        check(f"{mid} : clé dry_run True", res.get("dry_run") is True, repr(res.get("dry_run")))
        est = res.get("estimation") if isinstance(res.get("estimation"), dict) else {}
        check(f"{mid} : estimation présente (celle de lire_dce)", est.get("cout_eur") == 0.5
              and est.get("modele") == ARGON, repr(res.get("estimation")))
        check(f"{mid} : mode 'document'", res.get("mode") == "document", repr(res.get("mode")))
        check(f"{mid} : rien n'est écrit ni archivé", fichiers_ecrits(mid) == [], str(fichiers_ecrits(mid)))
        check(f"{mid} : briefs_extraits inchangé", cles_briefs() == cles_avant
              and (lire_brief(mid) == ancien if avec_brief else lire_brief(mid) is None))
        check(f"{mid} : dossier du DCE inchangé", instantane(chemin) == avant)


def test_document_budget():
    mid = "T5-DOC-BUDGET"
    ecrire_marche(mid)
    chemin = creer_dce(E.REPERTOIRE_DCE, mid, docx=True, zip_=True)
    ancien = ancien_brief(mid)
    stockage.ecrire("briefs_extraits", mid, copy.deepcopy(ancien))
    avant = instantane(chemin)
    res, err, appels = traiter(mid, chemin, {}, scenario="budget")
    check("BudgetDepasseError de lire_dce remonte de traiter_marche",
          isinstance(err, budget.BudgetDepasseError), f"{type(err).__name__}: {err} / {res!r}"[:200])
    check("budget refusé : brief existant intact, rien d'archivé, aucun fichier",
          lire_brief(mid) == ancien and fichiers_ecrits(mid) == [], str(fichiers_ecrits(mid)))
    check("budget refusé : dossier du DCE inchangé", instantane(chemin) == avant)


# =============================================================================
def test_classique():
    mid = "T5-CLA-OK"
    ecrire_marche(mid)
    chemin = creer_dce(E.REPERTOIRE_DCE, mid)
    ancien = ancien_brief(mid)
    stockage.ecrire("briefs_extraits", mid, copy.deepcopy(ancien))
    cles_avant = cles_briefs()
    SCENARIO["cas"] = "ok"
    APPELS_LIRE.clear()
    APPELS_CLASSIQUE.clear()
    res, err = silencieux(E.traiter_marche, mid, chemin, copy.deepcopy(PDFS_CLASSIQUE), mode="classique")
    res = res if isinstance(res, dict) else {}
    check("classique : aucune exception", err is None, repr(err))
    check("classique : mode_document.lire_dce n'est PAS appelé", APPELS_LIRE == [], str(len(APPELS_LIRE)))
    check("classique : extraire_via_llm appelé une fois", len(APPELS_CLASSIQUE) == 1, str(len(APPELS_CLASSIQUE)))
    a, k = APPELS_CLASSIQUE[0] if APPELS_CLASSIQUE else ((), {})
    texte = a[0] if a else k.get("texte")
    contexte = a[1] if len(a) > 1 else k.get("contexte")
    check("classique : le texte des pdfs est transmis",
          isinstance(texte, str) and "Règlement de consultation de la commune de Test" in texte, repr(texte)[:120])
    check("classique : contexte dict contenant l'id",
          isinstance(contexte, dict) and any(v == mid for v in contexte.values()), repr(contexte)[:200])
    check("classique : ok True, mode 'classique' dans le résultat",
          res.get("ok") is True and res.get("mode") == "classique",
          f"ok={res.get('ok')!r} mode={res.get('mode')!r} erreur={res.get('erreur')!r} raison={res.get('raison')!r}")
    ext = res.get("extraction") if isinstance(res.get("extraction"), dict) else {}
    meta = ext.get("_meta") if isinstance(ext.get("_meta"), dict) else {}
    check("classique : extraction = résultat de extraire_via_llm", ext.get("synthese_marche") == "classique",
          repr(ext)[:200])
    check("classique : _meta.mode == 'classique'", meta.get("mode") == "classique", repr(meta.get("mode")))
    check("classique : _meta.modele == 'claude-sonnet-4-6'", meta.get("modele") == SONNET, repr(meta.get("modele")))
    check("classique : _meta.id_marche", meta.get("id_marche") == mid, repr(meta.get("id_marche")))
    check("classique : brief écrit dans briefs_extraits",
          (lire_brief(mid) or {}).get("synthese_marche") == "classique", repr(lire_brief(mid))[:200])
    copies = archives_de(mid)
    check("classique : l'ancien brief est archivé (copie identique)",
          len(copies) == 1 and json.loads(copies[0].read_text(encoding="utf-8")) == ancien,
          str([p.name for p in copies]))
    check("classique : briefs_extraits garde exactement les mêmes clés", cles_briefs() == cles_avant,
          str(sorted(cles_briefs() ^ cles_avant)))


# =============================================================================
APPELS_ESPION = []
ESPION = {"ecrit_brief": True}


def espion_traiter_marche(id_marche, dossier_dce, pdfs, dry_run=False, verbose=True, mode=None,
                          max_cout_par_dce=2.5, **autres):
    APPELS_ESPION.append({"id": id_marche, "dossier": dossier_dce, "pdfs": pdfs, "dry_run": dry_run,
                          "mode": mode, "max_cout_par_dce": max_cout_par_dce})
    extraction = {"synthese_marche": "espion",
                  "_meta": {"id_marche": id_marche, "type": "complet", "mode": mode, "modele": ARGON,
                            "cout_eur": 0.5, "date_generation": "2026-11-11T10:00:00+00:00"}}
    if ESPION["ecrit_brief"]:
        stockage.ecrire("briefs_extraits", id_marche, extraction)
    return {"ok": True, "statut": "ok", "extraction": extraction, "erreur": None, "raison": None, "mode": mode}


def ids_espion() -> list:
    return [a["id"] for a in APPELS_ESPION]


def test_main_options():
    E.traiter_marche = espion_traiter_marche
    racine = dossier / "dce_faux_scan"
    a_traiter = []
    for i in range(3):
        mid = f"T5-MAIN-FAUX-{i}"
        ecrire_marche(mid)
        a_traiter.append((mid, creer_dce(racine, mid), {}, "nouveau"))
    E._scanner_dossiers_dce = lambda *a, **k: list(a_traiter)
    try:
        APPELS_ESPION.clear()
        _, err = silencieux(E.main, [])
        check("main([]) : les 3 marchés sont traités", err is None and len(APPELS_ESPION) == 3,
              f"{err!r} {ids_espion()}")
        check("sans option : traiter_marche reçoit mode 'document'",
              bool(APPELS_ESPION) and all(a["mode"] == "document" for a in APPELS_ESPION),
              str([a["mode"] for a in APPELS_ESPION]))
        check("sans option : traiter_marche reçoit max_cout_par_dce 2.5",
              bool(APPELS_ESPION) and all(a["max_cout_par_dce"] == 2.5 for a in APPELS_ESPION),
              str([a["max_cout_par_dce"] for a in APPELS_ESPION]))

        APPELS_ESPION.clear()
        _, err = silencieux(E.main, ["--mode", "classique", "--max-cout-par-dce", "4"])
        check("--mode classique --max-cout-par-dce 4 : sans exception, marchés traités",
              err is None and len(APPELS_ESPION) == 3, f"{err!r} {ids_espion()}")
        check("--mode classique transmis", bool(APPELS_ESPION)
              and all(a["mode"] == "classique" for a in APPELS_ESPION), str([a["mode"] for a in APPELS_ESPION]))
        check("--max-cout-par-dce 4 transmis en 4.0",
              bool(APPELS_ESPION) and all(a["max_cout_par_dce"] == 4.0
                                          and isinstance(a["max_cout_par_dce"], float) for a in APPELS_ESPION),
              str([a["max_cout_par_dce"] for a in APPELS_ESPION]))

        APPELS_ESPION.clear()
        _, err = silencieux(E.main, ["--mode", "document", "--max-cout-par-dce", "0.75", "--max-cout", "50"])
        check("--mode document explicite, --max-cout-par-dce 0.75 transmis",
              err is None and len(APPELS_ESPION) == 3
              and all(a["mode"] == "document" and a["max_cout_par_dce"] == 0.75 for a in APPELS_ESPION),
              f"{err!r} {[(a['mode'], a['max_cout_par_dce']) for a in APPELS_ESPION]}")

        APPELS_ESPION.clear()
        _, err = silencieux(E.main, ["--mode", "inconnu"])
        check("--mode inconnu : argparse sort en erreur (SystemExit 2)",
              isinstance(err, SystemExit) and err.code == 2, repr(err))
        check("--mode inconnu : aucun marché traité", APPELS_ESPION == [], str(ids_espion()))
        _, err = silencieux(E.main, ["--mode", ""])
        check("--mode vide : SystemExit 2", isinstance(err, SystemExit) and err.code == 2, repr(err))
        _, err = silencieux(E.main, ["--max-cout-par-dce", "beaucoup"])
        check("--max-cout-par-dce non numérique : SystemExit 2, rien traité",
              isinstance(err, SystemExit) and err.code == 2 and APPELS_ESPION == [], f"{err!r} {ids_espion()}")

        APPELS_ESPION.clear()
        _, err = silencieux(E.main, ["--max-cout", "0"])
        check("--max-cout 0 en mode document : aucun marché traité", err is None and APPELS_ESPION == [],
              f"{err!r} {ids_espion()}")
    finally:
        E._scanner_dossiers_dce = SCANNER_REEL


def test_main_dossiers():
    """Vrai scan des dossiers de E.REPERTOIRE_DCE, traiter_marche espionné."""
    E.traiter_marche = espion_traiter_marche
    E._scanner_dossiers_dce = SCANNER_REEL
    racine = dossier / "dce_main"
    dce_avant, E.REPERTOIRE_DCE = E.REPERTOIRE_DCE, str(racine)
    try:
        for mid in ("T5-MAIN-DOCX", "T5-MAIN-ZIP", "T5-MAIN-VIDE"):
            ecrire_marche(mid)
        chemin_docx = creer_dce(racine, "T5-MAIN-DOCX", docx=True)
        creer_dce(racine, "T5-MAIN-ZIP", docx=True, zip_=True)
        creer_dce(racine, "T5-MAIN-VIDE", docx=False)
        avant = instantane(racine)

        APPELS_ESPION.clear()
        _, err = silencieux(E.main, [])
        check("main([]) : sans exception", err is None, repr(err))
        check("dossier avec seulement un .docx (aucun PDF) : transmis à traiter_marche",
              "T5-MAIN-DOCX" in ids_espion(), str(ids_espion()))
        check("dossier .zip + .docx (aucun PDF) : transmis à traiter_marche",
              "T5-MAIN-ZIP" in ids_espion(), str(ids_espion()))
        check("dossier vide : pas traité", "T5-MAIN-VIDE" not in ids_espion(), str(ids_espion()))
        check("chaque marché traité une seule fois", sorted(ids_espion()) == ["T5-MAIN-DOCX", "T5-MAIN-ZIP"],
              str(ids_espion()))
        recu = next((a for a in APPELS_ESPION if a["id"] == "T5-MAIN-DOCX"), {})
        check("traiter_marche reçoit le dossier du marché",
              recu.get("dossier") is not None
              and os.path.normcase(os.path.abspath(str(recu.get("dossier")))) == os.path.normcase(os.path.abspath(chemin_docx)),
              repr(recu.get("dossier")))
        check("traiter_marche reçoit mode 'document' et 2.5",
              bool(APPELS_ESPION) and all(a["mode"] == "document" and a["max_cout_par_dce"] == 2.5
                                          for a in APPELS_ESPION),
              str([(a["mode"], a["max_cout_par_dce"]) for a in APPELS_ESPION]))
        check("main ne modifie pas les dossiers de REPERTOIRE_DCE (zip non dézippé)",
              instantane(racine) == avant, f"{avant} → {instantane(racine)}")
        check("état d'extraction écrit dans FICHIER_ETAT", os.path.isfile(E.FICHIER_ETAT))

        APPELS_ESPION.clear()
        _, err = silencieux(E.main, [])
        check("deuxième passe sans --force : aucun marché retraité", err is None and APPELS_ESPION == [],
              f"{err!r} {ids_espion()}")

        APPELS_ESPION.clear()
        _, err = silencieux(E.main, ["--marche", "T5-MAIN-DOCX"])
        check("--marche sur un marché déjà extrait, sans --force : pas retraité",
              err is None and APPELS_ESPION == [], f"{err!r} {ids_espion()}")

        APPELS_ESPION.clear()
        _, err = silencieux(E.main, ["--force"])
        check("--force : les marchés déjà extraits sont retraités",
              err is None and sorted(ids_espion()) == ["T5-MAIN-DOCX", "T5-MAIN-ZIP"], f"{err!r} {ids_espion()}")
        check("--force : le dossier vide n'est toujours pas traité", "T5-MAIN-VIDE" not in ids_espion())
        check("--force : dossiers de REPERTOIRE_DCE inchangés", instantane(racine) == avant)

        APPELS_ESPION.clear()
        _, err = silencieux(E.main, [])
        check("après --force : de nouveau à jour, rien retraité", err is None and APPELS_ESPION == [],
              f"{err!r} {ids_espion()}")

        # Signature différente (une pièce de plus, pas un PDF) : seul ce marché est retraité.
        with open(os.path.join(chemin_docx, "RC_rectificatif.docx"), "wb") as f:
            f.write(b"rectificatif " * 20)
        APPELS_ESPION.clear()
        _, err = silencieux(E.main, [])
        check("une pièce ajoutée (signature différente) : ce marché seul est retraité, sans --force",
              err is None and ids_espion() == ["T5-MAIN-DOCX"], f"{err!r} {ids_espion()}")
    finally:
        E.REPERTOIRE_DCE = dce_avant


# =============================================================================
def test_pipeline():
    lances = []
    P._executer_script = lambda script, args=None: lances.append((Path(script).name, list(args or []))) or True
    base = ["--skip-recup", "--skip-download", "--skip-dedies"]

    def args_extraire(argv):
        lances.clear()
        _, err = silencieux(P.main, argv)
        return next((a for s, a in lances if s == "extraire.py"), None), err

    def plafond(a):
        if not a or "--max-cout" not in a or a.index("--max-cout") + 1 >= len(a):
            return None
        return float(a[a.index("--max-cout") + 1])

    a, err = args_extraire(base)
    check("pipeline : se termine sans exception, étape 6 lancée", err is None and a is not None, f"{err!r} {lances}")
    check("étape 6 lancée SANS option --mode (le défaut de extraire s'applique)",
          a is not None and not any(str(x).startswith("--mode") for x in a), str(a))
    check("étape 6 : ni 'classique' ni 'document' dans les arguments",
          a is not None and "classique" not in a and "document" not in a, str(a))
    check("défaut : --max-cout 5.0 transmis à extraire", plafond(a) == 5.0, str(a))

    a, err = args_extraire(base + ["--max-cout-extraction", "3.5"])
    check("--max-cout-extraction 3.5 transmis tel quel", err is None and plafond(a) == 3.5, f"{err!r} {a}")
    check("--max-cout-extraction 3.5 : toujours sans --mode",
          a is not None and not any(str(x).startswith("--mode") for x in a), str(a))
    a, err = args_extraire(base + ["--max-cout-extraction", "0"])
    check("--max-cout-extraction 0 transmis (0 compris, pas remplacé par 5)", err is None and plafond(a) == 0.0,
          f"{err!r} {a}")
    a, err = args_extraire(base + ["--max-cout-extraction", "1000000"])
    check("--max-cout-extraction très grand transmis tel quel", err is None and plafond(a) == 1000000.0,
          f"{err!r} {a}")
    a, err = args_extraire(base + ["--force"])
    check("--force : l'étape 6 reste plafonnée à 5.0 et sans --mode",
          err is None and plafond(a) == 5.0 and not any(str(x).startswith("--mode") for x in a), f"{err!r} {a}")
    a, err = args_extraire(base + ["--skip-llm"])
    check("--skip-llm : étape 6 non lancée", err is None and a is None, f"{err!r} {a}")


# =============================================================================
def test_rattrapage():
    time.sleep = lambda *_a, **_k: None
    sys.path.insert(0, str(chemins.RACINE_DEPOT / "scripts" / "maintenance"))
    import rattrapage_btp_octobre as RB

    E.traiter_marche = espion_traiter_marche
    E._scanner_dossiers_dce = SCANNER_REEL
    ESPION["ecrit_brief"] = False       # les marchés restent à briefer d'un lancement à l'autre
    racine = dossier / "dce_rattrapage"
    dce_avant, E.REPERTOIRE_DCE = E.REPERTOIRE_DCE, str(racine)
    ids = ["T5-RAT-A", "T5-RAT-B", "T5-RAT-C"]

    def lancer(argv):
        r = silencieux(RB.main, argv)
        stockage.invalider_cache()
        return r

    try:
        for i, mid in enumerate(ids):
            ecrire_marche(mid, date_publication=f"2026-10-1{i}", date_limite_depot=J(20 + i))
            creer_dce(racine, mid, docx=True, zip_=(i == 0))     # aucun PDF nulle part
        stockage.invalider_cache()
        _, err = lancer(["cibles"])
        check("cibles : fichier d'ids écrit dans le dossier temporaire",
              err is None and RB.fichier_ids().exists() and RB.fichier_ids().parent == dossier, repr(err))
        a_briefer = RB.selectionner_briefs(RB.lire_ids(), stockage.charger("marches"),
                                           stockage.charger("briefs_extraits") or {})
        check("précondition : les 3 marchés à DCE complet sans brief sont à briefer",
              set(ids) <= set(a_briefer), str(a_briefer))
        avant = instantane(racine)

        APPELS_ESPION.clear()
        _, err = lancer(["briefs", "--max-cout", "5", "--max", "5"])
        check("briefs --max-cout 5 --max 5 : sans exception", err is None, repr(err))
        check("traiter_marche appelé pour chaque marché à briefer, même sans aucun PDF dans le dossier",
              set(ids) <= set(ids_espion()) and set(ids_espion()) == set(a_briefer[:5]),
              f"{ids_espion()} / attendu {a_briefer[:5]}")
        check("chaque marché une seule fois", len(ids_espion()) == len(set(ids_espion())), str(ids_espion()))
        check("défaut : mode 'document' transmis",
              bool(APPELS_ESPION) and all(a["mode"] == "document" for a in APPELS_ESPION),
              str([a["mode"] for a in APPELS_ESPION]))
        check("défaut : max_cout_par_dce 2.5 transmis",
              bool(APPELS_ESPION) and all(a["max_cout_par_dce"] == 2.5 for a in APPELS_ESPION),
              str([a["max_cout_par_dce"] for a in APPELS_ESPION]))
        check("rien n'est écrit dans les dossiers des DCE (zip non dézippé)", instantane(racine) == avant,
              f"{avant} → {instantane(racine)}")

        APPELS_ESPION.clear()
        _, err = lancer(["briefs", "--max-cout", "5", "--max", "5", "--max-cout-par-dce", "4"])
        check("--max-cout-par-dce 4 transmis en 4.0 (mode document)",
              err is None and bool(APPELS_ESPION)
              and all(a["max_cout_par_dce"] == 4.0 and a["mode"] == "document" for a in APPELS_ESPION),
              f"{err!r} {[(a['mode'], a['max_cout_par_dce']) for a in APPELS_ESPION]}")

        APPELS_ESPION.clear()
        _, err = lancer(["briefs", "--max-cout", "0", "--max", "5"])
        check("--max-cout 0 en mode document : traiter_marche jamais appelé", err is None and APPELS_ESPION == [],
              f"{err!r} {ids_espion()}")

        APPELS_ESPION.clear()
        _, err = lancer(["briefs", "--max-cout", "5", "--max", "5", "--mode", "inconnu"])
        check("--mode inconnu : SystemExit 2, rien traité",
              isinstance(err, SystemExit) and err.code == 2 and APPELS_ESPION == [], f"{err!r} {ids_espion()}")
        check("toujours rien d'écrit dans les dossiers des DCE", instantane(racine) == avant)

        # Mode classique : il lui faut du texte de PDF ; lecture et dézippage remplacés.
        from tendia.analyse import pdf_extract
        extraire_dossier_reel, dezipper_reel = pdf_extract.extraire_dossier, E._dezipper_dossier
        pdf_extract.extraire_dossier = lambda *a, **k: {"rc.pdf": {
            "hash": "h-rat", "taille_chars": 1300, "texte": "Règlement de consultation " * 50}}   # forme réelle de pdf_extract
        E._dezipper_dossier = lambda *a, **k: 0
        try:
            APPELS_ESPION.clear()
            _, err = lancer(["briefs", "--max-cout", "5", "--max", "5", "--mode", "classique"])
            check("--mode classique : traiter_marche appelé pour les 3 marchés",
                  err is None and set(ids) <= set(ids_espion()), f"{err!r} {ids_espion()}")
            check("--mode classique : mode 'classique' transmis",
                  bool(APPELS_ESPION) and all(a["mode"] == "classique" for a in APPELS_ESPION),
                  str([a["mode"] for a in APPELS_ESPION]))
        finally:
            pdf_extract.extraire_dossier, E._dezipper_dossier = extraire_dossier_reel, dezipper_reel
    finally:
        E.REPERTOIRE_DCE = dce_avant
        ESPION["ecrit_brief"] = True


# =============================================================================
def test_hors_ligne():
    check("aucun appel fournisseur (Gemini, Claude) pendant tout le test", APPELS_FOURNISSEUR == [],
          str(len(APPELS_FOURNISSEUR)))
    check("le vrai mode_document.lire_dce n'a jamais été rebranché", mode_document.lire_dce is faux_lire_dce)
    check("rien n'a été écrit dans le vrai dossier d'archive par ce test (redirection en place)",
          Path(E.REPERTOIRE_ARCHIVE_BRIEFS) == ARCH)


section("constantes et signatures", test_constantes)
section("archiver_brief_existant", test_archiver_brief_existant)
section("signature_dossier", test_signature_dossier)
section("traiter_marche, mode document : cas nominal", test_document_nominal)
section("traiter_marche, mode document : DCE sans aucun PDF", test_document_sans_pdf)
section("traiter_marche, mode document : brief existant archivé avant écrasement", test_document_brief_existant)
section("traiter_marche, mode document : DCE sauté et échecs", test_document_saute_et_echecs)
section("traiter_marche, mode document : plafond par DCE transmis", test_document_plafond_transmis)
section("traiter_marche, mode document : dry_run", test_document_dry_run)
section("traiter_marche, mode document : BudgetDepasseError", test_document_budget)
section("traiter_marche, mode classique", test_classique)
section("extraire.main : --mode et --max-cout-par-dce", test_main_options)
section("extraire.main : dossiers sans PDF, dossier vide, état", test_main_dossiers)
section("pipeline.main : étape 6", test_pipeline)
section("rattrapage_btp_octobre briefs : --mode et --max-cout-par-dce", test_rattrapage)
section("hors ligne", test_hors_ligne)

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
