"""
relancer_extraction_chantier1.py
--------------------------------
Re-extraction Chantier 1 des briefs `complet`, avec :
- plafond budgétaire € (arrêt propre quand atteint) ;
- ≥ 1 marché par preset garanti (couverture des 6 secteurs) ;
- priorisation par gisement preset décroissant (btp > ing > conseil > …) ;
- hors-périmètre traité en DERNIER (non-preset, valeur client moindre).

Saute les marchés déjà re-extraits Chantier 1 (`_meta.prompts_versions` présent).
Traitement par dossier (pas de re-scan global des ~200 dirs). Progrès flushé
dans logs/chantier1_1g_<date>.jsonl pour suivi en direct.

Usage : python relancer_extraction_chantier1.py [--plafond-eur 30] [--oui] [--max N]
"""
import argparse, json, os, sys, time
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage, preset, tendia_extraire, pdf_extract
preset.recharger()

PRESETS_ORDRE = ["btp", "ingenierie", "conseil", "formation", "it", "energie_renouvelable"]
LOG = "logs/chantier1_1g_20260614.jsonl"
# DCE pathologiquement volumineux : l'extraction de texte (pdf_extract) y est
# trop lente (ex. 56451 = 3,3 Go) et le texte est de toute façon tronqué à 400k.
# On les ÉCARTE du batch (loggés) pour traitement manuel ultérieur.
TAILLE_MAX_DCE_MO = 500
GEANTS_ECARTES = []


def _dir_size_mo(mid: str) -> float:
    d = os.path.join("data", "dce", mid)
    t = 0
    if os.path.isdir(d):
        for r, _, fs in os.walk(d):
            for f in fs:
                try:
                    t += os.path.getsize(os.path.join(r, f))
                except OSError:
                    pass
    return t / 1e6


def _codes(classifs, mid):
    return [d.get("code") for d in (classifs.get(mid, {}) or {}).get("domaines_metier", [])
            if isinstance(d, dict)]


def _principal(classifs, mid):
    p = preset.presets_pour_domaines(_codes(classifs, mid))
    return p[0] if p else "hors-perimetre"


