"""
decp/classif_batch.py — classification DECP complète via l'API Batch de Gemini (Sprint DECP-R).

Variante retenue au pilote v2 : gemini-3.1-flash-lite, prompt v2 complet, 50 contrats par
appel, sortie compacte, sans outil ni réflexion. Batch = -50 % sur le tarif standard
(tarif standard de config_llm.yaml × 0,5 — à rapprocher de la facture).

Commandes (python -m decp.classif_batch <cmd>) :
  base       : classification GRATUITE de tous les contrats non classés par CPV
               (mapping_cpv → famille ; domaine vide). Hors pré-filtre : définitif
               (source cpv_hors_prefiltre) ; dans le pré-filtre : repli en attendant l'IA
               (source cpv_attente_ia).
  estimer    : nombre d'appels et coût estimé par année (pré-filtre, hors doublons, pas encore IA)
  soumettre  : crée les lots Batch par ordre de priorité (2026, 2025, 2024, puis 2023, 2022)
               tant que le coût estimé du lot tient dans le budget restant de l'enveloppe
               (dépense journalisée + estimations des lots en cours).
  suivre     : interroge les lots, intègre les résultats terminés (decp_classification,
               llm_appels avec _meta.cout_eur par requête).
  propager   : copie la classification du contrat conservé vers ses doublons (doublon_de).
  etat       : résumé.
"""
import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import budget
import llm_router
import stockage
from decp import classif_ia as C
from decp import db as decp_db
from decp.mapping_cpv import classer_par_cpv

MODELE = "gemini-3.1-flash-lite"
TAILLE_LOT = 50
REQUETES_PAR_JOB = 300          # ~22 Ko par requête → ~6,6 Mo par job (limite inline 20 Mo)
REMISE_BATCH = 0.5
PRIORITE_ANNEES = ["2026", "2025", "2024", "2023", "2022"]
DOSSIER = "data/decp_reprise/batch"
ETAT = f"{DOSSIER}/etat.json"
SOURCE_IA = "ia_flash_lite_v2"
ENV = C.ENVELOPPE   # enveloppe budget (decp_reprise pendant le sprint ; decp_hebdo ensuite)
# Calibrage tokens (pilote v2, flash_v2_50) : entrée ≈ caractères / CAR_PAR_TOKEN ;
# sortie ≈ 5,9 tokens par contrat + 10.
CAR_PAR_TOKEN = 2.95
TOK_SORTIE_PAR_CONTRAT = 6.0


def _now():
    return datetime.now(timezone.utc).isoformat()


def _etat():
    if os.path.exists(ETAT):
        return json.load(open(ETAT, encoding="utf-8"))
    return {"jobs": []}


def _sauver_etat(e):
    os.makedirs(DOSSIER, exist_ok=True)
    tmp = ETAT + ".tmp"
    json.dump(e, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, ETAT)


def _famille_cpv(cpv):
    p, _ = classer_par_cpv(cpv)
    return C.CORRESPONDANCE_V1.get(p, p) if p else None


# ------------------------------------------------------------------ base CPV
def cmd_base(args):
    con = decp_db.connexion()
    rows = con.execute("""SELECT m.uid, m.cpv_principal, m.objet FROM decp_marches m
                          LEFT JOIN decp_classification c ON c.decp_id = m.uid
                          WHERE c.decp_id IS NULL""").fetchall()
    out, n_pf = [], 0
    for uid, cpv, objet in rows:
        pf = C.dans_prefiltre(cpv, objet)
        n_pf += pf
        fam = _famille_cpv(cpv) or "hors_perimetre"
        out.append((uid, fam, "cpv_attente_ia" if pf else "cpv_hors_prefiltre", None, _now(), None, fam))
    con.executemany("""INSERT INTO decp_classification
                       (decp_id, preset_principal, source, confiance, classified_at, domaine, famille)
                       VALUES (?,?,?,?,?,?,?) ON CONFLICT(decp_id) DO NOTHING""", out)
    con.commit()
    con.close()
    print(f"base CPV : {len(out):,} contrats classés (dont {n_pf:,} en attente d'IA)".replace(",", " "))


# ------------------------------------------------------------------ sélection
def _a_classer(con, annees):
    """Contrats du pré-filtre, non doublons, sans classification IA, par année."""
    q = ("SELECT m.uid, m.objet, m.cpv_principal, m.acheteur_nom, substr(m.date_notification,1,4) "
         "FROM decp_marches m JOIN decp_classification c ON c.decp_id = m.uid "
         "WHERE m.doublon_de IS NULL AND c.source = 'cpv_attente_ia' AND substr(m.date_notification,1,4) = ? "
         "ORDER BY m.uid")
    en_cours = set()
    for j in _etat()["jobs"]:
        if j["statut"] not in ("integre", "echec", "annule"):
            for r in j["requetes"]:
                en_cours.update(r["uids"])
    for an in annees:
        yield an, [r for r in con.execute(q, (an,)) if r[0] not in en_cours]


