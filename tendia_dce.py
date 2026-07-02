"""
tendia_dce.py
-------------
Script principal de récupération des URLs DCE pour les marchés actifs.

Pour chaque marché dont la date limite de dépôt est >= aujourd'hui (ou
publié récemment sans date limite), on :
1. Récupère le record API source (BOAMP / TED)
2. Extrait l'URL DCE spécifique :
   - Soit directement depuis le champ eForms (qualité 'directe')
   - Soit en cherchant sur PLACE par référence interne FT (qualité 'via_keyword')
3. Stocke url_dce + reference_ft dans le marché en base
4. Génère un rapport markdown avec toutes les infos cliquables

Usage :
    python tendia_dce.py                  # marchés actifs uniquement
    python tendia_dce.py --jours 90       # fenêtre élargie
    python tendia_dce.py --tous           # tous les marchés en base
    python tendia_dce.py --dry-run        # affiche sans modifier la base
    python tendia_dce.py --rapport-seul   # ne refait pas la recherche, juste le rapport
"""

import argparse
import os
import sys
import time
from collections import Counter
from datetime import date, datetime, timezone

import stockage
import dce_finder


COLLECTION_MARCHES = "marches"
REPERTOIRE_RAPPORTS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "rapports"
)
REPERTOIRE_DCE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "dce"
)


# ===========================================================================
# Qualification du CONTENU d'un dossier DCE (Sprint Téléchargeur)
# ===========================================================================
# NB : distinct de `dce_qualite` (résolution d'URL : directe/via_keyword/...).
# Le résultat de `qualifier_dce` est persisté dans le champ `dce_contenu`
# (5 niveaux : complet | incomplet | vide | auth_requise | erreur), sans
# toucher `dce_qualite` (lu comme filtre par enrichir/pipeline/veille).

import io as _io
import re as _re
import unicodedata as _unicodedata
import zipfile as _zipfile

# Pièces contractuelles : leur présence rend le DCE briefable.
# NB : `_norm_nom` sépare chiffres/lettres collés ('rc2026' -> 'rc 2026') mais
# PAS un suffixe-lettre de version collé ('CCAPv2' -> 'ccapv 2', token 'ccapv').
# Les motifs d'acronymes tolèrent donc un suffixe alpha optionnel (`[a-z]*` /
# `v?`) pour rattraper les versions (CCTPv3, CCAPv2, RCv2, AEv1...). Le CCTP
# couvre aussi « Cahier des charges » (nom usuel en prestations de service), et
# on reconnaît le CCP/CCATP (cahier des clauses particulières, doc combiné).
PATTERNS_PIECES_CONTRACTUELLES = {
    "RC":   [r"\brcv?\b", r"r[èe]glement.*consultation", r"regl.{0,3}cons"],
    "CCAP": [r"\bccap[a-z]*\b", r"clauses.*administratives.*particulieres"],
    "CCTP": [r"\bcctp[a-z]*\b", r"clauses.*techniques.*particulieres",
             r"cahier.{0,5}des.{0,5}charges", r"\bcdc\b"],
    "CCAG": [r"\bccag\b"],
    "DPGF": [r"\bdpgf[a-z]*\b", r"d[ée]composition.*prix.*global"],
    "BPU":  [r"\bbpu[a-z]*\b", r"bordereau.*prix.*unitaire"],
    "AE":   [r"\baev?\b", r"acte.*engagement"],
    "CCTG": [r"\bcctg\b"],
    "AAPC": [r"\baapc\b"],
    "CCP":  [r"\bccp[a-z]*\b", r"\bccatp[a-z]*\b",
             r"cahier.{0,5}des.{0,5}clauses.{0,5}particulieres"],
    # DCE consolidé en UN document (certains acheteurs publient tout le dossier de
    # consultation dans un seul PDF nommé « DCE… » / « Dossier de consultation »).
    # Sans ce type, ce fichier ne matchait aucune pièce → faux « vide ».
    "DCE":  [r"\bdce\b", r"dossier.{0,5}(de.{0,5})?consultation"],
}

