"""
organisme.py
------------
Gestion du profil de l'organisme dans Tendia.

ARCHITECTURE (Sprint 3 — refonte profil multi-secteurs)
=======================================================

Un profil organisme = un objet JSON unique qui combine :

  1. Un SOCLE COMMUN universel (identité, zones, capacité globale,
     économie, mots-clés), défini par `presets/_socle_profil_organisme.json`.

  2. Une LISTE de presets couverts par l'organisme (`presets_couverts`),
     ex : ["btp", "ingenierie"].

  3. Un DICT `profils_sectoriels` keyed par code preset. Chaque valeur
     suit le schéma sectoriel défini dans `presets/<code>/_schema.json`
     (qualifications, corps de métier, références, etc. propres au
     secteur).

STOCKAGE : SQLite collection `organisme`, id `principal`.

INTERFACE PUBLIQUE
==================
Lecture :
    charger_actif() -> dict | None
    profil_existe() -> bool
    presets_couverts(profil=None) -> list[str]
    profil_sectoriel(code_preset, profil=None) -> dict | None

Écriture :
    ecrire_profil(profil) -> None
    initialiser_si_absent(presets_couverts=None) -> dict
    supprimer_profil() -> bool

Schémas et templates :
    schema_socle() -> dict
    schema_sectoriel(code) -> dict | None
    template_socle_vide() -> dict
    template_sectoriel_vide(code) -> dict
    template_profil_complet(presets) -> dict

Validation :
    valider_profil(profil=None) -> dict
    champs_remplis(profil=None) -> dict  (legacy compat)

Migration :
    est_format_legacy(profil) -> bool

Backward compat :
    lire_profil() -> dict | None       (alias charger_actif)
    schema_vide() -> dict              (alias template_socle_vide)
"""

import json
from pathlib import Path
from typing import Optional, List, Any

import stockage


COLLECTION = "organisme"
ID_PROFIL = "principal"

# Codes presets reconnus. Doit correspondre aux dossiers presets/<code>/.
PRESETS_CONNUS = ["btp", "ingenierie", "conseil", "it",
                  "energie_renouvelable", "formation"]

# Chemin vers le dossier presets racine
_PRESETS_DIR = Path(__file__).parent / "presets"


# ---------------------------------------------------------------------------
# Chargement des schémas
# ---------------------------------------------------------------------------

def schema_socle() -> dict:
    """Retourne le JSON-schema du socle commun."""
    f = _PRESETS_DIR / "_socle_profil_organisme.json"
    if not f.exists():
        return {}
    return json.loads(f.read_text(encoding="utf-8"))


def schema_sectoriel(code_preset: str) -> Optional[dict]:
    """
    Retourne le JSON-schema sectoriel d'un preset, ou None si absent.

    Les presets formation et energie_renouvelable ont des schémas
    historiques qui contiennent encore le socle imbriqué ; ils seront
    refactorés Sprint 3+. Les nouveaux schémas (btp, etc.) suivent la
    convention sectorielle pure.
    """
    f = _PRESETS_DIR / code_preset / "_schema.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Templates (objets pré-remplis avec champs vides)
# ---------------------------------------------------------------------------

def template_socle_vide() -> dict:
    """Génère un template du socle avec tous les champs vides/nulls."""
    from datetime import datetime, timezone
    return {
        "id": ID_PROFIL,
        "_description": "",
        "_creation": datetime.now(timezone.utc).isoformat(),
        "_version_schema": "1.0",
        "identite": {
            "raison_sociale": "",
            "forme_juridique": "",
            "siren": "",
            "siret_siege": "",
            "naf_principal": "",
            "effectif_salaries": None,
            "annee_creation": None,
            "tva_intracom": "",
            "adresse_siege": {
                "rue": "",
                "code_postal": "",
                "ville": "",
                "departement": ""
            },
            "site_web": "",
            "contact_AO": {
                "nom": "",
                "fonction": "",
                "email": "",
                "telephone": ""
            }
        },
        "zones_intervention": [],
        "capacite_globale": {
            "ca_annuel_n_moins_1": None,
            "ca_annuel_n_moins_2": None,
            "ca_annuel_n_moins_3": None,
            "fonds_propres": None,
            "effectif_total_etp": None,
            "capacite_engagement_simultane": None,
            "seuil_minimum_marche_eur": None
        },
        "economie": {
            "marge_brute_cible_pct": None,
            "taux_journalier_moyen_eur": None,
            "frais_de_structure_pct": None,
            "agressivite_commerciale": "neutre"
        },
        "mots_cles_catalogue": [],
        "presets_couverts": [],
        "profils_sectoriels": {},
        "auto_reponses_exigences": {}
    }


