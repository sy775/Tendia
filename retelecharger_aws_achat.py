"""
retelecharger_aws_achat.py
--------------------------
Re-télécharge les marchés www.marches-publics.info (AWS-Achat), typiquement
classés `auth_requise` avant l'ajout du downloader anonyme aws_downloader.

Workflow ColdFusion 7 étapes + résolution captcha via 2captcha
(clé lue depuis .env / TWOCAPTCHA_API_KEY). Coût ~0,001 €/marché.

- Backup du dossier DCE existant sous <id>.bak_avant_aws_achat.
- Idempotent : skip si fichiers déjà présents.
- Rate-limit 3 s entre marchés (charge AWS plus longue qu'Atexo).
- Arrêt propre si le solde 2captcha est épuisé (ERROR_ZERO_BALANCE).
- Met à jour dce_contenu, dce_pieces_contractuelles, dce_raison_contenu,
  dce_telecharge_le, dce_pieces_manquantes.

Usage : python retelecharger_aws_achat.py [--oui] [--limite N]
"""
import argparse
import os
import sys
import shutil
import time
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import tendia_dce
import aws_downloader as A

REPERTOIRE_DCE = Path("data/dce")
RATE_LIMIT_SEC = 3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--oui", action="store_true", help="Pas de confirmation interactive.")
    ap.add_argument("--limite", type=int, default=None, help="Max de marchés à traiter.")
    args = ap.parse_args()

    api_key = os.environ.get("TWOCAPTCHA_API_KEY")
    if not api_key:
        print("❌ TWOCAPTCHA_API_KEY absente du .env. Abandon.")
        sys.exit(1)

    marches = stockage.charger("marches") or {}
    cibles = [
        (mid, m) for mid, m in sorted(marches.items())
        if "marches-publics.info" in (m.get("url_dce") or "")
    ]
    if args.limite:
        cibles = cibles[:args.limite]

    print("=== RE-TÉLÉCHARGEMENT AWS-ACHAT (www.marches-publics.info) ===")
    print(f"Cibles : {len(cibles)} marchés")
    cout = len(cibles) * 0.001
    print(f"Coût 2captcha estimé : ~{cout:.3f} € (1 captcha/marché)")
    print()

    if not cibles:
        print("Aucune cible. Rien à faire.")
        return

    if not args.oui:
        try:
            input("Appuie sur Entrée pour lancer (Ctrl+C pour annuler)... ")
        except (EOFError, KeyboardInterrupt):
            print("\nAnnulé.")
            return

    bilan = {}
    gains = []
    erreurs = []
    solde_epuise = False

    for i, (mid, marche) in enumerate(cibles, 1):
        dossier = REPERTOIRE_DCE / mid
        ancien_contenu = marche.get("dce_contenu") or "?"
        ancien_pieces = marche.get("dce_pieces_contractuelles") or []

        # Backup du dossier actuel (si non vide et pas déjà sauvegardé)
        if dossier.exists() and any(dossier.iterdir()):
            bak = REPERTOIRE_DCE / f"{mid}.bak_avant_aws_achat"
            if not bak.exists():
                try:
                    shutil.copytree(dossier, bak)
                except Exception:
                    pass

        # Téléchargement
        try:
            res = A.telecharger_dce_pour_marche(
                marche, str(REPERTOIRE_DCE),
                api_key_2captcha=api_key, verbose=False)
        except Exception as e:
            res = {"ok": False, "erreur": f"{type(e).__name__}: {e}"}

        if res.get("solde_2captcha_epuise"):
            print(f"  [{i}/{len(cibles)}] {mid} : ❌ SOLDE 2CAPTCHA ÉPUISÉ")
            solde_epuise = True
            erreurs.append((mid, "solde 2captcha épuisé"))
            break

        if res.get("ok"):
            qual = tendia_dce.qualifier_dce(str(dossier))
            nouveau_contenu = qual["qualite"]
            marche["dce_contenu"] = nouveau_contenu
            marche["dce_pieces_contractuelles"] = qual["pieces_contractuelles"]
            marche["dce_raison_contenu"] = qual["raison"]
            marche["dce_telecharge_le"] = datetime.now().isoformat()
            marche["dce_pieces_manquantes"] = []

            cle = f"{ancien_contenu}_to_{nouveau_contenu}"
            bilan[cle] = bilan.get(cle, 0) + 1
            if nouveau_contenu == "complet":
                gains.append((mid, ancien_pieces, qual["pieces_contractuelles"]))
        else:
            err = res.get("erreur", "?")
            etape = res.get("etape_erreur", "?")
            cle = f"{ancien_contenu}_to_erreur"
            bilan[cle] = bilan.get(cle, 0) + 1
            erreurs.append((mid, f"[{etape}] {err}"))
            marche["dce_telecharge_le"] = datetime.now().isoformat()
            marche["dce_raison_contenu"] = f"echec aws-achat [{etape}]: {err}"

        stockage.ecrire("marches", mid, marche)

        skip_label = " [skip]" if res.get("skip") else ""
        print(f"  [{i}/{len(cibles)}] {mid} : "
              f"{ancien_contenu} → {marche.get('dce_contenu')}{skip_label}")

        if i < len(cibles):
            time.sleep(RATE_LIMIT_SEC)

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
        for mid, err in erreurs[:12]:
            print(f"  {mid} : {err[:100]}")
        if len(erreurs) > 12:
            print(f"  ... +{len(erreurs) - 12} autres")

    if solde_epuise:
        print()
        print("⚠ Batch interrompu : solde 2captcha épuisé. Recharge puis relance "
              "(les marchés déjà OK seront skippés).")

    nb_complet = sum(
        bilan.get(f"{x}_to_complet", 0)
        for x in ("auth_requise", "vide", "incomplet", "complet", "erreur", "?")
    )
    print()
    print(f"⇒ Total marchés passés à complet : {nb_complet}")
    if nb_complet > 0:
        print("⇒ Briefs à re-extraire : python reextraire_briefs_complet.py")


if __name__ == "__main__":
    main()
