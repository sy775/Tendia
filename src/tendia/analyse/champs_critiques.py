"""
tendia/analyse/champs_critiques.py
----------------------------------
Les 6 champs critiques d'un brief du mode document (critères et pondérations, date et
heure limites, pièces exigées, visite, montant publié, lots) sont CHOISIS PAR LE CODE dans
les notes par pièce (data/pieces/<id>/_trace.json, analyses_pieces), sans LLM (chantier
2b, décision A). La fusion LLM reste pour les autres champs ; mode_document.fiabiliser_fusion
reste en garde-fou.

Pour chaque champ :
- candidats : réponses non nulles des notes par pièce (et de la recherche ciblée du
  contrôle de complétude, qui est aussi une lecture de pièce) ;
- choix : priorité RC > AE > CCAP > autres ; à priorité égale, la note la plus explicite
  (heure présente, montant chiffré, pondérations chiffrées, liste plus longue) ;
- désaccords entre notes : brief["_conflits"][champ] ;
- source : celle de la note retenue (sources_lecture._source : page corrigée si l'extrait
  est sur une autre page de la même pièce) ;
- valeur contrôlée : date, heure, pondérations et montant publié doivent figurer
  (normalisés) dans l'extrait ou dans le texte des pages citées ; sinon
  `valeur_verifiee` = False (« à vérifier » sur la fiche).

Montants : le montant PUBLIÉ (brief["montant_publie"], montant_marche, voie 1) vient
uniquement des notes RC / AE ; « non communiqué » s'il est absent de toutes. Les
estimations (voie 2 bottom-up, voie 3 comparables DECP) ne le remplissent jamais.
"""

import json
import re
import unicodedata
from typing import Optional

from tendia.analyse import pieces as P
from tendia.analyse import sources_lecture as S

CHAMPS = S.CHAMPS_SOURCES
QUESTIONS = {
    "criteres_ponderations": ("criteres_attribution",),
    "date_limite": ("date_limite_remise",),
    "pieces_candidature": ("pieces_candidature",),
    "pieces_offre": ("pieces_offre",),
    "visite": ("visite",),
    "montant": ("montant_estime", "montant"),
    "lots": ("lots", "lot"),
}
PRIORITE_TYPE = {"RC": 0, "AE": 1, "CCAP": 2}
TYPES_MONTANT = ("RC", "AE")          # montant publié : RC, AE (l'avis n'est pas une pièce du DCE)


# ---------------------------------------------------------------------------
# Normalisation et analyse des valeurs
# ---------------------------------------------------------------------------

def _sans_accents(s) -> str:
    s = unicodedata.normalize("NFKD", S.normaliser_extrait(s))
    return "".join(c for c in s if not unicodedata.combining(c))


def _texte(valeur) -> str:
    if valeur is None:
        return ""
    return valeur if isinstance(valeur, str) else json.dumps(valeur, ensure_ascii=False)


_RE_NOMBRE = re.compile(r"\d{1,3}(?:[   .]\d{3})+(?:,\d+)?|\d{4,}(?:[.,]\d+)?")


def nombres(texte) -> set:
    """Nombres (≥ 1 000) écrits dans un texte : « 305 000 € », « 1.016.667 », « 600000 »."""
    trouves = set()
    for brut in _RE_NOMBRE.findall(str(texte or "")):
        chiffres = re.sub(r"[   .]", "", brut.split(",")[0])
        if chiffres.isdigit() and int(chiffres) >= 1000:
            trouves.add(int(chiffres))
    return trouves


_RE_MONTANT = re.compile(
    r"(\d{1,3}(?:[   .]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)\s*"
    r"(k|m|millions?\s+d['’]|mille)?\s*(€|euros?\b|eur\b)\s*(h\.?t\.?\b|t\.?t\.?c\.?\b)?", re.I)