def _requetes(lignes, systeme):
    reqs = []
    for i in range(0, len(lignes), TAILLE_LOT):
        lot = lignes[i:i + TAILLE_LOT]
        user = C.prompt_utilisateur([{"objet": r[1], "cpv": r[2], "acheteur": r[3]} for r in lot])
        tin = (len(systeme) + len(user)) / CAR_PAR_TOKEN
        tout = TOK_SORTIE_PAR_CONTRAT * len(lot) + 10
        est = (llm_router.estimer_cout_eur(MODELE, int(tin), int(tout)) or 0) * REMISE_BATCH
        reqs.append({"uids": [r[0] for r in lot], "user": user, "estimation_eur": est})
    return reqs


def _engage_eur():
    """Dépense journalisée + estimations des jobs soumis non encore intégrés."""
    dep = budget.depense_enveloppe(ENV)["total_eur"]
    pend = sum(j["estimation_eur"] for j in _etat()["jobs"] if j["statut"] not in ("integre", "echec", "annule"))
    return dep, pend


def cmd_estimer(args):
    con = sqlite3.connect(f"file:{stockage.chemin_db()}?mode=ro", uri=True)
    systeme = C.prompt_systeme("v2")
    tot = 0
    for an, lignes in _a_classer(con, PRIORITE_ANNEES):
        reqs = _requetes(lignes, systeme)
        c = sum(r["estimation_eur"] for r in reqs)
        tot += c
        print(f"  {an} : {len(lignes):>7,} contrats, {len(reqs):>6,} appels, ≈ {c:6.2f} € (Batch)".replace(",", " "))
    dep, pend = _engage_eur()
    env = budget.lire_config()["enveloppes"][ENV]["total_eur"]
    print(f"  TOTAL ≈ {tot:.2f} € ; enveloppe {env} € ; dépensé {dep:.4f} € ; en cours {pend:.4f} € ; "
          f"reste {env - dep - pend:.2f} €")


# ------------------------------------------------------------------ soumission
def cmd_soumettre(args):
    from google.genai import types
    llm_router.charger_env()
    client = llm_router._client_gemini()
    systeme = C.prompt_systeme("v2")
    pv = C.version_prompt("v2")
    con = sqlite3.connect(f"file:{stockage.chemin_db()}?mode=ro", uri=True)
    env = budget.lire_config()["enveloppes"][ENV]["total_eur"]
    annees = args.annees.split(",") if args.annees else PRIORITE_ANNEES
    cfg = types.GenerateContentConfig(system_instruction=systeme, max_output_tokens=TAILLE_LOT * 12 + 200,
                                      temperature=0, thinking_config=types.ThinkingConfig(thinking_budget=0))
    etat = _etat()
    soumis = 0
    for an, lignes in _a_classer(con, annees):
        reqs = _requetes(lignes, systeme)
        for i in range(0, len(reqs), REQUETES_PAR_JOB):
            paquet = reqs[i:i + REQUETES_PAR_JOB]
            est = sum(r["estimation_eur"] for r in paquet)
            dep, pend = _engage_eur()
            budget.verifier_kill_switch("decp")
            if dep + pend + est > env:
                # tente un paquet réduit qui tient dans le reste
                reste = env - dep - pend
                k = 0
                acc = 0.0
                while k < len(paquet) and acc + paquet[k]["estimation_eur"] <= reste * 0.98:
                    acc += paquet[k]["estimation_eur"]
                    k += 1
                if k == 0:
                    print(f"⛔ budget : reste {reste:.4f} € < coût du prochain appel ({an}). Arrêt des soumissions.")
                    _sauver_etat(etat)
                    print(f"{soumis} job(s) soumis.")
                    return
                paquet, est = paquet[:k], acc
            if args.dry_run:
                print(f"  [dry-run] job {an} : {len(paquet)} requêtes, ≈ {est:.4f} €")
                continue
            src = [types.InlinedRequest(
                model=MODELE, contents=[r["user"]], config=cfg,
                metadata={"k": f"{an}-{i + j}"}) for j, r in enumerate(paquet)]
            try:
                job = client.batches.create(model=MODELE, src=src,
                                            config={"display_name": f"tendia-decp-{an}-{i // REQUETES_PAR_JOB}"})
            except Exception as e:
                if "RESOURCE_EXHAUSTED" in str(e) or "429" in str(e):
                    # quota Batch « tokens actifs simultanés » (Tier 1 : 10 M) : on attend que
                    # des jobs se terminent (commande piloter).
                    print("  ⏸ quota de tokens Batch simultanés atteint — reprise après intégration de jobs.")
                    _sauver_etat(etat)
                    print(f"{soumis} job(s) soumis.")
                    return
                raise
            etat["jobs"].append({
                "nom": job.name, "annee": an, "cree_le": _now(), "statut": "soumis",
                "estimation_eur": round(est, 5), "prompt_version": pv,
                "requetes": [{"k": f"{an}-{i + j}", "uids": r["uids"]} for j, r in enumerate(paquet)]})
            _sauver_etat(etat)
            soumis += 1
            print(f"  job {job.name} ({an}) : {len(paquet)} requêtes, {sum(len(r['uids']) for r in paquet)} "
                  f"contrats, ≈ {est:.4f} €", flush=True)
            if args.max_jobs and soumis >= args.max_jobs:
                print(f"{soumis} job(s) soumis (max atteint).")
                return
    print(f"{soumis} job(s) soumis.")


