"""
scripts/decp/reprise_doublons_regle.py — Sprint DECP-R : règle de dédoublonnage DECP.

Par défaut : SIMULATION (aucune écriture) → chiffres + exemples à vérifier (CSV).
--appliquer : MARQUE les doublons (decp_marches.doublon_de = uid conservé,
doublon_regle = code de règle). Aucune suppression. Rejouable : remet d'abord à NULL
les marques posées par cette règle (doublon_regle LIKE 'R%').

Règles (groupes = même acheteur, même date de notification, même montant, même objet normalisé) :
  R1 multi-source, titulaires identiques            → doublon (republication par un autre canal)
  R2 multi-source, un des contrats SANS titulaire    → doublon (copie incomplète, ex. scrap_*)
  R3 même source, id identiques une fois normalisés, titulaires identiques → doublon (id reformaté)
  R4 même acheteur + même id, CPV différents, objet/montant/titulaires identiques
     (dates éventuellement différentes)            → doublon (correction de CPV)
Non marqués (contrats distincts ou trop ambigus) : même source et id différents
(lots ou accords-cadres multi-attributaires au même montant plafond), titulaires
disjoints ou chevauchants, couples (acheteur, id) « lot réel ».

Contrat conservé dans un groupe : celui qui a des titulaires, puis la source la plus
récente/structurée (SOURCE_PRIORITE), puis le plus de modifications, puis la publication
la plus récente, puis l'uid (ordre stable).
"""
import argparse
import collections
import csv
import os
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tendia.core import stockage
from decp import db as decp_db
from reprise_doublons import norm_id, norm_objet

# Plus petit = préféré
SOURCE_PRIORITE = {"pes_marche_2024": 0, "aife_dume": 1, "aws_marches-publics.info": 2,
                   "decp_colmo": 3, "e-marchespublics.com_dematis": 3, "pes_marche_legacy": 5,
                   "aws_marches-publics.info_legacy": 6}
PRIO_SCRAP = 8   # sources scrap_* (copies sans titulaire fréquentes)
PRIO_AUTRE = 4


def _prio(src):
    if src in SOURCE_PRIORITE:
        return SOURCE_PRIORITE[src]
    return PRIO_SCRAP if (src or "").startswith("scrap_") else PRIO_AUTRE


def _canonique(g, tit):
    return min(g, key=lambda r: (0 if tit.get(r["uid"]) else 1, _prio(r["src"]),
                                 -(r["nbm"] or 0), "" if r["pub"] is None else
                                 "".join(chr(255 - ord(c)) for c in r["pub"]), r["uid"]))


def calculer(con):
    tit = collections.defaultdict(frozenset)
    tmp = collections.defaultdict(set)
    for did, ident in con.execute("SELECT decp_id, COALESCE(siren, siret_brut, nom) FROM decp_titulaires"):
        if ident:
            tmp[did].add(ident)
    for k, v in tmp.items():
        tit[k] = frozenset(v)
    cols = ["uid", "id", "ach", "date", "mt", "objet", "cpv", "src", "pub", "nbm", "tnom"]
    rows = [dict(zip(cols, r)) for r in con.execute(
        "SELECT uid, id, acheteur_siret, date_notification, montant_eur, objet, cpv_principal, "
        "source_dataset, date_publication_donnees, nb_modifications, titulaire_nom FROM decp_marches")]
    marques = {}   # uid → (uid conservé, règle)
    # --- R1, R2, R3 : groupes stricts
    grp = collections.defaultdict(list)
    for r in rows:
        if r["ach"] and r["date"] and r["mt"] is not None and r["objet"]:
            grp[(r["ach"], r["date"], r["mt"], norm_objet(r["objet"]))].append(r)
    for g in grp.values():
        if len(g) < 2:
            continue
        c = _canonique(g, tit)
        tc = tit.get(c["uid"], frozenset())
        for r in g:
            if r is c:
                continue
            tr = tit.get(r["uid"], frozenset())
            if r["src"] != c["src"]:
                if tr == tc and tr:
                    marques[r["uid"]] = (c["uid"], "R1_multi_source_titulaires_identiques")
                elif not tr or not tc:
                    marques[r["uid"]] = (c["uid"], "R2_multi_source_sans_titulaire")
            elif norm_id(r["id"]) == norm_id(c["id"]) and tr == tc:
                marques[r["uid"]] = (c["uid"], "R3_id_reformate")
    # --- R4 : même (acheteur, id), CPV différents, reste identique
    par_ai = collections.defaultdict(list)
    for r in rows:
        if r["ach"] and r["id"]:
            par_ai[(r["ach"], r["id"])].append(r)
    for g in par_ai.values():
        if len(g) < 2:
            continue
        if (len({norm_objet(r["objet"]) for r in g}) == 1 and len({r["mt"] for r in g}) == 1
                and len({tit.get(r["uid"], frozenset()) for r in g}) == 1 and len({r["cpv"] for r in g}) > 1):
            c = _canonique(g, tit)
            for r in g:
                if r is not c and r["uid"] not in marques:
                    marques[r["uid"]] = (c["uid"], "R4_correction_cpv")
    # chaînes : si le conservé est lui-même marqué, on remonte au conservé final
    for u, (cible, regle) in list(marques.items()):
        vus = {u}
        while cible in marques and cible not in vus:
            vus.add(cible)
            cible = marques[cible][0]
        marques[u] = (cible, regle)
    return rows, marques, tit


