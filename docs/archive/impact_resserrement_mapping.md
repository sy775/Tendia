# Impact — resserrement mapping (Sous-chantier 1C)

Actions appliquées :
1. Retrait de `moe_architecte_urbanisme` de `veille.domaines_optionnels` dans **btp** ET **conseil** (laissé en `domaines_acceptes` de **ingenierie** uniquement).
2. Correction du typo `energia_amo_etudes` → `energie_amo_etudes` dans `briefs_extraits/BOAMP-26-56662` (backup : `backups_brief_BOAMP-26-56662_avant_1c.json`).

## Mapping du code après resserrement

- `moe_architecte_urbanisme` → **[ingenierie]** (était `[ingenierie, btp, conseil]`, 3 presets → 1)
- `energie_amo_etudes` → `[energie_renouvelable, ingenierie]` (le typo `energia_*` ne mappait vers aucun preset)

## Impact sur les 27 marchés classifiés `moe_architecte_urbanisme`

- Changement de l'**ensemble** de presets : **27/27**
- Changement du preset **PRINCIPAL** (1ᵉʳ) : **0/27** (ingénierie reste principal)

| État | Répartition des ensembles de presets |
|---|---|
| AVANT | `[ingenierie, btp, conseil]` ×26 ; `[btp, ingenierie, conseil]` ×1 |
| APRÈS | `[ingenierie]` ×25 ; `[ingenierie, btp]` ×1 ; `[btp, ingenierie]` ×1 |

Les 2 marchés qui conservent `btp` ont, en plus de `moe`, un code `btp_*` propre (rattachement légitime). Les 25 autres deviennent **ingénierie seul**.

## ⚠️ Point d'attention (décision réversible)

Le retrait de `moe` de **btp.optionnels** (en plus de conseil, comme demandé en 1C) fait que **25 marchés** passent de 3 presets à **ingénierie seul** : un profil **BTP** ne les verra plus via ce code.

- **Cohérent métier** : la MOE architecture/urbanisme = études/conception, pas travaux → rattachement BTP discutable.
- **Si on préfère garder la visibilité BTP** : re-ajouter `moe_architecte_urbanisme` à `btp.veille.domaines_optionnels` → les 25 redeviendraient `[ingenierie, btp]`. Changement d'une ligne, trivialement réversible.

## Non-régression

- `moe_architecte_urbanisme` seul → `[ingenierie]` ✓
- `energie_amo_etudes` → `[energie_renouvelable, ingenierie]` ✓ (typo corrigé, code désormais reconnu)
- `btp.veille.domaines_optionnels` après = `[ingenierie_structure_genie_civil, energie_renovation_thermique]` (moe retiré) ✓
- Suites de tests : vertes (dce_finder, qualifier_dce).

## Détail (10 premiers marchés)

| Marché | Avant | Après |
|---|---|---|
| BOAMP-26-57084 | ingenierie, btp, conseil | ingenierie |
| BOAMP-26-56335 | ingenierie, btp, conseil | ingenierie, btp |
| BOAMP-26-57176 | ingenierie, btp, conseil | ingenierie |
| BOAMP-26-56496 | ingenierie, btp, conseil | ingenierie |
| BOAMP-26-57073 | ingenierie, btp, conseil | ingenierie |
| BOAMP-26-56588 | ingenierie, btp, conseil | ingenierie |
| BOAMP-26-57080 | ingenierie, btp, conseil | ingenierie |
| BOAMP-26-57223 | ingenierie, btp, conseil | ingenierie |
| BOAMP-26-57132 | ingenierie, btp, conseil | ingenierie |
| BOAMP-26-56774 | ingenierie, btp, conseil | ingenierie |
