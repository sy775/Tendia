"""
scripts/decp/pilote_arbitre.py — Sprint DECP-R : contrôle automatique du pilote.

1. Désaccords : lignes où Flash-Lite (50 et 100 par appel), Haiku et le CPV seul ne sont
   pas tous d'accord (modèles comparés au niveau domaine ; CPV seul comparé au niveau
   famille large, car il ne donne pas de domaine fin ; CPV « ambigu » = pas d'avis).
2. Arbitre gemini-4-argon : appel UNITAIRE par ligne en désaccord, sans outil (pas de
   recherche Google), réflexion basse, classement À L'AVEUGLE (il ne voit pas les
   propositions), justification en une phrase. Plafond arbitre : 0,50 € (et enveloppe).
3. Vérité terrain provisoire = verdict de l'arbitre (lignes en désaccord) ou consensus.
   Justesse au total et sur les cas sensibles (71314, 79952, CPV ambigus).
4. Décision automatique (Flash-Lite ≥ 95 % total ET ≥ 90 % sensibles).
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import budget
import llm_router
from decp import classif_ia as C

DOSSIER = "data/decp_reprise/pilote"
ARBITRE = "gemini-4-argon"
PLAFOND_ARBITRE_EUR = 0.50
SENSIBLES = {"cpv_71314", "cpv_79952", "cpv_ambigu"}
FAMILLES_LARGES = {"btp", "ingenierie", "it", "conseil", "formation", "energie_renouvelable"}


def large(fam):
    return fam if fam in FAMILLES_LARGES else "hors_perimetre"


def systeme_arbitre():
    s = C.prompt_systeme()
    s = s[:s.find("## FORMAT DE SORTIE")]
    return s + ("## FORMAT DE SORTIE (STRICT)\nTu reçois UN contrat. Réponds par un objet JSON "
                'unique : {"d": <numéro du domaine>, "j": "<justification en une phrase>"}')


def appel_arbitre(systeme, contrat):
    from google.genai import types
    llm_router.charger_env()
    client = llm_router._client_gemini()
    user = (f"Objet : {contrat['objet']}\nCPV : {contrat['cpv']}\nAcheteur : {contrat['acheteur']}")
    for refl in ({"thinking_level": "LOW"}, {"thinking_budget": 1024}, None):
        try:
            cfg = types.GenerateContentConfig(
                system_instruction=systeme, max_output_tokens=4096, temperature=0,
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(**refl) if refl else None)
            t0 = time.time()
            rep = client.models.generate_content(model=ARBITRE, contents=[user], config=cfg)
            u = rep.usage_metadata
            tin = int(getattr(u, "prompt_token_count", 0) or 0)
            tth = int(getattr(u, "thoughts_token_count", 0) or 0)
            tout = int(getattr(u, "candidates_token_count", 0) or 0) + tth
            return rep.text or "", tin, tout, tth, round(time.time() - t0, 2), refl
        except Exception as e:
            if "thinking" in str(e).lower() and refl is not None:
                continue
            raise


def main():
    ech = json.load(open(f"{DOSSIER}/echantillon.json", encoding="utf-8"))
    res = json.load(open(f"{DOSSIER}/resultats.json", encoding="utf-8"))
    P = {k: res[k]["predictions"] for k in ("flash_50", "flash_100", "haiku_50")}
    codes = {num: code for num, code, _, _ in C.taxonomie()}
    chemin_arb = f"{DOSSIER}/arbitre.json"
    arb = json.load(open(chemin_arb, encoding="utf-8")) if os.path.exists(chemin_arb) else {}
    systeme = systeme_arbitre()
    desaccords = []
    for c in ech:
        u = c["uid"]
        doms = {P[k].get(u) for k in P}
        cpv = c["cpv_seul"]
        fams = {large(C.famille_de(d)) if d else None for d in doms}
        if len(doms) > 1 or None in doms or (cpv != "ambigu_llm" and fams != {cpv}):
            desaccords.append(c)
    print(f"désaccords : {len(desaccords)} / {len(ech)}")
    depense_arb = sum(a["meta"]["cout_eur"] for a in arb.values())
    for c in desaccords:
        if c["uid"] in arb:
            continue
        tin_est = (len(systeme) + len(c["objet"] or "")) // 3
        est = llm_router.estimer_cout_eur(ARBITRE, tin_est, 1500) or 0.02
        if depense_arb + est > PLAFOND_ARBITRE_EUR:
            print(f"⛔ plafond arbitre atteint ({depense_arb:.4f} € + {est:.4f} € > {PLAFOND_ARBITRE_EUR} €)")
            break
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
        depense_arb += cout
        verdict, just = None, None
        j = llm_router.parser_json(texte) if texte else None
        if isinstance(j, dict) and j.get("d") is not None:
            try:
                verdict = codes.get(int(j["d"]))
            except (TypeError, ValueError):
                verdict = None
            just = j.get("j")
        meta = {"modele": ARBITRE, "tokens_in": tin, "tokens_out": tout, "tokens_reflexion": tth,
                "cout_eur": round(cout, 6), "duree_s": duree, "reflexion": refl, "etiquette": "pilote:arbitre"}
        budget.enregistrer_appel("decp", cout, statut=statut, tokens_input=tin, tokens_output=tout,
                                 duree_ms=int(duree * 1000), modele=ARBITRE, erreur=err,
                                 enveloppe=C.ENVELOPPE, extra={"_meta": meta})
        arb[c["uid"]] = {"verdict": verdict, "justification": just, "meta": meta, "erreur": err}
        json.dump(arb, open(chemin_arb, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"  {c['uid'][:40]:<40} → {verdict}  ({tin}+{tout} tok, {tth} réfl., {cout:.4f} €)"
              f"{' ⚠ ' + err if err else ''}", flush=True)
    print(f"dépense arbitre : {depense_arb:.4f} €")

    # ---- vérité provisoire et justesse
    verite = {}
    for c in ech:
        u = c["uid"]
        if c in desaccords:
            v = (arb.get(u) or {}).get("verdict")
            if v:
                verite[u] = v
        else:
            verite[u] = P["flash_50"][u]
    def justesse(filtre, cle):
        lignes = [c for c in ech if c["uid"] in verite and filtre(c)]
        if not lignes:
            return None, 0
        if cle == "cpv_seul":
            ok = sum(c["cpv_seul"] == large(C.famille_de(verite[c["uid"]])) for c in lignes)
        elif cle.endswith(":famille"):
            k = cle.split(":")[0]
            ok = sum(large(C.famille_de(P[k].get(c["uid"]) or "")) == large(C.famille_de(verite[c["uid"]]))
                     for c in lignes)
        else:
            ok = sum(P[cle].get(c["uid"]) == verite[c["uid"]] for c in lignes)
        return round(100 * ok / len(lignes), 1), len(lignes)
    tableau = {}
    for nom, f in (("total", lambda c: True), ("sensibles", lambda c: c["strate"] in SENSIBLES),
                   ("71314", lambda c: c["strate"] == "cpv_71314"), ("79952", lambda c: c["strate"] == "cpv_79952"),
                   ("cpv_ambigus", lambda c: c["strate"] == "cpv_ambigu"),
                   ("prefiltre", lambda c: c["strate"].startswith("prefiltre"))):
        tableau[nom] = {k: justesse(f, k) for k in ("flash_50", "flash_100", "haiku_50",
                                                    "flash_50:famille", "flash_100:famille",
                                                    "haiku_50:famille", "cpv_seul")}
    print("\nJustesse (%, n) — domaine fin pour les modèles ; « :famille » et cpv_seul = famille large")
    for nom, t in tableau.items():
        print(f"  {nom:<12} " + "  ".join(f"{k}={v[0]}%" for k, v in t.items()) + f"  (n={t['flash_50'][1]})")
    non_arb = [c["uid"] for c in desaccords if not (arb.get(c["uid"]) or {}).get("verdict")]
    divergences = [{"uid": c["uid"], "strate": c["strate"], "objet": c["objet"], "cpv": c["cpv"],
                    "acheteur": c["acheteur"], "flash_50": P["flash_50"].get(c["uid"]),
                    "flash_100": P["flash_100"].get(c["uid"]), "haiku": P["haiku_50"].get(c["uid"]),
                    "cpv_seul": c["cpv_seul"], "arbitre": verite.get(c["uid"]),
                    "justification": (arb.get(c["uid"]) or {}).get("justification")}
                   for c in ech if c["uid"] in verite and P["flash_50"].get(c["uid"]) != verite[c["uid"]]]
    json.dump({"tableau": tableau, "desaccords": len(desaccords), "non_arbitres": non_arb,
               "depense_arbitre_eur": round(depense_arb, 4), "divergences_flash50_arbitre": divergences},
              open(f"{DOSSIER}/controle.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nnon arbitrés (plafond/erreur) : {len(non_arb)} ; divergences Flash-Lite 50 / arbitre : {len(divergences)}")
    print("dépense enveloppe :", budget.depense_enveloppe(C.ENVELOPPE))


if __name__ == "__main__":
    main()
