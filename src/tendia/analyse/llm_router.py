"""
llm_router.py
-------------
Client LLM unique de Tendia (Claude et Gemini).

    call_llm(task, prompt, documents=None, model=None, *, type_appel, marche_id=None,
             system=..., ...) -> LLMResult

- `task`       : "classif" | "analyse" (modèle par défaut, timeout, max_tokens).
- `type_appel` : type budgétaire (budget.TYPES_VALIDES) ; obligatoire.
- `prompt`     : texte utilisateur.
- `documents`  : chemins de PDF à joindre nativement (Gemini : Files API ;
                 Claude : blocs `document` base64).
- `model`      : id complet ("gemini-…", "claude-…") ou alias "gemini"/"claude"
                 (résolu selon la tâche). Un id complet est respecté tel quel.

Garde-fous, appliqués ici pour tous les appelants :
- avant chaque tentative : budget.verifier_kill_switch(type_appel) ;
- après chaque tentative : budget.journaliser_appel (llm_appels), coût compris ;
- tâche "analyse" sans modèle explicite : repli sur `repli.analyse` de
  config_llm.yaml (Sonnet 4.6) si le modèle par défaut échoue, statut « repli ».

Configuration :
- .env : GEMINI_API_KEY, ANTHROPIC_API_KEY, GEMINI_MODEL_CLASSIF, GEMINI_MODEL_ANALYSE.
- config_llm.yaml : modèles par défaut, tarifs (datés), rate limits, timeouts, retries.

CLI :
    python -m tendia.analyse.llm_router --lister-modeles
"""

import base64
import json
import os
import random
import re
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import date as _date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# SSL : même contournement que llm_extract (interception TLS sur ce poste).
try:
    import truststore as _truststore
    _truststore.inject_into_ssl()
except Exception:
    pass

from tendia.core import budget
from tendia.core.chemins import RACINE_DEPOT

RACINE = RACINE_DEPOT
CHEMIN_CONFIG = RACINE / "config_llm.yaml"

TACHES = ("classif", "analyse")


# ---------------------------------------------------------------------------
# Configuration (.env + config_llm.yaml)
# ---------------------------------------------------------------------------

def charger_env() -> None:
    """Charge .env (ou .env.txt, BOM toléré) dans os.environ sans écraser l'existant."""
    for chemin in (RACINE / ".env", RACINE / ".env.txt"):
        if not chemin.is_file():
            continue
        with open(chemin, encoding="utf-8-sig") as f:
            for ligne in f:
                ligne = ligne.strip()
                if not ligne or ligne.startswith("#") or "=" not in ligne:
                    continue
                cle, _, valeur = ligne.partition("=")
                cle = cle.strip()
                valeur = valeur.split(" #")[0].strip().strip('"').strip("'")
                # TENDIA_PROXY_ACTIF ne se lit jamais dans .env (voir core.http_humain)
                if cle and valeur and cle != "TENDIA_PROXY_ACTIF" and cle not in os.environ:
                    os.environ[cle] = valeur
        return


_CONFIG_CACHE: Optional[dict] = None


def config() -> dict:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        import yaml
        with open(CHEMIN_CONFIG, encoding="utf-8") as f:
            _CONFIG_CACHE = yaml.safe_load(f) or {}
    return _CONFIG_CACHE


def resoudre_modele(task: str, model: Optional[str]) -> str:
    """Alias "gemini"/"claude"/None → id complet selon la tâche."""
    if task not in TACHES:
        raise ValueError(f"task inconnue : {task!r} (attendu : {TACHES})")
    charger_env()
    alias = (model or "gemini").strip()
    if alias in ("gemini", "claude"):
        var = f"{alias.upper()}_MODEL_{'CLASSIF' if task == 'classif' else 'ANALYSE'}"
        valeur = os.environ.get(var) or (config().get("modeles_par_defaut") or {}).get(var)
        if not valeur:
            raise RuntimeError(f"{var} non défini (.env ou config_llm.yaml › modeles_par_defaut)")
        return valeur
    return alias


def fournisseur(modele: str) -> str:
    if modele.startswith("gemini"):
        return "gemini"
    if modele.startswith("claude"):
        return "claude"
    raise ValueError(f"Fournisseur inconnu pour le modèle {modele!r}")


def _jour(date=None) -> _date:
    """date, datetime ou chaîne ISO → date ; None → aujourd'hui (UTC)."""
    if date is None:
        return datetime.now(timezone.utc).date()
    if isinstance(date, datetime):
        return date.date()
    if isinstance(date, _date):
        return date
    return _date.fromisoformat(str(date)[:10])


