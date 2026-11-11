"""
tendia/analyse/mode_document.py
-------------------------------
Lecture EXHAUSTIVE d'un DCE, sans troncature (promu de l'expérimentation exp_gemini,
commit 3ba9a4b ; prompts repris sans modification) :

  1) analyse de chaque pièce avec les questions propres à son type (RC, CCAP, CCTP,
     BPU/DPGF/DQE, AE, annexe), chaque information sourcée (pièce + page + extrait) ;
  2) fusion dans le schéma JSON de prod (prompt de prod, les notes par pièce
     remplaçant le texte brut) ;
  3) contrôle de complétude des 6 champs critiques et recherche ciblée dans la pièce
     concernée si un champ manque ;
  4) sans LLM : `_sources` (pièce, page, extrait ≤ 200 caractères, et `verifie` :
     l'extrait est retrouvé dans le texte de la page citée) et `_lecture` (statut de
     chaque pièce, `pct_non_lu`).

Aucune troncature : une pièce trop longue pour un appel est découpée par pages. Un DCE
dont le coût estimé dépasse le plafond est sauté et noté, jamais tronqué.

Tous les appels passent par llm_router.call_llm(task="analyse", type_appel="extraction") :
modèle par défaut de la tâche (Gemini argon), repli Sonnet 4.6, kill switch et journal
llm_appels assurés par le routeur.

Point d'entrée : lire_dce(marche_id, dossier_dce, contexte, codes_presets, ...).
"""

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from tendia.analyse import llm_router
from tendia.analyse import pieces as P
# Sources vérifiées et taux de lecture (sans LLM) : module à part, réexporté ici.
from tendia.analyse.sources_lecture import (  # noqa: F401
    CHAMPS_SOURCES, LONGUEUR_MAX_EXTRAIT, construire_sources, normaliser_extrait,
    tableau_lecture, verifier_extrait)
from tendia.core import budget
from tendia.core import logs as tendia_logs

SYSTEME_PIECE = (
    "Tu es un expert des marchés publics français de travaux (bâtiment, BTP). Tu lis UNE pièce "
    "d'un Dossier de Consultation des Entreprises (DCE) et tu en extrais les informations "
    "demandées, intégralement et sans rien inventer.\n"
    "Règles :\n"
    "- Chaque information cite sa source : numéro(s) de page selon les marqueurs [[Page N]] "
    "(ou nom de feuille [[Feuille X]]) et un court extrait textuel exact.\n"
    "- Information absente de la pièce → valeur null. Ne déduis pas, ne complète pas avec des "
    "connaissances générales.\n"
    "- Recopie les chiffres (pondérations, montants, taux, délais, dates) exactement.\n"
    "- Signale dans `autres_informations_importantes` tout élément susceptible d'influencer la "
    "décision de candidater, le prix ou la recevabilité de l'offre, même hors questions.\n"
    "- Réponds UNIQUEMENT en JSON valide, sans bloc markdown."
)

