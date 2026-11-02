"""
decp/parser_v2.py — normalisation DECP clé `uid` (Sprint DECP-R).

Pourquoi un v2 : dans la DECP consolidée, `id` est le numéro INTERNE à l'acheteur
(« 2025 », « 202601 »…), pas un identifiant unique. La clé unique est
`uid` = acheteur_id + id + "_" + codeCPV. Le parseur v1 (decp/parser.py, conservé pour
compatibilité) regroupait par `id` → contrats écrasés et titulaires fusionnés entre
acheteurs différents.

Entrée : les lignes brutes d'UN contrat (même `uid`), une ligne par titulaire, telles
que renvoyées par l'API tabulaire (types JSON) ou lues dans decp.csv (tout en texte).
Sortie : (contrat, titulaires) au schéma decp_marches v2 / decp_titulaires.

Pur (aucune E/S) → testable hors ligne.
"""
import json
import re
from datetime import datetime, timezone
from typing import Optional

from decp.parser import (MONTANT_MAX, normaliser_cpv, valider_siret,
                         _dept_normalise)

# Colonnes SOURCE de decp_marches v2 (l'UPSERT ne met à jour que celles-ci ; les
# colonnes dérivées — doublon_de… — ne sont jamais écrasées).
COLS_MARCHE = [
    "uid", "id", "source_fichier", "objet", "cpv_principal", "cpv_secondaires",
    "acheteur_siret", "acheteur_nom", "titulaire_siret", "titulaires_json",
    "montant_eur", "date_notification", "duree_mois", "procedure",
    "lieu_execution_code", "departement", "region", "parsed_at", "parse_warnings",
    # champs source ajoutés en v2
    "nature", "type_marche", "lieu_execution_type_code",
    "titulaire_nom", "titulaire_activite_code", "titulaire_categorie",
    "titulaire_type_identifiant", "nb_titulaires",
    "type_groupement", "sous_traitance_declaree", "offres_recues", "id_accord_cadre",
    "source_dataset", "date_publication_donnees", "montant_rationalise",
    "montant_anomalie", "modification_id",
    # versions (Sprint DECP-R) : montant_eur = montant_actuel (compat v1)
    "montant_initial", "montant_actuel", "duree_initiale", "duree_actuelle", "nb_modifications",
]

# Colonnes issues de la version INITIALE : en mise à jour, une valeur absente du lot
# (version initiale non re-téléchargée) ne doit pas effacer la valeur déjà en base.
COLS_INITIALES = ("date_notification", "montant_initial", "duree_initiale")