def tarif_usd(modele: str, date=None) -> Optional[dict]:
    """Tarif (USD par million) du modèle à la date de l'appel. `paliers_dates` :
    liste de {a_partir_du: AAAA-MM-JJ, input, output, ...} ; le dernier palier
    dont la date est atteinte remplace les valeurs de base."""
    tarifs = (config().get("tarifs_usd_par_million") or {}).get(modele)
    if not tarifs:
        return None
    effectif = {k: v for k, v in tarifs.items() if k != "paliers_dates"}
    jour = _jour(date)
    for palier in sorted(tarifs.get("paliers_dates") or [], key=lambda p: str(p["a_partir_du"])):
        if jour >= _jour(palier["a_partir_du"]):
            effectif.update({k: v for k, v in palier.items() if k != "a_partir_du"})
    return effectif


def estimer_cout_eur(modele: str, tokens_in: int, tokens_out: int, date=None,
                     tokens_cache_ecriture: int = 0, tokens_cache_lecture: int = 0) -> Optional[float]:
    """Coût en EUR d'après config_llm.yaml (tokens_out inclut les tokens de réflexion),
    au tarif en vigueur à `date` (défaut : aujourd'hui).

    Cache de prompt (Claude) : les tokens écrits et lus en cache sont facturés à part
    (clés `cache_write` / `cache_read` du tarif, à défaut 1,25 × et 0,1 × l'entrée).

    Gère les tarifs par paliers (ex. Gemini Pro : prix plus élevé au-delà de
    `seuil_long_contexte` tokens d'entrée). None si le modèle n'a pas de tarif.
    """
    tarifs = tarif_usd(modele, date)
    if not tarifs:
        return None
    long_ctx = tarifs.get("seuil_long_contexte")
    if long_ctx and tokens_in > long_ctx:
        p_in = tarifs.get("input_long", tarifs["input"])
        p_out = tarifs.get("output_long", tarifs["output"])
    else:
        p_in, p_out = tarifs["input"], tarifs["output"]
    usd = (tokens_in * p_in + tokens_out * p_out
           + (tokens_cache_ecriture or 0) * tarifs.get("cache_write", 1.25 * p_in)
           + (tokens_cache_lecture or 0) * tarifs.get("cache_read", 0.1 * p_in)) / 1_000_000
    return round(usd * float(config().get("taux_usd_eur", 0.92)), 6)


# ---------------------------------------------------------------------------
# Résultat + parsing JSON (même tolérance que le pipeline Claude)
# ---------------------------------------------------------------------------

@dataclass
class LLMResult:
    ok: bool
    task: str
    fournisseur: str
    modele: str
    texte: str = ""
    json: Optional[dict] = None
    tokens_in: int = 0
    tokens_out: int = 0          # tokens générés facturés (réponse + réflexion)
    tokens_reflexion: int = 0    # dont réflexion (Gemini "thinking")
    cout_eur: Optional[float] = None
    duree_s: float = 0.0
    tentatives: int = 0
    erreur: Optional[str] = None
    documents_natifs: list = field(default_factory=list)
    documents_ignores: list = field(default_factory=list)
    prompt_version: Optional[str] = None
    finish_reason: Optional[str] = None
    sortie_tronquee: bool = False          # arrêt sur la limite de tokens de sortie (≠ erreur du modèle)
    relance_reflexion_reduite: bool = False
    reflexion: Optional[str] = None        # réglage de réflexion appliqué (relance), ex. "budget=16000"
    tokens_cache_ecriture: int = 0         # Claude : tokens écrits en cache de prompt
    tokens_cache_lecture: int = 0          # Claude : tokens lus en cache de prompt
    erreur_locale: bool = False            # échec avant tout envoi (clé absente, fichier, PDF trop gros)
    modele_demande: Optional[str] = None   # modèle initial (≠ modele après un repli)
    repli: bool = False                    # True si la réponse vient du modèle de repli
    cout_total_eur: float = 0.0            # somme de toutes les tentatives de cet appel call_llm
    appels: list = field(default_factory=list)   # une entrée par tentative journalisée

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("json", None)
        d.pop("texte", None)
        return d


def _reparer_json(t: str) -> str:
    """Réparations sûres : placeholders `...`/`..` hors chaînes → null / vide,
    virgules finales avant } ou ]."""
    out, dans_chaine, echap = [], False, False
    i = 0
    while i < len(t):
        c = t[i]
        if dans_chaine:
            out.append(c)
            if echap:
                echap = False
            elif c == "\\":
                echap = True
            elif c == '"':
                dans_chaine = False
            i += 1
            continue
        if c == '"':
            dans_chaine = True
            out.append(c)
            i += 1
            continue
        if t.startswith("...", i) or t.startswith("..", i):
            n = 3 if t.startswith("...", i) else 2
            prev = "".join(out).rstrip()[-1:]
            out.append("" if prev == "[" else "null")
            i += n
            continue
        out.append(c)
        i += 1
    r = "".join(out)
    return re.sub(r",\s*([}\]])", r"\1", r)


