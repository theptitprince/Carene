# -*- coding: utf-8 -*-
"""Objets graphiques : capacités (vue pont et profil), lignes de ponts, repères."""
from __future__ import annotations

import re

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
    QStyle,
)

from . import theme
from .project import KIND_CONTOUR

# Les couleurs sont lues dans `theme` au moment du dessin : un changement
# de thème se répercute donc sans reconstruire les objets.


def _label(parent, color=None, size=8.5):
    t = QGraphicsSimpleTextItem(parent)
    f = QFont()
    f.setPointSizeF(size)
    f.setBold(True)
    t.setFont(f)
    t.setBrush(QBrush(QColor(color or theme.TEXT)))
    return t


class VertexHandle(QGraphicsItem):
    """Poignée d'un sommet de polygone : carré de taille fixe à l'écran,
    quel que soit le zoom. Enfant du polygone sélectionné, créé avec lui et
    détruit avec sa désélection — on ne garde pas 150 poignées par contour
    quand rien n'est en cours d'édition."""

    SIZE = 4.5

    def __init__(self, index: int, parent, verrouille: bool = False):
        super().__init__(parent)
        self.index = index
        self.current = False
        self.verrouille = bool(verrouille)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setZValue(5)
        self.maj_infobulle()

    def maj_infobulle(self):
        self.setToolTip(
            f"Sommet n°{self.index + 1} — VERROUILLÉ : clic droit pour le "
            "libérer" if self.verrouille
            else f"Sommet n°{self.index + 1} — glisser pour déplacer, "
                 "Suppr pour retirer, clic droit pour le verrouiller")

    def set_verrouille(self, on: bool):
        self.verrouille = bool(on)
        self.maj_infobulle()
        self.update()

    def boundingRect(self):
        s = self.SIZE + 3
        return QRectF(-s, -s, 2 * s, 2 * s)

    def paint(self, painter, option, widget=None):
        s = self.SIZE
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        if self.verrouille:
            # un sommet figé se voit d'un coup d'œil : carré PLEIN et plus
            # gros. Il n'y a rien à y faire — inutile de le dessiner comme une
            # poignée qu'on pourrait saisir.
            s += 1.0
            painter.setPen(QPen(QColor(theme.CAP_SEL), 1.8))
            painter.setBrush(QBrush(QColor(theme.CAP_SEL)))
            painter.drawRect(QRectF(-s, -s, 2 * s, 2 * s))
            return
        painter.setPen(QPen(QColor(theme.CAP_SEL), 1.2))
        painter.setBrush(QBrush(QColor(theme.ACCENT if self.current
                                       else theme.MARKER_BG)))
        painter.drawRect(QRectF(-s, -s, 2 * s, 2 * s))


class SnapMarkerItem(QGraphicsItem):
    """Repère du point accroché : cercle et croix de taille fixe à l'écran."""

    R = 7

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setZValue(60)
        self.setVisible(False)

    def boundingRect(self):
        r = self.R + 2
        return QRectF(-r, -r, 2 * r, 2 * r)

    def paint(self, painter, option, widget=None):
        r = self.R
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(theme.ACCENT), 1.6)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(0, 0), r, r)
        painter.drawLine(QPointF(-r - 2, 0), QPointF(-r + 3, 0))
        painter.drawLine(QPointF(r - 3, 0), QPointF(r + 2, 0))
        painter.drawLine(QPointF(0, -r - 2), QPointF(0, -r + 3))
        painter.drawLine(QPointF(0, r - 3), QPointF(0, r + 2))


