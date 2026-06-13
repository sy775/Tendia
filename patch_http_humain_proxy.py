"""
patch_http_humain_proxy.py
--------------------------
Patch : ajouter le support proxy via variable d'environnement TENDIA_PROXY_URL
dans creer_session_humaine() de http_humain.py.

Si TENDIA_PROXY_URL est définie dans l'environnement (ou .env), toutes les
sessions sortent par ce proxy. Sinon, comportement actuel (IP locale).

Permet de basculer en proxy résidentiel sans refactor de code, juste en
définissant TENDIA_PROXY_URL=http://USER:PASS@gate.smartproxy.com:7000

Idempotent : ne fait rien si déjà patché.
"""
import os
import sys
import shutil
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CIBLE = "http_humain.py"


def main():
    if not os.path.isfile(CIBLE):
        print(f"ERREUR : {CIBLE} introuvable.")
        sys.exit(1)

    with open(CIBLE, "r", encoding="utf-8") as f:
        src = f.read()

    if "# PATCH proxy_env" in src:
        print("Le patch est déjà appliqué.")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    backup = f"{CIBLE}.bak_avant_proxy_{stamp}"
    shutil.copy(CIBLE, backup)
    print(f"Backup : {backup}")

    # Trouver la fonction creer_session_humaine et lui ajouter le proxy
    # On cherche le return final de la fonction
    ancien = '''def creer_session_humaine(ua_fixe: Optional[str] = None) -> requests.Session:'''

    nouveau = '''def creer_session_humaine(ua_fixe: Optional[str] = None,
                            proxy_url: Optional[str] = None) -> requests.Session:'''

    if ancien not in src:
        # Variante sans annotation de type retour
        ancien2 = '''def creer_session_humaine(ua_fixe=None):'''
        nouveau2 = '''def creer_session_humaine(ua_fixe=None, proxy_url=None):'''
        if ancien2 in src:
            src = src.replace(ancien2, nouveau2, 1)
            print("Patch signature OK (variante sans annotations)")
        else:
            print("ERREUR : signature creer_session_humaine non trouvee. Patch manuel.")
            sys.exit(1)
    else:
        src = src.replace(ancien, nouveau, 1)
        print("Patch signature OK")

    # Ajouter le bloc proxy avant le return session
    # On cherche le motif "return session" et on insère juste avant
    ancien_return = '''    return session'''
    nouveau_return = '''    # PATCH proxy_env : si TENDIA_PROXY_URL est definie dans l'environnement,
    # toutes les sessions sortent par ce proxy (proxy residentiel anti-ban).
    if proxy_url is None:
        proxy_url = os.environ.get("TENDIA_PROXY_URL")
    if proxy_url:
        session.proxies = {"http": proxy_url, "https": proxy_url}
    return session'''

    if ancien_return not in src:
        print("ERREUR : 'return session' non trouve dans la fonction. Patch manuel.")
        sys.exit(1)

    # Assurer l'import os si pas déjà fait
    if "import os" not in src:
        # Ajouter après les autres imports
        src = src.replace("import random", "import os\nimport random", 1)

    src = src.replace(ancien_return, nouveau_return, 1)

    with open(CIBLE, "w", encoding="utf-8") as f:
        f.write(src)

    print(f"Patch applique a {CIBLE}.")
    print()
    print("Utilisation :")
    print("  1. Sans proxy (defaut) : comportement actuel, IP locale")
    print("  2. Avec proxy : definir TENDIA_PROXY_URL dans .env")
    print("     TENDIA_PROXY_URL=http://USER:PASS@gate.smartproxy.com:7000")
    print()
    print("Test rapide :")
    print('  python -c "import http_humain; '
          's=http_humain.creer_session_humaine(); print(\\"proxies:\\", s.proxies)"')


if __name__ == "__main__":
    main()
