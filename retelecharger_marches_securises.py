"""
retelecharger_marches_securises.py
----------------------------------
Batch : récupère le DCE sur marches-securises.fr pour les avis SANS DCE complet
dont l'avis cite cette plateforme + une référence. Recherche anonyme par
référence (arrêté du 22/03/2019) + désambiguïsation OBLIGATOIRE par acheteur.

MÉCANISME DU « throttle » (élucidé) — QUOTA DE TÉLÉCHARGEMENTS PAR IP.
marches-securises sert le lien de DL anonyme (dl_dc_s&token=) tant que l'IP est
SOUS un quota ; au-delà, la page affiche « Le nombre maximum de téléchargement a
été atteint. Votre adresse IP est (…) » et le lien disparaît. C'est PAR IP → la
ROTATION D'IP (proxy résidentiel) contourne le quota : le connecteur retente avec
des IP fraîches jusqu'à en trouver une sous quota (MAX_ESSAIS_IP). PRÉREQUIS
ABSOLU : `TENDIA_PROXY_URL` chargé (sinon on tape sur l'IP réelle, vite sur-quota
→ échec « token introuvable » trompeur ; c'était le vrai bug du batch).

COUVERTURE : recherche par RÉFÉRENCE (haute confiance) ET, pour les avis sans
référence dans la donnée BOAMP, fallback recherche par OBJET — toujours sécurisé
par la désambiguïsation acheteur obligatoire. Pacing court (politesse) ; multi-
passes pour les seuls échecs transitoires (réseau / quota épuisé sur N IP).

Intégré au pipeline (tendia_pipeline, étape connecteurs DCE). In-process.

Usage : python retelecharger_marches_securises.py [--oui] [--max N]
        python retelecharger_marches_securises.py --un-marche BOAMP-26-XXXXX
"""
import argparse
import sys
import time
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import tendia_dce
import resolution_reference as RR
import marches_securises_downloader as MS
import tendia_telecharger_dce as T

RATE_LIMIT_SEC = 6      # pacing inter-marchés (politesse) ; pas de throttle temporel,
#                         le quota par IP est battu par la rotation dans le connecteur.
MAX_PASSES = 2          # 2e passe pour les échecs réseau / « quota épuisé » transitoires.
PAUSE_PASSE = 30        # courte pause entre passes.

# Codes de statut d'un marché (aussi code de sortie en mode --un-marche).
EXIT_COMPLET = 0        # DCE téléchargé et qualifié complet → persisté
EXIT_PARTIEL = 2        # DCE téléchargé mais incomplet/candidature → persisté
EXIT_NON_RESOLUBLE = 3  # réf générique / restreinte / acheteur ≠ → définitif, pas de retry
EXIT_RETRYABLE = 1      # échec réseau / quota IP épuisé → à retenter


def _cibles(max_n: int):
    """Avis marches-securises sans DCE complet, récupérables par recherche :
      - avec RÉFÉRENCE (recherche par référence, haute confiance) ; OU
      - SANS référence mais avec un OBJET distinctif ET sans lien direct (url_dce) —
        recherche par objet + désambiguïsation acheteur (le lien direct, lui, est
        géré par le pipeline DCE normal)."""
    marches = stockage.charger("marches") or {}
    out = []
    for mid, m in sorted(marches.items()):
        if not (isinstance(m, dict) and m.get("nature_libelle") == "Avis de marché"
                and m.get("dce_contenu") != "complet"):
            continue
        base, ref = RR.extraire_plateforme_reference(m)
        if not (base and "marches-securises" in base.lower()):
            continue
        if ref:
            out.append((mid, m))
        elif (not m.get("url_dce")
              and len(MS._mots_cles_objet(m.get("objet") or "")) >= 6
              and m.get("acheteur_nom")):
            out.append((mid, m))
    return out[:max(0, max_n)]