class DeckCapacityItem(QGraphicsPolygonItem):
    """Polygone d'une capacité (ou contour) sur la vue d'un pont (X-Y).

    Sélectionné, il montre une poignée par sommet ; l'édition (glisser un
    sommet, en insérer, en retirer, déplacer le tout) est pilotée par la
    fenêtre, qui seule connaît le zoom de la vue et les points d'accroche.

    **Z.** Toutes les cales d'un pont se dessinent au même niveau, et deux
    cales qui se superposent se rangeaient alors dans leur ordre de création :
    le remplissage de la dernière tracée passait par-dessus les poignées de
    l'autre, qui devenaient impossibles à saisir (retour du bord : « on ne
    peut plus sélectionner un sommet caché par la cale qui superpose »). La
    cale SÉLECTIONNÉE monte donc au-dessus des autres tant qu'elle l'est.
    """

    Z_NORMAL = 20
    Z_SELECTION = 24

    def __init__(self, capacity, calibration, parent=None):
        super().__init__(parent)
        self.capacity = capacity
        self.calibration = calibration
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.label = _label(self)
        self.handles = []
        self.current_vertex = None
        self.setZValue(self.Z_NORMAL)
        self.rebuild()

    def _texte_etiquette(self):
        cap = self.capacity
        if cap.kind == KIND_CONTOUR:
            return "🔒" if cap.verrouillee else ""
        # le cadenas est DANS l'étiquette : c'est le seul endroit du plan qui
        # suit la cale quand on la déplace ou qu'on zoome
        return ("🔒 " if cap.verrouillee else "") \
            + f"{cap.code}  {round(cap.fill * 100)}%"

    def rebuild(self):
        poly = QPolygonF()
        for a, b in self.capacity.points:
            u, v = self.calibration.to_pixel(a, b)
            poly.append(QPointF(u, v))
        self.set_pixel_polygon(poly)
        cap = self.capacity
        self.label.setText(self._texte_etiquette())
        self.label.setBrush(QBrush(QColor(theme.TEXT)))
        self.setToolTip((cap.name or cap.code)
                        + (" — VERROUILLÉE (clic droit pour déverrouiller)"
                           if cap.verrouillee else ""))

    def maj_remplissage(self):
        """Le taux de remplissage a changé, et rien d'autre.

        La peinture relit `capacity.fill` d'elle-même ; seule l'étiquette le
        recopie. Sert au curseur de remplissage, qui bougeait toute la fenêtre
        (arbre, tableaux, vue iso) à chaque cran."""
        self.label.setText(self._texte_etiquette())
        self.update()

    def set_pixel_polygon(self, poly: QPolygonF):
        """Polygone en pixels (pendant un glisser, avant d'écrire le modèle)."""
        self.setPolygon(poly)
        r = poly.boundingRect()
        lr = self.label.boundingRect()
        self.label.setPos(r.center().x() - lr.width() / 2,
                          r.center().y() - lr.height() / 2)
        self._place_handles()

    # ------------------------------------------------------------ poignées
    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            # la cale choisie passe au-dessus des autres : sinon celle qui la
            # recouvre masque ses poignées, et le bord ne peut plus les saisir
            self.setZValue(self.Z_SELECTION if value else self.Z_NORMAL)
            self._build_handles(bool(value))
        return super().itemChange(change, value)

    def _build_handles(self, on: bool):
        for h in self.handles:
            h.setParentItem(None)
            if self.scene() is not None:
                self.scene().removeItem(h)
        self.handles = []
        if on:
            for i in range(self.polygon().count()):
                self.handles.append(
                    VertexHandle(i, self, self.capacity.sommet_verrouille(i)))
            self._place_handles()
        else:
            self.current_vertex = None

    def _place_handles(self):
        poly = self.polygon()
        for h in self.handles:
            if h.index < poly.count():
                h.setPos(poly.at(h.index))
            h.current = (h.index == self.current_vertex)
            h.set_verrouille(self.capacity.sommet_verrouille(h.index))

    def set_current_vertex(self, index):
        self.current_vertex = index
        self._place_handles()

    def hit_vertex(self, scene_pos: QPointF, tol: float):
        """Indice du sommet à moins de `tol` pixels-scène, ou None."""
        poly = self.polygon()
        best, best_d = None, tol
        for i in range(poly.count()):
            p = poly.at(i)
            d = ((p.x() - scene_pos.x()) ** 2 + (p.y() - scene_pos.y()) ** 2) ** 0.5
            if d < best_d:
                best, best_d = i, d
        return best

    def hit_edge(self, scene_pos: QPointF, tol: float):
        """(indice de l'arête i→i+1, point projeté) si le curseur est à moins
        de `tol` d'une arête, sinon None."""
        poly = self.polygon()
        n = poly.count()
        best = None
        best_d = tol
        for i in range(n):
            a = poly.at(i)
            b = poly.at((i + 1) % n)
            dx, dy = b.x() - a.x(), b.y() - a.y()
            l2 = dx * dx + dy * dy
            if l2 <= 1e-12:
                continue
            t = ((scene_pos.x() - a.x()) * dx + (scene_pos.y() - a.y()) * dy) / l2
            t = max(0.0, min(1.0, t))
            px, py = a.x() + t * dx, a.y() + t * dy
            d = ((px - scene_pos.x()) ** 2 + (py - scene_pos.y()) ** 2) ** 0.5
            if d < best_d:
                best_d = d
                best = (i, QPointF(px, py))
        return best

    def paint(self, painter, option, widget=None):
        option.state &= ~QStyle.StateFlag.State_Selected
        poly = self.polygon()
        if poly.isEmpty():
            return
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        sel = self.isSelected()
        verrou = bool(self.capacity.verrouillee)
        if self.capacity.kind == KIND_CONTOUR:
            pen = QPen(QColor(theme.CAP_SEL if sel else theme.CONTOUR), 2.0)
            pen.setCosmetic(True)
            pen.setStyle(Qt.PenStyle.DashDotLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(poly)
            return
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(theme.CAP_BASE)))
        painter.drawPolygon(poly)
        if self.capacity.fill > 0:
            col = QColor(theme.CAP_FILL)
            col.setAlpha(int(30 + 140 * self.capacity.fill))
            painter.setBrush(QBrush(col))
            painter.drawPolygon(poly)
        pen = QPen(QColor(theme.CAP_SEL if sel else theme.CAP_EDGE), 2.6 if sel else 1.6)
        pen.setCosmetic(True)
        if verrou:
            # trait TIRETÉ et plus épais : on voit que la cale est figée sans
            # avoir à la sélectionner ni à lire l'arbre
            pen.setStyle(Qt.PenStyle.DashLine)
            pen.setWidthF(pen.widthF() + 0.8)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(poly)


