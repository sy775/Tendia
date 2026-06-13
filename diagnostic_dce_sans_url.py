"""
diagnostic_dce_sans_url.py
--------------------------
Analyse pourquoi 239 marchés n'ont pas d'url_dce en base.

Pour chaque marché en `dce_qualite='absente'` ou sans dce_qualite :
  - Identifie sa source (BOAMP / TED) et sa référence externe
  - Échantillonne (5 BOAMP + 5 TED) en ré-interrogeant l'API pour récupérer
    le record complet
  - Liste les champs eForms qui contiennent une URL (toute URL string http*)
    qu'on n'a pas remontée
  - Affiche les buyer_profile, EndpointID, et autres URI suspects

Sortie : carte précise des champs eForms à exploiter en Phase 4.

Usage :
    python diagnostic_dce_sans_url.py           # échantillon de 10
    python diagnostic_dce_sans_url.py --n 20    # échantillon plus large
"""

import argparse
import io
import json
import sys
from collections import Counter
from urllib.parse import urlparse

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import dce_finder
from http_utils import get_json, post_json


def _collecter_urls_dans_obj(obj, prof_max=10):
    """Retourne toutes les chaînes commençant par http* dans un objet imbriqué.
    Renvoie list of (chemin, url)."""
    trouvees = []

    def _visit(o, chemin, prof):
        if prof > prof_max:
            return
        if isinstance(o, str):
            s = o.strip()
            if s.startswith(("http://", "https://")):
                trouvees.append((chemin, s))
        elif isinstance(o, dict):
            for k, v in o.items():
                _visit(v, f"{chemin}.{k}" if chemin else k, prof + 1)
        elif isinstance(o, list):
            for i, elt in enumerate(o):
                _visit(elt, f"{chemin}[{i}]", prof + 1)

    _visit(obj, "", 0)
    return trouvees


def _diagnostiquer_boamp(reference: str):
    """Pour une réf BOAMP, ré-interroge l'API et liste les URLs trouvées."""
    record = dce_finder._fetch_record_boamp(reference)
    if not record:
        return None
    donnees = dce_finder._parser_donnees(record)
    urls = _collecter_urls_dans_obj(donnees)
    # Classifie par domaine
    par_dom = Counter()
    for _, u in urls:
        try:
            par_dom[urlparse(u).netloc.lower().removeprefix("www.")] += 1
        except Exception:
            pass
    return {
        "nb_urls_totales": len(urls),
        "urls_uniques_par_chemin": urls[:20],   # limite affichage
        "par_domaine": par_dom,
        "buyer_profile": dce_finder._get_chemin(donnees, [
            "EFORMS", "ContractNotice",
            "cac:ContractingParty", "cbc:BuyerProfileURI",
        ]),
        "reference_ft": dce_finder._extraire_reference_ft(donnees),
    }


