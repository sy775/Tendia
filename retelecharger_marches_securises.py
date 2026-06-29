"""
retelecharger_marches_securises.py
----------------------------------
Batch : récupère le DCE sur marches-securises.fr pour les avis SANS DCE complet
dont l'avis cite cette plateforme + une référence. Recherche anonyme par
référence (arrêté du 22/03/2019) + désambiguïsation OBLIGATOIRE par acheteur.

⚠️ LIMITE PLATEFORME — DÉBIT ANTI-BULK (constat après reverse-engineering poussé).
marches-securises ne sert le lien de téléchargement anonyme qu'à CADENCE BASSE :
le token apparaît tant que le VOLUME de requêtes sur une fenêtre glissante reste
sous un seuil (~10-15 vues détail / quelques minutes, par ASN/pool résidentiel).
Au-delà, le token disparaît pour TOUTES les requêtes jusqu'à ce que la fenêtre se
vide (plusieurs minutes SANS aucune requête). Ce n'est PAS contournable par :
  - la rotation d'IP (vérifié : 4 IPs distinctes, throttle identique) ;
  - l'isolation en sous-process (le throttle est réseau/ASN, pas process) ;
  - un simple pacing serré (60s entre marchés ne suffit pas si le volume monte).
Un marché ISOLÉ après une période calme réussit toujours (token servi). D'où :

ARCHITECTURE « UN SOUS-PROCESS PAR MARCHÉ » (mode --un-marche) :
  - isole les pannes (un marché qui plante/hang ne tue pas le batch) ;
  - garantit un état de connexion propre par marché ;
  - n'élimine PAS la limite de débit → pacing LONG + cooldown inter-passe réel.
Rendement réaliste : quelques DCE par fenêtre. Les runs quotidiens du pipeline
accumulent les récupérations (un marché non pris aujourd'hui passe demain).
Levier pour industrialiser : un proxy d'un AUTRE ASN (FAI distinct) par run.

Usage : python retelecharger_marches_securises.py [--oui] [--max N]
        python retelecharger_marches_securises.py --un-marche BOAMP-26-XXXXX  (worker)
"""
import argparse
import subprocess
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

RATE_LIMIT_SEC = 90     # pacing inter-marchés : rester sous le seuil de débit du
#                         service de token anonyme (cadence quasi-humaine).
MAX_PASSES = 3          # re-tente les throttlés après un vrai cooldown de fenêtre.
PAUSE_PASSE = 300       # 5 min SANS requête pour vider la fenêtre glissante.

# Codes de sortie du worker --un-marche (interprétés par l'orchestrateur).
EXIT_COMPLET = 0        # DCE téléchargé et qualifié complet → persisté
EXIT_PARTIEL = 2        # DCE téléchargé mais incomplet/candidature → persisté
EXIT_NON_RESOLUBLE = 3  # réf générique / pas de DCE anonyme → définitif, pas de retry
EXIT_RETRYABLE = 1      # échec réseau/throttle → à retenter


def _cibles(max_n: int):
    """Avis ciblant marches-securises (plateforme + référence) sans DCE complet."""
    marches = stockage.charger("marches") or {}
    out = []
    for mid, m in sorted(marches.items()):
        if not (isinstance(m, dict) and m.get("nature_libelle") == "Avis de marché"
                and m.get("dce_contenu") != "complet"):
            continue
        base, ref = RR.extraire_plateforme_reference(m)
        if base and "marches-securises" in base.lower() and ref:
            out.append((mid, m))
    return out[:max(0, max_n)]


def traiter_un_marche(mid: str) -> int:
    """WORKER : télécharge le DCE d'UN marché, qualifie, persiste. Process dédié
    (appelé en sous-process) pour garantir un état de connexion frais → token
    anonyme servi de façon fiable. Retourne un code de sortie EXIT_*."""
    marches = stockage.charger("marches") or {}
    m = marches.get(mid)
    if not isinstance(m, dict):
        print(f"  {mid} : introuvable en base")
        return EXIT_NON_RESOLUBLE
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
        m["url_dce_source"] = "marches_securises_reference"
        stockage.ecrire("marches", mid, m)
        print(f"  {mid} : {ancien} → {q['qualite']}")
        return EXIT_COMPLET if q["qualite"] == "complet" else EXIT_PARTIEL
    err = str(res.get("erreur") or "")
    print(f"  {mid} : échec ({err[:55]})")
    if "générique" in err or "aucune consultation" in err:
        return EXIT_NON_RESOLUBLE
    return EXIT_RETRYABLE


def _lancer_worker(mid: str) -> int:
    """Lance le worker --un-marche dans un sous-process FRAIS. Renvoie le code."""
    cmd = [sys.executable, __file__, "--un-marche", mid]
    r = subprocess.run(cmd)
    return r.returncode


def orchestrer(max_n: int):
    cibles = _cibles(max_n)
    print("=== RE-TÉLÉCHARGEMENT MARCHES-SECURISES (1 sous-process / marché) ===")
    print(f"Cibles (plateforme + référence) : {len(cibles)}\n")
    if not cibles:
        print("Rien à faire.")
        return

    bilan = Counter()
    ok = 0
    restants = [mid for mid, _ in cibles]
    for passe in range(1, MAX_PASSES + 1):
        if not restants:
            break
        print(f"\n──── PASSE {passe}/{MAX_PASSES} · {len(restants)} marché(s) ────")
        echecs = []
        for i, mid in enumerate(restants, 1):
            print(f"  [P{passe} {i}/{len(restants)}] {mid} …")
            code = _lancer_worker(mid)
            if code == EXIT_COMPLET:
                ok += 1
                bilan["complet"] += 1
            elif code == EXIT_PARTIEL:
                bilan["partiel (téléchargé, incomplet)"] += 1
            elif code == EXIT_NON_RESOLUBLE:
                bilan["non résoluble"] += 1
            else:
                echecs.append(mid)
            # Non résoluble = 1 recherche, 0 vue détail → pacing court. Sinon une
            # vue détail a été consommée → pacing long (rester sous le seuil débit).
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
