"""
tendia_telecharger_dce.py
-------------------------
Téléchargement automatique des pièces DCE depuis PLACE (marches-publics.gouv.fr).

Pour chaque marché qui a une `url_dce` renseignée dans data/marches.json :
1. GET la page de consultation PLACE.
2. Parse la page (html.parser stdlib) pour repérer :
   - Liens directs vers .pdf / .zip / .doc / .docx
   - Formulaires de consentement CGU (POST avec checkbox)
   - Indicateurs de login requis ou captcha
3. Si formulaire CGU détecté → soumet automatiquement, re-parse la page suivante.
4. Télécharge les pièces accessibles dans data/dce/<id>/.
5. Tag le marché dans marches.json avec le statut et les détails.

Modes CLI :
  --marche XXX  : un seul marché par son ID
  --limit N     : limite à N marchés
  --force       : re-télécharge même si DCE déjà présent
  --dry-run     : explore les pages sans rien télécharger
  --verbose     : log détaillé HTTP

Limites connues :
- Marchés requérant un compte fournisseur PLACE → reportés en "manuel_requis"
- Captchas anti-bot → idem
- Sites avec JS dynamique → non gérés (pas Playwright pour l'instant)

Statuts de téléchargement écrits dans chaque marché :
  ok             : pièces téléchargées
  echec          : pas de pièces trouvées sur la page
  manuel_requis  : login/captcha détecté
  pas_url        : pas d'url_dce renseignée
  erreur_reseau  : connexion impossible
"""

import argparse
import json
import io
import os
import re
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urljoin, urlparse

import requests

# SSL : ce module fait ses requêtes via un requests.Session() brut. Sur ce poste
# Windows, le magasin certifi ne contient pas tous les CA intermédiaires des
# plateformes (PLACE, e-marchespublics, achatpublic, Atexo...), d'où des
# CERTIFICATE_VERIFY_FAILED systématiques (dette technique B4). `truststore`
# bascule Python sur le magasin de certificats système. Injection globale au
# process et idempotente.
try:
    import truststore as _truststore
    _truststore.inject_into_ssl()
except Exception:
    pass

# Force UTF-8 sur stdout/stderr (Windows cp1252 sinon UnicodeEncodeError sur
# les caracteres de mise en forme tableau ├ ─ etc.). Cohérent avec
# diagnostic_dce_pertinents.py et enrichir_complet.py.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REPERTOIRE_BASE = Path(__file__).parent
FICHIER_MARCHES = REPERTOIRE_BASE / "data" / "marches.json"
REPERTOIRE_DCE = REPERTOIRE_BASE / "data" / "dce"

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/121.0.0.0 Safari/537.36")
TIMEOUT_SEC = 30
DELAI_ENTRE_REQUETES_SEC = 1.5
MAX_TAILLE_FICHIER_MB = 100

EXTENSIONS_DOC = ('.pdf', '.zip', '.doc', '.docx', '.xlsx', '.xls', '.7z', '.rar')

# Mots-clés URL qui suggèrent un lien de téléchargement DCE même sans extension
MOTIFS_URL_DCE = (
    'telechargement', 'download', 'pieces', 'documentsconsultation',
    'consultationtelechargement', 'getdocument', 'fichier', 'document',
    # Ajouts Phase 2a — e-marchespublics & profils acheteur divers :
    'dossier_de_consultation',   # e-marchespublics : .../dossier_de_consultation_marche_public_anonyme_<hash>
    'avisdetails',               # e-marchespublics : POST /pack/recherche/avisdetails/
    'retirer',                   # certains profils acheteur : "Retirer le DCE"
)

# Mots-clés évoquant le téléchargement dans la valeur/nom d'un input submit.
# Sert à détecter les formulaires POST de téléchargement direct (cf
# _est_formulaire_telechargement_direct ci-dessous).
KEYWORDS_SUBMIT_DCE = (
    'telecharg', 'download', 'retirer', 'piece', 'dce',
    'consultation', 'document',
)

# Fichiers servis par certaines plateformes SANS donner accès au vrai DCE
# (guides génériques, DUME européen, CGU). Si APRÈS téléchargement on n'a que
# ces fichiers-là, c'est un faux succès (page d'attente / accès non débloqué).
# Source : diagnostic batch 10/06/2026 — 86 marchés sur 242 dans ce cas.
FICHIERS_BRUIT_EXACT = {
    "depot-pli.pdf",          # Guide AW Solutions / DEMATIS (servi avant captcha)
    "DUME Acheteur.zip",      # Formulaire DUME européen générique
}
PATTERNS_BRUIT = (
    re.compile(r"^cgu[_\-]", re.IGNORECASE),  # cgu_1-1.pdf, cgu-conditions.pdf, etc.
)


def _est_fichier_bruit(nom: str) -> bool:
    """True si le fichier est un générique servi sans vraie valeur DCE."""
    if nom in FICHIERS_BRUIT_EXACT:
        return True
    return any(p.search(nom) for p in PATTERNS_BRUIT)


def _normaliser_url_dce(url: str) -> str:
    """
    Normalise une URL DCE issue de l'extraction eForms :
    - Préfixe `https://` si le schéma manque (cas `www.xxx.fr/...`).
    - Retourne la chaîne d'origine si déjà bien formée ou vide.
    """
    if not url:
        return url
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith("www.") or url.startswith("//"):
        return "https://" + url.lstrip("/")
    return url


# Patterns d'URL PLACE/Atexo réservées aux ACHETEURS (côté agent), pas aux
# entreprises. Suivre ces URLs ne donne accès à rien côté soumissionnaire.
RE_URL_AGENT = re.compile(
    r"(?:/agent(?:/|$|\?)|[?&]page=Agent\.)",
    re.IGNORECASE,
)


def _est_url_cote_agent(url: str) -> bool:
    """True si l'URL pointe vers l'espace acheteur (inaccessible aux entreprises)."""
    return bool(RE_URL_AGENT.search(url or ""))


# ---------------------------------------------------------------------------
# Parser HTML
# ---------------------------------------------------------------------------

