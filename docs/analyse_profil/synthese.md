# Synthèse « Mon entreprise » (analyse du 2026-11-11)

Détail : `exigences_frequence.md` (mesures), `referentiel_pieces.md` (pièces et sources officielles), `parcours.md` et `maquettes/` (écrans).

## 1. Les 10 constats chiffrés

| # | Constat | Chiffre | Conséquence |
|---|---|---|---|
| 1 | Les exigences des acheteurs se rangent presque toutes dans un petit nombre de types, sans LLM | 253 briefs, 4 099 libellés, 57 types, 97,9 % typés par un dictionnaire de motifs | Le « type normalisé » qui manque au brief (rapport d'architecture § 4.2.3) peut être calculé de façon déterministe |
| 2 | Un dossier BTP demande une douzaine de pièces, dont la moitié en candidature | Médiane de 12 pièces par brief BTP ; 437 pièces de candidature sur 80 briefs | L'unité de travail du coffre est la douzaine, pas la centaine |
| 3 | Près d'un tiers des pièces de candidature BTP sont des formulaires que Tendia peut produire seul | 131 sur 437 (30 %) : DC1 71 % des marchés, DC2 64 %, déclaration sur l'honneur 54 %, DUME 31 % | Priorité au préremplissage DC1, DC2 (objectif 1, étape 4) |
| 4 | Un deuxième tiers tient à des renseignements déclaratifs du profil | 263 sur 437 (60 %) avec chiffre d'affaires (58 %), effectifs (48 %), matériel (38 %), références (64 %) | Ces champs existent déjà dans le schéma BTP ; il manque les effectifs par année et l'encadrement |
| 5 | Avec une vingtaine de types de documents déposés, on couvre presque tout | 408 sur 437 (93 %) ; toutes les pièces de candidature de 47 marchés sur 69 | Le coffre atteint l'objectif 2 (« 100 % des pièces de candidature ») sur 2 marchés sur 3 dès sa première version |
| 6 | Les deux documents les plus demandés sont les attestations d'assurance | Responsabilité civile 64 % des marchés BTP, décennale 42 % (5 % hors BTP) | Ce sont les deux premières pièces à savoir lire : période de validité, activités garanties |
| 7 | Les pièces qui expirent vite sont peu citées en candidature, mais dues par l'entreprise retenue | Urssaf 25 %, fiscale 24 % ; validité Urssaf 6 mois ; « moins de 6 mois » lu 15 fois | Les alertes d'expiration portent d'abord sur ces deux pièces et sur les assurances au 31 décembre |
| 8 | Le Kbis reste demandé alors que le SIREN suffit en droit | 16 % des marchés BTP ; « moins de 3 mois » 15 fois sur 20 ; R2143-9 modifié en 2021 | Garder un Kbis récent (gratuit pour le dirigeant) plutôt que discuter |
| 9 | Les qualifications nommées sont minoritaires et dispersées | Qualibat 19 % des marchés BTP, 48 codes distincts, aucun dans plus de 2 marchés ; RGE 6 % ; ISO 2 % ; MASE 0 ; habilitations du personnel 35 % | Ne pas bâtir l'éligibilité BTP sur les seuls codes Qualibat ; traiter les habilitations (AIPR) comme une rubrique à part |
| 10 | Les seuils chiffrés sont rares | Chiffre d'affaires minimum : 10 marchés sur 236 (4 %), de 75 000 € à 70 M€ ; effectif minimum : 2 marchés ; nombre de références : 18 marchés, 3 le plus souvent ; plafond légal du chiffre d'affaires exigible : 1,5 fois le montant estimé depuis le 2026-01-01 | Les questions oui/non pèsent plus que les seuils dans le verdict d'éligibilité |

Limites des mesures : 229 briefs sur 253 datent de juin 2026 (lecture partielle des DCE, pourcentages planchers) ; 80 briefs BTP ; 9 des 509 marchés BTP actifs ont un brief, donc tous les « N marchés ouverts » sont des estimations.

## 2. État actuel et cible

| Sujet | Aujourd'hui | Cible |
|---|---|---|
| Pièces de l'entreprise | Aucune : ni fichier, ni table, ni route de dépôt | Table `coffre_pieces`, fichiers hors git, dépôt en vrac |
| Dates de validité | Chaînes déclaratives (`validite_jusqu`) sans justificatif | Date lue dans la pièce ou saisie, avec source |
| Provenance des champs du profil | Aucune ; estimations indiscernables des valeurs confirmées | Source, date, confiance par champ |
| Type des exigences d'un marché | Libellé libre | Type du référentiel, calculé sans LLM |
| Réponses oui/non | Deux états, invisibles depuis le profil | Trois états (oui, non, inconnu), rubrique dédiée |
| Écran | Formulaire à onglets, bibliothèque de profils, inutilisable à 390 px | « Mon entreprise » : vue d'ensemble, documents, questions, chantiers, chiffres |

## 3. Modèle de données proposé

À valider : toute décision de schéma revient à Younes (CLAUDE.md, interdits).

### 3.1 Table `coffre_pieces` (une ligne par fichier déposé)

| Colonne | Type | Rôle |
|---|---|---|
| `id` | TEXT, clé | Identifiant de la pièce |
| `entreprise_id` | TEXT | Profil propriétaire (`organisme.id`) ; prépare le multi-entreprise |
| `type` | TEXT | Code du référentiel (`assurance_rc`, `decennale`, `kbis`, `urssaf`…), ou `inconnu` |
| `type_source` | TEXT | `lecture`, `humain`, `nom_fichier` |
| `fichier_chemin` | TEXT | Chemin relatif sous `data/coffre/<entreprise_id>/` |
| `fichier_nom_origine` | TEXT | Nom donné par le dirigeant, affiché tel quel |
| `sha256` | TEXT, unique par entreprise | Détection des doublons |
| `taille_octets`, `mime`, `nb_pages` | INTEGER, TEXT, INTEGER | Contrôles et affichage |
| `date_emission` | TEXT (ISO) | Date du document |
| `date_fin_validite` | TEXT (ISO), nul | Date lue, ou calculée (émission + durée du type) |
| `validite_source` | TEXT | `lue`, `calculee`, `saisie` |
| `champs_lus` | TEXT (JSON) | Selon le type : assureur, numéro de contrat, activités, codes Qualibat, SIRET, montants |
| `confiance` | REAL, nul | Confiance de la lecture automatique |
| `lu_par` | TEXT, nul | Modèle ou règle ; renvoi vers `llm_appels` |
| `confirme_le` | TEXT, nul | Confirmation humaine du type et des dates |
| `rattache_a` | TEXT, nul | Chantier (attestation de bonne exécution) ou personne (AIPR, CV) |
| `remplace_par` | TEXT, nul | Pièce plus récente du même type ; l'ancienne reste en historique |
| `depose_le`, `archive_le` | TEXT | Traçabilité ; pas de suppression, archivage |

Le statut (valable, expire bientôt, expirée, à vérifier) se calcule à l'affichage à partir de `date_fin_validite`, `confiance` et `confirme_le` : il n'est pas stocké.

### 3.2 Référentiel des types (fichier, pas table)

| Élément | Proposition |
|---|---|
| Emplacement | `presets/_referentiel_pieces.json`, relu depuis `referentiel_pieces.md` |
| Par type | code, nom affiché, famille, périmètre (général ou BTP), durée de validité habituelle en jours, seuil d'alerte, lien officiel d'obtention, champs à lire, motifs de reconnaissance, « générée par Tendia » ou « à déposer » |
| Usage | Dépôt (liste de correction), statuts, alertes, typage des exigences des briefs, texte des écrans |

### 3.3 Provenance par champ du profil

| Élément | Proposition |
|---|---|
| Forme | Bloc `_provenance` à la racine du profil : `{"<chemin du champ>": {"source", "date", "confiance", "piece_id"}}` |
| Exemple | `"capacite_globale.ca_annuel_n_moins_1": {"source": "saisie", "date": "2026-11-03", "confiance": 1.0}` |
| Valeurs de `source` | `saisie`, `piece`, `annuaire_entreprises`, `decp`, `estimation`, `import` |
| Pourquoi un bloc à part | Les feuilles du profil gardent leur forme : le matching et l'UI lisent les mêmes champs, et les mémoires, qui injectent le JSON entier du profil dans les prompts (§ 5.10), n'ont qu'une clé à retirer |
| Règle de priorité | Une valeur confirmée par un humain n'est jamais écrasée par une lecture automatique ; un écart est signalé |
| Réponses oui/non | `auto_reponses_exigences` accepte `oui`, `non`, `inconnu`, avec la même provenance |
| Ajouts au schéma BTP | Effectifs par année (3 ans) avec encadrement ; personnes d'encadrement (nom, fonction, ancienneté, habilitations avec date de fin) ; matériel avec quantité ; références : lieu, maître d'ouvrage, site occupé, pièce rattachée |

## 4. Découpage proposé en chantiers

| # | Chantier | Contenu | Critère de fin | Dépend de |
|---|---|---|---|---|
| A | Référentiel et typage des exigences | `presets/_referentiel_pieces.json` ; module de typage issu du dictionnaire de `analyse_exigences.py` ; type, validité exigée et « générée ou à déposer » affichés sur la fiche marché | 95 % des pièces des briefs BTP typées, test hors ligne sur un jeu de 200 libellés annotés ; aucune pièce d'un brief de référence sans type | Chantier 2 (briefs en mode document) |
| B | Coffre, version sans LLM | Table `coffre_pieces`, stockage des fichiers, dépôt multiple, type et date saisis ou devinés par le nom du fichier et le texte du PDF, doublons, statuts, alertes locales | Les 12 pièces du profil de démonstration déposées en moins de 10 minutes, statuts exacts, alerte visible à 60 jours, tests hors ligne | A |
| C | Écran « Mon entreprise » | Vue d'ensemble, Mes documents, Questions, Chantiers, Chiffres ; vocabulaire du parcours ; 390 px ; retrait de la bibliothèque de profils côté client | Une personne extérieure réalise seule : déposer un document, répondre aux questions, ajouter un chantier ; aucun défilement horizontal à 390 px ; audit design sans bloquant | B |
| D | Préremplissage par SIRET et provenance | Appel à l'API Recherche d'entreprises, bloc `_provenance`, affichage de l'origine | Un SIRET réel remplit l'identité sans saisie ; chaque champ affiché porte son origine ; test hors ligne sur réponse enregistrée | C |
| E | Lecture automatique des pièces | Règles d'abord, LLM léger en repli, journal `llm_appels`, plafond, confirmation humaine sous un seuil de confiance | Sur 30 pièces de référence : type exact 95 %, date de fin exacte 90 %, coût moyen par pièce mesuré et inférieur à 0,01 € | B |
| F | Injection dans le dossier | Pièces du coffre et formulaires DC1, DC2 préremplis joints au dossier ; contrôle de validité à la date limite de dépôt | Critère du chantier 4 du backlog : les pièces de candidature d'un profil sont injectées dans le dossier du chantier 3 | Chantier 3, B, D |

Ordre recommandé : A, B, C, D, E, F. A et B donnent une démonstration complète sans coût LLM. E peut passer avant D si les démonstrations montrent que la saisie de la date freine.

## 5. Questions à trancher par Younes

| # | Question | Options | Recommandation |
|---|---|---|---|
| 1 | Où stocker les fichiers ? | (a) `data/coffre/<entreprise>/` en local, hors git ; (b) stockage objet dès maintenant ; (c) dans la base | (a) maintenant, derrière un module unique d'accès aux fichiers pour passer en (b) le jour de l'hébergement. Fichiers nommés par leur empreinte, chiffrés au repos côté serveur. Sauvegarde : même question que `data/dce` (chantier 6) |
| 2 | Lire les pièces par LLM ? À quel coût ? | (a) règles seules ; (b) règles puis LLM léger ; (c) LLM toujours | (b). Estimation avec les tarifs de `config_llm.yaml` : une attestation de 1 à 3 pages en texte (2 000 à 6 000 tokens) coûte de l'ordre de 0,005 € avec Haiku 4.5 et 0,001 € avec Gemini flash-lite. Repères mesurés dans `llm_appels` : 0,0062 € par appel Haiku à 5 550 tokens d'entrée, 0,0011 € par appel flash-lite à 7 433 tokens. Douze pièces à l'entrée puis une trentaine de renouvellements par an : moins de 0,30 € par client et par an. Non mesuré : les scans lus en image |
| 3 | Les pièces peuvent-elles partir chez un fournisseur de LLM ? | (a) oui, avec information du client ; (b) non, lecture locale seulement | (a) pour les attestations d'entreprise, avec une phrase claire à l'écran de dépôt ; (b) pour les pièces nominatives (CV, liste des salariés étrangers, pièces d'identité), lues par règles ou saisies |
| 4 | Préremplir par SIRET avec l'API Recherche d'entreprises ? | Oui ou non | Oui. API ouverte, sans clé, 7 requêtes par seconde par adresse IP ; champs lus dans sa description : siège, activité, date de création, tranche d'effectif, dirigeants, finances (`ca`, `resultat_net`), `liste_rge`. Marquer chaque valeur `annuaire_entreprises` ; ne pas écraser une saisie |
| 5 | `coffre_pieces` : table SQL ou collection `kv_storage` ? | (a) table SQL (backlog, chantier 4) ; (b) collection KV | (a), avec ses fonctions d'accès dans `tendia.core.stockage` (CLAUDE.md interdit `sqlite3.connect` ailleurs). Les requêtes par date d'expiration et par type le justifient |
| 6 | Provenance : bloc `_provenance` ou valeur enrichie à chaque feuille ? | (a) bloc à part ; (b) `{valeur, source, confiance}` partout | (a) : aucun lecteur existant à modifier |
| 7 | Typer les exigences à l'extraction (prompt) ou après (règles) ? | (a) champ `type` demandé au LLM ; (b) typage déterministe après coup ; (c) les deux | (b) : reproductible, gratuit, 97,9 % mesurés. Demander en plus au LLM deux champs que les règles lisent mal : la validité exigée et le porteur (candidat, cotraitant, attributaire). Changement de schéma du brief, à décider avec le chantier 2 |
| 8 | Une entreprise, un profil ? | (a) retirer la bibliothèque de profils de l'écran client ; (b) la garder | (a). La bibliothèque reste un outil interne de démonstration |
| 9 | Troisième état « Je ne sais pas » | Oui ou non | Oui, avec le chantier 7 (état « inconnu » distinct de « non détenu ») |
| 10 | Seuils d'alerte | 30, 60 ou 90 jours | 60 jours pour les pièces annuelles (assurances, Qualibat), 30 jours pour les attestations de 6 mois ; rappel le 1er décembre pour les assurances qui finissent au 31 décembre |
| 11 | Que garder des pièces expirées ? | (a) tout, en historique ; (b) purge après N mois | (a) pendant 5 ans pour les pièces d'entreprise ; purge à 12 mois pour les pièces nominatives. Durées à valider (données personnelles) |
| 12 | Limites de dépôt | Taille, formats | 20 Mo par fichier ; PDF, JPG, PNG, HEIC ; pas d'archive compressée |
| 13 | Compter les marchés « débloqués » : estimation ou compte exact ? | (a) estimation dès maintenant, avec « environ » ; (b) attendre le compte exact | (a), puis compte exact quand les briefs en mode document couvriront les marchés BTP actifs (9 sur 509 aujourd'hui) |
| 14 | Le coffre comme « espace de stockage numérique » au sens de l'article R2143-13 | (a) viser cet usage ; (b) s'en tenir à l'injection dans le dossier | (b) pour l'instant : l'usage suppose un hébergement, un accès gratuit pour l'acheteur et des liens durables. À revoir avec l'objectif 8 |
| 15 | Aide humaine affichée au premier accès (numéro de téléphone) | Oui ou non | Oui pendant les démonstrations : c'est aussi le meilleur capteur des blocages |
| 16 | Certificat de la caisse de congés payés du BTP | L'ajouter au référentiel dès la première version ? | Oui : prévu par l'arrêté du 22 mars 2019 (art. 2 III), propre au BTP, absent des libellés mesurés (2 occurrences) |

## 6. Écarts par rapport à la consigne et points à vérifier

| Sujet | Ce qui a été fait | Raison |
|---|---|---|
| Jonction `data/` vers `../Tendia/data` | Non créée | Le worktree suit déjà `data/exemples/` et `data/profils_demo/` : remplacer `data/` par une jonction ferait écrire git dans le dépôt du chantier 2. Inutile par ailleurs : le paquet `tendia` installé pointe sur `D:\Projects\Tendia`, donc `stockage` lit la base de production sans jonction |
| Lecture seule de la base | `stockage.charger` uniquement | À l'ouverture, `stockage` exécute `PRAGMA journal_mode=WAL` et `CREATE TABLE IF NOT EXISTS`, sans effet sur une base existante |
| Sorties du script | Écrites à côté du script (`docs/analyse_profil/` du worktree), pas via `chemins.RACINE_DEPOT` | `RACINE_DEPOT` désigne le dépôt installé, c'est-à-dire le dossier du chantier 2 |
| Taille du script | 857 lignes, dont 230 de dictionnaire | Un seul fichier autorisé ; le dictionnaire part dans le référentiel au chantier A |
| Sources officielles | 25 pages lues ; economie.gouv.fr (DAJ), infogreffe.fr, urssaf.fr, travail-emploi.gouv.fr non lisibles automatiquement | Points concernés marqués « à vérifier » dans `referentiel_pieces.md` § 6 ; aucun contournement tenté |
| Noms de personnes dans les libellés | Masqués dans les CSV et le Markdown (« M. <nom masqué> ») | Les DCE citent parfois un agent de l'acheteur |
| Profil réel | Jamais lu ni cité | Seuls `demo_btp` et des agrégats apparaissent |
| Chiffres fictifs des maquettes | « 38 marchés » qui correspondent, effectifs 2023 et 2024, assureur, dates des pièces | Signalés en pied de chaque maquette |