# Pièces administratives non-DCE : ne comptent PAS comme contractuelles.
PATTERNS_FICHIERS_ADMINISTRATIFS = [
    r"depot.?pli",
    r"avis.?de.?publicit",
    r"\bdume\b",
    r"attestation",
    r"^formulaire",
    r"^aapc[._].*publicit",
]

# Plateformes qui exigent une authentification (auth + captcha) : le DCE n'est
# pas téléchargeable en automatique. À court-circuiter.
# www.marches-publics.info (AWS-Achat) a été retiré : aws_downloader sait
# désormais récupérer le DCE en mode anonyme (workflow ColdFusion + 2captcha).
PLATEFORMES_AUTH_REQUISES = {
    "marches-securises.fr",
}

# Motifs d'une page HTML de connexion / consultation côté agent.
_PATTERNS_LOGIN_HTML = [
    r"<form[^>]*login", r"password", r"mot de passe",
    r"veuillez vous connecter", r"authentification requise",
    r"entreprisedetailsconsultation", r"entrepriseadvancedsearch",
]


def _reparer_mojibake(s: str) -> str:
    """Répare un nom UTF-8 lu en latin-1 ('RÃ¨glement' -> 'Règlement')."""
    if "Ã" in s or "Â" in s:
        try:
            return s.encode("latin-1", "ignore").decode("utf-8", "ignore")
        except (UnicodeError, ValueError):
            return s
    return s


def _norm_nom(s: str) -> str:
    """
    Normalise un nom de fichier pour le matching : répare le mojibake, minuscule,
    retire les accents, sépare lettres/chiffres collés ('RC2026' -> 'rc 2026') et
    remplace les séparateurs (_, -, .) par des espaces ('2026_RC_MOE' -> 'rc'
    isolé), pour que les `\\b...\\b` matchent.
    """
    s = _reparer_mojibake(str(s or ""))
    nfkd = _unicodedata.normalize("NFKD", s.lower())
    sans_accent = "".join(c for c in nfkd if not _unicodedata.combining(c))
    # Sépare lettres<->chiffres collés (rc2026 -> rc 2026)
    espace = _re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", sans_accent)
    return _re.sub(r"[^a-z0-9]+", " ", espace)


def _est_administratif(nom_norm: str) -> bool:
    return any(_re.search(p, nom_norm) for p in PATTERNS_FICHIERS_ADMINISTRATIFS)


def _type_contractuel(nom_norm: str):
    """Retourne le type de pièce contractuelle (RC, CCAP, ...) ou None."""
    for type_piece, patterns in PATTERNS_PIECES_CONTRACTUELLES.items():
        if any(_re.search(p, nom_norm) for p in patterns):
            return type_piece
    return None


# Formulaires de candidature (DC1 lettre de candidature, DC2 déclaration du
# candidat, DC4 sous-traitance). Leur présence — quand le dossier ne contient
# pas encore de CCAP/CCTP — signale une consultation en PHASE CANDIDATURE.
_PATTERNS_DC_CANDIDATURE = [r"\bdc\s*[124]\b", r"lettre.{0,5}candidature",
                           r"declaration.{0,8}candidat"]


def _est_dc_candidature(nom_norm: str) -> bool:
    return any(_re.search(p, nom_norm) for p in _PATTERNS_DC_CANDIDATURE)


# Taille max d'une archive INTERNE lue en mémoire pour lister son contenu
# (garde-fou anti-OOM sur un ZIP de plans volumineux imbriqué).
_TAILLE_MAX_ARCHIVE_INTERNE = 300 * 1024 * 1024


def _noms_7z_rar(source, ext: str) -> list:
    """
    Basenames contenus dans une archive .7z (py7zr) ou .rar (rarfile).
    `source` = chemin (str) ou objet fichier en mémoire. Skip propre (liste
    vide) si la lib est absente ou l'archive illisible — jamais d'exception.
    """
    noms = []
    try:
        if ext == ".7z":
            import py7zr
            with py7zr.SevenZipFile(source, mode="r") as a:
                noms = a.getnames()
        elif ext == ".rar":
            try:
                import rarfile
            except ImportError:
                return []
            with rarfile.RarFile(source) as a:
                noms = a.namelist()
    except Exception:
        return []
    return [os.path.basename(n) for n in noms if n and not str(n).endswith("/")]


