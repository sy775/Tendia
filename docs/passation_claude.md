# Passation à Claude — Projet Tendia

**Tu es le prochain Claude qui va aider Younes sur Tendia.**
**Ce document est ton briefing.** Lis-le entièrement avant de répondre à Younes.

**Date de la passation** : 12 juin 2026, fin de Sprint 2bis + A + B
**Version** : 2.0 (post matching V2 multi-secteurs)
**Sprints clôturés** : 2, 2bis (Sujets 1+2, Phases 3a/3b/3c), A (profil socle+BTP), B (matching V2)
**État système** : stable et productif, 3 premiers verdicts `pertinent` end-to-end sur profil BTP démo IDF

---

## 1. Qui est Younes

### Profil et style

- Développeur solo, fondateur du projet Tendia
- **Très haute exigence sur la qualité architecturale**. Préfère systématiquement le travail propre à la vitesse. Si tu lui proposes un raccourci, il le refusera et préférera la solution propre. Plusieurs fois pendant le Sprint 2, il a corrigé Claude qui voulait shortcut.
- **Délégation intelligente** : valide explicitement chaque étape. Quand il dit "ok go", c'est qu'il a lu, compris et validé. Tu peux exécuter avec confiance.
- **Validation par retour terrain** : Younes ne valide pas une archi sur la théorie. Il lance, il observe, il décide. Toujours fournir un moyen empirique de tester.
- **Communication directe** : peu de formules, va à l'essentiel. Bonne expression écrite mais brève. Pas de "merci d'avance", pas de "ce serait gentil de". Just business.
- **Bilingue FR/EN** : code et docs en français, mais commentaires techniques OK en anglais. Préfère les noms FR (`preset`, `analyse`, `marche`).

### Patterns techniques observés

- **PowerShell sur Windows** : Younes lance ses commandes en PowerShell. Bug récurrent : les f-strings avec `\"` à l'intérieur cassent. Toujours écrire des scripts Python externes plutôt que des `python -c "..."` longs.
- **Backup avant sprint** : Younes backupe systématiquement `data\tendia.db` avant chaque modification structurelle. Toujours lui suggérer le backup.
- **Test empirique** : Il préfère 1 marché test ciblé avant de lancer un backfill complet. Toujours proposer un test ciblé d'abord.
- **Budget conscient** : Il a un budget LLM modeste. Toujours estimer le coût AVANT d'agir.

### Vision business

- Tendia est un projet **commercialisable**. Younes pense en SaaS multi-tenant.
- Cible : PME secteurs variés (formation, BTP, IT, conseil, ingénierie, EnR)
- Modèle : abonnement mensuel par organisme client
- Concurrence : Vecteur Plus, Dispofi, MyMarchespublics — différenciation par profondeur IA
- Pas encore de client. Phase actuelle : préparation au démarchage.

---

## 2. État du projet au 12 juin 2026 (post Sprint 2bis + A + B)

### Architecture actuelle

Tendia est un **fork d'Apptia** (mai 2026), généralisé pour servir N secteurs.

**Pipeline complet** :
```
BOAMP → marches (422 actuels)
   ↓
Classification IA (Sprint 2) → classifications_ia (421/422)
   ↓                             ↑
   ↓                          [Sprint 2bis Sujet 1] sync depuis sortie LLM
   ↓
Matching IA strict → scores_matching (275 pertinents / 422)
   ↓
Téléchargement DCE → ~90 marchés briefables (35% de couverture)
   ↓
Brief LLM complet → briefs_extraits (102 actuels)
   |   [Sprint 2bis] : routage classif IA → schéma sectoriel ciblé
   |                   + filtre anti-hallucination post-extraction
   |                   + 3 schémas sectoriels enrichis (IT, conseil, ingénierie)
   ↓
Calibration prix bottom-up → extractions_calibrees
   ↓
Matching organisme × marché V2 (Sprint B)
   |   [Sprint A] : profil socle commun + profils_sectoriels par preset
   |   [Sprint B] : motifs universels + sectoriels BTP (qualibat, RGE,
   |                corps_metier, types_ouvrages, capacité)
   ↓
UI : Dashboard (strict) + Explorer (exhaustif) + Fiche marché + Profil

```

### Ce qui marche

