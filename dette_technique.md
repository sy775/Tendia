# Dette technique — inventaire

Inventaire factuel (juin 2026). **Rien n'est supprimé** : ceci est une liste pour
priorisation. Sources : lecture du code (docs modules) + incidents de la session.

## 1. Bugs latents / risques

| # | Risque | Emplacement | Détail |
|---|---|---|---|
| B1 | **cdn_bypass non commité casse les tests** | `aws_downloader.py` (`_session_sans_proxy`) | Patch présent dans le working tree (non commité) ; `tests_aws_downloader.py` échoue car `_session_sans_proxy` crée une vraie session, contournant le `FakeSession` du test. À committer proprement + adapter le test (mocker `_session_sans_proxy`). |
| B2 | **Mismatch nommage log vs proxy** | downloaders / `http_humain` | Le nom de downloader dans les logs JSONL (`aws-achat`) diffère du code plateforme proxy (`aws_achat`). Risque de confusion / requêtes de logs ratées. |
| B3 | **Schéma `_meta` divergent** | `auto_brief` (light) vs `tendia_extraire` (complet) | `tokens_in`/`tokens_out` vs `tokens_input`/`tokens_output` ; `date_generation` vs `extraction_le`. Tout outil lisant `_meta` doit gérer les deux. Convention cible : `tokens_input` + `date_generation`. |
| B4 | **Dépendance truststore implicite** | tout module réseau | Sur ce poste, sans `truststore` injecté, le SSL échoue (anthropic, e-marchespublics, 2captcha). Injecté dans `http_client.py` ET `llm_extract.py` ; un nouveau process/module réseau qui n'importe ni l'un ni l'autre re-cassera. |
| B5 | **Intégrité preset (classe de bug)** | `presets/<code>/_preset.json` | Le preset IT contenait par erreur le contenu ingénierie (corrigé `8d57803`). Aucune validation `meta.code == dossier` ni unicité. Ajouter un check au chargement. |
| B6 | **Rotation IP absente** | `atexo_downloader`, `achatpublic_downloader` | Pas de retry/rotation IP sur ban (présent seulement Dematis/AWS). À confirmer si voulu. |
| B7 | **Appel sur fonction privée** | `enrichir_complet.py`, `diagnostic_dce_pertinents.py` | Appellent `analyse._ids_marches_pertinents()` (privée). Couplage fragile → exposer une API publique. |
| B8 | **`pdfs_traites` ≠ pièces envoyées** | `tendia_extraire.traiter_marche` | `_meta.pdfs_traites` liste tous les `pdfs`, mais l'appel LLM ne porte que sur `pdfs_valides`. Traçabilité trompeuse. |
| B9 | **Docstring obsolète** | `llm_extract._construire_prompt_utilisateur` | Le docstring parle encore d'« union complète » alors que le hors-périmètre injecte un schéma neutre (comportement corrigé en 1D). |
| B10 | **Verdict non caché** | `matching.evaluer` (via UI) | Recalculé à chaque affichage (Explorer ~2 s sur ~430 marchés). Envisager un cache (collection `matchings` existe mais vide). |
| B11 | **`statistiques()` incomplète** | `analyse.py` | N'implémente pas tout son docstring (pas de ventilation par type_marche/CPV). |
| B12 | **DCE PLACE/Atexo faussement `incomplet` (pièces non récupérées)** | `tendia_telecharger_dce.telecharger_pieces_dce` + chaîne d'extraction + env | **3 couches** (constaté 16/06 sur ~13 incomplets PLACE). (a) Le téléchargeur profond scrape les liens, choppe le bouton « Téléchargez le RC » (`nb_ok=1`), puis **saute le repli Atexo** car il est gaté sur `nb_ok==0` (l. ~714) → il ne déclenche JAMAIS le `completeDownload` (zip dossier complet) que fait pourtant `atexo_downloader.telecharger_dce`. (b) Le `completeDownload` PLACE ramène un **`.zip` contenant un `.7z` imbriqué** (ex. `dce_*.zip → DCE_*.7z → {RC,CCAP,CCTP,AE,BPU,…}`) ; la chaîne ne déballe pas `zip→7z` (un seul niveau). (c) **`py7zr` n'était pas installé** dans le python système (pourtant dans `requirements.txt`) → extraction `.7z` impossible. **Conséquence** : dossier marqué `incomplet` avec le seul RC alors que le dossier complet est disponible. **Preuve/contournement** (16/06) : `py7zr` installé (`pip install py7zr --use-feature=truststore`), script `recuperer_dce_7z_imbrique.py` (extraction récursive zip→7z→rar à plat + re-qualif) → 3 marchés repassés `complet` (55964, 56593, 56532). Les 14 autres sont **réellement RC-only** (phase candidature / pièce unique publiée). **Fix de fond à faire** : (1) dans `telecharger_pieces_dce`, pour les hôtes Atexo/PLACE (`atexo_downloader._detecter_url_base`), appeler `atexo_downloader.telecharger_dce_pour_marche` **en priorité** (ou déclencher le repli même si le RC est déjà scrapé), (2) faire récurser `tendia_extraire._dezipper_dossier` sur `zip→7z→rar`, (3) figer `py7zr` (et `rarfile`/`unrar` optionnels) comme dépendances installées de l'environnement de prod. ⚠️ NB : `--trusted-host` est interdit (casse TLS) — utiliser `--use-feature=truststore`. **MAJ 16/06 (enrichissement BOAMP v2)** : `cbc:EndpointID` de l'avis est désormais extrait dans `marche.url_consultation_dce_directe` (URL directe de consultation + `PCSLID`). Le downloader DCE pourra l'utiliser **en priorité** avant son code actuel de reconstruction d'URL → **B12 devient marginal** (ne subsiste que pour les avis sans EndpointID / formats legacy). **RÉSOLU EN PRATIQUE 17/06 (refonte pipeline v2)** : `tendia_telecharger_dce.telecharger_pieces_dce` est désormais un wrapper qui tente `url_consultation_dce_directe` **en priorité** (copie du marché avec `url_dce` surchargé) puis se replie sur l'URL reconstruite — confirmé fonctionnel (Atexo/maximilien : ZIP récupéré via l'URL directe). Re-download des candidats via `scripts/retenter_download_dce.py`. B12 ne subsiste que pour les avis legacy sans EndpointID et les plateformes auth-gated. |
| B13 | **`acheteur_type` à dériver (post-v2)** | enrichissement marché | Après l'enrichissement v2, dériver `acheteur_type` (collectivité / État / hôpital / bailleur / EPCI…) depuis `acheteur_nom` + `acheteur_siren` par **règles déterministes** (mots-clés nom + tranches SIREN). ~30 min de boulot, **utile pour un filtre UI ultérieur**. Non bloquant. |
| B14 | **Purge `brief_v1_backup` à 30 jours** | briefs_extraits | La refonte pipeline v2 stocke le brief v1 dans `brief_v1_backup` (rollback) avec `brief_v1_backup_expire_le`. **Job de purge à automatiser** (supprimer le champ au-delà de 30 jours) — pas fait dans ce chantier. Non bloquant. |

