"""
audit_presets_extraction.py
---------------------------
Audit (LECTURE SEULE) de la richesse des champs `prompt_extraction` et
`vocabulaire_llm` des 6 presets, par rapport au gabarit le plus complet (BTP).
Produit `audit_presets_extraction.md`. Sous-chantier 1A.1.

Usage : python audit_presets_extraction.py
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).parent / "presets"
GABARIT = "btp"  # preset de référence (le plus complet)
SORTIE = "audit_presets_extraction.md"

SOUS_CLES_PE = ["description", "bloc_schema_specifique", "regles_specifiques",
                "exemples_elements_a_chiffrer", "hints_calcul_montant",
                "few_shot_examples"]
SOUS_CLES_VOC = ["description", "secteur_libelle", "type_pieces_dce_typiques",
                 "type_repondant", "unite_principale_facturation",
                 "references_attendues", "alertes_typiques", "exemples_synthese"]


def _presets():
    out = {}
    for sub in sorted(BASE.iterdir()):
        f = sub / "_preset.json"
        if sub.is_dir() and f.is_file():
            try:
                out[sub.name] = json.loads(f.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"  ! {sub.name}: {e}")
    return out


def _taille(v):
    """(présent, n_chars, n_items) — n_items si liste."""
    if v is None or v == "" or v == [] or v == {}:
        return (False, 0, 0)
    if isinstance(v, list):
        return (True, len(json.dumps(v, ensure_ascii=False)), len(v))
    return (True, len(str(v)), 0)


def main():
    presets = _presets()
    L = []
    p = L.append
    p("# Audit richesse `prompt_extraction` / `vocabulaire_llm` par preset\n")
    p(f"_Lecture seule. Gabarit de référence : **{GABARIT}** (le plus complet). "
      f"Sous-chantier 1A.1._\n")
    p(f"Presets audités : {', '.join(presets.keys())}\n")

    # --- prompt_extraction ---
    p("## 1. `prompt_extraction` (sous-clés × presets)\n")
    p("Cellule = `chars` (ou `n items` pour les listes). `—` = ABSENT.\n")
    p("| Sous-clé | " + " | ".join(presets) + " |")
    p("|---" * (len(presets) + 1) + "|")
    for sc in SOUS_CLES_PE:
        cells = []
        for code, d in presets.items():
            pe = d.get("prompt_extraction", {}) or {}
            present, n, items = _taille(pe.get(sc))
            cells.append(f"{n}c" if present and not items else (f"{items} items" if items else "—"))
        p(f"| `{sc}` | " + " | ".join(cells) + " |")
    p("")

    # --- vocabulaire_llm ---
    p("## 2. `vocabulaire_llm` (sous-clés × presets)\n")
    p("| Sous-clé | " + " | ".join(presets) + " |")
    p("|---" * (len(presets) + 1) + "|")
    for sc in SOUS_CLES_VOC:
        cells = []
        for code, d in presets.items():
            voc = d.get("vocabulaire_llm", {}) or {}
            present, n, items = _taille(voc.get(sc))
            cells.append(f"{n}c" if present and not items else (f"{items} items" if items else "—"))
        p(f"| `{sc}` | " + " | ".join(cells) + " |")
    p("")

    # --- Manques par preset vs gabarit ---
    p("## 3. Manques par preset (vs gabarit `btp`)\n")
    gab = presets.get(GABARIT, {})
    gab_pe = set(k for k in (gab.get("prompt_extraction") or {}) if _taille((gab.get("prompt_extraction") or {}).get(k))[0])
    gab_voc = set(k for k in (gab.get("vocabulaire_llm") or {}) if _taille((gab.get("vocabulaire_llm") or {}).get(k))[0])
    p("| Preset | prompt_extraction manquants | vocabulaire_llm manquants |")
    p("|---|---|---|")
    for code, d in presets.items():
        pe = d.get("prompt_extraction", {}) or {}
        voc = d.get("vocabulaire_llm", {}) or {}
        miss_pe = [k for k in gab_pe if not _taille(pe.get(k))[0]]
        miss_voc = [k for k in gab_voc if not _taille(voc.get(k))[0]]
        # few_shot_examples : nouveau champ 1B, manquant partout au départ
        if not _taille(pe.get("few_shot_examples"))[0]:
            miss_pe = miss_pe + ["few_shot_examples (nouveau 1B)"]
        p(f"| {code} | {', '.join(miss_pe) or '✓ complet'} | {', '.join(miss_voc) or '✓ complet'} |")
    p("")

    # --- Sous-développés (présents mais courts vs gabarit) ---
    p("## 4. Champs présents mais SOUS-DÉVELOPPÉS (vs gabarit)\n")
    p("Seuil : < 60% de la taille du même champ chez `btp`.\n")
    p("| Preset | Champ | Taille | Gabarit btp | Ratio |")
    p("|---|---|---|---|---|")
    for famille, sous_cles, cle_top in [("PE", SOUS_CLES_PE, "prompt_extraction"),
                                         ("VOC", SOUS_CLES_VOC, "vocabulaire_llm")]:
        for sc in sous_cles:
            g_present, g_n, _ = _taille((gab.get(cle_top) or {}).get(sc))
            if not g_present or g_n == 0:
                continue
            for code, d in presets.items():
                if code == GABARIT:
                    continue
                present, n, _ = _taille((d.get(cle_top) or {}).get(sc))
                if present and n < 0.6 * g_n:
                    p(f"| {code} | {famille}.`{sc}` | {n}c | {g_n}c | {100*n//g_n}% |")
    p("")

    Path(SORTIE).write_text("\n".join(L), encoding="utf-8")
    print(f"✅ {SORTIE} écrit ({len(L)} lignes)")


if __name__ == "__main__":
    main()
