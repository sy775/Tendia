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

### ✅ Évaluateur sectoriel EnR + géographie (19 juin 2026)
Diagnostic via TEE27 sur un marché PV (56676, Charente) scoré 45 : (a) l'évaluateur
sectoriel EnR était un **stub** (+0) → l'expertise PV ne comptait pas ; (b) la géo ne
**pénalisait jamais** le hors-zone (+0). Corrigé :
- **`_eval_sectoriel_energie_renouvelable`** (`matching.py`) : 3 signaux —
  `enr_technologie` (familles PV/éolien/méthanisation/géothermie/… maîtrisées ET
  demandées : +22 / −8 si hors techno), `enr_prestation` (études/AMO vs travaux/fourniture
  vs exploitation — capte qu'un AMO comme TEE27 n'est pas un installateur : +8 / −6),
  `enr_segment` (clients publics : +3). Token/famille-matching robuste aux variantes.
- **Géographie** : lit désormais `perimetre_geographique` (« Dept 16 ») ; hors-zone
  **pénalité modérée** (−8, ou −12 si strict) — **pas un poids énorme** ; pour un acteur
  `zones_strict` (proximité), **go/no-go** → verdict `non_pertinent` (champ `go_no_go`
  sur le motif, lu par `_calculer_verdict`).
- **`zones_strict`** : nouveau champ profil (socle). TEE27 = True (Eure uniquement).

**Validation TEE27 / marché PV** : Charente (hors zone) → 52 mais **non_pertinent**
(gate) ; même marché simulé dans l'Eure → **99 très_pertinent** (géo +25, EnR +22,
synergie +10). BTP demo 57070 → 75 (aucune régression).

### ✅ Granularité de la taxonomie (19 juin 2026)
Tour des presets : les fourre-tout étaient `moe_architecte_urbanisme` (26 marchés),
`ingenierie_environnementale` (16), `btp_voirie_reseaux` (50), `energie_amo_etudes`.
**+7 codes fins** ajoutés (taxonomie 56 → 63), 4 descriptions recentrées :
- `moe_energetique_batiment` ★ (→ ingénierie + EnR), `moe_urbanisme_amenagement`, `moe_infrastructure_vrd`
- `ingenierie_eau_milieux` (→ ing + btp), `ingenierie_ecologie_biodiversite`
- `energie_amo_developpement` ★ (→ EnR + ing) — cœur AMO/montage TEE27
- `btp_reseaux_divers` (→ btp + ing)

**Méthode d'enrichissement** (réutilisable, cf `scripts/enrichir_taxonomie_v2.py`) :
1. Ajouter le code à `presets/_taxonomie_domaines.json` (libellé, description, exemples oui/non).
2. Câbler dans `presets/<preset>/_preset.json` → `veille.domaines_acceptes`/`optionnels`
   (pilote `presets_pour_domaines` donc le matching).
3. Recentrer la description du fourre-tout d'origine (renvois « → nouveau_code »).
4. Ajouter une **frontière piégeuse** dans les 2 prompts classeurs
   (`llm_extract._section_taxonomie_prompt` + `tendia_classification._prompt_systeme`).
5. **Re-classification ciblée** : `python scripts/reclassifier_affine.py --cibles-enrichissement`
   (ne touche que les marchés des codes recentrés).
Le gain pour TEE27 : une « MOE rénovation énergétique » sort de la MOE générique → matche
l'EnR au bon rang ; un « AMO développement PV » → `energie_amo_developpement` (cœur métier).

### Pistes restantes (non implémentées)
- **Croiser avec le poids du domaine côté marché** (`domaines_metier[].poids`) :
  adéquation = poids_marché × priorité_profil (éviter qu'un lot à 15 % pèse autant qu'un objet principal).
- **Évaluateurs sectoriels conseil / IT / formation** encore en stub.
- **Widgets de formulaire EnR/conseil** (cases guidées) — schéma EnR a des enums riches
  (technologies, prestations, segments) ; formulaire à enrichir (chantier UX en cours).
- **Granularité BTP/IT plus fine** si besoin (BTP matche déjà via corps_de_metier).

