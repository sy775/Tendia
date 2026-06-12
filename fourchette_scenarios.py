"""
fourchette_scenarios.py
-----------------------
Construit une fourchette montant total en 3 scénarios (bas / réaliste / haut).

**Principe** : seule la variable INCERTAINE pour le candidat est le taux
d'exécution du volume. Le prix unitaire est posé par le candidat (= choix
maîtrisé, pas une incertitude). Donc les 3 scénarios font varier UNIQUEMENT
le taux d'exécution, à prix unitaire médian fixé.

Pivot = `(min_eur + max_eur) / 2` ≈ prix unitaire médian × volume max théorique

Les 3 scénarios :
    Bas      = pivot × 50%   (faible remplissage / consommation partielle)
    Réaliste = pivot × 75%   (remplissage nominal, observation empirique AC FT)
    Haut     = pivot × 100%  (volume max contractuel pleinement consommé)

Chaque scénario expose explicitement le **volume effectif** correspondant
(nombre de sessions, bénéficiaires, heures…) pour que l'utilisateur voie
exactement le combien sur lequel on raisonne. Le volume max est déduit en
priorité de `max_eur / pu.max_eur` (cohérent par construction de la
calibration LLM), sinon de `brief.volumes.nb_beneficiaires_total`.
"""

from typing import Optional
import re


# Taux d'exécution typiques d'un accord-cadre FT reconductible
TAUX_EXEC_BAS = 0.50
TAUX_EXEC_REALISTE = 0.75
TAUX_EXEC_HAUT = 1.00


def _detecter_reconductions(commentaire_volumes: str) -> Optional[int]:
    if not commentaire_volumes:
        return None
    txt = commentaire_volumes.lower()
    m = re.search(r"reconductible\s+(\d+)\s+fois", txt)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s+reconductions?", txt)
    if m:
        return int(m.group(1))
    return None


def _format_volume(n: float, unite: str) -> str:
    """Formate un nombre de volume avec son unité, en arrondissant intelligemment."""
    n_arrondi = int(round(n))
    if not unite:
        return f"{n_arrondi}"
    # Pluriels simples
    u = unite.strip()
    if n_arrondi >= 2 and not u.endswith("s") and u not in ("heure", "jour"):
        # cas standard : "20 sessions", "30 bénéficiaires"
        if u.endswith("e"):
            return f"{n_arrondi} {u}s"
        return f"{n_arrondi} {u}s"
    if u in ("heure", "jour") and n_arrondi >= 2:
        return f"{n_arrondi} {u}s"
    return f"{n_arrondi} {u}"


def _deduire_volume_max(min_eur: float, max_eur: float, pu: dict,
                         brief: Optional[dict]) -> Optional[float]:
    """Déduit le volume max théorique du marché. Priorité :
    1. max_eur / pu.max_eur  (cohérent par construction de la calibration)
    2. brief.volumes.nb_beneficiaires_total
    """
    pu_max = pu.get("max_eur") if pu else None
    pu_min = pu.get("min_eur") if pu else None
    if pu_max and pu_max > 0 and max_eur:
        v1 = max_eur / pu_max
        # Validation croisée avec min : doit être cohérent
        if pu_min and min_eur:
            v2 = min_eur / pu_min
            # Si les deux convergent à <10% près, on a une déduction fiable
            if v2 > 0 and abs(v1 - v2) / max(v1, v2) < 0.1:
                return v1
        # Sinon on retient quand même la déduction max
        return v1
    # Fallback brief
    if brief:
        v = (brief.get("volumes") or {}).get("nb_beneficiaires_total")
        if v and v > 0:
            return float(v)
    return None


