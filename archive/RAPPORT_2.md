# Rapport du chantier 2 : lecture exhaustive des DCE (2026-11-11)

Branche `chantier/2-lecture-dce` (depuis `main` = `9f4e6a2`). Verdict : **à reprendre**. Le mode document est en prod et lit 100 % des pièces de texte des 4 DCE lus, mais le critère de fidélité n'est pas tenu (18/30 contre 28/30 exigés) et un DCE de référence n'a pas été lu. L'étape 8 n'a donc pas été lancée.

Arrêté à l'étape 8 : critère de l'étape 7 non atteint (fidélité 18/30 < 28/30, BOAMP-26-102749 non lu), étape 8 sautée conformément au texte du chantier.

## En bref

1. **Client LLM unique.** `llm_router` porte désormais tous les appels LLM de Tendia, avec kill switch et plafond avant chaque tentative et une entrée `llm_appels` après chaque tentative. Il n'existe plus aucun `Anthropic()` hors de lui. Aucun modèle ni aucun prompt n'a changé hors du brief.
2. **Lecture du DCE.** Le mode document est le mode par défaut. Il lit tout le dossier : sous-dossiers, zips imbriqués ou tronqués, `.doc`, `.xls`, `.odt` et `.rtf` convertis par Office, scans lus visuellement. Il travaille sous `data/pieces/<id>` et ne fait que lire `data/dce`. Chaque fichier reçoit un statut et chaque champ critique une source pièce + page vérifiée sans LLM. La fiche marché affiche ces sources et le taux de lecture.
3. **Résultats sur les 4 DCE lus.** 138 pièces de texte sur 138 sont lues (0 % non lu). 20 sources sur 20 marquées vérifiées le sont à juste titre, selon les vérificateurs. La fidélité est de 18/24 sur les 6 champs critiques, 18/30 en comptant le DCE non lu. Le défaut est systématique et vient de l'appel de fusion : il perd l'heure limite et fabrique ou dérive un montant que le DCE ne publie pas.
4. **Coût.** Le chantier a coûté **6,43 €** en appels LLM (plafond 16 €). Par DCE, la moyenne est de 1,61 € au tarif argon actuel, 3,18 € au tarif du 01/12 et 2,39 € en équivalent Sonnet 4.6 sur les mêmes tokens. La dépense de novembre atteint 34,38 €, pour un plafond de 45 €.
5. **Qualité.** Les étapes 1 à 6 ont été relues chacune par `relecteur-etape` : 2 bloquants et 23 majeurs relevés, tous corrigés, avec un commit de correctif par étape. Les tests passent de 30 fichiers et 765 vérifications à 48 fichiers et 2 282 vérifications, 100 % verts.

## Points d'attention

1. **La fusion invente des montants. C'est le premier défaut à corriger, au chantier 7 ou dans un chantier dédié.**
   - Sur les 4 briefs, aucune note par pièce ne porte de montant inventé : le RC et l'AE disent « non publié » ou « à compléter ».
   - C'est l'appel de fusion (prompt de prod de `llm_extract` + `SUPPLEMENT_SOURCES`) qui chiffre 320 000, 370 000 et 2 225 000 €, ou qui convertit 305 000 € TTC par an en 1 016 667 € HT sur 4 ans.
   - Cela heurte la règle « le LLM extrait, il ne calcule pas ». Le contrôle de complétude marque ces montants « present ».
   - L'heure limite (12h00 ou 16h00) est dans les notes par pièce et disparaît de `calendrier.date_limite_offres`.
   - Les prompts sont gelés (repris de 3ba9a4b, empreinte `doc-17afee47a0` testée) : rien n'a été modifié ici. Correctifs possibles : un post-traitement déterministe qui remet `montant_marche` à `non_communique` quand aucune note par pièce n'a de montant, et qui reprend l'heure de la note du RC ; ou un changement de prompt, décision à prendre par Younes.
2. **BOAMP-26-102749 n'a pas été lu.**
   - Son estimation (4,58 €) dépasse le plafond par DCE de 2,5 € fixé pour lui.
   - Son zip principal est tronqué (téléchargement interrompu) : 41 fichiers récupérés, le reste n'est pas lisible (statut `format_non_gere`).
   - Choix le plus prudent retenu : ne pas relever le plafond. Il faut retélécharger le DCE puis relancer avec `--max-cout-par-dce 5`.
