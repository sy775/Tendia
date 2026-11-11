# -*- coding: utf-8 -*-
"""
tests/fixtures/generer_dce_mixte.py
-----------------------------------
Régénère les fixtures légères tests/fixtures/dce_mixte/ et dce_conversion/ (DCE
fictif : ZIP imbriqué, sous-dossier, .rar, plan, doublon, format inconnu, .docx).
Les fichiers produits sont suivis par git ; ce script ne sert qu'à les refaire.

    python tests/fixtures/generer_dce_mixte.py
"""
import io
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ICI = Path(__file__).resolve().parent
MIXTE = ICI / "dce_mixte"
CONVERSION = ICI / "dce_conversion"


def pdf(pages: list) -> bytes:
    """PDF minimal, une liste de lignes par page (Helvetica, WinAnsi : accents lisibles par pypdf)."""
    objets = []

    def ajouter(contenu: bytes) -> int:
        objets.append(contenu)
        return len(objets)

    ajouter(b"")   # 1 : catalogue (rempli à la fin)
    ajouter(b"")   # 2 : pages
    police = ajouter(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    ids_pages = []
    for lignes in pages:
        flux = [b"BT /F1 11 Tf 50 780 Td 14 TL"]
        for ligne in lignes:
            texte = ligne.encode("cp1252").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
            flux.append(b"(" + texte + b") Tj T*")
        flux.append(b"ET")
        corps = b"\n".join(flux)
        contenu = ajouter(b"<< /Length %d >>\nstream\n" % len(corps) + corps + b"\nendstream")
        ids_pages.append(ajouter(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents %d 0 R "
            b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (contenu, police)))
    objets[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objets[1] = (b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % i for i in ids_pages)
                 + b"] /Count %d >>" % len(ids_pages))
    sortie = io.BytesIO()
    sortie.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    positions = []
    for i, contenu in enumerate(objets, 1):
        positions.append(sortie.tell())
        sortie.write(b"%d 0 obj\n" % i + contenu + b"\nendobj\n")
    debut_xref = sortie.tell()
    sortie.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objets) + 1))
    for p in positions:
        sortie.write(b"%010d 00000 n \n" % p)
    sortie.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objets) + 1, debut_xref))
    return sortie.getvalue()


def remplir(n: int) -> list:
    """Lignes de remplissage : une pièce de texte fait plus de 200 caractères par page."""
    return [f"Article {i} : les stipulations du présent article s'appliquent au titulaire du marché."
            for i in range(1, n + 1)]


RC = pdf([
    ["RÈGLEMENT DE LA CONSULTATION", "Commune de Fixture-sur-Test",
     "Objet : réfection de la toiture de l'école Jean Moulin", "Marché de travaux, procédure adaptée."]
    + remplir(6),
    ["Article 5 : jugement des offres",
     "Les critères sont pondérés : prix des prestations 40 %, valeur technique 60 %.",
     "Article 6 : remise des offres",
     "Date limite de remise des offres : 15 décembre 2026 à 12 h 00.",
     "Une visite du site est obligatoire avant la remise de l'offre."] + remplir(6),
])
CCAP = pdf([["CAHIER DES CLAUSES ADMINISTRATIVES PARTICULIÈRES",
             "Pénalités de retard : 150 euros par jour calendaire.",
             "Retenue de garantie : 5 %."] + remplir(8)])
CCTP = pdf([["CAHIER DES CLAUSES TECHNIQUES PARTICULIÈRES",
             "Lot unique : couverture en tuiles de terre cuite, 420 m2."] + remplir(8)])
PLAN = pdf([["PLAN DE MASSE", "Échelle 1/200"]])


def zip_octets(fichiers: dict) -> bytes:
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as z:
        for nom, contenu in sorted(fichiers.items()):
            info = zipfile.ZipInfo(nom, date_time=(2026, 11, 11, 0, 0, 0))   # date fixe : zip reproductible
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, contenu)
    return tampon.getvalue()


def bpu_xlsx() -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "BPU"
    ws.append(["N°", "Désignation", "Unité", "Quantité", "Prix unitaire HT"])
    ws.append([1, "Dépose de la couverture existante", "m2", 420, None])
    ws.append([2, "Fourniture et pose de tuiles de terre cuite", "m2", 420, None])
    ws.append([3, "Zinguerie, gouttières et descentes", "ml", 96, None])
    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


def ae_docx() -> bytes:
    from docx import Document
    doc = Document()
    doc.add_heading("ACTE D'ENGAGEMENT", 0)
    doc.add_paragraph("Marché de travaux : réfection de la toiture de l'école Jean Moulin.")
    for ligne in remplir(8):
        doc.add_paragraph(ligne)
    tampon = io.BytesIO()
    doc.save(tampon)
    return tampon.getvalue()


def main():
    (MIXTE / "sous_dossier").mkdir(parents=True, exist_ok=True)
    CONVERSION.mkdir(parents=True, exist_ok=True)
    interne = zip_octets({"CCTP.pdf": CCTP})
    fichiers = {
        MIXTE / "RC.pdf": RC,
        MIXTE / "plan_masse.pdf": PLAN,
        MIXTE / "photo_chantier.jpg": b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9",
        MIXTE / "pieces_complementaires.rar": b"Rar!\x1a\x07\x00" + b"\x00" * 32,
        MIXTE / "maquette.xyz": b"format inconnu de test",
        # zip : une pièce, un zip imbriqué, et une copie du RC (doublon par empreinte)
        MIXTE / "dossier_administratif.zip": zip_octets({
            "CCAP.pdf": CCAP, "technique/pieces_techniques.zip": interne, "RC_copie_zip.pdf": RC}),
        MIXTE / "sous_dossier" / "BPU.xlsx": bpu_xlsx(),
        MIXTE / "sous_dossier" / "RC_copie.pdf": RC,     # doublon par empreinte, hors zip
        CONVERSION / "AE.docx": ae_docx(),
    }
    for chemin, contenu in fichiers.items():
        chemin.write_bytes(contenu)
        print(f"  {chemin.relative_to(ICI)}  {len(contenu)} octets")


if __name__ == "__main__":
    main()