def montants_euros(texte) -> list:
    """[(valeur, taxe, position)] des montants en euros (≥ 1 000 €) d'un texte : un nombre
    suivi de €, euros ou EUR (k€, M€ et « millions d'euros » multipliés). Une année ou un
    numéro de page ne sont pas des montants."""
    sortie = []
    for m in _RE_MONTANT.finditer(str(texte or "")):
        brut, mult, _devise, taxe = m.groups()
        entier = re.sub(r"[   .]", "", brut) if re.search(r"[   .]\d{3}", brut) else brut
        try:
            v = float(entier.replace(",", "."))
        except ValueError:
            continue
        mult = (mult or "").lower()
        if mult == "k" or mult == "mille":
            v *= 1_000
        elif mult.startswith("m"):
            v *= 1_000_000
        if v >= 1000:
            taxe = (taxe or "").upper().replace(".", "") or None
            sortie.append((round(v, 2), taxe, m.start()))
    return sortie


_MOIS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
         "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12}
_RE_DATE_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_RE_DATE_NUM = re.compile(r"(?<!\d)(\d{1,2})\s*[/.]\s*(\d{1,2})\s*[/.]\s*(\d{4}|\d{2})(?!\d)")
_RE_DATE_LETTRES = re.compile(r"(?<!\d)(\d{1,2})(?:er)?\s+(" + "|".join(_MOIS) + r")\s+(\d{4})(?!\d)")
_RE_HEURE = re.compile(r"(?<![\d,.])(\d{1,2})\s*(?:h|:|heures?)\s*(\d{2})?(?!\d)")


def dates_dans(texte) -> set:
    """Dates (AAAA, MM, JJ) écrites dans un texte : ISO, JJ/MM/AAAA, JJ/MM/AA, « 14 décembre 2026 »."""
    t = _sans_accents(texte)
    trouvees = set()
    for a, m, j in _RE_DATE_ISO.findall(t):
        trouvees.add((int(a), int(m), int(j)))
    for j, m, a in _RE_DATE_NUM.findall(t):
        a = int(a) + (2000 if len(a) == 2 else 0)
        trouvees.add((a, int(m), int(j)))
    for j, mois, a in _RE_DATE_LETTRES.findall(t):
        trouvees.add((int(a), _MOIS[mois], int(j)))
    return {d for d in trouvees if 1 <= d[1] <= 12 and 1 <= d[2] <= 31}


def heures_dans(texte) -> set:
    """Heures (h, mn) écrites dans un texte : 12h00, 12 h, 12:00, 16 heures 30."""
    t = _RE_DATE_ISO.sub(" ", _sans_accents(texte))
    t = _RE_DATE_NUM.sub(" ", t)
    return {(int(h), int(mn or 0)) for h, mn in _RE_HEURE.findall(t) if int(h) <= 23 and int(mn or 0) <= 59}


def date_heure(valeur) -> tuple:
    """(date (a, m, j) | None, heure (h, mn) | None) d'une note de date limite."""
    t = _texte(valeur)
    m = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{1,2})[:h](\d{2}))?", t)
    if m:
        d = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return d, ((int(m.group(4)), int(m.group(5))) if m.group(4) else None)
    dates = sorted(dates_dans(t))
    heures = sorted(heures_dans(t))
    return (dates[0] if dates else None), (heures[0] if heures else None)


_RE_POND = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:%|pourcents?\b|points?\b|pts?\b)", re.I)
_RE_SOUS = re.compile(r"^\s*(?:[-•*–·]|\d+\s*\.\s*\d+|\d+\.\d+|sous[- ]?crit|[a-z]\s*\))", re.I)
_CLES_LIBELLE = ("nom", "libelle", "critere", "intitule", "name", "label")
_CLES_SOUS = ("sous_criteres", "sous-criteres", "sous_criteres_techniques", "souscriteres")


def _nombre(v) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.search(r"\d+(?:[.,]\d+)?", v)
        return float(m.group(0).replace(",", ".")) if m else None
    return None


def _ponderation_dict(d: dict) -> Optional[float]:
    for k, v in d.items():
        if any(x in str(k).lower() for x in ("ponder", "points", "poids", "pct", "pourcent", "note_max")):
            n = _nombre(v)
            if n is not None:
                return n
    return None