def _traiter(mid: str, m: dict) -> int:
    """Télécharge le DCE d'UN marché (réf puis fallback objet), qualifie, persiste.
    In-process. Retourne un code EXIT_* (COMPLET / PARTIEL / NON_RESOLUBLE / RETRYABLE)."""
    ancien = m.get("dce_contenu") or "?"
    dossier = str(T.REPERTOIRE_DCE / mid)
    try:
        res = MS.telecharger_dce_pour_marche(m, str(T.REPERTOIRE_DCE), verbose=True)
    except Exception as e:
        print(f"  {mid} : exception {type(e).__name__}: {e}")
        return EXIT_RETRYABLE
    if res.get("ok"):
        q = tendia_dce.qualifier_dce(dossier)
        m["dce_contenu"] = q["qualite"]
        m["dce_pieces_contractuelles"] = q["pieces_contractuelles"]
        m["dce_raison_contenu"] = q["raison"]
        m["dce_telecharge_le"] = datetime.now().isoformat()
        m["url_dce_source"] = f"marches_securises_{res.get('mode') or 'reference'}"
        stockage.ecrire("marches", mid, m)
        print(f"  {mid} : {ancien} → {q['qualite']} (via {res.get('mode')})")
        return EXIT_COMPLET if q["qualite"] == "complet" else EXIT_PARTIEL
    err = str(res.get("erreur") or "")
    print(f"  {mid} : échec ({err[:55]})")
    # Définitifs (inutile de retenter) : réf générique introuvable, consultation
    # restreinte (pas d'accès anonyme), acheteur non apparié (filet anti-erreur).
    # Retryable UNIQUEMENT : quota IP épuisé sur N IP, ou échec réseau (transitoire).
    definitifs = ("générique", "aucune consultation", "pas d'accès anonyme",
                  "acheteur non apparié")
    return EXIT_NON_RESOLUBLE if any(d in err for d in definitifs) else EXIT_RETRYABLE


def traiter_un_marche(mid: str) -> int:
    """Entrée CLI --un-marche : charge la base, traite le marché mid. Renvoie EXIT_*."""
    m = (stockage.charger("marches") or {}).get(mid)
    if not isinstance(m, dict):
        print(f"  {mid} : introuvable en base")
        return EXIT_NON_RESOLUBLE
    return _traiter(mid, m)


def orchestrer(max_n: int):
    cibles = _cibles(max_n)
    print("=== RE-TÉLÉCHARGEMENT MARCHES-SECURISES (référence + objet) ===")
    print(f"Cibles marches-securises récupérables : {len(cibles)}\n")
    if not cibles:
        print("Rien à faire.")
        return

    # Le quota par IP est battu par la rotation DANS le connecteur (retry IP fraîche).
    # Au niveau batch : multi-passes pour les échecs transitoires (réseau / quota
    # épuisé sur N IP). Les échecs définitifs ne sont pas retentés (cf _traiter).
    bilan = Counter()
    ok = 0
    restants = list(cibles)
    for passe in range(1, MAX_PASSES + 1):
        if not restants:
            break
        print(f"\n──── PASSE {passe}/{MAX_PASSES} · {len(restants)} marché(s) ────")
        echecs = []
        for i, (mid, m) in enumerate(restants, 1):
            print(f"  [P{passe} {i}/{len(restants)}] {mid} …")
            code = _traiter(mid, m)
            if code == EXIT_COMPLET:
                ok += 1
                bilan["complet"] += 1
            elif code == EXIT_PARTIEL:
                bilan["partiel (téléchargé, incomplet)"] += 1
            elif code == EXIT_NON_RESOLUBLE:
                bilan["non résoluble"] += 1
            else:
                echecs.append((mid, m))
            if i < len(restants):
                time.sleep(8 if code == EXIT_NON_RESOLUBLE else RATE_LIMIT_SEC)
        restants = echecs
        if restants and passe < MAX_PASSES:
            print(f"\n  ⏸ pause inter-passe {PAUSE_PASSE}s…")
            time.sleep(PAUSE_PASSE)

    if restants:
        bilan["échec (épuisé)"] += len(restants)

    print("\nBilan :")
    for k, n in bilan.most_common():
        print(f"  {k} : {n}")
    print(f"\n⇒ {ok} marchés passés à complet")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--oui", action="store_true")
    ap.add_argument("--max", type=int, default=30)
    ap.add_argument("--un-marche", metavar="MID",
                    help="WORKER interne : traite un seul marché et sort (code EXIT_*).")
    args = ap.parse_args()

    if args.un_marche:
        sys.exit(traiter_un_marche(args.un_marche))

    if not args.oui:
        try:
            input("Entrée pour lancer (Ctrl+C annuler)... ")
        except (EOFError, KeyboardInterrupt):
            print("\nAnnulé.")
            return
    orchestrer(args.max)


if __name__ == "__main__":
    main()
