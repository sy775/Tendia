# -*- coding: utf-8 -*-
"""
tests/test_recalcul_et_chemins_longs.py
---------------------------------------
Tests HORS-LIGNE ajoutés après la relecture des constats de l'étape 7 du chantier 2 :
  - pieces : zips imbriqués à chemins internes très longs (constat sur un DCE réel) :
    tout est lu, rien ne s'écrase, une entrée « ../ » reste refusée ;
  - scripts/maintenance/recalculer_sources_brief.py : dry-run, copie de l'ancien brief
    avant écriture, écriture unitaire, refus sur trace absente, partielle ou recalcul
    défavorable, code de sortie.

Lancement : python tests/test_recalcul_et_chemins_longs.py
"""
import contextlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from base_temporaire import isoler_stockage
dossier = isoler_stockage()

from tendia.analyse import extraire as E
from tendia.analyse import pieces as P
from tendia.core import stockage
from tendia.core.chemins import RACINE_DEPOT

ok = ko = 0


def check(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}  {str(detail)[:400]}")


FIXTURES = Path(__file__).resolve().parent / "fixtures"
spec = importlib.util.spec_from_file_location("generateur_fixtures_2", FIXTURES / "generer_dce_mixte.py")
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)
spec = importlib.util.spec_from_file_location("recalculer_sources_brief",
                                              RACINE_DEPOT / "scripts" / "maintenance" / "recalculer_sources_brief.py")
RS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RS)

TMP = Path(tempfile.mkdtemp(prefix="tendia_rc_"))
P.DIR_PIECES = TMP / "pieces"
P.DIR_PIECES.mkdir()
E.REPERTOIRE_EXTRACTIONS = str(TMP / "extractions")
E.REPERTOIRE_ARCHIVE_BRIEFS = TMP / "archive_briefs"
Path(E.REPERTOIRE_EXTRACTIONS).mkdir()


def pdf(titre, n=8):
    return gen.pdf([[titre] + gen.remplir(n)])


def zip_octets(fichiers: dict) -> bytes:
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w") as z:
        for nom, contenu in fichiers.items():
            z.writestr(nom, contenu)
    return tampon.getvalue()


# =====================================================================================
print("=== zips imbriqués à chemins très longs ===")
long_ = "/".join(["Dossier des ouvrages exécutés - lot chauffage ventilation climatisation"] * 3)
interne_a = zip_octets({f"{long_}/AUTOCONTROLES/Rapport d'autocontrôle des débits de la CTA, version signée.pdf":
                        pdf("Autocontrôle débits CTA : conforme"),
                        f"{long_}/AUTOCONTROLES/Rapport d'autocontrôle de la continuité de la mise à la terre.pdf":
                        pdf("Continuité de la mise à la terre : conforme", 9)})
interne_b = zip_octets({f"{long_}/AUTOCONTROLES/Rapport d'autocontrôle des débits de la CTA, version signée.pdf":
                        pdf("Autocontrôle débits CTA du second bâtiment : non conforme", 10)})
racine = TMP / "dce" / "LONG"
racine.mkdir(parents=True)
(racine / "doe.zip").write_bytes(zip_octets({
    f"{long_}/DOE bâtiment A - dossier complet des ouvrages exécutés.zip": interne_a,
    f"{long_}/DOE bâtiment B - dossier complet des ouvrages exécutés.zip": interne_b,
    "../hors_dossier.pdf": pdf("ne doit jamais être écrit hors du dossier de travail")}))
avant = {f.name: f.stat().st_size for f in racine.rglob("*") if f.is_file()}
inv = P.inventorier("LONG", str(racine), verbose=False)
textes = " ".join(P.texte_piece(p) for p in inv["pieces"])
check("les 3 pièces des deux zips imbriqués sont lues", len(inv["pieces"]) == 3, [p["nom"] for p in inv["pieces"]])
check("les deux homonymes (bâtiment A et B) sont distincts : aucun écrasement",
      "conforme" in textes and "second bâtiment" in textes and "mise à la terre" in textes)
check("aucune erreur d'extraction (FileNotFoundError constaté avant le correctif)",
      not [e for e in inv["erreurs"] if "FileNotFound" in e], inv["erreurs"])
check("entrée « ../ » refusée et signalée", any("hors archive" in e for e in inv["erreurs"])
      and not list(TMP.rglob("hors_dossier.pdf")))
check("tous les fichiers extraits sont sous le dossier de travail du marché",
      all(P.dossier_travail("LONG") in Path(p["chemin_lu"]).resolve().parents for p in inv["pieces"]))
check("chemins d'extraction sous 260 caractères", all(len(p["chemin_lu"]) < 260 for p in inv["pieces"]),
      max(len(p["chemin_lu"]) for p in inv["pieces"]))
check("source intacte", avant == {f.name: f.stat().st_size for f in racine.rglob("*") if f.is_file()})

