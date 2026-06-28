# -*- coding: utf-8 -*-
"""
Helpers internes PARTAGÉS du générateur de mémoire technique (Sprint B).

Mutualise le chargement des entrées (profil organisme, brief/lot, barème,
digest, texte DCE) et l'appel LLM Sonnet 4.6 entre les services d'appel
(`extraction_contexte_memoire`, `redaction_memoire`) et la régénération de
section. AUCUNE logique de prompt ici — uniquement de la plomberie.

Réutilise (sans les modifier) des fonctions du Sprint A
(`services.digest_memoire`) : chargement CCTP filtré par lot, repérage du lot,
clé de digest. Importer ≠ modifier : les guardrails Sprint A restent respectés.

⚠️ N'intègre rien au pipeline d'extraction. Module additif Sprint B.
"""
import json
import os
import re
import time
from typing import Optional, Tuple

import stockage
import llm_extract
import budget
from anthropic import Anthropic

from services import digest_memoire  # réutilisation lecture seule (Sprint A)

MODELE = llm_extract.MODELE                       # claude-sonnet-4-6
COLLECTION_MEMOIRES = "memoires_techniques"
COLLECTION_DIGESTS = digest_memoire.COLLECTION    # "digests_memoire"
REPERTOIRE_DCE = digest_memoire.REPERTOIRE_DCE    # data/dce
REPERTOIRE_PROFILS_DEMO = os.path.join("data", "profils_demo")


# ---------------------------------------------------------------------------
# Chargement des entrées
# ---------------------------------------------------------------------------

def charger_profil_organisme(id_user: str) -> dict:
    """Profil organisme du user. Priorité : base (collection 'organisme'),
    puis fichier data/profils_demo/<id_user>.json (profils fictifs du batch)."""
    prof = stockage.lire("organisme", id_user)
    if prof:
        return prof
    chemin = os.path.join(REPERTOIRE_PROFILS_DEMO, f"{id_user}.json")
    if os.path.isfile(chemin):
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    raise ValueError(
        f"Profil organisme introuvable : '{id_user}' (ni en base 'organisme', "
        f"ni dans {REPERTOIRE_PROFILS_DEMO}/{id_user}.json)."
    )


def charger_brief_et_lot(id_marche: str, numero_lot) -> Tuple[dict, dict]:
    """Retourne (brief, lot). Lève ValueError si absent."""
    brief = stockage.lire("briefs_extraits", id_marche)
    if not brief:
        raise ValueError(f"Brief introuvable pour {id_marche} (collection briefs_extraits).")
    lot = digest_memoire._trouver_lot(brief, numero_lot)
    if not lot:
        nums = [l.get("numero") for l in (brief.get("lots") or []) if isinstance(l, dict)]
        raise ValueError(f"Lot {numero_lot} introuvable dans {id_marche}. "
                         f"Lots disponibles : {nums}")
    return brief, lot


def charger_digest(id_marche: str, numero_lot) -> dict:
    """Digest mémoire (Sprint A) du lot. Lève ValueError avec la commande à
    lancer s'il n'a pas encore été généré."""
    cle = digest_memoire.cle_digest(id_marche, numero_lot)
    d = stockage.lire(COLLECTION_DIGESTS, cle)
    if not d:
        raise ValueError(
            f"Digest mémoire absent pour {id_marche} lot {numero_lot}. "
            f"Génère-le d'abord :\n"
            f"  python scripts/generer_digest_memoire.py "
            f"--id-marche {id_marche} --numero-lot {numero_lot}"
        )
    return d


def charger_dce_lot(id_marche: str, lot: dict, verbose: bool = True):
    """(texte_concatene, infos) — délègue au chargeur CCTP/DCE filtré du Sprint A."""
    return digest_memoire.charger_cctp_lot(id_marche, lot, verbose=verbose)


def bareme_et_criteres(brief: dict) -> Tuple[dict, str]:
    """(bareme_dict, criteres_publies_texte) — réutilise l'aplatisseur Sprint A."""
    bareme = brief.get("bareme_notation") or {}
    return bareme, digest_memoire._criteres_publies_texte(bareme)


