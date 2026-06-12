"""
calibrer_briefs.py
------------------
Lance la calibration prix (top-down DECP + bottom-up, ou bottom-up seul si
pas de DECP en base) sur les briefs COMPLET existants.

Mode 'auto' par défaut : si DECP est ingéré, fait la calibration complète
triangulée. Sinon fait un bottom-up seul (basé sur le brief + barèmes preset).
Coût : ~0,05-0,10 €/brief en bottom-up, ~0,05-0,10 € en triangulé.

Usage :
    python calibrer_briefs.py                          # tous les briefs COMPLET
    python calibrer_briefs.py --id BOAMP-26-56729      # un brief précis
    python calibrer_briefs.py --force                  # ignore cache
    python calibrer_briefs.py --mode bottom_up         # force bottom-up (ignore DECP)
    python calibrer_briefs.py --mode triangule         # force triangulé (échoue si pas DECP)
    python calibrer_briefs.py --dry-run                # liste sans appeler le LLM
"""

import argparse
import io
import json
import sys
import time
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import stockage
import llm_calibration


REPERTOIRE_BASE = Path(__file__).parent
REPERTOIRE_EXTRACTIONS = REPERTOIRE_BASE / "data" / "extractions"
REPERTOIRE_CALIBRATIONS = REPERTOIRE_BASE / "data" / "extractions_calibrees"


def _charger_briefs() -> dict:
    """Charge briefs SQLite + fallback disque."""
    briefs = {}
    try:
        briefs = dict(stockage.charger("briefs_extraits") or {})
    except Exception as e:
        print(f"  ⚠ Erreur SQLite : {e}")
    if REPERTOIRE_EXTRACTIONS.exists():
        for f in REPERTOIRE_EXTRACTIONS.glob("*.json"):
            id_m = f.stem
            if id_m not in briefs:
                try:
                    briefs[id_m] = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    pass
    return briefs


def _type_brief(brief: dict) -> str:
    meta = brief.get("_meta") or {}
    t = (meta.get("type") or "").upper()
    if t in ("COMPLET", "LIGHT"):
        return t
    if any(k in brief for k in ("criteres_attribution", "modalites_consultation",
                                  "duree_estimee", "volume_estime",
                                  "bareme_notation", "alertes_candidat")):
        return "COMPLET"
    return "INCONNU"


def _resume_calibration(calib: dict) -> str:
    """Retourne une ligne synthétique pour afficher le résultat."""
    if not calib:
        return "(échec ou impossible)"
    if calib.get("calibration_impossible_raison"):
        return f"impossible : {calib['calibration_impossible_raison'][:80]}"
    pu = calib.get("prix_unitaire_estime") or {}
    if not pu or pu.get("mediane_eur") is None:
        return "(prix unitaire null)"
    mediane = pu.get("mediane_eur")
    unite = pu.get("unite") or "?"
    confiance = pu.get("confiance") or "?"
    mode = (calib.get("_meta") or {}).get("mode") or calib.get("_mode_calibration") or "?"
    return f"{mediane:>6} €/{unite}  [{mode}, conf={confiance}]"


