# Tendia — Passation de session

> Document destiné à un prochain Claude qui reprendra le travail.  
> Younes attendra de toi que tu lises ce document **avant** d'agir, et que tu réfléchisses à voix haute avant de coder.  
> Voir aussi `SPECS_TECHNIQUES_TENDIA.md` pour les détails techniques (schémas, modules, contrats d'interface).

---

## 0. La règle au-dessus de toutes les autres

**L'objectif unique est la qualité du produit.**

Concrètement, cela veut dire :

- **Ne jamais afficher un marché incomplet** à l'utilisateur. Pas de "brief LIGHT en attendant", pas de "tri par richesse". Un marché qu'on ne sait pas analyser proprement n'apparaît pas dans l'UI. Point.
- **Mieux vaut afficher 5 marchés bien briefés que 35 marchés à moitié briefés.** Si on doit perdre du volume pour gagner en qualité, on perd du volume.
- **Pas de "presque bon"**. Un brief sans barème et sans montant n'est pas utile à un commercial qui décide s'il candidate. Si on ne peut pas extraire ces infos depuis le DCE réel, le marché ne passe pas le filtre.
- **Pas de raccourcis qui dégradent la qualité** : Younes refusera systématiquement les solutions qui marchent vite mais produisent du contenu douteux. Si le LLM hallucine sur un document pauvre, on filtre le document avant l'appel LLM — on ne stocke pas un brief approximatif.

Si tu dois choisir entre "plus de marchés mais qualité variable" et "moins de marchés mais qualité garantie", **choisis toujours la deuxième option**. Et si tu hésites, demande à Younes — il tranchera dans le même sens.

---

## 1. Qui est Younes et comment travailler avec lui

### Le contexte humain

- **Younes développe seul** `Tendia`, un SaaS de veille et d'analyse des marchés publics français (multi-secteurs).
- C'est un **fork d'Apptia**, son outil précédent calibré pour les marchés de formation France Travail. Apptia continue de tourner en parallèle.
- Il travaille sur **Windows / PowerShell** dans `C:\Users\sai-y\Tendia\`.

### Ses principes de travail (à respecter strictement)

1. **Qualité maximale > vitesse**. Si une approche est plus longue mais plus propre, c'est celle-là qu'il veut. Ne propose jamais de raccourci, il refusera.
2. **Pas de bullshit, pas de complaisance**. Si tu ne sais pas, dis-le. Si l'approche actuelle a un défaut, dis-le franchement. Younes te corrigera quand tu te trompes — accepte la correction sans flatterie.
3. **Décide-toi avant de coder**. Pose les questions structurantes, propose plusieurs options avec leurs trade-offs, attends sa décision, puis code. Ne pas partir bille en tête.
4. **Livraisons fichier par fichier**. Un fichier modifié = un fichier livré, sauf si plusieurs sont de même nature. Pas de zip global.
5. **Tests progressifs**. Avant tout run coûteux (LLM, scraping massif), il veut un dry-run, puis un test sur `--limite 1` ou `2`, puis l'échelle réelle.
6. **PowerShell**. Tes commandes de test doivent être en syntaxe PowerShell (pas bash). Attention à l'échappement des `"` dans les `python -c "..."` — préfère créer un petit fichier `.py` plutôt qu'un one-liner complexe.
7. **Encodage Windows**. PowerShell par défaut est `cp1252` — pas d'Unicode (`✓`, `⚠`, `→`) dans les scripts diagnostic, ou alors force UTF-8 sur stdout : `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")`.

### Ce qu'il n'aime pas

- Les bullets à la pelle dans un email/message. Réponds en prose quand c'est de la discussion, en tableau ou bullet quand c'est de l'info dense.
- Les "tu as raison c'est une excellente idée" gratuits. Va droit au but.
- Les solutions à "30 % du problème" qui demandent encore 5 sessions pour finir. Quand on attaque un chantier, on le finit ou on dit pourquoi on s'arrête.
- Les briefs vides stockés en base. Si on ne peut pas générer un vrai brief, on s'abstient — on ne pollue pas la collection avec du contenu fade.

---

## 2. État du projet à la fin de la session précédente

### Architecture en place (Sprint 3 + correctifs qualité)

```
BOAMP API (filtre date)
  ↓ tendia_recup.py --large (mode ingestion large, sans filtre acheteur)
  ↓ SQLite collection "marches"
  ↓ analyse.py (matching multi-preset : mots-clés inclusion/exclusion + CPV)
  ↓ SQLite collection "scores_matching"
  ↓ tendia_dce.py (récupère url_dce depuis BOAMP eForms + recherche récursive)
  ↓ tendia_telecharger_dce.py (HTTP GET → PDFs dans data/dce/<id>/)
  ↓ tendia_extraire.py (PDFs → filtre non-DCE → llm_extract → brief COMPLET)
  ↓ SQLite collection "briefs_extraits" (briefs UTILES uniquement)
  ↓ tendia_ui.py (filtre par preset actif)
```

### Modules clés et leur statut qualité

| Module | Statut | Détail |
|---|---|---|
| `stockage.py` | ✅ Stable | Backend SQLite, API stable |
| `budget.py` | ✅ Stable | Kill-switch, quotas, log appels LLM |
| `auto_brief.py` | ⚠ À déprécier | Génère brief LIGHT. Plus utilisé dans le workflow qualité — on veut COMPLET ou rien. |
| `analyse.py` | ✅ Stable | Matching multi-preset |
| `dce_finder.py` | ⚠ Bug connu | Capte parfois `/agent/` au lieu de `/?page=Entreprise...` — cf. § 6 |
| `tendia_telecharger_dce.py` | ⚠ Limitation | Pas d'authentification → DCE protégés par login inaccessibles |
| `tendia_extraire.py` | ✅ Stable | Filtre `_est_pdf_non_dce` actif, ne pollue plus la base |
| `enrichir_complet.py` | ✅ Stable | Orchestrateur, compteurs propres, garde-fou coût |

### Chiffres réels mesurés (fin de session, après correctifs qualité)

Base ingérée : 500 marchés BOAMP en mode large, fenêtre 6 mois.

| Métrique | Valeur |
|---|---|
| Marchés pertinents (au moins un preset matche) | 35 / 500 (7 %) |
| Dont formation | 28 |
| Dont énergie_renouvelable | 7 |
| Avec URL DCE exploitable (qualité directe ou via_keyword) | 23 / 35 (66 %) |
| Briefs COMPLET tentés dans le dernier run | 10 |
| ✅ Briefs COMPLET UTILES (barème ET montant) | 2 |
| ~ Briefs COMPLET PARTIELS (barème seul, montant non communiqué légitime) | 3 |
| ⊘ PDFs non-DCE rejetés avant LLM (économie) | 3 |
| ⚠ Login requis (achatpublic) | 2 |
| ⚠ DUME seul (PLACE accès limité) | 1 |
| ❌ Bug URL `/agent/` | 1 |

**Audit final des briefs en cache : 5 briefs, 100 % au moins partiels, 0 vide.**

### Ce qui marche bien

- **Le filtre `_est_pdf_non_dce`** rejette `depot-pli.pdf`, DUME, PDFs trop petits avant l'appel LLM. La base ne contient plus aucun brief vide. ~0.20€ économisés sur le dernier run.
- **Le téléchargement automatique PLACE** fonctionne quand le DCE est en accès libre (3/4 marchés PLACE testés → brief utile).
- **L'extraction LLM** est honnête : le LLM écrit explicitement "Aucun montant ne peut être estimé" plutôt que d'halluciner.

### Ce qui pose problème

- **Le DCE réel est protégé par login sur la majorité des plateformes** : `marches-publics.info` (~9 marchés pertinents), `achatpublic.com` (~4), parfois aussi PLACE pour certaines pièces.
- **En accès libre, on ne récupère souvent que `depot-pli.pdf`** (guide générique de dépôt, 9137 chars exactement) ou le DUME (formulaire administratif).
- **Conséquence brute** : 5 marchés sur 35 pertinents passent le filtre qualité = **14 % de couverture utilisable**. Inacceptable pour un produit qui se veut une veille opérationnelle.

Coût LLM cumulé sur la session : ~2,93 € (54 extractions). Le rapport coût/valeur n'est pas mauvais sur les briefs utiles, mais le volume de marchés affichables est trop faible.

---

## 3. Le problème central

**Younes a tranché : "je ne souhaite pas afficher de marché incomplet".** Et ce n'est pas négociable.

La cause racine est claire et identifiée : **la majorité des plateformes (`marches-publics.info`, PLACE, `achatpublic.com`) protègent le vrai DCE derrière un login obligatoire**. En accès libre on ne récupère que des documents vides de contenu métier (guide de dépôt ou DUME).

Tant qu'on n'a pas implémenté l'authentification sur ces plateformes, le filtre qualité strict masque la majorité des marchés. **C'est inacceptable au regard de l'objectif produit, et c'est le sujet prioritaire absolu de la prochaine session.**

---

## 4. Plan d'action pour atteindre la qualité cible

**Objectif chiffré** : passer de **5/35 (14 %) → au moins 25/35 (≥ 70 %)** de marchés affichables avec brief COMPLET utile.

### Étape 1 — Login PLACE automatisé (priorité absolue)

**Pourquoi c'est en premier** : PLACE (`marches-publics.gouv.fr`) c'est la plateforme officielle de l'État + nombreuses collectivités. Compte gratuit, inscription par formulaire web. Une fois loggé, accès complet au DCE (RC + CCTP + BPU + annexes). Sur les 23 marchés "URL exploitable" actuels, **9-10 sont sur PLACE** — c'est le plus gros gain possible en une seule action.

**Tâches** :
1. Vérifier avec Younes s'il a déjà un compte PLACE (ou s'il faut le créer).
2. Créer un module `place_login.py` qui :
   - Lit les identifiants depuis `data/credentials.json` (à `.gitignore` impérativement)
   - Effectue le login HTTP et conserve les cookies dans une `requests.Session()`
   - Expose une fonction `obtenir_session_authentifiee() -> requests.Session`
   - Gère la ré-authentification automatique en cas d'expiration de session