def _noms_dans_zip(zf, niveau: int = 0) -> list:
    """
    Basenames d'un ZipFile ouvert. Descend d'UN niveau dans les archives
    internes (.zip imbriqué, .7z, .rar) — lues EN MÉMOIRE, sans extraction
    disque. `niveau` borne la récursion à 1 (évite zip-bomb / boucles).
    """
    noms = []
    for n in zf.namelist():
        if not n or n.endswith("/"):
            continue
        bn = os.path.basename(n)
        noms.append(bn)
        if niveau >= 1:
            continue  # un seul niveau de descente
        low = bn.lower()
        if not low.endswith((".zip", ".7z", ".rar")):
            continue
        try:
            if zf.getinfo(n).file_size > _TAILLE_MAX_ARCHIVE_INTERNE:
                continue
            data = _io.BytesIO(zf.read(n))
        except Exception:
            continue
        if low.endswith(".zip"):
            try:
                with _zipfile.ZipFile(data) as z2:
                    noms.extend(_noms_dans_zip(z2, niveau + 1))
            except Exception:
                pass
        else:
            noms.extend(_noms_7z_rar(data, ".7z" if low.endswith(".7z") else ".rar"))
    return noms


def _html_est_login(chemin: str) -> bool:
    """Vrai si le fichier HTML ressemble à une page de connexion."""
    try:
        with open(chemin, "r", encoding="utf-8", errors="ignore") as f:
            contenu = f.read(200_000).lower()
    except OSError:
        return False
    return any(_re.search(p, contenu) for p in _PATTERNS_LOGIN_HTML)


def url_est_auth_requise(url_dce: str) -> bool:
    """Vrai si l'URL DCE pointe vers une plateforme à authentification connue."""
    u = (url_dce or "").lower()
    return any(p in u for p in PLATEFORMES_AUTH_REQUISES)


