# -*- coding: utf-8 -*-
"""Saisie « Chargement » : composer le plan de cale à la main.

Vue de dessus d'un pont entier, toutes ses cales visibles : on pose et on fait
glisser les charges d'une cale à l'autre à la souris, comme on poserait des
blocs. Un double-clic sur une cale zoome dessus pour le travail de détail.

Le tableau de droite et le plan sont **synchronisés dans les deux sens** :
déplacer un rectangle mesure à jour la ligne, corriger X, Y, l'orientation ou
l'empilement dans le tableau déplace le rectangle.

**Le geste, en une règle** : l'OUTIL dit ce que le clic veut dire. Quatre
outils exclusifs, comme dans un logiciel de dessin — **Sélectionner** (le
clic choisit, le glissement déplace, le cadre sélectionne, le clic droit
retire ; jamais de pose), **Poser** (un lot en main : le fantôme suit le
pointeur, le clic le pose), **Zone** (un cadre garni d'un coup) et
**Mesurer** (un cadre, une cote). Choisir un lot dans la barre bascule tout
seul sur Poser ; « — aucun lot — » ramène à Sélectionner.

Au clavier : A tourne le fantôme sans rien poser, R tourne SUR PLACE le colis
visé, Suppr retire le colis visé ou la sélection.

**Une exception à la règle, et une seule** : le clic sur une épontille
amovible la met en place ou la dépose, lot en main ou non. Sous le pointeur
il n'y a pas une place libre, il y a un mur (D-30) — on ne pose pas un colis
dans un mur, on décide s'il est là.

**ÉCHAP RAMÈNE TOUJOURS À « SÉLECTIONNER »** — « quand on frappe Échap, ça
devrait nous ramener systématiquement sur un outil sélectionner ». Elle lâche
le lot, annule le cadre, le glissement ou la mesure en cours, et remet l'outil
à Sélectionner ; frappée une seconde fois, alors qu'il n'y a plus rien à
annuler, elle vide la sélection.

**Et elle marche d'où qu'on la frappe.** Deux chemins, une seule règle
(`_echap_permis`) : le plan prend le clavier dès que la souris entre dessus
(`DeckStowView.enterEvent`), et le panneau pose un filtre sur
l'APPLICATION — pas sur la fenêtre — pour les moments où le focus est
ailleurs : liste des lots, manifeste, bouton de la barre, retour du
répartiteur, molette du jeu d'arrimage (`CargoPanel.eventFilter`). Seule une
SAISIE DE TEXTE en cours garde sa touche : Échap y annule une frappe. Une
molette, elle, n'annule rien — on ne lui laisse plus la touche.
"""
from __future__ import annotations

import os

from PySide6.QtCore import (QEvent, QObject, QPointF, QRectF, QSettings, Qt, QTimer,
                            Signal)
from PySide6.QtGui import (QAction, QColor, QCursor, QFont, QImage, QPainter,
                           QPen, QPolygonF, QTransform)
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .core.cargo_model import (ManifestLine, Placement, couleur_hex,
                               mention_debord, rect_occupe, se_touchent)
from .core.stowage import (Hold, LONGITUDINALE, Packer, aimanter,
                            bornes_polygone, est_epontille, gerbage_refuse,
                            meme_pile, rect_dans_polygone, rect_epontille,
                            resoudre, trop_haut)
from .project import KIND_CONTOUR
from .stow_editor import (COULEURS_CATEGORIE, DISPOSITION_DITE, PAS_SNAP,
                           _dessiner_annotations, _etiquette_pile,
                           _motif_obstacle, _obstacles_actifs, pivot_en_place,
                           reglages_du_remplissage)
from .saisie import SpinNombre

COLS = ["Cale", "Charge", "X", "Y", "Rot.", "Niv.", "Poids t", "Port"]

# L'entrée de tête du sélecteur de lot : rien en main, le clic choisit.
AUCUN_LOT = "— aucun lot (sélection) —"


# ---------------------------------------------------------------- calques
#
# LE PLAN DE POSE DESSINAIT TOUT, TOUJOURS. « Ces calques doivent être
# contraignants (potentiellement désactivables comme la charge au m²) et
# affichables ou non, histoire de ne pas surcharger la fenêtre quand on place
# les colis » : il y a donc deux familles d'interrupteurs, et il ne faut
# surtout pas les confondre.
#
# - les CALQUES ne commandent que le DESSIN. Décocher « Hauteurs libres »
#   dégage la fenêtre ; la hauteur libre reste ce qu'elle est, et une pile
#   trop haute reste comptée dans les problèmes.
# - les CONTRÔLES commandent le SIGNALEMENT des deux calques non bloquants
#   (D-12 charge au m², D-21 hauteur libre) : éteints, le dépassement n'est
#   plus compté ni surligné. Rien d'autre ne bouge — surtout pas le solveur,
#   qui respecte toujours charge et hauteur, ni le rapport de stabilité.
#
# Ce qui BLOQUE (contour de cale, zone interdite, épontille en place) n'a
# jamais d'interrupteur : on ne désactive pas un mur (D-27, D-30).
CALQUE_FOND = "fond"
CALQUE_CHARGES = "charges"
CALQUE_HAUTEURS = "hauteurs"
CALQUE_EPONTILLES = "epontilles"
CALQUE_INFOS = "infos"
CALQUE_ETIQUETTES = "etiquettes"
CTRL_CHARGE = "controle_charge"
CTRL_HAUTEUR = "controle_hauteur"

# (clé, libellé, coché par défaut, aide)
CALQUES = (
    (CALQUE_FOND, "Fond de plan", True,
     "Le plan calé du pont sous les cales. Il sert à voir où l'on pose, il "
     "n'entre dans aucun calcul (D-10)."),
    (CALQUE_CHARGES, "Zones de charge (t/m²)", True,
     "Le calque des charges admissibles du plan des charges. L'éteindre ne "
     "dégage que la vue : le dépassement reste signalé tant que « Signaler "
     "la charge au m² » est coché."),
    (CALQUE_HAUTEURS, "Hauteurs libres", True,
     "Les zones à plafond bas (« hauteur libre 1.70 m »). L'éteindre ne "
     "dégage que la vue : la pile trop haute reste signalée tant que "
     "« Signaler les hauteurs libres » est coché."),
    (CALQUE_EPONTILLES, "Épontilles", True,
     "Les épontilles amovibles, en place (pleines) ou déposées (pâles). "
     "Éteintes, elles ne se dessinent plus et ne se cliquent plus — mais "
     "celles qui sont EN PLACE continuent d'interdire la pose (D-30)."),
    (CALQUE_INFOS, "Informations", True,
     "Le calque d'information décalqué du plan : traits, repères, textes. "
     "Il ne contraint rien et ne se clique pas."),
    (CALQUE_ETIQUETTES, "Étiquettes des colis", True,
     "Le nom du colis et le compte de sa pile (« ×3 ») écrits dans son "
     "rectangle. Sur un plan très serré, les éteindre rend le dessin lisible."),
)
CONTROLES = (
    (CTRL_CHARGE, "Signaler la charge au m²", True,
     "Compter les dépassements de charge admissible dans les problèmes et "
     "les surligner en rouge (D-12). Décocher n'autorise rien : c'est un "
     "réglage d'affichage de CETTE session, le solveur respecte toujours la "
     "charge admissible et le rapport de stabilité dit ce qu'il dit."),
    (CTRL_HAUTEUR, "Signaler les hauteurs libres", True,
     "Compter les piles trop hautes dans les problèmes et les surligner en "
     "rouge (D-21). Décocher n'autorise rien : c'est un réglage d'affichage "
     "de CETTE session, le solveur respecte toujours la hauteur libre et le "
     "rapport de stabilité dit ce qu'il dit."),
)

# Où les cases sont retenues d'une session à l'autre. Un officier qui travaille
# sans le fond de plan doit le retrouver éteint le lendemain.
CLE_CALQUES = "carene/chargement/calques"
# Les suites de tests détournent les réglages vers un fichier jetable, comme
# `CARENE_CONFIG` détourne la configuration : elles ne doivent pas écrire dans
# les préférences du poste.
ENV_REGLAGES = "CARENE_REGLAGES"


def _en_saisie(widget=None):
    """Quelqu'un est-il en train de TAPER dans ce widget (ou dans celui qui a
    le focus) ?

    On ne prend le clavier à personne qui écrit : un nom de lot à moitié
    saisi, une cote en cours de frappe, une liste déroulante ouverte dont les
    flèches et Échap appartiennent à la liste. Un bouton, un tableau, une vue
    graphique ne tapent rien : le plan peut leur prendre la main sans rien
    perdre.

    Sert aux DEUX chemins du clavier du plan (le focus qui suit la souris, et
    le filet Échap du panneau) — la règle doit être la même des deux côtés."""
    from PySide6.QtWidgets import (QAbstractSpinBox, QLineEdit, QPlainTextEdit,
                                   QTextEdit)
    if QApplication.activePopupWidget() is not None:
        return True          # une liste déroulante est ouverte quelque part
    w = QApplication.focusWidget() if widget is None else widget
    if w is None:
        return False
    if isinstance(w, (QLineEdit, QAbstractSpinBox, QPlainTextEdit, QTextEdit)):
        return True
    if isinstance(w, QComboBox):
        # une liste fermée et non éditable ne saisit rien : ses touches sont
        # des raccourcis d'articles, pas du texte
        return w.isEditable() or w.view().isVisible()
    return False


def _saisie_de_texte(widget=None):
    """Quelqu'un tape-t-il un TEXTE dont Échap serait l'annulation ?

    C'est une question BIEN PLUS ÉTROITE que `_en_saisie`, et c'est voulu.
    `_en_saisie` répond à « peut-on lui prendre le clavier ? » ; celle-ci
    répond à « la touche Échap lui appartient-elle ? ». Les deux réponses
    diffèrent sur un point, et c'est le point qui faisait dire au bord
    qu'« Échap parfois ne fonctionne pas » : la MOLETTE du jeu d'arrimage.
    Elle garde le focus après une saisie tant qu'on ne clique pas ailleurs,
    et Échap n'y annule rien — un nombre déjà écrit dans une molette reste
    écrit. On ne lui laisse donc plus la touche.

    Restent vraies saisies : un champ de ligne (`QLineEdit` — l'éditeur de
    cellule d'un tableau, un champ de recherche, la partie éditable d'une
    liste déroulante) et un pavé de texte, tant qu'ils ne sont pas en lecture
    seule. La ligne d'édition INTERNE d'une molette n'en est pas une : c'est
    elle que Qt donne comme widget focalisé quand la molette a le focus."""
    from PySide6.QtWidgets import (QAbstractSpinBox, QLineEdit, QPlainTextEdit,
                                   QTextEdit)
    w = QApplication.focusWidget() if widget is None else widget
    if w is None:
        return False
    if isinstance(w, (QTextEdit, QPlainTextEdit)):
        return not w.isReadOnly()
    if isinstance(w, QLineEdit):
        if w.isReadOnly():
            return False
        return not isinstance(w.parentWidget(), QAbstractSpinBox)
    return False


def _echap_permis(panneau):
    """La touche Échap appartient-elle au plan de chargement, ici et
    maintenant ?

    UNE seule fonction, pour les DEUX chemins de la touche (le filtre posé sur
    l'application et le plan qui a le focus) : deux règles qui divergeraient,
    c'est exactement l'« Échap qui parfois ne fonctionne pas » du bord.

    Cinq conditions, toutes justifiées :

    - la fenêtre ACTIVE est celle du panneau (on ne prend pas la touche d'une
      autre fenêtre du logiciel) ;
    - aucune fenêtre MODALE n'est ouverte — Échap lui appartient, c'est sa
      façon de se fermer ;
    - aucun POPUP n'est ouvert : une liste déroulante déployée se referme par
      Échap, et elle seule ;
    - le plan est VISIBLE (on n'est pas dans une autre vue à onglets) ;
    - personne ne tape un texte (`_saisie_de_texte`)."""
    if QApplication.activeModalWidget() is not None:
        return False
    if QApplication.activePopupWidget() is not None:
        return False
    try:
        vue = getattr(panneau, "view", None)
        if vue is None or not vue.isVisible():
            return False
        fen = panneau.window()
    except RuntimeError:              # objet C++ détruit (fenêtre fermée)
        return False
    if fen is None:
        return False
    actif = QApplication.activeWindow()
    if actif is not None and actif is not fen:
        return False
    return not _saisie_de_texte()


def reglages():
    """Les réglages persistants de l'application (QSettings)."""
    chemin = os.environ.get(ENV_REGLAGES)
    if chemin:
        return QSettings(chemin, QSettings.Format.IniFormat)
    return QSettings("Carene", "Carene")


def jeu_arrimage(win):
    """Le JEU D'ARRIMAGE réglé à la molette de la vue Chargement (m).

    C'est une PRÉFÉRENCE DE TRAVAIL — l'espace qu'on laisse volontairement
    entre deux colis pour passer les saisines et les fourches — et non une
    dimension de la marchandise : le débord, lui, appartient au lot et se
    règle au manifeste (D-39).

    Une seule valeur pour tout le navire ouvert, lue ici par les trois chemins
    de calepinage — répartiteur, plan de cale, outil Zone — pour qu'ils posent
    la même chose. Elle vit dans la vue de chargement, qui dure autant que la
    fenêtre : le réglage est donc retenu d'un point de chargement à l'autre,
    sans entrer dans aucun fichier (ce n'est ni une donnée du navire ni une
    donnée du chargement). 0 si la vue n'est pas encore là."""
    vue = getattr(getattr(win, "cargo_panel", None), "view", None)
    try:
        return max(0.0, float(getattr(vue, "jeu_m", 0.0) or 0.0))
    except (TypeError, ValueError):
        return 0.0


class Calques(QObject):
    """Ce qui se dessine sur le plan de pose, et ce qui s'y signale.

    Un seul objet pour toute la vue : la barre du plan et le menu Affichage
    de la fenêtre principale cochent les MÊMES cases — deux menus qui
    divergent, c'est un officier qui ne sait plus ce qu'il regarde."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._etat = {cle: defaut for cle, _lib, defaut, _aide
                      in CALQUES + CONTROLES}
        self.relire()

    def actif(self, cle) -> bool:
        return bool(self._etat.get(cle, True))

    def relire(self):
        """Reprend l'état retenu à la session précédente. Une clé absente ou
        illisible garde son défaut : on n'éteint jamais un calque par
        accident de fichier."""
        s = reglages()
        for cle, _lib, defaut, _aide in CALQUES + CONTROLES:
            v = s.value(f"{CLE_CALQUES}/{cle}", None)
            if v is None:
                continue
            # QSettings rend « true »/« false » en texte selon le format
            self._etat[cle] = (v if isinstance(v, bool)
                               else str(v).strip().lower() in ("true", "1", "yes"))
        return self

    def regler(self, cle, valeur):
        """Coche ou décoche, retient le choix, et prévient tout le monde."""
        valeur = bool(valeur)
        if self._etat.get(cle) == valeur:
            return False
        self._etat[cle] = valeur
        reglages().setValue(f"{CLE_CALQUES}/{cle}", valeur)
        self.changed.emit()
        return True

    def signature(self):
        """De quoi distinguer deux états des interrupteurs — ce qui entre dans
        la mémoire des défauts du plan."""
        return tuple(sorted(self._etat.items()))

    def controles_eteints(self):
        """Les contrôles décochés, dits en clair pour la barre d'état."""
        return [nom for cle, nom in ((CTRL_CHARGE, "contrôle de charge au m²"),
                                     (CTRL_HAUTEUR, "contrôle de hauteur"))
                if not self.actif(cle)]


def remplir_menu_calques(menu, calques):
    """Garnit un menu de cases à cocher pilotant `calques`.

    Le même appel sert la barre du plan et le menu Affichage : les deux menus
    partagent l'objet, et chacun se remet d'aplomb quand l'autre change une
    case. Retourne {clé: QAction}."""
    actions = {}
    menu.setToolTipsVisible(True)

    def ajouter(cle, libelle, aide):
        a = QAction(libelle, menu)
        a.setCheckable(True)
        a.setChecked(calques.actif(cle))
        a.setToolTip(aide)
        a.toggled.connect(lambda v, k=cle: calques.regler(k, v))
        menu.addAction(a)
        actions[cle] = a

    for cle, libelle, _defaut, aide in CALQUES:
        ajouter(cle, libelle, aide)
    menu.addSeparator()
    titre = QAction("Contrôles", menu)
    titre.setEnabled(False)          # un intitulé se lit, il ne se coche pas
    menu.addAction(titre)
    for cle, libelle, _defaut, aide in CONTROLES:
        ajouter(cle, libelle, aide)

    def _resync():
        try:
            for cle, a in actions.items():
                a.blockSignals(True)
                a.setChecked(calques.actif(cle))
                a.blockSignals(False)
        except RuntimeError:
            return          # menu refait ou détruit : ces cases n'existent plus

    calques.changed.connect(_resync)
    return actions


# D'où vient un défaut : le compteur et l'info-bulle le disent, sinon
# « 3 problème(s) » n'apprend rien à qui doit décider quoi déplacer.
CALQUE_DE_CHARGE = "charge"
CALQUE_DE_HAUTEUR = "hauteur"
CALQUE_DE_EPONTILLE = "épontille"
CALQUE_DE_INTERDIT = "zone interdite"
CALQUE_DE_POSE = "pose"        # hors cale, chevauchement : ni calque ni réglage


def _hold_de(cap, epontilles_en_place=()):
    """La capacité vue par le moteur de chargement : polygone, hauteur, charge
    admissible, zones interdites et zones de hauteur réduite. C'est lui qui
    tranche ce qui bloque et ce qui ne fait que signaler — le plan n'a pas
    de règle à lui.

    `epontilles_en_place` : les identifiants des épontilles amovibles posées
    à CE point. Elles rejoignent les zones interdites, de sorte que tous les
    chemins de pose les refusent par le même contrôle, sans règle en double."""
    return Hold(cap.code, list(cap.points), cap.z_min, cap.z_max,
                getattr(cap, "charge_admissible_t_m2", 0.0), cap.name,
                obstacles=[tuple(o) for o in _obstacles_actifs(
                    cap, epontilles_en_place) if len(o) >= 4],
                zones_charge=list(getattr(cap, "zones_charge", []) or []),
                classes_imdg=list(getattr(cap, "classes_imdg", []) or []))


def _sur_obstacle(cap, rect, epontilles_en_place=(), tol=1e-9):
    """L'emprise mord-elle une zone INTERDITE de cette capacité ? Retourne
    l'obstacle touché (x0, y0, x1, y1[, nom[, marque]]) ou None.

    Une zone qui annonce une hauteur libre (« hauteur libre 1.70 m ») n'est
    pas interdite : c'est un calque, comme les charges admissibles (D-12) —
    on y pose, et une pile trop haute y est signalée en rouge. Une épontille
    EN PLACE, elle, interdit comme le contour de la cale."""
    return _hold_de(cap, epontilles_en_place).rect_sur_obstacle(rect, tol)


def _hauteur_libre_locale(cap, rect):
    """Hauteur libre sous une emprise : celle de la cale, abaissée par toute
    zone de hauteur réduite que l'emprise touche."""
    return _hold_de(cap).hauteur_libre_en(rect)


def _aire_polygone(points):
    a = 0.0
    n = len(points)
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return abs(a) / 2.0


def _limite_locale(cap, rect):
    """Charge admissible sous une emprise : celle de la zone du calque des
    charges qui s'y trouve, sinon celle de la cale. 0 = non renseignée."""
    return _hold_de(cap).charge_admissible_en(rect)


def _chevauche(a, b, tol=1e-9):
    return (a[0] < b[2] - tol and b[0] < a[2] - tol
            and a[1] < b[3] - tol and b[1] < a[3] - tol)


# Le nom que porte le cadre de l'outil Zone une fois traduit en obstacle. Il
# ne contient AUCUN nombre : une zone dont le nom annonce des mètres se lit
# comme un plafond bas (`hauteur_libre_de`, D-21) et non comme un mur.
NOM_CADRE_ZONE = "cadre de la zone"


def _obstacles_du_cadre(bbox, zone):
    """Le cadre demandé, traduit en OBSTACLES pour le calepineur.

    Le calepineur raisonne sur une cale entière ; on veut qu'il ne pose que
    dans le cadre. Découper le polygone de la cale par le cadre serait une
    géométrie de plus à écrire, à croire et à tenir juste le long d'une
    muraille oblique. Autour du rectangle demandé il reste, dans la boîte de
    la cale, quatre rectangles — arrière, avant, bâbord, tribord : les ajouter
    aux obstacles de la cale donne exactement le même résultat avec les murs
    que le moteur sait déjà refuser (D-27), et le contour de la cale n'est pas
    touché.

    Les quatre rectangles débordent largement la boîte de la cale : un colis à
    cheval sur la limite du cadre en mord un, et il est REFUSÉ — pas rogné,
    pas déplacé. Un colis qui affleure la limite, lui, passe : toucher n'est
    pas mordre, comme contre la muraille (D-27)."""
    zx0, zy0, zx1, zy1 = zone
    marge = 10.0
    ax0 = min(bbox[0], zx0) - marge
    ay0 = min(bbox[1], zy0) - marge
    ax1 = max(bbox[2], zx1) + marge
    ay1 = max(bbox[3], zy1) + marge
    murs = []
    if zx0 > ax0:
        murs.append((ax0, ay0, zx0, ay1, NOM_CADRE_ZONE))      # arrière
    if zx1 < ax1:
        murs.append((zx1, ay0, ax1, ay1, NOM_CADRE_ZONE))      # avant
    if zy0 > ay0:
        murs.append((zx0, ay0, zx1, zy0, NOM_CADRE_ZONE))      # tribord
    if zy1 < ay1:
        murs.append((zx0, zy1, zx1, ay1, NOM_CADRE_ZONE))      # bâbord
    return murs


def _touche(cadre, rect):
    """Le cadre effleure-t-il l'emprise ?

    Un cadre de sélection tiré à la volée sur une rangée en attrape rarement
    tous les colis à l'exacte : demander qu'ils soient ENTIÈREMENT dedans
    obligeait à ratisser large et à reprendre trois fois. On prend ce qu'on
    touche — c'est ce que fait tout logiciel de dessin."""
    x0, y0, x1, y1 = cadre
    a0, b0, a1, b1 = rect
    return not (a1 < x0 or x1 < a0 or b1 < y0 or y1 < b0)


def _etiquette_groupe(texte):
    """La petite étiquette grise en capitales d'un groupe de la barre.

    « Le bandeau pourrait être réorganisé pour garder une certaine logique » :
    une file de quinze boutons de rang égal ne dit pas lequel commande le
    pont, lequel commande le geste et lequel commande la marchandise. Les
    mêmes capitales pâles que les cartes du répartiteur et que la barre de
    l'éditeur de plans : le logiciel se lit partout de la même façon."""
    lbl = QLabel(texte)
    lbl.setObjectName("barGroup")
    lbl.setStyleSheet(
        f"QLabel#barGroup {{ color: {theme.TEXT_FAINT}; font-size: 9px;"
        f" font-weight: bold; letter-spacing: 0.9px; background: transparent;"
        f" padding: 0 3px 0 1px; }}")
    return lbl


def _separateur_barre():
    """Le trait vertical qui sépare deux groupes de la barre."""
    s = QFrame()
    s.setFrameShape(QFrame.Shape.VLine)
    s.setFixedWidth(1)
    s.setStyleSheet(f"color: {theme.BORDER_SOFT}; background: {theme.BORDER_SOFT};")
    return s


def _metres(v, decimales=1):
    """Une longueur écrite comme le bord l'écrit : « 41,2 m », virgule
    comprise. Les messages destinés à l'œil se lisent en français ; les
    valeurs comparées par les tests restent des nombres."""
    return f"{v:.{decimales}f}".replace(".", ",") + " m"


def _couleur_port(nom):
    """Couleur stable d'un port : la même d'un point à l'autre du journal."""
    from .core.cargo_model import couleur_de_lot
    return couleur_de_lot(sum(ord(c) for c in (nom or "—")))


def _couleur(p):
    if p.couleur:
        return QColor(p.couleur)
    if getattr(p, "est_materiel_bord", False):
        from .core.cargo_model import COULEUR_MATERIEL_BORD
        return QColor(COULEUR_MATERIEL_BORD)
    return QColor(COULEURS_CATEGORIE.get(p.categorie,
                                         COULEURS_CATEGORIE["Autre"]))


