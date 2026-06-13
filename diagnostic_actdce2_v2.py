"""
diagnostic_actdce2_v2.py
------------------------
Refait le workflow complet en réutilisant les helpers AWS-Achat (avec le fix
CFID régénéré). Inspecte le HTML de la page actDCE2 réelle pour comprendre
pourquoi le parsing des URL CDN échoue.

Lance : python diagnostic_actdce2_v2.py
"""
import io
import os
import re
import sys
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
    url1 = A._construire_url("dematEnt.choixDCE", IDM=idm, XFAOK="dce.verifLotsDCE")
    r1 = session.get(url1, timeout=30)
    cfid, cftoken = A._extraire_cfid_cftoken_depuis_html(r1.text)
    ids = A._extraire_ids_depuis_html(r1.text)
    print(f"[1] CFID={cfid}")

    # Étape 2
    url2 = A._construire_url("dce.avertissement", IDM=idm, type="DCE",
                              XFAOK="dce.verifLotsDCE", IDS=ids,
                              CFID=cfid, CFTOKEN=cftoken)
    r2 = session.get(url2, timeout=30)
    str_nom, hash_val = A._extraire_str_nom_image_et_hashval(r2.text)
    print(f"[2] strNomImage={str_nom}")

    # Étape 3
    url_img = f"{A.URL_BASE}/captcha/Captcha_{str_nom}.png"
    r3 = session.get(url_img, timeout=30)

    # Étape 4
    api_key = os.environ.get("TWOCAPTCHA_API_KEY")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(r3.content)
        tmp_path = tmp.name
    try:
        from twocaptcha import TwoCaptcha
        solver = TwoCaptcha(api_key)
        result = solver.normal(tmp_path)
        captcha_val = result["code"]
        print(f"[4] Captcha : '{captcha_val}'")
    finally:
        os.unlink(tmp_path)

    # Étape 5 (allow_redirects=False pour capter le 302 et le nouveau CFID)
    url5 = A._construire_url("dce.cnxAnonyme", IDM=idm, IDS=ids,
                              CFID=cfid, CFTOKEN=cftoken)
    payload5 = {
        "type": "DCE",
        "XFAOK": "dce.verifLotsDCE",
        "strNomImage": str_nom,
        "hashVal": hash_val,
        "captchaVal": captcha_val,
    }
    r5 = session.post(url5, data=payload5, timeout=30,
                       headers={"Origin": A.URL_BASE, "Referer": url2,
                                "Content-Type": "application/x-www-form-urlencoded"},
                       allow_redirects=False)
    print(f"[5] Status : {r5.status_code}")
    if r5.status_code not in (301, 302, 303, 307):
        print(f"   ECHEC : pas de 302, captcha probablement refusé")
        print(f"   Body : {r5.text[:300]}")
        return

    # PATCH cfid_refresh : récupérer les nouveaux CFID/CFTOKEN du Location
    location = r5.headers.get("Location", "")
    location_decode = html_lib.unescape(location)
    m_cfid = re.search(r"[?&]CFID=(\d+)", location_decode, re.IGNORECASE)
    m_cftoken = re.search(r"[?&]CFTOKEN=([0-9a-fA-F\-]+)",
                           location_decode, re.IGNORECASE)
    if m_cfid:
        cfid = m_cfid.group(1)
    if m_cftoken:
        cftoken = m_cftoken.group(1)
    print(f"[5b] CFID régénéré : {cfid}")

    # Étape 6 : GET verifLotsDCE avec les NOUVEAUX tokens
    from urllib.parse import urljoin
    url6 = urljoin(A.URL_BASE + A.URL_PATH if hasattr(A, 'URL_PATH') else A.URL_BASE + '/mpiaws/index.cfm',
                    location_decode)
    r6 = session.get(url6, timeout=30)
    print(f"[6] Status : {r6.status_code}, taille : {len(r6.text)}")
    lots = A._extraire_lots_depuis_verif_lots_dce(r6.text)
    print(f"   Lots détectés : {lots or '(mono-lot)'}")
    # Sauvegarde HTML étape 6
    with open("debug_verifLotsDCE.html", "w", encoding="utf-8") as f:
        f.write(r6.text)
    print(f"   Sauvegarde dans debug_verifLotsDCE.html")

    # Étape 7 : POST actDCE2 avec les NOUVEAUX tokens
    url7 = A._construire_url("dce.actDCE2", CFID=cfid, CFTOKEN=cftoken)
    champs = [("IDM", idm), ("Soumission", 0), ("selectAll", "")]
    for lot in lots:
        champs.append(("lots", lot))
    print(f"[7] POST avec champs : {champs}")
    r7 = session.post(url7, data=champs, timeout=30, allow_redirects=False,
                       headers={"Origin": A.URL_BASE, "Referer": url6,
                                "Content-Type": "application/x-www-form-urlencoded"})
    print(f"   Status : {r7.status_code}")
    print(f"   Headers : {dict(r7.headers)}")

    # Sauvegarder le HTML étape 7
    with open("debug_actdce2_v2.html", "w", encoding="utf-8") as f:
        f.write(r7.text)
    print(f"   Taille body : {len(r7.text)} chars")
    print(f"   Sauvegarde dans debug_actdce2_v2.html")
    print()

    # === INSPECTION ===
    if r7.status_code in (301, 302, 303, 307):
        print(f"⚠ 302 inattendu, Location : {r7.headers.get('Location')}")
        return

    print("=" * 70)
    print("INSPECTION HTML actDCE2 (etape 7)")
    print("=" * 70)
    html_brut = r7.text
    html_decode = html_lib.unescape(html_brut)

    print(f"Taille : {len(html_brut)} chars")

    # URLs CDN ?
    urls_cdn = re.findall(r'https?://downloads\.awsolutions\.fr/[^\s"\'<>]+', html_decode)
    print(f"URLs downloads.awsolutions.fr : {len(urls_cdn)}")
    for u in urls_cdn[:3]:
        print(f"  {u[:150]}...")

    # Tous les liens
    a_tags = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>', html_brut)
    print(f"Total <a href> : {len(a_tags)}")
    for href in a_tags[:10]:
        print(f"  {href[:150]}")

    # Mots-clés diagnostic
    print()
    print("Mots-clés présents :")
    for mot in ("DCE", "Télécharger", "Telecharger", "downloads", "TDoc",
                 "dossier", "fichier", "lot", "ZIP", "Reconnexion",
                 "expir", "session", "erreur", "AAPC", "RC", "CCAP", "CCTP"):
        n = html_brut.lower().count(mot.lower())
        if n > 0:
            print(f"  '{mot}' : {n}")

    print()
    print("=== 2500 premiers chars du HTML actDCE2 ===")
    print(html_brut[:2500])


if __name__ == "__main__":
    main()