def _critere_de_dict(d: dict) -> Optional[dict]:
    libelle = next((str(d[k]) for k in _CLES_LIBELLE if d.get(k)), None)
    pond = _ponderation_dict(d)
    if libelle is None and pond is None:
        return None
    sous = []
    for k in _CLES_SOUS:
        if isinstance(d.get(k), list):
            sous = [c for c in (_critere_de_dict(x) if isinstance(x, dict) else _critere_de_ligne(str(x))
                                for x in d[k]) if c]
            break
    return {"libelle": (libelle or "").strip(), "ponderation": pond, "sous_criteres": sous}


def _critere_de_ligne(ligne: str) -> Optional[dict]:
    m = _RE_POND.search(ligne)
    if not m:
        return None
    libelle = re.sub(r"^\s*(?:[-•*–·]\s*|\d+\s*[).:-]\s*)", "", ligne[:m.start()]).strip(" :(-–[")
    return {"libelle": libelle or ligne.strip()[:120], "ponderation": float(m.group(1).replace(",", ".")),
            "sous_criteres": []}


def criteres_de(valeur) -> list:
    """Critères de premier niveau [{libelle, ponderation, sous_criteres}] d'une note
    (dict, liste ou texte libre « 1) CRITERE PRIX : 60 points\\n- Sous-critère … (30 points) »)."""
    if isinstance(valeur, dict):
        for k in ("criteres", "critères", "liste", "criteres_attribution"):
            if isinstance(valeur.get(k), (list, str)):
                return criteres_de(valeur[k])
        # forme {"valeur_prix_pct": 60, "valeur_technique_pct": 40, "autres_criteres": [...]}
        sortie = []
        for k, v in valeur.items():
            n = _nombre(v) if isinstance(v, (int, float, str)) else None
            if n is not None and any(x in str(k).lower() for x in ("prix", "technique", "pct")):
                sortie.append({"libelle": str(k), "ponderation": n, "sous_criteres": []})
            elif isinstance(v, list) and "autres" in str(k).lower():
                sortie += [c for c in (_critere_de_dict(x) for x in v if isinstance(x, dict)) if c]
        return sortie
    if isinstance(valeur, list):
        sortie = []
        for x in valeur:
            if isinstance(x, dict):
                c = _critere_de_dict(x)
                if c:
                    sortie.append(c)
            elif isinstance(x, str):
                sortie += criteres_de(x)
        return sortie
    if not isinstance(valeur, str):
        return []
    lignes = [l for l in valeur.splitlines() if l.strip()]
    if len(lignes) == 1:
        lignes = [l for l in re.split(r"\s*;\s*|\s+/\s+", lignes[0]) if l.strip()]
    sortie = []
    for ligne in lignes:
        if re.match(r"^\s*(?:formule|note\b|grille)", ligne, re.I):
            continue
        c = _critere_de_ligne(ligne)
        if not c:
            continue
        if _RE_SOUS.match(ligne) and sortie:
            sortie[-1]["sous_criteres"].append(c)
        elif not _RE_SOUS.match(ligne):
            sortie.append(c)
    return sortie


def bareme_depuis_criteres(criteres: list) -> dict:
    """valeur_prix_pct, valeur_technique_pct, autres_criteres (pondérations ramenées en %
    quand le total des points n'est pas 100). Calcul déterministe."""
    ponderes = [c for c in criteres if c.get("ponderation") is not None]
    total = sum(c["ponderation"] for c in ponderes)
    if not ponderes or total <= 0:
        return {}
    pct = (lambda x: round(100.0 * x / total, 2)) if abs(total - 100) > 0.5 else (lambda x: round(x, 2))
    prix = [c for c in ponderes if "prix" in _sans_accents(c["libelle"])]
    tech = [c for c in ponderes if c not in prix and "technique" in _sans_accents(c["libelle"])]
    autres = [c for c in ponderes if c not in prix and c not in tech]
    entier = lambda x: int(x) if float(x).is_integer() else x
    return {"valeur_prix_pct": entier(pct(sum(c["ponderation"] for c in prix))) if prix else None,
            "valeur_technique_pct": entier(pct(sum(c["ponderation"] for c in tech))) if tech else None,
            "autres_criteres": [{"libelle": c["libelle"], "ponderation_pct": entier(pct(c["ponderation"]))}
                                for c in autres]}


