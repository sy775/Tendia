"""
tests/test_decp_classifier_llm.py — Lancement : python tests/test_decp_classifier_llm.py
Teste BudgetTracker + parsing/coût/validation SANS appel réseau (faux client).
"""
import os
import sys
import types

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import decp.classifier_llm as cl
from decp.classifier_llm import BudgetTracker, prompt_user, _cout_eur

ok = ko = 0


def check(nom, cond):
    global ok, ko
    if cond:
        ok += 1; print(f"  ✓ {nom}")
    else:
        ko += 1; print(f"  ✗ ÉCHEC {nom}")


# --- Faux client Anthropic ---
def _fake_response(text, tin=400, tout=20):
    usage = types.SimpleNamespace(input_tokens=tin, output_tokens=tout)
    block = types.SimpleNamespace(type="text", text=text)
    return types.SimpleNamespace(usage=usage, content=[block])


class _FakeMessages:
    def __init__(self, text): self._text = text
    def create(self, **kw): return _fake_response(self._text)


class _FakeClient:
    def __init__(self, text): self.messages = _FakeMessages(text)


def _install(text):
    cl._client = _FakeClient(text)


print("BudgetTracker")
t = BudgetTracker(1.0)
check("peut_continuer au départ", t.peut_continuer())
t.ajouter_cout(0.4); t.ajouter_cout(0.4)
check("reste 0.2", abs(t.reste_eur() - 0.2) < 1e-9)
check("nb_appels = 2", t.nb_appels == 2)
t.ajouter_cout(0.3)
check("dépassement → stop", not t.peut_continuer())

print("coût Haiku (1$/5$ ×0.95)")
u = types.SimpleNamespace(input_tokens=1_000_000, output_tokens=0)
check("1M input = 0.95 €", abs(_cout_eur(u) - 0.95) < 1e-6)
u2 = types.SimpleNamespace(input_tokens=0, output_tokens=1_000_000)
check("1M output = 4.75 €", abs(_cout_eur(u2) - 4.75) < 1e-6)

print("prompt_user")
pu = prompt_user({"objet": "Maintenance des serveurs", "cpv_principal": "72514000",
                  "acheteur_nom": "VILLE DE X"})
check("contient objet/CPV/acheteur", "Maintenance" in pu and "72514000" in pu and "VILLE DE X" in pu)

print("classer_llm (faux client)")
_install('{"preset": "it", "confiance": 0.92}')
r = cl.classer_llm({"objet": "logiciel", "cpv_principal": "48000000", "acheteur_nom": "X"})
check("preset it", r["preset"] == "it")
check("confiance 0.92", r["confiance"] == 0.92)
check("coût calculé (>0)", r["cout_eur"] > 0 and r["ok"])

_install('Voici: {"preset": "btp", "confiance": 1.5}')  # JSON noyé + confiance hors borne
r2 = cl.classer_llm({"objet": "x", "cpv_principal": "45", "acheteur_nom": "X"})
check("JSON extrait du bruit", r2["preset"] == "btp")
check("confiance clampée à 1.0", r2["confiance"] == 1.0)

_install('{"preset": "inexistant", "confiance": 0.4}')
r3 = cl.classer_llm({"objet": "x", "cpv_principal": "99", "acheteur_nom": "X"})
check("preset invalide → hors_perimetre", r3["preset"] == "hors_perimetre")

_install("pas du json du tout")
r4 = cl.classer_llm({"objet": "x", "cpv_principal": "99", "acheteur_nom": "X"})
check("JSON absent → hors_perimetre (fallback)", r4["preset"] == "hors_perimetre")

print(f"\n=== {ok} OK / {ko} KO ===")
sys.exit(1 if ko else 0)
