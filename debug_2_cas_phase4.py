"""
debug_2_cas_phase4.py
---------------------
Debug ciblé sur les 2 marchés pertinents identifiés comme "exploitables par
un patch ciblé" :
  - BOAMP-26-56264 : PLACE + ref MEAE_26005_ADC
  - BOAMP-26-56222 : sam.nouvelle-aquitaine.pro + ref 2026P000S02771

Le diagnostic teste réellement la requête HTTP Atexo keyword search et
affiche ce qui revient. Permet de trancher :
  - Si la recherche PLACE/Atexo retourne des résultats → patch facile
    (juste ajouter à la whitelist le cas échéant)
  - Si la plateforme n'utilise pas le moteur Atexo standard → acter la perte
  - Si la ref n'est pas indexée publiquement → acter la perte
"""

import io
import sys
import requests
from urllib.parse import urlparse

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "fr-FR,fr;q=0.9",
}


def tester_atexo_keyword(base_url: str, reference: str, label: str):
    print(f"\n{'=' * 78}")
    print(f"  {label}")
    print(f"{'=' * 78}")
    print(f"  Base URL  : {base_url}")
    print(f"  Référence : {reference}")

    # 1. Tester si l'URL racine répond
    print(f"\n  [1] Test base_url accessible...")
    try:
        r = requests.get(base_url, timeout=15, allow_redirects=True,
                         headers=HEADERS)
        print(f"      HTTP {r.status_code}  redirigé vers {r.url[:80]}")
        print(f"      taille HTML : {len(r.text)} chars")
        # Check si c'est du Atexo (signature : page=Entreprise. dans HTML)
        is_atexo = "page=Entreprise." in r.text or "MPE-" in r.text
        print(f"      moteur Atexo détecté : {'OUI' if is_atexo else 'NON'}")
    except Exception as e:
        print(f"      ❌ erreur : {type(e).__name__}: {e}")
        return

    # 2. Tester la recherche keyword Atexo
    url_recherche = (f"{base_url.rstrip('/')}/"
                     "?page=Entreprise.EntrepriseAdvancedSearch"
                     f"&searchAnnCons&keyWord={reference}")
    print(f"\n  [2] Test URL recherche Atexo...")
    print(f"      URL : {url_recherche}")
    try:
        r = requests.get(url_recherche, timeout=20, allow_redirects=True,
                         headers=HEADERS)
        print(f"      HTTP {r.status_code}  taille {len(r.text)} chars")
        if r.status_code != 200:
            print(f"      ❌ statut non-OK")
            return
        html = r.text.replace("&amp;", "&")

        # Cherche EntrepriseDetailsConsultation&id=XXX
        import re
        matches = re.findall(
            r'EntrepriseDetailsConsultation[^"\']*?id=(\d+)[^"\']*?orgAcronyme=([a-z0-9]+)',
            html, re.IGNORECASE)
        print(f"      Détails consultation trouvés : {len(matches)}")
        for m in matches[:5]:
            print(f"        id={m[0]} orgAcronyme={m[1]}")

        # Cherche aussi des liens spécifiques (autres patterns)
        autres = re.findall(r'href="([^"]*(?:consultation|detail|annonce)[^"]*)"',
                            html, re.IGNORECASE)
        if autres and not matches:
            print(f"      Liens 'consultation/detail/annonce' trouvés : {len(autres)}")
            for u in autres[:5]:
                print(f"        {u[:100]}")

        # Detecter si page = liste vide
        if "Aucune consultation" in html or "aucun résultat" in html.lower():
            print(f"      ⚠ Page indique 'Aucun résultat'")

        if not matches and not autres:
            print(f"      ⚠ Aucun lien de consultation trouvé")
            # Affiche un extrait du HTML pour comprendre
            extrait = html[:500].replace('\n', ' ')
            print(f"      HTML début : {extrait[:300]}...")

    except Exception as e:
        print(f"      ❌ erreur : {type(e).__name__}: {e}")


def main():
    tester_atexo_keyword(
        "https://www.marches-publics.gouv.fr",
        "MEAE_26005_ADC",
        "BOAMP-26-56264 → PLACE (whitelistée) + ref MEAE",
    )
    tester_atexo_keyword(
        "https://sam.nouvelle-aquitaine.pro",
        "2026P000S02771",
        "BOAMP-26-56222 → sam.nouvelle-aquitaine.pro + ref Région NA",
    )

    print(f"\n{'=' * 78}")
    print(f"  Interprétation")
    print(f"{'=' * 78}")
    print(f"""
  Pour chaque cas, le verdict dépend de :
  - moteur Atexo détecté    : oui → patchable, non → écosystème différent
  - HTTP 200 sur recherche  : oui → la requête passe
  - Détails consultation    : >0 → on a trouvé l'URL DCE → exploitable
                              0  → la ref n'est pas indexée publiquement
                                   ou format incompatible

  Cas exploitables :  patch dce_finder.py (whitelist + appel direct)
  Cas non-exploitables : à acter, le mur est structurel
""")


if __name__ == "__main__":
    main()
