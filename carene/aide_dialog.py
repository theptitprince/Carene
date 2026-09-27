# -*- coding: utf-8 -*-
"""L'aide de Carène : un navigateur interne sur les pages de `carene/aide/`.

Le bord n'a pas de manuel papier à côté du clavier, et le README du dépôt
parle de fichiers et de fonctions — pas de boutons. Les pages de
`carene/aide/` sont donc écrites pour quelqu'un qui **découvre** le logiciel
et doit charger un navire ; ce module les affiche.

Ce qu'il y a ici :

- le **sommaire**, lu dans `aide/index.md` — les entrées numérotées de la
  liste « Les pages, dans l'ordre de lecture », dans cet ordre. Ajouter une
  page se fait donc en écrivant le fichier et en l'inscrivant dans
  `index.md` : rien à changer dans le code ;
- le **rendu Markdown** par `QTextBrowser.setMarkdown`, puis une passe de
  couleurs prise dans `carene.theme` — le thème clair et le thème sombre
  doivent donner deux pages lisibles, pas une page noire sur fond noir ;
- la **navigation** : Précédent / Suivant suivent l'ordre de lecture,
  Sommaire revient à `index.md`, et un lien `[texte](autre_page.md)` d'une
  page ouvre l'autre page au lieu d'essayer de la télécharger ;
- une **recherche plein texte** sur toutes les pages à la fois, dont les
  résultats se cliquent.

La fenêtre est **non modale** : les plans de la fenêtre principale restent
cliquables pendant qu'on lit.

`ouvrir_aide(win, page="repartiteur.md")` ouvre l'aide directement sur une
page : c'est ce qu'appellent les boutons « ? » du répartiteur et de l'éditeur
de plans, et le bouton « Lire d'abord l'aide… » de l'écran sans navire, qui
arrive sur `creation_du_navire.md` (D-74).

`test_aide.py` vérifie que chaque entrée de menu de la fenêtre principale est
citée quelque part dans ces pages : une fonction nouvelle sans son paragraphe
d'aide fait échouer la suite.
"""
from __future__ import annotations

import os
import re
import unicodedata

from PySide6.QtCore import QSizeF, Qt, QUrl
from PySide6.QtGui import (QDesktopServices, QKeySequence, QShortcut,
                           QTextCharFormat, QTextCursor, QColor)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import MENTION, theme

# L'impression demande QtPrintSupport, absent de certaines installations
# minimales : l'enregistrement en PDF, lui, n'en a pas besoin (QPdfWriter est
# dans QtGui). Une aide qu'on ne peut pas emporter reste lisible à l'écran.
try:
    from PySide6.QtPrintSupport import QPrintDialog, QPrinter
    IMPRESSION_DISPONIBLE = True
except ImportError:                                 # pragma: no cover
    QPrintDialog = QPrinter = None
    IMPRESSION_DISPONIBLE = False

# Le dossier des pages : dans le paquet, donc embarqué tel quel par
# PyInstaller (voir `carene.spec`) et copié par un simple `zip` de `carene/`.
DOSSIER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aide")
INDEX = "index.md"

# `[texte](cible)` — le groupe 1 vaut « ! » quand c'est une image.
LIEN = re.compile(r"(!?)\[([^\]\n]*)\]\(([^)\s]+)\)")
# Une entrée numérotée du sommaire : « 3. [Titre](page.md) — … »
ENTREE_SOMMAIRE = re.compile(r"^\s*\d+\.\s")


# ------------------------------------------------------------------ fichiers
def dossier() -> str:
    """Où vivent les pages d'aide."""
    return DOSSIER


def chemin(page: str) -> str:
    """Le chemin complet d'une page, nommée par son fichier."""
    return os.path.join(DOSSIER, os.path.basename(page))


def existe(page: str) -> bool:
    return os.path.isfile(chemin(page))


def lire(page: str) -> str:
    """Le Markdown d'une page. Une page absente le dit à l'écran plutôt que
    de lever : l'aide ne doit jamais empêcher de travailler."""
    try:
        with open(chemin(page), encoding="utf-8") as f:
            return f.read()
    except OSError as e:
        return ("# Page introuvable\n\nLa page « %s » n'a pas pu être lue "
                "(%s).\n\n[Revenir au sommaire](index.md)\n" % (page, e))


