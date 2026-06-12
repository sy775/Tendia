"""
diagnostic_chaine_atexo.py
--------------------------
Dump le HTML et les structures (liens, formulaires) à chaque étape de la
chaîne Atexo (Maximilien, Ternum-BFC, 596280, etc.) pour comprendre
pourquoi notre Phase 5 échoue à franchir la page intermédiaire
`EntrepriseDemandeTelechargementSansIdentification`.

Workflow :
1. GET sur la page consultation initiale
2. Trouve le lien EntrepriseDemandeTelechargement... (URL complète, pas tronquée)
3. GET sur cette URL intermédiaire
4. Affiche : tous les liens, tous les formulaires (avec leurs champs détaillés),
   contenu lisible (texte sans HTML), et un extrait HTML brut autour du form
   de téléchargement attendu.
5. Optionnel : POST si --soumettre, voit ce qu'on reçoit en retour.

Usage :
    python diagnostic_chaine_atexo.py --url "https://marches.maximilien.fr/entreprise/consultation/940358?orgAcronyme=d7f"
    python diagnostic_chaine_atexo.py --url "..." --soumettre
"""

import argparse
import io
import re
import sys
from urllib.parse import urljoin

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import requests

import tendia_telecharger_dce as tdce


def _resume_form(form: dict, idx: int) -> str:
    """Affichage compact d'un formulaire."""
    method = form.get("method") or "GET"
    action = form.get("action") or "(même page)"
    champs = form.get("champs") or {}

    lignes = [f"  [Form {idx}] {method} → {action[:80]}"]
    lignes.append(f"    Champs ({len(champs)}) :")
    for nom, info in champs.items():
        typ = info.get("type") or "?"
        val = info.get("valeur") or ""
        oblig = " *" if info.get("required") else ""
        if typ in ("hidden",):
            preview = f"={val[:30]}" if val else ""
            lignes.append(f"      [hidden]    {nom}{preview}{oblig}")
        elif typ in ("submit", "button"):
            lignes.append(f"      [{typ:<10}] {nom} value='{val[:40]}'")
        elif typ == "checkbox":
            lignes.append(f"      [checkbox]  {nom}{oblig}")
        else:
            preview = f"={val[:30]}" if val else ""
            lignes.append(f"      [{typ:<10}] {nom}{preview}{oblig}")

    # Diagnostic : nos heuristiques pensent quoi de ce form ?
    is_cgu = tdce._est_formulaire_consentement(form)
    is_dl = tdce._est_formulaire_telechargement_direct(form)
    diag = []
    if is_cgu:
        diag.append("✓ détecté CGU")
    if is_dl:
        diag.append("✓ détecté téléchargement direct")
    if not diag:
        diag.append("✗ non détecté par nos heuristiques")
    lignes.append(f"    Diagnostic : {' | '.join(diag)}")
    return "\n".join(lignes)