def _afficher_detail(calib: dict, id_marche: str):
    """Affichage détaillé d'une calibration."""
    print(f"\n  ── Calibration {id_marche} ──")
    if not calib:
        print(f"  ✗ Calibration null")
        return
    raison_impossible = calib.get("calibration_impossible_raison")
    if raison_impossible:
        print(f"  ⚠ Impossible : {raison_impossible}")
        return

    pu = calib.get("prix_unitaire_estime") or {}
    meta = calib.get("_meta") or {}

    print(f"  Mode               : {meta.get('mode') or '?'}")
    if meta.get("note"):
        print(f"                       ↳ {meta['note']}")
    print(f"  Comparables utilisés: {meta.get('n_comparables_utilises', 0)}")

    print(f"\n  Prix unitaire estimé:")
    print(f"    Unité             : {pu.get('unite') or '?'}")
    print(f"    Médiane           : {pu.get('mediane_eur') or '?'} €")
    print(f"    Fourchette        : "
          f"{pu.get('min_eur') or '?'} – {pu.get('max_eur') or '?'} €")
    print(f"    Méthode fourchette: {pu.get('methode_fourchette') or '?'}")
    print(f"    Confiance         : {pu.get('confiance') or '?'}")

    bu = pu.get("bottom_up") or {}
    if bu:
        print(f"\n  Bottom-up :")
        for k in ("qualification_intervenants", "cout_horaire_retenu_eur",
                   "heures_effectives_par_beneficiaire",
                   "heures_effectives_par_unite",
                   "coef_complexite", "fourchette_eur"):
            v = bu.get(k)
            if v:
                print(f"    {k:<35} : {v}")
        if bu.get("calcul"):
            print(f"    calcul :")
            for ligne in str(bu["calcul"]).split("\n")[:8]:
                print(f"      {ligne[:120]}")

    ur = pu.get("unit_repricing") or {}
    if ur and not ur.get("_commentaire", "").startswith("OBLIGATOIRE"):
        print(f"\n  Unit repricing (BPU non-linéaire) :")
        print(f"    Unité marché     : {ur.get('unite_marche') or '?'}")
        cv = ur.get("cout_variable_par_unite_eur") or \
             ur.get("cout_variable_par_beneficiaire_eur")
        if cv:
            print(f"    Coût variable    : {cv} €/unité")
        if ur.get("calcul_session_type"):
            print(f"    Calcul type      : {ur['calcul_session_type'][:120]}")

    td = pu.get("top_down")
    if td:
        print(f"\n  Top-down (comparables DECP) :")
        print(f"    Médiane observée : {td.get('mediane_observee_eur') or '?'} €")
        print(f"    Q1 / Q3          : "
              f"{td.get('q1_eur') or '?'} / {td.get('q3_eur') or '?'} €")
        print(f"    Comparables util.: {td.get('n_comparables_exploitables') or 0}")
        if td.get("commentaire"):
            print(f"    Commentaire      : {td['commentaire'][:120]}")

    triang = pu.get("triangulation")
    if triang:
        print(f"\n  Triangulation :")
        for ligne in str(triang).split("\n")[:5]:
            print(f"    {ligne[:120]}")

    ft = calib.get("fourchette_marche_total_estimee") or {}
    if ft:
        print(f"\n  Fourchette marché total :")
        print(f"    Min : {ft.get('min_eur') or '?'} €")
        print(f"    Max : {ft.get('max_eur') or '?'} €")
        if ft.get("calcul"):
            print(f"    Calcul : {ft['calcul'][:120]}")
        scenarios = ft.get("scenarios") or {}
        for nom in ("bas", "realiste", "haut"):
            sc = scenarios.get(nom) or {}
            if sc:
                print(f"    {nom:<10} : {sc.get('montant_eur') or '?'} € "
                      f"— {(sc.get('hypothese') or '')[:80]}")

    if pu.get("limites"):
        print(f"\n  Limites :")
        for ligne in str(pu["limites"]).split("\n")[:3]:
            print(f"    {ligne[:120]}")