def qualifier_dce(dossier_dce_path: str, log_telechargement: dict = None) -> dict:
    """
    Qualifie le CONTENU d'un dossier DCE téléchargé.

    Inspecte les fichiers et les noms internes des archives — y compris les ZIP
    imbriqués (1 niveau) et les .7z/.rar, lus en mémoire sans extraction —,
    détecte les pièces contractuelles, les pages de login, et rend un verdict
    en 6 niveaux. Idempotent, pur (ne modifie pas le dossier).

    Retourne {qualite, pieces_contractuelles, nb_fichiers, taille_totale_octets, raison}.
    qualite ∈ {complet, incomplet, candidature, vide, auth_requise, erreur}.
    Ordre des règles (premier match l'emporte) : erreur > auth_requise > vide >
    (que de l'administratif) > candidature (DC + RC seul) > incomplet (1 pièce)
    > complet (≥2 pièces).
    `candidature` : la consultation n'expose que le RC + formulaires DC1/DC2 ;
    le CCAP/CCTP (phase offre) n'est pas encore publié — ce n'est pas un défaut.
    """
    res = {"qualite": "vide", "pieces_contractuelles": [], "nb_fichiers": 0,
           "taille_totale_octets": 0, "raison": "dossier vide"}

    # 1) Erreur réseau / HTTP signalée par le log de téléchargement
    if isinstance(log_telechargement, dict):
        statut = log_telechargement.get("statut")
        if statut in ("erreur", "echec") or log_telechargement.get("erreur"):
            raison = (log_telechargement.get("raison")
                      or log_telechargement.get("erreur") or "erreur téléchargement")
            res.update(qualite="erreur", raison=str(raison)[:200])
            return res

    if not dossier_dce_path or not os.path.isdir(dossier_dce_path):
        res.update(qualite="vide", raison="dossier inexistant")
        return res

    noms = []
    taille = 0
    nb = 0
    login = False
    for racine, _dirs, fichiers in os.walk(dossier_dce_path):
        for f in fichiers:
            chemin = os.path.join(racine, f)
            try:
                t = os.path.getsize(chemin)
            except OSError:
                t = 0
            taille += t
            nb += 1
            noms.append(f)
            low = f.lower()
            if low.endswith(".zip"):
                try:
                    with _zipfile.ZipFile(chemin) as z:
                        noms.extend(_noms_dans_zip(z, 0))
                except Exception:
                    pass
            elif low.endswith((".7z", ".rar")):
                noms.extend(_noms_7z_rar(chemin, ".7z" if low.endswith(".7z") else ".rar"))
            elif (low.endswith(".html") or low.endswith(".htm")) and 0 < t < 100 * 1024:
                if _html_est_login(chemin):
                    login = True

    res["nb_fichiers"] = nb
    res["taille_totale_octets"] = taille

    # 2) Page de login détectée
    if login:
        res.update(qualite="auth_requise",
                   raison="page de connexion détectée (auth + captcha)")
        return res

    # 3) Dossier vide / quasi-vide
    if taille < 1024:
        res.update(qualite="vide", raison="dossier vide")
        return res

    # Classement des noms
    _EXT_DOC = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                ".odt", ".ods", ".dwg", ".dxf", ".rtf", ".csv")
    types = set()
    n_admin = 0
    n_substantiel = 0   # documents « métier » réels (hors administratif)
    a_dc = False
    for nom in noms:
        if nom.endswith("/"):
            continue  # entrée dossier dans un zip
        nn = _norm_nom(nom)
        if _est_dc_candidature(nn):
            a_dc = True
        if _est_administratif(nn):
            n_admin += 1
            continue
        tc = _type_contractuel(nn)
        if tc:
            types.add(tc)
        if nom.lower().endswith(_EXT_DOC):
            n_substantiel += 1
    pieces = sorted(types)
    res["pieces_contractuelles"] = pieces

    # 3bis) Dossier RICHE : le completeDownload a ramené un vrai dossier multi-
    # documents dont les noms ne suivent pas la nomenclature canonique (cadres de
    # réponse, annexes, présentations, tableaux de candidature, plans...). Avec
    # ≥3 documents substantiels, c'est un DCE complet même si <2 pièces nommées
    # sont reconnues — sinon on marquait à tort « incomplet » des dossiers entiers.
    if n_substantiel >= 3:
        res.update(qualite="complet",
                   raison=f"complet : {n_substantiel} documents (dossier riche)")
        return res

    # 4) Aucune pièce contractuelle
    if not pieces:
        res.update(qualite="vide",
                   raison="uniquement fichiers administratifs" if n_admin
                   else "aucune pièce contractuelle exploitable")
        return res

    # 4bis) Phase candidature : formulaire(s) DC1/DC2/DC4 + RC seul, sans aucune
    # pièce "marché" (CCAP/CCTP/CCTG). Le DCE travaux/offre n'est pas encore
    # publié — ce n'est PAS un défaut de récupération, on le distingue.
    if a_dc and types == {"RC"}:
        res.update(qualite="candidature",
                   raison="phase candidature (formulaire DC + RC, sans CCAP/CCTP)")
        return res

    # 5) Une seule pièce
    if len(pieces) == 1:
        res.update(qualite="incomplet",
                   raison=f"1 seule pièce contractuelle ({pieces[0]})")
        return res

    # 6) DCE complet
    res.update(qualite="complet", raison="complet : " + ", ".join(pieces) + " détectés")
    return res


# ---------------------------------------------------------------------------
# Filtre marchés actifs
# ---------------------------------------------------------------------------

