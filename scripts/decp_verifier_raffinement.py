"""
scripts/decp_verifier_raffinement.py — Étape 1 du raffinement v2 (vérification bloquante).

Vérifie l'état EN BASE des 5 marchés problématiques repérés dans l'audit manuel
de Younes. But : savoir si le raffinement v1 a bien été appliqué (audit fait AVANT
raffinement → erreurs déjà corrigées) ou s'il reste un bug (audit POST-raffinement).

Usage : python scripts/decp_verifier_raffinement.py
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decp.db import connexion

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", "verification_raffinement_v1.txt")

# IDs problématiques (audit Younes) → (preset attendu post-raffinement, libellé)
IDS_TEST = {
    "2003": ("hors_perimetre", "P1 cérémonie remise de diplômes (CPV 79952)"),
    "2024-UTOPIA08": ("hors_perimetre", "P1 vitrines métiers (CPV 79952)"),
    "2024-UTOPIA13": ("hors_perimetre", "P1 MS 13 SROM (CPV 79952)"),
    "2022FOU03020400": ("hors_perimetre", "P2 fourniture électricité/gaz (CPV 71314100)"),
    "00": ("ingenierie", "P3 MOE logements collectifs (CPV 45211)"),
}


def main():
    con = connexion()
    lignes = []
    conformes = 0
    try:
        for mid, (attendu, libelle) in IDS_TEST.items():
            r = con.execute(
                "SELECT c.preset_principal, c.source, c.confiance, m.cpv_principal, m.objet "
                "FROM decp_classification c JOIN decp_marches m ON m.id = c.decp_id "
                "WHERE c.decp_id = ?", (mid,)).fetchone()
            if r is None:
                statut = "INTROUVABLE"
                lignes.append(f"[{statut}] id={mid} — {libelle} : aucune ligne en base")
                continue
            ok = (r["preset_principal"] == attendu)
            conformes += ok
            statut = "CONFORME" if ok else "NON CONFORME"
            lignes.append(
                f"[{statut}] id={mid} — {libelle}\n"
                f"           attendu={attendu} | obtenu={r['preset_principal']} "
                f"(source={r['source']}, confiance={r['confiance']}) | CPV={r['cpv_principal']}\n"
                f"           objet: {(r['objet'] or '')[:90]}")
    finally:
        con.close()

    n = len(IDS_TEST)
    entete = f"=== Vérification raffinement v1 — {conformes}/{n} conformes ===\n"
    if conformes == n:
        verdict = ("\n=> VERDICT : raffinement v1 APPLIQUÉ. Les 5 erreurs étaient déjà "
                   "corrigées en base ; l'export d'audit reflétait l'état PRÉ-raffinement.\n"
                   "   Précision réelle ~92 % (44-45/50). Poursuite Étape 2 (durcissement regex).")
    elif conformes == 0:
        verdict = ("\n=> VERDICT : raffinement v1 NON appliqué / bug structurel. STOP — "
                   "prévenir Younes avant tout fix.")
    else:
        verdict = (f"\n=> VERDICT : PARTIEL ({conformes}/{n}). Bug ciblé sur les non-conformes. "
                   "STOP si plusieurs non-conformes — prévenir Younes.")

    rapport = entete + "\n" + "\n".join(lignes) + "\n" + verdict + "\n"
    print(rapport)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(rapport)
    print(f"(Traçabilité écrite : {OUT})")


if __name__ == "__main__":
    main()
