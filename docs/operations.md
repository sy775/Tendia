# Manuel d'opération

Lancer les traitements, monitorer, sauvegarder/restaurer. Doc ancrée sur les
scripts réels.

## Sauvegarde / restauration de la base

- La base est `data/tendia.db` (SQLite, ~80 Mo). **Backup avant toute opération
  structurelle** :
  ```bash
  cp data/tendia.db data/tendia.db.backup_$(date +%Y%m%d_%H%M)
  ```
  (Convention déjà présente : `tendia.db.backup_*`, `tendia.db.bak_avant_*`.)
- Restauration : arrêter les process écrivains, remplacer `data/tendia.db` par le
  backup. Penser aux sidecars WAL (`tendia.db-wal`, `tendia.db-shm`) — checkpoint
  ou supprimer les sidecars avant restauration à froid.
- Sauvegarde ciblée d'une collection (ex. avant re-extraction) :
  `python -c "import stockage,json; json.dump(stockage.charger('briefs_extraits'), open('backups/briefs_<date>.json','w'), ensure_ascii=False)"`.

## Lancer le pipeline (par étape)

```bash
python tendia_veille.py            # ingestion BOAMP/TED → marches
python tendia_classification.py    # classification sectorielle → classifications_ia
python tendia_dce.py               # résolution URL DCE (par défaut marchés actifs)
# téléchargement DCE (batchs anti-ban, réseau) :
python retelecharger_dematis_anti_ban.py --max 15 --oui [--ignorer-heures]
python retelecharger_aws_achat_anti_ban.py [...]
python relancer_dce_echecs.py [...]
# extraction brief complet :
python tendia_extraire.py --marche <id>
python reextraire_briefs_complet.py --oui [--limite N]
# matching / analyse :
python analyse.py
python tendia_matcher.py
```

Lancer l'UI : `python tendia_ui.py` → http://localhost:5000.

## Batchs de téléchargement anti-ban

- Pacing : délai gaussien ~60 s entre marchés, pause cumulative tous les 20,
  contrainte heures de bureau (sauf `--ignorer-heures`), arrêt après 3 bans consécutifs.
- Idempotents : sautent les marchés déjà OK ; backup `.bak_avant_*` du dossier avant
  re-DL (et le vident pour forcer un re-DL complet — cf Dematis).
- Coût : ~0,001 $/captcha + bande passante proxy (cf [cost.md](cost.md)).

## Re-extraction des briefs (LLM)

- `reextraire_briefs_complet.py --oui [--limite N]` : re-extrait les marchés `complet`
  pas encore marqués `genere_avec_dce_complet`. ⚠️ fait un scan global des dossiers DCE
  (lent : re-décompresse tout, y compris gros DCE).
- Pour une re-extraction priorisée/plafonnée : `relancer_extraction_chantier1.py
  --plafond-eur 30 --oui` (1/preset garanti, priorisé par gisement, géants > 500 Mo
  écartés, log flushé `logs/chantier1_1g_*.jsonl`).
- **Toujours** backup `briefs_extraits` avant.

## Monitoring

- **Logs JSONL** : `logs/<downloader>_<date>.jsonl` (1 ligne/événement). Tail pour
  suivre un batch en direct (flushé par événement, contrairement à stdout bufferisé).
- **Budget LLM** : `python tendia_monitoring.py` / `budget.py` (compteur jour,
  coût cumulé, journal `llm_appels`).
- **Stats pipeline** : `python stats_pipeline_dce.py`, `python bilan_briefs.py`,
  `python audit_classifications.py`.
- **Suivi d'un batch via la base** (quand stdout est bufferisé) :
  ```bash
  python -c "import stockage; from collections import Counter; m=stockage.charger('marches'); \
  print(Counter(v.get('dce_contenu') for v in m.values() if 'e-marchespublics' in (v.get('url_dce') or '')))"
  ```

## Proxy

- Activer : renseigner `TENDIA_PROXY_URL` (IPRoyal) dans `.env`.
- Désactiver pour une plateforme sans ban : `TENDIA_PROXY_FOR_<P>=0`
  (déjà : `PLACE`, `BOAMP`, `DATA_GOUV`).
- Surveiller la consommation Go (poste de coût) — cf [cost.md](cost.md).

## Arrêt propre d'un serveur/batch

- UI : `Ctrl+C`, ou `taskkill /PID <pid> /F` (vérifier `netstat -ano | grep :5000`
  pour ne pas laisser de serveur stale).
- Batch : interrompre ; les batchs persistent par marché (reprise idempotente).