3. Modifier `tendia_telecharger_dce.py` :
   - Détecter automatiquement les URLs PLACE et utiliser la session authentifiée pour ces URLs
   - Continuer à utiliser une session anonyme pour les autres domaines
4. Tester sur 2-3 marchés PLACE qui n'avaient que le DUME en accès libre : doivent récupérer RC + CCTP + BPU.
5. Lancer `enrichir_complet.py --max-cout 5.0` et mesurer le nouveau taux via `audit_briefs.py`.

**Effort estimé** : 1 session (2-3 h)  
**Gain attendu** : +8-12 marchés affichables (passage à ~13-17/35 ≈ 40-50 %)  
**Risques** :
- PLACE pourrait avoir un captcha lors du login (vérifier la première fois — sinon il faudra un input manuel ponctuel)
- Les cookies de session expirent → prévoir re-login automatique
- L'URL de login peut changer (typiquement `marches-publics.gouv.fr/?page=...EntrepriseHomeFr`)

**Avant de coder, lui demander** :
- A-t-il déjà un compte PLACE ?
- Où stocker les credentials : JSON local, variable d'env, ou keyring Windows ?

### Étape 2 — Login achatpublic.com (priorité 2)

**Pourquoi** : 4-5 marchés pertinents sont sur achatpublic.com (Action Logement, ESCP, CCAS, etc.). Login obligatoire dès l'accueil de la consultation, donc 100 % de ces marchés sont aujourd'hui inaccessibles.