def _dump_page(html: str, url: str, label: str, max_html_chars: int = 4000):
    """Parse et dump une page HTML avec nos parsers existants."""
    print("=" * 80)
    print(f"  [{label}]")
    print(f"  URL : {url[:120]}")
    print(f"  Taille HTML : {len(html)} chars")
    print("=" * 80)

    parser = tdce.PagePlaceParser()
    parser.feed(html)

    print(f"  Titre page          : {parser.titre_page[:90] if parser.titre_page else '(vide)'}")
    print(f"  Indicateur captcha  : {parser.indicateur_captcha}")
    print(f"  Indicateur login    : {parser.indicateur_login}")
    print(f"  Liens documents     : {len(parser.liens_documents)}")
    for l in parser.liens_documents[:10]:
        print(f"    · {l['href'][:110]}")
    print(f"  Formulaires         : {len(parser.formulaires)}")
    print()
    for i, f in enumerate(parser.formulaires, 1):
        print(_resume_form(f, i))
        print()

    # Cherche tous les <form> bruts dans le HTML pour comparaison
    formes_brutes = re.findall(r'<form\b[^>]*>', html, re.IGNORECASE)
    if len(formes_brutes) != len(parser.formulaires):
        print(f"  ⚠ {len(formes_brutes)} <form> dans le HTML brut "
              f"vs {len(parser.formulaires)} détectés par parser")

    # Cherche les boutons et liens contenant "téléchar"
    boutons_dl = re.findall(
        r'<(?:button|input|a)[^>]*(?:téléchar|telechar|download|valider'
        r'|telechargement)[^>]*>',
        html, re.IGNORECASE
    )
    if boutons_dl:
        print(f"\n  Boutons/liens 'téléchargement' bruts ({len(boutons_dl)}) :")
        for b in boutons_dl[:8]:
            print(f"    {b[:150]}")

    # Cherche les scripts (JS éventuel)
    nb_scripts = len(re.findall(r'<script\b', html, re.IGNORECASE))
    if nb_scripts > 5:
        print(f"\n  ⚠ {nb_scripts} balises <script> dans la page "
              f"(form peut être JS-only)")

    # Cherche les frames/iframes
    iframes = re.findall(r'<iframe[^>]*src=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if iframes:
        print(f"\n  ⚠ Iframes détectées :")
        for src in iframes:
            print(f"    · {src[:100]}")

    # Extrait HTML brut autour des forms (utile pour voir si JS bloque)
    if "<form" in html.lower():
        print(f"\n  Extrait HTML autour du premier <form> :")
        idx = html.lower().find("<form")
        debut = max(0, idx - 100)
        fin = min(len(html), idx + max_html_chars)
        snippet = html[debut:fin]
        print("  " + "-" * 78)
        for line in snippet.split("\n")[:60]:
            print("    " + line[:120])
        print("  " + "-" * 78)

    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True,
                    help="URL de la page consultation initiale Atexo.")
    ap.add_argument("--soumettre", action="store_true",
                    help="Tente aussi un POST sur le form de téléchargement "
                         "et dumpe ce qu'on reçoit en retour.")
    ap.add_argument("--profondeur", type=int, default=2,
                    help="Profondeur max d'investigation (default: 2).")
    args = ap.parse_args()

    session = requests.Session()
    session.headers.update({
        "User-Agent": tdce.USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
    })

    # === Étape 1 : page initiale ===
    print(f"\n>>> GET {args.url[:100]}\n")
    r = session.get(args.url, timeout=30, allow_redirects=True)
    print(f"    HTTP {r.status_code}, content-type={r.headers.get('Content-Type', '?')}")
    if r.status_code != 200:
        print("Échec de la requête initiale.")
        return
    _dump_page(r.text, args.url, "ÉTAPE 1 — Page consultation initiale")

    # === Étape 2 : trouver l'URL intermédiaire EntrepriseDemandeTelechargement ===
    parser = tdce.PagePlaceParser()
    parser.feed(r.text)

    url_inter = None
    for l in parser.liens_documents:
        if tdce._est_url_intermediaire_atexo(l["href"]):
            url_inter = urljoin(args.url, l["href"])
            break

    # Fallback : chercher dans tout le HTML (pas seulement liens_documents)
    if not url_inter:
        matches = re.findall(
            r'href=["\']([^"\']*entreprisedemandetelechargement[^"\']*)["\']',
            r.text, re.IGNORECASE
        )
        if matches:
            url_inter = urljoin(args.url, matches[0].replace("&amp;", "&"))

    if not url_inter:
        print("⚠ Aucun lien EntrepriseDemandeTelechargement trouvé sur la page "
              "initiale. Phase 5 ne s'applique pas à ce marché.")
        return

    if args.profondeur < 1:
        return

    # === Étape 3 : suivre la page intermédiaire ===
    print(f"\n>>> GET {url_inter[:120]}\n")
    r2 = session.get(url_inter, timeout=30, allow_redirects=True)
    print(f"    HTTP {r2.status_code}, content-type={r2.headers.get('Content-Type', '?')}, "
          f"taille={len(r2.content)} octets")

    ctype = (r2.headers.get("Content-Type") or "").lower()
    if "text/html" not in ctype:
        # On a directement un binaire — gros indice que ça devrait marcher
        print(f"\n  ✓ ✓ ✓ Réponse binaire directe ({ctype}) !")
        print(f"  → Atexo nous sert directement le document sur GET de l'URL intermédiaire.")
        print(f"  → Notre code Phase 5 devrait gérer ça, vérifier pourquoi il ne le fait pas.")
        return

    _dump_page(r2.text, url_inter, "ÉTAPE 2 — Page intermédiaire Atexo")

    # === Étape 4 (optionnel) : soumettre le form ===
    if args.soumettre:
        parser2 = tdce.PagePlaceParser()
        parser2.feed(r2.text)
        if not parser2.formulaires:
            print("⚠ Aucun form sur la page intermédiaire, rien à soumettre.")
            return
        # Prend le premier form pour test
        form = parser2.formulaires[0]
        action_url = urljoin(url_inter, form.get("action") or "")
        data = tdce._data_form(form)
        print(f"\n>>> POST {action_url[:120]}")
        print(f"    data={list(data.keys())}")
        r3 = session.post(action_url, data=data, timeout=30, allow_redirects=True)
        print(f"    HTTP {r3.status_code}, content-type={r3.headers.get('Content-Type', '?')}, "
              f"taille={len(r3.content)} octets")
        if "text/html" in (r3.headers.get("Content-Type") or "").lower():
            _dump_page(r3.text, action_url, "ÉTAPE 3 — Réponse au POST form intermédiaire")
        else:
            print(f"  ✓ Réponse binaire après POST !")


if __name__ == "__main__":
    main()
