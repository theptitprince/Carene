# -*- coding: utf-8 -*-
"""Solveur de chargement : réglages, exécution, compte rendu.

Les réglages sont rangés en TROIS FAMILLES, dans l'ordre où l'officier de
chargement se pose les questions — et ce sont les mêmes trois familles que
dans `stowage.Reglages` :

1. **Ce qu'on cherche** — la priorité (charger au maximum ou tenir
   l'assiette), et les deux buts qu'on coche séparément : l'assiette visée et
   la gîte.
2. **Ce qu'on s'autorise** — empiler, tourner les colis, imposer la
   disposition dans la cale (dans quel sens elle se remplit, pas dans quel
   sens sont posés les colis), mélanger les lots, suivre les cales du
   manifeste, repartir des cales vides.
3. **Ce qu'on respecte** — l'ordre des escales, et les ponts qu'on sert
   d'abord.

Trois **réglages rapides** cochent d'un coup une combinaison qui se lit
ensuite case par case : on doit toujours pouvoir voir ce qu'on a demandé.

Le résultat est un **premier jet** — la boîte le dit, et affiche sans détour
ce qui n'a pas pu être placé, POURQUOI, et si la raison est un réglage, elle
nomme le réglage : une case se décoche, « plus de place » ne se décoche pas.

Les réglages se retiennent d'un lancement à l'autre (`app_paths`,
`carene.config.json`) : ce sont des réglages de TRAVAIL, jamais des données du
navire ni du chargement, et ils ne mettent donc rien dans le dossier du navire.
"""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QMessageBox,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import app_paths, theme
from .core import stowage
from .core.stowage import (ASSIETTE_GM, AUTO, BAS, CAPACITE, HAUT, Hold,
                           DEBORD_JEU_M, LONGITUDINALE, Reglages, TRANSVERSALE)
from .project import KIND_CONTOUR
from .stow_editor import _obstacles_actifs
from .saisie import SpinNombre


def holds_du_navire(project, epontilles_en_place=()):
    """Cales exploitables par le solveur (polygone tracé).

    `epontilles_en_place` : les épontilles amovibles posées au point courant.
    Elles rejoignent les zones interdites de leur cale — le solveur les
    contourne comme une muraille, il n'a aucune règle en propre à leur sujet."""
    return [Hold(c.code, list(c.points), c.z_min, c.z_max,
                 getattr(c, "charge_admissible_t_m2", 0.0), c.name,
                 obstacles=[tuple(o) for o in _obstacles_actifs(
                     c, epontilles_en_place)],
                 zones_charge=list(getattr(c, "zones_charge", [])),
                 classes_imdg=list(getattr(c, "classes_imdg", []) or []))
            for _, c in project.all_capacities()
            if c.kind != KIND_CONTOUR and len(c.points) >= 3]


def hors_cargaison(win, cond, cales):
    """(poids, moment longitudinal, moment transversal) de tout ce que le
    solveur ne pose pas : le lège, les caisses, les poids saisis — ET la
    cargaison des cales qu'il ne redistribue pas (`cales` : les codes des
    cales qu'il reçoit ; leurs colis gardés lui arrivent comme épinglés).

    Jusqu'à la 2.20.0, toute la cargaison des cales était retirée : ce qui
    était posé dans une cale non cochée ne comptait nulle part, et l'assiette
    annoncée par le répartiteur était fausse (+2,65 m annoncés, +1,40 m une
    fois le plan appliqué, pour 120 t laissées dans une autre cale).

    Une seule fonction pour les trois chemins de calepinage (répartiteur,
    plan de cale, zone) : deux chemins qui ne recevraient pas le même « reste
    du navire » viseraient deux TCG différents et poseraient différemment
    (D-39)."""
    nav = getattr(win, "nav", None)
    if nav is None:
        return 0.0, 0.0, 0.0
    cales = set(cales or ())
    noyau = cond.to_core(nav, win.project)
    noyau.cargo = [c for c in noyau.cargo
                   if getattr(c, "code_cale", None) not in cales]
    p, lcg, tcg, _vcg, _fsm = noyau.totals()
    return p, p * lcg, p * tcg


def lignes_restantes(lignes, cond, gardes, cales):
    """Les lignes de manifeste réduites à ce qu'il reste à poser.

    `gardes` : {code cale: [Placement]} conservés dans les cales que le
    solveur garnit ; `cales` : les codes de ces cales. Un exemplaire compte
    par niveau empilé. Ce qui est posé dans une cale non garnie reste, et
    compte aussi. On rend des COPIES : le manifeste n'est pas touché."""
    import dataclasses
    deja = {}
    for code, lst in cond.placements.items():
        source = gardes.get(code, []) if code in cales else lst
        for p in source:
            if p.lot_id and not p.est_materiel_bord:
                deja[p.lot_id] = deja.get(p.lot_id, 0) + max(1, p.niveaux)
    out = []
    for m in lignes:
        reste = m.quantite - deja.get(m.lot_id, 0)
        if reste > 0:
            out.append(dataclasses.replace(m, quantite=reste))
    return out