QUESTIONS = {
    "RC": {
        "criteres_attribution": "Critères de jugement des offres avec pondérations (%, points), sous-critères "
                                "et leurs pondérations, formule de notation du prix.",
        "criteres_par_lot": "Différences de critères ou pondérations selon les lots, le cas échéant.",
        "pieces_candidature": "Liste des pièces exigées au titre de la candidature.",
        "pieces_offre": "Liste des pièces exigées au titre de l'offre (mémoire technique, BPU, DPGF, AE, planning…).",
        "date_limite_remise": "Date ET heure limites de remise des offres (format AAAA-MM-JJ HH:MM).",
        "date_limite_questions": "Date limite pour poser des questions / demandes de renseignements.",
        "visite": "Visite de site : obligatoire / facultative / non prévue ; modalités, dates, contact, "
                  "attestation de visite exigée ?",
        "variantes": "Variantes autorisées ou interdites ; prestations supplémentaires éventuelles (PSE) "
                     "obligatoires ou non.",
        "lots": "Allotissement : numéro, intitulé, montant estimé de chaque lot ; ou marché non alloti.",
        "montant_estime": "Montant estimé du marché (global ou par lot), HT/TTC, et sa période.",
        "forme_marche": "Forme du marché (ordinaire, accord-cadre à bons de commande, mono/multi-attributaire, "
                        "min/max), tranches fermes/optionnelles.",
        "duree_delais": "Durée du marché, délai d'exécution, reconductions.",
        "procedure": "Type de procédure, négociation prévue ou non.",
        "modalites_remise": "Mode de remise (plateforme, signature électronique, format), durée de validité des offres.",
        "conditions_participation": "Capacités exigées : CA minimum, références, qualifications (Qualibat, RGE…), "
                                    "assurances, niveaux minimaux.",
    },
    "CCAP": {
        "penalites": "Pénalités : retard, absence aux réunions, non-respect du planning, propreté, documents "
                     "(montants/formules, plafonds).",
        "delais_execution": "Délais d'exécution, période de préparation, délais par lot/phase.",
        "avance": "Avance : taux, conditions, garantie exigée, possibilité d'y renoncer.",
        "retenue_garantie": "Retenue de garantie : taux, substitution par garantie à première demande / caution.",
        "revision_prix": "Prix fermes/actualisables/révisables : indices (BT, TP…), formule, périodicité, mois zéro.",
        "paiement": "Modalités et délai de paiement, acomptes, situations mensuelles.",
        "assurances": "Assurances exigées (RC, décennale, dommages-ouvrage…).",
        "sous_traitance": "Règles de sous-traitance / cotraitance (solidarité du mandataire…).",
        "reception_garanties": "Réception, garantie de parfait achèvement, autres garanties.",
        "clauses_particulieres": "Clauses sociales/environnementales, insertion (nombre d'heures), clauses "
                                 "inhabituelles ou risquées pour le titulaire.",
    },
    "CCTP": {
        "objet_consistance": "Objet et consistance des travaux, localisation, surfaces/quantités clés.",
        "exigences_techniques": "Exigences techniques principales et performances attendues.",
        "normes_reglementation": "Normes, DTU, réglementations citées (RE2020, ERP, amiante…).",
        "certifications_qualifications": "Certifications/qualifications exigées (Qualibat, RGE, habilitations, "
                                         "agréments, ACERMI…).",
        "materiaux_equipements": "Matériaux, équipements ou marques prescrits (et équivalence admise ?).",
        "contraintes_chantier": "Contraintes : site occupé, horaires, phasage, accès, nuisances, sécurité, "
                                "désamiantage, coactivité.",
        "essais_controles_documents": "Essais, contrôles, documents à produire (PAQ, DOE, plans d'exécution…).",
    },
    "BPU_DPGF_DQE": {
        "nature_document": "BPU, DPGF, DQE, détail estimatif ? Lot concerné.",
        "nb_postes": "Nombre total de postes/lignes de prix.",
        "postes_principaux": "Postes les plus significatifs (désignation, unité, quantité) — jusqu'à 40, en "
                             "priorisant les quantités/importances élevées.",
        "montants_renseignes": "Prix ou totaux déjà renseignés par l'acheteur (estimation), le cas échéant.",
        "observations": "Particularités : options, PSE, prix à zéro interdits, quantités indicatives…",
    },
    "AE": {
        "lot": "Lot concerné.",
        "montant": "Montant ou forme de prix (montant pré-rempli, min/max d'accord-cadre).",
        "duree_delais": "Durée / délai d'exécution indiqués.",
        "avance": "Renonciation à l'avance ou mention de l'avance.",
        "autres": "Autres engagements spécifiques (PSE, variantes, tranches).",
    },
    "annexe": {
        "nature_document": "Nature de la pièce (CCAG, DC1/DC2, planning, PGC, diagnostic amiante/plomb, étude "
                           "de sol, cadre de mémoire, avis de publicité…).",
        "informations_cles": "Toutes les informations qui concernent la candidature, l'offre, le prix, les "
                             "délais, les obligations ou les risques du titulaire.",
    },
}

SUPPLEMENT_SOURCES = """

EXIGENCES SUPPLÉMENTAIRES (expérimentation) :
1. Ajoute à la racine du JSON un objet "_sources" : pour chaque champ renseigné important, une entrée
   "chemin.du.champ" (ex. "bareme_notation", "calendrier.date_limite_offres", "montant_marche",
   "dossier_candidature.pieces_a_fournir", "lots", "complements_dce.visite") →
   [{"document": "nom exact de la pièce", "page": "numéro de page ou feuille"}].
2. Ajoute à la racine un objet "complements_dce" :
   {"visite": {"obligatoire": true/false/null, "modalites": "..."},
     "variantes": {"autorisees": true/false/null, "pse": "..."},
     "penalites": "...", "avance": "...", "retenue_garantie": "...", "delais_execution": "...",
     "normes_certifications": ["..."], "date_limite_questions": "..."}
   (null quand l'information est absente).
Ces deux objets s'ajoutent au schéma ci-dessus ; ne modifie pas le reste du schéma."""

