# -*- coding: utf-8 -*-
"""
tests/test_pieces.py
--------------------
Tests HORS-LIGNE (chantier 2, étape 4) de tendia.analyse.pieces : inventaire d'un DCE
(parcours récursif, ZIP imbriqués, doublons, plans, formats non gérés, conversion
Office), texte page par page, typage des pièces.

  - sorties sous P.DIR_PIECES / <id> ; le dossier source n'est JAMAIS modifié
    (empreinte de tests/fixtures/dce_mixte avant / après) ;
  - dce_mixte : 4 pièces retenues (RC, CCAP, CCTP, BPU), 2 doublons du RC,
    2 plan_ignore, 2 format_non_gere ; .7z : format_non_gere ;
  - tri des pièces par type (RC, CCAP, CCTP, BPU_DPGF_DQE, AE, annexe) puis nom ;
  - _inventaire.json relu tel quel au 2e appel, refait avec force=True ;
  - texte_piece (marqueurs « \\n[[Page N]]\\n » / « \\n[[Feuille NOM]]\\n »), texte_page ;
  - typer_piece (nom de fichier, puis début du contenu) ;
  - conversion Office/LibreOffice : testée si un convertisseur est présent, sinon
    « SAUTÉ » ; sans convertisseur : echec_conversion, rien n'est levé.

Base temporaire, P.DIR_PIECES temporaire, réseau coupé (socket), aucun appel LLM.

Lancement : python tests/test_pieces.py
"""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import shutil
import socket
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from base_temporaire import isoler_stockage
dossier = isoler_stockage()


def _reseau_interdit(*_a, **_k):
    raise OSError("réseau interdit dans tests/test_pieces.py")


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


FIXTURES = Path(__file__).resolve().parent / "fixtures"
MIXTE = FIXTURES / "dce_mixte"
CONVERSION = FIXTURES / "dce_conversion"

from tendia.core.chemins import DATA

try:
    from tendia.analyse import pieces as P
except Exception as e:  # noqa: BLE001
    check("import tendia.analyse.pieces", False, f"{type(e).__name__}: {e}")
    terminer()

# --- P.DIR_PIECES : valeur de prod vérifiée, puis redirigée AVANT tout appel ---
DIR_PIECES_PROD = getattr(P, "DIR_PIECES", None)
TMP = Path(tempfile.mkdtemp(prefix="tendia_test_pieces_"))


def rediriger(nom):
    d = TMP / nom
    d.mkdir(parents=True, exist_ok=True)
    P.DIR_PIECES = d
    return d


DIR_TEST = rediriger("pieces")

MID = "TEST-PIECES-MIXTE-ETAPE4"
TYPES = ("RC", "CCAP", "CCTP", "BPU_DPGF_DQE", "AE", "annexe")
CLES_INVENTAIRE = {"marche_id", "pieces", "ecartes", "doublons", "chars_total",
                   "nb_pages_total", "erreurs"}
CLES_PIECE = {"nom", "chemin_original", "chemin_lu", "type", "unite", "nb_pages", "chars",
              "lecture_visuelle", "parties_pdf", "texte_fichier"}


# --- Outils ------------------------------------------------------------------
def appeler(fonction, *args, **kwargs):
    """(résultat, exception) ; la sortie console de la fonction est absorbée."""
    tampon = io.StringIO()
    try:
        with contextlib.redirect_stdout(tampon), contextlib.redirect_stderr(tampon):
            return fonction(*args, **kwargs), None
    except Exception as e:  # noqa: BLE001
        return None, e


def empreinte(racine: Path) -> dict:
    """Chemin relatif → sha256 (ou « <dossier> ») : sert à prouver que la source est intacte."""
    etat = {}
    for p in sorted(racine.rglob("*")):
        rel = p.relative_to(racine).as_posix()
        etat[rel] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "<dossier>"
    return etat


def base(nom) -> str:
    """Nom de fichier nu (une pièce sortie d'un zip ou d'un sous-dossier peut porter un chemin relatif)."""
    return str(nom or "").replace("\\", "/").rsplit("/", 1)[-1]


def norm(s) -> str:
    return " ".join(str(s or "").lower().split())


def piece(inv, nom):
    for p in (inv or {}).get("pieces") or []:
        if base(p.get("nom")) == nom:
            return p
    return None


def ecarte(inv, nom):
    for e in (inv or {}).get("ecartes") or []:
        if base(e.get("nom")) == nom:
            return e
    return None


def sous(racine: Path, chemin) -> bool:
    try:
        Path(str(chemin)).resolve().relative_to(Path(racine).resolve())
        return True
    except (ValueError, OSError):
        return False


