# Passation à Claude — Projet Tendia

**Tu es le prochain Claude qui va aider Younes sur Tendia.**
**Ce document est ton briefing.** Lis-le entièrement avant de répondre à Younes.

**Date de la passation** : 13 juin 2026, fin du Sprint Atexo (téléchargeur DCE profond)
**Version** : 2.4 (post intégration downloader Atexo 2-POST)
**Sprints clôturés** : 2, 2bis (Sujets 1+2, Phases 3a/3b/3c), A (profil socle+BTP), B (matching V2), C-ingénierie, P (UI gestion profils), P bis (création + widgets), UI fiche marché (preset-aware), Téléchargeur DCE (qualif `dce_contenu`), Téléchargeur Profond (scaffolding), Atexo (downloader 2-POST généralisé — réseau à lancer par Younes), Dematis (downloader anonyme captcha validé bout-en-bout sur 3 acheteurs — truststore + cookie PHPSESSID + mojibake), **Chantier 1 (architecture prompts LLM par preset, 1A→1G : routage, champs sectoriels, fix hors-périmètre, versioning, re-extraction)**, **Proxy ciblé par plateforme**, **Passe UI** (Explorer multi-filtres, nettoyage fiche)
**État système** : stable et productif. Verdicts `pertinent`+ end-to-end sur 2 profils démo : BTP IDF (57070/56539/56378) et Ingénierie IDF (56588 `tres_pertinent`, 56774/55964/56096 `pertinent`). Fiche marché et gestion de profils désormais utilisables par un commercial.
**Repo sous git depuis le 12 juin** (init pendant Sprint P) : `data/`, `.env`, sidecars WAL gitignorés. Commit avant chaque sprint, working tree propre.

---

## 1. Qui est Younes

### Profil et style

- Développeur solo, fondateur du projet Tendia
- **Très haute exigence sur la qualité architecturale**. Préfère systématiquement le travail propre à la vitesse. Si tu lui proposes un raccourci, il le refusera et préférera la solution propre. Plusieurs fois pendant le Sprint 2, il a corrigé Claude qui voulait shortcut.
- **Délégation intelligente** : valide explicitement chaque étape. Quand il dit "ok go", c'est qu'il a lu, compris et validé. Tu peux exécuter avec confiance.
- **Validation par retour terrain** : Younes ne valide pas une archi sur la théorie. Il lance, il observe, il décide. Toujours fournir un moyen empirique de tester.
- **Communication directe** : peu de formules, va à l'essentiel. Bonne expression écrite mais brève. Pas de "merci d'avance", pas de "ce serait gentil de". Just business.
- **Bilingue FR/EN** : code et docs en français, mais commentaires techniques OK en anglais. Préfère les noms FR (`preset`, `analyse`, `marche`).

### Patterns techniques observés

- **PowerShell sur Windows** : Younes lance ses commandes en PowerShell. Bug récurrent : les f-strings avec `\"` à l'intérieur cassent. Toujours écrire des scripts Python externes plutôt que des `python -c "..."` longs.
- **Backup avant sprint** : Younes backupe systématiquement `data\tendia.db` avant chaque modification structurelle. Toujours lui suggérer le backup.
- **Test empirique** : Il préfère 1 marché test ciblé avant de lancer un backfill complet. Toujours proposer un test ciblé d'abord.
- **Budget conscient** : Il a un budget LLM modeste. Toujours estimer le coût AVANT d'agir.

### Vision business

- Tendia est un projet **commercialisable**. Younes pense en SaaS multi-tenant.
- Cible : PME secteurs variés (formation, BTP, IT, conseil, ingénierie, EnR)
- Modèle : abonnement mensuel par organisme client
- Concurrence : Vecteur Plus, Dispofi, MyMarchespublics — différenciation par profondeur IA
- Pas encore de client. Phase actuelle : préparation au démarchage.

---

## 2. État du projet au 13 juin 2026 (post UI fiche marché + Téléchargeurs DCE/Profond/Atexo)

### Architecture actuelle

Tendia est un **fork d'Apptia** (mai 2026), généralisé pour servir N secteurs.

**Pipeline complet** :
```
BOAMP → marches (422 actuels)
   ↓
Classification IA (Sprint 2) → classifications_ia (421/422)
   ↓                             ↑
   ↓                          [Sprint 2bis Sujet 1] sync depuis sortie LLM
   ↓
Matching IA strict → scores_matching (275 pertinents / 422)
   ↓
Téléchargement DCE → ~90 marchés briefables (35% de couverture)
   ↓
Brief LLM complet → briefs_extraits (102 actuels)
   |   [Sprint 2bis] : routage classif IA → schéma sectoriel ciblé
   |                   + filtre anti-hallucination post-extraction
   |                   + 3 schémas sectoriels enrichis (IT, conseil, ingénierie)
   ↓
Calibration prix bottom-up → extractions_calibrees
   ↓
Matching organisme × marché V2 (Sprint B)
   |   [Sprint A] : profil socle commun + profils_sectoriels par preset
   |   [Sprint B] : motifs universels + sectoriels BTP (qualibat, RGE,
   |                corps_metier, types_ouvrages, capacité)
   ↓
UI : Dashboard (strict) + Explorer (tri richesse, Sprint UI) + Fiche marché
     (preset-aware, Sprint UI) + Profils (bibliothèque + édition, Sprint P/P bis)

```

### Ce qui marche

- Classification IA Haiku 4.5 : 100% couverture, raffinée par re-classification post-brief (Sprint 2bis Sujet 1)
- 6 presets sectoriels actifs (formation, énergie, BTP, IT, conseil, ingénierie)
- **Routage classif IA → schéma LLM ciblé** (Sprint 2bis) : brief BTP ne reçoit plus de schéma formation parasite
- **Filtre anti-hallucination** (Sprint 2bis Sujet 2) : les blocs sectoriels hors-schéma sont supprimés post-parsing JSON
- **Schémas IT/conseil/ingénierie enrichis** (Phase 3b) : 8→17 (IT), 8→14 (conseil), 9→15 (ingénierie) champs
- **Rendu MD preset-aware** (Phase 3a) : plus de section "Publics cibles : Non applicable" pour un marché BTP
- Architecture mutualisée : marchés/classifications/briefs partagés, profils per-client
- **Profil organisme multi-secteurs** (Sprint A) : socle commun + spécialisations par preset
- **Matching V2 multi-secteurs** (Sprint B) : motifs universels (preset, thématique, géo via dept/région, capacité) + sectoriel BTP (qualibat go/no-go, RGE, corps_metier par tokens, types_ouvrages, capacité chantier)
- **Profil + matching sectoriel ingénierie** (Sprint C) : `presets/ingenierie/_schema.json` (11 propriétés) + profil démo Tridyne + 7 évaluateurs (ing_opqibi go/no-go, ing_decennale/ing_rc_pro conditionnels, ing_typologies, ing_competences seuil 0.8, ing_types_ouvrages, ing_capacite_etudes sur montant travaux). Lit les blocs brief `caracteristiques_mission_moe` + `qualifications_moe`.
- **UI de gestion des profils** (Sprint P + P bis) : bibliothèque KV `profils_bibliotheque` (collection à côté de `organisme/principal` actif), routes `/profil` (liste, détail, édition, activation, duplication, import, création from scratch). Édition par formulaires : checkboxes groupées pour les enums, zones par région (101 dépts), sous-formulaire dynamique de références. Helpers dans `organisme.py`, parsing dans `profil_form.py`, widgets dans `profil_widgets.py`.
- **Fiche marché preset-aware** (Sprint UI) : module `fiche_marche.py` (7 helpers purs testés). KPI cards preset-aware (plus de « Bénéficiaires » sur du BTP), verdict 90 secondes, encart verrous go/no-go, blocs sectoriels BTP/ingénierie/formation rendus en HTML, détail par lot/tranche, badge richesse brief, bouton « Lancer calibration ». Explorer trié par richesse décroissante + filtre `?complet=1`.
- **Qualification du contenu DCE** (Sprint Téléchargeur DCE) : `tendia_dce.qualifier_dce` → champ `dce_contenu` (**6 niveaux** `complet/incomplet/candidature/vide/auth_requise/erreur`), **distinct** de `dce_qualite` (résolution URL, lu comme filtre par enrichir/pipeline/veille — surtout ne pas confondre). Garde-fou dans `enrichir_complet` : pas d'appel LLM sur `vide/auth/erreur`. Backfill `backfill_dce_qualite.py`. UI : badge + bouton « Re-tenter ».
  - **`candidature`** (ajouté 14/06/2026) : la consultation n'expose que le **RC + formulaires DC1/DC2/DC4** (`dce_pieces_contractuelles == ['RC']` ET présence d'un DC), sans CCAP/CCTP. C'est une **phase candidature** (concours/restreint) où le DCE travaux/offre n'est pas encore publié — **pas un défaut de récupération** : à ne pas re-télécharger ni traiter comme `incomplet`. Détection : `_est_dc_candidature()` + règle `a_dc and types == {"RC"}`.
  - **Quick wins classification 14/06/2026** : (1) motifs élargis (`Cahier des charges`→CCTP, suffixe de version collé `CCTPv3`, type `CCP/CCATP`) ; (2) lecture des **ZIP imbriqués (1 niveau)** et **archives .7z/.rar** en mémoire dans `qualifier_dce` (`_noms_dans_zip`, `_noms_7z_rar`) — `.7z` nécessite `py7zr` (ajouté à `requirements.txt`), `.rar` nécessite `rarfile`+`unrar` (optionnel, skip propre sinon). Bilan backfill : complet 184→**195**, +2 `candidature`, 0 régression. Restent ~30 `incomplet` (dont 15 e-marchespublics → Sprint Dematis, 3 `.7z` en attente de `pip install -r requirements.txt`).
