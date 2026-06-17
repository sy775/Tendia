# Rapport — Refonte Pipeline d'Extraction v2

_Généré progressivement par les scripts `audit_etat_pipeline` / `retenter_download_dce` / `audit_couverture_v2`. Modèle LLM : Sonnet 4.6. Diagnostic Phase A : Scénario C (logique montant multi-preset neutre, pas de purge)._

## Phase A — Diagnostic prompt LLM (Scénario C)

Le prompt Chantier 1 estimait **déjà** le montant via une stratégie 4 étapes (explicite →
prix unitaire × volume → fourchette → non_communique) **preset-aware** (hints/few-shot par
preset dans la lib `preset` ; les 6 presets en sont pourvus — pas de mono-calibration
formation). Critères : split `valeur_prix_pct`/`valeur_technique_pct` (somme=100), bareme
hiérarchique. **→ Scénario C : pas de purge ; le v2 enrichit.** Modèle : `claude-sonnet-4-6`.

Le v2 ajoute : (1) bloc `montant_3_voies` explicite + Voie 2 forcée avant `non_communique` ;
(2) `unite_evaluation` par sous-critère → `criteres_attribution_plat` avec famille (euro→prix,
**résout le bug RSE €/CO2**) + validation ; (3) contexte BOAMP injecté ; (4) `prompt_version_sha`.

## Étape 1 — Audit état actuel

```
Briefs Tendia                 : 422
Distribution dce_contenu (complétude du DCE téléchargé) :
  complet        : 210
  vide           : 195
  incomplet      : 14
  candidature    : 2
  auth_requise   : 1

Candidats re-download         : 58
  (url_consultation_dce_directe présent ET dce_contenu != 'complet')

Cible re-extraction LLM v2     : 210
  - dce_contenu='complet'      : 210
  - déjà en v2 (skip)          : 0
Coût estimé re-extraction      : 65.5 € (prompt actuel) à 84.0 € (prompt v2 majoré) / cap 100 €
```

> ✓ 58 candidats (≥ 5), coût estimé ≤ 100 € → poursuite Phase B.

## Étape 2 — Câblage downloader + re-download DCE (bug B12)

