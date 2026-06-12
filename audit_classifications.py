"""
audit_classifications.py
------------------------
Audit des classifications LLM (champ `domaines_metier`) appliquées aux briefs.

Affiche :
1. Distribution des domaines classifiés
2. Alignement entre matching multi-preset (mots-clés/CPV) et classification LLM
3. Cas suspects : marché matché par preset X mais classifié LLM dans un domaine NON
   accepté par preset X → faux positif probable

Permet de valider empiriquement la qualité de la classification LLM avant
d'automatiser le filtrage (Sprint 3).

Usage :
    python audit_classifications.py                  # vue d'ensemble
    python audit_classifications.py --conflits       # détail des cas suspects
    python audit_classifications.py --preset formation  # focus 1 preset
"""

import argparse
import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import stockage


REPERTOIRE_BASE = Path(__file__).parent
REPERTOIRE_EXTRACTIONS = REPERTOIRE_BASE / "data" / "extractions"


def _charger_briefs() -> dict:
    """Briefs SQLite + fallback disque."""
    briefs = {}
    try:
        briefs = dict(stockage.charger("briefs_extraits") or {})
    except Exception:
        pass
    if REPERTOIRE_EXTRACTIONS.exists():
        for f in REPERTOIRE_EXTRACTIONS.glob("*.json"):
            if f.stem.startswith("_"):
                continue
            id_m = f.stem
            if id_m not in briefs:
                try:
                    briefs[id_m] = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    pass
    return briefs


def _charger_taxonomie() -> dict:
    """Liste des domaines connus."""
    chemin = REPERTOIRE_BASE / "presets" / "_taxonomie_domaines.json"
    if not chemin.is_file():
        return {}
    try:
        data = json.loads(chemin.read_text(encoding="utf-8"))
        return data.get("domaines", {})
    except Exception:
        return {}


def _charger_presets() -> dict:
    """Charge tous les presets installés avec leurs domaines acceptés."""
    presets = {}
    presets_dir = REPERTOIRE_BASE / "presets"
    if not presets_dir.is_dir():
        return presets
    for sub in presets_dir.iterdir():
        if not sub.is_dir():
            continue
        config = sub / "_preset.json"
        if not config.is_file():
            continue
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
            code = (data.get("meta") or {}).get("code") or sub.name
            veille = data.get("veille") or {}
            presets[code] = {
                "domaines_acceptes": veille.get("domaines_acceptes") or [],
                "domaines_optionnels": veille.get("domaines_optionnels") or [],
            }
        except Exception:
            pass
    return presets


def _presets_matches_par_marche(scores: dict) -> dict:
    """{id_marche: [preset_code]} depuis scores_matching."""
    par_marche = defaultdict(list)
    for cle, sc in scores.items():
        if not isinstance(sc, dict):
            continue
        if "preset_code" in sc and sc.get("matche"):
            id_m = sc.get("marche_id") or cle.rsplit("_", 1)[0]
            par_marche[id_m].append(sc["preset_code"])
    return dict(par_marche)


def _charger_classifications_unifiees() -> dict:
    """
    Charge les classifications depuis les 2 sources, en privilégiant le
    brief COMPLET (plus précis car lit le DCE) quand il existe :
    - Source 1 : `briefs_extraits` (brief COMPLET avec domaines_metier)
    - Source 2 : `classifications_ia` (Sprint 2 — classification IA sur métadonnées)

    Returns:
        {id_marche: {"domaines": [(code, poids, lots)],
                     "raison": str, "source": "brief_complet"|"classification_ia"}}
    """
    # Source 1 : briefs COMPLET (priorité)
    briefs = {}
    try:
        briefs = dict(stockage.charger("briefs_extraits") or {})
    except Exception:
        pass
    if REPERTOIRE_EXTRACTIONS.exists():
        for f in REPERTOIRE_EXTRACTIONS.glob("*.json"):
            if f.stem.startswith("_"):
                continue
            if f.stem not in briefs:
                try:
                    briefs[f.stem] = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    pass

    # Source 2 : classifications IA (Sprint 2)
    classifs_ia = {}
    try:
        classifs_ia = dict(stockage.charger("classifications_ia") or {})
    except Exception:
        pass

    # Unification
    unifie = {}
    # On commence par classifications_ia (couverture large)
    for id_m, c in classifs_ia.items():
        doms = _normaliser_domaines(c.get("domaines_metier"))
        if doms:
            unifie[id_m] = {
                "domaines": doms,
                "raison": c.get("raison_classification", ""),
                "source": "classification_ia",
            }
    # Override par briefs COMPLET (plus précis)
    for id_m, brief in briefs.items():
        doms = _normaliser_domaines(brief.get("domaines_metier"))
        if doms:
            unifie[id_m] = {
                "domaines": doms,
                "raison": brief.get("raison_classification", ""),
                "source": "brief_complet",
            }
    return unifie