def _diagnostiquer_ted(reference: str):
    """Pour une réf TED, ré-interroge avec plus de champs."""
    # On élargit les champs par rapport à ce que fait dce_finder
    champs_etendus = list(dce_finder.TED_FIELDS_DCE) + [
        "internet-address-buyer",
        "buyer-website",
        "address-domain-buyer",
        "notice-distribution",
        "internet-address",
    ]
    body = {
        "query": f"publication-number={reference}",
        "fields": champs_etendus,
        "limit": 1,
        "scope": "ALL",
        "checkQuerySyntax": False,
        "paginationMode": "PAGE_NUMBER",
    }
    try:
        rep = post_json("https://api.ted.europa.eu/v3/notices/search",
                         body, verbose=False)
    except Exception as e:
        return {"erreur": str(e)}
    notices = rep.get("notices") or rep.get("results") or []
    if not notices:
        return {"erreur": "0 notices"}
    notice = notices[0]
    # Collecte toutes les URLs dans tous les champs
    urls = _collecter_urls_dans_obj(notice)
    par_champ = Counter()
    for chemin, _ in urls:
        # Premier niveau du chemin = nom du champ TED
        par_champ[chemin.split(".")[0].split("[")[0]] += 1
    return {
        "nb_urls_totales": len(urls),
        "par_champ_principal": par_champ,
        "echantillon_urls": urls[:15],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10,
                    help="Taille d'échantillon par source (default 10).")
    args = ap.parse_args()

    print("=" * 78)
    print("  Diagnostic des marchés SANS url_dce")
    print("=" * 78)
    print()

    marches = stockage.charger("marches")

    # Filtre : qualité absente OU pas de qualité du tout
    sans_url = []
    for id_m, m in marches.items():
        q = m.get("dce_qualite")
        if q == "absente" or q is None or q == "non_recherchee":
            if not m.get("url_dce"):
                sans_url.append((id_m, m))

    print(f"  Marchés en base                    : {len(marches)}")
    print(f"  Marchés sans url_dce exploitable   : {len(sans_url)}")

    # Répartition par source
    par_source = Counter()
    for _, m in sans_url:
        par_source[m.get("source", "?")] += 1
    print()
    print("  Par source :")
    for s, n in par_source.most_common():
        print(f"    {s:10} : {n}")

    # Échantillon BOAMP
    boamp_ids = [(id_m, m) for id_m, m in sans_url
                 if m.get("source") == "BOAMP"][:args.n]
    ted_ids = [(id_m, m) for id_m, m in sans_url
               if m.get("source") == "TED"][:args.n]

    print()
    print("-" * 78)
    print(f"  ÉCHANTILLON BOAMP — ré-interroge l'API ({len(boamp_ids)} marchés)")
    print("-" * 78)

    boamp_urls_par_domaine_global = Counter()
    boamp_buyer_profiles = []
    boamp_avec_urls = 0
    for id_m, m in boamp_ids:
        ref = m.get("reference_externe", "")
        diag = _diagnostiquer_boamp(ref)
        if not diag:
            print(f"  [{id_m}] ref={ref}  → API n'a rien retourné")
            continue
        print(f"  [{id_m}] ref={ref}  acheteur={m.get('acheteur_nom','')[:35]}")
        print(f"      URLs trouvées dans eForms : {diag['nb_urls_totales']}")
        if diag["nb_urls_totales"]:
            boamp_avec_urls += 1
            for d, n in diag["par_domaine"].most_common(5):
                print(f"        · {d:45} : {n}")
                boamp_urls_par_domaine_global[d] += n
        if diag["buyer_profile"]:
            print(f"      buyer_profile : {diag['buyer_profile'][:100]}")
            boamp_buyer_profiles.append(diag["buyer_profile"])
        if diag["reference_ft"]:
            print(f"      reference_ft  : {diag['reference_ft']}")
        # Aperçu de qq URLs
        for chemin, url in diag["urls_uniques_par_chemin"][:5]:
            print(f"        ({chemin[-60:]:>60}) {url[:80]}")
        print()

    print()
    print("-" * 78)
    print(f"  ÉCHANTILLON TED — élargit la requête ({len(ted_ids)} marchés)")
    print("-" * 78)

    ted_avec_urls = 0
    for id_m, m in ted_ids:
        ref = m.get("reference_externe", "")
        diag = _diagnostiquer_ted(ref)
        print(f"  [{id_m}] ref={ref}  acheteur={m.get('acheteur_nom','')[:35]}")
        if "erreur" in diag:
            print(f"      ❌ {diag['erreur']}")
            continue
        print(f"      URLs trouvées : {diag['nb_urls_totales']}")
        if diag["nb_urls_totales"]:
            ted_avec_urls += 1
            for champ, n in diag["par_champ_principal"].most_common(5):
                print(f"        · {champ:35} : {n} URL(s)")
            for chemin, url in diag["echantillon_urls"][:3]:
                print(f"          ({chemin[:50]:50}) {url[:80]}")
        print()

    print()
    print("=" * 78)
    print("  BILAN GLOBAL")
    print("=" * 78)
    print(f"  BOAMP échantillon avec au moins 1 URL eForms : {boamp_avec_urls}/{len(boamp_ids)}")
    print(f"  TED échantillon avec au moins 1 URL          : {ted_avec_urls}/{len(ted_ids)}")
    print()
    if boamp_urls_par_domaine_global:
        print("  Top domaines présents dans eForms BOAMP (mais non remontés) :")
        for d, n in boamp_urls_par_domaine_global.most_common(15):
            print(f"    {d:50} : {n}")
    print()
    print("  → Si BOAMP a beaucoup d'URLs eForms mais pas remontées : on peut")
    print("    élargir _chercher_urls_dans_eforms() pour les capter.")
    print("  → Si TED a des URLs dans des champs qu'on n'examine pas : on")
    print("    élargit TED_FIELDS_DCE dans dce_finder.")


if __name__ == "__main__":
    main()
