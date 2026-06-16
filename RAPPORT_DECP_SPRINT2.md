# Rapport Sprint DECP 2 — classification preset des marchés DECP

_Généré par `scripts/decp_rapport_sprint2.py`. Modèle LLM : Haiku 4.5. Exploration CPV : `data/decp_cpv_distribution.csv`._

## Audit final classification

```
=== AUDIT FINAL CLASSIFICATION DECP ===
Total marchés DECP         : 142 735
Classifiés                 : 142 735 (100.0 %)
  - via préfiltrage CPV   : 127 685
  - via LLM Haiku         : 15 050
Non classifiés (budget)    : 0

Distribution finale par preset :
  - btp            :  50 978 (35.7 %)
  - ingenierie     :  11 948 (8.4 %)
  - it             :   7 127 (5.0 %)
  - conseil_rd     :   2 776 (1.9 %)
  - formation      :   2 312 (1.6 %)
  - enr            :     443 (0.3 %)
  - hors_perimetre :  67 151 (47.0 %)
  - non_classifie  :       0 (0.0 %)

Cohérence vs audit Sprint 1 (distribution CPV brute) :
  btp          attendu ~34.0 % -> effectif 35.7 %
  ingenierie   attendu ~8.1 % -> effectif 8.4 %
  it           attendu ~3.4 % -> effectif 5.0 %
  enr          attendu ~1.3 % -> effectif 0.3 %
  formation    attendu ~1.4 % -> effectif 1.6 %

Confiance LLM moyenne      : 0.89
Marchés LLM confiance <0.6 : 17
Coût total LLM             : 6.80 € / 50.00 €
```

✓ Aucun écart > 5 pts vs l'audit Sprint 1 — distribution cohérente.

## Validation manuelle (Étape 4)

Échantillon stratifié de 50 marchés via `scripts/decp_valider_classif.py` (7/preset, assouplissement conseil_rd, 50/50 cpv/llm). **À valider manuellement par Younes** (mode interactif o/n/?) — seuil **≥ 85 % = GO ferme** pour Sprint DECP 3. Un dump revue est dans `data/validation_decp_sample_*.csv`.

### Pré-validation indicative (automatique — à confirmer manuellement)

En attendant la passe manuelle, jugement des 50 marchés (objet + CPV → preset correct ?) :
**≈ 86-90 % corrects (43-45/50)**, équilibré CPV (~86 %) / LLM (~86 %). Erreurs repérées :

| # | Marché (extrait) | Pipeline | Devrait être | Cause |
|---|---|---|---|---|
| 5 | MOE « phase exécution » (CPV 45211000) | btp | ingenierie | acheteur a mis un CPV travaux sur une maîtrise d'œuvre |
| 29-31 | CPV 79952000 (cérémonie remise de diplômes, vitrines métiers) | formation | hors_perimetre | LLM piégé par « diplômes / métiers » (= événementiel) |
| 42 | CPV 71314100 (fourniture d'électricité / gaz naturel) | enr | hors_perimetre | sous-code `71314`→enr trop large (c'est de la fourniture d'énergie) |
| (33, 36) | communication (CPV 80540) ; rénovation énergétique bâtiment | formation / enr | discutable | cas-limites |

> ⚠️ **Indicatif** (jugement automatique, PAS la validation formelle). La **validation manuelle de Younes** (`python scripts/decp_valider_classif.py`, saisie o/n/?) reste le juge officiel du seuil ≥ 85 %. Dump revue : `data/validation_decp_sample_*.csv`.

## Recommandation go/no-go Sprint DECP 3

- **≥ 85 %** précision → GO ferme.
- **70-85 %** → GO conditionnel (raffiner le prompt LLM sur les presets fautifs).
- **< 70 %** → STOP (prompt trop court ou préfiltrage CPV trop agressif).


**Recommandation : GO (conditionnel) pour Sprint DECP 3.**

La pré-validation indicative (~86-90 %) franchit le seuil de 85 %, et la distribution est cohérente avec l'audit Sprint 1 (aucun écart > 5 pts). Le coût LLM (6,80 €) est très en-deçà du plafond (50 €), 0 marché non classifié pour cause de budget. **3 raffinements** à acter avant/pendant DECP 3 — ils corrigeraient ~5 des erreurs observées :

1. **Prompt LLM** — préciser que les **services événementiels** (CPV 79952xxx : cérémonies, salons, vitrines métiers, remises de diplômes) **≠ formation** → `hors_perimetre`. C'est le piège LLM le plus net (mots « diplômes / métiers »).
2. **Mapping CPV** — restreindre `71314`→enr aux seuls codes d'**ingénierie** EnR ; `71314100` (fourniture d'électricité / gaz) = `hors_perimetre`. Vérifier de même `0930x` (fourniture d'électricité générale ≠ renouvelable).
3. **Règle MOE** — objet contenant « maîtrise d'œuvre » / « MOE » → `ingenierie` **même si CPV = 45xxx** (les acheteurs collent souvent un CPV travaux sur une MOE).

> La confirmation **ferme** reste conditionnée à la **validation manuelle de Younes** (`python scripts/decp_valider_classif.py`, ≥ 85 %). Si elle ressort < 85 %, appliquer les raffinements ci-dessus et reclasser les seuls presets fautifs avant de relancer la passe.

