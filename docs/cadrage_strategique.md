# Tendia — Document de cadrage stratégique

**Date** : 12 juin 2026
**Statut** : MVP technique opérationnel avec matching V2 multi-secteurs validé end-to-end, en phase de préparation à la commercialisation
**Auteur** : Younes (concepteur) + Claude (assistant technique)

---

## 1. Vision produit

### 1.1 Ce qu'est Tendia

Tendia est une **plateforme SaaS de veille et d'analyse de marchés publics français**. Elle automatise la chaîne complète : du sourcing des appels d'offres BOAMP, en passant par la classification, l'extraction des exigences et le calibrage prix, jusqu'à la qualification d'éligibilité pour un organisme candidat.

C'est un **fork élargi d'Apptia**, qui ciblait uniquement le secteur formation pour France Travail. Tendia généralise l'architecture pour servir N secteurs (formation, énergie, BTP, IT, conseil, ingénierie) et N organismes.

### 1.2 Promesse de valeur

Pour un organisme candidat à des marchés publics :

> "Tendia trouve les marchés qui vous correspondent, vous explique en 30 secondes ce que l'acheteur attend, calibre le prix attendu sur des données réelles, et vous dit si vous êtes éligible."

Trois bénéfices concrets :
1. **Gain de temps** : pas besoin de lire 300 pages de DCE pour comprendre un marché
2. **Décision rapide** : "candidater ou pas" en quelques secondes
3. **Confiance prix** : calibrage triangulé sur des marchés réels DECP

### 1.3 Modèle économique cible

SaaS multi-tenant à abonnement mensuel par organisme client :
- **Base mutualisée** : marchés, classifications IA, briefs LLM = coût marginal nul par client
- **Profils per-organisme** : configuration sectorielle propre à chaque client
- **Pricing indicatif** : 200-500€/mois selon volume et fonctionnalités (à valider via prospects)

---

## 2. Photo de l'existant (12 juin 2026)

### 2.1 Architecture en place

```
BOAMP (sourcing) → 422 marchés en base
       ↓
Classification IA Haiku 4.5 (1.93€) → 421 classifiés sur 56 domaines métier
       ↓
6 presets sectoriels actifs : btp, conseil, énergie_renouvelable, formation, ingénierie, it
       ↓
Matching IA strict (Sprint 2) → 275 marchés pertinents (65% de la base)
       ↓
DCE téléchargé pour les marchés avec URL exploitable → ~90 marchés briefables
       ↓
Brief LLM COMPLET (Sonnet 4.6, ~0.15€/marché) → 13 briefs actuels
       ↓
Calibration prix bottom-up sectorielle → opérationnelle
       ↓
Matching d'éligibilité → fonctionnel sur profil formation (à généraliser)
       ↓
UI Dashboard + Explorer (Sprint 2) → opérationnels
```

### 2.2 Forces actuelles

| Domaine | Statut | Note |
|---|---|---|
| Sourcing BOAMP | ✅ Opérationnel | ~1000 marchés/mois ingestion |
| Classification IA | ✅ Excellente | 100% couverture, taxonomie 56 domaines |
| Couverture sectorielle | ✅ Large | 6 presets couvrent ~65% du marché public français |
| Architecture mutualisée | ✅ Conçue | Base SQLite mutualisable multi-clients |
| Calibration bottom-up | ✅ Stable | 6 baremes sectoriels configurés |
| Coût LLM | ✅ Maîtrisé | ~0.15€/brief complet, ~16€/mois en régime |

### 2.3 Faiblesses identifiées

| Domaine | Sévérité | Problème |
|---|---|---|
| Couverture DCE | 🔴 Critique | Seuls 35% des marchés ont un DCE téléchargeable (51% bloqués par plateformes mortes type DEMATIS) |
| Calibration top-down | 🟠 Important | DECP non exploité actuellement → confiance prix "faible" |
| Profil organisme | 🟠 Important | Hardcodé formation → impossible à utiliser pour BTP/IT/etc. |
| UI dashboard | 🟡 Modéré | Manque de hiérarchisation, lecture en N+1 actions pas claire |
| Multi-tenant | 🟡 Modéré | Pas d'authentification, 1 base = 1 utilisateur |
| Veille concurrentielle | 🟡 Modéré | Existe mais désuète, basée sur DECP FT uniquement |

---

## 3. Chantiers identifiés

Quatre chantiers principaux à mener, hiérarchisés par valeur produit.

### Chantier A — Profils sectoriels paramétrables 🔴 Critique

