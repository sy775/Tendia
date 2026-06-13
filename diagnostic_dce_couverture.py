"""
Diagnostic couverture DCE plateformes — Sprint Couverture Phase 1.

Lit la base Tendia (kv_storage SQLite) et produit un rapport sur :
1. Volume de marchés ayant un DCE accessible (URL plateforme) vs non
2. Répartition par plateforme source des URL DCE détectées
3. Pour chaque plateforme : nombre de marchés, nombre de DCE déjà
   téléchargés vs non téléchargés, exemples d'URL pour inspection

Lance-le tel quel :  python diagnostic_dce_couverture.py
Sortie console + fichier diagnostic_dce_couverture_<date>.txt
"""
import io
import sys
import os
import json
import sqlite3
import re
from collections import Counter, defaultdict
from datetime import datetime
from urllib.parse import urlparse

# Force UTF-8 pour Windows PowerShell
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = "data/tendia.db"
DCE_DIR = "data/dce"  # adapté si chemin différent — sera autodetected si besoin

# Patterns plateformes connues (élargir si tu en vois d'autres dans les URL)
PATTERNS_PLATEFORMES = [
    ("DEMATIS", [r"dematis", r"\.dematis\.com", r"marchepublic-dematis"]),
    ("achatpublic", [r"achatpublic\.com"]),
    ("marches-securises", [r"marches-securises\.fr"]),
    ("PLACE", [r"place\.marches-publics\.gouv\.fr", r"\bplace\b.*marches"]),
    ("mpe-quebec", [r"mpe-quebec"]),  # peu probable mais on log si trouvé
    ("e-marchespublics", [r"e-marchespublics\.com"]),
    ("klekoon", [r"klekoon"]),
    ("francemarches", [r"francemarches\.com", r"france-marches"]),
    ("megalis", [r"megalisbretagne", r"megalis"]),
    ("territoires-numeriques", [r"territoires-numeriques"]),
    ("centraledesmarches", [r"centraledesmarches"]),
    ("achatpublic_vdef", [r"achatpublic"]),  # capture URLs achatpublic non matchées par .com
    ("BOAMP_redirect", [r"boamp\.fr"]),  # URLs qui restent sur BOAMP = pas de plateforme tierce
    ("TED_direct", [r"ted\.europa\.eu"]),
    ("autre_gouv", [r"\.gouv\.fr"]),
]


def detecter_plateforme(url):
    """Renvoie le code plateforme pour une URL donnée, ou 'inconnue'."""
    if not url:
        return "absente"
    url_lower = url.lower()
    for code, patterns in PATTERNS_PLATEFORMES:
        for p in patterns:
            if re.search(p, url_lower):
                return code
    # Fallback : extraire le domaine
    try:
        host = urlparse(url).netloc.lower()
        if host:
            return f"autre[{host}]"
    except Exception:
        pass
    return "inconnue"


def charger_marches(conn):
    """Charge tous les marchés de la collection 'marches'."""
    cur = conn.execute(
        "SELECT id, contenu_json FROM kv_storage WHERE collection='marches'"
    )
    marches = {}
    for mid, contenu in cur.fetchall():
        try:
            marches[mid] = json.loads(contenu)
        except Exception:
            marches[mid] = None
    return marches


def charger_briefs(conn):
    """Charge tous les briefs extraits."""
    cur = conn.execute(
        "SELECT id, contenu_json FROM kv_storage WHERE collection='briefs_extraits'"
    )
    briefs = {}
    for bid, contenu in cur.fetchall():
        try:
            briefs[bid] = json.loads(contenu)
        except Exception:
            briefs[bid] = None
    return briefs


def lister_dce_telecharges(dce_dir):
    """Liste les répertoires DCE téléchargés (1 répertoire par marché en général)."""
    if not os.path.isdir(dce_dir):
        return set()
    return set(os.listdir(dce_dir))


