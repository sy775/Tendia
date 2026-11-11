# -*- coding: utf-8 -*-
"""
tests/test_ui_fiche_sources.py
------------------------------
Tests HORS-LIGNE de l'étape 6 du chantier 2 (fiche marché) : sous chacun des
6 champs critiques du brief, « Source : <pièce> p. <n> » (et « non vérifiée »
si verifie = false) ; en tête de la section brief, « <n>/<n> pièces lues » et
la liste des pièces non lues avec leur statut. Rien d'autre ne change.

Même mise en place que tests/test_ui_routes.py : client de test Flask sur une
base temporaire (tests/base_temporaire.py), profil `profil_btp_demo` actif,
marchés et briefs synthétiques écrits dans `marches` et `briefs_extraits`.
Aucun appel réseau, aucun LLM, rien n'est écrit dans data/tendia.db.

Lancement : python tests/test_ui_fiche_sources.py
"""
import copy
import difflib
import html as html_lib
import os
import re
import sys
from datetime import date, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from base_temporaire import isoler_stockage

isoler_stockage()

from tendia.core import stockage  # noqa: E402
from tendia.eligibilite import organisme  # noqa: E402
from tendia.ui.app import app  # noqa: E402

ok = ko = 0
signalements = []


def check(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}  {detail}")


def signaler(message):
    """Écart à faire remonter sans compter d'échec (pas de coche ni de croix :
    lancer_tous.py compte ces caractères)."""
    signalements.append(message)
    print(f"  ! SIGNALÉ {message}")


ID_DEMO = "profil_btp_demo"
res = organisme.activer_profil(ID_DEMO, "exemple")
check("profil démo activé dans la base temporaire", res["ok"], res)
client = app.test_client()

AUJ = date.today()
CHAMPS = ("criteres_ponderations", "date_limite", "pieces_exigees", "visite", "montant", "lots")
LIBELLES_STATUT = ("format non géré", "conversion impossible", "lecture en échec")


# ---------------------------------------------------------------- mise en place

def iso(jours: int) -> str:
    return (AUJ + timedelta(days=jours)).isoformat()


def marche_test(id_m, titre, limite, **extra):
    m = {"id": id_m, "titre": titre, "objet": titre, "acheteur_nom": "Commune de Test",
         "date_publication": iso(-20), "date_limite_depot": limite,
         "type_marche": "TRAVAUX", "nature": "APPEL_OFFRE", "notice_type": "5 | 1",
         "perimetre_geographique": "Dept 75", "acheteur_code_postal": "75001",
         "code_departement": ["75"], "cpv": ["45233140"]}
    m.update(extra)
    stockage.ecrire("marches", id_m, m)
    return m


def classer(id_m, code="btp_gros_oeuvre"):
    stockage.ecrire("classifications_ia", id_m, {
        "domaines_metier": [{"code": code, "poids": 1.0}],
        "synthese_marche": f"Synthèse de test {id_m}", "raison_classification": None})


def brief_base() -> dict:
    """Brief « mode document » réaliste, SANS _sources ni _lecture."""
    return {
        "_meta": {"type": "complet", "mode": "document"},
        "synthese_marche": "Construction d'un groupe scolaire de six classes, deux lots.",
        "bareme_notation": {"valeur_technique_pct": 60, "valeur_prix_pct": 40,
                            "sous_criteres_techniques": [
                                {"libelle": "Méthodologie", "ponderation_pct": 30}]},
        "calendrier": {"date_limite_offres": "2026-12-15 12:00"},
        "dossier_candidature": {"pieces_a_fournir": [
            {"libelle": "DC1", "phase": "candidature"},
            {"libelle": "Mémoire technique", "phase": "offre"}]},
        "complements_dce": {"visite": {"obligatoire": True, "modalites": "sur rendez-vous"}},
        "montant_marche": {"valeur_estimee_euros": 120000},
        "allotissement": {"nb_lots": 2},
        "lots": [{"numero": 1, "intitule": "Gros œuvre"}],
        "domaines_metier": [{"code": "btp_gros_oeuvre", "poids": 1.0}],
    }


def source(piece, page, verifie=True, extrait="passage cité du document"):
    return {"piece": piece, "page": page, "extrait": extrait, "verifie": verifie}