def grille_redaction_lot(brief: dict, lot: dict) -> str:
    """Aplatit la GRILLE D'ACTIONS du barème, filtrée pour le domaine du lot.

    Chaque sous-critère technique porte une `grille_actions_par_domaine`
    (actions adaptées par domaine métier) et une `grille_actions` générique de
    repli. On sélectionne les actions du domaine du lot (ex. `btp_gros_oeuvre`)
    et on les présente avec leur type (livrable/levier), poids % et source : la
    matière directement actionnable pour structurer et rédiger la mémoire."""
    domaine = (lot or {}).get("domaine")
    bareme = (brief or {}).get("bareme_notation") or {}
    scs = bareme.get("sous_criteres_techniques") or []
    if not scs:
        return "(aucune grille d'actions disponible dans le barème extrait)"

    lignes = [f"Grille d'actions à démontrer, filtrée pour le domaine du lot : {domaine}."]
    for i, sc in enumerate(scs, 1):
        if not isinstance(sc, dict):
            continue
        lignes.append(f"\nSous-critère {i} — {sc.get('libelle')} "
                      f"({sc.get('ponderation_pct')}%)")
        if sc.get("description"):
            lignes.append(f"  Attendu : {sc.get('description')}")

        gpd = sc.get("grille_actions_par_domaine") or {}
        if domaine and isinstance(gpd, dict) and gpd.get(domaine):
            actions, origine = gpd.get(domaine), f"domaine {domaine}"
        else:
            actions, origine = (sc.get("grille_actions") or []), "générique"
        if not actions:
            continue
        lignes.append(f"  Actions à démontrer ({origine}) :")
        for a in actions:
            if isinstance(a, dict):
                src = f" — source : {a.get('source')}" if a.get("source") else ""
                lignes.append(f"    • [{a.get('type', '?')}, poids {a.get('poids_pct')}%] "
                              f"{a.get('action')}{src}")
            else:
                lignes.append(f"    • {a}")
    return "\n".join(lignes)


# ---------------------------------------------------------------------------
# Appel LLM (Sonnet 4.6, streaming — pas de timeout, cf. préférence Younes)
# ---------------------------------------------------------------------------

def appeler_llm(system_prompt: str, user_msg: str, max_tokens: int) -> Tuple[str, dict]:
    """Appel Sonnet 4.6 en streaming. Retourne (texte_brut_nettoye, usage).

    usage = {tokens_entree, tokens_sortie, duree_s, stop_reason}. Le nettoyage
    se limite au retrait d'un éventuel fence markdown ```json … ```. AUCUNE
    réparation de JSON (cf. guardrails) — le parsing est laissé à l'appelant."""
    client = Anthropic()
    debut = time.time()
    with client.messages.stream(
        model=MODELE,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    ) as stream:
        message = stream.get_final_message()
    duree = time.time() - debut
    texte = message.content[0].text if message.content else ""
    texte = texte.strip()
    if texte.startswith("```"):
        texte = texte.split("```", 2)[1].lstrip("json").strip().rstrip("`").strip()
    return texte, {
        "tokens_entree": message.usage.input_tokens,
        "tokens_sortie": message.usage.output_tokens,
        "duree_s": round(duree, 1),
        "stop_reason": message.stop_reason,
    }


def parser_json_strict(texte: str, contexte: str):
    """Parse JSON avec UNE seule tentative de repli (extraction du bloc {…}).
    Si l'extraction échoue → RuntimeError clair et abort (pas de réparation
    automatique, cf. guardrails). Younes traite."""
    try:
        return json.loads(texte)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", texte, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise RuntimeError(
        f"Réponse LLM non parsable en JSON ({contexte}). "
        f"Aucune réparation automatique (cf. guardrails) — Younes traite. "
        f"Début de la réponse : {texte[:300]!r}"
    )


def cle_memoire(id_marche: str, numero_lot, id_user: str, timestamp: str) -> str:
    """memoire__<id_marche>__lot_<numero>__<id_user>__<timestamp>"""
    return f"memoire__{id_marche}__lot_{numero_lot}__{id_user}__{timestamp}"


def construire_contexte(memoire_obj: dict, brief: dict, profil: dict) -> dict:
    """Contexte d'assemblage .docx (page de garde, en-tête, chemin de sortie)
    dérivé d'un objet mémoire + brief + profil. Réutilisé par la génération
    initiale ET la régénération de section (ré-assemblage)."""
    id_marche = memoire_obj["id_marche"]
    numero_lot = memoire_obj["numero_lot"]
    intitule_marche = brief.get("intitule") or brief.get("objet") or id_marche
    organisme = ((profil.get("identite") or {}).get("raison_sociale")
                 or profil.get("id") or memoire_obj.get("id_user"))
    intitule_lot = memoire_obj.get("intitule_lot") or ""
    abrege = (intitule_marche or id_marche)[:48]
    genere_le = memoire_obj.get("genere_le") or ""
    date_lisible = genere_le[:10] if genere_le else ""
    return {
        "id_marche": id_marche,
        "numero_lot": numero_lot,
        "id_user": memoire_obj.get("id_user"),
        "timestamp": memoire_obj.get("timestamp") or "regen",
        "intitule_marche": intitule_marche,
        "intitule_lot": intitule_lot,
        "organisme": organisme,
        "entete": f"{abrege} — Lot {numero_lot}",
        "date_lisible": date_lisible,
    }


def cout_eur(usage: dict) -> float:
    """Coût € d'un appel à partir de son usage tokens (tarif Sonnet 4, budget.py)."""
    return budget.estimer_cout_eur(usage["tokens_entree"], usage["tokens_sortie"])
