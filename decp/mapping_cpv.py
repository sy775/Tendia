"""
decp/mapping_cpv.py — mapping CPV → preset Tendia (Sprint DECP 2, niveau 1).

Stratégie (validée Étape 0) :
- préfixe 2 chiffres haute confiance : 45→btp, 71→ingenierie, 72→it, 80→formation,
  48→it (progiciels) ;
- ~35 divisions hors-périmètre évidentes ;
- sous-codes EXACTS pour EnR (solaire/géothermie, centrales, ingénierie énergie) et
  conseil_rd (R&D 731/732, conseil/audit 794/79212) — car la division seule est ambiguë ;
- 09 / 50 / 79 (hors sous-codes mappés) → AMBIGUS → LLM ;
- 00000000 (CPV bidon) → traité par le classifier (objet vide → hors_perimetre, sinon LLM).

`classer_par_cpv(cpv) -> (preset|None, source)`. preset None = à envoyer au LLM.
"""
from typing import Optional, Tuple

# Quelques codes exacts (source 'cpv_exact', confiance 1.0) — le gros est couvert par préfixe.
MAPPING_CPV_EXACT = {
    "45000000": "btp", "71000000": "ingenierie", "72000000": "it",
    "80000000": "formation", "48000000": "it", "73000000": "conseil_rd",
}

# Sous-codes ciblés (préfixe 3 à 5 chiffres) — testés AVANT les ambigus et le préfixe 2.
MAPPING_CPV_SOUS_CODES = {
    # EnR
    "0933": "enr",     # énergie solaire / géothermie (09330000–09339999)
    "45251": "enr",    # construction de centrales (électricité/eau)
    "71314": "enr",    # ingénierie de l'énergie et associée
    # Conseil & R&D
    "731": "conseil_rd",   # R&D et services connexes
    "732": "conseil_rd",
    "794": "conseil_rd",   # conseil en gestion / management / évaluation
    "79212": "conseil_rd", # services d'audit
}

# Préfixe 2 chiffres → preset (haute confiance).
MAPPING_CPV_PREFIXE = {
    "45": "btp", "71": "ingenierie", "72": "it", "80": "formation", "48": "it",
}

# Divisions explicitement ambiguës → LLM (préfixe 2).
CPV_AMBIGUS_PREFIXE = {"09", "50", "79"}

# Divisions explicitement hors périmètre Tendia.
CPV_HORS_PERIMETRE_PREFIXE = {
    "03", "14", "15", "16", "18", "19", "22", "24", "30", "31", "32", "33",
    "34", "35", "37", "38", "39", "41", "42", "43", "44", "51", "55", "60",
    "63", "64", "65", "66", "70", "75", "76", "77", "85", "90", "92", "98",
}


def _digits(cpv) -> str:
    return "".join(c for c in str(cpv or "") if c.isdigit())[:8]


def classer_par_cpv(cpv_principal: str) -> Tuple[Optional[str], str]:
    """
    Retourne (preset, source_decision).
    source ∈ cpv_exact | cpv_prefixe_5 | cpv_prefixe_4 | cpv_prefixe_3 |
             cpv_prefixe_2 | cpv_ambigu_explicite | cpv_hors_perimetre | inconnu
    preset None → à envoyer au LLM (ambigu ou inconnu).
    """
    c = _digits(cpv_principal)
    if not c:
        return None, "inconnu"
    # 1. correspondance exacte
    if c in MAPPING_CPV_EXACT:
        return MAPPING_CPV_EXACT[c], "cpv_exact"
    # 2. sous-codes ciblés (du plus précis au plus court) — avant ambigus & préfixe 2
    for L in (5, 4, 3):
        if c[:L] in MAPPING_CPV_SOUS_CODES:
            return MAPPING_CPV_SOUS_CODES[c[:L]], f"cpv_prefixe_{L}"
    # 3. ambigu explicite (09/50/79 hors sous-codes mappés ci-dessus) → LLM
    if c[:2] in CPV_AMBIGUS_PREFIXE:
        return None, "cpv_ambigu_explicite"
    # 4. préfixe 2 preset
    if c[:2] in MAPPING_CPV_PREFIXE:
        return MAPPING_CPV_PREFIXE[c[:2]], "cpv_prefixe_2"
    # 5. hors périmètre explicite
    if c[:2] in CPV_HORS_PERIMETRE_PREFIXE:
        return "hors_perimetre", "cpv_hors_perimetre"
    # 6. inconnu → LLM
    return None, "inconnu"
