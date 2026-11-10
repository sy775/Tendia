# -*- coding: utf-8 -*-
"""
PROTOTYPE (test feature) — Grille de notation actionnable.

But : pour chaque sous-critère TECHNIQUE du barème, croiser le barème avec le
CCTP/RC pour produire une grille d'ACTIONS pondérées :
  - chaque action a un `type` : "livrable" (preuve/élément exigé à matérialiser)
    ou "levier" (argument différenciant qui fait gagner des points vs concurrence) ;
  - chaque action a un `poids_pct` ESTIMÉ = sa part DANS la note de ce sous-critère
    (la somme des poids d'un sous-critère = 100) ;
  - chaque action cite une `source` (article CCTP/RC) ou "estimé".

Isolé du prompt principal : ne change PAS PROMPT_V2_SHA, ne perturbe pas le batch.
Patche le brief du marché ciblé (avec backup .bak_avant_grille).

Usage :  python test_grille_notation.py BOAMP-26-56409
"""
import json
import os
import re
import sys
import unicodedata

import pdf_extract
import tendia_extraire
import stockage
from llm_extract import MODELE, _check_anthropic
from anthropic import Anthropic

SYSTEME = (
    "Tu es un expert des marchés publics français, spécialiste de la stratégie de "
    "réponse. Tu transformes un barème de notation en grille d'actions concrètes et "
    "priorisées pour le mémoire technique. Tu réponds UNIQUEMENT en JSON valide."
)

GABARIT = """Voici le barème technique d'un marché public et le texte du DCE (RC + CCTP).

## BARÈME TECHNIQUE (sous-critères et leurs pondérations)
{bareme}

## TEXTE DU DCE
{dce}

## TA MISSION
Produis une GRILLE D'ACTIONS pour chaque **CRITÈRE FEUILLE** du barème — c'est-à-dire
le niveau le plus FIN qui est noté (marqué « ← CRITÈRE FEUILLE » ci-dessus). Si un
critère a des sous-critères, descends jusqu'aux sous-critères : NE produis PAS d'actions
au niveau du parent (sinon on double avec ses enfants). Si un critère n'a pas de
sous-critère, c'est lui la feuille.
Pour CHAQUE critère feuille, croise sa définition avec les exigences du CCTP/RC et
produis 2 à 5 actions concrètes que le candidat doit mener dans son mémoire pour scorer
haut sur ce critère feuille.

Chaque action :
- `action` : formulation concrète et actionnable (un verbe + le livrable/argument).
- `type` : "livrable" si c'est un élément/preuve EXIGÉ par le DCE à matérialiser
  (sans lui, on perd des points) ; "levier" si c'est un argument DIFFÉRENCIANT qui
  fait gagner des points face à la concurrence (au-delà du minimum exigé).
- `poids_pct` : ENTIER. Part ESTIMÉE de cette action dans la note du sous-critère.
  La somme des `poids_pct` des actions d'un même sous-critère = EXACTEMENT 100.
- `source` : référence précise (ex "CCTP §3.2", "RC art 5") si l'attendu est explicite
  dans le DCE ; sinon "estimé" (pondération déduite, pas écrite noir sur blanc).

Règles :
- Le `poids_pct` est une ESTIMATION (le DCE chiffre rarement l'intérieur d'un critère) :
  fonde-le sur l'importance relative des attendus dans le CCTP, pas au hasard.
- N'invente pas d'exigence absente du DCE. Si un sous-critère est très générique,
  produis moins d'actions mais justes.
- Pass de cohérence finale : pour chaque sous-critère, vérifie Σ poids_pct = 100.

## FORMAT DE SORTIE (JSON strict, rien d'autre)
{{
  "grille": [
    {{
      "critere_libelle": "<libellé EXACT du sous-critère, recopié>",
      "ponderation_pct": <pondération du sous-critère reprise du barème>,
      "actions": [
        {{"action": "...", "type": "livrable", "poids_pct": 40, "source": "CCTP §..."}},
        {{"action": "...", "type": "levier",   "poids_pct": 60, "source": "estimé"}}
      ]
    }}
  ]
}}
"""


def _texte_dce(mid: str) -> str:
    dossier = os.path.join("data", "dce", mid)
    tendia_extraire._dezipper_dossier(dossier, verbose=False)
    pdfs = pdf_extract.extraire_dossier(dossier, verbose=False)
    if not pdfs:
        raise SystemExit(f"Aucun PDF exploitable pour {mid}")
    # Même filtre non-DCE que la pipeline
    valides = {}
    for nom, p in pdfs.items():
        non_dce, _ = tendia_extraire._est_pdf_non_dce(nom, p.get("taille_chars", 0))
        if not non_dce:
            valides[nom] = p
    return tendia_extraire._combiner_textes(valides or pdfs)


