# scripts/_archive

Scripts et dossiers **legacy, non maintenus**, sortis de la racine au nettoyage
du 2026-10-30. Gardés pour référence ; rien dans l'UI ni le pipeline ne les utilise.

- **DECP « France Travail » (ancienne génération)** : `decp.py`, `tendia_decp.py`,
  `enrichissement_sirene.py`, `inspecter_decp*.py`, `tendia_capture_attributions.py`,
  `tendia_decp_volumes.py` — remplacés par le package `decp/` et `connecteurs/decp_consolidee.py`.
- **Outils d'avant l'UI** : `tendia_matcher.py`, `tendia_apercu.py`, `tendia_veille.py`,
  `enrichir_complet.py`, `tendia_briefs_auto.py`, `tester_*.py` (+ `profils_test/`).
- **Tests live plateformes** (réseau, captcha) : `test_aws_*.py`, `test_achatpublic.py`, `test_atexo_*.py`.
- **Maintenance one-shot déjà exécutée** : `backfill_contacts_boamp.py`, `backfill_dce_qualite.py`,
  `nettoyer_*.py`, `purger_briefs_faux.py`, `reparer_statuts.py`, `identifier_briefs_pollues.py`.
- **Sauvegardes de presets** : `presets_backup_20260611_*`.

⚠️ Connus cassés (lisent `data/marches.json` / `data/marches_notifies.json`, disparus
depuis la migration SQLite) : `tendia_briefs_auto.py`, `tendia_decp_volumes.py`.
Les autres se lancent depuis la racine : `python scripts/_archive/<script>.py`.
