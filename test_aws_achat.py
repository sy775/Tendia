"""
test_aws_achat.py
-----------------
Test du téléchargeur AWS-Achat (www.marches-publics.info) sur 1 marché de la
base, avec verbose. Lecture seule de la base, écriture uniquement dans
data/dce/<id>/. Coût ~0,001 € (1 captcha 2captcha).

Usage : python test_aws_achat.py [IDM_ou_id_marche]
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import tendia_dce
import aws_downloader as A


def main():
    marches = stockage.charger("marches") or {}
    candidats = [
        (mid, m) for mid, m in marches.items()
        if "marches-publics.info" in (m.get("url_dce") or "")
    ]

    if not candidats:
        print("Aucun marché www.marches-publics.info dans la base.")
        sys.exit(1)

    # Sélection : argument explicite, sinon priorité auth_requise > vide > autre.
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg:
        candidats = [(mid, m) for mid, m in candidats
                     if mid == arg or A._extraire_idm_depuis_url(m.get("url_dce") or "") == arg]
        if not candidats:
            print(f"Marché/IDM {arg} introuvable parmi les marchés AWS-Achat.")
            sys.exit(1)
    else:
        auth = [c for c in candidats if c[1].get("dce_contenu") == "auth_requise"]
        if auth:
            print(f"{len(auth)} marchés AWS-Achat en auth_requise.")
            candidats = auth

    mid, marche = candidats[0]
    idm = A._extraire_idm_depuis_url(marche.get("url_dce") or "")

    print(f"\n=== TEST AWS-Achat : {mid} (IDM={idm}) ===")
    print(f"URL DCE : {marche.get('url_dce')}")
    print(f"dce_contenu actuel : {marche.get('dce_contenu')}")
    print(f"dce_pieces actuelles : {marche.get('dce_pieces_contractuelles')}")
    print()
    print("Téléchargement complet via aws_downloader (2captcha)...")
    print("-" * 60)

    result = A.telecharger_dce_pour_marche(marche, "data/dce", verbose=True)

    print("-" * 60)
    print("\n=== RÉSULTAT ===")
    for cle, val in result.items():
        if cle == "fichiers_telecharges":
            print(f"  {cle} : {len(val)} fichier(s)")
        else:
            print(f"  {cle} : {val}")

    if result.get("ok"):
        dossier = result.get("chemin")
        print(f"\n>>> SUCCÈS. Qualification du dossier {dossier} :")
        qual = tendia_dce.qualifier_dce(dossier)
        print(f"    qualité            : {qual['qualite']}")
        print(f"    pièces contractuelles : {qual['pieces_contractuelles']}")
        print(f"    raison             : {qual['raison']}")
        if qual["qualite"] == "complet":
            print("    ✅ DCE complet (RC/CCAP/CCTP/DPGF/LOT détectés)")
        else:
            print("    ⚠ DCE non complet — inspecter le contenu téléchargé.")
    else:
        print(f"\n>>> ÉCHEC (étape={result.get('etape_erreur')}) : {result.get('erreur')}")
        if result.get("solde_2captcha_epuise"):
            print("    → Recharger le compte 2captcha.")


if __name__ == "__main__":
    main()
