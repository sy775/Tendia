"""
Diagnostic Phase 2A — Pourquoi les briefs sont absents.

Objectif : comprendre pourquoi 320/422 marchés n'ont pas de brief alors que
414/422 ont un DCE téléchargé. Trois pistes à investiguer :

  Q1 — Que contiennent les répertoires DCE pour les marchés sans brief ?
       (vides ? PDF lisibles ? HTML de login ? rien d'utile ?)

  Q2 — Les 161 marchés "sans URL DCE détectable" sont-ils des marchés simples
       sans DCE, ou ont-ils une URL stockée dans un champ non scanné ?

  Q3 — Y a-t-il un log d'erreur (collection llm_appels ou autre) qui révèle
       pourquoi l'extraction n'a pas tourné sur ces marchés ?

Lance-le tel quel :  python diagnostic_briefs_absents.py
Lecture seule, ne touche RIEN.
"""
import io
import sys
import os
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime

# Force UTF-8 pour Windows PowerShell
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = "data/tendia.db"
DCE_DIR = "data/dce"


def charger_collection(conn, nom):
    cur = conn.execute(
        "SELECT id, contenu_json FROM kv_storage WHERE collection=?", (nom,)
    )
    res = {}
    for k, v in cur.fetchall():
        try:
            res[k] = json.loads(v)
        except Exception:
            res[k] = None
    return res


def inspecter_dossier_dce(dossier):
    """Renvoie {'taille_totale': int, 'fichiers': [(nom, taille, type), ...]}."""
    if not os.path.isdir(dossier):
        return None
    out = {"taille_totale": 0, "fichiers": []}
    try:
        for entry in os.listdir(dossier):
            chemin = os.path.join(dossier, entry)
            if os.path.isfile(chemin):
                taille = os.path.getsize(chemin)
                ext = os.path.splitext(entry)[1].lower().lstrip(".")
                out["taille_totale"] += taille
                out["fichiers"].append((entry, taille, ext))
    except Exception as e:
        out["erreur"] = str(e)
    return out


def deviner_nature_dce(inspection):
    """Heuristique : que contient ce dossier DCE ?"""
    if not inspection:
        return "dossier_absent"
    if not inspection["fichiers"]:
        return "dossier_vide"
    types = Counter(f[2] for f in inspection["fichiers"])
    taille_totale = inspection["taille_totale"]

    if taille_totale < 5_000:  # < 5 ko = quasi vide
        return "tres_leger_<5ko"

    # Si que du HTML et taille faible → page de login probable
    if types.get("html", 0) >= 1 and "pdf" not in types and taille_totale < 100_000:
        return "html_login_probable"

    if types.get("pdf", 0) >= 1:
        return f"pdf_present ({types.get('pdf')} PDF)"
    if types.get("zip", 0) >= 1:
        return f"zip_present ({types.get('zip')} ZIP)"
    if types.get("html", 0) >= 1:
        return f"html_seul ({types.get('html')} HTML)"
    if types.get("doc", 0) + types.get("docx", 0) >= 1:
        return "doc_word_present"

    return f"divers ({dict(types)})"


def cles_marche(marche):
    """Liste toutes les clés top-level d'un marché pour inspection."""
    if not marche or not isinstance(marche, dict):
        return []
    return sorted(marche.keys())


def dump_marche_compact(marche, max_chars=400):
    """Aperçu compact d'un marché pour inspection visuelle."""
    if not marche:
        return "(vide)"
    out = []
    for k, v in marche.items():
        if isinstance(v, str):
            out.append(f"  {k}: {v[:80]!r}")
        elif isinstance(v, (int, float, bool)):
            out.append(f"  {k}: {v}")
        elif isinstance(v, list):
            out.append(f"  {k}: list[{len(v)}]")
        elif isinstance(v, dict):
            out.append(f"  {k}: dict[{len(v)} clés]")
        else:
            out.append(f"  {k}: {type(v).__name__}")
    return "\n".join(out)[:max_chars]


