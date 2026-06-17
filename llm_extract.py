"""
llm_extract.py
--------------
Extraction structurée du contenu d'un DCE via Claude API.

Prend en entrée le texte combiné du RC + CCTP (+ autres pièces), retourne
un dict JSON avec les champs structurés clés pour décider de candidater.

Modèle : claude-sonnet-4-6 (équilibre qualité/coût pour extraction structurée).

API key : variable d'environnement ANTHROPIC_API_KEY.

API :
    extraire_via_llm(texte, contexte) -> dict
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

# SSL : sur ce poste, certifi ne peut pas bâtir la chaîne (interception TLS) →
# l'appel HTTPS du SDK anthropic échoue en "Connection error". truststore fait
# utiliser le magasin de certificats système. Injecté ici car le SDK anthropic
# n'importe PAS http_client (où truststore est aussi injecté). Idempotent.
try:
    import truststore as _truststore
    _truststore.inject_into_ssl()
except Exception:
    pass

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None


MODELE = "claude-sonnet-4-6"  # Sonnet 4.6 — canonical ID
MAX_TOKENS_REPONSE = 32000     # Sonnet 4.6 supporte bien au-delà ; les gros DCE multi-lots
                               # dépassaient 16000 → JSON tronqué → echec_llm. Streaming requis
                               # à ce niveau (cf. extraire_via_llm) pour éviter le timeout requête.
MAX_CHARS_INPUT = 400_000


# ---------------------------------------------------------------------------
# Chargement de la clé API depuis .env si la variable d'env n'est pas définie
# ---------------------------------------------------------------------------

def _charger_cle_depuis_env_file() -> Optional[str]:
    """
    Cherche un fichier .env à la racine du projet et y lit ANTHROPIC_API_KEY.

    Le fichier .env doit contenir une ligne du type :
        ANTHROPIC_API_KEY=sk-ant-XXXXXXXX
    (avec ou sans guillemets, avec ou sans espaces autour du =)

    Cherche aussi .env.txt (cas Notepad qui ajoute .txt sous Windows).
    Gère le BOM UTF-8 ajouté par Notepad.
    """
    racine = Path(__file__).parent
    # Cherche .env ou .env.txt (fallback Windows)
    candidats = [racine / ".env", racine / ".env.txt"]
    for chemin_env in candidats:
        if not chemin_env.is_file():
            continue
        try:
            # encoding="utf-8-sig" gère automatiquement le BOM ajouté par Notepad
            with open(chemin_env, encoding="utf-8-sig") as f:
                for ligne in f:
                    ligne = ligne.strip()
                    if not ligne or ligne.startswith("#"):
                        continue
                    if "=" not in ligne:
                        continue
                    cle, _, valeur = ligne.partition("=")
                    cle = cle.strip()
                    valeur = valeur.strip().strip('"').strip("'")
                    if cle == "ANTHROPIC_API_KEY" and valeur:
                        return valeur
        except Exception:
            continue
    return None


def _obtenir_cle_api() -> Optional[str]:
    """
    Récupère la clé API selon priorité :
    1. Variable d'environnement ANTHROPIC_API_KEY
    2. Fichier .env à la racine du projet
    """
    cle = os.environ.get("ANTHROPIC_API_KEY")
    if cle:
        return cle.strip()
    cle = _charger_cle_depuis_env_file()
    if cle:
        # Injecte dans l'env pour que le SDK Anthropic la trouve
        os.environ["ANTHROPIC_API_KEY"] = cle
        return cle
    return None


# ---------------------------------------------------------------------------
# Prompt structuré
# ---------------------------------------------------------------------------
#
# Le PROMPT_SYSTEME est désormais généré dynamiquement à partir du domaine
# actif (voir domaine.py). Le PROMPT_UTILISATEUR_TEMPLATE reste pour
# l'instant figé sur le schéma de sortie formation_ft ; son externalisation
# est prévue en Sprint 2 (chantier "schéma de sortie LLM par domaine").

import preset as _preset


# ---------------------------------------------------------------------------
# Taxonomie domaines métier (chargée lazy au premier usage)
# ---------------------------------------------------------------------------

_TAXONOMIE_CACHE: Optional[dict] = None


def _charger_taxonomie() -> dict:
    """Charge presets/_taxonomie_domaines.json (cached)."""
    global _TAXONOMIE_CACHE
    if _TAXONOMIE_CACHE is not None:
        return _TAXONOMIE_CACHE
    chemin = Path(__file__).parent / "presets" / "_taxonomie_domaines.json"
    if not chemin.is_file():
        _TAXONOMIE_CACHE = {"domaines": {}}
        return _TAXONOMIE_CACHE
    try:
        _TAXONOMIE_CACHE = json.loads(chemin.read_text(encoding="utf-8"))
    except Exception:
        _TAXONOMIE_CACHE = {"domaines": {}}
    return _TAXONOMIE_CACHE


def _section_taxonomie_prompt() -> str:
    """
    Construit la section taxonomie à injecter dans le prompt système.
    Compact : code + libellé + 1 ligne description.
    Inclut les règles de classification et exemples de frontières piégeuses.
    """
    tax = _charger_taxonomie()
    domaines = tax.get("domaines", {})
    if not domaines:
        return ""

    lignes = [
        "",
        "## RÈGLES DE CLASSIFICATION DOMAINE MÉTIER",
        "",
        "Tu DOIS classer le marché dans la taxonomie suivante (champ `domaines_metier`).",
        "",
        "Format :",
        "- **1 seul domaine** par défaut (cas majoritaire ~80%) : `[{\"code\": \"xxx\"}]` sans poids.",
        "- **2-3 domaines avec poids** UNIQUEMENT si marché multi-lots avec lots de métiers différents,",
        "  OU si marché unique mixe explicitement plusieurs métiers (ex: construction + formation opérateurs).",
        "  Poids ∈ [0.05, 1.0], somme strictement = 1.0.",
        "- JAMAIS plus de 3 domaines. Au-delà = surclassification.",
        "- Si vraiment hors taxonomie : un seul domaine = `autre`.",
        "",
        "Liste des codes disponibles :",
        "",
    ]
    for code, info in domaines.items():
        libelle = info.get("libelle", code)
        desc = info.get("description", "")
        # Compact : 1 phrase de description (tronquée à ~120 chars)
        desc_court = desc.split('.')[0][:120] if desc else ""
        lignes.append(f"- `{code}` — {libelle}. {desc_court}.")

    lignes.extend([
        "",
        "## FRONTIÈRES PIÉGEUSES — ATTENTION PARTICULIÈRE",
        "",
        "- \"qualification\" : `formation_pro_continue` si qualification professionnelle ; "
        "`services_environnement_analyses` si qualification de zones (salles propres, environnement maîtrisé) ; "
        "`btp_renovation_rehabilitation` si requalification fonctionnelle d'espaces.",
        "- \"accompagnement\" : `formation_pro_continue` ou `insertion_professionnelle` si vers l'emploi ; "
        "`conseil_juridique` si juridique ; `conseil_strategie_organisation` si conseil stratégique ; "
        "`insertion_sociale_mediation` si action sociale.",
        "- \"rénovation\" : `energie_renovation_thermique` si dominante isolation/thermique ; "
        "`btp_renovation_rehabilitation` si rénovation patrimoniale sans dimension énergétique forte.",
        "- \"AMO\" : `energie_amo_etudes` si AMO énergétique ; `moe_architecte_urbanisme` si programmation/MOE ; "
        "`ingenierie_structure_genie_civil` si ingénierie technique pure.",
        "- \"analyses\" : `services_environnement_analyses` pour eau/air/sols/salles propres ; "
        "`services_sante_medical` pour biologie médicale HUMAINE uniquement.",
        "- \"médiation\" : `insertion_sociale_mediation` (action sociale) ; "
        "JAMAIS confondre avec formation.",
        "- \"chèques d'accompagnement / cartes cadeau\" : `prestations_speciales_titres_cheques` "
        "(et non insertion sociale ou formation).",
        "- \"gardiennage\" : `securite_gardiennage` même si le bâtiment fait l'objet de rénovation énergétique.",
        "- \"restauration\" : `restauration_collective_prestations` si prestation déléguée ; "
        "`restauration_fournitures_alimentaires` si achat de denrées en gros sans prestation.",
        "- \"espaces verts\" : `amenagement_paysager_creation` si création/aménagement ; "
        "`amenagement_paysager_entretien` si entretien courant (tonte, taille, etc.).",
        "",
        "Si le marché ne te paraît pas correspondre à un domaine, JUSTIFIE par le champ `raison_classification`.",
    ])
    return "\n".join(lignes)


def _construire_prompt_systeme(codes_presets: Optional[list] = None) -> str:
    """
    Construit le prompt système, adapté aux presets pertinents pour le marché
    analysé (déduits de la classification IA).

    - Si codes_presets = [un_seul_preset] : prompt orienté sur ce secteur
      (vocabulaire dédié du preset).
    - Si codes_presets = plusieurs presets : prompt neutre multi-secteurs.
    - Si codes_presets = None ou [] : fallback sur le vocabulaire du preset
      actif (comportement legacy).
    """
    voc = _preset.vocabulaire_llm_pour_presets(codes_presets)
    secteur = voc.get("secteur_libelle", "marchés publics français")
    pieces = voc.get(
        "type_pieces_dce_typiques",
        "Règlement de Consultation (RC) et Cahier des Clauses Techniques Particulières (CCTP)",
    )
    repondant = voc.get("type_repondant", "candidat aux marchés publics")

    return (
        f"Tu es un expert en analyse de marchés publics français, "
        f"spécialisé dans les {secteur}.\n\n"
        f"Tu analyses des Dossiers de Consultation des Entreprises (DCE) "
        f"composés typiquement {pieces}.\n\n"
        f"Ta mission : extraire les informations structurées qui permettent "
        f"à un {repondant} de décider rapidement s'il peut et doit "
        f"candidater.\n\n"
        f"Réponds UNIQUEMENT en JSON valide, sans préambule, sans bloc "
        f"markdown, sans commentaire. Le JSON doit suivre exactement le "
        f"schéma demandé."
        + _section_taxonomie_prompt()
    )


# Backward compat : exposé comme constante évaluée à l'import (preset actif).
# Pour un prompt vraiment sectoriellement ciblé, appeler
# _construire_prompt_systeme(codes_presets=[...]) à chaque appel LLM.
PROMPT_SYSTEME = _construire_prompt_systeme()


def _construire_prompt_utilisateur(contexte_str: str, texte: str,
                                   codes_presets: Optional[list] = None) -> str:
    """
    Compose le prompt utilisateur final en injectant les blocs schéma des
    presets passés en argument.

    Routage par classification IA (Sprint 2bis) :
    - codes_presets = [...] (issus de presets_pour_domaines(classif_ia)) :
      seuls les blocs sectoriels pertinents pour ce marché sont injectés.
      → résout la collision de clés JSON et concentre le LLM.
    - codes_presets = None ou [] : fallback sur l'union complète de tous
      les presets installés (comportement legacy).

    Avantages du routage ciblé :
    - prompt 3-5x plus court (1-2k au lieu de 5-6k chars sur les blocs)
    - pas de collision `caracteristiques_techniques_chantier` entre BTP et
      énergie_renouvelable
    - plus de pollution lexicale formation (publics_cibles, parcours,
      bénéficiaires) pour un brief BTP/IT

    Fallbacks neutres si aucun preset ne fournit de bloc (cas dev/test ou
    marché classifié `autre`/hors-mapping).
    """
    # Sélection ciblée si on a une classif. HORS-PÉRIMÈTRE (codes_presets vide) :
    # on n'injecte AUCUN bloc sectoriel (les fallbacks neutres ci-dessous
    # produisent un schéma générique `caracteristiques_metier`). NE PLUS injecter
    # l'union complète (qui polluait ~50% des marchés avec tous les blocs).
    if codes_presets is None or len(codes_presets) == 0:
        union_schema = ""
        union_exemples = ""
        union_hints = ""
        union_regles = ""
        union_few_shot = ""
    else:
        # Mode ciblé : seuls les blocs des presets pertinents
        union_schema = _preset.schema_pour_presets(codes_presets)
        union_exemples = _preset.exemples_elements_a_chiffrer_pour_presets(codes_presets)
        union_hints = _preset.hints_calcul_montant_pour_presets(codes_presets)
        union_regles = _preset.regles_specifiques_pour_presets(codes_presets)
        union_few_shot = _preset.few_shot_examples_pour_presets(codes_presets)

    # Fallbacks neutres si aucun preset n'a fourni de bloc (marché classifié
    # `autre`, ou aucun preset installé en dev/test)
    if not union_schema.strip():
        union_schema = (
            '  "caracteristiques_metier": {\n'
            '    "description": "Description précise du sujet du marché.",\n'
            '    "criteres_eligibilite": []\n'
            '  }'
        )
    if not union_exemples.strip():
        union_exemples = (
            '"Prix unitaire de la prestation principale",\n'
            '        "Frais annexes"'
        )
    if not union_hints.strip():
        union_hints = (
            "Si tu trouves un prix unitaire et un volume plausible → CALCULE : "
            "`valeur_estimee_euros = volume × prix_unitaire` et mets "
            "`type: \"calcule_volumes\"`. Dans `commentaire`, EXPLIQUE le calcul."
        )

    # regles_specifiques / few_shot : formatage avec lignes blanches si non-vide
    rs_formate = f"\n{union_regles}\n" if union_regles.strip() else ""
    fs_formate = (f"\nEXEMPLES D'EXTRACTION (few-shot, à suivre comme modèle) :\n"
                  f"{union_few_shot}\n" if union_few_shot.strip() else "")

    return PROMPT_UTILISATEUR_TEMPLATE.format(
        contexte=contexte_str,
        texte=texte,
        bloc_schema_specifique=union_schema,
        exemples_elements_a_chiffrer=union_exemples,
        hints_calcul_montant=union_hints,
        few_shot_examples=fs_formate,
        regles_specifiques=rs_formate,
        regles_v2=REGLES_V2,
    )


PROMPT_UTILISATEUR_TEMPLATE = """Voici le contenu d'un DCE pour un marché public.

