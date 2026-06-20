"""
tendia_recup.py
---------------
Script principal de récupération des marchés publics pour Tendia.

Appelle les connecteurs enregistrés (actuellement : BOAMP), normalise les
résultats au format unifié, dédoublonne par `id` (= SOURCE-reference),
et écrit/met à jour la base SQLite via stockage.py.

Idempotent : peut être relancé autant de fois que voulu. Sur un marché
déjà connu, on incrémente `meta_recuperation.version` au lieu de créer
un doublon.

Usage :
    python tendia_recup.py                    # défaut : 6 mois, BOAMP, mode legacy FT
    python tendia_recup.py --large            # Sprint 3 : ingestion large
    python tendia_recup.py --mois 3
    python tendia_recup.py --limite 50        # plafond debug
    python tendia_recup.py --dry-run          # n'écrit rien, montre juste
"""

import argparse
import sys
import time
from datetime import datetime, timezone
from collections import Counter

import stockage
import connecteurs


COLLECTION = "marches"


# ---------------------------------------------------------------------------
# Récupération + persistance
# ---------------------------------------------------------------------------

def recuperer_tout(fenetre_mois: int = 6,
                    sources: list = None,
                    limite_par_source: int = None,
                    mode_large: bool = False,
                    differentiel: bool = False,
                    dry_run: bool = False,
                    verbose: bool = True) -> dict:
    """
    Appelle les connecteurs, normalise et persiste les marchés en base.

    Args:
        fenetre_mois: profondeur de récupération en mois.
        sources: liste de codes SOURCE à inclure (None = toutes).
        limite_par_source: cap par connecteur (debug).
        mode_large: si True, ingestion sans filtre par acheteur (Sprint 3).
                    Capte tous les marchés publics, le filtrage par preset
                    se fait à l'analyse. Si False (défaut), mode legacy
                    avec filtre par France Travail/Pôle Emploi.
        dry_run: si True, ne touche pas à la base.
        verbose: affichage console.

    Returns:
        dict avec stats : { sources_appelees, nb_recuperes, nb_nouveaux,
                            nb_mis_a_jour, par_source, par_categorie }
    """
    sources_dispo = connecteurs.sources_disponibles()
    if sources:
        sources_a_appeler = [s for s in sources if s in sources_dispo]
        sources_inconnues = [s for s in sources if s not in sources_dispo]
        if sources_inconnues:
            print(f"⚠ Sources inconnues ignorées : {sources_inconnues}",
                  file=sys.stderr)
    else:
        sources_a_appeler = sources_dispo

    if verbose:
        print()
        print("=" * 78)
        print(f"  TENDIA — Récupération sur {fenetre_mois} mois")
        print("=" * 78)
        print(f"  Sources actives : {', '.join(sources_a_appeler)}")
        if mode_large:
            print(f"  Mode             : INGESTION LARGE (Sprint 3, sans filtre acheteur)")
        else:
            print(f"  Mode             : legacy (filtre France Travail)")
        if dry_run:
            print(f"  Mode dry-run : aucune écriture en base.")
        print()

    # Charge l'existant pour identifier les doublons
    deja_en_base = {} if dry_run else stockage.charger(COLLECTION)
    if verbose:
        print(f"  Existant en base : {len(deja_en_base)} marchés")

    # Mode DIFFÉRENTIEL : on ne récupère QUE ce qui est postérieur au dernier
    # avis connu (borne basse de date côté API) et on n'écrit QUE les nouveaux
    # (les existants ne sont ni re-fetchés à fond, ni ré-écrits). Évite de
    # re-télécharger tout le window à chaque passe (utile + ménage l'hôte BOAMP).
    date_min = None
    if differentiel:
        dates_connues = [m.get("date_publication") for m in deja_en_base.values()
                         if isinstance(m, dict) and m.get("date_publication")]
        if dates_connues:
            date_min = max(dates_connues)[:10]
        if verbose:
            print(f"  Mode             : DIFFÉRENTIEL"
                  f"{f' (depuis {date_min})' if date_min else ' (base vide → fenêtre complète)'}")

    stats = {
        "sources_appelees": sources_a_appeler,
        "nb_recuperes": 0,
        "nb_nouveaux": 0,
        "nb_mis_a_jour": 0,
        "par_source": {},
        "par_categorie": Counter(),
        "duree_par_source_s": {},
    }

    nouveaux_marches: list = []

    for module in connecteurs.tous_les_connecteurs():
        code_source = getattr(module, "SOURCE", "?")
        if code_source not in sources_a_appeler:
            continue

        if verbose:
            print()
            print("─" * 78)
            print(f"  Connecteur : {code_source}")
            print("─" * 78)

        debut = time.time()
        try:
            marches_source = module.lister_marches(
                fenetre_mois=fenetre_mois,
                limite=limite_par_source,
                filtre_acheteur=(not mode_large),
                inclure_autre=mode_large,
                date_min=date_min,
                verbose=verbose,
            )
        except Exception as e:
            print(f"  ❌ Erreur sur {code_source} : {type(e).__name__}: {e}",
                  file=sys.stderr)
            marches_source = []

        duree = time.time() - debut
        stats["duree_par_source_s"][code_source] = round(duree, 1)
        stats["par_source"][code_source] = len(marches_source)
        stats["nb_recuperes"] += len(marches_source)

        if verbose:
            print(f"  → {len(marches_source)} marchés récupérés depuis {code_source} "
                  f"en {duree:.1f}s")

        nouveaux_marches.extend(marches_source)

    # Persistance avec dédup
    if verbose:
        print()
        print("─" * 78)
        print(f"  Persistance")
        print("─" * 78)

    horodatage = datetime.now(timezone.utc).isoformat()

    for m in nouveaux_marches:
        mid = m["id"]
        stats["par_categorie"][m.get("categorie_metier", "?")] += 1

        if differentiel and mid in deja_en_base:
            # Mode différentiel : on n'écrit QUE les nouveaux. Les marchés déjà
            # connus (re-captés par recouvrement de date au même jour) sont
            # ignorés — aucune ré-écriture, aucun bump de version.
            stats["nb_ignores_existants"] = stats.get("nb_ignores_existants", 0) + 1
            continue

        if mid in deja_en_base:
            # Mise à jour : on conserve la date de première récup, on
            # incrémente la version, on met à jour les champs FRAIS du
            # connecteur en PRESERVANT les enrichissements ex-post :
            #   - url_dce, dce_qualite, url_consultation : résolus par
            #     tendia_dce.py (le connecteur ne les renseigne pas)
            #   - cycle : statut du pipeline commercial (cycle_marche.py)
            #   - jointure_decp : jointure boamp↔decp ajoutée ex-post
            existant = deja_en_base[mid]
            meta_anc = existant.get("meta_recuperation", {})
            version = meta_anc.get("version", 1) + 1
            date_premiere = meta_anc.get("date_premiere_recuperation",
                                          meta_anc.get("date_recuperation",
                                                       horodatage))
            # On part de l'EXISTANT (préserve enrichissements ex-post),
            # puis on overlay les NOUVEAUX champs du connecteur, en
            # évitant d'écraser un champ enrichi par un None venu du
            # connecteur (qui ne le connaît pas).
            m_final = dict(existant)
            for k, v in m.items():
                # Cas spéciaux : champs qu'on ne doit JAMAIS écraser via
                # une récup connecteur, même avec une valeur non-None.
                if k in ("cycle", "url_dce", "dce_qualite",
                         "url_consultation", "jointure_decp"):
                    # Si le connecteur a une vraie valeur (rare), on log
                    # mais on respecte l'existant enrichi qui prime.
                    continue
                # Cas général : on garde l'existant si le connecteur
                # renvoie None (= pas d'info), sinon on overlay.
                if v is not None or k not in m_final:
                    m_final[k] = v
            m_final["meta_recuperation"] = {
                "date_premiere_recuperation": date_premiere,
                "date_derniere_recuperation": horodatage,
                "version": version,
                "source_connecteur": m["source"],
            }
            stats["nb_mis_a_jour"] += 1
        else:
            m_final = dict(m)
            m_final["meta_recuperation"] = {
                "date_premiere_recuperation": horodatage,
                "date_derniere_recuperation": horodatage,
                "version": 1,
                "source_connecteur": m["source"],
            }
            stats["nb_nouveaux"] += 1

        if not dry_run:
            stockage.ecrire(COLLECTION, mid, m_final)

    if verbose:
        print()
        print("=" * 78)
        print(f"  BILAN")
        print("=" * 78)
        print(f"  Total récupéré       : {stats['nb_recuperes']}")
        print(f"  Nouveaux             : {stats['nb_nouveaux']}")
        print(f"  Mis à jour           : {stats['nb_mis_a_jour']}")
        print(f"  Par source :")
        for src, n in stats["par_source"].items():
            duree = stats["duree_par_source_s"].get(src, 0)
            print(f"    {src:<10} : {n:>4} marchés ({duree:.1f}s)")
        print(f"  Par catégorie métier :")
        for cat, n in stats["par_categorie"].most_common():
            print(f"    {cat:<12} : {n}")
        if not dry_run:
            total_base = len(stockage.charger(COLLECTION))
            print(f"  Total en base après run : {total_base}")
        else:
            print(f"  (dry-run, aucune écriture)")

    # --- Hook jointure BOAMP↔DECP (B6) ---
    # Met à jour data/jointure.json avec les marchés ayant une reference_ft.
    # Idempotent : ne dégrade rien si relancé.
    if not dry_run:
        try:
            import jointure
            marches_actuels = stockage.charger(COLLECTION)
            stats_join = jointure.synchroniser_tous_boamp(marches_actuels,
                                                            verbose=False)
            if verbose:
                print(f"  Jointure : {stats_join['avec_ref']} marchés indexés "
                      f"par reference_ft ({stats_join['sans_ref']} sans ref)")
        except Exception as e:
            if verbose:
                print(f"  ⚠ Hook jointure ignoré : {e}")

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def purger_source(source: str, dry_run: bool = False, verbose: bool = True) -> dict:
    """Supprime de la base tous les marchés d'une source donnée.

    Utile après désactivation d'un connecteur pour faire le ménage.
    """
    deja_en_base = stockage.charger(COLLECTION)
    a_supprimer = {mid: m for mid, m in deja_en_base.items()
                    if m.get("source") == source}
    if verbose:
        print()
        print("=" * 78)
        print(f"  TENDIA — Purge des marchés source = '{source}'")
        print("=" * 78)
        print(f"  Trouvés : {len(a_supprimer)} marchés à supprimer.")
        for mid, m in list(a_supprimer.items())[:10]:
            print(f"    [{mid}] {(m.get('titre') or '')[:70]}...")
        if len(a_supprimer) > 10:
            print(f"    ... et {len(a_supprimer) - 10} autres")
    if dry_run:
        if verbose:
            print(f"  Mode dry-run : rien supprimé.")
        return {"trouves": len(a_supprimer), "supprimes": 0}
    if not a_supprimer:
        return {"trouves": 0, "supprimes": 0}
    nouveaux = {mid: m for mid, m in deja_en_base.items() if mid not in a_supprimer}
    stockage.sauver(COLLECTION, nouveaux)
    if verbose:
        print(f"  ✅ {len(a_supprimer)} marchés supprimés. Reste : {len(nouveaux)}.")
    return {"trouves": len(a_supprimer), "supprimes": len(a_supprimer)}