## 2. Modules critiques SANS tests dédiés

`matching.py`, `matching_exigences.py`, `preset.py`, `tendia_extraire.py`,
`analyse.py`, `organisme.py`, `fiche_marche.py`, `tendia_ui.py`,
`tendia_classification.py`, `llm_calibration.py`, `concurrence.py`.

Testés : downloaders (atexo/aws/dematis), `dce_finder`, `http_humain`, proxy,
`qualifier_dce`, `parseur_dce`, et `llm_extract` partiellement (`tests_llm_extract_routage.py`
couvre le routage, pas `extraire_via_llm` complet) + `briefs_versioning`.

Priorité tests : `matching` (cœur décision, 0 test), `preset` (logique de mapping
critique, 0 test), `matching_exigences` (éligibilité).

## 3. Fichiers jetables / scratch oubliés (à trier, NON supprimés)

- **~42 fichiers** `diag_*.py` / `diagnostic_*.py` (diagnostics ad hoc de sprints passés).
- **11 `patch_*.py`** : `patch_aws_cdn_bypass`, `patch_aws_cfid_refresh`,
  `patch_aws_decoder_manuel`, `patch_aws_encoding_chir`, `patch_aws_lots_mono`,
  `patch_aws_unescape(_html)`, `patch_disable_curl_cffi`, `patch_http_humain_proxy`,
  `patch_tendia_dce`, `patch_tendia_telecharger_dce` (scripts one-shot de patch déjà
  appliqués → archivables).
- Scratch divers (vus en working tree) : `_dematis_*.html`, `audit_btp.csv`,
  `echantillon_dce.zip`, `etape2_diag.txt`, `*.bak_*` (gitignorés), doublons de
  passation (`passation_claude_2026-06-14.md`), templates `.bak_*`.
- Suggestion : déplacer diag/patch dans un dossier `scratch/` ou `archive/` (hors
  scope nocturne — ne rien supprimer sans validation).

## 4. Patterns douteux

- **Styles inline massifs** : `ui/templates/marche.html` (~1736 lignes, quasi tout
  inline) → incohérences de padding/taille/couleur, refonte esthétique difficile.
  Centraliser dans des classes (card, stat, label).
- **Gros modules** : `tendia_ui.py` (56 K), `tendia_telecharger_dce.py` (53 K),
  `tendia_extraire.py` (51 K), `llm_calibration.py` (48 K), `matching.py` (47 K).
  Candidats à découpage.
- **Signatures downloaders non uniformes** : `telecharger_dce(...)` diffère par
  plateforme (Dematis a `verify_ssl`, AWS `idm`, Atexo `id_atexo/org_acronyme/url_base`,
  achatpublic `pcslid`). Seul `telecharger_dce_pour_marche(marche, repertoire_dce, …)`
  est homogène. Un registre/dispatch unifié aiderait.
- **Deux notions de « matching »** : `scores_matching` (pré-filtre keyword/CPV/IA, booléen
  `matche`) vs `matching.evaluer` (verdict + score). Nommage prêtant à confusion.
- **Constantes dupliquées** : `analyse.py` définit deux constantes pour la même
  collection `briefs_extraits` ; import `preset` apparemment inutilisé dans `analyse`.
- **Collections vides / features stubbées** : `matchings`, `briefs_calibres`,
  `titulaires`, `marches_notifies`, `marches_tendia_attribues` existent mais ne sont
  pas alimentées (calibration/concurrence partiellement intégrées).

## 5. Suggestions de priorisation

1. **B1** (committer cdn_bypass + réparer le test) — un test rouge masque les régressions.
2. **Tests `matching` + `preset`** — cœur décision, 0 couverture.
3. **B3 / B2** (harmoniser `_meta` et le nommage plateforme/log) — dette transverse cheap.
4. **B5** (validation `meta.code == dossier` au chargement preset) — évite la classe de bug IT.
5. **Refonte CSS fiche marché** (classes vs inline) — préalable à l'amélioration UX.
6. Tri des `diag_*`/`patch_*` dans `archive/` (cosmétique, faible priorité).
