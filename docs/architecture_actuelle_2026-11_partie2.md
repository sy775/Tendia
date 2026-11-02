# Tendia : architecture actuelle (état au 2 novembre 2026), partie 2/3

> Suite de `architecture_actuelle_2026-11_partie1.md` (méthode, légende [PROD]/[EXP]/[MORT],
> sommaire et faits à retenir en tête de la partie 1). Contenu : §5 Profils entreprise,
> §6 Mémoires techniques, §7 Interface et API.

---

## 5. Profils entreprise

### 5.1 Représentation

Une entreprise cliente est représentée par **un document JSON** (pas de table SQL) stocké dans
`kv_storage`, sous deux collections :

| Collection | Clés | Rôle |
|---|---|---|
| `organisme` | `principal` = **profil actif** (celui que lisent le matching, la fiche et les mémoires) ; `demo_btp`, `demo_ing`, `demo_it` = profils fictifs pour tester les mémoires | 4 objets, 3 937 caractères en moyenne, 8 213 au maximum |
| `profils_bibliotheque` | slug (`exemple_btp_sas`, `profil_btp_demo`, `profil_ingenierie_demo`, `formatix`, `ifpen`, + 1 slug du profil réel) | bibliothèque de N profils, dont un est « actif » par copie dans `organisme/principal` ; 5 130 caractères en moyenne, 8 134 au maximum |

**Mono-utilisateur** : il n'y a qu'un seul profil actif à la fois, aucune notion de compte ni de
tenant, et aucun identifiant SIREN unique imposé. L'`id_user` des mémoires est
`organisme/principal.id` (« principal ») ou l'id d'un profil démo.

**Invariant « lien actif »** (`organisme.py`) : `organisme/principal.id` doit être égal au slug de
l'entrée de bibliothèque (`activer_profil` copie le profil et force `id = slug`).
⚠️ `organisme.ecrire_profil` (CLI, et route `/exigence/repondre`) **force `id="principal"`** et
n'écrit que dans `organisme`. Les réponses aux exigences saisies sur la fiche **ne sont pas
répercutées** dans la bibliothèque, et le lien actif est rompu aujourd'hui
(`organisme/principal.id == "principal"`).

**Validation** : `organisme.valider_profil` (validation maison, sans `jsonschema`) : socle
obligatoire (`id, identite, presets_couverts, profils_sectoriels`) + `required` de chaque schéma
sectoriel. À la création depuis l'UI, seul le socle est validé.

**Format legacy formation** (Apptia) : il est détecté par la présence de `thematiques_metiers` ou
de `directions_regionales_couvertes` au premier niveau ; `matching` route alors vers V1.

### 5.2 Schéma complet

#### Socle (`presets/_socle_profil_organisme.json`, JSON Schema draft-07)

