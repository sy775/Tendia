# -*- coding: utf-8 -*-
"""
scripts/maintenance/rattrapage_btp_octobre.py
---------------------------------------------
Rattrapage des marchés BTP d'octobre 2026 (chantier 1) : sélection, DCE, briefs.

Sous-commandes (toutes avec --dry-run : rien n'est écrit, aucun appel réseau ni LLM) :

  cibles
      Marchés publiés en 2026-10, classés btp_* (classifications_ia) ou
      type_marche == "TRAVAUX", hors avis d'attribution, date limite >= aujourd'hui.
      Écrit data/rattrapage_btp_octobre_ids.txt (un id par ligne, date limite
      décroissante) et affiche un tableau par plateforme (url_profil_acheteur, à défaut url_dce).

  dce --max N --max-dedies M [--duree-max-min 120]
      Pour les ids du fichier sans dce_contenu == "complet" (date limite
      décroissante, N au plus) : résolution d'URL (dce/resolution) des marchés sans
      url_dce, puis téléchargement anonyme (dce/telecharger), écriture unitaire par
      marché. Puis connecteurs dédiés (AWS, Dematis, xmarches, marches-securises)
      avec --max M, seulement aux heures de bureau (jamais --ignorer-heures).
      Tableau avant/après par plateforme : url résolue, téléchargé, complet.

  briefs --max-cout EUR --max N
      Extraction LLM (analyse/extraire.traiter_marche) des ids du fichier à DCE
      complet et sans brief complet, date limite décroissante ; arrêt dès que le
      coût cumulé de la passe atteint --max-cout. Tableau id, date limite,
      plateforme, coût.

Le proxy résidentiel est autorisé (TENDIA_PROXY_ACTIF=1).
"""
import argparse
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from urllib.parse import urlparse

from tendia.core import chemins, stockage
from tendia.core.etat_marche import est_attribution  # noqa: F401  (R.est_attribution dans les tests)

MOIS_CIBLE = "2026-10"
NOM_FICHIER_IDS = "rattrapage_btp_octobre_ids.txt"
SCRIPTS_DEDIES = ("retelecharger_aws_achat_anti_ban.py", "retelecharger_dematis_anti_ban.py",
                  "retelecharger_xmarches.py", "retelecharger_marches_securises.py")


# ---------------------------------------------------------------------------
# Sélection (pure, testée hors ligne)
# ---------------------------------------------------------------------------

def fichier_ids():
    return chemins.DATA / NOM_FICHIER_IDS


def est_btp(id_marche: str, marche: dict, classifs: dict) -> bool:
    """Classé btp_* par la classification IA, ou type_marche == TRAVAUX."""
    doms = ((classifs.get(id_marche) or {}).get("domaines_metier")) or []
    if any(str(d.get("code") or "").startswith("btp_") for d in doms if isinstance(d, dict)):
        return True
    return (marche.get("type_marche") or "").upper() == "TRAVAUX"


def plateforme(marche: dict) -> str:
    """Domaine du profil acheteur (url_profil_acheteur) ; à défaut, domaine de url_dce
    (le profil manque sur ~85 % des avis) ; « (aucune) » sinon."""
    url = (marche.get("url_profil_acheteur") or marche.get("url_dce") or "").strip()
    if not url:
        return "(aucune)"
    if "://" not in url:
        url = "https://" + url
    hote = (urlparse(url).netloc or "").lower()
    return hote[4:] if hote.startswith("www.") else (hote or "(aucune)")


def _date_limite(marche: dict) -> str:
    return (marche.get("date_limite_depot") or "")[:10]


def _tri_date_limite_decroissante(ids, marches):
    return sorted(ids, key=lambda i: (_date_limite(marches[i]), i), reverse=True)


def selectionner_cibles(marches: dict, classifs: dict, aujourd_hui: str,
                        mois: str = MOIS_CIBLE) -> list:
    """Ids BTP publiés dans `mois`, hors attribution, date limite >= aujourd_hui,
    triés par date limite décroissante."""
    ids = [i for i, m in marches.items()
           if (m.get("date_publication") or "")[:7] == mois
           and est_btp(i, m, classifs)
           and not est_attribution(m)
           and _date_limite(m) >= aujourd_hui]
    return _tri_date_limite_decroissante(ids, marches)


