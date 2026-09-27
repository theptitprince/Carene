# -*- coding: utf-8 -*-
"""Boîtes de dialogue : calage, capacité, épontille, pont, import PDF ou DXF,
nouveau navire."""
from __future__ import annotations

import os
import re

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)
from .project import epontille_fixe
from .saisie import SpinEntier, SpinNombre


def _buttons(dlg, lay):
    b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                         | QDialogButtonBox.StandardButton.Cancel)
    b.accepted.connect(dlg.accept)
    b.rejected.connect(dlg.reject)
    lay.addWidget(b)


def _zspin(value=0.0, lo=-100.0, hi=100.0):
    s = SpinNombre()
    s.setRange(lo, hi)
    s.setDecimals(3)
    s.setSuffix(" m")
    s.setValue(value)
    return s


SUGGESTIONS_PROFIL = [
    "PPAR × ligne de base",
    "PPAV × ligne de base",
    "Couple C0 × ligne de base",
    "Ligne de base au milieu",
    "PPAR × pont principal",
    "PPAV × pont principal",
    "Livet de pont",
]

SUGGESTIONS_PONT = [
    "PPAR × ligne de foi",
    "PPAV × ligne de foi",
    "Ligne de foi × couple arrière",
    "Ligne de foi × couple avant",
    "Ligne de foi × C0",
    "Bordé bâbord au maître-couple (Y = B/2)",
    "Bordé tribord au maître-couple (Y = −B/2)",
    "Axe × maître-couple",
]


def parse_couple(text: str):
    """Numéro de couple tapé librement : « C.35 », « C35 », « c 35 », « 35 »
    → 35 ; None si ce n'est pas un couple."""
    m = re.fullmatch(r"\s*[cC]?\s*\.?\s*(\d{1,3})\s*", text or "")
    return int(m.group(1)) if m else None


def metres_fr(valeur: float, decimales: int = 3) -> str:
    """« −0,250 » : un nombre de mètres écrit comme on l'écrit en français.

    Les champs de saisie, eux, acceptent les deux séparateurs (`saisie.py`) ;
    ce qui est ÉCRIT au bord, en revanche, se lit avec une virgule."""
    return f"{float(valeur):.{decimales}f}".replace("-", "−").replace(".", ",")


# Ce que le bord cite en premier quand il dit comment il cale : « perpendiculaire
# arrière, perpendiculaire avant ». Ce sont les deux X que tout plan de chantier
# porte, et les seuls repères longitudinaux qu'on puisse affirmer sans lire une
# cote au cartouche. Le texte de l'aide, quand ils manquent, dit où les saisir.
MANQUE_PERPENDICULAIRES = (
    "Renseignez les X des perpendiculaires (Création du navire › "
    "Identification et dimensions) pour les proposer ici.")


class CalPointDialog(QDialog):
    """Intitulé et coordonnées navire réelles du point de calage cliqué.

    `couples` : table des couples du navire (`couples.csv`, X depuis C.0) ;
    quand elle existe, taper « C.35 » remplit X — on cale sur les traits de
    couples, pas sur une cote lue au cartouche (D-11). `snapped` : le point a
    été accroché à un sommet du PDF, on le dit (le pixel est alors exact).

    `perpendiculaires` : (X de la PPAR, X de la PPAV) lus dans `navire.json`
    (`app_paths.perpendiculaires`). Elles arment les BOUTONS DE REPÈRES
    RAPIDES en tête de la fiche : un clic pose l'abscisse ET la seconde
    coordonnée (ligne de base Z = 0 sur le profil, ligne de foi Y = 0 sur un
    pont), et écrit l'intitulé. C'est la recette que le bord décrit — « caler
    sur la perpendiculaire arrière, la perpendiculaire avant » — faite d'un
    geste au lieu de trois champs à remplir de tête."""

    def __init__(self, axes, index: int, parent=None, couples=None,
                 pixel=None, snapped=False, perpendiculaires=None):
        super().__init__(parent)
        ax1, ax2 = axes
        is_deck = ax2 == "Y"
        self.couples = list(couples or [])
        self.perpendiculaires = (tuple(perpendiculaires)
                                 if perpendiculaires else None)
        self._is_deck = is_deck
        self.setWindowTitle(f"Point de calage n°{index}")
        lay = QVBoxLayout(self)
        if is_deck:
            hint = ("Bons points pour un plan de pont : la PPAR puis la PPAV sur la\n"
                    "LIGNE DE FOI (Y = 0) — un bouton chacune — puis un point HORS AXE\n"
                    "dont vous connaissez Y : le bordé à la demi-largeur B/2 au\n"
                    "maître-couple, ou un couple hors axe. Une abscisse se prend aussi\n"
                    "dans la table des COUPLES, tapée « C.35 ».\n"
                    "Un calage, ce sont des coordonnées ET une échelle : deux points sur\n"
                    "l'axe donnent l'échelle en longueur, le troisième celle en largeur.\n"
                    "Rappel : Y positif = BÂBORD.")
        else:
            hint = ("Bons points pour le profil : la PPAR puis la PPAV sur la LIGNE DE\n"
                    "BASE (Z = 0) — un bouton chacune —, puis un point de hauteur\n"
                    "connue : un pont dont vous connaissez le Z.\n"
                    "Une abscisse se prend aussi dans la table des COUPLES, tapée\n"
                    "« C.35 » — coordonnées ET échelle en une fois.")
        lay.addWidget(QLabel(hint))
        if pixel is not None:
            where = QLabel(f"Pixel cliqué : ({pixel[0]:.1f} ; {pixel[1]:.1f})"
                           + ("  —  accroché à un sommet du plan" if snapped
                              else "  —  point libre (sans accroche)"))
            where.setObjectName("hint")
            lay.addWidget(where)
        lay.addLayout(self._reperes_rapides())

        form = QFormLayout()
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.addItem("")
        self.combo.addItems(SUGGESTIONS_PONT if is_deck else SUGGESTIONS_PROFIL)
        self.combo.setCurrentText("")
        self.combo.lineEdit().setPlaceholderText("ex. PPAR × ligne de base")
        self.spin1 = _zspin(lo=-10000, hi=10000)
        self.spin2 = _zspin(lo=-10000, hi=10000)
        form.addRow("Ce point est :", self.combo)
        self.edit_couple = None
        if self.couples and ax1 == "X":
            self.edit_couple = QLineEdit()
            self.edit_couple.setPlaceholderText(
                f"ex. C.35   (table du navire : C.0 à C.{len(self.couples) - 1})")
            self.edit_couple.textChanged.connect(self._on_couple)
            self.lbl_couple = QLabel("")
            self.lbl_couple.setObjectName("hint")
            form.addRow("Sur le couple :", self.edit_couple)
            form.addRow("", self.lbl_couple)
        if is_deck:
            # « Sur l'axe » est LE repère d'un plan de pont : la ligne de foi
            # est Y = 0, et deux points dessus valent la moitié d'un calage.
            # Le bord ne devinait pas qu'il fallait taper 0 : le bouton le dit
            # et le fait.
            ligne = QHBoxLayout()
            ligne.addWidget(self.spin2, 1)
            self.btn_axe = QPushButton("Sur l'axe (ligne de foi, Y = 0)")
            self.btn_axe.setProperty("ghost", "1")
            self.btn_axe.setToolTip(
                "Ce point est sur la ligne de foi : Y = 0. Deux points sur "
                "l'axe à des couples connus, puis un point hors axe, font un "
                "calage tenu.")
            self.btn_axe.clicked.connect(self.sur_laxe)
            ligne.addWidget(self.btn_axe)
            form.addRow(f"{ax1} :", self.spin1)
            form.addRow(f"{ax2} :", ligne)
        else:
            form.addRow(f"{ax1} :", self.spin1)
            form.addRow(f"{ax2} :", self.spin2)
        lay.addLayout(form)
        lay.addWidget(QLabel(
            "L'intitulé est facultatif mais recommandé : il s'affiche sur le plan\n"
            "à côté du repère, et permet de vérifier un calage des mois plus tard."))
        _buttons(self, lay)
        self.combo.setFocus()

    # ------------------------------------------------------- repères rapides
    def _reperes_rapides(self):
        """La rangée de boutons « PPAR / PPAV / ligne de base » et sa légende.

        Chaque bouton REMPLIT la fiche — abscisse, seconde coordonnée,
        intitulé — plutôt que de rappeler une valeur à recopier : c'est la
        différence entre proposer un repère et le poser. La légende dit d'où
        vient le chiffre, parce qu'un calage se vérifie des mois plus tard."""
        boite = QVBoxLayout()
        ligne = QHBoxLayout()
        ligne.addWidget(QLabel("Repères du navire :"))
        seconde = "ligne de base, Z = 0" if not self._is_deck \
            else "ligne de foi, Y = 0"
        self.btn_ppar = QPushButton("PPAR")
        self.btn_ppar.setProperty("ghost", "1")
        self.btn_ppar.setToolTip(
            "Perpendiculaire arrière, à son croisement avec la "
            f"{seconde} : les deux coordonnées du point d'un coup.")
        self.btn_ppar.clicked.connect(lambda: self.sur_perpendiculaire("AR"))
        self.btn_ppav = QPushButton("PPAV")
        self.btn_ppav.setProperty("ghost", "1")
        self.btn_ppav.setToolTip(
            "Perpendiculaire avant, à son croisement avec la "
            f"{seconde} : les deux coordonnées du point d'un coup.")
        self.btn_ppav.clicked.connect(lambda: self.sur_perpendiculaire("AV"))
        ligne.addWidget(self.btn_ppar)
        ligne.addWidget(self.btn_ppav)
        self.btn_base = None
        if not self._is_deck:
            # sur un pont, c'est « Sur l'axe » qui joue ce rôle, et il est
            # déjà posé contre le champ Y : deux boutons pour Y = 0 feraient
            # douter qu'ils font la même chose
            self.btn_base = QPushButton("Ligne de base (Z = 0)")
            self.btn_base.setProperty("ghost", "1")
            self.btn_base.setToolTip(
                "Ce point est sur la ligne de base : Z = 0. L'abscisse reste "
                "la vôtre (une perpendiculaire, un couple).")
            self.btn_base.clicked.connect(self.sur_ligne_de_base)
            ligne.addWidget(self.btn_base)
        ligne.addStretch(1)
        boite.addLayout(ligne)
        self.lbl_perp = QLabel("")
        self.lbl_perp.setObjectName("hint")
        self.lbl_perp.setWordWrap(True)
        boite.addWidget(self.lbl_perp)
        if self.perpendiculaires:
            x_ar, x_av = self.perpendiculaires
            self.lbl_perp.setText(
                f"PPAR = {metres_fr(x_ar)} m et PPAV = {metres_fr(x_av)} m "
                "depuis C.0, d'après navire.json.")
        else:
            # jamais un bouton gris sans explication : on dit où les saisir
            self.btn_ppar.setEnabled(False)
            self.btn_ppav.setEnabled(False)
            for b in (self.btn_ppar, self.btn_ppav):
                b.setToolTip(MANQUE_PERPENDICULAIRES)
            self.lbl_perp.setText(MANQUE_PERPENDICULAIRES)
        return boite

    def _seconde_a_zero(self, quoi):
        """Pose la seconde coordonnée à 0 et rend l'intitulé de ce croisement."""
        self.spin2.setValue(0.0)
        return f"{quoi} × " + ("ligne de foi" if self._is_deck
                               else "ligne de base")

    def sur_perpendiculaire(self, laquelle="AR"):
        """PPAR ou PPAV, sur la ligne de base (profil) ou la ligne de foi
        (pont) : X, la seconde coordonnée et l'intitulé d'un seul geste."""
        if not self.perpendiculaires:
            return
        x_ar, x_av = self.perpendiculaires
        avant = str(laquelle).upper().startswith("AV")
        x = x_av if avant else x_ar
        nom = "PPAV" if avant else "PPAR"
        self.spin1.setValue(float(x))
        intitule = self._seconde_a_zero(nom)
        if not self.combo.currentText().strip():
            self.combo.setCurrentText(intitule)
        self.lbl_perp.setText(
            f"{nom} = {metres_fr(x)} m depuis C.0, d'après navire.json.")

    def sur_ligne_de_base(self):
        """Ce point est sur la ligne de base : Z = 0, et l'intitulé le dit."""
        self.spin2.setValue(0.0)
        if not self.combo.currentText().strip():
            n = parse_couple(self.edit_couple.text()) if self.edit_couple else None
            self.combo.setCurrentText(f"C.{n} × ligne de base" if n is not None
                                      else "Ligne de base (Z = 0)")

    def sur_laxe(self):
        """Ce point est sur la ligne de foi : Y = 0, et l'intitulé le dit."""
        self.spin2.setValue(0.0)
        if not self.combo.currentText().strip():
            n = parse_couple(self.edit_couple.text()) if self.edit_couple else None
            self.combo.setCurrentText(f"Ligne de foi × C.{n}" if n is not None
                                      else "Ligne de foi (Y = 0)")

    def _on_couple(self, text):
        n = parse_couple(text)
        if n is None:
            self.lbl_couple.setText("" if not text.strip()
                                    else "Tapez un numéro de couple : C.35 ou 35.")
            return
        if n >= len(self.couples) or self.couples[n] != self.couples[n]:
            self.lbl_couple.setText(
                f"C.{n} n'est pas dans la table des couples du navire.")
            return
        x = self.couples[n]
        self.spin1.setValue(x)
        self.lbl_couple.setText(f"C.{n}  →  X = {x:.3f} m depuis C.0")
        if not self.combo.currentText().strip():
            self.combo.setCurrentText(
                f"Ligne de foi × C.{n}" if self.spin2.value() == 0 else f"C.{n}")

    def values(self):
        """(intitulé, coord1, coord2)"""
        return (self.combo.currentText().strip(),
                self.spin1.value(), self.spin2.value())