class ProfileCapacityItem(QGraphicsRectItem):
    """Projection d'une capacité sur le profil : [Xmin..Xmax] x [Zmin..Zmax],
    remplie de bas en haut selon le taux de remplissage."""

    def __init__(self, capacity, calibration, parent=None):
        super().__init__(parent)
        self.capacity = capacity
        self.calibration = calibration
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.label = _label(self, size=8.0)
        self.rebuild()

    def rebuild(self):
        cap = self.capacity
        x0, x1 = cap.x_range
        u0, v0 = self.calibration.to_pixel(x0, cap.z_max)
        u1, v1 = self.calibration.to_pixel(x1, cap.z_min)
        rect = QRectF(QPointF(u0, v0), QPointF(u1, v1)).normalized()
        self.setRect(rect)
        self.label.setText(cap.code)
        self.label.setBrush(QBrush(QColor(theme.TEXT)))
        lr = self.label.boundingRect()
        self.label.setPos(rect.center().x() - lr.width() / 2,
                          rect.center().y() - lr.height() / 2)
        self.setToolTip(f"{cap.code} — Z {cap.z_min:g} à {cap.z_max:g} m")

    def paint(self, painter, option, widget=None):
        option.state &= ~QStyle.StateFlag.State_Selected
        rect = self.rect()
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(theme.CAP_BASE)))
        painter.drawRect(rect)
        f = self.capacity.fill
        if f > 0:
            h = rect.height() * f
            painter.setBrush(QBrush(QColor(theme.CAP_FILL)))
            painter.drawRect(QRectF(rect.left(), rect.bottom() - h,
                                    rect.width(), h))
        sel = self.isSelected()
        pen = QPen(QColor(theme.CAP_SEL if sel else theme.CAP_EDGE), 2.4 if sel else 1.2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)