def selectionner_dce(ids, marches: dict, max_n: int = None) -> list:
    """Ids sans DCE complet, date limite décroissante, `max_n` au plus."""
    restants = [i for i in ids if i in marches and marches[i].get("dce_contenu") != "complet"]
    restants = _tri_date_limite_decroissante(restants, marches)
    return restants[:max_n] if max_n is not None else restants


def a_brief_complet(id_marche: str, briefs: dict) -> bool:
    return ((briefs.get(id_marche) or {}).get("_meta") or {}).get("type") == "complet"


def selectionner_briefs(ids, marches: dict, briefs: dict, max_n: int = None) -> list:
    """Ids à DCE complet et sans brief complet, date limite décroissante."""
    restants = [i for i in ids if i in marches
                and marches[i].get("dce_contenu") == "complet"
                and not a_brief_complet(i, briefs)]
    restants = _tri_date_limite_decroissante(restants, marches)
    return restants[:max_n] if max_n is not None else restants


def tableau_plateformes(ids, marches: dict) -> dict:
    """{plateforme: Counter(cibles, url_resolue, telecharge, complet)}."""
    t = defaultdict(Counter)
    for i in ids:
        m = marches.get(i) or {}
        c = t[plateforme(m)]
        c["cibles"] += 1
        c["url_resolue"] += bool((m.get("url_dce") or "").strip())
        c["telecharge"] += m.get("dce_telechargement_statut") in ("ok", "skip_deja_fait") \
            or bool(m.get("dce_contenu"))
        c["complet"] += m.get("dce_contenu") == "complet"
    return dict(t)


def lire_ids() -> list:
    f = fichier_ids()
    if not f.is_file():
        sys.exit(f"Fichier {f} absent : lance d'abord la sous-commande « cibles ».")
    return [l.strip() for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]


# ---------------------------------------------------------------------------
# Affichage
# ---------------------------------------------------------------------------

COLONNES = ("cibles", "url_resolue", "telecharge", "complet")


def afficher_tableau(titre: str, tab: dict, avant: dict = None):
    print(f"\n  {titre}")
    entete = "  " + f"{'plateforme':<42}" + "".join(f"{c:>13}" for c in COLONNES)
    print(entete)
    print("  " + "─" * (len(entete) - 2))
    totaux = Counter()
    for p in sorted(tab, key=lambda k: (-tab[k]["cibles"], k)):
        c = tab[p]
        totaux.update(c)
        cellules = []
        for col in COLONNES:
            v = c[col]
            if avant is not None and col != "cibles":
                cellules.append(f"{(avant.get(p) or Counter())[col]}→{v}".rjust(13))
            else:
                cellules.append(f"{v:>13}")
        print(f"  {p[:42]:<42}" + "".join(cellules))
    if avant is not None:
        tot_avant = Counter()
        for c in avant.values():
            tot_avant.update(c)
        print("  " + f"{'TOTAL':<42}" + "".join(
            (f"{tot_avant[col]}→{totaux[col]}" if col != "cibles" else str(totaux[col])).rjust(13)
            for col in COLONNES))
    else:
        print("  " + f"{'TOTAL':<42}" + "".join(f"{totaux[col]:>13}" for col in COLONNES))


# ---------------------------------------------------------------------------
# Sous-commandes
# ---------------------------------------------------------------------------

def cmd_cibles(args):
    marches = stockage.charger("marches") or {}
    classifs = stockage.charger("classifications_ia") or {}
    aujourd_hui = date.today().isoformat()
    ids = selectionner_cibles(marches, classifs, aujourd_hui)
    print(f"  Marchés {MOIS_CIBLE} BTP, hors attribution, date limite >= {aujourd_hui} : {len(ids)}")
    afficher_tableau("Cibles par plateforme (url_profil_acheteur, à défaut url_dce)", tableau_plateformes(ids, marches))
    if args.dry_run:
        print(f"\n  [DRY-RUN] {fichier_ids()} non écrit.")
        return ids
    fichier_ids().write_text("\n".join(ids) + ("\n" if ids else ""), encoding="utf-8")
    print(f"\n  ✓ {len(ids)} id écrits dans {fichier_ids()}")
    return ids


