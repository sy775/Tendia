"""
tendia_matcher.py
-----------------
Script principal de matching organisme × marchés pour Tendia.

Lit le profil de l'organisme depuis data/organisme.json et la collection
des marchés depuis data/marches.json, évalue chaque marché contre le
profil, et produit un rapport markdown dans `rapports/matching_YYYY-MM-DD.md`.

Format du rapport : "pour toi" (dense, technique). Si tu veux le présenter
à un client, on adapte le rendu plus tard.

Usage :
    python tendia_matcher.py                  # rapport complet
    python tendia_matcher.py --filtre pertinent    # uniquement les pertinents+
    python tendia_matcher.py --top 20         # n premiers
    python tendia_matcher.py --console        # n'écrit pas de fichier
"""

import argparse
import os
import sys
from collections import Counter
from datetime import datetime

import stockage
import organisme
import matching


COLLECTION_MARCHES = "marches"
REPERTOIRE_RAPPORTS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "rapports"
)


# Ordre des verdicts pour l'affichage
ORDRE_VERDICTS = ["tres_pertinent", "pertinent", "a_verifier", "non_pertinent"]

LIBELLES_VERDICTS = {
    "tres_pertinent": "✅ Très pertinent",
    "pertinent": "🟢 Pertinent",
    "a_verifier": "🟡 À vérifier",
    "non_pertinent": "⚪ Non pertinent",
}


# ---------------------------------------------------------------------------
# Rendu d'un marché évalué
# ---------------------------------------------------------------------------

def _formatter_motifs(motifs: list) -> str:
    """Sérialise les motifs en une ligne compacte."""
    parts = []
    for m in motifs:
        critere = m["critere"]
        if m["satisfait"] is True:
            parts.append(f"{critere}+{m['points']}")
        elif m["satisfait"] is False:
            parts.append(f"{critere}{m['points']}")
        else:
            parts.append(f"{critere}?")
    return " | ".join(parts)


def _formatter_marche_detail(marche: dict, eval_: dict) -> list:
    """Produit les lignes markdown pour un marché évalué."""
    lignes = []
    titre = (marche.get("titre") or marche.get("objet") or "(sans titre)")[:140]

    lignes.append(f"### [{eval_['score']}] {titre}")
    lignes.append("")

    # Méta-données du marché
    src = marche.get("source", "?")
    ref = marche.get("reference_externe", "?")
    ach = marche.get("acheteur_nom", "?")
    date_pub = marche.get("date_publication", "?")
    date_lim = marche.get("date_limite_depot") or "(non précisée)"
    cat = marche.get("categorie_metier", "?")
    cpv = marche.get("cpv_principal") or "—"

    lignes.append(f"- **ID** : `{marche.get('id', '?')}` · **Source** : {src} "
                  f"· **Réf** : `{ref}`")
    lignes.append(f"- **Acheteur** : {ach}")
    lignes.append(f"- **Catégorie** : {cat} · **CPV** : {cpv}")
    lignes.append(f"- **Publié** : {date_pub} · **Limite dépôt** : {date_lim}")
    if marche.get("url_avis"):
        lignes.append(f"- **Avis** : <{marche['url_avis']}>")

    # Motifs détaillés
    lignes.append(f"")
    lignes.append(f"**Motifs** :")
    for m in eval_["motifs"]:
        marqueur = "✓" if m["satisfait"] is True else \
                   "✗" if m["satisfait"] is False else "·"
        pts = f"{m['points']:+d}" if m["points"] != 0 else " 0"
        lignes.append(f"  - {marqueur} [{pts}] **{m['critere']}** — "
                      f"{m['commentaire']}")
    lignes.append("")
    return lignes


# ---------------------------------------------------------------------------
# Génération du rapport markdown
# ---------------------------------------------------------------------------