def sommaire() -> list[tuple[str, str]]:
    """Les pages dans l'ordre de lecture : [(fichier, titre), …].

    Lues dans la liste numérotée de `index.md` : c'est ce fichier qui fait
    foi, et non un ordre recopié dans le code."""
    pages, vus = [], set()
    for ligne in lire(INDEX).splitlines():
        if not ENTREE_SOMMAIRE.match(ligne):
            continue
        for bang, titre, cible in LIEN.findall(ligne):
            if bang or not cible.endswith(".md") or cible in vus:
                continue
            vus.add(cible)
            pages.append((cible, titre.strip()))
    return pages


def titre_de(page: str) -> str:
    """Le titre d'une page : son premier `# …`, à défaut son nom de fichier."""
    for ligne in lire(page).splitlines():
        if ligne.startswith("# "):
            return ligne[2:].strip()
    return page


def references(page: str) -> tuple[list[str], list[str]]:
    """(liens vers d'autres pages, images) cités par une page.

    Sert au navigateur et à `test_aide.py`, qui vérifie que tout ce qui est
    cité existe réellement."""
    liens, images = [], []
    for bang, _titre, cible in LIEN.findall(lire(page)):
        if cible.startswith(("http://", "https://", "mailto:", "#")):
            continue
        (images if bang else liens).append(cible)
    return liens, images


# ----------------------------------------------------------------- recherche
def _sans_accents(texte: str) -> str:
    """Pour que « epontille » retrouve « épontille »."""
    plat = unicodedata.normalize("NFD", texte.casefold())
    return "".join(c for c in plat if unicodedata.category(c) != "Mn")


def chercher(motif: str, maxi: int = 60) -> list[tuple[str, str, int, str]]:
    """Cherche `motif` dans toutes les pages.

    Rend [(fichier, titre de la page, n° de ligne, la ligne), …], dans
    l'ordre du sommaire. Insensible à la casse et aux accents."""
    motif = (motif or "").strip()
    if len(motif) < 2:
        return []
    cible = _sans_accents(motif)
    resultats = []
    for page, titre in [(INDEX, "Sommaire")] + sommaire():
        for n, ligne in enumerate(lire(page).splitlines(), 1):
            if cible in _sans_accents(ligne):
                extrait = re.sub(r"[#*`>|]", " ", ligne).strip()
                extrait = re.sub(r"\s{2,}", " ", extrait)
                if extrait:
                    resultats.append((page, titre, n, extrait))
                if len(resultats) >= maxi:
                    return resultats
    return resultats


# -------------------------------------------------------------------- rendu
def feuille_de_style() -> str:
    """La feuille de style du navigateur, dans le thème courant.

    Comme le reste de l'application, les couleurs sont lues dans
    `carene.theme` au moment où on l'applique : un changement de thème se
    répercute en rappelant `retheme()`."""
    return f"""
    QTextBrowser {{
        background: {theme.SURFACE};
        color: {theme.TEXT};
        border: 1px solid {theme.BORDER_SOFT};
        border-radius: 6px;
        padding: 14px 18px;
        selection-background-color: {theme.ACCENT_SOFT};
        selection-color: {theme.ACCENT_DARK};
    }}
    QListWidget {{
        background: {theme.SURFACE};
        color: {theme.TEXT};
        border: 1px solid {theme.BORDER_SOFT};
        border-radius: 6px;
    }}
    QListWidget::item {{ padding: 5px 7px; }}
    QListWidget::item:selected {{
        background: {theme.ACCENT_SOFT};
        color: {theme.ACCENT_DARK};
    }}
    """


