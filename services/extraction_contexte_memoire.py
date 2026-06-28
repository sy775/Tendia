# -*- coding: utf-8 -*-
"""
APPEL 1 — EXTRACTION DU CONTEXTE MÉMOIRE (Sprint B).

Produit le PLAN DE RÉDACTION (JSON) qui pilotera la rédaction (appel 2), à
partir du digest du lot, du DCE sur disque, du profil organisme et du barème.
Détecte un éventuel cadre de réponse .docx imposé par l'acheteur.

MAX_TOKENS_REPONSE = 16000. Coût loggé séparément (cf. guardrails).

⚠️ Module additif. N'intègre rien au pipeline d'extraction.
"""
import json
import os
import unicodedata

import pdf_extract
from services import _memoire_commun as commun
from prompts.extraction_contexte_memoire_v1 import (
    PROMPT_SYSTEME,
    PROMPT_UTILISATEUR,
    VERSION_PROMPT,
    CLES_REQUISES,
)

# Spec Sprint B : 16000. Relevé en batch validation (2026-06-21) : le plan de
# rédaction d'un gros lot (BTP 56995, IT 56097) dépasse 16k tokens de sortie et
# se fait tronquer → abort propre. Relevé à 32000 (output facturé au token réel,
# impact coût négligeable) pour laisser de la marge. Flaggé à Younes.
MAX_TOKENS_REPONSE = 32000
EST_TOKENS_SORTIE = 8000                 # estimation dry-run / garde-fou coût
MAX_CHARS_TEMPLATE = 30_000              # extrait du template acheteur injecté au prompt


def _normaliser(s: str) -> str:
    s = (s or "").lower()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return s


# Motifs de détection d'un cadre de réponse acheteur (cf. spec « DÉTECTION
# TEMPLATE ACHETEUR »). Chaque motif est un couple de jeux de tokens : le nom de
# fichier doit contenir AU MOINS un token de chaque jeu.
_MOTIFS_TEMPLATE = [
    (("cadre",), ("reponse", "memoire", "technique")),
    (("annexe",), ("memoire", "technique")),
    (("modele", "modèle"), ("memoire", "technique")),
    (("trame",), ("reponse", "memoire")),
]


def detecter_template_acheteur(id_marche: str, verbose: bool = True):
    """Cherche un fichier .docx « cadre de réponse / trame mémoire » dans
    data/dce/<id_marche>/. Retourne (chemin, nom, texte_extrait) ou (None, None, None).

    Si plusieurs candidats : le plus volumineux (heuristique : plus de contenu
    structurel). La confirmation finale revient au LLM (appel 1)."""
    dossier = os.path.join(commun.REPERTOIRE_DCE, id_marche)
    if not os.path.isdir(dossier):
        return None, None, None

    candidats = []
    for racine, _dirs, fichiers in os.walk(dossier):
        for nom in fichiers:
            if not nom.lower().endswith(".docx"):
                continue
            n = _normaliser(nom)
            for jeu_a, jeu_b in _MOTIFS_TEMPLATE:
                if any(t in n for t in jeu_a) and any(t in n for t in jeu_b):
                    chemin = os.path.join(racine, nom)
                    try:
                        taille = os.path.getsize(chemin)
                    except OSError:
                        taille = 0
                    candidats.append((taille, chemin, nom))
                    break

    if not candidats:
        return None, None, None

    candidats.sort(reverse=True)              # plus volumineux d'abord
    _taille, chemin, nom = candidats[0]
    texte = pdf_extract.extraire_docx(chemin) or ""
    if verbose:
        print(f"  📄 Cadre de réponse acheteur candidat : {nom} "
              f"({len(texte)} chars extraits)"
              + (f" — {len(candidats)} candidats, plus volumineux retenu"
                 if len(candidats) > 1 else ""))
    return chemin, nom, texte[:MAX_CHARS_TEMPLATE]


def _bloc_template(nom, texte) -> str:
    if not nom:
        return ("Aucun cadre de réponse .docx détecté sur le DCE. "
                "Structure la mémoire selon le RC / les critères / un squelette universel.")
    return (f"Fichier candidat : {nom}\n"
            f"--- DÉBUT EXTRAIT DU CADRE ---\n{texte}\n--- FIN EXTRAIT DU CADRE ---\n"
            f"Confirme s'il s'agit bien d'un cadre de réponse à épouser, et extrais sa structure.")


