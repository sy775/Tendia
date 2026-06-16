"""
decp/parser.py — normalisation des enregistrements DECP consolidée.

Convertit un record brut de l'API tabulaire (66 colonnes plates) vers le schéma
`decp_marches`. Réutilise la sémantique de `connecteurs/decp_consolidee.py`
(géo native, dédup multi-titulaires) sans dépendre du réseau (testable hors-ligne).
"""
from datetime import datetime, timezone
from typing import Optional

MONTANT_MAX = 1_000_000_000  # 1 Md€ : au-delà = aberrant (cf prompt sprint)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def valider_siret(siret) -> bool:
    """Validité SIRET : 14 chiffres + Luhn. Exception La Poste (356000000…)."""
    s = "".join(c for c in str(siret or "") if c.isdigit())
    if len(s) != 14:
        return False
    if s.startswith("356000000"):  # La Poste : dérogation réglementaire au Luhn
        return sum(int(c) for c in s) % 5 == 0
    total = 0
    for i, c in enumerate(reversed(s)):
        d = int(c)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def normaliser_cpv(val) -> Optional[str]:
    """CPV → 8 chiffres sans séparateur (les CPV ont la forme 'NNNNNNNN-C')."""
    if not val:
        return None
    digits = "".join(c for c in str(val) if c.isdigit())
    return digits[:8] if len(digits) >= 8 else (digits or None)


def _float_montant(val, warnings: list) -> Optional[float]:
    if val in (None, ""):
        return None
    try:
        m = float(val)
    except (TypeError, ValueError):
        warnings.append("montant_non_numerique")
        return None
    if m < 0:
        warnings.append("montant_negatif")
        return None
    if m > MONTANT_MAX:
        warnings.append("montant_aberrant_>1Md")
        return None
    return m


def _date_iso(val, warnings: list, champ: str) -> Optional[str]:
    if not val:
        return None
    s = str(val)[:10]
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except ValueError:
        warnings.append(f"date_non_iso:{champ}")
        return None


def _int(val) -> Optional[int]:
    if val in (None, ""):
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def _str(val) -> Optional[str]:
    if val in (None, ""):
        return None
    s = str(val).strip()
    return s or None


def _dept_normalise(code) -> Optional[str]:
    """Département natif DECP → 2 chiffres (ou 2A/2B/3 chiffres DOM)."""
    s = _str(code)
    if not s:
        return None
    s = s.upper()
    if s in ("2A", "2B"):
        return s
    if s.isdigit():
        return s.zfill(2) if len(s) == 1 else s[:3]
    return s[:3]


def parser_marche(raw: dict, source_fichier: str = "decp_consolidee_api") -> Optional[dict]:
    """
    Parse un marché DECP brut. Retourne un dict au schéma `decp_marches`, ou
    None si rejet dur (pas d'`id`). `parse_warnings` liste les anomalies non
    bloquantes (champ absent, valeur corrigée…).
    """
    if not isinstance(raw, dict):
        return None
    id_brut = _str(raw.get("id"))
    if not id_brut:
        return None

    warnings: list = []
    cpv = normaliser_cpv(raw.get("codeCPV"))
    if not cpv:
        warnings.append("cpv_absent")

    acheteur_siret = _str(raw.get("acheteur_id"))
    if acheteur_siret and not valider_siret(acheteur_siret):
        warnings.append("acheteur_siret_invalide")

    titulaire_siret = _str(raw.get("titulaire_id"))
    date_notif = _date_iso(raw.get("dateNotification"), warnings, "dateNotification")
    if not date_notif:
        warnings.append("date_notification_absente")

    montant = _float_montant(raw.get("montant"), warnings)

    return {
        "id": id_brut,
        "source_fichier": source_fichier,
        "objet": _str(raw.get("objet")),
        "cpv_principal": cpv,
        "cpv_secondaires": None,  # absent de la consolidée
        "acheteur_siret": acheteur_siret,
        "acheteur_nom": _str(raw.get("acheteur_nom")),
        "titulaire_siret": titulaire_siret,
        "titulaires_json": None,  # rempli par agreger_multi_titulaires
        "montant_eur": montant,
        "date_notification": date_notif,
        "duree_mois": _int(raw.get("dureeMois")),
        "procedure": _str(raw.get("procedure")),
        "lieu_execution_code": _str(raw.get("lieuExecution_code")),
        "departement": _dept_normalise(raw.get("acheteur_departement_code")),
        "region": _str(raw.get("acheteur_region_code")),
        "parsed_at": _now_iso(),
        "parse_warnings": warnings or None,
    }


def agreger_multi_titulaires(marches: list) -> list:
    """
    Un marché multi-attributaires apparaît en plusieurs lignes (même `id`) dans
    la consolidée. On agrège par `id` : 1ʳᵉ ligne = principale, `titulaire_siret`
    = 1er titulaire, `titulaires_json` = liste JSON de tous les SIRET titulaires.
    """
    import json as _json
    par_id: dict = {}
    titulaires: dict = {}
    for m in marches:
        if not m:
            continue
        mid = m["id"]
        if mid not in par_id:
            par_id[mid] = m
            titulaires[mid] = []
        st = m.get("titulaire_siret")
        if st and st not in titulaires[mid]:
            titulaires[mid].append(st)
    out = []
    for mid, principal in par_id.items():
        liste = titulaires[mid]
        if len(liste) > 1:
            principal["titulaires_json"] = _json.dumps(liste, ensure_ascii=False)
        out.append(principal)
    return out