class DeckLineItem(QGraphicsItem):
    """Ligne d'un pont sur le profil (horizontale à Z = deck.z), avec étiquette."""

    def __init__(self, deck, calibration, x_range, parent=None):
        super().__init__(parent)
        self.deck = deck
        self.calibration = calibration
        self.x_range = x_range
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setToolTip(f"{deck.name} — Z = {deck.z:g} m")
        self._compute()

    def _compute(self):
        x0, x1 = self.x_range
        z = self.deck.z
        self.p1 = self.calibration.to_pixel(x0, z)
        self.p2 = self.calibration.to_pixel(x1, z)

    def boundingRect(self):
        x0 = min(self.p1[0], self.p2[0])
        x1 = max(self.p1[0], self.p2[0])
        y0 = min(self.p1[1], self.p2[1])
        y1 = max(self.p1[1], self.p2[1])
        return QRectF(x0 - 5, y0 - 20, (x1 - x0) + 140, (y1 - y0) + 26)

    def paint(self, painter, option, widget=None):
        sel = self.isSelected()
        pen = QPen(QColor(theme.CAP_SEL if sel else theme.DECK_LINE), 2.2 if sel else 1.5)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        painter.drawLine(QPointF(*self.p1), QPointF(*self.p2))
        f = QFont()
        f.setPointSizeF(8.0)
        f.setBold(True)
        painter.setFont(f)
        painter.setPen(QPen(QColor(theme.CAP_SEL if sel else theme.DECK_LINE)))
        painter.drawText(QPointF(self.p1[0] + 7, self.p1[1] - 6),
                         f"{self.deck.name}  Z={self.deck.z:g}")

    def shape(self):
        from PySide6.QtGui import QPainterPath, QPainterPathStroker

        path = QPainterPath(QPointF(*self.p1))
        path.lineTo(QPointF(*self.p2))
        stroker = QPainterPathStroker()
        stroker.setWidth(8)
        return stroker.createStroke(path)


class CalMarkerItem(QGraphicsItem):
    """Repère d'un point de calage : croix, numéro et intitulé du point."""

    SIZE = 9

    def __init__(self, index: int, label: str = "", coords=None, parent=None):
        super().__init__(parent)
        self.index = index
        self.label = label or ""
        self.coords = coords
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        tip = f"Point de calage n°{index}"
        if self.label:
            tip += f" — {self.label}"
        if coords:
            tip += f"\n({coords[0]:g} ; {coords[1]:g}) m"
        self.setToolTip(tip)

    def _text(self):
        return f"{self.index}. {self.label}" if self.label else str(self.index)

    def _font(self):
        f = QFont()
        f.setPointSizeF(8.0)
        f.setBold(True)
        return f

    def boundingRect(self):
        s = self.SIZE
        w = QFontMetrics(self._font()).horizontalAdvance(self._text()) + 12
        return QRectF(-s - 3, -s - 20, s + w + 8, 2 * s + 24)

    def paint(self, painter, option, widget=None):
        s = self.SIZE
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        text = self._text()
        painter.setFont(self._font())
        fm = QFontMetrics(self._font())
        w = fm.horizontalAdvance(text)
        # cartouche lisible sur n'importe quel fond de plan
        box = QRectF(s - 1, -s - 15, w + 10, 15)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(theme.MARKER_BG)))
        painter.setPen(QPen(QColor(theme.DANGER), 1))
        painter.drawRoundedRect(box, 3, 3)
        painter.setPen(QPen(QColor(theme.DANGER)))
        painter.drawText(box.adjusted(5, 0, 0, 0),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         text)
        pen = QPen(QColor(theme.DANGER), 2)
        painter.setPen(pen)
        painter.drawLine(-s, 0, s, 0)
        painter.drawLine(0, -s, 0, s)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(0, 0), 3.5, 3.5)


# Une zone de cale annonce parfois sa hauteur libre dans son nom
# (« hauteur libre 1.70 m ») : le moteur le lit ainsi (core.stowage). On
# refait ici la même lecture plutôt que d'importer le moteur — l'éditeur de
# plans ne doit dépendre que du modèle, pas du calcul (D-10).
_RE_HAUTEUR = re.compile(r"(\d+(?:[.,]\d+)?)\s*m", re.IGNORECASE)


