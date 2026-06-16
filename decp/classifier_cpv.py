"""
decp/classifier_cpv.py — classification niveau 1 (CPV-only, 0 €).

Applique `mapping_cpv.classer_par_cpv` à chaque marché DECP et produit la ligne
d'insertion pour `decp_classification`. preset_principal NULL ⇒ marché à envoyer
au LLM (niveau 2).
"""
import re
from datetime import datetime, timezone

from decp.mapping_cpv import classer_par_cpv, _digits

CONFIANCE = {
    "cpv_exact": 1.0,
    "cpv_prefixe_5": 0.9, "cpv_prefixe_4": 0.9, "cpv_prefixe_3": 0.9,
    "cpv_prefixe_2": 0.75,
    "cpv_hors_perimetre": 1.0,
    "cpv_donnees_insuffisantes": 0.7,
    "cpv_moe_override": 0.85,  # override texte MOE sur CPV travaux (pattern 3)
}

# Patterns texte indiquant un marché de maîtrise d'œuvre (raffinement pattern 3).
# Les acheteurs collent souvent un CPV travaux (45xxx) sur une MOE → ingenierie.
# Classe d'apostrophes exhaustive : ASCII + smart quotes + prime + accents (raffinement
# v2 — les extraits DECP mélangent U+0027 / U+2019 / U+2018 selon la source).
_APOSTROPHE_CLASS = r"['‘’‛′`´]"
PATTERNS_MOE = re.compile(
    rf"(ma[iî]tris\w*\s+d\s*{_APOSTROPHE_CLASS}?\s*(?:œuvre|oeuvre)"  # maîtrise/maitrise d'œuvre
    rf"|\bmo[eE]\b"                                                    # MOE / moe
    rf"|mission\s+de\s+conception"
    rf"|mission\s+de\s+ma[iî]tris\w*)",
    re.IGNORECASE,
)


def _row(decp_id, preset, source, confiance):
    return {
        "decp_id": decp_id,
        "preset_principal": preset,      # None ⇒ LLM
        "preset_secondaire": None,
        "source": source,                # détaille la décision (cpv_exact, cpv_ambigu_explicite…)
        "confiance": confiance,
        "classified_at": datetime.now(timezone.utc).isoformat(),
    }


def classer_marche_cpv(marche: dict) -> dict:
    decp_id = marche.get("id")
    cpv = marche.get("cpv_principal")
    objet = (marche.get("objet") or "").strip()
    digits = _digits(cpv)

    # Cas spécial CPV bidon 00000000 (ou absent) : règle binaire.
    if not digits or digits == "00000000":
        if len(objet) < 10:
            return _row(decp_id, "hors_perimetre", "cpv_donnees_insuffisantes", 0.7)
        return _row(decp_id, None, "inconnu", None)  # objet exploitable → LLM

    # Règle texte MOE prioritaire : objet « maîtrise d'œuvre » + CPV travaux (45xxx)
    # → ingenierie (override le mapping CPV qui dirait btp). Pattern 3 post-validation.
    if digits.startswith("45") and PATTERNS_MOE.search(objet):
        return _row(decp_id, "ingenierie", "cpv_moe_override", 0.85)

    preset, source = classer_par_cpv(cpv)
    if preset is not None:
        return _row(decp_id, preset, source, CONFIANCE.get(source, 0.75))

    # Échec sur le principal → tenter les CPV secondaires (confiance dégradée ×0.8).
    sec = marche.get("cpv_secondaires")
    if sec:
        codes = sec if isinstance(sec, list) else [s for s in str(sec).replace(",", " ").split() if s]
        for s in codes:
            p, src = classer_par_cpv(s)
            if p is not None:
                return _row(decp_id, p, "cpv_secondaire", round(CONFIANCE.get(src, 0.75) * 0.8, 3))

    # Ambigu / inconnu → niveau 2 (LLM).
    return _row(decp_id, None, source, None)
