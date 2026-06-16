"""
decp/classifier_llm.py — classification niveau 2 (LLM Haiku 4.5), Sprint DECP 2.

Classe les marchés DECP ambigus/inconnus (preset_principal NULL après niveau 1)
avec Claude Haiku 4.5. Budget tracker thread-safe + arrêt net à 50 €.

Tarif Haiku 4.5 : 1 $/1M input, 5 $/1M output (×0.95 €/$). ~430 tok/marché ⇒ ~0,0005 €.
"""
import hashlib
import json
import os
import re
import threading
import time

import truststore
truststore.inject_into_ssl()  # SSL Windows (convention Tendia)
from anthropic import Anthropic

MODELE = "claude-haiku-4-5"
PRIX_IN_USD_1M = 1.0
PRIX_OUT_USD_1M = 5.0
TAUX_USD_EUR = 0.95
PRESETS_VALIDES = {"btp", "it", "ingenierie", "conseil_rd", "formation", "enr", "hors_perimetre"}

PROMPT_SYSTEME = (
    "Tu es un classificateur de marchés publics français. Tu reçois l'objet d'un "
    "marché et son code CPV, et tu dois retourner UN SEUL preset parmi :\n\n"
    "- btp : travaux de construction, bâtiment, génie civil, voirie, VRD, second œuvre\n"
    "- it : informatique, logiciel, infrastructure IT, télécoms, cybersécurité, équipements IT\n"
    "- ingenierie : architecture, maîtrise d'œuvre, AMO bâtiment/aménagement, études "
    "techniques (thermiques, environnementales, géotechniques, structures, fluides), "
    "programmation technique de projet, audits techniques, géomètre, topographie, "
    "ingénierie environnementale\n"
    "- conseil_rd : conseil stratégique, conseil juridique, audit organisationnel, "
    "évaluation de politiques publiques, études de marché, études socio-économiques, "
    "R&D scientifique, AMO juridique/financière (pas technique)\n"
    "- formation : formation professionnelle, enseignement, certification, écoles de conduite\n"
    "- enr : travaux, études, AMO et maintenance d'installations d'énergies renouvelables "
    "(solaire, éolien, biomasse, géothermie). NE PAS inclure les marchés de fourniture pure "
    "d'énergie (même verte) — ceux-là sont hors_perimetre.\n"
    "- hors_perimetre : tout le reste (transport, alimentation, mobilier, services généraux, "
    "événementiel, fourniture d'énergie/carburant, sécurité/gardiennage, maintenance "
    "non-spécialisée...)\n\n"
    "DISTINCTION CRITIQUE ingenierie vs conseil_rd :\n"
    "- \"Étude technique\" (thermique, environnement, structure, fluides, géotechnique, etc.) → ingenierie\n"
    "- \"Programme technique et fonctionnel\" / \"AMO programmation\" projet bâtiment → ingenierie\n"
    "- \"Étude PPRN / aléa naturel\" → ingenierie (étude technique environnement)\n"
    "- \"Conseil stratégique / d'organisation\" → conseil_rd\n"
    "- \"Évaluation politique publique\" → conseil_rd\n"
    "- \"Étude de marché / socio-économique\" → conseil_rd\n"
    "- \"AMO juridique / financière\" → conseil_rd\n"
    "- \"AMO Foncier\" → conseil_rd (conseils juridiques foncier)\n"
    "- \"Mission de conseil et accompagnement stratégique\" → conseil_rd\n\n"
    'Réponds STRICTEMENT en JSON :\n{"preset": "<un_des_codes_ci_dessus>", "confiance": <0.0-1.0>}\n\n'
    "Pas de prose, pas d'explication, juste le JSON."
)

# Version du prompt (traçabilité re-classification — cf. Chantier 1E).
PROMPT_VERSION = hashlib.sha256(PROMPT_SYSTEME.encode("utf-8")).hexdigest()[:12]

_client = None
_client_lock = threading.Lock()


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                if not os.environ.get("ANTHROPIC_API_KEY"):
                    import llm_extract
                    k = llm_extract._charger_cle_depuis_env_file()
                    if k:
                        os.environ["ANTHROPIC_API_KEY"] = k
                _client = Anthropic()
    return _client


def prompt_user(marche: dict) -> str:
    return (f"Objet : {(marche.get('objet') or '')[:600]}\n"
            f"CPV : {marche.get('cpv_principal') or '—'}\n"
            f"Acheteur : {marche.get('acheteur_nom') or '—'}")


def _cout_eur(usage) -> float:
    return round((usage.input_tokens * PRIX_IN_USD_1M
                 + usage.output_tokens * PRIX_OUT_USD_1M) / 1_000_000 * TAUX_USD_EUR, 6)


def classer_llm(marche: dict, retries: int = 2) -> dict:
    """Retourne {preset, confiance, cout_eur, ok, erreur}."""
    client = _get_client()
    derniere = None
    for tentative in range(1, retries + 1):
        try:
            rep = client.messages.create(
                model=MODELE, max_tokens=50, system=PROMPT_SYSTEME,
                messages=[{"role": "user", "content": prompt_user(marche)}])
            cout = _cout_eur(rep.usage)
            txt = "".join(b.text for b in rep.content if getattr(b, "type", "") == "text")
            m = re.search(r"\{.*\}", txt, re.S)
            data = json.loads(m.group(0)) if m else {}
            preset = str(data.get("preset") or "").strip()
            if preset not in PRESETS_VALIDES:
                preset = "hors_perimetre"
            try:
                conf = float(data.get("confiance"))
            except (TypeError, ValueError):
                conf = 0.5
            return {"preset": preset, "confiance": max(0.0, min(1.0, conf)),
                    "cout_eur": cout, "ok": True, "erreur": None}
        except Exception as e:
            derniere = e
            if tentative < retries:
                time.sleep(1.0 * tentative)
    return {"preset": None, "confiance": None, "cout_eur": 0.0, "ok": False,
            "erreur": f"{type(derniere).__name__}: {derniere}"}


class BudgetTracker:
    def __init__(self, plafond_eur: float):
        self.plafond_eur = plafond_eur
        self.consomme_eur = 0.0
        self.nb_appels = 0
        self.start_time = time.time()
        self._lock = threading.Lock()

    def peut_continuer(self) -> bool:
        with self._lock:
            return self.consomme_eur < self.plafond_eur

    def ajouter_cout(self, cout_eur: float):
        with self._lock:
            self.consomme_eur += cout_eur
            self.nb_appels += 1

    def reste_eur(self) -> float:
        with self._lock:
            return max(0.0, self.plafond_eur - self.consomme_eur)

    def log(self):
        dt = (time.time() - self.start_time) / 60
        moy = self.consomme_eur / self.nb_appels if self.nb_appels else 0
        print(f"  budget {self.consomme_eur:.3f}/{self.plafond_eur:.0f} € | "
              f"{self.nb_appels} appels | moy {moy:.5f} €/marché | {dt:.1f} min")
