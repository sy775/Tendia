"""
scripts/decp/reprise_doublons.py — Sprint DECP-R, arrêt n°2 : analyse des doublons.

LECTURE SEULE (aucun marquage) : mesure et propose une règle.

A. Doublons apparents : même acheteur, même date de notification, même montant, même
   objet (normalisé), uid différents. Cause probable de chaque groupe :
     - « multi_source »      : publié par plusieurs sourceDataset (republication) ;
     - « id_reformate »      : même source, id identiques une fois normalisés (2025-001 / 2025001) ;
     - « meme_id_cpv_diff »  : même acheteur + même id, CPV différents ;
     - « autre_meme_source » : même source, id réellement différents.
   + titulaires identiques ou non (ensemble des SIREN/identifiants).
B. Couples (acheteur, id) à plusieurs uid (CPV différents) : « lot réel » vs « correction
   de CPV » selon objet / montant / titulaires / dates.

Usage : python scripts/decp/reprise_doublons.py [--sortie data/decp_reprise/arret2.json]
"""
import argparse
import collections
import json
import os
import random
import re
import sqlite3
import sys
import unicodedata

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tendia.core import stockage


def norm_objet(s):
    if not s:
        return ""
    import html
    s = unicodedata.normalize("NFKD", html.unescape(s)).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def norm_id(s):
    return re.sub(r"[^A-Za-z0-9]", "", s or "").lstrip("0").upper()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default="data/decp_reprise/arret2.json")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    random.seed(args.seed)
    con = sqlite3.connect(f"file:{stockage.chemin_db()}?mode=ro", uri=True)
    tit = collections.defaultdict(set)
    for did, ident in con.execute("SELECT decp_id, COALESCE(siren, siret_brut, nom) FROM decp_titulaires"):
        tit[did].add(ident)
    rows = con.execute("""SELECT uid, id, acheteur_siret, date_notification, montant_eur, objet,
                                 cpv_principal, source_dataset, date_publication_donnees,
                                 nb_modifications, titulaire_nom
                          FROM decp_marches""").fetchall()
    n_total = len(rows)
    print(f"contrats v2 : {n_total:,}".replace(",", " "))

    # --- A. doublons apparents
    grp = collections.defaultdict(list)
    for r in rows:
        if r[2] and r[3] and r[4] is not None and r[5]:
            grp[(r[2], r[3], r[4], norm_objet(r[5]))].append(r)
    groupes = [g for g in grp.values() if len(g) > 1]
    causes = collections.Counter()
    tit_ident = collections.Counter()
    ex_par_cause = collections.defaultdict(list)
    lignes_dup = sum(len(g) for g in groupes)
    for g in groupes:
        sources = {r[7] for r in g}
        ids = {r[1] for r in g}
        nids = {norm_id(r[1]) for r in g}
        cpvs = {r[6] for r in g}
        if len(sources) > 1:
            cause = "multi_source"
        elif len(ids) == 1 and len(cpvs) > 1:
            cause = "meme_id_cpv_diff"
        elif len(nids) == 1:
            cause = "id_reformate"
        else:
            cause = "autre_meme_source"
        causes[cause] += 1
        ens = [frozenset(tit.get(r[0], ())) for r in g]
        tit_ident["titulaires_identiques" if len(set(ens)) == 1 else "titulaires_differents"] += 1
        if len(ex_par_cause[cause]) < 40:
            ex_par_cause[cause].append([{"uid": r[0], "id": r[1], "source": r[7], "cpv": r[6],
                                         "publication": r[8], "montant": r[4], "date": r[3],
                                         "objet": (r[5] or "")[:70], "titulaire": r[10],
                                         "nb_modifs": r[9]} for r in g])
    exemples_a = {c: random.sample(v, min(5, len(v))) for c, v in ex_par_cause.items()}
    res_a = {"groupes": len(groupes), "lignes_concernees": lignes_dup,
             "lignes_en_trop": lignes_dup - len(groupes),
             "taux_lignes_en_trop_%": round(100 * (lignes_dup - len(groupes)) / n_total, 2),
             "causes": dict(causes.most_common()), "titulaires": dict(tit_ident),
             "taille_groupes": dict(sorted(collections.Counter(min(len(g), 6) for g in groupes).items()))}
    print("\n=== A. Doublons apparents ===")
    print(json.dumps(res_a, ensure_ascii=False, indent=1))

    # --- B. (acheteur, id) à plusieurs uid
    par_ai = collections.defaultdict(list)
    for r in rows:
        if r[2] and r[1]:
            par_ai[(r[2], r[1])].append(r)
    multi = [g for g in par_ai.values() if len(g) > 1]
    typ = collections.Counter()
    ex_b = collections.defaultdict(list)
    for g in multi:
        objets = {norm_objet(r[5]) for r in g}
        montants = {r[4] for r in g}
        ens = {frozenset(tit.get(r[0], ())) for r in g}
        dates = {r[3] for r in g}
        lot_mot = any(re.search(r"\blot\s*n?\W*\d", (r[5] or "").lower()) for r in g)
        if len(objets) == 1 and len(montants) == 1 and len(ens) == 1:
            t = "correction_cpv_probable"          # tout identique sauf le CPV
        elif len(ens) > 1 or len(montants) > 1:
            t = "lot_reel_probable" if (len(objets) > 1 or lot_mot or len(ens) > 1) else "ambigu"
        else:
            t = "ambigu"
        typ[t] += 1
        if len(ex_b[t]) < 40:
            ex_b[t].append([{"uid": r[0], "cpv": r[6], "montant": r[4], "date": r[3],
                             "objet": (r[5] or "")[:70], "titulaire": r[10], "source": r[7]} for r in g])
    res_b = {"couples": len(multi), "uid_concernes": sum(len(g) for g in multi),
             "typologie": dict(typ.most_common()),
             "taille": dict(sorted(collections.Counter(min(len(g), 6) for g in multi).items()))}
    print("\n=== B. (acheteur, id) à plusieurs uid ===")
    print(json.dumps(res_b, ensure_ascii=False, indent=1))
    exemples_b = {t: random.sample(v, min(5, len(v))) for t, v in ex_b.items()}
    with open(args.sortie, "w", encoding="utf-8") as f:
        json.dump({"A": res_a, "exemples_A": exemples_a, "B": res_b, "exemples_B": exemples_b},
                  f, ensure_ascii=False, indent=1)
    print(f"\n→ {args.sortie}")


if __name__ == "__main__":
    main()