def nom_zone_hauteur(hauteur_m: float) -> str:
    """Le nom d'une zone à hauteur réduite : « hauteur libre 1.70 m ».

    C'est le seul endroit où cette phrase s'écrit. Le moteur la relit telle
    quelle (`core.stowage.hauteur_libre_de`, et `hauteur_annoncee` juste
    dessous) : un nom écrit autrement — sans le nombre, sans le « m » — ferait
    d'un simple plafond bas une zone INTERDITE, et la cale se refuserait à
    tout. Le point décimal, jamais la virgule : les deux se relisent, mais un
    seul se retrouve à l'œil dans un fichier."""
    return f"hauteur libre {float(hauteur_m):.2f} m"


def hauteur_annoncee(obstacle) -> float:
    """Hauteur libre (m) annoncée par une zone, 0 si elle n'en dit rien —
    une zone sans hauteur est interdite, une zone avec hauteur est un calque."""
    if len(obstacle) <= 4 or not obstacle[4]:
        return 0.0
    m = _RE_HAUTEUR.search(str(obstacle[4]))
    if not m:
        return 0.0
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return 0.0


class ZoneChargeItem(QGraphicsPolygonItem):
    """Zone de charge admissible particulière posée sur une cale (D-12).

    Elle ALERTE, elle ne borne pas le tracé : on la dessine en tireté, sans
    remplissage franc, pour qu'elle ne masque jamais le fond de plan qu'on
    décalque.

    Elle est SÉLECTIONNABLE dans l'éditeur de plans : le bord n'avait « pas
    trouvé où modifier les calques de limite t/m² » — un calque qu'on ne peut
    pas cliquer est un calque qu'on ne peut pas corriger. `capacity` dit à
    quelle cale elle appartient, pour pouvoir la retirer de la bonne liste."""

    def __init__(self, zone, calibration, capacity=None, parent=None):
        super().__init__(parent)
        self.zone = zone
        self.capacity = capacity
        self.calibration = calibration
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.label = _label(self, color=theme.WARN, size=7.5)
        self.rebuild()

    def rebuild(self):
        poly = QPolygonF()
        for a, b in self.zone.get("points", []):
            u, v = self.calibration.to_pixel(a, b)
            poly.append(QPointF(u, v))
        self.setPolygon(poly)
        t_m2 = self.zone.get("t_m2")
        nom = self.zone.get("nom") or "zone de charge"
        txt = nom + (f"  {t_m2:g} t/m²" if isinstance(t_m2, (int, float)) else "")
        self.label.setText(txt)
        self.label.setBrush(QBrush(QColor(theme.WARN)))
        r = poly.boundingRect()
        lr = self.label.boundingRect()
        self.label.setPos(r.center().x() - lr.width() / 2, r.top() + 2)
        self.setToolTip(f"Charge admissible {txt} — calque qui alerte, "
                        "sans jamais interdire (D-12).\nClic : la choisir ; "
                        "clic droit : Propriétés / Supprimer ; Suppr : la "
                        "retirer.")

    def paint(self, painter, option, widget=None):
        option.state &= ~QStyle.StateFlag.State_Selected
        poly = self.polygon()
        if poly.isEmpty():
            return
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        sel = self.isSelected()
        col = QColor(theme.WARN)
        fill = QColor(col)
        fill.setAlpha(60 if sel else 28)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(fill))
        painter.drawPolygon(poly)
        pen = QPen(QColor(theme.CAP_SEL) if sel else col, 2.6 if sel else 1.6)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.SolidLine if sel else Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(poly)


