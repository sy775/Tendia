# Sprint Dematis — Prompt Claude Code

> Tu travailles en autonomie. Livre tout d'un coup, je valide à la fin sur le batch réel.

---

## Contexte

**Tendia** : SaaS veille marchés publics multi-secteurs, Python 3.12 + SQLite, Windows + PowerShell.

Pipeline actuel : 422 avis BOAMP, 184 DCE complet (44%). **Dematis (`e-marchespublics.com`) = 0% complet** sur 21 marchés. 15 sont en `incomplet` avec uniquement le RC scrapé — le DCE complet est accessible par un workflow d'accès anonyme à coder ici.

Plateformes déjà couvertes : AWS-Achat (96%), Achatpublic (87%), PLACE (69%). Pattern à dupliquer depuis `aws_downloader.py`.

---

## Objectif

Créer `dematis_downloader.py` qui récupère le DCE complet (RC, CCAP, CCTP, AE, BPU/DPGF, annexes) sur `*.e-marchespublics.com`.

**Gain visé** : 12-15 marchés passent de `incomplet` à `complet`.

---

## Workflow technique (validé manuellement)

```
A. Page annonce       : /pack/annonce_marche_public_<id1>_<id2>.html
                        → onglets Avis | reglement | dossier | questions | depot
B. Onglet "dossier"   : 3 options de connexion + bandeau bas "ACCÈS ANONYME"
                        → extraire le lien vers /dossier_de_consultation_marche_public_anonyme_<token40>
                        (variante observée aussi : /acces_dce_marche_public_anonyme_<token>)
C. Page anonyme       : captcha image classique (5-6 chars rayés, ex. "c5r2da")
                        + champ texte + bouton "ENVOYEZ"
                        → résoudre via 2captcha (endpoint base64)
D. Liste fichiers     : page avec liens directs vers PDF/DOCX/XLSX/ZIP
                        → télécharger tout, décompresser les ZIPs imbriqués
                        (ex. L1_prod.zip, L2_rés.zip = pièces par lot)
                        → écrire dans data/dce/<marche_id>/
                        → MAJ DB : dce_pieces_contractuelles, dce_contenu='complet'
```

---

## Architecture

Aligne-toi sur `aws_downloader.py` (~36 Ko, à lire en premier). Livrables :

1. **`dematis_downloader.py`** — downloader principal, 4 fonctions étape + orchestration
2. **`retelecharger_dematis_anti_ban.py`** — script batch sur le modèle de `retelecharger_aws_achat_anti_ban.py`
3. **`tests_dematis_downloader.py`** — tests unitaires (parsing HTML, extraction token, mock 2captcha)
4. **Mise à jour `docs/passation_claude.md`** — section couverture plateformes + pattern Dematis

Pas de modification des autres downloaders (`aws_`, `atexo_`, `achatpublic_`). Sprint isolé.

---

## Modules à réutiliser

| Module | Usage |
|---|---|
| `http_humain.py` | Rate-limit gaussien, UA tournants, pauses cumulatives |
| `http_client.py` | Wrapper requests (backend pur, curl_cffi désactivé) |
| `tendia_logs.py` | Logs JSONL → `logs/dematis_<YYYY-MM-DD>.jsonl` |
| `stockage.py` | `charger("marches")` / `sauvegarder(...)` |
| Service 2captcha | Clé déjà dans `.env` (`TWOCAPTCHA_API_KEY`), endpoint image base64 |

Si le solver captcha image existe déjà sous forme réutilisable dans `aws_downloader.py`, extrais-le en module partagé. Sinon, inline dans `dematis_downloader.py` — pas de sur-engineering.

---

## Marchés de test (15 incomplets en base)