def _colorer(doc):
    """Passe de couleurs sur le document rendu.

    `setMarkdown` construit les blocs directement : une feuille de style CSS
    ne les atteint pas. On reprend donc à la main les trois choses qui
    doivent suivre le thème — les titres, les liens et le bord des
    tableaux — plutôt que de laisser un bleu d'usine sur fond ardoise."""
    accent = QColor(theme.ACCENT)
    dim = QColor(theme.TEXT_DIM)

    f_titre = QTextCharFormat()
    f_titre.setForeground(accent)
    f_h3 = QTextCharFormat()
    f_h3.setForeground(dim)
    f_lien = QTextCharFormat()
    f_lien.setForeground(accent)
    f_lien.setFontUnderline(True)

    bloc = doc.begin()
    while bloc.isValid():
        niveau = bloc.blockFormat().headingLevel()
        if niveau:
            cur = QTextCursor(bloc)
            cur.select(QTextCursor.SelectionType.BlockUnderCursor)
            cur.mergeCharFormat(f_titre if niveau <= 2 else f_h3)
            # Qt rend les titres sans marge : deux sections se collent et la
            # page devient un mur de texte. On les aère ici.
            bfmt = bloc.blockFormat()
            bfmt.setTopMargin(22 if niveau <= 2 else 14)
            bfmt.setBottomMargin(6)
            cur = QTextCursor(bloc)
            cur.setBlockFormat(bfmt)
        it = bloc.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid() and frag.charFormat().isAnchor():
                cur = QTextCursor(doc)
                cur.setPosition(frag.position())
                cur.setPosition(frag.position() + frag.length(),
                                QTextCursor.MoveMode.KeepAnchor)
                cur.mergeCharFormat(f_lien)
            it += 1
        bloc = bloc.next()

    # les tableaux : un filet dans la couleur des bordures du thème
    for enfant in doc.rootFrame().childFrames():
        fmt = enfant.frameFormat()
        try:
            fmt.setBorderBrush(QColor(theme.BORDER))
        except AttributeError:                      # pragma: no cover
            continue
        enfant.setFrameFormat(fmt)