# ------------------------------------------------------------------ suivi / intégration
def _integrer(job_etat, job):
    resp = (job.dest.inlined_responses if job.dest else None) or []
    par_k = {r["k"]: r for r in job_etat["requetes"]}
    con = decp_db.connexion()
    cout_total, n_ok, n_rep = 0.0, 0, 0
    lignes_cl = []
    for ir in resp:
        k = (ir.metadata or {}).get("k")
        req = par_k.get(k)
        if not req:
            continue
        n = len(req["uids"])
        if ir.error or not ir.response:
            budget.enregistrer_appel("decp", 0.0, statut="erreur", modele=MODELE, enveloppe=ENV,
                                     erreur=str(ir.error)[:300], extra={"_meta": {"batch": job_etat["nom"], "k": k}})
            continue
        u = ir.response.usage_metadata
        tin = int(getattr(u, "prompt_token_count", 0) or 0)
        tout = int(getattr(u, "candidates_token_count", 0) or 0) + int(getattr(u, "thoughts_token_count", 0) or 0)
        cout = (llm_router.estimer_cout_eur(MODELE, tin, tout) or 0.0) * REMISE_BATCH
        cout_total += cout
        preds = C.parser_sortie(ir.response.text or "", n)
        meta = {"modele": MODELE, "tokens_in": tin, "tokens_out": tout, "cout_eur": round(cout, 6),
                "batch": job_etat["nom"], "k": k, "n_contrats": n, "lus": len(preds),
                "prompt_version": job_etat["prompt_version"], "remise_batch": REMISE_BATCH}
        budget.enregistrer_appel("decp", cout, statut="ok", tokens_input=tin, tokens_output=tout,
                                 modele=MODELE, enveloppe=ENV, extra={"_meta": meta})
        for idx, uid in enumerate(req["uids"], 1):
            code = preds.get(idx)
            if code:
                fam = C.famille_de(code)
                lignes_cl.append((fam, SOURCE_IA, _now(), code, fam, MODELE, job_etat["prompt_version"], uid))
                n_ok += 1
            n_rep += 1
    con.executemany("""UPDATE decp_classification SET preset_principal=?, source=?, classified_at=?,
                       domaine=?, famille=?, modele=?, prompt_version=? WHERE decp_id=?""", lignes_cl)
    con.commit()
    con.close()
    return cout_total, n_ok, n_rep


def cmd_suivre(args):
    llm_router.charger_env()
    client = llm_router._client_gemini()
    etat = _etat()
    for j in etat["jobs"]:
        if j["statut"] in ("integre", "echec", "annule"):
            continue
        job = client.batches.get(name=j["nom"])
        s = getattr(job.state, "name", str(job.state))
        if s in ("JOB_STATE_SUCCEEDED", "JOB_STATE_PARTIALLY_SUCCEEDED"):
            cout, ok, n = _integrer(j, job)
            j.update(statut="integre", cout_reel_eur=round(cout, 5), contrats_classes=ok,
                     contrats_envoyes=n, integre_le=_now())
            print(f"  {j['nom']} ({j['annee']}) intégré : {ok}/{n} contrats, coût réel {cout:.4f} € "
                  f"(estimé {j['estimation_eur']:.4f} €)", flush=True)
        elif s in ("JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"):
            j.update(statut="echec", etat_api=s, erreur=str(job.error)[:300] if job.error else None)
            print(f"  {j['nom']} : {s}")
        else:
            j["etat_api"] = s
        _sauver_etat(etat)
    cmd_etat(args)