def main():
    parser = argparse.ArgumentParser(
        description="Récupération des marchés publics pour Tendia."
    )
    parser.add_argument("--mois", type=int, default=6,
                        help="Profondeur de récupération en mois (défaut 6).")
    parser.add_argument("--source", action="append", default=None,
                        choices=connecteurs.sources_disponibles(),
                        help=f"Limite à une ou plusieurs sources "
                             f"(parmi {connecteurs.sources_disponibles()}). "
                             f"Par défaut : {connecteurs.sources_par_defaut()}.")
    parser.add_argument("--large", action="store_true",
                        help="Ingestion large (Sprint 3) : capte TOUS les "
                             "marchés publics sans filtre par acheteur. Le "
                             "filtrage par preset se fait à l'analyse. "
                             "Sans cette option, mode legacy : filtre par "
                             "France Travail/Pôle Emploi.")
    parser.add_argument("--limite", type=int, default=None,
                        help="Plafond par source (debug).")
    parser.add_argument("--dry-run", action="store_true",
                        help="N'écrit rien en base.")
    parser.add_argument("--purge-source", default=None,
                        choices=connecteurs.sources_disponibles(),
                        help="Mode purge : supprime tous les marchés "
                             "de cette source de la base, puis quitte.")
    args = parser.parse_args()

    # Mode purge : action one-shot, on ne récupère pas
    if args.purge_source:
        purger_source(source=args.purge_source, dry_run=args.dry_run, verbose=True)
        return

    # Résolution des sources : --source > défaut
    if args.source:
        sources_choisies = args.source
    else:
        sources_choisies = connecteurs.sources_par_defaut()

    recuperer_tout(
        fenetre_mois=args.mois,
        sources=sources_choisies,
        limite_par_source=args.limite,
        mode_large=args.large,
        dry_run=args.dry_run,
        verbose=True,
    )


if __name__ == "__main__":
    main()
