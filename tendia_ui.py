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
from datetime import date, datetime
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, url_for

import organisme
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

    # === Sprint 3 : filtrage par preset actif ===
    # Si la collection scores_matching a été calculée (analyse.py a tourné),
    # on ne garde que les marchés pertinents pour le preset actif.
    # Sinon (analyse jamais lancée), comportement legacy : tous les actifs.
    try:
        import preset as _preset
        preset_code_actif = _preset.code_actif()
    except Exception:
        preset_code_actif = None

    scores_par_preset = {}
    if preset_code_actif:
        try:
            scores_all = stockage.charger("scores_matching")
            for cle, entree in scores_all.items():
                if entree.get("preset_code") == preset_code_actif:
                    scores_par_preset[entree.get("marche_id")] = entree
        except Exception:
            scores_par_preset = {}

    # On filtre seulement si on a des scores pour ce preset (sinon mode legacy)
    if scores_par_preset:
        actifs = [m for m in actifs
                   if scores_par_preset.get(m["id"], {}).get("matche")]

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
        # Sprint 3 : indique si le filtre par preset est actif
        "filtre_preset_actif": bool(scores_par_preset),
        "preset_code_actif": preset_code_actif,
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


def _famille_pour_domaine(code: str) -> str:
    """Retourne la famille racine d'un code domaine."""
    if not code:
        return "Autre"
    prefix = code.split("_", 1)[0]
    return _FAMILLES_RACINE.get(prefix, "Autre")


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
            ]).lower()
            if filtre_recherche not in haystack:
                continue

        lignes.append({
            "marche": marche,
            "id_marche": id_m,
            "titre_court": _titre_court(marche),
            "acheteur": marche.get("acheteur_nom") or "—",
            "perimetre": marche.get("perimetre_geographique") or "",
            "date_limite_fmt": _fmt_date(marche.get("date_limite_depot")),
            "jours_restants": _jours_restants(marche.get("date_limite_depot")),
            "domaine_principal": code_principal,
            "domaine_libelle": (domaines_def.get(code_principal) or {}).get("libelle", code_principal),
            "famille": famille,
            "tous_domaines": valides,
            "raison": classif.get("raison_classification", "")[:200],
            "synthese": classif.get("synthese_courte") or classif.get("synthese_marche", "")[:200],
            "source_classification": source,
            "a_brief_complet": source == "brief_complet",
        })

    # Tri : par famille, puis par date_limite croissante (urgents en haut)
    lignes.sort(key=lambda x: (
        x["famille"],
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
        },
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

    # Calibration LLM (2e passe : brief + comparables DECP → estimation sourcée)
    # On charge TOUJOURS depuis le cache disque si présent (instantané, free).
    # On ne déclenche un nouvel appel LLM qu'avec DECP dispo (sinon, l'utilisateur
    # passera par `python calibrer_briefs.py` pour faire le bottom-up en batch).
    calibration = None
    if brief:
        try:
            import llm_calibration
            # Cache d'abord (bottom_up_seul OU triangulé)
            calibration = llm_calibration.charger_si_existe(id_marche)
            # Pas en cache ET DECP dispo → calibrer triangulé
            if calibration is None and zone_prix and zone_prix.get("top_comparables"):
                calibration = llm_calibration.calibrer_et_cacher(
                    id_marche, brief, zone_prix, marches_notifies,
                    verbose=False, mode="auto",
                )
        except Exception:
            calibration = None

    # Montant estimé du marché extrait par le brief LLM — B3/B11
    montant_marche_eur = _montant_marche_eur(brief)

    # Dossier local DCE
    dossier_dce = REPERTOIRE_DCE / id_marche
    pdfs_locaux = []
    if dossier_dce.is_dir():
        for nom in sorted(os.listdir(dossier_dce)):
            if nom.lower().endswith(".pdf"):
                pdfs_locaux.append(nom)

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

    return render_template(
        "marche.html",
        marche=marche,
        eval=evaluation,
        brief=brief,
        brief_type=brief_type,
        concurrents=concurrents,
        zone_prix=zone_prix,
        calibration=calibration,
        scenarios_montant=scenarios_montant,
        montant_marche_eur=montant_marche_eur,
        pdfs_locaux=pdfs_locaux,
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


@app.route("/profil")
def page_profil():
    """Page de gestion du profil organisme."""
    profil = organisme.lire_profil()

    # Diagnostic des sections remplies
    diagnostic = organisme.champs_remplis(profil) if profil else {}

    # Compteurs des sections-clés pour affichage
    stats = {}
    if profil:
        certifs = profil.get("certifications", {}) or {}
        stats = {
            "nb_dr": len(profil.get("directions_regionales_couvertes") or []),
            "nb_thematiques": len(profil.get("thematiques_metiers") or []),
            "nb_publics": len(profil.get("publics_cibles") or []),
            "nb_prestations": len(profil.get("prestations_maitrisees") or []),
            "nb_mots_cles": len(profil.get("mots_cles_catalogue") or []),
            "nb_modalites": len(profil.get("modalites_pedagogiques") or []),
            "nb_qualiopi": sum([
                bool(certifs.get("qualiopi_actions_formation")),
                bool(certifs.get("qualiopi_apprentissage")),
                bool(certifs.get("qualiopi_bilans")),
                bool(certifs.get("qualiopi_vae")),
            ]),
            "nb_references": len(profil.get("references_marches") or []),
        }

    # Compte de sections remplies (sur le total)
    n_remplis = sum(1 for v in diagnostic.values() if v)
    n_total = len(diagnostic) if diagnostic else 0

    return render_template(
        "profil.html",
        profil=profil,
        organisme=profil,  # alimente le sidebar
        diagnostic=diagnostic,
        n_remplis=n_remplis,
        n_total=n_total,
        stats=stats,
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