# =====================================================================================
print("=== recalculer_sources_brief ===")
racine = TMP / "dce" / "RECALC"
racine.mkdir(parents=True)
(racine / "RC.pdf").write_bytes(gen.pdf([["RÈGLEMENT DE LA CONSULTATION"] + gen.remplir(8),
                                         ["Article 5 : critère prix 40 %, critère valeur technique 60 %."] + gen.remplir(8)]))
inv = P.inventorier("RECALC", str(racine), verbose=False)
travail = P.dossier_travail("RECALC")
analyses = [{"piece": "RC.pdf", "type": "RC", "nb_pages": 2, "empreinte": inv["pieces"][0]["empreinte"], "resultats": [
    {"partie": 1, "ok": True, "erreur": None, "json": {"informations": {
        "criteres_attribution": {"valeur": "40/60", "pages": [2],
                                 "extrait": "critère prix 40 % [...] critère valeur technique 60 %"}}}}]}]
(travail / "_trace.json").write_text(json.dumps({"version": "x", "analyses_pieces": analyses}), encoding="utf-8")
brief = {"synthese_marche": "x", "_meta": {"type": "complet", "mode": "document"},
         "_sources": {"criteres_ponderations": {"piece": "RC.pdf", "page": 2, "extrait": "ancien", "verifie": False}},
         "_lecture": {"pieces": [{"nom": "RC.pdf", "statut": "lu"}], "nb_pieces_texte": 1, "nb_lues": 1, "pct_non_lu": 0.0}}
stockage.ecrire("briefs_extraits", "RECALC", brief)


def lancer(argv):
    code = 0
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            RS.main(argv)
        except SystemExit as e:
            code = e.code or 0
    stockage.invalider_cache()
    return code


code = lancer(["RECALC", "--dry-run"])
check("dry-run : rien d'écrit, aucune copie", code == 0 and stockage.lire("briefs_extraits", "RECALC") == brief
      and not Path(E.REPERTOIRE_ARCHIVE_BRIEFS).exists())
code = lancer(["RECALC"])
apres = stockage.lire("briefs_extraits", "RECALC")
copies = list(Path(E.REPERTOIRE_ARCHIVE_BRIEFS).glob("RECALC_*.json"))
check("écrit : source des critères vérifiée p. 2", code == 0 and apres["_sources"]["criteres_ponderations"]["verifie"] is True,
      apres.get("_sources"))
check("l'ancien brief est copié dans l'archive avant l'écriture",
      len(copies) == 1 and json.loads(copies[0].read_text(encoding="utf-8")) == brief)
check("marque du recalcul dans _meta", bool(apres["_meta"].get("sources_recalculees_le")))
check("aucune clé de sauvegarde dans briefs_extraits",
      sorted(k for k in stockage.charger("briefs_extraits") if k.startswith("RECALC")) == ["RECALC"])

# trace partielle : la pièce lue du brief manque dans la trace
brief_2 = dict(apres, _lecture={"pieces": [{"nom": "RC.pdf", "statut": "lu"}, {"nom": "CCAP.pdf", "statut": "lu"}],
                                "nb_pieces_texte": 2, "nb_lues": 2, "pct_non_lu": 0.0})
stockage.ecrire("briefs_extraits", "RECALC", brief_2)
code = lancer(["RECALC"])
check("trace partielle (CCAP lu dans le brief, absent de la trace) : refus, code 1, rien d'écrit",
      code == 1 and stockage.lire("briefs_extraits", "RECALC") == brief_2)

# recalcul défavorable : le brief en base a plus de sources vérifiées que le recalcul
brief_3 = dict(apres, _sources={c: {"piece": "RC.pdf", "page": 2, "extrait": "x", "verifie": True}
                                for c in ("criteres_ponderations", "date_limite", "visite")})
stockage.ecrire("briefs_extraits", "RECALC", brief_3)
code = lancer(["RECALC"])
check("recalcul défavorable (3 vérifiées → 1) : refus, code 1, rien d'écrit",
      code == 1 and stockage.lire("briefs_extraits", "RECALC") == brief_3)
code = lancer(["RECALC", "--force"])
check("--force : écrit malgré tout", code == 0 and stockage.lire("briefs_extraits", "RECALC") != brief_3)

(travail / "_trace.json").rename(travail / "_trace_absente.json")
code = lancer(["RECALC"])
check("trace absente : refus, code 1", code == 1)
(travail / "_trace_absente.json").rename(travail / "_trace.json")
(travail / "_trace.json").write_text(json.dumps({"version": "x", "analyses_pieces": []}), encoding="utf-8")
code = lancer(["RECALC"])
check("trace sans analyses : refus, code 1", code == 1)
stockage.ecrire("briefs_extraits", "CLASSIQUE", {"_meta": {"type": "complet"}})
check("brief de l'ancien mode : refus", lancer(["CLASSIQUE"]) == 1)

shutil.rmtree(TMP, ignore_errors=True)
print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
