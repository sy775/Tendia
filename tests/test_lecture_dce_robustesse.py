# -*- coding: utf-8 -*-
"""
tests/test_lecture_dce_robustesse.py
------------------------------------
Tests HORS-LIGNE ajoutés après la relecture de l'étape 4 du chantier 2 (pieces,
mode_document, sources_lecture) :
  - identifiant de marché invalide refusé avant toute écriture ;
  - reconstruction de l'inventaire : rien n'est supprimé (ancien contenu archivé, trace
    conservée), inventaire invalidé quand le dossier source change ;
  - pièces homonymes lues toutes les deux, dossiers de zip raccourcis sans écrasement ;
  - pièce vide ou illisible jamais comptée « lue », aucun appel LLM dessus ;
  - estimation : alias résolus, modèle sans tarif refusé ;
  - reprise sur trace : par contenu, coût cumulé, trace partielle sur interruption ;
  - DCE sauté noté dans les journaux, kill switch en entrée, lecture visuelle d'un scan ;
  - extrait trop court jamais vérifié, rattachement de source non ambigu ;
  - gel des prompts du mode document (empreinte).

Lancement : python tests/test_lecture_dce_robustesse.py
"""
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

import importlib.util

from tendia.analyse import llm_router as R
from tendia.analyse import mode_document as MD
from tendia.analyse import pieces as P
from tendia.analyse import sources_lecture as SL
from tendia.core import budget
from tendia.core import logs as tendia_logs
from tendia.core.chemins import DATA

ok = ko = 0


def check(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}  {str(detail)[:500]}")


FIXTURES = Path(__file__).resolve().parent / "fixtures"
spec = importlib.util.spec_from_file_location("generateur_fixtures", FIXTURES / "generer_dce_mixte.py")
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

TMP = Path(tempfile.mkdtemp(prefix="tendia_rob_"))
assert Path(P.DIR_PIECES) == DATA / "pieces"
P.DIR_PIECES = TMP / "pieces"
P.DIR_PIECES.mkdir()


def pdf(titre, n=8):
    return gen.pdf([[titre] + gen.remplir(n)])


def dce(nom, fichiers: dict) -> Path:
    racine = TMP / "dce" / nom
    for chemin, contenu in fichiers.items():
        f = racine / chemin
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(contenu)
    racine.mkdir(parents=True, exist_ok=True)
    return racine


def instantane(racine: Path) -> dict:
    return {f.relative_to(racine).as_posix(): f.stat().st_size for f in racine.rglob("*") if f.is_file()}


# --- faux call_llm ------------------------------------------------------------------
APPELS = []
ECHEC_FUSION = {"actif": False}
LEVER = {"sur": None, "exception": None}


def faux_call_llm(task, prompt, documents=None, model=None, **kw):
    version = kw.get("prompt_version") or ""
    etape = version.rsplit(":", 1)[-1]
    APPELS.append({"etape": etape, "prompt": prompt, "documents": list(documents or []), "model": model, "kw": kw})
    if LEVER["sur"] and LEVER["sur"] in prompt[:200]:
        raise LEVER["exception"]
    if etape == "piece":
        nom = prompt.split("PIÈCE : ", 1)[1].split(" — ", 1)[0]
        j = {"type_confirme": "annexe", "informations": {
            "nature_document": {"valeur": f"contenu de {nom}", "pages": [1], "extrait": "Article 1"}},
            "autres_informations_importantes": []}
    elif etape == "fusion":
        if ECHEC_FUSION["actif"]:
            return R.LLMResult(ok=False, task="analyse", fournisseur="gemini", modele="gemini-4-argon",
                               erreur="reponse_non_json", cout_eur=0.02, cout_total_eur=0.02)
        j = {"synthese_marche": "fusion", "bareme_notation": {"valeur_technique_pct": 60, "valeur_prix_pct": 40},
             "calendrier": {"date_limite_offres": "2026-12-15 12:00"},
             "dossier_candidature": {"pieces_a_fournir": [{"libelle": "DC1", "phase": "candidature"}]},
             "complements_dce": {"visite": {"obligatoire": False, "modalites": None}},
             "montant_marche": {"valeur_estimee_euros": 1000}, "lots": [{"numero": 1, "intitule": "Lot 1"}]}
    else:
        j = {"trouve": False}
    return R.LLMResult(ok=True, task="analyse", fournisseur="gemini", modele="gemini-4-argon", json=j,
                       tokens_in=100, tokens_out=10, cout_eur=0.01, cout_total_eur=0.01)


