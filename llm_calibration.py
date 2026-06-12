"""
llm_calibration.py
------------------
Deuxième passe LLM : calibrer l'estimation prix unitaire d'un marché actif
en croisant le brief froid (extrait du DCE) avec des comparables DECP réels.

Architecture :
- Pass 1 (llm_extract.py) : LLM lit le DCE seul → brief froid, idempotent
- Pass 2 (ici)            : LLM reçoit brief synthétique + N comparables DECP
                             → estimation calibrée et sourcée

Indépendance :
- Cache disque : data/extractions_calibrees/<id>.json
- Recalculable quand la base DECP s'enrichit, sans toucher le brief
- ~0.05-0.10 $ par appel (input court, output court)

Reuse :
- Réutilise la mécanique d'authentification de llm_extract (clé API, .env)
- Mêmes patterns d'appel API et de parsing JSON
"""

import json
import re
import time
from pathlib import Path
from typing import Optional

# On délègue la mécanique de clé API à llm_extract (qui a déjà tout le code
# pour charger .env, vérifier le SDK, etc.) — pas de duplication.
import llm_extract


REPERTOIRE_BASE = Path(__file__).parent
REPERTOIRE_CALIBRATIONS = REPERTOIRE_BASE / "data" / "extractions_calibrees"
REPERTOIRE_CALIBRATIONS.mkdir(parents=True, exist_ok=True)

MODELE = "claude-sonnet-4-6"
MAX_TOKENS_REPONSE = 4000  # réponse courte, c'est juste une fourchette + analyse
N_COMPARABLES_MAX = 12     # limiter l'input pour économiser tokens

# Seuil de similarité moyenne en dessous duquel on ne calibre pas
# (les comparables ne sont pas assez proches pour être pertinents)
SEUIL_SIMILARITE_MIN = 0.35


import preset as _preset


def _construire_prompt_systeme() -> str:
    """
    Construit le prompt système calibration depuis le domaine actif.
    Sur formation_ft, équivalent strict à l'ancien PROMPT_SYSTEME Apptia.
    """
    pc = _preset.prompt_calibration()
    secteur_court = pc.get("secteur_libelle_court", "marchés publics")
    return (
        f"Tu es un expert en estimation de marchés publics {secteur_court}.\n\n"
        f"Tu calibres une fourchette de prix unitaire en croisant deux sources :\n"
        f"1. Un brief LLM extrait du DCE (volumes, durée, public cible, modalités)\n"
        f"2. Des marchés historiques DECP comparables déjà attribués, sur le même segment\n\n"
        f"Tu produis une estimation chiffrée DÉFENDABLE — pas une moyenne mécanique des\n"
        f"comparables, pas une paraphrase du brief. Une vraie estimation où chaque chiffre\n"
        f"est explicitement sourcé sur les comparables effectivement utilisés.\n\n"
        f"Tu retournes EXCLUSIVEMENT un objet JSON (pas de commentaire avant ou après,\n"
        f"pas de blocs ```)."
    )


# Backward compat
PROMPT_SYSTEME = _construire_prompt_systeme()


def _construire_prompt_utilisateur(brief_synthese: str, n_comp: int,
                                    comparables_synthese: str) -> str:
    """
    Compose le prompt utilisateur calibration en injectant les sections
    spécifiques du domaine actif (secteur_libelle_court, sections qualif
    intervenants, durée effective, coefficient complexité, re-pricing, top-down).

    Fallbacks neutres si un placeholder n'est pas défini par le domaine
    (cas d'un domaine en cours de définition).
    """
    pc = _preset.prompt_calibration()
    return PROMPT_UTILISATEUR_TEMPLATE.format(
        brief_synthese=brief_synthese,
        n_comp=n_comp,
        comparables_synthese=comparables_synthese,
        secteur_libelle_court=pc.get("secteur_libelle_court", "publics"),
        section_qualification_intervenants=pc.get(
            "section_qualification_intervenants",
            "a. **Qualification des intervenants exigée** : adapter les coûts horaires au profil métier."
        ),
        section_duree_effective=pc.get(
            "section_duree_effective",
            "b. **Volume / quantité de prestation** : extraire du DCE la grandeur principale (heures, unités, mètres) qui dimensionne le marché."
        ),
        section_coefficient_complexite=pc.get(
            "section_coefficient_complexite",
            "c. **Coefficient de complexité** : ×1.0 standard, jusqu'à ×1.5 selon contraintes spécifiques."
        ),
        section_re_pricing=pc.get(
            "section_re_pricing",
            "ÉTAPE 1bis — **DÉCOMPOSITION SI BPU NON-LINÉAIRE** : si l'unité du marché diffère de l'unité physique principale, décomposer en coûts fixes (mutualisés) + coûts variables (linéaires) et montrer le calcul."
        ),
        section_top_down=pc.get(
            "section_top_down",
            "ÉTAPE 1 — **ESTIMATION TOP-DOWN sur comparables DECP** : pour chaque comparable, diviser le montant par le volume principal connu. Si le volume est inconnu, exclure le comparable."
        ),
    )


