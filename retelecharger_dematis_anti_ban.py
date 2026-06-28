"""
retelecharger_dematis_anti_ban.py
---------------------------------
Batch ANTI-BAN de retrait du DCE sur les plateformes Dematis
(`*.e-marchespublics.com`), sur le modèle de retelecharger_aws_achat_anti_ban.py.

Cible les marchés Dematis encore non-complet (incomplet / vide / erreur) :
  - délai gaussien ~60 s entre marchés ;
  - pause cumulative tous les 20 marchés ;
  - cap par run (défaut 30) ;
  - heures de bureau sauf --ignorer-heures ;
  - arrêt après 3 bans consécutifs ;
  - re-qualifie + persiste dce_contenu après chaque téléchargement.

Réseau requis → à lancer par Younes. Idempotent (skip les marchés déjà OK).

Usage : python retelecharger_dematis_anti_ban.py [--oui] [--max N] [--ignorer-heures]
"""
import argparse
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import tendia_dce
import http_humain
import dematis_downloader as D

REPERTOIRE_DCE = Path("data/dce")

RATE_LIMIT_MOYEN_SEC = 60
RATE_LIMIT_ECART_SEC = 25
RATE_LIMIT_MIN_SEC = 20
RATE_LIMIT_MAX_SEC = 150
PAUSE_TOUTES_LES_N = 20
MAX_MARCHES_PAR_RUN = 30
BANS_CONSECUTIFS_STOP = 3