class ObstacleItem(QGraphicsRectItem):
    """Zone interdite (épontille, puits) ou à hauteur réduite dans une cale.

    Hachurée : on doit voir le trait du plan au travers, sinon on ne peut pas
    décalquer ce qui passe dessous.

    `source` est la LISTE du modèle, gardée par identité : c'est elle qu'il
    faut retirer de `cap.obstacles` quand le bord supprime la zone. `obstacle`
    reste une copie, pour que le dessin ne dépende pas d'une écriture en
    cours."""

    def __init__(self, obstacle, calibration, capacity=None, parent=None):
        super().__init__(parent)
        self.obstacle = list(obstacle)
        self.source = obstacle
        self.capacity = capacity
        self.calibration = calibration
        self.hauteur = hauteur_annoncee(obstacle)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.label = _label(self, size=7.5)
        self.rebuild()

    def _couleur(self):
        return QColor(theme.WARN if self.hauteur > 0 else theme.DANGER)

    def rebuild(self):
        x0, y0, x1, y1 = (float(v) for v in self.obstacle[:4])
        u0, v0 = self.calibration.to_pixel(x0, y0)
        u1, v1 = self.calibration.to_pixel(x1, y1)
        rect = QRectF(QPointF(u0, v0), QPointF(u1, v1)).normalized()
        self.setRect(rect)
        nom = (self.obstacle[4] if len(self.obstacle) > 4 else "") or "zone interdite"
        self.label.setText(str(nom))
        self.label.setBrush(QBrush(self._couleur()))
        lr = self.label.boundingRect()
        self.label.setPos(rect.center().x() - lr.width() / 2,
                          rect.center().y() - lr.height() / 2)
        aide = ("\nClic : la choisir ; clic droit : Propriétés / Supprimer ; "
                "Suppr : la retirer.")
        self.setToolTip(
            (f"{nom} — hauteur libre {self.hauteur:g} m (la pose y est signalée, "
             "pas refusée)" if self.hauteur > 0
             else f"{nom} — zone interdite : rien ne s'y pose") + aide)

    def paint(self, painter, option, widget=None):
        option.state &= ~QStyle.StateFlag.State_Selected
        rect = self.rect()
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        sel = self.isSelected()
        col = self._couleur()
        fill = QColor(col)
        fill.setAlpha(70 if sel else 38)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(fill, Qt.BrushStyle.BDiagPattern))
        painter.drawRect(rect)
        pen = QPen(QColor(theme.CAP_SEL) if sel else col, 2.6 if sel else 1.4)
        pen.setCosmetic(True)
        pen.setStyle(Qt.PenStyle.SolidLine if sel else
                     Qt.PenStyle.DotLine if self.hauteur > 0
                     else Qt.PenStyle.SolidLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)


class EpontilleItem(QGraphicsRectItem):
    """Emplacement d'une ÉPONTILLE AMOVIBLE, dans l'éditeur de plans.

    Elle n'est ni de la structure (un obstacle est toujours là) ni de la
    marchandise : on la dessine en carré barré d'une croix, dans la teinte des
    ponts, pour qu'elle ne se confonde avec rien. Le repère grossit jusqu'à
    rester saisissable même quand l'épontille fait vingt centimètres sur un
    plan au 1/100.

    Le point vif est le CENTRE : c'est lui qu'on clique pour la poser, et
    lui qu'on déplace."""

    MINI_PX = 9.0          # côté minimal du repère, en pixels du plan

    def __init__(self, epontille, capacity, calibration, parent=None):
        super().__init__(parent)
        self.epontille = epontille
        self.capacity = capacity
        self.calibration = calibration
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(19)
        self.label = _label(self, color=theme.DECK_LINE, size=7.5)
        self.rebuild()

    # ------------------------------------------------------------ géométrie
    def centre_pixel(self) -> QPointF:
        e = self.epontille
        u, v = self.calibration.to_pixel(float(e.get("x", 0.0)),
                                         float(e.get("y", 0.0)))
        return QPointF(u, v)

    def rebuild(self):
        from .core.stowage import rect_epontille
        x0, y0, x1, y1 = rect_epontille(self.epontille)[:4]
        u0, v0 = self.calibration.to_pixel(x0, y0)
        u1, v1 = self.calibration.to_pixel(x1, y1)
        rect = QRectF(QPointF(u0, v0), QPointF(u1, v1)).normalized()
        c = rect.center()
        w = max(rect.width(), self.MINI_PX)
        h = max(rect.height(), self.MINI_PX)
        rect = QRectF(c.x() - w / 2, c.y() - h / 2, w, h)
        self.setRect(rect)
        nom = str(self.epontille.get("nom") or "épontille")
        self.label.setText(nom)
        self.label.setBrush(QBrush(QColor(theme.DECK_LINE)))
        lr = self.label.boundingRect()
        self.label.setPos(rect.center().x() - lr.width() / 2, rect.bottom() + 2)
        e = self.epontille
        self.setToolTip(
            f"Épontille « {nom} » — {e.get('longueur_m', 0):g} × "
            f"{e.get('largeur_m', 0):g} m, cale {getattr(self.capacity, 'code', '?')}"
            "\nEmplacement du navire. Elle n'interdit la pose que lorsqu'elle "
            "est MISE EN PLACE, ce qui se décide dans la vue Chargement.")

    def paint(self, painter, option, widget=None):
        rect = self.rect()
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        choisie = bool(option.state & QStyle.StateFlag.State_Selected)
        col = QColor(theme.CAP_SEL if choisie else theme.DECK_LINE)
        fond = QColor(col)
        fond.setAlpha(70)
        painter.setBrush(QBrush(fond))
        pen = QPen(col, 2.4 if choisie else 1.6)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawRect(rect)
        painter.drawLine(rect.topLeft(), rect.bottomRight())
        painter.drawLine(rect.topRight(), rect.bottomLeft())