# Les outils du plan. Un seul actif à la fois, comme dans un logiciel de
# dessin : le geste de la souris veut dire une chose et une seule, et on sait
# laquelle en regardant la barre.
#
# POURQUOI « SÉLECTIONNER » EXISTE DE NOUVEAU. On avait fondu « choisir » et
# « poser » en un seul outil, en se disant qu'il n'y avait pas un mode à
# choisir mais une règle à dire : un lot en main, le clic pose ; pas de lot en
# main, le clic choisit. La règle est juste, mais elle n'a pas d'ÉTAT DE
# REPOS : l'officier qui frappe Échap veut revenir à un outil qui ne pose
# rien, quoi qu'il tienne en main — « ça devrait nous ramener
# systématiquement sur un outil sélectionner (qui n'existe pas totalement) ».
# Les deux gestes sont donc de nouveau deux outils, et choisir un lot bascule
# tout seul sur Poser : on ne perd pas la fluidité, on gagne le point de
# retour.
OUTIL_SELECTION = "selection"     # choisir, déplacer, cadre — JAMAIS poser
OUTIL_POSE = "pose"               # un lot en main : le clic pose au fantôme
OUTIL_POSER = OUTIL_POSE          # ancien nom : il désignait déjà « Poser »
OUTIL_ZONE = "zone"               # un cadre = autant de colis qu'il en tient
OUTIL_MESURE = "mesure"           # un cadre = une distance lue
# L'ordre de la barre, et celui des raccourcis : c'est l'ordre du travail.
OUTILS = (OUTIL_SELECTION, OUTIL_POSE, OUTIL_ZONE, OUTIL_MESURE)

# Le fantôme reste accroché à la cale quand la souris en sort : on pousse le
# pointeur dans la muraille pour accoster contre elle, et le colis en main ne
# doit pas s'évanouir pour autant. Au-delà, on a quitté la cale pour de bon.
PORTEE_CALE = 3.0                 # m, distance au-delà de laquelle le fantôme s'efface
# Un clic est un appui qui ne bouge pas. Au-delà, c'est un geste : un cadre
# (depuis le vide) ou un déplacement (depuis un colis posé).
CLIC_IMMOBILE_PX = 4.0
# Le temps d'arrêt du cadre au bout duquel l'aperçu de zone se calepine pour
# de bon. Assez court pour qu'on ne l'attende pas, assez long pour qu'un cadre
# qu'on tire ne déclenche pas un calepinage par image.
DELAI_APERCU_MS = 120


