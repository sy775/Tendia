"""
tendia_ui.py
------------
Serveur web Flask pour Tendia.

Lance avec :
    python tendia_ui.py
    → http://localhost:5000

Architecture :
- / : Dashboard (marchés actifs)
- /marche/<id> : Détail d'un marché
- /profil : Gestion organisme (Session 2)
- /veille : Boutons d'action (Session 2)
"""

import json
import os
import re
from datetime import date, datetime
from pathlib import Path

from flask import (Flask, abort, flash, redirect, render_template, request,
                   send_from_directory, url_for)

import organisme
import profil_form
import profil_widgets
import fiche_marche
import matching
import concurrence
import stockage


REPERTOIRE_BASE = Path(__file__).parent
REPERTOIRE_DATA = REPERTOIRE_BASE / "data"
REPERTOIRE_EXTRACTIONS = REPERTOIRE_DATA / "extractions"
REPERTOIRE_DCE = REPERTOIRE_DATA / "dce"

app = Flask(
    __name__,
    template_folder=str(REPERTOIRE_BASE / "ui" / "templates"),
    static_folder=str(REPERTOIRE_BASE / "ui" / "static"),
)
# Clé pour flash() — POC local mono-utilisateur, pas de session sensible.
app.secret_key = "tendia-poc-local-secret-key-profils"

# Migration de la bibliothèque de profils au démarrage (idempotent) : si la
# bibliothèque est vide mais qu'un profil actif existe, on l'y copie.
try:
    _rapport_migration = organisme.migrer_bibliotheque_au_demarrage()
    print(f"[migration profils] {_rapport_migration}")
except Exception as _e:
    print(f"[migration profils] erreur (non bloquante) : {_e}")


@app.context_processor
def _injecter_preset_actif():
    """
    Expose le preset actif à tous les templates via :
        {{ preset_etiquette }}  → étiquette UI courte (ex: "France Travail")
        {{ preset_code }}       → code technique (ex: "formation_ft")
        {{ preset_nom }}        → nom long (ex: "Formation et insertion — France Travail")

    Utilisé par le sidebar et tout libellé contextuel au secteur actif.
    En cas d'erreur de chargement, retourne des valeurs neutres pour ne
    pas faire planter l'UI.
    """
    try:
        import preset
        meta = preset.charger_actif()["preset"].get("meta", {})
        return {
            "preset_etiquette": preset.etiquette_courte(),
            "preset_code": preset.code_actif(),
            "preset_nom": meta.get("nom", preset.code_actif()),
        }
    except Exception:
        return {
            "preset_etiquette": "",
            "preset_code": "",
            "preset_nom": "",
        }


@app.template_filter("enum_label")
def _enum_label_filter(valeur):
    """Libellé lisible d'une valeur d'enum (pour les selects/checkboxes)."""
    import profil_widgets
    return profil_widgets._label(valeur)