def main():
    if not os.path.exists(DB_PATH):
        print(f"ERREUR : {DB_PATH} introuvable. Lance depuis la racine Tendia.")
        sys.exit(1)

    print(f"=== DIAGNOSTIC BRIEFS ABSENTS — {datetime.now():%Y-%m-%d %H:%M} ===")
    print()

    conn = sqlite3.connect(DB_PATH)
    marches = charger_collection(conn, "marches")
    briefs = charger_collection(conn, "briefs_extraits")
    llm_appels = charger_collection(conn, "llm_appels")
    classifications = charger_collection(conn, "classifications_ia")
    conn.close()

    dce_repertoires = set(os.listdir(DCE_DIR)) if os.path.isdir(DCE_DIR) else set()

    sans_brief = [mid for mid in marches if mid not in briefs]
    print(f"Marchés sans brief        : {len(sans_brief)} / {len(marches)}")
    print(f"  parmi ceux avec DCE     : "
          f"{sum(1 for m in sans_brief if m in dce_repertoires)}")
    print(f"  parmi ceux sans DCE     : "
          f"{sum(1 for m in sans_brief if m not in dce_repertoires)}")
    print()

    # ============== Q1 — Contenu des dossiers DCE des marchés sans brief ==============
    print("=" * 70)
    print("Q1 — Que contiennent les dossiers DCE des marchés sans brief ?")
    print("=" * 70)

    natures = Counter()
    exemples_par_nature = defaultdict(list)

    for mid in sans_brief:
        if mid not in dce_repertoires:
            continue
        dossier = os.path.join(DCE_DIR, mid)
        inspection = inspecter_dossier_dce(dossier)
        nature = deviner_nature_dce(inspection)
        natures[nature] += 1
        if len(exemples_par_nature[nature]) < 3:
            taille_ko = (inspection["taille_totale"] / 1024) if inspection else 0
            fichiers_apercu = ", ".join(
                f"{f[0]}({f[1]}o)" for f in inspection["fichiers"][:3]
            ) if inspection and inspection["fichiers"] else "—"
            exemples_par_nature[nature].append(
                f"    {mid} | {taille_ko:.1f} ko | {fichiers_apercu}"
            )

    print(f"{'Nature contenu DCE':<35} {'Nb marchés sans brief':>22}")
    print("-" * 60)
    for nature, n in natures.most_common():
        print(f"{nature:<35} {n:>22}")
    print()
    print("Exemples par nature :")
    for nature in natures:
        print(f"\n--- {nature} ---")
        for ex in exemples_par_nature[nature]:
            print(ex)

    # ============== Q2 — Marchés sans URL DCE : pourquoi ? ==============
    print()
    print("=" * 70)
    print("Q2 — Marchés sans URL DCE détectable : qu'est-ce qu'ils ont vraiment ?")
    print("=" * 70)

    # Identifier les marchés sans URL — on réutilise une heuristique légère
    def a_url_dce(marche):
        if not marche:
            return False
        for cle in ("url_dce", "url_documents", "lien_dce", "lien_documents",
                    "url_consultation", "url_acces_dce"):
            v = marche.get(cle)
            if v and isinstance(v, str) and v.startswith("http"):
                return True
        # Cas BOAMP : URL souvent imbriquée
        for cle in ("liens", "documents", "donnees_brutes"):
            v = marche.get(cle)
            if isinstance(v, dict):
                for sub in v.values():
                    if isinstance(sub, str) and sub.startswith("http"):
                        return True
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, str) and item.startswith("http"):
                        return True
                    elif isinstance(item, dict):
                        for sub in item.values():
                            if isinstance(sub, str) and sub.startswith("http"):
                                return True
        return False

    sans_url = [mid for mid, m in marches.items() if not a_url_dce(m)]
    print(f"Marchés sans URL DCE : {len(sans_url)}")
    print()

    # Échantillon : combien ont quand même un dossier DCE ?
    sans_url_avec_dossier = [m for m in sans_url if m in dce_repertoires]
    sans_url_sans_dossier = [m for m in sans_url if m not in dce_repertoires]
    print(f"  avec dossier DCE quand même : {len(sans_url_avec_dossier)}")
    print(f"  sans dossier DCE             : {len(sans_url_sans_dossier)}")
    print()

    # Inspection des clés top-level pour 3 exemples
    print("Inspection des CLÉS top-level de 5 marchés sans URL DCE détectée :")
    print("  (objectif : trouver un champ que le script Phase 1 n'a pas scanné)")
    for i, mid in enumerate(sans_url[:5]):
        m = marches[mid]
        cles = cles_marche(m)
        print(f"\n  [{i+1}] {mid} (dossier DCE: "
              f"{'oui' if mid in dce_repertoires else 'non'})")
        print(f"      clés top-level : {cles}")
        # Trouver tout champ contenant une URL plausible
        urls_dans_marche = []
        if isinstance(m, dict):
            for k, v in m.items():
                if isinstance(v, str) and ("http://" in v or "https://" in v):
                    urls_dans_marche.append((k, v[:90]))
        if urls_dans_marche:
            print("      URL trouvées dans champs non scannés :")
            for k, v in urls_dans_marche[:5]:
                print(f"        {k}: {v}")
        else:
            print("      → AUCUNE URL trouvée nulle part dans ce marché.")

    # ============== Q3 — Logs LLM appels : erreurs d'extraction ? ==============
    print()
    print("=" * 70)
    print("Q3 — Logs llm_appels : y a-t-il des erreurs d'extraction tracées ?")
    print("=" * 70)
    print(f"llm_appels en base : {len(llm_appels)} entrées")
    print()

    if llm_appels:
        # Échantillon des clés pour comprendre la structure
        sample_id = next(iter(llm_appels))
        sample_data = llm_appels[sample_id]
        print(f"Exemple d'entrée (id={sample_id}) :")
        print(dump_marche_compact(sample_data, max_chars=500))
        print()

        # Compter par statut si une clé 'statut' / 'success' / 'erreur' existe
        statuts = Counter()
        types_appels = Counter()
        appels_par_marche = defaultdict(list)
        erreurs_examples = []

        for aid, a in llm_appels.items():
            if not a:
                continue
            statut = a.get("statut") or a.get("status") or (
                "erreur" if a.get("erreur") or a.get("error") else "ok"
            )
            statuts[statut] += 1
            type_appel = a.get("type") or a.get("operation") or "?"
            types_appels[type_appel] += 1
            # Tenter de rattacher à un marché
            mid = a.get("marche_id") or a.get("id_marche") or a.get("marche")
            if mid:
                appels_par_marche[mid].append((type_appel, statut))
            if statut not in ("ok", "success", "succes") and len(erreurs_examples) < 5:
                erreurs_examples.append((aid, a.get("erreur") or a.get("error") or
                                         a.get("message") or "(?)"))

        print(f"Statuts observés : {dict(statuts)}")
        print(f"Types d'appels   : {dict(types_appels)}")
        print(f"Marchés ayant ≥1 appel LLM tracé : {len(appels_par_marche)}")
        print(f"  → sans brief malgré appel LLM tracé : "
              f"{sum(1 for m in appels_par_marche if m in sans_brief)}")
        print()
        if erreurs_examples:
            print("Exemples d'appels en erreur :")
            for aid, msg in erreurs_examples:
                print(f"  {aid} : {str(msg)[:200]}")

    # ============== Focus achatpublic : 46 DCE, 0 brief ==============
    print()
    print("=" * 70)
    print("Focus — achatpublic : 46 DCE téléchargés, 0 brief.")
    print("=" * 70)

    achatpublic_ids = []
    for mid, m in marches.items():
        if not m:
            continue
        # Repérage URL achatpublic
        json_str = json.dumps(m, ensure_ascii=False)
        if "achatpublic" in json_str.lower():
            achatpublic_ids.append(mid)

    print(f"Marchés détectés avec URL achatpublic : {len(achatpublic_ids)}")

    natures_ach = Counter()
    for mid in achatpublic_ids:
        if mid in dce_repertoires:
            dossier = os.path.join(DCE_DIR, mid)
            inspection = inspecter_dossier_dce(dossier)
            natures_ach[deviner_nature_dce(inspection)] += 1
    print(f"Nature contenu DCE achatpublic : {dict(natures_ach)}")
    print()
    if achatpublic_ids:
        print("3 exemples détaillés :")
        for mid in achatpublic_ids[:3]:
            print(f"\n  --- {mid} ---")
            dossier = os.path.join(DCE_DIR, mid)
            inspection = inspecter_dossier_dce(dossier)
            if inspection:
                print(f"      taille totale : {inspection['taille_totale']} o")
                for f in inspection["fichiers"][:5]:
                    print(f"      fichier : {f[0]} | {f[1]} o | type={f[2]}")
                if not inspection["fichiers"]:
                    print("      (dossier vide)")
            else:
                print("      (pas de dossier DCE)")

    # ============== Synthèse ==============
    print()
    print("=" * 70)
    print("SYNTHÈSE POUR PRIORISATION FIX EXTRACTION")
    print("=" * 70)

    print()
    print(f"  Marchés briefés         : {len(briefs)} / {len(marches)} "
          f"({len(briefs)/len(marches)*100:.0f}%)")
    print(f"  Sans brief malgré DCE   : "
          f"{sum(1 for m in sans_brief if m in dce_repertoires)}")
    print(f"  Sans brief et sans DCE  : "
          f"{sum(1 for m in sans_brief if m not in dce_repertoires)}")
    print()

    if natures:
        print("Causes probables (briefs absents malgré DCE) :")
        for nature, n in natures.most_common():
            if "vide" in nature or "leger" in nature or "html_login" in nature:
                print(f"  ✗ {nature:<30} : {n} marchés → DCE inutilisable, "
                      f"fix au niveau téléchargement nécessaire")
            elif "pdf" in nature or "zip" in nature or "doc" in nature:
                print(f"  ⚠ {nature:<30} : {n} marchés → DCE OK, "
                      f"extraction LLM n'a pas tourné → fix llm_extract")

    print()
    print("=" * 70)
    print("FIN DIAGNOSTIC PHASE 2A")
    print("=" * 70)


if __name__ == "__main__":
    main()