class DeckStowView(QWidget):
    """Pont entier vu de dessus : cales et charges, manipulables à la souris."""

    changed = Signal()
    selection_changed = Signal(object)
    refuse = Signal(str)           # une pose a été annulée, et pourquoi
    coupe_moved = Signal(float)    # le repère de coupe (trait rouge) a bougé
    outil_fini = Signal(str)       # un outil a terminé son geste (message)
    survole = Signal(object)       # la charge sous le pointeur, ou None
    zoom_annule = Signal()         # second double-clic : retour au pont entier
    lot_lache = Signal()           # Échap : plus rien en main, le clic choisit
    epontille_basculee = Signal(str)   # une épontille a été posée/déposée au clic
    epontilles_demandees = Signal()    # clic droit sur une épontille : la fenêtre
    echap_frappee = Signal()       # Échap sur le plan : le panneau tranche
    cale_survolee = Signal(object)     # le pointeur entre dans le vide d'une cale
    cale_ouverte = Signal(object)      # menu : le plan de cale de CELLE-CI
    cale_zoomee = Signal(object)       # double-clic : zoomer sur CETTE cale
    menu_cale = Signal(object, object)  # clic droit dans le vide : (cale, point écran)
    mesure_faite = Signal(object)      # (dx, dy, diagonale) en m, ou None

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        # ce qui se dessine et ce qui se signale — partagé avec le menu
        # « Calques » de la barre et celui du menu Affichage
        self.calques = Calques(self)
        self.calques.changed.connect(self._on_calques)
        self.deck = None
        self.zoom_hold = None          # cale isolée, ou None pour tout le pont
        self.selected = None
        self.setMinimumSize(520, 380)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.aimantation = True        # coller aux voisins et aux parois
        # jeu d'arrimage : ce qu'on laisse VOLONTAIREMENT entre deux colis
        # (saisines, fourches). Réglage de TRAVAIL, jamais un refus de pose —
        # au contraire du débord, qui est une cote du lot (D-39). Il vit ici,
        # donc il est retenu d'un point de chargement à l'autre.
        self.jeu_m = 0.0
        self._image = None             # le plan du pont, calé, sous les cales
        self._image_deck = None
        self.x_coupe = None            # abscisse du repère de coupe (m), None = milieu
        self._drag_coupe = False
        # LA DERNIÈRE MESURE, qui RESTE dessinée : (x0, y0, x1, y1) en repère
        # navire. « L'outil mesure semble ne pas fonctionner » — il
        # fonctionnait, mais le cadre s'effaçait au relâchement et le résultat
        # partait dans la barre d'état, loin des yeux. Une cote qu'on ne peut
        # pas relire n'a pas été prise.
        self.mesure = None
        self.outil = OUTIL_SELECTION
        self.selection = []            # plusieurs charges à la fois
        self.lot = None                # ligne de manifeste que « Poser » emploie
        self.mode_couleur = "lot"      # lot | port | type
        self._cadre = None             # cadre en cours de tracé (repère navire)
        self._drag_multi = None        # déplacement d'un groupe
        self.survol = None             # la charge sous le pointeur
        self.survol_cale = None        # la cale sous le pointeur
        # LE COLIS EN MAIN : tant qu'un lot est choisi, un exemplaire suit le
        # pointeur et montre où il tomberait, aimanté comme s'il était posé.
        # C'est le geste du jeu de construction : on voit la pièce, on la
        # tourne, on la pose — sans viser un bouton entre chaque colis.
        self.rot_main = 0              # orientation de la pièce en main (0 ou 90)
        self.fantome = None            # (rect, refus|None, pile visée|None)
        self.derniere_cale = None      # la dernière cale survolée : le fantôme
        #                                y reste accroché quand la souris sort
        self._press_px = None          # où l'appui a commencé, en pixels
        # MÉMOIRE DES DÉFAUTS : (signature, [(colis, cale, motif)], {id en
        # défaut}). `problemes()` coûte cher (chaque colis contre chaque
        # voisin), et le dessin en avait besoin à CHAQUE repeint — soit à
        # chaque image d'un glissement. On le mémorise, et on l'oublie à
        # chaque mutation : un contour rouge faux serait pire que la lenteur.
        self._problemes = None
        # L'APERÇU DE ZONE calepiné : (clé, plan). Le calepinage coûte deux
        # dixièmes de seconde ; on le calcule quand le cadre s'arrête, pas à
        # chaque image d'un cadre qu'on tire (`apercu_zone`).
        self._apercu = None
        self._minuterie_apercu = QTimer(self)
        self._minuterie_apercu.setSingleShot(True)
        self._minuterie_apercu.timeout.connect(self.calepiner_l_apercu)
        # toute pose, tout retrait, tout déplacement finit par `changed` :
        # c'est le raccord qui garantit qu'aucun chemin n'échappe à l'oubli
        self.changed.connect(self.invalider_problemes)

    def _on_calques(self):
        """Un interrupteur a bougé : le dessin est à refaire, et les défauts
        aussi — éteindre un CONTRÔLE change ce qui est compté."""
        self.invalider_problemes()
        self.update()

    # ------------------------------------------------------------- fond
    def _charger_image(self):
        """Le plan calé du pont (fond de plan de la géométrie), s'il existe.
        Il sert à voir où l'on pose — il n'entre dans aucun calcul (D-10)."""
        if self._image_deck is self.deck:
            return
        self._image_deck = self.deck
        self._image = None
        plan = getattr(self.deck, "plan", None)
        if plan and plan.image_path and os.path.exists(plan.image_path) \
                and plan.calibration.valid:
            img = QImage(plan.image_path)
            if not img.isNull():
                self._image = img

    # ------------------------------------------------------------- modèle
    def holds(self):
        if self.deck is None:
            return []
        if self.zoom_hold is not None:
            return [self.zoom_hold]
        return [c for c in self.deck.capacities
                if c.kind != KIND_CONTOUR and len(c.points) >= 3]

    def placements(self, cap):
        return self.win.condition.placements.setdefault(cap.code, [])

    def epontilles_en_place(self):
        """Les épontilles amovibles posées à ce point (identifiants).

        Elles viennent de la CONDITION, pas du navire : le même plan de cale
        n'a pas les mêmes murs d'une escale à l'autre."""
        cond = getattr(self.win, "condition", None)
        en_place = set(getattr(cond, "epontilles_en_place", []) or [])
        # les épontilles FIXES sont de la structure : en place d'office, quel
        # que soit le point — elles ne figurent pas dans la condition
        proj = getattr(self.win, "project", None)
        if proj is not None and hasattr(proj, "epontilles_fixes"):
            en_place |= proj.epontilles_fixes()
        return en_place

    def hold_of(self, placement):
        for cap in self.holds():
            if placement in self.placements(cap):
                return cap
        return None

    def _bbox(self):
        pts = [p for cap in self.holds() for p in cap.points]
        if not pts:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def _geom(self):
        bb = self._bbox()
        if bb is None:
            return None
        x0, y0, x1, y1 = bb
        span_x, span_y = x1 - x0, y1 - y0
        if span_x <= 0 or span_y <= 0:
            return None
        pad = 30
        w = max(1.0, self.width() - 2 * pad)
        h = max(1.0, self.height() - 2 * pad)
        scale = min(w / span_x, h / span_y)
        left = pad + (w - span_x * scale) / 2
        top = pad + (h - span_y * scale) / 2
        return scale, left, top, x0, y0, span_x, span_y

    def to_px(self, x, y, geom):
        scale, left, top, ox, oy, _sx, span_y = geom
        return left + (x - ox) * scale, top + (span_y - (y - oy)) * scale

    def to_ship(self, px, py, geom):
        scale, left, top, ox, oy, _sx, span_y = geom
        return ox + (px - left) / scale, oy + span_y - (py - top) / scale

    def hold_at(self, x, y):
        from .geometry import point_in_polygon
        for cap in self.holds():
            if point_in_polygon(x, y, cap.points):
                return cap
        return None

    @staticmethod
    def _distance_a(cap, x, y):
        """Distance (m) du point à la boîte de la cale ; 0 s'il est dedans."""
        import math
        x0, y0, x1, y1 = bornes_polygone(cap.points)
        return math.hypot(max(x0 - x, 0.0, x - x1), max(y0 - y, 0.0, y - y1))

    def cale_de_travail(self, x, y):
        """La cale dans laquelle on pose : celle sous le pointeur, ou — quand
        la souris vient d'en sortir — celle qu'on longeait, tant qu'on n'en
        est pas à plus de PORTEE_CALE.

        Accoster un colis contre la muraille se fait en poussant le pointeur
        dedans ; le fantôme ne doit pas s'éteindre à l'instant précis où l'on
        franchit le trait. Au-delà de trois mètres, en revanche, on a quitté
        la cale pour de bon et plus rien ne suit le pointeur. On ne s'accroche
        qu'à la cale RÉELLEMENT survolée : sans cela, viser à côté d'une cale
        poserait dans sa voisine, à deux mètres de là où l'on regarde."""
        cap = self.hold_at(x, y)
        if cap is not None:
            return cap
        derniere = self.derniere_cale
        if derniere is not None and derniere in self.holds() \
                and self._distance_a(derniere, x, y) <= PORTEE_CALE:
            return derniere
        return None

    def _ramener_dans(self, cap, x, y, emprise):
        """Ramène le point visé au bord de la cale, le colis restant entier
        dedans. Approximation par la boîte : l'aimantation, puis `_rapprocher`,
        finissent le travail contre le vrai contour (oblique, en escalier)."""
        dx, dy = emprise
        bx0, by0, bx1, by1 = bornes_polygone(cap.points)
        x = (min(max(x, bx0 + dx / 2), bx1 - dx / 2) if bx1 - bx0 > dx
             else (bx0 + bx1) / 2)
        y = (min(max(y, by0 + dy / 2), by1 - dy / 2) if by1 - by0 > dy
             else (by0 + by1) / 2)
        return x, y

    def _rapprocher(self, pl, cap, pas=0.05):
        """Glisse le colis vers le cœur de la cale jusqu'à ce que la pose
        tienne — et pas plus loin.

        Ramené au bord par la boîte, un colis peut encore mordre une muraille
        oblique ou une voisine. On avance de 5 cm en 5 cm vers le centre et on
        s'arrête à la PREMIÈRE position acceptée : c'est la plus proche du
        bord, donc celle que l'officier visait. Rien n'est jamais posé ici —
        le contrôle de pose (D-27) reste seul juge."""
        if self.pose_refusee(pl, cap) is None:
            return True
        import math
        pts = cap.points
        cx = sum(q[0] for q in pts) / len(pts)
        cy = sum(q[1] for q in pts) / len(pts)
        px, py = pl.centre
        d = math.hypot(cx - px, cy - py)
        if d < 1e-9:
            return False
        ux, uy = (cx - px) / d, (cy - py) / d
        depart = (pl.x, pl.y)
        for i in range(1, int(min(d, PORTEE_CALE * 2) / pas) + 1):
            pl.x = depart[0] + ux * pas * i
            pl.y = depart[1] + uy * pas * i
            if self.pose_refusee(pl, cap) is None:
                return True
        pl.x, pl.y = depart
        return False

    # ------------------------------------------------------------- validité
    def pose_refusee(self, pl, cap, hold=None):
        """Raison géométrique de refuser cette pose, ou None si elle tient.

        Ne juge que la PLACE OCCUPÉE : hors cale ou sur une autre charge. La
        hauteur et la charge de pont sont vérifiées à part, car elles ne
        dépendent pas de l'endroit où on lâche la charge.

        La place occupée, c'est l'ENCOMBREMENT — l'emprise plus le débord du
        lot de chaque côté (D-39) — plus le JEU D'ARRIMAGE réglé à la molette,
        qui est un débord de plus, commun à tous les colis (D-64). Deux
        palettes dont les sacs se touchent, c'est un refus au même titre qu'un
        chevauchement (D-27), et le motif le dit : sans cela l'officier verrait
        une pose refusée entre deux palettes qui ne se touchent visiblement pas.

        `hold` : la cale déjà vue par le moteur, quand l'appelant en tient une
        pour toute la cale (voir `problemes`). La reconstruire par colis est le
        gros du coût sur un pont chargé — le résultat est le même."""
        if cap is None:
            return "hors de toute cale"
        jeu = max(0.0, float(self.jeu_m or 0.0))
        if not rect_dans_polygone(*rect_occupe(pl, jeu), cap.points):
            return "déborde de la cale" + mention_debord(pl, jeu=jeu)
        if hold is None:
            hold = _hold_de(cap, self.epontilles_en_place())
        obstacle = hold.rect_sur_obstacle(rect_occupe(pl, jeu))
        if obstacle is not None:
            return _motif_obstacle(obstacle) + mention_debord(pl, jeu=jeu)
        for q in self.placements(cap):
            if q is not pl and se_touchent(pl, q, jeu):
                return f"chevauche « {q.nom} »" + mention_debord(pl, q, jeu=jeu)
        return None

    def appliquer(self, pl, **modifs):
        """Change la pose d'une charge, et l'annule si elle devient invalide.

        C'est la seule porte d'entrée : plan, clavier et tableau passent tous
        par là, de sorte qu'aucun chemin ne permet de superposer deux charges
        ou d'en faire sortir une de sa cale. Retourne la raison du refus, ou
        None si la modification est acceptée.

        Porte d'entrée unique veut dire aussi : c'est ici qu'on oublie les
        défauts mémorisés, y compris quand la pose est REFUSÉE — le retour en
        arrière est lui-même un mouvement, et la mémoire ne doit rien garder
        d'un état intermédiaire."""
        try:
            return self._appliquer(pl, **modifs)
        finally:
            self.invalider_problemes()

    def _appliquer(self, pl, **modifs):
        source = self.hold_of(pl)
        if source is None:
            # une charge d'un autre pont, ou retirée entre-temps (sélection
            # ou survol périmés) : la poser ici en créerait un double
            refus = "charge absente du plan affiché"
            self.refuse.emit(f"{pl.nom} : {refus} — pose annulée.")
            return refus
        if "rot" in modifs and modifs["rot"] != pl.rot \
                and not getattr(pl, "rotation_permise", True):
            refus = "rotation interdite pour ce type"
            self.refuse.emit(f"{pl.nom} : {refus} — pose annulée.")
            return refus
        avant = {k: getattr(pl, k) for k in modifs}
        for k, v in modifs.items():
            setattr(pl, k, v)
        cible = self.hold_at(*pl.centre)
        # lâché juste sur une pile du même lot : on empile au lieu de refuser
        # le chevauchement — c'est le geste naturel pour empiler (stack)
        pile = self.pile_sous(pl, cible) if ("x" in modifs or "y" in modifs) else None
        if pile is not None:
            refus = gerbage_refuse(pile, max(1, pl.niveaux))
            if refus is None:
                for k, v in avant.items():
                    setattr(pl, k, v)
                self.placements(source).remove(pl)
                pile.niveaux = max(1, pile.niveaux) + max(1, pl.niveaux)
                self.set_selection([pile])
                self.outil_fini.emit(
                    f"{pl.nom} empilé : pile de {pile.niveaux} "
                    f"(stack ×{pile.gerbable_max}).")
                return None
            for k, v in avant.items():
                setattr(pl, k, v)
            self.refuse.emit(f"{pl.nom} : {refus} — pose annulée.")
            return refus
        refus = self.pose_refusee(pl, cible)
        if refus is not None:
            for k, v in avant.items():
                setattr(pl, k, v)
            self.refuse.emit(f"{pl.nom} : {refus} — pose annulée.")
            return refus
        if cible is not source:
            self.placements(source).remove(pl)
            self.placements(cible).append(pl)
        return None

    def pile_sous(self, pl, cap):
        """La pile sur laquelle `pl` vient d'être lâché, ou None.

        « Sur » veut dire : même emprise (dimensions et orientation), et le
        centre de `pl` à l'intérieur de la pile — un colis simplement poussé
        contre sa voisine ne s'y empile pas. Seuls les colis d'un même lot
        (`meme_pile`) forment une pile."""
        if cap is None:
            return None
        cx, cy = pl.centre
        dx, dy = pl.emprise
        for q in self.placements(cap):
            if q is pl or not meme_pile(q, pl):
                continue
            qx0, qy0, qx1, qy1 = q.rect
            ex, ey = q.emprise
            if (abs(ex - dx) < 1e-6 and abs(ey - dy) < 1e-6
                    and qx0 < cx < qx1 and qy0 < cy < qy1):
                return q
        return None

    def elaguer(self):
        """Oublie sélection et survol qui ne sont plus sur le plan affiché :
        après un changement de pont, de point, un passage du solveur ou de
        la boîte de cale, ils désigneraient des charges qui n'y sont plus."""
        vivants = {id(pl) for cap in self.holds() for pl in self.placements(cap)}
        selection = [pl for pl in self.selection if id(pl) in vivants]
        if len(selection) != len(self.selection):
            self.set_selection(selection)
        if self.survol is not None and id(self.survol) not in vivants:
            self.survol = None
            self.survole.emit(None)
        if self.derniere_cale is not None and self.derniere_cale not in self.holds():
            self.derniere_cale = None

    def raisons_detaillees(self, pl, cap, hold=None):
        """[(calque, motif)] : tout ce qui ne va pas pour CE colis dans CETTE
        cale, avec **d'où** ça vient.

        Ce qui BLOQUE d'abord — hors cale, chevauchement, zone interdite,
        épontille en place — puis les deux calques qui alertent sans avoir
        empêché la pose (D-12 la charge, D-21 la hauteur). Ces deux-là
        obéissent aux contrôles de session : décochés, ils ne comptent plus.
        Les murs, eux, comptent toujours (D-27, D-30).

        `hold` : la cale déjà vue par le moteur, s'il y en a une sous la main."""
        if hold is None:
            hold = _hold_de(cap, self.epontilles_en_place())
        out = []
        refus = self.pose_refusee(pl, cap, hold)
        if refus is not None:
            # d'où vient le refus : un obstacle a son motif à lui, tout le
            # reste (contour, voisine) est un défaut de pose
            jeu = max(0.0, float(self.jeu_m or 0.0))
            obstacle = (hold.rect_sur_obstacle(rect_occupe(pl, jeu))
                        if cap is not None else None)
            if obstacle is not None \
                    and _motif_obstacle(obstacle) + mention_debord(pl, jeu=jeu) == refus:
                out.append((CALQUE_DE_EPONTILLE if est_epontille(obstacle)
                            else CALQUE_DE_INTERDIT, refus))
            else:
                out.append((CALQUE_DE_POSE, refus))
        classe = str(getattr(pl, "classe_imdg", "") or "")
        if classe and not hold.admet_imdg(classe):
            admises = ", ".join(hold.classes_imdg) if hold.classes_imdg else "aucune"
            out.append((CALQUE_DE_POSE,
                        f"marchandise dangereuse classe IMDG {classe} : cette cale "
                        f"ne l'admet pas (classes admises : {admises})"))
        if self.calques.actif(CTRL_HAUTEUR):
            haut = trop_haut(hold, pl)
            if haut is not None:
                out.append((CALQUE_DE_HAUTEUR, haut))
        if self.calques.actif(CTRL_CHARGE):
            lim = hold.charge_admissible_en(pl.rect)
            if lim > 0 and pl.charge_surfacique_t_m2() > lim + 1e-9:
                out.append((CALQUE_DE_CHARGE,
                            f"{pl.charge_surfacique_t_m2():.2f} t/m² "
                            f"> {lim:.2f} admissible ici"))
        return out

    def raisons(self, pl, cap, hold=None):
        """Les motifs seuls, sans dire de quel calque ils viennent."""
        return [motif for _calque, motif
                in self.raisons_detaillees(pl, cap, hold)]

    def _signature_defauts(self):
        """De quoi distinguer deux états du plan, à peu de frais : le pont
        affiché, la cale isolée, les épontilles en place, et de chaque colis
        tout ce dont un défaut dépend — position, orientation, dimensions,
        empilement, poids.

        Ce n'est PAS un raffinement : un colis se modifie aussi hors des portes
        d'entrée du plan (un `niveaux` changé à la main, un poids repris au
        tableau), et un contour rouge oublié serait pire que la lenteur qu'on
        cherche à éviter. La signature est donc la vraie clé ;
        `invalider_problemes` couvre le reste — ce qui change dans la CALE
        (zones interdites, charge admissible) et non dans les colis.

        Elle coûte quelques dizaines de microsecondes là où `problemes()` en
        coûte des dizaines de milliers."""
        colis = []
        for cap in self.holds():
            for pl in self.placements(cap):
                colis.append((id(pl), pl.x, pl.y, pl.rot,
                              pl.longueur_m, pl.largeur_m, pl.hauteur_m,
                              pl.debord_m, pl.niveaux, pl.poids_t))
        # les interrupteurs entrent dans la signature : éteindre un contrôle
        # change ce qui est compté sans qu'aucun colis n'ait bougé
        return (id(self.deck), id(self.zoom_hold),
                tuple(sorted(self.epontilles_en_place())),
                self.calques.signature(), tuple(colis))

    def invalider_problemes(self):
        """Oublie les défauts mémorisés : le prochain dessin les recalcule.
        À appeler après TOUTE mutation du plan.

        L'aperçu de zone s'oublie ici aussi : il est calculé sur les colis
        déjà posés, et un aperçu périmé — qui montrerait une place que le
        dernier colis vient de prendre — serait pire que lent."""
        self._problemes = None
        self._apercu = None

    def _calculer_problemes(self):
        """Tous les défauts du pont affiché, cale par cale.

        UN `Hold` par cale et non deux par colis : c'était l'essentiel du coût
        (le moteur reconstruit les zones interdites et les zones de charge à
        chaque construction), pour un résultat rigoureusement identique — les
        obstacles d'une cale ne changent pas d'un colis à l'autre."""
        probs = []
        en_place = self.epontilles_en_place()
        for cap in self.holds():
            hold = _hold_de(cap, en_place)
            for pl in self.placements(cap):
                probs.extend((pl, cap, calque, why) for calque, why
                             in self.raisons_detaillees(pl, cap, hold))
        return probs

    def problemes_detail(self):
        """[(colis, cale, calque, motif)] — mémorisé jusqu'à la prochaine
        mutation. Le calque dit d'où vient le défaut : charge, hauteur,
        épontille, zone interdite, pose."""
        sig = self._signature_defauts()
        if self._problemes is None or self._problemes[0] != sig:
            probs = self._calculer_problemes()
            self._problemes = (sig, probs, {id(pl) for pl, _c, _q, _w in probs})
        return self._problemes[1]

    def problemes(self):
        """[(colis, cale, motif)] — la même liste, sans le calque."""
        return [(pl, cap, why) for pl, cap, _calque, why
                in self.problemes_detail()]

    def colis_en_defaut(self):
        """Les identifiants des colis en défaut — ce que le dessin lit, sans
        avoir à reparcourir les motifs."""
        self.problemes_detail()
        return self._problemes[2]

    # ------------------------------------------------------------- dessin
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.BG_DEEP))
        geom = self._geom()
        if geom is None:
            p.setPen(QColor(theme.TEXT_FAINT))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Aucune cale tracée sur ce pont.")
            p.end()
            return

        self._charger_image()
        if self._image is not None and self.calques.actif(CALQUE_FOND):
            m = self.deck.plan.calibration.M
            pix_to_ship = QTransform(float(m[0, 0]), float(m[1, 0]),
                                     float(m[0, 1]), float(m[1, 1]),
                                     float(m[0, 2]), float(m[1, 2]))
            scale, left, top, ox, oy, _sx, span_y = geom
            ship_to_px = QTransform(scale, 0.0, 0.0, -scale,
                                    left - ox * scale,
                                    top + (span_y + oy) * scale)
            p.save()
            p.setClipRect(self.rect())
            p.setTransform(pix_to_ship * ship_to_px)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.setOpacity(0.55)
            p.drawImage(0, 0, self._image)
            p.restore()

        f = QFont()
        f.setPointSize(8)
        p.setFont(f)
        mauvais = self.colis_en_defaut()
        en_place = self.epontilles_en_place()

        for cap in self.holds():
            poly = QPolygonF([QPointF(*self.to_px(x, y, geom))
                              for x, y in cap.points])
            survolee = cap is self.survol_cale
            p.setPen(QPen(QColor(theme.CAP_SEL if survolee else theme.CAP_EDGE),
                          2.2 if survolee else 1.6))
            if survolee:
                c = QColor(theme.CAP_SEL)
                c.setAlpha(46)
                p.setBrush(c)
            else:
                p.setBrush(QColor(theme.CAP_BASE))
            p.drawPolygon(poly)
            xs = [q[0] for q in cap.points]
            ys = [q[1] for q in cap.points]
            tx, ty = self.to_px(min(xs), max(ys), geom)
            p.setPen(QColor(theme.TEXT_DIM))
            lim = getattr(cap, "charge_admissible_t_m2", 0.0)
            p.drawText(int(tx) + 4, int(ty) + 13,
                       cap.code + (f"  ·  {lim:g} t/m²" if lim > 0 else ""))

            # calque des charges admissibles (non bloquant), puis zones
            # interdites (épontilles fixes, descentes…) et hauteurs réduites.
            # Chaque calque s'éteint séparément — SAUF les zones interdites,
            # qui sont des murs : on ne masque pas ce qui bloque (D-27).
            from .stow_editor import (_dessiner_epontilles, _dessiner_obstacles,
                                      _dessiner_zones_charge)
            if self.calques.actif(CALQUE_CHARGES):
                _dessiner_zones_charge(p, getattr(cap, "zones_charge", []),
                                       lambda x, y: self.to_px(x, y, geom),
                                       getattr(cap, "charge_admissible_t_m2", 0.0))
            _dessiner_obstacles(p, getattr(cap, "obstacles", []),
                                lambda x, y: self.to_px(x, y, geom),
                                hauteurs=self.calques.actif(CALQUE_HAUTEURS))
            # les épontilles par-dessus : en place elles sont pleines, déposées
            # elles restent visibles en pâle — on doit voir où elles vont
            if self.calques.actif(CALQUE_EPONTILLES):
                _dessiner_epontilles(p, cap, en_place,
                                     lambda x, y: self.to_px(x, y, geom))

        # LE CALQUE D'INFORMATION, entre le décor et la marchandise : il
        # appartient au PONT (pas à une cale), il ne contraint rien et ne se
        # clique pas — il passe donc après les cales et sous les colis, qui
        # doivent rester lisibles par-dessus.
        if self.calques.actif(CALQUE_INFOS) and self.deck is not None:
            _dessiner_annotations(p, getattr(self.deck, "annotations", []),
                                  lambda x, y: self.to_px(x, y, geom))
            p.setFont(f)

        etiquettes = self.calques.actif(CALQUE_ETIQUETTES)
        for cap in self.holds():
            for pl in self.placements(cap):
                x0, y0, x1, y1 = pl.rect
                ax, ay = self.to_px(x0, y1, geom)
                bx, by = self.to_px(x1, y0, geom)
                rect = QRectF(ax, ay, bx - ax, by - ay)
                col = self.couleur_de(pl)
                alpha = 205 if pl.niveaux > 1 else 155
                if pl is self.survol:
                    alpha = min(255, alpha + 55)
                p.setBrush(QColor(col.red(), col.green(), col.blue(), alpha))
                if id(pl) in mauvais:
                    stylo = QPen(QColor(theme.DANGER), 2.2)
                elif pl in self.selection:
                    stylo = QPen(QColor(theme.CAP_SEL), 2.4)
                elif pl is self.survol:
                    stylo = QPen(QColor(theme.ACCENT_DARK), 2.0)
                else:
                    stylo = QPen(QColor(theme.SURFACE), 0.9)
                # LE MATÉRIEL DU BORD SE VOIT : contour tireté, plus épais.
                # Ce n'est pas de la marchandise, et l'officier doit le lire
                # sur le plan sans ouvrir un tableau — un chariot du bord et
                # une palette ne se traitent pas de la même façon à l'escale.
                if pl.est_materiel_bord:
                    stylo = QPen(stylo.color(), max(1.8, stylo.widthF()))
                    stylo.setStyle(Qt.PenStyle.DashLine)
                p.setPen(stylo)
                p.drawRect(rect)
                # CE QUI DÉPASSE SE VOIT : le débord du lot, en pointillé
                # autour de la palette. Sans ce trait, le bord ne comprend
                # pas pourquoi ses palettes ne se touchent pas (D-39).
                if pl.deborde:
                    ex0, ey0, ex1, ey1 = pl.rect_encombrement
                    cx, cy = self.to_px(ex0, ey1, geom)
                    ddx, ddy = self.to_px(ex1, ey0, geom)
                    fin = QPen(QColor(col.red(), col.green(), col.blue(), 210), 1.0)
                    fin.setStyle(Qt.PenStyle.DotLine)
                    p.setPen(fin)
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRect(QRectF(cx, cy, ddx - cx, ddy - cy))
                if pl.epingle:
                    p.setPen(QPen(QColor(theme.SURFACE), 1.8))
                    cx, cy = rect.center().x(), rect.top() + 5
                    p.drawLine(int(cx - 3), int(cy), int(cx + 3), int(cy))
                    p.drawLine(int(cx), int(cy - 3), int(cx), int(cy + 3))
                if etiquettes:
                    _etiquette_pile(p, rect, pl)

        # LE COLIS EN MAIN, là où il tomberait : en pointillé, à la couleur du
        # lot ; rouge s'il ne passe pas, avec un « +1 » s'il vient s'empiler sur
        # la pile visée. On le dessine avant le cadre, sous les traits de
        # mesure, et jamais pendant un glissement (le colis déplacé suffit).
        if (self.fantome is not None and self._cadre is None
                and self._drag_multi is None and not self._drag_coupe):
            (fx0, fy0, fx1, fy1), refus, pile = self.fantome
            ax, ay = self.to_px(fx0, fy1, geom)
            bx, by = self.to_px(fx1, fy0, geom)
            r = QRectF(ax, ay, bx - ax, by - ay)
            col = QColor(theme.DANGER) if refus is not None \
                else self.couleur_de(self.lot)
            stylo = QPen(col, 2.0)
            stylo.setStyle(Qt.PenStyle.DashLine)
            p.setPen(stylo)
            p.setBrush(QColor(col.red(), col.green(), col.blue(),
                              40 if refus is not None else 96))
            p.drawRect(r)
            # « × » : ça ne passe pas · « +1 » : ça vient s'empiler sur la pile
            # · « ⟳ » : rien à signaler, et A le fait tourner
            marque = "×" if refus is not None else ("+1" if pile is not None else "⟳")
            p.setPen(QPen(col.darker(140), 1.0))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, marque)

        # le cadre en cours de tracé : sélection, zone à remplir, mesure
        if self._cadre is not None:
            cx0, cy0, cx1, cy1 = self._cadre
            ax, ay = self.to_px(min(cx0, cx1), max(cy0, cy1), geom)
            bx, by = self.to_px(max(cx0, cx1), min(cy0, cy1), geom)
            r = QRectF(ax, ay, bx - ax, by - ay)
            teinte = {OUTIL_ZONE: theme.OK, OUTIL_MESURE: theme.WARN}.get(
                self.outil, theme.CAP_SEL)
            stylo = QPen(QColor(teinte), 1.6)
            stylo.setStyle(Qt.PenStyle.DashLine)
            p.setPen(stylo)
            c = QColor(teinte)
            c.setAlpha(38)
            p.setBrush(c if self.outil != OUTIL_MESURE else Qt.BrushStyle.NoBrush)
            p.drawRect(r)
            if self.outil == OUTIL_MESURE:
                import math
                p.setPen(QColor(teinte))
                p.drawText(r.adjusted(4, 2, -4, -2),
                           Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                           f"{abs(cx1 - cx0):.2f} × {abs(cy1 - cy0):.2f} m  "
                           f"(diag. {math.hypot(cx1 - cx0, cy1 - cy0):.2f})")
            elif self.outil == OUTIL_ZONE:
                # on montre CE QUI SERA POSÉ pendant qu'on tire le cadre :
                # nombre, et l'emplacement de chaque colis
                apercu = self.apercu_zone((min(cx0, cx1), min(cy0, cy1),
                                           max(cx0, cx1), max(cy0, cy1)))
                col = self.couleur_de(self.lot) if self.lot is not None \
                    else QColor(theme.OK)
                p.setPen(QPen(QColor(col), 1.0))
                p.setBrush(QColor(col.red(), col.green(), col.blue(), 120))
                for (ax0, ay0, ax1, ay1) in apercu:
                    ux, uy = self.to_px(ax0, ay1, geom)
                    vx, vy = self.to_px(ax1, ay0, geom)
                    p.drawRect(QRectF(ux, uy, vx - ux, vy - uy))
                p.setPen(QColor(teinte))
                reste = self.reste_du_lot()
                txt = f"{len(apercu)} colis"
                if reste is not None:
                    txt += f" · reste {max(0, reste - len(apercu))} après"
                p.drawText(r.adjusted(4, 2, -4, -2),
                           Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, txt)

        # LA DERNIÈRE MESURE, qui reste écrite sur le plan jusqu'à la
        # suivante : cadre tireté, et les trois cotes lisibles DESSUS — en
        # long, en travers, diagonale. Le bord ne voyait rien parce que le
        # cadre s'effaçait au relâchement ; il reste.
        self._dessiner_mesure(p, geom)

        # le repère de coupe : un trait rouge qu'on glisse
        xc = self.x_coupe_effectif()
        if xc is not None:
            ux, _ = self.to_px(xc, 0.0, geom)
            p.setPen(QPen(QColor(theme.DANGER), 1.6))
            p.drawLine(int(ux), 4, int(ux), self.height() - 4)
            p.setBrush(QColor(theme.DANGER))
            p.drawPolygon(QPolygonF([QPointF(ux - 6, 4), QPointF(ux + 6, 4), QPointF(ux, 14)]))
            p.setPen(QColor(theme.DANGER))
            # HORS DE CE PONT, on le DIT au lieu de mentir sur la cote : le
            # trait est à la borne, le chevron montre de quel côté est le
            # repère, et l'infobulle donne la vraie valeur.
            cote = self.coupe_hors_etendue()
            txt = (f"coupe x = {xc:.1f} m" if cote is None
                   else (f"◂ coupe à {self.x_coupe:.1f} m, hors de ce pont"
                         if cote == "◂"
                         else f"coupe à {self.x_coupe:.1f} m, hors de ce pont ▸"))
            larg = p.fontMetrics().horizontalAdvance(txt)
            # le repère est souvent contre un bord : la légende se ramène dans
            # l'image plutôt que de sortir avec lui
            tx = ux + 6 if cote != "◂" else ux - larg - 6
            tx = min(max(tx, 2.0), max(2.0, self.width() - larg - 2.0))
            p.drawText(int(tx), 16, txt)
        p.end()

    def _dessiner_mesure(self, p, geom):
        """La dernière mesure prise, cotée sur le plan.

        LES COTES S'ÉCRIVENT AUTOUR DU CADRE, jamais dedans : une mesure de
        deux mètres fait trente pixels à l'échelle d'un pont, et trois lignes
        de texte n'y tiennent pas. Une cote illisible, c'est une cote qu'on
        n'a pas prise — et c'est ce qui faisait dire que « l'outil mesure
        semble ne pas fonctionner »."""
        if self.mesure is None:
            return
        import math
        mx0, my0, mx1, my1 = self.mesure
        dx, dy = abs(mx1 - mx0), abs(my1 - my0)
        ax, ay = self.to_px(min(mx0, mx1), max(my0, my1), geom)
        bx, by = self.to_px(max(mx0, mx1), min(my0, my1), geom)
        r = QRectF(ax, ay, bx - ax, by - ay)
        stylo = QPen(QColor(theme.WARN), 1.6)
        stylo.setStyle(Qt.PenStyle.DashLine)
        p.setPen(stylo)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r)
        p.drawLine(r.topLeft(), r.bottomRight())
        p.setPen(QColor(theme.WARN))
        fm = p.fontMetrics()

        def ecrire(x, y, txt):
            """Écrit la cote, en la ramenant dans la fenêtre : un cadre tiré
            contre un bord ne doit pas envoyer sa cote hors de l'image."""
            w = fm.horizontalAdvance(txt)
            x = min(max(x, 2.0), max(2.0, self.width() - w - 2.0))
            y = min(max(y, fm.ascent() + 2.0), self.height() - 2.0)
            p.drawText(int(x), int(y), txt)

        en_long = f"{dx:.2f} m en long"
        en_travers = f"{dy:.2f} m en travers"
        diagonale = f"diagonale {math.hypot(dx, dy):.2f} m"
        ecrire(r.center().x() - fm.horizontalAdvance(en_long) / 2,
               r.top() - 5, en_long)
        ecrire(r.left() - fm.horizontalAdvance(en_travers) - 6,
               r.center().y() + fm.ascent() / 2, en_travers)
        ecrire(r.center().x() - fm.horizontalAdvance(diagonale) / 2,
               r.bottom() + fm.ascent() + 5, diagonale)

    def couleur_de(self, pl):
        """La couleur d'un colis sur le plan, selon le mode d'affichage."""
        if self.mode_couleur == "port":
            return QColor(_couleur_port(pl.port_dechargement))
        if self.mode_couleur == "type":
            from .core.cargo_model import COULEURS_CATEGORIE
            return QColor(COULEURS_CATEGORIE.get(pl.categorie,
                                                 COULEURS_CATEGORIE["Autre"]))
        return _couleur(pl)          # « lot » : la couleur choisie au manifeste

    # --------------------------------------------------- le repère de coupe
    def etendue_coupe(self):
        """L'étendue en X (m) où le repère de coupe a un sens sur le pont
        affiché : (x0, x1), ou None.

        C'est l'union des boîtes des CALES dessinées — celle de la cale seule
        quand on est zoomé dessus — et, à défaut de cale, le contour du pont.
        Au-delà, la coupe traverse du vide : on ne coupe rien."""
        bb = self._bbox()
        if bb is not None:
            return bb[0], bb[2]
        if self.deck is None:
            return None
        pts = [p for cap in self.deck.capacities if len(cap.points) >= 3
               for p in cap.points]
        if not pts:
            return None
        xs = [p[0] for p in pts]
        return min(xs), max(xs)

    def x_coupe_effectif(self):
        """Où le trait rouge se DESSINE : le repère borné à l'étendue des
        cales du pont affiché, ou leur milieu s'il n'a jamais été posé.

        LE REPÈRE EST PARTAGÉ PAR TOUS LES PONTS — c'est ce qu'on veut : la
        coupe qu'on lit à droite est la même quel que soit le niveau qu'on
        regarde. Mais « on peut déplacer le trait de coupe hors des cales sur
        le pont sélectionné, [et] dans la cale inférieure le trait de coupe
        disparaît » : posé à l'avant d'un pont long, il tombait hors du pont
        court d'en dessous, et le trait sortait de l'image avec sa poignée.

        On ne CORRIGE pas la valeur enregistrée pour autant — elle vaut pour
        les autres ponts —, on la borne À L'AFFICHAGE : le trait se dessine à
        la borne la plus proche, la poignée reste saisissable, et un chevron
        dit de quel côté est la vraie valeur (`coupe_hors_etendue`)."""
        et = self.etendue_coupe()
        if self.x_coupe is None:
            bb = self._bbox()
            if bb is not None:
                return (bb[0] + bb[2]) / 2
            return None if et is None else (et[0] + et[1]) / 2
        if et is None:
            return self.x_coupe
        return min(max(self.x_coupe, et[0]), et[1])

    def coupe_hors_etendue(self):
        """De quel côté le repère tombe-t-il hors de ce pont : « ◂ » (avant la
        première cale), « ▸ » (après la dernière), ou None s'il est dessus."""
        et = self.etendue_coupe()
        if self.x_coupe is None or et is None:
            return None
        if self.x_coupe < et[0]:
            return "◂"
        if self.x_coupe > et[1]:
            return "▸"
        return None

    def poser_coupe(self, x):
        """Pose le repère de coupe à cette abscisse, bornée aux cales du pont
        affiché : le glisser ne peut plus l'emmener dans le vide."""
        et = self.etendue_coupe()
        if et is not None:
            x = min(max(x, et[0]), et[1])
        self.x_coupe = round(x, 2)
        self.coupe_moved.emit(self.x_coupe)
        self.update()
        return self.x_coupe

    def infobulle_coupe(self):
        """Ce que dit la poignée du repère de coupe — et, quand il est hors de
        ce pont, POURQUOI le trait n'est pas là où l'on avait laissé le
        repère."""
        xc = self.x_coupe_effectif()
        if xc is None:
            return ""
        cote = self.coupe_hors_etendue()
        if cote is None:
            return (f"Repère de coupe à {_metres(xc)} — glissez-le pour "
                    "déplacer la coupe transversale.")
        return (f"coupe à {_metres(self.x_coupe)}, hors de ce pont : ramenée "
                "à la cale la plus proche. Glissez la poignée pour la reposer "
                "ici.")

    # ------------------------------------------------------------- souris
    def _at(self, x, y):
        for cap in self.holds():
            for pl in reversed(self.placements(cap)):
                x0, y0, x1, y1 = pl.rect
                if x0 <= x <= x1 and y0 <= y <= y1:
                    return pl
        return None

    # --------------------------------------------------- épontilles au plan
    def epontille_at(self, x, y, marge=0.0):
        """L'épontille amovible sous ce point : (cale, épontille) ou
        (None, None).

        `marge` (m) élargit la cible : une épontille de vingt centimètres fait
        trois pixels à l'écran du pont entier, et on ne demande pas à un
        officier de viser au pixel. Les épontilles éteintes au menu des
        calques ne se cliquent pas : ce qu'on ne voit pas ne se bascule pas
        par mégarde."""
        if not self.calques.actif(CALQUE_EPONTILLES):
            return None, None
        for cap in self.holds():
            for e in getattr(cap, "epontilles", []) or []:
                x0, y0, x1, y1 = rect_epontille(e)[:4]
                if (min(x0, x1) - marge <= x <= max(x0, x1) + marge
                        and min(y0, y1) - marge <= y <= max(y0, y1) + marge):
                    return cap, e
        return None, None

    def _marge_clic(self, geom):
        """Six pixels d'écran convertis en mètres, pour viser une épontille."""
        return 6.0 / geom[0] if geom and geom[0] > 0 else 0.0

    def basculer_epontille(self, e):
        """Met en place ou dépose l'épontille visée — LE MÊME chemin que la
        fenêtre « Épontilles… » (`EpontillesDialog.basculer`) : même écriture
        dans la condition, même phrase, y compris quand du fret est dessous.
        Deux chemins de bascule qui divergeraient, c'est un plan qui ment."""
        from .dialogs import EpontillesDialog
        eid = (e or {}).get("id")
        veut = eid not in self.epontilles_en_place()
        msg = EpontillesDialog.basculer(self.win, eid, veut)
        if msg is None:
            return False
        # une épontille en place est un mur (D-30) : ce qui est en défaut
        # change sans qu'aucun colis n'ait bougé
        self.invalider_problemes()
        self.update()
        self.epontille_basculee.emit(msg)
        return True

    def mousePressEvent(self, event):
        """L'appui n'engage rien : c'est le relâchement qui tranche.

        Un appui gauche dans le vide ouvre un cadre ; s'il ne bouge pas, ce
        cadre n'aura été qu'un clic (poser, ou vider la sélection). Un appui
        gauche sur un colis posé arme son déplacement ; s'il ne bouge pas, ce
        n'aura été qu'un choix. C'est ce qui permet au même outil de poser ET
        de sélectionner par cadre, avec ou sans colis en main."""
        geom = self._geom()
        if geom is None:
            return
        x, y = self.to_ship(event.position().x(), event.position().y(), geom)

        # CLIC DROIT SUR UN COLIS POSÉ : on l'enlève, il repart au manifeste.
        # Geste inverse du clic gauche, sans menu ni détour (parole du bord).
        if event.button() == Qt.MouseButton.RightButton:
            if self.retirer_sous(x, y):
                return
            # rien à retirer, mais une épontille visée : la liste à cocher.
            # Le clic gauche bascule celle-là ; le clic droit ouvre toutes
            # les autres, sans passer par la barre.
            _cap, e = self.epontille_at(x, y, self._marge_clic(geom))
            if e is not None:
                self.epontilles_demandees.emit()
                return
            # DANS LE VIDE, LE CLIC DROIT LÂCHE LA PIÈCE EN MAIN. « Une fois
            # qu'on a commencé à placer des colis, on ne peut plus quitter la
            # pose de colis » : Échap le faisait déjà, encore fallait-il que
            # le plan ait le focus. Le clic droit, lui, l'a toujours — c'est
            # la sortie de secours du mode de pose, celle qu'on a dans les
            # doigts.
            if self.lot is not None:
                self.lacher_le_lot()
                return
            # RIEN EN MAIN, DANS LE VIDE D'UNE CALE : SON MENU (D-65). « Un
            # clic droit dans une cale devrait ouvrir un menu : chargement
            # automatique (l'assistant déjà paramétré pour la cale), vider la
            # cale… » Le menu appartient au panneau, qui tient les fenêtres
            # et le répartiteur ; la vue dit seulement quelle cale et où.
            cap = self.hold_at(x, y)
            if cap is not None:
                self.menu_cale.emit(cap, event.globalPosition().toPoint())
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._press_px = (event.position().x(), event.position().y())

        # le repère de coupe se prend n'importe quel outil actif
        xc = self.x_coupe_effectif()
        if xc is not None:
            ux, _ = self.to_px(xc, 0.0, geom)
            if abs(event.position().x() - ux) <= 6 and self._at(x, y) is None:
                self._drag_coupe = True
                return

        # UNE ÉPONTILLE SE BASCULE SUR LE PLAN, là où elle se dresse : « je
        # n'ai pas trouvé comment activer certaines épontilles dans la partie
        # chargement ». AVEC OU SANS LOT EN MAIN : « une fois qu'on a commencé
        # à placer des colis, on ne peut plus recliquer sur les épontilles ».
        # La règle « un lot en main, le clic pose » réservait le geste aux
        # mains vides ; mais sous le pointeur il n'y a pas une place libre, il
        # y a un MUR (D-30) — le clic y posait un colis refusé, ou l'accostait
        # à côté. Cliquer un mur, c'est le mettre en place ou le déposer, et
        # le fret qui se trouvait dessous repart au manifeste comme par la
        # fenêtre « Épontilles… ».
        if self.outil in (OUTIL_SELECTION, OUTIL_POSE) and self._at(x, y) is None:
            _cap, e = self.epontille_at(x, y, self._marge_clic(geom))
            if e is not None:
                self._press_px = None
                self.basculer_epontille(e)
                return

        if self.outil in (OUTIL_ZONE, OUTIL_MESURE):
            self._cadre = (x, y, x, y)
            self.update()
            return

        # --- Sélectionner et Poser : le même appui, deux issues ----------
        pl = self._at(x, y)
        multi = bool(event.modifiers() & (Qt.KeyboardModifier.ControlModifier
                                          | Qt.KeyboardModifier.ShiftModifier))
        if pl is None:
            # rien sous le doigt : cadre en attente. La sélection n'est vidée
            # qu'au relâchement, si le cadre s'est révélé n'être qu'un clic.
            self._cadre = (x, y, x, y)
            self.update()
            return
        if multi:
            sel = list(self.selection)
            sel.remove(pl) if pl in sel else sel.append(pl)
            self.set_selection(sel)
        elif pl not in self.selection:
            self.set_selection([pl])
        # Épinglé = « le SOLVEUR ne me touche pas ». La main de l'officier,
        # elle, garde le dernier mot sur le matériel du bord : un chariot
        # s'arrime là où le bord le décide, on ne lui demande pas de le
        # désépingler d'abord (D-17 — le chargement se pose à la main).
        bougeables = [q for q in self.selection if not self._fige(q)]
        if bougeables:
            self._drag_multi = [(q, x - q.x, y - q.y, (q.x, q.y)) for q in bougeables]
        self.update()

    def mouseMoveEvent(self, event):
        geom = self._geom()
        if geom is None:
            return
        x, y = self.to_ship(event.position().x(), event.position().y(), geom)
        # le suivi de souris est actif pour la surbrillance : un mouvement sans
        # bouton ne doit surtout pas prolonger un cadre ni déplacer une charge
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            self._cadre = None
            if self._drag_multi is not None:
                # glissement interrompu : chaque charge revient d'où elle
                # vient, sinon elle resterait posée sur une voisine
                for q, _dx, _dy, depart in self._drag_multi:
                    q.x, q.y = depart
                self._drag_multi = None
                self.update()
            self._drag_coupe = False
            self._survol(x, y, geom)
            return
        if self._drag_coupe:
            # borné aux cales du pont affiché : on ne traîne plus le trait
            # dans le vide, d'où il disparaissait au pont suivant
            self.poser_coupe(x)
            return
        if self._cadre is not None:
            self._cadre = (self._cadre[0], self._cadre[1], x, y)
            self.update()
            return
        if self._drag_multi is None:
            return
        # le meneur du groupe donne le pas ; les autres suivent du même vecteur
        pl, dx, dy, _depart = self._drag_multi[0]
        nx, ny = x - dx, y - dy
        if not (event.modifiers() & Qt.KeyboardModifier.AltModifier):
            nx = round(nx / PAS_SNAP) * PAS_SNAP
            ny = round(ny / PAS_SNAP) * PAS_SNAP
            if len(self._drag_multi) == 1:
                nx, ny = self._aimanter(pl, nx, ny)
            else:
                # UN GROUPE (sélection au cadre) s'aimante comme un seul
                # bloc : sa place occupée d'ensemble contre les voisins et
                # les parois (D-88) — il ne suivait que la grille de 5 cm
                cx, cy = self._aimanter_groupe(
                    [q for q, *_r in self._drag_multi], nx - pl.x, ny - pl.y)
                nx, ny = pl.x + cx, pl.y + cy
        vx, vy = nx - pl.x, ny - pl.y
        for q, _dx, _dy, _dep in self._drag_multi:
            q.x += vx
            q.y += vy
        self.update()

    def _immobile(self, event):
        """L'appui a-t-il tenu en place ? En deçà de quatre pixels, c'est un
        clic — pas un cadre, pas un déplacement."""
        import math
        if self._press_px is None:
            return True
        return math.hypot(event.position().x() - self._press_px[0],
                          event.position().y() - self._press_px[1]) <= CLIC_IMMOBILE_PX

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        immobile = self._immobile(event)
        self._press_px = None
        if self._drag_coupe:
            self._drag_coupe = False
            return
        geom = self._geom()
        if self._cadre is not None:
            cadre, self._cadre = self._cadre, None
            x0, y0, x1, y1 = (min(cadre[0], cadre[2]), min(cadre[1], cadre[3]),
                              max(cadre[0], cadre[2]), max(cadre[1], cadre[3]))
            minuscule = (x1 - x0) < 0.05 and (y1 - y0) < 0.05
            multi = bool(event.modifiers() & (Qt.KeyboardModifier.ControlModifier
                                              | Qt.KeyboardModifier.ShiftModifier))
            if self.outil == OUTIL_ZONE:
                if not minuscule:
                    self.remplir_zone((x0, y0, x1, y1))
            elif self.outil == OUTIL_MESURE:
                if minuscule:
                    self.effacer_mesure()
                else:
                    self.prendre_mesure((x0, y0, x1, y1))
            elif immobile or minuscule:
                # LE CLIC SIMPLE DANS LE VIDE : sous l'outil Poser, on pose là
                # où le fantôme le montre ; sous Sélectionner, on lâche la
                # sélection — et JAMAIS on ne pose, même un lot en main.
                if geom is not None and self.outil == OUTIL_POSE \
                        and self.lot is not None:
                    ax, ay = self.to_ship(event.position().x(),
                                          event.position().y(), geom)
                    self.poser_un(ax, ay)
                elif not multi:
                    self.set_selection([])
            else:
                # LE CADRE : tout colis POSÉ qu'il touche, même à moitié, et
                # même quand un lot est en main — sélectionner pour déplacer
                # ou retirer en bloc ne doit pas obliger à lâcher sa pièce.
                dedans = [pl for cap in self.holds() for pl in self.placements(cap)
                          if _touche((x0, y0, x1, y1), pl.rect)]
                garde = list(self.selection) if multi else []
                self.set_selection(garde + [p for p in dedans if p not in garde])
                if dedans:
                    self.outil_fini.emit(
                        f"{len(self.selection)} colis sélectionné(s) — "
                        "glissez pour déplacer, Suppr pour remettre au manifeste.")
            self.update()
            return
        if self._drag_multi is None:
            return
        if immobile and self.outil == OUTIL_POSE and self.lot is not None \
                and geom is not None:
            # clic simple sur une pile du MÊME lot : on y ajoute un niveau,
            # c'est le geste du stack, l'empilement (D-22). Sur autre chose, le clic n'a
            # fait que choisir, et le déplacement nul n'a rien changé.
            ax, ay = self.to_ship(event.position().x(), event.position().y(), geom)
            cible = self._at(ax, ay)
            if cible is not None and meme_pile(cible, self.lot.to_placement()):
                for q, _dx, _dy, depart in self._drag_multi:
                    q.x, q.y = depart
                self._drag_multi = None
                self.poser_un(ax, ay)
                return
        groupe, self._drag_multi = self._drag_multi, None
        # le déplacement n'était que visuel : on repart des poses d'origine et
        # on demande chaque changement, refusé s'il n'est pas posable
        arrivees = [(q, q.x, q.y) for q, _dx, _dy, _dep in groupe]
        for q, _dx, _dy, depart in groupe:
            q.x, q.y = depart
        # LE PLUS EN AVANT D'ABORD (D-88) : posés dans l'ordre de la
        # sélection, les colis d'un même lot arrivaient chacun sur la place
        # que le suivant n'avait pas encore quittée — et `appliquer`, qui
        # empile un colis lâché sur une pile de son lot, ramassait le groupe
        # en piles. Dans le sens du mouvement, chacun arrive sur une place
        # déjà libérée.
        if len(arrivees) > 1:
            q0, ax0, ay0 = arrivees[0]
            d0 = next(dep for q, _dx, _dy, dep in groupe if q is q0)
            vx, vy = ax0 - d0[0], ay0 - d0[1]
            arrivees.sort(key=lambda t: -(t[0].x * vx + t[0].y * vy))
        refus = 0
        for q, ax, ay in arrivees:
            if self.appliquer(q, x=ax, y=ay) is not None:
                refus += 1
        if len(groupe) > 1:
            # la sélection reste le groupe, pour le déplacer encore
            self.set_selection([q for q, _ax, _ay in arrivees
                                if self.hold_of(q) is not None])
        if refus and len(groupe) > 1:
            self.refuse.emit(f"{refus} charge(s) sur {len(groupe)} n'ont pas pu "
                             "être déplacées : elles sont restées en place.")
        self.changed.emit()
        self.update()

    # ------------------------------------------------------------- mesure
    def dire_la_mesure(self):
        """La dernière mesure, en une phrase — ou "" s'il n'y en a pas."""
        if self.mesure is None:
            return ""
        import math
        mx0, my0, mx1, my1 = self.mesure
        dx, dy = abs(mx1 - mx0), abs(my1 - my0)
        return (f"Mesure : {dx:.2f} m en long × {dy:.2f} m en travers "
                f"— diagonale {math.hypot(dx, dy):.2f} m.")

    def prendre_mesure(self, cadre):
        """Retient la mesure d'un cadre et la dit.

        Elle RESTE dessinée jusqu'à la suivante, à Échap ou au changement
        d'outil : c'est tout ce qui manquait pour que l'outil « fonctionne »
        aux yeux du bord."""
        import math
        x0, y0, x1, y1 = cadre
        self.mesure = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        self.mesure_faite.emit((dx, dy, math.hypot(dx, dy)))
        self.outil_fini.emit(self.dire_la_mesure())
        self.update()
        return self.mesure

    def effacer_mesure(self):
        """Oublie la mesure dessinée (Échap, changement d'outil)."""
        if self.mesure is None:
            return False
        self.mesure = None
        self.mesure_faite.emit(None)
        self.update()
        return True

    # ------------------------------------------------------------- annuler
    def annuler_geste(self):
        """Abandonne le geste en cours : cadre tiré, groupe en déplacement,
        repère de coupe saisi. Dit si quelque chose a été annulé.

        Chaque charge saisie revient d'où elle vient : un glissement
        abandonné à mi-course laisserait sinon un colis posé sur sa voisine."""
        agi = False
        if self._cadre is not None:
            self._cadre = None
            agi = True
        if self._drag_multi is not None:
            for q, _dx, _dy, depart in self._drag_multi:
                q.x, q.y = depart
            self._drag_multi = None
            agi = True
        if self._drag_coupe:
            self._drag_coupe = False
            agi = True
        self._press_px = None
        if agi:
            self.update()
        return agi

    def _fantome(self, x, y):
        """La pièce en main, projetée là où elle tomberait — ou None.

        On ne la montre que sous l'outil POSER : sous Sélectionner, le clic ne
        pose pas, et un fantôme y promettrait un geste qui n'aura pas lieu.
        Il faut encore que le lot ait de quoi être posé et qu'une cale puisse
        l'accueillir : au-dessus d'une cale, ou à moins de PORTEE_CALE de
        celle qu'on vient de quitter (`cale_de_travail`). Plus loin, plus de
        fantôme : il promettrait une pose impossible."""
        if self.outil != OUTIL_POSE:
            return None
        if self.lot is None or self.cale_de_travail(x, y) is None:
            return None
        reste = self.reste_du_lot()
        if reste is not None and reste <= 0:
            return None
        pl, _cap, refus, pile = self.viser(x, y, self.rot_main,
                                           verifier_reste=False)
        if pl is None:
            return None
        return (pile.rect if pile is not None else pl.rect), refus, pile

    def _survol(self, x, y, geom):
        """Ce qui est sous le pointeur : une charge, une cale, et le colis en
        main projeté à sa place (le « fantôme »)."""
        pl = self._at(x, y)
        cap = self.hold_at(x, y)
        if cap is not None:
            self.derniere_cale = cap      # celle à laquelle le fantôme restera
        avant = self.fantome
        self.fantome = self._fantome(x, y)
        if (pl is not self.survol or cap is not self.survol_cale
                or self.fantome != avant):
            change_de_cale = cap is not self.survol_cale
            self.survol, self.survol_cale = pl, cap
            self.survole.emit(pl)
            # ON ENTRE DANS LE VIDE D'UNE CALE : c'est là que le double-clic
            # ouvre son plan de cale, et c'est là qu'il faut le dire. « Il est
            # difficile de tomber sur la bonne cale » : on nomme celle qui est
            # sous le pointeur, au moment où le geste est possible.
            if change_de_cale and cap is not None and pl is None \
                    and self.outil == OUTIL_SELECTION:
                self.cale_survolee.emit(cap)
            self.update()
        # le curseur dit ce que le geste fera : la croix quand on pose ou
        # qu'on tire un cadre, la main quand on peut saisir un colis
        if pl is None and self.outil in (OUTIL_SELECTION, OUTIL_POSE) \
                and self.epontille_at(x, y, self._marge_clic(geom))[1] is not None:
            # AU-DESSUS D'UNE ÉPONTILLE, le doigt annonce qu'il y a quelque
            # chose à basculer là — un lot en main ou non, puisque le clic y
            # bascule dans les deux cas. Le doigt passe donc devant la croix
            # du fantôme : ce qu'on montre doit être ce que le clic fera.
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif self.outil in (OUTIL_ZONE, OUTIL_MESURE) or self.fantome is not None:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif pl is not None:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def infobulle(self, pl, cap):
        """Ce que dit l'info-bulle d'un colis : ce qu'il est, sa pile, et en
        rouge ce qui ne va pas — avec le CALQUE dont vient le défaut :
        « hauteur — trop haut : 2.40 m pour 1.70 m libre ». Savoir que ça ne
        va pas ne suffit pas : il faut savoir quoi regarder pour y remédier."""
        dx, dy = pl.emprise
        lignes = [f"<b>{pl.nom}</b> — {dx:g} × {dy:g} m, "
                  f"{pl.hauteur_totale_m:.2f} m de haut, {pl.poids_total_t:.2f} t"
                  + (f" · pile de {pl.niveaux}" if pl.niveaux > 1 else "")]
        if pl.deborde:
            # dire les deux mesures : l'officier doit pouvoir rapprocher le
            # rectangle en pointillé du plan de ce qu'il a tapé au manifeste
            ex, ey = pl.encombrement
            lignes.append(f"débord {pl.debord_m:g} m — encombrement "
                          f"{ex:g} × {ey:g} m")
        if cap is not None:
            libre = _hauteur_libre_locale(cap, pl.rect)
            lignes.append(f"{cap.code} · hauteur libre ici {libre:.2f} m")
            for calque, why in self.raisons_detaillees(pl, cap):
                tete = "" if calque == CALQUE_DE_POSE else f"{calque} — "
                lignes.append(
                    f"<span style='color:{theme.DANGER}'>{tete}{why}</span>")
        return "<br>".join(lignes)

    def infobulle_epontille(self, e):
        """Ce que dit l'info-bulle d'une épontille : laquelle, dans quel état,
        et ce que le clic en fera. Un état qu'on ne peut pas changer sans
        ouvrir une fenêtre n'est pas un état qu'on tient à jour."""
        nom = str((e or {}).get("nom") or (e or {}).get("id") or "épontille")
        pose = (e or {}).get("id") in self.epontilles_en_place()
        etat = "en place" if pose else "déposée"
        geste = "déposer" if pose else "mettre en place"
        note = str((e or {}).get("note") or "")
        return (f"<b>Épontille {nom}</b> — {etat} (clic : {geste})"
                + (f"<br>{note}" if note else "")
                + "<br>Clic droit : la liste de toutes les épontilles.")

    def event(self, event):
        if event.type() == QEvent.Type.ToolTip:
            geom = self._geom()
            pl, e = None, None
            if geom is not None:
                # LA POIGNÉE DE COUPE D'ABORD : c'est elle qui doit dire
                # pourquoi le trait n'est pas là où on l'avait laissé
                xc = self.x_coupe_effectif()
                if xc is not None:
                    ux, _ = self.to_px(xc, 0.0, geom)
                    if abs(event.pos().x() - ux) <= 8:
                        QToolTip.showText(event.globalPos(),
                                          self.infobulle_coupe(), self)
                        return True
                x, y = self.to_ship(event.pos().x(), event.pos().y(), geom)
                pl = self._at(x, y)
                if pl is None:
                    _cap, e = self.epontille_at(x, y, self._marge_clic(geom))
            if pl is not None:
                QToolTip.showText(event.globalPos(),
                                  self.infobulle(pl, self.hold_of(pl)), self)
            elif e is not None:
                QToolTip.showText(event.globalPos(), self.infobulle_epontille(e),
                                  self)
            else:
                QToolTip.hideText()
            return True
        return super().event(event)

    def enterEvent(self, event):
        """LE CLAVIER SUIT LA SOURIS : pointer le plan suffit pour qu'il
        réponde.

        Sans cela, Échap, Suppr, A et R demandaient un clic préalable — un
        clic qui déplace parfois le colis qu'on voulait juste retirer, et qui
        pose un colis quand on a un lot en main. C'est aussi ce qui explique
        le « Échap ne fonctionne plus » du bord : dès que le focus était parti
        ailleurs (liste des lots, manifeste, retour du répartiteur), la touche
        n'était plus adressée au plan.

        Deux réserves : la fenêtre doit être ACTIVE (on ne prend pas le
        clavier d'une autre fenêtre parce que le pointeur a traversé
        celle-ci), et on ne prend rien à qui est en train de taper
        (`_en_saisie`)."""
        fen = self.window()
        if (fen is None or fen.isActiveWindow()) and not _en_saisie():
            self.setFocus(Qt.FocusReason.MouseFocusReason)
        return super().enterEvent(event)

    def leaveEvent(self, event):
        # le pointeur quitte le plan tout entier : plus de cale de travail non
        # plus, sinon le fantôme reparaîtrait ailleurs au retour
        self.derniere_cale = None
        if self.survol is not None or self.survol_cale is not None \
                or self.fantome is not None:
            self.survol = self.survol_cale = self.fantome = None
            self.survole.emit(None)
            self.update()
        return super().leaveEvent(event)

    # ------------------------------------------------------- pose à la main
    @staticmethod
    def _fige(pl):
        """La main de l'officier a-t-elle interdiction de bouger ce colis ?

        Une charge épinglée, oui — c'est le sens de l'épingle. Le matériel du
        bord est épinglé pour le SOLVEUR (il ne le déplace ni ne l'empile),
        mais il s'arrime à la main comme n'importe quoi d'autre."""
        return pl.epingle and not pl.est_materiel_bord

    def set_selection(self, charges):
        self.selection = list(charges)
        self.selected = self.selection[0] if len(self.selection) == 1 else None
        self.selection_changed.emit(self.selected)

    def _nouveau_colis(self, verifier_reste=True):
        """Un exemplaire du lot courant, ou None.

        Refuse d'en créer un de plus que le manifeste n'en annonce : poser
        au-delà, c'est agrandir le manifeste sans s'en apercevoir."""
        if self.lot is None:
            self.refuse.emit("Choisissez d'abord le lot à poser dans la barre du haut.")
            return None
        if verifier_reste:
            reste = self.reste_du_lot()
            if reste is not None and reste <= 0:
                if getattr(self.lot, "est_materiel_bord", False):
                    n = max(1, int(getattr(self.lot, "quantite", 1) or 1))
                    self.refuse.emit(
                        f"« {self.lot.nom} » est déjà arrimé : le navire n'en a "
                        + ("qu'un" if n == 1 else f"que {n}")
                        + ". Déplacez-le, ou retirez-le du plan avant de le "
                        "reposer ailleurs.")
                else:
                    self.refuse.emit(
                        f"« {self.lot.nom} » : tout est posé ({self.lot.quantite} sur "
                        f"{self.lot.quantite}). Augmentez la quantité au manifeste "
                        "pour en poser davantage.")
                # un lot servi ne reste pas en main : on repose la pièce ici
                # aussi, pour les chemins qui n'ont pas posé le dernier colis
                # (quantité du manifeste réduite après coup, épontille mise en
                # place qui a rendu du fret puis repris, zone…)
                self.lacher_le_lot()
                return None
        return self.lot.to_placement()

    def viser(self, x, y, rot=None, verifier_reste=True):
        """Où tomberait le colis en main, sans rien poser.

        Retourne `(colis, cale, refus, pile)` : `pile` non nul = il irait
        s'empiler sur cette charge-là plutôt que se poser à côté. C'est LA
        fonction que partagent le fantôme et la pose : ce qu'on montre est
        exactement ce qui sera fait, jamais une approximation."""
        pl = self._nouveau_colis(verifier_reste=verifier_reste)
        if pl is None:
            return None, None, None, None
        if rot is not None:
            pl.rot = 90 if rot % 180 else 0
        # viser UNE pile du même lot y ajoute un exemplaire : c'est le geste
        # pour empiler (stack), tant que la marchandise le permet (D-22)
        pile = self._at(x, y)
        if pile is not None and meme_pile(pile, pl):
            return pl, self.hold_of(pile), gerbage_refuse(pile), pile
        # la souris est sortie de la cale : le colis en main y reste accroché,
        # ramené contre la muraille — c'est ainsi qu'on accoste un bord
        dehors = self.hold_at(x, y) is None
        cale = self.cale_de_travail(x, y)
        if dehors and cale is not None:
            x, y = self._ramener_dans(cale, x, y, pl.encombrement)
        dx, dy = pl.emprise
        nx, ny = x - dx / 2, y - dy / 2
        if self.aimantation:
            nx = round(nx / PAS_SNAP) * PAS_SNAP
            ny = round(ny / PAS_SNAP) * PAS_SNAP
            nx, ny = self._aimanter(pl, nx, ny, cale)
        pl.x, pl.y = nx, ny
        if dehors and cale is not None:
            self._rapprocher(pl, cale)
        cap = self.hold_at(*pl.centre) or (cale if dehors else None)
        return pl, cap, self.pose_refusee(pl, cap), None

    def poser_un(self, x, y, rot=None):
        """Pose un colis du lot courant, centré sur le point visé."""
        if rot is None:
            rot = self.rot_main
        pl, cap, refus, pile = self.viser(x, y, rot)
        if pl is None:
            return None
        nom = pl.nom
        if pile is not None:
            if refus is not None:
                self.refuse.emit(f"{nom} : {refus} — pas posé.")
                return None
            pile.niveaux = max(1, pile.niveaux) + 1
            self.set_selection([pile])
            self.changed.emit()
            self.update()
            self.lacher_si_servi()
            return pile
        if refus is not None:
            self.refuse.emit(f"{nom} : {refus} — pas posé.")
            return None
        self.placements(cap).append(pl)
        self.set_selection([pl])
        self.changed.emit()
        self.update()
        self.lacher_si_servi()
        return pl

    def lot_servi(self):
        """Le lot en main est-il servi — plus rien à poser ?

        `None` de `reste_du_lot` veut dire « pose libre » (charge du bord hors
        manifeste) : rien n'est jamais servi dans ce cas."""
        if self.lot is None:
            return False
        reste = self.reste_du_lot()
        return reste is not None and reste <= 0

    def lacher_si_servi(self):
        """Le dernier colis du lot vient d'être posé : on SORT du mode de pose.

        Sans cela, on restait la main pleine d'un lot qui n'a plus rien à
        donner : plus de fantôme, un clic qui ne pose rien et refuse en
        disant « tout est posé », et l'impression de ne plus pouvoir quitter
        la pose. Le lot servi se repose donc tout seul, et on le dit — le
        clic redevient un choix, et l'épontille d'à côté se rebascule."""
        if not self.lot_servi():
            return False
        nom = getattr(self.lot, "nom", "")
        materiel = getattr(self.lot, "est_materiel_bord", False)
        n = max(1, int(getattr(self.lot, "quantite", 1) or 1))
        self.lacher_le_lot()
        self.outil_fini.emit(
            (f"« {nom} » est arrimé : le navire n'en a "
             + ("qu'un" if n == 1 else f"que {n}")
             + " — plus rien en main, le clic choisit de nouveau."
             if materiel else
             f"« {nom} » : tout est posé — plus rien en main, le clic choisit "
             "de nouveau. Reprenez un lot dans la barre pour poser."))
        return True

    def tourner_la_main(self):
        """Fait pivoter la pièce en main d'un quart de tour. Le fantôme suit ;
        rien n'est posé."""
        if self.lot is not None and not getattr(self.lot, "rotation_permise", True):
            self.refuse.emit(f"« {self.lot.nom} » ne se pose pas tourné.")
            return False
        self.rot_main = 0 if self.rot_main else 90
        self.update()
        return True

    # ------------------------------------------------------------- outil Zone
    # Le cadre est un SOUHAIT, pas une frontière du navire. Ce qui refuse une
    # pose reste ce qui la refuse partout ailleurs : le contour de la cale,
    # les obstacles, les épontilles en place, les voisins déjà posés, la
    # charge admissible et la hauteur libre (D-27). Le cadre n'ajoute qu'une
    # chose — « pas ailleurs qu'ici » — et il l'ajoute sous la forme que le
    # moteur sait déjà refuser : quatre obstacles autour de lui.

    def reglages_de_zone(self):
        """Les réglages avec lesquels la zone calepine.

        Ceux du DERNIER passage du répartiteur, le jeu de la molette en plus :
        exactement ce que prend le plan de cale (`reglages_du_remplissage`).
        Un même moteur ne doit pas poser de trois façons — la zone, le plan de
        cale et le répartiteur rendent le même plan avec les mêmes réglages,
        sinon le bord compare deux plans sans pouvoir dire pourquoi ils
        diffèrent."""
        return reglages_du_remplissage(self.win, self.jeu_m)

    def _cales_du_cadre(self, zone):
        """Les cales que le cadre touche, de l'arrière vers l'avant.

        Une zone peut chevaucher plusieurs cales : chacune se remplit alors
        pour sa part, et rien ne se pose entre les deux."""
        x0, y0, x1, y1 = zone
        touchees = []
        for cap in self.holds():
            bx0, by0, bx1, by1 = bornes_polygone(cap.points)
            if bx0 < x1 and x0 < bx1 and by0 < y1 and y0 < by1:
                touchees.append((bx0, cap))
        touchees.sort(key=lambda t: t[0])
        return [cap for _x, cap in touchees]

    @staticmethod
    def _majorant_du_cadre(cap, zone, emprise):
        """Combien de colis peuvent AU PLUS tenir dans le cadre, ici.

        C'est la borne du calepinage, et elle est franche : demander au
        calepineur de loger les deux cents colis qui restent au manifeste dans
        un cadre qui en tient douze, c'est lui faire composer la cale entière
        pour rien. La surface du cadre divisée par l'emprise d'un colis est un
        majorant exact du nombre de colis d'un seul niveau qu'on peut y loger
        — on ne perd donc aucune pose, on économise seulement du travail."""
        dx, dy = emprise
        if dx <= 0 or dy <= 0:
            return 0
        bx0, by0, bx1, by1 = bornes_polygone(cap.points)
        x0, y0 = max(zone[0], bx0), max(zone[1], by0)
        x1, y1 = min(zone[2], bx1), min(zone[3], by1)
        if x1 <= x0 or y1 <= y0:
            return 0
        return int((x1 - x0) * (y1 - y0) / (dx * dy)) + 1

    def _calepiner_la_cale(self, cap, zone, budget):
        """Le meilleur calepinage du lot courant dans le cadre, pour CETTE
        cale : `[(x, y, rot)]`. Rien n'est posé.

        C'est le calepineur du moteur (`stowage.resoudre`), celui du
        répartiteur et du plan de cale : il compose une quinzaine de
        calepinages complets — travées dans un sens ou dans l'autre, accostées
        d'un bord ou de l'autre, blocs, au plus près du bord — et garde le
        meilleur. Le balayage naïf, lui, quadrillait depuis le coin arrière
        bâbord du cadre et laissait vide la moitié d'un coin de muraille
        oblique.

        Le CADRE lui est dit en obstacles (`_obstacles_du_cadre`), les colis
        DÉJÀ POSÉS en épingles — comme le fait le plan de cale : la zone se
        pose autour d'eux, elle ne les déplace ni ne les empile."""
        modele = self.lot.to_placement()
        if min(modele.emprise) <= 0:
            return []
        n = self._majorant_du_cadre(cap, zone, modele.encombrement)
        if budget is not None:
            n = min(n, budget)
        if n <= 0:
            return []
        hold = _hold_de(cap, self.epontilles_en_place())
        hold.obstacles = list(hold.obstacles) + _obstacles_du_cadre(hold.bbox, zone)
        # Un lot À PART pour le calepineur : même emprise, même poids, même
        # droit de tourner que ce qu'on a en main, mais un `lot_id` neuf et un
        # gerbage de 1. La zone est un geste de PLANCHER — on garnit une
        # surface, on n'empile pas à l'aveugle ; empiler reste le clic sur une
        # pile, où l'on voit ce qu'on fait. Sans cela un cadre de trois mètres
        # viderait le lot en piles de trois sans que personne l'ait demandé.
        ligne = ManifestLine(
            type_code=getattr(modele, "type_code", ""), nom=modele.nom,
            quantite=int(n), longueur_m=modele.longueur_m,
            largeur_m=modele.largeur_m, hauteur_m=modele.hauteur_m,
            poids_t=modele.poids_t, gerbable_max=1,
            rotation_permise=getattr(modele, "rotation_permise", True),
            # le débord suit le lot jusque dans la zone : le calepineur doit
            # faire tenir l'encombrement, pas la palette nue (D-39)
            debord_m=getattr(modele, "debord_m", 0.0),
            categorie=modele.categorie)
        deja = list(self.placements(cap))
        rap = resoudre([hold], [ligne], self.reglages_de_zone(),
                       epingles={cap.code: deja}, navire=None)
        # `resoudre` rend les épinglées d'abord, dans l'ordre où on les a
        # données : ce qui suit est ce que le calepineur a ajouté
        return [(p.x, p.y, p.rot)
                for p in rap.places.get(cap.code, [])[len(deja):]]

    def _rangs_simples(self, zone, budget):
        """L'ancien remplissage : un quadrillage au pas de l'emprise, depuis le
        coin arrière tribord du cadre.

        On le garde pour deux raisons : c'est le point de comparaison qu'on
        annonce au bord (« 6 de plus qu'en rangs simples »), et c'est un
        calepinage de plus — s'il fait mieux que le calepineur sur un cadre
        donné, c'est lui qu'on pose, de sorte que la zone ne pose JAMAIS moins
        qu'avant. Deux rangs droits ne coûtent presque rien à essayer.

        Les colis gardent le SENS DU MANIFESTE : plus aucun réglage n'impose le
        grand côté — la « disposition » du répartiteur dit dans quel sens la
        cale se remplit, pas dans quel sens sont posés les colis.
        Elle décide en revanche de la PROGRESSION, et donc de l'endroit où
        tombe un lot qui ne remplit pas le cadre : rangée par rangée de tribord
        à bâbord (transversale, comme toujours), ou colonne par colonne
        d'arrière en avant (longitudinale).

        Ils gardent le jeu de la molette, même à zéro : c'est ce que faisait
        l'outil Zone, et un cadre juste à la bonne mesure y logeait une rangée
        de plus que le calepineur, qui ne descend pas sous la marge de 2 cm du
        moteur."""
        modele = self.lot.to_placement()
        # Les rangs se comptent en PLACE OCCUPÉE : la palette, plus le débord
        # du lot (D-39), plus le jeu d'arrimage de chaque côté (D-64). Le pas
        # d'un rang est donc exactement cette place — deux voisins se trouvent
        # ainsi séparés de deux jeux, et le premier rang décollé d'un jeu du
        # bord du cadre.
        jeu = max(self.jeu_m, 0.0)
        d = max(0.0, modele.debord_m) + jeu
        dx, dy = modele.encombrement
        dx, dy = dx + 2 * jeu, dy + 2 * jeu
        if dx <= 0 or dy <= 0:
            return []
        x0, y0, x1, y1 = zone
        en_long = self.reglages_de_zone().disposition == LONGITUDINALE
        out = []
        # `lent` est la rangée qu'on finit avant de passer à la suivante :
        # l'ordonnée en transversale (on va de tribord à bâbord), l'abscisse en
        # longitudinale (on va de l'arrière vers l'avant).
        lent, pas_lent, borne_lent = ((x0, dx, x1) if en_long
                                      else (y0, dy, y1))
        taille_lent = dx if en_long else dy
        while (lent + taille_lent <= borne_lent + 1e-9
               and (budget is None or len(out) < budget)):
            rapide, pas_rapide, borne_rapide = ((y0, dy, y1) if en_long
                                                else (x0, dx, x1))
            taille_rapide = dy if en_long else dx
            while (rapide + taille_rapide <= borne_rapide + 1e-9
                   and (budget is None or len(out) < budget)):
                x, y = (lent, rapide) if en_long else (rapide, lent)
                modele.x, modele.y = round(x + d, 3), round(y + d, 3)
                cap = self.hold_at(*modele.centre)
                if cap is not None and self.pose_refusee(modele, cap) is None:
                    out.append((modele.x, modele.y, modele.rot))
                rapide += pas_rapide
            lent += pas_lent
        return out

    def plan_de_zone(self, zone, budget=None):
        """Ce que « Zone » posera dans ce cadre : `(plan, n_rangs_simples)`.

        `plan` est `[(x, y, rot)]` — le meilleur du calepinage et des rangs
        simples ; `n_rangs_simples` est ce qu'aurait donné l'ancien balayage,
        pour pouvoir dire au bord EN QUOI c'est mieux. Rien n'est posé : la
        pose repasse par la porte de tous les autres chemins (D-27).

        Le temps, mesuré sur une cale d'entrepont : deux dixièmes de seconde
        par cale — c'est la composition des quinze calepinages, qui ne dépend
        pas de la taille du cadre — et le nombre de colis demandés est borné
        par ce qui peut tenir dans le cadre (`_majorant_du_cadre`). Le prix se
        paie donc PAR CALE traversée : un cadre tiré sur un pont entier (trois
        cales, quatre cents colis posés) coûte trois quarts de seconde, un
        cadre ordinaire un cinquième. C'est la borne franche du geste ; rien
        n'est rogné pour aller plus vite."""
        if self.lot is None:
            return [], 0
        rangs = self._rangs_simples(zone, budget)
        calepine, reste = [], budget
        for cap in self._cales_du_cadre(zone):
            if reste is not None and reste <= 0:
                break
            pose = self._calepiner_la_cale(cap, zone, reste)
            calepine.extend(pose)
            if reste is not None:
                reste -= len(pose)
        return (calepine if len(calepine) >= len(rangs) else rangs), len(rangs)

    def _rects_du_plan(self, plan):
        """Les emprises d'un plan de zone, pour le dessin de l'aperçu."""
        if self.lot is None:
            return []
        modele = self.lot.to_placement()
        out = []
        for x, y, rot in plan:
            modele.rot, modele.x, modele.y = rot, x, y
            out.append(modele.rect)
        return out

    def _budget_apercu(self, limite=400):
        """Ce que l'aperçu a le droit de montrer : le reste à embarquer, borné.

        La borne n'est pas une règle d'arrimage, c'est un plafond de dessin :
        un cadre tiré sur tout un pont ne doit pas faire calculer mille
        emprises à chaque image."""
        reste = self.reste_du_lot()
        return limite if reste is None else min(reste, limite)

    def apercu_zone(self, zone, limite=400):
        """Les emprises que « Zone » poserait dans ce cadre, sans rien poser.

        Sert à montrer le résultat pendant qu'on tire le cadre : on ne demande
        pas à l'officier de deviner ce que le logiciel va faire.

        En DEUX TEMPS, parce qu'un cadre se tire à la souris et que le
        calepinage coûte deux dixièmes de seconde : tant que le cadre bouge on
        montre les rangs simples, qui se calculent en un clin d'œil ; dès
        qu'il s'arrête, le calepinage prend leur place et l'aperçu redevient
        exactement ce qui sera posé. Le plan calculé est gardé : le
        remplissage qui suit le relâchement ne le recalcule pas."""
        if self.lot is None:
            return []
        budget = self._budget_apercu(limite)
        cle = self._cle_apercu(zone, budget)
        if self._apercu is not None and self._apercu[0] == cle:
            return self._rects_du_plan(self._apercu[1])
        self._minuterie_apercu.start(DELAI_APERCU_MS)
        return self._rects_du_plan(self._rangs_simples(zone, budget))

    def _cle_apercu(self, zone, budget):
        """De quoi dépend un aperçu : le cadre, le lot, le jeu, le budget.

        Le reste — les colis déjà posés, les épontilles, les réglages du
        répartiteur — passe par `invalider_problemes`, qui oublie l'aperçu à
        chaque mutation du plan : un aperçu périmé serait pire que lent."""
        return (tuple(round(v, 4) for v in zone),
                id(self.lot), round(self.jeu_m, 4), budget)

    def calepiner_l_apercu(self):
        """Le cadre s'est arrêté : on calepine pour de bon et on redessine.

        Appelée par la minuterie de l'aperçu — et directement par les tests,
        qui veulent l'aperçu définitif sans attendre."""
        cadre = self._cadre
        if cadre is None or self.outil != OUTIL_ZONE or self.lot is None:
            return
        x0, y0, x1, y1 = cadre
        zone = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        budget = self._budget_apercu()
        cle = self._cle_apercu(zone, budget)
        if self._apercu is not None and self._apercu[0] == cle:
            return
        plan, _rangs = self.plan_de_zone(zone, budget)
        self._apercu = (cle, plan)
        self.update()

    def remplir_zone(self, zone):
        """Pose au mieux dans le cadre — le calepineur du moteur, pas un
        quadrillage.

        Le cadre reste un souhait, pas une frontière du navire : ce qui compte
        est le contour de la cale, les obstacles, les voisins et la charge. Il
        est dit au calepineur sous forme d'obstacles, les colis déjà posés
        sous forme d'épingles, et les réglages sont ceux du dernier passage du
        répartiteur — la zone pose donc comme le plan de cale et comme le
        répartiteur, pas d'une troisième façon.

        On ne dépasse jamais ce qu'il reste à embarquer sur la ligne (D-19),
        et le lot servi d'un coup fait sortir du mode de pose comme après le
        dernier clic."""
        modele = self._nouveau_colis()
        if modele is None:
            return 0
        budget = self.reste_du_lot()
        if budget == 0:
            return 0
        cle = self._cle_apercu(zone, budget if budget is not None else 400)
        if self._apercu is not None and self._apercu[0] == cle:
            plan, rangs = self._apercu[1], len(self._rangs_simples(zone, budget))
        else:
            plan, rangs = self.plan_de_zone(zone, budget)
        poses = []
        # UN `Hold` par cale, et non un par colis : le reconstruire à chaque
        # pose est le gros du coût d'une grande zone, pour un résultat
        # rigoureusement identique — les obstacles d'une cale ne changent pas
        # d'un colis à l'autre. Le cadre, lui, n'est PAS dedans : il ne refuse
        # rien, il n'a servi qu'à dire au calepineur où poser.
        holds = {}
        epontilles = self.epontilles_en_place()
        for x, y, rot in plan:
            if budget is not None and len(poses) >= budget:
                break
            pl = self._nouveau_colis(verifier_reste=False)
            if pl is None:
                break
            pl.rot = 90 if rot % 180 else 0
            pl.x, pl.y = round(x, 6), round(y, 6)
            cap = self.hold_at(*pl.centre)
            if cap is not None and cap.code not in holds:
                holds[cap.code] = _hold_de(cap, epontilles)
            # MÊME PORTE que tous les autres chemins de pose : le calepineur
            # propose, `pose_refusee` dispose (D-27). Un plan composé sur une
            # grille de 2,5 cm n'a pas à être cru sur parole.
            if cap is not None and self.pose_refusee(pl, cap,
                                                     holds[cap.code]) is None:
                self.placements(cap).append(pl)
                poses.append(pl)
        if poses:
            self.set_selection(poses)
            self.changed.emit()
            self.update()
            self.outil_fini.emit(self._dire_la_zone(len(poses), rangs))
            # la zone a pu servir le lot d'un coup : on sort alors du mode de
            # pose comme après le dernier clic
            self.lacher_si_servi()
        else:
            self.outil_fini.emit("Aucun colis ne tient dans cette zone.")
        return len(poses)

    def _dire_la_zone(self, n, rangs):
        """Ce que la barre dit après un remplissage de zone : combien, en quoi
        c'est mieux quand ça l'est, et avec quoi ça a calepiné.

        « 18 colis posés dans la zone (6 de plus qu'en rangs simples) ·
        disposition : transversale · jeu 0,05 m ». Le gain se dit parce que
        c'est lui qui donne confiance : sans le chiffre de l'ancien balayage,
        « 18 colis » ne prouve rien à qui vient d'en compter douze à la main."""
        reg = self.reglages_de_zone()
        bouts = [f"disposition : "
                 f"{DISPOSITION_DITE.get(reg.disposition, reg.disposition)}",
                 "jeu {:.2f} m".format(reg.jeu_m or 0.0).replace(".", ",")]
        gain = f" ({n - rangs} de plus qu'en rangs simples)" if n > rangs else ""
        return f"{n} colis posés dans la zone{gain} · " + " · ".join(bouts)

    def reste_du_lot(self):
        """Ce qu'il reste à poser de ce qu'on a en main.

        Une ligne de manifeste : ce qu'il reste à embarquer (D-19). Un
        matériel du bord : ses exemplaires pas encore arrimés — le navire en a
        autant que sa fiche le dit, pas un de plus. None : pose libre (lot
        hors manifeste)."""
        cond = self.win.condition
        if getattr(self.lot, "est_materiel_bord", False):
            # Un engin du bord est un objet COMPTÉ : le navire a deux
            # chariots, pas trois. On en pose autant que l'inventaire en
            # déclare, un par clic, et pas au-delà (D-37).
            n = max(1, int(getattr(self.lot, "quantite", 1) or 1))
            return max(0, n - len(cond.poses_du_materiel(self.lot.id)))
        if self.lot is None or getattr(self.lot, "hors_manifeste", False):
            return None          # charge du bord : rien à embarquer, pas de reste
        if self.lot not in cond.manifeste:
            return None
        i = cond.manifeste.index(self.lot)
        return max(0, self.lot.quantite - cond.places_par_ligne()[i])

    def _lots_du_manifeste(self):
        """Les lots qui sont de la marchandise : ce qui en vient y retourne.
        Une charge du bord (D-18) n'a pas de « reste à embarquer »."""
        return {m.lot_id for m in self.win.condition.manifeste
                if not getattr(m, "hors_manifeste", False)}

    def dire_retrait(self, retires):
        """Ce que la barre d'état doit dire après un retrait.

        Retirer un colis n'est pas le détruire : il retourne au « reste à
        embarquer » de sa ligne de manifeste (`places_par_ligne`). Il faut
        que ça se lise, sinon on croit avoir perdu de la marchandise."""
        lots = self._lots_du_manifeste()
        rendus = sum(n for lot, n in retires if lot in lots)
        total = sum(n for _lot, n in retires)
        if not total:
            return ""
        if rendus == total:
            return f"{rendus} colis remis au manifeste (reste à embarquer)."
        if rendus:
            return (f"{total} colis retirés — {rendus} remis au manifeste, "
                    f"{total - rendus} du bord.")
        # rien du manifeste : c'est du matériel du bord (ou un colis d'avant
        # les lots). Un engin déposé reste à bord et à l'inventaire.
        return (f"{total} matériel(s) du bord déposé(s) : toujours à bord, "
                "plus arrimés.")

    def retirer_selection(self):
        """Retire toute la sélection d'un bloc — les colis retournent au
        manifeste. C'est l'action de groupe demandée sur un cadre."""
        n, retires = 0, []
        for pl in list(self.selection):
            cap = self.hold_of(pl)
            if cap is not None:
                self.placements(cap).remove(pl)
                retires.append((getattr(pl, "lot_id", ""), max(1, pl.niveaux)))
                n += 1
        self.set_selection([])
        if n:
            self.outil_fini.emit(self.dire_retrait(retires))
            self.changed.emit()
            self.update()
        return n

    def tourner_pose(self, pl, dire=True):
        """Tourne d'un quart de tour un colis DÉJÀ POSÉ, autour de son centre.

        C'est la rotation « en place » que le bord réclame : le colis pivote
        là où il est (`pivot_en_place`), et la nouvelle pose est revérifiée
        par la MÊME porte que toutes les autres — `appliquer` (D-27) : contour
        de la cale, zones interdites, épontilles en place (D-30), voisines.
        Refusée, le colis reste exactement comme il était et la barre dit
        pourquoi ; acceptée, le point est modifié et le bilan se recalcule,
        comme après une pose (`changed`).

        `dire` : mettre à False quand on tourne toute une sélection — c'est
        alors l'appelant qui fait le compte, une phrase pour tout le bloc.
        Rend **la raison du refus, ou None** si le colis a tourné."""
        if pl is None:
            return "aucun colis visé"
        if self._fige(pl):
            refus = "épinglé — dépinglez-le (P) avant de le tourner"
        elif not getattr(pl, "rotation_permise", True):
            refus = "rotation interdite pour ce type"
        else:
            x, y, rot = pivot_en_place(pl)
            refus = self.appliquer(pl, x=x, y=y, rot=rot)
            if refus is None:
                if dire:
                    self.changed.emit()
                    self.update()
                return None
        if dire:
            self.refuse.emit(f"« {pl.nom} » n'a pas pu tourner : {refus} — il "
                             "reste comme il est.")
        return refus

    def tourner_survol_ou_selection(self):
        """Le geste « tourner » sans lot en main : le colis SOUS LE POINTEUR
        d'abord, la sélection à défaut.

        Même ordre de priorité que Suppr — viser à la souris et appuyer est
        plus rapide que sélectionner puis agir, et c'est ce que le bord fait
        quand il retire un colis."""
        if self.survol is not None:
            return 1 if self.tourner_pose(self.survol) is None else 0
        return self.tourner_selection()

    def tourner_selection(self):
        """Toute la sélection d'un quart de tour, chacun autour de SON centre.

        Une phrase pour le bloc, pas une par colis : si aucun n'a tourné, on
        dit combien et la première raison — le plus souvent la voisine, qu'il
        faut dégager d'abord."""
        n, motifs = 0, []
        for pl in list(self.selection):
            motif = self.tourner_pose(pl, dire=False)
            if motif is None:
                n += 1
            else:
                motifs.append(motif)
        if n:
            self.changed.emit()
            self.update()
        elif motifs:
            self.refuse.emit(
                f"{len(motifs)} colis n'ont pas pu tourner sur place : "
                f"{motifs[0]} — ils restent comme ils sont.")
        return n

    def _aimanter(self, pl, nx, ny, cap=None):
        """Colle la charge en cours de déplacement à ses voisines et aux parois
        de la cale survolée. `Alt` court-circuite l'appel.

        `cap` force la cale — c'est le cas du colis en main quand la souris
        est sortie : il reste aimanté à la cale qu'on longeait."""
        if not self.aimantation:
            return nx, ny
        dx, dy = pl.emprise
        if cap is None:
            cap = self.hold_at(nx + dx / 2, ny + dy / 2)
        if cap is None:
            return nx, ny
        # On aimante les PLACES OCCUPÉES : c'est ce qui se touche vraiment
        # quand les sacs dépassent de la palette (débord du lot, D-39) et
        # quand on s'est réservé un jeu d'arrimage (D-64). Le coin rendu est
        # celui de la place occupée, ramené au coin de la palette avant de
        # poser. `aimanter` reçoit donc un jeu NUL : il est déjà dans les
        # rectangles, le compter deux fois écarterait les colis du double.
        jeu = max(0.0, float(self.jeu_m or 0.0))
        d = max(0.0, pl.debord_m) + jeu
        dx, dy = pl.encombrement
        dx, dy = dx + 2 * jeu, dy + 2 * jeu
        voisins = [rect_occupe(q, jeu) for q in self.placements(cap)
                   if q is not pl]
        # `_hold_de` fait déjà le tri que fait le contrôle de pose : seules les
        # zones SANS hauteur libre et les épontilles en place de CE point sont
        # des murs (D-30) ; une zone à hauteur réduite reste un calque (D-21)
        # et n'empêche pas de s'aimanter dessus.
        interdits = _hold_de(cap, self.epontilles_en_place()).zones_interdites
        ax, ay = aimanter((nx - d, ny - d, nx - d + dx, ny - d + dy), voisins,
                          bornes_polygone(cap.points), 0.0,
                          contour=cap.points, interdits=interdits)
        return ax + d, ay + d

    def _aimanter_groupe(self, groupe, vx, vy):
        """Le vecteur (vx, vy) d'un GROUPE de colis, corrigé pour que le bloc
        s'accoste à ses voisins et aux parois (D-88).

        Le bloc, c'est le rectangle qui englobe les places occupées du groupe
        une fois déplacé ; ses voisins, les colis de la cale qui n'en sont
        pas. Si le groupe est à cheval sur plusieurs cales, ou si aucun repère
        ne tient, le vecteur reste tel quel : la grille seule, comme avant."""
        if not self.aimantation or not groupe:
            return vx, vy
        jeu = max(0.0, float(self.jeu_m or 0.0))
        rects = [rect_occupe(q, jeu) for q in groupe]
        x0 = min(r[0] for r in rects) + vx
        y0 = min(r[1] for r in rects) + vy
        x1 = max(r[2] for r in rects) + vx
        y1 = max(r[3] for r in rects) + vy
        cap = self.hold_at((x0 + x1) / 2, (y0 + y1) / 2)
        if cap is None:
            return vx, vy
        dans_la_cale = self.placements(cap)
        membres = {id(q) for q in groupe}
        if any(id(q) not in {id(p) for p in dans_la_cale} for q in groupe):
            return vx, vy                   # à cheval sur deux cales
        voisins = [rect_occupe(q, jeu) for q in dans_la_cale if id(q) not in membres]
        interdits = _hold_de(cap, self.epontilles_en_place()).zones_interdites
        ax, ay = aimanter((x0, y0, x1, y1), voisins, bornes_polygone(cap.points),
                          0.0, contour=cap.points, interdits=interdits)
        return vx + (ax - x0), vy + (ay - y0)

    def mouseDoubleClickEvent(self, event):
        """DOUBLE-CLIC DANS LE VIDE D'UNE CALE : on ZOOME dessus, ici même.

        « Quand on double-clique sur une cale, ça devrait zoomer sur la cale.
        Je n'aime pas du tout la fenêtre qui s'ouvre, je ne veux pas de ça.
        Comme avant : un double-clic zoome dans la fenêtre principale sur la
        cale, un autre double-clic ramène au pont complet. » (D-65) Le plan de
        cale — l'éditeur d'UNE cale, avec son « Remplir » — reste accessible,
        mais par le menu du clic droit, jamais par surprise.

        Deux réserves, pour que le geste ne surprenne jamais : rien sous le
        pointeur (un double-clic sur un colis appartient au colis), et rien
        en main — avec un lot en main, le double-clic est fait de deux poses.

        Zoomé, le double-clic ramène au pont entier D'OÙ QU'IL VIENNE — dans
        la cale zoomée, ou dans la marge : c'est l'aller-retour promis."""
        geom = self._geom()
        if geom is None:
            return
        x, y = self.to_ship(event.position().x(), event.position().y(), geom)
        if self._at(x, y) is not None or self.lot is not None:
            return
        if self.zoom_hold is not None:
            self.zoom_annule.emit()
            return
        cap = self.hold_at(x, y)
        if cap is not None:
            self.cale_zoomee.emit(cap)

    def retirer_un(self, pl):
        """Retire UN exemplaire : un colis, ou un niveau si c'est une pile.

        Un seul, même quand il fait partie d'une fournée posée par zone (elle
        reste sélectionnée en bloc) — sans quoi ôter la palette de trop
        obligeait à tout défaire."""
        if pl is None:
            return False
        cap = self.hold_of(pl)
        if cap is None:
            return False
        if pl.niveaux > 1:
            pl.niveaux -= 1            # une pile se défait niveau par niveau
        else:
            self.placements(cap).remove(pl)
            if pl in self.selection:
                self.set_selection([q for q in self.selection if q is not pl])
            if pl is self.survol:
                self.survol = None
                self.survole.emit(None)
        self.outil_fini.emit(
            self.dire_retrait([(getattr(pl, "lot_id", ""), 1)]))
        self.changed.emit()
        self.update()
        return True

    def retirer_survole(self):
        """Retire le colis sous le pointeur (touche Suppr)."""
        return self.retirer_un(self.survol)

    def retirer_sous(self, x, y):
        """Retire le colis posé sous ce point — c'est le clic droit.

        Rien ailleurs : un clic droit dans le vide ne doit pas se traduire par
        une marchandise qui disparaît sans qu'on ait visé quoi que ce soit."""
        return self.retirer_un(self._at(x, y))

    def lacher_le_lot(self):
        """Repose la pièce en main : plus de fantôme, le clic redevient un
        choix. C'est ce que fait Échap — « quitter le type de colis que l'on
        veut poser », mot pour mot."""
        if self.lot is None:
            return False
        self.lot = None
        self.fantome = None
        self.lot_lache.emit()
        self.update()
        return True

    def rafraichir_fantome(self):
        """Recalcule le colis en main sous le pointeur — après une rotation,
        il faut le revoir tourné sans avoir à bouger la souris."""
        geom = self._geom()
        pos = self.mapFromGlobal(QCursor.pos())
        if geom is None or not self.rect().contains(pos):
            self.update()
            return
        x, y = self.to_ship(pos.x(), pos.y(), geom)
        self._survol(x, y, geom)

    def keyPressEvent(self, event):
        """LE CLAVIER DE LA POSE, tel que le bord l'a dicté :

        - **A** tourne le FANTÔME d'un quart de tour, et rien d'autre. Il ne
          pose plus : on tournait la charge et elle se posait aussitôt, sans
          qu'on ait vu où elle allait tomber.
        - **Suppr** retire le colis survolé ; sans rien sous le pointeur, la
          sélection entière. Les colis retournent au manifeste.
        - **Échap** ramène à l'outil **Sélectionner**, toujours : elle lâche
          la pièce en main, annule le cadre, le glissement ou la mesure en
          cours, et repose l'outil. Frappée une seconde fois, quand il n'y a
          plus rien à annuler, elle vide la sélection. Le panneau tranche
          (`CargoPanel.echap`), parce que l'outil est à lui.
        - **R** (et Espace) : tourner — le colis survolé, sinon la sélection,
          sinon le fantôme. Un colis POSÉ tourne autour de son centre, sur
          place (`tourner_pose`). **P** épingle la sélection.

        Maj force l'action sur la sélection plutôt que sur le survol."""
        k = event.key()
        maj = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)

        if k == Qt.Key.Key_Escape:
            # le plan ne sait pas remettre l'outil à Sélectionner : les
            # boutons sont au panneau. UNE seule logique, chez lui.
            self.echap_frappee.emit()
            self.update()
            return
        if k == Qt.Key.Key_A and self.lot is not None:
            # tourner le fantôme, JAMAIS poser
            if self.tourner_la_main():
                self.rafraichir_fantome()
            return
        # le colis SURVOLÉ répond directement, même s'il est dans la sélection :
        # viser à la souris et appuyer est plus rapide que sélectionner puis
        # agir, et cela permet d'ôter UN colis d'une fournée posée par zone.
        # `Z` reste accepté en second : il ne pose rien, il retire, et c'est le
        # geste que l'équipage a dans les doigts.
        if k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace, Qt.Key.Key_Z):
            # Ctrl+Z n'est PAS « Z » : c'est Annuler (D-61), et il appartient
            # à la fenêtre. Sans ce garde-fou, un Ctrl+Z frappé au-dessus d'un
            # colis le retirerait au lieu de défaire le dernier geste.
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                event.ignore()
                return
            if self.survol is not None and not maj:
                self.retirer_survole()
            elif self.selection:
                self.retirer_selection()
            return
        if k in (Qt.Key.Key_R, Qt.Key.Key_Space):
            if self.survol is not None and not maj:
                # le colis SOUS LE POINTEUR tourne autour de son centre, et
                # la pose est revérifiée : c'est le geste réclamé par le bord
                self.tourner_pose(self.survol)
                return
            if self.selection:
                self.tourner_selection()
                return
            if self.lot is not None and self.tourner_la_main():
                self.rafraichir_fantome()
            return
        if k == Qt.Key.Key_P and self.selection:
            # on ne désépingle pas un matériel du bord : c'est ce qui dit au
            # solveur de ne pas y toucher, et ce n'est pas une préférence
            engins = [pl for pl in self.selection if pl.est_materiel_bord]
            for pl in self.selection:
                if not pl.est_materiel_bord:
                    pl.epingle = not pl.epingle
            if engins:
                self.refuse.emit(
                    f"{len(engins)} matériel(s) du bord : toujours épinglé(s) "
                    "— le solveur ne les déplace jamais. Vous, si : "
                    "glissez-les sur le plan.")
            self.changed.emit()
            self.update()
            return
        return super().keyPressEvent(event)


