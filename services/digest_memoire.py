# -*- coding: utf-8 -*-
"""
DIGEST MÉMOIRE (Sprint A) — génération LAZY d'un digest narratif par lot.

Préalable au générateur de mémoire technique (.docx, Sprint B). Un digest est
généré à la demande pour UN lot, stocké en base (kv_storage / `digests_memoire`)
et mutualisé pour les users suivants.

⚠️ N'INTÈGRE RIEN au pipeline d'extraction existant. Module additif, appelé
uniquement depuis le CLI `scripts/generer_digest_memoire.py`.
"""
import json
import os
import time
from datetime import datetime, timezone
from typing import Optional

import stockage
import pdf_extract
import tendia_extraire
import llm_extract
import budget
from anthropic import Anthropic

from prompts.digest_memoire_v1 import (
    PROMPT_SYSTEME_DIGEST,
    PROMPT_UTILISATEUR_DIGEST,
    VERSION_PROMPT,
    CLES_REQUISES,
)

COLLECTION = "digests_memoire"
MODELE = llm_extract.MODELE                  # claude-sonnet-4-6
MAX_TOKENS_REPONSE = 24000                   # le digest est structuré mais détaillé (relevé : IT tronqué à 16k)
MAX_TOKENS_CONTEXTE_CCTP = 80_000            # cap d'entrée CCTP (≈ 320k chars)
EST_TOKENS_SORTIE = 6000                     # estimation pour dry-run / garde-fou coût
REPERTOIRE_DCE = os.path.join("data", "dce")


def cle_digest(id_marche: str, numero_lot) -> str:
    return f"digest_memoire__{id_marche}__lot_{numero_lot}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trouver_lot(brief: dict, numero_lot) -> Optional[dict]:
    for l in (brief.get("lots") or []):
        if isinstance(l, dict) and str(l.get("numero")) == str(numero_lot):
            return l
    return None


def _normaliser(s: str) -> str:
    import unicodedata
    s = (s or "").lower()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return s


def _fichier_concerne_lot(nom: str, numero_lot, intitule_lot: str) -> bool:
    """Heuristique : le nom de fichier vise-t-il ce lot ?"""
    n = _normaliser(nom)
    marqueurs = [f"lot_{numero_lot}", f"lot {numero_lot}", f"lot{numero_lot}",
                 f"lot-{numero_lot}", f"lot 0{numero_lot}", f"lot0{numero_lot}",
                 f"lot_0{numero_lot}"]
    if any(m in n for m in marqueurs):
        return True
    # tokens significatifs de l'intitulé (≥ 5 lettres) présents dans le nom de fichier
    toks = [t for t in _normaliser(intitule_lot).split() if len(t) >= 5]
    return any(t in n for t in toks)


def charger_cctp_lot(id_marche: str, lot: dict, verbose: bool = True):
    """Charge le texte CCTP/DCE filtré pour un lot.
    Retourne (texte_concatene, infos) où infos = {fichiers_utilises, mode_filtre,
    tronque, chars}."""
    dossier = os.path.join(REPERTOIRE_DCE, id_marche)
    if not os.path.isdir(dossier):
        return "", {"fichiers_utilises": [], "mode_filtre": "aucun_dce",
                    "tronque": False, "chars": 0}
    tendia_extraire._dezipper_dossier(dossier, verbose=False)
    pieces = pdf_extract.extraire_dossier(dossier, verbose=False)  # {nom: {texte,...}}
    if not pieces:
        return "", {"fichiers_utilises": [], "mode_filtre": "aucun_texte",
                    "tronque": False, "chars": 0}

    numero = lot.get("numero")
    intitule = lot.get("intitule") or ""
    cibles = {nom: info for nom, info in pieces.items()
              if _fichier_concerne_lot(nom, numero, intitule)}
    if cibles:
        mode = "par_lot"
    else:
        # Fallback : pas de filtre clair par lot → tout le DCE du marché.
        cibles = pieces
        mode = "fallback_tout_dce"

    blocs, total_chars = [], 0
    cap_chars = MAX_TOKENS_CONTEXTE_CCTP * 4  # ≈ 4 chars/token
    tronque = False
    utilises = []
    for nom in sorted(cibles):
        texte = (cibles[nom].get("texte") or "")
        if not texte.strip():
            continue
        bloc = f"\n\n=== PIÈCE : {nom} ===\n\n{texte}"
        if total_chars + len(bloc) > cap_chars:
            reste = cap_chars - total_chars
            if reste > 500:
                blocs.append(bloc[:reste])
                utilises.append(nom + " (tronqué)")
            tronque = True
            if verbose:
                print(f"  ⚠ Cap CCTP {MAX_TOKENS_CONTEXTE_CCTP} tokens atteint — "
                      f"contexte tronqué (pièce {nom} et suivantes).")
            break
        blocs.append(bloc)
        utilises.append(nom)
        total_chars += len(bloc)

    return "".join(blocs), {"fichiers_utilises": utilises, "mode_filtre": mode,
                            "tronque": tronque, "chars": total_chars}


