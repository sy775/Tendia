"""
bilan_briefs.py
---------------
État des lieux avant lancement (ou suite) du pipeline LLM bout-à-bout.

Croise quatre dimensions pour identifier précisément ce qu'il reste à
enrichir :
  1. Marchés pertinents (matchent au moins un preset, via scores_matching)
  2. Statut du téléchargement DCE (ok / faux_succes / login / etc.)
  3. Présence d'un brief COMPLET en cache (collection 'briefs_extraits')
  4. Présence d'un brief LIGHT en cache

Sortie : tableau croisé + liste des marchés à enrichir + coût estimé.

Usage :
    python bilan_briefs.py
    python bilan_briefs.py --liste-a-enrichir   # affiche les IDs concernés
"""

import argparse
import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import stockage


REPERTOIRE_BASE = Path(__file__).parent
REPERTOIRE_DCE = REPERTOIRE_BASE / "data" / "dce"
REPERTOIRE_EXTRACTIONS = REPERTOIRE_BASE / "data" / "extractions"

# Coût indicatif (selon doc : 0.15-0.30€/marché COMPLET, 0.025€/marché LIGHT)
COUT_MOYEN_COMPLET_EUR = 0.20
COUT_MOYEN_LIGHT_EUR = 0.025


def _charger_briefs() -> dict:
    """Briefs en base SQLite + fallback fichiers disque."""
    briefs = {}
    try:
        briefs = stockage.charger("briefs_extraits") or {}
    except Exception as e:
        print(f"  ⚠ Erreur chargement SQLite briefs_extraits : {e}")
    # Fallback : compléter avec ce qui est sur disque mais pas en SQLite
    if REPERTOIRE_EXTRACTIONS.exists():
        for fichier in REPERTOIRE_EXTRACTIONS.glob("*.json"):
            id_m = fichier.stem
            if id_m in briefs:
                continue
            try:
                briefs[id_m] = json.loads(fichier.read_text(encoding="utf-8"))
            except Exception:
                pass
    return briefs


def _type_brief(brief: dict) -> str:
    """Retourne 'COMPLET', 'LIGHT', ou 'INCONNU' selon le champ _meta."""
    meta = brief.get("_meta") or {}
    type_brief = (meta.get("type") or "").upper()
    if type_brief in ("COMPLET", "LIGHT"):
        return type_brief
    # Fallback : si on a des champs riches (criteres_attribution, etc.) → COMPLET
    if any(k in brief for k in ("criteres_attribution", "modalites_consultation",
                                  "duree_estimee", "volume_estime")):
        return "COMPLET"
    return "INCONNU"


def _statut_dce(marche: dict) -> str:
    """Renvoie une catégorie agrégée du statut DCE."""
    statut = marche.get("dce_telechargement_statut") or "jamais_tente"
    if statut == "ok":
        return "ok"
    if statut == "manuel_requis":
        return "manuel_requis"
    if statut == "echec":
        raison = (marche.get("dce_telechargement_raison") or "").lower()
        if "faux_succes" in raison:
            return "faux_succes"
        if "login" in raison:
            return "login_requis"
        if "captcha" in raison:
            return "captcha"
        if "espace acheteur" in raison:
            return "espace_acheteur"
        return "echec_autre"
    return statut


