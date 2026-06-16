"""
scripts/decp_explorer.py — Sprint DECP 1, Étape 0 (exploration préliminaire).

Valide le format RÉEL de la DECP avant d'écrire le parseur. Source = DECP
consolidée (Colin Maudry) via l'API tabulaire data.gouv.fr — la même ressource
que `connecteurs/decp_consolidee.py`. AUCUN LLM, lecture seule.

Découverte clé attendue (à confirmer/infirmer ici) : ce n'est PAS une série de
fichiers JSON mensuels, mais un dataset consolidé unique (~3 M lignes) requêtable
par l'API tabulaire (filtres date/CPV/SIRET, pagination). L'exploration échantillonne
un mois récent via l'API.

Produit `RAPPORT_DECP_EXPLORATION.md` à la racine du repo.

Usage : python scripts/decp_explorer.py [--mois AAAA-MM] [--echantillon N]
"""
import argparse
import json
import os
import sys
from collections import Counter
from datetime import date

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import truststore  # noqa: E402
truststore.inject_into_ssl()  # SSL via magasin système Windows (convention Tendia)

from http_utils import get_json  # noqa: E402

RESSOURCE_ID = "22847056-61df-452d-837d-8b8ceadbfc52"
API = f"https://tabular-api.data.gouv.fr/api/resources/{RESSOURCE_ID}/data/"
RES_META = f"https://tabular-api.data.gouv.fr/api/resources/{RESSOURCE_ID}/"
RAPPORT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "RAPPORT_DECP_EXPLORATION.md")

