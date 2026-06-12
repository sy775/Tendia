"""
inspecter_decp.py
-----------------
DIAGNOSTIC ONE-SHOT pour identifier le nom exact du champ `reference_acheteur`
dans le schéma DECP brut.

Appelle l'API DECP pour récupérer 3 marchés France Travail tels que livrés par
Opendatasoft (donc avec TOUS les champs disponibles, contrairement à ce qui
finit dans `marches_notifies.json` après normalisation).

Utilité : si le patch B6 de `connecteurs/decp.py` ne capte pas la référence
acheteur après `tendia_decp.py`, ce script permet de voir le nom exact du
champ et de l'ajouter à la liste candidate dans `_reference_acheteur()`.

Usage :
    python inspecter_decp.py
    python inspecter_decp.py --n 5         # plus d'échantillons
    python inspecter_decp.py --champs ref  # ne montre que les champs contenant 'ref'

Aucune mutation. Lecture seule.
"""

import argparse
import json
from typing import Optional

from http_utils import get_json


DECP_URL = (
    "https://data.economie.gouv.fr/api/explore/v2.1/"
    "catalog/datasets/decp-2022-marches-valides/records"
)
SIREN_FT = "13000548"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=3,
                        help="Nombre de marchés à inspecter (défaut: 3)")
    parser.add_argument("--champs", type=str, default=None,
                        help="Filtre : ne montre que les champs contenant ce mot")
    args = parser.parse_args()

    params = {
        "where": f'startswith(acheteur_id, "{SIREN_FT}")',
        "limit": args.n,
        "order_by": "datenotification DESC",
    }

    print("=" * 78)
    print("  INSPECTION DECP — champs bruts de l'API Opendatasoft")
    print("=" * 78)
    print(f"  URL    : {DECP_URL}")
    print(f"  Filtre : {params['where']}")
    print()

    try:
        rep = get_json(DECP_URL, params=params, verbose=True)
    except Exception as e:
        print(f"❌ Erreur API : {e}")
        return

    if not rep or not rep.get("results"):
        print("❌ Aucun résultat retourné par l'API")
        return

    print(f"  {len(rep['results'])} marché(s) reçus")
    print()

    for i, marche in enumerate(rep["results"], 1):
        print("=" * 78)
        print(f"  [{i}/{len(rep['results'])}] Tous les champs disponibles")
        print("=" * 78)

        # Pioche les champs avec un nom susceptible d'être une référence
        candidats_ref = {}
        for k, v in marche.items():
            if not args.champs or args.champs.lower() in k.lower():
                kl = k.lower()
                if any(mot in kl for mot in
                       ("ref", "id", "marche", "numero", "identif")):
                    candidats_ref[k] = v

        # Tous les champs présents
        print(f"  Total champs : {len(marche)}")
        if candidats_ref:
            print(f"  Champs candidats référence acheteur ({len(candidats_ref)}) :")
            for k, v in sorted(candidats_ref.items()):
                v_str = str(v)[:80] if v is not None else "(null)"
                print(f"    {k:40} = {v_str}")
        print()

        # Dump complet en JSON pour les très curieux
        if not args.champs:
            print(f"  Champs non-référence :")
            for k in sorted(marche.keys()):
                if k in candidats_ref:
                    continue
                v = marche[k]
                v_str = str(v)[:60] if v is not None else "(null)"
                print(f"    {k:40} = {v_str}")
        print()

    print("=" * 78)
    print("  ACTION ATTENDUE")
    print("=" * 78)
    print()
    print("  Repère dans les champs ci-dessus celui qui ressemble à une")
    print("  référence acheteur — typiquement un code de la forme :")
    print("    '2605-DRFT-NA-FOP-110' (FT actuel)")
    print("    'YYYY-...-NNN'")
    print()
    print("  Si tu en trouves un dont le nom n'est PAS déjà dans la liste")
    print("  candidate de `_reference_acheteur()` dans connecteurs/decp.py :")
    print("    id_marche, idMarche, reference_marche, reference_acheteur,")
    print("    referenceAcheteur, numero_marche, numeroMarche, numero,")
    print("    identifiant_marche, identifiantMarche, id_acheteur_marche")
    print()
    print("  → préviens Claude pour qu'il ajoute ce nom à la liste candidate.")


if __name__ == "__main__":
    main()