CONTEXTE DU MARCHÉ :
{contexte}

CONTENU DES PIÈCES DU DCE (RC, CCTP, etc.) :
---
{texte}
---

Extrais les informations dans ce schéma JSON :

{{
  "synthese_marche": "Résumé du marché en 2-3 phrases.",
  "domaines_metier": [
    {{
      "code": "code_domaine_principal",
      "_commentaire_omettre_si_un_seul_domaine": "Si UN SEUL domaine (cas majoritaire ~80%) : juste {{\\"code\\": \\"xxx\\"}}, sans champ poids ni lots_concernes. Voir 'RÈGLES DE CLASSIFICATION DOMAINE MÉTIER' dans le system prompt.",
      "poids": null,
      "lots_concernes": null
    }}
  ],
  "raison_classification": "1-2 phrases expliquant pourquoi tu as choisi ce(s) domaine(s). Mentionne les éléments du DCE qui ont guidé ta décision (objet, lots, vocabulaire spécifique). Utile pour debug.",
{bloc_schema_specifique},
  "bareme_notation": {{
    "valeur_technique_pct": null,
    "valeur_prix_pct": null,
    "sous_criteres_techniques": [
      {{
        "libelle": "Intitulé exact du sous-critère tel qu'écrit dans le RC",
        "ponderation_pct": 50,
        "description": "1-2 phrases factuelles depuis le RC expliquant CE que l'acheteur évalue précisément sur ce sous-critère.",
        "elements_attendus": [
          "Liste de 3-6 points concrets que la réponse doit contenir pour scorer haut",
          "Reformule textuellement les attendus explicites du RC",
          "Si absent du RC, mets [] vide — n'invente rien"
        ],
        "exemple_reponse_forte": "Court paragraphe (2-3 phrases) illustrant le type de contenu attendu d'une réponse qui scorerait haut sur ce sous-critère. Doit être plausible vis-à-vis du RC.",
        "source": "Référence vers le document où le sous-critère est décrit : 'RC §5.2', 'RC article 6 page 12'. Si pas localisable précisément : 'RC' ou null.",
        "unite_evaluation": "Unité D'ÉVALUATION du sous-critère (v2) : EXACTEMENT 'euro' si le sous-critère est noté sur une grandeur MONÉTAIRE (coût, prix, €/tonne CO2, coût global, pénalités chiffrées), 'delai_jours' si noté sur un délai en jours/semaines, sinon 'points' (mémoire technique, RSE notée en points, références, qualité). Détermine la famille prix/technique. Présent à TOUS les niveaux de sous-critères.",
        "sous_criteres": [
          {{
            "libelle": "Intitulé du sous-sous-critère",
            "ponderation_pct": 30,
            "description": "Sous-niveau imbriqué : présent UNIQUEMENT si le RC structure réellement le critère parent en sous-rubriques chiffrées.",
            "elements_attendus": ["..."],
            "exemple_reponse_forte": "...",
            "source": "RC §5.2.1"
          }},
          {{
            "libelle": "Intitulé d'un autre sous-sous-critère",
            "ponderation_pct": 20,
            "description": "...",
            "elements_attendus": [],
            "exemple_reponse_forte": null,
            "source": "RC §5.2.2"
          }}
        ]
      }}
    ],
    "prix": {{
      "type_formule": "moins_disant",
      "formule_explicite": "Ex: 'Note prix = (prix_le_plus_bas / prix_candidat) × 30' — si la formule exacte est dans le RC, recopier-la ; sinon décrire le mécanisme en 1 phrase",
      "source": "Référence RC du critère prix et de sa pondération : 'RC §5.3', 'RC article 6 page 14'. Si non localisable précisément : 'RC' ou null.",
      "elements_a_chiffrer": [
        {exemples_elements_a_chiffrer}
      ]
    }},
    "modalite_calcul_prix": "Ex libre — gardé pour rétro-compat. Recopier la formule prix telle qu'écrite dans le RC."
  }},
  "montant_marche": {{
    "valeur_estimee_euros": null,
    "fourchette_min_euros": null,
    "fourchette_max_euros": null,
    "type": "non_communique",
    "duree_couverte": null,
    "source_extraction": null,
    "commentaire": null
  }},
  "montant_3_voies": {{
    "voie_1_eur": null,
    "voie_1_source": null,
    "voie_2_disponible": false,
    "voie_2_min_eur": null,
    "voie_2_max_eur": null,
    "voie_2_hypotheses": [
      {{"hypothese": "Hypothèse retenue avec sa source DCE (ex: 'Surface 1200m² (CCTP p.4)')", "valeur": "1200 m²"}}
    ],
    "voie_2_raison_indisponible": null
  }},
  "revision_prix": {{
    "type": "indexation",
    "indices_utilises": ["SYNTEC", "ILC"],
    "ponderation": "Description en clair de la formule de pondération entre indices, recopiée du CCAP (ex selon secteur : '65% SYNTEC + 15% ILC + 20% partie fixe' pour services intellectuels ; '60% BT01 + 40% partie fixe' pour BTP ; etc.)",
    "periodicite": "semestrielle",
    "formule_revision": "Recopie de la formule du CCAP si présente (ex: 'Pn = P0 × (0.65 × SYNTECn/SYNTEC0 + 0.15 × ILCn/ILC0 + 0.20)')",
    "source_extraction": "Ex: 'CCAP article 5.3 page 12'",
    "commentaire": "Analyse courte de l'impact pour le candidat (favorable en inflation, complexe à anticiper, etc.)"
  }},
  "alertes_prix": [
    "Liste de 2-4 signaux contextuels liés au prix : ex 'Seuil d'OAB (offre anormalement basse) annoncé à 80% de l'estimation', 'Le marché précise un plafond budgétaire de 250 k€ par lot', 'Pondération prix de 40% inhabituellement élevée pour ce type de marché'. Mets [] vide si rien de notable."
  ],
  "references_exigees": {{
    "experience_minimale_annees": null,
    "experience_source": "Référence vers le doc qui mentionne l'expérience minimale : 'RC art 8.1' ou null",
    "volume_min_references_similaires": null,
    "volume_min_references_unite": "Unité du volume minimal de références exigées. À adapter au secteur du marché : 'marchés similaires', 'chantiers réalisés', 'm² rénovés', 'MWc installés', 'utilisateurs équipés', 'jours de mission', 'sites équipés', 'bénéficiaires accompagnés', etc. Si non précisé, null.",
    "secteur_experience": "Domaine d'expérience attendu, formulé fidèlement au RC (ex selon secteur du marché : 'réhabilitation d'ouvrage d'art en béton précontraint', 'installation PV tertiaire', 'TMA progiciel SI RH secteur public', 'audit organisationnel collectivité', 'insertion professionnelle public éloigné de l'emploi').",
    "secteur_source": "Référence ou null",
    "certifications_obligatoires": [
      {{
        "libelle": "Certification ou qualification requise, recopiée fidèlement du RC. Adapter au secteur : Qualibat XXXX pour BTP, ISO 27001/HDS pour IT, OPQIBI pour ingénierie, Qualiopi pour formation, RGE pour énergie, ordre professionnel pour conseil juridique, etc.",
        "source": "Ex: 'RC art 4.1' ou 'CCAP art 2'"
      }}
    ],
    "autres_exigences": [
      {{
        "libelle": "Ex: 'Chiffre d'affaires annuel moyen sur 3 derniers exercices ≥ 86 100 €'",
        "source": "Ex: 'RC art 4.3.2' ou null"
      }}
    ]
  }},
  "lots": [
    {{
      "numero": 1,
      "intitule": "Intitulé exact du lot tel qu'écrit dans le RC",
      "zone_geographique": "Zone si le lot est géographiquement défini, ex: code région (NAQ, IDF), département, ville. null sinon.",
      "volume_estime": null,
      "volume_estime_unite": "Unité du volume de ce lot, adaptée au secteur : 'm²', 'kWc', 'jours-homme', 'utilisateurs', 'bénéficiaires', 'tonnes', etc. Si non précisé, null.",
      "particularites": "Texte libre"
    }}
  ],
  "calendrier": {{
    "date_limite_offres": "YYYY-MM-DD si trouvée",
    "date_demarrage_prevue": "YYYY-MM-DD si trouvée",
    "duree_marche": "ex: '24 mois reconductibles'"
  }},
  "alertes_candidat": [
    "Liste de 3-5 points qui peuvent disqualifier un candidat ou demander attention particulière, formulés concrètement à partir du DCE. Adapter au secteur (ex BTP : 'qualification Qualibat XXXX exigée à peine d'irrecevabilité' ; IT : 'hébergement HDS obligatoire' ; ingénierie : 'référence d'ouvrage d'art béton précontraint des 5 dernières années requise' ; formation : 'Qualiopi exigé')."
  ],
  "points_differenciants_attendus": [
    {{
      "libelle": "Axe différenciant — courte description, ancrée dans le RC ou le contexte du marché.",
      "exemple": "Exemple concret (1-2 phrases) montrant comment un candidat peut s'en servir dans sa réponse. Doit être plausible vis-à-vis du marché analysé (pas un exemple générique).",
      "source": "Si l'axe est explicitement valorisé par un passage du RC/CCTP : 'CCTP §4.2'. Si tu l'infères du contexte du marché sans citation explicite : null."
    }}
  ]
}}

