# -*- coding: utf-8 -*-
"""Fenêtre dédiée « Création du navire ».

Un programme dans le programme : sommaire non linéaire à gauche, fiche
détaillée à droite (à quoi ça sert / ce qu'il faut / comment faire / format
attendu), et les commandes réelles d'import et de saisie.

Les données vivent dans un `carene.core.navire_draft.NavireDraft`, qui écrit
un dossier « navire virtuel » exploitable directement par le moteur de calcul.
Le contenu rédactionnel est dans `ship_editor_content.py`.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .core.navire_draft import (
    CHAMPS_DIMENSIONS,
    CHAMPS_IDENTIFICATION,
    CHAMPS_LEGE,
    CHAMPS_VENT,
    NavireDraft,
    nom_de_dossier,
    to_float,
)
from .ship_editor_content import CONVENTIONS, SECTIONS, STEPS
from .saisie import SpinNombre

GLYPH = {"ok": "✓", "warn": "!", "todo": "○", "info": "i"}
PILL_TEXT = {"ok": "FAIT", "warn": "À VÉRIFIER", "todo": "À FAIRE"}

# Types de contenu proposés pour une capacité. La liste est ouverte : un
# dossier peut nommer autrement, le champ reste librement modifiable.
TYPES_CAPACITE = [
    "Sea Water",        # ballast
    "Freshwater",
    "Gasoil",
    "Oil",
    "Greywater",
    "Blackwater",
    "Urea",
    "Sludge",
]


def _status_color(statut):
    return {"ok": theme.OK, "warn": theme.WARN,
            "todo": theme.TEXT_FAINT, "info": theme.ACCENT}.get(
        statut, theme.TEXT_FAINT)


def _clear_layout(lay):
    while lay.count():
        item = lay.takeAt(0)
        w = item.widget()
        if w is not None:
            # hide() AVANT setParent(None) : un widget visible détaché de son
            # parent devient une fenêtre de premier niveau, que certains
            # gestionnaires de fenêtres affichent le temps d'une image — d'où
            # les fenêtres qui clignotaient à chaque redessin.
            w.hide()
            # setParent(None) retire immédiatement de l'affichage : deleteLater()
            # seul n'est honoré qu'au retour dans la boucle d'événements.
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            _clear_layout(item.layout())


def _pill(text, tone="todo"):
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
    lay.setContentsMargins(16, 14, 16, 16)
    lay.setSpacing(9)
    if title:
        t = QLabel(title)
        t.setObjectName("cardTitle")
        lay.addWidget(t)
    return frame, lay


def _body(text, dim=False):
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    if dim:
        lbl.setObjectName("hint")
    return lbl


def _bullet(marker, text, marker_color=None, bold_marker=False):
    row = QHBoxLayout()
    row.setSpacing(9)
    m = QLabel(marker)
    m.setFixedWidth(15)
    m.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
    style = f"color: {marker_color or theme.TEXT_FAINT};"
    if bold_marker:
        style += " font-weight: bold;"
    m.setStyleSheet(style)
    t = QLabel(text)
    t.setWordWrap(True)
    row.addWidget(m, 0, Qt.AlignmentFlag.AlignTop)
    row.addWidget(t, 1)
    return row


class _StepRow(QWidget):
    """Ligne du sommaire : pastille de statut colorée + intitulé, cliquable."""

    clicked = Signal(str)

    def __init__(self, key, titre, statut, parent=None):
        super().__init__(parent)
        self.key = key
        self.statut = statut
        self.selected = False
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(31)
        self.setObjectName("stepRow")
        self.setStyleSheet(
            "QWidget#stepRow, QWidget#stepRow > QLabel { background: transparent; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(11, 3, 9, 3)
        lay.setSpacing(9)
        self.glyph = QLabel(GLYPH.get(statut, "○"))
        self.glyph.setFixedWidth(13)
        self.glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.glyph.setStyleSheet("font-weight: bold;")
        self.label = QLabel(titre)
        lay.addWidget(self.glyph)
        lay.addWidget(self.label, 1)
        self._restyle()

    def set_status(self, statut):
        self.statut = statut
        self.glyph.setText(GLYPH.get(statut, "○"))
        self._restyle()

    def _restyle(self):
        self.glyph.setStyleSheet(
            f"color: {_status_color(self.statut)}; font-weight: bold; "
            "background: transparent;")
        if self.selected:
            self.label.setStyleSheet(f"color: {theme.ACCENT_DARK}; "
                                     "font-weight: bold; background: transparent;")
        else:
            self.label.setStyleSheet(f"color: {theme.TEXT_DIM}; "
                                     "background: transparent;")

    def set_selected(self, on):
        self.selected = on
        self._restyle()
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(5, 1, -5, -1)
        if self.selected or self._hover:
            p.setBrush(QColor(theme.ACCENT_SOFT if self.selected else theme.HOVER))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(r, 6, 6)
        p.end()


class ShipEditorWindow(QMainWindow):
    """Fenêtre « Création du navire » branchée sur un NavireDraft réel."""

    navire_saved = Signal(str)

    def __init__(self, parent=None, draft=None, project=None,
                 on_open_plans=None):
        super().__init__(parent)
        self.draft = draft or NavireDraft()
        self.project = project
        self.on_open_plans = on_open_plans
        self.save_path = self.draft.source_path or ""
        self._dernier_compte_rendu = []
        self._rows = {}
        self._all_steps = {s["key"]: s for s in STEPS}
        self._all_steps[CONVENTIONS["key"]] = CONVENTIONS
        self._order = [s["key"] for s in STEPS]
        self._status = {}
        # on ouvre sur la première étape : « par où commencer », qui explique
        # le classeur. C'est la question que se pose quelqu'un devant un
        # logiciel vierge, elle doit être la première chose à l'écran.
        self._current = self._order[0]

        self.setWindowTitle("Création du navire")
        self.resize(1320, 880)

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_content(), 1)
        root.addLayout(body, 1)
        self.setCentralWidget(central)

        self.refresh(keep_step=False)

    # ------------------------------------------------------------- bandeau
    def _build_header(self):
        bar = QFrame()
        bar.setObjectName("headerBar")
        bar.setStyleSheet(
            f"QFrame#headerBar {{ background: {theme.SURFACE}; "
            f"border-bottom: 1px solid {theme.BORDER_SOFT}; }}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(20, 13, 20, 13)
        lay.setSpacing(14)

        left = QVBoxLayout()
        left.setSpacing(2)
        self.lbl_name = QLabel("Nouveau navire")
        self.lbl_name.setStyleSheet(
            "background: transparent; font-size: 17px; font-weight: bold;")
        self.lbl_sub = QLabel("")
        self.lbl_sub.setStyleSheet(
            f"background: transparent; color: {theme.TEXT_DIM};")
        left.addWidget(self.lbl_name)
        left.addWidget(self.lbl_sub)
        lay.addLayout(left)
        lay.addStretch(1)

        self.pill_ready = _pill("—", "todo")
        self.pill_steps = _pill("—", "todo")
        lay.addWidget(self.pill_ready)
        lay.addWidget(self.pill_steps)

        btn_save = QPushButton("Enregistrer le navire")
        btn_save.setProperty("accent", "1")
        btn_save.clicked.connect(lambda: self.save_navire())
        btn_close = QPushButton("Fermer")
        btn_close.setProperty("ghost", "1")
        btn_close.clicked.connect(self.close)
        lay.addWidget(btn_save)
        lay.addWidget(btn_close)
        return bar

    # ------------------------------------------------------------- sommaire
    def _build_sidebar(self):
        wrap = QFrame()
        wrap.setObjectName("sidebar")
        wrap.setFixedWidth(318)
        wrap.setStyleSheet(
            f"QFrame#sidebar {{ background: {theme.SURFACE}; "
            f"border-right: 1px solid {theme.BORDER_SOFT}; }}")
        outer = QVBoxLayout(wrap)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(6, 12, 6, 12)
        lay.setSpacing(2)

        for skey, titre, desc, mini in SECTIONS:
            head = QVBoxLayout()
            head.setSpacing(1)
            h = QLabel(titre.upper())
            h.setStyleSheet(
                f"color: {theme.TEXT if mini else theme.TEXT_FAINT}; "
                "font-size: 10px; font-weight: bold; letter-spacing: 1px; "
                "background: transparent;")
            head.addWidget(h)
            d = QLabel(desc)
            d.setWordWrap(True)
            d.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10px; "
                            "background: transparent;")
            head.addWidget(d)
            box = QWidget()
            box.setObjectName("sectionHead")
            box.setStyleSheet("QWidget#sectionHead { background: transparent; }")
            box.setLayout(head)
            head.setContentsMargins(11, 12, 11, 5)
            lay.addWidget(box)
            for step in STEPS:
                if step["section"] != skey:
                    continue
                row = _StepRow(step["key"], step["titre"], "todo")
                row.clicked.connect(self.show_step)
                self._rows[step["key"]] = row
                lay.addWidget(row)

        lay.addSpacing(10)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {theme.BORDER_SOFT};")
        lay.addWidget(sep)
        conv = _StepRow(CONVENTIONS["key"], CONVENTIONS["titre"], "info")
        conv.clicked.connect(self.show_step)
        self._rows[CONVENTIONS["key"]] = conv
        lay.addWidget(conv)
        lay.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        return wrap

    def _build_content(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        self.content = QVBoxLayout(inner)
        self.content.setContentsMargins(26, 22, 26, 26)
        self.content.setSpacing(14)
        scroll.setWidget(inner)
        self._content_scroll = scroll
        return scroll

    # ------------------------------------------------------------- état
    def refresh(self, keep_step=True, redessiner=True):
        """Relit l'état du brouillon et met la fenêtre à jour.

        `redessiner=False` ne touche qu'au bandeau, au sommaire et au bloc
        « État » : la fiche affichée n'est pas reconstruite. C'est ce qu'il
        faut après la saisie d'un champ — reconstruire toute la page à chaque
        valeur détruisait le champ qui avait le focus et faisait clignoter
        l'affichage, pour rien : rien n'est calculé ici, `status()` ne fait que
        compter ce qui est renseigné.
        """
        self._status = self.draft.status(self.project)
        for key, row in self._rows.items():
            if key in self._status:
                row.set_status(self._status[key][0])
        n_ok = sum(1 for k in self._order
                   if self._status.get(k, ("todo",))[0] == "ok")
        nom = self.draft.identification.get("nom") or "Nouveau navire"
        self.lbl_name.setText(nom)
        self.lbl_sub.setText(self.save_path or "Non enregistré")
        pret = self.draft.ready_to_compute()
        self.pill_ready.setText("Prêt à calculer" if pret else "Pas encore calculable")
        self.pill_ready.setProperty("tone", "ok" if pret else "todo")
        self.pill_steps.setText(f"{n_ok} / {len(self._order)} étapes")
        for w in (self.pill_ready, self.pill_steps):
            w.style().unpolish(w)
            w.style().polish(w)
        self.setWindowTitle(f"Création du navire — {nom}")
        if redessiner:
            self.show_step(self._current)
        else:
            self._maj_etat()
            self._maj_pastille_etape()

    def _maj_pastille_etape(self):
        """Pastille de statut en tête de fiche, sans reconstruire la fiche."""
        pill = getattr(self, "_pill_step", None)
        if pill is None:
            return
        statut = self._status.get(self._current, (None,))[0]
        if self._current == CONVENTIONS["key"]:
            statut = "info"
        if statut not in PILL_TEXT:
            pill.setVisible(False)
            return
        pill.setVisible(True)
        pill.setText(PILL_TEXT[statut])
        pill.setProperty("tone", statut)
        pill.style().unpolish(pill)
        pill.style().polish(pill)

    def _maj_etat(self):
        """Réécrit le seul bloc « État » de la fiche courante.

        C'est la seule partie qui dépend de ce qu'on vient de saisir ; la
        reconstruire seule coûte quelques QLabel au lieu de toute la page."""
        box = getattr(self, "_etat_box", None)
        if box is None:
            return
        _clear_layout(box)
        etat = self._status.get(self._current, (None, []))[1]
        if self._current == CONVENTIONS["key"]:
            etat = []
        self._etat_frame.setVisible(bool(etat))
        for text, tone in etat:
            box.addLayout(_bullet(GLYPH.get(tone, "○"), text,
                                  marker_color=_status_color(tone),
                                  bold_marker=True))

    # ------------------------------------------------------------- fiche
    def show_step(self, key):
        step = self._all_steps.get(key)
        if step is None:
            return
        self._current = key
        for k, row in self._rows.items():
            row.set_selected(k == key)
        _clear_layout(self.content)

        statut, etat = self._status.get(key, (step.get("statut", "todo"), []))
        if key == CONVENTIONS["key"]:
            statut, etat = "info", []

        top = QHBoxLayout()
        top.setSpacing(10)
        title = QLabel(step["titre"])
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        title.setWordWrap(True)
        top.addWidget(title, 1)
        # la pastille est gardée sous la main : elle se met à jour seule après
        # chaque saisie, sans reconstruire la fiche
        self._pill_step = _pill(PILL_TEXT.get(statut, ""), statut)
        self._pill_step.setVisible(statut in PILL_TEXT)
        top.addWidget(self._pill_step, 0, Qt.AlignmentFlag.AlignTop)
        self.content.addLayout(top)

        if step.get("resume"):
            self.content.addWidget(_body(step["resume"], dim=True))

        frame, lay = _card("À quoi ça sert")
        lay.addWidget(_body(step["a_quoi"]))
        self.content.addWidget(frame)

        if step.get("il_faut"):
            frame, lay = _card("Ce qu'il vous faut sous la main")
            for line in step["il_faut"]:
                lay.addLayout(_bullet("•", line))
            self.content.addWidget(frame)

        if step.get("comment"):
            frame, lay = _card("Comment faire")
            for i, line in enumerate(step["comment"], 1):
                lay.addLayout(_bullet(f"{i}.", line, bold_marker=True))
            self.content.addWidget(frame)

        if step.get("format_rows"):
            frame, lay = _card("Format attendu")
            if step.get("format_intro"):
                lay.addWidget(_body(step["format_intro"], dim=True))
            lay.addWidget(self._format_table(step["format_rows"]))
            self.content.addWidget(frame)

        if step.get("notes"):
            frame, lay = _card("Bon à savoir")
            for line in step["notes"]:
                lay.addLayout(_bullet("⚠", line, marker_color=theme.WARN))
            self.content.addWidget(frame)

        panel = self._panel_for(key)
        if panel is not None:
            self.content.addWidget(panel)

        # bloc « État » toujours créé, même vide : il se remplit et se vide
        # tout seul au fil de la saisie (voir _maj_etat)
        frame, lay = _card("État")
        self._etat_frame, self._etat_box = frame, lay
        for text, tone in etat:
            lay.addLayout(_bullet(GLYPH.get(tone, "○"), text,
                                  marker_color=_status_color(tone),
                                  bold_marker=True))
        frame.setVisible(bool(etat))
        self.content.addWidget(frame)

        self.content.addStretch(1)
        self.content.addLayout(self._nav_row(key))
        self._content_scroll.verticalScrollBar().setValue(0)

    @staticmethod
    def _format_table(rows):
        t = QTableWidget(len(rows), 4)
        t.setHorizontalHeaderLabels(
            ["Renseignement", "Unité / repère", "Requis", "Exemple"])
        for r, (nom, unite, oblig, exemple) in enumerate(rows):
            for c, val in enumerate((nom, unite, oblig, exemple)):
                item = QTableWidgetItem(val)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                item.setToolTip(val)
                if c == 2:
                    item.setForeground(QColor(
                        {"oui": theme.OK, "recommandé": theme.WARN}.get(
                            val, theme.TEXT_FAINT)))
                t.setItem(r, c, item)
        header = t.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        t.verticalHeader().setVisible(False)
        t.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        t.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        t.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        t.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for r in range(len(rows)):
            t.setRowHeight(r, 27)
        t.setFixedHeight(27 * len(rows) + t.horizontalHeader().height() + 2)
        return t

    def _nav_row(self, key):
        row = QHBoxLayout()
        row.setSpacing(9)
        if key in self._order:
            i = self._order.index(key)
            if i > 0:
                prev = self._order[i - 1]
                b = QPushButton("←  " + self._all_steps[prev]["titre"])
                b.setProperty("ghost", "1")
                b.clicked.connect(lambda _=False, k=prev: self.show_step(k))
                row.addWidget(b)
            row.addStretch(1)
            if i < len(self._order) - 1:
                nxt = self._order[i + 1]
                b = QPushButton(self._all_steps[nxt]["titre"] + "  →")
                b.setProperty("accent", "1")
                b.clicked.connect(lambda _=False, k=nxt: self.show_step(k))
                row.addWidget(b)
        else:
            row.addStretch(1)
        return row

    # --------------------------------------------------------- panneaux réels
    def _panel_for(self, key):
        builders = {
            "classeur": self._panel_classeur,
            "couples": self._panel_couples,
            "validation": self._panel_validation,
            "identification": self._panel_identification,
            "hydro": self._panel_hydro,
            "kn": self._panel_kn,
            "lege": self._panel_lege,
            "criteres": self._panel_criteres,
            "capacites": self._panel_capacites,
            "envahissement": self._panel_envahissement,
            "vent": self._panel_vent,
            "profil": self._panel_plans,
            "ponts": self._panel_plans,
            "plans_ponts": self._panel_plans,
            "polygones": self._panel_plans,
            "recap": self._panel_recap,
        }
        b = builders.get(key)
        return b() if b else None

    def _form(self, title, champs, target):
        """Formulaire générique : une ligne par champ, écrit dans `target`."""
        frame, lay = _card(title)
        for cle, libelle, unite, requis in champs:
            row = QHBoxLayout()
            row.setSpacing(9)
            lbl = QLabel(libelle + (" *" if requis else ""))
            lbl.setWordWrap(True)
            lbl.setMinimumWidth(230)
            edit = QLineEdit()
            val = target.get(cle)
            edit.setText("" if val is None else str(val))
            edit.setPlaceholderText("—")
            numeric = unite != "texte"

            def commit(_=None, cle=cle, edit=edit, numeric=numeric):
                txt = edit.text().strip()
                if not txt:
                    target.pop(cle, None)
                elif numeric:
                    v = to_float(txt)
                    if v is None:
                        edit.setStyleSheet(f"border: 1px solid {theme.DANGER};")
                        return
                    target[cle] = v
                else:
                    target[cle] = txt
                edit.setStyleSheet("")
                # on ne redessine pas la fiche : le champ suivant garde le
                # focus, et rien ne clignote
                self.refresh(redessiner=False)

            edit.editingFinished.connect(commit)
            row.addWidget(lbl, 1)
            row.addWidget(edit, 1)
            u = QLabel("" if unite == "texte" else unite)
            u.setFixedWidth(28)
            u.setStyleSheet(f"color: {theme.TEXT_FAINT};")
            row.addWidget(u)
            lay.addLayout(row)
        hint = QLabel("Les champs marqués * sont nécessaires au calcul. "
                      "La valeur est enregistrée en quittant le champ.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return frame

    def _panel_identification(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(self._form("Identification", CHAMPS_IDENTIFICATION,
                                 self.draft.identification))
        lay.addWidget(self._form("Dimensions principales", CHAMPS_DIMENSIONS,
                                 self.draft.dimensions))
        return w

    def _panel_lege(self):
        return self._form("Navire lège", CHAMPS_LEGE, self.draft.lege)

    def _panel_vent(self):
        """Les quatre champs d'UNE configuration de référence, et l'import de
        la table qui les décrit TOUTES.

        Les deux coexistent : les champs suffisent à un navire à moteur, dont
        la surface au vent ne dépend que du tirant d'eau ; la table est ce
        qu'il faut à un voilier, dont elle dépend aussi de la toile dehors —
        et c'est elle que lisent les critères de vent à l'écran."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(self._form("Surface exposée au vent", CHAMPS_VENT,
                                 self.draft.vent))

        def do_import():
            self._run_import(
                self.draft.import_profils_vent,
                self._pick("Importer la table des surfaces au vent par "
                           "voilure", multi=False))

        def do_clear():
            self.draft.profils_vent_rows = []
            self.refresh()

        lay.addWidget(self._import_card(
            "Surfaces au vent par configuration de voilure (facultatif)", [
                ("Importer la table…", True, do_import),
                ("Effacer", False, do_clear)]))
        return w

    def _import_card(self, title, buttons):
        frame, lay = _card(title)
        row = QHBoxLayout()
        row.setSpacing(9)
        for label, primary, handler in buttons:
            b = QPushButton(label)
            b.setProperty("accent" if primary else "ghost", "1")
            b.clicked.connect(handler)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        return frame

    def _ask_trim(self):
        """Demande l'assiette d'une table qui n'en porte pas."""
        dlg = QWidget(self, Qt.WindowType.Dialog)
        # boîte minimale : un spin + OK, via QMessageBox impossible (pas de saisie)
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        d = QDialog(self)
        d.setWindowTitle("Assiette de la table")
        v = QVBoxLayout(d)
        v.addWidget(QLabel("À quelle assiette correspond ce fichier ?\n"
                           "(positive sur l'arrière, en mètres)"))
        spin = SpinNombre()
        spin.setRange(-20, 20)
        spin.setDecimals(3)
        spin.setSingleStep(0.5)
        spin.setSuffix(" m")
        v.addWidget(spin)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        v.addWidget(bb)
        dlg.deleteLater()
        return spin.value() if d.exec() else None

    def _run_import(self, fn, paths, needs_trim=False):
        """Applique `fn` à chaque fichier, en signalant proprement les erreurs."""
        if not paths:
            return
        trim = None
        reports, errors = [], []
        for p in paths:
            try:
                try:
                    reports.append(fn(p, trim) if needs_trim else fn(p))
                except ValueError as e:
                    if needs_trim and "assiette" in str(e).lower() and trim is None:
                        trim = self._ask_trim()
                        if trim is None:
                            return
                        reports.append(fn(p, trim))
                    else:
                        raise
            except Exception as e:
                errors.append(f"{os.path.basename(p)} : {e}")
        self.refresh()
        if errors:
            QMessageBox.warning(
                self, "Import",
                f"{len(reports)} fichier(s) importé(s), "
                f"{len(errors)} en échec :\n\n" + "\n".join(errors[:8]))
        else:
            self.statusBar().showMessage(
                f"{len(reports)} fichier(s) importé(s).", 6000)

    def _pick(self, titre, multi=True):
        filt = "Tables (*.csv *.txt *.xlsx *.xlsm);;Tous les fichiers (*)"
        if multi:
            paths, _ = QFileDialog.getOpenFileNames(self, titre, "", filt)
            return paths
        path, _ = QFileDialog.getOpenFileName(self, titre, "", filt)
        return [path] if path else []

    def _panel_hydro(self):
        def do_import():
            self._run_import(
                lambda p, t: self.draft.import_hydro(p, assiette=t),
                self._pick("Importer une ou plusieurs tables hydrostatiques"),
                needs_trim=True)

        def do_clear():
            self.draft.hydro_rows = []
            self.refresh()

        return self._import_card("Import", [
            ("Importer une table…", True, do_import),
            ("Tout effacer", False, do_clear)])

    def _panel_kn(self):
        def do_import():
            self._run_import(
                lambda p, t: self.draft.import_kn(p, assiette=t),
                self._pick("Importer les pantocarènes", multi=False),
                needs_trim=True)

        def do_clear():
            self.draft.kn_rows = []
            self.draft.kn_angles = []
            self.refresh()

        return self._import_card("Import", [
            ("Importer les pantocarènes…", True, do_import),
            ("Effacer", False, do_clear)])

    def _panel_capacites(self):
        def do_caps():
            self._run_import(self.draft.import_capacites,
                             self._pick("Importer la liste des capacités",
                                        multi=False))

        def do_jauges():
            paths = self._pick("Importer une ou plusieurs tables de jaugeage")

            def imp(p):
                nom = os.path.splitext(os.path.basename(p))[0].replace("_", " ")
                return self.draft.import_jauge(p, nom=nom)

            self._run_import(imp, paths)

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(self._import_card("Import", [
            ("Importer la liste des capacités…", True, do_caps),
            ("Importer des jaugeages…", False, do_jauges)]))
        lay.addWidget(self._table_capacites())
        return w

    def _table_capacites(self):
        """Contenu et densité de chaque capacité, modifiables ici.

        Le dossier donne ces deux renseignements, mais ils lui sont propres :
        un ballast peut devenir une soute, une soute changer de produit. Ils se
        règlent donc à la création du navire, une fois pour toutes — le relevé
        quotidien ne fait plus que porter une mesure en face de chaque
        capacité, sans jamais toucher à la liste.
        """
        frame, lay = _card("Contenu et densité")
        if not self.draft.capacites:
            lay.addWidget(_body("Importez d'abord la liste des capacités.",
                                dim=True))
            return frame
        lay.addWidget(_body(
            "Le contenu nomme la capacité dans le relevé ; le groupe la range "
            "(eau douce, combustible, ballast…) et donne les sous-totaux du "
            "relevé et du bilan des poids — laissez-le vide pour qu'il se "
            "déduise du contenu. La densité est celle du produit embarqué. Les "
            "volumes, poids et centres, eux, viennent des tables de jaugeage et "
            "ne se saisissent jamais.", dim=True))

        cols = ["Capacité", "Contenu", "Groupe", "Ballast", "Densité",
                "Volume net m³", "FSM max t·m"]
        t = QTableWidget(len(self.draft.capacites), len(cols))
        t.setHorizontalHeaderLabels(cols)
        t.verticalHeader().setVisible(False)
        head = t.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (5, 6):
            head.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        # colonnes portant un widget : ResizeToContents ne mesure que l'en-tête
        for c, w in ((1, 170), (2, 150), (3, 70), (4, 100)):
            head.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
            t.setColumnWidth(c, w)
        t.setMinimumHeight(260)

        for r, meta in enumerate(self.draft.capacites):
            nom = QTableWidgetItem(str(meta.get("Nom", "")))
            nom.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            t.setItem(r, 0, nom)

            combo = QComboBox()
            combo.setEditable(True)          # un dossier peut nommer autrement
            combo.addItems(TYPES_CAPACITE)
            courant = str(meta.get("Type", "") or "")
            if courant and courant not in TYPES_CAPACITE:
                combo.addItem(courant)
            combo.setCurrentText(courant)
            combo.currentTextChanged.connect(
                lambda txt, m=meta: self._set_meta(m, "Type", txt))
            t.setCellWidget(r, 1, combo)

            # groupe : vide = déduit du contenu. On montre la déduction dans
            # le champ de saisie (texte grisé) pour qu'on voie ce qu'il vaudra
            # sans avoir à l'écrire.
            from .core.groupes import GROUPES_USUELS, groupe_de_meta
            grp = QComboBox()
            grp.setEditable(True)
            grp.addItem("")
            grp.addItems(GROUPES_USUELS)
            existant = str(meta.get("Groupe", "") or "")
            if existant and existant not in GROUPES_USUELS:
                grp.addItem(existant)
            grp.setCurrentText(existant)
            grp.lineEdit().setPlaceholderText(groupe_de_meta(meta))
            grp.setToolTip("Vide : le groupe est déduit du contenu — ici « "
                           + groupe_de_meta(meta) + " ».")
            grp.currentTextChanged.connect(
                lambda txt, m=meta: self._set_meta(m, "Groupe", txt.strip()))
            t.setCellWidget(r, 2, grp)

            # « Ballast » explicite : c'est lui que le solveur de ballastage
            # consulte — le type textuel n'est qu'une aide, chaque chantier
            # ayant son vocabulaire
            from .core.ballast import est_ballast as _est_ballast
            from .core.navire import Capacity as _Cap
            chk = QCheckBox()
            chk.setChecked(_est_ballast(_Cap(str(meta.get("Nom", "")), meta, [])))
            chk.setToolTip("Le solveur de ballastage ne joue que sur les "
                           "capacités cochées ici.")
            chk.toggled.connect(
                lambda v, m=meta: self._set_meta(m, "Ballast", 1 if v else 0))
            cont = QWidget()
            cl = QHBoxLayout(cont)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cl.addWidget(chk)
            t.setCellWidget(r, 3, cont)

            sp = SpinNombre()
            sp.setRange(0.10, 3.00)
            sp.setDecimals(3)
            sp.setSingleStep(0.01)
            try:
                sp.setValue(float(meta.get("Densite", 1.0) or 1.0))
            except (TypeError, ValueError):
                sp.setValue(1.0)
            sp.valueChanged.connect(
                lambda v, m=meta: self._set_meta(m, "Densite", v))
            t.setCellWidget(r, 4, sp)

            for c, cle, fmt in ((5, "Volume_net_m3", "{:.3f}"),
                                (6, "FSM_max_tm", "{:.3f}")):
                try:
                    txt = fmt.format(float(meta.get(cle, 0.0) or 0.0))
                except (TypeError, ValueError):
                    txt = "—"
                item = QTableWidgetItem(txt)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled
                              | Qt.ItemFlag.ItemIsSelectable)
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                      | Qt.AlignmentFlag.AlignVCenter)
                t.setItem(r, c, item)
        lay.addWidget(t)
        return frame

    def _set_meta(self, meta, cle, valeur):
        """Écrit un renseignement de capacité sans reconstruire la fiche."""
        meta[cle] = valeur
        self.refresh(redessiner=False)

    def _panel_envahissement(self):
        def do_import():
            self._run_import(self.draft.import_envahissement,
                             self._pick("Importer les points d'envahissement",
                                        multi=False))

        return self._import_card("Import", [
            ("Importer une liste…", True, do_import)])

    def _panel_criteres(self):
        """Le profil du navire, puis la BIBLIOTHÈQUE des réglementations
        (D-79) : chacune avec son texte, son statut et ses seuils ; le profil
        en fait proposer ; on coche celles qui s'appliquent."""
        from .core import reglements as R
        frame, lay = _card("Profil du navire et réglementations")
        lay.addWidget(_body(
            "Décrivez le navire : Carène propose les réglementations de stabilité "
            "à l'état intact qui s'y appliquent. Cochez, décochez : c'est votre "
            "dossier approuvé qui fait foi. Une réglementation « à relire » a des "
            "seuils écrits sans avoir été rejoués sur un dossier approuvé.", dim=True))
        prof = self.draft.profil
        grille = QGridLayout()
        grille.setHorizontalSpacing(10)

        self.cb_type = QComboBox()
        self.cb_type.addItem("— non renseigné —", "")
        for code, nom in R.TYPES:
            self.cb_type.addItem(nom, code)
        self.cb_type.setCurrentIndex(max(0, self.cb_type.findData(prof.get("type", ""))))
        self.cb_prop = QComboBox()
        self.cb_prop.addItem("— non renseignée —", "")
        for code, nom in R.PROPULSIONS:
            self.cb_prop.addItem(nom, code)
        self.cb_prop.setCurrentIndex(max(0, self.cb_prop.findData(prof.get("propulsion", ""))))
        self.sp_vitesse = SpinNombre()
        self.sp_vitesse.setRange(0.0, 60.0)
        self.sp_vitesse.setDecimals(1)
        self.sp_vitesse.setSuffix(" nd")
        self.sp_vitesse.setValue(float(prof.get("vitesse_service_kn") or 0.0))
        self.sp_pax = SpinNombre()
        self.sp_pax.setRange(0.0, 100000.0)
        self.sp_pax.setDecimals(1)
        self.sp_pax.setSuffix(" t·m")
        self.sp_pax.setValue(float(prof.get("moment_passagers_tm") or 0.0))
        self.chk_bois = QCheckBox("Bois en pontée")
        self.chk_bois.setChecked("bois_en_pontee" in (prof.get("cargaisons") or []))

        for i, (lib, w) in enumerate((("Type de navire", self.cb_type),
                                      ("Propulsion", self.cb_prop),
                                      ("Vitesse de service", self.sp_vitesse),
                                      ("Moment dû aux passagers", self.sp_pax))):
            grille.addWidget(QLabel(lib), i // 2, (i % 2) * 2)
            grille.addWidget(w, i // 2, (i % 2) * 2 + 1)
        grille.addWidget(self.chk_bois, 2, 0, 1, 2)
        lay.addLayout(grille)

        def profil_change(*_a):
            p = self.draft.profil
            p["type"] = self.cb_type.currentData() or ""
            p["propulsion"] = self.cb_prop.currentData() or ""
            v = self.sp_vitesse.value()
            p["vitesse_service_kn"] = v if v > 0 else None
            m = self.sp_pax.value()
            p["moment_passagers_tm"] = m if m > 0 else None
            p["cargaisons"] = ["bois_en_pontee"] if self.chk_bois.isChecked() else []
            for k in [k for k, v in p.items() if v in (None, "", [])]:
                p.pop(k)

        for w in (self.cb_type, self.cb_prop):
            w.currentIndexChanged.connect(profil_change)
        for w in (self.sp_vitesse, self.sp_pax):
            w.valueChanged.connect(profil_change)
        self.chk_bois.toggled.connect(profil_change)

        b = QPushButton("Proposer d'après le profil")
        b.setProperty("accent", "1")

        def proposer():
            profil_change()
            self.draft.proposer_reglements()
            self.refresh(redessiner=False)
        b.clicked.connect(proposer)
        lay.addWidget(b)

        regs, messages = R.bibliotheque()
        retenus = set(self.draft.reglements_retenus_ids())
        proposes = {r.id for r, _x in R.proposer(
            R.profil_du_navire({"profil": prof, "dimensions": self.draft.dimensions}), regs)}
        self.cases_reglements = {}
        for rid in sorted(regs):
            r = regs[rid]
            box = QCheckBox(r.titre + ("   — proposée" if rid in proposes else ""))
            box.setChecked(rid in retenus)

            def toggled(state, rid=rid):
                self.draft.choisir_reglement(rid, bool(state))
                self.refresh(redessiner=False)
            box.stateChanged.connect(toggled)
            lay.addWidget(box)
            self.cases_reglements[rid] = box
            seuils = ", ".join(
                f"{c.libelle} {c.comparaison} {c.seuil:g} {c.unite}".strip()
                for c in r.criteres if c.seuil is not None)
            detail = (f"    {r.texte}. Statut : {R.STATUTS.get(r.statut, r.statut)}."
                      + (f" Seuils : {seuils}." if seuils else ""))
            s = QLabel(detail)
            s.setObjectName("hint")
            s.setWordWrap(True)
            if r.a_relire:
                s.setStyleSheet("color: #B8860B;")
            lay.addWidget(s)
        for m in messages:
            lay.addWidget(_body("Bibliothèque : " + m, dim=True))
        return frame

    # ------------------------------------------------------- le classeur
    def _tests_en_cours(self):
        """Les suites hors écran ne doivent pas rester bloquées sur une boîte
        modale : c'est la même convention que la fenêtre principale."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        return bool(app is not None and app.property("carene_tests"))

    def _nom_propose(self, suffixe):
        nom = nom_de_dossier(self.draft.identification.get("nom") or "NAVIRE")
        return f"{nom}_dossier_de_stabilite{suffixe}"

    def _panel_classeur(self):
        frame, lay = _card("Le classeur du navire")
        lay.addWidget(_body(
            "Un seul fichier pour tout le dossier : une feuille par table, les "
            "colonnes déjà nommées, et une explication sur chaque intitulé "
            "(survolez-le dans le tableur). Remplissez-le à votre rythme, puis "
            "importez-le ici en une fois.", dim=True))
        row = QHBoxLayout()
        row.setSpacing(9)
        for label, primary, handler in (
                ("Créer le classeur type à remplir…", True,
                 lambda: self.creer_classeur_type()),
                ("Créer les gabarits CSV…", False,
                 lambda: self.creer_gabarits_csv()),
                ("Importer un classeur rempli…", True,
                 lambda: self.importer_classeur())):
            b = QPushButton(label)
            b.setProperty("accent" if primary else "ghost", "1")
            b.clicked.connect(handler)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(_body(
            "Les gabarits CSV rendent le même service sans tableur : un "
            "fichier par table, à importer ensuite étape par étape.", dim=True))
        if self._dernier_compte_rendu:
            lay.addWidget(self._table_compte_rendu(self._dernier_compte_rendu))
        return frame

    def creer_classeur_type(self, path=None):
        """Écrit le classeur VIDE à remplir. Rend le chemin écrit, ou ""."""
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Créer le classeur type à remplir",
                self._nom_propose(".xlsx"), "Classeur Excel (*.xlsx)")
            if not path:
                return ""
        if not path.lower().endswith((".xlsx", ".xlsm")):
            path += ".xlsx"
        try:
            feuilles = self.draft.ecrire_classeur_type(path)
        except Exception as e:
            self._dire("Classeur type", f"Échec : {e}", grave=True)
            return ""
        self.statusBar().showMessage(f"Classeur type écrit : {path}", 10000)
        self._dire("Classeur type",
                   f"Classeur écrit :\n{path}\n\n{len(feuilles)} feuilles, "
                   "une par table, vides et prêtes à remplir. Commencez par "
                   "la feuille « Lisez-moi ».")
        return path

    def creer_gabarits_csv(self, dossier=None):
        """Écrit les gabarits CSV (un fichier par table) dans un sous-dossier."""
        if dossier is None:
            dossier = QFileDialog.getExistingDirectory(
                self, "Où écrire les gabarits CSV ?", "")
            if not dossier:
                return ""
            dossier = os.path.join(dossier, self._nom_propose("_gabarits_csv"))
        try:
            fichiers = self.draft.ecrire_modeles_csv(dossier)
        except Exception as e:
            self._dire("Gabarits CSV", f"Échec : {e}", grave=True)
            return ""
        self.statusBar().showMessage(f"{len(fichiers)} gabarits écrits dans "
                                     f"{dossier}", 10000)
        self._dire("Gabarits CSV",
                   f"{len(fichiers)} fichiers écrits dans :\n{dossier}\n\n"
                   "Le LISEZ-MOI.md qui les accompagne donne, table par table, "
                   "les colonnes attendues et leur unité.")
        return dossier

    def importer_classeur(self, path=None):
        """Importe un classeur rempli et affiche le compte rendu par feuille."""
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Importer un classeur rempli", "",
                "Classeur Excel (*.xlsx *.xlsm);;Tous les fichiers (*)")
            if not path:
                return []
        try:
            rapport = self.draft.importer_classeur(path)
        except Exception as e:
            self._dire("Importer un classeur", f"Échec : {e}", grave=True)
            return []
        self._dernier_compte_rendu = rapport
        lus = sum(1 for _f, s, _m in rapport if s == "ok")
        self.refresh()
        self.statusBar().showMessage(
            f"{os.path.basename(path)} : {lus} feuille(s) lue(s).", 10000)
        self._montrer_compte_rendu(rapport)
        return rapport

    @staticmethod
    def _table_compte_rendu(rapport):
        """Le compte rendu d'import, feuille par feuille."""
        couleur = {"ok": theme.OK, "vide": theme.TEXT_FAINT,
                   "ignoree": theme.WARN, "erreur": theme.DANGER}
        t = QTableWidget(len(rapport), 3)
        t.setHorizontalHeaderLabels(["Feuille", "Lu", "Détail"])
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        head = t.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for r, (feuille, statut, message) in enumerate(rapport):
            for c, txt in enumerate((feuille, statut, message)):
                item = QTableWidgetItem(str(txt))
                item.setToolTip(str(message))
                if c == 1:
                    item.setForeground(QColor(couleur.get(statut,
                                                          theme.TEXT_FAINT)))
                t.setItem(r, c, item)
            t.setRowHeight(r, 25)
        t.setMinimumHeight(min(420, 25 * len(rapport) + 34))
        return t

    def _montrer_compte_rendu(self, rapport):
        """La boîte qui montre ce qui a été lu, feuille par feuille."""
        if self._tests_en_cours():
            return
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        d = QDialog(self)
        d.setWindowTitle("Import du classeur")
        d.resize(760, 520)
        v = QVBoxLayout(d)
        lus = sum(1 for _f, s, _m in rapport if s == "ok")
        vides = sum(1 for _f, s, _m in rapport if s == "vide")
        pb = sum(1 for _f, s, _m in rapport if s in ("erreur", "ignoree"))
        v.addWidget(_body(
            f"{lus} feuille(s) lue(s), {vides} vide(s) — une feuille vide est "
            f"ignorée sans dommage — et {pb} à regarder. Les étapes du "
            "sommaire montrent maintenant ce qui en a été tiré."))
        v.addWidget(self._table_compte_rendu(rapport))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(d.reject)
        bb.accepted.connect(d.accept)
        v.addWidget(bb)
        d.exec()

    def _dire(self, titre, message, grave=False):
        """Un message à l'utilisateur — muet pendant les tests hors écran."""
        if self._tests_en_cours():
            return
        if grave:
            QMessageBox.critical(self, titre, message)
        else:
            QMessageBox.information(self, titre, message)

    # ------------------------------------------------------- les couples
    def _panel_couples(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(self._import_card("Import", [
            ("Importer…", True, lambda: self._importer_couples()),
            ("Générer depuis les espacements…", True,
             lambda: self.generer_couples()),
            ("Tout effacer", False, lambda: self._effacer_couples())]))

        frame, box = _card("Table des couples")
        box.addWidget(_body(
            "Une ligne par couple : son numéro et son abscisse, dans le repère "
            "du navire. Les X des perpendiculaires, eux, se saisissent à "
            "l'étape « Identification et dimensions » (par exemple, la "
            "perpendiculaire arrière peut être à −0,25 m du couple 0).",
            dim=True))
        paires = self.draft.couples_paires()
        t = QTableWidget(len(paires), 2)
        t.setHorizontalHeaderLabels(["Couple (n)", "X (m)"])
        t.verticalHeader().setVisible(False)
        head = t.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for r, (n, x) in enumerate(paires):
            t.setItem(r, 0, QTableWidgetItem(str(n)))
            t.setItem(r, 1, QTableWidgetItem(f"{x:.3f}"))
            t.setRowHeight(r, 25)
        t.setMinimumHeight(300)
        t.itemChanged.connect(lambda _item: self._couples_depuis_table())
        self._table_couples = t
        box.addWidget(t)
        row = QHBoxLayout()
        row.setSpacing(9)
        b_add = QPushButton("Ajouter une ligne")
        b_add.setProperty("ghost", "1")
        b_add.clicked.connect(self._ajouter_couple)
        b_del = QPushButton("Supprimer la ligne")
        b_del.setProperty("ghost", "1")
        b_del.clicked.connect(self._supprimer_couple)
        row.addWidget(b_add)
        row.addWidget(b_del)
        row.addStretch(1)
        box.addLayout(row)
        lay.addWidget(frame)
        return w

    def _couples_depuis_table(self):
        """Relit le tableau après une saisie. Une ligne illisible est ignorée
        plutôt que refusée : on saisit un couple en deux temps (le numéro,
        puis l'abscisse), et refuser la première moitié effacerait la ligne."""
        t = getattr(self, "_table_couples", None)
        if t is None:
            return
        paires = []
        for r in range(t.rowCount()):
            a = t.item(r, 0)
            b = t.item(r, 1)
            n = to_float(a.text()) if a is not None else None
            x = to_float(b.text()) if b is not None else None
            if n is None or x is None or n < 0:
                continue
            paires.append((int(round(n)), x))
        self.draft.set_couples(paires)
        self.refresh(redessiner=False)

    def _ajouter_couple(self):
        t = getattr(self, "_table_couples", None)
        if t is None:
            return
        r = t.rowCount()
        t.insertRow(r)
        suivant = 0
        if r:
            precedent = t.item(r - 1, 0)
            v = to_float(precedent.text()) if precedent is not None else None
            suivant = int(v) + 1 if v is not None else r
        t.setItem(r, 0, QTableWidgetItem(str(suivant)))
        t.setItem(r, 1, QTableWidgetItem(""))
        t.setCurrentCell(r, 1)

    def _supprimer_couple(self):
        t = getattr(self, "_table_couples", None)
        if t is None or t.currentRow() < 0:
            return
        t.removeRow(t.currentRow())
        self._couples_depuis_table()

    def _effacer_couples(self):
        self.draft.couples = []
        self.refresh()

    def _importer_couples(self):
        self._run_import(self.draft.import_couples,
                         self._pick("Importer la table des couples",
                                    multi=False))

    def generer_couples(self, x_c0=None, troncons=None):
        """Table des couples déduite des espacements. Sans arguments, demande.

        Renvoie le compte rendu de `NavireDraft.generer_couples`, ou None si
        l'utilisateur renonce."""
        if x_c0 is None or troncons is None:
            reponse = self._dialogue_troncons()
            if reponse is None:
                return None
            x_c0, troncons = reponse
        try:
            rapport = self.draft.generer_couples(x_c0, troncons)
        except ValueError as e:
            self._dire("Générer les couples", str(e), grave=True)
            return None
        self.refresh()
        self.statusBar().showMessage(
            f"{rapport['couples']} couples générés, de {rapport['x'][0]:.3f} à "
            f"{rapport['x'][1]:.3f} m.", 8000)
        return rapport

    def _dialogue_troncons(self):
        """Petite boîte : X du couple 0, puis un tronçon par espacement."""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox
        d = QDialog(self)
        d.setWindowTitle("Générer la table des couples")
        v = QVBoxLayout(d)
        v.addWidget(_body(
            "Donnez l'abscisse du premier couple, puis un tronçon par "
            "espacement : « de C.0 à C.1 : 0,750 m », « de C.1 à C.15 : "
            "1,000 m »… Les tronçons doivent s'enchaîner : le couple de fin "
            "de l'un est le couple de début du suivant."))
        ligne = QHBoxLayout()
        ligne.addWidget(QLabel("X du premier couple (C.0) :"))
        spin = SpinNombre()
        spin.setRange(-100.0, 500.0)
        spin.setDecimals(3)
        spin.setSuffix(" m")
        spin.setValue(0.0)
        ligne.addWidget(spin)
        ligne.addStretch(1)
        v.addLayout(ligne)

        t = QTableWidget(1, 3)
        t.setHorizontalHeaderLabels(["Du couple", "Au couple", "Espacement (m)"])
        t.verticalHeader().setVisible(False)
        t.setItem(0, 0, QTableWidgetItem("0"))
        t.setItem(0, 1, QTableWidgetItem(""))
        t.setItem(0, 2, QTableWidgetItem(""))
        t.setMinimumHeight(180)
        v.addWidget(t)
        row = QHBoxLayout()
        b_add = QPushButton("Ajouter un tronçon")
        b_add.setProperty("ghost", "1")

        def ajouter():
            r = t.rowCount()
            t.insertRow(r)
            fin_precedente = t.item(r - 1, 1)
            t.setItem(r, 0, QTableWidgetItem(
                fin_precedente.text() if fin_precedente is not None else ""))
            t.setItem(r, 1, QTableWidgetItem(""))
            t.setItem(r, 2, QTableWidgetItem(""))

        b_add.clicked.connect(ajouter)
        b_del = QPushButton("Supprimer le tronçon")
        b_del.setProperty("ghost", "1")
        b_del.clicked.connect(
            lambda: t.removeRow(t.currentRow()) if t.currentRow() >= 0 else None)
        row.addWidget(b_add)
        row.addWidget(b_del)
        row.addStretch(1)
        v.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        v.addWidget(bb)
        if not d.exec():
            return None
        troncons = []
        for r in range(t.rowCount()):
            vals = [to_float(t.item(r, c).text()) if t.item(r, c) else None
                    for c in range(3)]
            if any(x is None for x in vals):
                continue
            troncons.append((int(round(vals[0])), int(round(vals[1])), vals[2]))
        if not troncons:
            return None
        return spin.value(), troncons

    # --------------------------------------------- cas de référence
    def _panel_validation(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(self._import_card("Contrôle", [
            ("Importer les cas…", True, lambda: self._importer_cas()),
            ("Rejouer les cas", True, lambda: self.rejouer_cas())]))

        # LA COHÉRENCE DES TABLES (D-82) : avant même un cas de référence, ce
        # que la physique impose aux tables importées
        from .core import controles_tables as C
        frame_c, box_c = _card("Cohérence des tables")
        constats = C.controler_brouillon(self.draft)
        if not constats:
            box_c.addWidget(_body("Aucune table importée, ou rien à signaler.", dim=True))
        couleurs = {C.ERREUR: "#B03030", C.AVERTISSEMENT: "#B8860B", C.INFO: "#4E5761"}
        noms = {C.ERREUR: "ERREUR", C.AVERTISSEMENT: "À VÉRIFIER", C.INFO: "info"}
        for c in constats:
            lbl = QLabel(f"<b>{noms[c.niveau]}</b> — {c.ligne()}")
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"color: {couleurs[c.niveau]};")
            box_c.addWidget(lbl)
        self.lbl_constats = [c.ligne() for c in constats]
        lay.addWidget(frame_c)

        frame, box = _card("Cas de référence")
        cas = self.draft.cas_reference
        if not cas:
            box.addWidget(_body(
                "Aucun cas saisi. Remplissez la feuille « Cas_de_reference » "
                "du classeur, ou importez un fichier à part : une ligne par "
                "cas du dossier approuvé.", dim=True))
            lay.addWidget(frame)
            return w
        box.addWidget(_body(
            f"{len(cas)} cas : "
            + ", ".join(str(c.get("Cas", "?")) for c in cas[:12])
            + (" …" if len(cas) > 12 else "")
            + ". « Rejouer les cas » recalcule chacun d'eux avec les tables "
            "importées et compare aux résultats du dossier.", dim=True))
        resultats = self.draft.rejeu_cas
        if resultats is None:
            box.addWidget(_body("Pas encore rejoués.", dim=True))
        else:
            box.addWidget(self._table_rejeu(resultats))
        lay.addWidget(frame)
        return w

    def _table_rejeu(self, resultats):
        """Une ligne par grandeur et par cas, l'écart en vert ou en rouge."""
        lignes = []
        for r in resultats:
            if r.get("erreur"):
                lignes.append((r["cas"], "Calcul impossible", r["erreur"],
                               "", "", "", False))
                continue
            for libelle, calc, att, ecart, tol, ok in r["lignes"]:
                lignes.append((r["cas"], libelle, f"{calc:.4f}", f"{att:.4f}",
                               f"{ecart:+.4f}", f"±{tol:g}", ok))
        cols = ["Cas", "Grandeur", "Calculé", "Dossier", "Écart", "Tolérance",
                ""]
        t = QTableWidget(len(lignes), len(cols))
        t.setHorizontalHeaderLabels(cols)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        head = t.horizontalHeader()
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for c in (0, 2, 3, 4, 5, 6):
            head.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        for r, (cas, libelle, calc, att, ecart, tol, ok) in enumerate(lignes):
            cells = [cas, libelle, calc, att, ecart, tol,
                     "✓" if ok else "écart"]
            for c, txt in enumerate(cells):
                item = QTableWidgetItem(str(txt))
                if c in (2, 3, 4, 5):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                          | Qt.AlignmentFlag.AlignVCenter)
                if c in (4, 6):
                    item.setForeground(QColor(theme.OK if ok else theme.DANGER))
                t.setItem(r, c, item)
            t.setRowHeight(r, 24)
        t.setMinimumHeight(min(460, 24 * len(lignes) + 34))
        return t

    def _importer_cas(self):
        self._run_import(self.draft.import_cas_reference,
                         self._pick("Importer les cas de référence",
                                    multi=False))

    def rejouer_cas(self):
        """Recalcule les cas de référence et affiche la comparaison."""
        if not self.draft.cas_reference:
            self._dire("Cas de référence",
                       "Importez d'abord au moins un cas du dossier approuvé.")
            return []
        if not self.draft.ready_to_compute():
            self._dire("Cas de référence",
                       "Il manque des données essentielles (tables "
                       "hydrostatiques, pantocarènes, lège) : le calcul n'est "
                       "pas encore possible.")
            return []
        try:
            resultats = self.draft.rejouer_cas_reference()
        except Exception as e:
            self._dire("Rejouer les cas", f"Échec : {e}", grave=True)
            return []
        total, ecarts = self.draft.ecarts_du_rejeu(resultats)
        self.refresh()
        self.statusBar().showMessage(
            f"{len(resultats)} cas rejoués : {total - ecarts}/{total} "
            "comparaisons dans la tolérance.", 12000)
        return resultats

    def _panel_plans(self):
        """Résumé des vues (profil, ponts) et ouverture de l'éditeur de plans
        sur la vue choisie. Les plans sont facultatifs : ils servent au
        placement graphique du chargement, jamais au calcul (D-10)."""
        frame, lay = _card("Plans du navire")
        proj = self.project
        if proj is None:
            lay.addWidget(_body(
                "Aucun fichier de plans n'est associé. Les plans sont "
                "facultatifs : ils servent au placement graphique du "
                "chargement, pas au calcul.", dim=True))
        else:
            vues = proj.views()
            cols = ["Vue", "Z (m)", "Plan", "Calé", "Capacités"]
            t = QTableWidget(len(vues), len(cols))
            t.setHorizontalHeaderLabels(cols)
            t.verticalHeader().setVisible(False)
            t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            head = t.horizontalHeader()
            head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            head.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            for c in (1, 3, 4):
                head.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
            for r, (key, label, deck, cal) in enumerate(vues):
                if not cal.image_path:
                    etat, tone = "○ sans plan", theme.TEXT_FAINT
                elif not cal.calibration.valid:
                    etat, tone = f"◐ {len(cal.cal_points)} pt, à caler", theme.WARN
                else:
                    res = cal.residuals()
                    etat = (f"✓ ±{max(res) * 100:.0f} cm" if len(res) > 2
                            else "✓ (2 points)")
                    tone = theme.OK
                fichier = os.path.basename(cal.image_path) if cal.image_path else "—"
                if cal.from_pdf:
                    fichier = f"{os.path.basename(cal.pdf_path)} p.{cal.pdf_page + 1}"
                nom = label + (f" ({deck.alias})" if deck is not None and deck.alias else "")
                cells = [nom, "—" if deck is None else f"{deck.z:g}", fichier, etat,
                         "—" if deck is None else str(deck.n_capacities())]
                for c, txt in enumerate(cells):
                    item = QTableWidgetItem(txt)
                    item.setToolTip(cal.image_path or "")
                    if c == 3:
                        item.setForeground(QColor(tone))
                    t.setItem(r, c, item)
                t.setRowHeight(r, 27)
            t.setFixedHeight(27 * len(vues) + t.horizontalHeader().height() + 4)
            t.selectRow(0)
            self._plans_table = t
            lay.addWidget(t)
            manque = [label for key, label, deck, cal in vues if not cal.ready]
            lay.addWidget(_body(
                ("À faire : " + ", ".join(manque) + "." if manque
                 else "Toutes les vues ont un plan calé.")
                + " Les contours servent à la vue et aux contrôles de pose, "
                "jamais au calcul de stabilité.", dim=True))
        row = QHBoxLayout()
        row.setSpacing(9)
        b = QPushButton("Ouvrir l'éditeur de plans sur cette vue…"
                        if proj is not None else "Ouvrir l'éditeur de plans…")
        b.setProperty("accent", "1")
        b.setEnabled(self.on_open_plans is not None)
        if self.on_open_plans is not None:
            b.clicked.connect(lambda: self.open_plans_on_selected_view())
        row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        return frame

    def open_plans_on_selected_view(self):
        """Ouvre l'éditeur de plans, sur la vue choisie dans le tableau."""
        if self.on_open_plans is None:
            return None
        editor = self.on_open_plans()
        t = getattr(self, "_plans_table", None)
        proj = self.project
        if editor is None or t is None or proj is None:
            return editor
        try:
            r = t.currentRow()
        except RuntimeError:
            return editor
        vues = proj.views()
        if 0 <= r < len(vues) and hasattr(editor, "show_view"):
            key, label, deck, cal = vues[r]
            editor.show_view(deck if deck is not None else "profil")
        return editor

    def _panel_recap(self):
        frame, lay = _card("Enregistrement")
        row = QHBoxLayout()
        row.setSpacing(9)
        b1 = QPushButton("Enregistrer le navire")
        b1.setProperty("accent", "1")
        b1.clicked.connect(lambda: self.save_navire())
        row.addWidget(b1)
        row.addStretch(1)
        cible, neuf = self.dossier_cible()
        note = QLabel(
            ("Le navire sera écrit dans un dossier À SON NOM :\n" if neuf
             else "Le navire est déjà enregistré ici — il y sera réécrit :\n")
            + cible
            + ("\n\nCopier ce dossier sur une clé suffit à emporter le navire "
               "sur un autre poste. L'application ne gère qu'un navire à la "
               "fois : c'est celui-ci qui s'ouvrira au prochain lancement."
               if neuf else ""))
        note.setObjectName("hint")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addLayout(row)
        return frame

    # --------------------------------------------------------- enregistrement
    def dossier_cible(self):
        """(dossier où enregistrer, est-ce un navire neuf ?).

        Un navire NEUF reçoit son propre dossier, à son nom, sous
        `navires/` à côté de l'application : c'est la promesse faite à l'étape
        « Identification » (« le nom saisi devient le nom du dossier de
        données »), et c'est ce qui permet d'emporter le navire tel quel. Un
        navire DÉJÀ enregistré, lui, ne bouge pas : le bord a pu le poser sur
        un disque partagé, ce n'est pas à l'enregistrement de le déménager.
        """
        from . import app_paths
        existe = bool(self.save_path) and os.path.exists(
            os.path.join(self.save_path, app_paths.MANIFEST))
        if existe:
            return self.save_path, False
        defaut = os.path.abspath(app_paths.DEFAULT_FOLDER)
        choisi = (self.save_path
                  and os.path.abspath(self.save_path) != defaut)
        if choisi:
            # emplacement explicitement désigné (« Ouvrir un autre dossier de navire… ») :
            # on le respecte, même s'il est encore vide
            return self.save_path, False
        nom = nom_de_dossier(self.draft.identification.get("nom") or "")
        return os.path.join(app_paths.DATA_DIR, "navires", nom), True

    def save_navire(self):
        if not self.draft.identification.get("nom"):
            QMessageBox.warning(self, "Enregistrer",
                                "Nommez d'abord le navire "
                                "(étape « Identification et dimensions »).")
            self.show_step("identification")
            return
        from . import app_paths
        path, neuf = self.dossier_cible()
        try:
            files = self.draft.save(path)
        except Exception as e:
            QMessageBox.critical(self, "Enregistrer", f"Échec : {e}")
            return
        if neuf:
            # l'application est mono-navire : le navire qu'on vient de créer
            # devient CELUI de l'installation, sinon il serait écrit sur le
            # disque sans que rien ne l'ouvre
            app_paths.set_ship_folder(path)
        self.save_path = path
        self.draft.source_path = path
        self.refresh()
        self.statusBar().showMessage(
            f"{len(files)} fichier(s) écrits dans {path}", 8000)
        self.navire_saved.emit(path)


class WelcomeScreen(QWidget):
    """Écran affiché dans la fenêtre principale quand aucun navire n'est ouvert."""

    create_requested = Signal()
    open_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        title = QLabel("Carène")
        title.setStyleSheet("font-size: 38px; font-weight: bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        col.addWidget(title)
        sub = QLabel("Chargement et stabilité")
        sub.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 16px;")
        sub.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        col.addWidget(sub)
        col.addSpacing(34)

        hint = QLabel("Aucun navire n'est ouvert.")
        hint.setStyleSheet("font-size: 13px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        col.addWidget(hint)
        col.addSpacing(16)

        btns = QHBoxLayout()
        btns.setSpacing(10)
        b_open = QPushButton("Ouvrir un navire…")
        b_open.setProperty("accent", "1")
        b_open.setMinimumWidth(180)
        b_open.clicked.connect(self.open_requested)
        b_new = QPushButton("Créer un navire…")
        b_new.setProperty("ghost", "1")
        b_new.setMinimumWidth(180)
        b_new.clicked.connect(self.create_requested)
        btns.addWidget(b_open)
        btns.addWidget(b_new)
        col.addLayout(btns)
        col.addSpacing(26)

        note = QLabel(
            "La création d'un navire — tables hydrostatiques, pantocarènes,\n"
            "capacités et plans — se fait dans une fenêtre dédiée.\n"
            "Menu  Navire › Créer ou modifier le navire…")
        note.setObjectName("hint")
        note.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        col.addWidget(note)

        row.addLayout(col)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)
