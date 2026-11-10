# archive/

Fichiers mis de côté le 2026-11-10, supprimés si personne ne les réclame avant le 2027-01-09.

L'arborescence d'origine est conservée : `archive/presets/it/_preset.json.bak_…` venait de
`presets/it/_preset.json.bak_…`. Pour récupérer un fichier, déplacez-le à son chemin d'origine.

Le contenu de ce dossier n'est **pas suivi par git** (voir `.gitignore`), seuls ce README et
`RAPPORT_0a.md` le sont. Les fichiers qui étaient suivis restent dans l'historique git
(commit précédant « chore: archive les scripts jetables et sauvegardes »). Une copie complète
de `data/` (hors DCE), `logs/` et `presets/` existe dans `D:\Projects\tendia_backup_2026-11-10.zip`.

Contenu :

- sauvegardes : `*.bak`, `*.bak_*`, `*.original_*`, `presets_backup_*` (presets, templates UI,
  bases `data/tendia.db.bak_*`, dossiers DCE `data/dce/*.bak_avant_*`)
- scripts et sorties de diagnostic : `debug_*`, `inspecter_decp*.py`, `docs/archive/_jetables/`
- captures : `HAR/` (dont `HAR/tests/`, doublons de `tests/`), `dematis exemple/`
- sorties générées : `rapports/brief_*.md` (re-générables via
  `scripts/maintenance/regenerer_briefs_md.py`)

Détail dans `RAPPORT_0a.md`.
