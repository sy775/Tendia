# Guides d'extension

Comment ajouter une plateforme, un preset, un domaine, un champ de brief.
Ancré sur les mécanismes réels.

## Ajouter un PRESET sectoriel

1. Créer `presets/<code>/_preset.json` avec (cf un preset existant comme gabarit,
   `presets/btp/_preset.json` est le plus complet) :
   - `meta` : `code` (= nom du dossier), `nom`, `etiquette_courte`, `description`, `version`.
   - `veille` : `domaines_acceptes` / `domaines_optionnels` (codes taxonomie),
     `mots_cles_inclusion/exclusion`, `cpv_inclusion`.
   - `vocabulaire_llm` : `description, secteur_libelle, type_pieces_dce_typiques,
     type_repondant, unite_principale_facturation, references_attendues,
     alertes_typiques[], exemples_synthese[]`.
   - `prompt_extraction` : `description, bloc_schema_specifique` (les blocs JSON
     sectoriels), `regles_specifiques, exemples_elements_a_chiffrer,
     hints_calcul_montant, few_shot_examples`.
   - `prompt_calibration`, `calibration_llm`, `matching` (selon besoin).
2. Créer `presets/<code>/_schema.json` (schéma du profil organisme pour ce secteur,
   utilisé par `organisme.py` / l'éditeur de profil).
3. **Le mapping domaine→preset est automatique** (dérivé de `veille.domaines_acceptes/
   optionnels`). Appeler `preset.recharger()` (ou redémarrer) pour vider le cache.
4. Le routage d'extraction et le filtre anti-hallucination prennent le nouveau preset
   en compte sans code (via `presets_pour_domaines` / `blocs_sectoriels_pour_presets`).

## Ajouter un DOMAINE (code taxonomie)

1. Ajouter le code dans `presets/_taxonomie_domaines.json` (clé + libellé).
2. Le référencer dans le `veille.domaines_acceptes` (ou `_optionnels`) d'au moins un
   preset, sinon il mappe vers 0 preset (hors-périmètre).
3. Vérifier le mapping : `preset.presets_pour_domaines(["<code>"])`.

## Ajouter un CHAMP au brief

- **Sous-champ d'un bloc existant** : l'ajouter dans `prompt_extraction.bloc_schema_specifique`
  du preset concerné (c'est une string de schéma JSON). Le filtre anti-hallucination
  ne contrôle QUE les blocs top-level → un sous-champ passe automatiquement au stockage.
  Pas besoin de toucher `_schema.json` (qui sert au profil, pas au brief).
- **Nouveau bloc top-level** : l'ajouter aussi dans `bloc_schema_specifique` → il est
  alors auto-autorisé par `blocs_sectoriels_pour_presets` (regex sur les clés top-level).
- Affichage : ajouter le rendu dans `ui/templates/marche.html` (+ helpers
  `fiche_marche.py` si calcul).
- Re-extraire les marchés concernés pour peupler le nouveau champ.

## Ajouter une PLATEFORME de téléchargement DCE

1. Créer `<plateforme>_downloader.py` exposant l'API commune :
   - `telecharger_dce(...) -> dict` (workflow réseau spécifique à la plateforme),
   - `telecharger_dce_pour_marche(marche, repertoire_dce, ...) -> dict` (wrapper
     idempotent + logs + rotation IP sur ban). Voir
     [modules/downloaders.md](modules/downloaders.md) pour les patrons existants.
2. Utiliser `http_humain.creer_session_humaine(session_id=..., plateforme="<p>")`
   (jamais `requests` nu) pour bénéficier de l'anti-ban + proxy.
3. Réutiliser les briques communes : `aws_downloader._resoudre_captcha_2captcha`,
   `_request_avec_retry`, `_sanitiser_nom` ; décompression imbriquée via
   `achatpublic_downloader._decompresser_zip_imbrique`.
4. Brancher la détection de plateforme là où l'URL DCE est routée vers le bon
   downloader (selon le host de `url_dce`).
5. Proxy : ON par défaut. Pour autoriser le direct (plateforme sans ban), gérer
   `TENDIA_PROXY_FOR_<P>=0` et documenter dans `.env.example`.
6. Logs : `tendia_logs.logger_evenement_marche("<plateforme>", id, evt)`. ⚠️ garder
   un nom de log cohérent avec le code plateforme proxy (éviter le mismatch
   `aws-achat`/`aws_achat`).

## Ajouter une SOURCE d'avis (ex. data.gouv.fr / DECP)

- Créer un connecteur dans `connecteurs/` (cf `connecteurs/boamp.py`) qui produit des
  objets dans la collection `marches` (ou une collection dédiée).
- Récupération via `http_utils` (sans proxy) ou `http_humain(plateforme="data_gouv")`
  (le flag `TENDIA_PROXY_FOR_DATA_GOUV=0` existe déjà).
- Mapper les champs vers le schéma `marches` (cf [data_model.md](data_model.md)).
