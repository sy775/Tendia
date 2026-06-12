"""
budget.py
---------
Garde-fou budgétaire pour les appels LLM de Tendia.

OBJECTIF
========
Empêcher une explosion accidentelle du coût Anthropic en :
- limitant le nombre d'extractions/calibrations par jour
- alertant quand le coût mensuel cumulé approche d'un seuil
- offrant un kill-switch global ("plus aucun appel LLM jusqu'à nouvel ordre")

CONFIG
======
Le fichier data/budget.json (créé automatiquement avec des valeurs par
défaut conservatrices) :

    {
      "actif": true,
      "extraction_max_par_jour": 100,
      "calibration_max_par_jour": 100,
      "alerte_seuil_eur_mois": 50,
      "kill_switch_global": false,
      "_commentaire": "Édité à la main quand tu veux changer les limites."
    }

Si "kill_switch_global": true, tous les appels LLM sont bloqués (mode
test sans coût). Pratique pour valider l'archi sans payer.
Si "actif": false, les compteurs ne sont pas appliqués (mais le logging
d'appels continue pour audit).

USAGE
=====
    import budget

    # Avant chaque appel LLM
    decision = budget.peut_appeler_llm("extraction", marche_id="M1")
    if not decision.autorise:
        raise budget.BudgetDepasseError(decision.raison)

    # ... appel LLM ...

    # Après l'appel, logger pour audit + compteur
    budget.enregistrer_appel(
        type="extraction",
        marche_id="M1",
        cout_eur=0.42,
        tokens_input=12000,
        tokens_output=3200,
        duree_ms=18000,
        modele="claude-sonnet-4.5",
        statut="ok",
    )

    # Stats / audit
    stats = budget.statistiques_jour()    # dict {extractions: n, cout: x€...}
    stats = budget.statistiques_mois()
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import stockage


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

RACINE = Path(__file__).resolve().parent
FICHIER_BUDGET = RACINE / "data" / "budget.json"

COLLECTION_APPELS = "llm_appels"

# Types d'appels LLM connus (pour validation)
TYPES_VALIDES = {"extraction", "calibration"}

# Valeurs par défaut conservatrices : 100 appels/jour de chaque type,
# alerte mensuelle à 50 €, kill-switch désactivé.
DEFAUT_BUDGET = {
    "actif": True,
    "extraction_max_par_jour": 100,
    "calibration_max_par_jour": 100,
    "alerte_seuil_eur_mois": 50.0,
    "kill_switch_global": False,
    "_commentaire": (
        "Édite ce fichier à la main pour changer les limites. "
        "kill_switch_global=true bloque tous les appels LLM (mode test sans coût). "
        "actif=false désactive les compteurs (les appels sont quand même loggés)."
    ),
}


# ---------------------------------------------------------------------------
# Lecture / écriture config
# ---------------------------------------------------------------------------

def _assurer_fichier_budget() -> dict:
    """Crée data/budget.json avec les valeurs par défaut si absent."""
    if not FICHIER_BUDGET.exists():
        FICHIER_BUDGET.parent.mkdir(parents=True, exist_ok=True)
        with FICHIER_BUDGET.open("w", encoding="utf-8") as f:
            json.dump(DEFAUT_BUDGET, f, ensure_ascii=False, indent=2)
        return dict(DEFAUT_BUDGET)
    try:
        with FICHIER_BUDGET.open("r", encoding="utf-8") as f:
            config = json.load(f)
    except (json.JSONDecodeError, OSError):
        # Fichier corrompu : on retourne les valeurs par défaut sans crasher
        return dict(DEFAUT_BUDGET)

    # Fusionne avec les défauts (clés manquantes = valeurs par défaut)
    fusion = dict(DEFAUT_BUDGET)
    fusion.update(config)
    return fusion


def lire_config() -> dict:
    """Retourne la config budget courante (lit data/budget.json à chaque appel)."""
    return _assurer_fichier_budget()


# ---------------------------------------------------------------------------
# Décision d'autorisation
# ---------------------------------------------------------------------------

@dataclass
class DecisionAppel:
    """Résultat d'une vérification budget."""
    autorise: bool
    raison: str = ""
    compteur_jour: int = 0
    plafond_jour: int = 0


class BudgetDepasseError(RuntimeError):
    """Levée quand un appel LLM est refusé par le garde-fou budget."""


