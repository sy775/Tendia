"""
scripts/reclassifier_affine.py — re-classifie tous les marchés avec le prompt de
classification AFFINÉ (frontières « travaux vs études », « énergie projet vs fourniture »).

Met à jour la collection `classifications_ia` (force=True). Bénéficie au routage des
presets, aux marchés sans brief et au dashboard. Haiku (économe).

Usage : python scripts/reclassifier_affine.py [--limit N] [--only-ingenierie-energie]
"""
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stockage
import tendia_classification as tc

# Charge la clé API depuis .env.txt si présente (convention projet).
try:
    from pathlib import Path
    env = Path(__file__).resolve().parent.parent / ".env.txt"
    if env.exists():
        for ligne in env.read_text(encoding="utf-8").splitlines():
            if "=" in ligne and not ligne.strip().startswith("#"):
                k, v = ligne.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
except Exception:
    pass


def _codes_actuels(mid, marche, briefs, classifs):
    """Codes domaines actuels (brief prioritaire, sinon classif IA)."""
    b = briefs.get(mid)
    src = (b.get("domaines_metier") if (b and b.get("domaines_metier"))
           else (classifs.get(mid) or {}).get("domaines_metier")) or []
    return [d.get("code") if isinstance(d, dict) else d for d in src]


def main():
    limit = None
    only_ie = "--only-ingenierie-energie" in sys.argv
    # Cible les codes recentrés par l'enrichissement taxonomie v2 (fourre-tout à scinder).
    only_enrichi = "--cibles-enrichissement" in sys.argv
    CODES_ENRICHIS = ("moe_architecte_urbanisme", "ingenierie_environnementale",
                      "energie_amo_etudes", "btp_voirie_reseaux")
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    marches = stockage.charger("marches") or {}
    briefs = stockage.charger("briefs_extraits") or {}
    classifs = stockage.charger("classifications_ia") or {}

    items = list(marches.items())
    if only_ie:
        items = [(mid, m) for mid, m in items
                 if any(c and (c.startswith(("ingenierie", "moe", "energie")))
                        for c in _codes_actuels(mid, m, briefs, classifs))]
    if only_enrichi:
        items = [(mid, m) for mid, m in items
                 if any(c in CODES_ENRICHIS
                        for c in _codes_actuels(mid, m, briefs, classifs))]
    if limit:
        items = items[:limit]

    total = len(items)
    print(f"=== Re-classification affinée : {total} marchés (force=True) ===", flush=True)
    debut = time.time()
    cout = 0.0
    stats = {"classifié": 0, "rejeté": 0, "échec": 0}
    changes = 0
    for i, (mid, marche) in enumerate(items, 1):
        avant = set(_codes_actuels(mid, marche, briefs, classifs))
        try:
            res = tc.classifier_un_marche(mid, marche, modele="haiku", force=True)
        except Exception as e:
            print(f"  [{i}/{total}] {mid} ERREUR {e}", flush=True)
            stats["échec"] += 1
            continue
        st = res.get("statut")
        stats[st] = stats.get(st, 0) + 1
        if st == "classifié":
            cl = res["classification"]
            cout += ((cl.get("_meta") or {}).get("cout_eur") or 0)
            apres = {d.get("code") for d in (cl.get("domaines_metier") or []) if isinstance(d, dict)}
            if apres != avant:
                changes += 1
                print(f"  [{i}/{total}] {mid} CHANGÉ {sorted(avant)} -> {sorted(apres)}", flush=True)
        if i % 25 == 0:
            print(f"  … {i}/{total} · {cout:.3f} € · {time.time()-debut:.0f}s", flush=True)

    print(f"=== Terminé : {stats} · {changes} classifications changées · "
          f"{cout:.3f} € · {time.time()-debut:.0f}s ===", flush=True)


if __name__ == "__main__":
    main()
