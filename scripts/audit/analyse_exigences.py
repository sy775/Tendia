"""
analyse_exigences.py
--------------------
Mesure ce que les acheteurs demandent aux candidats, à partir des briefs déjà
extraits (collection `briefs_extraits`, sauvegardes exclues).

Lecture seule : aucun appel LLM, aucun accès réseau, aucune écriture en base.
Le seul accès aux données passe par `stockage.charger`.

Sources agrégées par brief :
  P  dossier_candidature.pieces_a_fournir[]            (libellé, phase, obligatoire)
  C  references_exigees.certifications_obligatoires[]  (libellé, codes, bloquante)
  A  references_exigees.autres_exigences[]             (libellé)
  Q  qualifications_requises et blocs qualifications_* (listes de libellés)
  S  champs structurés (codes Qualibat, booléens RGE / MASE / ISO, expérience,
     nombre de références) : typés par construction, hors taux de typage.

Chaque libellé est rangé dans un ou plusieurs types par un dictionnaire de
motifs (TYPES ci-dessous). Un libellé sans aucun type est « non reconnu ».

Sorties (dans docs/analyse_profil/ du dépôt où se trouve CE fichier, et non via
`chemins.RACINE_DEPOT` : avec une installation éditable, RACINE_DEPOT désigne
le dépôt installé, qui peut être un autre worktree) :
  exigences_frequence.md      tableaux de fréquence
  exigences_types.csv         une ligne par type
  exigences_occurrences.csv   une ligne par libellé (noms de personnes masqués)
  exigences_non_reconnus.csv  libellés non reconnus, par fréquence
  exigences_couverture_candidature_btp.csv   couverture cumulée (minimum vital)

Usage :
    python scripts/audit/analyse_exigences.py
    python scripts/audit/analyse_exigences.py --sortie <dossier> --sans-projection
"""
import argparse
import csv
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tendia.core import stockage

SORTIE_DEFAUT = Path(__file__).resolve().parents[2] / "docs" / "analyse_profil"
RE_ID_COURANT = re.compile(r"^[A-Z]+-\d+-\d+$")   # les sauvegardes portent un suffixe « .bak_… »


# ---------------------------------------------------------------------------
# Dictionnaire des types : (code, nom usuel, famille, motifs sur texte normalisé)
# Le texte normalisé est en minuscules, sans accents, apostrophes droites.
# ---------------------------------------------------------------------------
F_FORM = "Candidature : formulaires"
F_JUR = "Candidature : situation juridique, fiscale et sociale"
F_ASS = "Assurances"
F_FIN = "Capacité financière"
F_TECH = "Capacité technique et professionnelle"
F_QUAL = "Qualifications et certifications"
F_OFFRE = "Offre"
F_EXEC = "Engagements et exécution"
F_DIV = "Divers"

