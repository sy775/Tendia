# Tendia — Documentation technique

**Version** : 3.0 (post Sprint 2bis + A + B — multi-secteurs avec matching V2)
**Date** : 12 juin 2026
**Audience** : développeur, mainteneur

---

## 1. Vue d'ensemble architecturale

### 1.1 Pile technique

```
Python 3.11+
Flask (UI web)
SQLite (stockage local, mutualisé entre clients à terme)
Anthropic SDK (LLM — Sonnet 4.6 + Haiku 4.5)
Tailwind CSS (UI)
```

Dépendances Python listées dans `requirements.txt`.

### 1.2 Pipeline complet

```
┌──────────────────┐
│ 1. INGESTION     │ → BOAMP + DECP (sources publiques)
│  connecteurs/    │   Stocke dans collection 'marches'
└──────────────────┘
         ↓
┌──────────────────┐
│ 2. CLASSIFICATION│ → Haiku 4.5 sur métadonnées (titre+CPV+objet)
│  tendia_         │   Génère 'domaines_metier' (taxonomie 56 domaines)
│  classification  │   Stocke dans collection 'classifications_ia'
│   .py            │   Coût : ~0.004€/marché
└──────────────────┘
         ↓
┌──────────────────┐
│ 3. MATCHING IA   │ → Compare classification ↔ presets installés
│  analyse.py      │   Mode strict : domaine ∈ domaines_acceptes
│                  │   Fallback keyword si non classifié
│                  │   Stocke dans collection 'scores_matching'
└──────────────────┘
         ↓
┌──────────────────┐
│ 4. TÉLÉCHARGE DCE│ → Récupère DCE depuis plateformes acheteurs
│  dce_           │   Plateformes OK : PLACE, e-marchespublics
│  telecharger.py  │   Bloquées : DEMATIS (captcha), achatpublic (login)
└──────────────────┘
         ↓
┌──────────────────┐
│ 5. BRIEF COMPLET │ → Sonnet 4.6 sur DCE complet
│  llm_extract.py  │   Génère brief structuré (synthèse, exigences, alertes)
│  enrichir_       │   Coût : ~0.15€/marché
│  complet.py      │   Stocke dans collection 'briefs_extraits'
└──────────────────┘
         ↓
┌──────────────────┐
│ 6. CALIBRATION   │ → Sonnet 4.6, bottom-up sectoriel
│  llm_calibration │   Triangulé DECP en Vague 1 (à venir)
│   .py            │   Stocke dans collection 'extractions_calibrees'
└──────────────────┘
         ↓
┌──────────────────┐
│ 7. ÉLIGIBILITÉ   │ → Matche alertes brief ↔ profil organisme
│  matching_       │   Verdict par alerte : OK, BLOQUANT, À VÉRIFIER
│  exigences.py    │   Score d'éligibilité global
└──────────────────┘
         ↓
┌──────────────────┐
│ 8. UI            │ → Dashboard (pertinents) + Explorer (exhaustif)
│  tendia_ui.py    │   + Fiche marché + Profil
│  ui/templates/   │
└──────────────────┘
```

### 1.3 Architecture mutualisée (cible)

Les collections suivantes sont **mutualisées** (partagées entre tous les clients) :
- `marches` — Données BOAMP/DECP brutes
- `classifications_ia` — Classifications LLM
- `briefs_extraits` — Briefs complets LLM
- `extractions_calibrees` — Calibrations prix

Les collections suivantes sont **per-client** :
- `scores_matching` — Calculé à partir du profil client (peut être recalculé à la demande)
- `profil_organisme_<code>.json` — Profil propre à chaque organisme
- `cycle_marche` — Suivi de candidature (statut, notes, dates)

À l'avenir, en mode multi-tenant, il y aura une table `organismes` qui isolera les données per-client. Aujourd'hui (mono-tenant), 1 base = 1 utilisateur, mais la séparation conceptuelle est en place.

