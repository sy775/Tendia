# -*- coding: utf-8 -*-
"""
RÉGÉNÉRATION D'UNE SECTION UNIQUE (Sprint B).

Recharge une mémoire existante depuis kv_storage, relance l'appel 2 sur UNE
seule section avec l'instruction d'ajustement du user, met à jour le JSON en
base, re-assemble le .docx complet, et logue la régénération dans l'historique.

MAX_TOKENS_REPONSE = 16000 (une seule section). Coût loggé dans
`regenerations[]` et cumulé dans `_meta.cout_total_eur`.

⚠️ Module additif. Pas d'auto-régénération en cas d'erreur : log et abort.
"""
import json
from datetime import datetime, timezone

from services import _memoire_commun as commun
from services import assemblage_docx
from prompts.redaction_memoire_v1 import (
    PROMPT_SYSTEME,
    PROMPT_UTILISATEUR_REGENERATION,
    VERSION_PROMPT,
)
from prompts.redaction_memoire_v1 import VERSION_PROMPT as VERSION_REDACTION  # noqa: F401

MAX_TOKENS_REPONSE = 16000
EST_TOKENS_SORTIE = 6000


def _trouver_section_plan(plan_redaction: dict, section_id: str):
    for s in (plan_redaction.get("plan_sections") or []):
        if isinstance(s, dict) and s.get("section_id") == section_id:
            return s
    return None


def regenerer_section(
    memoire_id: str,
    section_id: str,
    instruction_user: str,
    dry_run: bool = False,
    max_cout_eur=None,
    verbose: bool = True,
) -> dict:
    """Régénère `section_id` de la mémoire `memoire_id` selon `instruction_user`.
    Retourne l'objet mémoire mis à jour (ou estimation en dry_run)."""
    memoire = commun.stockage.lire(commun.COLLECTION_MEMOIRES, memoire_id)
    if not memoire:
        raise ValueError(f"Mémoire introuvable en base : {memoire_id} "
                         f"(collection {commun.COLLECTION_MEMOIRES}).")

    plan = memoire.get("plan_redaction") or {}
    spec = _trouver_section_plan(plan, section_id)
    if spec is None:
        ids = [s.get("section_id") for s in (plan.get("plan_sections") or [])
               if isinstance(s, dict)]
        raise ValueError(f"section_id '{section_id}' absent du plan de {memoire_id}. "
                         f"Sections disponibles : {ids}")

    id_marche = memoire["id_marche"]
    numero_lot = memoire["numero_lot"]
    id_user = memoire["id_user"]

    profil = commun.charger_profil_organisme(id_user)
    brief, lot = commun.charger_brief_et_lot(id_marche, numero_lot)
    digest = commun.charger_digest(id_marche, numero_lot)
    cctp, _infos = commun.charger_dce_lot(id_marche, lot, verbose=verbose)

    grille_actions = commun.grille_redaction_lot(brief, lot)
    texte_actuel = (memoire.get("sections_redigees") or {}).get(section_id) or "(section vide)"
    elements_verbatim = "\n".join(
        f"- « {e.get('formulation') if isinstance(e, dict) else e} »"
        for e in (plan.get("elements_a_reprendre_verbatim") or [])
    ) or "(aucun)"

    user_msg = PROMPT_UTILISATEUR_REGENERATION.format(
        lot_intitule=lot.get("intitule"),
        lot_domaine=lot.get("domaine"),
        profil_organisme=json.dumps(profil, ensure_ascii=False, indent=2),
        section_id=section_id,
        section_plan=json.dumps(spec, ensure_ascii=False, indent=2),
        instruction_user=instruction_user,
        texte_actuel=texte_actuel,
        elements_verbatim=elements_verbatim,
        grille_actions=grille_actions,
        digest_json=json.dumps(digest.get("digest", {}), ensure_ascii=False, indent=2),
        cctp_filtre=cctp or "(aucun texte CCTP disponible)",
    )

    tokens_in_est = (len(PROMPT_SYSTEME) + len(user_msg)) // 4
    cout_est = commun.budget.estimer_cout_eur(tokens_in_est, EST_TOKENS_SORTIE)
    if dry_run:
        if verbose:
            print(f"  [DRY-RUN] Régénération '{section_id}' — ≈ {tokens_in_est} tokens "
                  f"entrée, coût estimé ≈ {cout_est:.3f} €. Aucun appel LLM.")
        return {"_dry_estim": cout_est}

    if max_cout_eur is not None and cout_est > max_cout_eur:
        raise RuntimeError(
            f"⛔ ABORT régénération : coût estimé {cout_est:.3f} € > plafond {max_cout_eur:.3f} €.")

    commun.llm_extract._check_anthropic()
    if verbose:
        print(f"  → Régénération '{section_id}' / Sonnet 4.6… (≈ {tokens_in_est} tokens entrée)")
    texte, usage = commun.appeler_llm(PROMPT_SYSTEME, user_msg, MAX_TOKENS_REPONSE)
    if usage.get("stop_reason") == "max_tokens" and verbose:
        print("  ⚠ Régénération tronquée (max_tokens) — parsing possiblement en échec (abort propre).")
    data = commun.parser_json_strict(texte, f"régénération {section_id} / {memoire_id}")

    if section_id not in data or not isinstance(data.get(section_id), str):
        raise RuntimeError(f"La régénération n'a pas produit la clé attendue '{section_id}' "
                           f"(clés reçues : {list(data.keys())}).")

    cout = commun.cout_eur(usage)
    horod = datetime.now(timezone.utc).isoformat()

    # Mise à jour de l'objet mémoire
    memoire.setdefault("sections_redigees", {})[section_id] = data[section_id]
    memoire.setdefault("regenerations", []).append({
        "section_id": section_id,
        "instruction_user": instruction_user,
        "regenere_le": horod,
        "cout_eur": cout,
        "tokens_entree": usage["tokens_entree"],
        "tokens_sortie": usage["tokens_sortie"],
        "version_prompt_redaction": VERSION_PROMPT,
    })
    meta = memoire.setdefault("_meta", {})
    meta["cout_total_eur"] = round((meta.get("cout_total_eur") or 0) + cout, 4)
    meta["duree_totale_s"] = round((meta.get("duree_totale_s") or 0) + usage["duree_s"], 1)

    # Ré-assemblage du .docx complet (même chemin de sortie)
    contexte = commun.construire_contexte(memoire, brief, profil)
    chemin = assemblage_docx.assembler(
        memoire, profil, contexte,
        template_acheteur=memoire.get("template_acheteur"), verbose=verbose)
    memoire["chemin_docx"] = chemin

    commun.stockage.ecrire(commun.COLLECTION_MEMOIRES, memoire_id, memoire)
    if verbose:
        print(f"  ✓ Section '{section_id}' régénérée — {cout:.3f} € | "
              f"{usage['tokens_sortie']} tk sortie | {usage['duree_s']}s")
        print(f"  ✓ Mémoire mise à jour ({memoire_id}) & .docx ré-assemblé : {chemin}")
    return memoire