R.call_llm = faux_call_llm
CTX = lambda mid: {"id": mid, "titre": "test"}


def lire(mid, racine, **kw):
    APPELS.clear()
    return MD.lire_dce(mid, str(racine), CTX(mid), ["btp"], verbose=False, **kw)


def pieces_appelees():
    return sorted(a["prompt"].split("PIÈCE : ", 1)[1].split(" — ", 1)[0] for a in APPELS if a["etape"] == "piece")


# =====================================================================================
print("=== identifiant de marché invalide ===")
victime = TMP / "xvictime"
victime.mkdir()
(victime / "precieux.txt").write_text("à ne jamais supprimer", encoding="utf-8")
source = dce("simple", {"RC.pdf": pdf("RÈGLEMENT DE LA CONSULTATION")})
for mauvais in ("../xvictime", str(victime), "a/b", "..", "", "   ", "_archive", None):
    leve = None
    try:
        P.inventorier(mauvais, str(source), verbose=False, force=True)
    except ValueError as e:
        leve = e
    except Exception as e:  # noqa: BLE001
        leve = e
    check(f"mid {mauvais!r} refusé (ValueError)", isinstance(leve, ValueError), repr(leve))
check("le dossier visé hors de DIR_PIECES est intact", (victime / "precieux.txt").exists())
leve = None
try:
    P.inventorier("RECOUVRE", str(P.DIR_PIECES / "RECOUVRE"), verbose=False)
except ValueError as e:
    leve = e
check("dossier source = dossier de travail : refusé", leve is not None)

print("=== reconstruction : rien n'est supprimé, la trace reste ===")
inv = P.inventorier("ARCH", str(source), verbose=False)
travail = P.DIR_PIECES / "ARCH"
(travail / "_trace.json").write_text('{"version": "x"}', encoding="utf-8")
(travail / "_temoin.txt").write_text("ancien contenu", encoding="utf-8")
inv2 = P.inventorier("ARCH", str(source), verbose=False, force=True)
archives = [d for d in (P.DIR_PIECES / "_archive").glob("ARCH_*")] if (P.DIR_PIECES / "_archive").is_dir() else []
check("force=True : l'ancien contenu est déplacé dans l'archive, pas supprimé",
      len(archives) == 1 and (archives[0] / "_temoin.txt").read_text(encoding="utf-8") == "ancien contenu",
      [str(a) for a in archives])
check("l'ancien inventaire est dans l'archive", archives and (archives[0] / "_inventaire.json").exists())
check("_trace.json (analyses payées) reste en place", (travail / "_trace.json").read_text(encoding="utf-8") == '{"version": "x"}')
check("le nouvel inventaire est écrit", (travail / "_inventaire.json").exists() and len(inv2["pieces"]) == 1)
check("prod : archive sous archive/data/pieces", str(P._dir_archive()).endswith("_archive"))
P_DIR = P.DIR_PIECES
P.DIR_PIECES = DATA / "pieces"
from tendia.core.chemins import ARCHIVE
check("DIR_PIECES de prod → archive/data/pieces", P._dir_archive() == ARCHIVE / "data" / "pieces", P._dir_archive())
P.DIR_PIECES = P_DIR

print("=== inventaire invalidé quand la source change ===")
source = dce("change", {"RC.pdf": pdf("RÈGLEMENT DE LA CONSULTATION")})
inv = P.inventorier("CHG", str(source), verbose=False)
inv_bis = P.inventorier("CHG", str(source), verbose=False)
check("source inchangée : inventaire relu tel quel", inv_bis == inv and inv.get("signature_source"))
(source / "CCAP.pdf").write_bytes(pdf("CAHIER DES CLAUSES ADMINISTRATIVES PARTICULIÈRES"))
(source / "RC.pdf").write_bytes(pdf("RÈGLEMENT DE LA CONSULTATION - version rectifiée", 12))
inv3 = P.inventorier("CHG", str(source), verbose=False)
check("pièce ajoutée et RC modifié : inventaire reconstruit (2 pièces, nouvelle signature)",
      len(inv3["pieces"]) == 2 and inv3["signature_source"] != inv["signature_source"],
      [p["nom"] for p in inv3["pieces"]])