3. **Les deux gros DCE prévus ont été remplacés.**
   - BOAMP-26-104234 était estimé à 10,26 € (185 pièces, 7 M de caractères) et BOAMP-26-103744 à 10,16 € (250 pièces dont 127 scans).
   - Ils sont remplacés par les deux plus volumineux des briefs du chantier 1 qui tiennent sous 4 € : **BOAMP-26-104292** (2,19 €, 31 pièces) et **BOAMP-26-104768** (1,16 €, 19 pièces).
   - BOAMP-26-102932 (4,54 €) et BOAMP-26-105506 (5,30 €) dépassaient aussi 4 €.
   - Ids réellement utilisés : 102749 (sauté), 104121, 103934, 104292, 104768.
4. **Incident de limite d'usage.**
   - Les 4 `verificateur-brief` de l'étape 7 ont été lancés en parallèle. Ils ont tous échoué sur la limite d'usage de 5 heures du modèle Fable (HTTP 429), vers 16h10.
   - Ils ont été repris un par un après la levée de la limite (17h14), par reprise de leur transcription. Aucune vérification n'a été faite à leur place.
   - Depuis, les sous-agents Fable sont lancés un à la fois.
5. **Un bug réel trouvé et corrigé pendant l'étape 7.**
   - Le SDK Gemini met le nom du fichier dans un en-tête HTTP : un PDF scanné au nom accentué levait `UnicodeEncodeError`, puis déclenchait un repli Sonnet payant (3 replis sur 104292).
   - Le fichier est désormais envoyé par son contenu, avec un nom ASCII. L'envoi a été vérifié en réel (Files API seule, gratuite, sur une fixture fictive).
6. **Vérification des sources affinée après le run.**
   - Le modèle cite souvent des extraits condensés (« a [...] b », « a / b ») ou la page voisine. 7 sources sur 24 étaient marquées non vérifiées pour ces seules raisons.
   - Désormais, l'extrait est vérifié fragment par fragment. S'il figure sur une autre page de la même pièce, la page est corrigée et l'ancienne gardée dans `page_citee`.
   - Les briefs déjà payés ont été recalculés sans LLM (`scripts/maintenance/recalculer_sources_brief.py`). Les anciens briefs ont été copiés dans `archive/data/briefs/` avant recalcul.
7. **Le pipeline change de comportement.**
   - `python -m tendia` (étape 6) lit maintenant en mode document, plafonné à 5 € par passe et 2,5 € par DCE. Il écarte les marchés clos, absents de la base ou déjà briefés, et commence par la date limite la plus proche.
   - Au tarif du 01/12, le même plafond par DCE sautera environ deux fois plus de DCE.
8. **Volume disque.**
   - `data/pieces/` fait 4,4 Go, pour 19 inventaires dont 2 de plus de 1 Go (104234 et 103744, inventoriés à blanc).
   - Les anciens dossiers de travail sont déplacés dans `archive/data/pieces/` (1,3 Go) et jamais supprimés.
   - Par DCE, `data/pieces/<id>` pèse à peu près autant que `data/dce/<id>`. Une politique de purge des dossiers de travail des marchés clos est à décider ; c'est un changement de règle « rien n'est supprimé », non tranché ici.
9. **Écarts connus au principe « rien n'est écrit dans data/dce ».** L'ancien dézippage à plat reste appelé par le mode `--mode classique` et par `memoire/services/digest_memoire.py`. La signature de dossier du mode document y est rendue insensible, mais `digest_memoire` devrait lire via `pieces.inventorier` (proposition).
10. **Taux USD/EUR unifié à 0,92.** Il est lu dans `config_llm.yaml` par le routeur et par `budget`. Les coûts DECP et calibration journalisés baissent d'environ 3 % (avant : 0,95).

## Hésitations

