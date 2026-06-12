"""
place_crawler_test.py
---------------------
Test plusieurs approches pour récupérer l'URL DCE spécifique depuis PLACE :

A. GET avec Utah=OK (simule window.open du JS)
B. POST avec CSRF token (soumission formulaire complète)

Output : dump complet des réponses dans data/debug/ pour analyse.

Usage :
    python place_crawler_test.py
"""

import json
import os
import re
import sys
from datetime import date

import requests

import stockage


REPERTOIRE_DEBUG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data", "debug"
)


def _est_actif(marche: dict) -> bool:
    date_lim = marche.get("date_limite_depot")
    today = date.today().isoformat()
    if date_lim and len(date_lim) >= 10:
        return date_lim[:10] >= today
    return False


def crawler_place(reference: str) -> dict:
    """Teste 2 approches PLACE et dump les résultats."""

    session = requests.Session()
    session.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    })

    base_url = "https://www.marches-publics.gouv.fr"
    url_form = (f"{base_url}/?page=Entreprise.EntrepriseAdvancedSearch"
                f"&AllCons&refConsultation={reference}")

    resultats = {"reference": reference, "tentatives": []}

    # === Tentative 1 : GET initial (pour récupérer cookies + CSRF) ===
    print(f"  [{reference}] GET initial...")
    try:
        r1 = session.get(url_form, timeout=30, allow_redirects=True)
        # Extrait le CSRF token
        csrf_match = re.search(
            r'name="_csrf_token"[^>]*?value="([^"]+)"', r1.text, re.DOTALL
        )
        csrf_token = csrf_match.group(1) if csrf_match else None
        print(f"    Status {r1.status_code} ; CSRF token : "
              f"{'oui' if csrf_token else 'non'} ; "
              f"cookies : {len(session.cookies)}")
    except Exception as e:
        print(f"    ❌ Erreur GET initial : {e}")
        return resultats

    # === Tentative A : GET avec Utah=OK (simule window.open) ===
    print(f"  [{reference}] Tentative A : GET avec Utah=OK ...")
    url_utah = (f"{base_url}/?page=Entreprise.EntrepriseAdvancedSearch"
                f"&AllCons&refConsultation={reference}"
                f"&Utah=OK&calledFrom=entreprise&javaVersion=11.0")
    try:
        r_a = session.get(url_utah, timeout=30, allow_redirects=True)
        html_a = r_a.text
        # Cherche les liens EntrepriseDetails
        ids_a = re.findall(
            r'(?:EntrepriseDetailsConsultation|DetailsConsultation)'
            r'[^"\'<>]*?id=(\d+)', html_a, re.IGNORECASE
        )
        org_a = re.findall(r'orgAcronyme=(\w+)', html_a)
        # Sauve le HTML pour inspection
        with open(os.path.join(REPERTOIRE_DEBUG,
                                 f"place_A_GET_utah_{reference}.html"),
                   "w", encoding="utf-8") as f:
            f.write(html_a)
        resultats["tentatives"].append({
            "approche": "A_GET_Utah",
            "url_finale": r_a.url,
            "status": r_a.status_code,
            "html_size": len(html_a),
            "ids_consultation": ids_a[:5],
            "org_acronymes": list(set(org_a))[:5],
        })
        print(f"    Status {r_a.status_code}, HTML {len(html_a)} chars, "
              f"ids: {ids_a[:3]}, org: {list(set(org_a))[:2]}")
    except Exception as e:
        print(f"    ❌ Erreur A : {e}")

    # === Tentative B : POST formulaire avec CSRF ===
    if csrf_token:
        print(f"  [{reference}] Tentative B : POST avec CSRF ...")
        post_data = {
            "_csrf_token": csrf_token,
            "ctl0$atexoUtah$javaVersion": "11.0",
            "lang": "",
            # On peut tenter aussi des champs typiques de formulaire de recherche
            "ctl0$CONTENU_PAGE$AdvancedSearch$refConsultation": reference,
        }
        try:
            r_b = session.post(url_form, data=post_data, timeout=30,
                                allow_redirects=True)
            html_b = r_b.text
            ids_b = re.findall(
                r'(?:EntrepriseDetailsConsultation|DetailsConsultation)'
                r'[^"\'<>]*?id=(\d+)', html_b, re.IGNORECASE
            )
            org_b = re.findall(r'orgAcronyme=(\w+)', html_b)
            with open(os.path.join(REPERTOIRE_DEBUG,
                                     f"place_B_POST_csrf_{reference}.html"),
                       "w", encoding="utf-8") as f:
                f.write(html_b)
            resultats["tentatives"].append({
                "approche": "B_POST_CSRF",
                "url_finale": r_b.url,
                "status": r_b.status_code,
                "html_size": len(html_b),
                "ids_consultation": ids_b[:5],
                "org_acronymes": list(set(org_b))[:5],
            })
            print(f"    Status {r_b.status_code}, HTML {len(html_b)} chars, "
                  f"ids: {ids_b[:3]}, org: {list(set(org_b))[:2]}")
        except Exception as e:
            print(f"    ❌ Erreur B : {e}")

    return resultats


def main():
    os.makedirs(REPERTOIRE_DEBUG, exist_ok=True)

    marches = stockage.charger("marches")
    actifs_boamp = [m for m in marches.values()
                     if _est_actif(m) and m.get("source") == "BOAMP"]

    if not actifs_boamp:
        print("Aucun marché BOAMP actif. Sors.")
        return

    print(f"Test crawler PLACE sur {len(actifs_boamp)} marchés actifs.")
    print()

    bilan = []
    for m in actifs_boamp:
        ref = m["reference_externe"]
        r = crawler_place(ref)
        bilan.append(r)
        print()

    # Sauve le bilan
    chemin = os.path.join(REPERTOIRE_DEBUG, "place_crawler_bilan.json")
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(bilan, f, ensure_ascii=False, indent=2)
    print(f"Bilan sauvé : {chemin}")
    print()
    print("=" * 70)
    print("RÉCAP")
    print("=" * 70)
    for r in bilan:
        ref = r["reference"]
        for t in r["tentatives"]:
            ids = t.get("ids_consultation", [])
            orgs = t.get("org_acronymes", [])
            ok = "✅" if ids else "❌"
            print(f"  {ok} [{ref}] {t['approche']:<15} "
                  f"→ {len(ids)} ids, orgs={orgs}")


if __name__ == "__main__":
    main()
