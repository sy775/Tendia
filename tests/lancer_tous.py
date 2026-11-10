# -*- coding: utf-8 -*-
"""
tests/lancer_tous.py
--------------------
Lance chaque tests/test_*.py dans un sous-processus, depuis la racine du dépôt,
et affiche OK/KO par fichier (avec le nombre de ✓ et de ✗ relevés dans la sortie).

Un fichier est KO si son code de sortie est non nul ou s'il affiche au moins un ✗.
Code de sortie : 0 si tout est OK, 1 sinon.

Lancement : python tests/lancer_tous.py [--verbeux]
"""
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DOSSIER_TESTS = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(DOSSIER_TESTS)
DELAI_MAX_S = 600


def lancer(chemin):
    """Exécute un fichier de test ; retourne (code, nb_ok, nb_ko, sortie, durée)."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    debut = time.time()
    try:
        r = subprocess.run([sys.executable, chemin], cwd=RACINE, env=env,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=DELAI_MAX_S)
        code, sortie = r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        code, sortie = -1, f"délai dépassé ({DELAI_MAX_S} s)"
    return code, sortie.count("✓"), sortie.count("✗"), sortie, time.time() - debut


def main():
    verbeux = "--verbeux" in sys.argv
    fichiers = sorted(f for f in os.listdir(DOSSIER_TESTS)
                      if f.startswith("test_") and f.endswith(".py"))
    echecs = []
    for nom in fichiers:
        code, nb_ok, nb_ko, sortie, duree = lancer(os.path.join(DOSSIER_TESTS, nom))
        ok = code == 0 and nb_ko == 0
        print(f"  {'OK' if ok else 'KO'}  {nom:<40} ✓ {nb_ok:>3}  ✗ {nb_ko:>3}  "
              f"code {code:>2}  {duree:5.1f} s")
        if not ok:
            echecs.append(nom)
            if verbeux:
                print("\n".join("      " + l for l in sortie.strip().splitlines()[-15:]))
    print()
    print(f"RÉSULTAT : {len(fichiers) - len(echecs)}/{len(fichiers)} fichiers OK")
    for nom in echecs:
        print(f"  KO : {nom}")
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
