"""
matching_exigences.py
---------------------
Confronte les exigences/alertes d'un marché au profil organisme actif.

Pour chaque alerte critique (texte issu du brief LLM), retourne un statut
indiquant si l'organisme est capable d'y répondre ou non :

- "couvert"     ✅  : l'exigence est explicitement couverte par le profil
- "non_couvert" ❌  : le profil prouve que l'organisme ne peut pas répondre
- "a_verifier"  ⚠   : partiellement couvert, ou couvert sous condition
- "inconnu"     ❓  : information non présente au profil, vérif manuelle requise

L'idée : transformer les alertes textuelles en signal actionnable —
le candidat voit immédiatement où il a un trou de capacité.

Heuristiques (mots-clés + champs profil) :
    Qualiopi          → profil.certifications.qualiopi_*
    Local sur <ville> → profil.identite.siege_ville + heuristique
    CA / capacité fin → pas dans profil → inconnu
    BAC+3/+5 etc.     → pas dans profil → à vérifier
    PMSMP / immersion → profil.mots_cles_catalogue
    DR / région       → profil.directions_regionales_couvertes
    Public spécifique → profil.publics_cibles
    NDA déclaration   → pas dans profil → inconnu
    Prix / révision   → pas une exigence go/no-go → renvoie None (non affiché)
"""

from typing import Optional


# Liste de villes pour détection "local sur X obligatoire".
# Limité aux principales métropoles FT (couvre 95% des cas).
_VILLES_FR = {
    "bordeaux", "lyon", "marseille", "toulouse", "lille", "nantes",
    "strasbourg", "rennes", "nice", "montpellier", "paris",
    "saint-étienne", "saint etienne", "tours", "angers", "dijon",
    "grenoble", "le havre", "reims", "metz", "nancy", "amiens",
    "rouen", "limoges", "brest", "clermont-ferrand", "orleans", "orléans",
    "perpignan", "besancon", "besançon", "caen", "mulhouse", "ajaccio",
    "bastia", "fort-de-france", "pointe-à-pitre", "cayenne", "saint-denis",
}


def _texte_minuscule(s: str) -> str:
    return (s or "").lower().strip()


def _villes_mentionnees(texte_lower: str) -> list:
    """Détecte les villes citées dans l'alerte."""
    villes = []
    for v in _VILLES_FR:
        # Match en mot entier (entouré d'espaces ou ponctuation)
        idx = texte_lower.find(v)
        if idx >= 0:
            avant = texte_lower[idx - 1] if idx > 0 else " "
            apres = texte_lower[idx + len(v)] if idx + len(v) < len(texte_lower) else " "
            if not avant.isalpha() and not apres.isalpha():
                villes.append(v.capitalize())
    return villes


def _auto_reponse(profil: dict, cle: str) -> Optional[str]:
    """Cherche une réponse utilisateur déjà saisie pour cette clé d'exigence."""
    if not profil or not cle:
        return None
    rep = (profil.get("auto_reponses_exigences") or {}).get(cle)
    if rep in ("oui", "non"):
        return rep
    return None


def _statut_depuis_reponse(reponse: str, libelle_court: str) -> dict:
    """Construit un statut à partir d'une réponse utilisateur (oui/non)."""
    if reponse == "oui":
        return {
            "statut": "couvert",
            "libelle": "Couvert",
            "detail": f"{libelle_court} — confirmé manuellement",
            "source": "auto_reponse_utilisateur",
        }
    return {
        "statut": "non_couvert",
        "libelle": "Non couvert",
        "detail": f"{libelle_court} — déclaré non couvert manuellement",
        "source": "auto_reponse_utilisateur",
    }