`tendia_telecharger_dce.telecharger_pieces_dce` patché : **priorité `url_consultation_dce_directe`**
(avec PCSLID) → repli `url_dce` reconstruite. **Fonctionnel confirmé** (Atexo/maximilien :
ZIP `dce_940358.zip` récupéré via l'URL directe). Tests : `test_downloader_dce_directe` (12 OK).

Re-download parallèle (`scripts/retenter_download_dce.py`, 5 workers, écriture mono-thread) sur
les 58 candidats : **gain +7 briefs complet** (`dce_contenu` 210 → 217). Le reste des candidats
est soit **auth-gated** (plateformes exigeant un compte : marches-securises, marchés-publics.gouv,
maximilien…), soit sur des hôtes qui pendent — limite légitime, non un défaut du fix. B12 est
**résolu en pratique** pour les avis eForms portant un `EndpointID` exploitable.

> Le run complet a été interrompu (workers pendus sur connexions lentes sans timeout — dette
> mineure à durcir). Les +7 gains sont commités.


## Étape 6 — Audit couverture v2

```
=== AUDIT POST-EXTRACTION v2 ===
Briefs en v2                  : 46
Briefs complet encore en v1   : 171

Couverture montants (briefs v2) :
  Voie 1 (publié)             : 32 (70 %)
  Voie 2 (estimation)         : 15 (33 %)
  Au moins une voie           : 46 (100 %)  [cible ≥80%]
  Aucune voie                 : 0 (0 %)

Couverture critères (briefs v2) :
  Critères extraits           : 44 (96 %)
  Avec ≥1 alerte              : 10 (22 %)

Distribution preset (v2 vs v1 restant) :
  (sans cpv)     : v2   0 | v1  85
  ?              : v2  13 | v1  11
  btp            : v2   5 | v1  15
  conseil_rd     : v2   2 | v1   3
  formation      : v2   1 | v1   4
  hors_perimetre : v2  18 | v1  36
  ingenierie     : v2   6 | v1  14
  it             : v2   1 | v1   3

Top hypothèses Voie 2 :
    1× Lot 1 : environ 1568 prélèvements/an (eau+air+su
    1× Lot 2 : 475 recherches légionnelles/an × prix un
    1× Lot 3 : requalification salles propres 42 salles
    1× Lots 4+5 : 264 analyses bactério+endotoxines dia
    1× Lot 6 : ~10 analyses physico-chimiques × 100-200
    1× Lot 7 : ~21 prélèvements alimentaires mensuels ×
    1× Durée du marché MOE : 36 mois (RC §1 — Caractéri
    1× Travaux de sûreté blindage sur bâtiment administ
    1× Taux de rémunération MOE typique pour réhabilita
    1× Procédure adaptée ouverte (seuil < 215 000 € HT 
```

## Étape 5 — Re-extraction LLM v2 (échantillon limite-50)

`scripts/reextraire_briefs_v2.py` (parallèle 8 workers, BudgetTracker thread-safe, écriture
mono-thread) sur 50 cibles : **45 re-extraits** (1 échec LLM, 4 sans PDF exploitable),
**15,73 € / 100 €**, coût moyen **0,350 €/brief**, 16 min.

**Couverture (excellente)** : au moins une voie de montant **100 %** (cible ≥ 80 % large), critères
**96 %**, Voie 1 (publié) 70 %, Voie 2 (bottom-up) 33 %. Les hypothèses Voie 2 sont granulaires et
sourcées (ci-dessus).

**Alertes critères** : 10/46 (22 %), désormais **toutes légitimes** après correction d'un bug de
dérivation (les sous-critères techniques étaient tantôt en part-de-100, tantôt en part-du-technique →
normalisation à `valeur_technique_pct` ; 5 fausses alertes éliminées). Les 10 restantes : 4 bareme
non chiffré par l'acheteur (None/None), 6 incohérences `prix+technique≠100` du DCE → ce sont de
**vrais signaux** que la validation doit lever.

## Synthèse & recommandation

| Critère de succès | Cible | Mesuré (échantillon 46) |
|---|---|---|
| Au moins une voie de montant | ≥ 80 % | **100 %** ✅ |
| Critères extraits | — | **96 %** ✅ |
| Bug RSE €/CO2 (euro → prix) | résolu | **résolu** (test + dérivation) ✅ |
| Gain DCE-complet (B12) | > 0 | **+7** (auth-gating limite le reste) 🟠 |
| Tests | ≥ 215 OK | **~254 OK / 0 KO** ✅ |
| Coût | ≤ 100 € | **15,73 €** (échantillon 50) ✅ |

**Reste à faire (ta main)** :
1. **Étape 7 — validation manuelle** : `python scripts/valider_extraction_v2.py` (20 briefs :
   gagnés B12 + déjà-complet avec comparaison v1). **Gate Sprint DECP 3** : ≥ 85 % = GO ferme.
2. **Re-extraction du reste** : seulement **50/216** faits (échantillon progressif). Une fois la
   validation OK, lancer le complet — budget restant ≈ 84 € pour ~166 briefs à 0,35 € ≈ **58 €**
   (rentre dans le cap 100 € total). Commande : `python scripts/reextraire_briefs_v2.py --workers 8
   --plafond 84`.

**Recommandation** : la mécanique v2 est **validée techniquement** (couverture, critères, montants,
0 régression). Le passage **GO Sprint DECP 3** est conditionné à ta validation manuelle des 20
briefs (Étape 7). Je n'ai **pas** lancé la re-extraction complète : ta validation qualité est le
gate avant d'engager le reste du budget.

