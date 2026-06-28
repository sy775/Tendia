"""
retelecharger_aws_achat_anti_ban.py
-----------------------------------
Variante ANTI-BAN du batch AWS-Achat (www.marches-publics.info).

Suite au ban IP du 13/06/2026 (rythme fixe 3 s + UA unique = pattern bot
évident), ce script étale le téléchargement comme un humain :
  - délai gaussien ~75 s ±30 entre marchés (au lieu de 3 s fixes) ;
  - pause cumulative de 15-30 min tous les 20 marchés ;
  - cap de 30 marchés par run (étalement sur plusieurs jours / cron) ;
  - ne tourne qu'aux heures de bureau (8h-19h lun-ven) sauf --ignorer-heures ;
  - arrêt propre après 3 bans consécutifs (etape_erreur=ban_detecte).

Le User-Agent tournant et les délais inter-étapes sont gérés en amont par
aws_downloader (via http_humain). Idempotent : skip les marchés déjà OK.

L'ancien retelecharger_aws_achat.py est conservé (compat / rythme rapide).

Usage : python retelecharger_aws_achat_anti_ban.py [--oui] [--max N]
                                                   [--ignorer-heures]
"""
import argparse
import os
import sys
import shutil
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import tendia_dce
import http_humain
import aws_downloader as A

REPERTOIRE_DCE = Path("data/dce")

# --- Paramètres anti-ban ---
RATE_LIMIT_MOYEN_SEC = 75       # délai moyen entre marchés (gaussien)
RATE_LIMIT_ECART_SEC = 30       # écart-type
RATE_LIMIT_MIN_SEC = 20         # borne basse
RATE_LIMIT_MAX_SEC = 180        # borne haute
PAUSE_TOUTES_LES_N = 20         # pause longue toutes les N marchés
MAX_MARCHES_PAR_RUN = 30        # cap par session
BANS_CONSECUTIFS_STOP = 3       # arrêt après N bans d'affilée

