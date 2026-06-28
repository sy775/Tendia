# -*- coding: utf-8 -*-
"""
ASSEMBLAGE .DOCX (Sprint B).

Deux modes :
  1. Template Tendia stylé (par défaut) — page de garde, sommaire auto,
     en-tête/pied de page, hiérarchie H1/H2/H3, encadrés [À COMPLÉTER].
  2. Injection dans un cadre de réponse acheteur (.docx) si détecté — épouse
     SA structure, ne touche JAMAIS à ses styles/polices/en-têtes/pieds.

Sortie : data/memoires/<id_marche>/<id_user>_lot<n>_<timestamp>.docx

⚠️ Module additif. Dépend de python-docx (déjà installé).
"""
import os
import re

from docx import Document
from docx.shared import Pt, Cm, Mm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_SECTION
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

import pdf_extract

# Charte Tendia
NAVY = RGBColor(0x0F, 0x1B, 0x3D)
GOLD = RGBColor(0xC9, 0xA9, 0x61)
ANTHRACITE = RGBColor(0x2B, 0x2B, 0x2B)
NAVY_HEX = "0F1B3D"
GOLD_HEX = "C9A961"
COMPLETER_FILL = "FFF6CC"      # jaune clair pour les encadrés [À COMPLÉTER]
POLICE_TITRES = "Cambria"
POLICE_CORPS = "Calibri"

ENCADRE_FILL = "FBF3DD"         # crème clair pour les encadrés « engagement »
REPERTOIRE_MEMOIRES = os.path.join("data", "memoires")
RE_COMPLETER = re.compile(r"\[À COMPLÉTER\s*:.*?\]", re.IGNORECASE | re.DOTALL)
RE_GRAS = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
RE_TABLE_LIGNE = re.compile(r"^\s*\|.*\|\s*$")
RE_TABLE_SEP = re.compile(r"^[\s|:-]+$")


# ---------------------------------------------------------------------------
# Helpers oxml bas niveau
# ---------------------------------------------------------------------------

def _set_cell_or_par_shading(paragraph, fill_hex):
    pPr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill_hex)
    pPr.append(shd)


def _set_par_border(paragraph, color_hex, val="dotted", sz="12", space="6"):
    pPr = paragraph._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    for edge in ("top", "left", "bottom", "right"):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), val)
        e.set(qn("w:sz"), sz)
        e.set(qn("w:space"), space)
        e.set(qn("w:color"), color_hex)
        pbdr.append(e)
    pPr.append(pbdr)


def _add_field(paragraph, instr):
    """Insère un champ Word (PAGE, NUMPAGES…) dans un run du paragraphe."""
    run = paragraph.add_run()
    r = run._r
    f1 = OxmlElement("w:fldChar")
    f1.set(qn("w:fldCharType"), "begin")
    f1.set(qn("w:dirty"), "true")
    it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve"); it.text = f" {instr} "
    f2 = OxmlElement("w:fldChar"); f2.set(qn("w:fldCharType"), "separate")
    t = OxmlElement("w:t"); t.text = ""
    f3 = OxmlElement("w:fldChar"); f3.set(qn("w:fldCharType"), "end")
    for el in (f1, it, f2, t, f3):
        r.append(el)


