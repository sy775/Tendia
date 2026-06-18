# Itération — corrections UI/critères, plan prompt & matching multi-preset

Session du 19 juin 2026. Trois volets : (1) modifications déjà appliquées,
(2) plan d'optimisation du prompt d'extraction (préparé, **non lancé**),
(3) constat de conception sur le matching multi-preset (entreprises diversifiées).

---

## 1. Modifications appliquées (commitées)

### 1.1 Audit des « faux critères » d'éligibilité
- **`scripts/audit_faux_criteres.py`** (nouveau) : parcourt tous les briefs, évalue
  les `alertes_candidat`, flague les alertes classées « critère vérifiable »
  (clé canonique) alors qu'elles sont du **contexte** (délai, prix, coactivité).
  Résultat : **68 critères vérifiables, 0 faux positif** après corrections.
- **`matching_exigences.py`** :
  - Bloc 3 (capacité financière) : **garde-fou CA** — une alerte « accord-cadre
    **sans minimum** / aucun CA garanti » est un *risque commercial*, pas une
    exigence de CA candidat. Elle ne reçoit plus la clé `ca_min`. (2 faux positifs
    corrigés : 56172, 56320.)
  - Rappels des corrections amont (mêmes classes de bug, frontières de mot) :
    `nda` → ne matche plus « caleNDAires » ; `rge` → ne matche plus « urgence ».

### 1.2 Injection des certifications structurées dans l'éligibilité
- **`tendia_ui.py`** (route `detail_marche`, ~l.1219) : l'éligibilité ne lisait que
  `alertes_candidat` (plafonné à 3-5 points par le LLM → certifs bloquantes
  manquantes). On **injecte désormais** `references_exigees.certifications_obligatoires`
  (source structurée, fiable) dans les critères vérifiables, avec **dédup par clé
  canonique**. Corrige le cas 56378 (CERFF lot 3 manquait à côté de Qualifelec lot 4).

### 1.3 Refonte esthétique de la fiche marché (`ui/templates/marche.html`)
- Icônes de sections **harmonisées** : fond bleu marine + icône dorée (toutes).
- Tag « Analyse complète/partielle » rendu **discret** (texte coloré muet, sans fond).
- **Détail du verdict** déplacé en **tooltip au survol du score** (cercle), carte
  sidebar supprimée.
- Tags du header **rapprochés à droite** (`margin-right` 40 → 16 px).
- **Top 5 concurrents** remonté juste **sous les critères** d'éligibilité (DECP).
- Tag **Secteur** déplacé en haut à droite de la section « Résumé Tendia ».
- **Repli sectoriel** (`fiche_marche.py`, `_fallback_sectoriel` + `bloc_sectoriel_pour_marche`) :
  un preset détecté mais **sans données extraites** (ex : ingénierie sur 56378, brief
  établi sur le preset dominant BTP) n'affiche plus « non extraites » mais l'info
  réellement disponible : **sous-domaine + lots concernés** (depuis `domaines_metier`).

### 1.4 Profil TEE27 ingéré
- **`scripts/ingester_profil_tee27.py`** (nouveau, **non commité** sur demande) :
  SEML Transition Euroise Énergies. Presets `energie_renouvelable` (principal) +
  `ingenierie` + `conseil`. Zone Eure (27) stricte. Activé ; ancien profil (Tridyne)
  conservé en bibliothèque (`profil_ingenierie_demo`).
- Mapping appliqué : `enr → energie_renouvelable`, `conseil_rd → conseil`.
- Infos sans champ dédié (nom commercial, exclusions, ambivalence acheteur/répondant,
  caractère public) stockées dans `_description`. À compléter : SIREN, effectif, CA,
  certifications, références.

---

## 2. Plan d'optimisation du prompt d'extraction (préparé, NON lancé)

Toute modification du prompt change `PROMPT_V2_SHA` → déclenche une ré-extraction.
On regroupe les axes nécessitant le LLM en **une seule passe** (« itération efficace »).
**Décision : ne pas lancer le batch pour l'instant.**

| # | Axe | Décision | Modif prompt | Ré-extraction |
|---|-----|----------|--------------|---------------|
| 1 | Plancher BOAMP | **Garder 90 000 €** | aucune | non |
| 2 | Coût par lot + **ancrage lots** | schéma déjà là ; **règle d'ancrage ajoutée** | ✅ ancrage estimation sur lots | oui (cohérence 2 sections) |
| 3 | Secteur hors preset dominant | **corriger mapping + extraire, marché matché aux 2 presets** | routage + mapping | oui (multi-preset) |
| 4 | Critères / certifs | aval déjà corrigé ; durcissement optionnel | optionnel | si durci |
| 5 | Comment candidater / pièces à fournir | **nouveau** | nouveau champ | oui |

