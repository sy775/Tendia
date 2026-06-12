"""
tendia_extraire.py
------------------
Orchestrateur d'extraction LLM des DCE.

Workflow :
1. Scrute data/dce/<id_marche>/ pour les PDFs déposés par l'utilisateur
2. Pour chaque marché avec PDFs non encore traités (tracking via hash MD5) :
   a. Extrait le texte des PDFs (pypdf)
   b. Combine RC + CCTP + autres pièces
   c. Envoie à Claude API avec prompt structuré
   d. Stocke data/extractions/<id>.json
   e. Génère brief markdown rapports/brief_<id>.md
3. Met à jour data/extractions/_etat.json (tracking)

Usage :
    python tendia_extraire.py                  # tous les marchés avec PDFs
    python tendia_extraire.py --marche <id>    # un marché spécifique
    python tendia_extraire.py --force          # re-extraire même si déjà fait
    python tendia_extraire.py --dry-run        # n'appelle pas l'API, juste scan
"""

import argparse
import json
import os
import sys
import zipfile
from datetime import datetime, timezone

import stockage
import pdf_extract
import llm_extract


REPERTOIRE_BASE = os.path.dirname(os.path.abspath(__file__))
REPERTOIRE_DCE = os.path.join(REPERTOIRE_BASE, "data", "dce")
REPERTOIRE_EXTRACTIONS = os.path.join(REPERTOIRE_BASE, "data", "extractions")
REPERTOIRE_RAPPORTS = os.path.join(REPERTOIRE_BASE, "rapports")
FICHIER_ETAT = os.path.join(REPERTOIRE_EXTRACTIONS, "_etat.json")

COLLECTION_MARCHES = "marches"


# ---------------------------------------------------------------------------
# Détection des PDFs non-DCE (guides, dume, etc.)
# ---------------------------------------------------------------------------
#
# Beaucoup de plateformes (marches-publics.info, PLACE) distribuent en accès
# libre uniquement un guide de dépôt ou le DUME. Le vrai DCE (RC, CCTP, BPU)
# est derrière login. Inutile de payer un appel LLM pour ces docs vides
# de contenu métier.

# Patterns dans le nom du fichier qui désignent EXPLICITEMENT un doc non-DCE
PATTERNS_PDF_NON_DCE = (
    "depot-pli", "depot_pli", "depotpli",
    "guide-depot", "guide_depot", "guide-de-depot",
    "aide-en-ligne", "aide-depot",
    "notice-depot", "notice_depot",
    "tuto-depot", "tutoriel-depot",
    "dume-acheteur", "dume_acheteur",
)

# Mots-clés indiquant un vrai document métier (DCE) dans le nom du fichier
PATTERNS_PDF_DCE_VALIDE = (
    "rc", "ccap", "cctp", "ccp", "bpu", "aapc",
    "cahier", "consultation", "regl", "clauses",
    "dpgf", "cce", "bordereau", "annexe", "ccag",
    "lot", "tranche",
)


def _est_pdf_non_dce(nom_fichier: str, taille_chars: int) -> tuple:
    """
    Détecte si un PDF est probablement un guide/doc administratif et non
    le vrai DCE.

    Returns: (est_non_dce: bool, raison: str)
    """
    nom = nom_fichier.lower()
    # 1. Nom explicite de guide/dume
    for pat in PATTERNS_PDF_NON_DCE:
        if pat in nom:
            return True, f"nom contient '{pat}'"
    # 2. Très petit fichier (PDF corrompu, OCR raté, scan illisible)
    if taille_chars < 1000:
        return True, f"taille trop petite ({taille_chars} chars)"
    # 3. Petit fichier sans nom métier reconnu
    if taille_chars < 10000:
        if not any(pat in nom for pat in PATTERNS_PDF_DCE_VALIDE):
            return True, (f"taille petite ({taille_chars} chars) "
                          f"+ nom non métier")
    return False, ""


# ---------------------------------------------------------------------------
# Auto-décompression des zips déposés par l'utilisateur
# ---------------------------------------------------------------------------

def _dezipper_dossier(dossier: str, verbose: bool = True) -> int:
    """
    Si un .zip est présent dans le dossier, l'extrait à plat à côté
    (sans créer de sous-dossier). Déplace le zip dans un sous-dossier
    _zip_archives/ après extraction pour ne pas le re-traiter.

    Returns:
        Nombre de zips traités.
    """
    if not os.path.isdir(dossier):
        return 0
    archives_dir = os.path.join(dossier, "_zip_archives")
    n_traites = 0
    for nom in os.listdir(dossier):
        if not nom.lower().endswith(".zip"):
            continue
        chemin_zip = os.path.join(dossier, nom)
        try:
            with zipfile.ZipFile(chemin_zip, "r") as z:
                noms_internes = z.namelist()
                # Filtre les fichiers utiles (PDFs pertinents)
                # On extrait TOUT, mais on filtre lors du scan PDF ensuite
                for nom_interne in noms_internes:
                    # Ignore les sous-dossiers vides et les fichiers cachés
                    if nom_interne.endswith("/") or nom_interne.startswith("."):
                        continue
                    # Extrait à plat (basename seulement)
                    base = os.path.basename(nom_interne)
                    if not base:
                        continue
                    chemin_cible = os.path.join(dossier, base)
                    if os.path.exists(chemin_cible):
                        if verbose:
                            print(f"    déjà présent : {base}")
                        continue
                    with z.open(nom_interne) as src, \
                            open(chemin_cible, "wb") as dst:
                        dst.write(src.read())
                    if verbose:
                        print(f"    extrait : {base}")
            # Déplace le zip dans _zip_archives pour ne pas le re-traiter
            os.makedirs(archives_dir, exist_ok=True)
            os.rename(chemin_zip,
                      os.path.join(archives_dir, nom))
            n_traites += 1
            if verbose:
                print(f"    📦 zip déplacé : {nom} → _zip_archives/")
        except Exception as e:
            if verbose:
                print(f"    ⚠ Erreur dézip {nom} : {e}")
    return n_traites


# ---------------------------------------------------------------------------
# Tracking des extractions précédentes
# ---------------------------------------------------------------------------

