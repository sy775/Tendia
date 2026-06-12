"""
test_endpoint_download_reglement.py
-----------------------------------
Teste l'hypothèse découverte par diagnostic_chaine_atexo : l'endpoint
`?page=Entreprise.EntrepriseDownloadReglement&id=<base64(refCons)>&orgAcronyme=<orgCons>`
sert le RC directement sans passer par le formulaire à 31 champs.

Si vérifié → patch Phase 5 v2 : construire cette URL à partir de l'id +
orgAcronyme déjà extraits, et la tenter en priorité sur les plateformes
Atexo blanche modernes (Maximilien, Ternum, 596280, etc.).

Usage :
    python test_endpoint_download_reglement.py
"""

import base64
import io
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import requests


USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/120.0.0.0 Safari/537.36")


# Marchés à tester (id consultation + orgAcronyme + base URL)
CAS_TEST = [
    {
        "id_marche": "BOAMP-26-56411",
        "ref_cons": "940358",
        "org": "d7f",
        "base": "https://marches.maximilien.fr",
        "marche_url_dce": "https://marches.maximilien.fr/entreprise/consultation/940358?orgAcronyme=d7f",
    },
    {
        "id_marche": "BOAMP-26-56507",
        "ref_cons": "691953",
        "org": "i3q",
        "base": "https://marches.ternum-bfc.fr",
        "marche_url_dce": "https://marches.ternum-bfc.fr/index.php?page=Entreprise.EntrepriseDetailsConsultation&id=691953&orgAcronyme=i3q",
    },
    {
        "id_marche": "BOAMP-26-56583",
        "ref_cons": "940402",
        "org": "f4q",
        "base": "https://marches.maximilien.fr",
        "marche_url_dce": "https://marches.maximilien.fr/entreprise/consultation/940402?orgAcronyme=f4q",
    },
]


def b64(s: str) -> str:
    """Encode une chaîne en base64 (sans padding, format Atexo)."""
    return base64.b64encode(s.encode()).decode()


def main():
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "fr-FR,fr;q=0.9",
    })

    print("=" * 78)
    print("  Test endpoint Atexo EntrepriseDownloadReglement")
    print("=" * 78)
    print()

    for cas in CAS_TEST:
        ref_b64 = b64(cas["ref_cons"])
        url_dl = (f"{cas['base']}/index.php"
                  f"?page=Entreprise.EntrepriseDownloadReglement"
                  f"&id={ref_b64}"
                  f"&orgAcronyme={cas['org']}")

        print(f"  ── {cas['id_marche']} ──")
        print(f"  refCons    : {cas['ref_cons']} → base64 = {ref_b64}")
        print(f"  orgAcronyme: {cas['org']}")
        print(f"  URL test   : {url_dl}")

        # IMPORTANT : on visite d'abord la page de consultation pour récupérer
        # les cookies de session, c'est probablement requis.
        try:
            r_init = session.get(cas["marche_url_dce"], timeout=30,
                                 allow_redirects=True)
            print(f"  Étape 1 (cookies) : HTTP {r_init.status_code}, "
                  f"{len(session.cookies)} cookies")
        except requests.RequestException as e:
            print(f"  ❌ Erreur sur l'init : {e}")
            print()
            continue

        # Maintenant GET sur l'endpoint cible
        try:
            r = session.get(url_dl, timeout=60, stream=True,
                            allow_redirects=True)
        except requests.RequestException as e:
            print(f"  ❌ Erreur sur le DL : {e}")
            print()
            continue

        ctype = r.headers.get("Content-Type") or "?"
        cdisp = r.headers.get("Content-Disposition") or ""
        clen = r.headers.get("Content-Length") or "?"
        print(f"  Étape 2 (DL)      : HTTP {r.status_code}")
        print(f"    Content-Type        : {ctype}")
        print(f"    Content-Disposition : {cdisp[:80] if cdisp else '(absent)'}")
        print(f"    Content-Length      : {clen}")

        # Lit un peu pour voir
        if r.status_code == 200:
            try:
                chunk = next(r.iter_content(2048), b"")
            except Exception as e:
                chunk = b""
                print(f"    ⚠ Erreur lecture stream : {e}")

            # Heuristique : est-ce binaire ou HTML ?
            if "html" in ctype.lower():
                # Affiche le titre HTML pour comprendre
                txt = chunk.decode("utf-8", errors="replace")
                if "<title>" in txt.lower():
                    deb = txt.lower().find("<title>") + 7
                    fin = txt.lower().find("</title>")
                    titre = txt[deb:fin].strip()[:100]
                    print(f"    ⚠ HTML reçu, titre : '{titre}'")
                else:
                    print(f"    ⚠ HTML reçu, début : {txt[:200]}")
                print(f"    → VERDICT : page intermédiaire, endpoint pas direct")
            elif chunk.startswith(b"PK"):
                # ZIP
                print(f"    ✓ ✓ ✓ ZIP détecté (signature PK)")
                print(f"    → VERDICT : endpoint sert directement le ZIP DCE")
            elif chunk.startswith(b"%PDF"):
                # PDF
                print(f"    ✓ ✓ ✓ PDF détecté (signature %PDF)")
                print(f"    → VERDICT : endpoint sert directement le PDF RC")
            else:
                print(f"    ? Binaire inconnu : début hex = "
                      f"{chunk[:16].hex()}")
                print(f"    → VERDICT : à creuser")
        elif r.status_code == 404:
            print(f"    → VERDICT : 404, l'endpoint n'existe pas ou refCons "
                  f"invalide")
        elif r.status_code in (301, 302, 303, 307, 308):
            print(f"    Redirect vers : {r.headers.get('Location', '?')[:100]}")
        else:
            print(f"    → VERDICT : HTTP {r.status_code} inattendu")

        # Cleanup pour libérer le stream
        r.close()
        print()


if __name__ == "__main__":
    main()
