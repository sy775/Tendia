# Brief — Tierce Maintenance Applicative des applications SYMBIOSE et PARIS pour le compte de l’ASNR.

_Généré le 2026-06-20 01:09 par Claude claude-sonnet-4-6_

## Identifiants
- **ID Tendia** : `BOAMP-26-56760`
- **Source** : BOAMP `26-56760`
- **Référence interne acheteur** : `ASNR_2026_027_SYMBIOSE_PARIS`
- **Acheteur** : AUTORITE DE SURETE NUCLEAIRE ET DE RADIOPROTECTION
- **Date limite de dépôt** : **2026-07-29**
- **DCE PLACE** : <https://www.marches-publics.gouv.fr/?page=Entreprise.EntrepriseDetailsConsultation&id=3015064&orgAcronyme=d4t>

## Synthèse
L'ASNR (Autorité de Sûreté Nucléaire et de Radioprotection) lance un appel d'offres ouvert en deux lots pour la Tierce Maintenance Applicative (TMA) de ses applications SYMBIOSE (plateforme de modélisation du risque radiologique, lot 1, 400 000 € HT max) et PARIS (LIMS de gestion des analyses de laboratoire, lot 2, 380 000 € HT max). Chaque lot constitue un accord-cadre à bons de commande de 48 mois maximum (12 mois fermes + 3 reconductions tacites), couvrant prise en charge, MCO, maintenance évolutive et réversibilité. Le prestataire intervient principalement depuis ses locaux avec des déplacements occasionnels à Cadarache (lot 1) ou au Vésinet/Orsay (lot 2).

## 💶 Montant du marché
- **Plafond accord-cadre** : **780 000 €**
  - sur 48 mois maximum (accord-cadre, périodes de reconduction comprises)
  - _source : RC art 2.4 / AE_SYMBIOSE et AE_PARIS / CCAP_PARIS art 3.2 / CCAP_SYMBIOSE art 3.2_
- _Note_ : Lot 1 SYMBIOSE : plafond 400 000 € HT sur 48 mois. Lot 2 PARIS : plafond 380 000 € HT sur 48 mois. Total plafond consolidé : 780 000 € HT. Sans montant minimum garanti (les bons de commande sont émis selon les besoins). La valeur réelle consommée sera inférieure au plafond selon l'activité réelle de l'ASNR.

## Barème de notation
- **Valeur technique** : 60 %
- **Valeur prix** : 40 %
- **Sous-critères techniques** :
  - Organisation et méthodologies proposées pour les prestations de prise en charge et réversibilité : 5 %
  - Organisation et méthodologies proposées relatives aux prestations de TMA : 25 %
  - Compétences proposées (CV) et garanties en termes de maintien des compétences et de continuité de service : 30 %
- **Calcul du prix** : Note prix = (prix de l'offre la moins distante × pondération du sous-critère) / prix de l'offre considérée, puis somme des notes pondérées. RC art 6.2.2.2.a.

## Références et qualifications exigées
- **Expérience minimale** : —
- **Secteur d'expérience** : TMA d'applications informatiques scientifiques ou métier (logiciels de calcul, LIMS, SI de laboratoire) — aucun secteur spécifique explicitement exigé dans le RC
- **Autres exigences** :
  - Déclaration du chiffre d'affaires global et du CA dans le domaine d'activité faisant l'objet du marché (3 derniers exercices) (source=RC art 4.4 (tableau capacités économiques))
  - Déclarations appropriées de banques et preuve d'assurance couvrant les risques pertinents (source=RC art 4.4)
  - Bilans ou extraits de bilan des 3 dernières années (source=RC art 4.4)
  - Liste des principales prestations/livraisons en lien avec l'objet du marché au cours des 3 dernières années (source=RC art 4.4)
  - Déclaration des effectifs moyens annuels et importance du personnel d'encadrement sur 3 ans (source=RC art 4.4)

## Lots
- **Lot 1** — Tierce Maintenance Applicative de l'application SYMBIOSE
  - Zone : Fontenay-aux-Roses / Cadarache (13) — prestations principalement en locaux titulaire
  - Application scientifique SYMBIOSE (C++/QT/Fortran) de modélisation radiologique, copropriété ASNR/EDF. Deux composants à maintenir : IHM (QT 4.8.4/C++) et moteur de calcul (C++/Fortran via plateforme PELICANS). UOs différenciées : UO_MCO, UO_EVO_MOTEUR, UO_EVO_IHM, UO_PEC, UO_REV. Versioning SVN existant, migration vers GitLab. Déplacements occasionnels à Cadarache (13). Enquête sécurité (LPE) obligatoire pour tout intervenant.
- **Lot 2** — Tierce Maintenance Applicative de l'application PARIS pour le compte de l'ASNR
  - Zone : Vésinet (78) / Orsay (91) — prestations principalement en locaux titulaire
  - Volume estimé : 126 jours-homme/an
  - LIMS PARIS (WinDev 25, VBA Office 365, SQL Server, MS Access) utilisé par 25 utilisateurs simultanés dans les laboratoires SAME du Vésinet et d'Orsay. Répartition historique : 63% UO_EVO (83 j-h/an) + 33% UO_MCO (43 j-h/an). Besoins évolutifs importants : intégration de nouveaux processus analytiques LMRE (ICP-MS, ICP-AES, spectrométrie alpha, etc.). Gouvernance COPIL trimestrielle facturée en UO_MCO. IA autorisée pour développements (Claude Code, GitHub Copilot). Enquête sécurité (LPE) obligatoire.

## ⚠ Alertes candidat
- Habilitation sécurité individuelle obligatoire pour TOUT intervenant (Laisser Passer Entreprise + enquête CoSSeN) : délai de 4 à 6 semaines, à anticiper dès notification — tout personnel refusé ne peut ni accéder au site ni faire partie de l'équipe.
- Les CV des intervenants représentent 30% de la note globale (sous-critère le plus pondéré) : un dossier avec des profils non maîtres des technologies requises (C++/QT/Fortran pour lot 1 ; VBA/WinDev/SQL Server pour lot 2) sera éliminatoire en pratique.
- Lot 1 (SYMBIOSE) : compétences en C++, Fortran, QT, Python ET QGIS requises simultanément — profil rare combinant développement scientifique bas-niveau et SIG ; vérifier la disponibilité de tels profils avant de candidater.
- Accord-cadre sans montant minimum garanti : aucun chiffre d'affaires n'est garanti sur 48 mois — la charge réelle peut être très inférieure au plafond selon les priorités de l'ASNR ; dimensionner l'équipe en conséquence.
- Clause butoir de résiliation si révision de prix > 3%/an : risque de résiliation unilatérale par l'ASNR en cas d'inflation supérieure à ce seuil — à intégrer dans la stratégie de pricing et la gestion des risques.

## 💡 Points différenciants attendus
- Présentation de CV nominatifs ultra-ciblés sur les technologies spécifiques de chaque application (exemple=Pour le lot 1 : présenter un CV détaillant des réalisations concrètes en C++11/14 sur des applications scientifiques, avec expérience QT 4.x et idéalement connaissance d'une plateforme de simulation numérique. Pour le lot 2 : CV montrant des projets WinDev sur LIMS ou applications de laboratoire, avec maîtrise SQL Server et VBA Excel., source=RC art 6.2.2.1 — sous-critère 'Compétences proposées' à 30%)
- Dispositif de continuité de service documenté et robuste face aux contraintes d'habilitation sécurité (exemple=Démontrer qu'au moins 2 intervenants habilités (ou en cours d'habilitation anticipée) sont disponibles pour chaque lot, avec une politique de binômage explicite et des engagements sur les délais de remplacement — en anticipant les 4 à 6 semaines de délai LPE., source=CCTP_SYMBIOSE §6.4 / CCTP_PARIS §6.4)
- Maîtrise des outils de l'usine logicielle ASNR (GitLab, CI/CD, SonarQube) dès la prise en charge (exemple=Citer des projets récents où le candidat a mis en place ou opéré des pipelines CI/CD sur GitLab (tests unitaires, qualité de code via SonarQube, gestion semver), en démontrant que l'équipe est opérationnelle sans temps d'apprentissage sur ces outils., source=CCTP_PARIS §6.5.1 / CCTP_SYMBIOSE §6.5.1)
- Compréhension du contexte scientifique et métier (radioprotection, LIMS, modélisation radiologique) (exemple=Valoriser toute expérience antérieure en maintenance d'applications scientifiques (calcul, simulation) ou de LIMS dans un contexte réglementé (nucléaire, laboratoires accrédités COFRAC) — même si non exigée formellement, elle réduit le risque perçu par l'ASNR.)
- Utilisation maîtrisée de l'IA pour les développements (lot 2 — explicitement autorisée par l'ASNR) (exemple=Décrire un retour d'expérience concret sur l'utilisation de GitHub Copilot ou Claude Code pour accélérer la maintenance corrective/évolutive, avec les garde-fous mis en place (revue de code, non-exposition de données sensibles aux LLM cloud, conformité OWASP)., source=CCTP_PARIS §6.5.9 / CCTP_SYMBIOSE §6.5.5)