check("le texte relu est celui de la version rectifiée",
      "rectifiée" in P.texte_piece(next(p for p in inv3["pieces"] if p["nom"] == "RC.pdf")))

print("=== pièces homonymes ===")
source = dce("homonymes", {"lot1/CCTP.pdf": pdf("CCTP du lot 1 : charpente"),
                           "lot2/CCTP.pdf": pdf("CCTP du lot 2 : couverture", 9)})
r = lire("HOMO", source)
noms = sorted(p["nom"] for p in r["inventaire"]["pieces"])
check("deux pièces de même nom : noms affichés distincts", noms == ["lot1/CCTP.pdf", "lot2/CCTP.pdf"], noms)
check("les deux sont analysées", pieces_appelees() == noms, pieces_appelees())
fusion = next(a["prompt"] for a in APPELS if a["etape"] == "fusion")
check("les deux analyses arrivent à la fusion (aucune en double, aucune perdue)",
      "contenu de lot1/CCTP.pdf" in fusion and "contenu de lot2/CCTP.pdf" in fusion)
check("2 lignes lues, pct_non_lu 0", r["lecture"]["nb_lues"] == 2 and r["lecture"]["pct_non_lu"] == 0.0, r["lecture"])
r = lire("HOMO", source)
check("reprise : aucune des deux n'est repayée, les deux restent dans la fusion",
      pieces_appelees() == [] and r["nb_pieces_reprises"] == 2
      and all(f"contenu de {n}" in next(a["prompt"] for a in APPELS if a["etape"] == "fusion") for n in noms))

print("=== dossiers de zip raccourcis : pas d'écrasement ===")
tampon = io.BytesIO()
long_ = "Dossier de consultation des entreprises - "
with zipfile.ZipFile(tampon, "w") as z:
    z.writestr(f"{long_}Lot 1/CCTP.pdf", pdf("CCTP du lot 1 : charpente"))
    z.writestr(f"{long_}Lot 2/CCTP.pdf", pdf("CCTP du lot 2 : couverture", 9))
    interne = io.BytesIO()
    with zipfile.ZipFile(interne, "w") as zi:
        zi.writestr("annexe_a.pdf", pdf("Annexe A du premier zip"))
    z.writestr("Pièces complémentaires du dossier - partie 1.zip", interne.getvalue())
    interne = io.BytesIO()
    with zipfile.ZipFile(interne, "w") as zi:
        zi.writestr("annexe_b.pdf", pdf("Annexe B du second zip", 9))
    z.writestr("Pièces complémentaires du dossier - partie 2.zip", interne.getvalue())
source = dce("zip_long", {"dce.zip": tampon.getvalue()})
inv = P.inventorier("ZIPLONG", str(source), verbose=False)
textes = " ".join(P.texte_piece(p) for p in inv["pieces"])
check("les 2 CCTP de dossiers au même préfixe de 30 caractères sont lus",
      "charpente" in textes and "couverture" in textes, [p["nom"] for p in inv["pieces"]])
check("les 2 zips imbriqués au même préfixe sont lus", "Annexe A" in textes and "Annexe B" in textes)
check("4 pièces, aucune erreur", len(inv["pieces"]) == 4 and not inv["erreurs"], inv["erreurs"])

print("=== pièce vide ou illisible : jamais « lue », aucun appel LLM ===")
source = dce("vides", {"RC.pdf": pdf("RÈGLEMENT DE LA CONSULTATION"),
                       "corrompu.pdf": b"%PDF-1.4 ceci n'est pas un PDF lisible",
                       "vide.txt": b"", "illisible.xlsx": b"pas un classeur",
                       "avis.html": "<html><body><h1>Avis de marché</h1><p>Travaux de réfection de toiture, "
                                    "date limite le 15 décembre 2026.</p><script>x()</script></body></html>".encode("utf-8")})
