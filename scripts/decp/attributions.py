"""
scripts/decp/attributions.py — Sprint DECP-R, étape 9 : rapprochement avis Tendia ↔ DECP.

  acheteurs   [--appliquer] : complète marches.acheteur_siren manquant à partir de
                sirene_unites_legales (nom normalisé + département) et des acheteurs DECP.
                N'écrit que les correspondances SÛRES ; journalise les autres (TSV).
  rapprocher  [--appliquer] : decp/matching.scorer_match (déterministe, 0 LLM) sur les avis
                dont la date limite de dépôt est passée → marche_attribution_link
                (score ≥ SEUIL_CANDIDAT ; statut auto_fort si ≥ SEUIL_FORT).
  precedents  : avis ayant un contrat DECP du même acheteur (≥ 3 mots d'objet communs),
                méthode du rapport d'architecture (322 / 49) sur la table v1 et la v2,
                + variante stricte (contrat notifié AVANT la publication de l'avis).
"""
import argparse
import collections
import csv
import json
import os
import re
import sqlite3
import sys
from datetime import date, datetime, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import stockage
from decp import db as decp_db
from decp.matching import SEUIL_CANDIDAT, SEUIL_FORT, scorer_match
from decp.sirene import departement_de, normaliser_nom

DOSSIER = "data/decp_reprise"
AUJ = date.today().isoformat()


def _ro():
    return sqlite3.connect(f"file:{stockage.chemin_db()}?mode=ro", uri=True)


def _marches(con):
    return {i: json.loads(v) for i, v in con.execute(
        "SELECT id, contenu_json FROM kv_storage WHERE collection='marches'")}


def _est_avis(m):
    return not (m.get("notice_type") or "").startswith("10") and m.get("nature") != "ATTRIBUTION"


def _travaux(m):
    return (m.get("type_marche") or "").upper() == "TRAVAUX"


def _dept_marche(m):
    """Code postal de l'acheteur, à défaut « Dept XX » du périmètre (même règle que
    decp_comparables._dept_de)."""
    d = departement_de(str(m.get("acheteur_code_postal") or ""), "")
    if d:
        return d
    import decp_comparables
    return decp_comparables._dept_de({"perimetre_geographique": m.get("perimetre_geographique")})


