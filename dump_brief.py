"""
dump_brief.py
-------------
Affiche le contenu d'un brief LLM en format lisible, pour évaluation
qualitative humaine. Permet de juger : champs remplis vs vides, cohérence,
hallucinations, utilisabilité métier.

Modes :
  - Sans argument : liste tous les briefs en base avec leur type
  - --id BOAMP-XX-YYYY : dump détaillé d'un brief précis
  - --type COMPLET : dump tous les briefs d'un type donné
  - --resume : tableau récapitulatif synthétique (un marché par ligne)

Usage :
    python dump_brief.py                              # liste
    python dump_brief.py --resume                     # tableau synthèse
    python dump_brief.py --id BOAMP-26-56729          # détail
    python dump_brief.py --type COMPLET --resume      # tous les COMPLET
"""

import argparse
import io
import json
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import stockage


REPERTOIRE_BASE = Path(__file__).parent
REPERTOIRE_EXTRACTIONS = REPERTOIRE_BASE / "data" / "extractions"


def _charger_tout() -> dict:
    """Charge briefs SQLite + fallback disque (priorité SQLite)."""
    briefs = {}
    try:
        briefs = dict(stockage.charger("briefs_extraits") or {})
    except Exception as e:
        print(f"  ⚠ Erreur SQLite briefs_extraits : {e}")
    if REPERTOIRE_EXTRACTIONS.exists():
        for f in REPERTOIRE_EXTRACTIONS.glob("*.json"):
            id_m = f.stem
            if id_m not in briefs:
                try:
                    briefs[id_m] = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    pass
    return briefs


def _type_brief(brief: dict) -> str:
    meta = brief.get("_meta") or {}
    t = (meta.get("type") or "").upper()
    if t in ("COMPLET", "LIGHT"):
        return t
    if any(k in brief for k in ("criteres_attribution", "modalites_consultation",
                                  "duree_estimee", "volume_estime")):
        return "COMPLET"
    return "INCONNU"


def _aplatir_pour_resume(brief: dict) -> dict:
    """Extrait quelques champs-clés pour la vue tableau."""
    meta = brief.get("_meta") or {}
    return {
        "type": _type_brief(brief),
        "cout_eur": round(meta.get("cout_eur") or 0.0, 4),
        "duree_sec": meta.get("duree_sec") or "?",
        "tokens_in": meta.get("tokens_in") or "?",
        "tokens_out": meta.get("tokens_out") or "?",
        "preset_code": meta.get("preset_code") or "?",
        "champs_remplis": sum(
            1 for k, v in brief.items()
            if not k.startswith("_") and v not in (None, "", [], {}, "?")
        ),
        "nb_champs_total": sum(1 for k in brief if not k.startswith("_")),
        "sujet": (brief.get("sujet") or brief.get("titre") or "")[:60],
    }


def lister(briefs: dict):
    """Liste compacte de tous les briefs."""
    print(f"  Briefs en cache : {len(briefs)}\n")
    if not briefs:
        return
    types = {}
    for id_m, b in briefs.items():
        t = _type_brief(b)
        types.setdefault(t, []).append(id_m)
    for t, ids in sorted(types.items()):
        print(f"  ── {t} ({len(ids)}) ──")
        for id_m in sorted(ids)[:50]:
            sujet = (briefs[id_m].get("sujet") or briefs[id_m].get("titre") or "")[:60]
            print(f"    {id_m:<18}  {sujet}")
        if len(ids) > 50:
            print(f"    ... +{len(ids) - 50}")
        print()


def tableau_resume(briefs: dict, type_filtre: str | None = None):
    """Tableau récap : un marché par ligne."""
    items = [(id_m, b) for id_m, b in briefs.items()
             if not type_filtre or _type_brief(b) == type_filtre.upper()]
    if not items:
        print(f"  Aucun brief de type {type_filtre}")
        return

    print(f"\n  {'ID':<18} {'Type':<8} {'Coût€':>7} {'In tk':>7} {'Out tk':>7} "
          f"{'Champs':>8} {'Preset':<22} Sujet")
    print(f"  {'-'*18} {'-'*8} {'-'*7} {'-'*7} {'-'*7} {'-'*8} {'-'*22} {'-'*60}")
    cout_total = 0.0
    for id_m, b in sorted(items):
        r = _aplatir_pour_resume(b)
        cout_total += r["cout_eur"] or 0.0
        champs_str = f"{r['champs_remplis']}/{r['nb_champs_total']}"
        print(f"  {id_m:<18} {r['type']:<8} {r['cout_eur']:>7.4f} "
              f"{str(r['tokens_in']):>7} {str(r['tokens_out']):>7} "
              f"{champs_str:>8} {str(r['preset_code'])[:22]:<22} {r['sujet']}")
    print(f"  {'-'*18}")
    print(f"  Total briefs : {len(items)}, coût cumulé : {cout_total:.4f} €")


