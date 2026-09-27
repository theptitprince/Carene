# -*- coding: utf-8 -*-
"""Les brouillons du plan de chargement — plusieurs plans, un seul validé.

Avant une escale on essaie : le lourd à fond de cale, la reprise du plan de
l'escale précédente, tout à l'avant pour l'assiette. On veut pouvoir garder
ces essais côte à côte, les comparer au tonnage et aux cales servies, en
reprendre un — et n'en **valider** qu'un à la fin.

Un brouillon est un plan de la **cargaison** : le manifeste, ce qui est posé
par cale, les épontilles en place. **Pas les liquides** : les sondes sont un
relevé, pas un choix, et il n'y a qu'une réalité à bord — elles appartiennent
au point. Charger un brouillon ne touche donc jamais aux caisses.

Sur un point **figé**, la fenêtre s'ouvre en lecture : on regarde ce qui avait
été essayé, on ne charge rien. Un point figé est une archive.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from . import theme
from .condition_model import lisible

# Ce qu'on lit pour comparer deux plans : combien de colis, combien de tonnes,
# dans quelles cales. Et la coche du plan retenu, en tête de ligne — c'est la
# première chose qu'on cherche en rouvrant la fenêtre.
C_VALIDE, C_NOM, C_CREE, C_MODIF, C_COLIS, C_POIDS, C_CALES = range(7)
COLS = ["✓", "Nom", "Enregistré le", "Modifié le", "Colis", "Tonnage",
        "Cales servies"]

TITRE = "Brouillons du plan de chargement"


def _poids(t):
    return f"{float(t):,.1f} t".replace(",", " ")


class BrouillonsDialog(QDialog):
    """Les brouillons du point courant : enregistrer, charger, valider."""

    def __init__(self, win, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.setWindowTitle(TITRE)
        self.resize(860, 480)
        self.setModal(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        self.titre = QLabel("")
        self.titre.setObjectName("cardTitle")
        root.addWidget(self.titre)
        self.lbl = QLabel("")
        self.lbl.setObjectName("hint")
        self.lbl.setWordWrap(True)
        root.addWidget(self.lbl)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        head = self.table.horizontalHeader()
        for c in range(len(COLS)):
            head.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        # le nom prend la place restante : c'est lui qu'on allonge (« reprise
        # du plan d'Alger, sans les fûts »), les autres colonnes sont courtes
        head.setSectionResizeMode(C_NOM, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemDoubleClicked.connect(lambda _i: self.charger())
        root.addWidget(self.table, 1)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.b_save = QPushButton("Enregistrer le plan en cours comme brouillon…")
        self.b_save.setProperty("accent", "1")
        self.b_save.setToolTip(
            "Met de côté le plan de chargement tel qu'il est : manifeste, colis posés, "
            "épontilles en place. Les relevés des caisses ne sont pas copiés — ils "
            "appartiennent au point.")
        self.b_save.clicked.connect(self.enregistrer)
        self.b_load = QPushButton("Charger")
        self.b_load.setProperty("ghost", "1")
        self.b_load.setToolTip(
            "Le plan en cours devient une copie de ce brouillon. Le plan actuel vous "
            "est proposé à l'enregistrement s'il n'est pas déjà rangé.")
        self.b_load.clicked.connect(self.charger)
        self.b_valid = QPushButton("Valider")
        self.b_valid.setProperty("ghost", "1")
        self.b_valid.setToolTip(
            "C'est le plan retenu : il est chargé ET marqué ✓. Les autres brouillons "
            "restent, jusqu'à « Ne garder que le validé ».")
        self.b_valid.clicked.connect(self.valider)
        self.b_ren = QPushButton("Renommer…")
        self.b_ren.setProperty("ghost", "1")
        self.b_ren.clicked.connect(self.renommer)
        self.b_del = QPushButton("Supprimer")
        self.b_del.setProperty("ghost", "1")
        self.b_del.clicked.connect(self.supprimer)
        self.b_menage = QPushButton("Ne garder que le validé")
        self.b_menage.setProperty("ghost", "1")
        self.b_menage.setToolTip(
            "Efface tous les brouillons sauf celui qui porte ✓ — quand le plan est "
            "arrêté et qu'on ne veut plus voir les essais.")
        self.b_menage.clicked.connect(self.ne_garder_que_le_valide)
        for b in (self.b_save, self.b_load, self.b_valid, self.b_ren, self.b_del):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.b_menage)
        root.addLayout(row)

        fin = QHBoxLayout()
        fin.addStretch(1)
        b_close = QPushButton("Fermer")
        b_close.setProperty("ghost", "1")
        b_close.clicked.connect(self.close)
        fin.addWidget(b_close)
        root.addLayout(fin)

        self.refresh()

    # --------------------------------------------------------------- lecture
    @property
    def condition(self):
        return self.win.condition

    @property
    def fige(self) -> bool:
        """Le point est-il une archive ? Alors on regarde, on ne touche pas."""
        p = getattr(self.win, "point", None)
        return p is not None and bool(p.fige)

    def refresh(self):
        cond = self.condition
        brouillons = cond.brouillons if cond is not None else []
        point = getattr(self.win, "point", None)
        self.titre.setText(TITRE + (f" — {point.titre}" if point is not None else ""))
        self.table.setRowCount(len(brouillons))
        for r, b in enumerate(brouillons):
            cales = ", ".join(b.cales_servies) or "—"
            vals = ["✓" if b.valide else "", b.nom, lisible(b.cree_le),
                    lisible(b.modifie_le), str(b.nb_colis), _poids(b.poids_t), cales]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c == C_VALIDE and b.valide:
                    item.setForeground(QColor(theme.OK))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if b.valide:
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                self.table.setItem(r, c, item)
            if b.note:
                self.table.item(r, C_NOM).setToolTip(b.note)
        if not brouillons:
            self.table.setRowCount(0)
        elif self.table.currentRow() < 0:
            self.table.selectRow(0)
        self._dire()
        self._activer()

    def _dire(self):
        """La phrase du haut : où l'on en est, et ce qui se passerait."""
        cond = self.condition
        n = len(cond.brouillons) if cond is not None else 0
        if self.fige:
            self.lbl.setText(
                "Ce point est <b>figé</b> : les brouillons se regardent, rien ne se "
                "charge. Pour reprendre l'un d'eux, ouvrez un nouveau point — il en "
                "sera la copie intégrale, brouillons compris.")
            return
        if not n:
            self.lbl.setText(
                "Aucun brouillon pour ce point. « Enregistrer le plan en cours comme "
                "brouillon… » met de côté le manifeste, les colis posés et les "
                "épontilles en place — <b>pas les relevés des caisses</b>, qui "
                "appartiennent au point.")
            return
        i = cond.index_du_brouillon_du_plan()
        if i is None:
            etat = ("Le <b>plan en cours</b> ne correspond à aucun brouillon : il vous "
                    "sera proposé à l'enregistrement avant d'en charger un autre.")
        else:
            etat = f"Le <b>plan en cours</b> est celui du brouillon « {cond.brouillons[i].nom} »."
        valide = cond.index_du_brouillon_valide()
        if valide is not None:
            etat += f" Plan retenu (✓) : « {cond.brouillons[valide].nom} »."
        self.lbl.setText(f"{n} brouillon(s). " + etat)

    def _activer(self):
        """Un point figé n'écrit plus rien : tous les boutons se taisent."""
        actif = not self.fige
        cond = self.condition
        choisi = self._index() is not None
        self.b_save.setEnabled(actif and cond is not None)
        for b in (self.b_load, self.b_valid, self.b_ren, self.b_del):
            b.setEnabled(actif and choisi)
        self.b_menage.setEnabled(
            actif and cond is not None and cond.index_du_brouillon_valide() is not None)

    def _index(self):
        """L'index du brouillon choisi dans la liste, ou None."""
        cond = self.condition
        r = self.table.currentRow()
        if cond is None or r < 0 or r >= len(cond.brouillons):
            return None
        return r

    # --------------------------------------------------------------- outils
    def _avertir(self, message):
        """Un avertissement qui ne doit pas bloquer : boîte en usage normal,
        barre d'état sinon (tests hors écran, captures). C'est le `_signaler`
        de la fenêtre principale, quand elle en a un."""
        signaler = getattr(self.win, "_signaler", None)
        if callable(signaler):
            signaler(TITRE, message)
        else:                                     # pragma: no cover - fenêtre postiche
            QMessageBox.information(self, TITRE, message)

    def _refuser_si_fige(self) -> bool:
        """Vrai si le point est figé — et on l'a dit."""
        if not self.fige:
            return False
        self._avertir(
            "Ce point est figé : c'est une archive, elle ne se réécrit pas.\n\n"
            "Ouvrez un nouveau point (Ctrl+N) — il sera la copie intégrale de "
            "celui-ci, brouillons compris — et chargez le brouillon là.")
        return True

    def _modifie(self, message=""):
        """Le point a changé : il est à enregistrer, et la fenêtre le montre."""
        self.win._dirty = True
        self.refresh()
        if message:
            self.win.statusBar().showMessage(message, 9000)

    def _appliquer_le_plan(self, message):
        """Après un chargement : les saisies et les chiffres repartent du plan.

        Le même geste que `open_manifeste` et `import_case` — le manifeste et
        les colis posés ont changé, donc la vue Chargement, le récapitulatif et
        le bandeau doivent tous repartir de la même condition."""
        self.win._dirty = True
        self.win._refresh_saisies()
        self.win.recompute()
        self.refresh()
        self.win.statusBar().showMessage(message, 12000)

    # -------------------------------------------------------------- actions
    def enregistrer(self):
        """Met le plan en cours de côté, sous un nom proposé mais libre."""
        cond = self.condition
        if cond is None or self._refuser_si_fige():
            return None
        nom, ok = QInputDialog.getText(
            self, "Enregistrer le plan en cours comme brouillon",
            "Nom du brouillon :", text=cond.nom_de_brouillon_propose())
        if not ok:
            return None
        b = cond.enregistrer_brouillon(nom)
        self._modifie(f"Plan en cours enregistré comme brouillon « {b.nom} » "
                      f"({b.nb_colis} colis, {_poids(b.poids_t)}).")
        # le brouillon qu'on vient de faire est celui qu'on veut voir choisi
        self.table.selectRow(len(cond.brouillons) - 1)
        self._activer()
        return b

    def _mettre_le_plan_de_cote(self) -> bool:
        """Avant de charger, proposer d'enregistrer le plan en cours.

        On ne le propose que s'il DIFFÈRE de tous les brouillons : reprendre
        deux fois de suite le même brouillon ne doit pas remplir la liste de
        copies. Faux si l'officier renonce à tout."""
        cond = self.condition
        if cond.index_du_brouillon_du_plan() is not None:
            return True
        if not self._confirmations():
            return True
        rep = QMessageBox.question(
            self, TITRE,
            "Le plan de chargement en cours n'est enregistré dans aucun brouillon.\n\n"
            "L'enregistrer avant de charger celui-ci ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Yes)
        if rep == QMessageBox.StandardButton.Cancel:
            return False
        if rep == QMessageBox.StandardButton.Yes:
            return self.enregistrer() is not None
        return True

    def _confirmations(self):
        """Peut-on poser une question bloquante ? Non dans les tests hors
        écran — même règle que la fenêtre principale."""
        f = getattr(self.win, "_confirmations_actives", None)
        return bool(f()) if callable(f) else True

    def charger(self):
        """Le plan en cours devient une copie du brouillon choisi."""
        i = self._index()
        if i is None or self._refuser_si_fige():
            return
        if not self._mettre_le_plan_de_cote():
            return
        # la liste a pu s'allonger d'un brouillon (le plan mis de côté) : le
        # brouillon choisi n'a pas bougé de place, il était déjà là avant
        b = self.condition.charger_brouillon(i)
        self._appliquer_le_plan(
            f"Brouillon « {b.nom} » chargé : {b.nb_colis} colis, {_poids(b.poids_t)}. "
            "Les relevés des caisses n'ont pas bougé.")

    def valider(self):
        """Le plan retenu : chargé ET marqué ✓."""
        i = self._index()
        if i is None or self._refuser_si_fige():
            return
        cond = self.condition
        if not self._mettre_le_plan_de_cote():
            return
        b = cond.valider_brouillon(i)
        self._appliquer_le_plan(
            f"Brouillon « {b.nom} » validé et chargé : c'est le plan retenu pour ce "
            "point. Les autres brouillons restent.")

    def renommer(self):
        i = self._index()
        if i is None or self._refuser_si_fige():
            return
        cond = self.condition
        nom, ok = QInputDialog.getText(self, "Renommer le brouillon",
                                       "Nom du brouillon :", text=cond.brouillons[i].nom)
        if ok and cond.renommer_brouillon(i, nom):
            self._modifie(f"Brouillon renommé « {cond.brouillons[i].nom} ».")

    def supprimer(self):
        i = self._index()
        if i is None or self._refuser_si_fige():
            return
        cond = self.condition
        b = cond.brouillons[i]
        if self._confirmations():
            rep = QMessageBox.question(
                self, TITRE,
                f"Supprimer le brouillon « {b.nom} » "
                f"({b.nb_colis} colis, {_poids(b.poids_t)}) ?"
                + ("\n\nC'est le plan validé." if b.valide else "")
                + "\n\nLe plan de chargement en cours n'est pas touché.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if rep != QMessageBox.StandardButton.Yes:
                return
        cond.supprimer_brouillon(i)
        self._modifie(f"Brouillon « {b.nom} » supprimé.")

    def ne_garder_que_le_valide(self):
        """Le ménage de fin d'escale : on efface les essais, on garde le plan."""
        cond = self.condition
        if cond is None or self._refuser_si_fige():
            return
        i = cond.index_du_brouillon_valide()
        if i is None:
            self._avertir(
                "Aucun brouillon n'est validé : rien ne dit lequel garder.\n\n"
                "Choisissez le plan retenu et cliquez « Valider ».")
            return
        garde = cond.brouillons[i].nom
        autres = len(cond.brouillons) - 1
        if not autres:
            self.win.statusBar().showMessage(
                f"« {garde} » est déjà le seul brouillon de ce point.", 6000)
            return
        if self._confirmations():
            rep = QMessageBox.question(
                self, TITRE,
                f"Effacer les {autres} brouillon(s) non validés et ne garder "
                f"que « {garde} » ?\n\nC'est définitif pour ce point.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if rep != QMessageBox.StandardButton.Yes:
                return
        n = cond.ne_garder_que_le_valide()
        self._modifie(f"{n} brouillon(s) effacés ; « {garde} » est le seul qui reste.")
