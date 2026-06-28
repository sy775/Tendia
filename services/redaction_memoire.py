# -*- coding: utf-8 -*-
"""
APPEL 2 — RÉDACTION DE LA MÉMOIRE (Sprint B).

Rédige toutes les sections de la mémoire (JSON {section_id: texte}) en suivant
à la lettre le plan de rédaction produit par l'appel 1, à partir du digest, du
profil organisme et des éléments du DCE.

MAX_TOKENS_REPONSE = 40000. Coût loggé séparément (cf. guardrails).

⚠️ Module additif. N'intègre rien au pipeline d'extraction.
"""
import concurrent.futures
import json
import time

from services import _memoire_commun as commun
from prompts.redaction_memoire_v1 import (
    PROMPT_SYSTEME,
    PROMPT_UTILISATEUR,
    PROMPT_UTILISATEUR_SECTION,
    PROMPT_UTILISATEUR_REVISION,
    VERSION_PROMPT,
)

MAX_TOKENS_REPONSE = 40000
EST_TOKENS_SORTIE = 30000                # estimation dry-run / garde-fou coût
MAX_TOKENS_SECTION = 9000                # plafond de sortie par section (rédaction parallèle)
MAX_WORKERS_SECTIONS = 8                 # appels de sections simultanés (retry gère les 429)


def _bloc_verbatim(plan_redaction: dict) -> str:
    elems = plan_redaction.get("elements_a_reprendre_verbatim") or []
    if not elems:
        return "(aucun)"
    lignes = []
    for e in elems:
        if isinstance(e, dict):
            src = f" (source : {e.get('source')})" if e.get("source") else ""
            lignes.append(f"- « {e.get('formulation')} »{src}")
        else:
            lignes.append(f"- « {e} »")
    return "\n".join(lignes)


def _bloc_points_attention(plan_redaction: dict) -> str:
    pts = plan_redaction.get("points_attention_specifiques") or []
    return "\n".join(f"- {p}" for p in pts) if pts else "(aucun)"


def rediger_memoire(
    id_marche: str,
    numero_lot: int,
    profil: dict,
    lot: dict,
    digest: dict,
    plan_redaction: dict,
    cctp: str,
    grille_actions: str = "",
    dry_run: bool = False,
    max_cout_eur=None,
    verbose: bool = True,
) -> dict:
    """Lance l'appel 2. Retourne {sections_redigees, usage, cout_eur, version_prompt}.
    En dry_run : {_dry_estim, tokens_in_est} sans appel LLM."""
    user_msg = PROMPT_UTILISATEUR.format(
        lot_intitule=lot.get("intitule"),
        lot_domaine=lot.get("domaine"),
        profil_organisme=json.dumps(profil, ensure_ascii=False, indent=2),
        plan_redaction=json.dumps(plan_redaction, ensure_ascii=False, indent=2),
        elements_verbatim=_bloc_verbatim(plan_redaction),
        points_attention=_bloc_points_attention(plan_redaction),
        grille_actions=grille_actions or "(aucune grille d'actions disponible)",
        digest_json=json.dumps(digest.get("digest", {}), ensure_ascii=False, indent=2),
        cctp_filtre=cctp or "(aucun texte CCTP disponible)",
    )

    tokens_in_est = (len(PROMPT_SYSTEME) + len(user_msg)) // 4
    cout_est = commun.budget.estimer_cout_eur(tokens_in_est, EST_TOKENS_SORTIE)

    if dry_run:
        if verbose:
            print(f"  [DRY-RUN] Appel 2 (rédaction) — ≈ {tokens_in_est} tokens entrée, "
                  f"coût estimé ≈ {cout_est:.3f} € (sortie estimée {EST_TOKENS_SORTIE} tk).")
        return {"_dry_estim": cout_est, "tokens_in_est": tokens_in_est}

    if max_cout_eur is not None and cout_est > max_cout_eur:
        raise RuntimeError(
            f"⛔ ABORT appel 2 : coût estimé {cout_est:.3f} € > plafond {max_cout_eur:.3f} €.")

    commun.llm_extract._check_anthropic()
    if verbose:
        print(f"  → Appel 2 / Sonnet 4.6 ({commun.MODELE})… (≈ {tokens_in_est} tokens entrée)")
    texte, usage = commun.appeler_llm(PROMPT_SYSTEME, user_msg, MAX_TOKENS_REPONSE)
    if usage.get("stop_reason") == "max_tokens" and verbose:
        print("  ⚠ Appel 2 tronqué (max_tokens atteint) — la mémoire peut être incomplète ; "
              "le parsing JSON peut échouer (abort propre si c'est le cas).")
    sections = commun.parser_json_strict(texte, f"appel 2 / {id_marche} lot {numero_lot}")

    if not isinstance(sections, dict) or not sections:
        raise RuntimeError(f"Rédaction vide ou non conforme ({id_marche} lot {numero_lot}).")

    # Contrôle de couverture vs plan (warning, pas abort : le user peut régénérer).
    ids_plan = [s.get("section_id") for s in (plan_redaction.get("plan_sections") or [])
                if isinstance(s, dict)]
    manquantes = [sid for sid in ids_plan if sid not in sections]
    hors_plan = [sid for sid in sections if sid not in ids_plan]
    if verbose:
        if manquantes:
            print(f"  ⚠ Sections du plan NON rédigées ({len(manquantes)}) : {manquantes}")
        if hors_plan:
            print(f"  ⚠ Sections hors plan reçues ({len(hors_plan)}) : {hors_plan}")

    cout = commun.cout_eur(usage)
    if verbose:
        print(f"  ✓ Appel 2 OK — {len(sections)} section(s) rédigée(s) | {cout:.3f} € | "
              f"{usage['tokens_sortie']} tk sortie | {usage['duree_s']}s")
    return {
        "sections_redigees": sections,
        "usage": usage,
        "cout_eur": cout,
        "version_prompt": VERSION_PROMPT,
        "sections_manquantes": manquantes,
        "sections_hors_plan": hors_plan,
    }