**Tâches** :
1. Compte gratuit achatpublic à créer (formulaire long, vérifier les CGU SIRET).
2. Module `achatpublic_login.py` similaire à `place_login.py`.
3. Adapter `tendia_telecharger_dce.py` pour détecter le domaine et router vers la bonne session.

**Effort estimé** : 1 session  
**Gain attendu** : +3-5 marchés (passage à ~16-22/35 ≈ 50-65 %)  
**Particularité** : achatpublic exige souvent une déclaration SIRET. À clarifier avec Younes — sinon on bloquera dès la création de compte.

### Étape 3 — marches-publics.info (priorité 3)

**Pourquoi** : 9 marchés observés. Comportement variable selon l'acheteur (certaines collectivités exposent le DCE en accès libre, d'autres exigent un login).

**Tâches** :
1. Échantillonner manuellement 3-4 URLs `marches-publics.info` chez Younes pour comprendre si le login est systématique ou seulement pour certains acheteurs (vérifier en ouvrant les URLs au navigateur).
2. Si systématique : créer un compte + module `marches_publics_info_login.py`.
3. Si optionnel : améliorer le scraping HTML actuel (qui ne récupère que `depot-pli.pdf` en accès libre).

**Effort estimé** : 1-2 sessions selon le diagnostic  
**Gain attendu** : +4-7 marchés (passage à ~22-28/35 ≈ 65-80 %)