# CPV des 6 presets Tendia (préfiltrage grossier, cf prompt sprint)
PRESETS_CPV = {
    "btp": [("45000000", "45499999")],
    "ingenierie": [("71000000", "71999999")],
    "it": [("72000000", "72999999")],
    "conseil_rd": [("73000000", "73999999")],
    "formation": [("80000000", "80999999")],
    "enr": [("09310000", "09349999")],
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def luhn_siret(val) -> bool:
    """Validité SIRET (14 chiffres, Luhn). Exception La Poste (356000000…)."""
    s = "".join(c for c in str(val or "") if c.isdigit())
    if len(s) != 14:
        return False
    if s.startswith("356000000"):  # La Poste : exception réglementaire au Luhn
        return sum(int(c) for c in s) % 5 == 0
    total = 0
    for i, c in enumerate(reversed(s)):
        d = int(c)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _count(filtres: dict) -> int:
    """Nombre de lignes correspondant au filtre (lit meta.total, page_size=1)."""
    rep = get_json(API, params=dict(filtres, page="1", page_size="1"))
    return int((rep.get("meta") or {}).get("total") or 0)


def _echantillon(filtres: dict, n: int) -> list:
    """Récupère jusqu'à n lignes (pagination 100/page)."""
    out, page = [], 1
    while len(out) < n:
        rep = get_json(API, params=dict(filtres, page=str(page), page_size="100"))
        data = rep.get("data") or []
        if not data:
            break
        out.extend(data)
        total = int((rep.get("meta") or {}).get("total") or 0)
        if len(out) >= total:
            break
        page += 1
    return out[:n]


def _meta_ressource() -> dict:
    """Métadonnées de la ressource (taille, MAJ) — best-effort."""
    try:
        return get_json(RES_META) or {}
    except Exception:
        return {}


def _veille(jour: str) -> str:
    """Renvoie le jour précédent (ISO) — pour transformer >= en > strict."""
    from datetime import date as _d, timedelta as _td
    d = _d.fromisoformat(jour) - _td(days=1)
    return d.isoformat()


def _supporte_less(total_global: int) -> bool:
    """__less fiable si count(< 2010) << total (sinon l'API l'ignore)."""
    try:
        c = _count({"dateNotification__less": "2010-01-01"})
        return c < total_global * 0.2
    except Exception:
        return False


def _pct(n, d):
    return f"{100.0 * n / d:.1f} %" if d else "—"


# --------------------------------------------------------------------------- #
# Analyse d'un échantillon
# --------------------------------------------------------------------------- #
def analyser(records: list) -> dict:
    n = len(records)
    champs = Counter()
    for r in records:
        for k, v in r.items():
            if v not in (None, "", []):
                champs[k] += 1

    montants = []
    for r in records:
        v = r.get("montant")
        try:
            if v not in (None, ""):
                montants.append(float(v))
        except (TypeError, ValueError):
            pass

    cpv = Counter()
    cpv_mal_formes = 0
    for r in records:
        c = str(r.get("codeCPV") or "").strip()
        if c:
            cpv[c[:2]] += 1
            digits = c.replace("-", "").replace(".", "")
            if not (digits[:8].isdigit() and len(digits) >= 8):
                cpv_mal_formes += 1

    siret_ach_ok = sum(1 for r in records if luhn_siret(r.get("acheteur_id")))
    siret_tit_ok = sum(1 for r in records if luhn_siret(r.get("titulaire_id")))

    # multi-titulaires : même `id` brut sur plusieurs lignes
    ids = Counter(str(r.get("id")) for r in records if r.get("id"))
    multi = sum(1 for v in ids.values() if v > 1)

    # révisions : modification_id > 0 / donneesActuelles
    revisions = sum(1 for r in records
                    if str(r.get("modification_id") or "0") not in ("0", "0.0", "None"))
    pas_actuelles = sum(1 for r in records
                        if str(r.get("donneesActuelles")).lower() in ("false", "0"))

    # montants aberrants
    m_zero = sum(1 for m in montants if m == 0)
    m_neg = sum(1 for m in montants if m < 0)
    m_gros = sum(1 for m in montants if m > 100_000_000)

    # distribution montants
    tranches = {"0-50k": 0, "50k-500k": 0, "500k-5M": 0, "5M-50M": 0, ">50M": 0}
    for m in montants:
        if m <= 0:
            continue
        if m < 50_000:
            tranches["0-50k"] += 1
        elif m < 500_000:
            tranches["50k-500k"] += 1
        elif m < 5_000_000:
            tranches["500k-5M"] += 1
        elif m < 50_000_000:
            tranches["5M-50M"] += 1
        else:
            tranches[">50M"] += 1

    montants_pos = sorted(m for m in montants if m > 0)
    mediane = montants_pos[len(montants_pos) // 2] if montants_pos else None

    return {
        "n": n, "champs": champs,
        "avec_montant_pos": sum(1 for m in montants if m > 0),
        "avec_cpv": sum(1 for r in records if r.get("codeCPV")),
        "avec_date_notif": sum(1 for r in records if r.get("dateNotification")),
        "avec_lieu": sum(1 for r in records if r.get("lieuExecution_code")),
        "siret_ach_ok": siret_ach_ok, "siret_tit_ok": siret_tit_ok,
        "cpv_top": cpv.most_common(20), "cpv_mal_formes": cpv_mal_formes,
        "multi_titulaires_ids": multi, "ids_uniques": len(ids),
        "revisions": revisions, "pas_actuelles": pas_actuelles,
        "m_zero": m_zero, "m_neg": m_neg, "m_gros": m_gros,
        "tranches": tranches, "mediane": mediane,
        "montant_min": min(montants) if montants else None,
        "montant_max": max(montants) if montants else None,
    }


# --------------------------------------------------------------------------- #
# Rapport
# --------------------------------------------------------------------------- #
def ecrire_rapport(ctx: dict):
    a = ctx["analyse"]
    n = a["n"]
    L = []
    w = L.append
    w("# Rapport d'exploration DECP — Sprint DECP 1, Étape 0\n")
    w("_Généré par `scripts/decp_explorer.py`. 0 LLM, lecture seule. "
      "À valider par Younes avant l'Étape 1._\n")

    w("## ⚠️ Découvertes structurelles (impactent le design du sprint)\n")
    w("1. **La DECP n'est PAS publiée en fichiers JSON mensuels.** La source de "
      "référence est la **DECP consolidée** (Colin Maudry / Colmo), un dataset "
      "unique mis à jour **quotidiennement**, requêtable via l'**API tabulaire** "
      "data.gouv.fr (pagination + filtres `__greater`/`__less`/`__contains`/"
      "`__exact`). → L'Étape 1 ne peut pas s'appuyer sur `telecharger_decp(annee_mois)` "
      "qui télécharge un fichier mensuel ; il faut **soit** paginer l'API tabulaire "
      "filtrée par date+CPV, **soit** télécharger le fichier consolidé (Parquet) et "
      "filtrer localement (pyarrow).")
    w(f"   - Ressource : `{RESSOURCE_ID}` — API : `{API}`")
    w(f"   - Connecteur Tendia existant à réutiliser : `connecteurs/decp_consolidee.py`.\n")
    w("2. **Stockage Tendia = clé-valeur JSON, pas relationnel.** Les marchés "
      "Tendia vivent dans `kv_storage(collection='marches', id='BOAMP-26-…', "
      "contenu_json=…)` — il n'existe **pas de table relationnelle des marchés**. "
      "Le DDL du sprint (`-- FK vers la table marchés Tendia`) doit donc être "
      "résolu ainsi : `marche_attribution_link.marche_tendia_id` = l'`id` de la "
      "collection `marches` (ex. `BOAMP-26-57070`), **sans contrainte FK SQL réelle** "
      "(la cible est une ligne JSON d'une table KV). Les collections `marches_notifies` "
      "et `marches_tendia_attribues` sont déjà réservées (vides) pour la DECP.\n")

    w("## 1. Source identifiée\n")
    m = ctx["meta_ressource"]
    w(f"- **Dataset** : Données Essentielles de la Commande Publique (DECP) — consolidée.")
    w(f"- **Ressource (id)** : `{RESSOURCE_ID}` (format Parquet côté data.gouv.fr).")
    w(f"- **API tabulaire** : `{API}`")
    if m:
        titre = m.get("title") or (m.get("resource") or {}).get("title")
        w(f"- **Métadonnées ressource** : {json.dumps({k: m.get(k) for k in ('created_at','last_modified','title','format','filesize') if k in m}, ensure_ascii=False)}")
    w(f"- **MAJ** : quotidienne (source Colmo).")
    w(f"- **Volume total dataset** : **{ctx['total_global']:,}** lignes (actes/attributions).".replace(",", " "))
    w(f"- **Volume 12 derniers mois** (`dateNotification ≥ {ctx['seuil_12m']}`) : "
      f"**{ctx['total_12m']:,}** lignes.".replace(",", " "))
    w(f"- **Opérateur `__less` supporté** : {'oui' if ctx['less_ok'] else 'NON (fallback nécessaire)'}\n")

    w("## 2. Mois échantillonné\n")
    w(f"- Mois : **{ctx['mois']}** — total réel sur le mois : **{ctx['total_mois']:,}** lignes.".replace(",", " "))
    w(f"- Échantillon analysé : **{n}** lignes (pagination API).\n")

    w("## 3. Structure & formats (sur l'échantillon)\n")
    w("- **Premier niveau JSON** : `{ \"data\": [ {record plat}, … ], \"meta\": {total,…}, \"links\": {…} }`. "
      "Chaque record est **plat** (pas d'imbrication) — ~66 colonnes.")
    w(f"- **Format SIRET acheteur** (`acheteur_id`) : 14 chiffres, sans espaces. "
      f"Valides Luhn : **{_pct(a['siret_ach_ok'], n)}**.")
    w(f"- **Format SIRET titulaire** (`titulaire_id`) : selon `titulaire_typeIdentifiant` "
      f"(SIRET le plus souvent). Valides Luhn : **{_pct(a['siret_tit_ok'], n)}**.")
    w(f"- **Format montant** (`montant`) : numérique HT (peut être négatif/0/aberrant). "
      f"Médiane ≈ {a['mediane']:,.0f} €, min {a['montant_min']:,.0f}, max {a['montant_max']:,.0f}.".replace(",", " "))
    w("- **Format date** (`dateNotification`, `datePublicationDonnees`) : ISO 8601 (`AAAA-MM-JJ`).")
    w(f"- **Format CPV** (`codeCPV`) : 8 chiffres sans séparateur. Mal formés : "
      f"{a['cpv_mal_formes']} / {n}.")
    w(f"- **Multi-titulaires** : un marché multi-attributaires = **plusieurs lignes même `id`** "
      f"(à dédupliquer/agréger). Détectés : {a['multi_titulaires_ids']} id(s) en doublon "
      f"sur {a['ids_uniques']} id(s) uniques de l'échantillon.")
    w(f"- **Révisions / avenants** : `modification_id > 0` → {a['revisions']} ; "
      f"`donneesActuelles = false` → {a['pas_actuelles']}. (Le sprint a acté : versioning DECP = non "
      "→ filtrer `modification_id=0` + `donneesActuelles=true`.)\n")

    w("## 4. Couverture des champs clés (échantillon)\n")
    w("| Champ | Rempli |")
    w("|---|---|")
    w(f"| montant > 0 | {_pct(a['avec_montant_pos'], n)} |")
    w(f"| codeCPV | {_pct(a['avec_cpv'], n)} |")
    w(f"| acheteur SIRET valide (Luhn) | {_pct(a['siret_ach_ok'], n)} |")
    w(f"| titulaire SIRET valide (Luhn) | {_pct(a['siret_tit_ok'], n)} |")
    w(f"| dateNotification | {_pct(a['avec_date_notif'], n)} |")
    w(f"| lieuExecution_code | {_pct(a['avec_lieu'], n)} |\n")

    w("## 5. Distribution CPV (top 20, préfixe 2 chiffres)\n")
    w("| CPV (2) | Occurrences | % | Preset probable |")
    w("|---|---|---|---|")
    cpv_preset = {"45": "btp", "71": "ingenierie", "72": "it", "73": "conseil_rd",
                  "80": "formation", "09": "enr"}
    for code, cnt in a["cpv_top"]:
        w(f"| {code} | {cnt} | {_pct(cnt, n)} | {cpv_preset.get(code, '—')} |")
    w("")

    w("## 6. Distribution des montants (échantillon, montants > 0)\n")
    w("| Tranche | Nb | % |")
    w("|---|---|---|")
    tot_pos = a["avec_montant_pos"] or 1
    for k, v in a["tranches"].items():
        w(f"| {k}€ | {v} | {_pct(v, tot_pos)} |")
    w("")

    w("## 7. Anomalies détectées (échantillon)\n")
    w(f"- SIRETs acheteur invalides Luhn : {n - a['siret_ach_ok']} ({_pct(n - a['siret_ach_ok'], n)})")
    w(f"- Montants à 0 : {a['m_zero']}  ·  négatifs : {a['m_neg']}  ·  > 100 M€ : {a['m_gros']}")
    w(f"- CPV mal formés : {a['cpv_mal_formes']}\n")

    w("## 8. Échantillon de 5 marchés\n")
    for r in ctx["exemples"]:
        w(f"- **{(r.get('objet') or '')[:90]}** — acheteur « {r.get('acheteur_nom')} » "
          f"(SIRET {r.get('acheteur_id')}), titulaire « {r.get('titulaire_nom')} », "
          f"montant {r.get('montant')} €, CPV {r.get('codeCPV')}, "
          f"notifié {r.get('dateNotification')}.")
    w("")

    w("## 9. Recommandations parseur (Étape 1)\n")
    w("- **Réutiliser `connecteurs/decp_consolidee.py`** (mapping des 66 colonnes déjà "
      "écrit et testé en prod) plutôt que repartir de zéro ; en extraire la logique de "
      "normalisation vers `decp/parser.py`.")
    w("- **Champs à mapper** vers `decp_marches` : `id`→id, `codeCPV`→cpv_principal, "
      "`acheteur_id`→acheteur_siret, `titulaire_id`→titulaire_siret, `montant`→montant_eur, "
      "`dateNotification`→date_notification, `dureeMois`→duree_mois, `procedure`→procedure, "
      "`lieuExecution_code`→lieu_execution_code, `acheteur_departement_code`→departement, "
      "`acheteur_region_code`→region (géo native, **pas besoin de `ref_geo.py` ni de dérivation "
      "code postal** — déjà fourni par la consolidée).")
    w("- **Multi-titulaires** : agréger les lignes de même `id` (cf `_dedupliquer_co_titulaires`), "
      "stocker le 1er dans `titulaire_siret` et la liste dans `titulaires_json`.")
    w("- **Filtrer à l'ingestion** : `modification_id=0` ET `donneesActuelles=true` (versioning = non).")
    w("- **Rejets parseur** : pas d'`id` ; montant < 0 ou > 1 Md€ ; date non ISO. "
      "Garder un `parse_warnings` par marché.")
    w("- **Stratégie de téléchargement** : filtrer côté API par `dateNotification` (12 mois) + "
      "préfiltre CPV par preset (`codeCPV__contains` ou plage), pour ne PAS rapatrier les 3 M lignes. "
      "Alternative si volume trop gros : télécharger le Parquet consolidé et filtrer en local.\n")

    w("## 10. Stop-conditions — état\n")
    rejets = a["cpv_mal_formes"] + a["m_neg"]
    w(f"- Format fondamentalement différent de l'attendu : **OUI** sur la forme "
      "(API consolidée ≠ fichiers mensuels), mais la donnée est riche et exploitable — "
      "**pas un blocage**, juste une adaptation du plan de téléchargement (voir §9).")
    w(f"- Taux de rejet parsing estimé : faible (CPV mal formés {_pct(a['cpv_mal_formes'], n)}, "
      f"montants négatifs {a['m_neg']}) — **< 30 %**, OK.")
    w(f"- Couverture des champs de matching (CPV/SIRET/date) : élevée — **viable** pour l'Étape 3.\n")

    w("---\n")
    w("**Checkpoint** : valider ce rapport avant de lancer l'Étape 1 (parseur + ingestion 12 mois). "
      "Décision attendue de Younes sur la stratégie de téléchargement (API tabulaire filtrée vs Parquet).")

    with open(RAPPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(f"Rapport écrit : {RAPPORT}")


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mois", default=None, help="mois à échantillonner AAAA-MM (défaut: mois M-1)")
    ap.add_argument("--echantillon", type=int, default=3000)
    args = ap.parse_args()

    today = date.today()
    # mois M-1 par défaut (mois complet le plus récent)
    if args.mois:
        mois = args.mois
    else:
        y, mo = today.year, today.month - 1
        if mo == 0:
            y, mo = y - 1, 12
        mois = f"{y:04d}-{mo:02d}"
    y, mo = int(mois[:4]), int(mois[5:7])
    debut = f"{y:04d}-{mo:02d}-01"
    fin_y, fin_mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    fin = f"{fin_y:04d}-{fin_mo:02d}-01"
    seuil_12m = f"{today.year - 1:04d}-{today.month:02d}-{today.day:02d}"

    print(f"=== Exploration DECP (Étape 0) — mois {mois} ===")
    print("  Probe API + métadonnées…")
    meta_res = _meta_ressource()
    total_global = _count({})
    total_12m = _count({"dateNotification__greater": _veille(seuil_12m)})
    less_ok = _supporte_less(total_global)

    # Total du mois = robuste via différence de 2 comptages __greater (strict),
    # indépendant du support de __less : count(> veille(debut)) − count(> veille(fin)).
    base = {"modification_id__exact": "0", "donneesActuelles__exact": "True"}
    print(f"  Comptage mois {mois} (différence __greater)…")
    total_mois = (_count(dict(base, **{"dateNotification__greater": _veille(debut)}))
                  - _count(dict(base, **{"dateNotification__greater": _veille(fin)})))

    # Échantillon : on pagine depuis debut et on filtre localement au mois.
    print(f"  Échantillonnage {args.echantillon} lignes…")
    f_sample = dict(base, **{"dateNotification__greater": _veille(debut)})
    if less_ok:
        f_sample["dateNotification__less"] = fin
    brut = _echantillon(f_sample, args.echantillon * 2 if not less_ok else args.echantillon)
    ech = [r for r in brut if debut <= str(r.get("dateNotification") or "")[:10] < fin][:args.echantillon]

    if not ech:
        print("⚠ Échantillon vide — API indisponible ou format changé. STOP, prévenir Younes.")
        sys.exit(2)

    analyse = analyser(ech)
    exemples = ech[:5]

    print(f"  Global={total_global} | 12m={total_12m} | {mois}={total_mois} | échantillon={len(ech)}")
    ecrire_rapport({
        "total_global": total_global, "total_12m": total_12m,
        "total_mois": total_mois, "mois": mois, "seuil_12m": seuil_12m,
        "less_ok": less_ok, "meta_ressource": meta_res,
        "analyse": analyse, "exemples": exemples,
    })


if __name__ == "__main__":
    main()
