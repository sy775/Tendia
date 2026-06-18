"""
scripts/audit_faux_criteres.py — audit des FAUX critères d'éligibilité.

Une alerte est considérée « critère d'éligibilité vérifiable » dès qu'elle reçoit une
`cle_canonique` du matcher (matching_exigences). Des bugs de substring (ex 'nda' dans
'caleNDAires', 'rge' dans 'urgence') peuvent classer à tort une alerte de CONTEXTE
(délai, visite, prix…) comme critère.

Ce script parcourt tous les briefs, évalue les alertes, et FLAGUE chaque clé dont le
mot-clé attendu n'apparaît pas comme un vrai mot dans l'alerte (= faux positif probable).
0 € (pas de LLM).

Usage : python scripts/audit_faux_criteres.py
"""
import os
import re
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import stockage
import organisme
import matching_exigences

# Pour chaque famille de clé : mots attendus (en frontière de mot) dans l'alerte.
ATTENDUS = {
    "nda_declare": ["nda", "déclaration", "declaration", "activité", "activite",
                    "qualiopi", "6351", "formation"],
    "ca_min": ["ca", "chiffre", "affaires", "affaire", "financière", "financiere",
               "économique", "economique", "seuil"],
    "qualification_experience": ["expérience", "experience", "ans", "années", "annees",
                                 "référence", "reference", "références", "references"],
    "pmsmp_reseau_entreprises": ["pmsmp", "immersion", "immersions", "entreprises"],
}
# Préfixes dynamiques
def _attendus_pour(cle):
    if cle in ATTENDUS:
        return ATTENDUS[cle]
    if cle.startswith("certif_"):
        # le nom de la certif est encodé dans la clé (certif_qualifelec_e2_3 → qualifelec)
        toks = [t for t in cle.split("_")[1:] if len(t) >= 3]
        return toks + ["certif", "qualif", "habilit", "agrément", "agrement", "rge",
                       "qualibat", "qualifelec", "iso", "mase", "cerff", "opqibi"]
    if cle.startswith("local_"):
        return ["local", "locaux", "présence", "presence", "implant", "lieu", "site"]
    if cle.startswith("qualification_bac"):
        return ["bac", "niveau", "diplôme", "diplome", "master", "licence"]
    return None  # clé inconnue → pas de vérif (on ne flague pas)


def _mot_present(mots, texte_lower):
    # Radical/substring : 'habilitation' contient 'habilit', 'qualification' contient 'qualif'.
    # (Le matcher, lui, utilise déjà des frontières de mot pour les clés courtes risquées.)
    for m in mots:
        if m.lower() in texte_lower:
            return True
    return False


# Indices que l'alerte est du CONTEXTE (pas un critère d'éligibilité) : si une alerte
# classée « critère » en contient, c'est un faux positif candidat même si un radical matche.
_CONTEXTE = ("délai de réponse", "calendaire", "visite des locaux", "visite de site",
             "coactivité", "co-activité", "planning", "pénalité", "penalite",
             "prix global", "forfaitaire", "réponse extrêmement court", "semaine 1")


def main():
    be = stockage.charger("briefs_extraits") or {}
    prof = organisme.lire_profil() or {}

    total_verif = 0
    par_cle = Counter()
    faux = []          # (mid, cle, texte)
    exemples_cle = defaultdict(list)

    for mid, b in be.items():
        alertes = b.get("alertes_candidat") or []
        if not alertes:
            continue
        for ae in matching_exigences.evaluer_alertes(alertes, prof):
            ev = ae.get("evaluation") or {}
            cle = ev.get("cle_canonique")
            if not cle:
                continue
            total_verif += 1
            par_cle[cle.split("_")[0] if cle.startswith(("certif", "local", "qualification"))
                    else cle] += 1
            texte = (ae.get("texte") or "")
            tl = texte.lower()
            attendus = _attendus_pour(cle)
            mot_absent = attendus is not None and not _mot_present(attendus, tl)
            est_contexte = any(c in tl for c in _CONTEXTE) and not _mot_present(
                ["certif", "qualif", "habilit", "agrément", "agrement", "qualibat",
                 "qualifelec", "rge", "iso", "mase", "cerff", "opqibi", "carte prof",
                 "inscription", "ca ", "chiffre d'aff"], tl)
            if mot_absent or est_contexte:
                faux.append((mid, cle, "contexte" if est_contexte else "mot-clé absent", texte[:90]))
            elif len(exemples_cle[cle]) < 1:
                exemples_cle[cle].append(texte[:60])

    print(f"=== Audit faux critères — {len(be)} briefs ===")
    print(f"Total alertes classées « critère vérifiable » : {total_verif}")
    print(f"Familles de clés : " + ", ".join(f"{k}={v}" for k, v in par_cle.most_common()))
    print()
    print(f"⚠ FAUX CRITÈRES PROBABLES : {len(faux)}")
    for mid, cle, raison, texte in faux[:40]:
        print(f"  [{mid}] cle={cle} · {raison}")
        print(f"      « {texte} »")
    if len(faux) > 40:
        print(f"  … +{len(faux) - 40} autres")


if __name__ == "__main__":
    main()
