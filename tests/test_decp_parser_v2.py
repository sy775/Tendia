"""
tests/test_decp_parser_v2.py — Lancement : python tests/test_decp_parser_v2.py (hors ligne)
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tendia.prix.decp.parser_v2 import contrat_depuis_lignes, normaliser_identifiant, valider_siren

ok = ko = 0


def check(nom, cond):
    global ok, ko
    if cond:
        ok += 1; print(f"  ✓ {nom}")
    else:
        ko += 1; print(f"  ✗ ÉCHEC {nom}")


print("valider_siren")
check("SIREN valide", valider_siren("130005481"))
check("SIREN Luhn KO", not valider_siren("130005482"))
check("SIREN 8 chiffres", not valider_siren("13000548"))

print("normaliser_identifiant")
n = normaliser_identifiant("130 005 481 00010", "SIRET")
check("SIRET avec espaces → siret+siren", n["siret"] == "13000548100010" and n["siren"] == "130005481")
check("type absent traité comme SIRET", normaliser_identifiant("13000548100010", None)["valide"] == 1)
n = normaliser_identifiant("13000548100011", "SIRET")
check("SIRET Luhn KO mais SIREN OK → siren seul", n["siret"] is None and n["siren"] == "130005481"
      and n["motif_rejet"] == "siret_luhn_ko_siren_ok")
check("TVA FR → siren", normaliser_identifiant("FR12130005481", "TVA")["siren"] == "130005481")
check("TVA_INTRACOMMUNAUTAIRE (format 2022) = TVA", normaliser_identifiant("FR12130005481", "TVA_INTRACOMMUNAUTAIRE")["siren"] == "130005481")
check("TVA étrangère → rejet", normaliser_identifiant("DE123456789", "TVA")["valide"] == 0)
check("HORS-UE → pas de siren", normaliser_identifiant("ABC123", "HORS-UE")["motif_rejet"] == "type_hors-ue")
check("caractères parasites → rejet", normaliser_identifiant("NC", "SIRET")["motif_rejet"] == "caracteres_parasites")
check("longueur 5 → rejet", normaliser_identifiant("75012", "SIRET")["motif_rejet"] == "longueur_5")
check("vide → rejet", normaliser_identifiant("", "SIRET")["motif_rejet"] == "vide")

print("contrat_depuis_lignes")
base = {"uid": "2175000160001926F1_45000000", "id": "26F1", "acheteur_id": "21750001600019",
        "codeCPV": "45000000", "dateNotification": "2026-05-02", "montant": "120000.0",
        "dureeMois": "12.0", "typeGroupementOperateurs": "Solidaire", "sousTraitanceDeclaree": "false",
        "offresRecues": "3", "acheteur_departement_code": "75", "montant_rationalise": "120000.0",
        "modification_id": "0", "datePublicationDonnees": "2026-05-10"}
l1 = dict(base, titulaire_id="13000548100010", titulaire_typeIdentifiant="SIRET", titulaire_nom="A")
l2 = dict(base, titulaire_id="33071536800297", titulaire_typeIdentifiant="SIRET", titulaire_nom="B")
c, ts = contrat_depuis_lignes([l1, l2, dict(l2)], "test")
check("clé uid", c["uid"] == base["uid"] and c["id"] == "26F1")
check("titulaire répété dédoublonné", len(ts) == 2 and c["nb_titulaires"] == 2)
check("rôles groupement", ts[0]["role"] == "mandataire_presume" and ts[1]["role"] == "cotraitant")
check("titulaires_json compat v1", c["titulaires_json"] == '["13000548100010", "33071536800297"]')
check("types CSV convertis", c["montant_eur"] == 120000.0 and c["duree_mois"] == 12
      and c["sous_traitance_declaree"] == 0 and c["offres_recues"] == 3)
check("titulaire 1 en colonnes", c["titulaire_nom"] == "A" and c["titulaire_siret"] == "13000548100010")
c, ts = contrat_depuis_lignes([dict(l1, typeGroupementOperateurs="Pas de groupement"), dict(l2, typeGroupementOperateurs="Pas de groupement")], "t")
check("multi-attributaires sans groupement", {t["role"] for t in ts} == {"co_attributaire"})
c, ts = contrat_depuis_lignes([l1], "t")
check("titulaire seul", ts[0]["role"] == "titulaire" and c["titulaires_json"] is None)
c, _ = contrat_depuis_lignes([dict(l1, montant="2000000000")], "t")
check("montant > 1 Md écarté", c["montant_eur"] is None and "montant_aberrant" in c["parse_warnings"])
check("pas d'uid → None", contrat_depuis_lignes([{"id": "x"}], "t") is None)

print(f"\n=== {ok} OK / {ko} KO ===")
sys.exit(1 if ko else 0)
