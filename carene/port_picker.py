# -*- coding: utf-8 -*-
"""Choisir une escale : le champ unique, partout où l'on demande un port.

Le bord tapait « Pointe-à-Pitre » à la main dans chaque ligne de manifeste et
dans chaque point du journal. Au bout de trois escales il y avait trois
orthographes, et le pointage de déchargement sortait deux feuilles pour un
seul quai. Ici on tape trois lettres et on **choisit** :

- les **escales du navire** d'abord — sa ligne, celles qu'il retrouve ;
- puis le **monde** : les 17 573 ports du UN/LOCODE livrés avec le logiciel.
  On ne sait pas quel sera le prochain contrat (les mots du capitaine :
  « mondial hein ! »), alors la recherche ne s'arrête pas aux escales déjà
  faites.

Ce qui est **enregistré est le NOM** du port (« Le Havre »), pas son étiquette :
c'est ce nom qui est dans `port_chargement`, `port_dechargement` et
`Point.lieu`, et c'est lui qu'on relit dans un fichier vieux de deux ans. Le
code se lit à côté du champ et dans la liste déroulante, jamais dans le modèle.

Et si l'officier tape un nom que personne ne connaît — un quai, un mouillage,
un port que la CEE-ONU ignore — **on le garde tel quel**. Une liste ne doit
jamais faire perdre ce qu'un homme a écrit.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCompleter,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import ports as _ports
from .ports import EN_MER, Port, Ports

# Rôles portés par chaque proposition : ce qu'on écrira dans le modèle (le
# nom), et de quoi compléter la liste du bord quand on choisit un port du monde.
ROLE_NOM = int(Qt.ItemDataRole.UserRole)
ROLE_PORT = int(Qt.ItemDataRole.UserRole) + 1

# Les deux intertitres de la liste des propositions. Ce ne sont pas des
# escales : ils ne se choisissent pas (voir `_titre`).
TITRE_BORD = "— Escales du navire —"
TITRE_MONDE = "— Ports du monde (UN/LOCODE) —"

# En dessous, on ne va pas chercher dans le monde : une seule lettre rendrait
# des centaines de ports sans rapport, et la liste du bord suffit à ce
# stade — c'est elle qu'on emploie neuf fois sur dix.
MINI_MONDE = 2
# Ce qu'on montre : au-delà, la liste ne se lit plus, il faut taper une lettre
# de plus.
LIMITE = 40


def libelle(port):
    """Ce qu'on lit dans la liste : « FRLEH — Le Havre · FRANCE »."""
    texte = port.etiquette
    return f"{texte} · {port.pays}" if port.pays else texte


def nom_depuis_libelle(texte):
    """Le nom du port dans ce qui est écrit dans le champ.

    Le champ contient normalement le seul nom ; mais un choix pris à la souris
    y dépose parfois l'étiquette entière (« FRLEH — Le Havre · FRANCE »), et un
    officier peut très bien recopier une étiquette lue ailleurs. On en retire
    le nom, sans jamais rendre une chaîne vide : ce qui n'est pas reconnu est
    rendu tel quel."""
    t = (texte or "").strip()
    if "—" in t:
        t = t.partition("—")[2].strip() or t
    if " · " in t:
        t = t.partition(" · ")[0].strip() or t
    return t