def template_sectoriel_vide(code_preset: str) -> dict:
    """Génère un template du profil sectoriel pour un preset depuis son schéma."""
    sch = schema_sectoriel(code_preset)
    if not sch or "properties" not in sch:
        return {}
    return _build_template_from_schema(sch)


def _build_template_from_schema(sch: dict) -> Any:
    """Construit récursivement un template vide depuis un JSON-schema."""
    t = sch.get("type")
    if t == "object":
        out = {}
        for k, p in (sch.get("properties") or {}).items():
            out[k] = _build_template_from_schema(p)
        return out
    if t == "array":
        return []
    if t == "string":
        return ""
    if t in ("integer", "number"):
        return None
    if t == "boolean":
        return None
    return None


def template_profil_complet(codes_presets: List[str]) -> dict:
    """Template de profil complet : socle vide + profils sectoriels vides."""
    inconnus = [c for c in codes_presets if c not in PRESETS_CONNUS]
    if inconnus:
        raise ValueError(f"Presets inconnus : {inconnus}. "
                         f"Connus : {PRESETS_CONNUS}")
    p = template_socle_vide()
    p["presets_couverts"] = list(codes_presets)
    p["profils_sectoriels"] = {
        code: template_sectoriel_vide(code) for code in codes_presets
    }
    return p


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def profil_existe() -> bool:
    return stockage.lire(COLLECTION, ID_PROFIL) is not None


def charger_actif() -> Optional[dict]:
    """Retourne le profil principal, ou None s'il n'existe pas."""
    return stockage.lire(COLLECTION, ID_PROFIL)


def lire_profil() -> Optional[dict]:
    """Alias backward-compat de charger_actif()."""
    return charger_actif()


def ecrire_profil(profil: dict) -> None:
    """Écrit le profil principal (crée ou écrase)."""
    profil_a_ecrire = dict(profil)
    profil_a_ecrire["id"] = ID_PROFIL
    stockage.ecrire(COLLECTION, ID_PROFIL, profil_a_ecrire)


def supprimer_profil() -> bool:
    """Supprime le profil principal."""
    if not profil_existe():
        return False
    stockage.supprimer(COLLECTION, ID_PROFIL)
    return True


def initialiser_si_absent(presets_couverts: Optional[List[str]] = None) -> dict:
    """
    Crée le profil principal s'il n'existe pas. Si `presets_couverts` n'est
    pas fourni, crée un profil socle vide sans secteur.
    """
    existant = charger_actif()
    if existant is not None:
        return existant
    if presets_couverts:
        tpl = template_profil_complet(presets_couverts)
    else:
        tpl = template_socle_vide()
    ecrire_profil(tpl)
    return tpl


# ---------------------------------------------------------------------------
# Accès sectoriel
# ---------------------------------------------------------------------------

def presets_couverts(profil: Optional[dict] = None) -> List[str]:
    """Codes presets que l'organisme couvre."""
    p = profil if profil is not None else charger_actif()
    if not p:
        return []
    return list(p.get("presets_couverts") or [])


def profil_sectoriel(code_preset: str,
                     profil: Optional[dict] = None) -> Optional[dict]:
    """Retourne le bloc sectoriel d'un preset pour le profil actif."""
    p = profil if profil is not None else charger_actif()
    if not p:
        return None
    return (p.get("profils_sectoriels") or {}).get(code_preset)


# ---------------------------------------------------------------------------
# Validation (maison, sans dépendance jsonschema)
# ---------------------------------------------------------------------------