- **Téléchargeur profond** (Sprint Téléchargeur Profond — **scaffolding**) : `tendia_telecharger_dce` expose `ParseurDCE`/`telecharger_pieces_dce` (best-effort multi-pièces, ZIP global priorisé), 19 tests hors-ligne OK. Les parties réseau (diagnostic, re-DL, re-extraction) sont **à lancer par Younes** (pas de réseau dans l'env de dev Claude).
- **Downloader Atexo 2-POST** (Sprint Atexo) : `atexo_downloader.py` (dérivé du `place_downloader` Apptia, généralisé) télécharge le **DCE complet** sur les plateformes Atexo MPE/Prado en mode anonyme (GET form → POST anonyme+CGU → POST `completeDownload`), sans captcha. `url_base` détecté par signature (`orgAcronyme=`+`Entreprise.`) → rattrape les forks municipaux. `ParseurAtexo` dans le pipeline. **76 marchés `incomplet` routables** (mesuré hors-ligne). 25 tests hors-ligne OK. **Batch réseau à lancer par Younes.**

### Ce qui ne marche pas (ou pas encore)

- **Pas de profils sectoriels IT/conseil/EnR** (reste de Sprint C — modèles BTP et ingénierie sont OK)
- **Pas d'évaluateurs matching sectoriels** pour conseil/IT/EnR (Sprint C — stubs en place ; BTP et ingénierie faits)
- **`ing_opqibi` ne mord pas sur les briefs actuels** : le LLM remplit `qualifications_moe.opqibi` en texte libre, pas en codes à 4 chiffres → garde-fou neutre (piège 10). Le go/no-go OPQIBI n'agira que si l'extraction des codes est fiabilisée côté `llm_extract.py`.
- **DCE : 0 marché `complet`, 94 `incomplet` (RC seul), 200 `vide`, 128 `auth_requise`** (post backfill `dce_contenu`, AVANT le batch Atexo). FINDING majeur : le téléchargeur récupère le **RC seul ~90% du temps**, jamais le DCE complet (CCAP/CCTP/DPGF) → tous les briefs sont construits sur le RC. **Le Sprint Atexo a livré le downloader 2-POST** : **76 marchés `incomplet` routables Atexo** — `python retelecharger_incomplet.py` (par Younes, réseau) devrait les faire passer `complet`, puis `python reextraire_briefs_complet.py` re-génère les briefs riches. À FAIRE par Younes.
- **e-marchespublics (Dematis)** : moteur distinct d'Atexo. **Sprint Dematis (14/06/2026) — ✅ downloader anonyme VALIDÉ BOUT-EN-BOUT en réel** (calé sur HAR `dematis exemple/hautsdeseine-habitat.e-marchespublics.com.har`, cas `BOAMP-26-57070`).
  - **Workflow HAR strict** : GET annonce → **lien anonyme à token SHA-1 (40 hex)** — la page expose AUSSI un leurre token MD5 (32 hex) qui redirige vers l'accueil, à NE jamais suivre → GET `/dossier_de_consultation_marche_public_anonyme_<token40>` (page captcha, form `inscriptionEntreprise` : `captcha[id]`+`captcha[input]`+`submit`, image `/captcha/<captcha_id>.png`, **leurre `captchaResult` à ne pas soumettre**) → 2captcha → **POST sur la même URL → 302 `Location: /acces_dce_marche_public_anonyme_<token40>`** (un captcha refusé = 200) → GET acces_dce → pièces servies par `private.e-marchespublics.com/dce/getfile.php?id=…&anonyme=<token40>&fromnew` → DL + décompression ZIP imbriqués.
  - **Validé sur 3 acheteurs** : `hautsdeseine-habitat` (17 fichiers), `cmar-occitanie` / CMA Gard (17), `sdis13` (14). Généricité confirmée (sous-domaines + `pack` variables).
  - **2 découvertes NON visibles dans le HAR, corrigées** :
    - **SSL** : sur le poste Windows, `certifi` ne peut pas bâtir la chaîne → échec HTTPS sur *e-marchespublics* **ET** 2captcha.com. Fix racine : **`truststore`** (ajouté à `requirements.txt`, injecté au chargement de `http_client.py`) → magasin de certificats système, `verify=True` partout. (Paramètre `verify_ssl=False` conservé en dernier recours ponctuel.)
    - **Cookie `PHPSESSID` à `Domain=` vide** : la solution du captcha est stockée dans la session PHP ; Dematis pose `PHPSESSID` avec un `Domain=` malformé que `requests`/`cookielib` rejette → POST refusé (« code de vérification incorrect ») même avec la BONNE solution. Fix : `_installer_fix_cookies_domaine_vide` (hook réponse qui ré-injecte le cookie sur le bon hôte).
  - **Mojibake noms de fichiers** : la page acces_dce mêle octets UTF-8 et latin-1 selon les fichiers. Décodage latin-1 sans perte (`_decoder_liste_sans_perte`) + `_normaliser_nom_mojibake` (gère mojibake **simple ET double**, ex. SDIS13) appliqué au libellé ET au `Content-Disposition` de `getfile.php`.
  - **`dematis_downloader.py`** : API `telecharger_dce(url_dce, dossier, ..., verify_ssl=True)` et `telecharger_dce_pour_marche(marche, repertoire_dce, ...)` (idempotent, rotation IP sur ban, logs `logs/dematis_<date>.jsonl`).
  - **`retelecharger_dematis_anti_ban.py`** : batch — cap 30/run, délai gaussien ~60 s, pause cumulative, heures bureau, re-qualifie + persiste `dce_contenu`. **Corrigé** : (1) **vide le dossier après backup `.bak_avant_dematis`** sinon le skip idempotent empêchait le re-DL complet (marchés `incomplet` à 1 fichier RC) ; (2) **écarte les URLs listing `www.e-marchespublics.com/appel-offre/<id>`** (non téléchargeables en anonyme → faux « ban »). Usage : `python retelecharger_dematis_anti_ban.py --max 15 --oui`.
  - **Tests** : `tests_dematis_workflow_har.py` (**44 tests** mockés depuis le HAR : token 40-hex, payload captcha, suivi 302, 17 fichiers, fix cookie, mojibake simple/double, retries, entrée directe) + `tests_dematis_downloader.py` (35 tests, parsers + workflow) — **79 tests verts**.
  - **Dédoublonnage serveur** (14/06/2026) : la page acces_dce liste parfois le MÊME fichier plusieurs fois sous des `id` getfile.php différents (RATP : « Pièces écrites » ×3, « CCTP Dispositions communes » ×6). `_dedupliquer_fichiers` (clé `(nom_normalisé.lower(), taille)`, garde la 1ʳᵉ occurrence) + log JSONL `doublon_detecte`. Test dédié. Au 1ᵉʳ batch (ancien code, dédup inactive) : **18 fichiers / 0,86 Go re-téléchargés inutilement** (~40% de la bande passante proxy) — éliminés dès les prochains runs.
  - **Couverture Dematis — RÉSULTAT batch `--max 15`** : 0 `complet` avant → **12 `complet`** après (12/15 = **80%** de succès ; 92% hors 2 `vide` jamais téléchargeables). 14 sous-domaines acheteurs distincts validés. Échecs : 56517/56591 (« lien anonyme introuvable » = consultations closes), 56691 (incomplet→vide). Reste 2 `incomplet` (au-delà du cap) + 7 `vide` (dont URLs listing `www/appel-offre`, hors-scope anonyme). Volume : 2,16 Go via proxy IPRoyal (RATP 56469 = 1,96 Go / 108 min à lui seul), 6,35 Go sur disque après décompression. Coût : ~0,016 $ 2captcha + bande passante IPRoyal (~3,8–15 $ selon plan, dominé à 91% par le RATP). **Briefs à re-extraire** : `python reextraire_briefs_complet.py`.
- **128 marchés `auth_requise`** (81 marches-publics.info/AWS-Achat + 46 achatpublic + 1 securises) : auth+captcha, non récupérables en auto = cible **Sprint AWS-Achat** (+ 2captcha).
- **Calibration bottom-up faible** : seulement **14/102 briefs calibrés** (~14%), sur disque `data/extractions_calibrees/` (PAS une collection KV — lire via `llm_calibration.charger_si_existe`). 75/102 briefs sans montant estimé. Le pipeline calibration n'a jamais tourné en masse. Le bouton « Lancer calibration » (Sprint UI) permet de le faire à la demande.
- **Calibration top-down** : DECP non exploité aujourd'hui
- **Pas d'authentification multi-tenant** : 1 base = 1 utilisateur
- **5 marchés hors-preset** (assurance, entretien, env) : pas de stratégie ferme — décision à prendre (filtre strict vs preset générique services_supports)
- **Reste du Sprint UI fiche marché** : bouton « Tout déplier » de l'onglet Technique, badge richesse dans le Dashboard, cases à cocher UI du filtre « briefs complets » (marche par URL `?complet=1`), enquête header multi-dépt (56970). Les 12 tests navigateur ne sont pas tous passés (vérif curl + grep).
- **Édition profils conseil/IT/EnR** : ces presets affichent « Sprint D à venir » dans l'éditeur (schémas sectoriels non encore définis).
- **3 marchés avec mismatch DCE/métadonnée** (55964, 56061, 56063 historiques) : le DCE téléchargé ne correspond pas au marché BOAMP — chantier d'investigation séparé
- **Section `tranches` absente des briefs** : ex 56096 (« 12 tranches » annoncées) n'a pas de structure `tranches` exploitable → défaut Phase 3b à corriger côté extraction, pas côté UI.

### Résolu récemment

- ✅ **Bug `enrichir_complet.py --id`** (Sprint UI, commit `ca8a446`) : `--id` court-circuite désormais le filtre pertinent (un marché ciblé non-pertinent est traité). Le symptôme « --force pas honoré » venait de là.

### Chiffres importants à connaître

| Métrique | Valeur |
|---|---:|
| Marchés en base | 422 |
| Classifiés IA | 421 (100%) |
| Pertinents (6 presets) | 275 (65%) |
| Briefs complets | 102 |
| Briefs avec verdict `pertinent`+ (profil BTP démo IDF) | **3** (57070, 56539, 56378) |
| Coût total LLM depuis le début | ~25-30€ (incl. Sprint 2bis Phase 3c ~3€) |
| Coût mensuel régime | ~30€/mois (1 client) |
| Coût marginal par client supplémentaire | ~12€/mois |

---

## 3. Sprints récents

### Sprint 2 — Nouvelle architecture (juin 2026) ✅

- ✅ Module `tendia_classification.py`
- ✅ Taxonomie enrichie à 56 domaines
- ✅ 4 nouveaux presets MVP : BTP, IT, Conseil, Ingénierie
- ✅ Refactor `analyse.py` : matching IA strict + fallback keyword
- ✅ Route `/explorer` + filtres famille/sous-domaine/zone/recherche
- ✅ Mode `--mutualise` et `--prioriser` dans `enrichir_complet.py`
- ✅ Audit prompt `llm_extract.py` neutralisé (vestiges France Travail)

### Sprint 2bis — Anti-pollution multi-secteurs (12 juin 2026) ✅

Diagnostic : un brief BTP recevait tous les schémas sectoriels (formation, énergie, conseil, IT, ingénierie) → le LLM remplissait n'importe quoi, créant 8+ blocs hallucinés par brief.

**Sujet 1 — Sync classif IA depuis sortie LLM**. Après brief, la classif IA initiale (Haiku) est remplacée par celle ré-évaluée par le LLM (Sonnet) qui a lu le DCE complet. Log `🔄 Classif IA mise à jour : [...] → [...]`. Validé in vivo en Phase 3c (6 marchés re-classifiés, dont 2 corrections majeures de faux positifs).

**Sujet 2 — Anti-hallucination** :
- (a) Règle prompt explicite ajoutée en tête de RÈGLES IMPORTANTES dans `llm_extract.py` : "ne génère QUE les blocs présents dans le schéma fourni"
- (b) Filtre post-parsing JSON `_filtrer_hallucinations(data, codes_presets)` dans `llm_extract.py` qui supprime tout bloc top-level non listé dans `_CHAMPS_UNIVERSELS_BRIEF` (12 champs universels) + les blocs sectoriels des presets ciblés. Helper `preset.blocs_sectoriels_pour_presets(codes)`.

**Phase 3a** — `_synthese_brief` (rendu MD) preset-aware : ne génère plus de section "Publics cibles : Non applicable" pour un brief BTP.

**Phase 3b** — schémas IT/conseil/ingénierie enrichis. IT : 8→17 champs (méthodologie, jalons, livrables_par_phase, jours_consultant_par_profil...). Conseil : 8→14. Ingénierie : 9→15 (livrables_par_phase, coordinations, organigramme...).

**Phase 3c** — regen massive : 23 briefs identifiés pollués, 18 effectivement régénérés (5 skippés par bug `enrichir_complet.py`). Coût ~3€. 6 classifs IA mises à jour. Validation in vivo : 3 JSON audités → 0 pollution détectée.

### Sprint A — Profil organisme socle + BTP (12 juin 2026) ✅

Le profil organisme était formation-only. Refactor multi-secteurs validé par Younes : socle commun + spécialisations par preset (option C).

- `presets/_socle_profil_organisme.json` : 12 propriétés universelles (identite, presets_couverts, profils_sectoriels, zones_intervention, mots_cles_catalogue, capacite_globale, certifications, references_globales, valeurs_engagements, contraintes, _meta)
- `presets/btp/_schema.json` : 9 propriétés BTP (qualifications, corps_de_metier, types_ouvrages, capacite_chantiers, rh_chantier, moyens_materiels, references_chantiers, types_clients_publics, pratiques_specifiques)
- `organisme.py` refait (~460 lignes) : `charger_actif`, `profil_sectoriel(code)`, `schema_socle/sectoriel`, `template_socle/sectoriel`, `valider_profil` (validation maison, sans jsonschema), `supprimer_profil`. Backward compat legacy formation (`lire_profil`, `schema_vide`, `champs_remplis`, `est_format_legacy`, `DR_FRANCE_TRAVAIL`, `PRESTATIONS_FRANCE_TRAVAIL`)
- `init_profil.py` refait (~175 lignes) : `--status`, `--template <preset>`, `--depuis <fichier>`, `--purger --confirmer`, `--force`
- `data/exemples/profil_btp_demo.json` : profil démo "EXEMPLE BTP SAS" 75 ETP, 14.5M€ CA, IDF+HDF, 7 codes Qualibat, RGE, MASE, amiante SS4, ISO 9001+14001, 10 corps de métier, 5 types d'ouvrages, 4 références chiffrées

### Sprint B — Matching V2 multi-secteurs (12 juin 2026) ✅

- `matching.py` V2.1 (~770 lignes) avec routage automatique legacy vs multi-secteurs
- 4 motifs universels : `preset_compatibilite` (-50/-30/+20), `thematique` (mots-clés catalogue +25/+15), `geographie` (+25 dept direct, +15/+12 region via DEPARTEMENT_VERS_REGION 101 codes), `capacite` financière (+10/-10/-20)
- 6 évaluateurs sectoriels BTP : `btp_qualibat` (verrou -50 robuste aux strings texte libre), `btp_rge`, `btp_amiante`, `btp_corps_metier` (match par tokens), `btp_types_ouvrages` (match par tokens), `btp_capacite_chantier`
- Stubs Sprint C pour ingenierie/conseil/it/EnR
- Synergie +10 si preset+thematique+geo alignés
- Signature backward-compat : `evaluer(organisme, marche, brief=None, presets_marche=None)`
- 4 appelants patchés pour passer brief : `tendia_matcher.py:247`, `tendia_veille.py:156`, `tendia_ui.py:283`, `tendia_dce.py:163`
- `tester_matching.py` (script démo `--top N` et `--details <id>`)
- 3 fixes critiques post V2 : (1) btp_qualibat ne crash plus sur string libre ("Non précisé dans le RC..."), (2) ACHETEUR_VERS_DEPARTEMENT étendu aux 13 organismes nationaux IDF (OFPRA, CNAM, ministères...), (3) match `corps_metier`/`types_ouvrages` par tokens partagés au lieu de substring

**Résultat in vivo** : sur 422 marchés et profil BTP démo IDF :
- 1 `tres_pertinent` (57070 Rénovation ECS Champs Philippe 92, score 75)
- 2 `pertinent` (56539 CPAM Tours score 70, 56378 OFPRA Paris score 55)
- 35 `a_verifier` (8.3%)
- 384 `non_pertinent` (91%)

C'est le **premier passage `pertinent` end-to-end** sur la base réelle de Younes.

### Sprint C — Ingénierie (12 juin 2026) ✅

Reproduction du modèle BTP (Sprint A+B) pour le preset `ingenierie`, sans toucher BTP, le matching universel ni le socle.

- `presets/ingenierie/_schema.json` : 11 propriétés (qualifications OPQIBI, assurances décennale/RC, typologies_couvertes, competences_specialisees, types_ouvrages_etudies, types_clients_publics, capacite_etudes, rh_etudes, outils_logiciels, references_etudes, pratiques_specifiques). `required` : `qualifications` + `typologies_couvertes`.
- `data/exemples/profil_ingenierie_demo.json` : "Tridyne Ingénierie SAS", BET pluridisciplinaire 52 ETP IDF, valide 100% socle / 99% sectoriel.
- `matching.py` : 7 évaluateurs (`_eval_ing_*`) insérés en section dédiée après `_eval_sectoriel_btp`. Distinction études/MOE vs travaux : lit `caracteristiques_mission_moe` (typologie, typologie_ouvrage, montant_travaux_estime, organigramme_attendu) et `qualifications_moe` (opqibi). `ing_competences` à seuil 0.8 (un BET couvre rarement 100% des disciplines). Dispatcher `elif code == "ingenierie"` + verdict étendu (`ing_opqibi` -50 → `non_pertinent`).
- **Résultat in vivo** (profil Tridyne, 422 marchés) : 1 `tres_pertinent` (56588 Lycée Guer MOE, 75), 3 `pertinent` (56774 AMO rectorat Versailles 57, 55964 MOE route 50, 56096 pont de Pierre 50). Non-régression BTP : 57070/56539/56378 inchangés. 0€ LLM.

### Sprint P — UI gestion des profils (12 juin 2026) ✅

Avant : 1 seul profil actif, écrasement via `init_profil.py --purger`. Maintenant : bibliothèque multi-profils.

- Collection KV `profils_bibliotheque` (N profils) à côté de `organisme/principal` (actif). **Invariant lien actif** : `organisme/principal.id` = slug de l'entrée bibliothèque (sinon `est_actif` ne matche pas — `ecrire_profil` force `id="principal"` côté CLI, donc les écritures UI passent en direct par `stockage.ecrire`).
- Helpers `organisme.py` : `lister_profils_{bibliotheque,exemples}`, `activer_profil`, `enregistrer_profil_bibliotheque`, `importer_profil_json`, `dupliquer_profil`, `migrer_bibliotheque_au_demarrage` (idempotent, lancée au démarrage Flask), `_slugify`.
- Routes `/profil` (liste), `/profil/<source>/<id>` (détail), `/profil/bibliotheque/<id>/edit`, `/activer`, `/dupliquer`, `/importer`. Templates sous `ui/templates/profil/`.
- Parsing formulaire→profil par **merge sur l'existant** (zéro perte) dans `profil_form.py`, testable hors Flask.
- **Pas de création from scratch ni suppression depuis l'UI** au Sprint P (CLI only, anti-destruction).

### Sprint P bis — Création + widgets formulaire (12 juin 2026) ✅

- **Création from scratch** : `/profil/nouveau` (2 étapes). `organisme.creer_profil_bibliotheque` valide le **socle seulement** (le sectoriel est vide à la création, complété en édition — sinon les arrays requis vides bloqueraient).
- **Widgets** (`profil_widgets.py` + `ui/templates/profil/_macros.html`) : checkboxes groupées par famille pour les enums (corps_de_metier, typologies, compétences…) avec groupe défensif « Autres » ; zones d'intervention = 101 départements groupés par 18 régions (source `matching.DEPARTEMENT_VERS_REGION`) ; sous-formulaire dynamique de références (add/remove JS, parsing `references_xxx[N].champ`, index tolérant aux trous).
- Suppression du vestige `ui/templates/profil.html` (formation Apptia).

### Sprint UI fiche marché — preset-aware (12-13 juin 2026) ✅ (partiel)

Module **`fiche_marche.py`** : 7 helpers purs testés (résolution presets via poids `domaines_metier`, KPI cards, verdict 90s, verrous, blocs sectoriels, lots/tranches, richesse brief). Wiring dans `tendia_ui.py` route `/marche` + refonte `marche.html`.

- Livré : KPI preset-aware (fin résidu « Bénéficiaires »), verdict 90s, encart verrous, blocs sectoriels HTML, détail lots/tranches, badge richesse (fiche + Explorer), tri Explorer richesse-desc + filtre `?complet=1`, route `/marche/<id>/calibrer` + bouton, « Vigilance · N alertes ».
- **Reste** (voir « Ce qui ne marche pas ») : bouton « Tout déplier » technique, badge Dashboard, passe complète des 12 tests navigateur.

### Sprint Téléchargeur DCE — qualification du contenu (13 juin 2026) ✅

Diagnostic : 234 dossiers DCE « marqués traités » étaient en réalité **vides** ; le téléchargeur masquait les échecs en faux succès.

- `tendia_dce.qualifier_dce(dossier, log)` → 5 niveaux dans **`dce_contenu`** (≠ `dce_qualite` URL). Détecte pièces contractuelles (RC/CCAP/CCTP/DPGF…), pages de login (auth), mojibake des noms de fichiers. `PLATEFORMES_AUTH_REQUISES`, `url_est_auth_requise`.
- `backfill_dce_qualite.py` (+ `--relancer`), `tests_qualifier_dce.py` (10/10).
- Garde-fou `enrichir_complet` : extraction LLM sautée si `vide/auth/erreur` (RC seul=`incomplet` reste briefable).
- UI fiche : badge `dce_contenu` + bouton « Re-tenter ».
- Résultat backfill : 0 complet, 94 incomplet, 200 vide, 128 auth_requise. **70 marchés « marqués DCE » étaient vides.**

### Sprint Téléchargeur Profond — récupération multi-pièces (13 juin 2026) ✅ (scaffolding)

But : récupérer **toutes** les pièces du DCE (pas juste le RC) sur les plateformes anonymes. **Pas de réseau dans l'env Claude** → livré en scaffolding testé hors-ligne ; Younes lance les parties réseau.

- `tendia_telecharger_dce` : `ParseurDCE`/`ParseurGenerique` + 6 parseurs plateformes (PLACE, e-marchespublics, ternum-bfc, demat-ampa, megalis, maximilien), `trouver_parseur`, `_pieces_depuis_html` (pur), `_telecharger_avec_retry`, `telecharger_pieces_dce` (best-effort, ZIP global priorisé). `tests_parseur_dce.py` (19/19, HTML mocké + fake session).
- Scripts à lancer par Younes (réseau/LLM) : `diagnostic_plateformes_dce.py` (Livrable 0, à faire EN PREMIER) → `retelecharger_incomplet.py` (re-DL des 94) → `reextraire_briefs_complet.py` (re-brief, ~3-10€).
- UI : pièces manquantes + bouton « Re-tenter ces pièces ».
- **Caveats** : `_telecharger_marche` historique NON rewiré (chemin réseau qui marche) ; les parseurs spécifiques utilisent la stratégie générique en attendant le diagnostic (PLACE peut exposer en JS/POST que `href` seul ne capte pas).

### Sprint Atexo — downloader DCE 2-POST (13 juin 2026) ✅ (scaffolding)

Le diagnostic du sprint précédent montrait que les 6 plateformes anonymes exposent leurs pièces derrière un workflow formulaire (pas de `href`). Apptia avait déjà résolu PLACE → réutilisé et généralisé.

- `atexo_downloader.py` : dérivé de `place_downloader_apptia.py`. Workflow 2-POST Prado/Atexo (GET formulaire identité → POST anonyme+CGU → POST `PRADO_POSTBACK_TARGET=completeDownload`), vérif magic bytes `PK`. **`url_base` dynamique** via `_detecter_url_base` : host connu OU **signature Atexo** (`orgAcronyme=` + `Entreprise.`) → rattrape les forks municipaux (rhone, meuse, nantesmetropole, departement13…) ; exclut e-marchespublics + plateformes auth. Helpers Apptia intacts (`_extraire_inputs_form`, `_trouver_event_target`, `_extraire_id_org_depuis_url`).
- `tendia_telecharger_dce` : `ParseurAtexo` (délègue via marqueur `ZIP_GLOBAL_ATEXO`) **remplace** les 5 parseurs individuels (PLACE/ternum/demat/megalis/maximilien supprimés) ; `telecharger_pieces_dce` gère la branche Atexo (DL direct du zip dans `data/dce/<id>/`). `ParseurEMarchesPublics` conservé (Dematis, à diagnostiquer).
- `tests_atexo_downloader.py` (25 OK) + `tests_parseur_dce.py` (21 OK, branche Atexo mockée).
- `diagnostic_emarches.py` : à lancer par Younes pour trancher le cas Dematis.
- **Portée mesurée hors-ligne : 76 marchés `incomplet` routent vers Atexo.** Batch réseau + re-extraction à lancer par Younes.

### Sprint AWS-Achat — downloader anonyme ColdFusion + 2captcha (13 juin 2026) ✅

Les 81 marchés `www.marches-publics.info` (AWS-Achat / AW Solutions) étaient classés `auth_requise`. Investigation HAR → workflow anonyme conforme arrêté 14/12/2009, exposé derrière une page captcha custom (OCR ~6 chars).

- `aws_downloader.py` : workflow ColdFusion 7 étapes — GET `dematEnt.choixDCE` (session CFID/CFTOKEN, **pas de cookies HTTP** : tokens en query string), GET `dce.avertissement` (parse `strNomImage`+`hashVal`), GET image captcha, résolution **2captcha** (`TwoCaptcha.normal`, retry 3× si refusé), POST `dce.cnxAnonyme` (302=accepté / 200=refusé via `allow_redirects=False`), GET `dce.verifLotsDCE` (parse checkboxes lots), POST `dce.actDCE2` (tous les lots), parse URL CDN `downloads.awsolutions.fr` (filtre « Conditions d'accès », convertit AAPC relatif), DL multi-fichiers + décompression (réutilise `achatpublic_downloader._decompresser_zip_imbrique`). Gère `ERROR_ZERO_BALANCE`, marché clos (404), fallback mono-lot. Clé via `.env`/`TWOCAPTCHA_API_KEY` (`python-dotenv`).
- `tendia_telecharger_dce` : `ParseurAWS` (marqueur `ZIP_GLOBAL_AWS`) + branche dédiée dans `telecharger_pieces_dce`. `PARSEURS = [Atexo, Achatpublic, AWS, EMarchesPublics]`.
- `tendia_dce` : `www.marches-publics.info` retiré de `PLATEFORMES_AUTH_REQUISES` (reste `{marches-securises.fr}`).
- `tests_aws_downloader.py` (36 OK : helpers purs + workflow complet mocké + cas captcha refusé). Non-régression Atexo (25) / parseur (22) / qualifier (10) OK.
- Scripts : `test_aws_achat.py` (1 marché), `retelecharger_aws_achat.py` (batch 81, backup `.bak_avant_aws_achat`, rate-limit 3 s, arrêt propre si solde épuisé).
- **Livrable 7** : `reextraire_briefs_complet.py` refondu — n'appelle plus `enrichir_complet.enrichir(force=True)` (qui re-téléchargeait via le générique, voué à l'échec sur plateformes à downloader dédié). Désormais : scan `data/dce/<id>/` existant → `tendia_extraire.traiter_marche` (LLM seul, **sans re-DL**) ; skip propre si dossier absent/vide ; flag `genere_avec_dce_complet`. **106 marchés `complet` sans brief à jour** identifiés (tous avec dossier présent).
- **Bonus hygiène** : 51 scripts patchés `sys.stdout = io.TextIOWrapper(...)` → `sys.stdout.reconfigure(...)` (évite « I/O operation on closed file » en cascade d'imports).
- **À lancer par Younes** : `test_aws_achat.py` (1 marché, ~0,001 €) → si OK, `retelecharger_aws_achat.py --oui` (~5 € 2captcha) → `reextraire_briefs_complet.py` (~5 € LLM).

---

### Sprint Anti-Ban v1 — comportement humain pour les downloaders (13 juin 2026) ✅

Le batch test AWS-Achat a déclenché un **ban IP** (~10-15 sessions ColdFusion enchaînées en 1h, rythme fixe 3 s, UA unique → pattern bot). Objectif : rendre le trafic indistinguable d'un usage humain, sans proxy ni headless (gratuit).

- `http_humain.py` (nouveau, stdlib pure) : `creer_session_humaine()` (UA tournant parmi 7 Chrome/FF/Edge/Safari + headers Sec-Fetch réalistes), `attendre_humain(min,max,mu,sigma)` (délai gaussien borné), `attendre_inter_etapes()` (1.5-4 s entre étapes d'un workflow), `attendre_pause_cumulative()` (pause 15-30 min tous les N marchés), `heure_actuelle_est_bureau()` (8h-19h lun-ven), `jitter()`, `ressemble_a_page_ban()` (détection page d'accueil Bootstrap/acheteurs.htm servie au lieu de la page applicative). `tests_http_humain.py` : 27 OK (time/random/datetime mockés).
- **3 downloaders** (`atexo`, `achatpublic`, `aws`) : `requests.Session()` → `http_humain.creer_session_humaine()` + `attendre_inter_etapes()` entre étapes (aws : 3-6 s avant captcha, 2-4 s avant lots, 4-8 s avant actDCE2). Constantes `USER_AGENT` **conservées** (compat `diagnostic_actdce2.py`/`diagnostic_etape5.py` qui lisent `aws_downloader.USER_AGENT`) mais pointent vers le pool. **Détection ban** dans aws : `etape_erreur="ban_detecte"` si page d'accueil au lieu de la page captcha (étapes 1 et 2).
- **Batch** : `retelecharger_aws_achat_anti_ban.py` (nouveau) — délai gaussien 75±30 s, pause cumulative /20, cap `--max 30`/run, garde-fou heures de bureau (`--ignorer-heures` pour tester), **arrêt après 3 bans consécutifs**. Ancien `retelecharger_aws_achat.py` conservé. `retelecharger_achatpublic.py` (~15 s) et `retelecharger_incomplet.py` (~10 s) passés en rate-limit randomisé (pas de ban observé sur ces plateformes).
- `docs/cron_windows.md` : programmation Task Scheduler (3 matinées lun-mar-mer, script idempotent → 30×3 ≥ 81 marchés AWS).
- **Tests** : http_humain 27 OK, aws_downloader 38 OK (+ test ban_detecte), non-régression atexo 25 / parseur 22 / qualifier 10.
- **À lancer par Younes** : d'abord vérifier que le ban est levé (Phase A), puis `test_aws_achat.py` (1 marché), puis mini-batch `--max 5 --oui`, puis cron 30/jour. Si bans persistent → Sprint Anti-Ban v2 (curl_cffi / proxy résidentiel).

---

### Sprint Industrialisation v2 — downloaders production-ready (13 juin 2026) ✅

Anti-Ban v1 (comportement humain) avait des limites en réel : IP partagée polluée, fingerprint TLS `requests` détectable, pas de rotation IP sur ban. Younes a souscrit Bright Data ISP Pay-per-GB ($8/GB, ~10000 IPs FR rotatives). Ce sprint exploite l'infra et rend la stack autonome en cron.

- `http_client.py` (nouveau) : wrapper backend — `curl_cffi` (TLS fingerprint **Chrome 131**) si dispo, **fallback `requests`** sinon (warning, jamais de crash). Expose `Session/get/post` + exceptions `RequestException/Timeout/ConnectionError` unifiées. curl_cffi 0.13.0 installé chez Younes → `BACKEND=curl_cffi`.
- `http_humain.py` : migré vers `http_client.Session()`. **Session-id Bright Data** : `creer_session_humaine(session_id=...)` injecte `-session-<id>` dans le username proxy (`_injecter_session_id`) → 1 IP par session-id. `_nettoyer_session_id` (retire les tirets, sinon casse le découpage username). Sans session-id sur BRD → UUID (nouvelle IP/appel). Proxy non-BRD : utilisé tel quel. (Le `proxy_url`/`TENDIA_PROXY_URL` avait été ajouté par Younes avant le sprint.)
- **3 downloaders** : `import requests` → `import http_client as http_lib` (sessions déjà via http_humain). `session_id` passé (= id marché → IP stable/marché). aws : **rotation IP auto sur ban** dans `telecharger_dce_pour_marche` (jusqu'à `max_retries_ban=3` UUID, sinon `etape_erreur=ban_persistant`) ; **`_request_avec_retry`** (backoff 1/2/4 s sur Timeout/ConnectionError) sur les 7 étapes ; logs `tendia_logs`. atexo/achatpublic : session_id + logs.
- `tendia_logs.py` (nouveau) : logs JSONL `logs/<downloader>_<date>.jsonl` (jamais bloquant), + `lire_evenements()`. `logs/` gitignoré.
- `tendia_monitoring.py` (nouveau) : dashboard console — couverture DCE, derniers batchs, coûts du mois (bande × $8/GB + captchas), marchés en échec. Lit base + logs.
- `retelecharger_aws_achat_anti_ban.py` : estimation coût du run (bande passante + captchas) ; détecte `ban_persistant` (le wrapper a déjà tourné l'IP en interne).
- `docs/production.md` (nouveau) : archi, .env, cron, monitoring, troubleshooting, coûts (~$10-20/mois). `tests_http_humain` 37 OK (+session-id), `tests_aws_downloader` 43 OK (+rotation IP/ban persistant), non-régression atexo 25 / parseur 22 / qualifier 10.
- **À lancer par Younes** : `pip install curl_cffi`, vérifier `BACKEND`, puis `test_aws_achat.py`, mini-batch `--max 5 --oui --ignorer-heures`, batch complet, `tendia_monitoring.py`.

---

### Chantier 1 — architecture prompts LLM par preset (15 juin 2026) ✅

Objectif : améliorer la qualité des briefs (éliminer la pollution sectorielle,
enrichir les champs sectoriels). **Approche : enrichir l'existant, pas refondre** —
l'archi prompts-par-preset existait déjà (`presets/<code>/_preset.json.prompt_extraction`,
routage dans `llm_extract`). Doc complète : `docs/architecture.md`, `docs/pipeline.md`,
`docs/modules/`.

- **1A** — harmonisation des 6 `_preset.json` (vocabulaire_llm, exemples_synthese,
  regles_specifiques). `audit_presets_extraction.py/.md`.
- **1B** — champs structurés sectoriels + `few_shot_examples` (1/preset) : qualibat
  liste/MASE/ISO (btp), iso_27001/hds/typologie_systeme (it), création des blocs
  `qualifications_formation/enr/conseil`, renommage EnR `…_chantier`→`…_enr` (collision
  BTP supprimée). `proposition_champs_structures_1b.md`.
- **1C** — resserrement mapping : `moe_architecte_urbanisme` retiré de btp+conseil
  (→ ingénierie seul) ; typo `energia_amo_etudes`→`energie_amo_etudes` corrigée.
  `impact_resserrement_mapping.md`.
- **1D** (clé) — **fix fallback hors-périmètre** : `codes_presets=[]` n'injecte plus
  l'union complète des blocs (pollution ~50% des marchés) mais un schéma neutre ;
  `blocs_sectoriels_pour_presets([])→[]` (le filtre strippe tout en hors-périmètre) ;
  `few_shot_examples` câblés. `tests_llm_extract_routage.py` (28 tests).
- **1E** — versioning prompts SHA-256 (`preset.hash_preset`, `_meta.prompts_versions`),
  `_meta` harmonisé (`date_generation` canonique + `extraction_le` alias),
  `briefs_versioning.lister_briefs_obsoletes` (+ tests).
- **1F** — validation 10 marchés (réel) : **blocs hors-sujet 67→0**, 0 incohérence
  titre↔synthèse, hors-périmètre = bloc neutre, gros DCE non tronqués. **Fix truststore
  injecté dans `llm_extract.py`** (sinon `Connection error` sur api.anthropic.com).
  `audit_validation_chantier1.md`. Coût réel ~0,42 €/marché (gros DCE).
- **1G** — re-extraction full priorisée (plafond 30 €, 1/preset garanti, gisement
  décroissant, géants >500 Mo écartés). `relancer_extraction_chantier1.py`.
  **Résultat : 68 marchés, 27,61 €.** Couverture déséquilibrée (BTP=52, IT=0 — les
  DCE IT avaient été complétés *après* ce run). Comparatif :
  `comparaison_avant_apres_chantier1.md`. **Commit `49dffcf`.**
- **1G+** — complément IT ciblé (ajout `--preset it` au script, plafond 6 €).
  **Résultat : 7/8 marchés, 2,55 €, 24 min.** 1 échec : `BOAMP-26-56097` (gros DCE
  SSI ~13 Mo ; l'appel LLM aboutit en ~9 min mais le parse JSON échoue 2× → à
  reprendre). **Enseignement** : le DCE complet **re-qualifie** le gisement IT
  (56642→ingénierie, 56164/56170/56547/57263→hors-périmètre) → IT « réel » = 4. La
  re-extraction full DCE améliore donc la *précision de classification*, pas que le
  remplissage des champs. Inclus dans le **commit `49dffcf`**.
  - ⚠️ **Note timeout SDK Anthropic** : sans `timeout` explicite, le client SDK a un
    timeout par défaut ~600 s ; sur un stall transitoire d'un gros DCE, l'appel peut
    bloquer ~10 min (×retry) avant d'échouer. Observé sur 56097 (2 hangs ~9 min).
    Connectivité validée par ailleurs (appel haiku = 0,9 s) → ce n'est PAS une panne
    API mais la latence de génération d'un gros brief. Piste : passer la génération
    des gros DCE en **streaming** (ou borner via `Anthropic(timeout=...)`). Non
    appliqué (décision Younes : laisser le comportement par défaut pour l'instant).

⚠️ **Pré-requis routage** : `extraire_via_llm` lit `contexte["id"]` →
`_resoudre_presets_pour_marche` → presets ciblés. Sans `id`, fallback neutre.

### Mini-sprint Proxy ciblé par plateforme (15 juin 2026) ✅

Proxy IPRoyal **ON par défaut**, **désactivable par plateforme** via
`TENDIA_PROXY_FOR_<P>=0`. `creer_session_humaine(plateforme=…)` +
`_proxy_pour_plateforme`. Désactivés (sans ban) : `place` (marches-publics.gouv.fr),
`boamp`, `data_gouv`. Atexo décide `place`/`atexo` selon l'URL. BOAMP/TED passent déjà
par `http_utils` (sans proxy). `audit_proxy_par_plateforme.md`, `tests_proxy_par_plateforme.py`.
**Commit `eecb941`** (inclut le bypass CDN AWS `_session_sans_proxy` — cf dette : impacte
`tests_aws_downloader`).

### Passe UI (15 juin 2026) ✅ (partielle)

- Polices dé-technicalisées (suppression JetBrains Mono → système + tabular-nums).
- Explorer : tags verdict/score/éligibilité par carte + filtre **multi-sélection**
  Pertinence/Éligibilité/Score + filtre Brief.
- Fiche marché : artefacts techniques retirés (commandes CLI, `raison_classification`,
  « Domaine LLM », enums bruts, jargon DECP) ; tag « À vérifier », section
  « Vérifiez votre éligibilité » (ex-Vigilance, rouge→ambre).
- Reste à faire : refonte esthétique profonde de la fiche (à itérer avec l'œil de Younes).

### ⚠️ Bugs latents découverts (cf `dette_technique.md`)

- **IT preset** : `presets/it/_preset.json` contenait par erreur le contenu ingénierie
  (corrigé `8d57803`) — pas de validation `meta.code == dossier`.
- **truststore** : indispensable au SSL sur ce poste (anthropic, e-marchespublics,
  2captcha). Injecté dans `http_client.py` ET `llm_extract.py`.
- **cdn_bypass** : patch dans `aws_downloader.py` (`_session_sans_proxy`), **commité
  `eecb941`** ; casse `tests_aws_downloader` (crée une vraie session, contourne le
  mock) → à corriger (mocker `_session_sans_proxy` ou injecter la session).
- Mismatch `aws-achat` (log) vs `aws_achat` (proxy) ; schéma `_meta` light vs complet.

---

## 3bis. Sprint en cours / Prochain sprint

**Aucun sprint actif au moment de cette passation.** Le système est dans un état stable et productif. Plusieurs chantiers possibles selon les priorités :

### Lancer le batch Atexo (réseau, par Younes) — PRIORITAIRE

Le downloader Atexo est livré et testé hors-ligne (76 marchés `incomplet` routables). Pour le rendre effectif :
1. **Test 1 marché par plateforme** AVANT le batch (PLACE, ternum-bfc, megalis, demat-ampa, maximilien) : `python -c "import stockage,atexo_downloader as A; m=[x for x in stockage.charger('marches').values() if 'marches-publics.gouv.fr' in (x.get('url_dce') or '') and x.get('dce_contenu')=='incomplet'][0]; print(A.telecharger_dce_pour_marche(m,'data/dce'))"` → doit renvoyer `ok:True` + zip multi-pièces. Si un test échoue, débugger la plateforme avant le batch.
2. `python retelecharger_incomplet.py` (re-DL des 76+ via `telecharger_pieces_dce` qui route déjà vers Atexo, ~20-30 min)
3. `python reextraire_briefs_complet.py` (re-brief des marchés passés à complet, ~3-10€) — valider d'abord sur 1 marché (`--limite 1`) que le brief s'enrichit vraiment.
4. **e-marchespublics (15 marchés)** : `python diagnostic_emarches.py` → si Cas A/B, écrire `dematis_downloader.py` (contrat identique à atexo) + `ParseurEMarchesPublics` renvoyant `ZIP_GLOBAL_DEMATIS` ; si Cas C, ajouter `e-marchespublics.com` à `PLATEFORMES_AUTH_REQUISES`.
5. Optionnel : rewirer `_telecharger_marche` → `telecharger_pieces_dce` une fois validé.

### Sprint AWS-Achat — débloquer les 128 `auth_requise`

`www.marches-publics.info` (81) + achatpublic.com (46) + marches-securises.fr (1). Auth + captcha → 2captcha ou login programmatique. ~30% du volume DCE est là.

### Sprint C — Étendre à conseil, IT, EnR (~3-4h par preset)

**Ingénierie : fait** (voir Sprint C ci-dessus). Reste à reproduire le modèle pour conseil, IT, EnR :
- Créer `presets/<code>/_schema.json` (profil sectoriel)
- Implémenter `_eval_sectoriel_<code>(profil_sec, brief)` dans `matching.py` (section dédiée après les évaluateurs ingénierie), brancher le dispatcher (`elif code == "<code>"`) et, si go/no-go, étendre le tuple de `_calculer_verdict`
- Créer `data/exemples/profil_<code>_demo.json`
- Le pattern est tracé par BTP **et ingénierie**, copier-coller-adapter. Lire le bloc brief sectoriel du preset dans `presets/<code>/_preset.json` → `prompt_extraction.bloc_schema_specifique` pour connaître les vrais noms de champs.

Priorité Younes : conseil > IT > EnR (selon plan commercial).

### Roadmap actualisée (15 juin 2026)

- **DECP / data.gouv.fr** : exploiter les Données Essentielles de la Commande
  Publique pour la calibration des montants et l'analyse concurrentielle
  (attributaires historiques). Flag `TENDIA_PROXY_FOR_DATA_GOUV=0` déjà posé.
  Exploration préliminaire : `exploration_decp_preliminaire.md` (si produite).
- **Hébergement / multi-tenant** : aujourd'hui mono-utilisateur (1 base SQLite,
  1 profil actif). Préparer l'isolation par client avant la bêta.
- **Bêta** : préparation au démarchage (qualité des briefs = Chantier 1 ; UI à
  finaliser esthétiquement ; couverture DCE à augmenter via les batchs downloaders).
- **Documentation** : `docs/` désormais complet (architecture, pipeline, data_model,
  modules, operations, cost, extending, conventions, troubleshooting, cli_scripts) +
  `dette_technique.md`.

### Chantiers non-prioritaires mais reportés

- **Finir le Sprint UI fiche marché** : bouton « Tout déplier » onglet Technique, badge richesse dans le Dashboard, cases à cocher du filtre « briefs complets », enquête header multi-dépt (56970), passe des 12 tests navigateur.
- **Fiabiliser l'extraction des codes OPQIBI/Qualibat** côté `llm_extract.py` (codes à 4 chiffres structurés) pour que les verrous go/no-go mordent vraiment.
- **Bug DCE/métadonnée mismatch** sur 3 marchés historiques (55964, 56061, 56063) : DCE téléchargé ne correspond pas au marché BOAMP. Investigation séparée.
- **Section `tranches`** non extraite par le brief (Phase 3b) — bloque le rendu « Détail par tranche » sur les marchés à tranches (ex 56096).
- **Décision 5 hors-preset** : 5 marchés (assurance, entretien, environnement) sortent de la taxonomie. 3 options : (a1) filtre strict skip ; (a2) preset générique `services_supports` ; (a3) status quo. À trancher.
- **Rectorats par académie** : ajouter `rectorat de Paris → 75`, `rectorat de Versailles → 78`, etc. dans `ACHETEUR_VERS_DEPARTEMENT` (matching.py). Ferait passer 56774 (AMO rectorat IDF, score 47) à `pertinent`.
- **Affiner profil BTP démo** par Younes avec ses vraies données prospect.
- **Calibration top-down DECP** (Chantier C-V1 d'origine) — reporté.

Voir `docs/cadrage_strategique.md` pour la roadmap complète.

---

## 4. Conventions de Younes — RESPECTE-LES

### Code

- **Pas de hardcoding sectoriel en Python.** Tout passe par `_preset.json`. Younes a expressément rejeté les approches type "if marche.cpv.startswith('80'):  # formation" — c'est une heritage Apptia qu'on a éliminé.
- **Backward compatibility** : les nouveaux schémas JSON doivent supporter les anciens en lecture (fallback null/empty).
- **Idempotence partout** : toute commande doit pouvoir être relancée sans risque.
- **CLI avec garde-fous** : toujours `--dry-run`, `--limite`, `--max-cout`, `--force`.
- **Coût LLM tracé** : chaque appel LLM stocke `_meta.cout_eur` pour traçabilité.

### Communication

- **Brièveté** : Younes va à l'essentiel. Sois aussi bref que possible sans perdre en clarté.
- **Pas de blah-blah marketing** ("Excellente décision !", "C'est une approche brillante !"). Direct.
- **Présenter les choix** en clair avec ton vote argumenté. Younes valide rapidement.
- **Estimer toujours** : coût, durée, effort, impact. Donne des chiffres.
- **Tester avant industrialiser** : propose 1 cas test, puis le batch. Pas l'inverse.

### Fichiers

- Suffixe `_preset.json` pour les configs presets (PAS `_domaine.json` — vestige Apptia)
- Préfixe `tendia_` pour les modules principaux (`tendia_sourcing.py`, `tendia_classification.py`, etc.)
- Dossiers presets : nom du preset SANS préfixe (`presets/btp/`, pas `presets/preset_btp/`)
- Tous les scripts ont une docstring d'usage en tête

### LLM

- **Haiku 4.5** (`claude-haiku-4-5`) pour classification et tâches simples
- **Sonnet 4.6** (`claude-sonnet-4-6`) pour briefs et calibrations
- Toujours mentionner le modèle utilisé dans `_meta.modele`

---

## 5. Pièges à éviter

### Piège 1 — PowerShell et f-strings Python

```powershell
# BUG : PowerShell mange les \" à l'intérieur de Python
python -c "print(f'{val:\"format\"}')"
```

**Solution** : pour toute logique Python complexe, créer un fichier `.py` externe que Younes lance avec `python script.py`. Pas de `python -c "long stuff"`.

### Piège 2 — Le profil n'est pas chargé en mode multi-client

Le module `organisme.py` lit `data/profil_organisme.json` par défaut. Avec `tester_profils.py`, on bascule entre plusieurs profils. **Toujours vérifier quel profil est actif** avant un test.

### Piège 3 — Les briefs sur disque vs SQLite

Historiquement, les briefs étaient sur disque (`data/extractions_calibrees/*.json`). Maintenant ils sont dans SQLite (`briefs_extraits`). Le code lit les DEUX sources pour backward compat. **Ne pas casser ce double lookup.**

### Piège 4 — `taxonomie.json` vs `_taxonomie_domaines.json`

Apptia avait `taxonomie.json` (vestige). Tendia utilise `_taxonomie_domaines.json` (préfixe `_`). **Toujours utiliser le nouveau.**

### Piège 5 — `_preset.json` vs `_domaine.json`

Apptia utilisait `_domaine.json`. Tendia utilise `_preset.json`. Le code lit les deux pour backward compat mais **les nouveaux fichiers doivent être `_preset.json`**.

### Piège 6 — Younes lance les commandes manuellement

Tendia n'a pas (encore) de pipeline automatique. Younes lance chaque commande à la main. **Ne pas supposer que les choses tournent en cron.**

### Piège 7 — La base SQLite est mutualisée mais pas multi-utilisateur

Les collections `marches`, `classifications_ia`, `briefs_extraits` sont conçues pour servir N clients. Mais il n'y a pas de couche d'auth ou d'isolation **aujourd'hui**. C'est un sprint futur (Chantier E). Aujourd'hui : 1 base = 1 utilisateur.

### Piège 8 — Le mode mutualisé briefe TOUS les secteurs

`enrichir_complet.py --mutualise` ignore le preset actif et briefe tous les marchés briefables (~80-100). Younes l'a explicitement validé : c'est le modèle SaaS, base mutualisée. Ne pas le restreindre par preset.

### Piège 9 — Le matching IA prend la priorité sur le keyword

Dans `analyse.py`, si une classification IA existe pour un marché, elle SUPPLANTE le matching keyword. Le keyword est gardé en fallback pour les marchés non encore classifiés. **Toujours s'assurer que la classification IA passe en premier.**

### Piège 10 — `qualifications_requises.qualibat` peut être du texte libre

Le LLM peut sortir une string descriptive ("Non précisé dans le RC...") au lieu d'une liste de codes Qualibat à 4 chiffres. Si ton code itère sans guard, il itère caractère par caractère et produit des erreurs absurdes (vu en V2 : -50 sur "N, o, n,  , p, r, é..."). **Toujours vérifier `isinstance(v, list)` ET filtrer les codes à 4 chiffres** avant de comparer.

### Piège 11 — `acheteur_nom` n'a souvent pas le département

Pour les acheteurs nationaux IDF (OFPRA, CNAM, CNAF, Sénat, ministères...), le nom ne contient ni département ni région. La détection du département se fait via `ACHETEUR_VERS_DEPARTEMENT` (heuristique manuelle). Si tu ajoutes un nouveau pattern, **mets `None` pour les cas ambigus** (ex: "rectorat" qui dépend de l'académie).

### Piège 12 — `presets_marche=[]` ne signifie pas "hors taxonomie"

Un marché peut avoir `classifications_ia` rempli mais `presets_marche=[]` si le code domaine n'est pas mappé à un preset (ex: `entretien_proprete_locaux`, `services_environnement_analyses`, `transport_logistique_vehicules`, `fourniture_materiel`). Le matching V2 retourne alors un motif neutre (0) pour `preset_compatibilite`. Ce n'est PAS un bug — c'est juste qu'on n'a pas (encore) de preset pour ces familles. Décision 5 hors-preset pendante.

### Piège 13 — Clé `items` interdite dans un dict passé à Jinja

Jinja résout `mondict.items` vers la **méthode** `dict.items` (built-in), pas vers la clé `"items"`. Un `{{ mondict.items|length }}` plante (`builtin_function_or_method has no len()`). **Ne jamais nommer une clé `items`** dans une structure exposée au template (vu sur `tranches_ou_lots` → renommé `lignes`). Idem pour `keys`, `values`, `update`, `get`, `copy`.

### Piège 14 — Backup `data/tendia.db` en mode WAL

La base est en mode **WAL** (`PRAGMA journal_mode=WAL`). Un `Copy-Item data\tendia.db` (ou `cp`) **ne copie pas** le `-wal`/`-shm` : la copie peut être incohérente / périmée. **Toujours** faire `python -c "import sqlite3; c=sqlite3.connect('data/tendia.db'); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close()"` AVANT la copie. Pour remettre la base dans un état précis pendant les tests, préférer un reset par code (`stockage.sauver/ecrire`) à la copie de fichier.

### Piège 15 — Form multi-valeurs → `request.form.getlist`

Les widgets à valeurs multiples (checkboxes : presets, zones d'intervention, enums sectoriels) envoient le même `name` N fois. `request.form.get(name)` ne renvoie que la 1ʳᵉ valeur. **Toujours `getlist`** (sinon bug silencieux : ex `zones_intervention` lu en textarea ne gardait qu'un département). Le parser `profil_form.py` gère ça ; les références indexées se lisent via le pattern `prefix[N].champ`.

### Piège 16 — `dce_qualite` ≠ `dce_contenu` (NE PAS confondre)

Deux champs distincts sur `marches/<id>` :
- **`dce_qualite`** = qualité de **résolution de l'URL** (`directe`/`via_keyword`/`racine`/`absente`). **Porteur** : lu comme filtre de sélection des candidats au téléchargement par `enrichir_complet`, `tendia_pipeline`, `tendia_veille` (`in ("directe","via_keyword")`). **NE JAMAIS l'écraser** avec autre chose, sinon 0 candidat → pipeline cassé.
- **`dce_contenu`** = qualité du **contenu téléchargé** (`complet`/`incomplet`/`vide`/`auth_requise`/`erreur`), écrit par `tendia_dce.qualifier_dce`. C'est le champ à lire pour savoir si un DCE est briefable.

Un spec a déjà confondu les deux (proposait d'écraser `dce_qualite`) — ça aurait cassé 3 modules. Si tu vois une demande de « mettre la qualité du DCE dans `dce_qualite` », c'est `dce_contenu` qu'il faut.

### Piège 17 — Pas de réseau dans l'environnement de dev Claude

Les GET sortants échouent (SSLError, même google). Tout sprint impliquant du scraping live (plateformes DCE), des appels LLM réseau ou du téléchargement réel **n'est pas exécutable/vérifiable côté Claude** → livrer en scaffolding testé hors-ligne (HTML mockés, fake sessions) et laisser Younes lancer les parties réseau. Ne JAMAIS écrire de parseur de plateforme « à l'aveugle » sans le HTML réel du diagnostic.

---

## 6. Décisions architecturales clés à connaître

### Décision 1 — Classification IA remplace matching keyword

**Date** : Sprint 2 (juin 2026)
**Pourquoi** : Le matching keyword/CPV avait un taux de faux positifs énorme (0% d'alignement formation/EnR avant Sprint 2). Le LLM Haiku 4.5 à 0.004€/marché donne une classification fiable.
**Conséquence** : `scores_matching` contient un champ `mode_decision` ∈ {`classification_ia`, `keyword_fallback`}.

### Décision 2 — Architecture mutualisée

**Date** : Sprint 2
**Pourquoi** : Modèle SaaS multi-tenant cible. Coût marginal par client nul si les briefs sont mutualisés.
**Conséquence** : `enrichir_complet.py --mutualise` briefe TOUT, indépendamment du preset.

### Décision 3 — Mode strict par défaut sur le dashboard

**Date** : Sprint 2
**Pourquoi** : Le matching keyword remontait 80% de faux positifs (formation : 20 keyword vs 13 réellement pertinents). En strict, on affiche que les marchés où le LLM est d'accord.
**Conséquence** : Le dashboard est plus court mais plus pertinent. Younes peut explorer le reste via Explorer.

### Décision 4 — Templates par preset, pas méta-schéma

**Date** : Sprint 2 (à exécuter dans Chantier A)
**Pourquoi** : Younes a explicitement préféré la simplicité (1 template Jinja par preset) à la flexibilité (méta-schéma générique avec moteur de formulaires). Effort 2h30 vs 5h, complexité bien moindre.
**Conséquence** : `ui/templates/profil/<preset>.html` à créer pour chaque preset, pas de moteur générique.

### Décision 5 — DECP en requête à la volée (pas d'ingestion massive)

**Date** : Sprint 2 (en cours)
**Pourquoi** : Ingestion massive DECP = ~250k attributions = ~500 Mo + ~1000€ de classification. Trop. Requête en live = 0€ et scalable jusqu'à ~5000 utilisateurs.
**Conséquence** : `decp_consolidee.py` à généraliser pour requête ciblée par CPV/montant/dates.

### Décision 6 — Pas de classification IA de DECP

**Date** : Sprint 2
**Pourquoi** : DECP = marchés attribués, pas de candidature possible. La classification ne sert que si on veut filtrer par domaine fin (Vague 2 plus tard). 1000€ pour rien aujourd'hui.

### Décision 7 — Sprint DEMATIS reporté

**Date** : Sprint 2
**Pourquoi** : Captcha confirmé, effort 1-2 jours. Pas critique avant 1er prospect. À traiter quand le besoin est là.

### Décision 8 — Prompt LLM sectoriellement neutre

**Date** : Sprint 2
**Pourquoi** : `llm_extract.py` contenait 2 mentions "France Travail" dans le prompt système (vestige Apptia). Pour un marché BTP ou IT, ces mentions biaisaient potentiellement le LLM et étaient factuellement fausses pour les autres secteurs.
**Conséquence** : Prompt LLM 100% neutre désormais ("RC de marchés publics" au lieu de "RC France Travail"). Si tu ajoutes du contenu au prompt système, **vérifie absolument qu'il est applicable à TOUS les presets** (formation, BTP, IT, conseil, ingénierie, énergie).

### Décision 9 — Briefing priorisable par preset

**Date** : Sprint 2
**Pourquoi** : Younes veut briefer en priorité les presets de prospects ciblés (ex: énergie avant BTP avant formation). En mutualisé sans priorité, l'ordre serait alphabétique = inefficace pour le démarrage commercial.
**Conséquence** : `enrichir_complet.py --prioriser <preset>` (cumulable) ordonne les candidats. Pattern : `--prioriser energie_renouvelable --prioriser btp --prioriser formation` → énergie d'abord, puis BTP, puis formation, puis le reste.

### Décision 10 — Routage classif IA → schéma sectoriel ciblé

**Date** : Sprint 2bis (12 juin 2026)
**Pourquoi** : Avant le routage, un brief BTP recevait l'union de tous les schémas sectoriels (formation + énergie + conseil + IT + ingénierie). Le LLM remplissait n'importe quoi (publics_cibles formation pour un marché BTP, volumes_techniques EnR pour un marché conseil), produisant 8+ blocs hallucinés par brief.
**Conséquence** : `llm_extract.extraire_via_llm()` reçoit en argument la liste des presets cibles (résolus depuis `classifications_ia[marche_id].domaines_metier` via `preset.presets_pour_domaines()`) et envoie au LLM uniquement les schémas concernés. Si aucun preset n'est résolu (hors-taxonomie), fallback sur union complète (qui reste sous-optimal — voir Décision 5 hors-preset à trancher).

### Décision 11 — Filtre anti-hallucination post-LLM

**Date** : Sprint 2bis Sujet 2 (12 juin 2026)
**Pourquoi** : Le routage Décision 10 suffit dans 95% des cas, mais le LLM peut occasionnellement halluciner un bloc d'un autre schéma (mémoire des examples du prompt, classif initiale grossière, etc.). Il faut un filet de sécurité code.
**Conséquence** : Après parse JSON du LLM, `llm_extract._filtrer_hallucinations(data, codes_presets)` supprime tout bloc top-level qui n'est ni dans `_CHAMPS_UNIVERSELS_BRIEF` (12 champs universels : synthese_marche, domaines_metier, raison_classification, bareme_notation, montant_marche, revision_prix, alertes_prix, references_exigees, lots, calendrier, alertes_candidat, points_differenciants_attendus, + `_appel_llm`, `_meta`) ni dans `preset.blocs_sectoriels_pour_presets(codes_presets)`. Helper extraction par regex `^  "([a-z_]+)":\s*[\{\[]` sur `bloc_schema_specifique`.

### Décision 12 — Sync classif IA depuis sortie LLM (backflow)

**Date** : Sprint 2bis Sujet 1 (12 juin 2026)
**Pourquoi** : La classif IA initiale est faite par Haiku 4.5 sur le titre+objet (~200 tokens). Quand Sonnet 4.6 brief le DCE complet (~50k tokens), il a une vision beaucoup plus précise et peut re-classifier correctement. Garder la classif Haiku obsolète pénaliserait inutilement le routage Décision 10 sur les rebriefs futurs.
**Conséquence** : `tendia_extraire.py` met à jour `classifications_ia[marche_id]` après écriture du brief, si les codes domaines de la sortie LLM diffèrent de ceux stockés. Log `🔄 Classif IA mise à jour : [...] → [...]`. Validé in vivo : 6 marchés re-classifiés en Phase 3c, dont 2 corrections majeures de faux positifs (56463, 56493 qui n'étaient pas du tout BTP).

### Décision 13 — Profil organisme socle + sectoriels (Option C)

**Date** : Sprint A (12 juin 2026)
**Pourquoi** : Le profil organisme était formation-only (champs `publics_cibles`, `thematiques_metiers`, `directions_regionales_couvertes`). Pour un organisme BTP ou IT, ces champs n'avaient pas de sens. 3 options ont été comparées : (A) un seul schéma fourre-tout avec tous les champs nullables — illisible. (B) un schéma par preset complet — duplication. **(C) socle commun universel + profils sectoriels** par preset — propre.
**Conséquence** : Structure `{identite, presets_couverts, profils_sectoriels: {btp: {...}, it: {...}}, zones_intervention, mots_cles_catalogue, capacite_globale, certifications, references_globales, ...}`. Format legacy formation conservé en backward compat (détecté via présence de `thematiques_metiers` / `directions_regionales_couvertes` au top-level). Younes a explicitement validé : **pas d'admin UI POC, fichiers JSON édités à la main**.

### Décision 14 — Matching V2 avec routage legacy/multi-secteurs

**Date** : Sprint B (12 juin 2026)
**Pourquoi** : Conserver l'ancien code formation (Qualiopi, DR, prestations_maitrisees) tout en ajoutant le matching multi-secteurs sans casser les profils legacy existants.
**Conséquence** : `matching.evaluer()` détecte le format profil (`_est_format_legacy_formation()`) et route vers `_evaluer_legacy()` (V1 préservé) ou `_evaluer_v2()` (nouveau). Signature publique inchangée : `evaluer(organisme, marche, brief=None, presets_marche=None)`. Les 4 appelants (`tendia_matcher.py`, `tendia_veille.py`, `tendia_ui.py`, `tendia_dce.py`) ont été patchés pour passer le brief, mais fonctionnent même sans (mode dégradé sans scoring sectoriel).

---

## 7. Comment réagir aux situations courantes

### Situation : Younes pose une question stratégique

Pas de blabla. Réponds en 3 parties :
1. **Réponse directe** à la question
2. **Implications** chiffrées (coût, effort, risque)
3. **Ta recommandation** argumentée

Exemple : "DECP, est-ce faisable ?"
→ Pas : "Bonne question Younes ! C'est tout à fait possible et ouvre des perspectives intéressantes."
→ Plutôt : "Oui. Le module existe (decp_consolidee.py, hardcodé FT). 3 options : ingestion massive (250k, 1000€), requête live (3-4h dev, 0€/mois), cache hybride (4-5h dev). Mon vote : option 2, MVP scalable jusqu'à 5000 utilisateurs."

### Situation : Younes propose une décision

Évalue honnêtement. S'il a raison : confirme avec arguments. S'il a tort ou oublie un angle : pousse-le. Younes n'aime pas la flatterie, il aime la rigueur.

### Situation : Bug ou erreur dans son terminal

1. Diagnostique vite (1 ligne de Python pour vérifier l'état)
2. Identifie la cause (pas une supposition, un fait)
3. Propose le fix
4. Re-vérifie après application

### Situation : Younes valide rapidement ("ok go", "ok")

Il a vraiment validé. Exécute la commande/le code prévus, livre, passe à la suite.

### Situation : Younes hésite ou pose plusieurs questions

Il réfléchit stratégiquement. Ne pas précipiter. Reformule les options, pèse-les, donne ton vote argumenté, laisse-le décider.

### Situation : Coût ou risque potentiel

Toujours signaler. Younes apprécie la transparence. "Cette commande coûtera ~X€" / "Risque de Y" est mieux que "Lance-la sans y penser".

---

## 8. Ressources et docs

### Docs principaux

- **`docs/cadrage_strategique.md`** : Roadmap business, chantiers, coûts, stratégie commerciale
- **`docs/documentation_technique.md`** : Architecture interne, modules, conventions
- **`docs/README.md`** : Démarrage rapide, commandes essentielles
- **`docs/passation_claude.md`** : Ce document
- **`docs/journal.txt`** : Historique des sprints précédents

### Fichiers de configuration importants

- `.env` : `ANTHROPIC_API_KEY`
- `presets/_taxonomie_domaines.json` : 56 domaines, v1.1
- `presets/<code>/_preset.json` : 6 presets actifs
- `data/profil_organisme.json` : profil actif
- `data/profils/profil_<code>.json` : profils tests
- `budget.json` : kill-switch budget LLM

### Données

- `data/tendia.db` : ~80 Mo SQLite, mutualisée
- `data/dce_archives/<id>/` : DCE téléchargés (PDF originaux)
- `data/extractions_calibrees/<id>.json` : calibrations sourcées

---

## 9. Avant de répondre à Younes

**Checklist avant ton premier message** :

- [ ] Tu as lu `docs/cadrage_strategique.md` (roadmap business)
- [ ] Tu as lu `docs/documentation_technique.md` (architecture)
- [ ] Tu as lu ce document (passation Claude)
- [ ] Tu sais quel sprint est en cours
- [ ] Tu sais ce qui marche et ce qui ne marche pas
- [ ] Tu as une idée des conventions et préférences de Younes

**Ne demande PAS à Younes** :
- "Peux-tu m'expliquer ton projet ?" → Tu sais déjà.
- "Quelle est ton architecture ?" → Doc technique.
- "Quelles sont tes priorités ?" → Roadmap.
- "Comment lancer Tendia ?" → README.

**Demande à Younes** :
- L'état précis du sprint en cours (ce qui a tourné depuis ta passation)
- Les nouveaux blocages identifiés
- Les nouvelles décisions stratégiques

---

## 10. Mots de la fin

Tendia est un beau projet. Younes est rigoureux, a une vraie vision, et travaille proprement. Ton job est de l'aider à **livrer un produit commercialisable** sans perdre en qualité architecturale.

Si tu as un doute sur une décision : **demande**. Younes préfère 2 messages clairs à 1 message confus.

Si tu vois une opportunité d'amélioration architecturale : **propose**. Mais argumente toujours coût/effort/bénéfice.

Si tu identifies une dette technique : **signale**. Mais en respectant le timing (pas pendant un sprint critique).

**Bonne continuation. Tendia mérite de réussir.**

---

*Document mis à jour à chaque sprint. Dernière révision : 15 juin 2026 — Chantier 1
(architecture prompts LLM par preset 1A→1G : routage par preset effectif, champs
sectoriels enrichis, fix fallback hors-périmètre, versioning des prompts, re-extraction
priorisée), mini-sprint Proxy ciblé par plateforme, passe UI (Explorer multi-filtres +
nettoyage fiche marché), et documentation technique complète (`docs/` + `dette_technique.md`).*
