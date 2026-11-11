# -*- coding: utf-8 -*-
"""
tests/test_telecharger_ecriture_unitaire.py
-------------------------------------------
Tests HORS-LIGNE (chantier 2, étape 1) de tendia.dce.telecharger.main :
  - pour chaque marché traité, stockage.ecrire("marches", id, marche) juste après
    le marquage ; stockage.sauver n'est jamais appelé ;
  - telecharger._sauver_marches n'existe plus ;
  - si le traitement du 2e marché lève KeyboardInterrupt, le statut du 1er est
    déjà en base ;
  - avec --dry-run, aucune écriture.
_telecharger_marche et marquer_resultat_telechargement sont remplacés par des faux :
aucun réseau. Base temporaire, REPERTOIRE_DCE temporaire.

Lancement : python tests/test_telecharger_ecriture_unitaire.py
"""
import contextlib
import io
import sys
import time
from datetime import date, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from base_temporaire import isoler_stockage
dossier = isoler_stockage()

from tendia.core import stockage
from tendia.dce import telecharger as T

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
time.sleep = lambda *_a, **_k: None        # pas d'attente entre deux marchés
T.DELAI_ENTRE_REQUETES_SEC = 0
T.REPERTOIRE_DCE = dossier / "dce"
T.REPERTOIRE_DCE.mkdir(parents=True, exist_ok=True)
T.FICHIER_MARCHES = dossier / "marches.json"

ok = ko = 0


def check(nom, cond, detail=""):
    global ok, ko
    if cond:
        ok += 1
        print(f"  ✓ {nom}")
    else:
        ko += 1
        print(f"  ✗ ÉCHEC {nom}  {detail}")


# --- Espions et faux ----------------------------------------------------------
EVENEMENTS = []          # ("telecharger" | "marquer" | "ecrire" | "sauver", id, détail)
INTERROMPRE_AU = None    # n° (1, 2, ...) de l'appel à _telecharger_marche qui lève


def _faux_telecharger_marche(marche, session=None, force=False, dry_run=False,
                             verbose=False, **_kw):
    n = sum(1 for e in EVENEMENTS if e[0] == "telecharger") + 1
    EVENEMENTS.append(("telecharger", marche.get("id"), {"dry_run": dry_run, "force": force}))
    if INTERROMPRE_AU is not None and n == INTERROMPRE_AU:
        raise KeyboardInterrupt()
    return {"statut": "dry_run" if dry_run else "ok", "nb_fichiers": 0 if dry_run else 2}


def _faux_marquer(marche, id_m, result, verbose=False, **_kw):
    EVENEMENTS.append(("marquer", id_m, result.get("statut")))
    marche["telechargement_test"] = result["statut"]


_ecrire_reel = stockage.ecrire
_sauver_reel = stockage.sauver


def _espion_ecrire(collection, id_objet, objet, *a, **k):
    if collection == "marches":
        EVENEMENTS.append(("ecrire", id_objet, dict(objet)))
    return _ecrire_reel(collection, id_objet, objet, *a, **k)


def _espion_sauver(collection, donnees, *a, **k):
    EVENEMENTS.append(("sauver", collection, None))
    return _sauver_reel(collection, donnees, *a, **k)


T._telecharger_marche = _faux_telecharger_marche
T.marquer_resultat_telechargement = _faux_marquer

LIMITE = (date.today() + timedelta(days=30)).isoformat()
_n_fichier = 0


def preparer(ids):
    """Crée les marchés (écriture réelle, non espionnée) et remet les espions à zéro."""
    for mid in ids:
        _ecrire_reel("marches", mid, {
            "id": mid, "titre": f"Travaux {mid}", "objet": f"Travaux {mid}",
            "nature": "APPEL_OFFRE", "type_marche": "TRAVAUX",
            "date_publication": "2026-10-15", "date_limite_depot": LIMITE,
            "acheteur_nom": "Commune de Test",
            "url_dce": f"https://plateforme.exemple.test/dce/{mid}"})
    stockage.invalider_cache()
    EVENEMENTS.clear()