class PagePlaceParser(HTMLParser):
    """
    Parse une page de consultation PLACE.
    Récupère : liens vers documents, formulaires (avec champs cachés),
    indicateurs login/captcha, titre de la page.
    """

    def __init__(self):
        super().__init__()
        self.liens_documents = []   # [{href, libelle, origine}]
        self.formulaires = []       # [{action, method, name, id, champs}]
        self.indicateur_login = False
        self.indicateur_captcha = False
        self.titre_page = ""

        self._dans_form = False
        self._form_courant = None
        self._dans_a = False
        self._href_courant = None
        self._buffer_libelle_a = ""
        self._dans_title = False
        self._current_select = None

    def handle_starttag(self, tag, attrs):
        ad = dict(attrs)
        tag = tag.lower()

        if tag == 'title':
            self._dans_title = True

        elif tag == 'a':
            href = (ad.get('href') or '').strip()
            self._dans_a = True
            self._href_courant = href
            self._buffer_libelle_a = ""
            href_low = href.lower()
            if any(ext in href_low for ext in EXTENSIONS_DOC):
                self.liens_documents.append({
                    'href': href, 'libelle': '', 'origine': 'extension',
                })
            elif any(m in href_low for m in MOTIFS_URL_DCE):
                self.liens_documents.append({
                    'href': href, 'libelle': '', 'origine': 'pattern_url',
                })

        elif tag == 'form':
            self._dans_form = True
            self._form_courant = {
                'action': ad.get('action', ''),
                'method': (ad.get('method') or 'GET').upper(),
                'name': ad.get('name', ''),
                'id': ad.get('id', ''),
                'champs': {},
            }

        elif tag == 'input' and self._dans_form and self._form_courant is not None:
            nom = ad.get('name')
            if nom:
                self._form_courant['champs'][nom] = {
                    'valeur': ad.get('value', ''),
                    'type': (ad.get('type') or 'text').lower(),
                    'checked': 'checked' in ad,
                }

        elif tag == 'select' and self._dans_form and self._form_courant is not None:
            nom = ad.get('name')
            if nom:
                self._form_courant['champs'][nom] = {
                    'valeur': '', 'type': 'select', 'options': [],
                }
                self._current_select = nom

        elif tag == 'option' and self._current_select and self._form_courant is not None:
            val = ad.get('value', '')
            if 'selected' in ad:
                if self._current_select in self._form_courant['champs']:
                    self._form_courant['champs'][self._current_select]['valeur'] = val

        elif tag == 'iframe':
            src = (ad.get('src') or '').lower()
            if 'recaptcha' in src or 'hcaptcha' in src:
                self.indicateur_captcha = True

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == 'a' and self._dans_a:
            if self.liens_documents:
                dernier = self.liens_documents[-1]
                if dernier['href'] == self._href_courant:
                    dernier['libelle'] = self._buffer_libelle_a.strip()[:80]
            self._dans_a = False
            self._href_courant = None
        elif tag == 'form':
            if self._form_courant:
                self.formulaires.append(self._form_courant)
            self._dans_form = False
            self._form_courant = None
        elif tag == 'title':
            self._dans_title = False
        elif tag == 'select':
            self._current_select = None

    def handle_data(self, data):
        if self._dans_a:
            self._buffer_libelle_a += data
        if self._dans_title:
            self.titre_page += data
        data_low = data.lower()
        if any(kw in data_low for kw in (
                'connectez-vous', 'identifiez-vous', 'inscription requise',
                "veuillez vous identifier", "authentification requise",
                'compte requis', 'login obligatoire')):
            self.indicateur_login = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _est_formulaire_consentement(form: dict) -> bool:
    """
    Heuristique : POST + au moins une checkbox + pas de champs text visibles.
    Capture les formulaires "J'accepte les conditions générales" de PLACE.
    """
    if form.get('method') != 'POST':
        return False
    champs = form.get('champs') or {}
    nb_checkbox = sum(1 for c in champs.values() if c.get('type') == 'checkbox')
    nb_text_visibles = sum(1 for c in champs.values()
                            if c.get('type') in ('text', 'email', 'password', 'tel'))
    return nb_checkbox > 0 and nb_text_visibles == 0


def _est_formulaire_telechargement_direct(form: dict) -> bool:
    """
    Détecte un formulaire POST avec un bouton submit dont le nom ou la valeur
    évoque le téléchargement direct du DCE, ET sans champ d'inscription
    obligatoire (text/email/password).

    Couvre notamment e-marchespublics, où une page de marché contient un form
    POST `/pack/recherche/avisdetails/` avec :
        - champs hidden id_procedure, source, onglet
        - input type=submit name=telecharger_rc value="Téléchargez le RC"
    On exclut les formulaires d'auto-inscription (`enregistrementEntreprise*`)
    qui demandent siret/société/adresse — ils nécessitent une vraie saisie.

    Phase 2a : sans cette détection, e-marchespublics tombait en "aucun lien
    document trouvé" sur 100% des marchés.
    """
    if form.get('method') != 'POST':
        return False
    champs = form.get('champs') or {}

    # Exclure les formulaires d'inscription : siret/email/adresse obligatoires
    nb_text_obligatoires = sum(
        1 for c in champs.values()
        if c.get('type') in ('text', 'email', 'password', 'tel')
    )
    if nb_text_obligatoires > 2:  # auto-inscription typique : 10+ champs text
        return False

    # Cherche un submit avec mot-clé téléchargement
    for nom, info in champs.items():
        if info.get('type') != 'submit':
            continue
        value = (info.get('valeur') or '').lower()
        nom_low = nom.lower()
        for kw in KEYWORDS_SUBMIT_DCE:
            if kw in value or kw in nom_low:
                return True
    return False


# ---------------------------------------------------------------------------
# Phase 5 — suivre la chaîne Atexo "demande de téléchargement sans
# identification" pour les plateformes en marque blanche (Maximilien,
# Ternum-BFC, 596280, adullact, etc.). Le moteur Atexo MPE expose ces URLs
# en intermédiaire : page → form → document.
# ---------------------------------------------------------------------------

MOTIFS_URL_INTERMEDIAIRE_ATEXO = (
    'entreprisedemandetelechargement',           # ...EntrepriseDemandeTelechargementDceSansIdentification
    'entreprisetelechargementsansidentification',
    'entreprisetelechargementpiece',
)


def _est_url_intermediaire_atexo(url: str) -> bool:
    """True si l'URL pointe vers une page intermédiaire Atexo qui requiert
    de suivre une chaîne de formulaires pour récupérer le DCE."""
    if not url:
        return False
    url_low = url.lower()
    return any(motif in url_low for motif in MOTIFS_URL_INTERMEDIAIRE_ATEXO)


