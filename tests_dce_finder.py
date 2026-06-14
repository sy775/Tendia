"""
tests_dce_finder.py
-------------------
Tests HORS-LIGNE du fix /agent/ vs /entreprise/ dans dce_finder (aucun réseau).

Bug visé : le crawler capturait parfois une URL côté ACHETEUR (`/agent/` ou
`?page=Agent.…`) au lieu de l'interface ENTREPRISE. Comportement attendu :
  - chemin `/agent/` (Atexo)  → réécrit en `/entreprise/` (swap propre) ;
  - PLACE `?page=Agent.…`     → non réécrivable → URL écartée + incident loggué,
                                rien stocké en base (cascade tente le keyword) ;
  - URL entreprise correcte   → conservée intacte ;
  - URL non concernée         → inchangée.

Lancement : python tests_dce_finder.py
"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import dce_finder as D

ok = 0
ko = 0


def check(nom, cond):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}")


def _record(uri):
    """Faux record BOAMP avec l'URI DCE au chemin UBL standard (Niveau 1)."""
    donnees = {"EFORMS": {"ContractNotice": {"cac:ProcurementProjectLot": {
        "cac:TenderingTerms": {"cac:CallForTendersDocumentReference": {
            "cac:Attachment": {"cac:ExternalReference": {"cbc:URI": uri}}}}}}}}
    return {"donnees": json.dumps(donnees, ensure_ascii=False)}


URL_AGENT_PATH = "https://mpe.example.fr/agent/consultation/123?orgAcronyme=xyz789ab"
URL_ENTREPRISE_PATH = "https://mpe.example.fr/entreprise/consultation/123?orgAcronyme=xyz789ab"
URL_AGENT_PLACE = "https://www.marches-publics.gouv.fr/index.php?page=Agent.DetailConsultation&id=3014094"
URL_ENTREPRISE_PLACE = "https://www.marches-publics.gouv.fr/?page=Entreprise.EntrepriseDetailsConsultation&id=3014084&orgAcronyme=x7c"
URL_NON_PLACE = "https://achats.autreplateforme.fr/dce/document?ref=abcdefgh123"


# ===========================================================================
# Helpers purs : _est_url_cote_agent / _corriger_url_agent
# ===========================================================================
print("=== _est_url_cote_agent ===")
check("chemin /agent/ détecté", D._est_url_cote_agent(URL_AGENT_PATH))
check("PLACE page=Agent. détecté", D._est_url_cote_agent(URL_AGENT_PLACE))
check("URL entreprise (path) NON détectée", not D._est_url_cote_agent(URL_ENTREPRISE_PATH))
check("URL entreprise (PLACE) NON détectée", not D._est_url_cote_agent(URL_ENTREPRISE_PLACE))
check("URL non-PLACE NON détectée", not D._est_url_cote_agent(URL_NON_PLACE))

print("\n=== _corriger_url_agent ===")
u, inc = D._corriger_url_agent(URL_AGENT_PATH)
check("chemin /agent/ → réécrit en /entreprise/", u == URL_ENTREPRISE_PATH and inc is None)
u, inc = D._corriger_url_agent(URL_AGENT_PLACE)
check("PLACE page=Agent. → non réécrivable (None + incident)", u is None and inc is not None)
check("incident porte la raison + l'URL",
      inc and inc.get("raison") == "url_cote_agent_non_reecrivable" and inc.get("url") == URL_AGENT_PLACE)
u, inc = D._corriger_url_agent(URL_ENTREPRISE_PLACE)
check("URL entreprise PLACE conservée intacte", u == URL_ENTREPRISE_PLACE and inc is None)
u, inc = D._corriger_url_agent(URL_NON_PLACE)
check("URL non-PLACE inchangée", u == URL_NON_PLACE and inc is None)
# URL agent à la fois en path ET en query → swap de path insuffisant → écartée.
mix = "https://x.fr/agent/index.php?page=Agent.DetailConsultation&id=9"
u, inc = D._corriger_url_agent(mix)
check("agent path+query non réécrivable", u is None and inc is not None)


# ===========================================================================
# Intégration : _extraire_dce_boamp (les 3 cas du cahier des charges)
# ===========================================================================
print("\n=== _extraire_dce_boamp (cas eForms) ===")

# Cas 1 — URL /agent/ → réécrite vers l'entreprise équivalente.
out = D._extraire_dce_boamp(_record(URL_AGENT_PATH), "FT-1")
check("Cas 1 : url_dce réécrite en /entreprise/", out["url_dce"] == URL_ENTREPRISE_PATH)
check("Cas 1 : qualité directe", out["qualite"] == "directe")
check("Cas 1 : champ_source signale la réécriture", "réécrite" in (out.get("champ_source") or ""))
check("Cas 1 : aucun incident", not out["incidents"])

# Cas 1bis — PLACE page=Agent. non réécrivable → écartée + incident, rien stocké.
out = D._extraire_dce_boamp(_record(URL_AGENT_PLACE), "FT-2")
check("Cas 1bis : url_dce NON stockée (None)", out["url_dce"] is None)
check("Cas 1bis : qualité absente", out["qualite"] == "absente")
check("Cas 1bis : ≥1 incident enregistré", len(out["incidents"]) >= 1)
check("Cas 1bis : l'URL agent figure dans l'incident",
      any(i.get("url") == URL_AGENT_PLACE for i in out["incidents"]))

# Cas 2 — URL entreprise correcte → conservée intacte.
out = D._extraire_dce_boamp(_record(URL_ENTREPRISE_PLACE), "FT-3")
check("Cas 2 : url_dce entreprise conservée", out["url_dce"] == URL_ENTREPRISE_PLACE)
check("Cas 2 : qualité directe", out["qualite"] == "directe")
check("Cas 2 : aucun incident", not out["incidents"])

# Cas 3 — URL non-PLACE (non agent) → ne pas toucher.
out = D._extraire_dce_boamp(_record(URL_NON_PLACE), "FT-4")
check("Cas 3 : url_dce non-PLACE inchangée", out["url_dce"] == URL_NON_PLACE)
check("Cas 3 : aucun incident", not out["incidents"])


print(f"\n{'='*56}")
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