def generer_rapport(organisme_dict: dict, evaluations: list,
                    filtre_verdict: str = None,
                    top: int = None) -> str:
    """Assemble le markdown complet."""
    horodatage = datetime.now().isoformat(timespec="seconds")
    lignes = [
        f"# Matching Tendia — {horodatage}",
        "",
        f"Organisme : **{organisme_dict.get('identite', {}).get('nom', '?')}**",
        "",
    ]

    # Diagnostic profil
    remplis = organisme.champs_remplis(organisme_dict)
    manquants = [k for k, v in remplis.items() if not v]
    if manquants:
        lignes.append(f"> ⚠ Sections du profil non remplies : "
                      f"{', '.join(manquants)}. Le matcheur tourne en mode "
                      f"dégradé sur ces axes — édite `data/organisme.json` "
                      f"pour améliorer.")
        lignes.append("")

    # Distribution globale
    par_verdict = Counter(e["verdict"] for e in evaluations)
    lignes.append("## Synthèse")
    lignes.append("")
    lignes.append("| Verdict | Nombre |")
    lignes.append("|---|---|")
    for v in ORDRE_VERDICTS:
        lignes.append(f"| {LIBELLES_VERDICTS[v]} | {par_verdict.get(v, 0)} |")
    lignes.append(f"| **Total évalué** | **{len(evaluations)}** |")
    lignes.append("")

    # Filtrage selon options
    evaluations_a_afficher = list(evaluations)
    if filtre_verdict:
        if filtre_verdict == "pertinent":
            niveaux_ok = {"tres_pertinent", "pertinent"}
        elif filtre_verdict == "a_verifier":
            niveaux_ok = {"tres_pertinent", "pertinent", "a_verifier"}
        elif filtre_verdict in VERDICTS_VALIDES:
            niveaux_ok = {filtre_verdict}
        else:
            niveaux_ok = set(VERDICTS_VALIDES)
        evaluations_a_afficher = [e for e in evaluations_a_afficher
                                    if e["verdict"] in niveaux_ok]
    if top:
        evaluations_a_afficher = evaluations_a_afficher[:top]

    if not evaluations_a_afficher:
        lignes.append("")
        lignes.append("_Aucun marché ne correspond aux critères de filtrage._")
        return "\n".join(lignes)

    # Détail des marchés, regroupés par verdict
    par_verdict_liste: dict = {v: [] for v in ORDRE_VERDICTS}
    # Garder le mapping eval -> marché
    return _ecrire_section_marches(lignes, evaluations_a_afficher)


def _ecrire_section_marches(lignes: list, evaluations: list) -> str:
    """Écrit la section détaillée des marchés par verdict."""
    marches = stockage.charger(COLLECTION_MARCHES)

    par_verdict: dict = {v: [] for v in ORDRE_VERDICTS}
    for e in evaluations:
        m = marches.get(e["id_marche"])
        if m is None:
            continue
        par_verdict[e["verdict"]].append((m, e))

    for v in ORDRE_VERDICTS:
        items = par_verdict[v]
        if not items:
            continue
        lignes.append("")
        lignes.append("---")
        lignes.append("")
        lignes.append(f"## {LIBELLES_VERDICTS[v]} — {len(items)} marché(s)")
        lignes.append("")
        for m, e in items:
            lignes.extend(_formatter_marche_detail(m, e))

    return "\n".join(lignes)


VERDICTS_VALIDES = set(matching.VERDICTS)


# ---------------------------------------------------------------------------
# Écriture sur disque
# ---------------------------------------------------------------------------

def _chemin_rapport_defaut() -> str:
    dat = datetime.now().strftime("%Y-%m-%d")
    os.makedirs(REPERTOIRE_RAPPORTS, exist_ok=True)
    return os.path.join(REPERTOIRE_RAPPORTS, f"matching_{dat}.md")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Matching organisme × marchés (Tendia P1)."
    )
    parser.add_argument("--filtre", choices=["pertinent", "a_verifier",
                                              "tres_pertinent", "non_pertinent"],
                        default=None,
                        help="Limite le rapport à un niveau de verdict.")
    parser.add_argument("--top", type=int, default=None,
                        help="N premiers marchés affichés.")
    parser.add_argument("--console", action="store_true",
                        help="Imprime sur stdout au lieu d'écrire un fichier.")
    parser.add_argument("--sortie", type=str, default=None,
                        help="Chemin du fichier markdown de sortie.")
    args = parser.parse_args()

    # Charge le profil
    profil = organisme.lire_profil()
    if profil is None:
        print("❌ Aucun profil organisme. Crée d'abord data/organisme.json.")
        print("   Tu peux partir du template fourni ou faire :")
        print("     python organisme.py --init")
        sys.exit(1)

    # Charge les marchés
    marches = stockage.charger(COLLECTION_MARCHES)
    if not marches:
        print("❌ Aucun marché en base. Lance d'abord :")
        print("     python tendia_recup.py")
        sys.exit(1)

    print(f"Organisme : {profil.get('identite', {}).get('nom', '?')}")
    print(f"Marchés à évaluer : {len(marches)}")
    print("Évaluation en cours...")

    # Sprint B : on passe les briefs extraits a matching pour activer le
    # scoring sectoriel (BTP qualifications, corps_metier, types_ouvrages).
    briefs = stockage.charger("briefs_extraits") or {}
    evaluations = matching.evaluer_tous(profil, marches, briefs=briefs)

    rapport = generer_rapport(profil, evaluations,
                                filtre_verdict=args.filtre,
                                top=args.top)

    if args.console:
        print(rapport)
    else:
        chemin = args.sortie or _chemin_rapport_defaut()
        with open(chemin, "w", encoding="utf-8") as f:
            f.write(rapport)
        print(f"\n📄 Rapport écrit : {chemin}")

        # Bilan court en console
        par_verdict = Counter(e["verdict"] for e in evaluations)
        print(f"\nBilan :")
        for v in ORDRE_VERDICTS:
            print(f"  {LIBELLES_VERDICTS[v]:<20} : {par_verdict.get(v, 0)}")


if __name__ == "__main__":
    main()
