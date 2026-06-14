"""
audit_mapping_domaines_presets.py
---------------------------------
Audit (LECTURE SEULE) du mapping code domaine → presets, en vue du routage du
futur « Chantier 1 » (sélection du bon prompt sectoriel). NE MODIFIE PAS
`preset.py` : produit `audit_mapping_domaines_presets.md`.

Le mapping est dérivé des presets eux-mêmes : `presets/<code>/_preset.json` →
`veille.domaines_acceptes` / `veille.domaines_optionnels`, consommé par
`preset.presets_pour_domaines(codes)` (acceptés d'abord, puis optionnels).

Mesure :
  1. état actuel (config preset → domaines, + reverse code → presets) ;
  2. codes déclenchant 3+ presets (mapping trop large) ;
  3. proposition de resserrement justifiée ;
  4. impact estimé sur la classification des marchés existants.

Usage : python audit_mapping_domaines_presets.py
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import preset as preset_mod
import audit_classifications as AC

BASE = Path(__file__).parent
SORTIE_MD = "audit_mapping_domaines_presets.md"

# --- Proposition de resserrement (voir justification dans le rapport) ---
# moe_architecte_urbanisme déclenche 3 presets (ingenierie+btp+conseil). On le
# retire de conseil.optionnels (l'architecture/urbanisme MOE n'est pas du conseil
# stratégie/juridique), le laissant en ingenierie (acceptés) + btp (optionnels).
RETRAITS_PROPOSES = [
    ("conseil", "domaines_optionnels", "moe_architecte_urbanisme"),
]


def _charger_configs_presets() -> dict:
    """{code: {acceptes:[...], optionnels:[...]}} depuis presets/*/_preset.json."""
    configs = {}
    d = BASE / "presets"
    for sub in sorted(d.iterdir()) if d.is_dir() else []:
        cfg = sub / "_preset.json"
        if not cfg.is_file():
            continue
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
        except Exception:
            continue
        code = (data.get("meta") or {}).get("code") or sub.name
        veille = data.get("veille") or {}
        configs[code] = {
            "domaines_acceptes": list(veille.get("domaines_acceptes") or []),
            "domaines_optionnels": list(veille.get("domaines_optionnels") or []),
        }
    return configs


def _codes_par_marche() -> dict:
    """{id_marche: [codes]} depuis la classification unifiée (canonique)."""
    unifie = AC._charger_classifications_unifiees()
    out = {}
    for mid, c in unifie.items():
        out[mid] = [code for code, _p, _l in c.get("domaines", [])]
    return out


def _presets_proposes(codes: list, configs: dict) -> list:
    """Réplique presets_pour_domaines avec la config RESSERRÉE (retraits appliqués).
    Conserve l'ordre des presets de preset_mod pour un 'principal' comparable."""
    # config resserrée
    cfg = {k: {kk: list(vv) for kk, vv in v.items()} for k, v in configs.items()}
    for code_preset, champ, code_dom in RETRAITS_PROPOSES:
        if code_preset in cfg and code_dom in cfg[code_preset][champ]:
            cfg[code_preset][champ].remove(code_dom)
    codes_in = [c for c in codes if isinstance(c, str) and c]
    if not codes_in:
        return []
    # même logique/ordre que preset.presets_pour_domaines : on suit l'ordre des
    # presets tel que listé par preset_mod pour garder un 'principal' cohérent.
    ordre = preset_mod.presets_pour_domaines  # ground truth pour l'ordre
    # On déduit l'ordre des presets via un code bidon couvrant tous : à défaut,
    # on parcourt cfg dans l'ordre d'itération de preset_mod._charger_tous_les_presets.
    try:
        presets_tries = [p["code"] for p in preset_mod._charger_tous_les_presets()]
    except Exception:
        presets_tries = list(cfg.keys())
    acc, opt = [], []
    for pcode in presets_tries:
        v = cfg.get(pcode)
        if not v:
            continue
        da = set(v["domaines_acceptes"])
        do = set(v["domaines_optionnels"])
        if any(c in da for c in codes_in):
            acc.append(pcode)
        elif any(c in do for c in codes_in):
            opt.append(pcode)
    vu, res = set(), []
    for c in acc + opt:
        if c not in vu:
            vu.add(c)
            res.append(c)
    return res


def main():
    configs = _charger_configs_presets()
    taxo_path = BASE / "presets" / "_taxonomie_domaines.json"
    taxo = {}
    if taxo_path.is_file():
        taxo = (json.loads(taxo_path.read_text(encoding="utf-8")) or {}).get("domaines", {})

    codes_marche = _codes_par_marche()
    # Counter code → nb marchés
    compteur = Counter()
    for mid, codes in codes_marche.items():
        for c in set(codes):
            compteur[c] += 1

    # Reverse mapping (ground truth)
    reverse = {}
    for code in compteur:
        reverse[code] = preset_mod.presets_pour_domaines([code])

    buckets = defaultdict(list)
    for code, presets in reverse.items():
        buckets[len(presets)].append(code)

    L = []
    p = L.append
    p("# Audit — mapping domaine → presets (avant Chantier 1)\n")
    p("_Lecture seule. `preset.py` NON modifié. Le mapping vient des "
      "`presets/<code>/_preset.json` (`veille.domaines_acceptes/optionnels`)._\n")

    # --- 1. État actuel : config preset → domaines ---
    p("## 1. Configuration actuelle des presets\n")
    p("| Preset | domaines_acceptes | domaines_optionnels |")
    p("|---|---|---|")
    for code, v in configs.items():
        p(f"| {code} | {', '.join(v['domaines_acceptes']) or '—'} "
          f"| {', '.join(v['domaines_optionnels']) or '—'} |")
    p(f"\nTaxonomie : **{len(taxo)} codes** définis. "
      f"Codes réellement présents en base : **{len(compteur)}** "
      f"(sur {sum(compteur.values())} occurrences, {len(codes_marche)} marchés classés).\n")

    # --- 2. Reverse mapping code → nb presets ---
    p("## 2. Reverse mapping : combien de presets par code domaine ?\n")
    p("Trié par nb de presets décroissant, puis par nb de marchés.\n")
    p("| Code domaine | # presets | Presets déclenchés | Marchés | Verdict |")
    p("|---|---|---|---|---|")
    def _verdict(n):
        return {0: "hors-périmètre", 1: "✅ propre", 2: "🟡 acceptable"}.get(n, "🔴 trop large")
    for code in sorted(compteur, key=lambda c: (-len(reverse[c]), -compteur[c])):
        presets = reverse[code]
        p(f"| {code} | {len(presets)} | {', '.join(presets) or '—'} "
          f"| {compteur[code]} | {_verdict(len(presets))} |")
    p("")
    rep = Counter(len(v) for v in reverse.values())
    p(f"Répartition : "
      f"**{rep.get(0,0)}** codes hors-périmètre, "
      f"**{rep.get(1,0)}** propres (1 preset), "
      f"**{rep.get(2,0)}** acceptables (2), "
      f"**{sum(n for k,n in rep.items() if k>=3)}** trop larges (3+).\n")

    # --- 3. Problématiques (3+) ---
    p("## 3. Codes problématiques (3+ presets) & proposition\n")
    probs = sorted([c for c in compteur if len(reverse[c]) >= 3],
                   key=lambda c: -compteur[c])
    if not probs:
        p("_Aucun code ne déclenche 3+ presets._\n")
    for code in probs:
        p(f"### `{code}` → {reverse[code]} ({compteur[code]} marchés)\n")
        # où apparaît-il ?
        appar = []
        for pc, v in configs.items():
            if code in v["domaines_acceptes"]:
                appar.append(f"`{pc}`.acceptés")
            if code in v["domaines_optionnels"]:
                appar.append(f"`{pc}`.optionnels")
        p(f"- Apparaît dans : {', '.join(appar)}")
        p(f"- Label taxonomie : {taxo.get(code, {}).get('label', '—') if isinstance(taxo.get(code), dict) else '—'}")
    p("")
    p("**Proposition de resserrement :**\n")
    for pc, champ, code in RETRAITS_PROPOSES:
        p(f"- Retirer `{code}` de `{pc}.{champ}`.")
    p("\n_Justification métier_ : la maîtrise d'œuvre architecture/urbanisme "
      "(`moe_architecte_urbanisme`) relève du cœur **ingénierie** (acceptés) et "
      "intéresse légitimement le **BTP** en secondaire (un marché de MOE bâtiment "
      "peut concerner une entreprise de travaux). En revanche elle n'a pas de "
      "rapport avec le **conseil** (stratégie/juridique/finance) : ce rattachement "
      "optionnel est un faux positif. Resserrer 3 → 2 presets (🟡 acceptable).\n")

    # --- 4. Impact estimé ---
    p("## 4. Impact estimé du resserrement\n")
    chg_principal = chg_set = 0
    exemples = []
    for mid, codes in codes_marche.items():
        avant = preset_mod.presets_pour_domaines(codes)
        apres = _presets_proposes(codes, configs)
        if avant != apres:
            chg_set += 1
            if (avant[:1] or [None]) != (apres[:1] or [None]):
                chg_principal += 1
            if len(exemples) < 10:
                exemples.append((mid, avant, apres))
    p(f"- Marchés dont le **preset principal** (1ᵉʳ) change : **{chg_principal}**")
    p(f"- Marchés dont l'**ensemble de presets** change : **{chg_set}** "
      f"(sur {len(codes_marche)} classés)\n")
    p("> Le principal ne bouge pas : `moe_architecte_urbanisme` reste *accepté* "
      "par `ingenierie` (donc toujours 1ᵉʳ). Le resserrement retire seulement le "
      "rattachement secondaire `conseil` — un marché ne perd `conseil` que s'il "
      "n'a AUCUN autre code conseil.\n")
    if exemples:
        p("| Marché | Avant | Après |")
        p("|---|---|---|")
        for mid, av, ap in exemples:
            p(f"| {mid} | {', '.join(av) or '—'} | {', '.join(ap) or '—'} |")
    p("")

    # --- 5. Anomalies de données repérées ---
    p("## 5. Anomalies de données repérées (hors mapping)\n")
    hors_taxo = sorted(c for c in compteur if c not in taxo)
    if hors_taxo:
        p("Codes classifiés ABSENTS de la taxonomie (→ 0 preset, à corriger côté "
          "classification, PAS côté mapping) :")
        for c in hors_taxo:
            p(f"- `{c}` ({compteur[c]} marché(s))")
    else:
        p("_Aucun code hors-taxonomie._")
    p("")

    contenu = "\n".join(L)
    with open(SORTIE_MD, "w", encoding="utf-8") as f:
        f.write(contenu)
    print(f"✅ Rapport écrit : {SORTIE_MD}")
    print(f"   {len(compteur)} codes en base, {len(probs)} problématique(s) 3+, "
          f"impact resserrement : {chg_set} marchés (set), {chg_principal} (principal)")


if __name__ == "__main__":
    main()
