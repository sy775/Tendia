# Inventaire des scripts CLI Tendia

Inventaire des scripts Python exécutables du dépôt (racine, `connecteurs/`, `scripts/`)
qui exposent un bloc `if __name__ == "__main__"` et/ou un parseur `argparse`.
Le rôle et l'usage type sont tirés du code réel (docstring de tête + bloc
argparse). Seul ce qui existe est documenté.

---

## Pipeline (ingestion, classification, DCE, extraction)

- **tendia_pipeline.py** — orchestrateur du pipeline complet automatique (récup BOAMP/TED → URLs DCE → téléchargement PLACE → extraction LLM → rapport final). `python tendia_pipeline.py [--skip-recup] [--skip-download] [--skip-llm] [--force] [--jours N]`
- **tendia_recup.py** — récupération des marchés publics via les connecteurs (BOAMP), normalisation et écriture idempotente en base. `python tendia_recup.py [--mois N] [--source SRC] [--large] [--limite N] [--dry-run] [--purge-source SRC]`
- **tendia_dce.py** — résolution des URLs DCE des marchés actifs (champ eForms ou recherche PLACE par référence FT) + rapport markdown. `python tendia_dce.py [--jours N] [--tous] [--dry-run] [--rapport-seul]`
- **tendia_classification.py** — classification IA (domaines métier) de chaque marché ingéré à partir du titre/objet/CPV/acheteur (Haiku par défaut). `python tendia_classification.py [--id ID] [--backfill] [--force] [--limite N] [--max-cout EUR] [--modele haiku|sonnet] [--dry-run] [--verbose]`
- **tendia_extraire.py** — orchestrateur d'extraction LLM des DCE déposés dans `data/dce/<id>/` (texte → Claude → brief COMPLET JSON + markdown). `python tendia_extraire.py [--marche ID] [--force] [--dry-run]`
- **scripts/maintenance/tendia_reextraire_batch.py** — ré-extrait en batch tous les marchés ayant un dossier DCE local (après modif du prompt LLM), avec estimation de coût. `python scripts/maintenance/tendia_reextraire_batch.py [--oui] [--dry-run]`
- **scripts/_archive/tendia_briefs_auto.py** — génération automatique de briefs LIGHT (depuis l'avis BOAMP seul) pour les marchés sans brief ; ne touche jamais aux briefs COMPLET. `python scripts/_archive/tendia_briefs_auto.py [--force] [--limit N] [--marche ID] [--dry-run]`
- **auto_brief.py** — génération d'un brief LIGHT pour un marché à partir de l'avis BOAMP seul (titre + objet + métadonnées), sans DCE (module appelé par tendia_briefs_auto, exécutable directement). `python auto_brief.py`
- **scripts/_archive/enrichir_complet.py** — orchestrateur d'enrichissement COMPLET des marchés pertinents (téléchargement DCE puis extraction LLM, sous garde-fou budget). `python scripts/_archive/enrichir_complet.py [--dry-run] [--limite N] [--max-cout EUR] [--force] [--id ID] [--mutualise] [--prioriser PRESET]`
- **scripts/maintenance/reextraire_briefs_complet.py** — re-génère le brief LLM des marchés passés `dce_contenu=="complet"` sans re-télécharger le DCE (fichiers déjà sur disque). `python scripts/maintenance/reextraire_briefs_complet.py [--oui] [--limite N]`
- **veille (connecteurs/boamp.py)** — connecteur BOAMP France Travail ; exécuté directement, liste les marchés captés sur une fenêtre. `python connecteurs/boamp.py [--mois N] [--limite N]`
- **scripts/_archive/tendia_veille.py** — daemon de veille : passes périodiques (récup + re-matching + identification des marchés pertinents + journal). `python scripts/_archive/tendia_veille.py [--intervalle H] [--une-passe] [--avec-ted] [--mois N] [--match-seul] [--seuil-complet ...] [--max-extractions N]`

## Téléchargement DCE (batchs)

- **place_downloader.py** — téléchargement anonyme du DCE depuis PLACE (marches-publics.gouv.fr) via double POST Prado/Atexo (module ; CLI de test mono-marché). `python place_downloader.py <id_place> <org_acronyme> [chemin_zip]`
- **achatpublic_downloader.py** — téléchargement anonyme du DCE sur achatpublic.com (POST telechargerDCE + dézip imbriqué) ; CLI de test mono-marché. `python achatpublic_downloader.py <pcslid> [chemin_zip]`
- **aws_downloader.py** — téléchargement anonyme du DCE sur marches-publics.info (AWS-Achat / ColdFusion) avec résolution captcha 2captcha ; CLI de test mono-marché. `python aws_downloader.py <IDM> [dossier_destination]`
- **dematis_downloader.py** — téléchargement anonyme du DCE sur les plateformes Dematis (`*.e-marchespublics.com`), workflow captcha ; CLI de test mono-URL. `python dematis_downloader.py <url_dce> [dossier_destination] [--no-verify-ssl]`
- **tendia_telecharger_dce.py** — téléchargement automatique des pièces DCE depuis PLACE pour les marchés ayant une `url_dce` (parsing page, soumission CGU, dépôt dans `data/dce/<id>/`). `python tendia_telecharger_dce.py [--marche ID] [--limit N] [--force] [--dry-run] [--verbose]`
- **scripts/_archive/backfill_dce_qualite.py** — backfill rétroactif du champ `dce_contenu` (qualité du contenu) via tendia_dce.qualifier_dce, avec relance optionnelle. `python scripts/_archive/backfill_dce_qualite.py [--relancer]`
- **scripts/maintenance/relancer_dce_echecs.py** — relance le téléchargement DCE sur les marchés en statut `echec`, hors « murs » connus (login/captcha/faux succès). `python scripts/maintenance/relancer_dce_echecs.py [--filtre-domaine SUBSTR] [--exclure-raison SUBSTR] [--limit N] [--dry-run] [--verbose]`
- **scripts/maintenance/retelecharger_incomplet.py** — re-télécharge les marchés `dce_contenu=="incomplet"` via le téléchargeur profond puis re-qualifie. `python scripts/maintenance/retelecharger_incomplet.py`
- **scripts/maintenance/retelecharger_achatpublic.py** — re-télécharge les marchés achatpublic.com (auth_requise/vide) via le downloader anonyme dédié, avec backup. `python scripts/maintenance/retelecharger_achatpublic.py`
- **scripts/maintenance/retelecharger_aws_achat_anti_ban.py** — variante anti-ban du batch AWS-Achat (délais gaussiens, pauses cumulatives, cap/run, heures de bureau). `python scripts/maintenance/retelecharger_aws_achat_anti_ban.py [--oui] [--max N] [--ignorer-heures]`
- **scripts/maintenance/retelecharger_dematis_anti_ban.py** — batch anti-ban de retrait du DCE sur Dematis (délais gaussiens, pauses, cap/run, heures de bureau). `python scripts/maintenance/retelecharger_dematis_anti_ban.py [--oui] [--max N] [--ignorer-heures]`
- **scripts/maintenance/retelecharger_vide_atexo.py** — re-télécharge les marchés `dce_contenu=="vide"` à signature Atexo via atexo_downloader, avec backup. `python scripts/maintenance/retelecharger_vide_atexo.py`

## Matching & analyse

- **analyse.py** — moteur d'analyse multi-preset déterministe (mots-clés + CPV + exclusion) déterminant la pertinence des marchés, sans appel LLM. `python analyse.py [--force] [--montrer PRESET] [--stats] [--enrichir] [--limite N] [--dry-run] [--forcer-brief]`
- **scripts/_archive/tendia_matcher.py** — matching organisme × marchés contre le profil actif, avec rapport markdown. `python scripts/_archive/tendia_matcher.py [--filtre pertinent|a_verifier|...] [--top N] [--console] [--sortie FICHIER]`
- **scripts/audit/audit_matching_n2.py** — audit du scoring de pertinence V2 (matching.py) sur la base, comparaisons et export CSV. `python scripts/audit/audit_matching_n2.py [--db PATH] [--profil FICHIER] [--comparer] [--sans-injection] [--csv FICHIER]`
- **scripts/audit/audit_classifications.py** — audit des classifications LLM (domaines_metier) : distribution, alignement matching/LLM, cas suspects. `python scripts/audit/audit_classifications.py [--conflits] [--preset PRESET]`
- **scripts/audit/audit_briefs.py** — audit de la qualité des briefs COMPLET en cache (barème, montant, pièces traitées) avec verdict utile/partiel/vide. `python scripts/audit/audit_briefs.py`
- **scripts/audit/audit_plateformes_dce.py** — audit des plateformes de dématérialisation présentes (famille, outil reconnu, état du DCE obtenu). `python scripts/audit/audit_plateformes_dce.py`
- **scripts/audit/audit_mapping_domaines_presets.py** — audit (lecture seule) du mapping code domaine → presets et propositions de resserrement (produit un .md). `python scripts/audit/audit_mapping_domaines_presets.py`
- **scripts/audit/audit_presets_extraction.py** — audit (lecture seule) de la richesse des champs `prompt_extraction`/`vocabulaire_llm` des presets vs gabarit BTP (produit un .md). `python scripts/audit/audit_presets_extraction.py`
- **scripts/audit/bilan_briefs.py** — état des lieux croisé (pertinence × statut DCE × brief COMPLET × brief LIGHT) avec marchés à enrichir et coût estimé. `python scripts/audit/bilan_briefs.py [--liste-a-enrichir] [--liste-anomalies]`
- **scripts/audit/dump_brief.py** — affiche le contenu d'un brief LLM en format lisible pour évaluation humaine (liste, détail, synthèse). `python scripts/audit/dump_brief.py [--id ID] [--type COMPLET|LIGHT|INCONNU] [--resume]`
- **scripts/_archive/tendia_apercu.py** — aperçu lisible de la base marchés (volumétrie par source/catégorie/mois, top acheteurs, état d'ouverture). `python scripts/_archive/tendia_apercu.py [--categorie formation|insertion|autre] [--liste-tout] [--doute] [--top-acheteurs N] [--recents N]`

## Calibration & concurrence

- **scripts/maintenance/calibrer_briefs.py** — calibration prix (top-down DECP + bottom-up, ou bottom-up seul) sur les briefs COMPLET existants. `python scripts/maintenance/calibrer_briefs.py [--id ID] [--force] [--mode auto|bottom_up|triangule] [--dry-run] [--detail] [--preset-force PRESET]`
- **llm_calibration.py** — deuxième passe LLM : calibre l'estimation prix d'un marché en croisant le brief froid avec des comparables DECP (module ; CLI mono-marché). `python llm_calibration.py <id_marche> [--force] [-v]`
- **llm_extract.py** — extraction structurée du contenu d'un DCE (RC + CCTP + pièces) via Claude (module d'extraction, exécutable directement). `python llm_extract.py`
- **scripts/_archive/tendia_capture_attributions.py** — capture les attributions DECP des marchés actifs vus passer (matching réf/SIRET/objet), incrémental et idempotent. `python scripts/_archive/tendia_capture_attributions.py [--marche ID] [--dry-run] [--force] [--reset-etat] [--seuil-sim FLOAT]`
- **scripts/_archive/tendia_decp.py** — récupération des marchés notifiés France Travail depuis DECP, enrichissement SIRENE optionnel. `python scripts/_archive/tendia_decp.py [--annees N] [--limite N] [--enrichir] [--dry-run]`
- **scripts/_archive/tendia_decp_volumes.py** — rétro-extraction LLM (Haiku) des volumes manquants (bénéficiaires, durée, public...) sur les marchés DECP historiques. `python scripts/_archive/tendia_decp_volumes.py [--force] [--limit N] [--dry-run] [--marche ID] [--no-filtre]`
- **scripts/_archive/enrichissement_sirene.py** — enrichit un SIRET avec le nom de l'organisme via l'API recherche-entreprises (cache `titulaires`). `python scripts/_archive/enrichissement_sirene.py <siret> [--force]`
- **scripts/_archive/decp.py** — connecteur DECP (Opendatasoft) des marchés notifiés (module ; exécution directe pour collecte). `python scripts/_archive/decp.py [--annees N] [--limite N]`

## Maintenance / réparation base

- **scripts/_archive/nettoyer_attributions.py** — purge des marchés ContractAwardNotice (avis d'attribution) en base (dry-run par défaut). `python scripts/_archive/nettoyer_attributions.py [--dry-run] [--appliquer] [--vers-attribution] [--limite N]`
- **scripts/_archive/nettoyer_dce_faux_succes.py** — nettoie les dossiers DCE ne contenant que des fichiers génériques (faux succès) et corrige les statuts en base. `python scripts/_archive/nettoyer_dce_faux_succes.py [--dry-run] [--verbose]`
- **scripts/_archive/purger_briefs_faux.py** — détecte et purge les briefs générés sur des DCE en réalité vides (heuristique nb de pièces métier). `python scripts/_archive/purger_briefs_faux.py [--dry-run] [--appliquer] [--vers-suspect] [--seuil N]`
- **scripts/_archive/identifier_briefs_pollues.py** — identifie les briefs COMPLET à régénérer (blocs héritage formation/EnR inadéquats au preset). `python scripts/_archive/identifier_briefs_pollues.py [--ids] [--csv]`
- **scripts/_archive/reparer_statuts.py** — corrige les statuts DCE faussés par un premier run de nettoyage (marchés sans url_dce remis en `jamais_tente`), idempotent. `python scripts/_archive/reparer_statuts.py [--dry-run]`
- **scripts/maintenance/regenerer_briefs_md.py** — re-rend les briefs markdown depuis les JSON en cache, sans appel LLM. `python scripts/maintenance/regenerer_briefs_md.py [--id ID] [--type COMPLET|LIGHT|INCONNU] [--dry-run]`
- **jointure.py** — maintient l'index de jointure BOAMP↔DECP par référence acheteur interne (module ; exécutable directement). `python jointure.py`
- **briefs_versioning.py** — versioning des prompts d'extraction ; exécuté directement, liste les briefs obsolètes (prompts modifiés depuis génération). `python briefs_versioning.py`
- **stockage.py** — couche de persistance SQLite ; exécuté directement, affiche l'état des collections ou migre JSON → SQLite. `python stockage.py [--migrer [--forcer]]`

## Monitoring & stats

- **scripts/audit/tendia_monitoring.py** — dashboard console de l'état des téléchargements DCE (couverture, derniers batchs, coûts du mois, échecs à reprendre). `python scripts/audit/tendia_monitoring.py [--jours N]`
- **scripts/audit/stats_pipeline_dce.py** — comptage des avis ingérés, des DCE par état et des briefs LLM extraits. `python scripts/audit/stats_pipeline_dce.py [--db PATH]`
- **budget.py** — garde-fou budgétaire LLM ; exécuté directement, affiche la configuration et les statistiques du jour. `python budget.py`
- **preset.py** — module central de chargement des presets ; exécuté directement, affiche presets disponibles, preset actif et aperçu du vocabulaire. `python preset.py`
- **organisme.py** — gestion du profil organisme ; exécuté directement, affiche/valide le profil actif. `python organisme.py [--show] [--check]`

## UI

- **tendia_ui.py** — serveur web Flask de Tendia (dashboard marchés, détail, profil, veille), exposé sur http://localhost:5000. `python tendia_ui.py`

## Autres

- **scripts/maintenance/init_profil.py** — initialisation / migration du profil organisme depuis un JSON (génération de template, import, purge). `python scripts/maintenance/init_profil.py [--status] [--template PRESET...] [--depuis FICHIER] [--purger] [--force]`
- **pdf_extract.py** — extraction de texte des pièces DCE (.pdf/.docx/.xlsx) déposées dans `data/dce/<id>/` (module d'extraction, exécutable directement). `python pdf_extract.py`
- **scripts/_archive/inspecter_decp.py** — diagnostic one-shot du schéma DECP brut (nom exact du champ `reference_acheteur`), lecture seule. `python scripts/_archive/inspecter_decp.py [--n N] [--champs MOTIF]`
- **scripts/_archive/inspecter_decp_consolidee.py** — diagnostic de l'API DECP consolidée (data.gouv.fr) : accessibilité, filtres, colonnes, volume, échantillons. `python scripts/_archive/inspecter_decp_consolidee.py`
- **scripts/audit/inspecter_page_dce.py** — outil de diagnostic : récupère et parse une page DCE (liens, formulaires, login/captcha) avec le parser de tendia_telecharger_dce. `python scripts/audit/inspecter_page_dce.py <url> [--save-html]`

---

> Note : les scripts `diag_*`, `diagnostic_*`, `patch_*` et `_tmp_*` sont des outils
> jetables (diagnostics ponctuels, correctifs ad hoc) et ne sont pas documentés ici.
> Voir `dette_technique.md`.