RÈGLES IMPORTANTES :
- **RESPECT STRICT DU SCHÉMA** : tu produis EXACTEMENT les champs définis ci-dessus, ni plus ni moins. N'ajoute AUCUN bloc sectoriel qui n'est pas listé (par exemple : si le schéma ne contient pas `publics_cibles`, `caracteristiques_si`, `allotissement`, ou tout autre bloc, NE LE PRODUIS PAS). Tout champ hors-schéma sera supprimé du JSON final. Si tu juges que le marché ne correspond pas au domaine ciblé par le schéma, indique-le dans `raison_classification` et dans `domaines_metier` (code `autre` si nécessaire), mais NE FABRIQUE PAS de champs alternatifs hors du schéma fourni.
- Si une information n'est pas trouvée dans le texte, mets `null` (jamais "inconnu" ou texte libre).
- Pour les pourcentages, mets des NOMBRES (pas "30%"), donc 30 et pas "30%".
- Pour les listes, mets [] vide si rien.
- Sois précis sur les volumes (ne pas inventer si pas clair).

- **TRAÇABILITÉ DES SOURCES** : pour chaque assertion structurée du brief (critère d'éligibilité, sous-critère du barème, certification, exigence, point différenciant…), tu joins un champ `source` qui pointe vers le document du DCE et idéalement l'article ou le paragraphe.
  - Format court préféré : `"CCTP §2.1"`, `"RC art 4.2"`, `"CCAP article 5 page 12"`, `"BPU ligne 3"`.
  - Si tu ne peux pas localiser précisément l'article mais tu sais de quel document ça vient : mets le document seul, ex `"CCTP"`.
  - Si vraiment impossible à sourcer (information inférée, non-explicite) : mets `null` plutôt qu'inventer une référence.
  - Cite SEULEMENT les documents qui te sont effectivement fournis. Ne fabrique JAMAIS de référence à un document que tu n'as pas vu.
  - Quand un même article du DCE couvre plusieurs items consécutifs, recopie la même source — c'est normal.
  - Les sources sont la base de la confiance de l'utilisateur : prends-les au sérieux.

- **SOUS-CRITÈRES ENRICHIS** : pour chaque sous-critère technique tu produis 5 champs OBLIGATOIRES + 1 OPTIONNEL :
  - `libelle` : nom du sous-critère tel qu'écrit dans le RC
  - `ponderation_pct` : sa pondération en nombre (sans %)
  - `description` : 1-2 phrases factuelles tirées du RC sur CE que l'acheteur évalue (ne pas paraphraser de façon générique)
  - `elements_attendus` : 3-6 points concrets QUE LA RÉPONSE DEVRA CONTENIR pour scorer haut. Reformule les attendus explicites du RC. Si le RC ne précise rien, mets [] vide — ne brode pas.
  - `exemple_reponse_forte` : court paragraphe (2-3 phrases) qui illustre une réponse forte sur ce sous-critère. Doit être plausible vis-à-vis du contexte du marché. Si tu n'as pas matière, écris "—" (un simple tiret).
  - `source` : référence vers le document du DCE où ce sous-critère est défini (ex: "RC §5.2"). null si non-localisable.

- **HIÉRARCHIE DES SOUS-CRITÈRES — RÈGLE CRITIQUE** : un sous-critère peut lui-même se décomposer en sous-sous-critères chiffrés. C'est fréquent dans les RC de marchés publics structurés. Tu DOIS reproduire la hiérarchie réelle du RC, pas l'aplatir.

  - Si le RC affiche un critère « Valeur technique 50% » qui se décompose en « Méthodologie 30% / Moyens humains 20% », tu produis UN sous-critère "Valeur technique" avec `ponderation_pct=50` ET un champ `sous_criteres` contenant les 2 enfants chiffrés. Tu N'aplatit PAS en 2 sous-critères de 30% et 20% au premier niveau.

  - Si au contraire le RC liste directement plusieurs sous-critères de premier niveau sans regroupement parent (ex: Critère A 10%, Critère B 10%, Critère C 10%, Critère D 15%, …), tu les gardes plats — ne crée JAMAIS un faux regroupement parent qui n'existe pas dans le RC.

  - La récursion est libre : un sous-sous-critère peut lui-même contenir `sous_criteres` si le RC va à 3 niveaux.

  - Le champ `sous_criteres` est OPTIONNEL : omets-le complètement (ou mets `[]`) quand le sous-critère est terminal (feuille).

- **COHÉRENCE DES PONDÉRATIONS** : à chaque niveau, la somme des `ponderation_pct` doit valoir le `ponderation_pct` du parent (ou 100 au niveau racine pour la partie technique). Si tu vois une incohérence (ex: 50% = 30% + 15% + 10% = 55%), c'est probablement que tu as mal lu le RC — relis ce passage spécifique. Si l'incohérence persiste après vérification, mentionne-la dans la `description` du parent ("le RC affiche un sous-total à 55% au lieu de 50%").

- **CRITIQUE BARÈME** : `valeur_technique_pct` + `valeur_prix_pct` doit faire EXACTEMENT 100. Les critères RSE/environnementaux/sociaux sont presque toujours des SOUS-critères du technique (à ranger dans `sous_criteres_techniques`), pas un 3e critère principal. Ne crée jamais un troisième pourcentage qui ferait dépasser 100.

- **BLOC PRIX STRUCTURÉ** dans `bareme_notation.prix` :
  - `type_formule` : choisis EXACTEMENT une valeur parmi cette liste fermée :
    `moins_disant` (note proportionnelle au prix le plus bas)
    `lineaire` (note linéaire entre min et max)
    `ecart_type` (note vs moyenne, pénalise les extrêmes)
    `seuil` (note plein/zéro selon seuil)
    `autre`
    Si le RC ne précise pas explicitement la formule, mets "autre".
  - `formule_explicite` : recopie textuellement la formule du RC si elle est là (en LaTeX simplifié ou prose). Sinon 1 phrase descriptive.
  - `source` : OÙ dans le RC se trouve le critère prix et sa pondération (ex: "RC art 5.3 page 14", "RC §6.2"). Si non localisable précisément : "RC". Si vraiment introuvable : null.
  - `elements_a_chiffrer` : liste des postes/lignes à chiffrer dans le bordereau de prix (BPU, DPGF, etc.) selon le RC.

- **MONTANT DU MARCHÉ** dans `montant_marche` :

  C'est la question N°1 que se pose le candidat avant de répondre. Beaucoup de marchés publics (notamment les accords-cadres) ne donnent PAS de valeur explicite, mais il est presque toujours possible de **chiffrer une estimation** à partir des éléments présents. Tu dois TOUJOURS essayer dans cet ordre :

  1. **Cherche un montant explicite** dans le RC, le CCAP ou l'avis BOAMP. Mots-clés à scanner : "estimé à", "montant prévisionnel", "valeur estimée", "plafond", "maximum", "enveloppe budgétaire", "valeur totale". Si trouvé → `type: "estime_explicite"` ou `"plafond"`.

  2. **Sinon, cherche le prix unitaire** dans le BPU (Bordereau des Prix Unitaires), le CCAP ou le RC. {hints_calcul_montant}

  3. **Sinon, cherche une fourchette** dans l'avis BOAMP (champs "valeur min/max") ou dans le RC. Si trouvée → remplis `fourchette_min_euros` et `fourchette_max_euros`, et `type: "estime_explicite"`.

  4. **En tout dernier recours**, si AUCUN des 3 points ci-dessus ne donne rien après recherche approfondie, mets `type: "non_communique"` et toutes les valeurs à null. Mais c'est rare — il y a presque toujours un prix unitaire quelque part.

  - `valeur_estimee_euros` : nombre en euros (pas string). Ex: 250000.
  - `fourchette_min_euros` / `fourchette_max_euros` : nombres en euros si fourchette.
  - `type` : EXACTEMENT parmi `estime_explicite`, `plafond`, `calcule_volumes`, `non_communique`.
  - `duree_couverte` : période à laquelle s'applique le montant (ex: "période ferme 12 mois", "tranche 24 mois reconductible").
  - `source_extraction` : OÙ tu as trouvé l'info (ex: "RC article 3.2 page 8", "BPU ligne 12", "avis BOAMP rubrique II.2.6").
  - `commentaire` : si calculé, EXPLIQUE LE CALCUL clairement (ex: "200 bénéf × 1 250 € parcours = 250 000 € sur 12 mois"). Si plafond, précise (ex: "Plafond accord-cadre toutes tranches confondues").

  ⚠️ ATTENTION — Ne PAS confondre :
  - **Montant du marché** = ce que l'acheteur va payer au titulaire (= ce qu'on cherche ici).
  - **CA minimum exigé du candidat** = critère d'éligibilité (ex: "le candidat doit justifier d'un CA annuel ≥ 86 100 €"). Ce n'est PAS le montant du marché. Range-le dans `references_exigees.autres_exigences`, pas dans `montant_marche`.
  - **Honoraires d'expertise / frais accessoires** = composantes du prix, pas le montant total.