def evaluer_exigence(alerte_texte: str, profil: dict) -> Optional[dict]:
    """Confronte une alerte texte au profil organisme.

    Returns:
        dict avec clés statut, libelle, detail, source — ou None si l'alerte
        ne concerne pas une exigence go/no-go (ex: alerte de cadrage prix).
        statut ∈ {"couvert", "non_couvert", "a_verifier", "inconnu"}

        Pour les statuts "inconnu", inclut une clé `cle_canonique` permettant
        à l'UI de proposer un bouton OUI/NON à l'utilisateur. La réponse est
        ensuite stockée dans profil.auto_reponses_exigences et automatiquement
        appliquée aux marchés suivants présentant la même clé.
    """
    if not alerte_texte or not profil:
        return None

    t = _texte_minuscule(alerte_texte)

    # ----- Alertes de cadrage prix → on n'évalue pas vs profil (non go/no-go)
    if any(mc in t for mc in (
        "prix unique", "bordereau de prix", "révision des prix",
        "révision semestrielle", "indexation", "syntec",
        "moins-disant", "moins disant", "pondération prix",
        "rentabilité", "marge", "convergence des offres",
    )):
        return None

    # ----- 1) Qualiopi -----
    if "qualiopi" in t:
        certs = profil.get("certifications") or {}
        actives = [
            cle.replace("qualiopi_", "")
            for cle in ("qualiopi_actions_formation", "qualiopi_apprentissage",
                         "qualiopi_bilans", "qualiopi_vae")
            if certs.get(cle)
        ]
        if actives:
            return {
                "statut": "couvert",
                "libelle": "Couvert",
                "detail": "Qualiopi " + ", ".join(actives),
                "source": "certifications",
            }
        return {
            "statut": "non_couvert",
            "libelle": "Non couvert",
            "detail": "Aucune Qualiopi déclarée au profil",
            "source": "certifications",
        }

    # ----- 1bis) Certification / qualification professionnelle NOMMÉE -----
    #   Qualibat, Qualifelec, RGE, OPQIBI, Qualisol/PV/PAC/Bois, MASE, CERFF, ISO…
    #   Une certification est par nature VÉRIFIABLE (on la détient ou non) → on émet une
    #   `cle_canonique` spécifique (par certif + niveau) pour proposer le bouton Oui/Non.
    import re as _re
    _CERTIF_NOMS = ("qualibat", "qualifelec", "qualit'enr", "qualit enr", "qualitenr",
                    "opqibi", "opqtecc", "qualisol", "qualipv", "qualipac", "qualibois",
                    "mase", "cerff", "iso 9001", "iso 14001", "iso 27001", "iso 45001",
                    "rge", "qualiroute", "opqformation")
    _CERTIF_GEN = ("certification", "certifié", "certifie", "habilitation",
                   "agrément", "agrement", "qualification professionnelle")
    # Frontières de mot : évite que 'rge' matche 'urgence/charge', 'mase' matche 'masse'…
    def _mot(mc):
        return _re.search(r"\b" + _re.escape(mc) + r"\b", t) is not None
    _nom_cert = next((mc for mc in _CERTIF_NOMS if _mot(mc)), None)
    if _nom_cert or any(_mot(g) for g in _CERTIF_GEN):
        base = _nom_cert or "certification"
        m = _re.search(_re.escape(base) + r"[\s:°n-]*([a-z0-9][a-z0-9 /\-]{0,14})", t)
        suffixe = (m.group(1).strip() if m else "")
        cle = "certif_" + (_re.sub(r"[^a-z0-9]+", "_", (base + "_" + suffixe)).strip("_") or "x")[:44]
        rep = _auto_reponse(profil, cle)
        if rep:
            return _statut_depuis_reponse(rep, "Certification " + base)
        return {
            "statut": "inconnu",
            "libelle": "À confirmer",
            "detail": "Certification / qualification exigée — non vérifiée au profil",
            "source": "—",
            "cle_canonique": cle,
            "question": "Détenez-vous cette certification / qualification ?",
        }

    # ----- 2) Local / présence physique requise dans une ville -----
    a_mot_local = any(mc in t for mc in (
        "local sur", "locaux sur", "local obligatoire", "local requis",
        "local à fournir", "local physique", "local effectif",
        "présence physique", "présence sur", "presence physique",
        "lieu d'intervention", "lieu d intervention", "lieu d'exécution",
        "implantation", "implanté", "implante",
    ))
    villes = _villes_mentionnees(t)
    if a_mot_local and villes:
        siege = ((profil.get("identite") or {}).get("siege_ville") or "").lower()
        siege_couvre = any(v.lower() == siege for v in villes)
        if siege_couvre:
            return {
                "statut": "couvert",
                "libelle": "Couvert",
                "detail": f"Siège à {siege.capitalize()}",
                "source": "identite.siege_ville",
            }
        # Auto-réponse possible pour "local dans <ville>"
        cle = f"local_{villes[0].lower().replace(' ', '_')}"
        rep = _auto_reponse(profil, cle)
        if rep:
            return _statut_depuis_reponse(rep, f"Local à {villes[0]} disponible")
        return {
            "statut": "a_verifier",
            "libelle": "À vérifier",
            "detail": (f"Siège à {siege.capitalize() if siege else 'lieu non renseigné'}, "
                       f"local requis à {', '.join(villes)} — confirmer présence locale"),
            "source": "identite.siege_ville",
            "cle_canonique": cle,
            "question": f"Disposez-vous d'un local à {villes[0]} ?",
        }
    if a_mot_local:
        return {
            "statut": "a_verifier",
            "libelle": "À vérifier",
            "detail": "Local obligatoire — ville à confirmer dans le DCE",
            "source": "—",
        }

    # ----- 3) Capacité financière / CA annuel -----
    if any(mc in t for mc in ("ca annuel", "chiffre d'affaires",
                                "chiffre d affaires", "capacité financière",
                                "capacite financiere", "capacité économique",
                                "seuil financier")):
        # Extraire le montant du seuil si possible
        import re as _re
        m_montant = _re.search(r"(\d[\d\s\u202f]{2,})\s*€", alerte_texte)
        seuil_str = ""
        cle = "ca_min"
        if m_montant:
            montant_brut = _re.sub(r"[\s\u202f]", "", m_montant.group(1))
            try:
                montant = int(montant_brut)
                seuil_str = f" ≥ {montant:,} €".replace(",", " ")
                cle = f"ca_min_{montant}"
            except ValueError:
                pass
        rep = _auto_reponse(profil, cle)
        if rep:
            return _statut_depuis_reponse(rep, f"CA annuel{seuil_str}")
        return {
            "statut": "inconnu",
            "libelle": "Info manquante",
            "detail": f"CA annuel{seuil_str} — non renseigné au profil",
            "source": "—",
            "cle_canonique": cle,
            "question": f"Votre CA annuel moyen sur 3 ans atteint-il {seuil_str.lstrip(' ≥')} ?",
        }

    # ----- 4) Qualification intervenants (BAC+X) -----
    if any(mc in t for mc in ("bac+", "bac +")):
        import re as _re
        m_niveau = _re.search(r"bac\s*\+\s*(\d)", t)
        niveau = m_niveau.group(1) if m_niveau else "3"
        cle = f"qualification_bac{niveau}"
        rep = _auto_reponse(profil, cle)
        if rep:
            return _statut_depuis_reponse(rep, f"Intervenants BAC+{niveau}")
        return {
            "statut": "a_verifier",
            "libelle": "À vérifier",
            "detail": f"Intervenants BAC+{niveau} requis — qualification non renseignée au profil",
            "source": "—",
            "cle_canonique": cle,
            "question": f"Vos intervenants ont-ils au minimum un BAC+{niveau} ?",
        }
    if any(mc in t for mc in ("intervenants avec", "ans d'expérience",
                                "ans d expérience", "expérience minimum")):
        return {
            "statut": "a_verifier",
            "libelle": "À vérifier",
            "detail": "Qualifications des intervenants à confirmer côté équipe",
            "source": "—",
            "cle_canonique": "qualification_experience",
            "question": "Vos intervenants ont-ils l'expérience requise ?",
        }

    # ----- 5) PMSMP / immersion en milieu professionnel -----
    if "pmsmp" in t or "immersion en milieu" in t or "immersion professionnelle" in t:
        mots_cles = profil.get("mots_cles_catalogue") or []
        for m in mots_cles:
            ml = m.lower()
            if "pmsmp" in ml or "immersion" in ml or "mise en situation" in ml:
                return {
                    "statut": "couvert",
                    "libelle": "Couvert",
                    "detail": f"« {m} » au catalogue",
                    "source": "mots_cles_catalogue",
                }
        rep = _auto_reponse(profil, "pmsmp_reseau_entreprises")
        if rep:
            return _statut_depuis_reponse(rep, "Réseau entreprises pour PMSMP/immersion")
        return {
            "statut": "a_verifier",
            "libelle": "À vérifier",
            "detail": "PMSMP/immersion non explicite — réseau entreprises à formaliser",
            "source": "—",
            "cle_canonique": "pmsmp_reseau_entreprises",
            "question": "Disposez-vous d'un réseau d'entreprises pour les PMSMP/immersions ?",
        }

    # ----- 6) NDA / déclaration d'activité formation pro -----
    if any(mc in t for mc in ("nda", "déclaration d'activité",
                                "declaration d activite", "numéro de déclaration",
                                "l.6351-1")):
        certs = profil.get("certifications") or {}
        if certs.get("qualiopi_actions_formation"):
            return {
                "statut": "couvert",
                "libelle": "Couvert",
                "detail": "Activité formation déclarée (Qualiopi formation)",
                "source": "certifications",
            }
        rep = _auto_reponse(profil, "nda_declare")
        if rep:
            return _statut_depuis_reponse(rep, "Déclaration d'activité formation")
        return {
            "statut": "inconnu",
            "libelle": "Info manquante",
            "detail": "NDA non renseigné au profil",
            "source": "—",
            "cle_canonique": "nda_declare",
            "question": "Avez-vous un numéro de déclaration d'activité formation (NDA) ?",
        }

    # ----- 7) Direction régionale / périmètre géo -----
    if any(mc in t for mc in ("direction régionale", "dr couverte",
                                "couverture territoriale", "périmètre géographique",
                                "perimetre geographique")):
        drs = profil.get("directions_regionales_couvertes") or []
        if drs:
            return {
                "statut": "a_verifier",
                "libelle": "À vérifier",
                "detail": f"DR couvertes : {', '.join(drs[:5])}{'…' if len(drs) > 5 else ''}",
                "source": "directions_regionales_couvertes",
            }
        return {
            "statut": "inconnu",
            "libelle": "Info manquante",
            "detail": "Aucune DR renseignée au profil",
            "source": "—",
        }

    # ----- Défaut : pas d'évaluation possible automatiquement -----
    return {
        "statut": "inconnu",
        "libelle": "Vérification manuelle",
        "detail": "Critère non automatisé — à confirmer au cas par cas",
        "source": "—",
    }


