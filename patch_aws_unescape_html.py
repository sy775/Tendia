"""
patch_aws_unescape_html.py
--------------------------
Patch ciblé : décoder les entités HTML (&amp;) dans le HTML AVANT
d'appliquer les regex de parsing dans aws_downloader.py.

Bug observé : la page de session ColdFusion retourne du HTML contenant
des liens avec `&amp;CFID=...&amp;CFTOKEN=...`. La regex actuelle
`[?&]CFID=(\d+)` cherche `?CFID=` ou `&CFID=` mais pas `amp;CFID=`.

Fix : appeler html_lib.unescape(html) au début de chaque fonction de
parsing HTML : _extraire_cfid_cftoken_depuis_html, _extraire_ids_depuis_html,
_extraire_str_nom_image_et_hashval, _extraire_lots_depuis_verif_lots_dce,
_extraire_url_cdn_depuis_actdce2.

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

# Liste des fonctions à patcher : (nom, signature_recherche, ligne_a_inserer_apres)
FONCTIONS = [
    "_extraire_cfid_cftoken_depuis_html",
    "_extraire_ids_depuis_html",
    "_extraire_str_nom_image_et_hashval",
    "_extraire_lots_depuis_verif_lots_dce",
    "_extraire_url_cdn_depuis_actdce2",
]


def main():
    if not os.path.isfile(CIBLE):
        print(f"ERREUR : {CIBLE} introuvable.")
        sys.exit(1)

    with open(CIBLE, "r", encoding="utf-8") as f:
        src = f.read()

    # Compte les unescape deja presents pour idempotence
    nb_unescape_existants = src.count("html_lib.unescape(html)")
    if nb_unescape_existants >= len(FONCTIONS):
        print(f"Le patch est déjà appliqué ({nb_unescape_existants} unescape "
              f"trouvés). Rien à faire.")
        return

    # Backup
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    backup = f"{CIBLE}.bak_avant_unescape_html_{stamp}"
    shutil.copy(CIBLE, backup)
    print(f"Backup : {backup}")

    # Vérifier que html_lib est bien importé (devrait être déjà fait par le
    # patch précédent patch_aws_unescape.py)
    if "import html as html_lib" not in src:
        print("ERREUR : 'import html as html_lib' absent. Lance d'abord "
              "patch_aws_unescape.py.")
        sys.exit(1)

    # Patch : pour chaque fonction qui prend `html` en paramètre,
    # insérer `html = html_lib.unescape(html)` juste après le check
    # `if not html: return ...` (ou similaire).
    nb_patches = 0

    # Pattern générique : on cherche les définitions de fonctions qui prennent
    # un paramètre `html`. On insère le unescape après le premier check `if not html`.
    for nom_fct in FONCTIONS:
        # Trouve la fonction
        pattern_def = rf"(def {re.escape(nom_fct)}\([^)]*html[^)]*\)[^:]*:\s*\n"
        pattern_def += r"(?:\s*\"\"\"[\s\S]*?\"\"\"\s*\n)?"  # docstring optionnelle
        pattern_def += r"(\s+)if not html"
        pattern_def += r"[^\n]*?:\s*\n"  # if not html: ...
        pattern_def += r"\s+return[^\n]+\n)"

        m = re.search(pattern_def, src)
        if not m:
            print(f"  AVERT : pattern non trouvé pour {nom_fct} - skip")
            continue

        # Reconstruire avec l'ajout du unescape APRÈS le if not html
        bloc_existant = m.group(0)
        indent = m.group(2)
        bloc_patche = bloc_existant + f"{indent}html = html_lib.unescape(html)  # &amp; -> &\n"

        if "html_lib.unescape(html)" in bloc_existant:
            print(f"  {nom_fct} : déjà patchée, skip")
            continue

        src = src.replace(bloc_existant, bloc_patche, 1)
        nb_patches += 1
        print(f"  {nom_fct} : patché")

    if nb_patches == 0:
        print("AVERT : aucun patch appliqué. Vérifie la structure du fichier.")
        sys.exit(1)

    # Écrire le fichier patché
    with open(CIBLE, "w", encoding="utf-8") as f:
        f.write(src)

    print()
    print(f"Patch appliqué : {nb_patches} fonction(s) patchée(s) dans {CIBLE}.")
    print()
    print("Vérification rapide :")
    print('  python -c "import aws_downloader as A; '
          "cfid, cftoken = A._extraire_cfid_cftoken_depuis_html("
          "'<a href=\\\"x?CFID=123&amp;CFTOKEN=abc456\\\">test</a>'); "
          "print('CFID:', cfid, 'CFTOKEN:', cftoken)\"")
    print("Attendu : CFID: 123 CFTOKEN: abc456")


if __name__ == "__main__":
    main()