def _suivre_chaine_atexo(session, url_initiale, dossier,
                         prof: int = 0, max_prof: int = 2,
                         form_data: Optional[dict] = None,
                         verbose: bool = False) -> dict:
    """
    Suit récursivement une chaîne Atexo : page intermédiaire → form → document.

    Hypothèse : sur les plateformes Atexo blanche, le téléchargement du DCE
    passe par 1-2 pages intermédiaires avec formulaire CGU/déclaration avant
    de servir le ZIP. Notre code historique abandonne dès qu'il reçoit du
    HTML, ce qui empêche d'arriver au document.

    Args:
        session: requests.Session avec cookies/headers déjà configurés.
        url_initiale: URL à GET (ou POST si form_data fourni).
        dossier: répertoire de destination pour les fichiers téléchargés.
        prof: profondeur de récursion actuelle.
        max_prof: profondeur max (default 2, suffit pour Atexo standard).
        form_data: si fourni, fait un POST avec ces données au lieu d'un GET.
        verbose: log debug.

    Returns:
        dict {nb_ok: int, fichiers: list[str], derniere_raison: str}
    """
    if prof > max_prof:
        return {'nb_ok': 0, 'fichiers': [], 'derniere_raison': 'max profondeur'}

    try:
        if form_data is not None:
            r = session.post(url_initiale, data=form_data,
                             timeout=TIMEOUT_SEC, stream=True,
                             allow_redirects=True)
        else:
            r = session.get(url_initiale, timeout=TIMEOUT_SEC,
                            stream=True, allow_redirects=True)
    except requests.RequestException as e:
        return {'nb_ok': 0, 'fichiers': [],
                'derniere_raison': f'{type(e).__name__}: {e}'}

    if r.status_code != 200:
        return {'nb_ok': 0, 'fichiers': [],
                'derniere_raison': f'HTTP {r.status_code}'}

    ctype = (r.headers.get('Content-Type') or '').lower()
    is_html = 'text/html' in ctype and not any(
        bin_t in ctype for bin_t in ('application/pdf', 'application/zip',
                                      'application/octet-stream'))

    if is_html:
        # Page intermédiaire : on parse et on suit la chaîne
        if prof >= max_prof:
            return {'nb_ok': 0, 'fichiers': [],
                    'derniere_raison': 'HTML reçu à profondeur max'}

        html_text = r.text
        p = PagePlaceParser()
        p.feed(html_text)

        # Détecteurs de "murs" qui ne servent à rien de suivre
        if p.indicateur_captcha:
            return {'nb_ok': 0, 'fichiers': [],
                    'derniere_raison': 'captcha sur page intermédiaire'}
        if p.indicateur_login:
            return {'nb_ok': 0, 'fichiers': [],
                    'derniere_raison': 'login requis sur page intermédiaire'}

        # Cherche un formulaire à suivre (priorité : CGU > téléchargement direct)
        form_chain = (
            next((f for f in p.formulaires
                  if _est_formulaire_consentement(f)), None)
            or
            next((f for f in p.formulaires
                  if _est_formulaire_telechargement_direct(f)), None)
        )

        if form_chain:
            action = form_chain.get('action') or ''
            action_url = urljoin(url_initiale, action) if action else url_initiale
            data = _data_form(form_chain)
            if verbose:
                print(f"      → chaîne Atexo (prof={prof}), POST "
                      f"{action_url[:80]}")
            time.sleep(DELAI_ENTRE_REQUETES_SEC)
            return _suivre_chaine_atexo(
                session, action_url, dossier,
                prof=prof + 1, max_prof=max_prof,
                form_data=data, verbose=verbose,
            )

        # Pas de form : peut-être que la page contient des liens directs avec extension
        for l in p.liens_documents:
            href_low = l['href'].lower()
            if any(ext in href_low for ext in EXTENSIONS_DOC):
                url_doc = urljoin(url_initiale, l['href'])
                if verbose:
                    print(f"      → chaîne Atexo (prof={prof}), GET lien doc "
                          f"{url_doc[:80]}")
                time.sleep(DELAI_ENTRE_REQUETES_SEC)
                res = _suivre_chaine_atexo(
                    session, url_doc, dossier,
                    prof=prof + 1, max_prof=max_prof, verbose=verbose,
                )
                if res['nb_ok'] > 0:
                    return res

        return {'nb_ok': 0, 'fichiers': [],
                'derniere_raison': 'HTML reçu sans form ni lien document'}

    # Réponse binaire : on écrit sur disque
    nom = _nom_fichier(r.headers, url_initiale) or f'chaine_doc_{prof}.bin'
    nom = _sanitiser_nom(nom)
    if _est_fichier_bruit(nom):
        return {'nb_ok': 0, 'fichiers': [],
                'derniere_raison': f'fichier bruit en bout de chaîne: {nom}'}

    chemin = dossier / nom
    taille = 0
    overflow = False
    with open(chemin, 'wb') as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)
            taille += len(chunk)
            if taille > MAX_TAILLE_FICHIER_MB * 1_000_000:
                overflow = True
                break

    if overflow:
        chemin.unlink(missing_ok=True)
        return {'nb_ok': 0, 'fichiers': [],
                'derniere_raison': f'fichier trop gros (> {MAX_TAILLE_FICHIER_MB} MB)'}

    if verbose:
        print(f"        ✓ {nom} ({taille/1000:.0f} ko) [via chaîne Atexo "
              f"prof={prof}]")
    return {'nb_ok': 1, 'fichiers': [nom], 'derniere_raison': ''}
    return nb_checkbox > 0 and nb_text_visibles == 0


def _data_form(form: dict) -> dict:
    """Construit le dict de soumission POST en pré-remplissant tout."""
    data = {}
    for nom, info in (form.get('champs') or {}).items():
        if info.get('type') == 'checkbox':
            data[nom] = info.get('valeur') or 'on'
        elif info.get('type') == 'submit':
            # On garde le submit pour signaler quel bouton
            data[nom] = info.get('valeur', '')
        else:
            data[nom] = info.get('valeur', '')
    return data


def _nom_fichier(headers: dict, url_fallback: Optional[str] = None) -> Optional[str]:
    """Extrait le nom de fichier depuis Content-Disposition ou l'URL."""
    cd = headers.get('Content-Disposition') or headers.get('content-disposition') or ''
    # filename="X.pdf" ou filename*=UTF-8''X.pdf
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", cd)
    if m:
        return unquote(m.group(1).strip())
    if url_fallback:
        base = os.path.basename(urlparse(url_fallback).path)
        if '.' in base:
            return unquote(base)
    return None


def _sanitiser_nom(nom: str) -> str:
    """Nettoie un nom de fichier pour le système (retire chars invalides)."""
    nom = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', nom)
    nom = nom.strip(' .')
    return nom[:200] or 'document.bin'


# ---------------------------------------------------------------------------
# Téléchargement pour un marché
# ---------------------------------------------------------------------------