def _est_actif(marche: dict, fenetre_jours_sans_date: int = 60) -> bool:
    date_lim = marche.get("date_limite_depot")
    today = date.today().isoformat()
    if date_lim and len(date_lim) >= 10:
        return date_lim[:10] >= today
    date_pub = marche.get("date_publication")
    if not date_pub or len(date_pub) < 10:
        return False
    try:
        d = date.fromisoformat(date_pub[:10])
        return (date.today() - d).days <= fenetre_jours_sans_date
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Traitement principal : recherche URLs DCE
# ---------------------------------------------------------------------------

def traiter(filtre_actifs: bool = True,
            fenetre_jours_sans_date: int = 60,
            dry_run: bool = False,
            verbose: bool = True) -> dict:
    marches = stockage.charger(COLLECTION_MARCHES)
    if not marches:
        print("❌ Aucun marché en base. Lance d'abord : python tendia_recup.py")
        sys.exit(1)

    if filtre_actifs:
        marches_a_traiter = {
            mid: m for mid, m in marches.items()
            if _est_actif(m, fenetre_jours_sans_date)
        }
    else:
        marches_a_traiter = marches

    if verbose:
        print()
        print("=" * 78)
        print(f"  TENDIA — Recherche d'URLs DCE")
        print("=" * 78)
        print(f"  Marchés en base    : {len(marches)}")
        print(f"  Marchés à traiter  : {len(marches_a_traiter)} "
              f"({'actifs uniquement' if filtre_actifs else 'tous'})")
        print()

    if not marches_a_traiter:
        if verbose:
            print("  ⚠ Aucun marché à traiter.")
        return {}

    stats = {
        "total": 0,
        "par_qualite": Counter(),
        "avec_ref_ft": 0,
        "avec_url_dce": 0,
    }
    horodatage = datetime.now(timezone.utc).isoformat()

    for i, (mid, marche) in enumerate(marches_a_traiter.items(), 1):
        if verbose:
            titre = (marche.get("titre") or marche.get("objet") or "?")[:75]
            print(f"  [{i}/{len(marches_a_traiter)}] {marche.get('source')} - {titre}")

        resultat = dce_finder.trouver_urls_dce(marche, verbose=False)
        stats["total"] += 1
        qualite = resultat.get("qualite", "absente")
        stats["par_qualite"][qualite] += 1

        if resultat.get("reference_ft"):
            stats["avec_ref_ft"] += 1
        if resultat.get("url_dce"):
            stats["avec_url_dce"] += 1

        if verbose:
            print(f"      → qualité : {qualite}")
            if resultat.get("reference_ft"):
                print(f"        réf FT : {resultat['reference_ft']}")
            if resultat.get("url_dce"):
                print(f"        URL DCE : {resultat['url_dce'][:100]}")

        # Mise à jour du marché en base
        if not dry_run:
            # NE PAS écraser une url_dce existante par None : une re-résolution qui
            # échoue (lien direct expiré, recherche muette) ne doit pas effacer le
            # lien d'un marché déjà résolu/complet. On n'écrit que si on a trouvé
            # une nouvelle URL, ou s'il n'y en avait pas encore.
            nouvelle_url = resultat.get("url_dce")
            if nouvelle_url or not (marche.get("url_dce") or "").strip():
                marche["url_dce"] = nouvelle_url
            marche["reference_ft"] = resultat.get("reference_ft") or marche.get("reference_ft")
            marche["url_recherche_place"] = resultat.get("url_recherche")
            marche["dce_qualite"] = qualite
            marche["dce_recherche_le"] = horodatage
            stockage.ecrire(COLLECTION_MARCHES, mid, marche)

        # Politesse entre fetchs
        time.sleep(0.3)

    if verbose:
        print()
        print("─" * 78)
        print("  Bilan")
        print("─" * 78)
        print(f"  Marchés traités          : {stats['total']}")
        print(f"  Avec référence FT extraite : {stats['avec_ref_ft']}")
        print(f"  Avec URL DCE              : {stats['avec_url_dce']}")
        print(f"  Par qualité :")
        for q, n in stats["par_qualite"].most_common():
            print(f"    {q:<12} : {n}")

    return stats