PROMPT_UTILISATEUR_TEMPLATE = """Voici le contexte d'un marché public {secteur_libelle_court}
à estimer, et N marchés comparables historiques déjà attribués (source DECP).

=== BRIEF EXTRAIT DU DCE (faits objectifs) ===
{brief_synthese}

=== {n_comp} MARCHÉS COMPARABLES (DECP — déjà attribués) ===
{comparables_synthese}

=== TA MISSION ===

Calibre une fourchette de prix unitaire (en €/unité) en croisant DEUX méthodes.

ÉTAPE 0 (obligatoire) — **ESTIMATION BOTTOM-UP par décomposition coût**

Avant même de regarder les comparables, calcule un prix unitaire théorique
en partant des **caractéristiques de la prestation** :

{section_qualification_intervenants}

{section_duree_effective}

{section_coefficient_complexite}

d. **Calcule** : `prix_unitaire_bottom_up = coût_horaire × heures_effectives × coef_complexité`
   Donne une fourchette (borne basse hypothèses minimales, borne haute hypothèses maximales).

{section_re_pricing}

{section_top_down}

ÉTAPE 2 — **TRIANGULATION**

a. Compare la fourchette bottom-up et la médiane top-down (sur les comparables
   exploitables uniquement).
b. Si convergence (écart < 30%) : confiance haute, fourchette finale = moyenne pondérée.
c. Si divergence (> 30%) : **explicite la raison** :
   - Volumes mal estimés côté DECP ? → préfère bottom-up
   - Spécificité géographique/réglementaire des comparables ? → ajuste bottom-up
   - Évolution des taux depuis les comparables (inflation) ? → applique +5-7% par an
d. **Préfère systématiquement le raisonnement bottom-up** : il est défendable
   ligne par ligne. Le top-down est un repère, pas une vérité.

ÉTAPE 3 — **FOURCHETTE FINALE RESSERRÉE et ACTIONNABLE**

Règle stricte : `max_eur ≤ 1.5 × min_eur`.

Méthode recommandée, par ordre de priorité :
a. **IQR (50% central)** si ≥6 comparables exploitables : `min_eur` = Q1
   des prix unitaires observés, `max_eur` = Q3.
b. **±25% autour de la médiane bottom-up** si peu de comparables exploitables.
c. **±15% autour de la médiane bottom-up** si comparables incohérents
   (la fourchette est portée entièrement par le bottom-up).

**`mediane_eur` est OBLIGATOIRE** : c'est la valeur la plus défendable.

ÉTAPE 3bis — **FOURCHETTE MARCHÉ TOTAL : PRIX FIGÉ, VARIANCE SUR VOLUMES**

RÈGLE CRITIQUE : pour calculer `fourchette_marche_total_estimee`, NE PAS
combiner variance de prix ET variance de volumes. Cela produit des
fourchettes inexploitables (rapport haut/bas > 5x).

Le prix unitaire min/max reste dans `prix_unitaire_estime.min_eur/max_eur`
pour l'analyse, mais le total marché se calcule UNIQUEMENT avec
`mediane_eur`. La fourchette du total reflète l'incertitude sur les volumes,
la charge d'exécution et la durée — pas sur le prix.

- **bas** : prix MÉDIAN × volumes nominaux × charge 80% × période ferme seule
- **realiste** : prix MÉDIAN × volumes nominaux × charge 85% × période ferme + reconductions probables (50% du potentiel)
- **haut** : prix MÉDIAN × volumes maximaux contractuels × charge 100% × toutes reconductions

Objectif : rapport haut/bas ≤ 3x. Si tu obtiens plus de 3x, c'est que tu fais
varier le prix — corrige.

ÉTAPE 4 — **CONFIANCE**
- "haute" : ≥6 comparables exploitables avec volume connu, convergence bottom-up/top-down
- "moyenne" : 4-6 comparables OU divergence bottom-up/top-down modérée mais explicable
- "faible" : <4 comparables exploitables, OU divergence non explicable, OU
  bottom-up impossible (qualification intervenants inconnue)

RETOURNE EXACTEMENT cette structure JSON :

{{
  "prix_unitaire_estime": {{
    "unite": "parcours | heure-stagiaire | journee | session | beneficiaire | autre",
    "mediane_eur": 1450,
    "min_eur": 1200,
    "max_eur": 1700,
    "methode_fourchette": "IQR (Q1-Q3 sur 8 marchés) | ±25% mediane bottom-up | ±15% mediane",
    "bottom_up": {{
      "qualification_intervenants": "BAC+3 + 3 ans d'expérience interculturel",
      "cout_horaire_retenu_eur": "45-60 €/h",
      "heures_effectives_par_beneficiaire": "30-40h effectives sur 90 jours calendaires",
      "coef_complexite": "1.20 (public allophone QPV)",
      "calcul": "Décomposition COMPLÈTE et MATHÉMATIQUE — pas d'ajustement opaque. Si l'unité est le bénéficiaire : (45-60 €/h) × (30-40h) × 1.20 = 1 620 € – 2 880 €. Si l'unité est la session de N bénéficiaires : 1. coûts fixes/session = heures_collectives × taux + logistique + coordination ; 2. coût variable/bénéf = heures_individuelles × taux × coef ; 3. total session = fixes + N × variable + marge 15-25%. Donne TOUS les chiffres intermédiaires.",
      "fourchette_eur": "1 620 – 2 880"
    }},
    "unit_repricing": {{
      "_commentaire": "Bloc OBLIGATOIRE si l'unité du BPU n'est pas le bénéficiaire. Omettre sinon.",
      "unite_marche": "session de 8-12 bénéficiaires",
      "couts_fixes_par_session_eur": {{
        "encadrement_collectif": 660,
        "logistique": 500,
        "coordination_reporting": 300,
        "total_fixes": 1460
      }},
      "cout_variable_par_beneficiaire_eur": 440,
      "calcul_session_type": "Session de 10 bénéficiaires : 1 460 + 10 × 440 = 5 860 € HT, marge 15-25% appliquée → 6 740 € – 7 325 € par session",
      "fourchette_session_eur": "6 740 – 7 325"
    }},
    "top_down": {{
      "n_comparables_exploitables": 5,
      "n_comparables_exclus": 3,
      "mediane_observee_eur": 1480,
      "q1_eur": 1200,
      "q3_eur": 1750,
      "commentaire": "Volumes connus pour 5 comparables sur 8. Médiane cohérente avec la borne basse du bottom-up."
    }},
    "triangulation": "Le bottom-up suggère 1620-2880, le top-down observe 1200-1750. La divergence vers le bas du top-down s'explique par : les comparables sont des accords-cadres anciens (2023-2024) avant l'inflation, et les volumes incluent probablement des bénéficiaires entrés en parcours sans complétion (qui réduisent le prix unitaire moyen). Médiane finale retenue : 1450 €/bénéficiaire, légèrement sous bottom-up min pour intégrer la pression concurrentielle.",
    "hypotheses": "Synthèse en 2 phrases de la démarche complète.",
    "sources_principales": [
      {{
        "id_decp": "DECP-XXXX",
        "titulaire": "...",
        "annee": 2025,
        "prix_unitaire_calcule_eur": 1500,
        "raisonnement": "Très proche : même région, même public, volumes comparables. Référence centrale du calcul."
      }}
    ],
    "ajustements_appliques": "Inflation 2024-2026 estimée à +6%. Marché actif sur zone urbaine donc +5% vs comparable rural. Total ajustement : ~+11% sur la médiane brute observée.",
    "confiance": "haute | moyenne | faible",
    "limites": "Mentionne explicitement les biais ou angles morts : peu de comparables sur la région exacte, dispersion inhabituelle, etc."
  }},
  "fourchette_marche_total_estimee": {{
    "min_eur": 196000,
    "max_eur": 374500,
    "calcul": "PRIX FIGÉ À LA MÉDIANE × volumes variables. Ex : 1 750 €/parcours (médiane) × volumes des 3 scénarios = 196 000-374 500 €.",
    "scenarios": {{
      "bas": {{
        "montant_eur": 196000,
        "hypothese": "Scénario prudent : prix MÉDIAN × volumes nominaux × période ferme uniquement × charge 80%. Ex : 1 750 € × 140 × 0.80 × 1 an = 196 000 €."
      }},
      "realiste": {{
        "montant_eur": 297500,
        "hypothese": "Scénario médian : prix MÉDIAN × volumes nominaux × période ferme + reconductions probables (1.5 an en moyenne) × charge 85%. Ex : 1 750 € × 140 × 0.85 × 1.43 ≈ 297 500 €."
      }},
      "haut": {{
        "montant_eur": 374500,
        "hypothese": "Scénario plafond : prix MÉDIAN × volumes max × toutes reconductions × charge 100%. Ex : 1 750 € × 140 × 1.0 × ... = 374 500 € (durée totale 1.53 an équivalent plein)."
      }}
    }}
  }},
  "comparables_exclus": [
    {{"id_decp": "DECP-YYYY", "raison": "Montant aberrant (10x médiane), probablement accord-cadre national mal classifié."}}
  ]
}}

Si la calibration est impossible (comparables trop hétérogènes, données insuffisantes),
retourne ce JSON minimal :
{{
  "prix_unitaire_estime": null,
  "fourchette_marche_total_estimee": null,
  "calibration_impossible_raison": "Explique pourquoi en 1-2 phrases"
}}"""