class CapacityDialog(QDialog):
    """Code / nom / étendue verticale / remplissage d'une capacité."""

    def __init__(self, parent=None, z_min=0.0, z_max=0.0, contour=False):
        super().__init__(parent)
        self.contour = contour
        self.setWindowTitle("Contour du pont" if contour else "Nouvelle capacité")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        if not contour:
            self.edit_code = QLineEdit()
            self.edit_code.setPlaceholderText("ex. CALE1, WB 4C, GO B")
            self.edit_name = QLineEdit()
            self.edit_name.setPlaceholderText("ex. Cale inter avant")
            self.spin_zmin = _zspin(z_min)
            self.spin_zmax = _zspin(z_max)
            self.spin_fill = QSpinBox()
            self.spin_fill.setRange(0, 100)
            self.spin_fill.setSuffix(" %")
            form.addRow("Code :", self.edit_code)
            form.addRow("Nom :", self.edit_name)
            form.addRow("Z bas :", self.spin_zmin)
            form.addRow("Z haut :", self.spin_zmax)
            form.addRow("Remplissage :", self.spin_fill)
            lay.addLayout(form)
            lay.addWidget(QLabel(
                "Le code doit correspondre au classeur de données (feuille Capacites)\n"
                "pour relier le dessin aux tables de jauge.\n"
                "Z bas / Z haut pré-remplis : de ce pont au pont supérieur."
            ))
        else:
            lay.addWidget(QLabel(
                "Le contour du pont sert à la vue isométrique (plaque du pont)\n"
                "et au contrôle visuel. Il n'entre dans aucun calcul."
            ))
        _buttons(self, lay)
        if not contour:
            self.edit_code.setFocus()

    def values(self):
        if self.contour:
            return ("CONTOUR", "", 0.0, 0.0, 0.0)
        return (self.edit_code.text().strip().upper(),
                self.edit_name.text().strip(),
                self.spin_zmin.value(), self.spin_zmax.value(),
                self.spin_fill.value() / 100.0)


