"""
backfill_dce_qualite.py
-----------------------
Backfill rétroactif du champ `dce_contenu` (qualité du CONTENU téléchargé) sur
tous les marchés de la base, via tendia_dce.qualifier_dce.

NB : n'écrase PAS `dce_qualite` (résolution d'URL, lu comme filtre ailleurs).
Le contenu va dans `dce_contenu` + `dce_pieces_contractuelles` + `dce_raison_contenu`.

Usage :
    python backfill_dce_qualite.py              # qualification seule (read-only DL)
    python backfill_dce_qualite.py --relancer   # + re-télécharge les vide/incomplet/erreur

Idempotent : relançable N fois sans effet de bord (ne supprime rien).
"""
import argparse
import io
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import stockage
import tendia_dce

REPERTOIRE_DCE = tendia_dce.REPERTOIRE_DCE
RETENTABLES = {"vide", "incomplet", "erreur"}
DELAI_ENTRE_DL_SEC = 2  # rate-limit


def _maintenant():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _qualifier_un(marche, log=None):
    """Qualifie un marché : shortcut auth plateforme, sinon qualifier_dce."""
    mid = marche.get("id")
    url = marche.get("url_dce") or ""
    dossier = os.path.join(REPERTOIRE_DCE, mid)
    if tendia_dce.url_est_auth_requise(url):
        return {"qualite": "auth_requise", "pieces_contractuelles": [],
                "raison": "plateforme connue auth requise"}
    if not os.path.isdir(dossier):
        return {"qualite": "vide", "pieces_contractuelles": [],
                "raison": "dossier inexistant"}
    return tendia_dce.qualifier_dce(dossier, log)


def _appliquer(marche, res):
    marche["dce_contenu"] = res["qualite"]
    marche["dce_pieces_contractuelles"] = res.get("pieces_contractuelles", [])
    marche["dce_raison_contenu"] = res.get("raison", "")
    marche["dce_qualifie_le"] = _maintenant()


def _relancer_telechargement(marche):
    """Re-télécharge un marché. Retourne un log {statut, raison}."""
    try:
        import requests
        import tendia_telecharger_dce as tdce
        session = requests.Session()
        return tdce._telecharger_marche(marche, session=session, force=True,
                                        dry_run=False, verbose=False)
    except Exception as e:
        return {"statut": "erreur", "raison": f"{type(e).__name__}: {e}"}


def main():
    ap = argparse.ArgumentParser(description="Backfill dce_contenu.")
    ap.add_argument("--relancer", action="store_true",
                    help="Re-télécharge les marchés vide/incomplet/erreur (hors auth_requise).")
    args = ap.parse_args()

    marches = stockage.charger("marches") or {}
    print(f"=== BACKFILL DCE_CONTENU — {_maintenant()} ===")
    print(f"Marchés traités : {len(marches)}\n")

    avant = Counter(repr(m.get("dce_contenu")) for m in marches.values())
    print("Répartition initiale (dce_contenu avant backfill) :")
    for k, n in avant.most_common():
        print(f"  {k:<16} : {n}")
    print()

    apres = Counter()
    plateformes = Counter()
    marque_vers_vide = 0  # avait un dossier marqué mais finit vide
    bascules = Counter()

    for i, (mid, marche) in enumerate(sorted(marches.items()), 1):
        ancien_contenu = marche.get("dce_contenu")
        res = _qualifier_un(marche)

        # Comptage "marqué DCE -> vide" : dce_qualite exploitable mais contenu vide
        if (res["qualite"] == "vide"
                and marche.get("dce_qualite") in ("directe", "via_keyword", "racine")):
            marque_vers_vide += 1

        url = marche.get("url_dce") or ""
        for p in tendia_dce.PLATEFORMES_AUTH_REQUISES:
            if p in url.lower() and res["qualite"] == "auth_requise":
                plateformes[p] += 1

        _appliquer(marche, res)

        # Re-téléchargement optionnel (hors auth_requise / complet)
        if args.relancer and res["qualite"] in RETENTABLES:
            log = _relancer_telechargement(marche)
            res2 = _qualifier_un(marche, log)
            bascules[f"{res['qualite']} → {res2['qualite']}"] += 1
            if res2["qualite"] != res["qualite"]:
                _appliquer(marche, res2)
                marche["dce_relance_le"] = _maintenant()
                res = res2
            print(f"  [{i}/{len(marches)}] {mid} relance: {res['qualite']}")
            time.sleep(DELAI_ENTRE_DL_SEC)

        apres[res["qualite"]] += 1
        stockage.ecrire("marches", mid, marche)

    print("Répartition après backfill :")
    total = sum(apres.values()) or 1
    for niveau in ("complet", "incomplet", "vide", "auth_requise", "erreur"):
        n = apres.get(niveau, 0)
        print(f"  {niveau:<13} : {n:>4} ({100*n/total:.0f}%)")
    print()

    if plateformes:
        print("Plateformes auth_requise détectées :")
        for p, n in plateformes.most_common():
            print(f"  {p:<28} : {n}")
        print()

    print(f"Marchés 'marqué DCE exploitable' devenus 'vide' : {marque_vers_vide}")

    if args.relancer and bascules:
        print("\nBascules après re-téléchargement :")
        for b, n in bascules.most_common():
            print(f"  {b:<24} : {n}")

    # Note exploitabilité
    briefables = apres.get("complet", 0)
    bloques_auth = apres.get("auth_requise", 0)
    print(f"\n⇒ Marchés briefables (dce_contenu=complet) : {briefables}")
    print(f"⇒ Bloqués sur auth_requise (cible Sprint AWS-Achat) : {bloques_auth}")


if __name__ == "__main__":
    main()
