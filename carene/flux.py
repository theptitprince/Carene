# -*- coding: utf-8 -*-
"""Une mise en page qui PASSE À LA LIGNE : le bandeau supérieur (D-67).

Le bord (22/09/2026) : « si la fenêtre est trop petite, on perd une partie
du contenu du bandeau supérieur ». Le bandeau vivait dans la barre d'outils
de Qt, en un seul bloc — et une barre d'outils CACHE EN ENTIER un widget qui
ne tient plus dans sa largeur : plus de nom de navire, plus de chiffres, plus
de verdict, rien qu'un petit « » » qui n'ouvre sur rien. Le sélecteur de
voilure l'avait déjà fait basculer une fois ; un portable, ou une fenêtre
partagée avec le recueil de stabilité, le fait tous les jours.

Ce que le bord veut, c'est ce que fait un texte : quand la ligne est trop
courte, on va à la ligne. Cette mise en page range ses éléments de gauche à
droite et passe à la ligne suivante quand la largeur manque — rien ne
disparaît jamais, la deuxième ligne coûte trente pixels de hauteur, et sur un
grand écran il n'y a qu'une ligne comme avant. C'est le « flow layout » des
exemples de Qt, réduit à ce qu'on en emploie.

Qt ne sait calculer la hauteur d'une telle mise en page qu'en connaissant sa
largeur (`hasHeightForWidth`) : c'est ce qui permet à la fenêtre principale
de donner au bandeau juste la hauteur qu'il lui faut, et pas une de plus.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QSizePolicy, QStyle


class FlowLayout(QLayout):
    """Des éléments rangés en ligne, qui vont à la ligne quand elle est pleine.

    `h_espace` et `v_espace` : les blancs entre deux éléments et entre deux
    lignes ; -1 laisse le style décider, comme dans une barre d'outils."""

    def __init__(self, parent=None, marge=0, h_espace=-1, v_espace=-1):
        super().__init__(parent)
        self._h = h_espace
        self._v = v_espace
        self._items = []
        self.setContentsMargins(marge, marge, marge, marge)

    def __del__(self):
        while self.count():
            self.takeAt(0)

    # ------------------------------------------------------ le contrat QLayout
    def addItem(self, item):                         # noqa: N802 - Qt
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):                          # noqa: N802 - Qt
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):                          # noqa: N802 - Qt
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):                    # noqa: N802 - Qt
        return Qt.Orientation(0)

    def hasHeightForWidth(self):                      # noqa: N802 - Qt
        return True

    def heightForWidth(self, largeur):                # noqa: N802 - Qt
        return self._ranger(QRect(0, 0, largeur, 0), essai=True)

    def setGeometry(self, rect):                      # noqa: N802 - Qt
        super().setGeometry(rect)
        self._ranger(rect, essai=False)

    def sizeHint(self):                               # noqa: N802 - Qt
        return self.minimumSize()

    def minimumSize(self):                            # noqa: N802 - Qt
        """Le plus large des éléments, et la hauteur d'une ligne : c'est le
        minimum en deçà duquel on ne peut rien promettre — au-delà, tout tient
        toujours, sur autant de lignes qu'il faut."""
        taille = QSize()
        for item in self._items:
            taille = taille.expandedTo(item.minimumSize())
        g, h, d, b = self.getContentsMargins()
        return taille + QSize(g + d, h + b)

    # ----------------------------------------------------------- les espaces
    def h_espace(self):
        return self._h if self._h >= 0 else self._espace_du_style(
            QStyle.PixelMetric.PM_LayoutHorizontalSpacing)

    def v_espace(self):
        return self._v if self._v >= 0 else self._espace_du_style(
            QStyle.PixelMetric.PM_LayoutVerticalSpacing)

    def _espace_du_style(self, metrique):
        parent = self.parent()
        if parent is None:
            return -1
        if parent.isWidgetType():
            return parent.style().pixelMetric(metrique, None, parent)
        return parent.spacing()

    # ------------------------------------------------------------- le rangement
    def _ranger(self, rect, essai):
        """Place les éléments ligne après ligne ; rend la hauteur employée.

        `essai` : ne rien déplacer, seulement mesurer (pour `heightForWidth`)."""
        g, h, d, b = self.getContentsMargins()
        zone = rect.adjusted(g, h, -d, -b)
        x = zone.x()
        y = zone.y()
        haut_ligne = 0
        for item in self._items:
            w = item.widget()
            if w is not None and w.isHidden():
                continue                    # un élément caché ne prend pas de place
            he = self.h_espace()
            if he == -1 and w is not None:
                he = w.style().layoutSpacing(QSizePolicy.ControlType.PushButton,
                                             QSizePolicy.ControlType.PushButton,
                                             Qt.Orientation.Horizontal)
            ve = self.v_espace()
            if ve == -1 and w is not None:
                ve = w.style().layoutSpacing(QSizePolicy.ControlType.PushButton,
                                             QSizePolicy.ControlType.PushButton,
                                             Qt.Orientation.Vertical)
            taille = item.sizeHint()
            suivant = x + taille.width() + he
            if suivant - he > zone.right() + 1 and haut_ligne > 0:
                # la ligne est pleine : à la ligne
                x = zone.x()
                y = y + haut_ligne + ve
                suivant = x + taille.width() + he
                haut_ligne = 0
            if not essai:
                item.setGeometry(QRect(QPoint(x, y), taille))
            x = suivant
            haut_ligne = max(haut_ligne, taille.height())
        return y + haut_ligne - rect.y() + b