# ---------------------------------------------------------------------------
# Génération du rapport markdown
# ---------------------------------------------------------------------------

def _verdict_pour_profil(marche: dict, profil: dict) -> dict:
    """Calcule le verdict matching pour un marché contre un profil."""
    try:
        import matching
        # Sprint B : brief passe au matching pour scoring sectoriel.
        brief = stockage.lire("briefs_extraits", marche.get("id"))
        return matching.evaluer(profil, marche, brief=brief)
    except Exception:
        return None


def _dossier_dce_local(marche: dict) -> str:
    """Chemin local où l'utilisateur dépose les PDFs téléchargés."""
    mid = marche.get("id", "?")
    return os.path.join(REPERTOIRE_DCE, mid)


def generer_rapport(filtre_actifs: bool = True,
                     fenetre_jours_sans_date: int = 60) -> str:
    """Génère le rapport markdown des marchés actifs avec URLs DCE."""
    marches = stockage.charger(COLLECTION_MARCHES)

    if filtre_actifs:
        marches_filtres = [m for m in marches.values()
                            if _est_actif(m, fenetre_jours_sans_date)]
    else:
        marches_filtres = list(marches.values())

    # Charge le profil actif pour matcher
    try:
        import organisme
        profil = organisme.lire_profil()
    except Exception:
        profil = None

    # Trie par verdict (les plus pertinents en premier) si profil dispo
    if profil:
        ordre_verdict = {
            "tres_pertinent": 0, "pertinent": 1,
            "a_verifier": 2, "non_pertinent": 3,
        }
        for m in marches_filtres:
            v = _verdict_pour_profil(m, profil)
            m["_eval"] = v
        marches_filtres.sort(key=lambda m: (
            ordre_verdict.get((m.get("_eval") or {}).get("verdict"), 4),
            -((m.get("_eval") or {}).get("score", 0)),
        ))

    horodatage = datetime.now().isoformat(timespec="seconds")
    nom_org = (profil or {}).get("identite", {}).get("nom", "?")

    lignes = [
        f"# Marchés actifs Tendia — {horodatage}",
        "",
        f"Organisme : **{nom_org}**" if profil else "Organisme : (aucun profil actif)",
        f"Nombre de marchés : **{len(marches_filtres)}**",
        "",
        "---",
        "",
    ]

    if not marches_filtres:
        lignes.append("> Aucun marché actif à ce jour.")
        return "\n".join(lignes)

    verdict_emojis = {
        "tres_pertinent": "✅", "pertinent": "🟢",
        "a_verifier": "🟡", "non_pertinent": "⚪",
    }

    for marche in marches_filtres:
        eval_ = marche.get("_eval") or {}
        verdict = eval_.get("verdict", "?")
        score = eval_.get("score", 0)
        emoji = verdict_emojis.get(verdict, "❓")

        titre = (marche.get("titre") or marche.get("objet") or "?").strip()
        # Nettoyer le titre (newlines, etc.)
        titre_court = " ".join(titre.split())[:120]

        lignes.append(f"## {emoji} {titre_court}")
        lignes.append("")
        lignes.append(f"**Verdict** : {verdict} (score {score}/100)" if eval_ else "")
        lignes.append(
            f"- **Acheteur** : {marche.get('acheteur_nom', '?')}"
        )
        lignes.append(
            f"- **Source** : {marche.get('source')} `{marche.get('reference_externe')}`"
        )
        if marche.get("reference_ft"):
            lignes.append(
                f"- **Référence interne acheteur** : `{marche['reference_ft']}`"
            )
        lignes.append(
            f"- **Catégorie** : {marche.get('categorie_metier', '?')}"
        )
        if marche.get("date_publication"):
            lignes.append(f"- **Publié** : {marche['date_publication'][:10]}")
        if marche.get("date_limite_depot"):
            lignes.append(f"- **Date limite de dépôt** : "
                          f"**{marche['date_limite_depot'][:10]}**")

        # Liens
        lignes.append("")
        lignes.append("**Liens** :")
        if marche.get("url_dce"):
            qualite = marche.get("dce_qualite", "?")
            badge = "✅ direct" if qualite == "directe" else "🔍 via keyWord"
            lignes.append(
                f"- {badge} **Consultation PLACE** (DCE téléchargeable) : "
                f"<{marche['url_dce']}>"
            )
            lignes.append(f"- Avis source : <{marche.get('url_avis', '?')}>")
        else:
            # Pas d'URL DCE trouvée → fallback sur l'avis source qui contient
            # souvent les coordonnées du profil acheteur et un PDF d'avis complet
            source = marche.get("source", "?")
            url_avis = marche.get("url_avis", "?")
            lignes.append(
                f"- 🔗 **Voir l'avis sur {source}** (URL DCE non publiée par "
                f"l'acheteur, l'avis contient les modalités d'accès au DCE) : "
                f"<{url_avis}>"
            )
            if marche.get("url_recherche_place") and source != "TED":
                lignes.append(
                    f"- Recherche manuelle PLACE : "
                    f"<{marche['url_recherche_place']}>"
                )

        # Dossier local DCE
        dossier = _dossier_dce_local(marche)
        lignes.append("")
        lignes.append(f"**Dossier local** pour déposer les PDF téléchargés :")
        lignes.append(f"```")
        lignes.append(dossier)
        lignes.append(f"```")

        # Objet complet
        objet = marche.get("objet", "")
        if objet and objet != titre:
            lignes.append("")
            lignes.append(f"**Objet** : {objet[:600]}")

        # Motifs du matching si dispo
        if eval_ and eval_.get("motifs"):
            lignes.append("")
            lignes.append("**Motifs de matching** :")
            for motif in eval_["motifs"]:
                if motif.get("points"):
                    signe = "+" if motif["points"] > 0 else ""
                    lignes.append(f"  - [{signe}{motif['points']}] "
                                  f"**{motif['critere']}** — {motif['commentaire']}")

        lignes.append("")
        lignes.append("---")
        lignes.append("")

    return "\n".join(lignes)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Récupération des URLs DCE et rapport des marchés actifs."
    )
    parser.add_argument("--jours", type=int, default=60,
                        help="Fenêtre (jours) pour marchés sans date limite.")
    parser.add_argument("--tous", action="store_true",
                        help="Traite TOUS les marchés (pas seulement actifs).")
    parser.add_argument("--dry-run", action="store_true",
                        help="N'écrit rien en base.")
    parser.add_argument("--rapport-seul", action="store_true",
                        help="Génère juste le rapport, sans relancer la "
                             "recherche d'URLs DCE.")
    args = parser.parse_args()

    if not args.rapport_seul:
        traiter(
            filtre_actifs=not args.tous,
            fenetre_jours_sans_date=args.jours,
            dry_run=args.dry_run,
            verbose=True,
        )

    # Génère le rapport
    print()
    print("=" * 78)
    print("  Génération du rapport")
    print("=" * 78)
    rapport = generer_rapport(
        filtre_actifs=not args.tous,
        fenetre_jours_sans_date=args.jours,
    )
    os.makedirs(REPERTOIRE_RAPPORTS, exist_ok=True)
    dat = datetime.now().strftime("%Y-%m-%d")
    chemin = os.path.join(REPERTOIRE_RAPPORTS, f"marches_actifs_{dat}.md")
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(rapport)
    print(f"  📄 Rapport écrit : {chemin}")

    # Crée les dossiers data/dce/<id> pour les marchés actifs
    if not args.dry_run:
        marches = stockage.charger(COLLECTION_MARCHES)
        actifs = [m for m in marches.values()
                   if _est_actif(m, args.jours)] if not args.tous \
                else list(marches.values())
        os.makedirs(REPERTOIRE_DCE, exist_ok=True)
        for m in actifs:
            os.makedirs(_dossier_dce_local(m), exist_ok=True)
        print(f"  📁 {len(actifs)} dossiers DCE créés sous {REPERTOIRE_DCE}")


if __name__ == "__main__":
    main()
