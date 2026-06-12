# Tendia

> Plateforme de veille et d'analyse de marchés publics français.
> Sourcing automatisé, classification IA, calibrage prix, qualification d'éligibilité.

---

## Démarrage rapide

### Prérequis

- Python 3.11+
- Clé API Anthropic (Claude)
- 2 Go d'espace disque

### Installation

```bash
# Cloner le repo
git clone <repo_url> Tendia
cd Tendia

# Environnement virtuel (recommandé)
python -m venv .venv
.\.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# Dépendances
pip install -r requirements.txt

# Configuration clé API
echo "ANTHROPIC_API_KEY=sk-ant-XXXX" > .env

# Backup initial
copy data\tendia.db data\tendia.db.backup_initial
```

### Premier lancement

```bash
# 1. Ingestion BOAMP (premier sourcing — ~5-10 min)
python tendia_sourcing.py

# 2. Classification IA (~10-20 min selon volume)
python tendia_classification.py --backfill

# 3. Calcul des scores de matching (~10s)
python analyse.py --force

# 4. Lancer l'UI
python tendia_ui.py
# → Ouvre http://localhost:5000
```

---

## Vue d'ensemble

```
BOAMP / DECP → Ingestion → Classification IA → Matching → Brief LLM → Calibrage prix → UI
```

Tendia traite les marchés publics en chaîne automatisée :

1. **Sourcing** depuis BOAMP (avis de consultation)
2. **Classification** automatique par IA (taxonomie 56 domaines métier)
3. **Matching** contre des presets sectoriels (formation, BTP, énergie, IT, conseil, ingénierie)
4. **Téléchargement DCE** sur les plateformes acheteurs (PLACE, e-marchespublics, etc.)
5. **Brief LLM** détaillé sur le DCE (synthèse, exigences, alertes)
6. **Calibrage prix** triangulé (bottom-up sectoriel + comparables DECP)
7. **Qualification d'éligibilité** par profil organisme

---

## Commandes essentielles

### Sourcing et classification

```bash
# Ingérer de nouveaux marchés BOAMP
python tendia_sourcing.py

# Classifier les nouveaux marchés (Haiku 4.5, ~0.004€/marché)
python tendia_classification.py

# Reclassifier un marché spécifique
python tendia_classification.py --id BOAMP-26-XXXXX --force

# Reclassifier avec Sonnet (plus précis, ~0.01€/marché)
python tendia_classification.py --id BOAMP-26-XXXXX --force --modele sonnet
```

### Matching et briefing

```bash
# Recalculer tous les scores de matching (rapide, gratuit)
python analyse.py --force

# Briefer les marchés pertinents du preset actif
python enrichir_complet.py

# Briefer TOUS les marchés briefables (mode mutualisé multi-clients)
python enrichir_complet.py --mutualise --max-cout 20.0

# Briefer en priorisant certains presets en premier
python enrichir_complet.py --mutualise --max-cout 20.0 `
    --prioriser energie_renouvelable `
    --prioriser btp `
    --prioriser formation

# Dry-run pour estimer le coût
python enrichir_complet.py --mutualise --dry-run

# Briefer 1 marché spécifique
python enrichir_complet.py --id BOAMP-26-XXXXX
```

### Audit et debug

```bash
# Audit complet des classifications
python audit_classifications.py

# Switcher de preset actif
python -c "import preset; preset.basculer_preset('btp')"
python -c "import preset; print(preset.code_actif())"

# Diagnostic plateformes DCE
python connecteurs/diagnostic_plateformes.py
```

### Profils organismes

```bash
# Statut du profil actif
python init_profil.py

# Créer un template vide pour un preset (ex: BTP)
python init_profil.py --template btp

# Importer un profil depuis un fichier JSON
python init_profil.py --depuis data/exemples/profil_btp_demo.json

# Vérifier la validité du profil et son taux de remplissage
python organisme.py --check

# Supprimer le profil actif
python init_profil.py --purger --confirmer
```

Profil multi-secteurs depuis Sprint A : socle commun + profils sectoriels par preset. Format JSON. Validation par `valider_profil()` dans `organisme.py`. Backward compat avec format legacy formation.

### Matching organisme × marché

```bash
# Tester le matching V2 sur tous les marchés en base
python tester_matching.py --top 15

# Détails d'un marché spécifique
python tester_matching.py --details BOAMP-26-XXXXX
```

### UI web

```bash
# Lancer le serveur Flask
python tendia_ui.py
# → http://localhost:5000

