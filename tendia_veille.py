"""
tendia_veille.py
----------------
Daemon de veille automatisée pour Tendia.

Tourne en boucle infinie, exécute périodiquement une passe complète :
    1. Récupération des nouveaux marchés (tendia_recup, sources par défaut)
    2. Re-matching contre le profil organisme actif
    3. Identification des nouveaux marchés tres_pertinent / pertinent
    4. Écriture d'un journal `data/veille_journal.json`

Les briefs LLM ne sont PAS générés en automatique : ils nécessitent les PDF
du DCE qui doivent être déposés manuellement par l'utilisateur. Le journal
signale les marchés à ouvrir pour déclencher leur extraction.

Usage :
    # Daemon : passe toutes les 6h (défaut), Ctrl+C pour arrêter
    python tendia_veille.py

    # Daemon avec intervalle custom (en heures)
    python tendia_veille.py --intervalle 2

    # One-shot pour test ou pour Windows Task Scheduler
    python tendia_veille.py --une-passe

    # Activer aussi TED pour cette passe (off par défaut)
    python tendia_veille.py --avec-ted
"""

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone

import tendia_recup
import matching
import organisme
import stockage
import connecteurs


# ---------------------------------------------------------------------------
# Journal des passes de veille
# ---------------------------------------------------------------------------

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
JOURNAL_PATH = os.path.join(_BASE_DIR, "data", "veille_journal.json")
JOURNAL_MAX_PASSES = 100  # rolling : on garde les 100 dernières passes


def _charger_journal() -> dict:
    if not os.path.exists(JOURNAL_PATH):
        return {"passes": [], "derniere_passe": None, "ids_pertinents_connus": []}
    try:
        with open(JOURNAL_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"passes": [], "derniere_passe": None, "ids_pertinents_connus": []}


def _sauver_journal(journal: dict) -> None:
    os.makedirs(os.path.dirname(JOURNAL_PATH), exist_ok=True)
    chemin_tmp = JOURNAL_PATH + ".tmp"
    with open(chemin_tmp, "w", encoding="utf-8") as f:
        json.dump(journal, f, ensure_ascii=False, indent=2)
    os.replace(chemin_tmp, JOURNAL_PATH)


# ---------------------------------------------------------------------------
# Passe de veille (1 cycle)
# ---------------------------------------------------------------------------

def _ts_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ts_court() -> str:
    return datetime.now().strftime("%H:%M:%S")