def _telecharger_marche(marche: dict, session, force=False,
                          dry_run=False, verbose=False) -> dict:
    """
    Tente de télécharger toutes les pièces d'un marché.

    Returns: dict {statut, nb_fichiers, raison, detail}
    """
    id_m = marche.get('id', '?')
    url_dce = marche.get('url_dce')

    if not url_dce:
        return {'statut': 'pas_url', 'nb_fichiers': 0,
                'raison': "url_dce manquante (lance d'abord tendia_dce.py)"}

    # Normalisation : 3 URLs sur 242 du batch précédent étaient stockées sans
    # schéma (`www.xxx.fr`) et faisaient crasher requests.get avec MissingSchema.
    url_dce = _normaliser_url_dce(url_dce)

    # Filtrage : 3 URLs sur 242 pointaient vers l'espace acheteur (côté agent),
    # totalement inutilisable côté entreprise. On retourne un statut clair
    # plutôt que de perdre du temps à scraper une page de login interne.
    if _est_url_cote_agent(url_dce):
        return {'statut': 'echec', 'nb_fichiers': 0,
                'raison': "url_dce pointe vers espace acheteur (côté agent), inaccessible aux entreprises"}

    dossier = REPERTOIRE_DCE / id_m

    # Skip UNIQUEMENT si le dossier est déjà COMPLET (sauf --force). Un dossier
    # partiel (RC seul, etc.) ne doit PAS court-circuiter le chemin profond
    # ci-dessous, sinon le marché reste éternellement « incomplet » (le batch le
    # saute en voyant le RC, sans jamais déclencher le completeDownload).
    if not force and dossier.is_dir():
        fichiers = (list(dossier.glob('*.pdf')) + list(dossier.glob('*.zip'))
                    + list(dossier.glob('*.doc*')) + list(dossier.glob('*.xls*')))
        if fichiers:
            try:
                import tendia_dce
                deja_complet = tendia_dce.qualifier_dce(str(dossier)).get('qualite') == 'complet'
            except Exception:
                deja_complet = True  # prudence : on ne re-télécharge pas en cas de doute
            if deja_complet:
                return {'statut': 'skip_deja_fait', 'nb_fichiers': len(fichiers),
                        'raison': f"{len(fichiers)} fichiers déjà présents (complet)"}
            # dossier partiel → on poursuit vers le chemin profond pour compléter

    # --- Chemin profond d'abord (fix durable couverture) ----------------------
    # Le parsing HTML rapide ci-dessous n'attrape souvent que le RC (→ dossier
    # « incomplet ») et échoue sur achatpublic (login). Le chemin complet
    # `telecharger_pieces_dce` déclenche le completeDownload Atexo/PLACE, le
    # workflow anonyme achatpublic, etc. → dossier COMPLET en une passe. On le
    # tente en premier pour toutes les plateformes ; s'il ne ramène rien, on
    # laisse la logique HTML rapide tenter le repli (elle reste en dessous).
    #
    # Exception AWS (marches-publics.info) : son workflow ColdFusion+2captcha
    # consomme du proxy et exige un pacing anti-ban → RÉSERVÉ au batch dédié
    # retelecharger_aws_achat_anti_ban.py, jamais dans cette boucle rapide.
    url_l = url_dce.lower()
    if "marches-publics.info" in url_l:
        return {'statut': 'manuel_requis', 'nb_fichiers': 0,
                'raison': "AWS-Achat (marches-publics.info) : réservé au batch "
                          "anti-ban retelecharger_aws_achat_anti_ban.py"}
    if not dry_run:
        try:
            res = telecharger_pieces_dce(marche, str(dossier), session)
            pieces = res.get('pieces_recuperees') or []
            if pieces:
                return {'statut': 'ok', 'nb_fichiers': len(pieces),
                        'raison': f"{len(pieces)} pièces (chemin complet)"}
        except Exception as e:
            if verbose:
                print(f"      chemin complet KO ({type(e).__name__}: {e}), repli HTML")

    # 1. GET page consultation
    if verbose:
        print(f"      GET {url_dce}")
    try:
        r = session.get(url_dce, timeout=TIMEOUT_SEC, allow_redirects=True)
    except requests.RequestException as e:
        return {'statut': 'erreur_reseau', 'nb_fichiers': 0,
                'raison': f'GET échoué : {type(e).__name__}: {e}'}

    if r.status_code == 404:
        return {'statut': 'echec', 'nb_fichiers': 0,
                'raison': 'page consultation introuvable (404)'}
    if r.status_code >= 400:
        return {'statut': 'echec', 'nb_fichiers': 0,
                'raison': f'HTTP {r.status_code}'}

    # 2. Parse
    parser = PagePlaceParser()
    parser.feed(r.text)

    if parser.indicateur_captcha:
        return {'statut': 'manuel_requis', 'nb_fichiers': 0,
                'raison': 'captcha détecté sur la page consultation'}
    if parser.indicateur_login:
        return {'statut': 'manuel_requis', 'nb_fichiers': 0,
                'raison': 'login requis pour accéder au DCE'}

    if verbose:
        print(f"      Titre page : {parser.titre_page[:80]}")
        print(f"      Liens documents : {len(parser.liens_documents)}")
        print(f"      Formulaires     : {len(parser.formulaires)}")

    # 3. Si formulaire de consentement, le soumettre
    form_cgu = next((f for f in parser.formulaires
                     if _est_formulaire_consentement(f)), None)
    if form_cgu:
        if verbose:
            print(f"      → Formulaire consentement détecté, POST automatique")
        action_url = (urljoin(url_dce, form_cgu['action'])
                      if form_cgu['action'] else url_dce)
        data_post = _data_form(form_cgu)
        try:
            time.sleep(DELAI_ENTRE_REQUETES_SEC)
            r2 = session.post(action_url, data=data_post, timeout=TIMEOUT_SEC,
                              allow_redirects=True)
            if r2.status_code == 200:
                p2 = PagePlaceParser()
                p2.feed(r2.text)
                if verbose:
                    print(f"      Après consentement : {len(p2.liens_documents)} nouveaux liens, "
                          f"{len(p2.formulaires)} formulaires")
                parser.liens_documents.extend(p2.liens_documents)
                # Cas où après CGU il y a un autre form (téléchargement zip ?)
                form_dl = next((f for f in p2.formulaires
                                if f.get('method') == 'POST'
                                and any('telecharg' in str(k).lower() or 'download' in str(k).lower()
                                        for k in f.get('champs', {}))), None)
                if form_dl:
                    if verbose:
                        print(f"      → Form téléchargement secondaire détecté")
                    # On considère ce form comme un lien à essayer
                    parser.liens_documents.append({
                        'href': urljoin(url_dce, form_dl.get('action', '')),
                        'libelle': 'form download',
                        'origine': 'form_secondaire',
                        '_form_data': _data_form(form_dl),
                    })
        except requests.RequestException as e:
            if verbose:
                print(f"      ⚠ POST consentement échoué : {e}")

    # 3 bis. Si un formulaire de téléchargement direct est présent (POST avec
    # submit "Téléchargez le RC" etc.), on l'enregistre comme un lien synthétique
    # à essayer. Couvre e-marchespublics et certains profils acheteur.
    forms_dl_direct = [f for f in parser.formulaires
                       if _est_formulaire_telechargement_direct(f)]
    for form_dl in forms_dl_direct:
        action_url = (urljoin(url_dce, form_dl.get('action', ''))
                      if form_dl.get('action') else url_dce)
        parser.liens_documents.append({
            'href': action_url,
            'libelle': 'form téléchargement direct',
            'origine': 'form_dl_direct',
            '_form_data': _data_form(form_dl),
        })
        if verbose:
            print(f"      → Formulaire de téléchargement direct ajouté : {action_url[:80]}")

    # 4. Télécharger
    if not parser.liens_documents:
        return {'statut': 'echec', 'nb_fichiers': 0,
                'raison': "aucun lien document trouvé sur la page "
                          "(structure HTML inattendue ou page partielle)"}

    if dry_run:
        return {'statut': 'dry_run',
                'nb_fichiers': len(parser.liens_documents),
                'raison': f"{len(parser.liens_documents)} documents seraient téléchargés",
                'detail_urls': [l['href'][:100] for l in parser.liens_documents[:10]]}

    dossier.mkdir(parents=True, exist_ok=True)
    nb_ok = 0
    erreurs = []
    seen_hrefs = set()
    liens = [l for l in parser.liens_documents
             if l['href'] not in seen_hrefs and not seen_hrefs.add(l['href'])]

    for i, lien in enumerate(liens, 1):
        url_abs = urljoin(url_dce, lien['href'])
        try:
            time.sleep(DELAI_ENTRE_REQUETES_SEC)
            if '_form_data' in lien:
                r_doc = session.post(url_abs, data=lien['_form_data'],
                                      timeout=TIMEOUT_SEC, stream=True,
                                      allow_redirects=True)
            else:
                r_doc = session.get(url_abs, timeout=TIMEOUT_SEC, stream=True,
                                     allow_redirects=True)

            if r_doc.status_code != 200:
                erreurs.append(f"HTTP {r_doc.status_code} : {url_abs[:60]}")
                continue

            # Skip les réponses HTML (pas un document binaire)
            ctype = (r_doc.headers.get('Content-Type') or '').lower()
            if 'text/html' in ctype and 'application/' not in ctype:
                if verbose:
                    print(f"        ⊘ HTML reçu, pas un document : {url_abs[:80]}")
                continue

            nom = _nom_fichier(r_doc.headers, url_abs) or f"piece_{i:02d}.bin"
            nom = _sanitiser_nom(nom)
            chemin = dossier / nom

            taille = 0
            overflow = False
            with open(chemin, 'wb') as f:
                for chunk in r_doc.iter_content(8192):
                    f.write(chunk)
                    taille += len(chunk)
                    if taille > MAX_TAILLE_FICHIER_MB * 1_000_000:
                        overflow = True
                        break

            if overflow:
                chemin.unlink(missing_ok=True)
                erreurs.append(f"fichier trop gros (> {MAX_TAILLE_FICHIER_MB} MB) : {nom}")
                continue

            nb_ok += 1
            if verbose:
                print(f"        ✓ {nom} ({taille/1000:.0f} ko)")
        except requests.RequestException as e:
            erreurs.append(f"erreur réseau sur {url_abs[:60]} : {e}")

    # Phase 5 — Fallback Atexo : si rien n'a été récupéré via la boucle
    # principale ET qu'il y a des liens pointant vers des pages
    # intermédiaires Atexo (EntrepriseDemandeTelechargementSansIdentification,
    # EntrepriseTelechargementPiece, etc.), on suit la chaîne form→doc.
    # Couvre Maximilien, Ternum-BFC, 596280, adullact, demat-ampa nouveau format.
    if nb_ok == 0:
        liens_chaine = [l for l in liens
                        if _est_url_intermediaire_atexo(l['href'])]
        if liens_chaine and verbose:
            print(f"      → Phase 5 : {len(liens_chaine)} lien(s) "
                  f"intermédiaire(s) Atexo à suivre")
        for lien in liens_chaine:
            url_abs = urljoin(url_dce, lien['href'])
            result = _suivre_chaine_atexo(
                session, url_abs, dossier, verbose=verbose
            )
            if result['nb_ok'] > 0:
                nb_ok = result['nb_ok']
                if verbose:
                    print(f"      ✓ chaîne Atexo réussie ({nb_ok} fichier·s)")
                break
            elif verbose and result.get('derniere_raison'):
                print(f"        ⊘ chaîne Atexo : {result['derniere_raison']}")

    if nb_ok == 0:
        return {'statut': 'echec', 'nb_fichiers': 0,
                'raison': "aucun document téléchargeable (HTML reçu, erreurs réseau, ou structures non gérées)",
                'detail': erreurs[:5]}

    # Détection faux succès : si TOUS les fichiers récupérés sont du bruit
    # générique (guide DEMATIS, DUME seul, CGU), c'est que la plateforme nous
    # a servi sa page d'attente sans débloquer le vrai DCE.
    fichiers_disque = [f.name for f in dossier.iterdir() if f.is_file()]
    fichiers_utiles = [n for n in fichiers_disque if not _est_fichier_bruit(n)]
    if not fichiers_utiles and fichiers_disque:
        # Tout est du bruit -> on nettoie et on rapporte un échec parlant
        for n in fichiers_disque:
            (dossier / n).unlink(missing_ok=True)
        try:
            dossier.rmdir()
        except OSError:
            pass
        if "depot-pli.pdf" in fichiers_disque:
            motif = "faux_succes_depot_pli"
        elif "DUME Acheteur.zip" in fichiers_disque:
            motif = "faux_succes_dume_seul"
        else:
            motif = "faux_succes_cgu_ou_generique"
        return {'statut': 'echec', 'nb_fichiers': 0,
                'raison': f"{motif}: seuls des fichiers génériques rapatriés ({', '.join(fichiers_disque)})"}

    return {'statut': 'ok', 'nb_fichiers': nb_ok,
            'raison': f"{nb_ok} fichiers téléchargés",
            'erreurs_non_critiques': erreurs[:5] if erreurs else []}


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def _charger_marches() -> dict:
    """Charge tous les marchés depuis le stockage (SQLite Sprint 3)."""
    import stockage
    return stockage.charger("marches")