def _add_toc(document, plan_sections=None):
    """Champ TOC standard (sommaire paginé). Word le remplit via la mise à jour
    des champs : à l'ouverture (updateFields=true, hors vue protégée) ou F9 →
    « Mettre à jour TOUTE LA TABLE ». On garde un repli MINIMAL d'une seule ligne
    — surtout PAS une fausse liste d'entrées, qui ferait afficher « 1 » partout
    lors d'une mise à jour « numéros de page uniquement »."""
    p = document.add_paragraph()
    run = p.add_run()
    r = run._r
    f1 = OxmlElement("w:fldChar")
    f1.set(qn("w:fldCharType"), "begin")
    f1.set(qn("w:dirty"), "true")
    # \o "1-2" : seules les sections (H1) et sous-sections (H2) du plan ; les
    # sous-titres rédactionnels « ## » (H3) sont exclus pour garder un sommaire
    # compact (sinon il déborde sur 2 pages).
    it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve")
    it.text = 'TOC \\o "1-2" \\h \\z \\u'
    f2 = OxmlElement("w:fldChar"); f2.set(qn("w:fldCharType"), "separate")
    t = OxmlElement("w:t"); t.set(qn("xml:space"), "preserve")
    t.text = "Sommaire — clic dans cette zone puis F9 → « Mettre à jour toute la table »."
    f3 = OxmlElement("w:fldChar"); f3.set(qn("w:fldCharType"), "end")
    for el in (f1, it, f2, t, f3):
        r.append(el)


def _force_update_fields(document):
    """Demande à Word de mettre à jour les champs (sommaire, pagination) à
    l'ouverture du document."""
    settings = document.settings.element
    el = settings.find(qn("w:updateFields"))
    if el is None:
        el = OxmlElement("w:updateFields")
        settings.append(el)
    el.set(qn("w:val"), "true")


# ---------------------------------------------------------------------------
# Styles & mise en page Tendia
# ---------------------------------------------------------------------------

def _styler_document(document):
    styles = document.styles
    normal = styles["Normal"]
    normal.font.name = POLICE_CORPS
    normal.font.size = Pt(11)
    normal.font.color.rgb = ANTHRACITE
    pf = normal.paragraph_format
    pf.space_after = Pt(6)
    pf.line_spacing = 1.15

    for lvl, sz in ((1, 16), (2, 13), (3, 11.5)):
        st = styles[f"Heading {lvl}"]
        st.font.name = POLICE_TITRES
        st.font.size = Pt(sz)
        st.font.bold = True
        st.font.color.rgb = NAVY
        st.paragraph_format.space_before = Pt(14 if lvl == 1 else 10)
        st.paragraph_format.space_after = Pt(6)


def _mise_en_page_a4(section):
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(2.5)
    section.top_margin = Cm(2.5)
    section.bottom_margin = Cm(2.5)


def _entete_pied(section, entete_txt, organisme):
    # En-tête : nom marché abrégé + numéro lot
    h = section.header
    h.is_linked_to_previous = False
    ph = h.paragraphs[0]
    ph.text = entete_txt
    ph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for run in ph.runs:
        run.font.name = POLICE_CORPS
        run.font.size = Pt(8)
        run.font.color.rgb = GOLD

    # Pied : pagination "Page X / Y" + mention
    f = section.footer
    f.is_linked_to_previous = False
    pf = f.paragraphs[0]
    pf.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pf.add_run("Page ")
    _add_field(pf, "PAGE")
    pf.add_run(" / ")
    _add_field(pf, "NUMPAGES")
    pf.add_run(f"   ·   Mémoire technique — {organisme}")
    for run in pf.runs:
        run.font.name = POLICE_CORPS
        run.font.size = Pt(8)
        run.font.color.rgb = ANTHRACITE


# ---------------------------------------------------------------------------
# Rendu du texte des sections (avec marqueurs [À COMPLÉTER])
# ---------------------------------------------------------------------------

