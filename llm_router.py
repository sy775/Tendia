"""
llm_router.py
-------------
Couche d'abstraction des modèles LLM (expérimentation Gemini vs Claude).

    call_llm(task, prompt, documents=None, model=None, system=..., ...) -> LLMResult

- `task`      : "classif" | "analyse" (choisit le modèle par défaut + timeout).
- `prompt`    : texte utilisateur (identique à celui du pipeline Claude).
- `documents` : chemins de fichiers à joindre nativement (PDF). Gemini : upload
                via la Files API ; Claude : blocs `document` base64.
- `model`     : id complet ("gemini-…", "claude-…") ou alias "gemini"/"claude"
                (résolu selon la tâche : GEMINI_MODEL_CLASSIF / GEMINI_MODEL_ANALYSE,
                CLAUDE_MODEL_CLASSIF / CLAUDE_MODEL_ANALYSE).

Configuration :
- .env : GEMINI_API_KEY, GEMINI_MODEL_CLASSIF, GEMINI_MODEL_ANALYSE
         (ANTHROPIC_API_KEY pour Claude, déjà présente).
- config_llm.yaml : tarifs par modèle, rate limits, timeouts, retries.

Le pipeline de production (tendia_classification, llm_extract) N'UTILISE PAS ce
module : il reste strictement inchangé. Seuls les scripts d'expérimentation
(batch_gemini_batiment.py, compare_models.py) passent par ici.

CLI :
    python llm_router.py --lister-modeles      # modèles Gemini disponibles via l'API
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

RACINE = Path(__file__).resolve().parent
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
                if cle and valeur and cle not in os.environ:
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


def estimer_cout_eur(modele: str, tokens_in: int, tokens_out: int) -> Optional[float]:
    """Coût en EUR d'après config_llm.yaml (tokens_out inclut les tokens de réflexion).

    Gère les tarifs par paliers (ex. Gemini Pro : prix plus élevé au-delà de
    `seuil_long_contexte` tokens d'entrée). None si le modèle n'a pas de tarif.
    """
    tarifs = (config().get("tarifs_usd_par_million") or {}).get(modele)
    if not tarifs:
        return None
    long_ctx = tarifs.get("seuil_long_contexte")
    if long_ctx and tokens_in > long_ctx:
        p_in = tarifs.get("input_long", tarifs["input"])
        p_out = tarifs.get("output_long", tarifs["output"])
    else:
        p_in, p_out = tarifs["input"], tarifs["output"]
    usd = (tokens_in * p_in + tokens_out * p_out) / 1_000_000
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


def parser_json(texte: str) -> Optional[dict]:
    """json.loads tolérant : retire les fences markdown, sinon 1er bloc {...},
    puis réparations sûres (_reparer_json)."""
    t = (texte or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*\n", "", t)
        t = re.sub(r"\n```\s*$", "", t)
    m = re.search(r"\{.*\}", t, re.DOTALL)
    candidats = [t] + ([m.group(0)] if m else [])
    for c in candidats + [_reparer_json(x) for x in candidats]:
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
    with _VERROU_RL:
        attente = _DERNIER_APPEL.get(modele, 0.0) + intervalle - time.monotonic()
        if attente > 0:
            time.sleep(attente)
        _DERNIER_APPEL[modele] = time.monotonic()


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


def _avec_retries(fn: Callable, modele: str, res: LLMResult, verbose: bool):
    rc = config().get("retries") or {}
    max_tentatives = int(rc.get("max_tentatives", 5))
    base = float(rc.get("backoff_base_s", 2.0))
    plafond = float(rc.get("backoff_max_s", 90.0))
    derniere = None
    for tentative in range(1, max_tentatives + 1):
        res.tentatives = tentative
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


def _uploader_pdf_gemini(chemin: str, verbose: bool):
    from google.genai import types
    client = _client_gemini()
    f = client.files.upload(file=chemin, config=types.UploadFileConfig(
        mime_type="application/pdf", display_name=Path(chemin).name[:120]))
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
                  budget_tokens_entree: Optional[int] = None, reflexion: Optional[dict] = None) -> None:
    from google.genai import types
    client = _client_gemini()
    fichiers = []
    try:
        for chemin in documents or []:
            if os.path.getsize(chemin) > TAILLE_MAX_PDF_GEMINI:
                raise _ErreurNonRetentable(f"PDF > 50 Mo : {Path(chemin).name}")
            fichiers.append(_avec_retries(lambda c=chemin: _uploader_pdf_gemini(c, verbose),
                                          res.modele, res, verbose))
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
        )
        debut = time.time()
        rep = _avec_retries(lambda: client.models.generate_content(
            model=res.modele, contents=contenus, config=cfg), res.modele, res, verbose)
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
# Backend Claude (SDK anthropic) — pour symétrie ; le pipeline de prod ne l'utilise pas
# ---------------------------------------------------------------------------

def _appel_claude(res: LLMResult, prompt: str, system: Optional[str], documents: list,
                  max_tokens: int, json_mode: bool, timeout_s: int, verbose: bool,
                  budget_tokens_entree: Optional[int] = None, reflexion: Optional[dict] = None) -> None:
    import llm_extract
    llm_extract._check_anthropic()
    from anthropic import Anthropic
    client = Anthropic(timeout=timeout_s, max_retries=0)
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

    def _go():
        with client.messages.stream(model=res.modele, max_tokens=max_tokens,
                                    system=system or "",
                                    messages=[{"role": "user", "content": contenu}], **extra) as s:
            return s.get_final_message()

    debut = time.time()
    msg = _avec_retries(_go, res.modele, res, verbose)
    res.duree_s = round(time.time() - debut, 2)
    res.tokens_in = msg.usage.input_tokens
    res.tokens_out = msg.usage.output_tokens
    res.finish_reason = msg.stop_reason
    res.texte = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    if msg.stop_reason == "refusal":
        # Pas de fallback serveur : la comparaison doit rester sur le modèle demandé.
        det = getattr(msg, "stop_details", None)
        raise _ErreurNonRetentable(f"refus du modèle ({getattr(det, 'category', None)})")


# ---------------------------------------------------------------------------
# Point d'entrée unique
# ---------------------------------------------------------------------------

def call_llm(task: str, prompt: str, documents: Optional[list] = None,
             model: Optional[str] = None, *, system: Optional[str] = None,
             max_tokens: Optional[int] = None, json_mode: bool = True,
             prompt_version: Optional[str] = None,
             budget_tokens_entree: Optional[int] = None,
             journal: Optional[Callable[[LLMResult], None]] = None,
             verbose: bool = False) -> LLMResult:
    """Appelle le modèle choisi et renvoie un LLMResult (jamais d'exception API :
    l'erreur est portée par `res.erreur`, `res.ok=False`).

    Le JSON de la réponse est parsé (`res.json`) avec la même tolérance que le
    pipeline Claude. `budget_tokens_entree` (Gemini + documents) : les derniers PDF sont
    retirés tant que l'entrée dépasse ce nombre de tokens. `journal(res)` est appelé après chaque appel (succès ou échec).
    """
    modele = resoudre_modele(task, model)
    prov = fournisseur(modele)
    tcfg = (config().get("taches") or {}).get(task) or {}
    max_tokens = max_tokens or int(tcfg.get(f"max_tokens_{prov}", tcfg.get("max_tokens", 8000)))
    timeout_s = int(tcfg.get("timeout_s", 120))

    def _tentative(reflexion=None) -> LLMResult:
        res = LLMResult(ok=False, task=task, fournisseur=prov, modele=modele,
                        prompt_version=prompt_version)
        if reflexion:
            res.reflexion = ",".join(f"{k}={v}" for k, v in reflexion.items())
        debut = time.time()
        try:
            backend = _appel_gemini if prov == "gemini" else _appel_claude
            backend(res, prompt, system, documents or [], max_tokens, json_mode, timeout_s, verbose,
                    budget_tokens_entree, reflexion)
            res.cout_eur = estimer_cout_eur(modele, res.tokens_in, res.tokens_out)
            res.sortie_tronquee = (res.finish_reason or "").upper() in ("MAX_TOKENS", "MAX_TOKENS_REACHED")
            if json_mode:
                res.json = parser_json(res.texte)
                if res.json is None:
                    res.erreur = ((f"sortie_tronquee_max_tokens ({res.tokens_out} tokens dont "
                                   f"{res.tokens_reflexion} de réflexion)") if res.sortie_tronquee else
                                  f"reponse_non_json (finish={res.finish_reason}) "
                                  f"début={res.texte[:150]!r} fin={res.texte[-150:]!r}")
            res.ok = res.erreur is None
        except Exception as e:
            res.erreur = f"{type(e).__name__}: {str(e)[:500]}"
            res.duree_s = res.duree_s or round(time.time() - debut, 2)
            res.cout_eur = estimer_cout_eur(modele, res.tokens_in, res.tokens_out) or 0.0
        if verbose:
            etat = "✓" if res.ok else f"✗ {res.erreur}"
            cout = f"{res.cout_eur:.4f} €" if res.cout_eur is not None else "? €"
            print(f"    ← {modele} {res.duree_s:.1f}s · {res.tokens_in}+{res.tokens_out} tok · {cout} {etat}")
        if journal:
            try:
                journal(res)
            except Exception as e:
                print(f"    ⚠ journalisation impossible : {e}")
        return res

    res = _tentative()
    # Gemini arrêté sur la limite de sortie (souvent mangée par la réflexion) : UNE relance avec un
    # budget de réflexion réduit pour laisser la place au JSON. Repli sur thinking_level=LOW si le
    # modèle refuse thinking_budget.
    if prov == "gemini" and res.sortie_tronquee and not res.ok:
        budget = int((config().get("gemini_relance_max_tokens") or {}).get("thinking_budget", 16000))
        # Toujours affiché : l'événement doit être visible même sans --verbose.
        print(f"      ⚠ {modele} : sortie tronquée (MAX_TOKENS, {res.tokens_reflexion} tokens de réflexion) "
              f"→ relance avec thinking_budget={budget}", flush=True)
        r2 = _tentative({"thinking_budget": budget})
        if not r2.ok and r2.erreur and "thinking" in r2.erreur.lower() and not r2.sortie_tronquee:
            r2 = _tentative({"thinking_level": "LOW"})
        r2.relance_reflexion_reduite = True
        if not r2.ok and r2.sortie_tronquee:
            r2.erreur = "sortie_tronquee_max_tokens (après relance à réflexion réduite)"
        res = r2
    return res


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Routeur LLM Claude/Gemini (expérimentation).")
    ap.add_argument("--lister-modeles", action="store_true",
                    help="Liste les modèles Gemini disponibles pour la clé GEMINI_API_KEY.")
    args = ap.parse_args()
    if args.lister_modeles:
        for nom, disp, lim_in, lim_out, actions in sorted(lister_modeles_gemini()):
            if "generateContent" in actions:
                print(f"{nom:<45} {disp or '':<40} in={lim_in} out={lim_out}")
    else:
        ap.print_help()