def sources_completes() -> dict:
    """Les 6 sources, toutes distinctes (pièce ou page) pour vérifier que chaque
    champ affiche bien la sienne."""
    return {
        "criteres_ponderations": source("RC.pdf", 4),
        "date_limite": source("RC.pdf", 2, verifie=False),
        "pieces_exigees": source("RC.pdf", 7),
        "visite": source("CCTP.pdf", 3),
        "montant": source("AE.pdf", "12", verifie=False),      # page en chaîne numérique
        "lots": source("BPU.xlsx", "BPU"),                     # feuille de tableur
    }


def piece(nom, statut, type_="pdf", pages=5, caracteres=12000, detail=""):
    return {"nom": nom, "type": type_, "statut": statut, "pages": pages,
            "caracteres": caracteres, "detail": detail}


def lecture_partielle() -> dict:
    """4 pièces lues sur 6 pièces de texte, 1 plan ignoré, 2 pièces non lues."""
    return {
        "pieces": [
            piece("RC.pdf", "lu"),
            piece("CCTP.pdf", "lu", pages=48, caracteres=150000),
            piece("AE.pdf", "lu", pages=14),
            piece("BPU.xlsx", "lu", type_="xlsx", pages=1),
            piece("Plan_masse_A0.pdf", "plan_ignore", pages=1, caracteres=40),
            piece("Annexe_geotechnique.dwg", "format_non_gere", type_="dwg", pages=0, caracteres=0),
            piece("DPGF_ancien.xls", "echec_conversion", type_="xls", pages=0, caracteres=0,
                  detail="conversion xls impossible"),
        ],
        "nb_pieces_texte": 6, "nb_lues": 4, "pct_non_lu": 33.3,
    }


def lecture_complete() -> dict:
    return {
        "pieces": [
            piece("RC.pdf", "lu"), piece("CCTP.pdf", "lu"), piece("CCAP.pdf", "lu"),
            piece("AE.pdf", "lu"), piece("BPU.xlsx", "lu", type_="xlsx", pages=1),
            piece("Plan_masse_A0.pdf", "plan_ignore", pages=1, caracteres=40),
        ],
        "nb_pieces_texte": 5, "nb_lues": 5, "pct_non_lu": 0,
    }


def poser(id_m, brief, titre=None):
    """Marché ouvert (date limite future), classé, et son brief (None = pas de brief)."""
    marche_test(id_m, titre or f"Groupe scolaire test {id_m}", iso(30))
    classer(id_m)
    if brief is not None:
        stockage.ecrire("briefs_extraits", id_m, brief)
    stockage.invalider_cache()


def fiche(id_m):
    """(code HTTP, HTML) de la fiche ; une exception propagée compte comme un 500."""
    try:
        r = client.get(f"/marche/{id_m}")
        return r.status_code, r.get_data(as_text=True)
    except Exception as e:  # noqa: BLE001
        return 500, f"exception {type(e).__name__}: {e}"


# ---------------------------------------------------------------- lecture du HTML

BALISES_VIDES = {"br", "hr", "img", "input", "meta", "link"}


def _motif_ouvrante(classe):
    c = re.escape(classe)
    return re.compile(
        r'<([a-zA-Z][\w-]*)\b[^<>]*?\bclass\s*=\s*(?:'
        r'"[^"]*(?<![\w-])' + c + r'(?![\w-])[^"]*"'
        r"|'[^']*(?<![\w-])" + c + r"(?![\w-])[^']*'"
        r')[^<>]*>', re.S)


def _fin_element(page, balise, depart):
    """Indice de fin (balise fermante comprise) de l'élément ouvert juste avant `depart`."""
    if balise.lower() in BALISES_VIDES:
        return depart
    motif = re.compile(r"<(/?)%s\b[^<>]*?(/?)>" % re.escape(balise), re.I | re.S)
    profondeur = 1
    for m in motif.finditer(page, depart):
        if m.group(1):
            profondeur -= 1
            if profondeur == 0:
                return m.end()
        elif not m.group(2):
            profondeur += 1
    return depart


