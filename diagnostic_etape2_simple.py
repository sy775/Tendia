"""
diagnostic_etape2_simple.py
---------------------------
Diagnostic lÃ©ger SANS captcha (gratuit) : refait juste les Ã©tapes 1 et 2
pour vÃ©rifier ce que retourne la page dce.avertissement.

3 cas possibles :
  A. strNomImage et hashVal prÃ©sents -> notre regex foire (improbable)
  B. Reconnexion prÃ©sent -> cooldown AWS (attendre 10-15 min)
  C. Ni l'un ni l'autre -> structure HTML diffÃ©rente, Ã  analyser

Lance : python diagnostic_etape2_simple.py
"""
import io
import sys
import re

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests
import html as html_lib

IDM = "1832389"


def main():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/149.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9",
    })

    # Etape 1 : GET choixDCE pour rÃ©cupÃ©rer CFID/CFTOKEN
    print("=" * 60)
    print("Etape 1 : GET dematEnt.choixDCE")
    print("=" * 60)
    url1 = (f"https://www.marches-publics.info/mpiaws/index.cfm"
            f"?fuseaction=dematEnt.choixDCE&IDM={IDM}&XFAOK=dce.verifLotsDCE")
    r1 = session.get(url1, timeout=30)
    print(f"Status : {r1.status_code}")
    print(f"Taille HTML : {len(r1.text)}")

    # DÃ©coder pour rÃ©cupÃ©rer CFID/CFTOKEN
    html1_decoded = html_lib.unescape(r1.text)
    cfid_m = re.search(r"[?&]CFID=(\d+)", html1_decoded, re.IGNORECASE)
    cftoken_m = re.search(r"[?&]CFTOKEN=([0-9a-fA-F\-]+)", html1_decoded, re.IGNORECASE)
    if not cfid_m or not cftoken_m:
        print("ERREUR : CFID/CFTOKEN introuvables sur la page 1")
        print("Premiers 500 chars du HTML :")
        print(r1.text[:500])
        sys.exit(1)
    cfid = cfid_m.group(1)
    cftoken = cftoken_m.group(1)
    print(f"CFID = {cfid}")
    print(f"CFTOKEN = {cftoken[:32]}...")
    print()

    # Etape 2 : GET dce.avertissement
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
    print()

    # Analyse du contenu
    html2 = r2.text
    html2_decoded = html_lib.unescape(html2)
    print("=" * 60)
    print("ANALYSE")
    print("=" * 60)
    print(f"  'strNomImage' present : {('strNomImage' in html2) or ('strNomImage' in html2_decoded)}")
    print(f"  'hashVal'     present : {('hashVal' in html2) or ('hashVal' in html2_decoded)}")
    print(f"  'Captcha_'    present : {('Captcha_' in html2)}")
    print(f"  'captchaVal'  present : {('captchaVal' in html2)}")
    print(f"  'Reconnexion' present : {('Reconnexion' in html2)}")
    print(f"  'session'     present : {('session' in html2.lower())}")
    print(f"  'inactive'    present : {('inactive' in html2.lower())}")
    print(f"  'expir'       present : {('expir' in html2.lower())}")
    print(f"  'erreur'      present : {('erreur' in html2.lower())}")
    print(f"  'anomalie'    present : {('anomalie' in html2.lower())}")
    print(f"  'RETRAIT'     present : {('RETRAIT' in html2)}")
    print(f"  'ANONYME'     present : {('ANONYME' in html2)}")
    print()

    # Sauvegarde le HTML pour inspection
    with open("debug_etape2.html", "w", encoding="utf-8") as f:
        f.write(html2)
    print(f"HTML complet sauvegarde dans debug_etape2.html")
    print()

    # Verdict
    print("=" * 60)
    print("VERDICT")
    print("=" * 60)
    has_strnom = "strNomImage" in html2 or "strNomImage" in html2_decoded
    has_hashval = "hashVal" in html2 or "hashVal" in html2_decoded
    has_reconnexion = "Reconnexion" in html2
    has_retrait_anonyme = "ANONYME" in html2 or "RETRAIT" in html2

    if has_strnom and has_hashval:
        print("Cas A : strNomImage et hashVal presents")
        print("       => Notre regex foire, bug dans aws_downloader.py")
    elif has_reconnexion:
        print("Cas B : Reconnexion necessaire detectee")
        print("       => Cooldown AWS, attendre 10-15 min")
    elif not has_retrait_anonyme:
        print("Cas C : ni strNomImage ni Reconnexion ni RETRAIT/ANONYME")
        print("       => Structure HTML differente, ouvre debug_etape2.html")
        print("          pour voir ce qu'AWS retourne maintenant")
    else:
        print("Cas D : RETRAIT/ANONYME present mais pas strNomImage/hashVal")
        print("       => Variant captcha sans hashVal ? Ouvre debug_etape2.html")

    # Afficher les 1500 premiers chars du HTML 2 pour contexte
    print()
    print("=== 1500 premiers chars du HTML etape 2 ===")
    print(html2[:1500])


if __name__ == "__main__":
    main()
