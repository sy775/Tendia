"""
identifier_briefs_pollues.py
----------------------------
Identifie les briefs COMPLET qui doivent etre regenerees Phase 3c :
- briefs dont la classification IA mappe a un preset connu
- mais dont le JSON contient encore des blocs heritage formation/EnR
  (publics_cibles, volumes_techniques) inadequats pour ce preset

Exclut :
- briefs LIGHT (jamais regen depuis avis BOAMP seul)
- briefs hors-preset (autre, assurance, fourniture_materiel, etc.)
- briefs deja regen Phase 3a/3b (depuis le 2026-06-12)

Usage PowerShell :
    python identifier_briefs_pollues.py             # affichage humain
    python identifier_briefs_pollues.py --ids       # juste les IDs (pour piper)
    python identifier_briefs_pollues.py --csv       # CSV pour suivi
"""
import argparse
import io
import json
import sqlite3
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import preset

# Seuil temporel : briefs avec extraction_le APRES cette date sont consideres
# comme deja regen Phase 3a/3b. A ajuster si necessaire.
SEUIL_DEJA_REGEN = "2026-06-12T00:00"


def identifier():
    preset.recharger()
    db = Path("data/tendia.db")
    if not db.exists():
        print(f"DB introuvable : {db}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(str(db))
    cur = conn.cursor()
    cur.execute("SELECT id, contenu_json FROM kv_storage WHERE collection='briefs_extraits'")
    briefs = [(r[0], json.loads(r[1])) for r in cur.fetchall()]
    cur.execute("SELECT id, contenu_json FROM kv_storage WHERE collection='classifications_ia'")
    classifs = {r[0]: json.loads(r[1]) for r in cur.fetchall()}

    a_regen = []
    skip_light = 0
    skip_recent = 0
    skip_hors_preset = 0
    skip_propre = 0

    for bid, b in briefs:
        meta = b.get("_meta", {}) or {}
        if meta.get("type") != "complet":
            skip_light += 1
            continue
        extraction_le = meta.get("extraction_le", "") or ""
        if extraction_le >= SEUIL_DEJA_REGEN:
            skip_recent += 1
            continue
        c = classifs.get(bid, {}) or {}
        codes = [d.get("code") for d in (c.get("domaines_metier") or [])
                 if isinstance(d, dict)]
        presets_cibles = preset.presets_pour_domaines(codes)
        if not presets_cibles:
            skip_hors_preset += 1
            continue
        # Detection pollution : un bloc heritage non-pertinent pour ce preset
        pollu = False
        if b.get("publics_cibles") and "formation" not in presets_cibles:
            pollu = True
        if b.get("volumes_techniques") and "energie_renouvelable" not in presets_cibles:
            pollu = True
        if b.get("modalites_execution_chantier") and "energie_renouvelable" not in presets_cibles:
            pollu = True
        if not pollu:
            skip_propre += 1
            continue
        a_regen.append({
            "id": bid,
            "classif_codes": codes,
            "presets_cibles": presets_cibles,
            "extraction_le": extraction_le[:16],
            "titre": (b.get("synthese_marche") or "")[:80],
        })

    return a_regen, {
        "skip_light": skip_light,
        "skip_recent": skip_recent,
        "skip_hors_preset": skip_hors_preset,
        "skip_propre": skip_propre,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", action="store_true",
                    help="Sortie : juste les IDs (un par ligne, pour pipe)")
    ap.add_argument("--csv", action="store_true",
                    help="Sortie : CSV avec id,classif,presets,date")
    args = ap.parse_args()

    a_regen, stats = identifier()

    if args.ids:
        for item in a_regen:
            print(item["id"])
        return

    if args.csv:
        print("id;classif_codes;presets_cibles;extraction_le")
        for item in a_regen:
            print(f"{item['id']};"
                  f"{','.join(item['classif_codes'])};"
                  f"{','.join(item['presets_cibles'])};"
                  f"{item['extraction_le']}")
        return

    # Affichage humain
    print(f"\n{'='*80}")
    print(f"  Phase 3c — briefs a regenerer")
    print(f"{'='*80}")
    print(f"  Skippes LIGHT          : {stats['skip_light']}")
    print(f"  Skippes deja regen     : {stats['skip_recent']}")
    print(f"  Skippes hors-preset    : {stats['skip_hors_preset']}")
    print(f"  Skippes deja propres   : {stats['skip_propre']}")
    print(f"  -> A regenerer         : {len(a_regen)}")
    print(f"  -> Cout LLM estime     : ~{len(a_regen) * 0.16:.2f} EUR")
    print()
    for i, item in enumerate(a_regen, 1):
        print(f"  [{i:>2}/{len(a_regen)}] {item['id']}")
        print(f"         classif : {item['classif_codes']}")
        print(f"         presets : {item['presets_cibles']}")
        print(f"         extr    : {item['extraction_le']}")
        if item['titre']:
            print(f"         titre   : {item['titre']}")


if __name__ == "__main__":
    main()
