# -*- coding: utf-8 -*-
"""Le manifeste en tableau — maquette M-A.

Une ligne = un type × une quantité. **Tout s'y tape**, ligne par ligne : la
quantité, le poids unitaire réel, les trois dimensions L, l et h dans leur
colonne propre, le **débord** (ce qui dépasse de la palette, D-39), le stack
(empilement), les ports, la cale imposée, la note. La ligne
porte ses propres cotes, recopiées du type à la composition du lot : le
catalogue ne fait que proposer (D-36). C'est ce qu'il fallait pour la
hauteur — la largeur d'une palette est donnée à sa construction, mais sa
hauteur et son stack dépendent du chargement posé dessus.

Une ligne sans type est une charge ponctuelle : dimensions et poids saisis,
quantité 1.

Ce tableau ne pose rien : la pose se fait sur le plan (ou par le solveur).
« Posé » et « Reste » se déduisent de ce qui est dans les cales.

Il ne liste QUE de la marchandise. Le **matériel du bord** — chariot
élévateur, transpalette, appartenant au navire et servant au chargement — n'a
pas sa place dans un manifeste : il vit dans l'inventaire du navire et
s'ouvre par « Matériel du bord… ». Il pèse dans la stabilité comme le reste,
il ne compte simplement dans aucun total d'ici.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import ports as _ports
from . import theme
from .saisie import DelegueSansTiret
from .core.cargo_model import ManifestLine, couleur_de_lot, couleur_hex
from .port_picker import PortDelegate, nom_depuis_libelle


def _pastille(hexa, taille=13):
    """Une pastille de couleur, cernée : lisible sur fond clair comme sur la
    surbrillance de sélection."""
    from PySide6.QtGui import QIcon, QPainter, QPen, QPixmap
    pm = QPixmap(taille, taille)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(hexa))
    p.setPen(QPen(QColor(theme.BORDER), 1))
    p.drawRoundedRect(1, 1, taille - 2, taille - 2, 3, 3)
    p.end()
    return QIcon(pm)

COLS = ["Type", "Désignation", "Coul.", "Qté", "Posé", "Reste", "Poids unit. t", "Total t",
        "L (m)", "l (m)", "h (m)", "Débord (m)", "Stack", "Chargé à", "Déchargé à",
        "Cale imposée", "IMDG", "Note"]
(C_TYPE, C_NOM, C_COUL, C_QTE, C_POSE, C_RESTE, C_POIDS, C_TOTAL, C_L, C_LARG,
 C_H, C_DEB, C_GERB, C_CHG, C_DECH, C_CALE, C_IMDG, C_NOTE) = range(18)
# Tout ce qui décrit le lot se tape ici, type de catalogue ou pas : la ligne
# porte ses propres cotes (D-36). Seuls « Type », « Posé », « Reste » et le
# total se déduisent — ils ne sont l'affaire de personne à la saisie.
EDITABLES = {C_NOM, C_QTE, C_POIDS, C_L, C_LARG, C_H, C_DEB, C_GERB,
             C_CHG, C_DECH, C_CALE, C_IMDG, C_NOTE}
AIDES_COLONNES = {
    C_IMDG: "Classe IMDG de la marchandise dangereuse (3, 9, 2.1…), vide pour une "
            "marchandise ordinaire. Elle n'entre que dans une cale qui l'admet "
            "(éditeur de plans).",
    C_L: "Longueur du colis, le long de X quand la rotation vaut 0.",
    C_LARG: "Largeur du colis, le long de Y quand la rotation vaut 0.",
    C_H: "Hauteur d'un exemplaire de CE lot : elle dépend de ce qui est empilé "
         "sur la palette, pas de la palette. Elle sert au contrôle de hauteur "
         "libre et au centre de gravité.",
    C_DEB: "Ce qui dépasse de la palette, de chaque côté : 0,05 m = 5 cm "
           "tout autour. Compte pour la place occupée, jamais pour la charge "
           "au m² (le poids passe par la palette).",
    C_GERB: "Exemplaires empilables (stack) de ce lot — 1 = non empilable. "
            "Empilable ou non dépend du chargement posé, pas seulement du type.",
}


class ManifestPanel(QWidget):
    """Le manifeste, pleine largeur, avec totaux et bilan par port."""

    changed = Signal()

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self._loading = False
        # ligne du tableau -> indice dans `condition.manifeste` : le tableau
        # ne montre que la marchandise, les deux numérotations diffèrent dès
        # qu'un fichier ancien porte encore une ligne « du bord »
        self._rows = []

        root = QVBoxLayout(self)
        root.setContentsMargins(9, 7, 9, 9)
        root.setSpacing(8)

        row = QHBoxLayout()
        b_cat = QPushButton("+ depuis le catalogue")
        b_cat.setProperty("accent", "1")
        b_cat.clicked.connect(self.add_from_catalogue)
        b_one = QPushButton("+ charge ponctuelle")
        b_one.setProperty("ghost", "1")
        b_one.setToolTip("Une charge hors catalogue : dimensions et poids saisis, quantité 1.")
        b_one.clicked.connect(self.add_one_shot)
        b_bord = QPushButton("Matériel du bord…")
        b_bord.setProperty("ghost", "1")
        b_bord.setToolTip(
            "Les engins qui appartiennent au NAVIRE et servent au chargement : "
            "chariot élévateur, transpalette. Ils pèsent et occupent la place, "
            "mais ce n'est pas de la marchandise — ils ne figurent donc pas au "
            "manifeste. Leur inventaire est celui du navire ; leur position, "
            "elle, appartient au point.")
        b_bord.clicked.connect(self.open_materiel)
        b_del = QPushButton("Supprimer la ligne")
        b_del.setProperty("ghost", "1")
        b_del.clicked.connect(self.remove_selected)
        b_catalogue = QPushButton("Catalogue du bord…")
        b_catalogue.setProperty("ghost", "1")
        b_catalogue.clicked.connect(lambda: self.win.open_catalogue())
        b_escales = QPushButton("Escales du navire…")
        b_escales.setProperty("ghost", "1")
        b_escales.setToolTip(
            "Les ports de la ligne, avec leur code UN/LOCODE : c'est cette "
            "liste qui est proposée en tête des colonnes « Chargé à » et "
            "« Déchargé à ». On y cherche aussi n'importe quel port du monde.")
        b_escales.clicked.connect(self.open_ports)
        row.addWidget(b_cat)
        row.addWidget(b_one)
        row.addWidget(b_bord)
        row.addWidget(b_del)
        row.addStretch(1)
        row.addWidget(b_escales)
        row.addWidget(b_catalogue)
        root.addLayout(row)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        head = self.table.horizontalHeader()
        for c in range(len(COLS)):
            head.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(C_NOM, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(C_NOTE, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setWordWrap(False)
        # « Chargé à » et « Déchargé à » ne se tapent plus : un clic ouvre le
        # champ de recherche des ports — escales du navire d'abord, puis les
        # 17 573 ports du UN/LOCODE. Le tableau montre « FRLEH — Le Havre » ;
        # ce qui est enregistré reste le nom seul.
        # « — » (cale imposée, classe IMDG, type… vides) s'efface quand on
        # saisit (D-89) ; les ports ont leur propre délégué, qui le fait déjà
        self.table.setItemDelegate(DelegueSansTiret(self.table))
        self._delegue_port = PortDelegate(self.table, win=win)
        for c in (C_CHG, C_DECH):
            self.table.setItemDelegateForColumn(c, self._delegue_port)
        self.table.itemChanged.connect(self._on_edited)
        self.table.cellClicked.connect(self._on_click)
        root.addWidget(self.table, 1)

        self.lbl_aide = QLabel(
            "<b>Tout se tape ici, ligne par ligne</b> : quantité, poids unitaire "
            "(refusé au-delà du maximum du type), <b>L</b>, <b>l</b>, <b>h</b> et "
            "<b>Stack</b>. Le catalogue n'a fait que proposer ces cotes — la "
            "hauteur d'une palette et son stack dépendent de ce qu'on empile "
            "dessus, donc du lot. Corriger <b>h</b> ou <b>Stack</b> suit les colis "
            "déjà posés ; corriger <b>L</b> ou <b>l</b> ne les touche pas (leur "
            "emprise est déjà arbitrée sur le plan). "
            "<b>Posé</b> et <b>Reste</b> se déduisent des "
            "charges posées sur les ponts. Une ligne sans type est une <b>charge ponctuelle</b>. "
            "Le <b>matériel du bord</b> (chariot, transpalette) n'est pas de la marchandise : "
            "il n'est pas listé ici et ne compte dans aucun total — voyez « Matériel du bord… ».")
        self.lbl_aide.setObjectName("hint")
        self.lbl_aide.setWordWrap(True)
        root.addWidget(self.lbl_aide)

        bas = QHBoxLayout()
        self.lbl_total = QLabel("")
        self.lbl_ports = QLabel("")
        self.lbl_ports.setObjectName("hint")
        bas.addWidget(self.lbl_total)
        bas.addSpacing(24)
        bas.addWidget(self.lbl_ports, 1)
        b_solve = QPushButton("Répartir…")
        b_solve.setProperty("accent", "1")
        b_solve.clicked.connect(self.win.open_solver)
        bas.addWidget(b_solve)
        root.addLayout(bas)

    # ------------------------------------------------------------- lecture
    @property
    def condition(self):
        return self.win.condition

    def refresh(self):
        self._loading = True
        try:
            cond = self.condition
            cat = getattr(self.win, "catalogue", None)
            escales = _ports.liste_du_bord(self.win)
            attribue = cond.places_par_ligne()
            # Le manifeste liste la MARCHANDISE, et rien d'autre. Une ligne
            # « du bord » d'un fichier non encore migré est écartée d'ici —
            # elle est reprise dans le matériel du bord à l'ouverture.
            self._rows = [i for i, m in enumerate(cond.manifeste)
                          if not getattr(m, "hors_manifeste", False)]
            lignes = [cond.manifeste[i] for i in self._rows]
            attribue = [attribue[i] for i in self._rows]
            self.table.setRowCount(len(lignes) + (1 if lignes else 0))
            tq = tp = tr = tw = 0.0
            ports = {}
            for r, m in enumerate(lignes):
                t = cat.get(m.type_code) if (cat is not None and m.type_code) else None
                place = attribue[r]
                reste = m.quantite - place
                tq += m.quantite; tp += place; tr += max(0, reste)
                tw += m.poids_total_t
                # deux orthographes d'un même port ne font qu'une ligne de
                # bilan : c'est la même escale, donc le même déchargement
                pd = _ports.etiquette_de(escales, m.port_dechargement) or "—"
                a = ports.setdefault(pd, [0, 0.0, 0])
                a[0] += m.quantite; a[1] += m.poids_total_t; a[2] += max(0, reste)
                vals = [
                    (m.type_code or "—"),
                    m.nom, "", str(m.quantite), str(place),
                    (str(reste) if reste > 0 else ("✓" if reste == 0 else f"+{-reste}")),
                    f"{m.poids_t:g}", f"{m.poids_total_t:.2f}",
                    f"{m.longueur_m:g}", f"{m.largeur_m:g}", f"{m.hauteur_m:g}",
                    f"{m.debord_m:g}" if m.debord_m > 0 else "0",
                    str(m.gerbable_max),
                    _ports.etiquette_de(escales, m.port_chargement) or "—", pd,
                    m.cale_imposee or "—", getattr(m, "classe_imdg", "") or "—",
                    getattr(m, "note", ""),
                ]
                for c, v in enumerate(vals):
                    item = QTableWidgetItem(v)
                    if c not in EDITABLES:
                        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    if c in (C_L, C_LARG, C_H, C_DEB, C_GERB):
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                              | Qt.AlignmentFlag.AlignVCenter)
                        item.setToolTip(AIDES_COLONNES[c])
                    if c == C_DEB:
                        if m.debord_m > 0:
                            # dire ce que ça fait occuper : le chiffre seul ne
                            # se rapproche pas des L et l d'à côté
                            ex = m.longueur_m + 2 * m.debord_m
                            ey = m.largeur_m + 2 * m.debord_m
                            item.setToolTip(
                                AIDES_COLONNES[C_DEB]
                                + f"\nEmprise {m.longueur_m:g} × {m.largeur_m:g} m, "
                                  f"encombrement {ex:g} × {ey:g} m.")
                        else:
                            item.setForeground(QColor(theme.TEXT_DIM))
                    if c == C_TYPE:
                        item.setForeground(QColor(couleur_hex(m)))
                        f = item.font(); f.setBold(True); item.setFont(f)
                        if t is not None:
                            item.setToolTip(
                                f"Type du catalogue « {t.code} »"
                                + (f" ({t.source})" if t.source else "")
                                + ". Les cotes de CETTE ligne se corrigent ici : "
                                "le catalogue n'a fait que les proposer.")
                    if c == C_COUL:
                        # une pastille dessinée, pas un fond de cellule : le
                        # fond disparaît sous la surbrillance quand la ligne
                        # est sélectionnée, l'icône reste
                        item.setIcon(_pastille(couleur_hex(m)))
                        item.setFlags(Qt.ItemFlag.ItemIsEnabled
                                      | Qt.ItemFlag.ItemIsSelectable)
                        item.setToolTip("Cliquez pour choisir la couleur de ce lot "
                                        "sur le plan de chargement.")
                    if c in (C_CHG, C_DECH):
                        # le champ de saisie reçoit le NOM, la cellule montre
                        # l'étiquette : l'un se relit dans le fichier, l'autre
                        # se lit à l'écran
                        nom = m.port_chargement if c == C_CHG else m.port_dechargement
                        item.setData(Qt.ItemDataRole.UserRole, nom)
                        if v != "—":
                            item.setToolTip("Cliquez pour choisir l'escale : les ports du "
                                            "navire d'abord, puis tous ceux du monde.")
                    if c == C_RESTE:
                        item.setForeground(QColor(theme.WARN if reste > 0 else
                                                  (theme.OK if reste == 0 else theme.DANGER)))
                    if c == C_POIDS and t is not None and t.poids_max_t > 0:
                        item.setToolTip(f"Maximum {t.poids_max_t:g} t ({t.source})")
                    self.table.setItem(r, c, item)
            if lignes:
                r = len(lignes)
                # une case par colonne, remplie par indice nommé : une liste
                # écrite à la main se décale dès qu'une colonne bouge (elle
                # portait 15 entrées pour 14 colonnes)
                tot = [""] * len(COLS)
                tot[C_NOM] = "Total manifeste"
                tot[C_QTE] = f"{tq:g}"
                tot[C_POSE] = f"{tp:g}"
                tot[C_RESTE] = f"{tr:g}"
                tot[C_TOTAL] = f"{tw:.1f}"
                for c, v in enumerate(tot):
                    item = QTableWidgetItem(v)
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                    f = item.font(); f.setBold(True); item.setFont(f)
                    item.setBackground(QColor(theme.SURFACE_2))
                    self.table.setItem(r, c, item)
            if not lignes:
                self.lbl_total.setText("Rien à embarquer pour l'instant.")
                self.lbl_ports.setText("")
            else:
                self.lbl_total.setText(
                    f"<b>{tq:g}</b> charges prévues · <b>{tp:g}</b> posées · "
                    f"<b style='color:{theme.WARN if tr else theme.OK}'>{tr:g} restent</b> · "
                    f"<b>{tw:.1f} t</b> au total")
                self.lbl_ports.setText("Par port de déchargement : " + " · ".join(
                    f"{p} {a[0]:g} ({a[1]:.1f} t{', reste ' + format(a[2], 'g') if a[2] else ''})"
                    for p, a in ports.items()))
        finally:
            self._loading = False

    # ------------------------------------------------------------- édition
    def _ligne(self, r):
        """La ligne de manifeste affichée sur cette rangée, ou None (rangée
        des totaux)."""
        if 0 <= r < len(self._rows):
            return self.condition.manifeste[self._rows[r]]
        return None

    def _on_click(self, r, c):
        """Un clic sur la pastille ouvre le choix de couleur du lot."""
        m = self._ligne(r) if c == C_COUL else None
        if m is None:
            return
        from PySide6.QtWidgets import QColorDialog
        coul = QColorDialog.getColor(QColor(couleur_hex(m)), self,
                                     f"Couleur du lot « {m.nom} »")
        if coul.isValid():
            m.couleur = coul.name()
            # les colis déjà posés de ce lot changent avec lui : le plan,
            # l'iso et la coupe doivent montrer la même couleur
            for pl in self._placements_du_lot(m):
                pl.couleur = m.couleur
            self.refresh()
            self.changed.emit()

    def _placements_du_lot(self, m):
        """Tous les colis posés qui viennent de cette ligne, par son lot. Les
        colis d'avant les lots (sans `lot_id`) sont rattachés par le type,
        comme les compte `places_par_ligne`."""
        cle = m.type_code or m.nom
        return [pl for lst in self.condition.placements.values() for pl in lst
                if not pl.est_materiel_bord
                and (pl.lot_id == m.lot_id
                     or (not pl.lot_id and (pl.type_code or pl.nom) == cle))]

    def _on_edited(self, item):
        if self._loading:
            return
        r, c = item.row(), item.column()
        cond = self.condition
        m = self._ligne(r)
        if m is None:
            return
        txt = item.text().strip()
        cat = getattr(self.win, "catalogue", None)
        t = cat.get(m.type_code) if (cat is not None and m.type_code) else None
        try:
            if c == C_NOM:
                m.nom = txt or m.nom
            elif c == C_QTE:
                m.quantite = max(0, int(float(txt.replace(",", "."))))
            elif c == C_POIDS:
                val = float(txt.replace(",", "."))
                refus = t.poids_refuse(val) if t is not None else None
                if refus:
                    QMessageBox.warning(self, "Poids refusé", refus + ".")
                elif val > 0 and val != m.poids_t:
                    # Le POIDS SUIT les colis posés (2.20.1), comme la
                    # hauteur : une palette pesée au quai à 2,4 t au lieu de
                    # 1,6 t pèse 2,4 t dans la cale aussi. Avant, le
                    # manifeste disait 240 t et la stabilité calculait sur
                    # 160 t. Le changement est dit, en tonnes.
                    poses = self._placements_du_lot(m)
                    avant = sum(p.poids_total_t for p in poses)
                    m.poids_t = val
                    for pl in poses:
                        pl.poids_t = val
                    if poses:
                        apres = sum(p.poids_total_t for p in poses)
                        win = self.win
                        if hasattr(win, "statusBar"):
                            win.statusBar().showMessage(
                                f"« {m.nom} » : poids unitaire {val:g} t, "
                                f"reporté sur {len(poses)} colis posé(s) — "
                                f"{apres - avant:+.1f} t à bord.", 12000)
            elif c in (C_L, C_LARG):
                # L'EMPRISE AU SOL ne suit pas les colis déjà posés : la
                # changer sous eux fabriquerait des chevauchements sans passer
                # par la porte qui les refuse (D-27). Ce qui est posé garde ses
                # cotes ; on le retire et on le repose pour les reprendre.
                val = float(txt.replace(",", "."))
                if val > 0:
                    setattr(m, {C_L: "longueur_m", C_LARG: "largeur_m"}[c], val)
            elif c == C_H:
                # La hauteur, elle, SUIT les colis posés : elle ne touche pas
                # l'emprise au sol, donc rien ne peut se mettre à mordre — et
                # elle décide de la hauteur libre et du VCG, qu'on veut justes
                # tout de suite.
                val = float(txt.replace(",", "."))
                if val > 0:
                    m.hauteur_m = val
                    for pl in self._placements_du_lot(m):
                        pl.hauteur_m = val
            elif c == C_DEB:
                # Le débord SUIT les colis posés, comme la hauteur : c'est une
                # cote du lot qu'on corrige, et un colis déjà arrimé dont les
                # sacs dépassent doit se signaler tout de suite. Il change la
                # PLACE occupée, donc il peut faire apparaître des refus —
                # c'est justement ce qu'on veut voir (D-39). L'emprise
                # nominale, elle, ne bouge pas : aucun colis ne se déplace.
                val = float(txt.replace(",", "."))
                if val >= 0:
                    m.debord_m = val
                    for pl in self._placements_du_lot(m):
                        pl.debord_m = val
            elif c == C_GERB:
                m.gerbable_max = max(1, int(float(txt)))
                # même raison : le stack borne l'empilement, pas l'emprise
                for pl in self._placements_du_lot(m):
                    pl.gerbable_max = m.gerbable_max
            elif c == C_CHG:
                m.port_chargement = self._port_saisi(txt)
            elif c == C_DECH:
                m.port_dechargement = self._port_saisi(txt)
                # le port suit le LOT, pas le type : deux lots de palettes
                # peuvent débarquer à deux escales
                for pl in self._placements_du_lot(m):
                    pl.port_dechargement = m.port_dechargement
            elif c == C_CALE:
                m.cale_imposee = "" if txt in ("", "-", "—") else txt.upper()
            elif c == C_IMDG:
                # la classe IMDG du lot (D-83) : elle suit les colis posés, et
                # le contrôle de pose la confronte aussitôt à leur cale
                m.classe_imdg = "" if txt in ("", "-", "—") else txt.strip()
                for pl in self._placements_du_lot(m):
                    pl.classe_imdg = m.classe_imdg
            elif c == C_NOTE:
                m.note = txt
        except ValueError:
            pass
        self.refresh()
        self.changed.emit()

    def _port_saisi(self, txt):
        """Le nom d'escale à retenir dans la ligne.

        L'étiquette redevient un nom, et la liste du bord donne l'orthographe
        de référence quand elle reconnaît l'escale : « Pointe à Pitre » tapé
        ici et « Pointe-à-Pitre » choisi ailleurs sont le même port, et ne
        doivent surtout pas produire deux feuilles de pointage. Ce que la liste
        ne connaît pas est gardé tel quel."""
        txt = nom_depuis_libelle(txt)
        if txt in ("", "-", "—"):
            return ""
        return _ports.liste_du_bord(self.win).nom_de(txt)

    def add_from_catalogue(self):
        """Composer un lot : le catalogue et la ligne côte à côte, dans une
        fenêtre qui reste ouverte. Avant, c'étaient deux boîtes enchaînées — une
        liste de codes, puis un nombre — et tout le reste du lot (nom, couleur,
        ports, poids réel, cale) se corrigeait après coup dans le tableau."""
        ouvrir = getattr(self.win, "ajouter_un_lot", None)
        if callable(ouvrir):
            return ouvrir()
        return None

    def open_materiel(self):
        """Le matériel du bord, dans sa fenêtre : ce n'est pas du manifeste.

        On passe par la vue Chargement quand elle est là — c'est elle qui
        tient la fenêtre et rafraîchit le plan derrière."""
        panel = getattr(self.win, "cargo_panel", None)
        ouvrir = getattr(panel, "open_materiel", None)
        if callable(ouvrir):
            return ouvrir()
        from .equipements_dialog import EquipementsDialog
        dlg = EquipementsDialog(self.win, parent=self)
        dlg.changed.connect(self.changed.emit)
        dlg.refresh()
        dlg.show()
        return dlg

    def open_ports(self):
        """La liste des escales du navire, dans sa fenêtre.

        On passe par la fenêtre principale quand elle sait l'ouvrir — c'est
        elle qui tient la liste et qui doit rafraîchir tout ce qui l'affiche ;
        sinon on l'ouvre ici, sur la même liste en mémoire."""
        ouvrir = getattr(self.win, "open_ports", None)
        if callable(ouvrir):
            return ouvrir()
        from .port_picker import PortsDialog
        dlg = self._ports_dlg = PortsDialog(self.win, parent=self)
        dlg.changed.connect(self.refresh)
        dlg.show()
        dlg.raise_()
        return dlg

    def add_one_shot(self):
        m = ManifestLine(nom="Charge ponctuelle", quantite=1, categorie="Colis",
                         couleur=couleur_de_lot(len(self.condition.manifeste)))
        self.condition.manifeste.append(m)
        self.refresh()
        r = next((i for i, j in enumerate(self._rows)
                  if self.condition.manifeste[j] is m), 0)
        self.table.setCurrentCell(r, C_NOM)
        self.changed.emit()

    def remove_selected(self):
        """Retirer une ligne du manifeste, et décider du sort de ses colis.

        Retirer la ligne seule laisserait des colis ORPHELINS : le plan et le
        bilan continueraient de les compter, alors que plus aucune ligne ne les
        annonce — « posé » sans « prévu », le contraire de D-19. On demande donc
        quand il y en a. Une ligne dont rien n'est posé reste un seul clic."""
        m = self._ligne(self.table.currentRow())
        if m is None:
            return
        poses = self._placements_du_lot(m)
        if poses:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            # hors écran, la question ne se pose pas : on prend le comportement
            # par défaut (la ligne ET ses colis s'en vont ensemble)
            if not (app is not None and app.property("carene_tests")):
                rep = QMessageBox.question(
                    self, "Retirer la ligne",
                    f"{len(poses)} colis de ce lot sont posés — les retirer du "
                    "plan aussi ?\n\n"
                    f"Lot « {m.nom} ». « Non » garde la ligne au manifeste : "
                    "les colis posés restent annoncés.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    | QMessageBox.StandardButton.Cancel)
                if rep == QMessageBox.StandardButton.Cancel:
                    return
                if rep == QMessageBox.StandardButton.No:
                    return
        if poses:
            restants = set(id(pl) for pl in poses)
            for cale, lst in list(self.condition.placements.items()):
                self.condition.placements[cale] = [
                    pl for pl in lst if id(pl) not in restants]
        self.condition.manifeste.remove(m)
        self.refresh()
        self.changed.emit()
