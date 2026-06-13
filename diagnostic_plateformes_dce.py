"""
diagnostic_plateformes_dce.py
-----------------------------
Diagnostic des plateformes DCE anonymes (Sprint Téléchargeur Profond, Livrable 0).
Pour chaque plateforme cible, prend 2-3 marchés `incomplet`, GET la page DCE et
liste les pièces téléchargeables exposées. NE TÉLÉCHARGE RIEN, ne modifie rien.

Nécessite un accès réseau (à lancer sur ta machine).
Usage : python diagnostic_plateformes_dce.py
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import requests
import stockage
import tendia_telecharger_dce as T

PLATEFORMES = {
    "PLACE (marches-publics.gouv.fr)": ["marches-publics.gouv.fr"],
    "e-marchespublics": ["e-marchespublics.com"],
    "ternum-bfc": ["ternum-bfc.fr"],
    "demat-ampa": ["demat-ampa.fr"],
    "megalis": ["megalis"],
    "maximilien": ["maximilien.fr"],
}


def main():
    marches = stockage.charger("marches") or {}
    session = requests.Session()
    session.headers.update({"User-Agent": T.USER_AGENT,
                            "Accept-Language": "fr-FR,fr;q=0.9"})

    for nom, hosts in PLATEFORMES.items():
        cibles = [m for m in marches.values()
                  if m.get("dce_contenu") == "incomplet"
                  and any(h in (m.get("url_dce") or "").lower() for h in hosts)][:3]
        print("\n" + "=" * 72)
        print(f"=== Plateforme : {nom} ===")
        print(f"Échantillon : {len(cibles)} marché(s) incomplet")
        if not cibles:
            print("  (aucun marché incomplet sur cette plateforme)")
            continue
        for m in cibles:
            url = m.get("url_dce") or ""
            print(f"\nMarché {m.get('id')}")
            print(f"  URL DCE : {url[:110]}")
            try:
                r = session.get(url, timeout=30)
                print(f"  HTTP status : {r.status_code} | taille HTML : {len(r.text)}")
                pieces = T._pieces_depuis_html(r.text, url)
            except Exception as e:
                print(f"  ERREUR : {type(e).__name__}: {e}")
                continue
            pdfs = [p for p in pieces if p["url"].lower().split('?')[0].endswith(('.pdf', '.doc', '.docx', '.xls', '.xlsx'))]
            zips = [p for p in pieces if p["type_detecte"] == "ZIP_GLOBAL"]
            print(f"  Liens documents trouvés : {len(pdfs)}")
            for p in pdfs[:8]:
                print(f"    - [{p['type_detecte']}] {p['url'][:90]}")
            print(f"  Liens archive (ZIP global) : {len(zips)}")
            for p in zips[:3]:
                print(f"    - {p['url'][:90]}")
            types = sorted({p["type_detecte"] for p in pieces if p["type_detecte"] != "autre"})
            print(f"  Types contractuels vus : {types}")
            if not pieces:
                print("  ⚠ Aucun lien document en href : page probablement dynamique "
                      "(boutons JS / POST) → parseur spécifique requis.")

    print("\n" + "=" * 72)
    print("Stratégie suggérée par plateforme : voir ci-dessus —")
    print("  · ZIP global présent  -> privilégier l'archive (1 DL)")
    print("  · liens href multiples -> stratégie générique OK")
    print("  · 0 lien href          -> reverse-engineer le JS/POST (parseur dédié)")


if __name__ == "__main__":
    main()