def cmd_dce(args):
    from tendia.core import http_humain
    from tendia.dce import resolution, telecharger

    ids = lire_ids()
    marches = stockage.charger("marches") or {}
    avant = tableau_plateformes(ids, marches)
    selection = selectionner_dce(ids, marches, args.max)
    sans_url = [i for i in selection if not (marches[i].get("url_dce") or "").strip()]
    print(f"  Cibles : {len(ids)} ; sans DCE complet : {len(selectionner_dce(ids, marches))} ; "
          f"passe : {len(selection)} (--max {args.max}), dont {len(sans_url)} sans url_dce")
    if args.dry_run:
        for i in selection:
            print(f"    {i}  {_date_limite(marches[i])}  {plateforme(marches[i])}")
        print("\n  [DRY-RUN] aucune résolution, aucun téléchargement.")
        return

    debut = time.time()
    limite_s = args.duree_max_min * 60

    def temps_ecoule():
        return time.time() - debut >= limite_s

    # 1. Résolution d'URL (écriture unitaire par marché dans resolution.traiter)
    if sans_url:
        print(f"\n  ── Résolution d'URL : {len(sans_url)} marché(s)")
        resolution.traiter(ids=sans_url, verbose=False)

    # 2. Téléchargement anonyme, écriture unitaire par marché
    marches = stockage.charger("marches") or {}
    a_telecharger = [i for i in selection if (marches[i].get("url_dce") or "").strip()]
    print(f"\n  ── Téléchargement anonyme : {len(a_telecharger)} marché(s) avec url_dce")
    import requests
    session = requests.Session()
    session.headers.update({
        "User-Agent": telecharger.USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
    })
    for n, mid in enumerate(a_telecharger, 1):
        if temps_ecoule():
            print(f"  ⏱ Durée maximale ({args.duree_max_min} min) atteinte : arrêt avant {mid}.")
            break
        marche = stockage.lire("marches", mid)
        try:
            res = telecharger._telecharger_marche(marche, session, force=False,
                                                  dry_run=False, verbose=False)
        except Exception as e:
            res = {"statut": "erreur_reseau", "raison": f"{type(e).__name__}: {e}"[:200],
                   "nb_fichiers": 0}
        telecharger.marquer_resultat_telechargement(marche, mid, res)
        stockage.ecrire("marches", mid, marche)
        print(f"  [{n}/{len(a_telecharger)}] {mid}  {res['statut']}  "
              f"{marche.get('dce_contenu') or ''}  {(res.get('raison') or '')[:70]}")

    # 3. Connecteurs dédiés, aux heures de bureau seulement
    if args.max_dedies <= 0:
        print("\n  ── Connecteurs dédiés : --max-dedies 0, sautés.")
    elif not http_humain.heure_actuelle_est_bureau():
        print("\n  ── Connecteurs dédiés : hors heures de bureau (8h-19h lun-ven), sautés "
              "(pas de --ignorer-heures).")
    else:
        for script in SCRIPTS_DEDIES:
            if temps_ecoule():
                print(f"  ⏱ Durée maximale atteinte : {script} non lancé.")
                break
            cmd = [sys.executable, str(chemins.RACINE_DEPOT / "scripts" / "maintenance" / script),
                   "--oui", "--max", str(args.max_dedies)]
            print(f"\n  ── {script} --max {args.max_dedies}")
            reste_s = max(60, limite_s - (time.time() - debut))
            try:
                subprocess.run(cmd, cwd=chemins.RACINE_DEPOT, timeout=reste_s, check=False)
            except subprocess.TimeoutExpired:
                print(f"  ⏱ {script} interrompu (durée maximale).")

    stockage.invalider_cache("marches")
    marches = stockage.charger("marches") or {}
    afficher_tableau("DCE octobre par plateforme (avant → après)",
                     tableau_plateformes(ids, marches), avant=avant)
    print(f"\n  Durée : {int(time.time() - debut)} s")


