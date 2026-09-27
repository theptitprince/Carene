# -*- coding: utf-8 -*-
"""La fenêtre des mises à jour (D-70) : ce qu'il y a de neuf, et le bouton.
Et celle du serveur des mises à jour (D-85) : son adresse, l'identifiant et
le mot de passe du poste.

Le calcul est dans `core/mise_a_jour.py` ; ici, seulement ce qui se voit :
la version proposée, ses notes, une barre pendant le téléchargement, et deux
boutons — *Télécharger et installer*, *Plus tard*. La fenêtre est **non
modale** : une mise à jour n'a pas à interrompre une escale, elle attend
qu'on ait fini.

Le réseau tourne dans un fil à part (`_Tache`) : au lancement, la fenêtre
principale ne doit pas attendre GitHub — sur un poste sans réseau, la
vérification peut mettre quatre secondes à se déclarer hors ligne, et
quatre secondes de fenêtre figée se prennent pour un plantage.

Installer, c'est : télécharger et vérifier le zip, écrire le script,
proposer d'enregistrer le point, fermer Carène, et laisser le script faire
(il attend la fermeture, garde l'ancienne version de côté, déplie le zip,
relance). Le dossier du navire n'est jamais touché.
"""
from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from . import SERVEUR_MAJ, __version__, app_paths, identifiants, journal_technique, theme
from .core import mise_a_jour as MAJ

AVERTISSEMENT_HTTP = (
    "Adresse en <b>http://</b> : l'identifiant et le mot de passe circulent en "
    "clair sur le réseau, et l'empreinte ne protège que d'un téléchargement "
    "abîmé. Passez le serveur en <b>https://</b> dès que possible.")


class _Tache(QThread):
    """Une fonction exécutée hors du fil de l'interface ; `fini(résultat)` ou
    `rate(message)`."""

    fini = Signal(object)
    rate = Signal(str)

    def __init__(self, fonction, parent=None):
        super().__init__(parent)
        self._fonction = fonction

    def run(self):
        try:
            self.fini.emit(self._fonction())
        except Exception as e:                  # noqa: BLE001
            self.rate.emit(f"{type(e).__name__}: {e}")


def verifier_en_arriere_plan(parent, suite, ouvrir=None):
    """Lance `MAJ.verifier` dans un fil et appelle `suite(Verification)` sur le
    fil de l'interface. Rend la tâche (à garder vivante par l'appelant).

    La source : le serveur du bord (D-85), avec l'identifiant et le mot de
    passe que ce poste a gardés pour lui — lus ICI, sur le fil de
    l'interface, pas dans le fil réseau."""
    source = app_paths.source_maj()
    ids = identifiants.lire(source) if MAJ.est_serveur(source) else (None, None)
    ids = ids if ids and ids[0] else None
    tache = _Tache(lambda: MAJ.verifier(source, __version__, ouvrir=ouvrir,
                                        identifiants=ids), parent)
    tache.fini.connect(suite)
    tache.rate.connect(lambda m: suite(MAJ.Verification(courante=__version__, erreur=m)))
    tache.start()
    return tache