# ---------------------------------------------------------------------------
# Préparation des données d'entrée (résumé compact pour le LLM)
# ---------------------------------------------------------------------------

def _synthese_brief(brief: dict) -> str:
    """Extrait du brief tous les éléments qualitatifs utiles à la calibration.

    On passe TOUT ce qui détermine le coût réel d'une heure de prestation :
    - Qualification des intervenants exigée (BAC+3, BAC+5, certifications…) → coût horaire
    - Caractéristiques du public ou du chantier → intensité / complexité
    - Volumes et durées effectives → quantité d'heures à produire
    - Points différenciants attendus → niveau d'exigence technique

    Sans ce contexte qualitatif, le LLM se rabat sur du top-down arbitraire
    (division du montant comparable par un volume reconstitué cible-pondéré).

    PRESET-AWARE : la fonction lit DEUX schémas de brief alternativement :
      - formation : publics_cibles / volumes / modalites
      - énergie   : caracteristiques_techniques_chantier / volumes_techniques /
                    modalites_execution_chantier
    Chaque section utilise le bloc présent dans le brief, sans imposer de
    nommage figé. Pour ajouter un preset (BTP, conseil…), ajouter une branche
    dans chacune des 3 fonctions _section_*.
    """
    parts = []

    # ----- Contexte général -----
    if brief.get("synthese_marche"):
        parts.append(f"=== CONTEXTE ===\n{brief['synthese_marche']}")

    if brief.get("objet"):
        parts.append(f"Objet : {brief['objet']}")
    if brief.get("prestation_precise"):
        parts.append(f"Prestation précise : {brief['prestation_precise']}")
    if brief.get("perimetre_geographique") or brief.get("lieu_execution"):
        parts.append(f"Lieu d'exécution : "
                     f"{brief.get('perimetre_geographique') or brief.get('lieu_execution')}")

    # ----- Section sujet (public OU chantier selon preset) -----
    section_sujet = _section_sujet(brief)
    if section_sujet:
        parts.append(section_sujet)

    # ----- Section volumes (bénéficiaires OU puissance physique selon preset) -----
    section_vol = _section_volumes(brief)
    if section_vol:
        parts.append(section_vol)

    # ----- Exigences candidats (détermine coût horaire intervenants) -----
    re_ = brief.get("references_exigees") or {}
    if re_:
        ref_lines = ["=== QUALIFICATION DES INTERVENANTS EXIGÉE ==="]
        if re_.get("experience_minimale_annees"):
            ref_lines.append(f"Expérience minimum : {re_['experience_minimale_annees']} ans")
        if re_.get("secteur_experience"):
            ref_lines.append(f"Secteur d'expérience : {re_['secteur_experience']}")
        # Volume minimal de références (nouveau nom v4, avec fallback sur l'ancien)
        vol_min = re_.get("volume_min_references_similaires")
        if vol_min is None:
            vol_min = re_.get("nb_min_stagiaires_accompagnes")
        if vol_min is not None:
            unite_min = re_.get("volume_min_references_unite") or "références"
            ref_lines.append(f"Volume minimal de références : {vol_min} {unite_min}")
        if re_.get("certifications_obligatoires"):
            certs = re_["certifications_obligatoires"]
            certlibs = [c.get("libelle") if isinstance(c, dict) else str(c) for c in certs]
            ref_lines.append("Certifications : " + " ; ".join(certlibs))
        if re_.get("autres_exigences"):
            autres = re_["autres_exigences"]
            autrlibs = [a.get("libelle") if isinstance(a, dict) else str(a) for a in autres]
            ref_lines.append("Autres exigences : " + " ; ".join(autrlibs[:8]))
        if len(ref_lines) > 1:
            parts.append("\n".join(ref_lines))

    # ----- Section modalités (sites multiples, frais structurels) -----
    section_mod = _section_modalites(brief)
    if section_mod:
        parts.append(section_mod)

    # ----- Points différenciants attendus (niveau d'exigence technique) -----
    diffs = brief.get("points_differenciants_attendus") or brief.get("points_differenciants_probables") or []
    if diffs:
        diff_lines = ["=== POINTS DIFFÉRENCIANTS ATTENDUS ==="]
        for d in diffs[:6]:
            lib = d.get("libelle") if isinstance(d, dict) else str(d)
            diff_lines.append(f"- {lib}")
        parts.append("\n".join(diff_lines))

    # ----- Prix : ce que dit le DCE -----
    mc = brief.get("montant_marche") or {}
    bn = brief.get("bareme_notation") or {}
    prix_lines = []
    if mc.get("commentaire"):
        prix_lines.append(f"Ce que dit le DCE sur le prix : {mc['commentaire']}")
    if bn.get("modalite_calcul_prix"):
        prix_lines.append(f"Modalité de notation : {bn['modalite_calcul_prix']}")
    if bn.get("prix") and isinstance(bn["prix"], dict):
        if bn["prix"].get("elements_a_chiffrer"):
            elems = bn["prix"]["elements_a_chiffrer"]
            prix_lines.append("Éléments à chiffrer (bordereau de prix) : "
                              + " ; ".join(str(e) for e in elems[:6]))
    if prix_lines:
        parts.append("=== CADRAGE PRIX (DCE) ===\n" + "\n".join(prix_lines))

    return "\n\n".join(parts) if parts else "(brief vide)"


