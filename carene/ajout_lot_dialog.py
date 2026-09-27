# -*- coding: utf-8 -*-
"""Composer un lot du manifeste : une seule fenêtre, tout sous les yeux.

Avant, ajouter « 150 palettes de rhum » demandait deux boîtes enchaînées — une
liste de codes, puis un nombre — et le reste (nom du lot, couleur, ports,
poids réel, cale imposée) se corrigeait après coup, ligne par ligne, dans le
tableau. On composait à l'aveugle : rien ne disait ce que pèse une palette
Europe ni si elle s'empile.

Ici, le catalogue du bord est à gauche avec ses dimensions et son poids, la
ligne en cours de composition à droite, et « Ajouter » laisse la fenêtre
ouverte : on enchaîne les lots d'une escale sans revenir au tableau.

Un lot n'est pas un type : « 150 palettes de rhum » et « 200 palettes de café »
sont deux lots du même type EUR (D-7). Le nom, la couleur et les ports
appartiennent donc au LOT ; l'emprise au sol vient du type.

La **hauteur**, le **stack** (empilement, ex-« gerbage ») et le **débord**
(ce qui dépasse de la palette) sont au lot (D-36, D-39) : la largeur d'une
palette est fixée à sa construction, mais sa hauteur, le fait qu'elle
supporte une deuxième palette et ce qui déborde de ses bords dépendent de ce
qu'on a chargé dessus. Le type
les propose quand il les connaît ; quand sa hauteur est laissée à 0 au
catalogue, elle est **exigée ici** — elle sert au contrôle de hauteur libre et
au centre de gravité, et un 0 n'a rien à faire dans ces calculs.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import ports as _ports
from . import theme
from .core.cargo_model import ManifestLine, couleur_de_lot, couleur_hex
from .port_picker import PortPicker
from .saisie import SpinEntier, SpinNombre

COLS = ["Code", "Type", "L (m)", "l (m)", "h (m)", "Poids t", "Stack", "Rot."]
C_CODE, C_NOM, C_L, C_LARG, C_H, C_POIDS, C_GERB, C_ROT = range(8)


def _pastille(hexa, taille=13):
    from PySide6.QtGui import QPainter, QPen
    pm = QPixmap(taille, taille)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(hexa))
    p.setPen(QPen(QColor(theme.TEXT_DIM), 1.0))
    p.drawRoundedRect(1, 1, taille - 2, taille - 2, 3, 3)
    p.end()
    return QIcon(pm)


def _court(champ, apres=None, largeur=150):
    """Un champ de nombre à sa taille, pas à toute la largeur du volet.

    Une quantité ou un poids n'a que faire de quarante centimètres de champ :
    à l'écran ça se lisait comme un formulaire étiré. On borne le champ, on
    laisse le reste de la ligne au vide (ou à une aide courte)."""
    champ.setMaximumWidth(largeur)
    champ.setMinimumWidth(110)
    lay = QHBoxLayout()
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(champ)
    if apres is not None:
        lay.addSpacing(8)
        lay.addWidget(apres)
    lay.addStretch(1)
    return lay


class AjoutLotDialog(QDialog):
    """Choisir un type du bord et composer le lot qu'on en fait."""

    # une ligne de manifeste est prête : la fenêtre reste ouverte
    ajoute = Signal(object)
    ouvrir_catalogue = Signal()

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self.setWindowTitle("Ajouter un lot au manifeste")
        self.setModal(False)
        self.resize(940, 470)
        self._couleur = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 10)
        root.setSpacing(8)
        intro = QLabel(
            "À gauche, ce que le navire sait porter (le catalogue du bord) ; à "
            "droite, le lot qu'on en fait. Un lot porte un nom, une couleur, "
            "ses ports — et sa <b>hauteur</b> et son <b>stack</b>, qui "
            "dépendent de ce qu'on a chargé sur la palette, pas de la palette. "
            "Deux lots peuvent employer le même type. "
            "« Ajouter » laisse la fenêtre ouverte : on enchaîne les lots d'une escale.")
        intro.setObjectName("hint")
        intro.setWordWrap(True)
        root.addWidget(intro)

        split = QSplitter(Qt.Orientation.Horizontal)

        # ---- le catalogue, à gauche ---------------------------------------
        gauche = QWidget()
        lg = QVBoxLayout(gauche)
        lg.setContentsMargins(0, 0, 0, 0)
        lg.setSpacing(6)
        self.filtre = QLineEdit()
        self.filtre.setPlaceholderText("Filtrer le catalogue…")
        self.filtre.setClearButtonEnabled(True)
        self.filtre.textChanged.connect(self._recharger)
        lg.addWidget(self.filtre)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        head = self.table.horizontalHeader()
        for c, w in ((C_CODE, 76), (C_L, 54), (C_LARG, 54), (C_H, 54),
                     (C_POIDS, 62), (C_GERB, 56), (C_ROT, 42)):
            head.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(c, w)
        head.setStretchLastSection(False)
        head.setSectionResizeMode(C_NOM, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._on_type)
        self.table.itemDoubleClicked.connect(lambda _i: self.ajouter())
        lg.addWidget(self.table, 1)
        b_cat = QPushButton("Gérer le catalogue…")
        b_cat.setProperty("ghost", "1")
        b_cat.setToolTip("Créer ou corriger un type du bord (Ctrl+K).")
        b_cat.clicked.connect(self.ouvrir_catalogue.emit)
        lg.addWidget(b_cat)
        split.addWidget(gauche)

        # ---- le lot, à droite ---------------------------------------------
        droite = QGroupBox("Le lot à embarquer")
        ld = QVBoxLayout(droite)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self.nom = QLineEdit()
        self.nom.setPlaceholderText("Palettes de rhum")
        self.nom.setToolTip("Le nom qui apparaîtra sur le plan et au pointage.")
        form.addRow("Désignation", self.nom)
        self.qte = QSpinBox()
        self.qte.setRange(1, 100000)
        self.qte.setValue(10)
        self.qte.setToolTip("Ce qui attend sur le quai. On ne pourra jamais en "
                            "poser davantage (D-19).")
        form.addRow("Quantité", _court(self.qte))
        self.poids = SpinNombre()
        self.poids.setRange(0.001, 500.0)
        self.poids.setDecimals(3)
        self.poids.setSuffix(" t")
        self.poids.setToolTip("Poids réel d'un exemplaire, pesé ou annoncé — "
                              "le catalogue ne donne qu'un défaut.")
        form.addRow("Poids unitaire", _court(self.poids))
        # LA HAUTEUR EST AU LOT. Le catalogue peut ne pas la connaître (une
        # palette n'a de hauteur qu'une fois garnie) : elle est alors exigée
        # ici, parce qu'elle décide de la hauteur libre et du VCG.
        self.hauteur = SpinNombre()
        self.hauteur.setRange(0.0, 20.0)
        self.hauteur.setDecimals(2)
        self.hauteur.setSuffix(" m")
        self.hauteur.setSpecialValueText("à renseigner")
        self.hauteur.setToolTip(
            "Hauteur d'un exemplaire de CE lot, chargement compris. Elle sert "
            "au contrôle de hauteur libre de la cale et au centre de gravité : "
            "sans elle, on n'ajoute pas.")
        form.addRow("Hauteur", _court(self.hauteur))
        self.gerbe = SpinEntier()
        self.gerbe.setRange(1, 50)
        self.gerbe.setToolTip(
            "Combien d'exemplaires de ce lot s'empilent (stack) — 1 = non "
            "empilable. Une palette s'empile ou non selon ce qu'on a chargé "
            "dessus, pas seulement selon le type.")
        aide_gerbe = QLabel("<i>exemplaires empilables, 1 = non empilable</i>")
        aide_gerbe.setObjectName("hint")
        form.addRow("Stack", _court(self.gerbe, aide_gerbe))
        # LE DÉBORD EST AU LOT, comme la hauteur et le stack : la même palette
        # EUR porte des fûts au carré ou des sacs de café qui sortent de 5 cm
        # tout autour. Le type ne fait que le proposer (D-39).
        self.debord = SpinNombre()
        self.debord.setRange(0.0, 2.0)
        self.debord.setDecimals(2)
        self.debord.setSingleStep(0.05)
        self.debord.setSuffix(" m")
        self.debord.setToolTip(
            "Ce qui dépasse de la palette, de chaque côté : 0,05 m = 5 cm "
            "tout autour. Compte pour la place occupée, jamais pour la charge "
            "au m² (le poids passe par la palette).")
        self.debord.valueChanged.connect(self._maj_total)
        aide_deb = QLabel("<i>ce qui dépasse de la palette, de chaque côté</i>")
        aide_deb.setObjectName("hint")
        form.addRow("Débord", _court(self.debord, aide_deb))
        coul = QHBoxLayout()
        self.b_coul = QPushButton()
        self.b_coul.setProperty("ghost", "1")
        self.b_coul.clicked.connect(self._choisir_couleur)
        self.b_coul.setToolTip("La couleur de ce lot sur le plan de chargement.")
        self.b_coul.setMinimumWidth(150)
        coul.addWidget(self.b_coul)
        coul.addStretch(1)
        form.addRow("Couleur", coul)
        # les ports ne se tapent plus : on tape trois lettres et on choisit —
        # les escales du navire d'abord, puis les 17 573 ports du UN/LOCODE.
        # Ce qui est enregistré dans le lot est le NOM ; le code se lit à côté.
        self.chg = PortPicker(win=win, placeholder="port de chargement")
        self.dech = PortPicker(win=win, placeholder="port de déchargement")
        form.addRow("Chargé à", self.chg)
        form.addRow("Déchargé à", self.dech)
        self.cale = QComboBox()
        self.cale.setToolTip("Imposer une cale, ou laisser le répartiteur choisir.")
        form.addRow("Cale imposée", self.cale)
        self.note = QLineEdit()
        self.note.setPlaceholderText("Arrimage, remarque…")
        form.addRow("Note", self.note)
        # Plus de « charge du bord » ici : un engin du navire n'est pas une
        # ligne de manifeste, il a son propre inventaire (D-18). On le dit et
        # on y renvoie, plutôt que de laisser fabriquer une fausse marchandise.
        self.chk_bord = QCheckBox("Charge du bord (hors manifeste)")
        self.chk_bord.setVisible(False)          # gardé pour les anciens appels
        vers_bord = QLabel(
            "<i>Un engin du bord (chariot, transpalette) ne se met pas au "
            "manifeste :<br>Navire › <b>Matériel du bord…</b></i>")
        vers_bord.setObjectName("hint")
        vers_bord.setWordWrap(True)
        form.addRow("", vers_bord)
        ld.addLayout(form)
        self.lbl_total = QLabel("")
        self.lbl_total.setStyleSheet("font-weight: bold; font-size: 13px;")
        # Sans retour à la ligne, un avertissement d'une phrase (« Trop lourd
        # pour : … ») imposait sa largeur à tout le volet, et le catalogue à
        # gauche se retrouvait écrasé à cent pixels — « l'affichage n'est pas
        # terrible », disait le bord. Le texte se plie, le volet garde sa part.
        self.lbl_total.setWordWrap(True)
        ld.addWidget(self.lbl_total)
        self.lbl_aide = QLabel("")
        self.lbl_aide.setObjectName("hint")
        self.lbl_aide.setWordWrap(True)
        ld.addWidget(self.lbl_aide)
        ld.addStretch(1)
        split.addWidget(droite)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([520, 400])
        gauche.setMinimumWidth(360)
        droite.setMinimumWidth(380)
        root.addWidget(split, 1)

        ligne = QHBoxLayout()
        self.lbl_msg = QLabel("")
        self.lbl_msg.setObjectName("hint")
        ligne.addWidget(self.lbl_msg, 1)
        b_ponctuel = QPushButton("Charge ponctuelle…")
        b_ponctuel.setProperty("ghost", "1")
        b_ponctuel.setToolTip("Un colis hors catalogue : dimensions et poids "
                              "saisis à la main, quantité 1.")
        b_ponctuel.clicked.connect(self.ajouter_ponctuelle)
        ligne.addWidget(b_ponctuel)
        self.b_ajout = QPushButton("Ajouter au manifeste")
        self.b_ajout.setProperty("accent", "1")
        self.b_ajout.clicked.connect(self.ajouter)
        ligne.addWidget(self.b_ajout)
        b_close = QPushButton("Fermer")
        b_close.setProperty("ghost", "1")
        b_close.clicked.connect(self.accept)
        ligne.addWidget(b_close)
        root.addLayout(ligne)

        # Les liaisons se font UNE fois, à la construction : la fenêtre reste
        # ouverte d'une escale à l'autre et se réaffiche, et les brancher dans
        # showEvent ajoutait un abonné de plus à chaque ouverture — le total se
        # recalculait n fois à la n-ième.
        self.qte.valueChanged.connect(self._maj_total)
        self.poids.valueChanged.connect(self._maj_total)
        self.nom.textEdited.connect(lambda _t: setattr(self, "_nom_auto", False))

        self.refresh()

    # ------------------------------------------------------------- données
    @property
    def condition(self):
        return self.win.condition

    def _catalogue(self):
        return getattr(self.win, "catalogue", None)

    def refresh(self):
        """Relit le catalogue, les ports connus et les cales du navire."""
        self._recharger()
        # Les escales : celles de la ligne du navire, plus celles déjà
        # employées ici ou au journal — le champ, lui, va chercher le reste du
        # monde dès qu'on tape trois lettres.
        escales = _ports.liste_du_bord(self.win)
        vus = []
        for m in self.condition.manifeste:
            vus += [m.port_chargement, m.port_dechargement]
        journal = getattr(self.win, "journal", None)
        if journal is not None:
            try:
                vus += list(journal.lieux_connus())
            except Exception:            # pragma: no cover - le journal ne bloque rien
                pass
        escales.apprendre(vus)
        for champ in (self.chg, self.dech):
            champ.recharger()
        courant = self.cale.currentData()
        self.cale.clear()
        self.cale.addItem("— le répartiteur choisit —", "")
        proj = getattr(self.win, "project", None)
        if proj is not None:
            from .project import KIND_CONTOUR
            for _d, cap in proj.all_capacities():
                if cap.kind != KIND_CONTOUR and len(cap.points) >= 3:
                    nav = getattr(self.win, "nav", None)
                    if nav is not None and (nav.est_capacite(cap.code)
                                            or nav.est_capacite(cap.name)):
                        continue          # une soute n'est pas une cale
                    self.cale.addItem(f"{cap.code} · {cap.name or ''}".strip(" ·"),
                                      cap.code)
        i = self.cale.findData(courant)
        self.cale.setCurrentIndex(max(0, i))
        self._maj_total()

    def _recharger(self, *_a):
        cat = self._catalogue()
        courant = self.type_courant()
        filtre = self.filtre.text().strip().lower()
        self.table.setRowCount(0)
        for t in (cat or []):
            if filtre and filtre not in " ".join(
                    (t.code, t.nom, t.categorie)).lower():
                continue
            r = self.table.rowCount()
            self.table.insertRow(r)
            vals = {C_CODE: t.code, C_NOM: t.nom,
                    C_L: f"{t.longueur_m:g}", C_LARG: f"{t.largeur_m:g}",
                    # hauteur facultative au catalogue : « — » quand elle
                    # manque, et c'est le champ de droite qui la donnera
                    C_H: f"{t.hauteur_m:g}" if t.hauteur_renseignee else "—",
                    C_POIDS: f"{t.poids_t:g}",
                    C_GERB: f"×{t.gerbable_max}" if t.gerbable_max > 1 else "non",
                    C_ROT: "oui" if t.rotation_permise else "non"}
            for c in range(len(COLS)):
                it = QTableWidgetItem(vals.get(c, ""))
                it.setData(Qt.ItemDataRole.UserRole, t.code)
                if c == C_H and not t.hauteur_renseignee:
                    it.setForeground(QColor(theme.TEXT_DIM))
                    it.setToolTip("Hauteur non renseignée au catalogue : "
                                  "donnez-la dans « Hauteur » à droite.")
                if c in (C_L, C_LARG, C_H, C_POIDS, C_GERB):
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                        | Qt.AlignmentFlag.AlignVCenter)
                if c == C_CODE:
                    it.setIcon(_pastille(couleur_hex(t)))
                if c == C_NOM:
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                if t.note:
                    it.setToolTip(t.note)
                self.table.setItem(r, c, it)
            if courant is not None and t.code == courant.code:
                self.table.selectRow(r)
        if self.table.rowCount() and self.table.currentRow() < 0:
            self.table.selectRow(0)
        if not self.table.rowCount():
            self.lbl_msg.setText(
                "Le catalogue du bord est vide : « Gérer le catalogue… » pour "
                "y définir un premier type, ou « Charge ponctuelle… »."
                if not (cat and len(cat)) else "Aucun type ne correspond au filtre.")

    def type_courant(self):
        r = self.table.currentRow()
        it = self.table.item(r, C_CODE) if r >= 0 else None
        cat = self._catalogue()
        if it is None or cat is None:
            return None
        return cat.get(it.data(Qt.ItemDataRole.UserRole))

    # ------------------------------------------------------------- le lot
    def _on_type(self):
        t = self.type_courant()
        if t is None:
            return
        if not self.nom.text().strip() or getattr(self, "_nom_auto", True):
            self.nom.setText(t.nom)
            self._nom_auto = True
        self.poids.setMaximum(t.poids_max_t if t.poids_max_t > 0 else 500.0)
        self.poids.setValue(t.poids_t)
        # le type PROPOSE hauteur et stack (empilement) ; 0 = il ne les connaît pas
        self.hauteur.setValue(t.hauteur_m if t.hauteur_renseignee else 0.0)
        self.gerbe.setValue(max(1, int(t.gerbable_max or 1)))
        self.debord.setValue(max(0.0, float(t.debord_m or 0.0)))
        self._poser_couleur(couleur_de_lot(len(self.condition.manifeste)))
        aides = [f"{t.categorie} · "
                 + (f"stack ×{t.gerbable_max}" if t.gerbable_max > 1
                    else "non empilable (stack 1)")
                 + (" · rotation permise" if t.rotation_permise
                    else " · ne se pose pas tourné") + "."]
        if not t.hauteur_renseignee:
            aides.append("Ce type n'a pas de hauteur au catalogue : donnez "
                         "celle de ce lot, chargement compris.")
        if t.poids_max_t > 0:
            aides.append(f"Poids maximal : {t.poids_max_t:g} t par exemplaire "
                         "(manuel d'assujettissement) — au-delà, la saisie est "
                         "refusée.")
        if t.note:
            aides.append(f"Note du catalogue : {t.note}.")
        self.lbl_aide.setText("<br>".join(aides))
        self._maj_total()

    def _poser_couleur(self, hexa):
        self._couleur = hexa or ""
        self.b_coul.setText(self._couleur or "—")
        self.b_coul.setStyleSheet(
            f"QPushButton {{ border-left: 16px solid {self._couleur or '#888'}; "
            "padding-left: 8px; text-align: left; }")

    def _choisir_couleur(self):
        c = QColorDialog.getColor(QColor(self._couleur or "#888888"), self,
                                  "Couleur de ce lot sur le plan")
        if c.isValid():
            self._poser_couleur(c.name())

    def _maj_total(self, *_a):
        """Le poids du lot, en gros : c'est le chiffre qu'on relit avant de
        valider, et celui qui décide de la place à trouver.

        Et, dessous, ce que chaque pont accepte pour CETTE emprise : un colis
        de 1,6 t sur 1,2 × 0,8 m fait 1,67 t/m², ce qu'un pont à 1 t/m²
        refuse. Le voir ici évite de le découvrir au répartiteur, quand la
        moitié du navire « n'a pas de place ». Le catalogue du bord dit
        d'ailleurs « poids max selon le pont » : voilà ce que ça vaut."""
        n, p = self.qte.value(), self.poids.value()
        texte = f"{n} × {p:g} t = {n * p:.2f} t au total"
        t = self.type_courant()
        # Quand le lot déborde, on annonce les DEUX mesures : la palette
        # (celle qui porte le poids) et l'encombrement (celui qui prend la
        # place). C'est ce qui explique, plus tard, pourquoi deux palettes ne
        # se touchent pas sur le plan (D-39).
        d = self.debord.value()
        if t is not None and d > 0:
            texte += (f"<br>emprise {t.longueur_m:g} × {t.largeur_m:g} m, "
                      f"encombrement {t.longueur_m + 2 * d:g} × "
                      f"{t.largeur_m + 2 * d:g} m "
                      f"(débord {d:g} m de chaque côté)")
        proj = getattr(self.win, "project", None)
        if t is not None and proj is not None and t.longueur_m and t.largeur_m:
            aire = t.longueur_m * t.largeur_m
            from .project import KIND_CONTOUR
            par_pont = {}
            for d, cap in proj.all_capacities():
                lim = float(getattr(cap, "charge_admissible_t_m2", 0) or 0)
                if cap.kind == KIND_CONTOUR or len(cap.points) < 3 or lim <= 0:
                    continue
                par_pont[d.name] = min(par_pont.get(d.name, lim), lim)
            if par_pont:
                trop = [f"{nom} ({lim * aire:.2f} t)" for nom, lim in par_pont.items()
                        if p > lim * aire + 1e-9]
                if trop:
                    texte += ("<br><span style='color:#8F4C0A'>Trop lourd pour : "
                              + ", ".join(trop) + " — poids maximal par colis "
                              "sur cette emprise. Le répartiteur n'y posera ce "
                              "lot que dans une zone renforcée, s'il y en a."
                              "</span>")
                else:
                    texte += ("<br><span style='color:#5A6570'>Accepté sur tous "
                              "les ponts (au plus "
                              + ", ".join(f"{nom} {lim * aire:.2f} t"
                                          for nom, lim in par_pont.items())
                              + ").</span>")
        self.lbl_total.setText(texte)

    def showEvent(self, event):
        # à la réouverture, seul le récapitulatif est à refaire : les cales et
        # les charges admissibles ont pu changer entre-temps
        self._maj_total()
        return super().showEvent(event)

    # ------------------------------------------------------------- actions
    def ligne_composee(self):
        """La ligne de manifeste telle qu'elle est composée, ou None."""
        t = self.type_courant()
        if t is None or self.hauteur.value() <= 0:
            return None
        m = ManifestLine.from_type(t, quantite=self.qte.value(),
                                   hauteur_m=self.hauteur.value(),
                                   gerbable_max=self.gerbe.value(),
                                   debord_m=self.debord.value())
        m.nom = self.nom.text().strip() or t.nom
        m.poids_t = self.poids.value()
        m.couleur = self._couleur
        m.port_chargement = self.chg.valeur()
        m.port_dechargement = self.dech.valeur()
        m.cale_imposee = self.cale.currentData() or ""
        m.note = self.note.text().strip()
        m.hors_manifeste = self.chk_bord.isChecked()
        return m

    def ajouter(self):
        t = self.type_courant()
        if t is None:
            self.lbl_msg.setText("Choisissez d'abord un type dans le catalogue.")
            return None
        refus = t.poids_refuse(self.poids.value())
        if refus:
            self.lbl_msg.setText(refus + " — corrigez le poids unitaire.")
            return None
        # HAUTEUR OBLIGATOIRE : elle entre dans le contrôle de hauteur libre et
        # dans le VCG. Un lot sans hauteur passerait sous tous les contrôles au
        # lieu d'être signalé — mieux vaut refuser et le dire.
        if self.hauteur.value() <= 0:
            self.lbl_msg.setText(
                f"« {t.nom or t.code} » n'a pas de hauteur au catalogue : "
                "donnez la hauteur d'un exemplaire de ce lot (chargement "
                "compris) avant d'ajouter. Elle sert au contrôle de hauteur "
                "libre de la cale et au centre de gravité.")
            self.hauteur.setFocus()
            return None
        m = self.ligne_composee()
        self.condition.manifeste.append(m)
        self.ajoute.emit(m)
        self.lbl_msg.setText(
            f"« {m.nom} » : {m.quantite} × {m.poids_t:g} t ajouté au manifeste."
            + ("  (charge du bord)" if m.hors_manifeste else ""))
        # prêt pour le lot suivant : la couleur avance, le reste se garde
        self._poser_couleur(couleur_de_lot(len(self.condition.manifeste)))
        self.nom.selectAll()
        self.nom.setFocus()
        return m

    def ajouter_ponctuelle(self):
        """Une charge qui n'est dans aucun catalogue : la ligne est créée avec
        les dimensions par défaut, à corriger dans le tableau du manifeste."""
        m = ManifestLine(nom=self.nom.text().strip() or "Charge ponctuelle",
                         quantite=self.qte.value(),
                         poids_t=max(0.001, self.poids.value()),
                         # la hauteur et le stack saisis servent aussi ici ;
                         # à défaut, le manifeste les corrigera en colonne
                         hauteur_m=self.hauteur.value() or 1.0,
                         gerbable_max=max(1, self.gerbe.value()),
                         debord_m=max(0.0, self.debord.value()),
                         couleur=self._couleur or couleur_de_lot(
                             len(self.condition.manifeste)),
                         port_chargement=self.chg.valeur(),
                         port_dechargement=self.dech.valeur(),
                         cale_imposee=self.cale.currentData() or "",
                         note=self.note.text().strip(),
                         hors_manifeste=self.chk_bord.isChecked())
        self.condition.manifeste.append(m)
        self.ajoute.emit(m)
        self.lbl_msg.setText(
            f"« {m.nom} » ajouté — corrigez ses dimensions dans le manifeste "
            "(colonnes L, l et h).")
        return m
