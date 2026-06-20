# Passation Tendia — 2026-06-20 (fin de session)

Branche : `feat/decp-sprint-3` · Tout le code est **commité**. Dernier commit : `af3bf51`.

---

## ⏸️ BATCH EN PAUSE — à reprendre

**Réextraction LLM des briefs** avec le **nouveau modèle prix** (coût + CA + marge par lot).

- **Avancement : 31 / 217** marchés réextraits (~14 € dépensés).
- **186 restants.**
- **Prompt courant : `PROMPT_V2_SHA = dad51bcc9270`** (dans `llm_extract.py`).

### Comment REPRENDRE (après rallumage)
```bash
cd /c/Users/sai-y/Tendia
python relancer_extraction_v3.py        # Python SYSTÈME (Python312), PAS le venv
```
C'est **resumable automatiquement** : le script sélectionne les marchés `dce_contenu==complet`
+ DCE sur disque dont le brief n'est **pas** au SHA courant. Les 31 déjà faits sont skippés.
Coût restant estimé ~**80 €** (DCE sur disque → 0 € proxy/captcha). Durée ~1,5–2 h.
Log : `data/reextraction_v3.log`. Rapport final : `RAPPORT_REEXTRACTION_V3.md`.

> Tant que la réextraction n'est pas finie : les fiches des marchés **déjà** réextraits
> affichent le modèle complet (coût + CA + comment c'est calculé) ; les autres affichent
> le CA en fallback (voie_2 / montant_marche) sans détail par lot. C'est normal.

---

## 🧩 LE GROS CHANTIER DE LA SESSION : modèle prix coût + CA + marge par lot

Problème de départ : coût et CA étaient estimés **indépendamment** → incohérences
(3 totaux qui divergeaient, marge bancale, ex 56995). Recadrage fait **avec Younes** :

**Modèle cible (implémenté) :**
- Par lot, l'IA estime **`cout_estime_min/max`** (coût de revient direct, taux chargés)
  **ET** **`ca_estime_min/max`** (prix marché du lot) **ET** **`marge_brute_pct`**.
- Agrégation : `montant_3_voies.voie_2` = Σ CA lots ; `cout_realisation` = Σ coûts lots.
- **Pass de cohérence finale** obligatoire dans le prompt (Σ lots = totaux, CA ≥ coût,
  marges plausibles par archétype, réconciliation sur prix publié).
- Garde-fou de plausibilité de marge par **archétype** (cf. `docs/marge_archetypes_mapping.md` :
  64 codes taxonomie → 8 archétypes).

**Côté fiche (`marche.html` + `fiche_marche.py`) :**
- `somme_ca_lots()` = Σ `ca_estime` (le CA) ; `somme_cout_lots()` = Σ `cout_estime`.
- CA marché = Σ CA lots > voie_2 > montant_marche. Cohérence : total = Σ lots.
- **La MARGE n'est PAS affichée** (décision Younes) — on montre le **CA estimé**, le
  **coût de réalisation**, et **comment chacun est calculé** (« Base du CA estimé » =
  hypothèses voie_2 ; « Décomposition du coût » = postes cout_realisation).
- `marge_brute_pct` reste **calculée et stockée** dans les briefs (réutilisable plus tard,
  ex scoring) — juste pas affichée.

**Validé sur 56995** : marges/lot 15-27 %, Σ coût ≈ cout_realisation, CA cohérent.

### Option B (pas faite, à décider à froid)
Le sourcing des **bandes de marge** par archétype : Younes a déjà obtenu de Claude un
tableau de **marges nettes réalistes** (INSEE Esane / fédés de branche — bien plus basses
que les chiffres marketing : BTP 2-10 %, ingénierie 5-12 %, etc.). On a conclu que la
marge **nette** inclut les coûts indirects non estimables par marché → on n'affiche pas la
marge. Le mapping archétypes (`docs/marge_archetypes_mapping.md`) reste prêt si on veut un
garde-fou de plausibilité plus fin.

---

## 🎨 Autres changements UI de la session (tous commités)

**Explorer** : filtres multi-secteurs cumulables ; zone géo en liste de départements ;
barre « filtres actifs » collante + chips ✕ ; 2e KPI « Marchés pertinents » ;
**sidebar avec scroll dédié** (le bas des secteurs est atteignable) ; largeur 320px ;
compteur poussé à droite.

**Fiche marché** : certif « éliminatoire » + source RC ; tranches v3 ; fourchette estimation
robuste (3 emplacements de données) ; **tags secteur remontés à hauteur du titre « Résumé
Tendia »** (slot droit de la macro `sec(... right=...)`) ; bouton « Accéder à la plateforme »
en **fond crème + bordure dorée + texte gris foncé** ; **couleurs tag pertinence + score
alignées sur le dashboard** (très pertinent=navy, pertinent=vert, à vérifier=or, non pert=gris).

**Profil organisme** : zones larges (boutons **Toute la France / France métropolitaine** +
régions repliables) ; onglet **« Avancé » retiré** ; bouton **import JSON retiré** ;
liseré carte « Profil actif » = **bordure 3px épousant les coins** (style Résumé Tendia).
⚠️ `profil_form.parse` modifié pour **préserver** auto_reponses/formation legacy au save
(sinon le retrait du panel Avancé les effaçait).

**Dashboard** : tooltip du score **plus coupé** sur les dernières lignes (retrait
`overflow:hidden` du conteneur liste).

**Infra** : `http_utils` backoff exponentiel + retry 429 ; `recuperer_tout(differentiel=True)`
= ingestion différentielle (n'ingère que le neuf depuis le dernier avis connu).

---

## ℹ️ Infos pratiques pour reprendre

- **Serveur UI** : `python tendia_ui.py` → http://localhost:5000. `debug=False` →
  **redémarrer le serveur** après toute modif de template/python pour la voir.
  ⚠️ Piège récurrent : mes relances en `&` laissaient des **instances zombies** ; au besoin
  tuer toutes les `tendia_ui` puis relancer UNE seule (`netstat -ano | grep 5000` pour le PID).
- **Python SYSTÈME** (`python` = Python312), PAS le venv (venv sans pypdf/anthropic).
  Clé API dans `.env` (`ANTHROPIC_API_KEY`, `TWOCAPTCHA_API_KEY`, `TENDIA_PROXY_URL` IPRoyal).
- **Ingestion BOAMP** : connecteur OK, mais l'API OpenDataSoft **throttle l'IP** (resets TLS)
  après des rafales — réessayer à froid si « Max retries ». Le backoff durci aide.
  `tendia_veille.py` ingère en mode **legacy** (peu de neuf) ; pour du large :
  `recuperer_tout(mode_large=True, differentiel=True)`.
- Younes parle **français**. Pas de `timeout` sur `Anthropic()`. Gros DCE = appels longs normaux.

## ✅ Prochaines étapes suggérées
1. **Reprendre la réextraction** (`python relancer_extraction_v3.py`) → finir les 186.
2. Vérifier quelques fiches multi-lots après réextraction (CA + coût par lot cohérents).
3. (Optionnel) Ingestion BOAMP différentielle pour tester la pipeline complète quand l'IP
   est calmée.
4. (Optionnel) Médiane comparable : nécessite l'**ingestion de la base DECP** (actuellement
   0 comparable → bloc masqué). L'ancre prix est déjà câblée.
