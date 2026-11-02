"""
decp/sirene.py — table sirene_unites_legales depuis les fichiers stock Sirene (data.gouv)
— Sprint DECP-R. Téléchargement unique, AUCUN appel d'API.

Sélection (validée) :
  - SIREN présents dans decp_titulaires (siren valide) ;
  - acheteurs : SIREN des acheteurs DECP (9 premiers chiffres du SIRET) + personnes
    publiques (catégorie juridique 4xxx et 7xxx) ;
  - prospection BTP : NAF 41, 42, 43, unité ACTIVE, personne morale (catégorie juridique
    ≠ 1000 « entrepreneur individuel ») ;
  - dans tous les cas, exclusion des unités en diffusion partielle (statutDiffusion = P).
Adresse, code postal, commune, département = établissement SIÈGE (StockEtablissement).

Les fichiers zip sont lus en flux (zipfile + csv), sans décompression sur disque.
"""
import csv
import io
import re
import sqlite3
import time
import unicodedata
import zipfile

from decp import db as decp_db

csv.field_size_limit(2**31 - 1)

DDL = """
CREATE TABLE IF NOT EXISTS sirene_unites_legales (
    siren            TEXT PRIMARY KEY,
    denomination     TEXT,
    naf              TEXT,
    tranche_effectif TEXT,
    adresse          TEXT,
    date_creation    TEXT,
    etat             TEXT,          -- A = active, C = cessée
    -- compléments (rapprochement acheteurs, prospection)
    categorie_juridique TEXT,
    categorie_entreprise TEXT,
    sigle            TEXT,
    siret_siege      TEXT,
    code_postal      TEXT,
    commune          TEXT,
    code_commune     TEXT,
    departement      TEXT,
    denomination_normalisee TEXT,
    motifs           TEXT,          -- titulaire,acheteur,public,btp (séparés par des virgules)
    stock_du         TEXT
);
CREATE INDEX IF NOT EXISTS idx_sul_nom_dept ON sirene_unites_legales(denomination_normalisee, departement);
CREATE INDEX IF NOT EXISTS idx_sul_naf ON sirene_unites_legales(naf);
CREATE INDEX IF NOT EXISTS idx_sul_dept ON sirene_unites_legales(departement);
"""

_MOTS_VIDES = {"DE", "DU", "DES", "LA", "LE", "LES", "L", "D", "ET", "EN", "A", "AU", "AUX"}


def normaliser_nom(nom) -> str:
    """Nom normalisé pour le rapprochement : majuscules sans accents, ponctuation → espace,
    articles retirés, espaces compactés. Ex. « Commune de Saint-Étienne » → « COMMUNE SAINT ETIENNE »."""
    if not nom:
        return ""
    s = unicodedata.normalize("NFKD", str(nom)).encode("ascii", "ignore").decode().upper()
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return " ".join(m for m in s.split() if m not in _MOTS_VIDES)


def departement_de(code_postal, code_commune) -> str:
    cc = (code_commune or "").strip()
    if cc[:2] in ("2A", "2B"):
        return cc[:2]
    cp = (code_postal or "").strip()
    if len(cp) == 5 and cp.isdigit():
        return cp[:3] if cp.startswith("97") or cp.startswith("98") else cp[:2]
    return cc[:3] if cc.startswith("97") else cc[:2] or None


def _csv_du_zip(chemin_zip):
    z = zipfile.ZipFile(chemin_zip)
    nom = next(n for n in z.namelist() if n.lower().endswith(".csv"))
    return z, csv.DictReader(io.TextIOWrapper(z.open(nom), encoding="utf-8", newline=""))


def _sirens_decp(con) -> tuple:
    tit = {r[0] for r in con.execute("SELECT DISTINCT siren FROM decp_titulaires WHERE valide=1 AND siren IS NOT NULL")}
    ach = {r[0][:9] for r in con.execute("SELECT DISTINCT acheteur_siret FROM decp_marches WHERE acheteur_siret IS NOT NULL")
           if r[0] and len(r[0]) >= 9 and r[0][:9].isdigit()}
    return tit, ach