### Axe 1 — Plancher BOAMP (abandonné)
`SEUIL_PUBLICITE_BOAMP_EUR = 90_000` (`llm_extract.py` l.46), texte prompt l.622-628,
post-traitement l.966-972. **On conserve 90k.** (Le plancher est ré-appliqué en
post-traitement, donc modifiable sans LLM si besoin un jour.)

### Axe 2 — Coût par lot (déjà en place)
Schéma `lots[].cout_estime_min_eur/max_eur` (`llm_extract.py` l.466-467) + règles
« COÛT PAR LOT » (l.696-702). Branché UI (« Détail par lot »).
**Batch de peuplement terminé (19 juin 2026)** : 96 briefs multi-lots → 81 % ont au
moins un lot chiffré ; 398/487 lots (82 %) avec fourchette de coût. Le reste = lots
non chiffrables laissés à `null` par le LLM (normal).

**Modif prompt ajoutée (ancrage lots)** : la règle « COÛT PAR LOT » impose désormais,
dès qu'il y a des lots, d'estimer **chaque lot d'abord** puis de construire le coût
**global = somme des lots** (`cout_min/max/total_eur` = Σ des lots ; 1 poste = 1 lot).
Objectif : la **fourchette en gras** est identique dans « Prix & estimation » et
« Détail par lot ». ⚠️ Change `PROMPT_V2_SHA` → rend les briefs « stale » : à intégrer
dans la passe de ré-extraction de l'itération (non lancée).

