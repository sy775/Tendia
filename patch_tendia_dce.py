"""
patch_tendia_dce.py
-------------------
Patch automatique pour retirer 'achatpublic.com' de PLATEFORMES_AUTH_REQUISES
dans tendia_dce.py, maintenant qu'on a achatpublic_downloader.

Idempotent : ne fait rien si déjà retiré.
"""
import io
import os
import sys
import shutil
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CIBLE = "tendia_dce.py"


def main():
    if not os.path.isfile(CIBLE):
        print(f"ERREUR : {CIBLE} introuvable.")
        sys.exit(1)

    with open(CIBLE, "r", encoding="utf-8") as f:
        src = f.read()

    # Détecter la ligne "achatpublic.com" dans PLATEFORMES_AUTH_REQUISES
    if '"achatpublic.com"' not in src and "'achatpublic.com'" not in src:
        print("'achatpublic.com' n'est pas dans tendia_dce.py. Rien à faire.")
        return

    # Backup
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    backup = f"{CIBLE}.bak_avant_achatpublic_{stamp}"
    shutil.copy(CIBLE, backup)
    print(f"Backup : {backup}")

    # Retirer la ligne contenant 'achatpublic.com'
    lignes = src.splitlines(keepends=True)
    nouvelles = []
    retire = False
    for ligne in lignes:
        if '"achatpublic.com"' in ligne or "'achatpublic.com'" in ligne:
            # Vérifier qu'on est bien dans PLATEFORMES_AUTH_REQUISES
            # (heuristique : la ligne contient juste 'achatpublic.com' + virgule)
            ligne_trim = ligne.strip()
            if (ligne_trim.startswith('"achatpublic.com"') or
                ligne_trim.startswith("'achatpublic.com'")):
                if retire:
                    nouvelles.append(ligne)
                    continue
                retire = True
                print(f"  Ligne supprimée : {ligne.rstrip()}")
                continue
        nouvelles.append(ligne)

    if not retire:
        print("AVERTISSEMENT : achatpublic.com détecté mais pas dans le contexte attendu.")
        print("Patch manuel nécessaire.")
        return

    with open(CIBLE, "w", encoding="utf-8") as f:
        f.writelines(nouvelles)

    print(f"Patch appliqué à {CIBLE}.")
    print()
    print("Vérification :")
    print("  python -c \"import tendia_dce; print('PLATEFORMES_AUTH_REQUISES:',")
    print("    tendia_dce.PLATEFORMES_AUTH_REQUISES)\"")


if __name__ == "__main__":
    main()