# ------------------------------------------------------------------ acheteurs
def _sim(a, b):
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def cmd_acheteurs(args):
    con = _ro()
    marches = _marches(con)
    # index (nom normalisé, département) → {siren}
    idx = collections.defaultdict(set)
    par_dept = collections.defaultdict(list)
    for siren, nom, dept, motifs in con.execute(
            "SELECT siren, denomination_normalisee, departement, motifs FROM sirene_unites_legales "
            "WHERE motifs LIKE '%public%' OR motifs LIKE '%acheteur%'"):
        if nom:
            idx[(nom, dept)].add(siren)
            par_dept[dept].append((nom, siren))
    for siret, nom, dept in con.execute(
            "SELECT DISTINCT acheteur_siret, acheteur_nom, departement FROM decp_marches "
            "WHERE acheteur_siret IS NOT NULL AND acheteur_nom IS NOT NULL"):
        n = normaliser_nom(nom)
        if n and siret and len(siret) >= 9 and siret[:9].isdigit():
            idx[(n, dept)].add(siret[:9])
            par_dept[dept].append((n, siret[:9]))
    national = collections.defaultdict(set)
    for (nom_n, _), sirens in idx.items():
        national[nom_n] |= sirens
    avant = sum(1 for m in marches.values() if m.get("acheteur_siren"))
    sures, journal = {}, []
    for mid, m in marches.items():
        if m.get("acheteur_siren"):
            continue
        nom, dept = normaliser_nom(m.get("acheteur_nom")), _dept_marche(m)
        if not nom:
            journal.append((mid, m.get("acheteur_nom"), dept, "", 0, "nom_absent")); continue
        if not dept:
            # sans département : seul un nom exact UNIQUE en France est jugé sûr
            nat = national.get(nom, set())
            if len(nat) == 1:
                sures[mid] = (next(iter(nat)), 1.0, "nom_exact_unique_national")
            else:
                journal.append((mid, m.get("acheteur_nom"), "", ",".join(sorted(nat))[:60], 1.0 if nat else 0,
                                "sans_departement_" + ("ambigu" if nat else "aucun_nom_exact")))
            continue
        exact = idx.get((nom, dept), set())
        if len(exact) == 1:
            sures[mid] = (next(iter(exact)), 1.0, "nom_exact_dept")
            continue
        if len(exact) > 1:
            journal.append((mid, m.get("acheteur_nom"), dept, ",".join(sorted(exact)), 1.0, "ambigu_plusieurs_siren")); continue
        cands = sorted(((_sim(nom, n2), s) for n2, s in par_dept.get(dept, [])), reverse=True)
        best = cands[0] if cands else (0, None)
        second = next((c for c in cands if c[1] != best[1]), (0, None))
        if best[0] >= 0.9 and best[0] - second[0] >= 0.15:
            sures[mid] = (best[1], round(best[0], 3), "nom_proche_dept")
        else:
            journal.append((mid, m.get("acheteur_nom"), dept, best[1] or "", round(best[0], 3),
                            "score_insuffisant" if best[1] else "aucun_candidat"))
    os.makedirs(DOSSIER, exist_ok=True)
    with open(f"{DOSSIER}/acheteurs_non_surs.tsv", "w", encoding="utf-8") as f:
        f.write("marche_id\tacheteur_nom\tdept\tmeilleur_siren\tscore\tmotif\n")
        for r in journal:
            f.write("\t".join(" ".join(str(x).split()) for x in r) + "\n")
    n = len(marches)
    print(f"acheteur_siren : avant {avant}/{n} ({100 * avant / n:.1f} %) ; correspondances sûres {len(sures)} "
          f"→ après {avant + len(sures)}/{n} ({100 * (avant + len(sures)) / n:.1f} %)")
    print("  par méthode :", dict(collections.Counter(v[2] for v in sures.values())))
    print("  non sûres journalisées :", dict(collections.Counter(r[5] for r in journal)),
          f"→ {DOSSIER}/acheteurs_non_surs.tsv")
    if args.appliquer:
        for mid, (siren, score, methode) in sures.items():
            m = stockage.lire("marches", mid)
            if not m or m.get("acheteur_siren"):
                continue
            m["acheteur_siren"] = siren
            m["acheteur_siren_source"] = {"methode": methode, "score": score, "referentiel": "sirene_2026-10-01+decp",
                                          "le": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            stockage.ecrire("marches", mid, m)
        print(f"✅ {len(sures)} marchés complétés (acheteur_siren + acheteur_siren_source)")


# ------------------------------------------------------------------ rapprocher
def cmd_rapprocher(args):
    import fiche_marche
    con = _ro()
    marches = _marches(con)
    avis = {mid: m for mid, m in marches.items()
            if _est_avis(m) and m.get("date_limite_depot") and str(m["date_limite_depot"])[:10] < AUJ}
    print(f"avis à date limite passée : {len(avis)} (dont travaux {sum(_travaux(m) for m in avis.values())})")
    liens, meilleurs, scores_tous = [], {}, []
    for mid, m in avis.items():
        siren = (m.get("acheteur_siren") or "")[:9]
        pub = str(m.get("date_publication") or "")[:10]
        if not siren or not pub:
            continue
        brief = stockage.lire("briefs_extraits", mid) or {}
        try:
            mt = (brief.get("revenu_eur") or fiche_marche.montant_estime(brief)) if brief else None
        except Exception:
            mt = None
        mt = mt or m.get("montant_estime_eur")
        cand = con.execute(
            "SELECT uid, cpv_principal, acheteur_siret, acheteur_nom, date_notification, montant_eur, objet, titulaire_nom "
            "FROM decp_marches WHERE acheteur_siret >= ? AND acheteur_siret < ? AND doublon_de IS NULL "
            "AND date_notification >= ?", (siren, siren + ":", pub)).fetchall()
        mk = {"cpv_principal": m.get("cpv_principal"), "acheteur_siren": siren,
              "acheteur_nom": m.get("acheteur_nom"), "date_publication": pub, "montant_estime": mt}
        best = None
        for c in cand:
            sc = scorer_match(mk, {"cpv_principal": c[1], "acheteur_siret": c[2], "acheteur_nom": c[3],
                                   "date_notification": c[4], "montant_eur": c[5]})
            scores_tous.append(sc["score_total"])
            # scorer_match ne compare pas les objets : contrôle d'objet séparé pour le statut
            commun = len(_toks(m.get("objet") or m.get("titre")) & _toks(c[6]))
            sc = dict(sc, mots_objet_communs=commun)
            if sc["score_total"] >= SEUIL_CANDIDAT:
                liens.append({"marche_tendia_id": mid, "decp_id": c[0], **sc,
                              "statut": "auto_confirme_objet" if commun >= 3 else "auto_a_verifier",
                              "created_at": datetime.now(timezone.utc).isoformat()})
            cle = (sc["score_total"] >= SEUIL_CANDIDAT and commun >= 3, sc["score_total"])
            if not best or cle > best[2]:
                best = (c, sc, cle)
        if best:
            meilleurs[mid] = best
    retrouves = {l["marche_tendia_id"] for l in liens}
    forts = {l["marche_tendia_id"] for l in liens if l["statut"] == "auto_confirme_objet"}
    print(f"avis avec acheteur_siren : {sum(1 for m in avis.values() if m.get('acheteur_siren'))} ; "
          f"avec ≥1 contrat DECP candidat : {len(meilleurs)}")
    print(f"attributions retrouvées (score ≥ {SEUIL_CANDIDAT}) : {len(retrouves)} avis "
          f"(travaux {sum(_travaux(avis[m]) for m in retrouves)}) ; dont objet confirmé (≥ 3 mots communs) : "
          f"{len(forts)} (travaux {sum(_travaux(avis[m]) for m in forts)}) ; liens : {len(liens)} "
          f"({sum(l['statut'] == 'auto_confirme_objet' for l in liens)} confirmés)")
    tranches = collections.Counter(min(int(b[1]["score_total"] * 10), 9) / 10 for b in meilleurs.values())
    print("distribution du meilleur score par avis :", dict(sorted(tranches.items())))
    import random
    random.seed(9)
    ex = random.sample(sorted(forts), min(7, len(forts))) + random.sample(sorted(retrouves - forts), min(3, len(retrouves - forts)))
    with open(f"{DOSSIER}/attributions_a_verifier.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["marche_id", "type", "objet_avis", "publication", "decp_uid", "objet_decp", "notification",
                    "montant_decp", "titulaire", "score", "cpv", "acheteur", "periode", "montant",
                    "mots_objet_communs", "verdict (o/n)"])
        for mid in ex:
            c, sc, _ = meilleurs[mid]
            w.writerow([mid, avis[mid].get("type_marche"), (avis[mid].get("objet") or "")[:100],
                        avis[mid].get("date_publication"), c[0], (c[6] or "")[:100], c[4], c[5], c[7],
                        sc["score_total"], sc["score_cpv"], sc["score_acheteur"], sc["score_periode"],
                        sc["score_montant"], sc["mots_objet_communs"], ""])
    print(f"10 exemples → {DOSSIER}/attributions_a_verifier.csv")
    if args.appliquer:
        w = decp_db.connexion()
        n = 0
        for l in liens:
            n += decp_db.inserer_lien({k: v for k, v in l.items() if k != "mots_objet_communs"})
        w.close()
        print(f"✅ {n} liens insérés dans marche_attribution_link")


