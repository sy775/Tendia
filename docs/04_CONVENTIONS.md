# Tendia : conventions et règles de l'atelier

Même contenu que le `CLAUDE.md` du dépôt, en version longue. Si l'un change, l'autre suit.

## Rôles

| Qui | Fait | Ne fait pas |
|---|---|---|
| Younes | Décide le produit, valide, teste sur des marchés réels, prospecte | Coder |
| Claude (Projet, chat) | Spécifie chaque chantier, rédige les prompts Claude Code, relit les livrables, tient `CLAUDE.md` et ce backlog | Exécuter |
| Claude Code | Implémente un chantier à la fois, lance les tests, commit par étape | Décider l'architecture seul, lancer `Tendia.bat` ou des appels LLM non budgétés |
| `audit-code` (sous-agent) | Relit un livrable : lisibilité, structure, code mort, conformité à `CLAUDE.md`, tests | Modifier |
| `audit-design` (sous-agent) | Audite des écrans : données, paramétrage, lisibilité, responsive, captures | Modifier |

## Règles non négociables

1. Un chantier à la fois, numéroté, avec un critère de fin vérifiable et un rapport `archive/RAPPORT_<n>.md`.
2. Les calculs de prix sont déterministes : aucun LLM dans le calcul lui-même. Le LLM extrait des données, il ne calcule pas.
3. Rien à la racine du dépôt hors fichiers de config (`README.md`, `CLAUDE.md`, `pyproject.toml`, `requirements.txt`, `.env.example`, `.gitignore`, `Tendia.bat`) et les shims `tendia_ui.py`, `tendia_pipeline.py`.
4. Archiver avant de supprimer : tout fichier douteux va dans `archive/<chemin d'origine>`, jamais à la corbeille.
5. Les données vivent dans `data/` et `logs/`, hors git. Aucune donnée dans la connaissance du Projet.
6. Tout livrable Claude Code passe par `audit-code` avant d'être considéré terminé.
7. Aucun appel LLM payant sans plafond explicite (`--max-cost` ou `data/budget.json`) et sans journalisation dans `llm_appels`.
8. Jamais `Tendia.bat` pour vérifier que l'application démarre : `python -m tendia.ui` (ou `python tendia_ui.py`) suffit.
9. Jamais `stockage.sauver(collection)` pour une écriture unitaire : `stockage.ecrire(collection, id, objet)`.
10. La base de prod `data/tendia.db` est sauvegardée (`.bak_<objet>_<date>`, dans `archive/`) avant tout script qui la modifie en masse.
11. Pas de nouveau brainstorm produit avant le 2027-01-09 ou 5 démos faites.

## Code

- Python 3.12, UTF-8 partout, `sys.stdout.reconfigure(encoding="utf-8")` en tête des scripts CLI (Windows).
- Code, commentaires, docs et commits en français. Noms de fonctions en français (`telecharger_dce_pour_marche`), pas d'anglais mélangé.
- Persistance uniquement via `stockage` ; aucun `sqlite3.connect` dans le métier (exception connue à résorber : `src/tendia/prix/decp/db.py`, `tendia.eligibilite.organisme._timestamps_bibliotheque`).
- Appels LLM uniquement via `llm_router.call_llm` (ou `appeler_modele` pour un modèle fixé) : jamais de SDK direct.
- Un module = un rôle ; au-delà de 800 lignes, découper.
- Pas de script `diagnostic_*`, `debug_*`, `patch_*` commis à la racine : `scripts/audit/` ou `scripts/maintenance/`, sinon `archive/`.

## Tests

- Hors ligne, sans réseau ni clé API. Un test qui appelle une API n'est pas un test : c'est un script dans `scripts/`.
- `python tests/test_<module>.py` depuis la racine, style maison `check()` ; `python tests/lancer_tous.py` pour tout lancer.
- Fixtures dans `tests/fixtures/`, jamais de chemin en dur vers un autre dossier.
- Tout module de `core/`, `eligibilite/` et `analyse/` touché par un chantier reçoit au moins un test.

## Git

- Branche de travail : `main` (après 0b). Branches de chantier `chantier/<n>-<slug>` si le chantier dure plus d'une session, fusionnées en fin de chantier.
- Un commit par étape validée, message `type(scope): objet` (`chore`, `feat`, `fix`, `refactor`, `docs`, `test`).
- Push en fin de chantier, puis « Sync now » du connecteur GitHub dans le Projet Claude avant toute relecture dans le chat.

## Format des échanges

- Prompt Claude Code (rédigé par Claude chat) : contexte en 3 lignes, étapes numérotées avec un commit chacune, interdictions explicites, critère de fin, rapport attendu. Dans un bloc de code, prêt à coller.
- Rapport Claude Code : « en bref », points d'attention, hésitations, détail. Younes le colle dans le chat, Claude chat le relit et met à jour le backlog.
- Relecture par Claude chat : verdict en une ligne, écarts, correctif.