def construire_scenarios(calibration: dict, brief: Optional[dict] = None) -> Optional[dict]:
    """Retourne {bas, realiste, haut} avec montant_eur, hypothese, volume_effectif."""
    if not calibration:
        return None
    ft = calibration.get("fourchette_marche_total_estimee") or {}
    if not isinstance(ft, dict):
        return None

    # Cas 1 : scénarios explicites du LLM
    scenarios_llm = ft.get("scenarios")
    if isinstance(scenarios_llm, dict) and all(
        scenarios_llm.get(k) for k in ("bas", "realiste", "haut")
    ):
        return scenarios_llm

    # Cas 2 : calcul depuis min/max
    min_eur = ft.get("min_eur")
    max_eur = ft.get("max_eur")
    if not (min_eur and max_eur and min_eur > 0 and max_eur > 0):
        return None

    pu = calibration.get("prix_unitaire_estime") or {}
    pu_med = pu.get("mediane_eur") or pu.get("mediane")
    unite = (pu.get("unite") or "unité").strip()

    nb_benef = ((brief or {}).get("volumes") or {}).get("nb_beneficiaires_total")
    commentaire = ((brief or {}).get("volumes") or {}).get("commentaire_volumes", "")
    nb_reconductions = _detecter_reconductions(commentaire)

    # Pivot et 3 scénarios
    montant_pivot = (min_eur + max_eur) / 2
    montant_bas = int(round(montant_pivot * TAUX_EXEC_BAS))
    montant_realiste = int(round(montant_pivot * TAUX_EXEC_REALISTE))
    montant_haut = int(round(montant_pivot * TAUX_EXEC_HAUT))

    # Volume max théorique → volumes effectifs par scénario
    volume_max = _deduire_volume_max(min_eur, max_eur, pu, brief)
    vol_bas = volume_max * TAUX_EXEC_BAS if volume_max else None
    vol_realiste = volume_max * TAUX_EXEC_REALISTE if volume_max else None
    vol_haut = volume_max if volume_max else None

    # Hypothèses textuelles avec volumes effectifs explicites
    prix_ref = f"{pu_med} €/{unite}" if pu_med else f"prix médian/{unite}"

    if vol_bas is not None:
        h_bas = (
            f"{_format_volume(vol_bas, unite)} effectives "
            f"(soit 50% du max théorique de {_format_volume(volume_max, unite)}) "
            f"× {prix_ref}. Hypothèse : marché peu sollicité, reconductions non activées."
        )
    else:
        h_bas = (
            f"50% du volume max théorique × {prix_ref}. "
            f"Hypothèse : marché peu sollicité, reconductions non activées."
        )

    if vol_realiste is not None:
        reconductions_txt = ""
        if nb_reconductions:
            reconductions_txt = f" Période ferme + une partie des {nb_reconductions} reconductions."
        h_realiste = (
            f"{_format_volume(vol_realiste, unite)} effectives "
            f"(soit 75% du max théorique) × {prix_ref}.{reconductions_txt}"
        )
    else:
        h_realiste = f"75% du volume max théorique × {prix_ref}."

    if vol_haut is not None:
        reconductions_txt = ""
        if nb_reconductions:
            reconductions_txt = f", toutes les {nb_reconductions} reconductions activées"
        h_haut = (
            f"{_format_volume(vol_haut, unite)} pleinement consommées "
            f"(100% du max contractuel{reconductions_txt}) × {prix_ref}."
        )
    else:
        h_haut = f"Volume max contractuel pleinement consommé × {prix_ref}."

    return {
        "bas": {
            "montant_eur": montant_bas,
            "hypothese": h_bas,
            "volume_effectif": vol_bas,
            "volume_max_theorique": volume_max,
            "unite": unite,
            "taux_execution_pct": int(TAUX_EXEC_BAS * 100),
        },
        "realiste": {
            "montant_eur": montant_realiste,
            "hypothese": h_realiste,
            "volume_effectif": vol_realiste,
            "volume_max_theorique": volume_max,
            "unite": unite,
            "taux_execution_pct": int(TAUX_EXEC_REALISTE * 100),
        },
        "haut": {
            "montant_eur": montant_haut,
            "hypothese": h_haut,
            "volume_effectif": vol_haut,
            "volume_max_theorique": volume_max,
            "unite": unite,
            "taux_execution_pct": int(TAUX_EXEC_HAUT * 100),
        },
    }