class DeckDialog(QDialog):
    """Nom, hauteur et alias d'un pont (une vue) ; à la création, le plan et
    le calage d'un autre pont peuvent être repris — les niveaux d'un même
    navire sont souvent dessinés sur la même feuille."""

    def __init__(self, parent=None, name="", z=0.0, title="Nouveau pont",
                 alias="", decks=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._decks = list(decks or [])
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.edit_name = QLineEdit(name)
        self.edit_name.setPlaceholderText("ex. Fond de cale, Pont inter, Pont principal")
        self.spin_z = _zspin(z, lo=-5.0, hi=60.0)
        self.edit_alias = QLineEdit(alias)
        self.edit_alias.setPlaceholderText("ex. Tank Top, Freeboard Deck (nom du dossier)")
        form.addRow("Nom :", self.edit_name)
        form.addRow("Z (m /ligne de base) :", self.spin_z)
        form.addRow("Alias :", self.edit_alias)
        self.combo_copy = None
        if self._decks:
            self.combo_copy = QComboBox()
            self.combo_copy.addItem("— aucun : importer un plan ensuite —")
            for d in self._decks:
                etat = "calé" if d.plan.calibration.valid else "non calé"
                fichier = d.plan.image_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
                self.combo_copy.addItem(
                    f"{d.name}  (Z={d.z:g} · {fichier or 'sans plan'} · {etat})")
            form.addRow("Reprendre le plan de :", self.combo_copy)
        lay.addLayout(form)
        lay.addWidget(QLabel(
            "Astuce : en mode « Définir les ponts », le Z est pré-rempli\n"
            "avec la hauteur du point cliqué sur le profil."
            + ("\nReprendre le plan d'un autre pont copie l'image ET son "
               "calage :\nles ponts d'une même feuille se calent une seule fois."
               if self._decks else "")
        ))
        _buttons(self, lay)
        self.edit_name.setFocus()

    def values(self):
        return self.edit_name.text().strip() or "Pont", self.spin_z.value()

    def alias(self) -> str:
        return self.edit_alias.text().strip()

    def copy_from(self):
        """Le Deck dont reprendre le plan, ou None."""
        if self.combo_copy is None or self.combo_copy.currentIndex() <= 0:
            return None
        return self._decks[self.combo_copy.currentIndex() - 1]


class PdfImportDialog(QDialog):
    """Choix de la page, de la rotation et de la résolution d'un plan PDF.

    La page choisie est rendue en image dans le dossier du navire ; c'est
    cette image que tout le reste du logiciel voit. Les traits vectoriels de
    la page servent en plus à l'accroche du curseur (module `pdf_plan`)."""

    def __init__(self, pdf_path, parent=None, dpi=200, page=0):
        super().__init__(parent)
        from . import pdf_plan
        self._pdf = pdf_plan
        self.path = pdf_path
        self.setWindowTitle("Importer un plan PDF")
        self.resize(760, 520)
        self.infos = pdf_plan.page_info(pdf_path)

        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            f"<b>{os.path.basename(pdf_path)}</b> — {len(self.infos)} page(s). "
            "Choisissez la page à rendre ; la rotation s'ajoute à celle du "
            "fichier. Les traits du PDF resteront accrochables au calage et "
            "au tracé."))
        row = QHBoxLayout()
        self.pages = QListWidget()
        self.pages.setMaximumWidth(260)
        for i, (w, h, rot) in enumerate(self.infos):
            self.pages.addItem(
                f"Page {i + 1}  —  {w:.0f} × {h:.0f} mm"
                + (f"  (tournée {rot}°)" if rot else ""))
        # `page` : la page déjà choisie dans le CATALOGUE des plans. Rouvrir la
        # fiche sur la page 1 après l'avoir désignée dans le catalogue ferait
        # chercher deux fois la même chose.
        self.pages.setCurrentRow(max(0, min(int(page or 0), len(self.infos) - 1)))
        self.pages.currentRowChanged.connect(self._update)
        row.addWidget(self.pages)
        self.preview = QLabel("")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(360, 300)
        self.preview.setStyleSheet("background: #ffffff; border: 1px solid #c8c8c8;")
        row.addWidget(self.preview, 1)
        root.addLayout(row)

        form = QFormLayout()
        self.combo_rot = QComboBox()
        for r in pdf_plan.ROTATIONS:
            self.combo_rot.addItem(f"{r}°", r)
        self.combo_rot.currentIndexChanged.connect(self._update)
        self.spin_dpi = SpinEntier()
        self.spin_dpi.setRange(50, 600)
        self.spin_dpi.setSingleStep(25)
        self.spin_dpi.setValue(dpi)
        self.spin_dpi.setSuffix(" dpi")
        self.spin_dpi.valueChanged.connect(self._update_size)
        form.addRow("Rotation :", self.combo_rot)
        form.addRow("Résolution :", self.spin_dpi)
        self.lbl_size = QLabel("")
        self.lbl_size.setObjectName("hint")
        form.addRow("Image rendue :", self.lbl_size)
        root.addLayout(form)
        _buttons(self, root)
        self._update()

    def _update(self, *_):
        page = self.page()
        try:
            data = self._pdf.apercu_png(self.path, page, self.rotation(), 420)
            pm = QPixmap()
            pm.loadFromData(data, "PNG")
            self.preview.setPixmap(pm.scaled(
                self.preview.size() - QSize(8, 8),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        except Exception as e:      # aperçu impossible : on le dit, on continue
            self.preview.setText(f"Aperçu impossible : {e}")
        self._update_size()

    def _update_size(self, *_):
        try:
            w, h = self._pdf.taille_rendu(self.path, self.page(), self.rotation(),
                                          self.dpi())
        except Exception as e:
            self.lbl_size.setText(str(e))
            return
        mo = w * h * 4 / 1e6
        trop = max(w, h) > self._pdf.PIXELS_MAX_PAR_COTE
        self.lbl_size.setText(
            f"{w} × {h} pixels, environ {mo:.0f} Mo affichés"
            + ("  —  TROP GRAND : baissez la résolution" if trop
               else ("  —  lourd : 150 dpi suffit pour un A0" if mo > 200 else "")))

    def page(self) -> int:
        return max(0, self.pages.currentRow())

    def rotation(self) -> int:
        return int(self.combo_rot.currentData())

    def dpi(self) -> int:
        return int(self.spin_dpi.value())

    def values(self):
        """(page, rotation, dpi)"""
        return self.page(), self.rotation(), self.dpi()


class CatalogueDialog(QDialog):
    """Le CATALOGUE des plans PDF du navire : les choisir au lieu de les
    rechercher.

    Le bord demande « un catalogue de plans PDF » : les plans du chantier
    entrent une fois dans le dossier du navire et l'on y revient — page 3 du
    plan des cales pour l'entrepont, page 1 du plan d'ensemble pour le profil
    — sans rouvrir une boîte de fichiers ni se souvenir où le PDF traîne.

    La fenêtre ne fait qu'AFFICHER et CHOISIR : c'est l'éditeur qui importe
    ensuite la page retenue, par le même chemin qu'un import ordinaire
    (`PdfImportDialog` puis `import_pdf`). Ce qu'elle rend :

    - `choix()` → (chemin absolu du PDF, page à partir de 0), ou None ;
    - `veut_autre_fichier()` → le bouton « Autre fichier… » a été pressé, et
      l'appelant doit ouvrir la boîte de fichiers habituelle.

    « Utilisé par » n'est pas mémorisé : il est DÉDUIT des vues du projet
    (`catalogue_plans.utilisations`), pour qu'un plan remplacé ne laisse
    jamais une inscription périmée derrière lui.
    """

    def __init__(self, ship_folder, parent=None, project=None, vue="",
                 autre_fichier=False, dossier_depart=""):
        super().__init__(parent)
        from . import catalogue_plans, pdf_plan
        self._cat_mod = catalogue_plans
        self._pdf = pdf_plan
        self.ship_folder = ship_folder or ""
        self.project = project
        self.vue = vue or ""
        self._dossier_depart = dossier_depart or ""
        self._choix = None
        self._autre = False
        self._infos = []           # pages du plan sélectionné
        self.setWindowTitle("Catalogue des plans")
        self.resize(900, 600)

        root = QVBoxLayout(self)
        self.lbl_intro = QLabel("")
        self.lbl_intro.setWordWrap(True)
        root.addWidget(self.lbl_intro)

        row = QHBoxLayout()
        gauche = QVBoxLayout()
        gauche.addWidget(QLabel("Plans du navire"))
        self.liste = QListWidget()
        self.liste.setMinimumWidth(330)
        self.liste.currentRowChanged.connect(self._on_plan)
        gauche.addWidget(self.liste, 1)
        row.addLayout(gauche, 1)

        milieu = QVBoxLayout()
        milieu.addWidget(QLabel("Pages"))
        self.pages = QListWidget()
        self.pages.setMaximumWidth(210)
        self.pages.currentRowChanged.connect(self._on_page)
        milieu.addWidget(self.pages, 1)
        row.addLayout(milieu)

        self.preview = QLabel("")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(320, 300)
        self.preview.setStyleSheet("background: #ffffff; border: 1px solid #c8c8c8;")
        row.addWidget(self.preview, 1)
        root.addLayout(row, 1)

        self.lbl_etat = QLabel("")
        self.lbl_etat.setObjectName("hint")
        self.lbl_etat.setWordWrap(True)
        root.addWidget(self.lbl_etat)

        barre = QHBoxLayout()
        self.btn_ajouter = QPushButton("Ajouter un PDF…")
        self.btn_ajouter.setToolTip(
            "Copier un ou plusieurs plans PDF dans le dossier du navire : ils "
            "voyagent alors avec lui.")
        self.btn_ajouter.clicked.connect(self.ajouter_des_pdf)
        self.btn_renommer = QPushButton("Renommer…")
        self.btn_renommer.setToolTip("Changer le titre sous lequel ce plan est "
                                     "proposé (le fichier, lui, ne bouge pas).")
        self.btn_renommer.clicked.connect(self.renommer_le_plan)
        self.btn_retirer = QPushButton("Retirer")
        self.btn_retirer.setToolTip(
            "Ne plus proposer ce plan. Le PDF reste dans plans/ : les vues qui "
            "s'en servent gardent leur accroche.")
        self.btn_retirer.clicked.connect(self.retirer_le_plan)
        for b in (self.btn_ajouter, self.btn_renommer, self.btn_retirer):
            b.setProperty("ghost", "1")
            barre.addWidget(b)
        barre.addStretch(1)
        self.btn_autre = QPushButton("Autre fichier…")
        self.btn_autre.setProperty("ghost", "1")
        self.btn_autre.setToolTip(
            "Importer un plan qui n'est pas au catalogue (DXF, PDF ou image).")
        self.btn_autre.clicked.connect(self._sur_autre_fichier)
        self.btn_autre.setVisible(bool(autre_fichier))
        barre.addWidget(self.btn_autre)
        self.btn_utiliser = QPushButton("Utiliser cette page pour la vue courante…")
        self.btn_utiliser.setProperty("accent", "1")
        self.btn_utiliser.setDefault(True)
        self.btn_utiliser.clicked.connect(self._sur_utiliser)
        barre.addWidget(self.btn_utiliser)
        self.btn_fermer = QPushButton("Fermer")
        self.btn_fermer.setProperty("ghost", "1")
        self.btn_fermer.clicked.connect(self.reject)
        barre.addWidget(self.btn_fermer)
        root.addLayout(barre)
        self.rafraichir()

    # ------------------------------------------------------------- garnir
    def rafraichir(self, fichier_a_choisir=""):
        """Relit le catalogue et les utilisations, et regarnit la liste."""
        self.cat = self._cat_mod.charger(self.ship_folder)
        self.uses = self._cat_mod.utilisations(self.cat, self.project)
        self.entrees = list(self.cat.get("plans", []))
        garde = fichier_a_choisir or (self.entree_courante() or {}).get("fichier")
        self.liste.blockSignals(True)
        self.liste.clear()
        for e in self.entrees:
            uses = self.uses.get(e.get("fichier"), [])
            bouts = [e.get("titre") or e.get("fichier")]
            if e.get("reference"):
                bouts.append(e["reference"])
            bouts.append(f"{e.get('pages', 0)} page(s)")
            texte = "   ·   ".join(bouts)
            phrase = self._cat_mod.phrase_utilisation(uses)
            if phrase:
                texte += "\n" + phrase
            it = QListWidgetItem(texte)
            it.setToolTip(e.get("fichier", ""))
            self.liste.addItem(it)
        self.liste.blockSignals(False)
        vise = next((i for i, e in enumerate(self.entrees)
                     if e.get("fichier") == garde), 0 if self.entrees else -1)
        self.liste.setCurrentRow(vise)
        self._on_plan(vise)
        pour = f" pour la vue « {self.vue} »" if self.vue else ""
        self.lbl_intro.setText(
            "Les plans PDF du navire, rangés une fois dans son dossier "
            "<b>plans/</b> : choisissez le plan, puis la page à employer"
            + pour + ".<br>Un navire est un dossier qu'on emporte — un plan "
            "ajouté ici part avec lui, PDF compris, et ses traits restent "
            "accrochables."
            if self.entrees else
            "<b>Le catalogue est vide.</b> Ajoutez les plans PDF du chantier : "
            "ils seront copiés dans le dossier du navire, listés ici avec leur "
            "titre, et une page s'affectera à une vue en deux clics.")

    def _on_plan(self, index):
        e = self.entree_courante()
        self.pages.blockSignals(True)
        self.pages.clear()
        self._infos = []
        if e is not None:
            chemin = self.chemin_courant()
            try:
                self._infos = self._pdf.page_info(chemin)
            except Exception as err:
                self._infos = []
                self.lbl_etat.setText(f"Plan illisible : {err}")
            for i, (w, h, rot) in enumerate(self._infos):
                self.pages.addItem(
                    f"Page {i + 1}  —  {w:.0f} × {h:.0f} mm"
                    + (f"  ({rot}°)" if rot else ""))
        self.pages.blockSignals(False)
        if self._infos:
            # la page DÉJÀ employée par la vue courante, si c'est celle-là :
            # on rouvre là où le bord s'était arrêté
            deja = [p for p, vue in self.uses.get(e.get("fichier"), [])
                    if vue == self.vue]
            self.pages.setCurrentRow(deja[0] if deja and deja[0] < len(self._infos)
                                     else 0)
        self._on_page(self.pages.currentRow())
        for b in (self.btn_renommer, self.btn_retirer):
            b.setEnabled(e is not None)
        self.btn_utiliser.setEnabled(bool(self._infos))

    def _on_page(self, _index=0):
        e = self.entree_courante()
        if e is None or not self._infos:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("Aucun plan sélectionné." if e is None
                                 else "Aucune page lisible.")
            return
        try:
            data = self._pdf.apercu_png(self.chemin_courant(), self.page(), 0, 420)
            pm = QPixmap()
            pm.loadFromData(data, "PNG")
            self.preview.setPixmap(pm.scaled(
                self.preview.size() - QSize(8, 8),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        except Exception as err:
            self.preview.setPixmap(QPixmap())
            self.preview.setText(f"Aperçu impossible : {err}")
        phrase = self._cat_mod.phrase_utilisation(
            self.uses.get(e.get("fichier"), []))
        self.lbl_etat.setText(
            f"{e.get('fichier')}  —  page {self.page() + 1} sur "
            f"{len(self._infos)}" + (f"  —  {phrase}" if phrase else ""))

    # ------------------------------------------------------------- gestes
    def ajouter_des_pdf(self):
        """Copie un ou plusieurs PDF dans `plans/` et les inscrit."""
        chemins, _ = QFileDialog.getOpenFileNames(
            self, "Ajouter des plans PDF au catalogue", self._dossier_depart,
            "Plans PDF (*.pdf);;Tous les fichiers (*)")
        if not chemins:
            return
        dernier, rates = "", []
        for p in chemins:
            try:
                e = self._cat_mod.ajouter(self.ship_folder, p)
                dernier = e.get("fichier", "")
            except Exception as err:
                rates.append(f"{os.path.basename(p)} ({err})")
        self.rafraichir(dernier)
        if rates:
            # jamais un fichier perdu en silence : on dit lequel et pourquoi
            QMessageBox.warning(self, "Plans non ajoutés",
                                "Ces plans n'ont pas pu être ajoutés :\n  • "
                                + "\n  • ".join(rates))

    def renommer_le_plan(self):
        e = self.entree_courante()
        if e is None:
            return
        titre, ok = QInputDialog.getText(
            self, "Renommer le plan",
            f"Titre de « {e.get('fichier')} » :", text=e.get("titre", ""))
        if not ok:
            return
        self._cat_mod.renommer(self.ship_folder, e["fichier"], titre)
        self.rafraichir(e["fichier"])

    def retirer_le_plan(self):
        e = self.entree_courante()
        if e is None:
            return
        phrase = self._cat_mod.phrase_utilisation(
            self.uses.get(e.get("fichier"), []))
        rep = QMessageBox.question(
            self, "Retirer du catalogue",
            f"Retirer « {e.get('titre')} » du catalogue ?\n\n"
            "Le fichier PDF reste dans le dossier plans/ du navire : les vues "
            "qui s'en servent gardent leur fond de plan et leur accroche."
            + (f"\n\nCe plan est {phrase}." if phrase else ""))
        if rep != QMessageBox.StandardButton.Yes:
            return
        self._cat_mod.retirer(self.ship_folder, e["fichier"])
        self.rafraichir()

    def _sur_utiliser(self):
        if not self._infos:
            return
        self._choix = (self.chemin_courant(), self.page())
        self.accept()

    def _sur_autre_fichier(self):
        self._autre = True
        self.accept()

    # ------------------------------------------------------------- valeurs
    def entree_courante(self):
        i = self.liste.currentRow()
        return self.entrees[i] if 0 <= i < len(self.entrees) else None

    def chemin_courant(self) -> str:
        e = self.entree_courante()
        return "" if e is None else self._cat_mod.chemin_du_plan(
            self.ship_folder, e["fichier"])

    def page(self) -> int:
        return max(0, self.pages.currentRow())

    def choix(self):
        """(chemin du PDF, page à partir de 0) retenus, ou None."""
        return self._choix

    def veut_autre_fichier(self) -> bool:
        return self._autre


class DxfImportDialog(QDialog):
    """Choix des calques et de la finesse d'un plan DXF.

    Le DXF est le format pivot demandé au chantier (D-9) : il porte les traits
    aux coordonnées exactes. Trois choses se règlent ici, et rien d'autre :

    - **quels calques** garder — un plan de chantier traîne un cartouche, des
      cotations et des hachures qui rendent le décalquage illisible ; on les
      éteint et l'aperçu le montre tout de suite ;
    - **la finesse** du rendu, en largeur de l'image ;
    - le **calage automatique** sur les coordonnées du dessin quand celui-ci
      déclare son unité (le cas courant : millimètres à 1:1). Il est proposé,
      jamais imposé — le calage manuel sur deux points connus, et l'ajustement
      de l'échelle sur les traits de couples (D-11), restent disponibles et
      priment ensuite.

    Ce que la lecture n'a pas su lire est affiché en toutes lettres : un trait
    perdu en silence, c'est une cloison manquante (D-9).
    """

    def __init__(self, dxf_path, parent=None, axes=("X", "Z"),
                 largeur_cible=None):
        super().__init__(parent)
        from . import dxf_plan
        self._dxf = dxf_plan
        self.path = dxf_path
        self.axes = tuple(axes)
        self.setWindowTitle("Importer un plan DXF")
        self.resize(880, 620)
        app = QApplication.instance()
        if app is not None:
            app.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.dessin = dxf_plan.dessin_pour(dxf_path)
        finally:
            if app is not None:
                app.restoreOverrideCursor()

        d = self.dessin
        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            f"<b>{os.path.basename(dxf_path)}</b> — DXF {d.version}, "
            f"{d.n_polylignes()} traits, {len(d.sommets)} sommets accrochables, "
            f"{len(d.calques)} calques.<br>Unité du dessin : "
            f"<b>{d.unite_nom}</b>. Décochez les calques qui encombrent "
            "(cartouche, cotation, hachures) : ils ne seront ni dessinés ni "
            "accrochables."))

        row = QHBoxLayout()
        gauche = QVBoxLayout()
        self.calques = QListWidget()
        self.calques.setMaximumWidth(300)
        for nom, n_traits, n_som in d.infos_calques():
            it = QListWidgetItem(f"{nom}   —   {n_traits} traits, {n_som} sommets")
            it.setData(Qt.ItemDataRole.UserRole, nom)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            # un calque vide ne sert à rien : décoché d'office
            it.setCheckState(Qt.CheckState.Checked if n_traits
                             else Qt.CheckState.Unchecked)
            self.calques.addItem(it)
        self.calques.itemChanged.connect(self._update)
        gauche.addWidget(self.calques)
        boutons = QHBoxLayout()
        b_tout = QPushButton("Tout cocher")
        b_tout.clicked.connect(lambda: self._cocher(True))
        b_rien = QPushButton("Tout décocher")
        b_rien.clicked.connect(lambda: self._cocher(False))
        boutons.addWidget(b_tout)
        boutons.addWidget(b_rien)
        gauche.addLayout(boutons)
        row.addLayout(gauche)

        self.preview = QLabel("")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(380, 300)
        self.preview.setStyleSheet("background: #ffffff; border: 1px solid #c8c8c8;")
        row.addWidget(self.preview, 1)
        root.addLayout(row)

        form = QFormLayout()
        self.spin_largeur = SpinEntier()
        self.spin_largeur.setRange(800, self._dxf.PIXELS_MAX_PAR_COTE)
        self.spin_largeur.setSingleStep(500)
        self.spin_largeur.setValue(int(largeur_cible
                                       or dxf_plan.LARGEUR_CIBLE_DEFAUT))
        self.spin_largeur.setSuffix(" px de large")
        self.spin_largeur.valueChanged.connect(self._update_size)
        form.addRow("Finesse du rendu :", self.spin_largeur)
        self.lbl_size = QLabel("")
        self.lbl_size.setObjectName("hint")
        form.addRow("Image rendue :", self.lbl_size)

        self.chk_auto = QCheckBox(
            "Le DXF porte ses coordonnées réelles — caler dessus "
            "(pas de points à cliquer)")
        self.chk_auto.setChecked(d.unite_connue)
        self.chk_auto.setEnabled(d.unite_connue)
        if not d.unite_connue:
            self.chk_auto.setToolTip(
                "Le dessin ne déclare pas son unité ($INSUNITS) : impossible "
                "d'en déduire une échelle. Calez-le sur deux points connus.")
        self.chk_auto.toggled.connect(self._update_auto)
        form.addRow("Calage :", self.chk_auto)

        a1, a2 = self.axes
        dec = QHBoxLayout()
        self.spin_d1 = _zspin(0.0, lo=-10000.0, hi=10000.0)
        self.spin_d2 = _zspin(0.0, lo=-10000.0, hi=10000.0)
        dec.addWidget(QLabel(f"{a1} ="))
        dec.addWidget(self.spin_d1)
        dec.addWidget(QLabel(f"    {a2} ="))
        dec.addWidget(self.spin_d2)
        dec.addStretch(1)
        self.ligne_decalage = QLabel(
            f"Coordonnées navire du point (0, 0) du dessin :")
        form.addRow(self.ligne_decalage, dec)

        root.addLayout(form)
        self.lbl_alertes = QLabel("")
        self.lbl_alertes.setWordWrap(True)
        self.lbl_alertes.setObjectName("hint")
        root.addWidget(self.lbl_alertes)
        _buttons(self, root)
        self._update_auto(self.chk_auto.isChecked())
        self._update()

    # ---------------------------------------------------------------- état
    def _cocher(self, etat):
        self.calques.blockSignals(True)
        for i in range(self.calques.count()):
            self.calques.item(i).setCheckState(
                Qt.CheckState.Checked if etat else Qt.CheckState.Unchecked)
        self.calques.blockSignals(False)
        self._update()

    def _update_auto(self, coche):
        self.spin_d1.setEnabled(bool(coche))
        self.spin_d2.setEnabled(bool(coche))
        self.ligne_decalage.setEnabled(bool(coche))

    def _update(self, *_):
        calques = self.calques_retenus()
        try:
            data = self._dxf.apercu_png(self.dessin, calques, 460)
            pm = QPixmap()
            pm.loadFromData(data, "PNG")
            self.preview.setPixmap(pm.scaled(
                self.preview.size() - QSize(8, 8),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        except Exception as e:
            self.preview.setText(str(e))
        self._update_size()
        alertes = list(self.dessin.avertissements())
        self.lbl_alertes.setText(
            ("À SAVOIR :  " + "   •   ".join(alertes)) if alertes
            else "Tout le fichier a été lu : aucune entité laissée de côté.")

    def _update_size(self, *_):
        try:
            w, h, origine, res = self._dxf.cadrage(
                self.dessin, self.calques_retenus(),
                largeur_cible=self.spin_largeur.value())
        except Exception as e:
            self.lbl_size.setText(str(e))
            return
        mo = w * h * 4 / 1e6
        trop = max(w, h) > self._dxf.PIXELS_MAX_PAR_COTE
        k = self.dessin.metres_par_unite
        echelle = (f"  —  {res / k * 0.001:.1f} px/mm réel" if k else "")
        self.lbl_size.setText(
            f"{w} × {h} pixels, environ {mo:.0f} Mo affichés{echelle}"
            + ("  —  TROP GRAND : baissez la finesse" if trop
               else ("  —  lourd : 6000 px suffisent pour un A0" if mo > 200
                     else "")))

    # ---------------------------------------------------------------- valeurs
    def calques_retenus(self):
        """Les calques cochés, ou None si tous le sont (« tout le dessin »)."""
        pris, total = [], self.calques.count()
        for i in range(total):
            it = self.calques.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                pris.append(it.data(Qt.ItemDataRole.UserRole))
        return None if len(pris) == total else pris

    def largeur_cible(self) -> int:
        return int(self.spin_largeur.value())

    def calage_auto(self) -> bool:
        return bool(self.chk_auto.isChecked() and self.chk_auto.isEnabled())

    def decalage(self):
        return self.spin_d1.value(), self.spin_d2.value()

    def values(self):
        """(calques ou None, largeur_cible, calage_auto, décalage)"""
        return (self.calques_retenus(), self.largeur_cible(),
                self.calage_auto(), self.decalage())


class VertexDialog(QDialog):
    """Coordonnées navire d'un sommet de contour, saisies au clavier."""

    def __init__(self, parent=None, x=0.0, y=0.0, index=1):
        super().__init__(parent)
        self.setWindowTitle(f"Sommet n°{index}")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.spin_x = _zspin(x, lo=-1000, hi=1000)
        self.spin_y = _zspin(y, lo=-1000, hi=1000)
        form.addRow("X (m) :", self.spin_x)
        form.addRow("Y (m, bâbord +) :", self.spin_y)
        lay.addLayout(form)
        _buttons(self, lay)

    def values(self):
        return self.spin_x.value(), self.spin_y.value()


class NewShipDialog(QDialog):
    """Création d'un navire : nom (le reste se fait par l'assistant guidé)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nouveau navire")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("ex. MON NAVIRE")
        form.addRow("Nom du navire :", self.edit_name)
        lay.addLayout(form)
        lay.addWidget(QLabel(
            "Déroulé de l'assistant :\n"
            "  1. Importer le PLAN (DXF, PDF ou image) — profil, puis ponts\n"
            "  2. Le CALER : ligne de foi + couples (ou perpendiculaires sur le\n"
            "     profil) — coordonnées ET échelle en une fois\n"
            "  3. DÉCALQUER : contour de pont, cales, épontilles fixes\n"
            "  4. Poser les CALQUES : charge t/m² et hauteur libre (signalés,\n"
            "     non bloquants)\n"
            "  5. Poser le calque d'INFORMATION (rien n'en dépend)\n"
            "  6. Contrôler dans la vue isométrique, enregistrer le navire"
        ))
        _buttons(self, lay)
        self.edit_name.setFocus()

    def name(self):
        return self.edit_name.text().strip() or "Navire"


# ---------------------------------------------------------------- épontilles
# Encombrement proposé pour une épontille neuve. Le manuel d'assujettissement
# du navire donne la règle et la tenue — MSL 50 kN — jamais les
# dimensions : ce sont donc des valeurs de DÉPART, que le bord corrige. On
# retient les dernières employées pour la suivante : on en place plusieurs à
# la file, toutes du même modèle.
EPONTILLE_DEFAUT = {"longueur_m": 0.20, "largeur_m": 0.20}
_DERNIERE_EPONTILLE = dict(EPONTILLE_DEFAUT)


class EpontilleDialog(QDialog):
    """Nom, encombrement et note d'une épontille amovible.

    Elle se pose d'un clic sur le plan ; cette fiche ne sert qu'à dire ce
    qu'elle est. L'encombrement proposé est celui de la dernière posée."""

    def __init__(self, parent=None, nom="", longueur_m=None, largeur_m=None,
                 note="", x=None, y=None, cale="", fixe=False):
        super().__init__(parent)
        self.setWindowTitle("Épontille")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.edit_nom = QLineEdit(nom)
        self.edit_nom.setPlaceholderText("ex. AR bâbord")
        self.spin_long = _zspin(
            _DERNIERE_EPONTILLE["longueur_m"] if longueur_m is None
            else longueur_m, lo=0.02, hi=5.0)
        self.spin_larg = _zspin(
            _DERNIERE_EPONTILLE["largeur_m"] if largeur_m is None
            else largeur_m, lo=0.02, hi=5.0)
        for sp in (self.spin_long, self.spin_larg):
            sp.setSuffix(" m")
            sp.setSingleStep(0.05)
        form.addRow("Nom :", self.edit_nom)
        form.addRow("Longueur (selon X) :", self.spin_long)
        form.addRow("Largeur (selon Y) :", self.spin_larg)
        self.edit_note = QLineEdit(note)
        self.edit_note.setPlaceholderText("ex. MSL 50 kN — manuel d'assujettissement")
        form.addRow("Note :", self.edit_note)
        # Un seul outil pour toutes les épontilles (demande du bord) : c'est
        # ICI qu'on dit si elle est fixe. Fixe = structure, toujours en place,
        # le chargement ne la laisse pas déposer.
        self.chk_fixe = QCheckBox("Épontille fixe — toujours en place, ne se dépose pas")
        self.chk_fixe.setChecked(bool(fixe))
        form.addRow("", self.chk_fixe)
        lay.addLayout(form)
        ou = ""
        if x is not None and y is not None:
            ou = (f"Emplacement : X = {x:.3f} m, Y = {y:.3f} m"
                  + (f" — dans « {cale} »" if cale else "") + "\n")
        lay.addWidget(QLabel(
            ou +
            "L'emplacement appartient au NAVIRE : il est tracé une fois et\n"
            "enregistré avec les plans. Une épontille AMOVIBLE n'est un mur\n"
            "que lorsqu'elle est mise en place — cela se décide escale par\n"
            "escale, dans la vue Chargement. Une épontille FIXE l'est toujours."))
        _buttons(self, lay)
        self.edit_nom.setFocus()

    def values(self):
        """(nom, longueur_m, largeur_m, note, fixe) — et l'encombrement est
        retenu pour la prochaine épontille."""
        lo = round(self.spin_long.value(), 3)
        la = round(self.spin_larg.value(), 3)
        _DERNIERE_EPONTILLE["longueur_m"] = lo
        _DERNIERE_EPONTILLE["largeur_m"] = la
        return (self.edit_nom.text().strip(), lo, la,
                self.edit_note.text().strip(), self.chk_fixe.isChecked())


class TraitsConstructionDialog(QDialog):
    """Les traits de construction d'un plan : ligne de foi, couples, cotes.

    Décalquer un contour sur un plan de chantier, c'est s'appuyer sur des
    droites — la ligne de foi, un couple, une cote reportée au compas — pas
    dessiner à main levée. Chaque trait est une **valeur constante sur un axe**
    du repère navire ; il traverse tout le plan et le curseur s'y accroche.

    Ce sont des repères de DESSIN : ils sont rangés avec le plan, mais rien en
    aval ne les lit — ni la stabilité, ni le chargement."""

    def __init__(self, parent, calibrated, couples=None, titre=""):
        super().__init__(parent)
        self.cal = calibrated
        self.couples = list(couples or [])
        self.setWindowTitle("Traits de construction")
        self.resize(560, 430)
        lay = QVBoxLayout(self)
        intro = QLabel(
            "Un trait par ligne : l'axe du repère et sa valeur en mètres. "
            "Le curseur s'accroche au trait, et surtout au <b>croisement de "
            "deux traits</b> — c'est là qu'un point est vraiment tenu."
            + (f"<br>Plan : <b>{titre}</b>" if titre else ""))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Axe", "Valeur (m)", "Libellé"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)

        boutons = QHBoxLayout()
        b_add = QPushButton("+ un trait")
        b_add.clicked.connect(self.ajouter)
        b_del = QPushButton("Retirer")
        b_del.clicked.connect(self.retirer)
        self.b_foi = QPushButton("Ligne de foi (Y = 0)")
        self.b_foi.clicked.connect(self.ligne_de_foi)
        self.b_couples = QPushButton("Tous les couples")
        self.b_couples.setToolTip(
            "Un trait par couple de la table du navire (couples.csv) : "
            "l'ossature sur laquelle le chantier a coté ses plans.")
        self.b_couples.clicked.connect(self.tous_les_couples)
        self.b_couples.setEnabled(bool(self.couples))
        for b in (b_add, b_del, self.b_foi, self.b_couples):
            boutons.addWidget(b)
        boutons.addStretch(1)
        lay.addLayout(boutons)
        self.lbl = QLabel("")
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl)
        _buttons(self, lay)
        self.remplir()

    # ------------------------------------------------------------- garnir
    def axes(self):
        return tuple(getattr(self.cal, "axes", ("X", "Y")))

    def remplir(self):
        self.table.setRowCount(0)
        for t in getattr(self.cal, "traits", None) or []:
            self._ligne(t.get("axe", self.axes()[0]),
                        float(t.get("valeur", 0.0)), t.get("libelle", ""))
        self._compter()

    def _ligne(self, axe, valeur, libelle=""):
        r = self.table.rowCount()
        self.table.insertRow(r)
        combo = QComboBox()
        combo.addItems(list(self.axes()))
        i = combo.findText(axe)
        combo.setCurrentIndex(i if i >= 0 else 0)
        self.table.setCellWidget(r, 0, combo)
        spin = SpinNombre()
        spin.setRange(-500.0, 500.0)
        spin.setDecimals(3)
        spin.setSuffix(" m")
        spin.setValue(float(valeur))
        self.table.setCellWidget(r, 1, spin)
        self.table.setItem(r, 2, QTableWidgetItem(libelle))

    def ajouter(self):
        self._ligne(self.axes()[0], 0.0, "")
        self.table.selectRow(self.table.rowCount() - 1)
        self._compter()

    def retirer(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
        self._compter()

    def ligne_de_foi(self):
        """Y = 0 : l'axe du navire. Sur un profil, c'est Z = 0 (ligne de base)."""
        axe = "Y" if "Y" in self.axes() else self.axes()[1]
        lib = "ligne de foi" if axe == "Y" else "ligne de base"
        if not any(t["axe"] == axe and abs(t["valeur"]) < 1e-9
                   for t in self.valeurs()):
            self._ligne(axe, 0.0, lib)
        self._compter()

    def tous_les_couples(self):
        axe = "X"
        if axe not in self.axes():
            return
        connus = {round(t["valeur"], 3) for t in self.valeurs() if t["axe"] == axe}
        n = 0
        for i, x in enumerate(self.couples):
            if x != x or round(x, 3) in connus:
                continue
            self._ligne(axe, x, "C.%d" % i)
            n += 1
        self._compter()
        self.lbl.setText("%d couple(s) ajouté(s). Ils ne servent qu'au dessin : "
                         "le calage de l'échelle, lui, se fait sur les traits "
                         "de couples du plan lui-même (D-11)." % n)

    def _compter(self):
        self.lbl.setText(self.lbl.text() if self.lbl.text() else "")
        n = self.table.rowCount()
        self.setWindowTitle("Traits de construction — %d trait(s)" % n)

    # ------------------------------------------------------------- valeurs
    def valeurs(self):
        out = []
        for r in range(self.table.rowCount()):
            combo = self.table.cellWidget(r, 0)
            spin = self.table.cellWidget(r, 1)
            if combo is None or spin is None:
                continue
            it = self.table.item(r, 2)
            out.append({"axe": combo.currentText(),
                        "valeur": round(spin.value(), 3),
                        "libelle": (it.text().strip() if it else "")})
        return out


class EpontillesDialog(QDialog):
    """Les épontilles amovibles du navire, à mettre en place ou à déposer.

    Un geste, une case : cocher, c'est décrire le navire tel qu'il est à cette
    escale. Ce qui se trouve déjà dessous n'est **pas** supprimé — c'est
    signalé, comme le fait le calque des charges admissibles (D-12) : on
    décrit le navire, on ne se fait pas punir par lui."""

    changed = Signal(str)      # une épontille a bougé, et ce qu'il faut en dire

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self._sync = False
        self.setWindowTitle("Épontilles amovibles")
        self.resize(520, 480)
        lay = QVBoxLayout(self)
        intro = QLabel(
            "Les épontilles amovibles se posent dans l'emplacement prévu des "
            "cales avant et arrière de chaque pont (jamais dans la cave) et "
            "tiennent 50 kN chacune — manuel d'assujettissement. "
            "Une épontille EN PLACE interdit la pose sous elle, exactement "
            "comme le contour de la cale ; déposée, elle ne contraint rien.")
        intro.setWordWrap(True)
        intro.setObjectName("hint")
        lay.addWidget(intro)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Épontille", "État"])
        self.tree.setRootIsDecorated(True)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.itemChanged.connect(self._on_item)
        lay.addWidget(self.tree, 1)
        self.lbl = QLabel("")
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        # Qt libelle ses boutons standard en anglais tant qu'aucune traduction
        # n'est chargee : on impose le français, comme partout ailleurs.
        b.button(QDialogButtonBox.StandardButton.Close).setText("Fermer")
        b.rejected.connect(self.reject)
        b.accepted.connect(self.accept)
        lay.addWidget(b)
        self.refresh()

    # ------------------------------------------------------------- garnir
    def _condition(self):
        return getattr(self.win, "condition", None)

    def refresh(self):
        self._sync = True
        try:
            self.tree.clear()
            proj = getattr(self.win, "project", None)
            cond = self._condition()
            if proj is None or cond is None:
                return
            fixes = proj.epontilles_fixes()
            en_place = set(getattr(cond, "epontilles_en_place", []) or []) | fixes
            # groupées par cale, dans l'ordre des ponts : (Deck, Capacity)
            # ne se hache pas, on garde donc une liste de couples
            par_cale = []
            for deck, cap, e in proj.all_epontilles():
                if par_cale and par_cale[-1][0] is cap:
                    par_cale[-1][2].append(e)
                else:
                    par_cale.append((cap, deck, [e]))
            orphelines = cond.epontilles_inconnues(proj)
            # un emplacement supprimé des plans laisse son identifiant dans les
            # points qui le portaient : il ne contraint plus rien (la cale ne
            # le retrouve pas), mais on ne le tait pas
            perdues = ("" if not orphelines else
                       f"Ce point porte {len(orphelines)} épontille(s) que les "
                       "plans ne connaissent plus : " + ", ".join(orphelines)
                       + " — elles ne contraignent plus rien.")
            if not par_cale:
                self.lbl.setText(
                    "Aucun emplacement d'épontille n'est tracé sur ce navire. "
                    "Ils se placent dans le créateur de plan, outil "
                    "« Épontille ». " + perdues)
                return
            for cap, deck, liste in par_cale:
                pere = QTreeWidgetItem([f"{deck.name} — {cap.code}"
                                        f"{('  ' + cap.name) if cap.name else ''}",
                                        "toute la cale"])
                # cochable : toutes les épontilles de la cale d'un coup
                pere.setFlags(Qt.ItemFlag.ItemIsEnabled
                              | Qt.ItemFlag.ItemIsUserCheckable)
                pere.setData(0, Qt.ItemDataRole.UserRole, None)
                pere.setData(0, Qt.ItemDataRole.UserRole + 1, cap.code)
                posees = sum(1 for e in liste if e.get("id") in en_place)
                pere.setCheckState(0, Qt.CheckState.Checked if posees == len(liste)
                                   else Qt.CheckState.Unchecked if not posees
                                   else Qt.CheckState.PartiallyChecked)
                self.tree.addTopLevelItem(pere)
                for e in liste:
                    eid = e.get("id")
                    it = QTreeWidgetItem([str(e.get("nom") or eid), ""])
                    it.setData(0, Qt.ItemDataRole.UserRole, eid)
                    it.setFlags(Qt.ItemFlag.ItemIsEnabled
                                | Qt.ItemFlag.ItemIsUserCheckable
                                | Qt.ItemFlag.ItemIsSelectable)
                    pose = eid in en_place
                    it.setCheckState(0, Qt.CheckState.Checked if pose
                                     else Qt.CheckState.Unchecked)
                    n = self._colis_dessous(cap, e)
                    if eid in fixes:
                        # de la structure : cochée, et la case ne répond pas
                        it.setFlags(Qt.ItemFlag.ItemIsSelectable)
                        it.setText(1, "fixe — toujours en place")
                    else:
                        it.setText(1, ("en place" if pose else "déposée")
                                   + (f" · {n} colis dessous" if n else ""))
                    note = str(e.get("note") or "")
                    it.setToolTip(0, note or ("Épontille fixe (structure)"
                                              if eid in fixes else
                                              "Épontille amovible — MSL 50 kN"))
                    pere.addChild(it)
                pere.setExpanded(True)
            self.tree.resizeColumnToContents(0)
            if perdues:
                self.lbl.setText(perdues)
        finally:
            self._sync = False

    @staticmethod
    def compter_dessous(cond, cap, e):
        """Combien de colis posés mordent l'emprise de cette épontille.

        On compare les ENCOMBREMENTS : un colis dont les sacs débordent sur
        l'épontille est dessous, même si sa palette passe à côté — c'est la
        règle de la place occupée (D-39), la même qui refuse la pose."""
        from .core.stowage import _rects_se_chevauchent, rect_epontille
        if cond is None or cap is None or not e:
            return 0
        rect = rect_epontille(e)
        return sum(1 for pl in cond.placements.get(cap.code, [])
                   if _rects_se_chevauchent(pl.rect_encombrement, rect))

    def _colis_dessous(self, cap, e):
        return self.compter_dessous(self._condition(), cap, e)

    @classmethod
    def basculer(cls, win, eid, veut):
        """Met en place ou dépose une épontille, et rend la phrase à en dire
        (None si rien n'a changé).

        **LE seul chemin de la bascule** : la case de cette fenêtre y passe,
        et le clic sur l'épontille du plan de pose aussi. Deux chemins qui
        écriraient chacun leur version de « en place », ce serait deux plans
        de cale pour un seul navire."""
        cond = getattr(win, "condition", None)
        proj = getattr(win, "project", None)
        if not eid or cond is None or proj is None:
            return None
        _deck, cap, e = proj.epontille(eid)
        nom = str((e or {}).get("nom") or eid)
        if e is not None and epontille_fixe(e):
            # de la structure : on ne la dépose pas, et on le dit plutôt que
            # de laisser croire qu'un clic n'a pas été entendu
            return None if veut else \
                f"Épontille {nom} est fixe : elle est toujours en place."
        if not cond.poser_epontille(eid, veut):
            return None
        if veut:
            # Une épontille en place est un mur (D-30) : le fret qui était
            # dessous ne peut plus y être. Il REPART AU MANIFESTE — parole du
            # bord — plutôt que de rester posé dans un mur, et on dit combien.
            n = cls.liberer_dessous(cond, cap, e)
            return (f"Épontille {nom} en place — "
                    + (f"{n} colis retourné(s) au manifeste." if n
                       else "rien n'était posé dessous."))
        return f"Épontille {nom} déposée — la place se libère."

    @staticmethod
    def liberer_dessous(cond, cap, e):
        """Retire du plan les colis qui mordent l'emprise de l'épontille :
        ils retournent au manifeste (leur ligne les compte encore « à
        poser »). Rend le nombre de colis (niveaux compris)."""
        from .core.stowage import _rects_se_chevauchent, rect_epontille
        if cond is None or cap is None or not e:
            return 0
        rect = rect_epontille(e)
        lst = cond.placements.get(cap.code, [])
        # l'encombrement, comme au comptage : ce qu'on refuserait de poser
        # là, on ne le laisse pas y rester (D-39)
        dessous = [pl for pl in lst
                   if _rects_se_chevauchent(pl.rect_encombrement, rect)]
        for pl in dessous:
            lst.remove(pl)
        return sum(max(1, pl.niveaux) for pl in dessous)

    @classmethod
    def basculer_cale(cls, win, cap, veut):
        """Toutes les épontilles d'une cale d'un coup. Rend la phrase à dire,
        ou None si rien n'a changé."""
        n_ep, n_colis = 0, 0
        for e in getattr(cap, "epontilles", []) or []:
            eid = e.get("id")
            cond = getattr(win, "condition", None)
            if epontille_fixe(e):          # la structure ne se dépose pas
                continue
            if cond is None or not cond.poser_epontille(eid, veut):
                continue
            n_ep += 1
            if veut:
                n_colis += cls.liberer_dessous(cond, cap, e)
        if not n_ep:
            return None
        if veut:
            return (f"{n_ep} épontille(s) de {cap.code} en place — "
                    + (f"{n_colis} colis retourné(s) au manifeste."
                       if n_colis else "rien n'était posé dessous."))
        return f"{n_ep} épontille(s) de {cap.code} déposée(s) — la place se libère."

    # ------------------------------------------------------------- gestes
    def _on_item(self, item, column):
        if self._sync:
            return
        eid = item.data(0, Qt.ItemDataRole.UserRole)
        proj = getattr(self.win, "project", None)
        veut = item.checkState(0) == Qt.CheckState.Checked
        if eid is None:
            # la ligne d'une CALE : toutes ses épontilles d'un coup
            code = item.data(0, Qt.ItemDataRole.UserRole + 1)
            cap = next((c for _d, c in proj.all_capacities() if c.code == code), None)
            if cap is None or item.checkState(0) == Qt.CheckState.PartiallyChecked:
                return
            msg = self.basculer_cale(self.win, cap, veut)
            if msg is None:
                return
            self.lbl.setText(msg)
            self._sync = True
            try:
                for i in range(item.childCount()):
                    fils = item.child(i)
                    fils.setCheckState(0, item.checkState(0))
                    fils.setText(1, "en place" if veut else "déposée")
            finally:
                self._sync = False
            self.changed.emit(msg)
            return
        msg = self.basculer(self.win, eid, veut)
        if msg is None:
            return
        self.lbl.setText(msg)
        # on remet la ligne à jour SUR PLACE : reconstruire l'arbre depuis le
        # signal d'une de ses lignes détruirait la ligne qui vient de le
        # lancer — et ce que fait `refresh()`. Ceux qui écoutent `changed`
        # doivent différer toute reconstruction (QTimer.singleShot(0, …)).
        self._sync = True
        try:
            item.setText(1, "en place" if veut else "déposée")
            pere = item.parent()
            if pere is not None:
                etats = {pere.child(i).checkState(0) for i in range(pere.childCount())}
                pere.setCheckState(0, next(iter(etats)) if len(etats) == 1
                                   else Qt.CheckState.PartiallyChecked)
        finally:
            self._sync = False
        # dire ce qui vient de se passer, toujours : on ne coche pas une case
        # en silence quand elle déplace du chargement
        self.changed.emit(msg)


# ------------------------------------------------- calques posés sur une cale
# Les deux calques CONTRAIGNANTS d'une cale — la charge au m² (D-12) et la
# hauteur libre (D-21) — et le calque d'INFORMATION du pont, qui ne contraint
# rien. Le bord ne trouvait « où modifier les calques de limite t/m², ni le
# calque de limite de hauteur » : ces trois fiches sont la réponse, et chacune
# dit en toutes lettres ce que son calque fait — et ne fait pas.

class ZoneChargeDialog(QDialog):
    """Nom et charge admissible d'une zone du calque des charges (D-12).

    Le calque ALERTE, il n'interdit pas : la limite vient d'un tracé relevé
    sur le plan des charges, pas d'un chiffre du dossier approuvé. La fiche le
    dit, pour qu'on ne s'étonne pas de pouvoir poser au-delà."""

    def __init__(self, parent=None, nom="", t_m2=0.0, cale="",
                 t_m2_cale=0.0, surface_m2=0.0):
        super().__init__(parent)
        self.setWindowTitle("Zone de charge admissible")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.edit_nom = QLineEdit(nom)
        self.edit_nom.setPlaceholderText("ex. C.20–C.25 tribord")
        self.spin_t = SpinNombre()
        self.spin_t.setRange(0.0, 100.0)
        self.spin_t.setDecimals(2)
        self.spin_t.setSingleStep(0.1)
        self.spin_t.setSuffix(" t/m²")
        # pré-remplie avec celle de la cale : neuf zones sur dix la corrigent
        # d'un cran, elles ne la découvrent pas
        self.spin_t.setValue(float(t_m2 or t_m2_cale or 0.0))
        form.addRow("Nom :", self.edit_nom)
        form.addRow("Charge admissible :", self.spin_t)
        lay.addLayout(form)
        ou = []
        if cale:
            ou.append(f"Zone tracée dans « {cale} »"
                      + (f", dont la charge est {t_m2_cale:g} t/m²"
                         if t_m2_cale else ""))
        if surface_m2:
            ou.append(f"Surface du polygone : {surface_m2:.1f} m²")
        lay.addWidget(QLabel(
            ("\n".join(ou) + "\n\n" if ou else "")
            + "Ce calque SIGNALE un dépassement, il ne l'interdit pas : la\n"
              "limite vient d'un tracé, pas d'un chiffre du dossier approuvé\n"
              "(décision D-12). Le solveur, lui, la respecte."))
        _buttons(self, lay)
        self.edit_nom.setFocus()

    def values(self):
        """(nom, charge admissible en t/m²)"""
        return (self.edit_nom.text().strip(), round(self.spin_t.value(), 3))


class HauteurLibreDialog(QDialog):
    """Hauteur libre d'une zone à plafond bas (D-21).

    Comme la charge au m², c'est un calque qui alerte : on pose sous un
    plafond bas, une pile trop haute est signalée en rouge et le solveur ne
    l'y met pas. Une zone SANS hauteur, elle, est un mur — c'est l'outil
    « Épontille fixe » qui la trace."""

    def __init__(self, parent=None, hauteur_m=2.0, cale="", rect=None):
        super().__init__(parent)
        self.setWindowTitle("Zone à hauteur libre réduite")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.spin_h = SpinNombre()
        self.spin_h.setRange(0.05, 30.0)
        self.spin_h.setDecimals(2)
        self.spin_h.setSingleStep(0.05)
        self.spin_h.setSuffix(" m")
        self.spin_h.setValue(float(hauteur_m or 2.0))
        form.addRow("Hauteur libre :", self.spin_h)
        lay.addLayout(form)
        ou = ""
        if rect is not None:
            x0, y0, x1, y1 = (float(v) for v in rect[:4])
            ou = (f"Rectangle : X de {min(x0, x1):.2f} à {max(x0, x1):.2f} m, "
                  f"Y de {min(y0, y1):.2f} à {max(y0, y1):.2f} m"
                  + (f"\ndans « {cale} »" if cale else "") + "\n\n")
        lay.addWidget(QLabel(
            ou +
            "La zone sera nommée « hauteur libre X.XX m » : c'est ainsi que le\n"
            "moteur la relit. Une pile plus haute y est SIGNALÉE, jamais\n"
            "refusée (décision D-21) ; le solveur, lui, ne l'y place pas."))
        _buttons(self, lay)
        self.spin_h.setFocus()

    def values(self):
        """Hauteur libre en mètres."""
        return round(self.spin_h.value(), 3)


# Ce qu'on décalque comme zone BLOQUANTE : de la structure, toujours là.
SUGGESTIONS_INTERDIT = ["Épontille fixe", "Descente", "Puits", "Échelle",
                        "Trappe", "Mât de charge", "Caisson", "Coffre"]


class ZoneInterditeDialog(QDialog):
    """Nom d'une zone interdite : épontille fixe, descente, puits…

    Une zone sans hauteur est un MUR : rien ne s'y pose. C'est la différence
    avec le calque de hauteur libre, et elle tient au seul nom — d'où la mise
    en garde : un nom qui contient un nombre de mètres serait relu comme un
    plafond bas."""

    def __init__(self, parent=None, nom="Épontille fixe", cale=""):
        super().__init__(parent)
        self.setWindowTitle("Zone interdite (structure)")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.addItems(SUGGESTIONS_INTERDIT)
        self.combo.setCurrentText(nom or "Épontille fixe")
        form.addRow("Nature :", self.combo)
        lay.addLayout(form)
        lay.addWidget(QLabel(
            (f"Zone tracée dans « {cale} ».\n\n" if cale else "")
            + "Cette zone BLOQUE la pose : rien ne s'y met, jamais. C'est de la\n"
              "structure — une épontille fixe, une descente, un puits — pas une\n"
              "épontille amovible, qui se pose et se dépose à chaque escale.\n\n"
              "Évitez un nom contenant un nombre suivi de « m » : il serait relu\n"
              "comme une hauteur libre, et la zone cesserait de bloquer."))
        _buttons(self, lay)
        self.combo.setFocus()

    def values(self):
        """Le nom de la zone (jamais vide : une zone sans nom ne se relit pas)."""
        return self.combo.currentText().strip() or "Zone interdite"


class AnnotationDialog(QDialog):
    """Le calque d'INFORMATION : forme, texte et couleur d'une annotation.

    Le bord voulait « un calque supplémentaire pour décalquer des infos non
    contraignantes (emplacement des clés de saisissage…) ». Rien ne le lit :
    ni la pose, ni la stabilité, ni le solveur. La forme se choisit ICI parce
    qu'un point et le premier sommet d'une polyligne sont le même geste : sans
    la fiche, le logiciel devrait deviner."""

    def __init__(self, parent=None, forme="trait", texte="", couleur=None,
                 pont="", nouvelle=True):
        from .items import (COULEURS_ANNOTATION, COULEUR_ANNOTATION_DEFAUT,
                            FORMES_ANNOTATION, NOMS_FORMES_ANNOTATION)
        super().__init__(parent)
        self.setWindowTitle("Information à décalquer" if nouvelle
                            else "Information")
        self._formes = list(FORMES_ANNOTATION)
        self._couleurs = list(COULEURS_ANNOTATION)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.combo_forme = QComboBox()
        for f in self._formes:
            self.combo_forme.addItem(NOMS_FORMES_ANNOTATION[f])
        if forme in self._formes:
            self.combo_forme.setCurrentIndex(self._formes.index(forme))
        # la forme d'une annotation déjà tracée ne se change pas : ses points
        # ne veulent plus rien dire (deux sommets ne font pas un point)
        self.combo_forme.setEnabled(bool(nouvelle))
        self.edit_texte = QLineEdit(texte)
        self.edit_texte.setPlaceholderText("ex. clés de saisissage — rangée BB")
        self.combo_couleur = QComboBox()
        for nom, code in self._couleurs:
            self.combo_couleur.addItem(f"{nom}  ({code})")
        code = str(couleur or COULEUR_ANNOTATION_DEFAUT).lower()
        for i, (_n, c) in enumerate(self._couleurs):
            if c.lower() == code:
                self.combo_couleur.setCurrentIndex(i)
                break
        form.addRow("Forme :", self.combo_forme)
        form.addRow("Texte :", self.edit_texte)
        form.addRow("Couleur :", self.combo_couleur)
        lay.addLayout(form)
        lay.addWidget(QLabel(
            (f"Calque d'information de « {pont} ».\n\n" if pont else "")
            + "Ce calque ne contraint RIEN : ni la pose, ni la stabilité, ni le\n"
              "solveur ne le lisent. Il s'affiche, il s'éteint, c'est tout —\n"
              "c'est là qu'on décalque les clés de saisissage, une prise, une\n"
              "remarque du bord.\n\n"
              "Polyligne : cliquez les sommets, double-clic pour terminer.\n"
              "Polygone : mêmes gestes, et le double-clic le REFERME — comme\n"
              "un contour de cale.\n"
              "Point et texte : un seul clic sur le plan."))
        _buttons(self, lay)
        (self.edit_texte if not nouvelle else self.combo_forme).setFocus()

    def values(self):
        """(forme, texte, couleur « #RRGGBB »)"""
        return (self._formes[max(0, self.combo_forme.currentIndex())],
                self.edit_texte.text().strip(),
                self._couleurs[max(0, self.combo_couleur.currentIndex())][1])
