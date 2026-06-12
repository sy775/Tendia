"""
diagnostic_contract_notice.py
-----------------------------
Phase 4 — diagnostic approfondi.

Le diagnostic précédent (diagnostic_natures_boamp) a révélé que ~45% des
marchés sans url_dce sont des avis de marché ACTIFS (ContractNotice), pas
des avis d'attribution. Pour ceux-là, il y a probablement matière à
gagner sur l'extraction.

Ce script :
1. Filtre les marchés sans url_dce
2. Ré-interroge l'API BOAMP
3. Garde UNIQUEMENT les ContractNotice (= avis de marché actifs)
4. Pour chacun, regarde précisément ce qui aurait pu être extrait :
   - Présence d'une `cac:CallForTendersDocumentReference.cbc:URI` (URL DCE niveau lot)
   - Présence d'un `cbc:BuyerProfileURI` (URL profil acheteur générique)
   - Présence d'une référence interne acheteur (`cac:ProcurementProject.cbc:ID`)
   - URLs vues nulle part ailleurs dans le payload
5. Cartographie les patterns d'échec pour identifier les correctifs ciblés

Usage :
    python diagnostic_contract_notice.py --n 15
"""

import argparse
import io
import sys
from collections import Counter
from urllib.parse import urlparse

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import stockage
import dce_finder


