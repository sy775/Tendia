"""
patch_aws_lots_mono.py
----------------------
Patch : sur les marchés AWS-Achat mono-lot (sans checkboxes lots détectées),
il faut explicitement envoyer `lots=0` dans le POST actDCE2 (et non omettre
le champ comme le code actuel le fait).

Sinon AWS retourne "ANOMALIE RENCONTRÉE - OPÉRATION AVORTÉE [CODE: 12164096]".

URL qui marche en navigateur (validation manuelle sur IDM=1791723) :
  ?fuseaction=dce.actDCE2&IDM=1791723&lots=0&soumission=0&CFID=...&CFTOKEN=...

Idempotent : ne fait rien si déjà patché.
"""
import os
import sys
import shutil
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CIBLE = "aws_downloader.py"


def main():
    if not os.path.isfile(CIBLE):
        print(f"ERREUR : {CIBLE} introuvable.")
        sys.exit(1)

    with open(CIBLE, "r", encoding="utf-8") as f:
        src = f.read()

    if "# PATCH lots_mono" in src:
        print("Le patch est déjà appliqué. Rien à faire.")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    backup = f"{CIBLE}.bak_avant_lots_mono_{stamp}"
    shutil.copy(CIBLE, backup)
    print(f"Backup : {backup}")

    # Patch : si lots est vide, ajouter lots=0
    ancien = '''        # Body : IDM, Soumission, selectAll, puis lots=1&lots=2&... (clé répétée)
        champs = [("IDM", idm), ("Soumission", SOUMISSION_DEFAUT), ("selectAll", "")]
        for lot in lots:
            champs.append(("lots", lot))'''

    nouveau = '''        # PATCH lots_mono : Body avec lots=N par lot, OU lots=0 si mono-lot.
        # En mono-lot (verifLotsDCE n'a pas de checkboxes), AWS-Achat exige
        # explicitement `lots=0` dans le POST sinon retourne "ANOMALIE 12164096".
        champs = [("IDM", idm), ("Soumission", SOUMISSION_DEFAUT), ("selectAll", "")]
        if lots:
            for lot in lots:
                champs.append(("lots", lot))
        else:
            champs.append(("lots", "0"))  # mono-lot'''

    if ancien not in src:
        print("ERREUR : bloc à patcher non trouvé. Patch manuel nécessaire.")
        print()
        print("Cherche dans aws_downloader.py la ligne :")
        print('    champs = [("IDM", idm), ("Soumission", SOUMISSION_DEFAUT), ("selectAll", "")]')
        print()
        print("Et après la boucle 'for lot in lots:', ajoute :")
        print('        else:')
        print('            champs.append(("lots", "0"))  # mono-lot')
        sys.exit(1)

    src = src.replace(ancien, nouveau, 1)

    with open(CIBLE, "w", encoding="utf-8") as f:
        f.write(src)

    print(f"Patch appliqué à {CIBLE}.")
    print()
    print("Vérification syntaxe :")
    print("  python -c \"import aws_downloader; print('import OK')\"")
    print()
    print("Test :")
    print("  python test_aws_achat.py")


if __name__ == "__main__":
    main()
