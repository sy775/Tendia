"""
reextraire_briefs_complet.py
----------------------------
Re-génère le brief LLM des marchés passés à `dce_contenu == "complet"` dont le
brief n'a pas encore le flag `genere_avec_dce_complet=True`.

IMPORTANT (fix Sprint AWS-Achat) : ce script NE re-télécharge PAS le DCE. Les
fichiers sont DÉJÀ sur disque dans data/dce/<id>/ (récupérés par les downloaders
dédiés Atexo / Achatpublic / AWS-Achat). On appelle directement l'extraction LLM
sur ces fichiers via tendia_extraire.traiter_marche. L'ancienne version passait
par enrichir_complet.enrichir(force=True) qui re-téléchargeait via le téléchargeur
générique — voué à l'échec sur les plateformes à downloader dédié.

Comportement :
  1. Cibles = marchés dce_contenu=="complet" sans brief genere_avec_dce_complet.
  2. Si data/dce/<id>/ absent ou vide → skip (sans crash, continue).
  3. Si fichiers présents → extraction LLM directe (pas de re-download).
  4. Backup de l'ancien brief sous <id>.bak_avant_complet.
  5. Nouveau brief stocké avec genere_avec_dce_complet=True.

Nécessite réseau + API (coût LLM ~0,05 €/brief). Confirmation interactive.
Usage : python reextraire_briefs_complet.py [--oui] [--limite N]
"""
import argparse
import os
import sys

# sys.stdout.reconfigure plutôt que io.TextIOWrapper : évite le bug
# "I/O operation on closed file" en cascade d'imports sous Windows.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import tendia_extraire


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--oui", action="store_true",
                    help="Pas de confirmation interactive.")
    ap.add_argument("--limite", type=int, default=None,
                    help="Max de marchés à re-extraire.")
    args = ap.parse_args()

    marches = stockage.charger("marches") or {}
    briefs = stockage.charger("briefs_extraits") or {}

    cibles = []
    for mid, m in sorted(marches.items()):
        if m.get("dce_contenu") != "complet":
            continue
        b = briefs.get(mid)
        if b and b.get("genere_avec_dce_complet"):
            continue  # déjà à jour
        cibles.append(mid)

    if args.limite:
        cibles = cibles[:args.limite]

    print("=== RE-EXTRACTION (briefs depuis DCE complet, SANS re-téléchargement) ===")
    print(f"Cibles : {len(cibles)} marchés")
    cout = len(cibles) * 0.05
    print(f"Coût LLM estimé : ~{cout:.2f} €")
    if not cibles:
        return
    if not args.oui:
        try:
            input("Appuie sur Entrée pour lancer (Ctrl+C pour annuler)... ")
        except (EOFError, KeyboardInterrupt):
            print("\nAnnulé.")
            return

    # Scan unique de tous les dossiers DCE → map mid -> (dossier, pdfs).
    # force=True : re-décompresse et re-extrait le texte (pas d'appel LLM ici).
    print("\nScan des dossiers DCE déjà présents sur disque...")
    scan = tendia_extraire._scanner_dossiers_dce(force=True, verbose=False)
    par_mid = {t[0]: (t[1], t[2]) for t in scan}

    refait = 0
    skipped = 0
    erreurs = []
    cout_total = 0.0

    for mid in cibles:
        dossier = os.path.join("data", "dce", mid)

        # Vérification disque : présent et non vide ?
        if not os.path.isdir(dossier) or not any(os.scandir(dossier)):
            print(f"  [{mid}] skip : dossier DCE absent ou vide")
            skipped += 1
            continue

        # PDFs exploitables (depuis le scan) ?
        if mid not in par_mid:
            print(f"  [{mid}] skip : aucun fichier exploitable (pas de PDF/docx/xlsx)")
            skipped += 1
            continue

        _dossier_scan, pdfs = par_mid[mid]

        # Backup de l'ancien brief
        if mid in briefs:
            stockage.ecrire("briefs_extraits", f"{mid}.bak_avant_complet", briefs[mid])

        # Extraction LLM SEULE (pas de re-download)
        try:
            res = tendia_extraire.traiter_marche(mid, _dossier_scan, pdfs,
                                                 dry_run=False, verbose=False)
        except Exception as e:
            erreurs.append((mid, f"{type(e).__name__}: {e}"))
            print(f"  [{mid}] ❌ erreur extraction : {type(e).__name__}: {e}")
            continue

        if not res.get("ok"):
            erreurs.append((mid, res.get("erreur") or res.get("raison") or "?"))
            print(f"  [{mid}] ❌ extraction échouée : "
                  f"{res.get('erreur') or res.get('raison')}")
            continue

        # traiter_marche a déjà stocké le brief en base. On ré-ouvre pour
        # poser le flag genere_avec_dce_complet.
        nouveau = stockage.lire("briefs_extraits", mid)
        if nouveau:
            nouveau["genere_avec_dce_complet"] = True
            stockage.ecrire("briefs_extraits", mid, nouveau)
            refait += 1
            cout = ((res.get("extraction") or {}).get("_meta") or {}).get("cout_eur") or 0
            cout_total += float(cout or 0)
            print(f"  [{mid}] ✅ re-extrait (genere_avec_dce_complet=True)")
        else:
            erreurs.append((mid, "brief introuvable après extraction"))
            print(f"  [{mid}] ⚠ brief introuvable après extraction")

    # Bilan
    print()
    print("=" * 60)
    print("BILAN")
    print("=" * 60)
    print(f"  Re-extraits           : {refait}")
    print(f"  Skip (DCE absent/vide): {skipped}")
    print(f"  Erreurs               : {len(erreurs)}")
    print(f"  Coût LLM total        : ~{cout_total:.3f} €")
    if erreurs:
        print("\n  Détail erreurs :")
        for mid, err in erreurs[:12]:
            print(f"    {mid} : {str(err)[:90]}")
    if refait:
        print("\nCompare avant/après : briefs_extraits/<id> vs "
              "briefs_extraits/<id>.bak_avant_complet")


if __name__ == "__main__":
    main()