| Choix | Retenu | Alternative |
|---|---|---|
| Fidélité du montant estimé quand le DCE n'en publie aucun | Inexact (même règle sur les 4 briefs ; le vérificateur de 104292 l'avait compté exact, d'où 18/24 et non 19/24) | Exact si le brief dit « non publié » dans son commentaire |
| 102749 au-delà de 2,5 € | Sauté (choix prudent, ne dépense rien) | Relever son plafond à 5 € |
| Remplaçants des deux gros DCE | Les deux plus volumineux sous 4 € parmi les briefs du chantier 1 (104292, 104768) | 102932 (4,54 €) ou 105506 (5,30 €), au-delà de 4 € |
| Étape 8 | Sautée : critère non atteint | Lancer quand même les 10 briefs (~9 €) |
| Reprise de 104292 après correction du bug d'envoi | Relance de la seule pièce en échec + fusion (0,31 €), grâce à la reprise sur trace | Brief laissé à 30/31 pièces lues |
| Sources après le run | Recalcul sans LLM avec la vérification affinée | Laisser les sources du run (moins de vérifiées, même contenu) |
| Repli Sonnet | Un seul appel, sans relance JSON, jamais si le modèle est explicite ni sur une erreur locale | Relance JSON aussi sur le repli |
| `rmtree` du dossier de travail (relecture 4) | Remplacé par un déplacement dans `archive/data/pieces/`, trace des analyses payées conservée | Supprimer un cache régénérable |
| Plafond de passe du pipeline | 5 € par défaut sur l'étape 6 (aucun avant) | Pas de plafond de passe, seul le mensuel |
| Marchés déjà briefés en mode classique | Pas repayés en mode document sans `--force`, sauf nouvelles pièces | Tout relire au premier lancement (231 briefs complets hors état) |
| Tests de l'étape 6 | Fichier à part `test_ui_fiche_sources.py` (101 vérifications) + 15 dans `test_ui_routes.py` | Tout dans `test_ui_routes.py` |
| Visite de site sur la fiche | Ligne ajoutée dans « Comment candidater ? » pour porter sa source | Source seule, avec libellé |
| Date limite sur la fiche | La date lue dans le DCE est affichée avec sa source, sous la date de l'avis | Source sous la date de l'avis (trompeur, relevé par la relecture) |
| Sous-agents indisponibles en début de session | `testeur` et `relecteur-etape` créés à l'étape 0 n'étaient pas chargés : le testeur de l'étape 1 a tourné comme `general-purpose` avec le texte de `.claude/agents/testeur.md` ; tous les suivants ont tourné sous leur nom | Faire le travail soi-même |
| `mode_document.py` près de 800 lignes | Sources et taux de lecture sortis dans `sources_lecture.py` | Laisser à 792 lignes |

## Détail

### Tests avant / après

| | Avant (main `9f4e6a2`) | Après |
|---|---|---|
| Fichiers | 30 / 30 OK | 48 / 48 OK |
| Vérifications | 765 | 2 282 |
| Nouveaux | – | `test_plafond_cout` (53), `test_classification_max_cout` (18), `test_rattrapage_max_cout_zero` (12), `test_env_proxy_actif` (51), `test_base_temporaire_logs` (21), `test_explorer_methode` (23), `test_telecharger_ecriture_unitaire` (33), `test_llm_calibration_journal` (24), `test_max_cout_zero_cli` (17), `test_llm_router` (265), `test_llm_router_backends` (41), `test_appels_migres` (33), `test_pieces` (165), `test_mode_document` (300), `test_lecture_dce_robustesse` (77), `test_extraire_mode_document` (226), `test_extraire_scan_document` (42), `test_ui_fiche_sources` (101) |
| Modifiés | – | `test_classification`, `test_decp_classifier_llm` (faux client branché sur le routeur ; taux DECP 0,95 → 0,92), `test_ui_routes` (62 → 77), 10 tests de downloaders (`isoler_logs`) |

`logs/`, `data/extractions/_etat.json`, `data/dce` et `archive/data/briefs` sont inchangés par la suite (contrôlé avant et après).

### Relectures par étape (`relecteur-etape`)

