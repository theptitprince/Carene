# -*- coding: utf-8 -*-
"""Assistant de création de navire : fenêtre guidée, page par page.

Non modale à dessein : les étapes de calage et de tracé demandent de cliquer
sur les plans de la fenêtre principale, qui reste donc utilisable.
L'état des étapes est *déduit du projet*, jamais mémorisé : on peut revenir
en arrière, corriger, l'assistant se recale tout seul.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .project import KIND_CONTOUR

def rail_style():
    return f"""
QFrame#rail {{ background: {theme.BG_DEEP}; border-right: 1px solid {theme.BORDER_SOFT}; }}
QFrame#railItem {{ background: transparent; border-left: 3px solid transparent; }}
QFrame#railItem[state="current"] {{
    background: {theme.SURFACE}; border-left: 3px solid {theme.ACCENT};
}}
QLabel#railNum {{
    background: {theme.SURFACE_2}; color: {theme.TEXT_FAINT};
    border-radius: 11px; min-width: 22px; max-width: 22px;
    min-height: 22px; max-height: 22px; font-weight: bold; font-size: 11px;
}}
QLabel#railNum[state="current"] {{ background: {theme.ACCENT}; color: {theme.ACCENT_TEXT}; }}
QLabel#railNum[state="done"] {{ background: {theme.OK}; color: #FFFFFF; }}
QLabel#railText {{ color: {theme.TEXT_FAINT}; font-size: 12px; }}
QLabel#railText[state="current"] {{ color: {theme.TEXT}; font-weight: bold; }}
QLabel#railText[state="done"] {{ color: {theme.TEXT_DIM}; }}

