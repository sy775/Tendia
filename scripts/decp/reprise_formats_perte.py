"""
scripts/decp/reprise_formats_perte.py — Sprint DECP-R, arrêt n°1.

Lecture seule : staging (data/decp_reprise/staging.db) + table v1 de data/tendia.db.
  1. Versions : effet du filtre v1 (modification_id=0 ET donneesActuelles) par année.
  2. Formats par année (2022 → 2026) sur la version retenue : remplissage, identifiants,
     sources, avertissements de parsing.
  3. Perte de la table v1 (PK id) sur sa période (notification 2025-06-15 → 2026-06-15) :
     contrats perdus (collisions d'id vs publication tardive) et faux groupements.

Usage : python scripts/decp/reprise_formats_perte.py [--sortie data/decp_reprise/arret1.json]
"""
import argparse
import collections
import json
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tendia.core import stockage
from decp.parser_v2 import contrat_depuis_lignes

STAGING = "data/decp_reprise/staging.db"
SOURCE = "decp_csv"
V1_DEBUT, V1_FIN, V1_INGESTION = "2025-06-15", "2026-06-15", "2026-06-16"


def pct(a, b):
    return round(100.0 * a / b, 1) if b else None


def versions(st):
    print("\n=== 1. Versions (lignes brutes, une par titulaire) ===")
    q = """SELECT substr(date_notification,1,4) an, COUNT(*), COUNT(DISTINCT uid),
                  SUM(modification_id=0 AND donnees_actuelles=1),
                  SUM(donnees_actuelles=1), SUM(modification_id>0)
           FROM lignes WHERE source=? GROUP BY an ORDER BY an"""
    out = {}
    print(f"{'année':<6} {'lignes':>9} {'uid':>9} {'mod0+act':>9} {'act.':>9} {'mod>0':>8}")
    for an, n, u, m0a, act, modp in st.execute(q, (SOURCE,)):
        m0a, act, modp = m0a or 0, act or 0, modp or 0
        out[an] = dict(lignes=n, uid=u, mod0_actuelles=m0a, actuelles=act, mod_sup0=modp)
        print(f"{str(an):<6} {n:>9} {u:>9} {m0a:>9} {act:>9} {modp:>8}")
    # uid dont la version actuelle est une modification (exclus par le filtre v1)
    q2 = """SELECT substr(date_notification,1,4) an, COUNT(*) FROM (
              SELECT uid, MIN(date_notification) date_notification,
                     MAX(donnees_actuelles=1 AND modification_id=0) a0,
                     MAX(donnees_actuelles=1 AND modification_id>0) am
              FROM lignes WHERE source=? AND uid IS NOT NULL GROUP BY uid)
            WHERE a0=0 AND am=1 GROUP BY an ORDER BY an"""
    exclus = dict(st.execute(q2, (SOURCE,)).fetchall())
    q3 = """SELECT COUNT(*) FROM (SELECT uid FROM lignes WHERE source=? AND uid IS NOT NULL
            GROUP BY uid HAVING MAX(donnees_actuelles=1)=0)"""
    sans_act = st.execute(q3, (SOURCE,)).fetchone()[0]
    print("uid dont la version ACTUELLE est une modification (perdus par le filtre mod0) :", exclus)
    print("uid sans aucune ligne « donneesActuelles » :", sans_act)
    return {"par_annee": out, "exclus_filtre_mod0": exclus, "uid_sans_actuelle": sans_act}


def formats(st, filtre):
    print(f"\n=== 2. Formats par année (filtre : {filtre}) ===")
    champs = ["titulaire_nom", "titulaire_activite_code", "titulaire_categorie",
              "type_groupement", "sous_traitance_declaree", "offres_recues", "id_accord_cadre",
              "date_publication_donnees", "montant_rationalise", "montant_anomalie",
              "duree_mois", "procedure", "departement", "lieu_execution_code"]
    agg = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    n_an = collections.Counter()
    for uid, lignes in iterer(st, filtre):
        c, ts = contrat_depuis_lignes(lignes, SOURCE)
        an = (c["date_notification"] or "inconnue")[:4]
        n_an[an] += 1
        a = agg[an]
        for ch in champs:
            a["rempli"][ch] += c.get(ch) not in (None, "")
        a["montant"]["nul_ou_absent"] += not c["montant_eur"]
        a["montant"]["rationalise_differe"] += bool(c["montant_rationalise"] and c["montant_eur"]
                                                    and abs(c["montant_rationalise"] - c["montant_eur"]) > 1)
        a["cpv"]["8_chiffres"] += bool(c["cpv_principal"] and len(c["cpv_principal"]) == 8)
        a["uid"]["forme_std"] += c["uid"] == f"{lignes[0].get('acheteur_id')}{lignes[0].get('id')}_{lignes[0].get('codeCPV')}"
        a["titulaires"]["n"] += len(ts)
        a["titulaires"]["siren_valide"] += sum(t["valide"] for t in ts)
        a["titulaires"]["avec_nom"] += sum(1 for t in ts if t["nom"])
        a["groupement"][c["type_groupement"] or "absent"] += 1
        a["nature"][c["nature"] or "absent"] += 1
        a["source"][c["source_dataset"] or "absent"] += 1
        for t in ts:
            a["type_id"][t["type_identifiant"] or "absent"] += 1
            if t["motif_rejet"]:
                a["rejets"][t["motif_rejet"]] += 1
        for w in json.loads(c["parse_warnings"] or "[]"):
            a["warnings"][w] += 1
        a["duree"]["0_ou_absente"] += not c["duree_mois"]
    res = {}
    for an in sorted(n_an):
        n, a = n_an[an], agg[an]
        nt = a["titulaires"]["n"]
        r = {"contrats": n,
             "remplissage_%": {ch: pct(a["rempli"][ch], n) for ch in champs},
             "montant_nul_%": pct(a["montant"]["nul_ou_absent"], n),
             "montant_rationalise_differe_%": pct(a["montant"]["rationalise_differe"], n),
             "cpv_8ch_%": pct(a["cpv"]["8_chiffres"], n),
             "uid_forme_std_%": pct(a["uid"]["forme_std"], n),
             "duree_0_ou_absente_%": pct(a["duree"]["0_ou_absente"], n),
             "titulaires": nt, "siren_valide_%": pct(a["titulaires"]["siren_valide"], nt),
             "titulaire_avec_nom_%": pct(a["titulaires"]["avec_nom"], nt),
             "type_identifiant": dict(a["type_id"].most_common()),
             "rejets_identifiant": dict(a["rejets"].most_common(8)),
             "groupement": dict(a["groupement"].most_common()),
             "nature": dict(a["nature"].most_common(4)),
             "sources_top8": dict(a["source"].most_common(8)),
             "warnings": dict(a["warnings"].most_common())}
        res[an] = r
        print(f"\n--- {an} : {n} contrats, {nt} titulaires ---")
        print(json.dumps(r, ensure_ascii=False))
    return res


