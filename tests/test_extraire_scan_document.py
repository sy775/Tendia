# -*- coding: utf-8 -*-
"""
tests/test_extraire_scan_document.py
------------------------------------
Tests HORS-LIGNE ajoutés après la relecture de l'étape 5 du chantier 2 : ce que le mode
document choisit de lire (et de payer) quand on lance extraire ou le pipeline.
  - un brief complet existant n'est pas repayé (présent dans l'état, ou seulement en base) ;
  - marché clos ou absent de la base : pas lu, sauf --marche ou --force ;
  - nouvelles pièces depuis un brief classique : relu ; dossier modifié en mode document : relu ;
  - signature insensible au dézippage à plat de l'ancien code ;
  - échec mémorisé : pas retenté indéfiniment ; DCE sauté : pas ré-estimé à chaque passe ;
  - tri par date limite ; plafond de passe par défaut ; une erreur n'arrête pas la passe ;
  - archive des briefs inaccessible : aucune lecture payante lancée.

Lancement : python tests/test_extraire_scan_document.py
"""
import contextlib
import io
import json
import os
import sys
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from base_temporaire import isoler_stockage
dossier = isoler_stockage()

from tendia.analyse import extraire as E
from tendia.analyse import mode_document
from tendia.core import budget, stockage

ok = ko = 0


def check(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}  {str(detail)[:500]}")


E.REPERTOIRE_DCE = str(dossier / "dce")
E.REPERTOIRE_EXTRACTIONS = str(dossier / "extractions")
E.REPERTOIRE_RAPPORTS = str(dossier / "rapports")
E.FICHIER_ETAT = os.path.join(E.REPERTOIRE_EXTRACTIONS, "_etat.json")
E.REPERTOIRE_ARCHIVE_BRIEFS = dossier / "archive_briefs"
for d in (E.REPERTOIRE_DCE, E.REPERTOIRE_EXTRACTIONS, E.REPERTOIRE_RAPPORTS):
    os.makedirs(d, exist_ok=True)

J = lambda n: (date.today() + timedelta(days=n)).isoformat()
ISO = lambda secondes=0: (datetime.now(timezone.utc) + timedelta(seconds=secondes)).isoformat()


def marche(mid, limite_jours=30, **extra):
    stockage.ecrire("marches", mid, {"id": mid, "titre": mid, "nature": "APPEL_OFFRE",
                                     "date_limite_depot": J(limite_jours), **extra})


def dce(mid, fichiers=None):
    racine = Path(E.REPERTOIRE_DCE) / mid
    racine.mkdir(parents=True, exist_ok=True)
    for nom, contenu in (fichiers or {"RC.pdf": b"%PDF contenu du RC"}).items():
        (racine / nom).parent.mkdir(parents=True, exist_ok=True)
        (racine / nom).write_bytes(contenu)
    return str(racine)


def etat(contenu=None):
    if contenu is not None:
        Path(E.FICHIER_ETAT).write_text(json.dumps(contenu), encoding="utf-8")
    return json.loads(Path(E.FICHIER_ETAT).read_text(encoding="utf-8")) if os.path.exists(E.FICHIER_ETAT) else {}


def scan(**kw):
    stockage.invalider_cache()
    return [t[0] for t in E._scanner_dossiers_dce(mode="document", verbose=False, **kw)]


def vieillir(chemin_dossier, secondes=3600):
    """Recule la date de tous les fichiers du dossier (ils précèdent l'extraction)."""
    ancien = time.time() - secondes
    for f in Path(chemin_dossier).rglob("*"):
        if f.is_file():
            os.utime(f, (ancien, ancien))


def silencieux(fn, *a, **k):
    erreur = None
    with io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="replace") as sortie:
        with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(sortie):
            try:
                fn(*a, **k)
            except SystemExit as e:
                erreur = e
            except Exception as e:  # noqa: BLE001
                erreur = e
    return erreur


# =====================================================================================
print("=== ce qui n'est pas repayé ===")
marche("S-NEUF")
dce("S-NEUF")
marche("S-ETAT-CLASSIQUE")
vieillir(dce("S-ETAT-CLASSIQUE"))
marche("S-BRIEF-HORS-ETAT")
vieillir(dce("S-BRIEF-HORS-ETAT"))
stockage.ecrire("briefs_extraits", "S-BRIEF-HORS-ETAT",
                {"synthese_marche": "ancien", "_meta": {"type": "complet", "date_generation": ISO()}})