QLabel#pageTitle {{ font-size: 17px; font-weight: bold; color: {theme.TEXT}; }}
QLabel#pageSub {{ color: {theme.TEXT_DIM}; font-size: 12px; }}
QFrame#footer {{ background: {theme.SURFACE}; border-top: 1px solid {theme.BORDER_SOFT}; }}
QFrame#card {{
    background: {theme.SURFACE}; border: 1px solid {theme.BORDER_SOFT};
    border-radius: 8px;
}}
QListWidget {{
    background: {theme.SURFACE}; border: 1px solid {theme.BORDER_SOFT};
    border-radius: 8px; padding: 4px; outline: 0;
}}
QListWidget::item {{ padding: 7px 8px; border-radius: 5px; color: {theme.TEXT_DIM}; }}
QListWidget::item:hover {{ background: {theme.SURFACE_2}; color: {theme.TEXT}; }}
QListWidget::item:selected {{ background: {theme.ACCENT_SOFT}; color: {theme.ACCENT_DARK}; }}
"""


def _pill(text="", tone="todo"):
    lbl = QLabel(text)
    lbl.setObjectName("pill")
    lbl.setProperty("tone", tone)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return lbl


def _set_pill(lbl, text, tone):
    lbl.setText(text)
    lbl.setProperty("tone", tone)
    lbl.style().unpolish(lbl)
    lbl.style().polish(lbl)
    lbl.setVisible(bool(text))


def _hint(text):
    lbl = QLabel(text)
    lbl.setObjectName("hint")
    lbl.setWordWrap(True)
    return lbl


def _button(text, slot, accent=False, ghost=False, icon_name=None):
    b = QPushButton(text)
    if accent:
        b.setProperty("accent", "1")
    if ghost:
        b.setProperty("ghost", "1")
    if icon_name:
        b.setIcon(theme.icon(icon_name, theme.TEXT))
    b.clicked.connect(slot)
    return b


# ---------------------------------------------------------------- pages
class Page(QWidget):
    """Page d'assistant : titre, sous-titre, corps, pastille d'état."""

    changed = Signal()   # l'état du projet a changé -> rafraîchir toute l'appli
    touched = Signal()   # simple frappe -> rafraîchir l'assistant seulement

    key = ""
    title = ""
    subtitle = ""

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 18)
        lay.setSpacing(12)

        head = QVBoxLayout()
        head.setSpacing(3)
        t = QLabel(self.title)
        t.setObjectName("pageTitle")
        s = QLabel(self.subtitle)
        s.setObjectName("pageSub")
        s.setWordWrap(True)
        head.addWidget(t)
        head.addWidget(s)
        lay.addLayout(head)

        self.status = _pill()
        self.status.setVisible(False)
        lay.addWidget(self.status)

        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        lay.addLayout(self.body)
        lay.addStretch(1)
        self.build()

    # à surcharger
    def build(self):
        pass

    def refresh(self):
        pass

    def is_done(self) -> bool:
        return False

    # raccourcis
    @property
    def project(self):
        return self.win.project

    @property
    def deck(self):
        return self.win.current_deck


class PageShip(Page):
    key, title = "nom", "Nommer le navire"
    subtitle = ("Chaque navire est décrit par un fichier de configuration que "
                "le logiciel de chargement lira ensuite. Commençons par son nom.")

    def build(self):
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("ex. MON NAVIRE")
        self.edit.textChanged.connect(self._on_name)
        self.body.addWidget(QLabel("Nom du navire"))
        self.body.addWidget(self.edit)
        self.body.addWidget(_hint(
            "Vous pourrez le modifier plus tard. Ce nom sert de titre de fenêtre "
            "et de nom de fichier par défaut."))

    def _on_name(self, text):
        self.project.ship_name = text.strip()
        self.win.setWindowTitle(
            f"Carène — {self.project.ship_name}" if self.project.ship_name
            else "Carène — assistant navire")
        self.touched.emit()

    def refresh(self):
        if self.edit.text() != self.project.ship_name:
            self.edit.blockSignals(True)
            self.edit.setText(self.project.ship_name)
            self.edit.blockSignals(False)
        _set_pill(self.status, "Navire nommé" if self.is_done() else "", "ok")

    def is_done(self):
        return bool(self.project.ship_name)


class PageProfile(Page):
    key, title = "profil", "Importer le profil longitudinal"
    subtitle = ("Le profil est la vue maîtresse : c'est elle qui porte les "
                "hauteurs. Importez le plan de coupe longitudinale — DXF, PDF "
                "ou image (plan des capacités, plan d'ensemble…).")

    def build(self):
        row = QHBoxLayout()
        row.addWidget(_button("Choisir le plan du profil (DXF, PDF ou image)…",
                              self._import, accent=True, icon_name="image"))
        row.addWidget(_button("Choisir dans le catalogue…", self._catalogue,
                              icon_name="image"))
        row.addStretch(1)
        self.body.addLayout(row)
        self.file_lbl = _hint("")
        self.body.addWidget(self.file_lbl)
        self.body.addWidget(_hint(
            "Le <b>catalogue</b> est la réserve de plans PDF du navire : les "
            "plans du chantier y entrent une fois, avec leur titre et leur "
            "référence, et l'on y revient pour affecter une page à une vue — "
            "sans rechercher le fichier sur le disque."))
        self.body.addWidget(_hint(
            "Formats acceptés : <b>DXF</b>, <b>PDF</b>, PNG, JPG, BMP, TIFF "
            "(décision D-9). Un DXF, ou un PDF vectoriel sorti d'AutoCAD, est "
            "le meilleur choix : ses traits portent leurs sommets, et le "
            "curseur s'y <b>accroche</b> au calage comme au décalquage. Un scan "
            "convient aussi — il n'a pas besoin d'être parfaitement droit. Pour "
            "un DWG, convertissez-le d'abord en DXF (ODA File Converter) : le "
            "logiciel ne lit pas le DWG."))

    def _import(self):
        self.win.import_profile()
        self.changed.emit()

    def _catalogue(self):
        # « Autre fichier… » du catalogue ramène ici à la boîte de fichiers :
        # un bouton qui n'aboutit à rien vaut moins que pas de bouton
        if self.win.open_catalogue("profil", autre_fichier=True) == "autre":
            self.win.import_plan_fichier("profil")
        self.changed.emit()

    def refresh(self):
        import os
        prof = self.project.profile
        p = prof.image_path
        txt = f"Fichier : {os.path.basename(p)}" if p else ""
        if prof.from_pdf:
            txt += (f"  (PDF {os.path.basename(prof.pdf_path)}, page "
                    f"{prof.pdf_page + 1}, {prof.pdf_dpi} dpi)")
        self.file_lbl.setText(txt)
        _set_pill(self.status, "Profil chargé" if self.is_done() else "", "ok")

    def is_done(self):
        return bool(self.project.profile.image_path)


class PageProfileCal(Page):
    key, title = "calage_profil", "Caler le profil (X – Z)"
    subtitle = ("Caler, c'est donner au plan ses COORDONNÉES et son ÉCHELLE en "
                "une fois : cliquez 2 à 3 points dont vous connaissez les "
                "coordonnées, puis appliquez.")

    def build(self):
        self.body.addWidget(_hint(
            "<b>La recette, dans l'ordre :</b> 1. <b>PPAR × ligne de base</b> "
            "— ou le couple C.0 —, 2. <b>PPAV × ligne de base</b> — ou le "
            "dernier couple lisible —, 3. un <b>pont de hauteur connue</b>. "
            "Les deux premiers donnent l'échelle en longueur et l'origine des "
            "X. <b>Sur un PDF ou un DXF, ils suffisent</b> (une seule "
            "échelle) ; sur un scan, le troisième donne l'échelle en hauteur. "
            "Dans tous les cas, <b>contrôlez</b> que la ligne de chaque pont "
            "tombe à sa hauteur dans la grille.<br>"
            "Après chaque clic sur le profil, une petite fenêtre demande les "
            "coordonnées réelles du point. Les boutons <b>PPAR</b> et "
            "<b>PPAV</b> en tête de cette fiche posent l'abscisse ET Z = 0 "
            "d'un geste, d'après les perpendiculaires saisies dans "
            "« Création du navire › Identification et dimensions » ; "
            "<b>Ligne de base (Z = 0)</b> pose la hauteur seule, et « C.35 » "
            "prend l'abscisse dans la table des couples du navire.<br>"
            "Sur un plan DXF ou PDF, le curseur <b>s'accroche</b> aux traits : "
            "la barre d'état dit « accroche prête » dès que les sommets sont "
            "lus. Maj suspend l'accroche."))
        self.body.addWidget(_button("Cliquer les points sur le profil",
                                    self._start, accent=True, icon_name="target"))
        self.points = QListWidget()
        self.points.setMaximumHeight(110)
        self.body.addWidget(self.points)
        row = QHBoxLayout()
        row.addWidget(_button("Appliquer le calage", self._apply, icon_name="grid"))
        row.addWidget(_button("Tout effacer", self._clear, ghost=True,
                              icon_name="trash"))
        row.addStretch(1)
        self.body.addLayout(row)

    def _start(self):
        self.win.set_active("profil")
        self.win.start_mode("cal")
        self.changed.emit()

    def _apply(self):
        self.win.set_active("profil")
        self.win.apply_calibration()
        self.changed.emit()

    def _clear(self):
        self.win.set_active("profil")
        self.win.clear_calibration()
        self.changed.emit()

    def refresh(self):
        prof = self.project.profile
        self.points.clear()
        for i, cp in enumerate(prof.cal_points, start=1):
            a, b = cp["real"]
            label = cp.get("label") or "point sans intitulé"
            self.points.addItem(f"{i}.  {label}   —   X = {a:g} m,  Z = {b:g} m")
        if prof.calibration.valid:
            _set_pill(self.status, "Profil calé — vérifiez la grille", "ok")
        elif len(prof.cal_points) >= 2:
            _set_pill(self.status, "Points placés : appliquez le calage", "warn")
        elif prof.cal_points:
            _set_pill(self.status, "Encore un point au minimum", "warn")
        else:
            _set_pill(self.status, "", "todo")

    def is_done(self):
        return self.project.profile.calibration.valid


class PageDecks(Page):
    key, title = "ponts", "Définir les ponts"
    subtitle = ("Repérez les niveaux du navire sur le profil : fond de cale, "
                "entreponts, pont principal… Leur hauteur sera lue directement "
                "sur le plan calé.")

    def build(self):
        self.body.addWidget(_button("Cliquer les ponts sur le profil",
                                    self._start, accent=True, icon_name="decks"))
        self.body.addWidget(_hint(
            "À chaque clic sur le profil, la hauteur Z est pré-remplie : "
            "il ne reste qu'à nommer le pont. Un pont dessiné sur la même "
            "feuille qu'un autre peut reprendre son plan et son calage."))
        self.list = QListWidget()
        self.list.setMaximumHeight(140)
        self.body.addWidget(self.list)
        row = QHBoxLayout()
        row.addWidget(_button("Ajouter manuellement…", self._add, ghost=True))
        row.addWidget(_button("Supprimer", self._remove, ghost=True,
                              icon_name="trash"))
        row.addStretch(1)
        self.body.addLayout(row)

    def _start(self):
        self.win.start_mode("decks")
        self.changed.emit()

    def _add(self):
        self.win.add_deck_dialog()
        self.changed.emit()

    def _remove(self):
        i = self.list.currentRow()
        decks = self.project.sorted_decks()
        if 0 <= i < len(decks):
            self.project.decks.remove(decks[i])
            if self.win.current_deck is decks[i]:
                self.win.current_deck = None
            self.win.refresh_all()
            self.changed.emit()

    def refresh(self):
        self.list.clear()
        for d in self.project.sorted_decks():
            self.list.addItem(f"{d.name}    —    Z = {d.z:g} m")
        n = len(self.project.decks)
        _set_pill(self.status, f"{n} pont(s) défini(s)" if n else "",
                  "ok" if n else "todo")

    def is_done(self):
        return bool(self.project.decks)


class PageDeckPlans(Page):
    key, title = "plans_ponts", "Importer et caler le plan de chaque pont"
    subtitle = ("Pour chaque pont, importez sa vue de dessus (DXF, PDF ou "
                "image) et calez-la dans le repère du navire : coordonnées ET "
                "échelle.")

    def build(self):
        self.list = QListWidget()
        self.list.setMaximumHeight(130)
        self.list.currentRowChanged.connect(self._on_pick)
        self.body.addWidget(QLabel("Ponts du navire"))
        self.body.addWidget(self.list)
        self.body.addWidget(_hint(
            "<b>Calage d'un plan de pont, dans l'ordre :</b> 1. <b>PPAR sur "
            "la ligne de foi</b> (l'axe, Y = 0) — ou le couple C.0 —, 2. "
            "<b>PPAV sur la ligne de foi</b> — ou le dernier couple lisible "
            "— ; les boutons « PPAR » et « PPAV » de la fiche posent X et "
            "Y = 0 d'un geste. <b>Sur un PDF ou un DXF, ces deux points "
            "suffisent</b> : le plan n'a qu'une échelle, et l'accroche pose le "
            "curseur pile sur le <b>croisement</b> du trait du couple avec "
            "l'axe (cliquez ce croisement, pas le pied du trait). Puis "
            "<b>contrôlez</b> : le contour du pont doit tomber sur la coque des "
            "deux bords. Sur une <b>image scannée</b>, "
            "ajoutez un 3e point <b>hors de l'axe</b> dont vous connaissez Y "
            "(le bordé à la demi-largeur <b>B/2</b> au maître-couple) : un scan "
            "peut être étiré différemment dans les deux sens. Rappel : Y "
            "positif = bâbord.<br>"
            "« Sur l'axe » met Y = 0 pour n'importe quel point, et « C.35 » "
            "prend X dans la table des <b>couples</b> du navire. Sur un DXF ou "
            "un PDF, le curseur <b>s'accroche</b> aux traits du plan ; la "
            "barre d'état dit « accroche prête »."))
        row = QHBoxLayout()
        row.addWidget(_button("Importer le plan (DXF, PDF ou image)…", self._import,
                              accent=True, icon_name="image"))
        row.addWidget(_button("Choisir dans le catalogue…", self._catalogue,
                              icon_name="image"))
        row.addWidget(_button("Cliquer les points", self._start, icon_name="target"))
        row.addWidget(_button("Appliquer", self._apply, icon_name="grid"))
        row.addStretch(1)
        self.body.addLayout(row)
        self.points = QListWidget()
        self.points.setMaximumHeight(96)
        self.body.addWidget(self.points)

    def _on_pick(self, i):
        decks = self.project.sorted_decks()
        if 0 <= i < len(decks):
            self.win.set_current_deck(decks[i])
            self.win.refresh_wizard()

    def _import(self):
        self.win.import_deck_plan()
        self.changed.emit()

    def _catalogue(self):
        deck = self.deck or self.win.current_deck
        if deck is None:
            self.win.import_deck_plan()     # dit « sélectionnez un pont »
            return
        if self.win.open_catalogue(deck, autre_fichier=True) == "autre":
            self.win.import_plan_fichier(deck)
        self.changed.emit()

    def _start(self):
        self.win.set_active("pont")
        self.win.start_mode("cal")
        self.changed.emit()

    def _apply(self):
        self.win.set_active("pont")
        self.win.apply_calibration()
        self.changed.emit()

    def refresh(self):
        decks = self.project.sorted_decks()
        cur = self.list.currentRow()
        self.list.blockSignals(True)
        self.list.clear()
        for d in decks:
            if not d.plan.image_path:
                mark, state = "○", "plan à importer"
            elif not d.plan.calibration.valid:
                mark, state = "◐", f"{len(d.plan.cal_points)} point(s) — à caler"
            else:
                mark, state = "●", "calé"
            item = QListWidgetItem(f"{mark}  {d.name}  (Z={d.z:g})   —   {state}")
            self.list.addItem(item)
        if self.deck in decks:
            self.list.setCurrentRow(decks.index(self.deck))
        elif 0 <= cur < len(decks):
            self.list.setCurrentRow(cur)
        self.list.blockSignals(False)
        self.points.clear()
        if self.deck is not None:
            for i, cp in enumerate(self.deck.plan.cal_points, start=1):
                a, b = cp["real"]
                label = cp.get("label") or "point sans intitulé"
                self.points.addItem(
                    f"{i}.  {label}   —   X = {a:g} m,  Y = {b:g} m")
        left = [d.name for d in decks
                if not (d.plan.image_path and d.plan.calibration.valid)]
        if not decks:
            _set_pill(self.status, "Définissez d'abord des ponts", "warn")
        elif left:
            _set_pill(self.status, "Reste à faire : " + ", ".join(left), "warn")
        else:
            _set_pill(self.status, "Tous les plans de ponts sont calés", "ok")

    def is_done(self):
        decks = self.project.sorted_decks()
        return bool(decks) and all(
            d.plan.image_path and d.plan.calibration.valid for d in decks)


class PageCapacities(Page):
    key, title = "capacites", "Décalquer : contour de pont, cales, épontilles"
    subtitle = ("Sur le plan du pont sélectionné, décalquez la forme du pont, "
                "puis chaque cale, puis la structure qui l'encombre.")

    def build(self):
        row0 = QHBoxLayout()
        row0.addWidget(QLabel("Pont courant :"))
        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self._on_pick)
        row0.addWidget(self.combo, 1)
        self.body.addLayout(row0)
        row = QHBoxLayout()
        row.addWidget(_button("Contour du pont", self._contour,
                              icon_name="contour"))
        row.addWidget(_button("Cale", self._poly, accent=True,
                              icon_name="polygon"))
        row.addWidget(_button("Épontille", self._epontille,
                              icon_name="polygon"))
        row.addWidget(_button("Structure", self._interdit,
                              icon_name="contour"))
        row.addStretch(1)
        self.body.addLayout(row)
        self.body.addWidget(_hint(
            "<b>Contour de pont et cale</b> : cliquez les sommets du polygone, "
            "double-clic (ou <b>Entrée</b>) pour terminer ; <b>Retour arrière</b> "
            "retire le dernier sommet, <b>Échap</b> abandonne, <b>Maj</b> "
            "suspend l'accroche. Saisissez ensuite le <b>code</b> de la cale — "
            "le même que dans le classeur de données — et son étendue "
            "verticale, pré-remplie d'un pont à l'autre.<br>"
            "<b>Épontille</b> : un clic dans une cale, puis sa fiche. Cochez "
            "<b>fixe</b> si elle est de la structure (toujours en place, rien "
            "ne s'y pose) ; sinon elle est amovible et ne bloque que mise en "
            "place, escale par escale, dans le Chargement — glissez-la pour la "
            "déplacer, clic droit pour la supprimer.<br>"
            "<b>Structure</b> (descente, puits) : un rectangle glissé d'un "
            "coin à l'autre, dans une cale. C'est BLOQUANT : rien ne s'y "
            "posera.<br>"
            "Pour y voir clair sur un plan chargé, éteignez ce qui gêne dans "
            "le panneau <b>Calques</b> posé sur le plan.<br>"
            "<b>Retoucher un contour</b> : sélectionnez-le, glissez ses "
            "sommets (ils s'accrochent aux traits) ; pour en <b>ajouter</b> "
            "un, <b>clic droit sur un segment</b> → <i>Ajouter un sommet "
            "ici</i>, ou <b>double-clic</b> sur ce segment ; Suppr pour en "
            "retirer, Ctrl+Z pour annuler. Là où deux cales se recouvrent, un "
            "clic de plus au même endroit passe à la suivante.<br>"
            "<b>Verrouiller</b> : clic droit sur une cale → <i>Verrouiller la "
            "cale</i> (elle ne bouge plus du tout, trait tireté et 🔒), ou sur "
            "une poignée → <i>Verrouiller ce sommet</i> (carré plein). Deux "
            "cales d'un même pont qui se <b>chevauchent</b> sont signalées "
            "dans l'arbre et dans la barre d'état — c'est un avertissement, "
            "pas un refus."))
        self.list = QListWidget()
        self.body.addWidget(self.list)

    def _on_pick(self, i):
        decks = self.project.sorted_decks()
        if 0 <= i < len(decks):
            self.win.set_current_deck(decks[i])
            self.win.refresh_wizard()

    def _poly(self):
        self.win.start_mode("poly")
        self.changed.emit()

    def _contour(self):
        self.win.start_mode("contour")
        self.changed.emit()

    def _interdit(self):
        self.win.start_mode("interdit")
        self.changed.emit()

    def _epontille(self):
        self.win.start_mode("epontille")
        self.changed.emit()

    def refresh(self):
        decks = self.project.sorted_decks()
        self.combo.blockSignals(True)
        self.combo.clear()
        for d in decks:
            self.combo.addItem(f"{d.name} (Z={d.z:g})")
        if self.deck in decks:
            self.combo.setCurrentIndex(decks.index(self.deck))
        self.combo.blockSignals(False)
        self.list.clear()
        n = 0
        for d, c in self.project.all_capacities():
            if c.kind == KIND_CONTOUR:
                self.list.addItem(f"◇  contour de « {d.name} »")
            else:
                n += 1
                self.list.addItem(
                    f"■  {c.code}  —  {c.name or 'sans nom'}   "
                    f"(Z {c.z_min:g} → {c.z_max:g} m,  {round(c.fill*100)} %)")
        if n:
            _set_pill(self.status, f"{n} capacité(s) tracée(s)", "ok")
        elif self.deck is None or not self.deck.plan.calibration.valid:
            _set_pill(self.status, "Sélectionnez un pont dont le plan est calé",
                      "warn")
        else:
            _set_pill(self.status, "", "todo")

    def is_done(self):
        return any(c.kind != KIND_CONTOUR
                   for _, c in self.project.all_capacities())


class PageCalques(Page):
    """Les calques posés PAR-DESSUS les cales, une fois les contours tracés.

    Le bord résume ainsi son travail : « à la création de pont/cale on doit
    décalquer juste les contours des cales, épontilles fixes et coque, puis
    créer 2 calques contraignants : poids au m² et hauteur disponible, et un
    calque d'information ». Cette étape est ce « puis »."""

    key, title = "calques", "Poser les calques : charge, hauteur, information"
    subtitle = ("Deux calques qui SIGNALENT sans bloquer — la charge au m² et "
                "la hauteur libre — et un calque d'information dont rien ne "
                "dépend.")

    def build(self):
        row0 = QHBoxLayout()
        row0.addWidget(QLabel("Pont courant :"))
        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self._on_pick)
        row0.addWidget(self.combo, 1)
        self.body.addLayout(row0)
        row = QHBoxLayout()
        row.addWidget(_button("Charge t/m²", self._charge, accent=True,
                              icon_name="polygon"))
        row.addWidget(_button("Hauteur libre", self._hauteur,
                              icon_name="contour"))
        row.addWidget(_button("Information", self._info, icon_name="wand"))
        row.addStretch(1)
        self.body.addLayout(row)
        self.body.addWidget(_hint(
            "<b>Charge t/m²</b> : un polygone tracé DANS une cale, comme une "
            "cale ; la fiche demande le nom et la charge, pré-remplie avec "
            "celle de la cale. Un dépassement sera <b>signalé, jamais refusé</b> "
            "(décision D-12) — le solveur, lui, la respecte.<br>"
            "<b>Hauteur libre</b> : deux clics en coins opposés dans une cale, "
            "puis la hauteur en mètres. Une pile plus haute sera <b>signalée, "
            "jamais refusée</b> (décision D-21).<br>"
            "<b>Information</b> : une polyligne, un polygone, un point ou un texte — clés de "
            "saisissage, prise, remarque du bord. <b>Rien n'en dépend</b> : ni "
            "la pose, ni la stabilité, ni le solveur ne le lisent.<br>"
            "Chacun se choisit d'un clic sur le plan (ou dans l'arbre "
            "<i>Structure</i>), se retouche dans la colonne de droite, se "
            "supprime par <b>Suppr</b> ou par le clic droit, et <b>Ctrl+Z</b> "
            "annule."))
        self.list = QListWidget()
        self.body.addWidget(self.list)

    def _on_pick(self, i):
        decks = self.project.sorted_decks()
        if 0 <= i < len(decks):
            self.win.set_current_deck(decks[i])
            self.win.refresh_wizard()

    def _charge(self):
        self.win.start_mode("zone_charge")
        self.changed.emit()

    def _hauteur(self):
        self.win.start_mode("hauteur")
        self.changed.emit()

    def _info(self):
        self.win.start_mode("info")
        self.changed.emit()

    def _comptes(self):
        """(zones de charge, zones de hauteur, zones interdites, informations)"""
        from .items import hauteur_annoncee
        n_ch = n_h = n_int = 0
        for _d, c in self.project.all_capacities():
            n_ch += len(getattr(c, "zones_charge", None) or [])
            for o in getattr(c, "obstacles", None) or []:
                if hauteur_annoncee(o) > 0:
                    n_h += 1
                else:
                    n_int += 1
        n_info = sum(len(getattr(d, "annotations", None) or [])
                     for d in self.project.decks)
        return n_ch, n_h, n_int, n_info

    def refresh(self):
        decks = self.project.sorted_decks()
        self.combo.blockSignals(True)
        self.combo.clear()
        for d in decks:
            self.combo.addItem(f"{d.name} (Z={d.z:g})")
        if self.deck in decks:
            self.combo.setCurrentIndex(decks.index(self.deck))
        self.combo.blockSignals(False)
        from .items import hauteur_annoncee
        self.list.clear()
        for d, c in self.project.all_capacities():
            if c.kind == KIND_CONTOUR:
                continue
            for z in getattr(c, "zones_charge", None) or []:
                t = z.get("t_m2")
                self.list.addItem(
                    f"▨  {c.code}  ·  {z.get('nom') or 'zone de charge'}"
                    + (f"   {t:g} t/m²" if isinstance(t, (int, float)) else ""))
            for o in getattr(c, "obstacles", None) or []:
                h = hauteur_annoncee(o)
                nom = (o[4] if len(o) > 4 else "") or "zone interdite"
                self.list.addItem(
                    ("↧  " if h > 0 else "▩  ") + f"{c.code}  ·  {nom}"
                    + ("" if h > 0 else "   (bloquant)"))
        for d in self.project.sorted_decks():
            for a in getattr(d, "annotations", None) or []:
                self.list.addItem(
                    f"✎  {d.name}  ·  {a.get('texte') or a.get('type') or ''}")
        n_ch, n_h, n_int, n_info = self._comptes()
        if not self.is_done():
            _set_pill(self.status, "Décalquez d'abord des cales", "warn")
        elif n_ch or n_h or n_info:
            _set_pill(self.status,
                      f"{n_ch} charge · {n_h} hauteur · {n_int} interdite · "
                      f"{n_info} info", "ok")
        else:
            _set_pill(self.status, "Aucun calque posé — c'est permis", "todo")

    def is_done(self):
        """Étape FACULTATIVE : elle est « faite » dès qu'il y a des cales à
        habiller. Un navire peut n'avoir aucune zone particulière — exiger un
        calque pour continuer bloquerait l'assistant sur une case vide."""
        return any(c.kind != KIND_CONTOUR
                   for _, c in self.project.all_capacities())