def extraire_contexte_memoire(
    id_marche: str,
    numero_lot: int,
    id_user: str,
    profil: dict,
    brief: dict,
    lot: dict,
    digest: dict,
    cctp: str,
    grille_actions: str = "",
    dry_run: bool = False,
    max_cout_eur=None,
    verbose: bool = True,
) -> dict:
    """Lance l'appel 1. Retourne :
      {plan_redaction, template_acheteur_chemin, usage, cout_eur, _dry_estim}.
    En dry_run : renvoie {_dry_estim} sans appel LLM."""
    bareme, criteres_txt = commun.bareme_et_criteres(brief)
    tmpl_chemin, tmpl_nom, tmpl_texte = detecter_template_acheteur(id_marche, verbose=verbose)

    user_msg = PROMPT_UTILISATEUR.format(
        lot_intitule=lot.get("intitule"),
        lot_domaine=lot.get("domaine"),
        profil_organisme=json.dumps(profil, ensure_ascii=False, indent=2),
        bareme_notation=json.dumps(bareme, ensure_ascii=False),
        criteres_publies=criteres_txt,
        grille_actions=grille_actions or "(aucune grille d'actions disponible)",
        digest_json=json.dumps(digest.get("digest", {}), ensure_ascii=False, indent=2),
        template_acheteur=_bloc_template(tmpl_nom, tmpl_texte),
        cctp_filtre=cctp or "(aucun texte CCTP disponible)",
    )

    tokens_in_est = (len(PROMPT_SYSTEME) + len(user_msg)) // 4
    cout_est = commun.budget.estimer_cout_eur(tokens_in_est, EST_TOKENS_SORTIE)

    if dry_run:
        if verbose:
            print(f"  [DRY-RUN] Appel 1 (extraction contexte) — ≈ {tokens_in_est} tokens "
                  f"entrée, coût estimé ≈ {cout_est:.3f} €.")
        return {"_dry_estim": cout_est, "tokens_in_est": tokens_in_est,
                "template_acheteur_chemin": tmpl_chemin}

    if max_cout_eur is not None and cout_est > max_cout_eur:
        raise RuntimeError(
            f"⛔ ABORT appel 1 : coût estimé {cout_est:.3f} € > plafond {max_cout_eur:.3f} €.")

    commun.llm_extract._check_anthropic()
    if verbose:
        print(f"  → Appel 1 / Sonnet 4.6 ({commun.MODELE})… (≈ {tokens_in_est} tokens entrée)")
    texte, usage = commun.appeler_llm(PROMPT_SYSTEME, user_msg, MAX_TOKENS_REPONSE)
    if usage.get("stop_reason") == "max_tokens" and verbose:
        print("  ⚠ Appel 1 tronqué (max_tokens atteint) — le parsing JSON va probablement échouer.")
    data = commun.parser_json_strict(texte, f"appel 1 / {id_marche} lot {numero_lot}")

    manquantes = [k for k in CLES_REQUISES if k not in data]
    if manquantes:
        raise RuntimeError(f"Plan de rédaction incomplet, clés manquantes : {manquantes} "
                           f"({id_marche} lot {numero_lot}).")
    if not isinstance(data.get("plan_sections"), list) or not data["plan_sections"]:
        raise RuntimeError(f"Plan de rédaction sans sections exploitables ({id_marche} lot {numero_lot}).")

    cout = commun.cout_eur(usage)
    if verbose:
        print(f"  ✓ Appel 1 OK — {len(data['plan_sections'])} section(s) planifiée(s) | "
              f"posture={data.get('posture_redaction')} | {cout:.3f} € | "
              f"{usage['tokens_sortie']} tk sortie | {usage['duree_s']}s")

    # Le chemin réel du template n'est conservé que si le LLM confirme le cadre.
    cadre = data.get("cadre_reponse_impose") or {}
    chemin_retenu = tmpl_chemin if (tmpl_chemin and cadre.get("detecte")) else None
    return {
        "plan_redaction": data,
        "template_acheteur_chemin": chemin_retenu,
        "usage": usage,
        "cout_eur": cout,
        "version_prompt": VERSION_PROMPT,
    }