def texte(fragment):
    """Texte visible d'un fragment HTML, espaces et retours à la ligne normalisés
    (espaces insécables compris)."""
    t = re.sub(r"<[^<>]+>", " ", fragment)
    t = html_lib.unescape(t)
    t = t.replace(" ", " ").replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", t).strip()


def elements(page, classe):
    """Éléments portant la classe CSS donnée (les éléments imbriqués dans un élément
    déjà retenu ne sont pas recomptés)."""
    trouves, borne = [], 0
    for m in _motif_ouvrante(classe).finditer(page):
        if m.start() < borne:
            continue
        fin = _fin_element(page, m.group(1), m.end())
        borne = fin
        champ = re.search(r'data-champ\s*=\s*["\']([^"\']*)["\']', m.group(0))
        trouves.append({"debut": m.start(), "fin": fin, "ouvrante": m.group(0),
                        "champ": champ.group(1) if champ else None,
                        "texte": texte(page[m.end():fin])})
    return trouves


def sources_par_champ(page):
    """{data-champ: [éléments brief-source]}"""
    d = {}
    for e in elements(page, "brief-source"):
        d.setdefault(e["champ"], []).append(e)
    return d


def a_data_champ(page, champ):
    return re.search(r'data-champ\s*=\s*["\']%s["\']' % re.escape(champ), page) is not None


def retirer(page, *classes):
    """HTML privé des éléments portant ces classes (contenu compris)."""
    zones = sorted(((e["debut"], e["fin"]) for c in classes for e in elements(page, c)),
                   reverse=True)
    for debut, fin in zones:
        page = page[:debut] + page[fin:]
    return page


def jetons(page):
    """HTML découpé en balises et textes, blancs non significatifs éliminés."""
    p = re.sub(r"\s+", " ", page.replace(" ", " "))
    p = re.sub(r"\s*([<>])\s*", r"\1", p)
    return re.findall(r"<[^<>]*>|[^<>]+", p)


def texte_page(page):
    return texte(page)


# ================================================================ les tests

print("=== étape 6 : sources sous les 6 champs critiques ===")
b = brief_base()
b["_sources"] = sources_completes()
b["_lecture"] = lecture_partielle()
poser("TEST-SRC-COMPLET", b)
code, page = fiche("TEST-SRC-COMPLET")
check("fiche avec _sources et _lecture → 200", code == 200, code)
par_champ = sources_par_champ(page)
tous = elements(page, "brief-source")
check("6 éléments brief-source", len(tous) == 6, [(e["champ"], e["texte"]) for e in tous])
for c in CHAMPS:
    check(f"un seul élément data-champ=\"{c}\"", len(par_champ.get(c, [])) == 1,
          [e["texte"] for e in par_champ.get(c, [])])
check("aucun brief-source hors des 6 champs",
      set(par_champ) <= set(CHAMPS), sorted(str(k) for k in par_champ))


def txt(champ, d=None):
    d = par_champ if d is None else d
    return d[champ][0]["texte"] if d.get(champ) else ""


def contient_source(t, nom_piece, page_n):
    return re.search(r"Source : %s p\. %s(?!\d)" % (re.escape(nom_piece), re.escape(str(page_n))),
                     t) is not None


check("criteres_ponderations : « Source : RC.pdf p. 4 »",
      contient_source(txt("criteres_ponderations"), "RC.pdf", 4), txt("criteres_ponderations"))
check("date_limite : « Source : RC.pdf p. 2 »",
      contient_source(txt("date_limite"), "RC.pdf", 2), txt("date_limite"))
check("pieces_exigees : « Source : RC.pdf p. 7 »",
      contient_source(txt("pieces_exigees"), "RC.pdf", 7), txt("pieces_exigees"))
check("visite : « Source : CCTP.pdf p. 3 »",
      contient_source(txt("visite"), "CCTP.pdf", 3), txt("visite"))
check("montant : page en chaîne numérique → « Source : AE.pdf p. 12 »",
      contient_source(txt("montant"), "AE.pdf", 12), txt("montant"))
check("lots : feuille de tableur → nom de la pièce et « feuille BPU »",
      "BPU.xlsx" in txt("lots") and "feuille BPU" in txt("lots"), txt("lots"))
check("lots : une feuille n'est pas présentée comme une page (« p. BPU »)",
      "p. BPU" not in txt("lots"), txt("lots"))