marche("S-BRIEF-LIGHT")
vieillir(dce("S-BRIEF-LIGHT"))
stockage.ecrire("briefs_extraits", "S-BRIEF-LIGHT", {"_meta": {"type": "light", "date_generation": ISO()}})
marche("S-DOC-OK")
d_doc = dce("S-DOC-OK")
marche("S-CLOS", limite_jours=-3)
dce("S-CLOS")
marche("S-ATTRIBUE", nature="ATTRIBUTION")
dce("S-ATTRIBUE")
dce("S-HORS-BASE")
marche("S-VIDE")
os.makedirs(os.path.join(E.REPERTOIRE_DCE, "S-VIDE"), exist_ok=True)
etat({"S-ETAT-CLASSIQUE": {"signature_pdfs": "x", "extrait_le": ISO(), "pdfs": ["RC.pdf"]},
      "S-DOC-OK": {"mode": "document", "extrait_le": ISO(), "signature_dossier": E.signature_dossier(d_doc)}})
a_lire = scan()
check("marché jamais extrait : lu", "S-NEUF" in a_lire, a_lire)
check("extrait en mode classique (état), rien de neuf : pas repayé", "S-ETAT-CLASSIQUE" not in a_lire, a_lire)
check("brief complet en base mais hors état, rien de neuf : pas repayé", "S-BRIEF-HORS-ETAT" not in a_lire, a_lire)
check("brief light seulement : lu (le light ne vient pas du DCE)", "S-BRIEF-LIGHT" in a_lire, a_lire)
check("extrait en mode document, dossier inchangé : pas relu", "S-DOC-OK" not in a_lire, a_lire)
check("marché clos (date limite passée) : pas lu", "S-CLOS" not in a_lire, a_lire)
check("avis d'attribution : pas lu", "S-ATTRIBUE" not in a_lire, a_lire)
check("dossier sans marché en base : pas lu", "S-HORS-BASE" not in a_lire, a_lire)
check("dossier vide : pas lu", "S-VIDE" not in a_lire, a_lire)

print("=== ce qui est repris ===")
check("--marche sur un marché clos : lu", scan(ids={"S-CLOS"}) == ["S-CLOS"])
check("--marche sur un dossier hors base : lu", scan(ids={"S-HORS-BASE"}) == ["S-HORS-BASE"])
check("--marche sur un marché déjà extrait : pas relu sans --force", scan(ids={"S-DOC-OK"}) == [])
tout = scan(force=True)
check("--force : tout dossier non vide, clos et déjà extraits compris",
      {"S-NEUF", "S-ETAT-CLASSIQUE", "S-BRIEF-HORS-ETAT", "S-DOC-OK", "S-CLOS", "S-HORS-BASE"} <= set(tout)
      and "S-VIDE" not in tout, tout)
Path(E.REPERTOIRE_DCE, "S-ETAT-CLASSIQUE", "CCAP_rectifie.pdf").write_bytes(b"%PDF nouvelle piece")
Path(E.REPERTOIRE_DCE, "S-BRIEF-HORS-ETAT", "CCTP.pdf").write_bytes(b"%PDF nouvelle piece")
Path(E.REPERTOIRE_DCE, "S-DOC-OK", "annexe.pdf").write_bytes(b"%PDF nouvelle piece")
a_lire = scan()
check("nouvelles pièces depuis le brief classique (état) : relu", "S-ETAT-CLASSIQUE" in a_lire, a_lire)
check("nouvelles pièces depuis le brief classique (hors état) : relu", "S-BRIEF-HORS-ETAT" in a_lire, a_lire)
check("dossier modifié depuis la lecture en mode document : relu", "S-DOC-OK" in a_lire, a_lire)

print("=== tri par date limite ===")
for mid, jours in (("T-LOIN", 90), ("T-PROCHE", 2), ("T-MILIEU", 20)):
    marche(mid, limite_jours=jours)
    dce(mid)
ordre = [m for m in scan() if m.startswith("T-")]
check("la date limite la plus proche d'abord", ordre == ["T-PROCHE", "T-MILIEU", "T-LOIN"], ordre)

print("=== signature insensible au dézippage à plat de l'ancien code ===")
tampon = io.BytesIO()
with zipfile.ZipFile(tampon, "w") as z:
    z.writestr("DCE/RC.pdf", b"%PDF RC du zip")
    z.writestr("DCE/CCTP.pdf", b"%PDF CCTP du zip")
marche("Z-PLAT")
d_zip = dce("Z-PLAT", {"dce.zip": tampon.getvalue(), "avis.pdf": b"%PDF avis"})
avant = E.signature_dossier(d_zip)
etat({**etat(), "Z-PLAT": {"mode": "document", "extrait_le": ISO(), "signature_dossier": avant}})
E._dezipper_dossier(d_zip, verbose=False)     # ancien code : zip → _zip_archives/, contenu à plat
check("le dézippage a bien modifié le dossier (témoin)",
      os.path.isfile(os.path.join(d_zip, "_zip_archives", "dce.zip")) and os.path.isfile(os.path.join(d_zip, "RC.pdf")))