def cmd_piloter(args):
    """Boucle : intègre les jobs terminés, soumet de nouveaux jobs (budget + quota), jusqu'à
    ce que tout soit soumis/intégré ou que le budget de l'enveloppe soit épuisé."""
    import io
    import contextlib
    while True:
        try:
            cmd_suivre(args)
            avant = len(_etat()["jobs"])
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                cmd_soumettre(args)
            sortie = buf.getvalue()
        except Exception as e:      # coupure réseau, 5xx… : on réessaie au tour suivant
            print(f"  ⚠ erreur transitoire ({type(e).__name__}: {str(e)[:120]}) — nouvel essai dans {args.pause} s",
                  flush=True)
            time.sleep(args.pause)
            continue
        print(sortie.strip().splitlines()[-1] if sortie.strip() else "", flush=True)
        for l in sortie.splitlines():
            if l.strip().startswith("job ") or "⛔" in l or "⏸" in l:
                print(l, flush=True)
        actifs = [j for j in _etat()["jobs"] if j["statut"] not in ("integre", "echec", "annule")]
        budget_epuise = "⛔ budget" in sortie
        rien_de_plus = len(_etat()["jobs"]) == avant and "quota" not in sortie
        if not actifs and (budget_epuise or rien_de_plus):
            print("✅ pilotage terminé :", "budget épuisé" if budget_epuise else "plus rien à soumettre", flush=True)
            cmd_etat(args)
            return
        time.sleep(args.pause)


def cmd_propager(args):
    con = decp_db.connexion()
    n = con.execute("""INSERT INTO decp_classification
                         (decp_id, preset_principal, source, confiance, classified_at, domaine, famille, modele, prompt_version)
                       SELECT m.uid, c.preset_principal, 'copie_du_conserve:' || c.source, c.confiance, ?,
                              c.domaine, c.famille, c.modele, c.prompt_version
                       FROM decp_marches m JOIN decp_classification c ON c.decp_id = m.doublon_de
                       WHERE m.doublon_de IS NOT NULL
                       ON CONFLICT(decp_id) DO UPDATE SET preset_principal=excluded.preset_principal,
                         source=excluded.source, classified_at=excluded.classified_at, domaine=excluded.domaine,
                         famille=excluded.famille, modele=excluded.modele, prompt_version=excluded.prompt_version""",
                    (_now(),)).rowcount
    con.commit()
    con.close()
    print(f"classification propagée à {n} doublons")


def cmd_etat(args):
    etat = _etat()
    from collections import Counter
    print("jobs :", dict(Counter(j["statut"] + ("/" + j.get("etat_api", "") if j["statut"] == "soumis" else "")
                                 for j in etat["jobs"])))
    dep, pend = _engage_eur()
    print(f"enveloppe : dépensé {dep:.4f} € ; estimations en cours {pend:.4f} €")
    con = sqlite3.connect(f"file:{stockage.chemin_db()}?mode=ro", uri=True)
    print("decp_classification par source :",
          con.execute("SELECT source, COUNT(*) FROM decp_classification GROUP BY 1 ORDER BY 2 DESC").fetchall()[:8])


def main():
    ap = argparse.ArgumentParser(prog="decp.classif_batch")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("base").set_defaults(func=cmd_base)
    sub.add_parser("estimer").set_defaults(func=cmd_estimer)
    s = sub.add_parser("soumettre")
    s.add_argument("--annees", default=None)
    s.add_argument("--max-jobs", type=int, default=None)
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_soumettre)
    sub.add_parser("suivre").set_defaults(func=cmd_suivre)
    pl = sub.add_parser("piloter")
    pl.add_argument("--annees", default=None)
    pl.add_argument("--max-jobs", type=int, default=None)
    pl.add_argument("--dry-run", action="store_true")
    pl.add_argument("--pause", type=int, default=120)
    pl.set_defaults(func=cmd_piloter)
    sub.add_parser("propager").set_defaults(func=cmd_propager)
    sub.add_parser("etat").set_defaults(func=cmd_etat)
    ap.add_argument("--enveloppe", default=None, help="enveloppe budget (défaut decp_reprise)")
    a = ap.parse_args()
    if a.enveloppe:
        global ENV
        ENV = a.enveloppe
    a.func(a)


if __name__ == "__main__":
    main()
