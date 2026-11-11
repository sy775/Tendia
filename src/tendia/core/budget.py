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
    from tendia.core import budget

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
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from tendia.core import stockage


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

from tendia.core.chemins import DATA, RACINE_DEPOT

RACINE = RACINE_DEPOT
FICHIER_BUDGET = DATA / "budget.json"

COLLECTION_APPELS = "llm_appels"

# Types d'appels LLM connus (pour validation). Sprint DECP-R : tous les appels LLM
# de Tendia ont un type (classification, decp, memoire, digest en plus).
TYPES_VALIDES = {"extraction", "calibration", "classification", "decp", "memoire", "digest"}

# Valeurs par défaut conservatrices : 100 appels/jour de chaque type,
# alerte mensuelle à 50 €, kill-switch désactivé.
DEFAUT_BUDGET = {
    "actif": True,
    "extraction_max_par_jour": 100,
    "calibration_max_par_jour": 100,
    "classification_max_par_jour": 2000,
    "decp_max_par_jour": 20000,
    "memoire_max_par_jour": 50,
    "digest_max_par_jour": 50,
    "alerte_seuil_eur_mois": 50.0,
    # Plafond DUR mensuel (tous types journalisés dans llm_appels) : au-delà, tout appel
    # est refusé (décision Younes, Sprint DECP-R : 100 €/mois, alerte à 50 €).
    "plafond_global_eur_mois": 100.0,
    # Enveloppes de sprint (plafond dur sur les appels taggés de l'enveloppe).
    "enveloppes": {"decp_reprise": {"total_eur": 10.0, "claude_eur": 1.0},
                   "decp_hebdo": {"total_eur": 2.0, "claude_eur": 0.0, "mensuel": True}},
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

    # Plafond dur mensuel global (appliqué même si actif=false : c'est un garde-fou)
    plafond_mois = config.get("plafond_global_eur_mois")
    if plafond_mois is not None:
        cout_mois = _cout_mois()
        if cout_mois >= float(plafond_mois):
            return DecisionAppel(
                autorise=False,
                raison=(f"Plafond mensuel global atteint : {cout_mois:.2f} € ≥ "
                        f"{float(plafond_mois):.2f} € (plafond_global_eur_mois)."))

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


def verifier_kill_switch(type_appel: str) -> None:
    """Garde minimale à placer AVANT tout appel LLM qui ne passe pas par
    peut_appeler_llm (classification, calibration, mémoires, digest) :
        from tendia.core import budget
        budget.verifier_kill_switch("memoire")
    Lève BudgetDepasseError si kill_switch_global=true ou si le plafond mensuel global
    est atteint. Ne consomme aucun quota (ces appels ne sont pas comptés par jour)."""
    config = lire_config()
    if config.get("kill_switch_global"):
        raise BudgetDepasseError(
            f"Appel LLM « {type_appel} » bloqué : kill_switch_global=true (data/budget.json).")
    plafond_mois = config.get("plafond_global_eur_mois")
    if plafond_mois is not None and _cout_mois() >= float(plafond_mois):
        raise BudgetDepasseError(
            f"Appel LLM « {type_appel} » bloqué : plafond mensuel global "
            f"{float(plafond_mois):.2f} € atteint.")


def _cout_mois(mois: Optional[str] = None) -> float:
    mois = mois or _mois_iso()
    return sum(float(a.get("cout_eur") or 0) for a in stockage.charger(COLLECTION_APPELS).values()
               if a.get("mois") == mois)


def depense_enveloppe(enveloppe: str) -> dict:
    """Dépense d'une enveloppe : {total_eur, claude_eur, n}. Cumulée, ou limitée au mois
    courant si l'enveloppe est déclarée "mensuel": true (ex. mise à jour hebdomadaire DECP)."""
    env = (lire_config().get("enveloppes") or {}).get(enveloppe) or {}
    mois = _mois_iso() if env.get("mensuel") else None
    tot = claude = 0.0
    n = 0
    for a in stockage.charger(COLLECTION_APPELS).values():
        if a.get("enveloppe") == enveloppe and (mois is None or a.get("mois") == mois):
            c = float(a.get("cout_eur") or 0)
            tot += c
            n += 1
            if str(a.get("modele") or "").startswith("claude"):
                claude += c
    return {"total_eur": round(tot, 4), "claude_eur": round(claude, 4), "n": n}


def peut_depenser(enveloppe: str, cout_estime_eur: float, fournisseur: str = "") -> DecisionAppel:
    """Autorise une dépense ESTIMÉE dans une enveloppe de sprint (plafond dur). À appeler
    avant chaque lot : refuse si dépense + estimation dépasse le plafond total, ou le
    plafond Claude quand fournisseur == 'claude'. Respecte aussi le kill switch."""
    config = lire_config()
    if config.get("kill_switch_global"):
        return DecisionAppel(False, "Kill-switch budget activé (kill_switch_global=true).")
    env = (config.get("enveloppes") or {}).get(enveloppe)
    if not env:
        return DecisionAppel(False, f"Enveloppe inconnue : {enveloppe!r} (data/budget.json).")
    dep = depense_enveloppe(enveloppe)
    if dep["total_eur"] + cout_estime_eur > float(env.get("total_eur", 0)):
        return DecisionAppel(False, (f"Enveloppe {enveloppe} : {dep['total_eur']:.4f} € dépensés + "
                                     f"{cout_estime_eur:.4f} € estimés > {env.get('total_eur')} €."))
    if fournisseur == "claude" and dep["claude_eur"] + cout_estime_eur > float(env.get("claude_eur", 0)):
        return DecisionAppel(False, (f"Enveloppe {enveloppe} (Claude) : {dep['claude_eur']:.4f} € + "
                                     f"{cout_estime_eur:.4f} € > {env.get('claude_eur')} €."))
    return DecisionAppel(True, f"reste {float(env['total_eur']) - dep['total_eur']:.4f} €")


def plafond_atteint(cout_cumule: float, max_cout) -> bool:
    """Garde-fou --max-cout d'une passe. None : pas de plafond. 0 : tout appel est
    bloqué (le plafond est atteint avant le premier appel). Sinon : True dès que le
    coût cumulé atteint le plafond."""
    return max_cout is not None and float(cout_cumule or 0.0) >= float(max_cout)


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
                        erreur: Optional[str] = None,
                        enveloppe: Optional[str] = None,
                        extra: Optional[dict] = None) -> str:
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
    if enveloppe:
        entree["enveloppe"] = enveloppe
    if extra:
        entree["extra"] = extra
    stockage.ecrire(COLLECTION_APPELS, appel_id, entree)
    # stockage.charger met la collection en cache par processus : on l'invalide pour que
    # les compteurs (jour, mois, enveloppes) voient l'appel qui vient d'être journalisé.
    try:
        stockage.invalider_cache(COLLECTION_APPELS)
    except Exception:
        pass
    return appel_id


def journaliser_appel(type_appel: str, cout_eur: float, **kwargs) -> Optional[str]:
    """enregistrer_appel qui ne lève jamais : à placer HORS du try qui relance un
    appel LLM, pour qu'un échec d'écriture du journal ne déclenche pas un nouvel
    appel payant. Un échec est signalé sur stderr ; retourne l'id ou None."""
    try:
        return enregistrer_appel(type_appel, cout_eur, **kwargs)
    except Exception as e:
        print(f"  ⚠ journal llm_appels non écrit ({type_appel}) : "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return None


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