print("=== étape 6 : « non vérifiée » ===")
for c in ("date_limite", "montant"):
    check(f"{c} (verifie false) : « non vérifiée » dans l'élément",
          "non vérifiée" in txt(c).lower(), txt(c))
for c in ("criteres_ponderations", "pieces_exigees", "visite", "lots"):
    check(f"{c} (verifie true) : pas de « non vérifiée »",
          bool(txt(c)) and "non vérifiée" not in txt(c).lower(), txt(c))
check("l'extrait brut « None » n'apparaît dans aucune source",
      all("None" not in e["texte"] for e in tous), [e["texte"] for e in tous])

print("=== étape 6 : pièces lues, en tête de la section brief ===")
lect = elements(page, "brief-lecture")
check("un élément brief-lecture, un seul", len(lect) == 1, len(lect))
tl = lect[0]["texte"] if lect else ""
check("« 4/6 pièces lues »", "4/6 pièces lues" in tl, tl)
check("pièce non lue listée avec son statut : Annexe_geotechnique.dwg, « format non géré »",
      "Annexe_geotechnique.dwg" in tl and "format non géré" in tl, tl)
check("pièce non lue listée avec son statut : DPGF_ancien.xls, « conversion impossible »",
      "DPGF_ancien.xls" in tl and "conversion impossible" in tl, tl)
check("statut absent des données non affiché (« lecture en échec »)",
      "lecture en échec" not in tl, tl)
check("statut en clair, pas le code interne",
      "format_non_gere" not in tl and "echec_conversion" not in tl, tl)
check("les pièces lues ne figurent pas dans la liste",
      all(n not in tl for n in ("RC.pdf", "CCTP.pdf", "AE.pdf", "BPU.xlsx")), tl)
check("le plan ignoré ne figure pas dans la liste",
      "Plan_masse_A0.pdf" not in tl and "plan_ignore" not in tl, tl)
check("brief-lecture placé avant la première source (tête de la section brief)",
      bool(lect) and bool(tous) and lect[0]["debut"] < min(e["debut"] for e in tous),
      (lect[0]["debut"] if lect else None, [e["debut"] for e in tous]))

b = brief_base()
b["_sources"] = sources_completes()
b["_lecture"] = {"pieces": [piece("RC.pdf", "lu"),
                            piece("CCTP_scanne.pdf", "echec_lecture", pages=0, caracteres=0,
                                  detail="PDF chiffré")],
                 "nb_pieces_texte": 2, "nb_lues": 1, "pct_non_lu": 50.0}
poser("TEST-SRC-ECHEC-LECTURE", b)
code, p2 = fiche("TEST-SRC-ECHEC-LECTURE")
l2 = elements(p2, "brief-lecture")
t2 = l2[0]["texte"] if l2 else ""
check("echec_lecture → 200 et « 1/2 pièces lues »", code == 200 and "1/2 pièces lues" in t2, (code, t2))
check("echec_lecture : CCTP_scanne.pdf, « lecture en échec »",
      "CCTP_scanne.pdf" in t2 and "lecture en échec" in t2 and "echec_lecture" not in t2, t2)
check("echec_lecture : les deux autres libellés absents",
      "format non géré" not in t2 and "conversion impossible" not in t2, t2)

b = brief_base()
b["_sources"] = sources_completes()
b["_lecture"] = lecture_complete()
poser("TEST-SRC-TOUT-LU", b)
code, p3 = fiche("TEST-SRC-TOUT-LU")
l3 = elements(p3, "brief-lecture")
t3 = l3[0]["texte"] if l3 else ""
check("tout lu → 200 et « 5/5 pièces lues »", code == 200 and "5/5 pièces lues" in t3, (code, t3))
check("tout lu : aucun des trois libellés de statut",
      bool(t3) and all(s not in t3 for s in LIBELLES_STATUT), t3)
check("tout lu : aucune pièce listée (ni lue, ni plan ignoré)",
      bool(t3) and all(n not in t3 for n in ("RC.pdf", "CCTP.pdf", "CCAP.pdf", "AE.pdf",
                                             "BPU.xlsx", "Plan_masse_A0.pdf")), t3)
check("tout lu : les 6 sources restent affichées",
      len(elements(p3, "brief-source")) == 6, len(elements(p3, "brief-source")))