EN_TETE_NOTES = ("[Le DCE a été analysé pièce par pièce. Ci-dessous, les informations extraites de CHAQUE "
                 "pièce, avec leur source (pièce, pages, extrait). Construis le JSON demandé uniquement à "
                 "partir de ces notes ; en cas de contradiction entre pièces, privilégie le RC pour la "
                 "consultation, le CCAP pour les clauses administratives, l'AE pour les montants, et "
                 "signale la contradiction dans alertes_candidat.]")

CHAMPS_CRITIQUES = {
    "criteres_ponderations": {
        "present": lambda b: bool((b.get("bareme_notation") or {}).get("valeur_technique_pct") is not None
                                  or (b.get("bareme_notation") or {}).get("sous_criteres_techniques")),
        "pieces": ("RC", "annexe"),
        "question": "Quels sont les critères de jugement des offres et leurs pondérations (prix, technique, "
                    "sous-critères) ?",
        "format": '{"valeur_technique_pct": n, "valeur_prix_pct": n, "autres_criteres": [{"libelle": "...", '
                  '"ponderation_pct": n}], "sous_criteres_techniques": [{"libelle": "...", "ponderation_pct": n}]}',
    },
    "date_limite": {
        "present": lambda b: bool((b.get("calendrier") or {}).get("date_limite_offres")),
        "pieces": ("RC", "annexe", "AE"),
        "question": "Quelle est la date (et l'heure) limite de remise des offres ?",
        "format": '"AAAA-MM-JJ HH:MM"',
    },
    "pieces_exigees": {
        "present": lambda b: bool((b.get("dossier_candidature") or {}).get("pieces_a_fournir")),
        "pieces": ("RC",),
        "question": "Quelles pièces le candidat doit-il fournir (candidature et offre) ?",
        "format": '["pièce 1", "pièce 2", "..."]',
    },
    "visite": {
        "present": lambda b: ((b.get("complements_dce") or {}).get("visite") or {}).get("obligatoire") is not None,
        "pieces": ("RC", "CCAP", "CCTP"),
        "question": "Une visite des lieux / du site est-elle obligatoire, facultative ou non prévue ? Modalités ?",
        "format": '{"obligatoire": true/false, "modalites": "..."}',
    },
    "montant": {
        "present": lambda b: (b.get("montant_marche") or {}).get("valeur_estimee_euros") is not None,
        "pieces": ("RC", "AE", "annexe", "BPU_DPGF_DQE", "CCAP"),
        "question": "Quel est le montant estimé du marché (ou des lots, ou les montants min/max de "
                    "l'accord-cadre), en euros HT ?",
        "format": '{"valeur_estimee_euros": n, "fourchette_min_euros": n, "fourchette_max_euros": n, '
                  '"commentaire": "..."}',
    },
    "lots": {
        "present": lambda b: bool(b.get("lots")) or "non alloti" in json.dumps(b, ensure_ascii=False).lower(),
        "pieces": ("RC", "AE", "annexe"),
        "question": "Le marché est-il alloti ? Si oui, liste des lots (numéro, intitulé, montant estimé).",
        "format": '{"alloti": true/false, "lots": [{"numero": n, "intitule": "...", "montant_estime_eur": n}]}',
    },
}


def version_prompts() -> str:
    """Empreinte des prompts du mode document (traçabilité : extra.prompt_version)."""
    base = json.dumps([SYSTEME_PIECE, QUESTIONS, SUPPLEMENT_SOURCES, EN_TETE_NOTES,
                       {k: [v["question"], v["format"]] for k, v in CHAMPS_CRITIQUES.items()}],
                      ensure_ascii=False, sort_keys=True)
    return "doc-" + hashlib.sha256(base.encode("utf-8")).hexdigest()[:10]


class Suivi:
    """Cumul des appels LLM d'une lecture de DCE (partagé entre threads)."""

    def __init__(self, marche_id: Optional[str] = None, modele: Optional[str] = None):
        self.marche_id = marche_id
        self.modele = modele          # None : modèle par défaut de la tâche analyse (+ repli)
        self.cout_eur = 0.0
        self.nb_appels = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.modeles = {}             # modèle réellement utilisé -> nombre d'appels
        self.nb_replis = 0
        self._verrou = threading.Lock()

    def noter(self, r) -> None:
        with self._verrou:
            self.nb_appels += 1
            self.cout_eur += float(getattr(r, "cout_total_eur", 0) or getattr(r, "cout_eur", 0) or 0)
            self.tokens_in += int(getattr(r, "tokens_in", 0) or 0)
            self.tokens_out += int(getattr(r, "tokens_out", 0) or 0)
            if getattr(r, "modele", None):
                self.modeles[r.modele] = self.modeles.get(r.modele, 0) + 1
            if getattr(r, "repli", False):
                self.nb_replis += 1

    def bilan(self) -> dict:
        return {"cout_eur": round(self.cout_eur, 6), "nb_appels": self.nb_appels,
                "tokens_in": self.tokens_in, "tokens_out": self.tokens_out,
                "modeles": dict(self.modeles), "nb_replis": self.nb_replis}