def _presets_matches_par_marche(scores: dict) -> dict:
    """
    Retourne un dict {id_marche: [preset_code, ...]} listant les presets
    qui ont matché chaque marché.
    """
    par_marche = {}
    for cle, sc in scores.items():
        if not isinstance(sc, dict):
            continue
        # Format Sprint 3 : {preset_code, matche, marche_id} par entrée
        if "preset_code" in sc and "matche" in sc:
            if sc.get("matche"):
                id_m = sc.get("marche_id") or cle.rsplit("_", 1)[0]
                par_marche.setdefault(id_m, []).append(sc["preset_code"])
        else:
            # Format legacy : {preset_code: {matche: ...}}
            for preset_c, sub in sc.items():
                if isinstance(sub, dict) and sub.get("matche"):
                    par_marche.setdefault(cle, []).append(preset_c)
    return par_marche


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", help="ID Tendia d'un marché précis")
    ap.add_argument("--force", action="store_true",
                    help="Ignore le cache et recalibre")
    ap.add_argument("--mode", choices=["auto", "bottom_up", "triangule"],
                    default="auto",
                    help="Mode de calibration (défaut: auto)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Liste les marchés sans appeler le LLM")
    ap.add_argument("--detail", action="store_true",
                    help="Affiche le détail complet de chaque calibration")
    ap.add_argument("--preset-force",
                    help="Force un preset spécifique pour tous les marchés "
                         "(utile pour debug ou marché atypique). "
                         "Par défaut le preset matché par le marché est utilisé.")
    args = ap.parse_args()

    print("=" * 78)
    print("  Calibration prix — Sprint B (bottom-up + top-down)")
    print("=" * 78)

    # Charge tout
    import preset
    marches = stockage.charger("marches") or {}
    briefs = _charger_briefs()
    scores = stockage.charger("scores_matching") or {}
    presets_par_marche = _presets_matches_par_marche(scores)
    try:
        marches_notifies = stockage.charger("marches_notifies") or {}
    except Exception:
        marches_notifies = {}

    has_decp = bool(marches_notifies)
    preset_actif_initial = preset.code_actif()

    print(f"\n  Marchés en base       : {len(marches)}")
    print(f"  Briefs en cache       : {len(briefs)}")
    print(f"  Marchés notifies DECP : {len(marches_notifies)} "
          f"{'✓' if has_decp else '✗ (mode bottom-up activé)'}")
    print(f"  Preset actif (départ) : {preset_actif_initial}")
    if args.preset_force:
        print(f"  Preset forcé          : {args.preset_force}")

    # Sélection
    if args.id:
        if args.id not in briefs:
            print(f"\n  ✗ Aucun brief pour {args.id}")
            return
        a_traiter = {args.id: briefs[args.id]}
    else:
        a_traiter = {k: v for k, v in briefs.items()
                     if _type_brief(v) == "COMPLET"}

    print(f"  Briefs à calibrer     : {len(a_traiter)}")
    if args.mode != "auto":
        print(f"  Mode forcé           : {args.mode}")

    if not a_traiter:
        print("\n  Rien à faire.")
        return

    if args.dry_run:
        print("\n  Mode DRY-RUN — voici les cibles et leur preset :")
        for id_m, brief in sorted(a_traiter.items()):
            titre = (marches.get(id_m, {}).get("titre") or "?")[:55]
            presets_m = presets_par_marche.get(id_m, [])
            presets_str = ", ".join(presets_m) if presets_m else "AUCUN — sera skip"
            print(f"    {id_m}  preset={presets_str}")
            print(f"                     {titre}")
        return

    # Calibration marché par marché
    print(f"\n  Calibration en cours...")
    print(f"  {'─' * 72}")

    nb_ok = 0
    nb_impossible = 0
    nb_erreur = 0
    nb_sans_preset = 0

    profil = None
    if has_decp and args.mode != "bottom_up":
        try:
            import organisme
            profil = organisme.lire_profil()
        except Exception:
            pass

    import concurrence

    try:
        for id_m, brief in sorted(a_traiter.items()):
            marche = marches.get(id_m)
            if not marche:
                print(f"    ⊘ {id_m} : marché absent en base, skip")
                continue

            # Identifie le preset à utiliser pour ce marché
            presets_m = presets_par_marche.get(id_m, [])
            if args.preset_force:
                preset_cible = args.preset_force
            elif presets_m:
                preset_cible = presets_m[0]  # 1er preset matché
                if len(presets_m) > 1:
                    print(f"    ℹ {id_m} : matche {len(presets_m)} presets "
                          f"({', '.join(presets_m)}), utilise {preset_cible}")
            else:
                titre = (marche.get("titre") or "?")[:60]
                print(f"    ⊘ {id_m} : aucun preset matché, skip")
                print(f"           {titre}")
                nb_sans_preset += 1
                continue

            # Basculer si nécessaire
            if preset.code_actif() != preset_cible:
                try:
                    preset.basculer_preset(preset_cible)
                except Exception as e:
                    print(f"    ✗ {id_m} : impossible de basculer sur "
                          f"preset '{preset_cible}' : {e}")
                    nb_erreur += 1
                    continue

            # Reimport llm_calibration pour qu'il prenne le nouveau preset
            import importlib
            importlib.reload(llm_calibration)

            # Calcul zone_prix si DECP dispo
            zone_prix = None
            if has_decp and profil and args.mode != "bottom_up":
                try:
                    zone_prix = concurrence.zone_prix_marche(
                        profil, brief, marche, marches_notifies)
                except Exception as e:
                    print(f"    ⚠ zone_prix échec pour {id_m} : {e}")
                    zone_prix = None

            # Calibration
            debut = time.time()
            try:
                resultat = llm_calibration.calibrer_et_cacher(
                    id_m, brief, zone_prix or {}, marches_notifies,
                    force=args.force, verbose=False, mode=args.mode)
            except Exception as e:
                print(f"    ✗ {id_m} : {type(e).__name__}: {e}")
                nb_erreur += 1
                continue
            duree = time.time() - debut

            if not resultat:
                print(f"    ✗ {id_m} [preset={preset_cible}] : calibration None  "
                      f"({duree:.1f}s)")
                nb_erreur += 1
                continue

            if resultat.get("calibration_impossible_raison"):
                print(f"    ⊘ {id_m} [preset={preset_cible}] : "
                      f"{_resume_calibration(resultat)}")
                nb_impossible += 1
                continue

            print(f"    ✓ {id_m} [preset={preset_cible}] : "
                  f"{_resume_calibration(resultat)}  ({duree:.1f}s)")
            nb_ok += 1

            if args.detail:
                _afficher_detail(resultat, id_m)
    finally:
        # Restaure le preset initial même en cas d'erreur
        if preset.code_actif() != preset_actif_initial:
            try:
                preset.basculer_preset(preset_actif_initial)
                print(f"\n  (Preset restauré : {preset_actif_initial})")
            except Exception:
                pass

    # Synthèse
    print(f"\n  {'─' * 72}")
    print(f"  Synthèse :")
    print(f"    ✓ Calibrations réussies   : {nb_ok}")
    print(f"    ⊘ Impossible (data faible): {nb_impossible}")
    print(f"    ⊘ Sans preset matché      : {nb_sans_preset}")
    print(f"    ✗ Erreurs                 : {nb_erreur}")
    print(f"\n  Calibrations stockées dans : {REPERTOIRE_CALIBRATIONS}")
    print()

    if nb_ok > 0 and not args.detail:
        print(f"  Pour voir le détail d'une calibration :")
        print(f"    python calibrer_briefs.py --id <BOAMP-26-XXXXX> --detail")


if __name__ == "__main__":
    main()