def _ajouter_paragraphes_texte(document, texte):
    """Rend le texte d'une section avec un balisage léger : tableaux markdown
    (| a | b |), sous-titres « ## », encadrés engagement « > », puces « - »,
    gras « **…** » et marqueurs [À COMPLÉTER]."""
    blocs = re.split(r"\n\s*\n", (texte or "").strip())
    for bloc in blocs:
        bloc = bloc.strip()
        if not bloc:
            continue
        lignes = [l for l in bloc.split("\n") if l.strip()]

        # 1. Tableau markdown (≥ 2 lignes encadrées de « | »)
        if len(lignes) >= 2 and all(RE_TABLE_LIGNE.match(l) for l in lignes):
            _ajouter_tableau_markdown(document, lignes)
            continue
        # 2. Encadré « engagement » (bloc entièrement préfixé par « > »)
        if all(l.lstrip().startswith(">") for l in lignes):
            contenu = " ".join(l.lstrip().lstrip(">").strip() for l in lignes)
            _encadre_engagement(document, contenu)
            continue
        # 3. Liste à puces
        if all(l.lstrip().startswith(("- ", "• ", "* ")) for l in lignes):
            for l in lignes:
                p = document.add_paragraph(style="List Bullet")
                _rendre_runs(p, l.lstrip()[2:].strip())
            continue
        # 4. Sous-titre « ## » en tête de bloc (+ éventuel corps)
        if lignes[0].lstrip().startswith("## "):
            document.add_heading(lignes[0].lstrip()[3:].strip(), level=3)
            reste = [l for l in lignes[1:]]
            if reste:
                p = document.add_paragraph()
                _rendre_runs(p, " ".join(reste))
            continue
        # 5. Paragraphe normal
        p = document.add_paragraph()
        _rendre_runs(p, bloc.replace("\n", " "))


def _segments_inline(texte):
    """Découpe une chaîne en segments (contenu, type) où type ∈
    {normal, gras, completer}. Les marqueurs [À COMPLÉTER] priment sur le gras."""
    spans = []
    for m in RE_COMPLETER.finditer(texte):
        spans.append((m.start(), m.end(), "completer", m.group(0)))
    for m in RE_GRAS.finditer(texte):
        spans.append((m.start(), m.end(), "gras", m.group(1)))
    spans.sort()
    res, pos = [], 0
    for start, end, kind, contenu in spans:
        if start < pos:        # chevauche un segment déjà émis
            continue
        if start > pos:
            res.append((texte[pos:start], "normal"))
        res.append((contenu, kind))
        pos = end
    if pos < len(texte):
        res.append((texte[pos:], "normal"))
    return [(t, k) for t, k in res if t]


def _rendre_runs(paragraph, texte):
    """Ajoute le texte au paragraphe : gras « **…** », marqueurs [À COMPLÉTER]
    surlignés. Si le paragraphe est ENTIÈREMENT un marqueur, l'encadre."""
    if RE_COMPLETER.fullmatch(texte.strip()):
        _set_cell_or_par_shading(paragraph, COMPLETER_FILL)
        _set_par_border(paragraph, GOLD_HEX, val="dotted")
        run = paragraph.add_run(texte.strip())
        run.bold = True
        run.font.color.rgb = RGBColor(0x7A, 0x5A, 0x00)
        return
    for contenu, kind in _segments_inline(texte):
        run = paragraph.add_run(contenu)
        if kind == "completer":
            run.bold = True
            run.font.color.rgb = RGBColor(0x7A, 0x5A, 0x00)
            _surligner(run, "yellow")
        elif kind == "gras":
            run.bold = True


def _shade_cell(cell, fill_hex):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill_hex)
    tcPr.append(shd)


def _ajouter_tableau_markdown(document, lignes):
    """Convertit un tableau markdown en tableau Word stylé (en-tête navy, lignes
    alternées crème)."""
    rows = []
    for l in lignes:
        if RE_TABLE_SEP.match(l):        # ligne de séparation « |---|---| »
            continue
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        rows.append(cells)
    if not rows:
        return
    ncol = max(len(r) for r in rows)
    table = document.add_table(rows=0, cols=ncol)
    try:
        table.style = "Table Grid"
    except KeyError:
        pass
    table.autofit = True
    for i, r in enumerate(rows):
        cellules = table.add_row().cells
        for j in range(ncol):
            cell = cellules[j]
            cell.text = ""
            p = cell.paragraphs[0]
            _rendre_runs(p, r[j] if j < len(r) else "")
            for run in p.runs:
                run.font.name = POLICE_CORPS
                run.font.size = Pt(10 if i else 10.5)
                if i == 0:
                    run.font.bold = True
                    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            if i == 0:
                _shade_cell(cell, NAVY_HEX)
            elif i % 2 == 0:
                _shade_cell(cell, "FBF7EE")
    document.add_paragraph()