def doublons_possibles(rows, marques, tit):
    """Groupes AMBIGUS (validés comme non-doublons) : dans un groupe strict, parmi les
    contrats non marqués, (a) même source, id différents (non égaux une fois normalisés),
    mêmes titulaires ; (b) titulaires partiellement communs (intersection non vide,
    ensembles différents), toutes sources. Retourne {uid: id_groupe}."""
    import hashlib
    grp = collections.defaultdict(list)
    for r in rows:
        if r["ach"] and r["date"] and r["mt"] is not None and r["objet"] and r["uid"] not in marques:
            grp[(r["ach"], r["date"], r["mt"], norm_objet(r["objet"]))].append(r)
    out = {}
    for cle, g in grp.items():
        if len(g) < 2:
            continue
        gid = "G" + hashlib.sha1(repr(cle).encode("utf-8")).hexdigest()[:12]
        for i, a in enumerate(g):
            for b in g[i + 1:]:
                ta, tb = tit.get(a["uid"], frozenset()), tit.get(b["uid"], frozenset())
                meme_src = a["src"] == b["src"] and norm_id(a["id"]) != norm_id(b["id"]) and ta == tb
                partiel = bool(ta & tb) and ta != tb
                if meme_src or partiel:
                    out[a["uid"]] = gid
                    out[b["uid"]] = gid
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--appliquer", action="store_true")
    ap.add_argument("--exemples", default="data/decp_reprise/doublons_exemples.csv")
    args = ap.parse_args()
    con = sqlite3.connect(f"file:{stockage.chemin_db()}?mode=ro", uri=True)
    rows, marques, tit = calculer(con)
    n = len(rows)
    par_regle = collections.Counter(r for _, r in marques.values())
    par_an = collections.Counter()
    idx = {r["uid"]: r for r in rows}
    for u in marques:
        par_an[(idx[u]["date"] or "????")[:4]] += 1
    tot_an = collections.Counter((r["date"] or "????")[:4] for r in rows)
    print(f"contrats : {n:,} ; marqués doublons : {len(marques):,} ({100 * len(marques) / n:.2f} %)".replace(",", " "))
    for k, v in par_regle.most_common():
        print(f"  {k:<42} {v:>8,}".replace(",", " "))
    print("  par année :", {a: f"{par_an[a]} ({100 * par_an[a] / tot_an[a]:.1f} %)" for a in sorted(tot_an)})
    # exemples à vérifier : 15 par règle
    import random
    random.seed(11)
    with open(args.exemples, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["regle", "role", "uid", "id", "source", "date_notification", "publication",
                    "montant", "cpv", "titulaire", "objet", "verdict_younes (doublon ? o/n)"])
        par = collections.defaultdict(list)
        for u, (c, r) in marques.items():
            par[r].append((u, c))
        for regle, lst in sorted(par.items()):
            for u, c in random.sample(lst, min(15, len(lst))):
                for role, x in (("conservé", idx[c]), ("marqué", idx[u])):
                    w.writerow([regle, role, x["uid"], x["id"], x["src"], x["date"], x["pub"],
                                x["mt"], x["cpv"], x["tnom"], (x["objet"] or "")[:120], ""])
                w.writerow([])
    print("exemples →", args.exemples)
    con.close()
    if args.appliquer:
        w = decp_db.connexion()
        w.execute("UPDATE decp_marches SET doublon_de=NULL, doublon_regle=NULL WHERE doublon_regle LIKE 'R%'")
        w.executemany("UPDATE decp_marches SET doublon_de=?, doublon_regle=? WHERE uid=?",
                      [(c, r, u) for u, (c, r) in marques.items()])
        w.commit()
        print("✅ marquage appliqué :", w.execute("SELECT COUNT(*) FROM decp_marches WHERE doublon_de IS NOT NULL").fetchone()[0])
        poss = doublons_possibles(rows, marques, tit)
        w.execute("UPDATE decp_marches SET doublon_possible=NULL, doublon_groupe=NULL WHERE doublon_possible IS NOT NULL")
        w.executemany("UPDATE decp_marches SET doublon_possible=1, doublon_groupe=? WHERE uid=?",
                      [(g, u) for u, g in poss.items()])
        w.commit()
        print("✅ doublons possibles (indicateur seul) :", len(poss), "contrats,", len(set(poss.values())), "groupes")
        w.close()


if __name__ == "__main__":
    main()
