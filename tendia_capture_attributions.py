"""
tendia_capture_attributions.py
-------------------------------
Capture les attributions DECP des marchés actifs qu'on a vus passer.

Workflow :
    1. Itère sur les marchés actifs (data/marches.json) avec date_limite passée
    2. Pour chaque marché non encore capturé, cherche son attribution dans
       data/marches_notifies.json via 3 niveaux de matching :
         a. reference_externe identique           → confiance "haute"
         b. acheteur_siret + objet ≥ 80% similar  → confiance "haute"
         c. acheteur_siret + catégorie + DR       → confiance "moyenne"
    3. Pour chaque match trouvé : construit une entrée dans
       marches_tendia_attribues (avec brief LLM si dispo)
    4. Marque l'id du marché comme "tenté" dans data/_tendia_capture_etat.json
       (pour ne pas re-tenter à chaque exécution)

Le script est INCRÉMENTAL et IDEMPOTENT : on peut le relancer autant qu'on
veut, il ne re-traite pas ce qu'il a déjà fait.

Usage :
    python tendia_capture_attributions.py                # tous les marchés
    python tendia_capture_attributions.py --marche <id>  # un seul marché
    python tendia_capture_attributions.py --dry-run      # liste sans écrire
    python tendia_capture_attributions.py --force        # re-tente même
                                                          # ceux déjà tentés
    python tendia_capture_attributions.py --reset-etat   # vide le tracking
    python tendia_capture_attributions.py --seuil-sim 0.7 # seuil similarité objet
"""

import argparse
import json
import os
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import marches_attribues
import stockage


_BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = _BASE_DIR / "data"
ETAT_PATH = DATA_DIR / "_tendia_capture_etat.json"
BRIEFS_DIR = DATA_DIR / "extractions"

# Délai max entre date_limite_depot et date_notification pour un match plausible
DELAI_NOTIFICATION_MAX_JOURS = 540  # 18 mois

# Seuil similarité objet par défaut (matching niveau 2)
SEUIL_OBJET_SIMILAIRE = 0.72


# ---------------------------------------------------------------------------
# Tracking
# ---------------------------------------------------------------------------

def _charger_etat() -> dict:
    if not ETAT_PATH.exists():
        return {"marches_tentes": {}}
    try:
        with open(ETAT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"marches_tentes": {}}


