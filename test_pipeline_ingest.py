"""
test_pipeline_ingest.py
-----------------------
Test ponctuel de la pipeline complète sur de NOUVEAUX marchés, à coût borné.

Étapes :
  1. Laisse l'hôte BOAMP se calmer (le diagnostic a déclenché un throttling).
  2. Ingestion mode large CAPÉE (40 plus récents), avec plusieurs essais espacés
     — s'appuie sur le backoff durci de http_utils.
  3. Si (et seulement si) de vrais nouveaux marchés sont entrés : passe de veille
     `--une-passe --max-extractions 5 --seuil-complet pertinent`
     → match toute la base + extraction LLM des nouveaux pertinents (cap 5).

Coût : 0 € si aucun nouveau marché ; sinon ~2-5 € (≤ 5 extractions Sonnet +
proxy/2captcha sur les DCE des plateformes protégées).

Lancé en arrière-plan ; logue tout sur stdout.
"""
import subprocess
import sys
import time

import connecteurs
import stockage
import tendia_recup

CALME_INITIAL_SEC = 900      # 15 min sans trafic pour purger le throttle
NB_ESSAIS_INGEST = 4
DELAI_ENTRE_ESSAIS_SEC = 300  # 5 min
CAP_EXTRACTIONS = 5


def log(msg):
    print(msg, flush=True)


def main():
    log(f"[{time.strftime('%H:%M:%S')}] Pause initiale {CALME_INITIAL_SEC // 60} min "
        f"(laisser le throttle BOAMP retomber)...")
    time.sleep(CALME_INITIAL_SEC)

    avant = set(stockage.charger("marches").keys())
    nouveaux = []
    for essai in range(1, NB_ESSAIS_INGEST + 1):
        log(f"[{time.strftime('%H:%M:%S')}] Ingestion essai {essai}/{NB_ESSAIS_INGEST} "
            f"(mode large, DIFFÉRENTIEL depuis le dernier connu)...")
        try:
            tendia_recup.recuperer_tout(
                fenetre_mois=1,
                sources=connecteurs.sources_par_defaut(),
                mode_large=True,
                differentiel=True,
                verbose=False,
            )
        except Exception as e:
            log(f"    exception ingestion : {type(e).__name__}: {str(e)[:160]}")
        apres = stockage.charger("marches")
        nouveaux = [k for k in apres if k not in avant]
        log(f"    → nouveaux marchés ingérés : {len(nouveaux)}")
        if nouveaux:
            break
        if essai < NB_ESSAIS_INGEST:
            log(f"    rien de neuf, pause {DELAI_ENTRE_ESSAIS_SEC // 60} min...")
            time.sleep(DELAI_ENTRE_ESSAIS_SEC)

    if not nouveaux:
        log(f"[{time.strftime('%H:%M:%S')}] Aucun nouveau marché ingéré "
            f"(hôte BOAMP toujours instable). Arrêt — 0 € dépensé.")
        return

    apres = stockage.charger("marches")
    log(f"[{time.strftime('%H:%M:%S')}] {len(nouveaux)} nouveaux marchés :")
    for mid in nouveaux[:20]:
        m = apres.get(mid) or {}
        log(f"    - {mid} | {(m.get('objet') or m.get('titre') or '')[:70]}")

    log(f"[{time.strftime('%H:%M:%S')}] Passe de veille — extraction des nouveaux "
        f"pertinents (cap {CAP_EXTRACTIONS}, seuil pertinent)...")
    proc = subprocess.run(
        [sys.executable, "tendia_veille.py", "--une-passe",
         "--max-extractions", str(CAP_EXTRACTIONS),
         "--seuil-complet", "pertinent", "--mois", "1"],
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
    )
    log(f"[{time.strftime('%H:%M:%S')}] Passe terminée (exit {proc.returncode}).")


if __name__ == "__main__":
    main()