# ---------------------------------------------------------------------------
# Sections preset-aware utilisées par _synthese_brief
# ---------------------------------------------------------------------------

def _section_sujet(brief: dict) -> str:
    """
    Section décrivant le sujet du marché. Avec le brief mutualisé (Sprint 3),
    un brief peut contenir les deux schémas simultanément (ex: marché de
    formation à l'installation photovoltaïque qui matche les deux presets).
    On affiche TOUTES les sous-sections présentes, pas seulement la première.
    """
    sections = []

    # Sous-section formation
    pc = brief.get("publics_cibles") or {}
    if pc:
        lines = ["=== PUBLIC BÉNÉFICIAIRE ==="]
        if pc.get("description"):
            lines.append(pc["description"])
        if pc.get("publics_specifiques_signales"):
            lines.append("Publics spécifiques signalés : "
                          + ", ".join(pc["publics_specifiques_signales"]))
        if pc.get("criteres_eligibilite"):
            crits = pc["criteres_eligibilite"]
            critlibs = [c.get("libelle") if isinstance(c, dict) else str(c)
                        for c in crits]
            lines.append("Critères : " + " ; ".join(critlibs))
        if len(lines) > 1:
            sections.append("\n".join(lines))

    # Sous-section énergie renouvelable (peut s'afficher en plus de la formation)
    cc = brief.get("caracteristiques_techniques_chantier") or {}
    if cc:
        lines = ["=== CARACTÉRISTIQUES DU CHANTIER ==="]
        if cc.get("description"):
            lines.append(cc["description"])
        if cc.get("technologies_concernees"):
            techs = cc["technologies_concernees"]
            lines.append("Technologies : " + ", ".join(str(t) for t in techs))
        if cc.get("type_de_sites"):
            lines.append(f"Type de sites : {cc['type_de_sites']}")
        if cc.get("contraintes_site_signalees"):
            lines.append("Contraintes signalées : "
                          + ", ".join(str(c) for c in cc["contraintes_site_signalees"]))
        if cc.get("criteres_eligibilite"):
            crits = cc["criteres_eligibilite"]
            critlibs = [c.get("libelle") if isinstance(c, dict) else str(c)
                        for c in crits]
            lines.append("Critères : " + " ; ".join(critlibs))
        if len(lines) > 1:
            sections.append("\n".join(lines))

    return "\n\n".join(sections)


def _section_volumes(brief: dict) -> str:
    """
    Section décrivant les volumes physiques du marché. Avec le brief
    mutualisé, on affiche TOUTES les sections présentes (formation +
    énergie), pas seulement la première.
    """
    sections = []

    # Sous-section formation
    vol = brief.get("volumes") or {}
    if vol:
        lines = ["=== VOLUMES ==="]
        if vol.get("nb_beneficiaires_total"):
            lines.append(f"Nombre de bénéficiaires : {vol['nb_beneficiaires_total']}")
        if vol.get("nb_beneficiaires_par_lot"):
            lines.append(f"Bénéficiaires par lot : {vol['nb_beneficiaires_par_lot']}")
        if vol.get("duree_par_parcours_heures"):
            lines.append(f"Durée par parcours : {vol['duree_par_parcours_heures']} h")
        if vol.get("duree_par_parcours_semaines"):
            lines.append(f"Durée par parcours : {vol['duree_par_parcours_semaines']} semaines")
        if vol.get("duree_parcours_par_beneficiaire"):  # ancien nom toléré
            lines.append(f"Durée par bénéficiaire : {vol['duree_parcours_par_beneficiaire']}")
        if vol.get("duree_marche_mois"):
            lines.append(f"Durée totale marché : {vol['duree_marche_mois']} mois")
        if vol.get("duree_marche"):  # ancien nom toléré
            lines.append(f"Durée totale marché : {vol['duree_marche']}")
        if vol.get("intensite_accompagnement"):
            lines.append(f"Intensité accompagnement : {vol['intensite_accompagnement']}")
        if vol.get("commentaire_volumes"):
            lines.append(f"Commentaire volumes : {vol['commentaire_volumes']}")
        if len(lines) > 1:
            sections.append("\n".join(lines))

    # Sous-section énergie renouvelable
    vt = brief.get("volumes_techniques") or {}
    if vt:
        lines = ["=== VOLUMES TECHNIQUES ==="]
        if vt.get("puissance_totale_kwc"):
            lines.append(f"Puissance totale installée : {vt['puissance_totale_kwc']} kWc")
        if vt.get("puissance_par_site_kwc"):
            lines.append(f"Puissance par site : {vt['puissance_par_site_kwc']} kWc")
        if vt.get("nb_sites"):
            lines.append(f"Nombre de sites : {vt['nb_sites']}")
        if vt.get("surface_panneaux_m2"):
            lines.append(f"Surface panneaux : {vt['surface_panneaux_m2']} m²")
        if vt.get("productible_annuel_estime_mwh"):
            lines.append(f"Productible annuel estimé : {vt['productible_annuel_estime_mwh']} MWh")
        if vt.get("duree_marche_mois"):
            lines.append(f"Durée totale marché : {vt['duree_marche_mois']} mois")
        if vt.get("duree_maintenance_om_annees"):
            lines.append(f"Durée maintenance O&M : {vt['duree_maintenance_om_annees']} ans")
        if vt.get("commentaire_volumes"):
            lines.append(f"Commentaire volumes : {vt['commentaire_volumes']}")
        if len(lines) > 1:
            sections.append("\n".join(lines))

    return "\n\n".join(sections)


