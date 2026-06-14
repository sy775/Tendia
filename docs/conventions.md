# Conventions de code

Observées dans le repo (juin 2026). À respecter pour rester cohérent.

## Langue & style
- **Code et docs en français** (noms FR : `marche`, `preset`, `brief`, `analyse`).
  Commentaires techniques en anglais tolérés.
- Style direct, pas de boilerplate inutile. Docstrings de tête sur les modules.

## Encodage
- **UTF-8 partout** (fichiers, lecture/écriture).
- En tête de chaque script CLI : `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`
  (la console Windows est en cp1252 et plante sinon sur les accents / ✓ / ◆).
- Éviter les littéraux `bytes` accentués (`b"é…"` → SyntaxError) ; décoder puis comparer.
- Édition des JSON (presets) : round-trip `json.load` → modif → `json.dump(ensure_ascii=False, indent=2)`
  (préserve le fichier à l'octet près quand il est déjà en `indent=2`).

## Persistance
- Toujours passer par `stockage` (jamais d'accès SQLite direct dans le métier).
- `charger(coll)` lit tout ; `ecrire(coll, id, obj)` écrit un objet ;
  `sauver(coll, dict)` **remplace toute** la collection (attention).
- Données volumineuses (DCE) sur disque sous `data/dce/<id>/`, pas en base.

## Presets
- Le mapping domaine→preset est **dérivé des fichiers** `presets/<code>/_preset.json`
  (`veille.domaines_acceptes/optionnels`), pas un dict en dur.
- Après toute édition d'un `_preset.json` dans un process vivant : `preset.recharger()`
  (vide `_CACHE` + `_CACHE_UNION`).
- Versioning des prompts : SHA-256 (16 hex) via `preset.hash_preset` ; le `_meta`
  d'un brief complet porte `prompts_versions` (`{<code>/_preset.json: sha256:…}`).

## LLM
- Modèle d'extraction : `claude-sonnet-4-6` ; classification : Haiku.
- Tout appel LLM passe par le garde-fou `budget` (kill-switch + journal `llm_appels`).
- Tronquage entrée à `MAX_CHARS_INPUT = 400_000`.
- Routage par preset OBLIGATOIRE (passer `contexte["id"]` pour que
  `_resoudre_presets_pour_marche` fonctionne) ; sinon fallback neutre/union.

## HTTP & anti-ban
- Sessions via `http_humain.creer_session_humaine(plateforme=…)` (jamais `requests` nu
  pour les downloaders).
- Proxy ON par défaut ; désactivé par plateforme via `TENDIA_PROXY_FOR_<P>=0`.
- SSL : `truststore` injecté dans `http_client.py` ET `llm_extract.py` (le poste
  Windows n'a pas le CA intermédiaire dans certifi).

## Logs
- Événements machine : `tendia_logs.logger_evenement_marche(downloader, id, evt)`
  → `logs/<downloader>_<YYYY-MM-DD>.jsonl` (1 ligne JSON par événement, ne lève jamais).
- ⚠️ Les noms de downloader dans les logs (`aws-achat`) diffèrent parfois du code
  plateforme proxy (`aws_achat`) — cf dette_technique.

## Tests
- Style maison, **pas pytest** : `python tests_<module>.py`, compteur `ok/ko`,
  helper `check(nom, cond)`, `sys.exit(1 if ko else 0)`.
- Mocks via `FakeSession`/`FakeResponse` + monkeypatch des fonctions réseau.
- Fixtures réelles depuis les HAR (ex. `dematis exemple/…har`).

## Git
- Commits ciblés (`git add <fichiers précis>`), jamais `git add -A` aveugle.
- Séparer un fix d'intégrité d'une feature (`git add -p` si besoin).
- Message de commit clair ; trailer `Co-Authored-By: …`.
- Backups avant édition risquée : `<fichier>.bak_<contexte>_<timestamp>`
  (gitignorés : `*.bak`, `*.bak_*`).

## UI
- 100% polices système (pas de monospace « technique ») ; chiffres alignés via
  `font-variant-numeric: tabular-nums`.
- Pas d'affichage technique destiné au dev dans les vues utilisateur (commandes
  CLI, codes bruts, enums, IDs DECP) — cf passe UI.
- Serveur dev `python tendia_ui.py` (debug=off → redémarrer pour voir les changements
  de templates/code).