```jsonc
{
  "id": "str  (« principal » ou slug)",
  "_description": "str (positionnement, libre)",
  "_creation": "ISO 8601",
  "_version_schema": "« 1.0 »",
  "identite": {
    "raison_sociale": "str", "forme_juridique": "str",
    "siren": "9 chiffres", "siret_siege": "14 chiffres", "naf_principal": "str (ex 7112B)",
    "effectif_salaries": "int", "annee_creation": "int", "tva_intracom": "str",
    "adresse_siege": {"rue": "", "code_postal": "", "ville": "", "departement": "ex 75"},
    "site_web": "str",
    "contact_AO": {"nom": "", "fonction": "", "email": "", "telephone": ""}
  },
  "zones_intervention": ["codes département (pref.) ou région"],
  "capacite_globale": {
    "ca_annuel_n_moins_1": "num €HT", "ca_annuel_n_moins_2": "num", "ca_annuel_n_moins_3": "num",
    "fonds_propres": "num", "effectif_total_etp": "int",
    "capacite_engagement_simultane": "num €HT", "seuil_minimum_marche_eur": "num"
  },
  "economie": {"marge_brute_cible_pct": "num", "taux_journalier_moyen_eur": "num",
               "frais_de_structure_pct": "num", "agressivite_commerciale": "prudent|neutre|aggressif"},
  "mots_cles_catalogue": ["str"],
  "presets_couverts": ["btp|ingenierie|conseil|it|energie_renouvelable|formation"],   // enum à 6 valeurs seulement
  "profils_sectoriels": {"<preset>": { /* schéma presets/<preset>/_schema.json */ }},
  "auto_reponses_exigences": {"<cle_libre>": "str"}       // « oui »/« non » ou texte de réponse type
}
// required : id, identite, presets_couverts, profils_sectoriels
```
**Champs hors schéma présents en base** (ajoutés par le code ou l'ingestion, non déclarés) :
`domaines_couverts` (codes taxonomie, lus par `matching._eval_domaines_couverts`), `zones_strict`
(bool), `presets_priorites` (`{preset: rang}`), `_fictif`, `_notes_fictif`, et
`references_chantiers` au niveau socle (profils démo).

#### Profil sectoriel BTP (`presets/btp/_schema.json`), required : `qualifications`, `corps_de_metier`

```jsonc
{
  "qualifications": {
    "qualibat": ["codes 4 chiffres"],
    "rge": {"detenue": "bool", "specialites": ["str"], "validite_jusqu": "date"},
    "mase": {"detenue": "bool", "validite_jusqu": "date"},
    "amiante": {"ss3": "bool", "ss4": "bool", "validite_jusqu": "date"},
    "opqibi": ["str"], "iso_9001": "bool", "iso_14001": "bool", "iso_45001": "bool", "autres": ["str"]
  },
  "corps_de_metier": ["enum"], "types_ouvrages": ["enum"], "types_clients_publics": ["enum"],
  "capacite_chantiers": {"ca_btp_annuel": "num", "montant_max_par_chantier": "num",
    "nb_chantiers_simultanes_max": "int", "effectif_chantier_etp": "int", "rayon_intervention_km": "int"},
  "rh_chantier": {
    "encadrement": {"conducteurs_travaux": "int", "chefs_chantier": "int", "chefs_equipe": "int"},
    "operationnels": {"compagnons_qualifies": "int", "ouvriers_non_qualifies": "int", "apprentis": "int"},
    "habilitations_diverses": ["str"]},
  "moyens_materiels": ["str"],
  "references_chantiers": [{"annee": "int", "client": "str", "ouvrage": "str", "type_ouvrage": "str",
    "corps_etat": ["str"], "montant_eur_ht": "num", "duree_mois": "int",
    "statut": "enum(3) ex livre", "notes": "str"}],
  "pratiques_specifiques": {
    "clause_insertion_sociale": {"pratiquee": "bool", "heures_realisees_annee": "int", "partenaires": ["str"]},
    "demarche_environnementale": {"label_rse": "str", "bilan_carbone_realise": "bool",
      "filieres_dechets_tracees": "bool", "materiaux_biosources_pratiques": "bool"},
    "bim": {"pratique": "bool", "niveau_max": "enum(5)"}}
}
```
Les **dates de validité** (RGE, MASE, amiante) sont des chaînes déclaratives, **sans pièce
justificative**. Les enums (`corps_de_metier`, `types_ouvrages`…) sont définis dans le schéma et
regroupés par famille pour l'UI (`profil_widgets.py`).

#### Autres schémas sectoriels (propriétés)

- **ingenierie** (required : `qualifications`, `typologies_couvertes`) : `qualifications{opqibi, opqcm,
  iso_*, autres}`, `assurances{decennale_ingenierie{detenue, plafond_eur, validite_jusqu},
  rc_pro{…}}`, `typologies_couvertes`, `competences_specialisees`, `types_ouvrages_etudies`,
  `types_clients_publics`, `capacite_etudes{ca_ingenierie_annuel, montant_travaux_max_supervisable,
  nb_missions_simultanees_max, effectif_etudes_etp}`, `rh_etudes{encadrement, production,
  architectes_hmonp}`, `outils_logiciels`, `references_etudes[{annee, client, projet, type_ouvrage,
  typologies_mission, competences_mobilisees, montant_travaux_eur_ht, honoraires_eur_ht, duree_mois,
  phases_realisees, statut, notes}]`, `pratiques_specifiques{bim, demarche_environnementale,
  clause_insertion_sociale}`.
- **energie_renouvelable** (required : `id`, `identite`) : style « profil autonome » qui duplique
  une partie du socle : `identite{…}`, `qualifications{rge, qualibat, qualifelec, iso_*, mase,
  habilitations_electriques, garantie_decennale, rc_pro_montant_eur, autres}`,
  `technologies_maitrisees`, `types_prestations`, `segments_clients`, `zones_intervention`,
  `capacite{…}`, `economie`, `mots_cles_catalogue`, `references_chantiers[{annee, client,
  localisation, technologie, puissance_kwc, montant_eur_ht}]`, `auto_reponses_exigences`.
- **formation** (required : `id`, `identite`) : même style autonome (`certifications{qualiopi_*,
  cpf_eligible, datadock…}`, `thematiques_metiers`, `publics_cibles`, …).
- **conseil, it et les 8 presets récents** : **pas de `_schema.json`**. L'éditeur affiche « Sprint D
  à venir ».

### 5.3 Exemple complet : `profils_bibliotheque/profil_btp_demo`

Profil de **démonstration fictif** (le contact nominatif et les coordonnées sont masqués).
Il a été écrit le 2026-06-17 lors de l'activation de l'exemple disque `data/exemples/profil_btp_demo.json`.

```json
{
 "id": "profil_btp_demo",
 "_description": "PROFIL DE DEMO BTP — entreprise generale du batiment 50-100 ETP, region IDF + Hauts-de-France. À adapter avec tes vraies données avant utilisation. Une fois rempli, importer via : python init_profil.py --depuis data/exemples/profil_btp_demo.json",
 "_creation": "2026-06-12T12:00:00+00:00",
 "_version_schema": "1.0",
 "identite": {
  "raison_sociale": "EXEMPLE BTP SAS", "forme_juridique": "SAS",
  "siren": "000000000", "siret_siege": "00000000000000", "naf_principal": "4399C",
  "effectif_salaries": 75, "annee_creation": 2008, "tva_intracom": "FR00000000000",
  "adresse_siege": {"rue": "<masqué>", "code_postal": "93200", "ville": "Saint-Denis", "departement": "93"},
  "site_web": "https://exemple-btp.fr",
  "contact_AO": {"nom": "<masqué>", "fonction": "Responsable Appels d'Offres", "email": "x@x.fr", "telephone": "0X XX XX XX XX"}
 },
 "zones_intervention": ["75","77","78","91","92","93","94","95","59","62"],
 "capacite_globale": {"ca_annuel_n_moins_1": 14500000, "ca_annuel_n_moins_2": 13200000, "ca_annuel_n_moins_3": 11800000,
   "fonds_propres": 3500000, "effectif_total_etp": 75, "capacite_engagement_simultane": 8000000, "seuil_minimum_marche_eur": 80000},
 "economie": {"marge_brute_cible_pct": 12, "taux_journalier_moyen_eur": null, "frais_de_structure_pct": 18, "agressivite_commerciale": "neutre"},
 "mots_cles_catalogue": ["rehabilitation","renovation","gros oeuvre","second oeuvre","etablissement scolaire",
   "etablissement de sante","logement social","patrimoine","amiante","voirie communale"],
 "presets_couverts": ["btp"],
 "profils_sectoriels": {
  "btp": {
   "qualifications": {
    "qualibat": ["1311","2112","2311","3431","4431","5413","6112"],
    "rge": {"detenue": true, "specialites": ["Qualibat RGE 8611"], "validite_jusqu": "2027-09-30"},
    "mase": {"detenue": true, "validite_jusqu": "2027-12-31"},
    "amiante": {"ss3": false, "ss4": true, "validite_jusqu": "2027-06-30"},
    "opqibi": [], "iso_9001": true, "iso_14001": true, "iso_45001": false,
    "autres": ["NF Habitat HQE","Effinergie+"]
   },
   "corps_de_metier": ["gros_oeuvre","demolition","menuiseries_exterieures","menuiseries_interieures",
     "cloisons_doublages","sols_durs","sols_souples","peinture","couverture","etancheite"],
   "types_ouvrages": ["batiment_administratif","etablissement_scolaire","etablissement_sante","logement_social","patrimoine_classe"],
   "types_clients_publics": ["commune","communaute_communes","communaute_agglo","conseil_departemental",
     "conseil_regional","etablissement_public_local","sante_etablissement_local"],
   "capacite_chantiers": {"ca_btp_annuel": 14500000, "montant_max_par_chantier": 6000000,
     "nb_chantiers_simultanes_max": 8, "effectif_chantier_etp": 55, "rayon_intervention_km": 150},
   "rh_chantier": {
    "encadrement": {"conducteurs_travaux": 4, "chefs_chantier": 8, "chefs_equipe": 12},
    "operationnels": {"compagnons_qualifies": 28, "ouvriers_non_qualifies": 6, "apprentis": 4},
    "habilitations_diverses": ["AIPR encadrant","AIPR operateur","Travail en hauteur","CACES R482 cat A/B/C",
      "Habilitations electriques B0/H0","SST"]
   },
   "moyens_materiels": ["pelle 8t (2)","pelle 25t (1)","compresseur 50bar","echafaudage roulant 12m (4 ensembles)",
     "centrale beton 50m3/h mobile","atelier menuiserie integre"],
   "references_chantiers": [
    {"annee": 2025, "client": "Conseil Departemental 93", "ouvrage": "Renovation thermique college Jean-Moulin",
     "type_ouvrage": "etablissement_scolaire", "corps_etat": ["gros_oeuvre","menuiseries_exterieures","etancheite","peinture"],
     "montant_eur_ht": 4200000, "duree_mois": 14, "statut": "livre",
     "notes": "Site occupe pendant travaux, phasage par batiment, clause insertion 800h"},
    {"annee": 2024, "client": "Ville de Saint-Denis", "ouvrage": "Rehabilitation hotel de ville (patrimoine classe)",
     "type_ouvrage": "patrimoine_classe", "corps_etat": ["gros_oeuvre","couverture","menuiseries_exterieures"],
     "montant_eur_ht": 5800000, "duree_mois": 22, "statut": "livre", "notes": "Coordination ABF, materiaux specifiques (pierre de Saint-Maximin)"},
    {"annee": 2024, "client": "Communaute d'agglo Plaine Commune", "ouvrage": "Construction creche 60 berceaux",
     "type_ouvrage": "etablissement_sante", "corps_etat": ["gros_oeuvre","second_oeuvre","menuiseries_interieures"],
     "montant_eur_ht": 2900000, "duree_mois": 11, "statut": "livre", "notes": "Certification BBC, materiaux biosources 30%"},
    {"annee": 2023, "client": "OPH Seine-Saint-Denis Habitat", "ouvrage": "Renovation thermique 80 logements collectifs",
     "type_ouvrage": "logement_social", "corps_etat": ["menuiseries_exterieures","isolation_thermique_exterieure","etancheite"],
     "montant_eur_ht": 3200000, "duree_mois": 9, "statut": "livre", "notes": "Site occupe, phasage par cage d'escalier, clause insertion 600h"}
   ],
   "pratiques_specifiques": {
    "clause_insertion_sociale": {"pratiquee": true, "heures_realisees_annee": 3200,
      "partenaires": ["Mission Locale Saint-Denis","PLIE Plaine Commune","Association ARES SIAE"]},
    "demarche_environnementale": {"label_rse": "Engage RSE AFNOR niveau confirme", "bilan_carbone_realise": true,
      "filieres_dechets_tracees": true, "materiaux_biosources_pratiques": true},
    "bim": {"pratique": true, "niveau_max": "LOD 300"}
   }
  }
 },
 "auto_reponses_exigences": {
  "attestation_russie": "Nous attestons sur l'honneur ne pas etre soumis aux mesures restrictives europeennes vis-a-vis de la Russie au titre du reglement (UE) 833/2014.",
  "visite_obligatoire": "Notre conducteur de travaux et notre chef d'agence se rendront a la visite obligatoire, equipes d'EPI complets et munis d'une piece d'identite a presenter."
 }
}
```

### 5.4 Le profil actif réel (`organisme/principal`), résumé anonymisé

- **Entreprise réelle** (prospect) : SEML locale, ingénierie énergétique / AMO EnR, 8 ETP,
  département de l'Eure. **Pas BTP.** SIREN, SIRET et TVA **vides**.
- Créé par `scripts/maintenance/ingester_profil_tee27.py` (2026-06-19) : **profil saisi en dur
  dans le script Python**. Le script annote lui-même le CA, les fonds propres et la capacité
  comme « **ESTIMATIONS à confirmer** », et le SIREN « à compléter via Sirene/INPI ». Ces
  valeurs **inventées** sont lues par le matching sans aucun marqueur de confiance.
- `presets_couverts = [ingenierie, conseil, energie_renouvelable]`, `presets_priorites`,
  10 départements, `domaines_couverts` en triple (13 codes ×3).
- `auto_reponses_exigences = {"local_bordeaux":"oui", "qualification_bac3":"oui", "ca_min_86100":"oui"}`
  (clés canoniques de `matching_exigences`, d'inspiration formation).

### 5.5 Les autres profils démo

| Collection / id | Raison sociale | Nature | Origine |
|---|---|---|---|
| `organisme/demo_btp` | « Bâti Confiance Construction (BCC) », SAS, 84 ETP, Pays de la Loire | **fictif** (`_fictif=true`) | `data/profils_demo/demo_btp.json`, chargé par `scripts/memoire/generer_memoire.py` |
| `organisme/demo_ing` | « Atelier Ingénierie Durable (AID) », SARL, BET | fictif | `data/profils_demo/demo_ing.json` |
| `organisme/demo_it` | « NovaServ IT », SAS, ESN IDF | fictif | `data/profils_demo/demo_it.json` |
| `profils_bibliotheque/exemple_btp_sas` | « EXEMPLE BTP SAS » | démo (doublon de `profil_btp_demo`) | UI |
| `profils_bibliotheque/profil_btp_demo` | « EXEMPLE BTP SAS » | démo (§5.3) | `data/exemples/profil_btp_demo.json` |
| `profils_bibliotheque/profil_ingenierie_demo` | « Tridyne Ingénierie SAS », BET 52 ETP IDF | démo | `data/exemples/profil_ingenierie_demo.json` |
| `profils_bibliotheque/formatix`, `/ifpen` | — | saisis via `/profil/nouveau` | UI |
| `profils_bibliotheque/<slug réel>` | profil réel (§5.4) | réel | `ingester_profil_tee27.py` |

Les SIREN et SIRET des `demo_*` sont **inventés mais de format valide**.

### 5.6 Ce qui crée et modifie les profils

| Moyen | Détail |
|---|---|
| **UI** `/profil/nouveau` | création en 2 étapes → `organisme.creer_profil_bibliotheque` (validation du socle seul) |
| **UI** `/profil/bibliotheque/<id>/edit` | formulaire par sections (checkboxes groupées, 101 départements par région, sous-formulaire de références) → `profil_form.parse(form, profil_existant)` (**fusion sur l'existant**) → `enregistrer_profil_bibliotheque` |
| **UI** `/profil/<source>/<id>/activer`, `/dupliquer` | copie dans `organisme/principal` ; duplication |
| **UI** `/profil/importer` | **seul upload de fichier de l'application** : un JSON de profil → `importer_profil_json` |
| **UI** `POST /exigence/repondre` | Oui/Non/Effacer sur une exigence de la fiche → `organisme/principal.auto_reponses_exigences[cle]` |
| CLI | `init_profil.py` (`--template`, `--depuis`, `--purger --confirmer`, `--status`), `ingester_profil_tee27.py` (profil codé en dur), `generer_memoire.py` (charge les `demo_*`) |
| Démarrage Flask | `organisme.migrer_bibliotheque_au_demarrage()` (idempotent) |

**Questionnaire** : **aucun questionnaire guidé.** L'équivalent le plus proche est la réponse
Oui/Non mémorisée sur une exigence (`matching_exigences` + `auto_reponses_exigences`), qui se
reporte aux autres fiches présentant la même clé canonique.

### 5.7 Documents rattachés à l'entreprise

**Aucun.** Il n'y a ni Kbis, ni attestations URSSAF ou fiscales, ni assurances, ni certificats
Qualibat, ni CV, ni attestations de bonne exécution : aucun champ de fichier, aucune
collection ni table, aucun dossier dédié, aucune route d'upload. On trouve seulement des
déclarations (booléens, `validite_jusqu` en texte) et des textes types dans
`auto_reponses_exigences`. Les seuls fichiers produits pour une entreprise sont les mémoires
`.docx` (`data/memoires/<id_marche>/<id_user>_lot<n>_<ts>.docx`).

### 5.8 Intégrations de données publiques entreprise

| Source | État | Détail |
|---|---|---|
| **API recherche-entreprises (Sirene)** | **[MORT / archivé]** `scripts/_archive/enrichissement_sirene.py` | `GET https://recherche-entreprises.api.gouv.fr/search?q=<siret>&per_page=1` via `http_utils.get_json`, politesse de 0,5 s. Récupère **le nom** de l'organisme (pour les titulaires DECP). Cache prévu dans la collection KV `titulaires` (**absente de la base** : jamais alimentée ou purgée). Non branché sur le profil. |
| API Sirene INSEE (`api.insee.fr`) | **absent** | — |
| RGE ADEME (`data.ademe.fr`) | **absent** | (la seule occurrence de « ademe » est un acheteur dans `ACHETEUR_VERS_DEPARTEMENT`) |
| INPI / RNE / comptes annuels / BODACC / Pappers / Infogreffe | **absent** | `ingester_profil_tee27.py` mentionne « à compléter via Sirene/INPI » en commentaire |
| Qualibat (annuaire) | **absent** | — |
| **DECP** (historique de l'entreprise comme titulaire) | données **présentes** (`decp_marches`) mais **aucun code** ne construit un historique par SIREN ni ne l'injecte dans un profil | cf. §8ter |
| `connecteurs/decp_consolidee.py` | la docstring évoque un `titulaire_nom` natif, mais **la colonne n'existe pas** dans `decp_marches` | à confirmer : le parseur ignore-t-il ce champ ? |

### 5.9 Extraction de texte libre vers le profil ; provenance

- **Aucun mécanisme** n'extrait d'informations structurées d'un texte libre pour mettre à jour un
  profil : il n'y a ni prompt « profil », ni parsing de chat, ni extraction depuis une plaquette ou
  un Kbis. Les mémoires **lisent** le profil (JSON complet injecté dans les prompts) et, quand une
  information manque, produisent des `[À COMPLÉTER]` **dans le .docx**, sans jamais écrire
  dans le profil. La révision d'une mémoire (`reviser_memoire`, mode « compléter ») intègre des
  « infos du candidat » **dans le texte de la mémoire**, pas dans le profil.
- **Provenance** : **aucune notion de source, de date ou de confiance par champ.** Seuls existent
  `_creation` (au niveau du profil), `cree_le`/`mis_a_jour_le` (au niveau de la ligne
  `kv_storage`), et les marqueurs globaux `_fictif`/`_notes_fictif` des profils démo. Les
  estimations (profil réel) sont indiscernables des valeurs confirmées. Aucun historique des
  versions du profil (écrasement complet à chaque `ecrire`).
- Le parseur de formulaire `profil_form.parse` (**fusion** champ par champ sur l'existant, sans
  perte) est la seule brique proche d'une « mise à jour partielle ». Il est réutilisable pour
  appliquer des faits confirmés.

### 5.10 Champs du profil lus aujourd'hui (à garder compatibles)

**Par le matching** (`matching.py`, V2) :
- socle : `presets_couverts`, `presets_priorites`, `domaines_couverts`, `mots_cles_catalogue`,
  `zones_intervention`, `zones_strict`, `capacite_globale.seuil_minimum_marche_eur`,
  `capacite_globale.capacite_engagement_simultane` ;
- BTP : `profils_sectoriels.btp.qualifications.{qualibat, rge, amiante}` (MASE et ISO ne sont **pas** lus par le matching),
  `corps_de_metier`, `types_ouvrages`, `capacite_chantiers.montant_max_par_chantier` ;
- ingénierie : `qualifications.opqibi`, `assurances`, `typologies_couvertes`,
  `competences_specialisees`, `types_ouvrages_etudies`, `capacite_etudes` ;
- EnR : `technologies_maitrisees`, `types_prestations`, `segments_clients` ;
- legacy formation : `certifications`, `directions_regionales_couvertes`, `prestations_maitrisees`…

**Par `matching_exigences`** : `auto_reponses_exigences`, `identite` (ville du siège),
`certifications`, `mots_cles_catalogue`, `directions_regionales_couvertes`.

**Par l'UI** (`tendia_ui.py`) : `zones_intervention`, `profils_sectoriels`, `domaines_couverts`,
`auto_reponses_exigences`, `identite.raison_sociale`.

**Par les mémoires** : **le profil JSON entier** (`json.dumps(profil)` injecté sous
`{profil_organisme}` dans `extraction_contexte_memoire`, `redaction_memoire` et
`regeneration_section`) ; `identite.raison_sociale` et `id` pour le `.docx` et les clés. Toute
évolution du format (par exemple `{valeur, source, confiance}` à chaque feuille) se verrait donc
**directement** dans les prompts : il faut injecter une **vue aplatie** du profil.

---

## 6. Mémoires techniques

### 6.1 Architecture

Modules : `services/` (le code) et `prompts/` (prompts versionnés `VERSION_PROMPT`).

```
[lazy] DIGEST du lot  services/digest_memoire.generer_digest_memoire_lot(id_marche, numero_lot, …)
        entrées : brief (lots[], bareme_notation) + CCTP filtré par lot (charger_cctp_lot)
        prompt  : prompts/digest_memoire_v1.py   modèle : Sonnet 4.6 (streaming)
        sortie  : kv_storage[digests_memoire/digest_memoire__<id>__lot_<n>]   (mutualisé, réutilisé)
            │
APPEL 1  services/extraction_contexte_memoire.extraire_contexte_memoire(...)
        entrées : profil (JSON complet), brief + lot, digest, texte DCE du lot, grille d'actions
                  (commun.grille_redaction_lot), template acheteur détecté (detecter_template_acheteur)
        prompt  : prompts/extraction_contexte_memoire_v1.py (v1.1)
        sortie  : plan_redaction {cadre_reponse_impose{detecte, fichier_template, structure_resumee},
                  posture_redaction, plan_sections[{section_id, titre, niveau, longueur_cible_pages,
                  objectif, elements_a_couvrir, criteres_lies, contraintes}],
                  elements_a_reprendre_verbatim[{formulation, source}], points_attention_specifiques[]}
            │
APPEL 2  services/redaction_memoire.rediger_memoire_parallele(...)
        UNE requête PAR SECTION du plan (parallèle), prompt prompts/redaction_memoire_v1.py (v1.2),
        max_tokens par section, relance si la sortie est tronquée ou non parsable ; « INTERDICTION D'INVENTER » → [À COMPLÉTER]
        sortie  : sections_redigees {section_id: texte}
            │
ASSEMBLAGE services/assemblage_docx.assembler(memoire, profil, contexte, template_acheteur)
        - template détecté → injecter_template_acheteur(template_path, …) (remplissage du cadre .docx)
        - sinon assembler_tendia : page de garde, sommaire (champ TOC), en-tête/pied, styles,
          tableaux markdown, encadrés « engagement », surlignage des [À COMPLÉTER]
        → data/memoires/<id_marche>/<id_user>_lot<n>_<timestamp>.docx
            │
STOCKAGE kv_storage[memoires_techniques/memoire__<id>__lot_<n>__<id_user>__<ts>]  (cf. partie 1 §2.3)
```

Orchestration : `services/pipeline_memoire.generer_memoire(id_marche, numero_lot, id_user, profil,
force, completer, max_cout_eur, dry_run, verbose, progress_callback)` : `dry_run` (estimation des
2 appels), `max_cout_eur` (abandon si l'estimation dépasse), `completer` (`reviser_memoire` :
sections manquantes seulement), `force`. `services/regeneration_section.regenerer_section`
régénère une section.

UI : `POST /marche/<id>/generer-memoire/<lot>` lance un **thread** (registre des jobs en mémoire
`_MEMOIRE_JOBS`, perdu au redémarrage) ; `GET /memoire-statut/<lot>` (polling JSON) ;
`GET /memoire/<lot>/download`. Mesures : 1 209 s et ~1,26 € par mémoire, ~0,35 € par digest.
Volumétrie : 8 mémoires (4 marchés ; profils `principal` et `demo_*`) et 6 digests.

### 6.2 Détection du template acheteur

`services/extraction_contexte_memoire.detecter_template_acheteur(id_marche)` :
- `os.walk` récursif de `data/dce/<id_marche>/` ;
- **uniquement des `.docx`** dont le nom normalisé contient (`cadre` + `reponse|memoire|technique`),
  (`annexe` + `memoire|technique`), (`modele|modèle` + `memoire|technique`) ou (`trame` + `reponse|memoire`) ;
- s'il y a plusieurs candidats, le **plus volumineux** est retenu. Le texte est extrait, tronqué
  à `MAX_CHARS_TEMPLATE`, puis **confirmé par le LLM** (`cadre_reponse_impose.detecte`) ;
- les `.doc`, `.odt`, PDF et `.xlsx` de cadre ne sont pas détectés. **Les formulaires DC1, DC2,
  DUME et AE ne sont pas visés** : la détection ne concerne que le mémoire technique.

### 6.3 Filtrage du DCE par lot

`digest_memoire._fichier_concerne_lot` / `charger_cctp_lot` : nom de fichier contenant `lot_N`,
`lot N`, `lotN` ou des tokens de l'intitulé ; à défaut, tout le DCE ; plafond d'environ 80 000 tokens
(`cctp_tronque`). Les plans PDF sont inclus (vu dans `cctp_fichiers`).

### 6.4 Réutilisable pour le compagnon

| Élément | Où | Réutilisation |
|---|---|---|
| Filtrage du DCE par lot | `digest_memoire._fichier_concerne_lot`, `charger_cctp_lot` | rattacher les pièces et exigences à un lot (étape 4) |
| Détection d'un cadre imposé | `detecter_template_acheteur` (+ confirmation LLM) | à généraliser à l'AE, au BPU/DPGF et aux cadres en `.doc`/`.xlsx`/`.pdf` (étape 6) |
| Injection dans un `.docx` acheteur | `assemblage_docx.injecter_template_acheteur` | **base du préremplissage de l'AE et des cadres acheteur** (étape 6) |
| Générateur `.docx` maison | `assemblage_docx.assembler_tendia` (styles, TOC, tableaux) | génération de DC1/DC2 aux formats officiels : **à créer** (les modèles officiels ne sont pas dans le repo) |
| `[À COMPLÉTER]`, `elements_manquants_dans_DCE`, `points_attention_*` | digest, plan, rédaction | alimentent les **questions** au candidat (étapes 3 et 5) |
| `grille_redaction_lot`, `grille_actions` | `_memoire_commun`, brief | lien critère → actions, pour le relecteur |
| Jobs asynchrones + polling | `tendia_ui._MEMOIRE_JOBS`, JS de `marche.html` | modèle pour les actions longues de l'agent (registre à rendre persistant) |
| Garde-fous coût (`dry_run`, `max_cout_eur`) | `pipeline_memoire` | à généraliser à tous les appels |

---

## 7. Interface et API

### 7.1 Écrans (Flask `tendia_ui.py`, templates `ui/templates/`)

| Route | Méthode | Template | Contenu |
|---|---|---|---|
| `/` | GET | `dashboard.html` | marchés actifs suivant le matching affiné (`matching.evaluer` à la volée) + verdict d'éligibilité (`matching_exigences`), KPIs |
| `/explorer` | GET | `explorer.html` | tous les marchés : filtres famille / sous-domaine / zone / recherche (y compris par n° d'avis), multi-sélection pertinence / éligibilité / score / brief, tri par richesse, `?complet=1` |
| `/marche/<id>` | GET | `marche.html` (2 393 l.) | **fiche marché** : KPIs, « En bref », verdict en 90 s, contact acheteur, **éligibilité (exigences avec boutons Oui/Non en AJAX)**, lots pertinents, détail par lot, exigences sectorielles, barème, grille d'actions, prix (3 voies, coût, marge, comparables DECP, scénarios), révision, **« Dossier de candidature / Le dossier à déposer »**, remise des offres, documents du DCE, statut DCE + « Re-tenter », **mémoire technique par lot** (génération et suivi) |
| `/marche/<id>/document/<nom>` | GET | — | téléchargement d'une pièce du DCE |
| `/marche/<id>/dce.zip` | GET | — | ZIP du DCE généré à la volée |
| `/marche/<id>/grille.xlsx` | GET | — | export Excel de la grille |
| `/marche/<id>/calibrer` | POST | — | calibration LLM |
| `/marche/<id>/cycle` | POST | — | statut de candidature (`cycle_marche`) |
| `/marche/<id>/retenter-dce`, `/retenter-pieces-manquantes` | POST | — | nouveau téléchargement |
| `/marche/<id>/generer-memoire/<lot>`, `/memoire-statut/<lot>`, `/memoire/<lot>/download` | POST/GET/GET | — | mémoire technique |
| `/marche-notifie/<id>` | GET | `marche_notifie.html` | marché DECP notifié |
| `/decp` | GET | `decp_liste.html` | liste DECP |
| `/concurrence` (alias `/veille`) | GET | `concurrence.html` | veille (collections lues **vides**) |
| `/profil`, `/profil/<source>/<id>`, `/profil/bibliotheque/<id>/edit`, `/profil/nouveau`, `/profil/<source>/<id>/activer`, `/dupliquer`, `/profil/importer` | GET/POST | `profil/*.html` (+ `_macros.html`) | bibliothèque, détail, édition, création, activation, duplication, import |
| `/exigence/repondre` | POST | — | Oui/Non sur une exigence (AJAX `ajax=1` ou redirection) |
| 404 | — | `404.html` | |

### 7.2 Authentification et comptes clients

- **Aucune authentification**, aucun compte, aucun rôle, aucun tenant. Le serveur écoute sur
  `127.0.0.1:5000` uniquement.
- `app.secret_key` est **codé en dur** dans `tendia_ui.py` (valeur non reproduite) et ne sert
  qu'aux messages `flash`. **Aucune protection CSRF.** Serveur Werkzeug de développement.
- La « gestion des comptes clients » se limite à la **bibliothèque de profils** et à l'activation
  d'un profil (§5.6).

### 7.3 API

**Pas d'API REST dédiée.** Les endpoints JSON sont internes à l'UI : `/memoire-statut/<lot>`, et
`generer-memoire` ou `/exigence/repondre` avec `ajax=1`. Aucun versioning, aucune documentation.

### 7.4 Upload de fichiers

**Seulement l'import d'un profil JSON** (`/profil/importer`, `request.files["fichier"]`). Il n'y a
aucun upload de pièces, de DCE ou de documents d'entreprise, et aucun glisser-déposer. Un dépôt
manuel dans `data/dce/<id>/`, côté système de fichiers, reste lu par `tendia_extraire`.

### 7.5 Chat et historique de conversation

**Rien.** Aucun écran de chat, aucune collection ni table de messages, aucune route de streaming
(SSE ou WebSocket), aucune boucle LLM conversationnelle (cf. partie 1 §4.3.4). Les
occurrences de « chat » ne concernent que le contenu des DCE.

### 7.6 Composants réutilisables pour un écran « dossier » (matrice à gauche, chat à droite)

| Besoin | Existant réutilisable | Manque |
|---|---|---|
| Layout, thème | `base.html` (layout, navigation), **Tailwind v4.3 compilé statiquement** (`ui/static/tailwind.css`, 22 Ko) + `apptia-utilities.css` ; styles inline (`<style>`) dans `marche.html` | ⚠️ **aucune configuration ni chaîne de build Tailwind dans le repo** (pas de `package.json` ni de `tailwind.config`) : seules les classes déjà compilées sont disponibles ; de nouvelles classes utilitaires exigent de recréer un build |
| Tableau / matrice | sections de `marche.html` (« Le dossier à déposer », détail par lot, documents en grille) ; aucun composant tableau générique | composant de matrice (lignes = exigences, colonnes = porteurs × lots, cellules à statut) |
| Cartes de confirmation | **boutons Oui/Non d'éligibilité** en AJAX (`fetch(url_for("repondre_exigence"))`, mise à jour sans recharger, `marche.html` l.~2380), messages `flash` | carte « proposition de mise à jour du profil » (valeur, source, confiance, Confirmer/Corriger) |
| Actions asynchrones | génération de mémoire : `fetch` POST, puis polling `memoire-statut` (`marche.html` l.~2032-2039), barre d'étapes | streaming des réponses LLM (SSE), file d'actions persistante |
| Formulaires | macros Jinja `profil/_macros.html` : `checkboxes_groupees`, `zones_intervention` (101 départements par région), sous-formulaires de références `ref_btp_block` / `ref_ing_block` (ajout et suppression en JS), `_ref_input/_ref_select/_ref_checks` ; parseur `profil_form.parse` | — |
| Glisser-déposer de fichiers | **aucun** (pas de `dragover`, `drop`, `FormData` d'upload) ; seul l'import JSON par `<input type=file>` existe | zone de dépôt, upload multipart, aperçu, rattachement à une exigence |
| Téléchargement de pièces | `send_from_directory` (`/document/<nom>`), ZIP à la volée (`/dce.zip`) | pack de dépôt (étape 6) |
| JS | vanilla inline (aucun framework, aucun bundler) | — |

*(Suite : `architecture_actuelle_2026-11_partie3.md`.)*