COLS_TITULAIRE = ["decp_id", "rang", "siret", "siren", "siret_brut", "type_identifiant",
                  "nom", "activite_code", "categorie", "role", "valide", "motif_rejet"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _s(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _f(v) -> Optional[float]:
    s = _s(v)
    if s is None:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _i(v) -> Optional[int]:
    f = _f(v)
    return int(f) if f is not None else None


def _b(v) -> Optional[int]:
    s = _s(v)
    if s is None:
        return None
    s = s.lower()
    if s in ("true", "1", "oui", "vrai"):
        return 1
    if s in ("false", "0", "non", "faux"):
        return 0
    return None


def _date(v, warnings: list, champ: str) -> Optional[str]:
    s = _s(v)
    if not s:
        return None
    s = s[:10]
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except ValueError:
        warnings.append(f"date_non_iso:{champ}")
        return None


def valider_siren(siren) -> bool:
    """SIREN : 9 chiffres + Luhn (exception La Poste 356000000)."""
    s = str(siren or "")
    if len(s) != 9 or not s.isdigit():
        return False
    if s == "356000000":
        return True
    total = 0
    for i, c in enumerate(reversed(s)):
        d = int(c)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def normaliser_identifiant(brut, type_identifiant) -> dict:
    """
    Normalise l'identifiant d'un titulaire. Retourne
    {siret, siren, valide, motif_rejet}. Règles :
      - SIRET (ou type absent) : on garde les chiffres ; 14 chiffres + Luhn → siret+siren ;
        14 chiffres Luhn KO mais SIREN (9 premiers) valide → siren seul (motif siret_luhn) ;
        9 chiffres SIREN valide → siren seul ; sinon rejet (motif explicite).
      - TVA : TVA intracommunautaire FR (FRcc + SIREN) → siren si valide ; étrangère → rejet.
      - HORS-UE / IREP / autres : pas de SIREN (motif = le type).
    `valide` = 1 si un SIREN valide a été retenu.
    """
    t = (_s(type_identifiant) or "").upper()
    if t == "TVA_INTRACOMMUNAUTAIRE":   # libellé des formats 2022-2023
        t = "TVA"
    b = _s(brut)
    out = {"siret": None, "siren": None, "valide": 0, "motif_rejet": None}
    if not b:
        out["motif_rejet"] = "vide"
        return out
    if t == "TVA":
        m = re.fullmatch(r"FR[0-9A-Z]{2}(\d{9})", re.sub(r"[\s.\-]", "", b.upper()))
        if m and valider_siren(m.group(1)):
            out.update(siren=m.group(1), valide=1)
        else:
            out["motif_rejet"] = "tva_non_fr_ou_invalide"
        return out
    if t and t not in ("SIRET", "SIREN"):
        out["motif_rejet"] = f"type_{t.lower()}"
        return out
    # SIRET / type absent : tolère espaces, points, tirets ; rejette le reste
    if re.search(r"[^\d\s.\-]", b):
        out["motif_rejet"] = "caracteres_parasites"
        return out
    d = re.sub(r"\D", "", b)
    if len(d) == 14:
        if valider_siret(d):
            out.update(siret=d, siren=d[:9], valide=1)
        elif valider_siren(d[:9]):
            out.update(siren=d[:9], valide=1, motif_rejet="siret_luhn_ko_siren_ok")
        else:
            out["motif_rejet"] = "luhn_ko"
    elif len(d) == 9:
        if valider_siren(d):
            out.update(siren=d, valide=1)
        else:
            out["motif_rejet"] = "siren_luhn_ko"
    elif d and set(d) == {"0"}:
        out["motif_rejet"] = "que_des_zeros"
    else:
        out["motif_rejet"] = f"longueur_{len(d)}"
    return out


def _role(rang: int, n: int, type_groupement: Optional[str]) -> str:
    """Rôle validé (Sprint DECP-R) : rang 1 en groupement = mandataire présumé, les autres
    cotraitants ; type absent avec plusieurs titulaires = inconnu. Plusieurs titulaires
    « Pas de groupement » = attributaires distincts (accord-cadre multi-attributaires)."""
    if n <= 1:
        return "titulaire"
    tg = (type_groupement or "").lower()
    if tg in ("solidaire", "conjoint"):
        return "mandataire_presume" if rang == 1 else "cotraitant"
    if tg == "pas de groupement":
        return "co_attributaire"
    return "inconnu"


def contrat_depuis_lignes(lignes: list, source_fichier: str) -> Optional[tuple]:
    """
    lignes : lignes brutes d'un même `uid`, dans l'ordre source (rang = position).
    Retourne (contrat: dict, titulaires: list[dict]) ou None si pas d'uid.
    """
    if not lignes:
        return None
    r = lignes[0]
    uid = _s(r.get("uid"))
    if not uid:
        return None
    w: list = []
    cpv = normaliser_cpv(r.get("codeCPV"))
    if not cpv:
        w.append("cpv_absent")
    ach = _s(r.get("acheteur_id"))
    if ach and not valider_siret(ach):
        w.append("acheteur_siret_invalide")
    date_notif = _date(r.get("dateNotification"), w, "dateNotification")
    if not date_notif:
        w.append("date_notification_absente")
    montant = _f(r.get("montant"))
    if montant is not None and (montant < 0 or montant > MONTANT_MAX):
        w.append("montant_negatif" if montant < 0 else "montant_aberrant_>1Md")
        montant = None
    tg = _s(r.get("typeGroupementOperateurs"))

    # Titulaires : une ligne par titulaire ; dédoublonne un même identifiant répété.
    vus, titulaires = set(), []
    for l in lignes:
        brut = _s(l.get("titulaire_id"))
        cle = (brut, _s(l.get("titulaire_nom")))
        if cle in vus or (brut is None and cle[1] is None):
            continue
        vus.add(cle)
        norm = normaliser_identifiant(brut, l.get("titulaire_typeIdentifiant"))
        titulaires.append({
            "decp_id": uid, "rang": len(titulaires) + 1,
            "siret": norm["siret"], "siren": norm["siren"], "siret_brut": brut,
            "type_identifiant": _s(l.get("titulaire_typeIdentifiant")),
            "nom": _s(l.get("titulaire_nom")),
            "activite_code": _s(l.get("titulaire_activite_code")),
            "categorie": _s(l.get("titulaire_categorie")),
            "valide": norm["valide"], "motif_rejet": norm["motif_rejet"],
        })
    n = len(titulaires)
    for t in titulaires:
        t["role"] = _role(t["rang"], n, tg)
    t1 = titulaires[0] if titulaires else {}

    contrat = {
        "uid": uid, "id": _s(r.get("id")), "source_fichier": source_fichier,
        "objet": _s(r.get("objet")), "cpv_principal": cpv, "cpv_secondaires": None,
        "acheteur_siret": ach, "acheteur_nom": _s(r.get("acheteur_nom")),
        # compat v1 : titulaire_siret = identifiant brut du 1er titulaire,
        # titulaires_json = liste des identifiants bruts si plusieurs.
        "titulaire_siret": t1.get("siret_brut"),
        "titulaires_json": (json.dumps([t["siret_brut"] for t in titulaires], ensure_ascii=False)
                            if n > 1 else None),
        "montant_eur": montant, "date_notification": date_notif,
        "duree_mois": _i(r.get("dureeMois")), "procedure": _s(r.get("procedure")),
        "lieu_execution_code": _s(r.get("lieuExecution_code")),
        "departement": _dept_normalise(r.get("acheteur_departement_code")),
        "region": _s(r.get("acheteur_region_code")),
        "parsed_at": _now_iso(),
        "parse_warnings": json.dumps(w, ensure_ascii=False) if w else None,
        "nature": _s(r.get("nature")), "type_marche": _s(r.get("type")),
        "lieu_execution_type_code": _s(r.get("lieuExecution_typeCode")),
        "titulaire_nom": t1.get("nom"), "titulaire_activite_code": t1.get("activite_code"),
        "titulaire_categorie": t1.get("categorie"),
        "titulaire_type_identifiant": t1.get("type_identifiant"),
        "nb_titulaires": n,
        "type_groupement": tg,
        "sous_traitance_declaree": _b(r.get("sousTraitanceDeclaree")),
        "offres_recues": _i(r.get("offresRecues")),
        "id_accord_cadre": _s(r.get("idAccordCadre")),
        "source_dataset": _s(r.get("sourceDataset")),
        "date_publication_donnees": _date(r.get("datePublicationDonnees"), w, "datePublicationDonnees"),
        "montant_rationalise": _f(r.get("montant_rationalise")),
        "montant_anomalie": _s(r.get("montant_anomalie")),
        "modification_id": _i(r.get("modification_id")),
    }
    contrat["parse_warnings"] = json.dumps(w, ensure_ascii=False) if w else None
    return contrat, titulaires


def contrat_versionne(lignes: list, source_fichier: str, date_min: str = "2022-01-01"):
    """
    lignes : TOUTES les lignes brutes d'un uid (toutes versions), ordre source.
    Règles validées (Sprint DECP-R) :
      - champs du contrat et titulaires = version ACTUELLE (donneesActuelles) ;
      - date_notification = date de la version INITIALE (modification_id = 0) — dans la
        DECP, la dateNotification d'une modification est la date de la modification ;
      - montant/durée initiaux = version initiale ; actuels = version actuelle ;
      - nb_modifications = modification_id de la version actuelle.
    Retourne (contrat, titulaires, None) ou (None, None, motif_exclusion). Si la version
    initiale est absente du lot, les champs initiaux valent None (l'UPSERT conserve
    alors ceux déjà en base, cf. COLS_INITIALES) et le motif « sans_version_initiale »
    est renvoyé AVEC le contrat pour que l'appelant décide.
    """
    def _act(l):
        return _b(l.get("donneesActuelles")) == 1

    def _m(l):
        return _i(l.get("modification_id"))

    actuelles = [l for l in lignes if _act(l)]
    if not actuelles:
        return None, None, "sans_version_actuelle"
    mod_act = max((_m(l) or 0) for l in actuelles)
    actuelles = [l for l in actuelles if (_m(l) or 0) == mod_act]
    initiales = [l for l in lignes if _m(l) == 0]
    res = contrat_depuis_lignes(actuelles, source_fichier)
    if res is None:
        return None, None, "sans_uid"
    c, ts = res
    w = [x for x in json.loads(c["parse_warnings"] or "[]")
         if x not in ("date_notification_absente", "date_non_iso:dateNotification")]
    c["montant_actuel"] = c["montant_eur"]
    c["duree_actuelle"] = c["duree_mois"]
    c["nb_modifications"] = mod_act
    motif = None
    if initiales:
        i0 = initiales[0]
        d0 = _date(i0.get("dateNotification"), [], "dateNotification")
        if not d0:
            return None, None, "sans_date_notification"
        if d0 < date_min:
            return None, None, "notifie_avant_" + date_min[:4]
        c["date_notification"] = d0
        m0 = _f(i0.get("montant"))
        c["montant_initial"] = m0 if (m0 is not None and 0 <= m0 <= MONTANT_MAX) else None
        c["duree_initiale"] = _i(i0.get("dureeMois"))
    else:
        c["date_notification"] = None
        c["montant_initial"] = None
        c["duree_initiale"] = None
        motif = "sans_version_initiale"
    c["parse_warnings"] = json.dumps(w, ensure_ascii=False) if w else None
    return c, ts, motif
