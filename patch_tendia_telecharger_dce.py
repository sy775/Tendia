"""
patch_tendia_telecharger_dce.py
-------------------------------
Patch automatique pour ajouter ParseurAchatpublic à tendia_telecharger_dce.py
et la branche ZIP_GLOBAL_ACHATPUBLIC dans telecharger_pieces_dce.

Lance : python patch_tendia_telecharger_dce.py

Idempotent : ne fait rien si le patch est déjà appliqué.
"""
import io
import os
import re
import sys
import shutil
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CIBLE = "tendia_telecharger_dce.py"


def main():
    if not os.path.isfile(CIBLE):
        print(f"ERREUR : {CIBLE} introuvable. Lance depuis la racine Tendia.")
        sys.exit(1)

    with open(CIBLE, "r", encoding="utf-8") as f:
        src = f.read()

    # 1) Vérifier l'état du patch
    if "ParseurAchatpublic" in src and "ZIP_GLOBAL_ACHATPUBLIC" in src:
        print("Le patch est déjà appliqué. Rien à faire.")
        return

    # 2) Backup
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    backup = f"{CIBLE}.bak_avant_achatpublic_{stamp}"
    shutil.copy(CIBLE, backup)
    print(f"Backup : {backup}")

    # 3) Insérer ParseurAchatpublic juste avant la ligne PARSEURS = [...]
    parseur_class = '''
class ParseurAchatpublic(ParseurDCE):
    """
    achatpublic.com — workflow anonyme conforme arrêté 14/12/2009.
    N'utilise PAS le parsing HTML : délègue à achatpublic_downloader qui fait
    le GET page détail + POST telechargerDCE.action pour récupérer le ZIP DCE,
    puis décompresse le ZIP imbriqué automatiquement.
    """
    PATTERNS_HOSTS = ["achatpublic.com"]

    def lister_pieces(self, session, url_dce):
        return [{"nom": "DCE_complet.zip", "url": url_dce,
                 "type_detecte": "ZIP_GLOBAL_ACHATPUBLIC",
                 "taille_estimee": None}]


'''

    # Trouver la définition de PARSEURS
    m = re.search(r"^PARSEURS\s*=\s*\[", src, re.MULTILINE)
    if not m:
        print("ERREUR : ligne 'PARSEURS = [' introuvable.")
        sys.exit(1)

    # Insérer la classe avant
    src_avec_classe = src[:m.start()] + parseur_class + src[m.start():]

    # 4) Ajouter ParseurAchatpublic dans la liste PARSEURS
    # On cherche la liste actuelle et on ajoute ParseurAchatpublic dedans
    # Format typique : PARSEURS = [ParseurAtexo, ParseurEMarchesPublics]
    src_avec_liste = re.sub(
        r"PARSEURS\s*=\s*\[\s*ParseurAtexo\s*,\s*(ParseurEMarchesPublics)",
        r"PARSEURS = [ParseurAtexo, ParseurAchatpublic, \1",
        src_avec_classe,
        count=1,
    )
    if src_avec_liste == src_avec_classe:
        # Pattern différent — fallback générique
        src_avec_liste = re.sub(
            r"PARSEURS\s*=\s*\[\s*ParseurAtexo\s*,",
            r"PARSEURS = [ParseurAtexo, ParseurAchatpublic,",
            src_avec_classe,
            count=1,
        )

    if src_avec_liste == src_avec_classe:
        print("AVERTISSEMENT : la liste PARSEURS n'a pas pu être adaptée "
              "automatiquement. Ajoute ParseurAchatpublic à la main dans PARSEURS.")

    # 5) Ajouter la branche ZIP_GLOBAL_ACHATPUBLIC dans telecharger_pieces_dce
    # On la place juste après la branche ZIP_GLOBAL_ATEXO existante
    branche_achat = '''
    # Cas Achatpublic : marqueur ZIP_GLOBAL_ACHATPUBLIC -> workflow GET+POST
    # achatpublic_downloader (téléchargement direct du ZIP + décompression
    # automatique du ZIP imbriqué).
    if pieces and pieces[0].get("type_detecte") == "ZIP_GLOBAL_ACHATPUBLIC":
        import achatpublic_downloader as _ap
        res = _ap.telecharger_dce_pour_marche(marche, os.path.dirname(dossier_destination)
                                                if os.path.basename(dossier_destination)
                                                else dossier_destination,
                                                verbose=False)
        # _ap retourne {chemin: data/dce/<id>/dce_<pcslid>.zip}
        if res.get("ok"):
            recuperees = [{"nom": os.path.basename(res.get("chemin") or "dce.zip"),
                           "type": "ZIP_GLOBAL",
                           "taille": res.get("taille_octets", 0),
                           "chemin": res.get("chemin")}]
            manquantes = []
        else:
            recuperees = []
            manquantes = [{"nom": "DCE_complet.zip", "url": url_dce,
                           "type_detecte": "ZIP_GLOBAL_ACHATPUBLIC",
                           "raison_echec": res.get("erreur", "?")}]
        return {"pieces_recuperees": recuperees, "pieces_manquantes": manquantes,
                "duree_secondes": res.get("duree_secondes", 0.0),
                "session_cookies": {}}

'''

    # Cherche la branche existante ZIP_GLOBAL_ATEXO et insère la branche
    # achatpublic juste après
    m_atexo = re.search(
        r'(if pieces and pieces\[0\]\.get\("type_detecte"\) == "ZIP_GLOBAL_ATEXO":.*?session_cookies": \{\}\})\n',
        src_avec_liste,
        re.DOTALL,
    )
    if m_atexo:
        # Insérer juste après le bloc Atexo
        src_final = (src_avec_liste[:m_atexo.end()]
                     + branche_achat
                     + src_avec_liste[m_atexo.end():])
    else:
        print("AVERTISSEMENT : branche ZIP_GLOBAL_ATEXO introuvable. "
              "La branche Achatpublic n'a pas été insérée automatiquement.")
        src_final = src_avec_liste

    # 6) Écrire le fichier patché
    with open(CIBLE, "w", encoding="utf-8") as f:
        f.write(src_final)

    print(f"Patch appliqué à {CIBLE}.")
    print()
    print("Vérifications recommandées :")
    print("  1. python -c \"import tendia_telecharger_dce as T; print('PARSEURS:', T.PARSEURS)\"")
    print("  2. Le serveur Flask doit être redémarré pour prendre en compte")


if __name__ == "__main__":
    main()