def _encadre_engagement(document, contenu):
    """Encadré « engagement » : fond crème, liseré doré, label en or."""
    p = document.add_paragraph()
    _set_cell_or_par_shading(p, ENCADRE_FILL)
    _set_par_border(p, GOLD_HEX, val="single", sz="8", space="6")
    label = p.add_run("Notre engagement   ")
    label.bold = True
    label.font.color.rgb = GOLD
    _rendre_runs(p, contenu)
    for run in p.runs[1:]:
        run.font.color.rgb = ANTHRACITE


def _border_bottom(paragraph, color_hex, sz="6"):
    pPr = paragraph._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), sz)
    bottom.set(qn("w:space"), "3")
    bottom.set(qn("w:color"), color_hex)
    pbdr.append(bottom)
    pPr.append(pbdr)


def _surligner(run, couleur):
    rPr = run._r.get_or_add_rPr()
    hl = OxmlElement("w:highlight")
    hl.set(qn("w:val"), couleur)
    rPr.append(hl)


def _filet_gold(document):
    """Filet doré séparateur (bordure basse d'un paragraphe vide)."""
    p = document.add_paragraph()
    pPr = p._p.get_or_add_pPr()
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "12")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), GOLD_HEX)
    pbdr.append(bottom)
    pPr.append(pbdr)


# ---------------------------------------------------------------------------
# Mode 1 — Template Tendia
# ---------------------------------------------------------------------------

def _page_de_garde(document, contexte):
    for _ in range(3):
        document.add_paragraph()
    # Placeholder logo Tendia
    logo = document.add_paragraph("TENDIA")
    logo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = logo.runs[0]
    r.font.name = POLICE_TITRES
    r.font.size = Pt(28)
    r.font.bold = True
    r.font.color.rgb = NAVY
    sous = document.add_paragraph("[ Logo Tendia — emplacement ]")
    sous.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sous.runs[0].font.size = Pt(8)
    sous.runs[0].font.color.rgb = GOLD

    _filet_gold(document)
    document.add_paragraph()

    titre = document.add_paragraph("MÉMOIRE TECHNIQUE")
    titre.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rt = titre.runs[0]
    rt.font.name = POLICE_TITRES
    rt.font.size = Pt(24)
    rt.font.bold = True
    rt.font.color.rgb = NAVY

    for libelle, valeur, taille in (
        (None, contexte["intitule_marche"], 14),
        ("Lot", f"{contexte['numero_lot']} — {contexte['intitule_lot']}", 13),
    ):
        p = document.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if libelle:
            p.add_run(f"{libelle} ").font.color.rgb = GOLD
        run = p.add_run(valeur or "")
        run.font.name = POLICE_TITRES
        run.font.size = Pt(taille)
        run.font.color.rgb = ANTHRACITE

    document.add_paragraph()
    _filet_gold(document)
    for _ in range(2):
        document.add_paragraph()

    for libelle, valeur in (
        ("Candidat", contexte["organisme"]),
        ("Marché", contexte["id_marche"]),
        ("Date de génération", contexte["date_lisible"]),
    ):
        p = document.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.add_run(f"{libelle} : ").bold = True
        p.add_run(valeur or "")

    document.add_page_break()