def valider_profil(profil: Optional[dict] = None) -> dict:
    """
    Valide un profil en mode best-effort.

    Retourne :
        {valide, erreurs[], warnings[], champs_remplis{socle, par_preset{}}}
    """
    p = profil if profil is not None else charger_actif()
    rapport = {"valide": True, "erreurs": [], "warnings": [],
               "champs_remplis": {"socle": 0.0, "par_preset": {}}}
    if not p:
        rapport["valide"] = False
        rapport["erreurs"].append("Profil absent.")
        return rapport

    # 1) Socle : champs required
    socle_required = (schema_socle() or {}).get("required") or []
    for k in socle_required:
        v = p.get(k)
        if v is None or (isinstance(v, (list, dict, str)) and len(v) == 0):
            rapport["valide"] = False
            rapport["erreurs"].append(f"Socle : champ requis '{k}' manquant/vide")

    # 2) Cohérence presets_couverts ↔ profils_sectoriels
    presets = p.get("presets_couverts") or []
    sectoriels = p.get("profils_sectoriels") or {}
    for code in presets:
        if code not in PRESETS_CONNUS:
            rapport["erreurs"].append(f"Preset inconnu dans presets_couverts : '{code}'")
            rapport["valide"] = False
        if code not in sectoriels:
            rapport["erreurs"].append(
                f"Preset '{code}' déclaré couvert mais absent de profils_sectoriels")
            rapport["valide"] = False
    for code in sectoriels:
        if code not in presets:
            rapport["warnings"].append(
                f"profils_sectoriels['{code}'] est rempli mais pas listé dans presets_couverts")

    # 3) Required de chaque profil sectoriel
    for code, ps in sectoriels.items():
        sch = schema_sectoriel(code)
        if not sch:
            rapport["warnings"].append(
                f"Aucun schéma pour preset '{code}' — validation sectorielle skippée")
            continue
        req = sch.get("required") or []
        for k in req:
            v = (ps or {}).get(k)
            if v is None or (isinstance(v, (list, dict, str)) and len(v) == 0):
                rapport["valide"] = False
                rapport["erreurs"].append(
                    f"Preset '{code}' : champ requis '{k}' manquant/vide")

    # 4) Stats de remplissage
    rapport["champs_remplis"]["socle"] = _ratio_remplissage(
        {k: v for k, v in p.items() if k != "profils_sectoriels"})
    for code, ps in sectoriels.items():
        rapport["champs_remplis"]["par_preset"][code] = _ratio_remplissage(ps)

    return rapport


def _ratio_remplissage(d: Any) -> float:
    """% de feuilles non-vides (récursif)."""
    feuilles = _collecter_feuilles(d)
    if not feuilles:
        return 0.0
    rempli = sum(1 for v in feuilles if v is not None
                  and not (isinstance(v, (list, dict, str)) and len(v) == 0))
    return round(rempli / len(feuilles), 2)


def _collecter_feuilles(d: Any) -> list:
    """Récupère toutes les valeurs feuilles d'un objet."""
    if isinstance(d, dict):
        out = []
        for v in d.values():
            out.extend(_collecter_feuilles(v))
        return out
    if isinstance(d, list):
        if not d:
            return [d]
        out = []
        for v in d:
            out.extend(_collecter_feuilles(v))
        return out
    return [d]


# ---------------------------------------------------------------------------
# Détection format legacy + helpers compat
# ---------------------------------------------------------------------------

def est_format_legacy(profil: dict) -> bool:
    """Détecte si un profil suit l'ancien format formation."""
    if not profil:
        return False
    if "presets_couverts" in profil and "profils_sectoriels" in profil:
        return False
    legacy_markers = ("thematiques_metiers", "publics_cibles",
                      "prestations_maitrisees", "modalites_pedagogiques",
                      "directions_regionales_couvertes")
    return any(m in profil for m in legacy_markers)


