# -*- coding: utf-8 -*-
"""Le manifeste dans sa propre fenêtre.

Composer le manifeste et poser les colis sont deux moments différents : l'un
se fait au bureau avant l'escale, l'autre sur le plan pendant. Les séparer rend
les deux plus lisibles — et laisse toute la largeur au plan de chargement.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QVBoxLayout

from .manifest_panel import ManifestPanel


class ManifestDialog(QDialog):
    """Le manifeste, en grand."""

    changed = Signal()

    def __init__(self, win, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.setWindowTitle("Manifeste — ce qu'il y a à embarquer")
        self.resize(1280, 700)
        self.setModal(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.panel = ManifestPanel(win)
        self.panel.changed.connect(self.changed.emit)
        root.addWidget(self.panel, 1)

        row = QHBoxLayout()
        row.setContentsMargins(9, 0, 9, 9)
        row.addStretch(1)
        b = QPushButton("Fermer")
        b.setProperty("accent", "1")
        b.clicked.connect(self.accept)
        row.addWidget(b)
        root.addLayout(row)

    def refresh(self):
        self.panel.refresh()
