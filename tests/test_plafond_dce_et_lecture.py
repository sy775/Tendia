# -*- coding: utf-8 -*-
"""
tests/test_plafond_dce_et_lecture.py
------------------------------------
Tests HORS-LIGNE (chantier 2b, étape 2) :
  - --max-cout-par-dce borne le coût RÉEL : au-delà, plus d'appel ; avant la fusion, pas de
    brief (raison plafond_dce_atteint, pièces lues tracées pour la reprise) ; pendant les
    recherches ciblées, brief gardé et marqué _incomplet ;
  - plan_ignore : un « plan » qui porte du texte (> 1 500 caractères par page en moyenne)
    est lu ; un vrai plan reste ignoré ;
  - ancien mode : les zips sont extraits dans data/pieces/<id>/_classique, rien n'est écrit
    dans le dossier source (data/dce).

Faux call_llm (aucun réseau, aucun appel payant). Lancement : python tests/test_plafond_dce_et_lecture.py
"""
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import types
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from base_temporaire import isoler_stockage
dossier = isoler_stockage({"kill_switch_global": False, "plafond_global_eur_mois": 1e12})

from tendia.analyse import extraire as E
from tendia.analyse import llm_router
from tendia.analyse import mode_document as MD
from tendia.analyse import pieces as P

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
spec = importlib.util.spec_from_file_location("generateur_fixtures_pl", FIXTURES / "generer_dce_mixte.py")
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

TMP = Path(tempfile.mkdtemp(prefix="tendia_pl_"))
P.DIR_PIECES = TMP / "pieces"
P.DIR_PIECES.mkdir()

# =====================================================================================
print("=== plafond par DCE sur le coût réel ===")
APPELS = []
COUT_APPEL = 1.0


def faux_call_llm(task, prompt, documents=None, model=None, **k):
    version = k.get("prompt_version") or ""
    APPELS.append(version.rsplit(":", 1)[-1])
    if version.endswith(":fusion"):
        j = {"synthese_marche": "x", "bareme_notation": {}, "calendrier": {}}   # champs critiques manquants
    elif version.endswith(":controle"):
        j = {"trouve": False}
    else:
        j = {"type_confirme": "RC", "informations": {}}
    return types.SimpleNamespace(ok=True, erreur=None, json=j, cout_total_eur=COUT_APPEL, cout_eur=COUT_APPEL,
                                 tokens_in=10, tokens_out=10, modele="faux", repli=False,
                                 to_dict=lambda: {"ok": True, "modele": "faux"})


llm_router.call_llm = faux_call_llm
racine = TMP / "dce" / "PLAF"
racine.mkdir(parents=True)
for nom in ("RC.pdf", "CCAP.pdf", "CCTP.pdf"):
    (racine / nom).write_bytes(gen.pdf([[nom] + gen.remplir(8)]))


def lire(mid, plafond):
    APPELS.clear()
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        return MD.lire_dce(mid, str(racine), {"id": mid}, [], max_cout_par_dce=plafond, reprendre=False)


res = lire("PLAF", 1.5)
check("plafond atteint pendant les pièces : aucune fusion, pas de brief",
      "fusion" not in APPELS and res["brief"] is None and res["raison"] == "plafond_dce_atteint", (APPELS, res["raison"]))
check("coût réel rapporté (pièces payées)", res["cout_eur"] == APPELS.count("piece") * COUT_APPEL, res["cout_eur"])
trace = json.loads((P.DIR_PIECES / "PLAF" / "_trace.json").read_text(encoding="utf-8"))
check("pièces lues tracées pour la reprise (trace interrompue)",
      trace.get("interrompue") and len(trace.get("analyses_pieces") or []) == APPELS.count("piece"), trace.keys())

res = lire("PLAF", 3.5)
check("plafond atteint après la fusion : une seule recherche ciblée au plus, puis plus d'appel",
      APPELS.count("fusion") == 1 and APPELS.count("controle") == 0, APPELS)
check("brief gardé, marqué incomplet, champs non recherchés listés",
      res["ok"] and (res["brief"] or {}).get("_incomplet", {}).get("raison") == "plafond_dce_atteint"
      and len(res["brief"]["_incomplet"]["champs_non_recherches"]) == 6, (res.get("raison"), (res["brief"] or {}).get("_incomplet")))

res = lire("PLAF", None)
check("sans plafond : lecture complète (recherches ciblées faites)", APPELS.count("controle") >= 1 and res["ok"], APPELS)

# =====================================================================================
print("=== plan_ignore : un « plan » qui porte du texte est lu ===")
racine = TMP / "dce" / "PLANS"
racine.mkdir(parents=True)
long_ = [("Plan général de coordination : mesures de prévention, coactivité, accès au chantier, "
          "installations de chantier, consignes de sécurité applicables à toutes les entreprises. ") * 2] * 12
(racine / "plan_general_coordination.pdf").write_bytes(gen.pdf([long_, long_]))
(racine / "plan_masse.pdf").write_bytes(gen.pdf([["PLAN DE MASSE", "Échelle 1/200"]]))
(racine / "RC.pdf").write_bytes(gen.pdf([["RC"] + gen.remplir(8)]))
inv = P.inventorier("PLANS", str(racine), verbose=False)
noms = [p["nom"] for p in inv["pieces"]]
check("PGC nommé « plan… » mais rédigé : lu", "plan_general_coordination.pdf" in noms, noms)
check("vrai plan (peu de texte) : plan_ignore, avec sa moyenne de caractères",
      any(e["nom"] == "plan_masse.pdf" and e["statut"] == "plan_ignore" and "caractères par page" in e["detail"]
          for e in inv["ecartes"]), inv["ecartes"])

# =====================================================================================
print("=== ancien mode : rien n'est écrit dans data/dce ===")
source = TMP / "dce" / "CLASSIQUE"
source.mkdir(parents=True)
tampon = io.BytesIO()
with zipfile.ZipFile(tampon, "w") as z:
    z.writestr("sous/CCTP.pdf", gen.pdf([["CCTP"] + gen.remplir(8)]))
(source / "dce.zip").write_bytes(tampon.getvalue())
(source / "RC.pdf").write_bytes(gen.pdf([["RC"] + gen.remplir(8)]))
avant = sorted(f.name for f in source.rglob("*"))
dossiers = E.dossiers_lecture_classique(str(source))
pdfs = E.extraire_dossiers(dossiers)
check("le PDF du zip est lu, avec celui du 1er niveau", {"CCTP.pdf", "RC.pdf"} <= set(pdfs), sorted(pdfs))
check("dossier source inchangé (zip non déplacé, rien d'extrait à côté)",
      sorted(f.name for f in source.rglob("*")) == avant, sorted(f.name for f in source.rglob("*")))
check("extraction dans data/pieces/<id>/_classique",
      Path(dossiers[-1]) == P.dossier_travail("CLASSIQUE") / "_classique" and (Path(dossiers[-1]) / "CCTP.pdf").is_file())

shutil.rmtree(TMP, ignore_errors=True)
print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