TYPES = [
    # --- formulaires de candidature
    ("dc1", "DC1 / lettre de candidature", F_FORM,
     [r"\bdc ?1\b", r"lettres? de candidature", r"declaration d'intention de soumissionner"]),
    ("dc2", "DC2 / déclaration du candidat", F_FORM,
     [r"\bdc ?2\b", r"declaration du candidat"]),
    ("dume", "DUME", F_FORM,
     [r"\be?-?dume\b", r"document unique de marche"]),
    ("dc4", "DC4 / déclaration de sous-traitance", F_FORM,
     [r"\bdc ?4\b", r"sous-?trait"]),
    ("groupement", "Pièces de groupement, capacités d'un tiers", F_FORM,
     [r"co-?traitan", r"\bmandat\b", r"convention de groupement", r"(en cas|si|dans le cas) (de |d'un )?groupement",
      r"repartition des prestations", r"capacites d'un tiers", r"operateurs? economiques? (sur lesquels|invoque)",
      r"capacites d'autres operateurs"]),
    ("attestation_honneur", "Déclaration sur l'honneur (interdictions de soumissionner)", F_FORM,
     [r"sur l'honneur", r"interdictions? de soumissionner", r"cas d'exclusion", r"non[- ]exclusion",
      r"n'entre dans aucun", r"l\.? ?2141", r"motifs? d'exclusion", r"interdictions? de concourir"]),
    # --- situation juridique, fiscale, sociale
    ("kbis", "Extrait Kbis / inscription au registre", F_JUR,
     [r"k-? ?bis", r"registre du commerce", r"registre de la profession", r"\brcs\b",
      r"repertoire des metiers", r"extrait d'immatriculation", r"registre national des entreprises",
      r"\bd1\b", r"inscription (sur un|au) registre", r"numero unique d'identification", r"\bsiret\b",
      r"\binsee\b", r"statuts", r"registre professionnel", r"\bsiren\b"]),
    ("urssaf", "Attestation URSSAF (régularité sociale, vigilance)", F_JUR,
     [r"urssaf", r"attestations? (de regularite )?sociales?", r"cotisations sociales",
      r"fiscales? et sociales?", r"sociales? et fiscales?", r"certificats? sociaux",
      r"attestations? de vigilance", r"regularite (fiscale et )?sociale", r"obligations (fiscales et )?sociales",
      r"\bnoti ?2\b", r"\bmsa\b", r"conges payes", r"declarations sociales", r"organismes sociaux"]),
    ("fiscale", "Attestation de régularité fiscale", F_JUR,
     [r"attestations? (de regularite )?fiscales?", r"regularite fiscale", r"impots",
      r"certificats? fiscaux", r"sociales? et fiscales?", r"fiscales? et sociales?",
      r"obligations fiscales", r"\bnoti ?2\b", r"administration fiscale", r"\bdgfip\b",
      r"liasse 3666", r"situation fiscale"]),
    ("travail_dissimule", "Pièces de lutte contre le travail dissimulé (D.8222-5)", F_JUR,
     [r"travail dissimule", r"d\.? ?8222", r"l\.? ?8221", r"l\.? ?8222"]),
    ("lnte", "Liste nominative des travailleurs étrangers (LNTE)", F_JUR,
     [r"travailleurs? etrangers?", r"salaries etrangers", r"\blnte\b", r"d\.? ?8254",
      r"autorisation de travail", r"detaches et etrangers", r"salaries detaches", r"travailleurs detaches"]),
    ("obligation_emploi_th", "Obligation d'emploi des travailleurs handicapés", F_JUR,
     [r"obligation d'emploi", r"travailleurs handicapes", r"l\.? ?5212", r"\bagefiph\b"]),
    ("redressement", "Jugement de redressement judiciaire", F_JUR,
     [r"redressement judiciaire", r"jugements? prononces?", r"procedure de sauvegarde",
      r"liquidation judiciaire", r"procedure collective"]),
    ("pouvoir", "Pouvoir / délégation de signature", F_JUR,
     [r"\bpouvoirs?\b", r"habilite[es]* a engager", r"delegations? de (signature|pouvoir)",
      r"personnes? habilite", r"habilitation du signataire", r"capacite a engager",
      r"qualite du signataire", r"habilitation a signer"]),
    ("rib", "RIB", F_JUR,
     [r"\brib\b", r"releve d'identite bancaire", r"\biban\b", r"coordonnees bancaires"]),
    ("plateforme_attestations", "Dépôt des attestations sur une plateforme tierce (e-Attestations, Provigis)", F_JUR,
     [r"e-?attestations?", r"aprovall", r"provigis", r"attestation legale"]),
    ("sanctions_russie", "Attestation de non-soumission aux sanctions (Russie)", F_JUR,
     [r"\bruss", r"833/2014", r"mesures restrictives"]),
    ("conflit_interets", "Déclaration d'absence de conflit d'intérêts / indépendance", F_JUR,
     [r"conflits? d'interets?", r"liens? d'interets?", r"\bindependance\b"]),
    ("egalite_parite", "Égalité professionnelle, index, parité", F_JUR,
     [r"egalite (professionnelle|femmes|entre les femmes)", r"l\.? ?2242", r"index egalite"]),
    # --- assurances
    ("assurance_rc", "Attestation d'assurance RC professionnelle", F_ASS,
     [r"responsabilite civile(?! decennale)", r"\brc ?pro", r"risques professionnels",
      r"attestations? d'assurances?(?! decennale)", r"assurance professionnelle",
      r"polices? d'assurance", r"attestations? (d'|de l')assureur", r"assurances? en cours",
      r"justificatifs? d'assurance", r"assurance rc\b", r"certificats? d'assurance",
      r"assurances? (obligatoires|requises|exigees)", r"contrats? d'assurance", r"preuves? d'(une )?assurance",
      r"assurance (perte|responsabilite|couvrant|constructeur)"]),
    ("decennale", "Attestation d'assurance décennale", F_ASS,
     [r"decennale", r"\brcd\b", r"\b1792", r"l\.? ?241-1", r"biennale"]),
    # --- capacité financière
    ("ca_bilans", "Chiffre d'affaires, bilans", F_FIN,
     [r"chiffres? d'affaires?", r"\bca\b", r"\bbilans?(?! pedagogique)(?! carbone)(?! des emissions)(?! d'emissions)(?! ges)",
      r"comptes annuels", r"liasses? fiscales?", r"capacites? (economiques? et )?financieres?",
      r"comptes de resultat", r"situation financiere", r"capacite economique"]),
    ("declaration_bancaire", "Déclaration de banque / garantie financière", F_FIN,
     [r"declarations? (appropriees? )?(de |d'une |des )?banques?", r"garanties? financieres?",
      r"caution bancaire", r"cautionnement", r"garantie a premiere demande", r"retenue de garantie",
      r"capacite de prefinancement", r"attestation bancaire", r"etablissements? bancaires?", r"garantie bancaire"]),
    # --- capacité technique
    ("references", "Références de chantiers / prestations", F_TECH,
     [r"references?\b", r"travaux (similaires |equivalents )?(executes|realises)", r"principaux (services|travaux)",
      r"principales (prestations|fournitures|livraisons|realisations|missions)",
      r"liste des (travaux|services|prestations|marches|fournitures|chantiers|operations|realisations)",
      r"liste de (travaux|services|prestations)",
      r"experiences? (similaires?|professionnelles?|significatives?|dans|en matiere|d'au moins)",
      r"(prestations|chantiers|travaux|marches|operations|missions) (similaires|comparables|equivalent|de meme nature)",
      r"\d+ ans d'experience", r"experience (minimale|minimum|de \d+|≥|superieure)", r"realisations? (similaires|comparables|recentes)"]),
    ("bonne_execution", "Attestations de bonne exécution / certificats de capacité", F_TECH,
     [r"bonne execution", r"certificats? de capacite", r"bonne fin",
      r"attestations? (du|des|de) (destinataires?|maitres? d'ouvrage|clients?)"]),
    ("effectifs", "Déclaration des effectifs", F_TECH,
     [r"effectifs?\b"]),
    ("titres_etudes", "Titres d'études et professionnels, diplômes", F_TECH,
     [r"titres? d'etudes?", r"titres? professionnels?", r"diplomes?", r"titres? et (de )?l'experience"]),
    ("cv_moyens_humains", "CV, équipe, moyens humains", F_TECH,
     [r"\bcvs?\b", r"curriculum", r"moyens humains", r"moyens en personnel",
      r"equipes? (dediee|projet|affectee|proposee|mobilisee|d'intervention|candidate|de travail|technique)",
      r"organigramme", r"composition de l'equipe", r"personnels? (affecte|dedie|propose|mobilise|intervenant)",
      r"interlocuteur", r"\breferent\b", r"chef de (projet|chantier)", r"conducteur de travaux",
      r"note d'organisation", r"organisation (de l'entreprise|du candidat|generale)"]),
    ("moyens_materiels", "Outillage, matériel, moyens techniques", F_TECH,
     [r"outillage", r"moyens (humains et |humains, )?(techniques|materiels)", r"materiels? et (l'|d')?equipements?",
      r"equipements? techniques?", r"liste (du|des) materiels?", r"parc (de |)(materiel|vehicules|engins)",
      r"moyens (matériels|materiels)", r"moyens (generaux|logistiques|de l'entreprise|du candidat|mis en oeuvre|dont)",
      r"vehicules", r"engins", r"materiels? (dont|a disposition|disponible|utilise|propose|affecte)", r"locaux"]),
    ("presentation_entreprise", "Présentation de l'entreprise / fiche de renseignements", F_TECH,
     [r"fiches? (de )?(renseignements?|candidat|contacts?|d'identification|signaletique|entreprise)",
      r"presentation (du candidat|de l'entreprise|de la societe|generale|de la structure|du groupement|de l'operateur|synthetique)",
      r"note de presentation", r"plaquette", r"coordonnees", r"identification du candidat",
      r"dossier de presentation", r"renseignements? (administratifs|concernant|relatifs|sur le candidat|permettant)",
      r"fiches? (du candidat|fournisseur|moyens)", r"description de l'entreprise", r"adresse (mail|electronique|courriel)"]),
    ("capacites_generique", "Renvoi générique aux capacités (aucune pièce nommée)", F_TECH,
     [r"capacites? (du candidat|techniques?|professionnelles?)", r"garanties? (professionnelles?|techniques?)",
      r"r\.? ?2142", r"r\.? ?2143", r"r\.? ?2144", r"aptitude a exercer"]),
    # --- qualifications
    ("qualibat", "Qualibat", F_QUAL, [r"qualibat"]),
    ("rge", "RGE (Reconnu garant de l'environnement)", F_QUAL,
     [r"\brge\b", r"reconnu garant", r"qualipv", r"qualipac", r"qualisol", r"qualibois", r"qualit'?enr", r"eco-?artisan"]),
    ("mase", "MASE", F_QUAL, [r"\bmase\b"]),
    ("iso", "Certification ISO (9001, 14001, 45001…)", F_QUAL,
     [r"\biso[ -]?\d{4,5}", r"\biso\b", r"ohsas"]),
    ("qualifelec", "Qualifelec", F_QUAL, [r"qualifelec"]),
    ("fntp", "Identification professionnelle FNTP / Canalisateurs", F_QUAL,
     [r"\bfntp\b", r"identifications? professionnelles?", r"canalisateurs"]),
    ("opqibi", "OPQIBI / OPQTECC / OPQCM (ingénierie, conseil)", F_QUAL,
     [r"opqibi", r"opqtecc", r"opqcm", r"\bopqu\b", r"\bopqcb\b"]),
    ("amiante", "Certification ou habilitation amiante (SS3 / SS4)", F_QUAL,
     [r"amiante", r"\bss ?[34]\b", r"sous-section [34]", r"desamiantage"]),
    ("habilitations_personnel", "Habilitations du personnel (AIPR, électrique, CACES, SST…)", F_QUAL,
     [r"habilitations?\b(?! du mandataire)(?! du signataire)(?! a signer)", r"\baipr\b", r"caces", r"\bsst\b",
      r"travail en hauteur", r"\bssiap\b", r"haccp", r"attestations? de formation", r"formations? (du|des) (personnel|agents|intervenants)",
      r"carte (btp|d'identification professionnelle)", r"permis", r"\bcqp\b", r"\bfimo\b", r"\bfco\b",
      r"certibiocide", r"certiphyto", r"aptitude medicale", r"sauveteur", r"\bcatec\b", r"fluides frigorigenes",
      r"formation (travaux|a la|adr|radioprotection|'bonnes)", r"plongee", r"attestations? pour trav", r"espace confine",
      r"\badeli\b", r"\brpps\b", r"attestation de supervision", r"attestations? de competences?"]),
    ("certificats_qualification", "Certificats de qualification professionnelle (sans label nommé)", F_QUAL,
     [r"certificats? de qualifications?", r"qualifications? professionnelles?", r"certificats? de qualite",
      r"certificats? (etablis|delivres|emis)", r"organismes? (independants?|certificateurs?)",
      r"preuves? equivalentes?", r"certificats? professionnels?", r"qualifications? (requises|exigees|de l'entreprise|du candidat|ou equivalent)",
      r"moyens? de preuve", r"certifications? (professionnelles?|de l'entreprise|du candidat|detenues|ou equivalent|qualite)",
      r"justificatifs? de qualification", r"qualification ou equivalent", r"niveau de qualification"]),
    ("autorisation_exercer", "Autorisation d'exercer (licence, agrément, carte professionnelle, ordre)", F_QUAL,
     [r"licences?\b", r"agrements?\b", r"cartes? professionnelles?", r"inscription a l'ordre", r"ordre des",
      r"\borias\b", r"registre des transport", r"numero de declaration d'activite", r"\bnda\b",
      r"autorisations? (administrative|prefectorale|d'exploit|d'exercer|d'exercice)", r"recepisse",
      r"qualiopi", r"\bcnaps\b", r"accreditations?", r"cofrac", r"\bhds\b", r"\bicpe\b", r"entreprise adaptee",
      r"\besat\b", r"\bsiae\b", r"structure d'insertion", r"capacite professionnelle", r"mandat de la compagnie",
      r"immatriculation (au|a l')", r"architecte", r"\bapsad\b", r"\bhmonp\b", r"expert-comptable",
      r"marche reserve", r"secret defense", r"habilitation (confidentiel|secret)", r"bilan pedagogique",
      r"autorisation d'(ouverture|etablissement)", r"\bbpf\b", r"\bgmp\b", r"\bansm\b", r"barreau", r"\bavocat\b",
      r"commissaires? aux comptes", r"written confirmation", r"l\.? ?6351", r"autorisation de jeux"]),
    ("labels_divers", "Autres labels et certifications nommés", F_QUAL,
     [r"\blabels?\b", r"certifications?\b", r"certifie", r"\bnf\b", r"marquage ce", r"\bfsc\b", r"\bpefc\b",
      r"ecolabel", r"\bafaq\b", r"\bafnor\b", r"\bcstb\b", r"qualisport", r"qualipaysage", r"\bcerff\b",
      r"normes?\b", r"\bconsuel\b", r"\bemas\b", r"secnumcloud", r"\bitil\b", r"\bsoc ?2\b"]),
    # --- offre
    ("visite", "Attestation / certificat de visite", F_OFFRE,
     [r"visites? (obligatoires?|du site|des lieux|sur site|de site|des sites|sur place|prealable|facultative|conseillee|des locaux|de reconnaissance|du chantier|des installations)",
      r"(attestations?|certificats?|recepisses?|bons?|comptes?[- ]rendus?|justificatifs?) de visite", r"reconnaissance des lieux"]),
    ("ae", "Acte d'engagement (AE, ATTRI1)", F_OFFRE,
     [r"actes? d'engagement", r"\bae\b", r"attri ?1", r"\bdc ?3\b", r"projet de (contrat|marche|convention)",
      r"contrat (de concession|signe|complete)", r"lettre d'engagement", r"cadre d'acte", r"projet d'accord-cadre",
      r"projet de marche"]),
    ("prix", "BPU / DPGF / DQE / pièces de prix", F_OFFRE,
     [r"\bbpu\b", r"\bc?dpgf\b", r"\bdqe\b", r"bordereaux? (de |des |de prix|des prix|unitaire)", r"decomposition (du|des) prix",
      r"detail (quantitatif )?(et )?estimatif", r"detail des prix", r"sous-detail", r"offre (financiere|de prix|tarifaire)",
      r"\bdevis\b", r"annexe financiere", r"proposition financiere", r"cadre (de |des )?(decomposition|prix)",
      r"grille (tarifaire|de prix)", r"\bbp\b", r"\bdpf\b", r"prix (global|forfaitaire|unitaires?)",
      r"tarifs?\b", r"\bdroft\b", r"simulation financiere", r"cadre financier", r"remises?\b", r"decomposition (de la|des) remuneration",
      r"etat des prix", r"compte d'exploitation", r"\bcep\b", r"budget", r"details? estimatifs?", r"taux de",
      r"simulation de commande", r"scenario de commande", r"panier-type", r"commande type", r"facture",
      r"bordereau justificatif", r"remuneration", r"\bdafo\b", r"participation aux benefices"]),
    ("memoire_technique", "Mémoire technique / cadre de réponse", F_OFFRE,
     [r"memoires?\b", r"cadres? de (reponses?|memoire)", r"notes? methodologiques?", r"offre technique",
      r"proposition technique", r"\bcrt\b", r"\bcmt\b", r"notes? techniques?", r"dossier technique",
      r"notices? (techniques?|methodologiques?|explicatives?)", r"methodologie", r"note (de |d')(synthese|intention|organisation|presentation de l'offre|motivation)",
      r"cadre technique", r"questionnaire", r"\bdto\b", r"reponse technique", r"valeur technique", r"descriptif (technique|de l'offre|detaille)",
      r"projet (pedagogique|d'etablissement|de service|educatif|architectural)", r"programme (de formation|pedagogique|detaille)",
      r"dispositions? (que|prises|envisagees|proposees)", r"modalites? (d'execution|de realisation|d'intervention|d'organisation)",
      r"justificatif des dispositions", r"mode operatoire", r"exemples? de (rapport|livrable|compte|consultation)",
      r"dossier de reponse", r"cas pratique", r"note de calcul"]),
    ("planning", "Planning, calendrier, délais", F_OFFRE,
     [r"planning", r"calendrier", r"phasage", r"delais?\b"]),
    ("fiches_techniques", "Fiches techniques, échantillons, documentation produit", F_OFFRE,
     [r"fiches? (techniques?|produits?|descriptives?|de donnees)", r"documentations? (techniques?|commerciale|fournisseur|constructeur)",
      r"echantillons?", r"\bfds\b", r"catalogues?", r"avis techniques?", r"\bpv\b", r"proces-verba",
      r"\bfdes\b", r"notices? (d'utilisation|fabricant|constructeur)", r"prototype", r"specifications? techniques?",
      r"attestation (constructeur|fabricant|du fabricant|du constructeur)", r"photos?\b", r"demonstration", r"garantie (constructeur|fabricant|systeme)",
      r"notices? descriptives?", r"certificats? de provenance", r"reaction au feu"]),
    ("pieces_marche_signees", "Pièces du marché à accepter ou signer (CCAP, CCTP, RC, charte)", F_OFFRE,
     [r"^(le |la |les |l')?(cahiers? des (clauses|charges)|ccap|cctp|ccp|cctc|ccag|reglement de (la )?consultation|rc\b|reglement de service|programme)",
      r"(ccap|cctp|ccp|\brc|reglement de (la )?consultation|cahiers? des (charges|clauses)[^,;(]{0,60})[^,;]{0,60}(sign|accept|paraph|approuv|prise de connaissance)",
      r"acceptation[^,;]{0,40}dossier de consultation", r"\bcharte\b",
      r"pieces? (du marche|contractuelles?|constitutives?) (sign|accept|paraph)",
      r"annexes? (\S+ ){0,2}(au|du|a l') ?(ccap|cctp|ccp|rc\b|reglement)", r"accuse de reception", r"reglement interieur",
      r"^pieces? \d+ ?:"]),
    ("variantes_pse", "Variantes, PSE, options", F_OFFRE,
     [r"variantes?", r"\bpse\b", r"prestations? supplementaires?", r"\boptions?\b", r"tranches? (optionnelle|conditionnelle)"]),
    ("signature_depot", "Signature électronique, copie de sauvegarde, modalités de dépôt", F_OFFRE,
     [r"signature electronique", r"copie de sauvegarde", r"certificat de signature", r"\bxades\b", r"\bpades\b", r"\brgs\b"]),
    # --- engagements et exécution
    ("insertion", "Engagement d'insertion / clause sociale", F_EXEC,
     [r"insertion", r"clauses? sociales?", r"eloigne(e|s)* de l'emploi", r"heures? d'insertion"]),
    ("environnement_dechets", "Environnement, déchets (SOGED, SOSED), RSE", F_EXEC,
     [r"soged", r"sosed", r"dechets", r"environnement", r"\bpae\b", r"\bnre\b", r"carbone", r"gaz a effet",
      r"developpement durable", r"\brse\b", r"beges", r"ecologique", r"chantier (vert|propre|a faibles nuisances)",
      r"reemploi", r"biosource", r"energetique", r"\bre ?2020\b"]),
    ("securite_qualite", "Sécurité et qualité (PPSPS, PAQ, plan de prévention)", F_EXEC,
     [r"ppsps", r"plans? de prevention", r"plans? d'assurance (de la )?(qualite|securite)", r"\bpaq\b", r"\bsopaq\b",
      r"hygiene et (de )?securite", r"plans? (particulier )?de securite", r"livret de securite", r"mesures? de securite",
      r"sante et (de )?securite", r"securite au travail", r"\bpgc(sps)?\b", r"prevention des risques",
      r"document unique d'evaluation", r"\bduerp?\b", r"demarche qualite", r"controle (de (la )?)?qualite", r"\bdoe\b",
      r"\bdiuo\b", r"attestation de securite", r"\bepi\b", r"consignes de securite"]),
    ("acces_site", "Contrôle d'accès au site (liste nominative, pièces d'identité, enquête)", F_EXEC,
     [r"liste nominative", r"pieces? d'identite", r"\bcni\b", r"enquete (de securite|administrative)", r"casier judiciaire",
      r"laissez-passer", r"controle d'acces", r"\bbadge", r"habilitation (defense|d'acces)"]),
    ("donnees_confidentialite", "RGPD, confidentialité, cybersécurité", F_EXEC,
     [r"donnees (a caractere )?personnel", r"rgpd", r"confidentialite", r"cyber", r"securite (si|informatique|des systemes)",
      r"hebergement", r"\bpas\b", r"non-divulgation", r"reversibilite", r"\bsaas\b", r"localisation des donnees"]),
    ("exigence_execution", "Condition d'exécution ou de moyens (délai d'intervention, présence locale, astreinte)", F_EXEC,
     [r"astreinte", r"delai d'intervention", r"presence (permanente|locale|sur site|obligatoire)", r"implantation",
      r"agence (locale|a moins)", r"a moins de \d+ ?(km|minutes|h)", r"lieu d'intervention", r"penalite",
      r"apres (la )?(notification|attribution)", r"suivant la notification",
      r"avant (le |tout |toute )?(demarrage|notification|debut|pose|premiere intervention)",
      r"en cours d'execution", r"a la notification", r"periode de preparation", r"au demarrage",
      r"dans (un delai|les) (de )?\d+ ?(jours|mois|semaines)", r"reprise (du|des) personnels?", r"l\.? ?1224", r"annexe 7",
      r"continuite de service", r"chorus", r"pendant (toute )?(la duree|l'execution)", r"24h/24"]),
]

