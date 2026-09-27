# -*- coding: utf-8 -*-
"""La fenêtre « Exporter ou imprimer… » (Ctrl+E, Ctrl+P) : choisir quoi, puis
l'exporter (PDF, CSV), le prévisualiser ou l'imprimer — TOUTE la sélection,
à la suite (D-92).

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
        self.setWindowTitle("Exporter ou imprimer")
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
        # L'APERÇU ET L'IMPRESSION PORTENT SUR TOUT CE QUI EST COCHÉ (D-92) :
        # « imperçu doit donner un aperçu de ce qui est sélectionné, idem pour
        # imprimer ». Plus de « document désigné » : la sélection, c'est les cases.
        for cle, libelle in list(rapports.EXPORTS) + [rapports.EXPORT_DOCKERS]:
            cb = QCheckBox(libelle)
            cb.setChecked(True)
            cb.toggled.connect(lambda _v=False: self._refresh_apercu())
            self.cases[cle] = cb
            root.addWidget(cb)
        tout = QHBoxLayout()
        tout.setContentsMargins(0, 0, 0, 0)
        b_tout = QPushButton("Tout cocher")
        b_tout.setProperty("ghost", "1")
        b_tout.clicked.connect(lambda: self.cocher_tout(True))
        b_rien = QPushButton("Tout décocher")
        b_rien.setProperty("ghost", "1")
        b_rien.clicked.connect(lambda: self.cocher_tout(False))
        tout.addWidget(b_tout)
        tout.addWidget(b_rien)
        tout.addStretch(1)
        root.addLayout(tout)
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
        self.b_apercu = QPushButton("Aperçu…")
        self.b_apercu.clicked.connect(self.apercu)
        self.b_imprimer = QPushButton("Imprimer…")
        self.b_imprimer.clicked.connect(self.imprimer)
        if not IMPRESSION_DISPONIBLE:
            for b in (self.b_apercu, self.b_imprimer):
                b.setEnabled(False)
                b.setToolTip("Impression indisponible : module QtPrintSupport absent. "
                             "L'export PDF reste possible.")
        boutons.addWidget(self.b_apercu)
        boutons.addWidget(self.b_imprimer)
        boutons.addStretch(1)
        self.b_exporter = QPushButton("Exporter (PDF, CSV)…")
        self.b_exporter.setToolTip("Écrire les documents cochés dans un dossier.")
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

    def cocher_tout(self, coche=True):
        for cb in self.cases.values():
            cb.setChecked(bool(coche))
        self._refresh_apercu()

    def coches(self):
        """Les documents cochés, dans l'ordre de la fenêtre."""
        return [c for c, cb in self.cases.items() if cb.isChecked()]

    def imprimables(self):
        """Les documents cochés qui se peignent (aperçu, impression) : tous
        sauf les CSV seuls, comme le journal."""
        return [c for c in self.coches() if rapports.imprimable(self.win, c)]

    def _libelle_du(self, cle):
        for c, libelle in list(rapports.EXPORTS) + [rapports.EXPORT_DOCKERS]:
            if c == cle:
                return libelle
        return cle

    def _refresh_apercu(self):
        """Les boutons disent sur combien de documents ils portent."""
        if not hasattr(self, "b_apercu"):
            return
        coches = self.coches()
        n = len(self.imprimables())
        csv = [self._libelle_du(c).split(" (")[0] for c in coches
               if c not in self.imprimables()]
        compte = f" ({n} document{'s' if n > 1 else ''})" if n else ""
        self.b_apercu.setText(f"Aperçu{compte}…")
        self.b_imprimer.setText(f"Imprimer{compte}…")
        self.b_exporter.setEnabled(bool(coches))
        if not IMPRESSION_DISPONIBLE:
            return
        self.b_apercu.setEnabled(n > 0)
        self.b_imprimer.setEnabled(n > 0)
        aide = ("Les documents cochés, à la suite, tels qu'ils s'imprimeront."
                if n else "Cochez au moins un document qui s'imprime.")
        if csv:
            aide += (" Non imprimé, ce n'est qu'un tableau CSV : "
                     + ", ".join(csv) + " — il s'ouvre dans un tableur après l'export.")
        self.b_apercu.setToolTip(aide)
        self.b_imprimer.setToolTip(aide)

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
        self._refresh_apercu()
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

    def _documents_prets(self, cles, ctx):
        """Les documents fabriqués UNE FOIS : l'aperçu redemande le dessin à
        chaque page affichée et à chaque changement de zoom."""
        return {c: rapports.document(self.win, c, ctx, self.port())
                for c in cles if c not in rapports.PEINTS}

    def _titres(self, cles):
        return ", ".join(self._libelle_du(c).split(" (")[0] for c in cles)

    def apercu(self):
        """Aperçu avant impression de TOUS LES DOCUMENTS COCHÉS, à la suite,
        chacun dans sa mise en page (D-92) — les CSV seuls exceptés."""
        if not IMPRESSION_DISPONIBLE:
            return None
        cles = self.imprimables()
        if not cles:
            self.lbl_etat.setText("Rien à prévisualiser : cochez au moins un "
                                  "document qui s'imprime (le journal n'est qu'un CSV).")
            return None
        ctx = rapports.Contexte(self.win)
        docs = self._documents_prets(cles, ctx)
        printer = self._imprimante()
        dlg = QPrintPreviewDialog(printer, self)
        dlg.setWindowTitle("Aperçu — " + self._titres(cles))
        dlg.resize(900, 760)
        port = self.port()

        def peindre(pr):
            rapports.peindre_documents(self.win, cles, pr, ctx, port, docs=docs)

        dlg.paintRequested.connect(peindre)
        self._apercu = dlg
        if QApplication.instance().property("carene_tests"):
            dlg.show()          # les tests ne bloquent pas sur exec()
        else:
            dlg.exec()
        return dlg

    def imprimer(self):
        """Imprime TOUS LES DOCUMENTS COCHÉS, à la suite, en un seul envoi,
        comme l'aperçu les montre (D-92)."""
        if not IMPRESSION_DISPONIBLE:
            return None
        cles = self.imprimables()
        if not cles:
            self.lbl_etat.setText("Rien à imprimer : cochez au moins un document "
                                  "qui s'imprime (le journal n'est qu'un CSV).")
            return None
        printer = self._imprimante()
        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle("Imprimer — " + self._titres(cles))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        peints = rapports.peindre_documents(self.win, cles, printer, port=self.port())
        titres = ", ".join(t for _c, t in peints)
        self.lbl_etat.setText(f"Envoyé à l'impression : {titres}.")
        self.win.statusBar().showMessage(f"Envoyé à l'impression : {titres}.", 6000)
        return peints