def _section_modalites(brief: dict) -> str:
    """
    Section décrivant les modalités d'exécution. Avec le brief mutualisé,
    on affiche TOUTES les sections présentes (formation + énergie).
    """
    sections = []

    # Sous-section formation
    mod = brief.get("modalites") or {}
    if mod:
        lines = []
        if mod.get("presentiel_obligatoire") is not None:
            lines.append(f"Présentiel obligatoire : {mod['presentiel_obligatoire']}")
        if mod.get("distanciel_possible") is not None:
            lines.append(f"Distanciel possible : {mod['distanciel_possible']}")
        if mod.get("synchrone_asynchrone"):
            lines.append(f"Modalité : {mod['synchrone_asynchrone']}")
        if mod.get("sites_execution"):
            sites = mod["sites_execution"]
            lines.append(f"Sites d'exécution ({len(sites)}) : "
                          + ", ".join(str(s) for s in sites[:10])
                          + ("…" if len(sites) > 10 else ""))
        if mod.get("sites"):  # ancien nom toléré
            sites = mod["sites"]
            lines.append(f"Sites d'exécution ({len(sites)}) : "
                          + ", ".join(str(s) for s in sites[:10])
                          + ("…" if len(sites) > 10 else ""))
        if mod.get("amplitude_horaire"):
            lines.append(f"Amplitude horaire : {mod['amplitude_horaire']}")
        if mod.get("nb_lots"):  # ancien nom toléré
            lines.append(f"Nombre de lots : {mod['nb_lots']}")
        if mod.get("commentaire_modalites"):
            lines.append(mod["commentaire_modalites"])
        if lines:
            sections.append("=== MODALITÉS ===\n" + "\n".join(lines))

    # Sous-section énergie renouvelable
    mc = brief.get("modalites_execution_chantier") or {}
    if mc:
        lines = []
        if mc.get("raccordement_reseau_inclus") is not None:
            lines.append(f"Raccordement réseau inclus : {mc['raccordement_reseau_inclus']}")
        if mc.get("etudes_techniques_incluses") is not None:
            lines.append(f"Études techniques incluses : {mc['etudes_techniques_incluses']}")
        if mc.get("calendrier_chantier_contraint"):
            lines.append(f"Calendrier contraint : {mc['calendrier_chantier_contraint']}")
        if mc.get("sites_execution"):
            sites = mc["sites_execution"]
            lines.append(f"Sites d'exécution ({len(sites)}) : "
                          + ", ".join(str(s) for s in sites[:10])
                          + ("…" if len(sites) > 10 else ""))
        if mc.get("engagement_productible"):
            lines.append(f"Engagement productible : {mc['engagement_productible']}")
        if mc.get("engagement_disponibilite_om"):
            lines.append(f"Engagement disponibilité O&M : {mc['engagement_disponibilite_om']}")
        if lines:
            sections.append("=== MODALITÉS D'EXÉCUTION CHANTIER ===\n" + "\n".join(lines))

    return "\n\n".join(sections)


def _synthese_comparables(top_comparables: list,
                            marches_notifies: dict) -> str:
    """Construit une synthèse compacte des N comparables DECP."""
    lignes = []
    for c in top_comparables[:N_COMPARABLES_MAX]:
        id_c = c.get("id")
        # Récupère le marché complet en base (pour avoir l'objet)
        m_decp = marches_notifies.get(id_c, {})
        objet = (m_decp.get("objet") or "")[:180]
        l = [
            f"ID: {id_c}",
            f"sim: {(c.get('similarite') or 0) * 100:.0f}%",
            f"montant: {c.get('montant_eur') or '?'} €",
            f"durée: {c.get('duree_mois') or '?'} mois",
        ]
        if c.get("annee_notification"):
            l.append(f"année: {c['annee_notification']}")
        if c.get("titulaire"):
            l.append(f"titulaire: {c['titulaire']}")
        if c.get("lieu_execution"):
            l.append(f"lieu: {c['lieu_execution']}")
        # Champs spécifiques au format DECP enrichi
        if m_decp.get("acheteur_region_nom"):
            l.append(f"région acheteur: {m_decp['acheteur_region_nom']}")
        if m_decp.get("titulaire_categorie"):
            l.append(f"cat titulaire: {m_decp['titulaire_categorie']}")
        if m_decp.get("offres_recues"):
            l.append(f"offres reçues: {m_decp['offres_recues']}")
        if m_decp.get("forme_prix"):
            l.append(f"forme prix: {m_decp['forme_prix']}")
        ligne = "  ".join(l)
        if objet:
            ligne += f"\n  objet: {objet}"
        lignes.append(ligne)
    return "\n\n".join(lignes) if lignes else "(aucun comparable)"


# ---------------------------------------------------------------------------
# Appel LLM
# ---------------------------------------------------------------------------

