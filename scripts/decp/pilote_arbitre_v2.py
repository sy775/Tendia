"""
scripts/decp/pilote_arbitre_v2.py — Sprint DECP-R : contrôle automatique du pilote v2.

- Variantes évaluées : Flash-Lite prompt v2 (complet / allégé) × (50 / 100 par appel) ;
  Haiku (pilote 1) et CPV seul pour information.
- Désaccord : les variantes v2, Haiku et le CPV seul (famille large) ne sont pas tous d'accord.
- Arbitre gemini-4-argon, prompt v2 (domaine btp_maintenance_exploitation + règles), appel
  unitaire, à l'aveugle, sans outil, justification en une phrase. Plafond 0,40 €.
  Verdicts du pilote 1 RÉUTILISÉS seulement si les nouvelles règles ne peuvent pas les
  changer (hors CPV 50* / 71314*, verdict hors {btp_second_oeuvre, autre,
  it_maintenance_support, entretien_proprete_locaux, fourniture_materiel}).
  Ordre d'arbitrage : lignes touchant le BTP d'abord, puis cas sensibles, puis le reste.
- Seuils (décision Younes) : famille BTP oui/non justesse ≥ 95 % ET rappel BTP ≥ 95 % ;
  domaine fin au sein de la famille BTP ≥ 90 % ; autres secteurs : informatif.
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import budget
import llm_router
from decp import classif_ia as C
from pilote_arbitre import ARBITRE, SENSIBLES, appel_arbitre, large

DOSSIER = "data/decp_reprise/pilote"
PLAFOND = 0.40
V2 = ["flash_v2_50", "flash_v2_100", "flash_v2a_50", "flash_v2a_100"]
INFO = ["haiku_50"]
VERDICTS_FRAGILES = {"btp_second_oeuvre", "autre", "it_maintenance_support",
                     "entretien_proprete_locaux", "fourniture_materiel"}


def systeme_arbitre_v2():
    s = C.prompt_systeme("v2")
    s = s[:s.find("## FORMAT DE SORTIE")]
    return s + ("## FORMAT DE SORTIE (STRICT)\nTu reçois UN contrat. Réponds par un objet JSON "
                'unique : {"d": <numéro du domaine>, "j": "<justification en une phrase>"}')


def est_btp(code):
    return C.famille_de(code or "") == "btp"


def main():
    ech = json.load(open(f"{DOSSIER}/echantillon.json", encoding="utf-8"))
    res = json.load(open(f"{DOSSIER}/resultats.json", encoding="utf-8"))
    P = {k: res[k]["predictions"] for k in V2 + INFO}
    codes = {num: code for num, code, _, _ in C.taxonomie()}
    arb1 = json.load(open(f"{DOSSIER}/arbitre.json", encoding="utf-8"))
    chemin = f"{DOSSIER}/arbitre_v2.json"
    arb2 = json.load(open(chemin, encoding="utf-8")) if os.path.exists(chemin) else {}
    systeme = systeme_arbitre_v2()

    desacc = []
    for c in ech:
        u = c["uid"]
        doms = {P[k].get(u) for k in V2 + INFO}
        fams = {large(C.famille_de(d)) if d else None for d in doms}
        if len(doms) > 1 or None in doms or (c["cpv_seul"] != "ambigu_llm" and fams != {c["cpv_seul"]}):
            desacc.append(c)
    def reutilisable(c):
        a = arb1.get(c["uid"]) or {}
        v = a.get("verdict")
        return bool(v) and not (c["cpv"] or "").startswith(("50", "71314")) and v not in VERDICTS_FRAGILES
    def priorite(c):
        u = c["uid"]
        btp = any(est_btp(P[k].get(u)) for k in V2 + INFO) or c["cpv_seul"] == "btp"
        return (0 if btp else 1, 0 if c["strate"] in SENSIBLES else 1)
    a_arbitrer = sorted([c for c in desacc if not reutilisable(c) and c["uid"] not in arb2], key=priorite)
    print(f"désaccords : {len(desacc)} ; verdicts pilote 1 réutilisés : {sum(reutilisable(c) for c in desacc)} ; "
          f"à arbitrer : {len(a_arbitrer)}")
    dep = sum(a["meta"]["cout_eur"] for a in arb2.values())
    for c in a_arbitrer:
        est = llm_router.estimer_cout_eur(ARBITRE, (len(systeme) + len(c["objet"] or "")) // 3, 300) or 0.01
        if dep + est > PLAFOND:
            print(f"⛔ plafond arbitre v2 atteint ({dep:.4f} €)"); break
        d = budget.peut_depenser(C.ENVELOPPE, est, "gemini")
        if not d.autorise:
            print("⛔", d.raison); break
        budget.verifier_kill_switch("decp")
        try:
            texte, tin, tout, tth, duree, refl = appel_arbitre(systeme, c)
            statut, err = "ok", None
        except Exception as e:
            texte, tin, tout, tth, duree, refl, statut, err = "", 0, 0, 0, 0, None, "erreur", str(e)[:300]
        cout = llm_router.estimer_cout_eur(ARBITRE, tin, tout) or 0.0
        dep += cout
        j = llm_router.parser_json(texte) if texte else None
        verdict = just = None
        if isinstance(j, dict) and j.get("d") is not None:
            try:
                verdict = codes.get(int(j["d"]))
            except (TypeError, ValueError):
                pass
            just = j.get("j")
        meta = {"modele": ARBITRE, "tokens_in": tin, "tokens_out": tout, "tokens_reflexion": tth,
                "cout_eur": round(cout, 6), "duree_s": duree, "reflexion": refl, "etiquette": "pilote:arbitre_v2"}
        budget.enregistrer_appel("decp", cout, statut=statut, tokens_input=tin, tokens_output=tout,
                                 duree_ms=int(duree * 1000), modele=ARBITRE, erreur=err,
                                 enveloppe=C.ENVELOPPE, extra={"_meta": meta})
        arb2[c["uid"]] = {"verdict": verdict, "justification": just, "meta": meta, "erreur": err}
        json.dump(arb2, open(chemin, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"  {c['uid'][:38]:<38} → {verdict}  ({cout:.4f} €)", flush=True)
    print(f"dépense arbitre v2 : {dep:.4f} €")

    verite = {}
    for c in ech:
        u = c["uid"]
        if c in desacc:
            v = (arb2.get(u) or {}).get("verdict") or ((arb1.get(u) or {}).get("verdict") if reutilisable(c) else None)
            if v:
                verite[u] = v
        else:
            verite[u] = P["flash_v2_50"][u]

    def stats(cle, lignes):
        pred = (lambda c: c["cpv_seul"] == "btp") if cle == "cpv_seul" else (lambda c: est_btp(P[cle].get(c["uid"])))
        vp = sum(1 for c in lignes if pred(c) and est_btp(verite[c["uid"]]))
        fn = sum(1 for c in lignes if not pred(c) and est_btp(verite[c["uid"]]))
        fp = sum(1 for c in lignes if pred(c) and not est_btp(verite[c["uid"]]))
        ok = sum(1 for c in lignes if pred(c) == est_btp(verite[c["uid"]]))
        out = {"btp_justesse": round(100 * ok / len(lignes), 1),
               "btp_rappel": round(100 * vp / (vp + fn), 1) if vp + fn else None,
               "btp_precision": round(100 * vp / (vp + fp), 1) if vp + fp else None}
        if cle != "cpv_seul":
            bt = [c for c in lignes if est_btp(verite[c["uid"]])]
            out["btp_domaine_fin"] = round(100 * sum(P[cle].get(c["uid"]) == verite[c["uid"]] for c in bt) / len(bt), 1) if bt else None
            out["domaine_total"] = round(100 * sum(P[cle].get(c["uid"]) == verite[c["uid"]] for c in lignes) / len(lignes), 1)
            out["famille_total"] = round(100 * sum(large(C.famille_de(P[cle].get(c["uid"]) or "")) == large(C.famille_de(verite[c["uid"]])) for c in lignes) / len(lignes), 1)
            sens = [c for c in lignes if c["strate"] in SENSIBLES]
            out["domaine_sensibles"] = round(100 * sum(P[cle].get(c["uid"]) == verite[c["uid"]] for c in sens) / len(sens), 1)
            autres = {}
            for c in lignes:
                f = large(C.famille_de(verite[c["uid"]]))
                if f != "btp":
                    autres.setdefault(f, [0, 0])
                    autres[f][1] += 1
                    autres[f][0] += P[cle].get(c["uid"]) == verite[c["uid"]]
            out["autres_familles_domaine"] = {f: f"{round(100 * a / b)} % (n={b})" for f, (a, b) in sorted(autres.items())}
        return out
    lignes = [c for c in ech if c["uid"] in verite]
    n_btp = sum(est_btp(verite[c["uid"]]) for c in lignes)
    tableau = {k: stats(k, lignes) for k in V2 + INFO + ["cpv_seul"]}
    print(f"\nvérité provisoire : {len(lignes)} lignes (dont {n_btp} BTP) ; sans vérité : {len(ech) - len(lignes)}")
    for k, t in tableau.items():
        print(f"  {k:<14} " + "  ".join(f"{m}={v}" for m, v in t.items() if m != "autres_familles_domaine"))
    for k in V2:
        print(f"  {k:<14} autres familles : {tableau[k]['autres_familles_domaine']}")

    def passe(t):
        return t["btp_justesse"] >= 95 and (t["btp_rappel"] or 0) >= 95 and (t["btp_domaine_fin"] or 0) >= 90
    ok = [k for k in V2 if passe(tableau[k])]
    print("\nvariantes qui passent les seuils :", ok)
    choix = None
    if ok:
        # moins chère d'abord si l'écart avec la meilleure est négligeable (≤ 1,5 pt sur chaque seuil)
        cout_rel = {"flash_v2a_100": 1, "flash_v2_100": 2, "flash_v2a_50": 3, "flash_v2_50": 4}
        meilleur = max(ok, key=lambda k: (tableau[k]["btp_rappel"], tableau[k]["btp_domaine_fin"], tableau[k]["btp_justesse"]))
        for k in sorted(ok, key=cout_rel.get):
            if all(tableau[meilleur][m] - tableau[k][m] <= 1.5 for m in ("btp_justesse", "btp_rappel", "btp_domaine_fin")):
                choix = k
                break
    print("CHOIX :", choix)
    div = [{"uid": c["uid"], "strate": c["strate"], "objet": c["objet"], "cpv": c["cpv"],
            "pred": P[choix or "flash_v2_50"].get(c["uid"]), "arbitre": verite[c["uid"]],
            "justification": (arb2.get(c["uid"]) or arb1.get(c["uid"]) or {}).get("justification")}
           for c in lignes if P[choix or "flash_v2_50"].get(c["uid"]) != verite[c["uid"]]]
    json.dump({"tableau": tableau, "choix": choix, "variantes_ok": ok, "lignes_verite": len(lignes),
               "n_btp": n_btp, "depense_arbitre_v2": round(dep, 4), "divergences": div},
              open(f"{DOSSIER}/controle_v2.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("dépense enveloppe :", budget.depense_enveloppe(C.ENVELOPPE))


if __name__ == "__main__":
    main()