def _bareme_compact(brief: dict) -> str:
    bar = brief.get("bareme_notation") or {}
    sous = bar.get("sous_criteres_techniques") or []
    lignes = [f"Valeur technique {bar.get('valeur_technique_pct')}% / "
              f"Prix {bar.get('valeur_prix_pct')}%", ""]

    def _walk(noeuds, prof):
        for sc in noeuds:
            if not isinstance(sc, dict):
                continue
            enfants = [c for c in (sc.get("sous_criteres") or []) if isinstance(c, dict)]
            marque = "" if enfants else "   ← CRITÈRE FEUILLE (génère la grille ICI)"
            ind = "  " * prof
            lignes.append(f"{ind}- {sc.get('libelle')} — {sc.get('ponderation_pct')}%{marque}")
            for el in (sc.get("elements_attendus") or [])[:8]:
                lignes.append(f"{ind}    · attendu : {el}")
            if enfants:
                _walk(enfants, prof + 1)

    _walk(sous, 0)
    return "\n".join(lignes)


def _domaines_des_lots(brief):
    """Domaines distincts présents dans les lots (ordre d'apparition)."""
    domaines = []
    for l in (brief.get("lots") or []):
        d = l.get("domaine") if isinstance(l, dict) else None
        if d and d not in domaines:
            domaines.append(d)
    return domaines


def _scope_domaine(dom, lots_d):
    """Texte de cadrage : restreint la grille aux lots d'un domaine donné."""
    lignes = [f"Cette grille concerne UNIQUEMENT le domaine métier « {dom} » du marché, "
              f"c'est-à-dire les lots suivants :"]
    for l in lots_d:
        suff = f" — {l.get('particularites')}" if l.get("particularites") else ""
        lignes.append(f"  - Lot {l.get('numero')} : {l.get('intitule', '')}{suff}")
    lignes.append("Le barème (critères + pondérations) est COMMUN à tous les lots, mais tu "
                  "produis ici les actions SPÉCIFIQUES à CE métier (concrètes, pas génériques). "
                  "Ignore totalement les lots des autres domaines.")
    return "\n".join(lignes)


def _appeler_llm(client, bareme_txt, dce, scope):
    prompt = GABARIT.format(bareme=bareme_txt, dce=dce)
    if scope:
        prompt = "## PÉRIMÈTRE — LIRE EN PREMIER\n" + scope + "\n\n" + prompt
    with client.messages.stream(model=MODELE, max_tokens=8000, system=SYSTEME,
                                messages=[{"role": "user", "content": prompt}]) as stream:
        msg = stream.get_final_message()
    txt = (msg.content[0].text if msg.content else "").strip()
    cout = (msg.usage.input_tokens * 3 + msg.usage.output_tokens * 15) / 1_000_000
    print(f"    ✓ réponse (~{cout*0.92:.3f} €)")
    if txt.startswith("```"):
        txt = txt.split("```", 2)[1].lstrip("json").strip().rstrip("`").strip()
    return json.loads(txt)


def generer_grille(mid: str) -> dict:
    _check_anthropic()
    import fiche_marche
    brief = stockage.lire("briefs_extraits", mid)
    if not brief:
        raise SystemExit(f"Pas de brief pour {mid}")
    sous = (brief.get("bareme_notation") or {}).get("sous_criteres_techniques") or []
    if not sous:
        raise SystemExit(f"{mid} n'a pas de sous-critères techniques — rien à croiser.")

    stockage.ecrire("briefs_extraits", f"{mid}.bak_avant_grille",
                    json.loads(json.dumps(brief, ensure_ascii=False)))

    dce = _texte_dce(mid)[:300_000]
    bareme_txt = _bareme_compact(brief)
    lots = [l for l in (brief.get("lots") or []) if isinstance(l, dict)]
    domaines = _domaines_des_lots(brief)
    client = Anthropic()

    brutes, meta = {}, []
    if len(domaines) <= 1:
        # Mono-domaine (ou pas de lots) : une seule grille (champ historique).
        print(f"  → 1 grille (mono-domaine) — DCE {len(dce)} chars...")
        data = _appeler_llm(client, bareme_txt, dce, scope=None)
        _patcher(brief, sous, data, domaine=None)
        brutes["__mono__"] = data
        dom = domaines[0] if domaines else None
        meta.append({"domaine": dom,
                     "label": fiche_marche._libelle_domaine_court(dom) if dom else "Grille",
                     "lots": [l.get("numero") for l in lots]})
    else:
        print(f"  → {len(domaines)} grilles (multi-domaines : {', '.join(domaines)})")
        for dom in domaines:
            lots_d = [l for l in lots if l.get("domaine") == dom]
            print(f"  → domaine {dom} ({len(lots_d)} lots)...")
            data = _appeler_llm(client, bareme_txt, dce, scope=_scope_domaine(dom, lots_d))
            _patcher(brief, sous, data, domaine=dom)
            brutes[dom] = data
            meta.append({"domaine": dom,
                         "label": fiche_marche._libelle_domaine_court(dom),
                         "lots": [l.get("numero") for l in lots_d]})

    brief["grille_notation"] = {"domaines": meta}
    brief["_grille_notation_test"] = True
    stockage.ecrire("briefs_extraits", f"{mid}.grille_brute", brutes)
    stockage.ecrire("briefs_extraits", mid, brief)
    print(f"  ✓ Grille générée pour {len(meta)} domaine(s).")
    return brutes