- **RÉVISION DES PRIX** dans `revision_prix` — souvent dans le CCAP, pas le RC :
  - `type` : choisis EXACTEMENT parmi cette liste fermée :
    `indexation` (prix révisés périodiquement selon un ou plusieurs indices)
    `actualisation` (prix actualisable une seule fois entre soumission et démarrage)
    `ferme` (prix ferme et non révisable sur toute la durée)
    `non_communique` (rien sur le sujet dans les pièces analysées)
  - `indices_utilises` : liste des indices cités (ex: ["SYNTEC", "ILC", "INSEE BT01"]). Mets [] vide si type ≠ indexation.
  - `ponderation` : description de la formule de pondération en clair (ex: "65% SYNTEC + 15% ILC + 20% partie fixe"). Recopie du CCAP si présent, sinon null.
  - `periodicite` : trimestrielle / semestrielle / annuelle / autre / null
  - `formule_revision` : recopie textuelle de la formule du CCAP si lisible (ex: "Pn = P0 × (0.65 × SYNTECn/SYNTEC0 + 0.15 × ILCn/ILC0 + 0.20)"). Sinon null.
  - `source_extraction` : où c'est dans le DCE (ex: "CCAP article 5.3")
  - `commentaire` : impact pour le candidat en 1 phrase (ex: "Formule mixte SYNTEC+ILC : favorable en inflation mais complexe à anticiper pour le chiffrage initial"). Sinon null.
  - NE PAS INVENTER. Si tu n'as pas trouvé la révision des prix dans les pièces fournies, mets `type: "non_communique"` et le reste à null/vide. Ne suppose pas qu'il y a forcément du SYNTEC.

