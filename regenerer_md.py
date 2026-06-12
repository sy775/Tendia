"""
regenerer_md.py
---------------
Regenere les fichiers .md de TOUS les briefs en cache (sans appel LLM).
Utile apres un refactor du rendu (Phase 3a preset-aware) pour mettre a jour
les rapports markdown sans recouter en regeneration LLM.

Usage PowerShell :
    python regenerer_md.py
"""
import io
import json
import sqlite3
import sys
from pathlib import Path

# Force UTF-8 pour les prints (compat cp1252 PowerShell)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import tendia_extraire

def main():
    db = Path("data/tendia.db")
    if not db.exists():
        print(f"DB introuvable : {db}")
        sys.exit(1)
    conn = sqlite3.connect(str(db))
    cur = conn.cursor()
    cur.execute("SELECT id, contenu_json FROM kv_storage WHERE collection='briefs_extraits'")
    briefs = [(r[0], json.loads(r[1])) for r in cur.fetchall()]
    cur.execute("SELECT id, contenu_json FROM kv_storage WHERE collection='marches'")
    marches = {r[0]: json.loads(r[1]) for r in cur.fetchall()}

    dossier = Path("rapports")
    dossier.mkdir(exist_ok=True)

    n_ok = 0
    n_skip = 0
    for bid, extraction in briefs:
        marche = marches.get(bid) or {"id": bid}
        try:
            md = tendia_extraire._generer_brief(marche, extraction)
            cible = dossier / f"brief_{bid}.md"
            cible.write_text(md, encoding="utf-8")
            n_ok += 1
        except Exception as e:
            print(f"  KO {bid} : {e}")
            n_skip += 1

    print(f"{n_ok} briefs MD regeneres dans {dossier}/ ({n_skip} skippes)")


if __name__ == "__main__":
    main()
