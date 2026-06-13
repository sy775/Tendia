"""
purger_briefs_faux.py
---------------------
Détecte et purge les briefs LLM générés sur des DCE en réalité vides
(faux_succes_depot_pli, espace_acheteur, DCE sans documents exploitables).

Heuristique simple et robuste :
  → Si le dossier `data/dce/<id_marche>/` contient MOINS DE 2 documents
    métier (PDF/XLSX/DOCX, hors fichiers bruit comme depot-pli.pdf,
    DUME Acheteur, guides de dépôt), alors le brief est suspect : un vrai
    DCE contient toujours plusieurs pièces (RC + CCTP + CCAP + BPU minimum).

Le script :
1. Pour chaque brief en cache, inspecte le dossier DCE sur disque
2. Compte les fichiers métier (en excluant les patterns de bruit connus)
3. Liste les candidats à purger (dry-run par défaut)
4. Avec --appliquer : supprime de briefs_extraits SQLite + extractions/<id>.json
   + rapports/brief_<id>.md
5. Option --vers-suspect pour MARQUER au lieu de supprimer

Usage :
    python purger_briefs_faux.py                       # dry-run
    python purger_briefs_faux.py --seuil 2             # seuil personnalisé
    python purger_briefs_faux.py --appliquer           # supprime
    python purger_briefs_faux.py --appliquer --vers-suspect
"""

import argparse
import io
import json
import sys
from collections import Counter
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage


REPERTOIRE_BASE = Path(__file__).parent
REPERTOIRE_EXTRACTIONS = REPERTOIRE_BASE / "data" / "extractions"
REPERTOIRE_RAPPORTS = REPERTOIRE_BASE / "rapports"
REPERTOIRE_DCE = REPERTOIRE_BASE / "data" / "dce"

# Patterns indiquant un fichier de BRUIT (guide, formulaire vierge, etc.)
# qui ne compte pas comme "document DCE"
PATTERNS_BRUIT = (
    "depot-pli", "depot_pli", "depotpli",
    "guide-depot", "guide_depot", "guide-de-depot",
    "aide-en-ligne", "aide-depot", "aide_depot",
    "notice-depot", "notice_depot",
    "tuto-depot", "tutoriel-depot",
    "dume-acheteur", "dume_acheteur", "dume acheteur",
    "dume.pdf",
)

# Extensions considérées comme documents métier (les autres sont ignorées)
EXTENSIONS_METIER = (".pdf", ".xlsx", ".xlsm", ".docx", ".doc",
                     ".rtf", ".odt", ".ods")


def _est_fichier_bruit(nom: str) -> bool:
    nom_low = nom.lower()
    return any(pat in nom_low for pat in PATTERNS_BRUIT)


