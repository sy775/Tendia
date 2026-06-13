"""
diagnostic_actdce2.py
---------------------
Reproduit le workflow AWS-Achat jusqu'à la page actDCE2 et inspecte son
contenu HTML pour comprendre pourquoi _extraire_url_cdn_depuis_actdce2
ne trouve aucune URL.

Lance : python diagnostic_actdce2.py
"""
import io
import sys
import re

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import aws_downloader as A
import html as html_lib


def main():
    marches = stockage.charger("marches")
    # Cible : BOAMP-26-56599 (celui qui a échoué)
    marche = marches.get("BOAMP-26-56599")
    if not marche:
        # Fallback : 1er marché AWS auth_requise
        marche = next(
            (m for m in marches.values()
             if "marches-publics.info" in (m.get("url_dce") or "")
             and m.get("dce_contenu") == "auth_requise"),
            None
        )
    if not marche:
        print("Aucun marché AWS trouvé")
        sys.exit(1)

    url_dce = marche["url_dce"]
    idm = A._extraire_idm_depuis_url(url_dce)
    print(f"Marché : {marche.get('id')}, IDM={idm}")
    print(f"URL : {url_dce}")
    print()

    # Importer le workflow interne pour avoir une session
    import requests
    session = requests.Session()
    session.headers.update({
        "User-Agent": A.USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9",
    })

    # Étape 1 : GET choixDCE
    print("[1/7] GET choixDCE...")
    url1 = (f"{A.URL_BASE}/mpiaws/index.cfm"
            f"?fuseaction=dematEnt.choixDCE&IDM={idm}"
            f"&XFAOK=dce.verifLotsDCE")
    r1 = session.get(url1, timeout=30)
    cfid, cftoken = A._extraire_cfid_cftoken_depuis_html(r1.text)
    ids = A._extraire_ids_depuis_html(r1.text)
    print(f"   CFID={cfid}, CFTOKEN={cftoken[:16]}..., IDS={ids}")

    # Étape 2 : GET dce.avertissement
    print("[2/7] GET dce.avertissement (captcha)...")
    url2 = (f"{A.URL_BASE}/mpiaws/index.cfm"
            f"?fuseaction=dce.avertissement&IDM={idm}"
            f"&type=DCE&XFAOK=dce.verifLotsDCE"
            f"&IDS={ids}&CFID={cfid}&CFTOKEN={cftoken}")
    r2 = session.get(url2, timeout=30)
    str_nom, hash_val = A._extraire_str_nom_image_et_hashval(r2.text)
    print(f"   strNomImage={str_nom}, hashVal={hash_val[:32]}...")

    # Étape 3 : GET captcha image
    print("[3/7] GET image captcha...")
    url_img = f"{A.URL_BASE}/captcha/Captcha_{str_nom}.png"
    r3 = session.get(url_img, timeout=30)
    print(f"   Image : {len(r3.content)} octets")

    # Étape 4 : 2captcha
    print("[4/7] 2captcha...")
    import os
    api_key = os.environ.get("TWOCAPTCHA_API_KEY")
    if not api_key:
        from dotenv import load_dotenv
        load_dotenv()
        api_key = os.environ.get("TWOCAPTCHA_API_KEY")
    if not api_key:
        print("ERREUR : TWOCAPTCHA_API_KEY absent")
        sys.exit(1)

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(r3.content)
        tmp_path = tmp.name
    try:
        from twocaptcha import TwoCaptcha
        solver = TwoCaptcha(api_key)
        result = solver.normal(tmp_path)
        captcha_val = result["code"]
        print(f"   Résolu : '{captcha_val}'")
    finally:
        os.unlink(tmp_path)

    # Étape 5 : POST cnxAnonyme
    print("[5/7] POST cnxAnonyme...")
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
    r5 = session.post(url5, data=payload5, timeout=30,
                       headers={"Origin": A.URL_BASE, "Referer": url2})
    print(f"   Status : {r5.status_code}")

    # Étape 6 : GET verifLotsDCE
    print("[6/7] GET verifLotsDCE...")
    url6 = (f"{A.URL_BASE}/mpiaws/index.cfm"
            f"?fuseaction=dce.verifLotsDCE&IDM={idm}"
            f"&IDS={ids}&CFID={cfid}&CFTOKEN={cftoken}")
    r6 = session.get(url6, timeout=30)
    lots = A._extraire_lots_depuis_verif_lots_dce(r6.text)
    print(f"   Lots détectés : {lots}")

    # Étape 7 : POST actDCE2
    print("[7/7] POST actDCE2...")
    url7 = (f"{A.URL_BASE}/mpiaws/index.cfm"
            f"?fuseaction=dce.actDCE2&CFID={cfid}&CFTOKEN={cftoken}")
    payload7 = {"IDM": idm, "Soumission": 0, "selectAll": ""}
    if lots:
        # Construire la liste lots=N&lots=M en multi-value
        from requests.models import PreparedRequest
        payload7_str = "&".join([f"{k}={v}" for k, v in payload7.items()])
        for lot in lots:
            payload7_str += f"&lots={lot}"
        r7 = session.post(url7, data=payload7_str, timeout=30,
                           headers={"Origin": A.URL_BASE, "Referer": url6,
                                    "Content-Type": "application/x-www-form-urlencoded"})
    else:
        r7 = session.post(url7, data=payload7, timeout=30,
                           headers={"Origin": A.URL_BASE, "Referer": url6})
    print(f"   Status : {r7.status_code}, taille : {len(r7.text)} chars")
    print()

    # === INSPECTION HTML actDCE2 ===
    html = r7.text
    print("=" * 70)
    print("INSPECTION HTML actDCE2")
    print("=" * 70)
    print(f"Taille totale : {len(html)} chars")
    print()

    # Décoder le HTML
    html_decode = html_lib.unescape(html)

    # 1. URL downloads.awsolutions.fr présentes ?
    urls_cdn = re.findall(r'https?://downloads\.awsolutions\.fr/[^\s"\'<>]+', html_decode)
    print(f"URLs downloads.awsolutions.fr : {len(urls_cdn)}")
    for u in urls_cdn[:3]:
        print(f"  {u[:120]}...")
    print()

    # 2. Liens "Télécharger" présents ?
    a_tags = re.findall(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>', html)
    print(f"Total tags <a href> : {len(a_tags)}")

    # 3. Mots-clés DCE / RC / CCAP / CCTP
    for mot in ("DCE", "CCAP", "CCTP", "downloads", "Télécharger", "Telecharger",
                "dossier", "consultation", "annulé", "clos"):
        n = html.lower().count(mot.lower())
        if n > 0:
            print(f"  '{mot}' : {n} occurrences")
    print()

    # 4. Erreur affichée ?
    for marqueur in ("erreur", "error", "session expirée", "expirée", "captcha"):
        if marqueur.lower() in html.lower():
            # Afficher le contexte
            idx = html.lower().find(marqueur.lower())
            print(f"  '{marqueur}' trouvé à idx {idx} :")
            print(f"    {html[max(0,idx-50):idx+150]}")
    print()

    # 5. Premier 1500 chars du HTML
    print("=== HTML brut (1500 premiers chars) ===")
    print(html[:1500])
    print()
    print("=== HTML brut (chars 1500-3000) ===")
    print(html[1500:3000])

    # 6. Sauvegarder le HTML complet pour inspection
    with open("debug_actdce2.html", "w", encoding="utf-8") as f:
        f.write(html)
    print()
    print("HTML complet sauvegardé dans : debug_actdce2.html")


if __name__ == "__main__":
    main()
