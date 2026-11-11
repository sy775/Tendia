# -*- coding: utf-8 -*-
"""
tendia.ui.bloc_decision
-----------------------
Bloc de décision en tête de la fiche marché (chantier 1b, objectif 3 étape 4) :
verdict + score, « ce qui vous manque », date limite, bouton « Préparer le
dossier » (inactif jusqu'au chantier 3).

Mise en forme uniquement : les données viennent de l'évaluation matching déjà
calculée par la route (motifs) et du brief existant. Aucun calcul de score,
aucun appel LLM.
"""
from datetime import date
from typing import Optional

from tendia.core.etat_marche import date_cloture, est_attribution, est_clos

LIBELLES_VERDICT = {
    "tres_pertinent": "Très pertinent",
    "pertinent": "Pertinent",
    "a_verifier": "À vérifier",
    "non_pertinent": "Non pertinent",
    "non_classe": "À classer",
    "clos": "Clos",
}

# critère matching → (ce qui manque, champ du profil à renseigner, section du profil)
# Sections = data-section des panneaux de templates/profil/edit.html.
_CRITERES = {
    "geographie": ("Zone d'intervention", "Zones d'intervention", "zones"),
    "capacite": ("Capacité financière", "Chiffre d'affaires et effectifs", "capacite"),
    "preset_compatibilite": ("Secteur d'activité", "Secteurs couverts", "activite"),
    "domaines_couverts": ("Domaine d'activité", "Domaines couverts", "activite"),
    "thematique": ("Mots-clés métier", "Mots-clés", "activite"),
    "btp_qualibat": ("Qualification Qualibat", "Qualifications Qualibat", "sect-btp"),
    "btp_rge": ("Certification RGE", "Certifications RGE", "sect-btp"),
    "btp_amiante": ("Certification amiante", "Certification amiante (SS3 / SS4)", "sect-btp"),
    "btp_corps_metier": ("Corps d'état", "Corps de métier", "sect-btp"),
    "btp_types_ouvrages": ("Type d'ouvrage", "Types d'ouvrages", "sect-btp"),
    "btp_capacite_chantier": ("Capacité chantier", "Capacité chantiers", "sect-btp"),
    "ing_opqibi": ("Qualification OPQIBI", "Qualifications OPQIBI", "sect-ing"),
    "ing_typologies": ("Typologie de mission", "Typologies couvertes", "sect-ing"),
    "ing_competences": ("Compétences exigées", "Compétences spécialisées", "sect-ing"),
    "ing_types_ouvrages": ("Type d'ouvrage", "Types d'ouvrages étudiés", "sect-ing"),
    "ing_capacite_etudes": ("Capacité d'études", "Capacité d'études", "sect-ing"),
    "enr_technologie": ("Technologie", "Technologies maîtrisées", "sect-enr"),
    "enr_prestation": ("Type de prestation", "Types de prestations", "sect-enr"),
    "enr_segment": ("Segment de marché", "Segments", "sect-enr"),
    "qualiopi": ("Certification Qualiopi", "Certifications", "activite"),
    "categorie": ("Catégorie de prestation", "Secteurs couverts", "activite"),
    # Contrainte du marché, pas un champ du profil : affichée sans lien.
    "allotissement": ("Offre globale obligatoire", None, None),
}
MAX_MANQUES = 5

_MOIS = ["", "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
         "août", "septembre", "octobre", "novembre", "décembre"]


def _date_longue(d: Optional[date]) -> Optional[str]:
    return f"{d.day} {_MOIS[d.month]} {d.year}" if d else None


def _date_iso(valeur) -> Optional[date]:
    try:
        return date.fromisoformat(str(valeur)[:10]) if valeur and len(str(valeur)) >= 10 else None
    except ValueError:
        return None


def manques(evaluation: Optional[dict], url_profil: Optional[str]) -> list:
    """Motifs négatifs du matching → [{manque, detail, champ, url}], les plus
    pénalisants d'abord. `url` pointe sur la section du profil à compléter."""
    motifs = (evaluation or {}).get("motifs") or []
    negatifs = [m for m in motifs if m.get("satisfait") is False]
    negatifs.sort(key=lambda m: m.get("points") or 0)
    out = []
    for m in negatifs[:MAX_MANQUES]:
        critere = m.get("critere") or ""
        if critere.startswith("sectoriel_"):
            defaut = ("Critère sectoriel", "Profil sectoriel", "activite")
        else:
            defaut = (critere.replace("_", " ").capitalize(), "Profil", "activite")
        manque, champ, section = _CRITERES.get(critere, defaut)
        out.append({
            "critere": critere,
            "manque": manque,
            "detail": (m.get("commentaire") or "").strip(),
            "points": m.get("points") or 0,
            "champ": champ,
            "url": (f"{url_profil}#{section}" if (url_profil and section) else None),
        })
    return out


def construire(marche: dict, evaluation: Optional[dict], brief: Optional[dict],
               url_profil: Optional[str], aujourdhui: Optional[date] = None) -> dict:
    """Données du bloc de décision. `url_profil` : page d'édition du profil
    actif (None sans profil modifiable)."""
    aujourdhui = aujourdhui or date.today()
    clos = est_clos(marche, aujourdhui)
    verdict = (evaluation or {}).get("verdict")
    if clos:
        etat = "clos"
    elif verdict:
        etat = verdict
    else:
        etat = None  # pas de profil actif : pas de verdict

    limite = _date_iso(marche.get("date_limite_depot")) or _date_iso(
        ((brief or {}).get("calendrier") or {}).get("date_limite_offres"))
    jours = (limite - aujourdhui).days if limite else None

    return {
        "etat": etat,
        "libelle": LIBELLES_VERDICT.get(etat, "Pas de profil actif") if etat else "Pas de profil actif",
        "score": (evaluation or {}).get("score") if etat not in ("clos", "non_classe", None) else None,
        "clos": clos,
        "clos_attribution": clos and est_attribution(marche),
        "date_cloture": _date_longue(date_cloture(marche, aujourdhui)) if clos else None,
        "date_limite": _date_longue(limite),
        "jours_restants": jours if (jours is not None and not clos) else None,
        "manques": [] if (clos or etat in ("non_classe", None)) else manques(evaluation, url_profil),
        "url_profil": url_profil,
    }
