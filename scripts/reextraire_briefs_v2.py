"""
scripts/reextraire_briefs_v2.py — Refonte pipeline v2, Étape 5 (re-extraction LLM v2).

Re-extrait les briefs dce_contenu='complet' (& version != 2) avec le prompt v2 (3 voies
de montant + critères stricts + contexte BOAMP). Parallélisé (workers produisent l'appel
LLM, UN thread écrit en base → pas de 'database is locked'). BudgetTracker thread-safe,
cap dur (€). Backup du brief v1 dans `brief_v1_backup`. Sonnet 4.6.

Pattern progressif : --dry-run → --limite 5 --workers 1 → --limite 50 --workers 8 → complet.

Usage : python scripts/reextraire_briefs_v2.py [--limite N] [--dry-run] [--plafond 100.0]
        [--workers 8] [--marche-id ID]
"""
import argparse
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stockage
import pdf_extract
import preset
import llm_extract
import tendia_extraire as TE

COUT_ESTIME = 0.40   # € par brief (prompt v2, majoré)


class BudgetTracker:
    """Cap budgétaire thread-safe (réservation atomique + ajustement coût réel)."""
    def __init__(self, plafond_eur):
        self.plafond_eur = plafond_eur
        self.consomme_eur = 0.0
        self.nb = 0
        self._lock = threading.Lock()

    def try_reserve(self, cout_estime):
        with self._lock:
            if self.consomme_eur + cout_estime > self.plafond_eur:
                return False
            self.consomme_eur += cout_estime
            self.nb += 1
            return True

    def ajuster_cout_reel(self, cout_estime, cout_reel):
        with self._lock:
            self.consomme_eur += (cout_reel - cout_estime)