### ✅ Matching plus précis — affinage additif du prompt de classification (19 juin 2026)
Le matching dépend de la qualité de `domaines_metier`. Affinage **additif** (aucune
règle existante modifiée) appliqué aux **deux** prompts qui classent :
- `llm_extract.py` → `_section_taxonomie_prompt` (domaines lors de l'extraction) ;
- `tendia_classification.py` → `_prompt_systeme` (pré-classifieur `classifications_ia`,
  qui pilote aussi le **routage des presets** à l'extraction et le dashboard).

Deux frontières piégeuses **ajoutées** :
1. **TRAVAUX vs ÉTUDES** : des travaux techniques (CVC, élec, plomberie, fluides,
   génie climatique en installation/pose) = **BTP** (corps d'état), PAS `ingenierie_*`
   ni `moe_*` (réservés aux missions d'études/conception sans travaux). Corrige la
   racine du cas 56378 (`ingenierie_fluides_climatique` collé à des travaux CVC/élec).
2. **ÉNERGIE** : projet/AMO/réalisation ENR (`energie_*`) ≠ fourniture pure
   d'élec/gaz (`fourniture_*`/`autre`) ≠ rénovation thermique (`energie_renovation_thermique`).
   Utile pour le profil TEE27 (exclut la fourniture d'énergie de son cœur EnR).

⚠️ **Aucun suivi de version dans le classifieur** → l'ajout ne re-classifie rien
automatiquement (additif pur, « ne rien casser ») : il s'applique aux **nouvelles**
classifications / extractions. Pour l'appliquer au stock existant → re-classification
ciblée (lot distinct, p. ex. sur les marchés `ingenierie_*` issus d'avis « nature =
Travaux », candidats probables au reclassement BTP).

> ⚠️ Tension à arbitrer sur 56378 : avec cette précision, une re-classification le
> ramènerait vraisemblablement en **BTP seul** (les lots CVC/élec sont des travaux),
> alors que la décision §2-axe3 était « matché aux deux presets ». À trancher : soit
> on accepte BTP-seul (plus correct), soit on garde un 2e domaine BTP technique.

---

## 4. Matching généralisé au DOMAINE + refonte UI (19 juin 2026, suite)

### 4.1 Matching fin généralisé — `domaines_couverts` (changement majeur)
**Problème** : le matching au niveau PRESET était trop grossier → faux positifs (formation
softskills attrapée via le preset `conseil` de TEE27, MOE bâtiment générique via `ingenierie`).
Presets `conseil`/`it` sans évaluateur.

**Solution** (`matching._eval_domaines_couverts`) : le profil déclare ses **domaines précis
couverts** (`domaines_couverts`, taxonomie 63 codes). Le matching compare les `domaines_metier`
du marché à ces domaines, **pondéré par le poids du domaine côté marché** :
- aucun domaine déclaré → neutre (compat ascendante) ;
- marché dont AUCUN domaine n'est couvert (preset large matché) → **−30** (faux positif) ;
- sinon → **+28 × poids**.

Uniforme pour tous les presets (plus de schéma/évaluateur bespoke nécessaire), chaque domaine
déclaré SERT, faux positifs filtrés. Validation TEE27 : 57028 → non_pertinent · 56456 PV 10% →
à_vérifier · 56576 → 96 · MOE bâtiment générique → filtré · BTP demo 75 (pas de régression).

Pondération complémentaire `_poids_preset_marche` : atténue preset/thématique/sectoriels quand
le preset matché ne pèse qu'une fraction du marché (56456 : 99 → 40).

> **Décision (Younes)** : ne PAS dissoudre le preset « ingénierie ». La maille de matching est
> le DOMAINE ; le preset n'est qu'un regroupement de formulaire. Migration inutile.

### 4.2 Taxonomie
- `conseil_transition_energetique` (→ conseil + énergie) : comble le trou « conseil sans
  énergie » (PCAET, schéma directeur énergie). Frontière piégeuse vs AMO projet vs conseil généraliste.
- Re-classification **parallélisée** (8 workers) : 418 marchés en **2,7 min** (vs 21 min), 137 reclassés, 2,5 €.

### 4.3 Formulaire profil
- **Domaines couverts éditables** par onglet preset (chaque onglet = ses domaines + son sectoriel).
- Widgets **EnR** ; conseil/it montrent leurs domaines (fin du « Sprint D »).
- **Onglets** des presets actifs (segmented control navy). Généralisé à la création aussi.

### 4.4 Fiche marché — fix majeur
Un `{% if bareme_notation %}` englobait nav onglets + Résumé + Prix → **26 fiches** (ex 56456)
perdaient onglets + moitié haute. Déverrouillé : seule la section Barème reste gatée. **Design
généralisé à 232/232 fiches.**

### 4.5 Refonte dashboard + explorer
Largeur 1560px, accent verdict coloré, score coloré, barre KPI premium + pipeline compact,
tooltips « Verdict en 90s » + « Détail du score » comme la fiche, badge « À vérifier ». Dashboard
suit le matching affiné (écarte les non-pertinents). KPIs sur marchés affichés.

### 4.6 Direction proposée (NON implémentée) — mutualiser les critères communs
Cap validé : « droit au but » secteur (1 formulaire = domaines couverts) + **mutualiser le reste** :
- **Géo** : déjà mutualisé (socle).
- **Capacité** : dupliquée (socle + `capacite_chantiers` BTP + `capacite_etudes` ingé) → **1 section universelle**.
- **Certifications & assurances** : éparpillées (ISO/RGE/Qualibat/OPQIBI/décennale) → **1 section universelle**.
- Onglets preset = seulement le sector-specific (corps de métier, technologies EnR, typologies).
- Refactor moyen (champs sectoriel → socle + matching qui lit `*.qualifications` → un `qualifications` universel). **Prochaine session.**

### 4.7 Notes / dette
- `scripts/ingester_profil_tee27.py` **réécrit** le profil à chaque run → **ne pas le relancer**
  pendant les tests ; éditer via `/profil`. Zones TEE27 = 10 dépts (Normandie + Pays de la Loire).
- Évaluateurs sectoriels conseil/it/formation = stubs au niveau preset, **mais OK** : le matching
  fin passe par `domaines_couverts`.

### 4.8 Chantier LOTS — pertinence par lot (19 juin 2026)
Objectif Younes : « toutes les infos rentrées par le user servent à qlq chose » + visualiser la
pertinence **lot par lot** dans la fiche (allotissement). Décisions et état :

**Allotissement → matching** (`matching._candidature_par_lot`, signal dans `_evaluer_v2`)
- Parse `allotissement.description` : candidature **par lot** vs **offre globale obligatoire**.
- Quand le profil ne couvre qu'une fraction du marché (`_poids_preset_marche < 0.6`) :
  **+7** si on peut candidater par lot (on vise juste nos lots) · **−25** si offre globale
  obligatoire (on devrait porter tout le marché). Badge dans « Comment candidater »
  (✓ vert par-lot / ⚠ doré globale / ◆ inconnu).

**Classification de lot — RÉUTILISE LA CLASSIF IA** (`fiche_marche._lot_domaine_depuis_marche`)
- Demande Younes : « il faut réutiliser la classif IA pour le matching » (≠ mots-clés).
- Mécanique : chaque lot est **rattaché au domaine du marché** (`domaines_metier`, déjà
  classifié par l'IA) dont le libellé/code matche le mieux le **texte propre du lot**
  (intitulé + corps d'état + description PROPRE). **Aucun nouvel appel LLM.**
- ⚠️ Piège corrigé : ne JAMAIS utiliser `allotissement.description` (globale) pour
  dériver le domaine d'un lot → elle contamine tous les lots sans desc propre (ex 56456 :
  « CHARPENTE BOIS » devenait `energie_pv_solaire` car la desc globale parle de PV).
- Fallback mots-clés (`_compat_lot`, substring de mots-clés forts ≥6 car.) seulement si la
  classif IA ne tranche pas. `_compat_lot` retourne `(niveau, mots_matchés)` ; un mot-clé
  **très spécifique** (≥10 car., ex « photovoltaique ») → `coeur` à lui seul.
- Niveaux : `coeur` (cœur de cible) / `partielle` / `hors` / `?`. Le lot prend `coeur` si son
  domaine ∈ `domaines_couverts`.
- Validé 56456 (14 lots BTP+PV, TEE27) : **seul LOT 14 PHOTOVOLTAIQUE = cœur de cible**,
  les 13 lots BTP = hors. Avant : 5 faux positifs (charpente via « bois énergie »).

**UI fiche** (`ui/templates/marche.html`, `fiche_marche.synthese_lots_pertinents`)
- « Détail par lot » : carte avec **barre navy à gauche** (généralisée à toutes les sections
  `.sec`), chip corps d'état (navy), domaine (italique), montant (« prix marché »), coût.
  **Pas d'icônes/badges numéro** (retirés à la demande). Tag compat avec **tooltip** : survol →
  niveau + mots-clés/correspondance matchés (cf. les 3 `title=` sur les `<span>` compat).
- Résumé : mini-section sobre **« Lots pertinents »** (pastille dorée + titres en tirets « – »).
- Per-lot : montant par lot via `allotissement.lots_detailles` (mergé par `numero`).

**À FAIRE (prochaine session) — important**
1. **Peupler `lots[].domaine` à l'extraction.** Le prompt `llm_extract` a déjà le champ
   `lots[].domaine` (« code taxonomie du métier DOMINANT de CE lot »), MAIS les briefs
   existants ne l'ont pas → on s'appuie aujourd'hui sur `_lot_domaine_depuis_marche` (dérivé
   du marché). Une **ré-extraction ciblée** (ou un batch de classif de lots) donnerait une
   maille **plus fine que les `domaines_metier`** du marché (un lot peut sortir de la liste
   marché). Quand `lots[].domaine` est présent, il a priorité (déjà câblé).
2. Idem `conseil_transition_energetique` : présent dans le prompt, à peupler sur le stock.
3. Mutualiser critères communs (§4.6) — capacité + certifications → sections universelles.

### 4.9 État serveur / vérif rapide
- Serveur : `python tendia_ui.py` (port 5000, debug=False) → **redémarrer à chaque changement**.
- Profil actif de test = **TEE27** (EnR/ingénierie/conseil, 10 dépts). Marché-témoin lots =
  **`/marche/BOAMP-26-56456`** (14 lots, doit montrer LOT 14 PV en cœur de cible).
- Tous les commits du chantier lots sont sur `master` (pas encore mergé `main`).