def _cfg_doc() -> dict:
    return llm_router.config().get("mode_document") or {}


def _modele_effectif(modele: Optional[str]) -> str:
    """Id complet du modèle (None et les alias « gemini » / « claude » sont résolus)."""
    return llm_router.resoudre_modele("analyse", modele)


def _chars_par_token(modele: Optional[str]) -> float:
    c = _cfg_doc().get("chars_par_token") or {}
    return float(c.get(llm_router.fournisseur(_modele_effectif(modele)), 3.0))


def decouper(texte: str, max_chars: int) -> list:
    """Découpe aux marqueurs de page pour rester sous max_chars par morceau."""
    if len(texte) <= max_chars:
        return [texte]
    blocs = texte.split("\n[[")
    morceaux, courant = [], ""
    for i, b in enumerate(blocs):
        b = ("\n[[" + b) if i else b
        if courant and len(courant) + len(b) > max_chars:
            morceaux.append(courant)
            courant = ""
        while len(b) > max_chars:            # page géante : coupe brute
            morceaux.append(b[:max_chars])
            b = b[max_chars:]
        courant += b
    if courant:
        morceaux.append(courant)
    return morceaux


def _appel_json(user, documents, suivi: Suivi, version, max_tokens, system=None):
    """Un appel d'analyse. Comme en expérimentation, une réponse qui n'est pas un JSON
    exploitable est relancée une fois avec un rappel du format : cette relance (et le
    repli Sonnet si argon échoue) est faite par llm_router, qui journalise chaque tentative."""
    r = llm_router.call_llm("analyse", user, documents=documents, model=suivi.modele,
                            type_appel="extraction", marche_id=suivi.marche_id,
                            system=system or SYSTEME_PIECE, prompt_version=version,
                            max_tokens=max_tokens, json_strict=True)
    suivi.noter(r)
    return r


_CONSIGNE_VISUELLE = ("La pièce est jointe en PDF : c'est un document SCANNÉ (images), lis-le visuellement. "
                      "Les numéros de page sont ceux du PDF joint.\n")


def _morceaux_piece(piece: dict, max_chars: int) -> list:
    """[(texte, documents)] : parties PDF natives pour une pièce scannée, sinon texte découpé."""
    if piece.get("lecture_visuelle") and piece.get("parties_pdf"):
        return [("", [p]) for p in piece["parties_pdf"]]
    texte = P.texte_piece(piece)
    return [(m, []) for m in (decouper(texte, max_chars) if texte.strip() else [""])]


# ---------------------------------------------------------------------------
# 1. Analyse par pièce
# ---------------------------------------------------------------------------

def analyser_piece(piece: dict, contexte: dict, suivi: Suivi, version: str) -> dict:
    questions = QUESTIONS[piece["type"]]
    q_txt = "\n".join(f"- {k} : {v}" for k, v in questions.items())
    fmt = ('{"type_confirme": "RC", "informations": {'
           + ", ".join(f'"{k}": {{"valeur": null, "pages": [], "extrait": null}}' for k in questions)
           + '}, "autres_informations_importantes": [{"info": "texte", "pages": [1], "extrait": "citation"}]}'
           + "\n(type_confirme ∈ RC, CCAP, CCTP, BPU_DPGF_DQE, AE, annexe ; « valeur » : texte, nombre, "
             "liste ou objet ; « pages » : liste de numéros ou de noms de feuille. JSON strictement valide : "
             "guillemets intérieurs échappés, aucun commentaire.)")
    max_chars = int(int(_cfg_doc().get("max_tokens_entree_par_appel", 350000)) * _chars_par_token(suivi.modele))
    morceaux = _morceaux_piece(piece, max_chars)
    resultats, cout = [], 0.0
    for i, (m, documents) in enumerate(morceaux, 1):
        partie = f" (partie {i}/{len(morceaux)})" if len(morceaux) > 1 else ""
        user = (f"PIÈCE : {piece['nom']}{partie} — type présumé : {piece['type']}\n"
                f"MARCHÉ : {json.dumps(contexte, ensure_ascii=False)}\n\n"
                f"QUESTIONS :\n{q_txt}\n\nFORMAT DE RÉPONSE :\n{fmt}\n\n"
                + (_CONSIGNE_VISUELLE if documents else f"CONTENU DE LA PIÈCE :\n---\n{m}\n---"))
        r = _appel_json(user, documents, suivi, version + ":piece",
                        _cfg_doc().get("max_tokens_piece", 16000))
        resultats.append({"partie": i, "ok": r.ok, "erreur": r.erreur, "json": r.json})
        cout += float(getattr(r, "cout_total_eur", 0) or getattr(r, "cout_eur", 0) or 0)
    return {"piece": piece["nom"], "type": piece["type"], "nb_pages": piece["nb_pages"],
            "empreinte": piece.get("empreinte"), "cout_eur": round(cout, 6), "resultats": resultats}