def _normaliser_domaines(raw) -> list:
    """Convertit domaines_metier en liste de tuples (code, poids, lots)."""
    if not isinstance(raw, list):
        return []
    codes = []
    for d in raw:
        if isinstance(d, dict) and d.get("code"):
            codes.append((d["code"], d.get("poids"), d.get("lots_concernes")))
    return codes


def _domaines_du_brief(brief: dict) -> list:
    """Compat backward (utilise _normaliser_domaines)."""
    return _normaliser_domaines(brief.get("domaines_metier"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conflits", action="store_true",
                    help="Affiche le détail des cas suspects (preset matche "
                         "mais domaine LLM hors domaines_acceptes)")
    ap.add_argument("--preset",
                    help="Filtre sur un preset spécifique")
    args = ap.parse_args()

    print("=" * 78)
    print("  Audit des classifications LLM (domaines_metier)")
    print("=" * 78)

    marches = stockage.charger("marches") or {}
    classifs_unifiees = _charger_classifications_unifiees()
    scores = stockage.charger("scores_matching") or {}
    taxonomie = _charger_taxonomie()
    presets = _charger_presets()
    presets_par_marche = _presets_matches_par_marche(scores)

    # Stats par source pour visibilité
    par_source = Counter(c["source"] for c in classifs_unifiees.values())

    print(f"\n  Marchés en base       : {len(marches)}")
    print(f"  Classifications totales : {len(classifs_unifiees)}")
    for source, n in par_source.most_common():
        label = "brief COMPLET (DCE lu)" if source == "brief_complet" else "classification IA (métadonnées)"
        print(f"    · depuis {label:<35} : {n}")
    print(f"  Taxonomie chargée     : {len(taxonomie)} domaines")
    print(f"  Presets installés     : {', '.join(presets.keys()) or '(aucun)'}")
    print(f"\n  Couverture            : "
          f"{len(classifs_unifiees) * 100 // max(len(marches), 1)}% "
          f"des marchés ont une classification")

    if not classifs_unifiees:
        print()
        print(f"  Aucune classification disponible.")
        print(f"  Lance : python tendia_classification.py --backfill")
        return

    # Distribution des domaines (principal = poids max ou 1er si pas de poids)
    distribution_principal = Counter()
    distribution_tous = Counter()
    for c in classifs_unifiees.values():
        doms = c["domaines"]
        if not doms:
            continue
        principal = max(doms, key=lambda x: x[1] or 1.0)
        distribution_principal[principal[0]] += 1
        for code, _, _ in doms:
            distribution_tous[code] += 1

    print(f"\n  ── Distribution des domaines (principal) ──")
    for code, n in distribution_principal.most_common():
        libelle = (taxonomie.get(code) or {}).get("libelle", code)
        pct = n * 100 // len(classifs_unifiees)
        print(f"    {n:>3}  ({pct:>2}%)  {code:<45}  {libelle}")

    n_multi = sum(1 for c in classifs_unifiees.values() if len(c["domaines"]) > 1)
    if n_multi:
        print(f"\n  Marchés multi-domaines (2-3 domaines) : {n_multi}")

    # Alignement preset / domaine
    if presets:
        print(f"\n  ── Alignement preset-matching (keyword) ↔ classification IA ──")
        conflits = []
        verses = defaultdict(lambda: {"alignes": 0, "conflits": 0, "optionnels": 0})

        for id_m, c in classifs_unifiees.items():
            doms = c["domaines"]
            if not doms:
                continue
            principal_code = max(doms, key=lambda x: x[1] or 1.0)[0]
            presets_m = presets_par_marche.get(id_m, [])

            for preset_code in presets_m:
                if args.preset and preset_code != args.preset:
                    continue
                p = presets.get(preset_code, {})
                acceptes = set(p.get("domaines_acceptes") or [])
                optionnels = set(p.get("domaines_optionnels") or [])
                if principal_code in acceptes:
                    verses[preset_code]["alignes"] += 1
                elif principal_code in optionnels:
                    verses[preset_code]["optionnels"] += 1
                else:
                    verses[preset_code]["conflits"] += 1
                    conflits.append((id_m, preset_code, principal_code,
                                     c["raison"], c["source"]))

        for preset_code, stats in sorted(verses.items()):
            total = sum(stats.values())
            if total == 0:
                continue
            print(f"\n    Preset '{preset_code}' — {total} marchés matchés par keyword :")
            print(f"      ✓ Alignés (domaine LLM ∈ domaines_acceptes) : "
                  f"{stats['alignes']}")
            print(f"      ~ Optionnels (∈ domaines_optionnels)         : "
                  f"{stats['optionnels']}")
            print(f"      ✗ Conflits (hors acceptés/optionnels)        : "
                  f"{stats['conflits']}")
            taux = stats['alignes'] * 100 // total
            print(f"      Taux d'alignement : {taux}% "
                  f"(= % de vrais positifs du matching keyword)")

        # Marchés qui matchent un preset DOMAINE_ACCEPTE mais ne sont pas matchés par keyword
        # (vrais positifs LLM que le keyword loupe)
        print(f"\n  ── Vrais positifs LLM manqués par le matching keyword ──")
        for preset_code, p in presets.items():
            if args.preset and preset_code != args.preset:
                continue
            acceptes = set(p.get("domaines_acceptes") or [])
            optionnels = set(p.get("domaines_optionnels") or [])
            manques = []
            for id_m, c in classifs_unifiees.items():
                principal = max(c["domaines"], key=lambda x: x[1] or 1.0)[0]
                if principal not in acceptes and principal not in optionnels:
                    continue
                # LLM dit oui, keyword dit oui ?
                if preset_code in presets_par_marche.get(id_m, []):
                    continue  # déjà matché, ok
                manques.append((id_m, principal))
            print(f"\n    Preset '{preset_code}' : "
                  f"{len(manques)} marchés que le LLM classifie en domaine "
                  f"accepté mais que le matching keyword n'a PAS détectés")
            if manques and not args.conflits:
                # Aperçu : montrer les 5 premiers
                for id_m, dom in manques[:5]:
                    titre = (marches.get(id_m, {}).get("titre") or "?")[:55]
                    print(f"      · {id_m}  [{dom}]  {titre}")
                if len(manques) > 5:
                    print(f"      ... +{len(manques)-5} autres "
                          f"(utilise --conflits pour tout voir)")

        if args.conflits and conflits:
            print(f"\n  ── Détail des conflits ({len(conflits)} cas) ──")
            for id_m, preset_code, dom_llm, raison, source in conflits[:30]:
                m = marches.get(id_m, {})
                titre = (m.get("titre") or "?")[:60]
                print(f"\n    {id_m}  [{source}]")
                print(f"      preset keyword = {preset_code} → LLM classe = {dom_llm}")
                print(f"      titre : {titre}")
                if raison:
                    print(f"      raison LLM : {raison[:140]}")

    # Marchés en 'autre'
    n_autre = distribution_principal.get("autre", 0)
    if n_autre:
        print(f"\n  ⚠ {n_autre} marché(s) classés en 'autre' — taxonomie potentiellement incomplète")
        for id_m, c in classifs_unifiees.items():
            principal = max(c["domaines"], key=lambda x: x[1] or 1.0)[0]
            if principal == "autre":
                titre = (marches.get(id_m, {}).get("titre") or "?")[:60]
                raison = c["raison"]
                print(f"    {id_m}  {titre}")
                if raison:
                    print(f"      raison : {raison[:120]}")

    print()


if __name__ == "__main__":
    main()
