# -*- coding: utf-8 -*-
"""
Orchestration de la génération d'une mémoire technique (Sprint B).

Source unique partagée par le CLI (`scripts/generer_memoire.py`) ET l'UI
(`tendia_ui.py`) : enchaîne appel 1 (plan) → appel 2 (rédaction) → assemblage
.docx → stockage. Tous les prints sont gardés par `verbose` pour rester muet
quand l'UI l'appelle dans un thread de fond.

⚠️ Module additif. N'intègre rien au pipeline d'extraction.
"""
import time
from datetime import datetime, timezone

import stockage
from services import _memoire_commun as commun
from services import extraction_contexte_memoire as appel1
from services import redaction_memoire as appel2
from services import assemblage_docx


def cle_memoire_existante(id_marche, numero_lot, id_user):
    """Clé de la mémoire LA PLUS RÉCENTE pour ce (marché, lot, user), ou None.
    Les clés se terminent par __<timestamp> (format triable), donc le max
    lexicographique = la version la plus récente (après régénération `force`)."""
    prefixe = f"memoire__{id_marche}__lot_{numero_lot}__{id_user}__"
    matchs = [c for c in stockage.lister_ids(commun.COLLECTION_MEMOIRES) if c.startswith(prefixe)]
    return max(matchs) if matchs else None


def _resoudre_profil(id_user, profil):
    """Retourne (profil_dict, id_user_effectif). Accepte soit un id_user (chargé
    depuis la base / les profils démo), soit un profil déjà résolu (passé par
    l'UI, qui connaît le profil actif)."""
    if profil is not None:
        id_eff = id_user or profil.get("id") or "principal"
        return profil, id_eff
    if not id_user:
        raise ValueError("id_user ou profil requis pour générer une mémoire.")
    return commun.charger_profil_organisme(id_user), id_user


def sections_manquantes_memoire(memoire: dict):
    """Liste des section_id du plan absents (ou vides) dans sections_redigees."""
    plan = (memoire.get("plan_redaction") or {}).get("plan_sections") or []
    secs = memoire.get("sections_redigees") or {}
    ids_ok = {k for k, v in secs.items() if isinstance(v, str) and v.strip()}
    return [s.get("section_id") for s in plan
            if isinstance(s, dict) and s.get("section_id") and s.get("section_id") not in ids_ok]


def reviser_memoire(id_marche, numero_lot, id_user=None, profil=None,
                    verbose=True, progress_callback=None):
    """MUTUALISATION : réutilise le plan ET le texte déjà rédigé d'une mémoire
    existante (PAS d'appel 1). Pour chaque section, REFORMULE le texte existant
    (ton candidat + infos du profil à jour) ; génère celles qui manquaient.
    ~2× plus rapide qu'une régénération complète. Si la révision d'une section
    échoue, son texte précédent est conservé (rien n'est perdu). Retourne l'objet
    mis à jour, ou None s'il n'existe pas de mémoire à réviser."""
    profil, id_user = _resoudre_profil(id_user, profil)
    cle = cle_memoire_existante(id_marche, numero_lot, id_user)
    if not cle:
        return None
    memoire = stockage.lire(commun.COLLECTION_MEMOIRES, cle)
    plan = memoire.get("plan_redaction") or {}
    sections_existantes = dict(memoire.get("sections_redigees") or {})

    brief, lot = commun.charger_brief_et_lot(id_marche, numero_lot)
    digest = commun.charger_digest(id_marche, numero_lot)
    grille = commun.grille_redaction_lot(brief, lot)
    if verbose:
        print(f"  ↻ Révision : plan réutilisé, reformulation de "
              f"{len(plan.get('plan_sections') or [])} section(s) (pas d'appel 1).")

    sous_cb = (lambda f, t: progress_callback("redaction", f, t)) if progress_callback else None
    t0 = time.time()
    r2 = appel2.rediger_memoire_parallele(
        id_marche, numero_lot, profil, lot, digest, plan,
        grille_actions=grille, textes_existants=sections_existantes,
        progress_callback=sous_cb, verbose=verbose)

    # Fusion : les sections révisées/générées écrasent ; une section dont la
    # révision a échoué conserve son texte existant (rien n'est perdu).
    sections = dict(sections_existantes)
    sections.update(r2["sections_redigees"])
    memoire["sections_redigees"] = sections
    memoire["version_prompt_redaction"] = r2["version_prompt"]

    meta = memoire.setdefault("_meta", {})
    meta["cout_total_eur"] = round((meta.get("cout_total_eur") or 0) + r2["cout_eur"], 4)
    meta["duree_totale_s"] = round((meta.get("duree_totale_s") or 0) + round(time.time() - t0, 1), 1)
    meta["sections_manquantes"] = sections_manquantes_memoire(memoire)
    memoire.setdefault("revisions", []).append({
        "revise_le": datetime.now(timezone.utc).isoformat(),
        "sections_revisees": len(r2["sections_redigees"]),
        "cout_eur": r2["cout_eur"],
    })

    if progress_callback:
        progress_callback("assemblage", 0, 0)
    contexte = commun.construire_contexte(memoire, brief, profil)
    memoire["chemin_docx"] = assemblage_docx.assembler(
        memoire, profil, contexte, template_acheteur=memoire.get("template_acheteur"), verbose=verbose)
    stockage.ecrire(commun.COLLECTION_MEMOIRES, cle, memoire)
    if verbose:
        print(f"  ✓ Révision terminée — {r2['cout_eur']:.3f} €")
    return memoire


