"""
scripts/decp/pilote_classif.py — Sprint DECP-R : pilote de classification DECP (200 contrats).

Étapes :
  echantillon : tire 200 contrats stratifiés (années, CPV ambigus, 71314, 79952, pré-filtre)
                → data/decp_reprise/pilote/echantillon.json (aucun appel LLM)
  estimer     : coût estimé de chaque variante (tokens comptés en caractères/3)
  lancer      : exécute les variantes (Gemini Flash-Lite et Haiku, lots de 50 et 100) sous
                l'enveloppe budget decp_reprise ; chaque appel est journalisé (llm_appels)
  csv         : fichier de vérification à la main (CPV seul | Flash-Lite | Haiku | vérité terrain)
  mesurer     : justesse par variante une fois la colonne « verite_terrain » remplie

Gemini : sans outil (pas de grounding), réflexion désactivée. Haiku : SDK anthropic, clé lue
par llm_extract._obtenir_cle_api() (.env).
"""
import argparse
import csv
import json
import os
import random
import sqlite3
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tendia.core import budget
from tendia.core import stockage
from tendia.prix.decp import classif_ia as C
from tendia.prix.decp.mapping_cpv import classer_par_cpv

DOSSIER = "data/decp_reprise/pilote"
ECH = f"{DOSSIER}/echantillon.json"
RES = f"{DOSSIER}/resultats.json"
MODELE_GEMINI = "gemini-3.1-flash-lite"
MODELE_HAIKU = "claude-haiku-4-5"
VARIANTES = [  # (nom, fournisseur, modèle, taille de lot, prompt)
    ("flash_50", "gemini", MODELE_GEMINI, 50, "complet"),
    ("flash_100", "gemini", MODELE_GEMINI, 100, "complet"),
    ("flash_compact_100", "gemini", MODELE_GEMINI, 100, "compact"),
    ("haiku_50", "claude", MODELE_HAIKU, 50, "complet"),
    ("haiku_100", "claude", MODELE_HAIKU, 100, "complet"),
    # Pilote v2 : domaine btp_maintenance_exploitation, règles + exemples, sortie compacte
    ("flash_v2_50", "gemini", MODELE_GEMINI, 50, "v2"),
    ("flash_v2_100", "gemini", MODELE_GEMINI, 100, "v2"),
    ("flash_v2a_50", "gemini", MODELE_GEMINI, 50, "v2_allege"),
    ("flash_v2a_100", "gemini", MODELE_GEMINI, 100, "v2_allege"),
]


def prompt_compact() -> str:
    """Variante coût : codes + libellés seulement (sans descriptions ni frontières)."""
    lignes = ["Tu classes des contrats de marchés publics français attribués (DECP) dans une "
              "taxonomie de domaines métier. L'OBJET prime sur le CPV (indicatif). Un seul "
              "domaine par contrat (le dominant) ; sinon `autre`. Travaux (pose, réalisation) = "
              "BTP ; études/conception/maîtrise d'œuvre = ingénierie/MOE.", "", "## DOMAINES"]
    lignes += [f"{n} {code} — {lib}" for n, code, lib, _ in C.taxonomie()]
    lignes += ["", "## SORTIE : une ligne JSON compacte par contrat, dans l'ordre : "
               '{"i":<numéro du contrat>,"d":<numéro du domaine>} — rien d\'autre.']
    return "\n".join(lignes)


def _cpv_seul(cpv):
    p, _ = classer_par_cpv(cpv)
    return C.CORRESPONDANCE_V1.get(p, p) if p else "ambigu_llm"