def peut_appeler_llm(type_appel: str,
                       marche_id: Optional[str] = None,
                       preset_code: Optional[str] = None) -> DecisionAppel:
    """
    Vérifie si un appel LLM est autorisé selon la config budget courante.

    Ne consomme PAS le quota — la consommation se fait à enregistrer_appel().
    Cette séparation permet de vérifier avant de lancer l'appel (qui dure
    plusieurs secondes), et de logger après en fonction du résultat réel.
    """
    if type_appel not in TYPES_VALIDES:
        return DecisionAppel(autorise=False,
                              raison=f"Type d'appel inconnu : {type_appel!r}")

    config = lire_config()

    # Kill-switch global
    if config.get("kill_switch_global"):
        return DecisionAppel(
            autorise=False,
            raison="Kill-switch budget activé (kill_switch_global=true). "
                   "Édite data/budget.json pour réactiver.",
        )

    # Si actif=false, on laisse passer sans vérifier les compteurs
    if not config.get("actif", True):
        return DecisionAppel(autorise=True,
                              raison="Compteurs budget désactivés (actif=false)")

    # Compteur du jour pour ce type d'appel
    n_jour = _compter_appels_jour(type_appel)
    plafond = int(config.get(f"{type_appel}_max_par_jour", 100))

    if n_jour >= plafond:
        return DecisionAppel(
            autorise=False,
            raison=(f"Quota quotidien {type_appel} atteint : "
                    f"{n_jour}/{plafond}. Édite data/budget.json pour augmenter, "
                    f"ou attends demain (compteur RAZ à minuit UTC)."),
            compteur_jour=n_jour,
            plafond_jour=plafond,
        )

    return DecisionAppel(autorise=True,
                          compteur_jour=n_jour,
                          plafond_jour=plafond)


# ---------------------------------------------------------------------------
# Logging des appels (table SQLite via stockage K/V)
# ---------------------------------------------------------------------------

def _maintenant_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _jour_iso() -> str:
    """Date du jour au format YYYY-MM-DD (UTC)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _mois_iso() -> str:
    """Mois courant au format YYYY-MM (UTC)."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def enregistrer_appel(type_appel: str,
                        cout_eur: float,
                        statut: str = "ok",
                        marche_id: Optional[str] = None,
                        preset_code: Optional[str] = None,
                        tokens_input: Optional[int] = None,
                        tokens_output: Optional[int] = None,
                        duree_ms: Optional[int] = None,
                        modele: Optional[str] = None,
                        erreur: Optional[str] = None) -> str:
    """
    Enregistre un appel LLM dans la collection 'llm_appels' pour audit
    et calcul des compteurs. Retourne l'id généré de l'appel.

    statut : 'ok' | 'erreur' | 'bloque_budget' | 'no_llm'
    """
    maintenant = _maintenant_iso()
    appel_id = f"{_jour_iso()}-{type_appel}-{os.urandom(4).hex()}"
    entree = {
        "id": appel_id,
        "type": type_appel,
        "marche_id": marche_id,
        "preset_code": preset_code,
        "cout_eur": float(cout_eur) if cout_eur is not None else 0.0,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "duree_ms": duree_ms,
        "modele": modele,
        "statut": statut,
        "erreur": erreur,
        "appele_le": maintenant,
        "jour": _jour_iso(),
        "mois": _mois_iso(),
    }
    stockage.ecrire(COLLECTION_APPELS, appel_id, entree)
    return appel_id


# ---------------------------------------------------------------------------
# Compteurs et statistiques
# ---------------------------------------------------------------------------

def _compter_appels_jour(type_appel: str) -> int:
    """Nombre d'appels d'un type donné dans le jour courant (UTC).
    
    Ne compte que les appels OK (pas les erreurs ni les blocages budget).
    """
    jour = _jour_iso()
    n = 0
    for appel in stockage.charger(COLLECTION_APPELS).values():
        if (appel.get("type") == type_appel
                and appel.get("jour") == jour
                and appel.get("statut") == "ok"):
            n += 1
    return n


def statistiques_jour(jour: Optional[str] = None) -> dict:
    """
    Statistiques pour un jour donné (par défaut aujourd'hui UTC).
    Retourne un dict avec compteurs par type, coût total, statuts.
    """
    if jour is None:
        jour = _jour_iso()

    stats = {
        "jour": jour,
        "extractions_ok": 0,
        "calibrations_ok": 0,
        "erreurs": 0,
        "bloques_budget": 0,
        "cout_total_eur": 0.0,
        "tokens_input_total": 0,
        "tokens_output_total": 0,
    }
    for appel in stockage.charger(COLLECTION_APPELS).values():
        if appel.get("jour") != jour:
            continue
        statut = appel.get("statut")
        type_a = appel.get("type")
        cout = float(appel.get("cout_eur") or 0)
        ti = appel.get("tokens_input") or 0
        to = appel.get("tokens_output") or 0
        stats["cout_total_eur"] += cout
        stats["tokens_input_total"] += ti
        stats["tokens_output_total"] += to
        if statut == "ok":
            if type_a == "extraction":
                stats["extractions_ok"] += 1
            elif type_a == "calibration":
                stats["calibrations_ok"] += 1
        elif statut == "erreur":
            stats["erreurs"] += 1
        elif statut == "bloque_budget":
            stats["bloques_budget"] += 1

    return stats


