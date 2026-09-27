# -*- coding: utf-8 -*-
"""Contenu pédagogique de la fenêtre « Création du navire ».

Ce module ne contient que du TEXTE : l'énoncé de chaque étape, ce qu'elle
sert, ce qu'il faut avoir sous la main, la marche à suivre et le format
attendu des données. Il est volontairement séparé du code de l'interface
pour pouvoir être relu et corrigé sans toucher à la fenêtre.

Les champs `statut` et `etat` ne servent plus qu'en secours : la fenêtre
affiche désormais l'état réel, déduit des données présentes dans le navire
(voir `carene.core.navire_draft.NavireDraft.status`).
"""
from __future__ import annotations

# ---------------------------------------------------------------- sections
# `mini` : l'étape fait-elle partie du minimum nécessaire pour calculer ?
SECTIONS = [
    ("ESSENTIEL", "Essentiel", "Indispensable pour calculer une stabilité.", True),
    ("COMPART", "Compartimentage",
     "Soutes, ballasts et ouvertures. Nécessaire dès qu'on embarque des "
     "liquides ou qu'on vérifie l'envahissement.", False),
    ("PLANS", "Plans du navire",
     "Facultatif : sert uniquement à placer et visualiser le chargement "
     "graphiquement. Le calcul fonctionne sans.", False),
    ("VERIF", "Vérification", "Contrôle et enregistrement du navire.", False),
]

CONVENTIONS = {
    "key": "conventions",
    "titre": "Conventions et repères",
    "section": None,
    "statut": "info",
    "resume": "À lire avant tout import. C'est la première source d'erreur.",
    "a_quoi": (
        "Toutes les positions saisies dans ce logiciel doivent être exprimées "
        "dans le même repère, sinon les calculs seront faux sans qu'aucun "
        "message d'erreur n'apparaisse. Cette page est la référence : elle ne "
        "demande aucune saisie, gardez-la sous la main pendant les imports."
    ),
    "il_faut": [],
    "comment": [],
    "format_intro": ("Le repère du navire, tel qu'utilisé partout dans le "
                     "logiciel (exemples : valeurs d'un navire d'exemple) :"),
    "format_rows": [
        ("X — abscisse", "m depuis l'origine des abscisses du dossier "
         "(par exemple le couple 0)", "positif vers l'avant", "30.60"),
        ("Y — ordonnée", "m depuis le plan de symétrie (ligne de foi)",
         "positif vers BÂBORD", "3.767"),
        ("Z — hauteur", "m au-dessus de la ligne de base (quille)",
         "positif vers le haut", "6.39"),
        ("Assiette", "m", "positive sur l'arrière (apparent aft)", "+0.500"),
        ("Gîte", "degrés", "positive sur bâbord", "15"),
    ],
    "notes": [
        "Le logiciel ne connaît pas l'origine de vos abscisses : il prend "
        "toutes les valeurs telles quelles. Peu importe laquelle vous "
        "choisissez — perpendiculaire arrière, couple 0, milieu du navire — "
        "pourvu que TOUTES les données du navire partent de la même. Si une "
        "table de votre dossier compte autrement, convertissez-la AVANT de "
        "l'importer.",
        "La convention « Y positif bâbord » est celle du logiciel. "
        "Un TCG de signe inverse fait pencher le navire du mauvais côté.",
        "Les hauteurs (VCG, KM, KN) se comptent depuis la QUILLE, pas depuis "
        "la flottaison.",
    ],
}