### Étape 4 — Améliorer `dce_finder.py` pour les 12 "absente"

12 marchés pertinents n'ont actuellement aucune URL DCE exploitable. Diagnostic à faire avant de coder : pour chacun, aller voir l'avis BOAMP sur le site officiel et vérifier si l'URL DCE existe dans le payload eForms mais dans un chemin que `_chercher_urls_dans_eforms()` ne couvre pas.

**Effort estimé** : 1-2 sessions  
**Gain attendu** : +2-5 marchés (passage à ~24-33/35 ≈ 70-95 %)

### Étape 5 — Fix bug `/agent/` dans `dce_finder.py`

Le marché BOAMP-26-56214 a une URL `https://www.marches-publics.gouv.fr/agent/` captée par `dce_finder.py`. C'est l'interface acheteur (pas l'interface entreprise) — donc le téléchargeur récupère une page d'accueil, pas un DCE.

**Tâches** :
1. Dans `dce_finder.py`, ajouter à `_est_url_specifique()` une exclusion explicite des paths `/agent/`, `/admin/`, `/profilacheteur/` qui ne sont pas des URLs entreprise.
2. Ou alors filtrer dans la recherche récursive `_chercher_urls_dans_eforms` les URLs contenant `/agent` ou `/admin`.

**Effort estimé** : 30 minutes  
**Gain attendu** : +1 marché (anecdotique) mais évite des téléchargements en erreur

### Étape 6 — Filtre UI strict "marché complet uniquement"

Une fois la couverture remontée au-dessus de 70 %, implémenter le filtre UI demandé par Younes.

**Tâches** :
1. Dans `tendia_ui.py`, fonction `dashboard()`, ajouter un filtre : un marché n'apparaît que si son brief en cache satisfait des critères de qualité minimale.
2. Critères proposés :
   - `_meta.type == "complet"`
   - ET au moins un de `bareme_notation.valeur_technique_pct` ou `montant_marche.valeur_estimee_euros` non null
3. Indicateur visible dans le dashboard : "X marchés pertinents en attente de complétion DCE" → Younes voit qu'il y a des opportunités à traiter manuellement.
4. Optionnel : page séparée "À enrichir" listant les marchés masqués, avec leur URL DCE pour téléchargement manuel par Younes.

**Important** : ne PAS implémenter étape 6 avant les étapes 1-3, sinon le dashboard sera presque vide.

### Étape 7 — Automatisation (plus tard)

- Tâche planifiée Windows : `tendia_recup.py --large` + `analyse.py` + `enrichir_complet.py` tous les matins.
- Alertes mail si nouveaux marchés pertinents.
- Réingestion incrémentale (ne pas re-télécharger les marchés déjà connus).

---

## 5. Ordre d'exécution recommandé

1. **Étape 1 — Login PLACE** (priorité absolue, gros gain rapide)
2. **Étape 5 — Fix `/agent/`** (30 min, à caser en marge de l'étape 1)
3. Mesurer le nouveau taux. Si ≥ 50 % avec PLACE seul → considérer si étape 2/3 vaut le coup
4. **Étape 2 — Login achatpublic** (gain solide, effort moyen)
5. **Étape 4 — `dce_finder.py` étendu** (gain modéré, effort court)
6. **Étape 3 — marches-publics.info** (gain modéré, effort variable selon diagnostic)
7. **Étape 6 — Filtre UI strict** (à faire seulement quand la couverture est ≥ 70 %)

---

## 6. Pièges techniques connus (à éviter dès le départ)

### Bug URL `/agent/` (à fixer en priorité, cf. étape 5)

Sur PLACE, `dce_finder.py` capte parfois `https://www.marches-publics.gouv.fr/agent/` qui est l'interface acheteur, pas entreprise. Le téléchargeur tente ensuite une page d'accueil et échoue. À filtrer dans la recherche récursive.

### Credentials

- **Ne JAMAIS committer** `data/credentials.json`. Ajouter à `.gitignore` dès le premier commit.
- Format proposé : `{"place": {"email": "...", "password": "..."}, "achatpublic": {...}}`.

### Scraping et rate limiting

- PLACE et achatpublic ont des seuils de rate limiting. Sleep entre requêtes (1-2 sec).
- Ne pas marteler en cas d'erreur — backoff exponentiel.

### Tests sans coût

- Toujours `--dry-run` puis `--limite 1` ou `2` avant un run à l'échelle.
- Kill-switch budget (`data/budget.json` → `kill_switch_global: true`) pour tester sans payer.

### Affichage en cours de run

- Téléchargement + extraction LLM peut prendre 1-3 minutes par marché. Toujours `flush=True` sur les prints, sinon Younes croit que c'est planté.

### Briefs et SQLite

- Toujours lancer `python audit_briefs.py` après un run pour vérifier la qualité réelle des briefs générés.
- Si tu modifies un brief à la main dans `data/extractions/<id>.json`, pense à aussi mettre à jour SQLite (ou purger SQLite pour forcer le fallback disque).

### PowerShell quirks

- Encodage cp1252 par défaut → forcer UTF-8 dans tout script affichant du français.
- Pas de Python one-liner complexe avec des `"` imbriqués → mettre dans un fichier `.py`.

---

## 7. Commandes utiles pour reprendre le contexte

```powershell
cd C:\Users\sai-y\Tendia

# Vue d'ensemble
python stockage.py                           # état des collections SQLite
python analyse.py --stats                    # stats matching multi-preset
python budget.py                              # coûts LLM cumulés
python audit_briefs.py                        # qualité des briefs en cache (utile/partiel/vide)
python diagnostic_dce_pertinents.py           # ratio URL exploitable sur pertinents

# Ingestion + analyse (pas de coût LLM)
python tendia_recup.py --large --limite 100  # 100 marchés BOAMP
python analyse.py                             # matching multi-preset

# Diagnostic DCE
python tendia_dce.py                          # remplit url_dce dans les marchés
python diagnostic_dce_pertinents.py           # ratio URL exploitable sur pertinents

# Enrichissement brief COMPLET (coûte de l'argent)
python enrichir_complet.py --dry-run          # affiche la liste des candidats
python enrichir_complet.py --limite 2 --max-cout 1.0  # test prudent
python enrichir_complet.py --max-cout 5.0     # batch
```

---

## 8. Questions à poser à Younes au démarrage de la prochaine session

1. **A-t-il déjà un compte PLACE ?** (`marches-publics.gouv.fr`)
2. **A-t-il déjà un compte achatpublic.com ?**
3. **A-t-il un SIRET / structure légale** pour créer les comptes côté plateformes (souvent demandé) ?
4. **Comment stocker les credentials** : JSON local (`data/credentials.json`), variables d'env, ou keyring Windows ?
5. **Tolérance d'itération** sur le login PLACE : si le formulaire web change ou utilise un captcha, faut-il prévoir un mode "login manuel + récupération de cookies" en fallback ?

Ne pas commencer à coder le login avant d'avoir ces réponses. Si Younes n'a pas les comptes, lui faire créer pendant que tu prépares le code.

---

## 9. Mantra à garder en tête

> L'objectif unique est la qualité du produit.  
> Un marché sans brief utile = un marché qu'on ne montre pas.  
> Si on hésite entre "moins de marchés mais bien traités" et "plus de marchés mais incertains", **on choisit toujours moins de marchés bien traités**.  
> Si tu as un doute, demande à Younes — il tranchera dans le sens qualité.