def dump_detail(brief: dict, id_m: str):
    """Dump détaillé en markdown."""
    print(f"\n{'=' * 78}")
    print(f"  BRIEF {id_m}")
    print(f"{'=' * 78}\n")

    meta = brief.get("_meta") or {}
    type_b = _type_brief(brief)

    print(f"## Métadonnées\n")
    print(f"  Type           : {type_b}")
    print(f"  Coût           : {meta.get('cout_eur', '?')} €")
    print(f"  Durée appel    : {meta.get('duree_sec', '?')} s")
    print(f"  Tokens in/out  : {meta.get('tokens_in', '?')} / {meta.get('tokens_out', '?')}")
    print(f"  Modèle         : {meta.get('modele', '?')}")
    print(f"  Date           : {meta.get('date', '?')}")
    print(f"  Preset cible   : {meta.get('preset_code', '?')}")
    print(f"  Source PDF     : {meta.get('source_pdf', meta.get('pdfs_traites', '?'))}")
    print(f"  Chars input    : {meta.get('chars_input', '?')}")
    print()

    # Champs principaux : tous sauf _meta
    print(f"## Champs ({sum(1 for k in brief if not k.startswith('_'))})\n")
    for k, v in brief.items():
        if k.startswith("_"):
            continue

        # Mise en forme selon le type
        if v is None or v == "" or v == []:
            print(f"  ❌ **{k}** : (vide)")
        elif isinstance(v, list):
            print(f"  📋 **{k}** :")
            for item in v[:10]:
                if isinstance(item, dict):
                    # Format compact : 3 premiers couples clé:valeur
                    parts = [f"{kk}={str(vv)[:50]}" for kk, vv in list(item.items())[:3]]
                    print(f"      · {' | '.join(parts)}")
                else:
                    print(f"      · {str(item)[:120]}")
            if len(v) > 10:
                print(f"      ... +{len(v) - 10} autres")
        elif isinstance(v, dict):
            print(f"  📂 **{k}** :")
            for kk, vv in v.items():
                if vv in (None, "", [], {}, "?"):
                    print(f"      {kk} : (vide)")
                else:
                    s = str(vv)
                    if len(s) > 120:
                        print(f"      {kk} : {s[:120]}...")
                    else:
                        print(f"      {kk} : {s}")
        else:
            s = str(v)
            if len(s) > 200:
                # Texte long : tronque proprement
                print(f"  ✓ **{k}** :")
                for ligne in s.split("\n")[:10]:
                    print(f"      {ligne[:200]}")
                if s.count("\n") > 10:
                    print(f"      ... (+{s.count(chr(10)) - 10} lignes)")
            else:
                print(f"  ✓ **{k}** : {s}")

    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", help="Dump détaillé d'un brief précis")
    ap.add_argument("--type", choices=["COMPLET", "LIGHT", "INCONNU"],
                    help="Filtre par type")
    ap.add_argument("--resume", action="store_true",
                    help="Tableau récap synthétique")
    args = ap.parse_args()

    briefs = _charger_tout()
    print(f"=== Briefs LLM en cache ({len(briefs)}) ===\n")

    if args.id:
        b = briefs.get(args.id)
        if not b:
            print(f"  ⚠ Aucun brief pour {args.id}")
            # Suggestions par similarité
            matches = [id_m for id_m in briefs if args.id in id_m]
            if matches:
                print(f"  IDs proches : {', '.join(matches[:5])}")
            return
        dump_detail(b, args.id)
        return

    if args.type:
        briefs = {k: v for k, v in briefs.items()
                  if _type_brief(v) == args.type}
        print(f"  (filtre type={args.type} → {len(briefs)} briefs)\n")

    if args.resume:
        tableau_resume(briefs, args.type)
    else:
        lister(briefs)


if __name__ == "__main__":
    main()