# ---------------------------------------------------------------- étapes
STEPS = [
    # ============================================================ ESSENTIEL
    {
        "key": "classeur",
        "titre": "Par où commencer : le classeur à remplir",
        "section": "ESSENTIEL",
        "statut": "info",
        "resume": "Un seul fichier à remplir, un seul import. Le chemin court.",
        "a_quoi": (
            "Reprendre un dossier de stabilité demande de recopier une dizaine "
            "de tables. Plutôt que de les fabriquer une par une en devinant "
            "les intitulés de colonnes, créez ici le CLASSEUR TYPE : un "
            "fichier Excel où chaque table a sa feuille, ses colonnes déjà "
            "nommées, et une explication sur chaque intitulé (survolez-le) — "
            "unité, repère, obligatoire ou non, et une valeur d'exemple. "
            "Vous le remplissez tranquillement, à terre ou à "
            "bord, éventuellement à plusieurs ; puis vous l'importez ici en "
            "une fois. Chaque étape suivante montre alors ce qui a été lu."
        ),
        "il_faut": [
            "Le dossier de stabilité approuvé, papier ou PDF.",
            "Un tableur (Excel, LibreOffice). À défaut, les gabarits CSV "
            "rendent le même service, un fichier par table.",
        ],
        "comment": [
            "Cliquez « Créer le classeur type à remplir… » et rangez le "
            "fichier proposé où vous voulez.",
            "Ouvrez-le, lisez la feuille « Lisez-moi », puis remplissez "
            "feuille par feuille. Ce que votre dossier ne donne pas reste "
            "vide : une feuille vide est simplement ignorée.",
            "Pour les jaugeages, dupliquez la feuille « Jauge_EXEMPLE » une "
            "fois par capacité et renommez-la « Jauge_<NOM DE LA CAPACITÉ> ».",
            "Revenez ici et cliquez « Importer un classeur rempli… ». Le "
            "compte rendu dit, feuille par feuille, ce qui a été lu et ce qui "
            "a été ignoré.",
            "Vous pouvez réimporter le même classeur autant de fois que vous "
            "le complétez : chaque import remplace ce qu'il apporte.",
        ],
        "format_intro": "Les feuilles du classeur, dans l'ordre :",
        "format_rows": [
            ("Lisez-moi", "texte", "—", "conventions X / Y / Z, mode d'emploi"),
            ("Identification", "champ / valeur", "oui",
             "nom, dimensions principales"),
            ("Lege", "champ / valeur", "oui", "masse, LCG, VCG, TCG"),
            ("Vent", "champ / valeur", "facultatif",
             "surface au vent de référence"),
            ("Couples", "n, x_m", "facultatif", "table d'espacement"),
            ("Hydrostatiques", "table", "oui",
             "toutes assiettes, colonne Assiette_m"),
            ("Pantocarenes_KN", "table", "oui", "une colonne par angle"),
            ("Capacites", "table", "recommandé", "liste des capacités"),
            ("Jauge_<CAPACITÉ>", "table", "recommandé",
             "une feuille par capacité, à dupliquer"),
            ("Envahissement", "table", "recommandé", "ouvertures et cotes"),
            ("Cas_de_reference", "table", "recommandé",
             "cas du dossier + résultats"),
        ],
        "notes": [
            "Le classeur n'est pas un passage obligé : chaque étape reste "
            "importable seule, table par table, comme avant. C'est le même "
            "format de colonnes.",
            "Le classeur n'est pas le navire : il sert à le constituer. Une "
            "fois le navire enregistré, c'est son dossier qui fait foi — "
            "gardez tout de même le classeur, il documente d'où viennent les "
            "chiffres.",
            "Si l'installation livre un navire d'exemple, son classeur rempli "
            "est dans `import_<NOM>/` : ouvrez-le pour voir à quoi "
            "ressemble un classeur complet.",
        ],
    },
    {
        "key": "identification",
        "titre": "Identification et dimensions",
        "section": "ESSENTIEL",
        "statut": "ok",
        "resume": "Nom, immatriculation et dimensions principales du navire.",
        "a_quoi": (
            "Ces valeurs servent d'en-tête à tous les documents produits, et "
            "surtout elles alimentent les formules réglementaires : le critère "
            "météo utilise la largeur, le creux et le coefficient de bloc pour "
            "calculer la période de roulis et l'angle de roulis."
        ),
        "il_faut": [
            "La page de garde du dossier de stabilité approuvé.",
            "Le certificat de jauge ou la fiche technique du navire.",
        ],
        "comment": [
            "Remplissez le nom du navire — il servira de nom au dossier de "
            "données créé sur le disque.",
            "Reportez les dimensions dans les champs ci-dessous, en mètres, "
            "telles qu'imprimées dans le dossier approuvé.",
            "Le coefficient de bloc peut être laissé vide : le logiciel le "
            "calcule alors à partir de la table hydrostatique au tirant d'eau "
            "d'été.",
        ],
        "format_intro": ("Renseignements demandés (exemples : valeurs d'un navire "
                         "d'exemple) :"),
        "format_rows": [
            ("Nom du navire", "texte", "oui", "MON NAVIRE"),
            ("Numéro OMI / immatriculation", "texte", "recommandé", "1234567"),
            ("Type de navire", "texte", "recommandé", "Voilier cargo"),
            ("Pavillon", "texte", "recommandé", "RIF"),
            ("Carène liquide : « reel » (FSM au remplissage) ou « max » "
             "(FSM maximal)", "texte", "recommandé", "reel"),
            ("Longueur hors tout", "m", "recommandé", "79.400"),
            ("Longueur entre perpendiculaires", "m", "oui", "63.450"),
            ("Largeur hors membres (B)", "m", "oui", "12.350"),
            ("Creux sur quille (D)", "m", "oui", "8.480"),
            ("Aire des quilles anti-roulis", "m²", "recommandé", "27.300"),
            # pas d'exemple chiffré : le dossier du navire de référence ne
            # donne pas l'abscisse de ses perpendiculaires dans le repère du
            # couple 0, et on n'invente pas une valeur sous l'intitulé
            # « valeurs d'un navire d'exemple »
            ("X de la perpendiculaire arrière", "m", "recommandé", "—"),
            ("X de la perpendiculaire avant", "m", "recommandé", "—"),
        ],
        "notes": [
            "Le nom saisi devient le nom du dossier de données. Évitez les "
            "accents et les espaces si le navire doit être transporté sur un "
            "autre ordinateur.",
            "La carène liquide est une convention du DOSSIER : « reel » "
            "interpole le moment de carène liquide de chaque capacité à son "
            "remplissage (c'est ce que fait le recueil approuvé du navire de "
            "référence, et "
            "LOCOPIAS) ; « max » prend le moment maximal, plus sévère. Laissée "
            "vide, c'est « max » qui s'applique — et le relevé le dit.",
            "Les X des perpendiculaires servent à répartir le tirant d'eau le "
            "long du navire (tirant d'eau local, angle d'envahissement). Sans "
            "eux, le tirant d'eau local est pris uniforme : l'angle "
            "d'envahissement ignore alors l'assiette.",
        ],
    },
    {
        "key": "hydro",
        "titre": "Table hydrostatique",
        "section": "ESSENTIEL",
        "statut": "ok",
        "resume": "Le cœur du calcul : une table par valeur d'assiette.",
        "a_quoi": (
            "C'est la pièce maîtresse. À partir du poids total embarqué et de "
            "la position longitudinale du centre de gravité, le logiciel y lit "
            "le tirant d'eau d'équilibre, l'assiette, la hauteur métacentrique "
            "et les centres de carène et de flottaison. Sans cette table, "
            "aucun calcul d'équilibre n'est possible."
        ),
        "il_faut": [
            "Les tables hydrostatiques du dossier de stabilité approuvé.",
            "Un fichier CSV ou Excel par valeur d'assiette (par exemple "
            "−0.500 m, 0.000 m, +0.500 m, +1.000 m, +1.500 m).",
        ],
        "comment": [
            "Recopiez ou exportez chaque table dans un fichier : une ligne par "
            "tirant d'eau, une colonne par grandeur, la première ligne "
            "contenant les intitulés de colonnes.",
            "Cliquez « Importer une table… » et choisissez le fichier.",
            "Indiquez à quelle valeur d'assiette correspond cette table.",
            "Vérifiez l'aperçu : les colonnes reconnues apparaissent en vert, "
            "les colonnes ignorées en gris. Corrigez les intitulés au besoin.",
            "Recommencez pour chaque assiette du dossier. Il en faut au moins "
            "deux pour que le logiciel puisse interpoler l'assiette.",
        ],
        "format_intro": (
            "Colonnes attendues dans chaque fichier — l'ordre n'a pas "
            "d'importance, seuls les intitulés comptent :"),
        "format_rows": [
            ("Tirant d'eau moyen", "m", "oui", "3.500"),
            ("Déplacement", "t", "oui", "1720.39"),
            ("LCB — centre de carène long.", "m depuis C0", "oui", "34.188"),
            ("LCF — centre de flottaison", "m depuis C0", "oui", "31.735"),
            ("KMT — métacentre transversal", "m / quille", "oui", "5.671"),
            ("BML — rayon métacentrique long.", "m", "recommandé", "77.353"),
            ("MCT — moment unitaire d'assiette", "t·m/cm", "recommandé", "19.631"),
            ("TPC — tonnes par cm d'immersion", "t/cm", "facultatif", "6.091"),
            ("VCB — centre de carène vertical", "m / quille", "facultatif", "1.957"),
        ],
        "notes": [
            "Attention : certains dossiers impriment KMT alors que la colonne "
            "contient en réalité BMT (métacentre au-dessus du centre de "
            "carène, hors VCB). Le contrôle de cohérence vous préviendra si "
            "une table décroche des autres.",
            "Toutes les abscisses doivent partir de la même origine — voir "
            "« Conventions et repères ».",
        ],
    },
    {
        "key": "kn",
        "titre": "Pantocarènes (courbes KN)",
        "section": "ESSENTIEL",
        "statut": "ok",
        "resume": "Les bras de levier de forme, par déplacement et par gîte.",
        "a_quoi": (
            "Les courbes KN donnent, pour chaque déplacement et chaque angle "
            "de gîte, le bras de levier dû à la seule forme de la coque. Le "
            "logiciel en déduit la courbe GZ en retranchant l'effet de la "
            "hauteur du centre de gravité. C'est ce qui permet de vérifier "
            "tous les critères de stabilité à grands angles."
        ),
        "il_faut": [
            "La table des pantocarènes (cross curves) du dossier approuvé.",
            "Un seul fichier CSV ou Excel.",
        ],
        "comment": [
            "Mettez les déplacements en première colonne, un par ligne.",
            "Mettez ensuite une colonne par angle de gîte, l'intitulé étant "
            "l'angle en degrés.",
            "Cliquez « Importer les pantocarènes… ».",
            "Vérifiez sur l'aperçu que les courbes montent régulièrement puis "
            "s'infléchissent : un croisement de courbes signale une erreur de "
            "recopie.",
        ],
        "format_intro": "Structure du fichier :",
        "format_rows": [
            ("Déplacement", "t", "oui", "2600.0"),
            ("KN à 5°", "m", "oui", "0.475"),
            ("KN à 10°, 15°, 20°…", "m", "oui", "…"),
            ("KN à 60°", "m", "recommandé", "5.047"),
        ],
        "notes": [
            "Les critères d'aire IS2008 demandent au moins 40° de gîte. "
            "Au-delà — un dossier va souvent jusqu'à 60° — on gagne l'angle "
            "d'annulation, et la marge nécessaire pour mesurer la stabilité "
            "résiduelle d'un navire qui a déjà de la bande.",
            "La colonne « KN à 0° » est facultative : KN y est nul par "
            "construction et le logiciel l'ajoute. La fournir quand même ne "
            "gêne pas, elle est simplement ignorée.",
            "Le KG utilisé pour établir ces courbes doit être nul (KN vrai). "
            "Si votre dossier fournit des GZ pour un KG donné, ce n'est pas "
            "la même chose — signalez-le, une conversion est nécessaire.",
        ],
    },
    {
        "key": "lege",
        "titre": "Navire lège",
        "section": "ESSENTIEL",
        "statut": "ok",
        "resume": "Le navire vide : masse et centre de gravité.",
        "a_quoi": (
            "Le navire lège est le point de départ de toute condition de "
            "chargement : c'est le navire complet, armé, mais sans cargaison, "
            "sans liquides consommables et sans personne à bord. Tout ce que "
            "vous chargerez ensuite s'ajoutera à ces valeurs."
        ),
        "il_faut": [
            "Le procès-verbal de l'essai de stabilité (inclining experiment), "
            "ou la page « lightship » du dossier approuvé.",
        ],
        "comment": [
            "Reportez les quatre valeurs ci-dessous telles qu'elles figurent "
            "au procès-verbal.",
            "Si le dossier fournit un lège « corrigé » après modification du "
            "navire, utilisez la valeur la plus récente approuvée.",
            "Attention au cas fréquent des deux lèges : l'essai de stabilité "
            "mesure le navire réel, mais le dossier approuvé a souvent été "
            "calculé pour un lège légèrement différent, accepté au titre des "
            "tolérances. Ce sont les valeurs du DOSSIER qui portent les "
            "courbes limites : prenez ses centres, et la masse mesurée. "
            "(Exemple : essai 1012,40 t à LCG 30,636 / VCG 6,348 ; dossier "
            "1010 t à LCG 30,60 / VCG 6,39 — on retient 1012,40 t à 30,60 / "
            "6,39, comme le fait LOCOPIAS.)",
        ],
        "format_intro": "Renseignements demandés :",
        "format_rows": [
            ("Masse lège", "t", "oui", "1012.40"),
            ("LCG — centre de gravité long.", "m depuis l'origine", "oui", "30.60"),
            ("VCG — centre de gravité vertical", "m / quille", "oui", "6.39"),
            ("TCG — centre de gravité transversal", "m, + bâbord", "oui", "0.160"),
            ("Date de l'expérience de stabilité", "texte", "facultatif", "2024-05-14"),
            ("Base retenue", "texte", "facultatif",
             "masse de l'expérience de stabilité, centres du dossier approuvé"),
            ("Source", "texte", "facultatif",
             "expérience de stabilité p.2 et dossier de stabilité §7.1.1"),
        ],
        "notes": [
            "Les trois lignes de texte disent d'où viennent les chiffres : "
            "elles ne servent pas au calcul, mais un navire rebâti depuis le "
            "classeur garde ainsi la trace du choix (masse mesurée, centres "
            "du dossier) dans son manifeste.",
            "Un TCG lège non nul est normal sur un navire asymétrique, mais "
            "vérifiez son signe : il fait gîter le navire en permanence.",
            "Le VCG lège est la valeur la plus sensible de tout le dossier. "
            "Une erreur de 10 cm ici décale toutes les hauteurs métacentriques "
            "de 10 cm.",
        ],
    },
    {
        "key": "criteres",
        "titre": "Critères de stabilité",
        "section": "ESSENTIEL",
        "statut": "ok",
        "resume": "Le profil du navire, et les réglementations qu'il retient.",
        "a_quoi": (
            "Ce sont les réglementations de stabilité à l'état intact auxquelles "
            "chaque condition de chargement sera confrontée. Elles viennent de la "
            "BIBLIOTHÈQUE de Carène — un fichier par réglementation, avec son "
            "texte, sa version et ses seuils. Décrivez le navire (type, "
            "propulsion, vitesse, cargaisons particulières) : « Proposer d'après "
            "le profil » coche celles qui s'appliquent. Vous cochez, décochez ; "
            "votre dossier approuvé fait foi."
        ),
        "il_faut": [
            "La page « critères de stabilité » du dossier approuvé, pour "
            "vérifier que les seuils retenus sont bien les vôtres.",
        ],
        "comment": [
            "Cochez les jeux de critères applicables.",
            "Vérifiez chaque seuil affiché contre votre dossier : en cas de "
            "divergence, c'est le dossier approuvé qui fait foi.",
            "Un seuil modifié est signalé en orange pour que vous sachiez "
            "qu'il s'écarte de la valeur réglementaire par défaut.",
        ],
        "format_intro": "La bibliothèque livrée :",
        "format_rows": [
            ("Code IS 2008 § 2.2 — critères généraux", "aires GZ, GZmax, GM",
             "vérifiée", "aire 0–30° ≥ 0.055 m·rad"),
            ("Code IS 2008 § 2.3 — critère météo", "vent et roulis",
             "vérifiée", "b ≥ a"),
            ("BV NR500 — GM des voiliers", "hauteur métacentrique",
             "vérifiée", "GM ≥ 0.30 m"),
            ("BV NR500 — sous voile", "vent, GZ à 50°",
             "vérifiée", "GZ ≥ 0.50 m"),
            ("Ligne de charge (LL 1966)", "tirant d'eau d'été",
             "vérifiée", "T milieu ≤ T été"),
            ("Code IS 2008 § 3.1 — passagers", "giration, regroupement",
             "à relire", "gîte ≤ 10°"),
            ("Code IS 2008 § 3.3 — bois en pontée", "aire, GZ, GM",
             "à relire", "aire 0–40° ≥ 0.080 m·rad"),
            ("Code IS 2008 B § 2.1 — pêche", "GM",
             "à relire", "GM ≥ 0.35 m"),
        ],
        "notes": [
            "Le critère météo et le critère « sous voile » ne s'appliquent "
            "pas ensemble : pour une condition sous voile, c'est le second qui "
            "remplace le premier.",
            "Le critère météo a besoin de la surface exposée au vent — voir "
            "l'étape correspondante dans « Compartimentage ».",
        ],
    },
    # ============================================================ COMPART
    {
        "key": "capacites",
        "titre": "Capacités et jaugeages",
        "section": "COMPART",
        "statut": "ok",
        "resume": "Soutes, ballasts, eaux : volume et centre selon le remplissage.",
        "a_quoi": (
            "Pour chaque capacité liquide, le logiciel a besoin de savoir ce "
            "que pèse son contenu, où se situe son centre de gravité et quel "
            "moment de carène liquide elle génère — le tout en fonction du "
            "taux de remplissage. Ces tables viennent du jaugeage officiel, "
            "elles ne sont jamais calculées depuis un plan."
        ),
        "il_faut": [
            "Les tables de jaugeage (sounding / ullage tables) du dossier.",
            "Un fichier CSV ou Excel par capacité, plus la liste des "
            "capacités avec leur type de liquide.",
        ],
        "comment": [
            "Créez une entrée par capacité : code (celui du dossier), nom, "
            "type de liquide et densité.",
            "Pour chaque capacité, importez sa table de jaugeage : une ligne "
            "par taux de remplissage.",
            "Vérifiez que le remplissage 100 % redonne bien la capacité "
            "totale annoncée au dossier.",
        ],
        # la LISTE des capacités (une ligne par capacité) n'a pas les mêmes
        # colonnes que la table de JAUGEAGE d'une capacité (une ligne par taux
        # de remplissage) : les deux tables sont décrites, la seconde sous
        # « format_rows » puisque c'est elle qu'on importe le plus souvent.
        # Exemples : la capacité WB 3B du navire de référence, pleine.
        "format_rows_liste": [
            ("Nom de la capacité", "texte, celui du dossier", "oui", "WB 3B"),
            ("Type — contenu", "texte", "recommandé", "Sea Water"),
            ("Groupe", "texte", "facultatif", "Ballast"),
            ("Densité du produit", "—", "recommandé", "1.025"),
            ("Volume net", "m³ (capacité pleine)", "recommandé", "27.866"),
            ("Perméabilité", "%", "facultatif", "97.0"),
            ("Poids", "t (capacité pleine)", "facultatif", "28.5625"),
            ("LCG", "m depuis C0 (capacité pleine)", "facultatif", "45.2364"),
            ("TCG", "m, + bâbord (capacité pleine)", "facultatif", "3.8574"),
            ("VCG", "m / quille (capacité pleine)", "facultatif", "0.7702"),
            ("FSM maximal", "t·m", "recommandé", "29.3493"),
            ("Baffles — cloisons anti-ballant", "0 ou 1", "facultatif", "0"),
            ("Ballast — ballastable par le solveur", "0 ou 1", "facultatif",
             "1"),
        ],
        "format_intro": "Colonnes attendues dans chaque table de jaugeage :",
        "format_rows": [
            ("Capacité prise en exemple", "nom", "—", "WB 3B"),
            ("Remplissage", "%", "oui", "50.0"),
            ("Volume", "m³", "oui", "13.930"),
            ("Poids", "t", "oui", "14.278"),
            ("LCG", "m depuis C0", "oui", "44.877"),
            ("TCG", "m, + bâbord", "oui", "3.767"),
            ("VCG", "m / quille", "oui", "0.536"),
            ("FSM — moment de carène liquide", "t·m", "oui", "28.047"),
            ("Sondage", "m", "recommandé", "0.625"),
        ],
        "notes": [
            "Le FSM (free surface moment) est indispensable : c'est lui qui "
            "corrige la hauteur métacentrique lorsqu'une capacité est "
            "partiellement remplie.",
            "Si votre dossier ne donne que le moment d'inertie i (m⁴), le "
            "FSM s'obtient en le multipliant par la densité du liquide.",
        ],
    },
    {
        "key": "envahissement",
        "titre": "Points d'envahissement",
        "section": "COMPART",
        "statut": "warn",
        "resume": "Les ouvertures par lesquelles l'eau peut entrer.",
        "a_quoi": (
            "Ce sont les ouvertures non étanches — manches à air, panneaux, "
            "portes, dalots — par lesquelles l'eau entrerait si le navire "
            "gîtait trop. Le logiciel calcule l'angle auquel le premier point "
            "atteint la flottaison : plusieurs critères réglementaires "
            "s'arrêtent à cet angle."
        ),
        "il_faut": [
            "La liste des points d'envahissement du dossier approuvé, avec "
            "leurs coordonnées.",
        ],
        "comment": [
            "Ajoutez une ligne par ouverture.",
            "Donnez les trois coordonnées dans le repère du navire.",
            "Si vous hésitez sur une ouverture, incluez-la : le logiciel "
            "retient toujours la plus pénalisante, une ouverture en trop est "
            "sans risque, une ouverture oubliée est dangereuse.",
        ],
        "format_intro": "Renseignements demandés par point :",
        "format_rows": [
            ("Repère", "texte", "oui", "12200v5"),
            ("Description", "texte", "recommandé",
             "Ventilation cale avant supérieure"),
            ("X", "m depuis C0", "oui", "38.410"),
            ("Y", "m, + bâbord", "oui", "3.387"),
            ("Z", "m / quille", "oui", "9.689"),
        ],
        "notes": [
            "Ne mettez ici que les ouvertures NON étanches aux intempéries. "
            "Une porte étanche homologuée n'est pas un point d'envahissement.",
            "Un dossier nomme souvent beaucoup plus d'ouvertures qu'il n'en "
            "cote : les autres portent la mention « non regardée » avec son "
            "motif (en hauteur, loin du bordé, plus au centre qu'une "
            "ouverture déjà retenue). N'importez que celles qui ont des "
            "coordonnées — ce sont les seules que le dossier a retenues — "
            "mais gardez la liste des autres quelque part : si le navire est "
            "modifié, c'est là qu'il faudra rechercher.",
            "Le logiciel retient le point le plus contraignant, tous côtés "
            "confondus. L'angle qu'il en tire est compté depuis la verticale : "
            "une gîte permanente consomme d'autant la marge réelle.",
        ],
    },
    {
        "key": "vent",
        "titre": "Surface exposée au vent",
        "section": "COMPART",
        "statut": "todo",
        "resume": ("Facultatif — et attention : ce n'est PAS une propriété du "
                   "navire."),
        "a_quoi": (
            "Le critère météo IS2008 §2.3 simule l'effet d'une rafale sur le "
            "navire en train de rouler. Il a besoin de la surface exposée au "
            "vent au-dessus de la flottaison, de sa hauteur, et du plan de "
            "dérive immergé. Or ces valeurs dépendent du tirant d'eau — donc "
            "de la condition de chargement — et, pour un voilier, du gréement "
            "déployé. Ce qu'on saisit ici décrit une CONFIGURATION DE "
            "RÉFÉRENCE, faute de mieux ; les valeurs exactes de chaque "
            "condition viennent du dossier, cas par cas. Sans ces valeurs, "
            "tous les autres critères restent calculables — seul le critère "
            "météo n'est pas évalué, et le logiciel le dit."
        ),
        "il_faut": [
            "La page « windage area » ou « surface au vent » du dossier.",
        ],
        "comment": [
            "Renseignez les quatre valeurs pour une condition de référence "
            "représentative (par exemple le départ pleine charge), ou laissez "
            "vide si votre dossier n'en donne pas.",
            "Si le navire porte des voiles, importez en plus la TABLE des "
            "surfaces au vent (feuille « Profils_vent » du classeur) : une "
            "ligne par configuration de voilure et par tirant d'eau. C'est "
            "elle qui permet d'évaluer le critère de vent à l'écran, dans la "
            "voilure réellement portée, et d'interpoler au tirant d'eau du "
            "moment.",
        ],
        "format_intro": ("Renseignements demandés (exemple : le cas 01 d'un "
                         "dossier de stabilité, configuration cargo) :"),
        "format_rows": [
            ("Aire de la surface exposée au vent", "m²", "facultatif", "618.065"),
            ("Hauteur du centre de cette surface", "m / quille", "facultatif",
             "15.721"),
            ("Aire du plan de dérive immergé", "m²", "facultatif", "305.989"),
            ("Hauteur du centre du plan de dérive", "m / quille", "facultatif",
             "2.500"),
        ],
        "notes": [
            "L'aire des quilles anti-roulis intervient aussi dans le critère "
            "météo (coefficient k) : elle se saisit à l'étape « Identification "
            "et dimensions ». L'omettre rend le critère plus sévère qu'il ne "
            "devrait, donc le résultat reste du côté de la sécurité.",
        ],
    },
    # ============================================================ PLANS
    {
        "key": "couples",
        "titre": "Table des couples",
        "section": "PLANS",
        "statut": "todo",
        "resume": "Les traits de couples : de quoi caler un plan sans mesurer.",
        "a_quoi": (
            "Un plan de chantier porte ses traits de couples, cotés « C.35 », "
            "rarement des abscisses en mètres. Avec cette table, le calage "
            "d'un plan se fait en désignant un couple : le logiciel connaît "
            "son X et place la grille. Sans elle, il faut mesurer les "
            "abscisses à la main sur chaque plan, et se tromper une fois "
            "suffit à décaler tout un pont. Elle sert aussi à coter les plans "
            "à l'écran. Elle n'entre dans AUCUN calcul de stabilité (D-11)."
        ),
        "il_faut": [
            "La table d'espacement des couples du dossier, ou le cartouche du "
            "plan de structure (« frame spacing »).",
        ],
        "comment": [
            "Le plus simple : « Générer depuis les espacements… » — donnez "
            "l'abscisse du couple 0, puis un tronçon par espacement (« de C.0 "
            "à C.1 : 0,75 m », « de C.1 à C.15 : 1,00 m »…). Les tronçons "
            "doivent s'enchaîner sans trou.",
            "Sinon, « Importer… » un fichier à deux colonnes (n, x_m), ou "
            "saisissez les lignes à la main dans le tableau.",
            "Vérifiez le dernier couple contre le plan : c'est le contrôle le "
            "plus rapide d'un espacement mal repris.",
        ],
        "format_intro": ("Renseignements demandés (exemples : valeurs d'un navire "
                         "d'exemple) :"),
        "format_rows": [
            ("Numéro de couple", "entier", "oui", "35"),
            ("X — abscisse du couple", "m depuis l'origine des abscisses",
             "oui", "39.950"),
        ],
        "notes": [
            "L'origine des abscisses reste la vôtre : par exemple, C.0 à "
            "X = 0 et des couples jusqu'à C.61 à 71,000 m, avec un "
            "espacement qui n'est pas constant (0,75 m, puis 1,00, 1,25 et "
            "1,35 m).",
            "Les X des PERPENDICULAIRES, eux, se saisissent à l'étape "
            "« Identification et dimensions » — ce sont deux choses "
            "différentes (par exemple, la perpendiculaire arrière peut être à "
            "−0,25 m de C.0).",
        ],
    },
    {
        "key": "profil",
        "titre": "Profil longitudinal",
        "section": "PLANS",
        "statut": "ok",
        "resume": "L'image du profil, calée dans le repère du navire.",
        "a_quoi": (
            "Le profil est la vue maîtresse : c'est lui qui porte les "
            "hauteurs. Une fois calé, cliquer un point de l'image donne "
            "directement sa position réelle en mètres, ce qui permet ensuite "
            "de placer les ponts sans les mesurer à la main."
        ),
        "il_faut": [
            "Une image du plan de profil (PNG ou JPG), la plus nette possible.",
            "Deux repères connus sur cette image : par exemple "
            "l'intersection de la perpendiculaire arrière et de la ligne de "
            "base, et un point du pont principal.",
        ],
        "comment": [
            "Cliquez « Importer un plan… » et choisissez le plan de profil (image ou PDF).",
            "Cliquez un premier repère sur l'image, puis saisissez ses "
            "coordonnées réelles (X et Z, en mètres).",
            "Recommencez avec un deuxième repère, décalé à la fois "
            "horizontalement et verticalement du premier. Un troisième point "
            "améliore la précision si le scan est de travers.",
            "Cliquez « Appliquer » : une grille se superpose au plan. Elle "
            "doit tomber juste sur les repères imprimés. Sinon, corrigez les "
            "points.",
        ],
        "format_intro": None,
        "format_rows": [],
        "notes": [
            "Chaque point de calage reçoit un intitulé libre (« PPAR × ligne "
            "de base »). Prenez le temps de le remplir : c'est ce qui rendra "
            "le calage vérifiable dans six mois.",
            "L'écart résiduel de calage est affiché en mètres après "
            "application. Au-delà de quelques centimètres, reprenez les points.",
        ],
    },
    {
        "key": "ponts",
        "titre": "Ponts",
        "section": "PLANS",
        "statut": "ok",
        "resume": "Les niveaux du navire et leur hauteur.",
        "a_quoi": (
            "Les ponts découpent le navire en niveaux. Ils servent à ranger "
            "les capacités, à pré-remplir l'étendue verticale d'une cale d'un "
            "pont à l'autre, et à dessiner la vue isométrique."
        ),
        "il_faut": ["Le profil calé à l'étape précédente."],
        "comment": [
            "Cliquez la ligne d'un pont directement sur le profil : sa hauteur "
            "Z se remplit toute seule.",
            "Donnez-lui un nom (« Pont principal », « Pont inter »…).",
            "Recommencez pour chaque niveau, du bas vers le haut.",
        ],
        "format_intro": "Renseignements demandés par pont :",
        "format_rows": [
            ("Nom du pont", "texte", "oui", "Pont principal"),
            ("Hauteur Z", "m / quille", "oui", "6.500"),
        ],
        "notes": [],
    },
    {
        "key": "plans_ponts",
        "titre": "Plans de ponts",
        "section": "PLANS",
        "statut": "warn",
        "resume": "Une vue de dessus par pont, calée en X et Y.",
        "a_quoi": (
            "La vue de dessus de chaque pont permet de tracer les contours et "
            "les capacités à leur emplacement réel, et c'est sur elle que "
            "s'appuie le placement graphique des palettes."
        ),
        "il_faut": [
            "Une image de la vue de dessus par pont.",
            "Deux points de la ligne de foi (Y = 0) à des abscisses connues, "
            "et un point hors axe.",
        ],
        "comment": [
            "Sélectionnez un pont, puis « Importer le plan de ce pont… ».",
            "Cliquez deux points situés sur la ligne de foi, à des X connus.",
            "Cliquez un troisième point hors de l'axe, dont vous connaissez X "
            "et Y — c'est lui qui fixe l'échelle transversale et le sens de Y.",
            "Appliquez, puis vérifiez la grille superposée.",
        ],
        "format_intro": None,
        "format_rows": [],
        "notes": [
            "Rappel : Y est positif vers BÂBORD. Si la grille place bâbord du "
            "mauvais côté, c'est le signe du troisième point qui est en cause.",
        ],
    },
    {
        "key": "polygones",
        "titre": "Contours et capacités dessinées",
        "section": "PLANS",
        "statut": "todo",
        "resume": "Le tracé des cales, pour y placer le chargement.",
        "a_quoi": (
            "Tracer le contour d'une cale permet de la garnir graphiquement : "
            "c'est sur ce polygone que la grille de palettes vient se poser. "
            "Le contour du pont, lui, sert de décor à la vue isométrique."
        ),
        "il_faut": ["Les plans de ponts calés à l'étape précédente."],
        "comment": [
            "Choisissez l'outil « Contour » pour tracer la forme du pont, "
            "ou « Capacité » pour une cale.",
            "Cliquez les sommets du polygone sur le plan, puis Entrée pour "
            "fermer.",
            "Donnez le code de la capacité — celui du dossier de données — "
            "et vérifiez l'étendue verticale, pré-remplie d'un pont à l'autre.",
        ],
        "format_intro": "Renseignements demandés par capacité :",
        "format_rows": [
            ("Code", "texte", "oui", "CALE2"),
            ("Nom", "texte", "recommandé", "Cale 2"),
            ("Z bas", "m / quille", "oui", "0.900"),
            ("Z haut", "m / quille", "oui", "3.600"),
        ],
        "notes": [
            "Le polygone sert à placer et visualiser, jamais à calculer un "
            "volume : les volumes et centres viennent toujours des tables de "
            "jaugeage officielles.",
        ],
    },
    # ============================================================ VERIF
    {
        "key": "validation",
        "titre": "Cas de référence (contrôle)",
        "section": "VERIF",
        "statut": "todo",
        "resume": "La preuve que les tables ont été importées correctement.",
        "a_quoi": (
            "C'est le filet de sécurité de tout ce travail. Vous recopiez un "
            "ou deux cas de chargement du dossier approuvé avec leurs "
            "résultats imprimés ; le logiciel recalcule et compare. Si les "
            "écarts sont infimes, vos tables sont bonnes. Si un écart "
            "apparaît, c'est qu'une colonne a été mal reprise — et il vaut "
            "mieux le découvrir maintenant."
        ),
        "il_faut": [
            "Une ou deux pages « conditions de chargement » du dossier "
            "approuvé, avec le total des poids et les résultats. Le détail "
            "cale par cale n'est pas nécessaire : c'est le TOTAL (poids, LCG, "
            "TCG, VCG, FSM) qui sert d'entrée.",
        ],
        "comment": [
            "Remplissez la feuille « Cas_de_reference » du classeur (ou "
            "importez un fichier à part) : une ligne par cas.",
            "Recopiez d'abord les entrées du cas : poids total, LCG, TCG, VCG "
            "et moment de carène liquide total.",
            "Recopiez ensuite les résultats imprimés — tirant d'eau, assiette, "
            "GM corrigé, GZmax et son angle. Ne renseignez que ceux que votre "
            "dossier donne : seuls ceux-là seront comparés.",
            "Cliquez « Rejouer les cas » et lisez le tableau : chaque écart "
            "est affiché avec sa tolérance, en vert s'il tient, en rouge "
            "sinon.",
        ],
        "format_intro": ("Une ligne par cas (exemple : le cas 01 d'un dossier "
                         "de stabilité) — d'abord les entrées, puis les résultats "
                         "attendus :"),
        "format_rows": [
            ("Cas", "texte", "oui", "01"),
            ("Titre", "texte", "recommandé", "Départ avec cargo"),
            ("Déplacement total (poids embarqué)", "t", "oui", "2616.33"),
            ("LCG total", "m depuis C0", "oui", "33.0827"),
            ("TCG total", "m, + bâbord", "facultatif", "0.0002"),
            ("VCG solide", "m / quille", "oui (ou le corrigé)", "4.8447"),
            ("VCG corrigé", "m / quille", "oui (ou le solide)", "4.8587"),
            ("FSM — moment de carène liquide", "t·m", "oui", "36.5447"),
            ("Tirant d'eau moyen attendu", "m", "facultatif", "4.8945"),
            ("Assiette attendue", "m", "facultatif", "−0.0384"),
            ("GM corrigé attendu", "m", "facultatif", "0.570"),
            ("GZmax attendu", "m", "facultatif", "0.9253"),
            ("Angle du GZmax attendu", "degrés", "facultatif", "50.0"),
        ],
        "notes": [
            "Attention : dans beaucoup de dossiers — celui du navire de "
            "référence compris — "
            "le « VCG total » imprimé est DÉJÀ corrigé de la carène liquide. "
            "Portez-le alors en « VCG corrigé » : le logiciel en déduit le VCG "
            "solide (VCG corrigé − FSM / poids). Le porter en « VCG solide » "
            "compterait la correction deux fois et abaisserait le GM d'autant.",
            "Les tolérances appliquées sont celles du rejeu des 15 cas "
            "du navire de référence : tirant d'eau ±0,02 m, assiette ±0,06 m, GM ±0,015 m, "
            "GZmax ±0,06 m, angle du GZmax ±3°. Elles couvrent l'interpolation "
            "des tables et l'arrondi d'impression, rien de plus.",
            "Un écart de GM supérieur à 1 cm mérite une recherche avant de "
            "mettre le navire en service dans le logiciel.",
        ],
    },
    {
        "key": "recap",
        "titre": "Récapitulatif et enregistrement",
        "section": "VERIF",
        "statut": "todo",
        "resume": "Vue d'ensemble, puis écriture du dossier navire.",
        "a_quoi": (
            "Dernière étape : vous voyez d'un coup d'œil ce qui est fait et ce "
            "qui manque, et vous enregistrez. Le navire est écrit dans un "
            "dossier autonome : le copier sur une clé suffit à le transporter "
            "sur un autre ordinateur."
        ),
        "il_faut": [],
        "comment": [
            "Relisez le récapitulatif ci-dessous.",
            "Cliquez « Enregistrer le navire ». Un navire NEUF reçoit son "
            "propre dossier, à son nom, à côté de l'application : "
            "`navires/<NOM DU NAVIRE>/` — le panneau ci-dessous affiche le "
            "chemin exact avant l'écriture. Un navire déjà enregistré reste "
            "là où il est.",
            "Vous pouvez revenir modifier n'importe quelle étape plus tard : "
            "rien n'est figé.",
        ],
        "format_intro": "Ce qui sera écrit sur le disque :",
        "format_rows": [
            ("navire.json", "manifeste", "—", "identité, dimensions, critères"),
            ("hydrostatiques.csv", "tables", "—", "une section par assiette"),
            ("pantocarenes_kn.csv", "tables", "—", "KN par déplacement et gîte"),
            ("jauges/", "dossier", "—", "une table par capacité"),
            ("couples.csv", "table", "—", "abscisse de chaque couple"),
            ("validation/cas_reference.csv", "table", "—",
             "les cas du dossier et leurs résultats"),
            ("plans/", "dossier", "—", "images des plans et leur calage"),
        ],
        "notes": [
            "Le nom du dossier est tiré du nom du navire, sans accent ni "
            "espace et en majuscules (« Sœur Océane » → `SOEUR_OCEANE`) : un "
            "dossier de navire se copie sur une clé et doit s'ouvrir sur "
            "n'importe quel poste.",
            "Évitez d'enregistrer le navire dans un dossier synchronisé qui "
            "pourrait le modifier pendant une exploitation.",
        ],
    },
]
