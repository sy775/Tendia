"""
decp/classif_ia.py — classification DECP par IA dans la taxonomie de classifications_ia
(Sprint DECP-R).

- Taxonomie : presets/_taxonomie_domaines.json (64 codes, mêmes codes que classifications_ia).
- famille = preset officiel du domaine (preset.presets_pour_domaines) ; correspondance
  avec les anciens codes DECP : conseil_rd → conseil, enr → energie_renouvelable.
- Lot de N contrats par appel, sortie « une ligne JSON par contrat » :
      {"i": <n° du contrat dans le lot>, "d": <n° du domaine>}
  (numéros plutôt que codes : ~4× moins de tokens de sortie ; validés à la lecture).
- Gemini SANS outil (pas de recherche Google / grounding) et SANS réflexion.
- Budget : chaque appel est journalisé dans llm_appels (type « decp », enveloppe
  decp_reprise) avec _meta.cout_eur ; un lot n'est lancé que si budget.peut_depenser().

Le CPV seul n'est pas fiable : l'OBJET prime (consigne explicite du prompt).
"""
import hashlib
import json
import re
import unicodedata
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
CHEMIN_TAXONOMIE = RACINE / "presets" / "_taxonomie_domaines.json"
ENVELOPPE = "decp_reprise"

# Anciens codes de decp_classification v1 → famille (preset officiel)
CORRESPONDANCE_V1 = {"conseil_rd": "conseil", "enr": "energie_renouvelable",
                     "btp": "btp", "ingenierie": "ingenierie", "it": "it",
                     "formation": "formation", "hors_perimetre": "hors_perimetre"}

# Pré-filtre large : CPV 45*, 71*, 50*, 44* OU mots-clés travaux dans l'objet
CPV_PREFILTRE = ("45", "71", "50", "44")
_MOTS_TRAVAUX = re.compile(
    r"\b(travaux|renovation|rehabilitation|construction|demolition|desamiantage|amenagement|"
    r"voirie|vrd|assainissement|terrassement|maconnerie|gros oeuvre|second oeuvre|couverture|"
    r"etancheite|menuiserie|menuiseries|plomberie|electricite|chauffage|cvc|ventilation|"
    r"climatisation|peinture|carrelage|platrerie|cloisons|facade|facades|toiture|charpente|"
    r"genie civil|ouvrage d art|maitrise d oeuvre|reseaux|enrobes|chaussee|batiment|extension|"
    r"restructuration|isolation|ravalement|serrurerie|metallerie)\b")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def dans_prefiltre(cpv, objet) -> bool:
    return bool((cpv or "")[:2] in CPV_PREFILTRE or _MOTS_TRAVAUX.search(_norm(objet)))


# Domaines PROPRES à la classification DECP (décision Younes, Sprint DECP-R), ajoutés en fin
# de liste sans toucher presets/_taxonomie_domaines.json (utilisée par la prod : classification
# de nos marchés, prompt des briefs, presets, formulaire de profil). Même code que celui
# qui sera ajouté à la taxonomie partagée au Sprint 1.
DOMAINES_DECP = {
    "btp_maintenance_exploitation": {
        "libelle": "Maintenance et exploitation des équipements techniques du bâtiment",
        "description": ("Contrats d'entretien, de maintenance préventive/corrective et d'exploitation "
                        "(CVC/chauffage P2-P3, ascenseurs, portes et portails automatiques, sécurité "
                        "incendie, plomberie, clôtures) — sans travaux neufs"),
        "famille": "btp"},
}


def taxonomie() -> list:
    """[(numero, code, libelle, description_courte)] — ordre stable du fichier, puis les
    domaines propres à la DECP (DOMAINES_DECP)."""
    dom = json.loads(CHEMIN_TAXONOMIE.read_text(encoding="utf-8"))["domaines"]
    out = []
    for n, (code, info) in enumerate(dom.items(), 1):
        desc = (info.get("description") or "").split(".")[0][:110]
        out.append((n, code, info.get("libelle", code), desc))
    for code, info in DOMAINES_DECP.items():
        out.append((len(out) + 1, code, info["libelle"], info["description"]))
    return out