def _charger_etat() -> dict:
    if not os.path.isfile(FICHIER_ETAT):
        return {}
    try:
        with open(FICHIER_ETAT, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _sauver_etat(etat: dict):
    os.makedirs(REPERTOIRE_EXTRACTIONS, exist_ok=True)
    with open(FICHIER_ETAT, "w", encoding="utf-8") as f:
        json.dump(etat, f, ensure_ascii=False, indent=2)


def _signature_pdfs(pdfs: dict) -> str:
    """Signature unique pour un ensemble de PDFs (concat des hashs triés)."""
    hashs = sorted(info["hash"] for info in pdfs.values())
    return "_".join(hashs)


# ---------------------------------------------------------------------------
# Identification des marchés à traiter
# ---------------------------------------------------------------------------

def _scanner_dossiers_dce(force: bool = False,
                            verbose: bool = True) -> list:
    """
    Retourne la liste des marchés ayant des PDFs à traiter.

    Pour chaque dossier marché :
    1. Détecte et décompresse les .zip présents (workflow PLACE)
    2. Liste les PDFs
    3. Compare la signature MD5 avec l'état précédent

    Returns:
        [(id_marche, dossier, pdfs_dict, raison), ...]
    """
    if not os.path.isdir(REPERTOIRE_DCE):
        return []

    etat = _charger_etat()
    a_traiter = []

    for nom_dossier in sorted(os.listdir(REPERTOIRE_DCE)):
        dossier = os.path.join(REPERTOIRE_DCE, nom_dossier)
        if not os.path.isdir(dossier):
            continue

        # Auto-décompression des zips déposés (workflow PLACE)
        n_zips = _dezipper_dossier(dossier, verbose=verbose)
        if n_zips and verbose:
            print(f"  📦 {nom_dossier} : {n_zips} zip(s) décompressé(s)")

        pdfs = pdf_extract.extraire_dossier(dossier, verbose=False)
        if not pdfs:
            continue
        signature = _signature_pdfs(pdfs)
        etat_marche = etat.get(nom_dossier, {})
        if etat_marche.get("signature_pdfs") == signature and not force:
            continue
        raison = ("re-traitement forcé" if force
                   else ("nouvelle extraction" if not etat_marche
                          else "nouveaux PDFs détectés"))
        a_traiter.append((nom_dossier, dossier, pdfs, raison))

    return a_traiter


# ---------------------------------------------------------------------------
# Traitement d'un marché
# ---------------------------------------------------------------------------

def _construire_contexte(marche: dict) -> dict:
    """Réduit le marché à un contexte utile pour le LLM."""
    return {
        "id": marche.get("id"),
        "source": marche.get("source"),
        "reference_externe": marche.get("reference_externe"),
        "reference_ft_interne": marche.get("reference_ft"),
        "titre": marche.get("titre"),
        "objet": marche.get("objet"),
        "acheteur": marche.get("acheteur_nom"),
        "date_publication": marche.get("date_publication"),
        "date_limite_depot": marche.get("date_limite_depot"),
        "categorie_metier": marche.get("categorie_metier"),
        "cpv_principal": marche.get("cpv_principal"),
    }


def _combiner_textes(pdfs: dict) -> str:
    """Combine les textes des différents PDFs en un seul corpus."""
    blocs = []
    for nom, info in pdfs.items():
        blocs.append(f"\n\n=== PIÈCE : {nom} ===\n\n{info['texte']}")
    return "".join(blocs)


def traiter_marche(id_marche: str, dossier: str, pdfs: dict,
                     dry_run: bool = False,
                     verbose: bool = True) -> dict:
    """
    Traite un marché : extraction texte → LLM → stockage.

    Returns:
        {"ok": bool, "extraction": dict | None, "erreur": str | None,
         "raison": str | None}
        Le champ 'raison' permet de distinguer les cas :
        - "pdfs_non_dce" : que des guides / DUME, pas le vrai DCE
        - "extraction_llm" : appel LLM échoué
        - None : pas d'erreur
    """
    if verbose:
        print(f"\n  [Marché {id_marche}]")
        print(f"    Dossier : {dossier}")
        print(f"    PDFs    : {list(pdfs.keys())} "
              f"({sum(p['taille_chars'] for p in pdfs.values())} chars total)")

    # === Sprint 3 : filtre PDFs non-DCE (guides, dume, etc.) ===
    pdfs_valides = {}
    pdfs_rejetes = []
    for nom, p in pdfs.items():
        est_non_dce, raison_rejet = _est_pdf_non_dce(nom, p.get("taille_chars", 0))
        if est_non_dce:
            pdfs_rejetes.append((nom, raison_rejet))
        else:
            pdfs_valides[nom] = p

    if pdfs_rejetes and verbose:
        print(f"    ⊘ {len(pdfs_rejetes)} PDF(s) rejeté(s) (non-DCE) :")
        for nom, raison_rejet in pdfs_rejetes:
            print(f"        - {nom} : {raison_rejet}")

    if not pdfs_valides:
        if verbose:
            print(f"    ⊘ Aucun PDF DCE exploitable. Téléchargement manuel "
                  f"du vrai DCE (RC+CCTP) requis.")
        return {"ok": False, "extraction": None,
                "erreur": "Aucun PDF DCE exploitable",
                "raison": "pdfs_non_dce"}

    # Charger le marché en base pour le contexte
    marches = stockage.charger(COLLECTION_MARCHES)
    marche = marches.get(id_marche)
    if not marche:
        if verbose:
            print(f"    ⚠ Marché absent de la base, on continue avec contexte minimal")
        marche = {"id": id_marche}

    contexte = _construire_contexte(marche)
    texte_combine = _combiner_textes(pdfs_valides)

    if dry_run:
        if verbose:
            print(f"    [DRY-RUN] Pas d'appel API. Texte préparé : "
                  f"{len(texte_combine)} chars")
        return {"ok": True, "extraction": None, "erreur": None,
                "dry_run": True}

    # Appel LLM
    extraction = llm_extract.extraire_via_llm(
        texte_combine, contexte, verbose=verbose
    )
    if not extraction:
        if verbose:
            print(f"    ❌ Extraction LLM échouée.")
        return {"ok": False, "extraction": None,
                "erreur": "extraction LLM échouée",
                "raison": "extraction_llm"}

    # Récupère les méta d'appel LLM injectées par extraire_via_llm (Sprint 3)
    appel_meta = extraction.pop("_appel_llm", None) or {}

    # Enrichir avec méta
    extraction["_meta"] = {
        "id_marche": id_marche,
        "type": "complet",
        "extraction_le": datetime.now(timezone.utc).isoformat(),
        "modele": appel_meta.get("modele") or llm_extract.MODELE,
        "tokens_input": appel_meta.get("tokens_input"),
        "tokens_output": appel_meta.get("tokens_output"),
        "cout_eur": appel_meta.get("cout_eur"),
        "duree_sec": appel_meta.get("duree_sec"),
        "pdfs_traites": [
            {"nom": n, "hash": p["hash"], "taille_chars": p["taille_chars"]}
            for n, p in pdfs.items()
        ],
    }

    # Stocker en JSON (disque, compat historique Apptia)
    os.makedirs(REPERTOIRE_EXTRACTIONS, exist_ok=True)
    chemin_json = os.path.join(REPERTOIRE_EXTRACTIONS, f"{id_marche}.json")
    with open(chemin_json, "w", encoding="utf-8") as f:
        json.dump(extraction, f, ensure_ascii=False, indent=2)
    if verbose:
        print(f"    💾 JSON : {chemin_json}")

    # Stocker aussi en SQLite collection 'briefs_extraits' (Sprint 3).
    # Ceci REMPLACE un éventuel brief LIGHT précédent (même clé = id_marche),
    # ce qui fait que l'UI Tendia affichera désormais le brief COMPLET.
    try:
        stockage.ecrire("briefs_extraits", id_marche, extraction)
        if verbose:
            print(f"    🗄  Indexé en base SQLite (briefs_extraits)")
    except Exception as e:
        if verbose:
            print(f"    ⚠  Échec écriture SQLite : {e}")

    # Sync classif IA en base depuis la sortie LLM (Sprint 2bis - Sujet 1).
    # Le LLM peut re-classifier le marché lors du brief complet (plus de
    # contexte qu'au moment du backfill). On met à jour `classifications_ia`
    # pour que le prochain rebrief utilise la bonne classif côté routage.
    try:
        domaines_llm = extraction.get("domaines_metier") or []
        if domaines_llm:
            classif = stockage.lire("classifications_ia", id_marche) or {}
            ancienne_codes = [d.get("code") for d in (classif.get("domaines_metier") or [])
                              if isinstance(d, dict)]
            nouvelle_codes = [d.get("code") for d in domaines_llm if isinstance(d, dict)]
            if ancienne_codes != nouvelle_codes:
                classif["domaines_metier"] = domaines_llm
                if extraction.get("raison_classification"):
                    classif["raison_classification"] = extraction["raison_classification"]
                classif["source"] = "brief_complet"
                classif["mis_a_jour_le"] = datetime.now(timezone.utc).isoformat()
                stockage.ecrire("classifications_ia", id_marche, classif)
                if verbose:
                    print(f"    🔄 Classif IA mise à jour : "
                          f"{ancienne_codes} → {nouvelle_codes}")
    except Exception as e:
        if verbose:
            print(f"    ⚠  Échec sync classif IA : {e}")

    # Générer brief markdown
    brief = _generer_brief(marche, extraction)
    os.makedirs(REPERTOIRE_RAPPORTS, exist_ok=True)
    chemin_brief = os.path.join(REPERTOIRE_RAPPORTS, f"brief_{id_marche}.md")
    with open(chemin_brief, "w", encoding="utf-8") as f:
        f.write(brief)
    if verbose:
        print(f"    📄 Brief : {chemin_brief}")

    return {"ok": True, "extraction": extraction, "erreur": None}


# ---------------------------------------------------------------------------
# Génération du brief markdown
# ---------------------------------------------------------------------------

def _fmt_val(v, suffixe=""):
    if v is None or v == "":
        return "—"
    return f"{v}{suffixe}"


def _item_label(item) -> str:
    """
    Représente proprement un élément de liste qui peut être :
    - une string : retournée telle quelle
    - un dict {"nom": ..., "type": ...} ou {"libelle": ...}
      -> retourne le champ le plus pertinent + détails entre parenthèses
    - autre : str(item)
    """
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        # Cherche le label principal
        for k in ("nom", "libelle", "label", "intitule", "name", "title"):
            if item.get(k):
                label = str(item[k]).strip()
                # Ajoute les autres champs en complément
                details = []
                for k2, v2 in item.items():
                    if k2 == k or not v2:
                        continue
                    if isinstance(v2, (str, int, float)):
                        details.append(f"{k2}={v2}")
                if details:
                    return f"{label} ({', '.join(details)})"
                return label
        # Pas de label trouvé, sérialise les valeurs
        return ", ".join(f"{k}={v}" for k, v in item.items() if v)
    return str(item)


def _join_safe(items, sep: str = ", ") -> str:
    """Joint une liste d'éléments (strings OU dicts) en string lisible."""
    if not items:
        return ""
    return sep.join(_item_label(i) for i in items)


def _fmt_montant_euros(v) -> str:
    """Formate un montant en euros : 86100 → '86 100 €'."""
    if v is None or v == "":
        return "—"
    try:
        n = float(v)
        if n >= 1_000_000:
            return f"{n/1_000_000:.2f} M€".replace(".", ",")
        return f"{int(n):,} €".replace(",", " ")
    except (TypeError, ValueError):
        return str(v)


# ---------------------------------------------------------------------------
# Helpers de rendu sectoriel (Phase 3a - preset-aware MD)
# ---------------------------------------------------------------------------
#
# Idée : chaque bloc sectoriel (BTP, ENR, MOE, conseil, IT, formation) a sa
# fonction _section_*() qui détecte si le bloc est rempli, et si oui rend
# une section MD avec labels métier appropriés. Les sections vides sont
# silencieusement skippées — fini les "## Publics cibles : Non applicable"
# pour un brief BTP.


def _bloc_non_vide(d) -> bool:
    """True si le dict/list contient au moins une valeur non-null/non-vide."""
    if d is None:
        return False
    if isinstance(d, dict):
        for v in d.values():
            if v is None:
                continue
            if isinstance(v, (list, dict)) and not v:
                continue
            if isinstance(v, str) and not v.strip():
                continue
            return True
        return False
    if isinstance(d, list):
        return bool(d)
    return True


def _fmt_bool(v) -> str:
    if v is True:
        return "oui"
    if v is False:
        return "non"
    return "—"


def _kv_ligne(label: str, valeur, prefixe: str = "- "):
    """Ligne MD '- **Label** : valeur' si valeur non-vide, None sinon."""
    if valeur is None:
        return None
    if isinstance(valeur, str) and not valeur.strip():
        return None
    if isinstance(valeur, (list, dict)) and not valeur:
        return None
    if isinstance(valeur, list):
        return f"{prefixe}**{label}** : {_join_safe(valeur)}"
    if isinstance(valeur, bool):
        return f"{prefixe}**{label}** : {_fmt_bool(valeur)}"
    return f"{prefixe}**{label}** : {valeur}"


def _liste_kv(d: dict, mapping: list) -> list:
    """Génère lignes MD à partir d'un dict + mapping [(cle, label), ...]."""
    out = []
    for cle, label in mapping:
        l = _kv_ligne(label, d.get(cle))
        if l:
            out.append(l)
    return out


def _detecter_schema_chantier(ctc: dict) -> str:
    """
    Le champ `caracteristiques_techniques_chantier` peut suivre le schéma
    BTP (typologie_ouvrage, corps_etat) ou ENR (technologies_concernees,
    type_de_sites). Retourne 'btp', 'enr' ou 'inconnu'.

    Avec le routage par classif IA (Sprint 2bis), il n'y a plus de collision :
    le brief ne reçoit que le schéma de SON preset. Mais on garde la détection
    pour les briefs antérieurs au routage qui ont les deux mélangés.
    """
    if not isinstance(ctc, dict):
        return "inconnu"
    cles = set(ctc.keys())
    if cles & {"typologie_ouvrage", "corps_etat", "site_occupe"}:
        return "btp"
    if cles & {"technologies_concernees", "type_de_sites",
               "contraintes_site_signalees"}:
        return "enr"
    return "inconnu"


# ----- Sections sectorielles --------------------------------------------------

def _section_chantier_btp(extraction: dict) -> list:
    """Section BTP : chantier + qualifications + allotissement."""
    ctc = extraction.get("caracteristiques_techniques_chantier") or {}
    alot = extraction.get("allotissement") or {}
    qual = extraction.get("qualifications_requises") or {}

    schema = _detecter_schema_chantier(ctc) if _bloc_non_vide(ctc) else "absent"
    ctc_btp = (schema == "btp")

    if not (ctc_btp or _bloc_non_vide(alot) or _bloc_non_vide(qual)):
        return []

    lignes = ["## 🏗 Chantier — caractéristiques BTP"]

    if ctc_btp:
        lignes.extend(_liste_kv(ctc, [
            ("description", "Description"),
            ("typologie_ouvrage", "Type d'ouvrage"),
            ("surface_volume", "Surface / volume"),
            ("site_occupe", "Site occupé pendant travaux"),
        ]))
        ce = ctc.get("corps_etat") or []
        if ce:
            lignes.append(f"- **Corps d'état mobilisés** : {_join_safe(ce)}")
        cs = ctc.get("contraintes_specifiques") or []
        if cs:
            lignes.append("- **Contraintes spécifiques** :")
            for c in cs:
                lignes.append(f"  - {_item_label(c)}")
        lignes.append("")

    if _bloc_non_vide(alot):
        lignes.append("### Allotissement")
        if alot.get("description"):
            lignes.append(f"{alot['description']}")
        nb = alot.get("nb_lots")
        if nb is not None:
            lignes.append(f"- **Nombre de lots** : {nb}")
        for lot in (alot.get("lots_detailles") or []):
            num = lot.get("numero", "?")
            intit = lot.get("intitule", "?")
            lignes.append(f"- **Lot {num}** — {intit}")
            if lot.get("corps_etat"):
                lignes.append(f"  - Corps d'état : {lot['corps_etat']}")
            if lot.get("montant_estime") is not None:
                lignes.append(f"  - Montant estimé : "
                              f"{_fmt_montant_euros(lot['montant_estime'])}")
            if lot.get("description"):
                lignes.append(f"  - {lot['description']}")
        lignes.append("")

    if _bloc_non_vide(qual):
        lignes.append("### Qualifications BTP exigées")
        if qual.get("description"):
            lignes.append(f"{qual['description']}")
        qb = qual.get("qualibat") or []
        if qb:
            lignes.append(f"- **Qualibat** : {_join_safe(qb)}")
        rge = qual.get("rge")
        if rge:  # ignore False/None/[]
            lignes.append(f"- **RGE** : "
                          f"{_join_safe(rge) if isinstance(rge, list) else rge}")
        for cle, label in [("opqibi", "OPQIBI"),
                           ("mase", "MASE"),
                           ("amiante_ss3_ss4", "Amiante SS3/SS4"),
                           ("seuils_financiers", "Seuils financiers")]:
            l = _kv_ligne(label, qual.get(cle))
            if l:
                lignes.append(l)
        # Champ tantôt `autres`, tantôt `autres_certifications` selon époque
        autres = (qual.get("autres") or qual.get("autres_certifications")
                  or qual.get("autres_exigences") or [])
        if autres:
            lignes.append("- **Autres exigences** :")
            for a in autres:
                lignes.append(f"  - {_item_label(a)}")
        lignes.append("")

    return lignes


def _section_chantier_enr(extraction: dict) -> list:
    """Section EnR : caracs techniques + volumes techniques + modalités."""
    ctc = extraction.get("caracteristiques_techniques_chantier") or {}
    vt = extraction.get("volumes_techniques") or {}
    me = extraction.get("modalites_execution_chantier") or {}

    schema = _detecter_schema_chantier(ctc) if _bloc_non_vide(ctc) else "absent"
    ctc_enr = (schema == "enr")

    if not (ctc_enr or _bloc_non_vide(vt) or _bloc_non_vide(me)):
        return []

    lignes = ["## ⚡ Parc EnR — caractéristiques techniques"]

    if ctc_enr:
        if ctc.get("description"):
            lignes.append(f"- **Description** : {ctc['description']}")
        for cle, lab in [("technologies_concernees", "Technologies concernées"),
                         ("type_de_sites", "Type de sites"),
                         ("criteres_eligibilite", "Critères d'éligibilité"),
                         ("contraintes_site_signalees", "Contraintes site signalées")]:
            v = ctc.get(cle)
            if not v:
                continue
            if isinstance(v, list):
                lignes.append(f"- **{lab}** :")
                for it in v:
                    lignes.append(f"  - {_item_label(it)}")
            else:
                lignes.append(f"- **{lab}** : {v}")
        lignes.append("")

    if _bloc_non_vide(vt):
        lignes.append("### Volumes techniques")
        lignes.extend(_liste_kv(vt, [
            ("puissance_totale_kwc", "Puissance totale (kWc)"),
            ("productible_annuel_estime_mwh", "Productible annuel estimé (MWh)"),
            ("nb_sites", "Nombre de sites"),
            ("duree_marche_mois", "Durée du marché (mois)"),
            ("duree_maintenance_om_annees", "Durée maintenance O&M (années)"),
            ("commentaire_volumes", "Note"),
        ]))
        lignes.append("")

    if _bloc_non_vide(me):
        lignes.append("### Modalités d'exécution")
        sites = me.get("sites_execution") or []
        if sites:
            lignes.append(f"- **Sites d'exécution** : {_join_safe(sites)}")
        lignes.extend(_liste_kv(me, [
            ("raccordement_reseau_inclus", "Raccordement réseau inclus"),
            ("etudes_techniques_incluses", "Études techniques incluses"),
            ("engagement_productible", "Engagement productible"),
        ]))
        lignes.append("")

    return lignes


def _section_moe(extraction: dict) -> list:
    """Section ingénierie / MOE."""
    cm = extraction.get("caracteristiques_mission_moe") or {}
    qm = extraction.get("qualifications_moe") or {}
    if not (_bloc_non_vide(cm) or _bloc_non_vide(qm)):
        return []

    lignes = ["## 🧮 Mission MOE / ingénierie"]

    if _bloc_non_vide(cm):
        lignes.extend(_liste_kv(cm, [
            ("typologie", "Typologie de mission"),
            ("typologie_ouvrage", "Type d'ouvrage"),
            ("complexite_technique", "Complexité technique"),
            ("taux_remuneration_moe_pct", "Taux rémunération MOE"),
            ("bim_niveau", "BIM niveau attendu"),
        ]))
        phases = cm.get("phases_couvertes") or []
        if phases:
            lignes.append(f"- **Phases couvertes** : {_join_safe(phases)}")
        mt = cm.get("montant_travaux_estime")
        if mt is not None:
            lignes.append(f"- **Montant travaux estimé** : "
                          f"{_fmt_montant_euros(mt)}")
        # Livrables par phase (nouveau)
        lpp = cm.get("livrables_par_phase") or []
        if lpp:
            lignes.append("- **Livrables par phase** :")
            for ph in lpp:
                if isinstance(ph, dict):
                    nom = ph.get("phase", "?")
                    livs = ph.get("livrables") or []
                    lignes.append(f"  - **{nom}** :")
                    for l in livs:
                        lignes.append(f"    - {_item_label(l)}")
        # Indices de révision (nouveau)
        ind = cm.get("indices_revision") or []
        if ind:
            lignes.append(f"- **Indices révision** : {_join_safe(ind)}")
        # Coordinations associées (nouveau)
        coord = cm.get("coordinations_associees") or []
        if coord:
            lignes.append("- **Coordinations associées** :")
            for c in coord:
                lignes.append(f"  - {_item_label(c)}")
        # Organigramme attendu (nouveau)
        org = cm.get("organigramme_attendu") or []
        if org:
            lignes.append("- **Organigramme attendu** :")
            for p in org:
                if isinstance(p, dict):
                    profil = p.get("profil", "?")
                    nb = p.get("nombre")
                    anc = p.get("anciennete_min_annees")
                    bits = [profil]
                    if nb is not None:
                        bits.append(f"×{nb}")
                    if anc is not None:
                        bits.append(f"≥{anc} ans")
                    lignes.append(f"  - {' '.join(bits)}")
                else:
                    lignes.append(f"  - {p}")
        lignes.append("")

    if _bloc_non_vide(qm):
        lignes.append("### Qualifications MOE exigées")
        for cle, lab in [("opqibi", "OPQIBI"), ("opqcm", "OPQCM"),
                         ("bim", "BIM")]:
            v = qm.get(cle)
            if v:
                if isinstance(v, bool):
                    lignes.append(f"- **{lab}** : exigé")
                elif isinstance(v, list):
                    lignes.append(f"- **{lab}** : {_join_safe(v)}")
                else:
                    lignes.append(f"- **{lab}** : {v}")
        autres = qm.get("autres") or []
        if autres:
            lignes.append("- **Autres exigences** :")
            for a in autres:
                lignes.append(f"  - {_item_label(a)}")
        lignes.append("")

    return lignes


def _section_conseil(extraction: dict) -> list:
    """Section conseil : mission + profils intervenants."""
    cm = extraction.get("caracteristiques_mission") or {}
    pi = extraction.get("profils_intervenants") or {}
    if not (_bloc_non_vide(cm) or _bloc_non_vide(pi)):
        return []

    lignes = ["## 🎯 Mission conseil"]

    if _bloc_non_vide(cm):
        lignes.extend(_liste_kv(cm, [
            ("typologie_mission", "Typologie de mission"),
            ("domaine_expertise", "Domaine d'expertise"),
            ("duree_mission", "Durée de mission"),
            ("jours_consultant_estimes", "Jours-consultant estimés"),
            ("methodologie_attendue", "Méthodologie attendue"),
            ("accompagnement_apres", "Accompagnement post-livraison"),
        ]))
        liv = cm.get("livrables_attendus") or []
        if liv:
            lignes.append("- **Livrables attendus** :")
            for l in liv:
                lignes.append(f"  - {_item_label(l)}")
        # Livrables par phase (nouveau)
        liv_phases = cm.get("livrables_par_phase") or []
        if liv_phases:
            lignes.append("- **Livrables par phase** :")
            for phase in liv_phases:
                if isinstance(phase, dict):
                    nom = phase.get("phase", "?")
                    livs = phase.get("livrables") or []
                    lignes.append(f"  - **{nom}** :")
                    for l in livs:
                        lignes.append(f"    - {_item_label(l)}")
        # Jours-consultant par profil (nouveau)
        jcp = cm.get("jours_consultant_par_profil") or []
        if jcp:
            lignes.append("- **Jours-consultant par profil** :")
            for p in jcp:
                if isinstance(p, dict):
                    profil = p.get("profil", "?")
                    j_min = p.get("nb_jours_min")
                    j_max = p.get("nb_jours_max")
                    if j_min is not None or j_max is not None:
                        rng = f"{j_min or '?'}–{j_max or '?'} j"
                        lignes.append(f"  - {profil} : {rng}")
                    else:
                        lignes.append(f"  - {profil}")
        lignes.append("")

    if _bloc_non_vide(pi):
        lignes.append("### Profils intervenants")
        if pi.get("description"):
            lignes.append(f"{pi['description']}")
        # chef_de_mission : peut être string (legacy) ou dict (nouveau format)
        cdm = pi.get("chef_de_mission")
        if isinstance(cdm, dict) and _bloc_non_vide(cdm):
            lignes.append("- **Chef de mission** :")
            bits = []
            if cdm.get("anciennete_min_annees") is not None:
                bits.append(f"≥ {cdm['anciennete_min_annees']} ans d'expérience")
            if cdm.get("secteur_experience"):
                bits.append(f"secteur : {cdm['secteur_experience']}")
            if cdm.get("taux_dedie_pct") is not None:
                bits.append(f"dédié à {cdm['taux_dedie_pct']}%")
            for b in bits:
                lignes.append(f"  - {b}")
            certs = cdm.get("certifs_requises") or []
            if certs:
                lignes.append(f"  - certifications : {_join_safe(certs)}")
        elif isinstance(cdm, str) and cdm.strip():
            lignes.append(f"- **Chef de mission** : {cdm}")
        # consultants : peut être string (legacy) ou array (nouveau format)
        cons = pi.get("consultants")
        if isinstance(cons, list) and cons:
            lignes.append("- **Consultants** :")
            for c in cons:
                if isinstance(c, dict):
                    profil = c.get("profil", "?")
                    nb = c.get("nombre")
                    anc = c.get("anciennete_min_annees")
                    bits = [profil]
                    if nb is not None:
                        bits.append(f"×{nb}")
                    if anc is not None:
                        bits.append(f"≥{anc} ans")
                    lignes.append(f"  - {' '.join(bits)}")
                else:
                    lignes.append(f"  - {c}")
        elif isinstance(cons, str) and cons.strip():
            lignes.append(f"- **Consultants** : {cons}")
        lignes.append("")

    return lignes


def _section_si(extraction: dict) -> list:
    """Section IT / SI."""
    cs = extraction.get("caracteristiques_si") or {}
    qs = extraction.get("qualifications_si") or {}
    if not (_bloc_non_vide(cs) or _bloc_non_vide(qs)):
        return []

    lignes = ["## 💻 Système d'information / IT"]

    if _bloc_non_vide(cs):
        lignes.extend(_liste_kv(cs, [
            ("description", "Description"),
            ("typologie_projet", "Typologie de projet"),
            ("architecture", "Architecture cible"),
            ("volumetrie", "Volumétrie"),
            ("hebergement", "Hébergement"),
            ("methodologie", "Méthodologie attendue"),
            ("sla_disponibilite_pct", "SLA disponibilité"),
            ("rto_rpo", "RTO / RPO"),
            ("reversibilite", "Réversibilité"),
            ("support_garantie", "Support / garantie"),
        ]))
        tech = cs.get("technologies_mentionnees") or []
        if tech:
            lignes.append(f"- **Technologies mentionnées** : {_join_safe(tech)}")
        integ = cs.get("integrations") or []
        if integ:
            lignes.append("- **Intégrations SI amont/aval** :")
            for i in integ:
                lignes.append(f"  - {_item_label(i)}")
        # Profil équipe attendu : array d'objets
        equipe = cs.get("profil_equipe_attendu") or []
        if equipe:
            lignes.append("- **Profil équipe attendu** :")
            for p in equipe:
                if isinstance(p, dict):
                    profil = p.get("profil", "?")
                    nb = p.get("nombre_min")
                    anc = p.get("anciennete_min_annees")
                    bits = [profil]
                    if nb is not None:
                        bits.append(f"×{nb}")
                    if anc is not None:
                        bits.append(f"≥{anc} ans")
                    lignes.append(f"  - {' '.join(bits)}")
                else:
                    lignes.append(f"  - {p}")
        lignes.append("")

    if _bloc_non_vide(qs):
        lignes.append("### Qualifications SI exigées")
        for cle, lab in [("iso_27001", "ISO 27001"),
                         ("anssi", "ANSSI"),
                         ("hds", "HDS (Données de santé)")]:
            v = qs.get(cle)
            if v:
                if isinstance(v, bool):
                    lignes.append(f"- **{lab}** : exigé")
                elif isinstance(v, list):
                    lignes.append(f"- **{lab}** : {_join_safe(v)}")
                else:
                    lignes.append(f"- **{lab}** : {v}")
        autres = qs.get("autres") or []
        if autres:
            lignes.append("- **Autres exigences** :")
            for a in autres:
                lignes.append(f"  - {_item_label(a)}")
        lignes.append("")

    return lignes


def _section_formation(extraction: dict) -> list:
    """Section formation : publics cibles + volumes + modalités."""
    pc = extraction.get("publics_cibles") or {}
    vol = extraction.get("volumes") or {}
    mod = extraction.get("modalites") or {}
    if not (_bloc_non_vide(pc) or _bloc_non_vide(vol) or _bloc_non_vide(mod)):
        return []

    lignes = ["## 🎓 Formation / accompagnement"]

    if _bloc_non_vide(pc):
        lignes.append("### Publics cibles")
        if pc.get("description"):
            lignes.append(f"{pc['description']}")
        crit = pc.get("criteres_eligibilite") or []
        if crit:
            lignes.append("- **Critères d'éligibilité** :")
            for c in crit:
                lignes.append(f"  - {_item_label(c)}")
        spec = pc.get("publics_specifiques_signales") or []
        if spec:
            lignes.append(f"- **Publics spécifiques signalés** : {_join_safe(spec)}")
        lignes.append("")

    if _bloc_non_vide(vol):
        lignes.append("### Volumes")
        lignes.extend(_liste_kv(vol, [
            ("nb_beneficiaires_total", "Bénéficiaires (total)"),
            ("nb_beneficiaires_par_lot", "Par lot"),
            ("duree_par_parcours_heures", "Durée par parcours (h)"),
            ("duree_par_parcours_semaines", "Durée par parcours (sem.)"),
            ("duree_marche_mois", "Durée marché (mois)"),
            ("commentaire_volumes", "Note"),
        ]))
        lignes.append("")

    if _bloc_non_vide(mod):
        lignes.append("### Modalités")
        lignes.extend(_liste_kv(mod, [
            ("synchrone_asynchrone", "Présentiel/distanciel"),
            ("amplitude_horaire", "Amplitude horaire"),
        ]))
        sites = mod.get("sites_execution") or []
        if sites:
            lignes.append(f"- **Sites d'exécution** : {_join_safe(sites)}")
        lignes.append("")

    return lignes


def _generer_brief(marche: dict, extraction: dict) -> str:
    """Génère un brief markdown 1-page synthèse."""
    lignes = []

    titre = (marche.get("titre") or marche.get("objet") or "?").strip()
    titre = " ".join(titre.split())[:150]
    lignes.append(f"# Brief — {titre}")
    lignes.append("")
    lignes.append(f"_Généré le {datetime.now().strftime('%Y-%m-%d %H:%M')} "
                  f"par Claude {llm_extract.MODELE}_")
    lignes.append("")

    # En-tête marché
    lignes.append("## Identifiants")
    lignes.append(f"- **ID Tendia** : `{marche.get('id', '?')}`")
    lignes.append(f"- **Source** : {marche.get('source')} "
                  f"`{marche.get('reference_externe')}`")
    if marche.get("reference_ft"):
        lignes.append(f"- **Référence interne acheteur** : `{marche['reference_ft']}`")
    lignes.append(f"- **Acheteur** : {marche.get('acheteur_nom', '?')}")
    if marche.get("date_limite_depot"):
        lignes.append(f"- **Date limite de dépôt** : "
                      f"**{marche['date_limite_depot'][:10]}**")
    if marche.get("url_dce"):
        lignes.append(f"- **DCE PLACE** : <{marche['url_dce']}>")
    lignes.append("")

    # Synthèse
    lignes.append("## Synthèse")
    lignes.append(extraction.get("synthese_marche") or "—")
    lignes.append("")

    # === SECTIONS SECTORIELLES (preset-aware) ===
    # Chacune décide en interne si elle s'affiche, en fonction des blocs
    # effectivement remplis par le LLM dans l'extraction.
    lignes.extend(_section_chantier_btp(extraction))
    lignes.extend(_section_chantier_enr(extraction))
    lignes.extend(_section_moe(extraction))
    lignes.extend(_section_conseil(extraction))
    lignes.extend(_section_si(extraction))
    lignes.extend(_section_formation(extraction))

    # Montant du marché (la question récurrente pour décider GO/NO-GO)
    mm = extraction.get("montant_marche") or {}
    lignes.append("## 💶 Montant du marché")
    type_mm = mm.get("type") or "non_communique"
    val_centr = mm.get("valeur_estimee_euros")
    val_min = mm.get("fourchette_min_euros")
    val_max = mm.get("fourchette_max_euros")
    source = mm.get("source_extraction")
    duree = mm.get("duree_couverte")
    com = mm.get("commentaire")

    if type_mm == "estime_explicite" and val_centr:
        lignes.append(f"- **Valeur estimée** : "
                      f"**{_fmt_montant_euros(val_centr)}**")
        if duree:
            lignes.append(f"  - sur {duree}")
        if source:
            lignes.append(f"  - _source : {source}_")
    elif type_mm == "plafond" and val_centr:
        lignes.append(f"- **Plafond accord-cadre** : "
                      f"**{_fmt_montant_euros(val_centr)}**")
        if duree:
            lignes.append(f"  - sur {duree}")
        if source:
            lignes.append(f"  - _source : {source}_")
    elif (val_min is not None) or (val_max is not None):
        rng_min = _fmt_montant_euros(val_min) if val_min else "?"
        rng_max = _fmt_montant_euros(val_max) if val_max else "?"
        lignes.append(f"- **Fourchette** : entre {rng_min} et {rng_max}")
        if duree:
            lignes.append(f"  - sur {duree}")
        if source:
            lignes.append(f"  - _source : {source}_")
    elif type_mm == "calcule_volumes" and val_centr:
        lignes.append(f"- **Estimation calculée** : "
                      f"≈ {_fmt_montant_euros(val_centr)}")
        if com:
            lignes.append(f"  - _calcul : {com}_")
        if duree:
            lignes.append(f"  - sur {duree}")
    else:
        lignes.append(f"- _Montant non communiqué dans le DCE._")
        lignes.append(f"  - Typique des accords-cadres à bons de commande : "
                      f"le volume dépend des commandes effectivement passées "
                      f"par l'acheteur sur la durée du marché.")
    if com and type_mm not in ("calcule_volumes",):
        lignes.append(f"- _Note_ : {com}")
    lignes.append("")

    # Barème
    bar = extraction.get("bareme_notation") or {}
    lignes.append("## Barème de notation")
    lignes.append(f"- **Valeur technique** : "
                  f"{_fmt_val(bar.get('valeur_technique_pct'), ' %')}")
    lignes.append(f"- **Valeur prix** : "
                  f"{_fmt_val(bar.get('valeur_prix_pct'), ' %')}")
    sscrit = bar.get("sous_criteres_techniques") or []
    if sscrit:
        lignes.append(f"- **Sous-critères techniques** :")
        for sc in sscrit:
            lignes.append(f"  - {sc.get('libelle', '?')} : "
                          f"{_fmt_val(sc.get('ponderation_pct'), ' %')}")
    if bar.get("modalite_calcul_prix"):
        lignes.append(f"- **Calcul du prix** : {bar['modalite_calcul_prix']}")
    lignes.append("")

    # Références exigées
    ref = extraction.get("references_exigees") or {}
    lignes.append("## Références et qualifications exigées")
    lignes.append(f"- **Expérience minimale** : "
                  f"{_fmt_val(ref.get('experience_minimale_annees'), ' ans')}")
    # Volume minimal de références (nom élargi en v4) — fallback sur l'ancien
    # nom 'nb_min_stagiaires_accompagnes' pour les briefs extraits avant v4.
    vol_min = ref.get("volume_min_references_similaires")
    if vol_min is None:
        vol_min = ref.get("nb_min_stagiaires_accompagnes")
    unite_min = ref.get("volume_min_references_unite") or "références similaires"
    if vol_min is not None:
        lignes.append(f"- **Volume minimal de références** : "
                      f"{vol_min} {unite_min}")
    if ref.get("secteur_experience"):
        lignes.append(f"- **Secteur d'expérience** : {ref['secteur_experience']}")
    certifs = ref.get("certifications_obligatoires") or []
    if certifs:
        lignes.append(f"- **Certifications obligatoires** : {_join_safe(certifs)}")
    autres = ref.get("autres_exigences") or []
    if autres:
        lignes.append(f"- **Autres exigences** :")
        for a in autres:
            lignes.append(f"  - {_item_label(a)}")
    lignes.append("")

    # Lots — universel, mais skippé si l'allotissement BTP a déjà été rendu
    # (sinon doublon avec la section "## 🏗 Chantier" qui affiche les lots
    # détaillés).
    lots = extraction.get("lots") or []
    alot_rendu = _bloc_non_vide(extraction.get("allotissement"))
    if lots and not alot_rendu:
        lignes.append("## Lots")
        for lot in lots:
            lignes.append(f"- **Lot {lot.get('numero', '?')}** — "
                          f"{lot.get('intitule', '?')}")
            if lot.get("zone_geographique"):
                lignes.append(f"  - Zone : {lot['zone_geographique']}")
            # Volume estimé (nom élargi en v4) — fallback sur l'ancien
            # nom 'nb_beneficiaires_estime' pour les briefs avant v4.
            vol_lot = lot.get("volume_estime")
            if vol_lot is None:
                vol_lot = lot.get("nb_beneficiaires_estime")
            unite_lot = lot.get("volume_estime_unite") or "—"
            if vol_lot:
                lignes.append(f"  - Volume estimé : {vol_lot} {unite_lot}")
            if lot.get("particularites"):
                lignes.append(f"  - {lot['particularites']}")
        lignes.append("")

    # Alertes (critique)
    alertes = extraction.get("alertes_candidat") or []
    if alertes:
        lignes.append("## ⚠ Alertes candidat")
        for a in alertes:
            lignes.append(f"- {_item_label(a)}")
        lignes.append("")

    # Points différenciants
    diffs = extraction.get("points_differenciants_attendus") or []
    if diffs:
        lignes.append("## 💡 Points différenciants attendus")
        for d in diffs:
            lignes.append(f"- {_item_label(d)}")
        lignes.append("")

    return "\n".join(lignes)


# ---------------------------------------------------------------------------
# Workflow principal
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--marche", type=str, default=None,
                        help="ID du marché à traiter spécifiquement")
    parser.add_argument("--force", action="store_true",
                        help="Re-extraire même si déjà fait")
    parser.add_argument("--dry-run", action="store_true",
                        help="N'appelle pas l'API LLM, juste scan + extraction texte")
    args = parser.parse_args()

    print()
    print("=" * 78)
    print("  TENDIA — Extraction LLM des DCE")
    print("=" * 78)
    print(f"  Dossier DCE         : {REPERTOIRE_DCE}")
    print(f"  Sortie extractions  : {REPERTOIRE_EXTRACTIONS}")
    print(f"  Modèle Claude       : {llm_extract.MODELE}")
    if args.dry_run:
        print(f"  MODE DRY-RUN (pas d'appel API)")

    # Vérif API key sauf en dry-run
    if not args.dry_run:
        cle = llm_extract._obtenir_cle_api()
        if not cle:
            print()
            print("❌ Clé API Anthropic introuvable.")
            print()
            print("  Solution simple : crée un fichier .env à la racine du projet :")
            print(f"     {os.path.join(REPERTOIRE_BASE, '.env')}")
            print()
            print("  Contenu du fichier (une seule ligne) :")
            print('     ANTHROPIC_API_KEY=sk-ant-XXXXXXXX')
            print()
            print("  (Pas de guillemets, pas d'espaces autour du =)")
            sys.exit(1)
        else:
            print(f"  Clé API détectée    : {cle[:10]}... ({len(cle)} chars)")

    # Scanner
    print()
    print("─" * 78)
    print("  Scan des dossiers DCE...")
    print("─" * 78)
    a_traiter = _scanner_dossiers_dce(force=args.force, verbose=True)

    if args.marche:
        a_traiter = [t for t in a_traiter if t[0] == args.marche]

    if not a_traiter:
        print()
        print("  ℹ Aucun marché à traiter.")
        print(f"    → Dépose les PDFs dans : {REPERTOIRE_DCE}\\<id_marche>\\")
        print(f"    → Puis relance ce script.")
        return

    print(f"  {len(a_traiter)} marché(s) à traiter :")
    for id_marche, _, pdfs, raison in a_traiter:
        print(f"    - {id_marche} ({len(pdfs)} PDF(s)) — {raison}")

    # Traitement
    etat = _charger_etat()
    stats = {"ok": 0, "echec": 0}

    for id_marche, dossier, pdfs, raison in a_traiter:
        resultat = traiter_marche(
            id_marche, dossier, pdfs,
            dry_run=args.dry_run, verbose=True,
        )
        if resultat["ok"]:
            stats["ok"] += 1
            if not args.dry_run:
                etat[id_marche] = {
                    "signature_pdfs": _signature_pdfs(pdfs),
                    "extrait_le": datetime.now(timezone.utc).isoformat(),
                    "pdfs": [n for n in pdfs.keys()],
                }
                _sauver_etat(etat)
        else:
            stats["echec"] += 1
            print(f"    ❌ {resultat.get('erreur')}")

    print()
    print("─" * 78)
    print("  Bilan")
    print("─" * 78)
    print(f"  Succès : {stats['ok']}")
    print(f"  Échec  : {stats['echec']}")
    print()
    if stats["ok"] > 0:
        print(f"  📄 Briefs disponibles dans : {REPERTOIRE_RAPPORTS}\\brief_*.md")
        print(f"  📦 JSON structurés dans    : {REPERTOIRE_EXTRACTIONS}\\*.json")


if __name__ == "__main__":
    main()