**Pourquoi** : Sans profil adapté au preset (BTP, IT, etc.), Tendia ne peut pas faire de matching éligibilité pour ces secteurs. Tu ne peux pas démarcher un prospect BTP avec un formulaire orienté Qualiopi.

**État actuel** : Profil hardcodé formation. Schéma rigide.

**Objectif** : 1 schéma de profil par preset, formulaire dédié, matching éligibilité fonctionnel sur les 6 presets.

**Effort estimé** : 4-5h

**Détail des sous-tâches** :
1. Définir un schéma profil minimal commun (identité, finances, zone) — 30 min
2. Étendre les 4 nouveaux presets avec leur bloc `clauses_eligibilite` (Qualibat, ISO 27001, OPQIBI, inscription Ordre) — 1h
3. Refactor `organisme.py` pour stocker un dict par preset — 1h
4. Templates Jinja par preset (`profil/btp.html`, `profil/it.html`, etc.) — 1h30
5. Adaptation `matching_exigences.py` pour règles par preset — 1h
6. Tests : créer 6 profils tests (un par preset) et vérifier le verdict éligibilité — 30 min

**Bénéfice direct** : tu peux démarcher un prospect dans n'importe quel secteur couvert.

---

### Chantier B — Couverture DCE étendue 🔴 Critique

**Pourquoi** : 51% des marchés sont inaccessibles (DEMATIS captcha, achatpublic login). Sans DCE, pas de brief LLM. Sans brief, pas de calibrage ni d'analyse complète.

**État actuel** : 35% de réussite globale sur le téléchargement DCE. PLACE (gouv.fr) marche bien (73%), e-marchespublics aussi (71%). DEMATIS 0% (captcha confirmé).

**Objectif** : passer de 35% à 65%+ en débloquant DEMATIS et achatpublic.

**Effort estimé** : 1-2 jours par plateforme à débloquer

**Détail des sous-tâches** :

**B1 — Sprint DEMATIS** (`marches-publics.info`, 82 marchés en base, 0% actuel)
- Captcha présent au téléchargement DCE
- Solutions :
  - Option 1 : intégrer un solveur de captcha payant (2Captcha, ~3€/1000 captchas)
  - Option 2 : workflow "dépôt manuel" : Younes télécharge à la main, dépose dans un dossier, Tendia traite
  - Option 3 : Playwright avec slot mode (humain résout le captcha occasionnellement)
- Effort : 1-2 jours pour Option 1 ou 3, quelques heures pour Option 2
- Bénéfice : +82 marchés briefables = +20% de couverture absolue

**B2 — Sprint achatpublic** (`achatpublic.com`, 46 marchés en base, 0%)
- Login requis, pas de captcha
- Solution : compte de service Tendia avec login automatique (cookies persistés)
- Risque : violation des CGU possibles (à vérifier)
- Effort : 1 jour
- Bénéfice : +46 marchés briefables

**B3 — Optimisation plateformes existantes**
- Améliorer le taux PLACE de 73% à 90%+
- Identifier les patterns d'échec sur e-marchespublics (29% d'échec)
- Effort : 1 jour
- Bénéfice : +20-30 marchés supplémentaires

**Priorisation** : commencer par B1 (DEMATIS) avec Option 2 (manuel) pour valider la valeur, puis Option 1 (solveur captcha) si traction.

**Bénéfice global** : couverture DCE passe de 35% à 65%+, soit ~270 marchés briefables vs ~94 aujourd'hui.

---

### Chantier C — Exploitation DECP (calibrage triangulé) 🟠 Important

**Pourquoi** : Aujourd'hui ton calibrage prix est bottom-up seul, confiance "faible". Avec DECP triangulé : "sourcé sur 18 marchés réels", confiance "moyenne/haute". C'est l'argument commercial #1.

**État actuel** : Module `connecteurs/decp_consolidee.py` existe mais hardcodé France Travail (vestige Apptia).

**Objectif** : Calibration triangulée fonctionnelle sur les 6 presets.

**Effort estimé** : 3-4h (Vague 1, MVP)

**Stratégie en 3 vagues** :

**Vague 1 — Calibrage triangulé en live (MAINTENANT, MVP)**
- Refactor `decp_consolidee.py` pour enlever hardcode FT (1h)
- Nouvelle fonction `chercher_comparables(cpv, montant_min, montant_max, annees)` qui requête DECP en live (1h)
- Intégration dans `llm_calibration.py` pour alimenter le top-down (1h)
- Adaptation UI marché pour afficher "calibré sur N marchés DECP réels" (30 min)
- Effort : 3-4h
- Coût récurrent : 0€/mois (API data.gouv.fr gratuite)
- Bénéfice : confiance calibration "moyenne/haute" sur tous les marchés briefés