# ------------------------------------------------------------ informations
# Formes du CALQUE D'INFORMATION, dans l'ordre où la fiche les propose.
FORMES_ANNOTATION = ("trait", "polygone", "point", "texte")
NOMS_FORMES_ANNOTATION = {
    "trait": "Polyligne (clics + double-clic)",
    # Le bord : « on ne peut pas rajouter la fermeture automatique des
    # polygones comme pour la création des contours de cale ? » — si : mêmes
    # gestes que le contour d'une cale, et le double-clic REFERME la forme.
    "polygone": "Polygone fermé (clics + double-clic)",
    "point": "Point (un clic)",
    "texte": "Texte (un clic, puis la saisie)",
}
# Couleurs proposées : peu nombreuses et franches. Un nuancier complet ferait
# perdre du temps pour un calque dont personne ne lit la couleur.
COULEURS_ANNOTATION = [
    ("Bleu", "#1F6FEB"), ("Vert", "#1A7F37"), ("Orange", "#BC4C00"),
    ("Rouge", "#CF222E"), ("Violet", "#8250DF"), ("Gris", "#57606A"),
]
COULEUR_ANNOTATION_DEFAUT = COULEURS_ANNOTATION[0][1]

# Rayon du repère d'un point d'information, en pixels du PLAN (comme
# `EpontilleItem.MINI_PX`) : assez gros pour être visé, assez petit pour ne pas
# masquer le trait qu'il désigne.
RAYON_POINT_INFO = 7.0