class PortPicker(QWidget):
    """Le champ « port » : on tape, on choisit, le code s'affiche à côté.

    Il se conduit comme la liste déroulante qu'il remplace — `setCurrentText`,
    `currentText`, `setEnabled` — et ajoute `valeur()`, qui rend le **nom**
    normalisé : c'est lui qui va dans le modèle.
    """

    # le nom retenu a changé (frappe ou choix) — même signature qu'un
    # `currentTextChanged` de QComboBox, pour se brancher là où il l'était
    changed = Signal(str)

    def __init__(self, parent=None, win=None, liste=None, dossier="",
                 en_mer=False, placeholder="port ou code (FRLEH, Le Havre…)"):
        super().__init__(parent)
        self.win = win
        self._liste = liste
        self._dossier = dossier
        self.en_mer = en_mer
        self._garde = False          # évite l'aller-retour signal → champ → signal

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo.lineEdit().setPlaceholderText(placeholder)
        self.combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setToolTip(
            "Tapez trois lettres du nom ou le code UN/LOCODE : les escales du "
            "navire viennent d'abord, puis tous les ports du monde.\n"
            "Un nom que la liste ne connaît pas est conservé tel quel.")
        lay.addWidget(self.combo, 1)
        self.lbl_code = QLabel("")
        self.lbl_code.setObjectName("hint")
        self.lbl_code.setMinimumWidth(64)
        self.lbl_code.setToolTip("Le code UN/LOCODE de l'escale choisie. "
                                 "Le manifeste, lui, retient le nom.")
        lay.addWidget(self.lbl_code)

        # La liste des propositions est la NÔTRE : le complèteur affiche ce
        # qu'on lui donne (mode « sans filtre ») au lieu de filtrer les entrées
        # du menu déroulant — c'est ainsi qu'on peut y mettre le monde entier
        # sans charger la liste déroulante de 17 573 lignes.
        self.modele = QStandardItemModel(self)
        self.completeur = QCompleter(self.modele, self)
        self.completeur.setCompletionMode(
            QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.completeur.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completeur.setMaxVisibleItems(14)
        # posé sur le champ de saisie et non sur la QComboBox : celle-ci
        # rebranche sinon son propre choix sur SES entrées, et remet dans le
        # champ la ligne de menu au lieu du nom du port
        self.combo.lineEdit().setCompleter(self.completeur)
        self.completeur.activated[str].connect(self._on_choix)
        self.combo.lineEdit().textEdited.connect(self._on_frappe)
        self.combo.currentTextChanged.connect(self._on_texte)
        self.combo.lineEdit().editingFinished.connect(self._normaliser)

        self.recharger()

    # ------------------------------------------------------------- la liste
    @property
    def liste(self):
        """La liste des escales du navire (celle de la fenêtre si elle en a une)."""
        if self._liste is None and self.win is not None:
            self._liste = _ports.liste_du_bord(self.win)
        if self._liste is None:
            self._liste = Ports()
        return self._liste

    def set_liste(self, liste, dossier=None):
        self._liste = liste
        if dossier is not None:
            self._dossier = dossier
        self.recharger()

    def dossier(self):
        if self._dossier:
            return self._dossier
        return _ports.dossier_du_navire(self.win) if self.win is not None else ""

    def recharger(self):
        """Remplit le menu déroulant : les escales du navire, rien d'autre.

        Dérouler la flèche, c'est demander « où va-t-on d'habitude ? » — la
        réponse tient en dix lignes. Le monde, lui, se cherche en tapant."""
        texte = self.combo.currentText()
        self._garde = True
        try:
            self.combo.clear()
            self.combo.addItem("")
            if self.en_mer:
                self.combo.addItem(EN_MER)
            for p in self.liste:
                self.combo.addItem(libelle(p), p.nom)
            self.combo.setCurrentIndex(-1)
            self.combo.setEditText(texte)
        finally:
            self._garde = False
        self._maj_code()

    # ------------------------------------------------------- les valeurs
    def valeur(self):
        """Le **nom** de l'escale à enregistrer dans le modèle.

        Normalisé par la liste du bord quand elle reconnaît l'escale (les trois
        orthographes de Pointe-à-Pitre rendent le même nom), rendu tel quel
        sinon — on ne perd jamais ce que l'officier a écrit."""
        texte = nom_depuis_libelle(self.combo.currentText())
        if not texte:
            return ""
        if _ports.meme_port(texte, EN_MER):
            return EN_MER
        return self.liste.nom_de(texte)

    def set_valeur(self, nom):
        """Pose un nom dans le champ, sans réveiller les signaux d'édition."""
        self._garde = True
        try:
            self.combo.setCurrentText(nom or "")
        finally:
            self._garde = False
        self._maj_code()

    # compatibilité avec la QComboBox qu'il remplace ------------------------
    def currentText(self):
        return self.valeur()

    def setCurrentText(self, texte):
        self.combo.setCurrentText(texte or "")

    def setPlaceholderText(self, texte):
        self.combo.lineEdit().setPlaceholderText(texte)

    def setFocus(self, *a):
        self.combo.setFocus(*a)

    # ------------------------------------------------------------- frappe
    def propositions(self):
        """Les libellés actuellement proposés (intertitres compris)."""
        return [self.modele.item(r).text() for r in range(self.modele.rowCount())]

    def ports_proposes(self):
        """Les ports actuellement proposés, sans les intertitres."""
        return [self.modele.item(r).data(ROLE_PORT)
                for r in range(self.modele.rowCount())
                if self.modele.item(r).data(ROLE_PORT) is not None]

    def _titre(self, texte):
        it = QStandardItem(texte)
        it.setFlags(Qt.ItemFlag.NoItemFlags)      # un intertitre ne se choisit pas
        return it

    def _proposition(self, port):
        it = QStandardItem(libelle(port))
        it.setData(port.nom, ROLE_NOM)
        it.setData(port, ROLE_PORT)
        return it

    def remplir(self, filtre):
        """Compose la liste des propositions pour ce qui est tapé."""
        filtre = (filtre or "").strip()
        self.modele.clear()
        if not filtre:
            return
        bord = self.liste.chercher(filtre)
        if self.en_mer and _ports._cle_nom(filtre) in _ports._cle_nom(EN_MER):
            self.modele.appendRow(self._proposition(Port(nom=EN_MER)))
        if bord:
            self.modele.appendRow(self._titre(TITRE_BORD))
            for p in bord[:LIMITE]:
                self.modele.appendRow(self._proposition(p))
        if len(filtre) < MINI_MONDE:
            return
        connus = {_ports._cle_nom(p.nom) for p in bord}
        monde = [p for p in _ports.chercher_partout(filtre, None, LIMITE)
                 if _ports._cle_nom(p.nom) not in connus]
        if monde:
            self.modele.appendRow(self._titre(TITRE_MONDE))
            for p in monde:
                self.modele.appendRow(self._proposition(p))

    def _on_frappe(self, texte):
        self.remplir(texte)
        self._maj_code()
        if self.modele.rowCount():
            self.completeur.complete()
        self.changed.emit(self.valeur())

    def _on_texte(self, _texte):
        """Le champ a changé autrement qu'à la frappe (menu déroulant, code)."""
        if self._garde:
            return
        self._maj_code()
        self.changed.emit(self.valeur())

    def _on_choix(self, texte):
        """Une proposition a été prise : le champ reçoit le NOM, pas l'étiquette.

        Un port du monde choisi ici entre du même coup dans la liste du navire :
        c'est une escale de sa ligne à partir de maintenant, avec son code."""
        port = next((p for p in self.ports_proposes() if libelle(p) == texte), None)
        nom = port.nom if port is not None else nom_depuis_libelle(texte)
        if port is not None and port.nom != EN_MER:
            self.retenir(port)
        self._garde = True
        try:
            self.combo.setEditText(nom)
        finally:
            self._garde = False
        self._maj_code()
        self.changed.emit(self.valeur())

    def _normaliser(self):
        """À la sortie du champ : l'étiquette redevient un nom."""
        nom = self.valeur()
        if nom != self.combo.currentText():
            self._garde = True
            try:
                self.combo.setEditText(nom)
            finally:
                self._garde = False
        self._maj_code()

    def retenir(self, port):
        """Range dans la liste du navire une escale prise dans le monde, et
        l'enregistre — la liste des escales se remplit à l'usage.

        Un échec d'écriture (clé retirée, dossier en lecture seule) ne doit
        surtout pas empêcher de composer un manifeste : l'escale reste en
        mémoire pour la session."""
        if self.liste.trouver(port.code or port.nom) is not None:
            return None
        ajoute = self.liste.ajouter(Port(nom=port.nom, code=port.code,
                                         pays=port.pays, source=port.source))
        dossier = self.dossier()
        if dossier and os.path.isdir(dossier):
            try:
                self.liste.save(dossier)
            except OSError:                     # pragma: no cover
                pass
        self.recharger()
        return ajoute

    def _maj_code(self):
        texte = nom_depuis_libelle(self.combo.currentText())
        if not texte:
            self.lbl_code.setText("")
            return
        if _ports.meme_port(texte, EN_MER):
            self.lbl_code.setText("hors port")
            return
        p = self.liste.trouver(texte)
        if p is None:
            self.lbl_code.setText("nouvelle escale")
        elif p.code:
            self.lbl_code.setText(p.code)
        else:
            self.lbl_code.setText("sans code")


class PortDelegate(QStyledItemDelegate):
    """Le même champ, dans une cellule de tableau : un clic sur « Chargé à »
    ouvre la recherche au lieu d'un champ de texte nu."""

    def __init__(self, parent=None, win=None, liste=None):
        super().__init__(parent)
        self.win = win
        self._liste = liste

    def createEditor(self, parent, option, index):
        return PortPicker(parent, win=self.win, liste=self._liste)

    def setEditorData(self, editor, index):
        texte = index.data(Qt.ItemDataRole.UserRole) or index.data(Qt.ItemDataRole.EditRole)
        editor.set_valeur(nom_depuis_libelle("" if texte in (None, "—") else str(texte)))

    def setModelData(self, editor, model, index):
        # le modèle reçoit le NOM : c'est lui qu'on relira dans deux ans
        model.setData(index, editor.valeur(), Qt.ItemDataRole.EditRole)

    def sizeHint(self, option, index):
        base = super().sizeHint(option, index)
        return QSize(max(base.width(), 150), base.height())


# ===================================================================== fenêtre
C_NOM, C_CODE, C_PAYS, C_SOURCE, C_NOTE = range(5)
COLS = ["Escale", "Code UN/LOCODE", "Pays", "Origine", "Note"]


class PortsDialog(QDialog):
    """Les escales du navire : sa ligne, avec les codes.

    À gauche ce que le navire connaît — on corrige un code, on ajoute un quai
    que la CEE-ONU ignore, on retire une escale qui n'est plus desservie. À
    droite la recherche mondiale : un clic et le port entre dans la liste avec
    son code officiel, jamais tapé de mémoire.

    La liste appartient au navire : elle est enregistrée dans son dossier.
    """

    changed = Signal()

    def __init__(self, win=None, parent=None, liste=None, dossier=""):
        super().__init__(parent or win)
        self.win = win
        self._liste = liste
        self._dossier = dossier
        self.setWindowTitle("Escales du navire — noms et codes")
        self.setModal(False)
        self.resize(980, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 10)
        root.setSpacing(8)
        intro = QLabel(
            "Les escales de la ligne du navire, avec leur code <b>UN/LOCODE</b>. "
            "C'est cette liste qui est proposée en tête partout où l'on demande "
            "un port. Un code vide reste vide : le logiciel n'en invente jamais. "
            "Cherchez à droite dans les 17 573 ports du monde pour en ajouter un "
            "avec son code officiel.")
        intro.setObjectName("hint")
        intro.setWordWrap(True)
        root.addWidget(intro)

        milieu = QHBoxLayout()
        milieu.setSpacing(12)

        gauche = QVBoxLayout()
        gauche.setSpacing(6)
        gauche.addWidget(QLabel("<b>Escales du navire</b>"))
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        head = self.table.horizontalHeader()
        for c in range(len(COLS)):
            head.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(C_NOTE, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._on_edit)
        gauche.addWidget(self.table, 1)
        ligne = QHBoxLayout()
        b_add = QPushButton("Ajouter une escale")
        b_add.setProperty("ghost", "1")
        b_add.setToolTip("Un quai, un mouillage, un port que la CEE-ONU ne "
                         "connaît pas : le code peut rester vide.")
        b_add.clicked.connect(self.ajouter_vide)
        b_del = QPushButton("Retirer")
        b_del.setProperty("ghost", "1")
        b_del.clicked.connect(self.retirer)
        b_imp = QPushButton("Importer UN/LOCODE…")
        b_imp.setProperty("ghost", "1")
        b_imp.setToolTip(
            "Le fichier officiel de la CEE-ONU (UNLOCODE CodeListPart*.csv), "
            "quand l'armement en a une édition plus récente que celle livrée "
            "avec Carène.")
        b_imp.clicked.connect(self.importer)
        ligne.addWidget(b_add)
        ligne.addWidget(b_del)
        ligne.addStretch(1)
        ligne.addWidget(b_imp)
        gauche.addLayout(ligne)
        milieu.addLayout(gauche, 3)

        droite = QVBoxLayout()
        droite.setSpacing(6)
        droite.addWidget(QLabel("<b>Chercher dans le monde</b>"))
        self.filtre = QLineEdit()
        self.filtre.setPlaceholderText("nom ou code : « pointe », « FRLEH »…")
        self.filtre.setClearButtonEnabled(True)
        self.filtre.textChanged.connect(self._chercher)
        droite.addWidget(self.filtre)
        self.monde = QTableWidget(0, 2)
        self.monde.setHorizontalHeaderLabels(["Code", "Port"])
        self.monde.verticalHeader().setVisible(False)
        self.monde.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.monde.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.monde.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.monde.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.monde.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.monde.itemDoubleClicked.connect(lambda _i: self.ajouter_du_monde())
        droite.addWidget(self.monde, 1)
        b_prendre = QPushButton("Ajouter aux escales du navire")
        b_prendre.setProperty("accent", "1")
        b_prendre.clicked.connect(self.ajouter_du_monde)
        droite.addWidget(b_prendre)
        milieu.addLayout(droite, 2)
        root.addLayout(milieu, 1)

        self.lbl_msg = QLabel("")
        self.lbl_msg.setObjectName("hint")
        self.lbl_msg.setWordWrap(True)
        bas = QHBoxLayout()
        bas.addWidget(self.lbl_msg, 1)
        b_close = QPushButton("Fermer")
        b_close.setProperty("accent", "1")
        b_close.clicked.connect(self.accept)
        bas.addWidget(b_close)
        root.addLayout(bas)

        self.refresh()

    # ------------------------------------------------------------- données
    @property
    def liste(self):
        if self._liste is None and self.win is not None:
            self._liste = _ports.liste_du_bord(self.win)
        if self._liste is None:
            self._liste = Ports()
        return self._liste

    def dossier(self):
        if self._dossier:
            return self._dossier
        return _ports.dossier_du_navire(self.win) if self.win is not None else ""

    def refresh(self):
        self._loading = True
        try:
            self.table.setRowCount(len(self.liste))
            for r, p in enumerate(self.liste):
                vals = [p.nom, p.code, p.pays, p.source, p.note]
                for c, v in enumerate(vals):
                    it = QTableWidgetItem(v)
                    if c == C_SOURCE:
                        it.setFlags(Qt.ItemFlag.ItemIsEnabled
                                    | Qt.ItemFlag.ItemIsSelectable)
                        it.setToolTip("« bord » : saisie ou déduite de l'usage. "
                                      "« UN/LOCODE » : reprise de la liste officielle.")
                    if c == C_NOTE and p.note:
                        it.setToolTip(p.note)
                    self.table.setItem(r, c, it)
        finally:
            self._loading = False
        self.lbl_msg.setText(
            f"{len(self.liste)} escale(s) — enregistrées dans le dossier du navire."
            if len(self.liste) else
            "Aucune escale : cherchez à droite, ou ajoutez un quai à la main.")

    def _chercher(self, texte):
        texte = (texte or "").strip()
        self.monde.setRowCount(0)
        if len(texte) < MINI_MONDE:
            return
        for p in _ports.chercher_partout(texte, self.liste, 200):
            r = self.monde.rowCount()
            self.monde.insertRow(r)
            for c, v in ((0, p.code), (1, f"{p.nom} · {p.pays}" if p.pays else p.nom)):
                it = QTableWidgetItem(v)
                it.setData(Qt.ItemDataRole.UserRole, p)
                self.monde.setItem(r, c, it)

    # ------------------------------------------------------------- édition
    def enregistrer(self):
        dossier = self.dossier()
        if not (dossier and os.path.isdir(dossier)):
            return None
        try:
            chemin = self.liste.save(dossier)
        except OSError as e:                    # pragma: no cover
            QMessageBox.warning(self, "Escales du navire",
                                f"La liste n'a pas pu être enregistrée : {e}")
            return None
        self.changed.emit()
        return chemin

    def _on_edit(self, item):
        if getattr(self, "_loading", False):
            return
        r, c = item.row(), item.column()
        if r >= len(self.liste):
            return
        p = self.liste.ports[r]
        txt = item.text().strip()
        avis = ""
        if c == C_NOM:
            if not txt:
                self.refresh()
                return                      # une escale sans nom n'existe pas
            p.nom = txt
        elif c == C_CODE:
            code = txt.upper()
            if code and not _ports.code_valide(code):
                # un code faux est pire qu'un code absent : il ferait passer
                # une escale pour vérifiée sur un papier signé
                avis = (f"« {code} » n'a pas la forme d'un UN/LOCODE (deux "
                        "lettres de pays, trois de localité : FRLEH). Le code "
                        "est laissé vide plutôt que faux.")
                p.code = ""
            else:
                p.code = code
        elif c == C_PAYS:
            p.pays = txt
        elif c == C_NOTE:
            p.note = txt
        self.refresh()
        self.enregistrer()
        if avis:
            self.lbl_msg.setText(avis)

    def ajouter_vide(self):
        self.liste.ajouter(Port(nom="Nouvelle escale", source="bord"))
        self.refresh()
        self.table.setCurrentCell(len(self.liste) - 1, C_NOM)
        self.table.editItem(self.table.item(len(self.liste) - 1, C_NOM))
        return self.liste.ports[-1]

    def retirer(self):
        r = self.table.currentRow()
        if not (0 <= r < len(self.liste)):
            return None
        p = self.liste.ports[r]
        self.liste.retirer(p.nom)
        self.refresh()
        self.enregistrer()
        self.lbl_msg.setText(f"« {p.nom} » retirée des escales du navire. "
                             "Les points et manifestes qui la nomment ne changent pas.")
        return p

    def ajouter_du_monde(self):
        r = self.monde.currentRow()
        it = self.monde.item(r, 0) if r >= 0 else None
        if it is None:
            return None
        p = it.data(Qt.ItemDataRole.UserRole)
        avant = len(self.liste)
        ajoute = self.liste.ajouter(Port(nom=p.nom, code=p.code, pays=p.pays,
                                         source=p.source))
        self.refresh()
        self.enregistrer()
        self.lbl_msg.setText(
            f"« {libelle(p)} » ajoutée aux escales du navire."
            if len(self.liste) > avant else
            f"« {p.nom} » était déjà dans la liste ; son code a été complété "
            "si besoin.")
        return ajoute

    def importer(self):
        """La liste officielle de la CEE-ONU, quand l'armement en a une édition
        plus récente que celle livrée avec Carène."""
        chemin, _f = QFileDialog.getOpenFileName(
            self, "Fichier UN/LOCODE de la CEE-ONU (CodeListPart*.csv)", "",
            "Liste UN/LOCODE (*.csv);;Tous les fichiers (*)")
        if not chemin:
            return None
        pays, ok = _demander_pays(self)
        if not ok:
            return None
        try:
            ajoutes, lus = self.liste.importer_unlocode(chemin, pays or None)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Importer UN/LOCODE",
                                f"Le fichier n'a pas pu être lu : {e}")
            return None
        self.refresh()
        self.enregistrer()
        self.lbl_msg.setText(
            f"{ajoutes} escale(s) ajoutée(s) sur {lus} localité(s) lue(s) "
            f"({os.path.basename(chemin)}) — seuls les ports maritimes sont retenus.")
        return ajoutes, lus


def _demander_pays(parent):
    """Quels pays importer : la liste entière fait plus de cent mille lignes,
    et un navire n'a pas besoin de l'Ouzbékistan. Vide = tout."""
    from PySide6.QtWidgets import QInputDialog
    texte, ok = QInputDialog.getText(
        parent, "Importer UN/LOCODE",
        "Codes pays à retenir, séparés par des virgules (FR, GP, MQ…).\n"
        "Laissez vide pour importer tous les pays du fichier.")
    if not ok:
        return None, False
    return [c.strip() for c in (texte or "").split(",") if c.strip()], True
