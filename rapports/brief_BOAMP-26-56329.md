# Brief — Acquisition, mise en oeuvre et maintenance d'un système d'information des ressources humaines RH

_Généré le 2026-06-15 20:40 par Claude claude-sonnet-4-6_

## Identifiants
- **ID Tendia** : `BOAMP-26-56329`
- **Source** : BOAMP `26-56329`
- **Référence interne acheteur** : `2026-029`
- **Acheteur** : OPCO MOBILITES
- **Date limite de dépôt** : **2026-07-10**
- **DCE PLACE** : <https://www.marches-publics.info/mpiaws/index.cfm?fuseaction=dematEnt.login&amp;type=DCE&amp;IDM=1832389>

## Synthèse
OPCO Mobilités lance un marché composite en 2 lots pour l'acquisition, la mise en œuvre et la maintenance d'un SIRH complet en mode SaaS. Le lot 1 couvre l'externalisation du traitement de la paie et l'outil de gestion de la paie, tandis que le lot 2 porte sur les modules ADP, GTA, gestion de carrière, recrutement, formation et pilotage salarial. Le marché est estimé à 840 000 € HT sur 4 ans (2 ans fermes + 2 reconductions d'1 an), avec une procédure avec négociation.

## 💶 Montant du marché
- **Valeur estimée** : **840 000 €**
  - sur 4 ans (2 ans fermes + 2 reconductions d'1 an)
  - _source : CCAP Article 4 page 4-5_
- _Note_ : Estimation globale indicative non contractuelle : 210 000 € HT/an × 4 ans = 840 000 € HT. Lot 1 : 67 200 € HT/an forfait + 16 800 € HT/an bons de commande = 84 000 €/an → 336 000 € sur 4 ans. Lot 2 : 100 800 € HT/an forfait + 25 200 € HT/an bons de commande = 126 000 €/an → 504 000 € sur 4 ans. Montants maximaux bons de commande : lot 1 plafond 70 000 € HT, lot 2 plafond 105 000 € HT sur toute la durée.

## Barème de notation
- **Valeur technique** : 80 %
- **Valeur prix** : 20 %
- **Sous-critères techniques** :
  - Qualité et conformité de la prestation d'externalisation de la paie : 20 %
  - Processus et méthodologie de déploiement de l'outil de gestion de la paie : 15 %
  - Fonctionnalités attendues et paramétrage : 15 %
  - Suivi de la prestation (accompagnement experts paie OPCO Mobilités) : 15 %
  - Exploitation et maintenance : 15 %
  - Processus et méthodologie de déploiement de l'outil SIRH (Lot 2) : 20 %
  - Fonctionnalités attendues et paramétrage (Lot 2) : 20 %
  - Suivi de la prestation (accompagnement experts RH OPCO Mobilités) (Lot 2) : 20 %
  - Exploitation et maintenance (Lot 2) : 10 %
- **Calcul du prix** : Pondération prix = 20% de la note globale. Chiffrage mixte : part forfaitaire (DPGF annuelle) + part à bons de commande (BPU avec DQE sur 4 ans comme base de comparaison financière non contractuelle). Formule exacte non communiquée dans les pièces disponibles.

## Références et qualifications exigées
- **Expérience minimale** : —
- **Secteur d'expérience** : Intégration et externalisation de SIRH (outil de paie, ADP, GTA, recrutement, formation, GEPP) pour des structures de 500 salariés ou plus, idéalement dans le secteur paritaire/associatif ou opérateurs de compétences
- **Autres exigences** :
  - SSO obligatoire via Azure Active Directory (Entra ID) avec SAML 2.0 ou OAuth2/OpenID Connect — aucune dérogation sans validation OPCO Mobilités (source=CCTP Article 4.G.2 et Article 5.J.2)
  - Hébergement SaaS avec connexion SSL minimum, données de préférence en France, tolérance UE (source=CCTP Article 4.I.10.a et Article 5.L.10.a)
  - Conformité RGPD attestée avec remplissage du cadre de réponse RGPD (Annexe 2 CCAP) (source=CCAP Article 12.2 et Annexe 2)
  - Fourniture d'un SOC 2 (niveau de référence attendu) communicable sur demande (source=CCTP Article 4.I.10.f et Article 5.L.10.g)
  - Attestation relative à l'interdiction d'attribution des marchés publics aux entreprises russes à fournir obligatoirement (source=AE Lot 1 et AE Lot 2)

## Lots
- **Lot 1** — SIRH Outil de Paie / Externalisation de la prestation de traitement de la paie
  - Volume estimé : 336000 euros HT sur 4 ans
  - Marché composite : forfait annuel estimé 67 200 € HT/an + bons de commande plafonnés à 70 000 € HT sur 4 ans. Inclut l'externalisation du cycle de paie complet (bulletins classiques, STC, DSN, OD Sage), le traitement des absences CPAM, l'outil paie avec coffre-fort numérique et passerelle bancaire, ~500-700 bulletins/mois. Logiciel paie actuel à migrer : Nibelis. Particularité : statut VLU URSSAF (pas de télépaiement possible). CPV lot : 79211110.
- **Lot 2** — SIRH outil de Gestion de l'ADP, la GTA et la Gestion de carrière (formation, recrutement, campagne d'entretiens)
  - Volume estimé : 504000 euros HT sur 4 ans
  - Marché composite : forfait annuel estimé 100 800 € HT/an + bons de commande plafonnés à 105 000 € HT sur 4 ans. Périmètre très large : 10 modules (recrutement avec multidiffusion illimitée, ADP/pré-boarding, GTA, formation/PDC, GEPP avec référentiel 45 emplois/45 compétences, entretiens annuels, pilotage salarial/BDESE). Interconnexion obligatoire avec lot 1. ~550 utilisateurs dont 60 managers. Signature électronique avancée requise. Reprise entretiens depuis 01/01/2024. CPV lot : 48450000.

## ⚠ Alertes candidat
- SSO via Azure AD (Entra ID) OBLIGATOIRE sans alternative locale : toute solution ne supportant pas SAML 2.0 ou OAuth2/OpenID Connect avec Azure AD est éliminatoire (CCTP art. 4.G.2 et 5.J.2).
- Interconnexion inter-lots impérative : les deux lots doivent communiquer en temps réel (flux GTA → paie, absences CPAM, formation ↔ GTA). En cas de prestataires distincts, la compatibilité technique doit être démontrée avec des exemples d'interconnexions existantes.
- Externalisation du traitement des absences CPAM (saisie arrêts, recouvrement IJSS, DSN évènementiels) : compétence métier exigeante et spécifique, souvent sous-traitée — le titulaire lot 1 reste responsable du rendu même en cas de sous-traitance (CCTP art. 4.B.2.e).
- Délai de validité des offres de 180 jours : engagement financier long sur des prix SaaS potentiellement variables — bien anticiper les révisions possibles et la clause de sauvegarde +4%.
- Procédure avec négociation : une première offre sera soumise à négociation. Prévoir une marge de manœuvre dans le chiffrage initial pour la phase de négociation sans dégrader la qualité technique.

## 💡 Points différenciants attendus
- Référence sectorielle OPCO / paritaire ou opérateur de compétences avec externalisation de paie complexe (exemple=Citer 2-3 clients du même secteur (OPCO, OPCA, branche professionnelle) avec périmètre similaire (500+ salariés, statut VLU URSSAF, accord de performance collective) valorise fortement la crédibilité sur la conformité réglementaire et la gestion des spécificités conventionnelles., source=CCTP Article 4.B.2.a)
- Gestionnaire de paie dédié et nominatif avec back-up identifié dès l'offre (exemple=Présenter le CV du gestionnaire paie attitré (senior, maîtrise DSN, VLU, accords de performance collective) et de son back-up nominatif renforce significativement le sous-critère 1 (20 pts) et rassure sur la continuité de service., source=CCTP Article 4.B.2.b et CRT Lot 1 sous-critère n°1)
- Solution couvrant les deux lots avec un seul prestataire (SIRH intégré paie + HCM) (exemple=Proposer une solution couvrant lot 1 et lot 2 sur une plateforme unifiée élimine le risque d'incompatibilité inter-lots et simplifie la gouvernance projet — argument fort pour scorer sur les sous-critères d'interfaçage des deux CRT., source=CCTP Article 3 et Articles 4.C.9 / 5.G.1.c)
- Maîtrise de la gestion des spécificités RH OPCO Mobilités : CET, plan senior, VLU URSSAF, accord de performance collective (exemple=Démontrer une expérience documentée sur le CET (alimentation, indemnisation, transfert PERO), le plan de départ progressif senior et le statut VLU URSSAF (pas de télépaiement, gestion des cotisations) avec des exemples de paramétrages réalisés chez d'autres clients., source=CCTP Articles 4.B.2.d et 5.C.1 à 5.C.5)
- Architecture SaaS hébergée en France avec SOC 2 Type II disponible et PRA/PCA documenté (exemple=Joindre le résumé exécutif SOC 2 Type II de la solution et une fiche PRA avec RTO H+4 testé annuellement. Préciser la localisation exacte des datacenters (France) et les certifications ISO 27001 de l'hébergeur renforce la crédibilité sécurité face aux exigences RGPD et ANSSI., source=CCTP Articles 4.I.10 et 5.L.10 ; CCAP Article 12.3)
- Intégration native du référentiel emplois-compétences OPCO Mobilités (4 filières, 45 emplois, 45 compétences, niveaux 1-4) (exemple=Présenter une maquette ou capture d'écran de la saisie du référentiel fourni par OPCO Mobilités dans l'outil, avec les vues radar de compétences par salarié et l'alimentation automatique des campagnes d'entretiens annuels, démontre une compréhension fine du besoin lot 2., source=CCTP Article 5.F.2)