def _toutes_urls_recursif(obj, prof_max=12):
    """Collecte toutes les URLs HTTP avec leur chemin dans l'objet."""
    out = []

    def visit(o, chemin, prof):
        if prof > prof_max:
            return
        if isinstance(o, str):
            s = o.strip()
            if s.startswith(("http://", "https://")):
                out.append((chemin, s))
        elif isinstance(o, dict):
            for k, v in o.items():
                visit(v, f"{chemin}.{k}" if chemin else k, prof + 1)
        elif isinstance(o, list):
            for i, e in enumerate(o):
                visit(e, f"{chemin}[{i}]", prof + 1)
    visit(obj, "", 0)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=15,
                    help="Nombre de ContractNotice à analyser en profondeur.")
    args = ap.parse_args()

    marches = stockage.charger("marches")
    sans_url = [m for m in marches.values()
                if not m.get("url_dce") and m.get("source") == "BOAMP"]

    print("=" * 78)
    print("  Phase 4 — diagnostic ContractNotice sans url_dce")
    print("=" * 78)
    print(f"  Total sans url_dce : {len(sans_url)}")

    contract_notices = []
    contract_awards = 0
    autres = 0
    api_404 = 0
    nb_explores = 0
    # Cap dur sur l'exploration pour éviter de tourner 4 minutes
    cap_exploration = min(args.n * 4, 50)

    print()
    print(f"  Filtrage : ne garder que les ContractNotice (avis de marché actifs)...")
    print(f"  (cap d'exploration : {cap_exploration} marchés pour limiter les appels API)")
    for i, m in enumerate(sans_url):
        if len(contract_notices) >= args.n:
            break
        if nb_explores >= cap_exploration:
            break
        nb_explores += 1
        if nb_explores % 5 == 0:
            print(f"    ... {nb_explores} marchés interrogés, "
                  f"{len(contract_notices)} ContractNotice trouvés")
        ref = m.get("reference_externe", "")
        record = dce_finder._fetch_record_boamp(ref)
        if not record:
            api_404 += 1
            continue
        donnees = dce_finder._parser_donnees(record)
        eforms = donnees.get("EFORMS") or {}
        if "ContractNotice" in eforms:
            contract_notices.append((m, record, donnees))
        elif "ContractAwardNotice" in eforms:
            contract_awards += 1
        else:
            autres += 1

    print(f"  Échantillonné       : {nb_explores}")
    print(f"    ContractNotice    : {len(contract_notices)}  ← analyse approfondie")
    print(f"    ContractAwardNotice (skip) : {contract_awards}")
    print(f"    Autres branches   : {autres}")
    print(f"    API 404           : {api_404}")
    print()

    # Compteurs pour la cartographie
    has_uri_lot = 0
    has_buyer_profile = 0
    has_reference_ft = 0
    has_aucune_url = 0
    uri_lots_specifiques = 0
    uri_lots_racines = 0
    domaines_buyer_profile = Counter()
    domaines_urls_orphelines = Counter()
    exemples_aucune_url = []

    print("-" * 78)
    print(f"  Détail des {len(contract_notices)} ContractNotice actifs")
    print("-" * 78)

    for i, (m, record, donnees) in enumerate(contract_notices, 1):
        id_m = m["id"]
        acheteur = (m.get("acheteur_nom") or "")[:35]
        print(f"\n  [{i}] {id_m}  acheteur={acheteur}")

        # 1. URL DCE niveau lot (chemin officiel)
        cn = donnees.get("EFORMS", {}).get("ContractNotice", {})
        lot_data = dce_finder._get_chemin(cn, ["cac:ProcurementProjectLot"])
        lots = [lot_data] if isinstance(lot_data, dict) else (lot_data or [])
        uris_lots = []
        for lot in lots:
            uri = dce_finder._extraire_uri_lot(lot)
            if uri:
                uris_lots.append(uri)
        if uris_lots:
            has_uri_lot += 1
            for u in uris_lots:
                spec = dce_finder._est_url_specifique(u)
                if spec:
                    uri_lots_specifiques += 1
                else:
                    uri_lots_racines += 1
                print(f"        URI lot     : {'(specifique)' if spec else '(racine)':<14} {u[:90]}")
        else:
            print(f"        URI lot     : ABSENT")

        # 2. Buyer profile
        bp = dce_finder._get_chemin(cn, [
            "cac:ContractingParty", "cbc:BuyerProfileURI"
        ])
        if bp:
            has_buyer_profile += 1
            try:
                dom = urlparse(bp).netloc.lower().removeprefix("www.")
                domaines_buyer_profile[dom] += 1
            except Exception:
                pass
            print(f"        BuyerProfile: {bp[:90]}")
        else:
            print(f"        BuyerProfile: ABSENT")

        # 3. Référence interne acheteur (pour fallback PLACE keyword)
        ref_acheteur = dce_finder._extraire_reference_ft({"EFORMS": {"ContractNotice": cn}})
        if ref_acheteur:
            has_reference_ft += 1
            print(f"        Ref interne : {ref_acheteur}")
        else:
            print(f"        Ref interne : ABSENT")

        # 4. URLs orphelines : présentes dans le payload mais pas remontées
        toutes = _toutes_urls_recursif(donnees)
        urls_brutes = [u for _, u in toutes]
        urls_specifiques = [u for u in urls_brutes if dce_finder._est_url_specifique(u)
                            and dce_finder._domaine_est_plateforme_mp(u)]
        if urls_specifiques:
            print(f"        URL spécifiques trouvées dans le payload : {len(urls_specifiques)}")
            for u in urls_specifiques[:3]:
                try:
                    dom = urlparse(u).netloc.lower().removeprefix("www.")
                    domaines_urls_orphelines[dom] += 1
                except Exception:
                    pass
                print(f"           · {u[:90]}")

        # 5. Verdict pour ce marché
        a_quelque_chose = bool(uris_lots or bp or ref_acheteur or urls_specifiques)
        if not a_quelque_chose:
            has_aucune_url += 1
            exemples_aucune_url.append((id_m, acheteur))

    # Synthèse
    n = len(contract_notices)
    print()
    print("=" * 78)
    print(f"  Synthèse sur {n} ContractNotice actifs")
    print("=" * 78)
    if n > 0:
        print(f"  Avec URI lot eForms         : {has_uri_lot}/{n}")
        print(f"     dont spécifique          : {uri_lots_specifiques}")
        print(f"     dont racine (inutile)    : {uri_lots_racines}")
        print(f"  Avec BuyerProfileURI        : {has_buyer_profile}/{n}")
        print(f"  Avec référence acheteur     : {has_reference_ft}/{n}")
        print(f"  AUCUNE info exploitable     : {has_aucune_url}/{n}")
    print()

    if domaines_buyer_profile:
        print("  Top domaines BuyerProfile (rarement spécifiques) :")
        for d, n_ in domaines_buyer_profile.most_common(10):
            print(f"    {d:45} : {n_}")

    if domaines_urls_orphelines:
        print()
        print("  Top domaines URL orphelines (potentiellement exploitables) :")
        for d, n_ in domaines_urls_orphelines.most_common(10):
            print(f"    {d:45} : {n_}")

    if exemples_aucune_url:
        print()
        print("  Marchés sans aucune info exploitable :")
        for id_m, ach in exemples_aucune_url[:10]:
            print(f"    · {id_m}  {ach}")

    print()
    print("-" * 78)
    print("  PISTES Phase 4 (selon ce qui ressort) :")
    print("-" * 78)
    print("  - Si URI lot racine fréquent  → utiliser BuyerProfile + ref_acheteur")
    print("                                   pour faire un _chercher_url_dce_via_X")
    print("                                   sur chaque plateforme connue")
    print("  - Si BuyerProfile + ref      → étendre _chercher_url_dce_via_place")
    print("                                   aux autres plateformes (Atexo blanche)")
    print("  - Si AUCUNE info             → ces marchés sont structurellement perdus")
    print("                                   (info pas dans BOAMP)")


if __name__ == "__main__":
    main()