class PageFinish(Page):
    key, title = "fin", "Vérifier et enregistrer"
    subtitle = ("Dernier contrôle avant d'enregistrer le fichier navire.")

    def build(self):
        self.recap = QLabel("")
        self.recap.setWordWrap(True)
        self.recap.setTextFormat(Qt.TextFormat.RichText)
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.addWidget(self.recap)
        self.body.addWidget(card)
        self.body.addWidget(_hint(
            "Contrôlez la vue isométrique : les ponts doivent s'empiler dans le "
            "bon ordre et les capacités tomber au bon endroit. La grille "
            "superposée aux plans doit coïncider avec les repères dessinés."))
        row = QHBoxLayout()
        row.addWidget(_button("Zoom ajusté sur toutes les vues",
                              lambda: self.win.zoom_fit(), ghost=True,
                              icon_name="fit"))
        row.addWidget(_button("Enregistrer les plans", self._save, accent=True,
                              icon_name="save"))
        row.addStretch(1)
        self.body.addLayout(row)
        self.body.addWidget(_hint(
            "Les plans sont écrits dans le dossier du navire, à côté de ses "
            "tables. Fermez ensuite cette fenêtre : le chargement et la "
            "stabilité se font depuis la fenêtre principale."))

    def _save(self):
        self.win.save_project()
        self.changed.emit()

    def refresh(self):
        p = self.project
        decks = p.sorted_decks()
        caps = [c for _, c in p.all_capacities() if c.kind != KIND_CONTOUR]
        profil = ("calé" if p.profile.calibration.valid
                  else f"<span style='color:{theme.WARN}'>non calé</span>")
        lines = [
            f"<b style='font-size:14px'>{p.ship_name or 'Navire sans nom'}</b><br>",
            f"Profil : {profil}",
            f"Ponts : {len(decks)}"
            + (" — " + ", ".join(f"{d.name} (Z={d.z:g})" for d in decks) if decks else ""),
            f"Capacités tracées : {len(caps)}",
        ]
        if caps:
            zmin = min(c.z_min for c in caps)
            zmax = max(c.z_max for c in caps)
            lines.append(f"Étendue verticale couverte : {zmin:g} → {zmax:g} m")
        lines.append("Dossier du navire : " + (
            p.navire_virtuel_path or
            f"<span style='color:{theme.WARN}'>non défini</span>"))
        self.recap.setText("<br>".join(lines))
        folder = getattr(self.win, "ship_folder", "") or p.navire_virtuel_path
        import os
        saved = folder and os.path.exists(os.path.join(folder, "geometrie.json"))
        _set_pill(self.status, "Plans enregistrés" if saved else "", "ok")

    def is_done(self):
        """Fait dès que les plans sont écrits dans le dossier du navire."""
        import os
        folder = getattr(self.win, "ship_folder", "") or self.project.navire_virtuel_path
        return bool(folder and os.path.exists(
            os.path.join(folder, "geometrie.json")))


