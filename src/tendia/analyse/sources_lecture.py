"""
tendia/analyse/sources_lecture.py
---------------------------------
Sources vérifiées et taux de lecture d'un brief du mode document, SANS LLM :

- construire_sources : `_sources` du brief, pour chacun des 6 champs critiques la pièce,
  la page, un extrait (≤ 200 caractères) et `verifie` (l'extrait figure dans le texte de
  la page citée, casse, espaces, ligatures et apostrophes normalisés). `verifie` prouve
  que l'extrait existe à cet endroit, pas qu'il porte la valeur retenue par le brief.
- tableau_lecture : `_lecture` du brief, une ligne par pièce avec son statut, et
  `pct_non_lu`.
"""

import json
import re
import unicodedata
from typing import Optional

from tendia.analyse import pieces as P

CHAMPS_SOURCES = ("criteres_ponderations", "date_limite", "pieces_exigees", "visite", "montant", "lots")
LONGUEUR_MAX_EXTRAIT = 200

# Champ critique → clé du bloc "_sources" rendu par le modèle, et questions par pièce qui le renseignent.
_CHEMIN_MODELE = {
    "criteres_ponderations": "bareme_notation",
    "date_limite": "calendrier.date_limite_offres",
    "pieces_exigees": "dossier_candidature.pieces_a_fournir",
    "visite": "complements_dce.visite",
    "montant": "montant_marche",
    "lots": "lots",
}
_QUESTIONS_DU_CHAMP = {
    "criteres_ponderations": ("criteres_attribution", "criteres_par_lot"),
    "date_limite": ("date_limite_remise",),
    "pieces_exigees": ("pieces_candidature", "pieces_offre"),
    "visite": ("visite",),
    "montant": ("montant_estime", "montant", "montants_renseignes"),
    "lots": ("lots", "lot"),
}

_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'", "´": "'", "«": '"', "»": '"',
                              "“": '"', "”": '"', "–": "-", "—": "-", "‑": "-", " ": " ",
                              " ": " ", " ": " ", "œ": "oe", "Œ": "OE", "æ": "ae", "Æ": "AE"})


def normaliser_extrait(s) -> str:
    """Forme de comparaison d'un extrait et d'une page : ligatures décomposées (ﬁ, ﬂ, œ),
    apostrophes et tirets typographiques ramenés à l'ASCII, minuscules, toute suite
    d'espaces ou de retours à la ligne réduite à une espace."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s)).translate(_APOSTROPHES)
    return re.sub(r"\s+", " ", s).strip().lower()


LONGUEUR_MIN_EXTRAIT = 5      # caractères alphanumériques : « oui », « 1 », « le » ne prouvent rien


# Coupes qu'un modèle met dans une citation condensée : « début [...] suite », « a / b / c ».
_RE_COUPE = re.compile(r"\s*(?:\[\s*(?:\.\.\.|…)\s*\]|\(\s*(?:\.\.\.|…)\s*\)|\.\.\.|…|\s/\s)\s*")


def fragments_extrait(extrait) -> list:
    """Fragments d'un extrait normalisé, coupé aux ellipses et aux « / » de mise en liste.
    Seuls les fragments d'au moins LONGUEUR_MIN_EXTRAIT caractères alphanumériques comptent."""
    return [f.strip() for f in _RE_COUPE.split(normaliser_extrait(extrait))
            if sum(c.isalnum() for c in f) >= LONGUEUR_MIN_EXTRAIT]


def verifier_extrait(extrait, texte_page) -> bool:
    """True si l'extrait figure dans le texte de la page (formes normalisées). Sans LLM.
    Une citation condensée (« début [...] suite ») est vérifiée fragment par fragment :
    TOUS ses fragments doivent figurer dans la page. Un extrait (ou un fragment) de moins
    de LONGUEUR_MIN_EXTRAIT caractères alphanumériques ne prouve rien : on le trouverait
    sur n'importe quelle page."""
    fragments = fragments_extrait(extrait)
    if not fragments:
        return False
    page = normaliser_extrait(texte_page)
    return all(f in page for f in fragments)


def _numero_page(page):
    """2, "2", "p. 2", "Page 2" → 2 ; un nom de feuille reste une chaîne ; None sinon."""
    if page is None or isinstance(page, bool):
        return None
    if isinstance(page, int):
        return page
    if isinstance(page, float) and page.is_integer():
        return int(page)
    s = str(page).strip()
    if not s:
        return None
    m = re.fullmatch(r"(?:p(?:age)?\.?\s*)?(\d+)", s, re.I)
    if m:
        return int(m.group(1))
    return s[8:].strip() if s.lower().startswith("feuille ") else s