---

## 2. Modules clés

### 2.1 Sourcing

**`connecteurs/boamp.py`** (~600 lignes)
- Pagine via l'API BOAMP officielle
- Normalise vers le schéma interne Tendia
- Déduplication basée sur l'ID BOAMP
- Limites : pas tous les CPV, pas tous les avis (à voir avec data.gouv.fr)

**`connecteurs/decp_consolidee.py`** (~373 lignes)
- Source DECP consolidée via tabular-api.data.gouv.fr
- **HARDCODÉ France Travail aujourd'hui** (vestige Apptia) — à généraliser dans le Chantier C-V1
- API gratuite, sans clé

### 2.2 Classification

**`tendia_classification.py`** (~600 lignes, Sprint 2)

Fonctions clés :
- `pre_filtre_rejette(marche)` — Rejet statique gratuit (ContractAwardNotice, marchés expirés)
- `classifier(marche, modele='haiku')` — Appel LLM avec prompt système contenant la taxonomie complète
- `classifier_un_marche(marche_id, marche, ...)` — Pipeline complet : pré-filtre → LLM → stockage

CLI :
```bash
python tendia_classification.py --backfill        # tous les marchés
python tendia_classification.py --id BOAMP-...    # 1 marché
python tendia_classification.py --force           # ignore le cache
python tendia_classification.py --modele sonnet   # plus précis, plus cher
```

Schéma de sortie LLM :
```json
{
  "domaines_metier": [
    {"code": "btp_voirie_reseaux", "poids": 0.6, "lots_concernes": [1,2]},
    {"code": "btp_demolition", "poids": 0.4, "lots_concernes": [3]}
  ],
  "raison_classification": "...",
  "synthese_courte": "...",
  "_meta": {
    "modele": "claude-haiku-4-5",
    "input_tokens": 3120,
    "output_tokens": 200,
    "cout_eur": 0.0042,
    "duree_s": 2.8
  }
}
```

**Important** : 1 marché peut avoir 1 à 3 domaines avec poids. Le matching utilise le domaine avec `poids` maximum (ou le premier si pas de poids).

### 2.3 Taxonomie

**`presets/_taxonomie_domaines.json`** (v1.1, 56 domaines)

Structure :
```json
{
  "_meta": {"version": "1.1", "derniere_maj": "2026-06-11"},
  "domaines": {
    "btp_gros_oeuvre": {
      "libelle": "BTP gros œuvre et construction neuve",
      "description": "...",
      "exemples_oui": ["...", "..."],
      "exemples_non": ["...", "..."]
    },
    ...
  }
}
```

Si on ajoute un domaine, mettre à jour le `_meta.version` et la `derniere_maj`. La taxonomie est **injectée dans le prompt LLM système** de `tendia_classification.py`.

### 2.4 Matching

Deux niveaux de matching :

**(A) Matching marché × preset** dans `analyse.py` (~870 lignes) : pour chaque marché, détermine si le marché concerne le preset. Utilisé par le dashboard, Explorer, etc.

Fonctions clés :
- `matcher_preset_marche(preset_def, marche)` — Ancien matching keyword/CPV (gardé pour fallback)
- `matcher_preset_marche_par_ia(preset_def, marche_id, classifs_ia, briefs)` — Matching IA (Sprint 2)
- `est_pertinent_strict(...)` — Wrapper IA prioritaire + fallback keyword
- `recalculer_tout(force=True)` — Recalcule TOUS les scores (422×6 = 2532 entrées)

Score stocké dans `scores_matching` :
```python
{
  "BOAMP-26-XXX__btp": {
    "marche_id": "BOAMP-26-XXX",
    "preset_code": "btp",
    "matche": True,
    "mode_decision": "classification_ia",  # ou "keyword_fallback"
    "niveau_ia": "principal",  # principal | optionnel | hors | non_classifie
    "domaine_classifie": "btp_voirie_reseaux",
    ...
  }
}
```

