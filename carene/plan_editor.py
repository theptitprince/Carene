# -*- coding: utf-8 -*-
"""Éditeur de plans : vues (profil et ponts), calage, contours, capacités.

C'est une activité de CRÉATION du navire : cette fenêtre est ouverte depuis la
section « Plans du navire » de la fenêtre de création, pas depuis le poste de
travail quotidien. Elle enregistre la géométrie dans le dossier du navire.

Une **vue** est un plan calé : le profil longitudinal (X–Z) ou un pont (X–Y).
Le fond de plan est une image, une page de PDF vectoriel ou un **DXF** (D-9) ;
dans les deux derniers cas les sommets des traits sont relus et le curseur s'y
**accroche** au calage et au tracé (modules `pdf_plan` et `dxf_plan`, même
façade — voir `scene.source_traits`). Cette lecture se fait **en fil de fond**
(`scene.ChargeurTraits`) : sur le plan d'ensemble elle demande plusieurs
secondes, et la fenêtre ne doit pas s'y figer. Tant qu'elle n'est pas finie
l'accroche est simplement absente, et la barre d'état le dit.

Tout ce qui est tracé ici sert à la vue et aux contrôles de pose, jamais au
calcul de stabilité (D-10).
"""
from __future__ import annotations

import math
import os
import sys

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsView,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import app_paths, catalogue_plans, dxf_plan, pdf_plan, theme
from .dialogs import (
    AnnotationDialog,
    CalPointDialog,
    CapacityDialog,
    CatalogueDialog,
    DeckDialog,
    DxfImportDialog,
    EpontilleDialog,
    HauteurLibreDialog,
    PdfImportDialog,
    TraitsConstructionDialog,
    ZoneChargeDialog,
    ZoneInterditeDialog,
)
from .geometry import Calibration
from .isoview import IsoView
from .items import (COULEUR_ANNOTATION_DEFAUT, NOMS_FORMES_ANNOTATION,
                    AnnotationItem, DeckCapacityItem, EpontilleItem,
                    ObstacleItem, ProfileCapacityItem, VertexHandle,
                    ZoneChargeItem, hauteur_annoncee, nom_zone_hauteur)
from .project import (Calibrated, Capacity, Deck, KIND_CONTOUR, Project,
                      epontille_fixe)
from .scene import (CALQUES, NOMS_CALQUES, SNAP_PX, PlanScene, VuePlanBase,
                    accrocher, chargeur, source_traits)
from .wizard import ShipWizard
from .saisie import SpinNombre

def _vivant(item):
    """L'objet graphique existe-t-il encore côté C++ ?

    Une scène qui se reconstruit détruit ses objets ; une liste Python qui
    les tient encore ne le sait pas, et `setSelected` sur l'un d'eux tombe en
    RuntimeError (« Internal C++ object already deleted »). On demande à
    shiboken avant de toucher."""
    try:
        import shiboken6
        return shiboken6.isValid(item)
    except Exception:
        return item is not None


def _vivants(items):
    return [it for it in items if _vivant(it)]


def _echap_pour_moi(fenetre):
    """La touche Échap appartient-elle à CETTE fenêtre d'éditeur ?

    La même règle que dans la vue Chargement (`cargo_panel._echap_permis`),
    pour la même raison : deux règles qui divergeraient, c'est un « Échap qui
    n'a pas un fonctionnement fiable ». Une fenêtre modale, une liste
    déroulante ouverte et un champ de texte en cours de frappe gardent leur
    touche — Échap y annule quelque chose. Une MOLETTE, non : Échap n'annule
    rien dans un nombre déjà écrit, et la lui laisser, c'est la perdre."""
    from PySide6.QtWidgets import QApplication
    from .cargo_panel import _saisie_de_texte
    if QApplication.activeModalWidget() is not None:
        return False
    if QApplication.activePopupWidget() is not None:
        return False
    try:
        if not fenetre.isVisible():
            return False
    except RuntimeError:              # objet C++ détruit
        return False
    actif = QApplication.activeWindow()
    if actif is not None and actif is not fenetre:
        return False
    return not _saisie_de_texte()


MODE_SELECT = "select"
MODE_CAL = "cal"
MODE_DECKS = "decks"
MODE_POLY = "poly"
MODE_CONTOUR = "contour"
# Poser une ÉPONTILLE AMOVIBLE : un clic dans une cale, et c'est fait. Le
# capitaine les place lui-même — le manuel d'assujettissement dit dans quelles
# cales elles vont et ce qu'elles tiennent (MSL 50 kN), jamais où exactement.
MODE_EPONTILLE = "epontille"
MODE_TRAIT = "trait"           # poser un trait de construction d'un clic

# Les trois CALQUES qu'on pose par-dessus les cales, une fois les contours
# décalqués. Deux contraignent (charge au m², D-12 ; hauteur libre, D-21) sans
# jamais bloquer : ils SIGNALENT. Le troisième — les informations — ne
# contraint rien du tout, personne ne le lit. Ce qui BLOQUE, c'est l'épontille
# fixe et la structure : une zone sans hauteur (MODE_INTERDIT).
MODE_ZONE_CHARGE = "zone_charge"   # polygone dans une cale → cap.zones_charge
MODE_HAUTEUR = "hauteur"           # rectangle → cap.obstacles, AVEC hauteur
MODE_INTERDIT = "interdit"         # rectangle → cap.obstacles, SANS hauteur
MODE_INFO = "info"       # polyligne / polygone / point / texte → annotations

# Les modes qui tracent un polygone sommet par sommet (clics + double-clic).
MODES_POLYGONE = (MODE_POLY, MODE_CONTOUR, MODE_ZONE_CHARGE)
# Ceux qui posent un rectangle par deux clics (coins opposés). Le moteur ne
# sait lire qu'un rectangle aligné sur les axes pour une zone d'obstacle
# (`Capacity.obstacles` = [x0, y0, x1, y1, nom]) : c'est la forme qu'on trace.
MODES_RECTANGLE = (MODE_HAUTEUR, MODE_INTERDIT)
# Les formes du calque d'information qui se tracent sommet par sommet, comme
# un contour de cale : le double-clic les termine (et REFERME le polygone).
# Un point et un texte, eux, se posent d'un seul clic.
FORMES_TRACEES_INFO = ("trait", "polygone")

# le rayon d'accroche (8 px d'écran) vit dans `scene` : la fiche de plan de
# cale s'en sert aussi, et deux valeurs feraient deux accroches différentes
# Court sursis laissé à la lecture des traits avant de rendre la main : un plan
# léger se lit en quelques millisecondes, et l'accroche est alors là dès le
# premier clic. Au-delà — le plan d'ensemble et ses secondes de lecture — on
# rend la main et la lecture finit en tâche de fond. Assez court pour être
# imperceptible, assez long pour couvrir les petits plans.
SURSIS_TRAITS_MS = 60
EDGE_PX = 6.0          # tolérance pour viser une arête (insertion de sommet)
# Tolérance pour viser une POIGNÉE de sommet. Elle vaut la demi-poignée plus
# une marge, et le tir se fait sur la géométrie du polygone plutôt que sur
# `itemAt` : une cale posée par-dessus une autre couvrait sinon les poignées
# de celle du dessous, qui devenaient impossibles à saisir (retour du bord).
VERTEX_PX = 7.5
DRAG_PX = 3.0          # au-delà, un clic devient un glisser
CLIC_PX = 12.0         # au-delà, un clic de tracé est un geste : aucun sommet posé
UNDO_MAX = 60

# Ce qui reste d'une forme tronquée au contour de sa cale doit valoir la peine
# d'être gardé : en dessous, c'est un débord tracé de travers, pas une zone —
# et une zone de 2 cm² dans le fichier du navire n'aiderait personne.
AIRE_MINI_ZONE_M2 = 0.05

# Largeur de la colonne de droite et hauteur de la vignette « vue navire ».
# Le décalquage se fait sur le plan : tout le reste se serre pour lui laisser
# la place (souhait du bord, v29).
COLONNE_PX = 264
ISO_PX = 220
PROFIL_PX = 210

# Réglages de mise en page gardés pour la SESSION (pas dans le fichier navire :
# ce n'est pas une donnée du navire, et deux postes ne travaillent pas pareil).
_ETAT_SESSION = {}

# DXF, PDF ou image (D-9). Le DWG figure dans la liste **pour être refusé en
# toutes lettres** : le choisir explique quoi faire plutôt que de laisser
# chercher pourquoi il n'apparaît pas.
FILTRE_PLANS = ("Plans (*.dxf *.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff);;"
                "DXF (*.dxf);;PDF (*.pdf);;"
                "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;"
                "DWG — à convertir en DXF au préalable (*.dwg)")
MESSAGE_DWG = (
    "Carène lit le <b>DXF</b>, le <b>PDF</b> ou une <b>image</b> — pas le DWG "
    "(décision D-9).<br><br>Convertissez d'abord votre DWG en DXF avec "
    "<b>ODA File Converter</b>, gratuit :<br>"
    "https://www.opendesign.com/guestfiles/oda_file_converter<br><br>"
    "puis réimportez le DXF obtenu. Aucun lecteur DWG n'est embarqué et rien "
    "n'est lancé sur la machine : un lecteur DWG libre passe certaines "
    "entités en silence, et une cloison manquante, c'est une cale décalquée "
    "trop grande.")


def _real(cal, p: QPointF):
    x, y = cal.to_real(p.x(), p.y())
    return (round(float(x), 4), round(float(y), 4))