def fichier_ids(ids):
    global _n_fichier
    _n_fichier += 1
    chemin = dossier / f"ids_{_n_fichier}.txt"
    chemin.write_text("\n".join(ids) + "\n", encoding="utf-8")
    return str(chemin)


def lancer(argv):
    """T.main(argv) avec espions actifs ; retourne l'exception éventuelle (hors
    KeyboardInterrupt et SystemExit(0), tolérés)."""
    stockage.ecrire, stockage.sauver = _espion_ecrire, _espion_sauver
    erreur = None
    sortie = io.StringIO()
    try:
        with contextlib.redirect_stdout(sortie), contextlib.redirect_stderr(sortie):
            T.main(argv)
    except KeyboardInterrupt:
        pass
    except SystemExit as e:
        if e.code not in (0, None, 130):
            erreur = e
    except Exception as e:  # noqa: BLE001
        erreur = e
    finally:
        stockage.ecrire, stockage.sauver = _ecrire_reel, _sauver_reel
        stockage.invalider_cache()
    return erreur


def ids_de(type_evt):
    return [e[1] for e in EVENEMENTS if e[0] == type_evt]


def base(mid):
    stockage.invalider_cache()
    return stockage.lire("marches", mid) or {}


print("=== _sauver_marches retiré ===")
check("telecharger._sauver_marches n'existe plus", not hasattr(T, "_sauver_marches"))

print("=== --ids-fichier : une écriture unitaire par marché ===")
preparer(["T-1", "T-2", "T-3"])
erreur = lancer(["--ids-fichier", fichier_ids(["T-1", "T-2"])])
check("main se termine sans exception", erreur is None, repr(erreur))
traites = ids_de("telecharger")
check("les 2 marchés du fichier sont traités, pas le 3e", sorted(traites) == ["T-1", "T-2"],
      str(traites))
check("stockage.ecrire('marches', id, …) une fois par marché traité",
      ids_de("ecrire") == traites, f"écrits {ids_de('ecrire')} / traités {traites}")
check("stockage.sauver jamais appelé", ids_de("sauver") == [], str(ids_de("sauver")))
sequence = [(e[0], e[1]) for e in EVENEMENTS if e[0] in ("telecharger", "marquer", "ecrire")]
attendue = [(t, mid) for mid in traites for t in ("telecharger", "marquer", "ecrire")]
check("ordre : télécharger, marquer, écrire, puis marché suivant", sequence == attendue,
      str(sequence))
ecrits = {e[1]: e[2] for e in EVENEMENTS if e[0] == "ecrire"}
check("l'objet écrit porte le marquage",
      bool(ecrits) and all(o.get("telechargement_test") == "ok" for o in ecrits.values()),
      str({k: v.get("telechargement_test") for k, v in ecrits.items()}))
check("l'objet écrit est le marché complet (champs d'origine conservés)",
      bool(ecrits) and all(o.get("id") == mid and o.get("url_dce") and o.get("titre")
                           for mid, o in ecrits.items()))
check("statut relu en base pour les 2 marchés",
      base("T-1").get("telechargement_test") == "ok"
      and base("T-2").get("telechargement_test") == "ok",
      f"{base('T-1').get('telechargement_test')} / {base('T-2').get('telechargement_test')}")
check("marché hors fichier intact en base", "telechargement_test" not in base("T-3")
      and base("T-3").get("url_dce") == "https://plateforme.exemple.test/dce/T-3")
check("les 3 marchés sont toujours en base",
      set(stockage.lister_ids("marches")) == {"T-1", "T-2", "T-3"},
      str(stockage.lister_ids("marches")))

print("=== --marche ID : un seul marché écrit ===")
preparer(["U-1", "U-2"])
erreur = lancer(["--marche", "U-2"])
check("main se termine sans exception", erreur is None, repr(erreur))
check("seul U-2 est traité", ids_de("telecharger") == ["U-2"], str(ids_de("telecharger")))
check("seul U-2 est écrit, unitairement", ids_de("ecrire") == ["U-2"], str(ids_de("ecrire")))
check("stockage.sauver jamais appelé", ids_de("sauver") == [])
check("U-2 marqué en base, U-1 intact",
      base("U-2").get("telechargement_test") == "ok" and "telechargement_test" not in base("U-1"))

