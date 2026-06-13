"""
diagnostic_etape2_chrome.py
---------------------------
Diagnostic léger SANS captcha (gratuit) : refait les étapes 1 et 2 avec
des headers Chrome 149 COMPLETS pour imiter au maximum un vrai navigateur.

Comparer avec diagnostic_etape2_simple.py (qui a juste UA + Accept-Language)
pour savoir si :
- Si "simple" KO mais "chrome" OK : c'est les headers qui te faisaient ban
- Si les 2 KO : c'est le fingerprint TLS de Python (besoin de curl_cffi)
- Si les 2 OK : ton IP est débannie / pas de ban

Lance : python diagnostic_etape2_chrome.py
"""
import io
import sys
import re

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests
import html as html_lib

IDM = "1791723"


def main():
    session = requests.Session()
    # Headers Chrome 149 sur Windows 10/11 — copiés depuis DevTools d'un vrai
    # navigateur (ordre important : certains serveurs vérifient l'ordre)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/149.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                   "image/avif,image/webp,image/apng,*/*;q=0.8,"
                   "application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
        "DNT": "1",
        "Sec-Ch-Ua": '"Google Chrome";v="149", "Chromium";v="149", "Not?A_Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    })

    # Etape 1 : GET choixDCE
    print("=" * 60)
    print("Etape 1 : GET dematEnt.choixDCE (avec headers Chrome complets)")
    print("=" * 60)
    url1 = (f"https://www.marches-publics.info/mpiaws/index.cfm"
            f"?fuseaction=dematEnt.choixDCE&IDM={IDM}&XFAOK=dce.verifLotsDCE")
    r1 = session.get(url1, timeout=30)
    print(f"Status : {r1.status_code}")
    print(f"Taille HTML : {len(r1.text)}")

    # Detecter le pattern ban (page HTML5/Bootstrap)
    if "bootstrap-iso.css" in r1.text or "jquery-3.6.3" in r1.text:
        print()
        print("⚠ BAN DETECTE : page HTML5/Bootstrap retournée")
        print("Premier 500 chars :")
        print(r1.text[:500])
        sys.exit(1)

    html1_decoded = html_lib.unescape(r1.text)
    cfid_m = re.search(r"[?&]CFID=(\d+)", html1_decoded, re.IGNORECASE)
    cftoken_m = re.search(r"[?&]CFTOKEN=([0-9a-fA-F\-]+)", html1_decoded, re.IGNORECASE)
    if not cfid_m or not cftoken_m:
        print("ERREUR : CFID/CFTOKEN introuvables")
        print(r1.text[:500])
        sys.exit(1)
    cfid = cfid_m.group(1)
    cftoken = cftoken_m.group(1)
    print(f"CFID = {cfid}")
    print(f"CFTOKEN = {cftoken[:32]}...")

    # Mise a jour Sec-Fetch-Site pour la suite (same-origin maintenant)
    session.headers["Sec-Fetch-Site"] = "same-origin"
    session.headers["Referer"] = url1

    # Etape 2 : GET dce.avertissement
    print()
    print("=" * 60)
    print("Etape 2 : GET dce.avertissement")
    print("=" * 60)
    url2 = (f"https://www.marches-publics.info/mpiaws/index.cfm"
            f"?fuseaction=dce.avertissement&IDM={IDM}&type=DCE"
            f"&XFAOK=dce.verifLotsDCE&IDS=25"
            f"&CFID={cfid}&CFTOKEN={cftoken}")
    r2 = session.get(url2, timeout=30)
    print(f"Status : {r2.status_code}")
    print(f"Taille HTML : {len(r2.text)}")

    # Analyse
    html2 = r2.text
    print()
    print("=" * 60)
    print("ANALYSE")
    print("=" * 60)
    print(f"  'strNomImage' present : {'strNomImage' in html2}")
    print(f"  'hashVal'     present : {'hashVal' in html2}")
    print(f"  'Captcha_'    present : {'Captcha_' in html2}")
    print(f"  'RETRAIT'     present : {'RETRAIT' in html2}")
    print(f"  'ANONYME'     present : {'ANONYME' in html2}")
    print(f"  'bootstrap'   present : {'bootstrap' in html2.lower()}")

    print()
    print("=" * 60)
    print("VERDICT")
    print("=" * 60)
    if "strNomImage" in html2 and "hashVal" in html2:
        print("✅ Page captcha ColdFusion normale recue.")
        print("   Si diagnostic_etape2_simple.py donnait KO mais celui-ci OK :")
        print("   --> c'est un probleme de headers (curl_cffi non necessaire)")
    elif "bootstrap" in html2.lower() or "bootstrap-iso" in html2:
        print("⚠ BAN : page HTML5/Bootstrap retournee meme avec headers complets")
        print("   --> probleme de fingerprint TLS, besoin de curl_cffi")
    else:
        print("? Reponse inattendue, voir HTML pour analyse")

    # Sauvegarde
    with open("debug_etape2_chrome.html", "w", encoding="utf-8") as f:
        f.write(html2)
    print()
    print("HTML complet sauvegarde dans debug_etape2_chrome.html")


if __name__ == "__main__":
    main()