_RE_VISITE_NON = re.compile(r"\b(?:non|pas)\s+obligatoire|facultati|(?:non|pas)\s+prevue|pas\s+de\s+visite|"
                            r"aucune\s+visite|n'est\s+pas\s+(?:obligatoire|prevue|exigee)|sans\s+objet|"
                            r"non\s+exigee|pas\s+exigee")


def visite_obligatoire(valeur) -> Optional[bool]:
    if isinstance(valeur, dict) and isinstance(valeur.get("obligatoire"), bool):
        return valeur["obligatoire"]
    t = _sans_accents(_texte(valeur))
    if _RE_VISITE_NON.search(t):
        return False
    if "obligatoire" in t or "exigee" in t:
        return True
    return None


def liste_pieces(valeur) -> list:
    """Libellés des pièces exigées d'une note (liste, ou texte une pièce par ligne)."""
    if isinstance(valeur, list):
        items = []
        for x in valeur:
            if isinstance(x, dict):
                x = next((x[k] for k in ("libelle", "piece", "nom", "intitule") if x.get(k)), None)
            if x:
                items.append(str(x))
    elif isinstance(valeur, str):
        items = valeur.splitlines()
    else:
        return []
    items = [re.sub(r"^\s*(?:[-•*–·]\s*|\d+\s*[).]\s*)", "", i).strip() for i in items]
    # une ligne d'intitulé (« Hors dispositif DUME : ») n'est pas une pièce
    return [i for i in items if sum(c.isalnum() for c in i) >= 3 and not i.endswith(":")]


_RE_LOT = re.compile(r"\blot\s*(?:n\s*[°o]?\s*)?(\d+)\s*[:\-–.)]\s*([^;\n]+)", re.I)


def lots_de(valeur) -> tuple:
    """(alloti True/False/None, [{numero, intitule}]) d'une note d'allotissement."""
    lots = []
    if isinstance(valeur, list):
        for x in valeur:
            if isinstance(x, dict):
                n = _nombre(x.get("numero") if x.get("numero") is not None else x.get("lot"))
                lots.append({"numero": int(n) if n is not None else None,
                             "intitule": next((str(x[k]) for k in ("intitule", "libelle", "objet", "nom") if x.get(k)), "")})
            elif isinstance(x, str):
                lots += [{"numero": int(n), "intitule": i.strip()} for n, i in _RE_LOT.findall(x)]
    elif isinstance(valeur, dict):
        if isinstance(valeur.get("lots"), list):
            alloti, lots = lots_de(valeur["lots"])
            return (valeur.get("alloti") if isinstance(valeur.get("alloti"), bool) else (len(lots) > 1 or None)), lots
        if isinstance(valeur.get("alloti"), bool):
            return valeur["alloti"], []
    t = _sans_accents(_texte(valeur))
    if isinstance(valeur, str):
        lots = [{"numero": int(n), "intitule": i.strip()} for n, i in _RE_LOT.findall(valeur)]
    if re.search(r"non\s+alloti|pas\s+(?:alloti|de\s+(?:decomposition|allotissement))|ne\s+pas\s+allotir|"
                 r"lot\s+unique|marche\s+unique|ni\s+en\s+lots?|pas\s+d'allotissement|sans\s+allotissement", t) \
            and len(lots) <= 1:
        return False, lots
    if len(lots) > 1 or re.search(r"\balloti\b|\ballotissement\b.*\blots?\b", t):
        return (True if len(lots) > 1 or "alloti" in t else None), lots
    return None, lots


# ---------------------------------------------------------------------------
# Candidats, choix, contrôle
# ---------------------------------------------------------------------------

def _type_piece(inv: dict, nom) -> Optional[str]:
    p = S._piece_par_nom(inv, nom)
    return p.get("type") if p else None