# ---------------------------------------------------------------------------
# 2. Fusion + 3. contrôle de complétude
# ---------------------------------------------------------------------------

def _notes_compactes(analyses: list) -> str:
    out = []
    for a in analyses:
        for r in a["resultats"]:
            if r["json"]:
                out.append({"piece": a["piece"], "type": a["type"], "partie": r["partie"], **r["json"]})
            else:
                out.append({"piece": a["piece"], "type": a["type"], "partie": r["partie"],
                            "erreur_lecture": r["erreur"]})
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


def _recherche_ciblee(champ: str, spec: dict, inv: dict, contexte: dict, suivi: Suivi, version):
    candidates = [p for t in spec["pieces"] for p in inv["pieces"] if p["type"] == t]
    for piece in candidates[:6]:
        max_chars = int(int(_cfg_doc().get("max_tokens_entree_par_appel", 350000)) * _chars_par_token(suivi.modele))
        for m, documents in _morceaux_piece(piece, max_chars):
            user = (f"RECHERCHE CIBLÉE dans la pièce « {piece['nom']} » ({piece['type']}) du marché "
                    f"{contexte.get('id')}.\nQuestion : {spec['question']}\n"
                    f"Lis attentivement TOUTE la pièce, y compris tableaux et annexes. N'invente rien.\n"
                    f'Réponds en JSON : {{"trouve": true/false, "valeur": {spec["format"]}, '
                    f'"pages": [1], "extrait": "citation exacte"}}\n\n'
                    + (_CONSIGNE_VISUELLE if documents else f"CONTENU :\n---\n{m}\n---"))
            r = _appel_json(user, documents, suivi, version + ":controle", 8000)
            if r.ok and (r.json or {}).get("trouve"):
                return {"statut": "trouve_par_relance", "piece": piece["nom"], **r.json}
    return {"statut": "absent_confirme", "pieces_relues": [p["nom"] for p in candidates[:6]]}


def _appliquer(brief: dict, champ: str, res: dict) -> None:
    v = res.get("valeur")
    src = [{"document": res.get("piece"), "page": p} for p in (res.get("pages") or [None])]
    brief.setdefault("_sources_modele", {})
    if champ == "criteres_ponderations" and isinstance(v, dict):
        bn = brief.setdefault("bareme_notation", {})
        for k in ("valeur_technique_pct", "valeur_prix_pct"):
            if bn.get(k) is None and v.get(k) is not None:
                bn[k] = v[k]
        if not bn.get("sous_criteres_techniques") and v.get("sous_criteres_techniques"):
            bn["sous_criteres_techniques"] = v["sous_criteres_techniques"]
        brief["_sources_modele"]["bareme_notation"] = src
    elif champ == "date_limite" and v:
        brief.setdefault("calendrier", {})["date_limite_offres"] = str(v)
        brief["_sources_modele"]["calendrier.date_limite_offres"] = src
    elif champ == "pieces_exigees" and v:
        brief.setdefault("dossier_candidature", {})["pieces_a_fournir"] = v if isinstance(v, list) else [v]
        brief["_sources_modele"]["dossier_candidature.pieces_a_fournir"] = src
    elif champ == "visite" and isinstance(v, dict):
        brief.setdefault("complements_dce", {})["visite"] = v
        brief["_sources_modele"]["complements_dce.visite"] = src
    elif champ == "montant" and isinstance(v, dict):
        mm = brief.setdefault("montant_marche", {})
        for k in ("valeur_estimee_euros", "fourchette_min_euros", "fourchette_max_euros"):
            if mm.get(k) is None and v.get(k) is not None:
                mm[k] = v[k]
        mm.setdefault("source_extraction", f"{res.get('piece')} p.{res.get('pages')}")
        brief["_sources_modele"]["montant_marche"] = src
    elif champ == "lots" and isinstance(v, dict):
        if v.get("lots"):
            brief["lots"] = [{"numero": l.get("numero"), "intitule": l.get("intitule"),
                              "montant_estime_eur": l.get("montant_estime_eur")} for l in v["lots"]]
        elif v.get("alloti") is False:
            brief.setdefault("complements_dce", {})["allotissement"] = "non alloti"
        brief["_sources_modele"]["lots"] = src


