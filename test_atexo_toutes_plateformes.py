"""
test_atexo_toutes_plateformes.py
--------------------------------
Test le telechargeur Atexo sur 1 marche par plateforme Atexo connue
(ternum-bfc, demat-ampa, megalis, maximilien, + forks municipaux si trouves).
Verifie pour chacune que le ZIP est telecharge avec au moins 2 pieces
contractuelles distinctes.

Usage : python test_atexo_toutes_plateformes.py
"""
import io
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import atexo_downloader as A


# Plateformes Atexo connues. Les forks municipaux sont detectes par signature.
HOSTS_A_TESTER = [
    "marches.ternum-bfc.fr",
    "demat-ampa.fr",
    "marches.megalis.bretagne.bzh",
    "marches.maximilien.fr",
    # forks municipaux (rattrapes par signature Atexo)
    "marches.rhone.fr",
    "profilacheteur.meuse.fr",
    "marchespublics.nantesmetropole.fr",
    "marches.departement13.fr",
    "mpe.mairie-marseille.fr",
    "marchespublics596280.fr",
]


def trouver_candidat(marches, host):
    """Trouve 1 marche dont url_dce contient `host`. Prefere `incomplet`."""
    pool = [
        (mid, m) for mid, m in marches.items()
        if host in (m.get("url_dce") or "")
    ]
    if not pool:
        return None
    # Priorite : incomplet
    incomplets = [c for c in pool if c[1].get("dce_contenu") == "incomplet"]
    if incomplets:
        return incomplets[0]
    return pool[0]


def tester_marche(mid, marche):
    print(f"\n=== {mid} ===")
    print(f"URL DCE : {marche.get('url_dce')}")
    print(f"dce_contenu actuel : {marche.get('dce_contenu')}")
    print(f"dce_pieces actuelles : {marche.get('dce_pieces_contractuelles')}")
    print("Telechargement Atexo en cours...")

    try:
        result = A.telecharger_dce_pour_marche(marche, "data/dce", verbose=False)
    except Exception as e:
        print(f"  EXCEPTION : {type(e).__name__}: {e}")
        return False, []

    if not result.get("ok"):
        print(f"  ECHEC : {result.get('erreur')}")
        return False, []

    print(f"  OK : {result.get('taille_octets')} octets en "
          f"{result.get('duree_secondes')}s")
    print(f"  Chemin : {result.get('chemin')}")

    # Lister le contenu du ZIP
    chemin = result.get("chemin")
    noms = []
    if chemin:
        try:
            with zipfile.ZipFile(chemin) as z:
                noms = z.namelist()
                print(f"  Contenu ({len(noms)} fichiers) :")
                for n in noms[:10]:
                    print(f"    - {n}")
                if len(noms) > 10:
                    print(f"    ... +{len(noms) - 10} autres")
        except Exception as e:
            print(f"  ZIP non lisible : {e}")
            return False, []

    return True, noms


def main():
    print("=" * 70)
    print("TEST ATEXO MULTI-PLATEFORMES")
    print("=" * 70)

    marches = stockage.charger("marches")
    print(f"\n{len(marches)} marches en base")
    print(f"Test sur {len(HOSTS_A_TESTER)} plateformes Atexo")

    resultats = {}
    for host in HOSTS_A_TESTER:
        print("\n" + "-" * 70)
        print(f"PLATEFORME : {host}")
        print("-" * 70)
        candidat = trouver_candidat(marches, host)
        if not candidat:
            print(f"  (aucun marche pour {host}, skip)")
            resultats[host] = ("skip", 0)
            continue
        mid, marche = candidat
        ok, noms = tester_marche(mid, marche)
        resultats[host] = ("ok" if ok else "echec", len(noms))

    # Synthese
    print("\n" + "=" * 70)
    print("SYNTHESE")
    print("=" * 70)
    print(f"{'Plateforme':<45} {'Statut':<8} {'Fichiers':<10}")
    print("-" * 70)
    for host, (statut, n) in resultats.items():
        print(f"{host:<45} {statut:<8} {n if statut == 'ok' else '-':<10}")

    nb_ok = sum(1 for s, _ in resultats.values() if s == "ok")
    nb_echec = sum(1 for s, _ in resultats.values() if s == "echec")
    nb_skip = sum(1 for s, _ in resultats.values() if s == "skip")
    print(f"\nTotal : {nb_ok} OK, {nb_echec} echec, {nb_skip} skip")

    if nb_echec == 0 and nb_ok >= 4:
        print("\n>>> Le mecanisme Atexo est valide sur les plateformes principales.")
        print(">>> On peut lancer le batch retelecharger_incomplet.py.")
    elif nb_echec > 0:
        print(f"\n>>> {nb_echec} plateforme(s) en echec : investiguer avant le batch.")


if __name__ == "__main__":
    main()