def executer_passe(avec_ted: bool = False,
                    fenetre_mois: int = 6,
                    mode_complet: bool = True,
                    seuil_complet: str = "tres_pertinent",
                    max_extractions: int = 10,
                    verbose: bool = True) -> dict:
    """Exécute une passe complète de veille.

    Args:
        avec_ted: réactive le connecteur TED (off par défaut)
        fenetre_mois: profondeur d'historique BOAMP/TED
        mode_complet: si True (DÉFAUT), déclenche aussi téléchargement DCE +
            extraction LLM pour les nouveaux marchés détectés. Si False,
            la veille se limite à récup + match + journal (mode léger).
        seuil_complet: verdict minimal pour déclencher l'extraction.
            Valeurs : "tres_pertinent" (recommandé) ou "pertinent".
        max_extractions: cap sur le nombre d'extractions LLM par passe.
            Sécurité anti-facture-surprise (ex: première passe avec backlog
            de 50 marchés des 6 derniers mois). Défaut 10 ≈ 4 €.
        verbose: affiche les logs en console.

    Returns un dict décrivant ce qui s'est passé (à archiver dans le journal).
    """
    debut = time.time()
    ts_passe = _ts_iso()

    if verbose:
        print()
        print("█" * 78)
        print(f"  [{_ts_court()}] TENDIA VEILLE — Passe de veille")
        print("█" * 78)

    # 1) RÉCUPÉRATION
    sources = (connecteurs.sources_disponibles() if avec_ted
                else connecteurs.sources_par_defaut())
    if verbose:
        print(f"  ▸ Étape 1/3 — Récupération sources {sources}")

    nb_avant_recup = len(stockage.charger("marches"))
    try:
        tendia_recup.recuperer_tout(
            fenetre_mois=fenetre_mois,
            sources=sources,
            verbose=False,  # on log nous-mêmes la synthèse
        )
        recup_ok = True
        recup_erreur = None
    except Exception as e:
        recup_ok = False
        recup_erreur = f"{type(e).__name__}: {e}"
        print(f"  ❌ Erreur récupération : {recup_erreur}", file=sys.stderr)

    marches = stockage.charger("marches")
    nb_apres_recup = len(marches)
    nb_nouveaux_marches = max(0, nb_apres_recup - nb_avant_recup)
    if verbose:
        print(f"    Marchés en base : {nb_avant_recup} → {nb_apres_recup} "
              f"(+{nb_nouveaux_marches} nouveaux)")

    # 2) MATCHING contre profil actif
    if verbose:
        print(f"  ▸ Étape 2/3 — Matching contre profil actif")

    profil = organisme.lire_profil()
    if not profil:
        if verbose:
            print(f"    ⚠ Aucun profil actif — matching sauté")
        evaluations = []
        nb_pert_total = 0
        nouveaux_pertinents_ids = []
    else:
        try:
            # Sprint B : briefs passes au matching pour scoring sectoriel.
            briefs = stockage.charger("briefs_extraits") or {}
            evaluations = matching.evaluer_tous(profil, marches, briefs=briefs)
        except Exception as e:
            print(f"  ❌ Erreur matching : {type(e).__name__}: {e}",
                  file=sys.stderr)
            evaluations = []

        # On persiste les évaluations
        matchings_dict = {ev["id_marche"]: ev for ev in evaluations if "id_marche" in ev}
        stockage.sauver("matchings", matchings_dict)

        # Identification des pertinents
        ids_pertinents_actuels = {
            ev["id_marche"] for ev in evaluations
            if ev.get("verdict") in ("tres_pertinent", "pertinent")
        }
        nb_pert_total = len(ids_pertinents_actuels)

        # Différentiel vs dernière passe
        journal = _charger_journal()
        ids_connus = set(journal.get("ids_pertinents_connus") or [])
        nouveaux_pertinents_ids = sorted(ids_pertinents_actuels - ids_connus)

        if verbose:
            print(f"    Pertinents/très_pertinents : {nb_pert_total} "
                  f"(dont {len(nouveaux_pertinents_ids)} nouveaux)")

    # 3) NOTIFICATIONS dans le journal (les briefs LLM se font à la demande)
    if verbose:
        print(f"  ▸ Étape 3/3 — Mise à jour du journal de veille")

    if nouveaux_pertinents_ids and verbose:
        print()
        print(f"    ⚡ {len(nouveaux_pertinents_ids)} nouveaux marchés pertinents :")
        for mid in nouveaux_pertinents_ids[:10]:
            m = marches.get(mid) or {}
            titre = (m.get("titre") or "")[:75]
            print(f"      → [{mid}] {titre}…")
        if len(nouveaux_pertinents_ids) > 10:
            print(f"      … et {len(nouveaux_pertinents_ids) - 10} autres")

    # 4) MODE COMPLET (par défaut) : déclenche le pipeline d'extraction pour
    #    chaque nouveau marché détecté qui dépasse le seuil de pertinence.
    #    Coût indicatif : ~0.40 $/marché LLM. Filtre conservateur par défaut
    #    sur "tres_pertinent" pour ne pas cramer des appels sur des bruits.
    #    Sécurités :
    #      - max_extractions cap le nombre de LLM par passe (anti-surprise)
    #      - skip des marchés dont la date_limite est passée (morts)
    #      - skip si brief déjà en cache (idempotent)
    stats_pipeline = {"tentes": 0, "skip_clos": 0, "skip_cap": 0,
                       "skip_deja_brief": 0,
                       "dce_ok": 0, "dce_echec": 0,
                       "extraction_ok": 0, "extraction_echec": 0}
    ids_a_traiter = []
    if mode_complet and nouveaux_pertinents_ids and evaluations:
        from datetime import date as _date
        ev_par_id = {ev["id_marche"]: ev for ev in evaluations}
        seuils_acceptes = (("tres_pertinent",) if seuil_complet == "tres_pertinent"
                            else ("tres_pertinent", "pertinent"))
        aujourd_hui = _date.today()
        for mid in nouveaux_pertinents_ids:
            ev = ev_par_id.get(mid, {})
            if ev.get("verdict") not in seuils_acceptes:
                continue
            # Skip si date_limite passée (marché clos)
            m = marches.get(mid) or {}
            dl_str = m.get("date_limite_depot") or m.get("date_limite_reponse")
            if dl_str:
                try:
                    dl = _date.fromisoformat(dl_str[:10])
                    if dl < aujourd_hui:
                        stats_pipeline["skip_clos"] += 1
                        continue
                except (ValueError, TypeError):
                    pass
            # Skip si brief déjà en cache (le marché a déjà été extrait
            # auparavant, par exemple via tendia_pipeline.py manuel)
            chemin_brief = os.path.join(_BASE_DIR, "data", "extractions",
                                         f"{mid}.json")
            if os.path.exists(chemin_brief):
                stats_pipeline["skip_deja_brief"] += 1
                continue
            ids_a_traiter.append(mid)

        # Cap pour éviter la facture surprise à la première passe
        if len(ids_a_traiter) > max_extractions:
            stats_pipeline["skip_cap"] = len(ids_a_traiter) - max_extractions
            ids_a_traiter = ids_a_traiter[:max_extractions]

    if mode_complet and ids_a_traiter:
        cout_estime = round(0.40 * len(ids_a_traiter), 2)
        if verbose:
            print()
            print(f"  ▸ Étape 4/4 — Pipeline complet "
                  f"(seuil {seuil_complet}, cap {max_extractions})")
            print(f"    {len(ids_a_traiter)} marché(s) à traiter "
                  f"(DCE + extraction LLM) · coût estimé ~{cout_estime} $")
            if stats_pipeline["skip_clos"]:
                print(f"    {stats_pipeline['skip_clos']} ignoré(s) (date_limite passée)")
            if stats_pipeline["skip_deja_brief"]:
                print(f"    {stats_pipeline['skip_deja_brief']} ignoré(s) (brief déjà en cache)")
            if stats_pipeline["skip_cap"]:
                print(f"    ⚠ {stats_pipeline['skip_cap']} reporté(s) à la prochaine passe (cap)")

        import place_downloader
        import tendia_extraire
        import os as _os

        # Répertoires (consistance avec tendia_pipeline.py)
        rep_dce = _os.path.join(_BASE_DIR, "data", "dce")
        _os.makedirs(rep_dce, exist_ok=True)

        for mid in ids_a_traiter:
            stats_pipeline["tentes"] += 1
            marche = marches.get(mid) or {}
            titre = (marche.get("titre") or "")[:60]
            if verbose:
                print(f"\n    ─ [{mid}] {titre}…")

            # 4a) Téléchargement DCE si URL résolue
            if marche.get("url_dce") and marche.get("dce_qualite") in (
                    "directe", "via_keyword"):
                try:
                    res = place_downloader.telecharger_dce_pour_marche(
                        marche, rep_dce, verbose=False
                    )
                    if res.get("ok"):
                        stats_pipeline["dce_ok"] += 1
                        if verbose:
                            print(f"      ✓ DCE téléchargé "
                                  f"{'(déjà présent)' if res.get('skip') else ''}")
                    else:
                        stats_pipeline["dce_echec"] += 1
                        if verbose:
                            print(f"      ⚠ DCE échec : {res.get('erreur')}")
                        continue
                except Exception as e:
                    stats_pipeline["dce_echec"] += 1
                    if verbose:
                        print(f"      ❌ DCE exception : "
                              f"{type(e).__name__}: {e}")
                    continue
            else:
                stats_pipeline["dce_echec"] += 1
                if verbose:
                    print(f"      ⚠ Pas d'URL DCE résolue, extraction sautée")
                continue

            # 4b) Extraction LLM si DCE local présent
            dossier_dce = _os.path.join(rep_dce, mid)
            if not _os.path.isdir(dossier_dce):
                stats_pipeline["extraction_echec"] += 1
                if verbose:
                    print(f"      ⚠ Dossier DCE absent, extraction sautée")
                continue
            try:
                pdfs = {f: _os.path.join(dossier_dce, f)
                        for f in _os.listdir(dossier_dce)
                        if f.lower().endswith(('.pdf', '.docx', '.xlsx'))
                        and not f.startswith('_')}
                if not pdfs:
                    stats_pipeline["extraction_echec"] += 1
                    if verbose:
                        print(f"      ⚠ Aucun document exploitable")
                    continue
                res_ext = tendia_extraire.traiter_marche(
                    mid, dossier_dce, pdfs, dry_run=False, verbose=False
                )
                if res_ext.get("ok"):
                    stats_pipeline["extraction_ok"] += 1
                    if verbose:
                        print(f"      ✓ Brief LLM extrait")
                else:
                    stats_pipeline["extraction_echec"] += 1
                    if verbose:
                        print(f"      ⚠ Extraction échec : "
                              f"{res_ext.get('erreur')}")
            except Exception as e:
                stats_pipeline["extraction_echec"] += 1
                if verbose:
                    print(f"      ❌ Extraction exception : "
                          f"{type(e).__name__}: {e}")

        if verbose:
            print()
            print(f"    Bilan pipeline : "
                  f"{stats_pipeline['dce_ok']} DCE OK · "
                  f"{stats_pipeline['extraction_ok']} brief OK · "
                  f"{stats_pipeline['dce_echec'] + stats_pipeline['extraction_echec']} échecs")

    duree_s = round(time.time() - debut, 1)

    resume_passe = {
        "ts": ts_passe,
        "duree_s": duree_s,
        "sources": sources,
        "mode_complet": mode_complet,
        "recup_ok": recup_ok,
        "recup_erreur": recup_erreur,
        "nb_marches_total": nb_apres_recup,
        "nb_marches_nouveaux": nb_nouveaux_marches,
        "nb_pertinents_total": nb_pert_total,
        "nb_pertinents_nouveaux": len(nouveaux_pertinents_ids),
        "nouveaux_pertinents_ids": nouveaux_pertinents_ids[:20],
        "pipeline_stats": stats_pipeline if mode_complet else None,
    }

    # Persistance du journal (rolling 100 dernières)
    journal = _charger_journal()
    journal["passes"].append(resume_passe)
    journal["passes"] = journal["passes"][-JOURNAL_MAX_PASSES:]
    journal["derniere_passe"] = ts_passe
    # Mémorise les pertinents connus pour le diff de la prochaine passe
    journal["ids_pertinents_connus"] = sorted(
        {ev["id_marche"] for ev in evaluations
         if ev.get("verdict") in ("tres_pertinent", "pertinent")}
    )
    _sauver_journal(journal)

    if verbose:
        print()
        print(f"  ✅ Passe terminée en {duree_s}s. "
              f"Journal : {JOURNAL_PATH}")

    return resume_passe


