# Rapport du chantier 0a : nettoyage du dépôt (2026-11-10)

## En bref

- Fichiers suivis par git : **902 avant**, **313 après** (critère < 400 atteint).
- Aucun fichier de `venv/` ni de `data/dce/` suivi (`venv/` et `data/dce/` ne l'étaient déjà plus).
- Aucun `.py` modifié, aucune suppression définitive : tout ce qui a quitté l'index est sur le disque,
  dans l'historique git, et (sauf `data/dce` hors `.bak*`) dans `D:\Projects\tendia_backup_2026-11-10.zip`.
- `python tendia_ui.py` démarre : `/`, `/profil`, `/explorer`, `/decp` et 3 fiches `/marche/<id>` répondent 200, sans traceback.
  `Tendia.bat` n'a pas été lancé : il exécute d'abord le pipeline complet (téléchargements, appels LLM payants).

## À traiter : régressions et points d'attention

1. **`tests/test_dematis_workflow_har.py` : 6 échecs (51 OK avant, 40 OK après).** Ce test lit sa fixture à un chemin
   en dur, `dematis exemple/hautsdeseine-habitat.e-marchespublics.com.har`, archivé à l'étape 3. Vérifié : en remettant
   le fichier en place, on retrouve 51 OK. Correctif (hors périmètre, touche un `.py`) : déplacer la fixture dans
   `tests/fixtures/` et adapter le chemin. Sinon, la remettre à sa place (elle reste hors suivi à cause de `*.har`).
2. **`tests/test_grille_notation.py` n'est pas un test** : c'est un prototype CLI qui appelle l'API Anthropic et
   modifie un brief. Depuis `tests/`, il ne trouve plus les modules de la racine (`ModuleNotFoundError: pdf_extract`).
   À lancer avec `PYTHONPATH=. python tests/test_grille_notation.py <id>`. Un `pytest` lancé sur `tests/` le collecterait
   et échouerait à l'import. Mieux : le ranger dans `scripts/` sous un autre nom.
3. **`archive/` est hors suivi git** (sauf `README.md` et ce rapport). Sinon, les 239 briefs et les fichiers déplacés
   resteraient suivis et le compte ne passerait pas sous 400. Ils restent dans l'historique git.
4. **`rapports/brief_*.md` ajouté au `.gitignore`** (non demandé) : `tendia_extraire.py` continue d'en écrire
   dans `rapports/`, ils réapparaîtraient sinon comme fichiers non suivis.
5. **`data/budget.json` et `data/jointure.json`** avaient des modifications non commitées : elles sont sur le disque mais
   pas dans git (fichiers désormais hors suivi).
6. **Sauvegarde sans `data/dce`** (124 Go, jamais suivi), choix validé en cours de chantier. Les 341 dossiers
   `data/dce/*.bak*` déplacés y sont inclus. Premier zip en échec (chemin > 260 caractères), refait avec le préfixe
   `\\?\` : 5 315 fichiers, 26,29 Go, zip de 21,51 Go, intégrité vérifiée. La copie non zippée
   `D:\Projects\tendia_backup_2026-11-10\` est toujours là (25 Go) : à supprimer à la main une fois le zip jugé suffisant.
7. **Étape 1 sans commit** : elle ne change rien dans le dépôt.

## Hésitations

- `scripts/audit/inspecter_page_dce.py` correspond au motif `inspect*.py` mais c'est un outil d'audit rangé et
  documenté : **gardé**. Les deux `scripts/_archive/inspecter_decp*.py` (déjà archivés) ont été déplacés.
- 32 fichiers `*.bak` imbriqués dans `data/dce/<id>/…` : ce sont des sauvegardes AutoCAD qui font
  partie des DCE des acheteurs, pas des sauvegardes de Tendia. **Laissés en place** : seuls les dossiers `data/dce/*.bak*`
  de premier niveau ont été déplacés.
- `data/debug_*.html` (3 pages de debug du 2026-06-10) : déplacés, ils correspondent à `debug_*.html`.
- `data/tendia.db.backup_*` (6 sauvegardes de base) : ils ne correspondent à aucun motif (`backup_` ≠ `bak_`), **laissés**
  dans `data/`. Hors suivi, à archiver au prochain passage si besoin.
- `exp_gemini/` et `data/exp_gemini/` (expérience en cours, non suivis) : non touchés.
- Aucun fichier `*.original_*`, `diagnostic_*.txt`, `voir_raisons_echec.py`, `place_*`, `scraper_place_discover.py`
  ni `test_xlsx.txt` sur le disque : ils avaient déjà disparu lors d'un nettoyage précédent.

## Doublons de tests tranchés

| Fichier | `HAR/tests/` | `tests/` | Décision |
|---|---|---|---|
| `test_boamp_enrichissement.py` | 30/10 22:12 | 30/10 22:45 | gardé `tests/`, archivé `HAR/tests/` (contenu identique, seules les fins de ligne diffèrent) |
| `test_decp_classifier_cpv.py` | 30/10 22:12 | 30/10 22:45 | gardé `tests/`, archivé `HAR/tests/` (contenu identique, seules les fins de ligne diffèrent) |
| `test_decp_classifier_llm.py` | 30/10 22:12 | 30/10 22:45 | gardé `tests/`, archivé `HAR/tests/` (contenu identique, seules les fins de ligne diffèrent) |
| `test_decp_db.py` | 30/10 22:12 | 30/10 22:45 | gardé `tests/`, archivé `HAR/tests/` (contenu identique, seules les fins de ligne diffèrent) |
| `test_decp_mapping_cpv.py` | 30/10 22:12 | 30/10 22:45 | gardé `tests/`, archivé `HAR/tests/` (contenu identique, seules les fins de ligne diffèrent) |
| `test_decp_matching.py` | 30/10 22:12 | 30/10 22:45 | gardé `tests/`, archivé `HAR/tests/` (contenu identique, seules les fins de ligne diffèrent) |
| `test_decp_parser.py` | 30/10 22:12 | 30/10 22:45 | gardé `tests/`, archivé `HAR/tests/` (contenu identique, seules les fins de ligne diffèrent) |
| `test_downloader_dce_directe.py` | 30/10 22:12 | 30/10 22:45 | gardé `tests/`, archivé `HAR/tests/` (contenu identique, seules les fins de ligne diffèrent) |
| `test_extraction_v2_criteres.py` | 30/10 22:12 | 30/10 22:45 | gardé `tests/`, archivé `HAR/tests/` (contenu identique, seules les fins de ligne diffèrent) |
| `test_extraction_v2_montants.py` | 30/10 22:12 | 30/10 22:45 | gardé `tests/`, archivé `HAR/tests/` (contenu identique, seules les fins de ligne diffèrent) |
| `test_parallelisation.py` | 30/10 22:12 | 30/10 22:45 | gardé `tests/`, archivé `HAR/tests/` (contenu identique, seules les fins de ligne diffèrent) |

Racine → `tests/` : `test_grille_notation.py` → `tests/test_grille_notation.py` (aucun doublon, nom déjà conforme).

## Étape 2 : retirés de l'index git (332 fichiers, conservés sur le disque)

- data/extractions/ : 231
- data/test_dematis_live/ : 45
- data/test_dematis_live/ : 18
- data/extractions_calibrees/ : 16
- data/memoires/ : 9
- data/validation_digests/ : 5
- data/validation_memoires/ : 4
- data/budget.json/ : 1
- data/jointure.json/ : 1
- data/veille_journal.json/ : 1
- dematis exemple/hautsdeseine-habitat.e-marchespublics.com.har/ : 1

## Étape 3 : fichiers archivés (dans `archive/<chemin d'origine>`)

### Sauvegardes (presets, templates, bases, presets_backup) (37)

- `data/tendia.db.bak_avant_3c_20260612_1450`
- `data/tendia.db.bak_avant_decp_reprise_20261102`
- `data/tendia.db.bak_avant_decp_reprise_20261102-shm`
- `data/tendia.db.bak_avant_decp_reprise_20261102-wal`
- `data/tendia.db.bak_avant_digest_20260621_131208`
- `data/tendia.db.bak_avant_memoire_20260621_185845`
- `data/tendia.db.bak_avant_memoire_20260621_192222`
- `data/tendia.db.bak_avant_memoire_20260621_200843`
- `data/tendia.db.bak_avant_purge_juin`
- `data/tendia.db.bak_avant_reextraction_v3_20260622_121208`
- `data/tendia.db.bak_avant_sprintA_20260612_1530`
- `data/tendia.db.bak_avant_sprint_aws`
- `data/tendia.db.bak_sprint_c`
- `data/tendia.db.bak_sprint_p`
- `data/tendia.db.bak_sprint_p_bis`
- `data/tendia.db.bak_sprint_telechargeur`
- `presets/btp/_preset.json.bak_1b_20260614_213839`
- `presets/btp/_preset.json.bak_1c_20260614_214427`
- `presets/conseil/_preset.json.bak_1b_20260614_213839`
- `presets/conseil/_preset.json.bak_1c_20260614_214427`
- `presets/conseil/_preset.json.bak_20260612_1236`
- `presets/conseil/_preset.json.bak_avant_chantier1_20260614_210945`
- `presets/energie_renouvelable/_preset.json.bak_1b_20260614_213839`
- `presets/energie_renouvelable/_preset.json.bak_avant_chantier1_20260614_210945`
- `presets/formation/_preset.json.bak_1b_20260614_213839`
- `presets/formation/_preset.json.bak_avant_chantier1_20260614_210945`
- `presets/ingenierie/_preset.json.bak_1b_20260614_213839`
- `presets/ingenierie/_preset.json.bak_20260612_1236`
- `presets/ingenierie/_preset.json.bak_avant_chantier1_20260614_210945`
- `presets/it/_preset.json.bak_1b_20260614_213839`
- `presets/it/_preset.json.bak_20260612_1236`
- `presets/it/_preset.json.bak_avant_chantier1_20260614_210444`
- `scripts/_archive/presets_backup_20260611_2116/`
- `scripts/_archive/presets_backup_20260611_2143/`
- `ui/templates/marche.html.bak_20260612_2309`
- `ui/templates/profil/edit.html.bak_20260612_1929`
- `ui/templates/profil/edit.html.bak_avant_refonte_hybride`

### Dossiers DCE `data/dce/*.bak*` (341)

- `data/dce/BOAMP-26-51011.bak_avant_reprofond/`
- `data/dce/BOAMP-26-51023.bak_avant_reprofond/`
- `data/dce/BOAMP-26-55964.bak_avant_b12/`
- `data/dce/BOAMP-26-55964.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56006.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56006.bak_avant_b12/`
- `data/dce/BOAMP-26-56042.bak_avant_b12/`
- `data/dce/BOAMP-26-56045.bak_avant_b12/`
- `data/dce/BOAMP-26-56053.bak_avant_vide_atexo/`
- `data/dce/BOAMP-26-56055.bak_avant_b12/`
- `data/dce/BOAMP-26-56055.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56061.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56063.bak_avant_b12/`
- `data/dce/BOAMP-26-56063.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56076.bak_avant_b12/`
- `data/dce/BOAMP-26-56076.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56083.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56090.bak_avant_aws_achat/`
- `data/dce/BOAMP-26-56096.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56115.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56116.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56129.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56134.bak_avant_b12/`
- `data/dce/BOAMP-26-56134.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56140.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56151.bak_avant_b12/`
- `data/dce/BOAMP-26-56151.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56164.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56168.bak_avant_b12/`
- `data/dce/BOAMP-26-56168.bak_avant_vide_atexo/`
- `data/dce/BOAMP-26-56170.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56172.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56190.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56212.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56212.bak_avant_b12/`
- `data/dce/BOAMP-26-56231.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56231.bak_avant_b12/`
- `data/dce/BOAMP-26-56236.bak_avant_b12/`
- `data/dce/BOAMP-26-56236.bak_avant_vide_atexo/`
- `data/dce/BOAMP-26-56238.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56248.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56261.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56262.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56263.bak_avant_b12/`
- `data/dce/BOAMP-26-56263.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56267.bak_avant_b12/`
- `data/dce/BOAMP-26-56267.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56270.bak_avant_b12/`
- `data/dce/BOAMP-26-56270.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56292.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56303.bak_avant_dematis/`
- `data/dce/BOAMP-26-56303.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56305.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56308.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56308.bak_avant_b12/`
- `data/dce/BOAMP-26-56310.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56315.bak_avant_b12/`
- `data/dce/BOAMP-26-56315.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56320.bak_avant_b12/`
- `data/dce/BOAMP-26-56320.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56323.bak_avant_b12/`
- `data/dce/BOAMP-26-56323.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56329.bak_avant_aws_achat/`
- `data/dce/BOAMP-26-56338.bak_avant_aws_achat/`
- `data/dce/BOAMP-26-56341.bak_avant_aws_achat/`
- `data/dce/BOAMP-26-56341.bak_avant_b12/`
- `data/dce/BOAMP-26-56346.bak_avant_vide_atexo/`
- `data/dce/BOAMP-26-56351.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56351.bak_avant_b12/`
- `data/dce/BOAMP-26-56361.bak_avant_b12/`
- `data/dce/BOAMP-26-56361.bak_avant_dematis/`
- `data/dce/BOAMP-26-56361.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56364.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56368.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56378.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56379.bak_avant_b12/`
- `data/dce/BOAMP-26-56379.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56391.bak_avant_b12/`
- `data/dce/BOAMP-26-56391.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56408.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56408.bak_avant_b12/`
- `data/dce/BOAMP-26-56409.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56409.bak_avant_b12/`
- `data/dce/BOAMP-26-56413.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56413.bak_avant_b12/`
- `data/dce/BOAMP-26-56415.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56417.bak_avant_b12/`
- `data/dce/BOAMP-26-56417.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56419.bak_avant_b12/`
- `data/dce/BOAMP-26-56419.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56434.bak_avant_b12/`
- `data/dce/BOAMP-26-56434.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56439.bak_avant_dematis/`
- `data/dce/BOAMP-26-56439.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56440.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56440.bak_avant_b12/`
- `data/dce/BOAMP-26-56454.bak_avant_b12/`
- `data/dce/BOAMP-26-56462.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56463.bak_avant_dematis/`
- `data/dce/BOAMP-26-56463.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56469.bak_avant_dematis/`
- `data/dce/BOAMP-26-56469.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56475.bak_avant_b12/`
- `data/dce/BOAMP-26-56475.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56482.bak_avant_dematis/`
- `data/dce/BOAMP-26-56482.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56488.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56490.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56490.bak_avant_b12/`
- `data/dce/BOAMP-26-56490.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56491.bak_avant_b12/`
- `data/dce/BOAMP-26-56491.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56493.bak_avant_b12/`
- `data/dce/BOAMP-26-56493.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56494.bak_avant_dematis/`
- `data/dce/BOAMP-26-56494.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56495.bak_avant_b12/`
- `data/dce/BOAMP-26-56495.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56507.bak_avant_vide_atexo/`
- `data/dce/BOAMP-26-56510.bak_avant_b12/`
- `data/dce/BOAMP-26-56510.bak_avant_vide_atexo/`
- `data/dce/BOAMP-26-56520.bak_avant_b12/`
- `data/dce/BOAMP-26-56520.bak_avant_vide_atexo/`
- `data/dce/BOAMP-26-56525.bak_avant_dematis/`
- `data/dce/BOAMP-26-56525.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56526.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56526.bak_avant_b12/`
- `data/dce/BOAMP-26-56527.bak_avant_b12/`
- `data/dce/BOAMP-26-56531.bak_avant_b12/`
- `data/dce/BOAMP-26-56531.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56532.bak_avant_b12/`
- `data/dce/BOAMP-26-56532.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56539.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56546.bak_avant_b12/`
- `data/dce/BOAMP-26-56546.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56547.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56558.bak_avant_b12/`
- `data/dce/BOAMP-26-56558.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56563.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56563.bak_avant_b12/`
- `data/dce/BOAMP-26-56574.bak_avant_dematis/`
- `data/dce/BOAMP-26-56574.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56575.bak_avant_b12/`
- `data/dce/BOAMP-26-56575.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56576.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56576.bak_avant_b12/`
- `data/dce/BOAMP-26-56588.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56592.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56593.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56594.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56596.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56598.bak_avant_b12/`
- `data/dce/BOAMP-26-56598.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56626.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56626.bak_avant_b12/`
- `data/dce/BOAMP-26-56627.bak_avant_b12/`
- `data/dce/BOAMP-26-56627.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56631.bak_avant_b12/`
- `data/dce/BOAMP-26-56631.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56633.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56635.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56635.bak_avant_b12/`
- `data/dce/BOAMP-26-56635.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56638.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56638.bak_avant_b12/`
- `data/dce/BOAMP-26-56642.bak_avant_dematis/`
- `data/dce/BOAMP-26-56642.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56652.bak_avant_b12/`
- `data/dce/BOAMP-26-56652.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56656.bak_avant_b12/`
- `data/dce/BOAMP-26-56656.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56657.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56662.bak_avant_b12/`
- `data/dce/BOAMP-26-56662.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56664.bak_avant_b12/`
- `data/dce/BOAMP-26-56664.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56670.bak_avant_b12/`
- `data/dce/BOAMP-26-56691.bak_avant_dematis/`
- `data/dce/BOAMP-26-56691.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56706.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56706.bak_avant_b12/`
- `data/dce/BOAMP-26-56710.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56712.bak_avant_dematis/`
- `data/dce/BOAMP-26-56712.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56729.bak_avant_dematis/`
- `data/dce/BOAMP-26-56729.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56730.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56730.bak_avant_b12/`
- `data/dce/BOAMP-26-56732.bak_avant_b12/`
- `data/dce/BOAMP-26-56732.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56734.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56734.bak_avant_b12/`
- `data/dce/BOAMP-26-56737.bak_avant_dematis/`
- `data/dce/BOAMP-26-56737.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56743.bak_avant_b12/`
- `data/dce/BOAMP-26-56743.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56745.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56745.bak_avant_b12/`
- `data/dce/BOAMP-26-56746.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56746.bak_avant_b12/`
- `data/dce/BOAMP-26-56749.bak_avant_b12/`
- `data/dce/BOAMP-26-56750.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56750.bak_avant_b12/`
- `data/dce/BOAMP-26-56751.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56751.bak_avant_b12/`
- `data/dce/BOAMP-26-56752.bak_avant_b12/`
- `data/dce/BOAMP-26-56752.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56753.bak_avant_b12/`
- `data/dce/BOAMP-26-56753.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56753.bak_avant_vide_atexo/`
- `data/dce/BOAMP-26-56757.bak_avant_b12/`
- `data/dce/BOAMP-26-56757.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56758.bak_avant_vide_atexo/`
- `data/dce/BOAMP-26-56760.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56763.bak_avant_b12/`
- `data/dce/BOAMP-26-56763.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56766.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56768.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56774.bak_avant_b12/`
- `data/dce/BOAMP-26-56774.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56815.bak_avant_b12/`
- `data/dce/BOAMP-26-56815.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56842.bak_avant_b12/`
- `data/dce/BOAMP-26-56842.bak_avant_dematis/`
- `data/dce/BOAMP-26-56842.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56848.bak_avant_b12/`
- `data/dce/BOAMP-26-56848.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56881.bak_avant_b12/`
- `data/dce/BOAMP-26-56881.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56883.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56883.bak_avant_b12/`
- `data/dce/BOAMP-26-56887.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56887.bak_avant_b12/`
- `data/dce/BOAMP-26-56958.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56958.bak_avant_b12/`
- `data/dce/BOAMP-26-56959.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-56959.bak_avant_b12/`
- `data/dce/BOAMP-26-56968.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56970.bak_avant_reprofond/`
- `data/dce/BOAMP-26-56972.bak_avant_b12/`
- `data/dce/BOAMP-26-56972.bak_avant_reprofond/`
- `data/dce/BOAMP-26-57028.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-57028.bak_avant_b12/`
- `data/dce/BOAMP-26-57054.bak_avant_reprofond/`
- `data/dce/BOAMP-26-57058.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-57058.bak_avant_b12/`
- `data/dce/BOAMP-26-57070.bak_avant_b12/`
- `data/dce/BOAMP-26-57070.bak_avant_dematis/`
- `data/dce/BOAMP-26-57070.bak_avant_reprofond/`
- `data/dce/BOAMP-26-57094.bak_avant_reprofond/`
- `data/dce/BOAMP-26-57123.bak_avant_aws_achat/`
- `data/dce/BOAMP-26-57153.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-57153.bak_avant_b12/`
- `data/dce/BOAMP-26-57166.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-57166.bak_avant_b12/`
- `data/dce/BOAMP-26-57168.bak_avant_reprofond/`
- `data/dce/BOAMP-26-57174.bak_avant_b12/`
- `data/dce/BOAMP-26-57174.bak_avant_vide_atexo/`
- `data/dce/BOAMP-26-57203.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-57203.bak_avant_b12/`
- `data/dce/BOAMP-26-57238.bak_avant_reprofond/`
- `data/dce/BOAMP-26-57239.bak_avant_b12/`
- `data/dce/BOAMP-26-57239.bak_avant_reprofond/`
- `data/dce/BOAMP-26-57239.bak_avant_vide_atexo/`
- `data/dce/BOAMP-26-57240.bak_avant_reprofond/`
- `data/dce/BOAMP-26-57252.bak_avant_reprofond/`
- `data/dce/BOAMP-26-57265.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-57278.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-57278.bak_avant_b12/`
- `data/dce/BOAMP-26-57285.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-57286.bak_avant_achatpublic/`
- `data/dce/BOAMP-26-57286.bak_avant_b12/`
- `data/dce/BOAMP-26-62817.bak_avant_reprofond/`
- `data/dce/BOAMP-26-62821.bak_avant_aws_achat/`
- `data/dce/BOAMP-26-62821.bak_avant_reprofond/`
- `data/dce/BOAMP-26-62857.bak_avant_reprofond/`
- `data/dce/BOAMP-26-62875.bak_avant_reprofond/`
- `data/dce/BOAMP-26-62902.bak_avant_reprofond/`
- `data/dce/BOAMP-26-62912.bak_avant_reprofond/`
- `data/dce/BOAMP-26-62947.bak_avant_reprofond/`
- `data/dce/BOAMP-26-62948.bak_avant_reprofond/`
- `data/dce/BOAMP-26-62950.bak_avant_reprofond/`
- `data/dce/BOAMP-26-62955.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63000.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63019.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63020.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63043.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63045.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63051.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63054.bak_avant_dematis/`
- `data/dce/BOAMP-26-63054.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63071.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63072.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63333.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63335.bak_avant_dematis/`
- `data/dce/BOAMP-26-63335.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63352.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63360.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63364.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63402.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63407.bak_avant_dematis/`
- `data/dce/BOAMP-26-63407.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63422.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63429.bak_avant_dematis/`
- `data/dce/BOAMP-26-63429.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63432.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63464.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63477.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63496.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63510.bak_avant_dematis/`
- `data/dce/BOAMP-26-63510.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63519.bak_avant_dematis/`
- `data/dce/BOAMP-26-63519.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63579.bak_avant_dematis/`
- `data/dce/BOAMP-26-63579.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63580.bak_avant_dematis/`
- `data/dce/BOAMP-26-63580.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63619.bak_avant_dematis/`
- `data/dce/BOAMP-26-63619.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63624.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63633.bak_avant_dematis/`
- `data/dce/BOAMP-26-63633.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63635.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63669.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63673.bak_avant_dematis/`
- `data/dce/BOAMP-26-63673.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63681.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63716.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63732.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63734.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63749.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63755.bak_avant_dematis/`
- `data/dce/BOAMP-26-63755.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63756.bak_avant_dematis/`
- `data/dce/BOAMP-26-63756.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63758.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63790.bak_avant_dematis/`
- `data/dce/BOAMP-26-63790.bak_avant_reprofond/`
- `data/dce/BOAMP-26-63808.bak_avant_reprofond/`
- `data/dce/BOAMP-26-64321.bak_avant_aws_achat/`
- `data/dce/BOAMP-26-64359.bak_avant_aws_achat/`

### Scripts et sorties de diagnostic (5)

- `data/debug_martinique_developpement.e_marchespublics.com_20260610_204405.html`
- `data/debug_musee_orsay.e_marchespublics.com_20260610_204406.html`
- `data/debug_www.e_marchespublics.com_20260610_204405.html`
- `scripts/_archive/inspecter_decp.py`
- `scripts/_archive/inspecter_decp_consolidee.py`

### Dossiers entiers (3)

- `dematis exemple/`
- `HAR/`
- `docs/archive/_jetables/`

### Briefs générés `rapports/brief_*.md` (239)

- `rapports/brief_BOAMP-26-51011.md`
- `rapports/brief_BOAMP-26-51023.md`
- `rapports/brief_BOAMP-26-55964.md`
- `rapports/brief_BOAMP-26-55977.md`
- `rapports/brief_BOAMP-26-55979.md`
- `rapports/brief_BOAMP-26-56006.md`
- `rapports/brief_BOAMP-26-56021.md`
- `rapports/brief_BOAMP-26-56023.md`
- `rapports/brief_BOAMP-26-56027.md`
- `rapports/brief_BOAMP-26-56029.md`
- `rapports/brief_BOAMP-26-56053.md`
- `rapports/brief_BOAMP-26-56055.md`
- `rapports/brief_BOAMP-26-56061.md`
- `rapports/brief_BOAMP-26-56063.md`
- `rapports/brief_BOAMP-26-56068.md`
- `rapports/brief_BOAMP-26-56076.md`
- `rapports/brief_BOAMP-26-56083.md`
- `rapports/brief_BOAMP-26-56090.md`
- `rapports/brief_BOAMP-26-56096.md`
- `rapports/brief_BOAMP-26-56097.md`
- `rapports/brief_BOAMP-26-56098.md`
- `rapports/brief_BOAMP-26-56115.md`
- `rapports/brief_BOAMP-26-56116.md`
- `rapports/brief_BOAMP-26-56126.md`
- `rapports/brief_BOAMP-26-56129.md`
- `rapports/brief_BOAMP-26-56134.md`
- `rapports/brief_BOAMP-26-56140.md`
- `rapports/brief_BOAMP-26-56150.md`
- `rapports/brief_BOAMP-26-56151.md`
- `rapports/brief_BOAMP-26-56164.md`
- `rapports/brief_BOAMP-26-56165.md`
- `rapports/brief_BOAMP-26-56170.md`
- `rapports/brief_BOAMP-26-56172.md`
- `rapports/brief_BOAMP-26-56190.md`
- `rapports/brief_BOAMP-26-56191.md`
- `rapports/brief_BOAMP-26-56212.md`
- `rapports/brief_BOAMP-26-56215.md`
- `rapports/brief_BOAMP-26-56231.md`
- `rapports/brief_BOAMP-26-56238.md`
- `rapports/brief_BOAMP-26-56245.md`
- `rapports/brief_BOAMP-26-56248.md`
- `rapports/brief_BOAMP-26-56261.md`
- `rapports/brief_BOAMP-26-56262.md`
- `rapports/brief_BOAMP-26-56263.md`
- `rapports/brief_BOAMP-26-56267.md`
- `rapports/brief_BOAMP-26-56270.md`
- `rapports/brief_BOAMP-26-56275.md`
- `rapports/brief_BOAMP-26-56280.md`
- `rapports/brief_BOAMP-26-56292.md`
- `rapports/brief_BOAMP-26-56303.md`
- `rapports/brief_BOAMP-26-56305.md`
- `rapports/brief_BOAMP-26-56308.md`
- `rapports/brief_BOAMP-26-56310.md`
- `rapports/brief_BOAMP-26-56315.md`
- `rapports/brief_BOAMP-26-56320.md`
- `rapports/brief_BOAMP-26-56323.md`
- `rapports/brief_BOAMP-26-56326.md`
- `rapports/brief_BOAMP-26-56329.md`
- `rapports/brief_BOAMP-26-56331.md`
- `rapports/brief_BOAMP-26-56333.md`
- `rapports/brief_BOAMP-26-56335.md`
- `rapports/brief_BOAMP-26-56338.md`
- `rapports/brief_BOAMP-26-56340.md`
- `rapports/brief_BOAMP-26-56341.md`
- `rapports/brief_BOAMP-26-56346.md`
- `rapports/brief_BOAMP-26-56351.md`
- `rapports/brief_BOAMP-26-56361.md`
- `rapports/brief_BOAMP-26-56364.md`
- `rapports/brief_BOAMP-26-56368.md`
- `rapports/brief_BOAMP-26-56378.md`
- `rapports/brief_BOAMP-26-56379.md`
- `rapports/brief_BOAMP-26-56391.md`
- `rapports/brief_BOAMP-26-56408.md`
- `rapports/brief_BOAMP-26-56409.md`
- `rapports/brief_BOAMP-26-56411.md`
- `rapports/brief_BOAMP-26-56413.md`
- `rapports/brief_BOAMP-26-56415.md`
- `rapports/brief_BOAMP-26-56417.md`
- `rapports/brief_BOAMP-26-56419.md`
- `rapports/brief_BOAMP-26-56426.md`
- `rapports/brief_BOAMP-26-56434.md`
- `rapports/brief_BOAMP-26-56439.md`
- `rapports/brief_BOAMP-26-56440.md`
- `rapports/brief_BOAMP-26-56448.md`
- `rapports/brief_BOAMP-26-56450.md`
- `rapports/brief_BOAMP-26-56451.md`
- `rapports/brief_BOAMP-26-56454.md`
- `rapports/brief_BOAMP-26-56455.md`
- `rapports/brief_BOAMP-26-56456.md`
- `rapports/brief_BOAMP-26-56459.md`
- `rapports/brief_BOAMP-26-56462.md`
- `rapports/brief_BOAMP-26-56463.md`
- `rapports/brief_BOAMP-26-56464.md`
- `rapports/brief_BOAMP-26-56469.md`
- `rapports/brief_BOAMP-26-56475.md`
- `rapports/brief_BOAMP-26-56478.md`
- `rapports/brief_BOAMP-26-56482.md`
- `rapports/brief_BOAMP-26-56484.md`
- `rapports/brief_BOAMP-26-56488.md`
- `rapports/brief_BOAMP-26-56491.md`
- `rapports/brief_BOAMP-26-56493.md`
- `rapports/brief_BOAMP-26-56494.md`
- `rapports/brief_BOAMP-26-56496.md`
- `rapports/brief_BOAMP-26-56498.md`
- `rapports/brief_BOAMP-26-56510.md`
- `rapports/brief_BOAMP-26-56517.md`
- `rapports/brief_BOAMP-26-56520.md`
- `rapports/brief_BOAMP-26-56525.md`
- `rapports/brief_BOAMP-26-56526.md`
- `rapports/brief_BOAMP-26-56527.md`
- `rapports/brief_BOAMP-26-56531.md`
- `rapports/brief_BOAMP-26-56532.md`
- `rapports/brief_BOAMP-26-56539.md`
- `rapports/brief_BOAMP-26-56546.md`
- `rapports/brief_BOAMP-26-56547.md`
- `rapports/brief_BOAMP-26-56553.md`
- `rapports/brief_BOAMP-26-56554.md`
- `rapports/brief_BOAMP-26-56558.md`
- `rapports/brief_BOAMP-26-56563.md`
- `rapports/brief_BOAMP-26-56574.md`
- `rapports/brief_BOAMP-26-56575.md`
- `rapports/brief_BOAMP-26-56576.md`
- `rapports/brief_BOAMP-26-56583.md`
- `rapports/brief_BOAMP-26-56588.md`
- `rapports/brief_BOAMP-26-56591.md`
- `rapports/brief_BOAMP-26-56592.md`
- `rapports/brief_BOAMP-26-56593.md`
- `rapports/brief_BOAMP-26-56594.md`
- `rapports/brief_BOAMP-26-56596.md`
- `rapports/brief_BOAMP-26-56598.md`
- `rapports/brief_BOAMP-26-56599.md`
- `rapports/brief_BOAMP-26-56600.md`
- `rapports/brief_BOAMP-26-56605.md`
- `rapports/brief_BOAMP-26-56606.md`
- `rapports/brief_BOAMP-26-56608.md`
- `rapports/brief_BOAMP-26-56610.md`
- `rapports/brief_BOAMP-26-56611.md`
- `rapports/brief_BOAMP-26-56614.md`
- `rapports/brief_BOAMP-26-56626.md`
- `rapports/brief_BOAMP-26-56627.md`
- `rapports/brief_BOAMP-26-56628.md`
- `rapports/brief_BOAMP-26-56631.md`
- `rapports/brief_BOAMP-26-56632.md`
- `rapports/brief_BOAMP-26-56633.md`
- `rapports/brief_BOAMP-26-56638.md`
- `rapports/brief_BOAMP-26-56642.md`
- `rapports/brief_BOAMP-26-56652.md`
- `rapports/brief_BOAMP-26-56656.md`
- `rapports/brief_BOAMP-26-56662.md`
- `rapports/brief_BOAMP-26-56664.md`
- `rapports/brief_BOAMP-26-56668.md`
- `rapports/brief_BOAMP-26-56669.md`
- `rapports/brief_BOAMP-26-56670.md`
- `rapports/brief_BOAMP-26-56673.md`
- `rapports/brief_BOAMP-26-56674.md`
- `rapports/brief_BOAMP-26-56676.md`
- `rapports/brief_BOAMP-26-56677.md`
- `rapports/brief_BOAMP-26-56680.md`
- `rapports/brief_BOAMP-26-56691.md`
- `rapports/brief_BOAMP-26-56702.md`
- `rapports/brief_BOAMP-26-56706.md`
- `rapports/brief_BOAMP-26-56710.md`
- `rapports/brief_BOAMP-26-56712.md`
- `rapports/brief_BOAMP-26-56717.md`
- `rapports/brief_BOAMP-26-56720.md`
- `rapports/brief_BOAMP-26-56729.md`
- `rapports/brief_BOAMP-26-56730.md`
- `rapports/brief_BOAMP-26-56732.md`
- `rapports/brief_BOAMP-26-56734.md`
- `rapports/brief_BOAMP-26-56737.md`
- `rapports/brief_BOAMP-26-56743.md`
- `rapports/brief_BOAMP-26-56745.md`
- `rapports/brief_BOAMP-26-56746.md`
- `rapports/brief_BOAMP-26-56749.md`
- `rapports/brief_BOAMP-26-56750.md`
- `rapports/brief_BOAMP-26-56751.md`
- `rapports/brief_BOAMP-26-56752.md`
- `rapports/brief_BOAMP-26-56757.md`
- `rapports/brief_BOAMP-26-56758.md`
- `rapports/brief_BOAMP-26-56760.md`
- `rapports/brief_BOAMP-26-56763.md`
- `rapports/brief_BOAMP-26-56766.md`
- `rapports/brief_BOAMP-26-56768.md`
- `rapports/brief_BOAMP-26-56774.md`
- `rapports/brief_BOAMP-26-56777.md`
- `rapports/brief_BOAMP-26-56782.md`
- `rapports/brief_BOAMP-26-56786.md`
- `rapports/brief_BOAMP-26-56790.md`
- `rapports/brief_BOAMP-26-56791.md`
- `rapports/brief_BOAMP-26-56815.md`
- `rapports/brief_BOAMP-26-56842.md`
- `rapports/brief_BOAMP-26-56848.md`
- `rapports/brief_BOAMP-26-56857.md`
- `rapports/brief_BOAMP-26-56871.md`
- `rapports/brief_BOAMP-26-56881.md`
- `rapports/brief_BOAMP-26-56883.md`
- `rapports/brief_BOAMP-26-56887.md`
- `rapports/brief_BOAMP-26-56924.md`
- `rapports/brief_BOAMP-26-56926.md`
- `rapports/brief_BOAMP-26-56928.md`
- `rapports/brief_BOAMP-26-56929.md`
- `rapports/brief_BOAMP-26-56941.md`
- `rapports/brief_BOAMP-26-56958.md`
- `rapports/brief_BOAMP-26-56959.md`
- `rapports/brief_BOAMP-26-56968.md`
- `rapports/brief_BOAMP-26-56970.md`
- `rapports/brief_BOAMP-26-56972.md`
- `rapports/brief_BOAMP-26-56995.md`
- `rapports/brief_BOAMP-26-57006.md`
- `rapports/brief_BOAMP-26-57028.md`
- `rapports/brief_BOAMP-26-57038.md`
- `rapports/brief_BOAMP-26-57054.md`
- `rapports/brief_BOAMP-26-57058.md`
- `rapports/brief_BOAMP-26-57070.md`
- `rapports/brief_BOAMP-26-57075.md`
- `rapports/brief_BOAMP-26-57080.md`
- `rapports/brief_BOAMP-26-57094.md`
- `rapports/brief_BOAMP-26-57132.md`
- `rapports/brief_BOAMP-26-57133.md`
- `rapports/brief_BOAMP-26-57153.md`
- `rapports/brief_BOAMP-26-57166.md`
- `rapports/brief_BOAMP-26-57168.md`
- `rapports/brief_BOAMP-26-57174.md`
- `rapports/brief_BOAMP-26-57186.md`
- `rapports/brief_BOAMP-26-57187.md`
- `rapports/brief_BOAMP-26-57188.md`
- `rapports/brief_BOAMP-26-57203.md`
- `rapports/brief_BOAMP-26-57216.md`
- `rapports/brief_BOAMP-26-57218.md`
- `rapports/brief_BOAMP-26-57238.md`
- `rapports/brief_BOAMP-26-57240.md`
- `rapports/brief_BOAMP-26-57252.md`
- `rapports/brief_BOAMP-26-57260.md`
- `rapports/brief_BOAMP-26-57261.md`
- `rapports/brief_BOAMP-26-57263.md`
- `rapports/brief_BOAMP-26-57265.md`
- `rapports/brief_BOAMP-26-57278.md`
- `rapports/brief_BOAMP-26-57285.md`
- `rapports/brief_BOAMP-26-57286.md`