- Classification IA Haiku 4.5 : 100% couverture, raffinée par re-classification post-brief (Sprint 2bis Sujet 1)
- 6 presets sectoriels actifs (formation, énergie, BTP, IT, conseil, ingénierie)
- **Routage classif IA → schéma LLM ciblé** (Sprint 2bis) : brief BTP ne reçoit plus de schéma formation parasite
- **Filtre anti-hallucination** (Sprint 2bis Sujet 2) : les blocs sectoriels hors-schéma sont supprimés post-parsing JSON
- **Schémas IT/conseil/ingénierie enrichis** (Phase 3b) : 8→17 (IT), 8→14 (conseil), 9→15 (ingénierie) champs
- **Rendu MD preset-aware** (Phase 3a) : plus de section "Publics cibles : Non applicable" pour un marché BTP
- Architecture mutualisée : marchés/classifications/briefs partagés, profils per-client
- **Profil organisme multi-secteurs** (Sprint A) : socle commun + spécialisations par preset
- **Matching V2 multi-secteurs** (Sprint B) : motifs universels (preset, thématique, géo via dept/région, capacité) + sectoriel BTP (qualibat go/no-go, RGE, corps_metier par tokens, types_ouvrages, capacité chantier)

### Ce qui ne marche pas (ou pas encore)

- **Pas de profils sectoriels IT/conseil/ingénierie** (Sprint C à faire — modèle BTP est OK)
- **Pas d'évaluateurs matching sectoriels** pour IT/conseil/ingénierie/EnR (Sprint C — stubs en place)
- **Couverture DCE 35%** : plateformes DEMATIS (captcha) et achatpublic (login) bloquent 51% du volume
- **Calibration top-down** : DECP non exploité aujourd'hui
- **Pas d'authentification multi-tenant** : 1 base = 1 utilisateur
- **UI orientée dev** : pas assez "commercial-ready"
- **5 marchés hors-preset** (assurance, entretien, env) : pas de stratégie ferme — décision à prendre (filtre strict vs preset générique services_supports)
- **Bug `enrichir_complet.py`** : filtre `--id $_ --force` n'honore pas vraiment `--force`, certains marchés non-pertinents sont skippés malgré l'argument explicite
- **3 marchés avec mismatch DCE/métadonnée** (55964, 56061, 56063 historiques) : le DCE téléchargé ne correspond pas au marché BOAMP — chantier d'investigation séparé

### Chiffres importants à connaître

| Métrique | Valeur |
|---|---:|
| Marchés en base | 422 |
| Classifiés IA | 421 (100%) |
| Pertinents (6 presets) | 275 (65%) |
| Briefs complets | 102 |
| Briefs avec verdict `pertinent`+ (profil BTP démo IDF) | **3** (57070, 56539, 56378) |
| Coût total LLM depuis le début | ~25-30€ (incl. Sprint 2bis Phase 3c ~3€) |
| Coût mensuel régime | ~30€/mois (1 client) |
| Coût marginal par client supplémentaire | ~12€/mois |

---

## 3. Sprints récents

### Sprint 2 — Nouvelle architecture (juin 2026) ✅

- ✅ Module `tendia_classification.py`
- ✅ Taxonomie enrichie à 56 domaines
- ✅ 4 nouveaux presets MVP : BTP, IT, Conseil, Ingénierie
- ✅ Refactor `analyse.py` : matching IA strict + fallback keyword
- ✅ Route `/explorer` + filtres famille/sous-domaine/zone/recherche
- ✅ Mode `--mutualise` et `--prioriser` dans `enrichir_complet.py`
- ✅ Audit prompt `llm_extract.py` neutralisé (vestiges France Travail)

### Sprint 2bis — Anti-pollution multi-secteurs (12 juin 2026) ✅

Diagnostic : un brief BTP recevait tous les schémas sectoriels (formation, énergie, conseil, IT, ingénierie) → le LLM remplissait n'importe quoi, créant 8+ blocs hallucinés par brief.

**Sujet 1 — Sync classif IA depuis sortie LLM**. Après brief, la classif IA initiale (Haiku) est remplacée par celle ré-évaluée par le LLM (Sonnet) qui a lu le DCE complet. Log `🔄 Classif IA mise à jour : [...] → [...]`. Validé in vivo en Phase 3c (6 marchés re-classifiés, dont 2 corrections majeures de faux positifs).

