"""
patch_aws_unescape.py
---------------------
Patch ciblé : décoder les entités HTML (&amp;) dans les URLs avant parsing
de l'IDM dans aws_downloader.py.

Bug observé : 41/81 URLs AWS-Achat de la base contiennent `&amp;` au lieu
de `&` (bug d'ingestion BOAMP qui ne décode pas le HTML). La regex
`_extraire_idm_depuis_url` cherche `&IDM=` qui ne matche pas `amp;IDM=`.

Idempotent : ne fait rien si déjà patché.
"""
import io
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

    # Check si patch deja applique
    if "html_lib.unescape(url)" in src or "import html as html_lib" in src:
        print("Le patch est deja applique. Rien a faire.")
        return

    # Backup
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    backup = f"{CIBLE}.bak_avant_unescape_{stamp}"
    shutil.copy(CIBLE, backup)
    print(f"Backup : {backup}")

    # Patch 1 : ajouter import html_lib en haut du fichier
    # Cherche le bloc d'imports standards et insere apres
    ancien_imports = """import os
import re"""
    nouveau_imports = """import html as html_lib
import os
import re"""
    if ancien_imports in src:
        src = src.replace(ancien_imports, nouveau_imports, 1)
        print("Patch 1/2 OK : import html as html_lib ajoute")
    else:
        print("AVERT : bloc imports non trouve, patch 1 non applique.")
        print("Ajoute manuellement 'import html as html_lib' en haut.")

    # Patch 2 : decoder l'URL dans _extraire_idm_depuis_url
    ancien_fct = '''def _extraire_idm_depuis_url(url: str) -> Optional[str]:
    """Extrait l'IDM depuis n'importe quelle URL marches-publics.info."""
    if not url:
        return None
    try:
        qs = parse_qs(urlparse(url).query)'''

    nouveau_fct = '''def _extraire_idm_depuis_url(url: str) -> Optional[str]:
    """Extrait l'IDM depuis n'importe quelle URL marches-publics.info.

    Decode au prealable les entites HTML (&amp; -> &) car certaines URLs
    de la base contiennent &amp; au lieu de & (bug d'ingestion BOAMP qui
    ne fait pas d'html.unescape sur les URLs).
    """
    if not url:
        return None
    url = html_lib.unescape(url)  # &amp; -> &, &lt; -> <, etc.
    try:
        qs = parse_qs(urlparse(url).query)'''

    if ancien_fct in src:
        src = src.replace(ancien_fct, nouveau_fct, 1)
        print("Patch 2/2 OK : html_lib.unescape() ajoute dans _extraire_idm_depuis_url")
    else:
        print("ERREUR : fonction _extraire_idm_depuis_url non trouvee.")
        print("Edit manuel necessaire.")
        sys.exit(1)

    # Ecrire le fichier patche
    with open(CIBLE, "w", encoding="utf-8") as f:
        f.write(src)

    print()
    print(f"Patch applique a {CIBLE}.")
    print()
    print("Verification :")
    print("  python -c \"import aws_downloader as A; print('IDM:', "
          "A._extraire_idm_depuis_url("
          "'https://www.marches-publics.info/?fuseaction=x&amp;IDM=1791723'))\"")
    print("Attendu : IDM: 1791723")


if __name__ == "__main__":
    main()
