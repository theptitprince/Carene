# -*- coding: utf-8 -*-
"""Le catalogue des charges du bord : palettes, engins, colis particuliers.

Ces types appartiennent au NAVIRE (catalogue_charges.json dans son dossier),
pas à un chargement : on les définit une fois — dimensions, poids, empilement
(stack), rotation, couleur — et chaque manifeste s'en sert ensuite. Cette fenêtre les
gère ; la pose elle-même se fait sur le plan.

C'est un **tableau qui se tape**, dans l'esprit du manifeste : une ligne par
type, tout se corrige dans la cellule, sans formulaire. **Rien n'y est
verrouillé** : le catalogue livré avec le navire d'exemple est celui d'une démonstration,
et chaque bord fait le sien (D-36). La colonne « Origine » dit d'où viennent
les chiffres — c'est une information, pas une serrure.

La **hauteur est facultative** (colonne vide) : la longueur et la largeur d'une
palette sont fixées à sa construction, sa hauteur dépend de ce qu'on empile
dessus. Elle se précise alors au manifeste, lot par lot.

Le **débord** — ce qui dépasse de la palette, de chaque côté — se propose ici
et se règle au manifeste : c'est une dimension du LOT, pas du type (D-39).
Une palette EUR porte des fûts au carré ou des sacs de café qui sortent de
5 cm ; c'est la ligne du manifeste qui le sait.

Elle s'ouvre de partout où l'on en a besoin (vue Chargement, manifeste, menu
Navire, Ctrl+K) et reste ouverte pendant qu'on travaille : c'est une fenêtre,
pas une boîte modale. Ce qui y est saisi est enregistré avec le navire à
chaque modification (signal `changed`) et à la fermeture.
"""
from __future__ import annotations

import dataclasses

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QColorDialog,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from . import theme
from .saisie import DelegueSansTiret
from .core.cargo_model import CATEGORIES, CargoType, couleur_hex

COLS = ["Code", "Nom", "Catégorie", "L (m)", "l (m)", "h (m)", "Débord (m)",
        "Poids t", "Max t", "Stack", "Rot.", "Coul.", "Note", "Origine"]
(C_CODE, C_NOM, C_CAT, C_L, C_LARG, C_H, C_DEB, C_POIDS, C_MAX, C_GERB, C_ROT,
 C_COUL, C_NOTE, C_SRC) = range(14)
# TOUT se corrige, sur n'importe quel type : plus de verrouillage (D-36) —
# le CODE aussi, depuis D-69 (« dans le catalogue des charges, on devrait
# pouvoir éditer le code »). Il était fermé parce que les manifestes s'y
# réfèrent : ils SUIVENT désormais le changement (signal `code_renomme`, que
# la fenêtre principale reporte sur le manifeste et les colis posés du
# point ouvert). Les points archivés gardent l'ancien code, avec leurs
# propres dimensions — un manifeste porte les siennes, le type ne fait que
# les proposer (D-36).
EDITABLES_LIBRE = {C_CODE, C_NOM, C_CAT, C_L, C_LARG, C_H, C_DEB, C_POIDS, C_MAX,
                   C_GERB, C_ROT, C_COUL, C_NOTE, C_SRC}
AIDES_COLONNES = {
    C_CODE: "Identifiant du type. Il se corrige : le manifeste et les colis "
            "posés du point ouvert suivent ; les points archivés gardent "
            "l'ancien code, avec leurs propres dimensions.",
    C_L: "Longueur, le long de X quand la rotation vaut 0.",
    C_LARG: "Largeur, le long de Y quand la rotation vaut 0.",
    C_H: "Hauteur d'un exemplaire — FACULTATIVE : la hauteur d'une palette "
         "dépend de ce qu'on empile dessus. Vide (« — ») : elle se précise au "
         "manifeste, lot par lot.",
    C_DEB: "Ce qui dépasse de la palette, de chaque côté : 0,05 m = 5 cm "
           "tout autour. Compte pour la place occupée, jamais pour la charge "
           "au m² (le poids passe par la palette). Une proposition : le "
           "débord réel se règle au manifeste, lot par lot.",
    C_POIDS: "Poids par défaut d'un exemplaire ; le poids réel se tape au manifeste.",
    C_MAX: "Poids maximal d'un exemplaire (0 = sans limite) : au-delà, la "
           "saisie est refusée (D-8).",
    C_GERB: "Nombre d'exemplaires empilables (stack) — 1 = non empilable. Une "
            "proposition : le stack réel se précise au manifeste.",
    C_ROT: "Coché : le colis peut être posé tourné de 90°.",
    C_COUL: "Couleur des colis de ce type sur le plan. Clic : choisir ; "
            "« auto » (F2, ou taper le mot) : celle de la catégorie.",
    C_SRC: "D'où viennent les chiffres — une information, pas une contrainte : "
           "le type se modifie et se retire comme les autres.",
}