def _criteres_publies_texte(bareme: dict) -> str:
    """Aplatit les critères PUBLIÉS du barème (libellé + pondération + source)."""
    if not bareme:
        return "Barème non extrait."
    lignes = [f"Valeur technique : {bareme.get('valeur_technique_pct')}% — "
              f"Prix : {bareme.get('valeur_prix_pct')}%"]

    def _walk(noeuds, prof):
        for sc in noeuds or []:
            if not isinstance(sc, dict):
                continue
            src = f" (source : {sc.get('source')})" if sc.get("source") else ""
            lignes.append("  " * prof + f"- {sc.get('libelle')} : "
                          f"{sc.get('ponderation_pct')}%{src}")
            _walk(sc.get("sous_criteres"), prof + 1)

    _walk(bareme.get("sous_criteres_techniques"), 1)
    prix = bareme.get("prix") or {}
    if prix:
        lignes.append(f"- Prix — type formule : {prix.get('type_formule')} ; "
                      f"{prix.get('formule_explicite') or ''}")
    return "\n".join(lignes)


def _appeler_llm(user_msg: str):
    """Appel Sonnet 4.6 (streaming). Retourne (data_json, usage)."""
    client = Anthropic()
    debut = time.time()
    with client.messages.stream(
        model=MODELE,
        max_tokens=MAX_TOKENS_REPONSE,
        system=PROMPT_SYSTEME_DIGEST,
        messages=[{"role": "user", "content": user_msg}],
    ) as stream:
        message = stream.get_final_message()
    duree = time.time() - debut
    texte = message.content[0].text if message.content else ""
    texte = texte.strip()
    if texte.startswith("```"):
        texte = texte.split("```", 2)[1].lstrip("json").strip().rstrip("`").strip()
    try:
        data = json.loads(texte)
    except json.JSONDecodeError:
        import re
        m = re.search(r"\{.*\}", texte, re.DOTALL)
        data = json.loads(m.group(0)) if m else None
    return data, {
        "tokens_entree": message.usage.input_tokens,
        "tokens_sortie": message.usage.output_tokens,
        "duree_s": round(duree, 1),
    }


# ---------------------------------------------------------------------------
# Fonction core
# ---------------------------------------------------------------------------