# ------------------------------------------------------------------- fenêtre
class AideDialog(QDialog):
    """Le navigateur d'aide : sommaire et recherche à gauche, page à droite."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Aide de Carène")
        self.setModal(False)
        self.resize(1060, 740)
        self.pages = sommaire()
        # l'ordre de lecture, sommaire compris : c'est lui que suivent
        # Précédent et Suivant
        self.ordre = [INDEX] + [f for f, _ in self.pages]
        self.page = INDEX

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ---------------------------------------------------------- à gauche
        gauche = QWidget()
        gauche.setFixedWidth(268)
        lg = QVBoxLayout(gauche)
        lg.setContentsMargins(0, 0, 0, 0)
        lg.setSpacing(6)

        self.champ = QLineEdit()
        self.champ.setPlaceholderText("Rechercher dans toute l'aide…")
        self.champ.setClearButtonEnabled(True)
        self.champ.textChanged.connect(self._recherche_changee)
        lg.addWidget(self.champ)

        self.liste = QListWidget()
        self.liste.setToolTip("Les pages de l'aide, dans l'ordre de lecture.")
        for i, (fichier, titre) in enumerate(self.pages, 1):
            item = QListWidgetItem("%d. %s" % (i, titre))
            item.setData(Qt.ItemDataRole.UserRole, fichier)
            self.liste.addItem(item)
        self.liste.itemClicked.connect(
            lambda it: self.aller(it.data(Qt.ItemDataRole.UserRole)))
        lg.addWidget(self.liste, 1)

        self.resultats = QListWidget()
        self.resultats.setVisible(False)
        self.resultats.itemClicked.connect(self._ouvrir_resultat)
        lg.addWidget(self.resultats, 1)

        self.lbl_etat = QLabel("")
        self.lbl_etat.setObjectName("hint")
        self.lbl_etat.setWordWrap(True)
        lg.addWidget(self.lbl_etat)
        root.addWidget(gauche)

        # ---------------------------------------------------------- à droite
        droite = QVBoxLayout()
        droite.setSpacing(8)
        self.vue = QTextBrowser()
        self.vue.setOpenLinks(False)            # on résout les liens nous-mêmes
        self.vue.setOpenExternalLinks(False)
        self.vue.setSearchPaths([DOSSIER])      # pour les images relatives
        self.vue.anchorClicked.connect(self._lien_clique)
        droite.addWidget(self.vue, 1)

        barre = QHBoxLayout()
        self.b_prec = QPushButton("◀ Précédent")
        self.b_prec.setProperty("ghost", "1")
        self.b_prec.clicked.connect(lambda: self._pas(-1))
        self.b_suiv = QPushButton("Suivant ▶")
        self.b_suiv.setProperty("ghost", "1")
        self.b_suiv.clicked.connect(lambda: self._pas(+1))
        b_som = QPushButton("Sommaire")
        b_som.setProperty("ghost", "1")
        b_som.clicked.connect(lambda: self.aller(INDEX))
        # L'AIDE SUR PAPIER (D-62). Le bord : « on devrait pouvoir exporter
        # l'aide en pdf, ou imprimer chaque page ». Un manuel qu'on ne peut
        # pas emporter à la table à cartes n'est lu que devant l'écran.
        self.b_pdf = QPushButton("PDF…")
        self.b_pdf.setProperty("ghost", "1")
        self.b_pdf.setToolTip("Enregistrer en PDF : cette page seule, ou "
                              "tout le manuel d'un coup.")
        self.b_pdf.clicked.connect(self.exporter_pdf)
        self.b_imprimer = QPushButton("Imprimer…")
        self.b_imprimer.setProperty("ghost", "1")
        self.b_imprimer.setToolTip("Imprimer la page affichée.")
        self.b_imprimer.clicked.connect(self.imprimer)
        if not IMPRESSION_DISPONIBLE:
            self.b_imprimer.setEnabled(False)
            self.b_imprimer.setToolTip(
                "Impression indisponible : module QtPrintSupport absent. "
                "L'enregistrement en PDF reste possible.")
        b_fermer = QPushButton("Fermer")
        b_fermer.clicked.connect(self.close)
        barre.addWidget(self.b_prec)
        barre.addWidget(self.b_suiv)
        barre.addWidget(b_som)
        barre.addStretch(1)
        barre.addWidget(self.b_pdf)
        barre.addWidget(self.b_imprimer)
        barre.addWidget(b_fermer)
        droite.addLayout(barre)
        root.addLayout(droite, 1)

        # Échap ferme, F1 revient au sommaire : la fenêtre se pilote sans
        # souris quand on a les mains sur le clavier du poste de chargement.
        QShortcut(QKeySequence("F1"), self, activated=lambda: self.aller(INDEX))

        self.retheme()
        self.aller(INDEX)

    # ------------------------------------------------------------ navigation
    def aller(self, page: str | None = None, mot: str = ""):
        """Affiche une page. `mot` fait défiler sur sa première occurrence."""
        page = os.path.basename(page or INDEX)
        if not page.endswith(".md"):
            page += ".md"
        self.page = page
        doc = self.vue.document()
        doc.setBaseUrl(QUrl.fromLocalFile(DOSSIER + os.sep))
        doc.setMarkdown(lire(page),
                        doc.MarkdownFeature.MarkdownDialectGitHub)
        _colorer(doc)
        self._ajuster_images()
        self.vue.moveCursor(QTextCursor.MoveOperation.Start)
        if mot:
            # on se pose sur la première occurrence cherchée plutôt qu'en
            # haut de page : un résultat de recherche doit se voir
            self.vue.find(mot)
        else:
            self.vue.verticalScrollBar().setValue(0)
        self._resynchroniser()

    def _ajuster_images(self):
        """Ramène chaque capture à la largeur de la fenêtre.

        Les captures sont livrées à 1 000 px : sans cela, la page défile
        horizontalement dès que la fenêtre est étroite. On repart toujours de
        la taille naturelle de l'image, pour qu'un agrandissement de la
        fenêtre la rende à nouveau grande."""
        from PySide6.QtGui import QTextDocument
        if getattr(self, "vue", None) is None:
            return                              # redimensionné avant la vue
        doc = self.vue.document()
        large = max(260, self.vue.viewport().width() - 56)
        bloc = doc.begin()
        while bloc.isValid():
            it = bloc.begin()
            while not it.atEnd():
                frag = it.fragment()
                it += 1
                if not frag.isValid() or not frag.charFormat().isImageFormat():
                    continue
                fmt = frag.charFormat().toImageFormat()
                source = doc.resource(
                    QTextDocument.ResourceType.ImageResource, QUrl(fmt.name()))
                if source is None or source.isNull():
                    continue
                nat_l, nat_h = source.width(), source.height()
                if not nat_l or not nat_h:
                    continue
                l = min(nat_l, large)
                fmt.setWidth(l)
                fmt.setHeight(round(nat_h * l / nat_l))
                cur = QTextCursor(doc)
                cur.setPosition(frag.position())
                cur.setPosition(frag.position() + frag.length(),
                                QTextCursor.MoveMode.KeepAnchor)
                cur.setCharFormat(fmt)
            bloc = bloc.next()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._ajuster_images()

    def _resynchroniser(self):
        """Remet le sommaire, les boutons et le titre d'aplomb."""
        self.setWindowTitle("Aide de Carène — %s" % titre_de(self.page))
        self.liste.blockSignals(True)
        self.liste.setCurrentRow(-1)
        for i in range(self.liste.count()):
            it = self.liste.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == self.page:
                self.liste.setCurrentRow(i)
                break
        self.liste.blockSignals(False)
        i = self.ordre.index(self.page) if self.page in self.ordre else 0
        self.b_prec.setEnabled(i > 0)
        self.b_suiv.setEnabled(i < len(self.ordre) - 1)

    def _pas(self, sens: int):
        if self.page not in self.ordre:
            return self.aller(INDEX)
        i = self.ordre.index(self.page) + sens
        if 0 <= i < len(self.ordre):
            self.aller(self.ordre[i])

    # --------------------------------------------------------- sur papier
    def document_imprimable(self, tout=False):
        """Le document à imprimer : la page affichée, ou TOUT le manuel.

        On repart du Markdown, pas du document de la vue : le manuel entier
        est une suite de pages séparées par un saut de page, avec le sommaire
        en tête — c'est un livret, pas une capture d'écran. Les images gardent
        leur taille naturelle, bornée à la largeur de la page."""
        from PySide6.QtGui import QTextDocument
        doc = QTextDocument()
        doc.setBaseUrl(QUrl.fromLocalFile(DOSSIER + os.sep))
        if not tout:
            doc.setMarkdown(lire(self.page),
                            doc.MarkdownFeature.MarkdownDialectGitHub)
        else:
            pages = [INDEX] + [p for p, _t in sommaire() if p != INDEX]
            morceaux = []
            for i, page in enumerate(pages):
                texte = lire(page)
                if i:
                    # un saut de page entre deux pages du manuel : chacune
                    # commence en haut d'une feuille, comme un chapitre
                    morceaux.append("\n\n<div style='page-break-before:always'></div>\n\n")
                morceaux.append(texte)
            doc.setMarkdown("\n".join(morceaux),
                            doc.MarkdownFeature.MarkdownDialectGitHub)
        _colorer(doc)
        return doc

    def _nom_de_fichier(self, tout):
        from . import __version__
        if tout:
            return f"Carene_{__version__}_aide_complete.pdf"
        titre = self.page[:-3] if self.page.endswith(".md") else self.page
        return f"Carene_{__version__}_aide_{titre}.pdf"

    def exporter_pdf(self, tout=None, chemin_cible=""):
        """Enregistre l'aide en PDF : cette page, ou le manuel entier.

        `tout=None` : on demande. Les paramètres explicites servent aux tests
        et à un appel depuis un menu."""
        from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter
        from PySide6.QtCore import QMarginsF
        if tout is None:
            rep = QMessageBox.question(
                self, "Aide en PDF",
                "Enregistrer TOUT le manuel en un seul PDF ?\n\n"
                "« Oui » : les " + str(len(sommaire()) + 1) + " pages à la suite, "
                "sommaire en tête.\n« Non » : seulement la page affichée.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes)
            if rep == QMessageBox.StandardButton.Cancel:
                return None
            tout = rep == QMessageBox.StandardButton.Yes
        cible = chemin_cible
        if not cible:
            depart = os.path.join(os.path.expanduser("~"), self._nom_de_fichier(tout))
            cible, _f = QFileDialog.getSaveFileName(
                self, "Enregistrer l'aide en PDF", depart, "PDF (*.pdf)")
            if not cible:
                return None
        if not cible.lower().endswith(".pdf"):
            cible += ".pdf"
        doc = self.document_imprimable(tout)
        writer = QPdfWriter(cible)
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        writer.setPageOrientation(QPageLayout.Orientation.Portrait)
        writer.setPageMargins(QMarginsF(16, 14, 16, 14), QPageLayout.Unit.Millimeter)
        writer.setResolution(96)
        writer.setTitle("Aide de Carène" if tout else f"Aide de Carène — {self.page}")
        writer.setCreator(MENTION)
        rect = writer.pageLayout().paintRectPixels(writer.resolution())
        doc.setPageSize(QSizeF(rect.width(), rect.height()))
        doc.print_(writer)
        del writer                    # le PDF se ferme et s'écrit sur le disque
        self._dire_ecrit(cible, tout)
        return cible

    def _dire_ecrit(self, cible, tout):
        quoi = "Le manuel complet" if tout else "La page affichée"
        self.lbl_etat.setText(f"{quoi} : {os.path.basename(cible)}")
        app = QApplication.instance()
        if app is not None and app.property("carene_tests"):
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(cible) or "."))

    def imprimer(self):
        """Imprime la page affichée (ou tout le manuel, si on le demande)."""
        if not IMPRESSION_DISPONIBLE:
            return None
        rep = QMessageBox.question(
            self, "Imprimer l'aide",
            "Imprimer TOUT le manuel ?\n\n« Non » : seulement la page affichée.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.No)
        if rep == QMessageBox.StandardButton.Cancel:
            return None
        tout = rep == QMessageBox.StandardButton.Yes
        printer = QPrinter(QPrinter.PrinterMode.ScreenResolution)
        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle("Imprimer l'aide")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        self.document_imprimable(tout).print_(printer)
        return printer

    def _lien_clique(self, url: QUrl):
        """Un lien d'une page : une autre page, une ancre, ou le dehors."""
        texte = url.toString()
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)
            return
        if texte.startswith("#"):
            self.vue.scrollToAnchor(texte[1:])
            return
        cible = os.path.basename(url.path() or texte)
        if cible.endswith(".md"):
            self.aller(cible)
            if url.hasFragment():
                self.vue.scrollToAnchor(url.fragment())
            return
        chem = chemin(cible)
        if os.path.exists(chem):
            QDesktopServices.openUrl(QUrl.fromLocalFile(chem))

    # ------------------------------------------------------------- recherche
    def _recherche_changee(self, texte: str):
        trouves = chercher(texte)
        cherche = len((texte or "").strip()) >= 2
        self.resultats.clear()
        self.resultats.setVisible(cherche)
        self.liste.setVisible(not cherche)
        if not cherche:
            self.lbl_etat.setText("")
            return
        for page, titre, ligne, extrait in trouves:
            it = QListWidgetItem("%s — %s" % (titre, extrait[:110]))
            it.setData(Qt.ItemDataRole.UserRole, (page, texte.strip()))
            it.setToolTip("%s, ligne %d" % (page, ligne))
            self.resultats.addItem(it)
        self.lbl_etat.setText(
            "Aucun résultat." if not trouves else
            "%d passage(s) dans %d page(s)."
            % (len(trouves), len({p for p, _, _, _ in trouves})))

    def _ouvrir_resultat(self, item):
        page, mot = item.data(Qt.ItemDataRole.UserRole)
        self.aller(page, mot)

    # ----------------------------------------------------------------- thème
    def retheme(self):
        """Rejoue la feuille de style et la page courante dans le thème
        courant — appelé par *Affichage › Thème sombre*."""
        self.setStyleSheet(feuille_de_style())
        if getattr(self, "page", None):
            self.aller(self.page)


def ouvrir_aide(win, page: str = INDEX):
    """Ouvre (ou ramène au premier plan) l'aide, sur la page demandée.

    Une seule fenêtre par fenêtre appelante : rouvrir l'aide ne doit pas
    empiler cinq navigateurs sur l'écran du bord.

        ouvrir_aide(self, "repartiteur.md")
    """
    dlg = getattr(win, "_aide", None)
    try:
        vivant = dlg is not None and dlg.isVisible() is not None
    except RuntimeError:                        # objet C++ déjà détruit
        vivant = False
    if not vivant:
        dlg = AideDialog(win)
        try:
            win._aide = dlg
        except AttributeError:                  # pragma: no cover
            pass
    dlg.aller(page)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg
