# Planifier les téléchargements DCE anti-ban (Windows Task Scheduler)

Le batch AWS-Achat (`retelecharger_aws_achat_anti_ban.py`) est volontairement
**lent** (≈75 s entre marchés, pauses de 15-30 min toutes les 20 marchés, cap
de 30 marchés/jour, uniquement aux heures de bureau). C'est ce qui le rend
indistinguable d'un usage humain et évite le ban IP.

Pour couvrir les 81 marchés AWS-Achat sans surveiller la console, on programme
le script sur **3 matinées consécutives** via le Planificateur de tâches
Windows. Le script étant **idempotent** (il skippe les marchés déjà
téléchargés et reprend les restants), il suffit de le relancer chaque jour.

> Rappel : il faut que la clé `TWOCAPTCHA_API_KEY` soit présente dans
> `C:\Users\sai-y\Tendia\.env`, et que l'ordinateur soit allumé à l'heure
> programmée.

---

## Méthode A — Interface graphique (recommandée)

### Créer la tâche du lundi

1. Ouvrir le menu Démarrer → taper **« Planificateur de tâches »** → Entrée.
2. Dans le panneau de droite, cliquer **« Créer une tâche… »** (pas « tâche de
   base » : on a besoin des options avancées).
3. Onglet **Général** :
   - Nom : `Tendia DCE AWS lundi`
   - Cocher **« Exécuter même si l'utilisateur n'est pas connecté »** (optionnel)
   - Cocher **« Exécuter avec les autorisations maximales »**
4. Onglet **Déclencheurs** → **Nouveau…** :
   - Lancer la tâche : **Selon un planning**
   - **Hebdomadaire**, cocher **Lundi**, à **09:00:00**
   - OK
5. Onglet **Actions** → **Nouveau…** :
   - Action : **Démarrer un programme**
   - Programme/script : `python.exe`
     (ou le chemin complet, ex. `C:\Users\sai-y\AppData\Local\Programs\Python\Python3xx\python.exe` ;
     pour le trouver : dans un terminal, `where python`)
   - Ajouter des arguments : `retelecharger_aws_achat_anti_ban.py --oui`
   - **Commencer dans (facultatif)** : `C:\Users\sai-y\Tendia`
     ⚠️ Ce champ est **indispensable** : le script lit `.env` et la base via des
     chemins relatifs. Sans lui, il échoue.
   - OK
6. Onglet **Conditions** :
   - Décocher « Ne démarrer la tâche que si l'ordinateur est relié au secteur »
     si c'est un portable que tu veux voir tourner sur batterie.
   - Cocher **« Sortir l'ordinateur du mode veille pour exécuter cette tâche »**
     si tu veux qu'il se réveille.
7. Onglet **Paramètres** :
   - Cocher **« Exécuter la tâche dès que possible après un démarrage planifié
     manqué »** (rattrape si le PC était éteint à 9h).
8. **OK** pour enregistrer.

### Dupliquer pour mardi et mercredi

Le plus simple :
1. Dans la bibliothèque du Planificateur, clic droit sur `Tendia DCE AWS lundi`
   → **Exporter…** → enregistre un `.xml`.
2. Clic droit dans la bibliothèque → **Importer une tâche…** → choisis le `.xml`.
3. Renomme en `Tendia DCE AWS mardi`, va dans **Déclencheurs**, édite le jour →
   **Mardi**. Idem pour mercredi.

Le script étant idempotent, lancer 3 jours d'affilée suffit :
`30 marchés/jour × 3 jours = 90 ≥ 81`.

---

## Méthode B — Ligne de commande (`schtasks`)

À lancer dans un terminal **PowerShell en administrateur**, depuis n'importe où
(adapte le chemin de `python.exe` si besoin — `where python`) :

```powershell
$py  = (Get-Command python).Source
$dir = "C:\Users\sai-y\Tendia"
$arg = "retelecharger_aws_achat_anti_ban.py --oui"

# Le /TR combine programme + arguments. On force le dossier de travail via cmd.
foreach ($jour in @("MON","TUE","WED")) {
  schtasks /Create /TN "Tendia DCE AWS $jour" /SC WEEKLY /D $jour /ST 09:00 `
    /TR "cmd /c cd /d `"$dir`" && `"$py`" $arg" /F
}
```

Vérifier : `schtasks /Query /TN "Tendia DCE AWS MON" /V /FO LIST`
Supprimer : `schtasks /Delete /TN "Tendia DCE AWS MON" /F`

---

## Vérifier que ça tourne

- **Tester immédiatement** sans attendre 9h : dans le Planificateur, clic droit
  sur la tâche → **Exécuter**. (Attention : ça lance un vrai run réseau ;
  préfère un jour ouvré, sinon le garde-fou « heures de bureau » coupe le run.)
- **Logs** : le script écrit sa progression sur la sortie standard. Pour la
  conserver, change l'argument en :
  `retelecharger_aws_achat_anti_ban.py --oui > data\log_aws_%date%.txt 2>&1`
  (via une action `cmd /c`).
- **Forcer hors heures de bureau** (tests uniquement) : ajouter `--ignorer-heures`.
- **Limiter un run** : `--max 5` (utile pour la phase de validation à 5 marchés).

---

## Et les autres plateformes ?

- **achatpublic** (`retelecharger_achatpublic.py`) et **Atexo**
  (`retelecharger_incomplet.py`) n'ont jamais déclenché de ban. Ils utilisent un
  rate-limit randomisé léger (~10-15 s) sans contrainte d'heures ni cap. On peut
  les lancer à la main, ils tiennent en une session.
- **e-marchespublics** (15 marchés) : une seule session suffira quand le
  downloader sera livré.