# ---------------------------------------------------------------------------
# Rédaction PARALLÈLE — une section par appel, en concurrence (vitesse)
# ---------------------------------------------------------------------------

def _plan_global_compact(plan_redaction: dict) -> str:
    """Vue condensée du plan (titre + objectif + longueur) injectée dans chaque
    appel de section pour la cohérence d'ensemble, sans gonfler les tokens."""
    lignes = []
    for s in (plan_redaction.get("plan_sections") or []):
        if isinstance(s, dict):
            lignes.append(f"- [{s.get('section_id')}] {s.get('titre')} "
                          f"(~{s.get('longueur_cible_pages')}p) : {s.get('objectif')}")
    return "\n".join(lignes)


def _max_tokens_section(spec: dict) -> int:
    """Plafond de sortie calé sur la longueur cible (~700 tokens/page + marge),
    borné [2500, MAX_TOKENS_SECTION]. Évite la sur-génération sans étrangler les
    sections (un budget trop serré tronque le JSON → section perdue)."""
    try:
        pages = float(spec.get("longueur_cible_pages") or 2)
    except (TypeError, ValueError):
        pages = 2.0
    return max(2500, min(MAX_TOKENS_SECTION, int(pages * 700) + 800))


def _extraire_texte_section(data, section_id):
    if isinstance(data, dict):
        txt = data.get(section_id)
        if not isinstance(txt, str):  # le modèle a pu nommer la clé autrement
            txt = next((v for v in data.values() if isinstance(v, str)), None)
        if isinstance(txt, str) and txt.strip():
            return txt
    return None


def _rediger_une_section(spec: dict, contexte_commun: dict, texte_existant=None):
    """Rédige (ou RÉVISE si `texte_existant` fourni) une section, avec RETRY :
    si la réponse est tronquée (max_tokens) ou non parsable, on relance avec un
    budget de tokens augmenté plutôt que d'abandonner. Retourne
    (section_id, texte, usage_cumulé)."""
    section_id = spec.get("section_id")
    if texte_existant and texte_existant.strip():
        template, extra = PROMPT_UTILISATEUR_REVISION, {"texte_actuel": texte_existant}
    else:
        template, extra = PROMPT_UTILISATEUR_SECTION, {}
    user_msg = template.format(
        section_id=section_id,
        section_plan=json.dumps(spec, ensure_ascii=False, indent=2),
        **extra, **contexte_commun,
    )
    base = _max_tokens_section(spec)
    cumul = {"tokens_entree": 0, "tokens_sortie": 0, "duree_s": 0.0, "stop_reason": None}
    derniere = "?"
    for tentative in range(3):
        mt = min(MAX_TOKENS_SECTION, int(base * (1.7 ** tentative)))
        texte, usage = commun.appeler_llm(PROMPT_SYSTEME, user_msg, mt)
        cumul["tokens_entree"] += usage["tokens_entree"]
        cumul["tokens_sortie"] += usage["tokens_sortie"]
        cumul["duree_s"] = round(cumul["duree_s"] + usage["duree_s"], 1)
        if usage.get("stop_reason") == "max_tokens":
            derniere = "tronquée (max_tokens)"
            continue  # budget trop court → on relance plus grand
        try:
            data = commun.parser_json_strict(texte, f"section {section_id}")
        except Exception as e:
            derniere = f"{type(e).__name__}"
            continue
        txt = _extraire_texte_section(data, section_id)
        if txt is not None:
            return section_id, txt, cumul
        derniere = "clé/texte introuvable"
    raise RuntimeError(f"Section '{section_id}' échouée après 3 tentatives ({derniere}).")


