# -*- coding: utf-8 -*-
"""Panneau « Condition » : le récapitulatif de ce qui est embarqué.

Les deux saisies ont leur propre onglet au centre — le relevé des liquides et
le plan de chargement. Ce panneau ne les duplique pas : il **totalise**, et
n'édite que ce qui n'a pas d'autre place, à savoir le manifeste (ce qu'il reste
à embarquer) et les poids divers (équipage, vivres, colis hors plan).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .saisie import DelegueSansTiret
from .condition_model import ExtraWeight
from .core.cargo_model import ManifestLine


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


def _table(cols, widths):
    t = QTableWidget(0, len(cols))
    t.setHorizontalHeaderLabels(cols)
    head = t.horizontalHeader()
    head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for c, w in enumerate(widths, start=1):
        head.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
        t.setColumnWidth(c, w)
    t.verticalHeader().setVisible(False)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.setMinimumHeight(84)
    t.setWordWrap(False)
    # « — » (port, cale imposée vides) s'efface quand on saisit (D-89)
    t.setItemDelegate(DelegueSansTiret(t))
    return t


class ConditionPanel(QWidget):
    """Récapitulatif de la condition + manifeste + poids divers."""

    changed = Signal()
    hold_activated = Signal(object)

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self._loading = False

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setContentsMargins(9, 8, 9, 9)
        root.setSpacing(12)
        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # --- navire lège
        frame, lay = _card("Navire lège")
        self.chk_lege = QCheckBox("Inclure le navire lège")
        self.chk_lege.setChecked(True)
        self.chk_lege.stateChanged.connect(self._on_lege)
        lay.addWidget(self.chk_lege)
        self.lbl_lege = QLabel("—")
        self.lbl_lege.setObjectName("hint")
        self.lbl_lege.setWordWrap(True)
        lay.addWidget(self.lbl_lege)
        root.addWidget(frame)

        # --- récapitulatif (lecture seule : la saisie est dans les onglets)
        frame, lay = _card("Récapitulatif")
        self.tbl_recap = _table(["Poste", "Poids t", "LCG"], [74, 58])
        self.tbl_recap.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tbl_recap.setMaximumHeight(150)
        lay.addWidget(self.tbl_recap)
        hint = QLabel("Les liquides et le chargement se saisissent dans les "
                      "onglets au centre.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        root.addWidget(frame)

        # --- manifeste : ce qu'il y a à embarquer, ET où on en est.
        # « Placé » compte les exemplaires posés dans les cales (empilement
        # compris), « Reste » dit ce qu'il faut encore rentrer — c'est la
        # colonne qu'on surveille pendant l'escale.
        frame, lay = _card("À embarquer (manifeste)")
        self.tbl_manif = _table(["Charge", "Qté", "Placé", "Reste", "Poids t",
                                 "Décharg.", "Cale"],
                                [40, 44, 44, 52, 60, 48])
        self.tbl_manif.setToolTip(
            "Qté : à embarquer · Placé/Reste : suivi de la pose · Poids : "
            "poids unitaire réel (refusé au-delà du maximum du type) · "
            "Décharg. : port de déchargement · Cale : imposée, ou au choix du solveur.")
        self.tbl_manif.itemChanged.connect(self._on_manif_edited)
        lay.addWidget(self.tbl_manif)
        row = QHBoxLayout()
        b_add = QPushButton("+ depuis le catalogue")
        b_add.setProperty("ghost", "1")
        b_add.clicked.connect(self.add_manifest_from_catalogue)
        b_cat = QPushButton("Catalogue…")
        b_cat.setProperty("ghost", "1")
        b_cat.setToolTip("Définir les types de charges du bord : palettes, "
                         "engins, colis particuliers — enregistrés avec le "
                         "navire.")
        b_cat.clicked.connect(self.open_catalogue)
        b_del = QPushButton("Supprimer")
        b_del.setProperty("ghost", "1")
        b_del.clicked.connect(lambda: self._del_row(self.tbl_manif))
        row.addWidget(b_add)
        row.addWidget(b_cat)
        row.addWidget(b_del)
        row.addStretch(1)
        lay.addLayout(row)
        self.lbl_manif = QLabel("")
        self.lbl_manif.setObjectName("hint")
        self.lbl_manif.setWordWrap(True)
        lay.addWidget(self.lbl_manif)
        root.addWidget(frame)

        root.addStretch(1)

    # ---------------------------------------------------------------- lecture
    @property
    def condition(self):
        return self.win.condition

    def refresh(self):
        self._loading = True
        try:
            self.chk_lege.setChecked(self.condition.inclure_lege)
            nav = getattr(self.win, "nav", None)
            if nav is not None:
                lege = nav.lege
                self.lbl_lege.setText(
                    f"{lege.get('masse_t', 0):.2f} t · "
                    f"LCG {lege.get('lcg_m', 0):.3f} m · "
                    f"VCG {lege.get('vcg_m', 0):.3f} m")
            else:
                self.lbl_lege.setText("Tables du navire non chargées.")
            self._refresh_recap()
            self._refresh_manifeste()

        finally:
            self._loading = False

    def _refresh_recap(self):
        """Poids et LCG par grand poste — la seule vue d'ensemble chiffrée."""
        nav = getattr(self.win, "nav", None)
        cond = self.condition
        postes = []
        if cond.inclure_lege and nav is not None:
            lege = nav.lege
            postes.append(("Lège", float(lege.get("masse_t", 0.0)),
                           float(lege.get("lcg_m", 0.0))))
        w = lm = 0.0
        for t in cond.tanks:
            # `ligne` rend déjà le poids à la densité du POINT quand elle est
            # relevée (voir TankFill.capacite_chargee) : le récapitulatif pèse
            # donc le produit embarqué, pas celui du dossier
            ligne = t.ligne(nav)
            if ligne:
                p = float(ligne["Poids_t"])
                w += p
                lm += p * float(ligne["LCG_m"])
        if w > 0:
            postes.append(("Liquides", w, lm / w))
        lignes = cond.hold_lines(self.win.project)
        if lignes:
            tw = sum(l[2] for l in lignes)
            tlm = sum(l[2] * l[3] for l in lignes)
            postes.append((f"Cales ({len(lignes)})", tw, tlm / tw))
        ew = sum(e.poids_t for e in cond.extras)
        if ew:
            elm = sum(e.poids_t * e.lcg_m for e in cond.extras)
            postes.append(("Poids divers", ew, elm / ew))

        self.tbl_recap.setRowCount(len(postes) + (1 if postes else 0))
        for r, (nom, poids, lcg) in enumerate(postes):
            for c, v in enumerate([nom, f"{poids:.2f}", f"{lcg:.2f}"]):
                self.tbl_recap.setItem(r, c, QTableWidgetItem(v))
        if postes:
            tot = sum(p for _n, p, _l in postes)
            mom = sum(p * l for _n, p, l in postes)
            r = len(postes)
            for c, v in enumerate(["TOTAL", f"{tot:.2f}",
                                   f"{mom / tot:.2f}" if tot else "—"]):
                item = QTableWidgetItem(v)
                item.setForeground(QColor(theme.ACCENT_DARK))
                self.tbl_recap.setItem(r, c, item)

    def _places_par_ligne(self):
        return self.condition.poses_par_type()

    def _repartis_sur_les_lignes(self):
        return self.condition.places_par_ligne()

    def _refresh_manifeste(self):
        attribue = self._repartis_sur_les_lignes()
        self.tbl_manif.setRowCount(len(self.condition.manifeste))
        reste_total = reste_poids = 0.0
        for r, m in enumerate(self.condition.manifeste):
            place = attribue[r]
            reste = m.quantite - place
            reste_total += max(0, reste)
            reste_poids += max(0, reste) * m.poids_t
            vals = [m.nom, str(m.quantite), str(place),
                    (f"{reste}" if reste > 0 else
                     ("✓" if reste == 0 else f"+{-reste}")),
                    f"{m.poids_t:g}", m.port_dechargement or "—",
                    m.cale_imposee or "—"]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c in (2, 3):
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled
                                  | Qt.ItemFlag.ItemIsSelectable)
                if c == 3:
                    if reste > 0:
                        item.setForeground(QColor(theme.WARN))
                    elif reste == 0:
                        item.setForeground(QColor(theme.OK))
                    else:
                        # plus posé que prévu : à vérifier, pas une réussite
                        item.setForeground(QColor(theme.DANGER))
                        item.setToolTip(f"{-reste} exemplaire(s) posé(s) de "
                                        "plus que le manifeste.")
                item.setToolTip(item.toolTip() or (
                    f"{m.nom} · {m.longueur_m:g}×{m.largeur_m:g}×{m.hauteur_m:g} m"
                    f" · {m.poids_t:g} t l'unité\nstack {m.gerbable_max}, "
                    + ("rotation permise" if m.rotation_permise else "sans rotation")
                    + "\nCale : " + (m.cale_imposee or "au choix du solveur")))
                self.tbl_manif.setItem(r, c, item)
        total = self.condition.poids_manifeste_t()
        nb = sum(m.quantite for m in self.condition.manifeste)
        if not nb:
            self.lbl_manif.setText("Rien à embarquer pour l'instant.")
        elif reste_total:
            self.lbl_manif.setText(
                f"Reste à embarquer : {reste_total:.0f} charge(s) · "
                f"{reste_poids:.1f} t (sur {nb} · {total:.1f} t prévues).")
        else:
            self.lbl_manif.setText(
                f"Manifeste complet : {nb} charge(s) · {total:.1f} t posées.")

    def _emit(self):
        if not self._loading:
            self.changed.emit()

    def _on_lege(self, state):
        self.condition.inclure_lege = bool(state)
        self._emit()

    def add_manifest_from_catalogue(self):
        from PySide6.QtWidgets import QInputDialog
        cat = getattr(self.win, "catalogue", None)
        if cat is None or not len(cat):
            return
        noms = [f"{t.code} · {t.nom}" for t in cat]
        choix, ok = QInputDialog.getItem(self, "Ajouter au manifeste",
                                         "Type de charge :", noms, 0, False)
        if not ok:
            return
        t = cat.get(choix.split(" · ")[0])
        if t is None:
            return
        qte, ok = QInputDialog.getInt(self, "Quantité",
                                      f"Combien de « {t.nom} » ?", 10, 1, 100000)
        if not ok:
            return
        # La hauteur du catalogue est facultative : quand elle manque, on la
        # demande plutôt que de laisser un 0 entrer dans la hauteur libre et
        # dans le VCG (D-36).
        hauteur = t.hauteur_m
        if not t.hauteur_renseignee:
            hauteur, ok = QInputDialog.getDouble(
                self, "Hauteur du lot",
                f"Hauteur d'un exemplaire de « {t.nom} », en mètres,\n"
                "chargement compris (elle sert à la hauteur libre et au VCG) :",
                1.0, 0.01, 20.0, 2)
            if not ok:
                return
        self.condition.manifeste.append(
            ManifestLine.from_type(t, quantite=qte, hauteur_m=hauteur))
        self._loading = True
        try:
            self._refresh_manifeste()
        finally:
            self._loading = False
        self._emit()

    def _on_manif_edited(self, item):
        if self._loading:
            return
        r, c = item.row(), item.column()
        if r >= len(self.condition.manifeste):
            return
        m = self.condition.manifeste[r]
        txt = item.text().strip()
        if c == 0:
            m.nom = txt or m.nom
        elif c == 1:
            try:
                m.quantite = max(0, int(float(txt.replace(",", "."))))
            except ValueError:
                pass
        elif c == 4:
            try:
                val = float(txt.replace(",", "."))
            except ValueError:
                val = 0.0
            if val > 0:
                cat = getattr(self.win, "catalogue", None)
                t = cat.get(m.type_code) if (cat is not None and m.type_code) else None
                refus = t.poids_refuse(val) if t is not None else None
                if refus:
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(self, "Poids refusé", refus + ".")
                else:
                    m.poids_t = val
        elif c == 5:
            m.port_dechargement = "" if txt in ("", "-", "—") else txt
            # le port suit le LOT, pas le type (deux lots du même type
            # peuvent débarquer à deux escales)
            cle = m.type_code or m.nom
            for lst in self.condition.placements.values():
                for pl in lst:
                    if pl.lot_id == m.lot_id or (
                            not pl.lot_id and (pl.type_code or pl.nom) == cle):
                        pl.port_dechargement = m.port_dechargement
        elif c == 6:
            m.cale_imposee = "" if txt in ("", "-", "—") else txt.upper()
        self._loading = True
        try:
            self._refresh_manifeste()
        finally:
            self._loading = False
        self._emit()

    def open_catalogue(self):
        """Définir les types de charges du bord, enregistrés avec le navire."""
        from .catalogue_dialog import CatalogueDialog
        cat = getattr(self.win, "catalogue", None)
        if cat is None:
            from .core.cargo_model import Catalogue
            cat = Catalogue.load(getattr(self.win, "ship_folder", lambda: "")()
                                 if callable(getattr(self.win, "ship_folder",
                                                     None)) else "")
        dlg = CatalogueDialog(cat, self)
        dlg.exec()
        # la boîte modifie le catalogue en place, « Fermer » ou non : ce qui
        # a été saisi est enregistré quoi qu'il en soit
        from . import app_paths
        try:
            cat.save(app_paths.ship_folder())
        except OSError as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Catalogue",
                                f"Le catalogue n'a pas pu être enregistré : {e}")
        self.win.catalogue = cat
        self._loading = True
        try:
            self._refresh_manifeste()
        finally:
            self._loading = False

    def _del_row(self, table):
        """Supprime la ligne choisie du manifeste."""
        rows = sorted({i.row() for i in table.selectedIndexes()}, reverse=True)
        for r in rows:
            if 0 <= r < len(self.condition.manifeste):
                del self.condition.manifeste[r]
        if rows:
            self._loading = True
            try:
                self._refresh_manifeste()
            finally:
                self._loading = False
            self._emit()

