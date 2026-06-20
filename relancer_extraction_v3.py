"""Ré-extraction v3 de TOUS les briefs (prompt enrichi : dossier_candidature,
tranches, lots[].domaine, certifs codes/bloquante, routage multi-preset).

- Cible : marchés `dce_contenu == complet` avec DCE sur disque, dont le brief
  n'est PAS déjà au SHA courant (resumable, pas de double paiement).
- LLM seul sur le DCE déjà téléchargé (pas de re-download).
- Backup de chaque brief en `<id>.bak_avant_v3` avant écrasement.
- Progression : data/reextraction_v3.log (append) + console.
- Rapport final : RAPPORT_REEXTRACTION_V3.md.
- Safety : continue sur erreur ; stop net si coût cumulé dépasse PLAFOND_EUR.

Usage : python relancer_extraction_v3.py
"""
import io
import os
import sys
import json
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import stockage
import pdf_extract
import tendia_extraire
import llm_extract

SHA = llm_extract.PROMPT_V2_SHA
PLAFOND_EUR = 160.0  # garde-fou anti-emballement
LOG = os.path.join("data", "reextraction_v3.log")
RAPPORT = "RAPPORT_REEXTRACTION_V3.md"


def log(msg):
    ligne = f"{time.strftime('%H:%M:%S')} {msg}"
    print(ligne, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(ligne + "\n")
    except Exception:
        pass


def _sha_brief(b):
    if not isinstance(b, dict):
        return None
    return b.get("prompt_version_sha") or (b.get("_meta") or {}).get("prompt_version_sha")


def main():
    marches = stockage.charger("marches") or {}
    briefs = stockage.charger("briefs_extraits") or {}

    # Sélection : complet + dossier disque non vide + PAS déjà ré-extrait en v3
    # (marqueur `_reextrait_v3` posé par ce script → resumable après crash).
    cibles = []
    deja_a_jour = 0
    for mid, m in sorted(marches.items()):
        if m.get("dce_contenu") != "complet":
            continue
        dossier = os.path.join("data", "dce", mid)
        if not (os.path.isdir(dossier) and any(os.scandir(dossier))):
            continue
        # Skip uniquement si le brief est DÉJÀ au SHA de prompt COURANT.
        # (Avant : on skippait sur le marqueur booléen `_reextrait_v3`, ce qui
        #  ignorait tout changement de prompt ultérieur → des briefs restaient
        #  sur un prompt intermédiaire. On compare désormais le SHA.)
        if _sha_brief(briefs.get(mid)) == SHA:
            deja_a_jour += 1
            continue
        cibles.append(mid)

    log(f"=== RE-EXTRACTION v3 (SHA {SHA}) ===")
    log(f"Cibles : {len(cibles)} | déjà à jour : {deja_a_jour} | plafond {PLAFOND_EUR} €")

    refait, erreurs = [], []
    stats = {"tranches": 0, "dossier_pieces": 0, "lots_domaine": 0,
             "certs_bloquantes": 0, "certs_codes": 0, "multi_preset": 0}
    cout_total = 0.0
    t0 = time.time()

    for i, mid in enumerate(cibles, 1):
        dossier = os.path.join("data", "dce", mid)
        try:
            tendia_extraire._dezipper_dossier(dossier, verbose=False)
            pdfs = pdf_extract.extraire_dossier(dossier, verbose=False)
            if not pdfs:
                erreurs.append((mid, "aucun PDF exploitable"))
                log(f"[{i}/{len(cibles)}] {mid} : skip (aucun PDF)")
                continue
            # Backup avant écrasement
            if mid in briefs:
                stockage.ecrire("briefs_extraits", f"{mid}.bak_avant_v3", briefs[mid])
            res = tendia_extraire.traiter_marche(mid, dossier, pdfs,
                                                 dry_run=False, verbose=False)
            if not res.get("ok"):
                erreurs.append((mid, res.get("erreur") or res.get("raison") or "?"))
                log(f"[{i}/{len(cibles)}] {mid} : ECHEC {res.get('erreur') or res.get('raison')}")
                continue
            b = stockage.lire("briefs_extraits", mid) or {}
            b["genere_avec_dce_complet"] = True
            b["_reextrait_v3"] = True
            b["prompt_version_sha"] = SHA  # stampe le SHA (non persisté nativement)
            stockage.ecrire("briefs_extraits", mid, b)

            # Stats des nouveaux champs
            if b.get("tranches"):
                stats["tranches"] += 1
            dc = b.get("dossier_candidature") or {}
            if dc.get("pieces_a_fournir"):
                stats["dossier_pieces"] += 1
            lots = b.get("lots") or []
            if any(isinstance(l, dict) and l.get("domaine") for l in lots):
                stats["lots_domaine"] += 1
            certs = (b.get("references_exigees") or {}).get("certifications_obligatoires") or []
            if any(isinstance(c, dict) and c.get("bloquante") for c in certs):
                stats["certs_bloquantes"] += 1
            if any(isinstance(c, dict) and c.get("codes") for c in certs):
                stats["certs_codes"] += 1
            if len((b.get("domaines_metier") or [])) > 1:
                stats["multi_preset"] += 1

            cout = float((b.get("_meta") or {}).get("cout_eur") or 0)
            cout_total += cout
            refait.append(mid)
            log(f"[{i}/{len(cibles)}] {mid} : OK ({cout:.3f} € | cumul {cout_total:.2f} €)")

            if cout_total > PLAFOND_EUR:
                log(f"⛔ PLAFOND {PLAFOND_EUR} € atteint — arrêt. {len(refait)} faits, {len(cibles)-i} restants.")
                break
        except Exception as e:
            erreurs.append((mid, f"{type(e).__name__}: {e}"))
            log(f"[{i}/{len(cibles)}] {mid} : EXCEPTION {type(e).__name__}: {e}")

    duree_min = (time.time() - t0) / 60
    _ecrire_rapport(cibles, refait, erreurs, stats, cout_total, duree_min, deja_a_jour)
    log(f"=== TERMINÉ : {len(refait)} OK / {len(erreurs)} échecs / {cout_total:.2f} € / {duree_min:.0f} min ===")
    log(f"Rapport : {RAPPORT}")


def _ecrire_rapport(cibles, refait, erreurs, stats, cout, duree, deja):
    n = len(refait)
    lignes = [
        "# Rapport — Ré-extraction v3",
        "",
        f"Prompt SHA : `{llm_extract.PROMPT_V2_SHA}` · durée {duree:.0f} min · coût **{cout:.2f} €**",
        "",
        "## Bilan",
        f"- Cibles : {len(cibles)} (déjà à jour avant run : {deja})",
        f"- ✅ Ré-extraits : **{n}**",
        f"- ❌ Échecs : {len(erreurs)}",
        f"- Coût moyen / brief : {cout/n:.3f} €" if n else "- Coût moyen : n/a",
        "",
        "## Peuplement des nouveaux champs (sur les briefs ré-extraits)",
        f"- `tranches` non vide : {stats['tranches']} / {n}",
        f"- `dossier_candidature.pieces_a_fournir` : {stats['dossier_pieces']} / {n}",
        f"- `lots[].domaine` peuplé : {stats['lots_domaine']} / {n}",
        f"- certifs `bloquante=true` : {stats['certs_bloquantes']} / {n}",
        f"- certifs avec `codes` (4 chiffres) : {stats['certs_codes']} / {n}",
        f"- multi-domaines (routage Axe 3) : {stats['multi_preset']} / {n}",
        "",
    ]
    if erreurs:
        lignes.append("## Échecs (à reprendre)")
        for mid, raison in erreurs:
            lignes.append(f"- `{mid}` : {raison}")
        lignes.append("")
    lignes.append("_Backups par brief : `<id>.bak_avant_v3` dans la collection briefs_extraits._")
    with open(RAPPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lignes))


if __name__ == "__main__":
    main()
