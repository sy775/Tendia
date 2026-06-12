"""
enrichir_complet.py
-------------------
Orchestrateur d'enrichissement COMPLET des marchés pertinents.

Pipeline pour chaque marché pertinent ayant une url_dce exploitable :
  1. Téléchargement du DCE (tendia_telecharger_dce._telecharger_marche)
  2. Si réussi, extraction LLM (tendia_extraire.traiter_marche)
  3. Le brief COMPLET remplace automatiquement le LIGHT en base SQLite
     (grâce à la modif de tendia_extraire vue précédemment).

Le budget LLM est respecté (kill-switch et quotas via budget.py).

CLI :
    python enrichir_complet.py                  # tous les marchés pertinents
    python enrichir_complet.py --dry-run        # simule sans appel API
    python enrichir_complet.py --limite 5       # max 5 marchés
    python enrichir_complet.py --max-cout 2.0   # arrête si coût > 2€
    python enrichir_complet.py --force          # ré-extrait même si déjà fait

Sortie : rapport détaillé indiquant pour chaque marché le statut à chaque
étape (téléchargement, extraction). À la fin, taux de succès agrégé pour
décider de la stratégie UI (filtre strict vs hybride).
"""

import io
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Force UTF-8 sur stdout (Windows cp1252)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import stockage
import analyse


# Qualités d'URL DCE considérées comme exploitables pour téléchargement auto
QUALITES_EXPLOITABLES = {"directe", "via_keyword"}


def _candidats() -> list:
    """
    Liste les marchés pertinents qui ont une url_dce de qualité exploitable.
    Retourne une liste de tuples (mid, marche).
    """
    marches = stockage.charger("marches")
    pertinents = analyse._ids_marches_pertinents()
    cands = []
    for mid in sorted(pertinents):
        m = marches.get(mid)
        if not m:
            continue
        if not m.get("url_dce"):
            continue
        if m.get("dce_qualite") not in QUALITES_EXPLOITABLES:
            continue
        cands.append((mid, m))
    return cands


def _candidats_mutualises() -> list:
    """
    Mode MUTUALISÉ : tous les marchés avec une url_dce de qualité exploitable,
    indépendamment du matching preset. Permet de constituer une base de briefs
    multi-secteurs pour servir plusieurs profils clients à coût marginal nul.
    """
    marches = stockage.charger("marches") or {}
    cands = []
    for mid in sorted(marches.keys()):
        m = marches[mid]
        if not m.get("url_dce"):
            continue
        if m.get("dce_qualite") not in QUALITES_EXPLOITABLES:
            continue
        cands.append((mid, m))
    return cands


def _briefs_complet_existants() -> set:
    """Set d'ids de marchés qui ont déjà un brief COMPLET en base SQLite."""
    import auto_brief
    briefs = stockage.charger("briefs_extraits")
    return {mid for mid, b in briefs.items() if auto_brief.est_brief_complet(b)}


