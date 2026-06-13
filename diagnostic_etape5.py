"""
diagnostic_etape5.py
--------------------
Inspecte les réponses des étapes 5-7 du workflow AWS-Achat pour comprendre
pourquoi le POST cnxAnonyme retourne 200 au lieu de 302.

Lance : python diagnostic_etape5.py
"""
import io
import sys
import os
import re
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

import requests
import html as html_lib
import stockage
import aws_downloader as A


def main():
    marches = stockage.charger("marches")
    marche = marches.get("BOAMP-26-56599")
    if not marche:
        marche = next(m for m in marches.values()
                       if "marches-publics.info" in (m.get("url_dce") or ""))

    idm = A._extraire_idm_depuis_url(marche["url_dce"])
    print(f"Marché : {marche.get('id')}, IDM={idm}")

    session = requests.Session()
    session.headers.update({
        "User-Agent": A.USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9",
    })

    # Étape 1
    print("\n[1] GET choixDCE...")
    url1 = (f"{A.URL_BASE}/mpiaws/index.cfm"
            f"?fuseaction=dematEnt.choixDCE&IDM={idm}&XFAOK=dce.verifLotsDCE")
    r1 = session.get(url1, timeout=30)
    print(f"   Status : {r1.status_code}")
    print(f"   Cookies session apres etape 1 : {len(session.cookies)} ({[c.name for c in session.cookies]})")
    cfid, cftoken = A._extraire_cfid_cftoken_depuis_html(r1.text)
    ids = A._extraire_ids_depuis_html(r1.text)
    print(f"   CFID={cfid} CFTOKEN={cftoken[:16]}... IDS={ids}")

    # Étape 2
    print("\n[2] GET dce.avertissement...")
    url2 = (f"{A.URL_BASE}/mpiaws/index.cfm"
            f"?fuseaction=dce.avertissement&IDM={idm}&type=DCE"
            f"&XFAOK=dce.verifLotsDCE&IDS={ids}"
            f"&CFID={cfid}&CFTOKEN={cftoken}")
    r2 = session.get(url2, timeout=30)
    print(f"   Status : {r2.status_code}")
    print(f"   Cookies apres etape 2 : {len(session.cookies)}")
    str_nom, hash_val = A._extraire_str_nom_image_et_hashval(r2.text)
    print(f"   strNomImage={str_nom} hashVal={hash_val[:32]}...")

    # Étape 3
    print("\n[3] GET captcha image...")
    url_img = f"{A.URL_BASE}/captcha/Captcha_{str_nom}.png"
    r3 = session.get(url_img, timeout=30)
    print(f"   Image : {len(r3.content)} octets")
    print(f"   Cookies apres etape 3 : {len(session.cookies)}")

    # Étape 4 : 2captcha
    print("\n[4] 2captcha...")
    api_key = os.environ.get("TWOCAPTCHA_API_KEY")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(r3.content)
        tmp_path = tmp.name
    try:
        from twocaptcha import TwoCaptcha
        solver = TwoCaptcha(api_key)
        result = solver.normal(tmp_path)
        captcha_val = result["code"]
        print(f"   Resolu : '{captcha_val}'")
    finally:
        os.unlink(tmp_path)

    # Étape 5 : POST cnxAnonyme — INSPECTION DETAILLEE
    print("\n[5] POST cnxAnonyme (INSPECTION DETAILLEE)...")
    url5 = (f"{A.URL_BASE}/mpiaws/index.cfm"
            f"?fuseaction=dce.cnxAnonyme&IDM={idm}"
            f"&IDS={ids}&CFID={cfid}&CFTOKEN={cftoken}")
    payload5 = {
        "type": "DCE",
        "XFAOK": "dce.verifLotsDCE",
        "strNomImage": str_nom,
        "hashVal": hash_val,
        "captchaVal": captcha_val,
    }
    print(f"   Payload : {payload5}")
    # IMPORTANT : ne pas suivre les redirections pour voir le 302 brut
    r5 = session.post(url5, data=payload5, timeout=30,
                       headers={"Origin": A.URL_BASE, "Referer": url2,
                                "Content-Type": "application/x-www-form-urlencoded"},
                       allow_redirects=False)
    print(f"   Status (no redirect) : {r5.status_code}")
    print(f"   Headers reponse :")
    for k, v in r5.headers.items():
        print(f"     {k}: {v[:120]}")
    print(f"   Cookies apres etape 5 : {len(session.cookies)} ({[c.name for c in session.cookies]})")
    print(f"   Body taille : {len(r5.text)} chars")
    if len(r5.text) > 100:
        # Sauvegarde HTML
        with open("debug_etape5_body.html", "w", encoding="utf-8") as f:
            f.write(r5.text)
        print(f"   Body sauvegarde dans debug_etape5_body.html")
        # Chercher des indices d'erreur
        body_decode = html_lib.unescape(r5.text)
        for mot in ("capt", "erreur", "expir", "session", "Reconnexion",
                     "incorrect", "invalide"):
            if mot.lower() in body_decode.lower():
                idx = body_decode.lower().find(mot.lower())
                ctx = body_decode[max(0, idx-50):idx+200]
                print(f"   '{mot}' trouve : ...{ctx}...")
                break  # juste le 1er match suffit

    print("\n=== ANALYSE ===")
    if r5.status_code == 302:
        print("OK 302 reçu : workflow cnxAnonyme accepté")
        loc = r5.headers.get("Location", "")
        print(f"   Redirect vers : {loc}")
    elif r5.status_code == 200:
        print("⚠ 200 reçu au lieu de 302 :")
        print("   - Soit captcha refusé (page d'erreur affichée)")
        print("   - Soit session ColdFusion expirée")
        print("   - Soit autre erreur métier")
        print("   Voir debug_etape5_body.html pour diagnostic visuel")


if __name__ == "__main__":
    main()