# ---------------------------------------------------------------- échantillon
def cmd_echantillon(args):
    random.seed(args.seed)
    con = sqlite3.connect(f"file:{stockage.chemin_db()}?mode=ro", uri=True)
    rows = con.execute("""SELECT uid, objet, cpv_principal, acheteur_nom, date_notification
                          FROM decp_marches WHERE doublon_de IS NULL AND objet IS NOT NULL""").fetchall()
    def ok(r, f):
        return f(r)
    strates = [
        ("cpv_71314", 30, lambda r: (r[2] or "").startswith("71314")),
        ("cpv_79952", 30, lambda r: (r[2] or "").startswith("79952")),
        ("cpv_ambigu", 40, lambda r: (r[2] or "") in ("45000000", "71000000", "50000000", "44000000",
                                                     "45200000", "45400000", "71300000", "50700000",
                                                     "79000000", "98000000", "00000000")
                                     or (r[2] or "")[:2] in ("09", "50", "79")),
    ]
    choisis, vus = [], set()
    for nom, n, f in strates:
        cand = [r for r in rows if f(r) and r[0] not in vus]
        for r in random.sample(cand, min(n, len(cand))):
            choisis.append((nom, r)); vus.add(r[0])
    # 100 contrats du pré-filtre, 20 par année 2022-2026
    for an in ("2022", "2023", "2024", "2025", "2026"):
        cand = [r for r in rows if (r[4] or "")[:4] == an and r[0] not in vus and C.dans_prefiltre(r[2], r[1])]
        for r in random.sample(cand, min(20, len(cand))):
            choisis.append((f"prefiltre_{an}", r)); vus.add(r[0])
    random.shuffle(choisis)
    out = [{"uid": r[0], "objet": r[1], "cpv": r[2], "acheteur": r[3], "date": r[4], "strate": s,
            "cpv_seul": _cpv_seul(r[2])} for s, r in choisis]
    os.makedirs(DOSSIER, exist_ok=True)
    json.dump(out, open(ECH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    import collections
    print(len(out), "contrats →", ECH, dict(collections.Counter(o["strate"] for o in out)))


# ---------------------------------------------------------------- appels
def _systeme(variante):
    """complet = prompt v1 (pilote 1) ; v2 / v2_allege = prompt v2 complet / allégé."""
    if variante == "compact":
        return prompt_compact()
    if variante == "v2":
        return C.prompt_systeme("v2")
    if variante == "v2_allege":
        return C.prompt_systeme("v2", allege=True)
    return C.prompt_systeme("v1")


def _estimer(sys_prompt, lot, fournisseur, modele):
    from tendia.analyse import llm_router
    tin = (len(sys_prompt) + len(C.prompt_utilisateur(lot))) // 3
    tout = 14 * len(lot) + 20
    return llm_router.estimer_cout_eur(modele, tin, tout) or 0.0, tin, tout


def _appel_gemini(modele, systeme, user, max_out):
    from tendia.analyse import llm_router
    from google.genai import types
    llm_router.charger_env()
    client = llm_router._client_gemini()
    for reflexion in ({"thinking_budget": 0}, {"thinking_level": "MINIMAL"}, {"thinking_level": "LOW"}, None):
        try:
            cfg = types.GenerateContentConfig(
                system_instruction=systeme, max_output_tokens=max_out, temperature=0,
                thinking_config=types.ThinkingConfig(**reflexion) if reflexion else None)
            t0 = time.time()
            rep = client.models.generate_content(model=modele, contents=[user], config=cfg)
            u = rep.usage_metadata
            tin = int(getattr(u, "prompt_token_count", 0) or 0)
            tth = int(getattr(u, "thoughts_token_count", 0) or 0)
            tout = int(getattr(u, "candidates_token_count", 0) or 0) + tth
            return rep.text or "", tin, tout, tth, round(time.time() - t0, 2), reflexion
        except Exception as e:
            if "thinking" in str(e).lower() and reflexion is not None:
                continue
            raise


def _appel_claude(modele, systeme, user, max_out, extra_journal=None):
    """Appel Claude par le client unique : le routeur journalise l'appel dans llm_appels
    (type decp, enveloppe du pilote) ; classer_lot ne le journalise donc pas une 2e fois."""
    from tendia.analyse import llm_router
    rep = llm_router.appeler_modele("classif", user, model=modele, type_appel="decp",
                                    system=systeme, max_tokens=max_out,
                                    enveloppe=C.ENVELOPPE, extra_journal=extra_journal)
    return rep.texte, rep.tokens_in, rep.tokens_out, 0, rep.duree_s, None


def classer_lot(lot, fournisseur, modele, systeme, etiquette):
    """Un appel ; journalisé dans llm_appels (type decp, enveloppe decp_reprise)."""
    from tendia.analyse import llm_router
    est, _, _ = _estimer(systeme, lot, fournisseur, modele)
    d = budget.peut_depenser(C.ENVELOPPE, est, fournisseur)
    if not d.autorise:
        raise budget.BudgetDepasseError(d.raison)
    budget.verifier_kill_switch("decp")
    max_out = 20 * len(lot) + 200
    version = __import__("hashlib").sha256(systeme.encode("utf-8")).hexdigest()[:12]
    try:
        if fournisseur == "gemini":
            texte, tin, tout, tth, duree, refl = _appel_gemini(
                modele, systeme, C.prompt_utilisateur(lot), max_out)
        else:
            texte, tin, tout, tth, duree, refl = _appel_claude(
                modele, systeme, C.prompt_utilisateur(lot), max_out,
                extra_journal={"etiquette": etiquette, "prompt_version": version,
                               "n_contrats": len(lot)})
        statut, err = "ok", None
    except budget.BudgetDepasseError:
        raise
    except Exception as e:
        texte, tin, tout, tth, duree, refl, statut, err = "", 0, 0, 0, 0, None, "erreur", str(e)[:300]
    cout = llm_router.estimer_cout_eur(modele, tin, tout) or 0.0
    meta = {"modele": modele, "tokens_in": tin, "tokens_out": tout, "tokens_reflexion": tth,
            "cout_eur": round(cout, 6), "duree_s": duree, "reflexion": refl, "etiquette": etiquette,
            "prompt_version": version, "n_contrats": len(lot)}
    # Claude : déjà journalisé par llm_router (succès comme erreur), pas de double comptage.
    if fournisseur == "gemini":
        budget.enregistrer_appel("decp", cout, statut=statut, tokens_input=tin, tokens_output=tout,
                                 duree_ms=int(duree * 1000), modele=modele, erreur=err,
                                 enveloppe=C.ENVELOPPE, extra={"_meta": meta})
    return C.parser_sortie(texte, len(lot)), meta, err


def cmd_estimer(args):
    ech = json.load(open(ECH, encoding="utf-8"))
    tot = 0
    for nom, fourn, modele, taille, var in VARIANTES:
        s = _systeme(var)
        c = sum(_estimer(s, ech[i:i + taille], fourn, modele)[0] for i in range(0, len(ech), taille))
        tot += c
        print(f"  {nom:<18} {len(range(0, len(ech), taille))} appels  ≈ {c:.4f} €")
    print(f"  TOTAL pilote ≈ {tot:.4f} € ; dépense actuelle enveloppe : {budget.depense_enveloppe(C.ENVELOPPE)}")


def cmd_lancer(args):
    ech = json.load(open(ECH, encoding="utf-8"))
    res = json.load(open(RES, encoding="utf-8")) if os.path.exists(RES) else {}
    for nom, fourn, modele, taille, var in VARIANTES:
        if args.variantes and nom not in args.variantes.split(","):
            continue
        if nom in res and not args.force:
            print(f"  {nom} : déjà fait"); continue
        s = _systeme(var)
        preds, metas = {}, []
        for i in range(0, len(ech), taille):
            lot = ech[i:i + taille]
            p, meta, err = classer_lot([{"objet": c["objet"], "cpv": c["cpv"], "acheteur": c["acheteur"]}
                                        for c in lot], fourn, modele, s, f"pilote:{nom}")
            for k, code in p.items():
                preds[lot[k - 1]["uid"]] = code
            metas.append(meta)
            print(f"  {nom} lot {i // taille + 1} : {len(p)}/{len(lot)} lus, {meta['tokens_in']}+"
                  f"{meta['tokens_out']} tok ({meta['tokens_reflexion']} réflexion), "
                  f"{meta['cout_eur']:.5f} €{' ⚠ ' + err if err else ''}", flush=True)
        res[nom] = {"predictions": preds, "meta": metas}
        json.dump(res, open(RES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("dépense enveloppe :", budget.depense_enveloppe(C.ENVELOPPE))


def cmd_csv(args):
    ech = json.load(open(ECH, encoding="utf-8"))
    res = json.load(open(RES, encoding="utf-8"))
    noms = [v[0] for v in VARIANTES if v[0] in res]
    chemin = f"{DOSSIER}/pilote_a_verifier.csv"
    with open(chemin, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["uid", "strate", "annee", "cpv", "objet", "acheteur",
                    "cpv_seul_famille", "flash_lite_domaine", "haiku_domaine", "verite_terrain_domaine",
                    "flash_lite_famille", "haiku_famille"] + [f"{n}" for n in noms])
        for c in ech:
            fl = res.get("flash_50", {}).get("predictions", {}).get(c["uid"], "")
            hk = res.get("haiku_50", {}).get("predictions", {}).get(c["uid"], "")
            w.writerow([c["uid"], c["strate"], (c["date"] or "")[:4], c["cpv"], c["objet"], c["acheteur"],
                        c["cpv_seul"], fl, hk, "",
                        C.famille_de(fl) if fl else "", C.famille_de(hk) if hk else ""]
                       + [res[n]["predictions"].get(c["uid"], "") for n in noms])
    print("→", chemin)


def cmd_mesurer(args):
    with open(args.csv, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    verites = [r for r in rows if r["verite_terrain_domaine"].strip()]
    print(f"{len(verites)} lignes avec vérité terrain")
    cols = [c for c in rows[0] if c in [v[0] for v in VARIANTES]]
    for col in cols:
        dom = sum(r[col] == r["verite_terrain_domaine"].strip() for r in verites)
        fam = sum(C.famille_de(r[col]) == C.famille_de(r["verite_terrain_domaine"].strip())
                  for r in verites if r[col])
        print(f"  {col:<18} domaine {100 * dom / max(len(verites), 1):5.1f} %   famille {100 * fam / max(len(verites), 1):5.1f} %")
    fam_cpv = sum(r["cpv_seul_famille"] == C.famille_de(r["verite_terrain_domaine"].strip()) for r in verites)
    print(f"  {'cpv_seul':<18} famille {100 * fam_cpv / max(len(verites), 1):5.1f} %")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("echantillon"); e.add_argument("--seed", type=int, default=2026); e.set_defaults(func=cmd_echantillon)
    sub.add_parser("estimer").set_defaults(func=cmd_estimer)
    l = sub.add_parser("lancer"); l.add_argument("--variantes", default=None); l.add_argument("--force", action="store_true"); l.set_defaults(func=cmd_lancer)
    sub.add_parser("csv").set_defaults(func=cmd_csv)
    m = sub.add_parser("mesurer"); m.add_argument("--csv", default=f"{DOSSIER}/pilote_a_verifier.csv"); m.set_defaults(func=cmd_mesurer)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