# ===========================================================================
# TÉLÉCHARGEUR PROFOND — récupération de TOUTES les pièces du DCE
# (Sprint Téléchargeur Profond)
# ===========================================================================
#
# Objectif : sur les plateformes ANONYMES, parser la page DCE pour lister toutes
# les pièces (RC, CCAP, CCTP, DPGF, ZIP global...) et les télécharger en
# best-effort, là où le téléchargeur historique s'arrêtait souvent au RC seul.
#
# NOTE IMPORTANTE (scaffolding hors-ligne) : les parseurs spécifiques par
# plateforme partagent pour l'instant la STRATÉGIE GÉNÉRIQUE (suivre tous les
# liens href vers des documents). Ils doivent être spécialisés contre le HTML
# RÉEL une fois le diagnostic (diagnostic_plateformes_dce.py) lancé en ligne —
# certaines plateformes exposent les pièces via boutons JS / POST que href seul
# ne capte pas. Le `_telecharger_marche` historique N'EST PAS rewiré (chemin
# réseau qui marche, non testable hors ligne) : la nouvelle stack est appelée
# par retelecharger_incomplet.py.

_EXTENSIONS_DOC = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip",
                   ".7z", ".rar", ".odt", ".ods", ".rtf")
_HINTS_ZIP_GLOBAL = ["dossier", "tout", "complet", "ensemble",
                     "integralite", "telecharger le dce", "telecharger tout"]


def _pieces_depuis_html(html: str, base_url: str) -> list:
    """
    PUR (testable hors ligne) : extrait les pièces téléchargeables d'une page
    DCE depuis son HTML. Retourne [{nom, url, type_detecte, taille_estimee}].
    type_detecte ∈ {RC, CCAP, CCTP, DPGF, ..., ZIP_GLOBAL, autre}.
    """
    from bs4 import BeautifulSoup
    import tendia_dce
    soup = BeautifulSoup(html or "", "html.parser")
    pieces = []
    vus = set()
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.lower().startswith(("#", "javascript:", "mailto:")):
            continue
        low = href.lower()
        if not any(ext in low for ext in _EXTENSIONS_DOC):
            continue
        url_abs = urljoin(base_url, href)
        if url_abs in vus:
            continue
        vus.add(url_abs)
        texte = (a.get_text() or "").strip()
        nom = unquote(low.rsplit("/", 1)[-1].split("?")[0]) or (texte[:60] or "piece")
        norm_texte = tendia_dce._norm_nom(texte)
        if low.endswith((".zip", ".7z", ".rar")):
            # Un archive = souvent le dossier complet (privilégié en best-effort)
            type_d = "ZIP_GLOBAL"
        else:
            type_d = tendia_dce._type_contractuel(
                tendia_dce._norm_nom(texte + " " + nom)) or "autre"
        pieces.append({"nom": nom, "url": url_abs, "type_detecte": type_d,
                       "taille_estimee": None})
    return pieces


class ParseurDCE:
    """Parseur abstrait : liste exhaustive des pièces d'un DCE."""
    PATTERNS_HOSTS = []

    @classmethod
    def reconnait(cls, url_dce: str) -> bool:
        u = (url_dce or "").lower()
        return any(h in u for h in cls.PATTERNS_HOSTS)

    def lister_pieces(self, session, url_dce: str) -> list:
        raise NotImplementedError