def candidats(analyses: list, questions: tuple, relance: dict = None, inv: dict = None) -> list:
    """Réponses non nulles des notes par pièce (ordre des pièces, puis des parties) et de
    la recherche ciblée : [{piece, type, question, valeur, pages, extrait, ordre}]."""
    sortie = []
    for a in analyses or []:
        for r in a.get("resultats") or []:
            j = r.get("json")
            infos = (j.get("informations") or {}) if isinstance(j, dict) else {}
            for q in questions:
                info = infos.get(q)
                if isinstance(info, dict) and info.get("valeur") not in (None, "", [], {}):
                    sortie.append({"piece": a.get("piece"), "type": a.get("type"), "question": q,
                                   "valeur": info.get("valeur"), "pages": info.get("pages"),
                                   "extrait": info.get("extrait"), "ordre": len(sortie)})
    if relance and relance.get("statut") == "trouve_par_relance" and relance.get("valeur") not in (None, "", [], {}):
        sortie.append({"piece": relance.get("piece"), "type": _type_piece(inv, relance.get("piece")) or "annexe",
                       "question": "recherche_ciblee", "valeur": relance.get("valeur"),
                       "pages": relance.get("pages"), "extrait": relance.get("extrait"), "ordre": len(sortie)})
    return sortie


def explicite(champ: str, valeur) -> float:
    """Score d'explicitation d'une note (plus haut = plus explicite)."""
    if champ == "date_limite":
        d, h = date_heure(valeur)
        return (1 if d else 0) + (1 if h else 0)
    if champ == "montant":
        return 1 if montants_euros(_texte(valeur)) else 0
    if champ == "criteres_ponderations":
        cr = criteres_de(valeur)
        n = sum(1 for c in cr if c.get("ponderation") is not None)
        total = sum(c["ponderation"] for c in cr if c.get("ponderation") is not None)
        return n + (5 if n and abs(total - 100) <= 0.5 else 0)
    if champ == "visite":
        return 1 if visite_obligatoire(valeur) is not None else 0
    if champ == "lots":
        alloti, lots = lots_de(valeur)
        return (1 if alloti is not None else 0) + len(lots)
    if champ in ("pieces_candidature", "pieces_offre"):
        return len(liste_pieces(valeur))
    return 0


def choisir(champ: str, cands: list) -> Optional[dict]:
    """Note retenue : priorité RC > AE > CCAP > autres, puis la plus explicite, puis l'ordre."""
    utiles = [c for c in cands if explicite(champ, c["valeur"]) > 0] or cands
    if not utiles:
        return None
    return min(utiles, key=lambda c: (PRIORITE_TYPE.get(c.get("type"), 3), -explicite(champ, c["valeur"]), c["ordre"]))


def cle_comparaison(champ: str, valeur):
    """Forme comparable d'une valeur, pour détecter les désaccords entre notes (None : non comparable)."""
    if champ == "date_limite":
        d, h = date_heure(valeur)
        return (d, h) if d else None
    if champ == "montant":
        m = montants_euros(_texte(valeur))
        return frozenset(round(v) for v, _t, _p in m) or None
    if champ == "criteres_ponderations":
        p = tuple(sorted(c["ponderation"] for c in criteres_de(valeur) if c.get("ponderation") is not None))
        return p or None
    if champ == "visite":
        return visite_obligatoire(valeur)
    if champ == "lots":
        alloti, lots = lots_de(valeur)
        return (alloti, len(lots)) if alloti is not None else None
    return None


def _en_desaccord(champ: str, a, b) -> bool:
    if a is None or b is None:
        return False
    if champ == "montant":
        return not (a & b)                 # aucun montant commun
    if champ == "date_limite":
        (da, ha), (db, hb) = a, b
        return da != db or (ha is not None and hb is not None and ha != hb)
    return a != b


def conflits(champ: str, retenu: dict, cands: list) -> list:
    ref = cle_comparaison(champ, retenu["valeur"])
    sortie = []
    for c in cands:
        if c is retenu:
            continue
        if _en_desaccord(champ, ref, cle_comparaison(champ, c["valeur"])):
            sortie.append({"piece": c["piece"], "type": c.get("type"), "pages": c.get("pages"),
                           "valeur": _texte(c["valeur"])[:300]})
    return sortie


def _textes_controle(inv: dict, retenu: dict, source: Optional[dict]) -> str:
    """Extrait de la note + texte des pages citées (et de la page corrigée de la source)."""
    piece = S._piece_par_nom(inv, retenu.get("piece"))
    pages = S._pages_piece(piece, retenu.get("pages"))
    if source and source.get("page") is not None and source["page"] not in pages:
        pages.append(source["page"])
    morceaux = [_texte(retenu.get("extrait"))]
    if piece:
        morceaux += [P.texte_page(piece, p) for p in pages]
    return "\n".join(m for m in morceaux if m)


