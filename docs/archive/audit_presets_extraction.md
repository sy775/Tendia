# Audit richesse `prompt_extraction` / `vocabulaire_llm` par preset

_Lecture seule. Gabarit de référence : **btp** (le plus complet). Sous-chantier 1A.1._

Presets audités : btp, conseil, energie_renouvelable, formation, ingenierie, it

## 1. `prompt_extraction` (sous-clés × presets)

Cellule = `chars` (ou `n items` pour les listes). `—` = ABSENT.

| Sous-clé | btp | conseil | energie_renouvelable | formation | ingenierie | it |
|---|---|---|---|---|---|---|
| `description` | 60c | 60c | 153c | 142c | 60c | 60c |
| `bloc_schema_specifique` | 1223c | 1851c | 1960c | 1212c | 1689c | 1581c |
| `regles_specifiques` | 419c | 301c | 696c | 641c | 491c | 520c |
| `exemples_elements_a_chiffrer` | 213c | 144c | 236c | 150c | 149c | 243c |
| `hints_calcul_montant` | 145c | 230c | 396c | 390c | 103c | 109c |
| `few_shot_examples` | — | — | — | — | — | — |

## 2. `vocabulaire_llm` (sous-clés × presets)

| Sous-clé | btp | conseil | energie_renouvelable | formation | ingenierie | it |
|---|---|---|---|---|---|---|
| `description` | 83c | 83c | 77c | 93c | 83c | 83c |
| `secteur_libelle` | 109c | 123c | 149c | 186c | 141c | 172c |
| `type_pieces_dce_typiques` | 298c | 266c | 262c | 210c | 284c | 196c |
| `type_repondant` | 102c | 165c | 90c | 148c | 198c | 215c |
| `unite_principale_facturation` | 63c | 44c | 91c | 75c | 48c | 72c |
| `references_attendues` | 111c | 86c | 130c | 113c | 91c | 98c |
| `alertes_typiques` | 9 items | 5 items | 12 items | 9 items | 6 items | 6 items |
| `exemples_synthese` | 3 items | 3 items | 2 items | 2 items | 3 items | 3 items |

## 3. Manques par preset (vs gabarit `btp`)

| Preset | prompt_extraction manquants | vocabulaire_llm manquants |
|---|---|---|
| btp | few_shot_examples (nouveau 1B) | ✓ complet |
| conseil | few_shot_examples (nouveau 1B) | ✓ complet |
| energie_renouvelable | few_shot_examples (nouveau 1B) | ✓ complet |
| formation | few_shot_examples (nouveau 1B) | ✓ complet |
| ingenierie | few_shot_examples (nouveau 1B) | ✓ complet |
| it | few_shot_examples (nouveau 1B) | ✓ complet |

## 4. Champs présents mais SOUS-DÉVELOPPÉS (vs gabarit)

Seuil : < 60% de la taille du même champ chez `btp`.

| Preset | Champ | Taille | Gabarit btp | Ratio |
|---|---|---|---|---|
