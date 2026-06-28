"""
audit_plateformes_dce.py
------------------------
Audit des plateformes de dématérialisation présentes dans les marchés captés et
de notre capacité à en récupérer les DCE.

Pour chaque marché disposant d'une `url_dce`, on détermine :
  - la PLATEFORME (famille déduite du domaine de l'URL) ;
  - l'OUTIL qui la reconnaît (parseur de tendia_telecharger_dce, càd a-t-on un
    downloader dédié, un fallback générique, ou rien) ;
  - l'ÉTAT du DCE déjà obtenu (`dce_contenu` : complet / incomplet / vide /
    auth_requise / erreur).

Le croisement met en évidence les plateformes où l'outillage manque ou échoue.

Usage : python audit_plateformes_dce.py
"""

from collections import Counter, defaultdict
from urllib.parse import urlparse

import stockage
import tendia_telecharger_dce as ttd


def famille_plateforme(url: str) -> str:
    """Domaine normalisé, avec regroupement des sous-domaines en marque blanche."""
    try:
        dom = urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return "(url invalide)"
    if not dom:
        return "(pas d'URL)"
    # e-marchespublics.com (Dematis) sert des centaines de sous-domaines acheteurs
    if dom.endswith("e-marchespublics.com"):
        return "*.e-marchespublics.com"
    return dom


def nom_outil(url: str) -> str:
    """Nom du parseur qui reconnaît l'URL (= outil de téléchargement)."""
    p = ttd.trouver_parseur(url)
    if p is None:
        return "AUCUN (auth/absent)"
    return type(p).__name__


# Niveau de maturité de chaque parseur (pour le verdict outillage).
OUTIL_MATURITE = {
    "ParseurAtexo":          "OK — downloader dédié (2-POST anonyme)",
    "ParseurAWS":            "OK — downloader dédié (ColdFusion + 2captcha)",
    "ParseurAchatpublic":    "OK — downloader dédié (workflow anonyme)",
    "ParseurEMarchesPublics": "STUB — pas de vrai workflow (générique, 0 pièce)",
    "ParseurGenerique":      "FALLBACK — parsing href générique, peu fiable",
    "AUCUN (auth/absent)":   "AUCUN — plateforme à authentification / sans URL",
}


def main():
    marches = stockage.charger("marches") or {}
    vals = list(marches.values())
    total = len(vals)

    sans_url = [v for v in vals if not (v.get("url_dce") or "").strip()]
    avec_url = [v for v in vals if (v.get("url_dce") or "").strip()]

    # --- Vue 1 : par OUTIL (parseur) ---
    par_outil = defaultdict(list)
    for v in avec_url:
        par_outil[nom_outil(v["url_dce"])].append(v)

    # --- Vue 2 : par PLATEFORME (domaine) ---
    par_plateforme = defaultdict(list)
    for v in avec_url:
        par_plateforme[famille_plateforme(v["url_dce"])].append(v)

    def repartition_contenu(lst):
        return dict(Counter(v.get("dce_contenu", "(inconnu)") for v in lst).most_common())

    print("=" * 78)
    print(f"AUDIT PLATEFORMES DCE — {total} marchés "
          f"({len(avec_url)} avec URL DCE, {len(sans_url)} sans)")
    print("=" * 78)

    print("\n### COUVERTURE PAR OUTIL (a-t-on un downloader ?)\n")
    ordre = ["ParseurAtexo", "ParseurAWS", "ParseurAchatpublic",
             "ParseurEMarchesPublics", "ParseurGenerique", "AUCUN (auth/absent)"]
    for outil in sorted(par_outil, key=lambda o: ordre.index(o) if o in ordre else 99):
        lst = par_outil[outil]
        complets = sum(1 for v in lst if v.get("dce_contenu") == "complet")
        print(f"  {outil:24} {len(lst):4} marchés  | {complets:3} complets  "
              f"| {OUTIL_MATURITE.get(outil, '?')}")
        print(f"  {'':24}      contenu : {repartition_contenu(lst)}")

    print("\n### DÉTAIL PAR PLATEFORME (domaine)\n")
    for plat, lst in sorted(par_plateforme.items(), key=lambda kv: -len(kv[1])):
        outils = Counter(nom_outil(v["url_dce"]) for v in lst)
        outil_principal = outils.most_common(1)[0][0]
        print(f"  {plat:34} {len(lst):4} | outil: {outil_principal:22} "
              f"| {repartition_contenu(lst)}")

    # --- Synthèse actionnable ---
    print("\n### SYNTHÈSE\n")
    incomplets = sum(1 for v in vals if v.get("dce_contenu") == "incomplet")
    vides = sum(1 for v in vals if v.get("dce_contenu") == "vide")
    complets = sum(1 for v in vals if v.get("dce_contenu") == "complet")
    print(f"  DCE complets    : {complets}")
    print(f"  DCE incomplets  : {incomplets}")
    print(f"  DCE vides       : {vides}")
    print(f"  Sans URL DCE    : {len(sans_url)}")
    stub = par_outil.get("ParseurEMarchesPublics", [])
    if stub:
        print(f"\n  ⚠ e-marchespublics.com (Dematis) : {len(stub)} marchés, "
              f"AUCUN complet — downloader à écrire (outil le plus rentable à bâtir).")


if __name__ == "__main__":
    main()