def statistiques_mois(mois: Optional[str] = None) -> dict:
    """
    Statistiques pour un mois donné (par défaut mois courant UTC, YYYY-MM).
    """
    if mois is None:
        mois = _mois_iso()

    stats = {
        "mois": mois,
        "extractions_ok": 0,
        "calibrations_ok": 0,
        "erreurs": 0,
        "bloques_budget": 0,
        "cout_total_eur": 0.0,
        "tokens_input_total": 0,
        "tokens_output_total": 0,
        "jours_actifs": 0,
    }
    jours_vus = set()
    for appel in stockage.charger(COLLECTION_APPELS).values():
        if appel.get("mois") != mois:
            continue
        jours_vus.add(appel.get("jour"))
        statut = appel.get("statut")
        type_a = appel.get("type")
        cout = float(appel.get("cout_eur") or 0)
        ti = appel.get("tokens_input") or 0
        to = appel.get("tokens_output") or 0
        stats["cout_total_eur"] += cout
        stats["tokens_input_total"] += ti
        stats["tokens_output_total"] += to
        if statut == "ok":
            if type_a == "extraction":
                stats["extractions_ok"] += 1
            elif type_a == "calibration":
                stats["calibrations_ok"] += 1
        elif statut == "erreur":
            stats["erreurs"] += 1
        elif statut == "bloque_budget":
            stats["bloques_budget"] += 1
    stats["jours_actifs"] = len(jours_vus)

    # Alerte si seuil mensuel dépassé
    config = lire_config()
    seuil = float(config.get("alerte_seuil_eur_mois") or 50)
    stats["alerte_active"] = stats["cout_total_eur"] >= seuil
    stats["seuil_alerte"] = seuil

    return stats


# ---------------------------------------------------------------------------
# Estimation de coût (préalable à un appel LLM)
# ---------------------------------------------------------------------------
#
# Tarifs Anthropic Claude Sonnet 4 (à jour mi-2025) :
# - Input  : $3 / 1M tokens
# - Output : $15 / 1M tokens
# Convertit en EUR avec un taux de change conservateur 1 USD = 0.95 EUR.

PRIX_USD_PAR_1M_INPUT = 3.0
PRIX_USD_PAR_1M_OUTPUT = 15.0
TAUX_USD_EUR = 0.95


def estimer_cout_eur(tokens_input: int, tokens_output: int) -> float:
    """Estime le coût d'un appel LLM en euros (Claude Sonnet 4 actuel)."""
    cout_usd = (
        tokens_input * PRIX_USD_PAR_1M_INPUT / 1_000_000
        + tokens_output * PRIX_USD_PAR_1M_OUTPUT / 1_000_000
    )
    return round(cout_usd * TAUX_USD_EUR, 4)


# ---------------------------------------------------------------------------
# Diagnostic CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    config = lire_config()
    print("=== Configuration budget ===")
    for cle in ("actif", "kill_switch_global",
                  "extraction_max_par_jour", "calibration_max_par_jour",
                  "alerte_seuil_eur_mois"):
        print(f"  {cle:30} = {config.get(cle)}")
    print(f"  Fichier de config           : {FICHIER_BUDGET}")
    print()

    stats_j = statistiques_jour()
    print(f"=== Aujourd'hui ({stats_j['jour']}) ===")
    print(f"  Extractions OK              : {stats_j['extractions_ok']}")
    print(f"  Calibrations OK             : {stats_j['calibrations_ok']}")
    print(f"  Erreurs                     : {stats_j['erreurs']}")
    print(f"  Bloqués budget              : {stats_j['bloques_budget']}")
    print(f"  Coût total                  : {stats_j['cout_total_eur']:.2f} €")
    print()

    stats_m = statistiques_mois()
    print(f"=== Mois courant ({stats_m['mois']}) ===")
    print(f"  Extractions OK              : {stats_m['extractions_ok']}")
    print(f"  Calibrations OK             : {stats_m['calibrations_ok']}")
    print(f"  Coût total                  : {stats_m['cout_total_eur']:.2f} € "
          f"(seuil alerte : {stats_m['seuil_alerte']} €)")
    print(f"  Alerte active               : {stats_m['alerte_active']}")
    print(f"  Jours actifs                : {stats_m['jours_actifs']}")
