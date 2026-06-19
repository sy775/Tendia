# Validation Chantier 1 — échantillon de 10 marchés re-extraits

_Comparaison AVANT (briefs du 10/06, backup `backups/briefs_avant_chantier1_*.json`) vs APRÈS (re-extraction avec presets enrichis + routage 1D)._

## 1. Tableau comparatif

| Marché | Presets | Blocs HS avant→après | synthèse | barème | titre↔synthèse | versioning |
|---|---|---|---|---|---|---|
| BOAMP-26-56712 | btp | 9→**0** | ✓ | ✓ | ✓ | ✓ |
| BOAMP-26-56525 | btp | 0→**0** | ✓ | ✓ | ✓ | ✓ |
| BOAMP-26-56419 | btp | 0→**0** | ✓ | ✓ | ✓ | ✓ |
| BOAMP-26-56494 | conseil | 10→**0** | ✓ | ✓ | ✓ | ✓ |
| BOAMP-26-56627 | it | 12→**0** | ✓ | ✓ | ✓ | ✓ |
| BOAMP-26-56760 | it | 12→**0** | ✓ | ✓ | ✓ | ✓ |
| BOAMP-26-56303 | HORS-PÉRIM. | 12→**0** | ✓ | ✓ | ✓ | ✓ |
| BOAMP-26-56439 | HORS-PÉRIM. | 12→**0** | ✓ | ✓ | ✓ | ✓ |
| BOAMP-26-56995 | btp,energie_renouvelable | 0→**0** | ✓ | ✓ | ✓ | ✓ |
| BOAMP-26-56364 | btp | 0→**0** | ✓ | ✓ | ✓ | ✓ |

**Blocs hors-sujet : 67 → 0** sur l'échantillon.

## 2. Remplissage des champs structurés sectoriels (après)

| Marché | Preset | Champ clé | Rempli ? |
|---|---|---|---|
| BOAMP-26-56712 | btp | qualifications_requises.qualibat | — (peut-être absent du RC) |
| BOAMP-26-56525 | btp | qualifications_requises.qualibat | — (peut-être absent du RC) |
| BOAMP-26-56419 | btp | qualifications_requises.qualibat | — (peut-être absent du RC) |
| BOAMP-26-56494 | conseil | qualifications_conseil | ✓ |
| BOAMP-26-56627 | it | qualifications_it (iso_27001/hds/...) | ✓ |
| BOAMP-26-56760 | it | qualifications_it (iso_27001/hds/...) | ✓ |
| BOAMP-26-56303 | HORS-PÉRIM. | (bloc neutre caracteristiques_metier) | ✓ présent |
| BOAMP-26-56439 | HORS-PÉRIM. | (bloc neutre caracteristiques_metier) | ✓ présent |
| BOAMP-26-56995 | btp | qualifications_requises.qualibat | — (peut-être absent du RC) |
| BOAMP-26-56364 | btp | qualifications_requises.qualibat | — (peut-être absent du RC) |

## 3. Hors-périmètre (fix 1D)

- **BOAMP-26-56303** : blocs sectoriels présents = AUCUN ✓ ; bloc neutre caracteristiques_metier = ✓
- **BOAMP-26-56439** : blocs sectoriels présents = AUCUN ✓ ; bloc neutre caracteristiques_metier = ✓

## 4. Gros DCE (test tronquage 400k)

- **BOAMP-26-56995** : synthèse ✓, barème ✓, tokens_in=141037, coût=0.5327€
- **BOAMP-26-56364** : synthèse ✓, barème ✓, tokens_in=160077, coût=0.5263€

## 5. Critères go/no-go

- Blocs hors-sujet : 67 → **0** (cible 0) — ✅
- Incohérences titre↔synthèse : **0**  (cible 0) — ✅
- BTP avec qualibat rempli : **0/5** — **VÉRIFIÉ CORRECT** : les RC de ces 5 marchés BTP ne mentionnent AUCUN code Qualibat (grep = 0 occurrence ; le LLM remplit `qualifications_requises.description` en l'expliquant, ex. « Le DCE ne mentionne pas explicitement de qualifications Qualibat »). Le bloc `qualifications_requises` EST présent et correctement renseigné (assurance RC/décennale notée). Critère « ≥80% quand le RC le mentionne » → satisfait (dénominateur = 0 ici). — ✅
- Hors-périmètre sans bloc sectoriel : voir §3
- Coût réel échantillon : **4.17 €** (10 marchés, ~0.42€/marché — gros DCE coûteux)

⚠️ **Coût** : ~0.42€/marché >> estimation initiale 0,13€ (les gros DCE tronqués à 400k = ~100k tokens). Extrapolé à ~195 marchés : potentiellement **81€** si même profil (mais l'échantillon sur-représente les gros DCE).