def enrichir(limite: Optional[int] = None,
              dry_run: bool = False,
              force: bool = False,
              max_cout_eur: Optional[float] = None,
              ids: Optional[list] = None,
              mutualise: bool = False,
              prioriser_presets: Optional[list] = None,
              verbose: bool = True) -> dict:
    """
    Pour chaque marché pertinent avec URL DCE exploitable :
      a. Télécharge le DCE
      b. Si réussi, lance l'extraction LLM (brief COMPLET)

    Args:
        prioriser_presets: liste ordonnée de codes presets pour prioriser le
            traitement. Les marchés dont la classification IA matche le 1er
            preset de la liste passent en premier, puis le 2e, etc.
            Les marchés non matchés par les presets prioritaires sont mis
            à la fin.

    Returns:
        stats dict avec compteurs et coût total.
    """
    import requests
    import tendia_telecharger_dce as tdce
    import tendia_extraire as textr

    # --id (comme --mutualise) court-circuite le filtre "pertinent" : un marché
    # ciblé explicitement par son id doit pouvoir être (re)briefé même s'il n'est
    # pas (ou plus) classé pertinent. On part alors de la base non filtrée, puis
    # l'intersection --id ci-dessous restreint aux marchés demandés.
    cands = _candidats_mutualises() if (mutualise or ids) else _candidats()
    if ids:
        ids_set = set(ids)
        cands = [(mid, m) for (mid, m) in cands if mid in ids_set]

    # Priorisation par preset (Sprint 2) : on classe les candidats selon la
    # liste prioriser_presets. Marchés du 1er preset en tête, puis 2e, etc.
    # Marchés sans match dans la liste prioritaire vont à la fin.
    if prioriser_presets:
        scores = stockage.charger("scores_matching") or {}
        def rang_priorite(mid: str) -> int:
            for i, preset_code in enumerate(prioriser_presets):
                cle = f"{mid}__{preset_code}"
                entree = scores.get(cle)
                if entree and entree.get("matche"):
                    return i  # 0 pour le 1er preset, 1 pour le 2e, etc.
            return len(prioriser_presets)  # non matché par les prioritaires
        cands = sorted(cands, key=lambda x: rang_priorite(x[0]))

    briefs_existants = _briefs_complet_existants()

    if verbose:
        print()
        print("=" * 78)
        if mutualise:
            print("  Tendia · Enrichissement MUTUALISÉ (tous secteurs, base SaaS)")
        else:
            print("  Tendia · Enrichissement COMPLET des marchés pertinents")
        print("=" * 78)
        if mutualise:
            print(f"  Marchés avec URL DCE exploitable             : {len(cands)}")
            print(f"    (filtre preset DÉSACTIVÉ — tous secteurs)")
        else:
            print(f"  Marchés pertinents avec URL DCE exploitable : {len(cands)}")
        print(f"  Briefs COMPLET déjà en cache                  : "
              f"{sum(1 for mid, _ in cands if mid in briefs_existants)}")
        if dry_run:
            print(f"  Mode dry-run : AUCUN téléchargement, AUCUN appel LLM.")
        if prioriser_presets:
            print(f"  Priorisation par preset                       : "
                  f"{' → '.join(prioriser_presets)} → autres")
            # Décompte par groupe de priorité pour transparence
            scores_dbg = stockage.charger("scores_matching") or {}
            for i, pc in enumerate(prioriser_presets):
                n = sum(1 for mid, _ in cands
                        if scores_dbg.get(f"{mid}__{pc}", {}).get("matche"))
                print(f"      · {pc:<25} : {n} marchés")
            n_autres = sum(1 for mid, _ in cands
                          if not any(scores_dbg.get(f"{mid}__{pc}", {}).get("matche")
                                     for pc in prioriser_presets))
            print(f"      · autres                  : {n_autres} marchés")
        if limite:
            print(f"  Limite                                        : {limite}")
        if max_cout_eur is not None:
            print(f"  Garde-fou coût                                : {max_cout_eur} €")
        if force:
            print(f"  Force : ré-extrait même si brief COMPLET existe")
        print()

    stats = {
        "candidats_total": len(cands),
        "deja_complet_skip": 0,
        # Téléchargement
        "dl_ok": 0,
        "dl_skip_deja_fait": 0,
        "dl_manuel_requis": 0,
        "dl_echec": 0,
        # Extraction LLM
        "extract_ok": 0,
        "extract_echec": 0,
        "extract_pas_pdf": 0,
        "extract_pdfs_non_dce": 0,  # PDFs téléchargés mais juste guides/DUME
        # Coût
        "cout_total_eur": 0.0,
        # Détail par marché
        "par_marche": [],
        "stoppe_garde_fou_cout": False,
        "dry_run": dry_run,
    }

    # Session HTTP partagée (cookies, etc.)
    session = requests.Session() if not dry_run else None

    traites = 0
    for i, (mid, marche) in enumerate(cands, 1):
        if limite and traites >= limite:
            if verbose:
                print(f"  → Limite de {limite} atteinte, arrêt.")
            break
        # Garde-fou coût
        if max_cout_eur is not None and stats["cout_total_eur"] >= max_cout_eur:
            if verbose:
                print(f"  → Garde-fou coût atteint ({stats['cout_total_eur']:.2f}€ "
                      f"≥ {max_cout_eur}€), arrêt.")
            stats["stoppe_garde_fou_cout"] = True
            break

        titre = (marche.get("titre") or "")[:65]
        if verbose:
            print(f"  [{i}/{len(cands)}] {mid}")
            print(f"      {titre}")
            print(f"      url_dce : {(marche.get('url_dce') or '')[:90]}")

        detail = {"id": mid, "titre": titre}

        # Skip si brief COMPLET déjà présent (sauf force)
        if not force and mid in briefs_existants:
            stats["deja_complet_skip"] += 1
            detail["statut"] = "deja_complet"
            stats["par_marche"].append(detail)
            if verbose:
                print(f"      → ⊘ brief COMPLET déjà présent, skip")
            continue

        traites += 1

        if dry_run:
            detail["statut"] = "dry_run"
            stats["par_marche"].append(detail)
            if verbose:
                print(f"      → [dry-run] téléchargement + extraction simulés")
            continue

        # === Étape 1 : téléchargement DCE ===
        if verbose:
            print(f"      [{datetime.now().strftime('%H:%M:%S')}] téléchargement en cours...", flush=True)
        t_dl = time.time()
        try:
            res_dl = tdce._telecharger_marche(marche, session=session,
                                                force=force, dry_run=False,
                                                verbose=verbose)
        except Exception as e:
            res_dl = {"statut": "erreur", "raison": f"{type(e).__name__}: {e}"}
        duree_dl = time.time() - t_dl

        statut_dl = res_dl.get("statut")
        detail["dl_statut"] = statut_dl
        detail["dl_nb_fichiers"] = res_dl.get("nb_fichiers", 0)
        detail["dl_raison"] = res_dl.get("raison", "")

        if statut_dl == "ok":
            stats["dl_ok"] += 1
            if verbose:
                print(f"      → ✓ téléchargement OK en {duree_dl:.0f}s "
                      f"({res_dl.get('nb_fichiers', 0)} fichier(s))", flush=True)
        elif statut_dl == "skip_deja_fait":
            stats["dl_skip_deja_fait"] += 1
            if verbose:
                print(f"      → ⊘ déjà téléchargé ({res_dl.get('nb_fichiers', 0)} fichier(s))", flush=True)
        elif statut_dl == "manuel_requis":
            stats["dl_manuel_requis"] += 1
            detail["statut"] = "dl_manuel_requis"
            stats["par_marche"].append(detail)
            if verbose:
                print(f"      → ⚠ manuel requis : {res_dl.get('raison', '')}", flush=True)
            continue
        else:
            stats["dl_echec"] += 1
            detail["statut"] = "dl_echec"
            stats["par_marche"].append(detail)
            if verbose:
                print(f"      → ❌ téléchargement échec : "
                      f"{statut_dl} - {res_dl.get('raison', '')[:80]}", flush=True)
            continue

        # === Étape 2 : extraction LLM ===
        # Scan du dossier pour récupérer les PDFs
        scan = textr._scanner_dossiers_dce(force=True, verbose=False)
        match = [t for t in scan if t[0] == mid]
        if not match:
            stats["extract_pas_pdf"] += 1
            detail["statut"] = "extract_pas_pdf"
            stats["par_marche"].append(detail)
            if verbose:
                print(f"      → ⚠ téléchargé mais pas de PDF exploitable", flush=True)
            continue

        _, dossier, pdfs, _raison = match[0]

        if verbose:
            taille = sum(p.get('taille_chars', 0) for p in pdfs.values())
            print(f"      [{datetime.now().strftime('%H:%M:%S')}] extraction LLM "
                  f"({len(pdfs)} PDF(s), {taille:,} chars)...", flush=True)
        t_ext = time.time()
        try:
            res_ext = textr.traiter_marche(mid, dossier, pdfs,
                                              dry_run=False, verbose=verbose)
        except Exception as e:
            res_ext = {"ok": False, "erreur": f"{type(e).__name__}: {e}"}
        duree_ext = time.time() - t_ext

        if res_ext.get("ok"):
            stats["extract_ok"] += 1
            detail["statut"] = "ok_complet"
            extraction = res_ext.get("extraction") or {}
            meta = extraction.get("_meta") or {}
            cout = meta.get("cout_eur")
            # Fallback : si l'extraction n'a pas remonté le coût dans _meta,
            # on va le chercher dans la collection llm_appels (source de vérité
            # budgétaire).
            if cout is None:
                appels = stockage.charger("llm_appels")
                # Dernier appel "ok" extraction pour ce marché
                appels_marche = [
                    a for a in appels.values()
                    if a.get("marche_id") == mid
                    and a.get("type") == "extraction"
                    and a.get("statut") == "ok"
                ]
                if appels_marche:
                    dernier = max(appels_marche, key=lambda a: a.get("appele_le", ""))
                    cout = dernier.get("cout_eur") or 0.0
                else:
                    cout = 0.0
            cout = float(cout or 0)
            detail["cout_eur"] = cout
            stats["cout_total_eur"] += cout
            if verbose:
                print(f"      → ✅ brief COMPLET généré en {duree_ext:.0f}s "
                      f"({cout:.3f} €)", flush=True)
        elif res_ext.get("raison") == "pdfs_non_dce":
            # Cas spécifique : PDFs téléchargés mais que des guides/DUME.
            # Aucun appel LLM n'a eu lieu, pas de coût. Le marché nécessite
            # un téléchargement manuel du vrai DCE.
            stats["extract_pdfs_non_dce"] += 1
            detail["statut"] = "pdfs_non_dce"
            if verbose:
                print(f"      → ⊘ téléchargement OK mais que des guides/DUME, "
                      f"vrai DCE manuel requis", flush=True)
        else:
            stats["extract_echec"] += 1
            detail["statut"] = "extract_echec"
            detail["extract_erreur"] = res_ext.get("erreur", "?")
            if verbose:
                print(f"      → ❌ extraction LLM échec : "
                      f"{res_ext.get('erreur', '?')[:80]}", flush=True)

        stats["par_marche"].append(detail)

    # === Synthèse ===
    if verbose:
        print()
        print("-" * 78)
        print("  Synthèse")
        print("-" * 78)
        n = len(cands)
        print(f"  Candidats (pertinents + url_dce exploitable) : {n}")
        if not dry_run:
            print(f"  Déjà complet (skip)                          : "
                  f"{stats['deja_complet_skip']}")
            print(f"  Téléchargements :")
            print(f"      OK                                       : {stats['dl_ok']}")
            print(f"      déjà fait (skip)                         : {stats['dl_skip_deja_fait']}")
            print(f"      manuel requis (login)                    : {stats['dl_manuel_requis']}")
            print(f"      échec                                    : {stats['dl_echec']}")
            print(f"  Extractions LLM :")
            print(f"      OK (brief COMPLET généré)                : {stats['extract_ok']}")
            print(f"      pas de PDF exploitable                   : {stats['extract_pas_pdf']}")
            print(f"      PDFs non-DCE (guides/dume)               : {stats['extract_pdfs_non_dce']}")
            print(f"      échec                                    : {stats['extract_echec']}")
            print()
            print(f"  Coût total LLM                               : "
                  f"{stats['cout_total_eur']:.3f} €")

            # Ratio final actionnable
            avec_complet = stats["extract_ok"] + stats["deja_complet_skip"]
            if n > 0:
                pct = 100 * avec_complet / n
                print()
                print(f"  ⇒ {avec_complet}/{n} marchés avec brief COMPLET ({pct:.0f}%)")
                if pct >= 70:
                    print(f"  → Stratégie UI suggérée : filtre strict (>= 70% OK)")
                elif pct >= 40:
                    print(f"  → Stratégie UI suggérée : hybride (badges COMPLET/LIGHT)")
                else:
                    print(f"  → Stratégie UI suggérée : tout afficher, tri par richesse brief")

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Enrichissement COMPLET des marchés pertinents : "
                    "téléchargement DCE + extraction LLM."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Simule sans téléchargement ni appel LLM.")
    parser.add_argument("--limite", type=int, default=None,
                        help="Maximum de marchés à traiter dans cette passe.")
    parser.add_argument("--max-cout", type=float, default=None,
                        metavar="EUR",
                        help="Garde-fou : stoppe si le coût LLM dépasse ce montant.")
    parser.add_argument("--force", action="store_true",
                        help="Ré-extrait même si brief COMPLET déjà en cache.")
    parser.add_argument("--id", action="append", dest="ids", default=None,
                        metavar="BOAMP-26-XXXXX",
                        help="Limite à un (ou plusieurs --id ...) marché(s) spécifique(s). "
                             "Utile pour tester le pipeline sur 1 marché avant de tout enrichir.")
    parser.add_argument("--mutualise", action="store_true",
                        help="Mode MUTUALISÉ : briefe TOUS les marchés avec un DCE "
                             "exploitable, sans filtre preset. Permet de constituer "
                             "une base de briefs multi-secteurs servable à plusieurs "
                             "clients (modèle SaaS).")
    parser.add_argument("--prioriser", action="append", default=None,
                        metavar="PRESET",
                        help="Priorise le traitement par preset (utiliser plusieurs "
                             "--prioriser pour ordonner). Ex: "
                             "--prioriser energie_renouvelable --prioriser btp --prioriser formation "
                             "→ les marchés énergie sont briefés en 1er, puis BTP, "
                             "puis formation, puis le reste.")
    args = parser.parse_args()

    enrichir(limite=args.limite,
              dry_run=args.dry_run,
              force=args.force,
              max_cout_eur=args.max_cout,
              ids=args.ids,
              mutualise=args.mutualise,
              prioriser_presets=args.prioriser,
              verbose=True)


if __name__ == "__main__":
    main()