# Dashboard       : http://localhost:5000/
# Explorer        : http://localhost:5000/explorer
# Fiche marché    : http://localhost:5000/marche/<id>
# Profil          : http://localhost:5000/profil
```

---

## Structure du repo

```
Tendia/
├── tendia_sourcing.py       # Sourcing BOAMP/DECP
├── tendia_classification.py # Classification IA Haiku (Sprint 2)
├── tendia_extraire.py       # Pipeline brief LLM avec sync classif (Sprint 2bis)
├── tendia_ui.py             # Serveur Flask
├── analyse.py               # Matching marché × preset
├── matching.py              # Matching organisme × marché V2 (Sprint B)
├── tester_matching.py       # Démo matching V2
├── enrichir_complet.py      # Orchestrateur briefs LLM
├── llm_extract.py           # Brief LLM + routage classif + filtre anti-hallucination
├── llm_calibration.py       # Calibrage prix (Sonnet 4.6)
├── matching_exigences.py    # Qualification d'éligibilité (legacy formation)
├── organisme.py             # Profil organisme socle+sectoriel (Sprint A)
├── init_profil.py           # CLI profil
├── preset.py                # Gestion presets sectoriels
├── budget.py                # Module budget LLM (Sprint 3)
├── stockage.py              # Couche SQLite kv_storage (Sprint 3)
├── identifier_briefs_pollues.py # Détection briefs pré-Sprint 2bis
├── regenerer_md.py          # Régénération des MD depuis briefs en base
├── connecteurs/
│   ├── boamp.py             # Connecteur BOAMP
│   └── decp_consolidee.py   # Connecteur DECP
├── presets/                # Presets sectoriels
│   ├── _taxonomie_domaines.json
│   ├── formation/_preset.json
│   ├── energie_renouvelable/_preset.json
│   ├── btp/_preset.json
│   ├── it/_preset.json
│   ├── conseil/_preset.json
│   └── ingenierie/_preset.json
├── ui/templates/           # Templates Jinja
│   ├── base.html
│   ├── dashboard.html
│   ├── explorer.html
│   ├── marche.html
│   └── profil.html
├── data/
│   ├── tendia.db           # Base SQLite principale
│   ├── dce_archives/       # DCE téléchargés
│   └── extractions_calibrees/ # Calibrations sourcées
├── docs/
│   ├── cadrage_strategique.md
│   ├── documentation_technique.md
│   ├── passation_claude.md
│   └── journal.txt
└── .env                    # ANTHROPIC_API_KEY
```

---

## Presets sectoriels actuels

| Preset | Domaines couverts | Statut |
|---|---|---|
| `formation` | 7 (formation pro, insertion, bilan, VAE...) | Stable |
| `energie_renouvelable` | 8 (PV, éolien, biomasse, géothermie...) | Stable |
| `btp` | 5 (gros œuvre, second œuvre, VRD, rénovation, démolition) | MVP |
| `it` | 5 (dev, infra, cybersec, progiciels, maintenance) | MVP |
| `conseil` | 5 (stratégie, juridique, financier, com, SI) | MVP |
| `ingenierie` | 5 (structure, fluides, environnementale, MOE, topo) | MVP |

Voir `docs/documentation_technique.md` pour ajouter un preset.

---

## Coûts indicatifs

| Action | Modèle | Coût unitaire | Volume mensuel typique |
|---|---|---:|---:|
| Classification IA | Haiku 4.5 | ~0.004€ | 1000 marchés = 4€ |
| Brief complet | Sonnet 4.6 | ~0.15€ | 100 marchés = 15€ |
| Calibrage prix | Sonnet 4.6 | ~0.20€ | 50 calibrations = 10€ |
| **Total mensuel régime** | | | **~30€/mois** |

---

## Backup

Avant tout sprint majeur ou modification structurelle :

```powershell
# Windows
$date = Get-Date -Format "yyyyMMdd_HHmm"
Copy-Item "data\tendia.db" "data\tendia.db.backup_$date"
```

```bash
# Linux/Mac
cp data/tendia.db "data/tendia.db.backup_$(date +%Y%m%d_%H%M)"
```

---

## Troubleshooting

### `ANTHROPIC_API_KEY introuvable`

Vérifier que `.env` existe à la racine et contient :
```
ANTHROPIC_API_KEY=sk-ant-XXXXXXXX
```

(sans guillemets, sans espace avant/après le `=`)

### `0 marchés pertinents` après analyse

Vérifier les presets :
```bash
python -c "from pathlib import Path; import json; [print(s.name, len(json.load(open(s/'_preset.json',encoding='utf-8')).get('veille',{}).get('domaines_acceptes',[]))) for s in Path('presets').iterdir() if s.is_dir() and (s/'_preset.json').is_file()]"
```

Si les `domaines_acceptes` sont vides → recréer les `_preset.json` avec les blocs nécessaires.

### DCE non téléchargeable

Voir `docs/cadrage_strategique.md` section "Chantier B — Couverture DCE".
- PLACE (`marches-publics.gouv.fr`) : 73% de réussite
- e-marchespublics : 71%
- DEMATIS (`marches-publics.info`) : 0% (captcha)
- achatpublic : 0% (login)

### Coût LLM élevé inattendu

Vérifier `budget.json` à la racine. Le kill-switch est armé pour bloquer à un seuil mensuel.

---

## Documentation

- **`docs/cadrage_strategique.md`** : Vision produit, roadmap, chantiers, coûts, stratégie commerciale
- **`docs/documentation_technique.md`** : Architecture interne, modules, conventions, extension
- **`docs/passation_claude.md`** : Contexte pour assistant IA (LLM)
- **`docs/journal.txt`** : Historique des sprints

---

## Licence

Propriétaire. Tous droits réservés à Younes.

---

## Contact

Mainteneur : Younes
Repo local : `C:\Users\sai-y\Tendia\`
Version : Sprint 2bis + A + B (matching V2 multi-secteurs) — 12 juin 2026