### Axe 3 — Secteur hors preset dominant
**Cause racine** : `_resoudre_presets_pour_marche` (`llm_extract.py` l.1023-1060) lit
la collection `classifications_ia`, souvent **plus pauvre** que les `domaines_metier`
finaux du brief. Ex 56378 : classif = `btp` seul → schéma ingénierie jamais injecté
→ champs MOE inextractibles.
**Modifs** :
1. Routage = `presets(classif_ia) ∪ presets(brief.domaines_metier existant)` — une
   seule extraction multi-preset suffit (`schema_pour_presets` gère déjà l'union).
2. **Revoir le mapping domaine → preset** : distinguer une **mission MOE** (études,
   conception fluides → preset ingénierie) d'un **lot de travaux** technique
   (élec/CVC dans un marché BTP → reste BTP). Sinon le bloc MOE reste vide.
   - Décision Younes : « les deux » — corriger le mapping **et** extraire le secteur
     secondaire ; le marché doit être **matché aux deux presets**.
   - **Question ouverte** : faut-il un 3e sous-type « travaux techniques spécialisés »
     (élec/CVC/fluides en tant que *travaux*), distinct du preset MOE ?

### Axe 4 — Critères / certifications
`references_exigees.certifications_obligatoires` (`llm_extract.py` l.446) est **fiable**.
`alertes_candidat` (l.476) est plafonné à « 3-5 points » → ne flague pas toutes les
certifs bloquantes. Corrigé **en aval** (cf. §1.2). **Durcissement prompt optionnel** :
garantir que toute certif/qualif « à peine d'irrecevabilité » figure dans
`certifications_obligatoires`.

### Axe 5 — Comment candidater / pièces à fournir (nouveau)
Aujourd'hui la liste des pièces est **codée en dur et générique** dans le template
(`marche.html` l.1750 « DC1, DC2, attestations » ; l.1779 « Acte d'engagement +
bordereau »). Le RC précise pourtant une **liste exacte** non extraite.
**Modif** : nouveau champ schéma, ex `dossier_candidature.pieces_a_fournir`
(candidature + offre), chaque pièce avec `libelle` + `source`. Brancher le template
dessus (avec repli sur le générique actuel si vide).
**Question ouverte** : se limiter à la liste des pièces, ou aussi mode de dépôt /
signature électronique / nombre d'exemplaires ?

---

## 3. Constat — matching multi-preset & entreprises diversifiées

**Remarque Younes** : « le système match tous les preset au même poids, et n'est pas
designé pour des entreprises diversifiées ». **Confirmé.**

### Ce que fait le moteur (`matching.py`, `_evaluer_v2` l.906-942)
- **`_eval_preset_compatibilite`** (l.351-372) : **+20 forfaitaire** dès qu'il existe
  *une* intersection entre presets du marché et presets du profil. Aucune distinction
  selon que le marché touche l'activité **principale** ou **tertiaire**.
- **Boucle sectorielle** (l.919-927) : pour *chaque* preset couvert en commun, on
  **additionne** les signaux sectoriels — sans pondération cœur/périphérie.
- **`presets_couverts` est une liste plate** : le `principal/secondaire/tertiaire`
  fourni (ex TEE27) est **aplati**, il n'existe aucun champ de priorité.
- Score = **somme** des motifs, bornée [0, 100].

### Conséquences pour une entreprise diversifiée
- Un marché sur un métier **marginal** obtient la même compat preset (+20) qu'un
  marché **cœur**.
- Aucune notion de « c'est mon activité principale, priorise-la ».
- Une entreprise à 3 presets peut accumuler plus de motifs sectoriels (breadth)
  sans que cela reflète une vraie adéquation stratégique.

### ✅ IMPLÉMENTÉ (19 juin 2026) — pondération par priorité de preset

Décote **équilibrée** retenue (décision Younes).

1. **Schéma profil** (`organisme.py`) : nouveau champ **`presets_priorites`**
   (`{code: rang}`, 1=principal, 2=secondaire, 3=tertiaire). `presets_couverts` reste
   la liste de couverture (compat ascendante). Défaut si vide : ordre de
   `presets_couverts`. Ajouté à `template_socle_vide` + `template_profil_complet`.
2. **Scoring** (`matching.py`) :
   - `_rang_preset(organisme, code)` : rang via `presets_priorites`, sinon index de liste.
   - `_eval_preset_compatibilite` pondéré par le **meilleur** preset matché :
     `PRESET_COMPAT_POINTS = {1:20, 2:13, 3:7}` (défaut 7 au-delà).
   - Signaux sectoriels **positifs** atténués : `PRESET_FACTEUR_SECTORIEL = {1:1.0, 2:0.6, 3:0.35}`
     (`_ponderer_motifs_sectoriels` ; les pénalités go/no-go négatives restent pleines).
   - `rang_preset_matche(organisme, presets_marche)` : helper public pour le tri.
   - **Compat ascendante** : un profil mono-preset (legacy) → rang 1 → +20 (inchangé).
3. **Tri dashboard** (`tendia_ui.py`) : si un profil est actif, tri par
   `(preset_rang asc, score desc, urgence)` → l'activité **principale** remonte d'abord,
   les marchés hors-activités (rang 99) tombent en bas. Sans profil → tri richesse (inchangé).
4. **Formulaire profil** : sélecteur **Principal/Secondaire/Tertiaire** par preset
   (`edit.html`, `nouveau.html`) ; parsing `preset_priorite.<code>` (`profil_form.py`) ;
   priorité affichée dans `detail.html`.
5. **TEE27** ré-ingéré avec `{energie_renouvelable:1, ingenierie:2, conseil:3}`.

**Validation TEE27** : distribution des rangs sur la base = 6 (rang 1 EnR) · 35 (rang 2
ingénierie) · 20 (rang 3 conseil) · 361 (hors activités). Le dashboard remonte bien le
cœur EnR d'abord. Barème : `PRESET_COMPAT_POINTS` / `PRESET_FACTEUR_SECTORIEL` en tête
de `matching.py`, **facilement ajustable**.

### Pistes restantes (non implémentées)
- **Croiser avec le poids du domaine côté marché** (`domaines_metier[].poids`) :
  adéquation = poids_marché × priorité_profil (éviter qu'un lot à 15 % pèse autant qu'un objet principal).
- **Strict géographique** comme go/no-go dur (TEE27 : Eure uniquement) — aujourd'hui
  la géo est un motif pondéré, pas un couperet.

### Matching plus précis — affiner le prompt de classification (additif)
Le matching dépend de la qualité de `domaines_metier` (classification IA). Pour
l'améliorer **sans rien casser** : **ajouter** des précisions au prompt de
classification (frontières piégeuses, sous-domaines, règles de désambiguïsation)
**en plus** de l'existant, sans réécrire les règles actuelles. ⚠️ Change la
classification → nécessite une **re-classification** pour prendre effet ; à scoper
comme un lot distinct (peut être ciblé sur les marchés mal classés). À détailler.
