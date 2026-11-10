"""
decp/ingest_v2.py — ingestion DECP v2 (clé uid, versions) — Sprint DECP-R.

Deux entrées, même règle (parser_v2.contrat_versionne) :
  - staging (historique, depuis decp.csv) : toutes les versions de chaque uid ;
  - API (rattrapage et mise à jour hebdomadaire) : lignes TOUTES versions depuis une
    date, regroupées par uid. Un contrat dont la version initiale n'est pas dans le lot
    n'est mis à jour que s'il existe déjà en base (ses champs initiaux y sont conservés
    via COALESCE) ; sinon il est ignoré (notifié hors période ou initiale non publiée).

Écritures : decp_marches (UPSERT colonnes source) et decp_titulaires. Les colonnes
dérivées (doublon_de…) ne sont jamais écrasées.
"""
import collections
import json
import sqlite3
import time

from tendia.prix.decp import db as decp_db
from tendia.prix.decp.parser_v2 import contrat_versionne

LOT = 5000


def _ecrire(con, contrats, titulaires, dry_run):
    if dry_run or not contrats:
        return
    decp_db.upsert_contrats(con, contrats)
    decp_db.upsert_titulaires(con, titulaires)
    con.commit()


def ingerer_staging(chemin_staging: str, source: str = "decp_csv", db_path=None,
                    dry_run: bool = False, limite: int = None, date_min: str = "2022-01-01",
                    journal_rejets: str = None) -> dict:
    st = sqlite3.connect(f"file:{chemin_staging}?mode=ro", uri=True)
    con = None if dry_run else decp_db.connexion(db_path)
    stats = collections.Counter()
    rejets_id = collections.Counter()
    f_rej = open(journal_rejets, "w", encoding="utf-8") if journal_rejets else None
    if f_rej:
        f_rej.write("decp_id\trang\ttype_identifiant\tmotif\tidentifiant_brut\n")
    contrats, titulaires, t0 = [], [], time.time()
    cur = st.execute("SELECT uid, data FROM lignes WHERE source=? AND uid IS NOT NULL "
                     "ORDER BY uid, ordre", (source,))
    courant, paquet = None, []

    def traiter(lignes):
        c, ts, motif = contrat_versionne(lignes, f"{source}", date_min=date_min)
        if c is None or motif == "sans_version_initiale":
            stats["exclu_" + (motif or "inconnu")] += 1
            return
        stats["contrats"] += 1
        stats["avec_modification"] += bool(c["nb_modifications"])
        contrats.append(c)
        for t in ts:
            stats["titulaires"] += 1
            stats["titulaires_siren_valide"] += t["valide"]
            if t["motif_rejet"]:
                rejets_id[t["motif_rejet"]] += 1
                if f_rej:
                    f_rej.write(f"{t['decp_id']}\t{t['rang']}\t{t['type_identifiant'] or ''}\t"
                                f"{t['motif_rejet']}\t{t['siret_brut'] or ''}\n")
        titulaires.extend(ts)

    for uid, data in cur:
        if uid != courant and paquet:
            traiter(paquet)
            paquet = []
            if len(contrats) >= LOT:
                _ecrire(con, contrats, titulaires, dry_run)
                contrats.clear(); titulaires.clear()
                if stats["contrats"] % 100000 < LOT:
                    print(f"  [v2] {stats['contrats']:,} contrats, {time.time()-t0:.0f}s"
                          .replace(",", " "), flush=True)
            if limite and stats["contrats"] >= limite:
                break
        courant = uid
        paquet.append(json.loads(data))
    if paquet and not (limite and stats["contrats"] >= limite):
        traiter(paquet)
    _ecrire(con, contrats, titulaires, dry_run)
    if f_rej:
        f_rej.close()
    if con:
        con.close()
    st.close()
    return {**stats, "rejets_identifiant": dict(rejets_id.most_common()),
            "secondes": round(time.time() - t0)}


def ingerer_lignes_api(lignes: list, db_path=None, dry_run: bool = False,
                       date_min: str = "2022-01-01", source: str = "decp_api") -> dict:
    """Lignes brutes API (toutes versions) → UPSERT. Voir docstring du module."""
    par_uid = collections.defaultdict(list)
    for r in lignes:
        if r.get("uid"):
            par_uid[r["uid"]].append(r)
    con = decp_db.connexion(db_path)
    existants = set()
    uids = list(par_uid)
    for i in range(0, len(uids), 900):
        q = uids[i:i + 900]
        existants |= {r[0] for r in con.execute(
            f"SELECT uid FROM decp_marches WHERE uid IN ({','.join('?' * len(q))})", q)}
    stats = collections.Counter()
    contrats, titulaires = [], []
    for uid, ls in par_uid.items():
        c, ts, motif = contrat_versionne(ls, source, date_min=date_min)
        if c is None:
            stats["exclu_" + motif] += 1
            continue
        if motif == "sans_version_initiale" and uid not in existants:
            stats["ignore_sans_initiale_hors_base"] += 1
            continue
        stats["mis_a_jour" if uid in existants else "nouveaux"] += 1
        contrats.append(c)
        titulaires.extend(ts)
    if not dry_run:
        tit_par_uid = collections.defaultdict(list)
        for t in titulaires:
            tit_par_uid[t["decp_id"]].append(t)
        for i in range(0, len(contrats), LOT):
            lot = contrats[i:i + LOT]
            _ecrire(con, lot, [t for c in lot for t in tit_par_uid[c["uid"]]], dry_run)
    con.close()
    return dict(stats)
