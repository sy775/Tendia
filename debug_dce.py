"""
debug_dce.py
------------
Script de diagnostic pour comprendre où trouver les URLs DCE.

Trois opérations :

1. Liste les champs valides de l'API TED v3 (en provoquant une erreur 400
   avec un champ inconnu, ce qui force TED à lister tous les champs supportés)

2. Pour chaque marché actif en base :
   - BOAMP : dump le record complet de l'API Opendatasoft
   - TED   : dump le notice complet avec tous les champs supportés

3. Tente une recherche PLACE par référence pour voir si on peut récupérer
   l'URL spécifique de consultation.

Output : fichiers JSON dans data/debug\

Usage :
    python debug_dce.py
"""

import json
import os
import sys
from datetime import date

import requests

import stockage


REPERTOIRE_DEBUG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data", "debug"
)
COLLECTION = "marches"


def _est_actif(marche: dict) -> bool:
    date_lim = marche.get("date_limite_depot")
    today = date.today().isoformat()
    if date_lim and len(date_lim) >= 10:
        return date_lim[:10] >= today
    date_pub = marche.get("date_publication")
    if date_pub and len(date_pub) >= 10:
        try:
            d = date.fromisoformat(date_pub[:10])
            return (date.today() - d).days <= 60
        except ValueError:
            pass
    return False


# ---------------------------------------------------------------------------
# 1. Lister tous les champs TED valides
# ---------------------------------------------------------------------------

def lister_champs_ted_valides():
    """
    Provoque volontairement une erreur 400 en demandant un champ invalide.
    TED renvoie en réponse la liste complète des champs supportés.
    """
    print("=" * 78)
    print("  ÉTAPE 1 — Lister les champs TED v3 valides")
    print("=" * 78)
    body = {
        "query": "publication-number=*",
        "fields": ["__diagnostic_invalid_field__"],
        "limit": 1,
        "scope": "ALL",
        "checkQuerySyntax": False,
        "paginationMode": "PAGE_NUMBER",
    }
    try:
        r = requests.post(
            "https://api.ted.europa.eu/v3/notices/search",
            json=body, timeout=30,
            headers={"Content-Type": "application/json",
                     "Accept": "application/json"}
        )
        print(f"  HTTP {r.status_code}")
        try:
            data = r.json()
        except Exception:
            data = {"raw_text": r.text[:5000]}
        chemin = os.path.join(REPERTOIRE_DEBUG, "ted_fields_diagnostic.json")
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  Réponse sauvée : {chemin}")
        # Extrait la liste des champs si présente dans le message
        message = (data.get("message") or "") if isinstance(data, dict) else ""
        if "supported values are:" in message:
            apres = message.split("supported values are:", 1)[1]
            # nettoie en cherchant un point final
            fields_str = apres.split(")", 1)[0]
            champs = [c.strip() for c in fields_str.split(",")]
            champs = [c for c in champs if c and not c.startswith("(")][:200]
            print(f"  {len(champs)} champs TED extraits :")
            for ch in champs[:30]:
                print(f"    {ch}")
            if len(champs) > 30:
                print(f"    ... ({len(champs) - 30} autres)")
            return champs
        else:
            print(f"  ⚠ Pas pu extraire la liste depuis le message.")
            print(f"  Contenu réponse (extrait) :")
            print(f"  {str(data)[:1000]}")
            return None
    except Exception as e:
        print(f"  ❌ Erreur : {e}")
        return None


# ---------------------------------------------------------------------------
# 2. Dump record BOAMP pour un marché
# ---------------------------------------------------------------------------

def dump_record_boamp(idweb: str) -> dict:
    url = ("https://boamp-datadila.opendatasoft.com/api/explore/v2.1/"
           "catalog/datasets/boamp/records")
    params = {"where": f'idweb="{idweb}"', "limit": 1}
    try:
        r = requests.get(url, params=params, timeout=30)
        if r.status_code == 200:
            data = r.json()
            results = data.get("results") or []
            if results:
                return results[0]
            return {"_diagnostic": "no results"}
        return {"_diagnostic": f"HTTP {r.status_code}",
                "_body": r.text[:2000]}
    except Exception as e:
        return {"_diagnostic": f"erreur: {e}"}


