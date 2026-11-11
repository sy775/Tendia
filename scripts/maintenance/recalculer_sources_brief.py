# -*- coding: utf-8 -*-
"""
scripts/maintenance/recalculer_sources_brief.py
-----------------------------------------------
Recalcule `_sources` et `_lecture` d'un brief du mode document, SANS appel LLM, à partir
de ce qui est déjà sur le disque : data/pieces/<id>/_inventaire.json (pièces et textes
par page) et data/pieces/<id>/_trace.json (analyses par pièce). Sert quand la
vérification des sources (tendia.analyse.sources_lecture) a été corrigée : les briefs
déjà payés en profitent sans être relus.

L'ancien brief est copié dans archive/data/briefs/ avant l'écriture (écriture unitaire).

    python scripts/maintenance/recalculer_sources_brief.py ID [ID ...] [--dry-run] [--force]

Refus d'écrire (sauf --force) : trace sans analyses, trace partielle ou d'une autre
lecture (ses pièces ne couvrent pas celles du brief), ou recalcul qui ferait baisser le
nombre de sources vérifiées ou de pièces lues. Code de sortie 1 si un marché est refusé.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tendia.analyse import extraire
from tendia.analyse import pieces
from tendia.analyse import sources_lecture
from tendia.core import stockage


def recalculer(marche_id: str, dry_run: bool = False, force: bool = False) -> dict:
    """Rend {"id", "avant", "apres", "ecrit"} (nombre de sources vérifiées avant / après)."""
    brief = stockage.lire("briefs_extraits", marche_id)
    if not brief or (brief.get("_meta") or {}).get("mode") != "document":
        return {"id": marche_id, "erreur": "pas de brief du mode document"}
    travail = pieces.dossier_travail(marche_id)
    try:
        inv = json.loads((travail / "_inventaire.json").read_text(encoding="utf-8"))
        trace = json.loads((travail / "_trace.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"id": marche_id, "erreur": f"inventaire ou trace illisible : {e}"}
    analyses = trace.get("analyses_pieces") or []
    if not analyses:
        return {"id": marche_id, "erreur": "trace sans analyses de pièces : rien n'est recalculé"}
    pieces_trace = {a.get("piece") for a in analyses}
    pieces_brief = {l.get("nom") for l in (brief.get("_lecture") or {}).get("pieces") or []
                    if l.get("statut") == "lu"}
    if (trace.get("interrompue") or not pieces_brief <= pieces_trace) and not force:
        return {"id": marche_id, "erreur": "trace partielle ou d'une autre lecture : "
                f"{len(pieces_brief - pieces_trace)} pièce(s) lue(s) du brief absente(s) de la trace"}
    compter = lambda s: sum(1 for v in (s or {}).values() if (v or {}).get("verifie"))
    avant = compter(brief.get("_sources"))
    nouvelles = sources_lecture.construire_sources(brief, analyses, inv)
    lecture = sources_lecture.tableau_lecture(inv, analyses)
    resultat = {"id": marche_id, "avant": avant, "apres": compter(nouvelles), "ecrit": False,
                "sources": nouvelles}
    lues_avant = (brief.get("_lecture") or {}).get("nb_lues") or 0
    if (resultat["apres"] < avant or (lecture.get("nb_lues") or 0) < lues_avant) and not force:
        resultat["refus"] = (f"recalcul défavorable (vérifiées {avant} → {resultat['apres']}, "
                             f"lues {lues_avant} → {lecture.get('nb_lues')}) : rien n'est écrit sans --force")
        return resultat
    if dry_run or (nouvelles == brief.get("_sources") and lecture == brief.get("_lecture")):
        return resultat
    extraire.archiver_brief_existant(marche_id)
    brief["_sources"] = nouvelles
    brief["_lecture"] = lecture
    brief.setdefault("_meta", {})["sources_recalculees_le"] = datetime.now(timezone.utc).isoformat()
    stockage.ecrire("briefs_extraits", marche_id, brief)
    chemin_json = os.path.join(extraire.REPERTOIRE_EXTRACTIONS, f"{marche_id}.json")
    if os.path.isfile(chemin_json):
        with open(chemin_json, "w", encoding="utf-8") as f:
            json.dump(brief, f, ensure_ascii=False, indent=2)
    resultat["ecrit"] = True
    return resultat


def main(argv=None):
    ap = argparse.ArgumentParser(description="Recalcule _sources et _lecture d'un brief (sans LLM).")
    ap.add_argument("ids", nargs="+")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="écrit même si le recalcul est défavorable")
    args = ap.parse_args(argv)
    refus = False
    for mid in args.ids:
        r = recalculer(mid, dry_run=args.dry_run, force=args.force)
        if r.get("erreur") or r.get("refus"):
            refus = True
            print(f"  {mid} : {r.get('erreur') or r.get('refus')}")
            if r.get("erreur"):
                continue
        print(f"  {mid} : sources vérifiées {r['avant']}/6 → {r['apres']}/6"
              f"{' (écrit)' if r['ecrit'] else ' (inchangé ou dry-run)'}")
        for champ, s in r["sources"].items():
            if s:
                corrigee = f" (page citée par le modèle : {s['page_citee']})" if "page_citee" in s else ""
                print(f"      {champ:<22} {s['piece']} p. {s['page']} "
                      f"{'vérifiée' if s['verifie'] else 'NON vérifiée'}{corrigee}")
            else:
                print(f"      {champ:<22} pas de source")
    if refus:
        sys.exit(1)


if __name__ == "__main__":
    main()
