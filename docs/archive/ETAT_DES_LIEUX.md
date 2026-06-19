# État des lieux — pipeline Tendia (17/06/2026)

Point complet après la session de QA. Branche `feat/decp-sprint-3` (commits **locaux**,
push GitHub bloqué côté permissions). Source unique de vérité pour reprendre.

---

## A. ✅ RÉGLÉ cette session (committé)

### Extraction LLM v2
| Sujet | Commit |
|---|---|
| Refonte v2 : 3 voies montant + critères stricts (famille prix/technique) + parallélisation | `898f376` |
| Normalisation dérivation critères plat (fausses alertes « somme ») | `cc0609c` |
| Surrogates UTF-8 (crash gros DCE) + fourchette Voie 2 **mono-dimension** (plus de fourchettes énormes) | `bc7eb37` |
| **Quota journalier cumulatif** (déblocage re-extraction) + streaming + max_tokens 32000 | `d5ced4e` |
| Synchro `montant_marche ← montant_3_voies` (l'UI affiche enfin le montant) | `bf3d135` |
| Mode `--reextract-voie2` + préservation backup v1 | `2bf9ef7` |

### UI / fiche marché
| Sujet | Commit |
|---|---|
| Fourchette montant dans le KPI + durée (`volumes.duree_marche_mois`) + `publics_cibles` dict brut | `af4b270` |
| Retrait « Calibration LLM » (formation-biaisée, doublon Voie 2) | `909ce7a` |
| Classification : libellés taxonomie + typos `energia→energie` tolérées | `adac420` |
| Bloc ingénierie/MOE enrichi (livrables/coordinations/indices affichés) | `fc676d8` |

### DCE
| Sujet | Commit |
|---|---|
| Re-qualif des **74 faux-complet** (RC seul) → `incomplet` | `a632705` |

### Enrichissement BOAMP (antérieur, base du tout)
| 31 champs depuis l'avis (SIREN, montant, URL DCE, lots…) | `17aac4a` |

**Données en base** : 182 briefs v2, 88 fourchettes Voie 2 resserrées, montants synchronisés,
codes domaine typo normalisés. ~**135 € LLM** dépensés cette session.

---

## B. 🔧 À RÉGLER avant le run end-to-end

| # | Problème | Vérifié | Bloquant | Effort |
|---|---|---|---|---|
| **P1** | **Routage download** : le wrapper `telecharger_pieces_dce` ne déclenche PAS le `completeDownload` Atexo/achatpublic → ne ramène que le RC (1 pièce). **Testé : les downloaders dédiés marchent en direct** (zips 2,5 Mo Atexo, 20,8 Mo achatpublic). | ✅ | 🔴 **OUI** | moyen, 0 € |
| **P2** | **`qualifier_dce` faux-complet** : qualifie sur les *types* de pièces (lus dans le RC), pas les fichiers réels → 74/217 faux-complet. Données re-qualifiées (P1 fait), mais la **logique** non corrigée → récidive aux futurs crawls. | ✅ | 🟠 oui (récurrence) | moyen, 0 € |
| **P3** | **Normalisation preset à l'extraction** : `energia`→ non normalisé dans `_resoudre_presets`/`presets_pour_domaines` → mauvais schéma (10 briefs). Codes stockés normalisés (fait), mais pas la résolution. | ✅ | 🟠 futurs | petit, 0 € |
| **P4** | **Sous-extraction MOE** : `livrables_par_phase` / `taux_remuneration_moe_pct` restent vides malgré schéma+règle. Durcir l'instruction. **À valider sur 1-2 briefs avant batch.** | ✅ | 🟡 qualité | petit |
| **P5** | **`url_consultation_dce_directe` PLACE = page de recherche** (le lien UI tombe sur la recherche). Mais `id`+`orgAcronyme` SONT dedans → construire l'URL consultation propre. | ✅ | 🟡 cosmétique | petit, 0 € |
| **P6** | **~10 incomplet hors Atexo/achatpublic** (marches-publics.info, e-marchespublics…) → cas par cas. | partiel | 🟢 | variable |
| **P7** | **Flag `est_europeen` sur-compte** : matche « Marchés entre 90k€ et seuils **européens** » comme JOUE → 91% au lieu de ~45%. | ✅ | 🟢 mineur | petit, 0 € |

---

## C. 📦 Données à re-traiter (après fixes)

| Lot | Nb | Action |
|---|---|---|
| Incomplet **récupérables** (Atexo 46 + achatpublic 33) | **~79** | re-download (P1) → re-qualif → re-extraction v2 |
| Briefs au **mauvais preset_utilise** | **10** | re-extraction (après P3) |
| Briefs **« light »** (avis seul, anciens) | **35** | décider : passage v2 ? |
| Incomplet **non-récupérables** auto | **~10** | P6 cas par cas |

⚠️ Overlap : les 74 faux-complet ⊂ les 89 incomplet ; ~79 récupérables. Total à re-extraire ≈ **80-90 briefs** une fois les vrais DCE récupérés (~30 €).

---

## D. 📊 Chiffrages actés (cadrage)

- **Volume BOAMP** : ~**7 800 avis ouverts/mois** (compté API 30j : 7 790 `APPEL_OFFRE`).
- **Entonnoir** : 64% matchent un preset → **32% arrivent à l'extraction full** (in-preset ET avec DCE).
- **Coût mensuel** (tous presets, BOAMP, mutualisé, pipeline réglée) : **~900 €/mois (~10,8 k€/an)**.
  - Aujourd'hui (avant P1, 24% extraits) : ~660 €/mois.
  - Sans filtre preset (43%) : ~1 200 €/mois (inutile).
- **TED** : ~doublon de la portion JOUE → **inutile pour le volume FR**. Garder pour expansion UE.
- **MAPA < 90 k€** : quasi absents de BOAMP (732/mois) → nécessiteraient un **crawl plateformes** (autre chantier).
- **Crawl actuel** = 2 jours seulement (422), tous acheteurs, avis ouverts.

---

## E. 🎯 Ordre recommandé du run unique

1. **Fixes code 0 €** : P1 (routage download) → P2 (qualifier honnête) → P3 (preset typo) → P5 (URL) → P7 (est_europeen).
2. **Durcir prompt P4** + valider sur 1-2 briefs (~1 €).
3. **Re-download** des ~79 récupérables (réseau, ~0 € LLM).
4. **Re-qualif** auto (nouveaux dossiers complets).
5. **Re-extraction v2** des nouveaux complet + 10 mauvais preset (~30-40 €, cap dur).
6. **Validation finale** (échantillon).
7. *(Plus tard)* élargir le crawl (2 → 30 jours) sur pipeline saine.

→ **P1 est la priorité absolue** : sans lui, re-download inutile (ne ramène que le RC).

---

## F. ❓ Décisions en attente (Younes)

1. **P6 (~10 marchés)** : me donner le lien « accéder à la consultation » si l'avis n'a pas la réf, sinon → « incomplet · accès à vérifier ».
2. **35 briefs light** : passage v2 dans le run, ou on les laisse ?
3. **Périmètre futur** : BOAMP seul (~900 €/mois) acté ? MAPA/plateformes = phase ultérieure ? TED = phase UE ?