def _pages(valeur) -> list:
    """Pages citées, à plat : [2], "2", "p. 5, 16-35" → [5, 16, 17, …, 35] ; une feuille
    reste un nom."""
    if valeur is None:
        return []
    if not isinstance(valeur, (list, tuple)):
        valeur = [valeur]
    pages = []
    for v in valeur:
        if isinstance(v, str) and re.fullmatch(r"\s*(?:p(?:ages?)?\.?\s*)?\d+(?:\s*[-–]\s*\d+)?(?:\s*[,;]\s*\d+(?:\s*[-–]\s*\d+)?)+\s*|"
                                               r"\s*(?:p(?:ages?)?\.?\s*)?\d+\s*[-–]\s*\d+\s*", v, re.I):
            for debut, fin in re.findall(r"(\d+)(?:\s*[-–]\s*(\d+))?", v):
                a, b = int(debut), int(fin or debut)
                pages.extend(range(a, min(b, a + 60) + 1) if b >= a else [a])
            continue
        p = _numero_page(v)
        if p is not None:
            pages.append(p)
    return pages


def _piece_par_nom(inv: dict, nom) -> Optional[dict]:
    """Pièce de l'inventaire citée par le modèle (nom exact, puis casse, puis sans extension)."""
    if not nom:
        return None
    pieces = (inv or {}).get("pieces") or []
    cle = str(nom).strip()
    for egal in (lambda p: p["nom"] == cle,
                 lambda p: p["nom"].lower() == cle.lower(),
                 lambda p: p["nom"].rsplit("/", 1)[-1].lower() == cle.rsplit("/", 1)[-1].lower(),
                 lambda p: P._norm(p["nom"].rsplit(".", 1)[0]) == P._norm(cle.rsplit(".", 1)[0])):
        trouvees = [p for p in pieces if egal(p)]
        if len(trouvees) == 1:
            return trouvees[0]
        if trouvees:
            return None                # nom ambigu (pièces homonymes) : pas de rattachement au hasard
    # nom abrégé par le modèle : tous ses mots, entiers, dans le nom d'UNE seule pièce
    mots = P._norm(cle.rsplit(".", 1)[0]).split()
    if len("".join(mots)) >= 4:
        trouvees = [p for p in pieces if set(mots) <= set(P._norm(p["nom"].rsplit(".", 1)[0]).split())]
        if len(trouvees) == 1:
            return trouvees[0]
    return None


def _texte_extrait(valeur) -> Optional[str]:
    if valeur is None:
        return None
    s = valeur if isinstance(valeur, str) else json.dumps(valeur, ensure_ascii=False)
    s = s.strip()
    return s[:LONGUEUR_MAX_EXTRAIT] if s else None


def _source(inv: dict, nom_piece, pages, extrait) -> Optional[dict]:
    """Une source vérifiée : l'extrait (≤ 200 caractères) est cherché dans chaque page
    citée ; la page retenue est la première où il figure. S'il n'est sur aucune page citée
    mais figure ailleurs dans la MÊME pièce, la page est corrigée (la page citée par le
    modèle est gardée dans "page_citee") : la citation affichée est alors exacte. Sinon la
    source reste sur la première page citée, non vérifiée."""
    piece = _piece_par_nom(inv, nom_piece)
    nom = piece["nom"] if piece else (str(nom_piece) if nom_piece else None)
    if not nom:
        return None
    pages = _pages(pages)
    extrait = _texte_extrait(extrait)
    page, verifie = (pages[0] if pages else None), False
    source = {"piece": nom, "page": page, "extrait": extrait, "verifie": False}
    if piece and extrait:
        for p in pages:
            if verifier_extrait(extrait, P.texte_page(piece, p)):
                page, verifie = p, True
                break
        if not verifie:
            for cle, texte in P.pages_de(piece):
                if cle not in pages and verifier_extrait(extrait, texte):
                    source["page_citee"] = page
                    page, verifie = cle, True
                    break
    source.update(page=page, verifie=verifie)
    return source


def _informations(analyses: list, nom_piece: str, questions: tuple) -> list:
    """[(pages, extrait)] des réponses non nulles de cette pièce aux questions du champ."""
    trouvees = []
    for a in analyses or []:
        if a.get("piece") != nom_piece:
            continue
        for r in a.get("resultats") or []:
            infos = ((r.get("json") or {}).get("informations") or {}) if isinstance(r.get("json"), dict) else {}
            for q in questions:
                info = infos.get(q)
                if isinstance(info, dict) and info.get("valeur") not in (None, "", [], {}):
                    trouvees.append((_pages(info.get("pages")), info.get("extrait")))
    return trouvees


