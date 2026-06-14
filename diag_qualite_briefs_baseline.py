"""
diag_qualite_briefs_baseline.py
-------------------------------
Baseline MESURÉE de la qualité des briefs existants, en vue du futur sprint
d'optimisation des prompts LLM (« Chantier 1 »). NE MODIFIE RIEN : lecture seule
de la base, produit `baseline_briefs_avant_chantier1.md`.

Mesure, par preset (BTP / ingénierie / IT / conseil / formation / EnR /
hors-périmètre — déterminé via la classification du marché) :
  - taux de remplissage des champs critiques transverses ;
  - taux de remplissage des champs SECTORIELS attendus pour le preset ;
  - blocs sectoriels HORS-SUJET (remplis alors qu'ils n'appartiennent pas au
    preset attendu — symptôme d'un schéma LLM non routé) ;
  - incohérences titre↔synthèse (la synthèse ne reprend aucun mot du titre) ;
  - coût LLM (moyen/médian), distribution des tokens in, briefs pré/post _meta.

Le preset d'un marché est dérivé de sa classification (`classifications_ia`
⊕ `domaines_metier` du brief complet) → `preset.presets_pour_domaines` →
preset principal (1ʳᵉ entrée). Réutilise les loaders canoniques d'
`audit_classifications` pour rester cohérent avec le reste du repo.

Usage : python diag_qualite_briefs_baseline.py
"""
import statistics
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import preset as preset_mod
import audit_classifications as AC

SORTIE_MD = "baseline_briefs_avant_chantier1.md"

# Presets « métier » connus (ordre d'affichage). 'hors-périmètre' = aucun preset.
PRESETS_CONNUS = ["btp", "ingenierie", "it", "conseil", "formation", "enr"]
HORS_PERIMETRE = "hors-périmètre"

# Blocs sectoriels → preset propriétaire (pour la détection hors-sujet).
# Un bloc rempli dans un brief dont le preset ≠ propriétaire = bloc hors-sujet.
BLOCS_SECTORIELS = {
    "caracteristiques_techniques_chantier": "btp",
    "volumes_techniques": "btp",
    "modalites_execution_chantier": "btp",
    "caracteristiques_mission_moe": "ingenierie",
    "qualifications_moe": "ingenierie",
    "caracteristiques_si": "it",
    "qualifications_si": "it",
    "qualifications_formation": "formation",
    "qualifications_enr": "enr",
}


# ---------------------------------------------------------------------------
# Helpers de présence / remplissage
# ---------------------------------------------------------------------------
def _non_vide(v) -> bool:
    """True si la valeur est « réellement renseignée » (pas None/''/[]/{}/0-vide)."""
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ""
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return True  # nombres / bool : présents


def _meta_tokens_in(b: dict):
    """tokens d'entrée — `tokens_input` (brief complet) ou `tokens_in` (light)."""
    m = b.get("_meta", {}) or {}
    v = m.get("tokens_input")
    if v is None:
        v = m.get("tokens_in")
    return v if isinstance(v, (int, float)) else None


def _meta_date(b: dict):
    """date de génération — `date_generation` (light) ou `extraction_le` (complet)."""
    m = b.get("_meta", {}) or {}
    return m.get("date_generation") or m.get("extraction_le")


def _chemin(d: dict, *cles):
    """Accès tolérant d[c1][c2]... → valeur ou None."""
    cur = d
    for c in cles:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(c)
    return cur


def _bloc_actif(brief: dict, nom_bloc: str) -> bool:
    """Un bloc sectoriel est « actif » s'il existe et porte au moins une valeur
    renseignée AUTRE qu'une simple `description` (sinon coquille vide schématique)."""
    bloc = brief.get(nom_bloc)
    if not _non_vide(bloc):
        return False
    if isinstance(bloc, dict):
        return any(_non_vide(v) for k, v in bloc.items() if k != "description")
    return True


# Champs critiques transverses : libellé → fonction(brief) -> bool rempli.
CHAMPS_CRITIQUES = {
    "synthese_marche": lambda b: _non_vide(b.get("synthese_marche")),
    "bareme.valeur_technique_pct": lambda b: _non_vide(_chemin(b, "bareme_notation", "valeur_technique_pct")),
    "montant.valeur_estimee_euros": lambda b: _non_vide(_chemin(b, "montant_marche", "valeur_estimee_euros")),
    "refs.experience_minimale_annees": lambda b: _non_vide(_chemin(b, "references_exigees", "experience_minimale_annees")),
    "refs.certifications_obligatoires": lambda b: _non_vide(_chemin(b, "references_exigees", "certifications_obligatoires")),
    "points_differenciants_attendus": lambda b: _non_vide(b.get("points_differenciants_attendus")),
    "alertes_candidat": lambda b: _non_vide(b.get("alertes_candidat")),
}