class ParseurGenerique(ParseurDCE):
    """Stratégie par défaut : GET la page + suit tous les liens href documents."""
    PATTERNS_HOSTS = []

    def lister_pieces(self, session, url_dce: str) -> list:
        r = session.get(url_dce, timeout=60)
        if getattr(r, "status_code", 0) != 200:
            return []
        return _pieces_depuis_html(r.text, url_dce)


class ParseurAtexo(ParseurDCE):
    """
    Plateformes Atexo MPE / Prado (PLACE + forks régionaux/municipaux).
    N'utilise PAS le parsing HTML href : délègue à atexo_downloader qui fait les
    2 POST anonymes nécessaires pour récupérer le ZIP DCE complet. La
    reconnaissance s'appuie sur atexo_downloader._detecter_url_base (host connu
    OU signature Atexo orgAcronyme + Entreprise.).
    """
    @classmethod
    def reconnait(cls, url_dce):
        import atexo_downloader
        return atexo_downloader._detecter_url_base(url_dce) is not None

    def lister_pieces(self, session, url_dce):
        # Pas de liste de pièces avant le DL chez Atexo : un seul ZIP global.
        return [{"nom": "DCE_complet.zip", "url": url_dce,
                 "type_detecte": "ZIP_GLOBAL_ATEXO", "taille_estimee": None}]


class ParseurEMarchesPublics(ParseurGenerique):
    """
    Dematis (e-marchespublics.com, wildcard sous-domaines). Moteur distinct
    d'Atexo, workflow à DÉTERMINER empiriquement (diagnostic_emarches.py) —
    stratégie générique en attendant (retourne 0 pièce car href vide).
    """
    PATTERNS_HOSTS = ["e-marchespublics.com"]



class ParseurAchatpublic(ParseurDCE):
    """
    achatpublic.com — workflow anonyme conforme arrêté 14/12/2009.
    N'utilise PAS le parsing HTML : délègue à achatpublic_downloader qui fait
    le GET page détail + POST telechargerDCE.action pour récupérer le ZIP DCE,
    puis décompresse le ZIP imbriqué automatiquement.
    """
    PATTERNS_HOSTS = ["achatpublic.com"]

    def lister_pieces(self, session, url_dce):
        return [{"nom": "DCE_complet.zip", "url": url_dce,
                 "type_detecte": "ZIP_GLOBAL_ACHATPUBLIC",
                 "taille_estimee": None}]


class ParseurAWS(ParseurDCE):
    """
    AWS-Achat / www.marches-publics.info — moteur ColdFusion AW Solutions.
    N'utilise PAS le parsing HTML href : délègue à aws_downloader qui exécute
    le workflow anonyme 7 étapes (session ColdFusion + captcha résolu via
    2captcha + sélection de tous les lots), puis décompresse les ZIP imbriqués.
    """
    PATTERNS_HOSTS = ["marches-publics.info"]

    def lister_pieces(self, session, url_dce):
        return [{"nom": "DCE_multi.zip", "url": url_dce,
                 "type_detecte": "ZIP_GLOBAL_AWS", "taille_estimee": None}]


PARSEURS = [ParseurAtexo, ParseurAchatpublic, ParseurAWS, ParseurEMarchesPublics]


def trouver_parseur(url_dce: str):
    """1er parseur reconnaissant l'URL, sinon générique (hors plateformes auth)."""
    import tendia_dce
    if not url_dce:
        return None
    for cls in PARSEURS:
        if cls.reconnait(url_dce):
            return cls()
    if tendia_dce.url_est_auth_requise(url_dce):
        return None
    return ParseurGenerique()


def _telecharger_avec_retry(session, piece: dict, dossier_destination: str,
                            max_essais: int = 2, timeout: int = 60):
    """
    Télécharge une pièce, max `max_essais` essais, retry après pause sur
    timeout/5xx. Retourne (ok: bool, info: dict).
    """
    os.makedirs(dossier_destination, exist_ok=True)
    derniere = ""
    for essai in range(1, max_essais + 1):
        try:
            r = session.get(piece["url"], timeout=timeout, stream=True)
            code = getattr(r, "status_code", 0)
            if code >= 500:
                derniere = f"HTTP {code}"
                time.sleep(3)
                continue
            if code != 200:
                return False, {"erreur": f"HTTP {code}"}
            nom = _nom_fichier(getattr(r, "headers", {}) or {}, piece["url"]) \
                or piece.get("nom") or f"piece_{essai}.bin"
            chemin = os.path.join(dossier_destination, nom)
            taille = 0
            with open(chemin, "wb") as f:
                for chunk in r.iter_content(8192):
                    if chunk:
                        f.write(chunk)
                        taille += len(chunk)
            if taille == 0:
                derniere = "0 octet"
                continue
            return True, {"nom": nom, "type": piece.get("type_detecte"),
                          "taille": taille, "chemin": chemin}
        except Exception as e:
            derniere = type(e).__name__
            time.sleep(3)
    return False, {"erreur": derniere or "echec"}


def telecharger_pieces_dce(marche: dict, dossier_destination: str, session=None) -> dict:
    """
    Wrapper de priorité d'URL (enrichissement BOAMP v2 — résout B12 en pratique).

    Ordre de tentative :
      1. `url_consultation_dce_directe` (URL directe de consultation + PCSLID issue
         de l'avis BOAMP) — quand présente ;
      2. `url_dce` (reconstruite/scrapée) — en repli si la directe est absente OU
         échoue (aucune pièce récupérée).

    Ajoute `url_utilisee` et `url_source` ('directe'|'reconstruite') au résultat.
    Rétrocompatible : un marché sans `url_consultation_dce_directe` part directement
    sur `url_dce` (comportement historique).
    """
    url_directe = (marche.get("url_consultation_dce_directe") or "").strip()
    url_reconstruite = (marche.get("url_dce") or "").strip()

    tentatives = []
    if url_directe:
        tentatives.append(("directe", url_directe))
    if url_reconstruite and url_reconstruite != url_directe:
        tentatives.append(("reconstruite", url_reconstruite))
    if not tentatives:
        return {"pieces_recuperees": [], "pieces_manquantes": [],
                "raison": "aucune URL DCE (ni directe ni reconstruite)",
                "duree_secondes": 0.0, "url_utilisee": None, "url_source": None}

    dernier = None
    for source, url in tentatives:
        marche_url = {**marche, "url_dce": url}
        res = _telecharger_pieces_dce_impl(marche_url, dossier_destination, session)
        res["url_utilisee"] = url
        res["url_source"] = source
        if res.get("pieces_recuperees"):
            return res  # succès : on s'arrête
        dernier = res  # échec → on tentera le repli (ou on retourne le dernier)
    return dernier