def cmd_briefs(args):
    from tendia.analyse import extraire, pdf_extract

    ids = lire_ids()
    marches = stockage.charger("marches") or {}
    briefs = stockage.charger("briefs_extraits") or {}
    selection = selectionner_briefs(ids, marches, briefs, args.max)
    print(f"  Cibles à DCE complet sans brief complet : "
          f"{len(selectionner_briefs(ids, marches, briefs))} ; passe : {len(selection)} "
          f"(--max {args.max}, --max-cout {args.max_cout:.2f} €)")
    if args.dry_run:
        for i in selection:
            print(f"    {i}  {_date_limite(marches[i])}  {plateforme(marches[i])}")
        print("\n  [DRY-RUN] aucun appel LLM.")
        return

    etat = extraire._charger_etat()
    cout_cumule = 0.0
    lignes = []
    for mid in selection:
        if extraire.plafond_atteint(cout_cumule, args.max_cout):
            print(f"\n  ⛔ Plafond --max-cout atteint : {cout_cumule:.3f} € ≥ "
                  f"{args.max_cout:.2f} €. Arrêt avant {mid}.")
            break
        dossier = os.path.join(extraire.REPERTOIRE_DCE, mid)
        extraire._dezipper_dossier(dossier, verbose=False)
        pdfs = pdf_extract.extraire_dossier(dossier, verbose=False)
        if not pdfs:
            lignes.append((mid, 0.0, "aucun PDF"))
            print(f"  {mid}  ⊘ aucun PDF exploitable")
            continue
        res = extraire.traiter_marche(mid, dossier, pdfs, dry_run=False, verbose=False)
        cout = extraire.cout_du_resultat(res)
        cout_cumule += cout
        if res.get("ok") and res.get("extraction"):
            etat[mid] = {"signature_pdfs": extraire._signature_pdfs(pdfs),
                         "extrait_le": time.strftime("%Y-%m-%dT%H:%M:%S"),
                         "pdfs": list(pdfs.keys())}
            extraire._sauver_etat(etat)
        statut = "ok" if res.get("ok") else (res.get("raison") or res.get("erreur") or "échec")
        lignes.append((mid, cout, statut))
        print(f"  {mid}  {statut}  {cout:.3f} €  (cumul {cout_cumule:.3f} €)")

    print(f"\n  {'id':<20}{'date limite':>12}  {'plateforme':<34}{'coût €':>8}  statut")
    for mid, cout, statut in lignes:
        m = marches.get(mid) or {}
        print(f"  {mid:<20}{_date_limite(m):>12}  {plateforme(m)[:34]:<34}{cout:>8.3f}  {statut}")
    print(f"\n  Coût de la passe : {cout_cumule:.3f} € ; briefs ok : "
          f"{sum(1 for l in lignes if l[2] == 'ok')}")


def main(argv=None):
    os.environ.setdefault("TENDIA_PROXY_ACTIF", "1")  # proxy résidentiel autorisé (lanceur de téléchargements)
    ap = argparse.ArgumentParser(prog="rattrapage_btp_octobre.py",
                                 description="Rattrapage des marchés BTP d'octobre 2026.")
    sous = ap.add_subparsers(dest="commande", required=True)
    pc = sous.add_parser("cibles", help="liste les cibles et écrit le fichier d'ids")
    pc.add_argument("--dry-run", action="store_true")
    pc.set_defaults(func=cmd_cibles)
    pd = sous.add_parser("dce", help="résolution d'URL et téléchargement des DCE")
    pd.add_argument("--max", type=int, required=True, help="marchés traités au plus")
    pd.add_argument("--max-dedies", type=int, required=True,
                    help="cap transmis aux connecteurs dédiés (0 : sautés)")
    pd.add_argument("--duree-max-min", type=int, default=120,
                    help="durée maximale d'horloge (défaut : 120 min)")
    pd.add_argument("--dry-run", action="store_true")
    pd.set_defaults(func=cmd_dce)
    pb = sous.add_parser("briefs", help="extraction LLM des DCE complets")
    pb.add_argument("--max-cout", type=float, required=True, metavar="EUR")
    pb.add_argument("--max", type=int, required=True)
    pb.add_argument("--dry-run", action="store_true")
    pb.set_defaults(func=cmd_briefs)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
