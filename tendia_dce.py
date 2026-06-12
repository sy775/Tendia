"""
tendia_dce.py
-------------
Script principal de récupération des URLs DCE pour les marchés actifs.

Pour chaque marché dont la date limite de dépôt est >= aujourd'hui (ou
publié récemment sans date limite), on :
1. Récupère le record API source (BOAMP / TED)
2. Extrait l'URL DCE spécifique :
   - Soit directement depuis le champ eForms (qualité 'directe')
   - Soit en cherchant sur PLACE par référence interne FT (qualité 'via_keyword')
3. Stocke url_dce + reference_ft dans le marché en base
4. Génère un rapport markdown avec toutes les infos cliquables

Usage :
    python tendia_dce.py                  # marchés actifs uniquement
    python tendia_dce.py --jours 90       # fenêtre élargie
    python tendia_dce.py --tous           # tous les marchés en base
    python tendia_dce.py --dry-run        # affiche sans modifier la base
    python tendia_dce.py --rapport-seul   # ne refait pas la recherche, juste le rapport
"""

import argparse
import os
import sys
import time
from collections import Counter
from datetime import date, datetime, timezone

import stockage
import dce_finder


COLLECTION_MARCHES = "marches"
REPERTOIRE_RAPPORTS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "rapports"
)
REPERTOIRE_DCE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "dce"
)


# ---------------------------------------------------------------------------
# Filtre marchés actifs
# ---------------------------------------------------------------------------

def _est_actif(marche: dict, fenetre_jours_sans_date: int = 60) -> bool:
    date_lim = marche.get("date_limite_depot")
    today = date.today().isoformat()
    if date_lim and len(date_lim) >= 10:
        return date_lim[:10] >= today
    date_pub = marche.get("date_publication")
    if not date_pub or len(date_pub) < 10:
        return False
    try:
        d = date.fromisoformat(date_pub[:10])
        return (date.today() - d).days <= fenetre_jours_sans_date
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Traitement principal : recherche URLs DCE
# ---------------------------------------------------------------------------

def traiter(filtre_actifs: bool = True,
            fenetre_jours_sans_date: int = 60,
            dry_run: bool = False,
            verbose: bool = True) -> dict:
    marches = stockage.charger(COLLECTION_MARCHES)
    if not marches:
        print("❌ Aucun marché en base. Lance d'abord : python tendia_recup.py")
        sys.exit(1)

    if filtre_actifs:
        marches_a_traiter = {
            mid: m for mid, m in marches.items()
            if _est_actif(m, fenetre_jours_sans_date)
        }
    else:
        marches_a_traiter = marches

    if verbose:
        print()
        print("=" * 78)
        print(f"  TENDIA — Recherche d'URLs DCE")
        print("=" * 78)
        print(f"  Marchés en base    : {len(marches)}")
        print(f"  Marchés à traiter  : {len(marches_a_traiter)} "
              f"({'actifs uniquement' if filtre_actifs else 'tous'})")
        print()

    if not marches_a_traiter:
        if verbose:
            print("  ⚠ Aucun marché à traiter.")
        return {}

    stats = {
        "total": 0,
        "par_qualite": Counter(),
        "avec_ref_ft": 0,
        "avec_url_dce": 0,
    }
    horodatage = datetime.now(timezone.utc).isoformat()

    for i, (mid, marche) in enumerate(marches_a_traiter.items(), 1):
        if verbose:
            titre = (marche.get("titre") or marche.get("objet") or "?")[:75]
            print(f"  [{i}/{len(marches_a_traiter)}] {marche.get('source')} - {titre}")

        resultat = dce_finder.trouver_urls_dce(marche, verbose=False)
        stats["total"] += 1
        qualite = resultat.get("qualite", "absente")
        stats["par_qualite"][qualite] += 1

        if resultat.get("reference_ft"):
            stats["avec_ref_ft"] += 1
        if resultat.get("url_dce"):
            stats["avec_url_dce"] += 1

        if verbose:
            print(f"      → qualité : {qualite}")
            if resultat.get("reference_ft"):
                print(f"        réf FT : {resultat['reference_ft']}")
            if resultat.get("url_dce"):
                print(f"        URL DCE : {resultat['url_dce'][:100]}")

        # Mise à jour du marché en base
        if not dry_run:
            marche["url_dce"] = resultat.get("url_dce")
            marche["reference_ft"] = resultat.get("reference_ft")
            marche["url_recherche_place"] = resultat.get("url_recherche")
            marche["dce_qualite"] = qualite
            marche["dce_recherche_le"] = horodatage
            stockage.ecrire(COLLECTION_MARCHES, mid, marche)

        # Politesse entre fetchs
        time.sleep(0.3)

    if verbose:
        print()
        print("─" * 78)
        print("  Bilan")
        print("─" * 78)
        print(f"  Marchés traités          : {stats['total']}")
        print(f"  Avec référence FT extraite : {stats['avec_ref_ft']}")
        print(f"  Avec URL DCE              : {stats['avec_url_dce']}")
        print(f"  Par qualité :")
        for q, n in stats["par_qualite"].most_common():
            print(f"    {q:<12} : {n}")

    return stats