def _compter_docs_metier(dossier: Path) -> tuple:
    """
    Retourne (nb_docs_metier, liste_fichiers_metier, liste_fichiers_bruit).
    """
    if not dossier.is_dir():
        return 0, [], []
    metier = []
    bruit = []
    for f in dossier.iterdir():
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext not in EXTENSIONS_METIER:
            continue
        if _est_fichier_bruit(f.name):
            bruit.append(f.name)
        else:
            metier.append(f.name)
    return len(metier), metier, bruit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", default=True,
                    help="Affiche sans modifier (défaut)")
    ap.add_argument("--appliquer", action="store_true",
                    help="Applique réellement les suppressions")
    ap.add_argument("--vers-suspect", action="store_true",
                    help="Marque les briefs comme 'suspect_dce_vide' au lieu "
                         "de supprimer (pour audit)")
    ap.add_argument("--seuil", type=int, default=1,
                    help="Nombre minimum de documents métier pour qu'un brief "
                         "soit considéré comme valide (défaut: 1). "
                         "Avec seuil=1, on ne purge que les briefs sur dossiers "
                         "VIDES ou inexistants. Avec seuil=2, on est plus strict "
                         "mais on risque de purger des DCE compacts en RC unique.")
    args = ap.parse_args()

    if args.appliquer:
        args.dry_run = False

    print("=" * 78)
    print("  Purge des briefs LLM générés sur DCE quasi-vide")
    print("=" * 78)
    print(f"  Heuristique : un DCE valide doit contenir au moins {args.seuil} "
          f"documents métier")
    print(f"               (PDF/XLSX/DOCX, hors fichiers bruit comme "
          f"depot-pli.pdf)")
    if args.dry_run:
        print(f"  Mode DRY-RUN : aucune modification.")

    # Chargement
    marches = stockage.charger("marches") or {}
    briefs_sqlite = stockage.charger("briefs_extraits") or {}

    briefs_disque = {}
    if REPERTOIRE_EXTRACTIONS.exists():
        for f in REPERTOIRE_EXTRACTIONS.glob("*.json"):
            if f.stem == "_etat":  # fichier interne, à ignorer
                continue
            try:
                briefs_disque[f.stem] = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                pass

    tous_briefs_ids = set(briefs_sqlite.keys()) | set(briefs_disque.keys())
    # Filtre les IDs internes (genre "_etat")
    tous_briefs_ids = {i for i in tous_briefs_ids
                       if not i.startswith("_") and i in marches}

    print(f"\n  Marchés en base       : {len(marches)}")
    print(f"  Briefs SQLite         : {len(briefs_sqlite)}")
    print(f"  Briefs disque         : {len(briefs_disque)}")
    print(f"  Briefs uniques        : {len(tous_briefs_ids)}")

    # Analyse dossier par dossier
    a_purger = []  # liste de (id, nb_metier, liste_metier, liste_bruit)
    distribution_nb = Counter()
    sans_dossier = []

    for id_m in sorted(tous_briefs_ids):
        dossier = REPERTOIRE_DCE / id_m
        if not dossier.is_dir():
            sans_dossier.append(id_m)
            distribution_nb["sans_dossier"] += 1
            # Brief sans dossier DCE physique → suspect
            a_purger.append((id_m, 0, [], []))
            continue
        nb, metier, bruit = _compter_docs_metier(dossier)
        distribution_nb[nb] += 1
        if nb < args.seuil:
            a_purger.append((id_m, nb, metier, bruit))

    print(f"\n  Distribution nb de documents métier par dossier DCE :")
    for k in sorted(distribution_nb.keys(),
                    key=lambda x: -1 if x == "sans_dossier" else x):
        n = distribution_nb[k]
        label = (f"sans dossier" if k == "sans_dossier"
                 else f"{k} docs")
        marker = " ⚠ suspect" if k != "sans_dossier" and k < args.seuil else ""
        marker_no_dir = " ⚠ pas de DCE" if k == "sans_dossier" else marker
        print(f"    {label:<18} : {n}{marker_no_dir}")

    print(f"\n  ── À purger : {len(a_purger)} brief(s) (seuil < {args.seuil} docs) ──")
    for id_m, nb, metier, bruit in a_purger:
        m = marches.get(id_m, {})
        titre = (m.get("titre") or "?")[:55]
        print(f"\n    {id_m}  ({nb} docs métier)")
        print(f"      titre   : {titre}")
        if metier:
            print(f"      métier  : {', '.join(metier)[:75]}")
        if bruit:
            print(f"      bruit   : {', '.join(bruit)[:75]}")
        if not metier and not bruit:
            if id_m in sans_dossier:
                print(f"      (aucun dossier DCE sur disque)")
            else:
                print(f"      (dossier vide)")

    if not a_purger:
        print(f"\n  ✓ Aucun brief à purger.")
        return

    print(f"\n  ── Impact estimé ──")
    print(f"  Briefs SQLite à toucher : "
          f"{sum(1 for i, _, _, _ in a_purger if i in briefs_sqlite)}")
    print(f"  Briefs disque à toucher : "
          f"{sum(1 for i, _, _, _ in a_purger if i in briefs_disque)}")
    n_markdown = sum(1 for i, _, _, _ in a_purger
                     if (REPERTOIRE_RAPPORTS / f"brief_{i}.md").is_file())
    print(f"  Markdown à toucher      : {n_markdown}")

    if args.dry_run:
        print()
        print(f"  → Pour appliquer : python purger_briefs_faux.py --appliquer")
        print(f"    (ajoute --vers-suspect pour MARQUER au lieu de supprimer)")
        return

    # Application
    print()
    if args.vers_suspect:
        print(f"  → Marquage en cours (statut=suspect_dce_vide)...")
        n_marques = 0
        for id_m, nb, metier, bruit in a_purger:
            if id_m in briefs_sqlite:
                brief = briefs_sqlite[id_m]
                meta = brief.get("_meta") or {}
                meta["suspect_dce_vide"] = True
                meta["nb_docs_metier"] = nb
                meta["fichiers_metier"] = metier
                brief["_meta"] = meta
                briefs_sqlite[id_m] = brief
                n_marques += 1
        stockage.sauver("briefs_extraits", briefs_sqlite)
        print(f"  ✓ {n_marques} briefs marqués 'suspect_dce_vide'.")
    else:
        print(f"  → Suppression en cours...")
        n_sql = n_disk = n_md = 0
        for id_m, _, _, _ in a_purger:
            if id_m in briefs_sqlite:
                del briefs_sqlite[id_m]
                n_sql += 1
            chemin_json = REPERTOIRE_EXTRACTIONS / f"{id_m}.json"
            if chemin_json.is_file():
                try:
                    chemin_json.unlink()
                    n_disk += 1
                except Exception:
                    pass
            chemin_md = REPERTOIRE_RAPPORTS / f"brief_{id_m}.md"
            if chemin_md.is_file():
                try:
                    chemin_md.unlink()
                    n_md += 1
                except Exception:
                    pass
        stockage.sauver("briefs_extraits", briefs_sqlite)
        print(f"  ✓ {n_sql} briefs SQLite supprimés.")
        print(f"  ✓ {n_disk} JSON disque supprimés.")
        print(f"  ✓ {n_md} markdown rendus supprimés.")

    print()
    print(f"  ── Prochaine étape ──")
    print(f"  Relancer la calibration (les briefs purgés ne consommeront plus) :")
    print(f"    python calibrer_briefs.py")


if __name__ == "__main__":
    main()