PAGES = [PageShip, PageProfile, PageProfileCal, PageDecks,
         PageDeckPlans, PageCapacities, PageCalques, PageFinish]


# ---------------------------------------------------------------- rail
class RailItem(QFrame):
    clicked = Signal(int)

    def __init__(self, index, title, parent=None):
        super().__init__(parent)
        self.setObjectName("railItem")
        self.index = index
        lay = QHBoxLayout(self)
        lay.setContentsMargins(13, 9, 13, 9)
        lay.setSpacing(11)
        self.num = QLabel(str(index + 1))
        self.num.setObjectName("railNum")
        self.num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text = QLabel(title)
        self.text.setObjectName("railText")
        self.text.setWordWrap(True)
        lay.addWidget(self.num, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self.text, 1)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_state(self, state):
        self.num.setText("✓" if state == "done" else str(self.index + 1))
        for w in (self, self.num, self.text):
            w.setProperty("state", state)
            w.style().unpolish(w)
            w.style().polish(w)

    def mousePressEvent(self, event):
        self.clicked.emit(self.index)
        super().mousePressEvent(event)


# ---------------------------------------------------------------- fenêtre
class ShipWizard(QDialog):
    """Assistant guidé, non modal, piloté par l'état du projet."""

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self.setWindowTitle("Assistant — création du navire")
        self.setModal(False)
        self.resize(880, 580)
        self.setStyleSheet(rail_style())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)

        # rail
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(258)
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(0, 16, 0, 16)
        rl.setSpacing(2)
        head = QLabel("  CRÉATION DU NAVIRE")
        head.setStyleSheet(
            f"color:{theme.TEXT_FAINT};font-size:10px;font-weight:bold;"
            f"letter-spacing:1.5px;padding:0 13px 10px 13px;")
        rl.addWidget(head)
        self.rail_items = []
        for i, cls in enumerate(PAGES):
            it = RailItem(i, cls.title)
            it.clicked.connect(self.go_to)
            rl.addWidget(it)
            self.rail_items.append(it)
        rl.addStretch(1)
        # la vraie version, lue au même endroit que la fenêtre « À propos » :
        # un numéro écrit en dur dans le rail annonçait « Carène 0.5 » sur une
        # 2.14, et c'est le premier chiffre qu'on lit quand on rend compte
        # d'un ennui à terre
        from . import __version__
        version = QLabel(f"  Carène {__version__}")
        version.setStyleSheet(f"color:{theme.TEXT_FAINT};font-size:10px;padding:0 13px;")
        rl.addWidget(version)
        middle.addWidget(rail)

        # pages
        self.stack = QStackedWidget()
        self.pages = []
        for cls in PAGES:
            page = cls(win)
            page.changed.connect(self.on_page_changed)
            page.touched.connect(self.refresh)
            self.stack.addWidget(page)
            self.pages.append(page)
        middle.addWidget(self.stack, 1)
        outer.addLayout(middle, 1)

        # pied de page
        footer = QFrame()
        footer.setObjectName("footer")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(18, 11, 18, 11)
        fl.setSpacing(9)
        self.progress = QLabel("")
        self.progress.setStyleSheet(f"color:{theme.TEXT_FAINT};")
        fl.addWidget(self.progress)
        fl.addStretch(1)
        self.btn_close = _button("Fermer l'assistant", self.hide, ghost=True)
        self.btn_prev = _button("← Précédent", self.prev, ghost=True)
        self.btn_next = _button("Suivant →", self.next, accent=True)
        fl.addWidget(self.btn_close)
        fl.addWidget(self.btn_prev)
        fl.addWidget(self.btn_next)
        outer.addWidget(footer)

        self.index = 0
        self.refresh()

    def restyle(self):
        """Réapplique la feuille de style après un changement de thème."""
        self.setStyleSheet(rail_style())
        self.refresh()

    # ------------------------------------------------------------------ nav
    def go_to(self, index):
        self.index = max(0, min(index, len(self.pages) - 1))
        self.stack.setCurrentIndex(self.index)
        self.refresh()

    def next(self):
        if self.index < len(self.pages) - 1:
            self.go_to(self.index + 1)
        else:
            self.hide()

    def prev(self):
        self.go_to(self.index - 1)

    def on_page_changed(self):
        self.win.refresh_all()

    def first_unfinished(self) -> int:
        for i, p in enumerate(self.pages):
            if not p.is_done():
                return i
        return len(self.pages) - 1

    def jump_to_current_step(self):
        """Ouvre l'assistant sur la première étape non terminée."""
        self.go_to(self.first_unfinished())

    # ------------------------------------------------------------------ état
    def refresh(self):
        for p in self.pages:
            p.refresh()
        current = self.index
        for i, (item, page) in enumerate(zip(self.rail_items, self.pages)):
            if i == current:
                item.set_state("current")
            elif page.is_done():
                item.set_state("done")
            else:
                item.set_state("todo")
        done = sum(1 for p in self.pages if p.is_done())
        self.progress.setText(
            f"Étape {current + 1} sur {len(self.pages)}   ·   "
            f"{done}/{len(self.pages)} terminée(s)")
        self.btn_prev.setEnabled(current > 0)
        last = current == len(self.pages) - 1
        self.btn_next.setText("Terminer" if last else "Suivant →")
        self.btn_next.setEnabled(self.pages[current].is_done() or last)
        self.btn_next.setToolTip(
            "" if self.pages[current].is_done()
            else "Terminez cette étape pour continuer "
                 "(vous pouvez aussi cliquer une étape dans la colonne de gauche).")
