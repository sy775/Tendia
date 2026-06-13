# Tendia downloaders DCE — guide production

Comment faire tourner les téléchargeurs DCE en autonomie (cron), avec proxy
résidentiel rotatif, fingerprint TLS Chrome et monitoring. État au Sprint
Industrialisation v2 (13/06/2026).

---

## 1. Vue d'ensemble

```
            ┌─────────────────────────────────────────────┐
 cron  ───▶ │ retelecharger_aws_achat_anti_ban.py (batch)  │
            │  · cap /run, heures bureau, pauses, coûts     │
            └───────────────┬───────────────────────────────┘
                            │ telecharger_dce_pour_marche
                            ▼
            ┌─────────────────────────────────────────────┐
            │ aws_downloader / atexo / achatpublic          │
            │  · rotation IP sur ban   · backoff réseau     │
            │  · logs JSONL (tendia_logs)                   │
            └───────────────┬───────────────────────────────┘
                            │ creer_session_humaine(session_id)
                            ▼
        http_humain ──────────────────────────────────────────
          · UA tournant + headers Sec-Fetch (anti-ban)
          · délais gaussiens / inter-étapes / pauses
          · session-id Bright Data → 1 IP résidentielle / marché
                            │ Session()
                            ▼
        http_client ──────────────────────────────────────────
          · curl_cffi (TLS fingerprint Chrome 131) si dispo
          · fallback automatique sur requests sinon
                            │
                            ▼
        Proxy Bright Data ISP ($8/GB)  +  2captcha (résolution captcha AWS)
```

Couches complémentaires :
- **http_client** : *comment* on parle TCP/TLS (impersonate Chrome).
- **http_humain** : *à quel rythme* et *avec quelle identité* (UA, délais, IP).
- **downloaders** : la logique métier de chaque plateforme + robustesse.
- **batch** : l'orchestration sûre pour le cron.

---

## 2. Configuration (`.env` à la racine)

| Variable | Rôle | Requis |
|----------|------|--------|
| `ANTHROPIC_API_KEY` | extraction LLM des briefs | oui (briefs) |
| `TWOCAPTCHA_API_KEY` | résolution captcha AWS-Achat | oui (AWS-Achat) |
| `TENDIA_PROXY_URL` | proxy résidentiel rotatif | recommandé |

Format `TENDIA_PROXY_URL` (Bright Data ISP) :
```
TENDIA_PROXY_URL=http://brd-customer-<ID>-zone-<ZONE>:<PASSWORD>@brd.superproxy.io:22225
```
Si Bright Data est détecté (`brd.superproxy.io`), un `-session-<id>` est injecté
automatiquement dans le username pour piloter la rotation d'IP : **une IP par
marché** (session-id = id du marché), et **une nouvelle IP à chaque retry** en
cas de ban. Tout autre proxy est utilisé tel quel, sans injection.

Sans `TENDIA_PROXY_URL`, les downloaders sortent par l'IP locale (déconseillé en
batch — c'est ce qui a causé le ban du 13/06).

### Backend HTTP

`pip install curl_cffi` active le fingerprint TLS Chrome. Vérifier :
```powershell
python -c "import http_client; print('Backend:', http_client.BACKEND)"
# Attendu : Backend: curl_cffi   (sinon 'requests' = fallback, OK mais moins furtif)
```
Si `curl_cffi` ne s'installe pas, **tout continue de fonctionner** en fallback
`requests` (un warning au démarrage, pas de crash).

---

## 3. Cron Windows Task Scheduler

Voir `docs/cron_windows.md` (procédure complète GUI + `schtasks`). Principe :
3 matinées lun-mar-mer, `retelecharger_aws_achat_anti_ban.py --oui`, script
idempotent → 30 marchés/jour × 3 ≥ les ~70 marchés AWS restants.

---

## 4. Monitoring

Après chaque batch :
```powershell
python tendia_monitoring.py
```
Affiche : couverture DCE de la base, derniers batchs (logs JSONL), coûts du mois
(bande passante × $8/GB + captchas), marchés en échec à reprendre.

Les logs bruts sont dans `logs/<downloader>_<YYYY-MM-DD>.jsonl` (gitignorés).

---

## 5. Troubleshooting

| Symptôme | Cause probable | Action |
|----------|----------------|--------|
| Tous les marchés en `ban_persistant` | Pool/zone Bright Data brûlée, ou ban applicatif | Attendre 1-2 h, ou changer de zone Bright Data ; vérifier `TENDIA_PROXY_URL` |
| `ban_detecte` ponctuel | IP polluée | Normal : le wrapper retente seul sur une nouvelle IP (jusqu'à 3×) |
| Erreurs réseau répétées (`Timeout`/`ConnectionError`) | Endpoint proxy KO | Vérifier l'URL/le port Bright Data (22225), tester `curl -x $TENDIA_PROXY_URL https://api.ipify.org` |
| `solde_2captcha_epuise` | Crédit 2captcha à 0 | Recharger le compte 2captcha |
| `Backend: requests` au lieu de curl_cffi | `curl_cffi` non installé | `pip install curl_cffi` (optionnel : fallback fonctionne) |
| Captcha refusé 3× | OCR 2captcha en échec sur ce captcha | Le marché passe en erreur `captcha` ; il sera repris au prochain run |

---

## 6. Coûts attendus

- **Bright Data** : ~$5-15/mois en régime Tendia (DCE = quelques Mo/marché ;
  $8/GB). Un batch de 70 marchés ≈ quelques centaines de Mo → < $1.
- **2captcha** : ~$5/mois (seul AWS-Achat consomme des captchas, ~$0.001 pièce).
- **Total infra** : ~$10-20/mois. Le coût LLM (briefs) est suivi à part.

`tendia_monitoring.py` recalcule ces coûts depuis les logs réels chaque mois.

---

## 7. Évolutions futures

- **Sprint v3** : pool de zones Bright Data multiples avec failover automatique
  (si une zone est bannie, bascule sur la suivante).
- **Sprint v4** : Playwright headless pour les plateformes qui durciraient
  (JS obligatoire / challenges interactifs) — uniquement si curl_cffi+proxy ne
  suffisent plus. Robustesse > furtivité absolue.
