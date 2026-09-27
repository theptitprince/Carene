# -*- coding: utf-8 -*-
"""« Signaler un problème… » : trois questions, et le rapport part (D-63).

Le bord veut que les ennuis remontent. Pour cela il faut que signaler coûte
moins cher que de se taire : trois champs, un bouton, et tout le reste —
version, système, navire, point, verdict, dernières lignes du journal
technique — assemblé sans rien demander (`core/rapport_bug.py`).

Trois chemins d'envoi, parce qu'un poste de passerelle n'a pas toujours de
client de messagerie : **ouvrir un courriel** tout prêt, **copier** le rapport
pour le coller ailleurs, ou **l'enregistrer** dans un fichier à joindre. Le
fichier est écrit dans tous les cas dès que le rapport est long : un courriel
tronqué ne sert à personne.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from . import theme
from .core import rapport_bug

CONTACT = rapport_bug.CONTACT


class BugDialog(QDialog):
    """Le formulaire de signalement, et les trois façons de l'envoyer."""

    def __init__(self, win=None, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.fichier = ""
        self.setWindowTitle("Signaler un problème")
        self.resize(720, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        titre = QLabel("Signaler un problème")
        titre.setStyleSheet("font-size: 18px; font-weight: bold;")
        root.addWidget(titre)
        intro = QLabel(
            "Un bogue, un chiffre douteux, une fenêtre qui se ferme : "
            "dites-le. Les signalements se font sur <b>GitHub</b>, dans les "
            f"« Issues » de Carène (<a href='{CONTACT}'>{CONTACT}</a>) — il "
            "faut un compte GitHub, gratuit. <b>Le dépôt est public</b> : "
            "relisez le rapport avant de l'envoyer ; le nom du navire et son "
            "dossier y sont masqués par défaut.<br>"
            "Répondez comme vous pouvez aux trois questions : même "
            "incomplètes, elles valent mieux que rien. Carène joint "
            "d'elle-même ce qui tournait (version, système, navire, point, "
            "verdict) et les dernières lignes du journal technique — c'est là "
            "que les erreurs atterrissent.")
        intro.setObjectName("hint")
        intro.setWordWrap(True)
        root.addWidget(intro)

        self.champs = {}
        for cle, libelle, exemple in (
                ("geste", "Ce que je faisais",
                 "j'ai posé une palette dans la cale 1040, puis appuyé sur R"),
                ("probleme", "Ce qui s'est passé",
                 "le colis a disparu et le verdict est passé à NON ÉVALUABLE"),
                ("attendu", "Ce que j'attendais",
                 "qu'il tourne sur place, comme les autres")):
            root.addWidget(self._etiquette(libelle))
            champ = QPlainTextEdit()
            champ.setPlaceholderText("Par exemple : " + exemple)
            champ.setFixedHeight(64)
            champ.textChanged.connect(self._refresh)
            self.champs[cle] = champ
            root.addWidget(champ)

        self.chk_journal = QCheckBox(
            "Joindre les dernières lignes du journal technique (recommandé)")
        self.chk_journal.setChecked(True)
        self.chk_journal.setToolTip(
            "Le journal technique note les erreurs et les avertissements de "
            "la session. Sans lui, un problème rare est presque impossible à "
            "retrouver. Il ne contient ni chargement ni donnée du navire.")
        self.chk_journal.toggled.connect(self._refresh)
        root.addWidget(self.chk_journal)
        self.chk_masquer = QCheckBox(
            "Masquer le nom du navire et le chemin de son dossier (recommandé : "
            "le signalement est public)")
        self.chk_masquer.setChecked(True)
        self.chk_masquer.toggled.connect(self._refresh)
        root.addWidget(self.chk_masquer)

        root.addWidget(self._etiquette("Ce qui sera envoyé"))
        self.apercu = QPlainTextEdit()
        self.apercu.setReadOnly(True)
        self.apercu.setStyleSheet("font-family: monospace; font-size: 11px;")
        root.addWidget(self.apercu, 1)

        self.lbl_etat = QLabel("")
        self.lbl_etat.setObjectName("hint")
        self.lbl_etat.setWordWrap(True)
        root.addWidget(self.lbl_etat)

        row = QHBoxLayout()
        self.b_mail = QPushButton("Signaler sur GitHub…")
        self.b_mail.setProperty("accent", "1")
        self.b_mail.clicked.connect(self.envoyer)
        self.b_copier = QPushButton("Copier le rapport")
        self.b_copier.clicked.connect(self.copier)
        self.b_fichier = QPushButton("Enregistrer…")
        self.b_fichier.clicked.connect(self.enregistrer)
        b_fermer = QPushButton("Fermer")
        b_fermer.clicked.connect(self.reject)
        row.addWidget(self.b_mail)
        row.addWidget(self.b_copier)
        row.addWidget(self.b_fichier)
        row.addStretch(1)
        row.addWidget(b_fermer)
        root.addLayout(row)

        self._refresh()

    @staticmethod
    def _etiquette(texte):
        lbl = QLabel(texte)
        lbl.setStyleSheet(f"color: {theme.TEXT_DIM}; font-weight: bold;")
        return lbl

    # ------------------------------------------------------------- rapport
    def rapport(self):
        """Le texte tel qu'il partira."""
        return rapport_bug.texte(
            geste=self.champs["geste"].toPlainText(),
            probleme=self.champs["probleme"].toPlainText(),
            attendu=self.champs["attendu"].toPlainText(),
            win=self.win, avec_journal=self.chk_journal.isChecked(),
            masquer_navire=self.chk_masquer.isChecked())

    def _refresh(self):
        """L'aperçu montre le rapport ENTIER : on n'envoie rien qu'on n'ait
        pu lire — c'est ce qui permet de signaler sans crainte."""
        self.apercu.setPlainText(self.rapport())

    # ------------------------------------------------------------- envois
    def envoyer(self):
        """Ouvre un nouveau signalement sur GitHub, titre et corps remplis
        (D-91). Le rapport COMPLET est d'abord copié : un rapport trop long
        pour l'URL y est tronqué, et on le colle à la place."""
        corps = self.rapport()
        url, tronque = rapport_bug.url_signalement(corps, self.win)
        self.copier()
        ouvert = self._ouvrir(url)
        if ouvert:
            self.lbl_etat.setText(
                "Page de signalement ouverte sur GitHub."
                + (" Le rapport y est tronqué : il est complet dans le "
                   "presse-papiers, collez-le à la place." if tronque else "")
                + " Relisez-le avant de l'envoyer : le dépôt est public.")
        else:
            self.lbl_etat.setText(
                "Le navigateur n'a pas pu s'ouvrir sur ce poste. Le rapport est "
                f"copié : ouvrez {CONTACT} depuis un autre poste et collez-le "
                "dans un nouveau signalement.")
        return url

    def _ouvrir(self, url):
        app = QApplication.instance()
        if app is not None and app.property("carene_tests"):
            return True          # hors écran, on n'ouvre pas de navigateur
        return bool(QDesktopServices.openUrl(QUrl(url)))

    def copier(self):
        app = QApplication.instance()
        if app is not None:
            app.clipboard().setText(self.rapport())
        self.lbl_etat.setText(
            f"Rapport copié. Collez-le dans un signalement sur GitHub ({CONTACT}).")
        return True

    def enregistrer(self, silencieux=False, dossier=""):
        """Écrit le rapport dans un fichier texte."""
        corps = self.rapport()
        if not dossier:
            dossier = self._dossier_par_defaut()
        if not silencieux:
            app = QApplication.instance()
            interactif = not (app is not None and app.property("carene_tests"))
            if interactif:
                depart = os.path.join(dossier, rapport_bug.nom_de_fichier())
                chemin, _f = QFileDialog.getSaveFileName(
                    self, "Enregistrer le signalement", depart, "Texte (*.txt)")
                if not chemin:
                    return ""
                with open(chemin, "w", encoding="utf-8") as f:
                    f.write(corps)
                self.fichier = chemin
                self.lbl_etat.setText(f"Signalement enregistré : {chemin}")
                return chemin
        self.fichier = rapport_bug.ecrire(dossier, corps)
        if not silencieux:
            self.lbl_etat.setText(f"Signalement enregistré : {self.fichier}")
        return self.fichier

    def _dossier_par_defaut(self):
        """À côté du journal technique : c'est là qu'on va chercher les
        traces d'un ennui, autant y trouver aussi les signalements."""
        try:
            from . import journal_technique
            return journal_technique.dossier()
        except Exception:                   # pragma: no cover
            return os.path.expanduser("~")
