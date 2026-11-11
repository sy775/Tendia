# -*- coding: utf-8 -*-
"""
scripts/audit/rapport_lecture_dce.py
------------------------------------
Bilan de lecture de DCE en mode document, en LECTURE SEULE (aucun appel LLM, aucune
écriture en base) : pour chaque marché, pièces trouvées / lues / plans ignorés / non
gérées / échecs, pct_non_lu, modèle, coût réel lu dans llm_appels, coût au tarif argon du
2026-12-01, coût équivalent Sonnet 4.6 sur les mêmes tokens, durée, sources vérifiées.

    python scripts/audit/rapport_lecture_dce.py ID [ID ...] [--depuis AAAA-MM-JJTHH:MM:SS]
    python scripts/audit/rapport_lecture_dce.py --depense-depuis AAAA-MM-JJTHH:MM:SS
        (affiche seulement la dépense « extraction » depuis cette date UTC, pour borner une passe)

--depuis : ne compte que les appels llm_appels à partir de cette date UTC (défaut : tous
les appels du marché journalisés par le mode document, c'est-à-dire avec prompt_version doc-…).
--json : sortie JSON au lieu des tableaux markdown.
"""
import argparse
import json
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tendia.analyse import llm_router
from tendia.analyse import mode_document
from tendia.core import stockage

CHAMPS = mode_document.CHAMPS_SOURCES
DATE_TARIF_DECEMBRE = "2026-12-01"
SONNET = "claude-sonnet-4-6"


def appels_du_marche(marche_id: str, depuis: str = None) -> list:
    """Appels du mode document pour ce marché (llm_appels, type extraction)."""
    retenus = []
    for a in stockage.charger("llm_appels").values():
        if a.get("marche_id") != marche_id or a.get("type") != "extraction":
            continue
        if depuis and (a.get("appele_le") or "") < depuis:
            continue
        if not str((a.get("extra") or {}).get("prompt_version") or "").startswith("doc-"):
            continue
        retenus.append(a)
    return sorted(retenus, key=lambda a: a.get("appele_le") or "")


def bilan_marche(marche_id: str, depuis: str = None) -> dict:
    brief = stockage.lire("briefs_extraits", marche_id) or {}
    meta = brief.get("_meta") or {}
    lecture = brief.get("_lecture") or {}
    statuts = Counter(p.get("statut") for p in lecture.get("pieces") or [])
    sources = brief.get("_sources") or {}
    appels = appels_du_marche(marche_id, depuis)
    cout_reel = sum(float(a.get("cout_eur") or 0) for a in appels)
    cout_decembre = cout_sonnet = 0.0
    for a in appels:
        tin, tout = int(a.get("tokens_input") or 0), int(a.get("tokens_output") or 0)
        cout_decembre += llm_router.estimer_cout_eur(a.get("modele"), tin, tout, DATE_TARIF_DECEMBRE) or 0.0
        cout_sonnet += llm_router.estimer_cout_eur(SONNET, tin, tout) or 0.0
    modeles = Counter(a.get("modele") for a in appels)
    return {
        "id": marche_id,
        "brief_mode_document": meta.get("mode") == "document",
        "pieces_trouvees": len(lecture.get("pieces") or []),
        "pieces_texte": lecture.get("nb_pieces_texte"),
        "lues": lecture.get("nb_lues"),
        "plans_ignores": statuts.get("plan_ignore", 0),
        "non_gerees": statuts.get("format_non_gere", 0),
        "echecs_conversion": statuts.get("echec_conversion", 0),
        "echecs_lecture": statuts.get("echec_lecture", 0),
        "pct_non_lu": lecture.get("pct_non_lu"),
        "non_lues": [(p.get("nom"), p.get("statut"), p.get("detail"))
                     for p in lecture.get("pieces") or [] if p.get("statut") not in ("lu", "plan_ignore")],
        "modele": meta.get("modele"),
        "modeles_appels": dict(modeles),
        "nb_appels": len(appels),
        "nb_replis": sum(1 for a in appels if a.get("statut") == "repli"),
        "nb_erreurs": sum(1 for a in appels if a.get("statut") == "erreur"),
        "tokens_in": sum(int(a.get("tokens_input") or 0) for a in appels),
        "tokens_out": sum(int(a.get("tokens_output") or 0) for a in appels),
        "cout_reel_eur": round(cout_reel, 4),
        "cout_estime_eur": meta.get("cout_estime_eur"),
        "cout_tarif_decembre_eur": round(cout_decembre, 4),
        "cout_equivalent_sonnet_eur": round(cout_sonnet, 4),
        "duree_s": meta.get("duree_sec"),
        "sources": {c: sources.get(c) for c in CHAMPS},
        "sources_presentes": sum(1 for c in CHAMPS if sources.get(c)),
        "sources_verifiees": sum(1 for c in CHAMPS if (sources.get(c) or {}).get("verifie")),
    }


def depense_extraction_depuis(depuis: str) -> float:
    return round(sum(float(a.get("cout_eur") or 0) for a in stockage.charger("llm_appels").values()
                     if a.get("type") == "extraction" and (a.get("appele_le") or "") >= depuis), 4)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Bilan de lecture de DCE (mode document), lecture seule.")
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--depuis", default=None)
    ap.add_argument("--depense-depuis", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.depense_depuis:
        print(depense_extraction_depuis(args.depense_depuis))
        return
    bilans = [bilan_marche(i, args.depuis) for i in args.ids]
    if args.json:
        print(json.dumps(bilans, ensure_ascii=False, indent=1))
        return
    print("| Id | Pièces trouvées | Texte | Lues | Plans ignorés | Non gérées | Échecs conv. | Échecs lecture | % non lu | "
          "Modèle | Appels (replis) | Coût réel € | Coût estimé € | Au tarif du 01/12 € | Équiv. Sonnet € | Durée s | Sources (vérifiées) /6 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for b in bilans:
        print(f"| {b['id']} | {b['pieces_trouvees']} | {b['pieces_texte']} | {b['lues']} | {b['plans_ignores']} | "
              f"{b['non_gerees']} | {b['echecs_conversion']} | {b['echecs_lecture']} | {b['pct_non_lu']} | "
              f"{b['modele']} | {b['nb_appels']} ({b['nb_replis']}) | {b['cout_reel_eur']:.3f} | {b['cout_estime_eur']} | "
              f"{b['cout_tarif_decembre_eur']:.3f} | {b['cout_equivalent_sonnet_eur']:.3f} | {b['duree_s']} | "
              f"{b['sources_presentes']} ({b['sources_verifiees']}) |")
    for b in bilans:
        print(f"\n### {b['id']}")
        for champ in CHAMPS:
            s = b["sources"].get(champ)
            if s:
                print(f"- {champ} : {s.get('piece')} p. {s.get('page')} "
                      f"({'vérifiée' if s.get('verifie') else 'non vérifiée'}) « {(s.get('extrait') or '')[:90]} »")
            else:
                print(f"- {champ} : pas de source")
        for nom, statut, detail in b["non_lues"]:
            print(f"- non lue : {nom} ({statut} ; {detail})")


if __name__ == "__main__":
    main()
