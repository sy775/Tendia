"""
place_form_inspect.py
---------------------
Script de découverte : analyse le formulaire PLACE de téléchargement DCE
pour comprendre sa structure (champs, action, méthode, tokens cachés).

Lance simplement :
    python place_form_inspect.py

Le script :
1. Va sur la page de téléchargement DCE du marché MILE (id=3003304)
2. Récupère le HTML, sauve dans data/debug/place_form.html
3. Parse tous les inputs/forms et imprime un rapport
4. Tente un POST avec radio "anonyme" + case CGU cochées
5. Sauve la réponse dans data/debug/place_post_response.html
6. Imprime ce qui s'est passé (succès, échec, contenu retourné)

Pas besoin de Playwright, pas besoin de captcha — du simple HTTP.
"""

import os
import re
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERREUR : la lib 'requests' manque. Lance : pip install requests")
    sys.exit(1)

DEBUG_DIR = Path(__file__).parent / "data" / "debug" / "place_form"
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

URL_FORMULAIRE = (
    "https://www.marches-publics.gouv.fr/index.php"
    "?page=Entreprise.EntrepriseDemandeTelechargementDce"
    "&id=3003304&orgAcronyme=h8j"
)


def main():
    print("=" * 75)
    print("  PLACE — Inspection formulaire téléchargement DCE")
    print("=" * 75)
    print()

    # Session HTTP avec cookies persistants
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
        "Accept-Language": "fr-FR,fr;q=0.9",
    })

    # ====== ÉTAPE 1 : GET la page formulaire ======
    print(f"[1] GET {URL_FORMULAIRE[:80]}...")
    try:
        r = session.get(URL_FORMULAIRE, timeout=30, allow_redirects=True)
        print(f"    HTTP {r.status_code}")
        print(f"    URL finale : {r.url[:100]}")
        print(f"    Taille HTML : {len(r.text)} octets")
        print(f"    Cookies session : {len(session.cookies)} cookies")
        for c in session.cookies:
            print(f"      - {c.name} = {c.value[:30]}...")

        # Sauve le HTML
        chemin_html = DEBUG_DIR / "01_formulaire.html"
        chemin_html.write_text(r.text, encoding="utf-8")
        print(f"    HTML sauvé : {chemin_html}")
    except Exception as e:
        print(f"    ERREUR : {e}")
        return

    html = r.text

    # ====== ÉTAPE 2 : Parser le formulaire ======
    print()
    print("[2] Analyse de la structure du formulaire...")

    # Trouve toutes les balises <form>
    forms = re.findall(
        r'<form([^>]*)>(.*?)</form>',
        html, re.DOTALL | re.IGNORECASE
    )
    print(f"    Nombre de <form> : {len(forms)}")
    for i, (attrs, content) in enumerate(forms):
        action_m = re.search(r'action\s*=\s*["\']([^"\']+)["\']',
                              attrs, re.IGNORECASE)
        method_m = re.search(r'method\s*=\s*["\']([^"\']+)["\']',
                              attrs, re.IGNORECASE)
        name_m = re.search(r'name\s*=\s*["\']([^"\']+)["\']',
                            attrs, re.IGNORECASE)
        id_m = re.search(r'id\s*=\s*["\']([^"\']+)["\']',
                          attrs, re.IGNORECASE)
        print(f"\n    Form #{i+1} :")
        print(f"      name   = {name_m.group(1) if name_m else '—'}")
        print(f"      id     = {id_m.group(1) if id_m else '—'}")
        print(f"      action = {action_m.group(1) if action_m else '—'}")
        print(f"      method = {method_m.group(1) if method_m else 'GET'}")

    # Trouve tous les inputs (visibles ET cachés ET cachés-par-style)
    # IMPORTANT : Prado/Atexo utilise <input type="text" style="display:none">
    # pour PRADO_PAGESTATE (≈17 KB) — il faut l'inclure dans le POST sinon
    # le serveur ré-affiche la page d'origine sans traiter notre choix.
    print()
    print("[3] Tous les <input> :")
    inputs = re.findall(r'<input([^>]+)>', html, re.IGNORECASE)
    radios_anonyme = []
    checkboxes_cgu = []
    all_fields = {}  # nom -> valeur (TOUS les inputs nommés)
    submit_buttons = []
    hidden_count = 0

    for inp in inputs:
        type_m = re.search(r'type\s*=\s*["\']?([^"\'\s>]+)', inp, re.IGNORECASE)
        name_m = re.search(r'name\s*=\s*["\']?([^"\'\s>]+)', inp, re.IGNORECASE)
        value_m = re.search(r'value\s*=\s*["\']([^"\']*)["\']',
                             inp, re.IGNORECASE)
        id_m = re.search(r'id\s*=\s*["\']?([^"\'\s>]+)', inp, re.IGNORECASE)
        checked = "checked" in inp.lower()
        type_v = type_m.group(1) if type_m else "text"
        name_v = name_m.group(1) if name_m else ""
        value_v = value_m.group(1) if value_m else ""
        id_v = id_m.group(1) if id_m else ""

        # Skip inputs sans name (ne sont jamais envoyés en POST)
        if not name_v:
            continue

        if type_v == "submit":
            submit_buttons.append({"name": name_v, "value": value_v})
            continue  # ne pas ajouter aux champs par défaut

        if type_v == "radio":
            # On garde la radio par défaut (checked=True) sauf si on a une meilleure
            if checked and name_v not in all_fields:
                all_fields[name_v] = value_v
            label = _trouver_label_proche(html, id_v, name_v)
            print(f"      [radio]    name={name_v[-40:]:>40} value={value_v[-30:]:>30} checked={checked}")
            if label and ("anonym" in label.lower() or "anonym" in value_v.lower()):
                radios_anonyme.append({"name": name_v, "value": value_v,
                                          "id": id_v, "label": label})
        elif type_v == "checkbox":
            # Par défaut, on n'envoie PAS la case (en HTML, décochée = absente)
            # On l'ajoutera plus tard si on veut la cocher
            label = _trouver_label_proche(html, id_v, name_v)
            if "cgu" in (label or "").lower() or \
                    "conditions" in (label or "").lower() or \
                    "accepte" in (label or "").lower():
                checkboxes_cgu.append({"name": name_v, "value": value_v,
                                          "id": id_v, "label": label})
        else:
            # type=hidden OU type=text (incluant PRADO_PAGESTATE display:none)
            all_fields[name_v] = value_v
            if type_v == "hidden" or "display:none" in inp.lower():
                hidden_count += 1

    print()
    print(f"    Total inputs nommés capturés : {len(all_fields)}")
    print(f"    Dont hidden ou display:none : {hidden_count}")

    # Signal les champs gros (state)
    print("\n    Champs au volume notable (>100 chars) :")
    for k, v in all_fields.items():
        if len(str(v)) > 100:
            print(f"      {k} ({len(v)} chars) : {str(v)[:60]}...")

    print()
    print(f"    🔘 Radios candidats 'anonyme' : {len(radios_anonyme)}")
    for r_ in radios_anonyme:
        print(f"      → {r_['name']} = {r_['value']}")
    print(f"    ☑️  Checkboxes candidates CGU : {len(checkboxes_cgu)}")
    for c_ in checkboxes_cgu:
        print(f"      → {c_['name']} = {c_['value']!r}")
    print(f"    🟢 Boutons submit : {len(submit_buttons)}")
    for b_ in submit_buttons:
        print(f"      → {b_}")

    # ====== ÉTAPE 3 : Tenter le POST ======
    print()
    print("[4] Tentative de POST avec radio 'anonyme' + CGU cochées...")

    # Construit le payload : tous les inputs nommés + override de la radio
    # vers 'anonyme', + case CGU cochée
    payload = dict(all_fields)
    if radios_anonyme:
        r_ano = radios_anonyme[0]
        payload[r_ano["name"]] = r_ano["value"]  # remplace le défaut
    if checkboxes_cgu:
        c_cgu = checkboxes_cgu[0]
        # Pour une checkbox, l'envoyer comme "on" (convention HTML par défaut)
        payload[c_cgu["name"]] = "on"

    # Garde une trace
    print(f"    Payload construit ({len(payload)} champs) :")
    for k, v in payload.items():
        v_short = str(v) if len(str(v)) < 60 else str(v)[:60] + f"...({len(str(v))} chars)"
        print(f"      {k[:60]:60} = {v_short}")

    # Action de la form (cherche main_form spécifiquement, pas loginForm !)
    action_url = URL_FORMULAIRE  # par défaut
    form_principal = None
    for attrs, content in forms:
        name_m = re.search(r'name\s*=\s*["\']([^"\']+)["\']',
                            attrs, re.IGNORECASE)
        if name_m and name_m.group(1) == "main_form":
            form_principal = (attrs, content)
            break

    if form_principal is None and forms:
        # Fallback : prend le form qui contient la radio "choixAnonyme"
        for attrs, content in forms:
            if "choixAnonyme" in content:
                form_principal = (attrs, content)
                break

    if form_principal:
        action_m = re.search(r'action\s*=\s*["\']([^"\']+)["\']',
                              form_principal[0], re.IGNORECASE)
        if action_m:
            action_attr = action_m.group(1).replace("&amp;", "&")
            if action_attr.startswith("http"):
                action_url = action_attr
            elif action_attr.startswith("/"):
                action_url = "https://www.marches-publics.gouv.fr" + action_attr
            else:
                action_url = "https://www.marches-publics.gouv.fr/" + action_attr
    print(f"    Action POST : {action_url[:120]}")

    # Force l'ajout du bouton Valider (pas Annuler ni Se connecter)
    # Le bouton "Valider" est ctl0$CONTENU_PAGE$validateButton
    for b in submit_buttons:
        if b.get("value", "").lower() == "valider":
            payload[b["name"]] = b["value"]
            print(f"    Ajout bouton Valider : {b['name']} = {b['value']}")
            break

    try:
        r2 = session.post(
            action_url, data=payload, timeout=60, allow_redirects=True,
            headers={"Referer": URL_FORMULAIRE},
        )
        print(f"    HTTP {r2.status_code}")
        print(f"    URL après POST : {r2.url[:100]}")
        print(f"    Content-Type : {r2.headers.get('Content-Type', '?')}")
        print(f"    Content-Length : {len(r2.content)} octets")
        # Si le Content-Disposition est présent → c'est un téléchargement
        cd = r2.headers.get("Content-Disposition", "")
        if cd:
            print(f"    Content-Disposition : {cd}")
            print(f"    🎉 ON A UN FICHIER ! C'est probablement le zip DCE.")
            chemin_zip = DEBUG_DIR / "02_dce_download.zip"
            chemin_zip.write_bytes(r2.content)
            print(f"    Sauvé : {chemin_zip}")
            print()
            print("=" * 75)
            print(f"FIN — Tous les fichiers debug dans : {DEBUG_DIR}")
            print("=" * 75)
            return

        # Sinon, sauve la réponse et tente l'étape 3 (Prado postback)
        chemin_reponse = DEBUG_DIR / "02_reponse_post.html"
        chemin_reponse.write_text(r2.text, encoding="utf-8")
        print(f"    Réponse HTML sauvée : {chemin_reponse}")

        html2 = r2.text

        # ====== ÉTAPE 5 : POST n°2 avec PRADO_POSTBACK_TARGET ======
        print()
        print("[5] Tentative POST n°2 : Prado postback pour 'completeDownload'...")

        # Détecte le EventTarget à utiliser depuis le JS de la page
        event_target_m = re.search(
            r"'EventTarget':\s*\"([^\"]*completeDownload[^\"]*)\"",
            html2
        )
        if not event_target_m:
            print("    ⚠ Pas trouvé l'EventTarget 'completeDownload' dans la page.")
            print("    Inspection manuelle requise pour identifier le bouton.")
            return
        event_target = event_target_m.group(1)
        print(f"    EventTarget détecté : {event_target}")

        # Construit le payload pour le POST 2 :
        # - Tous les hidden de la nouvelle page (PRADO_PAGESTATE différent !)
        # - PRADO_POSTBACK_TARGET = EventTarget du bouton
        # - PRADO_POSTBACK_PARAMETER = "" (vide)
        payload2 = {}
        for m in re.finditer(r'<input([^>]+)>', html2, re.IGNORECASE):
            inp = m.group(1)
            type_m = re.search(r'type\s*=\s*["\']?([^"\'\s>]+)', inp, re.IGNORECASE)
            name_m = re.search(r'name\s*=\s*["\']?([^"\'\s>]+)', inp, re.IGNORECASE)
            value_m = re.search(r'value\s*=\s*["\']([^"\']*)["\']',
                                 inp, re.IGNORECASE)
            type_v = type_m.group(1) if type_m else "text"
            name_v = name_m.group(1) if name_m else ""
            value_v = value_m.group(1) if value_m else ""
            if not name_v or type_v == "submit":
                continue
            # Pour radio/checkbox : inclure seulement si checked
            if type_v in ("radio", "checkbox"):
                if "checked" in inp.lower():
                    payload2[name_v] = value_v or "on"
                continue
            payload2[name_v] = value_v

        # Ajoute les paramètres Prado postback
        payload2["PRADO_POSTBACK_TARGET"] = event_target
        payload2["PRADO_POSTBACK_PARAMETER"] = ""

        print(f"    Payload POST 2 ({len(payload2)} champs)")
        # Affiche les champs critiques
        for k in ["PRADO_POSTBACK_TARGET", "PRADO_POSTBACK_PARAMETER",
                  "_csrf_token", "PRADO_PAGESTATE"]:
            if k in payload2:
                v = payload2[k]
                v_short = v if len(str(v)) < 60 else str(v)[:60] + f"...({len(str(v))} chars)"
                print(f"      {k} = {v_short}")

        # POST n°2 sur la même URL
        print(f"    POST → {action_url[:80]}...")
        r3 = session.post(
            action_url, data=payload2, timeout=120, allow_redirects=True,
            headers={"Referer": r2.url},
            stream=True,  # important pour les gros fichiers binaires
        )
        print(f"    HTTP {r3.status_code}")
        print(f"    URL : {r3.url[:100]}")
        print(f"    Content-Type : {r3.headers.get('Content-Type', '?')}")

        cd2 = r3.headers.get("Content-Disposition", "")
        if cd2:
            print(f"    Content-Disposition : {cd2}")
            print(f"    🎉🎉🎉 ON A LE ZIP DCE !")
            chemin_zip = DEBUG_DIR / "03_dce_download.zip"
            with open(chemin_zip, "wb") as f:
                for chunk in r3.iter_content(chunk_size=65536):
                    f.write(chunk)
            taille = chemin_zip.stat().st_size
            print(f"    Sauvé : {chemin_zip} ({taille:,} octets)")
            # Vérifie que c'est un vrai zip
            if taille > 1000:
                with open(chemin_zip, "rb") as f:
                    magic = f.read(4)
                if magic[:2] == b"PK":
                    print(f"    ✅ Signature ZIP valide (PK)")
                else:
                    print(f"    ⚠ Signature inattendue : {magic}")
        else:
            ct = r3.headers.get("Content-Type", "")
            taille = len(r3.content)
            print(f"    Pas de Content-Disposition. Taille reçue : {taille} octets.")
            if "html" in ct:
                chemin_dbg = DEBUG_DIR / "03_reponse_post2.html"
                chemin_dbg.write_text(r3.text, encoding="utf-8")
                print(f"    Réponse HTML sauvée : {chemin_dbg}")
            elif "zip" in ct or "octet" in ct or taille > 100000:
                # Peut-être un zip sans Content-Disposition propre
                chemin_bin = DEBUG_DIR / "03_response.bin"
                with open(chemin_bin, "wb") as f:
                    f.write(r3.content)
                print(f"    Réponse binaire sauvée : {chemin_bin}")
                magic = r3.content[:4]
                print(f"    Magic bytes : {magic}")
                if magic[:2] == b"PK":
                    print(f"    ✅ C'est un ZIP ! Renommage en .zip")
                    chemin_bin.rename(DEBUG_DIR / "03_dce_download.zip")
    except Exception as e:
        print(f"    ERREUR : {e}")
        import traceback
        traceback.print_exc()
        return

    print()
    print("=" * 75)
    print(f"FIN — Tous les fichiers debug dans : {DEBUG_DIR}")
    print("=" * 75)
    print()
    print("Envoie à Claude :")
    print("  1. Cette sortie console complète (copier-coller)")
    print(f"  2. Le contenu de : {DEBUG_DIR / '02_reponse_post.html'}")
    print(f"     (ou {DEBUG_DIR / '02_dce_download.zip'} si on a eu le zip)")


def _trouver_label_proche(html: str, id_attr: str, name_attr: str) -> str | None:
    """Trouve un <label for=id> ou texte autour d'un input."""
    if id_attr:
        m = re.search(
            rf'<label[^>]*for\s*=\s*["\']?{re.escape(id_attr)}["\']?[^>]*>(.+?)</label>',
            html, re.DOTALL | re.IGNORECASE
        )
        if m:
            return re.sub(r'<[^>]+>', '', m.group(1)).strip()
    # Cherche du texte juste après l'input
    if id_attr:
        m = re.search(
            rf'id\s*=\s*["\']?{re.escape(id_attr)}["\']?[^>]*>(?:\s|<[^>]+>)*([^<]{{10,200}})',
            html, re.IGNORECASE
        )
        if m:
            return m.group(1).strip()
    return None


if __name__ == "__main__":
    main()