def rediger_memoire_parallele(
    id_marche: str,
    numero_lot: int,
    profil: dict,
    lot: dict,
    digest: dict,
    plan_redaction: dict,
    grille_actions: str = "",
    progress_callback=None,
    max_workers: int = MAX_WORKERS_SECTIONS,
    sections_ids=None,
    textes_existants=None,
    verbose: bool = True,
) -> dict:
    """Rédige les sections EN PARALLÈLE (un appel LLM par section).
    `sections_ids` (optionnel) restreint la génération à ces section_id (mode
    « compléter » : on ne régénère que les manquantes). Le contexte injecté reste
    le plan COMPLET, pour la cohérence d'ensemble.
    `progress_callback(faites, total)` est appelé après chaque section. Une
    section qui échoue est laissée manquante (encadré [À COMPLÉTER]) plutôt que
    d'abandonner toute la mémoire."""
    specs = [s for s in (plan_redaction.get("plan_sections") or [])
             if isinstance(s, dict) and s.get("section_id")]
    if sections_ids is not None:
        cibles = set(sections_ids)
        specs = [s for s in specs if s.get("section_id") in cibles]
    total = len(specs)
    contexte_commun = {
        "lot_intitule": lot.get("intitule"),
        "lot_domaine": lot.get("domaine"),
        "profil_organisme": json.dumps(profil, ensure_ascii=False, indent=2),
        "plan_global": _plan_global_compact(plan_redaction),
        "elements_verbatim": _bloc_verbatim(plan_redaction),
        "points_attention": _bloc_points_attention(plan_redaction),
        "grille_actions": grille_actions or "(aucune grille d'actions disponible)",
        "digest_json": json.dumps(digest.get("digest", {}), ensure_ascii=False, indent=2),
    }

    commun.llm_extract._check_anthropic()
    if verbose:
        print(f"  → Appel 2 PARALLÈLE / Sonnet 4.6 — {total} sections, "
              f"{max_workers} en simultané…")
    if progress_callback:
        progress_callback(0, total)

    textes_existants = textes_existants or {}
    sections, usages = {}, []
    faites = 0
    debut = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_rediger_une_section, spec, contexte_commun,
                          textes_existants.get(spec.get("section_id"))): spec for spec in specs}
        for fut in concurrent.futures.as_completed(futs):
            spec = futs[fut]
            sid = spec.get("section_id")
            try:
                sid, txt, usage = fut.result()
                sections[sid] = txt
                usages.append(usage)
            except Exception as e:
                print(f"    ⚠ Section '{sid}' échouée (laissée à compléter) : {type(e).__name__}: {e}")
            faites += 1
            if progress_callback:
                progress_callback(faites, total)
            if verbose:
                print(f"    ✓ {faites}/{total} sections rédigées")
    duree = round(time.time() - debut, 1)

    tokens_in = sum(u["tokens_entree"] for u in usages)
    tokens_out = sum(u["tokens_sortie"] for u in usages)
    cout = commun.budget.estimer_cout_eur(tokens_in, tokens_out)
    ids_plan = [s.get("section_id") for s in specs]
    manquantes = [sid for sid in ids_plan if sid not in sections]
    if verbose:
        print(f"  ✓ Appel 2 (parallèle) OK — {len(sections)}/{total} sections | {cout:.3f} € | "
              f"{tokens_out} tk sortie | {duree}s"
              + (f" | ⚠ {len(manquantes)} manquante(s)" if manquantes else ""))
    return {
        "sections_redigees": sections,
        "usage": {"tokens_entree": tokens_in, "tokens_sortie": tokens_out,
                  "duree_s": duree, "stop_reason": None},
        "cout_eur": cout,
        "version_prompt": VERSION_PROMPT,
        "sections_manquantes": manquantes,
        "sections_hors_plan": [],
    }
