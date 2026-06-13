"""
patch_aws_cfid_refresh.py
-------------------------
Patch : ColdFusion régénère CFID/CFTOKEN après le POST cnxAnonyme.
Le code AWS-Achat actuel continue d'utiliser les anciens tokens dans l'étape 7
(POST actDCE2), ce qui cause "Reconnexion nécessaire" sur la page actDCE2.

Fix : après extraction du Location header de l'étape 5 (302 cnxAnonyme),
extraire les nouveaux CFID/CFTOKEN et les utiliser pour toutes les étapes
suivantes (6 et 7).

Idempotent : ne fait rien si déjà patché.
"""
import io
import os
import re
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

    # Check si patch deja applique
    if "# PATCH cfid_refresh" in src:
        print("Le patch est déjà appliqué. Rien à faire.")
        return

    # Backup
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    backup = f"{CIBLE}.bak_avant_cfid_refresh_{stamp}"
    shutil.copy(CIBLE, backup)
    print(f"Backup : {backup}")

    # Le patch : après la ligne `location_lots = r5.headers.get("Location") or ""`,
    # extraire les nouveaux CFID/CFTOKEN du Location et mettre à jour les variables.
    ancien = '''        if r5.status_code in (301, 302, 303, 307):
            location_lots = r5.headers.get("Location") or ""
            if verbose:
                print("        → 302 : captcha accepté")
            break'''

    nouveau = '''        if r5.status_code in (301, 302, 303, 307):
            location_lots = r5.headers.get("Location") or ""
            # PATCH cfid_refresh : ColdFusion régénère CFID/CFTOKEN après le
            # POST cnxAnonyme. Les anciens tokens deviennent invalides.
            # On extrait les nouveaux depuis le Location header et on les
            # propage aux étapes 6 et 7.
            _location_decode = html_lib.unescape(location_lots)
            _new_cfid = re.search(r"[?&]CFID=(\\d+)", _location_decode, re.IGNORECASE)
            _new_cftoken = re.search(r"[?&]CFTOKEN=([0-9a-fA-F\\-]+)",
                                      _location_decode, re.IGNORECASE)
            if _new_cfid and _new_cftoken:
                cfid = _new_cfid.group(1)
                cftoken = _new_cftoken.group(1)
                if verbose:
                    print(f"        → 302 captcha accepté (CFID régénéré : {cfid})")
            elif verbose:
                print("        → 302 captcha accepté")
            break'''

    if ancien not in src:
        print("ERREUR : bloc à patcher non trouvé. La structure du fichier a "
              "peut-être changé. Patch manuel nécessaire.")
        sys.exit(1)

    src = src.replace(ancien, nouveau, 1)

    # Écrire le fichier patché
    with open(CIBLE, "w", encoding="utf-8") as f:
        f.write(src)

    print(f"Patch appliqué à {CIBLE}.")
    print()
    print("Vérification :")
    print("  python -c \"import aws_downloader; print('OK')\"")


if __name__ == "__main__":
    main()