def _telecharger_pieces_dce_impl(marche: dict, dossier_destination: str, session=None) -> dict:
    """
    Récupère toutes les pièces du DCE en best-effort (ZIP global privilégié,
    sinon pièces unitaires). Retourne {pieces_recuperees, pieces_manquantes,
    session_cookies, duree_secondes, raison?}. URL lue dans `marche['url_dce']`
    (surchargée par le wrapper selon la priorité directe/reconstruite).
    """
    debut = datetime.now()
    url_dce = marche.get("url_dce") or ""

    # === DISPATCH DIRECT (fix P1) ===
    # Pour les plateformes à `completeDownload` connu, on appelle le downloader
    # DÉDIÉ sans passer par le parsing HTML (qui ne ramenait que le RC car le parser
    # ne renvoie pas le marqueur ZIP_GLOBAL_* sur ces URL « consultation »).
    def _res_zip(res):
        secs = (datetime.now() - debut).total_seconds()
        if res.get("ok"):
            return {"pieces_recuperees": [{"nom": os.path.basename(res.get("chemin") or "dce.zip"),
                    "type": "ZIP_GLOBAL", "taille": res.get("taille_octets", 0),
                    "chemin": res.get("chemin")}], "pieces_manquantes": [],
                    "duree_secondes": secs, "session_cookies": {}}
        return {"pieces_recuperees": [], "pieces_manquantes": [
                {"nom": "DCE_complet.zip", "url": url_dce, "raison_echec": res.get("erreur", "?")}],
                "duree_secondes": secs}

    if "achatpublic.com" in url_dce and "PCSLID=" in url_dce:
        try:
            import achatpublic_downloader as _ap
            parent = (os.path.dirname(dossier_destination)
                      if os.path.basename(dossier_destination) else dossier_destination)
            return _res_zip(_ap.telecharger_dce_pour_marche({**marche, "url_dce": url_dce},
                                                            parent, verbose=False))
        except Exception as e:
            return {"pieces_recuperees": [], "pieces_manquantes": [],
                    "raison": f"achatpublic échec : {type(e).__name__}: {e}",
                    "duree_secondes": (datetime.now() - debut).total_seconds()}
    try:
        import atexo_downloader as _ad
        base = _ad._detecter_url_base(url_dce)
        if base:
            id_atexo, org = _ad._extraire_id_org_depuis_url(url_dce)
            if id_atexo and org:
                os.makedirs(dossier_destination, exist_ok=True)
                chemin_zip = os.path.join(dossier_destination, f"dce_{id_atexo}.zip")
                return _res_zip(_ad.telecharger_dce(id_atexo, org, chemin_zip, base, verbose=False))
    except Exception:
        pass  # repli sur le parsing générique ci-dessous

    parseur = trouver_parseur(url_dce)
    if not parseur:
        return {"pieces_recuperees": [], "pieces_manquantes": [],
                "raison": "aucun parseur (plateforme auth ou URL absente)",
                "duree_secondes": 0.0}

    session = session or requests.Session()
    try:
        session.headers.update({"User-Agent": USER_AGENT,
                                "Accept-Language": "fr-FR,fr;q=0.9"})
    except Exception:
        pass

    try:
        pieces = parseur.lister_pieces(session, url_dce)
    except Exception as e:
        return {"pieces_recuperees": [], "pieces_manquantes": [],
                "raison": f"listing échoué : {type(e).__name__}: {e}",
                "duree_secondes": (datetime.now() - debut).total_seconds()}

    # Cas Atexo : marqueur ZIP_GLOBAL_ATEXO -> workflow 2-POST atexo_downloader
    # (téléchargement direct du ZIP dans le dossier du marché, pas de href).
    if pieces and pieces[0].get("type_detecte") == "ZIP_GLOBAL_ATEXO":
        import atexo_downloader as _ad
        url_base = _ad._detecter_url_base(url_dce)
        id_atexo, org = _ad._extraire_id_org_depuis_url(url_dce)
        if url_base and id_atexo and org:
            chemin_zip = os.path.join(dossier_destination, f"dce_{id_atexo}.zip")
            res = _ad.telecharger_dce(id_atexo, org, chemin_zip, url_base, verbose=False)
        else:
            res = {"ok": False, "erreur": "id/orgAcronyme/base introuvables dans l'URL",
                   "duree_secondes": 0.0}
        if res.get("ok"):
            recuperees = [{"nom": os.path.basename(res.get("chemin") or "dce.zip"),
                           "type": "ZIP_GLOBAL", "taille": res.get("taille_octets", 0),
                           "chemin": res.get("chemin")}]
            manquantes = []
        else:
            recuperees = []
            manquantes = [{"nom": "DCE_complet.zip", "url": url_dce,
                           "type_detecte": "ZIP_GLOBAL_ATEXO",
                           "raison_echec": res.get("erreur", "?")}]
        return {"pieces_recuperees": recuperees, "pieces_manquantes": manquantes,
                "duree_secondes": res.get("duree_secondes", 0.0), "session_cookies": {}}

    # Cas Achatpublic : marqueur ZIP_GLOBAL_ACHATPUBLIC -> workflow GET+POST
    # achatpublic_downloader (téléchargement direct du ZIP + décompression
    # automatique du ZIP imbriqué).
    if pieces and pieces[0].get("type_detecte") == "ZIP_GLOBAL_ACHATPUBLIC":
        import achatpublic_downloader as _ap
        res = _ap.telecharger_dce_pour_marche(marche, os.path.dirname(dossier_destination)
                                                if os.path.basename(dossier_destination)
                                                else dossier_destination,
                                                verbose=False)
        # _ap retourne {chemin: data/dce/<id>/dce_<pcslid>.zip}
        if res.get("ok"):
            recuperees = [{"nom": os.path.basename(res.get("chemin") or "dce.zip"),
                           "type": "ZIP_GLOBAL",
                           "taille": res.get("taille_octets", 0),
                           "chemin": res.get("chemin")}]
            manquantes = []
        else:
            recuperees = []
            manquantes = [{"nom": "DCE_complet.zip", "url": url_dce,
                           "type_detecte": "ZIP_GLOBAL_ACHATPUBLIC",
                           "raison_echec": res.get("erreur", "?")}]
        return {"pieces_recuperees": recuperees, "pieces_manquantes": manquantes,
                "duree_secondes": res.get("duree_secondes", 0.0),
                "session_cookies": {}}

    # Cas AWS-Achat : marqueur ZIP_GLOBAL_AWS -> workflow ColdFusion 7 étapes
    # (session CFID/CFTOKEN + captcha 2captcha + tous les lots), téléchargement
    # multi-fichiers direct dans le dossier du marché + décompression auto.
    if pieces and pieces[0].get("type_detecte") == "ZIP_GLOBAL_AWS":
        import aws_downloader as _aws
        api_key = os.environ.get("TWOCAPTCHA_API_KEY")
        res = _aws.telecharger_dce_pour_marche(
            marche,
            os.path.dirname(dossier_destination)
            if os.path.basename(dossier_destination) else dossier_destination,
            api_key_2captcha=api_key, verbose=False)
        if res.get("ok"):
            recuperees = [{"nom": os.path.basename(f),
                           "type": "ZIP_GLOBAL" if f.lower().endswith(".zip") else "autre",
                           "taille": 0, "chemin": f}
                          for f in (res.get("fichiers_telecharges") or [])]
            if not recuperees and res.get("skip"):
                recuperees = [{"nom": "DCE_multi", "type": "ZIP_GLOBAL",
                               "taille": res.get("taille_octets", 0),
                               "chemin": res.get("chemin")}]
            manquantes = []
        else:
            recuperees = []
            manquantes = [{"nom": "DCE_multi.zip", "url": url_dce,
                           "type_detecte": "ZIP_GLOBAL_AWS",
                           "raison_echec": res.get("erreur", "?")}]
        return {"pieces_recuperees": recuperees, "pieces_manquantes": manquantes,
                "duree_secondes": res.get("duree_secondes", 0.0),
                "session_cookies": {}}


    zips = [p for p in pieces if p["type_detecte"] == "ZIP_GLOBAL"]
    unitaires = [p for p in pieces if p["type_detecte"] != "ZIP_GLOBAL"]
    recuperees, manquantes = [], []

    # Priorité au ZIP global (1 DL contient tout)
    for zp in zips:
        ok, info = _telecharger_avec_retry(session, zp, dossier_destination)
        if ok:
            recuperees.append(info)
            break
        manquantes.append({**zp, "raison_echec": info.get("erreur", "?")})

    # Sinon, pièces unitaires
    if not recuperees:
        for p in unitaires:
            ok, info = _telecharger_avec_retry(session, p, dossier_destination)
            if ok:
                recuperees.append(info)
            else:
                manquantes.append({**p, "raison_echec": info.get("erreur", "?")})

    cookies = {}
    try:
        cookies = dict(session.cookies)
    except Exception:
        pass
    return {"pieces_recuperees": recuperees, "pieces_manquantes": manquantes,
            "session_cookies": cookies,
            "duree_secondes": (datetime.now() - debut).total_seconds()}


