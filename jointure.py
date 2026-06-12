"""
jointure.py
-----------
Maintient un index de jointure entre les marchés BOAMP (avis publiés) et les
marchés DECP (avis notifiés), via la **référence acheteur interne** :
    - côté BOAMP : champ `reference_ft` (ex: "2605-DRFT-NA-FOP-110")
    - côté DECP  : champ `reference_acheteur` (ajouté par le patch B6)

Pourquoi ce module :
- Aujourd'hui, un marché publié au BOAMP qui est notifié plus tard via DECP
  ne peut pas être recroisé : DECP ne stocke pas la référence acheteur dans
  la base actuelle.
- Avec ce module + le patch de `connecteurs/decp.py`, dès qu'un BOAMP et un
  DECP partagent la même `reference_acheteur`, ils sont liés automatiquement.
- Dans 6-12 mois, la base contiendra X paires complètes (BOAMP+DECP appariés)
  qui permettront de calculer un prix unitaire historique (€/bénéficiaire)
  en croisant les volumes BOAMP (avis publiés) et les montants DECP (notifiés).

Architecture :
- Stockage : `data/jointure.json` au format dict {ref_normalisee: entree}
- Module pur : pas d'appel API, pas de matching heuristique. Si la
  référence acheteur manque, on n'invente rien.
- Idempotent : `synchroniser_*()` peuvent être appelés N fois sans dégrader.

Usage côté pipeline :
    import jointure
    jointure.synchroniser_tous_boamp(marches_boamp_dict)
    jointure.synchroniser_tous_decp(marches_decp_dict)
    stats = jointure.stats()
    print(stats)

Pour initialisation rétroactive : `python jointure_init.py`
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPERTOIRE_BASE = Path(__file__).parent
FICHIER_JOINTURE = REPERTOIRE_BASE / "data" / "jointure.json"


# ---------------------------------------------------------------------------
# Normalisation des références
# ---------------------------------------------------------------------------

def normaliser_reference(ref: Optional[str]) -> Optional[str]:
    """
    Normalise une référence acheteur pour la clé de jointure.
    - Trim
    - Majuscules
    - Supprime espaces internes et tirets surnuméraires
    - Retourne None si vide ou trop court (<5 chars : probable bruit)
    """
    if not ref or not isinstance(ref, str):
        return None
    s = ref.strip().upper()
    # Supprime espaces et points multiples, normalise les tirets
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[\.]+", "", s)
    s = re.sub(r"-+", "-", s)
    s = s.strip("-")
    if len(s) < 5:
        return None
    return s


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def charger() -> dict:
    """Charge l'index de jointure depuis disque (dict vide si absent)."""
    if not FICHIER_JOINTURE.is_file():
        return {}
    try:
        with open(FICHIER_JOINTURE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  ⚠ Erreur lecture {FICHIER_JOINTURE} : {e}", file=sys.stderr)
        return {}


def ecrire(index: dict):
    """Écrit l'index sur disque (écriture atomique via fichier temporaire)."""
    FICHIER_JOINTURE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FICHIER_JOINTURE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    tmp.replace(FICHIER_JOINTURE)


# ---------------------------------------------------------------------------
# Extraction des refs depuis un marché
# ---------------------------------------------------------------------------

def _ref_depuis_boamp(marche: dict) -> Optional[str]:
    """Pioche la référence acheteur d'un marché BOAMP."""
    return normaliser_reference(marche.get("reference_ft")
                                  or marche.get("reference_acheteur"))


def _ref_depuis_decp(marche: dict) -> Optional[str]:
    """Pioche la référence acheteur d'un marché DECP."""
    return normaliser_reference(marche.get("reference_acheteur"))


def _bloc_boamp(marche: dict) -> dict:
    """Extrait le sous-dict BOAMP à stocker dans la jointure."""
    return {
        "id": marche.get("id"),
        "idweb": marche.get("reference_externe"),
        "date_publication": marche.get("date_publication"),
        "date_limite_depot": marche.get("date_limite_depot"),
        "titre": (marche.get("titre") or marche.get("objet") or "")[:200],
        "perimetre_geographique": marche.get("perimetre_geographique"),
        "acheteur_nom": marche.get("acheteur_nom"),
        "categorie_metier": marche.get("categorie_metier"),
    }


def _bloc_decp(marche: dict) -> dict:
    """Extrait le sous-dict DECP à stocker dans la jointure."""
    return {
        "id": marche.get("id"),
        "reference_externe": marche.get("reference_externe"),
        "date_notification": marche.get("date_notification"),
        "duree_mois": marche.get("duree_mois"),
        "montant_eur": marche.get("montant_eur"),
        "titulaire_siret": marche.get("titulaire_siret"),
        "titulaire_nom": marche.get("titulaire_nom"),
        "categorie_metier": marche.get("categorie_metier"),
    }


def _etat(entree: dict) -> str:
    has_boamp = bool(entree.get("boamp"))
    has_decp = bool(entree.get("decp"))
    if has_boamp and has_decp:
        return "complet"
    if has_boamp:
        return "boamp_seul"
    if has_decp:
        return "decp_seul"
    return "vide"


# ---------------------------------------------------------------------------
# Synchronisation unitaire
# ---------------------------------------------------------------------------

def synchroniser_boamp(marche_boamp: dict,
                        index: Optional[dict] = None,
                        persister: bool = True) -> Optional[str]:
    """
    Insère ou met à jour l'entrée de jointure correspondant à un marché BOAMP.

    Args:
        marche_boamp: dict du marché BOAMP (depuis marches.json)
        index: index pré-chargé (sinon chargé depuis disque)
        persister: True pour écrire sur disque immédiatement

    Returns:
        La clé de jointure (ref normalisée) si insertion réussie, None sinon.
    """
    ref = _ref_depuis_boamp(marche_boamp)
    if not ref:
        return None

    if index is None:
        index = charger()
        owned = True
    else:
        owned = False

    if ref in index:
        entree = index[ref]
        entree["boamp"] = _bloc_boamp(marche_boamp)
        entree["maj_le"] = _maintenant()
    else:
        entree = {
            "reference_acheteur": ref,
            "siret_acheteur": (marche_boamp.get("acheteur_id") or "").strip()
                                or None,
            "boamp": _bloc_boamp(marche_boamp),
            "decp": None,
            "cree_le": _maintenant(),
            "maj_le": _maintenant(),
        }
        index[ref] = entree

    entree["etat"] = _etat(entree)

    if owned and persister:
        ecrire(index)
    return ref


def synchroniser_decp(marche_decp: dict,
                       index: Optional[dict] = None,
                       persister: bool = True) -> Optional[str]:
    """
    Insère ou met à jour l'entrée de jointure correspondant à un marché DECP.
    Mêmes mécaniques que synchroniser_boamp().
    """
    ref = _ref_depuis_decp(marche_decp)
    if not ref:
        return None

    if index is None:
        index = charger()
        owned = True
    else:
        owned = False

    if ref in index:
        entree = index[ref]
        entree["decp"] = _bloc_decp(marche_decp)
        # Si on a un SIRET acheteur ici et pas en boamp, on remplit
        if not entree.get("siret_acheteur"):
            entree["siret_acheteur"] = (marche_decp.get("acheteur_id")
                                          or "").strip() or None
        entree["maj_le"] = _maintenant()
    else:
        entree = {
            "reference_acheteur": ref,
            "siret_acheteur": (marche_decp.get("acheteur_id") or "").strip()
                                or None,
            "boamp": None,
            "decp": _bloc_decp(marche_decp),
            "cree_le": _maintenant(),
            "maj_le": _maintenant(),
        }
        index[ref] = entree

    entree["etat"] = _etat(entree)

    if owned and persister:
        ecrire(index)
    return ref


# ---------------------------------------------------------------------------
# Synchronisation en masse
# ---------------------------------------------------------------------------

def synchroniser_tous_boamp(marches_boamp: dict,
                              verbose: bool = False) -> dict:
    """
    Synchronise tout le dict marches BOAMP.
    Retourne le dict de stats.
    """
    index = charger()
    nb_avec_ref = 0
    nb_sans_ref = 0
    for marche in marches_boamp.values():
        result = synchroniser_boamp(marche, index=index, persister=False)
        if result:
            nb_avec_ref += 1
        else:
            nb_sans_ref += 1
    ecrire(index)
    if verbose:
        print(f"  [Jointure] BOAMP : {nb_avec_ref} avec ref / "
              f"{nb_sans_ref} sans ref")
    return {"avec_ref": nb_avec_ref, "sans_ref": nb_sans_ref}


def synchroniser_tous_decp(marches_decp: dict,
                            verbose: bool = False) -> dict:
    """Synchronise tout le dict marches DECP."""
    index = charger()
    nb_avec_ref = 0
    nb_sans_ref = 0
    for marche in marches_decp.values():
        result = synchroniser_decp(marche, index=index, persister=False)
        if result:
            nb_avec_ref += 1
        else:
            nb_sans_ref += 1
    ecrire(index)
    if verbose:
        print(f"  [Jointure] DECP : {nb_avec_ref} avec ref / "
              f"{nb_sans_ref} sans ref")
    return {"avec_ref": nb_avec_ref, "sans_ref": nb_sans_ref}


# ---------------------------------------------------------------------------
# Lecture / statistiques
# ---------------------------------------------------------------------------

def stats(index: Optional[dict] = None) -> dict:
    """Retourne les compteurs d'état de la jointure."""
    if index is None:
        index = charger()
    s = {"total": len(index), "complet": 0, "boamp_seul": 0,
         "decp_seul": 0, "vide": 0}
    for entree in index.values():
        etat = entree.get("etat") or _etat(entree)
        s[etat] = s.get(etat, 0) + 1
    return s


def lister_paires_completes(index: Optional[dict] = None) -> list:
    """Retourne les entrées en état 'complet' (BOAMP + DECP appariés)."""
    if index is None:
        index = charger()
    return [entree for entree in index.values()
            if entree.get("etat") == "complet"]


def chercher_par_ref(ref: str, index: Optional[dict] = None) -> Optional[dict]:
    """Cherche une entrée par référence acheteur (avec normalisation)."""
    if index is None:
        index = charger()
    return index.get(normaliser_reference(ref))


# ---------------------------------------------------------------------------
# CLI minimal pour debug
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("  Jointure BOAMP ↔ DECP — état actuel")
    print("=" * 70)
    s = stats()
    print(f"  Entrées totales       : {s['total']}")
    print(f"    complètes (boamp+decp): {s['complet']}")
    print(f"    BOAMP seul          : {s['boamp_seul']}")
    print(f"    DECP seul           : {s['decp_seul']}")
    if s.get("vide"):
        print(f"    vides (bug)         : {s['vide']}")

    if s["complet"] > 0:
        print()
        print("  Aperçu des paires complètes :")
        for entree in lister_paires_completes()[:5]:
            ref = entree.get("reference_acheteur")
            b = entree.get("boamp") or {}
            d = entree.get("decp") or {}
            print(f"    {ref}")
            print(f"      BOAMP {b.get('id')}  · publié {b.get('date_publication')}")
            print(f"      DECP  {d.get('id')}  · notifié {d.get('date_notification')}  · {d.get('montant_eur')} €  · {d.get('titulaire_nom')}")