def _pastille(hexa, taille=13):
    pm = QPixmap(taille, taille)
    pm.fill(Qt.GlobalColor.transparent)
    from PySide6.QtGui import QPainter, QPen
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(hexa))
    p.setPen(QPen(QColor(theme.TEXT_DIM), 1.0))
    p.drawRoundedRect(1, 1, taille - 2, taille - 2, 3, 3)
    p.end()
    return QIcon(pm)


def _nombre(txt):
    return float(txt.strip().replace(",", ".").replace(" ", ""))


class _CategorieDelegate(QStyledItemDelegate):
    """La catégorie se choisit dans une liste, pas en la tapant : elle sert de
    repère de couleur et de tri, une faute de frappe y ferait un « Palete »."""

    def createEditor(self, parent, option, index):
        cb = QComboBox(parent)
        cb.addItems(CATEGORIES)
        return cb

    def setEditorData(self, editor, index):
        txt = index.data() or CATEGORIES[0]
        editor.setCurrentText(txt if txt in CATEGORIES else CATEGORIES[0])

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)


class CatalogueDialog(QDialog):
    """Créer, modifier, dupliquer, retirer les types de charges du catalogue —
    dans un tableau qui se tape en place."""

    # le catalogue a changé : la fenêtre principale enregistre et rafraîchit
    changed = Signal()
    code_renomme = Signal(str, str)      # (ancien code, nouveau code)
    # « Ajouter au manifeste » : (CargoType, quantité)
    ajouter_au_manifeste = Signal(object, int)

    def __init__(self, catalogue, parent=None, vers_manifeste=False):
        super().__init__(parent)
        self.catalogue = catalogue
        self.setWindowTitle("Catalogue des charges du bord")
        self.setModal(False)
        self.resize(1080, 540)
        self._loading = False
        # les types créés dans cette fenêtre : leur code reste corrigeable tant
        # qu'elle est ouverte — après, un manifeste peut s'y référer
        self._nouveaux = set()
        # avertissements de saisie (aussi relus par les tests, où aucune boîte
        # ne s'ouvre)
        self.avertissements = []

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 10)
        root.setSpacing(8)
        intro = QLabel(
            "Une ligne par type, tout se corrige dans la cellule : un clic, on "
            "tape, Entrée. Les types définis ici sont enregistrés avec le navire "
            "et servent à composer les manifestes ; modifier un type ne change "
            "pas les charges déjà posées. <b>Ce catalogue est le vôtre</b> : "
            "rien n'y est verrouillé, la colonne <b>Origine</b> ne fait que "
            "dire d'où viennent les chiffres. "
            "<b>h (m)</b> est facultative — la hauteur d'une palette dépend de "
            "ce qu'on empile dessus, elle se précise au manifeste. "
            "<b>Stack</b> : exemplaires empilables (stack), 1 = non empilable. "
            "<b>Débord (m)</b> : ce qui dépasse de la palette, de chaque côté "
            "— il compte pour la place occupée, jamais pour la charge au m².")
        intro.setObjectName("hint")
        intro.setWordWrap(True)
        root.addWidget(intro)

        haut = QHBoxLayout()
        self.filtre = QLineEdit()
        self.filtre.setPlaceholderText("Filtrer (code, nom, catégorie, origine)…")
        self.filtre.setClearButtonEnabled(True)
        self.filtre.textChanged.connect(self._recharger)
        haut.addWidget(self.filtre, 1)
        self.lbl_compte = QLabel("")
        self.lbl_compte.setObjectName("hint")
        haut.addWidget(self.lbl_compte)
        root.addLayout(haut)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        for c, aide in AIDES_COLONNES.items():
            self.table.horizontalHeaderItem(c).setToolTip(aide)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # un clic suffit pour taper (voir `_on_click`) ; les autres chemins
        # habituels — F2, double-clic, commencer à taper — restent ouverts
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed)
        # « — » (hauteur non renseignée) s'efface quand on saisit (D-89)
        self.table.setItemDelegate(DelegueSansTiret(self.table))
        self.table.setItemDelegateForColumn(C_CAT, _CategorieDelegate(self.table))
        self.table.setAlternatingRowColors(False)
        self.table.setWordWrap(False)
        head = self.table.horizontalHeader()
        head.setMinimumSectionSize(28)
        for c, w in ((C_CODE, 84), (C_NOM, 200), (C_CAT, 84), (C_L, 58),
                     (C_LARG, 58), (C_H, 58), (C_DEB, 74), (C_POIDS, 62),
                     (C_MAX, 58),
                     (C_GERB, 56), (C_ROT, 40), (C_COUL, 74), (C_SRC, 190)):
            head.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(c, w)
        head.setSectionResizeMode(C_NOTE, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._on_edited)
        self.table.cellClicked.connect(self._on_click)
        self.table.itemSelectionChanged.connect(self._sync_boutons)
        root.addWidget(self.table, 1)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.b_new = QPushButton("Nouveau")
        self.b_new.setProperty("accent", "1")
        self.b_new.setToolTip("Une ligne de plus, à remplir dans le tableau.")
        self.b_new.clicked.connect(self.nouveau)
        self.b_dup = QPushButton("Dupliquer")
        self.b_dup.setProperty("ghost", "1")
        self.b_dup.setToolTip("Un nouveau type à partir de celui-ci — le moyen "
                              "de décliner une variante sans retaper ses cotes.")
        self.b_dup.clicked.connect(self.dupliquer)
        self.b_del = QPushButton("Retirer")
        self.b_del.setProperty("ghost", "1")
        self.b_del.clicked.connect(self.retirer)
        for b in (self.b_new, self.b_dup, self.b_del):
            row.addWidget(b)
        self.b_manif = QPushButton("Ajouter au manifeste…")
        self.b_manif.setProperty("ghost", "1")
        self.b_manif.setToolTip("Une ligne de manifeste de ce type, avec la quantité demandée.")
        self.b_manif.clicked.connect(self._vers_manifeste)
        self.b_manif.setVisible(bool(vers_manifeste))
        row.addWidget(self.b_manif)
        row.addStretch(1)
        b_save = QPushButton("Enregistrer")
        b_save.setProperty("ghost", "1")
        b_save.setToolTip("Chaque modification est déjà enregistrée avec le "
                          "navire ; ce bouton force l'écriture.")
        b_save.clicked.connect(self.changed.emit)
        row.addWidget(b_save)
        b_close = QPushButton("Fermer")
        b_close.setProperty("accent", "1")
        b_close.clicked.connect(self.accept)
        row.addWidget(b_close)
        root.addLayout(row)
        self._recharger()

    # ------------------------------------------------------------- liste
    def _recharger(self, *_a):
        courant = self._selection()
        filtre = self.filtre.text().strip().lower()
        self._loading = True
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(0)
            n_total = 0
            for t in self.catalogue:
                n_total += 1
                if filtre and filtre not in " ".join(
                        (t.code, t.nom, t.categorie, t.source, t.note)).lower():
                    continue
                self._ligne(t)
                if courant is not None and t.code == courant.code:
                    self.table.selectRow(self.table.rowCount() - 1)
        finally:
            self.table.setUpdatesEnabled(True)
            self._loading = False
        self.lbl_compte.setText(
            f"{self.table.rowCount()} / {n_total} type(s)" if filtre
            else f"{n_total} type(s)")
        self._sync_boutons()

    def _ligne(self, t):
        r = self.table.rowCount()
        self.table.insertRow(r)
        vals = [t.code, t.nom, t.categorie, f"{t.longueur_m:g}",
                f"{t.largeur_m:g}",
                # hauteur facultative : « — » quand elle n'est pas renseignée,
                # pour qu'on voie qu'elle manque au lieu de lire un « 0 »
                f"{t.hauteur_m:g}" if t.hauteur_renseignee else "—",
                f"{t.debord_m:g}" if t.debord_m > 0 else "0",
                f"{t.poids_t:g}",
                f"{t.poids_max_t:g}" if t.poids_max_t > 0 else "0",
                str(max(1, t.gerbable_max)), "", t.couleur or "auto",
                t.note or "", t.source or ""]
        editables = EDITABLES_LIBRE
        for c, v in enumerate(vals):
            it = QTableWidgetItem(v)
            it.setData(Qt.ItemDataRole.UserRole, t.code)
            flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            if c == C_ROT:
                if c in editables:
                    flags |= Qt.ItemFlag.ItemIsUserCheckable
                it.setFlags(flags)
                # la case au milieu de sa colonne : sur 40 px, collée à
                # gauche, on croit qu'elle appartient à la colonne d'à côté
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                it.setCheckState(Qt.CheckState.Checked if t.rotation_permise
                                 else Qt.CheckState.Unchecked)
            elif c in editables:
                it.setFlags(flags | Qt.ItemFlag.ItemIsEditable)
            else:
                it.setFlags(flags)
            if c in (C_L, C_LARG, C_H, C_DEB, C_POIDS, C_MAX, C_GERB):
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                    | Qt.AlignmentFlag.AlignVCenter)
            if c == C_COUL:
                it.setIcon(_pastille(couleur_hex(t)))
                it.setToolTip(AIDES_COLONNES[C_COUL]
                              + ("" if t.couleur else "\nActuellement : couleur "
                                 f"de la catégorie « {t.categorie} »."))
            elif c == C_GERB:
                it.setToolTip("Non empilable (stack 1)" if t.gerbable_max <= 1
                              else f"Jusqu'à {t.gerbable_max} exemplaires empilés")
                if t.gerbable_max <= 1:
                    it.setForeground(QColor(theme.TEXT_DIM))
            elif c == C_MAX and t.poids_max_t <= 0:
                it.setForeground(QColor(theme.TEXT_DIM))
                it.setToolTip("Sans limite de poids")
            elif c == C_DEB and t.debord_m <= 0:
                it.setForeground(QColor(theme.TEXT_DIM))
                it.setToolTip("Rien ne dépasse de la palette.")
            elif c == C_H and not t.hauteur_renseignee:
                it.setForeground(QColor(theme.TEXT_DIM))
                it.setToolTip("Hauteur non renseignée : elle sera demandée à "
                              "l'ajout du lot au manifeste.")
            elif c in AIDES_COLONNES:
                it.setToolTip(AIDES_COLONNES[c])
            if c == C_NOM:
                f = it.font()
                f.setBold(True)
                it.setFont(f)
            self.table.setItem(r, c, it)
        return r

    def _code_de(self, r):
        it = self.table.item(r, C_CODE) if r >= 0 else None
        return None if it is None else it.data(Qt.ItemDataRole.UserRole)

    def _selection(self):
        code = self._code_de(self.table.currentRow())
        return None if code is None else self.catalogue.get(code)

    def _ligne_de(self, t):
        for r in range(self.table.rowCount()):
            if self._code_de(r) == t.code:
                return r
        return -1

    def _sync_boutons(self):
        t = self._selection()
        self.b_dup.setEnabled(t is not None)
        self.b_manif.setEnabled(t is not None)
        self.b_del.setEnabled(t is not None)

    # ------------------------------------------------------------- édition
    def _avertir(self, titre, texte):
        """Un refus de saisie se dit dans une boîte — sauf dans les tests, où
        il se lit dans `avertissements`."""
        self.avertissements.append(texte)
        app = QApplication.instance()
        if app is not None and app.property("carene_tests"):
            return
        QMessageBox.warning(self, titre, texte)

    def _on_click(self, r, c):
        """Un clic suffit : la cellule passe en saisie ; sur la pastille, le
        choix de couleur s'ouvre."""
        it = self.table.item(r, c)
        if it is None:
            return
        if c == C_COUL:
            self._choisir_couleur(r)
            return
        if it.flags() & Qt.ItemFlag.ItemIsEditable:
            self.table.editItem(it)

    def _choisir_couleur(self, r):
        t = self.catalogue.get(self._code_de(r))
        if t is None:
            return
        coul = QColorDialog.getColor(QColor(couleur_hex(t)), self,
                                     f"Couleur des colis « {t.nom or t.code} »")
        if coul.isValid():
            t.couleur = coul.name()
            self._recharger()
            self.changed.emit()

    def _on_edited(self, item):
        if self._loading:
            return
        r, c = item.row(), item.column()
        t = self.catalogue.get(self._code_de(r))
        if t is None:
            return
        txt = item.text().strip()
        try:
            ok = self._appliquer(t, c, txt, item)
        except ValueError:
            self._avertir("Saisie refusée",
                          f"« {txt} » n'est pas un nombre.")
            ok = False
        self._recharger()
        if ok:
            self.changed.emit()

    def _appliquer(self, t, c, txt, item):
        """Reporte une cellule dans le type ; False (avec message) si la valeur
        n'est pas acceptable. Les règles : dimensions et poids positifs, poids
        sous le maximum quand il y en a un, code unique, stack entier ≥ 1."""
        if c == C_CODE:
            code = txt.upper().replace(" ", "_")
            if not code:
                self._avertir("Code refusé", "Le code ne peut pas être vide.")
                return False
            autre = self.catalogue.get(code)
            if autre is not None and autre is not t:
                self._avertir("Code refusé",
                              f"Le code « {code} » est déjà celui de « {autre.nom} » : "
                              "chaque type a le sien.")
                return False
            ancien = t.code
            t.code = code
            if ancien and ancien != code:
                # ceux qui s'y réfèrent doivent suivre : c'est l'appelant qui
                # tient le manifeste et le plan (D-69)
                self.code_renomme.emit(ancien, code)
        elif c == C_NOM:
            t.nom = txt or t.nom
        elif c == C_CAT:
            t.categorie = txt if txt in CATEGORIES else t.categorie
        elif c == C_H:
            # La hauteur est la SEULE dimension facultative : « — », vide ou 0
            # veut dire « non renseignée », et le manifeste la demandera. Les
            # deux autres sont fixées à la construction du colis.
            if txt.lower() in ("", "—", "-", "0"):
                t.hauteur_m = 0.0
            else:
                v = _nombre(txt)
                if v < 0:
                    self._avertir("Hauteur refusée",
                                  "La hauteur ne peut pas être négative "
                                  "(vide ou 0 = non renseignée).")
                    return False
                t.hauteur_m = v
        elif c == C_DEB:
            # Le débord est une COTE, pas un réglage : négatif n'a pas de
            # sens, 0 veut dire « rien ne dépasse » (D-39).
            if txt.lower() in ("", "—", "-"):
                t.debord_m = 0.0
            else:
                v = _nombre(txt)
                if v < 0:
                    self._avertir("Débord refusé",
                                  "Le débord ne peut pas être négatif "
                                  "(0 = rien ne dépasse de la palette).")
                    return False
                t.debord_m = v
        elif c in (C_L, C_LARG):
            v = _nombre(txt)
            if v <= 0:
                self._avertir("Dimension refusée",
                              "Une dimension doit être strictement positive.")
                return False
            setattr(t, {C_L: "longueur_m", C_LARG: "largeur_m"}[c], v)
        elif c == C_POIDS:
            v = _nombre(txt)
            if v <= 0:
                self._avertir("Poids refusé", "Le poids doit être strictement positif.")
                return False
            refus = t.poids_refuse(v)
            if refus:
                self._avertir("Poids refusé", refus + ".")
                return False
            t.poids_t = v
        elif c == C_MAX:
            v = _nombre(txt)
            if v < 0:
                self._avertir("Poids maximal refusé",
                              "Le poids maximal ne peut pas être négatif "
                              "(0 = sans limite).")
                return False
            if v > 0 and t.poids_t > v + 1e-9:
                self._avertir("Poids maximal refusé",
                              f"Le poids par défaut ({t.poids_t:g} t) dépasserait ce "
                              f"maximum de {v:g} t : baissez d'abord le poids.")
                return False
            t.poids_max_t = v
        elif c == C_GERB:
            bas = txt.lower()
            if bas in ("non", "0", ""):
                n = 1
            else:
                n = int(_nombre(txt.split()[0]))
            if n < 1:
                self._avertir("Stack refusé",
                              "Le stack est un nombre d'exemplaires empilables, "
                              "1 au minimum (1 = non empilable).")
                return False
            t.gerbable_max = n
        elif c == C_ROT:
            t.rotation_permise = item.checkState() == Qt.CheckState.Checked
        elif c == C_COUL:
            if txt.lower() in ("", "auto", "—", "-"):
                t.couleur = ""
            else:
                coul = QColor(txt)
                if not coul.isValid():
                    self._avertir("Couleur refusée",
                                  f"« {txt} » n'est pas une couleur (#rrggbb), ni « auto ».")
                    return False
                t.couleur = coul.name()
        elif c == C_NOTE:
            t.note = txt
        elif c == C_SRC:
            # simple information : d'où viennent les chiffres. Elle se corrige
            # comme le reste — un bord qui reprend un type d'un manuel doit
            # pouvoir écrire lequel (D-36).
            t.source = txt
        else:
            return False
        return True

    # ------------------------------------------------------------- actions
    def _commencer(self, t, colonne):
        """Montre la ligne de `t` (le filtre est levé s'il la cachait) et met
        la cellule en saisie : une ligne neuve se remplit tout de suite."""
        if self.filtre.text():
            self.filtre.blockSignals(True)
            self.filtre.clear()
            self.filtre.blockSignals(False)
        self._recharger()
        r = self._ligne_de(t)
        if r >= 0:
            self.table.selectRow(r)
            self.table.setCurrentCell(r, colonne)
            self.table.scrollToItem(self.table.item(r, colonne))
            self.table.editItem(self.table.item(r, colonne))

    def nouveau(self):
        # hauteur laissée à 0 = non renseignée : on ne fabrique pas une cote
        # qui finirait par servir à un contrôle de hauteur libre ou à un VCG.
        t = CargoType(code=self.catalogue.unique_code("NOUVEAU"), nom="Nouveau type",
                      categorie=CATEGORIES[0], hauteur_m=0.0, source="bord")
        self.catalogue.add(t)
        self._nouveaux.add(id(t))
        self._commencer(t, C_CODE)
        self.changed.emit()

    def dupliquer(self):
        t = self._selection()
        if t is None:
            return
        copie = dataclasses.replace(t, source=f"d'après {t.code}")
        copie.code = self.catalogue.unique_code(t.code + "_2")
        copie.nom = f"{t.nom} (copie)"
        self.catalogue.add(copie)
        self._nouveaux.add(id(copie))
        self._commencer(copie, C_NOM)
        self.changed.emit()

    def retirer(self):
        t = self._selection()
        if t is None:
            return
        app = QApplication.instance()
        if not (app is not None and app.property("carene_tests")):
            rep = QMessageBox.question(
                self, "Retirer du catalogue",
                f"Retirer « {t.code} · {t.nom} » du catalogue ?\n\n"
                "Les manifestes et les charges déjà posées qui s'en servent "
                "gardent leurs dimensions : rien n'est recalculé.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if rep != QMessageBox.StandardButton.Yes:
                return
        self.catalogue.remove(t.code)
        self._nouveaux.discard(id(t))
        self._recharger()
        self.changed.emit()

    def _vers_manifeste(self):
        t = self._selection()
        if t is None:
            return
        n, ok = QInputDialog.getInt(self, "Ajouter au manifeste",
                                    f"Quantité de « {t.nom or t.code} » :", 1, 1, 100000)
        if ok:
            self.ajouter_au_manifeste.emit(t, int(n))

    def valider_saisie(self):
        """Valide la cellule en cours de saisie, s'il y en a une : on ferme
        souvent la fenêtre juste après avoir tapé, sans passer par Entrée, et
        cette valeur-là ne doit pas se perdre."""
        w = QApplication.focusWidget()
        if w is not None and self.table.isAncestorOf(w) and w is not self.table:
            from PySide6.QtWidgets import QAbstractItemDelegate
            self.table.commitData(w)
            self.table.closeEditor(w, QAbstractItemDelegate.EndEditHint.NoHint)

    def done(self, r):
        # fermer, c'est enregistrer : ce qui est saisi ici appartient au navire
        self.valider_saisie()
        self._nouveaux.clear()
        self.changed.emit()
        super().done(r)
