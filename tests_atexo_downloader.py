"""
tests_atexo_downloader.py
-------------------------
Tests HORS-LIGNE des helpers purs de atexo_downloader (aucun réseau).
Lancement : python tests_atexo_downloader.py
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import atexo_downloader as A

ok = 0
ko = 0


def check(nom, cond):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}")


print("=== _detecter_url_base (hosts Atexo) ===")
CAS_OK = {
    "https://www.marches-publics.gouv.fr/?page=Entreprise.EntrepriseDetailsConsultation&id=3003304&orgAcronyme=h8j": "https://www.marches-publics.gouv.fr",
    "https://marches.ternum-bfc.fr/?page=Entreprise.EntrepriseDetailsConsultation&id=12&orgAcronyme=abc": "https://marches.ternum-bfc.fr",
    "https://demat-ampa.fr/?page=Entreprise.x&id=9&orgAcronyme=zz": "https://demat-ampa.fr",
    "https://marches.megalis.bretagne.bzh/?page=Entreprise.x&id=5&orgAcronyme=mg": "https://marches.megalis.bretagne.bzh",
    "https://marches.maximilien.fr/?page=Entreprise.x&id=7&orgAcronyme=mx": "https://marches.maximilien.fr",
}
for url, attendu in CAS_OK.items():
    check(f"base = {attendu}", A._detecter_url_base(url) == attendu)

print("\n=== _detecter_url_base (signature Atexo sur fork municipal) ===")
check("fork municipal inconnu mais signature Atexo -> détecté",
      A._detecter_url_base("https://profilacheteur.example.fr/index.php?page=Entreprise.EntrepriseDetailsConsultation&id=42&orgAcronyme=ex")
      == "https://profilacheteur.example.fr")

print("\n=== _detecter_url_base (exclusions) ===")
check("e-marchespublics -> None", A._detecter_url_base("https://ccas-calais.e-marchespublics.com/?id=1&orgAcronyme=x&page=Entreprise.x") is None)
check("marches-publics.info (auth) -> None", A._detecter_url_base("https://www.marches-publics.info/?id=1&orgAcronyme=x&page=Entreprise.x") is None)
check("achatpublic (auth) -> None", A._detecter_url_base("https://www.achatpublic.com/x") is None)
check("url quelconque sans signature -> None", A._detecter_url_base("https://mairie-xyz.fr/dce/page") is None)
check("url vide -> None", A._detecter_url_base("") is None)

print("\n=== _extraire_id_org_depuis_url ===")
cas = [
    ("https://www.marches-publics.gouv.fr/?page=Entreprise.EntrepriseDetailsConsultation&id=3003304&orgAcronyme=h8j", "3003304", "h8j"),
    ("https://marches.ternum-bfc.fr/?id=12345&orgAcronyme=abc123", "12345", "abc123"),
    ("https://www.marches-publics.gouv.fr/app.php/entreprise/consultation/9999?orgAcronyme=zz", "9999", "zz"),
    ("https://demat-ampa.fr/?orgAcronyme=mg&id=77&page=x", "77", "mg"),
    ("https://x.fr/?page=y", None, None),
]
for url, eid, eorg in cas:
    i, o = A._extraire_id_org_depuis_url(url)
    check(f"id={eid} org={eorg}", i == eid and o == eorg)

print("\n=== _extraire_inputs_form (HTML Prado mocké) ===")
HTML = '''
<form name="main_form" action="/index.php?page=x&amp;y=1">
  <input type="hidden" name="PRADO_PAGESTATE" value="ABCDEF1234567890" />
  <input type="text" name="ctl0$nom" value="Jean" />
  <input type="radio" name="ctl0$choix" value="ctl0_choixAnonyme" checked />
  <input type="radio" name="ctl0$choix" value="ctl0_choixIdentifie" />
  <input type="checkbox" name="ctl0$accepterConditions" />
  <input type="submit" name="ctl0$valider" value="Valider" />
</form>
'''
fields = A._extraire_inputs_form(HTML)
print("  champs:", {k: (v[:20] if isinstance(v, str) else v) for k, v in fields.items()})
check("PRADO_PAGESTATE capturé", fields.get("PRADO_PAGESTATE") == "ABCDEF1234567890")
check("input texte capturé", fields.get("ctl0$nom") == "Jean")
check("radio checked capturé", fields.get("ctl0$choix") == "ctl0_choixAnonyme")
check("radio non-checked ignoré (1 seule valeur radio)", fields.get("ctl0$choix") != "ctl0_choixIdentifie")
check("checkbox non-checked absente", "ctl0$accepterConditions" not in fields)
check("submit ignoré", "ctl0$valider" not in fields)

print("\n=== _trouver_event_target (JS Prado mocké) ===")
JS = '''<script>
new Prado.WebUI.TLinkButton({'ID':'ctl0_x','EventTarget':"ctl0$CONTENU$completeDownload",'CausesValidation':false});
</script>'''
et = A._trouver_event_target(JS, "completeDownload")
print("  event_target:", et)
check("EventTarget extrait", et == "ctl0$CONTENU$completeDownload")
check("EventTarget absent -> None", A._trouver_event_target("<script>rien</script>") is None)

print("\n=== _construire_url_formulaire ===")
u = A._construire_url_formulaire(3003304, "h8j", "https://marches.ternum-bfc.fr")
check("url formulaire correcte (url_base dynamique)",
      u == "https://marches.ternum-bfc.fr/index.php?page=Entreprise.EntrepriseDemandeTelechargementDce&id=3003304&orgAcronyme=h8j")

print(f"\n=== {ok} OK / {ko} KO ===")
sys.exit(1 if ko else 0)