```
BOAMP-26-57070  Rénovation ECS Champs Philippe        hautsdeseine-habitat  (workflow validé manuel)
BOAMP-26-56525  Étanchéité toiture CMA Gard           cmar-occitanie
BOAMP-26-56482  RESEAU D'EXPERT 3.0                   martinique-developpement
BOAMP-26-56737  Transports par autocars               mairie-gouvieux
BOAMP-26-56439  Transport usagers déficients          ocens
BOAMP-26-56463  Contrôles assainissement              hydreaulys
BOAMP-26-56303  Assurances CC Val d'Essonne           cc-val-essonne
BOAMP-26-56729  Chèques accompagnement                ccas-calais
BOAMP-26-56469  Réhabilitation RATP Garage Bastille   ratprealestate
BOAMP-26-56712  Ouvrages hydrauliques Piano'cktail    ville-bouguenais
BOAMP-26-56574  Restauration collective SDIS 13       sdis13
BOAMP-26-56842  Centre de secours SDIS 81             sdis81
BOAMP-26-56494  AMO contrat SIAEPA                    siaepa-bonnetan
BOAMP-26-56642  Maintenance chauffage CMA Pays Loire  cmar-paysdeloire
BOAMP-26-56691  Réfection trottoirs Cernay            ville-cernay
```

Cas de référence pour le développement : **BOAMP-26-57070** (validé bout-en-bout manuellement).

---

## Critères d'acceptation

Sprint réussi quand :

- `python retelecharger_dematis_anti_ban.py --max 15 --oui` traite les 15 marchés ; **≥12 passent à `complet`** avec ≥5 pièces (RC + CCAP + AE + 1 BPU/DPGF + 1 annexe minimum)
- `pytest tests_dematis_downloader.py` passe
- `logs/dematis_<date>.jsonl` contient 1 ligne JSONL par marché (`id_marche`, `ok`, `etape_erreur`, `nb_fichiers`, `nb_captcha_resolus`, `duree_secondes`)
- `python stats_pipeline_dce.py` montre Dematis ≥80% complet (vs 0% avant)
- Pas de régression sur les autres plateformes

---

## Pièges connus à anticiper

1. **Encoding HTML** : Dematis déclare UTF-8. Vérifier en début, sinon forcer.
2. **Captcha 2captcha** : endpoint `in.php?method=base64`, polling 5-10s pour la réponse.
3. **Token anonyme** : 2 variantes d'URL observées (`/dossier_de_consultation_marche_public_anonyme_<token>` ET `/acces_dce_marche_public_anonyme_<token>`). Supporter les deux, logger laquelle a été empruntée.
4. **ZIPs imbriqués** : décompresser dans `data/dce/<marche_id>/`, archive originale conservée dans `_zip_archives/` (pattern AWS).
5. **Anti-ban** : démarrer SANS proxy IPRoyal. `proxy_url=""` par défaut. Activable via env var `TENDIA_DEMATIS_USE_PROXY=1` si ban observé en batch.
6. **Sous-domaines** : tous variables (`hautsdeseine-habitat`, `sdis13`, `ratprealestate`, ...). Code générique `*.e-marchespublics.com`, pas de liste hardcodée bloquante.
7. **Cas dégénérés** : DCE expiré → flag, pas crash. Captcha échoué → retry max 2 fois puis abandon. Fichier 404 → continuer les autres.
8. **Le path d'anonyme contient des underscores** entre les mots (séparateur du token, pas un slash).

---

## Contraintes Windows + style

- UTF-8 sans BOM sur tous les fichiers (BOM casse `python-dotenv`)
- `sys.stdout.reconfigure(encoding='utf-8')` en début des scripts CLI
- Pas de `.bak_*` automatique : tu modifies directement, j'ai Git pour rollback
- Style direct comme `aws_downloader.py`, pas de boilerplate inutile
- Pas de docstrings interminables, pas de print verbeux : logs JSONL d'un côté, console concise de l'autre

---

## Format de livraison

Travaille en autonomie, livre tout en un coup à la fin. Pas besoin de me demander validation entre les étapes ni de me faire valider des options en début. Si un point est franchement bloquant (genre 2captcha ne marche pas), tu t'arrêtes et tu me le remontes — sinon tu décides et tu avances.

À la fin, donne-moi :
- Le résultat du batch `--max 15` (combien passés en `complet`, échecs avec raison)
- Un récap de ce qui a été créé/modifié
- Les éventuels points à surveiller pour la suite

Go.