def _post_traiter(brief: dict, codes_presets: list) -> dict:
    """Post-traitement de prod, en préservant les blocs propres au mode document. Les
    sources rendues par le modèle (clé "_sources" du prompt) sont rangées sous
    "_sources_modele" : "_sources" est reconstruit et vérifié sans LLM (construire_sources)."""
    from tendia.analyse import llm_extract as LE
    sources_modele = brief.pop("_sources", None)
    extras = {k: brief.pop(k) for k in ("complements_dce",) if k in brief}
    LE._filtrer_hallucinations(brief, codes_presets, verbose=False)
    LE._normaliser_codes_domaines(brief, verbose=False)
    brief.update(extras)
    brief["_sources_modele"] = sources_modele if isinstance(sources_modele, dict) else {}
    return brief


def _prompts_prod(contexte: dict, texte: str, codes_presets: list) -> tuple:
    from tendia.analyse import llm_extract as LE
    ctx = json.dumps(contexte, ensure_ascii=False, indent=2)
    user = LE._construire_prompt_utilisateur(ctx, texte, codes_presets) + SUPPLEMENT_SOURCES
    return LE._construire_prompt_systeme(codes_presets), user.encode("utf-8", "ignore").decode("utf-8", "ignore")


def analyser_document(inv: dict, contexte: dict, codes_presets: list, suivi: Suivi = None,
                      version: str = None, verbose: bool = True, trace_precedente: dict = None) -> tuple:
    """Retourne (brief | None, trace). Trace : analyses par pièce, fusion, contrôle.
    `trace_precedente` : les pièces déjà analysées avec succès (même version de prompt) sont
    réutilisées ; seules les pièces en échec sont relancées."""
    suivi = suivi or Suivi(marche_id=inv.get("marche_id"))
    version = version or version_prompts()
    n_workers = int(_cfg_doc().get("pieces_en_parallele", 4))
    cache = {}
    if trace_precedente and trace_precedente.get("version") == version:
        # Reprise par CONTENU : même nom et même empreinte du fichier (une pièce modifiée,
        # ou un homonyme, est relue).
        empreintes = {p["nom"]: p.get("empreinte") for p in inv["pieces"]}
        cache = {a["piece"]: a for a in trace_precedente.get("analyses_pieces") or []
                 if a.get("resultats") and all(r["ok"] for r in a["resultats"])
                 and a.get("empreinte") and a.get("empreinte") == empreintes.get(a.get("piece"))}
    a_faire = [p for p in inv["pieces"] if p["nom"] not in cache]
    if verbose:
        print(f"      mode document : {len(a_faire)} pièce(s) à analyser"
              + (f", {len(cache)} reprise(s) du run précédent" if cache else "")
              + f" ({n_workers} en parallèle)…", flush=True)
    nouvelles = {}
    with ThreadPoolExecutor(n_workers) as ex:
        futurs = [ex.submit(analyser_piece, p, contexte, suivi, version) for p in a_faire]
        erreur = None
        for futur in futurs:
            try:
                a = futur.result()
                nouvelles[a["piece"]] = a
            except BaseException as e:      # kill switch, plafond, interruption
                erreur = erreur or e
    if erreur is not None:
        # Les analyses terminées (et payées) sont rendues à l'appelant pour être tracées.
        erreur.trace_partielle = {"version": version, "analyses_pieces":
                                  list(cache.values()) + list(nouvelles.values()),
                                  "interrompue": True}
        raise erreur
    analyses = [cache.get(p["nom"]) or nouvelles[p["nom"]] for p in inv["pieces"]]
    for a in analyses:
        a["reprise"] = a["piece"] in cache
    echecs = [a["piece"] for a in analyses if not all(r["ok"] for r in a["resultats"])]
    trace = {"version": version, "analyses_pieces": analyses, "pieces_en_echec": echecs}
    if verbose and echecs:
        print(f"      ⚠ {len(echecs)} pièce(s) non analysées : {echecs[:5]}")

    # 2. Fusion dans le schéma de prod
    notes = f"{EN_TETE_NOTES}\n{_notes_compactes(analyses)}"
    systeme, user = _prompts_prod(contexte, notes, codes_presets)
    r = _appel_json(user, [], suivi, version + ":fusion", None, system=systeme)
    trace["fusion"] = r.to_dict()
    if not r.ok:
        return None, trace
    brief = _post_traiter(dict(r.json), codes_presets)

    # 3. Contrôle de complétude + relances ciblées
    controle = {}
    for champ, spec in CHAMPS_CRITIQUES.items():
        try:
            present = spec["present"](brief)
        except Exception:
            present = False
        if present:
            controle[champ] = {"statut": "present"}
            continue
        if verbose:
            print(f"      ↻ champ critique manquant : {champ} → recherche ciblée", flush=True)
        res = _recherche_ciblee(champ, spec, inv, contexte, suivi, version)
        controle[champ] = res
        if res["statut"] == "trouve_par_relance":
            _appliquer(brief, champ, res)
    brief["_controle_completude"] = controle
    trace["controle"] = controle
    return brief, trace