class PlanGraphicsView(VuePlanBase):
    """Vue de décalquage : zoom molette au curseur, pan au bouton du milieu ou
    Espace+glisser, panneaux flottants posés dans les coins.

    Le zoom, le déplacement et l'échelle d'écran viennent de `VuePlanBase`,
    partagée avec la fiche de plan de cale.

    La souris est confiée à la fenêtre (`controller`), seule à connaître le
    mode, l'accroche et la sélection — un événement qu'elle consomme ne va pas
    à la scène. Le pan, lui, est traité ICI et avant tout le reste : un geste
    de déplacement ne doit jamais poser un sommet.
    """

    activated = Signal()

    def __init__(self, scene, name, controller=None, parent=None):
        super().__init__(scene, parent)
        self.name = name
        self.controller = controller
        self.setRenderHints(QPainter.RenderHint.Antialiasing
                            | QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._space = False          # barre d'espace maintenue : pan au clic gauche
        self._overlays = []          # [(widget, coin)] posés sur la vue

    # ---------------------------------------------------------- panneaux posés
    def add_overlay(self, widget, coin="haut-gauche", marge=10):
        """Pose un panneau flottant dans un coin de la vue (aide au tracé,
        calques) : il suit la vue, il ne prend pas de place à côté d'elle."""
        widget.setParent(self)
        widget.raise_()
        self._overlays.append((widget, coin, marge))
        self._place_overlays()
        return widget

    def _place_overlays(self):
        w, h = self.width(), self.height()
        for widget, coin, m in self._overlays:
            if widget.isHidden():
                continue
            widget.adjustSize()
            r = widget.size()
            x = m if "gauche" in coin else max(m, w - r.width() - m)
            y = m if "haut" in coin else max(m, h - r.height() - m)
            widget.move(int(x), int(y))
            widget.raise_()

    def refresh_overlays(self):
        self._place_overlays()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_overlays()

    # ---------------------------------------------------------- zoom et pan
    # `view_scale`, `scene_pos`, `wheelEvent`, `panning` et `_pan_move` sont
    # dans `scene.VuePlanBase` — partagés avec la fiche de plan de cale.
    def _start_pan(self, event):
        self._panning = True
        self._pan_start = event.position()
        self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        if self.controller is not None:
            self.controller.pan_started(self)
        event.accept()

    def _stop_pan(self, event=None):
        self._panning = False
        self.viewport().setCursor(
            Qt.CursorShape.OpenHandCursor if self._space
            else self.controller.cursor_for_mode() if self.controller is not None
            else Qt.CursorShape.ArrowCursor)
        if event is not None:
            event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space = True
            if not self._panning:
                self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space = False
            if not self._panning:
                self._stop_pan()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        # la barre d'espace « relâchée » pendant qu'on est ailleurs resterait
        # sinon enfoncée pour toujours
        self._space = False
        super().focusOutEvent(event)

    # ---------------------------------------------------------- souris
    def mousePressEvent(self, event):
        self.activated.emit()
        if event.button() == Qt.MouseButton.MiddleButton or (
                self._space and event.button() == Qt.MouseButton.LeftButton):
            self._start_pan(event)
            return
        if self.controller is not None and self.controller.view_press(self, event):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan_move(event):
            return
        if self.controller is not None and self.controller.view_move(self, event):
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning and event.button() in (Qt.MouseButton.MiddleButton,
                                                Qt.MouseButton.LeftButton):
            self._stop_pan(event)
            return
        if self.controller is not None and self.controller.view_release(self, event):
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.controller is not None \
                and self.controller.view_double_click(self, event):
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        """Clic droit : le menu de l'objet visé.

        C'est ce que le bord n'a pas trouvé — supprimer une épontille n'était
        possible que par un bouton caché dans un panneau replié, ou par la
        touche Suppr, qu'il faut connaître."""
        if self.controller is not None and \
                self.controller.view_context_menu(self, event):
            event.accept()
            return
        super().contextMenuEvent(event)

    def leaveEvent(self, event):
        if self.controller is not None:
            self.controller.view_leave(self)
        super().leaveEvent(event)


class Section(QWidget):
    """Bloc repliable de la colonne de droite : un bandeau cliquable, un corps.

    Replié, il ne prend plus que la hauteur de son bandeau — et le bandeau
    reste là : on retrouve toujours le chemin du retour."""

    toggled = Signal(bool)

    def __init__(self, titre, corps, replie=False, hauteur=0, fixe=True,
                 parent=None):
        super().__init__(parent)
        self.corps = corps
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.bouton = QToolButton()
        self.bouton.setObjectName("sectionHead")
        self.bouton.setText(titre)
        self.bouton.setCheckable(True)
        self.bouton.setChecked(not replie)
        self.bouton.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.bouton.setArrowType(Qt.ArrowType.DownArrow if not replie
                                 else Qt.ArrowType.RightArrow)
        self.bouton.setSizePolicy(QSizePolicy.Policy.Expanding,
                                  QSizePolicy.Policy.Fixed)
        self.bouton.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bouton.setStyleSheet(
            f"QToolButton#sectionHead {{ background: {theme.SURFACE_2};"
            f" color: {theme.TEXT_DIM}; border: none;"
            f" border-top: 1px solid {theme.BORDER_SOFT};"
            f" padding: 4px 8px; font-size: 10px; font-weight: bold;"
            f" letter-spacing: 1px; text-align: left; }}"
            f"QToolButton#sectionHead:hover {{ background: {theme.HOVER};"
            f" color: {theme.TEXT}; }}")
        self.bouton.clicked.connect(lambda on: self.set_open(on))
        lay.addWidget(self.bouton)
        if hauteur:
            corps.setMinimumHeight(hauteur if fixe else 0)
            corps.setMaximumHeight(hauteur)
        lay.addWidget(corps, 1)
        corps.setVisible(not replie)

    def set_open(self, on: bool):
        on = bool(on)
        self.corps.setVisible(on)
        self.bouton.setChecked(on)
        self.bouton.setArrowType(Qt.ArrowType.DownArrow if on
                                 else Qt.ArrowType.RightArrow)
        self.toggled.emit(on)

    def is_open(self) -> bool:
        # isVisible() est faux tant que la fenêtre n'est pas affichée : c'est
        # isHidden() qui dit ce qui a été demandé, avant comme après.
        return not self.corps.isHidden()


def _style_panneau() -> str:
    """Feuille de style d'un panneau posé sur un plan : lisible sans cacher le
    dessin — fond opaque mais compact, bord discret."""
    bg = QColor(theme.MARKER_BG)
    fond = f"rgba({bg.red()}, {bg.green()}, {bg.blue()}, {bg.alpha() / 255:.2f})"
    return f"""
QFrame#overlayPanel {{
    background: {fond};
    border: 1px solid {theme.BORDER};
    border-radius: 7px;
}}
QFrame#overlayPanel QLabel {{ background: transparent; color: {theme.TEXT_DIM}; }}
QFrame#overlayPanel QLabel#overlayTitle {{
    color: {theme.ACCENT_DARK}; font-weight: bold;
}}
QFrame#overlayPanel QLabel#overlayKeys {{ color: {theme.TEXT_FAINT}; }}
QFrame#overlayPanel QCheckBox {{ background: transparent; color: {theme.TEXT_DIM}; }}
"""


class TraceOverlay(QFrame):
    """L'aide au tracé, posée dans le coin du plan.

    Elle dit ce qu'on trace, combien de sommets sont posés, si l'accroche
    mord, et les quatre touches qui servent — pour ne pas aller chercher un
    bouton pendant qu'on décalque."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("overlayPanel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(11, 8, 12, 9)
        lay.setSpacing(2)
        self.titre = QLabel("")
        self.titre.setObjectName("overlayTitle")
        self.compte = QLabel("")
        self.accroche = QLabel("")
        self.touches = QLabel(
            "Double-clic ou Entrée : fermer le tracé<br>"
            "Retour arrière : retirer le dernier sommet<br>"
            "Échap : abandonner &nbsp;·&nbsp; Maj : suspendre l'accroche<br>"
            "Espace + glisser ou bouton du milieu : déplacer la vue")
        self.touches.setObjectName("overlayKeys")
        self.touches.setTextFormat(Qt.TextFormat.RichText)
        for w in (self.titre, self.compte, self.accroche, self.touches):
            lay.addWidget(w)
        self.restyle()
        self.hide()

    def restyle(self):
        self.setStyleSheet(_style_panneau())

    def set_trace(self, titre, n_sommets, accroche):
        self.titre.setText(titre)
        self.compte.setText(
            "aucun sommet posé — cliquez le premier" if n_sommets == 0
            else f"{n_sommets} sommet(s) posé(s)")
        self.accroche.setText(accroche)
        self.adjustSize()


class LayersOverlay(QFrame):
    """Les calques du plan, posés sur le plan.

    Décalquer un contour sur un plan de chantier chargé demande de pouvoir
    éteindre ce qui gêne : le fond, les cales déjà tracées, les zones de
    charge, les zones interdites, la grille."""

    changed = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("overlayPanel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(11, 8, 12, 9)
        lay.setSpacing(2)
        titre = QLabel("CALQUES")
        titre.setObjectName("overlayTitle")
        lay.addWidget(titre)
        self.boxes = {}
        for nom in CALQUES:
            box = QCheckBox(NOMS_CALQUES[nom])
            box.setChecked(True)
            box.toggled.connect(lambda on, k=nom: self.changed.emit(k, on))
            lay.addWidget(box)
            self.boxes[nom] = box
        self.restyle()

    def restyle(self):
        self.setStyleSheet(_style_panneau())

    def set_checked(self, nom, on):
        box = self.boxes.get(nom)
        if box is None or box.isChecked() == bool(on):
            return
        box.blockSignals(True)
        box.setChecked(bool(on))
        box.blockSignals(False)

    def etat(self):
        return {k: b.isChecked() for k, b in self.boxes.items()}


class PlanEditorWindow(QMainWindow):

    geometry_saved = Signal()

    def __init__(self):
        super().__init__()
        self.ship_folder = ""
        self.setWindowTitle("Carène — plans du navire")
        self.resize(1500, 940)

        self.project = Project()
        self.current_deck: Deck | None = None
        self.mode = MODE_SELECT
        self.active = "profil"
        self._poly_points = []
        self._poly_preview = None
        self._sync = False
        self._selected_capacity = None
        self._selected_deck = None
        self._selected_vertex = None
        self._selected_epontille = None   # (cale, épontille) choisie, ou None
        # Objet de calque choisi : {"quoi": "zone"|"obstacle"|"annotation",
        # "parent": cale ou pont, "objet": le dict/la liste du modèle}. C'est
        # ce qui manquait au bord : sans sélection, pas de retouche possible.
        self._selected_calque = None
        self._rect_start = None      # premier coin d'un rectangle en cours
        self._rect_preview = None    # son aperçu dans la scène
        # Rectangle tracé au GLISSER (appui, déplacement, relâchement) : le
        # geste naturel, et celui que le bord a fait sans que rien ne se passe.
        self._rect_glisser = False
        # Ce qu'on décalque sur le calque d'information — retenu d'une
        # annotation à la suivante : on en pose plusieurs à la file, du même
        # genre et de la même couleur.
        self._info_forme = "trait"
        self._info_texte = ""
        self._info_couleur = COULEUR_ANNOTATION_DEFAUT
        self._drag = None            # glisser en cours (sommet, polygone, épontille)
        self._clic_trace = None      # clic de tracé en attente de relâchement
        self._hud_wanted = True
        self._layers_wanted = True
        self._restoring = False
        self._undo = []              # [(capacité, anciens points)]
        self._last_snap = None       # dernier point accroché (pixel) ou None
        self._local_index = {}       # index d'accroche des tracés, par vue
        self._couples_signale = False   # couples.csv fautif : dit une seule fois
        self._perp_signale = False      # perpendiculaires absentes : de même
        self.snap_enabled = True
        # lecture des traits du fond (PDF ou DXF) hors du fil de l'interface
        self.chargeur = chargeur()
        self.chargeur.pret.connect(self._traits_prets)
        self.chargeur.echec.connect(self._traits_rates)
        self.wizard: ShipWizard | None = None

        self.profile_scene = PlanScene("profil", self)
        self.deck_scene = PlanScene("pont", self)
        self.profile_view = PlanGraphicsView(self.profile_scene, "profil", self)
        self.deck_view = PlanGraphicsView(self.deck_scene, "pont", self)
        self.iso_view = IsoView()
        for v in (self.profile_view, self.deck_view):
            v.activated.connect(lambda n=v.name: self.set_active(n))
        self.profile_scene.selectionChanged.connect(
            lambda: self.on_scene_selection(self.profile_scene))
        self.deck_scene.selectionChanged.connect(
            lambda: self.on_scene_selection(self.deck_scene))
        self.iso_view.scene().selectionChanged.connect(self.on_iso_selection)

        # ------------------------------------------------------------------
        # Mise en page : la zone de décalquage prend l'écran.
        # En haut et en grand le plan de pont — c'est lui qu'on décalque neuf
        # fois sur dix ; sous lui, le profil dans un bandeau qu'on referme
        # d'un geste (les deux plans sont larges et bas : l'un sur l'autre,
        # ils tiennent mieux que côte à côte). À droite, une colonne étroite
        # qui ne montre que ce qui sert, et la vue navire réduite à une
        # vignette de contrôle.
        # ------------------------------------------------------------------
        self.header_profile = self._header("PROFIL LONGITUDINAL · X–Z")
        self.header_deck = self._header("PONT COURANT · X–Y")
        self.pane_deck = self._titled(self.header_deck, self.deck_view)
        self.pane_profile = self._titled(self.header_profile, self.profile_view)
        self.split_draw = QSplitter(Qt.Orientation.Vertical)
        self.split_draw.addWidget(self.pane_deck)
        self.split_draw.addWidget(self.pane_profile)
        self.split_draw.setCollapsible(0, False)
        self.split_draw.setCollapsible(1, True)
        self.split_draw.setStretchFactor(0, 3)
        self.split_draw.setStretchFactor(1, 0)
        self.split_draw.setHandleWidth(5)
        self.split_draw.setSizes([700, PROFIL_PX])

        self.side = self._build_side_column()
        self.split_root = QSplitter(Qt.Orientation.Horizontal)
        self.split_root.addWidget(self.split_draw)
        self.split_root.addWidget(self.side)
        self.split_root.setCollapsible(0, False)
        self.split_root.setCollapsible(1, True)
        self.split_root.setStretchFactor(0, 1)
        self.split_root.setStretchFactor(1, 0)
        self.split_root.setHandleWidth(5)
        self.split_root.setSizes([1500 - COLONNE_PX, COLONNE_PX])
        self.setCentralWidget(self.split_root)

        self._build_actions()
        self._build_overlays()
        self._connect_props()
        self._restore_session_layout()
        self.split_draw.splitterMoved.connect(lambda *_: self._on_splitter_moved())
        self.split_root.splitterMoved.connect(lambda *_: self._on_splitter_moved())
        self.statusBar().showMessage("Prêt — l'assistant vous guide étape par étape.")
        # LE FILET ÉCHAP, posé sur l'application (voir `eventFilter`) : la
        # touche n'arrivait pas jusqu'ici dès que le focus était dans la
        # colonne de droite.
        QApplication.instance().installEventFilter(self)
        self.refresh_all()

    # ------------------------------------------------------------------ UI
    @staticmethod
    def _header(text):
        lbl = QLabel(text)
        lbl.setObjectName("viewHeader")
        return lbl

    @staticmethod
    def _titled(header, widget):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(header)
        lay.addWidget(widget)
        return w

    @staticmethod
    def _groupe_barre(tb, texte, separateur=True):
        """Un libellé de groupe dans la barre d'outils.

        Il sépare ce qu'on DÉCALQUE de ce qu'on POSE PAR-DESSUS : sans lui, la
        barre est une file de boutons de même rang, et rien ne dit lequel
        bloque la pose."""
        if separateur:
            tb.addSeparator()
        lbl = QLabel(f" {texte} ")
        lbl.setObjectName("toolGroup")
        lbl.setStyleSheet(
            f"QLabel#toolGroup {{ color: {theme.TEXT_FAINT}; font-size: 9px;"
            f" font-weight: bold; letter-spacing: 1.2px;"
            f" padding: 0 6px 0 4px; }}")
        tb.addWidget(lbl)
        return lbl

    def _build_actions(self):
        tb = QToolBar("Décalquer", self)
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)
        # DEUX rangées, et non une seule qui déborde : les douze outils
        # demandent 2540 px, aucun écran de passerelle n'en a autant. Une barre
        # qui déborde cache ses derniers boutons derrière un chevron — et c'est
        # précisément le groupe « Calques » que le bord ne trouvait pas. Il
        # occupe donc sa propre rangée, où rien ne peut le pousser dehors.
        self.addToolBarBreak()
        tb2 = QToolBar("Calques", self)
        tb2.setMovable(False)
        tb2.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb2)
        self.toolbar_decalquer, self.toolbar_calques = tb, tb2
        m_file = self.menuBar().addMenu("&Fichier")
        m_edit = self.menuBar().addMenu("&Édition")
        m_view = self.menuBar().addMenu("&Affichage")
        m_help = self.menuBar().addMenu("&Aide")

        def act(text, slot, sc=None, check=False, menu=None, toolbar=True,
                icon=None, tip=None, bar=None):
            a = QAction(text, self)
            if icon:
                a.setIcon(theme.icon(icon))
            if sc:
                a.setShortcut(QKeySequence(sc))
                a.setToolTip(f"{tip or text}  ({sc})")
            elif tip:
                a.setToolTip(tip)
            a.setCheckable(check)
            (a.toggled if check else a.triggered).connect(slot)
            if menu is not None:
                menu.addAction(a)
            if toolbar:
                (bar or tb).addAction(a)
            return a

        # Les actions de DOSSIER (assistant, enregistrer, importer) sont
        # créées ici — l'ordre des menus en dépend — mais posées en fin de
        # seconde rangée : ainsi les deux libellés de groupe, DÉCALQUER et
        # CALQUES, tombent l'un sous l'autre au bord gauche des deux rangées.
        self.act_wizard = act("Assistant", self.open_wizard, "F1", icon="wand",
                              menu=m_help, toolbar=False,
                              tip="Rouvrir l'assistant guidé")
        self.act_save = act(
            "Enregistrer", self.save_project, "Ctrl+S", icon="save",
            menu=m_file, toolbar=False,
            tip="Écrire la géométrie dans le dossier du navire")
        act("Reprendre un ancien fichier .carene.json…",
            self.import_legacy_project, menu=m_file, toolbar=False,
            tip="Convertir un navire des versions antérieures")
        m_file.addSeparator()
        self.act_import = act("Importer un plan…", self.import_plan_active,
                              icon="image", menu=m_file, toolbar=False,
                              tip="DXF, PDF ou image pour la vue active "
                                  "(profil ou pont courant)")
        # par une lambda, et non `self.open_catalogue` : `triggered` livre un
        # booléen « coché » qui atterrirait dans `target` et ferait ouvrir le
        # catalogue pour une vue nommée « False »
        self.act_catalogue = act(
            "Catalogue des plans…", lambda *_: self.open_catalogue(),
            icon="image", menu=m_file, toolbar=False,
            tip="Les plans PDF du chantier rangés dans le dossier du navire : "
                "les ajouter une fois, puis affecter une page à une vue sans "
                "rechercher le fichier.")
        act("Importer le profil…", self.import_profile,
            menu=m_file, toolbar=False)
        act("Importer le plan du pont…", self.import_deck_plan,
            menu=m_file, toolbar=False)
        m_file.addSeparator()
        act("Reprendre la silhouette schématique…", self.reprendre_schema,
            menu=m_file, toolbar=False,
            tip="Partir de la coque reconstituée depuis les tables du navire, "
                "puis la retoucher")

        # ------------------------------------------------------------------
        # CHANGER DE VUE, EN PREMIER ET SOUS LA MAIN. « Il faudrait trouver un
        # moyen plus simple de changer de pont » : la seule façon était de
        # trouver la ligne dans le tableau des vues de la colonne de droite —
        # une colonne qu'on peut replier, et qu'on replie. La liste est donc
        # dans la barre, en tête, avec ses deux raccourcis.
        # ------------------------------------------------------------------
        self.lbl_groupe_vue = self._groupe_barre(tb, "VUE", separateur=False)
        self.combo_vue = QComboBox()
        self.combo_vue.setMinimumWidth(152)
        self.combo_vue.setMaximumWidth(230)
        self.combo_vue.setToolTip(
            "Le plan sur lequel on travaille : le profil, puis chaque pont "
            "dans l'ordre des Z (du bas vers le haut).\n\n"
            "Ctrl+Page↑ / Ctrl+Page↓ (ou Ctrl+↑ / Ctrl+↓) passent à la vue "
            "précédente ou suivante sans lâcher la souris.")
        self.combo_vue.currentIndexChanged.connect(self._on_combo_vue)
        tb.addWidget(self.combo_vue)
        # un trait après la liste : « Sélection » n'appartient à aucun groupe
        # (c'est le mode de repos), et il ne doit pas avoir l'air d'en faire
        # partie
        tb.addSeparator()
        self.act_vue_prec = act(
            "Vue précédente", lambda: self.vue_voisine(-1), "Ctrl+PgUp",
            menu=m_view, toolbar=False,
            tip="Descendre d'une vue dans la liste (vers le profil)")
        self.act_vue_suiv = act(
            "Vue suivante", lambda: self.vue_voisine(+1), "Ctrl+PgDown",
            menu=m_view, toolbar=False,
            tip="Monter d'une vue dans la liste (vers le pont supérieur)")
        # les mêmes gestes aux flèches : c'est ce que la main essaie d'abord
        for sc, sens in (("Ctrl+Up", -1), ("Ctrl+Down", +1)):
            a = QAction(self)
            a.setShortcut(QKeySequence(sc))
            a.triggered.connect(lambda _c=False, s=sens: self.vue_voisine(s))
            self.addAction(a)

        self.act_select = act("Sélection", lambda c: c and self._set_mode(MODE_SELECT),
                              check=True,
                              tip="Sélectionner et modifier ce qui est tracé : "
                                  "contours, zones des calques, épontilles "
                                  "amovibles (clic droit : Propriétés / "
                                  "Supprimer ; Suppr : supprimer). Échap y "
                                  "ramène toujours.")
        # ------------------------------------------------------------------
        # La barre se lit en deux temps, comme le travail du bord : d'abord on
        # DÉCALQUE ce que le plan montre (contours, structure), puis on POSE
        # LES CALQUES par-dessus. Sans ces deux libellés, douze boutons de rang
        # égal ne disaient pas lequel bloque la pose et lequel se contente de
        # la signaler.
        # ------------------------------------------------------------------
        self.lbl_groupe_decalquer = self._groupe_barre(tb, "DÉCALQUER")
        self.act_cal = act("Calage", lambda c: self._toggle_mode(MODE_CAL, c),
                           check=True, icon="target",
                           tip="Poser les points de référence de la vue active : "
                               "ligne de foi et couples. Un calage donne les "
                               "COORDONNÉES et l'ÉCHELLE en une fois.")
        self.act_cal_apply = act("Appliquer", self.apply_calibration, icon="grid",
                                 tip="Calculer le calage à partir des points placés")
        self.act_decks = act("Ponts", lambda c: self._toggle_mode(MODE_DECKS, c),
                             check=True, icon="decks",
                             tip="Cliquer les lignes de ponts sur le profil")
        self.act_contour = act("Contour de pont",
                               lambda c: self._toggle_mode(MODE_CONTOUR, c),
                               check=True, icon="contour",
                               tip="Décalquer le contour du pont (la coque à ce "
                                   "niveau). Sert à la vue et au repérage : "
                                   "rien n'y est bloqué.")
        self.act_poly = act("Cale", lambda c: self._toggle_mode(MODE_POLY, c),
                            check=True, icon="polygon",
                            tip="Décalquer le contour d'une cale. BLOQUANT : "
                                "un colis hors de sa cale n'est pas posé "
                                "(décision D-27).")
        self.act_epontille = act(
            "Épontille", lambda c: self._toggle_mode(MODE_EPONTILLE, c),
            check=True, icon="polygon",
            tip="Poser une épontille : un clic dans une cale, puis sa fiche — "
                "où l'on coche « fixe » si elle est de la structure (toujours "
                "en place). Une épontille amovible n'est bloquante que mise "
                "en place, ce qui se décide escale par escale dans le "
                "Chargement. En mode Sélection : glisser pour la déplacer, "
                "clic droit pour Propriétés / Supprimer.")
        self.act_interdit = act(
            "Structure", lambda c: self._toggle_mode(MODE_INTERDIT, c),
            check=True, icon="contour",
            tip="Décalquer une zone de STRUCTURE dans une cale — descente, "
                "puits, cloisonnette — d'un glisser ou par deux clics en coins "
                "opposés. BLOQUANT : rien ne s'y pose, jamais. Pour une "
                "épontille fixe, préférez l'outil Épontille (case « fixe »).")
        self.act_trait = act(
            "Trait de construction", lambda c: self._toggle_mode(MODE_TRAIT, c),
            check=True, icon="target",
            tip="Poser un trait de construction : un clic pose une droite qui "
                "traverse le plan à cette cote (ligne de foi, couple, cote "
                "reportée). Repère de DESSIN : rien ne le lit, mais le curseur "
                "s'y accroche — et surtout à leurs croisements. Menu Édition › "
                "Traits de construction… pour la liste.")
        self.act_traits = act(
            "Traits de construction…", self.open_traits, menu=m_edit,
            toolbar=False,
            tip="La liste des traits de construction de ce plan : ligne de foi, "
                "couples, cotes reportées.")
        self.lbl_groupe_calques = self._groupe_barre(tb2, "CALQUES",
                                                    separateur=False)
        self.act_zone_charge = act(
            "Charge t/m²", lambda c: self._toggle_mode(MODE_ZONE_CHARGE, c),
            check=True, icon="polygon", bar=tb2,
            tip="Tracer une zone où la charge admissible diffère de celle de "
                "la cale : un polygone, comme une cale. SIGNALÉ, NON "
                "BLOQUANT — un dépassement s'affiche, il ne se refuse pas "
                "(décision D-12). Le solveur, lui, la respecte.")
        self.act_hauteur = act(
            "Hauteur libre", lambda c: self._toggle_mode(MODE_HAUTEUR, c),
            check=True, icon="contour", bar=tb2,
            tip="Tracer une zone à plafond bas dans une cale : deux clics en "
                "coins opposés, puis la hauteur libre en mètres. SIGNALÉ, NON "
                "BLOQUANT — une pile trop haute est marquée en rouge, pas "
                "refusée (décision D-21).")
        self.act_info = act(
            "Information", self.basculer_information,
            check=True, icon="wand", bar=tb2,
            tip="Décalquer une information : polyligne, polygone fermé, "
                "point ou texte — "
                "clés de saisissage, prise, remarque du bord. RIEN n'en "
                "dépend : ni la pose, ni la stabilité, ni le solveur ne la "
                "lisent.")
        tb2.addSeparator()
        self.act_snap = act("Accroche", self.toggle_snap, check=True,
                            icon="target", menu=m_edit, bar=tb2,
                            tip="Accrocher le curseur aux sommets du plan PDF, "
                                "aux tracés et aux points de calage "
                                "(Maj enfoncée : accroche suspendue)")
        self.act_snap.setChecked(True)
        self.act_undo = act("Annuler", self.undo, "Ctrl+Z", menu=m_edit,
                            toolbar=False, tip="Annuler la dernière retouche de contour")
        m_edit.addSeparator()
        act("Effacer le calage de la vue active", self.clear_calibration,
            menu=m_edit, toolbar=False)
        self.act_grid = act("Grille", self.toggle_grid, "G", check=True,
                            icon="grid", menu=m_view, bar=tb2)
        self.act_grid.setChecked(True)
        self.act_recadrer = act(
            "Recadrer", self.recadrer, "R", icon="fit", menu=m_view, bar=tb2,
            tip="Cadrer le plan de la vue où l'on travaille (molette : zoom au "
                "curseur ; bouton du milieu ou Espace + glisser : déplacer)")
        act("Ajuster toutes les vues", self.zoom_fit, "F", menu=m_view,
            toolbar=False, tip="Zoom ajusté sur le profil, le pont et la vue navire")
        tb2.addSeparator()
        for a in (self.act_wizard, self.act_save, self.act_import,
                  self.act_catalogue):
            tb2.addAction(a)
        m_view.addSeparator()

        # Les panneaux : chacun a sa case, on ne peut pas en perdre un.
        self.act_panneau_profil = act(
            "Bandeau du profil", self.set_profile_visible, "Ctrl+1", check=True,
            menu=m_view, toolbar=False,
            tip="Afficher ou replier la vue du profil sous le plan de pont")
        self.act_panneau_profil.setChecked(True)
        self.act_panneau_colonne = act(
            "Colonne de droite", self.set_side_visible, "Ctrl+0", check=True,
            menu=m_view, toolbar=False,
            tip="Afficher ou replier toute la colonne (vue navire, vues, "
                "propriétés)")
        self.act_panneau_colonne.setChecked(True)
        self.act_panneau_iso = act(
            "Vue navire (vignette)", lambda c: self.sec_iso.set_open(c),
            check=True, menu=m_view, toolbar=False)
        self.act_panneau_iso.setChecked(True)
        self.act_panneau_vues = act(
            "Liste des vues", lambda c: self.sec_views.set_open(c),
            check=True, menu=m_view, toolbar=False)
        self.act_panneau_vues.setChecked(True)
        self.act_panneau_tree = act(
            "Structure du navire", lambda c: self.sec_tree.set_open(c),
            check=True, menu=m_view, toolbar=False)
        self.act_panneau_tree.setChecked(False)
        self.act_panneau_props = act(
            "Propriétés", lambda c: self.sec_props.set_open(c),
            check=True, menu=m_view, toolbar=False)
        self.act_panneau_props.setChecked(True)
        self.act_calques = act(
            "Calques du plan", self.set_layers_visible, "L", check=True,
            menu=m_view, toolbar=False,
            tip="Le petit panneau de calques posé sur le plan")
        self.act_calques.setChecked(True)
        self.act_aide_trace = act(
            "Aide au tracé sur le plan", self.set_hud_visible, check=True,
            menu=m_view, toolbar=False)
        self.act_aide_trace.setChecked(True)
        m_view.addSeparator()
        act("Tout remettre en place", self.reset_layout, menu=m_view,
            toolbar=False, tip="Retrouver la disposition d'origine")
        # plus de « Thème sombre » (D-72)
        # L'aide de Carène, droit sur la page de l'éditeur de plans. `F1` est
        # déjà pris ici par l'assistant de calage, qui est le geste du
        # débutant : l'aide se prend au « ? » de la barre, ou en Maj+F1.
        act("Aide de Carène…", self.ouvrir_aide, "Shift+F1", menu=m_help,
            toolbar=False, icon="help",
            tip="Le mode d'emploi, sur la page de l'éditeur de plans")
        self.act_aide = act("Aide", self.ouvrir_aide, icon="help", bar=tb2,
                            tip="Le mode d'emploi, sur la page de l'éditeur "
                                "de plans  (Maj+F1)")
        m_help.addSeparator()
        act("Raccourcis et gestes…", self.aide_raccourcis, menu=m_help,
            toolbar=False)
        act("À propos…", self.about, menu=m_help, toolbar=False)
        self.act_select.setChecked(True)

    def _build_side_column(self) -> QWidget:
        """La colonne de droite : étroite, et rien d'inutile dedans.

        Quatre blocs repliables — vue navire, vues, structure, propriétés.
        Chacun garde son bandeau quand il est replié, et une case dans le menu
        Affichage : on ne peut pas perdre un panneau sans savoir le retrouver."""
        col = QWidget()
        col.setObjectName("sideColumn")
        col.setMinimumWidth(228)
        col.setMaximumWidth(460)
        lay = QVBoxLayout(col)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.sec_iso = Section("VUE NAVIRE", self.iso_view, hauteur=ISO_PX)
        self.iso_view.setToolTip("Contrôle d'ensemble : les ponts doivent "
                                 "s'empiler dans le bon ordre.")
        lay.addWidget(self.sec_iso)
        self.sec_views = Section("VUES DU NAVIRE", self._build_views_panel(),
                                 hauteur=272)
        lay.addWidget(self.sec_views)
        self.sec_tree = Section("STRUCTURE", self._build_tree_panel(),
                                replie=True, hauteur=230, fixe=False)
        lay.addWidget(self.sec_tree)
        self.sec_props = Section("PROPRIÉTÉS", self._build_props_panel())
        lay.addWidget(self.sec_props, 1)
        for sec in (self.sec_iso, self.sec_views, self.sec_tree, self.sec_props):
            sec.toggled.connect(lambda *_: self._on_sections_changed())
        return col

    def _build_views_panel(self) -> QWidget:
        """Une ligne par plan calé (profil, ponts), et ce qu'on peut en faire."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(7, 6, 7, 7)
        lay.setSpacing(5)
        self.views_table = QTableWidget(0, 5)
        self.views_table.setHorizontalHeaderLabels(
            ["Vue", "Z", "Plan", "Calé", "Cap."])
        self.views_table.verticalHeader().setVisible(False)
        self.views_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.views_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.views_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        head = self.views_table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for c in (1, 3, 4):
            head.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.views_table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.views_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.views_table.setWordWrap(False)
        self.views_table.setMaximumHeight(154)
        # 264 px ne portent pas cinq colonnes : le nom du fichier de plan
        # passe en infobulle et dans les propriétés, où il a la place
        self.views_table.setColumnHidden(2, True)
        self.views_table.itemSelectionChanged.connect(self.on_views_selection)
        self.views_table.doubleClicked.connect(lambda _i: self.edit_view_dialog())
        lay.addWidget(self.views_table)

        grid = QGridLayout()
        grid.setSpacing(4)

        def btn(text, slot, r, c, accent=False, icon=None, tip=None):
            b = QPushButton(text)
            b.setProperty("accent" if accent else "ghost", "1")
            if icon:
                b.setIcon(theme.icon(icon))
            if tip:
                b.setToolTip(tip)
            b.clicked.connect(slot)
            grid.addWidget(b, r, c)
            return b

        btn("Nouvelle vue…", self.add_deck_dialog, 0, 0, accent=True,
            tip="Créer un pont : nom, Z, alias, plan repris d'un autre pont")
        btn("Modifier…", self.edit_view_dialog, 0, 1,
            tip="Renommer, changer le Z ou l'alias de la vue")
        btn("Dupliquer", self.duplicate_view, 1, 0,
            tip="Copier le plan, le calage et le contour de ce pont")
        btn("Supprimer", self.delete_view, 1, 1, icon="trash")
        btn("Plan…", self.import_plan_selected_view, 2, 0, icon="image",
            tip="Importer l'image ou le PDF de cette vue "
                "(remplace le plan actuel)")
        btn("Caler", self.calibrate_selected_view, 2, 1, icon="target",
            tip="Placer les points de référence de cette vue")
        lay.addLayout(grid)
        self.views_hint = QLabel("")
        self.views_hint.setObjectName("hint")
        self.views_hint.setWordWrap(True)
        lay.addWidget(self.views_hint)
        return w

    def _build_tree_panel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(7, 6, 7, 7)
        lay.setSpacing(6)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(12)
        self.tree.itemSelectionChanged.connect(self.on_tree_selection)
        lay.addWidget(self.tree)
        row = QHBoxLayout()
        b1 = QPushButton("Ajouter un pont")
        b1.setProperty("ghost", "1")
        b1.clicked.connect(self.add_deck_dialog)
        b2 = QPushButton("Supprimer")
        b2.setProperty("ghost", "1")
        b2.setIcon(theme.icon("trash"))
        b2.clicked.connect(self.delete_tree_selection)
        row.addWidget(b1)
        row.addWidget(b2)
        lay.addLayout(row)
        return w

    def _build_props_panel(self) -> QWidget:
        """Les propriétés : uniquement les champs de ce qui est sélectionné.

        Rien de sélectionné, c'est une ligne — pas une colonne vide qui prend
        la place du plan. Le mode d'emploi est ailleurs (Aide → Raccourcis)."""
        self.props = QStackedWidget()

        # 0 — rien de sélectionné : une seule ligne
        empty = QWidget()
        el = QVBoxLayout(empty)
        el.setContentsMargins(11, 10, 11, 10)
        self.props_empty = QLabel("Rien de sélectionné — cliquez une vue "
                                  "ci-dessus, ou un contour sur le plan.")
        self.props_empty.setObjectName("hint")
        self.props_empty.setWordWrap(True)
        el.addWidget(self.props_empty)
        el.addStretch(1)
        self.props.addWidget(empty)

        # 1 — capacité ou contour
        capw = QWidget()
        form = QFormLayout(capw)
        form.setContentsMargins(11, 10, 11, 10)
        form.setSpacing(7)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.cap_form = form
        self.cap_title = QLabel("<b>Capacité</b>")
        self.cap_code = QLineEdit()
        self.cap_name = QLineEdit()
        self.cap_zmin = SpinNombre()
        self.cap_zmax = SpinNombre()
        for sp in (self.cap_zmin, self.cap_zmax):
            sp.setRange(-5, 60)
            sp.setDecimals(3)
            sp.setSuffix(" m")
            # sans cela, chaque touche frappée relit et réécrit le champ :
            # taper « 12.5 » donnait 12.000, la valeur étant reformatée avant
            # la fin de la frappe. Tous les autres champs de la fenêtre le font.
            sp.setKeyboardTracking(False)
        self.cap_fill = QSlider(Qt.Orientation.Horizontal)
        self.cap_fill.setRange(0, 100)
        self.cap_fill_lbl = QLabel("0 %")
        self.cap_delete = QPushButton("Supprimer cette capacité")
        self.cap_delete.setProperty("ghost", "1")
        self.cap_delete.setIcon(theme.icon("trash"))
        form.addRow(self.cap_title)
        form.addRow("Code", self.cap_code)
        form.addRow("Nom", self.cap_name)
        form.addRow("Z bas", self.cap_zmin)
        form.addRow("Z haut", self.cap_zmax)
        # LES CLASSES IMDG ADMISES (D-83) : une donnée du navire, posée ici
        self.cap_imdg = QLineEdit()
        self.cap_imdg.setPlaceholderText("aucune marchandise dangereuse")
        self.cap_imdg.setToolTip(
            "Classes IMDG admises dans cette cale : « 3, 9 », ou « toutes ». "
            "Vide : aucune marchandise dangereuse. Un lot d'une classe non "
            "admise est refusé par le répartiteur et signalé sur le plan.")
        self.cap_imdg.editingFinished.connect(self.on_cap_imdg)
        form.addRow("IMDG admises", self.cap_imdg)
        form.addRow("Remplissage", self.cap_fill)
        form.addRow("", self.cap_fill_lbl)
        # Le verrou est une donnée du NAVIRE (D-42) : il se pose ici, à côté
        # du code et des cotes, pas dans un réglage d'affichage.
        self.cap_verrou = QCheckBox("Verrouillée")
        self.cap_verrou.setToolTip(
            "Une cale verrouillée ne se déplace plus, ses sommets non plus, "
            "et on n'en ajoute ni n'en retire. Le verrou part avec le dossier "
            "du navire : il vaut pour tous les postes.")
        form.addRow("", self.cap_verrou)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        form.addRow(sep)
        self.vtx_title = QLabel("<b>Sommets du contour</b>")
        self.vtx_title.setWordWrap(True)
        form.addRow(self.vtx_title)
        self.vtx_index = QSpinBox()
        self.vtx_index.setRange(1, 1)
        self.vtx_x = SpinNombre()
        self.vtx_y = SpinNombre()
        for sp in (self.vtx_x, self.vtx_y):
            sp.setRange(-1000, 1000)
            sp.setDecimals(3)
            sp.setSuffix(" m")
            sp.setKeyboardTracking(False)
        form.addRow("Sommet n°", self.vtx_index)
        form.addRow("X", self.vtx_x)
        form.addRow("Y (bâbord +)", self.vtx_y)
        vrow = QHBoxLayout()
        self.vtx_delete = QPushButton("Retirer ce sommet")
        self.vtx_delete.setProperty("ghost", "1")
        self.vtx_undo = QPushButton("Annuler")
        self.vtx_undo.setProperty("ghost", "1")
        self.vtx_undo.setToolTip("Ctrl+Z")
        vrow.addWidget(self.vtx_delete)
        vrow.addWidget(self.vtx_undo)
        form.addRow(vrow)
        self.cap_hint = QLabel(
            "Ce tracé sert à la vue et aux contrôles de pose : il n'entre "
            "jamais dans le calcul de stabilité (D-10).")
        self.cap_hint.setObjectName("hint")
        self.cap_hint.setWordWrap(True)
        form.addRow(self.cap_hint)
        form.addRow(self.cap_delete)
        # lignes que le contour de pont n'a pas : code, nom, Z, remplissage
        self.cap_rows_capacite = [1, 2, 3, 4, 5, 6]
        self.props.addWidget(capw)

        # 2 — pont (vue de pont)
        deckw = QWidget()
        form2 = QFormLayout(deckw)
        form2.setContentsMargins(11, 10, 11, 10)
        form2.setSpacing(7)
        form2.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form2.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.deck_name = QLineEdit()
        self.deck_z = SpinNombre()
        self.deck_z.setRange(-5, 60)
        self.deck_z.setDecimals(3)
        self.deck_z.setSuffix(" m")
        self.deck_z.setKeyboardTracking(False)
        self.deck_alias = QLineEdit()
        self.deck_alias.setPlaceholderText("nom du dossier (Tank Top…)")
        self.deck_import = QPushButton("Importer le plan de ce pont…")
        self.deck_import.setProperty("accent", "1")
        self.deck_cal = QPushButton("Caler ce plan")
        self.deck_cal.setProperty("ghost", "1")
        self.deck_cal.setIcon(theme.icon("target"))
        self.deck_info = QLabel("")
        self.deck_info.setObjectName("hint")
        self.deck_info.setWordWrap(True)
        form2.addRow(QLabel("<b>Pont</b>"))
        form2.addRow("Nom", self.deck_name)
        form2.addRow("Z", self.deck_z)
        form2.addRow("Alias", self.deck_alias)
        form2.addRow(self.deck_import)
        form2.addRow(self.deck_cal)
        form2.addRow(self.deck_info)
        self.props.addWidget(deckw)

        # 3 — profil
        profw = QWidget()
        form3 = QFormLayout(profw)
        form3.setContentsMargins(11, 10, 11, 10)
        form3.setSpacing(7)
        self.prof_import = QPushButton("Importer le profil…")
        self.prof_import.setProperty("accent", "1")
        self.prof_cal = QPushButton("Caler le profil")
        self.prof_cal.setProperty("ghost", "1")
        self.prof_cal.setIcon(theme.icon("target"))
        self.prof_info = QLabel("")
        self.prof_info.setObjectName("hint")
        self.prof_info.setWordWrap(True)
        form3.addRow(QLabel("<b>Profil longitudinal (X–Z)</b>"))
        form3.addRow(self.prof_import)
        form3.addRow(self.prof_cal)
        form3.addRow(self.prof_info)
        self.props.addWidget(profw)

        # 4 — épontille amovible
        epw = QWidget()
        form4 = QFormLayout(epw)
        form4.setContentsMargins(11, 10, 11, 10)
        form4.setSpacing(7)
        form4.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form4.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.ep_titre = QLabel("<b>Épontille</b>")
        self.ep_titre.setWordWrap(True)
        self.ep_nom = QLineEdit()
        self.ep_x = SpinNombre()
        self.ep_y = SpinNombre()
        for sp in (self.ep_x, self.ep_y):
            sp.setRange(-1000, 1000)
            sp.setDecimals(3)
            sp.setSuffix(" m")
            sp.setKeyboardTracking(False)
        self.ep_long = SpinNombre()
        self.ep_larg = SpinNombre()
        for sp in (self.ep_long, self.ep_larg):
            sp.setRange(0.02, 5.0)
            sp.setDecimals(3)
            sp.setSingleStep(0.05)
            sp.setSuffix(" m")
            sp.setKeyboardTracking(False)
        self.ep_note = QLineEdit()
        self.ep_fixe = QCheckBox("Fixe — toujours en place, ne se dépose pas")
        self.ep_delete = QPushButton("Supprimer cette épontille")
        self.ep_delete.setProperty("ghost", "1")
        self.ep_delete.setIcon(theme.icon("trash"))
        form4.addRow(self.ep_titre)
        form4.addRow("Nom", self.ep_nom)
        form4.addRow("X (centre)", self.ep_x)
        form4.addRow("Y (bâbord +)", self.ep_y)
        form4.addRow("Longueur (X)", self.ep_long)
        form4.addRow("Largeur (Y)", self.ep_larg)
        form4.addRow("Note", self.ep_note)
        form4.addRow("", self.ep_fixe)
        self.ep_hint = QLabel(
            "L'emplacement appartient au navire. Amovible : la mettre EN PLACE "
            "est une décision de chaque escale, prise dans la vue Chargement "
            "(MSL 50 kN — manuel d'assujettissement). Fixe : c'est de la structure, "
            "elle est toujours en place.")
        self.ep_hint.setObjectName("hint")
        self.ep_hint.setWordWrap(True)
        form4.addRow(self.ep_hint)
        form4.addRow(self.ep_delete)
        self.props.addWidget(epw)

        # 5 — zone de charge admissible (calque, D-12)
        zcw = QWidget()
        form5 = QFormLayout(zcw)
        form5.setContentsMargins(11, 10, 11, 10)
        form5.setSpacing(7)
        form5.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form5.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.zc_titre = QLabel("<b>Zone de charge</b>")
        self.zc_titre.setWordWrap(True)
        self.zc_nom = QLineEdit()
        self.zc_t = SpinNombre()
        self.zc_t.setRange(0.0, 100.0)
        self.zc_t.setDecimals(2)
        self.zc_t.setSingleStep(0.1)
        self.zc_t.setSuffix(" t/m²")
        self.zc_t.setKeyboardTracking(False)
        self.zc_delete = QPushButton("Supprimer cette zone de charge")
        self.zc_delete.setProperty("ghost", "1")
        self.zc_delete.setIcon(theme.icon("trash"))
        self.zc_hint = QLabel(
            "Calque qui ALERTE, jamais bloquant : un dépassement est signalé, "
            "pas refusé — la limite vient d'un tracé, pas du dossier approuvé "
            "(D-12). Le solveur, lui, la respecte.")
        self.zc_hint.setObjectName("hint")
        self.zc_hint.setWordWrap(True)
        form5.addRow(self.zc_titre)
        form5.addRow("Nom", self.zc_nom)
        form5.addRow("Charge admissible", self.zc_t)
        form5.addRow(self.zc_hint)
        form5.addRow(self.zc_delete)
        self.props.addWidget(zcw)

        # 6 — zone interdite ou à hauteur réduite (cap.obstacles)
        obw = QWidget()
        form6 = QFormLayout(obw)
        form6.setContentsMargins(11, 10, 11, 10)
        form6.setSpacing(7)
        form6.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form6.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.ob_titre = QLabel("<b>Zone</b>")
        self.ob_titre.setWordWrap(True)
        # une seule case décide de TOUT le comportement de la zone : avec
        # hauteur c'est un calque qui alerte, sans hauteur c'est un mur. Elle
        # est donc en tête, avant le nom.
        self.ob_bloquante = QCheckBox("Bloque la pose (structure)")
        self.ob_nom = QLineEdit()
        self.ob_hauteur = SpinNombre()
        self.ob_hauteur.setRange(0.05, 30.0)
        self.ob_hauteur.setDecimals(2)
        self.ob_hauteur.setSingleStep(0.05)
        self.ob_hauteur.setSuffix(" m")
        self.ob_hauteur.setKeyboardTracking(False)
        self.ob_x0 = SpinNombre()
        self.ob_x1 = SpinNombre()
        self.ob_y0 = SpinNombre()
        self.ob_y1 = SpinNombre()
        for sp in (self.ob_x0, self.ob_x1, self.ob_y0, self.ob_y1):
            sp.setRange(-1000, 1000)
            sp.setDecimals(3)
            sp.setSuffix(" m")
            sp.setKeyboardTracking(False)
        self.ob_delete = QPushButton("Supprimer cette zone")
        self.ob_delete.setProperty("ghost", "1")
        self.ob_delete.setIcon(theme.icon("trash"))
        self.ob_hint = QLabel("")
        self.ob_hint.setObjectName("hint")
        self.ob_hint.setWordWrap(True)
        form6.addRow(self.ob_titre)
        form6.addRow(self.ob_bloquante)
        form6.addRow("Nom", self.ob_nom)
        form6.addRow("Hauteur libre", self.ob_hauteur)
        form6.addRow("X de", self.ob_x0)
        form6.addRow("X à", self.ob_x1)
        form6.addRow("Y de", self.ob_y0)
        form6.addRow("Y à", self.ob_y1)
        form6.addRow(self.ob_hint)
        form6.addRow(self.ob_delete)
        self.props.addWidget(obw)

        # 7 — annotation du calque d'information (deck.annotations)
        anw = QWidget()
        form7 = QFormLayout(anw)
        form7.setContentsMargins(11, 10, 11, 10)
        form7.setSpacing(7)
        form7.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form7.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.an_titre = QLabel("<b>Information</b>")
        self.an_titre.setWordWrap(True)
        self.an_forme = QLabel("")
        self.an_texte = QLineEdit()
        self.an_couleur = QComboBox()
        from .items import COULEURS_ANNOTATION
        self._couleurs_annotation = list(COULEURS_ANNOTATION)
        for nom_c, code in self._couleurs_annotation:
            self.an_couleur.addItem(f"{nom_c}  ({code})")
        self.an_delete = QPushButton("Supprimer cette information")
        self.an_delete.setProperty("ghost", "1")
        self.an_delete.setIcon(theme.icon("trash"))
        self.an_hint = QLabel(
            "Calque d'information : rien n'en dépend — ni la pose, ni la "
            "stabilité, ni le solveur. Il s'affiche ou s'éteint, c'est tout.")
        self.an_hint.setObjectName("hint")
        self.an_hint.setWordWrap(True)
        form7.addRow(self.an_titre)
        form7.addRow("Forme", self.an_forme)
        form7.addRow("Texte", self.an_texte)
        form7.addRow("Couleur", self.an_couleur)
        form7.addRow(self.an_hint)
        form7.addRow(self.an_delete)
        self.props.addWidget(anw)

        # une colonne étroite ne peut pas tout montrer d'un coup : elle défile
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(self.props)
        return area

    def _connect_props(self):
        self.cap_code.editingFinished.connect(self.on_cap_edited)
        self.cap_name.editingFinished.connect(self.on_cap_edited)
        self.cap_zmin.valueChanged.connect(self.on_cap_edited)
        self.cap_zmax.valueChanged.connect(self.on_cap_edited)
        self.cap_fill.valueChanged.connect(self.on_cap_fill)
        self.cap_fill.sliderReleased.connect(self.on_cap_fill_lache)
        self.cap_delete.clicked.connect(self.delete_selected_capacity)
        self.cap_verrou.toggled.connect(self.on_cap_verrou)
        self.vtx_index.valueChanged.connect(self.on_vertex_index)
        self.vtx_x.valueChanged.connect(self.on_vertex_edited)
        self.vtx_y.valueChanged.connect(self.on_vertex_edited)
        self.vtx_delete.clicked.connect(self.delete_selected_vertex)
        self.vtx_undo.clicked.connect(self.undo)
        self.deck_name.editingFinished.connect(self.on_deck_edited)
        self.deck_z.valueChanged.connect(self.on_deck_edited)
        self.deck_alias.editingFinished.connect(self.on_deck_edited)
        self.deck_import.clicked.connect(self.import_deck_plan)
        self.deck_cal.clicked.connect(lambda: self.calibrate_view(self._selected_deck))
        self.ep_nom.editingFinished.connect(self.on_epontille_edited)
        self.ep_note.editingFinished.connect(self.on_epontille_edited)
        self.ep_fixe.toggled.connect(self.on_epontille_edited)
        for sp in (self.ep_x, self.ep_y, self.ep_long, self.ep_larg):
            sp.valueChanged.connect(self.on_epontille_edited)
        self.ep_delete.clicked.connect(self.delete_selected_epontille)
        self.zc_nom.editingFinished.connect(self.on_zone_charge_edited)
        self.zc_t.valueChanged.connect(self.on_zone_charge_edited)
        self.zc_delete.clicked.connect(self.delete_selected_calque)
        self.ob_bloquante.toggled.connect(self.on_obstacle_edited)
        self.ob_nom.editingFinished.connect(self.on_obstacle_edited)
        for sp in (self.ob_hauteur, self.ob_x0, self.ob_x1, self.ob_y0,
                   self.ob_y1):
            sp.valueChanged.connect(self.on_obstacle_edited)
        self.ob_delete.clicked.connect(self.delete_selected_calque)
        self.an_texte.editingFinished.connect(self.on_annotation_edited)
        self.an_couleur.currentIndexChanged.connect(self.on_annotation_edited)
        self.an_delete.clicked.connect(self.delete_selected_calque)
        self.prof_import.clicked.connect(self.import_profile)
        self.prof_cal.clicked.connect(lambda: self.calibrate_view("profil"))

    # ------------------------------------------------------------------ panneaux posés
    def _build_overlays(self):
        """Les deux panneaux posés SUR le plan : aide au tracé et calques.

        Ils flottent au-dessus de la vue plutôt que de lui prendre de la
        largeur — c'est le plan qui doit avoir la place."""
        self.hud = TraceOverlay()
        self.deck_view.add_overlay(self.hud, "haut-gauche")
        self.layers_panel = LayersOverlay()
        self.layers_panel.changed.connect(self.on_layer_changed)
        self.deck_view.add_overlay(self.layers_panel, "bas-gauche")
        self.layers_panel.setVisible(getattr(self, "_layers_wanted", True))
        self.deck_view.refresh_overlays()
        self._refresh_hud()

    def on_layer_changed(self, nom, on):
        """Un calque s'allume ou s'éteint sur les deux plans à la fois : le
        profil et le pont montrent les mêmes choses."""
        for scene in (self.deck_scene, self.profile_scene):
            scene.set_layer_visible(nom, on)
        if nom == "grille":
            self.act_grid.blockSignals(True)
            self.act_grid.setChecked(bool(on))
            self.act_grid.blockSignals(False)
        self._save_session_layout()

    def set_layers_visible(self, on):
        self._layers_wanted = bool(on)
        if not hasattr(self, "layers_panel"):
            return                      # panneaux pas encore construits
        self.layers_panel.setVisible(bool(on))
        self.deck_view.refresh_overlays()
        self._save_session_layout()

    def set_hud_visible(self, on):
        self._hud_wanted = bool(on)
        self._refresh_hud()
        self._save_session_layout()

    def _refresh_hud(self):
        """Met à jour l'aide au tracé : quoi, combien de sommets, accroche."""
        hud = getattr(self, "hud", None)
        if hud is None:
            return
        trace = self.mode in MODES_POLYGONE or (
            self.mode == MODE_INFO and self._info_forme in FORMES_TRACEES_INFO)
        if not getattr(self, "_hud_wanted", True) or not trace:
            hud.hide()
            return
        deck = self.current_deck.name if self.current_deck else "—"
        quoi = {MODE_CONTOUR: "Contour du pont", MODE_POLY: "Cale",
                MODE_ZONE_CHARGE: "Zone de charge t/m² (signalée, non bloquante)",
                MODE_INFO: "Information (rien n'en dépend)"}.get(self.mode, "Cale")
        cal = self.deck_scene.calibrated
        if not self.snap_enabled:
            etat = "accroche suspendue"
        elif self.chargeur.en_lecture(cal):
            etat = "lecture des traits… (accroche sur les tracés seulement)"
        elif self._vector_index(cal) is not None:
            etat = "accroche active (sommets du plan, tracés, points de calage)"
        else:
            etat = "accroche active (tracés et points de calage)"
        hud.set_trace(f"TRACÉ · {quoi} — {deck}", len(self._poly_points), etat)
        hud.show()
        self.deck_view.refresh_overlays()

    # ------------------------------------------------------------------ mise en page
    def _on_sections_changed(self):
        for act_, sec in ((getattr(self, "act_panneau_iso", None), self.sec_iso),
                          (getattr(self, "act_panneau_vues", None), self.sec_views),
                          (getattr(self, "act_panneau_tree", None), self.sec_tree),
                          (getattr(self, "act_panneau_props", None), self.sec_props)):
            if act_ is None:
                continue
            act_.blockSignals(True)
            act_.setChecked(sec.is_open())
            act_.blockSignals(False)
        self._save_session_layout()

    def _on_splitter_moved(self):
        """Replier un panneau à la poignée doit décocher sa case : sinon on ne
        sait plus si le menu Affichage dit vrai."""
        for act_, taille in ((self.act_panneau_profil, self.split_draw.sizes()[1]),
                             (self.act_panneau_colonne, self.split_root.sizes()[1])):
            act_.blockSignals(True)
            act_.setChecked(taille > 0)
            act_.blockSignals(False)
        self._save_session_layout()

    def set_profile_visible(self, on):
        """Le bandeau du profil se referme entièrement : on trace un plan de
        pont neuf fois sur dix, le profil ne sert qu'aux ponts et au calage."""
        sizes = self.split_draw.sizes()
        total = sum(sizes) or 900
        if on:
            h = _ETAT_SESSION.get("profil_px", PROFIL_PX) or PROFIL_PX
            self.split_draw.setSizes([max(120, total - h), h])
        else:
            if sizes[1] > 0:
                _ETAT_SESSION["profil_px"] = sizes[1]
            self.split_draw.setSizes([total, 0])
            self.statusBar().showMessage(
                "Bandeau du profil replié — Affichage ▸ Bandeau du profil "
                "(Ctrl+1) pour le rouvrir.", 8000)
        self.pane_profile.setVisible(bool(on))
        if hasattr(self, "act_panneau_profil"):
            self.act_panneau_profil.blockSignals(True)
            self.act_panneau_profil.setChecked(bool(on))
            self.act_panneau_profil.blockSignals(False)
        self._save_session_layout()

    def set_side_visible(self, on):
        sizes = self.split_root.sizes()
        total = sum(sizes) or 1400
        if on:
            w = _ETAT_SESSION.get("colonne_px", COLONNE_PX) or COLONNE_PX
            self.split_root.setSizes([max(200, total - w), w])
        else:
            if sizes[1] > 0:
                _ETAT_SESSION["colonne_px"] = sizes[1]
            self.split_root.setSizes([total, 0])
            self.statusBar().showMessage(
                "Colonne de droite repliée — Affichage ▸ Colonne de droite "
                "(Ctrl+0) pour la rouvrir.", 8000)
        self.side.setVisible(bool(on))
        if hasattr(self, "act_panneau_colonne"):
            self.act_panneau_colonne.blockSignals(True)
            self.act_panneau_colonne.setChecked(bool(on))
            self.act_panneau_colonne.blockSignals(False)
        self._save_session_layout()

    def reset_layout(self):
        """Remet la disposition d'origine : plan en grand, colonne étroite."""
        _ETAT_SESSION.clear()
        self.sec_iso.set_open(True)
        self.sec_views.set_open(True)
        self.sec_tree.set_open(False)
        self.sec_props.set_open(True)
        self.set_profile_visible(True)
        self.set_side_visible(True)
        largeur = max(self.width(), 900)
        self.split_root.setSizes([largeur - COLONNE_PX, COLONNE_PX])
        hauteur = max(self.split_draw.height(), 600)
        self.split_draw.setSizes([hauteur - PROFIL_PX, PROFIL_PX])
        self.act_calques.setChecked(True)
        self.act_aide_trace.setChecked(True)
        for nom in CALQUES:
            self.layers_panel.set_checked(nom, True)
            self.on_layer_changed(nom, True)
        self.zoom_fit()

    def _save_session_layout(self):
        """La disposition tient la session : on ne la réapprend pas à chaque
        fenêtre rouverte. Ce n'est pas une donnée du navire, elle n'est donc
        pas écrite dans son dossier."""
        if not hasattr(self, "layers_panel") or self._restoring:
            return
        d = _ETAT_SESSION
        s_draw = self.split_draw.sizes()
        s_root = self.split_root.sizes()
        if s_draw[1] > 0:
            d["profil_px"] = s_draw[1]
        if s_root[1] > 0:
            d["colonne_px"] = s_root[1]
        d["profil_ouvert"] = s_draw[1] > 0
        d["colonne_ouverte"] = s_root[1] > 0
        d["sections"] = {"iso": self.sec_iso.is_open(),
                         "vues": self.sec_views.is_open(),
                         "structure": self.sec_tree.is_open(),
                         "props": self.sec_props.is_open()}
        d["calques"] = self.layers_panel.etat()
        d["calques_visible"] = getattr(self, "_layers_wanted", True)
        d["aide_trace"] = getattr(self, "_hud_wanted", True)

    def _restore_session_layout(self):
        """Reprend la disposition de la session — sans l'écraser au passage."""
        d = dict(_ETAT_SESSION)
        self._restoring = True
        try:
            self._apply_session_layout(d)
        finally:
            self._restoring = False
        self._save_session_layout()

    def _apply_session_layout(self, d):
        self._hud_wanted = d.get("aide_trace", True)
        self.act_aide_trace.setChecked(self._hud_wanted)
        sections = d.get("sections") or {}
        for cle, sec in (("iso", self.sec_iso), ("vues", self.sec_views),
                         ("structure", self.sec_tree), ("props", self.sec_props)):
            if cle in sections:
                sec.set_open(sections[cle])
        self._on_sections_changed()
        for nom, on in (d.get("calques") or {}).items():
            self.layers_panel.set_checked(nom, on)
            self.on_layer_changed(nom, on)
        if not d.get("calques_visible", True):
            self.act_calques.setChecked(False)
        if not d.get("profil_ouvert", True):
            self.set_profile_visible(False)
        if not d.get("colonne_ouverte", True):
            self.set_side_visible(False)

    # ------------------------------------------------------------------ vue
    def recadrer(self):
        """Cadre le plan de la vue où l'on travaille (le pont, ou le profil)."""
        name = self.active if self.active in ("profil", "pont") else "pont"
        view = self._view_for(name)
        scene = self._scene_for(name)
        if scene.pixmap_item is None:
            self.zoom_fit()
            return
        view.fitInView(scene.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
        self.statusBar().showMessage(
            f"Vue « {name} » recadrée sur le plan.", 3000)

    def pan_started(self, view):
        """Un geste de déplacement commence : le clic en cours ne posera pas de
        sommet (c'est la promesse faite au bord : on déplace sans tracer)."""
        self._clic_trace = None
        if self._rect_glisser:
            # un pan commencé au milieu d'un glisser de rectangle : on rend le
            # plan, pas une zone posée au hasard du déplacement
            self._cancel_rect()

    def cursor_for_mode(self):
        return (Qt.CursorShape.CrossCursor
                if self.mode in (MODE_CAL, MODE_DECKS, MODE_TRAIT, MODE_INFO)
                or self.mode in MODES_POLYGONE or self.mode in MODES_RECTANGLE
                else Qt.CursorShape.ArrowCursor)

    def ouvrir_aide(self, *_a):
        """Le bouton « Aide » de la barre et *Maj+F1* : l'aide de Carène,
        droit sur la page qui décrit l'éditeur de plans.

        (`triggered(bool)` passe son booléen au slot : on l'avale.)"""
        from .aide_dialog import ouvrir_aide
        return ouvrir_aide(self, "navire.md")

    def aide_raccourcis(self):
        QMessageBox.information(
            self, "Raccourcis et gestes",
            "<b>Le déroulé d'un plan</b><br>"
            "1. Importer le plan (DXF, PDF ou image) &nbsp;·&nbsp; "
            "2. Le <b>caler</b> : ligne de foi et couples (ou perpendiculaires "
            "sur le profil) — coordonnées ET échelle en une fois<br>"
            "3. <b>Décalquer</b> : contour de pont, cales, épontilles fixes "
            "&nbsp;·&nbsp; 4. Poser les <b>calques</b> charge t/m² et hauteur "
            "libre &nbsp;·&nbsp; 5. Le calque d'<b>information</b> "
            "&nbsp;·&nbsp; 6. Enregistrer.<br><br>"
            "<b>Naviguer</b><br>"
            "Molette : zoom au curseur<br>"
            "Bouton du milieu, ou Espace + glisser : déplacer la vue<br>"
            "<b>R</b> : recadrer la vue courante &nbsp; <b>F</b> : ajuster toutes "
            "les vues &nbsp; <b>G</b> : grille<br><br>"
            "<b>Tracer un polygone (Cale, Contour de pont, Charge t/m², "
            "Information)</b><br>"
            "Clic : poser un sommet &nbsp;·&nbsp; double-clic ou <b>Entrée</b> : "
            "fermer<br><b>Retour arrière</b> : retirer le dernier sommet<br>"
            "<b>Échap</b> : abandonner &nbsp;·&nbsp; <b>Maj</b> : suspendre "
            "l'accroche<br>Un geste de déplacement ne pose jamais de sommet.<br><br>"
            "<b>Tracer un rectangle (Épontille fixe, Hauteur libre)</b><br>"
            "Deux clics en coins opposés, DANS une cale ; une fiche demande le "
            "nom, ou la hauteur libre en mètres. <b>Échap</b> abandonne.<br><br>"
            "<b>Retoucher un contour</b><br>"
            "Cliquer le polygone, puis glisser un sommet par sa poignée.<br>"
            "<b>Ajouter un sommet — deux gestes, au choix</b> : "
            "<b>clic droit sur un segment</b> → <i>Ajouter un sommet ici</i>, "
            "ou <b>double-clic</b> sur ce segment. Le sommet se pose sur le "
            "segment, à l'endroit visé, accroché comme le reste.<br>"
            "<b>Suppr</b> sur un sommet : le retirer ; glisser "
            "l'intérieur : déplacer le tout ; <b>Ctrl+Z</b> : annuler.<br>"
            "Là où deux cales se recouvrent, un clic de plus au même endroit "
            "passe à la suivante — et l'arbre <i>Structure</i> les liste "
            "toutes. La cale choisie passe au-dessus : ses sommets restent "
            "saisissables même sous une autre.<br><br>"
            "<b>Verrouiller (pour ne rien décaler par mégarde)</b><br>"
            "<b>Clic droit sur une cale</b> → <i>Verrouiller la cale</i> (ou "
            "la case <i>Verrouillée</i> dans <i>Propriétés</i>) : elle ne se "
            "déplace plus, ses sommets non plus, on n'en ajoute ni n'en "
            "retire, et elle se dessine en tirets avec un 🔒.<br>"
            "<b>Clic droit sur une poignée</b> → <i>Verrouiller ce sommet</i> : "
            "ce sommet-là seulement, dessiné en carré plein. Un geste refusé "
            "par un verrou est toujours annoncé dans la barre d'état.<br>"
            "Les verrous partent avec le dossier du navire (D-42) : un plan "
            "verrouillé l'est pour tous les postes qui l'ouvrent.<br><br>"
            "<b>Cales qui se chevauchent</b><br>"
            "Deux cales d'un même pont qui se mordent de plus de quelques "
            "millimètres sont <b>signalées</b> — barre d'état, arbre "
            "(« ⚠ chevauche… ») et rapport d'enregistrement. Se toucher bord "
            "à bord reste normal. C'est un avertissement, jamais un refus : "
            "on enregistre, on corrige ensuite.<br><br>"
            "<b>Choisir, retoucher, supprimer un calque</b><br>"
            "En mode Sélection, un clic sur une zone de charge, une zone de "
            "hauteur, une zone interdite, une information ou une épontille la "
            "choisit : ses champs s'affichent dans la colonne de droite. "
            "<b>Clic droit</b> ouvre <i>Propriétés…</i> et <i>Supprimer</i> ; "
            "<b>Suppr</b> supprime ; <b>Ctrl+Z</b> annule l'ajout comme la "
            "suppression. L'arbre <i>Structure</i> les liste aussi, cale par "
            "cale.<br><br>"
            "<b>Ce qui bloque et ce qui ne bloque pas</b><br>"
            "Bloquant : le contour d'une <b>cale</b> (rien ne se pose dehors) "
            "et une <b>zone interdite / épontille fixe</b>. Signalé mais non "
            "bloquant : la <b>charge t/m²</b> (D-12) et la <b>hauteur libre</b> "
            "(D-21). Sans effet : le calque d'<b>information</b> et les "
            "<b>traits de construction</b>.<br><br>"
            "<b>Épontilles amovibles</b><br>"
            "Outil <b>Épontille amovible</b>, puis un clic DANS une cale : elle "
            "se pose à cet endroit. En mode Sélection : <b>glisser pour la "
            "déplacer</b>, clic droit pour <i>Propriétés…</i> / "
            "<i>Supprimer</i>, <b>Suppr</b> pour la retirer. Elle n'interdit la "
            "pose que lorsqu'elle est mise en place, dans la vue Chargement.<br><br>"
            "<b>Panneaux</b><br>"
            "<b>Ctrl+1</b> : bandeau du profil &nbsp; <b>Ctrl+0</b> : colonne de "
            "droite &nbsp; <b>L</b> : calques<br>"
            "Tout se retrouve dans le menu Affichage.")

    # ------------------------------------------------------------------ assistant
    def open_wizard(self):
        if self.wizard is None:
            self.wizard = ShipWizard(self, self)
        self.wizard.jump_to_current_step()
        self.wizard.show()
        self.wizard.raise_()
        self.wizard.activateWindow()

    def refresh_wizard(self):
        if self.wizard is not None and self.wizard.isVisible():
            self.wizard.refresh()

    # ------------------------------------------------------------------ vues
    @staticmethod
    def _plan_state(cal: Calibrated):
        if not cal.image_path:
            return "○", "aucun"
        # le rendu PNG se refait tout seul (`scene.ensure_rendered`) tant que
        # le fichier d'origine est là — DXF aussi bien que PDF : ne dire
        # « fichier absent » que si c'est LUI qui manque
        source = ((cal.pdf_path and os.path.exists(cal.pdf_path))
                  or (getattr(cal, "dxf_path", "")
                      and os.path.exists(cal.dxf_path)))
        if not os.path.exists(cal.image_path) and not source:
            return "!", "fichier absent"
        if not cal.calibration.valid:
            return "◐", f"{len(cal.cal_points)} pt"
        res = cal.residuals()
        if not res:
            # calé sur les coordonnées du dessin : pas de point à contrôler
            return "✓", ("coord. DXF" if getattr(cal, "from_dxf", False)
                         else "calé")
        pire = max(res)
        return "✓", (f"±{pire * 100:.0f} cm" if len(res) > 2 else "✓ 2 pts")

    # ----------------------------------------------------- changer de vue
    def refresh_combo_vue(self):
        """La liste « Vue » de la barre : le profil, puis les ponts par Z.

        Elle dit la même chose que le tableau des vues de la colonne de
        droite, et elle est TOUJOURS là — le tableau, lui, se replie avec sa
        colonne. Deux listes qui divergeraient seraient pires qu'une : elles
        se refont toutes les deux depuis `project.views()`, et la sélection
        des deux suit la vue courante (`_sync_views_selection`)."""
        combo = getattr(self, "combo_vue", None)
        if combo is None:
            return
        combo.blockSignals(True)
        try:
            combo.clear()
            for key, label, deck, _cal in self.project.views():
                if deck is None:
                    combo.addItem("Profil longitudinal", "profil")
                else:
                    combo.addItem(f"{label}  ·  Z = {deck.z:g} m", id(deck))
            combo.setCurrentIndex(self._index_vue_courante())
        finally:
            combo.blockSignals(False)

    def _index_vue_courante(self):
        """La ligne de la liste « Vue » qui correspond à ce qu'on regarde."""
        combo = self.combo_vue
        if self.active == "pont" and self.current_deck is not None:
            cible = id(self.current_deck)
            for i in range(combo.count()):
                if combo.itemData(i) == cible:
                    return i
        return 0

    def _on_combo_vue(self, index):
        """Une vue choisie dans la barre : on y va."""
        data = self.combo_vue.itemData(index)
        if data == "profil":
            self.show_view("profil")
            return
        for d in self.project.decks:
            if id(d) == data:
                self.show_view(d)
                return

    def vue_voisine(self, sens):
        """Passe à la vue précédente (-1) ou suivante (+1) : Ctrl+Page↑/↓.

        « Il faudrait trouver un moyen plus simple de changer de pont » : le
        plus simple, c'est de ne pas lâcher la souris. Aux bouts, on s'arrête
        — on ne repart pas au profil quand on est au pont supérieur, ce serait
        un saut qu'on ne verrait pas venir."""
        vues = self.project.views()
        if not vues:
            return None
        i = self._index_vue_courante()
        j = min(max(i + sens, 0), len(vues) - 1)
        if j == i:
            self.statusBar().showMessage(
                "Première vue de la liste." if sens < 0
                else "Dernière vue de la liste.", 3000)
            return None
        _key, label, deck, _cal = vues[j]
        self.show_view(deck if deck is not None else "profil")
        self.statusBar().showMessage(f"Vue « {label} ».", 4000)
        return deck

    def refresh_views_table(self):
        # la liste de la barre et le tableau de la colonne se refont ENSEMBLE,
        # depuis la même source : elles ne peuvent pas diverger
        self.refresh_combo_vue()
        t = self.views_table
        t.blockSignals(True)
        t.setRowCount(0)
        cur = None
        for key, label, deck, cal in self.project.views():
            r = t.rowCount()
            t.insertRow(r)
            name = label + (f"  ({deck.alias})" if deck is not None and deck.alias else "")
            fichier = os.path.basename(cal.image_path) if cal.image_path else "—"
            if cal.from_dxf:
                n = len(cal.dxf_layers)
                fichier = (os.path.basename(cal.dxf_path)
                           + (f" ({n} calques)" if n else " (tous calques)"))
            elif cal.from_pdf:
                fichier = (f"{os.path.basename(cal.pdf_path)} p.{cal.pdf_page + 1}"
                           + (f" ↻{cal.pdf_rotation}°" if cal.pdf_rotation else ""))
            mark, etat = self._plan_state(cal)
            cells = [name, "—" if deck is None else f"{deck.z:g}", fichier,
                     f"{mark} {etat}" if mark != "✓" else etat,
                     "—" if deck is None else str(deck.n_capacities())]
            tips = [f"{name}\n{fichier}", "Hauteur sur ligne de base",
                    cal.image_path or "Aucun plan importé",
                    {"○": "Pas de plan : importez-en un",
                     "!": "L'image du plan (et son PDF) sont introuvables : "
                          "réimportez le plan",
                     "◐": f"{len(cal.cal_points)} point(s) de calage placé(s) — "
                          "appliquez le calage (2 points au moins)",
                     "✓": "Calé — écart résiduel maximal des points de référence"}[mark],
                    "Capacités tracées sur ce pont"]
            for c, txt in enumerate(cells):
                it = QTableWidgetItem(txt)
                it.setData(Qt.ItemDataRole.UserRole, key if deck is None else id(deck))
                it.setToolTip(tips[c])
                if c == 3:
                    it.setForeground(QColor(theme.OK if mark == "✓" else
                                            theme.WARN if mark == "◐" else
                                            theme.DANGER if mark == "!" else
                                            theme.TEXT_FAINT))
                t.setItem(r, c, it)
            if (deck is None and self.active == "profil") \
                    or (deck is not None and deck is self.current_deck and self.active == "pont"):
                cur = r
        if cur is not None:
            t.setCurrentCell(cur, 0)
            t.selectRow(cur)
        t.blockSignals(False)
        n = len(self.project.decks)
        self.views_hint.setText(
            f"{n} pont(s) · double-clic pour modifier."
            if n else "Créez une vue par niveau : fond de cale, entrepont, "
                      "pont principal…")

    def _selected_view(self):
        """('profil', None) ou ('pont', Deck) d'après la ligne choisie ;
        à défaut, la vue active."""
        rows = self.views_table.selectionModel().selectedRows() \
            if self.views_table.selectionModel() else []
        if rows:
            r = rows[0].row()
            data = self.views_table.item(r, 0).data(Qt.ItemDataRole.UserRole)
            if data == "profil":
                return "profil", None
            for d in self.project.decks:
                if id(d) == data:
                    return "pont", d
        if self.active == "pont" and self.current_deck is not None:
            return "pont", self.current_deck
        return "profil", None

    def on_views_selection(self):
        kind, deck = self._selected_view()
        self.show_view(deck if kind == "pont" else "profil")

    def show_view(self, target):
        """Rend une vue courante : "profil" ou un Deck (ou son nom)."""
        if isinstance(target, str) and target != "profil":
            target = next((d for d in self.project.decks if d.name == target), None)
        if target is None or target == "profil":
            self.set_active("profil")
            self._selected_deck = None
            self.show_profile_props()
        else:
            self.set_current_deck(target)
            self.set_active("pont")
            self.show_deck_props(target)
        self._sync_views_selection()
        self.refresh_wizard()

    def _sync_views_selection(self):
        """La ligne du tableau des vues ET la liste « Vue » de la barre suivent
        la vue courante."""
        combo = getattr(self, "combo_vue", None)
        if combo is not None and combo.count():
            i = self._index_vue_courante()
            if combo.currentIndex() != i:
                combo.blockSignals(True)
                combo.setCurrentIndex(i)
                combo.blockSignals(False)
        t = self.views_table
        for r in range(t.rowCount()):
            data = t.item(r, 0).data(Qt.ItemDataRole.UserRole)
            on = (data == "profil" and self.active == "profil") or \
                 (self.active == "pont" and self.current_deck is not None
                  and data == id(self.current_deck))
            if on and t.currentRow() != r:
                t.blockSignals(True)
                t.setCurrentCell(r, 0)
                t.selectRow(r)
                t.blockSignals(False)

    def edit_view_dialog(self):
        kind, deck = self._selected_view()
        if kind != "pont" or deck is None:
            QMessageBox.information(self, "Vue", "Le profil n'a ni nom ni Z à "
                                    "modifier : importez-le et calez-le.")
            return
        dlg = DeckDialog(self, name=deck.name, z=deck.z, alias=deck.alias,
                         title=f"Modifier la vue « {deck.name} »")
        if dlg.exec():
            deck.name, deck.z = dlg.values()
            deck.alias = dlg.alias()
            self.refresh_all()
            self.show_view(deck)

    def duplicate_view(self):
        kind, deck = self._selected_view()
        if kind != "pont" or deck is None:
            QMessageBox.information(self, "Dupliquer", "Choisissez un pont à dupliquer.")
            return
        dlg = DeckDialog(self, name=f"{deck.name} (copie)", z=deck.z, alias=deck.alias,
                         title=f"Dupliquer « {deck.name} »")
        if dlg.exec():
            name, z = dlg.values()
            d = self.project.duplicate_deck(deck, name, z)
            d.alias = dlg.alias()
            self.refresh_all()
            self.show_view(d)
            self.statusBar().showMessage(
                f"« {d.name} » créé avec le plan, le calage et le contour de "
                f"« {deck.name} » — les capacités ne sont pas copiées.", 8000)

    def delete_view(self):
        kind, deck = self._selected_view()
        if kind != "pont" or deck is None:
            QMessageBox.information(self, "Supprimer", "Le profil ne se supprime pas : "
                                    "remplacez son plan ou effacez son calage.")
            return
        self._delete_deck(deck)

    def _delete_deck(self, deck):
        n = deck.n_capacities()
        rep = QMessageBox.question(
            self, "Supprimer la vue",
            f"Supprimer le pont « {deck.name} » (Z = {deck.z:g} m)"
            + (f" et ses {n} capacité(s)" if n else "") + " ?\n\n"
            "Le fichier du plan reste dans le dossier du navire.")
        if rep != QMessageBox.StandardButton.Yes:
            return
        self.project.remove_deck(deck)
        if self.current_deck is deck:
            self.current_deck = None
        if self._selected_deck is deck:
            self._selected_deck = None
        if self._selected_calque and (self._selected_calque["parent"] is deck
                                      or self._selected_calque["parent"]
                                      in deck.capacities):
            self._selected_calque = None
        self._oublier_undo(list(deck.capacities) + [deck])
        self.props.setCurrentIndex(0)
        self.refresh_all()

    def import_plan_selected_view(self):
        kind, deck = self._selected_view()
        self.import_plan_for(deck if kind == "pont" else "profil")

    def calibrate_selected_view(self):
        kind, deck = self._selected_view()
        self.calibrate_view(deck if kind == "pont" else "profil")

    def calibrate_view(self, target):
        if target is None:
            return
        self.show_view(target)
        cal = self.project.profile if target == "profil" else target.plan
        if not cal.image_path:
            QMessageBox.information(self, "Calage", "Importez d'abord un plan "
                                    "pour cette vue.")
            return
        self._set_mode(MODE_CAL)

    # ------------------------------------------------------------------ arbre
    def refresh_tree(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        state = "calé" if self.project.profile.calibration.valid else "à caler"
        prof = QTreeWidgetItem([f"Profil longitudinal  ·  {state}"])
        prof.setData(0, Qt.ItemDataRole.UserRole, ("profile",))
        self.tree.addTopLevelItem(prof)
        for deck in self.project.sorted_decks():
            flag = "" if deck.plan.calibration.valid else "  ·  plan à caler"
            it = QTreeWidgetItem([f"{deck.name}   Z={deck.z:g} m{flag}"])
            it.setData(0, Qt.ItemDataRole.UserRole, ("deck", deck))
            # ce qui se chevauche se lit AUSSI dans l'arbre : la barre d'état
            # s'efface, l'arbre reste sous les yeux jusqu'à la correction
            chevauche = {}
            for a, b, _d in deck.recouvrements():
                chevauche.setdefault(id(a), []).append(b.code)
                chevauche.setdefault(id(b), []).append(a.code)
            for cap in deck.capacities:
                label = ("Contour du pont" if cap.kind == KIND_CONTOUR
                         else f"{cap.code}   {round(cap.fill * 100)} %")
                if cap.verrouillee:
                    label = "🔒 " + label
                voisins = chevauche.get(id(cap))
                if voisins:
                    label += "   ⚠ chevauche " + ", ".join(sorted(voisins))
                c = QTreeWidgetItem([label])
                c.setData(0, Qt.ItemDataRole.UserRole, ("cap", deck, cap))
                # Sous chaque cale, TOUT ce qui est posé dedans — le bord ne
                # trouvait ni ses zones de charge ni ses zones de hauteur : ici
                # elles se voient, se choisissent et se suppriment, même quand
                # leur calque est éteint sur le plan.
                for z in getattr(cap, "zones_charge", []) or []:
                    t = z.get("t_m2")
                    txt = f"▨ {z.get('nom') or 'zone de charge'}"
                    if isinstance(t, (int, float)):
                        txt += f"   {t:g} t/m²"
                    zc = QTreeWidgetItem([txt])
                    zc.setData(0, Qt.ItemDataRole.UserRole,
                               ("zone", deck, cap, z))
                    c.addChild(zc)
                for o in getattr(cap, "obstacles", []) or []:
                    if len(o) < 4:
                        continue
                    h = hauteur_annoncee(o)
                    nom = (o[4] if len(o) > 4 else "") or "zone interdite"
                    oc = QTreeWidgetItem([("↧ " if h > 0 else "▩ ") + str(nom)])
                    oc.setData(0, Qt.ItemDataRole.UserRole,
                               ("obstacle", deck, cap, o))
                    c.addChild(oc)
                for e in getattr(cap, "epontilles", []) or []:
                    ec = QTreeWidgetItem([f"⌖ {e.get('nom') or e.get('id')}"])
                    ec.setData(0, Qt.ItemDataRole.UserRole,
                               ("epontille", deck, cap, e))
                    c.addChild(ec)
                c.setExpanded(True)
                it.addChild(c)
            # le calque d'information appartient au PONT, pas à une cale
            for note in getattr(deck, "annotations", []) or []:
                forme = str(note.get("type") or "trait")
                titre = (note.get("texte") or "").strip() \
                    or NOMS_FORMES_ANNOTATION.get(forme, forme)
                ac = QTreeWidgetItem(["✎ " + titre])
                ac.setData(0, Qt.ItemDataRole.UserRole,
                           ("annotation", deck, note))
                it.addChild(ac)
            self.tree.addTopLevelItem(it)
            it.setExpanded(True)
        self.tree.blockSignals(False)

    def on_tree_selection(self):
        items = self.tree.selectedItems()
        if not items:
            return
        data = items[0].data(0, Qt.ItemDataRole.UserRole)
        if data[0] == "deck":
            self.show_view(data[1])
        elif data[0] == "cap":
            self.set_current_deck(data[1])
            self.select_capacity(data[2])
        elif data[0] == "epontille":
            self.set_current_deck(data[1])
            self.select_epontille(data[2], data[3])
        elif data[0] in ("zone", "obstacle"):
            self.set_current_deck(data[1])
            self.select_objet_calque(data[0], data[2], data[3])
        elif data[0] == "annotation":
            self.set_current_deck(data[1])
            self.select_objet_calque("annotation", data[1], data[2])
        else:
            self.show_view("profil")

    def delete_tree_selection(self):
        items = self.tree.selectedItems()
        if not items:
            return
        data = items[0].data(0, Qt.ItemDataRole.UserRole)
        if data[0] == "deck":
            self._delete_deck(data[1])
        elif data[0] == "cap":
            # on passe par le chemin officiel (sélectionner, puis supprimer) :
            # retirer la capacité de la liste à la main laissait
            # `_selected_capacity` pointer sur un objet disparu et gardait ses
            # retouches dans la pile d'annulation — Ctrl+Z disait alors
            # « Retouche annulée » sans plus rien restaurer
            self.set_current_deck(data[1])
            self.select_capacity(data[2])
            self.delete_selected_capacity()
        elif data[0] == "epontille":
            self.select_epontille(data[2], data[3])
            self.delete_selected_epontille()
        elif data[0] in ("zone", "obstacle"):
            # même chemin officiel que pour une cale : on choisit, puis on
            # supprime — la sélection et la pile d'annulation restent justes
            self.set_current_deck(data[1])
            self.select_objet_calque(data[0], data[2], data[3])
            self.delete_selected_calque()
        elif data[0] == "annotation":
            self.set_current_deck(data[1])
            self.select_objet_calque("annotation", data[1], data[2])
            self.delete_selected_calque()

    # ------------------------------------------------------------------ modes
    def set_active(self, name):
        self.active = name
        for header, key in ((self.header_profile, "profil"),
                            (self.header_deck, "pont")):
            on = (key == name)
            header.setStyleSheet(
                "" if on else f"border-left-color: {theme.BORDER_SOFT};")
        self._update_snap_state()

    def start_mode(self, name):
        """Point d'entrée public (utilisé par l'assistant)."""
        self._set_mode({"cal": MODE_CAL, "decks": MODE_DECKS, "poly": MODE_POLY,
                        "contour": MODE_CONTOUR,
                        "epontille": MODE_EPONTILLE,
                        "zone_charge": MODE_ZONE_CHARGE,
                        "hauteur": MODE_HAUTEUR,
                        "interdit": MODE_INTERDIT,
                        "info": MODE_INFO}.get(name, MODE_SELECT))

    def _toggle_mode(self, mode, checked):
        if checked:
            self._set_mode(mode)
        elif self.mode == mode:
            self._set_mode(MODE_SELECT)

    def _set_mode(self, mode):
        if mode == MODE_DECKS and not self.project.profile.calibration.valid:
            self.statusBar().showMessage(
                "Calez d'abord le profil avant de définir les ponts.")
            mode = MODE_SELECT
        if mode in (MODE_EPONTILLE, MODE_INFO) or mode in MODES_POLYGONE \
                or mode in MODES_RECTANGLE:
            if self.current_deck is None or not self.current_deck.plan.calibration.valid:
                self.statusBar().showMessage(
                    "Sélectionnez un pont dont le plan est calé avant de tracer.")
                mode = MODE_SELECT
            else:
                self.set_active("pont")
        if mode == MODE_DECKS:
            self.set_active("profil")
        self.mode = mode
        self._cancel_poly()
        self._cancel_rect()
        self._drag = None
        for a, m in ((self.act_select, MODE_SELECT), (self.act_cal, MODE_CAL),
                     (self.act_decks, MODE_DECKS), (self.act_poly, MODE_POLY),
                     (self.act_contour, MODE_CONTOUR),
                     (self.act_epontille, MODE_EPONTILLE),
                     (self.act_trait, MODE_TRAIT),
                     (self.act_zone_charge, MODE_ZONE_CHARGE),
                     (self.act_hauteur, MODE_HAUTEUR),
                     (self.act_interdit, MODE_INTERDIT),
                     (self.act_info, MODE_INFO)):
            a.blockSignals(True)
            a.setChecked(m == mode)
            a.blockSignals(False)
        cursor = self.cursor_for_mode()
        self.profile_view.viewport().setCursor(cursor)
        self.deck_view.viewport().setCursor(cursor)
        self._clic_trace = None
        # changer d'outil abandonne le rectangle en cours : un premier coin
        # resté armé aurait posé la zone suivante depuis un point oublié
        self._cancel_rect()
        deck_name = self.current_deck.name if self.current_deck else "?"
        msgs = {
            MODE_SELECT: "Mode sélection — cliquez une cale, puis glissez une "
                         "poignée pour déplacer un sommet. AJOUTER un sommet : "
                         "clic droit sur un segment (« Ajouter un sommet "
                         "ici ») ou double-clic dessus. Clic droit : "
                         "verrouiller la cale ou le sommet visé.",
            MODE_CAL: f"Calage de la vue « {self.active} » : cliquez un point connu, "
                      "donnez son intitulé et ses coordonnées, puis « Appliquer ».",
            MODE_DECKS: "Cliquez la ligne de chaque pont sur le profil "
                        "— la hauteur Z est pré-remplie.",
            MODE_POLY: f"Tracé d'une capacité sur « {deck_name} » : "
                       "cliquez les sommets, double-clic pour terminer.",
            MODE_CONTOUR: f"Tracé du contour de « {deck_name} » : "
                          "cliquez les sommets, double-clic pour terminer.",
            MODE_EPONTILLE: f"Épontilles de « {deck_name} » : cliquez le point "
                            "où l'épontille se dresse — il doit être DANS une "
                            "cale. Sa fiche dit si elle est fixe ou amovible.",
            MODE_TRAIT: "Trait de construction : cliquez où passe la droite. "
                        "Elle traverse le plan à cette cote, et le curseur "
                        "s'y accroche ensuite.",
            MODE_ZONE_CHARGE: f"Zone de charge sur « {deck_name} » : cliquez "
                              "les sommets DANS une cale, double-clic pour "
                              "terminer. Calque signalé, non bloquant (D-12).",
            MODE_HAUTEUR: f"Hauteur libre sur « {deck_name} » : glissez d'un "
                          "coin à l'autre, ou cliquez deux coins opposés, "
                          "DANS une cale. Calque signalé, non "
                          "bloquant (D-21).",
            MODE_INTERDIT: f"Structure sur « {deck_name} » : glissez d'un "
                           "coin à l'autre, ou cliquez deux coins opposés, "
                           "DANS une cale. BLOQUANT : rien ne s'y posera. "
                           "(Une épontille fixe : outil Épontille, case "
                           "« fixe ».)",
            MODE_INFO: f"Information sur « {deck_name} » : "
                       + self._aide_forme_info()
                       + " Rien n'en dépend.",
        }
        self.statusBar().showMessage(msgs[mode])
        if mode in (MODE_CAL, MODE_EPONTILLE, MODE_TRAIT, MODE_INFO) \
                or mode in MODES_POLYGONE or mode in MODES_RECTANGLE:
            # c'est ici qu'on a besoin des sommets du fond : la lecture part
            # en tâche de fond (une fois par session et par plan), avec un
            # message — jamais en silence, jamais en figeant la fenêtre
            self._ensure_vector_index(self._scene_for(self.active).calibrated)
        for scene in (self.profile_scene, self.deck_scene):
            scene.show_snap(None)
        self._refresh_hud()
        self.refresh_wizard()

    # ------------------------------------------------------------------ accroche
    def toggle_snap(self, checked):
        self.snap_enabled = bool(checked)
        self._update_snap_state()
        if not checked:
            for scene in (self.profile_scene, self.deck_scene):
                scene.show_snap(None)
        self._refresh_hud()

    def _update_snap_state(self):
        txt = self.etat_accroche(self._scene_for(self.active).calibrated)
        self.act_snap.setStatusTip(txt)
        self.act_snap.setToolTip(txt + "\nMaj enfoncée : accroche suspendue.")

    @staticmethod
    def _origine_traits(cal) -> str:
        """D'où sortent les sommets accrochables de cette vue.

        Le fichier de sommets rangé avec le navire (`traits_plan`) passe avant
        le PDF du chantier, qui souvent n'a pas voyagé : dire « du PDF » quand
        le PDF n'est plus là, c'est envoyer chercher un fichier absent."""
        src = source_traits(cal)
        if src is None:
            return "du plan"
        from . import traits_plan
        if src[0] is traits_plan:
            return "du plan, rangés avec le navire"
        return "du DXF" if getattr(cal, "from_dxf", False) else "du PDF"

    def etat_accroche(self, cal) -> str:
        """Une phrase disant d'où viennent les points d'accroche de la vue —
        et, pendant la lecture des traits, qu'elle est en cours."""
        if cal is None or not source_traits(cal):
            return ("Accroche : tracés et points de calage "
                    "(pas de plan vectoriel sur cette vue).")
        quoi = "DXF" if getattr(cal, "from_dxf", False) else "PDF"
        idx = self._vector_index(cal)
        if idx is not None:
            n = f"{len(idx):,}".replace(",", " ")
            return (f"Accroche prête : {n} sommets "
                    f"{self._origine_traits(cal)} "
                    "+ tracés + points de calage.")
        rate = self.chargeur.echec_de(cal)
        if rate:
            return (f"Accroche : traits du {quoi} illisibles ({rate}) — "
                    "il reste les tracés et les points de calage.")
        if self.chargeur.en_lecture(cal):
            return (f"Accroche : lecture des traits du {quoi}… "
                    "(les tracés et les points de calage marchent déjà).")
        return (f"Accroche : traits du {quoi} non encore lus "
                "(lecture au premier calage ou tracé).")

    def _vector_index(self, cal):
        """L'index d'accroche des traits du fond **s'il est prêt** — jamais un
        index en cours de construction (voir `scene.ChargeurTraits`)."""
        return self.chargeur.index(cal) if cal is not None else None

    # rétrocompatibilité : l'ancien nom, du temps où seul le PDF s'accrochait
    def _pdf_index(self, cal):
        return self._vector_index(cal)

    def _ensure_vector_index(self, cal):
        """Demande la lecture des traits de la vue si elle n'est pas faite.

        Ne bloque jamais : la lecture part dans un fil de fond et la fenêtre
        reste maniable. L'accroche est simplement absente jusqu'à ce que
        `_traits_prets` la rende — impossible, donc, de se servir d'un index à
        moitié construit."""
        if cal is None or not source_traits(cal):
            return None
        idx = self.chargeur.demander(cal)
        if idx is None and self.chargeur.en_lecture(cal):
            # un petit plan est déjà lu au bout de ce sursis : inutile de
            # priver l'utilisateur de l'accroche pour quelques millisecondes
            self.chargeur.attendre(SURSIS_TRAITS_MS)
            idx = self.chargeur.index(cal)
        if idx is not None:
            # le dire : le bord affirmait n'avoir « aucune accroche », faute
            # que quoi que ce soit à l'écran lui dise qu'elle était là
            self.statusBar().showMessage(self.etat_accroche(cal), 8000)
        if idx is None and self.chargeur.en_lecture(cal):
            quoi = "DXF" if getattr(cal, "from_dxf", False) else "PDF"
            self.statusBar().showMessage(
                f"Lecture des traits du {quoi} pour l'accroche… "
                "(vous pouvez continuer, l'accroche s'activera toute seule)")
        rate = self.chargeur.echec_de(cal)
        if rate:
            self.statusBar().showMessage(
                f"Traits du plan illisibles ({rate}) : pas d'accroche aux "
                "traits sur cette vue, seulement aux tracés.", 10000)
        self._update_snap_state()
        return idx

    def _ensure_pdf_index(self, cal):
        """Comme `_ensure_vector_index`, mais **en attendant** la fin de la
        lecture. L'interface ne s'en sert pas — elle n'attend jamais — ; c'est
        le chemin des scripts et des tests qui veulent l'accroche tout de
        suite après un import."""
        self._ensure_vector_index(cal)
        if cal is None or not source_traits(cal):
            return None
        idx = self.chargeur.attendre_index(cal)
        self._update_snap_state()
        return idx

    def _traits_prets(self, cle):
        """Un index de traits vient d'être rangé : on le dit, sans déranger."""
        for nom in ("profil", "pont"):
            cal = self._scene_for(nom).calibrated
            src = source_traits(cal)
            if src is not None and src[2] == cle:
                idx = self._vector_index(cal)
                if idx is not None:
                    n = f"{len(idx):,}".replace(",", " ")
                    self.statusBar().showMessage(
                        f"Accroche prête : {n} sommets lus dans le plan, le "
                        "curseur s'y accroche (Maj pour suspendre).", 8000)
                break
        self._update_snap_state()
        self._refresh_hud()

    def _traits_rates(self, cle, message):
        self.statusBar().showMessage(
            f"Traits du plan illisibles ({message}) : il reste l'accroche aux "
            "tracés et aux points de calage.", 10000)
        self._update_snap_state()

    def _local_snap_index(self, name):
        """Index d'accroche des tracés de la vue, bâti une fois et gardé.

        Le sommet qu'on tire n'en est PAS retiré : `pdf_plan.snap` l'écarte par
        son argument `exclude` — il ne bouge pas dans `cap.points` tant que le
        glisser n'est pas relâché, l'index reste donc juste. Le rebâtir à
        chaque mouvement de souris coûtait 2,1 ms par mouvement sur 313
        sommets, alors que les autres sommets, eux, ne bougent pas."""
        idx = self._local_index.get(name)
        if idx is None:
            idx = self._scene_for(name).local_snap_index()
            self._local_index[name] = idx
        return idx

    def _snap(self, view, scene_pos, modifiers, exclude_capacity=None,
              exclude_vertex=None):
        """(point retenu, accroché ?) : le sommet le plus proche à moins de
        SNAP_PX pixels d'écran, parmi les traits du fond vectoriel (PDF ou
        DXF), les tracés et les points de calage — sauf accroche suspendue
        (bouton ou Maj). Si les traits ne sont pas encore lus, l'accroche se
        contente des tracés : elle n'attend jamais."""
        if not self.snap_enabled or (modifiers & Qt.KeyboardModifier.ShiftModifier):
            return scene_pos, False
        scene = view.scene()
        if scene.calibrated is None or scene.pixmap_item is None:
            return scene_pos, False
        radius = SNAP_PX / view.view_scale()
        exclude = None
        if exclude_capacity is not None and exclude_vertex is not None \
                and scene.calibrated.calibration.valid:
            pt = exclude_capacity.points[exclude_vertex]
            exclude = scene.calibrated.calibration.to_pixel(*pt)
        # la règle d'arbitrage (sommets d'abord, croisement de traits de
        # construction ensuite) est dans `scene.accrocher` : c'est LE geste de
        # l'application, il n'en existe qu'un exemplaire
        return accrocher(scene_pos, radius,
                         [self._vector_index(scene.calibrated),
                          self._local_snap_index(view.name)],
                         getattr(scene, "construction_lines", None) or (),
                         exclude=exclude)

    # ------------------------------------------------------------------ souris
    def _scene_for(self, name):
        return self.profile_scene if name == "profil" else self.deck_scene

    def _view_for(self, name):
        return self.profile_view if name == "profil" else self.deck_view

    def _selected_item(self):
        """L'objet polygone sélectionné sur la vue du pont, s'il y en a un."""
        if self._selected_capacity is None:
            return None
        it = self.deck_scene.item_for_capacity(self._selected_capacity)
        return it if isinstance(it, DeckCapacityItem) and it.isSelected() else None

    # ------------------------------------------------------- recouvrements
    @staticmethod
    def _cm(metres) -> str:
        return f"{metres * 100:.0f} cm" if metres < 1 else f"{metres:.2f} m"

    def recouvrements_du_pont(self):
        """Les cales du pont courant qui se mordent : [(a, b, mètres)]."""
        if self.current_deck is None:
            return []
        return self.current_deck.recouvrements()

    def avertissement_recouvrements(self) -> str:
        """La phrase d'alerte du pont courant, ou "" si tout va bien.

        C'est un AVERTISSEMENT, pas un refus (D-12 et D-21 disent déjà que ce
        qui vient d'un tracé se signale) : deux cales qui se mordent, c'est
        du fret compté deux fois et une cale impossible à viser au clic — mais
        le bord doit pouvoir enregistrer un plan à moitié retracé."""
        rec = self.recouvrements_du_pont()
        if not rec:
            return ""
        bouts = [f"{a.code} et {b.code} ({self._cm(d)})" for a, b, d in rec[:3]]
        reste = "" if len(rec) <= 3 else f", et {len(rec) - 3} autre(s)"
        return ("⚠ Cales qui se chevauchent sur ce pont : "
                + " ; ".join(bouts) + reste
                + " — à corriger, mais l'enregistrement reste possible.")

    def _dire_recouvrements(self, prefixe=""):
        """Met l'avertissement dans la barre d'état, s'il y en a un."""
        msg = self.avertissement_recouvrements()
        if not msg:
            return False
        self.statusBar().showMessage((prefixe + "   " if prefixe else "")
                                     + msg, 12000)
        return True

    # ------------------------------------------------------------- verrous
    def _dire_verrou_cale(self, cap, geste="être retouchée"):
        self.statusBar().showMessage(
            f"Cale {cap.code} VERROUILLÉE : elle ne peut pas {geste}. "
            "Clic droit sur la cale → « Déverrouiller la cale », ou décochez "
            "« Verrouillée » dans Propriétés.", 8000)

    def _verrou_refuse(self, cap, index, geste="déplacer") -> bool:
        """Ce sommet est-il figé ? Si oui, on le DIT — jamais de refus muet.

        C'est le seul point de passage : glisser, flèches des champs X/Y,
        insertion, suppression, tous demandent ici."""
        if cap is None or index is None:
            return False
        if cap.verrouillee:
            self._dire_verrou_cale(cap, "être retouchée")
            return True
        if cap.sommet_verrouille(index):
            self.statusBar().showMessage(
                f"Sommet n°{index + 1} de {cap.code} VERROUILLÉ : impossible "
                f"de le {geste}. Clic droit dessus → « Déverrouiller ce "
                "sommet ».", 8000)
            return True
        return False

    # ------------------------------------------------------- choix d'une cale
    def _cales_sous(self, scene_pos):
        """Les objets-cales du pont dont le contour contient ce point.

        Les vraies cales d'abord, le contour de pont en dernier : il englobe
        tout par construction, et s'il passait devant on ne cliquerait plus
        jamais une cale."""
        cales, contours = [], []
        for it in _vivants(self.deck_scene.object_items):
            if not isinstance(it, DeckCapacityItem) or not it.isVisible():
                continue
            if not it.polygon().containsPoint(scene_pos,
                                              Qt.FillRule.OddEvenFill):
                continue
            (contours if it.capacity.kind == KIND_CONTOUR else cales).append(it)
        return cales or contours

    def _choisir_cale_sous(self, scene_pos) -> bool:
        """Choisit la cale visée ; un clic de plus au même endroit passe à la
        suivante.

        Là où deux cales se recouvrent, la seconde tracée masquait la première
        et le clic ne rendait jamais qu'elle. Le cycle donne accès aux deux —
        l'arbre *Structure*, lui, les liste toutes en permanence."""
        caps = [it.capacity for it in self._cales_sous(scene_pos)]
        if not caps:
            return False
        cur = self._selected_capacity
        i = next((k for k, c in enumerate(caps) if c is cur), None)
        cap = caps[(i + 1) % len(caps)] if i is not None else caps[0]
        if cap is cur:
            return True
        self.select_capacity(cap)
        if len(caps) > 1:
            self.statusBar().showMessage(
                f"{cap.code or 'Contour'} — {len(caps)} tracés se recouvrent "
                "ici : cliquez encore au même endroit pour passer au suivant.",
                8000)
        return True

    def _snapping_now(self, name):
        return ((self.mode in (MODE_CAL, MODE_EPONTILLE, MODE_TRAIT, MODE_INFO)
                 or self.mode in MODES_POLYGONE or self.mode in MODES_RECTANGLE)
                and name == self.active) \
            or (self._drag is not None
                and self._drag["kind"] in ("vertex", "epontille"))

    def view_press(self, view, event) -> bool:
        name = view.name
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        scene_pos = view.scene_pos(event)
        mods = event.modifiers()
        if self.mode == MODE_SELECT and name == "pont":
            # une épontille se saisit directement, sans avoir à la choisir
            # d'abord : c'est un objet ponctuel, pas un contour à retoucher
            objet = self._objet_calque_sous(scene_pos)
            if isinstance(objet, EpontilleItem):
                self.select_epontille(objet.capacity, objet.epontille)
                self._start_drag_epontille(objet, scene_pos)
                return True
            if objet is not None:
                self.select_objet_calque_item(objet)
                return True
            item = self._selected_item()
            if item is not None:
                # LE SOMMET D'ABORD, et par la GÉOMÉTRIE plutôt que par
                # `itemAt` : le tir d'écran rendait la cale dessinée par-dessus,
                # et le sommet de la cale choisie, pourtant sous le curseur,
                # était perdu (« on ne peut plus sélectionner un sommet caché
                # par la cale qui superpose »). Un sommet de la cale
                # SÉLECTIONNÉE gagne donc sur le remplissage de toute autre.
                iv = item.hit_vertex(scene_pos, VERTEX_PX / view.view_scale())
                if iv is not None:
                    self._set_selected_vertex(iv)
                    if self._verrou_refuse(item.capacity, iv, "déplacer"):
                        return True
                    self._start_drag("vertex", item, scene_pos, iv)
                    return True
                # un autre polygone sous le curseur (une cale dans le contour
                # du pont) : on le laisse se sélectionner, on ne déplace pas
                if item.polygon().containsPoint(scene_pos, Qt.FillRule.OddEvenFill):
                    if item.capacity.kind == KIND_CONTOUR \
                            and any(c is not item
                                    for c in self._cales_sous(scene_pos)):
                        # une cale posée DANS le contour du pont prend le
                        # clic : sans quoi on déplacerait le pont entier en
                        # croyant saisir la cale
                        return self._choisir_cale_sous(scene_pos)
                    if item.capacity.verrouillee:
                        # jamais de refus muet : on dit le verrou et comment
                        # l'ôter, plutôt que de laisser croire à un plantage
                        self._dire_verrou_cale(item.capacity, "se déplacer")
                        return True
                    self._start_drag("move", item, scene_pos)
                    return True
            # rien d'autre n'a pris le clic : c'est une CALE qu'on vise, et
            # là où deux se recouvrent, un clic de plus passe à la suivante
            return self._choisir_cale_sous(scene_pos)
        if self.mode == MODE_CAL and name == self.active:
            self.on_click(name, scene_pos, mods, view)
            return True
        if self.mode == MODE_DECKS and name == "profil":
            self.on_click(name, scene_pos, mods, view)
            return True
        if ((self.mode in (MODE_EPONTILLE, MODE_INFO)
             or self.mode in MODES_POLYGONE or self.mode in MODES_RECTANGLE)
                and name == "pont") \
                or (self.mode == MODE_TRAIT and name == self.active):
            # le sommet n'est posé qu'au relâchement, et seulement si la
            # souris n'a pas voyagé : un geste de déplacement (Espace, ou
            # simplement une main qui traîne) ne doit jamais poser un sommet
            # — ni une épontille
            self._clic_trace = (view, QPointF(scene_pos), event.position(), mods)
            return True
        return False

    def view_move(self, view, event) -> bool:
        name = view.name
        scene_pos = view.scene_pos(event)
        mods = event.modifiers()
        scene = view.scene()
        pos, snapped = scene_pos, False
        if self._drag is not None and self._drag["kind"] == "vertex" and name == "pont":
            d = self._drag
            pos, snapped = self._snap(view, scene_pos, mods, d["item"].capacity, d["index"])
            self._drag["moved"] = True
            pts = [QPointF(p) for p in d["item"].polygon()]
            pts[d["index"]] = pos
            d["item"].set_pixel_polygon(QPolygonF(pts))
            scene.show_snap(pos if snapped else None)
            self._status_coords(name, pos, snapped)
            return True
        if self._drag is not None and self._drag["kind"] == "epontille" \
                and name == "pont":
            d = self._drag
            pos, snapped = self._snap(view, scene_pos, mods)
            delta = pos - d["start"]
            if not d["moved"] and math.hypot(delta.x(), delta.y()) \
                    * view.view_scale() < DRAG_PX:
                return True
            d["moved"] = True
            centre = d["centre"] + delta
            d["item"].setPos(centre - d["item"].centre_pixel())
            scene.show_snap(pos if snapped else None)
            self._status_coords(name, centre, snapped)
            return True
        if self._drag is not None and self._drag["kind"] == "move" and name == "pont":
            d = self._drag
            delta = scene_pos - d["start"]
            if not d["moved"] and math.hypot(delta.x(), delta.y()) * view.view_scale() < DRAG_PX:
                return True
            d["moved"] = True
            poly = QPolygonF([p + delta for p in d["orig_poly"]])
            d["item"].set_pixel_polygon(poly)
            self._status_coords(name, scene_pos, False)
            return True
        if self._snapping_now(name):
            pos, snapped = self._snap(view, scene_pos, mods)
            scene.show_snap(pos if snapped else None)
            self._last_snap = (pos, snapped)
        self._status_coords(name, pos, snapped)
        if self._poly_points and name == "pont" and (
                self.mode in MODES_POLYGONE or self.mode == MODE_INFO):
            self._update_poly_preview(pos)
        # Un rectangle se trace aussi d'un GLISSER : dès que la souris quitte
        # le point d'appui, le premier coin est posé et l'aperçu suit — sans
        # cela le geste le plus naturel (appuyer, tirer, lâcher) ne donnait
        # rien du tout, et c'est ce qui est arrivé au bord.
        if self.mode in MODES_RECTANGLE and name == "pont" \
                and self._clic_trace is not None:
            v, depart, ecran, mods_appui = self._clic_trace
            d = event.position() - ecran
            if math.hypot(d.x(), d.y()) > CLIC_PX and not v.panning:
                if self._rect_start is None:
                    self._rect_start = self._snap(v, depart, mods_appui)[0]
                # un glisser après un premier clic termine lui aussi le
                # rectangle : autrement le geste restait sans effet et le
                # premier coin traînait, armé, jusqu'au clic suivant
                self._rect_glisser = True
        if self.mode in MODES_RECTANGLE and self._rect_start is not None \
                and name == "pont":
            self._update_rect_preview(pos)
        return False

    def view_release(self, view, event) -> bool:
        clic = self._clic_trace
        self._clic_trace = None
        if clic is not None and event.button() == Qt.MouseButton.LeftButton:
            v, scene_pos, ecran, mods = clic
            d = event.position() - ecran
            if math.hypot(d.x(), d.y()) <= CLIC_PX and not v.panning:
                self.on_click(v.name, scene_pos, mods, v)
            elif self._rect_glisser and self.mode in MODES_RECTANGLE:
                # relâchement d'un glisser : c'est le COIN OPPOSÉ, et le
                # rectangle est fini — inutile d'attendre un second clic
                p1 = self._rect_start
                self._cancel_rect()
                if p1 is not None:
                    self.poser_rectangle_calque(
                        p1, self._snap(v, v.scene_pos(event), mods)[0])
            return True
        if self._drag is None or event.button() != Qt.MouseButton.LeftButton:
            return False
        cal = (self.deck_scene.calibrated.calibration
               if self.deck_scene.calibrated else None)
        rien = not self._drag["moved"] or cal is None or not cal.valid
        if self._drag["kind"] == "epontille":
            if rien:
                self._annuler_drag()
                return True
            d, self._drag = self._drag, None
            self.deck_scene.show_snap(None)
            item = d["item"]
            centre = item.centre_pixel() + item.pos()
            x, y = _real(cal, centre)
            self.deplacer_epontille(d["capacity"], d["epontille"], x, y)
            return True
        if rien:
            d = self._annuler_drag()
            # un appui-relâchement SANS déplacement, c'est un clic : là où
            # plusieurs cales se recouvrent, il passe à la suivante
            if d is not None and d.get("kind") == "move" and not d.get("moved"):
                self._choisir_cale_sous(d["start"])
            return True
        d, self._drag = self._drag, None
        item = d["item"]
        cap = item.capacity
        self._push_undo(cap)
        poly = item.polygon()
        # au dixième de millimètre : un sommet accroché sur celui d'une cale
        # voisine doit lui être exactement égal, pas à 1e-15 près
        cap.points = [_real(cal, poly.at(i)) for i in range(poly.count())]
        self.deck_scene.show_snap(None)
        self._after_edit()
        # un contour qu'on vient de retoucher peut mordre son voisin : c'est
        # le moment de le dire, pas trois manœuvres plus tard
        self._dire_recouvrements()
        return True

    def view_double_click(self, view, event) -> bool:
        name = view.name
        scene_pos = view.scene_pos(event)
        if name == "pont" and (self.mode in MODES_POLYGONE
                               or (self.mode == MODE_INFO
                                   and self._info_forme in FORMES_TRACEES_INFO)):
            self._drag = None
            self.finish_polygon()
            return True
        if name == "pont" and self.mode in MODES_RECTANGLE:
            # Deux clics au même endroit, c'est un double-clic — et jusqu'ici
            # il laissait un premier coin armé sans un mot. On abandonne et on
            # dit les DEUX gestes possibles : c'est très exactement ce que le
            # bord n'a pas trouvé (« la création de forme ne fonctionne pas »).
            self._drag = None
            self._cancel_rect()
            self.statusBar().showMessage(
                "Un double-clic ne trace pas de rectangle : tracez un "
                "rectangle — glissez d'un coin à l'autre, ou cliquez deux "
                "coins OPPOSÉS.", 8000)
            return True
        if self.mode == MODE_SELECT and name == "pont":
            item = self._selected_item()
            if item is not None:
                self._drag = None
                # même chemin que le clic droit → « Ajouter un sommet ici » :
                # deux gestes, une seule règle
                if self.inserer_sommet_sur_arete(item, scene_pos, view):
                    return True
        return False

    def view_leave(self, view):
        view.scene().show_snap(None)

    # -------------------------------------------------------- menu contextuel
    def menu_pour_objet(self, scene_pos):
        """(QMenu, description) de l'objet sous ce point, ou (None, "").

        Un menu par objet, avec les deux seules choses qu'on veut en faire :
        voir ses champs, et le supprimer. Pour une épontille amovible, le menu
        rappelle en plus qu'elle se DÉPLACE en la glissant — le bord ne le
        savait pas."""
        item = self._objet_calque_sous(scene_pos)
        if item is None:
            return None, ""
        menu = QMenu(self)
        if isinstance(item, EpontilleItem):
            quoi = f"Épontille « {item.epontille.get('nom') or ''} »"
            choisir = lambda: self.select_epontille(item.capacity,
                                                    item.epontille)
            supprimer = self.delete_selected_epontille
            glisser = True
        else:
            noms = {"zone": "Zone de charge", "obstacle": "Zone",
                    "annotation": "Information"}
            quoi = noms[self._quoi_item(item)]
            choisir = lambda: self.select_objet_calque_item(item)
            supprimer = self.delete_selected_calque
            glisser = False
        titre = menu.addAction(quoi)
        titre.setEnabled(False)
        menu.addSeparator()
        a_props = menu.addAction("Propriétés…")
        a_props.triggered.connect(lambda *_: (choisir(),
                                              self.sec_props.set_open(True)))
        if glisser:
            a_glisser = menu.addAction("Glisser pour déplacer")
            a_glisser.setEnabled(False)
            a_glisser.setToolTip("En mode Sélection, saisissez-la et "
                                 "faites-la glisser dans sa cale.")
        a_suppr = menu.addAction(theme.icon("trash"), "Supprimer")
        a_suppr.triggered.connect(lambda *_: (choisir(), supprimer()))
        return menu, quoi

    def menu_pour_cale(self, scene_pos, view):
        """(QMenu, description) pour la CALE visée par un clic droit.

        Trois menus selon ce qu'on vise dans la cale sélectionnée, du plus
        précis au plus large :

        - un **sommet** : le verrouiller ou le libérer, le retirer ;
        - un **segment** : « Ajouter un sommet ici ». C'est le geste que le
          bord n'a pas trouvé — l'insertion n'existait qu'au double-clic sur
          une arête, et il a conclu que c'était « impossible ». Le double-clic
          reste ;
        - le **remplissage** : verrouiller la cale entière, ses propriétés.

        Rien de sélectionné : le clic droit sur une cale la choisit et propose
        déjà son verrou."""
        item = self._selected_item()
        if item is None:
            cales = self._cales_sous(scene_pos)
            item = cales[0] if cales else None
        if item is None:
            return None, ""
        cap = item.capacity
        echelle = view.view_scale()
        nom = "Contour du pont" if cap.kind == KIND_CONTOUR else f"Cale {cap.code}"
        if cap.verrouillee:
            nom += " 🔒"
        menu = QMenu(self)

        iv = item.hit_vertex(scene_pos, VERTEX_PX / echelle)
        arete = None if iv is not None else item.hit_edge(scene_pos,
                                                          EDGE_PX / echelle)
        if iv is not None:
            quoi = f"Sommet n°{iv + 1} — {nom}"
            titre = menu.addAction(quoi)
            titre.setEnabled(False)
            menu.addSeparator()
            fige = cap.sommet_verrouille(iv)
            a_v = menu.addAction("Déverrouiller ce sommet" if fige
                                 else "Verrouiller ce sommet")
            a_v.setEnabled(not cap.verrouillee)
            a_v.triggered.connect(
                lambda *_, i=iv: self.basculer_verrou_sommet(cap, i))
            if not fige:
                a_s = menu.addAction(theme.icon("trash"), "Retirer ce sommet")
                a_s.triggered.connect(
                    lambda *_, i=iv: (self.select_capacity(cap),
                                      self._set_selected_vertex(i),
                                      self.delete_selected_vertex()))
        elif arete is not None:
            quoi = f"Segment n°{arete[0] + 1} — {nom}"
            titre = menu.addAction(quoi)
            titre.setEnabled(False)
            menu.addSeparator()
            if cap.verrouillee:
                # pas d'entrée grisée sans explication : on dit le verrou, et
                # le bas du menu propose déjà de l'ôter
                mot = menu.addAction("Cale verrouillée : aucun sommet à "
                                     "ajouter ici")
                mot.setEnabled(False)
            else:
                a_i = menu.addAction("Ajouter un sommet ici")
                a_i.setToolTip("Le sommet se pose sur le segment, à l'endroit "
                               "cliqué (double-clic : même chose).")
                a_i.triggered.connect(
                    lambda *_, p=QPointF(scene_pos):
                    self.inserer_sommet_sur_arete(item, p, view))
        else:
            quoi = nom
            titre = menu.addAction(quoi)
            titre.setEnabled(False)
            menu.addSeparator()
            a_p = menu.addAction("Propriétés…")
            a_p.triggered.connect(lambda *_: (self.select_capacity(cap),
                                              self.sec_props.set_open(True)))
        menu.addSeparator()
        a_c = menu.addAction("Déverrouiller la cale" if cap.verrouillee
                             else "Verrouiller la cale")
        a_c.setToolTip("Une cale verrouillée ne se déplace plus, ses sommets "
                       "non plus, et on n'en ajoute ni n'en retire.")
        a_c.triggered.connect(lambda *_: self.basculer_verrou_cale(cap))
        return menu, quoi

    def view_context_menu(self, view, event) -> bool:
        """Clic droit sur le plan du pont : le menu de l'objet visé."""
        if view.name != "pont":
            return False
        scene_pos = view.mapToScene(event.pos())
        menu, quoi = self.menu_pour_objet(scene_pos)
        if menu is None:
            menu, quoi = self.menu_pour_cale(scene_pos, view)
        if menu is None:
            return False
        menu.exec(event.globalPos())
        return True

    def _status_coords(self, name, pos, snapped):
        scene = self._scene_for(name)
        parts = []
        if snapped:
            parts.append(f"accroché  ({pos.x():.1f} ; {pos.y():.1f}) px")
        if scene.calibrated is not None and scene.calibrated.calibration.valid:
            a, b = scene.calibrated.calibration.to_real(pos.x(), pos.y())
            ax1, ax2 = scene.calibrated.axes
            parts.append(f"{ax1} = {a:8.2f} m      {ax2} = {b:8.2f} m")
        elif not snapped:
            parts.append(f"pixel ({pos.x():.0f} ; {pos.y():.0f}) — vue non calée")
        if name == "pont" and self.current_deck:
            parts.append(f"pont : {self.current_deck.name}")
        self.statusBar().showMessage("      ".join(parts))

    def on_click(self, view_name, pos, modifiers=Qt.KeyboardModifier.NoModifier,
                 view=None):
        """Clic gauche dans un mode de saisie ; `pos` est brute, l'accroche
        s'applique ici."""
        view = view or self._view_for(view_name)
        if self.mode == MODE_CAL and view_name == self.active:
            scene = self._scene_for(view_name)
            if scene.calibrated is None or scene.pixmap_item is None:
                self.statusBar().showMessage(
                    "Aucun plan sur cette vue : importez-en un avant de caler.")
                return
            pos, snapped = self._snap(view, pos, modifiers)
            dlg = CalPointDialog(scene.calibrated.axes,
                                 len(scene.calibrated.cal_points) + 1, self,
                                 couples=self._couples(),
                                 perpendiculaires=self._perpendiculaires(),
                                 pixel=(pos.x(), pos.y()), snapped=snapped)
            if dlg.exec():
                label, a, b = dlg.values()
                scene.add_cal_point(pos, (a, b), label)
                self._local_index.pop(view_name, None)
                self.refresh_views_table()
                self.refresh_wizard()
        elif self.mode == MODE_DECKS and view_name == "profil":
            cal = self.project.profile.calibration
            if not cal.valid:
                return
            _, z = cal.to_real(pos.x(), pos.y())
            dlg = DeckDialog(self, z=round(z, 3), decks=self.project.sorted_decks())
            if dlg.exec():
                name, zval = dlg.values()
                d = self.project.add_deck(name, zval, dlg.alias(), dlg.copy_from())
                self.refresh_all()
                self.show_view(d)
        elif self.mode == MODE_TRAIT and view_name == self.active:
            scene = self._scene_for(view_name)
            cal = scene.calibrated
            if cal is None or not cal.calibration.valid:
                self.statusBar().showMessage(
                    "Vue non calée : un trait de construction se pose à une "
                    "cote du repère navire, il faut d'abord caler le plan.")
                return
            pos, _ = self._snap(view, pos, modifiers)
            self.poser_trait(cal, pos, modifiers)
        elif self.mode == MODE_EPONTILLE and view_name == "pont":
            pos, _ = self._snap(view, pos, modifiers)
            cal = self.current_deck.plan.calibration if self.current_deck else None
            if cal is None or not cal.valid:
                return
            x, y = _real(cal, pos)
            self.poser_epontille(x, y)
        elif self.mode in MODES_RECTANGLE and view_name == "pont":
            pos, _ = self._snap(view, pos, modifiers)
            self.clic_rectangle(pos)
        elif self.mode == MODE_INFO and view_name == "pont":
            pos, _ = self._snap(view, pos, modifiers)
            if self._info_forme in FORMES_TRACEES_INFO:
                self._poly_points.append(pos)
                self._update_poly_preview(pos)
                self._refresh_hud()
            else:
                # un point et un texte se posent d'UN clic : il n'y a rien à
                # fermer, la fiche s'ouvre tout de suite
                self.poser_annotation([pos])
        elif self.mode in MODES_POLYGONE and view_name == "pont":
            pos, _ = self._snap(view, pos, modifiers)
            self._poly_points.append(pos)
            self._update_poly_preview(pos)
            self._refresh_hud()

    def on_double_click(self, view_name, pos):
        if view_name == "pont" and (self.mode in MODES_POLYGONE
                                    or self.mode == MODE_INFO):
            self.finish_polygon()

    def _dossier_navire(self):
        """Le dossier du navire sur lequel on travaille : celui de la fenêtre,
        celui du brouillon de création, sinon celui de l'installation."""
        return self.ship_folder or self.project.navire_virtuel_path \
            or app_paths.ship_folder()

    def _perpendiculaires(self):
        """(X de la PPAR, X de la PPAV) du navire, ou None.

        C'est ce qui arme les boutons « PPAR » et « PPAV » de la fiche de
        calage : le bord cale sur les perpendiculaires avant tout, et elles
        sont déjà saisies dans « Création du navire ». Les redemander à la
        main serait les saisir deux fois — et deux fois, c'est une fois de
        trop pour qu'elles restent d'accord."""
        folder = self._dossier_navire()
        try:
            perp = app_paths.perpendiculaires(folder) if folder else None
        except Exception:
            return None
        motif = app_paths.DERNIER_MESSAGE_PERPENDICULAIRES
        if perp is None and motif and not self._perp_signale:
            self._perp_signale = True
            self.statusBar().showMessage(motif, 15000)
        return perp

    def _couples(self):
        folder = self._dossier_navire()
        try:
            couples = app_paths.table_couples(folder) if folder else []
        except Exception:
            return []
        # un couples.csv présent mais illisible faisait disparaître le champ
        # « Sur le couple » sans un mot : on le dit une fois, au premier calage
        motif = app_paths.DERNIER_MESSAGE_COUPLES
        if motif and not self._couples_signale:
            self._couples_signale = True
            self.statusBar().showMessage(motif, 15000)
        return couples

    # ------------------------------------------------------------------ calage
    def _active_calibrated(self):
        if self.active == "profil":
            return self.project.profile, self.profile_scene
        if self.current_deck is None:
            return None, None
        return self.current_deck.plan, self.deck_scene

    def apply_calibration(self):
        calibrated, scene = self._active_calibrated()
        if calibrated is None:
            QMessageBox.information(self, "Calage",
                                    "Sélectionnez d'abord un pont.")
            return
        pts = calibrated.cal_points
        if len(pts) < 2:
            QMessageBox.warning(
                self, "Calage",
                f"Placez au moins 2 points de référence sur la vue « {self.active} ».")
            return
        try:
            # un PDF ou un DXF n'a qu'une échelle : deux points sur la ligne
            # de foi le calent, équerre comprise (D-56)
            cal = Calibration.fit([p["pixel"] for p in pts],
                                  [p["real"] for p in pts],
                                  isotrope=calibrated.est_vectoriel)
        except ValueError as e:
            QMessageBox.warning(self, "Calage impossible", str(e))
            return
        calibrated.calibration = cal
        self._set_mode(MODE_SELECT)
        self.refresh_all()
        QMessageBox.information(self, "Calage appliqué",
                                self.calibration_report(calibrated))

    @staticmethod
    def calibration_report(calibrated: Calibrated) -> str:
        """Compte rendu en clair : écart de chaque point, échelle trouvée,
        et ce qui cloche s'il y a quelque chose."""
        cal = calibrated.calibration
        pts = calibrated.cal_points
        if not cal.valid:
            return "Le plan n'est pas calé."
        errs = calibrated.residuals()
        ax1, ax2 = calibrated.axes
        lines = []
        for i, (p, e) in enumerate(zip(pts, errs), start=1):
            label = p.get("label") or "sans intitulé"
            a, b = p["real"]
            lines.append(f"  {i}. {label} — {ax1} = {a:g}, {ax2} = {b:g} : "
                         f"écart {e * 100:.1f} cm")
        s1, s2, aniso, equerre = cal.diagnostic()
        if not pts:
            # calage tiré des coordonnées du dessin (DXF, D-9) : il n'y a pas
            # de point de référence à contrôler, et il faut le dire
            txt = ("Ce plan est calé sur les coordonnées du dessin lui-même "
                   "(DXF), sans point de référence.\nRien ne le contrôle : "
                   "vérifiez que la grille tombe sur les couples, et posez "
                   "deux points connus si elle ne tombe pas.")
        else:
            txt = "Écart de chaque point de référence :\n" + "\n".join(lines)
            if len(pts) == 2 and calibrated.est_vectoriel:
                txt += ("\n\nPlan vectoriel (PDF, DXF) : une seule échelle, axes "
                        "à l'équerre — les deux points fixent l'échelle et "
                        "l'orientation. Rien ne les contrôle : vérifiez que la "
                        "grille tombe sur les couples et sur la ligne de foi.")
            elif len(pts) == 2:
                txt += ("\n\nAvec 2 points le calage passe exactement par eux : "
                        "rien ne le contrôle. Un 3e point (hors axe) dirait s'il "
                        "est juste.")
            else:
                txt += f"\n\nÉcart maximal : {max(errs) * 100:.1f} cm."
        txt += (f"\nÉchelle trouvée : {1 / s1:.2f} px/m selon la largeur, "
                f"{1 / s2:.2f} px/m selon la hauteur de l'image.")
        avert = cal.avertissements(errs)
        if avert:
            txt += "\n\nÀ VÉRIFIER :\n" + "\n".join("  • " + a for a in avert)
        else:
            txt += ("\n\nRien à signaler. Vérifiez tout de même que la grille "
                    "tombe sur les repères du plan (couples, ligne de foi, ponts).")
        return txt

    def clear_calibration(self):
        calibrated, scene = self._active_calibrated()
        if calibrated is None:
            return
        scene.clear_cal_points()
        calibrated.calibration = Calibration()
        self.refresh_all()

    # ------------------------------------------------------------------ polygones
    def _update_poly_preview(self, current):
        """Le tracé en cours : la ligne jusqu'au curseur ET une pastille par
        sommet posé — on doit voir ce qu'on a placé, pas seulement le trait."""
        path = QPainterPath(self._poly_points[0])
        for p in self._poly_points[1:]:
            path.lineTo(p)
        path.lineTo(current)
        r = 3.5 / self.deck_view.view_scale()
        for p in self._poly_points:
            path.addEllipse(p, r, r)
        if self._poly_preview is None:
            pen = QPen(QColor(theme.CAP_SEL), 1.8)
            pen.setCosmetic(True)
            pen.setStyle(Qt.PenStyle.DashLine)
            self._poly_preview = self.deck_scene.addPath(path, pen)
            self._poly_preview.setZValue(40)
        else:
            self._poly_preview.setPath(path)

    def _redraw_poly_preview(self):
        """Redessine le tracé en cours sans point courant (après un retrait)."""
        if not self._poly_points:
            if self._poly_preview is not None:
                try:
                    self.deck_scene.removeItem(self._poly_preview)
                except RuntimeError:
                    pass
                self._poly_preview = None
            return
        self._update_poly_preview(self._poly_points[-1])

    def remove_last_poly_point(self):
        """Retour arrière pendant un tracé : le dernier sommet posé s'en va."""
        if not self._poly_points:
            self.statusBar().showMessage("Aucun sommet à retirer.", 3000)
            return
        self._poly_points.pop()
        self._redraw_poly_preview()
        self._refresh_hud()
        self.statusBar().showMessage(
            f"Dernier sommet retiré — {len(self._poly_points)} restant(s).", 4000)

    def _cancel_poly(self):
        self._poly_points = []
        if self._poly_preview is not None:
            try:
                self.deck_scene.removeItem(self._poly_preview)
            except RuntimeError:
                pass
            self._poly_preview = None
        self._refresh_hud()

    def finish_polygon(self):
        if self.current_deck is None:
            self._cancel_poly()
            return
        if self.mode == MODE_INFO:
            # une polyligne d'information n'est pas un contour : deux sommets
            # suffisent, elle ne se referme pas. Un POLYGONE, lui, se ferme
            # tout seul au double-clic comme le contour d'une cale — il lui
            # faut donc trois sommets, sinon il n'entoure rien.
            mini = 3 if self._info_forme == "polygone" else 2
            if len(self._poly_points) >= mini:
                pts = list(self._poly_points)
                self._cancel_poly()
                self.poser_annotation(pts)
            else:
                n = len(self._poly_points)
                self._cancel_poly()
                if n:
                    self.statusBar().showMessage(
                        f"Polygone abandonné : {n} sommet(s) posé(s), il en "
                        "faut au moins 3 pour refermer une forme.", 6000)
            return
        if len(self._poly_points) < 3:
            self._cancel_poly()
            return
        if self.mode == MODE_ZONE_CHARGE:
            pts = list(self._poly_points)
            self._cancel_poly()
            self.poser_zone_charge(pts)
            return
        deck = self.current_deck
        contour = self.mode == MODE_CONTOUR
        z0, z1 = self.project.default_z_range(deck)
        dlg = CapacityDialog(self, z_min=z0, z_max=z1, contour=contour)
        if dlg.exec():
            code, name, zmin, zmax, fill = dlg.values()
            if not contour and not code:
                QMessageBox.warning(self, "Capacité", "Le code est obligatoire.")
                self._cancel_poly()
                return
            cal = deck.plan.calibration
            # au dixième de millimètre, comme tous les autres chemins de
            # tracé : deux cales accrochées au même sommet doivent en sortir
            # exactement égales, pas à 1e-15 près
            pts = [_real(cal, p) for p in self._poly_points]
            if contour:
                deck.capacities = [c for c in deck.capacities
                                   if c.kind != KIND_CONTOUR]
                deck.capacities.append(Capacity(code="CONTOUR", points=pts,
                                                kind=KIND_CONTOUR,
                                                z_min=deck.z, z_max=deck.z))
            else:
                deck.capacities.append(Capacity(code=code, name=name, points=pts,
                                                z_min=zmin, z_max=zmax, fill=fill))
            self._cancel_poly()
            self.refresh_all()
            # à la fin du tracé, tant que la main est encore dessus : deux
            # cales qui se mordent se corrigent en trois secondes ici, et en
            # une demi-heure six mois plus tard
            self._dire_recouvrements()
        self._cancel_poly()

    # ---------------------------------------------------------------- épontilles
    def cale_sous(self, x, y):
        """La cale du pont courant qui contient ce point (repère navire).

        Le contour du pont n'en est pas une : une épontille se dresse DANS une
        cale, pas au milieu d'un pont."""
        from .geometry import point_in_polygon
        if self.current_deck is None:
            return None
        for cap in self.current_deck.capacities:
            if cap.kind == KIND_CONTOUR or len(cap.points) < 3:
                continue
            if point_in_polygon(x, y, cap.points):
                return cap
        return None

    # --------------------------------------------- traits de construction
    def poser_trait(self, cal, pos, modifiers=Qt.KeyboardModifier.NoModifier):
        """Pose un trait de construction passant par `pos` (pixels).

        L'axe retenu est **le second** du plan — Y sur un pont, Z sur un
        profil : c'est la cote qu'on reporte le plus souvent (une demi-largeur,
        une hauteur de pont). Ctrl pose le trait sur le premier axe (X), pour
        reporter un couple ou une abscisse."""
        a, b = _real(cal.calibration, pos)
        premier = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        axe = cal.axes[0] if premier else cal.axes[1]
        valeur = round(a if premier else b, 3)
        traits = list(getattr(cal, "traits", None) or [])
        traits.append({"axe": axe, "valeur": valeur, "libelle": ""})
        cal.traits = traits
        self.refresh_all()
        self.statusBar().showMessage(
            f"Trait de construction posé : {axe} = {valeur:.3f} m. "
            "Ctrl+clic pose un trait sur l'autre axe ; "
            "Édition › Traits de construction… pour la liste.", 8000)
        return traits[-1]

    def open_traits(self, *_):
        """La liste des traits de construction du plan actif."""
        scene = self._scene_for(self.active)
        cal = scene.calibrated
        if cal is None:
            self.statusBar().showMessage(
                "Aucun plan sur cette vue : rien à construire dessus.")
            return None
        titre = (self.current_deck.name if self.active == "pont" and self.current_deck
                 else "profil")
        dlg = TraitsConstructionDialog(self, cal, couples=self._couples(),
                                       titre=titre)
        if dlg.exec():
            cal.traits = dlg.valeurs()
            self.refresh_all()
            self.statusBar().showMessage(
                "%d trait(s) de construction sur « %s »."
                % (len(cal.traits), titre), 6000)
        return dlg

    def poser_epontille(self, x, y):
        """Pose l'emplacement d'une épontille au point (x, y) du repère navire.

        Elle doit tomber DANS une cale : ailleurs elle ne contraindrait rien
        et personne ne saurait à quelle cale elle appartient. On le dit au
        lieu de poser dans le vide."""
        cap = self.cale_sous(x, y)
        if cap is None:
            self.statusBar().showMessage(
                f"Point hors cale (X = {x:.2f} m, Y = {y:.2f} m) : une "
                "épontille se dresse DANS une cale — cliquez à l'intérieur "
                "d'un contour de cale tracé.", 8000)
            return None
        n = len(getattr(cap, "epontilles", [])) + 1
        dlg = EpontilleDialog(self, nom=f"Épontille {n}", x=x, y=y,
                              cale=cap.name or cap.code)
        if not dlg.exec():
            return None
        nom, longueur, largeur, note, fixe = dlg.values()
        e = {"id": cap.nouvel_id_epontille(), "nom": nom or f"Épontille {n}",
             "x": round(float(x), 3), "y": round(float(y), 3),
             "largeur_m": largeur, "longueur_m": longueur, "note": note,
             "fixe": bool(fixe)}
        cap.epontilles.append(e)
        self._push_undo_ajout(cap, "epontilles", e)
        self.refresh_all()
        self.select_epontille(cap, e)
        self.statusBar().showMessage(
            f"Épontille « {e['nom'] }» posée dans {cap.code} "
            f"(X = {e['x']:.2f} m, Y = {e['y']:.2f} m). "
            + ("Fixe : rien ne s'y posera jamais."
               if fixe else
               "Elle n'interdira la pose que lorsqu'elle sera mise en place, "
               "au chargement."), 8000)
        return e

    def _start_drag_epontille(self, item, scene_pos):
        self._drag = {"kind": "epontille", "item": item, "index": None,
                      "start": QPointF(scene_pos), "moved": False,
                      "centre": item.centre_pixel(),
                      "capacity": item.capacity, "epontille": item.epontille}
        # jamais la variante bloquante ici : un premier glisser sur le plan
        # d'ensemble figeait la fenêtre le temps de lire les traits (mesuré
        # 2,6 s). L'accroche est simplement absente au premier geste, et
        # s'active toute seule dès que la lecture de fond a fini.
        self._ensure_vector_index(self.deck_scene.calibrated)

    def deplacer_epontille(self, cap, e, x, y):
        """Déplace une épontille — en refusant de la sortir de sa cale.

        Une épontille lâchée hors de toute cale revient d'où elle vient : on
        n'en perd pas une en glissant trop loin."""
        cible = self.cale_sous(x, y)
        if cible is None:
            self.refresh_all(keep_selection=True)
            self.select_epontille(cap, e)
            self.statusBar().showMessage(
                "Une épontille reste dans une cale : le déplacement est "
                "annulé.", 6000)
            return False
        if cible is not cap and e in cap.epontilles:
            # elle change de cale : elle change aussi d'identifiant, sinon
            # deux cales se disputeraient le même
            cap.epontilles.remove(e)
            e["id"] = cible.nouvel_id_epontille()
            cible.epontilles.append(e)
        e["x"], e["y"] = round(float(x), 3), round(float(y), 3)
        self.refresh_all(keep_selection=True)
        self.select_epontille(cible, e)
        self.statusBar().showMessage(
            f"Épontille « {e.get('nom', '')} » : X = {e['x']:.2f} m, "
            f"Y = {e['y']:.2f} m ({cible.code}).", 6000)
        return True

    def select_epontille(self, cap, e):
        """Choisit une épontille : elle s'allume sur le plan, ses champs
        s'affichent dans la colonne."""
        if self._sync:
            return
        self._sync = True
        try:
            self._selected_epontille = (cap, e) if e is not None else None
            self._selected_capacity = None
            self._selected_vertex = None
            self._selected_calque = None
            for scene in (self.profile_scene, self.deck_scene):
                for it in _vivants(scene.object_items):
                    it.setSelected(False)
            for it in _vivants(self.deck_scene.epontille_items):
                it.setSelected(it.epontille is e)
            self._deselectionner_calques()
            self.show_epontille_props(cap, e)
        finally:
            self._sync = False

    def show_epontille_props(self, cap, e):
        if e is None:
            self.props.setCurrentIndex(0)
            return
        self.props.setCurrentIndex(4)
        widgets = (self.ep_nom, self.ep_x, self.ep_y, self.ep_long,
                   self.ep_larg, self.ep_note, self.ep_fixe)
        for w in widgets:
            w.blockSignals(True)
        self.ep_titre.setText(
            f"<b>Épontille {'fixe' if epontille_fixe(e) else 'amovible'}</b>"
            f" — {getattr(cap, 'code', '?')}  ·  {e.get('id', '')}")
        self.ep_fixe.setChecked(epontille_fixe(e))
        self.ep_nom.setText(str(e.get("nom") or ""))
        self.ep_x.setValue(float(e.get("x", 0.0)))
        self.ep_y.setValue(float(e.get("y", 0.0)))
        self.ep_long.setValue(float(e.get("longueur_m", 0.0)))
        self.ep_larg.setValue(float(e.get("largeur_m", 0.0)))
        self.ep_note.setText(str(e.get("note") or ""))
        for w in widgets:
            w.blockSignals(False)

    def on_epontille_edited(self):
        """Les champs de la colonne : renommer, déplacer au clavier, redimensionner."""
        if self._selected_epontille is None or self._sync:
            return
        cap, e = self._selected_epontille
        e["nom"] = self.ep_nom.text().strip() or str(e.get("id", "épontille"))
        e["longueur_m"] = round(self.ep_long.value(), 3)
        e["largeur_m"] = round(self.ep_larg.value(), 3)
        e["note"] = self.ep_note.text().strip()
        e["fixe"] = bool(self.ep_fixe.isChecked())
        x, y = round(self.ep_x.value(), 3), round(self.ep_y.value(), 3)
        if abs(x - float(e.get("x", 0.0))) > 1e-9 \
                or abs(y - float(e.get("y", 0.0))) > 1e-9:
            self.deplacer_epontille(cap, e, x, y)
            return
        self.refresh_all(keep_selection=True)
        self.select_epontille(cap, e)

    def delete_selected_epontille(self):
        if self._selected_epontille is None:
            return False
        cap, e = self._selected_epontille
        liste = getattr(cap, "epontilles", None) or []
        index = next((i for i, o in enumerate(liste) if o is e), None)
        if index is not None:
            self._push_undo_suppression(cap, "epontilles", e, index)
            del liste[index]
        self._selected_epontille = None
        self.refresh_all()
        self.props.setCurrentIndex(0)
        self.statusBar().showMessage(
            f"Épontille « {e.get('nom', '')} » supprimée de {cap.code} "
            "(Ctrl+Z la remet en place). Les chargements qui la portaient en "
            "place l'oublient.", 8000)
        return True

    # =================================================== calques d'une cale
    # Ce que le bord ne trouvait pas : « je n'ai pas trouvé où modifier les
    # calques de limite t/m², ni le calque de limite de hauteur ». Il n'y avait
    # tout simplement AUCUN outil — seul `tools/retracer_cales.py` en produisait,
    # hors de l'application. Voici les trois : charge au m² (D-12), hauteur
    # libre (D-21) et zone interdite (structure, bloquante).

    @staticmethod
    def _centre_polygone(points):
        """Le centre (centroïde d'aire) d'un polygone en coordonnées navire.

        C'est lui qui désigne la cale à laquelle la zone appartient : une zone
        de charge se pose DANS une cale, et il faut un point, pas une
        intention. Repli sur la moyenne des sommets quand l'aire est nulle
        (polygone dégénéré)."""
        pts = [(float(a), float(b)) for a, b in points]
        n = len(pts)
        if n == 0:
            return (0.0, 0.0)
        a2 = cx = cy = 0.0
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            f = x0 * y1 - x1 * y0
            a2 += f
            cx += (x0 + x1) * f
            cy += (y0 + y1) * f
        if abs(a2) < 1e-12:
            return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)
        return (cx / (3 * a2), cy / (3 * a2))

    # ------------------------------------------------- zone de charge (D-12)
    def poser_zone_charge(self, points_pixels):
        """Ferme une zone de charge tracée sur le plan : demande son nom et sa
        charge, puis la range dans la cale qui contient son CENTRE.

        Hors cale, on refuse en le disant : une charge admissible qui
        n'appartiendrait à aucune cale ne serait jamais lue par personne."""
        deck = self.current_deck
        if deck is None or not deck.plan.calibration.valid:
            return None
        cal = deck.plan.calibration
        pts = [_real(cal, p) for p in points_pixels]
        cx, cy = self._centre_polygone(pts)
        cap = self.cale_sous(cx, cy)
        if cap is None:
            self.statusBar().showMessage(
                f"Centre de la zone hors cale (X = {cx:.2f} m, Y = {cy:.2f} m) : "
                "une charge admissible appartient à UNE cale — tracez la zone "
                "à l'intérieur d'un contour de cale.", 10000)
            return None
        pts, note = self._tronquer_a_la_cale(pts, cap)
        if pts is None:
            self.statusBar().showMessage(note, 12000)
            return None
        dlg = ZoneChargeDialog(self, cale=cap.name or cap.code,
                               t_m2_cale=float(getattr(
                                   cap, "charge_admissible_t_m2", 0.0) or 0.0),
                               surface_m2=self._aire_polygone(pts))
        if not dlg.exec():
            return None
        nom, t_m2 = dlg.values()
        return self.ajouter_zone_charge(cap, pts, nom, t_m2, note)

    def _tronquer_a_la_cale(self, points, cap):
        """Rabat un polygone sur le contour de sa cale : (sommets, phrase).

        Le bord : « les formes pour la restriction de charge au mètre carré
        devraient être tronquées pour correspondre aux limites de la cale
        quand ça dépasse ». Une charge admissible qui déborde d'une cale ne
        veut rien dire : au-delà du contour, ce n'est plus le plancher de
        cette cale. On garde donc l'INTERSECTION du tracé et du contour.

        Sommets à None : il ne reste rien d'utilisable ; la phrase dit
        pourquoi. Phrase vide : rien n'a été tronqué, le tracé passe tel
        quel."""
        from .geometry import aire_polygone, intersection_polygones
        contour = [(float(a), float(b)) for a, b in (cap.points or [])]
        pts = [(float(a), float(b)) for a, b in points]
        if len(contour) < 3 or len(pts) < 3:
            return pts, ""
        aire0 = aire_polygone(pts)
        morceaux = intersection_polygones(pts, contour)
        if not morceaux:
            return None, (
                f"Zone entièrement hors de « {cap.code} » : une charge "
                "admissible est le plancher d'UNE cale — retracez-la à "
                "l'intérieur du contour.")
        garde = morceaux[0]
        aire = aire_polygone(garde)
        if len(garde) < 3 or aire < AIRE_MINI_ZONE_M2:
            return None, (
                f"Zone tronquée au contour de « {cap.code} » : il ne reste "
                f"que {aire:.3f} m² (minimum {AIRE_MINI_ZONE_M2:g} m²) — "
                "retracez-la à l'intérieur.")
        if aire >= aire0 - 1e-4 and len(morceaux) == 1:
            return pts, ""
        # au dixième de millimètre, comme tout ce qui sort d'un tracé : deux
        # zones tronquées au même contour doivent partager exactement ses
        # sommets, pas à 1e-15 près
        garde = [(round(x, 4), round(y, 4)) for x, y in garde]
        phrase = (f"Zone tronquée au contour de {cap.code} : "
                  f"{aire0:.1f} → {aire:.1f} m².")
        if len(morceaux) > 1:
            # une cale en U traversée par une bande : on garde le plus grand
            # morceau, et on le DIT — sinon les autres disparaîtraient en
            # silence, et personne ne saurait qu'ils ont existé
            phrase += (f" L'intersection donne {len(morceaux)} morceaux : "
                       "le plus grand est gardé, retracez les autres à part.")
        return garde, phrase

    @staticmethod
    def _aire_polygone(points):
        pts = [(float(a), float(b)) for a, b in points]
        n = len(pts)
        s = 0.0
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            s += x0 * y1 - x1 * y0
        return abs(s) / 2.0

    def ajouter_zone_charge(self, cap, points, nom, t_m2, note=""):
        """Range une zone de charge dans `cap.zones_charge` (chemin public,
        sans fiche : c'est par ici que passent les tests et l'assistant)."""
        zone = {"nom": nom or "zone de charge", "t_m2": round(float(t_m2), 3),
                "points": [(round(float(a), 4), round(float(b), 4))
                           for a, b in points]}
        cap.zones_charge.append(zone)
        self._push_undo_ajout(cap, "zones_charge", zone)
        self.refresh_all()
        self.select_objet_calque("zone", cap, zone)
        self.statusBar().showMessage(
            f"Zone de charge « {zone['nom']} » : {zone['t_m2']:g} t/m² dans "
            f"{cap.code}, {self._aire_polygone(zone['points']):.1f} m². "
            "Calque signalé, jamais bloquant (D-12)."
            + (" " + note if note else ""), 10000)
        return zone

    # ------------------------------------- rectangle : hauteur libre / interdit
    def clic_rectangle(self, pos):
        """Un clic d'un outil rectangle : premier coin, puis coin opposé."""
        if self._rect_start is None:
            self._rect_start = QPointF(pos)
            self._update_rect_preview(pos)
            self.statusBar().showMessage(
                "Premier coin posé — cliquez le coin opposé (Échap pour "
                "abandonner).", 8000)
            return None
        p1, self._rect_start = self._rect_start, None
        self._cancel_rect()
        return self.poser_rectangle_calque(p1, pos)

    def poser_rectangle_calque(self, p1, p2):
        """Deux coins opposés (en pixels) → une zone de `cap.obstacles`.

        Le rectangle est aligné sur les axes du repère navire : c'est la seule
        forme que le moteur sache lire pour un obstacle
        (`Capacity.obstacles` = [x0, y0, x1, y1, nom])."""
        deck = self.current_deck
        if deck is None or not deck.plan.calibration.valid:
            return None
        cal = deck.plan.calibration
        (xa, ya), (xb, yb) = _real(cal, p1), _real(cal, p2)
        x0, x1 = sorted((xa, xb))
        y0, y1 = sorted((ya, yb))
        if (x1 - x0) < 1e-3 or (y1 - y0) < 1e-3:
            self.statusBar().showMessage(
                "Rectangle plat : tracez un rectangle — glissez d'un coin à "
                "l'autre, ou cliquez deux coins OPPOSÉS (deux clics au même "
                "point ne posent rien).", 8000)
            return None
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        cap = self.cale_sous(cx, cy)
        if cap is None:
            quoi = ("une hauteur libre" if self.mode == MODE_HAUTEUR
                    else "une zone interdite")
            self.statusBar().showMessage(
                f"Centre du rectangle hors cale (X = {cx:.2f} m, "
                f"Y = {cy:.2f} m) : {quoi} appartient à UNE cale — tracez-la "
                "à l'intérieur d'un contour de cale.", 10000)
            return None
        rect, note = self._borner_rectangle_a_la_cale((x0, y0, x1, y1), cap)
        if rect is None:
            self.statusBar().showMessage(note, 12000)
            return None
        if self.mode == MODE_HAUTEUR:
            dlg = HauteurLibreDialog(self, cale=cap.name or cap.code,
                                     rect=rect)
            if not dlg.exec():
                return None
            return self.ajouter_zone_hauteur(cap, rect, dlg.values(), note)
        dlg = ZoneInterditeDialog(self, cale=cap.name or cap.code)
        if not dlg.exec():
            return None
        return self.ajouter_zone_interdite(cap, rect, dlg.values(), note)

    def _borner_rectangle_a_la_cale(self, rect, cap):
        """Rabat un rectangle sur sa cale : (rectangle gardé, phrase à dire).

        Le moteur ne sait lire qu'un rectangle ALIGNÉ sur les axes pour un
        obstacle (D-21, `Capacity.obstacles` = [x0, y0, x1, y1, nom]) : on ne
        peut donc pas rendre l'intersection exacte avec un contour de cale
        quelconque, qui serait un polygone. On borne à la boîte englobante de
        la cale — ce qui déborde du pont disparaît, et ce qui reste est bien
        un rectangle que le moteur relira.

        Rectangle gardé à None : il ne reste rien d'utilisable, la phrase dit
        alors pourquoi (jamais de refus muet)."""
        x0, y0, x1, y1 = (float(v) for v in rect[:4])
        pts = [(float(a), float(b)) for a, b in (cap.points or [])]
        if len(pts) < 3:
            return (round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)), ""
        bx0, bx1 = min(p[0] for p in pts), max(p[0] for p in pts)
        by0, by1 = min(p[1] for p in pts), max(p[1] for p in pts)
        nx0, nx1 = max(x0, bx0), min(x1, bx1)
        ny0, ny1 = max(y0, by0), min(y1, by1)
        aire = max(0.0, nx1 - nx0) * max(0.0, ny1 - ny0)
        if (nx1 - nx0) < 1e-3 or (ny1 - ny0) < 1e-3 or aire < AIRE_MINI_ZONE_M2:
            return None, (
                f"Rectangle hors de « {cap.code} » ou trop petit : une fois "
                f"tronqué au contour de la cale il ne reste que {aire:.3f} m² "
                f"(minimum {AIRE_MINI_ZONE_M2:g} m²) — retracez-le à "
                "l'intérieur. Un poteau se pose avec l'outil Épontille "
                "(case « fixe »).")
        borne = tuple(round(v, 4) for v in (nx0, ny0, nx1, ny1))
        if max(abs(nx0 - x0), abs(ny0 - y0),
               abs(nx1 - x1), abs(ny1 - y1)) < 1e-4:
            return borne, ""
        return borne, (f"Zone tronquée au contour de {cap.code} : "
                       f"{(x1 - x0) * (y1 - y0):.1f} → {aire:.1f} m².")

    def ajouter_zone_hauteur(self, cap, rect, hauteur_m, note=""):
        """Zone à hauteur réduite : rangée dans `cap.obstacles` AVEC sa hauteur
        dans le nom — c'est ainsi que le moteur la relit (D-21)."""
        x0, y0, x1, y1 = (round(float(v), 4) for v in rect[:4])
        obs = [x0, y0, x1, y1, nom_zone_hauteur(hauteur_m)]
        cap.obstacles.append(obs)
        self._push_undo_ajout(cap, "obstacles", obs)
        self.refresh_all()
        self.select_objet_calque("obstacle", cap, obs)
        # Les COTES dans la barre d'état : le bord doit voir que la zone
        # existe et où elle est, sans avoir à la chercher sur le plan.
        self.statusBar().showMessage(
            f"« {obs[4]} » dans {cap.code}, {self._cotes_rect(obs)} : une pile "
            "plus haute y sera SIGNALÉE, jamais refusée (D-21)."
            + (" " + note if note else ""), 10000)
        return obs

    @staticmethod
    def _cotes_rect(rect) -> str:
        """« 2.00 × 1.50 m, X 26.00→28.00, Y 1.00→2.50 » — ce qu'on vient de
        tracer, en clair."""
        x0, y0, x1, y1 = (float(v) for v in rect[:4])
        return (f"{x1 - x0:.2f} × {y1 - y0:.2f} m, X {x0:.2f}→{x1:.2f}, "
                f"Y {y0:.2f}→{y1:.2f}")

    def ajouter_zone_interdite(self, cap, rect, nom, note=""):
        """Zone de structure : rangée dans `cap.obstacles` SANS hauteur, donc
        BLOQUANTE — rien ne s'y pose."""
        x0, y0, x1, y1 = (round(float(v), 4) for v in rect[:4])
        nom = str(nom or "Zone interdite")
        obs = [x0, y0, x1, y1, nom]
        cap.obstacles.append(obs)
        self._push_undo_ajout(cap, "obstacles", obs)
        self.refresh_all()
        self.select_objet_calque("obstacle", cap, obs)
        avert = ""
        if hauteur_annoncee(obs) > 0:
            # le nom fait foi : « Épontille 2 m » deviendrait un plafond bas
            avert = (" ATTENTION : ce nom contient une hauteur, la zone sera "
                     "relue comme un plafond bas et cessera de bloquer — "
                     "renommez-la.")
        self.statusBar().showMessage(
            f"« {nom} » dans {cap.code}, {self._cotes_rect(obs)} : zone "
            "BLOQUANTE, rien ne s'y posera." + avert
            + (" " + note if note else ""), 10000)
        return obs

    # --------------------------------------------- calque d'information
    def _aide_forme_info(self) -> str:
        return {"trait": "cliquez les sommets de la polyligne, double-clic "
                         "pour terminer.",
                "polygone": "cliquez les sommets, double-clic pour REFERMER "
                            "le polygone — comme un contour de cale.",
                "point": "un clic pose le point.",
                "texte": "un clic pose le texte."}[self._info_forme]

    def choisir_information(self) -> bool:
        """La fiche qui dit CE QU'ON VA décalquer : forme, texte, couleur.

        La forme se choisit avant le geste parce qu'un point et le premier
        sommet d'une polyligne sont le même clic : sans cette fiche, le
        logiciel devrait deviner."""
        dlg = AnnotationDialog(
            self, forme=self._info_forme, texte=self._info_texte,
            couleur=self._info_couleur,
            pont=self.current_deck.name if self.current_deck else "")
        if not dlg.exec():
            return False
        self._info_forme, self._info_texte, self._info_couleur = dlg.values()
        return True

    def basculer_information(self, checked):
        """L'outil Information : on demande la forme AVANT d'armer le mode."""
        if not checked:
            if self.mode == MODE_INFO:
                self._set_mode(MODE_SELECT)
            return
        if self.current_deck is None or not self.current_deck.plan.calibration.valid:
            self._set_mode(MODE_INFO)      # refuse et dit pourquoi
            return
        self._set_mode(MODE_INFO if self.choisir_information() else MODE_SELECT)

    def poser_annotation(self, points_pixels):
        """Ferme une annotation : la fiche confirme texte et couleur, puis
        elle est rangée dans le calque d'information du PONT."""
        deck = self.current_deck
        if deck is None or not deck.plan.calibration.valid or not points_pixels:
            return None
        cal = deck.plan.calibration
        pts = [_real(cal, p) for p in points_pixels]
        # un texte se saisit APRÈS le clic quand il est encore vide : c'est le
        # geste que le bord attend (« un clic puis saisie »)
        if self._info_forme == "texte" and not self._info_texte:
            if not self.choisir_information():
                return None
        dlg = AnnotationDialog(self, forme=self._info_forme,
                               texte=self._info_texte,
                               couleur=self._info_couleur,
                               pont=deck.name, nouvelle=False)
        if not dlg.exec():
            return None
        forme, texte, couleur = dlg.values()
        self._info_texte, self._info_couleur = texte, couleur
        return self.ajouter_annotation(deck, self._info_forme, pts, texte,
                                       couleur)

    def ajouter_annotation(self, deck, forme, points, texte="", couleur=None):
        """Range une annotation dans `deck.annotations` (chemin public).

        Un point et un texte ne gardent que leur premier sommet : le reste
        n'aurait pas de sens, et un fichier relu ne doit pas contenir de
        géométrie que personne ne dessine."""
        pts = [[round(float(a), 4), round(float(b), 4)] for a, b in points]
        if forme in ("point", "texte"):
            pts = pts[:1]
        note = {"type": forme, "points": pts, "texte": str(texte or ""),
                "couleur": str(couleur or COULEUR_ANNOTATION_DEFAUT)}
        deck.annotations.append(note)
        self._push_undo_ajout(deck, "annotations", note)
        self.refresh_all()
        self.select_objet_calque("annotation", deck, note)
        self.statusBar().showMessage(
            f"Information « {note['texte'] or NOMS_FORMES_ANNOTATION[forme]} » "
            f"posée sur « {deck.name} ». Rien n'en dépend : ni la pose, ni la "
            "stabilité, ni le solveur.", 8000)
        return note

    # ------------------------------------------- aperçu du rectangle en cours
    def _update_rect_preview(self, current):
        if self._rect_start is None:
            return
        rect = QRectF(self._rect_start, QPointF(current)).normalized()
        path = QPainterPath()
        path.addRect(rect)
        if self._rect_preview is None:
            pen = QPen(QColor(theme.CAP_SEL), 1.8)
            pen.setCosmetic(True)
            pen.setStyle(Qt.PenStyle.DashLine)
            self._rect_preview = self.deck_scene.addPath(path, pen)
            self._rect_preview.setZValue(40)
        else:
            self._rect_preview.setPath(path)

    def _cancel_rect(self):
        self._rect_start = None
        self._rect_glisser = False
        if self._rect_preview is not None:
            try:
                self.deck_scene.removeItem(self._rect_preview)
            except RuntimeError:
                pass
            self._rect_preview = None

    # =============================== sélection des objets de calque
    def _objet_calque_sous(self, scene_pos):
        """L'objet de calque le plus haut sous ce point de la scène du pont.

        On interroge la scène plutôt que `view.itemAt` : le polygone d'une
        cale est dessiné AU-DESSUS de ses zones, il attraperait tous les clics.
        Ici, ce qui est posé PAR-DESSUS une cale se clique d'abord — c'est ce
        qu'attend la main."""
        try:
            items = self.deck_scene.items(QPointF(scene_pos))
        except RuntimeError:
            return None
        for it in items:
            if not it.isVisible():
                continue
            if isinstance(it, (EpontilleItem, AnnotationItem, ObstacleItem,
                               ZoneChargeItem)):
                return it
            parent = it.parentItem()
            if isinstance(parent, (EpontilleItem, AnnotationItem, ObstacleItem,
                                   ZoneChargeItem)):
                return parent
        return None

    @staticmethod
    def _quoi_item(item):
        if isinstance(item, ZoneChargeItem):
            return "zone"
        if isinstance(item, ObstacleItem):
            return "obstacle"
        if isinstance(item, AnnotationItem):
            return "annotation"
        return None

    def select_objet_calque_item(self, item):
        """Choisit l'objet de calque que porte cet objet graphique."""
        quoi = self._quoi_item(item)
        if quoi == "zone":
            self.select_objet_calque("zone", item.capacity, item.zone)
        elif quoi == "obstacle":
            self.select_objet_calque("obstacle", item.capacity, item.source)
        elif quoi == "annotation":
            self.select_objet_calque("annotation", item.deck, item.annotation)

    def select_objet_calque(self, quoi, parent, objet):
        """Met en surbrillance une zone de charge, une zone d'obstacle ou une
        annotation, et affiche ses champs dans la colonne de droite."""
        if self._sync:
            return
        self._sync = True
        try:
            self._selected_calque = {"quoi": quoi, "parent": parent,
                                     "objet": objet}
            self._selected_capacity = None
            self._selected_vertex = None
            self._selected_epontille = None
            for scene in (self.profile_scene, self.deck_scene):
                for it in _vivants(scene.object_items):
                    it.setSelected(False)
            for it in _vivants(self.deck_scene.epontille_items):
                it.setSelected(False)
            sc = self.deck_scene
            for it in sc.zone_items:
                it.setSelected(quoi == "zone" and it.zone is objet)
            for it in sc.obstacle_items:
                it.setSelected(quoi == "obstacle"
                               and getattr(it, "source", None) is objet)
            for it in sc.annotation_items:
                it.setSelected(quoi == "annotation" and it.annotation is objet)
            if quoi == "zone":
                self.show_zone_charge_props(parent, objet)
            elif quoi == "obstacle":
                self.show_obstacle_props(parent, objet)
            else:
                self.show_annotation_props(parent, objet)
            self._montrer_dans_larbre(objet)
        finally:
            self._sync = False

    def _montrer_dans_larbre(self, objet):
        """Choisit dans l'arbre la ligne de CET objet de calque.

        Une zone qu'on vient de poser doit se voir aux trois endroits où on la
        cherche : sur le plan (surbrillance), dans les propriétés, et dans
        l'arbre. Sans cette ligne, le bord tracait une zone et ne trouvait
        nulle part la preuve qu'elle existait."""
        tree = getattr(self, "tree", None)
        if tree is None:
            return
        pile = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
        while pile:
            it = pile.pop()
            data = it.data(0, Qt.ItemDataRole.UserRole)
            if data and data[0] in ("zone", "obstacle", "annotation") \
                    and data[-1] is objet:
                # signaux coupés : on montre la sélection, on ne la rejoue pas
                tree.blockSignals(True)
                try:
                    tree.setCurrentItem(it)
                    tree.scrollToItem(it)
                finally:
                    tree.blockSignals(False)
                return
            pile.extend(it.child(i) for i in range(it.childCount()))

    # ------------------------------------------------------- leurs propriétés
    def show_zone_charge_props(self, cap, zone):
        self.props.setCurrentIndex(5)
        for w in (self.zc_nom, self.zc_t):
            w.blockSignals(True)
        self.zc_titre.setText(
            f"<b>Zone de charge</b> — {getattr(cap, 'code', '?')}")
        self.zc_nom.setText(str(zone.get("nom") or ""))
        self.zc_t.setValue(float(zone.get("t_m2") or 0.0))
        for w in (self.zc_nom, self.zc_t):
            w.blockSignals(False)

    def show_obstacle_props(self, cap, obs):
        self.props.setCurrentIndex(6)
        widgets = (self.ob_bloquante, self.ob_nom, self.ob_hauteur,
                   self.ob_x0, self.ob_x1, self.ob_y0, self.ob_y1)
        for w in widgets:
            w.blockSignals(True)
        h = hauteur_annoncee(obs)
        nom = (obs[4] if len(obs) > 4 else "") or "zone interdite"
        self.ob_titre.setText(
            ("<b>Zone à hauteur réduite</b> — " if h > 0
             else "<b>Zone interdite</b> — ") + f"{getattr(cap, 'code', '?')}")
        self.ob_bloquante.setChecked(h <= 0)
        self.ob_nom.setText(str(nom))
        self.ob_hauteur.setValue(h if h > 0 else 2.0)
        self.ob_x0.setValue(float(obs[0]))
        self.ob_x1.setValue(float(obs[2]))
        self.ob_y0.setValue(float(obs[1]))
        self.ob_y1.setValue(float(obs[3]))
        self.ob_nom.setEnabled(h <= 0)
        self.ob_hauteur.setEnabled(h > 0)
        self.ob_hint.setText(
            "Zone interdite : rien ne s'y pose, jamais. C'est de la structure "
            "— épontille fixe, descente, puits."
            if h <= 0 else
            "Calque de hauteur : une pile plus haute est SIGNALÉE, pas "
            "refusée (D-21). Le solveur, lui, n'y met rien de trop haut.")
        for w in widgets:
            w.blockSignals(False)

    def show_annotation_props(self, deck, note):
        self.props.setCurrentIndex(7)
        widgets = (self.an_texte, self.an_couleur)
        for w in widgets:
            w.blockSignals(True)
        forme = str(note.get("type") or "trait")
        self.an_titre.setText(
            f"<b>Information</b> — {getattr(deck, 'name', '?')}")
        self.an_forme.setText(NOMS_FORMES_ANNOTATION.get(forme, forme))
        self.an_texte.setText(str(note.get("texte") or ""))
        code = str(note.get("couleur") or COULEUR_ANNOTATION_DEFAUT).lower()
        for i, (_n, c) in enumerate(self._couleurs_annotation):
            if c.lower() == code:
                self.an_couleur.setCurrentIndex(i)
                break
        for w in widgets:
            w.blockSignals(False)

    # ------------------------------------------------------- leurs retouches
    def _objet_calque(self, quoi):
        """(parent, objet) de la sélection si elle est de ce genre, sinon
        (None, None)."""
        sel = self._selected_calque
        if not sel or sel["quoi"] != quoi or self._sync:
            return None, None
        return sel["parent"], sel["objet"]

    def on_zone_charge_edited(self):
        cap, zone = self._objet_calque("zone")
        if zone is None:
            return
        zone["nom"] = self.zc_nom.text().strip() or "zone de charge"
        zone["t_m2"] = round(self.zc_t.value(), 3)
        self.refresh_all(keep_selection=True)

    def on_obstacle_edited(self):
        """Nom, nature et emprise d'une zone. La CASE décide de tout : cochée,
        la zone est un mur ; décochée, c'est un plafond bas — et son nom
        devient « hauteur libre X.XX m », la seule forme que le moteur relit."""
        cap, obs = self._objet_calque("obstacle")
        if obs is None:
            return
        x0, x1 = sorted((self.ob_x0.value(), self.ob_x1.value()))
        y0, y1 = sorted((self.ob_y0.value(), self.ob_y1.value()))
        obs[0], obs[1], obs[2], obs[3] = (round(x0, 4), round(y0, 4),
                                          round(x1, 4), round(y1, 4))
        if self.ob_bloquante.isChecked():
            nom = self.ob_nom.text().strip() or "Zone interdite"
            if hauteur_annoncee([0, 0, 1, 1, nom]) > 0:
                # le nom porte encore une hauteur (« hauteur libre 1.70 m ») :
                # la case ne bloquerait rien, puisque c'est le NOM qui décide.
                # On le remplace plutôt que de mentir à l'écran.
                nom = "Zone interdite"
        else:
            nom = nom_zone_hauteur(self.ob_hauteur.value())
        if len(obs) > 4:
            obs[4] = nom
        else:
            obs.append(nom)
        self.refresh_all(keep_selection=True)

    def on_annotation_edited(self):
        deck, note = self._objet_calque("annotation")
        if note is None:
            return
        note["texte"] = self.an_texte.text().strip()
        i = max(0, self.an_couleur.currentIndex())
        note["couleur"] = self._couleurs_annotation[i][1]
        self.refresh_all(keep_selection=True)

    # ------------------------------------------------------- leur suppression
    def delete_selected_calque(self):
        """Supprime la zone de charge, la zone d'obstacle ou l'annotation
        choisie. Ctrl+Z la remet en place, à son rang."""
        sel = self._selected_calque
        if not sel:
            return False
        quoi, parent, objet = sel["quoi"], sel["parent"], sel["objet"]
        attribut = {"zone": "zones_charge", "obstacle": "obstacles",
                    "annotation": "annotations"}[quoi]
        liste = getattr(parent, attribut, None) or []
        index = next((i for i, o in enumerate(liste) if o is objet), None)
        if index is None:
            return False
        self._push_undo_suppression(parent, attribut, objet, index)
        del liste[index]
        self._selected_calque = None
        self.props.setCurrentIndex(0)
        self.refresh_all()
        quoi_txt = {"zone": "Zone de charge", "obstacle": "Zone",
                    "annotation": "Information"}[quoi]
        self.statusBar().showMessage(
            f"{quoi_txt} supprimée de « "
            f"{getattr(parent, 'code', None) or getattr(parent, 'name', '?')} » "
            "— Ctrl+Z la remet en place.", 8000)
        return True

    # ------------------------------------------------------------------ retouche
    def _start_drag(self, kind, item, scene_pos, index=None):
        self._drag = {"kind": kind, "item": item, "index": index,
                      "start": scene_pos, "moved": False,
                      "orig_poly": [QPointF(p) for p in item.polygon()]}
        if kind == "vertex":
            # jamais la variante bloquante ici (2,6 s de gel au premier
            # glisser sur le plan d'ensemble) : l'accroche s'active seule
            self._ensure_vector_index(self.deck_scene.calibrated)
            # l'index des tracés est bâti UNE fois, ici : pendant le glisser
            # aucun autre sommet ne bouge, et le sommet tiré est écarté par
            # l'argument `exclude` de l'accroche
            self._local_snap_index("pont")

    def _annuler_drag(self):
        """Abandonne le glisser en cours et remet l'objet où il était.

        `rebuild()` redessine depuis le modèle mais ne défait pas le `setPos()`
        du glisser — `EpontilleItem.rebuild` ne fait qu'un `setRect` : sans la
        remise à zéro de la position, l'épontille reste dessinée décalée
        jusqu'au prochain rafraîchissement complet. Échap et le relâchement
        d'un glisser sans effet passent donc tous les deux par ici."""
        d, self._drag = self._drag, None
        if d is not None:
            item = d["item"]
            try:
                item.setPos(0, 0)
                item.rebuild()
            except RuntimeError:      # objet déjà remplacé par un rafraîchissement
                pass
        self.deck_scene.show_snap(None)
        return d

    # ------------------------------------------------------------ annulation
    # La pile porte trois sortes d'actions, toutes sous la même forme :
    # {"quoi", "parent", "attribut", "objet", "index", "points"}. Elle couvrait
    # jusqu'ici la seule retouche de contour ; elle couvre désormais l'AJOUT et
    # la SUPPRESSION des objets de calque et des épontilles — sinon un geste
    # malheureux sur une zone qu'on vient de tracer se rattrapait à la main.
    def _empiler(self, entree):
        self._undo.append(entree)
        del self._undo[:-UNDO_MAX]
        self.act_undo.setEnabled(True)

    def _push_undo(self, cap):
        """Avant une retouche de contour : ses sommets d'avant — et les
        indices verrouillés d'avant, qui suivent les insertions et les
        suppressions et n'ont donc plus la même valeur après."""
        self._empiler({"quoi": "points", "parent": cap,
                       "points": [tuple(p) for p in cap.points],
                       "verrous": list(cap.sommets_verrouilles)})

    def _push_undo_ajout(self, parent, attribut, objet):
        self._empiler({"quoi": "ajout", "parent": parent,
                       "attribut": attribut, "objet": objet})

    def _push_undo_suppression(self, parent, attribut, objet, index):
        self._empiler({"quoi": "suppr", "parent": parent, "attribut": attribut,
                       "objet": objet, "index": int(index)})

    def _oublier_undo(self, objets):
        """Sort de la pile tout ce qui porte sur des objets disparus.

        Comparaison par IDENTITÉ : deux capacités distinctes peuvent être
        égales au sens de `==` (ce sont des dataclasses), et on rejouerait
        alors une retouche sur la mauvaise."""
        morts = list(objets)
        self._undo = [u for u in self._undo
                      if not any(u.get("parent") is m or u.get("objet") is m
                                 for m in morts)]
        self.act_undo.setEnabled(bool(self._undo))

    @staticmethod
    def _nom_court(parent):
        return (getattr(parent, "code", None) or getattr(parent, "name", None)
                or "?")

    def undo(self):
        if not self._undo:
            self.statusBar().showMessage("Rien à annuler.", 3000)
            return
        u = self._undo.pop()
        quoi = u.get("quoi")
        if quoi == "points":
            cap = u["parent"]
            cap.points = [tuple(p) for p in u["points"]]
            if "verrous" in u:
                cap.sommets_verrouilles = list(u["verrous"])
            if self._selected_vertex is not None \
                    and self._selected_vertex >= len(cap.points):
                self._selected_vertex = None
            self._selected_capacity = cap
            self._after_edit()
            self.statusBar().showMessage(f"Retouche annulée sur {cap.code}.", 3000)
            return
        parent, attribut, objet = u["parent"], u["attribut"], u["objet"]
        liste = getattr(parent, attribut, None)
        if liste is None:
            return
        if quoi == "ajout":
            i = next((k for k, o in enumerate(liste) if o is objet), None)
            if i is not None:
                del liste[i]
            self._selected_calque = None
            self._selected_epontille = None
            self.props.setCurrentIndex(0)
            mot = "ajout"
        else:                                  # suppression : on la remet
            liste.insert(min(int(u.get("index", len(liste))), len(liste)), objet)
            mot = "suppression"
        self.refresh_all()
        self.statusBar().showMessage(
            f"{mot.capitalize()} annulé(e) sur « {self._nom_court(parent)} ».",
            5000)

    def _after_edit(self):
        """Après une retouche de contour : redessiner, garder la sélection."""
        self._local_index.pop("pont", None)
        self.refresh_all(keep_selection=True)

    def _set_selected_vertex(self, index):
        self._selected_vertex = index
        item = self._selected_item()
        if item is not None:
            item.set_current_vertex(index)
        self._refresh_vertex_widgets()

    def inserer_sommet_sur_arete(self, item, scene_pos, view) -> bool:
        """Insère un sommet sur le SEGMENT visé, à l'endroit cliqué.

        Le point est projeté sur le segment (jamais posé « à côté » du trait),
        puis accroché si l'accroche est active — c'est ce qui permet de poser
        le nouveau sommet exactement sur un couple ou sur l'angle d'une cale
        voisine. Une accroche qui ramènerait le point sur un sommet DÉJÀ là est
        ignorée : elle ferait un doublon invisible que personne ne saurait
        retrouver.

        Rend vrai si un sommet a été inséré. Sert au double-clic sur une arête
        comme au clic droit → « Ajouter un sommet ici »."""
        cap = item.capacity
        hit = item.hit_edge(scene_pos, EDGE_PX / view.view_scale())
        if hit is None:
            return False
        if cap.verrouillee:
            self._dire_verrou_cale(cap, "recevoir un sommet")
            return True
        arete, pt = hit
        pos, accroche = self._snap(view, pt, Qt.KeyboardModifier.NoModifier)
        if accroche:
            poly = item.polygon()
            if any((pos - poly.at(k)).manhattanLength() < 1e-6
                   for k in range(poly.count())):
                pos = pt
        self.insert_vertex(cap, arete + 1, pos)
        return True

    def insert_vertex(self, cap, index, pixel_pos):
        cal = self.deck_scene.calibrated.calibration if self.deck_scene.calibrated else None
        if cal is None or not cal.valid:
            return
        if cap.verrouillee:
            self._dire_verrou_cale(cap, "recevoir un sommet")
            return
        self._push_undo(cap)
        # par le modèle : c'est lui qui fait suivre les indices verrouillés,
        # sans quoi insérer un sommet AVANT un sommet figé figerait son voisin
        cap.inserer_sommet(index, _real(cal, pixel_pos))
        self._selected_vertex = index
        self._after_edit()
        self.statusBar().showMessage(
            f"Sommet inséré (n°{index + 1}) — glissez-le pour le placer.", 5000)

    def delete_selected_vertex(self):
        cap = self._selected_capacity
        i = self._selected_vertex
        if cap is None or i is None or i >= len(cap.points):
            return
        if self._verrou_refuse(cap, i, "retirer"):
            return
        if len(cap.points) <= 3:
            QMessageBox.information(self, "Sommet", "Un contour garde au moins "
                                    "3 sommets : supprimez plutôt la capacité.")
            return
        self._push_undo(cap)
        cap.supprimer_sommet(i)
        self._selected_vertex = min(i, len(cap.points) - 1)
        self._after_edit()

    # ------------------------------------------------------------- verrouiller
    def basculer_verrou_cale(self, cap, on=None):
        """Verrouille ou libère une cale entière.

        Le verrou n'entre PAS dans la pile d'annulation : ce n'est pas une
        retouche du tracé mais une consigne sur le tracé, et elle se défait par
        le même geste qui l'a posée."""
        cap.verrouillee = (not cap.verrouillee) if on is None else bool(on)
        self.refresh_all(keep_selection=True)
        self.statusBar().showMessage(
            f"Cale {cap.code} VERROUILLÉE — ses sommets ne bougent plus."
            if cap.verrouillee else
            f"Cale {cap.code} déverrouillée — elle se retouche à nouveau.",
            6000)

    def basculer_verrou_sommet(self, cap, index, on=None):
        """Fige ou libère UN sommet — pour tenir un coin sur un couple sans
        immobiliser le reste du contour."""
        if cap.verrouillee:
            self._dire_verrou_cale(cap, "changer de verrou sommet par sommet")
            return
        fige = cap.sommet_verrouille(index) if on is None else not bool(on)
        cap.verrouiller_sommet(index, not fige)
        self.refresh_all(keep_selection=True)
        self.statusBar().showMessage(
            f"Sommet n°{index + 1} de {cap.code} "
            + ("déverrouillé." if fige else
               "VERROUILLÉ — il ne se déplacera plus."), 6000)

    def on_vertex_index(self, value):
        cap = self._selected_capacity
        if cap is None or self._sync:
            return
        i = value - 1
        if 0 <= i < len(cap.points):
            self._set_selected_vertex(i)

    def on_vertex_edited(self):
        cap = self._selected_capacity
        i = self._selected_vertex
        if cap is None or i is None or self._sync or i >= len(cap.points):
            return
        new = (self.vtx_x.value(), self.vtx_y.value())
        if abs(new[0] - cap.points[i][0]) < 1e-9 and abs(new[1] - cap.points[i][1]) < 1e-9:
            return
        if self._verrou_refuse(cap, i, "déplacer"):
            # les champs affichent à nouveau la vraie valeur : un sommet figé
            # qui resterait affiché déplacé serait un mensonge de plus
            self._refresh_vertex_widgets()
            return
        self._push_undo(cap)
        cap.points[i] = new
        self._after_edit()

    def _refresh_vertex_widgets(self):
        cap = self._selected_capacity
        widgets = (self.vtx_index, self.vtx_x, self.vtx_y)
        for w in widgets:
            w.blockSignals(True)
        n = len(cap.points) if cap is not None else 0
        self.vtx_index.setRange(1, max(1, n))
        i = self._selected_vertex
        has = cap is not None and i is not None and 0 <= i < n
        self.vtx_index.setValue(i + 1 if has else 1)
        self.vtx_x.setValue(cap.points[i][0] if has else 0.0)
        self.vtx_y.setValue(cap.points[i][1] if has else 0.0)
        fige = has and cap.sommet_verrouille(i)
        for w in (self.vtx_x, self.vtx_y, self.vtx_delete):
            w.setEnabled(has and not fige)
        self.vtx_title.setText(
            f"<b>Sommets du contour</b> — {n}"
            + (f", n°{i + 1} choisi" if has else " (cliquez une poignée)")
            + (" 🔒 verrouillé" if fige else ""))
        for w in widgets:
            w.blockSignals(False)

    # ------------------------------------------------------------------ sélection
    def _deselectionner_calques(self):
        """Éteint la surbrillance de tous les objets de calque du pont."""
        sc = self.deck_scene
        for it in (sc.zone_items + sc.obstacle_items + sc.annotation_items):
            it.setSelected(False)

    def select_capacity(self, capacity, annoncer=True):
        """Choisit cette capacité partout (plan, profil, iso, propriétés).

        `annoncer` : dire les gestes dans la barre d'état. Un rafraîchissement
        qui ne fait que RETROUVER la sélection ne les redit pas — il écraserait
        le message que le geste précédent vient d'y laisser."""
        if self._sync:
            return
        self._sync = True
        try:
            if capacity is not self._selected_capacity:
                self._selected_vertex = None
            self._selected_capacity = capacity
            self._selected_epontille = None
            self._selected_calque = None
            for it in self.deck_scene.epontille_items:
                it.setSelected(False)
            self._deselectionner_calques()
            for scene in (self.profile_scene, self.deck_scene):
                for it in scene.object_items:
                    if isinstance(it, (DeckCapacityItem, ProfileCapacityItem)):
                        it.setSelected(getattr(it, "capacity", None) is capacity)
            item = self.deck_scene.item_for_capacity(capacity)
            if isinstance(item, DeckCapacityItem):
                item.set_current_vertex(self._selected_vertex)
            self.iso_view.select_capacity(capacity)
            self.show_capacity_props(capacity)
        finally:
            self._sync = False
        if annoncer and capacity is not None:
            self._dire_gestes_de_cale(capacity)

    def _dire_gestes_de_cale(self, cap):
        """Les gestes d'une cale choisie, dans la barre d'état.

        Le bord n'avait pas trouvé comment AJOUTER un sommet (« difficile,
        impossible ? ») : les deux gestes qui le font sont donc écrits là où il
        regarde déjà, au moment où il vient de choisir la cale."""
        quoi = "Contour du pont" if cap.kind == KIND_CONTOUR else f"Cale {cap.code}"
        if cap.verrouillee:
            self.statusBar().showMessage(
                f"{quoi} — 🔒 VERROUILLÉE : rien ne s'y déplace. Clic droit "
                "→ « Déverrouiller la cale » pour la retoucher.", 12000)
            return
        msg = (f"{quoi} — ajouter un sommet : CLIC DROIT sur un segment "
               "(« Ajouter un sommet ici ») ou DOUBLE-CLIC sur ce segment  ·  "
               "glisser une poignée : déplacer le sommet  ·  Suppr : le "
               "retirer  ·  clic droit sur une poignée : la verrouiller.")
        alerte = self.avertissement_recouvrements()
        self.statusBar().showMessage(msg + ("      " + alerte if alerte else ""),
                                     12000)

    def on_scene_selection(self, scene):
        if self._sync:
            return
        try:
            selected = [it for it in scene.selectedItems() if _vivant(it)]
        except RuntimeError:
            return  # scène détruite (fermeture de l'application)
        for it in selected:
            if isinstance(it, EpontilleItem):
                self.select_epontille(it.capacity, it.epontille)
                return
            # AVANT le cas général : une zone de charge et une zone interdite
            # portent elles aussi un attribut `capacity` — celui de la cale qui
            # les contient. Sans ce passage, cliquer une zone sélectionnait sa
            # cale, et le bord se retrouvait à retoucher un contour.
            if self._quoi_item(it) is not None:
                self.select_objet_calque_item(it)
                return
            cap = getattr(it, "capacity", None)
            if cap is not None:
                for deck in self.project.decks:
                    if cap in deck.capacities and deck is not self.current_deck:
                        self.set_current_deck(deck)
                        break
                self.select_capacity(cap)
                return
            deck = getattr(it, "deck", None)
            if deck is not None:
                self.set_current_deck(deck)
                self.show_deck_props(deck)
                return

    def on_iso_selection(self):
        if self._sync:
            return
        try:
            selected = self.iso_view.scene().selectedItems()
        except RuntimeError:
            return
        for it in selected:
            cap = getattr(it, "capacity", None)
            if cap is not None:
                for deck in self.project.decks:
                    if cap in deck.capacities and deck is not self.current_deck:
                        self.set_current_deck(deck)
                        break
                self.select_capacity(cap)
                return

    # ------------------------------------------------------------------ propriétés
    def show_capacity_props(self, cap):
        """Les champs de la sélection, et rien d'autre : un contour de pont n'a
        ni code, ni nom, ni étendue verticale — ces lignes disparaissent au
        lieu de rester grisées à occuper la colonne."""
        if cap is None:
            self.props.setCurrentIndex(0)
            return
        self.props.setCurrentIndex(1)
        contour = cap.kind == KIND_CONTOUR
        widgets = (self.cap_code, self.cap_name, self.cap_zmin,
                   self.cap_zmax, self.cap_fill, self.cap_imdg)
        for w in widgets:
            w.blockSignals(True)
        self.cap_code.setText(cap.code)
        self.cap_name.setText(cap.name)
        self.cap_imdg.setText(", ".join(getattr(cap, "classes_imdg", []) or []))
        self.cap_zmin.setValue(cap.z_min)
        self.cap_zmax.setValue(cap.z_max)
        self.cap_fill.setValue(round(cap.fill * 100))
        self.cap_fill_lbl.setText(f"{round(cap.fill * 100)} %")
        for w in widgets:
            w.setEnabled(not contour)
            w.blockSignals(False)
        for row in self.cap_rows_capacite:
            self.cap_form.setRowVisible(row, not contour)
        self.cap_title.setText(
            "<b>Contour du pont</b>" if contour
            else f"<b>Capacité {cap.code}</b>")
        self.cap_delete.setText("Supprimer ce contour de pont" if contour
                                else "Supprimer cette capacité")
        self.cap_verrou.blockSignals(True)
        self.cap_verrou.setChecked(bool(cap.verrouillee))
        self.cap_verrou.blockSignals(False)
        self._refresh_vertex_widgets()

    def show_profile_props(self):
        self.props.setCurrentIndex(3)
        prof = self.project.profile
        if not prof.image_path:
            txt = ("Aucun profil : importez une image ou un PDF de la coupe "
                   "longitudinale, puis calez-le (2 à 3 points connus).")
        elif not prof.calibration.valid:
            txt = (f"Plan : {os.path.basename(prof.image_path)}\n"
                   f"{len(prof.cal_points)} point(s) de calage — cliquez « Caler », "
                   "placez les points, puis « Appliquer ».")
        else:
            txt = f"Plan : {os.path.basename(prof.image_path)}\n" \
                + self.calibration_report(prof).split("\n\n")[0]
        if prof.from_pdf:
            txt += (f"\nPDF : {os.path.basename(prof.pdf_path)}, page "
                    f"{prof.pdf_page + 1}, {prof.pdf_dpi} dpi"
                    + (f", tourné de {prof.pdf_rotation}°" if prof.pdf_rotation else ""))
        self.prof_info.setText(txt)

    def show_deck_props(self, deck):
        self._selected_deck = deck
        self.props.setCurrentIndex(2)
        for w in (self.deck_name, self.deck_z, self.deck_alias):
            w.blockSignals(True)
        self.deck_name.setText(deck.name)
        self.deck_z.setValue(deck.z)
        self.deck_alias.setText(deck.alias)
        for w in (self.deck_name, self.deck_z, self.deck_alias):
            w.blockSignals(False)
        n = deck.n_capacities()
        plan = deck.plan
        if not plan.image_path:
            txt = ("Plan non importé : importez le plan de ce pont (image ou "
                   "PDF), puis placez 2 points sur la ligne de foi et 1 point "
                   "hors axe.")
        elif not plan.calibration.valid:
            txt = (f"Plan : {os.path.basename(plan.image_path)}\n"
                   f"{len(plan.cal_points)} point(s) de calage placé(s) — "
                   "« Caler ce plan » puis « Appliquer ».")
        else:
            txt = f"Plan : {os.path.basename(plan.image_path)}\n" \
                + self.calibration_report(plan).split("\n\n")[0]
        if plan.from_pdf:
            txt += (f"\nPDF : {os.path.basename(plan.pdf_path)}, page "
                    f"{plan.pdf_page + 1}, {plan.pdf_dpi} dpi"
                    + (f", tourné de {plan.pdf_rotation}°" if plan.pdf_rotation else ""))
        txt += f"\n{n} capacité(s) sur ce pont."
        self.deck_info.setText(txt)

    def on_cap_edited(self):
        cap = self._selected_capacity
        if cap is None:
            return
        nouveau = self.cap_code.text().strip().upper()
        if nouveau and nouveau != cap.code:
            # UN CODE, UNE CALE (2.20.1) : deux cales au même code faisaient
            # compter deux fois la cargaison rangée sous ce code. Et le code
            # d'une AUTRE cale, même ancien, désignerait ses colis d'autrefois.
            pris = set()
            for _d, autre in self.project.all_capacities():
                if autre is not cap:
                    pris.add(autre.code)
                    pris.update(getattr(autre, "anciens_codes", []) or [])
            if nouveau in pris:
                self.cap_code.blockSignals(True)
                self.cap_code.setText(cap.code)
                self.cap_code.blockSignals(False)
                self.statusBar().showMessage(
                    f"Code « {nouveau} » refusé : il désigne déjà une autre "
                    "capacité (ou l'a désignée). Un code, une cale — sinon "
                    "la cargaison rangée sous ce code serait comptée deux "
                    "fois.", 12000)
            else:
                # l'ancien code est gardé : les colis des points déjà écrits
                # restent dans cette cale (voir Capacity.anciens_codes)
                cap.changer_code(nouveau)
        cap.name = self.cap_name.text().strip()
        cap.z_min = self.cap_zmin.value()
        cap.z_max = self.cap_zmax.value()
        self.refresh_all(keep_selection=True)

    def on_cap_imdg(self):
        cap = self._selected_capacity
        if cap is None:
            return
        from .core.stowage import classes_imdg_de
        classes = classes_imdg_de(self.cap_imdg.text())
        if classes == list(getattr(cap, "classes_imdg", []) or []):
            return
        cap.classes_imdg = classes
        self.statusBar().showMessage(
            f"{cap.code} : " + ("aucune marchandise dangereuse." if not classes else
                                "classes IMDG admises : " + ", ".join(classes) + "."),
            8000)

    def on_cap_verrou(self, on):
        cap = self._selected_capacity
        if cap is None or self._sync or bool(cap.verrouillee) == bool(on):
            return
        self.basculer_verrou_cale(cap, bool(on))

    def on_cap_fill(self, value):
        cap = self._selected_capacity
        if cap is None:
            return
        cap.fill = value / 100.0
        self.cap_fill_lbl.setText(f"{value} %")
        if self.cap_fill.isSliderDown():
            # pendant le glissement, on ne redessine que les deux objets
            # concernés : refaire toute la fenêtre coûtait 17 ms par cran
            # (arbre, tableau des vues, vue iso reconstruite entièrement),
            # et le curseur devenait poisseux. Les deux objets relisent
            # `cap.fill` à la peinture ; le reste rattrape au relâchement.
            for scene in (self.profile_scene, self.deck_scene):
                it = scene.item_for_capacity(cap)
                if it is None:
                    continue
                if isinstance(it, DeckCapacityItem):
                    it.maj_remplissage()
                else:
                    it.update()
            return
        self.refresh_all(keep_selection=True)

    def on_cap_fill_lache(self):
        """Curseur de remplissage relâché : la vue iso et les tableaux, qui
        n'ont pas suivi cran par cran, se remettent à jour d'un coup."""
        if self._selected_capacity is not None:
            self.refresh_all(keep_selection=True)

    def on_deck_edited(self):
        deck = self._selected_deck
        if deck is None:
            return
        deck.name = self.deck_name.text().strip() or deck.name
        deck.z = self.deck_z.value()
        deck.alias = self.deck_alias.text().strip()
        self.refresh_all()

    def delete_selected_capacity(self):
        cap = self._selected_capacity
        if cap is None:
            return
        if cap.verrouillee:
            # une suppression ne se rattrape pas par Ctrl+Z (voir le message
            # plus bas) : c'est très exactement ce contre quoi le verrou a été
            # demandé
            self._dire_verrou_cale(cap, "être supprimée")
            return
        for deck in self.project.decks:
            if cap in deck.capacities:
                deck.capacities.remove(cap)
        self._selected_capacity = None
        self._selected_vertex = None
        if self._selected_calque and self._selected_calque["parent"] is cap:
            self._selected_calque = None
        self._oublier_undo([cap])
        self.props.setCurrentIndex(0)
        self.refresh_all()
        # dire ce qui vient de disparaître : la suppression est immédiate et
        # les retouches de CETTE capacité sont sorties de la pile d'annulation
        self.statusBar().showMessage(
            f"Capacité {cap.code} supprimée — il faut la retracer pour la "
            "retrouver (Ctrl+Z ne défait que les retouches de contour).", 8000)

    # ------------------------------------------------------------------ ponts
    def add_deck_dialog(self):
        decks = self.project.sorted_decks()
        z = (decks[-1].z + 2.5) if decks else 0.0
        dlg = DeckDialog(self, z=z, decks=decks)
        if dlg.exec():
            name, z = dlg.values()
            d = self.project.add_deck(name, z, dlg.alias(), dlg.copy_from())
            self.refresh_all()
            self.show_view(d)

    def set_current_deck(self, deck):
        if deck is self.current_deck:
            return
        self.current_deck = deck
        self._local_index.pop("pont", None)
        if deck is None:
            self.deck_scene.load(None)
            self.header_deck.setText("PONT COURANT · X–Y")
            return
        self.deck_scene.load(deck.plan, project=self.project, deck=deck)
        self.header_deck.setText(f"PONT COURANT · {deck.name.upper()} · X–Y")
        self._refresh_hud()
        if self.deck_scene.pixmap_item is not None:
            self.deck_view.fitInView(self.deck_scene.pixmap_item,
                                     Qt.AspectRatioMode.KeepAspectRatio)
        self._update_snap_state()

    def charger_projet(self, project):
        """Reprend la fenêtre sur un AUTRE navire (ou sur le même rechargé).

        La fenêtre de l'éditeur est unique et ré-ouverte telle quelle : sans
        cela, la pile d'annulation et la sélection restaient celles du navire
        précédent. Ctrl+Z aurait alors réécrit les points d'une capacité qui
        n'appartient plus au projet affiché — une cale du navire d'avant,
        remise en place à l'aveugle."""
        self.project = project
        self._undo = []
        self._selected_capacity = None
        self._selected_epontille = None
        self._selected_calque = None
        self._selected_vertex = None
        self._selected_deck = None
        self._drag = None
        self._cancel_rect()
        self._local_index = {}
        self._couples_signale = False   # autre navire, autre couples.csv
        self._perp_signale = False
        # par la méthode, pour que la scène du pont se vide aussi : laisser
        # `current_deck` à None sans recharger garderait le plan d'avant
        self.set_current_deck(None)
        self.act_undo.setEnabled(False)
        self.props.setCurrentIndex(0)

    # ------------------------------------------------------------------ fichiers
    def new_ship(self):
        """Repart de plans vierges (les tables du navire ne sont pas touchées)."""
        self.project = Project(
            ship_name=self.project.ship_name,
            navire_virtuel_path=self.ship_folder or app_paths.ship_folder())
        self.current_deck = None
        self._selected_capacity = None
        self._selected_deck = None
        self._undo = []
        self.refresh_all()
        self.open_wizard()

    def _plans_folder(self):
        folder = self.ship_folder or self.project.navire_virtuel_path \
            or app_paths.ship_folder()
        return os.path.join(folder, "plans")

    def import_pdf(self, pdf_path, page, rotation, dpi, target) -> Calibrated:
        """Rend une page de PDF en image dans `plans/` du dossier du navire et
        l'affecte à la vue `target` ("profil" ou Deck). Lève ValueError si
        l'image serait démesurée (le message dit quoi faire)."""
        ship = os.path.dirname(os.path.abspath(self._plans_folder()))
        out, dest_pdf = pdf_plan.import_into(pdf_path, page, rotation, dpi, ship)
        axes = ("X", "Z") if target == "profil" else ("X", "Y")
        cal = Calibrated(image_path=out, axes=axes, pdf_path=dest_pdf,
                         pdf_page=int(page), pdf_rotation=int(rotation) % 360,
                         pdf_dpi=int(dpi))
        if target == "profil":
            self.project.profile = cal
        else:
            target.plan = cal
            if self.current_deck is target:
                self.current_deck = None
            self.set_current_deck(target)
        # Le PDF vient d'entrer dans `plans/` : qu'il soit venu du catalogue ou
        # de la boîte de fichiers, il appartient maintenant au navire — donc au
        # catalogue. C'est ICI, au seul endroit par où passent tous les imports
        # de PDF, plutôt que dans chacun de leurs appelants.
        self.synchroniser_catalogue()
        return cal

    def synchroniser_catalogue(self):
        """Inscrit au catalogue les PDF de `plans/` qu'une vue emploie sans
        qu'ils y figurent. Ne fait jamais échouer un import : un catalogue non
        écrit (dossier en lecture seule) ne doit pas coûter un plan."""
        ship = os.path.dirname(os.path.abspath(self._plans_folder()))
        try:
            return catalogue_plans.synchroniser(ship, self.project)
        except Exception:
            return None

    def import_dxf(self, dxf_path, calques, largeur_cible, target,
                   calage_auto=False, decalage=(0.0, 0.0)) -> Calibrated:
        """Rend les calques retenus d'un DXF en image dans `plans/` du dossier
        du navire et l'affecte à la vue `target` ("profil" ou Deck).

        `calage_auto` : le dessin porte ses coordonnées réelles (D-9), on en
        déduit le calage au lieu de cliquer deux points ; `decalage` donne les
        coordonnées navire du point (0, 0) du dessin. Le calage manuel reste
        possible ensuite — deux points posés et « Appliquer » l'emportent, ce
        qui est la façon d'ajuster l'échelle sur les traits de couples (D-11).
        """
        ship = os.path.dirname(os.path.abspath(self._plans_folder()))
        out, dest, w, h, origine, res = dxf_plan.import_into(
            dxf_path, ship, calques=calques, largeur_cible=largeur_cible)
        axes = ("X", "Z") if target == "profil" else ("X", "Y")
        cal = Calibrated(image_path=out, axes=axes, dxf_path=dest,
                         dxf_layers=list(calques or []),
                         dxf_origin=(float(origine[0]), float(origine[1])),
                         dxf_resolution=float(res), dxf_size=(int(w), int(h)))
        if calage_auto:
            dessin = dxf_plan.dessin_pour(dest)
            M = dxf_plan.matrice_calage(origine, res, dessin.metres_par_unite,
                                        decalage)
            if M is not None:
                cal.calibration = Calibration(M)
        if target == "profil":
            self.project.profile = cal
        else:
            target.plan = cal
            if self.current_deck is target:
                self.current_deck = None
            self.set_current_deck(target)
        return cal

    def _importer_dxf(self, path, target):
        """Le déroulé complet d'un import DXF : calques, rendu, calage."""
        axes = ("X", "Z") if target == "profil" else ("X", "Y")
        try:
            dlg = DxfImportDialog(path, self, axes=axes)
        except Exception as e:
            QMessageBox.warning(self, "DXF illisible", str(e))
            return None
        if not dlg.exec():
            return None
        calques, largeur, auto, decalage = dlg.values()
        app = QApplication.instance()
        if app is not None:
            app.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.statusBar().showMessage("Rendu des calques du DXF…")
        if app is not None:
            app.processEvents()
        try:
            cal = self.import_dxf(path, calques, largeur, target, auto, decalage)
        except Exception as e:
            if app is not None:
                app.restoreOverrideCursor()
            QMessageBox.warning(self, "Import DXF", str(e))
            return None
        if app is not None:
            app.restoreOverrideCursor()
        self._ensure_vector_index(cal)
        alertes = dlg.dessin.avertissements()
        if auto and cal.calibration.valid:
            self.statusBar().showMessage(
                "Plan DXF calé sur ses propres coordonnées "
                f"({dlg.dessin.unite_nom}). Vérifiez que la grille tombe sur "
                "les couples ; sinon, posez deux points et appliquez le "
                "calage.", 12000)
        elif alertes:
            self.statusBar().showMessage("DXF importé — " + " ".join(alertes),
                                         12000)
        return cal

    def _importer_pdf(self, path, target, page=0):
        """Le déroulé complet d'un import PDF : page, rotation, rendu, accroche.

        `page` : la page déjà désignée (catalogue) — la fiche s'ouvre dessus."""
        try:
            dlg = PdfImportDialog(path, self, page=page)
        except Exception as e:
            QMessageBox.warning(self, "PDF illisible", str(e))
            return None
        if not dlg.exec():
            return None
        page, rot, dpi = dlg.values()
        app = QApplication.instance()
        if app is not None:
            app.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.statusBar().showMessage("Rendu de la page du PDF…")
        if app is not None:
            app.processEvents()
        try:
            cal = self.import_pdf(path, page, rot, dpi, target)
        except Exception as e:
            if app is not None:
                app.restoreOverrideCursor()
            QMessageBox.warning(self, "Import PDF", str(e))
            return None
        if app is not None:
            app.restoreOverrideCursor()
        self._ensure_pdf_index(cal)
        return cal

    def catalogue_du_navire(self):
        """Le catalogue des plans PDF du navire (jamais None)."""
        ship = os.path.dirname(os.path.abspath(self._plans_folder()))
        try:
            return catalogue_plans.charger(ship)
        except Exception:
            return catalogue_plans.catalogue_vide()

    def open_catalogue(self, target=None, autre_fichier=False) -> str:
        """Ouvre le CATALOGUE des plans pour la vue `target` (« profil » ou un
        Deck ; la vue active par défaut).

        Rend ce qui s'est passé : « importe » (une page a été affectée à la
        vue), « autre » (le bord veut la boîte de fichiers) ou "" (rien). Ce
        code de retour est ce qui permet à `import_plan_for` de proposer le
        catalogue D'ABORD sans perdre l'import par fichier."""
        if target is None:
            target = "profil" if self.active == "profil" else self.current_deck
        if target is None:
            QMessageBox.information(
                self, "Catalogue des plans",
                "Sélectionnez d'abord un pont (ou la vue du profil) : une page "
                "du catalogue s'affecte à une vue.")
            return ""
        # ce qui est déjà employé par les vues entre au catalogue avant de
        # l'ouvrir : sinon un navire d'avant le catalogue s'y montre vide
        self.synchroniser_catalogue()
        ship = os.path.dirname(os.path.abspath(self._plans_folder()))
        vue = "profil" if target == "profil" else f"pont {target.name}"
        dlg = CatalogueDialog(ship, self, project=self.project, vue=vue,
                              autre_fichier=autre_fichier)
        if not dlg.exec():
            return ""
        if dlg.veut_autre_fichier():
            return "autre"
        choix = dlg.choix()
        if not choix:
            return ""
        chemin, page = choix
        if self._importer_pdf(chemin, target, page=page) is None:
            return ""
        self.refresh_all()
        self.zoom_fit()
        self.show_view(target)
        return "importe"

    def import_plan_for(self, target):
        """Choix du plan pour la vue `target` : le CATALOGUE d'abord quand il
        y a des plans dedans, la boîte de fichiers sinon (ou sur demande).

        Le bord importe dix pages du même plan d'ensemble : lui rouvrir une
        boîte de fichiers à chaque fois, c'est lui faire rechercher dix fois
        un PDF qui est déjà dans le dossier de son navire."""
        if target is None:
            QMessageBox.information(self, "Plan", "Sélectionnez d'abord une vue.")
            return
        if self.catalogue_du_navire().get("plans"):
            if self.open_catalogue(target, autre_fichier=True) != "autre":
                return
        self.import_plan_fichier(target)

    def import_plan_fichier(self, target):
        """La boîte de fichiers habituelle (image, PDF ou DXF) pour `target`.

        C'est l'autre moitié d'`import_plan_for` : le chemin qu'emprunte
        « Autre fichier… » du catalogue, qui ne doit pas y ramener."""
        if target is None:
            QMessageBox.information(self, "Plan", "Sélectionnez d'abord une vue.")
            return
        titre = ("Importer le profil longitudinal" if target == "profil"
                 else f"Importer le plan du pont « {target.name} »")
        path, _ = QFileDialog.getOpenFileName(self, titre, "", FILTRE_PLANS)
        if not path:
            return
        if path.lower().endswith(".dwg"):
            QMessageBox.information(self, "DWG à convertir", MESSAGE_DWG)
            return
        if path.lower().endswith(".dxf"):
            if self._importer_dxf(path, target) is None:
                return
        elif path.lower().endswith(".pdf"):
            if self._importer_pdf(path, target) is None:
                return
        else:
            axes = ("X", "Z") if target == "profil" else ("X", "Y")
            # l'image est rangée dans `plans/` comme le PDF et le DXF : sinon
            # `geometrie.json` retient un chemin absolu hors du navire, et la
            # vue est vide dès que le dossier change de machine
            ship = os.path.dirname(os.path.abspath(self._plans_folder()))
            cal = Calibrated(image_path=app_paths.ranger_dans_plans(path, ship),
                             axes=axes)
            if target == "profil":
                self.project.profile = cal
            else:
                target.plan = cal
                if self.current_deck is target:
                    self.current_deck = None
                self.set_current_deck(target)
        self.refresh_all()
        self.zoom_fit()
        self.show_view(target)

    def import_plan_active(self):
        self.import_plan_for("profil" if self.active == "profil" else self.current_deck)

    def import_profile(self):
        self.import_plan_for("profil")

    def import_deck_plan(self):
        deck = self.current_deck or self._selected_deck
        if deck is None:
            QMessageBox.information(self, "Pont",
                                    "Sélectionnez d'abord un pont.")
            return
        self.import_plan_for(deck)

    def reprendre_schema(self):
        """Convertit la silhouette schématique en géométrie modifiable.

        Elle cesse alors d'être signalée comme schématique : elle devient le
        tracé de l'utilisateur, et plus rien ne la distingue d'un contour relevé
        sur plan. C'est pourquoi on le demande explicitement, et qu'on ne
        touche à rien de ce qui est déjà tracé."""
        from .core import coque as _coque
        from .core.navire import Navire

        dossier = getattr(self, "ship_folder", None)
        try:
            nav = Navire.load(dossier) if dossier else None
        except Exception as e:
            nav = None
            erreur = str(e)
        if nav is None:
            QMessageBox.information(
                self, "Silhouette schématique",
                "Les tables du navire ne sont pas lisibles : impossible de "
                "reconstituer une coque."
                + (f"\n\n{erreur}" if dossier else ""))
            return
        rep = QMessageBox.question(
            self, "Reprendre la silhouette schématique",
            "La coque reconstituée depuis les tables va être écrite dans la "
            "géométrie, avec une capacité par soute ou ballast.\n\n"
            "Elle respecte le volume, l'aire et le centre de flottaison du "
            "dossier à chaque tirant d'eau tabulé, mais l'emprise de chaque "
            "capacité reste supposée : à retoucher sur plan.\n\n"
            "Une fois reprise, plus rien ne la distinguera d'un tracé fait sur "
            "plan. Continuer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if rep != QMessageBox.StandardButton.Yes:
            return
        n_ponts, n_caps = _coque.reprendre_en_geometrie(nav, self.project)
        self.refresh_all()
        self.statusBar().showMessage(
            f"Silhouette reprise : {n_ponts} contour(s) de pont, "
            f"{n_caps} capacité(s). Enregistrez les plans pour la conserver.",
            12000)

    def save_project(self):
        """Écrit la géométrie dans le dossier du navire (un navire = un
        dossier) et prévient la fenêtre principale."""
        folder = self.ship_folder or app_paths.ship_folder()
        try:
            path = self.project.save_geometry(folder)
        except Exception as e:
            QMessageBox.critical(self, "Enregistrer", f"Échec : {e}")
            return
        self.ship_folder = folder
        # Le rapport d'enregistrement dit ce qui a été écrit ET ce qui reste à
        # reprendre : un recouvrement n'empêche pas d'enregistrer (le bord doit
        # pouvoir sauver un plan à moitié retracé), mais il ne doit pas partir
        # dans le dossier du navire sans que personne ne l'ait lu.
        msg = f"Plans enregistrés : {path}"
        rec = self.project.recouvrements()
        if rec:
            bouts = [f"{a.code}/{b.code} sur {self._cm(d)} ({deck.name})"
                     for deck, a, b, d in rec[:3]]
            msg += (f"   ⚠ {len(rec)} chevauchement(s) de cales à corriger : "
                    + " ; ".join(bouts))
        self.statusBar().showMessage(msg, 15000)
        self.refresh_wizard()
        self.geometry_saved.emit()

    def import_legacy_project(self):
        """Reprend un ancien fichier .carene.json (plans séparés des tables).

        Les plans de palettes qu'il contenait éventuellement ne sont pas repris
        ici : ils appartiennent désormais à une condition de chargement."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Reprendre un ancien fichier navire", "",
            "Ancien projet Carène (*.carene.json *.json)")
        if not path:
            return
        try:
            proj = Project.load(path)
        except Exception as e:
            QMessageBox.warning(self, "Ouverture", str(e))
            return
        n_pal = len(proj.legacy_pallets())
        proj.navire_virtuel_path = self.ship_folder or app_paths.ship_folder()
        self.project = proj
        self.current_deck = None
        self._undo = []
        decks = self.project.sorted_decks()
        if decks:
            self.set_current_deck(decks[0])
        self.refresh_all()
        self.zoom_fit()
        msg = "Ancien fichier repris — enregistrez pour le ranger dans le dossier du navire."
        if n_pal:
            msg += (f" {n_pal} plan(s) de palettes ont été ignorés : ils "
                    "appartiennent maintenant aux cas de chargement.")
        self.statusBar().showMessage(msg, 15000)

    # ------------------------------------------------------------------ divers
    def refresh_all(self, keep_selection=False):
        sel = self._selected_capacity if keep_selection else None
        vtx = self._selected_vertex if keep_selection else None
        ep = self._selected_epontille if keep_selection else None
        calque = self._selected_calque if keep_selection else None
        self._selected_epontille = None
        self._selected_calque = None
        self._drag = None
        self._local_index = {}
        self.profile_scene.load(self.project.profile, project=self.project)
        if self.current_deck is not None and self.current_deck not in self.project.decks:
            self.current_deck = None
        if self.current_deck is not None:
            self.deck_scene.load(self.current_deck.plan, project=self.project,
                                 deck=self.current_deck)
        else:
            self.deck_scene.load(None)
        self.iso_view.rebuild(self.project)
        self.iso_view.fit()
        self.refresh_tree()
        self.refresh_views_table()
        self.refresh_wizard()
        self.act_undo.setEnabled(bool(self._undo))
        self._update_snap_state()
        self._refresh_hud()
        if calque is not None:
            self.select_objet_calque(calque["quoi"], calque["parent"],
                                     calque["objet"])
        elif ep is not None:
            self.select_epontille(*ep)
        elif sel is not None:
            self._selected_vertex = vtx
            # sans `annoncer=False`, chaque rafraîchissement effacerait le
            # message du geste qui vient de l'appeler
            self.select_capacity(sel, annoncer=False)
        elif self._selected_deck is not None and self.props.currentIndex() == 2:
            self.show_deck_props(self._selected_deck)
        elif self.props.currentIndex() == 3:
            self.show_profile_props()

    def toggle_grid(self, checked):
        self.profile_scene.set_grid_visible(checked)
        self.deck_scene.set_grid_visible(checked)
        if hasattr(self, "layers_panel"):
            self.layers_panel.set_checked("grille", checked)
            self._save_session_layout()

    def retheme_tout(self):
        """Repeint palette, icônes et vues avec la palette (une seule, D-72)."""
        app = QApplication.instance()
        if app is None:
            return
        theme.apply_theme(app)
        for scene in (self.profile_scene, self.deck_scene):
            scene.setBackgroundBrush(QColor(theme.BG_DEEP))
        self.iso_view.scene().setBackgroundBrush(QColor(theme.BG_DEEP))
        for a, name in ((self.act_wizard, "wand"), (self.act_cal, "target"),
                        (self.act_cal_apply, "grid"), (self.act_decks, "decks"),
                        (self.act_poly, "polygon"), (self.act_contour, "contour"),
                        (self.act_grid, "grid"),
                        (self.act_snap, "target"), (self.act_import, "image"),
                        (self.act_epontille, "polygon"),
                        (self.act_interdit, "contour"),
                        (self.act_zone_charge, "polygon"),
                        (self.act_hauteur, "contour"), (self.act_info, "wand"),
                        (self.act_trait, "target")):
            a.setIcon(theme.icon(name))
        for panneau in (getattr(self, "hud", None),
                        getattr(self, "layers_panel", None)):
            if panneau is not None:
                panneau.restyle()
        if self.wizard is not None:
            self.wizard.restyle()
        self.refresh_all()

    def zoom_fit(self):
        if self.profile_scene.pixmap_item is not None:
            self.profile_view.fitInView(self.profile_scene.pixmap_item,
                                        Qt.AspectRatioMode.KeepAspectRatio)
        if self.deck_scene.pixmap_item is not None:
            self.deck_view.fitInView(self.deck_scene.pixmap_item,
                                     Qt.AspectRatioMode.KeepAspectRatio)
        self.iso_view.fit()

    def about(self):
        QMessageBox.information(
            self, "À propos de Carène",
            "<b>Carène</b> — création du fichier navire<br>"
            "pour le logiciel de chargement et stabilité.<br><br>"
            "Les plans importés (image ou PDF) servent au repérage et à la "
            "saisie ; les volumes et centres proviennent toujours des tables "
            "de jauge du dossier de stabilité approuvé.<br><br>"
            "<b>F1</b> ouvre l'assistant guidé.")

    def showEvent(self, event):
        """Premier affichage : cadrer les vues une fois la mise en page connue."""
        super().showEvent(event)
        if not getattr(self, "_first_shown", False):
            self._first_shown = True
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, self.zoom_fit)
        self.deck_view.refresh_overlays()
        self.profile_view.refresh_overlays()

    # ------------------------------------------------------------ touche Échap
    def echap(self):
        """ÉCHAP DANS L'ÉDITEUR : annuler, puis revenir à la sélection.

        « Dans l'édition de plan, la touche Échap n'a pas un fonctionnement
        fiable. » Elle était bien traitée — mais par `keyPressEvent` de la
        FENÊTRE, c'est-à-dire seulement quand personne d'autre n'en avait
        voulu en chemin : un tableau, une liste, une case à cocher de la
        colonne de droite l'avalaient sans rien en faire, et la touche
        n'arrivait jamais. Le filtre posé sur l'application (`eventFilter`)
        l'apporte ici quoi qu'il arrive ; cette méthode dit ce qu'elle fait.

        Dans l'ordre, et d'un seul coup : le glisser en cours est défait, le
        tracé commencé est abandonné, le mode revient à SÉLECTION. S'il n'y
        avait rien de tout cela — on était déjà au repos —, la seconde frappe
        désélectionne.

        Rend `True` si quelque chose a été fait : la touche n'est consommée
        que dans ce cas."""
        if self._drag is not None:
            self._annuler_drag()
            self.statusBar().showMessage("Déplacement annulé.", 4000)
            return True
        agi = bool(self._poly_points) or self._rect_start is not None \
            or self._rect_glisser
        self._cancel_poly()
        self._cancel_rect()
        self._clic_trace = None
        if self.mode != MODE_SELECT:
            self._set_mode(MODE_SELECT)
            return True
        if agi:
            self.statusBar().showMessage("Tracé abandonné — mode sélection.", 4000)
            return True
        # déjà au repos : la seconde frappe lâche ce qui est choisi
        if self._selected_capacity is not None or self._selected_epontille is not None \
                or self._selected_calque is not None or self._selected_vertex is not None:
            self.select_capacity(None)
            self.props.setCurrentIndex(0)
            self.refresh_all()
            self.statusBar().showMessage("Sélection lâchée.", 4000)
            return True
        return False

    def eventFilter(self, obj, event):
        """Le filet Échap de l'éditeur, posé sur l'APPLICATION.

        Mêmes garde-fous que dans la vue Chargement, et pour la même raison :
        une fenêtre modale, une liste déroulante ouverte ou un champ de texte
        en cours de frappe gardent leur touche ; tout le reste la cède à
        l'éditeur. La fenêtre ACTIVE doit être celle-ci : deux éditeurs ou
        l'éditeur et la fenêtre principale ne se volent pas le clavier."""
        if event.type() == QEvent.Type.KeyPress \
                and event.key() == Qt.Key.Key_Escape \
                and _echap_pour_moi(self):
            if self.echap():
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.echap()
        elif event.key() == Qt.Key.Key_Backspace \
                and (self.mode in MODES_POLYGONE or self.mode == MODE_INFO):
            self.remove_last_poly_point()
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self.mode == MODE_SELECT:
                # l'ordre est celui du plus PRÉCIS au plus gros : une zone de
                # calque choisie ne doit pas emporter la cale qui la porte
                if self._selected_calque is not None:
                    self.delete_selected_calque()
                elif self._selected_epontille is not None:
                    self.delete_selected_epontille()
                elif self._selected_vertex is not None and self._selected_item() is not None:
                    self.delete_selected_vertex()
                else:
                    self.delete_selected_capacity()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.mode in MODES_POLYGONE or self.mode == MODE_INFO:
                self.finish_polygon()
        else:
            super().keyPressEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Carène")
    theme.apply_theme(app, "light")
    win = PlanEditorWindow()
    win.show()
    win.open_wizard()
    sys.exit(app.exec())