COUT_2CAPTCHA_USD_PAR_CAPTCHA = 0.001


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--oui", action="store_true", help="Pas de confirmation.")
    ap.add_argument("--max", type=int, default=MAX_MARCHES_PAR_RUN,
                    help=f"Max de marchés ce run (défaut {MAX_MARCHES_PAR_RUN}).")
    ap.add_argument("--ignorer-heures", action="store_true",
                    help="Ignore la contrainte heures de bureau.")
    args = ap.parse_args()

    api_key = os.environ.get("TWOCAPTCHA_API_KEY")
    if not api_key:
        print("❌ TWOCAPTCHA_API_KEY absente du .env. Abandon.")
        sys.exit(1)

    if not args.ignorer_heures and not http_humain.heure_actuelle_est_bureau(verbose=True):
        print("Hors heures de bureau (8h-19h lun-ven). Arrêt (ou --ignorer-heures).")
        return

    marches = stockage.charger("marches") or {}

    def _annonce_telechargeable(url: str) -> bool:
        # L'anonyme Dematis ne sait traiter qu'une page annonce acheteur
        # (`<acheteur>.e-marchespublics.com/.../annonce_marche_public_...` ou un
        # lien anonyme direct). Les URLs de listing `www.e-marchespublics.com/
        # appel-offre/<id>` n'exposent pas de lien anonyme → on les écarte
        # (sinon faux « ban » sur la page d'accueil).
        low = (url or "").lower()
        return D.est_url_dematis(low) and (
            "annonce_marche_public" in low or "marche_public_anonyme" in low)

    tous_non_complet = [
        (mid, m) for mid, m in sorted(marches.items())
        if D.est_url_dematis(m.get("url_dce") or "")
        and m.get("dce_contenu") not in ("complet", "candidature")
    ]
    cibles = [(mid, m) for mid, m in tous_non_complet
              if _annonce_telechargeable(m.get("url_dce") or "")]
    non_telechargeables = len(tous_non_complet) - len(cibles)
    total_restant = len(cibles)
    if non_telechargeables:
        print(f"({non_telechargeables} marché(s) écarté(s) : URL listing "
              f"www/appel-offre non téléchargeable en anonyme)")
    cibles = cibles[:max(0, args.max)]

    print("=== RE-TÉLÉCHARGEMENT DEMATIS (ANTI-BAN) ===")
    print(f"Marchés Dematis non-complet restants : {total_restant}")
    print(f"Traités ce run (cap {args.max})       : {len(cibles)}")
    duree_est = len(cibles) * RATE_LIMIT_MOYEN_SEC / 60
    duree_est += (len(cibles) // PAUSE_TOUTES_LES_N) * 22
    print(f"Durée estimée                         : ~{duree_est:.0f} min")
    print(f"Coût 2captcha estimé                  : ~{len(cibles) * 0.001:.3f} €\n")

    if not cibles:
        print("Rien à faire ce run.")
        return
    if not args.oui:
        try:
            input("Entrée pour lancer (Ctrl+C pour annuler)... ")
        except (EOFError, KeyboardInterrupt):
            print("\nAnnulé.")
            return

    bilan, gains, erreurs = {}, [], []
    bans_consecutifs = traites = nb_captchas = 0
    solde_epuise = False
    retry_captcha = []   # échecs captcha (transitoires) à retenter après la boucle

    for i, (mid, marche) in enumerate(cibles, 1):
        if not args.ignorer_heures and not http_humain.heure_actuelle_est_bureau():
            print(f"\nHeures de bureau dépassées, arrêt après {i - 1} marchés (relance demain).")
            break

        dossier = REPERTOIRE_DCE / mid
        ancien_contenu = marche.get("dce_contenu") or "?"
        ancien_pieces = marche.get("dce_pieces_contractuelles") or []

        # Un marché non-complet a souvent déjà un dossier (RC seul d'un ancien
        # run) : on le sauvegarde puis on le VIDE, sinon le skip idempotent de
        # telecharger_dce_pour_marche court-circuite le re-téléchargement complet.
        if dossier.exists() and any(dossier.iterdir()):
            bak = REPERTOIRE_DCE / f"{mid}.bak_avant_dematis"
            if not bak.exists():
                try:
                    shutil.copytree(dossier, bak)
                except Exception:
                    pass
            try:
                shutil.rmtree(dossier)  # force le re-DL complet du DCE
            except Exception:
                pass

        try:
            res = D.telecharger_dce_pour_marche(marche, str(REPERTOIRE_DCE),
                                                api_key_2captcha=api_key, verbose=False)
        except Exception as e:
            res = {"ok": False, "erreur": f"{type(e).__name__}: {e}"}

        traites += 1
        nb_captchas += res.get("nb_captcha_resolus", 0) or 0

        if res.get("solde_2captcha_epuise"):
            print(f"  [{i}/{len(cibles)}] {mid} : ❌ SOLDE 2CAPTCHA ÉPUISÉ")
            solde_epuise = True
            erreurs.append((mid, "solde 2captcha épuisé"))
            break

        if res.get("etape_erreur") in ("ban_detecte", "ban_persistant"):
            bans_consecutifs += 1
            erreurs.append((mid, "ban détecté"))
            print(f"  [{i}/{len(cibles)}] {mid} : 🚫 BAN ({bans_consecutifs}/{BANS_CONSECUTIFS_STOP})")
            if bans_consecutifs >= BANS_CONSECUTIFS_STOP:
                print(f"\n🚫 {BANS_CONSECUTIFS_STOP} bans consécutifs : arrêt. Attends avant de relancer.")
                break
            if i < len(cibles):
                http_humain.attendre_humain(RATE_LIMIT_MIN_SEC, RATE_LIMIT_MAX_SEC,
                                            mu=RATE_LIMIT_MOYEN_SEC, sigma=RATE_LIMIT_ECART_SEC, verbose=True)
            continue
        bans_consecutifs = 0

        if res.get("ok"):
            qual = tendia_dce.qualifier_dce(str(dossier))
            nouveau = qual["qualite"]
            marche["dce_contenu"] = nouveau
            marche["dce_pieces_contractuelles"] = qual["pieces_contractuelles"]
            marche["dce_raison_contenu"] = qual["raison"]
            marche["dce_telecharge_le"] = datetime.now().isoformat()
            marche["dce_pieces_manquantes"] = []
            bilan[f"{ancien_contenu}_to_{nouveau}"] = bilan.get(f"{ancien_contenu}_to_{nouveau}", 0) + 1
            if nouveau == "complet":
                gains.append((mid, ancien_pieces, qual["pieces_contractuelles"]))
        else:
            etape = res.get("etape_erreur", "?")
            err = res.get("erreur", "?")
            bilan[f"{ancien_contenu}_to_erreur"] = bilan.get(f"{ancien_contenu}_to_erreur", 0) + 1
            erreurs.append((mid, f"[{etape}] {err}"))
            marche["dce_telecharge_le"] = datetime.now().isoformat()
            marche["dce_raison_contenu"] = f"echec dematis [{etape}]: {err}"
            if etape == "captcha":   # transitoire → on retentera après la boucle
                retry_captcha.append((mid, marche))

        stockage.ecrire("marches", mid, marche)
        skip = " [skip]" if res.get("skip") else ""
        print(f"  [{i}/{len(cibles)}] {mid} : {ancien_contenu} → {marche.get('dce_contenu')}{skip}")

        http_humain.attendre_pause_cumulative(i, seuil=PAUSE_TOUTES_LES_N, verbose=True)
        if i < len(cibles):
            http_humain.attendre_humain(RATE_LIMIT_MIN_SEC, RATE_LIMIT_MAX_SEC,
                                        mu=RATE_LIMIT_MOYEN_SEC, sigma=RATE_LIMIT_ECART_SEC, verbose=True)

    # --- Passes de retry des échecs CAPTCHA (transitoires : 2captcha se trompe).
    # Additive, après la boucle principale ; on s'abstient si ban/solde. ---
    passe = 0
    while (retry_captcha and passe < 2 and not solde_epuise
           and bans_consecutifs < BANS_CONSECUTIFS_STOP
           and (args.ignorer_heures or http_humain.heure_actuelle_est_bureau())):
        passe += 1
        print(f"\n--- Retry captcha (passe {passe}) : {len(retry_captcha)} marché(s) ---")
        encore = []
        for j, (mid, marche) in enumerate(retry_captcha, 1):
            dossier = REPERTOIRE_DCE / mid
            if dossier.exists():
                try:
                    shutil.rmtree(dossier)
                except Exception:
                    pass
            try:
                res = D.telecharger_dce_pour_marche(marche, str(REPERTOIRE_DCE),
                                                    api_key_2captcha=api_key, verbose=False)
            except Exception as e:
                res = {"ok": False, "erreur": str(e), "etape_erreur": "exception"}
            nb_captchas += res.get("nb_captcha_resolus", 0) or 0
            if res.get("solde_2captcha_epuise"):
                solde_epuise = True
                break
            if res.get("ok"):
                qual = tendia_dce.qualifier_dce(str(dossier))
                marche["dce_contenu"] = qual["qualite"]
                marche["dce_pieces_contractuelles"] = qual["pieces_contractuelles"]
                marche["dce_raison_contenu"] = qual["raison"]
                marche["dce_telecharge_le"] = datetime.now().isoformat()
                stockage.ecrire("marches", mid, marche)
                bilan[f"captcha_retry_to_{qual['qualite']}"] = \
                    bilan.get(f"captcha_retry_to_{qual['qualite']}", 0) + 1
                if qual["qualite"] == "complet":
                    gains.append((mid, [], qual["pieces_contractuelles"]))
                print(f"  ✓ {mid} → {qual['qualite']}")
            elif res.get("etape_erreur") == "captcha":
                encore.append((mid, marche))
                print(f"  ⚠ {mid} : captcha encore raté")
            else:
                print(f"  ✗ {mid} : {str(res.get('erreur'))[:45]}")
            if j < len(retry_captcha):
                http_humain.attendre_humain(RATE_LIMIT_MIN_SEC, RATE_LIMIT_MAX_SEC,
                                            mu=RATE_LIMIT_MOYEN_SEC,
                                            sigma=RATE_LIMIT_ECART_SEC, verbose=False)
        retry_captcha = encore

    print("\n" + "=" * 60 + "\nBILAN\n" + "=" * 60)
    print(f"Marchés traités ce run : {traites}")
    for cle, n in sorted(bilan.items(), key=lambda x: -x[1]):
        print(f"  {cle}: {n}")
    if gains:
        print(f"\nMarchés passés à complet ({len(gains)}) :")
        for mid, a, n in gains[:15]:
            print(f"  {mid} : {a} → {n}")
    if erreurs:
        print(f"\nErreurs ({len(erreurs)}) :")
        for mid, err in erreurs[:12]:
            print(f"  {mid} : {err[:90]}")
    if solde_epuise:
        print("\n⚠ Interrompu : solde 2captcha épuisé.")
    if bans_consecutifs >= BANS_CONSECUTIFS_STOP:
        print("\n⚠ Interrompu : ban IP.")

    cout = nb_captchas * COUT_2CAPTCHA_USD_PAR_CAPTCHA
    print(f"\nCaptchas résolus : {nb_captchas} (~${cout:.3f} 2captcha)")
    nb_complet = sum(v for k, v in bilan.items() if k.endswith("_to_complet"))
    print(f"\n⇒ Total marchés passés à complet ce run : {nb_complet}")
    if nb_complet > 0:
        print("⇒ Briefs à re-extraire : python reextraire_briefs_complet.py")


if __name__ == "__main__":
    main()
