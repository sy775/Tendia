"""
tests_qualifier_dce.py
----------------------
Tests unitaires de tendia_dce.qualifier_dce sur des dossiers fabriqués.
Lancement : python tests_qualifier_dce.py
"""
import io
import os
import sys
import tempfile
import zipfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import tendia_dce as T


def _dossier(fichiers: dict, zips: dict = None):
    """Crée un dossier temporaire. fichiers={nom: contenu_bytes}, zips={nom: [noms_internes]}."""
    d = tempfile.mkdtemp(prefix="dcetest_")
    for nom, contenu in (fichiers or {}).items():
        with open(os.path.join(d, nom), "wb") as f:
            f.write(contenu if isinstance(contenu, bytes) else contenu.encode("utf-8"))
    for nom, internes in (zips or {}).items():
        with zipfile.ZipFile(os.path.join(d, nom), "w") as z:
            for ni in internes:
                z.writestr(ni, b"x" * 2048)
    return d


KO = "\033[0m"
ok = 0
ko = 0


def verif(nom, dossier, qualite_attendue, pieces_attendues=None, log=None):
    global ok, ko
    r = T.qualifier_dce(dossier, log)
    cond = r["qualite"] == qualite_attendue
    if pieces_attendues is not None:
        cond = cond and set(r["pieces_contractuelles"]) == set(pieces_attendues)
    statut = "✓" if cond else "✗ ÉCHEC"
    if cond:
        ok += 1
    else:
        ko += 1
    print(f"  {statut}  {nom:<42} -> {r['qualite']:<12} {r['pieces_contractuelles']}  ({r['raison']})")


PDF = b"%PDF-1.4\n" + b"0" * 5000  # ~5 ko, > seuil 1ko

print("=== Tests qualifier_dce ===")
verif("dossier vide", _dossier({}), "vide")
verif("depot-pli seul", _dossier({"depot-pli.pdf": PDF}), "vide")
verif("RC seul", _dossier({"RC.pdf": PDF}), "incomplet", ["RC"])
verif("RC + CCAP + CCTP", _dossier({"RC.pdf": PDF, "CCAP.pdf": PDF, "CCTP.pdf": PDF}),
      "complet", ["RC", "CCAP", "CCTP"])
verif("login.html (password)",
      _dossier({"page.html": "<html><form action=login><input type=password></form></html>"}),
      "auth_requise")
verif("DUME.zip + xml",
      _dossier({"data.xml": PDF}, zips={"DUME Acheteur.zip": ["dume.xml"]}),
      "vide")
verif("noms longs FR (RC + CCAP)",
      _dossier({"Reglement_de_consultation.pdf": PDF,
                "Clauses_administratives_particulieres.pdf": PDF}),
      "complet", ["RC", "CCAP"])
verif("ZIP contenant RC + CCTP",
      _dossier({}, zips={"DCE.zip": ["RC.pdf", "CCTP.pdf"]}),
      "complet", ["RC", "CCTP"])
verif("erreur reseau (log)", _dossier({"RC.pdf": PDF}), "erreur",
      log={"statut": "erreur", "raison": "HTTP 503"})
verif("EntrepriseDetailsConsultation html",
      _dossier({"consultation.html": "<html>EntrepriseDetailsConsultation veuillez vous connecter</html>"}),
      "auth_requise")

print(f"\n=== {ok} OK / {ko} KO ===")
sys.exit(1 if ko else 0)
