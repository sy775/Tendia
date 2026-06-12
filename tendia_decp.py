"""
tendia_decp.py
--------------
Script de récupération des marchés notifiés France Travail depuis DECP.

Analogue à tendia_recup.py mais pour la collection `marches_notifies`.
Idempotent. Enrichit optionnellement les SIRET des titulaires via SIRENE.

Usage :
    python tendia_decp.py                # 2 ans, sans enrichissement
    python tendia_decp.py --annees 5
    python tendia_decp.py --enrichir     # appelle SIRENE pour les noms
    python tendia_decp.py --dry-run
"""

import argparse
import sys
import time
from collections import Counter
from datetime import datetime, timezone

import stockage
# Migration vers DECP consolidée (data.gouv.fr / Colin Maudry).
# L'ancien connecteur Opendatasoft est conservé en
# connecteurs/decp_opendatasoft.py.bak au cas où.
from connecteurs import decp_consolidee as decp


COLLECTION = "marches_notifies"


def recuperer(annees: int = 2,
              enrichir: bool = False,
              limite: int = None,
              dry_run: bool = False,
              verbose: bool = True) -> dict:
    """Récupère les marchés DECP et persiste dans marches_notifies."""

    if verbose:
        print()
        print("=" * 78)
        print(f"  TENDIA — Récupération DECP sur {annees} an(s)")
        print("=" * 78)
        print()

    debut = time.time()
    marches = decp.lister_marches_notifies(annees=annees, limite=limite,
                                             verbose=verbose)
    duree_decp = time.time() - debut

    if verbose:
        print(f"\n  → {len(marches)} marchés normalisés en {duree_decp:.1f}s")

    # Persistance avec idempotence
    deja_en_base = {} if dry_run else stockage.charger(COLLECTION)
    horodatage = datetime.now(timezone.utc).isoformat()

    nb_nouveaux = 0
    nb_maj = 0
    par_categorie = Counter()
    par_annee = Counter()
    sirets_titulaires = set()

    for m in marches:
        mid = m["id"]
        par_categorie[m.get("categorie_metier", "?")] += 1
        annee_notif = (m.get("date_notification") or "")[:4]
        if annee_notif:
            par_annee[annee_notif] += 1
        if m.get("titulaire_siret"):
            sirets_titulaires.add(m["titulaire_siret"])
        for st in m.get("co_titulaires_sirets", []) or []:
            sirets_titulaires.add(st)

        if mid in deja_en_base:
            existant = deja_en_base[mid]
            meta_anc = existant.get("meta_recuperation", {})
            version = meta_anc.get("version", 1) + 1
            date_premiere = meta_anc.get(
                "date_premiere_recuperation",
                meta_anc.get("date_recuperation", horodatage)
            )
            m_final = dict(m)
            m_final["meta_recuperation"] = {
                "date_premiere_recuperation": date_premiere,
                "date_derniere_recuperation": horodatage,
                "version": version,
                "source_connecteur": "DECP",
            }
            nb_maj += 1
        else:
            m_final = dict(m)
            m_final["meta_recuperation"] = {
                "date_premiere_recuperation": horodatage,
                "date_derniere_recuperation": horodatage,
                "version": 1,
                "source_connecteur": "DECP",
            }
            nb_nouveaux += 1

        if not dry_run:
            stockage.ecrire(COLLECTION, mid, m_final)

    if verbose:
        print()
        print("─" * 78)
        print("  Bilan persistance")
        print("─" * 78)
        print(f"  Nouveaux           : {nb_nouveaux}")
        print(f"  Mis à jour         : {nb_maj}")
        print(f"  SIRET titulaires uniques : {len(sirets_titulaires)}")
        print(f"  Par catégorie métier :")
        for cat, n in par_categorie.most_common():
            print(f"    {cat:<12} : {n}")
        print(f"  Par année de notification :")
        for annee in sorted(par_annee.keys(), reverse=True):
            print(f"    {annee} : {par_annee[annee]}")

    # Enrichissement optionnel
    if enrichir and not dry_run and sirets_titulaires:
        print()
        print("─" * 78)
        print(f"  Enrichissement SIRENE de {len(sirets_titulaires)} SIRET(s)")
        print("─" * 78)
        from enrichissement_sirene import enrichir_batch
        debut_enr = time.time()
        enrichir_batch(list(sirets_titulaires), verbose=verbose)
        duree_enr = time.time() - debut_enr
        print(f"  Enrichissement terminé en {duree_enr:.1f}s")

        # Mise à jour des marchés avec les noms des titulaires
        print(f"  Application des noms aux marchés...")
        marches_db = stockage.charger(COLLECTION)
        nb_maj_nom = 0
        for mid, m in marches_db.items():
            siret = m.get("titulaire_siret")
            if siret:
                from enrichissement_sirene import nom_pour_siret
                nom = nom_pour_siret(siret)
                if nom and m.get("titulaire_nom") != nom:
                    m["titulaire_nom"] = nom
                    stockage.ecrire(COLLECTION, mid, m)
                    nb_maj_nom += 1
        print(f"  {nb_maj_nom} marchés mis à jour avec les noms.")

    if verbose:
        print()
        print("=" * 78)
        if not dry_run:
            total = len(stockage.charger(COLLECTION))
            print(f"  Total marchés notifiés en base : {total}")
        else:
            print(f"  (dry-run, aucune écriture)")

    # --- Hook jointure BOAMP↔DECP (B6) ---
    # Met à jour data/jointure.json avec les marchés DECP ayant une
    # reference_acheteur. Idempotent.
    if not dry_run:
        try:
            import jointure
            marches_actuels = stockage.charger(COLLECTION)
            stats_join = jointure.synchroniser_tous_decp(marches_actuels,
                                                          verbose=False)
            if verbose:
                print(f"  Jointure : {stats_join['avec_ref']} marchés indexés "
                      f"par reference_acheteur ({stats_join['sans_ref']} sans ref)")
                s = jointure.stats()
                if s["complet"] > 0:
                    print(f"           : {s['complet']} paires complètes BOAMP+DECP")
        except Exception as e:
            if verbose:
                print(f"  ⚠ Hook jointure ignoré : {e}")

    return {
        "nb_recuperes": len(marches),
        "nb_nouveaux": nb_nouveaux,
        "nb_mis_a_jour": nb_maj,
        "par_categorie": dict(par_categorie),
        "par_annee": dict(par_annee),
        "sirets_titulaires_uniques": len(sirets_titulaires),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Récupération des marchés notifiés DECP France Travail."
    )
    parser.add_argument("--annees", type=int, default=2,
                        help="Profondeur en années (défaut 2).")
    parser.add_argument("--limite", type=int, default=None,
                        help="Plafond (debug).")
    parser.add_argument("--enrichir", action="store_true",
                        help="Enrichit les SIRET titulaires via SIRENE (~5min "
                             "pour 200 SIRETs).")
    parser.add_argument("--dry-run", action="store_true",
                        help="N'écrit rien.")
    args = parser.parse_args()

    recuperer(annees=args.annees, enrichir=args.enrichir,
               limite=args.limite, dry_run=args.dry_run, verbose=True)


if __name__ == "__main__":
    main()
