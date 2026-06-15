"""
tests_boamp_contact.py
----------------------
Tests de l'extraction du contact (correspondant) depuis l'avis BOAMP
(`connecteurs.boamp._extraire_contact`).

Couvre les 3 variantes structurelles du champ `donnees` :
- A : legacy correspondantPRM (identité) + coord (mel/tel) ;
- B : legacy bloc communication (nomContact/adresseMailContact/telContact) ;
- C : eForms UBL cac:Contact imbriqué profond ;
plus cas limites (aucun contact, email dans le champ nom).

Lancement : python tests_boamp_contact.py
"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from connecteurs import boamp

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


def _avis(donnees_obj):
    """Emballe une structure `donnees` comme l'API BOAMP (chaîne JSON)."""
    return {"donnees": json.dumps(donnees_obj, ensure_ascii=False)}


# --- Variante A : correspondantPRM + coord ---
avis_a = _avis({"MAPA": {"organisme": {
    "correspondantPRM": {"civilite": "MME", "nom": "SERGI", "pren": "Valérie",
                          "fonc": "La Vice-Présidente du CCAS"},
    "coord": {"tel": "0493135140", "mel": "dao@nicecotedazur.org"},
}}})
ca = boamp._extraire_contact(avis_a)
print("Variante A (correspondantPRM + coord)")
check("nom prénom+nom", ca and ca.get("nom") == "Valérie SERGI")
check("civilite", ca and ca.get("civilite") == "MME")
check("fonction", ca and ca.get("fonction", "").startswith("La Vice-Présidente"))
check("email", ca and ca.get("email") == "dao@nicecotedazur.org")
check("telephone", ca and ca.get("telephone") == "0493135140")

# --- Variante B : bloc communication ---
avis_b = _avis({"FNSimple": {"initial": {"communication": {
    "nomContact": "M. le Président",
    "adresseMailContact": "contact@coeurdeloire.fr",
    "telContact": "+33 386289292",
}}}})
cb = boamp._extraire_contact(avis_b)
print("Variante B (communication)")
check("nom", cb and cb.get("nom") == "M. le Président")
check("email", cb and cb.get("email") == "contact@coeurdeloire.fr")
check("telephone", cb and cb.get("telephone") == "+33 386289292")

# --- Variante C : eForms UBL cac:Contact imbriqué profond (~10 niveaux) ---
avis_c = _avis({"EFORMS": {"ContractNotice": {"ext:UBLExtensions": {
    "ext:UBLExtension": {"ext:ExtensionContent": {"efext:EformsExtension": {
        "efac:Organizations": {"efac:Organization": [
            {"efac:Company": {"cac:Contact": {
                "cbc:Name": "Cellule achats",
                "cbc:ElectronicMail": "cellule.achats-marches@villepetitcanal.fr",
                "cbc:Telephone": "0590226204",
            }}},
            {"efac:Company": {"cac:Contact": {
                "cbc:ElectronicMail": "greffe.ta-guadeloupe@juradm.fr",
            }}},
        ]}}}}}}}})
cc = boamp._extraire_contact(avis_c)
print("Variante C (eForms profond, 1re organisation = acheteur)")
check("email acheteur (pas tribunal)",
      cc and cc.get("email") == "cellule.achats-marches@villepetitcanal.fr")
check("telephone", cc and cc.get("telephone") == "0590226204")

# --- Cas limite : aucun contact ---
avis_vide = _avis({"FNSimple": {"objet": "Travaux de voirie"}})
print("Cas limite : aucun contact")
check("retourne None", boamp._extraire_contact(avis_vide) is None)
check("donnees absent -> None", boamp._extraire_contact({}) is None)
check("donnees non-JSON -> None",
      boamp._extraire_contact({"donnees": "pas du json {"}) is None)

# --- Cas limite : email saisi dans le champ nom ---
avis_email_nom = _avis({"FNSimple": {"initial": {"communication": {
    "nomContact": "servicedesmarches@maregionsud.fr",
}}}})
cen = boamp._extraire_contact(avis_email_nom)
print("Cas limite : email dans le champ nom")
check("nom promu en email", cen and cen.get("email") == "servicedesmarches@maregionsud.fr")

# --- Préférence : candidat avec email l'emporte ---
avis_mix = _avis({"X": {
    "correspondantPRM": {"nom": "DUPONT", "pren": "Jean"},   # nom seul, pas d'email
    "initial": {"communication": {"adresseMailContact": "ze@mairie.fr"}},  # email
}})
cm = boamp._extraire_contact(avis_mix)
print("Préférence candidat avec email")
check("email présent", cm and cm.get("email") == "ze@mairie.fr")

print(f"\n=== {ok} OK / {ko} KO ===")
sys.exit(1 if ko else 0)
