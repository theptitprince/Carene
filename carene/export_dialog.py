# -*- coding: utf-8 -*-
"""La fenêtre « Exporter… » (Ctrl+E) : choisir quoi, choisir où, exporter.

Une seule fenêtre pour tous les exports plutôt qu'une entrée de menu par
document : à l'escale on sort en général tout d'un coup — le rapport pour le
dossier, les feuilles de pointage pour le quai, le plan pour la passerelle —
et dans le même dossier, nommé d'après le point du journal.

Toute la fabrication des documents est dans `carene.rapports` ; ici il n'y a
que les cases à cocher, le choix du dossier, l'aperçu avant impression et la
ligne d'état qui dit ce qui a été écrit.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPageLayout
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from . import rapports

# QtPrintSupport manque sur certaines installations minimales (PySide6
# Essentials sans le module) : l'export PDF ne doit pas en dépendre, seuls
# l'aperçu et l'impression le demandent.
try:
    from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrintPreviewDialog
    IMPRESSION_DISPONIBLE = True
except ImportError:                                 # pragma: no cover
    QPrintDialog = QPrinter = QPrintPreviewDialog = None
    IMPRESSION_DISPONIBLE = False


class ExportDialog(QDialog):
    """Cases à cocher, dossier de sortie, aperçu, export."""

    def __init__(self, win, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.ecrits = []
        # dernier dossier PROPOSÉ : sert à savoir si celui affiché a été choisi
        # à la main (voir `rafraichir`)
        self._dossier_propose = ""
        self.setWindowTitle("Exporter…")
        self.setModal(False)
        self.resize(640, 460)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)
        self.lbl_titre = titre = QLabel("")
        titre.setWordWrap(True)
        root.addWidget(titre)
        sous = QLabel("Chaque document porte le navire, le point du journal, la version "
                      "de Carène et l'avertissement : ce qui est exporté est ce que "
                      "l'écran affiche, réserves comprises.")
        sous.setObjectName("hint")
        sous.setWordWrap(True)
        root.addWidget(sous)

        self.cases = {}
        # Le lot de l'escale, puis la planche du quai : elle s'exporte dans le
        # même dossier que le reste, mais elle ne fait pas partie du lot par
        # défaut de `rapports.tout_exporter` (voir EXPORT_DOCKERS).
        # le dernier document DÉSIGNÉ : celui qu'on vient de cocher ou dont on
        # a cliqué le libellé. C'est lui que l'aperçu montre (D-62).
        self._vise = rapports.EXPORTS[0][0]
        for cle, libelle in list(rapports.EXPORTS) + [rapports.EXPORT_DOCKERS]:
            cb = QCheckBox(libelle)
            cb.setChecked(True)
            cb.clicked.connect(lambda _v=False, c=cle: self._designer(c))
            self.cases[cle] = cb
            root.addWidget(cb)
        self.cases[rapports.EXPORT_DOCKERS[0]].setToolTip(
            "Une planche par pont, à l'échelle : les colis en couleur de lot, "
            "numérotés, avec la légende des lots et le compte par cale. "
            "C'est la feuille qu'on tend aux dockers.")

        # filtre des feuilles de pointage : un port de déchargement, ou tous
        form = QFormLayout()
        form.setContentsMargins(24, 0, 0, 0)
        self.combo_port = QComboBox()
        self.combo_port.setToolTip("Feuilles de pointage : ne garder que les colis "
                                   "destinés à ce port de déchargement.")
        form.addRow("Port de déchargement :", self.combo_port)
        root.addLayout(form)

        # dossier de sortie : sous le navire, un sous-dossier par point
        ligne = QHBoxLayout()
        self.champ_dossier = QLineEdit("")
        b_dossier = QPushButton("Choisir…")
        b_dossier.clicked.connect(self._choisir_dossier)
        ligne.addWidget(QLabel("Dossier :"))
        ligne.addWidget(self.champ_dossier, 1)
        ligne.addWidget(b_dossier)
        root.addLayout(ligne)

        self.lbl_etat = QLabel("")
        self.lbl_etat.setObjectName("hint")
        self.lbl_etat.setWordWrap(True)
        self.lbl_etat.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.lbl_etat, 1)

        boutons = QHBoxLayout()
        self.b_apercu = QPushButton("Aperçu du rapport…")
        self.b_apercu.setToolTip("Le rapport de stabilité tel qu'il s'imprimera.")
        self.b_apercu.clicked.connect(self.apercu)
        self.b_imprimer = QPushButton("Imprimer le rapport…")
        self.b_imprimer.clicked.connect(self.imprimer)
        if not IMPRESSION_DISPONIBLE:
            for b in (self.b_apercu, self.b_imprimer):
                b.setEnabled(False)
                b.setToolTip("Impression indisponible : module QtPrintSupport absent. "
                             "L'export PDF reste possible.")
        boutons.addWidget(self.b_apercu)
        boutons.addWidget(self.b_imprimer)
        boutons.addStretch(1)
        self.b_exporter = QPushButton("Exporter")
        self.b_exporter.setProperty("accent", "1")
        self.b_exporter.setDefault(True)
        self.b_exporter.clicked.connect(self.exporter)
        b_fermer = QPushButton("Fermer")
        b_fermer.clicked.connect(self.close)
        boutons.addWidget(self.b_exporter)
        boutons.addWidget(b_fermer)
        root.addLayout(boutons)

        self.rafraichir()

    # ------------------------------------------------------------- contexte
    def rafraichir(self):
        """Relit le contexte : navire, point du journal, ports, dossier.

        La fenêtre est UNIQUE et se rouvre (Ctrl+E) après qu'on a changé de
        point, posé du fret ou renommé une escale. Sans cela, elle exporterait
        l'en-tête et les ports du moment où elle a été construite — un rapport
        au nom du point précédent, ce qui est pire qu'une fenêtre absente."""
        ctx = rapports.Contexte(self.win)
        self.lbl_titre.setText(f"<b>{ctx.navire}</b> — {ctx.point_texte}")
        choisi = self.combo_port.currentData() if self.combo_port.count() else ""
        self.combo_port.blockSignals(True)
        self.combo_port.clear()
        self.combo_port.addItem("Tous les ports (une feuille de déchargement par port)", "")
        for p in rapports.ports_de_dechargement(self.win):
            self.combo_port.addItem(p, p)
        i = self.combo_port.findData(choisi or "")
        self.combo_port.setCurrentIndex(max(0, i))
        self.combo_port.blockSignals(False)
        # le dossier ne se reprend QUE s'il n'a pas été choisi à la main :
        # l'officier qui a désigné un dossier ne veut pas le voir remplacé
        defaut = ctx.dossier_par_defaut()
        if self.champ_dossier.text().strip() in ("", self._dossier_propose or ""):
            self.champ_dossier.setText(defaut)
        self._dossier_propose = defaut
        self._refresh_apercu()

    def _designer(self, cle):
        """Le document sur lequel portent l'aperçu et l'impression."""
        self._vise = cle
        self._refresh_apercu()
        return cle

    def document_vise(self):
        """La clé du document aperçu : le dernier désigné s'il est coché,
        sinon le premier coché — on n'aperçoit pas ce qu'on n'exporte pas."""
        coches = [c for c, cb in self.cases.items() if cb.isChecked()]
        if self._vise in coches:
            return self._vise
        return coches[0] if coches else None

    def _libelle_du(self, cle):
        for c, libelle in list(rapports.EXPORTS) + [rapports.EXPORT_DOCKERS]:
            if c == cle:
                return libelle
        return cle

    def _refresh_apercu(self):
        """Les deux boutons nomment le document qu'ils vont montrer."""
        if not hasattr(self, "b_apercu"):
            return
        cle = self.document_vise()
        court = self._libelle_du(cle).split(" (")[0] if cle else ""
        peut = bool(cle) and (cle in rapports.PEINTS
                              or rapports.document(self.win, cle) is not None) \
            if cle else False
        self.b_apercu.setText(f"Aperçu : {court}…" if cle else "Aperçu…")
        self.b_imprimer.setText(f"Imprimer : {court}…" if cle else "Imprimer…")
        if not IMPRESSION_DISPONIBLE:
            return
        self.b_apercu.setEnabled(bool(peut))
        self.b_imprimer.setEnabled(bool(peut))
        if cle and not peut:
            self.b_apercu.setToolTip(
                "Ce document n'est qu'un tableau CSV : il n'a pas d'aperçu "
                "avant impression. Ouvrez-le dans un tableur après l'export.")
        else:
            self.b_apercu.setToolTip("Le document coché, tel qu'il s'imprimera.")

    def viser(self, cle):
        """Ouvre la fenêtre SUR UN document : lui seul reste coché.

        On arrive ici par une entrée de menu qui nomme un document précis —
        « Plan de chargement pour les dockers… ». Celui qui l'a choisie veut
        cette feuille-là, pas les douze autres : la laisser noyée au milieu
        de cases toutes cochées lui ferait réimprimer tout le dossier de
        l'escale pour avoir une planche. Un clic remet les autres."""
        cb = self.cases.get(cle)
        if cb is None:
            return None
        for autre, case in self.cases.items():
            case.setChecked(autre == cle)
        cb.setFocus()
        self._designer(cle)
        return cb

    # ------------------------------------------------------------- choix
    def choix(self):
        return {cle for cle, cb in self.cases.items() if cb.isChecked()}

    def port(self):
        return self.combo_port.currentData() or None

    def dossier(self):
        return self.champ_dossier.text().strip()

    def _choisir_dossier(self):
        path = QFileDialog.getExistingDirectory(self, "Dossier des exports",
                                                self.dossier() or os.getcwd())
        if path:
            self.champ_dossier.setText(path)

    # ------------------------------------------------------------- actions
    def exporter(self, demander=None):
        """Exporte les documents cochés. `demander` : ouvrir le choix du
        dossier avant d'écrire (D-62, demande du bord). Par défaut oui — sauf
        hors écran, où aucune boîte ne doit s'ouvrir."""
        choix = self.choix()
        if not choix:
            self.lbl_etat.setText("Rien n'est coché.")
            return
        if demander is None:
            app = QApplication.instance()
            demander = not (app is not None and app.property("carene_tests"))
        if demander:
            propose = self.dossier() or self._dossier_propose
            path = QFileDialog.getExistingDirectory(
                self, "Où exporter ces documents ?", propose or os.getcwd())
            if not path:
                self.lbl_etat.setText("Export annulé : aucun dossier choisi.")
                return
            self.champ_dossier.setText(path)
        dossier = self.dossier()
        if not dossier:
            self.lbl_etat.setText("Indiquez un dossier.")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.ecrits = rapports.tout_exporter(self.win, dossier, choix, self.port())
        except Exception as e:
            QApplication.restoreOverrideCursor()
            self.lbl_etat.setText(f"Échec : {e}")
            app = QApplication.instance()
            if app is not None and app.property("carene_tests"):
                raise            # hors écran, une boîte modale bloquerait la suite pour toujours
            QMessageBox.critical(self, "Exporter", f"L'export a échoué : {e}")
            return
        QApplication.restoreOverrideCursor()
        noms = "<br>".join("• " + os.path.basename(p) for p in self.ecrits)
        self.lbl_etat.setText(f"{len(self.ecrits)} fichier(s) écrit(s) dans "
                              f"<b>{dossier}</b> :<br>{noms}")
        self.win.statusBar().showMessage(
            f"{len(self.ecrits)} fichier(s) exporté(s) dans {dossier}", 10000)
        self._ouvrir_dossier(dossier)
        return self.ecrits

    def _ouvrir_dossier(self, dossier):
        """Montre le dossier dans l'explorateur — jamais dans les tests."""
        app = QApplication.instance()
        if app is not None and app.property("carene_tests"):
            return
        if not getattr(self.win, "demander_confirmations", True):
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(dossier))

    def _imprimante(self):
        # résolution écran : la mise en page (tailles en px) est pensée à 96
        # dpi, et l'aperçu doit montrer exactement ce que donne le PDF
        return QPrinter(QPrinter.PrinterMode.ScreenResolution)

    def apercu(self):
        """Aperçu avant impression DU DOCUMENT COCHÉ (D-62).

        Le bord : « l'aperçu ne montre que l'aperçu de la stab, pas l'aperçu
        de ce que l'on a sélectionné dans la liste. » C'est maintenant le
        document désigné qui est peint, avec sa mise en page (A4 portrait,
        paysage, ou A3 pour les deux planches)."""
        if not IMPRESSION_DISPONIBLE:
            return None
        cle = self.document_vise()
        if cle is None:
            self.lbl_etat.setText("Rien n'est coché : rien à prévisualiser.")
            return None
        ctx = rapports.Contexte(self.win)
        # le document est fabriqué UNE FOIS : l'aperçu redemande le dessin à
        # chaque page affichée et à chaque changement de zoom
        peint = cle in rapports.PEINTS
        doc = None if peint else rapports.document(self.win, cle, ctx, self.port())
        if not peint and doc is None:
            self.lbl_etat.setText(
                f"« {self._libelle_du(cle)} » n'a pas d'aperçu : c'est un "
                "tableau CSV, à ouvrir dans un tableur.")
            return None
        printer = self._imprimante()
        titre = (self._libelle_du(cle).split(" (")[0])
        if not peint:
            _t, _html, _res, paysage = doc
            printer.setPageOrientation(
                QPageLayout.Orientation.Landscape if paysage
                else QPageLayout.Orientation.Portrait)
        dlg = QPrintPreviewDialog(printer, self)
        dlg.setWindowTitle(f"Aperçu — {titre}")
        dlg.resize(900, 760)

        def peindre(pr):
            if peint:
                rapports.peindre_document(self.win, cle, pr, ctx, self.port())
            else:
                t, html, res, paysage = doc
                rapports._preparer(pr, paysage, f"{t} — {ctx.navire}")
                rapports.peindre(pr, ctx, t, html, res)

        dlg.paintRequested.connect(peindre)
        self._apercu = dlg
        if QApplication.instance().property("carene_tests"):
            dlg.show()          # les tests ne bloquent pas sur exec()
        else:
            dlg.exec()
        return dlg

    def imprimer(self):
        """Imprime LE DOCUMENT COCHÉ, comme l'aperçu le montre (D-62)."""
        if not IMPRESSION_DISPONIBLE:
            return
        cle = self.document_vise()
        if cle is None:
            self.lbl_etat.setText("Rien n'est coché : rien à imprimer.")
            return
        titre = self._libelle_du(cle).split(" (")[0]
        printer = self._imprimante()
        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle(f"Imprimer : {titre}")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        peint = rapports.peindre_document(self.win, cle, printer, port=self.port())
        if peint is None:
            self.lbl_etat.setText(
                f"« {self._libelle_du(cle)} » n'a pas d'impression : c'est un "
                "tableau CSV, à ouvrir dans un tableur.")
            return
        self.win.statusBar().showMessage(f"{titre} envoyé à l'impression.", 6000)