# ---------------------------------------------------------------------------
# 3. Dump notice TED avec champs valides
# ---------------------------------------------------------------------------

def dump_notice_ted(publication_number: str, champs_valides: list) -> dict:
    if not champs_valides:
        # fallback minimal
        champs_valides = ["publication-number", "notice-title", "links",
                           "buyer-name"]
    # Limite la taille de la requête (max 100 champs)
    champs_a_demander = champs_valides[:100]
    body = {
        "query": f"publication-number={publication_number}",
        "fields": champs_a_demander,
        "limit": 1,
        "scope": "ALL",
        "checkQuerySyntax": False,
        "paginationMode": "PAGE_NUMBER",
    }
    try:
        r = requests.post(
            "https://api.ted.europa.eu/v3/notices/search",
            json=body, timeout=30,
            headers={"Content-Type": "application/json",
                     "Accept": "application/json"}
        )
        if r.status_code == 200:
            data = r.json()
            notices = data.get("notices") or data.get("results") or []
            if notices:
                return notices[0]
            return {"_diagnostic": "no notices",
                    "_response_keys": list(data.keys())}
        # En cas d'erreur 400 sur trop de champs, retry avec moins
        if r.status_code == 400 and len(champs_a_demander) > 30:
            body["fields"] = champs_a_demander[:30]
            r = requests.post(
                "https://api.ted.europa.eu/v3/notices/search",
                json=body, timeout=30,
                headers={"Content-Type": "application/json",
                         "Accept": "application/json"}
            )
            if r.status_code == 200:
                data = r.json()
                notices = data.get("notices") or data.get("results") or []
                if notices:
                    return notices[0]
        return {"_diagnostic": f"HTTP {r.status_code}",
                "_body": r.text[:2000]}
    except Exception as e:
        return {"_diagnostic": f"erreur: {e}"}


# ---------------------------------------------------------------------------
# 4. Test PLACE — recherche par référence
# ---------------------------------------------------------------------------