- Pour `alertes_candidat`, identifie ce qui peut RÉELLEMENT bloquer une candidature (hors prix).
- Pour `alertes_prix`, focus sur les signaux liés au prix : seuil OAB, plafond budgétaire, pondération atypique, bordereau complexe à risque d'erreur, etc.
- Pour `points_differenciants_attendus`, ce qui distingue les bons dossiers selon le RC. Chaque item est un objet `{{libelle, exemple, source}}` :
  - `libelle` : courte phrase nommant l'axe différenciant
  - `exemple` : 1-2 phrases concrètes montrant comment un candidat peut s'en servir
  - `source` : référence DCE si l'axe est valorisé explicitement par un passage ; null si tu l'infères du contexte sans citation
{few_shot_examples}
{regles_specifiques}
{regles_v2}
Réponds UNIQUEMENT avec le JSON, sans aucun texte autour."""


# === Règles v2 (refonte pipeline) : 3 voies de montant + critères stricts + BOAMP ===
REGLES_V2 = """
=== RÈGLES v2 — MONTANT EN 3 VOIES (bloc `montant_3_voies`) ===

Tu remplis `montant_3_voies` EN PLUS de `montant_marche` (rétro-compat).

VOIE 1 — MONTANT PUBLIÉ (priorité absolue) :
- Cherche dans le DCE (RC, AAPC, CCAP, DUME, BPU, formulaires) tout montant publié
  explicitement : estimation HT, montant maximum d'accord-cadre, budget/enveloppe annoncé.
- Si trouvé → `voie_1_eur` = nombre, `voie_1_source` = référence textuelle précise
  (ex: "RC §3.2 page 8"). Sinon `voie_1_eur` = null.

VOIE 2 — ESTIMATION BOTTOM-UP (UNIQUEMENT si Voie 1 absente) :
- Si et seulement si `voie_1_eur` est null, tu PRODUIS une estimation à partir des
  caractéristiques du projet présentes dans le DCE. NE te rabats PAS trop vite sur
  l'indisponibilité : sur l'ingénierie, le conseil et les services, il y a presque
  toujours un volume (jours-homme, ETP, durée, surface, nb d'unités) permettant un ordre
  de grandeur. Tu n'écris `voie_2_disponible=false` qu'en DERNIER recours.
- Règles : tu listes chaque hypothèse dans `voie_2_hypotheses` ({hypothese, valeur}) AVEC
  sa source DCE ; tu appliques des ratios de référence métier explicites adaptés au secteur
  du marché ; tu n'inventes AUCUN chiffre non justifiable depuis le DCE.
- FOURCHETTE `voie_2_min_eur`/`voie_2_max_eur` (jamais une valeur unique) : tu ne fais varier
  qu'UNE SEULE dimension à la fois — la PLUS incertaine (en général le prix/ratio unitaire OU
  la quantité, pas les deux) — en gardant l'autre à sa valeur centrale. NE combine JAMAIS
  min_quantité × min_prix puis max_quantité × max_prix : cela produit des fourchettes
  irréalistes (rapport max/min > 2). Vise un rapport max/min ≈ 1,3-1,8. Indique dans une
  hypothèse quelle dimension tu fais varier (ex : « quantité fixée à 1200 m² ; ratio varié
  2000-2400 €/m² »).
- Si le DCE est vraiment trop pauvre (aucun volume chiffrable) → `voie_2_disponible=false`
  + `voie_2_raison_indisponible` (raison précise). Ce cas doit rester rare.
- (Voie 3 = rapprochement DECP en aval, hors LLM : ne la calcule pas ici.)

=== RÈGLES v2 — CRITÈRES : champ `unite_evaluation` ===

Pour CHAQUE sous-critère technique (à tous les niveaux), tu renseignes `unite_evaluation` :
- "euro"        → le sous-critère est noté sur une grandeur MONÉTAIRE (coût, coût global,
                  €/tonne CO2, pénalités chiffrées). ⚠️ Un critère environnemental CHIFFRÉ
                  en euros est "euro" (→ famille prix), PAS "points".