def _source_depuis_analyses(inv: dict, analyses: list, nom_piece: str, questions: tuple,
                            page_citee=None) -> Optional[dict]:
    infos = _informations(analyses, nom_piece, questions)
    if not infos:
        return None
    # de préférence la réponse dont les pages contiennent la page citée par la fusion
    infos.sort(key=lambda i: (page_citee not in i[0], not i[1]))
    candidates = [_source(inv, nom_piece, pages or ([page_citee] if page_citee is not None else []), extrait)
                  for pages, extrait in infos]
    candidates = [c for c in candidates if c]
    return next((c for c in candidates if c["verifie"]), candidates[0] if candidates else None)


def construire_sources(brief: dict, analyses: list, inv: dict) -> dict:
    """`_sources` du brief : pour chacun des 6 champs critiques, {"piece", "page",
    "extrait" (≤ 200 caractères), "verifie"} ou None s'il n'y a pas de source.

    Origine, dans l'ordre : (1) recherche ciblée du contrôle de complétude ; (2) pièce et
    page citées par la fusion (`_sources_modele`), avec l'extrait relevé dans l'analyse de
    cette pièce ; (3) première analyse de pièce qui renseigne le champ. `verifie` : l'extrait
    figure dans le texte de la page citée (verifier_extrait, sans LLM)."""
    brief = brief or {}
    controle = brief.get("_controle_completude") or {}
    sources_modele = brief.get("_sources_modele") or {}
    resultat = {}
    for champ in CHAMPS_SOURCES:
        questions = _QUESTIONS_DU_CHAMP[champ]
        source = None
        relance = controle.get(champ) or {}
        if relance.get("statut") == "absent_confirme":
            resultat[champ] = None     # le champ n'est pas dans le brief : rien à sourcer
            continue
        if relance.get("statut") == "trouve_par_relance":
            source = _source(inv, relance.get("piece"), relance.get("pages"), relance.get("extrait"))
        if source is None:
            citees = sources_modele.get(_CHEMIN_MODELE[champ]) or []
            if isinstance(citees, dict):
                citees = [citees]
            candidates = []
            for citee in citees if isinstance(citees, list) else []:
                if not isinstance(citee, dict):
                    continue
                piece = _piece_par_nom(inv, citee.get("document"))
                page = _numero_page(citee.get("page"))
                s = _source_depuis_analyses(inv, analyses, piece["nom"], questions, page) if piece else None
                # pièce citée sans extrait relevé : la source reste citée, non vérifiée
                candidates.append(s or _source(inv, citee.get("document"), [page], None))
            candidates = [c for c in candidates if c]
            source = next((c for c in candidates if c["verifie"]), candidates[0] if candidates else None)
        if source is None:
            for a in analyses or []:
                source = _source_depuis_analyses(inv, analyses, a.get("piece"), questions)
                if source:
                    break
        resultat[champ] = source
    return resultat


def tableau_lecture(inv: dict, analyses: list) -> dict:
    """`_lecture` du brief : une ligne par pièce retenue et par fichier écarté (les doublons
    n'ont pas de ligne), et `pct_non_lu`, calculé sans LLM.

    Statut d'une pièce retenue : "lu" si toutes ses parties ont été analysées avec succès,
    sinon "echec_lecture". Fichier écarté : plan_ignore, format_non_gere ou echec_conversion.
    pct_non_lu = 100 × pièces de texte non lues / pièces de texte, une pièce de texte étant
    toute ligne qui n'est pas plan_ignore."""
    par_piece = {a.get("piece"): a for a in analyses or []}
    lignes = []
    for p in (inv or {}).get("pieces") or []:
        a = par_piece.get(p["nom"])
        resultats = (a or {}).get("resultats") or []
        lu = bool(resultats) and all(r.get("ok") for r in resultats)
        detail = None
        if not lu:
            detail = next((str(r.get("erreur"))[:200] for r in resultats if not r.get("ok") and r.get("erreur")),
                          "pièce non analysée")
        sans_texte = 0 if p.get("lecture_visuelle") else len(p.get("pages_sans_texte") or [])
        if lu and sans_texte:
            detail = f"{sans_texte} page(s) sans texte (images) non lue(s) dans ce PDF"
        lignes.append({"nom": p["nom"], "type": p.get("type"), "statut": "lu" if lu else "echec_lecture",
                       "pages": p.get("nb_pages"), "caracteres": p.get("chars"), "detail": detail,
                       "pages_sans_texte": sans_texte})
    for e in (inv or {}).get("ecartes") or []:
        lignes.append({"nom": e.get("nom"), "type": None, "statut": e.get("statut"),
                       "pages": None, "caracteres": None, "detail": e.get("detail"), "pages_sans_texte": 0})
    texte = [l for l in lignes if l["statut"] != "plan_ignore"]
    lues = [l for l in texte if l["statut"] == "lu"]
    pct = round(100.0 * (len(texte) - len(lues)) / len(texte), 1) if texte else 0.0
    return {"pieces": lignes, "nb_pieces_texte": len(texte), "nb_lues": len(lues), "pct_non_lu": pct}