def calibrer(brief: dict,
              top_comparables: list,
              marches_notifies: dict,
              max_retries: int = 2,
              verbose: bool = False) -> Optional[dict]:
    """
    Effectue l'appel LLM de calibration.

    Args:
        brief: brief froid extrait par llm_extract
        top_comparables: liste depuis zone_prix.top_comparables
        marches_notifies: base complète {id: marche} pour enrichir les comparables
        max_retries: nombre de tentatives en cas de JSON malformé
        verbose: log API détaillé

    Returns:
        dict calibration ou None si échec/impossible
    """
    if not top_comparables:
        return None

    # Refuse de calibrer si les comparables sont trop éloignés
    sims = [c.get("similarite", 0) for c in top_comparables]
    sim_moy = sum(sims) / len(sims) if sims else 0
    if sim_moy < SEUIL_SIMILARITE_MIN:
        return {
            "prix_unitaire_estime": None,
            "fourchette_marche_total_estimee": None,
            "calibration_impossible_raison": (
                f"Similarité moyenne des comparables ({sim_moy:.0%}) trop faible "
                f"pour une calibration fiable (seuil {SEUIL_SIMILARITE_MIN:.0%})."
            ),
        }

    llm_extract._check_anthropic()
    from anthropic import Anthropic
    client = Anthropic()

    prompt = _construire_prompt_utilisateur(
        brief_synthese=_synthese_brief(brief),
        n_comp=len(top_comparables[:N_COMPARABLES_MAX]),
        comparables_synthese=_synthese_comparables(top_comparables, marches_notifies),
    )

    debut = time.time()
    for tentative in range(1, max_retries + 1):
        try:
            if verbose:
                print(f"  → Calibration LLM tentative {tentative} "
                      f"({len(prompt)} chars input)")
            message = client.messages.create(
                model=MODELE,
                max_tokens=MAX_TOKENS_REPONSE,
                system=_construire_prompt_systeme(),
                messages=[{"role": "user", "content": prompt}],
            )
            duree = time.time() - debut
            texte = message.content[0].text if message.content else ""

            if verbose:
                in_t = message.usage.input_tokens
                out_t = message.usage.output_tokens
                cout = (in_t * 3 + out_t * 15) / 1_000_000
                print(f"  ← Calibration {duree:.1f}s · {in_t}+{out_t} tokens · "
                      f"{cout:.4f} $")

            # Parser le JSON
            try:
                return json.loads(texte)
            except json.JSONDecodeError:
                m = re.search(r"\{.*\}", texte, re.DOTALL)
                if m:
                    try:
                        return json.loads(m.group(0))
                    except json.JSONDecodeError:
                        pass
                if tentative >= max_retries:
                    if verbose:
                        print(f"  ⚠ JSON malformé après {max_retries} essais")
                        print(f"    Début : {texte[:300]}")
                    return None
        except Exception as e:
            if verbose:
                print(f"  ⚠ Erreur API tentative {tentative} : {e}")
            if tentative >= max_retries:
                return None

    return None