- "delai_jours" → noté sur un délai en jours/semaines.
- "points"      → tout le reste (mémoire technique, méthodologie, RSE notée en points,
                  références, qualité, performance).
Le code dérive la famille prix/valeur_technique à partir de `unite_evaluation` ("euro"=prix).

=== RÈGLES v2 — CONTEXTE BOAMP (bloc CONTEXTE DU MARCHÉ) ===

Le contexte inclut des champs BOAMP issus de l'avis (indépendants du DCE) : `acheteur_siren`,
`acheteur_nuts`, `nature`, `procedure_libelle`, `est_europeen`, `criteres_attribution_boamp`
(flags ["sociaux","environnementaux"]), `nombre_lots`/`lots`. Tu les utilises pour :
1. Vérifier la cohérence (si BOAMP annonce N lots et que tu n'en vois qu'un dans le DCE,
   signale-le dans `synthese_marche`).
2. Compléter ce que le DCE ne donne pas.
3. Affiner la Voie 2 (un marché européen implique des seuils minimaux applicables).
"""

import hashlib as _hashlib
# Version du prompt v2 (SHA-256 des règles ajoutées) — stockée par brief (prompt_version_sha).
PROMPT_V2_SHA = _hashlib.sha256(REGLES_V2.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Appel API
# ---------------------------------------------------------------------------

def _check_anthropic():
    if Anthropic is None:
        raise RuntimeError(
            "Le SDK anthropic n'est pas installé. Lance :\n"
            "    pip install anthropic"
        )
    cle = _obtenir_cle_api()
    if not cle:
        raise RuntimeError(
            "Clé API Anthropic introuvable.\n"
            "Définis-la de l'une de ces 2 façons :\n"
            "  1. Crée un fichier .env à la racine du projet contenant :\n"
            "       ANTHROPIC_API_KEY=sk-ant-XXXXXXXX\n"
            "  2. Ou définis la variable d'environnement ANTHROPIC_API_KEY"
        )


# Champs universels : présents dans tous les briefs quel que soit le secteur.
# Le filtre anti-hallucination préserve ces clés en plus des blocs sectoriels
# des presets ciblés. Tout autre top-level non-listé sera supprimé.
_CHAMPS_UNIVERSELS_BRIEF = {
    "synthese_marche",
    "domaines_metier",
    "raison_classification",
    "bareme_notation",
    "montant_marche",
    "montant_3_voies",
    "revision_prix",
    "alertes_prix",
    "references_exigees",
    "lots",
    "calendrier",
    "alertes_candidat",
    "points_differenciants_attendus",
    # Bloc neutre injecté pour les marchés HORS-PÉRIMÈTRE (aucun preset) — doit
    # survivre au filtre anti-hallucination quand blocs_autorises est vide.
    "caracteristiques_metier",
    # Méta techniques (peuvent apparaître si réponse partielle)
    "_appel_llm",
    "_meta",
}


def _famille_depuis_unite(unite) -> str:
    """unite_evaluation → famille critère (v2). 'euro' → prix (résout le bug RSE €/CO2)."""
    u = (str(unite or "")).strip().lower()
    if u == "euro":
        return "prix"
    if u in ("points", "delai_jours", "delai", ""):
        return "valeur_technique"
    return "valeur_technique"


def _num(v):
    """Float ou None (tolère les pondérations en string)."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def deriver_criteres_attribution_plat(bareme: dict) -> list:
    """Dérive le schéma PLAT `criteres_attribution_plat` depuis le bareme hiérarchique.

    Entrée 'Prix' (valeur_prix_pct) + critères techniques NORMALISÉS pour sommer à
    valeur_technique_pct (les pondérations de sous-critères sont tantôt en part-de-100,
    tantôt en part-du-technique : on renormalise → la somme plat = prix_pct + tech_pct).
    Famille par `unite_evaluation` (euro → prix : résout le bug RSE €/CO2). Si pas de
    sous-critères, une entrée 'Valeur technique' globale (= valeur_technique_pct).
    Format : [{libelle, famille, ponderation_pct, unite_evaluation, source_texte}].
    """
    bareme = bareme or {}
    pct_prix = _num(bareme.get("valeur_prix_pct"))
    pct_tech = _num(bareme.get("valeur_technique_pct"))
    sous = [sc for sc in (bareme.get("sous_criteres_techniques") or []) if isinstance(sc, dict)]
    plat = []

    prix_part = pct_prix if (pct_prix and pct_prix > 0) else 0
    if prix_part:
        plat.append({"libelle": "Prix", "famille": "prix", "ponderation_pct": pct_prix,
                     "unite_evaluation": "euro", "source_texte": (bareme.get("prix") or {}).get("source")})

    raw = [_num(sc.get("ponderation_pct")) for sc in sous]
    raw_sum = sum(r for r in raw if r) or 0

    def _entrees_sous(scale):
        """Construit les entrées plates des sous-critères. scale=None → poids bruts."""
        out = []
        for sc, r in zip(sous, raw):
            p = round(r * scale, 1) if (scale is not None and r) else r
            out.append({"libelle": sc.get("libelle"),
                        "famille": _famille_depuis_unite(sc.get("unite_evaluation")),
                        "ponderation_pct": p, "unite_evaluation": sc.get("unite_evaluation"),
                        "source_texte": sc.get("source")})
        return out

    if sous and raw_sum > 0:
        # D1 — les sous-critères encodent déjà des poids ABSOLUS (part-de-100) si
        # `prix + Σsous ≈ 100`. Dans ce cas on les garde TELS QUELS : ne pas rescaler
        # sur `valeur_technique_pct`, scalaire souvent sous-renseigné par le LLM (il
        # met 60 alors que ses propres sous-critères somment à 75 = la vraie valeur).
        if 98 <= prix_part + raw_sum <= 102:
            plat.extend(_entrees_sous(None))
        # Sinon, si un `valeur_technique_pct` fiable existe, les sous-critères sont
        # exprimés en part-DU-technique → on les renormalise pour sommer à pct_tech.
        elif pct_tech and pct_tech > 0:
            plat.extend(_entrees_sous(pct_tech / raw_sum))
        # Ni absolus ni rescalables : poids bruts (best effort, alerte possible).
        else:
            plat.extend(_entrees_sous(None))
    elif pct_tech and pct_tech > 0:
        # D2 — sous-critères absents OU tous non pondérés (raw_sum=0). La partie
        # technique NE DOIT PAS s'évaporer (bug : scale=None → ponderation_pct=None →
        # 60-70% techniques perdus). Repli : entrée unique « Valeur technique » = pct_tech.
        plat.append({"libelle": "Valeur technique", "famille": "valeur_technique",
                     "ponderation_pct": pct_tech, "unite_evaluation": "points", "source_texte": None})
    else:
        # Ni pct_tech ni poids de sous-critères : best effort (alerte légitime possible).
        plat.extend(_entrees_sous(None))
    return plat


def valider_criteres_plat(plat: list) -> dict:
    """Validation post-LLM du schéma plat. Retourne somme + flags d'alerte."""
    pcts = [c.get("ponderation_pct") for c in plat
            if isinstance(c.get("ponderation_pct"), (int, float))]
    somme = round(sum(pcts), 1)
    a_prix = any(c.get("famille") == "prix"
                 and isinstance(c.get("ponderation_pct"), (int, float))
                 and c["ponderation_pct"] > 0 for c in plat)
    # D3 — flag vivant : un critère sans pondération exploitable (None) échappe à la
    # somme et signale un barème mal extrait. (L'ancien test `famille=="non_classe"`
    # était mort : `_famille_depuis_unite` ne renvoie jamais cette valeur.)
    non_classe = any(c.get("ponderation_pct") is None
                     or c.get("famille") == "non_classe" for c in plat)
    return {
        "criteres_somme_ponderations": somme,
        "criteres_alerte_somme_incorrecte": not (98 <= somme <= 102),
        "criteres_alerte_pas_de_prix": not a_prix,
        "criteres_alerte_non_classes": non_classe,
    }