def assembler_tendia(memoire_obj: dict, profil: dict, contexte: dict) -> str:
    """Construit le .docx Tendia stylé. Retourne le chemin écrit."""
    document = Document()
    _styler_document(document)

    sec0 = document.sections[0]
    _mise_en_page_a4(sec0)

    # Page de garde (section sans en-tête/pied)
    _page_de_garde(document, contexte)

    # Nouvelle section pour le corps (en-tête/pied à partir d'ici)
    document.add_section(WD_SECTION.NEW_PAGE)
    sec_corps = document.sections[-1]
    _mise_en_page_a4(sec_corps)
    sec_corps.header.is_linked_to_previous = False
    sec_corps.footer.is_linked_to_previous = False
    _entete_pied(sec_corps, contexte["entete"], contexte["organisme"])

    # Sommaire — titre stylé manuellement (PAS de style Heading, sinon il se
    # listerait lui-même dans le TOC \o "1-3").
    h = document.add_paragraph()
    rh = h.add_run("Sommaire")
    rh.font.name = POLICE_TITRES
    rh.font.size = Pt(16)
    rh.font.bold = True
    rh.font.color.rgb = NAVY
    _add_toc(document, (memoire_obj.get("plan_redaction") or {}).get("plan_sections") or [])
    document.add_page_break()

    # Corps : sections du plan, dans l'ordre
    plan = (memoire_obj.get("plan_redaction") or {}).get("plan_sections") or []
    sections = memoire_obj.get("sections_redigees") or {}
    rendues = 0
    for spec in plan:
        if not isinstance(spec, dict):
            continue
        sid = spec.get("section_id")
        titre = spec.get("titre") or sid or "Section"
        niveau = spec.get("niveau") if spec.get("niveau") in (1, 2, 3) else 1
        h = document.add_heading(titre, level=niveau)
        if niveau == 1:
            _border_bottom(h, GOLD_HEX, sz="6")   # filet doré sous les sections
        texte = sections.get(sid)
        if texte:
            _ajouter_paragraphes_texte(document, texte)
            rendues += 1
        else:
            p = document.add_paragraph()
            _set_cell_or_par_shading(p, COMPLETER_FILL)
            _set_par_border(p, GOLD_HEX, val="dotted")
            run = p.add_run(f"[À COMPLÉTER : section « {titre} » non rédigée — "
                            f"relancer la génération ou regenerer_section.py]")
            run.bold = True
            run.font.color.rgb = RGBColor(0x7A, 0x5A, 0x00)

    # Sections hors-plan éventuelles (rendues en fin, H1)
    ids_plan = {s.get("section_id") for s in plan if isinstance(s, dict)}
    for sid, texte in sections.items():
        if sid in ids_plan:
            continue
        document.add_heading(sid, level=1)
        _ajouter_paragraphes_texte(document, texte)
        rendues += 1

    _force_update_fields(document)
    chemin = _chemin_sortie(contexte)
    document.save(chemin)
    return chemin


# ---------------------------------------------------------------------------
# Mode 2 — Injection dans le cadre de réponse acheteur
# ---------------------------------------------------------------------------

def _normaliser(s):
    import unicodedata
    s = (s or "").lower()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", s)


def _est_titre(paragraph):
    style = (paragraph.style.name or "") if paragraph.style else ""
    return style.startswith("Heading") or style.startswith("Titre")


def _insert_paragraph_after(paragraph, text=None):
    new_p = OxmlElement("w:p")
    paragraph._p.addnext(new_p)
    np = Paragraph(new_p, paragraph._parent)
    if text:
        np.add_run(text)
    return np