def generer_memoire(id_marche, numero_lot, id_user=None, profil=None, force=False,
                    completer=False, max_cout_eur=None, dry_run=False, verbose=True,
                    progress_callback=None):
    """Génère une mémoire technique complète. Retourne l'objet mémoire stocké
    (ou None en dry-run / si déjà existante sans force).

    `completer=True` : mode mutualisé — réutilise une mémoire existante et ne
    génère que ses sections manquantes (cf. completer_memoire).
    `progress_callback(etape, faites, total)` (optionnel) suit l'avancement :
    etape ∈ {"plan", "redaction", "assemblage"} ; (faites, total) = sections."""
    profil, id_user = _resoudre_profil(id_user, profil)

    if completer and not dry_run:
        maj = reviser_memoire(id_marche, numero_lot, id_user=id_user, profil=profil,
                              verbose=verbose, progress_callback=progress_callback)
        if maj is not None:
            return maj
        # sinon (pas de mémoire existante) → génération complète normale

    if not force and not dry_run:
        existante = cle_memoire_existante(id_marche, numero_lot, id_user)
        if existante:
            if verbose:
                print(f"  ↩ Mémoire déjà en base ({existante}) — force pour régénérer.")
            return stockage.lire(commun.COLLECTION_MEMOIRES, existante)

    # Entrées
    brief, lot = commun.charger_brief_et_lot(id_marche, numero_lot)
    digest = commun.charger_digest(id_marche, numero_lot)
    cctp, infos_cctp = commun.charger_dce_lot(id_marche, lot, verbose=verbose)
    grille = commun.grille_redaction_lot(brief, lot)
    if verbose:
        print(f"  CCTP : {len(infos_cctp['fichiers_utilises'])} pièce(s) "
              f"[{infos_cctp['mode_filtre']}], {infos_cctp['chars']} chars"
              + (" (TRONQUÉ)" if infos_cctp["tronque"] else ""))
        nb_sc = len((brief.get("bareme_notation") or {}).get("sous_criteres_techniques") or [])
        print(f"  Grille d'actions : {nb_sc} sous-critère(s) filtré(s) pour domaine '{lot.get('domaine')}'")

    # --- DRY-RUN : estimation des deux appels, pas d'appel LLM ---
    if dry_run:
        est1 = appel1.extraire_contexte_memoire(
            id_marche, numero_lot, id_user, profil, brief, lot, digest, cctp,
            grille_actions=grille, dry_run=True, verbose=verbose)
        est2 = appel2.rediger_memoire(
            id_marche, numero_lot, profil, lot, digest, {}, cctp,
            grille_actions=grille, dry_run=True, verbose=verbose)
        total = (est1.get("_dry_estim") or 0) + (est2.get("_dry_estim") or 0)
        if verbose:
            print(f"  [DRY-RUN] Coût TOTAL estimé ≈ {total:.3f} € "
                  f"(appel 1 ≈ {est1.get('_dry_estim'):.3f} € + appel 2 ≈ {est2.get('_dry_estim'):.3f} €).")
        return None

    # --- Garde-fou budget AVANT tout appel (estimation peu coûteuse) ---
    if max_cout_eur is not None:
        est1 = appel1.extraire_contexte_memoire(
            id_marche, numero_lot, id_user, profil, brief, lot, digest, cctp,
            grille_actions=grille, dry_run=True, verbose=False)
        est2 = appel2.rediger_memoire(
            id_marche, numero_lot, profil, lot, digest, {}, cctp,
            grille_actions=grille, dry_run=True, verbose=False)
        total_est = (est1.get("_dry_estim") or 0) + (est2.get("_dry_estim") or 0)
        if total_est > max_cout_eur:
            raise RuntimeError(
                f"⛔ ABORT : coût total estimé {total_est:.3f} € > plafond "
                f"{max_cout_eur:.3f} € ({id_marche} lot {numero_lot}).")

    t0 = time.time()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    genere_le = datetime.now(timezone.utc).isoformat()

    # --- Appel 1 : plan de rédaction ---
    if progress_callback:
        progress_callback("plan", 0, 0)
    if verbose:
        print("\n  ── APPEL 1 — extraction du contexte mémoire ──")
    r1 = appel1.extraire_contexte_memoire(
        id_marche, numero_lot, id_user, profil, brief, lot, digest, cctp,
        grille_actions=grille, dry_run=False, max_cout_eur=None, verbose=verbose)
    plan_redaction = r1["plan_redaction"]
    template_acheteur = r1.get("template_acheteur_chemin")

    # --- Appel 2 : rédaction PARALLÈLE (une section par appel) ---
    if verbose:
        print("\n  ── APPEL 2 — rédaction de la mémoire (parallèle) ──")
    sous_cb = (lambda f, t: progress_callback("redaction", f, t)) if progress_callback else None
    r2 = appel2.rediger_memoire_parallele(
        id_marche, numero_lot, profil, lot, digest, plan_redaction,
        grille_actions=grille, progress_callback=sous_cb, verbose=verbose)
    sections = r2["sections_redigees"]

    duree_totale = round(time.time() - t0, 1)

    # --- Objet mémoire (schéma de stockage) ---
    memoire = {
        "id_marche": id_marche,
        "numero_lot": lot.get("numero"),
        "id_user": id_user,
        "intitule_lot": lot.get("intitule"),
        "timestamp": timestamp,
        "template_acheteur": template_acheteur,
        "version_prompt_extraction": r1["version_prompt"],
        "version_prompt_redaction": r2["version_prompt"],
        "genere_le": genere_le,
        "plan_redaction": plan_redaction,
        "sections_redigees": sections,
        "chemin_docx": None,
        "regenerations": [],
        "_meta": {
            "cout_total_eur": round(r1["cout_eur"] + r2["cout_eur"], 4),
            "cout_appel_1_eur": r1["cout_eur"],
            "cout_appel_2_eur": r2["cout_eur"],
            "tokens_entree_appel_1": r1["usage"]["tokens_entree"],
            "tokens_sortie_appel_1": r1["usage"]["tokens_sortie"],
            "tokens_entree_appel_2": r2["usage"]["tokens_entree"],
            "tokens_sortie_appel_2": r2["usage"]["tokens_sortie"],
            "modele": commun.MODELE,
            "duree_totale_s": duree_totale,
            "cctp_fichiers": infos_cctp["fichiers_utilises"],
            "cctp_mode_filtre": infos_cctp["mode_filtre"],
            "cctp_tronque": infos_cctp["tronque"],
            "sections_manquantes": r2.get("sections_manquantes") or [],
            "sections_hors_plan": r2.get("sections_hors_plan") or [],
        },
    }

    # --- Assemblage .docx ---
    if progress_callback:
        progress_callback("assemblage", 0, 0)
    if verbose:
        print("\n  ── ASSEMBLAGE .docx ──")
    contexte = commun.construire_contexte(memoire, brief, profil)
    chemin_docx = assemblage_docx.assembler(
        memoire, profil, contexte, template_acheteur=template_acheteur, verbose=verbose)
    memoire["chemin_docx"] = chemin_docx

    # --- Stockage ---
    cle = commun.cle_memoire(id_marche, numero_lot, id_user, timestamp)
    stockage.ecrire(commun.COLLECTION_MEMOIRES, cle, memoire)

    if verbose:
        print("\n  " + "─" * 70)
        print(f"  ✓ MÉMOIRE générée & stockée ({cle})")
        print(f"    Coût total : {memoire['_meta']['cout_total_eur']:.3f} € "
              f"(appel 1 : {r1['cout_eur']:.3f} € · appel 2 : {r2['cout_eur']:.3f} €)")
        print(f"    Durée : {duree_totale}s · Sections : {len(sections)}")
        print(f"    .docx : {chemin_docx}")
    return memoire