print("=== KeyboardInterrupt au 2e marché : le 1er est déjà en base ===")
preparer(["K-1", "K-2", "K-3"])
INTERROMPRE_AU = 2
erreur = lancer(["--ids-fichier", fichier_ids(["K-1", "K-2", "K-3"])])
INTERROMPRE_AU = None
check("pas d'autre exception que l'interruption", erreur is None, repr(erreur))
traites = ids_de("telecharger")
check("l'interruption a bien eu lieu au 2e marché", len(traites) == 2, str(traites))
premier = traites[0] if traites else None
second = traites[1] if len(traites) > 1 else None
check("statut du 1er marché déjà en base",
      premier is not None and base(premier).get("telechargement_test") == "ok",
      f"{premier} : {base(premier) if premier else None}")
check("le 1er a été écrit avant le début du 2e",
      [(e[0], e[1]) for e in EVENEMENTS if e[0] in ("telecharger", "ecrire")][:3]
      == [("telecharger", premier), ("ecrire", premier), ("telecharger", second)],
      str([(e[0], e[1]) for e in EVENEMENTS]))
check("le marché interrompu n'est pas marqué",
      second is not None and "telechargement_test" not in base(second))
check("stockage.sauver jamais appelé, même à l'interruption", ids_de("sauver") == [],
      str(ids_de("sauver")))
check("aucun marché perdu en base", set(stockage.lister_ids("marches")) >= {"K-1", "K-2", "K-3"})

print("=== --dry-run : aucune écriture ===")
preparer(["D-1", "D-2"])
stockage.invalider_cache()
avant = {k: dict(v) for k, v in stockage.charger("marches").items()}
erreur = lancer(["--ids-fichier", fichier_ids(["D-1", "D-2"]), "--dry-run"])
check("main se termine sans exception", erreur is None, repr(erreur))
appels = [e for e in EVENEMENTS if e[0] == "telecharger"]
check("les marchés sont explorés en dry-run",
      sorted(e[1] for e in appels) == ["D-1", "D-2"] and all(e[2]["dry_run"] for e in appels),
      str(appels))
check("aucun stockage.ecrire sur marches", ids_de("ecrire") == [], str(ids_de("ecrire")))
check("aucun stockage.sauver", ids_de("sauver") == [], str(ids_de("sauver")))
stockage.invalider_cache()
check("base inchangée", stockage.charger("marches") == avant)

print("=== --dry-run --marche : aucune écriture non plus ===")
preparer(["D-3"])
avant = dict(base("D-3"))
erreur = lancer(["--marche", "D-3", "--dry-run"])
check("aucune écriture, base inchangée",
      erreur is None and ids_de("ecrire") == [] and ids_de("sauver") == [] and base("D-3") == avant,
      f"{erreur!r} {ids_de('ecrire')}")

print("=== cas limites ===")
preparer(["V-1"])
erreur = lancer(["--ids-fichier", fichier_ids([])])
check("fichier d'ids vide : aucune écriture, aucun sauver",
      ids_de("ecrire") == [] and ids_de("sauver") == [], f"{erreur!r} {EVENEMENTS}")
preparer(["V-2"])
erreur = lancer(["--marche", "ID-INCONNU"])
check("--marche inconnu : aucune écriture, aucun sauver",
      ids_de("ecrire") == [] and ids_de("sauver") == [], f"{erreur!r} {EVENEMENTS}")
check("--marche inconnu : les marchés existants ne sont pas touchés",
      "telechargement_test" not in base("V-2"))
preparer(["F-1"])
erreur = lancer(["--marche", "F-1", "--force"])
check("--force : écriture unitaire aussi, sans sauver",
      erreur is None and ids_de("ecrire") == ["F-1"] and ids_de("sauver") == [],
      f"{erreur!r} {ids_de('ecrire')}")

print()
print("=" * 60)
print(f"RÉSULTAT : {ok} OK, {ko} ÉCHEC(S)")
sys.exit(1 if ko else 0)