**Vague 2 — Classification DECP ciblée (PLUS TARD si traction)**
- Quand 2-3 clients payants
- Classifier uniquement DECP des CPV pertinents pour les presets installés
- Coût Haiku : ~500-800€ one-shot
- Bénéfice : comparables ultra-pertinents par domaine fin + veille concurrentielle par domaine
- Effort : ~8h (script de batch + monitoring)

**Vague 3 — Cache local hybride (FUTUR si scale)**
- Si >5000 utilisateurs / >50k calibrations/mois
- Cache requêtes DECP locales avec TTL 24h
- Effort : ~3h
- Bénéfice : latence négligeable, robustesse aux pannes API data.gouv.fr

**Recommandation** : Vague 1 immédiatement, Vagues 2 et 3 quand le métier le justifie.

---

### Chantier D — Refonte UI et expérience produit 🟡 Important

**Pourquoi** : Aujourd'hui l'UI est fonctionnelle mais "outil dev". Pour vendre, il faut une expérience prospect lisible en 2 minutes.

**État actuel** : Dashboard + Explorer + fiche marché en place (Sprint 2). Manque de hiérarchie visuelle, beaucoup d'informations brutes.

**Objectif** : Expérience prospect qui démontre la valeur Tendia en 90 secondes.

**Effort estimé** : 1-2 jours

**Détail des sous-tâches** :

**D1 — Dashboard "Top opportunités"** (4-6h)
- Affichage premium des 5 marchés les plus pertinents du moment
- Score d'opportunité combiné : pertinence preset × score éligibilité × proximité échéance
- Cards visuelles avec montant estimé, jours restants, verdict éligibilité, raison
- Bénéfice : démonstration produit immédiate

**D2 — Fiche marché commerciale** (4-6h)
- Refonte de `marche.html` pour mettre en avant les insights métier
- Top de la page : verdict éligibilité + montant estimé + comparables DECP
- Sections progressives : synthèse → exigences clés → calibration prix → DCE détaillé
- Print/PDF export pour partager à un commercial
- Bénéfice : outil utilisable en RDV prospect

**D3 — Explorer enrichi** (2-3h)
- Filtres avancés : montant, durée, type marché, acheteur récurrent
- Vue cartographique par région (déjà en preset.acheteur_vers_zone)
- Export CSV pour analyses externes
- Bénéfice : outil de prospection commerciale

**D4 — Onboarding et création profil guidée** (4-6h)
- Wizard de création profil organisme (choix preset → questionnaire adapté)
- Tutoriel intégré "Comment lire un brief Tendia"
- Démo pré-remplie pour démos prospect
- Bénéfice : un prospect peut tester Tendia en 5 min sans assistance

**Priorisation** : D1 et D2 en premier (impact démonstration), D3 et D4 après validation marché.

---

### Chantier E — Multi-tenant et déploiement (transverse) 🟡 Modéré

**Pourquoi** : Pour commercialiser, il faut un déploiement SaaS multi-tenant.

**État actuel** : Application locale, 1 utilisateur, pas d'auth.

**Objectif** : Déploiement cloud avec auth, 1 base mutualisée, N profils organismes.

**Effort estimé** : 1-2 semaines

**Détail des sous-tâches** :

1. Auth : intégration de Flask-Login ou Auth0 (1 jour)
2. Migration SQLite → PostgreSQL (1 jour)
3. Séparation : marchés/classifications/briefs mutualisés vs profils per-organisme (1 jour)
4. Déploiement : VPS ou Render/Railway (1 jour)
5. Monitoring : logs, métriques, alertes coût LLM (1 jour)
6. RGPD : politique de confidentialité, CGU, hébergement données (1 jour)

**Quand le faire** : seulement quand 1 prospect a signé une LOI ou 1er paiement. Pas avant.

---

### Chantier F — Industrialisation pipeline (transverse) 🟢 Confort

**Pourquoi** : Aujourd'hui Younes lance manuellement chaque étape (ingestion, classification, enrichissement). À industrialiser pour qu'un client n'ait rien à faire.

**État actuel** : Scripts CLI Python, lancement manuel.

**Objectif** : Pipeline automatique quotidien.

**Effort estimé** : 2-3 jours

**Détail des sous-tâches** :