def famille_de(code: str) -> str:
    if code in DOMAINES_DECP:
        return DOMAINES_DECP[code]["famille"]
    from tendia.veille import preset
    p = (preset.presets_pour_domaines([code]) or [None])[0]
    return p or "hors_perimetre"


REGLES_V2 = """## RÈGLES COMPLÉMENTAIRES (données DECP)
- MAINTENANCE / EXPLOITATION d'équipements techniques du BÂTIMENT (chauffage-ventilation-
  climatisation, contrats P2/P3, ascenseurs, élévateurs, portes et portails automatiques,
  sécurité incendie : extincteurs, BAES, SSI, désenfumage ; plomberie, fontaines ; clôtures)
  → `btp_maintenance_exploitation`. Des TRAVAUX neufs ou de remplacement restent en `btp_*`.
- Maintenance d'équipements MÉDICAUX ou de LABORATOIRE (CHU, biologie, imagerie) →
  `services_sante_medical`. `it_maintenance_support` est RÉSERVÉ à l'informatique (postes,
  serveurs, logiciels, téléphonie IP).
- RÉSEAUX de télécommunication : extension, pose, génie civil → `btp_reseaux_divers`.
- CPV 71314 (énergie) : études, audits, suivi de performance, dossiers CEE →
  `energie_amo_etudes` ; AMO de montage/développement de projet (réseau de chaleur, SPL,
  centrale) → `energie_amo_developpement` ; planification territoriale (PCAET, schéma
  directeur territorial) → `conseil_transition_energetique` ; TRAVAUX d'efficacité
  énergétique → `energie_renovation_thermique` ; exploitation-maintenance du chauffage →
  `btp_maintenance_exploitation`.
- Charpente métallique, structure, maçonnerie → `btp_gros_oeuvre` ; aménagement intérieur,
  cloisons, menuiseries, électricité, plomberie (travaux) → `btp_second_oeuvre`.

## EXEMPLES
- « Maintenance des ascenseurs et monte-charges des établissements » → btp_maintenance_exploitation
- « Maintenance des automatismes de portes, portails et barrières » → btp_maintenance_exploitation
- « Exploitation et maintenance des installations de chauffage avec garantie totale » → btp_maintenance_exploitation
- « Maintenance des extincteurs, BAES et RIA » → btp_maintenance_exploitation
- « Maintenance des spectromètres de masse du laboratoire du CHU » → services_sante_medical
- « Extension et maintenance des réseaux de communication de la commune » → btp_reseaux_divers
- « Accompagnement pour le dépôt de dossiers Certificats d'économies d'énergie » → energie_amo_etudes
- « Schéma directeur et AMO pour la création d'un réseau de chaleur » → energie_amo_developpement
- « Lot 5 charpente métallique — aménagement des établissements balnéaires » → btp_gros_oeuvre
- « Aménagement intérieur d'un restaurant » → btp_second_oeuvre"""


def _frontieres() -> str:
    """Section « FRONTIÈRES PIÉGEUSES » du prompt de prod (tendia_classification),
    réutilisée telle quelle pour garder la même sémantique que nos marchés."""
    from tendia.veille import classification as tc
    p = tc._prompt_systeme()
    i = p.find("## FRONTIÈRES")
    if i < 0:
        return ""
    j = p.find("\n## ", i + 5)
    return p[i:j if j > 0 else None].strip()