@app.template_filter("json_pretty")
def _json_pretty_filter(valeur):
    """Sérialise une valeur en JSON indenté (pour les textareas d'édition)."""
    try:
        return json.dumps(valeur if valeur is not None else [],
                          ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return ""


# Filtres Jinja pour formatage français des dates (indépendant de la locale)
def _date_fr_filter(d):
    if not d:
        return ""
    # Import différé pour éviter une boucle au chargement
    return _date_fr_long(d)

app.add_template_filter(_date_fr_filter, name="date_fr")


# Filtre Jinja : format euros lisible.
# - < 1 000 000 : affichage précis en € avec séparateur français (ex: "1 450 €", "250 000 €")
# - ≥ 1 000 000 : compactage en M€ (ex: "1.25 M€") pour rester lisible
# Le compactage en k€ a été retiré : tronquait trop pour les prix unitaires.
def _euro_short_filter(montant):
    if montant is None or montant == 0:
        return "—"
    try:
        montant = float(montant)
    except (TypeError, ValueError):
        return "—"
    if montant >= 1_000_000:
        m = montant / 1_000_000
        # 1 M€ (pas 1.00 M€), 1.5 M€ (pas 1.50), 1.25 M€
        s = f"{m:.2f}".rstrip("0").rstrip(".")
        return f"{s} M€"
    return f"{int(round(montant)):,} €".replace(",", " ")

app.add_template_filter(_euro_short_filter, name="euro_short")


# Filtre Jinja : séparateur de milliers FR (espace) sur n'importe quel nombre.
# Laisse les chaînes non numériques intactes (ex. déjà formatées "1 500 m²").
def _milliers_filter(valeur):
    if valeur is None or valeur == "":
        return valeur
    try:
        f = float(valeur)
    except (TypeError, ValueError):
        return valeur
    if f == int(f):
        return f"{int(f):,}".replace(",", " ")
    # garde 2 décimales max, séparateur de milliers sur la partie entière
    return f"{f:,.2f}".replace(",", " ").rstrip("0").rstrip(".")

app.add_template_filter(_milliers_filter, name="milliers")


# Filtre Jinja : nettoyer les sources affichées (§ → art., compactage espaces).
# Évite les caractères typographiques qui font "techniques de juriste" dans l'UI.
def _clean_source_filter(text):
    if not text:
        return ""
    import re as _re
    s = str(text)
    # § est lourd visuellement, on le remplace par "art."
    s = s.replace("§", "art.")
    # Espaces multiples → 1 espace
    s = _re.sub(r"\s+", " ", s).strip()
    return s

app.add_template_filter(_clean_source_filter, name="clean_source")


# Filtre Jinja : mettre en valeur le mot-clé d'attaque d'une alerte critique.
# Heuristique pragmatique : split sur le premier tiret cadratin "—" qui structure
# titre + détail dans les alertes du brief. Le titre passe en gras coloré.
# Si pas de séparateur, l'alerte reste en texte normal.
# Bonus : un mot d'attaque en MAJUSCULES (IRRECEVABILITÉ, IRRÉGULARITÉ, etc.)
# au tout début est mis en rouge fort.
def _format_alerte_filter(text):
    from markupsafe import Markup, escape
    import re as _re
    if not text:
        return ""
    s = str(text).strip()
    # Nettoyer les § dans le texte source aussi (cas où source apparait dans l'alerte)
    s = s.replace("§", "art.")

    # Étape 1 : split sur le premier tiret cadratin (—)
    parts = s.split("—", 1)
    if len(parts) == 2:
        titre = parts[0].strip()
        detail = parts[1].strip()
    else:
        # Pas de —, garder tout comme texte normal
        return escape(s)

    # Étape 2 : dans le titre, détecter un mot d'attaque MAJUSCULE en début
    m = _re.match(
        r"^([A-ZÉÈÊÀÂÎÔÛÇŒÆ]{5,}(?:\s+[A-ZÉÈÊÀÂÎÔÛÇŒÆ]+)*)(\s+)(.+)$",
        titre,
    )
    if m:
        verdict = m.group(1)
        reste_titre = m.group(3)
        titre_html = (
            f'<strong style="color: var(--c-rose); font-weight: 800;">{escape(verdict)}</strong>'
            f' <strong style="color: var(--apt-ink); font-weight: 700;">{escape(reste_titre)}</strong>'
        )
    else:
        # Titre simple en gras gris foncé
        titre_html = f'<strong style="color: var(--apt-ink); font-weight: 700;">{escape(titre)}</strong>'

    detail_html = f'<span style="color: var(--apt-ink-3);"> — {escape(detail)}</span>'
    return Markup(titre_html + detail_html)

app.add_template_filter(_format_alerte_filter, name="format_alerte")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VERDICT_LABEL = {
    "tres_pertinent": "Très pertinent",
    "pertinent": "Pertinent",
    "a_verifier": "À vérifier",
    "non_pertinent": "Non pertinent",
}

VERDICT_ORDRE = {
    "tres_pertinent": 0,
    "pertinent": 1,
    "a_verifier": 2,
    "non_pertinent": 3,
}

# État du contenu DCE (champ `dce_contenu`, 5 niveaux : voir tendia_dce.py).
# `montre` = faut-il afficher un badge (on n'attire pas l'œil sur "complet").
DCE_STATUT_META = {
    "complet":      {"label": "DCE complet",          "couleur": "green", "montre": False},
    "candidature":  {"label": "Phase candidature",    "couleur": "stone", "montre": True},
    "incomplet":    {"label": "DCE incomplet",        "couleur": "amber", "montre": True},
    "vide":         {"label": "DCE non récupéré",     "couleur": "rose",  "montre": True},
    "auth_requise": {"label": "DCE — accès restreint", "couleur": "amber", "montre": True},
    "erreur":       {"label": "DCE — erreur",         "couleur": "rose",  "montre": True},
}


def _dce_badge(marche: dict) -> dict | None:
    """
    Meta du badge d'état DCE pour un marché, ou None si rien à signaler
    (DCE complet, ou aucune info de contenu disponible).

    Retourne {label, couleur, montre, tooltip}.
    """
    contenu = marche.get("dce_contenu")
    meta = DCE_STATUT_META.get(contenu)
    if not meta:
        return None
    manquantes = marche.get("dce_pieces_manquantes") or []
    # Items hétérogènes : soit des strings (noms de pièces), soit des dicts
    # ({"nom", "raison_echec", ...} venant des workflows downloader).
    noms = []
    for x in manquantes:
        if isinstance(x, dict):
            n = x.get("nom") or x.get("piece") or x.get("type_detecte")
            if n:
                noms.append(str(n))
        elif x:
            noms.append(str(x))
    raison = marche.get("dce_raison_contenu") or ""
    tooltip = raison
    if noms:
        tooltip = (tooltip + " — " if tooltip else "") + "Manque : " + ", ".join(noms)
    return {**meta, "tooltip": tooltip or meta["label"]}


def _est_actif(marche: dict, fenetre_jours: int = 60) -> bool:
    """Marché toujours en lice : date limite future, ou publié récemment."""
    date_lim = marche.get("date_limite_depot")
    today = date.today().isoformat()
    if date_lim and len(date_lim) >= 10:
        return date_lim[:10] >= today
    date_pub = marche.get("date_publication")
    if not date_pub or len(date_pub) < 10:
        return False
    try:
        d = date.fromisoformat(date_pub[:10])
        return (date.today() - d).days <= fenetre_jours
    except ValueError:
        return False


def _charger_extraction_llm(id_marche: str) -> dict | None:
    """Charge le brief LLM JSON s'il existe.
    
    Stratégie de lecture (Sprint 3) :
    1. SQLite collection 'briefs_extraits' (briefs LIGHT depuis avis BOAMP
       générés par auto_brief, et briefs COMPLET depuis DCE)
    2. Fallback disque : data/extractions/<id>.json (ancien stockage Apptia)
    """
    # 1. Tentative SQLite (Sprint 3)
    try:
        brief = stockage.lire("briefs_extraits", id_marche)
        if brief is not None:
            return brief
    except Exception:
        pass

    # 2. Fallback disque (compat ancien stockage)
    chemin = REPERTOIRE_EXTRACTIONS / f"{id_marche}.json"
    if not chemin.is_file():
        return None
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _montant_marche_eur(brief: dict | None) -> float | None:
    """
    Extrait la valeur estimée du marché en euros depuis le brief LLM.
    Sources par ordre de fiabilité : valeur_estimee_euros, ou moyenne
    de la fourchette si fourchette min+max fournies.
    """
    if not brief:
        return None
    mm = brief.get("montant_marche") or {}
    v = mm.get("valeur_estimee_euros")
    if v and isinstance(v, (int, float)) and v > 0:
        return float(v)
    fmin = mm.get("fourchette_min_euros")
    fmax = mm.get("fourchette_max_euros")
    if (fmin and fmax
            and isinstance(fmin, (int, float)) and isinstance(fmax, (int, float))
            and fmin > 0 and fmax > 0):
        return (float(fmin) + float(fmax)) / 2
    return None


def _zone_prix_marche(profil: dict | None, brief: dict | None,
                       marche: dict, marches_notifies: dict) -> dict | None:
    """
    Wrapper qui appelle concurrence.zone_prix_marche() en gérant les cas
    de bord (profil absent, brief absent, base DECP vide).
    Retourne None si on ne peut rien calculer du tout — auquel cas le
    template marche.html omet le bloc zone prix.

    Source de comparables prioritaire : la base interne `marches_tendia_attribues`
    (marchés vus + attribués + briefs LLM enrichis). Fallback : DECP brut.
    """
    if not marches_notifies:
        return None
    if not profil:
        return None
    # Charger la base interne (vide tant qu'on n'a pas peuplé la collection)
    try:
        import marches_attribues
        marches_tendia = marches_attribues.lister_pour_knn()
    except Exception as e:
        print(f"⚠ Erreur chargement marches_tendia_attribues : {e}")
        marches_tendia = []
    try:
        return concurrence.zone_prix_marche(
            profil, brief, marche, marches_notifies,
            marches_tendia=marches_tendia or None,
        )
    except Exception as e:
        # Sécurité : si la fonction plante, on n'affiche rien plutôt que de
        # casser la page. À surveiller dans les logs.
        print(f"⚠ Erreur zone_prix_marche pour {marche.get('id')} : {e}")
        return None


def _evaluer_marche(profil: dict, marche: dict) -> dict | None:
    """Calcule le verdict matching d'un marché contre un profil."""
    try:
        # Sprint B : brief passe au matching pour scoring sectoriel.
        brief = stockage.lire("briefs_extraits", marche.get("id"))
        return matching.evaluer(profil, marche, brief=brief)
    except Exception:
        return None


def _jours_restants(date_limite: str | None) -> int | None:
    if not date_limite or len(date_limite) < 10:
        return None
    try:
        d = date.fromisoformat(date_limite[:10])
        delta = (d - date.today()).days
        return delta
    except ValueError:
        return None


_MOIS_FR = ['', 'janvier', 'février', 'mars', 'avril', 'mai', 'juin',
            'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']
_MOIS_FR_COURT = ['', 'jan', 'fév', 'mar', 'avr', 'mai', 'juin',
                  'juil', 'août', 'sept', 'oct', 'nov', 'déc']


def _fmt_date(s: str | None) -> str:
    """Format une date ISO en français court : '10 juin 2026'."""
    if not s or len(s) < 10:
        return "—"
    try:
        d = date.fromisoformat(s[:10])
        return f"{d.day} {_MOIS_FR_COURT[d.month]} {d.year}"
    except ValueError:
        return s[:10]


def _date_fr_long(d) -> str:
    """Format une date Python en français long : '5 juin 2026'.
    Indépendant de la locale système (qui sur Windows renvoie souvent l'anglais)."""
    if not d:
        return ""
    return f"{d.day} {_MOIS_FR[d.month]} {d.year}"


def _titre_court(marche: dict, n: int = 110) -> str:
    titre = (marche.get("titre") or marche.get("objet") or "").strip()
    titre = " ".join(titre.split())
    return titre[:n] + ("…" if len(titre) > n else "")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def dashboard():
    """Page d'accueil : tableau des marchés actifs + KPIs pipeline."""
    marches = stockage.charger("marches")
    profil = organisme.lire_profil()

    # Marchés actifs (date limite future ou publié récemment)
    actifs = [m for m in marches.values() if _est_actif(m)]

    # === Filtrage par les secteurs (presets) du PROFIL ORGANISME ACTIF ===
    # Le profil organisme actif définit les secteurs couverts (presets_couverts).
    # On ne garde que les marchés pertinents pour AU MOINS UN de ces secteurs,
    # d'après la collection scores_matching (calculée par analyse.py).
    # Sans scores pour ces secteurs (analyse jamais lancée) : comportement
    # legacy = tous les marchés actifs.
    #
    # NB : on s'appuie sur presets_couverts du profil, PAS sur preset.code_actif()
    # (réglage global distinct) — c'est le profil activé dans /profil qui pilote
    # désormais le dashboard.
    presets_profil = (profil or {}).get("presets_couverts") or []
    ids_pertinents = set()
    if presets_profil:
        try:
            scores_all = stockage.charger("scores_matching") or {}
            for entree in scores_all.values():
                if (entree.get("preset_code") in presets_profil
                        and entree.get("matche")):
                    ids_pertinents.add(entree.get("marche_id"))
        except Exception:
            ids_pertinents = set()

    filtre_preset_actif = bool(presets_profil and ids_pertinents)
    if filtre_preset_actif:
        actifs = [m for m in actifs if m["id"] in ids_pertinents]

    # Charge la collection des briefs SQLite une fois (au lieu de N appels)
    try:
        briefs_sqlite = stockage.charger("briefs_extraits")
    except Exception:
        briefs_sqlite = {}

    # Évalue chaque marché actif contre le profil
    import matching_exigences
    import cycle_marche
    enriched = []
    for m in actifs:
        evaluation = _evaluer_marche(profil, m) if profil else None
        # a_brief : SQLite (Sprint 3) OU disque (compat Apptia)
        a_brief = (m["id"] in briefs_sqlite
                   or (REPERTOIRE_EXTRACTIONS / f"{m['id']}.json").is_file())
        # Charge le brief si présent : montant + verdict d'éligibilité + type
        brief_m = None
        montant_eur = None
        verdict_elig = None
        type_brief = None  # 'COMPLET' / 'LIGHT' / 'INCONNU' / None
        if a_brief:
            brief_m = _charger_extraction_llm(m["id"])
            montant_eur = _montant_marche_eur(brief_m)
            if brief_m:
                meta = brief_m.get("_meta") or {}
                t = (meta.get("type") or "").upper()
                if t in ("COMPLET", "LIGHT"):
                    type_brief = t
                else:
                    # Heuristique : présence de sections riches = COMPLET
                    riches = ("bareme_notation", "alertes_candidat",
                              "modalites_consultation", "lots_detailles")
                    if any(brief_m.get(k) for k in riches):
                        type_brief = "COMPLET"
                    else:
                        type_brief = "INCONNU"
            if profil and brief_m:
                alertes = brief_m.get("alertes_candidat") or []
                if alertes:
                    evaluees = matching_exigences.evaluer_alertes(alertes, profil)
                    verdict_elig = matching_exigences.verdict_eligibilite(evaluees)
        # Domaine LLM principal (depuis brief.domaines_metier)
        domaine_principal = None
        domaine_tooltip = None
        if brief_m:
            doms = brief_m.get("domaines_metier") or []
            if doms and isinstance(doms, list):
                # 1er domaine = principal (s'il y a un poids, c'est le plus élevé en supposant tri)
                # On affiche le code du domaine le mieux noté
                d_principal = max(doms, key=lambda d: d.get("poids", 1.0) if isinstance(d, dict) else 0)
                if isinstance(d_principal, dict):
                    domaine_principal = d_principal.get("code")
                    # Tooltip détaillé : tous les domaines avec poids
                    parts = []
                    for d in doms:
                        if not isinstance(d, dict):
                            continue
                        c = d.get("code", "?")
                        p = d.get("poids")
                        if p:
                            parts.append(f"{c} ({int(p*100)}%)")
                        else:
                            parts.append(c)
                    domaine_tooltip = "Classification IA : " + ", ".join(parts)

        statut_cycle = cycle_marche.statut(m)
        enriched.append({
            "marche": m,
            "eval": evaluation,
            "verdict": (evaluation or {}).get("verdict"),
            "score": (evaluation or {}).get("score", 0),
            "titre_court": _titre_court(m),
            "date_limite_fmt": _fmt_date(m.get("date_limite_depot")),
            "jours_restants": _jours_restants(m.get("date_limite_depot")),
            "a_brief_llm": a_brief,
            "type_brief": type_brief,
            "montant_eur": montant_eur,
            "verdict_eligibilite": verdict_elig,
            "statut_cycle": statut_cycle,
            "statut_cycle_meta": cycle_marche.meta(statut_cycle),
            "domaine_llm_principal": domaine_principal,
            "domaine_llm_tooltip": domaine_tooltip,
            "dce_badge": _dce_badge(m),
        })

    # Tri : par verdict puis par score décroissant
    enriched.sort(key=lambda x: (
        VERDICT_ORDRE.get(x["verdict"], 99),
        -x["score"],
    ))

    # KPIs
    ids_actifs = [m["id"] for m in actifs]
    pipeline = cycle_marche.kpis_pipeline(marches, ids_actifs=ids_actifs)
    kpis = {
        "actifs_total": len(actifs),
        "tres_pertinents": sum(1 for e in enriched
                                  if e["verdict"] == "tres_pertinent"),
        "pertinents": sum(1 for e in enriched if e["verdict"] == "pertinent"),
        "avec_brief": sum(1 for e in enriched if e["a_brief_llm"]),
        "marches_total": len(marches),
        # Pipeline commercial
        "pipeline": pipeline,
        # Indique si le filtre par secteurs du profil actif s'applique
        "filtre_preset_actif": filtre_preset_actif,
        "preset_code_actif": ", ".join(presets_profil) if presets_profil else None,
    }

    return render_template(
        "dashboard.html",
        kpis=kpis,
        marches_enriched=enriched,
        organisme=profil,
        verdict_label=VERDICT_LABEL,
        now=datetime.now(),
    )


# ---------------------------------------------------------------------------
# /explorer — Vue exploratoire de TOUS les marchés classifiés (Sprint 2)
# ---------------------------------------------------------------------------

# Familles racine — préfixe → libellé d'affichage
_FAMILLES_RACINE = {
    "formation":     "Formation & insertion",
    "insertion":     "Formation & insertion",
    "bilan":         "Formation & insertion",
    "energie":       "Énergie",
    "btp":           "BTP & travaux",
    "ingenierie":    "Ingénierie & études",
    "moe":           "Ingénierie & études",
    "topographie":   "Ingénierie & études",
    "conseil":       "Conseil & stratégie",
    "it":            "IT & numérique",
    "services":      "Services environnement/santé",
    "transport":     "Transport & logistique",
    "securite":      "Sécurité & gardiennage",
    "restauration":  "Restauration",
    "amenagement":   "Espaces verts & paysager",
    "entretien":     "Entretien & propreté",
    "fourniture":    "Fournitures",
    "assurance":     "Assurance",
    "evenementiel":  "Événementiel & culture",
    "prestations":   "Prestations spéciales",
    "traduction":    "Traduction & interprétariat",
    "voyage":        "Voyages d'affaires",
    "petite":        "Petite enfance & périscolaire",
    "gestion":       "Gestion documentaire",
    "autre":         "Autre",
}


# Typos de préfixe fréquents produits par le LLM (ex. 'energia' au lieu de 'energie').
_TYPO_PREFIXE_DOMAINE = {"energia": "energie", "energy": "energie",
                         "ingenerie": "ingenierie", "ingeniere": "ingenierie"}
_TAXO_DOMAINES_CACHE = None


def _normaliser_code_domaine(code: str) -> str:
    """Normalise un code domaine LLM : minuscules, sans accents, typos de préfixe
    corrigées (energia→energie). Évite le « Autre » dû à une faute de frappe du LLM."""
    if not code:
        return ""
    import unicodedata as _ud
    c = _ud.normalize("NFKD", str(code).strip().lower())
    c = "".join(ch for ch in c if not _ud.combining(ch))
    prefix, sep, reste = c.partition("_")
    prefix = _TYPO_PREFIXE_DOMAINE.get(prefix, prefix)
    return f"{prefix}_{reste}" if sep else prefix


def _libelle_domaine(code: str) -> str:
    """Code domaine → libellé lisible de la taxonomie (tolérant aux typos),
    sinon le code titleisé en repli."""
    global _TAXO_DOMAINES_CACHE
    if _TAXO_DOMAINES_CACHE is None:
        try:
            import llm_extract
            _TAXO_DOMAINES_CACHE = (llm_extract._charger_taxonomie() or {}).get("domaines", {})
        except Exception:
            _TAXO_DOMAINES_CACHE = {}
    d = _TAXO_DOMAINES_CACHE.get(_normaliser_code_domaine(code))
    if isinstance(d, dict) and d.get("libelle"):
        return d["libelle"]
    return str(code or "").replace("_", " ").strip().title() or "Autre"


def _famille_pour_domaine(code: str) -> str:
    """Retourne la famille racine d'un code domaine (typos corrigées)."""
    code = _normaliser_code_domaine(code)
    if not code:
        return "Autre"
    prefix = code.split("_", 1)[0]
    return _FAMILLES_RACINE.get(prefix, "Autre")


app.add_template_filter(_libelle_domaine, name="libelle_domaine")


@app.route("/explorer")
def explorer():
    """
    Vue exploratoire de TOUS les marchés classifiés (pas filtrés par preset).

    Permet de naviguer la base complète par famille / sous-domaine / zone,
    pour identifier des opportunités sur secteurs non couverts par les
    presets installés (démarchage prospect).

    Query params optionnels :
        ?famille=BTP
        ?domaine=btp_voirie_reseaux
        ?zone=texte
        ?recherche=texte_libre
    """
    import stockage
    marches = stockage.charger("marches") or {}
    classifs_ia = stockage.charger("classifications_ia") or {}
    briefs = stockage.charger("briefs_extraits") or {}

    # Lecture des filtres URL
    filtre_famille = (request.args.get("famille") or "").strip()
    filtre_domaine = (request.args.get("domaine") or "").strip()
    filtre_zone = (request.args.get("zone") or "").strip().lower()
    filtre_recherche = (request.args.get("recherche") or "").strip().lower()
    # Filtre par tag de richesse du brief (complet / partiel / light).
    filtre_brief = (request.args.get("brief") or "").strip().lower()
    # Filtres de pertinence/éligibilité (MULTI-sélection via getlist).
    filtre_verdicts = [v for v in request.args.getlist("verdict") if v]
    filtre_elig = [e for e in request.args.getlist("elig") if e]
    try:
        filtre_score_min = int(request.args.get("score_min") or 0)
    except (TypeError, ValueError):
        filtre_score_min = 0
    # Profil actif → évaluation matching (verdict/score/éligibilité) à la volée.
    import matching_exigences
    profil_actif = organisme.lire_profil()

    # Charge taxonomie pour les libellés
    import json
    try:
        chemin_tax = Path(__file__).parent / "presets" / "_taxonomie_domaines.json"
        taxonomie = json.loads(chemin_tax.read_text(encoding="utf-8"))
        domaines_def = taxonomie.get("domaines", {})
    except Exception:
        domaines_def = {}

    # Construction de la table enrichie : 1 ligne par marché classifié
    lignes = []
    for id_m, marche in marches.items():
        # Récupérer la classification (prio brief COMPLET, fallback classification IA)
        classif = None
        source = None
        brief = briefs.get(id_m)
        if brief and brief.get("domaines_metier"):
            classif = brief
            source = "brief_complet"
        elif id_m in classifs_ia:
            classif = classifs_ia[id_m]
            source = "classification_ia"

        if not classif:
            continue

        doms = classif.get("domaines_metier") or []
        if not isinstance(doms, list) or not doms:
            continue
        valides = [d for d in doms if isinstance(d, dict) and d.get("code")]
        if not valides:
            continue
        principal = max(valides, key=lambda d: d.get("poids") or 1.0)
        code_principal = principal.get("code")
        famille = _famille_pour_domaine(code_principal)

        # Filtres
        if filtre_famille and famille != filtre_famille:
            continue
        if filtre_domaine and code_principal != filtre_domaine:
            continue
        if filtre_zone:
            zone_str = (marche.get("perimetre_geographique") or "").lower()
            if filtre_zone not in zone_str:
                continue
        if filtre_recherche:
            haystack = " ".join([
                (marche.get("titre") or ""),
                (marche.get("objet") or ""),
                (marche.get("acheteur_nom") or ""),
                # Référence d'avis : permet de coller un code dans la recherche
                # (ex. "55977", "26-55977" ou "BOAMP-26-55977" trouvent le marché).
                str(id_m or ""),
                (marche.get("reference_externe") or ""),
                (marche.get("reference_ft") or ""),
            ]).lower()
            if filtre_recherche not in haystack:
                continue

        presets_l = fiche_marche.resolve_preset_codes(brief) if (brief and brief.get("domaines_metier")) else []
        richesse_l = (fiche_marche.calculer_richesse_brief(brief, presets_l, marche)
                      if brief else {"score": 0, "niveau": "light"})

        # Évaluation matching vs profil actif (verdict + score + éligibilité), à la volée.
        evaluation_l = None
        verdict_elig_l = None
        if profil_actif:
            try:
                evaluation_l = matching.evaluer(profil_actif, marche, brief=brief)
            except Exception:
                evaluation_l = None
            alertes_l = (brief or {}).get("alertes_candidat") or []
            if alertes_l:
                try:
                    verdict_elig_l = matching_exigences.verdict_eligibilite(
                        matching_exigences.evaluer_alertes(alertes_l, profil_actif))
                except Exception:
                    verdict_elig_l = None

        lignes.append({
            "marche": marche,
            "id_marche": id_m,
            "richesse": richesse_l,
            "verdict": (evaluation_l or {}).get("verdict"),
            "score": (evaluation_l or {}).get("score"),
            "eligibilite": verdict_elig_l,
            "titre_court": _titre_court(marche),
            "acheteur": marche.get("acheteur_nom") or "—",
            "perimetre": marche.get("perimetre_geographique") or "",
            "date_limite_fmt": _fmt_date(marche.get("date_limite_depot")),
            "jours_restants": _jours_restants(marche.get("date_limite_depot")),
            "domaine_principal": code_principal,
            "domaine_libelle": _libelle_domaine(code_principal),
            "famille": famille,
            "tous_domaines": valides,
            "raison": classif.get("raison_classification", "")[:200],
            "synthese": classif.get("synthese_courte") or classif.get("synthese_marche", "")[:200],
            "source_classification": source,
            "a_brief_complet": source == "brief_complet",
        })

    # Filtre optionnel : uniquement briefs complets/partiels (Sprint UI L7.3)
    if request.args.get("complet"):
        lignes = [l for l in lignes if l["richesse"]["niveau"] in ("complet", "partiel")]
    # Filtre par tag de richesse (niveau exact : complet / partiel / light).
    if filtre_brief in ("complet", "partiel", "light"):
        lignes = [l for l in lignes if l["richesse"]["niveau"] == filtre_brief]
    # Filtres pertinence (multi) / éligibilité (multi) / score minimum.
    if filtre_verdicts:
        lignes = [l for l in lignes if l.get("verdict") in filtre_verdicts]
    if filtre_elig:
        lignes = [l for l in lignes
                  if (l.get("eligibilite") or {}).get("statut") in filtre_elig]
    if filtre_score_min > 0:
        lignes = [l for l in lignes if (l.get("score") or 0) >= filtre_score_min]

    # Tri par défaut : richesse brief décroissante, puis urgence (jours croissants)
    lignes.sort(key=lambda x: (
        -x["richesse"]["score"],
        x["jours_restants"] if x["jours_restants"] is not None else 9999,
    ))

    # Stats agrégées POUR LES FILTRES (calculées sur TOUT le classifié, pas filtré)
    # → permet d'afficher "Familles: BTP (145), Énergie (12), ..."
    from collections import Counter
    stats_familles = Counter()
    stats_domaines = Counter()
    domaines_par_famille = {}  # famille → set(domaines)
    for id_m, marche in marches.items():
        classif = None
        brief = briefs.get(id_m)
        if brief and brief.get("domaines_metier"):
            classif = brief
        elif id_m in classifs_ia:
            classif = classifs_ia[id_m]
        if not classif:
            continue
        doms = classif.get("domaines_metier") or []
        if not isinstance(doms, list):
            continue
        valides = [d for d in doms if isinstance(d, dict) and d.get("code")]
        if not valides:
            continue
        principal = max(valides, key=lambda d: d.get("poids") or 1.0)
        code = principal.get("code")
        fam = _famille_pour_domaine(code)
        stats_familles[fam] += 1
        stats_domaines[code] += 1
        domaines_par_famille.setdefault(fam, set()).add(code)

    # Pour la sidebar : familles triées par volume desc + sous-domaines triés
    familles_triees = [
        {
            "nom": fam,
            "total": n,
            "domaines": sorted(
                [(d, stats_domaines[d], (domaines_def.get(d) or {}).get("libelle", d))
                 for d in domaines_par_famille.get(fam, set())],
                key=lambda x: -x[1]
            ),
        }
        for fam, n in stats_familles.most_common()
    ]

    return render_template(
        "explorer.html",
        lignes=lignes,
        familles_triees=familles_triees,
        total_classifies=sum(stats_familles.values()),
        total_marches=len(marches),
        filtres={
            "famille": filtre_famille,
            "domaine": filtre_domaine,
            "zone": filtre_zone,
            "recherche": filtre_recherche,
            "brief": filtre_brief,
            "verdicts": filtre_verdicts,
            "elig": filtre_elig,
            "score_min": filtre_score_min,
        },
        verdict_label=VERDICT_LABEL,
        a_profil=bool(profil_actif),
        organisme=organisme.lire_profil(),
        now=datetime.now(),
    )


@app.route("/marche/<id_marche>/cycle", methods=["POST"])
def changer_cycle(id_marche):
    """Change le statut du cycle de vie d'un marché.

    Body form-encoded: statut=<nouveau_statut> [, note=<texte>]
    Redirige vers la fiche ou le dashboard selon l'origine.
    """
    import cycle_marche
    from flask import request, redirect, url_for, flash
    nouveau = request.form.get("statut", "").strip()
    note = request.form.get("note", "").strip()
    retour = request.form.get("retour", "fiche")
    res = cycle_marche.changer_statut(id_marche, nouveau, note=note)
    if not res.get("ok"):
        # Pour ne pas bloquer le user, on log juste et on redirige
        print(f"[cycle] Erreur changement statut {id_marche} → {nouveau} : "
              f"{res.get('erreur')}")
    if retour == "dashboard":
        return redirect(url_for("dashboard"))
    return redirect(url_for("detail_marche", id_marche=id_marche))


@app.route("/marche-notifie/<path:id_marche>")
def detail_marche_notifie(id_marche):
    """Page détail d'un marché DECP notifié (historique).

    Affiche la fiche complète d'un marché historique de la base DECP
    consolidée : acheteur, titulaire, montant, durée, accord-cadre, etc.
    Sert notamment quand on clique sur un comparable depuis une fiche
    marché active (zone_prix.top_comparables).
    """
    try:
        marches_notifies = stockage.charger("marches_notifies") or {}
    except Exception:
        marches_notifies = {}

    marche_n = marches_notifies.get(id_marche)
    if not marche_n:
        abort(404)

    # Construit une URL Google pour recherche externe complémentaire
    # (avis original, profil titulaire, articles presse, etc.)
    parts = []
    if marche_n.get("titulaire_nom"):
        parts.append(f'"{marche_n["titulaire_nom"]}"')
    if marche_n.get("acheteur_nom"):
        # Garde juste "France Travail" + DR si présent
        nom = marche_n["acheteur_nom"]
        parts.append(f'"{nom}"')
    if marche_n.get("objet"):
        # Premiers mots significatifs
        mots = marche_n["objet"].split()[:6]
        parts.append(" ".join(mots))
    query_google = " ".join(parts)
    from urllib.parse import quote_plus
    url_google = f"https://www.google.com/search?q={quote_plus(query_google)}"

    return render_template(
        "marche_notifie.html",
        m=marche_n,
        url_google=url_google,
    )


# Libellés parlants pour les pièces de DCE (au lieu des sigles RC/CCAP/…).
# Ordre = du plus spécifique au plus générique (évite que CCP matche avant CCTP).
_DOC_LABELS = [
    ("CCTP", "Cahier des clauses techniques (CCTP)"),
    ("CCTG", "Cahier des clauses techniques générales (CCTG)"),
    ("CCAP", "Cahier des clauses administratives (CCAP)"),
    ("CCAG", "Cahier des clauses administratives générales (CCAG)"),
    ("CCP", "Cahier des clauses particulières (CCP)"),
    ("DPGF", "Décomposition du prix global et forfaitaire (DPGF)"),
    ("BPU", "Bordereau des prix unitaires (BPU)"),
    ("DQE", "Détail quantitatif estimatif (DQE)"),
    ("DE", "Détail estimatif (DE)"),
    ("BP", "Bordereau des prix (BP)"),
    ("CMT", "Cadre de mémoire technique (CMT)"),
    ("MT", "Mémoire technique"),
    ("AAPC", "Avis d'appel public à la concurrence"),
    ("DUME", "Document unique de marché européen (DUME)"),
    ("DC1", "Lettre de candidature (DC1)"),
    ("DC2", "Déclaration du candidat (DC2)"),
    ("DC4", "Déclaration de sous-traitance (DC4)"),
    ("AE", "Acte d'engagement"),
    ("RC", "Règlement de consultation"),
]


def _libelle_document(nom: str) -> str:
    """Transforme un nom de fichier DCE en libellé parlant (sigle → intitulé)."""
    base = os.path.splitext(nom)[0]
    tokens = [t.upper() for t in re.split(r"[^A-Za-z0-9]+", base) if t]
    for abbr, label in _DOC_LABELS:
        for t in tokens:
            # token exact, ou sigle suivi d'un chiffre de version (CCTP3, RC2024)
            if t == abbr or (t.startswith(abbr) and t[len(abbr):len(abbr) + 1].isdigit()):
                return label
    # Repli : sigle/intitulé de tête (tokens AVANT la première référence chiffrée),
    # pour que les pièces sœurs partagent un libellé et soient groupées (variantes).
    tete = []
    for t in tokens:
        if any(c.isdigit() for c in t):
            break
        tete.append(t)
    if tete:
        return " ".join(tete)
    propre = re.sub(r"^\d+[\.\)\-_ ]+", "", base).replace("_", " ").strip()
    return propre or nom


def _lcs(a: str, b: str) -> str:
    """Plus longue sous-chaîne commune (sert à isoler la référence partagée)."""
    if not a or not b:
        return ""
    prev = [0] * (len(b) + 1)
    best = fin = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best, fin = cur[j], i
        prev = cur
    return a[fin - best:fin]


def _prettifier_variante(v: str) -> str:
    v = v.strip()
    if not v:
        return ""
    if re.fullmatch(r"[A-Za-z]", v):
        return "partie " + v.upper()
    m = re.fullmatch(r"[Aa](\d+)", v)
    if m:
        return "annexe " + m.group(1)
    if re.search(r"\d{3,}", v):
        return ""  # variante qui contient encore une référence → bruit, on masque
    return v


def _distinguer_variantes(docs: list) -> None:
    """Quand plusieurs documents partagent le même libellé (pièce découpée en
    parties/annexes), calcule un discriminateur court (« partie A », « annexe 1 »)
    pour ne pas donner l'impression d'un doublon. Mute `docs` en place."""
    from collections import defaultdict
    groupes = defaultdict(list)
    for d in docs:
        d["variante"] = ""
        groupes[d["label"]].append(d)
    for items in groupes.values():
        if len(items) < 2:
            continue
        bases = [os.path.splitext(d["nom"])[0] for d in items]
        # référence commune au groupe (ex. "2026031910MV") via LCS réduit
        ref = bases[0]
        for b in bases[1:]:
            ref = _lcs(ref, b)
            if len(ref) < 4:
                ref = ""
                break
        # sigil de type commun en tête (ex. "CCTP") à retirer
        def _t0(b):
            toks = [t for t in re.split(r"[^A-Za-z0-9]+", b) if t]
            return toks[0].upper() if toks else ""
        type_tok = _t0(bases[0])
        if not all(_t0(b) == type_tok for b in bases):
            type_tok = None
        for d, base in zip(items, bases):
            v = base.replace(ref, " ") if ref else base
            toks = [t for t in re.split(r"[^A-Za-z0-9]+", v) if t and t.upper() != type_tok]
            d["variante"] = _prettifier_variante(" ".join(toks))


@app.route("/marche/<id_marche>/document/<path:nom>")
def telecharger_document(id_marche, nom):
    """Télécharge un document analysé du DCE local (clic sur la fiche)."""
    dossier = (REPERTOIRE_DCE / id_marche).resolve()
    if not dossier.is_dir():
        abort(404)
    try:
        return send_from_directory(dossier, nom, as_attachment=True)
    except (FileNotFoundError, NotADirectoryError):
        abort(404)


@app.route("/marche/<id_marche>")
def detail_marche(id_marche):
    """Page détail d'un marché."""
    marches = stockage.charger("marches")
    marche = marches.get(id_marche)
    if not marche:
        abort(404)
    profil = organisme.lire_profil()
    evaluation = _evaluer_marche(profil, marche) if profil else None
    brief = _charger_extraction_llm(id_marche)

    # Détection du type de brief (LIGHT depuis avis vs COMPLET depuis DCE)
    brief_type = None
    if brief:
        try:
            import auto_brief
            if auto_brief.est_brief_light(brief):
                brief_type = "light"
            elif auto_brief.est_brief_complet(brief):
                brief_type = "complet"
            else:
                brief_type = "complet"  # défaut prudent
        except Exception:
            brief_type = "complet"

    # Charge la base DECP une fois pour la réutiliser (concurrents + zone prix)
    try:
        marches_notifies = stockage.charger("marches_notifies") or {}
    except Exception:
        marches_notifies = {}

    # Concurrents historiques DECP sur le segment
    concurrents = _trouver_concurrents(marche, marches_notifies=marches_notifies)

    # Zone de prix FT (KNN sur DECP) — B6/B7
    zone_prix = _zone_prix_marche(profil, brief, marche, marches_notifies)

    # Calibration LLM (2e passe Apptia) RETIRÉE de la fiche : son prompt était
    # verrouillé sur le preset actif (`formation`) et inadapté aux autres secteurs
    # (BTP/IT/…) → "indisponible". Elle fait désormais doublon avec la Voie 2 de
    # l'extraction v2 (`montant_3_voies`), qui est multi-preset. La section est masquée
    # (calibration=None → le `{% if calibration %}` du template ne rend rien).
    calibration = None

    # Montant estimé du marché extrait par le brief LLM — B3/B11
    montant_marche_eur = _montant_marche_eur(brief)

    # Dossier local DCE
    dossier_dce = REPERTOIRE_DCE / id_marche
    pdfs_locaux = []
    docs_analyses = []
    if dossier_dce.is_dir():
        for nom in sorted(os.listdir(dossier_dce)):
            bas = nom.lower()
            if bas.endswith(".pdf"):
                pdfs_locaux.append(nom)
            if bas.endswith((".pdf", ".docx", ".xlsx", ".doc")):
                docs_analyses.append({
                    "nom": nom,
                    "label": _libelle_document(nom),
                    "ext": os.path.splitext(nom)[1].lstrip(".").upper(),
                })
    # Distingue les pièces découpées (CCTP partie A, annexe 1…) pour éviter
    # l'effet « doublon » quand plusieurs fichiers ont le même libellé.
    _distinguer_variantes(docs_analyses)

    # Matching exigences alertes ↔ profil organisme
    import matching_exigences
    import cycle_marche
    alertes_evaluees = matching_exigences.evaluer_alertes(
        (brief or {}).get("alertes_candidat") or [], profil or {}
    )
    couverture_synthese = matching_exigences.synthese_couverture(alertes_evaluees)
    verdict_eligibilite = matching_exigences.verdict_eligibilite(alertes_evaluees)

    # Fourchette montant total : 3 scénarios (bas / réaliste / haut)
    import fourchette_scenarios
    scenarios_montant = fourchette_scenarios.construire_scenarios(
        calibration, brief
    )

    # --- Sprint UI : structures preset-aware (fiche_marche) ---
    presets_resolus = fiche_marche.resolve_preset_codes(brief or {})
    kpi_cards = fiche_marche.kpi_cards_pour_marche(brief, marche, presets_resolus, calibration)
    # Enrichit la card Valeur avec la fourchette de scénarios si pas de montant direct
    if kpi_cards and kpi_cards[0]["valeur"] == "—" and scenarios_montant:
        bas = (scenarios_montant.get("bas") or {}).get("montant_eur")
        haut = (scenarios_montant.get("haut") or {}).get("montant_eur")
        if bas and haut:
            kpi_cards[0]["valeur"] = f"{fiche_marche._fmt_eur(bas)} – {fiche_marche._fmt_eur(haut)}"
            kpi_cards[0]["hint"] = "estimation Tendia"
            kpi_cards[0]["classe"] = "val"
    verrous = fiche_marche.detecter_verrous(brief or {}, profil or {})
    verdict_90 = fiche_marche.verdict_90_secondes(brief or {}, evaluation, profil or {}, verrous)
    blocs_sectoriels = fiche_marche.bloc_sectoriel_pour_marche(brief or {}, presets_resolus, profil or {})
    detail_lots = fiche_marche.tranches_ou_lots(brief or {}, profil or {})
    richesse = fiche_marche.calculer_richesse_brief(brief or {}, presets_resolus, marche)

    # Voie 3 — comparables DECP (calibration du montant sur contrats réels exécutés).
    # Calculé au rendu (quelques requêtes SQL indexées, pas de LLM). Sert à ancrer le
    # Revenu estimé sur des données réelles quand le DCE ne publie pas de montant.
    try:
        import decp_comparables
        _preset_v3 = presets_resolus[0] if presets_resolus else None
        if isinstance(_preset_v3, (list, tuple)):
            _preset_v3 = _preset_v3[0]
        voie3 = decp_comparables.comparables_pour_marche(marche, _preset_v3)
    except Exception:
        voie3 = {"disponible": False}

    return render_template(
        "marche.html",
        voie3=voie3,
        marche=marche,
        eval=evaluation,
        brief=brief,
        presets_resolus=presets_resolus,
        kpi_cards=kpi_cards,
        verrous=verrous,
        verdict_90=verdict_90,
        blocs_sectoriels=blocs_sectoriels,
        detail_lots=detail_lots,
        richesse=richesse,
        dce_contenu=marche.get("dce_contenu"),
        dce_raison_contenu=marche.get("dce_raison_contenu"),
        dce_pieces=marche.get("dce_pieces_contractuelles") or [],
        dce_pieces_manquantes=marche.get("dce_pieces_manquantes") or [],
        brief_type=brief_type,
        concurrents=concurrents,
        zone_prix=zone_prix,
        calibration=calibration,
        scenarios_montant=scenarios_montant,
        montant_marche_eur=montant_marche_eur,
        pdfs_locaux=pdfs_locaux,
        docs_analyses=docs_analyses,
        dossier_dce=str(dossier_dce),
        organisme=profil,
        alertes_evaluees=alertes_evaluees,
        couverture_synthese=couverture_synthese,
        verdict_eligibilite=verdict_eligibilite,
        cycle=cycle_marche.lire_cycle(marche),
        cycle_statut=cycle_marche.statut(marche),
        cycle_meta=cycle_marche.meta(cycle_marche.statut(marche)),
        cycle_transitions=cycle_marche.transitions_possibles(cycle_marche.statut(marche)),
        verdict_label=VERDICT_LABEL,
        jours_restants=_jours_restants(marche.get("date_limite_depot")),
        fmt_date=_fmt_date,
    )


@app.route("/marche/<id_marche>/calibrer", methods=["POST"])
def calibrer_marche(id_marche):
    """Lance une calibration bottom-up à la demande (~0.1-0.5€ LLM)."""
    marche = (stockage.charger("marches") or {}).get(id_marche)
    if not marche:
        abort(404)
    brief = _charger_extraction_llm(id_marche)
    if not brief:
        flash("Aucun brief à calibrer pour ce marché.", "erreur")
        return redirect(url_for("detail_marche", id_marche=id_marche))
    try:
        import llm_calibration
        res = llm_calibration.calibrer_et_cacher(
            id_marche, brief, None, {}, force=True, verbose=False, mode="bottom_up")
        if res:
            flash("Calibration bottom-up effectuée.", "succes")
        else:
            flash("Calibration non aboutie (brief insuffisant pour estimer).", "erreur")
    except Exception as e:
        flash(f"Échec de la calibration : {e}", "erreur")
    return redirect(url_for("detail_marche", id_marche=id_marche))


@app.route("/marche/<id_marche>/retenter-dce", methods=["POST"])
def retenter_dce(id_marche):
    """Re-tente le téléchargement du DCE puis re-qualifie le contenu."""
    marches = stockage.charger("marches") or {}
    marche = marches.get(id_marche)
    if not marche:
        abort(404)
    import tendia_dce
    if tendia_dce.url_est_auth_requise(marche.get("url_dce") or ""):
        flash("Plateforme à authentification : téléchargement automatique impossible. "
              "Connecte-toi via l'avis BOAMP.", "erreur")
        return redirect(url_for("detail_marche", id_marche=id_marche))
    try:
        import requests
        import tendia_telecharger_dce as tdce
        log = tdce._telecharger_marche(marche, session=requests.Session(),
                                       force=True, dry_run=False, verbose=False)
    except Exception as e:
        log = {"statut": "erreur", "raison": f"{type(e).__name__}: {e}"}
    dossier = str(REPERTOIRE_DCE / id_marche)
    qual = tendia_dce.qualifier_dce(dossier, log)
    marche["dce_contenu"] = qual["qualite"]
    marche["dce_pieces_contractuelles"] = qual["pieces_contractuelles"]
    marche["dce_raison_contenu"] = qual["raison"]
    marche["dce_relance_le"] = datetime.now().isoformat()
    stockage.ecrire("marches", id_marche, marche)
    if qual["qualite"] in ("complet", "incomplet"):
        flash(f"Téléchargement réussi : DCE {qual['qualite']} "
              f"({', '.join(qual['pieces_contractuelles']) or qual['raison']}).", "succes")
    elif qual["qualite"] == "erreur":
        flash("Erreur réseau, ré-essaye dans quelques minutes.", "erreur")
    elif qual["qualite"] == "auth_requise":
        flash("DCE sur plateforme à authentification — non récupérable en auto.", "erreur")
    else:
        flash("Téléchargement effectué mais DCE toujours indisponible.", "erreur")
    return redirect(url_for("detail_marche", id_marche=id_marche))


@app.route("/marche/<id_marche>/retenter-pieces-manquantes", methods=["POST"])
def retenter_pieces_manquantes(id_marche):
    """Re-tente UNIQUEMENT les pièces DCE manquantes, puis re-qualifie."""
    marche = stockage.lire("marches", id_marche)
    if not marche:
        abort(404)
    manquantes = marche.get("dce_pieces_manquantes") or []
    if not manquantes:
        flash("Aucune pièce manquante à retenter.", "succes")
        return redirect(url_for("detail_marche", id_marche=id_marche))
    import requests
    import tendia_dce
    import tendia_telecharger_dce as tdce
    session = requests.Session()
    session.headers.update({"User-Agent": tdce.USER_AGENT,
                            "Accept-Language": "fr-FR,fr;q=0.9"})
    dossier = str(REPERTOIRE_DCE / id_marche)
    recuperees, encore = [], []
    for piece in manquantes:
        try:
            ok, info = tdce._telecharger_avec_retry(session, piece, dossier, max_essais=2)
        except Exception as e:
            ok, info = False, {"erreur": f"{type(e).__name__}: {e}"}
        if ok:
            recuperees.append(info)
        else:
            encore.append({**piece, "raison_echec": info.get("erreur", "?")})
    qual = tendia_dce.qualifier_dce(dossier)
    marche["dce_contenu"] = qual["qualite"]
    marche["dce_pieces_contractuelles"] = qual["pieces_contractuelles"]
    marche["dce_pieces_manquantes"] = encore
    marche["dce_raison_contenu"] = qual["raison"]
    stockage.ecrire("marches", id_marche, marche)
    if recuperees:
        flash(f"{len(recuperees)} pièce(s) récupérée(s).", "succes")
    else:
        flash("Aucune pièce supplémentaire récupérée cette fois.", "erreur")
    return redirect(url_for("detail_marche", id_marche=id_marche))


def _trouver_concurrents(marche: dict, limit: int = 5,
                          marches_notifies: dict | None = None) -> list:
    """Top concurrents historiques DECP sur la catégorie/CPV du marché."""
    if marches_notifies is None:
        try:
            marches_notifies = stockage.charger("marches_notifies")
        except Exception:
            return []
    notifies = marches_notifies
    if not notifies:
        return []
    cat = marche.get("categorie_metier")
    if not cat or cat == "autre":
        return []
    # Filtre par catégorie
    matchs = [m for m in notifies.values()
              if m.get("categorie_metier") == cat
              and m.get("titulaire_nom")]
    # Agrège par titulaire
    par_titulaire = {}
    for m in matchs:
        nom = m["titulaire_nom"]
        if nom not in par_titulaire:
            par_titulaire[nom] = {"nom": nom, "nb_marches": 0, "montant_total": 0}
        par_titulaire[nom]["nb_marches"] += 1
        montant = m.get("montant_total") or 0
        if isinstance(montant, (int, float)):
            par_titulaire[nom]["montant_total"] += montant
    # Top par nb de marchés
    tops = sorted(par_titulaire.values(),
                  key=lambda x: (-x["nb_marches"], -x["montant_total"]))
    return tops[:limit]


# ---------------------------------------------------------------------------
# Profils organisme — bibliothèque + activation + édition (Sprint P)
# ---------------------------------------------------------------------------

def _enum_options(code_preset: str) -> dict:
    """Extrait les listes `enum` des propriétés array d'un schéma sectoriel,
    pour générer des cases à cocher. {nom_propriete: [valeurs]}."""
    sch = organisme.schema_sectoriel(code_preset) or {}
    out = {}
    for prop, spec in (sch.get("properties") or {}).items():
        if spec.get("type") == "array":
            enum = (spec.get("items") or {}).get("enum")
            if enum:
                out[prop] = enum
    return out


@app.route("/profil")
def page_profil():
    """Liste des profils : actif + bibliothèque + exemples."""
    actif = organisme.charger_actif()
    return render_template(
        "profil/liste.html",
        organisme=actif,
        profil_actif=actif,
        actif_id=organisme.id_profil_actif(),
        bibliotheque=organisme.lister_profils_bibliotheque(),
        exemples=organisme.lister_profils_exemples(),
        preset_labels={m["code"]: m["etiquette_courte"] for m in organisme.meta_presets()},
    )


@app.route("/profil/<source>/<id>")
def profil_detail(source, id):
    """Détail lecture seule d'un profil (bibliothèque ou exemple)."""
    if source == "bibliotheque":
        profil = organisme.lire_profil_bibliotheque(id)
    elif source == "exemple":
        profil = organisme.lire_profil_exemple(id)
    else:
        abort(404)
    if profil is None:
        abort(404)
    return render_template(
        "profil/detail.html",
        organisme=organisme.charger_actif(),
        profil=profil,
        source=source,
        id=id,
        est_actif=(source == "bibliotheque" and id == organisme.id_profil_actif()),
        profil_json=json.dumps(profil, ensure_ascii=False, indent=2),
    )


@app.route("/profil/bibliotheque/<id>/edit", methods=["GET", "POST"])
def profil_edit(id):
    """Édition d'un profil de la bibliothèque."""
    profil = organisme.lire_profil_bibliotheque(id)
    if profil is None:
        abort(404)

    erreurs_champs = {}
    erreurs_validation = []

    if request.method == "POST":
        profil, erreurs_champs = profil_form.parse(request.form, profil)
        rapport = organisme.valider_profil(profil)
        erreurs_validation = rapport["erreurs"] if not rapport["valide"] else []
        if not erreurs_champs and not erreurs_validation:
            res = organisme.enregistrer_profil_bibliotheque(id, profil)
            if res["ok"]:
                flash(f"Profil « {profil.get('identite', {}).get('raison_sociale') or id} » enregistré.", "succes")
                return redirect(url_for("profil_detail", source="bibliotheque", id=id))
            erreurs_validation = res["erreurs"]

    return render_template(
        "profil/edit.html",
        organisme=organisme.charger_actif(),
        profil=profil,
        id=id,
        erreurs_champs=erreurs_champs,
        erreurs_validation=erreurs_validation,
        presets_connus=organisme.PRESETS_CONNUS,
        widgets=profil_widgets.contexte_widgets(profil),
        phases_etudes=profil_widgets.PHASES_ETUDES,
        statuts_reference=profil_widgets.STATUTS_REFERENCE,
        dr_formation=organisme.DR_FRANCE_TRAVAIL,
        prestations_formation=organisme.PRESTATIONS_FRANCE_TRAVAIL,
        est_legacy=organisme.est_format_legacy(profil),
    )


@app.route("/profil/nouveau", methods=["GET", "POST"])
def profil_nouveau():
    """
    Création d'un profil via l'assistant guidé (1 formulaire, étapes côté client).

    Le formulaire respecte la convention de nommage de `profil_form.parse`
    (`identite.*`, `zones_intervention`, `presets_couverts`, `sect.<code>.*`,
    `capacite_globale.*`, `mots_cles_catalogue`) : le POST est donc parsé par le
    même code que l'édition, et produit directement un profil complet.
    """
    erreurs = []
    profil = organisme.template_socle_vide()  # défauts pour le ré-affichage GET/erreur

    if request.method == "POST":
        presets = request.form.getlist("presets_couverts")
        profil = organisme.template_socle_vide()
        profil["presets_couverts"] = presets
        # un bloc sectoriel par preset coché ({} si schéma non défini : conseil/it)
        profil["profils_sectoriels"] = {
            code: (organisme.template_sectoriel_vide(code) or {})
            for code in presets
        }
        # Absorbe identité, zones, périmètre métier, capacité, mots-clés.
        profil, erreurs_champs = profil_form.parse(request.form, profil)
        # Seules les erreurs de format (nombre invalide) bloquent ici ; la
        # complétude sectorielle (corps_de_metier...) reste optionnelle à la
        # création — validation stricte assurée plus tard dans l'éditeur. La
        # création applique sa propre validation allégée (raison + ≥1 preset).
        erreurs += [f"{k} : {v}" for k, v in (erreurs_champs or {}).items()]

        if not erreurs:
            res = organisme.creer_profil_bibliotheque(profil)
            if res["ok"]:
                flash(f"Profil « {profil['identite'].get('raison_sociale') or res['id']} » créé.", "succes")
                return redirect(url_for("profil_detail", source="bibliotheque", id=res["id"]))
            erreurs += res["erreurs"]

    # Widgets des deux secteurs à schéma (BTP + ingénierie) : rendus dans
    # l'assistant et affichés/masqués par JS selon les secteurs cochés.
    widgets = profil_widgets.contexte_widgets({
        "presets_couverts": ["btp", "ingenierie"],
        "profils_sectoriels": profil.get("profils_sectoriels") or {},
        "zones_intervention": profil.get("zones_intervention") or [],
    })

    return render_template(
        "profil/nouveau.html",
        organisme=organisme.charger_actif(),
        presets_meta=organisme.meta_presets(),
        widgets=widgets,
        profil=profil,
        erreurs=erreurs,
    )


@app.route("/profil/<source>/<id>/activer", methods=["POST"])
def profil_activer(source, id):
    """Active un profil (exemple ou bibliothèque)."""
    res = organisme.activer_profil(id, source)
    if res["ok"]:
        flash(res["message"], "succes")
    else:
        flash(res["message"] + " " + " ; ".join(res.get("erreurs") or []), "erreur")
    return redirect(url_for("page_profil"))


@app.route("/profil/<source>/<id>/dupliquer", methods=["POST"])
def profil_dupliquer(source, id):
    """Duplique un profil vers la bibliothèque et ouvre son édition."""
    res = organisme.dupliquer_profil(id, source)
    if not res["ok"]:
        flash("Duplication impossible : " + " ; ".join(res.get("erreurs") or []), "erreur")
        return redirect(url_for("page_profil"))
    flash(f"Profil dupliqué : « {res['id_nouveau']} ». Vous pouvez l'éditer.", "succes")
    return redirect(url_for("profil_edit", id=res["id_nouveau"]))


@app.route("/profil/importer", methods=["GET", "POST"])
def profil_importer():
    """Importe un profil JSON (textarea ou fichier)."""
    erreurs = []
    contenu = ""
    if request.method == "POST":
        fichier = request.files.get("fichier")
        if fichier and fichier.filename:
            contenu = fichier.read().decode("utf-8", errors="replace")
        else:
            contenu = request.form.get("contenu_json") or ""
        res = organisme.importer_profil_json(contenu)
        if res["ok"]:
            flash(f"Profil importé : « {res['id']} ».", "succes")
            return redirect(url_for("profil_detail", source="bibliotheque", id=res["id"]))
        erreurs = res["erreurs"]
    return render_template(
        "profil/importer.html",
        organisme=organisme.charger_actif(),
        erreurs=erreurs,
        contenu=contenu,
    )


@app.route("/exigence/repondre", methods=["POST"])
def repondre_exigence():
    """Enregistre une réponse Oui/Non à une exigence dans le profil organisme.

    Une fois enregistrée, la réponse est appliquée automatiquement à toute
    fiche marché présentant la même `cle_canonique` (CA seuil identique,
    local dans la même ville, BAC+N identique, etc.).
    """
    from flask import request

    cle = (request.form.get("cle") or "").strip()
    reponse = (request.form.get("reponse") or "").strip().lower()
    redirect_to = request.form.get("redirect_to") or url_for("dashboard")

    if not cle or reponse not in ("oui", "non", "effacer"):
        abort(400, "cle ou reponse invalide")

    profil = organisme.lire_profil() or {}
    auto = dict(profil.get("auto_reponses_exigences") or {})

    if reponse == "effacer":
        auto.pop(cle, None)
    else:
        auto[cle] = reponse

    profil["auto_reponses_exigences"] = auto
    try:
        organisme.ecrire_profil(profil)
    except Exception as e:
        return f"Erreur écriture profil : {e}", 500

    return redirect(redirect_to)


@app.route("/concurrence")
def page_concurrence():
    """Page Veille concurrentielle : exploration DECP brut + base interne Tendia."""
    import veille_concurrence
    profil = organisme.lire_profil()
    try:
        marches_notifies = stockage.charger("marches_notifies")
    except Exception:
        marches_notifies = {}
    stats = veille_concurrence.agreger_tout(marches_notifies)
    return render_template(
        "concurrence.html",
        organisme=profil,
        stats=stats,
    )


@app.route("/veille")
def page_veille():
    """Alias rétrocompat → page concurrence."""
    return page_concurrence()


@app.errorhandler(404)
def page_404(e):
    return render_template("404.html",
                            organisme=organisme.lire_profil()), 404


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("  Tendia UI — Veille marchés publics France Travail")
    print("=" * 70)
    print()
    print(f"  Serveur démarré sur : http://localhost:5000")
    print(f"  Pour arrêter        : Ctrl+C")
    print()
    app.run(host="127.0.0.1", port=5000, debug=False)
