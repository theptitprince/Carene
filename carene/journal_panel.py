# -*- coding: utf-8 -*-
"""La vue « Journal » : la chronologie des points du navire.

En haut, le point courant — sa date, son voyage, son lieu, son libellé, sa
note — et ce qu'on peut en faire : l'enregistrer, le figer, en ouvrir un
nouveau. En bas, la liste de tous les points, du plus récent au plus ancien,
avec ce qui a été lu à l'écran quand chacun a été figé.

**Deux dates**, ici comme dans le fichier : la **date du point** est celle de
l'événement (départ, arrivée, relevé en mer) et se saisit ; « **Modifié le** »
est celle du dernier enregistrement et ne se saisit jamais — Carène la pose en
écrivant. Une seule colonne « Date » ne permettait pas de répondre à la
question du bord : « cette date, c'est quoi ? »

Le libellé est un menu : « Arrivée », « Départ », ou « Autre… » qui découvre
un champ libre. Le voyage est celui de la compagnie, facultatif et repris de
point en point ; le numéro du point reste, lui, l'identifiant du journal.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateTimeEdit,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QDateTime

from . import ports as _ports
from . import theme
from .saisie import DelegueSansTiret
from .journal import AUTRE, LIBELLES_PHARES, libelles_autres
from .port_picker import PortPicker

# Les colonnes que le bord lit vraiment quand il feuillette son journal :
# où l'on était, quel voyage, ce qu'on pesait, ce qu'on portait, et le début
# de la note. Le détail hydrostatique (tirants d'eau, assiette, GM, verdict)
# se lit dans la vue Stabilité du point, ou dans l'export CSV du journal :
# ici il faisait onze colonnes serrées où l'on ne trouvait plus rien.
#
# DEUX DATES, et elles ne disent pas la même chose : « Date du point » est
# celle de l'événement (départ, arrivée, relevé en mer), saisie par le bord ;
# « Modifié le » est celle du dernier enregistrement du fichier. Une seule
# colonne « Date » laissait le bord sans réponse à « c'est quoi, cette date ? ».
(C_NUM, C_VOYAGE, C_DATE, C_LIEU, C_LIBELLE, C_DEPL, C_CARGO, C_ETAT,
 C_MODIF, C_NOTE) = range(10)
COLS = ["N°", "Voyage", "Date du point", "Lieu", "Libellé", "Déplacement",
        "Cargaison", "État", "Modifié le", "Note"]

# Ce qu'on montre d'une note dans le tableau : les premiers mots suffisent à
# reconnaître le point ; la note entière est en infobulle.
NOTE_CAR = 60


def _ou_tiret(v):
    """Un tiret plutôt qu'un zéro ou un « None » : on n'affiche jamais une
    valeur qu'on n'a pas (D-10, et le principe qui va avec — ne rien présenter
    comme calculé qui ne le soit pas)."""
    return "—" if v is None or v == "" else str(v)


def _poids(t):
    """Un poids en tonnes, à la centaine de kilos, espace pour les milliers —
    la même écriture que le bandeau."""
    return f"{float(t):,.1f} t".replace(",", "\u202f")


def _debut_note(note):
    """Les premiers mots de la note, sur une ligne, élidés."""
    texte = " ".join((note or "").split())
    if not texte:
        return "—"
    if len(texte) <= NOTE_CAR:
        return texte
    return texte[:NOTE_CAR - 1].rstrip() + "…"


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


class JournalPanel(QWidget):
    """Point courant + liste des points."""

    changed = Signal()          # les champs du point courant ont changé

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self._loading = False
        self._points = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        titre = QLabel("JOURNAL — la chronologie du navire, point par point")
        titre.setObjectName("viewHeader")
        root.addWidget(titre)

        corps = QWidget()
        lay = QVBoxLayout(corps)
        lay.setContentsMargins(9, 7, 9, 9)
        lay.setSpacing(10)
        root.addWidget(corps, 1)

        # --- point courant : deux colonnes, la note à droite ---------------
        frame, fl = _card("Point courant")
        self.lbl_etat = QLabel("")
        self.lbl_etat.setObjectName("hint")
        self.lbl_etat.setWordWrap(True)
        fl.addWidget(self.lbl_etat)

        colonnes = QHBoxLayout()
        colonnes.setSpacing(16)
        form = QFormLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(4)
        # LA DATE DU POINT : celle de l'événement, saisie et corrigée par le
        # bord. Ce n'est pas la date d'enregistrement du fichier — celle-là
        # s'affiche à côté, en lecture seule, et se pose toute seule.
        self.ed_date = QDateTimeEdit()
        self.ed_date.setDisplayFormat("dd/MM/yyyy HH:mm")
        self.ed_date.setCalendarPopup(True)
        self.ed_date.setMaximumWidth(190)
        self.ed_date.setToolTip(
            "L'heure de l'événement : l'arrivée, le départ, le relevé en mer.\n"
            "C'est elle qu'on relira dans le journal ; elle se corrige.")
        self.ed_date.dateTimeChanged.connect(self._on_edit)
        self.lbl_modifie = QLabel("—")
        self.lbl_modifie.setObjectName("hint")
        self.lbl_modifie.setToolTip(
            "La date du dernier enregistrement de ce point, posée par Carène.\n"
            "Elle ne se saisit pas : « Enregistrer » et « Figer… » la mettent à jour.")
        # le lieu : le champ des ports — on tape trois lettres, on choisit
        # parmi les escales du navire puis parmi tous les ports du monde. « En
        # mer » y est proposé aussi : ce n'est pas une escale, mais c'est un
        # lieu de point. Et le champ reste libre pour une rade ou un mouillage
        # que la CEE-ONU ne connaît pas : ce qui est tapé est conservé.
        self.ed_lieu = PortPicker(win=self.win, en_mer=True,
                                  placeholder="port, rade, « En mer »…")
        self.ed_lieu.setMaximumWidth(330)
        self.ed_lieu.changed.connect(self._on_edit)
        # le voyage de la compagnie : on propose ceux du journal, parce qu'un
        # voyage porte plusieurs points et qu'un chiffre retapé de travers
        # coupe le voyage en deux. Facultatif : vide, il reste vide.
        self.ed_voyage = QComboBox()
        self.ed_voyage.setEditable(True)
        self.ed_voyage.setMaximumWidth(200)
        self.ed_voyage.lineEdit().setPlaceholderText("n° de la compagnie — facultatif")
        self.ed_voyage.setToolTip(
            "Le numéro de voyage de l'armement, celui qui figure sur les papiers du bord.\n"
            "Il est repris tel quel par les points suivants du même voyage.\n"
            "L'identifiant du point, lui, reste son numéro (colonne N°).")
        self.ed_voyage.currentTextChanged.connect(self._on_edit)
        # le libellé : un menu, parce qu'un point est une arrivée ou un départ
        # neuf fois sur dix. « Autre… » découvre le champ libre — qui garde
        # dans sa liste les moments plus fins (début de chargement, après
        # soutage…) et accepte n'importe quel texte : un libellé enregistré
        # par une version antérieure, où tout était libre, se retrouve là.
        self.ed_libelle = QComboBox()
        self.ed_libelle.setMinimumWidth(120)
        self.ed_libelle.addItem("")                 # pas encore nommé
        self.ed_libelle.addItems(LIBELLES_PHARES)
        self.ed_libelle.addItem(AUTRE)
        self.ed_libelle.currentIndexChanged.connect(self._on_libelle_menu)
        self.ed_libelle_autre = QComboBox()
        self.ed_libelle_autre.setEditable(True)
        self.ed_libelle_autre.setMinimumWidth(180)
        self.ed_libelle_autre.addItem("")
        self.ed_libelle_autre.addItems(libelles_autres())
        self.ed_libelle_autre.lineEdit().setPlaceholderText("moment du point")
        self.ed_libelle_autre.currentTextChanged.connect(self._on_edit)
        self.ed_libelle_autre.setVisible(False)
        self.box_libelle = QWidget()
        bl = QHBoxLayout(self.box_libelle)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)
        bl.addWidget(self.ed_libelle)
        bl.addWidget(self.ed_libelle_autre, 1)
        self.box_libelle.setMaximumWidth(330)
        form.addRow("Date du point", self.ed_date)
        form.addRow("Modifié le", self.lbl_modifie)
        form.addRow("Voyage", self.ed_voyage)
        form.addRow("Lieu", self.ed_lieu)
        form.addRow("Libellé", self.box_libelle)
        gauche = QWidget()
        gl = QVBoxLayout(gauche)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(6)
        gl.addLayout(form)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.b_save = QPushButton("Enregistrer")
        self.b_save.setProperty("accent", "1")
        self.b_save.clicked.connect(lambda: self.win.save_point())
        self.b_freeze = QPushButton("Figer…")
        self.b_freeze.setProperty("ghost", "1")
        self.b_freeze.setToolTip("Un point figé n'est plus jamais réécrit : c'est l'archive de "
                                 "l'état du navire à cet instant, verdict compris.")
        self.b_freeze.clicked.connect(lambda: self.win.freeze_point())
        self.b_new = QPushButton("Nouveau point")
        self.b_new.setProperty("ghost", "1")
        self.b_new.setToolTip("Ouvrir le point suivant : copie intégrale de celui-ci.")
        # sans le lambda, le signal `clicked` passe son booléen en premier
        # argument — il devenait le point source, et le bouton ne faisait rien
        self.b_new.clicked.connect(lambda: self.win.new_point())
        row.addWidget(self.b_save)
        row.addWidget(self.b_freeze)
        row.addWidget(self.b_new)
        row.addStretch(1)
        gl.addLayout(row)
        colonnes.addWidget(gauche)

        droite = QWidget()
        dl = QVBoxLayout(droite)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(3)
        lbl_note = QLabel("Note")
        lbl_note.setObjectName("hint")
        dl.addWidget(lbl_note)
        self.ed_note = QPlainTextEdit()
        self.ed_note.setPlaceholderText("Ce qui a été fait, ce qui reste à faire, ce qui a "
                                        "été constaté aux marques.")
        self.ed_note.setMaximumHeight(66)
        self.ed_note.textChanged.connect(self._on_edit)
        dl.addWidget(self.ed_note)
        colonnes.addWidget(droite, 1)
        fl.addLayout(colonnes)
        lay.addWidget(frame)

        # --- liste ----------------------------------------------------------
        frame, fl = _card("Tous les points")
        self.table = QTableWidget(0, len(COLS))
        # « — » (voyage, lieu, libellé vides) s'efface quand on saisit (D-89)
        self.table.setItemDelegate(DelegueSansTiret(self.table))
        self.table.setHorizontalHeaderLabels(COLS)
        head = self.table.horizontalHeader()
        for c in range(len(COLS)):
            head.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        # c'est la note qui prend la place restante : les autres colonnes
        # sont des valeurs courtes, elle seule gagne à s'allonger
        head.setSectionResizeMode(C_NOTE, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemDoubleClicked.connect(lambda _i: self.ouvrir())
        fl.addWidget(self.table, 1)
        row = QHBoxLayout()
        b_open = QPushButton("Ouvrir")
        b_open.setProperty("ghost", "1")
        b_open.clicked.connect(self.ouvrir)
        b_from = QPushButton("Nouveau point depuis celui-ci")
        b_from.setProperty("ghost", "1")
        b_from.clicked.connect(self.nouveau_depuis)
        b_del = QPushButton("Supprimer")
        b_del.setProperty("ghost", "1")
        b_del.clicked.connect(self.supprimer)
        b_imp = QPushButton("Importer un ancien cas…")
        b_imp.setProperty("ghost", "1")
        b_imp.clicked.connect(self.win.import_case)
        row.addWidget(b_open)
        row.addWidget(b_from)
        row.addWidget(b_del)
        row.addStretch(1)
        row.addWidget(b_imp)
        fl.addLayout(row)
        self.lbl_liste = QLabel("")
        self.lbl_liste.setObjectName("hint")
        self.lbl_liste.setWordWrap(True)
        fl.addWidget(self.lbl_liste)
        lay.addWidget(frame, 1)

    # ------------------------------------------------------------- lecture
    def refresh(self):
        self._loading = True
        try:
            p = self.win.point
            if p is None:
                self.lbl_etat.setText("Aucun navire.")
                return
            qd = QDateTime.fromString(p.horodatage, Qt.DateFormat.ISODate)
            if qd.isValid():
                self.ed_date.setDateTime(qd)
            else:
                # un point sans date lisible ne reprend pas celle du point
                # affiché avant lui — elle s'écrivait dans ce point à la
                # première retouche du lieu (D-77) : on part de maintenant
                self.ed_date.setDateTime(QDateTime.currentDateTime())
            # jamais modifiable : c'est Carène qui la pose en écrivant
            self.lbl_modifie.setText(p.modifie_lisible)
            # les lieux déjà employés par le journal rejoignent les escales du
            # navire : on repasse par les mêmes ports, et un lieu tapé avant
            # que cette liste existe ne doit pas disparaître de la liste
            liste = _ports.liste_du_bord(self.win)
            if self.win.journal is not None:
                liste.apprendre(self.win.journal.lieux_connus())
            self.ed_lieu.recharger()
            self.ed_lieu.set_valeur(p.lieu)
            voyages = [""] + (self.win.journal.voyages_connus() if self.win.journal else [])
            if [self.ed_voyage.itemText(i) for i in range(self.ed_voyage.count())] != voyages:
                self.ed_voyage.clear()
                self.ed_voyage.addItems(voyages)
            self.ed_voyage.setCurrentText(p.voyage)
            self._poser_libelle(p.libelle)
            if self.ed_note.toPlainText() != p.note:
                self.ed_note.setPlainText(p.note)
            for w in (self.ed_date, self.ed_voyage, self.ed_lieu, self.ed_libelle,
                      self.ed_libelle_autre, self.ed_note):
                w.setEnabled(not p.fige)
            self.b_new.setEnabled(self.win.journal is not None)
            self.b_save.setEnabled(not p.fige)
            self.b_freeze.setEnabled(not p.fige)
            if p.fige:
                # « figé le » est la date de la DERNIÈRE ÉCRITURE, c'est-à-dire
                # celle où l'on a figé — pas celle du point, qui est l'heure de
                # l'événement et peut la précéder de plusieurs jours
                self.lbl_etat.setText(
                    f"<b>{p.titre}</b> — point du {p.date_lisible}, figé le "
                    f"{p.modifie_lisible}. Il ne se modifie plus : pour préparer la suite, "
                    "ouvrez un nouveau point (copie intégrale de celui-ci).")
            elif not p.path:
                self.lbl_etat.setText(
                    f"<b>{p.titre}</b> — en cours, <b>pas encore enregistré</b>.")
            else:
                self.lbl_etat.setText(f"<b>{p.titre}</b> — en cours.")
            self._refresh_liste()
        finally:
            self._loading = False

    # --------------------------------------------------------------- libellé
    def _afficher_libelle_autre(self):
        """Le champ libre ne se montre que sous « Autre… » : autrement, il
        laisserait croire qu'on peut écrire à côté du menu."""
        self.ed_libelle_autre.setVisible(self.ed_libelle.currentText() == AUTRE)

    def _poser_libelle(self, libelle):
        """Range un libellé dans les deux champs.

        « Arrivée » et « Départ » vont au menu. Tout le reste — les moments
        plus fins, et surtout les libellés libres des points enregistrés
        avant que ce menu existe — passe par « Autre… » et garde son texte
        **mot pour mot** : relire un point ne doit jamais le renommer."""
        libelle = libelle or ""
        if libelle in LIBELLES_PHARES:
            self.ed_libelle.setCurrentIndex(self.ed_libelle.findText(libelle))
            self.ed_libelle_autre.setCurrentText("")
        elif not libelle:
            self.ed_libelle.setCurrentIndex(0)
            self.ed_libelle_autre.setCurrentText("")
        else:
            self.ed_libelle.setCurrentIndex(self.ed_libelle.findText(AUTRE))
            if self.ed_libelle_autre.currentText() != libelle:
                self.ed_libelle_autre.setCurrentText(libelle)
        self._afficher_libelle_autre()

    def _libelle_saisi(self):
        """Le libellé que disent les deux champs réunis."""
        tete = self.ed_libelle.currentText()
        if tete == AUTRE:
            return self.ed_libelle_autre.currentText().strip()
        return tete.strip()

    def _on_libelle_menu(self, _index=0):
        autre = self.ed_libelle.currentText() == AUTRE
        self._afficher_libelle_autre()
        if autre and not self._loading:
            self.ed_libelle_autre.setFocus()
        self._on_edit()

    def refresh_liste(self):
        """La liste seule : après une modification du point courant (lieu,
        libellé…) ou un recalcul, sans toucher aux champs de saisie."""
        self._refresh_liste()

    def _refresh_liste(self):
        points = list(reversed(self.win.journal.points())) if self.win.journal else []
        courant = self.win.point
        # la liste vient du disque : le point courant y est remplacé par son
        # état en mémoire (libellé tapé, modifications non enregistrées), sinon
        # la ligne montre ce qu'on a enregistré et non ce qu'on a sous les yeux
        if courant is not None:
            points = [courant if q.numero == courant.numero else q for q in points]
        self._points = points
        # le point courant non enregistré apparaît en tête, pour qu'on le voie
        lignes = []
        if courant is not None and not any(q is courant for q in self._points):
            lignes.append(courant)
        lignes.extend(self._points)
        self._points = lignes
        self.table.setRowCount(len(lignes))
        for r, p in enumerate(lignes):
            # un point figé montre l'instantané qu'il porte ; le point ouvert
            # montre ce qui est à l'écran en ce moment. Ce qui manque reste un
            # tiret : un déplacement absent n'est pas un déplacement nul.
            res = p.resultats or {}
            if courant is not None and p.numero == courant.numero and not p.fige:
                res = self.win.resultats_courants() or {}
            vals = [str(p.numero), p.voyage or "—", p.date_lisible,
                    p.lieu or "—", p.libelle or "—",
                    _ou_tiret(res.get("deplacement")), self._cargaison(p, res),
                    p.etat + ("" if p.path else " (non enregistré)"),
                    p.modifie_lisible, _debut_note(p.note)]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if p.fige and c == C_ETAT:
                    item.setForeground(QColor(theme.TEXT_DIM))
                if courant is not None and p.numero == courant.numero:
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                self.table.setItem(r, c, item)
            # la note entière en infobulle : la colonne n'en montre que le début
            if p.note:
                self.table.item(r, C_NOTE).setToolTip(p.note)
            # les deux dates, expliquées là où on se pose la question
            self.table.item(r, C_DATE).setToolTip(
                "La date du point : l'événement (départ, arrivée, relevé en mer), "
                "telle que le bord l'a saisie.")
            self.table.item(r, C_MODIF).setToolTip(
                "La date du dernier enregistrement de ce point. Elle ne se saisit "
                "pas.\n« — » : point jamais enregistré, ou enregistré par une "
                "version antérieure qui ne datait pas ses écritures.")
            # le verdict a quitté le tableau (neuf colonnes se lisent, onze
            # non) mais pas le journal : il reste en infobulle sur l'état, et
            # en toutes lettres dans la vue Stabilité et l'export CSV. Pas de
            # couleur ici : celle de la colonne État dit figé ou en cours.
            verdict = res.get("verdict")
            if verdict and verdict != "—":
                self.table.item(r, C_ETAT).setToolTip(f"Verdict : {verdict}")
            if p.fige and p.resultats:
                infobulle = ("Valeurs lues à l'écran quand le point a été figé"
                             f" (moteur {p.resultats.get('version', '?')})")
                for c in (C_DEPL, C_CARGO):
                    self.table.item(r, c).setToolTip(infobulle)
        n = len([p for p in lignes if p.path])
        self.lbl_liste.setText(
            f"{n} point(s) enregistré(s). Les valeurs des points figés sont celles lues à "
            "l'écran au moment où ils ont été figés ; ouvrir un point recalcule tout."
            if n else "Le journal est vide : enregistrez ou figez le point courant.")

    def _cargaison(self, p, res):
        """Le poids de la cargaison seule : les charges posées, sans les
        soutes ni le lège.

        L'instantané du point figé prime s'il le porte — c'est ce qui a été lu
        à l'écran ce jour-là. Sinon on additionne les charges posées du point
        lui-même : ce n'est pas un calcul, c'est l'inventaire archivé avec lui,
        donc il est aussi vrai pour un point figé que pour le point ouvert."""
        v = res.get("cargaison")
        if v not in (None, ""):
            return str(v)
        try:
            return _poids(p.poids_cargaison_t)
        except (AttributeError, TypeError, ValueError):
            return "—"

    def _selection(self):
        r = self.table.currentRow()
        if r < 0 or r >= len(self._points):
            return None
        return self._points[r]

    # ------------------------------------------------------------- édition
    def _on_edit(self, *_a):
        if self._loading or self.win.point is None or self.win.point.fige:
            return
        p = self.win.point
        p.horodatage = self.ed_date.dateTime().toString(Qt.DateFormat.ISODate)[:16]
        # le NOM du port (« Le Havre »), jamais son étiquette : c'est lui
        # qu'on relira dans le fichier du point dans deux ans
        p.lieu = self.ed_lieu.valeur()
        p.voyage = self.ed_voyage.currentText().strip()
        p.libelle = self._libelle_saisi()
        p.note = self.ed_note.toPlainText()
        self.changed.emit()

    # ------------------------------------------------------------- actions
    def ouvrir(self):
        p = self._selection()
        if p is not None:
            self.win.open_point(p)

    def nouveau_depuis(self):
        p = self._selection()
        if p is not None:
            self.win.new_point(depuis=p)

    def supprimer(self):
        p = self._selection()
        if p is not None:
            self.win.delete_point(p)
