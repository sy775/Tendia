"""
debug_place_html.py
-------------------
Dump le HTML COMPLET de la recherche PLACE pour les marchés actifs sans
URL DCE précise. Objectif : analyser où dans le HTML se trouve l'id de
consultation, pour en déduire le pattern d'extraction.

Output : data/debug/place_html_<ref>.html
"""

import json
import os
import sys
from datetime import date

import requests

import stockage


REPERTOIRE_DEBUG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data", "debug"
)
COLLECTION = "marches"

URL_PLACE_TEMPLATE = (
    "https://www.marches-publics.gouv.fr/"
    "?page=Entreprise.EntrepriseAdvancedSearch&AllCons&refConsultation={ref}"
)


def _est_actif(marche: dict) -> bool:
    date_lim = marche.get("date_limite_depot")
    today = date.today().isoformat()
    if date_lim and len(date_lim) >= 10:
        return date_lim[:10] >= today
    date_pub = marche.get("date_publication")
    if date_pub and len(date_pub) >= 10:
        try:
            d = date.fromisoformat(date_pub[:10])
            return (date.today() - d).days <= 60
        except ValueError:
            pass
    return False


def main():
    os.makedirs(REPERTOIRE_DEBUG, exist_ok=True)

    marches = stockage.charger(COLLECTION)
    actifs_boamp = [m for m in marches.values()
                     if _est_actif(m) and m.get("source") == "BOAMP"]

    print(f"Dump HTML PLACE pour {len(actifs_boamp)} marchés BOAMP actifs.")
    print()

    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
    }

    for m in actifs_boamp:
        ref = m.get("reference_externe")
        url = URL_PLACE_TEMPLATE.format(ref=ref)
        print(f"  Fetch : {ref}")
        print(f"    URL : {url}")
        try:
            r = requests.get(url, headers=headers, timeout=30,
                              allow_redirects=True)
            print(f"    Status : {r.status_code}")
            print(f"    Final URL : {r.url}")
            print(f"    HTML size : {len(r.text)} caractères")
            print(f"    Cookies reçus : {len(r.cookies)} cookies")

            # Dump HTML
            chemin = os.path.join(REPERTOIRE_DEBUG, f"place_html_{ref}.html")
            with open(chemin, "w", encoding="utf-8") as f:
                f.write(r.text)
            print(f"    Sauvé : {chemin}")

            # Cherche quelques patterns probables
            import re
            html = r.text
            patterns_a_tester = [
                (r"id=(\d{4,})", "id=NUMÉRO"),
                (r"idConsultation=(\d+)", "idConsultation"),
                (r"refConsultation['\"]?\s*[:=]\s*['\"]?(\d+)", "refConsultation"),
                (r"orgAcronyme=(\w+)", "orgAcronyme"),
                (r"data-consultation-id=['\"]?(\w+)", "data-consultation-id"),
                (r"consultation_id['\"]?\s*[:=]\s*['\"]?(\d+)", "consultation_id"),
                (rf"{re.escape(ref)}[^<]{{0,200}}", f"contexte autour de {ref}"),
            ]
            print(f"    Patterns trouvés :")
            for pattern, label in patterns_a_tester:
                matchs = re.findall(pattern, html, re.IGNORECASE)
                if matchs:
                    uniques = list(set(matchs[:5]))
                    print(f"      {label} : {len(matchs)} matchs, ex : {uniques[:3]}")
        except Exception as e:
            print(f"    ❌ Erreur : {e}")
        print()

    print(f"Fichiers HTML dans : {REPERTOIRE_DEBUG}")
    print(f"→ Zipper et envoyer pour analyse :")
    print(f"  Compress-Archive -Path data\\debug -DestinationPath debug2.zip")


if __name__ == "__main__":
    main()
