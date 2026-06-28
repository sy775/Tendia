"""
resolution_reference.py
-----------------------
Résout l'`url_dce` des avis qui n'ont PAS de lien direct dans la donnée BOAMP,
en exploitant deux champs présents dans le raw avis :
  - `urlProfilAch` / `cbc:URI` : le SITE de la plateforme (homepage)
  - `identifiantInterne`       : la RÉFÉRENCE acheteur de la consultation

Sur les moteurs Atexo (marques blanches), une recherche anonyme par référence
(`_chercher_url_dce_via_atexo`) retrouve la consultation → on en déduit l'url_dce.
L'accès est anonyme (garanti réglementairement pour les marchés publics).

Helpers réutilisables + chaîne testable :
    extraire_plateforme_reference(marche) -> (base, reference)
    resoudre_url_via_reference(marche)     -> url_dce | None
"""
import json
import re
from typing import Optional

import dce_finder

# Moteurs Atexo (marques blanches + PLACE) où la recherche GET fonctionne.
HOSTS_ATEXO_SEARCH = (
    "marches-publics.gouv", "megalis", "demat-ampa", "ternum", "maximilien",
    "596280", "marchespublics.eure", "marchespublics.ain", "alsacemarchespublics",
    "marchespublics.aude", "nantesmetropole", "adullact", "marches.rhone",
    "auvergnerhonealpes", "muretain", "sictiam", "profilacheteur", "agglo-muretain",
    "ternum-bfc", "marches.rennes",
)

# Le raw avis est une chaîne JSON échappée → on tolère le `\"`.
_RE_PROFIL = re.compile(r'urlProfilAch\\?"\s*:\s*\\?"([^"\\]+)')
_RE_URI = re.compile(r'cbc:URI[^h]{0,40}(https?://[^"\\ ]+)', re.I)
_RE_REF = re.compile(r'identifiantInterne\\?"\s*:\s*\\?"([^"\\]+)')


def extraire_plateforme_reference(marche: dict):
    """Retourne (base_plateforme, reference) depuis le raw avis, ou (None, None)."""
    brut = marche.get("donnees_boamp_brut")
    t = brut if isinstance(brut, str) else json.dumps(brut, ensure_ascii=False)
    mp = _RE_PROFIL.search(t) or _RE_URI.search(t)
    mr = _RE_REF.search(t)
    base = mp.group(1).rstrip("/") if mp else None
    ref = (mr.group(1).strip() if mr else None) or None
    return base, ref


def est_moteur_atexo(base: str) -> bool:
    return any(h in (base or "").lower() for h in HOSTS_ATEXO_SEARCH)


def normaliser_base(base: str) -> str:
    """Corrige les `urlProfilAch` mal formés (sous-domaine/point manquants) vers
    l'hôte de recherche canonique. Sinon la recherche échoue à tort."""
    low = (base or "").lower()
    if "megalis" in low:               # www.megalis / megalisbretagne (sans point)…
        return "https://marches.megalis.bretagne.bzh"
    return base


def resoudre_url_via_reference(marche: dict) -> Optional[str]:
    """Cherche l'url_dce d'un avis sans lien direct via plateforme + référence.
    Phase 1 : moteurs Atexo uniquement (recherche GET prouvée)."""
    base, ref = extraire_plateforme_reference(marche)
    if not (base and ref and est_moteur_atexo(base)):
        return None
    try:
        return dce_finder._chercher_url_dce_via_atexo(ref, normaliser_base(base),
                                                      verbose=False)
    except Exception:
        return None
