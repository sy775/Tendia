"""
connecteurs/__init__.py
-----------------------
Fabrique de connecteurs Tendia.

Un connecteur expose :
    SOURCE          : str  (code court : "BOAMP")
    DOMAINES        : list[str]  (domaines d'URLs pris en charge)
    lister_marches(fenetre_mois, limite, filtre_acheteur, inclure_autre, verbose) -> list[dict]
        Liste les marchés ouverts pertinents, au format unifié défini ci-dessous.

Format unifié d'un marché (retourné par lister_marches) :
{
    "id": "BOAMP-25-12345",                # SOURCE-reference
    "source": "BOAMP",
    "reference_externe": "25-12345",
    "url_source": "...",
    "url_avis": "...",                     # URL UI cliquable
    "titre": "...",
    "objet": "...",
    "acheteur_nom": "...",
    "acheteur_id": "...",                  # SIRET si dispo
    "perimetre_geographique": "...",
    "date_publication": "YYYY-MM-DD",
    "date_limite_depot": "YYYY-MM-DD",
    "cpv_principal": "80530000",
    "categorie_metier": "formation" | "insertion" | "autre",
    "famille_boamp": "...",
    "notice_type": "...",
}

Le pipeline d'ingestion (tendia_recup.py) ajoutera `meta_recuperation`
et écrira dans la base SQLite via stockage.py.

Ajouter une nouvelle source = créer un module ici, l'importer, l'enregistrer
dans `_REGISTRE`. Le reste du code ne change pas.
"""

from urllib.parse import urlparse

from connecteurs import boamp


# Registre des connecteurs. L'ordre n'a pas d'importance.
# Sprint 3 : BOAMP est l'unique source. TED a été retiré (rapportait < 5
# marchés/an pertinents en moyenne, avec des données pauvres, et 0 doublon
# utile avec BOAMP). PLACE viendra dans un sprint ultérieur (scraping web).
_REGISTRE = [boamp]
SOURCES_PAR_DEFAUT = ["BOAMP"]


def selectionner_connecteur(url: str):
    """
    Retourne le module connecteur capable de gérer cette URL, ou lève
    ValueError si aucun ne matche.
    """
    if not url:
        raise ValueError("URL vide.")
    domaine = (urlparse(url).netloc or "").lower()
    if not domaine:
        raise ValueError(f"URL invalide (pas de domaine) : {url}")

    for connecteur in _REGISTRE:
        for d in getattr(connecteur, "DOMAINES", []):
            if d.lower() in domaine:
                return connecteur

    sources_dispo = ", ".join(getattr(c, "SOURCE", "?") for c in _REGISTRE)
    raise ValueError(
        f"Aucun connecteur ne gère le domaine '{domaine}'. "
        f"Connecteurs disponibles : {sources_dispo}."
    )


def code_source_depuis_url(url: str) -> str:
    """Retourne le code SOURCE d'un connecteur depuis une URL, ou 'INCONNU'."""
    try:
        return getattr(selectionner_connecteur(url), "SOURCE", "INCONNU")
    except ValueError:
        return "INCONNU"


def sources_disponibles() -> list:
    """Liste les codes SOURCE de tous les connecteurs enregistrés."""
    return [getattr(c, "SOURCE", "?") for c in _REGISTRE]


def sources_par_defaut() -> list:
    """Sources actives par défaut."""
    return list(SOURCES_PAR_DEFAUT)


def tous_les_connecteurs() -> list:
    """Retourne la liste des modules connecteurs enregistrés."""
    return list(_REGISTRE)