def _sauver_marches(marches: dict):
    """Sauvegarde les marchés en base (SQLite Sprint 3).
    
    Note : avec SQLite, on pourrait faire des updates ciblés via
    stockage.ecrire(id, marche) au lieu de réécrire toute la collection,
    mais sauver() est atomique et reste rapide (transactions).
    """
    import stockage
    stockage.sauver("marches", marches)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Téléchargement automatique des pièces DCE depuis PLACE.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--marche', type=str, default=None,
                        help='Traite un seul marché (par ID).')
    parser.add_argument('--limit', type=int, default=None,
                        help='Max N marchés (utile pour test).')
    parser.add_argument('--force', action='store_true',
                        help='Re-télécharge même si DCE local existe déjà.')
    parser.add_argument('--dry-run', action='store_true',
                        help='Explore les pages sans télécharger.')
    parser.add_argument('--verbose', action='store_true',
                        help='Log HTTP détaillé.')
    args = parser.parse_args()

    print("=" * 70)
    print("  Tendia · Téléchargement DCE depuis PLACE")
    print("=" * 70)
    print()

    marches = _charger_marches()
    print(f"  Marchés en base : {len(marches)}")

    # Filtre la liste à traiter
    if args.marche:
        if args.marche not in marches:
            print(f"  ❌ Marché {args.marche} introuvable.")
            sys.exit(1)
        a_traiter = [args.marche]
    else:
        a_traiter = []
        nb_sans_url = 0
        nb_deja_fait = 0
        for id_m, m in marches.items():
            if not m.get('url_dce'):
                nb_sans_url += 1
                continue
            dossier = REPERTOIRE_DCE / id_m
            if not args.force and dossier.is_dir():
                fichiers = (list(dossier.glob('*.pdf'))
                            + list(dossier.glob('*.zip'))
                            + list(dossier.glob('*.doc*')))
                if fichiers:
                    nb_deja_fait += 1
                    continue
            a_traiter.append(id_m)
        if args.limit:
            a_traiter = a_traiter[:args.limit]
        print(f"    ├─ sans url_dce       : {nb_sans_url}")
        print(f"    ├─ déjà téléchargés   : {nb_deja_fait}  (relance avec --force)")
        print(f"    └─ à traiter ce run   : {len(a_traiter)}")

    if not a_traiter:
        print()
        print("  ✓ Rien à faire.")
        return

    print()
    print("-" * 70)

    # Session HTTP avec cookies persistants
    session = requests.Session()
    session.headers.update({
        'User-Agent': USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.5',
    })

    debut = time.time()
    stats = {'ok': 0, 'manuel_requis': 0, 'echec': 0, 'pas_url': 0,
             'erreur_reseau': 0, 'dry_run': 0, 'skip_deja_fait': 0}

    for i, id_m in enumerate(a_traiter, 1):
        marche = marches[id_m]
        titre = (marche.get('titre') or marche.get('objet') or '?').strip()[:55]
        print(f"  [{i:2d}/{len(a_traiter)}] {id_m}  · {titre}...")

        result = _telecharger_marche(
            marche, session,
            force=args.force, dry_run=args.dry_run, verbose=args.verbose,
        )

        statut = result['statut']
        nb_f = result.get('nb_fichiers', 0)
        raison = result.get('raison', '')
        stats[statut] = stats.get(statut, 0) + 1

        if statut == 'ok':
            print(f"           ✓ {nb_f} fichiers téléchargés")
        elif statut == 'dry_run':
            print(f"           → [dry-run] {raison}")
            if result.get('detail_urls'):
                for u in result['detail_urls'][:3]:
                    print(f"               · {u}")
        elif statut == 'skip_deja_fait':
            print(f"           ⊘ déjà fait ({nb_f} fichiers)")
        elif statut == 'manuel_requis':
            print(f"           ⚠ manuel requis : {raison}")
        else:
            print(f"           ❌ {raison}")
            if args.verbose and result.get('detail'):
                for d in result['detail'][:3]:
                    print(f"               · {d}")

        # Met à jour les marques dans marches.json
        if not args.dry_run:
            marche['dce_telechargement_statut'] = statut
            marche['dce_telechargement_raison'] = raison
            marche['dce_telechargement_date'] = datetime.now(timezone.utc).isoformat()
            marche['dce_telechargement_nb_fichiers'] = nb_f
            # Qualification : pose `dce_contenu` (complet/incomplet/vide) après un
            # téléchargement réussi. Sans ça le batch de base laissait `dce_contenu`
            # à None et les DCE bien récupérés étaient comptés comme non-couverts
            # (dette B15.a). Aligné sur ce que font les `retelecharger_*`.
            if statut in ('ok', 'skip_deja_fait'):
                try:
                    import tendia_dce
                    qual = tendia_dce.qualifier_dce(str(REPERTOIRE_DCE / id_m))
                    marche['dce_contenu'] = qual.get('qualite')
                    marche['dce_pieces_contractuelles'] = qual.get('pieces_contractuelles')
                    marche['dce_raison_contenu'] = qual.get('raison')
                    marche['dce_telecharge_le'] = marche['dce_telechargement_date']
                    if statut == 'ok':
                        print(f"             → qualité : {qual.get('qualite')}")
                except Exception as e:
                    if args.verbose:
                        print(f"             ⚠ qualification échouée : {e}")

    if not args.dry_run:
        _sauver_marches(marches)

    duree = time.time() - debut

    print()
    print("-" * 70)
    print("  Résumé")
    print("-" * 70)
    print(f"    Traités        : {len(a_traiter)}")
    for k, v in stats.items():
        if v > 0:
            print(f"      {k:<18s} : {v}")
    print(f"    Durée          : {duree:.0f} s")
    print()

    if stats.get('manuel_requis', 0) > 0 or stats.get('echec', 0) > 0:
        print("  Pour les marchés en manuel/échec : ouvre l'url_dce dans le navigateur")
        print("  et télécharge à la main dans data\\dce\\<id>\\. Puis :")
        print("    python tendia_extraire.py --marche <id>")
        print()


if __name__ == "__main__":
    main()
