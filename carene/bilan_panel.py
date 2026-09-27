# -*- coding: utf-8 -*-
"""Le bilan des poids, groupé avec sous-totaux — vue Stabilité.

Chaque ligne, son poids, ses trois centres, sa carène liquide ; un sous-total
par groupe ; le total qui entre dans le calcul. Les chiffres sont ceux du
moteur (voir `carene.bilan`).

Le **matériel du bord** (chariot élévateur, transpalette) a son propre groupe,
séparé des cales : ce n'est pas du fret, il sera encore là au prochain voyage.
Il pèse exactement comme avant — la séparation est de lecture, pas de calcul.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import bilan, theme

COLS = ["Poste", "Poids t", "LCG m", "TCG m", "VCG m", "FSM t·m", "Détail"]


class BilanPanel(QWidget):
    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(9, 7, 9, 9)
        lay.setSpacing(6)
        titre = QLabel("BILAN DES POIDS — ce que le calcul additionne")
        titre.setObjectName("cardTitle")
        lay.addWidget(titre)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        head = self.table.horizontalHeader()
        for c in range(len(COLS)):
            head.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setWordWrap(False)
        lay.addWidget(self.table, 1)
        self.lbl = QLabel("")
        self.lbl.setObjectName("hint")
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl)

    def refresh(self):
        nav = getattr(self.win, "nav", None)
        if nav is None:
            self.table.setRowCount(0)
            self.lbl.setText("Tables du navire absentes : pas de bilan.")
            return
        b = bilan.construire(self.win.condition, nav, self.win.project)
        rows = []
        for g in b.groupes:
            rows.append(("groupe", g))
            for l in g.lignes:
                rows.append(("ligne", l))
            if len(g.lignes) > 1:
                rows.append(("sous-total", g))
        rows.append(("total", b))
        self.table.setRowCount(len(rows))
        for r, (genre, obj) in enumerate(rows):
            if genre == "groupe":
                vals = [obj.nom.upper(), "", "", "", "", "", ""]
            elif genre == "ligne":
                vals = [f"    {obj.nom}", f"{obj.poids_t:.2f}", f"{obj.lcg_m:.2f}", f"{obj.tcg_m:+.2f}",
                        f"{obj.vcg_m:.2f}", f"{obj.fsm_tm:.1f}" if obj.fsm_tm else "",
                        obj.detail + (f" — {obj.alerte}" if obj.alerte else "")]
            else:
                lcg, tcg, vcg = obj.centres()
                nom = "TOTAL" if genre == "total" else f"Sous-total {obj.nom.lower()}"
                vals = [nom, f"{obj.poids_t:.2f}", f"{lcg:.2f}", f"{tcg:+.2f}", f"{vcg:.2f}",
                        f"{obj.fsm_tm:.1f}" if obj.fsm_tm else "", ""]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c in (1, 2, 3, 4, 5):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if genre in ("groupe", "sous-total", "total"):
                    f = item.font(); f.setBold(True); item.setFont(f)
                if genre == "groupe":
                    item.setForeground(QColor(theme.TEXT_DIM))
                if genre == "sous-total":
                    item.setBackground(QColor(theme.SURFACE_2))
                if genre == "total":
                    item.setForeground(QColor(theme.ACCENT_DARK))
                    item.setBackground(QColor(theme.SURFACE_2))
                if genre == "ligne" and obj.alerte and c == 6:
                    item.setForeground(QColor(theme.WARN if "carène" in obj.alerte else theme.DANGER))
                self.table.setItem(r, c, item)
        lcg, tcg, vcg = b.centres()
        conv = getattr(nav, "convention_fsm", "max")
        self.lbl.setText(
            f"Total {b.poids_t:.1f} t · LCG {lcg:.3f} m · TCG {tcg:+.3f} m · VCG {vcg:.3f} m · "
            f"FSM {b.fsm_tm:.1f} t·m — « MATÉRIEL DU BORD » est un groupe à part : "
            "il pèse comme le reste, mais ce n'est pas de la marchandise. "
            f"Carène liquide : convention « {conv} » du dossier "
            f"({'FSM maximal dès qu’une capacité est en carène liquide' if conv == 'max' else 'FSM interpolé au remplissage'}). "
            "VCG solide ; la correction de carène liquide est portée une seule fois, sur le GM.")
