"""
scripts/decp/maj_hebdo.py — mise à jour hebdomadaire DECP, IDEMPOTENTE (Sprint DECP-R).

Différentiel depuis la dernière date ingérée (moins 45 jours de recouvrement, pour absorber
les publications tardives et les modifications de contrats anciens) :
  1. intègre les lots Batch de classification terminés (semaine précédente) ;
  2. API DECP toutes versions depuis la date de reprise → UPSERT decp_marches / decp_titulaires
     (colonnes source seulement : doublon_de, doublon_possible, classification jamais écrasés) ;
  3. dédoublonnage R1-R4 + doublons possibles (rejouable) ;
  4. classification CPV gratuite des nouveaux contrats, puis IA (Batch) des nouveaux contrats
     du pré-filtre sous l'enveloppe MENSUELLE decp_hebdo (data/budget.json), plus récents d'abord ;
  5. propagation de la classification aux doublons ;
  6. acheteur_siren manquants (correspondances sûres) + rapprochement des attributions.
Un verrou (fichier) empêche deux exécutions simultanées. Journal : data/decp_reprise/maj_hebdo/.

Lancement manuel : python scripts/decp/maj_hebdo.py [--sans-ia] [--dry-run]
"""
import argparse
import contextlib
import io
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

RACINE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(RACINE)                      # lancé par le Planificateur de tâches : cwd quelconque
sys.path.insert(0, RACINE)
sys.path.insert(0, os.path.join(RACINE, "scripts", "decp"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DOSSIER = os.path.join("data", "decp_reprise", "maj_hebdo")
ETAT = os.path.join(DOSSIER, "etat.json")
VERROU = os.path.join(DOSSIER, "verrou")
RECOUVREMENT_JOURS = 45
ENVELOPPE_HEBDO = "decp_hebdo"


def _log(msg, f):
    ligne = f"[{datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(ligne, flush=True)
    f.write(ligne + "\n")
    f.flush()


def _date_reprise(etat):
    import sqlite3
    from tendia.core import stockage
    ref = etat.get("derniere_date_source")
    if not ref:
        con = sqlite3.connect(f"file:{stockage.chemin_db()}?mode=ro", uri=True)
        ref = con.execute("SELECT MAX(date_notification) FROM decp_marches").fetchone()[0]
        con.close()
    return (date.fromisoformat(ref[:10]) - timedelta(days=RECOUVREMENT_JOURS)).isoformat()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sans-ia", action="store_true", help="pas de classification IA (CPV seulement)")
    ap.add_argument("--dry-run", action="store_true", help="téléchargement + comptage, aucune écriture")
    args = ap.parse_args()
    os.makedirs(DOSSIER, exist_ok=True)
    if os.path.exists(VERROU) and time.time() - os.path.getmtime(VERROU) < 12 * 3600:
        print("⛔ une mise à jour est déjà en cours (verrou < 12 h) — arrêt.")
        sys.exit(1)
    open(VERROU, "w").write(str(os.getpid()))
    etat = json.load(open(ETAT, encoding="utf-8")) if os.path.exists(ETAT) else {}
    journal = open(os.path.join(DOSSIER, f"maj_{date.today().isoformat()}.log"), "a", encoding="utf-8")
    resume = {"debut": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        from tendia.core import budget
        from decp import classif_batch as B
        from decp import telecharger
        from decp.ingest_v2 import ingerer_lignes_api
        B.ENV = ENVELOPPE_HEBDO

        class A:   # arguments factices pour les commandes de classif_batch
            annees = None; max_jobs = None; dry_run = args.dry_run; pause = 60

        if not args.dry_run:
            _log("1. intégration des lots Batch terminés", journal)
            with contextlib.redirect_stdout(io.StringIO()) as buf:
                B.cmd_suivre(A)
            _log(buf.getvalue().strip().replace("\n", " | ")[:500], journal)

        depuis = _date_reprise(etat)
        _log(f"2. API DECP toutes versions depuis {depuis}", journal)
        r = telecharger.fetch_toutes_versions(depuis, verbose=False)
        resume.update(depuis=depuis, lignes_api=len(r["lignes"]), pages_en_echec=r["pages_en_echec_final"])
        _log(f"   {len(r['lignes'])} lignes, pages en échec : {r['pages_en_echec_final']}", journal)
        if args.dry_run:
            _log("   [dry-run] aucune écriture", journal)
            return
        st = ingerer_lignes_api(r["lignes"])
        resume["ingestion"] = st
        _log(f"   ingestion : {st}", journal)
        dates = [str(x.get("dateNotification") or "")[:10] for x in r["lignes"] if x.get("dateNotification")]
        if dates and not r["pages_en_echec_final"]:
            etat["derniere_date_source"] = max(dates)

        _log("3. dédoublonnage (R1-R4 + doublons possibles)", journal)
        import reprise_doublons_regle as R
        sys_argv = sys.argv
        sys.argv = ["reprise_doublons_regle.py", "--appliquer", "--exemples",
                    os.path.join(DOSSIER, "doublons_exemples_derniere_maj.csv")]
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            R.main()
        sys.argv = sys_argv
        _log("   " + " | ".join(l.strip() for l in buf.getvalue().splitlines() if "marqu" in l or "✅" in l), journal)

        _log("4. classification (CPV gratuite puis IA Batch sous l'enveloppe decp_hebdo)", journal)
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            B.cmd_base(A)
            if not args.sans_ia:
                B.cmd_soumettre(A)
        _log("   " + buf.getvalue().strip().replace("\n", " | ")[:600], journal)
        resume["depense_decp_hebdo_mois"] = budget.depense_enveloppe(ENVELOPPE_HEBDO)

        _log("5. propagation aux doublons", journal)
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            B.cmd_propager(A)
        _log("   " + buf.getvalue().strip(), journal)

        _log("6. acheteurs + attributions", journal)
        import attributions as AT

        class X:
            appliquer = True
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            AT.cmd_acheteurs(X)
            AT.cmd_rapprocher(X)
        _log("   " + " | ".join(l.strip() for l in buf.getvalue().splitlines()
                                  if l.startswith(("acheteur_siren", "attributions", "✅")))[:600], journal)
        resume["fin"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        etat["derniere_execution"] = resume
        json.dump(etat, open(ETAT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        _log("✅ mise à jour terminée", journal)
    except Exception as e:
        _log(f"⛔ ÉCHEC : {type(e).__name__}: {e}", journal)
        raise
    finally:
        journal.close()
        try:
            os.remove(VERROU)
        except OSError:
            pass


if __name__ == "__main__":
    main()
