# Chantier 1b : UI démo (rapport)

Branche `chantier/1b-ui-demo`, du 2026-11-11. Source : `docs/audit_design/2026-11-10_synthese.md` (branche `audit/design-2026-11` fusionnée dans `main` à l'étape 0). Aucun appel LLM, aucun preset modifié.

## En bref

1. Le profil BTP s'enregistre : le select « Type ouvrage » reprend le vocabulaire du schéma BTP, et chaque erreur nomme son champ. Une référence de chantier a été enregistrée depuis l'UI, dans un vrai navigateur, sur `profil_btp_demo`.
2. Les marchés clos ont une définition unique (`tendia.core.etat_marche`) : date limite passée ou avis d'attribution. Ils sortent des listes, l'explorer leur donne un filtre « Clos », et la fiche affiche « Clos le … ».
3. L'explorer est paginé à 50 cartes. Sur la base réelle, il passe de 6 141 Ko et 2 794 cartes (1,32 s à chaud) à 204 Ko et 50 cartes (0,45 s à chaud).
4. Nouveau verdict `non_classe`, et `matching` lit enfin `classifications_ia`. Le dashboard du profil démo passe de 0 à 145 marchés BTP (3 pertinents, 142 à vérifier), avec un compteur « À classer » séparé.
5. La fiche s'ouvre sur un bloc de décision : verdict et score, « Ce qui vous manque » avec un lien vers chaque section du profil, date limite et jours restants, bouton « Préparer le dossier » inactif. Tests : 27 → 30 fichiers, 667 → 765 vérifications, 100 % vert.

## Points d'attention

- **Le changement le plus important est dans `matching`, pas dans l'UI.** La classification Haiku n'écrivait que dans `classifications_ia`, que `matching.evaluer` ne lisait jamais. Les 1 757 marchés classés au chantier 1 restaient donc `non_pertinent` sauf s'ils avaient un brief : c'est la vraie cause du dashboard vide (point 2 de l'audit). Désormais :
  - `evaluer` reçoit la classification en paramètre ou la lit dans `stockage` ;
  - les presets se résolvent dans l'ordre brief → classification → champs du marché.
  - Effet sur le profil démo : 1 612 non pertinents, 142 à vérifier, 3 pertinents, 0 à classer (tous les actifs sont classés).
- **Le pipeline et la résolution DCE changent de périmètre.** `_est_actif` exclut maintenant les avis d'attribution, ce qui fait passer les actifs de 1 891 à 1 757. Le pipeline ne cherchera plus de DCE pour ces 134 avis. C'est voulu (un marché attribué est clos), mais le comportement change hors de l'UI.
- **Profils en base.**
  - Le profil réel actif (`organisme/principal`, « SEML Transition Euroise Énergies ») a été sauvegardé dans `archive/data/organisme_principal.bak_chantier1b_2026-11-11.json` avant l'activation du profil démo, puis réécrit à l'identique à la fin (comparaison stricte OK). Son id `principal` n'a pas de copie dans la bibliothèque : il fallait passer par la sauvegarde.
  - `profils_bibliotheque/profil_btp_demo` garde la référence ajoutée par l'UI (5 références au lieu de 4). Sauvegarde avant modification dans `archive/data/profils_bibliotheque_profil_btp_demo.bak_chantier1b_2026-11-11.json`.
- **Temps à froid.** Avec les caches de stockage vidés, l'explorer met 1,5 à 1,8 s. Ce temps se répartit ainsi :
  - chargement des 3 collections : 0,88 s, une fois par processus ;
  - compilation du template : 0,26 s, une fois par processus ;
  - matching de 1 835 marchés : 0,79 s, à chaque requête.

  La cible < 1 s est tenue à chaud, qui est le cas courant dans l'UI lancée. La suite logique est un cache du matching par (marché, version du profil) ; c'est hors périmètre, je le propose pour le chantier 7.
- **Dashboard sans limite.** Avec 145 lignes, la page fait 554 Ko et 0,40 s. Le point 7 de l'audit (25 à 50 lignes) n'était pas dans le périmètre.
- **Taille des modules.** `app.py` fait 2 210 lignes, `matching.py` 1 415 et `fiche_marche.py` 1 314, tous au-delà de 800. Le nouveau code du bloc de décision est donc dans un module à part (`ui/bloc_decision.py`, 125 lignes). Le découpage d'`app.py` reste à planifier.
- **Défauts vus sans les corriger (hors périmètre).**
  - « Ville d&#039;Aubervilliers » : l'acheteur est échappé deux fois dans les données.
  - Raison sociale vide dans le sous-titre du dashboard (`identite.nom`, point 16 de l'audit).
  - Textes des motifs sans accents (« Aucun corps d'etat commun ») : ils viennent de `matching.py`.
  - Une fiche réelle (BOAMP-26-105028) met 12,7 s à froid : bloc prix / DECP, à mesurer.

## Hésitations (tranchées seul)

1. **Périmètre « points 1 à 4 et 6 ».**
   - Lu comme les rangs du tableau « 10 corrections » de la synthèse, le périmètre comprend le mobile (rang 4) et le format des montants (rang 6), que le prompt exclut (mobile) ou ne nomme pas.
   - Lu comme les numéros de problèmes, il comprend la sidebar 390 px (n°1), elle aussi exclue.
   - J'ai donc suivi les étapes du prompt : profil (n°4), clos (n°5), pagination (n°6), non classé et état vide (n°2 et 3), bloc de décision (n°7). J'ai ajouté la garde du point 22, reproduite par le test de l'explorer.
2. **Tri « date limite croissante parmi les actifs ».** Appliqué à l'intérieur de chaque groupe de verdict : très pertinent, pertinent, à vérifier, à classer, puis non pertinent ; le score ne sert qu'à départager. Un tri purement chronologique aurait mis en tête de l'explorer des marchés non pertinents qui ferment demain.
3. **« Accessibles par un filtre clos » sur le dashboard.** Le dashboard ne lit aucun paramètre GET. Il affiche « N clos » avec un lien vers `/explorer?etat=clos` plutôt que d'ajouter un second système de filtres.
4. **« Un marché clos reste clos ».** C'est l'UI qui fait primer l'état clos sur le verdict (bloc de décision, explorer). `matching.evaluer` ne renvoie pas de verdict `clos`. Le nouveau verdict `non_classe` change déjà son contrat : `resolution` le gère, mais `scripts/audit/audit_matching_n2.py` l'ignore (voir la suite de l'audit).
5. **Définition de « classé ».** Le prompt dit « pas d'entrée dans `classifications_ia` ». J'ai aussi considéré comme classé un marché qui a un brief avec `domaines_metier`, ou des `preset_codes` / `domaines_metier` posés sur le marché. Sinon, un marché lu en entier (brief complet) sans entrée Haiku serait marqué « à classer ».
6. **Vocabulaire « Type ouvrage ».** Les presets sont en lecture seule et le schéma BTP n'a pas d'`enum`. La liste vient donc de la description du schéma (« Valeurs typiques : … »), complétée par les groupages des cases « Types d'ouvrages » (`profil_widgets`) et par la valeur déjà enregistrée. Ajouter un vrai `enum` au schéma serait plus propre : c'est un changement de schéma, que je propose sans le faire.
7. **`est_attribution`.** Il réunit les trois définitions du dépôt : `nature` « attribution / award », `ContractAwardNotice` (à la racine ou dans `donnees`), `notice_type` « 10 | … ». `scripts/decp/attributions._est_avis` s'appuie maintenant dessus ; le résultat est le même sur la base (247 attributions). Les avis `ANNULATION` (3) ne sont pas « clos », conformément à la question ouverte 5.
8. **Bandeaux des étapes 2 et 4.** Posés d'abord sous le titre, ils ont été repris dans le bloc de décision à l'étape 5 pour ne pas afficher deux fois la même information.
9. **Infobulle du bouton.** Elle dit « Bientôt disponible (chantier 3) ». Le mot « chantier » est du jargon interne, mais c'est le texte demandé.

## Détail

### Point de l'audit → correction

| # audit (synthèse) | Problème | Correction | Fichier:ligne |
|---|---|---|---|
| 4 | Select « Type ouvrage » vide, profil BTP non enregistrable | Options = vocabulaire du schéma + groupages + valeurs enregistrées | src/tendia/ui/profil_widgets.py:303, 316 |
| 19 (partiel) | Erreurs de référence muettes | Message qui nomme le champ, affiché sous le champ et listé en tête ; défilement jusqu'à la 1re erreur | src/tendia/ui/profil_form.py:299, 352 ; templates/profil/_macros.html:111, 125 ; templates/profil/edit.html |
| 5 | Expirés en tête, « J−-104 », pas d'état clos | `etat_marche.est_clos` / `est_actif` / `date_cloture` (définition unique) ; explorer `?etat=` (ouverts par défaut, clos, tous) ; « Clos le … » sur la fiche | src/tendia/core/etat_marche.py:35-90 ; src/tendia/ui/app.py:764 ; templates/explorer.html:498 |
| 5 | Tri sans échéance | Groupe de verdict, puis date limite croissante, puis score (dashboard et explorer) | src/tendia/ui/app.py (tri dashboard et explorer) |
| 6 | Explorer 2 794 cartes / 6,3 Mo | Pagination 50 / page, `?page=`, `?par_page=` ≤ 200, filtres conservés | src/tendia/ui/app.py:709 ; templates/explorer.html:712 |
| 22 | 500 si `raison_classification` vaut None | `(… or "")[:200]` | src/tendia/ui/app.py:883-884 |
| 2 | Non classé = non pertinent, dashboard vide | Verdict `non_classe` ; presets lus dans `classifications_ia` | src/tendia/eligibilite/matching.py:327, 1184, 1281 |
| 2 | Pas de compteur « à classer » | KPI « À classer », badge dédié | src/tendia/ui/app.py:560 ; templates/dashboard.html:40 |
| 3 | État vide faux + commande CLI | 3 cas (pas de profil / aucun ouvert / aucun pertinent) avec liens /explorer et /profil | templates/dashboard.html:280 |
| 7 | Pas de bloc décision | Bloc en tête : verdict + score, manques avec lien profil, date limite + jours, « Préparer le dossier » inactif | src/tendia/ui/bloc_decision.py:71, 96 ; templates/_bloc_decision.html ; templates/marche.html:590 ; src/tendia/ui/app.py:1393, 1619 |
| 12 (partiel) | Aucun lien fiche → profil | Chaque manque pointe sur `…/edit#<section>`, qui ouvre la section | templates/profil/edit.html:559 |

### Mesures de l'explorer

Client de test Flask sur la base réelle, profil `profil_btp_demo` actif, 3 essais par URL : « froid » = caches de stockage vidés, « chaud » = minimum des 2 essais suivants. L'empreinte de `kv_storage` est identique avant et après chaque série (`bcd274ac9bdb8b24`).

| URL | Avant chantier (242c7df) | Après étape 2 (clos masqués) | Après étape 3 (pagination) |
|---|---|---|---|
| `/explorer` | 6 141 Ko, 2 794 cartes, 2,41 s froid / 1,32 s chaud | 3 977 Ko, 1 835 cartes, 1,75 / 0,61 s | **204 Ko, 50 cartes, 1,80 / 0,45 s** |
| `/explorer?page=3` | – | – | 202 Ko, 50 cartes, 0,46 s chaud |
| `/explorer?etat=tous&par_page=200` | – | 6 117 Ko, 2 794 cartes (sans pagination) | 524 Ko, 200 cartes, 1,07 s chaud |
| `/explorer?famille=BTP & travaux` | 1 865 Ko, 855 cartes, 1,94 / 0,46 s | 1 177 Ko, 533 cartes, 1,49 / 0,27 s | 203 Ko, 50 cartes, 0,21 s chaud |
| `/` (dashboard) | 67 Ko, 0 marché, 1,24 / 0,30 s | – | 554 Ko, 145 marchés, 1,39 / 0,40 s (après étape 4) |

Cible < 1 s et < 500 Ko : tenue à chaud pour la vue par défaut. À froid, voir les points d'attention.

### Tests avant / après

| | Avant (main 7d63803) | Après |
|---|---|---|
| Fichiers | 27 / 27 OK | 30 / 30 OK |
| Vérifications | 667 | 765 |
| Nouveaux | – | `test_ui_routes.py` (62 : profil, clos, pagination, non classé, bloc de décision ; client Flask + base temporaire), `test_matching.py` (14), `test_etat_marche.py` (22, dont l'unicité de la définition dans `src/` et `scripts/`) |
| Modifiés | – | aucun test existant modifié ; `test_classification` (20) et `test_rattrapage_btp_octobre` (20) passent sur la nouvelle `est_attribution` |

### Fichiers `data/` retirés du suivi git

Aucun. `git ls-files data/` ne liste que des profils fictifs :
- `data/exemples/profil_btp_demo.json`, `data/exemples/profil_ingenierie_demo.json` ;
- `data/profils_demo/demo_btp.json`, `demo_ing.json`, `demo_it.json` (« Bâti Confiance Construction », « Atelier Ingénierie Durable », « NovaServ IT », sans SIRET).

`data/budget.json` et les données réelles étaient déjà ignorés. Les `profils_demo` restent suivis comme les exemples.

### Captures avant / après (1440 px)

Profil `profil_btp_demo` actif. Masquage repris des scripts de l'audit : profils d'entreprises réelles de la bibliothèque renommés « Entreprise exemple », contacts acheteur remplacés, comparables DECP floutés. Les listes sont coupées à 2 600 px.

| Écran | Avant (audit) | Après |
|---|---|---|
| Dashboard | [dashboard_1440](../docs/audit_design/captures/dashboard_1440.png) | [dashboard_1440](../docs/audit_design/apres/dashboard_1440.png) |
| Explorer | [explorer_1440](../docs/audit_design/captures/explorer_1440.png) | [explorer_1440](../docs/audit_design/apres/explorer_1440.png) · [explorer_clos_1440](../docs/audit_design/apres/explorer_clos_1440.png) |
| Fiche marché | [fiche_marche_1440](../docs/audit_design/captures/fiche_marche_1440.png) (55977) | [fiche_marche_1440](../docs/audit_design/apres/fiche_marche_1440.png) · [bloc de décision](../docs/audit_design/apres/fiche_marche_bloc_decision_1440.png) (105185) |
| Profil (accueil) | [profil_accueil_1440](../docs/audit_design/captures/profil_accueil_1440.png) | [profil_accueil_1440](../docs/audit_design/apres/profil_accueil_1440.png) |
| Profil (édition BTP) | [profil_edition_sect-btp_1440](../docs/audit_design/captures/profil_edition_sect-btp_1440.png) | [profil_edition_1440](../docs/audit_design/apres/profil_edition_1440.png) |

La fiche « avant » (BOAMP-26-55977) est close depuis juillet. La fiche « après » montre un marché ouvert pertinent (BOAMP-26-105185), parce que le bloc de décision d'un marché clos n'affiche que « Clos ».

### Référence de chantier enregistrée depuis l'UI

Playwright sur `python -m tendia.ui` (port 5000), page `/profil/bibliotheque/profil_btp_demo/edit#sect-btp`. Clic sur « ＋ Ajouter une référence », saisie (2025, « Commune exemple », `etablissement_scolaire`, « Réfection de la cour de l'école (démo chantier 1b) », 185 000 €, 3 mois, livré), puis « Enregistrer ». Résultat : redirection et message « Profil « EXEMPLE BTP SAS » enregistré. ». Les 4 références existantes passent avec la nouvelle : 5 références relues dans `profils_bibliotheque` et dans `organisme/principal`.

### Commits

- `242c7df` docs(audit-design): rapports fusionnés dans main
- `059d5a0` fix(ui): liste type d'ouvrage du profil BTP
- `b5cda0b` feat(ui): état clos et tri des listes
- `47f1fe2` perf(ui): pagination de l'explorer
- `8d8982d` feat(matching): verdict non_classe
- `0dff511` feat(ui): bloc décision fiche marché
- étape 6 : docs(chantier-1b): rapport, audit, captures

## Suite de l'audit (archive/AUDIT_1b.md)

Verdict de l'audit : livrable acceptable, aucun constat bloquant. Conformément à la règle (bloquants seulement), aucun correctif de code n'a été fait après l'audit. Seuls deux points ont été corrigés : le sous-titre du dashboard (« triés par verdict puis date limite »), commité avec ce rapport, et deux erreurs factuelles du présent rapport.

Constats majeurs reportés, à reprendre en tête du prochain chantier UI ou au chantier 7 :
1. **URL de pagination.** `app._paginer.url_page` recopie tous les `request.args`. Avec `?_method=` ou `?_anchor=`, l'explorer renvoie une erreur 500 dès qu'il a plus d'une page. Correctif : ne garder que les filtres connus.
2. **Nouveaux avis.** Tant que la classification ne tourne pas dans le pipeline, chaque nouvel avis est `non_classe`, et le dashboard les liste tous, sans limite. Décision produit à prendre : liste séparée ou simple compteur avec lien vers l'explorer.
3. **`audit_matching_n2.py`.** Le script ignore le verdict `non_classe` (listes `VERDICTS` et `cibles`).
4. **Lecture de la base dans `matching.evaluer`.** La fonction lit `classifications_ia` quand la classification n'est pas fournie : une requête par marché, et une exception avalée sans trace. C'est un choix d'architecture fait sans validation, que je soumets ici. Alternative : la classification devient un paramètre obligatoire, passé par les appelants.
5. **Jours restants.** Quand la date limite vient du brief et qu'elle est passée, le bloc de décision peut afficher un nombre de jours négatif.
6. **Taille des modules.** Elle est toujours au-delà de la limite (`app.py` 2 219 lignes, `matching.py` 1 415, fonctions de route de 170 à 290 lignes) : découpage d'`app.py` à planifier.

Les 12 constats mineurs (case « À classer » absente du filtre Verdict, doublons de helpers dans `bloc_decision`, `str()` à ajouter dans `est_attribution`, dates non ISO, tri des clos sur `date_cloture`, `URIError` sur l'ancre, etc.) sont listés dans `AUDIT_1b.md`.