def injecter_template_acheteur(template_path: str, memoire_obj: dict, contexte: dict) -> str:
    """Ouvre le cadre acheteur, injecte les sections rédigées sous les titres
    correspondants. Ne modifie PAS les styles/en-têtes/pieds du template.
    Sections non rattachées → ajoutées en fin avec un titre H1. Retourne le chemin."""
    document = Document(template_path)
    plan = (memoire_obj.get("plan_redaction") or {}).get("plan_sections") or []
    sections = memoire_obj.get("sections_redigees") or {}

    # Index des titres du template
    titres = [(i, p, _normaliser(p.text)) for i, p in enumerate(document.paragraphs)
              if _est_titre(p) and p.text.strip()]

    non_rattachees = []
    for spec in plan:
        if not isinstance(spec, dict):
            continue
        sid = spec.get("section_id")
        texte = sections.get(sid)
        if not texte:
            continue
        cible = _meilleur_titre(spec, titres)
        if cible is None:
            non_rattachees.append((spec, texte))
            continue
        _injecter_sous_titre(document, cible, texte)

    # Sections non rattachées → fin de document, titre H1 (cf. spec règle 6)
    for spec, texte in non_rattachees:
        titre = spec.get("titre") or spec.get("section_id") or "Section complémentaire"
        print(f"  ⚠ Section « {titre} » sans zone d'injection dans le template — "
              f"ajoutée en fin de document.")
        document.add_heading(titre, level=1)
        for bloc in re.split(r"\n\s*\n", (texte or "").strip()):
            if bloc.strip():
                document.add_paragraph(bloc.replace("\n", " ").strip())

    chemin = _chemin_sortie(contexte)
    document.save(chemin)
    return chemin


def _meilleur_titre(spec, titres):
    """Apparie une section du plan à un titre du template (recouvrement de
    tokens significatifs ≥ 5 lettres)."""
    cible_txt = _normaliser((spec.get("titre") or "") + " " + (spec.get("section_id") or ""))
    toks = {t for t in cible_txt.split() if len(t) >= 5}
    if not toks:
        return None
    meilleur, meilleur_score = None, 0
    for _i, par, txt_norm in titres:
        toks_titre = {t for t in txt_norm.split() if len(t) >= 5}
        score = len(toks & toks_titre)
        if score > meilleur_score:
            meilleur, meilleur_score = par, score
    return meilleur if meilleur_score >= 1 else None


def _injecter_sous_titre(document, titre_par, texte):
    """Insère les paragraphes du texte juste après le titre cible. Ne modifie
    pas le style du titre."""
    curseur = titre_par
    for bloc in re.split(r"\n\s*\n", (texte or "").strip()):
        bloc = bloc.strip()
        if not bloc:
            continue
        curseur = _insert_paragraph_after(curseur, bloc.replace("\n", " "))


# ---------------------------------------------------------------------------
# Orchestrateur + chemin de sortie
# ---------------------------------------------------------------------------

def _chemin_sortie(contexte: dict) -> str:
    dossier = os.path.join(REPERTOIRE_MEMOIRES, contexte["id_marche"])
    os.makedirs(dossier, exist_ok=True)
    nom = f"{contexte['id_user']}_lot{contexte['numero_lot']}_{contexte['timestamp']}.docx"
    return os.path.join(dossier, nom)


def assembler(memoire_obj: dict, profil: dict, contexte: dict,
              template_acheteur: str = None, verbose: bool = True) -> str:
    """Point d'entrée. Choisit l'injection template acheteur si fourni ET
    valide, sinon le template Tendia. Retourne le chemin du .docx."""
    if template_acheteur and os.path.isfile(template_acheteur):
        try:
            if verbose:
                print(f"  🧩 Assemblage par INJECTION dans le cadre acheteur : "
                      f"{os.path.basename(template_acheteur)}")
            chemin = injecter_template_acheteur(template_acheteur, memoire_obj, contexte)
            if verbose:
                print(f"  ✓ .docx (cadre acheteur) écrit : {chemin}")
            return chemin
        except Exception as e:
            # On NE réécrit pas le template ; on bascule sur le template Tendia.
            print(f"  ⚠ Injection cadre acheteur échouée ({type(e).__name__}: {e}) — "
                  f"bascule sur le template Tendia.")

    if verbose:
        print("  🎨 Assemblage avec le template Tendia.")
    chemin = assembler_tendia(memoire_obj, profil, contexte)
    if verbose:
        print(f"  ✓ .docx (Tendia) écrit : {chemin}")
    return chemin
