"""
diagnostic_pertinents_sans_url.py
---------------------------------
Phase 4 ciblée pertinents — diagnostic des 18 marchés pertinents sans
url_dce extraite.

Le sprint couverture DCE précédent (passé de 8 à 93 vrais DCE) a optimisé
sur les 500 marchés bruts. Mais le bilan_briefs montre que 51% des marchés
pertinents n'ont même pas d'url_dce. Avant de patcher dce_finder, comprendre
précisément pourquoi.

Le script :
1. Charge les marchés pertinents (via scores_matching)
2. Filtre ceux sans url_dce
3. Pour chacun, ré-interroge BOAMP et analyse ce qui aurait dû être extrait :
   - BuyerProfile (URL plateforme) — présent ? type ? whitelist ?
   - reference_acheteur (réf interne)
   - URI lot eForms (racine vs spécifique)
   - URLs orphelines dans le payload
4. Cartographie les patterns récurrents
5. Suggère le patch ciblé en bout

Usage :
    python diagnostic_pertinents_sans_url.py
"""

import argparse
import io
import sys
from collections import Counter, defaultdict
from urllib.parse import urlparse

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import dce_finder


def _categorie_buyer_profile(bp: str) -> str:
    """Catégorise le BuyerProfile selon la plateforme reconnue."""
    if not bp:
        return "(aucun)"
    bp_low = bp.lower()
    plateformes = {
        "marches-publics.gouv.fr": "PLACE (whitelisté)",
        "marches-publics.info": "DEMATIS (mur captcha)",
        "achatpublic.com": "achatpublic (mur login)",
        "e-marchespublics.com": "e-marchespublics (whitelisté)",
        "megalis": "Megalis (whitelisté Phase 4)",
        "maximilien": "Maximilien (mur form 31 champs)",
        "ternum-bfc": "Ternum-BFC (mur form 31 champs)",
        "596280": "Mp 596280 (mur form 31 champs)",
        "agglo-": "Agglo (whitelisté Phase 4)",
        "marches-securises": "Marches-sécurisés (whitelisté Phase 4)",
        "achatpublic": "achatpublic (mur login)",
        "marches.": "marches.* générique",
    }
    for pat, label in plateformes.items():
        if pat in bp_low:
            return label
    return f"INCONNU: {bp[:60]}"


def _est_url_specifique(url: str) -> bool:
    """Hérite la logique de dce_finder."""
    if not url:
        return False
    return dce_finder._est_url_specifique(url)