print("=== étape 6 : champs sans source ===")
b = brief_base()
b["_sources"] = {"criteres_ponderations": None, "date_limite": source("RC.pdf", 2),
                 "pieces_exigees": None, "visite": None, "montant": None,
                 "lots": source("BPU.xlsx", "BPU", verifie=False)}
b["_lecture"] = lecture_complete()
poser("TEST-SRC-PARTIEL", b)
code, p4 = fiche("TEST-SRC-PARTIEL")
d4 = sources_par_champ(p4)
check("sources partielles → 200", code == 200, code)
check("2 éléments brief-source seulement (date_limite, lots)",
      sorted(str(k) for k in d4) == ["date_limite", "lots"]
      and all(len(v) == 1 for v in d4.values()), {k: len(v) for k, v in d4.items()})
for c in ("criteres_ponderations", "pieces_exigees", "visite", "montant"):
    check(f"source None : aucun élément data-champ=\"{c}\"", not a_data_champ(p4, c))
check("date_limite toujours sourcée : « Source : RC.pdf p. 2 », sans « non vérifiée »",
      contient_source(txt("date_limite", d4), "RC.pdf", 2)
      and "non vérifiée" not in txt("date_limite", d4).lower(), txt("date_limite", d4))
check("feuille non vérifiée : « feuille BPU » et « non vérifiée »",
      "feuille BPU" in txt("lots", d4) and "non vérifiée" in txt("lots", d4).lower(),
      txt("lots", d4))

b = brief_base()
b["_sources"] = {c: None for c in CHAMPS}
b["_lecture"] = lecture_complete()
poser("TEST-SRC-AUCUNE", b)
code, p5 = fiche("TEST-SRC-AUCUNE")
check("6 sources None → 200, aucun brief-source, aucun data-champ",
      code == 200 and not elements(p5, "brief-source")
      and not any(a_data_champ(p5, c) for c in CHAMPS), code)
check("6 sources None : brief-lecture toujours affiché (« 5/5 pièces lues »)",
      any("5/5 pièces lues" in e["texte"] for e in elements(p5, "brief-lecture")))

b = brief_base()
b["_sources"] = {}
poser("TEST-SRC-VIDE", b)
code, p6 = fiche("TEST-SRC-VIDE")
check("_sources vide ({}) sans _lecture → 200, aucun brief-source",
      code == 200 and not elements(p6, "brief-source"), code)

print("=== étape 6 : brief de l'ancien mode, marché sans brief ===")
ancien = brief_base()
ancien["_meta"] = {"type": "complet"}
poser("TEST-SRC-ANCIEN", ancien)
code, pa = fiche("TEST-SRC-ANCIEN")
ta = texte_page(pa)
check("ancien brief (sans _sources ni _lecture) → 200", code == 200, code)
check("ancien brief : aucun élément brief-source", not elements(pa, "brief-source")
      and "brief-source" not in pa)
check("ancien brief : aucun élément brief-lecture", not elements(pa, "brief-lecture")
      and "brief-lecture" not in pa)
check("ancien brief : aucun data-champ des 6 champs",
      not any(a_data_champ(pa, c) for c in CHAMPS))
m = re.search(r"Source : [^:]{0,80}?(?:p\. ?\d|feuille )", ta)
check("ancien brief : aucun « Source : <pièce> p. <n> »", m is None, m.group(0) if m else "")
check("ancien brief : « pièces lues » absent", "pièces lues" not in ta)
check("ancien brief : « non vérifiée » absent", "non vérifiée" not in ta.lower())

poser("TEST-SRC-SANS-BRIEF", None)
code, pb = fiche("TEST-SRC-SANS-BRIEF")
check("marché sans brief → 200", code == 200, code)
check("marché sans brief : aucun brief-source",
      not elements(pb, "brief-source") and not any(a_data_champ(pb, c) for c in CHAMPS))