# Champs SECTORIELS attendus par preset : preset → {libellé: fn(brief)->bool}.
CHAMPS_SECTORIELS = {
    "btp": {
        "qualifications_requises.qualibat": lambda b: _non_vide(_chemin(b, "qualifications_requises", "qualibat")),
    },
    "ingenierie": {
        "qualifications_moe.opqibi": lambda b: _non_vide(_chemin(b, "qualifications_moe", "opqibi")),
    },
    "it": {
        "qualifications_si.iso_27001": lambda b: _non_vide(_chemin(b, "qualifications_si", "iso_27001")),
        "caracteristiques_si.typologie_systeme": lambda b: _non_vide(_chemin(b, "caracteristiques_si", "typologie_systeme")),
    },
    "formation": {
        "qualifications_formation.qualiopi": lambda b: _non_vide(_chemin(b, "qualifications_formation", "qualiopi")),
        "publics_cibles": lambda b: _non_vide(b.get("publics_cibles")),
    },
    "enr": {
        "qualifications_enr.qualipv": lambda b: _non_vide(_chemin(b, "qualifications_enr", "qualipv")),
    },
    "conseil": {},  # pas de bloc sectoriel dédié dans le schéma actuel
}

MOTS_VIDES = {"de", "la", "le", "les", "des", "du", "un", "une", "et", "en",
              "pour", "par", "sur", "aux", "avec", "dans", "ses", "son", "sa",
              "marche", "marché", "public", "publics", "prestation", "prestations",
              "fourniture", "fournitures", "service", "services", "travaux",
              "lot", "lots", "appel", "offre", "offres"}


def _mots_signifiants(texte: str) -> set:
    import re
    mots = re.findall(r"[a-zàâäéèêëïîôöùûüç]{4,}", (texte or "").lower())
    return {m for m in mots if m not in MOTS_VIDES}


def _coherence_titre_synthese(titre: str, synthese: str) -> bool:
    """True si la synthèse partage ≥1 mot signifiant (>3 car.) avec le titre."""
    mt = _mots_signifiants(titre)
    ms = _mots_signifiants(synthese)
    if not mt or not ms:
        return True  # indéterminable → on ne pénalise pas
    return len(mt & ms) >= 1


# ---------------------------------------------------------------------------
# Chargement + mapping preset
# ---------------------------------------------------------------------------
def _preset_principal(codes: list) -> str:
    presets = preset_mod.presets_pour_domaines(codes)
    return presets[0] if presets else HORS_PERIMETRE