class SolverDialog(QDialog):
    """Règle et lance le solveur, puis rend compte."""

    def __init__(self, win, parent=None, cales=None):
        super().__init__(parent or win)
        self.win = win
        self.rapport = None
        # les seules cales à cocher à l'ouverture (menu du clic droit d'une
        # cale, D-65) ; None = toutes, comme toujours
        self.cales_imposees = set(cales) if cales else None
        self.setWindowTitle("Répartir le chargement")
        self.resize(1160, 720)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Le titre, et à droite le « ? » qui ouvre la page d'aide DE CETTE
        # fenêtre : les trois familles de réglages y sont expliquées une à
        # une, avec ce que dit le compte rendu quand un colis reste à quai.
        ligne_titre = QHBoxLayout()
        titre = QLabel("Répartition automatique")
        titre.setStyleSheet("font-size: 18px; font-weight: bold;")
        ligne_titre.addWidget(titre)
        ligne_titre.addStretch(1)
        self.btn_aide = QPushButton("?")
        self.btn_aide.setProperty("ghost", "1")
        self.btn_aide.setFixedWidth(32)
        self.btn_aide.setToolTip("Ouvrir l'aide du répartiteur  (F1)")
        self.btn_aide.clicked.connect(self.ouvrir_aide)
        ligne_titre.addWidget(self.btn_aide)
        root.addLayout(ligne_titre)
        QShortcut(QKeySequence("F1"), self, activated=self.ouvrir_aide)
        intro = QLabel(
            "Un premier jet, à ajuster ensuite. Le solveur essaie une "
            "quinzaine de calepinages par cale et garde le meilleur, en "
            "respectant toujours le contour, la hauteur libre, la charge "
            "admissible et le stack de chaque lot ; les charges épinglées ne "
            "sont jamais déplacées. Le reste se règle ci-dessous : ce qu'on "
            "cherche, ce qu'on s'autorise, ce qu'on respecte.")
        intro.setObjectName("hint")
        intro.setWordWrap(True)
        root.addWidget(intro)

        # ------------------------------------------------- réglages rapides
        # Trois combinaisons que le bord emploie tous les jours. Ce ne sont
        # pas des modes : elles COCHENT les cases ci-dessous, qui restent
        # visibles et modifiables — on doit pouvoir lire ce qu'on a demandé.
        rapide = QHBoxLayout()
        rapide.setSpacing(8)
        lbl_r = QLabel("Réglage rapide :")
        lbl_r.setObjectName("hint")
        rapide.addWidget(lbl_r)
        for libelle, cle, aide in (
                ("Au plus", "au_plus",
                 "Tout ce qui entre : on mélange les lots, on empile, on "
                 "tourne. L'assiette et la gîte départagent les cales, sans "
                 "jamais coûter un colis."),
                ("Chargement soigné", "soigne",
                 "Un lot par cale, l'ordre des escales tenu, les ponts bas "
                 "d'abord : le quai va plus vite et le GM est meilleur, mais "
                 "il restera de la place inemployée."),
                ("Assiette tenue", "assiette",
                 "L'assiette visée prime sur le remplissage : le solveur "
                 "s'arrête de garnir une cale plutôt que de rater la cible.")):
            b = QPushButton(libelle)
            b.setProperty("ghost", "1")
            b.setToolTip(aide)
            b.clicked.connect(lambda _=False, c=cle: self._reglage_rapide(c))
            rapide.addWidget(b)
        rapide.addStretch(1)
        root.addLayout(rapide)

        # --------------------------------------- les trois familles, côte à côte
        familles = QHBoxLayout()
        familles.setSpacing(10)

        # === A · CE QU'ON CHERCHE =========================================
        ca, la = self._carte("Ce qu'on cherche")
        p_lbl = QLabel("Priorité")
        p_lbl.setStyleSheet("font-weight: bold;")
        la.addWidget(p_lbl)
        self.rb_capacite = QRadioButton("Charger au maximum (l'assiette suit)")
        self.rb_capacite.setToolTip(
            "Le solveur sert à chaque colis la cale la plus libre, en "
            "fraction de sa surface — la petite cave est servie comme les "
            "grandes. Il ne renonce jamais à un colis pour tenir une "
            "assiette : c'est le ballast qui rattrapera.")
        self.rb_assiette = QRadioButton("Tenir l'assiette visée (quitte à "
                                        "charger moins)")
        self.rb_assiette.setChecked(True)
        self.rb_assiette.setToolTip(
            "Le solveur calcule le LCG que la cargaison doit avoir pour "
            "tomber sur l'assiette demandée et répartit pour l'approcher, en "
            "descendant les lourdes. Une cale peut rester à moitié vide si la "
            "remplir écartait le navire de la cible.")
        la.addWidget(self.rb_capacite)
        la.addWidget(self.rb_assiette)

        grille_a = QGridLayout()
        grille_a.setHorizontalSpacing(8)
        grille_a.setColumnStretch(0, 1)
        self.chk_viser = QCheckBox("Viser une assiette de")
        self.chk_viser.setChecked(True)
        self.chk_viser.setToolTip(
            "Décochée, l'assiette n'entre dans AUCUN départage — pas même "
            "pour choisir entre deux cales également libres en mode « au "
            "maximum ». C'est le réglage du bord qui dit : « remplis, je "
            "m'occuperai de l'assiette au ballast ». Le compte rendu annonce "
            "quand même l'assiette que donne le plan.")
        self.sp_trim = SpinNombre()
        self.sp_trim.setRange(-5, 5)
        self.sp_trim.setDecimals(2)
        self.sp_trim.setSingleStep(0.1)
        self.sp_trim.setSuffix(" m")
        self.sp_trim.setValue(0.30)
        self.sp_trim.setToolTip(
            "Assiette visée, en mètres (positif = sur l'arrière). Le solveur "
            "en déduit le LCG que la cargaison doit avoir ; si ce LCG tombe "
            "hors de l'étendue des cales, il le dit au lieu de le remplacer.")
        grille_a.addWidget(self.chk_viser, 0, 0)
        grille_a.addWidget(self.sp_trim, 0, 1)

        # Chercher la gîte : c'est un QUATRIÈME critère, après la capacité et
        # l'assiette (D-38). Coché d'office — un navire droit est ce qu'on
        # veut à chaque escale, et le bord ne devrait pas avoir à le demander.
        self.chk_gite = QCheckBox("Chercher la gîte, TCG visé")
        self.chk_gite.setChecked(True)
        self.chk_gite.setToolTip(
            "Le solveur suit le TCG de ce qu'il pose et, à cale et calepinage "
            "équivalents, sert le bord qui compense. La capacité et l'assiette "
            "gardent la main : la gîte ne se cherche qu'ensuite. Le compte "
            "rendu annonce le TCG prévu — pas une gîte en degrés, que le "
            "solveur ne peut pas calculer sans le GM ; la gîte réelle se lit "
            "au bandeau une fois le plan appliqué.")
        self.sp_tcg = SpinNombre()
        self.sp_tcg.setRange(-5, 5)
        self.sp_tcg.setDecimals(2)
        self.sp_tcg.setSingleStep(0.05)
        self.sp_tcg.setSuffix(" m")
        self.sp_tcg.setValue(0.0)
        self.sp_tcg.setToolTip(
            "TCG que le NAVIRE ENTIER doit avoir : 0 m = navire droit, ce "
            "qu'on veut presque toujours. Le solveur en déduit le TCG que la "
            "cargaison doit viser, compte tenu de tout ce qui penche déjà "
            "(lège, caisses, matériel). On vise autre chose pour compenser "
            "une avarie ou une carène dissymétrique. Une zone morte de 5 cm "
            "marque l'objectif atteint.")
        grille_a.addWidget(self.chk_gite, 1, 0)
        grille_a.addWidget(self.sp_tcg, 1, 1)
        la.addLayout(grille_a)
        la.addStretch(1)
        familles.addWidget(ca, 1)

        # === B · CE QU'ON S'AUTORISE ======================================
        cb, lb = self._carte("Ce qu'on s'autorise")
        self.chk_empiler = QCheckBox("Empiler les colis quand le lot le "
                                     "permet (stack)")
        self.chk_empiler.setChecked(True)
        self.chk_empiler.setToolTip(
            "Décochée, le solveur pose UNE SEULE COUCHE, même sur un lot dont "
            "le manifeste annonce un stack de 3 : il faut alors trois fois "
            "plus de surface, et il restera des colis à quai — le compte rendu "
            "dit combien, et dit que c'est ce réglage. Le manifeste, lui, "
            "n'est pas touché : le stack reste une donnée de la marchandise.")
        lb.addWidget(self.chk_empiler)

        # DISPOSITION : dans quel sens la cale se REMPLIT, et non dans quel
        # sens sont posés les colis. C'est le retour du bord : « quand
        # il s'agit de choisir entre longitudinale ou transversale, il n'est
        # pas question du sens des colis, mais dans quel sens ils sont DISPOSÉS
        # dans les cales ». Le transversal sert la gîte, le longitudinal
        # l'assiette ; l'infobulle le dit avec ses mots.
        form2 = QFormLayout()
        form2.setContentsMargins(0, 0, 0, 0)
        self.cb_disposition = QComboBox()
        for libelle, valeur in (
                ("Automatique (le solveur choisit)", AUTO),
                ("Transversale — de tribord à bâbord, pour la gîte",
                 TRANSVERSALE),
                ("Longitudinale — d'arrière en avant, pour l'assiette",
                 LONGITUDINALE)):
            self.cb_disposition.addItem(libelle, valeur)
        self.cb_disposition.setToolTip(
            "Dans quel sens la cale se REMPLIT — pas dans quel sens sont posés "
            "les colis (ça, c'est « Tourner les colis de 90° »). "
            "« Transversale » : les colis se disposent d'une muraille à "
            "l'autre, et c'est la GÎTE VISÉE qui décide du côté de départ — "
            "depuis tribord, depuis bâbord, ou depuis l'axe vers les deux "
            "bords quand on veut le navire droit. « Longitudinale » : d'un "
            "bout à l'autre, et c'est l'ASSIETTE VISÉE qui décide du bout de "
            "départ — d'arrière en avant, d'avant en arrière, ou depuis le "
            "milieu. Ça ne change rien tant que le lot remplit la cale ; ça "
            "décide de tout dès qu'il ne la remplit qu'à moitié. "
            "« Automatique » laisse le calepineur loger le plus de colis "
            "possible. Le compte rendu dit, cale par cale, ce qui a été fait.")
        # L'ancien nom de la case, le temps que tout ait migré : la fenêtre du
        # plan de cale et les tests la désignent encore ainsi.
        self.cb_sens = self.cb_disposition
        form2.addRow("Disposition dans la cale", self.cb_disposition)
        lb.addLayout(form2)

        # La rotation n'est plus couplée à la disposition : celle-ci gouverne
        # l'ORDRE dans lequel la cale se remplit, celle-là le sens des colis.
        # Deux questions distinctes, deux cases vives.
        self.chk_rotation = QCheckBox("Tourner les colis de 90°")
        self.chk_rotation.setChecked(True)
        self.chk_rotation.setToolTip(
            "Le calepinage choisit alors l'orientation de chaque colis pour "
            "occuper le plus de place — ce n'est pas un rattrapage de fin de "
            "rangée. Décochez pour garder tous les colis dans le sens du "
            "manifeste : sens d'empilement, passage des fourches, saisines. Un "
            "type que le catalogue déclare « sans rotation » n'est jamais "
            "tourné, quoi qu'il en soit ici. C'est le SEUL réglage qui touche "
            "au sens des colis : « Disposition dans la cale » dit seulement "
            "dans quel ordre la cale se remplit.")
        lb.addWidget(self.chk_rotation)

        self.chk_melanger = QCheckBox("Mélanger les lots dans une même cale")
        self.chk_melanger.setChecked(True)
        self.chk_melanger.setToolTip(
            "Cochée, une cale reçoit plusieurs lots : on remplit davantage, "
            "mais au quai il faut aller chercher deux ou trois marchandises "
            "dans la même cale. Décochée, le solveur finit un lot dans une "
            "cale avant d'y en commencer un autre et n'ouvre une deuxième "
            "cale que si la première est pleine ; le compte rendu dit combien "
            "de colis ça laisse à terre.")
        lb.addWidget(self.chk_melanger)

        self.chk_imposee = QCheckBox("Respecter les cales imposées du manifeste")
        self.chk_imposee.setChecked(True)
        self.chk_imposee.setToolTip(
            "La colonne « Cale » du manifeste fait loi : un lot qui la porte "
            "n'est essayé que là, et il reste à quai si elle est pleine. "
            "Décochée, le solveur traite cette colonne comme un souhait et "
            "place le lot où il entre.")
        lb.addWidget(self.chk_imposee)

        # Le bord pose souvent quelques colis à la main AVANT de lancer le
        # solveur (une pièce lourde à sa place, une rangée qu'on veut ainsi)
        # : il ne veut pas les voir balayés. Par défaut le solveur COMPLÈTE
        # ce qui est posé ; repartir des cales vides se demande, et se
        # confirme si des colis y passent (retour du bord, v2.14.3).
        self.chk_vider = QCheckBox("Repartir des cales vides")
        self.chk_vider.setChecked(False)
        self.chk_vider.setToolTip(
            "Décoché (par défaut) : le solveur garde tout ce qui est posé et "
            "place le reste autour. Coché : il retire les colis des lots "
            "cochés dans les cales cochées — sauf les colis épinglés et le "
            "matériel du bord — et vous le confirme avant de le faire.")
        lb.addWidget(self.chk_vider)
        lb.addStretch(1)
        familles.addWidget(cb, 1)

        # === C · CE QU'ON RESPECTE ========================================
        cc, lc = self._carte("Ce qu'on respecte")
        self.chk_escales = QCheckBox("Ordre des escales : ne rien empiler sur "
                                     "ce qui se débarque avant")
        self.chk_escales.setChecked(False)
        self.chk_escales.setToolTip(
            "Le solveur lit le port de déchargement de chaque lot et l'ordre "
            "des escales du navire (Navire › Escales). Il refuse alors de "
            "poser un lot au-dessus d'un lot qui sort à une escale "
            "ANTÉRIEURE — dans une pile comme d'un pont à l'autre. Il ne "
            "modélise RIEN d'autre : ni le chemin des fourches, ni « ce qui "
            "est devant bloque ce qui est derrière ». Deux lots sans port, ou "
            "de même port, ne se contraignent pas.")
        lc.addWidget(self.chk_escales)

        # LES DEUX CONTRAINTES QU'ON PEUT DÉBRAYER (D-71). Cochées, elles
        # refusent ; décochées, le plan les ignore et le compte rendu dit,
        # cale par cale, ce qui les dépasse — et le plan de chargement le
        # signale par ses calques. Le rappel orange sous les cases reste
        # tant qu'une case est décochée : un plan « sans refus » obtenu en
        # débrayant une contrainte ne doit jamais passer pour un plan valide.
        self.chk_charge = QCheckBox("Charge de pont admissible (t/m²) : "
                                    "refuser ce qui la dépasse")
        self.chk_charge.setChecked(True)
        self.chk_charge.setToolTip(
            "Cochée : un colis qui dépasserait la charge admissible de "
            "l'endroit (calque des charges) ou la charge moyenne de la cale "
            "n'est pas posé, et le compte rendu dit pourquoi. Décochée : il "
            "est posé quand même, et le dépassement est SIGNALÉ — ici, et sur "
            "le plan par le calque des charges. À réserver aux cas qu'on "
            "assume : renfort local que le calque ne connaît pas, ou pour "
            "mesurer ce que la contrainte coûte.")
        self.chk_charge.toggled.connect(self._contraintes_changees)
        lc.addWidget(self.chk_charge)
        self.chk_hauteur = QCheckBox("Hauteur libre des cales : refuser ce "
                                     "qui la dépasse")
        self.chk_hauteur.setChecked(True)
        self.chk_hauteur.setToolTip(
            "Cochée : une pile ne dépasse jamais la hauteur libre à l'endroit "
            "où elle est (zones de hauteur réduite comprises). Décochée : "
            "seul le stack de la marchandise borne l'empilement, et ce qui "
            "dépasse est SIGNALÉ — ici, et sur le plan par le calque des "
            "hauteurs.")
        self.chk_hauteur.toggled.connect(self._contraintes_changees)
        lc.addWidget(self.chk_hauteur)
        self.lbl_contraintes = QLabel("")
        self.lbl_contraintes.setWordWrap(True)
        self.lbl_contraintes.setStyleSheet(
            f"color: {theme.WARN}; font-weight: bold;")
        self.lbl_contraintes.setVisible(False)
        lc.addWidget(self.lbl_contraintes)

        form3 = QFormLayout()
        form3.setContentsMargins(0, 0, 0, 0)
        self.cb_vertical = QComboBox()
        for libelle, valeur in (
                ("Automatique", AUTO),
                ("Ponts bas (meilleur GM)", BAS),
                ("Ponts hauts (débarquement plus facile)", HAUT)):
            self.cb_vertical.addItem(libelle, valeur)
        self.cb_vertical.setToolTip(
            "À capacité et assiette équivalentes, quelle cale servir "
            "d'abord ? « Ponts bas » descend les charges — le GM y gagne et "
            "le navire est plus raide ; « Ponts hauts » les monte — moins de "
            "manutention en cale au déchargement. C'est un départage, jamais "
            "une contrainte : aucun colis n'est perdu pour cela, la cale "
            "suivante est servie dès que la préférée est pleine.")
        form3.addRow("Ponts servis d'abord", self.cb_vertical)
        lc.addLayout(form3)

        note = QLabel(
            "Carène ne modélise pas l'accès : le plan proposé peut demander "
            "de déplacer un colis pour en sortir un autre qui est derrière. "
            "Seul l'empilement est tenu.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        lc.addWidget(note)
        lc.addStretch(1)
        familles.addWidget(cc, 1)

        root.addLayout(familles)

        # Les tests répondent à la confirmation sans fenêtre : ils remplacent
        # cette fonction par `lambda n: True`.
        self.confirmer_retrait = self._demander_retrait
        self.chk_viser.toggled.connect(self._viser_change)
        self._viser_change()
        # Les réglages du dernier passage, gardés hors du dossier du navire :
        # ce sont des réglages de travail, pas des données du bord.
        self._relire_reglages()

        # --- ce qu'on répartit, et où ------------------------------------
        choix = QHBoxLayout()
        choix.setSpacing(10)
        c1 = QFrame(); c1.setObjectName("card")
        l1 = QVBoxLayout(c1); l1.setContentsMargins(12, 10, 12, 12)
        t1 = QLabel("Lots à répartir"); t1.setObjectName("cardTitle")
        l1.addWidget(t1)
        self.list_lots = QListWidget()
        self.list_lots.setMaximumHeight(110)
        l1.addWidget(self.list_lots)
        r1 = QHBoxLayout()
        b_t1 = QPushButton("Tout"); b_t1.setProperty("ghost", "1")
        b_t1.clicked.connect(lambda: self._cocher(self.list_lots, True))
        b_r1 = QPushButton("Aucun"); b_r1.setProperty("ghost", "1")
        b_r1.clicked.connect(lambda: self._cocher(self.list_lots, False))
        r1.addWidget(b_t1); r1.addWidget(b_r1); r1.addStretch(1)
        l1.addLayout(r1)
        choix.addWidget(c1, 1)

        c2 = QFrame(); c2.setObjectName("card")
        l2 = QVBoxLayout(c2); l2.setContentsMargins(12, 10, 12, 12)
        t2 = QLabel("Cales à garnir"); t2.setObjectName("cardTitle")
        l2.addWidget(t2)
        self.list_cales = QListWidget()
        self.list_cales.setMaximumHeight(110)
        l2.addWidget(self.list_cales)
        r2 = QHBoxLayout()
        b_t2 = QPushButton("Toutes"); b_t2.setProperty("ghost", "1")
        b_t2.clicked.connect(lambda: self._cocher(self.list_cales, True))
        b_r2 = QPushButton("Aucune"); b_r2.setProperty("ghost", "1")
        b_r2.clicked.connect(lambda: self._cocher(self.list_cales, False))
        r2.addWidget(b_t2); r2.addWidget(b_r2); r2.addStretch(1)
        l2.addLayout(r2)
        choix.addWidget(c2, 1)
        root.addLayout(choix)
        self._remplir_choix()

        self.zone = QScrollArea()
        self.zone.setWidgetResizable(True)
        self.zone.setFrameShape(QFrame.Shape.NoFrame)
        self.zone.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        self.compte = QVBoxLayout(inner)
        self.compte.setContentsMargins(0, 0, 0, 0)
        self.compte.setSpacing(6)
        self.zone.setWidget(inner)
        root.addWidget(self.zone, 1)

        row = QHBoxLayout()
        self.btn_run = QPushButton("Répartir")
        self.btn_run.setProperty("accent", "1")
        self.btn_run.clicked.connect(self.run)
        self.btn_apply = QPushButton("Appliquer ce plan")
        self.btn_apply.setProperty("accent", "1")
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self.accept)
        b_close = QPushButton("Fermer")
        b_close.clicked.connect(self.reject)
        row.addWidget(self.btn_run)
        row.addStretch(1)
        row.addWidget(b_close)
        row.addWidget(self.btn_apply)
        root.addLayout(row)

        self._dire("Réglez les trois cartes — ce qu'on cherche, ce qu'on "
                   "s'autorise, ce qu'on respecte — puis cliquez "
                   "« Répartir ».", "hint")

    def ouvrir_aide(self):
        """Le « ? » et `F1` : l'aide, droit sur la page du répartiteur."""
        from .aide_dialog import ouvrir_aide
        return ouvrir_aide(self.win, "repartiteur.md")

    # -------------------------------------------------------- les cartes
    @staticmethod
    def _carte(titre):
        """Une carte titrée, et le layout où poser ses réglages.

        Les trois familles ont exactement la même façure : une carte qui
        ressemble à une autre est une carte qu'on lit sans y penser."""
        c = QFrame()
        c.setObjectName("card")
        lay = QVBoxLayout(c)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(6)
        t = QLabel(titre)
        t.setObjectName("cardTitle")
        lay.addWidget(t)
        return c, lay

    # Ce que chaque bouton de réglage rapide coche. Écrit en toutes lettres :
    # un bouton qui pose une combinaison qu'on ne peut pas lire ailleurs est
    # un bouton magique, et on ne fait pas confiance à la magie sur un quai.
    RAPIDES = {
        # Tout ce qui entre. L'assiette et la gîte restent cochées : elles ne
        # coûtent aucun colis en priorité capacité, elles départagent.
        "au_plus": dict(objectif=CAPACITE, viser_assiette=True,
                        equilibrer_tcg=True, empiler=True, rotation=True,
                        disposition=AUTO, melanger_lots=True,
                        respecter_cale_imposee=True, respecter_escales=False,
                        priorite_verticale=AUTO),
        # Le chargement qu'on tient au quai : un lot par cale, l'ordre des
        # escales, les ponts bas. On remplit moins, et on l'assume.
        "soigne": dict(objectif=CAPACITE, viser_assiette=True,
                       equilibrer_tcg=True, empiler=True, rotation=True,
                       disposition=AUTO, melanger_lots=False,
                       respecter_cale_imposee=True, respecter_escales=True,
                       priorite_verticale=BAS),
        # L'assiette d'abord, le reste suit.
        "assiette": dict(objectif=ASSIETTE_GM, viser_assiette=True,
                         equilibrer_tcg=True, empiler=True, rotation=True,
                         disposition=AUTO, melanger_lots=True,
                         respecter_cale_imposee=True, respecter_escales=False,
                         priorite_verticale=AUTO),
    }

    def _reglage_rapide(self, cle):
        """Coche la combinaison du bouton — sans rien lancer : le bord relit,
        corrige ce qu'il veut, puis répartit."""
        d = self.RAPIDES.get(cle)
        if not d:
            return
        self.rb_capacite.setChecked(d["objectif"] == CAPACITE)
        self.rb_assiette.setChecked(d["objectif"] == ASSIETTE_GM)
        self.chk_viser.setChecked(d["viser_assiette"])
        self.chk_gite.setChecked(d["equilibrer_tcg"])
        self.chk_empiler.setChecked(d["empiler"])
        self.chk_rotation.setChecked(d["rotation"])
        self.cb_disposition.setCurrentIndex(
            max(0, self.cb_disposition.findData(d["disposition"])))
        self.chk_melanger.setChecked(d["melanger_lots"])
        self.chk_imposee.setChecked(d["respecter_cale_imposee"])
        self.chk_escales.setChecked(d["respecter_escales"])
        self.cb_vertical.setCurrentIndex(
            max(0, self.cb_vertical.findData(d["priorite_verticale"])))
        self._viser_change()

    def _viser_change(self):
        """Sans assiette visée, il n'y a plus de cible à tenir : le champ de
        l'assiette et la priorité « tenir l'assiette » n'ont plus d'objet. On
        les grise en disant pourquoi, plutôt que de laisser le bord choisir
        une priorité qui ne commanderait rien."""
        vise = self.chk_viser.isChecked()
        self.sp_trim.setEnabled(vise)
        self.rb_assiette.setEnabled(vise)
        if not vise:
            self.rb_capacite.setChecked(True)
            self.rb_assiette.setToolTip(
                "Sans objet : « Viser une assiette » est décochée, il n'y a "
                "aucune assiette à tenir. Recochez-la pour rendre ce choix "
                "possible.")
        else:
            self.rb_assiette.setToolTip(
                "Le solveur calcule le LCG que la cargaison doit avoir pour "
                "tomber sur l'assiette demandée et répartit pour l'approcher, "
                "en descendant les lourdes. Une cale peut rester à moitié vide "
                "si la remplir écartait le navire de la cible.")

    # ------------------------------------------------ réglages qui se retiennent
    def _contraintes_changees(self, *_a):
        """Le rappel orange : ce qui est débrayé, en toutes lettres."""
        debrayees = []
        if not self.chk_charge.isChecked():
            debrayees.append("la charge de pont admissible")
        if not self.chk_hauteur.isChecked():
            debrayees.append("la hauteur libre")
        if debrayees:
            self.lbl_contraintes.setText(
                "⚠ Débrayé : " + " et ".join(debrayees) + ". Le plan pourra "
                "les dépasser ; les dépassements seront signalés dans le "
                "compte rendu et sur le plan, pas refusés. Le verdict de "
                "stabilité n'en sait rien : c'est à vous de juger.")
        self.lbl_contraintes.setVisible(bool(debrayees))

    def contraintes_debrayees(self):
        """Les contraintes décochées, pour qui veut le savoir (tests, rapport)."""
        return {c for c, case in (("charge", self.chk_charge),
                                  ("hauteur", self.chk_hauteur))
                if not case.isChecked()}

    def _etat_des_reglages(self):
        """Les cases telles qu'elles sont, sous forme de dictionnaire —
        c'est ce qui part dans `carene.config.json`."""
        return {
            "objectif": (ASSIETTE_GM if self.rb_assiette.isChecked()
                         else CAPACITE),
            "viser_assiette": self.chk_viser.isChecked(),
            "assiette_cible_m": self.sp_trim.value(),
            "equilibrer_tcg": self.chk_gite.isChecked(),
            "tcg_cible_m": self.sp_tcg.value(),
            "empiler": self.chk_empiler.isChecked(),
            "rotation_permise": self.chk_rotation.isChecked(),
            "disposition": self.cb_disposition.currentData(),
            "melanger_lots": self.chk_melanger.isChecked(),
            "respecter_cale_imposee": self.chk_imposee.isChecked(),
            "respecter_escales": self.chk_escales.isChecked(),
            "priorite_verticale": self.cb_vertical.currentData(),
            "vider": self.chk_vider.isChecked(),
            # les contraintes débrayées ne se retiennent PAS d'un passage à
            # l'autre (D-71) : débrayer se décide à chaque fois, exprès
        }

    def _relire_reglages(self):
        """Repose les cases du dernier passage. Une valeur absente ou
        inconnue laisse la case d'usine : un fichier écrit par une autre
        version ne doit jamais empêcher la fenêtre de s'ouvrir."""
        d = app_paths.reglages_solveur()
        if not d:
            return
        try:
            if "objectif" in d:
                self.rb_assiette.setChecked(d["objectif"] == ASSIETTE_GM)
                self.rb_capacite.setChecked(d["objectif"] != ASSIETTE_GM)
            for cle, case in (("viser_assiette", self.chk_viser),
                              ("equilibrer_tcg", self.chk_gite),
                              ("empiler", self.chk_empiler),
                              ("rotation_permise", self.chk_rotation),
                              ("melanger_lots", self.chk_melanger),
                              ("respecter_cale_imposee", self.chk_imposee),
                              ("respecter_escales", self.chk_escales),
                              ("vider", self.chk_vider)):
                if cle in d:
                    case.setChecked(bool(d[cle]))
            if "assiette_cible_m" in d:
                self.sp_trim.setValue(float(d["assiette_cible_m"]))
            if "tcg_cible_m" in d:
                self.sp_tcg.setValue(float(d["tcg_cible_m"]))
            for cle, combo in (("disposition", self.cb_disposition),
                               ("priorite_verticale", self.cb_vertical)):
                i = combo.findData(d.get(cle))
                if i >= 0:
                    combo.setCurrentIndex(i)
        except (TypeError, ValueError):
            pass                  # configuration abîmée : les valeurs d'usine
        self._viser_change()

    # --------------------------------------------------------------- choix
    def _remplir_choix(self):
        """Les lots du manifeste et les cales du navire, tous cochés d'office :
        le cas courant est « tout, partout », et l'on décoche ce qu'on veut
        garder en main."""
        from .manifest_panel import _pastille
        from .core.cargo_model import couleur_hex
        cond = self.win.condition
        restes = cond.places_par_ligne()
        self.list_lots.clear()
        for i, m in enumerate(cond.manifeste):
            # le matériel du bord n'est plus au manifeste ; une ligne
            # « du bord » d'un fichier non encore migré n'y a rien à faire
            if getattr(m, "hors_manifeste", False):
                continue
            reste = max(0, m.quantite - restes[i])
            item = QListWidgetItem(f"{m.nom} — {m.quantite} prévus, reste {reste}")
            item.setIcon(_pastille(couleur_hex(m)))
            item.setData(Qt.ItemDataRole.UserRole, m.lot_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if reste > 0
                               else Qt.CheckState.Unchecked)
            self.list_lots.addItem(item)
        self.list_cales.clear()
        for deck in self.win.project.sorted_decks():
            for cap in deck.capacities:
                if cap.kind == KIND_CONTOUR or len(cap.points) < 3:
                    continue
                item = QListWidgetItem(f"{cap.code} · {cap.name or deck.name}")
                item.setData(Qt.ItemDataRole.UserRole, cap.code)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                cochee = (self.cales_imposees is None
                          or cap.code in self.cales_imposees)
                item.setCheckState(Qt.CheckState.Checked if cochee
                                   else Qt.CheckState.Unchecked)
                self.list_cales.addItem(item)

    @staticmethod
    def _cocher(liste, actif):
        etat = Qt.CheckState.Checked if actif else Qt.CheckState.Unchecked
        for i in range(liste.count()):
            liste.item(i).setCheckState(etat)

    @staticmethod
    def _coches(liste):
        return {liste.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(liste.count())
                if liste.item(i).checkState() == Qt.CheckState.Checked}

    # ------------------------------------------------------------- affichage
    def _vider(self):
        while self.compte.count():
            item = self.compte.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _dire(self, texte, style="", gras=False):
        lbl = QLabel(texte)
        lbl.setWordWrap(True)
        if style == "hint":
            lbl.setObjectName("hint")
        elif style:
            lbl.setStyleSheet(f"color: {style};"
                              + (" font-weight: bold;" if gras else ""))
        elif gras:
            lbl.setStyleSheet("font-weight: bold;")
        self.compte.addWidget(lbl)
        return lbl

    # ------------------------------------------------------------- exécution
    def run(self):
        win = self.win
        cond = win.condition
        self._vider()
        holds = holds_du_navire(
            win.project, getattr(cond, "epontilles_en_place", ()) or ())
        if not holds:
            self._dire("Aucune cale tracée : dessinez les capacités dans "
                       "l'éditeur de plans.", theme.WARN)
            return
        lots = self._coches(self.list_lots)
        lignes = [m for m in cond.lignes_a_embarquer()
                  if m.quantite > 0 and m.lot_id in lots]
        if not lignes:
            self._dire("Aucun lot à répartir : cochez ce que vous voulez faire "
                       "placer dans la liste « Lots à répartir ».", theme.WARN)
            return
        cales = self._coches(self.list_cales)
        holds = [h for h in holds if h.code in cales]
        if not holds:
            self._dire("Aucune cale cochée : choisissez où répartir.", theme.WARN)
            return

        # Ce qui est posé dans une cale NON cochée reste tel quel : le solveur
        # n'y touche pas, et le rapport n'a pas à le rendre. De même pour le
        # matériel du bord et pour les lots NON cochés : « repartir des cales
        # vides » ne vide que ce qu'on redistribue, sinon un lot décoché
        # (souvent parce qu'il est déjà tout posé) disparaîtrait du plan.
        #
        # Le **matériel du bord** est gardé quoi qu'il arrive : le chariot
        # élévateur est arrimé là où le bord l'a mis, c'est un obstacle à
        # contourner exactement comme une charge épinglée — le solveur ne le
        # déplace jamais et n'empile rien dessus.
        lots_gardes = {m.lot_id for m in cond.manifeste
                       if getattr(m, "hors_manifeste", False)
                       or m.lot_id not in lots}
        chk_vider = self.chk_vider.isChecked()
        epingles = {}
        for code, lst in cond.placements.items():
            if code not in cales:
                continue
            garde = [p for p in lst if p.epingle or p.est_materiel_bord
                     or p.lot_id in lots_gardes] \
                if chk_vider else list(lst)
            # des COPIES : le solveur empile sur ce qu'il garde (niveaux + 1).
            # Sur les colis du point eux-mêmes, un calcul qu'on annule
            # laissait des niveaux fantômes — 2 colis de 1 t devenus 6 t.
            garde = [copy.deepcopy(p) for p in garde]
            if garde:
                epingles[code] = garde
        retires = sum(len(lst) - len(epingles.get(code, []))
                      for code, lst in cond.placements.items() if code in cales)
        if retires and not self.confirmer_retrait(retires):
            self._dire("Rien n'a été retiré : décochez « Repartir des cales "
                       "vides » pour compléter ce qui est posé.", theme.WARN)
            return

        # Le solveur ne reçoit que le RESTE de chaque lot : ce qui est gardé
        # dans les cales garnies et ce qui est posé ailleurs compte déjà.
        # Lui passer la quantité entière, c'est dépasser le manifeste.
        lignes = lignes_restantes(lignes, cond, epingles, cales)
        if not lignes:
            self._dire("Tout est déjà posé pour les lots cochés : rien à "
                       "répartir. Retirez des colis du plan, ou cochez les "
                       "cales où ils sont, pour les reposer.", theme.WARN)
            return

        from .cargo_panel import jeu_arrimage
        reglages = Reglages(
            # --- A · ce qu'on cherche
            objectif=ASSIETTE_GM if self.rb_assiette.isChecked() else CAPACITE,
            viser_assiette=self.chk_viser.isChecked(),
            assiette_cible_m=self.sp_trim.value(),
            equilibrer_tcg=self.chk_gite.isChecked(),
            tcg_cible_m=self.sp_tcg.value(),
            # --- B · ce qu'on s'autorise
            empiler=self.chk_empiler.isChecked(),
            rotation_permise=None if self.chk_rotation.isChecked() else False,
            disposition=self.cb_disposition.currentData(),
            melanger_lots=self.chk_melanger.isChecked(),
            respecter_cale_imposee=self.chk_imposee.isChecked(),
            # --- C · ce qu'on respecte
            respecter_escales=self.chk_escales.isChecked(),
            priorite_verticale=self.cb_vertical.currentData(),
            respecter_charge_pont=self.chk_charge.isChecked(),
            respecter_hauteur_libre=self.chk_hauteur.isChecked(),
            # Le JEU D'ARRIMAGE réglé à la molette de la vue Chargement vaut
            # aussi ici : les trois chemins de calepinage — répartiteur, plan
            # de cale, outil Zone — doivent poser pareil, sinon le bord
            # compare deux plans sans pouvoir dire pourquoi ils diffèrent
            # (D-39). Molette à zéro, on retombe sur la marge d'usine — dite
            # en DÉBORDEMENT par colis, comme la molette (D-64) : c'est
            # `DEBORD_JEU_M`, la moitié de l'écart d'usine `JEU_M`.
            jeu_m=max(jeu_arrimage(win), DEBORD_JEU_M))
        self._reglages = reglages
        # Le plan de cale relit ces réglages pour son bouton « Remplir » : le
        # même moteur doit poser la même chose des deux côtés, sinon le bord
        # se retrouve devant deux plans différents sans savoir pourquoi.
        win.derniers_reglages_solveur = reglages
        # ... et le lancement suivant les retrouve : le bord ne recoche pas
        # douze cases à chaque escale. Réglages de TRAVAIL, donc dans la
        # configuration de l'application, jamais dans le dossier du navire.
        app_paths.set_reglages_solveur(self._etat_des_reglages())

        # L'ordre des escales vient de la ligne du navire (`ports.json`), lue
        # comme partout ailleurs. Le solveur ne le devine pas : sans liste, le
        # réglage « ordre des escales » ne dit simplement rien.
        from . import ports as _ports
        ordre_escales = [pt.nom for pt in _ports.liste_du_bord(win)]

        # poids et moments (longitudinal ET transversal) de tout ce qui
        # n'est pas la cargaison des cales : le lège, les caisses, le
        # matériel. Sans le moment transversal, le solveur visait un TCG de
        # cargaison nul sur un navire qui penchait déjà — et chargeait « du
        # mauvais côté » (retour du bord, v2.15.2).
        poids_hors, moment_hors, moment_t_hors = hors_cargaison(win, cond, cales)

        self.rapport = stowage.resoudre(
            holds, lignes, reglages, epingles=epingles,
            navire=win.nav, poids_hors_cargaison_t=poids_hors,
            moment_hors_cargaison_tm=moment_hors,
            moment_t_hors_cargaison_tm=moment_t_hors,
            ordre_escales=ordre_escales)
        self._rendre(self.rapport, holds)
        self.btn_apply.setEnabled(self.rapport.nb_places > 0)

    def _demander_retrait(self, n):
        """Avant de balayer des colis posés à la main : on le dit, on demande."""
        rep = QMessageBox.question(
            self, "Repartir des cales vides",
            f"{n} colis déjà posé(s) dans les cales cochées seront retirés du "
            "plan avant la répartition (les colis épinglés et le matériel du "
            "bord restent). Continuer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        return rep == QMessageBox.StandardButton.Yes

    def _rendre(self, rap, holds):
        self._vider()
        w, lcg, tcg, vcg, n = stowage.totaux(rap.places, holds)
        self._dire(f"{rap.nb_places} charge(s) placée(s) · {w:.1f} t", gras=True)
        # Le TCG se lit à côté du LCG : c'est ce qui fait la gîte. On annonce
        # le TCG et non des degrés — le solveur n'a pas le GM (D-38), et la
        # gîte réelle s'affiche au bandeau dès le plan appliqué.
        tcg_prevu = rap.tcg_prevu_m if rap.tcg_prevu_m is not None else tcg
        self._dire(f"Cargaison : LCG {lcg:.2f} m · TCG {tcg_prevu:+.2f} m · "
                   f"VCG {vcg:.2f} m", "hint")
        if self.chk_gite.isChecked():
            # la même zone morte que le solveur : ce qu'il tient pour atteint,
            # le compte rendu ne doit pas le donner pour raté. Ce qui compte,
            # c'est le TCG du NAVIRE — cargaison et tout le reste
            reg = getattr(self, "_reglages", None) or Reglages()
            navire_tcg = (rap.tcg_navire_prevu_m
                          if rap.tcg_navire_prevu_m is not None else tcg_prevu)
            reste = navire_tcg - reg.tcg_cible_m
            if abs(reste) > reg.tolerance_tcg_m:
                self._dire(
                    f"TCG du navire prévu {navire_tcg:+.2f} m : il reste "
                    f"{reste:+.2f} m à compenser — le manifeste est "
                    "dissymétrique. Le bandeau donnera la gîte réelle ; "
                    "corrigez au ballast ou en déplaçant une pièce lourde.",
                    theme.WARN)
            else:
                self._dire(f"TCG du navire prévu {navire_tcg:+.2f} m : bâbord "
                           "et tribord s'équilibrent, gîte visée tenue.",
                           theme.OK)

        if rap.assiette_prevue_m is not None:
            ok = rap.dans_domaine
            self._dire(
                f"Assiette prévue : {rap.assiette_prevue_m:+.2f} m"
                + ("" if ok else "  —  HORS DOMAINE DES TABLES"),
                theme.OK if ok else theme.DANGER, gras=True)

        for m in rap.messages:
            self._dire("• " + m, "hint")

        # CE QUE LE PLAN DÉPASSE, contrainte débrayée (D-71) : en orange et
        # en gras, avant même les non-placés — c'est ce qu'on a choisi de
        # laisser passer, il faut le lire avant d'appliquer
        if getattr(rap, "avertissements", None):
            self._dire("⚠ Contraintes débrayées — ce que le plan dépasse",
                       theme.WARN, gras=True)
            for m in rap.avertissements:
                self._dire(f"   {m}", theme.WARN)
            self._dire("   Ces dépassements restent signalés sur le plan de "
                       "chargement (calques des charges et des hauteurs).",
                       "hint")

        if rap.non_places:
            self._dire("Non placé — et pourquoi, cale par cale", theme.WARN, gras=True)
            for nom, qte, why in rap.non_places:
                self._dire(f"   {qte}× {nom}", theme.WARN)
                # un motif par ligne : « 3030, 3040 : charge locale … ».
                # Un motif SANS cale, c'est un réglage : il vient en tête et
                # se lit en gras — c'est celui-là qu'on peut décocher.
                for motif in why.split(" ; "):
                    reglage = " : " not in motif
                    self._dire(f"        {motif}", theme.WARN, gras=reglage)
            if any("charge locale" in why or "charge moyenne" in why
                   for _n, _q, why in rap.non_places):
                self._dire("   Une cale vide qui refuse « pour la charge » ne "
                           "manque pas de place : le colis est trop lourd pour "
                           "ce pont. Allégez le lot au poids indiqué, ou "
                           "réservez-le aux cales qui l'acceptent.", "hint")
        else:
            self._dire("Tout le manifeste est placé.", theme.OK)
        self._dire("Répartition par cale", gras=True)
        for h in holds:
            lst = rap.places.get(h.code, [])
            poids = sum(p.poids_total_t for p in lst)
            # ce qui est OCCUPÉ, c'est l'encombrement — le taux répond à
            # « que reste-t-il de place ? », et le débord en prend (D-39)
            occupee = sum(p.encombrement[0] * p.encombrement[1] for p in lst)
            taux = (100 * occupee / h.aire_m2) if h.aire_m2 else 0
            # Avec quoi la cale s'est remplie, en toutes lettres. Le bord règle
            # une DISPOSITION et doit pouvoir vérifier ce que le calepineur en
            # a fait — surtout en « automatique », où c'est lui qui choisit.
            dite = getattr(rap, "disposition_par_cale", {}).get(h.code, "")
            self._dire(
                f"   {h.code} : {len(lst)} charge(s) · {poids:.1f} t · "
                f"{taux:.0f} % de la surface"
                + (f" · disposition : {dite}" if dite else ""), "hint")

        # Le compte rendu vient de grandir d'un coup : sans cela, la zone
        # défilante garde la hauteur d'avant jusqu'au prochain passage de la
        # boucle d'événements, et les lignes se chevauchent à l'écran.
        self.compte.addStretch(1)
        self.compte.activate()
        self.zone.widget().adjustSize()

    def values(self):
        return self.rapport