1. Planificateur quotidien (cron ou APScheduler) : ingestion BOAMP → classification → enrichissement (1 jour)
2. Notifications email pour nouveaux marchés pertinents par profil (1 jour)
3. Monitoring : alertes si pipeline échoue (1 jour)

**Quand le faire** : avant le 1er client payant, ou après le 1er pour montrer la valeur (selon traction).

---

## 4. Roadmap proposée

### Sprint clôturé (12 juin) — Foundations commerciales

| # | Chantier | Effort | Statut |
|---|---|---|---|
| 0 | Backfill classification IA 410 marchés | 21 min | ✅ Fait (1.93€) |
| 0 | Création 4 nouveaux presets BTP/IT/Conseil/Ingénierie | 30 min | ✅ Fait |
| 0 | Audit prompt `llm_extract.py` (vestiges FT) | 15 min | ✅ Fait |
| 0 | Flag `--prioriser` enrichissement par preset | 15 min | ✅ Fait |
| 2bis | Sujet 1+2 anti-hallucination + sync classif IA | 2-3h | ✅ Fait |
| 3a | Rendu MD preset-aware | 30 min | ✅ Fait |
| 3b | Schémas IT/conseil/ingénierie enrichis | 1h | ✅ Fait |
| 3c | Regen massive briefs pollués | 1h + 3€ | ✅ Fait (18/23) |
| A | Profil organisme socle + sectoriel BTP | 3-4h | ✅ Fait |
| B | Matching V2 multi-secteurs + 3 fixes critiques | 3-4h | ✅ Fait |
| C-V1 | Calibrage triangulé DECP | 3-4h | ⏳ Reporté |

**Livrable sprint atteint** : Tendia avec couverture 6 secteurs, briefs mutualisés sans pollution, profil organisme multi-secteurs, matching V2 avec scoring sectoriel BTP fin, **3 premiers verdicts `pertinent` end-to-end** sur la base réelle. Démonstrable à un prospect BTP.

### Sprint à venir — Étendre matching aux autres presets (Sprint C)

| # | Chantier | Effort par preset |
|---|---|---|
| C-ING | Profil + matching sectoriel ingénierie (Bouygues, Setec, Egis...) | 3-4h |
| C-CONS | Profil + matching sectoriel conseil (cabinets, BCG, McK...) | 3-4h |
| C-IT | Profil + matching sectoriel IT (ESN, Capgemini, Sopra...) | 3-4h |
| C-ENR | Profil + matching sectoriel énergies renouvelables | 3-4h |

Priorité Younes : ingénierie > conseil > IT > EnR (selon plan commercial).

### Sprint S+1 (semaine prochaine) — Démonstration produit

| # | Chantier | Effort |
|---|---|---|
| D1 | Dashboard "Top opportunités" | 4-6h |
| D2 | Fiche marché commerciale | 4-6h |

**Livrable** : UI prête à montrer en RDV prospect.

### Sprint S+2 — Premier démarchage

- Identification de 3-5 prospects par secteur (BTP en priorité)
- Démo Tendia avec profil BTP démo (puis ingé/conseil/IT au fur et à mesure de Sprint C)
- Validation valeur prospect avant industrialisation

### Sprint S+3 à S+6 (si traction) — Industrialisation

- F : Pipeline auto
- E : Multi-tenant
- B1 : Sprint DEMATIS
- C-V1 : Calibrage triangulé DECP (reporté du sprint en cours)
- C-V2 : Classification DECP ciblée

### Sprint S+6+ (si scale) — Optimisations

- B2, B3 : Plateformes complémentaires
- C-V3 : Cache DECP
- D3, D4 : Explorer enrichi + onboarding

---

## 5. Coûts récurrents prévisionnels

### En régime de croisière (1 organisme, 1000 marchés/mois)

| Poste | Coût/mois |
|---|---:|
| Classification IA (Haiku) | ~4€ |
| Briefs LLM mutualisés (Sonnet, ~100 marchés) | ~15€ |
| Calibrations LLM (Sonnet, ~50 par client) | ~7€ |
| Veille DECP (Vague 1, API gratuite) | 0€ |
| Hébergement Postgres + Flask | 20€ |
| Anthropic Workspace (suivi tokens) | inclus |
| **TOTAL** | **~46€/mois** |

### Avec 10 organismes (mutualisation efficace)

| Poste | Coût/mois |
|---|---:|
| Classification IA (mutualisée) | ~4€ |
| Briefs LLM (mutualisés) | ~15€ |
| Calibrations LLM (×10 clients) | ~70€ |
| Hébergement | 30€ |
| **TOTAL** | **~120€/mois** |