# --- Tarifs pour l'estimation de coût ---
COUT_BRIGHTDATA_USD_PAR_GB = 8.0          # plan ISP Pay-per-GB
COUT_2CAPTCHA_USD_PAR_CAPTCHA = 0.001     # ~$1/1000 captchas normaux


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--oui", action="store_true",
                    help="Pas de confirmation interactive.")
    ap.add_argument("--max", type=int, default=MAX_MARCHES_PAR_RUN,
                    help=f"Max de marchés ce run (défaut {MAX_MARCHES_PAR_RUN}).")
    ap.add_argument("--ignorer-heures", action="store_true",
                    help="Ignore la contrainte heures de bureau (tests).")
    args = ap.parse_args()

    api_key = os.environ.get("TWOCAPTCHA_API_KEY")
    if not api_key:
        print("❌ TWOCAPTCHA_API_KEY absente du .env. Abandon.")
        sys.exit(1)

    if not args.ignorer_heures and not http_humain.heure_actuelle_est_bureau(verbose=True):
        print("Hors heures de bureau (8h-19h lun-ven). Arrêt "
              "(relance pendant les heures ouvrées, ou --ignorer-heures).")
        return

    marches = stockage.charger("marches") or {}
    # On vise les marchés AWS encore non-complet (auth_requise / vide / erreur).
    cibles = [
        (mid, m) for mid, m in sorted(marches.items())
        if "marches-publics.info" in (m.get("url_dce") or "")
        and m.get("dce_contenu") != "complet"
    ]
    total_restant = len(cibles)
    cibles = cibles[:max(0, args.max)]

    print("=== RE-TÉLÉCHARGEMENT AWS-ACHAT (ANTI-BAN) ===")
    print(f"Marchés AWS non-complet restants : {total_restant}")
    print(f"Traités ce run (cap {args.max})   : {len(cibles)}")
    duree_est = len(cibles) * RATE_LIMIT_MOYEN_SEC / 60
    duree_est += (len(cibles) // PAUSE_TOUTES_LES_N) * 22  # pauses ~22 min
    print(f"Durée estimée                     : ~{duree_est:.0f} min")
    print(f"Coût 2captcha estimé              : ~{len(cibles) * 0.001:.3f} €")
    print()

    if not cibles:
        print("Rien à faire ce run.")
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
    bans_consecutifs = 0
    solde_epuise = False
    traites = 0
    bw_octets = 0          # bande passante consommée (proxy Bright Data)
    nb_captchas = 0        # captchas résolus (2captcha)
    retry_captcha = []     # échecs captcha (transitoires) à retenter après la boucle

    for i, (mid, marche) in enumerate(cibles, 1):
        # Garde-fou heures de bureau à chaque itération (les runs sont longs).
        if not args.ignorer_heures and not http_humain.heure_actuelle_est_bureau():
            print(f"\nHeures de bureau dépassées, arrêt après {i - 1} marchés "
                  f"(le script est idempotent, relance demain).")
            break

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

        try:
            res = A.telecharger_dce_pour_marche(
                marche, str(REPERTOIRE_DCE),
                api_key_2captcha=api_key, verbose=False)
        except Exception as e:
            res = {"ok": False, "erreur": f"{type(e).__name__}: {e}"}

        traites += 1
        bw_octets += res.get("taille_octets", 0) or 0
        nb_captchas += res.get("nb_captcha_resolus", 0) or 0

        # --- Solde 2captcha épuisé : arrêt immédiat ---
        if res.get("solde_2captcha_epuise"):
            print(f"  [{i}/{len(cibles)}] {mid} : ❌ SOLDE 2CAPTCHA ÉPUISÉ")
            solde_epuise = True
            erreurs.append((mid, "solde 2captcha épuisé"))
            break

        # --- Détection ban : compteur consécutif. Le wrapper a déjà fait une
        # rotation d'IP en interne ; un ban_persistant ici = pool/zone bannie. ---
        if res.get("etape_erreur") in ("ban_detecte", "ban_persistant"):
            bans_consecutifs += 1
            erreurs.append((mid, "ban détecté"))
            bilan[f"{ancien_contenu}_to_ban"] = bilan.get(f"{ancien_contenu}_to_ban", 0) + 1
            print(f"  [{i}/{len(cibles)}] {mid} : 🚫 BAN détecté "
                  f"({bans_consecutifs}/{BANS_CONSECUTIFS_STOP})")
            if bans_consecutifs >= BANS_CONSECUTIFS_STOP:
                print(f"\n🚫 {BANS_CONSECUTIFS_STOP} bans consécutifs : arrêt du batch. "
                      f"L'IP est probablement bannie — attends quelques heures/jours "
                      f"avant de relancer (le script reprendra où il s'est arrêté).")
                break
            # On laisse passer le délai inter-marché normal avant de retenter.
            if i < len(cibles):
                http_humain.attendre_humain(
                    RATE_LIMIT_MIN_SEC, RATE_LIMIT_MAX_SEC,
                    mu=RATE_LIMIT_MOYEN_SEC, sigma=RATE_LIMIT_ECART_SEC, verbose=True)
            continue

        bans_consecutifs = 0  # tout sauf un ban réinitialise le compteur

        if res.get("ok"):
            qual = tendia_dce.qualifier_dce(str(dossier))
            nouveau_contenu = qual["qualite"]
            marche["dce_contenu"] = nouveau_contenu
            marche["dce_pieces_contractuelles"] = qual["pieces_contractuelles"]
            marche["dce_raison_contenu"] = qual["raison"]
            marche["dce_telecharge_le"] = datetime.now().isoformat()
            marche["dce_pieces_manquantes"] = []
            bilan[f"{ancien_contenu}_to_{nouveau_contenu}"] = \
                bilan.get(f"{ancien_contenu}_to_{nouveau_contenu}", 0) + 1
            if nouveau_contenu == "complet":
                gains.append((mid, ancien_pieces, qual["pieces_contractuelles"]))
        else:
            err = res.get("erreur", "?")
            etape = res.get("etape_erreur", "?")
            bilan[f"{ancien_contenu}_to_erreur"] = bilan.get(f"{ancien_contenu}_to_erreur", 0) + 1
            erreurs.append((mid, f"[{etape}] {err}"))
            marche["dce_telecharge_le"] = datetime.now().isoformat()
            marche["dce_raison_contenu"] = f"echec aws-achat [{etape}]: {err}"
            if etape == "captcha":   # transitoire → on retentera après la boucle
                retry_captcha.append((mid, marche))

        stockage.ecrire("marches", mid, marche)

        skip_label = " [skip]" if res.get("skip") else ""
        print(f"  [{i}/{len(cibles)}] {mid} : "
              f"{ancien_contenu} → {marche.get('dce_contenu')}{skip_label}")

        # --- Pause cumulative tous les N marchés ---
        http_humain.attendre_pause_cumulative(i, seuil=PAUSE_TOUTES_LES_N,
                                              verbose=True)

        # --- Délai « humain » entre marchés (gaussien) ---
        if i < len(cibles):
            http_humain.attendre_humain(
                RATE_LIMIT_MIN_SEC, RATE_LIMIT_MAX_SEC,
                mu=RATE_LIMIT_MOYEN_SEC, sigma=RATE_LIMIT_ECART_SEC, verbose=True)

    # --- Passes de retry des échecs CAPTCHA (transitoires). Additive, après la
    # boucle ; on s'abstient si ban/solde/hors-heures. ---
    passe = 0
    while (retry_captcha and passe < 2 and not solde_epuise
           and bans_consecutifs < BANS_CONSECUTIFS_STOP
           and (args.ignorer_heures or http_humain.heure_actuelle_est_bureau())):
        passe += 1
        print(f"\n--- Retry captcha (passe {passe}) : {len(retry_captcha)} marché(s) ---")
        encore = []
        for j, (mid, marche) in enumerate(retry_captcha, 1):
            dossier = REPERTOIRE_DCE / mid
            try:
                res = A.telecharger_dce_pour_marche(marche, str(REPERTOIRE_DCE),
                                                    api_key_2captcha=api_key, verbose=False)
            except Exception as e:
                res = {"ok": False, "erreur": str(e), "etape_erreur": "exception"}
            bw_octets += res.get("taille_octets", 0) or 0
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

    # --- Bilan ---
    print()
    print("=" * 60)
    print("BILAN")
    print("=" * 60)
    print(f"Marchés traités ce run : {traites}")
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
            print(f"  {mid} : {err[:90]}")

    if solde_epuise:
        print("\n⚠ Batch interrompu : solde 2captcha épuisé. Recharge puis relance.")
    if bans_consecutifs >= BANS_CONSECUTIFS_STOP:
        print("\n⚠ Batch interrompu : ban IP. Attends avant de relancer.")

    # --- Estimation coût du run ---
    cout_brightdata = bw_octets / 1_000_000_000 * COUT_BRIGHTDATA_USD_PAR_GB
    cout_2captcha = nb_captchas * COUT_2CAPTCHA_USD_PAR_CAPTCHA
    print()
    print("Coûts estimés de ce run")
    print(f"  Bande passante  : {bw_octets / 1_000_000:.1f} Mo "
          f"(~${cout_brightdata:.3f} Bright Data @ ${COUT_BRIGHTDATA_USD_PAR_GB}/GB)")
    print(f"  Captchas résolus: {nb_captchas} "
          f"(~${cout_2captcha:.3f} 2captcha)")
    print(f"  Total           : ~${cout_brightdata + cout_2captcha:.3f}")

    nb_complet = sum(v for k, v in bilan.items() if k.endswith("_to_complet"))
    print()
    print(f"⇒ Total marchés passés à complet ce run : {nb_complet}")
    restant = max(0, total_restant - nb_complet)
    if restant > 0:
        print(f"⇒ Reste ~{restant} marchés AWS à traiter (relance le script un autre jour).")
    if nb_complet > 0:
        print("⇒ Briefs à re-extraire : python reextraire_briefs_complet.py")


if __name__ == "__main__":
    main()