# ---------------------------------------------------------------------------
# Génération du rapport markdown
# ---------------------------------------------------------------------------

def _verdict_pour_profil(marche: dict, profil: dict) -> dict:
    """Calcule le verdict matching pour un marché contre un profil."""
    try:
        import matching
        # Sprint B : brief passe au matching pour scoring sectoriel.
        brief = stockage.lire("briefs_extraits", marche.get("id"))
        return matching.evaluer(profil, marche, brief=brief)
    except Exception:
        return None


def _dossier_dce_local(marche: dict) -> str:
    """Chemin local où l'utilisateur dépose les PDFs téléchargés."""
    mid = marche.get("id", "?")
    return os.path.join(REPERTOIRE_DCE, mid)


def generer_rapport(filtre_actifs: bool = True,
                     fenetre_jours_sans_date: int = 60) -> str:
    """Génère le rapport markdown des marchés actifs avec URLs DCE."""
    marches = stockage.charger(COLLECTION_MARCHES)

    if filtre_actifs:
        marches_filtres = [m for m in marches.values()
                            if _est_actif(m, fenetre_jours_sans_date)]
    else:
        marches_filtres = list(marches.values())

    # Charge le profil actif pour matcher
    try:
        import organisme
        profil = organisme.lire_profil()
    except Exception:
        profil = None

    # Trie par verdict (les plus pertinents en premier) si profil dispo
    if profil:
        ordre_verdict = {
            "tres_pertinent": 0, "pertinent": 1,
            "a_verifier": 2, "non_pertinent": 3,
        }
        for m in marches_filtres:
            v = _verdict_pour_profil(m, profil)
            m["_eval"] = v
        marches_filtres.sort(key=lambda m: (
            ordre_verdict.get((m.get("_eval") or {}).get("verdict"), 4),
            -((m.get("_eval") or {}).get("score", 0)),
        ))

    horodatage = datetime.now().isoformat(timespec="seconds")
    nom_org = (profil or {}).get("identite", {}).get("nom", "?")

    lignes = [
        f"# Marchés actifs Tendia — {horodatage}",
        "",
        f"Organisme : **{nom_org}**" if profil else "Organisme : (aucun profil actif)",
        f"Nombre de marchés : **{len(marches_filtres)}**",
        "",
        "---",
        "",
    ]

    if not marches_filtres:
        lignes.append("> Aucun marché actif à ce jour.")
        return "\n".join(lignes)

    verdict_emojis = {
        "tres_pertinent": "✅", "pertinent": "🟢",
        "a_verifier": "🟡", "non_pertinent": "⚪",
    }

    for marche in marches_filtres:
        eval_ = marche.get("_eval") or {}
        verdict = eval_.get("verdict", "?")
        score = eval_.get("score", 0)
        emoji = verdict_emojis.get(verdict, "❓")

        titre = (marche.get("titre") or marche.get("objet") or "?").strip()
        # Nettoyer le titre (newlines, etc.)
        titre_court = " ".join(titre.split())[:120]

        lignes.append(f"## {emoji} {titre_court}")
        lignes.append("")
        lignes.append(f"**Verdict** : {verdict} (score {score}/100)" if eval_ else "")
        lignes.append(
            f"- **Acheteur** : {marche.get('acheteur_nom', '?')}"
        )
        lignes.append(
            f"- **Source** : {marche.get('source')} `{marche.get('reference_externe')}`"
        )
        if marche.get("reference_ft"):
            lignes.append(
                f"- **Référence interne acheteur** : `{marche['reference_ft']}`"
            )
        lignes.append(
            f"- **Catégorie** : {marche.get('categorie_metier', '?')}"
        )
        if marche.get("date_publication"):
            lignes.append(f"- **Publié** : {marche['date_publication'][:10]}")
        if marche.get("date_limite_depot"):
            lignes.append(f"- **Date limite de dépôt** : "
                          f"**{marche['date_limite_depot'][:10]}**")

        # Liens
        lignes.append("")
        lignes.append("**Liens** :")
        if marche.get("url_dce"):
            qualite = marche.get("dce_qualite", "?")
            badge = "✅ direct" if qualite == "directe" else "🔍 via keyWord"
            lignes.append(
                f"- {badge} **Consultation PLACE** (DCE téléchargeable) : "
                f"<{marche['url_dce']}>"
            )
            lignes.append(f"- Avis source : <{marche.get('url_avis', '?')}>")
        else:
            # Pas d'URL DCE trouvée → fallback sur l'avis source qui contient
            # souvent les coordonnées du profil acheteur et un PDF d'avis complet
            source = marche.get("source", "?")
            url_avis = marche.get("url_avis", "?")
            lignes.append(
                f"- 🔗 **Voir l'avis sur {source}** (URL DCE non publiée par "
                f"l'acheteur, l'avis contient les modalités d'accès au DCE) : "
                f"<{url_avis}>"
            )
            if marche.get("url_recherche_place") and source != "TED":
                lignes.append(
                    f"- Recherche manuelle PLACE : "
                    f"<{marche['url_recherche_place']}>"
                )

        # Dossier local DCE
        dossier = _dossier_dce_local(marche)
        lignes.append("")
        lignes.append(f"**Dossier local** pour déposer les PDF téléchargés :")
        lignes.append(f"```")
        lignes.append(dossier)
        lignes.append(f"```")

        # Objet complet
        objet = marche.get("objet", "")
        if objet and objet != titre:
            lignes.append("")
            lignes.append(f"**Objet** : {objet[:600]}")

        # Motifs du matching si dispo
        if eval_ and eval_.get("motifs"):
            lignes.append("")
            lignes.append("**Motifs de matching** :")
            for motif in eval_["motifs"]:
                if motif.get("points"):
                    signe = "+" if motif["points"] > 0 else ""
                    lignes.append(f"  - [{signe}{motif['points']}] "
                                  f"**{motif['critere']}** — {motif['commentaire']}")

        lignes.append("")
        lignes.append("---")
        lignes.append("")

    return "\n".join(lignes)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Récupération des URLs DCE et rapport des marchés actifs."
    )
    parser.add_argument("--jours", type=int, default=60,
                        help="Fenêtre (jours) pour marchés sans date limite.")
    parser.add_argument("--tous", action="store_true",
                        help="Traite TOUS les marchés (pas seulement actifs).")
    parser.add_argument("--dry-run", action="store_true",
                        help="N'écrit rien en base.")
    parser.add_argument("--rapport-seul", action="store_true",
                        help="Génère juste le rapport, sans relancer la "
                             "recherche d'URLs DCE.")
    args = parser.parse_args()

    if not args.rapport_seul:
        traiter(
            filtre_actifs=not args.tous,
            fenetre_jours_sans_date=args.jours,
            dry_run=args.dry_run,
            verbose=True,
        )

    # Génère le rapport
    print()
    print("=" * 78)
    print("  Génération du rapport")
    print("=" * 78)
    rapport = generer_rapport(
        filtre_actifs=not args.tous,
        fenetre_jours_sans_date=args.jours,
    )
    os.makedirs(REPERTOIRE_RAPPORTS, exist_ok=True)
    dat = datetime.now().strftime("%Y-%m-%d")
    chemin = os.path.join(REPERTOIRE_RAPPORTS, f"marches_actifs_{dat}.md")
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(rapport)
    print(f"  📄 Rapport écrit : {chemin}")

    # Crée les dossiers data/dce/<id> pour les marchés actifs
    if not args.dry_run:
        marches = stockage.charger(COLLECTION_MARCHES)
        actifs = [m for m in marches.values()
                   if _est_actif(m, args.jours)] if not args.tous \
                else list(marches.values())
        os.makedirs(REPERTOIRE_DCE, exist_ok=True)
        for m in actifs:
            os.makedirs(_dossier_dce_local(m), exist_ok=True)
        print(f"  📁 {len(actifs)} dossiers DCE créés sous {REPERTOIRE_DCE}")


if __name__ == "__main__":
    main()
