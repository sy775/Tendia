"""
inspecter_page_dce.py
---------------------
Outil de diagnostic : récupère une page DCE, parse son HTML avec le même
parser que tendia_telecharger_dce.py, et imprime une vue détaillée de :
  - les liens trouvés (avec leur classification)
  - les formulaires détectés
  - les indicateurs login/captcha
  - le HTML brut autour des éléments clés

Sert à comprendre pourquoi une plateforme donnée échoue, sans avoir
à exécuter du `python -c` (qui crash en PowerShell sur certains setups).

Usage :
    python inspecter_page_dce.py <url>
    python inspecter_page_dce.py https://martinique-developpement.e-marchespublics.com/pack/annonce_marche_public_28655_1163195.html

Sauvegarde aussi le HTML brut dans `data/debug_<domaine>_<timestamp>.html`
pour analyse hors-ligne.
"""

import argparse
import io
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import requests

import tendia_telecharger_dce as t


USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/121.0.0.0 Safari/537.36")


def _domaine_safe(url: str) -> str:
    """Domaine slug-isé pour nom de fichier."""
    try:
        return re.sub(r"[^a-z0-9.]+", "_", urlparse(url).netloc.lower())
    except Exception:
        return "inconnu"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="URL de la page DCE à inspecter.")
    ap.add_argument("--save-html", action="store_true",
                    help="Sauve le HTML brut dans data/ pour analyse.")
    args = ap.parse_args()

    print("=" * 78)
    print(f"  Inspection : {args.url}")
    print("=" * 78)

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
    })

    try:
        r = session.get(args.url, timeout=30, allow_redirects=True)
    except requests.RequestException as e:
        print(f"  ❌ GET échoué : {type(e).__name__}: {e}")
        sys.exit(1)

    print(f"  URL finale  : {r.url}")
    print(f"  Status HTTP : {r.status_code}")
    print(f"  Content-Type: {r.headers.get('Content-Type', '?')}")
    print(f"  Taille HTML : {len(r.text)} chars")
    print()

    # Optionnel : sauver le HTML
    if args.save_html:
        Path("data").mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        nom = f"data/debug_{_domaine_safe(r.url)}_{ts}.html"
        with open(nom, "w", encoding="utf-8") as f:
            f.write(r.text)
        print(f"  ✓ HTML sauvé : {nom}")
        print()

    # Parse avec le parser officiel
    parser = t.PagePlaceParser()
    parser.feed(r.text)

    print(f"  Titre page          : {(parser.titre_page or '').strip()[:100]}")
    print(f"  Indicateur login    : {parser.indicateur_login}")
    print(f"  Indicateur captcha  : {parser.indicateur_captcha}")
    print(f"  Liens documents     : {len(parser.liens_documents)}")
    print(f"  Formulaires         : {len(parser.formulaires)}")
    print()

    # Détails liens
    if parser.liens_documents:
        print("-" * 78)
        print("  LIENS DOCUMENTS DÉTECTÉS PAR LE PARSER")
        print("-" * 78)
        for i, l in enumerate(parser.liens_documents, 1):
            origine = l.get("origine", "?")
            libelle = l.get("libelle", "")[:50]
            print(f"  [{i}] origine={origine}")
            print(f"      libelle: {libelle}")
            print(f"      href:    {l['href'][:120]}")
        print()

    # Détails formulaires
    if parser.formulaires:
        print("-" * 78)
        print("  FORMULAIRES DÉTECTÉS")
        print("-" * 78)
        for i, f in enumerate(parser.formulaires, 1):
            cgu = t._est_formulaire_consentement(f)
            method = f.get("method", "?")
            action = (f.get("action") or "(vide)")[:100]
            name = f.get("name", "")
            id_ = f.get("id", "")
            champs = f.get("champs") or {}
            print(f"  [{i}] method={method}  est_cgu={cgu}  name={name!r}  id={id_!r}")
            print(f"      action: {action}")
            if champs:
                print(f"      champs ({len(champs)}) :")
                for nom_c, info in list(champs.items())[:10]:
                    type_c = info.get("type", "?")
                    val = info.get("valeur", "")[:40]
                    print(f"        - {nom_c[:30]:<30} type={type_c:<10} val={val!r}")
                if len(champs) > 10:
                    print(f"        ... et {len(champs) - 10} autres")
            print()

    # === Liens HTML bruts (regex hors parser) ===
    # Le parser ne voit que les liens avec extension OU pattern URL.
    # Affichons TOUS les <a href=...> pour voir ce qu'on rate.
    print("-" * 78)
    print("  TOUS LES LIENS <a> DANS LA PAGE (top 30)")
    print("-" * 78)
    tous_a = re.findall(r'<a[^>]+href=["\']([^"\']+)["\']', r.text, re.IGNORECASE)
    interessants = []
    for href in tous_a:
        href_low = href.lower()
        # Filtre : on garde ceux qui contiennent un mot évoquant un DCE potentiel
        if any(kw in href_low for kw in (
                "telechargement", "download", "dce", "consultation",
                "detail", "annonce", "piece", "document", "retirer",
                "acceder", "voir", "ouvrir", "open", "consult",
                "pdf", "zip", "doc")):
            interessants.append(href)

    # Déduplique en gardant l'ordre
    seen = set()
    uniques = [h for h in interessants if not (h in seen or seen.add(h))]
    print(f"  Liens potentiellement DCE-related : {len(uniques)} (uniques, max 30 affichés)")
    for i, h in enumerate(uniques[:30], 1):
        print(f"  [{i:2d}] {h[:130]}")
    print()

    # === Boutons / formulaires qui pourraient être l'action DCE ===
    print("-" * 78)
    print("  BOUTONS/INPUTS SUSPECTS (value avec mot-clé DCE)")
    print("-" * 78)
    boutons = re.findall(
        r'<(?:button|input)[^>]*(?:value|name)=["\']([^"\']+)["\'][^>]*>',
        r.text, re.IGNORECASE)
    suspects = [b for b in boutons if any(kw in b.lower() for kw in (
        "dce", "telecharg", "download", "retirer", "consulter",
        "acceder", "voir", "ouvrir", "piece"))]
    seen = set()
    suspects = [b for b in suspects if not (b in seen or seen.add(b))]
    for s in suspects[:15]:
        print(f"  · {s[:100]}")
    print()

    print("=" * 78)
    print("  Diagnostic terminé. Partage cette sortie.")
    print("=" * 78)


if __name__ == "__main__":
    main()