→ Coût marginal par client : ~12€/mois. Avec un abonnement 200€/mois : marge 94%. SaaS classique.

---

## 6. Risques identifiés

### Risque 1 — Plateformes DCE mortes (DEMATIS, achatpublic)
- **Impact** : limite la couverture à 35% des marchés
- **Mitigation** : Chantier B en S+3-S+6, ou workflow manuel temporaire
- **Probabilité de levée** : moyenne (captcha = combat permanent)

### Risque 2 — Qualité briefs LLM variable
- **Impact** : prospect déçu si brief approximatif
- **Mitigation** : revue manuelle des briefs avant démo, fine-tuning prompts si besoin
- **Probabilité** : faible (Sonnet 4.6 est très fiable sur ces tâches)

### Risque 3 — RGPD et données acheteurs
- **Impact** : blocage commercial public
- **Mitigation** : tout est open data, pas de données personnelles, RGPD trivial
- **Probabilité** : négligeable

### Risque 4 — Concurrence (Dispofi, Vecteur Plus, MyMarchespublics)
- **Impact** : compression marges, érosion proposition de valeur
- **Mitigation** : différenciation par profondeur IA (briefs, calibration triangulée) — features non-existantes chez les concurrents au 12 juin
- **Probabilité** : à surveiller

### Risque 5 — Dépendance technique LLM Anthropic
- **Impact** : panne ou hausse tarif unilatérale
- **Mitigation** : abstraire les appels LLM derrière un proxy (Claude/GPT/Gemini interchangeable)
- **Probabilité** : faible (Anthropic stable)

---

## 7. Stratégie commerciale (brouillon)

### Cibles prioritaires

1. **PME formation** (10-50 salariés) avec Qualiopi : OF spécialisés, cabinets de bilan de compétences, organismes d'insertion. Volume marché public formation : ~13 marchés/mois.
2. **PME BTP** spécialisées second œuvre ou rénovation thermique. Volume : ~145 marchés/mois.
3. **ESN PME** (20-100 salariés) sur infrastructure ou dev. Volume : ~25 marchés/mois.
4. **Cabinets conseil/audit** spécialisés secteur public. Volume : ~30 marchés/mois.

### Canaux de prospection

1. LinkedIn ciblé par secteur
2. Salons sectoriels (CSF Numérique, BIM World, Salon de la Formation)
3. Partenariats fédérations (FFB, Syntec, Garf, FFP)
4. Bouche-à-oreille (après 1er client satisfait)

### Argumentation prospect

1. **Démo Tendia 90 secondes** : "Voici les 5 marchés qui vous correspondent ce mois, avec leur prix estimé et leur verdict éligibilité"
2. **Comparaison concurrentielle** : "Vecteur Plus vous dit qu'il y a 25 marchés, vous devez les lire un par un. Tendia vous dit lesquels candidater"
3. **Pricing** : "200€/mois pour démarrer, sans engagement" (modèle freemium possible)

---

## 8. Validation immédiate de cette doc

Cette doc est un brouillon. Avant validation :

- [ ] Younes relit et corrige les estimations d'effort
- [ ] Younes valide la priorisation Chantier A → C → D → autres
- [ ] Younes corrige la cible commerciale (selon son réseau et son intuition)
- [ ] Younes décide : commence-t-on par le démarchage formation (que Younes connaît) ou un autre secteur ?

---

## 9. Décisions à prendre maintenant

| # | Question | Mon vote |
|---|---|---|
| Q1 | Lancer enrichissement mutualisé ce soir ? | ✅ Oui |
| Q2 | Faire Chantier C (DECP triangulé) cette nuit ? | ✅ Oui, ~3-4h dev |
| Q3 | Faire Chantier A (profils sectoriels) après C ? | ✅ Oui, ~4-5h dev |
| Q4 | UI commerciale (Chantier D1-D2) en sprint S+1 ? | ✅ Oui |
| Q5 | DEMATIS (B1) maintenant ou attendre traction ? | ⏳ Attendre 1er prospect |
| Q6 | Multi-tenant (E) maintenant ou plus tard ? | ⏳ Attendre 1er prospect signé |

---

**Synthèse en 1 phrase** : Tendia est techniquement à 80% prêt pour démarcher des prospects. Les 20% restants (profils sectoriels + calibration DECP + UI commerciale) représentent ~3-4 jours de dev, à faire avant le 1er RDV commercial.