# ---------------------------------------------------------------------------
# 5. Estimation avant appel et point d'entrée
# ---------------------------------------------------------------------------

TOKENS_PAR_PAGE_SCAN = 800        # page de PDF lue visuellement
TOKENS_CONSIGNE_PIECE = 1500      # consigne + questions d'un appel de pièce
TOKENS_SORTIE_PIECE = 2000        # notes rendues pour un appel de pièce
TOKENS_PROMPT_FUSION = 20000      # prompt de prod (système + schéma)
TOKENS_SORTIE_FUSION = 15000


def estimer_cout(inv: dict, modele: str = None, date=None) -> dict:
    """Coût estimé de la lecture AVANT tout appel : caractères / chars_par_token × tarif
    du modèle à `date` (défaut : aujourd'hui), plus les consignes, les sorties attendues
    et la fusion. Aucun appel LLM.

    C'est un ordre de grandeur, pas un plafond de dépense : les tokens de réflexion du
    modèle, les recherches ciblées, les relances et un éventuel repli sur Sonnet (plus
    cher) ne sont pas comptés, et les pièces reprises d'une trace ne sont pas déduites."""
    modele_effectif = _modele_effectif(modele)
    cpt = _chars_par_token(modele_effectif)
    max_chars = int(int(_cfg_doc().get("max_tokens_entree_par_appel", 350000)) * cpt)
    entree, appels = 0.0, 0
    for p in (inv or {}).get("pieces") or []:
        if p.get("lecture_visuelle"):
            entree += (p.get("nb_pages") or 0) * TOKENS_PAR_PAGE_SCAN
            appels += max(1, len(p.get("parties_pdf") or []))
        else:
            entree += (p.get("chars") or 0) / cpt
            appels += max(1, -(-(p.get("chars") or 0) // max_chars))
    sortie_pieces = appels * TOKENS_SORTIE_PIECE
    tokens_entree = int(entree + appels * TOKENS_CONSIGNE_PIECE + sortie_pieces + TOKENS_PROMPT_FUSION)
    tokens_sortie = int(sortie_pieces + TOKENS_SORTIE_FUSION)
    cout = llm_router.estimer_cout_eur(modele_effectif, tokens_entree, tokens_sortie, date)
    if cout is None:
        raise ValueError(f"modèle sans tarif dans config_llm.yaml : {modele_effectif!r} "
                         f"(estimation impossible, le plafond par DCE ne protégerait rien)")
    return {"modele": modele_effectif, "tokens_entree": tokens_entree, "tokens_sortie": tokens_sortie,
            "nb_appels_pieces": appels, "cout_eur": round(cout, 4)}


def lire_dce(marche_id: str, dossier_dce: str, contexte: dict, codes_presets: list,
             max_cout_par_dce: float = 2.5, dry_run: bool = False, verbose: bool = True,
             modele: str = None, reprendre: bool = True, force: bool = False) -> dict:
    """Lit tout le DCE et rend {"ok", "brief", "raison", "estimation", "inventaire",
    "lecture", "cout_eur", "modele", "appels", "duree_s"}.

    - Estimation au-delà de `max_cout_par_dce` : DCE sauté (raison "cout_estime_depasse"),
      noté dans les journaux d'extraction, aucun appel LLM. Jamais de troncature.
    - `dry_run` : inventaire et estimation seulement (raison "dry_run").
    - `reprendre` : les pièces déjà analysées avec succès lors d'une lecture précédente
      (même version de prompts, même contenu de fichier, trace dans
      data/pieces/<id>/_trace.json) ne sont pas repayées. "cout_eur" est le coût de cette
      lecture, "cout_cumule_eur" y ajoute celui des pièces reprises.
    - `force` : l'inventaire est reconstruit même si le dossier n'a pas changé (il l'est
      de toute façon quand la signature du dossier source change).
    Lève budget.BudgetDepasseError si le kill switch ou le plafond mensuel bloque.
    """
    debut = time.time()
    resultat = {"ok": False, "brief": None, "raison": None, "estimation": None, "inventaire": None,
                "lecture": None, "cout_eur": 0.0, "cout_cumule_eur": 0.0, "nb_pieces_reprises": 0,
                "modele": None, "appels": None, "duree_s": 0.0}
    if not dry_run:
        # Avant tout travail, et dans le thread principal (ouvre la base avant les threads).
        budget.verifier_kill_switch("extraction")
    inv = P.inventorier(marche_id, dossier_dce, verbose=verbose, force=force)
    resultat["inventaire"] = inv
    estimation = estimer_cout(inv, modele)
    resultat["estimation"] = estimation
    if verbose:
        print(f"      estimation : {estimation['tokens_entree']:,} tokens d'entrée, "
              f"{estimation['cout_eur']:.2f} € ({estimation['modele']})")
    if dry_run:
        resultat["raison"] = "dry_run"
        return resultat
    if not inv.get("pieces"):
        resultat["raison"] = "aucune_piece_lisible"
        resultat["lecture"] = tableau_lecture(inv, [])
        return resultat
    if max_cout_par_dce is not None and estimation["cout_eur"] > float(max_cout_par_dce):
        resultat["raison"] = "cout_estime_depasse"
        tendia_logs.logger_evenement_marche(
            "extraction", marche_id,
            {"evenement": "dce_saute_cout_estime", "cout_estime_eur": estimation["cout_eur"],
             "max_cout_par_dce_eur": float(max_cout_par_dce), "nb_pieces": len(inv["pieces"])})
        if verbose:
            print(f"      ⊘ DCE sauté : estimation {estimation['cout_eur']:.2f} € > "
                  f"{float(max_cout_par_dce):.2f} € (--max-cout-par-dce). Rien n'est tronqué.")
        return resultat

    suivi = Suivi(marche_id=marche_id, modele=modele)
    version = version_prompts()
    fichier_trace = P.DIR_PIECES / marche_id / "_trace.json"
    trace_precedente = None
    if reprendre and fichier_trace.exists():
        try:
            trace_precedente = json.loads(fichier_trace.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            trace_precedente = None
    def _ecrire_trace(trace: dict) -> None:
        try:
            fichier_trace.parent.mkdir(parents=True, exist_ok=True)
            fichier_trace.write_text(json.dumps(trace, ensure_ascii=False, default=str), encoding="utf-8")
        except OSError:
            pass

    try:
        brief, trace = analyser_document(inv, contexte, codes_presets, suivi=suivi, version=version,
                                         verbose=verbose, trace_precedente=trace_precedente)
    except BaseException as e:
        # Lecture interrompue (kill switch, plafond mensuel, Ctrl+C) : les pièces déjà
        # analysées sont tracées pour ne pas être repayées à la reprise.
        if getattr(e, "trace_partielle", None):
            _ecrire_trace(e.trace_partielle)
        raise
    _ecrire_trace(trace)
    analyses = trace.get("analyses_pieces") or []
    cout_repris = sum(float(a.get("cout_eur") or 0) for a in analyses if a.get("reprise"))
    resultat["lecture"] = tableau_lecture(inv, analyses)
    resultat["appels"] = suivi.bilan()
    resultat["cout_eur"] = round(suivi.cout_eur, 6)
    resultat["cout_cumule_eur"] = round(suivi.cout_eur + cout_repris, 6)
    resultat["nb_pieces_reprises"] = sum(1 for a in analyses if a.get("reprise"))
    resultat["modele"] = (trace.get("fusion") or {}).get("modele")
    resultat["duree_s"] = round(time.time() - debut, 1)
    if brief is None:
        resultat["raison"] = "echec_fusion : " + str((trace.get("fusion") or {}).get("erreur") or "?")[:200]
        return resultat
    brief["_sources"] = construire_sources(brief, analyses, inv)
    brief["_lecture"] = resultat["lecture"]
    resultat["ok"] = True
    resultat["brief"] = brief
    return resultat
