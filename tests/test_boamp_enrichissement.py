"""
tests/test_boamp_enrichissement.py — Lancement : python tests/test_boamp_enrichissement.py

Couvre l'extraction des ~31 champs d'enrichissement v2 (cf. docs/modules/marche.md
SECTION 1) sur des avis synthétiques eForms et legacy. 0 réseau.
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connecteurs.boamp import extraire_champs_enrichissement

ok = ko = 0


def check(nom, cond):
    global ok, ko
    if cond:
        ok += 1; print(f"  ✓ {nom}")
    else:
        ko += 1; print(f"  ✗ ÉCHEC {nom}")


# --- Avis eForms synthétique (structure UBL réaliste) ---
DONNEES_EFORMS = {
    "EFORMS": {"ContractNotice": {
        "cbc:BuyerProfileURI": "https://www.achatpublic.com/sdm/ent2/gen/index.jsp",
        "cbc:EndpointID": "https://www.achatpublic.com/sdm/ent/gen/ent_detail.do?PCSLID=CSL_2026_ABCdef&autre=1",
        "efac:Organizations": {"efac:Organization": [
            {"efac:Company": {
                "cac:PartyIdentification": {"cbc:CompanyID": "775 682 917"},
                "cac:PostalAddress": {
                    "cbc:StreetName": "104-110 BOULEVARD HAUSSMANN",
                    "cbc:CityName": "Paris",
                    "cbc:PostalZone": "75008",
                    "cbc:CountrySubentityCode": {"@listName": "nuts", "#text": "FR101"},
                    "cac:Country": {"cbc:IdentificationCode": "FRA"},
                }}}]},
        "cac:ProcurementProject": {
            "cbc:Name": "Restauration collective",
            "cac:MainCommodityClassification": {
                "cbc:ItemClassificationCode": {"@listName": "cpv", "#text": "55320000"}}},
        "cac:ProcurementProjectLot": [
            {"cbc:ID": "LOT-0001",
             "cac:ProcurementProject": {
                 "cbc:Name": "Lot 1 : RIE Paris",
                 "cbc:Description": "Restauration inter-entreprises site parisien",
                 "cac:MainCommodityClassification": {
                     "cbc:ItemClassificationCode": {"#text": "55321000"}},
                 "cac:PlannedPeriod": {"cbc:DurationMeasure": {"@unitCode": "MONTH", "#text": "48"}}},
             "cac:RequestedTenderTotal": {
                 "cbc:EstimatedOverallContractAmount": {"@currencyID": "EUR", "#text": "500000"}}},
            {"cbc:ID": "LOT-0002",
             "cac:ProcurementProject": {"cbc:Name": "Lot 2 : RIE Chartres"}},
        ],
        "cbc:EstimatedOverallContractAmount": {"@currencyID": "EUR", "#text": "0.00"},
    }}
}

AVIS_EFORMS = {
    "idweb": "26-99999", "nature": "APPEL_OFFRE", "nature_libelle": "Avis de marché",
    "procedure_libelle": "Procédure ouverte", "criteres": ["sociaux", "environnementaux"],
    "famille": "JOUE", "famille_libelle": "Marchés européens",
    "contractfolderid": "abc-123", "datefindiffusion": "2026-07-29", "etat": "INITIAL",
    "type_avis": ["5", "1"], "source_schema": "3.2.5",
    "donnees": json.dumps(DONNEES_EFORMS, ensure_ascii=False),
}

# --- Avis legacy (pas de bloc donnees eForms) ---
AVIS_LEGACY = {
    "idweb": "26-88888", "nature": "MAPA", "nature_libelle": "MAPA",
    "famille": "MAPA", "famille_libelle": "Marchés nationaux",
    "etat": "INITIAL", "donnees": None,
}


print("Avis eForms — trio critique")
e = extraire_champs_enrichissement(AVIS_EFORMS, source="test")
check("acheteur_siren = 9 chiffres", e["acheteur_siren"] == "775682917")
check("url_consultation_dce_directe contient PCSLID",
      "PCSLID=CSL_2026_ABCdef" in (e["url_consultation_dce_directe"] or ""))
check("montant_estime_eur = 0.0 (présent mais nul)", e["montant_estime_eur"] == 0.0)

print("Avis eForms — priorité 1 (géo + lots)")
check("url_profil_acheteur", e["url_profil_acheteur"].startswith("https://www.achatpublic.com"))
check("acheteur_ville = Paris", e["acheteur_ville"] == "Paris")
check("acheteur_code_postal = 75008", e["acheteur_code_postal"] == "75008")
check("acheteur_nuts = FR101", e["acheteur_nuts"] == "FR101")
check("nombre_lots = 2", e["nombre_lots"] == 2)
lot1 = e["lots_json"][0]
check("lot1 intitule", lot1.get("intitule") == "Lot 1 : RIE Paris")
check("lot1 description_complete (amendement)",
      lot1.get("description_complete") == "Restauration inter-entreprises site parisien")
check("lot1 cpv", lot1.get("cpv") == "55321000")
check("lot1 montant_estime = 500000", lot1.get("montant_estime") == 500000.0)
check("lot1 duree = 48 mois", lot1.get("duree") == 48)

print("Avis eForms — priorité 2/3")
check("cpv_secondaires = [55321000]", e["cpv_secondaires"] == ["55321000"])
check("nature", e["nature"] == "APPEL_OFFRE")
check("procedure_libelle", e["procedure_libelle"] == "Procédure ouverte")
check("criteres_attribution", e["criteres_attribution"] == ["sociaux", "environnementaux"])
check("est_europeen (JOUE) = True", e["est_europeen"] is True)
check("acheteur_adresse", "HAUSSMANN" in (e["acheteur_adresse"] or ""))
check("dce_consultation_id", e["dce_consultation_id"] == "abc-123")
check("date_fin_diffusion", e["date_fin_diffusion"] == "2026-07-29")

print("Avis eForms — méta")
check("enrichissement_version = v2", e["enrichissement_version"] == "v2")
check("enrichissement_source = test", e["enrichissement_source"] == "test")
check("montant dans champs_absents (car 0)", "montant_estime_eur" in e["enrichissement_champs_absents"])
check("source_schema_eforms = 3.2.5", e["source_schema_eforms"] == "3.2.5")
check("donnees_boamp_brut est une string JSON", isinstance(e["donnees_boamp_brut"], str)
      and "26-99999" in e["donnees_boamp_brut"])

print("Avis legacy — dégradation gracieuse")
l = extraire_champs_enrichissement(AVIS_LEGACY, source="test")
check("acheteur_siren absent → None", l["acheteur_siren"] is None)
check("url_consultation_dce_directe absent → None", l["url_consultation_dce_directe"] is None)
check("nombre_lots = 0", l["nombre_lots"] == 0)
check("est_europeen (MAPA) = False", l["est_europeen"] is False)
check("nature ODS toujours lue", l["nature"] == "MAPA")
check("méta présente même en legacy", l["enrichissement_version"] == "v2")
check("plusieurs champs dans absents", len(l["enrichissement_champs_absents"]) >= 8)

print(f"\n=== {ok} OK / {ko} KO ===")
sys.exit(1 if ko else 0)
