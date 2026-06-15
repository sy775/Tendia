# Comparaison avant / après — Chantier 1 (re-extraction prompts par preset)

_Mesure de l'impact du Chantier 1 (1A→1G + complément IT) sur la qualité et la
couverture des briefs. AVANT = `baseline_briefs_avant_chantier1.md` (briefs du
10/06). APRÈS = briefs re-extraits avec presets enrichis, routage 1D et versioning 1E._

> Détail qualité (blocs hors-sujet, champs sectoriels, titre↔synthèse) sur
> l'échantillon de 10 marchés : voir `audit_validation_chantier1.md`.

## 1. Couverture de la re-extraction

| Run | Marchés | Coût | Durée | Note |
|---|---|---|---|---|
| 1F — validation échantillon | 10 | 4,17 € | — | go/no-go qualité |
| 1G — re-extraction full (plafond 30 €) | 68 | 27,61 € | ~… | 1/preset garanti, gisement décroissant, géants >500 Mo écartés |
| 1G+ — complément IT (plafond 6 €) | 7 (/8) | 2,55 € | 24 min | 56097 en échec (parse JSON après 2 retries) |
| **Total briefs Chantier 1 (`prompts_versions`)** | **90** | **~36 €** | — | cumul `_meta.cout_eur` |

- **11 DCE géants écartés** (>500 Mo, extraction texte trop lente / tronquée à 400k) :
  56326, 56341, 56451, 56469, 56576, 56588, 56774, 56968, 57058, 57132, 57133.
  → traitement manuel ultérieur.
- **1 échec** : `BOAMP-26-56097` (IT, 13 Mo SSI) — l'appel LLM aboutit (~9 min)
  mais la sortie JSON échoue au parse 2× → marché non re-extrait. À reprendre.

## 2. Répartition par preset — AVANT vs APRÈS

| Preset (principal) | AVANT (baseline) | APRÈS (Chantier 1) |
|---|---|---|
| btp | 19 | 52 |
| ingenierie | 15 | 9 |
| conseil | 7 | 10 |
| formation | 5 | 1 |
| it | 4 | 4 |
| energie_renouvelable | 0 | 0 |
| hors-périmètre | 52 | 14 |
| **Total mesuré** | **102** | **90** |

> Les totaux diffèrent : la baseline couvrait 102 briefs figés au 10/06 ; l'APRÈS
> compte les 90 briefs effectivement re-extraits en Chantier 1 (les autres ne sont
> pas encore repassés ou sont des DCE géants écartés).

## 3. Complément IT — le « gisement IT » re-qualifié par le DCE complet

Le run 1G full avait produit **IT=0** : les marchés du gisement IT avaient été
téléchargés/complétés **après** ce run. Le complément 1G+ les a re-extraits. Constat
clé : **avec le DCE complet, la classification se corrige** (la classification
initiale s'appuyait sur les maigres métadonnées BOAMP).

| Marché | Avant (gisement) | Après re-extraction | Coût |
|---|---|---|---|
| 56329 | it | **it** ✓ | 0,54 € |
| 56462 | it | **it** ✓ | 0,36 € |
| 56642 (66 Mo) | it | ingénierie (fluides/climatique) | 0,48 € |
| 56164 | it | hors-périmètre (`autre`) | 0,43 € |
| 56170 | it | hors-périmètre (`autre`) | 0,28 € |
| 56547 | it | hors-périmètre (`autre`) | 0,33 € |
| 57263 | it | hors-périmètre (`autre`) | 0,14 € |
| 56097 | it | **échec extraction** | — |

- IT « réel » en Chantier 1 après complément = **4** (56329, 56462 + 56627, 56760
  déjà faits en 1F).
- Enseignement : l'« IT=0 » du 1G n'était pas qu'un trou de couverture — **la
  majorité du gisement IT n'est pas de l'IT** une fois le DCE lu. Le sur-classement
  IT venait de la pauvreté des métadonnées BOAMP. La re-extraction full DCE améliore
  donc aussi la **précision de classification**, pas seulement le remplissage des champs.

## 4. Qualité (rappel échantillon 1F)

- Blocs sectoriels hors-sujet : **67 → 0** sur l'échantillon (cible 0) ✅
- Incohérences titre↔synthèse : **0** ✅
- Hors-périmètre : bloc neutre `caracteristiques_metier` au lieu de l'union polluante ✅
- Champs sectoriels IT (`qualifications_it` iso_27001/hds…) remplis quand le RC le
  mentionne ✅

## 5. Coût

- ~**0,42 €/marché** en moyenne (vs estimation initiale 0,13 €) — les gros DCE
  tronqués à 400k = ~100k tokens en entrée dominent le coût.
- Complément IT : 2,55 € pour 7 marchés (moy. 0,36 €/marché, profil plus léger que
  l'échantillon de validation).

## 6. Reste à faire

- Reprendre **56097** (échec parse JSON) — éventuellement en réduisant la troncature
  ou en isolant le bloc fautif.
- Traiter les **11 DCE géants** écartés (manuel / pipeline dédié).
- Repasser les presets sous-couverts si besoin (formation=1, enr=0).