class AnnotationItem(QGraphicsItem):
    """Un objet du CALQUE D'INFORMATION d'un pont (`Deck.annotations`).

    Quatre formes : une polyligne, un polygone fermé, un point, un texte. Le
    polygone se trace comme le contour d'une cale — clics puis double-clic qui
    referme — parce que c'est le geste que le bord connaît déjà.

    Rien en aval ne les lit
    — ni la stabilité, ni la pose, ni le solveur : c'est ce que le bord voulait
    pouvoir décalquer (« emplacement des clés de saisissage… ») sans que le
    logiciel en tire la moindre conséquence. On les dessine donc dans leur
    propre couleur, jamais dans celle des objets qui, eux, contraignent."""

    def __init__(self, annotation, calibration, deck=None, parent=None):
        super().__init__(parent)
        self.annotation = annotation
        self.deck = deck
        self.calibration = calibration
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.points = []
        self.rebuild()

    # ------------------------------------------------------------ géométrie
    @property
    def forme(self) -> str:
        f = str(self.annotation.get("type") or "trait")
        return f if f in FORMES_ANNOTATION else "trait"

    def couleur(self) -> QColor:
        c = QColor(str(self.annotation.get("couleur") or ""))
        return c if c.isValid() else QColor(COULEUR_ANNOTATION_DEFAUT)

    def texte(self) -> str:
        return str(self.annotation.get("texte") or "")

    def _font(self):
        f = QFont()
        f.setPointSizeF(9.0)
        f.setBold(True)
        return f

    def rebuild(self):
        self.prepareGeometryChange()
        self.points = [QPointF(*self.calibration.to_pixel(float(p[0]), float(p[1])))
                       for p in (self.annotation.get("points") or [])
                       if len(p) >= 2]
        quoi = {"trait": "polyligne", "polygone": "polygone fermé",
                "point": "point", "texte": "texte"}[self.forme]
        titre = self.texte() or f"information ({quoi})"
        self.setToolTip(
            f"« {titre} » — calque d'information : rien n'en dépend, ni la "
            "pose, ni la stabilité, ni le solveur.\nClic : la choisir ; clic "
            "droit : Propriétés / Supprimer ; Suppr : la retirer.")
        self.update()

    def boundingRect(self):
        if not self.points:
            return QRectF(-1, -1, 2, 2)
        xs = [p.x() for p in self.points]
        ys = [p.y() for p in self.points]
        r = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        if self.forme == "texte":
            w = QFontMetrics(self._font()).horizontalAdvance(
                self.texte() or "texte")
            return r.adjusted(-6, -18, w + 12, 8)
        return r.adjusted(-RAYON_POINT_INFO - 3, -RAYON_POINT_INFO - 3,
                          RAYON_POINT_INFO + 3, RAYON_POINT_INFO + 3)

    def shape(self):
        """Une polyligne se clique sur son trait, pas dans son rectangle
        englobant : sans cela, une longue diagonale attraperait tous les clics
        d'un quart du plan."""
        from PySide6.QtGui import QPainterPath, QPainterPathStroker

        path = QPainterPath()
        if self.forme == "polygone" and len(self.points) >= 3:
            # un polygone se clique DANS sa surface : c'est une emprise, pas
            # un trait — et son remplissage est ce qu'on voit
            path.addPolygon(QPolygonF(self.points))
            path.closeSubpath()
            return path
        if self.forme == "trait" and len(self.points) >= 2:
            path.moveTo(self.points[0])
            for p in self.points[1:]:
                path.lineTo(p)
            stroker = QPainterPathStroker()
            stroker.setWidth(8)
            return stroker.createStroke(path)
        path.addRect(self.boundingRect())
        return path

    # ------------------------------------------------------------ dessin
    def paint(self, painter, option, widget=None):
        option.state &= ~QStyle.StateFlag.State_Selected
        if not self.points:
            return
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        sel = self.isSelected()
        col = QColor(theme.CAP_SEL) if sel else self.couleur()
        pen = QPen(col, 2.6 if sel else 1.6)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        forme = self.forme
        if forme == "polygone" and len(self.points) >= 3:
            # dessiné FERMÉ et légèrement rempli : on doit voir d'un coup
            # d'œil que c'est une emprise, sans qu'elle masque le plan qu'elle
            # recouvre — ce calque n'est qu'une note, il ne contraint rien
            fond = QColor(col)
            fond.setAlpha(45 if sel else 30)
            painter.setBrush(QBrush(fond))
            painter.drawPolygon(QPolygonF(self.points))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        elif forme == "trait" and len(self.points) >= 2:
            for a, b in zip(self.points, self.points[1:]):
                painter.drawLine(a, b)
        elif forme == "point":
            p = self.points[0]
            r = RAYON_POINT_INFO
            painter.drawEllipse(p, r, r)
            painter.drawLine(QPointF(p.x() - r - 3, p.y()),
                             QPointF(p.x() + r + 3, p.y()))
            painter.drawLine(QPointF(p.x(), p.y() - r - 3),
                             QPointF(p.x(), p.y() + r + 3))
        else:                       # texte
            p = self.points[0]
            painter.setFont(self._font())
            painter.drawText(QPointF(p.x() + 4, p.y() - 4),
                             self.texte() or "(texte vide)")
            painter.drawLine(QPointF(p.x() - 4, p.y()), QPointF(p.x() + 4, p.y()))
            painter.drawLine(QPointF(p.x(), p.y() - 4), QPointF(p.x(), p.y() + 4))
        if forme in ("trait", "polygone") and self.texte():
            painter.setFont(self._font())
            p = self.points[0]
            painter.drawText(QPointF(p.x() + 5, p.y() - 5), self.texte())