class Rangee:
    """Une barre d'outils faite de GROUPES insécables, qui passe à la ligne.

    L'interface est celle d'un `QHBoxLayout` (addWidget, addLayout,
    addSpacing, addStretch) pour que le code qui garnit la barre ne change
    pas : chaque appel s'adresse au groupe ouvert par le dernier `groupe()`.
    Un groupe est un cadre à disposition horizontale, posé dans un
    `FlowLayout` : quand la fenêtre rétrécit, ce sont des groupes entiers qui
    passent à la ligne suivante — jamais un bouton coupé de son étiquette.

    `addStretch` ne fait rien : dans un flux il n'y a pas de « reste de la
    ligne » à pousser, et un ressort y ferait sauter une ligne pour rien."""

    def __init__(self, cadre, marges=(8, 4, 8, 4), espace=5, entre_groupes=10):
        self.flux = FlowLayout(cadre, marge=0, h_espace=entre_groupes, v_espace=2)
        self.flux.setContentsMargins(*marges)
        self.espace = espace
        self.courant = None
        self.groupes = []

    def groupe(self, etiquette=None, separateur=None):
        """Ouvre un nouveau groupe et rend son cadre. `etiquette` : le widget
        d'intitulé (facultatif) ; `separateur` : le trait qui le précède."""
        from PySide6.QtWidgets import QFrame, QHBoxLayout
        g = QFrame()
        g.setObjectName("groupeBarre")
        g.setStyleSheet("QFrame#groupeBarre { background: transparent; }")
        lay = QHBoxLayout(g)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(self.espace)
        if separateur is not None:
            lay.addWidget(separateur)
            lay.addSpacing(2)
        if etiquette is not None:
            lay.addWidget(etiquette)
        self.flux.addWidget(g)
        self.courant = lay
        self.groupes.append(g)
        return g

    # ------------------------------------------------ l'interface QHBoxLayout
    def _lay(self):
        if self.courant is None:
            self.groupe()
        return self.courant

    def addWidget(self, w, *args, **kw):              # noqa: N802 - Qt
        self._lay().addWidget(w, *args, **kw)

    def addLayout(self, lay, *args):                  # noqa: N802 - Qt
        self._lay().addLayout(lay, *args)

    def addSpacing(self, n):                          # noqa: N802 - Qt
        self._lay().addSpacing(n)

    def addStretch(self, *_a):                        # noqa: N802 - Qt
        """Rien : voir la docstring de la classe."""

    def setContentsMargins(self, *m):                 # noqa: N802 - Qt
        self.flux.setContentsMargins(*m)

    def setSpacing(self, n):                          # noqa: N802 - Qt
        self.espace = n