def _domaine(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=None,
                    help="Cap explorations (défaut : tout)")
    args = ap.parse_args()

    print("=" * 78)
    print("  Phase 4 ciblée pertinents — diagnostic marchés sans url_dce")
    print("=" * 78)

    marches = stockage.charger("marches") or {}
    scores = stockage.charger("scores_matching") or {}

    # Identifie les marchés pertinents (matche ≥1 preset)
    pertinents = set()
    pertinents_par_preset = defaultdict(set)
    for cle, score in scores.items():
        if not isinstance(score, dict):
            continue
        if "preset_code" in score and "matche" in score:
            if score.get("matche"):
                id_m = score.get("marche_id") or score.get("id") or cle.rsplit("_", 1)[0]
                pertinents_par_preset[score["preset_code"]].add(id_m)
                pertinents.add(id_m)
        else:
            for preset_c, sub in score.items():
                if isinstance(sub, dict) and sub.get("matche"):
                    pertinents_par_preset[preset_c].add(cle)
                    pertinents.add(cle)

    # Filtre ceux sans url_dce
    cibles = []
    for id_m in pertinents:
        m = marches.get(id_m)
        if not m:
            continue
        if not m.get("url_dce"):
            cibles.append((id_m, m))

    print(f"\n  Pertinents au total : {len(pertinents)}")
    print(f"  Sans url_dce        : {len(cibles)}  ← cible du diagnostic")
    print(f"  Par preset :")
    for p, ids in sorted(pertinents_par_preset.items()):
        sans_url = sum(1 for id_m in ids if not marches.get(id_m, {}).get("url_dce"))
        print(f"    · {p:<28} : {sans_url}/{len(ids)} pertinents sans url_dce")

    if args.n:
        cibles = cibles[:args.n]

    if not cibles:
        print("\n  ✓ Tous les marchés pertinents ont une url_dce.")
        return

    # === Analyse marché par marché ===
    print(f"\n{'-' * 78}")
    print(f"  Détail des {len(cibles)} marchés")
    print(f"{'-' * 78}")

    # Compteurs pour synthèse
    cat_buyer_profile = Counter()
    has_uri_lot_racine = 0
    has_uri_lot_specifique = 0
    has_aucun_uri = 0
    has_reference_acheteur = 0
    has_buyer_profile = 0
    has_aucune_info = 0
    urls_orphelines_par_domaine = Counter()
    branches_eforms = Counter()
    natures_boamp = Counter()

    pour_patch = []  # marchés exploitables par un patch ciblé

    for i, (id_m, m) in enumerate(cibles, 1):
        ref = m.get("reference_externe", "")
        acheteur = (m.get("acheteur_nom") or "?")[:40]
        titre = (m.get("titre") or m.get("objet") or "?")[:60]

        record = dce_finder._fetch_record_boamp(ref)
        if not record:
            print(f"\n  [{i}] {id_m}  ⚠ API BOAMP 404")
            continue

        donnees = dce_finder._parser_donnees(record)
        eforms = donnees.get("EFORMS") or {}

        # Branche eForms : ContractNotice (actif) vs ContractAwardNotice (attribué)
        branche = next((k for k in eforms.keys()
                        if k in ("ContractNotice", "ContractAwardNotice",
                                  "PriorInformationNotice")), "?")
        branches_eforms[branche] += 1
        nature = record.get("nature_libelle") or "?"
        natures_boamp[nature] += 1

        # Extraction du contenu utile
        cn = eforms.get(branche, {})
        bp = dce_finder._get_chemin(cn, ["cac:ContractingParty", "cbc:BuyerProfileURI"])
        ref_acheteur = dce_finder._extraire_reference_ft({"EFORMS": {branche: cn}})

        # URIs lot
        lot_data = dce_finder._get_chemin(cn, ["cac:ProcurementProjectLot"])
        lots = [lot_data] if isinstance(lot_data, dict) else (lot_data or [])
        uris_lot = []
        for lot in lots:
            uri = dce_finder._extraire_uri_lot(lot)
            if uri:
                uris_lot.append(uri)

        if bp:
            has_buyer_profile += 1
            cat = _categorie_buyer_profile(bp)
            cat_buyer_profile[cat] += 1
        if ref_acheteur:
            has_reference_acheteur += 1

        # Analyse URIs lot
        spec_count = sum(1 for u in uris_lot if _est_url_specifique(u))
        racine_count = len(uris_lot) - spec_count
        if spec_count:
            has_uri_lot_specifique += 1
        elif racine_count:
            has_uri_lot_racine += 1
        else:
            has_aucun_uri += 1

        # Verdict patch-exploitable
        exploitable_par_patch = bool(bp and ref_acheteur and not spec_count)
        if not (bp or ref_acheteur or uris_lot):
            has_aucune_info += 1
        if exploitable_par_patch:
            pour_patch.append((id_m, bp, ref_acheteur, acheteur))

        # Affichage compact
        statut = (
            "✓ exploitable patch" if exploitable_par_patch
            else "✓ URL spécifique trouvable" if spec_count
            else "✗ rien" if not (bp or ref_acheteur or uris_lot)
            else "? partiel"
        )
        bp_short = (bp or "(aucun)")[:55] if bp else "(aucun)"
        print(f"\n  [{i:2d}] {id_m}  [{branche[:15]:<15}]  {statut}")
        print(f"       acheteur     : {acheteur}")
        print(f"       titre        : {titre}")
        print(f"       BuyerProfile : {bp_short}")
        if bp:
            print(f"          → cat      : {_categorie_buyer_profile(bp)}")
        print(f"       Ref acheteur : {ref_acheteur or '(absent)'}")
        if uris_lot:
            for u in uris_lot[:2]:
                marqueur = "spec" if _est_url_specifique(u) else "racine"
                print(f"       URI lot ({marqueur:<6}): {u[:60]}")

    # === Synthèse ===
    n = len(cibles)
    print()
    print("=" * 78)
    print(f"  SYNTHÈSE sur {n} marchés pertinents sans url_dce")
    print("=" * 78)
    print(f"\n  Branches eForms :")
    for k, v in branches_eforms.most_common():
        print(f"    {k:<25} : {v}")
    print(f"\n  Natures BOAMP :")
    for k, v in natures_boamp.most_common():
        print(f"    {k:<35} : {v}")

    print(f"\n  Champs présents :")
    print(f"    Avec BuyerProfile           : {has_buyer_profile}/{n}")
    print(f"    Avec référence acheteur     : {has_reference_acheteur}/{n}")
    print(f"    Avec URI lot spécifique     : {has_uri_lot_specifique}/{n}")
    print(f"    Avec URI lot racine seul    : {has_uri_lot_racine}/{n}")
    print(f"    Sans aucun URI lot          : {has_aucun_uri}/{n}")
    print(f"    Aucune info exploitable     : {has_aucune_info}/{n}")

    if cat_buyer_profile:
        print(f"\n  Plateformes BuyerProfile rencontrées (top 15) :")
        for cat, v in cat_buyer_profile.most_common(15):
            print(f"    {cat:<45} : {v}")

    print(f"\n  ★ Exploitables par un patch ciblé : {len(pour_patch)}")
    print(f"    (= BuyerProfile + ref_acheteur présents, URI lot non spécifique)")

    if pour_patch:
        print(f"\n  Liste des candidats au patch :")
        for id_m, bp, ref, acheteur in pour_patch:
            dom = _domaine(bp)
            print(f"    {id_m}  {dom:<35} ref={ref}")

    # Verdict
    print(f"\n  ── Prochaine étape suggérée ──")
    if len(pour_patch) >= 3:
        print(f"  → {len(pour_patch)} candidats exploitables.")
        print(f"    Patcher dce_finder.py pour ajouter les plateformes manquantes")
        print(f"    à la whitelist DOMAINES_PLATEFORMES_MP et tester.")
    elif has_aucune_info >= n // 2:
        print(f"  ⚠ {has_aucune_info}/{n} marchés sans aucune info exploitable.")
        print(f"    Mur structurel BOAMP/eForms — pas grand-chose à gagner ici.")
        print(f"    Considérer l'ingestion d'autres sources (TED, DECP, web scraping).")
    else:
        print(f"  Investigations supplémentaires nécessaires sur les cas \"partiel\".")


if __name__ == "__main__":
    main()