**Sujet 2 — Anti-hallucination** :
- (a) Règle prompt explicite ajoutée en tête de RÈGLES IMPORTANTES dans `llm_extract.py` : "ne génère QUE les blocs présents dans le schéma fourni"
- (b) Filtre post-parsing JSON `_filtrer_hallucinations(data, codes_presets)` dans `llm_extract.py` qui supprime tout bloc top-level non listé dans `_CHAMPS_UNIVERSELS_BRIEF` (12 champs universels) + les blocs sectoriels des presets ciblés. Helper `preset.blocs_sectoriels_pour_presets(codes)`.

**Phase 3a** — `_synthese_brief` (rendu MD) preset-aware : ne génère plus de section "Publics cibles : Non applicable" pour un brief BTP.

**Phase 3b** — schémas IT/conseil/ingénierie enrichis. IT : 8→17 champs (méthodologie, jalons, livrables_par_phase, jours_consultant_par_profil...). Conseil : 8→14. Ingénierie : 9→15 (livrables_par_phase, coordinations, organigramme...).

**Phase 3c** — regen massive : 23 briefs identifiés pollués, 18 effectivement régénérés (5 skippés par bug `enrichir_complet.py`). Coût ~3€. 6 classifs IA mises à jour. Validation in vivo : 3 JSON audités → 0 pollution détectée.

### Sprint A — Profil organisme socle + BTP (12 juin 2026) ✅

Le profil organisme était formation-only. Refactor multi-secteurs validé par Younes : socle commun + spécialisations par preset (option C).

- `presets/_socle_profil_organisme.json` : 12 propriétés universelles (identite, presets_couverts, profils_sectoriels, zones_intervention, mots_cles_catalogue, capacite_globale, certifications, references_globales, valeurs_engagements, contraintes, _meta)
- `presets/btp/_schema.json` : 9 propriétés BTP (qualifications, corps_de_metier, types_ouvrages, capacite_chantiers, rh_chantier, moyens_materiels, references_chantiers, types_clients_publics, pratiques_specifiques)
- `organisme.py` refait (~460 lignes) : `charger_actif`, `profil_sectoriel(code)`, `schema_socle/sectoriel`, `template_socle/sectoriel`, `valider_profil` (validation maison, sans jsonschema), `supprimer_profil`. Backward compat legacy formation (`lire_profil`, `schema_vide`, `champs_remplis`, `est_format_legacy`, `DR_FRANCE_TRAVAIL`, `PRESTATIONS_FRANCE_TRAVAIL`)
- `init_profil.py` refait (~175 lignes) : `--status`, `--template <preset>`, `--depuis <fichier>`, `--purger --confirmer`, `--force`
- `data/exemples/profil_btp_demo.json` : profil démo "EXEMPLE BTP SAS" 75 ETP, 14.5M€ CA, IDF+HDF, 7 codes Qualibat, RGE, MASE, amiante SS4, ISO 9001+14001, 10 corps de métier, 5 types d'ouvrages, 4 références chiffrées

### Sprint B — Matching V2 multi-secteurs (12 juin 2026) ✅

- `matching.py` V2.1 (~770 lignes) avec routage automatique legacy vs multi-secteurs
- 4 motifs universels : `preset_compatibilite` (-50/-30/+20), `thematique` (mots-clés catalogue +25/+15), `geographie` (+25 dept direct, +15/+12 region via DEPARTEMENT_VERS_REGION 101 codes), `capacite` financière (+10/-10/-20)
- 6 évaluateurs sectoriels BTP : `btp_qualibat` (verrou -50 robuste aux strings texte libre), `btp_rge`, `btp_amiante`, `btp_corps_metier` (match par tokens), `btp_types_ouvrages` (match par tokens), `btp_capacite_chantier`
- Stubs Sprint C pour ingenierie/conseil/it/EnR
- Synergie +10 si preset+thematique+geo alignés
- Signature backward-compat : `evaluer(organisme, marche, brief=None, presets_marche=None)`
- 4 appelants patchés pour passer brief : `tendia_matcher.py:247`, `tendia_veille.py:156`, `tendia_ui.py:283`, `tendia_dce.py:163`
- `tester_matching.py` (script démo `--top N` et `--details <id>`)
- 3 fixes critiques post V2 : (1) btp_qualibat ne crash plus sur string libre ("Non précisé dans le RC..."), (2) ACHETEUR_VERS_DEPARTEMENT étendu aux 13 organismes nationaux IDF (OFPRA, CNAM, ministères...), (3) match `corps_metier`/`types_ouvrages` par tokens partagés au lieu de substring

