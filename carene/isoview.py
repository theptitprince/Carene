# -*- coding: utf-8 -*-
"""Vue isométrique : ponts en plaques translucides, capacités extrudées."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPolygonItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QStyle,
)

from . import theme
from .core.cargo_model import couleur_hex
from .core.stowage import rect_epontille
from .geometry import iso_project, polygon_centroid

# Angle de rotation autour de la verticale, partagé par tous les items d'une
# scène. Une liste plutôt qu'un flottant : `_poly` est une fonction libre,
# appelée de partout, et doit lire la valeur du moment.
ANGLE = [0.0]
from .project import KIND_CONTOUR

SCALE = 10.0
# couleurs lues dans `theme` au moment du dessin


def _vivant(item):
    """L'objet graphique existe-t-il encore côté C++ ?

    Une scène qui se reconstruit détruit ses objets ; la liste Python qui les
    tient encore ne le sait pas, et le moindre appel sur l'un d'eux tombe en
    RuntimeError (« Internal C++ object (IsoCapacityItem) already deleted »,
    remonté du bord le 11/09). On demande à shiboken avant de toucher.

    Le même garde-fou existe dans `plan_editor` ; il n'est pas importé d'ici,
    c'est `plan_editor` qui importe `isoview` et non l'inverse."""
    try:
        import shiboken6
        return shiboken6.isValid(item)
    except Exception:
        return item is not None


def _poly(points3d):
    poly = QPolygonF()
    for x, y, z in points3d:
        u, v = iso_project(x, y, z, SCALE, ANGLE[0])
        poly.append(QPointF(u, v))
    return poly


class IsoCapacityItem(QGraphicsPolygonItem):
    """Face supérieure d'une capacité en iso — sert aussi de zone cliquable.

    `ratio` (0..1) teinte la face selon le taux de chargement : c'est ce qui
    permet de lire l'état du navire d'un coup d'œil dans la vue de chargement.
    """

    def __init__(self, capacity, ratio=None, parent=None, contour_seul=False,
                 estompe=False, couleur=None, pont=""):
        super().__init__(parent)
        self.capacity = capacity
        self.ratio = ratio
        self.estompe = estompe
        self.couleur = couleur
        self.pont = pont or ""
        # le plancher : c'est LUI qu'on éclaire au survol. Le plafond ne dit
        # rien de la place disponible ; le plancher, c'est la surface qu'on
        # va garnir.
        self.plancher = _poly([(x, y, capacity.z_min) for x, y in capacity.points])
        # `contour_seul` : la cale montre son chargement réel à l'intérieur ;
        # on ne peut pas la coiffer d'une face pleine sans le masquer. La face
        # reste là — c'est elle qu'on clique — mais elle n'est plus peinte.
        self.contour_seul = contour_seul
        self.survole = False
        # choisie dans un tableau (D-87) : tout son volume s'allume, pas
        # seulement le trait de sa face du dessus
        self.choisi = False
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setPolygon(_poly([(x, y, capacity.z_max) for x, y in capacity.points]))
        # Le pont n'est plus écrit sur le dessin (les étiquettes se
        # recouvraient) : il est dans l'infobulle, avec la cote. Le code de la
        # capacité, lui, reste peint — c'est ce qu'on cherche du regard.
        lignes = [f"{capacity.code}"
                  + (f" — {capacity.name}" if getattr(capacity, "name", "")
                     and capacity.name != capacity.code else "")]
        if self.pont:
            lignes.append(f"{self.pont} · Z = {capacity.z_min:g} à "
                          f"{capacity.z_max:g} m sur quille")
        if ratio is not None:
            self.setAcceptHoverEvents(True)
            lignes.append(f"{ratio * 100:.0f} % chargé")
            lignes.append("Double-cliquez pour charger cette cale.")
        self.setToolTip("\n".join(lignes))

    # le survol éclaire le VOLUME de la cale, pas seulement sa face : on veut
    # voir quel pont on s'apprête à choisir avant de double-cliquer
    def hoverEnterEvent(self, event):
        self._allumer(True)
        return super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._allumer(False)
        return super().hoverLeaveEvent(event)

    def _allumer(self, actif):
        for it in self.scene().items() if self.scene() else []:
            if getattr(it, "capacity", None) is self.capacity:
                it.survole = actif
                it.update()

    def _brush(self):
        if self.contour_seul:
            return QBrush(Qt.BrushStyle.NoBrush)
        if self.ratio is None:
            return QBrush(QColor(theme.ISO_TOP))
        base = QColor(theme.ISO_TOP)
        # la teinte de la nature quand elle est donnée : le remplissage se lit
        # alors « du vide vers la couleur du produit »
        acc = QColor(self.couleur) if self.couleur else QColor(theme.ACCENT)
        r = max(0.0, min(1.0, self.ratio))
        col = QColor(
            int(base.red() + (acc.red() - base.red()) * r),
            int(base.green() + (acc.green() - base.green()) * r),
            int(base.blue() + (acc.blue() - base.blue()) * r),
            int(70 + 150 * r))
        return QBrush(col)

    def paint(self, painter, option, widget=None):
        option.state &= ~QStyle.StateFlag.State_Selected
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        sel = self.isSelected() or self.choisi
        if sel and not self.survole:
            # LA SURBRILLANCE (D-87) : le plancher et le dessus teintés de la
            # couleur de sélection, un trait épais, jamais estompée
            fond = QColor(theme.CAP_SEL)
            fond.setAlpha(140)
            painter.setBrush(QBrush(fond))
            trait = QPen(QColor(theme.CAP_SEL), 2.5)
            trait.setCosmetic(True)
            painter.setPen(trait)
            painter.drawPolygon(self.plancher)
            dessus = QColor(theme.CAP_SEL)
            dessus.setAlpha(90 if not self.contour_seul else 0)
            painter.setBrush(QBrush(dessus))
            painter.drawPolygon(self.polygon())
            return
        couleur = (theme.CAP_SEL if sel else
                   (theme.ACCENT if self.survole else theme.ISO_EDGE))
        # QColor(...) explicite : une couleur du thème est une chaîne « #rrggbb »,
        # et `QPen(str, float)` n'existe pas — la vue iso le criait à chaque
        # repeint sur le poste du bord (et ne dessinait plus ses contours)
        pen = QPen(QColor(couleur), 2.0 if (sel or self.survole) else 1.0)
        pen.setCosmetic(True)
        painter.setPen(pen)
        brosse = self._brush()
        if self.survole and not self.contour_seul:
            c = QColor(theme.ACCENT)
            c.setAlpha(70)
            brosse = QBrush(c)
        if self.estompe and not self.survole:
            painter.setOpacity(0.42)
        if self.survole:
            # le plancher, bien visible, sous le reste du dessin
            c = QColor(theme.ACCENT)
            c.setAlpha(120)
            painter.setBrush(QBrush(c))
            painter.setPen(QPen(QColor(theme.ACCENT_DARK), 2.0))
            painter.drawPolygon(self.plancher)
            painter.setPen(pen)
        painter.setBrush(brosse)
        painter.drawPolygon(self.polygon())


class IsoFaceItem(QGraphicsPolygonItem):
    """Une face latérale de cale. Elle porte sa capacité pour s'allumer avec
    elle au survol : on veut voir tout le VOLUME, pas seulement le dessus."""

    def __init__(self, capacity, polygone, parent=None, estompe=False,
                 couleur=None):
        super().__init__(polygone, parent)
        self.capacity = capacity
        self.survole = False
        self.choisi = False
        self.estompe = estompe
        self.couleur = couleur
        self.setBrush(QBrush(QColor(theme.ISO_SIDE)))

    def paint(self, painter, option, widget=None):
        if self.choisi and not self.survole:
            c = QColor(theme.CAP_SEL)
            c.setAlpha(95)
            self.setBrush(QBrush(c))
            return super().paint(painter, option, widget)
        if self.survole:
            c = QColor(theme.ACCENT)
            c.setAlpha(60)
            self.setBrush(QBrush(c))
        else:
            if self.couleur:
                c = QColor(self.couleur)
                c.setAlpha(46)
            else:
                c = QColor(theme.ISO_SIDE)
            if self.estompe:
                c.setAlpha(max(12, c.alpha() // 3))
            self.setBrush(QBrush(c))
        if self.estompe and not self.survole:
            painter.setOpacity(0.42)
        return super().paint(painter, option, widget)


class IsoBoiteItem(QGraphicsPolygonItem):
    """Une face d'une capacité SCHÉMATIQUE (reconstituée depuis les tables,
    pas tracée sur plan). Elle porte sa boîte pour qu'on puisse la choisir et
    l'allumer comme une capacité tracée (D-87)."""

    def __init__(self, boite, polygone, parent=None):
        super().__init__(polygone, parent)
        self.boite = boite
        self.choisi = False

    def paint(self, painter, option, widget=None):
        if self.choisi:
            brosse, trait = self.brush(), self.pen()
            c = QColor(theme.CAP_SEL)
            c.setAlpha(110)
            p = QPen(QColor(theme.CAP_SEL), 2.5)
            p.setCosmetic(True)
            self.setBrush(QBrush(c))
            self.setPen(p)
            super().paint(painter, option, widget)
            self.setBrush(brosse)
            self.setPen(trait)
            return None
        return super().paint(painter, option, widget)