def _figure_nombre(n: float, texte_norm: str) -> bool:
    entier = int(n) if float(n).is_integer() else None
    formes = {str(entier)} if entier is not None else {str(n), str(n).replace(".", ",")}
    return any(re.search(r"(?<![\d,.])" + re.escape(f) + r"(?![\d]|[.,]\d)", texte_norm) for f in formes)


def controler_valeur(champ: str, valeur, texte: str) -> Optional[bool]:
    """True / False si la valeur (date, heure, pondérations, montant) figure dans le texte ;
    None pour un champ sans valeur chiffrée à contrôler."""
    if champ == "date_limite":
        d, h = date_heure(valeur)
        if not d:
            return False
        return d in dates_dans(texte) and (h is None or h in heures_dans(texte))
    if champ == "criteres_ponderations":
        ponds = [c["ponderation"] for c in criteres_de(valeur) if c.get("ponderation") is not None]
        norm = S.normaliser_extrait(texte)
        return bool(ponds) and all(_figure_nombre(p, norm) for p in ponds)
    if champ == "montant":
        m = montants_euros(_texte(valeur))
        if not m:
            return None
        dans_texte = nombres(texte) | {round(v) for v, _t, _p in montants_euros(texte)}
        return abs(m[0][0] - min(dans_texte, key=lambda x: abs(x - m[0][0]), default=-10)) <= 1
    return None


# ---------------------------------------------------------------------------
# Application au brief
# ---------------------------------------------------------------------------

def _source_note(inv: dict, retenu: dict) -> Optional[dict]:
    return S._source(inv, retenu.get("piece"), retenu.get("pages"), retenu.get("extrait"))


def _ref(source: Optional[dict], retenu: dict) -> str:
    page = (source or {}).get("page")
    return f"{retenu.get('piece')}" + (f" p. {page}" if page is not None else "")


def _appliquer_criteres(brief: dict, retenu: dict) -> None:
    criteres = criteres_de(retenu["valeur"])
    bareme = bareme_depuis_criteres(criteres)
    bn = brief.setdefault("bareme_notation", {})
    if not isinstance(bn, dict):
        bn = brief["bareme_notation"] = {}
    for k in ("valeur_prix_pct", "valeur_technique_pct"):
        if k in bareme:
            bn[k] = bareme[k]
    if bareme:
        bn["autres_criteres"] = bareme["autres_criteres"]
    bn["criteres_rc"] = criteres


def _appliquer_date(brief: dict, retenu: dict) -> None:
    d, h = date_heure(retenu["valeur"])
    if d:
        valeur = f"{d[0]:04d}-{d[1]:02d}-{d[2]:02d}" + (f" {h[0]:02d}:{h[1]:02d}" if h else "")
        cal = brief.setdefault("calendrier", {})
        if isinstance(cal, dict):
            cal["date_limite_offres"] = valeur


def _appliquer_pieces(brief: dict, choisis: dict, sources: dict) -> None:
    liste = []
    for phase, cle in (("candidature", "pieces_candidature"), ("offre", "pieces_offre")):
        retenu = choisis.get(cle)
        if not retenu:
            continue
        for libelle in liste_pieces(retenu["valeur"]):
            conditionnelle = re.search(r"le cas echeant|eventuel|si le candidat|s'il y a lieu|\bsi\b",
                                       _sans_accents(libelle))
            liste.append({"libelle": libelle, "phase": phase, "obligatoire": not conditionnelle,
                          "source": _ref(sources.get(cle), retenu)})
    if liste:
        dc = brief.setdefault("dossier_candidature", {})
        if isinstance(dc, dict):
            dc["pieces_a_fournir"] = liste


def _appliquer_visite(brief: dict, retenu: dict) -> None:
    oblig = visite_obligatoire(retenu["valeur"])
    cd = brief.setdefault("complements_dce", {})
    if not isinstance(cd, dict):
        return
    v = cd.get("visite") if isinstance(cd.get("visite"), dict) else {}
    v["obligatoire"] = oblig
    texte = retenu["valeur"] if isinstance(retenu["valeur"], str) else (
        (retenu["valeur"] or {}).get("modalites") if isinstance(retenu["valeur"], dict) else None)
    if texte:
        v["modalites"] = str(texte)[:600]
    cd["visite"] = v