def charger_generateur():
    """Fonctions pdf() / remplir() du générateur de fixtures (main() n'est pas exécuté)."""
    spec = importlib.util.spec_from_file_location("generer_dce_mixte_pour_tests",
                                                  FIXTURES / "generer_dce_mixte.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EMPREINTE_MIXTE = empreinte(MIXTE)
EMPREINTE_CONVERSION = empreinte(CONVERSION)
INV = {}


# =============================================================================
def test_dir_pieces():
    check("P.DIR_PIECES (prod) == DATA / 'pieces'",
          DIR_PIECES_PROD is not None and Path(DIR_PIECES_PROD) == Path(DATA) / "pieces",
          repr(DIR_PIECES_PROD))
    check("P.DIR_PIECES est un Path", isinstance(DIR_PIECES_PROD, Path), type(DIR_PIECES_PROD).__name__)
    check("P.DIR_PIECES redirigé vers un dossier temporaire pour les tests",
          Path(P.DIR_PIECES) == DIR_TEST and not sous(DATA, P.DIR_PIECES), repr(P.DIR_PIECES))
    check("fixtures présentes (dce_mixte : 8 fichiers)",
          sum(1 for v in EMPREINTE_MIXTE.values() if v != "<dossier>") == 8, str(sorted(EMPREINTE_MIXTE)))


# =============================================================================
def test_inventaire_mixte():
    global INV
    inv, exc = appeler(P.inventorier, MID, str(MIXTE), verbose=False)
    check("inventorier(dce_mixte) : aucune exception", exc is None, repr(exc))
    check("inventorier rend un dict", isinstance(inv, dict), type(inv).__name__)
    inv = inv if isinstance(inv, dict) else {}
    INV = inv
    check("clés de l'inventaire présentes", CLES_INVENTAIRE <= set(inv),
          f"manquantes : {sorted(CLES_INVENTAIRE - set(inv))}")
    check("marche_id repris", inv.get("marche_id") == MID, repr(inv.get("marche_id")))

    pieces = inv.get("pieces") or []
    noms = [base(p.get("nom")) for p in pieces]
    check("4 pièces retenues", len(pieces) == 4, str(noms))
    check("pièces triées par type : RC.pdf, CCAP.pdf, CCTP.pdf, BPU.xlsx",
          noms == ["RC.pdf", "CCAP.pdf", "CCTP.pdf", "BPU.xlsx"], str(noms))
    check("types : RC, CCAP, CCTP, BPU_DPGF_DQE",
          [p.get("type") for p in pieces] == ["RC", "CCAP", "CCTP", "BPU_DPGF_DQE"],
          str([p.get("type") for p in pieces]))
    check("la pièce RC s'appelle exactement « RC.pdf » (l'original, pas une copie)",
          bool(pieces) and pieces[0].get("nom") == "RC.pdf", repr(pieces[0].get("nom") if pieces else None))
    check("une seule pièce de type RC", sum(1 for p in pieces if p.get("type") == "RC") == 1)
    check("chaque pièce porte toutes les clés du contrat",
          bool(pieces) and all(CLES_PIECE <= set(p) for p in pieces),
          str([sorted(CLES_PIECE - set(p)) for p in pieces]))
    check("unité : page pour les PDF, feuille pour BPU.xlsx",
          [p.get("unite") for p in pieces] == ["page", "page", "page", "feuille"],
          str([p.get("unite") for p in pieces]))
    check("nb_pages : RC 2, CCAP 1, CCTP 1",
          [p.get("nb_pages") for p in pieces[:3]] == [2, 1, 1], str([p.get("nb_pages") for p in pieces]))
    check("chars > 0 pour chaque pièce",
          bool(pieces) and all(isinstance(p.get("chars"), int) and p.get("chars") > 0 for p in pieces),
          str([p.get("chars") for p in pieces]))
    rc = piece(inv, "RC.pdf") or {}
    check("RC.pdf : plus de 400 caractères (2 pages de plus de 200 caractères)",
          (rc.get("chars") or 0) > 400, repr(rc.get("chars")))
    check("lecture_visuelle False pour des pièces qui ont du texte",
          bool(pieces) and all(p.get("lecture_visuelle") is False for p in pieces),
          str([p.get("lecture_visuelle") for p in pieces]))
    check("parties_pdf est une liste", bool(pieces) and all(isinstance(p.get("parties_pdf"), list) for p in pieces),
          str([type(p.get("parties_pdf")).__name__ for p in pieces]))
    check("types tous dans la liste fermée", all(p.get("type") in TYPES for p in pieces))

    check("chars_total = somme des chars des pièces retenues",
          bool(pieces) and inv.get("chars_total") == sum(p.get("chars") or 0 for p in pieces),
          f"{inv.get('chars_total')!r} / {sum(p.get('chars') or 0 for p in pieces)}")
    check("nb_pages_total = 4 (pièces en pages seulement : 2 + 1 + 1, BPU en feuilles exclu)",
          inv.get("nb_pages_total") == 4, repr(inv.get("nb_pages_total")))
    check("erreurs est une liste", isinstance(inv.get("erreurs"), list), repr(inv.get("erreurs")))

    # --- écartés ---
    ecartes = inv.get("ecartes") or []
    check("4 fichiers écartés", len(ecartes) == 4, str([(base(e.get("nom")), e.get("statut")) for e in ecartes]))
    check("chaque écarté : nom, statut, detail",
          bool(ecartes) and all({"nom", "statut", "detail"} <= set(e) for e in ecartes), str(ecartes))
    for nom, statut in (("plan_masse.pdf", "plan_ignore"), ("photo_chantier.jpg", "plan_ignore"),
                        ("pieces_complementaires.rar", "format_non_gere"),
                        ("maquette.xyz", "format_non_gere")):
        e = ecarte(inv, nom)
        check(f"{nom} : écarté, statut {statut}", e is not None and e.get("statut") == statut,
              repr(e))
        check(f"{nom} : absent des pièces retenues", piece(inv, nom) is None)
    check("statuts des écartés dans la liste fermée",
          all(e.get("statut") in ("plan_ignore", "format_non_gere", "echec_conversion") for e in ecartes),
          str({e.get("statut") for e in ecartes}))
    check("aucun echec_conversion sur dce_mixte (rien à convertir)",
          not any(e.get("statut") == "echec_conversion" for e in ecartes))
    check("les .zip ne sont ni des pièces ni des écartés (ils sont décompressés)",
          not any(base(x.get("nom")).endswith(".zip") for x in pieces + ecartes),
          str([base(x.get("nom")) for x in pieces + ecartes]))

    # --- doublons ---
    doublons = inv.get("doublons") or []
    check("2 doublons signalés", len(doublons) == 2, str(doublons))
    check("doublons = RC_copie.pdf (sous-dossier) et RC_copie_zip.pdf (zip)",
          sorted(base(d.get("nom")) for d in doublons) == ["RC_copie.pdf", "RC_copie_zip.pdf"],
          str(doublons))
    check("doublon_de = RC.pdf pour les deux",
          len(doublons) == 2 and all(base(d.get("doublon_de")) == "RC.pdf" for d in doublons),
          str(doublons))
    check("les doublons ne sont ni des pièces ni des écartés",
          all(piece(inv, n) is None and ecarte(inv, n) is None for n in ("RC_copie.pdf", "RC_copie_zip.pdf")))

    # --- sorties ---
    sortie = DIR_TEST / MID
    check("sorties sous P.DIR_PIECES / <id>", sortie.is_dir(), str(sortie))
    extraits = {p.name for p in sortie.rglob("*") if p.is_file()} if sortie.is_dir() else set()
    check("ZIP décompressé sous P.DIR_PIECES / <id> (CCAP.pdf)", "CCAP.pdf" in extraits, str(sorted(extraits)))
    check("ZIP imbriqué décompressé sous P.DIR_PIECES / <id> (CCTP.pdf)", "CCTP.pdf" in extraits,
          str(sorted(extraits)))
    for nom in ("CCAP.pdf", "CCTP.pdf"):
        p = piece(inv, nom) or {}
        check(f"{nom} : chemin_lu sous P.DIR_PIECES / <id> et fichier présent",
              bool(p.get("chemin_lu")) and sous(sortie, p.get("chemin_lu"))
              and Path(str(p.get("chemin_lu"))).is_file(), repr(p.get("chemin_lu")))
    check("rien d'écrit dans DATA / 'pieces' / <id> (prod)", not (Path(DATA) / "pieces" / MID).exists())
    check("dossier source intact après l'inventaire (empreinte identique, aucun fichier ajouté)",
          empreinte(MIXTE) == EMPREINTE_MIXTE,
          str(sorted(set(empreinte(MIXTE)) ^ set(EMPREINTE_MIXTE))))


# =============================================================================
def test_inventaire_json():
    fichier = DIR_TEST / MID / "_inventaire.json"
    check("_inventaire.json écrit sous P.DIR_PIECES / <id>", fichier.is_file(), str(fichier))
    if not fichier.is_file():
        return
    sur_disque = json.loads(fichier.read_text(encoding="utf-8"))
    check("_inventaire.json = résultat rendu", sur_disque == json.loads(json.dumps(INV)),
          f"clés disque {sorted(sur_disque)}")

    inv2, exc = appeler(P.inventorier, MID, str(MIXTE), verbose=False)
    check("2e appel : même résultat", exc is None and inv2 is not None
          and json.loads(json.dumps(inv2)) == sur_disque, repr(exc))

    # Un témoin posé dans le fichier prouve que le 2e appel relit, et que force=True refait.
    temoin = dict(sur_disque)
    temoin["_temoin"] = "relu"
    fichier.write_text(json.dumps(temoin, ensure_ascii=False), encoding="utf-8")
    inv3, exc = appeler(P.inventorier, MID, str(MIXTE), verbose=False)
    check("2e appel sans force : _inventaire.json relu tel quel",
          exc is None and isinstance(inv3, dict) and inv3.get("_temoin") == "relu", f"{exc!r}")
    inv4, exc = appeler(P.inventorier, MID, str(MIXTE), verbose=False, force=True)
    check("force=True : inventaire refait (témoin disparu du résultat)",
          exc is None and isinstance(inv4, dict) and "_temoin" not in inv4, f"{exc!r}")
    check("force=True : toujours 4 pièces, 4 écartés, 2 doublons",
          isinstance(inv4, dict) and len(inv4.get("pieces") or []) == 4
          and len(inv4.get("ecartes") or []) == 4 and len(inv4.get("doublons") or []) == 2,
          repr({k: len(v) for k, v in (inv4 or {}).items() if isinstance(v, list)}))
    apres = json.loads(fichier.read_text(encoding="utf-8"))
    check("force=True : _inventaire.json réécrit (témoin disparu du fichier)", "_temoin" not in apres)
    check("force=True : même contenu qu'au premier passage",
          isinstance(inv4, dict) and json.loads(json.dumps(inv4)) == sur_disque)
    check("dossier source intact après les relectures", empreinte(MIXTE) == EMPREINTE_MIXTE)


# =============================================================================
def test_texte_piece():
    rc, bpu = piece(INV, "RC.pdf"), piece(INV, "BPU.xlsx")
    check("pièces RC.pdf et BPU.xlsx disponibles", rc is not None and bpu is not None)
    if rc is None or bpu is None:
        return
    copie = copy.deepcopy(rc)
    t, exc = appeler(P.texte_piece, rc)
    check("texte_piece(RC) rend une chaîne", exc is None and isinstance(t, str), f"{exc!r}")
    t = t or ""
    check("marqueur exact « \\n[[Page 1]]\\n »", "\n[[Page 1]]\n" in t, repr(t[:60]))
    check("marqueur exact « \\n[[Page 2]]\\n »", "\n[[Page 2]]\n" in t)
    check("un marqueur par page : 2 marqueurs, pas de page 0 ni 3",
          t.count("[[Page ") == 2 and "[[Page 0]]" not in t and "[[Page 3]]" not in t,
          str(t.count("[[Page ")))
    p1, p2 = t.find("\n[[Page 1]]\n"), t.find("\n[[Page 2]]\n")
    check("page 1 avant page 2", 0 <= p1 < p2, f"{p1} / {p2}")
    avant, apres = norm(t[:p2]), norm(t[p2:])
    check("texte de la page 1 après son marqueur (« RÈGLEMENT DE LA CONSULTATION »)",
          "règlement de la consultation" in avant and "règlement de la consultation" not in apres)
    check("texte de la page 2 après son marqueur (critères, date limite, visite)",
          "prix des prestations 40 %, valeur technique 60 %" in apres
          and "date limite de remise des offres : 15 décembre 2026 à 12 h 00" in apres
          and "une visite du site est obligatoire" in apres and "date limite de remise" not in avant,
          repr(apres[:300]))
    check("texte_piece ne modifie pas la pièce", rc == copie)

    tb, exc = appeler(P.texte_piece, bpu)
    tb = tb or ""
    check("texte_piece(BPU) : marqueur exact « \\n[[Feuille BPU]]\\n »",
          exc is None and "\n[[Feuille BPU]]\n" in tb, f"{exc!r} {tb[:60]!r}")
    check("BPU : aucun marqueur de page", "[[Page " not in tb)
    check("BPU : contenu des cellules présent",
          "fourniture et pose de tuiles de terre cuite" in norm(tb) and "zinguerie" in norm(tb),
          repr(tb[:200]))
    for nom in ("CCAP.pdf", "CCTP.pdf"):
        tp, exc = appeler(P.texte_piece, piece(INV, nom))
        check(f"texte_piece({nom}) : un seul marqueur de page, texte non vide",
              exc is None and isinstance(tp, str) and tp.count("[[Page ") == 1
              and "\n[[Page 1]]\n" in tp and len(tp) > 200, f"{exc!r}")
    tc, _ = appeler(P.texte_piece, piece(INV, "CCAP.pdf"))
    check("CCAP : texte lu depuis le zip (« Retenue de garantie »)", "retenue de garantie" in norm(tc))
    tt, _ = appeler(P.texte_piece, piece(INV, "CCTP.pdf"))
    check("CCTP : texte lu depuis le zip imbriqué (« Lot unique »)", "lot unique" in norm(tt))


# =============================================================================
def test_texte_page():
    rc, bpu = piece(INV, "RC.pdf"), piece(INV, "BPU.xlsx")
    check("pièces RC.pdf et BPU.xlsx disponibles", rc is not None and bpu is not None)
    if rc is None or bpu is None:
        return
    p1, e1 = appeler(P.texte_page, rc, 1)
    p2, e2 = appeler(P.texte_page, rc, 2)
    check("texte_page(RC, 1) : page 1 seulement",
          e1 is None and "règlement de la consultation" in norm(p1) and "date limite" not in norm(p1),
          f"{e1!r} {str(p1)[:80]!r}")
    check("texte_page(RC, 2) : page 2 seulement",
          e2 is None and "valeur technique 60 %" in norm(p2)
          and "15 décembre 2026 à 12 h 00" in norm(p2)
          and "règlement de la consultation" not in norm(p2), f"{e2!r} {str(p2)[:80]!r}")
    ps, es = appeler(P.texte_page, rc, "2")
    check("page en chaîne \"2\" = page 2", es is None and ps == p2 and bool(ps), f"{es!r}")
    tout, _ = appeler(P.texte_piece, rc)
    check("le texte de chaque page est contenu dans texte_piece",
          bool(p1) and bool(p2) and norm(p1) in norm(tout) and norm(p2) in norm(tout))
    for page in (3, 0, -1, 10**9, None, "", "abc", "99"):
        v, exc = appeler(P.texte_page, rc, page)
        check(f"texte_page(RC, {page!r}) → \"\" (page inexistante), sans exception",
              exc is None and v == "", f"{v!r:.60} {exc!r}")
    f, exc = appeler(P.texte_page, bpu, "BPU")
    check("texte_page(BPU, 'BPU') : contenu de la feuille",
          exc is None and "dépose de la couverture existante" in norm(f), f"{exc!r} {str(f)[:80]!r}")
    for page in ("Inexistante", None, ""):
        v, exc = appeler(P.texte_page, bpu, page)
        check(f"texte_page(BPU, {page!r}) → \"\" (feuille inexistante)", exc is None and v == "",
              f"{v!r:.60} {exc!r}")
    v, exc = appeler(P.texte_page, piece(INV, "CCAP.pdf"), 2)
    check("texte_page(CCAP, 2) → \"\" (pièce d'une seule page)", exc is None and v == "", f"{exc!r}")


# =============================================================================
def test_typer_piece():
    cas = (
        ("RC.pdf", "", "RC"),
        ("03_CCTP_lot2.pdf", "", "CCTP"),
        ("DPGF lot 1.xlsx", "", "BPU_DPGF_DQE"),
        ("Acte d'engagement.docx", "", "AE"),
        ("notice.pdf", "RÈGLEMENT DE LA CONSULTATION\nCommune de Fixture-sur-Test", "RC"),
        ("notice.pdf", "", "annexe"),
        ("CCAP.pdf", "", "CCAP"),
        ("CCTP.pdf", "", "CCTP"),
        ("BPU.xlsx", "", "BPU_DPGF_DQE"),
        ("AE.docx", "", "AE"),
        ("DQE.xlsx", "", "BPU_DPGF_DQE"),
    )
    for nom, debut, attendu in cas:
        v, exc = appeler(P.typer_piece, nom, debut)
        suffixe = " + contenu RC" if debut else ""
        check(f"typer_piece({nom!r}{suffixe}) → {attendu}", exc is None and v == attendu, f"{v!r} {exc!r}")
    v, exc = appeler(P.typer_piece, "notice.pdf")
    check("debut_texte optionnel : typer_piece('notice.pdf') → annexe", exc is None and v == "annexe",
          f"{v!r} {exc!r}")
    v, exc = appeler(P.typer_piece, "CCTP.pdf", "RÈGLEMENT DE LA CONSULTATION")
    check("le nom de fichier prime sur le contenu (CCTP.pdf au contenu de RC → CCTP)",
          exc is None and v == "CCTP", f"{v!r} {exc!r}")
    v, exc = appeler(P.typer_piece, "notice.pdf", "Notice de sécurité du chantier, sans titre de pièce.")
    check("contenu sans indice → annexe", exc is None and v == "annexe", f"{v!r} {exc!r}")
    v, exc = appeler(P.typer_piece, "", "")
    check("nom vide, contenu vide → annexe, sans exception", exc is None and v == "annexe", f"{v!r} {exc!r}")
    v, exc = appeler(P.typer_piece, "x" * 10000 + ".pdf", "y" * 1_000_000)
    check("nom et contenu très longs sans indice → annexe", exc is None and v == "annexe", f"{v!r:.40} {exc!r}")
    for nom in ("RC.pdf", "plan.dwg", "sans_extension", "àéï ç.PDF", "..", "a/b\\c.pdf"):
        v, exc = appeler(P.typer_piece, nom, "")
        check(f"typer_piece({nom!r}) rend un type de la liste fermée", exc is None and v in TYPES,
              f"{v!r} {exc!r}")


# =============================================================================
def test_formats_et_tri():
    """DCE fabriqué dans un dossier temporaire : .7z, tri type puis nom, PDF sans texte."""
    gen = charger_generateur()
    dce = TMP / "dce_formats"
    dce.mkdir()
    shutil.copyfile(MIXTE / "RC.pdf", dce / "RC.pdf")
    (dce / "AE.pdf").write_bytes(gen.pdf([["ACTE D'ENGAGEMENT", "Le titulaire s'engage."] + gen.remplir(8)]))
    (dce / "b_notice.pdf").write_bytes(gen.pdf([["Notice de sécurité du chantier"] + gen.remplir(8)]))
    (dce / "a_notice.pdf").write_bytes(gen.pdf([["Notice de phasage du chantier"] + gen.remplir(9)]))
    (dce / "archive.7z").write_bytes(b"7z\xbc\xaf\x27\x1c" + b"\x00" * 32)
    (dce / "CCTP_scanne.pdf").write_bytes(gen.pdf([[], []]))       # 2 pages sans aucun texte
    avant = empreinte(dce)
    inv, exc = appeler(P.inventorier, "TEST-PIECES-FORMATS", str(dce), verbose=False)
    check("inventaire du DCE fabriqué : aucune exception", exc is None and isinstance(inv, dict), repr(exc))
    inv = inv if isinstance(inv, dict) else {}
    e = ecarte(inv, "archive.7z")
    check(".7z : écarté avec le statut format_non_gere", e is not None and e.get("statut") == "format_non_gere",
          repr(e))
    check(".7z : absent des pièces", piece(inv, "archive.7z") is None)
    noms = [base(p.get("nom")) for p in inv.get("pieces") or [] if base(p.get("nom")) != "CCTP_scanne.pdf"]
    check("tri par type puis nom : RC, AE, puis annexes a_notice avant b_notice",
          noms == ["RC.pdf", "AE.pdf", "a_notice.pdf", "b_notice.pdf"], str(noms))
    types = {base(p.get("nom")): p.get("type") for p in inv.get("pieces") or []}
    check("AE.pdf de type AE, notices de type annexe",
          types.get("AE.pdf") == "AE" and types.get("a_notice.pdf") == "annexe"
          and types.get("b_notice.pdf") == "annexe", str(types))
    check("contenus différents : aucun doublon signalé", (inv.get("doublons") or []) == [],
          str(inv.get("doublons")))
    scan = piece(inv, "CCTP_scanne.pdf")
    check("PDF sans texte : jamais retenu comme pièce de texte (lecture_visuelle True, ou écarté)",
          (scan is not None and scan.get("lecture_visuelle") is True)
          or (scan is None and ecarte(inv, "CCTP_scanne.pdf") is not None),
          f"pièce={scan!r} écarté={ecarte(inv, 'CCTP_scanne.pdf')!r}")
    check("DCE fabriqué : dossier source intact", empreinte(dce) == avant)
    check("fixtures intactes", empreinte(MIXTE) == EMPREINTE_MIXTE)


# =============================================================================
def test_limites():
    vide = TMP / "dce_vide"
    vide.mkdir()
    inv, exc = appeler(P.inventorier, "TEST-PIECES-VIDE", str(vide), verbose=False)
    check("dossier vide : aucune exception, un dict", exc is None and isinstance(inv, dict), repr(exc))
    inv = inv if isinstance(inv, dict) else {}
    check("dossier vide : aucune pièce, aucun écarté, aucun doublon",
          inv.get("pieces") == [] and inv.get("ecartes") == [] and inv.get("doublons") == [],
          repr({k: inv.get(k) for k in ("pieces", "ecartes", "doublons")}))
    check("dossier vide : chars_total 0 et nb_pages_total 0",
          inv.get("chars_total") == 0 and inv.get("nb_pages_total") == 0,
          f"{inv.get('chars_total')!r} / {inv.get('nb_pages_total')!r}")
    check("dossier vide : la source reste vide", list(vide.iterdir()) == [])

    absent = TMP / "dce_qui_n_existe_pas"
    inv, exc = appeler(P.inventorier, "TEST-PIECES-ABSENT", str(absent), verbose=False)
    check("dossier inexistant : exception, ou inventaire sans aucune pièce (rien d'inventé)",
          exc is not None or (isinstance(inv, dict) and not inv.get("pieces")), f"{inv!r:.200}")
    check("dossier inexistant : le dossier source n'est pas créé", not absent.exists())

    # verbose=True (défaut) : la sortie console ne change pas le résultat
    inv, exc = appeler(P.inventorier, "TEST-PIECES-VERBEUX", str(MIXTE))
    check("verbose par défaut : même inventaire (4 pièces, 4 écartés, 2 doublons)",
          exc is None and isinstance(inv, dict) and len(inv.get("pieces") or []) == 4
          and len(inv.get("ecartes") or []) == 4 and len(inv.get("doublons") or []) == 2, repr(exc))
    check("deux marchés : deux dossiers de sortie distincts",
          (DIR_TEST / "TEST-PIECES-VERBEUX").is_dir() and (DIR_TEST / MID).is_dir())


# =============================================================================
def test_conversion():
    moteurs, exc = appeler(P.moteurs_conversion)
    check("moteurs_conversion() rend une liste", exc is None and isinstance(moteurs, list), f"{moteurs!r} {exc!r}")
    moteurs = moteurs if isinstance(moteurs, list) else []
    check("moteurs_conversion() ⊆ ['office', 'libreoffice'], sans répétition",
          set(moteurs) <= {"office", "libreoffice"} and len(set(moteurs)) == len(moteurs), repr(moteurs))

    if not moteurs:
        print("  ⊘ SAUTÉ conversion Office/LibreOffice : aucun convertisseur")
    else:
        d = rediriger("pieces_conversion")
        try:
            inv, exc = appeler(P.inventorier, "TEST-PIECES-CONV", str(CONVERSION), verbose=False)
        finally:
            P.DIR_PIECES = DIR_TEST
        check(f"conversion ({', '.join(moteurs)}) : aucune exception", exc is None and isinstance(inv, dict),
              repr(exc))
        ae = piece(inv, "AE.docx") or {}
        check("AE.docx retenu comme pièce", bool(ae), repr((inv or {}).get("ecartes")))
        check("AE.docx : type AE", ae.get("type") == "AE", repr(ae.get("type")))
        check("AE.docx : unité page", ae.get("unite") == "page", repr(ae.get("unite")))
        check("AE.docx : chars > 0", (ae.get("chars") or 0) > 0, repr(ae.get("chars")))
        check("AE.docx : nb_pages >= 1", (ae.get("nb_pages") or 0) >= 1, repr(ae.get("nb_pages")))
        lu = str(ae.get("chemin_lu") or "")
        check("AE.docx : chemin_lu en .pdf", lu.lower().endswith(".pdf"), repr(lu))
        check("AE.docx : chemin_lu sous P.DIR_PIECES, fichier présent",
              bool(lu) and sous(d, lu) and Path(lu).is_file(), repr(lu))
        check("AE.docx : pas dans les écartés", ecarte(inv, "AE.docx") is None)
        if ae:
            t, exc = appeler(P.texte_piece, ae)
            check("AE.docx converti : texte lisible (« ACTE D'ENGAGEMENT »), marqueur de page 1",
                  exc is None and "acte d" in norm(t) and "engagement" in norm(t) and "\n[[Page 1]]\n" in (t or ""),
                  f"{exc!r} {str(t)[:80]!r}")
        check("conversion : dossier source intact (aucun PDF ni fichier de verrou laissé)",
              empreinte(CONVERSION) == EMPREINTE_CONVERSION,
              str(sorted(set(empreinte(CONVERSION)) ^ set(EMPREINTE_CONVERSION))))

    # Sans convertisseur : echec_conversion, rien n'est levé.
    d = rediriger("pieces_sans_convertisseur")
    d_reel = P.moteurs_conversion
    P.moteurs_conversion = lambda: []
    try:
        inv, exc = appeler(P.inventorier, "TEST-PIECES-SANS-CONV", str(CONVERSION), verbose=False)
    finally:
        P.moteurs_conversion = d_reel
        P.DIR_PIECES = DIR_TEST
    check("sans convertisseur : rien n'est levé", exc is None and isinstance(inv, dict), repr(exc))
    inv = inv if isinstance(inv, dict) else {}
    e = ecarte(inv, "AE.docx")
    check("sans convertisseur : AE.docx dans les écartés, statut echec_conversion",
          e is not None and e.get("statut") == "echec_conversion", repr(inv.get("ecartes")))
    check("sans convertisseur : AE.docx n'est pas une pièce retenue", piece(inv, "AE.docx") is None,
          repr([p.get("nom") for p in inv.get("pieces") or []]))
    check("sans convertisseur : chars_total 0", inv.get("chars_total") == 0, repr(inv.get("chars_total")))
    check("sans convertisseur : dossier source intact", empreinte(CONVERSION) == EMPREINTE_CONVERSION)


# =============================================================================
def test_source_intacte():
    check("dce_mixte intact en fin de test (mêmes fichiers, mêmes empreintes)",
          empreinte(MIXTE) == EMPREINTE_MIXTE, str(sorted(set(empreinte(MIXTE)) ^ set(EMPREINTE_MIXTE))))
    check("dce_conversion intact en fin de test", empreinte(CONVERSION) == EMPREINTE_CONVERSION)
    check("P.DIR_PIECES toujours sur le dossier temporaire", Path(P.DIR_PIECES) == DIR_TEST, repr(P.DIR_PIECES))
    check("aucun dossier de test dans DATA / 'pieces'",
          not any((Path(DATA) / "pieces" / m).exists()
                  for m in (MID, "TEST-PIECES-FORMATS", "TEST-PIECES-VIDE", "TEST-PIECES-ABSENT",
                            "TEST-PIECES-VERBEUX", "TEST-PIECES-CONV", "TEST-PIECES-SANS-CONV")))


section("P.DIR_PIECES", test_dir_pieces)
section("inventaire de dce_mixte", test_inventaire_mixte)
section("_inventaire.json : relecture et force", test_inventaire_json)
section("texte_piece : marqueurs de page et de feuille", test_texte_piece)
section("texte_page", test_texte_page)
section("typer_piece", test_typer_piece)
section(".7z, tri type puis nom, PDF sans texte", test_formats_et_tri)
section("cas limites : dossier vide, dossier inexistant", test_limites)
section("conversion Office / LibreOffice", test_conversion)
# =============================================================================
def test_zip_archives_et_chemin_piege():
    """Ajouté après l'écriture du code (chantier 2, étape 4) : zips déjà rangés dans
    _zip_archives/ par l'ancien dézippage à plat, et entrée de zip à chemin piégé."""
    import zipfile
    gen = charger_generateur()
    dce = TMP / "dce_zip_archives"
    (dce / "_zip_archives").mkdir(parents=True)
    # État laissé par l'ancien code : le zip est archivé, UNE des deux notices homonymes
    # a été extraite à plat, l'autre (même nom, autre dossier du zip) a été perdue.
    notice_lot1 = gen.pdf([["Notice du lot 1 : charpente"] + gen.remplir(8)])
    notice_lot2 = gen.pdf([["Notice du lot 2 : couverture"] + gen.remplir(9)])
    with zipfile.ZipFile(dce / "_zip_archives" / "dossier.zip", "w") as z:
        z.writestr("lot1/notice.pdf", notice_lot1)
        z.writestr("lot2/notice.pdf", notice_lot2)
        z.writestr("../evasion.txt", "ne doit jamais sortir du dossier de travail")
        z.writestr("../../evasion2.txt", "idem")
    (dce / "notice.pdf").write_bytes(notice_lot1)
    avant = empreinte(dce)
    travail = rediriger("pieces_zip_archives")
    try:
        inv, exc = appeler(P.inventorier, "TEST-PIECES-ZIPARCH", str(dce), verbose=False)
    finally:
        P.DIR_PIECES = DIR_TEST
    check("inventaire sans exception", exc is None and isinstance(inv, dict), repr(exc))
    inv = inv or {}
    notices = [p for p in inv.get("pieces") or [] if base(p.get("nom")) == "notice.pdf"]
    textes = " ".join(P.texte_piece(p) for p in notices)
    check("les deux notices homonymes sont lues (celle perdue par le dézippage à plat comprise)",
          len(notices) == 2 and "charpente" in textes and "couverture" in textes,
          repr([(p.get("nom"), p.get("chars")) for p in inv.get("pieces") or []]))
    check("la copie à plat et sa jumelle du zip : un seul exemplaire, un doublon signalé",
          len(inv.get("doublons") or []) == 1, repr(inv.get("doublons")))
    check("entrées à chemin piégé (../) : rien n'est écrit hors du dossier de travail",
          not (travail / "evasion.txt").exists() and not (travail / "TEST-PIECES-ZIPARCH" / "evasion.txt").exists()
          and not list(TMP.glob("evasion*.txt")) and not list(travail.rglob("evasion2.txt")),
          repr([str(f) for f in TMP.rglob("evasion*")]))
    check("les entrées piégées sont signalées dans erreurs",
          any("evasion" in str(e) for e in inv.get("erreurs") or []), repr(inv.get("erreurs")))
    check("dossier source intact (rien n'est écrit ni déplacé dans le DCE)", empreinte(dce) == avant)


def test_zip_tronque_et_chemins_longs():
    """Ajouté après l'essai sur des DCE réels (chantier 2, étape 4) : zip dont le
    téléchargement a été interrompu (pas de répertoire central), et zip aux chemins
    internes trop longs pour Windows."""
    import io
    import zipfile
    gen = charger_generateur()
    dce = TMP / "dce_zip_tronque"
    dce.mkdir()
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("DCE/RC.pdf", gen.pdf([["RÈGLEMENT DE LA CONSULTATION"] + gen.remplir(8)]))
        z.writestr("DCE/CCAP.pdf", gen.pdf([["CAHIER DES CLAUSES ADMINISTRATIVES PARTICULIÈRES"] + gen.remplir(8)]))
        z.writestr("DCE/CCTP.pdf", gen.pdf([["CAHIER DES CLAUSES TECHNIQUES PARTICULIÈRES"] + gen.remplir(40)]))
    octets = tampon.getvalue()
    debut_cctp = octets.rfind(b"PK\x03\x04")
    (dce / "dce_tronque.zip").write_bytes(octets[:debut_cctp + 200])     # coupé au milieu du CCTP
    long_dossier = "/".join(["Dossier de consultation des entreprises - pièces écrites et annexes"] * 4)
    with zipfile.ZipFile(dce / "chemins_longs.zip", "w") as z:
        z.writestr(f"{long_dossier}/Annexe au règlement de la consultation - version définitive.pdf",
                   gen.pdf([["Annexe : attestation de visite"] + gen.remplir(8)]))
    avant = empreinte(dce)
    rediriger("pieces_zip_tronque")
    try:
        inv, exc = appeler(P.inventorier, "TEST-PIECES-ZIPTRONQUE", str(dce), verbose=False)
    finally:
        P.DIR_PIECES = DIR_TEST
    check("inventaire sans exception", exc is None and isinstance(inv, dict), repr(exc))
    inv = inv or {}
    noms = sorted(base(p.get("nom")) for p in inv.get("pieces") or [])
    check("zip tronqué : les pièces complètes avant la coupure sont récupérées (RC, CCAP)",
          "RC.pdf" in noms and "CCAP.pdf" in noms, repr(noms))
    check("zip tronqué : la pièce coupée n'est pas retenue", "CCTP.pdf" not in noms, repr(noms))
    e = ecarte(inv, "dce_tronque.zip")
    check("zip tronqué : signalé format_non_gere (le reste de l'archive n'est pas lu)",
          e is not None and e.get("statut") == "format_non_gere" and "récupéré" in (e.get("detail") or ""), repr(e))
    longue = piece(inv, "Annexe au règlement de la consultation - version définitive.pdf")
    check("chemins internes trop longs : la pièce est lue, son nom est conservé",
          longue is not None and longue.get("chars", 0) > 200 and len(str(longue.get("chemin_original"))) < 260,
          repr(noms))
    check("chemins longs : aucune erreur d'archive", ecarte(inv, "chemins_longs.zip") is None,
          repr(inv.get("erreurs")))
    check("dossier source intact", empreinte(dce) == avant)


section("_zip_archives relu, chemin de zip piégé", test_zip_archives_et_chemin_piege)
section("zip tronqué, chemins internes trop longs", test_zip_tronque_et_chemins_longs)
section("dossier source jamais modifié", test_source_intacte)

terminer()