class MiseAJourDialog(QDialog):
    """« Une mise à jour est disponible » — et ce qu'on en fait."""

    # l'avancement vient du fil de téléchargement : un signal, jamais un
    # widget touché depuis un autre fil
    progres = Signal(int)

    def __init__(self, win, verification, ouvrir=None, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.v = verification
        self._ouvrir = ouvrir              # accès réseau injectable (tests)
        self._tache = None
        self.zip = ""
        self.installation = None
        self.setWindowTitle("Mise à jour de Carène")
        self.setModal(False)
        self.resize(640, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)
        titre = QLabel(f"Carène {self.v.version} est disponible")
        titre.setStyleSheet("font-size: 18px; font-weight: bold;")
        root.addWidget(titre)
        sous = QLabel(f"Vous utilisez Carène {__version__}. Les mises à jour "
                      f"viennent de <b>{self.v.adresse or app_paths.source_maj()}</b>"
                      + (f" — {self.v.taille / 1e6:.1f} Mo à télécharger."
                         if self.v.taille else "."))
        sous.setObjectName("hint")
        sous.setWordWrap(True)
        root.addWidget(sous)
        if self.v.http_clair:
            clair = QLabel(AVERTISSEMENT_HTTP)
            clair.setWordWrap(True)
            clair.setStyleSheet(f"color: {theme.WARN};")
            root.addWidget(clair)

        root.addWidget(self._etiquette("Ce qu'il y a de neuf"))
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.setMarkdown(self.v.notes or "_(aucune note publiée avec cette version)_")
        root.addWidget(self.notes, 1)

        garde = QLabel(
            "Ce qui se passe : le zip est téléchargé et vérifié (taille, "
            "empreinte), puis Carène vous propose d'enregistrer le point et "
            "se ferme ; un petit script attend sa fermeture, garde l'ancienne "
            "version de côté (<code>_ancienne_" + __version__ + "</code>), "
            "installe la nouvelle et relance Carène.<br><b>Le dossier du "
            "navire, votre journal, la configuration et les journaux ne sont "
            "jamais touchés.</b>")
        garde.setObjectName("hint")
        garde.setWordWrap(True)
        root.addWidget(garde)

        self.barre = QProgressBar()
        self.barre.setRange(0, 100)
        self.barre.setValue(0)
        self.barre.setVisible(False)
        self.progres.connect(self.barre.setValue)
        root.addWidget(self.barre)
        self.lbl_etat = QLabel("")
        self.lbl_etat.setWordWrap(True)
        root.addWidget(self.lbl_etat)

        row = QHBoxLayout()
        self.b_installer = QPushButton("Télécharger et installer…")
        self.b_installer.setProperty("accent", "1")
        self.b_installer.clicked.connect(self.telecharger)
        self.b_page = QPushButton("Voir la page de la version")
        self.b_page.setProperty("ghost", "1")
        self.b_page.setEnabled(bool(self.v.page))
        self.b_page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.v.page)))
        self.b_plus_tard = QPushButton("Plus tard")
        self.b_plus_tard.clicked.connect(self.reject)
        row.addWidget(self.b_installer)
        row.addWidget(self.b_page)
        row.addStretch(1)
        row.addWidget(self.b_plus_tard)
        root.addLayout(row)

    @staticmethod
    def _etiquette(texte):
        lbl = QLabel(texte)
        lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-weight: bold;")
        return lbl

    # ---------------------------------------------------------- téléchargement
    def telecharger(self):
        """Le zip, dans un dossier temporaire, avec la barre qui avance."""
        if self._tache is not None and self._tache.isRunning():
            return None
        self.b_installer.setEnabled(False)
        self.barre.setVisible(True)
        self.barre.setValue(0)
        self.lbl_etat.setText(f"Téléchargement de {self.v.nom_zip}…")
        dossier = os.path.join(tempfile.gettempdir(), "carene_mise_a_jour")
        v, ouvrir = self.v, self._ouvrir
        avancement = self._avancement

        def travail():
            return MAJ.telecharger(v, dossier, ouvrir=ouvrir, progression=avancement)

        self._tache = _Tache(travail, self)
        self._tache.fini.connect(self._telecharge)
        self._tache.rate.connect(self._rate)
        self._tache.start()
        return self._tache

    def _avancement(self, recu, total):
        # appelé depuis le fil de téléchargement : on émet, on ne dessine pas
        if total:
            self.progres.emit(int(100 * recu / total))

    def _rate(self, message):
        self.barre.setVisible(False)
        self.b_installer.setEnabled(True)
        self.lbl_etat.setText(f"<span style='color:{theme.DANGER}'>La mise à jour "
                              f"n'a pas été installée : {message}</span>")
        journal_technique.noter(f"mise à jour : échec — {message}", "erreur")

    def _telecharge(self, chemin):
        self.zip = chemin
        self.barre.setValue(100)
        self.lbl_etat.setText(f"Zip vérifié : {os.path.basename(chemin)}.")
        journal_technique.noter(f"mise à jour : zip téléchargé et vérifié, {chemin}", "info")
        self.installer()

    # ---------------------------------------------------------- installation
    def installer(self):
        """Écrit le script, propose d'enregistrer, ferme Carène, lance."""
        if not self.zip:
            return None
        app = QApplication.instance()
        tests = bool(app is not None and app.property("carene_tests"))
        self.installation = MAJ.preparer_installation(
            self.zip, app_paths.APP_DIR, __version__)
        journal_technique.noter(
            f"mise à jour : script écrit, {self.installation.script}", "info")
        if tests:
            # hors écran on ne ferme rien et on ne lance rien : le script est
            # là, c'est ce que le test vérifie
            self.lbl_etat.setText("Script d'installation prêt (tests : non lancé).")
            return self.installation
        rep = QMessageBox.question(
            self, "Installer la mise à jour",
            f"Carène va se fermer pour installer la version {self.v.version}, "
            "puis se relancer.\n\nSi le point en cours a des modifications, "
            "elles vous seront proposées à l'enregistrement. Continuer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if rep != QMessageBox.StandardButton.Yes:
            self.lbl_etat.setText("Installation reportée : le zip reste prêt, "
                                  "relancez la vérification quand vous voudrez.")
            self.b_installer.setEnabled(True)
            return None
        win = self.win
        if win is not None and not win.peut_fermer():
            self.lbl_etat.setText("Fermeture annulée : la mise à jour attendra.")
            self.b_installer.setEnabled(True)
            return None
        MAJ.lancer_script(self.installation)
        journal_technique.noter("mise à jour : script lancé, fermeture de Carène", "info")
        self.accept()
        if win is not None:
            # la question de fermeture vient d'être posée : on ne la repose pas
            win._fermeture_deja_confirmee = True
            win.close()
        return self.installation


class ServeurMajDialog(QDialog):
    """*Aide › Serveur des mises à jour…* (D-85) : l'adresse du serveur, et
    l'identifiant et le mot de passe du dossier protégé par `.htaccess`.

    L'adresse va dans la configuration du poste ; l'identifiant et le mot de
    passe, jamais dans un fichier : dans le gestionnaire d'identification de
    Windows (`carene/identifiants.py`)."""

    def __init__(self, win=None, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.setWindowTitle("Serveur des mises à jour")
        self.resize(560, 320)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)
        intro = QLabel(
            "Carène cherche ses mises à jour à cette adresse : elle y lit "
            f"<code>{MAJ.DESCRIPTION}</code>, puis télécharge le zip qu'il nomme "
            "et vérifie son empreinte SHA-256 avant de l'installer. Si le "
            "dossier est protégé (<code>.htaccess</code>), donnez l'identifiant "
            "et le mot de passe : ils restent sur ce poste, dans le gestionnaire "
            "d'identification de Windows, jamais dans un fichier.")
        intro.setObjectName("hint")
        intro.setWordWrap(True)
        root.addWidget(intro)
        form = QFormLayout()
        self.adresse = QLineEdit(app_paths.serveur_maj())
        self.adresse.setPlaceholderText(SERVEUR_MAJ)
        self.adresse.textChanged.connect(self._avertir)
        self.identifiant = QLineEdit()
        self.mot_de_passe = QLineEdit()
        self.mot_de_passe.setEchoMode(QLineEdit.EchoMode.Password)
        ident, mdp = identifiants.lire(app_paths.serveur_maj())
        self.identifiant.setText(ident or "")
        self.mot_de_passe.setText(mdp or "")
        form.addRow("Adresse", self.adresse)
        form.addRow("Identifiant", self.identifiant)
        form.addRow("Mot de passe", self.mot_de_passe)
        root.addLayout(form)
        self.lbl_http = QLabel(AVERTISSEMENT_HTTP)
        self.lbl_http.setWordWrap(True)
        self.lbl_http.setStyleSheet(f"color: {theme.WARN};")
        root.addWidget(self.lbl_http)
        self.lbl_etat = QLabel("")
        self.lbl_etat.setWordWrap(True)
        root.addWidget(self.lbl_etat)
        root.addStretch(1)
        row = QHBoxLayout()
        self.b_enregistrer = QPushButton("Enregistrer")
        self.b_enregistrer.setProperty("accent", "1")
        self.b_enregistrer.clicked.connect(self.enregistrer)
        self.b_oublier = QPushButton("Oublier le mot de passe")
        self.b_oublier.setProperty("ghost", "1")
        self.b_oublier.clicked.connect(self.oublier)
        self.b_verifier = QPushButton("Enregistrer et vérifier")
        self.b_verifier.clicked.connect(self.enregistrer_et_verifier)
        fermer = QPushButton("Fermer")
        fermer.clicked.connect(self.reject)
        row.addWidget(self.b_enregistrer)
        row.addWidget(self.b_verifier)
        row.addWidget(self.b_oublier)
        row.addStretch(1)
        row.addWidget(fermer)
        root.addLayout(row)
        self._avertir()

    def _avertir(self, *_a):
        self.lbl_http.setVisible(
            self.adresse.text().strip().lower().startswith("http://"))

    def enregistrer(self):
        """L'adresse dans la configuration, le reste au coffre. Rend True si
        c'est enregistré."""
        adresse = self.adresse.text().strip().rstrip("/") or SERVEUR_MAJ
        if not MAJ.est_serveur(adresse):
            self.lbl_etat.setText(f"<span style='color:{theme.DANGER}'>L'adresse doit "
                                  "commencer par https:// (ou http://).</span>")
            return False
        ancienne = app_paths.serveur_maj()
        app_paths.set_serveur_maj(adresse)
        if MAJ.est_serveur(ancienne) and identifiants.hote_de(ancienne) != identifiants.hote_de(adresse):
            identifiants.effacer(ancienne)
        ident = self.identifiant.text().strip()
        if ident:
            dans_coffre = identifiants.enregistrer(adresse, ident, self.mot_de_passe.text())
            garde = ("gardés dans le gestionnaire d'identification de Windows"
                     if dans_coffre else "gardés pour cette session seulement")
            self.lbl_etat.setText(f"Adresse enregistrée ; identifiant et mot de passe {garde}.")
        else:
            identifiants.effacer(adresse)
            self.lbl_etat.setText("Adresse enregistrée, sans identifiant.")
        journal_technique.noter(f"mise à jour : serveur {adresse}"
                                + (" (avec identifiant)" if ident else ""), "info")
        return True

    def oublier(self):
        identifiants.effacer(app_paths.serveur_maj())
        self.identifiant.clear()
        self.mot_de_passe.clear()
        self.lbl_etat.setText("Identifiant et mot de passe oubliés sur ce poste.")

    def enregistrer_et_verifier(self):
        if not self.enregistrer():
            return None
        if self.win is not None and hasattr(self.win, "verifier_mises_a_jour"):
            self.accept()
            return self.win.verifier_mises_a_jour()
        return None