def champs_remplis(profil: Optional[dict] = None) -> dict:
    """[LEGACY] Rapport simple de remplissage pour backward-compat init_profil.py."""
    p = profil if profil is not None else charger_actif()
    if not p:
        return {}
    if est_format_legacy(p):
        return {
            "identite_nom": bool(p.get("identite", {}).get("nom")),
            "directions_regionales": bool(p.get("directions_regionales_couvertes")),
            "thematiques": bool(p.get("thematiques_metiers")),
            "publics_cibles": bool(p.get("publics_cibles")),
            "prestations": bool(p.get("prestations_maitrisees")),
            "mots_cles": bool(p.get("mots_cles_catalogue")),
            "qualiopi": any([
                p.get("certifications", {}).get("qualiopi_actions_formation"),
                p.get("certifications", {}).get("qualiopi_apprentissage"),
                p.get("certifications", {}).get("qualiopi_bilans"),
            ]),
        }
    rapport = valider_profil(p)
    out = {
        "socle_identite": bool(p.get("identite", {}).get("raison_sociale")),
        "socle_zones": bool(p.get("zones_intervention")),
        "socle_capacite": bool(p.get("capacite_globale", {}).get("ca_annuel_n_moins_1")),
        "socle_mots_cles": bool(p.get("mots_cles_catalogue")),
        "presets_couverts": bool(p.get("presets_couverts")),
    }
    for code in (p.get("presets_couverts") or []):
        ratio = rapport["champs_remplis"]["par_preset"].get(code, 0.0)
        out[f"sectoriel_{code}"] = ratio >= 0.5
    return out


def schema_vide() -> dict:
    """[LEGACY] Alias de template_socle_vide() pour backward-compat."""
    return template_socle_vide()


# ---------------------------------------------------------------------------
# Référentiels historiques (gardés pour compat formation)
# ---------------------------------------------------------------------------

DR_FRANCE_TRAVAIL = [
    "DG", "ARA", "BFC", "BRE", "CVL", "COR", "GES", "HDF", "IDF",
    "NOR", "NAQ", "OCC", "PDL", "PACA",
    "GUA", "MAR", "GUY", "REU", "MAY",
]

PRESTATIONS_FRANCE_TRAVAIL = [
    "AFC", "AFPR", "POEI", "POEC",
    "ACTIV_Seniors", "ACTIV_Decouverte", "ACTIV_Crea", "ACTIV_Emergence",
    "AGIL_Cadres", "MILE", "Creascope",
    "Bilan_competences", "VAE",
    "formation_diplomante", "formation_certifiante", "formation_continue",
]


# ---------------------------------------------------------------------------
# CLI / debug
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if "--show" in sys.argv:
        p = charger_actif()
        if p is None:
            print("Aucun profil. Lance : python init_profil.py")
        else:
            print(json.dumps(p, ensure_ascii=False, indent=2))

    elif "--check" in sys.argv:
        rapport = valider_profil()
        print(f"Valide : {rapport['valide']}")
        if rapport["erreurs"]:
            print("\nErreurs :")
            for e in rapport["erreurs"]:
                print(f"  X {e}")
        if rapport["warnings"]:
            print("\nAvertissements :")
            for w in rapport["warnings"]:
                print(f"  ! {w}")
        cr = rapport["champs_remplis"]
        print(f"\nRemplissage socle : {cr['socle']*100:.0f}%")
        for code, r in cr["par_preset"].items():
            print(f"  preset {code} : {r*100:.0f}%")

    elif "--supprimer" in sys.argv:
        if "--confirmer" not in sys.argv:
            print("Suppression du profil principal. Ajoute --confirmer pour valider.")
            sys.exit(1)
        if supprimer_profil():
            print("Profil supprime.")
        else:
            print("Aucun profil a supprimer.")

    elif "--template" in sys.argv:
        codes = [a for a in sys.argv[2:] if not a.startswith("--")]
        if not codes:
            print("Usage : python organisme.py --template <code_preset>...")
            print(f"Presets connus : {PRESETS_CONNUS}")
            sys.exit(1)
        tpl = template_profil_complet(codes)
        print(json.dumps(tpl, ensure_ascii=False, indent=2))

    else:
        print("Usage :")
        print("  python organisme.py --show                       Affiche le profil")
        print("  python organisme.py --check                      Valide le profil")
        print("  python organisme.py --template btp [ingenierie]  Genere un template")
        print("  python organisme.py --supprimer --confirmer      Supprime le profil")