r = lire("VIDES", source)
statuts = {l["nom"]: l["statut"] for l in r["lecture"]["pieces"]}
check("PDF corrompu, .txt vide et .xlsx illisible : echec_conversion",
      all(statuts.get(n) == "echec_conversion" for n in ("corrompu.pdf", "vide.txt", "illisible.xlsx")), statuts)
check("aucun appel LLM sur ces trois fichiers", pieces_appelees() == ["RC.pdf", "avis.html"], pieces_appelees())
check("pct_non_lu compte les 3 pièces non lues (3 sur 5 = 60 %)", r["lecture"]["pct_non_lu"] == 60.0, r["lecture"]["pct_non_lu"])
avis = next(p for p in r["inventaire"]["pieces"] if p["nom"] == "avis.html")
check("page HTML lue comme du texte (balises et scripts retirés)",
      "réfection de toiture" in P.texte_piece(avis) and "x()" not in P.texte_piece(avis))

print("=== estimation : alias et tarif ===")
inv = r["inventaire"]
e_defaut, e_gemini, e_claude = MD.estimer_cout(inv), MD.estimer_cout(inv, "gemini"), MD.estimer_cout(inv, "claude")
check("alias gemini = modèle par défaut, coût > 0",
      e_gemini["modele"] == e_defaut["modele"] == "gemini-4-argon" and e_gemini["cout_eur"] == e_defaut["cout_eur"] > 0, e_gemini)
check("alias claude résolu en Sonnet 4.6, coût > 0", e_claude["modele"] == "claude-sonnet-4-6" and e_claude["cout_eur"] > 0, e_claude)
leve = None
try:
    MD.estimer_cout(inv, "claude-inconnu-9")
except ValueError as e:
    leve = e
check("modèle sans tarif : ValueError (pas d'estimation à 0 €)", leve is not None)

print("=== reprise sur trace ===")
source = dce("reprise", {"RC.pdf": pdf("RÈGLEMENT DE LA CONSULTATION"), "CCAP.pdf": pdf("CAHIER DES CLAUSES ADMINISTRATIVES PARTICULIÈRES"),
                         "CCTP.pdf": pdf("CAHIER DES CLAUSES TECHNIQUES PARTICULIÈRES")})
ECHEC_FUSION["actif"] = True
r1 = lire("REP", source)
ECHEC_FUSION["actif"] = False
check("fusion en échec : pas de brief, 3 pièces payées (0,03 €) + fusion (0,02 €)",
      not r1["ok"] and abs(r1["cout_eur"] - 0.05) < 1e-9 and len(pieces_appelees()) == 3, r1["cout_eur"])
check("la trace est écrite", (P.DIR_PIECES / "REP" / "_trace.json").exists())
r2 = lire("REP", source)
check("2e lecture : aucune pièce repayée, fusion seule", r2["ok"] and pieces_appelees() == []
      and [a["etape"] for a in APPELS] == ["fusion"], [a["etape"] for a in APPELS])
check("cout_eur = lecture courante (0,01 €), cout_cumule_eur = avec les pièces reprises (0,04 €)",
      abs(r2["cout_eur"] - 0.01) < 1e-9 and abs(r2["cout_cumule_eur"] - 0.04) < 1e-9 and r2["nb_pieces_reprises"] == 3,
      (r2["cout_eur"], r2["cout_cumule_eur"]))
r3 = lire("REP", source, reprendre=False)
check("reprendre=False : tout est relu", len(pieces_appelees()) == 3)
(source / "CCAP.pdf").write_bytes(pdf("CAHIER DES CLAUSES ADMINISTRATIVES PARTICULIÈRES - rectifié", 11))
r4 = lire("REP", source)
check("une pièce modifiée (même nom) est relue, les deux autres reprises",
      pieces_appelees() == ["CCAP.pdf"] and r4["nb_pieces_reprises"] == 2, pieces_appelees())