# Types dont le libellé décrit un document « contenant » : on ne type pas ce qu'il énumère.
CONTENANTS = {"memoire_technique"}
SEPARATEURS_CONTENU = [" : ", " (", " decrivant", " precisant", " comprenant", " incluant", " avec ",
                       " detaillant", " presentant", " indiquant", " structure", " portant sur", " - ", " comportant",
                       " exposant", " justifiant", " explicitant", " abordant", " developpant", " couvrant"]

TYPES_COMPILES = [(c, n, f, [re.compile(m) for m in motifs]) for c, n, f, motifs in TYPES]
NOM_TYPE = {c: n for c, n, _, _ in TYPES}
FAMILLE_TYPE = {c: f for c, _, f, _ in TYPES}
ORDRE_FAMILLES = [F_FORM, F_JUR, F_ASS, F_FIN, F_TECH, F_QUAL, F_OFFRE, F_EXEC, F_DIV]

# Mentions de validité ou d'ancienneté : (motif, rendu)
MOTS_NOMBRES = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "dix": 10, "douze": 12}
NB = r"(\d+|un|une|deux|trois|quatre|cinq|six|dix|douze)"
VALIDITES = [
    (re.compile(r"(?:moins de|< ?|inferieure? a|n'excedant pas|maximum) ?" + NB + r" mois"), "moins de {n} mois"),
    (re.compile(r"(?:tous les|chaque) " + NB + r" mois"), "à renouveler tous les {n} mois"),
    (re.compile(r"en cours de validite|en vigueur|valable"), "en cours de validité"),
    (re.compile(r"\ba jour\b"), "à jour"),
    (re.compile(r"annee en cours|annee civile|31 decembre"), "de l'année en cours (ou au 31 décembre N-1)"),
    (re.compile(r"(?:sur |des |au cours des |pour chacune? des |pendant les )?" + NB + r" dernie(?:re)?s? (?:annees|exercices)"), "{n} dernières années ou exercices"),
    (re.compile(r"sur " + NB + r" ans"), "{n} dernières années ou exercices"),
    (re.compile(r"moins de " + NB + r" ans"), "moins de {n} ans"),
]