def _construire_prompt_bottom_up_seul(brief_synthese: str) -> str:
    """
    Prompt adapté quand aucun comparable DECP n'est disponible.
    Le LLM produit UNIQUEMENT le bottom-up (pas de top-down ni triangulation).

    Utile en attendant l'ingestion DECP : permet d'avoir une première
    estimation chiffrée à partir du brief seul + barèmes sectoriels du preset.
    """
    pc = _preset.prompt_calibration()
    return f"""Voici le contexte d'un marché public {pc.get("secteur_libelle_court", "publics")}
à estimer. Aucun comparable DECP n'est disponible pour ce calcul — tu vas donc
produire une estimation BOTTOM-UP seule (calcul à partir des caractéristiques
de la prestation).

=== BRIEF EXTRAIT DU DCE (faits objectifs) ===
{brief_synthese}

=== TA MISSION ===

Calibre une fourchette de prix unitaire (en €/unité) par DÉCOMPOSITION COÛT,
en partant uniquement des caractéristiques de la prestation.

ÉTAPE 0 — **ESTIMATION BOTTOM-UP par décomposition coût**

{pc.get("section_qualification_intervenants",
       "a. **Qualification des intervenants exigée** : adapter les coûts horaires au profil métier.")}

{pc.get("section_duree_effective",
       "b. **Volume / quantité de prestation** : extraire du DCE la grandeur principale (heures, unités, mètres) qui dimensionne le marché.")}

{pc.get("section_coefficient_complexite",
       "c. **Coefficient de complexité** : ×1.0 standard, jusqu'à ×1.5 selon contraintes spécifiques.")}

d. **Calcule** : `prix_unitaire_bottom_up = coût_horaire × heures_effectives × coef_complexité`
   Donne une fourchette (borne basse hypothèses minimales, borne haute hypothèses maximales).

{pc.get("section_re_pricing",
       "ÉTAPE 0bis — **DÉCOMPOSITION SI BPU NON-LINÉAIRE** : si l'unité du marché diffère de l'unité physique principale, décomposer en coûts fixes (mutualisés) + coûts variables (linéaires) et montrer le calcul.")}

ÉTAPE 1 — **FOURCHETTE MARCHÉ TOTAL** (prix figé à la médiane, variance sur volumes)

RÈGLE CRITIQUE : la fourchette du marché total NE DOIT PAS combiner variance
de prix ET variance de volumes. Cela produit des fourchettes inexploitables
(rapport haut/bas > 5x). Le prix unitaire min/max est conservé dans le bloc
`prix_unitaire_estime.bottom_up` pour analyse, mais le calcul de la fourchette
marché total se fait UNIQUEMENT à la médiane.

Trois scénarios, prix figé à `mediane_eur`, on fait varier UNIQUEMENT volumes,
charge d'exécution et durée :

- **bas** : prix MÉDIAN × volumes nominaux × charge 80% × période ferme seule
- **realiste** : prix MÉDIAN × volumes nominaux × charge 85% × période ferme + reconductions probables (50% du potentiel)
- **haut** : prix MÉDIAN × volumes maximaux contractuels × charge 100% × toutes reconductions

Objectif : rapport haut/bas ≤ 3x. Si tu obtiens plus de 3x, c'est que tu fais
varier le prix — corrige.

ÉTAPE 2 — **CONFIANCE et LIMITES**

Note explicitement que :
- Pas de top-down possible (zéro comparable DECP en base)
- Confiance = "faible" par défaut (passera à "moyenne" quand DECP sera ingéré)
- Liste 2-3 hypothèses-clés qui pourraient invalider l'estimation

=== FORMAT DE SORTIE ===

Retourne EXCLUSIVEMENT un objet JSON (pas de blocs ``` ni de commentaire) :

{{
  "prix_unitaire_estime": {{
    "unite": "unité naturelle déduite du brief (parcours / heure / kWc / m² / etc.)",
    "mediane_eur": <nombre>,
    "min_eur": <nombre>,
    "max_eur": <nombre>,
    "methode_fourchette": "Bottom-up seul (pas de comparables DECP)",
    "bottom_up": {{
      "qualification_intervenants": "...",
      "cout_horaire_retenu_eur": "...",
      "heures_effectives_par_unite": "...",
      "coef_complexite": "...",
      "calcul": "Décomposition COMPLÈTE et MATHÉMATIQUE — donne tous les chiffres intermédiaires.",
      "fourchette_eur": "X – Y"
    }},
    "unit_repricing": {{
      "_commentaire": "OBLIGATOIRE si l'unité du BPU n'est pas l'unité physique. Omettre sinon.",
      "unite_marche": "...",
      "couts_fixes_par_session_eur": {{}},
      "cout_variable_par_unite_eur": <nombre>,
      "calcul_session_type": "...",
      "fourchette_session_eur": "X – Y"
    }},
    "top_down": null,
    "triangulation": "Bottom-up seul — pas de top-down possible sans comparables DECP en base. La validation par triangulation sera possible quand DECP sera ingéré.",
    "hypotheses": "Synthèse en 2 phrases de la démarche.",
    "ajustements_appliques": "...",
    "confiance": "faible",
    "limites": "Mentionne les biais : pas de validation externe par comparables, prix calculé en pur théorique, inflation/contexte régional non vérifiés, etc."
  }},
  "fourchette_marche_total_estimee": {{
    "min_eur": <nombre>,
    "max_eur": <nombre>,
    "calcul": "Détail du calcul prix_unitaire × volumes du brief",
    "scenarios": {{
      "bas": {{
        "montant_eur": <nombre>,
        "hypothese": "..."
      }},
      "realiste": {{
        "montant_eur": <nombre>,
        "hypothese": "..."
      }},
      "haut": {{
        "montant_eur": <nombre>,
        "hypothese": "..."
      }}
    }}
  }}
}}

Si le brief manque d'informations critiques pour faire un bottom-up
(volumes manquants, prestation indéterminée), retourne :

{{
  "prix_unitaire_estime": null,
  "fourchette_marche_total_estimee": null,
  "calibration_impossible_raison": "Explique pourquoi en 1-2 phrases"
}}"""


def calibrer_bottom_up_seul(brief: dict,
                             max_retries: int = 2,
                             verbose: bool = False) -> Optional[dict]:
    """
    Calibration en mode DÉGRADÉ (bottom-up seul, sans comparables DECP).

    Utile quand la base DECP n'a pas encore été ingérée. Le LLM calcule
    le prix unitaire par décomposition coût à partir du brief + barèmes
    horaires du preset actif. Pas de top-down ni triangulation.

    La confiance est par défaut "faible" (pas de validation externe).
    Quand DECP sera ingéré, relancer `calibrer()` pour upgrade vers une
    calibration triangulée.

    Args:
        brief: brief froid extrait par llm_extract
        max_retries: tentatives en cas de JSON malformé
        verbose: log API détaillé

    Returns:
        dict calibration (mode bottom-up seul) ou None si échec.
    """
    llm_extract._check_anthropic()
    from anthropic import Anthropic
    client = Anthropic()

    prompt = _construire_prompt_bottom_up_seul(_synthese_brief(brief))

    debut = time.time()
    for tentative in range(1, max_retries + 1):
        try:
            if verbose:
                print(f"  → Calibration bottom-up seul, tentative {tentative} "
                      f"({len(prompt)} chars input)")
            message = client.messages.create(
                model=MODELE,
                max_tokens=MAX_TOKENS_REPONSE,
                system=_construire_prompt_systeme(),
                messages=[{"role": "user", "content": prompt}],
            )
            duree = time.time() - debut
            texte = message.content[0].text if message.content else ""

            if verbose:
                in_t = message.usage.input_tokens
                out_t = message.usage.output_tokens
                cout = (in_t * 3 + out_t * 15) / 1_000_000
                print(f"  ← Calibration {duree:.1f}s · {in_t}+{out_t} tokens · "
                      f"{cout:.4f} $")

            # Parser le JSON
            try:
                resultat = json.loads(texte)
            except json.JSONDecodeError:
                m = re.search(r"\{.*\}", texte, re.DOTALL)
                if m:
                    try:
                        resultat = json.loads(m.group(0))
                    except json.JSONDecodeError:
                        if tentative >= max_retries:
                            if verbose:
                                print(f"  ⚠ JSON malformé après {max_retries} essais")
                            return None
                        continue
                else:
                    if tentative >= max_retries:
                        return None
                    continue

            # Marque le mode de calibration utilisé
            if resultat:
                resultat["_mode_calibration"] = "bottom_up_seul"
            return resultat

        except Exception as e:
            if verbose:
                print(f"  ⚠ Erreur API tentative {tentative} : {e}")
            if tentative >= max_retries:
                return None

    return None


# ---------------------------------------------------------------------------
# Cache disque (recalculable)
# ---------------------------------------------------------------------------

def _cache_path(id_marche: str) -> Path:
    # Sanitize l'ID pour éviter les traversals
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", id_marche)
    return REPERTOIRE_CALIBRATIONS / f"{safe}.json"