def tester_place_search(reference: str) -> dict:
    """Test différentes URLs PLACE pour voir laquelle répond et ce qu'elle renvoie."""
    urls_a_tester = [
        # Page de recherche avancée
        f"https://www.marches-publics.gouv.fr/?page=Entreprise.EntrepriseAdvancedSearch&AllCons&refConsultation={reference}",
        # Recherche par mot-clé
        f"https://www.marches-publics.gouv.fr/index.php5?page=Entreprise.EntrepriseAdvancedSearch&searchAnnCons&keyword={reference}",
    ]
    resultats = []
    for u in urls_a_tester:
        try:
            r = requests.get(u, timeout=20,
                              headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                                       "Accept": "text/html"},
                              allow_redirects=True)
            html = r.text or ""
            # Cherche si la référence apparait dans la page (= consultation trouvée)
            ref_trouvee = reference.lower() in html.lower()
            # Cherche des liens vers EntrepriseDetailsConsultation (= URL de la consultation)
            import re
            ids_consultation = re.findall(
                r"EntrepriseDetailsConsultation[^\"'<>]*?id=(\d+)", html
            )
            resultats.append({
                "url_testee": u,
                "status": r.status_code,
                "url_finale_apres_redirect": r.url,
                "html_length": len(html),
                "reference_trouvee_dans_html": ref_trouvee,
                "ids_consultation_trouves": ids_consultation[:5],
            })
        except Exception as e:
            resultats.append({"url_testee": u, "erreur": str(e)})
    return {"reference": reference, "resultats": resultats}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    os.makedirs(REPERTOIRE_DEBUG, exist_ok=True)

    # === Étape 1 : champs TED ===
    champs_ted = lister_champs_ted_valides()
    print()

    # === Étape 2+3 : dump des marchés actifs ===
    marches = stockage.charger(COLLECTION)
    actifs = {mid: m for mid, m in marches.items() if _est_actif(m)}
    print("=" * 78)
    print(f"  ÉTAPE 2 — Dump des {len(actifs)} marchés actifs")
    print("=" * 78)

    for mid, marche in actifs.items():
        source = marche.get("source")
        ref = marche.get("reference_externe")
        titre = (marche.get("titre") or marche.get("objet") or "?")[:70]
        print()
        print(f"  --- [{source}] {ref} - {titre}")

        if source == "BOAMP":
            record = dump_record_boamp(ref)
            chemin = os.path.join(REPERTOIRE_DEBUG, f"boamp_{ref}.json")
        elif source == "TED":
            record = dump_notice_ted(ref, champs_ted or [])
            chemin = os.path.join(REPERTOIRE_DEBUG, f"ted_{ref}.json")
        else:
            print(f"    Source inconnue, skip.")
            continue

        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        n_cles = len(record) if isinstance(record, dict) else 0
        print(f"    {n_cles} clés racine, sauvé dans {chemin}")

        # Pour BOAMP : aussi extraire les champs susceptibles de contenir des
        # URLs (recherche par nom de clé ET par valeur)
        if source == "BOAMP" and isinstance(record, dict):
            cles_url = _trouver_cles_avec_url(record)
            if cles_url:
                print(f"    Clés contenant 'url' ou 'http' :")
                for cle, val in cles_url[:8]:
                    val_court = str(val)[:120].replace("\n", " ")
                    print(f"      {cle} = {val_court}")

    # === Étape 3 : test PLACE search ===
    print()
    print("=" * 78)
    print("  ÉTAPE 3 — Test recherche PLACE")
    print("=" * 78)
    # Test sur 2-3 références BOAMP actives
    refs_a_tester = [m["reference_externe"] for m in list(actifs.values())[:3]
                      if m.get("source") == "BOAMP"]
    for ref in refs_a_tester:
        print()
        print(f"  Test PLACE pour référence : {ref}")
        rez = tester_place_search(ref)
        chemin = os.path.join(REPERTOIRE_DEBUG, f"place_search_{ref}.json")
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(rez, f, ensure_ascii=False, indent=2)
        for r in rez["resultats"]:
            print(f"    status={r.get('status')} "
                  f"ref_trouvee={r.get('reference_trouvee_dans_html')} "
                  f"ids={len(r.get('ids_consultation_trouves', []))}")

    print()
    print("=" * 78)
    print("  Tous les fichiers de diagnostic dans :")
    print(f"  {REPERTOIRE_DEBUG}")
    print("=" * 78)
    print()
    print("  → Envoie les fichiers .json à Claude pour analyse comparative.")
    print("  → Le plus important : ted_fields_diagnostic.json (champs valides)")
    print("    et la comparaison entre les BOAMP qui ont une URL DCE et")
    print("    ceux qui n'en ont pas.")


# Helper : trouver les champs avec URL dans une struct imbriquée
def _trouver_cles_avec_url(obj, prefixe="", trouves=None):
    if trouves is None:
        trouves = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            nouv_prefixe = f"{prefixe}.{k}" if prefixe else k
            # Match par nom de clé
            if any(mot in k.lower() for mot in ("url", "internet", "adresse",
                                                  "lien", "lieu_acces",
                                                  "profil")):
                trouves.append((nouv_prefixe, v))
            # Match par valeur (string contient http)
            elif isinstance(v, str) and ("http" in v.lower() or
                                          "www." in v.lower()):
                trouves.append((nouv_prefixe, v))
            else:
                _trouver_cles_avec_url(v, nouv_prefixe, trouves)
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:5]):
            _trouver_cles_avec_url(item, f"{prefixe}[{i}]", trouves)
    return trouves


if __name__ == "__main__":
    main()