**(B) Matching organisme × marché** dans `matching.py` V2.1 (~770 lignes, Sprint B) : pour un profil organisme donné, retourne le verdict de pertinence du marché.

API publique :
```python
matching.evaluer(organisme, marche, brief=None, presets_marche=None) -> dict
matching.evaluer_tous(organisme, marches, briefs=None) -> list
```

Détecte automatiquement le format du profil (`_est_format_legacy_formation()`) et route vers :
- `_evaluer_legacy(organisme, marche)` — code formation V1 préservé (Qualiopi, DR France Travail, prestations_maitrisees)
- `_evaluer_v2(organisme, marche, brief, presets_marche)` — nouveau code multi-secteurs

Moteur V2 :
- **4 motifs universels** : `preset_compatibilite` (-50 si profil vide, -30 si pas d'intersection, +20 si OK), `thematique` (mots-clés catalogue +25/+15), `geographie` (+25 dept direct, +15/+12 region via mapping `DEPARTEMENT_VERS_REGION` 101 codes), `capacite` financière (+10 OK, -10 sous seuil min, -20 au-dessus du plafond engagement)
- **Évaluateurs sectoriels par preset commun** : pour chaque code dans l'intersection `presets_marche ∩ presets_profil`, appel d'un évaluateur dédié. V1 implémente BTP, V2 (Sprint C) implémentera ingenierie/conseil/IT/EnR.
- **Synergie +10** si `thematique ≥15 ET geographie ≥15 ET preset_compatibilite ≥20` (alignement total).
- **Verrou go/no-go** : si motif `btp_qualibat` ou `qualiopi` est `False` avec points ≤ -25, verdict forcé à `non_pertinent`.

Évaluateurs BTP (6 motifs) :
- `btp_qualibat` : compare la liste des codes Qualibat à 4 chiffres exigés vs détenus. Robuste aux strings texte libre (LLM met parfois "Non précisé dans le RC" au lieu d'une liste).
- `btp_rge` : booléen exigé vs détenu (+10/-25)
- `btp_amiante` : SS3/SS4 détectés via `qualifications_requises.autres`
- `btp_corps_metier` : match par tokens partagés (insensible aux séparateurs et accents), ratio ≥0.7 = excellent (+15), ≥0.4 = partiel (+8)
- `btp_types_ouvrages` : match par tokens partagés sur `typologie_ouvrage` (+10)
- `btp_capacite_chantier` : `montant_marche.valeur_estimee_euros` vs `capacite_chantiers.montant_max_par_chantier` (+5 OK, -5 légère cotraitance, -15 forte cotraitance)

Seuils verdict : ≥75 `tres_pertinent`, ≥50 `pertinent`, ≥20 `a_verifier`, sinon `non_pertinent`.

Score résultat sur 422 marchés et profil BTP démo IDF (Sprint B validé) :
| Verdict | Nombre | % |
|---|---:|---:|
| `tres_pertinent` | 1 | 0.2% |
| `pertinent` | 2 | 0.5% |
| `a_verifier` | 35 | 8.3% |
| `non_pertinent` | 384 | 91% |

### 2.5 Presets

Architecture en 2 niveaux depuis Sprint A/B :

**(A) Preset extraction & analyse** : `presets/<code>/_preset.json` (1 par secteur, inchangé depuis Sprint 2)

Blocs essentiels :
- `meta` : code, nom, version
- `veille.domaines_acceptes` / `domaines_optionnels` : codes taxonomie
- `vocabulaire_llm` : termes injectés dans prompts
- `prompt_extraction.bloc_schema_specifique` : schéma JSON des champs sectoriels du brief
- `prompt_calibration` : sections du prompt de calibration
- `calibration_llm` : barèmes sectoriels (€/h, %, ratios)

**(B) Schéma profil organisme** (Sprint A) :
- `presets/_socle_profil_organisme.json` : socle commun universel (12 propriétés : identite, presets_couverts, profils_sectoriels, zones_intervention, mots_cles_catalogue, capacite_globale, certifications, references_globales, valeurs_engagements, contraintes, _meta, +autres)
- `presets/<code>/_schema.json` : profil sectoriel spécifique au preset. À ce jour seul `presets/btp/_schema.json` existe (Sprint A). À créer en Sprint C pour ingenierie/conseil/it/EnR.

Schéma BTP : 9 propriétés (qualifications, corps_de_metier, types_ouvrages, capacite_chantiers, rh_chantier, moyens_materiels, references_chantiers, types_clients_publics, pratiques_specifiques).

**Convention** : le code preset = nom du dossier (`presets/btp/` → code `"btp"`). Pas de préfixe.

Presets actuels :
- `formation` (v2) — Stable, 7 domaines, schéma profil legacy
- `energie_renouvelable` (v1) — Stable, 8 domaines, pas de schéma profil
- `btp` (v1 MVP+schéma profil) — Sprint 2/A, 5 domaines, schéma sectoriel complet
- `it` (v1 MVP) — Sprint 2/3b enrichi, 5 domaines, pas de schéma profil
- `conseil` (v1 MVP) — Sprint 2/3b enrichi, 5 domaines, pas de schéma profil
- `ingenierie` (v1 MVP) — Sprint 2/3b enrichi, 5 domaines, pas de schéma profil

### 2.6 Brief LLM

**`llm_extract.py`** (~700 lignes)

Fonction clé : `extraire_via_llm(texte, contexte)` — Appelle Sonnet 4.6 sur le texte concaténé du DCE.

Sortie : JSON structuré avec :
- 12 champs universels : `synthese_marche`, `domaines_metier`, `raison_classification`, `bareme_notation`, `montant_marche`, `revision_prix`, `alertes_prix`, `references_exigees`, `lots`, `calendrier`, `alertes_candidat`, `points_differenciants_attendus`
- Blocs sectoriels selon les presets cibles résolus (voir Décision 10 Sprint 2bis ci-dessous)
- `_appel_llm`, `_meta` : métadonnées techniques

Coût : ~0.15-0.30€/brief (variable selon taille DCE).

**`enrichir_complet.py`** (~400 lignes) — Orchestrateur

CLI :
```bash
python enrichir_complet.py                    # pertinents du preset actif
python enrichir_complet.py --mutualise        # tous les marchés briefables (Sprint 2)
python enrichir_complet.py --mutualise \
    --prioriser energie_renouvelable \
    --prioriser btp \
    --prioriser formation                     # priorisation par preset
python enrichir_complet.py --id BOAMP-...     # 1 marché
python enrichir_complet.py --dry-run          # simule sans appel LLM
python enrichir_complet.py --force            # regénère même si existant
python enrichir_complet.py --max-cout 20.0    # garde-fou coût €
```

⚠ **Bug connu Sprint 3c** : `--id` n'est pas honoré en bypass du filtre pertinent. Si le profil organisme ne considère plus le marché comme pertinent, il est skippé malgré `--force --id`. Patch trivial à appliquer (~10 min) — voir passation_claude.md.

#### 2.6.1 Routage classif → schéma ciblé (Sprint 2bis)

Avant Sprint 2bis, le brief mutualisé envoyait au LLM l'UNION de tous les `bloc_schema_specifique` des 6 presets installés. Conséquence : un brief BTP recevait aussi les schémas formation, énergie, conseil, IT, ingénierie, et le LLM remplissait sciemment plusieurs blocs hors-secteur — 8+ blocs hallucinés par brief.

Maintenant : `llm_extract.extraire_via_llm()` reçoit en argument la liste des presets cibles (résolus depuis `classifications_ia[marche_id].domaines_metier` via `preset.presets_pour_domaines()`) et envoie au LLM uniquement les schémas concernés. Réduction massive de la pollution.

Fallback union : si aucun preset n'est résolu (marché hors-taxonomie), on retombe sur l'union complète. C'est sous-optimal et restera tant que la Décision 5 hors-preset n'est pas tranchée.

#### 2.6.2 Filtre anti-hallucination (Sprint 2bis Sujet 2)

Filet de sécurité code après parse JSON :

```python
def _filtrer_hallucinations(data: dict, codes_presets: list[str]) -> dict:
    """
    Supprime les blocs top-level non listés dans :
    - _CHAMPS_UNIVERSELS_BRIEF (12 champs + _appel_llm + _meta)
    - preset.blocs_sectoriels_pour_presets(codes_presets)
    """
```

`preset.blocs_sectoriels_pour_presets(codes)` extrait par regex `^  "([a-z_]+)":\s*[\{\[]` les noms de blocs top-level depuis `bloc_schema_specifique` de chaque preset ciblé.

Validé in vivo Phase 3c : 3 JSON régénérés audités → **0 pollution détectée**. La règle prompt suffit dans 95% des cas ; le filtre code est le filet pour les 5% restants.

#### 2.6.3 Sync classif IA depuis sortie LLM (Sprint 2bis Sujet 1)

La classif IA initiale est faite par Haiku 4.5 sur titre+objet (~200 tokens). Quand Sonnet 4.6 brief le DCE complet (~50k tokens), sa re-classification est plus précise. `tendia_extraire.py` met à jour `classifications_ia[marche_id]` après écriture du brief si les codes domaines diffèrent.

Log : `🔄 Classif IA mise à jour : [anciens_codes] → [nouveaux_codes]`

Validé Phase 3c : 6 marchés re-classifiés, dont 2 corrections majeures de faux positifs (56463 `btp_voirie_reseaux` → `services_environnement_analyses`, 56493 `btp_voirie_reseaux` → `fourniture_materiel`).

### 2.7 Calibration prix

**`llm_calibration.py`** (~900 lignes)

Pipeline en 2 étapes :
1. Estimation top-down (à venir : sur DECP)
2. Re-pricing bottom-up (sectoriel, depuis preset)
3. Synthèse LLM qui triangule

Sortie : `data/extractions_calibrees/<id>.json`

Coût : ~0.20€/calibration (variable).

### 2.8 Éligibilité

**`matching_exigences.py`** (~300 lignes)

Pour chaque alerte du brief, applique la règle preset `clauses_eligibilite` correspondante :
- `contains_in_profil_bool` — Champ profil booléen (ex: qualifications.qualiopi)
- `ca_minimum` — Profil.finances.ca_annuel ≥ seuil
- `references_minimum` — Nombre de références ≥ seuil

Verdict par alerte : `OK` / `BLOQUANT` / `À VÉRIFIER`. Score global agrégé.

**Mise à jour Sprint A+B** : le profil organisme est désormais multi-secteurs (socle commun + profils sectoriels par preset, voir 2.5(B)). Le matching organisme × marché est implémenté dans `matching.py` V2.1 (voir section 2.4(B)) avec détection automatique du format profil (legacy formation vs nouveau multi-secteurs) et routage. Le module `organisme.py` (~460 lignes) expose : `charger_actif()`, `profil_sectoriel(code)`, `schema_socle()`, `schema_sectoriel(code)`, `template_socle()`, `template_sectoriel(code)`, `valider_profil()` (validation maison sans jsonschema), `supprimer_profil()`. Backward compat legacy : `lire_profil()`, `schema_vide()`, `champs_remplis()`, `est_format_legacy()`, constantes `DR_FRANCE_TRAVAIL` et `PRESTATIONS_FRANCE_TRAVAIL`.

CLI `init_profil.py` (~175 lignes) :
```bash
python init_profil.py                           # --status (par défaut)
python init_profil.py --template btp            # génère un template vide BTP
python init_profil.py --depuis fichier.json     # import
python init_profil.py --purger --confirmer      # supprime
python init_profil.py --force                   # écrase
```

### 2.9 UI

**`tendia_ui.py`** (~1000 lignes)

Routes principales :
- `GET /` — Dashboard (marchés pertinents pour le preset actif)
- `GET /explorer` — Exhaustif (tous les marchés classifiés, filtrable)
- `GET /marche/<id>` — Fiche détaillée
- `GET /profil` — Édition profil organisme
- `POST /marche/<id>/cycle` — Change statut cycle (à candidater / candidaté / etc.)
- `GET /concurrence` — Veille concurrentielle (basique)

**Templates** dans `ui/templates/` :
- `base.html` — Layout commun (nav latérale, header)
- `dashboard.html` — Vue marchés pertinents
- `explorer.html` — Vue exhaustive avec filtres (Sprint 2)
- `marche.html` — Fiche marché détaillée
- `profil.html` — Édition profil

**CSS** : Tailwind + `static/apptia-utilities.css` (utilitaires custom).

### 2.10 Stockage

**`stockage.py`** (~200 lignes, rewrite Sprint 3 étape 2)

API publique préservée (backward-compat) :
```python
data = stockage.charger("collection_name")        # dict {id: {...}}
stockage.sauver("collection_name", data)          # remplace tout
stockage.lire("collection_name", id)              # un objet
stockage.ecrire("collection_name", id, contenu)   # un objet
```

Backend SQLite, une seule table : `kv_storage(collection TEXT, id TEXT, contenu_json BLOB, PRIMARY KEY(collection, id))`. Ce schéma single-table remplace l'ancien backend per-collection. Migration faite en Sprint 3 étape 2.

**Convention** : pas d'opérations atomiques fines. Pour modifier : `data = charger() ; data[k] = ... ; sauver(data)`. Risque de race conditions en multi-thread (non-pertinent aujourd'hui, à revoir en multi-tenant).

---

## 3. Conventions et patterns

### 3.1 Naming

- Modules : `tendia_<role>.py` pour les modules principaux (sourcing, classification)
- Sinon : `<role>.py` (analyse, stockage, organisme, ...)
- Fichiers de config : `_preset.json`, `_taxonomie_domaines.json` (préfixe `_`)
- Variables : snake_case
- Constantes : MAJUSCULES_SNAKE_CASE

### 3.2 Codes domaines

Format `<famille>_<sous_domaine>` :
- `btp_gros_oeuvre`, `btp_voirie_reseaux`
- `it_developpement_web_app`, `it_infrastructure_cloud`
- `conseil_strategie_organisation`, `conseil_juridique`

La famille est déduite du préfixe (avant `_`) dans l'Explorer UI. Voir `_FAMILLES_RACINE` dans `tendia_ui.py`.

### 3.3 Idempotence

Toutes les commandes Tendia sont **idempotentes** : on peut relancer sans risque, le cache empêche la duplication.
- `tendia_classification.py` : skip si déjà classifié (sauf `--force`)
- `enrichir_complet.py` : skip si brief existe (sauf `--force`)
- `analyse.py` : skip si score existe (sauf `--force`)

### 3.4 Gestion API key Anthropic

`llm_extract.py` contient `_check_anthropic()` qui :
1. Cherche `ANTHROPIC_API_KEY` dans `os.environ`
2. Sinon, lit depuis `.env` ou `.env.txt` à la racine (Windows Notepad ajoute parfois `.txt`)
3. Gère le BOM UTF-8 ajouté par Notepad (encoding `utf-8-sig`)

Tous les autres modules délèguent à cette fonction pour la cohérence.

### 3.5 Modèles LLM utilisés

| Module | Modèle | Pourquoi |
|---|---|---|
| `tendia_classification.py` | Haiku 4.5 | Tâche simple, coût primordial |
| `llm_extract.py` (brief) | Sonnet 4.6 | Qualité d'extraction critique |
| `llm_calibration.py` | Sonnet 4.6 | Raisonnement multi-source |

Pour basculer un modèle, modifier la constante `MODELE` en haut du fichier.

### 3.6 Coût LLM

Le coût est calculé en EUR via le mapping `PRICING` dans chaque module, basé sur USD pricing × 0.92 (taux de change indicatif). Stocké dans `_meta.cout_eur` de chaque entrée pour traçabilité.

Budget global suivi via `budget.json` (kill-switch si dépassement).

### 3.7 Backward compatibility

Les schémas JSON évoluent. Convention : nouveau champ = optionnel, ancien champ = supporté en lecture.

Exemple Sprint 2 : `domaines_metier` est un nouveau champ dans `briefs_extraits`. Les anciens briefs sans ce champ sont lus normalement (fallback sur null).

---

## 4. État de la base données

Au 12 juin 2026 :

```sql
-- Collections principales
marches                  : 422 entrées
classifications_ia       : 421 entrées (Sprint 2)
briefs_extraits          : ~13 entrées (à enrichir mutualisé)
extractions_calibrees    : ~13 entrées
scores_matching          : 2532 entrées (422 marchés × 6 presets)
cycle_marche             : variable selon usage

-- Stockage physique
data/tendia.db           : ~80 Mo
data/dce_archives/       : ~500 Mo (DCE téléchargés)
data/extractions_calibrees/ : ~50 Mo (calibrations sourcées)
```

Backup recommandé : copie SQLite avant tout sprint lourd (déjà en place chez Younes).

---

## 5. Tests et debug

### 5.1 Pas de framework de tests automatisés

Tendia n'a pas (encore) de pytest. Les "tests" sont des CLI utilitaires :
- `tester_profils.py` — Crée des profils tests et bascule entre eux
- `audit_classifications.py` — Audit des classifications LLM
- `connecteurs/diagnostic_*.py` — Diagnostic des plateformes DCE

À ajouter dans un sprint futur : `pytest` sur les fonctions pures (matching, classification logique).

### 5.2 Logs

Pas de framework de logs structuré. Les modules utilisent `print(...)` pour les sorties CLI. À refactorer en `logging` standard si volume croissant.

### 5.3 Debug commun

**Marché non pertinent attendu ?**
```python
# Voir le détail du score
import stockage
scores = stockage.charger("scores_matching")
print(scores.get("BOAMP-26-XXX__formation"))
```

**Classification semble fausse ?**
```python
import stockage
classifs = stockage.charger("classifications_ia")
c = classifs.get("BOAMP-26-XXX")
print(c.get("raison_classification"))
print(c.get("domaines_metier"))
```

**Reclassifier avec Sonnet (plus précis)** :
```bash
python tendia_classification.py --id BOAMP-26-XXX --force --modele sonnet
```

---

## 6. Performance

### 6.1 Goulots d'étranglement connus

- **Téléchargement DCE** : 30-90s par marché (3-15 Mo de PDFs)
- **Brief LLM** : 10-25s par marché (Sonnet 4.6 + DCE volumineux)
- **Calibration LLM** : 8-15s par marché

Mitigation : tout est asynchrone par marché (pas par utilisateur). Le pipeline est conçu pour tourner en batch nocturne.

### 6.2 SQLite limits

SQLite tient confortablement jusqu'à ~50 000 entrées par collection avec les patterns actuels (charger-tout-en-mémoire). Au-delà : passer à PostgreSQL en Chantier E.

---

## 7. Points d'extension

### 7.1 Ajouter un preset

1. Créer `presets/<code>/_preset.json` avec la structure documentée (section 2.5)
2. (Optionnel) Ajouter de nouveaux codes dans `_taxonomie_domaines.json`
3. Relancer `python analyse.py --force` pour recalculer les scores

Effort : 30 min à 1h.

### 7.2 Ajouter un domaine taxonomie

1. Éditer `presets/_taxonomie_domaines.json`
2. Bumper `_meta.version`
3. Mettre à jour les presets concernés si besoin (ajouter le nouveau code dans `domaines_acceptes`)
4. Relancer `python tendia_classification.py --force` pour reclassifier
5. Mettre à jour `_FAMILLES_RACINE` dans `tendia_ui.py` si la famille n'est pas mappée

### 7.3 Ajouter une source de marchés

1. Créer `connecteurs/<source>.py` avec une fonction `lister_marches(...) -> list`
2. Normaliser vers le schéma Tendia (voir `boamp.py` comme modèle)
3. Injecter dans le pipeline d'ingestion

### 7.4 Ajouter un type d'alerte (matching éligibilité)

1. Éditer `matching_exigences.py` pour ajouter le type d'alerte (ex: `surface_minimum`)
2. Mettre à jour les presets concernés dans `clauses_eligibilite`
3. Mettre à jour le profil organisme pour exposer le nouveau champ

---

## 8. Roadmap technique (cf. cadrage_strategique.md)

| Chantier | Impact technique | Effort |
|---|---|---|
| A — Profils sectoriels | Refactor `organisme.py`, `matching_exigences.py`, templates | 4-5h |
| B — Couverture DCE | Refactor `dce_telecharger.py`, intégration solveur captcha | 1-2j/plateforme |
| C — DECP triangulé | Refactor `decp_consolidee.py`, intégration `llm_calibration.py` | 3-4h |
| D — UI commerciale | Refonte `dashboard.html`, `marche.html`, ajout `top_opportunites` | 1-2j |
| E — Multi-tenant | Auth, Postgres, séparation per-organisme | 1-2 sem |
| F — Pipeline auto | APScheduler, monitoring, alertes | 2-3j |

---

## 9. Anti-patterns à éviter

### 9.1 Ne pas hardcoder sectoriellement

**Mauvais** : `if marche.get("cpv_principal", "").startswith("80"):  # formation`
**Bon** : `if preset.code_actif() == "formation":` ou via `classification_ia`

Le code Python ne doit avoir aucun terme métier dur (Qualiopi, Qualibat, etc.). Tout passe par `_preset.json`.

### 9.2 Ne pas mélanger les niveaux d'abstraction

**Mauvais** : Mixer logique métier et stockage SQLite dans la même fonction
**Bon** : Modules métier (`analyse.py`) appellent `stockage.charger/sauver()` qui isole SQLite

### 9.3 Ne pas oublier la backward compatibility

Si on change un schéma JSON, fournir un fallback de lecture pour les anciennes entrées.

### 9.4 Ne pas modifier directement les briefs/calibrations existants

Ces fichiers sont coûteux à régénérer (LLM). Pour modifier en masse : créer une migration explicite.

### 9.5 Ne pas confondre matching et éligibilité

- **Matching** = "ce marché correspond-il au SECTEUR du preset ?" (basé classification IA)
- **Éligibilité** = "l'organisme peut-il candidater ?" (basé profil + alertes brief)

Ce sont deux étapes distinctes du pipeline.

---

## 10. Contacts et historique

- **Créateur** : Younes, fork d'Apptia (sept 2025), généralisation en Tendia (mai 2026)
- **Assistance** : Claude (Anthropic) pour développement et architecture
- **Repo** : local `C:\Users\sai-y\Tendia\`
- **Backups** : SQLite copié avant chaque sprint majeur (`data/tendia.db.backup_YYYYMMDD_HHMM`)
- **Sprints** : voir `docs/journal.txt` pour l'historique des sprints

---

**Document maintenu en parallèle de l'évolution du code.** Toute modification structurelle doit être reflétée ici.