# Types pour lesquels une validité ou une ancienneté a un sens (les autres : « sans objet »).
TYPES_DATES = {"kbis", "urssaf", "fiscale", "travail_dissimule", "lnte", "plateforme_attestations", "pouvoir",
               "assurance_rc", "decennale", "ca_bilans", "references", "bonne_execution", "effectifs", "qualibat",
               "rge", "mase", "iso", "qualifelec", "fntp", "opqibi", "amiante", "habilitations_personnel",
               "certificats_qualification", "autorisation_exercer", "labels_divers", "cv_moyens_humains"}

RE_NOM_PERSONNE = re.compile(r"\b(M\.|Mme|MM\.|Monsieur|Madame|Mlle|Dr|Me)\s+((?:[A-ZÉÈÀÂÎÔÛÇ][\w'’\-]+\s?){1,3})")


def normaliser(texte) -> str:
    """Minuscules, sans accents, apostrophes et tirets unifiés, espaces réduits."""
    t = unicodedata.normalize("NFKD", str(texte or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = t.replace("’", "'").replace("`", "'").replace("–", "-").replace("—", "-").replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", t).strip()


def masquer_personnes(texte: str) -> str:
    """Les libellés viennent de DCE publics mais citent parfois un agent de l'acheteur."""
    return RE_NOM_PERSONNE.sub(lambda m: f"{m.group(1)} <nom masqué>", str(texte or ""))


def _nombre(mot: str) -> int:
    return int(mot) if mot.isdigit() else MOTS_NOMBRES.get(mot, 0)


def typer(libelle: str):
    """Retourne (types, validites) : types = liste ordonnée de codes, validites =
    {code_type: [mention, ...]}. Une mention de validité est rattachée au type
    dont le motif est le plus proche dans le libellé."""
    t = normaliser(libelle)
    positions = {}                                   # code -> position du premier motif trouvé
    for code, _, _, motifs in TYPES_COMPILES:
        for motif in motifs:
            m = motif.search(t)
            if m:
                positions[code] = m.start()
                break
    # Document contenant en tête de libellé : on ignore ce qu'il énumère ensuite.
    for code in CONTENANTS:
        if code in positions and positions[code] <= 50:
            debut = positions[code]
            coupes = [t.find(s, debut) for s in SEPARATEURS_CONTENU]
            coupes = [c for c in coupes if c > debut]
            if coupes:
                limite = min(coupes)
                positions = {c: p for c, p in positions.items() if p < limite or c in CONTENANTS}
    validites = defaultdict(list)
    if positions:
        for motif, rendu in VALIDITES:
            for m in motif.finditer(t):
                n = _nombre(m.group(1)) if m.groups() else 0
                proche = min(positions, key=lambda c: (abs(positions[c] - m.start()), positions[c]))
                if proche in TYPES_DATES:
                    validites[proche].append(rendu.format(n=n))
    return sorted(positions, key=positions.get), dict(validites)


# ---------------------------------------------------------------------------
# Lecture des briefs
# ---------------------------------------------------------------------------
def briefs_courants() -> dict:
    tous = stockage.charger("briefs_extraits")
    return {i: b for i, b in tous.items() if RE_ID_COURANT.match(i) and isinstance(b, dict)}


def est_btp(brief: dict) -> bool:
    meta = brief.get("_meta") or {}
    if meta.get("preset_utilise") == "btp":
        return True
    return any(isinstance(d, dict) and str(d.get("code", "")).startswith("btp")
               for d in brief.get("domaines_metier") or [])


def _codes_qualibat(*textes) -> list:
    codes = []
    for texte in textes:
        for bloc in re.finditer(r"qualibat((?:[^\d]{0,45}\d{4}\b)+)", normaliser(texte)):
            codes += re.findall(r"\b(\d{4})\b", bloc.group(1))
    return [c for c in codes if not c.startswith(("19", "20"))]     # écarte les années


def occurrences(brief: dict):
    """Génère les exigences d'un brief sous forme de dicts homogènes."""
    def occ(source, libelle, **k):
        base = {"source": source, "libelle": str(libelle or "").strip(), "phase": "", "obligatoire": "",
                "bloquante": "", "codes": [], "types_forces": None, "contexte": ""}
        base.update(k)
        return base

    dossier = brief.get("dossier_candidature") or {}
    for p in dossier.get("pieces_a_fournir") or []:
        if isinstance(p, dict) and p.get("libelle"):
            yield occ("P", p["libelle"], phase=p.get("phase") or "", obligatoire=p.get("obligatoire"))
        elif isinstance(p, str) and p.strip():
            yield occ("P", p)

    refs = brief.get("references_exigees") or {}
    for c in refs.get("certifications_obligatoires") or []:
        if isinstance(c, dict) and c.get("libelle"):
            yield occ("C", c["libelle"], bloquante=c.get("bloquante"), codes=[str(x) for x in c.get("codes") or []])
        elif isinstance(c, str) and c.strip():
            yield occ("C", c)
    for a in refs.get("autres_exigences") or []:
        libelle = a.get("libelle") if isinstance(a, dict) else a
        if libelle and str(libelle).strip():
            yield occ("A", libelle)
    if refs.get("experience_minimale_annees") not in (None, "", 0) or refs.get("volume_min_references_similaires") not in (None, "", 0):
        yield occ("S", "Références exigées (champ structuré)", types_forces=["references"])

    for cle, bloc in brief.items():
        if not cle.startswith("qualifications_") or not isinstance(bloc, dict):
            continue
        for champ, valeur in bloc.items():
            if champ == "description":
                continue
            if champ == "qualibat":
                codes = re.findall(r"\b\d{4}\b", " ".join(map(str, valeur)) if isinstance(valeur, list) else str(valeur or ""))
                if codes:
                    yield occ("S", "Qualibat " + ", ".join(codes), codes=codes, types_forces=["qualibat"])
            elif valeur is True:
                yield occ("S", champ.replace("_", " "))        # typé par le nom du champ (rge, mase, iso 9001…)
            elif isinstance(valeur, list):
                for v in valeur:
                    if isinstance(v, str) and v.strip():
                        yield occ("Q", v, contexte="" if champ.startswith("autre") else champ)
            elif isinstance(valeur, str) and valeur.strip() and valeur.strip().lower() not in ("false", "true", "null", "non", "aucune", "aucun"):
                yield occ("Q", valeur)


# ---------------------------------------------------------------------------
# Seuils chiffrés : CA minimum, effectif minimum, nombre de références
# ---------------------------------------------------------------------------
RE_MONTANT = re.compile(r"(\d{1,3}(?:[ .]\d{3})+|\d+(?:[.,]\d+)?) ?(m€|millions?|k€|keur|€|euros?|eur\b)")
RE_SEUIL = re.compile(r"minim|au moins|≥|>=|superieur|egal|plancher|seuil|\bniveau\b")
RE_RATIO = re.compile(r"(\d+(?:[.,]\d+)?) ?(?:x|×|fois) ?(?:le |au )?(?:montant|l'estimation|la valeur)")
TRANCHES_CA = [(100_000, "moins de 100 k€"), (500_000, "100 à 500 k€"), (1_000_000, "500 k€ à 1 M€"),
               (5_000_000, "1 à 5 M€"), (float("inf"), "plus de 5 M€")]


def ca_minimum(libelle: str):
    """Montants de CA minimum cités dans un libellé (liste d'euros), et ratio éventuel."""
    t = normaliser(libelle)
    if not re.search(r"chiffres? d'affaires?|\bca\b", t) or not RE_SEUIL.search(t):
        return [], None
    montants = []
    for m in RE_MONTANT.finditer(t):
        brut = m.group(1).replace(" ", "")
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", brut):
            brut = brut.replace(".", "")
        valeur = float(brut.replace(",", "."))
        unite = m.group(2)
        if unite.startswith("m"):
            valeur *= 1_000_000
        elif unite.startswith("k"):
            valeur *= 1_000
        if valeur >= 1_000:
            montants.append(valeur)
    ratio = RE_RATIO.search(t)
    return montants, (float(ratio.group(1).replace(",", ".")) if ratio else None)


def nb_references(libelle: str):
    t = normaliser(libelle)
    m = re.search(r"(?:au moins|minimum(?: de)?|au minimum|≥|>=) ?" + NB + r" (?:references?|chantiers|operations|realisations|marches|prestations|missions)", t) \
        or re.search(r"\b" + NB + r" references?\b", t)
    return _nombre(m.group(1)) if m else None


def periode_references(libelle: str):
    t = normaliser(libelle)
    m = re.search(NB + r" dernie(?:re)?s? annees", t) or re.search(r"(?:moins de|sur) " + NB + r" ans", t)
    return _nombre(m.group(1)) if m else None


def effectif_minimum(libelle: str):
    t = normaliser(libelle)
    if "effectif" not in t or not re.search(r"minim|au moins|≥|>=", t):
        return None
    m = re.search(r"(\d+) ?(?:agents|personnes|salaries|etp|compagnons|ouvriers)", t)
    return int(m.group(1)) if m else 0


# ---------------------------------------------------------------------------
# Agrégation
# ---------------------------------------------------------------------------
def analyser(briefs: dict) -> dict:
    lignes = []                                       # une ligne par occurrence
    par_type = defaultdict(lambda: {"marches": set(), "btp": set(), "autres": set(), "phase_cand": set(),
                                    "phase_offre": set(), "phase_nc": set(), "oblig": Counter(), "bloq": Counter(),
                                    "validites": Counter(), "exemples": Counter(), "occ": 0})
    non_reconnus = Counter()
    exemples_non_reconnus = {}
    qualibat = defaultdict(lambda: {"marches": set(), "exemple": ""})
    iso = Counter()
    ca_min, ca_ratios, refs_nb, refs_periode, experience, effectifs_min = [], [], [], Counter(), Counter(), []
    secteurs = {}
    base = set()                                      # briefs portant au moins une exigence

    for id_marche, brief in briefs.items():
        btp = est_btp(brief)
        secteurs[id_marche] = btp
        r = brief.get("references_exigees") or {}
        if isinstance(r.get("experience_minimale_annees"), (int, float)) and r["experience_minimale_annees"]:
            experience[int(r["experience_minimale_annees"])] += 1
        if isinstance(r.get("volume_min_references_similaires"), (int, float)) and r["volume_min_references_similaires"]:
            refs_nb.append((id_marche, int(r["volume_min_references_similaires"]), "champ structuré"))
        periodes_marche, nb_marche = set(), set()

        for o in occurrences(brief):
            base.add(id_marche)
            if o["types_forces"] is not None:
                types, validites = o["types_forces"], {}
            else:
                types, validites = typer(o["libelle"])
                if not types and o["contexte"]:          # code seul dans une liste nommée (opqibi : « 0902 »)
                    types, validites = typer(o["contexte"] + " " + o["libelle"])
            if o["source"] == "S" and not types:
                types = ["labels_divers"]
            # Codes Qualibat : champ codes d'une certification citant Qualibat, ou codes dans le libellé
            if "qualibat" in types:
                codes = [c for c in o["codes"] if re.fullmatch(r"\d{4}", c)] or _codes_qualibat(o["libelle"])
                for c in codes:
                    qualibat[c]["marches"].add(id_marche)
                    if o["source"] != "S" and not qualibat[c]["exemple"]:
                        qualibat[c]["exemple"] = o["libelle"]
            if "iso" in types:
                for n in re.findall(r"iso[ _-]?(\d{4,5})", normaliser(o["libelle"])) or ["non précisée"]:
                    iso[(n, id_marche)] += 1
            montants, ratio = ca_minimum(o["libelle"])
            for m in montants:
                ca_min.append((id_marche, m, o["libelle"]))
            if ratio:
                ca_ratios.append((id_marche, ratio, o["libelle"]))
            if "references" in types and o["source"] != "S":
                n = nb_references(o["libelle"])
                if n and n not in nb_marche:
                    nb_marche.add(n)
                    refs_nb.append((id_marche, n, o["libelle"]))
                p = periode_references(o["libelle"])
                if p:
                    periodes_marche.add(p)
            e = effectif_minimum(o["libelle"])
            if e is not None:
                effectifs_min.append((id_marche, e, o["libelle"]))

            mentions = sorted({v for vs in validites.values() for v in vs})
            lignes.append({"id_marche": id_marche, "secteur": "btp" if btp else "autre", "source": o["source"],
                           "phase": o["phase"], "obligatoire": o["obligatoire"], "bloquante": o["bloquante"],
                           "libelle": masquer_personnes(o["libelle"]), "types": "|".join(types),
                           "validite": "|".join(mentions)})
            if not types:
                cle = normaliser(o["libelle"])
                non_reconnus[cle] += 1
                exemples_non_reconnus.setdefault(cle, masquer_personnes(o["libelle"]))
            for t in types:
                a = par_type[t]
                a["occ"] += 1
                a["marches"].add(id_marche)
                a["btp" if btp else "autres"].add(id_marche)
                if o["source"] == "P":
                    cle_phase = {"candidature": "phase_cand", "offre": "phase_offre"}.get(o["phase"], "phase_nc")
                    a[cle_phase].add(id_marche)
                    a["oblig"][str(o["obligatoire"])] += 1
                else:
                    a["phase_nc"].add(id_marche)
                if o["source"] == "C":
                    a["bloq"][str(o["bloquante"])] += 1
                for v in validites.get(t, []):
                    a["validites"][v] += 1
                if o["source"] != "S":
                    a["exemples"][masquer_personnes(o["libelle"])] += 1
        for p in periodes_marche:
            refs_periode[p] += 1

    libres = [l for l in lignes if l["source"] != "S"]
    return {"lignes": lignes, "par_type": par_type, "non_reconnus": non_reconnus,
            "exemples_non_reconnus": exemples_non_reconnus, "qualibat": qualibat, "iso": iso,
            "ca_min": ca_min, "ca_ratios": ca_ratios, "refs_nb": refs_nb, "refs_periode": refs_periode,
            "experience": experience, "effectifs_min": effectifs_min, "secteurs": secteurs, "base": base,
            "nb_libres": len(libres), "nb_types": sum(1 for l in libres if l["types"])}


def marches_btp_actifs():
    """Nombre de marchés actifs classés BTP (pour projeter « débloque N marchés »)."""
    from tendia.core import etat_marche
    marches = stockage.charger("marches")
    classes = stockage.charger("classifications_ia")
    actifs = [i for i, m in marches.items() if isinstance(m, dict) and etat_marche.est_actif(m)]
    btp = [i for i in actifs
           if any(isinstance(d, dict) and str(d.get("code", "")).startswith("btp")
                  for d in (classes.get(i) or {}).get("domaines_metier") or [])]
    return len(actifs), btp


# ---------------------------------------------------------------------------
# Rendu
# ---------------------------------------------------------------------------
def pct(n: int, total: int) -> str:
    return f"{100 * n / total:.0f} %" if total else "n/a"


def _cellule(texte: str, maxi: int = 110) -> str:
    t = str(texte).replace("|", "/").replace("\n", " ").strip()
    return t if len(t) <= maxi else t[: maxi - 1].rstrip() + "…"


def ecrire_sorties(res: dict, briefs: dict, sortie: Path, projection) -> dict:
    sortie.mkdir(parents=True, exist_ok=True)
    base = res["base"]
    n_base = len(base)
    n_btp = sum(1 for i in base if res["secteurs"][i])
    n_autres = n_base - n_btp
    nb_actifs, actifs_btp = projection if projection else (0, [])
    actifs_btp_briefes = [i for i in actifs_btp if i in base]
    taux = res["nb_types"] / res["nb_libres"] if res["nb_libres"] else 0
    types_tries = sorted(res["par_type"], key=lambda t: (-len(res["par_type"][t]["btp"]), -len(res["par_type"][t]["marches"])))

    # --- CSV par type
    with open(sortie / "exigences_types.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["type", "nom", "famille", "occurrences", "marches_tous", "pct_tous", "marches_btp", "pct_btp",
                    "marches_autres", "pct_autres", "marches_phase_candidature", "marches_phase_offre",
                    "marches_phase_non_precisee", "pieces_obligatoires", "pieces_facultatives",
                    "certifs_bloquantes", "certifs_non_bloquantes", "validites", "marches_btp_actifs_estimes",
                    "marches_btp_actifs_briefes"])
        for t in types_tries:
            a = res["par_type"][t]
            w.writerow([t, NOM_TYPE[t], FAMILLE_TYPE[t], a["occ"], len(a["marches"]), round(100 * len(a["marches"]) / n_base, 1),
                        len(a["btp"]), round(100 * len(a["btp"]) / n_btp, 1) if n_btp else "",
                        len(a["autres"]), round(100 * len(a["autres"]) / n_autres, 1) if n_autres else "",
                        len(a["phase_cand"]), len(a["phase_offre"]), len(a["phase_nc"]),
                        a["oblig"]["True"], a["oblig"]["False"], a["bloq"]["True"], a["bloq"]["False"],
                        " ; ".join(f"{v} ({n})" for v, n in a["validites"].most_common(4)),
                        round(len(a["btp"]) / n_btp * len(actifs_btp)) if n_btp and actifs_btp else "",
                        sum(1 for i in actifs_btp_briefes if i in a["marches"]) if actifs_btp else ""])

    # --- CSV brut des occurrences
    with open(sortie / "exigences_occurrences.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, delimiter=";", fieldnames=["id_marche", "secteur", "source", "phase", "obligatoire",
                                                         "bloquante", "types", "validite", "libelle"])
        w.writeheader()
        w.writerows(res["lignes"])

    # --- CSV des non reconnus
    with open(sortie / "exigences_non_reconnus.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["occurrences", "libelle"])
        for cle, n in res["non_reconnus"].most_common():
            w.writerow([n, res["exemples_non_reconnus"][cle]])

    # --- Markdown
    L = []
    dates = sorted(str((b.get("_meta") or {}).get("date_generation") or "")[:7] for b in briefs.values())
    par_mois = Counter(d or "sans date" for d in dates)
    L += ["# Fréquence des pièces et exigences demandées aux candidats", "",
          f"Produit par `scripts/audit/analyse_exigences.py` le {datetime.now():%Y-%m-%d à %H:%M} (lecture seule, sans LLM, sans réseau). "
          "Relancer le script régénère ce fichier et les CSV voisins.", "",
          "## Base de mesure", "",
          "| Mesure | Valeur |", "|---|---|",
          f"| Briefs courants dans `briefs_extraits` (sauvegardes `.bak_*` et `.grille_brute` exclues) | {len(briefs)} |",
          f"| Briefs portant au moins une exigence (base des pourcentages) | {n_base} |",
          f"| dont BTP (preset `btp` ou domaine `btp_*`) | {n_btp} |",
          f"| dont autres secteurs | {n_autres} |",
          f"| Mois de génération des briefs | {', '.join(f'{m} : {n}' for m, n in sorted(par_mois.items()))} |",
          f"| Libellés libres analysés (sources P, C, A, Q) | {res['nb_libres']} |",
          f"| Libellés rangés dans au moins un type | {res['nb_types']} ({100 * taux:.1f} %) |",
          f"| Libellés non reconnus | {res['nb_libres'] - res['nb_types']} ({len(res['non_reconnus'])} libellés distincts) |",
          f"| Marchés actifs en base / dont classés BTP | {nb_actifs} / {len(actifs_btp)} |" if projection else "| Marchés actifs | non calculé (`--sans-projection`) |",
          f"| Marchés BTP actifs disposant d'un brief | {len(actifs_btp_briefes)} |" if projection else "| | |",
          "", "Sources : P = `dossier_candidature.pieces_a_fournir`, C = `references_exigees.certifications_obligatoires`, "
          "A = `references_exigees.autres_exigences`, Q = listes des blocs `qualifications_*`, "
          "S = champs structurés (codes Qualibat, booléens, expérience), exclus du taux de typage.", "",
          "### Limites à garder en tête", "",
          "- Les libellés sont ceux rédigés par le LLM d'extraction, pas le texte du règlement de consultation. Deux briefs disent la même chose avec des mots différents ; le dictionnaire de motifs absorbe ces variantes.",
          "- La plupart des briefs datent de juin 2026 (lecture partielle du DCE : pièces de premier niveau, troncature à 400 000 caractères). Une pièce absente du brief n'est pas forcément absente du DCE : les pourcentages sont des planchers.",
          "- Un libellé peut porter plusieurs types (« DC2 avec Kbis de moins de 3 mois et pouvoirs » compte pour DC2, Kbis et pouvoir). Un mémoire technique qui énumère son contenu ne compte que pour le mémoire.",
          "- Le DUME et le couple DC1 + DC2 sont interchangeables : un marché qui cite « DC1 ou DUME » compte dans les deux lignes.",
          "- La phase vient du champ `phase` des pièces (source P) ; les exigences des sources C, A, Q n'ont pas de phase.",
          f"- La colonne « marchés BTP actifs (estimation) » applique le pourcentage BTP aux {len(actifs_btp)} marchés BTP actifs du jour ; seuls {len(actifs_btp_briefes)} d'entre eux ont un brief, le chiffre exact n'est donc pas mesurable aujourd'hui." if projection else "",
          ""]

    L += ["## Fréquence par type", "",
          "Pourcentages = part des marchés de la colonne qui portent au moins une exigence du type. Trié par fréquence BTP.", "",
          f"| Type | Tous ({n_base}) | BTP ({n_btp}) | Autres ({n_autres}) | Phase (marchés : candidature / offre / non précisée) | Obligatoire (pièces : oui / non) | Validité ou ancienneté exigée | Marchés BTP actifs (estimation) |",
          "|---|---|---|---|---|---|---|---|"]
    for t in types_tries:
        a = res["par_type"][t]
        validites = "sans objet"
        if t in TYPES_DATES:
            validites = " ; ".join(f"{v} ({n})" for v, n in a["validites"].most_common(3)) or "non précisée"
        estime = round(len(a["btp"]) / n_btp * len(actifs_btp)) if n_btp and actifs_btp else "n/a"
        L.append(f"| {NOM_TYPE[t]} | {pct(len(a['marches']), n_base)} ({len(a['marches'])}) | {pct(len(a['btp']), n_btp)} ({len(a['btp'])}) | "
                 f"{pct(len(a['autres']), n_autres)} ({len(a['autres'])}) | {len(a['phase_cand'])} / {len(a['phase_offre'])} / {len(a['phase_nc'])} | "
                 f"{a['oblig']['True']} / {a['oblig']['False']} | {validites} | {estime} |")
    L.append("")

    L += ["## Détail par type : exemples de libellés", ""]
    for famille in ORDRE_FAMILLES:
        membres = [t for t in types_tries if FAMILLE_TYPE[t] == famille]
        if not membres:
            continue
        L += [f"### {famille}", "", "| Type | Code | Occurrences | Certifications bloquantes (oui / non) | Exemples de libellés |", "|---|---|---|---|---|"]
        for t in membres:
            a = res["par_type"][t]
            exemples = " ; ".join(f"« {_cellule(e)} »" for e, _ in a["exemples"].most_common(3))
            L.append(f"| {NOM_TYPE[t]} | `{t}` | {a['occ']} | {a['bloq']['True']} / {a['bloq']['False']} | {exemples} |")
        L.append("")

    # Couverture cumulée des pièces de candidature BTP (base du « minimum vital »)
    cand = [set(l["types"].split("|")) - {""} for l in res["lignes"]
            if l["secteur"] == "btp" and l["source"] == "P" and l["phase"] == "candidature"]
    L += ["## Couverture cumulée des pièces de candidature BTP", "",
          f"Base : {len(cand)} pièces de phase candidature dans les {n_btp} briefs BTP. Une pièce est couverte quand tous ses "
          "types sont dans la liste. À chaque rang, le type ajouté est celui qui couvre le plus de pièces supplémentaires.", "",
          "| Rang | Type ajouté | Pièces couvertes (cumul) | Part cumulée |", "|---|---|---|---|"]
    choisis, couverture = set(), []
    candidats = {t for ts in cand for t in ts}
    while candidats:
        meilleur = max(sorted(candidats), key=lambda t: (sum(1 for ts in cand if ts and ts <= choisis | {t}),
                                                         sum(1 for ts in cand if t in ts and not ts <= choisis)))
        choisis.add(meilleur)
        candidats.discard(meilleur)
        couvert = sum(1 for ts in cand if ts and ts <= choisis)
        couverture.append((meilleur, couvert))
        L.append(f"| {len(couverture)} | {NOM_TYPE[meilleur]} | {couvert} | {pct(couvert, len(cand))} |")
        if couvert >= 0.95 * len(cand):
            break
    L.append("")
    with open(sortie / "exigences_couverture_candidature_btp.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["rang", "type", "nom", "pieces_couvertes_cumul", "pct_cumul"])
        for rang, (t, couvert) in enumerate(couverture, 1):
            w.writerow([rang, t, NOM_TYPE[t], couvert, round(100 * couvert / len(cand), 1) if cand else ""])

    # Qualibat
    q = sorted(res["qualibat"].items(), key=lambda kv: (-len(kv[1]["marches"]), kv[0]))
    marches_qualibat = res["par_type"]["qualibat"]["marches"] if "qualibat" in res["par_type"] else set()
    L += ["## Codes Qualibat", "",
          f"{len(marches_qualibat)} marchés citent Qualibat, {len({m for _, v in q for m in v['marches']})} avec au moins un code à 4 chiffres, "
          f"{len(q)} codes distincts. Liste limitée aux 30 premiers.", "",
          "| Code | Marchés | Exemple de libellé |", "|---|---|---|"]
    for code, v in q[:30]:
        L.append(f"| {code} | {len(v['marches'])} | {_cellule(masquer_personnes(v['exemple']), 140) or 'champ `qualifications_requises.qualibat`'} |")
    L.append("")

    # RGE, MASE, ISO
    L += ["## RGE, MASE, ISO", "", "| Certification | Marchés tous | Marchés BTP | Part des marchés BTP |", "|---|---|---|---|"]
    for t in ("qualibat", "rge", "mase", "iso", "qualifelec", "fntp", "amiante", "habilitations_personnel"):
        a = res["par_type"].get(t) or {"marches": set(), "btp": set()}
        if a is not None:
            L.append(f"| {NOM_TYPE[t]} | {len(a['marches'])} | {len(a['btp'])} | {pct(len(a['btp']), n_btp)} |")
    normes = Counter(n for (n, _m) in res["iso"])
    L += ["", "Normes ISO citées (en marchés) : " + (", ".join(f"ISO {n} : {c}" for n, c in normes.most_common()) or "aucune") + ".", ""]

    # CA minimum
    par_marche = defaultdict(list)
    for i, m, _ in res["ca_min"]:
        par_marche[i].append(m)
    tranches = Counter()
    for i, ms in par_marche.items():
        plus_bas = min(ms)
        tranches[next(nom for borne, nom in TRANCHES_CA if plus_bas < borne)] += 1
    ca_declares = res["par_type"]["ca_bilans"]["marches"] if "ca_bilans" in res["par_type"] else set()
    L += ["## Chiffre d'affaires minimum", "",
          f"{len(ca_declares)} marchés ({pct(len(ca_declares), n_base)}) demandent le chiffre d'affaires ou les bilans ; "
          f"{len(par_marche)} seulement ({pct(len(par_marche), n_base)}) fixent un seuil chiffré, "
          f"dont {sum(1 for i in par_marche if res['secteurs'][i])} en BTP. "
          f"Marchés exprimant aussi le seuil en multiple du montant du marché : {len({i for i, _, _ in res['ca_ratios']})}.", "",
          "| Seuil le plus bas cité par le marché | Marchés |", "|---|---|"]
    for _, nom in TRANCHES_CA:
        L.append(f"| {nom} | {tranches[nom]} |")
    L += ["", "| Marché | Secteur | Seuils cités (€) | Libellé |", "|---|---|---|---|"]
    vus = set()
    for i, m, lib in sorted(res["ca_min"], key=lambda x: x[1]):
        if (i, lib) in vus:
            continue
        vus.add((i, lib))
        seuils = ", ".join(f"{int(x):,}".replace(",", " ") for x in sorted({mm for ii, mm, ll in res["ca_min"] if ii == i and ll == lib}))
        L.append(f"| {i} | {'BTP' if res['secteurs'][i] else 'autre'} | {seuils} | {_cellule(masquer_personnes(lib), 160)} |")
    L.append("")

    # Références
    nb_par_marche = {}
    for i, n, _ in res["refs_nb"]:
        nb_par_marche[i] = min(n, nb_par_marche.get(i, n))
    dist = Counter(nb_par_marche.values())
    refs = res["par_type"]["references"]["marches"] if "references" in res["par_type"] else set()
    L += ["## Références demandées", "",
          f"{len(refs)} marchés ({pct(len(refs), n_base)}) demandent des références ; {len(nb_par_marche)} en fixent le nombre minimum.", "",
          "| Nombre minimum de références | Marchés |", "|---|---|"]
    L += [f"| {n} | {c} |" for n, c in sorted(dist.items())]
    L += ["", "| Période couverte par les références (libellés) | Marchés |", "|---|---|"]
    L += [f"| {n} dernières années | {c} |" for n, c in sorted(res["refs_periode"].items())]
    L += ["", "| Champ `experience_minimale_annees` | Marchés |", "|---|---|"]
    L += [f"| {n} ans | {c} |" for n, c in sorted(res["experience"].items())]
    L += ["", "Le champ `experience_minimale_annees` reprend le plus souvent la période des références (« 5 dernières années »), pas une ancienneté de l'entreprise.", ""]

    # Effectifs
    eff = res["par_type"]["effectifs"]["marches"] if "effectifs" in res["par_type"] else set()
    L += ["## Effectifs", "",
          f"{len(eff)} marchés ({pct(len(eff), n_base)}) demandent une déclaration d'effectifs ; "
          f"{len({i for i, _, _ in res['effectifs_min']})} fixent un effectif minimum.", "",
          "| Marché | Secteur | Effectif minimum lu | Libellé |", "|---|---|---|---|"]
    for i, e, lib in res["effectifs_min"]:
        L.append(f"| {i} | {'BTP' if res['secteurs'][i] else 'autre'} | {e or 'non chiffré'} | {_cellule(masquer_personnes(lib), 160)} |")
    L.append("")

    # Non reconnus
    L += ["## Libellés non reconnus (100 plus fréquents)", "",
          f"{res['nb_libres'] - res['nb_types']} occurrences sur {res['nb_libres']} ({100 * (1 - taux):.1f} %). Liste complète : `exigences_non_reconnus.csv`.", "",
          "| Occurrences | Libellé |", "|---|---|"]
    for cle, n in res["non_reconnus"].most_common(100):
        L.append(f"| {n} | {_cellule(res['exemples_non_reconnus'][cle], 200)} |")
    L.append("")

    (sortie / "exigences_frequence.md").write_text("\n".join(L), encoding="utf-8")
    return {"taux": taux, "n_base": n_base, "n_btp": n_btp, "actifs_btp": len(actifs_btp)}


def main() -> int:
    parseur = argparse.ArgumentParser(description="Fréquence des pièces et exigences demandées (lecture seule).")
    parseur.add_argument("--sortie", type=Path, default=SORTIE_DEFAUT, help="dossier de sortie (défaut : docs/analyse_profil)")
    parseur.add_argument("--sans-projection", action="store_true", help="ne charge pas la collection marches (58 Mo)")
    args = parseur.parse_args()

    briefs = briefs_courants()
    res = analyser(briefs)
    projection = None if args.sans_projection else marches_btp_actifs()
    bilan = ecrire_sorties(res, briefs, args.sortie, projection)
    print(f"Briefs courants : {len(briefs)} ; base : {bilan['n_base']} (BTP {bilan['n_btp']})")
    print(f"Libellés libres : {res['nb_libres']} ; typés : {res['nb_types']} ({100 * bilan['taux']:.1f} %)")
    print(f"Non reconnus : {len(res['non_reconnus'])} libellés distincts")
    print(f"Marchés BTP actifs : {bilan['actifs_btp']}")
    print(f"Sorties : {args.sortie}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
