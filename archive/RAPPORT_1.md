# Rapport du chantier 1 : redémarrer la chaîne LLM (2026-11-10)

Branche `chantier/1-chaine-llm` (depuis `main` = `f44727a`). **Rapport en cours de rédaction** : les sections des étapes 6 à 8 sont remplies au fil des runs.

## En bref (provisoire)

- Étapes 1 à 5 faites et poussées : tests alignés sur le code (27/27 fichiers OK), proxy résidentiel conditionné à `TENDIA_PROXY_ACTIF=1`, tous les appels LLM journalisés dans `llm_appels`, classification en étape 2 du pipeline, script `rattrapage_btp_octobre.py`.
- Plafond mensuel porté à 30 € (décision Younes en cours de chantier) : novembre portait déjà 10,00 € de DECP au 02/11, un plafond à 20 € n'aurait laissé que 10 € au chantier.
- Pré-filtre de classification corrigé : les avis d'attribution BOAMP (`nature = "ATTRIBUTION"`) passaient au LLM (134 en octobre).
- Étape 6 : 1 992 marchés d'octobre traités, 1 757 classés, 235 rejetés par le pré-filtre, 0 reste, 10,85 € (Haiku, 0 échec).
- Étapes 7 et 8 : 534 cibles BTP d'octobre ; sur une passe de 60, 27 DCE complets ; **14 briefs BTP** à date limite ≥ 2026-12-09, 7,10 €.
- **Coût réel du chantier : 17,95 €** (classification 10,85 €, extraction 7,10 €), lu dans `llm_appels`, sous le plafond de 20 €.

## Points d'attention

