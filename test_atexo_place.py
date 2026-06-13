"""
test_atexo_place.py
-------------------
Test le téléchargeur Atexo (Apptia généralisé) sur 1 marché PLACE incomplet.
Lecture seule de la base, écriture uniquement dans data/dce/<id>/.

Usage : python test_atexo_place.py
"""
import io
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import atexo_downloader as A


def main():
    # Prendre 1 marché PLACE en dce_contenu == "incomplet"
    marches = stockage.charger("marches")
    candidats = [
        (mid, m) for mid, m in marches.items()
        if "marches-publics.gouv.fr" in (m.get("url_dce") or "")
        and m.get("dce_contenu") == "incomplet"
    ]

    if not candidats:
        print("Aucun marche PLACE en dce_contenu=incomplet trouve.")
        # Plan B : tenter sur n'importe quel marche PLACE
        candidats = [
            (mid, m) for mid, m in marches.items()
            if "marches-publics.gouv.fr" in (m.get("url_dce") or "")
        ]
        if not candidats:
            print("Aucun marche PLACE non plus.")
            sys.exit(1)
        print(f"Bascule sur 1 marche PLACE quelconque ({len(candidats)} dispo).")

    mid, marche = candidats[0]
    print(f"\n=== TEST PLACE : {mid} ===")
    print(f"URL DCE : {marche.get('url_dce')}")
    print(f"dce_contenu actuel : {marche.get('dce_contenu')}")
    print(f"dce_pieces_contractuelles actuelles : "
          f"{marche.get('dce_pieces_contractuelles')}")
    print()
    print("Tentative de telechargement complet via atexo_downloader...")
    print("-" * 60)

    result = A.telecharger_dce_pour_marche(marche, "data/dce", verbose=True)

    print("-" * 60)
    print("\n=== RESULTAT ===")
    for cle, val in result.items():
        print(f"  {cle} : {val}")

    if result.get("ok"):
        print("\n>>> SUCCES : le ZIP est telecharge. Verifie son contenu :")
        chemin = result.get("chemin")
        if chemin:
            import zipfile
            try:
                with zipfile.ZipFile(chemin) as z:
                    noms = z.namelist()
                    print(f"    Contenu du ZIP ({len(noms)} fichiers) :")
                    for n in noms[:20]:
                        print(f"      - {n}")
                    if len(noms) > 20:
                        print(f"      ... +{len(noms) - 20} autres")
            except Exception as e:
                print(f"    ZIP non lisible : {e}")
    else:
        print("\n>>> ECHEC : voir l'erreur ci-dessus.")
        print("    Si erreur = 'Page inattendue' -> adapter atexo_downloader")
        print("      pour faire un saut intermediaire vers ")
        print("      EntrepriseDemandeTelechargementDce.")
        print("    Si erreur = 'Radio choixAnonyme introuvable' -> HTML PLACE")
        print("      a evolue, a inspecter manuellement.")


if __name__ == "__main__":
    main()
