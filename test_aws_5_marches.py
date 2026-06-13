"""
test_aws_5_marches.py
---------------------
Teste le workflow AWS-Achat sur 5 marchés différents pour évaluer
le taux de succès et identifier si l'erreur 12164096 est spécifique
ou globale.

Coût : ~0.005€ (5 captchas).

Lance : python test_aws_5_marches.py
"""
import io
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import stockage
import aws_downloader as A


def main():
    marches = stockage.charger("marches")
    cibles_all = [(mid, m) for mid, m in marches.items()
                   if "marches-publics.info" in (m.get("url_dce") or "")
                   and m.get("dce_contenu") == "auth_requise"]

    # 5 marchés variés
    cibles = cibles_all[:5]
    print(f"=== TEST 5 MARCHES AWS-Achat ===")
    print(f"Cibles : {len(cibles)} sur {len(cibles_all)} marchés AWS dispos")
    print()

    resultats = []
    for i, (mid, marche) in enumerate(cibles, 1):
        print(f"\n{'='*60}")
        print(f"[{i}/5] {mid}")
        print(f"   Titre : {(marche.get('titre') or '')[:80]}")
        print(f"   Acheteur : {(marche.get('acheteur_nom') or '')[:60]}")
        print(f"   URL : {marche.get('url_dce')[:120]}")
        print(f"{'='*60}")
        try:
            res = A.telecharger_dce_pour_marche(marche, "data/dce", verbose=True)
        except Exception as e:
            res = {"ok": False, "erreur": f"{type(e).__name__}: {e}",
                   "etape_erreur": "exception"}

        resultats.append((mid, res))
        if i < 5:
            print(f"\n   Pause 5 sec entre marchés...")
            time.sleep(5)

    # Bilan
    print("\n")
    print("=" * 60)
    print("BILAN")
    print("=" * 60)
    for mid, res in resultats:
        statut = "✅ OK" if res.get("ok") else f"❌ {res.get('etape_erreur','?')}"
        erreur = res.get("erreur", "")[:80] if res.get("erreur") else ""
        nb_fichiers = res.get("fichiers_telecharges", 0)
        print(f"  {mid} : {statut} {erreur}")
        if res.get("ok"):
            print(f"           {nb_fichiers} fichier(s), "
                  f"{res.get('taille_octets_total', 0):,} octets")


if __name__ == "__main__":
    main()