def extraire_url_dce(marche, brief):
    """Cherche l'URL DCE dans plusieurs endroits du marché et du brief.

    Renvoie la 1ère URL trouvée, ou None.
    """
    candidats = []

    if marche:
        for cle in ("url_dce", "url_documents", "lien_dce", "lien_documents",
                    "url_consultation", "url_acces_dce"):
            v = marche.get(cle)
            if v and isinstance(v, str):
                candidats.append(v)
        # Cas BOAMP : URL souvent dans un champ imbriqué
        for cle in ("liens", "documents", "donnees_brutes"):
            v = marche.get(cle)
            if isinstance(v, dict):
                for sub in v.values():
                    if isinstance(sub, str) and sub.startswith("http"):
                        candidats.append(sub)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, str) and item.startswith("http"):
                        candidats.append(item)
                    elif isinstance(item, dict):
                        for sub in item.values():
                            if isinstance(sub, str) and sub.startswith("http"):
                                candidats.append(sub)

    if brief:
        for cle in ("url_dce", "url_documents", "lien_dce", "lien_consultation"):
            v = brief.get(cle)
            if v and isinstance(v, str):
                candidats.append(v)

    # On préfère une URL plateforme tierce à une URL BOAMP/TED
    candidats_filtres = [c for c in candidats if "boamp.fr" not in c.lower()
                          and "ted.europa.eu" not in c.lower()]
    if candidats_filtres:
        return candidats_filtres[0]
    return candidats[0] if candidats else None


def detecter_richesse_brief(brief):
    """Heuristique : un brief est 'riche' s'il a >= 4 sections Phase 3b remplies."""
    if not brief:
        return "absent"
    sections_phase_3b = [
        "caracteristiques_techniques_chantier",
        "caracteristiques_mission_moe",
        "caracteristiques_mission_it",
        "caracteristiques_mission_conseil",
        "qualifications_requises",
        "qualifications_moe",
        "alertes_candidat",
        "bareme_notation",
        "lots",
        "tranches",
    ]
    non_vides = 0
    for s in sections_phase_3b:
        v = brief.get(s)
        if v and (isinstance(v, dict) and v) or (isinstance(v, list) and v):
            non_vides += 1
    if non_vides >= 4:
        return "complet"
    if non_vides >= 2:
        return "partiel"
    return "light"