class CargoPanel(QWidget):
    """Plan de pont manipulable + tableau synchronisé."""

    changed = Signal()

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self._rows = []            # index de ligne -> (placement, capacité)
        self._loading = False
        # LA VUE D'ABORD : la barre du haut porte le menu des calques, qui
        # pilote l'objet `Calques` de la vue. On construit donc le plan avant
        # sa barre, et on le range dans le séparateur plus bas.
        self.view = DeckStowView(win)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- LA BARRE, EN GROUPES -----------------------------------------
        #
        # « Le bandeau pourrait être réorganisé pour garder une certaine
        # logique. » Il n'en avait aucune : les boutons s'étaient ajoutés les
        # uns après les autres, au fil des retours, et l'œil ne trouvait plus
        # rien. On les range donc par QUESTION POSÉE, chaque groupe sous sa
        # petite étiquette grise et derrière son trait :
        #
        #   rangée 1 — PONT (où je regarde) · OUTIL (ce que le clic veut dire)
        #              · LOT (ce que je tiens) · AFFICHAGE (ce que je vois)
        #   rangée 2 — CHARGEMENT (la marchandise) · NAVIRE (ce qui appartient
        #              au bord) · POSE (comment ça se pose) … et, à droite,
        #              l'ÉTAT : ce qui est posé, la dernière mesure, le verdict.
        #
        # L'ordre est celui du travail : on choisit un pont, un outil, un lot,
        # puis on pose.
        self.groupes_barre = {}

        bar = QFrame()
        bar.setObjectName("cargoBar")
        bar.setStyleSheet(
            f"QFrame#cargoBar {{ background: {theme.SURFACE}; "
            f"border-bottom: 1px solid {theme.BORDER_SOFT}; }}")
        # LES DEUX RANGÉES PASSENT À LA LIGNE (D-67) : chaque groupe est un
        # bloc insécable dans un flux ; sur une fenêtre étroite les derniers
        # groupes descendent d'une ligne au lieu d'imposer à la fenêtre une
        # largeur minimale plus grande que l'écran — c'est ce qui faisait
        # « perdre une partie du contenu » sur un portable.
        from .flux import Rangee
        hb = Rangee(bar)

        def groupe(boite, nom, premier=False):
            """Ouvre un groupe dans la barre : un trait, puis son étiquette."""
            lbl = _etiquette_groupe(nom)
            boite.groupe(lbl, None if premier else _separateur_barre())
            self.groupes_barre[nom] = lbl
            return lbl

        # ---- PONT : où je regarde ----------------------------------------
        groupe(hb, "PONT", premier=True)
        # les ponts : des onglets, un clic — changer de pont est le geste le
        # plus fréquent du chargement, il ne mérite pas une liste déroulante
        self.boutons_pont = []
        self.ponts_box = QHBoxLayout()
        self.ponts_box.setSpacing(2)
        hb.addLayout(self.ponts_box)
        self.btn_zoom = QPushButton("Tout le pont")
        self.btn_zoom.setProperty("ghost", "1")
        self.btn_zoom.setToolTip("Quitter le zoom sur une cale et revoir le "
                                 "pont entier.")
        self.btn_zoom.clicked.connect(self.zoom_out)
        self.btn_zoom.setEnabled(False)
        hb.addWidget(self.btn_zoom)

        # ---- OUTIL : ce que le clic veut dire ------------------------------
        groupe(hb, "OUTIL")
        self.boutons_outil = {}
        for cle, texte, aide in (
                (OUTIL_SELECTION, "Sélectionner",
                 "Le clic CHOISIT un colis, un cadre tiré dans le vide "
                 "sélectionne ceux qu'il touche, un glissement les déplace, le "
                 "clic DROIT retire le colis visé. Cet outil ne pose JAMAIS : "
                 "c'est le point de retour, celui où Échap ramène toujours. "
                 "Double-clic dans le vide d'une cale : son plan de cale."),
                (OUTIL_POSE, "Poser",
                 "Le lot choisi dans « Lot » est EN MAIN : le fantôme suit le "
                 "pointeur et montre où le colis tomberait, le clic gauche l'y "
                 "pose, A le tourne d'un quart de tour. Choisir un lot bascule "
                 "ici tout seul ; Échap ou « — aucun lot — » ramène à "
                 "Sélectionner."),
                (OUTIL_ZONE, "Zone",
                 "Tracez un cadre : autant de colis du lot qu'il en tient y "
                 "sont posés."),
                (OUTIL_MESURE, "Mesurer",
                 "Tracez un cadre pour lire une distance sur le plan. La cote "
                 "RESTE écrite dessus — en long, en travers, diagonale — "
                 "jusqu'à la mesure suivante, à Échap ou au changement "
                 "d'outil.")):
            b = QPushButton(texte)
            b.setCheckable(True)
            b.setProperty("ghost", "1")
            b.setToolTip(aide)
            b.clicked.connect(lambda _c, k=cle: self.set_outil(k))
            hb.addWidget(b)
            self.boutons_outil[cle] = b

        # ---- LOT : ce que je tiens ----------------------------------------
        groupe(hb, "LOT")
        self.combo_lot = QComboBox()
        self.combo_lot.setMinimumWidth(200)
        self.combo_lot.setToolTip(
            "Le lot qu'on a EN MAIN : le choisir bascule sur l'outil « Poser », "
            "il suit alors le pointeur sur le plan et montre où il tomberait ; "
            "le clic gauche l'y pose et A le tourne d'un quart de tour. Pour "
            "QUITTER la pose, trois chemins : « — aucun lot — » ici, la touche "
            "Échap, ou le clic droit dans le vide. Un lot entièrement posé se "
            "repose tout seul.")
        self.combo_lot.currentIndexChanged.connect(self._on_lot)
        hb.addWidget(self.combo_lot)

        b_tourner = QPushButton("Tourner")
        b_tourner.setProperty("ghost", "1")
        b_tourner.setToolTip("Un lot en main : tourne le FANTÔME de 90° (touche "
                             "A), et il reste tourné pour les colis suivants. "
                             "Sans lot en main : tourne SUR PLACE, autour de "
                             "son centre, le colis sous le pointeur — la "
                             "sélection à défaut (touche R).")
        b_tourner.clicked.connect(self._tourner_bouton)
        b_retirer = QPushButton("Retirer")
        b_retirer.setProperty("ghost", "1")
        b_retirer.setToolTip("Retirer la sélection du plan (Maj+Suppr). Sous le "
                             "pointeur, Suppr — ou le clic DROIT — n'enlève QUE "
                             "le colis visé, même s'il vient d'une fournée posée "
                             "par zone. Les colis retournent au « reste à "
                             "embarquer » du manifeste.")
        b_retirer.clicked.connect(self.remove_selected)
        hb.addWidget(b_tourner)
        hb.addWidget(b_retirer)
        hb.addStretch(1)

        # ---- AFFICHAGE : ce que je vois ------------------------------------
        groupe(hb, "AFFICHAGE")
        # LE MENU DES CALQUES : ce qu'on dessine, et ce qu'on signale. Il
        # pilote l'objet `Calques` de la vue — le même que celui du menu
        # Affichage de la fenêtre principale.
        self.btn_calques = QPushButton("Calques ▾")
        self.btn_calques.setProperty("ghost", "1")
        self.btn_calques.setToolTip(
            "Ce qui se dessine sur le plan (fond, charges, hauteurs, "
            "épontilles, informations, étiquettes) et ce qui s'y signale. "
            "Les cases sont retenues d'une session à l'autre. Ce qui BLOQUE "
            "— contour de cale, zone interdite, épontille en place — n'a "
            "pas d'interrupteur : on ne masque pas un mur.")
        self.menu_calques = QMenu(self.btn_calques)
        self.actions_calques = remplir_menu_calques(self.menu_calques,
                                                    self.view.calques)
        self.btn_calques.setMenu(self.menu_calques)
        hb.addWidget(self.btn_calques)
        lbl_coul = QLabel("couleur")
        lbl_coul.setStyleSheet("background: transparent;")
        hb.addWidget(lbl_coul)
        self.combo_couleur = QComboBox()
        self.combo_couleur.addItem("par lot", "lot")
        self.combo_couleur.addItem("par port", "port")
        self.combo_couleur.addItem("par catégorie", "type")
        self.combo_couleur.setToolTip(
            "Ce que la couleur des colis raconte sur le plan : le lot du "
            "manifeste, le port de déchargement, ou la catégorie.")
        self.combo_couleur.currentIndexChanged.connect(self._on_mode_couleur)
        hb.addWidget(self.combo_couleur)
        root.addWidget(bar)

        # ---- deuxième rangée : la marchandise, le navire, la pose, l'état --
        bar2 = QFrame()
        bar2.setObjectName("cargoBar2")
        bar2.setStyleSheet(
            f"QFrame#cargoBar2 {{ background: {theme.SURFACE}; "
            f"border-bottom: 1px solid {theme.BORDER_SOFT}; }}")
        h2 = Rangee(bar2)

        # ---- CHARGEMENT : la marchandise -----------------------------------
        groupe(h2, "CHARGEMENT", premier=True)
        self.btn_solve = QPushButton("Répartir le chargement…")
        self.btn_solve.setProperty("accent", "1")
        self.btn_solve.setToolTip(
            "Proposer une répartition à partir du manifeste (F9) — un premier "
            "jet, à ajuster ensuite à la main.")
        self.btn_solve.clicked.connect(self._solve)
        h2.addWidget(self.btn_solve)
        b_manif = QPushButton("Manifeste…")
        b_manif.setProperty("ghost", "1")
        b_manif.setToolTip("Ce qu'il y a à embarquer : lots, quantités, ports, "
                           "couleurs — dans sa propre fenêtre.")
        b_manif.clicked.connect(self.open_manifeste)
        h2.addWidget(b_manif)
        b_liste = QPushButton("Charges posées…")
        b_liste.setProperty("ghost", "1")
        b_liste.setToolTip("La liste de ce qui est posé sur ce pont, avec les "
                           "positions — dans sa propre fenêtre.")
        b_liste.clicked.connect(self.open_liste_posees)
        h2.addWidget(b_liste)
        b_epont = QPushButton("Épontilles…")
        b_epont.setProperty("ghost", "1")
        b_epont.setToolTip(
            "Les épontilles amovibles des cales : cocher celles qui sont MISES "
            "EN PLACE à cette escale. Une épontille en place interdit la pose "
            "sous elle, comme le contour de la cale ; déposée, elle ne "
            "contraint rien. C'est une donnée du point, pas du navire.")
        b_epont.clicked.connect(self.open_epontilles)
        h2.addWidget(b_epont)
        # « Brouillons… » n'existe QUE si la fenêtre sait les ouvrir : le
        # brouillon de chargement appartient au journal, et un bouton qui
        # renverrait à une méthode absente serait un bouton mort.
        self.btn_brouillons = None
        if callable(getattr(self.win, "open_brouillons", None)):
            self.btn_brouillons = QPushButton("Brouillons…")
            self.btn_brouillons.setProperty("ghost", "1")
            self.btn_brouillons.setToolTip(
                "Les chargements mis de côté sans être figés au journal : les "
                "rouvrir, les comparer, en reprendre un.")
            self.btn_brouillons.clicked.connect(
                lambda: self.win.open_brouillons())
            h2.addWidget(self.btn_brouillons)
        # Pas de bouton « Plan de cale… » ici : « il est difficile de tomber
        # sur la bonne cale ». On la désigne du doigt — double-clic dans le
        # vide d'une cale, outil Sélectionner (`ouvrir_plan_de_cale`).
        # Pas de bouton « Contours… » non plus : on ne retouche pas un plan en
        # chargeant, et un bouton sous la main invite à le faire. L'éditeur
        # est dans le menu Navire, où l'on va exprès (parole du bord).

        # ---- NAVIRE : ce qui appartient au bord ----------------------------
        groupe(h2, "NAVIRE")
        b_cat = QPushButton("Catalogue…")
        b_cat.setProperty("ghost", "1")
        b_cat.setToolTip("Les types de colis du bord (Ctrl+K) : dimensions, poids, "
                         "stack, couleur — et de là, une ligne au manifeste.")
        b_cat.clicked.connect(lambda: self.win.open_catalogue())
        h2.addWidget(b_cat)
        b_mat = QPushButton("Matériel du bord…")
        b_mat.setProperty("ghost", "1")
        b_mat.setToolTip(
            "Les engins qui appartiennent au NAVIRE — chariot élévateur, "
            "transpalette : l'inventaire, leur poids, et où ils sont arrimés. "
            "Ils pèsent dans la stabilité mais ne sont pas de la marchandise : "
            "ils ne figurent jamais au manifeste.")
        b_mat.clicked.connect(self.open_materiel)
        h2.addWidget(b_mat)

        # ---- POSE : comment ça se pose -------------------------------------
        groupe(h2, "POSE")
        self.chk_aimant = QCheckBox("Aimanter")
        self.chk_aimant.setChecked(True)
        self.chk_aimant.setStyleSheet("background: transparent;")
        self.chk_aimant.setToolTip(
            "Coller les colis bord à bord entre eux et contre les parois de la "
            "cale, et aligner les rangées. Alt pendant le glissement s'en affranchit.")
        self.chk_aimant.toggled.connect(self._on_aimant)
        h2.addWidget(self.chk_aimant)
        lbl_jeu = QLabel("jeu d'arrimage")
        lbl_jeu.setStyleSheet("background: transparent;")
        h2.addWidget(lbl_jeu)
        self.sp_jeu = SpinNombre()
        self.sp_jeu.setRange(0.0, 1.0)
        self.sp_jeu.setSingleStep(0.05)
        self.sp_jeu.setDecimals(2)
        self.sp_jeu.setSuffix(" m")
        self.sp_jeu.setMaximumWidth(78)
        self.sp_jeu.setToolTip(
            "Le DÉBORDEMENT qu'on prête à chaque colis, de chaque côté : une "
            "palette affaissée dont le contenu dépasse un peu, la place des "
            "saisines, le passage des fourches. Deux voisins se trouvent donc "
            "écartés de deux fois cette valeur, un colis et la muraille d'une "
            "seule.\n\nIl s'applique PARTOUT et de la même façon : à la main "
            "comme en automatique (répartiteur, « Remplir la zone », plan de "
            "cale), à l'aimantation, et que « Aimanter » soit coché ou non. "
            "Une pose qui ne le respecte pas est refusée, et le motif le "
            "dit.\n\nC'est un réglage de travail, retenu d'un point de "
            "chargement à l'autre et écrit dans aucun fichier. À ne pas "
            "confondre avec le DÉBORD, qui est une dimension du LOT — ce qui "
            "dépasse vraiment de la palette — et se règle au manifeste, ligne "
            "par ligne. Les deux s'additionnent.")
        self.sp_jeu.setValue(self.view.jeu_m)
        self.sp_jeu.valueChanged.connect(self._on_jeu)
        # LA MOLETTE REND LE CLAVIER AU PLAN dès que la saisie est finie :
        # elle gardait le focus tant qu'on ne cliquait pas ailleurs, et c'est
        # de là que partait le « Échap parfois ne fonctionne pas » du bord.
        # Le filtre d'application le rattrape désormais, mais mieux vaut ne
        # pas avoir à le rattraper.
        self.sp_jeu.editingFinished.connect(self._jeu_saisi)
        h2.addWidget(self.sp_jeu)
        h2.addStretch(1)

        # ---- ÉTAT : ce qui est posé, et ce que ça vaut ---------------------
        groupe(h2, "ÉTAT")
        # UN CONTRÔLE ÉTEINT SE DIT, en orange, à côté du compteur : sans
        # cela, « Plan valide » mentirait par omission à qui reprend le poste.
        self.lbl_controles = QLabel("")
        self.lbl_controles.setStyleSheet("background: transparent;")
        h2.addWidget(self.lbl_controles)
        h2.addSpacing(8)
        self.lbl_total = QLabel("")
        self.lbl_total.setStyleSheet("font-weight: bold; background: transparent;")
        h2.addWidget(self.lbl_total)
        # LA DERNIÈRE MESURE, SOUS LES YEUX : la barre d'état est loin du
        # regard de celui qui tire un cadre sur le plan. En abrégé et bornée
        # en largeur : une cote qui pousserait le verdict hors de la barre
        # serait un mauvais marché — la phrase entière est de toute façon
        # écrite sur le plan, dans l'infobulle et dans la barre d'état.
        self.lbl_mesure = QLabel("")
        self.lbl_mesure.setStyleSheet(
            f"color: {theme.WARN}; background: transparent;")
        self.lbl_mesure.setMaximumWidth(200)
        h2.addWidget(self.lbl_mesure)
        h2.addSpacing(10)
        # LE VERDICT SE DÉROULE. « Quand une erreur est relevée, on a le
        # nombre d'erreurs affiché. Il serait bien de pouvoir dérouler la
        # liste des erreurs et d'un simple clic arriver sur le colis en
        # défaut » : ce n'est plus une étiquette, c'est un bouton à menu.
        self.lbl_probs = QToolButton()
        self.lbl_probs.setObjectName("verdictPlan")
        self.lbl_probs.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.lbl_probs.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.lbl_probs.setAutoRaise(True)
        self.lbl_probs.setMinimumWidth(104)
        self.menu_problemes = QMenu(self.lbl_probs)
        # le menu se garnit À L'OUVERTURE : parcourir tout le navire à chaque
        # colis posé coûterait cher pour une liste que personne ne regarde
        self.menu_problemes.aboutToShow.connect(self._garnir_menu_problemes)
        self.lbl_probs.setMenu(self.menu_problemes)
        self.btn_problemes = self.lbl_probs      # son vrai nom, depuis v2.15.2
        h2.addWidget(self.lbl_probs)
        root.addWidget(bar2)

        # ---- le plan, en grand ; l'iso et la coupe à droite ---------------
        split = QSplitter(Qt.Orientation.Horizontal)
        self.view.changed.connect(self._on_view_changed)
        self.view.selection_changed.connect(self._on_view_selection)
        self.view.zoom_annule.connect(self.zoom_out)
        self.view.refuse.connect(self._message)
        self.view.outil_fini.connect(self._message)
        self.view.lot_lache.connect(self.lacher_le_lot)
        self.view.echap_frappee.connect(self.echap)
        self.view.cale_survolee.connect(self._dire_la_cale_survolee)
        self.view.cale_ouverte.connect(self.ouvrir_plan_de_cale)
        self.view.cale_zoomee.connect(self.zoom_in)
        self.view.menu_cale.connect(self.menu_de_la_cale)
        self.view.mesure_faite.connect(self._on_mesure)
        # une épontille basculée AU PLAN suit exactement le chemin de la
        # fenêtre « Épontilles… » : même rafraîchissement, même phrase
        self.view.epontille_basculee.connect(self._on_epontille_change)
        self.view.epontilles_demandees.connect(self.open_epontilles)
        self.view.calques.changed.connect(self._on_calques)
        # Ce qu'on regarde a un nom, et il doit être écrit au-dessus du plan :
        # le pont entier (« Pont intermédiaire »), ou la cale quand on est
        # zoomé dessus (« 2040 CALE AR MILIEU — Pont intermédiaire »). Sans
        # cela rien ne distingue à l'œil un pont d'une cale isolée (retour du
        # bord, v2.14.7).
        bloc_plan = QWidget()
        bp = QVBoxLayout(bloc_plan)
        bp.setContentsMargins(0, 0, 0, 0)
        bp.setSpacing(0)
        self.titre_plan = QLabel("")
        self.titre_plan.setObjectName("viewHeader")
        bp.addWidget(self.titre_plan)
        bp.addWidget(self.view, 1)
        split.addWidget(bloc_plan)

        from .isoview import IsoView
        from .coupe_view import CoupeView
        droite = QSplitter(Qt.Orientation.Vertical)
        bloc_iso = QWidget()
        bl = QVBoxLayout(bloc_iso)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        t_iso = QLabel("VUE NAVIRE — clic : venir sur son pont · double-clic : zoomer")
        t_iso.setObjectName("viewHeader")
        bl.addWidget(t_iso)
        self.iso = IsoView()
        self.iso.capacity_activated.connect(self._iso_activee)
        self.iso.capacity_clicked.connect(self._iso_choisie)
        self.iso.capacity_hovered.connect(self._iso_survolee)
        bl.addWidget(self.iso, 1)
        droite.addWidget(bloc_iso)
        bloc_coupe = QWidget()
        bc = QVBoxLayout(bloc_coupe)
        bc.setContentsMargins(0, 0, 0, 0)
        bc.setSpacing(0)
        t_coupe = QLabel("COUPE AU REPÈRE — glissez le trait rouge · clic sur une cale : "
                         "venir sur son pont")
        t_coupe.setObjectName("viewHeader")
        bc.addWidget(t_coupe)
        self.coupe = CoupeView(win)
        self.coupe.cliquable = self.est_cale
        self.coupe.cale_choisie.connect(self._iso_choisie)
        bc.addWidget(self.coupe, 1)
        droite.addWidget(bloc_coupe)
        droite.setSizes([320, 300])
        droite.setMinimumWidth(300)
        self.view.coupe_moved.connect(self.coupe.set_x)
        split.addWidget(droite)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        split.setSizes([1080, 380])
        root.addWidget(split, 1)
        self.set_outil(OUTIL_SELECTION)
        self._refresh_controles()
        # LE FILET ÉCHAP, posé sur l'APPLICATION (voir `eventFilter`).
        QApplication.instance().installEventFilter(self)

    # --------------------------------------------------------- touche Échap
    def eventFilter(self, obj, event):
        """LE FILET ÉCHAP, second chemin de la touche vers le plan.

        POURQUOI DEUX MÉCANISMES. Le premier — le focus qui suit la souris
        (`DeckStowView.enterEvent`) — est le bon : il rend au plan tout le
        clavier (Échap, A, R, Suppr) dès que le pointeur est dessus, et c'est
        la situation de travail normale. Mais il ne couvre que ce cas : le
        pointeur peut être sur la liste des lots, sur le manifeste, sur un
        bouton de la barre, sur la molette du jeu, ou revenir d'une fenêtre
        qu'on vient de fermer (répartiteur F9, boîte de dialogue) — le focus
        est alors ailleurs, et pour le bord « Échap ne marche plus ». D'où ce
        second chemin, qui ne dépend d'aucun focus.

        POURQUOI SUR L'APPLICATION, ET PLUS SUR LA FENÊTRE. Posé sur la
        fenêtre, le filtre ne voyait la touche qu'après TOUS les widgets :
        n'importe quel widget qui l'avalait sans rien en faire — et une
        molette avale Échap — la faisait disparaître en route. Sur
        l'application, on la voit en premier, et les garde-fous de
        `_echap_permis` disent à qui elle appartient : une modale, un popup,
        une saisie de texte la gardent ; tout le reste la cède au plan.

        On ne la consomme QUE si l'on agit (`echap`)."""
        if event.type() == QEvent.Type.KeyPress \
                and event.key() == Qt.Key.Key_Escape \
                and _echap_permis(self):
            if self.echap():
                return True
        return super().eventFilter(obj, event)

    def echap(self):
        """ÉCHAP : retour à l'outil « Sélectionner », quoi qu'il arrive.

        « Quand on frappe Échap, ça devrait nous ramener systématiquement sur
        un outil sélectionner. » Dans l'ordre, et d'un seul coup : le geste en
        cours est abandonné (cadre, glissement, repère de coupe), la mesure
        dessinée s'efface, la pièce en main est reposée, l'outil revient à
        Sélectionner. S'il n'y avait rien de tout cela — on était déjà au
        repos —, la seconde frappe vide la sélection.

        Rend `True` si quelque chose a été annulé : la touche n'est consommée
        que dans ce cas, pour qu'un Échap qui ne sert à rien ici serve
        ailleurs."""
        v = self.view
        agi = v.annuler_geste()
        if v.effacer_mesure():
            agi = True
        lache = False
        if v.lot is not None:
            # par le plan : c'est lui qui efface aussi le colis en main. Son
            # signal `lot_lache` ramène la barre à « aucun lot », donc l'outil
            # à Sélectionner (`_on_lot`), et dit ce qu'il a fait.
            v.lacher_le_lot()
            agi = lache = True
        if v.outil != OUTIL_SELECTION:
            self.set_outil(OUTIL_SELECTION)
            agi = True
        if not agi and v.selection:
            v.set_selection([])
            v.update()
            self._message("Sélection vidée.")
            return True
        if agi:
            v.update()
            if not lache:      # « Lot lâché… » dit déjà mieux ce qui s'est passé
                self._message("Retour à l'outil « Sélectionner » : le clic "
                              "choisit, il ne pose plus.")
        return agi

    # ------------------------------------------------------------- outils
    def set_outil(self, cle):
        """Rend un outil courant : un seul actif, et la barre le montre.

        Changer d'outil efface la mesure dessinée — une cote qui resterait
        sur le plan pendant qu'on pose ne se rapporterait plus à rien."""
        if cle != self.view.outil:
            self.view.effacer_mesure()
        self.view.outil = cle
        for k, b in self.boutons_outil.items():
            b.blockSignals(True)
            b.setChecked(k == cle)
            b.blockSignals(False)
        # sous « Sélectionner », le fantôme n'a plus lieu d'être ; sous
        # « Poser », il doit reparaître sans qu'on ait à bouger la souris
        self.view.rafraichir_fantome()
        aides = {
            OUTIL_SELECTION:
                "Sélectionner — clic : choisir un colis · cadre dans le vide : "
                "sélectionner ce qu'il touche · glisser : déplacer · clic "
                "droit : retirer · double-clic dans le vide d'une cale : son "
                "plan de cale · clic sur une épontille : la mettre en place ou "
                "la déposer · R : tourner sur place · Suppr : retirer.",
            OUTIL_POSE:
                "Poser — le lot de la barre est en main : le clic gauche le "
                "pose au fantôme · A le tourne · clic droit sur un colis : le "
                "retirer · Échap : revenir à « Sélectionner ».",
            OUTIL_ZONE: "Tracez le cadre à garnir : autant de colis du lot qu'il en tient.",
            OUTIL_MESURE: "Tracez un cadre pour lire une distance. Elle reste "
                          "écrite sur le plan jusqu'à la suivante.",
        }
        self._message(aides.get(cle, ""))

    def _on_lot(self, index):
        """Le lot choisi dans la barre passe EN MAIN — l'outil bascule sur
        « Poser », et le plan reprend le focus.

        CHOISIR UN LOT, C'EST VOULOIR LE POSER : on ne demande pas un second
        geste pour armer l'outil. Inversement, « — aucun lot — » ramène à
        Sélectionner : il n'y a plus rien à poser.

        Le focus rendu au plan n'est pas un détail : sans cela le clavier
        restait à la liste déroulante, Échap, A et R n'arrivaient jamais au
        plan, et « on ne peut plus quitter la pose de colis » — la sortie
        existait, elle n'était simplement plus adressée."""
        lot = self.combo_lot.itemData(index)
        self.view.lot = lot
        self.set_outil(OUTIL_POSE if lot is not None else OUTIL_SELECTION)
        self.view.setFocus()
        self._dire_le_lot()

    def _dire_le_lot(self):
        """Ce que la barre d'état dit de la pièce en main — et des TROIS
        façons d'en sortir, puisque le bord n'en trouvait aucune."""
        lot = self.view.lot
        if lot is None:
            self._message("Aucun lot en main — outil « Sélectionner » : le clic "
                          "choisit, le clic sur une épontille la met en place "
                          "ou la dépose, le double-clic dans le vide d'une "
                          "cale ouvre son plan de cale.")
            return
        self._message(
            f"« {lot.nom} » en main, outil « Poser » : le clic gauche pose au "
            "fantôme, A le tourne. Pour QUITTER la pose : Échap, clic droit "
            "dans le vide, ou « — aucun lot — » dans la barre.")

    def _on_mode_couleur(self, index):
        self.view.mode_couleur = self.combo_couleur.itemData(index)
        self.view.update()
        self._refresh_iso(getattr(self.win, "project", None))
        self._refresh_coupe()

    def couleur_charge(self, pl):
        """La couleur d'un colis selon le mode choisi (lot, port, catégorie),
        en hexadécimal. La vue iso et la coupe peuvent la lire
        (`getattr(panel, "couleur_charge", None)`) pour peindre comme le plan."""
        return self.view.couleur_de(pl).name()

    def open_contours(self):
        """L'éditeur de plans, ouvert sur le pont affiché : c'est en posant
        qu'on voit qu'un contour est faux, autant le corriger sans quitter
        le chargement. La géométrie enregistrée revient ici toute seule."""
        ouvrir = getattr(self.win, "open_plan_editor", None)
        if not callable(ouvrir):
            return None
        ed = ouvrir()
        if ed is not None and self.view.deck is not None:
            montrer = getattr(ed, "show_view", None)
            if callable(montrer):
                montrer(self.view.deck.name)
        return ed

    def _ouvrir_fenetre(self, attribut, fabrique):
        """Ouvre (ou rouvre) une fenêtre annexe, sans jamais rester coincé.

        Une fenêtre déjà fermée se rouvre ; une fenêtre dont l'objet C++ a été
        détruit est reconstruite plutôt que de faire échouer le clic ; et si
        elle refuse de se garnir, on le dit au lieu de montrer un tableau vide.
        """
        dlg = getattr(self, attribut, None)
        try:
            if dlg is not None:
                dlg.isVisible()          # lève si l'objet C++ n'est plus là
        except RuntimeError:
            dlg = None
        if dlg is None:
            dlg = fabrique()
            setattr(self, attribut, dlg)
        try:
            dlg.refresh()
        except Exception as e:           # pragma: no cover - filet de sécurité
            import traceback
            traceback.print_exc()
            self._message(f"La fenêtre n'a pas pu se garnir : {e}")
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        return dlg

    def open_manifeste(self):
        from .manifest_dialog import ManifestDialog

        def fabrique():
            d = ManifestDialog(self.win, self)
            d.changed.connect(self._on_manifeste_change)
            return d
        return self._ouvrir_fenetre("_manif", fabrique)

    def _on_manifeste_change(self):
        self._refresh_lots()
        self.win.on_condition_changed()

    def _tourner_bouton(self):
        """Le bouton « Tourner » fait ce que le bord attend de lui : un lot en
        main, c'est le fantôme qu'on tourne — et il reste tourné d'un colis
        au suivant. Le bouton tournait la sélection, c'est-à-dire le colis
        qu'on venait de poser, et jamais celui qu'on s'apprêtait à poser. Le
        focus revient à la vue : la touche A doit marcher juste après.

        Sans lot en main, il fait ce que fait la touche R : le colis SOUS LE
        POINTEUR d'abord, la sélection à défaut — et cette rotation-là se fait
        autour du centre du colis, sur place."""
        v = self.view
        if v.lot is not None:
            v.tourner_la_main()
            v.rafraichir_fantome()
        else:
            v.tourner_survol_ou_selection()
        v.setFocus()

    def open_epontilles(self):
        """La fenêtre des épontilles amovibles : une case par épontille.

        Elle vit à côté du plan (on coche, on voit tout de suite le plan
        changer) et chaque bascule redit ce qu'elle a fait dans la barre."""
        from .dialogs import EpontillesDialog

        def fabrique():
            d = EpontillesDialog(self.win, self)
            d.changed.connect(self._on_epontille_change)
            return d
        return self._ouvrir_fenetre("_epont", fabrique)

    def _on_epontille_change(self, message):
        """Une épontille vient d'être posée ou déposée : le plan, les
        problèmes et le calcul repartent tous de la condition modifiée."""
        # une épontille en place est un mur (D-30) : elle change ce qui est en
        # défaut sans qu'aucun colis n'ait bougé
        self.view.invalider_problemes()
        self.view.update()
        self._message(message)
        self.win.on_condition_changed()
        self._refresh_problems()
        # basculée AU PLAN, la fenêtre ouverte doit suivre : deux états de la
        # même épontille sous les yeux, c'est un plan auquel on ne croit plus
        # … mais JAMAIS depuis le signal d'une de ses propres lignes : quand
        # la bascule vient d'une case de cette fenêtre, on est encore dans
        # `itemChanged` de la ligne cochée, et `refresh()` fait `tree.clear()`
        # — la ligne est détruite sous les pieds de Qt, qui s'effondre
        # (plantage constaté à bord à la première épontille cochée). On
        # reconstruit donc au prochain tour de boucle, une fois le signal
        # entièrement déroulé.
        dlg = getattr(self, "_epont", None)
        try:
            if dlg is not None and dlg.isVisible():
                QTimer.singleShot(0, dlg.refresh)
        except RuntimeError:
            self._epont = None            # fenêtre détruite : on l'oublie

    def open_liste_posees(self):
        from .posees_dialog import PoseesDialog
        return self._ouvrir_fenetre(
            "_posees", lambda: PoseesDialog(self.win, self))

    def _on_aimant(self, actif):
        """« Aimanter » ne commande QUE l'aimantation.

        Le jeu restait grisé quand on la décochait, alors que le calepinage
        (remplir une zone, en montrer l'aperçu) continuait de l'appliquer :
        l'officier voyait un champ éteint et des colis espacés quand même. Le
        jeu sert au calepinage, pas à l'aimantation — il reste donc réglable."""
        self.view.aimantation = bool(actif)

    def _on_jeu(self, v):
        # La vue GARDE le réglage : elle vit autant que la fenêtre, donc le
        # jeu vaut d'un point de chargement à l'autre. Le plan de cale et le
        # répartiteur viennent le lire ici (`jeu_arrimage`) : un seul jeu
        # d'arrimage pour tout le navire ouvert (D-39).
        self.view.jeu_m = float(v)

    def _jeu_saisi(self):
        """La saisie du jeu est finie : le clavier retourne au plan.

        La molette le gardait tant qu'on ne cliquait pas ailleurs — et c'est
        de là que partait, pour une bonne part, l'« Échap ne fonctionne pas »
        du bord : la touche allait à un champ qui n'en faisait rien. On ne
        reprend le focus QUE si la molette l'a encore (un Tab l'a peut-être
        déjà donné à un voisin) et si le plan est là pour le recevoir."""
        if self.sp_jeu.hasFocus() and self.view.isVisible():
            self.view.setFocus(Qt.FocusReason.OtherFocusReason)

    def _on_mesure(self, mesure):
        """La dernière mesure, écrite dans l'état du panneau — à côté du
        compte des charges, sous les yeux de qui tire le cadre.

        En abrégé : la barre est étroite, et la phrase entière est déjà sur le
        plan, dans la barre d'état et dans l'infobulle."""
        if mesure is None:
            self.lbl_mesure.setText("")
            self.lbl_mesure.setToolTip("")
            return
        dx, dy, _diag = mesure
        self.lbl_mesure.setText(f"·  mesure {dx:.2f} × {dy:.2f} m")
        self.lbl_mesure.setToolTip(self.view.dire_la_mesure())

    def _solve(self, cales=None):
        """Le répartiteur ; `cales` : ne cocher que celles-là (menu d'une cale)."""
        ouvrir = getattr(self.win, "open_solver", None)
        if callable(ouvrir):
            ouvrir(cales=cales) if cales else ouvrir()

    # ------------------------------------------------------------- titre
    def titre_du_plan(self):
        """Ce que montre le plan, dit comme le bord le nomme.

        Le pont entier n'a que son nom ; une cale zoomée se nomme par son
        code ET son nom — c'est ainsi qu'elle est repérée à bord et sur les
        plans du chantier — suivis du pont où elle est, qu'on perd de vue dès
        qu'on est zoomé dessus. Aucun libellé n'est écrit en dur : tout vient
        du navire ouvert."""
        deck = self.view.deck
        cap = self.view.zoom_hold
        pont = (deck.name if deck is not None else "") or "Pont sans nom"
        if cap is None:
            return pont if deck is not None else "Aucun pont tracé"
        cale = " ".join(m for m in (cap.code, cap.name) if m) or "Cale sans nom"
        return f"{cale} — {pont}"

    def _refresh_titre(self):
        titre = getattr(self, "titre_plan", None)
        if titre is not None:
            titre.setText(self.titre_du_plan())

    # ------------------------------------------------------------- ponts
    def refresh(self):
        self._refresh_impl()
        self._refresh_coupe()

    def _refresh_coupe(self):
        coupe = getattr(self, "coupe", None)
        if coupe is None:
            return
        xc = self.view.x_coupe_effectif()
        if xc is not None:
            coupe.set_x(xc)
        else:
            coupe.update()

    def _refresh_impl(self):
        proj = getattr(self.win, "project", None)
        decks = proj.sorted_decks() if proj else []
        self._adopter_materiel_migre()
        self._loading = True
        try:
            self._refresh_ponts(decks)
            self._refresh_lots()
        finally:
            self._loading = False
        self.view.elaguer()
        # le titre suit le pont montré et le zoom : tout ce qui change l'un ou
        # l'autre repasse ici
        self._refresh_titre()
        # tout ce qui arrive par l'extérieur (solveur, plan de cale, manifeste,
        # épontilles, changement de point ou de navire) repasse par ici : les
        # défauts mémorisés du plan n'y survivent pas
        self.view.invalider_problemes()
        self._refresh_resume()
        self.view.update()
        self._refresh_iso(proj)
        for nom in ("_posees", "_manif"):
            dlg = getattr(self, nom, None)
            try:
                if dlg is not None and dlg.isVisible():
                    dlg.refresh()
            except RuntimeError:
                setattr(self, nom, None)      # fenêtre détruite : on l'oublie

    def _refresh_ponts(self, decks):
        """Un bouton par pont, dans l'ordre du navire (du bas vers le haut)."""
        courant = self.view.deck
        if len(self.boutons_pont) != len(decks) or any(
                b.property("deck_nom") != d.name for b, d in zip(self.boutons_pont, decks)):
            while self.ponts_box.count():
                w = self.ponts_box.takeAt(0).widget()
                if w is not None:
                    w.deleteLater()
            self.boutons_pont = []
            for d in decks:
                b = QPushButton(d.name)
                b.setCheckable(True)
                b.setProperty("ghost", "1")
                b.setProperty("deck_nom", d.name)
                b.setToolTip(f"{d.name} — Z = {d.z:g} m sur quille")
                b.clicked.connect(lambda _c, dd=d: self.choisir_pont(dd))
                self.ponts_box.addWidget(b)
                self.boutons_pont.append(b)
        if decks and courant not in decks:
            # autre navire (ou ponts refaits) : le zoom désignait une cale de
            # l'ancien projet, l'iso n'a jamais cadré celui-ci
            courant = decks[0]
            self.view.deck = courant
            self.view.zoom_hold = None
            self.btn_zoom.setEnabled(False)
            self.btn_zoom.setText("Tout le pont")
            self.view.set_selection([])
            self._iso_faite = False
        for b, d in zip(self.boutons_pont, decks):
            b.blockSignals(True)
            b.setChecked(d is courant)
            b.blockSignals(False)

    def choisir_pont(self, deck):
        self.view.deck = deck
        self.view.zoom_hold = None
        self.view.set_selection([])
        self.btn_zoom.setEnabled(False)
        self._refresh_impl()
        self._refresh_coupe()

    def _refresh_lots(self):
        """Les lots du manifeste, avec ce qu'il en reste à embarquer.

        En tête, une entrée « — aucun lot — » : c'est elle qui dit, noir sur
        blanc, qu'on n'a rien en main et que le clic sert alors à choisir.
        Échap y revient. On ne la quitte plus tout seul : un lot lâché reste
        lâché, y compris après chaque pose (la liste se recompose à chaque
        changement, elle ne doit pas remettre une pièce en main d'autorité).

        Deux groupes séparés par un trait : les **lots du manifeste** — ce qui
        attend sur le quai — puis le **matériel du bord** — ce qui appartient
        au navire. On ne confond pas les deux d'un clic distrait."""
        from PySide6.QtGui import QIcon, QPixmap
        cond = self.win.condition
        courant = self.combo_lot.currentData()
        # la toute première composition, elle, met le premier lot en main :
        # ouvrir le chargement avec un manifeste et rien à poser serait sec.
        # « Première » se juge sur les LOTS déjà offerts, pas sur la longueur
        # de la liste : le matériel du bord y figure dès le départ, et il ne
        # doit pas faire croire qu'un lot a déjà été proposé.
        premiere = not getattr(self, "_lots_offerts", False)
        restes = cond.places_par_ligne()
        self.combo_lot.blockSignals(True)
        try:
            self.combo_lot.clear()
            self.combo_lot.addItem(AUCUN_LOT, None)
            index = 0
            # la première composition met le premier LOT en main — jamais un
            # matériel du bord : on n'ouvre pas le chargement avec le chariot
            # du bord au bout du pointeur
            premier = None
            for i, m in enumerate(cond.manifeste):
                etiquette = ("du bord" if getattr(m, "hors_manifeste", False)
                             else f"reste {max(0, m.quantite - restes[i])}")
                pm = QPixmap(10, 10)
                pm.fill(QColor(couleur_hex(m)))
                self.combo_lot.addItem(QIcon(pm), f"{m.nom} — {etiquette}", m)
                if premier is None:
                    premier = self.combo_lot.count() - 1
                if m is courant:
                    index = self.combo_lot.count() - 1
            # LE MATÉRIEL DU BORD, À PART. Ce n'est pas de la marchandise :
            # il se pose et se déplace comme un colis, mais il ne se mélange
            # pas aux lots du manifeste dans la liste — un séparateur et un
            # intitulé, pour qu'on ne le prenne jamais pour du fret.
            engins = [e for e in self._materiel_a_bord() if e.a_bord]
            if engins:
                self.combo_lot.insertSeparator(self.combo_lot.count())
                self.combo_lot.addItem("— Matériel du bord —", None)
                self._desactiver_entree(self.combo_lot.count() - 1)
                for e in engins:
                    pm = QPixmap(10, 10)
                    pm.fill(QColor(couleur_hex(e)))
                    # avec plusieurs exemplaires, la liste dit ce qu'il reste à
                    # arrimer — comme le « reste » d'un lot du manifeste
                    qte = max(1, int(getattr(e, "quantite", 1) or 1))
                    poses = len(cond.poses_du_materiel(e.id))
                    if qte > 1:
                        etat = (f"{poses}/{qte} posé(s)" if poses
                                else f"{qte} à arrimer")
                    else:
                        etat = "posé" if poses else "à arrimer"
                    self.combo_lot.addItem(QIcon(pm), f"{e.nom} — {etat}", e)
                    if e is courant or getattr(courant, "id", None) == e.id:
                        index = self.combo_lot.count() - 1
            if courant is None and premiere and premier is not None:
                index = premier
                # la toute première composition met un lot en main : l'outil
                # qui va avec est « Poser ». Aux compositions suivantes on ne
                # touche à rien — l'officier peut travailler à la sélection
                # avec un lot encore choisi dans la barre.
                arme_la_pose = True
            else:
                arme_la_pose = False
            self.combo_lot.setCurrentIndex(index)
            self.view.lot = self.combo_lot.itemData(index)
            self._lots_offerts = bool(cond.manifeste)
        finally:
            self.combo_lot.blockSignals(False)
        if arme_la_pose and self.view.lot is not None:
            self.set_outil(OUTIL_POSE)

    def _desactiver_entree(self, i):
        """Un intitulé de groupe se lit, il ne se choisit pas."""
        modele = self.combo_lot.model()
        item = modele.item(i) if hasattr(modele, "item") else None
        if item is not None:
            item.setEnabled(False)

    def _materiel_a_bord(self):
        """L'inventaire du matériel du bord de ce navire.

        Il appartient au NAVIRE : on le lit dans son dossier, une fois, et on
        le partage avec la fenêtre d'inventaire et le manifeste."""
        from .equipements_dialog import inventaire_du_bord
        try:
            return list(inventaire_du_bord(self.win))
        except Exception:            # pragma: no cover - dossier illisible
            return []

    def open_materiel(self):
        """L'inventaire du matériel du bord, dans sa fenêtre."""
        from .equipements_dialog import EquipementsDialog

        def fabrique():
            d = EquipementsDialog(self.win, self)
            d.changed.connect(self._on_materiel_change)
            return d
        return self._ouvrir_fenetre("_materiel", fabrique)

    def _on_materiel_change(self):
        self._refresh_lots()
        self.view.elaguer()
        self.view.update()
        self.win.on_condition_changed()

    def _adopter_materiel_migre(self):
        """Un point enregistré avant l'inventaire portait ses engins en lignes
        de manifeste « du bord » : on les verse à l'inventaire du navire, et
        on le dit une fois dans la barre d'état. Ni silence complet, ni boîte
        de dialogue à cliquer avant de travailler."""
        cond = getattr(self.win, "condition", None)
        if cond is None or not getattr(cond, "materiel_migre", None):
            return 0
        from .equipements_dialog import adopter_migration
        n, msg = adopter_migration(self.win, cond)
        if msg:
            self._message(msg)
        return n

    def lacher_le_lot(self):
        """Plus rien en main : la barre repasse à « aucun lot », et l'outil à
        « Sélectionner ».

        Trois chemins y mènent (Échap, le clic droit dans le vide, le lot
        entièrement posé) et ils passent tous ici : une barre qui montrerait
        encore « Poser » alors qu'il n'y a plus rien à poser, c'est un clic
        suivant qu'on ne comprend pas."""
        if self.combo_lot.currentIndex() != 0:
            self.combo_lot.setCurrentIndex(0)   # → `_on_lot` fait le reste
        self.view.lot = None
        if self.view.outil == OUTIL_POSE:
            self.set_outil(OUTIL_SELECTION)
        self._message("Lot lâché : le clic choisit de nouveau. "
                      "Reprenez un lot dans la barre pour poser.")

    def _refresh_resume(self):
        """Le compte de ce pont, dans la barre — plus de tableau permanent."""
        charges = [(pl, cap) for cap in self.view.holds()
                   for pl in self.view.placements(cap)]
        poids = sum(pl.poids_total_t for pl in (p for p, _c in charges))
        sel = len(self.view.selection)
        self.lbl_total.setText(
            (f"{len(charges)} charge(s) sur ce pont · {poids:.2f} t"
             if charges else "Aucune charge sur ce pont.")
            + (f"  ·  {sel} sélectionnée(s)" if sel else ""))
        self._refresh_problems()

    def _refresh_iso(self, proj):
        """La vue navire ne montre que les **cales**, avec les colis qui y sont
        posés, et sert de sélecteur inter-ponts.

        Les soutes et ballasts tracés sur les mêmes ponts sont écartés : ils
        appartiennent à la vue des capacités, et on ne charge rien dedans."""
        premiere = not getattr(self, "_iso_faite", False)
        # les cales du pont affiché en pleine lumière, les autres estompées :
        # on voit où l'on travaille sans lire les étiquettes
        en_avant = ({c.code for c in self.view.deck.capacities}
                    if self.view.deck is not None else None)
        # les épontilles du POINT, pas celles du plan : la vue navire doit
        # montrer les murs qui sont effectivement dressés (D-30)
        self.iso.rebuild(proj, load_ratio=self._taux_occupation,
                         filtre=self.est_cale,
                         charges=self.win.condition.placements,
                         en_avant=en_avant,
                         couleur_charge=self.couleur_charge,
                         epontilles=(self.view.epontilles_en_place()
                                     if self.view.calques.actif(CALQUE_EPONTILLES)
                                     else None))
        if premiere and self.iso.scene().items():
            self.iso.fit()
            self._iso_faite = True

    def est_cale(self, cap):
        """Une forme tracée qui n'est pas une capacité liquide du dossier."""
        nav = getattr(self.win, "nav", None)
        if nav is None:
            return True
        return not (nav.est_capacite(cap.code) or nav.est_capacite(cap.name))

    def _taux_occupation(self, cap):
        aire = _aire_polygone(cap.points) if len(cap.points) >= 3 else 0.0
        if aire <= 0:
            return 0.0
        # ce qui est occupé, c'est l'encombrement : le taux répond à « que
        # reste-t-il de place ? », et le débord en prend (D-39)
        occupee = sum(p.encombrement[0] * p.encombrement[1]
                      for p in self.win.condition.placements.get(cap.code, []))
        return max(0.0, min(1.0, occupee / aire))

    def _iso_choisie(self, cap):
        """Simple clic dans la vue navire : le plan vient sur ce pont, et la
        cale est mise en avant. Le double-clic, lui, zoome dessus."""
        proj = getattr(self.win, "project", None)
        if proj is None or cap is None:
            return
        for deck in proj.sorted_decks():
            if cap in deck.capacities:
                if deck is not self.view.deck:
                    self.choisir_pont(deck)
                self.view.zoom_hold = None
                self.btn_zoom.setEnabled(False)
                self.view.survol_cale = cap
                # on quitte le zoom sans repasser par `_refresh_impl` : le
                # titre doit redire le pont
                self._refresh_titre()
                self.view.update()
                self._refresh_iso(proj)
                self._message(
                    f"{cap.code} · {cap.name or ''} — {deck.name}. "
                    "Double-cliquez pour zoomer dessus.".strip())
                return

    def _iso_survolee(self, cap):
        if cap is None:
            self._message("")
            return
        taux = self._taux_occupation(cap) * 100
        self._message(f"{cap.code} · {cap.name or ''} — {taux:.0f} % occupée. "
                      "Un clic pour venir sur son pont, un double-clic pour "
                      "zoomer.".strip())

    def _iso_activee(self, cap):
        """Double-clic dans la vue navire : on saute au pont de la cale et on
        zoome dessus."""
        proj = getattr(self.win, "project", None)
        if proj is None:
            return
        for deck in proj.sorted_decks():
            if cap in deck.capacities:
                self.view.deck = deck
                break
        if cap.kind != KIND_CONTOUR:
            self.zoom_in(cap)

    def zoom_in(self, cap):
        self.view.zoom_hold = cap
        self.btn_zoom.setEnabled(True)
        self.btn_zoom.setText(f"Tout le pont (zoom : {cap.code})")
        self._refresh_impl()
        self._refresh_coupe()

    def zoom_out(self):
        self.view.zoom_hold = None
        self.btn_zoom.setEnabled(False)
        self.btn_zoom.setText("Tout le pont")
        self._refresh_impl()
        # l'étendue des cales visibles change avec le zoom : le repère de
        # coupe se redessine ailleurs, la coupe doit suivre
        self._refresh_coupe()

    def _on_calques(self):
        """Un calque ou un contrôle a bougé : la vue se redessine (elle s'en
        charge), le compteur se refait — un contrôle éteint retire des
        problèmes — et la barre rappelle ce qui est éteint."""
        self._refresh_controles()
        self._refresh_problems()
        # la vue navire dessine les épontilles : elle suit le même calque
        self._refresh_iso(getattr(self.win, "project", None))
        self._refresh_coupe()

    def _refresh_controles(self):
        """Le rappel orange des contrôles éteints.

        Un plan « valide » parce qu'on a éteint le contrôle de hauteur n'est
        pas un plan valide : la ligne le dit, à côté du compteur, tant que
        l'interrupteur est ouvert."""
        eteints = self.view.calques.controles_eteints()
        if not eteints:
            self.lbl_controles.setText("")
            self.lbl_controles.setToolTip("")
            return
        self.lbl_controles.setText(
            f"<span style='color:{theme.WARN}'>⚠ "
            + " · ".join(f"{nom} désactivé" for nom in eteints) + "</span>")
        self.lbl_controles.setToolTip(
            "Ces dépassements ne sont plus comptés ni surlignés sur CE poste "
            "(réglage de session, menu « Calques »). Ils ne sont pas pour "
            "autant autorisés : le solveur respecte toujours la charge "
            "admissible et la hauteur libre, et le rapport de stabilité dit "
            "ce qu'il dit.")

    # ------------------------------------------------------- les problèmes
    def problemes_du_navire(self):
        """TOUS les défauts du plan, tous ponts et toutes cales confondus :
        [(pont, cale, colis, calque, motif)].

        Le plan de chargement n'est pas celui du pont qu'on regarde : « Plan
        valide » ne doit pas le dire parce qu'on a changé d'onglet. C'est
        aussi ce que le bord veut DÉROULER : la liste des erreurs, où qu'elles
        soient, avec de quoi aller dessus d'un clic.

        Le même moteur que le plan affiché (`raisons_detaillees`), donc les
        mêmes contrôles de session : un calque décoché ne compte pas plus ici
        qu'ailleurs."""
        proj = getattr(self.win, "project", None)
        cond = getattr(self.win, "condition", None)
        if proj is None or cond is None:
            return []
        en_place = self.view.epontilles_en_place()
        out = []
        for deck in proj.sorted_decks():
            for cap in deck.capacities:
                if cap.kind == KIND_CONTOUR or len(cap.points) < 3:
                    continue
                poses = cond.placements.get(cap.code) or []
                if not poses:
                    continue
                # UN `Hold` par cale et non un par colis : c'est l'essentiel
                # du coût, pour un résultat identique
                hold = _hold_de(cap, en_place)
                for pl in poses:
                    for calque, why in self.view.raisons_detaillees(pl, cap, hold):
                        out.append((deck, cap, pl, calque, why))
        return out

    def _libelle_probleme(self, cap, pl, calque, why):
        """Une ligne du menu des problèmes : la cale, le colis, d'où vient le
        défaut et pourquoi — de quoi décider sans ouvrir le colis."""
        tete = "" if calque == CALQUE_DE_POSE else f"{calque} : "
        return f"{cap.code} · {pl.nom} — {tete}{why}"

    def _garnir_menu_problemes(self):
        """Le menu déroulant du verdict, refait à chaque ouverture.

        À l'ouverture et pas avant : parcourir tout le navire à chaque colis
        posé coûterait cher pour une liste que personne ne regarde."""
        menu = self.menu_problemes
        menu.clear()
        probs = self.problemes_du_navire()
        if not probs:
            a = menu.addAction("Aucun problème sur le plan.")
            a.setEnabled(False)
            return
        courant = None
        for deck, cap, pl, calque, why in probs:
            if deck is not courant:
                courant = deck
                titre = menu.addAction(
                    deck.name + ("" if deck is self.view.deck
                                 else "   (autre pont)"))
                titre.setEnabled(False)
            a = menu.addAction(self._libelle_probleme(cap, pl, calque, why))
            a.setToolTip("Aller sur ce colis : le pont, la cale zoomée, le "
                         "colis sélectionné.")
            a.triggered.connect(
                lambda _c=False, d=deck, c=cap, p=pl: self.aller_au_probleme(d, c, p))

    def aller_au_probleme(self, deck, cap, pl):
        """D'UN CLIC SUR LE COLIS EN DÉFAUT : on change de pont s'il le faut,
        on zoome sur sa cale, on le sélectionne.

        Zoomer sur la cale est ce qui « centre » le colis : la vue cadre alors
        cette cale seule, donc le colis est forcément dans le rectangle
        visible — et il est le seul de la sélection."""
        if deck is not None and deck is not self.view.deck:
            self.choisir_pont(deck)
        if cap is not None:
            self.zoom_in(cap)
        if pl is not None:
            self.view.set_selection([pl])
            self.view.survol = None
        self.view.update()
        if pl is not None and cap is not None:
            motifs = self.view.raisons(pl, cap)
            self._message(f"{cap.code} · {pl.nom}"
                          + (" — " + " · ".join(motifs) if motifs else ""))
        return pl

    def _refresh_problems(self):
        probs = self.problemes_du_navire()
        if probs:
            detail = "\n".join(
                "• " + self._libelle_probleme(cap, pl, calque, why)
                for _d, cap, pl, calque, why in probs[:12])
            if len(probs) > 12:
                detail += f"\n… et {len(probs) - 12} autre(s)"
            # DE QUEL CALQUE VIENT LE DÉFAUT, dans le compteur lui-même :
            # « 5 problème(s) » ne dit pas s'il faut alléger, abaisser ou
            # déplacer, et c'est pourtant la première question qu'on se pose.
            compte = {}
            for _d, _cap, _pl, calque, _why in probs:
                compte[calque] = compte.get(calque, 0) + 1
            par_calque = " · ".join(f"{n} {c}" for c, n in
                                    sorted(compte.items(), key=lambda kv: -kv[1]))
            # pas de chevron dans le texte : le bouton en dessine déjà un
            self.lbl_probs.setText(f"{len(probs)} problème(s)  ({par_calque})")
            self.lbl_probs.setStyleSheet(
                f"QToolButton#verdictPlan {{ color: {theme.DANGER}; "
                f"font-weight: bold; background: transparent; }}")
            self.lbl_probs.setToolTip(
                detail + "\n\nDéroulez la liste : un clic amène sur le colis.")
        else:
            self.lbl_probs.setText("Plan valide")
            self.lbl_probs.setStyleSheet(
                f"QToolButton#verdictPlan {{ color: {theme.OK}; "
                f"background: transparent; }}")
            self.lbl_probs.setToolTip("Aucun colis en défaut, sur aucun pont.")

    # ------------------------------------------------------- édition fine
    def _message(self, texte):
        barre = getattr(self.win, "statusBar", None)
        if callable(barre):
            barre().showMessage(texte, 9000)

    def _changer_poids(self, pl, txt):
        """Poids unitaire saisi : refusé au-delà du maximum du type (D-8 — la
        limite vient du manuel d'assujettissement, pas d'un tracé)."""
        try:
            val = float(txt.replace(",", "."))
        except ValueError:
            return
        if val <= 0:
            return
        cat = getattr(self.win, "catalogue", None)
        t = cat.get(pl.type_code) if (cat is not None and pl.type_code) else None
        refus = t.poids_refuse(val) if t is not None else None
        if refus:
            self._message(f"Poids refusé : {refus}.")
            return
        pl.poids_t = val
        # le poids décide de la charge au m² : les défauts sont à refaire
        self.view.invalider_problemes()

    def _changer_niveaux(self, pl, cap, txt):
        """Empilement saisi, borné comme partout ailleurs : le stack de
        la marchandise et la hauteur libre de la cale À CET ENDROIT (un barrot
        bas au-dessus de la pile compte)."""
        try:
            demande = max(1, int(float(txt.replace(",", "."))))
        except ValueError:
            return
        haut = _hauteur_libre_locale(cap, pl.rect)
        nmax = pl.niveaux_max(haut)
        pl.niveaux = min(demande, nmax)
        # la hauteur de la pile décide du calque « hauteur libre » et de la
        # charge au m² : les défauts sont à refaire
        self.view.invalider_problemes()
        if demande > nmax:
            self._message(
                f"{pl.nom} : {demande} niveaux impossibles — stack {pl.gerbable_max} "
                f"max et {haut:.2f} m libres pour {pl.hauteur_m:.2f} m "
                f"par exemplaire. Limité à {nmax}.")

    # ------------------------------------------------------------- actions
    def _on_view_changed(self):
        self._refresh_lots()
        self._refresh_resume()
        self.changed.emit()

    def _on_view_selection(self, pl):
        self._refresh_resume()
        dlg = getattr(self, "_posees", None)
        if dlg is not None and dlg.isVisible():
            dlg.suivre_selection()

    def remove_selected(self):
        """Le bouton « Retirer » : la sélection repart au manifeste. Le compte
        exact est dit par la vue (`dire_retrait`), qui sait ce qui est de la
        marchandise et ce qui est du bord."""
        self.view.retirer_selection()

    def _dire_la_cale_survolee(self, cap):
        """Le pointeur entre dans le vide d'une cale : on dit son nom et le
        geste qui ouvre son plan.

        « Il est difficile de tomber sur la bonne cale » : on ne demande plus
        de la deviner dans une liste, on la nomme au moment où le pointeur est
        dessus et où le double-clic l'ouvrirait."""
        if cap is None:
            return
        nom = " ".join(m for m in (cap.code, cap.name or "") if m)
        self._message(f"{nom} — double-clic : zoomer ; clic droit : le menu de la cale.")

    # ------------------------------------------------- le menu d'une cale
    def menu_de_la_cale(self, cap, point_ecran):
        """Le MENU DU CLIC DROIT dans le vide d'une cale (D-65).

        Ce qu'on fait à UNE cale, réuni là où on la regarde : zoomer, la
        remplir automatiquement (le répartiteur s'ouvre déjà réglé sur elle
        seule), tout sélectionner, la vider, ouvrir son plan de cale. Le
        libellé de chaque entrée nomme la cale : on ne vide pas « la cale »,
        on vide « 2040 », et la barre d'état répète ce qui a été fait."""
        if cap is None:
            return None
        poses = list(self.view.placements(cap))
        n = len(poses)
        menu = QMenu(self)
        titre = menu.addAction(f"{cap.code} · {cap.name or ''} — "
                               f"{self._taux_occupation(cap) * 100:.0f} % occupée, "
                               + ("aucun colis" if not n else
                                  f"{n} colis" if n > 1 else "1 colis"))
        titre.setEnabled(False)
        menu.addSeparator()
        if self.view.zoom_hold is cap:
            menu.addAction("Revenir au pont entier", self.zoom_out)
        else:
            menu.addAction(f"Zoomer sur {cap.code}", lambda: self.zoom_in(cap))
        menu.addSeparator()
        a = menu.addAction(f"Répartir automatiquement dans {cap.code}…",
                           lambda: self._solve(cales=[cap.code]))
        a.setToolTip("Le répartiteur, déjà réglé pour ne garnir que cette cale")
        menu.addAction(f"Plan de cale de {cap.code}…",
                       lambda: self.ouvrir_plan_de_cale(cap))
        menu.addSeparator()
        a = menu.addAction(f"Sélectionner les colis de {cap.code}",
                           lambda: self.selectionner_cale(cap))
        a.setEnabled(n > 0)
        a = menu.addAction(f"Vider {cap.code} — les colis retournent au manifeste",
                           lambda: self.vider_cale(cap))
        a.setEnabled(n > 0)
        self.menu_cale_ouvert = menu          # pour les tests : le dernier menu
        if point_ecran is not None:
            menu.popup(point_ecran)
        return menu

    def selectionner_cale(self, cap):
        """Toute la cale devient la sélection : déplacer, tourner ou retirer
        d'un bloc ce qui s'y trouve."""
        poses = list(self.view.placements(cap))
        self.view.set_selection(poses)
        self._message(f"{cap.code} : {len(poses)} colis sélectionnés.")
        return len(poses)

    def vider_cale(self, cap):
        """Vide UNE cale : ses colis repartent au manifeste. Pas de question
        posée — Ctrl+Z défait le geste (D-61), et c'est dit."""
        poses = list(self.view.placements(cap))
        if not poses:
            return 0
        self.view.set_selection(poses)
        n = self.view.retirer_selection()
        self._message(f"{cap.code} vidée : {n} colis de retour au manifeste "
                      "(Ctrl+Z pour les remettre).")
        return n

    def ouvrir_plan_de_cale(self, cap):
        """Le plan de cale d'UNE cale désignée : double-clic sur elle.

        La fenêtre reste ce qu'elle est — l'éditeur d'une cale seule, avec son
        « Remplir » —, mais on n'y arrive plus par un bouton qui demandait de
        deviner sur quelle cale il allait tomber : on la montre du doigt."""
        if cap is None:
            return None
        from .stow_editor import StowEditorDialog
        cond = self.win.condition
        dlg = StowEditorDialog(self.win, cap, cond,
                               getattr(self.win, "catalogue", None), self)
        ok = bool(dlg.exec())
        # les colis se lisent d'abord, la fenêtre se détruit ensuite : elle a
        # ce panneau pour parent et resterait sinon vivante à chaque cale
        # ouverte, une par une, pour toute la session
        poses = dlg.values() if ok else None
        dlg.deleteLater()
        if ok:
            cond.placements[cap.code] = poses
            self._refresh_impl()
            self.changed.emit()
        return cap

    def cale_de_reference(self):
        """La cale sur laquelle le plan de cale s'ouvre à défaut de doigt
        pointé : celle qu'on a zoomée, sinon celle du colis choisi, sinon la
        première du pont. Sert aux appels d'ailleurs (récapitulatif)."""
        cap = self.view.zoom_hold
        if cap is None:
            pl = self.view.selection[0] if self.view.selection else None
            cap = self.view.hold_of(pl) if pl is not None else None
        if cap is None:
            holds = self.view.holds()
            cap = holds[0] if holds else None
        return cap

    def open_hold_editor(self):
        """Plan détaillé d'une cale, sans doigt pointé (récapitulatif,
        `MainWindow.open_hold`) : on prend la cale de référence."""
        return self.ouvrir_plan_de_cale(self.cale_de_reference())