def _sauver_etat(etat: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ETAT_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(etat, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ETAT_PATH)


# ---------------------------------------------------------------------------
# Matching marché actif ↔ attribution DECP
# ---------------------------------------------------------------------------

def _normaliser_objet(texte: str) -> str:
    """Normalise un objet pour la comparaison (lowercase, espaces, accents simplifiés)."""
    import unicodedata
    if not texte:
        return ""
    s = unicodedata.normalize("NFKD", texte.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.split())


def _similarite_objet(o1: str, o2: str) -> float:
    """Retourne un score [0, 1] de similarité textuelle entre 2 objets."""
    o1n = _normaliser_objet(o1)
    o2n = _normaliser_objet(o2)
    if not o1n or not o2n:
        return 0.0
    return SequenceMatcher(None, o1n, o2n).ratio()


def _date_dans_fenetre(date_limite_str: str, date_notif_str: str) -> bool:
    """True si la date de notification tombe dans la fenêtre attendue après
    la date_limite (entre 0 et DELAI_NOTIFICATION_MAX_JOURS jours après)."""
    if not date_limite_str or not date_notif_str:
        return False
    try:
        dl = datetime.strptime(date_limite_str[:10], "%Y-%m-%d").date()
        dn = datetime.strptime(date_notif_str[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return False
    delta_j = (dn - dl).days
    return 0 <= delta_j <= DELAI_NOTIFICATION_MAX_JOURS


def _meme_acheteur(marche_actif: dict, attribution: dict) -> bool:
    """True si les acheteurs sont les mêmes (SIRET prioritaire, fallback nom)."""
    s1 = marche_actif.get("acheteur_siret") or ""
    s2 = attribution.get("acheteur_id") or ""
    if s1 and s2 and s1 == s2:
        return True
    n1 = (marche_actif.get("acheteur_nom") or "").strip().lower()
    n2 = (attribution.get("acheteur_nom") or "").strip().lower()
    if n1 and n2 and n1 == n2:
        return True
    return False


def chercher_attribution(marche_actif: dict, marches_notifies: dict,
                          seuil_objet: float = SEUIL_OBJET_SIMILAIRE
                          ) -> list:
    """Cherche les attributions DECP plausibles pour un marché actif.

    Retourne une liste de tuples (attribution_decp, dict_matching_meta),
    triée par confiance décroissante. Liste vide si rien trouvé.
    """
    candidates = []

    # Pré-filtrage : on ignore tout ce qui a une date_notification antérieure
    # à la date_publication du marché actif (un marché ne peut pas avoir été
    # notifié avant d'avoir été publié).
    date_pub = marche_actif.get("date_publication", "") or ""
    date_limite = (marche_actif.get("date_limite_depot")
                   or marche_actif.get("date_limite_reponse") or "")
    ref_actif = marche_actif.get("reference_externe") or ""
    objet_actif = (marche_actif.get("objet")
                   or marche_actif.get("titre") or "")

    for id_decp, attribution in marches_notifies.items():
        # Vérif date plausible
        date_notif = attribution.get("date_notification") or ""
        if date_pub and date_notif:
            try:
                dp = datetime.strptime(date_pub[:10], "%Y-%m-%d").date()
                dn = datetime.strptime(date_notif[:10], "%Y-%m-%d").date()
                if dn < dp:
                    continue
            except (ValueError, TypeError):
                pass

        # NIVEAU 1 : référence_externe identique
        ref_decp = attribution.get("reference_externe") or ""
        if ref_actif and ref_decp and ref_actif == ref_decp:
            candidates.append((attribution, {
                "confiance": "haute",
                "methode": "reference_externe_exacte",
                "score": 1.0,
            }))
            continue

        # NIVEAUX 2 & 3 nécessitent l'acheteur identique
        if not _meme_acheteur(marche_actif, attribution):
            continue

        # NIVEAU 2 : acheteur + objet similaire + fenêtre notification
        objet_decp = attribution.get("objet") or ""
        sim_objet = _similarite_objet(objet_actif, objet_decp)
        date_ok = _date_dans_fenetre(date_limite, date_notif)
        if sim_objet >= seuil_objet and date_ok:
            candidates.append((attribution, {
                "confiance": "haute",
                "methode": "siret_objet_similaire",
                "score": round(sim_objet, 3),
            }))
            continue

        # NIVEAU 3 : acheteur + catégorie + DR + fenêtre
        cat_actif = marche_actif.get("categorie_metier")
        cat_decp = attribution.get("categorie_metier")
        if (cat_actif and cat_decp and cat_actif == cat_decp
                and date_ok and sim_objet >= 0.5):
            candidates.append((attribution, {
                "confiance": "moyenne",
                "methode": "siret_categorie_date",
                "score": round(sim_objet, 3),
            }))

    # Trier : haute confiance d'abord, puis score décroissant
    ordre_confiance = {"haute": 0, "moyenne": 1, "a_valider": 2}
    candidates.sort(key=lambda x: (
        ordre_confiance.get(x[1]["confiance"], 99),
        -x[1]["score"],
    ))
    return candidates


# ---------------------------------------------------------------------------
# Pipeline de capture
# ---------------------------------------------------------------------------

def _charger_brief(id_marche: str) -> dict:
    """Charge le brief LLM s'il existe."""
    chemin = BRIEFS_DIR / f"{id_marche}.json"
    if not chemin.exists():
        return None
    try:
        with open(chemin, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def capturer_tout(force: bool = False,
                   dry_run: bool = False,
                   id_filtre: str = None,
                   seuil_objet: float = SEUIL_OBJET_SIMILAIRE,
                   verbose: bool = True) -> dict:
    """Boucle principale. Retourne un dict de statistiques."""
    marches = stockage.charger("marches")
    marches_notifies = stockage.charger("marches_notifies")
    etat = _charger_etat()
    tentes = etat.get("marches_tentes") or {}

    maintenant = datetime.now().date()

    # Sélection des candidats à tenter
    candidats = []
    for mid, m in marches.items():
        if id_filtre and mid != id_filtre:
            continue
        # Skip si déjà tenté (sauf --force)
        if not force and mid in tentes:
            continue
        # Skip si date_limite pas encore passée
        dl_str = m.get("date_limite_depot") or m.get("date_limite_reponse")
        if not dl_str:
            continue
        try:
            dl = datetime.strptime(dl_str[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        if dl > maintenant:
            continue  # encore ouvert
        candidats.append((mid, m))

    if verbose:
        print()
        print("=" * 78)
        print(f"  TENDIA CAPTURE ATTRIBUTIONS  {'(dry-run)' if dry_run else ''}")
        print("=" * 78)
        print(f"  Marchés actifs en base   : {len(marches)}")
        print(f"  Marchés DECP en base     : {len(marches_notifies)}")
        print(f"  Marchés déjà tentés      : {len(tentes)}")
        print(f"  Candidats à tenter       : {len(candidats)}")
        print(f"  Seuil similarité objet   : {seuil_objet}")

    stats = {
        "candidats": len(candidats),
        "matches_haute": 0,
        "matches_moyenne": 0,
        "non_trouves": 0,
        "erreurs": 0,
        "creations": 0,
        "nouveaux_ids": [],
    }

    for mid, m in candidats:
        if verbose:
            print()
            print(f"  ▸ {mid}")
            print(f"    {(m.get('titre') or '')[:74]}...")

        try:
            matches = chercher_attribution(m, marches_notifies, seuil_objet)
        except Exception as e:
            print(f"    ❌ Erreur matching : {type(e).__name__}: {e}")
            stats["erreurs"] += 1
            continue

        if not matches:
            stats["non_trouves"] += 1
            if verbose:
                print(f"    ∅ Aucune attribution trouvée (le marché n'a probablement pas encore été notifié dans DECP)")
            # Marquer comme tenté (mais éligible re-tentative future)
            if not dry_run:
                tentes[mid] = {
                    "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "resultat": "non_trouve",
                }
            continue

        # On retient le 1er match (= meilleur)
        attribution, meta_match = matches[0]
        if meta_match["confiance"] == "haute":
            stats["matches_haute"] += 1
        else:
            stats["matches_moyenne"] += 1

        if verbose:
            print(f"    ✓ Match {meta_match['confiance']} ({meta_match['methode']}, score {meta_match['score']})")
            print(f"      → DECP {attribution.get('id')} · titulaire {attribution.get('titulaire_nom')} · {attribution.get('montant_eur'):,.0f} €")
            if len(matches) > 1:
                print(f"      (+ {len(matches) - 1} candidats secondaires non retenus)")

        if dry_run:
            continue

        # Charger le brief LLM si dispo
        brief = _charger_brief(mid)

        # Construire l'entrée et l'écrire
        try:
            entree = marches_attribues.construire_entree(
                marche_actif=m,
                brief=brief,
                attribution_decp=attribution,
                matching_meta=meta_match,
            )
            marches_attribues.ecrire(entree["id"], entree)
            stats["creations"] += 1
            stats["nouveaux_ids"].append(entree["id"])
            if verbose:
                ratios = entree.get("ratios") or {}
                if ratios.get("prix_par_beneficiaire_eur"):
                    print(f"      Entrée créée. Ratio : {ratios['prix_par_beneficiaire_eur']:,.0f} €/bénéficiaire")
                elif ratios.get("prix_mensuel_eur"):
                    print(f"      Entrée créée. Ratio : {ratios['prix_mensuel_eur']:,.0f} €/mois")
                else:
                    print(f"      Entrée créée (sans brief — ratios fins indisponibles)")
        except Exception as e:
            print(f"      ❌ Erreur construction/écriture : {type(e).__name__}: {e}")
            stats["erreurs"] += 1
            continue

        tentes[mid] = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "resultat": "match_" + meta_match["confiance"],
            "id_tendia": entree["id"],
        }

    # Persister l'état
    if not dry_run:
        etat["marches_tentes"] = tentes
        _sauver_etat(etat)

    if verbose:
        print()
        print("=" * 78)
        print(f"  BILAN")
        print("=" * 78)
        print(f"  Candidats traités        : {stats['candidats']}")
        print(f"  Matches haute confiance  : {stats['matches_haute']}")
        print(f"  Matches moyenne          : {stats['matches_moyenne']}")
        print(f"  Aucune attribution       : {stats['non_trouves']}")
        print(f"  Erreurs                  : {stats['erreurs']}")
        print(f"  Entrées créées           : {stats['creations']}{'  (dry-run)' if dry_run else ''}")
        if stats["creations"]:
            print(f"\n  Total dans marches_tendia_attribues : {marches_attribues.compter()}")

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Capture les attributions DECP des marchés actifs."
    )
    parser.add_argument("--marche", default=None,
                        help="Traite uniquement ce marché.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Liste les matches sans écrire.")
    parser.add_argument("--force", action="store_true",
                        help="Re-tente même les marchés déjà traités.")
    parser.add_argument("--reset-etat", action="store_true",
                        help="Efface le tracking des tentatives (n'efface pas "
                             "les entrées de marches_tendia_attribues).")
    parser.add_argument("--seuil-sim", type=float, default=SEUIL_OBJET_SIMILAIRE,
                        help=f"Seuil similarité objet (défaut {SEUIL_OBJET_SIMILAIRE}).")
    args = parser.parse_args()

    if args.reset_etat:
        if ETAT_PATH.exists():
            ETAT_PATH.unlink()
            print(f"  ✓ Tracking effacé ({ETAT_PATH})")
        else:
            print(f"  Tracking déjà absent.")
        return

    capturer_tout(
        force=args.force,
        dry_run=args.dry_run,
        id_filtre=args.marche,
        seuil_objet=args.seuil_sim,
        verbose=True,
    )


if __name__ == "__main__":
    main()