def main():
    briefs = AC._charger_briefs()
    marches = stockage.charger("marches") or {}
    classifs = AC._charger_classifications_unifiees()

    # preset principal par marché (depuis la classification unifiée)
    preset_par_marche = {}
    for mid, c in classifs.items():
        codes = [code for code, _poids, _lots in c.get("domaines", [])]
        preset_par_marche[mid] = _preset_principal(codes)

    # Regroupement des briefs par preset
    par_preset = defaultdict(list)
    for mid, brief in briefs.items():
        p = preset_par_marche.get(mid, HORS_PERIMETRE)
        par_preset[p].append((mid, brief))

    lignes = []
    pc = lignes.append
    pc(f"# Baseline qualité des briefs — avant Chantier 1\n")
    pc(f"_Lecture seule. {len(briefs)} briefs analysés "
       f"({sum(1 for b in briefs.values() if b.get('_meta', {}).get('type') == 'complet')} complet, "
       f"{sum(1 for b in briefs.values() if b.get('_meta', {}).get('type') == 'light')} light)._\n")
    pc("> Référence figée pour mesurer l'amélioration post-optimisation des prompts.\n")

    # --- 1. Répartition par preset ---
    pc("## 1. Répartition des briefs par preset (classification du marché)\n")
    pc("| Preset | Nb briefs |")
    pc("|---|---|")
    ordre = [p for p in PRESETS_CONNUS if p in par_preset] + \
            [p for p in par_preset if p not in PRESETS_CONNUS]
    for p in ordre:
        pc(f"| {p} | {len(par_preset[p])} |")
    pc(f"| **Total** | **{sum(len(v) for v in par_preset.values())}** |\n")

    # --- 2. Champs critiques transverses par preset ---
    pc("## 2. Remplissage des champs critiques (transverses), par preset\n")
    entetes = list(CHAMPS_CRITIQUES.keys())
    pc("| Preset | n | " + " | ".join(entetes) + " |")
    pc("|---" * (len(entetes) + 2) + "|")
    for p in ordre:
        items = par_preset[p]
        n = len(items)
        cells = []
        for libelle, fn in CHAMPS_CRITIQUES.items():
            k = sum(1 for _mid, b in items if fn(b))
            cells.append(f"{100 * k // n if n else 0}% ({k})")
        pc(f"| {p} | {n} | " + " | ".join(cells) + " |")
    pc("")

    # --- 3. Champs sectoriels attendus, par preset ---
    pc("## 3. Remplissage des champs SECTORIELS attendus (preset identifié)\n")
    pc("_Mesuré uniquement sur les briefs dont le preset attend ce bloc._\n")
    pc("| Preset | n | Champ sectoriel | Taux rempli |")
    pc("|---|---|---|---|")
    for p in PRESETS_CONNUS:
        items = par_preset.get(p, [])
        n = len(items)
        champs = CHAMPS_SECTORIELS.get(p, {})
        if not champs:
            pc(f"| {p} | {n} | _(aucun bloc sectoriel dédié)_ | — |")
            continue
        for libelle, fn in champs.items():
            k = sum(1 for _mid, b in items if fn(b))
            pc(f"| {p} | {n} | {libelle} | {100 * k // n if n else 0}% ({k}/{n}) |")
    pc("")

    # --- 4. Blocs hors-sujet ---
    pc("## 4. Blocs sectoriels HORS-SUJET\n")
    pc("_Bloc rempli alors qu'il n'appartient pas au preset du marché "
       "(symptôme d'un schéma LLM non routé vers le bon secteur)._\n")
    pc("| Preset du brief | n | Briefs avec ≥1 bloc HS | Blocs HS les plus fréquents |")
    pc("|---|---|---|---|")
    total_hs = 0
    detail_hs = []  # (mid, preset, [blocs])
    for p in ordre:
        items = par_preset[p]
        n = len(items)
        nb_avec_hs = 0
        compteur_blocs = Counter()
        for mid, b in items:
            hs = [bloc for bloc, owner in BLOCS_SECTORIELS.items()
                  if owner != p and owner in PRESETS_CONNUS and _bloc_actif(b, bloc)]
            # hors-périmètre : tout bloc sectoriel actif est suspect
            if p == HORS_PERIMETRE:
                hs = [bloc for bloc in BLOCS_SECTORIELS if _bloc_actif(b, bloc)]
            if hs:
                nb_avec_hs += 1
                total_hs += 1
                compteur_blocs.update(hs)
                detail_hs.append((mid, p, hs))
        top = ", ".join(f"{bl}×{c}" for bl, c in compteur_blocs.most_common(3)) or "—"
        pc(f"| {p} | {n} | {nb_avec_hs} | {top} |")
    pc(f"\n**{total_hs} briefs** présentent au moins un bloc sectoriel hors-sujet.\n")

    # --- 5. Incohérences titre↔synthèse ---
    pc("## 5. Incohérences titre ↔ synthèse\n")
    pc("_Synthèse ne partageant aucun mot signifiant (>3 car.) avec le titre du marché._\n")
    incoherents = []
    n_testes = 0
    for mid, b in briefs.items():
        titre = (marches.get(mid, {}) or {}).get("titre") or \
                (marches.get(mid, {}) or {}).get("objet") or ""
        synth = b.get("synthese_marche") or ""
        if not titre or not synth:
            continue
        n_testes += 1
        if not _coherence_titre_synthese(titre, synth):
            incoherents.append((mid, titre, synth))
    pc(f"- Briefs testés (titre + synthèse présents) : **{n_testes}**")
    pc(f"- Incohérents (0 mot commun) : **{len(incoherents)}** "
       f"({100 * len(incoherents) // n_testes if n_testes else 0}%)\n")
    if incoherents:
        pc("| Marché | Titre (extrait) | Synthèse (extrait) |")
        pc("|---|---|---|")
        for mid, titre, synth in incoherents[:15]:
            pc(f"| {mid} | {titre[:60].replace('|', '/')} | {synth[:60].replace('|', '/')} |")
        if len(incoherents) > 15:
            pc(f"| _… {len(incoherents) - 15} autres_ | | |")
    pc("")

    # --- 6. Coût LLM + tokens ---
    pc("## 6. Coût LLM & tokens, par preset\n")
    pc("| Preset | n (avec coût) | Coût moyen € | Coût médian € | Tokens_in moyen | Tokens_in médian |")
    pc("|---|---|---|---|---|---|")
    for p in ordre:
        couts = [b.get("_meta", {}).get("cout_eur") for _m, b in par_preset[p]]
        couts = [c for c in couts if isinstance(c, (int, float))]
        tin = [_meta_tokens_in(b) for _m, b in par_preset[p]]
        tin = [t for t in tin if t is not None]
        if couts and tin:
            pc(f"| {p} | {len(couts)} | {statistics.mean(couts):.4f} | "
               f"{statistics.median(couts):.4f} | "
               f"{statistics.mean(tin):.0f} | {statistics.median(tin):.0f} |")
        elif couts:
            pc(f"| {p} | {len(couts)} | {statistics.mean(couts):.4f} | {statistics.median(couts):.4f} | — | — |")
        else:
            pc(f"| {p} | 0 | — | — | — | — |")
    tous_couts = [b.get("_meta", {}).get("cout_eur") for b in briefs.values()
                  if isinstance(b.get("_meta", {}).get("cout_eur"), (int, float))]
    if tous_couts:
        pc(f"\n**Coût total briefs** : {sum(tous_couts):.2f} € sur {len(tous_couts)} briefs "
           f"(moyen {statistics.mean(tous_couts):.4f} €, médian {statistics.median(tous_couts):.4f} €).\n")

    # Corrélation grossière tokens_in ↔ coût (light ET complet)
    paires = [(_meta_tokens_in(b), b["_meta"]["cout_eur"]) for b in briefs.values()
              if _meta_tokens_in(b) is not None
              and isinstance(b.get("_meta", {}).get("cout_eur"), (int, float))]
    if len(paires) >= 5:
        tin_tries = sorted(paires)
        q = len(tin_tries) // 4
        bas = tin_tries[:q] or tin_tries[:1]
        haut = tin_tries[-q:] or tin_tries[-1:]
        pc(f"- Quartile BAS tokens_in (~{statistics.mean(t for t, _ in bas):.0f} tok) "
           f"→ coût moyen {statistics.mean(c for _, c in bas):.4f} €")
        pc(f"- Quartile HAUT tokens_in (~{statistics.mean(t for t, _ in haut):.0f} tok) "
           f"→ coût moyen {statistics.mean(c for _, c in haut):.4f} €")
        pc("  (les gros DCE produisent bien des briefs plus chers)\n")

    # --- 7. Datation & schéma _meta ---
    pc("## 7. Datation des briefs & schéma `_meta`\n")
    pc("> Les 2 pipelines n'utilisent PAS les mêmes clés `_meta` : brief **light** "
       "→ `date_generation` + `tokens_in/out` ; brief **complet** → `extraction_le` "
       "+ `tokens_input/output` (+ `pdfs_traites`). À harmoniser (impacte tout outil "
       "qui lit `_meta`).\n")
    sans_date_gen = sum(1 for b in briefs.values()
                        if not (b.get("_meta", {}) or {}).get("date_generation"))
    sans_aucune_date = sum(1 for b in briefs.values() if not _meta_date(b))
    sans_tokens = sum(1 for b in briefs.values() if _meta_tokens_in(b) is None)
    pc(f"- Sans `date_generation` (champ light) : **{sans_date_gen}** "
       f"(dont la plupart ont `extraction_le`)")
    pc(f"- Sans AUCUNE date (`date_generation` ni `extraction_le`) : **{sans_aucune_date}**")
    pc(f"- Sans tokens_in exploitables : **{sans_tokens}**\n")
    modeles = Counter((b.get("_meta", {}) or {}).get("modele") for b in briefs.values())
    pc("Modèles LLM utilisés : " + ", ".join(f"`{m}`×{c}" for m, c in modeles.most_common()) + "\n")

    contenu = "\n".join(lignes)
    with open(SORTIE_MD, "w", encoding="utf-8") as f:
        f.write(contenu)
    print(f"✅ Rapport écrit : {SORTIE_MD} ({len(lignes)} lignes)")
    print(f"   {len(briefs)} briefs, {total_hs} avec bloc HS, "
          f"{len(incoherents)} incohérences titre↔synthèse")


if __name__ == "__main__":
    main()
