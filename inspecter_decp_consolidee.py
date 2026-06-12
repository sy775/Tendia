"""
inspecter_decp_consolidee.py
-----------------------------
Diagnostic préalable à la migration DECP : explore l'API tabulaire de
data.gouv.fr (DECP consolidée par Colin Maudry, mise à jour quotidienne).

C'est la source officielle DECP réglementaire, plus riche que ce que renvoie
Opendatasoft sur data.economie.gouv.fr. Elle contient notamment le champ `id`
qui est la référence interne acheteur (clé manquante côté Opendatasoft).

Objectifs :
1. Vérifier l'accessibilité de l'API
2. Tester les filtres supportés (__exact, __startswith, __contains)
3. Lister les noms exacts des colonnes telles que servies par l'API
4. Compter le volume de marchés FT
5. Sortir 3 marchés bruts complets pour cartographier le mapping

Usage :
    python inspecter_decp_consolidee.py
"""

import json
from http_utils import get_json


# Ressource DECP consolidée (Colin Maudry / Colmo) sur data.gouv.fr
# Format Parquet, ~200 Mo, mis à jour quotidiennement
RESSOURCE_ID = "22847056-61df-452d-837d-8b8ceadbfc52"
BASE_URL = f"https://tabular-api.data.gouv.fr/api/resources/{RESSOURCE_ID}/data/"
PROFILE_URL = f"https://tabular-api.data.gouv.fr/api/resources/{RESSOURCE_ID}/profile/"

# SIRETs France Travail connus (à compléter si DR ont des SIRETs distincts)
SIRET_FT_PRINCIPAL = "13000548100010"
SIREN_FT = "13000548"


def _print_titre(t: str):
    print()
    print("=" * 78)
    print(f"  {t}")
    print("=" * 78)


def _print_section(t: str):
    print()
    print(f"  {t}")
    print("  " + "─" * (len(t) + 2))


def _appeler(url: str, params: dict = None) -> dict:
    """Wrapper qui catch les erreurs proprement."""
    try:
        return get_json(url, params=params, verbose=False)
    except Exception as e:
        print(f"  ⚠ Erreur API : {e}")
        return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_1_profile():
    """Récupère le schéma/profil du dataset."""
    _print_titre("Test 1 — Profil du dataset (schéma complet)")
    rep = _appeler(PROFILE_URL)
    if not rep:
        return
    # Profile contient la liste des colonnes et leurs types
    print(f"  {len(rep.get('profile', {}))} clés top-level dans le profil")
    if "profile" in rep:
        cols = rep["profile"].get("columns") or rep["profile"].get("fields") or {}
        if isinstance(cols, dict):
            print(f"  {len(cols)} colonnes définies :")
            for nom, meta in sorted(cols.items())[:40]:
                t = meta.get("python_type") or meta.get("type") or "?"
                print(f"    {nom:40} ({t})")
        elif isinstance(cols, list):
            print(f"  {len(cols)} colonnes définies :")
            for col in cols[:40]:
                print(f"    {col}")


def test_2_filtre_exact():
    """Filtre __exact sur le SIRET principal FT."""
    _print_titre("Test 2 — Filtre __exact sur SIRET FT principal")
    params = {"acheteur_id__exact": SIRET_FT_PRINCIPAL, "page_size": 1}
    rep = _appeler(BASE_URL, params=params)
    if not rep:
        return None
    total = rep.get("meta", {}).get("total")
    print(f"  Filtre   : acheteur_id__exact={SIRET_FT_PRINCIPAL}")
    print(f"  Total    : {total} ligne(s) retournées")
    return total


def test_3_filtre_startswith():
    """Vérifie si __startswith est supporté."""
    _print_titre("Test 3 — Filtre __startswith sur le SIREN FT (13000548)")
    params = {"acheteur_id__startswith": SIREN_FT, "page_size": 1}
    rep = _appeler(BASE_URL, params=params)
    if not rep:
        print("  → __startswith non supporté ou autre erreur")
        return None
    total = rep.get("meta", {}).get("total")
    print(f"  Filtre   : acheteur_id__startswith={SIREN_FT}")
    print(f"  Total    : {total} ligne(s) retournées")
    if total and total > 0:
        print(f"  ✓ Le filtre __startswith fonctionne")
    return total


def test_4_filtre_contains():
    """Vérifie si __contains est supporté."""
    _print_titre("Test 4 — Filtre __contains sur SIREN FT")
    params = {"acheteur_id__contains": SIREN_FT, "page_size": 1}
    rep = _appeler(BASE_URL, params=params)
    if not rep:
        print("  → __contains non supporté ou autre erreur")
        return None
    total = rep.get("meta", {}).get("total")
    print(f"  Filtre   : acheteur_id__contains={SIREN_FT}")
    print(f"  Total    : {total} ligne(s) retournées")
    return total