def construire_ordre():
    m = stockage.charger("marches") or {}
    b = stockage.charger("briefs_extraits") or {}
    classifs = stockage.charger("classifications_ia") or {}
    par_preset = {}
    global GEANTS_ECARTES
    GEANTS_ECARTES = []
    for mid, mk in sorted(m.items()):
        if mk.get("dce_contenu") != "complet":
            continue
        if not os.path.isdir(os.path.join("data", "dce", mid)):
            continue
        if "prompts_versions" in (b.get(mid, {}) or {}).get("_meta", {}):
            continue  # déjà fait
        taille = _dir_size_mo(mid)
        if taille > TAILLE_MAX_DCE_MO:
            GEANTS_ECARTES.append((mid, round(taille)))
            continue  # DCE trop volumineux → écarté du batch (traitement manuel)
        par_preset.setdefault(_principal(classifs, mid), []).append(mid)

    ordre, vus = [], set()
    # 1) un marché par preset (ordre PRESETS_ORDRE = gisement décroissant connu)
    for p in PRESETS_ORDRE:
        if par_preset.get(p):
            mid = par_preset[p][0]
            ordre.append(mid); vus.add(mid)
    # 2) reste des presets par gisement décroissant
    for p in sorted([k for k in par_preset if k != "hors-perimetre"],
                    key=lambda k: -len(par_preset[k])):
        for mid in par_preset[p]:
            if mid not in vus:
                ordre.append(mid); vus.add(mid)
    # 3) hors-périmètre en dernier
    for mid in par_preset.get("hors-perimetre", []):
        if mid not in vus:
            ordre.append(mid); vus.add(mid)
    return ordre, par_preset


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plafond-eur", type=float, default=30.0)
    ap.add_argument("--oui", action="store_true")
    ap.add_argument("--max", type=int, default=None)
    ap.add_argument("--preset", default=None,
                    help="ne traiter QUE les marchés de ce preset principal "
                         "(ex. --preset it pour le complément IT du chantier 1G)")
    args = ap.parse_args()

    classifs_filtre = stockage.charger("classifications_ia") or {}
    ordre, par_preset = construire_ordre()
    if args.preset:
        ordre = [mid for mid in ordre if _principal(classifs_filtre, mid) == args.preset]
    if args.max:
        ordre = ordre[:args.max]
    print("=== RE-EXTRACTION CHANTIER 1 (plafond {:.0f}€) ===".format(args.plafond_eur))
    print("Gisement restant : " + ", ".join(f"{p}={len(par_preset.get(p,[]))}"
          for p in PRESETS_ORDRE + ["hors-perimetre"]))
    print(f"Ordre construit : {len(ordre)} marchés (1/preset puis gisement, HP en dernier)")
    if GEANTS_ECARTES:
        print(f"⚠ {len(GEANTS_ECARTES)} DCE écartés (>{TAILLE_MAX_DCE_MO} Mo, extraction trop lente, "
              f"traitement manuel) : " + ", ".join(f"{mid}({mo}Mo)" for mid, mo in GEANTS_ECARTES))
    if not ordre:
        print("Rien à faire."); return
    if not args.oui:
        try:
            input("Entrée pour lancer (Ctrl+C annule)... ")
        except (EOFError, KeyboardInterrupt):
            print("\nAnnulé."); return

    os.makedirs("logs", exist_ok=True)
    classifs = stockage.charger("classifications_ia") or {}
    cout_cumule = 0.0
    faits = {}
    erreurs = []
    debut = time.time()
    RESERVE = 0.6  # marge pour ne pas dépasser le plafond d'un gros DCE

    for i, mid in enumerate(ordre, 1):
        if cout_cumule + RESERVE >= args.plafond_eur:
            print(f"\n⛔ Plafond {args.plafond_eur:.0f}€ atteint (cumul {cout_cumule:.2f}€) "
                  f"après {i-1} marchés. Arrêt propre.")
            break
        dossier = os.path.join("data", "dce", mid)
        p = _principal(classifs, mid)
        try:
            tendia_extraire._dezipper_dossier(dossier, verbose=False)
            pdfs = pdf_extract.extraire_dossier(dossier, verbose=False)
            if not pdfs:
                erreurs.append((mid, "no pdf")); continue
            res = tendia_extraire.traiter_marche(mid, dossier, pdfs, dry_run=False, verbose=False)
        except Exception as e:
            erreurs.append((mid, f"{type(e).__name__}: {e}"))
            print(f"  [{i}/{len(ordre)}] {mid} ({p}) ❌ {type(e).__name__}")
            continue
        if not res.get("ok"):
            erreurs.append((mid, res.get("erreur") or res.get("raison") or "?"))
            print(f"  [{i}/{len(ordre)}] {mid} ({p}) ❌ {res.get('erreur') or res.get('raison')}")
            continue
        # flag compat + coût
        nb = stockage.lire("briefs_extraits", mid)
        if nb:
            nb["genere_avec_dce_complet"] = True
            stockage.ecrire("briefs_extraits", mid, nb)
        meta = ((res.get("extraction") or {}).get("_meta") or {})
        c = float(meta.get("cout_eur") or 0); cout_cumule += c
        faits[p] = faits.get(p, 0) + 1
        # log flushé
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"i": i, "mid": mid, "preset": p, "cout": c,
                                "cumul": round(cout_cumule, 4),
                                "presets_matches": meta.get("presets_matches")},
                               ensure_ascii=False) + "\n")
        print(f"  [{i}/{len(ordre)}] {mid} ({p}) ✅ {c:.4f}€ | cumul {cout_cumule:.2f}€")

    duree = (time.time() - debut) / 60
    print("\n=== BILAN 1G ===")
    print(f"Marchés re-extraits : {sum(faits.values())} | coût total {cout_cumule:.2f}€ | {duree:.0f} min")
    print("Par preset : " + ", ".join(f"{p}={faits.get(p,0)}" for p in PRESETS_ORDRE + ["hors-perimetre"]))
    if erreurs:
        print(f"Erreurs : {len(erreurs)}")
        for mid, e in erreurs[:8]:
            print(f"  - {mid}: {e}")


if __name__ == "__main__":
    main()