def prompt_systeme(version: str = "v2", allege: bool = False) -> str:
    """v1 : prompt du pilote 1 (sortie une ligne JSON par contrat).
    v2 : + domaine btp_maintenance_exploitation, règles complémentaires, exemples, sortie
         compacte (tableau JSON de paires). allege=True : sans descriptions ni frontières."""
    if version == "v1":
        return _prompt_v1()
    lignes = [
        "Tu classes des contrats de marchés publics français DÉJÀ ATTRIBUÉS (données DECP) "
        "dans une taxonomie de domaines métier.",
        "Pour chaque contrat : numéro, objet, code CPV, acheteur.",
        "Le CPV est INDICATIF et souvent mal choisi par l'acheteur : l'OBJET prime toujours.",
        "UN SEUL domaine par contrat (le dominant) ; si aucun ne convient : `autre`.",
        "", "## DOMAINES (numéro, code, libellé" + ("" if allege else ", description") + ")"]
    for n, code, lib, desc in taxonomie():
        lignes.append(f"{n} {code} — {lib}" + ("" if allege else f". {desc}."))
    if not allege:
        lignes += ["", _frontieres()]
    lignes += ["", REGLES_V2, "",
               "## FORMAT DE SORTIE (STRICT)",
               "Un unique tableau JSON de paires [numéro du contrat, numéro du domaine], dans l'ordre :",
               "[[1,12],[2,40],[3,5]]",
               "Aucun autre texte, aucun bloc markdown."]
    return "\n".join(lignes)


def _prompt_v1() -> str:
    """Prompt du pilote 1 — la liste ne contient QUE la taxonomie partagée (64 codes)."""
    lignes = [
        "Tu classes des contrats de marchés publics français DÉJÀ ATTRIBUÉS (données DECP) "
        "dans une taxonomie de domaines métier.",
        "Pour chaque contrat, tu reçois : son numéro, son objet, son code CPV et l'acheteur.",
        "Le CPV est INDICATIF et souvent mal choisi par l'acheteur : l'OBJET prime toujours.",
        "Choisis UN SEUL domaine : le domaine dominant du contrat. Si aucun domaine ne "
        "convient, choisis `autre`.",
        "",
        "## DOMAINES (numéro, code, libellé)",
    ]
    for n, code, lib, desc in taxonomie():
        if code in DOMAINES_DECP:
            continue
        lignes.append(f"{n} {code} — {lib}. {desc}.")
    lignes += ["", _frontieres(), "",
               "## FORMAT DE SORTIE (STRICT)",
               "Une ligne par contrat, dans l'ordre, chaque ligne étant un objet JSON compact :",
               '{"i":<numéro du contrat>,"d":<numéro du domaine>}',
               "Aucun autre texte, aucun bloc markdown, aucune explication."]
    return "\n".join(lignes)


def prompt_utilisateur(lot: list) -> str:
    """lot : [{"objet", "cpv", "acheteur"}] → lignes « n | objet | CPV | acheteur »."""
    import html
    out = ["Contrats à classer (numéro | objet | CPV | acheteur) :"]
    for i, c in enumerate(lot, 1):
        objet = " ".join(html.unescape(c.get("objet") or "").split())[:300]
        out.append(f"{i} | {objet} | {c.get('cpv') or '-'} | {(c.get('acheteur') or '-')[:80]}")
    return "\n".join(out)


def version_prompt(version: str = "v2", allege: bool = False) -> str:
    return hashlib.sha256(prompt_systeme(version, allege).encode("utf-8")).hexdigest()[:12]


def parser_sortie(texte: str, n: int) -> dict:
    """Retourne {index_1_based: code} pour les entrées valides ; ignore le reste.
    Accepte la sortie v2 (tableau de paires [[i,d],…]) et la sortie v1 ({"i":…,"d":…} par ligne)."""
    codes = {num: code for num, code, _, _ in taxonomie()}
    res = {}
    for m in re.finditer(r'\[\s*(\d+)\s*,\s*(\d+)\s*\]', texte or ""):
        i, d = int(m.group(1)), int(m.group(2))
        if 1 <= i <= n and d in codes and i not in res:
            res[i] = codes[d]
    for m in re.finditer(r'\{\s*"i"\s*:\s*(\d+)\s*,\s*"d"\s*:\s*(\d+)\s*\}', texte or ""):
        i, d = int(m.group(1)), int(m.group(2))
        if 1 <= i <= n and d in codes and i not in res:
            res[i] = codes[d]
    return res
