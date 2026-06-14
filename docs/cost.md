# Économique : coûts LLM & proxy

Coûts réels observés (juin 2026). À actualiser si les tarifs changent.

## LLM (Anthropic)

- **Modèle extraction** : `claude-sonnet-4-6`. Tarifs codés (`llm_extract.py` ~l.755) :
  **3 $/M tokens input, 15 $/M tokens output**.
- **Classification** : Haiku (beaucoup moins cher, métadonnées seules).

### Coût par brief (mesuré)
| Type de brief | Tokens input | Coût observé |
|---|---|---|
| **light** (avis seul) | ~2 000 | ~0,027 € |
| **complet** petit DCE | ~13–25 k | ~0,10–0,20 € |
| **complet** gros DCE (tronqué 400k chars) | ~100–160 k | **~0,40–0,53 €** |

- Le tronquage à `MAX_CHARS_INPUT = 400 000` chars ≈ 100–160 k tokens input → c'est
  le facteur de coût dominant. Un gros DCE coûte ~4× un petit.
- **Échantillon Chantier 1F** : 10 marchés = **4,17 €** (~0,42 €/marché, échantillon
  sur-représentant les gros DCE).
- **Re-extraction Chantier 1G** : plafonnée à 30 € ; ~0,4 €/marché en moyenne.
- **Coût LLM cumulé projet** : ordre de ~25–30 € historique + la re-extraction
  Chantier 1.

### Leviers d'optimisation (non implémentés)
- Tronquage plus malin (prioriser RC/CCAP/CCTP vs annexes graphiques) → moins de
  tokens input sur les gros DCE. Cf `tendia_extraire`/`pdf_extract`.
- Cache de brief par hash de prompt (`prompts_versions`) + `lister_briefs_obsoletes`
  → ne re-extraire que ce qui a changé.
- Modèle moins cher pour les marchés hors-périmètre (peu de valeur).

### Garde-fou
- `budget.py` : kill-switch (plafond/jour, défaut 100 appels) + journal `llm_appels`
  (coût, tokens, modèle par appel). `budget.peut_appeler_llm(...)` avant chaque appel.

## Proxy résidentiel (IPRoyal)

- Activé par défaut sur les downloaders à ban (Dematis, AWS-Achat, achatpublic, forks
  Atexo). Désactivé sur PLACE/BOAMP/data.gouv (`TENDIA_PROXY_FOR_*=0`).
- **Coût = bande passante** (résidentiel facturé au Go ; ~1,75–7 $/Go selon le plan).
- **Batch Dematis (15 marchés)** : ~2,16 Go transités → coût dominé à ~91 % par UN
  marché géant (RATP, DCE ~1,4 Go avec doublons serveur).
- Leviers : dédoublonnage getfile (fait, ~40 % de bande passante économisée),
  cap de taille DCE (écarté pour l'instant — politique « tout télécharger »),
  bypass proxy pour les CDN non protégés (patch `cdn_bypass` côté AWS).

## 2captcha

- ~**0,001 $/captcha** résolu. Batch Dematis (15 marchés) ≈ 16 captchas ≈ 0,016 $.
- Négligeable vs LLM et proxy.

## Synthèse : où va l'argent
1. **LLM extraction des gros DCE** (poste n°1).
2. **Bande passante proxy** sur les gros DCE BTP/EnR (graphiques/BIM).
3. 2captcha : négligeable.
