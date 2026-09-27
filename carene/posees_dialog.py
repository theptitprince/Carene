# -*- coding: utf-8 -*-
"""La liste des charges posées — dans sa propre fenêtre.

Elle encombrait le plan alors qu'on ne la consulte que par moments : pour
vérifier une position au centimètre, pour retrouver un colis, pour corriger un
poids. Elle s'ouvre donc à la demande, et se referme.

Le tableau et le plan restent synchronisés dans les deux sens : choisir une
ligne éclaire le colis, choisir un colis éclaire la ligne.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from . import theme
from .manifest_panel import _pastille

COLS = ["Pont", "Cale", "", "Charge", "X m", "Y m", "Rot.", "Niv.", "Poids t",
        "Port", "Origine"]
(C_PONT, C_CALE, C_COUL, C_NOM, C_X, C_Y, C_ROT, C_NIV, C_POIDS, C_PORT,
 C_ORIGINE) = range(11)
EDITABLES = {C_NOM, C_X, C_Y, C_ROT, C_NIV, C_POIDS, C_PORT}


class PoseesDialog(QDialog):
    """Les charges posées sur le pont courant."""

    def __init__(self, win, panel, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.panel = panel
        self._rows = []
        self._loading = False
        self.setWindowTitle("Charges posées")
        self.resize(900, 620)
        self.setModal(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        self.titre = QLabel("")
        self.titre.setObjectName("cardTitle")
        root.addWidget(self.titre)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(C_NOM, QHeaderView.ResizeMode.Stretch)
        for c in range(len(COLS)):
            if c != C_NOM:
                head.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(C_COUL, 26)
        self.table.setColumnWidth(C_PONT, 118)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.itemChanged.connect(self._on_edit)
        self.table.itemSelectionChanged.connect(self._on_select)
        root.addWidget(self.table, 1)

        row = QHBoxLayout()
        b_del = QPushButton("Retirer la sélection")
        b_del.setProperty("ghost", "1")
        b_del.clicked.connect(self._retirer)
        b_rot = QPushButton("Tourner")
        b_rot.setProperty("ghost", "1")
        b_rot.clicked.connect(self._tourner)
        row.addWidget(b_del)
        row.addWidget(b_rot)
        row.addStretch(1)
        self.lbl = QLabel("")
        self.lbl.setStyleSheet("font-weight: bold;")
        row.addWidget(self.lbl)
        b_close = QPushButton("Fermer")
        b_close.setProperty("accent", "1")
        b_close.clicked.connect(self.accept)
        row.addWidget(b_close)
        root.addLayout(row)

    # ------------------------------------------------------------- rendu
    def refresh(self):
        vue = self.panel.view
        self._loading = True
        self.table.setUpdatesEnabled(False)
        try:
            # TOUT le navire, pas seulement le pont affiché : c'est la liste
            # de ce qui est à bord, elle doit dire où chaque colis se trouve
            cond = self.win.condition
            lots = {m.lot_id: m for m in cond.manifeste}
            self._rows = []
            for deck in self.win.project.sorted_decks():
                for cap in deck.capacities:
                    for pl in cond.placements.get(cap.code) or []:
                        self._rows.append((pl, cap, deck))
            self.table.setRowCount(len(self._rows))
            poids = 0.0
            n_probs = 0
            for r, (pl, cap, deck) in enumerate(self._rows):
                lot = lots.get(pl.lot_id)
                if pl.est_materiel_bord:
                    # ce n'est pas de la marchandise : ni lot, ni manifeste,
                    # ni « reste » — c'est un engin qui appartient au navire
                    origine = "matériel du bord"
                elif lot is not None and getattr(lot, "hors_manifeste", False):
                    origine = "charge du bord"
                else:
                    origine = lot.nom if lot is not None else "hors manifeste"
                vals = [deck.name, cap.code, "", pl.nom, f"{pl.x:.2f}", f"{pl.y:.2f}",
                        "90°" if pl.rot else "0°", str(pl.niveaux),
                        f"{pl.poids_t:g}", pl.port_dechargement or "—", origine]
                # ce qui ne va pas (trop haut, trop lourd, chevauche…) se lit
                # ici aussi, en rouge — la liste sert à vérifier, pas
                # seulement à retrouver
                raisons = vue.raisons(pl, cap)
                n_probs += bool(raisons)
                for c, v in enumerate(vals):
                    item = QTableWidgetItem(v)
                    if c not in EDITABLES:
                        item.setFlags(Qt.ItemFlag.ItemIsEnabled
                                      | Qt.ItemFlag.ItemIsSelectable)
                    if c == C_COUL:
                        # le code couleur du plan, en pastille : le nom reste
                        # lisible, et la couleur se voit même sélectionnée
                        item.setIcon(_pastille(vue.couleur_de(pl).name()))
                        item.setToolTip(f"Couleur de « {pl.nom} » sur le plan.")
                    elif c == C_NIV:
                        item.setToolTip(
                            f"Exemplaires empilés — stack ×{pl.gerbable_max}"
                            + (" (non empilable)" if pl.gerbable_max <= 1 else "")
                            + f", hauteur de la pile {pl.hauteur_totale_m:.2f} m.")
                    if raisons:
                        item.setForeground(QColor(theme.DANGER))
                        item.setToolTip(" ; ".join(raisons))
                    self.table.setItem(r, c, item)
                poids += pl.poids_total_t
            for c in range(len(COLS)):
                if c != C_NOM:
                    self.table.resizeColumnToContents(c)
            self.titre.setText("CHARGES POSÉES — tout le navire")
            self.lbl.setText(
                f"{len(self._rows)} charge(s) · {poids:.2f} t"
                + (f" · <span style='color:{theme.DANGER}'>{n_probs} en rouge</span>"
                   if n_probs else ""))
        finally:
            self.table.setUpdatesEnabled(True)
            self._loading = False
        self.suivre_selection()

    def suivre_selection(self):
        """La sélection du plan se retrouve dans le tableau."""
        vue = self.panel.view
        self._loading = True
        try:
            self.table.clearSelection()
            for r, (pl, _cap, _d) in enumerate(self._rows):
                if pl in vue.selection:
                    self.table.selectRow(r)
        finally:
            self._loading = False

    # ------------------------------------------------------------- édition
    def _on_select(self):
        if self._loading:
            return
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        vue = self.panel.view
        # une charge d'un autre pont ne peut pas être sélectionnée sur ce
        # plan-ci : on saute au pont où elle est posée
        choisis = [self._rows[r] for r in rows if 0 <= r < len(self._rows)]
        if choisis and choisis[0][2] is not vue.deck:
            self.panel.choisir_pont(choisis[0][2])
            vue = self.panel.view
        vue.set_selection([pl for pl, _c, d in choisis if d is vue.deck])
        vue.update()

    def _on_edit(self, item):
        if self._loading:
            return
        r, c = item.row(), item.column()
        if r >= len(self._rows):
            return
        pl, cap, deck = self._rows[r]
        vue = self.panel.view
        txt = item.text().strip()
        # la charge peut être sur un autre pont, ou hors du zoom : on vient
        # sur son pont entier avant de la modifier, sinon `appliquer` ne la
        # retrouverait pas sur le plan affiché
        if c in (C_X, C_Y, C_ROT) and (deck is not vue.deck
                                        or vue.zoom_hold is not None):
            self.panel.choisir_pont(deck)
            vue = self.panel.view
        if c == C_NOM:
            pl.nom = txt or pl.nom
        elif c in (C_X, C_Y):
            try:
                v = float(txt.replace(",", "."))
            except ValueError:
                self.refresh()
                return
            vue.appliquer(pl, **{"x" if c == C_X else "y": v})
        elif c == C_ROT:
            vue.appliquer(pl, rot=90 if txt.startswith("9") else 0)
        elif c == C_NIV:
            self.panel._changer_niveaux(pl, cap, txt)
        elif c == C_POIDS:
            self.panel._changer_poids(pl, txt)
        elif c == C_PORT:
            pl.port_dechargement = "" if txt in ("", "-", "—") else txt
        self.refresh()
        vue.update()
        self.panel.changed.emit()

    def _retirer(self):
        self._on_select()
        n = self.panel.view.retirer_selection()
        self.refresh()
        if n:
            self.lbl.setText(f"{n} charge(s) retirée(s).")

    def _tourner(self):
        self._on_select()
        self.panel.view.tourner_selection()
        self.refresh()