def iterer(st, filtre):
    cur = st.execute(f"SELECT uid, data FROM lignes WHERE source=? AND uid IS NOT NULL "
                     f"AND ({filtre}) ORDER BY uid, ordre", (SOURCE,))
    courant, paquet = None, []
    for uid, data in cur:
        if uid != courant and paquet:
            yield courant, paquet
            paquet = []
        courant = uid
        paquet.append(json.loads(data))
    if paquet:
        yield courant, paquet


def perte_v1(st):
    print(f"\n=== 3. Perte de la table v1 (notification {V1_DEBUT} → {V1_FIN}) ===")
    tdb = sqlite3.connect(f"file:{stockage.chemin_db()}?mode=ro", uri=True)
    t = {r[0] for r in tdb.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    table_v1 = "decp_marches_v1_id" if "decp_marches_v1_id" in t else "decp_marches"
    v1 = {}
    for id_, ach, cpv, tj, ts in tdb.execute(
            f"SELECT id, acheteur_siret, cpv_principal, titulaires_json, titulaire_siret FROM {table_v1}"):
        v1[f"{ach}{id_}_{cpv}"] = (json.loads(tj) if tj else ([ts] if ts else []))
    n_v1 = tdb.execute(f"SELECT COUNT(*) FROM {table_v1}").fetchone()[0]
    filtre = (f"modification_id=0 AND donnees_actuelles=1 AND date_notification>='{V1_DEBUT}' "
              f"AND date_notification<='{V1_FIN}'")
    c = collections.Counter()
    faux = collections.Counter()
    exemples = []
    for uid, lignes in iterer(st, filtre):
        contrat, tits = contrat_depuis_lignes(lignes, SOURCE)
        dispo = (contrat["date_publication_donnees"] or "9999") <= V1_INGESTION
        c["univers"] += 1
        c["dispo_a_l_ingestion" if dispo else "publie_apres_ingestion"] += 1
        vrais = [t["siret_brut"] for t in tits]
        if uid in v1:
            c["present_v1"] += 1
            ids_v1 = v1[uid]
            if len(ids_v1) > 1 or len(vrais) > 1:
                c["multi_v1_ou_reel"] += 1
                if set(ids_v1) == set(vrais):
                    faux["groupement_correct"] += 1
                elif set(vrais) < set(ids_v1):
                    faux["titulaires_etrangers_ajoutes"] += 1
                    if len(exemples) < 5:
                        exemples.append({"uid": uid, "objet": (contrat["objet"] or "")[:60],
                                         "titulaires_reels": len(vrais), "titulaires_v1": len(ids_v1)})
                else:
                    faux["autre_ecart"] += 1
        else:
            c["absent_v1_" + ("collision_ou_autre" if dispo else "publication_tardive")] += 1
    res = {"lignes_v1": n_v1, **c, "groupements": dict(faux), "exemples_faux_groupements": exemples,
           "perte_collision_%_des_dispo": pct(c["absent_v1_collision_ou_autre"], c["dispo_a_l_ingestion"])}
    v1_multi = sum(1 for v in v1.values() if len(v) > 1)
    res["v1_contrats_multi_titulaires"] = v1_multi
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default="data/decp_reprise/arret1.json")
    args = ap.parse_args()
    st = sqlite3.connect(f"file:{STAGING}?mode=ro", uri=True)
    out = {"versions": versions(st)}
    out["formats_mod0_actuelles"] = formats(st, "modification_id=0 AND donnees_actuelles=1")
    out["perte_v1"] = perte_v1(st)
    with open(args.sortie, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n→ {args.sortie}")


if __name__ == "__main__":
    main()
