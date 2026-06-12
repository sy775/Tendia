"""
scraper_place_discover.py
-------------------------
Découverte du fonctionnement de la recherche PLACE par Playwright.

Premier run : navigateur Chromium VISIBLE et ralenti pour qu'on observe
ce qui se passe à chaque étape. Screenshots et HTML dumpés dans data/debug/.

Plan :
1. Va sur la page de recherche avancée PLACE
2. Explore le formulaire (liste tous les champs interactifs)
3. Cherche le champ "Acheteur public" et y tape "France Travail"
4. Clique "Lancer la recherche"
5. Récupère la page de résultats avec les consultations FT

Usage :
    python scraper_place_discover.py             # mode visible (recommandé)
    python scraper_place_discover.py --headless  # mode invisible (après validation)
    python scraper_place_discover.py --explore   # juste exploration formulaire
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("❌ Playwright pas installé. Lance :")
    print("    pip install playwright")
    print("    playwright install chromium")
    sys.exit(1)


REPERTOIRE_DEBUG = Path(__file__).parent / "data" / "debug" / "place_scraper"
REPERTOIRE_DEBUG.mkdir(parents=True, exist_ok=True)

URL_RECHERCHE_AVANCEE = (
    "https://www.marches-publics.gouv.fr/"
    "?page=Entreprise.EntrepriseAdvancedSearch&AllCons"
)


# ---------------------------------------------------------------------------
# Helpers de logging et debug
# ---------------------------------------------------------------------------

def _log(etape: str, msg: str = ""):
    print(f"[{etape}] {msg}")


def _screenshot(page, nom: str):
    """Screenshot horodaté."""
    chemin = REPERTOIRE_DEBUG / f"{nom}.png"
    try:
        page.screenshot(path=str(chemin), full_page=True)
        print(f"    📸 Screenshot : {chemin.name}")
    except Exception as e:
        print(f"    ⚠ Screenshot raté : {e}")


def _dump_html(page, nom: str):
    """Dump HTML de la page courante."""
    chemin = REPERTOIRE_DEBUG / f"{nom}.html"
    try:
        chemin.write_text(page.content(), encoding="utf-8")
        print(f"    💾 HTML : {chemin.name} ({chemin.stat().st_size} octets)")
    except Exception as e:
        print(f"    ⚠ Dump HTML raté : {e}")


# ---------------------------------------------------------------------------
# Exploration du formulaire (étape clé pour identifier les sélecteurs)
# ---------------------------------------------------------------------------

def explorer_formulaire(page) -> dict:
    """
    Explore le formulaire de recherche avancée et liste tous les champs.

    Retourne un dict avec :
        {
          "inputs": [(name, id, type, label_visible), ...],
          "selects": [(name, id, options_count), ...],
          "boutons": [(text, id, type), ...],
        }
    """
    _log("EXPLO", "Inventaire des champs du formulaire...")

    # Récupère les inputs interactifs (text, search, hidden, etc.)
    inputs_info = page.evaluate("""() => {
        const inputs = Array.from(document.querySelectorAll('input'));
        return inputs.map(inp => {
            // Cherche le label associé
            let label = '';
            if (inp.id) {
                const lbl = document.querySelector(`label[for="${inp.id}"]`);
                if (lbl) label = lbl.innerText.trim();
            }
            if (!label && inp.placeholder) label = inp.placeholder;
            if (!label && inp.title) label = inp.title;
            return {
                name: inp.name || '',
                id: inp.id || '',
                type: inp.type || 'text',
                value: (inp.value || '').substring(0, 50),
                label: label.substring(0, 80),
                visible: inp.offsetParent !== null,
            };
        }).filter(i => i.visible && i.type !== 'hidden');
    }""")

    selects_info = page.evaluate("""() => {
        const selects = Array.from(document.querySelectorAll('select'));
        return selects.map(s => {
            let label = '';
            if (s.id) {
                const lbl = document.querySelector(`label[for="${s.id}"]`);
                if (lbl) label = lbl.innerText.trim();
            }
            return {
                name: s.name || '',
                id: s.id || '',
                options: s.options.length,
                label: label.substring(0, 80),
                visible: s.offsetParent !== null,
            };
        }).filter(s => s.visible);
    }""")

    boutons_info = page.evaluate("""() => {
        const btns = Array.from(document.querySelectorAll('button, input[type="submit"], input[type="button"], a.button, a.btn'));
        return btns.map(b => ({
            text: (b.innerText || b.value || '').trim().substring(0, 80),
            id: b.id || '',
            name: b.name || '',
            type: b.type || 'button',
            tag: b.tagName.toLowerCase(),
            visible: b.offsetParent !== null,
        })).filter(b => b.visible && b.text);
    }""")

    print(f"\n  Champs INPUT visibles ({len(inputs_info)}) :")
    for i in inputs_info[:20]:
        print(f"    [{i['type']:<8}] name='{i['name']}' id='{i['id']}'")
        if i['label']:
            print(f"               label='{i['label']}'")

    print(f"\n  SELECTS visibles ({len(selects_info)}) :")
    for s in selects_info[:15]:
        print(f"    name='{s['name']}' id='{s['id']}' "
              f"options={s['options']} label='{s['label']}'")

    print(f"\n  BOUTONS visibles ({len(boutons_info)}) :")
    for b in boutons_info[:15]:
        print(f"    [{b['type']:<8}] text='{b['text']}' id='{b['id']}'")

    # Cherche les champs probablement liés à l'acheteur
    print(f"\n  🎯 Champs candidats pour 'Acheteur / Entité publique' :")
    mots_cles_acheteur = ["acheteur", "entit", "ministere", "ministère",
                            "etablissement", "organisme", "publique", "buyer"]
    for i in inputs_info + selects_info:
        texte = (i.get('label', '') + ' ' + i.get('name', '') +
                  ' ' + i.get('id', '')).lower()
        for mc in mots_cles_acheteur:
            if mc in texte:
                print(f"    → {i.get('name')} / {i.get('id')} "
                      f"(label: {i.get('label')})")
                break

    # Cherche les champs liés à "recherche" ou "soumission"
    print(f"\n  🎯 Boutons candidats pour 'Lancer la recherche' :")
    mots_cles_search = ["recherche", "rechercher", "lancer", "search",
                          "valider", "submit", "envoyer"]
    for b in boutons_info:
        texte = (b.get('text', '') + ' ' + b.get('name', '') +
                  ' ' + b.get('id', '')).lower()
        for mc in mots_cles_search:
            if mc in texte:
                print(f"    → {b.get('text')} (id: {b.get('id')})")
                break

    return {
        "inputs": inputs_info,
        "selects": selects_info,
        "boutons": boutons_info,
    }


# ---------------------------------------------------------------------------
# Workflow principal
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--headless", action="store_true",
                        help="Navigateur invisible (par défaut visible)")
    parser.add_argument("--explore", action="store_true",
                        help="Juste explorer le formulaire, ne rien soumettre")
    parser.add_argument("--slow", type=int, default=800,
                        help="Délai ms entre actions (visualisation)")
    args = parser.parse_args()

    print(f"Mode : {'HEADLESS' if args.headless else 'VISIBLE'}")
    print(f"Dossier debug : {REPERTOIRE_DEBUG}")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=args.headless,
            slow_mo=args.slow if not args.headless else 0,
        )
        try:
            context = browser.new_context(
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"),
                locale="fr-FR",
                viewport={"width": 1400, "height": 900},
            )
            page = context.new_page()

            # === Étape 1 : Charger la page de recherche avancée ===
            _log("STEP 1", f"GET {URL_RECHERCHE_AVANCEE}")
            try:
                page.goto(URL_RECHERCHE_AVANCEE,
                           timeout=30000, wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle", timeout=20000)
            except PWTimeout:
                _log("STEP 1", "⚠ Timeout networkidle, on continue quand même.")
            _screenshot(page, "01_page_chargee")
            _dump_html(page, "01_page_chargee")
            print(f"    URL actuelle : {page.url}")
            print(f"    Title : {page.title()}")

            # === Étape 2 : Explorer le formulaire ===
            print()
            inventaire = explorer_formulaire(page)
            (REPERTOIRE_DEBUG / "02_inventaire.json").write_text(
                json.dumps(inventaire, ensure_ascii=False, indent=2),
                encoding="utf-8")

            if args.explore:
                print("\n✓ Mode --explore : on s'arrête après l'inventaire.")
                print(f"  Consulte {REPERTOIRE_DEBUG}/02_inventaire.json")
                return

            # === Étape 3 : Trouver et remplir le champ Acheteur ===
            print()
            _log("STEP 3", "Recherche du champ Acheteur public...")
            candidats_selectors = [
                'input[placeholder*="Acheteur"]',
                'input[placeholder*="Entit"]',
                'input[id*="Acheteur"]',
                'input[id*="entiteAchat"]',
                'input[id*="organisme"]',
                'input[name*="acheteur"]',
                'input[name*="Acheteur"]',
                'input[type="text"][autocomplete]',
            ]
            champ_acheteur = None
            for sel in candidats_selectors:
                try:
                    el = page.locator(sel).first
                    if el.count() > 0 and el.is_visible():
                        champ_acheteur = el
                        _log("STEP 3", f"  ✓ Trouvé avec : {sel}")
                        break
                except Exception:
                    continue

            if champ_acheteur is None:
                _log("STEP 3", "  ❌ Aucun champ acheteur trouvé.")
                _log("STEP 3", "    Consulte les screenshots/HTML/inventaire.")
                _screenshot(page, "03_pas_champ_acheteur")
                return

            try:
                champ_acheteur.click()
                champ_acheteur.fill("France Travail")
                time.sleep(1)
                _screenshot(page, "03_acheteur_tape")
                _log("STEP 3", "  ✓ 'France Travail' tapé.")
            except Exception as e:
                _log("STEP 3", f"  ⚠ Erreur saisie : {e}")
                _screenshot(page, "03_erreur_saisie")
                return

            # Essayer d'attendre une auto-complétion ou suggestion
            try:
                page.wait_for_selector(
                    'li:has-text("France Travail"), '
                    '.autocomplete-suggestion:has-text("France Travail"), '
                    '.ui-menu-item:has-text("France Travail")',
                    timeout=4000)
                _log("STEP 3", "  ✓ Suggestion visible, on clique.")
                page.locator(
                    'li:has-text("France Travail"), '
                    '.autocomplete-suggestion:has-text("France Travail"), '
                    '.ui-menu-item:has-text("France Travail")'
                ).first.click()
                _screenshot(page, "03_acheteur_selectionne")
            except PWTimeout:
                _log("STEP 3", "  (pas d'auto-complétion détectée, on continue)")

            # === Étape 4 : Cliquer "Lancer la recherche" ===
            print()
            _log("STEP 4", "Recherche du bouton 'Lancer la recherche'...")
            candidats_bouton = [
                'button:has-text("Lancer la recherche")',
                'input[value="Lancer la recherche"]',
                'a:has-text("Lancer la recherche")',
                'button:has-text("Rechercher")',
                'input[value="Rechercher"]',
                'input[type="submit"]',
                'button[type="submit"]',
            ]
            bouton = None
            for sel in candidats_bouton:
                try:
                    el = page.locator(sel).first
                    if el.count() > 0 and el.is_visible():
                        bouton = el
                        _log("STEP 4", f"  ✓ Trouvé avec : {sel}")
                        break
                except Exception:
                    continue

            if bouton is None:
                _log("STEP 4", "  ❌ Aucun bouton de recherche trouvé.")
                _screenshot(page, "04_pas_bouton")
                return

            try:
                bouton.click()
                _log("STEP 4", "  → Clic effectué, attente du rendu...")
                page.wait_for_load_state("networkidle", timeout=30000)
                time.sleep(2)
            except PWTimeout:
                _log("STEP 4", "  ⚠ Timeout networkidle après clic.")
            _screenshot(page, "05_resultats")
            _dump_html(page, "05_resultats")
            print(f"    URL après recherche : {page.url}")
            print(f"    Title : {page.title()}")

            # === Étape 5 : Analyser les résultats ===
            print()
            _log("STEP 5", "Analyse des résultats...")
            urls_consultations = page.evaluate("""() => {
                const liens = Array.from(document.querySelectorAll('a[href*="EntrepriseDetailsConsultation"]'));
                return liens.map(a => ({
                    href: a.href,
                    text: a.innerText.trim().substring(0, 100),
                }));
            }""")
            print(f"  Liens 'EntrepriseDetailsConsultation' trouvés : "
                  f"{len(urls_consultations)}")
            for u in urls_consultations[:10]:
                print(f"    {u['text'][:60]}")
                print(f"      → {u['href'][:150]}")

            # Sauve aussi un résumé
            (REPERTOIRE_DEBUG / "05_resultats_urls.json").write_text(
                json.dumps(urls_consultations, ensure_ascii=False, indent=2),
                encoding="utf-8")

            print()
            print("=" * 70)
            print("FIN — Consulte le dossier debug :")
            print(f"  {REPERTOIRE_DEBUG}")
            print()
            if not args.headless:
                print("Navigateur reste ouvert 30s pour observation finale...")
                time.sleep(30)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