def _appliquer_lots(brief: dict, retenu: dict) -> None:
    alloti, lots = lots_de(retenu["valeur"])
    cd = brief.setdefault("complements_dce", {})
    if alloti is False:
        if isinstance(cd, dict):
            cd["allotissement"] = "non alloti"
        if len(brief.get("lots") or []) > 1:
            brief["lots"] = (brief.get("lots") or [])[:1]
    elif alloti and lots:
        if isinstance(cd, dict):
            cd["allotissement"] = "alloti"
        anciens = {l.get("numero"): l for l in brief.get("lots") or [] if isinstance(l, dict)}
        brief["lots"] = [dict(anciens.get(l["numero"]) or {}, numero=l["numero"],
                              intitule=l["intitule"] or (anciens.get(l["numero"]) or {}).get("intitule"))
                         for l in lots]


def _appliquer_montant(brief: dict, retenu: Optional[dict], source: Optional[dict]) -> dict:
    """Montant PUBLIÉ seulement. Rend brief["montant_publie"]."""
    mm = brief.get("montant_marche") if isinstance(brief.get("montant_marche"), dict) else {}
    brief["montant_marche"] = mm
    v3 = brief.get("montant_3_voies") if isinstance(brief.get("montant_3_voies"), dict) else None
    trouves = montants_euros(_texte(retenu["valeur"])) if retenu else []
    if trouves:
        valeur, taxe, pos = trouves[0]
        texte = _texte(retenu["valeur"])
        avant = _sans_accents(texte[max(0, pos - 60):pos])
        plafond = bool(re.search(r"maxim|plafond", avant)) and not re.search(r"estim", avant)
        publie = {"statut": "publie", "valeur_eur": valeur, "taxe": taxe, "texte": texte[:400],
                  "piece": retenu.get("piece"), "page": (source or {}).get("page"),
                  "montants_cites": sorted({v for v, _t, _p in trouves})}
        mm.update(valeur_estimee_euros=valeur, fourchette_min_euros=None, fourchette_max_euros=None,
                  type="plafond" if plafond else "estime_explicite", source_extraction=_ref(source, retenu),
                  commentaire="Montant publié : " + texte[:300])
        if v3 is not None:
            v3["voie_1_eur"] = valeur
            v3["voie_1_source"] = _ref(source, retenu)
    else:
        publie = {"statut": "non_communique", "valeur_eur": None, "taxe": None,
                  "texte": _texte(retenu["valeur"])[:400] if retenu else None,
                  "piece": retenu.get("piece") if retenu else None, "page": (source or {}).get("page")}
        mm.update(valeur_estimee_euros=None, fourchette_min_euros=None, fourchette_max_euros=None,
                  type="non_communique", source_extraction=_ref(source, retenu) if retenu else None,
                  commentaire="Aucun montant publié dans les notes du RC et de l'acte d'engagement.")
        if v3 is not None:
            v3["voie_1_eur"] = None
            v3["voie_1_source"] = None
    brief["montant_publie"] = publie
    return publie


def _valeur_fusion(brief: dict, champ: str):
    chemin = S._CHEMIN_MODELE[champ]
    v = brief
    for k in chemin.split("."):
        v = v.get(k) if isinstance(v, dict) else None
    return json.loads(json.dumps(v, ensure_ascii=False, default=str)) if v is not None else None


