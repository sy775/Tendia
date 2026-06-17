"""
scripts/retenter_download_dce.py — Refonte pipeline v2, Étape 3 (re-download DCE, B12).

Re-tente le téléchargement du DCE sur les candidats (url_consultation_dce_directe présent
ET dce_contenu != 'complet') via le downloader patché Étape 2 (priorité URL directe → repli
reconstruite). Parallélisé (workers téléchargent+qualifient, UN thread écrit en base).

Le gain attendu = la résolution pratique de B12 : l'URL directe de consultation (avec PCSLID)
permet de récupérer le dossier complet là où la reconstruction d'URL échouait.

Pattern progressif : --dry-run → --limite 5 --workers 1 → --limite 50 --workers 5 → complet.

Usage : python scripts/retenter_download_dce.py [--dry-run] [--limite N] [--workers 5]
"""
import argparse
import os
import shutil
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import truststore
truststore.inject_into_ssl()

import stockage
import tendia_dce
import tendia_telecharger_dce as T
import tendia_extraire as TE

STAGGER_SEC = 0.2        # anti-burst entre lancements de threads
RETRIES = 3
_submit_lock = threading.Lock()


def _candidats(limite=None):
    m = stockage.charger("marches") or {}
    out = []
    for mid, mk in sorted(m.items()):
        # Cible les DCE incomplets ayant une URL exploitable (le wrapper dispatch
        # Atexo/achatpublic via id+org/PCSLID sur l'une des 2 URLs).
        if mk.get("dce_contenu") == "incomplet" and (
                mk.get("url_consultation_dce_directe") or mk.get("url_dce")):
            out.append((mid, mk))
            if limite and len(out) >= limite:
                break
    return out


def _telecharger_un(mid, mk):
    """Worker : backup + download (patché) + dézip + qualif. Ne touche PAS la base."""
    with _submit_lock:
        time.sleep(STAGGER_SEC)  # stagger les démarrages
    dossier = os.path.join(str(T.REPERTOIRE_DCE), mid)
    avant = mk.get("dce_contenu")
    bak = os.path.join(str(T.REPERTOIRE_DCE), f"{mid}.bak_avant_b12")
    if os.path.isdir(dossier) and not os.path.isdir(bak):
        try:
            if os.listdir(dossier):
                shutil.copytree(dossier, bak)
        except Exception:
            pass
    os.makedirs(dossier, exist_ok=True)

    res, err = None, None
    for tentative in range(1, RETRIES + 1):
        try:
            res = T.telecharger_pieces_dce(mk, dossier)
            break
        except Exception as e:
            err = str(e)[:120]
            if tentative < RETRIES:
                time.sleep(min(2 ** tentative, 30))  # backoff exponentiel
    if res is None:
        res = {"pieces_recuperees": [], "pieces_manquantes": [], "raison": err or "?",
               "url_source": None}
    try:
        TE._dezipper_dossier(dossier, verbose=False)
    except Exception:
        pass
    qual = tendia_dce.qualifier_dce(dossier)
    return {
        "mid": mid, "avant": avant, "apres": qual["qualite"],
        "pieces_contractuelles": qual.get("pieces_contractuelles"),
        "raison": qual.get("raison"),
        "pieces_manquantes": res.get("pieces_manquantes", []),
        "url_source": res.get("url_source"),
        "n_pieces": len(res.get("pieces_recuperees", [])),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limite", type=int, default=None)
    ap.add_argument("--workers", type=int, default=5)
    args = ap.parse_args()

    cibles = _candidats(args.limite)
    n = len(cibles)
    print(f"=== Re-download DCE (B12) — {n} candidats"
          f"{' [DRY-RUN]' if args.dry_run else ''} ===")
    if args.dry_run:
        from urllib.parse import urlparse
        hosts = Counter(urlparse(mk["url_consultation_dce_directe"]).netloc for _, mk in cibles)
        print(f"  Plateformes : " + ", ".join(f"{h}={c}" for h, c in hosts.most_common(8)))
        print(f"  Avant : " + ", ".join(f"{k}={v}" for k, v in
              Counter(mk.get('dce_contenu') for _, mk in cibles).most_common()))
        print("  [DRY-RUN] aucun téléchargement.")
        return
    if not n:
        print("  Aucun candidat.")
        return

    t0 = time.time()
    transitions = Counter()
    url_src = Counter()
    gains = []
    cibles_idx = {mid: mk for mid, mk in cibles}

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(_telecharger_un, mid, mk) for mid, mk in cibles]
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            transitions[f"{r['avant']} → {r['apres']}"] += 1
            if r["url_source"]:
                url_src[r["url_source"]] += 1
            # Écriture base (thread principal uniquement)
            mk = cibles_idx[r["mid"]]
            if r["apres"] == "complet" and r["avant"] != "complet":
                gains.append(r["mid"])
            mk["dce_contenu"] = r["apres"]
            mk["dce_pieces_contractuelles"] = r["pieces_contractuelles"]
            mk["dce_pieces_manquantes"] = r["pieces_manquantes"]
            mk["dce_raison_contenu"] = r["raison"]
            mk["dce_telecharge_le"] = datetime.now().isoformat()
            stockage.ecrire("marches", r["mid"], mk)
            if i % 5 == 0 or i == n:
                print(f"  …{i}/{n} | complet gagnés : {len(gains)}")

    dt = (time.time() - t0) / 60
    echecs = sum(v for k, v in transitions.items() if not k.endswith("→ complet"))
    taux_echec = 100.0 * echecs / n if n else 0
    print(f"\n=== Re-download terminé ({dt:.1f} min, {args.workers} workers) ===")
    print(f"Candidats {n} | nouveaux complet : {len(gains)}")
    print("Transitions :")
    for k, v in transitions.most_common():
        print(f"  {k:28} : {v}")
    print(f"URL utilisée : " + ", ".join(f"{k}={v}" for k, v in url_src.most_common()))
    print(f"Taux non-complet : {taux_echec:.0f} %"
          + ("  ⚠ > 30 % — à signaler" if taux_echec > 30 else ""))
    print(f"\n⇒ {len(gains)} marchés passés à complet (à re-extraire en v2).")


if __name__ == "__main__":
    main()