def charger_si_existe(id_marche: str) -> Optional[dict]:
    """Retourne le cache si présent, None sinon."""
    p = _cache_path(id_marche)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def calibrer_et_cacher(id_marche: str,
                         brief: dict,
                         zone_prix: dict,
                         marches_notifies: dict,
                         force: bool = False,
                         verbose: bool = False,
                         mode: str = "auto") -> Optional[dict]:
    """
    Wrapper avec cache disque. Ne fait l'appel API que si nécessaire.

    Args:
        id_marche: identifiant du marché actif (ex: "BOAMP-26-51023")
        brief: brief froid extrait
        zone_prix: résultat de concurrence.zone_prix_marche() (peut être None
                   ou vide si DECP pas ingéré)
        marches_notifies: base DECP complète (pour enrichir les comparables)
        force: ignore le cache et force le recalcul
        verbose: log
        mode: 'auto' (par défaut, fallback bottom-up si pas DECP),
              'triangule' (force la calibration complète, échoue si pas DECP),
              'bottom_up' (force le bottom-up seul, ignore DECP même si dispo)

    Returns:
        dict calibration (peut contenir des null si impossible), ou None si
        échec API.
    """
    if not force:
        cached = charger_si_existe(id_marche)
        if cached is not None:
            return cached

    top = (zone_prix or {}).get("top_comparables") or []
    has_decp = bool(top)

    # Décide du mode effectif
    if mode == "triangule":
        if not has_decp:
            if verbose:
                print(f"  ⚠ Mode 'triangule' demandé mais 0 comparable DECP. "
                      f"Calibration impossible.")
            return None
        mode_effectif = "triangule"
    elif mode == "bottom_up":
        mode_effectif = "bottom_up"
    else:  # auto
        mode_effectif = "triangule" if has_decp else "bottom_up"

    if verbose:
        print(f"  Mode calibration : {mode_effectif} "
              f"(comparables DECP : {len(top)})")

    if mode_effectif == "triangule":
        resultat = calibrer(brief, top, marches_notifies, verbose=verbose)
        if resultat:
            from datetime import datetime, timezone
            resultat["_meta"] = {
                "date_calibration": datetime.now(timezone.utc).isoformat(),
                "mode": "triangule",
                "n_comparables_utilises": len(top),
                "similarite_moyenne": round(
                    sum(c.get("similarite", 0) for c in top) / len(top), 2
                ),
                "ids_comparables": [c.get("id") for c in top],
            }
    else:  # bottom_up
        resultat = calibrer_bottom_up_seul(brief, verbose=verbose)
        if resultat:
            from datetime import datetime, timezone
            resultat["_meta"] = {
                "date_calibration": datetime.now(timezone.utc).isoformat(),
                "mode": "bottom_up_seul",
                "n_comparables_utilises": 0,
                "note": ("Calibration dégradée — pas de comparables DECP en base. "
                         "Relancer en mode 'triangule' quand DECP sera ingéré "
                         "pour upgrade."),
            }

    if resultat:
        try:
            _cache_path(id_marche).write_text(
                json.dumps(resultat, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass
    return resultat


def calibrer_et_cacher_legacy(id_marche: str,
                                brief: dict,
                                zone_prix: dict,
                                marches_notifies: dict,
                                force: bool = False,
                                verbose: bool = False) -> Optional[dict]:
    """Ancienne signature pour compat. Refuse de calibrer si 0 comparable."""
    if not force:
        cached = charger_si_existe(id_marche)
        if cached is not None:
            return cached

    if not zone_prix:
        return None
    top = zone_prix.get("top_comparables") or []
    if not top:
        return None

    resultat = calibrer(brief, top, marches_notifies, verbose=verbose)
    if resultat:
        from datetime import datetime, timezone
        resultat["_meta"] = {
            "date_calibration": datetime.now(timezone.utc).isoformat(),
            "n_comparables_utilises": len(top),
            "similarite_moyenne": round(
                sum(c.get("similarite", 0) for c in top) / len(top), 2
            ),
            "ids_comparables": [c.get("id") for c in top],
        }
        try:
            _cache_path(id_marche).write_text(
                json.dumps(resultat, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass
    return resultat


def invalider_cache(id_marche: str) -> bool:
    """Supprime le cache pour un marché donné. True si supprimé."""
    p = _cache_path(id_marche)
    if p.exists():
        p.unlink()
        return True
    return False


# ---------------------------------------------------------------------------
# CLI minimal pour debug
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import stockage
    import concurrence
    import organisme

    parser = argparse.ArgumentParser(
        description="Calibre une estimation pour un marché donné.")
    parser.add_argument("id_marche",
                        help="ID Tendia du marché (ex: BOAMP-26-51023)")
    parser.add_argument("--force", action="store_true",
                        help="Ignore le cache")
    parser.add_argument("-v", "--verbose", action="store_true", default=True)
    args = parser.parse_args()

    marches = stockage.charger("marches")
    marche = marches.get(args.id_marche)
    if not marche:
        print(f"  ❌ Marché {args.id_marche} introuvable")
        raise SystemExit(1)

    brief_path = (Path("data/extractions") / f"{args.id_marche}.json")
    if not brief_path.exists():
        print(f"  ❌ Brief LLM introuvable : {brief_path}")
        raise SystemExit(1)
    brief = json.loads(brief_path.read_text(encoding="utf-8"))

    profil = organisme.lire_profil()
    notifies = stockage.charger("marches_notifies") or {}
    zone = concurrence.zone_prix_marche(profil, brief, marche, notifies)
    if not zone or not zone.get("top_comparables"):
        print(f"  ⚠ Pas de comparables, calibration impossible")
        raise SystemExit(1)

    print(f"  Calibration pour {args.id_marche}...")
    res = calibrer_et_cacher(args.id_marche, brief, zone, notifies,
                               force=args.force, verbose=args.verbose)
    if res:
        print()
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"  ❌ Calibration échouée")