1. **Novembre avait déjà 10,00 € dépensés** (reprise DECP du 02/11 : 8 479 appels Gemini flash-lite, 104 Gemini argon, 8 Haiku). `plafond_global_eur_mois` est mensuel : la valeur 20 demandée aurait bloqué le chantier à mi-classification. Valeur retenue après accord : 30 € (alerte 25 €). Le chantier reste borné par ses `--max-cout` (13 € classification, 7 € briefs).
2. **Pré-filtre de classification défaillant** depuis l'ingestion eForms : il lisait `nature_marche` et `ContractAwardNotice`, alors que les marchés portent `nature = "ATTRIBUTION"` et `notice_type = "10 | 6"`. Corrigé (`f5b7d6b`) : 245 rejets gratuits au lieu de 111. Les `ANNULATION` (3) et `RECTIFICATIF` (121) restent classés (non tranché : ce sont des avis modificatifs d'un marché existant).
3. **`test_aws_downloader` appelait le vrai CDN** `downloads.awsolutions.fr` (et le site AWS pour l'AAPC) depuis le patch `cdn_bypass` du 15/06 : `_session_sans_proxy` crée une vraie session HTTP. Le test recevait des HTTP 500 (54 s). Corrigé dans le test (session factice, AAPC servi) : hors ligne, 4 s, 3 fichiers.
4. **Pollution de la base de prod par un test** : une fois `classer_llm` journalisé, `test_decp_classifier_llm` a écrit 4 entrées factices dans le vrai `llm_appels` (0,0019 €). Retirées, archivées dans `archive/data/llm_appels_pollution_test_2026-11-10.json`. `tests/base_temporaire.py` isole désormais base et budget ; la suite complète est vérifiée sans écriture en prod (empreinte `kv_storage` identique avant/après).
5. **Rapport 0b erroné sur la clé API** : `ANTHROPIC_API_KEY` est bien dans `.env`, en ligne 1 derrière un BOM UTF-8 (`llm_extract` la lit en `utf-8-sig` ; ma recherche de 0b l'avait manquée).
6. **`telecharger.main` réécrit toute la collection `marches` en fin de run** (`sauver` global, dette connue) : interrompu, il perd tous les statuts. Le script de rattrapage ne l'appelle pas : il réutilise `_telecharger_marche` et écrit marché par marché.
7. **Quotas journaliers non appliqués** aux types journalisés par `verifier_kill_switch` (classification, calibration, mémoire, digest, decp) : `classification_max_par_jour = 2500` n'a d'effet que via `peut_appeler_llm`, que la classification n'appelle pas. Seuls kill switch et plafond mensuel s'appliquent. Non modifié.
8. **`llm_router` (Gemini, Opus) n'est pas journalisé** : hors périmètre (chantier 2). Les coûts DECP Gemini du 02/11 étaient journalisés par les scripts appelants.
9. **Coût de classification réel ≈ 0,0062 €/marché**, le double de l'estimation affichée par le module (0,003 €) : le prompt système (taxonomie de 64 domaines) fait ~5 500 tokens d'entrée.
10. **Restes de 0b nettoyés au passage** : 13 `import os` en double (amorce `sys.path`) retirés (`cd2ae16`).

## Hésitations

| Choix | Retenu | Alternative |
|---|---|---|
| Plafond mensuel | 30 € (10 € déjà dépensés + 20 € de chantier), validé par Younes | 20 € littéral (chantier à 10 €) ou 25 € |
| Échec d'écriture du journal | `budget.journaliser_appel` : enregistre hors du `try` qui relance l'appel, ne lève jamais (avertissement stderr) | `enregistrer_appel` direct : une erreur SQLite relancerait un appel payant |
| Une entrée par tentative | Chaque appel API journalisé (ok avec coût, erreur à 0 €) ; une réponse JSON invalide relancée compte deux fois | Une entrée par classification finale (sous-estime le coût réel) |
| Coût mémoire / digest | `budget.estimer_cout_eur` (tarif Sonnet, juste pour ces appels Sonnet) | Table de prix locale dans chaque module |
| Coût calibration | Formule du module (3 $ / 15 $) × `budget.TAUX_USD_EUR` | `estimer_cout_eur` (identique au centime) |
| `marche_id` des appels | Paramètre optionnel ajouté à `calibrer`, `calibrer_bottom_up_seul`, `appeler_llm`, `_appeler_llm`, transmis quand l'appelant le connaît ; `_rediger_une_section` (rédaction parallèle) journalise sans id | Ne pas transmettre l'id |
| Isolation des tests | `tests/base_temporaire.py` (`stockage.DATA_DIR`, `budget.FICHIER_BUDGET` temporaires) | Mocker `journaliser_appel` dans chaque test |
| Attente AWS du test | 3 fichiers avec session factice qui sert aussi l'AAPC (hors ligne) | 3 en laissant le réseau réel (non déterministe : le CDN répondait 500) |
| `TENDIA_PROXY_ACTIF` | `os.environ.setdefault` en tête de `main` (pipeline, 8 `retelecharger_*`, rattrapage) ; `plateforme=None` aussi coupé sans la variable | Variable lue au moment de l'import |
| Pré-filtre | Lecture de `nature` en plus de `nature_marche` | Laisser le LLM classer les attributions |
| Plateforme du tableau | `url_profil_acheteur`, à défaut hôte de `url_dce` (le profil manque sur 387 des 455 cibles) | `url_profil_acheteur` seul (« (aucune) » à 85 %) |
| Téléchargement du rattrapage | En processus (`_telecharger_marche` + `marquer_resultat_telechargement`, écriture unitaire) ; `--ids-fichier` ajouté aux CLI `resolution` et `telecharger` | Sous-processus `telecharger.py --ids-fichier` (sauver global en fin de run) |
| Connecteurs dédiés du rattrapage | Lancés tels quels (`--oui --max M`), ils choisissent leurs cibles par plateforme, pas seulement les ids d'octobre | Ajouter `--ids-fichier` aux 4 scripts dédiés |
| `extraire --max-cout` | Arrêt avant le marché suivant dès que le cumul atteint le plafond (dépassement possible d'un brief) | Arrêt sur estimation avant appel |

## Détail

### Tests avant / après

| Fichier | ✓ avant | ✗ avant | avant | ✓ après | ✗ après | après |
|---|---|---|---|---|---|---|
| `test_atexo_downloader.py` | 25 | 0 | OK | 25 | 0 | OK |
| `test_aws_downloader.py` | 42 | 1 | KO | 43 | 0 | OK |
| `test_boamp_contact.py` | 15 | 0 | OK | 15 | 0 | OK |
| `test_boamp_enrichissement.py` | 33 | 0 | OK | 33 | 0 | OK |
| `test_briefs_versioning.py` | 13 | 0 | OK | 13 | 0 | OK |
| `test_chemins.py` | 15 | 0 | OK | 37 | 0 | OK |
| `test_classification.py` | — | — | (nouveau) | 20 | 0 | OK |
| `test_dce_finder.py` | 24 | 0 | OK | 24 | 0 | OK |
| `test_decp_classifier_cpv.py` | 19 | 0 | OK | 19 | 0 | OK |
| `test_decp_classifier_llm.py` | 14 | 0 | OK | 16 | 0 | OK |
| `test_decp_db.py` | 13 | 0 | OK | 13 | 0 | OK |
| `test_decp_mapping_cpv.py` | 42 | 0 | OK | 42 | 0 | OK |
| `test_decp_matching.py` | 32 | 0 | OK | 32 | 0 | OK |
| `test_decp_parser.py` | 25 | 0 | OK | 25 | 0 | OK |
| `test_decp_parser_v2.py` | 23 | 0 | OK | 23 | 0 | OK |
| `test_dematis_downloader.py` | 35 | 0 | OK | 35 | 0 | OK |
| `test_dematis_workflow_har.py` | 51 | 0 | OK | 51 | 0 | OK |
| `test_downloader_dce_directe.py` | 12 | 0 | OK | 12 | 0 | OK |
| `test_extraction_v2_criteres.py` | 26 | 0 | OK | 26 | 0 | OK |
| `test_extraction_v2_montants.py` | 14 | 0 | OK | 14 | 0 | OK |
| `test_http_humain.py` | 37 | 0 | OK | 37 | 0 | OK |
| `test_llm_extract_routage.py` | 28 | 0 | OK | 28 | 0 | OK |
| `test_parallelisation.py` | 9 | 0 | OK | 9 | 0 | OK |
| `test_parseur_dce.py` | 22 | 0 | OK | 22 | 0 | OK |
| `test_proxy_par_plateforme.py` | 15 | 0 | OK | 23 | 0 | OK |
| `test_qualifier_dce.py` | 9 | 1 | KO | 10 | 0 | OK |
| `test_rattrapage_btp_octobre.py` | — | — | (nouveau) | 20 | 0 | OK |
| **Total** | | | **23/25** | | | **27/27** |

### Valeurs de `data/budget.json`

| Clé | Avant | Après |
|---|---|---|
| `plafond_global_eur_mois` | 100.0 | 30.0 (20 demandé, porté à 30 après accord : voir point 1) |
| `alerte_seuil_eur_mois` | 50.0 | 25.0 (15 demandé, aligné sur le plafond de 30) |
| `classification_max_par_jour` | 2000 | 2500 |
| autres clés | inchangées | inchangées |

### Appels LLM journalisés dans `llm_appels`

| Appel | Type | Fichier:ligne (succès / erreur) | Coût |
|---|---|---|---|
| `classification.classifier` | classification | `src/tendia/veille/classification.py:374` / `:429` | table `PRICING` Haiku du module |
| `llm_calibration.calibrer` | calibration | `src/tendia/analyse/llm_calibration.py:672` / `:705` | 3 $ / 15 $ × `TAUX_USD_EUR` |
| `llm_calibration.calibrer_bottom_up_seul` | calibration | `src/tendia/analyse/llm_calibration.py:891` / `:933` | idem |
| `_memoire_commun.appeler_llm` | memoire | `src/tendia/memoire/services/_memoire_commun.py:167` / `:162` | `budget.estimer_cout_eur` (Sonnet) |
| `digest_memoire._appeler_llm` | digest | `src/tendia/memoire/services/digest_memoire.py:173` / `:168` | idem |
| `prix/decp/classifier_llm.classer_llm` | decp | `src/tendia/prix/decp/classifier_llm.py:105` / `:125` | `_cout_eur` du module |
| déjà journalisés avant le chantier | | | |
| `llm_extract` (brief complet) | extraction | `src/tendia/analyse/llm_extract.py:1331`, `:1443`, `:1462`, `:1483` | module |
| `auto_brief` (brief light) | extraction | `src/tendia/analyse/auto_brief.py:176`, `:248`, `:274`, `:291` | module |
| `prix/decp/classif_batch` (batch DECP) | decp | `src/tendia/prix/decp/classif_batch.py:228`, `:240` | module |
| **non journalisé** : `llm_router` (Gemini/Opus) | | `src/tendia/analyse/llm_router.py:385` | chantier 2 |

### Étape 6 : classification

Suivi du run (`python -m tendia.veille.classification --max-cout 13`, lancé à 21h28) :

| Heure | Marchés traités | Classés / rejetés / échecs | Coût cumulé `llm_appels` (classification du jour) |
|---|---|---|---|
| 22h28 | 1 426 / 2 002 | 1 253 / 172 / 0 | 7,90 € (1 279 appels ok) |
| 22h49 (fin, 4 845 s) | 2 002 / 2 002 | 1 757 / 245 / 0 | 10,85 € (1 757 appels ok) |

`--dry-run` préalable : 2 002 cibles (tous les marchés non classés), 245 rejetées par le pré-filtre, 1 757 appels LLM annoncés (coût affiché 5,27 € sur la base erronée de 0,003 €/marché).

| Périmètre | Cibles | Classés | Rejetés (pré-filtre) | Échecs | Coût (`llm_appels`, type classification, 2026-11-10) |
|---|---|---|---|---|---|
| Tous les non classés | 2 002 | 1 757 | 245 | 0 | 10,8502 € (1 757 appels `claude-haiku-4-5`, tous `ok`) |
| dont octobre 2026 | 1 992 | 1 757 | 235 (134 attributions, 101 dates limites dépassées) | 0 | |
| dont hors octobre | 10 | 0 | 10 | 0 | |

Contrôle « marchés publiés en 2026-10 ni classés ni rejetés par `pre_filtre_rejette` » : **0** (1 992 = 1 757 classés + 235 rejetés). Coût moyen 0,0062 €/marché, garde-fou `--max-cout 13` non atteint. Marchés d'octobre classés `btp_*` : 511. Dépense totale de novembre après l'étape 6 : 20,85 € (10,00 € DECP du 02/11 + 10,85 €).

### Étape 7 : DCE d'octobre par plateforme

Lancé à 22h50 : `rattrapage_btp_octobre.py cibles`, puis `dce --max 60 --max-dedies 15`. Durée 597 s (borne de 2 h non atteinte).

- `cibles` : **534** marchés BTP d'octobre (classés `btp_*` ou `TRAVAUX`), hors attribution, date limite ≥ 2026-11-10. Aucun n'avait de DCE complet ; 6 avaient une `url_dce`.
- Passe : les 60 cibles à la date limite la plus lointaine. Résolution d'URL sur 59 sans `url_dce` ; téléchargement anonyme sur les 44 résolues : 28 ok, 15 manuel_requis, 1 erreur_reseau (les 15 `manuel_requis` sont des marchés AWS-Achat, réservés au batch anti-ban dédié).
- **Connecteurs dédiés sautés** : run hors heures de bureau (22h50), `--ignorer-heures` interdit. Les 15 AWS-Achat et les marches-securises restent à faire en journée.
- Résultat : URL résolue 6 → 49, téléchargés 0 → 28, **complets 0 → 27**.
- Lecture du tableau : la plateforme vient de `url_profil_acheteur`, à défaut de `url_dce`. Une URL résolue pendant le run peut donc faire changer un marché de ligne entre « avant » et « après » ; les totaux sont exacts.

| Plateforme | Cibles | URL résolue avant → après | Téléchargé avant → après | Complet avant → après |
|---|---|---|---|---|
| (aucune) | 386 | 0→0 | 0→0 | 0→0 |
| marches-publics.info | 32 | 2→15 | 0→0 | 0→0 |
| marches-publics.gouv.fr | 31 | 0→11 | 0→11 | 0→11 |
| achatpublic.com | 14 | 1→7 | 0→7 | 0→7 |
| marches-securises.fr | 10 | 1→1 | 0→0 | 0→0 |
| agysoft.marches-publics.info | 3 | 1→1 | 0→0 | 0→0 |
| marches.maximilien.fr | 3 | 0→3 | 0→3 | 0→3 |
| marches.megalis.bretagne.bzh | 3 | 0→1 | 0→1 | 0→1 |
| demat-ampa.fr | 2 | 0→1 | 0→1 | 0→1 |
| demat.centraledesmarches.com | 2 | 0→0 | 0→0 | 0→0 |
| klekoon.com | 2 | 0→1 | 0→0 | 0→0 |
| marches.ternum-bfc.fr | 2 | 0→1 | 0→1 | 0→1 |
| marchespublics.seinesaintdenis.fr | 2 | 0→0 | 0→0 | 0→0 |
| marchespublics596280.fr | 2 | 1→2 | 0→1 | 0→1 |
| montelimar-agglomeration-habitat.e-marches | 2 | 0→0 | 0→0 | 0→0 |
| mp74.fr | 2 | 0→0 | 0→0 | 0→0 |
| v2.marches-securises.fr | 2 | 0→0 | 0→0 | 0→0 |
| achats.yvelines.fr | 1 | 0→0 | 0→0 | 0→0 |
| brl.e-marchespublics.com | 1 | 0→1 | 0→1 | 0→0 |
| ca-montsaintmichel-normandie.e-marchespubl | 1 | 0→0 | 0→0 | 0→0 |
| cnfpt.marches-publics.info | 1 | 0→0 | 0→0 | 0→0 |
| e-marchespublics.com | 1 | 0→0 | 0→0 | 0→0 |
| eguadeloupe.com | 1 | 0→0 | 0→0 | 0→0 |
| fondsdegarantie.fr | 1 | 0→0 | 0→0 | 0→0 |
| letholonet.fr | 1 | 0→0 | 0→0 | 0→0 |
| mairie-de-collegien.fr | 1 | 0→0 | 0→0 | 0→0 |
| marches-grandbelfort.safetender.com | 1 | 0→0 | 0→0 | 0→0 |
| marches-publics.finances.rie.gouv.fr | 1 | 0→0 | 0→0 | 0→0 |
| marches.departement13.fr | 1 | 0→0 | 0→0 | 0→0 |
| marches2.lyon.fr | 1 | 0→0 | 0→0 | 0→0 |
| marchespublics-aude.safetender.com | 1 | 0→0 | 0→0 | 0→0 |
| marchespublics-departement.deux-sevres.fr | 1 | 0→0 | 0→0 | 0→0 |
| marchespublics.auvergnerhonealpes.eu | 1 | 0→1 | 0→1 | 0→1 |
| marchespublics.departement18.fr | 1 | 0→1 | 0→0 | 0→0 |
| marchespublics.grandest.fr | 1 | 0→0 | 0→0 | 0→0 |
| marchespublics.lacharente.fr | 1 | 0→0 | 0→0 | 0→0 |
| marchespublics.laregion.fr | 1 | 0→0 | 0→0 | 0→0 |
| marchespublics.vendee.fr | 1 | 0→0 | 0→0 | 0→0 |
| marchespublicsmanche.fr | 1 | 0→0 | 0→0 | 0→0 |
| marneetgondoire.fr | 1 | 0→0 | 0→0 | 0→0 |
| megalis.bretagne.bzh | 1 | 0→0 | 0→0 | 0→0 |
| mpe76.fr | 1 | 0→0 | 0→0 | 0→0 |
| plateforme.alsacemarchespublics.eu | 1 | 0→1 | 0→1 | 0→1 |
| sagep.e-marchespublics.com | 1 | 0→0 | 0→0 | 0→0 |
| saint-etienne.fr | 1 | 0→0 | 0→0 | 0→0 |
| saintjoseph.achatpublic.com | 1 | 0→0 | 0→0 | 0→0 |
| saintlouis.re | 1 | 0→0 | 0→0 | 0→0 |
| savoie.fr | 1 | 0→0 | 0→0 | 0→0 |
| trappes.fr | 1 | 0→0 | 0→0 | 0→0 |
| vaucluse.sudest-marchespublics.com | 1 | 0→0 | 0→0 | 0→0 |
| ville-septemes.fr | 1 | 0→1 | 0→0 | 0→0 |
| TOTAL | 534 | 6→49 | 0→28 | 0→27 |

### Étape 8 : briefs BTP d'octobre

Lancé à 23h01 : `rattrapage_btp_octobre.py briefs --max-cout 7 --max 20` (`--dry-run` préalable : 27 cibles à DCE complet sans brief complet, passe de 20). Durée ≈ 55 min (3 à 4 min par brief).

- **14 briefs complets** (`briefs_extraits`, `_meta.type = "complet"`), tous à date limite ≥ 2026-12-09 (critère : ≥ 2026-11-17). Coût lu dans `llm_appels` (type extraction) : **7,0971 €**, 0 erreur, 0,51 € par brief en moyenne.
- 3 marchés sans brief faute de PDF exploitable (aucun appel LLM) : à regarder à la main (DCE en `.doc`, `.zip` imbriqué ou scans : c'est le périmètre de lecture du chantier 2).
- Arrêt au plafond après le 17ᵉ marché de la passe : 7,097 € ≥ 7,00 € (dépassement de 0,097 € par le dernier brief, la règle d'arrêt vérifiant le cumul avant chaque marché). Restent 10 marchés à DCE complet sans brief (`BOAMP-26-103800` et suivants).

| Id | Date limite | Plateforme | Coût € (`llm_appels`) | Statut |
|---|---|---|---|---|
| `BOAMP-26-102749` | 2027-02-08 | marches-publics.gouv.fr | 0,000 | `pdfs_non_dce` : aucun PDF retenu comme pièce de DCE, pas d'appel LLM |
| `BOAMP-26-102932` | 2027-01-22 | marches-publics.gouv.fr | 0,400 | ok |
| `BOAMP-26-103744` | 2027-01-15 | marches.maximilien.fr | 0,663 | ok |
| `BOAMP-26-105552` | 2027-01-08 | achatpublic.com | 0,406 | ok |
| `BOAMP-26-105548` | 2027-01-08 | achatpublic.com | 0,396 | ok |
| `BOAMP-26-103907` | 2027-01-08 | marches.megalis.bretagne.bzh | 0,615 | ok |
| `BOAMP-26-104768` | 2027-01-07 | marches-publics.gouv.fr | 0,598 | ok |
| `BOAMP-26-104234` | 2026-12-18 | marches-publics.gouv.fr | 0,761 | ok |
| `BOAMP-26-103389` | 2026-12-15 | marchespublics596280.fr | 0,645 | ok |
| `BOAMP-26-104993` | 2026-12-14 | achatpublic.com | 0,294 | ok |
| `BOAMP-26-104121` | 2026-12-14 | achatpublic.com | 0,000 | aucun PDF exploitable (DCE « complet » au sens des noms de pièces, mais sans texte PDF lisible) |
| `BOAMP-26-103934` | 2026-12-14 | achatpublic.com | 0,000 | aucun PDF exploitable (idem) |
| `BOAMP-26-103126` | 2026-12-14 | marches-publics.gouv.fr | 0,616 | ok |
| `BOAMP-26-105506` | 2026-12-11 | marches-publics.gouv.fr | 0,435 | ok |
| `BOAMP-26-104757` | 2026-12-11 | achatpublic.com | 0,352 | ok |
| `BOAMP-26-104292` | 2026-12-10 | marches-publics.gouv.fr | 0,515 | ok |
| `BOAMP-26-105185` | 2026-12-09 | marches.maximilien.fr | 0,401 | ok |

### Coût par type d'appel (chantier)

Lu dans `llm_appels` (appels du 10/11 à partir de 19h UTC, soit la durée du chantier) :

| Type | Appels | Erreurs | Coût € |
|---|---|---|---|
| classification (Haiku 4.5) | 1 757 | 0 | 10,8502 |
| extraction (Sonnet 4.6) | 14 | 0 | 7,0971 |
| **Total chantier** | **1 771** | **0** | **17,9473** (≤ 20 €) |

Dépense totale de novembre : 27,95 € (10,00 € DECP du 02/11 + 17,95 €), sous le plafond mensuel de 30 €.