def _cle_de(objet):
    """Ce qui désigne une capacité d'un tableau à l'autre : son code, son
    nom, ou le nom d'une boîte schématique."""
    return {str(v) for v in (getattr(objet, "code", None), getattr(objet, "name", None),
                             getattr(objet, "nom", None)) if v}


class IsoView(QGraphicsView):
    """Vue isométrique reconstruite depuis le modèle (aucune édition ici).

    En mode chargement (`load_ratio` fourni à `rebuild`), elle sert aussi de
    **sélecteur de cale** :

    - survoler une cale l'allume en entier (dessus et flancs) ;
    - un simple clic la choisit — `capacity_clicked` — ce qui, dans la vue de
      chargement, amène le plan sur son pont ;
    - un double-clic zoome dessus — `capacity_activated`.

    Les cales qui ne sont pas sur le pont affiché sont estompées : on voit
    ainsi où l'on travaille sans avoir à lire les étiquettes.

    Comment on la manœuvre
    ----------------------

    - **molette** : zoom, centré sur le curseur ;
    - **glisser au bouton gauche** : tourne le navire autour de la verticale —
      n'importe où, y compris SUR une cale. C'est le geste le plus courant, et
      l'exiger « dans le vide » revenait à l'interdire dans la vue de
      chargement, où les cales couvrent presque tout le cadre ;
    - **clic** (appuyer et relâcher sans bouger) sur une cale : la choisit ;
      **double-clic** : l'active. Le partage se fait au relâchement, sur un
      seuil de quelques pixels — on ne peut plus choisir une cale par mégarde
      en tournant, ni manquer une rotation parce qu'on a visé une cale ;
    - **glisser au bouton du milieu**, ou **Espace + glisser** : déplace la vue
      (translation). Sans elle, un navire zoomé ne se visitait pas ;
    - **Recadrer** (`fit()`) : remet le cadrage et le zoom d'origine, **sans**
      toucher à l'angle — on ne perd pas l'orientation qu'on vient de choisir.
    """

    capacity_activated = Signal(object)
    capacity_clicked = Signal(object)
    capacity_hovered = Signal(object)

    # au-delà de ce déplacement, l'appui du bouton gauche est une rotation et
    # non plus un clic
    SEUIL_GLISSE = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.scene().setBackgroundBrush(QBrush(QColor(theme.BG_DEEP)))
        self.setRenderHints(QPainter.RenderHint.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        # Les barres de défilement servent au déplacement (elles portent la
        # translation de la vue) mais ne se montrent pas : elles mangeraient
        # deux bandes d'un cadre déjà étroit.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._cap_items = []
        self._survol = None
        self._rotation = None
        self._deplacement = None      # (x, y) du dernier point, en pixels vue
        self._appui = None            # (x, y, capacité) de l'appui gauche
        self._espace = False          # Espace maintenu : glisser = déplacer
        self._cadre = None            # le rectangle du DESSIN (hors marge)
        self._origine = None          # défilement au dernier recadrage
        self._touche = False          # l'utilisateur a-t-il zoomé ou déplacé ?
        self.angle = 0.0
        self._dernier_rebuild = None
        self.setMouseTracking(True)
        # comment on la manœuvre, écrit une fois pour toutes : c'est la même
        # convention que l'éditeur de plans (molette = zoom, milieu = déplacer)
        self.setToolTip(
            "Molette : zoom au curseur\n"
            "Glisser : tourner le navire\n"
            "Bouton du milieu, ou Espace + glisser : déplacer la vue\n"
            "Recadrer (F) : remettre le cadrage, sans changer l'angle")

    def set_angle(self, angle):
        """Tourne la vue autour de la verticale et la redessine."""
        self.angle = float(angle) % 360.0
        if self._dernier_rebuild is not None:
            args, kwargs = self._dernier_rebuild
            self.rebuild(*args, **kwargs)

    def wheelEvent(self, event):
        f = 1.25 if event.angleDelta().y() > 0 else 0.8
        self._touche = True
        self.scale(f, f)

    def resizeEvent(self, event):
        """Tant que personne n'a zoomé ni déplacé, la vue se recadre seule.

        Le premier `fit()` a lieu avant que la fenêtre soit disposée : le
        cadrage y est fait sur une taille qui n'est pas encore la bonne. On le
        refait donc à chaque changement de taille — mais **plus du tout** dès
        que l'utilisateur a pris la main, sinon un simple redimensionnement de
        la fenêtre annulerait son zoom."""
        super().resizeEvent(event)
        if not self._touche:
            self.fit()

    # ------------------------------------------------------------ déplacement
    def deplacer_de(self, dx, dy):
        """Fait glisser la vue de (dx, dy) pixels — le dessin suit la souris."""
        self._touche = True
        h, v = self.horizontalScrollBar(), self.verticalScrollBar()
        h.setValue(h.value() - int(round(dx)))
        v.setValue(v.value() - int(round(dy)))

    @property
    def decalage(self):
        """La translation courante en pixels, comptée depuis le recadrage.

        (0, 0) juste après `fit()` ; c'est ce que « Recadrer » remet à zéro."""
        h0, v0 = self._origine or (0, 0)
        return (self.horizontalScrollBar().value() - h0,
                self.verticalScrollBar().value() - v0)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self._espace = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        return super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self._espace = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        return super().keyReleaseEvent(event)

    # ------------------------------------------------------------ souris
    def mousePressEvent(self, event):
        pos = event.position()
        b = event.button()
        if b == Qt.MouseButton.MiddleButton or (
                b == Qt.MouseButton.LeftButton and self._espace):
            self._deplacement = (pos.x(), pos.y())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if b == Qt.MouseButton.LeftButton:
            # On ne tranche pas ici entre « choisir une cale » et « tourner » :
            # c'est le mouvement qui le dira. Émettre le choix dès l'appui,
            # comme avant, rendait la rotation impossible partout où une cale
            # est dessinée — c'est-à-dire dans presque toute la vue de
            # chargement.
            self._appui = (pos.x(), pos.y(), self.capacity_at(pos.toPoint()))
            self._rotation = None
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._deplacement is not None:
            self._deplacement = None
            self.setCursor(Qt.CursorShape.OpenHandCursor if self._espace
                           else Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        if self._appui is not None:
            _x, _y, cap = self._appui
            tourne = self._rotation is not None
            self._appui = None
            self._rotation = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            if not tourne and cap is not None:
                self.capacity_clicked.emit(cap)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        cap = self.capacity_at(event.position().toPoint())
        if cap is not None:
            self._appui = None
            self.capacity_activated.emit(cap)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._deplacement is not None:
            self.deplacer_de(pos.x() - self._deplacement[0],
                             pos.y() - self._deplacement[1])
            self._deplacement = (pos.x(), pos.y())
            event.accept()
            return
        if self._appui is not None and self._rotation is None:
            dx = pos.x() - self._appui[0]
            dy = pos.y() - self._appui[1]
            if abs(dx) >= self.SEUIL_GLISSE or abs(dy) >= self.SEUIL_GLISSE:
                self._rotation = (self._appui[0], self.angle)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
        if self._rotation is not None:
            depart_x, depart_angle = self._rotation
            # un demi-tour pour ~360 px : assez rapide pour faire le tour du
            # navire d'un geste, assez lent pour viser une cale
            self.set_angle(depart_angle + (pos.x() - depart_x) * 0.5)
            event.accept()
            return
        cap = self.capacity_at(pos.toPoint())
        if cap is not getattr(self, "_survol", None):
            self._survol = cap
            self.capacity_hovered.emit(cap)
        self.setCursor(Qt.CursorShape.OpenHandCursor if self._espace
                       else (Qt.CursorShape.PointingHandCursor if cap is not None
                             else Qt.CursorShape.ArrowCursor))
        return super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if getattr(self, "_survol", None) is not None:
            self._survol = None
            self.capacity_hovered.emit(None)
        return super().leaveEvent(event)

    # les boîtes schématiques se cliquent là où on le demande (vue des
    # capacités, D-87) ; ailleurs, seul ce qui est tracé se choisit
    boites_choisissables = False

    def capacity_at(self, view_pos):
        """Capacité sous ce point de la vue, ou None — une boîte schématique
        (`BoiteCapacite`) si la vue les rend choisissables."""
        for it in self.items(view_pos):
            cap = getattr(it, "capacity", None)
            if cap is not None:
                return cap
            if self.boites_choisissables and getattr(it, "boite", None) is not None:
                return it.boite
        return None

    # ------------------------------------------------------------------ rendu
    def rebuild(self, project, load_ratio=None, coque=None, boites=None,
                filtre=None, charges=None, en_avant=None, couleur=None,
                couleur_charge=None, epontilles=None):
        """`load_ratio` : fonction capacité -> taux 0..1, ou None pour le rendu
        neutre (contrôle de calage).

        `coque` / `boites` : silhouette et capacités **schématiques**,
        reconstituées depuis les tables du navire (voir `carene.core.coque`).
        Elles ne sont dessinées que là où rien n'a été tracé sur plan : dès
        qu'un vrai contour existe, c'est lui qui prime.

        `filtre` : prédicat capacité -> bool. Les capacités qu'il écarte ne
        sont pas dessinées du tout. C'est ce qui permet à la vue des capacités
        de ne montrer que les capacités liquides, et à la vue de chargement de
        ne montrer que les cales : sur un plan, les deux sont tracées côte à
        côte, et les mélanger rend la vue illisible.

        `couleur` : fonction capacité -> couleur, ou None. Elle sert à teinter
        les capacités par nature (eau douce, combustible, ballast…) : sur trente
        capacités, la couleur dit d'un coup d'œil ce qu'on regarde.

        `en_avant` : ensemble de codes de cale à laisser en pleine lumière ;
        les autres sont estompées. C'est ainsi que la vue de chargement montre
        le pont sur lequel on travaille.

        `charges` : dict `code de cale -> [Placement]`. Quand il est fourni, le
        remplissage d'une cale n'est plus un plan de liquide (qui mentirait sur
        ce qu'il y a dedans) mais les colis eux-mêmes, extrudés à leur hauteur
        réelle. `couleur_charge` : fonction Placement -> couleur hexa, pour
        suivre le mode de couleur du plan (lot, port, catégorie).

        `epontilles` : les identifiants des épontilles amovibles EN PLACE à ce
        point (None : on n'en dessine aucune). Une épontille en place est un
        montant du plancher au barrot : la vue navire la montre comme telle,
        et la déposer la fait disparaître — l'iso dit l'état du point, pas
        celui du plan du chantier (D-30)."""
        self._dernier_rebuild = ((project,), dict(
            load_ratio=load_ratio, coque=coque, boites=boites, filtre=filtre,
            charges=charges, en_avant=en_avant, couleur=couleur,
            couleur_charge=couleur_charge, epontilles=epontilles))
        # L'angle courant est REAPPLIQUÉ à chaque reconstruction, d'où qu'elle
        # vienne : la vue de chargement appelle `rebuild` directement à chaque
        # rafraîchissement (pose d'un colis, changement de pont), et la vue
        # doit se retrouver telle qu'on l'avait tournée. Et on ne recadre pas
        # ici : recadrer à chaque rebuild annulait zoom et déplacement.
        ANGLE[0] = self.angle
        sc = self.scene()
        # Les items retenus sont OUBLIÉS AVANT `clear()`, et la scène se tait
        # pendant qu'elle se vide : détruire un item sélectionné émet
        # selectionChanged au milieu de la destruction, et l'éditeur de plans
        # (`on_iso_selection` → `select_capacity`) repassait alors sur
        # `_cap_items` — des items déjà détruits côté C++ (« Internal C++
        # object (IsoCapacityItem) already deleted », journal du bord du
        # 11/09). Même précaution que `PlanScene.load`.
        self._cap_items = []
        self._survol = None
        sc.blockSignals(True)
        try:
            sc.clear()
        finally:
            sc.blockSignals(False)
        font = QFont()
        font.setPointSizeF(8.0)
        self._draw_coque(sc, coque, boites, font, couleur)
        if project is None or not project.decks:
            self._cadrer(sc)
            return

        for deck in project.sorted_decks():
            # plaque du pont : contour tracé s'il existe, sinon enveloppe des capacités
            contour = next((c for c in deck.capacities
                            if c.kind == KIND_CONTOUR and len(c.points) >= 3), None)
            plate_pts = contour.points if contour else None
            if plate_pts is None and coque is not None:
                # aucun contour tracé : on pose la plaque sur la silhouette
                plate_pts = coque.contour_au_niveau(deck.z) or None
            if plate_pts:
                plate = QGraphicsPolygonItem(
                    _poly([(x, y, deck.z) for x, y in plate_pts]))
                plate.setBrush(QBrush(QColor(theme.ISO_PLATE)))
                pen = QPen(QColor(theme.ISO_PLATE_EDGE), 1.0)
                pen.setCosmetic(True)
                plate.setPen(pen)
                # Le nom du pont est dans l'INFOBULLE, plus sur le dessin :
                # « Pont supérieur Z=6.21 » écrit à côté de chaque plaque, ce
                # sont trois pavés de texte qui se recouvrent au moindre quart
                # de tour, pour une information que le tableau voisin donne
                # déjà. Le cadre reste propre ; les codes de capacité, eux,
                # restent peints — c'est ce qu'on cherche du regard.
                plate.setToolTip(f"{deck.name} — Z = {deck.z:g} m sur quille")
                plate.setAcceptHoverEvents(False)
                # la plaque du pont passe DERRIÈRE les capacités schématiques,
                # sinon elle les masquait entièrement
                plate.setZValue(-20)
                sc.addItem(plate)

            # capacités extrudées
            for cap in deck.capacities:
                if cap.kind == KIND_CONTOUR or len(cap.points) < 3:
                    continue
                if filtre is not None and not filtre(cap):
                    continue
                pts = list(cap.points)
                n = len(pts)
                estompee = en_avant is not None and cap.code not in en_avant
                teinte = None if couleur is None else couleur(cap)
                edge_pen = QPen(QColor(theme.ISO_EDGE), 1.0)
                edge_pen.setCosmetic(True)
                # faces latérales
                for i in range(n):
                    a, b = pts[i], pts[(i + 1) % n]
                    quad = _poly([(a[0], a[1], cap.z_min), (b[0], b[1], cap.z_min),
                                  (b[0], b[1], cap.z_max), (a[0], a[1], cap.z_max)])
                    side = IsoFaceItem(cap, quad, estompe=estompee,
                                       couleur=teinte)
                    side.setPen(edge_pen)
                    sc.addItem(side)
                ratio = None if load_ratio is None else load_ratio(cap)
                poses = (charges or {}).get(cap.code) or []
                if charges is not None and en_avant is not None and not estompee:
                    # le plancher de la cale sur laquelle on travaille est
                    # peint presque opaque : il cache ce qui est posé sur le
                    # pont du dessous, qui se projette exactement au même
                    # endroit et se lisait comme « dans » cette cale
                    sol = QGraphicsPolygonItem(
                        _poly([(x, y, cap.z_min) for x, y in pts]))
                    fond = QColor(theme.SURFACE)
                    fond.setAlpha(235)
                    sol.setBrush(QBrush(fond))
                    sol.setPen(edge_pen)
                    sc.addItem(sol)
                # illustration du chargement : les colis réellement posés
                colis_dessines = self._draw_colis(
                    sc, poses, cap.z_min, cap.z_max, edge_pen,
                    estompe=estompee, couleur_de=couleur_charge)
                if not colis_dessines:
                    # niveau de remplissage (plan du liquide, ou hauteur chargée)
                    level = cap.fill if load_ratio is None else (ratio or 0.0)
                    if level > 0:
                        zl = cap.z_min + level * (cap.z_max - cap.z_min)
                        liq = QGraphicsPolygonItem(
                            _poly([(x, y, zl) for x, y in pts]))
                        liq.setBrush(QBrush(QColor(theme.ISO_LIQ)))
                        liq.setPen(QPen(Qt.PenStyle.NoPen))
                        sc.addItem(liq)
                if epontilles is not None:
                    self._draw_epontilles(sc, cap, epontilles, edge_pen,
                                          estompe=estompee)
                # face supérieure (cliquable)
                top = IsoCapacityItem(cap, ratio, contour_seul=colis_dessines,
                                      estompe=estompee, couleur=teinte,
                                      pont=deck.name)
                sc.addItem(top)
                self._cap_items.append(top)
                cx, cy = polygon_centroid(pts)
                u, v = iso_project(cx, cy, cap.z_max, SCALE, ANGLE[0])
                t = QGraphicsSimpleTextItem(cap.code)
                t.setFont(font)
                t.setBrush(QBrush(QColor(theme.TEXT)))
                t.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
                tr = t.boundingRect()
                t.setPos(u - tr.width() / 2, v - tr.height() / 2)
                sc.addItem(t)

        self._cadrer(sc)
        # la capacité choisie le reste d'une reconstruction à l'autre (D-87) :
        # le relevé d'une sonde recalcule tout, la surbrillance ne doit pas
        # s'éteindre sous les doigts de celui qui saisit
        code = getattr(self, "_code_choisi", None)
        if code:
            self.choisir(code)

    def _cadrer(self, sc):
        """Fixe le rectangle de scène, et retient le cadre du DESSIN.

        Deux rectangles, pas un : celui du dessin (ce que « Recadrer » remet
        dans la fenêtre) et celui de la scène, volontairement beaucoup plus
        large. Une vue graphique ne peut se déplacer hors de sa scène : sans
        cette marge, le glissement au bouton du milieu ne bougeait de rien dès
        que le navire tenait entier dans le cadre."""
        # cadre minimal : évite un zoom absurde tant que le navire est presque vide
        rect = sc.itemsBoundingRect().adjusted(-40, -40, 40, 40)
        if rect.width() < 400:
            rect.adjust(-(400 - rect.width()) / 2, 0, (400 - rect.width()) / 2, 0)
        if rect.height() < 260:
            rect.adjust(0, -(260 - rect.height()) / 2, 0, (260 - rect.height()) / 2)
        self._cadre = QRectF(rect)
        marge_x = max(rect.width(), 800.0)
        marge_y = max(rect.height(), 600.0)
        sc.setSceneRect(rect.adjusted(-marge_x, -marge_y, marge_x, marge_y))

    def _draw_coque(self, sc, coque, boites, font, couleur=None):
        """Silhouette et capacités schématiques, en trait fin et sans remplissage
        appuyé : elles situent, elles ne prétendent pas décrire la coque.

        Les BOÎTES de capacités se dessinent même sans silhouette : quand un
        plan est calé, la coque schématique s'efface mais les soutes et
        ballasts non tracés doivent rester visibles."""
        pen = QPen(QColor(theme.ISO_PLATE_EDGE), 1.0)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.DashLine)
        self._draw_boites(sc, boites, pen, couleur)
        if coque is None or not coque.lignes:
            return
        for i, ligne in enumerate(coque.lignes):
            if not ligne.points:
                continue
            # une ligne d'eau sur trois suffit à donner la forme
            if i % 3 and ligne is not coque.lignes[-1]:
                continue
            item = QGraphicsPolygonItem(
                _poly([(x, y, ligne.z_m) for x, y in ligne.points]))
            item.setPen(pen)
            item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            item.setZValue(-30)
            sc.addItem(item)
        # quelques génératrices verticales, pour lire le volume
        haute = coque.lignes[-1]
        basse = coque.lignes[0]
        n = min(len(haute.points), len(basse.points))
        montant = QPen(QColor(theme.ISO_PLATE_EDGE), 0.8)
        montant.setCosmetic(True)
        montant.setStyle(Qt.PenStyle.DotLine)
        for j in range(0, n, max(1, n // 10)):
            x, y = haute.points[j]
            xb, yb = basse.points[j]
            g = QGraphicsPolygonItem(_poly([(xb, yb, basse.z_m), (x, y, haute.z_m)]))
            g.setPen(montant)
            g.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            g.setZValue(-30)
            sc.addItem(g)


    # nombre de colis au-delà duquel on renonce à les dessiner un par un :
    # au-dessus, la vue devient une bouillie et le rendu traîne. On retombe
    # alors sur la teinte d'occupation, qui reste honnête.
    MAX_COLIS = 400

    def _draw_colis(self, sc, poses, z_plancher, z_plafond, edge_pen,
                    estompe=False, couleur_de=None):
        """Les colis d'une cale, extrudés à leur hauteur réelle.

        Les faces sont peintes du plus lointain au plus proche **dans la
        projection courante** (la profondeur d'écran, pas x + y : dès qu'on
        a tourné la vue, x + y ne dit plus qui est devant) ; sans cela, un
        colis de l'arrière se dessine par-dessus un colis de l'avant et
        l'empilement se lit à l'envers.

        `estompe` : la cale n'est pas sur le pont affiché. Ses colis sont
        alors peints en transparence : trois ponts de cales superposées se
        projettent au même endroit, et un colis du pont inférieur dessiné en
        pleine couleur paraissait posé dans la cale du dessus, au mauvais
        endroit."""
        if not poses or len(poses) > self.MAX_COLIS:
            return False

        def profondeur(p):
            x0, y0, x1, y1 = p.rect
            return iso_project((x0 + x1) / 2, (y0 + y1) / 2, 0.0, SCALE, ANGLE[0])[1]

        for pl in sorted(poses, key=profondeur):
            x0, y0, x1, y1 = pl.rect
            h = pl.hauteur_totale_m
            if h <= 0:
                continue
            zb = z_plancher
            zh = min(z_plancher + h, z_plafond) if z_plafond > z_plancher \
                else z_plancher + h
            col = QColor(couleur_de(pl) if couleur_de else couleur_hex(pl))
            att = 0.3 if estompe else 1.0
            pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
            # deux faces latérales suffisent (les deux autres sont cachées),
            # mais on les dessine toutes : une cale se regarde sous deux angles
            for k in range(4):
                a, b = pts[k], pts[(k + 1) % 4]
                side = QGraphicsPolygonItem(_poly(
                    [(a[0], a[1], zb), (b[0], b[1], zb),
                     (b[0], b[1], zh), (a[0], a[1], zh)]))
                ombre = QColor(col)
                ombre.setAlpha(int(150 * att))
                side.setBrush(QBrush(ombre))
                side.setPen(edge_pen)
                sc.addItem(side)
            dessus = QGraphicsPolygonItem(_poly([(x, y, zh) for x, y in pts]))
            clair = QColor(col)
            clair.setAlpha(int(215 * att))
            dessus.setBrush(QBrush(clair))
            dessus.setPen(edge_pen)
            n = max(1, pl.niveaux)
            dessus.setToolTip(
                f"{pl.nom} — {pl.poids_total_t:.2f} t"
                + (f" · {n} niveaux" if n > 1 else ""))
            sc.addItem(dessus)
        return True

    def _draw_epontilles(self, sc, cap, en_place, edge_pen, estompe=False):
        """Les épontilles amovibles de la cale, dressées du plancher au barrot.

        En place : un montant plein, qu'on voit passer entre les piles — c'est
        un mur, et il doit se voir en volume comme sur le plan. Déposée : le
        même montant en transparence, pour qu'on sache où elle irait sans
        croire qu'elle y est. Rien de cliquable : la bascule se fait sur le
        plan de pose, à plat, là où l'on travaille."""
        ids = set(en_place or ())
        n = 0
        for e in getattr(cap, "epontilles", []) or []:
            x0, y0, x1, y1 = rect_epontille(e)[:4]
            if x1 - x0 <= 0 or y1 - y0 <= 0:
                continue
            pose = e.get("id") in ids
            pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
            col = QColor(theme.DECK_LINE)
            att = 0.3 if estompe else 1.0
            for k in range(4):
                a, b = pts[k], pts[(k + 1) % 4]
                face = QGraphicsPolygonItem(_poly(
                    [(a[0], a[1], cap.z_min), (b[0], b[1], cap.z_min),
                     (b[0], b[1], cap.z_max), (a[0], a[1], cap.z_max)]))
                teinte = QColor(col)
                teinte.setAlpha(int((165 if pose else 45) * att))
                face.setBrush(QBrush(teinte))
                face.setPen(edge_pen)
                face.setToolTip(f"Épontille {e.get('nom') or e.get('id')} — "
                                + ("en place" if pose else "déposée"))
                sc.addItem(face)
            n += 1
        return n

    def items_de_capacite(self):
        """Les faces cliquables ENCORE VIVANTES — la liste est purgée au passage.

        `_cap_items` est une liste Python d'items C++ : une reconstruction de
        la scène (ou sa destruction à la fermeture) les détruit sans que la
        liste en sache rien. Tout ce qui parcourt `_cap_items` passe par ici,
        et jamais par la liste brute."""
        vivants = [it for it in self._cap_items if _vivant(it)]
        if len(vivants) != len(self._cap_items):
            self._cap_items = vivants
        return list(vivants)

    def select_capacity(self, capacity):
        """Éclaire la face de cette capacité, et elle seule.

        Deux précautions, toutes deux payées par un plantage à bord :
        on ne touche qu'aux items vivants, et on tolère un item SANS scène
        (`scene()` vaut None entre son retrait et sa destruction) — on fait
        alors taire la scène de la vue, pas celle de l'item."""
        self._allumer_choix(capacity)

    def choisir(self, code):
        """Allume la capacité de ce code ou de ce nom — tracée ou
        schématique (D-87). Rend True si elle est dans la vue."""
        code = str(code or "")
        for it in self.items_de_capacite():
            if code in _cle_de(it.capacity):
                self._allumer_choix(it.capacity)
                return True
        sc = self.scene()
        for it in (sc.items() if sc is not None and _vivant(sc) else []):
            b = getattr(it, "boite", None)
            if b is not None and code in _cle_de(b):
                self._allumer_choix(b)
                return True
        self._allumer_choix(None)
        self._code_choisi = code or None
        return False

    def _allumer_choix(self, capacity):
        # retenu pour la reconstruction suivante (`rebuild` → `choisir`)
        self._code_choisi = (None if capacity is None else
                             str(getattr(capacity, "code", None)
                                 or getattr(capacity, "nom", None)
                                 or getattr(capacity, "name", "")) or None)
        items = self.items_de_capacite()
        sc = self.scene()
        muette = sc is not None and _vivant(sc)
        bloque = sc.blockSignals(True) if muette else False
        try:
            for it in items:
                it.setSelected(capacity is not None and it.capacity is capacity)
                it.update()
            # LA SURBRILLANCE (D-87) : le dessus, le plancher et les faces
            # latérales de la capacité choisie, passés DEVANT le reste — une
            # soute au fond de la coque ne doit pas rester cachée derrière les
            # autres
            if sc is not None and _vivant(sc):
                for it in sc.items():
                    if not hasattr(it, "choisi") or not _vivant(it):
                        continue
                    porte = getattr(it, "capacity", None)
                    if porte is None:
                        porte = getattr(it, "boite", None)
                    choisi = capacity is not None and porte is capacity
                    if not hasattr(it, "_z_origine"):
                        it._z_origine = it.zValue()
                    it.choisi = choisi
                    it.setZValue(it._z_origine + (1000 if choisi else 0))
                    it.update()
        finally:
            if muette:
                sc.blockSignals(bloque)

    def fit(self):
        """« Recadrer » : remet le dessin entier dans la fenêtre.

        Le zoom et le déplacement repartent de zéro ; **l'angle ne bouge pas**
        — on vient de choisir sous quel angle on regarde le navire, ce n'est
        pas au recadrage de l'annuler. On cadre sur le rectangle du dessin, pas
        sur celui de la scène, qui porte la marge de déplacement."""
        if self.scene().items():
            cadre = self._cadre or self.scene().itemsBoundingRect()
            self.fitInView(cadre, Qt.AspectRatioMode.KeepAspectRatio)
            self._origine = (self.horizontalScrollBar().value(),
                             self.verticalScrollBar().value())
            self._touche = False

    def _draw_boites(self, sc, boites, pen, couleur=None):
        for b in (boites or []):
            pts = [(b.x0, b.y0), (b.x1, b.y0), (b.x1, b.y1), (b.x0, b.y1)]
            fill = max(0.0, min(1.0, getattr(b, "fill", 0.0)))
            # le liquide prend la teinte de sa nature (eau douce, gazole,
            # ballast…) quand on la connaît : trente boîtes bleues ne disent
            # rien, trente boîtes colorées se lisent comme le tableau
            liquide = QColor(theme.ISO_LIQ)
            teinte = couleur(b) if couleur is not None else None
            if teinte:
                liquide = QColor(teinte)
                liquide.setAlpha(150)
            z_liq = b.z_min + fill * (b.z_max - b.z_min)
            for k in range(4):
                a, c2 = pts[k], pts[(k + 1) % 4]
                # partie mouillée de la paroi, teintée liquide
                if fill > 0:
                    bas = QGraphicsPolygonItem(_poly(
                        [(a[0], a[1], b.z_min), (c2[0], c2[1], b.z_min),
                         (c2[0], c2[1], z_liq), (a[0], a[1], z_liq)]))
                    bas.setBrush(QBrush(liquide))
                    bas.setPen(QPen(Qt.PenStyle.NoPen))
                    bas.setZValue(-6)
                    sc.addItem(bas)
                quad = _poly([(a[0], a[1], b.z_min), (c2[0], c2[1], b.z_min),
                              (c2[0], c2[1], b.z_max), (a[0], a[1], b.z_max)])
                side = IsoBoiteItem(b, quad)
                side.setBrush(QBrush(Qt.BrushStyle.NoBrush) if fill > 0
                              else QBrush(QColor(theme.ISO_SIDE)))
                side.setPen(pen)
                side.setZValue(-5)
                sc.addItem(side)
            if fill > 0:
                # plan du liquide
                liq = QGraphicsPolygonItem(
                    _poly([(x, y, z_liq) for x, y in pts]))
                liq.setBrush(QBrush(liquide))
                liq.setPen(QPen(Qt.PenStyle.NoPen))
                liq.setZValue(-5)
                sc.addItem(liq)
            top = IsoBoiteItem(b, _poly([(x, y, b.z_max) for x, y in pts]))
            top.setBrush(QBrush(QColor(theme.ISO_PLATE)) if fill <= 0
                         else QBrush(Qt.BrushStyle.NoBrush))
            top.setPen(pen)
            top.setZValue(-5)
            top.setToolTip(f"{b.nom} — {b.volume_m3:.1f} m³"
                           + (f" · rempli à {100 * fill:.0f} %" if fill > 0
                              else "")
                           + f" · {b.approx}")
            sc.addItem(top)
        # Pas d'étiquette sur les capacités schématiques : une trentaine de
        # noms sur une silhouette de 80 m se recouvrent et ne se lisent plus.
        # Le nom est dans l'infobulle, et le tableau au-dessus les nomme toutes.