def charger(zip_ul: str, zip_etab: str, stock_du: str, db_path=None, verbose=True) -> dict:
    con = decp_db.connexion(db_path)
    con.executescript(DDL)
    tit, ach = _sirens_decp(con)
    if verbose:
        print(f"  [sirene] SIREN titulaires DECP : {len(tit):,} ; acheteurs DECP : {len(ach):,}"
              .replace(",", " "), flush=True)
    t0, lues = time.time(), 0
    sel, stats = {}, {"exclu_diffusion_partielle": 0}
    z, rd = _csv_du_zip(zip_ul)
    for r in rd:
        lues += 1
        siren = r.get("siren")
        cj = r.get("categorieJuridiqueUniteLegale") or ""
        naf = r.get("activitePrincipaleUniteLegale") or ""
        etat = r.get("etatAdministratifUniteLegale") or ""
        motifs = []
        if siren in tit:
            motifs.append("titulaire")
        if siren in ach:
            motifs.append("acheteur")
        if cj[:1] in ("4", "7"):
            motifs.append("public")
        if naf[:2] in ("41", "42", "43") and etat == "A" and cj != "1000":
            motifs.append("btp")
        if not motifs:
            continue
        if (r.get("statutDiffusionUniteLegale") or "").upper() == "P":
            stats["exclu_diffusion_partielle"] += 1
            continue
        denom = (r.get("denominationUniteLegale") or r.get("denominationUsuelle1UniteLegale")
                 or " ".join(x for x in (r.get("prenomUsuelUniteLegale"), r.get("nomUsageUniteLegale")
                                         or r.get("nomUniteLegale")) if x) or None)
        sel[siren] = {
            "siren": siren, "denomination": denom, "naf": naf or None,
            "tranche_effectif": r.get("trancheEffectifsUniteLegale") or None,
            "date_creation": r.get("dateCreationUniteLegale") or None, "etat": etat or None,
            "categorie_juridique": cj or None, "categorie_entreprise": r.get("categorieEntreprise") or None,
            "sigle": r.get("sigleUniteLegale") or None,
            "siret_siege": (siren + r["nicSiegeUniteLegale"]) if r.get("nicSiegeUniteLegale") else None,
            "denomination_normalisee": normaliser_nom(denom), "motifs": ",".join(motifs),
            "stock_du": stock_du,
        }
        if verbose and len(sel) % 250000 == 0:
            print(f"  [sirene] UL : {lues:,} lues, {len(sel):,} retenues, {time.time()-t0:.0f}s"
                  .replace(",", " "), flush=True)
    z.close()
    stats["ul_lues"] = lues
    if verbose:
        print(f"  [sirene] UL terminé : {len(sel):,} retenues — lecture des sièges…".replace(",", " "), flush=True)
    z, rd = _csv_du_zip(zip_etab)
    n_et = sieges = 0
    for r in rd:
        n_et += 1
        if (r.get("etablissementSiege") or "").lower() != "true":
            continue
        u = sel.get(r.get("siren"))
        if not u:
            continue
        sieges += 1
        voie = " ".join(x for x in (r.get("numeroVoieEtablissement"), r.get("indiceRepetitionEtablissement"),
                                    r.get("typeVoieEtablissement"), r.get("libelleVoieEtablissement")) if x)
        cp, commune, ccom = (r.get("codePostalEtablissement"), r.get("libelleCommuneEtablissement"),
                             r.get("codeCommuneEtablissement"))
        u["adresse"] = ", ".join(x for x in (r.get("complementAdresseEtablissement"), voie,
                                             " ".join(y for y in (cp, commune) if y)) if x) or None
        u["code_postal"], u["commune"], u["code_commune"] = cp or None, commune or None, ccom or None
        u["departement"] = departement_de(cp, ccom)
        if verbose and n_et % 5000000 == 0:
            print(f"  [sirene] établissements : {n_et:,} lus, {sieges:,} sièges, {time.time()-t0:.0f}s"
                  .replace(",", " "), flush=True)
    z.close()
    cols = ["siren", "denomination", "naf", "tranche_effectif", "adresse", "date_creation", "etat",
            "categorie_juridique", "categorie_entreprise", "sigle", "siret_siege", "code_postal",
            "commune", "code_commune", "departement", "denomination_normalisee", "motifs", "stock_du"]
    maj = ",".join(f"{c}=excluded.{c}" for c in cols if c != "siren")
    rows = [tuple(u.get(c) for c in cols) for u in sel.values()]
    for i in range(0, len(rows), 20000):
        con.executemany(f"INSERT INTO sirene_unites_legales ({','.join(cols)}) VALUES "
                        f"({','.join('?' * len(cols))}) ON CONFLICT(siren) DO UPDATE SET {maj}",
                        rows[i:i + 20000])
        con.commit()
    con.close()
    stats.update({"retenues": len(sel), "avec_siege": sieges, "etablissements_lus": n_et,
                  "secondes": round(time.time() - t0)})
    return stats