def evaluer_alertes(alertes: list, profil: dict) -> list:
    """Évalue chaque alerte du brief. Retourne la liste enrichie de leur statut.

    Conserve les alertes non-évaluables (statut=None) sans badge.
    """
    if not alertes:
        return []
    resultats = []
    for a in alertes:
        statut = evaluer_exigence(a, profil)
        resultats.append({"texte": a, "evaluation": statut})
    return resultats


def synthese_couverture(alertes_evaluees: list) -> dict:
    """Synthèse globale : combien d'alertes par statut.

    Utile pour un teaser de section ("3 couvertes, 1 non couverte, 2 à vérifier").
    """
    compteur = {"couvert": 0, "non_couvert": 0, "a_verifier": 0, "inconnu": 0,
                "non_evaluable": 0, "total": 0}
    for ae in alertes_evaluees:
        compteur["total"] += 1
        ev = ae.get("evaluation")
        if ev is None:
            compteur["non_evaluable"] += 1
        else:
            compteur[ev["statut"]] = compteur.get(ev["statut"], 0) + 1
    return compteur


def verdict_eligibilite(alertes_evaluees: list) -> dict:
    """Verdict consolidé d'éligibilité sur un marché.

    Logique binaire : un marché est éligible OU bloqué. Les statuts ? et !
    sont des RÉSERVES (Tendia n'a pas l'info au profil, mais c'est probablement
    OK et le candidat le saura). Ce ne sont PAS des blocages.

    Retourne :
        {
          "statut": "eligible" | "bloque" | "inconnu",
          "avec_reserves": bool,
          "label_court": "Éligible" | "Non éligible" | "À évaluer",
          "couleur": "green" | "rose" | "stone",
          "icone": "✓" | "✕" | "?",
          "tooltip": "...",
          "compteurs": {...},
          "points_a_lever": [...]   # liste d'alertes en a_verifier, inconnu OU non_couvert
        }

    Règles :
        - "bloque" si au moins 1 alerte en non_couvert (=✕)
        - "eligible" sinon (couvert + éventuelles réserves ?/!)
            - avec_reserves=True s'il y a des ? ou !
            - avec_reserves=False si tout est ✓
        - "inconnu" si aucune alerte évaluable
    """
    if not alertes_evaluees:
        return {
            "statut": "inconnu",
            "avec_reserves": False,
            "label_court": "À évaluer",
            "couleur": "stone",
            "icone": "?",
            "tooltip": "Aucune alerte d'éligibilité extraite du brief.",
            "compteurs": {"total": 0},
            "points_a_lever": [],
        }

    compteurs = synthese_couverture(alertes_evaluees)
    nb_bloque = compteurs.get("non_couvert", 0)
    nb_a_verifier = compteurs.get("a_verifier", 0)
    nb_inconnu = compteurs.get("inconnu", 0)
    nb_couvert = compteurs.get("couvert", 0)
    nb_reserves = nb_a_verifier + nb_inconnu

    # Détails par catégorie pour tooltip
    points_bloquants = []
    points_reserves = []
    for ae in alertes_evaluees:
        ev = ae.get("evaluation") or {}
        statut = ev.get("statut")
        entry = {
            "libelle": ev.get("libelle_court") or ae.get("alerte", "")[:80],
            "detail": ev.get("detail") or "",
            "statut": statut,
        }
        if statut == "non_couvert":
            points_bloquants.append(entry)
        elif statut in ("a_verifier", "inconnu"):
            points_reserves.append(entry)

    # Cas BLOQUÉ : un seul ✕ suffit
    if nb_bloque > 0:
        return {
            "statut": "bloque",
            "avec_reserves": False,
            "label_court": "Non éligible",
            "couleur": "rose",
            "icone": "✕",
            "tooltip": f"{nb_bloque} exigence{'s' if nb_bloque > 1 else ''} non couverte{'s' if nb_bloque > 1 else ''} par le profil organisme.",
            "compteurs": compteurs,
            "points_a_lever": points_bloquants,
        }

    # Cas ÉLIGIBLE AVEC RÉSERVES : couvert + des ? ou !
    if nb_reserves > 0:
        return {
            "statut": "eligible",
            "avec_reserves": True,
            "label_court": "Éligible",
            "couleur": "green",
            "icone": "✓",
            "tooltip": (
                f"Éligible — {nb_couvert} exigence{'s' if nb_couvert > 1 else ''} couverte{'s' if nb_couvert > 1 else ''}, "
                f"{nb_reserves} réserve{'s' if nb_reserves > 1 else ''} à vérifier au cas par cas "
                f"(données non disponibles dans le profil)."
            ),
            "compteurs": compteurs,
            "points_a_lever": points_reserves,
        }

    # Cas ÉLIGIBLE PUR : tout est ✓
    if nb_couvert > 0:
        return {
            "statut": "eligible",
            "avec_reserves": False,
            "label_court": "Éligible",
            "couleur": "green",
            "icone": "✓",
            "tooltip": f"Toutes les exigences ({nb_couvert}) sont couvertes par le profil organisme.",
            "compteurs": compteurs,
            "points_a_lever": [],
        }

    return {
        "statut": "inconnu",
        "avec_reserves": False,
        "label_court": "À évaluer",
        "couleur": "stone",
        "icone": "?",
        "tooltip": "Aucune exigence évaluable (profil absent ou alertes non parsables).",
        "compteurs": compteurs,
        "points_a_lever": [],
    }


def calculer_verdict_pour_marche(id_marche: str, profil: dict) -> Optional[dict]:
    """Helper : charge le brief d'un marché et calcule son verdict d'éligibilité.

    Retourne None si pas de brief disponible (= marché non encore extrait
    par le LLM). Sinon retourne le dict de verdict_eligibilite().
    """
    import json
    import os
    if not profil:
        return None
    chemin = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "data", "extractions", f"{id_marche}.json")
    if not os.path.exists(chemin):
        return None
    try:
        with open(chemin, "r", encoding="utf-8") as f:
            brief = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    alertes = brief.get("alertes_candidat") or []
    if not alertes:
        return None
    evaluees = evaluer_alertes(alertes, profil)
    return verdict_eligibilite(evaluees)
