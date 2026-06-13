"""
retelecharger_vide_atexo.py
---------------------------
Re-télécharge les marchés `dce_contenu == "vide"` qui ont une signature
Atexo dans leur URL (orgAcronyme + Entreprise). Ce sont des marchés
identifiés comme dette cachée par diagnostic_vide.py — le téléchargeur
historique avait échoué (ou récupéré que des fichiers admin), mais
atexo_downloader devrait pouvoir les chopper.

Backup du dossier DCE avant écrasement. Idempotent (relançable).
Rate-limit 2 s entre marchés.

Usage : python retelecharger_vide_atexo.py
"""
import io
import sys
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import tendia_dce
import atexo_downloader as A

REPERTOIRE_DCE = Path("data/dce")
RATE_LIMIT_SEC = 2


def main():
    marches = stockage.charger("marches") or {}
    cibles = []
    for mid, m in marches.items():
        if m.get("dce_contenu") != "vide":
            continue
        url = (m.get("url_dce") or "").lower()
        # Signature Atexo (cohérent avec atexo_downloader._detecter_url_base)
        if "orgacronyme=" in url and "entreprise." in url:
            # Vérifier que le downloader le reconnaît bien
            if A._detecter_url_base(m.get("url_dce")) is not None:
                cibles.append((mid, m))

    print(f"=== RE-TÉLÉCHARGEMENT VIDE ATEXO (dette cachée) ===")
    print(f"Cibles : {len(cibles)} marchés vide avec signature Atexo")
    print()

    if not cibles:
        print("Aucune cible. Rien à faire.")
        return

    bilan = {"vide_to_complet": 0, "vide_to_incomplet": 0,
             "vide_to_vide": 0, "vide_to_erreur": 0, "vide_to_auth": 0}
    gains_pieces = []

    for i, (mid, marche) in enumerate(cibles, 1):
        dossier = REPERTOIRE_DCE / mid
        ancien_contenu = marche.get("dce_contenu")
        ancien_pieces = marche.get("dce_pieces_contractuelles") or []

        # Backup du dossier actuel
        if dossier.exists():
            bak = REPERTOIRE_DCE / f"{mid}.bak_avant_vide_atexo"
            if bak.exists():
                shutil.rmtree(bak)
            shutil.copytree(dossier, bak)

        # Re-téléchargement Atexo
        try:
            res = A.telecharger_dce_pour_marche(marche, str(REPERTOIRE_DCE),
                                                 verbose=False)
        except Exception as e:
            res = {"ok": False, "erreur": f"{type(e).__name__}: {e}"}

        if res.get("ok"):
            # Re-qualifier
            qual = tendia_dce.qualifier_dce(str(dossier))
            nouveau_contenu = qual["qualite"]
            nouvelles_pieces = qual["pieces_contractuelles"]
            marche["dce_contenu"] = nouveau_contenu
            marche["dce_pieces_contractuelles"] = nouvelles_pieces
            marche["dce_raison_contenu"] = qual["raison"]
            marche["dce_telecharge_le"] = datetime.now().isoformat()
            marche["dce_pieces_manquantes"] = []

            cle = f"vide_to_{nouveau_contenu}"
            bilan[cle] = bilan.get(cle, 0) + 1
            if nouveau_contenu == "complet":
                gains_pieces.append((mid, ancien_pieces, nouvelles_pieces))
        else:
            bilan["vide_to_erreur"] += 1
            marche["dce_telecharge_le"] = datetime.now().isoformat()
            marche["dce_raison_contenu"] = f"echec atexo: {res.get('erreur', '?')}"

        stockage.ecrire("marches", mid, marche)

        print(f"  [{i}/{len(cibles)}] {mid} : "
              f"{ancien_contenu} → {marche['dce_contenu']}")

        if i < len(cibles):
            time.sleep(RATE_LIMIT_SEC)

    # Bilan
    print()
    print("=" * 60)
    print("BILAN")
    print("=" * 60)
    for cle, n in bilan.items():
        if n > 0:
            print(f"  {cle}: {n}")

    if gains_pieces:
        print()
        print(f"Marchés passés à complet ({len(gains_pieces)}) :")
        for mid, ancien, nouveau in gains_pieces:
            print(f"  {mid} : {ancien} → {nouveau}")

    print()
    nb_complet = bilan.get("vide_to_complet", 0)
    nb_incomplet = bilan.get("vide_to_incomplet", 0)
    if nb_complet > 0:
        print(f"⇒ {nb_complet} marchés gagnés en complet")
        print("⇒ ces briefs sont à re-extraire (script reextraire_briefs_complet.py)")


if __name__ == "__main__":
    main()
