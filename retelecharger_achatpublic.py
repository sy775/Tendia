"""
retelecharger_achatpublic.py
----------------------------
Re-télécharge les marchés achatpublic.com (typiquement classés `auth_requise`
ou `vide` avant l'ajout du downloader anonyme).

Utilise achatpublic_downloader.telecharger_dce_pour_marche qui inclut la
décompression automatique du ZIP imbriqué.

Backup du dossier DCE avant écrasement. Idempotent (skip si déjà décompressé).
Rate-limit 2 s entre marchés.

Usage : python retelecharger_achatpublic.py
"""
import io
import os
import sys
import shutil
import time
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import tendia_dce
import http_humain
import achatpublic_downloader as A

REPERTOIRE_DCE = Path("data/dce")
# Rate-limit randomisé (anti-ban léger). achatpublic n'a jamais montré de ban,
# on reste peu agressif : ~15 s en moyenne, pas de pause cumulative.
RATE_LIMIT_MOYEN_SEC = 15
RATE_LIMIT_MIN_SEC = 8
RATE_LIMIT_MAX_SEC = 30


def main():
    marches = stockage.charger("marches") or {}
    cibles = [
        (mid, m) for mid, m in marches.items()
        if "achatpublic.com" in (m.get("url_dce") or "")
    ]

    print(f"=== RE-TÉLÉCHARGEMENT ACHATPUBLIC ===")
    print(f"Cibles : {len(cibles)} marchés achatpublic")
    print()

    if not cibles:
        print("Aucune cible. Rien à faire.")
        return

    # Compteurs
    bilan = {}
    gains = []
    erreurs = []

    for i, (mid, marche) in enumerate(cibles, 1):
        dossier = REPERTOIRE_DCE / mid
        ancien_contenu = marche.get("dce_contenu") or "?"
        ancien_pieces = marche.get("dce_pieces_contractuelles") or []

        # Backup du dossier actuel (uniquement si non vide et pas déjà fait)
        if dossier.exists() and any(dossier.iterdir()):
            bak = REPERTOIRE_DCE / f"{mid}.bak_avant_achatpublic"
            if not bak.exists():
                try:
                    shutil.copytree(dossier, bak)
                except Exception:
                    pass

        # Téléchargement
        try:
            res = A.telecharger_dce_pour_marche(marche, str(REPERTOIRE_DCE),
                                                 verbose=False)
        except Exception as e:
            res = {"ok": False, "erreur": f"{type(e).__name__}: {e}"}

        if res.get("ok"):
            # Re-qualifier le dossier
            qual = tendia_dce.qualifier_dce(str(dossier))
            nouveau_contenu = qual["qualite"]
            nouvelles_pieces = qual["pieces_contractuelles"]
            marche["dce_contenu"] = nouveau_contenu
            marche["dce_pieces_contractuelles"] = nouvelles_pieces
            marche["dce_raison_contenu"] = qual["raison"]
            marche["dce_telecharge_le"] = datetime.now().isoformat()
            marche["dce_pieces_manquantes"] = []

            cle = f"{ancien_contenu}_to_{nouveau_contenu}"
            bilan[cle] = bilan.get(cle, 0) + 1
            if nouveau_contenu == "complet":
                gains.append((mid, ancien_pieces, nouvelles_pieces))
        else:
            err = res.get("erreur", "?")
            bilan[f"{ancien_contenu}_to_erreur"] = bilan.get(
                f"{ancien_contenu}_to_erreur", 0) + 1
            erreurs.append((mid, err))
            marche["dce_telecharge_le"] = datetime.now().isoformat()
            marche["dce_raison_contenu"] = f"echec achatpublic: {err}"

        stockage.ecrire("marches", mid, marche)

        skip_label = " [skip]" if res.get("skip") else ""
        print(f"  [{i}/{len(cibles)}] {mid} : "
              f"{ancien_contenu} → {marche.get('dce_contenu')}{skip_label}")

        if i < len(cibles):
            http_humain.attendre_humain(
                RATE_LIMIT_MIN_SEC, RATE_LIMIT_MAX_SEC,
                mu=RATE_LIMIT_MOYEN_SEC, sigma=5, verbose=True)

    # Bilan
    print()
    print("=" * 60)
    print("BILAN")
    print("=" * 60)
    for cle, n in sorted(bilan.items(), key=lambda x: -x[1]):
        print(f"  {cle}: {n}")

    if gains:
        print()
        print(f"Marchés passés à complet ({len(gains)}) :")
        for mid, ancien, nouveau in gains[:15]:
            print(f"  {mid} : {ancien} → {nouveau}")
        if len(gains) > 15:
            print(f"  ... +{len(gains) - 15} autres")

    if erreurs:
        print()
        print(f"Erreurs ({len(erreurs)}) :")
        for mid, err in erreurs[:10]:
            print(f"  {mid} : {err[:100]}")
        if len(erreurs) > 10:
            print(f"  ... +{len(erreurs) - 10} autres")

    nb_complet = sum(
        bilan.get(f"{x}_to_complet", 0)
        for x in ("auth_requise", "vide", "incomplet", "complet")
    )
    print()
    print(f"⇒ Total marchés en complet (issus de ce sprint) : {nb_complet}")
    if nb_complet > 0:
        print("⇒ Briefs à re-extraire : python reextraire_briefs_complet.py")


if __name__ == "__main__":
    main()