check("la signature ne change pas", E.signature_dossier(d_zip) == avant)
check("le marché n'est pas repayé après un dézippage à plat", "Z-PLAT" not in scan())
Path(d_zip, "rectificatif.pdf").write_bytes(b"%PDF vraie nouvelle piece")
check("une vraie nouvelle pièce change la signature", E.signature_dossier(d_zip) != avant and "Z-PLAT" in scan())

print("=== échecs mémorisés ===")
marche("E-ECHEC")
d_ech = dce("E-ECHEC")
marche("E-SAUTE")
d_sau = dce("E-SAUTE")
e = etat()
E.noter_echec(e, "E-ECHEC", "echec_fusion : X", d_ech, 2.5)
E.noter_echec(e, "E-SAUTE", "cout_estime_depasse", d_sau, 2.5)
etat(e)
check("1er échec : encore retenté", "E-ECHEC" in scan(max_cout_par_dce=2.5))
check("DCE sauté pour coût estimé : pas ré-estimé au même plafond", "E-SAUTE" not in scan(max_cout_par_dce=2.5))
check("DCE sauté : repris si le plafond par DCE change", "E-SAUTE" in scan(max_cout_par_dce=4.0))
e = etat()
E.noter_echec(e, "E-ECHEC", "echec_fusion : X", d_ech, 2.5)
etat(e)
check(f"{E.MAX_TENTATIVES_ECHEC} échecs sur le même contenu : plus retenté",
      etat()["E-ECHEC"]["echec"]["nb_tentatives"] == 2 and "E-ECHEC" not in scan(max_cout_par_dce=2.5))
check("--force le reprend", "E-ECHEC" in scan(force=True))
Path(d_ech, "piece_corrigee.pdf").write_bytes(b"%PDF")
check("contenu modifié : retenté", "E-ECHEC" in scan(max_cout_par_dce=2.5))
e = etat()
E.noter_echec(e, "S-DOC-OK", "echec_fusion : Y", d_doc, 2.5)
check("noter_echec conserve l'entrée de l'extraction réussie", e["S-DOC-OK"].get("extrait_le") and e["S-DOC-OK"]["echec"]["nb_tentatives"] == 1)

print("=== mode classique : un brief du mode document n'est pas remplacé sans --force ===")
from tendia.analyse import pdf_extract
pdf_reel = pdf_extract.extraire_dossier
pdf_extract.extraire_dossier = lambda d, verbose=False: {"RC.pdf": {"hash": "h-" + os.path.basename(d), "taille_chars": 9, "texte": "x"}}
etat({"S-DOC-OK": {"mode": "document", "extrait_le": ISO(), "signature_dossier": "s"}})
classique = [t[0] for t in E._scanner_dossiers_dce(mode="classique", verbose=False)]
check("classique sans --force : marché lu en mode document ignoré", "S-DOC-OK" not in classique and "S-NEUF" in classique, classique)
check("classique --force : repris", "S-DOC-OK" in [t[0] for t in E._scanner_dossiers_dce(mode="classique", verbose=False, force=True)])
pdf_extract.extraire_dossier = pdf_reel

# =====================================================================================
print("=== main : plafond de passe par défaut, erreurs, budget ===")
LUS = []
COMPORTEMENT = {}


def faux_lire_dce(marche_id, dossier_dce, contexte, codes_presets, max_cout_par_dce=2.5, dry_run=False, verbose=True, **kw):
    LUS.append(marche_id)
    quoi = COMPORTEMENT.get(marche_id)
    if isinstance(quoi, BaseException):
        raise quoi
    if quoi == "echec":
        return {"ok": False, "brief": None, "raison": "echec_fusion : X", "estimation": {"cout_eur": 1.0},
                "inventaire": {}, "lecture": None, "cout_eur": 0.7, "modele": None, "appels": {}}
    lecture = {"pieces": [], "nb_pieces_texte": 1, "nb_lues": 1, "pct_non_lu": 0.0}
    return {"ok": True, "brief": {"synthese_marche": "ok", "domaines_metier": [], "_sources": {}, "_lecture": lecture},
            "raison": None, "estimation": {"cout_eur": 2.0}, "inventaire": {}, "lecture": lecture,
            "cout_eur": 3.0, "modele": "gemini-4-argon", "appels": {"nb_appels": 2}, "duree_s": 1.0}