ancienne_version = MD.version_prompts
MD.version_prompts = lambda: "doc-autreversion"
r5 = lire("REP", source)
MD.version_prompts = ancienne_version
check("prompts changés : rien n'est repris", len(pieces_appelees()) == 3)

print("=== interruption : trace partielle ===")
source = dce("interrompu", {"RC.pdf": pdf("RÈGLEMENT DE LA CONSULTATION"), "CCAP.pdf": pdf("CAHIER DES CLAUSES ADMINISTRATIVES PARTICULIÈRES"),
                            "CCTP.pdf": pdf("CAHIER DES CLAUSES TECHNIQUES PARTICULIÈRES")})
LEVER.update(sur="PIÈCE : CCTP.pdf", exception=budget.BudgetDepasseError("plafond mensuel atteint"))
leve = None
try:
    lire("INT", source)
except budget.BudgetDepasseError as e:
    leve = e
LEVER.update(sur=None, exception=None)
check("BudgetDepasseError remonte de lire_dce", leve is not None)
trace = json.loads((P.DIR_PIECES / "INT" / "_trace.json").read_text(encoding="utf-8")) if (P.DIR_PIECES / "INT" / "_trace.json").exists() else {}
check("les pièces déjà analysées sont dans la trace partielle",
      sorted(a["piece"] for a in trace.get("analyses_pieces") or []) == ["CCAP.pdf", "RC.pdf"], trace.get("analyses_pieces"))
r = lire("INT", source)
check("à la reprise, seule la pièce interrompue est payée", r["ok"] and pieces_appelees() == ["CCTP.pdf"], pieces_appelees())