# ---------------------------------------------------------------------------
# Boucle daemon
# ---------------------------------------------------------------------------

_stop_demande = False


def _handler_signal(signum, frame):
    global _stop_demande
    _stop_demande = True
    print()
    print(f"  [{_ts_court()}] ⚠ Signal reçu — arrêt après la passe en cours")


def boucle_daemon(intervalle_heures: float = 6.0,
                   avec_ted: bool = False,
                   fenetre_mois: int = 6,
                   mode_complet: bool = True,
                   seuil_complet: str = "tres_pertinent",
                   max_extractions: int = 10):
    """Boucle infinie : passe → sleep → passe → sleep → ..."""
    intervalle_s = int(intervalle_heures * 3600)

    print()
    print("=" * 78)
    print(f"  TENDIA VEILLE — Daemon démarré")
    print("=" * 78)
    print(f"  Intervalle      : {intervalle_heures}h ({intervalle_s}s)")
    print(f"  TED activé      : {'oui' if avec_ted else 'non (BOAMP seul)'}")
    print(f"  Fenêtre recup   : {fenetre_mois} mois")
    if mode_complet:
        print(f"  Mode            : COMPLET (récup + DCE + LLM auto)")
        print(f"  Seuil extraction: {seuil_complet}")
        print(f"  Cap par passe   : {max_extractions} extractions max "
              f"(~{round(0.40 * max_extractions, 1)} $)")
    else:
        print(f"  Mode            : MATCH SEUL (pas de DCE ni LLM auto)")
    print(f"  Journal         : {JOURNAL_PATH}")
    print(f"  Arrêt           : Ctrl+C (après la passe en cours)")
    print("=" * 78)

    # Gestion Ctrl+C propre
    signal.signal(signal.SIGINT, _handler_signal)
    try:
        signal.signal(signal.SIGTERM, _handler_signal)
    except (AttributeError, ValueError):
        pass

    n_passes = 0
    while not _stop_demande:
        n_passes += 1
        try:
            executer_passe(avec_ted=avec_ted,
                           fenetre_mois=fenetre_mois,
                           mode_complet=mode_complet,
                           seuil_complet=seuil_complet,
                           max_extractions=max_extractions,
                           verbose=True)
        except Exception as e:
            print(f"  ❌ Erreur passe : {type(e).__name__}: {e}",
                  file=sys.stderr)
            import traceback
            traceback.print_exc()

        if _stop_demande:
            break

        prochaine = datetime.now() + (datetime.now() - datetime.now())
        # Affichage simple de la prochaine passe
        from datetime import timedelta
        prochaine = datetime.now() + timedelta(seconds=intervalle_s)
        print()
        print(f"  [{_ts_court()}] ⏱ Prochaine passe à "
              f"{prochaine.strftime('%H:%M:%S')} "
              f"(dans {intervalle_heures}h). Ctrl+C pour stopper.")

        # Sleep découpé pour réagir au Ctrl+C plus vite
        reste = intervalle_s
        while reste > 0 and not _stop_demande:
            chunk = min(30, reste)  # vérifie toutes les 30s
            time.sleep(chunk)
            reste -= chunk

    print()
    print("=" * 78)
    print(f"  TENDIA VEILLE — Daemon arrêté après {n_passes} passe(s)")
    print("=" * 78)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Daemon de veille Tendia. Pipeline complet par défaut "
                    "(récup BOAMP + matching + téléchargement DCE + extraction LLM). "
                    "Utilise --match-seul pour le mode léger."
    )
    parser.add_argument("--intervalle", type=float, default=6.0,
                        help="Intervalle entre passes en heures (défaut 6).")
    parser.add_argument("--une-passe", action="store_true",
                        help="Exécute une seule passe puis quitte "
                             "(pour test ou Windows Task Scheduler).")
    parser.add_argument("--avec-ted", action="store_true",
                        help="Active aussi le connecteur TED (off par défaut).")
    parser.add_argument("--mois", type=int, default=6,
                        help="Fenêtre de récupération en mois (défaut 6).")
    parser.add_argument("--match-seul", action="store_true",
                        help="Mode léger : récup + matching seulement, pas de "
                             "téléchargement DCE ni d'extraction LLM. Utile pour "
                             "tester ou si on veut piloter le pipeline manuellement.")
    parser.add_argument("--seuil-complet", choices=("tres_pertinent", "pertinent"),
                        default="tres_pertinent",
                        help="Seuil de verdict pour déclencher l'extraction "
                             "(défaut: tres_pertinent, conservateur).")
    parser.add_argument("--max-extractions", type=int, default=10,
                        help="Nombre max d'extractions LLM par passe (défaut 10). "
                             "Anti-facture-surprise à la première passe avec backlog. "
                             "Les marchés en trop sont reportés à la passe suivante.")
    args = parser.parse_args()

    mode_complet = not args.match_seul

    if args.une_passe:
        executer_passe(avec_ted=args.avec_ted,
                       fenetre_mois=args.mois,
                       mode_complet=mode_complet,
                       seuil_complet=args.seuil_complet,
                       max_extractions=args.max_extractions,
                       verbose=True)
    else:
        boucle_daemon(intervalle_heures=args.intervalle,
                      avec_ted=args.avec_ted,
                      fenetre_mois=args.mois,
                      mode_complet=mode_complet,
                      seuil_complet=args.seuil_complet,
                      max_extractions=args.max_extractions)


if __name__ == "__main__":
    main()