mode_document.lire_dce = faux_lire_dce
etat({})
import shutil
shutil.rmtree(E.REPERTOIRE_DCE)
os.makedirs(E.REPERTOIRE_DCE)
for i in range(4):
    marche(f"P-{i}", limite_jours=10 + i)
    dce(f"P-{i}")
stockage.invalider_cache()
err = silencieux(E.main, [])
check("sans --max-cout : plafond de passe par défaut de 5 € (briefs à 3 € : arrêt après le 2e)",
      err is None and LUS == ["P-0", "P-1"], f"{err!r} {LUS}")
check("les 2 marchés lus sont marqués extraits en mode document",
      all(etat().get(m, {}).get("mode") == "document" for m in ("P-0", "P-1")) and "P-2" not in etat())
LUS.clear()
err = silencieux(E.main, ["--max-cout", "50"])
check("2e passe : les marchés déjà extraits ne sont pas repayés", err is None and LUS == ["P-2", "P-3"], f"{err!r} {LUS}")

etat({})
for m in ("P-0", "P-1", "P-2", "P-3"):
    stockage.supprimer("briefs_extraits", m) if hasattr(stockage, "supprimer") else None
COMPORTEMENT.update({"P-0": RuntimeError("panne inattendue"), "P-1": "echec"})
LUS.clear()
err = silencieux(E.main, ["--max-cout", "50", "--force"])
e = etat()
check("une erreur sur un marché n'arrête pas la passe", err is None and LUS == ["P-0", "P-1", "P-2", "P-3"], f"{err!r} {LUS}")
check("erreur et échec mémorisés dans l'état, succès marqués extraits",
      e.get("P-0", {}).get("echec") and e.get("P-1", {}).get("echec", {}).get("raison", "").startswith("echec_fusion")
      and e.get("P-2", {}).get("mode") == "document", e)
check("le coût d'une lecture sans brief compte dans la passe",
      E.cout_du_resultat({"ok": False, "cout_eur_sans_brief": 0.7}) == 0.7)

COMPORTEMENT.clear()
COMPORTEMENT["P-1"] = budget.BudgetDepasseError("plafond mensuel atteint")
LUS.clear()
err = silencieux(E.main, ["--max-cout", "50", "--force"])
check("plafond mensuel atteint en cours de passe : arrêt propre, code de sortie 1",
      isinstance(err, SystemExit) and err.code == 1 and LUS == ["P-0", "P-1"], f"{err!r} {LUS}")
COMPORTEMENT.clear()

print("=== archive des briefs inaccessible ===")
marche("A-ARCH")
d_a = dce("A-ARCH")
stockage.ecrire("briefs_extraits", "A-ARCH", {"synthese_marche": "ancien brief", "_meta": {"type": "complet"}})
fichier_bloquant = dossier / "pas_un_dossier"
fichier_bloquant.write_text("x", encoding="utf-8")
archive_reelle, E.REPERTOIRE_ARCHIVE_BRIEFS = E.REPERTOIRE_ARCHIVE_BRIEFS, fichier_bloquant / "briefs"
LUS.clear()
res = E.traiter_marche("A-ARCH", d_a, {}, verbose=False)
check("brief existant et archive inaccessible : aucune lecture payante lancée",
      LUS == [] and res["ok"] is False and res["raison"] == "archive_inaccessible", f"{LUS} {res}")
check("l'ancien brief est intact", stockage.lire("briefs_extraits", "A-ARCH")["synthese_marche"] == "ancien brief")
marche("A-NEUF")
res = E.traiter_marche("A-NEUF", dce("A-NEUF"), {}, verbose=False)
check("sans brief existant, l'archive n'est pas requise : lecture faite", res["ok"] is True and LUS == ["A-NEUF"], res.get("raison"))
E.REPERTOIRE_ARCHIVE_BRIEFS = archive_reelle

print("=== écriture en base impossible : le marché n'est pas marqué extrait ===")
marche("B-BASE")
d_b = dce("B-BASE")
ecrire_reel = stockage.ecrire


def ecrire_en_panne(collection, cle, valeur):
    if collection == "briefs_extraits":
        raise OSError("disque plein")
    return ecrire_reel(collection, cle, valeur)


stockage.ecrire = ecrire_en_panne
leve = None
try:
    E.traiter_marche("B-BASE", d_b, {}, verbose=False)
except RuntimeError as e:
    leve = e
stockage.ecrire = ecrire_reel
check("échec d'écriture du brief : erreur remontée (plus de succès silencieux)", leve is not None, repr(leve))
check("le JSON du brief payé est conservé sur disque",
      os.path.isfile(os.path.join(E.REPERTOIRE_EXTRACTIONS, "B-BASE.json")))

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
