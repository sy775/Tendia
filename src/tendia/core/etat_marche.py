# -*- coding: utf-8 -*-
"""
tendia.core.etat_marche
-----------------------
Définition UNIQUE de l'état d'un marché dans le dépôt (chantier 1b) :

- `est_attribution(marche)` : l'avis est un avis d'attribution (marché déjà
  attribué, on ne candidate plus) ;
- `est_clos(marche)` : date limite de dépôt passée, ou avis d'attribution ;
- `est_actif(marche)` : non clos, et date limite à venir ou, sans date limite,
  publié depuis moins de `fenetre_jours` jours ;
- `date_cloture(marche)` : date à afficher dans « clos le … ».

Utilisé par le pipeline, la résolution DCE, la classification (pré-filtre) et
l'UI. Ne pas redéfinir ces règles ailleurs.
"""
import json
import re
from datetime import date
from typing import Optional

FENETRE_SANS_DATE_JOURS = 60


def _date_iso(valeur) -> Optional[date]:
    """'2026-11-11...' -> date ; None si absent ou illisible."""
    if not valeur or len(str(valeur)) < 10:
        return None
    try:
        return date.fromisoformat(str(valeur)[:10])
    except ValueError:
        return None


def est_attribution(marche: dict) -> bool:
    """Avis d'attribution : nature ATTRIBUTION (format BOAMP), type d'avis
    ContractAwardNotice (eForms, à la racine ou dans `donnees`), ou notice_type
    BOAMP « 10 | … »."""
    nature = (marche.get("nature") or marche.get("nature_marche") or "").lower()
    if "attribution" in nature or "award" in nature:
        return True
    donnees = marche.get("donnees") or {}
    if isinstance(donnees, str):
        try:
            donnees = json.loads(donnees)
        except Exception:
            donnees = {}
    types = (marche.get("notice_type"), marche.get("type_notice"),
             donnees.get("notice_type") if isinstance(donnees, dict) else None)
    for t in types:
        t = str(t or "").strip()
        if "ContractAwardNotice" in t or re.match(r"10(\D|$)", t):
            return True
    return False


def est_clos(marche: dict, aujourdhui: Optional[date] = None) -> bool:
    """Clos : date limite de dépôt passée (strictement avant aujourd'hui), ou
    avis d'attribution."""
    aujourdhui = aujourdhui or date.today()
    limite = _date_iso(marche.get("date_limite_depot"))
    if limite is not None and limite < aujourdhui:
        return True
    return est_attribution(marche)


def est_actif(marche: dict, fenetre_jours: int = FENETRE_SANS_DATE_JOURS,
              aujourdhui: Optional[date] = None) -> bool:
    """Toujours en lice : non clos, et date limite à venir ou, sans date limite,
    publié depuis au plus `fenetre_jours` jours."""
    aujourdhui = aujourdhui or date.today()
    if est_clos(marche, aujourdhui):
        return False
    if _date_iso(marche.get("date_limite_depot")) is not None:
        return True
    publication = _date_iso(marche.get("date_publication"))
    return publication is not None and (aujourdhui - publication).days <= fenetre_jours


def date_cloture(marche: dict, aujourdhui: Optional[date] = None) -> Optional[date]:
    """Date affichée dans « clos le … » : la date limite passée, sinon (avis
    d'attribution) la date de publication de l'avis. None si le marché n'est pas
    clos ou si aucune date n'est connue."""
    if not est_clos(marche, aujourdhui):
        return None
    aujourdhui = aujourdhui or date.today()
    limite = _date_iso(marche.get("date_limite_depot"))
    if limite is not None and limite < aujourdhui:
        return limite
    return _date_iso(marche.get("date_publication"))
