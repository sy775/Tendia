"""
diagnostic_vide.py
------------------
Investigation des marchés dce_contenu == "vide" pour identifier des dettes
cachées : URL DCE présentes mais non scannées, plateformes Atexo non détectées,
URL valides mais qualifie_dce a échoué pour une autre raison.

Lecture seule. Lancement : python diagnostic_vide.py
"""
import io
import sys
import os
import json

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage


def main():
    marches = stockage.charger("marches") or {}
    vides = [(mid, m) for mid, m in marches.items()
             if m.get("dce_contenu") == "vide"]

    print(f"=== DIAGNOSTIC marchés 'vide' ===")
    print(f"Marchés vide : {len(vides)} / {len(marches)}")
    print()

    # Sous-catégoriser
    sans_url_dce = []           # pas d'url_dce du tout
    avec_url_dce = []           # url_dce présente mais résultat vide
    atexo_potentiel = []        # url contient signature Atexo : aurait dû être récupéré
    plateforme_connue_auth = [] # ex achatpublic, AWS-Achat
    autre_plateforme = []       # plateforme tierce non Atexo, non AWS

    AUTH_PLATEFORMES = ("www.marches-publics.info", "achatpublic.com",
                        "marches-securises.fr")

    for mid, m in vides:
        url = (m.get("url_dce") or "").strip()
        if not url:
            sans_url_dce.append((mid, m))
            continue
        avec_url_dce.append((mid, m))
        low = url.lower()
        # Signature Atexo ?
        if ("orgacronyme=" in low and "entreprise." in low):
            atexo_potentiel.append((mid, m, url))
        elif any(p in low for p in AUTH_PLATEFORMES):
            plateforme_connue_auth.append((mid, m, url))
        else:
            autre_plateforme.append((mid, m, url))

    print(f"  Sans url_dce du tout       : {len(sans_url_dce)}")
    print(f"  Avec url_dce               : {len(avec_url_dce)}")
    print(f"    dont signature Atexo     : {len(atexo_potentiel)}   ← DETTE CACHÉE")
    print(f"    dont plateforme auth     : {len(plateforme_connue_auth)}")
    print(f"    dont autre plateforme    : {len(autre_plateforme)}")
    print()

    # Échantillon "sans url_dce" : top 5
    if sans_url_dce:
        print("--- Marchés SANS url_dce (top 5) ---")
        print("  Probablement : marchés avec avis BOAMP/TED simple, pas de DCE.")
        for mid, m in sans_url_dce[:5]:
            titre = (m.get("titre") or "")[:70]
            acheteur = (m.get("acheteur_nom") or "")[:40]
            print(f"  {mid:<25} | {acheteur:<40} | {titre}")
        print()

    # Échantillon "Atexo potentiel" — la VRAIE dette
    if atexo_potentiel:
        print("--- Marchés AVEC SIGNATURE ATEXO mais classés vide ---")
        print("  Ces marchés devraient être récupérables via atexo_downloader.")
        for mid, m, url in atexo_potentiel[:15]:
            print(f"  {mid}")
            print(f"    URL : {url[:150]}")
            print(f"    contenu actuel : {m.get('dce_raison_contenu')}")
        print()

    # Échantillon plateforme auth
    if plateforme_connue_auth:
        # Compter par plateforme
        compteur = {}
        for mid, m, url in plateforme_connue_auth:
            for p in AUTH_PLATEFORMES:
                if p in url.lower():
                    compteur[p] = compteur.get(p, 0) + 1
                    break
        print("--- Marchés avec plateforme auth (déjà identifié pour Sprint Captcha) ---")
        for p, n in compteur.items():
            print(f"  {p:<40} : {n} marchés")
        print()

    # Échantillon autre plateforme
    if autre_plateforme:
        # Compter par host
        from urllib.parse import urlparse
        compteur_hosts = {}
        for mid, m, url in autre_plateforme:
            try:
                host = urlparse(url).netloc.lower()
                compteur_hosts[host] = compteur_hosts.get(host, 0) + 1
            except Exception:
                pass
        print("--- Marchés avec autre plateforme (top 10 hosts) ---")
        tries = sorted(compteur_hosts.items(), key=lambda x: x[1], reverse=True)
        for host, n in tries[:10]:
            print(f"  {host:<50} : {n} marchés")
        print()
        # Top 5 exemples avec URL et titre
        print("--- Exemples ---")
        for mid, m, url in autre_plateforme[:5]:
            titre = (m.get("titre") or "")[:60]
            print(f"  {mid} | {url[:120]}")
            print(f"    titre: {titre}")
        print()

    # Vérif : combien de marchés vide ont un dossier DCE physique non vide ?
    # (cas : DCE téléchargé mais qualifier_dce a échoué)
    dossier_dce_present = []
    for mid, m in vides:
        chemin = os.path.join("data", "dce", mid)
        if os.path.isdir(chemin):
            taille = 0
            nb = 0
            for racine, dirs, fichiers in os.walk(chemin):
                for f in fichiers:
                    try:
                        taille += os.path.getsize(os.path.join(racine, f))
                        nb += 1
                    except OSError:
                        pass
            if taille > 1024:
                dossier_dce_present.append((mid, taille, nb))

    if dossier_dce_present:
        print(f"--- Anomalies : marchés vide MAIS dossier DCE non vide ({len(dossier_dce_present)}) ---")
        print("  Possibles bugs qualifier_dce.")
        for mid, taille, nb in dossier_dce_present[:5]:
            print(f"  {mid} : {nb} fichiers, {taille:,} octets")
        print()

    print("=" * 60)
    print("SYNTHÈSE")
    print("=" * 60)
    if atexo_potentiel:
        print(f"⚠ DETTE CACHÉE : {len(atexo_potentiel)} marchés avec signature Atexo")
        print("  → Potentiellement récupérables. Relancer retelecharger sur ces marchés ?")
    if plateforme_connue_auth:
        print(f"   {sum(c[2] for c in [(None, None, len(plateforme_connue_auth))])}"
              f" marchés sur plateformes auth (Sprint Captcha à venir)")
    if dossier_dce_present:
        print(f"⚠ ANOMALIE : {len(dossier_dce_present)} dossiers DCE non vides mais "
              "classés vide.")
    if sans_url_dce:
        print(f"  {len(sans_url_dce)} marchés sans url_dce = perte structurelle "
              "(pas de DCE accessible).")

    print()
    print(f"Total vide : {len(vides)}")
    print(f"  - {len(sans_url_dce)} structurellement irrécupérables (pas d'URL)")
    print(f"  - {len(plateforme_connue_auth)} pour le Sprint Captcha")
    print(f"  - {len(atexo_potentiel)} potentiellement récupérables maintenant (Atexo)")
    print(f"  - {len(autre_plateforme)} autres plateformes à investiguer")


if __name__ == "__main__":
    main()