def appliquer(brief: dict, analyses: list, inv: dict) -> dict:
    """Choisit les 6 champs critiques dans les notes par pièce et les écrit dans le brief,
    sans LLM. Met à jour brief["_sources"][champ] (source de la note retenue, plus
    "valeur_verifiee"), brief["_conflits"], brief["_champs_critiques"] (origine, pièce,
    valeur de la fusion remplacée) et brief["montant_publie"]. Rend _champs_critiques.

    Champ sans aucune note : la valeur de la fusion est gardée, marquée origine "fusion" et
    valeur_verifiee False ; sauf le montant publié, qui passe à « non communiqué »."""
    controle = brief.get("_controle_completude") or {}
    sources = brief.setdefault("_sources", {})
    if not isinstance(sources, dict):
        sources = brief["_sources"] = {}
    conflits_brief, suivi = {}, {}
    choisis, sources_choisies = {}, {}
    for champ, questions in QUESTIONS.items():
        champ_controle = "pieces_exigees" if champ.startswith("pieces_") else champ
        relance = controle.get(champ_controle) if champ in ("criteres_ponderations", "date_limite", "visite",
                                                            "montant", "lots") else None
        cands = candidats(analyses, questions, relance, inv)
        if champ == "montant":
            cands = [c for c in cands if c.get("type") in TYPES_MONTANT
                     or (c["question"] == "recherche_ciblee" and c.get("type") in TYPES_MONTANT)]
        retenu = choisir(champ, cands)
        if not retenu:
            continue
        choisis[champ] = retenu
        sources_choisies[champ] = _source_note(inv, retenu)
        desaccords = conflits(champ, retenu, cands)
        if desaccords:
            conflits_brief[champ_controle] = conflits_brief.get(champ_controle, []) + desaccords

    for champ in CHAMPS:
        fusion_avant = _valeur_fusion(brief, champ)
        if champ == "pieces_exigees":
            retenus = [choisis[c] for c in ("pieces_candidature", "pieces_offre") if c in choisis]
            if retenus:
                _appliquer_pieces(brief, choisis, sources_choisies)
                src = sources_choisies.get("pieces_candidature") or sources_choisies.get("pieces_offre")
                cle = "pieces_candidature" if "pieces_candidature" in choisis else "pieces_offre"
                verif = bool(src and src.get("verifie"))
                suivi[champ] = {"origine": "notes", "piece": choisis[cle]["piece"], "type": choisis[cle]["type"],
                                "valeur_verifiee": verif, "valeur_fusion": fusion_avant}
                if src:
                    sources[champ] = dict(src, valeur_verifiee=verif)
            else:
                suivi[champ] = {"origine": "fusion", "valeur_verifiee": False, "valeur_fusion": fusion_avant}
                if isinstance(sources.get(champ), dict):
                    sources[champ]["valeur_verifiee"] = False
            continue
        retenu = choisis.get(champ)
        src = sources_choisies.get(champ)
        if champ == "montant":
            publie = _appliquer_montant(brief, retenu, src)
            verif = controler_valeur("montant", retenu["valeur"], _textes_controle(inv, retenu, src)) \
                if retenu and publie["statut"] == "publie" else None
            suivi[champ] = {"origine": "notes" if retenu else "absent", "statut": publie["statut"],
                            "piece": (retenu or {}).get("piece"), "type": (retenu or {}).get("type"),
                            "valeur_verifiee": verif, "valeur_fusion": fusion_avant}
            if retenu and src:
                sources[champ] = dict(src, valeur_verifiee=verif if verif is not None else bool(src.get("verifie")))
            elif not retenu:
                sources[champ] = None
            continue
        if not retenu:
            suivi[champ] = {"origine": "fusion" if fusion_avant not in (None, {}, []) else "absent",
                            "valeur_verifiee": False, "valeur_fusion": fusion_avant}
            if isinstance(sources.get(champ), dict):
                sources[champ]["valeur_verifiee"] = False
            continue
        {"criteres_ponderations": _appliquer_criteres, "date_limite": _appliquer_date,
         "visite": _appliquer_visite, "lots": _appliquer_lots}[champ](brief, retenu)
        verif = controler_valeur(champ, retenu["valeur"], _textes_controle(inv, retenu, src))
        if verif is None:
            verif = bool(src and src.get("verifie"))
        suivi[champ] = {"origine": "relance" if retenu["question"] == "recherche_ciblee" else "notes",
                        "piece": retenu["piece"], "type": retenu.get("type"), "valeur_verifiee": verif,
                        "valeur_fusion": fusion_avant}
        if src:
            sources[champ] = dict(src, valeur_verifiee=verif)
    brief["_conflits"] = conflits_brief
    brief["_champs_critiques"] = suivi
    return suivi