def parser_json(texte: str, reparer: bool = True) -> Optional[dict]:
    """json.loads tolérant : retire les fences markdown, sinon 1er bloc {...},
    puis réparations sûres (_reparer_json). `reparer=False` : aucune réparation
    (un JSON élidé « ... » ou à virgule finale est rejeté)."""
    t = (texte or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*\n", "", t)
        t = re.sub(r"\n```\s*$", "", t)
    m = re.search(r"\{.*\}", t, re.DOTALL)
    candidats = [t] + ([m.group(0)] if m else [])
    for c in candidats + ([_reparer_json(x) for x in candidats] if reparer else []):
        try:
            v = json.loads(c)
            if isinstance(v, dict):
                return v
        except json.JSONDecodeError:
            continue
    return None


# ---------------------------------------------------------------------------
# Rate limit (intervalle minimal entre appels, par modèle) + retries
# ---------------------------------------------------------------------------

_VERROU_RL = threading.Lock()
_DERNIER_APPEL: dict = {}


def _respecter_rate_limit(modele: str) -> None:
    rpm = ((config().get("rate_limits_rpm") or {}).get(modele)
           or (config().get("rate_limits_rpm") or {}).get("defaut") or 60)
    intervalle = 60.0 / float(rpm)
    # Le créneau est réservé sous verrou, l'attente se fait hors verrou : les threads
    # d'un même modèle s'échelonnent sans se bloquer les uns derrière les autres.
    with _VERROU_RL:
        maintenant = time.monotonic()
        creneau = max(maintenant, _DERNIER_APPEL.get(modele, 0.0) + intervalle)
        _DERNIER_APPEL[modele] = creneau
    if creneau > maintenant:
        time.sleep(creneau - maintenant)


class _ErreurNonRetentable(Exception):
    pass


def _est_retentable(exc: Exception) -> tuple:
    """(retentable, délai_suggéré_s). 429 / 5xx / timeouts / réseau → oui."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    nom = type(exc).__name__
    msg = str(exc)
    delai = None
    m = re.search(r"retry(?:Delay|-after)?['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s?", msg, re.I)
    if m:
        delai = float(m.group(1))
    if code in (408, 409, 429, 500, 502, 503, 504, 529):
        return True, delai
    if any(k in nom for k in ("Timeout", "Connection", "RateLimit", "Overloaded",
                              "InternalServer", "ServerError", "APIConnection")):
        return True, delai
    if any(k in msg.lower() for k in ("timed out", "timeout", "temporarily", "unavailable",
                                      "resource_exhausted", "overloaded", "connection reset")):
        return True, delai
    return False, None


def _avec_retries(fn: Callable, modele: str, res: LLMResult, verbose: bool,
                  generation: bool = False):
    """Rejoue `fn` sur erreur retentable (429, 5xx, timeout, réseau).

    `generation=True` (appel de génération, potentiellement facturé) : avant chaque
    nouvel essai, le garde-fou budget posé par call_llm sur `res` est relu
    (budget.BudgetDepasseError remonte) ; chaque essai échoué qui sera rejoué est
    journalisé (un timeout ou un flux coupé peut avoir été facturé)."""
    avant_essai = getattr(res, "_avant_essai", None) if generation else None
    apres_echec = getattr(res, "_apres_echec", None) if generation else None
    rc = config().get("retries") or {}
    max_tentatives = int(rc.get("max_tentatives", 5))
    base = float(rc.get("backoff_base_s", 2.0))
    plafond = float(rc.get("backoff_max_s", 90.0))
    derniere = None
    for tentative in range(1, max_tentatives + 1):
        res.tentatives = tentative
        if tentative > 1 and avant_essai:
            avant_essai()          # hors du try : BudgetDepasseError n'est pas rejouée
        _respecter_rate_limit(modele)
        try:
            return fn()
        except _ErreurNonRetentable:
            raise
        except Exception as e:
            derniere = e
            retentable, delai = _est_retentable(e)
            if not retentable or tentative >= max_tentatives:
                raise
            if apres_echec:
                apres_echec(e, tentative)
            attente = delai if delai else min(plafond, base * 2 ** (tentative - 1))
            attente += random.uniform(0, attente * 0.25)
            if verbose:
                print(f"    ⚠ {modele} : {type(e).__name__} ({str(e)[:120]}) "
                      f"→ nouvel essai dans {attente:.0f}s ({tentative}/{max_tentatives})")
            time.sleep(attente)
    raise derniere  # pragma: no cover


# ---------------------------------------------------------------------------
# Backend Gemini (SDK google-genai)
# ---------------------------------------------------------------------------

_CLIENT_GEMINI = None
TAILLE_MAX_PDF_GEMINI = 50 * 1024 * 1024   # limite Files API par document PDF


def _client_gemini():
    global _CLIENT_GEMINI
    if _CLIENT_GEMINI is None:
        charger_env()
        cle = os.environ.get("GEMINI_API_KEY")
        if not cle:
            raise _ErreurNonRetentable("GEMINI_API_KEY introuvable (.env)")
        from google import genai
        _CLIENT_GEMINI = genai.Client(api_key=cle)
    return _CLIENT_GEMINI


def lister_modeles_gemini() -> list:
    """[(nom, display_name, input_token_limit, output_token_limit, actions)]."""
    out = []
    for m in _client_gemini().models.list():
        nom = (m.name or "").replace("models/", "")
        out.append((nom, m.display_name, m.input_token_limit, m.output_token_limit,
                    list(m.supported_actions or [])))
    return out


def _nom_ascii(nom: str) -> str:
    """Nom de fichier réduit à l'ASCII : tout ce qui part dans un en-tête HTTP doit l'être."""
    import unicodedata
    ascii_ = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode("ascii")
    return (re.sub(r"[^A-Za-z0-9 ._()-]+", "_", ascii_).strip() or "document.pdf")[:120]


def _uploader_pdf_gemini(chemin: str, verbose: bool):
    from google.genai import types
    client = _client_gemini()
    # Le fichier est envoyé par son contenu, pas par son chemin : le SDK met le nom du fichier
    # dans un en-tête HTTP, et un nom accentué (« prévisionnel.pdf ») y lève UnicodeEncodeError.
    # Copie en mémoire (≤ 50 Mo) : un fichier ouvert expose son nom (accentué) au SDK, qui
    # le met dans un en-tête HTTP ; le BytesIO n'en a pas. Envoi vérifié en réel le 2026-11-11.
    import io
    with open(chemin, "rb") as fh:
        contenu = io.BytesIO(fh.read())
    f = client.files.upload(file=contenu, config=types.UploadFileConfig(
        mime_type="application/pdf", display_name=_nom_ascii(Path(chemin).name)))
    debut = time.time()
    while getattr(f.state, "name", str(f.state)) == "PROCESSING":
        if time.time() - debut > 300:
            raise TimeoutError(f"Traitement du fichier Gemini trop long : {chemin}")
        time.sleep(2)
        f = client.files.get(name=f.name)
    if getattr(f.state, "name", str(f.state)) == "FAILED":
        raise _ErreurNonRetentable(f"Upload Gemini refusé : {Path(chemin).name}")
    if verbose:
        print(f"      ⇪ PDF envoyé à Gemini : {Path(chemin).name}")
    return f


def _appel_gemini(res: LLMResult, prompt: str, system: Optional[str], documents: list,
                  max_tokens: int, json_mode: bool, timeout_s: int, verbose: bool,
                  budget_tokens_entree: Optional[int] = None, reflexion: Optional[dict] = None,
                  options: Optional[dict] = None) -> None:
    from google.genai import types
    client = _client_gemini()
    fichiers = []
    try:
        try:
            for chemin in documents or []:
                if os.path.getsize(chemin) > TAILLE_MAX_PDF_GEMINI:
                    raise _ErreurNonRetentable(f"PDF > 50 Mo : {Path(chemin).name}")
                fichiers.append(_avec_retries(lambda c=chemin: _uploader_pdf_gemini(c, verbose),
                                              res.modele, res, verbose))
        except Exception:
            res._echec_envoi = True     # échec avant la génération : rien n'est facturé
            raise
        noms = [Path(c).name for c in documents or []]

        def _contenus():
            return [types.Part.from_uri(file_uri=f.uri, mime_type="application/pdf")
                    for f in fichiers] + [prompt]

        # Plafond d'entrée (parité avec la troncature texte de la prod) : on retire
        # les dernières pièces tant que le total dépasse. count_tokens est gratuit.
        if budget_tokens_entree and fichiers:
            while True:
                n = _avec_retries(lambda: client.models.count_tokens(
                    model=res.modele, contents=_contenus()), res.modele, res, verbose).total_tokens
                if n <= budget_tokens_entree or len(fichiers) <= 1:
                    break
                retire = fichiers.pop()
                res.documents_ignores.insert(0, noms.pop())
                try:
                    client.files.delete(name=retire.name)
                except Exception:
                    pass
            if verbose and res.documents_ignores:
                print(f"      ✂ {len(res.documents_ignores)} PDF non joints (plafond "
                      f"{budget_tokens_entree} tokens) : {res.documents_ignores}")
        res.documents_natifs = noms
        contenus = _contenus()
        cfg = types.GenerateContentConfig(
            system_instruction=system or None,
            max_output_tokens=max_tokens,
            response_mime_type="application/json" if json_mode else None,
            http_options=types.HttpOptions(timeout=timeout_s * 1000),
            thinking_config=types.ThinkingConfig(**reflexion) if reflexion else None,
            **(options or {}),
        )
        debut = time.time()
        res._generation_lancee = True        # au-delà, l'appel peut être facturé
        rep = _avec_retries(lambda: client.models.generate_content(
            model=res.modele, contents=contenus, config=cfg), res.modele, res, verbose, generation=True)
        res.duree_s = round(time.time() - debut, 2)
        u = rep.usage_metadata
        res.tokens_in = int(getattr(u, "prompt_token_count", 0) or 0)
        res.tokens_reflexion = int(getattr(u, "thoughts_token_count", 0) or 0)
        res.tokens_out = int(getattr(u, "candidates_token_count", 0) or 0) + res.tokens_reflexion
        if rep.candidates:
            fr = rep.candidates[0].finish_reason
            res.finish_reason = getattr(fr, "name", str(fr)) if fr else None
        res.texte = rep.text or ""
    finally:
        for f in fichiers:
            try:
                client.files.delete(name=f.name)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Backend Claude (SDK anthropic)
# ---------------------------------------------------------------------------

_CLIENTS_CLAUDE: dict = {}
_VERROU_CLIENTS = threading.Lock()


def _client_claude(timeout_s: int):
    """Seule instanciation du SDK Anthropic de Tendia (un client par timeout, partagé
    entre threads : le client du SDK est sûr en multi-thread)."""
    with _VERROU_CLIENTS:
        client = _CLIENTS_CLAUDE.get(timeout_s)
        if client is None:
            charger_env()
            try:
                from anthropic import Anthropic
            except ImportError:
                raise _ErreurNonRetentable("SDK anthropic absent (pip install anthropic)")
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise _ErreurNonRetentable("ANTHROPIC_API_KEY introuvable (.env)")
            client = _CLIENTS_CLAUDE[timeout_s] = Anthropic(timeout=timeout_s, max_retries=0)
        return client


def _appel_claude(res: LLMResult, prompt: str, system: Optional[str], documents: list,
                  max_tokens: int, json_mode: bool, timeout_s: int, verbose: bool,
                  budget_tokens_entree: Optional[int] = None, reflexion: Optional[dict] = None,
                  options: Optional[dict] = None) -> None:
    client = _client_claude(timeout_s)
    contenu = []
    for chemin in documents or []:
        with open(chemin, "rb") as f:
            contenu.append({"type": "document", "source": {
                "type": "base64", "media_type": "application/pdf",
                "data": base64.standard_b64encode(f.read()).decode("ascii")}})
    res.documents_natifs = [Path(c).name for c in documents or []]
    contenu.append({"type": "text", "text": prompt})

    extra = {}
    effort = (config().get("effort_claude") or {}).get(res.modele)
    if effort:
        extra["output_config"] = {"effort": effort}
    extra.update(options or {})   # options de l'appelant transmises telles quelles

    def _go():
        with client.messages.stream(model=res.modele, max_tokens=max_tokens,
                                    system=system or "",
                                    messages=[{"role": "user", "content": contenu}], **extra) as s:
            return s.get_final_message()

    debut = time.time()
    res._generation_lancee = True            # au-delà, l'appel peut être facturé
    msg = _avec_retries(_go, res.modele, res, verbose, generation=True)
    res.duree_s = round(time.time() - debut, 2)
    res.tokens_in = msg.usage.input_tokens
    res.tokens_out = msg.usage.output_tokens
    res.tokens_cache_ecriture = int(getattr(msg.usage, "cache_creation_input_tokens", 0) or 0)
    res.tokens_cache_lecture = int(getattr(msg.usage, "cache_read_input_tokens", 0) or 0)
    res.finish_reason = msg.stop_reason
    res.texte = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    if msg.stop_reason == "refusal":
        det = getattr(msg, "stop_details", None)
        raise _ErreurNonRetentable(f"refus du modèle ({getattr(det, 'category', None)})")


# ---------------------------------------------------------------------------
# Point d'entrée unique
# ---------------------------------------------------------------------------

class ErreurLLM(RuntimeError):
    """Échec d'un appel (API, réseau, clé absente). `resultat` porte le LLMResult."""

    def __init__(self, resultat: "LLMResult"):
        super().__init__(resultat.erreur or "échec de l'appel LLM")
        self.resultat = resultat


# Paramètres déjà portés par call_llm : interdits dans `options` (valeur en double au SDK).
OPTIONS_RESERVEES = frozenset({"model", "system", "messages", "max_tokens", "contents", "config",
                               "max_output_tokens", "system_instruction", "response_mime_type",
                               "thinking_config", "http_options"})

RAPPEL_JSON = ("\n\nATTENTION : ta réponse précédente n'était pas un JSON "
               "valide. Renvoie UNIQUEMENT un objet JSON strictement valide.")


def modele_repli(task: str) -> Optional[str]:
    """Modèle de repli de la tâche (config_llm.yaml › repli), ou None."""
    return (config().get("repli") or {}).get(task)


def _journaliser(res: LLMResult, type_appel: str, marche_id: Optional[str], statut: str,
                 enveloppe: Optional[str] = None, extra_journal: Optional[dict] = None) -> None:
    """Une entrée llm_appels par tentative (ne lève jamais : budget.journaliser_appel)."""
    extra = {k: v for k, v in (("task", res.task), ("prompt_version", res.prompt_version),
                               ("tokens_reflexion", res.tokens_reflexion or None),
                               ("reflexion", res.reflexion), ("finish_reason", res.finish_reason),
                               ("tokens_cache_ecriture", res.tokens_cache_ecriture or None),
                               ("tokens_cache_lecture", res.tokens_cache_lecture or None))
             if v}
    extra.update(extra_journal or {})
    budget.journaliser_appel(
        type_appel, res.cout_eur or 0.0, statut=statut, marche_id=marche_id,
        tokens_input=res.tokens_in, tokens_output=res.tokens_out,
        duree_ms=int((res.duree_s or 0) * 1000), modele=res.modele,
        erreur=(res.erreur or None) and res.erreur[:300], enveloppe=enveloppe,
        extra=extra or None)


def call_llm(task: str, prompt: str, documents: Optional[list] = None,
             model: Optional[str] = None, *, type_appel: str,
             marche_id: Optional[str] = None, system=None,
             max_tokens: Optional[int] = None, json_mode: bool = True,
             relance_json: Optional[bool] = None, json_strict: bool = False,
             options: Optional[dict] = None, prompt_version: Optional[str] = None,
             budget_tokens_entree: Optional[int] = None,
             enveloppe: Optional[str] = None, extra_journal: Optional[dict] = None,
             verbose: bool = False) -> LLMResult:
    """Appelle le modèle choisi et renvoie un LLMResult (jamais d'exception API :
    l'erreur est portée par `res.erreur`, `res.ok=False`).

    Budget : `budget.verifier_kill_switch(type_appel)` avant chaque tentative (lève
    budget.BudgetDepasseError) ; chaque tentative est journalisée dans llm_appels
    (« ok », « erreur », ou « repli » pour l'appel de repli). `res.cout_total_eur`
    cumule toutes les tentatives, `res.appels` les détaille.

    `json_mode` : la réponse est parsée (`res.json`) ; si elle n'est pas un objet
    JSON, une relance avec rappel de format quand `relance_json` (défaut : oui pour
    "analyse", non pour "classif"). `json_strict` : aucune réparation du JSON (une réponse
    élidée ou tronquée est rejetée au lieu d'être complétée par des null). `options` : paramètres du fournisseur transmis
    tels quels (température…) ; `system` peut être une liste de blocs (cache de prompt).
    `budget_tokens_entree` (Gemini + documents) : les derniers PDF sont retirés tant
    que l'entrée dépasse ce nombre de tokens. `enveloppe` et `extra_journal` sont
    recopiés dans l'entrée llm_appels (enveloppes de sprint, métadonnées de l'appelant).

    Repli : tâche avec `repli.<task>` dans config_llm.yaml et modèle non explicite
    (None ou alias) ; si le modèle par défaut finit en échec (hors erreur locale), un
    appel au modèle de repli, sans les `options` si le fournisseur change. `res.modele`
    est le modèle réellement utilisé.

    Lève ValueError avant tout appel : type_appel inconnu, modèle sans tarif, clé
    réservée dans `options`.

    Multi-thread : sûr (une entrée llm_appels par tentative). Le plafond mensuel est
    relu avant chaque tentative sans réservation : avec N threads, il peut être
    dépassé d'au plus N − 1 appels en cours.
    """
    if type_appel not in budget.TYPES_VALIDES:
        raise ValueError(f"type_appel inconnu : {type_appel!r} (attendu : {sorted(budget.TYPES_VALIDES)})")
    reservees = set(options or {}) & OPTIONS_RESERVEES
    if reservees:
        raise ValueError(f"options réservées (paramètres de call_llm) : {sorted(reservees)}")
    modele_explicite = model is not None and model.strip() not in ("gemini", "claude")
    modele_initial = resoudre_modele(task, model)
    repli = None if modele_explicite else modele_repli(task)
    if repli == modele_initial:
        repli = None
    # Un modèle sans tarif serait journalisé à 0 € : le plafond mensuel ne le verrait pas.
    for m in (modele_initial, repli):
        if m and tarif_usd(m) is None:
            raise ValueError(f"modèle sans tarif dans config_llm.yaml › tarifs_usd_par_million : {m!r}")
    tcfg = (config().get("taches") or {}).get(task) or {}
    timeout_s = int(tcfg.get("timeout_s", 120))
    if relance_json is None:
        relance_json = task == "analyse"
    historique = []

    def _tentative(modele: str, texte_prompt: str, reflexion=None, statut_force=None) -> LLMResult:
        budget.verifier_kill_switch(type_appel)
        prov = fournisseur(modele)
        plafond_sortie = max_tokens or int(tcfg.get(f"max_tokens_{prov}", tcfg.get("max_tokens", 8000)))
        res = LLMResult(ok=False, task=task, fournisseur=prov, modele=modele,
                        prompt_version=prompt_version, modele_demande=modele_initial)
        if reflexion:
            res.reflexion = ",".join(f"{k}={v}" for k, v in reflexion.items())
        debut = time.time()

        def _cout() -> float:
            return estimer_cout_eur(modele, res.tokens_in, res.tokens_out,
                                    tokens_cache_ecriture=res.tokens_cache_ecriture,
                                    tokens_cache_lecture=res.tokens_cache_lecture) or 0.0

        def _essai_echoue(exc: Exception, essai: int) -> None:
            """Essai interne échoué puis rejoué (_avec_retries) : journalisé à part."""
            echec = LLMResult(ok=False, task=task, fournisseur=prov, modele=modele,
                              prompt_version=prompt_version, cout_eur=0.0,
                              erreur=f"{type(exc).__name__}: {str(exc)[:300]}",
                              duree_s=round(time.time() - debut, 2))
            _journaliser(echec, type_appel, marche_id, "erreur", enveloppe,
                         {**(extra_journal or {}), "essai_interne": essai})
            historique.append({"modele": modele, "statut": "erreur", "cout_eur": 0.0, "tokens_in": 0,
                               "tokens_out": 0, "duree_s": echec.duree_s, "erreur": echec.erreur})

        # Crochets lus par _avec_retries (attributs hors dataclass : absents de to_dict).
        res._avant_essai = lambda: budget.verifier_kill_switch(type_appel)
        res._apres_echec = _essai_echoue
        # Les options sont propres à un fournisseur : elles ne suivent pas un repli vers l'autre.
        options_backend = options if prov == fournisseur(modele_initial) else None
        try:
            backend = _appel_gemini if prov == "gemini" else _appel_claude
            backend(res, texte_prompt, system, documents or [], plafond_sortie, json_mode, timeout_s,
                    verbose, budget_tokens_entree, reflexion, options_backend)
            res.cout_eur = _cout()
            res.sortie_tronquee = (res.finish_reason or "").upper() in ("MAX_TOKENS", "MAX_TOKENS_REACHED")
            if json_mode:
                res.json = parser_json(res.texte, reparer=not json_strict)
                if res.json is None:
                    res.erreur = ((f"sortie_tronquee_max_tokens ({res.tokens_out} tokens dont "
                                   f"{res.tokens_reflexion} de réflexion)") if res.sortie_tronquee else
                                  f"reponse_non_json (finish={res.finish_reason}) "
                                  f"début={res.texte[:150]!r} fin={res.texte[-150:]!r}")
            res.ok = res.erreur is None
        except budget.BudgetDepasseError:
            raise      # garde-fou relu entre deux essais internes : les essais échoués sont déjà journalisés
        except Exception as e:
            res.erreur = f"{type(e).__name__}: {str(e)[:500]}"
            # Erreur avant tout appel de génération (clé absente, fichier illisible, envoi du
            # PDF refusé, nom de fichier non encodable…) : rien n'a été facturé, et le même
            # document ferait échouer le repli, ou le paierait pour rien.
            res.erreur_locale = (not res.tokens_in
                                 and (isinstance(e, (_ErreurNonRetentable, OSError, UnicodeError))
                                      or getattr(res, "_echec_envoi", False)))
            res.cout_eur = _cout()
        except BaseException as e:
            # Interruption (Ctrl+C) pendant l'appel : la requête a pu être facturée.
            res.erreur = f"interrompu ({type(e).__name__})"
            res.cout_eur = _cout()
            res.duree_s = res.duree_s or round(time.time() - debut, 2)
            _journaliser(res, type_appel, marche_id, "erreur", enveloppe, extra_journal)
            raise
        res.duree_s = res.duree_s or round(time.time() - debut, 2)
        if verbose:
            etat = "✓" if res.ok else f"✗ {res.erreur}"
            cout = f"{res.cout_eur:.4f} €" if res.cout_eur is not None else "? €"
            print(f"    ← {modele} {res.duree_s:.1f}s · {res.tokens_in}+{res.tokens_out} tok · {cout} {etat}")
        statut = statut_force or ("ok" if res.ok else "erreur")
        _journaliser(res, type_appel, marche_id, statut, enveloppe, extra_journal)
        historique.append({"modele": modele, "statut": statut, "cout_eur": res.cout_eur or 0.0,
                           "tokens_in": res.tokens_in, "tokens_out": res.tokens_out,
                           "duree_s": res.duree_s, "erreur": res.erreur})
        return res

    def _serie(modele: str, statut_force=None) -> LLMResult:
        """Une tentative, puis au plus une relance MAX_TOKENS (Gemini) ou une relance JSON."""
        res = _tentative(modele, prompt, statut_force=statut_force)
        # Gemini arrêté sur la limite de sortie (souvent mangée par la réflexion) : UNE relance avec un
        # budget de réflexion réduit pour laisser la place au JSON. Repli sur thinking_level=LOW si le
        # modèle refuse thinking_budget.
        if fournisseur(modele) == "gemini" and res.sortie_tronquee and not res.ok:
            budget_reflexion = int((config().get("gemini_relance_max_tokens") or {}).get("thinking_budget", 16000))
            # Toujours affiché : l'événement doit être visible même sans --verbose.
            print(f"      ⚠ {modele} : sortie tronquée (MAX_TOKENS, {res.tokens_reflexion} tokens de réflexion) "
                  f"→ relance avec thinking_budget={budget_reflexion}", flush=True)
            r2 = _tentative(modele, prompt, {"thinking_budget": budget_reflexion}, statut_force)
            if not r2.ok and r2.erreur and "thinking" in r2.erreur.lower() and not r2.sortie_tronquee:
                r2 = _tentative(modele, prompt, {"thinking_level": "LOW"}, statut_force)
            r2.relance_reflexion_reduite = True
            if not r2.ok and r2.sortie_tronquee:
                r2.erreur = "sortie_tronquee_max_tokens (après relance à réflexion réduite)"
            res = r2
        elif (json_mode and relance_json and not res.ok
              and (res.erreur or "").startswith("reponse_non_json")):
            res = _tentative(modele, prompt + RAPPEL_JSON, statut_force=statut_force)
        return res

    res = _serie(modele_initial)
    # Pas de repli payant sur une erreur locale (clé absente, fichier introuvable, PDF trop gros).
    if not res.ok and repli and not res.erreur_locale:
        print(f"      ⚠ {modele_initial} en échec ({(res.erreur or '')[:80]}) → repli sur {repli}", flush=True)
        # UN seul appel de repli : ni relance JSON ni relance MAX_TOKENS.
        res = _tentative(repli, prompt, statut_force="repli")
        res.repli = True
    res.appels = historique
    res.cout_total_eur = round(sum(a["cout_eur"] for a in historique), 6)
    return res


def appeler_modele(task: str, prompt: str, *, model: str, type_appel: str,
                   marche_id: Optional[str] = None, system=None,
                   max_tokens: Optional[int] = None, json_mode: bool = False,
                   json_strict: bool = True,
                   options: Optional[dict] = None, enveloppe: Optional[str] = None,
                   extra_journal: Optional[dict] = None, verbose: bool = False) -> LLMResult:
    """call_llm pour les modules qui gardent leur modèle et leur propre boucle de
    relance : modèle explicite (donc ni repli ni changement de modèle), aucune relance
    JSON dans le routeur. Lève ErreurLLM si l'appel lui-même échoue (API, réseau, clé) ;
    une réponse reçue mais non JSON (json_mode=True) est rendue avec res.json = None,
    sans réparation du JSON par défaut (json_strict), comme le faisaient ces modules.
    budget.BudgetDepasseError remonte telle quelle."""
    res = call_llm(task, prompt, model=model, type_appel=type_appel, marche_id=marche_id,
                   system=system, max_tokens=max_tokens, json_mode=json_mode,
                   relance_json=False, json_strict=json_strict, options=options, enveloppe=enveloppe,
                   extra_journal=extra_journal, verbose=verbose)
    if not res.ok and not (res.erreur or "").startswith(("reponse_non_json", "sortie_tronquee")):
        raise ErreurLLM(res)
    return res


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Routeur LLM Claude/Gemini.")
    ap.add_argument("--lister-modeles", action="store_true",
                    help="Liste les modèles Gemini disponibles pour la clé GEMINI_API_KEY.")
    args = ap.parse_args()
    if args.lister_modeles:
        for nom, disp, lim_in, lim_out, actions in sorted(lister_modeles_gemini()):
            if "generateContent" in actions:
                print(f"{nom:<45} {disp or '':<40} in={lim_in} out={lim_out}")
    else:
        ap.print_help()