def _relever_cap_appels(n):
    """Relève extraction_max_par_jour dans data/budget.json AU-DESSUS du cumul d'appels
    DÉJÀ faits aujourd'hui (le quota est journalier et cumulatif sur tous les runs ; le
    vrai garde-fou est le cap € du tracker). Sinon un 2ᵉ/3ᵉ run du jour se fait bloquer."""
    try:
        import json
        import budget as B
        cfg = B.lire_config()
        deja = 0
        try:
            deja = B._compter_appels_jour("extraction")  # appels extraction déjà faits ce jour
        except Exception:
            pass
        cible = deja + n + 50  # marge
        if cfg.get("extraction_max_par_jour", 0) < cible:
            cfg["extraction_max_par_jour"] = cible
            with open(B.FICHIER_BUDGET, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            print(f"  ⓘ cap appels/jour relevé à {cible} (déjà {deja} aujourd'hui + {n} + marge ; "
                  f"vrai garde-fou = cap € du tracker).")
    except Exception as e:
        print(f"  ⚠ cap appels non relevé ({e}) — risque de blocage par le quota journalier.")


def _cibles(limite=None, marche_id=None, reextract_voie2=False, reextract_sha=False,
            multi_lots=False):
    m = stockage.charger("marches") or {}
    be = stockage.charger("briefs_extraits") or {}
    out = []
    for mid, mk in sorted(m.items()):
        if marche_id and mid != marche_id:
            continue
        if mk.get("dce_contenu") != "complet":
            continue
        b = be.get(mid) or {}
        if multi_lots and len(b.get("lots") or []) <= 1:
            continue
        est_v2 = str(b.get("version_extraction_llm")) == "2"
        deja_au_sha = b.get("prompt_version_sha") == llm_extract.PROMPT_V2_SHA
        if reextract_voie2:
            # Mode resserrage fourchettes : on re-extrait UNIQUEMENT les v2 ayant une Voie 2,
            # et PAS ceux déjà ré-extraits avec le prompt courant (idempotence anti-double-spend).
            if not (est_v2 and b.get("montant_voie_2_disponible")):
                continue
            if deja_au_sha:
                continue
        elif reextract_sha:
            # Mode refonte prompt (L1/L2…) : re-extrait tout brief PAS au SHA courant
            # (v2 obsolète OU v1 OU jamais extrait). Idempotent : un v2 déjà au SHA est sauté.
            if est_v2 and deja_au_sha:
                continue
        elif est_v2:
            continue
        dossier = os.path.join(TE.REPERTOIRE_DCE, mid)
        if not os.path.isdir(dossier):
            continue
        out.append((mid, mk, dossier))
        if limite and len(out) >= limite:
            break
    return out, be


def _extraire_un(mid, mk, dossier, tracker):
    """Worker : charge PDFs, appelle le LLM v2, post-traite. Ne touche PAS la base."""
    pdfs = pdf_extract.extraire_dossier(dossier, verbose=False)
    pdfs_valides = {n: p for n, p in (pdfs or {}).items()
                    if not TE._est_pdf_non_dce(n, p.get("taille_chars", 0))[0]}
    if not pdfs_valides:
        return {"mid": mid, "statut": "pas_de_pdf"}
    if not tracker.try_reserve(COUT_ESTIME):
        return {"mid": mid, "statut": "budget"}
    contexte = TE._construire_contexte(mk)
    texte = TE._combiner_textes(pdfs_valides)
    try:
        extraction = llm_extract.extraire_via_llm(texte, contexte, verbose=False)
    except Exception as e:
        return {"mid": mid, "statut": "erreur", "erreur": str(e)[:120]}
    if not extraction:
        return {"mid": mid, "statut": "echec_llm"}
    extraction = llm_extract.post_traiter_extraction_v2(extraction)
    appel = extraction.pop("_appel_llm", None) or {}
    return {"mid": mid, "statut": "ok", "extraction": extraction, "appel": appel,
            "pdfs": pdfs, "cout_reel": appel.get("cout_eur") or COUT_ESTIME}


def _ecrire(mid, mk, r, be):
    """Thread principal UNIQUEMENT : backup v1 + _meta + écriture base."""
    extraction = r["extraction"]
    appel = r["appel"]
    codes = appel.get("codes_presets") or []
    horo = datetime.now(timezone.utc).isoformat()
    extraction["_meta"] = {
        "id_marche": mid, "type": "complet",
        "date_generation": horo, "extraction_le": horo,
        "modele": appel.get("modele") or llm_extract.MODELE,
        "preset_utilise": codes[0] if codes else None,
        "presets_matches": codes,
        "prompts_versions": preset.prompts_versions_pour_presets(codes),
        "prompt_version_sha_v2": llm_extract.PROMPT_V2_SHA,
        "tokens_input": appel.get("tokens_input"), "tokens_output": appel.get("tokens_output"),
        "cout_eur": appel.get("cout_eur"), "duree_sec": appel.get("duree_sec"),
        "pdfs_traites": [{"nom": n, "hash": p.get("hash"), "taille_chars": p.get("taille_chars")}
                         for n, p in (r["pdfs"] or {}).items()],
    }
    ancien = be.get(mid)
    if ancien is not None:
        if "brief_v1_backup" in ancien:
            # Re-run d'un brief DÉJÀ v2 (ex. resserrage fourchettes) : on PRÉSERVE le
            # backup v1 original au lieu de l'écraser par l'ancien v2.
            extraction["brief_v1_backup"] = ancien["brief_v1_backup"]
            extraction["brief_v1_backup_expire_le"] = ancien.get("brief_v1_backup_expire_le", horo)
        else:
            # Première conversion v1 → v2 : on sauvegarde le v1.
            extraction["brief_v1_backup"] = {k: v for k, v in ancien.items() if k != "brief_v1_backup"}
            extraction["brief_v1_backup_expire_le"] = horo
    extraction["extraction_v2_le"] = horo
    stockage.ecrire("briefs_extraits", mid, extraction)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--plafond", type=float, default=100.0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--marche-id", default=None)
    ap.add_argument("--reextract-voie2", action="store_true",
                    help="re-extrait les briefs DÉJÀ v2 ayant une Voie 2 (resserrage fourchettes)")
    ap.add_argument("--reextract-sha", action="store_true",
                    help="re-extrait tout brief pas au SHA prompt courant (refonte prompt L1/L2)")
    ap.add_argument("--multi-lots", action="store_true",
                    help="ne cible que les briefs multi-lots (>1 lot) — coût par lot")
    args = ap.parse_args()

    cibles, be = _cibles(args.limite, args.marche_id,
                         reextract_voie2=args.reextract_voie2,
                         reextract_sha=args.reextract_sha,
                         multi_lots=args.multi_lots)
    n = len(cibles)
    mode = ("v2 avec Voie 2 (resserrage)" if args.reextract_voie2
            else "v2 obsolète (SHA≠courant) + v1/jamais" if args.reextract_sha
            else "dce_contenu=complet, !=v2")
    print(f"=== Re-extraction LLM v2 — {n} briefs cibles ({mode})"
          f"{' [DRY-RUN]' if args.dry_run else ''} ===")
    if args.dry_run:
        print(f"  Coût estimé si tous traités : ~{n*COUT_ESTIME:.1f} € / {args.plafond:.0f} €")
        print(f"  Workers : {args.workers} | prompt v2 SHA {llm_extract.PROMPT_V2_SHA}")
        print("  [DRY-RUN] aucun appel LLM, aucune écriture.")
        return
    if not n:
        print("  Rien à re-extraire.")
        return

    _relever_cap_appels(n + 50)
    tracker = BudgetTracker(args.plafond)
    t0 = time.time()
    stats = Counter()
    couv = Counter()
    cibles_idx = {mid: mk for mid, mk, _ in cibles}

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(_extraire_un, mid, mk, dossier, tracker)
                for mid, mk, dossier in cibles]
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            stats[r["statut"]] += 1
            if r["statut"] == "ok":
                tracker.ajuster_cout_reel(COUT_ESTIME, r["cout_reel"])
                _ecrire(r["mid"], cibles_idx[r["mid"]], r, be)
                e = r["extraction"]
                if e.get("montant_voie_1_eur"):
                    couv["voie_1"] += 1
                if e.get("montant_voie_2_disponible"):
                    couv["voie_2"] += 1
                if e.get("montant_au_moins_une_voie"):
                    couv["au_moins_une"] += 1
                if e.get("criteres_attribution_plat"):
                    couv["criteres"] += 1
                for f in ("criteres_alerte_pas_de_prix", "criteres_alerte_somme_incorrecte",
                          "criteres_alerte_non_classes", "extraction_v2_a_verifier"):
                    if e.get(f):
                        couv[f] += 1
            if i % 10 == 0 or i == n:
                print(f"  …{i}/{n} | ok={stats['ok']} budget={stats['budget']} "
                      f"| {tracker.consomme_eur:.1f} €")

    dt = (time.time() - t0) / 60
    ok = stats["ok"]
    print(f"\n=== Re-extraction v2 terminée ({dt:.1f} min, {args.workers} workers) ===")
    print(f"Cibles {n} | re-extraits {ok} | budget {stats['budget']} | "
          f"échecs LLM {stats['echec_llm']+stats['erreur']} | sans PDF {stats['pas_de_pdf']}")
    print(f"Budget consommé : {tracker.consomme_eur:.2f} € / {args.plafond:.0f} €")
    print(f"Coût moyen : {tracker.consomme_eur/ok if ok else 0:.3f} €/brief")
    if ok:
        print(f"\nCouverture (sur {ok} briefs v2) :")
        print(f"  Voie 1 (publié)        : {couv['voie_1']} ({100*couv['voie_1']/ok:.0f} %)")
        print(f"  Voie 2 (estimation)    : {couv['voie_2']} ({100*couv['voie_2']/ok:.0f} %)")
        print(f"  Au moins une voie      : {couv['au_moins_une']} ({100*couv['au_moins_une']/ok:.0f} %)")
        print(f"  Critères extraits      : {couv['criteres']} ({100*couv['criteres']/ok:.0f} %)")
        print(f"  Alerte pas_de_prix     : {couv['criteres_alerte_pas_de_prix']}")
        print(f"  Alerte somme           : {couv['criteres_alerte_somme_incorrecte']}")
        print(f"  Alerte non_classe      : {couv['criteres_alerte_non_classes']}")
        print(f"  À vérifier (≥2 alertes) : {couv['extraction_v2_a_verifier']}")


if __name__ == "__main__":
    main()