def generer_digest_memoire_lot(
    id_marche: str,
    numero_lot: int,
    force: bool = False,
    max_cout_eur: Optional[float] = None,
    dry_run: bool = False,
    verbose: bool = True,
) -> Optional[dict]:
    """Génère (ou retourne) le digest mémoire d'un lot. Voir docstring module."""
    cle = cle_digest(id_marche, numero_lot)

    # 1. Digest déjà présent ?
    if not force:
        existant = stockage.lire(COLLECTION, cle)
        if existant:
            if verbose:
                print(f"  ↩ Digest déjà en base ({cle}) — pas d'appel LLM "
                      f"(utiliser --force pour régénérer).")
            return existant

    # 2. Brief
    brief = stockage.lire("briefs_extraits", id_marche)
    if not brief:
        raise ValueError(f"Brief introuvable pour {id_marche} (collection briefs_extraits).")

    # 3. Lot ciblé
    lot = _trouver_lot(brief, numero_lot)
    if not lot:
        nums = [l.get("numero") for l in (brief.get("lots") or []) if isinstance(l, dict)]
        raise ValueError(f"Lot {numero_lot} introuvable dans {id_marche}. "
                         f"Lots disponibles : {nums}")

    # 4. CCTP filtré
    cctp, infos_cctp = charger_cctp_lot(id_marche, lot, verbose=verbose)
    if verbose:
        print(f"  CCTP : {len(infos_cctp['fichiers_utilises'])} pièce(s) "
              f"[{infos_cctp['mode_filtre']}], {infos_cctp['chars']} chars"
              + (" (TRONQUÉ)" if infos_cctp["tronque"] else ""))

    bareme = brief.get("bareme_notation") or {}
    user_msg = PROMPT_UTILISATEUR_DIGEST.format(
        lot_intitule=lot.get("intitule"),
        lot_domaine=lot.get("domaine"),
        lot_particularites=lot.get("particularites"),
        lot_cout_min=lot.get("cout_estime_min_eur"),
        lot_cout_max=lot.get("cout_estime_max_eur"),
        bareme_notation=json.dumps(bareme, ensure_ascii=False),
        criteres_publies=_criteres_publies_texte(bareme),
        cctp_filtre=cctp or "(aucun texte CCTP disponible)",
    )

    # 5. Dry-run : estimation, pas d'appel
    tokens_in_est = (len(PROMPT_SYSTEME_DIGEST) + len(user_msg)) // 4
    cout_est = budget.estimer_cout_eur(tokens_in_est, EST_TOKENS_SORTIE)
    if dry_run:
        print(f"  [DRY-RUN] {id_marche} lot {numero_lot} — "
              f"≈ {tokens_in_est} tokens entrée, coût estimé ≈ {cout_est:.3f} € "
              f"(sortie estimée {EST_TOKENS_SORTIE} tk). Aucun appel LLM.")
        return None

    # 6. Garde-fou coût
    if max_cout_eur is not None and cout_est > max_cout_eur:
        print(f"  ⛔ ABORT : coût estimé {cout_est:.3f} € > plafond {max_cout_eur:.3f} € "
              f"({id_marche} lot {numero_lot}).")
        return None

    # 7. Appel LLM
    llm_extract._check_anthropic()
    if verbose:
        print(f"  → Appel Sonnet 4.6 ({MODELE})… (≈ {tokens_in_est} tokens entrée)")
    data, usage = _appeler_llm(user_msg)
    if data is None:
        raise RuntimeError(f"Réponse LLM non parsable en JSON ({id_marche} lot {numero_lot}).")

    # 8. Validation de structure
    manquantes = [k for k in CLES_REQUISES if k not in data]
    if manquantes:
        raise RuntimeError(f"Digest incomplet, clés manquantes : {manquantes} "
                           f"({id_marche} lot {numero_lot}).")

    cout_eur = budget.estimer_cout_eur(usage["tokens_entree"], usage["tokens_sortie"])
    digest_obj = {
        "id_marche": id_marche,
        "numero_lot": lot.get("numero"),
        "intitule_lot": lot.get("intitule"),
        "domaine_lot": lot.get("domaine"),
        "version_prompt": VERSION_PROMPT,
        "genere_le": datetime.now(timezone.utc).isoformat(),
        "digest": {k: data.get(k) for k in CLES_REQUISES},
        "_meta": {
            "cout_eur": cout_eur,
            "tokens_entree": usage["tokens_entree"],
            "tokens_sortie": usage["tokens_sortie"],
            "modele": MODELE,
            "duree_s": usage["duree_s"],
            "cctp_fichiers": infos_cctp["fichiers_utilises"],
            "cctp_mode_filtre": infos_cctp["mode_filtre"],
            "cctp_tronque": infos_cctp["tronque"],
        },
    }

    # 9. Stockage + retour
    stockage.ecrire(COLLECTION, cle, digest_obj)
    if verbose:
        print(f"  ✓ Digest généré & stocké ({cle}) — "
              f"{cout_eur:.3f} € | {usage['tokens_sortie']} tk sortie | "
              f"{usage['duree_s']}s")
    return digest_obj