def main():
    if not os.path.exists(DB_PATH):
        print(f"ERREUR : {DB_PATH} introuvable. Lance depuis la racine Tendia.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    marches = charger_marches(conn)
    briefs = charger_briefs(conn)
    dce_telecharges = lister_dce_telecharges(DCE_DIR)
    conn.close()

    print(f"=== DIAGNOSTIC COUVERTURE DCE — {datetime.now():%Y-%m-%d %H:%M} ===")
    print()
    print(f"Marchés en base       : {len(marches)}")
    print(f"Briefs extraits       : {len(briefs)}")
    print(f"DCE téléchargés (rép) : {len(dce_telecharges)} (dans {DCE_DIR})")
    print()

    # ======== 1) Répartition URL DCE détectée par plateforme ========
    print("=" * 60)
    print("1) URL DCE détectée : répartition par plateforme")
    print("=" * 60)

    par_plateforme = Counter()
    par_plateforme_telecharge = defaultdict(lambda: {"avec_dce": 0, "sans_dce": 0,
                                                      "exemples": []})
    par_plateforme_brief = defaultdict(lambda: {"complet": 0, "partiel": 0,
                                                 "light": 0, "absent": 0})

    for mid, marche in marches.items():
        brief = briefs.get(mid)
        url = extraire_url_dce(marche, brief)
        plateforme = detecter_plateforme(url)
        par_plateforme[plateforme] += 1

        dce_present = mid in dce_telecharges
        if dce_present:
            par_plateforme_telecharge[plateforme]["avec_dce"] += 1
        else:
            par_plateforme_telecharge[plateforme]["sans_dce"] += 1
            if len(par_plateforme_telecharge[plateforme]["exemples"]) < 3 and url:
                par_plateforme_telecharge[plateforme]["exemples"].append(
                    f"  {mid} → {url[:120]}"
                )

        richesse = detecter_richesse_brief(brief)
        par_plateforme_brief[plateforme][richesse] += 1

    print(f"{'Plateforme':<28} {'Total':>7} {'Avec DCE':>10} {'Sans DCE':>10}")
    print("-" * 60)
    for plateforme, total in par_plateforme.most_common():
        dce_info = par_plateforme_telecharge[plateforme]
        print(f"{plateforme:<28} {total:>7} {dce_info['avec_dce']:>10} "
              f"{dce_info['sans_dce']:>10}")
    print()

    # ======== 2) Détail par plateforme : exemples d'URL non téléchargées ========
    print("=" * 60)
    print("2) Exemples d'URL non téléchargées par plateforme")
    print("   (= cibles potentielles pour Sprint Couverture Phase 2)")
    print("=" * 60)
    for plateforme in par_plateforme:
        info = par_plateforme_telecharge[plateforme]
        if info["sans_dce"] > 0 and info["exemples"]:
            print(f"\n--- {plateforme} ({info['sans_dce']} marchés sans DCE) ---")
            for ex in info["exemples"]:
                print(ex)

    # ======== 3) Qualité des briefs par plateforme ========
    print()
    print("=" * 60)
    print("3) Qualité des briefs par plateforme")
    print("   (proxy : combien de sections Phase 3b remplies)")
    print("=" * 60)
    print(f"{'Plateforme':<28} {'Complet':>9} {'Partiel':>9} {'Light':>9} "
          f"{'Absent':>9}")
    print("-" * 70)
    for plateforme in par_plateforme:
        info = par_plateforme_brief[plateforme]
        print(f"{plateforme:<28} {info['complet']:>9} {info['partiel']:>9} "
              f"{info['light']:>9} {info['absent']:>9}")
    print()

    # ======== 4) Synthèse pour priorisation Phase 2 ========
    print("=" * 60)
    print("4) Synthèse pour priorisation Sprint Couverture Phase 2")
    print("=" * 60)

    cibles_potentielles = []
    for plateforme, info in par_plateforme_telecharge.items():
        if plateforme in ("absente", "inconnue", "BOAMP_redirect", "TED_direct"):
            continue  # pas une vraie plateforme tierce
        if info["sans_dce"] >= 5:
            cibles_potentielles.append((info["sans_dce"], plateforme,
                                         info["avec_dce"]))

    cibles_potentielles.sort(reverse=True)

    if cibles_potentielles:
        print("Plateformes avec >= 5 marchés non téléchargés (ordre priorité) :")
        for sans, plateforme, avec in cibles_potentielles:
            ratio_couverture = avec / (avec + sans) * 100 if (avec + sans) else 0
            print(f"  • {plateforme:<22} : {sans} non téléchargés "
                  f"(couverture actuelle : {ratio_couverture:.0f}%)")
    else:
        print("Aucune plateforme tierce avec >= 5 marchés non téléchargés détectée.")

    print()
    nb_sans_url = par_plateforme.get("absente", 0)
    if nb_sans_url:
        print(f"⚠ {nb_sans_url} marchés n'ont AUCUNE URL DCE détectable.")
        print("  Causes possibles : marché simple sans DCE, brief minimal,")
        print("  ou champ URL stocké dans une clé non scannée par ce script.")

    nb_inconnue = par_plateforme.get("inconnue", 0)
    if nb_inconnue:
        print(f"⚠ {nb_inconnue} marchés avec URL DCE mais plateforme NON identifiée.")
        print("  → vérifie les exemples ci-dessus, peut-être un pattern à ajouter.")

    print()
    print("=" * 60)
    print("FIN DIAGNOSTIC")
    print("=" * 60)


if __name__ == "__main__":
    main()
