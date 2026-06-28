"""Test ciblé de la ré-extraction v3 sur 1 marché (BOAMP-26-56096).

Valide que les nouveaux champs se peuplent : dossier_candidature.pieces_a_fournir,
tranches, lots[].domaine, certifications_obligatoires[].codes/bloquante, et le
routage multi-preset (Axe 3). Appel LLM réel (~0,40 € sur gros DCE).
"""
import io
import os
import sys
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import stockage
import pdf_extract
import tendia_extraire
import llm_extract

MID = "BOAMP-26-56096"
dossier = os.path.join("data", "dce", MID)

print(f"=== Ré-extraction TEST sur {MID} ===")
print(f"PROMPT_V2_SHA actif : {llm_extract.PROMPT_V2_SHA}")
print(f"Presets résolus (Axe 3) : {llm_extract._resoudre_presets_pour_marche(MID)}")

# Backup de l'ancien brief
briefs = stockage.charger("briefs_extraits") or {}
if MID in briefs:
    stockage.ecrire("briefs_extraits", f"{MID}.bak_avant_v3", briefs[MID])
    print("Ancien brief sauvegardé (.bak_avant_v3)")

# Dézip si besoin + extraction texte du dossier
tendia_extraire._dezipper_dossier(dossier, verbose=False)
pdfs = pdf_extract.extraire_dossier(dossier, verbose=False)
print(f"Pièces lues : {len(pdfs)}")

print("\nAppel LLM (peut prendre quelques minutes sur un gros DCE)...")
res = tendia_extraire.traiter_marche(MID, dossier, pdfs, dry_run=False, verbose=True)
print(f"\nRésultat : ok={res.get('ok')} {res.get('erreur') or res.get('raison') or ''}")

if not res.get("ok"):
    sys.exit(1)

b = stockage.lire("briefs_extraits", MID) or {}
b["genere_avec_dce_complet"] = True
stockage.ecrire("briefs_extraits", MID, b)


def montre(titre, valeur):
    print(f"\n--- {titre} ---")
    print(json.dumps(valeur, ensure_ascii=False, indent=2)[:1400] if valeur else "  (vide / null)")


print("\n" + "=" * 60)
print("VALIDATION DES NOUVEAUX CHAMPS")
print("=" * 60)
montre("domaines_metier (routage)", b.get("domaines_metier"))
montre("lots[].domaine", [{"numero": l.get("numero"), "intitule": (l.get("intitule") or "")[:40],
                            "domaine": l.get("domaine")} for l in (b.get("lots") or [])])
montre("tranches", b.get("tranches"))
montre("dossier_candidature", b.get("dossier_candidature"))
montre("certifications_obligatoires (codes/bloquante)",
       (b.get("references_exigees") or {}).get("certifications_obligatoires"))
print(f"\nCoût de cet appel : {(b.get('_meta') or {}).get('cout_eur')} €")
