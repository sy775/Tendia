"""
voir_raisons_echec.py
---------------------
Affiche la distribution complète des raisons d'échec en base, pour calibrer
les exclusions du script de relance.
"""

import io
import sys
from collections import Counter

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import stockage

marches = stockage.charger("marches")

# Tous les statuts
statuts = Counter()
for m in marches.values():
    statuts[m.get("dce_telechargement_statut") or "(jamais_tente)"] += 1

print("=== Statuts de téléchargement DCE (toute la base) ===")
for s, n in statuts.most_common():
    print(f"  {n:4d}  {s}")

# Détail des echec
print()
print("=== Détail des raisons pour statut=echec ===")
raisons = Counter()
raisons_avec_url = Counter()
raisons_sans_url = Counter()
for m in marches.values():
    if m.get("dce_telechargement_statut") != "echec":
        continue
    raison_courte = (m.get("dce_telechargement_raison") or "")[:80]
    raisons[raison_courte] += 1
    if m.get("url_dce"):
        raisons_avec_url[raison_courte] += 1
    else:
        raisons_sans_url[raison_courte] += 1

print()
print("  Avec url_dce présente :")
for r, n in raisons_avec_url.most_common(15):
    print(f"    {n:4d}  {r}")

print()
print("  Sans url_dce :")
for r, n in raisons_sans_url.most_common(15):
    print(f"    {n:4d}  {r}")