def _dossier_dce_non_vide(id_marche: str) -> bool:
    """True si le dossier data/dce/<id>/ contient au moins un fichier utile."""
    dossier = REPERTOIRE_DCE / id_marche
    if not dossier.is_dir():
        return False
    fichiers = [f for f in dossier.iterdir() if f.is_file()]
    if not fichiers:
        return False
    # Filtre les fichiers bruit connus
    bruits = {"depot-pli.pdf", "DUME Acheteur.zip"}
    utiles = [f for f in fichiers if f.name not in bruits
              and not f.name.lower().startswith("cgu")]
    return len(utiles) > 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--liste-a-enrichir", action="store_true",
                    help="Affiche les IDs des marchés à enrichir.")
    ap.add_argument("--liste-anomalies", action="store_true",
                    help="Affiche les marchés pertinents avec brief mais "
                         "sans DCE (pour audit).")
    args = ap.parse_args()

    print("=" * 78)
    print("  Bilan briefs LLM avant pipeline bout-à-bout")
    print("=" * 78)

    marches = stockage.charger("marches") or {}
    scores = stockage.charger("scores_matching") or {}
    briefs = _charger_briefs()

    print(f"\n  Marchés en base      : {len(marches)}")
    print(f"  Scores matching      : {len(scores)}")
    print(f"  Briefs en cache      : {len(briefs)}")

    # Identifier les marchés pertinents (ceux qui matchent ≥1 preset)
    # Le schéma scores_matching peut être soit {id: {...}} soit {id: {preset: {...}}}
    # selon l'historique. On gère les deux.
    pertinents_par_preset = defaultdict(set)
    pertinents_tous = set()

    for cle, score in scores.items():
        if not isinstance(score, dict):
            continue
        # Cas 1 : clé composite "id_preset" ou similaire
        if "preset_code" in score and "matche" in score:
            if score.get("matche"):
                # Cherche l'id du marché : soit dans score, soit dans la clé
                id_m = score.get("marche_id") or score.get("id") or cle.rsplit("_", 1)[0]
                preset_c = score["preset_code"]
                pertinents_par_preset[preset_c].add(id_m)
                pertinents_tous.add(id_m)
        # Cas 2 : id direct, dict imbriqué {preset: {matche, ...}}
        else:
            for preset_c, sub in score.items():
                if isinstance(sub, dict) and sub.get("matche"):
                    pertinents_par_preset[preset_c].add(cle)
                    pertinents_tous.add(cle)

    print(f"\n  ── Pertinence (matching multi-preset) ──")
    print(f"  Pertinents au total  : {len(pertinents_tous)}")
    for p, ids in sorted(pertinents_par_preset.items()):
        print(f"    · {p:<28} : {len(ids)}")

    if not pertinents_tous:
        print("\n  ⚠ Aucun marché pertinent. Lance d'abord :")
        print("      python analyse.py")
        return

    # === Croisement DCE × Brief sur les marchés pertinents ===
    matrice = defaultdict(lambda: Counter())
    anomalies = []  # pertinents avec brief mais sans DCE valide
    a_enrichir = []  # pertinents avec DCE valide mais sans brief COMPLET

    for id_m in sorted(pertinents_tous):
        marche = marches.get(id_m)
        if not marche:
            matrice["pertinent_sans_marche"]["?"] += 1
            continue
        dce_cat = _statut_dce(marche)
        dossier_ok = _dossier_dce_non_vide(id_m)

        brief = briefs.get(id_m)
        if brief:
            type_b = _type_brief(brief)
        else:
            type_b = "AUCUN"

        # Clé matrice : (statut DCE, type brief)
        matrice[dce_cat][type_b] += 1

        # Anomalies
        if type_b == "COMPLET" and not dossier_ok:
            anomalies.append((id_m, dce_cat, "brief COMPLET sans DCE sur disque"))

        # À enrichir : pertinent, DCE OK, pas encore COMPLET
        if dossier_ok and type_b != "COMPLET":
            a_enrichir.append((id_m, dce_cat, type_b))

    # Affichage matrice
    print(f"\n  ── Croisement DCE × Brief (sur {len(pertinents_tous)} pertinents) ──")
    print(f"  {'DCE statut':<22} {'AUCUN':>6} {'LIGHT':>6} {'COMPLET':>8} "
          f"{'INCONNU':>8}  {'total':>6}")
    print(f"  {'-'*22} {'-'*6} {'-'*6} {'-'*8} {'-'*8}  {'-'*6}")
    ordre = ["ok", "manuel_requis", "faux_succes", "login_requis", "captcha",
             "espace_acheteur", "echec_autre", "jamais_tente",
             "pertinent_sans_marche"]
    totaux = Counter()
    for dce_cat in ordre + [k for k in matrice if k not in ordre]:
        if dce_cat not in matrice:
            continue
        row = matrice[dce_cat]
        tot = sum(row.values())
        totaux["AUCUN"] += row["AUCUN"]
        totaux["LIGHT"] += row["LIGHT"]
        totaux["COMPLET"] += row["COMPLET"]
        totaux["INCONNU"] += row["INCONNU"]
        totaux["total"] += tot
        print(f"  {dce_cat:<22} {row['AUCUN']:>6} {row['LIGHT']:>6} "
              f"{row['COMPLET']:>8} {row['INCONNU']:>8}  {tot:>6}")
    print(f"  {'-'*22} {'-'*6} {'-'*6} {'-'*8} {'-'*8}  {'-'*6}")
    print(f"  {'TOTAL':<22} {totaux['AUCUN']:>6} {totaux['LIGHT']:>6} "
          f"{totaux['COMPLET']:>8} {totaux['INCONNU']:>8}  {totaux['total']:>6}")

    # === Verdict ===
    print(f"\n  ── Verdict ──")
    print(f"  À enrichir ce run (pertinent + DCE ok + brief absent ou LIGHT) : "
          f"{len(a_enrichir)}")
    cout_estime = len(a_enrichir) * COUT_MOYEN_COMPLET_EUR
    print(f"  Coût estimé : ~{cout_estime:.2f} € "
          f"(à {COUT_MOYEN_COMPLET_EUR:.2f}€/marché en moyenne)")

    if anomalies:
        print(f"\n  ⚠ {len(anomalies)} anomalies (briefs sans DCE disque)")

    # === Listes optionnelles ===
    if args.liste_a_enrichir and a_enrichir:
        print(f"\n  IDs à enrichir :")
        for id_m, dce_cat, brief_cat in a_enrichir:
            print(f"    {id_m}  DCE={dce_cat:<14}  brief actuel={brief_cat}")

    if args.liste_anomalies and anomalies:
        print(f"\n  Anomalies :")
        for id_m, dce_cat, raison in anomalies:
            print(f"    {id_m}  ({dce_cat}) — {raison}")

    # === Prochaine étape suggérée ===
    print(f"\n  ── Prochaine étape suggérée ──")
    if len(a_enrichir) == 0:
        print(f"  ✓ Tous les marchés pertinents avec DCE ont déjà un brief COMPLET.")
        print(f"  → Passer à l'inspection des briefs (qualité, complétude).")
    elif cout_estime < 1.0:
        print(f"  → Petit volume, lance sans garde-fou strict :")
        print(f"      python enrichir_complet.py")
    else:
        print(f"  → Lance par tranches pour contrôler le coût :")
        print(f"      python enrichir_complet.py --limite 5 --max-cout 2.0")
        print(f"      # Si OK, enchaîne par tranches de 10")


if __name__ == "__main__":
    main()
