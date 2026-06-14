# Troubleshooting — erreurs connues & résolutions

Catalogue des erreurs réellement rencontrées et leur résolution.

## SSL / réseau

### `Connection error` sur api.anthropic.com (extraction LLM)
- **Cause** : sur ce poste Windows, `certifi` ne peut pas bâtir la chaîne TLS
  (CA intermédiaire absent / interception). Le SDK `anthropic` échoue.
- **Fix** : `truststore` injecté au chargement de `llm_extract.py` (utilise le
  magasin de certificats système). Vérifier que `truststore` est installé.

### `SSLCertVerificationError` sur *.e-marchespublics.com / 2captcha.com
- **Même cause**. Fix : `truststore` injecté dans `http_client.py` (importé par les
  downloaders). Dernier recours ponctuel : `telecharger_dce(..., verify_ssl=False)`.

### `pip install` échoue en SSL (`Could not find a version…`)
- **Fix** : `pip install <pkg> --trusted-host pypi.org --trusted-host files.pythonhosted.org`.

## Téléchargement DCE (downloaders)

### Dematis : captcha « code de vérification incorrect » malgré une bonne solution
- **Cause** : la solution du captcha est en **session PHP** ; Dematis pose
  `PHPSESSID` avec un attribut `Domain=` VIDE que `requests`/`cookielib` rejette →
  session perdue.
- **Fix** : `_installer_fix_cookies_domaine_vide` (hook réponse qui ré-injecte le
  cookie sur le bon hôte). Déjà en place dans `dematis_downloader`.

### Dematis : suit le mauvais lien (redirige vers l'accueil)
- **Cause** : la page annonce expose 2 tokens — un **leurre MD5 (32 hex)** et le bon
  **SHA-1 (40 hex)**.
- **Fix** : ne suivre que le token 40 hex (`_extraire_liens_anonymes` priorise SHA-1).

### Noms de fichiers en mojibake (`rÃ©seaux`, `mÃ©moire`)
- **Cause** : la page acces_dce mêle octets UTF-8 et latin-1 ; le `Content-Disposition`
  de getfile.php est décodé latin-1.
- **Fix** : `_decoder_liste_sans_perte` (latin-1 sans perte) + `_normaliser_nom_mojibake`
  (répare mojibake simple ET double), appliqué au libellé ET au Content-Disposition.

### Batch Dematis : 0 marché passe `complet` (tout en `skip`)
- **Cause** : skip idempotent — les marchés `incomplet` ont déjà 1 fichier (RC) ; le
  dossier n'était pas vidé avant re-DL.
- **Fix** : `retelecharger_dematis_anti_ban` vide le dossier après backup `.bak_avant_dematis`.

### Faux « ban » sur `www.e-marchespublics.com/appel-offre/<id>`
- **Cause** : ces URLs sont des pages de listing (pas d'annonce acheteur) →
  `ressemble_a_page_ban` les rejette.
- **Fix** : le batch écarte les URLs listing (ne garde que les annonces téléchargeables).

### Gros DCE très lent / bloqué
- **Cause** : `pdf_extract.extraire_dossier` sur un dossier de plusieurs Go (ex. RATP
  6 Go, BIM/DWG) est très lent ; le download proxy l'est aussi.
- **Atténuation** : dans la re-extraction Chantier 1, garde-fou de taille (skip + log
  des dossiers > 500 Mo). Pas de cap en téléchargement (politique « tout récupérer »).

## UI / serveur Flask

### Les changements UI n'apparaissent pas
- **Cause 1** : `debug=off` → pas d'auto-reload. Redémarrer `python tendia_ui.py`
  après toute modif de code/template.
- **Cause 2** : un **serveur stale** d'un lancement précédent tient encore le port 5000
  (Windows autorise 2 listeners via SO_REUSEADDR) → le navigateur tombe sur l'ancien.
  - Diagnostic : `netstat -ano | grep :5000` (plusieurs PID LISTENING).
  - Fix : `taskkill /PID <stale> /F`, garder un seul serveur.
- **Cause 3** : cache navigateur → **Ctrl+F5**.

### `/explorer` lent (~2 s)
- **Normal** : le verdict/score est calculé à la volée via `matching.evaluer` pour
  ~430 marchés (non caché). Acceptable pour un outil interne.

## Environnement / scripts

### `UnicodeEncodeError 'charmap'` à l'affichage console
- **Cause** : console Windows en cp1252, caractères ✓/◆/accents non encodables.
- **Fix** : `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` en tête de script.
- (À l'inspection ad hoc, l'affichage peut tromper : se fier aux **codepoints**, pas
  au rendu console.)

### Sortie d'un script en arrière-plan vide
- **Cause** : Python bufferise stdout quand la sortie est un fichier (pas un TTY).
- **Contournement** : écrire un log flushé par étape (ex. JSONL), ou se fier à la base.

### `bytes can only contain ASCII literal characters`
- **Cause** : littéral `b"…"` avec accents dans un script de test.
- **Fix** : comparer sur du texte décodé (`.decode('utf-8')`), pas sur des bytes accentués.

## Données / intégrité

### Domaines `it_*` non mappés / preset IT cassé
- **Cause (corrigée)** : `presets/it/_preset.json` contenait par erreur le contenu du
  preset ingénierie (en HEAD). Restauré (commit `8d57803`).
- **Leçon** : un `meta.code` doit correspondre au dossier ; vérifier l'unicité.

### Code domaine non reconnu (`energia_amo_etudes`)
- **Cause** : typo dans la classification d'un marché (hors taxonomie → 0 preset).
- **Fix** : corriger le code dans `briefs_extraits`/`classifications_ia` du marché.
