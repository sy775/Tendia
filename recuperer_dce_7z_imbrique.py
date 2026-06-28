"""
recuperer_dce_7z_imbrique.py
----------------------------
Récupère les marchés `incomplet` dont le dossier contient un zip completeDownload
(atexo) renfermant un .7z imbriqué : extrait zip → .7z → pièces à plat, puis
re-qualifie. Corrige le cas où la chaîne s'arrêtait au RC faute d'extraction du
.7z imbriqué (py7zr requis).

Usage : python recuperer_dce_7z_imbrique.py
"""
import glob
import os
import sys
import zipfile
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import tendia_dce
import tendia_telecharger_dce as T


def _extraire_archives_a_plat(dossier: str, verbose=False) -> int:
    """Extrait récursivement zip + 7z + rar présents dans le dossier, à plat.
    Retourne le nombre de fichiers extraits."""
    extraits = 0
    change = True
    passes = 0
    while change and passes < 4:
        change = False
        passes += 1
        for arc in glob.glob(os.path.join(dossier, "*.zip")) + \
                   glob.glob(os.path.join(dossier, "*.7z")) + \
                   glob.glob(os.path.join(dossier, "*.rar")):
            try:
                if arc.lower().endswith(".zip"):
                    with zipfile.ZipFile(arc) as z:
                        z.extractall(dossier)
                elif arc.lower().endswith(".7z"):
                    import py7zr
                    with py7zr.SevenZipFile(arc) as a:
                        a.extractall(dossier)
                elif arc.lower().endswith(".rar"):
                    import rarfile
                    with rarfile.RarFile(arc) as r:
                        r.extractall(dossier)
                else:
                    continue
                os.remove(arc)  # archive consommée → évite la double détection
                extraits += 1
                change = True
            except Exception as e:
                if verbose:
                    print(f"      ⚠ extraction {os.path.basename(arc)} : {e}")
    return extraits


def main():
    m = stockage.charger("marches") or {}
    cibles = []
    for mid, mk in sorted(m.items()):
        if mk.get("dce_contenu") != "incomplet":
            continue
        dossier = os.path.join(str(T.REPERTOIRE_DCE), mid)
        if glob.glob(os.path.join(dossier, "*.zip")) or glob.glob(os.path.join(dossier, "*.7z")):
            cibles.append((mid, mk, dossier))

    print(f"=== Récupération .7z/.zip imbriqués — {len(cibles)} incomplets avec archive ===\n")
    if not cibles:
        print("Aucun incomplet avec archive à extraire.")
        return

    bilan = Counter()
    gains = []
    for i, (mid, mk, dossier) in enumerate(cibles, 1):
        avant = mk.get("dce_pieces_contractuelles") or []
        n = _extraire_archives_a_plat(dossier, verbose=True)
        qual = tendia_dce.qualifier_dce(dossier)
        nouveau = qual["qualite"]
        bilan[f"incomplet → {nouveau}"] += 1
        if nouveau == "complet":
            gains.append((mid, avant, qual["pieces_contractuelles"]))
        mk["dce_contenu"] = nouveau
        mk["dce_pieces_contractuelles"] = qual["pieces_contractuelles"]
        mk["dce_raison_contenu"] = qual["raison"]
        mk["dce_telecharge_le"] = datetime.now().isoformat()
        stockage.ecrire("marches", mid, mk)
        print(f"  [{i}/{len(cibles)}] {mid} : {n} archive(s) extraite(s) → {nouveau} "
              f"(pièces {qual['pieces_contractuelles']})")

    print("\nBilan :")
    for b, n in bilan.most_common():
        print(f"  {b:<26} : {n}")
    if gains:
        print(f"\nMarchés passés à complet ({len(gains)}) :")
        for mid, av, ap in gains:
            print(f"  {mid} : {av or ['RC']} → {ap}")
    print(f"\n⇒ {bilan.get('incomplet → complet', 0)} marchés récupérés en complet.")


if __name__ == "__main__":
    main()
