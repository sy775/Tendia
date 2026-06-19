# Inventaire pipeline — à régler avant le run end-to-end

Analyse de fond (17/06) avant de relancer la pipeline de bout en bout (coûteuse en €).
Objectif : tout fiabiliser AVANT de dépenser, pour ne le faire qu'une fois.

---

## A. Déjà réglé cette session (pour mémoire)

| Domaine | Correctif | Commit |
|---|---|---|
| Extraction | Surrogates UTF-8 (crash gros DCE) | bc7eb37 |
| Extraction | Fourchette Voie 2 mono-dimension (plus de fourchettes énormes) | bc7eb37 |
| Extraction | Quota journalier d'appels cumulatif (déblocage re-extraction) | + streaming + max_tokens 32000 |
| Extraction | Normalisation dérivation critères (fausses alertes somme) | cc0609c |
| UI | Synchro `montant_marche ← montant_3_voies` (affichage montant) | (montant) |
| UI | Fourchette montant dans le KPI + durée (`volumes.duree_marche_mois`) + `publics_cibles` dict brut | af4b270 |
| UI | Retrait « Calibration LLM » (formation-biaisée) | 909ce7a |
| UI | Classification : libellés taxonomie + typos `energia→energie` | adac420 |
| UI | Bloc ingénierie/MOE enrichi (livrables, coordinations, indices) | fc676d8 |
| DCE | Re-qualif des 74 faux-complet → incomplet | a632705 |

---

## B. À RÉGLER avant le run (cœur de l'inventaire)

| # | Problème | Étape | Bloquant ? | Effort |
|---|---|---|---|---|
| **P1** | **Routage download** : le wrapper `telecharger_pieces_dce` ne déclenche PAS le `completeDownload` Atexo/achatpublic pour les URL PLACE (`?page=…AdvancedSearch&id=…&orgAcronyme=…`) → il scrape **1 pièce (le RC)**. Les downloaders **dédiés** (`atexo_downloader.telecharger_dce`, `achatpublic_downloader`) marchent (testé : zip 2,5 Mo et 20,8 Mo). | DCE download | 🔴 **OUI** — sans ça le re-download ne ramène que le RC | moyen |
| **P2** | **`qualifier_dce` faux-complet** : marque « complet » dès ≥2 *types* de pièces détectés (potentiellement dans un zip / via noms), pas sur les **fichiers réellement exploitables** → 74/217 faux-complet. À durcir, sinon les futurs crawls répètent le bug. | DCE qualif | 🟠 OUI (récurrence) | moyen |
| **P3** | **Résolution preset / typos** : le LLM produit parfois `energia_…` ; `_resoudre_presets_pour_marche` / `presets_pour_domaines` ne normalisent PAS → mauvais preset → mauvais schéma d'extraction (10 briefs). Codes stockés normalisés (fait), mais pas la résolution. | Classification | 🟠 moyen (futurs) | petit |
| **P4** | **Sous-extraction MOE/ingénierie** : `livrables_par_phase` et `taux_remuneration_moe_pct` restent vides malgré le schéma et la règle. Durcir l'instruction (forcer le remplissage si les phases sont identifiées). À **valider sur 1-2 briefs** avant batch. | Extraction LLM | 🟡 qualité | petit |
| **P5** | **`url_consultation_dce_directe` PLACE = page de recherche** : l'`EndpointID` extrait est l'URL « AdvancedSearch » (le lien UI tombe sur la recherche). On a `id`+`orgAcronyme` dedans → on peut construire l'URL `EntrepriseDetailsConsultation` propre pour l'affichage. | Enrichissement/UI | 🟡 cosmétique | petit |
| **P6** | **~10 incomplet hors Atexo/achatpublic** (`marches-publics.info`, `e-marchespublics.com`, sans id) → à traiter au cas par cas (downloader dédié ou lien manuel). | DCE download | 🟢 partiel | variable |

---

## C. Volumes à re-traiter (après fixes)

| Lot | Nombre | Action | Coût |
|---|---|---|---|
| Incomplet récupérables (Atexo 46 + achatpublic 33) | **~79** | re-download (P1) → re-qualif → re-extraction v2 | réseau + ~30 € LLM |
| Mauvais preset_utilise | **10** | re-extraction (après P3) | ~4 € |
| Briefs « sans méta » (light/anciens) | **35** | décider : passage v2 ? | ~10 € si oui |
| Incomplet non-récupérables auto | **~10** | P6 cas par cas | — |

⚠️ Overlap : les 74 faux-complet ⊂ les 89 incomplet ⊂ une partie des 79 récupérables. Compter ~80-90 briefs à re-extraire au total une fois les vrais DCE récupérés.

---

## D. Ordre recommandé du run end-to-end (1 seule fois)

1. **Fixes code** (0 €) : P1 (routage downloader), P2 (qualifier honnête), P3 (normalisation preset), P5 (URL consultation), + durcir prompt P4.
2. **Valider P4** sur 1-2 briefs (≈1 €) — confirmer livrables/taux remplis.
3. **Re-download** des ~79 incomplet récupérables (réseau, rate-limité, ~0 € LLM).
4. **Re-qualif** automatique (les nouveaux dossiers complets passent « complet »).
5. **Re-extraction v2** des nouveaux complet + 10 mauvais preset (~30-40 €, cap dur).
6. **Validation finale** (échantillon) avant de déclarer la base propre.

→ Tant que **P1 n'est pas réglé**, inutile de lancer le re-download (il ne ramènerait que le RC). **P1 est la priorité absolue.**

---

## E. Question ouverte pour Younes

- **P6 (~10 marchés)** : si tu vois le bouton « accéder à la consultation » sur ces plateformes, son lien (avec l'id/réf) me permettrait de les câbler. Sinon on les laisse en « incomplet · accès à vérifier ».
- **35 briefs light** : on les passe en v2 dans le run, ou on les laisse tels quels ?