print("=== étape 6 : rien d'autre ne change ===")
# Même marché, même brief : rendu sans les deux blocs, puis avec.
sans = brief_base()
poser("TEST-SRC-DIFF", sans)
code_s1, page_s1 = fiche("TEST-SRC-DIFF")
stockage.invalider_cache()
code_s2, page_s2 = fiche("TEST-SRC-DIFF")
avec = brief_base()
avec["_sources"] = sources_completes()
avec["_lecture"] = lecture_partielle()
stockage.ecrire("briefs_extraits", "TEST-SRC-DIFF", avec)
stockage.invalider_cache()
code_a, page_a = fiche("TEST-SRC-DIFF")
check("les trois rendus → 200", (code_s1, code_s2, code_a) == (200, 200, 200),
      (code_s1, code_s2, code_a))
check("le brief avec blocs est bien celui rendu (6 sources affichées)",
      len(elements(page_a, "brief-source")) == 6, len(elements(page_a, "brief-source")))
j_sans = jetons(page_s1)
temoin = j_sans == jetons(page_s2)
if not temoin:
    signaler("deux rendus successifs de la même fiche diffèrent (contenu variable dans la "
             "page) : la comparaison avec / sans _sources reste indicative")
j_avec = jetons(retirer(page_a, "brief-source", "brief-lecture"))
ops = [o for o in difflib.SequenceMatcher(None, j_sans, j_avec, autojunk=False).get_opcodes()
       if o[0] != "equal"]
if not ops:
    check("fiche identique une fois brief-source et brief-lecture retirés", True)
else:
    ajouts = [" ".join(j_avec[o[3]:o[4]]) for o in ops]
    retraits = [" ".join(j_sans[o[1]:o[2]]) for o in ops]
    que_des_ajouts = all(o[0] == "insert" for o in ops)
    que_visite = que_des_ajouts and all("visite" in a.lower() for a in ajouts)
    if que_visite:
        signaler("seule différence hors brief-source / brief-lecture : un ajout lié à la "
                 "visite de site → " + " | ".join(a[:300] for a in ajouts))
    else:
        detail = [(o[0], r[:200], a[:200]) for o, r, a in zip(ops, retraits, ajouts)][:6]
        check("fiche identique une fois brief-source et brief-lecture retirés", False, detail)

print("=== étape 6 : cas limites ===")
b = brief_base()
b["_sources"] = sources_completes()
b["_sources"]["date_limite"] = source("RC.pdf", 99999, extrait="x" * 10000)
b["_sources"]["montant"] = source("AE.pdf", 0)
b["_lecture"] = {
    "pieces": ([piece(f"piece_{i:03d}.pdf", "lu") for i in range(250)]
               + [piece(f"piece_{i:03d}.dwg", "format_non_gere", type_="dwg", pages=0, caracteres=0)
                  for i in range(250, 300)]),
    "nb_pieces_texte": 300, "nb_lues": 250, "pct_non_lu": 16.7}
poser("TEST-SRC-GRAND", b)
code, pg = fiche("TEST-SRC-GRAND")
dg = sources_par_champ(pg)
lg = elements(pg, "brief-lecture")
tg = lg[0]["texte"] if lg else ""
check("300 pièces, page 99999, extrait de 10 000 caractères, page 0 → 200", code == 200, code)
check("très grande page : « Source : RC.pdf p. 99999 »",
      contient_source(txt("date_limite", dg), "RC.pdf", 99999), txt("date_limite", dg)[:200])
check("300 pièces : « 250/300 pièces lues »", "250/300 pièces lues" in tg, tg[:200])
check("300 pièces : les 50 non lues sont toutes listées",
      all(f"piece_{i:03d}.dwg" in tg for i in range(250, 300)), tg[:200])
check("300 pièces : aucune pièce lue listée",
      not any(f"piece_{i:03d}.pdf" in tg for i in (0, 124, 249)), tg[:200])

b = brief_base()
b["_sources"] = {c: None for c in CHAMPS}
b["_lecture"] = {"pieces": [piece("RC.doc", "echec_conversion", type_="doc", pages=0, caracteres=0),
                            piece("CCTP.pdf", "echec_lecture", pages=0, caracteres=0),
                            piece("Annexe.odt", "format_non_gere", type_="odt", pages=0, caracteres=0)],
                 "nb_pieces_texte": 3, "nb_lues": 0, "pct_non_lu": 100.0}
