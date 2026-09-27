# -*- coding: utf-8 -*-
"""Panneau « Résultats » : équilibre, courbe GZ et critères réglementaires.

Il ne détient aucun état : on lui passe le résultat d'un calcul et il l'affiche.
Le calcul lui-même est fait par la fenêtre principale, qui appelle le moteur.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import theme


class GZChartWidget(QWidget):
    """Courbe GZ(gîte) dessinée à la main (cohérent avec le reste de
    l'application, pas de dépendance à QtCharts)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(230)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.heels = []
        self.gzs = []
        self.gz_max = None
        self.angle_gz_max = None
        self.angle_annulation = None

    def set_curve(self, gz_res):
        if gz_res is None:
            self.heels, self.gzs = [], []
            self.gz_max = self.angle_gz_max = self.angle_annulation = None
        else:
            self.heels = [h for h in gz_res.heel_deg if h >= 0]
            self.gzs = gz_res.gz_m[-len(self.heels):]
            self.gz_max = gz_res.gz_max_m
            self.angle_gz_max = gz_res.angle_gz_max_deg
            self.angle_annulation = gz_res.angle_annulation_deg
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.SURFACE))
        pad_l, pad_r, pad_t, pad_b = 42, 16, 16, 26
        w = self.width() - pad_l - pad_r
        h = self.height() - pad_t - pad_b
        if w <= 10 or h <= 10:
            p.end()
            return

        if not self.heels:
            p.setPen(QColor(theme.TEXT_FAINT))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Calculez une condition pour afficher la courbe GZ")
            p.end()
            return

        x_max = max(60.0, max(self.heels))
        y_max = max(0.3, max(self.gzs) * 1.18)
        y_min = min(0.0, min(self.gzs) * 1.1)

        def px(heel):
            return pad_l + heel / x_max * w

        def py(gz):
            return pad_t + h - (gz - y_min) / (y_max - y_min) * h

        # grille + axes
        pen_grid = QPen(QColor(*theme.GRID_X) if isinstance(theme.GRID_X, tuple)
                        else QColor(theme.GRID_X))
        pen_grid.setWidthF(1)
        p.setPen(pen_grid)
        step_x = 10 if x_max <= 65 else 20
        xt = 0
        while xt <= x_max + 1e-6:
            p.drawLine(int(px(xt)), pad_t, int(px(xt)), pad_t + h)
            xt += step_x
        step_y = 0.2 if y_max <= 1.4 else (0.5 if y_max <= 3.5 else 1.0)
        yt = math.ceil(y_min / step_y) * step_y
        while yt <= y_max + 1e-6:
            p.drawLine(pad_l, int(py(yt)), pad_l + w, int(py(yt)))
            yt += step_y

        pen_axis = QPen(QColor(theme.BORDER_SOFT))
        pen_axis.setWidthF(1.4)
        p.setPen(pen_axis)
        p.drawLine(pad_l, int(py(0)), pad_l + w, int(py(0)))
        p.drawLine(pad_l, pad_t, pad_l, pad_t + h)

        p.setPen(QColor(theme.TEXT_FAINT))
        f = QFont()
        f.setPointSize(8)
        p.setFont(f)
        xt = 0
        while xt <= x_max + 1e-6:
            p.drawText(int(px(xt)) - 10, pad_t + h + 16, 20, 12,
                       Qt.AlignmentFlag.AlignCenter, f"{xt:g}°")
            xt += step_x
        yt = math.ceil(y_min / step_y) * step_y
        while yt <= y_max + 1e-6:
            p.drawText(2, int(py(yt)) - 7, pad_l - 6, 14,
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{yt:.1f}")
            yt += step_y

        # courbe GZ
        pen_curve = QPen(QColor(theme.ACCENT))
        pen_curve.setWidthF(2.4)
        pen_curve.setCosmetic(True)
        p.setPen(pen_curve)
        pts = [(px(h), py(g)) for h, g in zip(self.heels, self.gzs)]
        for i in range(len(pts) - 1):
            p.drawLine(int(pts[i][0]), int(pts[i][1]), int(pts[i + 1][0]), int(pts[i + 1][1]))

        # sommet
        if self.gz_max is not None and self.angle_gz_max is not None:
            cx, cy = px(self.angle_gz_max), py(self.gz_max)
            p.setBrush(QColor(theme.ACCENT))
            p.setPen(QPen(QColor(theme.SURFACE), 1.5))
            p.drawEllipse(cx - 4, cy - 4, 8, 8)
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(int(cx) - 40, int(cy) - 22, 90, 16,
                       Qt.AlignmentFlag.AlignLeft,
                       f"GZmax {self.gz_max:.2f} m @ {self.angle_gz_max:.0f}°")
        p.end()



def _pill(text="", tone="todo"):
    lbl = QLabel(text)
    lbl.setObjectName("pill")
    lbl.setProperty("tone", tone)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return lbl


def _card(title):
    frame = QFrame()
    frame.setObjectName("card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(9, 7, 9, 9)
    lay.setSpacing(8)
    if title:
        t = QLabel(title)
        t.setObjectName("cardTitle")
        lay.addWidget(t)
    return frame, lay


class ResultsPanel(QWidget):
    """Courbe GZ + tableau des critères."""

    def __init__(self, parent=None):
        super().__init__(parent)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        self.root = QVBoxLayout(inner)
        self.root.setContentsMargins(9, 8, 9, 9)
        self.root.setSpacing(12)
        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        frame, lay = _card("Flottaison et centre de gravité")
        self.flot_box = QVBoxLayout()
        self.flot_box.setSpacing(2)
        lay.addLayout(self.flot_box)
        self.lbl_flot_none = QLabel("Aucun calcul effectué.")
        self.lbl_flot_none.setObjectName("hint")
        self.lbl_flot_none.setWordWrap(True)
        lay.addWidget(self.lbl_flot_none)
        self.root.addWidget(frame)

        frame, lay = _card("Courbe de stabilité")
        self.chart = GZChartWidget()
        lay.addWidget(self.chart)
        self.root.addWidget(frame)

        frame, lay = _card("Critères réglementaires")
        self.lbl_avert = QLabel("")
        self.lbl_avert.setWordWrap(True)
        self.lbl_avert.setVisible(False)
        lay.addWidget(self.lbl_avert)
        self.criteria_box = QVBoxLayout()
        self.criteria_box.setSpacing(4)
        lay.addLayout(self.criteria_box)
        self.lbl_none = QLabel("Aucun calcul effectué.")
        self.lbl_none.setObjectName("hint")
        self.lbl_none.setWordWrap(True)
        lay.addWidget(self.lbl_none)
        self.root.addWidget(frame)
        self.root.addStretch(1)

    # ------------------------------------------------------------------ rendu
    def clear(self, message="Aucun calcul effectué."):
        self.chart.set_curve(None)
        self._clear_criteria()
        self._vider(self.flot_box)
        self.lbl_flot_none.setVisible(True)
        self.set_avertissement("")
        self.lbl_none.setText(message)
        self.lbl_none.setVisible(True)

    def _clear_criteria(self):
        self._vider(self.criteria_box)

    @staticmethod
    def _vider(box):
        while box.count():
            item = box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)     # deleteLater seul laisse un fantôme
                w.deleteLater()

    def set_avertissement(self, texte=""):
        """Réserve explicite sur la portée des critères affichés."""
        self.lbl_avert.setText(
            f"<span style='color:{theme.DANGER}'>{texte}</span>" if texte else "")
        self.lbl_avert.setVisible(bool(texte))

    def show_flottaison(self, lignes):
        """Le détail chiffré de la flottaison, en intitulé → valeur."""
        self._vider(self.flot_box)
        self.lbl_flot_none.setVisible(not lignes)
        for libelle, valeur in lignes:
            w = QWidget()
            row = QHBoxLayout(w)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            g = QLabel(libelle)
            g.setStyleSheet(f"color: {theme.TEXT_DIM};")
            g.setWordWrap(True)
            d = QLabel(valeur)
            d.setStyleSheet("font-weight: bold;")
            d.setAlignment(Qt.AlignmentFlag.AlignRight
                           | Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(g, 1)
            row.addWidget(d, 0)
            self.flot_box.addWidget(w)

    def show_result(self, gz, rapport):
        self.chart.set_curve(gz)
        self._clear_criteria()
        self.lbl_none.setVisible(False)
        if not rapport.checks:
            self.lbl_none.setVisible(True)
            self.lbl_none.setText("Aucun critère évaluable pour cet état.")
        groupe_courant = ""
        for chk in rapport.checks:
            # Les critères de vent dépendent de la voilure portée : ils
            # arrivent sous leur propre titre pour qu'on ne les lise pas comme
            # des critères généraux valables en toute circonstance.
            groupe = getattr(chk, "groupe", "") or ""
            if groupe != groupe_courant:
                groupe_courant = groupe
                if groupe:
                    self._add_titre(groupe)
            evaluable = getattr(chk, "evaluable", True)
            information = getattr(chk, "information", False)
            # décimales selon l'unité, valeur et seuil au même format (D-78)
            from .core.criteria import format_nombre
            if not evaluable:
                seuil = format_nombre(chk.seuil, chk.unite)
                detail = ("valeur non calculable" if information or seuil == "—" else
                          f"valeur non calculable — seuil {chk.comparaison} "
                          f"{seuil} {chk.unite}".strip())
            elif information:
                detail = f"{format_nombre(chk.valeur, chk.unite)} {chk.unite}".strip()
            else:
                detail = (f"{format_nombre(chk.valeur, chk.unite)} {chk.comparaison} "
                          f"{format_nombre(chk.seuil, chk.unite)} {chk.unite}".strip())
            self._add_row(chk.libelle, chk.ok, detail, evaluable, information)

    def _add_titre(self, texte):
        """Le titre d'un bloc de critères (« NR500 voilier — Full sails… »)."""
        lbl = QLabel(texte)
        lbl.setObjectName("cardTitle")
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-weight: bold; "
                          "margin-top: 6px;")
        self.criteria_box.addWidget(lbl)

    def _add_row(self, label, ok, detail="", evaluable=True, information=False):
        """Intitulé + pastille sur une ligne, valeur chiffrée en dessous —
        aucune troncature quelle que soit la largeur du panneau.

        Une ligne d'INFORMATION (la force de vent admissible, la pression
        correspondante) n'a pas de pastille : ce n'est pas une épreuve à
        passer, c'est un résultat que le dossier imprime."""
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(0, 2, 0, 2)
        col.setSpacing(1)
        top = QHBoxLayout()
        top.setSpacing(6)
        lbl = QLabel(label)
        lbl.setStyleSheet("font-weight: bold;" if not information
                          else f"color: {theme.TEXT_DIM};")
        lbl.setWordWrap(True)
        top.addWidget(lbl, 1)
        # « non évaluable » n'est pas « non conforme » : un calcul qui n'a pas
        # abouti ne doit pas se lire comme un verdict
        if not evaluable:
            top.addWidget(_pill("NON ÉVALUABLE", "todo"), 0,
                          Qt.AlignmentFlag.AlignRight)
        elif not information:
            top.addWidget(_pill("CONFORME" if ok else "NON CONFORME",
                                "ok" if ok else "warn"), 0,
                          Qt.AlignmentFlag.AlignRight)
        col.addLayout(top)
        if detail:
            d = QLabel(detail)
            d.setObjectName("hint")
            d.setWordWrap(True)
            # « 20.000 <= 27.73 deg » : un chevron suffit à faire deviner du
            # texte riche à Qt, qui avalerait alors le seuil comme une balise
            d.setTextFormat(Qt.TextFormat.PlainText)
            col.addWidget(d)
        self.criteria_box.addWidget(w)