def post_traiter_extraction_v2(data: dict) -> dict:
    """Post-traitement v2 (après extraire_via_llm) : dérive le plat, valide, versionne.

    Ajoute `criteres_attribution_plat`, les flags `criteres_*`, `montant_voie_*` (aplatis
    depuis `montant_3_voies`), `version_extraction_llm='2'`, `prompt_version_sha`,
    `extraction_v2_a_verifier`. Non destructif (conserve le bareme hiérarchique).
    """
    if not isinstance(data, dict):
        return data
    plat = deriver_criteres_attribution_plat(data.get("bareme_notation") or {})
    data["criteres_attribution_plat"] = plat
    validation = valider_criteres_plat(plat)
    data.update(validation)

    m3 = data.get("montant_3_voies") or {}
    v1 = m3.get("voie_1_eur")
    v2_dispo = bool(m3.get("voie_2_disponible"))
    vmin, vmax = m3.get("voie_2_min_eur"), m3.get("voie_2_max_eur")
    hypos = m3.get("voie_2_hypotheses") or []
    data["montant_voie_1_eur"] = v1
    data["montant_voie_1_source"] = m3.get("voie_1_source")
    data["montant_voie_2_disponible"] = v2_dispo
    data["montant_au_moins_une_voie"] = bool(v1) or v2_dispo
    alerte_v1 = bool(v1) != bool(m3.get("voie_1_source"))
    alerte_v2 = v2_dispo and (
        not hypos or not isinstance(vmin, (int, float)) or not isinstance(vmax, (int, float))
        or vmin > vmax)
    data["montant_alerte_coherence"] = alerte_v1 or alerte_v2

    # SYNCHRO montant_marche ← montant_3_voies (l'UI lit encore montant_marche).
    # Si le LLM a laissé montant_marche vide mais rempli une voie, on reporte la
    # valeur/fourchette pour que la fiche affiche un montant. Non destructif : on ne
    # touche pas un montant_marche déjà renseigné.
    mm = dict(data.get("montant_marche") or {})
    if not mm.get("valeur_estimee_euros") and not mm.get("fourchette_min_euros"):
        if v1:
            mm["valeur_estimee_euros"] = v1
            mm["type"] = "estime_explicite"
            mm["source_extraction"] = m3.get("voie_1_source") or mm.get("source_extraction")
            mm.setdefault("commentaire", "Montant publié (Voie 1).")
            data["montant_marche"] = mm
        elif v2_dispo and isinstance(vmin, (int, float)) and isinstance(vmax, (int, float)):
            mm["fourchette_min_euros"] = vmin
            mm["fourchette_max_euros"] = vmax
            mm["valeur_estimee_euros"] = round((vmin + vmax) / 2)
            mm["type"] = "calcule_volumes"
            mm["commentaire"] = ("Estimation bottom-up (Voie 2) : "
                                 + " ; ".join(h.get("hypothese", "") for h in hypos[:2]))[:500]
            data["montant_marche"] = mm

    nb_alertes = sum([validation["criteres_alerte_somme_incorrecte"],
                      validation["criteres_alerte_pas_de_prix"],
                      validation["criteres_alerte_non_classes"],
                      data["montant_alerte_coherence"]])
    data["extraction_v2_a_verifier"] = nb_alertes >= 2
    data["version_extraction_llm"] = "2"
    data["prompt_version_sha"] = PROMPT_V2_SHA
    return data


def _filtrer_hallucinations(data: dict,
                            codes_presets: Optional[list],
                            verbose: bool = False) -> dict:
    """
    Supprime de la sortie LLM les blocs sectoriels qui ne sont pas autorisés
    pour les presets ciblés.

    Le LLM peut halluciner des noms de blocs depuis son entraînement (vu sur
    le 56164 où il a produit `caracteristiques_techniques_chantier`, `volumes`,
    `publics_cibles` etc. alors que le schéma envoyé ne contenait que
    `caracteristiques_si`/`qualifications_si`).

    Args:
        data : dict parsé de la réponse LLM.
        codes_presets : liste des codes presets ciblés (None/[] = fallback
                        union, on autorise tous les blocs sectoriels).
        verbose : log les blocs supprimés.

    Returns:
        Le dict filtré (mutation in-place + retour pour chaînage).
    """
    if not isinstance(data, dict):
        return data
    blocs_autorises = set(_preset.blocs_sectoriels_pour_presets(codes_presets))
    cles_autorisees = _CHAMPS_UNIVERSELS_BRIEF | blocs_autorises
    cles_a_supprimer = [k for k in data.keys() if k not in cles_autorisees]
    if cles_a_supprimer:
        if verbose:
            print(f"  🚫 Filtre anti-hallucination : "
                  f"{len(cles_a_supprimer)} bloc(s) hors-schéma supprimé(s) : "
                  f"{cles_a_supprimer}")
        for k in cles_a_supprimer:
            data.pop(k, None)
    return data


def _resoudre_presets_pour_marche(marche_id: Optional[str]) -> list:
    """
    Pour un marche_id donné, retourne la liste des codes presets pertinents
    en lisant sa classification IA depuis la collection `classifications_ia`.

    Retourne [] (déclenchera le fallback union complète côté builder) si :
    - marche_id est None
    - aucune classification IA n'existe pour ce marché
    - les domaines classifiés ne mappent vers aucun preset installé
      (cas typique : marché classifié `autre`, `fourniture_materiel`, etc.)

    Cette fonction est silencieuse en cas d'erreur (import stockage,
    collection manquante, JSON corrompu) : elle retourne [] et laisse le
    fallback union prendre le relais. Pas de raise pour ne pas bloquer
    l'extraction sur un détail d'environnement.
    """
    if not marche_id:
        return []
    try:
        import stockage as _stockage
        classifs = _stockage.charger("classifications_ia") or {}
        classif = classifs.get(marche_id)
        if not classif:
            return []
        domaines = classif.get("domaines_metier") or []
        codes_domaines = []
        for d in domaines:
            if isinstance(d, dict):
                code = d.get("code")
                if isinstance(code, str) and code:
                    codes_domaines.append(code)
            elif isinstance(d, str) and d:
                codes_domaines.append(d)
        if not codes_domaines:
            return []
        return _preset.presets_pour_domaines(codes_domaines)
    except Exception:
        return []