# ------------------------------------------------------------------ précédents
def _toks(s):
    s = re.sub(r"[^a-z0-9àâçéèêëîïôûùüÿñæœ ]", " ", (s or "").lower())
    return {t for t in s.split() if len(t) > 3}


def cmd_precedents(args):
    con = _ro()
    marches = _marches(con)
    res = {}
    for nom, table, filtre in (("v1 (avant reprise)", "decp_marches_v1_id", ""),
                               ("v2 (après reprise)", "decp_marches", "WHERE doublon_de IS NULL")):
        idx = collections.defaultdict(list)
        for s9, d, objet in con.execute(f"SELECT substr(acheteur_siret,1,9), date_notification, objet FROM {table} {filtre}"):
            idx[s9].append((d, _toks(objet)))
        c = collections.Counter()
        for mid, m in marches.items():
            if (m.get("notice_type") or "").startswith("10"):
                continue
            s = (m.get("acheteur_siren") or "")[:9]
            if not s:
                continue
            tm = _toks(m.get("objet") or m.get("titre"))
            pub = str(m.get("date_publication") or "")[:10]
            prev = [d for d, t in idx.get(s, []) if len(tm & t) >= 3]
            if prev:
                c["methode_rapport"] += 1
                c["methode_rapport_travaux"] += _travaux(m)
            if any(d and pub and d < pub for d in prev):
                c["strict_anterieur"] += 1
                c["strict_anterieur_travaux"] += _travaux(m)
        res[nom] = dict(c)
        print(f"{nom} : {dict(c)}")
    json.dump(res, open(f"{DOSSIER}/precedents.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("acheteurs"); a.add_argument("--appliquer", action="store_true"); a.set_defaults(func=cmd_acheteurs)
    r = sub.add_parser("rapprocher"); r.add_argument("--appliquer", action="store_true"); r.set_defaults(func=cmd_rapprocher)
    sub.add_parser("precedents").set_defaults(func=cmd_precedents)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
