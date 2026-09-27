# -*- coding: utf-8 -*-
"""Les champs de saisie de nombres, tels que le bord les veut.

Deux reproches, tous deux justes :

- **l'unité ne doit pas être dans le champ.** Un suffixe Qt (« 1,6 t ») fait
  partie du texte édité : on sélectionne tout, on tape, et la saisie se bat
  avec l'unité. Ici l'unité est PEINTE à droite du champ, hors du texte —
  imposée, jamais éditable, et le champ ne contient que des chiffres ;
- **le point et la virgule sont tous deux des séparateurs décimaux.** Sur un
  Windows en français, Qt n'accepte que la virgule ; le pavé numérique tape un
  point. Un poids saisi « 1.6 » était refusé sans un mot. On accepte les deux.
"""
from __future__ import annotations

from PySide6.QtCore import QLocale, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QDoubleSpinBox, QSpinBox, QStyle, QStyledItemDelegate

from . import theme


# ce que les tableaux écrivent dans une cellule VIDE, pour qu'on voie qu'une
# valeur manque au lieu de lire un « 0 » : un affichage, jamais une saisie
TIRET_VIDE = "—"


class DelegueSansTiret(QStyledItemDelegate):
    """L'éditeur d'une cellule qui n'affiche que « — » s'ouvre VIDE (D-89).

    Le tiret est un vrai caractère de la cellule : sans ce délégué, taper une
    valeur à sa place l'ajoutait derrière le tiret (« —1,35 »), et il fallait
    l'effacer à la main."""

    def setEditorData(self, editor, index):
        super().setEditorData(editor, index)
        texte = getattr(editor, "text", None)
        if callable(texte) and str(texte()).strip() == TIRET_VIDE \
                and hasattr(editor, "clear"):
            editor.clear()


class SpinNombre(QDoubleSpinBox):
    """QDoubleSpinBox dont l'unité est hors du texte, et qui accepte « . »
    comme « , »."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._unite = ""
        # locale neutre : le point est le séparateur natif ; la virgule est
        # convertie à la volée dans `validate` / `valueFromText`
        self.setLocale(QLocale.c())
        # Ce qu'on tape est ce qu'on obtient : sans cela, chaque frappe
        # réécrit le champ (« 12.5 » devient « 12.000 » avant qu'on ait fini).
        self.setKeyboardTracking(False)

    # ------------------------------------------------------------ l'unité
    def setSuffix(self, texte):          # noqa: N802 — même nom que Qt, exprès
        """L'unité, peinte à droite — jamais dans le texte."""
        self._unite = (texte or "").strip()
        super().setSuffix("")
        self._marges()

    def suffix(self):                    # noqa: N802
        return self._unite

    def unite(self):
        return self._unite

    def _marges(self):
        le = self.lineEdit()
        if le is None:
            return
        largeur = self.fontMetrics().horizontalAdvance(self._unite) + 8 if self._unite else 0
        le.setTextMargins(0, 0, largeur, 0)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (event.Type.FontChange, event.Type.StyleChange):
            self._marges()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._unite:
            return
        # la zone de texte, sans les flèches : l'unité se peint tout à droite
        opt = self._option()
        zone = self.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, opt,
                                           QStyle.SubControl.SC_SpinBoxEditField, self)
        p = QPainter(self)
        p.setPen(QColor(theme.TEXT_DIM) if theme.TEXT_DIM
                 else self.palette().placeholderText().color())
        p.drawText(zone.adjusted(0, 0, -4, 0),
                   int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                   self._unite)
        p.end()

    def _option(self):
        from PySide6.QtWidgets import QStyleOptionSpinBox
        opt = QStyleOptionSpinBox()
        self.initStyleOption(opt)
        return opt

    # ------------------------------------------------ point ou virgule
    @staticmethod
    def _normaliser(texte):
        return (texte or "").replace(",", ".").replace(" ", "").replace("\\u202f", "")

    def validate(self, texte, pos):
        etat, t, p = super().validate(self._normaliser(texte), pos)
        return etat, texte, pos

    def valueFromText(self, texte):      # noqa: N802
        return super().valueFromText(self._normaliser(texte))

    def fixup(self, texte):
        return super().fixup(self._normaliser(texte))


class SpinEntier(QSpinBox):
    """QSpinBox avec l'unité hors du texte, pour les mêmes raisons."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._unite = ""
        self.setKeyboardTracking(False)

    def setSuffix(self, texte):          # noqa: N802
        self._unite = (texte or "").strip()
        super().setSuffix("")
        le = self.lineEdit()
        if le is not None:
            largeur = self.fontMetrics().horizontalAdvance(self._unite) + 8 if self._unite else 0
            le.setTextMargins(0, 0, largeur, 0)

    def suffix(self):                    # noqa: N802
        return self._unite

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._unite:
            return
        from PySide6.QtWidgets import QStyleOptionSpinBox
        opt = QStyleOptionSpinBox()
        self.initStyleOption(opt)
        zone = self.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, opt,
                                           QStyle.SubControl.SC_SpinBoxEditField, self)
        p = QPainter(self)
        p.setPen(self.palette().placeholderText().color())
        p.drawText(zone.adjusted(0, 0, -4, 0),
                   int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                   self._unite)
        p.end()