| Étape | Commit | Verdict | Constats | Correctif |
|---|---|---|---|---|
| 1 Majeurs des audits 1 et 1b | `4ebef39` | accepté sous réserve | 0 bloquant, 3 majeurs (test du rattrapage non discriminant, `--max-cout 0` non testé sur `extraire.main` et le pipeline, backlog), 9 mineurs | `627e4fe` |
| 2 Routeur journalisé | `a6b150a` | à reprendre | 0 bloquant, 5 majeurs (kill switch absent des essais internes, essai facturé non journalisé, modèle sans tarif à 0 €, cache de prompt non compté, tests bornés à la couture) | `4a297dd` |
| 3 Client unique | `93fa533` | à reprendre | 0 bloquant, 3 majeurs (DECP freiné à 60 appels/min, JSON réparé accepté pour les briefs, tests manquants) | `0e2152c` |
| 4 Lecture en prod | `8a294da` | à reprendre | 1 bloquant (`rmtree` non borné), 9 majeurs (homonymes, zips écrasés, pièce vide « lue », alias à 0 €, inventaire périmé, fixtures abîmées par git, macros Office, tests de reprise) | `5c7df06`, `0e1f3da` |
| 5 Branchement | `925350c` | à reprendre | 1 bloquant (231 briefs existants repayés au premier lancement), 6 majeurs (passe sans plafond, scripts de ré-extraction, échecs retentés, dézippage à plat, nouvelles pièces ignorées, archive vérifiée trop tard) | `bada392` |
| 6 Fiche | `9e99a0e` | à reprendre | 0 bloquant, 4 majeurs (source de date sous la date de l'avis, critères invisibles au prix seul, montant mal placé, contraste) | `1b9f6e9` |

### Appels migrés vers `llm_router` (étape 3)

Les lignes sont celles de l'état final ; aucun modèle n'a été changé.

| Fichier:ligne | Appel | Modèle conservé | Type |
|---|---|---|---|
| `src/tendia/veille/classification.py:346` | `appeler_modele("classif")` | Haiku 4.5 (Sonnet 4.6 si `--modele sonnet`) | classification |
| `src/tendia/analyse/llm_extract.py:1380` | `appeler_modele("analyse")`, JSON strict | Sonnet 4.6 (mode `classique`) | extraction |
| `src/tendia/analyse/auto_brief.py:221` | `appeler_modele("analyse")`, JSON strict | Sonnet 4.6 | extraction |
| `src/tendia/analyse/llm_calibration.py:656` | `calibrer` | Sonnet 4.6 | calibration |
| `src/tendia/analyse/llm_calibration.py:861` | `calibrer_bottom_up_seul` | Sonnet 4.6 | calibration |
| `src/tendia/memoire/services/_memoire_commun.py:152` | `appeler_llm` | Sonnet 4.6 | memoire |
| `src/tendia/memoire/services/digest_memoire.py:157` | `_appeler_llm` | Sonnet 4.6 | digest |
| `src/tendia/prix/decp/classifier_llm.py:73` | `classer_llm` | Haiku 4.5 | decp |
| `scripts/decp/pilote_classif.py:149` | branche Claude de `classer_lot` | modèle de la variante | decp (enveloppe `decp_reprise`) |
| `src/tendia/analyse/mode_document.py:272` | `_appel_json` (nouveau) | Gemini 4 argon, repli Sonnet 4.6 | extraction |

`grep -rn "Anthropic(" src/ scripts/` (hors `_archive`) : uniquement `src/tendia/analyse/llm_router.py:501`.

Appels Gemini batch directs laissés tels quels, journalisés par leurs modules : `src/tendia/prix/decp/classif_batch.py`, `scripts/decp/pilote_arbitre.py`, `scripts/decp/pilote_arbitre_v2.py`, branche Gemini de `scripts/decp/pilote_classif.py`.

### Étape 7 : DCE de référence

Passe lancée à 13h19 UTC, plafonnée à 7 € (`--max-cout` = reste du plafond avant chaque DCE). Le `--dry-run` préalable (inventaire et estimation, aucun appel LLM) a été fait sur les 5 ids prévus et sur les 12 autres briefs du chantier 1.

| DCE | Pièces trouvées | Texte | Lues | Plans ignorés | Non gérées | Échecs conv. | % non lu avant | % non lu après | Modèle (replis) | Coût réel € | Au tarif du 01/12 € | Équiv. Sonnet € | Durée | Fidélité | Sources vérifiées |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 102749 | 43 (inventaire) | 41 | 0 | 1 | 1 (zip tronqué) | 0 | n/d (aucun brief : « pdfs_non_dce ») | non lu : sauté, estimation 4,58 € > 2,5 € | – | 0 | (9,17 estimé) | (6,88 estimé) | – | 0/6 | – |
| 104121 | 204 | 47 | 47 | 157 | 0 | 0 | n/d (aucun brief) | 0,0 | argon (0) | 1,510 | 3,019 | 2,264 | 452 s | 5/6 | 5/6, toutes à juste titre |
| 103934 | 336 | 41 | 41 | 295 | 0 | 0 | n/d (aucun brief) | 0,0 | argon (0) | 1,400 | 2,800 | 2,100 | 444 s | 4/6 | 5/6, toutes à juste titre |
| 104292 | 37 | 31 | 31 | 6 | 0 | 0 | n/d (brief classique : seul le CETS lu après troncature) | 0,0 | argon (3 replis Sonnet, bug d'envoi corrigé) | 2,464 | 4,774 | 3,619 | 457 s + 256 s | 4/6 (5/6 selon le vérificateur) | 5/6, toutes à juste titre |
| 104768 | 19 | 19 | 19 | 0 | 0 | 0 | n/d (brief classique, sans `_lecture`) | 0,0 | argon (0) | 1,058 | 2,116 | 1,587 | 361 s | 5/6 | 5/6, toutes à juste titre |
| **Total (4 lus)** | 596 | 138 | 138 | 458 | 0 | 0 | | **0,0** | | **6,431** | **12,709** | **9,570** | | **18/24** (18/30 avec 102749) | **20/20** |

Coût moyen par DCE lu : 1,61 € au tarif actuel, 3,18 € au tarif argon du 01/12, 2,39 € en équivalent Sonnet 4.6. Les coûts réels sont lus dans `llm_appels`, et `scripts/audit/rapport_lecture_dce.py` les recalcule.

Écart entre l'estimation et le coût réel : 104121 1,51 € pour 2,18 € estimés, 103934 1,40 pour 1,94, 104292 2,46 pour 2,19, 104768 1,06 pour 1,16. L'estimation est un ordre de grandeur, pas un plafond.

Volume : `data/pieces/` 4,4 Go (19 dossiers), dont 104121 392 Mo (DCE 344 Mo), 103934 543 Mo (494 Mo), 104292 38 Mo (65 Mo), 104768 17 Mo (26 Mo) ; `archive/data/pieces/` 1,3 Go.

#### Causes des champs inexacts (vérificateurs)

| DCE | Champ | Cause |
|---|---|---|
| 104121 | Montant (320 000 € inventé ; aucun montant au DCE) | Fusion : les notes RC et AE disent « non publié » |
| 103934 | Date limite (heure 12h00 absente) | Fusion : présente dans la note du RC |
| 103934 | Montant (370 000 € inventé) | Fusion |
| 104292 | Critères (agrégat technique 60 au lieu de 50 : critères 3 et 4 rangés dans « technique ») | Fusion : la note du RC est juste (40/50/5/5) ; le schéma prod n'a que deux cases |
| 104292 | Montant (2 225 000 € estimé, aucun montant publié) | Fusion |
| 104768 | Montant (305 000 € TTC/an converti en 1 016 667 € HT sur 4 ans, plancher inventé) | Fusion : les notes RC et AE sont justes |

Sur les 4 briefs, l'heure limite est présente dans la note du RC et perdue à la fusion. Aucun champ inexact ne vient d'une pièce non lue ni d'une question absente pour un type de pièce.

Manques et déformations hors champs critiques les plus utiles (détail dans les retours des vérificateurs) :
- pièces à produire par l'attributaire (RC, sous 5 à 8 jours), absentes des 4 briefs ;
- étude G2 PRO mise à la charge du candidat dans 104292, alors que le CCTP la met à la charge du maître d'ouvrage ;
- `experience_minimale_annees` déduit à tort de « références de moins de N ans » ;
- `poids_pct` de `grille_actions` inventés ;
- pénalité « absence réunion » reprise d'un titre d'article dont le texte copie la pénalité de retard.

#### Ancien brief (Sonnet 4.6, PDF tronqués) et nouveau brief

**104292**

| Champ | Ancien | Nouveau | DCE | Juste |
|---|---|---|---|---|
| Critères | nuls (« RC non disponible ») | 40/50/5/5 détaillés, agrégat technique 60 | 40/50/5/5 | Nouveau (agrégat à corriger) |
| Date limite | 2026-12-10 | 2026-12-10 | 10/12/26 12h00 | Les deux (sans heure) |
| Pièces exigées | liste vide | 15 pièces | 15 pièces (RC 5.1) | Nouveau |
| Visite | absente | obligatoire, 17/11 14h, attestation | idem | Nouveau |
| Montant | non communiqué, voie 2 0,8 à 2,5 M€ | 2 225 000 € estimé | aucun montant publié | Ancien sur le champ strict |
| Lots | vide | non alloti | non alloti | Nouveau |

**104768**

| Champ | Ancien | Nouveau | DCE | Juste |
|---|---|---|---|---|
| Critères | nuls | 60/40, tous les sous-critères et formules | identique | Nouveau |
| Date limite | 2027-01-07 | 2027-01-07 | 07/01/2027 16h00 | Les deux (sans heure) |
| Pièces exigées | 9 pièces, 7 manquantes, 1 inventée | 14 pièces | RC art. 5 | Nouveau |
| Visite | alerte sans modalités | obligatoire, délais, attestation | RC art. 11 | Nouveau |
| Montant | « aucun montant publié » | 1 016 667 € HT sur 4 ans | 305 000 € TTC/an, max 600 000 € TTC/an | Aucun |
| Lots | non alloti | non alloti | non alloti | Les deux |

### Étape 8

Non lancée : l'étape 7 ne donne ni 0 pièce de texte non lue sur les 5 DCE (102749 non lu), ni une fidélité ≥ 28/30 (18/30). La condition sur « 100 % de `verifie = true` sur les champs exacts » est en revanche tenue : 20 sources sur 20 marquées vérifiées le sont à juste titre.

### Coût par type d'appel (chantier)

Lu dans `llm_appels`, appels du 2026-11-11 (tous issus de l'étape 7) :

| Type | Modèle | Statut | Appels | Coût € | Tokens entrée / sortie |
|---|---|---|---|---|---|
| extraction | gemini-4-argon | ok | 141 | 6,2259 | 2 041 095 / 268 510 |
| extraction | gemini-4-argon | erreur (JSON invalide payé, ou erreur d'envoi à 0 €) | 4 | 0,0517 | 19 732 / 1 676 |
| extraction | claude-sonnet-4-6 | repli | 3 | 0,1537 | 39 174 / 3 306 |
| **Total** | | | **148** | **6,4314** | |

Aucun autre appel LLM pendant le chantier : tous les tests sont hors ligne, et l'envoi de contrôle du correctif (Files API) n'est pas facturé. Novembre au 2026-11-11 : 34,38 € (27,95 € avant le chantier).

### `data/budget.json`

| Clé | Avant | Après |
|---|---|---|
| `plafond_global_eur_mois` | 30.0 | 45.0 (décision du 2026-11-11 ; retour à 30 en décembre à faire à la main) |
| `alerte_seuil_eur_mois` | 25.0 | 40.0 |
| autres clés | inchangées | inchangées |

### Convertisseur

Microsoft Office 16 (Word et Excel) en COM, piloté par PowerShell, avec macros désactivées (`AutomationSecurity = 3`) et sans invite de mot de passe. LibreOffice est absent, comme `unrar` et `7z` : les `.rar` et `.7z` ont le statut `format_non_gere`. Test du COM à l'étape 0 sans document utilisateur : Word 16.0 et Excel 16.0, 0 document ouvert.

### Commits

`9782b62` prérequis et sous-agents · `4ebef39` + `627e4fe` étape 1 · `a6b150a` + `4a297dd` étape 2 · `93fa533` + `0e2152c` étape 3 · `8a294da` + `5c7df06` + `0e1f3da` étape 4 · `925350c` + `bada392` étape 5 · `9e99a0e` + `1b9f6e9` étape 6 · `ab87282` constats de l'étape 7 · étape 7 : ce rapport.
