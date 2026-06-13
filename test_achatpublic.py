"""
test_achatpublic.py
-------------------
Test du téléchargeur achatpublic sur 1 marché de la base.
Lecture seule de la base, écriture uniquement dans data/dce/<id>/.

Usage : python test_achatpublic.py
"""
import io
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import achatpublic_downloader as A


def main():
    marches = stockage.charger("marches")
    # Cibler tout marché achatpublic, idéalement en auth_requise (= jamais récupéré)
    candidats = [
        (mid, m) for mid, m in marches.items()
        if "achatpublic.com" in (m.get("url_dce") or "")
    ]

    if not candidats:
        print("Aucun marché achatpublic dans la base.")
        sys.exit(1)

    # Prioriser : auth_requise > vide > autre
    auth = [c for c in candidats if c[1].get("dce_contenu") == "auth_requise"]
    if auth:
        candidats = auth
        print(f"{len(auth)} marchés achatpublic en auth_requise.")
    mid, marche = candidats[0]

    print(f"\n=== TEST achatpublic : {mid} ===")
    print(f"URL DCE : {marche.get('url_dce')}")
    print(f"dce_contenu actuel : {marche.get('dce_contenu')}")
    print(f"dce_pieces actuelles : {marche.get('dce_pieces_contractuelles')}")
    print()
    print("Tentative de telechargement complet via achatpublic_downloader...")
    print("-" * 60)

    result = A.telecharger_dce_pour_marche(marche, "data/dce", verbose=True)

    print("-" * 60)
    print("\n=== RESULTAT ===")
    for cle, val in result.items():
        print(f"  {cle} : {val}")

    if result.get("ok"):
        print("\n>>> SUCCES : le ZIP est telecharge. Contenu :")
        chemin = result.get("chemin")
        if chemin:
            try:
                with zipfile.ZipFile(chemin) as z:
                    noms = z.namelist()
                    print(f"    {len(noms)} fichiers :")
                    for n in noms[:20]:
                        print(f"      - {n}")
                    if len(noms) > 20:
                        print(f"      ... +{len(noms) - 20} autres")
            except Exception as e:
                print(f"    ZIP non lisible : {e}")
    else:
        print("\n>>> ECHEC : voir l'erreur ci-dessus.")
        print("    Si erreur = 'dceId introuvable' -> structure HTML achatpublic")
        print("      a peut-etre evolue, inspecter la page manuellement.")
        print("    Si erreur = 'Reponse HTML au lieu de ZIP' -> le marche")
        print("      est peut-etre clos ou restreint.")


if __name__ == "__main__":
    main()