def _norm(s):
    s = (s or "").lower()
    s = re.sub(r"sous[-\s]?crit[eè]re\s*\d*\s*[:\-]?", "", s)
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def _strip_grille(noeuds, domaine=None):
    """Retire la grille existante du champ concerné (re-génération propre).
    domaine=None → `grille_actions` ; sinon `grille_actions_par_domaine[domaine]`."""
    for n in noeuds or []:
        if isinstance(n, dict):
            if domaine is None:
                n.pop("grille_actions", None)
                n.pop("grille_actions_somme_poids", None)
            else:
                (n.get("grille_actions_par_domaine") or {}).pop(domaine, None)
            _strip_grille(n.get("sous_criteres"), domaine)


def _patcher(brief, sous, data, domaine=None):
    """Rattache les actions de la grille aux critères du barème (tout niveau), par
    libellé normalisé. domaine=None → champ historique `grille_actions` ; sinon
    `grille_actions_par_domaine[domaine]`."""
    _strip_grille(sous, domaine)
    gl = {_norm(g.get("critere_libelle")): g for g in data.get("grille", [])}

    def best(libn):
        if libn in gl:
            return gl[libn]
        for k, g in gl.items():
            if libn and (libn in k or k in libn):
                return g
        lt = set(libn.split())
        bg, bs = None, 0.0
        for k, g in gl.items():
            kt = set(k.split())
            ov = len(lt & kt) / max(1, len(lt | kt))
            if ov > bs:
                bs, bg = ov, g
        return bg if bs >= 0.5 else None

    def walk(noeud):
        n = 0
        if isinstance(noeud, dict):
            g = best(_norm(noeud.get("libelle")))
            if g and g.get("actions"):
                if domaine is None:
                    noeud["grille_actions"] = g["actions"]
                    noeud["grille_actions_somme_poids"] = sum(
                        int(a.get("poids_pct") or 0) for a in g["actions"])
                else:
                    noeud.setdefault("grille_actions_par_domaine", {})[domaine] = g["actions"]
                n += 1
            for child in (noeud.get("sous_criteres") or []):
                n += walk(child)
        return n

    return sum(walk(sc) for sc in sous if isinstance(sc, dict))


def repatcher(mid: str):
    """Re-rattache depuis la/les grille(s) brute(s) déjà en base (zéro appel LLM).
    Gère le format mono ({'__mono__': data}) et multi-domaine ({dom: data})."""
    brief = stockage.lire("briefs_extraits", mid)
    brutes = stockage.lire("briefs_extraits", f"{mid}.grille_brute")
    if not brutes:
        raise SystemExit(f"Pas de grille brute en base pour {mid} — lance d'abord la génération.")
    sous = (brief.get("bareme_notation") or {}).get("sous_criteres_techniques") or []
    # Rétrocompat : ancien format = un seul objet {'grille': [...]}.
    if "grille" in brutes:
        brutes = {"__mono__": brutes}
    total = 0
    for cle, data in brutes.items():
        dom = None if cle == "__mono__" else cle
        total += _patcher(brief, sous, data, domaine=dom)
    stockage.ecrire("briefs_extraits", mid, brief)
    print(f"  ✓ Re-patché : {total} critères sur {len(brutes)} domaine(s).")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    mid = args[0] if args else "BOAMP-26-56409"
    if "--repatch" in sys.argv:
        print(f"=== Re-patch grille (sans LLM) — {mid} ===")
        repatcher(mid)
    else:
        print(f"=== Grille de notation (prototype) — {mid} ===")
        generer_grille(mid)