**Résultat in vivo** : sur 422 marchés et profil BTP démo IDF :
- 1 `tres_pertinent` (57070 Rénovation ECS Champs Philippe 92, score 75)
- 2 `pertinent` (56539 CPAM Tours score 70, 56378 OFPRA Paris score 55)
- 35 `a_verifier` (8.3%)
- 384 `non_pertinent` (91%)

C'est le **premier passage `pertinent` end-to-end** sur la base réelle de Younes.

---

## 3bis. Sprint en cours / Prochain sprint

**Aucun sprint actif au moment de cette passation.** Le système est dans un état stable et productif. Plusieurs chantiers possibles selon les priorités :

### Sprint C — Étendre à ingénierie, conseil, IT, EnR (~3-4h par preset)

Reproduire le modèle BTP pour les autres presets :
- Créer `presets/<code>/_schema.json` (profil sectoriel)
- Implémenter `_eval_sectoriel_<code>(profil_sec, brief)` dans `matching.py`
- Créer `data/exemples/profil_<code>_demo.json`
- Le pattern est tracé par BTP, copier-coller-adapter.

Priorité Younes : ingénierie > conseil > IT > EnR (selon plan commercial).

### Chantiers non-prioritaires mais reportés

- **Patch `enrichir_complet.py`** : honorer `--id` en bypass du filtre `pertinent` (~10 min). Sans ça, on ne peut pas régénérer un brief spécifique si le profil ne le considère plus comme pertinent.
- **Bug DCE/métadonnée mismatch** sur 3 marchés historiques (55964, 56061, 56063) : DCE téléchargé ne correspond pas au marché BOAMP. Investigation séparée.
- **Bandeau LIGHT** sur briefs incomplets dans l'UI (~10 min).
- **Décision 5 hors-preset** : 5 marchés (assurance, entretien, environnement) sortent de la taxonomie. 3 options : (a1) filtre strict skip ; (a2) preset générique `services_supports` ; (a3) status quo. À trancher.
- **Rectorats par académie** : ajouter `rectorat de Paris → 75`, `rectorat de Versailles → 78`, etc. dans `ACHETEUR_VERS_DEPARTEMENT` (matching.py). Ferait passer 56774 (AMO rectorat IDF, score 47) à `pertinent`.
- **Affiner profil BTP démo** par Younes avec ses vraies données prospect.
- **Calibration top-down DECP** (Chantier C-V1 d'origine) — reporté.

Voir `docs/cadrage_strategique.md` pour la roadmap complète.

---

## 4. Conventions de Younes — RESPECTE-LES

### Code

- **Pas de hardcoding sectoriel en Python.** Tout passe par `_preset.json`. Younes a expressément rejeté les approches type "if marche.cpv.startswith('80'):  # formation" — c'est une heritage Apptia qu'on a éliminé.
- **Backward compatibility** : les nouveaux schémas JSON doivent supporter les anciens en lecture (fallback null/empty).
- **Idempotence partout** : toute commande doit pouvoir être relancée sans risque.
- **CLI avec garde-fous** : toujours `--dry-run`, `--limite`, `--max-cout`, `--force`.
- **Coût LLM tracé** : chaque appel LLM stocke `_meta.cout_eur` pour traçabilité.

### Communication

- **Brièveté** : Younes va à l'essentiel. Sois aussi bref que possible sans perdre en clarté.
- **Pas de blah-blah marketing** ("Excellente décision !", "C'est une approche brillante !"). Direct.
- **Présenter les choix** en clair avec ton vote argumenté. Younes valide rapidement.
- **Estimer toujours** : coût, durée, effort, impact. Donne des chiffres.
- **Tester avant industrialiser** : propose 1 cas test, puis le batch. Pas l'inverse.

### Fichiers

- Suffixe `_preset.json` pour les configs presets (PAS `_domaine.json` — vestige Apptia)
- Préfixe `tendia_` pour les modules principaux (`tendia_sourcing.py`, `tendia_classification.py`, etc.)
- Dossiers presets : nom du preset SANS préfixe (`presets/btp/`, pas `presets/preset_btp/`)
- Tous les scripts ont une docstring d'usage en tête

### LLM

- **Haiku 4.5** (`claude-haiku-4-5`) pour classification et tâches simples
- **Sonnet 4.6** (`claude-sonnet-4-6`) pour briefs et calibrations
- Toujours mentionner le modèle utilisé dans `_meta.modele`

---

## 5. Pièges à éviter

### Piège 1 — PowerShell et f-strings Python

```powershell
# BUG : PowerShell mange les \" à l'intérieur de Python
python -c "print(f'{val:\"format\"}')"
```

**Solution** : pour toute logique Python complexe, créer un fichier `.py` externe que Younes lance avec `python script.py`. Pas de `python -c "long stuff"`.

### Piège 2 — Le profil n'est pas chargé en mode multi-client

Le module `organisme.py` lit `data/profil_organisme.json` par défaut. Avec `tester_profils.py`, on bascule entre plusieurs profils. **Toujours vérifier quel profil est actif** avant un test.

### Piège 3 — Les briefs sur disque vs SQLite

Historiquement, les briefs étaient sur disque (`data/extractions_calibrees/*.json`). Maintenant ils sont dans SQLite (`briefs_extraits`). Le code lit les DEUX sources pour backward compat. **Ne pas casser ce double lookup.**

### Piège 4 — `taxonomie.json` vs `_taxonomie_domaines.json`

Apptia avait `taxonomie.json` (vestige). Tendia utilise `_taxonomie_domaines.json` (préfixe `_`). **Toujours utiliser le nouveau.**

### Piège 5 — `_preset.json` vs `_domaine.json`

Apptia utilisait `_domaine.json`. Tendia utilise `_preset.json`. Le code lit les deux pour backward compat mais **les nouveaux fichiers doivent être `_preset.json`**.

### Piège 6 — Younes lance les commandes manuellement

Tendia n'a pas (encore) de pipeline automatique. Younes lance chaque commande à la main. **Ne pas supposer que les choses tournent en cron.**

### Piège 7 — La base SQLite est mutualisée mais pas multi-utilisateur

Les collections `marches`, `classifications_ia`, `briefs_extraits` sont conçues pour servir N clients. Mais il n'y a pas de couche d'auth ou d'isolation **aujourd'hui**. C'est un sprint futur (Chantier E). Aujourd'hui : 1 base = 1 utilisateur.

### Piège 8 — Le mode mutualisé briefe TOUS les secteurs

`enrichir_complet.py --mutualise` ignore le preset actif et briefe tous les marchés briefables (~80-100). Younes l'a explicitement validé : c'est le modèle SaaS, base mutualisée. Ne pas le restreindre par preset.

### Piège 9 — Le matching IA prend la priorité sur le keyword

Dans `analyse.py`, si une classification IA existe pour un marché, elle SUPPLANTE le matching keyword. Le keyword est gardé en fallback pour les marchés non encore classifiés. **Toujours s'assurer que la classification IA passe en premier.**

### Piège 10 — `qualifications_requises.qualibat` peut être du texte libre

Le LLM peut sortir une string descriptive ("Non précisé dans le RC...") au lieu d'une liste de codes Qualibat à 4 chiffres. Si ton code itère sans guard, il itère caractère par caractère et produit des erreurs absurdes (vu en V2 : -50 sur "N, o, n,  , p, r, é..."). **Toujours vérifier `isinstance(v, list)` ET filtrer les codes à 4 chiffres** avant de comparer.

### Piège 11 — `acheteur_nom` n'a souvent pas le département

Pour les acheteurs nationaux IDF (OFPRA, CNAM, CNAF, Sénat, ministères...), le nom ne contient ni département ni région. La détection du département se fait via `ACHETEUR_VERS_DEPARTEMENT` (heuristique manuelle). Si tu ajoutes un nouveau pattern, **mets `None` pour les cas ambigus** (ex: "rectorat" qui dépend de l'académie).

### Piège 12 — `presets_marche=[]` ne signifie pas "hors taxonomie"

Un marché peut avoir `classifications_ia` rempli mais `presets_marche=[]` si le code domaine n'est pas mappé à un preset (ex: `entretien_proprete_locaux`, `services_environnement_analyses`, `transport_logistique_vehicules`, `fourniture_materiel`). Le matching V2 retourne alors un motif neutre (0) pour `preset_compatibilite`. Ce n'est PAS un bug — c'est juste qu'on n'a pas (encore) de preset pour ces familles. Décision 5 hors-preset pendante.

---

## 6. Décisions architecturales clés à connaître

### Décision 1 — Classification IA remplace matching keyword

**Date** : Sprint 2 (juin 2026)
**Pourquoi** : Le matching keyword/CPV avait un taux de faux positifs énorme (0% d'alignement formation/EnR avant Sprint 2). Le LLM Haiku 4.5 à 0.004€/marché donne une classification fiable.
**Conséquence** : `scores_matching` contient un champ `mode_decision` ∈ {`classification_ia`, `keyword_fallback`}.

### Décision 2 — Architecture mutualisée

**Date** : Sprint 2
**Pourquoi** : Modèle SaaS multi-tenant cible. Coût marginal par client nul si les briefs sont mutualisés.
**Conséquence** : `enrichir_complet.py --mutualise` briefe TOUT, indépendamment du preset.

### Décision 3 — Mode strict par défaut sur le dashboard

**Date** : Sprint 2
**Pourquoi** : Le matching keyword remontait 80% de faux positifs (formation : 20 keyword vs 13 réellement pertinents). En strict, on affiche que les marchés où le LLM est d'accord.
**Conséquence** : Le dashboard est plus court mais plus pertinent. Younes peut explorer le reste via Explorer.

### Décision 4 — Templates par preset, pas méta-schéma

**Date** : Sprint 2 (à exécuter dans Chantier A)
**Pourquoi** : Younes a explicitement préféré la simplicité (1 template Jinja par preset) à la flexibilité (méta-schéma générique avec moteur de formulaires). Effort 2h30 vs 5h, complexité bien moindre.
**Conséquence** : `ui/templates/profil/<preset>.html` à créer pour chaque preset, pas de moteur générique.

### Décision 5 — DECP en requête à la volée (pas d'ingestion massive)

**Date** : Sprint 2 (en cours)
**Pourquoi** : Ingestion massive DECP = ~250k attributions = ~500 Mo + ~1000€ de classification. Trop. Requête en live = 0€ et scalable jusqu'à ~5000 utilisateurs.
**Conséquence** : `decp_consolidee.py` à généraliser pour requête ciblée par CPV/montant/dates.

### Décision 6 — Pas de classification IA de DECP

**Date** : Sprint 2
**Pourquoi** : DECP = marchés attribués, pas de candidature possible. La classification ne sert que si on veut filtrer par domaine fin (Vague 2 plus tard). 1000€ pour rien aujourd'hui.

### Décision 7 — Sprint DEMATIS reporté

**Date** : Sprint 2
**Pourquoi** : Captcha confirmé, effort 1-2 jours. Pas critique avant 1er prospect. À traiter quand le besoin est là.

### Décision 8 — Prompt LLM sectoriellement neutre

**Date** : Sprint 2
**Pourquoi** : `llm_extract.py` contenait 2 mentions "France Travail" dans le prompt système (vestige Apptia). Pour un marché BTP ou IT, ces mentions biaisaient potentiellement le LLM et étaient factuellement fausses pour les autres secteurs.
**Conséquence** : Prompt LLM 100% neutre désormais ("RC de marchés publics" au lieu de "RC France Travail"). Si tu ajoutes du contenu au prompt système, **vérifie absolument qu'il est applicable à TOUS les presets** (formation, BTP, IT, conseil, ingénierie, énergie).

### Décision 9 — Briefing priorisable par preset

**Date** : Sprint 2
**Pourquoi** : Younes veut briefer en priorité les presets de prospects ciblés (ex: énergie avant BTP avant formation). En mutualisé sans priorité, l'ordre serait alphabétique = inefficace pour le démarrage commercial.
**Conséquence** : `enrichir_complet.py --prioriser <preset>` (cumulable) ordonne les candidats. Pattern : `--prioriser energie_renouvelable --prioriser btp --prioriser formation` → énergie d'abord, puis BTP, puis formation, puis le reste.

### Décision 10 — Routage classif IA → schéma sectoriel ciblé

**Date** : Sprint 2bis (12 juin 2026)
**Pourquoi** : Avant le routage, un brief BTP recevait l'union de tous les schémas sectoriels (formation + énergie + conseil + IT + ingénierie). Le LLM remplissait n'importe quoi (publics_cibles formation pour un marché BTP, volumes_techniques EnR pour un marché conseil), produisant 8+ blocs hallucinés par brief.
**Conséquence** : `llm_extract.extraire_via_llm()` reçoit en argument la liste des presets cibles (résolus depuis `classifications_ia[marche_id].domaines_metier` via `preset.presets_pour_domaines()`) et envoie au LLM uniquement les schémas concernés. Si aucun preset n'est résolu (hors-taxonomie), fallback sur union complète (qui reste sous-optimal — voir Décision 5 hors-preset à trancher).

### Décision 11 — Filtre anti-hallucination post-LLM

**Date** : Sprint 2bis Sujet 2 (12 juin 2026)
**Pourquoi** : Le routage Décision 10 suffit dans 95% des cas, mais le LLM peut occasionnellement halluciner un bloc d'un autre schéma (mémoire des examples du prompt, classif initiale grossière, etc.). Il faut un filet de sécurité code.
**Conséquence** : Après parse JSON du LLM, `llm_extract._filtrer_hallucinations(data, codes_presets)` supprime tout bloc top-level qui n'est ni dans `_CHAMPS_UNIVERSELS_BRIEF` (12 champs universels : synthese_marche, domaines_metier, raison_classification, bareme_notation, montant_marche, revision_prix, alertes_prix, references_exigees, lots, calendrier, alertes_candidat, points_differenciants_attendus, + `_appel_llm`, `_meta`) ni dans `preset.blocs_sectoriels_pour_presets(codes_presets)`. Helper extraction par regex `^  "([a-z_]+)":\s*[\{\[]` sur `bloc_schema_specifique`.

### Décision 12 — Sync classif IA depuis sortie LLM (backflow)

**Date** : Sprint 2bis Sujet 1 (12 juin 2026)
**Pourquoi** : La classif IA initiale est faite par Haiku 4.5 sur le titre+objet (~200 tokens). Quand Sonnet 4.6 brief le DCE complet (~50k tokens), il a une vision beaucoup plus précise et peut re-classifier correctement. Garder la classif Haiku obsolète pénaliserait inutilement le routage Décision 10 sur les rebriefs futurs.
**Conséquence** : `tendia_extraire.py` met à jour `classifications_ia[marche_id]` après écriture du brief, si les codes domaines de la sortie LLM diffèrent de ceux stockés. Log `🔄 Classif IA mise à jour : [...] → [...]`. Validé in vivo : 6 marchés re-classifiés en Phase 3c, dont 2 corrections majeures de faux positifs (56463, 56493 qui n'étaient pas du tout BTP).

### Décision 13 — Profil organisme socle + sectoriels (Option C)

**Date** : Sprint A (12 juin 2026)
**Pourquoi** : Le profil organisme était formation-only (champs `publics_cibles`, `thematiques_metiers`, `directions_regionales_couvertes`). Pour un organisme BTP ou IT, ces champs n'avaient pas de sens. 3 options ont été comparées : (A) un seul schéma fourre-tout avec tous les champs nullables — illisible. (B) un schéma par preset complet — duplication. **(C) socle commun universel + profils sectoriels** par preset — propre.
**Conséquence** : Structure `{identite, presets_couverts, profils_sectoriels: {btp: {...}, it: {...}}, zones_intervention, mots_cles_catalogue, capacite_globale, certifications, references_globales, ...}`. Format legacy formation conservé en backward compat (détecté via présence de `thematiques_metiers` / `directions_regionales_couvertes` au top-level). Younes a explicitement validé : **pas d'admin UI POC, fichiers JSON édités à la main**.

### Décision 14 — Matching V2 avec routage legacy/multi-secteurs

**Date** : Sprint B (12 juin 2026)
**Pourquoi** : Conserver l'ancien code formation (Qualiopi, DR, prestations_maitrisees) tout en ajoutant le matching multi-secteurs sans casser les profils legacy existants.
**Conséquence** : `matching.evaluer()` détecte le format profil (`_est_format_legacy_formation()`) et route vers `_evaluer_legacy()` (V1 préservé) ou `_evaluer_v2()` (nouveau). Signature publique inchangée : `evaluer(organisme, marche, brief=None, presets_marche=None)`. Les 4 appelants (`tendia_matcher.py`, `tendia_veille.py`, `tendia_ui.py`, `tendia_dce.py`) ont été patchés pour passer le brief, mais fonctionnent même sans (mode dégradé sans scoring sectoriel).

---

## 7. Comment réagir aux situations courantes

### Situation : Younes pose une question stratégique

Pas de blabla. Réponds en 3 parties :
1. **Réponse directe** à la question
2. **Implications** chiffrées (coût, effort, risque)
3. **Ta recommandation** argumentée

Exemple : "DECP, est-ce faisable ?"
→ Pas : "Bonne question Younes ! C'est tout à fait possible et ouvre des perspectives intéressantes."
→ Plutôt : "Oui. Le module existe (decp_consolidee.py, hardcodé FT). 3 options : ingestion massive (250k, 1000€), requête live (3-4h dev, 0€/mois), cache hybride (4-5h dev). Mon vote : option 2, MVP scalable jusqu'à 5000 utilisateurs."

### Situation : Younes propose une décision

Évalue honnêtement. S'il a raison : confirme avec arguments. S'il a tort ou oublie un angle : pousse-le. Younes n'aime pas la flatterie, il aime la rigueur.

### Situation : Bug ou erreur dans son terminal

1. Diagnostique vite (1 ligne de Python pour vérifier l'état)
2. Identifie la cause (pas une supposition, un fait)
3. Propose le fix
4. Re-vérifie après application

### Situation : Younes valide rapidement ("ok go", "ok")

Il a vraiment validé. Exécute la commande/le code prévus, livre, passe à la suite.

### Situation : Younes hésite ou pose plusieurs questions

Il réfléchit stratégiquement. Ne pas précipiter. Reformule les options, pèse-les, donne ton vote argumenté, laisse-le décider.

### Situation : Coût ou risque potentiel

Toujours signaler. Younes apprécie la transparence. "Cette commande coûtera ~X€" / "Risque de Y" est mieux que "Lance-la sans y penser".

---

## 8. Ressources et docs

### Docs principaux

- **`docs/cadrage_strategique.md`** : Roadmap business, chantiers, coûts, stratégie commerciale
- **`docs/documentation_technique.md`** : Architecture interne, modules, conventions
- **`docs/README.md`** : Démarrage rapide, commandes essentielles
- **`docs/passation_claude.md`** : Ce document
- **`docs/journal.txt`** : Historique des sprints précédents

### Fichiers de configuration importants

- `.env` : `ANTHROPIC_API_KEY`
- `presets/_taxonomie_domaines.json` : 56 domaines, v1.1
- `presets/<code>/_preset.json` : 6 presets actifs
- `data/profil_organisme.json` : profil actif
- `data/profils/profil_<code>.json` : profils tests
- `budget.json` : kill-switch budget LLM

### Données

- `data/tendia.db` : ~80 Mo SQLite, mutualisée
- `data/dce_archives/<id>/` : DCE téléchargés (PDF originaux)
- `data/extractions_calibrees/<id>.json` : calibrations sourcées

---

## 9. Avant de répondre à Younes

**Checklist avant ton premier message** :

- [ ] Tu as lu `docs/cadrage_strategique.md` (roadmap business)
- [ ] Tu as lu `docs/documentation_technique.md` (architecture)
- [ ] Tu as lu ce document (passation Claude)
- [ ] Tu sais quel sprint est en cours
- [ ] Tu sais ce qui marche et ce qui ne marche pas
- [ ] Tu as une idée des conventions et préférences de Younes

**Ne demande PAS à Younes** :
- "Peux-tu m'expliquer ton projet ?" → Tu sais déjà.
- "Quelle est ton architecture ?" → Doc technique.
- "Quelles sont tes priorités ?" → Roadmap.
- "Comment lancer Tendia ?" → README.

**Demande à Younes** :
- L'état précis du sprint en cours (ce qui a tourné depuis ta passation)
- Les nouveaux blocages identifiés
- Les nouvelles décisions stratégiques

---

## 10. Mots de la fin

Tendia est un beau projet. Younes est rigoureux, a une vraie vision, et travaille proprement. Ton job est de l'aider à **livrer un produit commercialisable** sans perdre en qualité architecturale.

Si tu as un doute sur une décision : **demande**. Younes préfère 2 messages clairs à 1 message confus.

Si tu vois une opportunité d'amélioration architecturale : **propose**. Mais argumente toujours coût/effort/bénéfice.

Si tu identifies une dette technique : **signale**. Mais en respectant le timing (pas pendant un sprint critique).

**Bonne continuation. Tendia mérite de réussir.**

---

*Document mis à jour à chaque sprint. Dernière révision : 12 juin 2026 — Sprint 2 nouvelle architecture.*