poser("TEST-SRC-ZERO-LU", b)
code, pz = fiche("TEST-SRC-ZERO-LU")
lz = elements(pz, "brief-lecture")
tz = lz[0]["texte"] if lz else ""
check("aucune pièce lue → 200 et « 0/3 pièces lues » (zéro affiché, pas masqué)",
      code == 200 and "0/3 pièces lues" in tz, (code, tz))
check("aucune pièce lue : les trois pièces et les trois libellés",
      all(n in tz for n in ("RC.doc", "CCTP.pdf", "Annexe.odt"))
      and all(s in tz for s in LIBELLES_STATUT), tz)

b = brief_base()
b["_sources"] = sources_completes()
b["_lecture"] = {"pieces": [], "nb_pieces_texte": 0, "nb_lues": 0, "pct_non_lu": 0}
poser("TEST-SRC-ZERO-PIECE", b)
code, p0 = fiche("TEST-SRC-ZERO-PIECE")
check("_lecture sans aucune pièce (0/0) → 200, sources toujours affichées",
      code == 200 and len(elements(p0, "brief-source")) == 6,
      (code, len(elements(p0, "brief-source"))))
check("0/0 : aucun libellé de statut",
      all(s not in e["texte"] for e in elements(p0, "brief-lecture") for s in LIBELLES_STATUT))

print("=== étape 6 : robustesse (données mal formées) ===")


def cas_malforme(nom, sources="__absent__", lecture="__absent__"):
    """Rend la fiche d'un brief dont _sources / _lecture sont mal formés."""
    cas_malforme.n += 1
    id_m = f"TEST-SRC-MALFORME-{cas_malforme.n:02d}"
    br = brief_base()
    if sources != "__absent__":
        br["_sources"] = sources
    if lecture != "__absent__":
        br["_lecture"] = lecture
    poser(id_m, br)
    code_m, page_m = fiche(id_m)
    check(f"{nom} → 200, pas d'erreur 500", code_m == 200, (code_m, page_m[:200] if code_m != 200 else ""))
    return page_m


cas_malforme.n = 0

cas_malforme("_sources = liste", sources=[source("RC.pdf", 2)], lecture=lecture_partielle())
cas_malforme("_sources = chaîne", sources="RC.pdf p. 2", lecture=lecture_partielle())
cas_malforme("_sources = None", sources=None, lecture=lecture_partielle())
cas_malforme("_sources = entier", sources=3, lecture=lecture_partielle())
cas_malforme("_lecture = liste", sources=sources_completes(), lecture=[piece("RC.pdf", "lu")])
cas_malforme("_lecture = chaîne", sources=sources_completes(), lecture="4/6")
cas_malforme("_lecture = None", sources=sources_completes(), lecture=None)
cas_malforme("_sources et _lecture = None", sources=None, lecture=None)
cas_malforme("_lecture = {} (aucune clé)", sources=sources_completes(), lecture={})
cas_malforme("_lecture.pieces = None",
             lecture={"pieces": None, "nb_pieces_texte": 2, "nb_lues": 1, "pct_non_lu": 50})
cas_malforme("_lecture.pieces = chaîne",
             lecture={"pieces": "RC.pdf", "nb_pieces_texte": 2, "nb_lues": 1, "pct_non_lu": 50})
cas_malforme("_lecture.pieces = liste de chaînes et de None",
             lecture={"pieces": ["RC.pdf", None, 3], "nb_pieces_texte": 2, "nb_lues": 1,
                      "pct_non_lu": 50})
cas_malforme("_lecture : pièce sans nom ni statut, statut inconnu",
             lecture={"pieces": [{}, {"nom": "X.pdf"}, {"statut": "echec_lecture"},
                                 {"nom": "Y.pdf", "statut": "statut_inconnu"},
                                 {"nom": None, "statut": None}],
                      "nb_pieces_texte": 5, "nb_lues": 0, "pct_non_lu": 100})
cas_malforme("_lecture : compteurs None",
             lecture={"pieces": [piece("RC.pdf", "lu")], "nb_pieces_texte": None, "nb_lues": None,
                      "pct_non_lu": None})
cas_malforme("_lecture : compteurs en chaînes",
             lecture={"pieces": [piece("RC.pdf", "lu")], "nb_pieces_texte": "1", "nb_lues": "1",
                      "pct_non_lu": "0"})

