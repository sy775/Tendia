"""
inspecter_boamp_brut.py — diagnostic des champs disponibles dans l'API BOAMP

A lancer une fois pour comprendre la structure reelle des donnees :
    python inspecter_boamp_brut.py > diagnostic_boamp.txt

Aucun appel LLM, aucune ecriture en base.
"""

import io
import json
import sys
from datetime import date, timedelta
from http_utils import get_json

# Force UTF-8 sur stdout pour eviter UnicodeEncodeError sur Windows cp1252
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BOAMP_URL = (
    "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/"
    "catalog/datasets/boamp/records"
)

print("=== 1. Recuperation d'un echantillon de 3 avis recents ===\n")
params = {
    "limit": 3,
    "offset": 0,
    "order_by": "dateparution DESC",
}
reponse = get_json(BOAMP_URL, params=params, verbose=False)
avis_liste = reponse.get("results") or []

print(f"Total cote API (sans filtre) : {reponse.get('total_count'):,}")
print(f"Avis recus : {len(avis_liste)}\n")

# Test differents formats de filtre date cote API
print("=== 2. Test du filtre date cote API ===\n")
date_debut = (date.today() - timedelta(days=180)).isoformat()
tests_filtre_date = [
    ("dateparution >= date'2025-12-01'", "syntaxe ODS date"),
    (f"dateparution >= '{date_debut}'", "syntaxe ODS string ISO"),
    (f"dateparution:>='{date_debut}'", "syntaxe Lucene"),
]
for clause, libelle in tests_filtre_date:
    try:
        r = get_json(BOAMP_URL,
                     params={"where": clause, "limit": 1},
                     verbose=False)
        total = r.get("total_count", "?")
        print(f"  OK  {libelle:40} -> total = {total:,}")
    except Exception as e:
        print(f"  KO  {libelle:40} -> ERREUR : {str(e)[:80]}")
print()

# Premier avis : sa structure complete (les cles top-level)
if avis_liste:
    a = avis_liste[0]
    print("=== 3. Structure d'un avis (cles top-level uniquement) ===\n")
    cles = sorted(a.keys())
    for cle in cles:
        valeur = a[cle]
        type_v = type(valeur).__name__
        if isinstance(valeur, str):
            apercu = valeur[:80].replace("\n", " ")
            print(f"  {cle:35} [{type_v:6}] {apercu!r}")
        elif isinstance(valeur, (int, float, bool)) or valeur is None:
            print(f"  {cle:35} [{type_v:6}] {valeur}")
        elif isinstance(valeur, list):
            print(f"  {cle:35} [{type_v:6}] longueur={len(valeur)}")
        else:
            print(f"  {cle:35} [{type_v:6}] {str(valeur)[:80]}")
    print()

    # Cherche tous les champs qui mentionnent "cpv" dans leur nom
    print("=== 4. Champs contenant 'cpv' dans le nom ===\n")
    champs_cpv = [c for c in cles if "cpv" in c.lower()]
    if champs_cpv:
        for cle in champs_cpv:
            print(f"  {cle:35} = {a[cle]!r}")
    else:
        print("  AUCUN champ avec 'cpv' au top-level.")
    print()

    # Cherche dans donnees / detail / nested si le top-level est pauvre
    print("=== 5. Recherche profonde de CPV dans les sous-objets ===\n")
    def chercher_cpv(obj, chemin="", profondeur=0):
        if profondeur > 4:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                if "cpv" in k.lower():
                    apercu = str(v)[:100]
                    print(f"  {chemin}.{k} = {apercu!r}")
                chercher_cpv(v, f"{chemin}.{k}", profondeur + 1)
        elif isinstance(obj, list) and obj:
            chercher_cpv(obj[0], f"{chemin}[0]", profondeur + 1)

    chercher_cpv(a)
    print()

    # Affichage complet du premier avis (JSON) pour exploration manuelle
    print("=== 6. JSON complet du premier avis (pour exploration manuelle) ===\n")
    print(json.dumps(a, ensure_ascii=False, indent=2)[:3000])
    print("\n... (tronque si > 3000 chars)")