print("=== DCE sauté : noté ; kill switch en entrée ===")
r = lire("REP", source if False else TMP / "dce" / "reprise", max_cout_par_dce=0.0001)
journaux = list(Path(tendia_logs.LOG_DIR).glob("extraction_*.jsonl"))
lignes = [json.loads(l) for f in journaux for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
notes = [l for l in lignes if "dce_saute_cout_estime" in json.dumps(l)]
check("DCE sauté : raison cout_estime_depasse, aucun appel", r["raison"] == "cout_estime_depasse" and not APPELS)
check("le saut est noté dans le journal d'extraction (marché, estimation, plafond)",
      len(notes) >= 1 and "REP" in json.dumps(notes[-1]) and "0.0001" in json.dumps(notes[-1]), notes[-1:] or lignes[-1:])
config = dict(budget.DEFAUT_BUDGET, kill_switch_global=True)
budget.FICHIER_BUDGET.write_text(json.dumps(config), encoding="utf-8")
leve = None
try:
    lire("KS", TMP / "dce" / "simple")
except budget.BudgetDepasseError as e:
    leve = e
budget.FICHIER_BUDGET.write_text(json.dumps(dict(budget.DEFAUT_BUDGET)), encoding="utf-8")
check("kill switch : BudgetDepasseError avant tout inventaire et tout appel",
      leve is not None and not APPELS and not (P.DIR_PIECES / "KS").exists())
r = MD.lire_dce("KS", str(TMP / "dce" / "simple"), CTX("KS"), ["btp"], dry_run=True, verbose=False)
check("dry_run : inventaire et estimation même sans budget, aucun appel", r["raison"] == "dry_run" and r["estimation"]["cout_eur"] > 0)

print("=== lecture visuelle d'un scan ===")
source = dce("scan", {"RC_scanne.pdf": gen.pdf([[], [], []]), "CCAP.pdf": pdf("CAHIER DES CLAUSES ADMINISTRATIVES PARTICULIÈRES")})
r = lire("SCAN", source)
scan = next(p for p in r["inventaire"]["pieces"] if p["nom"] == "RC_scanne.pdf")
appel = next(a for a in APPELS if a["etape"] == "piece" and "RC_scanne.pdf" in a["prompt"][:80])
check("PDF sans texte : lecture visuelle, parties sous DIR_PIECES ou la source en lecture",
      scan["lecture_visuelle"] and scan["parties_pdf"])
check("le PDF est joint à l'appel et la consigne de lecture visuelle est dans le prompt",
      appel["documents"] == scan["parties_pdf"] and "lis-le visuellement" in appel["prompt"], appel["documents"])
check("le scan analysé est « lu »", {l["nom"]: l["statut"] for l in r["lecture"]["pieces"]}["RC_scanne.pdf"] == "lu")
check("tous les appels : JSON strict demandé au routeur", all(a["kw"].get("json_strict") is True for a in APPELS))

print("=== sources : extrait trop court, rattachement non ambigu, champ absent ===")
check("extraits sans valeur de preuve jamais vérifiés",
      not any(SL.verifier_extrait(e, "Le prix : oui, 1 lot. Article 12.") for e in (".", "1", "le", "oui", "12", " ")))
check("extrait réel toujours vérifié", SL.verifier_extrait("le prix : oui, 1 lot", "Le prix : oui, 1 lot. Article 12."))
inv_noms = {"pieces": [{"nom": n, "texte_fichier": None} for n in
                       ("CCTP_marche_travaux.pdf", "Annexe_maeva.pdf", "CCAP_lot1.pdf", "RC.pdf", "lot1/CCTP.pdf", "lot2/CCTP.pdf")]}
check("« RC » ne se rattache pas à CCTP_marche_travaux.pdf", SL._piece_par_nom(inv_noms, "RC")["nom"] == "RC.pdf")
check("« AE » ne se rattache pas à Annexe_maeva.pdf", SL._piece_par_nom(inv_noms, "AE") is None)
check("« 1 » ne se rattache à rien", SL._piece_par_nom(inv_noms, "1") is None)
check("nom ambigu entre deux homonymes : aucun rattachement", SL._piece_par_nom(inv_noms, "CCTP.pdf") is None)
check("nom complet d'un homonyme : rattaché", SL._piece_par_nom(inv_noms, "lot2/CCTP.pdf")["nom"] == "lot2/CCTP.pdf")
check("nom abrégé non ambigu : rattaché (« CCAP lot1 »)", SL._piece_par_nom(inv_noms, "CCAP lot1")["nom"] == "CCAP_lot1.pdf")
analyses = [{"piece": "BPU.xlsx", "type": "BPU_DPGF_DQE", "nb_pages": 1, "resultats": [
    {"partie": 1, "ok": True, "erreur": None, "json": {"informations": {
        "montants_renseignes": {"valeur": 5, "pages": ["BPU"], "extrait": "Prix unitaire HT"}}}}]}]
s = SL.construire_sources({"_controle_completude": {"montant": {"statut": "absent_confirme"}}}, analyses, {"pieces": []})
check("champ confirmé absent du DCE : pas de source (None)", s["montant"] is None, s["montant"])
ligne = SL.tableau_lecture({"pieces": [{"nom": "a.pdf", "type": "annexe", "nb_pages": 10, "chars": 5000,
                                        "lecture_visuelle": False, "pages_sans_texte": [3, 4]}], "ecartes": []},
                           [{"piece": "a.pdf", "resultats": [{"ok": True}]}])["pieces"][0]
check("PDF lu en texte avec 2 pages images : signalé dans la ligne de lecture",
      ligne["statut"] == "lu" and ligne["pages_sans_texte"] == 2 and "2 page" in (ligne["detail"] or ""), ligne)

print("=== gel des prompts du mode document ===")
# Les prompts sont repris de l'expérimentation (commit 3ba9a4b) sans modification : toute
# retouche change cette empreinte et doit être une décision explicite.
check("empreinte des prompts inchangée", MD.version_prompts() == "doc-17afee47a0", MD.version_prompts())
check("le rappel de format JSON du routeur est celui de l'expérimentation",
      R.RAPPEL_JSON == ("\n\nATTENTION : ta réponse précédente n'était pas un JSON "
                        "valide. Renvoie UNIQUEMENT un objet JSON strictement valide."))

print("=== le vrai data/pieces n'a rien reçu ===")
check("aucun dossier de test dans DATA / pieces",
      not any((DATA / "pieces" / m).exists() for m in ("ARCH", "CHG", "HOMO", "ZIPLONG", "VIDES", "REP", "INT", "KS", "SCAN")))
shutil.rmtree(TMP, ignore_errors=True)

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