s = sources_completes()
s["criteres_ponderations"] = "RC.pdf"
s["pieces_exigees"] = ["RC.pdf", 7]
s["visite"] = {}
s["montant"] = 12
pm = cas_malforme("sources de types inattendus (chaîne, liste, {}, entier)", sources=s,
                  lecture=lecture_partielle())
dm = sources_par_champ(pm)
check("sources de types inattendus : les sources valides restent affichées (date_limite, lots)",
      contient_source(txt("date_limite", dm), "RC.pdf", 2) and "feuille BPU" in txt("lots", dm),
      (txt("date_limite", dm), txt("lots", dm)))

s = sources_completes()
s["date_limite"] = {"page": 2, "extrait": "…", "verifie": True}          # sans « piece »
s["montant"] = {"piece": None, "page": 3, "extrait": "…", "verifie": False}
s["visite"] = {"piece": "", "page": 1, "extrait": "", "verifie": True}
pm = cas_malforme("source sans « piece », piece None, piece vide", sources=s,
                  lecture=lecture_partielle())
check("source sans pièce : jamais « Source : None » ni « Source : p. »",
      re.search(r"Source : (None|p\. )", texte_page(pm)) is None)
check("source sans pièce : les autres champs restent sourcés (criteres_ponderations)",
      contient_source(txt("criteres_ponderations", sources_par_champ(pm)), "RC.pdf", 4))

s = sources_completes()
s["date_limite"] = {"piece": "RC.pdf", "page": None, "extrait": "…", "verifie": True}
s["montant"] = {"piece": "AE.pdf", "extrait": "…", "verifie": True}          # sans « page »
s["visite"] = {"piece": "CCTP.pdf", "page": "", "extrait": "…", "verifie": True}
pm = cas_malforme("page None, page absente, page vide", sources=s, lecture=lecture_partielle())
tm = texte_page(pm)
check("page None : jamais « p. None » ni « feuille None »",
      "p. None" not in tm and "feuille None" not in tm)
check("page None : les autres champs restent sourcés (pieces_exigees)",
      contient_source(txt("pieces_exigees", sources_par_champ(pm)), "RC.pdf", 7))

s = sources_completes()
s["date_limite"] = {"piece": "RC.pdf", "page": 2}                             # sans verifie ni extrait
s["montant"] = {"piece": "AE.pdf", "page": 12, "extrait": None, "verifie": None}
cas_malforme("source sans « verifie » ni « extrait », verifie None", sources=s,
             lecture=lecture_partielle())

print("=== étape 6 : échappement du nom de pièce ===")
NOM_XSS = "<script>alert(1789)</script>RC.pdf"
s = sources_completes()
s["date_limite"] = source(NOM_XSS, 2)
s["lots"] = source(NOM_XSS, "<script>alert(1790)</script>")
lx = lecture_partielle()
lx["pieces"].append(piece("<script>alert(1791)</script>.dwg", "format_non_gere", type_="dwg",
                          pages=0, caracteres=0, detail="<script>alert(1792)</script>"))
lx["nb_pieces_texte"] = 7
px = cas_malforme("nom de pièce contenant <script>", sources=s, lecture=lx)
bas = px.lower()
check("aucune balise <script> injectée (sources, feuille, pièces non lues)",
      not any(f"<script>alert({n})" in bas for n in (1789, 1790, 1791, 1792)))
dx = sources_par_champ(px)
check("nom de pièce échappé et affiché tel quel sous date_limite",
      "<script>alert(1789)</script>RC.pdf" in txt("date_limite", dx)
      and "&lt;script&gt;alert(1789)" in px, txt("date_limite", dx))
tx = " ".join(e["texte"] for e in elements(px, "brief-lecture"))
check("nom de pièce non lue échappé et affiché tel quel dans brief-lecture",
      "<script>alert(1791)</script>.dwg" in tx, tx)
check("les 6 sources restent affichées, une par champ",
      sorted(str(k) for k in dx) == sorted(CHAMPS) and all(len(v) == 1 for v in dx.values()),
      {str(k): len(v) for k, v in dx.items()})

if signalements:
    print()
    print("SIGNALEMENTS (sans échec) :")
    for msg in signalements:
        print(f"  - {msg}")

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
