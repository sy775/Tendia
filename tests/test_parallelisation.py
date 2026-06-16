"""
tests/test_parallelisation.py — Lancement : python tests/test_parallelisation.py

Couvre le BudgetTracker thread-safe (réservation atomique) et le pattern producteur/
consommateur (workers parallèles, écriture mono-thread) du runner v2.
"""
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from reextraire_briefs_v2 import BudgetTracker

ok = ko = 0


def check(nom, cond):
    global ok, ko
    if cond:
        ok += 1; print(f"  ✓ {nom}")
    else:
        ko += 1; print(f"  ✗ ÉCHEC {nom}")


print("BudgetTracker — réservation atomique sous contention")
t = BudgetTracker(50.0)
resultats = []
barriere = threading.Barrier(10)


def _tente():
    barriere.wait()  # maximise la contention
    resultats.append(t.try_reserve(10.0))


with ThreadPoolExecutor(max_workers=10) as ex:
    for _ in range(10):
        ex.submit(_tente)
check("exactement 5 réservations réussies (budget 50 / 10€)", sum(resultats) == 5)
check("consommé = 50 €", abs(t.consomme_eur - 50.0) < 1e-9)
check("nb réservations = 5", t.nb == 5)
check("plus aucune réservation possible", t.try_reserve(0.01) is False)

print("BudgetTracker — ajustement coût réel")
t2 = BudgetTracker(100.0)
t2.try_reserve(0.40)
t2.ajuster_cout_reel(0.40, 0.15)  # coût réel < estimé
check("ajustement à la baisse", abs(t2.consomme_eur - 0.15) < 1e-9)
t2.try_reserve(0.40)
t2.ajuster_cout_reel(0.40, 0.60)  # coût réel > estimé
check("ajustement à la hausse", abs(t2.consomme_eur - (0.15 + 0.60)) < 1e-9)

print("Producteur/consommateur — workers produisent, 1 thread écrit")
# Simulation : 8 workers produisent 50 résultats, un seul thread (le principal) les
# écrit séquentiellement → aucun perdu, aucune écriture concurrente.
ecrits = []
ecriture_lock_calls = {"concurrent": 0}
_w = threading.Lock()


def _ecrire_seq(item):
    # détecte toute écriture concurrente (ne devrait jamais arriver : mono-thread)
    if not _w.acquire(blocking=False):
        ecriture_lock_calls["concurrent"] += 1
        _w.acquire()
    try:
        ecrits.append(item)
    finally:
        _w.release()


with ThreadPoolExecutor(max_workers=8) as ex:
    futs = [ex.submit(lambda i=i: i * i) for i in range(50)]
    from concurrent.futures import as_completed
    for fut in as_completed(futs):
        _ecrire_seq(fut.result())   # consommation mono-thread
check("50 résultats écrits", len(ecrits) == 50)
check("aucune écriture concurrente", ecriture_lock_calls["concurrent"] == 0)
check("tous les carrés présents", sorted(ecrits) == sorted(i * i for i in range(50)))

print(f"\n=== {ok} OK / {ko} KO ===")
sys.exit(1 if ko else 0)