def test_5_donnees_actuelles():
    """Vérifie le filtre donneesActuelles + modification_id."""
    _print_titre("Test 5 — Filtre donneesActuelles (= dernière version)")
    # Essai 1 : booléen Python true/false
    for valeur in ["true", "True", "oui"]:
        params = {
            "acheteur_id__exact": SIRET_FT_PRINCIPAL,
            "donneesActuelles__exact": valeur,
            "page_size": 1,
        }
        rep = _appeler(BASE_URL, params=params)
        if rep:
            total = rep.get("meta", {}).get("total")
            print(f"  donneesActuelles__exact={valeur:5} → total: {total}")


def test_6_modification_id_zero():
    """Filtre modification_id=0 (attribution initiale)."""
    _print_titre("Test 6 — Filtre modification_id=0 (attribution initiale)")
    params = {
        "acheteur_id__exact": SIRET_FT_PRINCIPAL,
        "modification_id__exact": "0",
        "page_size": 1,
    }
    rep = _appeler(BASE_URL, params=params)
    if rep:
        total = rep.get("meta", {}).get("total")
        print(f"  Filtre   : acheteur_id={SIRET_FT_PRINCIPAL} + modification_id=0")
        print(f"  Total    : {total} ligne(s) (= nombre de marchés uniques)")


def test_7_echantillon_complet():
    """Récupère 3 marchés bruts pour voir la structure complète."""
    _print_titre("Test 7 — 3 marchés bruts (cartographie des champs)")
    params = {
        "acheteur_id__exact": SIRET_FT_PRINCIPAL,
        "page_size": 3,
    }
    rep = _appeler(BASE_URL, params=params)
    if not rep or not rep.get("data"):
        print("  ⚠ Pas de données")
        return

    print(f"  {len(rep['data'])} marché(s) reçus")
    print(f"  Total disponible : {rep.get('meta', {}).get('total')}")

    for i, m in enumerate(rep["data"], 1):
        print()
        print(f"  ─── Marché {i} ───")
        print(f"  {len(m)} champs présents")
        for k in sorted(m.keys()):
            v = m[k]
            v_str = str(v)[:80] if v is not None else "(null)"
            # Met en évidence les champs clés
            marker = " 🔑" if k in ("id", "uid", "acheteur_id",
                                       "titulaire_id", "montant",
                                       "dateNotification", "dureeMois") else ""
            print(f"    {k:40} = {v_str}{marker}")


def test_8_volume_2_ans():
    """Estimation du volume sur 2 ans (filtre date)."""
    _print_titre("Test 8 — Volume FT sur 2 dernières années")
    from datetime import date, timedelta
    date_seuil = (date.today() - timedelta(days=730)).isoformat()
    params = {
        "acheteur_id__exact": SIRET_FT_PRINCIPAL,
        "dateNotification__greater": date_seuil,
        "page_size": 1,
    }
    rep = _appeler(BASE_URL, params=params)
    if rep:
        total = rep.get("meta", {}).get("total")
        print(f"  Marchés FT (SIRET principal) notifiés depuis {date_seuil} : {total}")
    # Idem avec __startswith pour comparer
    params = {
        "acheteur_id__startswith": SIREN_FT,
        "dateNotification__greater": date_seuil,
        "page_size": 1,
    }
    rep = _appeler(BASE_URL, params=params)
    if rep:
        total = rep.get("meta", {}).get("total")
        print(f"  Marchés FT (SIREN, tous SIRETs) notifiés depuis {date_seuil} : {total}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print()
    print("╔" + "═" * 76 + "╗")
    print("║" + "  INSPECTION DECP CONSOLIDÉE (data.gouv.fr)".ljust(76) + "║")
    print("║" + "  Source maintenue par Colin Maudry / Colmo".ljust(76) + "║")
    print("║" + f"  Ressource ID : {RESSOURCE_ID}".ljust(76) + "║")
    print("╚" + "═" * 76 + "╝")

    test_1_profile()
    test_2_filtre_exact()
    test_3_filtre_startswith()
    test_4_filtre_contains()
    test_5_donnees_actuelles()
    test_6_modification_id_zero()
    test_7_echantillon_complet()
    test_8_volume_2_ans()

    print()
    print("=" * 78)
    print("  À RAPPORTER À CLAUDE")
    print("=" * 78)
    print("""
  1. Le filtre __startswith fonctionne-t-il ? (test 3)
     → Si oui, on l'utilise pour capter tous les SIRETs FT en une requête.
     → Si non, on liste manuellement les SIRETs FT et on fait N appels.

  2. Combien de marchés FT au total ? (test 2)
     → Si > 5000, on filtre par date pour rester sur 2 ans.

  3. Le champ `id` du test 7 contient-il bien une référence du genre
     '2605-DRFT-NA-FOP-110' ou similaire ?
     → C'est la donnée critique. Si absente ou vide, on a un problème.

  4. Le filtre donneesActuelles__exact accepte quelle valeur ? (test 5)
     → true / True / oui / 1 / autre

  5. Liste de TOUS les noms de colonnes affichés par le test 7
     (avec ou sans point, en camelCase ou snake_case)
     → Détermine le mapping exact dans le nouveau connecteur.
""")