def extraire_via_llm(texte: str, contexte: dict,
                       verbose: bool = True,
                       max_retries: int = 2) -> Optional[dict]:
    """
    Envoie le texte d'un DCE à Claude et récupère les champs structurés.

    Args:
        texte: texte combiné du RC + CCTP + autres pièces.
        contexte: dict avec id, titre, acheteur, source, etc. (méta du marché).
        verbose: True pour afficher coût estimé et temps.
        max_retries: relance en cas d'erreur API ou JSON invalide.

    Returns:
        dict JSON parsé, ou None si échec définitif.

    Raises:
        budget.BudgetDepasseError : si le quota budget LLM est atteint
                                       (kill-switch ou max_par_jour).
    """
    # === Garde-fou budget (Sprint 3) ===
    import budget as _budget
    marche_id = contexte.get("id") if contexte else None
    decision = _budget.peut_appeler_llm("extraction", marche_id=marche_id)
    if not decision.autorise:
        if verbose:
            print(f"  ⛔ Budget : {decision.raison}")
        _budget.enregistrer_appel(
            type_appel="extraction",
            cout_eur=0.0,
            statut="bloque_budget",
            marche_id=marche_id,
            erreur=decision.raison,
        )
        raise _budget.BudgetDepasseError(decision.raison)

    _check_anthropic()
    if len(texte) > MAX_CHARS_INPUT:
        if verbose:
            print(f"  ⚠ Texte tronqué : {len(texte)} → {MAX_CHARS_INPUT} chars")
        texte = texte[:MAX_CHARS_INPUT]

    # === Routage par classification IA (Sprint 2bis) ===
    # On résout les presets pertinents pour CE marché à partir de sa
    # classification IA (si disponible). Les builders prompt système/utilisateur
    # ne reçoivent que les blocs des presets concernés → résout la collision
    # de clés et concentre le LLM. Fallback sur union complète si pas de
    # classif disponible.
    codes_presets = _resoudre_presets_pour_marche(marche_id)
    if verbose and codes_presets:
        print(f"  → Presets ciblés (via classif IA) : {codes_presets}")
    elif verbose:
        print(f"  → Pas de classif IA exploitable, fallback union complète")

    contexte_str = json.dumps(contexte, ensure_ascii=False, indent=2)
    prompt_user = _construire_prompt_utilisateur(contexte_str, texte, codes_presets)
    prompt_systeme = _construire_prompt_systeme(codes_presets)
    # Assainit les surrogates Unicode orphelins (U+D800-U+DFFF) issus d'extractions
    # PDF bancales : ils font planter l'encodage UTF-8 de la requête API (vu sur de
    # gros DCE → echec_llm silencieux). encode('ignore') les supprime proprement.
    prompt_user = prompt_user.encode("utf-8", "ignore").decode("utf-8", "ignore")
    prompt_systeme = prompt_systeme.encode("utf-8", "ignore").decode("utf-8", "ignore")

    client = Anthropic()

    debut = time.time()
    derniere_erreur = None
    for tentative in range(1, max_retries + 1):
        try:
            if verbose:
                print(f"  → Appel Claude API (tentative {tentative})...")
                print(f"    input ≈ {len(prompt_user)} chars "
                      f"(≈ {len(prompt_user) // 4} tokens)")
            # STREAMING (et non messages.create) : indispensable pour les gros DCE
            # multi-lots dont la génération est longue. En non-streamé, l'appel heurte
            # le timeout de requête du SDK avant la fin (cause des echec_llm sur les
            # briefs lourds). Le streaming garde la connexion vivante tant que des
            # tokens arrivent ; get_final_message() reconstitue le message complet.
            with client.messages.stream(
                model=MODELE,
                max_tokens=MAX_TOKENS_REPONSE,
                system=prompt_systeme,
                messages=[{"role": "user", "content": prompt_user}],
            ) as stream:
                message = stream.get_final_message()
            duree = time.time() - debut
            reponse_text = message.content[0].text if message.content else ""

            in_tokens = message.usage.input_tokens
            out_tokens = message.usage.output_tokens
            cout_usd = (in_tokens * 3 + out_tokens * 15) / 1_000_000
            cout_eur = _budget.estimer_cout_eur(in_tokens, out_tokens)

            if verbose:
                print(f"  ← Réponse en {duree:.1f}s")
                print(f"    tokens in/out : {in_tokens} / {out_tokens}")
                print(f"    coût estimé   : {cout_usd:.4f} $ ({cout_eur:.3f} €)")

            # Parser le JSON
            data_parsee = None
            try:
                data_parsee = json.loads(reponse_text)
            except json.JSONDecodeError:
                # Le LLM a parfois mis du texte autour. Cherche le bloc {...}
                m = re.search(r"\{.*\}", reponse_text, re.DOTALL)
                if m:
                    try:
                        data_parsee = json.loads(m.group(0))
                    except json.JSONDecodeError as e:
                        if verbose:
                            print(f"  ⚠ JSON parse échoue : {e}")

            if data_parsee is not None:
                # Filtre anti-hallucination (Sprint 2bis - Sujet 2b).
                # Le LLM peut produire des blocs sectoriels hors-schéma
                # (vus dans son entraînement). On supprime tout bloc sectoriel
                # qui n'est pas autorisé pour les presets ciblés. Les champs
                # universels (synthese_marche, bareme_notation, etc.) sont
                # toujours conservés.
                data_parsee = _filtrer_hallucinations(
                    data_parsee, codes_presets, verbose=verbose
                )
                # Attache les méta d'appel au dict retourné. Le caller
                # (tendia_extraire ou autre) peut récupérer ces infos et
                # les déplacer dans son propre _meta.
                data_parsee["_appel_llm"] = {
                    "modele": MODELE,
                    "tokens_input": in_tokens,
                    "tokens_output": out_tokens,
                    "cout_eur": cout_eur,
                    "duree_sec": round(duree, 1),
                    "codes_presets": codes_presets,  # 1E : remonté pour le _meta
                }
                # Succès : on log l'appel
                _budget.enregistrer_appel(
                    type_appel="extraction",
                    cout_eur=cout_eur,
                    statut="ok",
                    marche_id=marche_id,
                    tokens_input=in_tokens,
                    tokens_output=out_tokens,
                    duree_ms=int(duree * 1000),
                    modele=MODELE,
                )
                return data_parsee

            # JSON invalide : on retente ou on abandonne
            if tentative < max_retries:
                continue
            if verbose:
                print(f"  ❌ Réponse non-JSON après {max_retries} tentatives")
                print(f"    Début réponse : {reponse_text[:500]}")
            # Log de l'échec JSON (on a quand même payé les tokens)
            _budget.enregistrer_appel(
                type_appel="extraction",
                cout_eur=cout_eur,
                statut="erreur",
                marche_id=marche_id,
                tokens_input=in_tokens,
                tokens_output=out_tokens,
                duree_ms=int(duree * 1000),
                modele=MODELE,
                erreur="reponse_non_json",
            )
            return None
        except Exception as e:
            derniere_erreur = e
            if verbose:
                print(f"  ⚠ Erreur API (tentative {tentative}) : {e}")
            if tentative < max_retries:
                time.sleep(2)
                continue
            # Échec définitif : log erreur sans coût (l'appel a probablement
            # échoué côté réseau, pas de tokens facturés)
            _budget.enregistrer_appel(
                type_appel="extraction",
                cout_eur=0.0,
                statut="erreur",
                marche_id=marche_id,
                modele=MODELE,
                erreur=f"{type(e).__name__}: {e}",
            )
            return None
    return None


if __name__ == "__main__":
    # Test rapide : envoie un texte court à Claude
    texte_test = """RÈGLEMENT DE CONSULTATION
    
    Article 1 - Objet : Le présent marché a pour objet la fourniture de \
    prestations d'insertion professionnelle de type Activ Seniors auprès de \
    1500 demandeurs d'emploi de plus de 45 ans en Nouvelle-Aquitaine.
    
    Article 2 - Durée : 24 mois, reconductibles 1 fois 12 mois.
    
    Article 3 - Critères d'attribution :
    - Valeur technique : 70 points
      - Méthodologie pédagogique : 30 points
      - Qualité de l'équipe : 25 points
      - Adéquation au public : 15 points
    - Valeur prix : 30 points
    
    Article 4 - Les candidats doivent justifier de Qualiopi Actions de \
    formation et d'au moins 3 ans d'expérience dans l'accompagnement de \
    seniors demandeurs d'emploi."""
    contexte = {
        "id": "test",
        "titre": "Marché Activ Seniors test",
        "acheteur": "France Travail Nouvelle-Aquitaine",
    }
    print("Test d'extraction LLM...")
    res = extraire_via_llm(texte_test, contexte, verbose=True)
    if res:
        print()
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print("Échec.")
