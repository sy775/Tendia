"""
diagnostic_emarches.py
----------------------
Diagnostic du workflow de téléchargement DCE sur e-marchespublics (Dematis).
Pour 2-3 marchés e-marchespublics de la base, GET la page DCE et analyse le HTML
pour déterminer le type de workflow (Cas A formulaire HTTP / Cas B AJAX / Cas C
protégé). NE TÉLÉCHARGE RIEN. Nécessite réseau — à lancer par Younes.

Usage : python diagnostic_emarches.py
"""
import io
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests
import stockage
import tendia_telecharger_dce as T


def analyser(html: str) -> dict:
    """Heuristiques pour deviner le workflow Dematis."""
    low = html.lower()
    forms = re.findall(r'<form[^>]*>', html, re.IGNORECASE)
    inputs = re.findall(r'<input[^>]+name=["\']([^"\']+)["\']', html, re.IGNORECASE)
    # endpoints AJAX (fetch/XHR/ajax url)
    ajax = re.findall(r'(?:url|action)\s*[:=]\s*["\']([^"\']+(?:telechar|download|dce|document)[^"\']*)["\']',
                      low)
    boutons_dl = re.findall(r'(?:id|class)=["\']([^"\']*(?:telechar|download)[^"\']*)["\']', low)
    mots = [m for m in ("anonyme", "télécharger", "telecharger", "consultation",
                        "accepter", "conditions", "captcha", "recaptcha") if m in low]
    return {
        "nb_forms": len(forms),
        "nb_inputs": len(inputs),
        "inputs_noms": inputs[:12],
        "ajax_endpoints": list(dict.fromkeys(ajax))[:6],
        "boutons_dl": list(dict.fromkeys(boutons_dl))[:6],
        "mots_cles": mots,
        "captcha_present": ("captcha" in low or "recaptcha" in low),
    }


def verdict(a: dict) -> str:
    if a["captcha_present"]:
        return "Cas C — captcha détecté : auth_requise provisoire (Sprint dédié)"
    if a["nb_forms"] >= 1 and a["nb_inputs"] >= 2 and not a["ajax_endpoints"]:
        return "Cas A probable — formulaire HTTP classique : écrire dematis_downloader (modèle atexo)"
    if a["ajax_endpoints"]:
        return "Cas B probable — endpoint(s) AJAX : mimer l'XHR en requests direct"
    return "Indéterminé — inspecter le HTML manuellement (boutons JS ?)"


def main():
    marches = stockage.charger("marches") or {}
    cibles = [m for m in marches.values()
              if "e-marchespublics.com" in (m.get("url_dce") or "").lower()
              and m.get("dce_contenu") == "incomplet"][:3]
    if not cibles:
        cibles = [m for m in marches.values()
                  if "e-marchespublics.com" in (m.get("url_dce") or "").lower()][:3]

    session = requests.Session()
    session.headers.update({"User-Agent": T.USER_AGENT,
                            "Accept-Language": "fr-FR,fr;q=0.9"})

    print("=== DIAGNOSTIC e-marchespublics (Dematis) ===")
    print(f"Échantillon : {len(cibles)} marché(s)\n")
    for m in cibles:
        url = m.get("url_dce") or ""
        print(f"Marché {m.get('id')}")
        print(f"  URL : {url[:110]}")
        try:
            r = session.get(url, timeout=30)
            print(f"  HTTP {r.status_code} | HTML {len(r.text)} octets")
            a = analyser(r.text)
            print(f"  forms={a['nb_forms']} inputs={a['nb_inputs']} mots={a['mots_cles']}")
            print(f"  inputs: {a['inputs_noms']}")
            if a["ajax_endpoints"]:
                print(f"  AJAX: {a['ajax_endpoints']}")
            if a["boutons_dl"]:
                print(f"  boutons DL: {a['boutons_dl']}")
            print(f"  ⇒ {verdict(a)}")
        except Exception as e:
            print(f"  ERREUR : {type(e).__name__}: {e}")
        print()

    print("Décision : si Cas A/B -> écrire dematis_downloader.py (contrat identique")
    print("à atexo_downloader) + ParseurEMarchesPublics renvoyant ZIP_GLOBAL_DEMATIS.")
    print("Si Cas C -> ajouter 'e-marchespublics.com' à PLATEFORMES_AUTH_REQUISES.")


if __name__ == "__main__":
    main()
