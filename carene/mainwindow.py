# -*- coding: utf-8 -*-
"""Fenêtre principale : le poste de travail chargement & stabilité.

Elle ne contient plus aucun outil de création : le calage des plans et l'import
des tables vivent dans la fenêtre « Création du navire »
(`carene.ship_editor`), elle-même ouvrant l'éditeur de plans
(`carene.plan_editor`) pour la géométrie.

Ici on fait le travail quotidien, et rien d'autre :

- un **bandeau permanent** (l'en-tête) : les gestes du jour, navire et point
  en cours, les trois boutons de vue, et les chiffres qui décident
  (déplacement, TE AR/AV, assiette, gîte, GM corrigé, verdict). Il passe à
  la ligne quand la fenêtre est étroite au lieu de perdre un morceau
  (`carene.flux`, D-67) ;
- **trois vues**, une par métier, chacune emportant ses panneaux :
  « Liquides » (relevé + situation 3D), « Chargement » (condition + plan de
  pont + tableau synchronisé), « Stabilité » (flottaison, courbe GZ,
  critères). Plus de colonne permanente qui ne sert qu'à une partie du
  travail.

Le recalcul est automatique à chaque modification de la condition.

L'application est mono-navire (voir `carene.app_paths`) : elle ouvre au
démarrage l'unique navire de l'installation.
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl
from PySide6.QtGui import (QAction, QDesktopServices, QKeySequence,
                           QTextCursor)
from PySide6.QtWidgets import (
    QDialog,
    QPlainTextEdit,
    QGraphicsView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import app_paths, journal_technique, theme
from .condition_model import (
    LoadingCondition,
    conditions_dir,
    list_conditions,
    renommer_type_code,
    safe_filename,
)
from .condition_panel import ConditionPanel
from .cargo_panel import CargoPanel
from .journal import Journal, Point, PointFige
from . import ports
from .journal_panel import JournalPanel
from .bilan_panel import BilanPanel
from .liquids_panel import LiquidsPanel
from .project import Project
from .results_panel import ResultsPanel

CORE_ERROR = None
try:
    from .core import (annulation, criteria, hydrostatics, reglements,
                       stability, weather)
    from .core.navire import Navire
    from .core.voilure import CRITERE_METEO
except Exception as e:                       # pragma: no cover
    Navire = None
    CORE_ERROR = e


def _te_val(eq, colonne, defaut):
    v = (eq.hydro or {}).get(colonne)
    return defaut if v is None else float(v)


def _te(eq, colonne):
    """Tirant d'eau lu directement dans la table hydrostatique du navire.

    Les colonnes TE_AR_m / TE_AV_m viennent du dossier : rien n'est reconstruit
    à partir de l'assiette. Si le navire n'en fournit pas, on n'invente pas —
    on affiche un tiret."""
    v = (eq.hydro or {}).get(colonne)
    return "—" if v is None else f"{float(v):.2f} m"


def _pill(text="", tone="todo"):
    lbl = QLabel(text)
    lbl.setObjectName("pill")
    lbl.setProperty("tone", tone)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return lbl


class _Figure(QWidget):
    """Un chiffre du bandeau : intitulé discret, valeur lisible de loin."""

    def __init__(self, titre, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        self.titre = QLabel(titre)
        self.value = QLabel("—")
        self.retheme()
        lay.addWidget(self.titre)
        lay.addWidget(self.value)

    def retheme(self):
        """Relit les couleurs du thème : appelé au changement clair/sombre,
        sans quoi l'intitulé garde la couleur du thème de départ."""
        self.titre.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10px; "
                                 "letter-spacing: 1px; background: transparent;")
        self.value.setStyleSheet(
            "font-size: 14px; font-weight: bold; background: transparent;")

    def set(self, text):
        self.value.setText(text)


class _ChoixVoilure(QWidget):
    """Le sélecteur de voilure du bandeau, à côté du verdict.

    POURQUOI là et pas dans le panneau Stabilité : la voilure décide de quel
    critère de vent s'applique, donc du verdict lui-même. Le bord doit voir
    d'un seul regard « Full sails » et « NON CONFORME » — les mettre à deux
    endroits différents de l'écran, c'est la question « non conforme dans
    quelle voilure ? » à chaque fois.

    Sans configuration de voilure au dossier, il ne se cache pas : il dit que
    le dossier n'en décrit pas. Un bord dont le recueil parle de « full sails »
    et qui ne voit rien à l'écran ne peut pas savoir si c'est le logiciel qui
    ignore la question ou son navire qui n'a pas de voiles.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        self.titre = QLabel("VOILURE")
        self.combo = QComboBox()
        # COMPACT, quoi que disent les libellés du dossier (« Intermediate
        # sails (voilure intermédiaire) » fait 260 px) : le bandeau est un seul
        # bloc dans la barre d'outils, et Qt le CACHE EN ENTIER dès qu'il ne
        # tient plus dans la largeur de la fenêtre — plus de navire, plus de
        # verdict, rien. Un libellé tronqué dans la liste, avec son texte
        # complet en infobulle, vaut mieux qu'un bandeau disparu.
        self.combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(11)
        self.combo.setMinimumWidth(120)
        self.combo.setMaximumWidth(150)
        self.lbl_absent = QLabel("le dossier n'en décrit pas")
        self.lbl_absent.setToolTip(
            "Voilure : le dossier n'en décrit pas. Ajoutez « profils_vent » "
            "à navire.json et un fichier profils_vent.csv au dossier du "
            "navire pour que les critères de vent soient évalués.")
        self.lbl_absent.setVisible(False)
        self.retheme()
        lay.addWidget(self.titre)
        lay.addWidget(self.combo)
        lay.addWidget(self.lbl_absent)

    def retheme(self):
        self.titre.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10px; "
                                 "letter-spacing: 1px; background: transparent;")
        self.lbl_absent.setStyleSheet(
            f"color: {theme.TEXT_DIM}; font-size: 12px; background: transparent;")

    def peupler(self, profils_vent, courant):
        """Range les configurations du navire dans la liste, sans déclencher de
        recalcul (`blockSignals`) : c'est l'appelant qui décide quand
        recalculer, une fois la liste et le point remis d'accord."""
        self.combo.blockSignals(True)
        try:
            self.combo.clear()
            profils = list(getattr(profils_vent, "profils", []) or [])
            for p in profils:
                self.combo.addItem(p["nom"], p["id"])
                if p.get("description"):
                    self.combo.setItemData(
                        self.combo.count() - 1, p["description"],
                        Qt.ItemDataRole.ToolTipRole)
            self.combo.setVisible(bool(profils))
            self.lbl_absent.setVisible(not profils)
            if profils:
                i = self.combo.findData(courant)
                self.combo.setCurrentIndex(max(0, i))
                self.combo.setToolTip(
                    "La voilure portée à ce point : elle décide du critère de "
                    "vent appliqué (météo IS2008 voiles enroulées, NR500 "
                    "voilier sous voile) et de la surface exposée au vent.")
        finally:
            self.combo.blockSignals(False)

    def courant(self):
        """L'identifiant choisi, ou None si le dossier n'en décrit aucun."""
        return self.combo.currentData() if self.combo.count() else None


VUE_JOURNAL, VUE_CAPACITES, VUE_CHARGEMENT, VUE_STABILITE = range(4)
# la donnée de la dernière entrée du sélecteur de point : « Nouveau point… »
NOUVEAU_POINT = "__nouveau_point__"


class _NavireBascule(Exception):
    """Signal interne : open_ship() a été relancé sur un autre dossier."""


# La page de l'aide qu'ouvre l'écran « aucun navire » (D-74) : le parcours
# complet depuis une installation vierge — pas le sommaire.
PAGE_AIDE_VIERGE = "creation_du_navire.md"


class MainWindow(QMainWindow):
    """Poste de travail chargement & stabilité (mono-navire)."""

    # Les questions bloquantes (« Enregistrer ? », avertissements) se coupent
    # d'un drapeau : les tests hors écran et les captures ne doivent jamais
    # attendre un clic. Voir `_confirmations_actives`.
    demander_confirmations = True

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Carène — chargement et stabilité")
        self.resize(1560, 960)

        self.project = Project()
        self.journal = None            # Journal du navire ouvert
        self.point = Point()           # le point courant du journal
        self.nav = None
        self.nav_error = None
        self.ship_editor = None
        self.plan_editor = None
        self.catalogue = None
        self.inventaire_bord = None   # les engins du navire (equipements_bord.json)
        self.ports = None             # les escales du navire (ports.json)
        self._dirty = False        # le point courant a-t-il changé depuis l'enregistrement ?
        self._gite = None          # gîte d'équilibre, None tant qu'inconnue
        # ANNULER / REFAIRE (D-61) : une pile d'états du chargement, alimentée
        # après chaque calcul. `_etat_annulation` est l'état de référence (le
        # dernier vu) ; `_gel_annulation` > 0 pendant qu'on restaure ou qu'on
        # ouvre un point — ce ne sont pas des gestes de l'officier.
        self.annulation = annulation.PileAnnulation()
        self._etat_annulation = None
        self._gel_annulation = 0
        # Réglages du dernier passage du répartiteur (`SolverDialog.run`), que
        # le plan de cale relit pour son bouton « Remplir » : le même moteur
        # doit poser la même chose des deux côtés. None tant qu'il n'a pas
        # tourné — le plan de cale remplit alors « au plus », comme avant.
        self.derniers_reglages_solveur = None
        # le verrou DU NAVIRE (D-55) : pris dans `open_ship`, battu toutes
        # les 30 s, rendu à la fermeture. `lecture_seule` : un autre poste
        # tient le navire, on ne fait que regarder.
        self.verrou_navire = None
        self.lecture_seule = False

        self._build_actions()
        self._build_center()
        self._build_docks()
        from . import MENTION
        self.statusBar().showMessage(f"{MENTION} — prêt.")
        self.open_ship()
        from .core.verrou_navire import BATTEMENT_S
        self._minuterie_verrou = QTimer(self)
        self._minuterie_verrou.setInterval(BATTEMENT_S * 1000)
        self._minuterie_verrou.timeout.connect(self._battre_verrou_navire)
        self._minuterie_verrou.start()

    # ------------------------------------------------------------------ UI
    def _build_actions(self):
        # PLUS DE BARRE D'OUTILS QT (D-67) : elle cachait en entier tout ce qui
        # ne tenait plus dans la largeur de la fenêtre. Les gestes du jour et
        # le bandeau vivent dans un EN-TÊTE qui passe à la ligne (`_build_
        # entete`), construit une fois les actions et les menus en place.
        m_file = self.menuBar().addMenu("&Chargement")
        # LE JOURNAL A SON MENU (D-68) : « le plus simple pour accéder au
        # journal reste par le menu du haut, et devrait permettre : voir les
        # points, ajouter un point, ouvrir le journal ». Ce qui touche aux
        # points quitte donc le menu Chargement, qui ne garde que ce qu'on
        # fait AU chargement.
        m_journal = self.menuBar().addMenu("&Journal")
        m_ship = self.menuBar().addMenu("&Navire")
        m_export = self.menuBar().addMenu("&Exporter")
        m_view = self.menuBar().addMenu("&Affichage")
        m_help = self.menuBar().addMenu("&Aide")

        # (action, nom d'icône) : les icônes sont redessinées au changement de
        # thème, sinon elles gardent les couleurs du thème de départ
        self._actions_icones = []
        # les actions qui ont un BOUTON dans l'en-tête, dans l'ordre
        self._actions_entete = []

        def act(text, slot, sc=None, menu=None, toolbar=False, icon=None,
                tip=None, check=False, court=None):
            a = QAction(text, self)
            # `court` : le mot du BOUTON de l'en-tête, quand celui du menu est
            # trop long pour y tenir (« Enregistrer le point » → « Enregistrer »)
            if court:
                a.setIconText(court)
            if icon:
                a.setIcon(theme.icon(icon))
                self._actions_icones.append((a, icon))
            if sc:
                a.setShortcut(QKeySequence(sc))
                a.setToolTip(f"{tip or text}  ({sc})")
            elif tip:
                a.setToolTip(tip)
            a.setCheckable(check)
            if check:
                a.toggled.connect(slot)
            else:
                # `triggered(bool)` passe son booléen au slot : pour
                # new_point(depuis=None, …) il devenait le point source
                # (depuis=False → plantage). On l'avale pour tous les slots.
                a.triggered.connect(lambda *_a, s=slot: s())
            if menu is not None:
                menu.addAction(a)
            if toolbar:
                self._actions_entete.append(a)
            return a

        # ANNULER / REFAIRE, en tête du menu où l'on modifie le chargement
        # (D-61). Les libellés disent ce qu'ils vont défaire : ils sont
        # réécrits à chaque changement par `_refresh_annulation`.
        self.act_annuler = act("Annuler", self.annuler, "Ctrl+Z", menu=m_file,
                               icon="undo",
                               tip="Revenir sur le dernier changement du chargement")
        self.act_refaire = act("Refaire", self.refaire, "Ctrl+Shift+Z", menu=m_file,
                               tip="Rétablir ce qui vient d'être annulé")
        # Ctrl+Y en plus : c'est le refaire de Windows, et le bord y va d'instinct
        self.act_refaire_bis = QAction("Refaire", self)
        self.act_refaire_bis.setShortcut(QKeySequence("Ctrl+Y"))
        self.act_refaire_bis.triggered.connect(lambda *_a: self.refaire())
        self.addAction(self.act_refaire_bis)
        self.act_annuler.setEnabled(False)
        self.act_refaire.setEnabled(False)
        m_file.addSeparator()
        # Les brouillons appartiennent au POINT (ils s'archivent avec lui) :
        # leur place est dans le menu Chargement, et non dans le menu Navire.
        # La barre de la vue Chargement a le même bouton.
        act("Brouillons du plan de chargement…", self.open_brouillons, menu=m_file,
            tip="Plusieurs plans de cargaison pour ce point : les garder côte à côte, "
                "en charger un, en valider un")
        m_file.addSeparator()

        # ---- LE MENU JOURNAL (D-68) ----------------------------------------
        # Plus de « cas de chargement » : un JOURNAL de points. Un nouveau
        # point est la copie intégrale du courant ; un point figé ne bouge plus.
        act("Voir le journal", lambda: self.tabs.setCurrentIndex(VUE_JOURNAL), "F2",
            menu=m_journal, tip="La chronologie des points : ouvrir, figer, comparer")
        # LA LISTE DES POINTS, dans le menu même : « voir les points ». Elle
        # se refait à l'ouverture du sous-menu, le journal ayant pu changer.
        self.menu_points = m_journal.addMenu("Ouvrir le point")
        self.menu_points.aboutToShow.connect(self._garnir_menu_points)
        m_journal.addSeparator()
        # L'ICÔNE BATEAU DE LA BARRE, C'ÉTAIT CE GESTE-CI. « Ça crée des
        # points dans le journal ? Je ne vois pas trop son utilité » : une
        # icône seule, à côté du sélecteur de point, se cliquait par erreur et
        # ouvrait un point de plus à chaque fois. Le geste reste — c'est celui
        # de chaque escale — mais il se fait par ce menu, par Ctrl+N ou par le
        # sélecteur du bandeau, avec son nom écrit en toutes lettres.
        act("Nouveau point (copie du courant)", self.new_point, "Ctrl+N", menu=m_journal,
            tip="Ouvrir le point suivant du journal, copie intégrale de celui-ci")
        act("Enregistrer le point", self.save_point, "Ctrl+S", menu=m_journal,
            toolbar=True, icon="save", court="Enregistrer",
            tip="Enregistrer le point courant dans le journal")
        act("Figer ce point…", self.freeze_point, "Ctrl+Shift+S", menu=m_journal,
            tip="Archiver l'état du navire à cet instant, verdict compris — définitif")
        m_journal.addSeparator()
        act("Importer un ancien cas de chargement…", self.import_case, menu=m_journal,
            tip="Un cas enregistré avec les versions précédentes devient un point")
        # Ctrl+J ouvrait le journal jusqu'ici : on le garde pour les doigts
        # qui l'ont appris, sans l'afficher
        self.act_journal_bis = QAction("Journal", self)
        self.act_journal_bis.setShortcut(QKeySequence("Ctrl+J"))
        self.act_journal_bis.triggered.connect(
            lambda *_a: self.tabs.setCurrentIndex(VUE_JOURNAL))
        self.addAction(self.act_journal_bis)

        # Le navire se définit une fois pour toutes : sa place est dans le
        # menu, pas dans une barre d'outils dédiée aux gestes quotidiens.
        act("Créer ou modifier le navire…", self.open_ship_editor,
            menu=m_ship,
            tip="Tables, capacités et plans — fenêtre dédiée")
        act("Éditeur de plans…", self.open_plan_editor, menu=m_ship,
            tip="Décalquer les cales, poser les calques de charge, de hauteur et "
                "d'information — rarement, et exprès : ce n'est pas un geste de "
                "chargement")
        act("Catalogue des charges…", self.open_catalogue, "Ctrl+K",
            menu=m_ship,
            tip="Les types de colis du bord : dimensions, poids, stack, couleur")
        act("Matériel du bord…", self.open_equipements, menu=m_ship,
            tip="Les engins du navire : chariot, transpalette — ils pèsent et "
                "occupent la place, ils ne sont pas au manifeste")
        act("Escales du navire…", self.open_ports, menu=m_ship,
            tip="Les ports de la ligne et leur code UN/LOCODE — et la recherche "
                "dans les 17 573 ports du monde")
        act("Épontilles…", lambda: self.cargo_panel.open_epontilles(),
            menu=m_ship,
            tip="Mettre en place ou déposer les épontilles amovibles — elles se "
                "tracent dans « Créer ou modifier le navire… »")
        # EXPORTS ET IMPRESSION : UNE fenêtre pour tout (D-92). Le menu avait
        # quatre entrées qui ouvraient toutes cette même fenêtre, réglée
        # autrement ; la fenêtre coche, prévisualise, imprime et exporte toute
        # la sélection : une entrée suffit, et un bouton au bandeau.
        act("Exporter ou imprimer…", self.open_exports, "Ctrl+E", menu=m_export,
            toolbar=True, icon="print", court="Exporter / imprimer",
            tip="Rapport de stabilité, relevés, plans, feuilles de pointage : "
                "cocher, prévisualiser, imprimer ou exporter (PDF, CSV)")
        # Ctrl+P, le raccourci d'impression de tous les logiciels, ouvre la même
        self.act_imprimer_bis = QAction("Exporter ou imprimer", self)
        self.act_imprimer_bis.setShortcut(QKeySequence("Ctrl+P"))
        self.act_imprimer_bis.triggered.connect(lambda *_a: self.open_exports())
        self.addAction(self.act_imprimer_bis)
        m_ship.addSeparator()
        # La sauvegarde : un zip du dossier du navire (journal, plans, tout)
        # avec son manifeste, que toute version ultérieure relit (D-54).
        act("Exporter une sauvegarde du navire…", self.exporter_sauvegarde,
            menu=m_ship,
            tip="Un zip du navire entier — tables, plans, journal, brouillons — "
                "à mettre sur une clé avant une mise à jour, ou à envoyer")
        act("Importer une sauvegarde…", self.importer_sauvegarde,
            menu=m_ship,
            tip="Reprendre un navire depuis une sauvegarde, de cette version ou "
                "d'une version passée ; le navire en place est mis de côté, "
                "jamais effacé")
        m_ship.addSeparator()
        act("Ouvrir un autre dossier de navire…", self.change_ship_folder, menu=m_ship,
            tip="Choisir le dossier d'un navire (sur ce poste, une clé ou le "
                "NAS) et l'ouvrir à la place de celui-ci — rien n'est déplacé")
        act("Supprimer le navire…", self.delete_ship, menu=m_ship,
            tip="L'application ne gère qu'un navire : le supprimer permet d'en "
                "créer un autre")

        # « Répartir » n'a de sens que devant un plan de chargement : le bouton
        # est dans l'onglet Chargement, le menu et F9 restent pour l'habitude.
        act("Répartir le chargement…", self.open_solver, "F9", menu=m_file,
            tip="Proposer un plan de chargement (premier jet)")
        act("Ballastage…", self.open_ballast, "F8", menu=m_file,
            tip="Chercher la meilleure répartition dans les ballasts")
        # Le relevé de tirants d'eau appartient au POINT, comme le chargement
        # qu'il met à l'épreuve : sa place est dans ce menu, pas dans Navire.
        act("Tirants d'eau relevés…", self.open_tirants, "F7", menu=m_file,
            tip="Comparer les tirants d'eau lus à la coque au chargement "
                "déclaré, et en tirer le poids fictif manquant")
        m_file.addSeparator()
        act("Quitter", self.close, menu=m_file)
        act("Recalculer", self.recompute, "Ctrl+R", menu=m_view, toolbar=True,
            icon="grid", tip="Relancer le calcul d'équilibre et de stabilité")
        act("Capacités", lambda: self.tabs.setCurrentIndex(VUE_CAPACITES), "F3",
            menu=m_view, tip="Relevé des soutes et ballasts")
        act("Chargement", lambda: self.tabs.setCurrentIndex(VUE_CHARGEMENT), "F4",
            menu=m_view, tip="Plan de chargement")
        act("Stabilité", lambda: self.tabs.setCurrentIndex(VUE_STABILITE), "F5",
            menu=m_view, tip="Résultats et critères")
        act("Recadrer la vue", self.recadrer_vue, "F", menu=m_view, toolbar=True,
            icon="fit", court="Recadrer",
            tip="Recadrer la vue en cours (iso des capacités, plan de chargement) — "
                "remet le cadrage et le zoom, sans changer l'angle de la vue iso")
        m_view.addSeparator()
        # LES CALQUES DU PLAN DE CHARGEMENT, ici aussi : la barre du plan les
        # porte, mais on cherche un affichage dans le menu Affichage. Les deux
        # menus cochent les MÊMES cases (le panneau les garnit dès qu'il
        # existe, voir `_garnir_menu_calques`).
        self.menu_calques = m_view.addMenu("Calques du plan de chargement")
        m_view.addSeparator()
        # plus de « Thème sombre » (D-72) : une seule palette, la claire
        self.act_infobulles = act("Infobulles d'aide", self.regler_infobulles,
                                  check=True, menu=m_view)
        self.act_infobulles.setChecked(app_paths.infobulles_actives())
        FiltreInfobulles.installer(app_paths.infobulles_actives())
        # L'aide en tête du menu Aide, et un « ? » dans la barre : c'est là
        # qu'on la cherche. Elle s'ouvre sur le sommaire ; le répartiteur et
        # l'éditeur de plans l'ouvrent, eux, sur leur propre page.
        act("Aide de Carène…", self.ouvrir_aide, "F1", menu=m_help,
            toolbar=True, icon="help", court="Aide",
            tip="Le mode d'emploi : une page par écran, avec la recherche")
        m_help.addSeparator()
        # SIGNALER UN PROBLÈME (D-63) : le bord veut que les ennuis remontent.
        # L'entrée est dans le menu Aide, et l'avertissement du lancement la
        # rappelle — un bogue qu'on ne signale pas ne se corrige pas.
        act("Signaler un problème…", self.open_bug, menu=m_help,
            tip="Écrire au développeur : trois questions, et Carène joint "
                "d'elle-même ce qui tournait et le journal technique")
        act("Vérifier les mises à jour…", self.verifier_mises_a_jour, menu=m_help,
            tip="Demander au serveur des mises à jour s'il existe une version "
                "plus récente de Carène, et l'installer d'un clic — le navire "
                "n'est jamais touché")
        # LES MISES À JOUR (D-70), toutes au même endroit (D-92) : la case du
        # lancement était seule dans Affichage, loin de ses deux sœurs
        self.act_maj_lancement = act(
            "Vérifier les mises à jour au lancement", self.regler_maj_lancement,
            check=True, menu=m_help,
            tip="Au démarrage, Carène demande au serveur des mises à jour s'il "
                "existe une version plus récente — sans réseau, une ligne le dit "
                "et c'est tout")
        self.act_maj_lancement.setChecked(app_paths.verifier_maj_au_lancement())
        act("Serveur des mises à jour…", self.regler_serveur_maj, menu=m_help,
            tip="L'adresse du serveur des mises à jour, et l'identifiant et le "
                "mot de passe de ce poste (gardés par Windows, jamais dans un fichier)")
        act("Journal technique…", self.montrer_journal, menu=m_help,
            tip="Ce que Carène a noté depuis son lancement — à joindre en cas "
                "de problème")
        act("À propos…", self.about, menu=m_help)

        # l'en-tête : les boutons des gestes, puis le bandeau — navire et
        # point, boutons de vue, chiffres, voilure, verdict
        self.entete = self._build_entete()

    def _garnir_menu_calques(self):
        """Le sous-menu Affichage des calques du plan de chargement.

        Il pilote l'objet `Calques` de la vue de pose — le même que le bouton
        « Calques » de la barre du plan : cocher ici décoche là-bas, et l'état
        est retenu d'une session à l'autre (QSettings)."""
        from .cargo_panel import remplir_menu_calques
        menu = getattr(self, "menu_calques", None)
        if menu is None:
            return None
        menu.clear()
        self.actions_calques = remplir_menu_calques(
            menu, self.cargo_panel.view.calques)
        return self.actions_calques

    def _build_center(self):
        self.center = QStackedWidget()

        # page 0 : aucun navire dans cette installation
        empty = QWidget()
        el = QVBoxLayout(empty)
        el.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        col = QVBoxLayout()
        col.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        t = QLabel("Carène")
        t.setStyleSheet("font-size: 30px; font-weight: bold;")
        t.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        col.addWidget(t)
        self.lbl_sous_titre = s = QLabel("Chargement et stabilité")
        s.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 13px;")
        s.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        col.addWidget(s)
        col.addSpacing(30)
        self.lbl_empty = QLabel("Aucun navire n'est encore défini sur ce poste.")
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        col.addWidget(self.lbl_empty)
        col.addSpacing(14)
        self.btn_creer_navire = b = QPushButton("Créer le navire…")
        b.setProperty("accent", "1")
        b.setMinimumWidth(220)
        b.clicked.connect(self.open_ship_editor)
        # le navire est sur un NAS qui ne répond pas (D-77) : on ne propose
        # surtout pas d'en créer un autre, on propose de réessayer
        self.btn_reessayer = QPushButton("Réessayer")
        self.btn_reessayer.setProperty("accent", "1")
        self.btn_reessayer.setMinimumWidth(220)
        self.btn_reessayer.setVisible(False)
        self.btn_reessayer.clicked.connect(lambda *_: self.open_ship())
        # LA PORTE VERS L'AIDE (D-74) : celui qui lance Carène pour la
        # première fois n'a ni navire ni manuel sous les yeux, et « Créer le
        # navire… » ouvre seize étapes d'un coup. Le second bouton ouvre
        # l'aide DROIT SUR le parcours « Recréer le navire depuis un logiciel
        # vierge » — pas sur le sommaire, où il faudrait encore deviner quelle
        # page lire. F1 reste le chemin vers le sommaire.
        self.btn_aide_vierge = ba = QPushButton("Lire d'abord l'aide…")
        ba.setProperty("ghost", "1")
        ba.setMinimumWidth(220)
        ba.setToolTip("Ouvre l'aide sur « Recréer le navire depuis un "
                      "logiciel vierge » : ce qu'il faut sous la main, "
                      "et les étapes dans l'ordre. F1 ouvre le sommaire.")
        ba.clicked.connect(lambda *_: self.ouvrir_aide(PAGE_AIDE_VIERGE))
        brow = QHBoxLayout()
        brow.setSpacing(10)
        brow.addStretch(1)
        brow.addWidget(b)
        brow.addWidget(self.btn_reessayer)
        brow.addWidget(ba)
        brow.addStretch(1)
        col.addLayout(brow)
        col.addSpacing(22)
        note = QLabel("Cette installation ne gère qu'un seul navire.\n"
                      "Tables, capacités et plans se saisissent dans la "
                      "fenêtre dédiée ;\n"
                      "l'aide en donne le parcours, étape par étape.")
        note.setObjectName("hint")
        note.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        col.addWidget(note)
        row.addLayout(col)
        row.addStretch(1)
        el.addLayout(row)
        el.addStretch(1)
        self.center.addWidget(empty)

        # page 1 : les trois vues métier, pilotées par les boutons du bandeau.
        # Chaque vue emporte ses propres panneaux latéraux : la condition de
        # chargement n'a de sens que devant le plan de chargement, les
        # résultats détaillés n'ont de sens que dans la vue Stabilité — plus
        # de colonne permanente qui ne sert qu'à une partie du travail.
        self.liquids_panel = LiquidsPanel(self)
        self.liquids_panel.changed.connect(self.on_condition_changed)
        self.cargo_panel = CargoPanel(self)
        self.cargo_panel.changed.connect(self.on_loading_changed)
        self._garnir_menu_calques()
        # le récapitulatif reste construit — le catalogue et le manifeste y
        # puisent — mais il n'occupe plus la vue Chargement
        self.condition_panel = ConditionPanel(self)
        self.condition_panel.changed.connect(self.on_condition_changed)
        self.condition_panel.hold_activated.connect(self.open_hold)
        self.results_panel = ResultsPanel()
        self.journal_panel = JournalPanel(self)
        self.journal_panel.changed.connect(self._on_journal_edit)

        # vue Chargement : le plan en grand, l'iso et la coupe à droite. Le
        # manifeste, le catalogue et la liste des charges posées s'ouvrent en
        # fenêtres depuis sa barre — on ne les consulte que par moments, et le
        # plan mérite toute la largeur.
        vue_chargement = self.cargo_panel

        # vue Stabilité : les résultats complets, en pleine largeur
        vue_stab = self._build_vue_stabilite()

        # Le Journal en tête : on choisit d'abord SUR QUEL POINT on travaille,
        # ensuite on relève, on charge, on vérifie.
        self.tabs = QStackedWidget()
        self.tabs.addWidget(self.journal_panel)     # 0 — Journal
        self.tabs.addWidget(self.liquids_panel)     # 1 — Capacités
        self.tabs.addWidget(vue_chargement)         # 2 — Chargement
        self.tabs.addWidget(vue_stab)               # 3 — Stabilité
        self.tabs.currentChanged.connect(self._sync_boutons_vue)
        self.center.addWidget(self.tabs)

        # L'EN-TÊTE AU-DESSUS DE TOUT, dans le widget central et non dans une
        # barre d'outils (D-67) : c'est ce qui lui permet de passer à la ligne
        # au lieu de disparaître quand la fenêtre est étroite.
        corps = QWidget()
        vl = QVBoxLayout(corps)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)
        vl.addWidget(self.entete)
        vl.addWidget(self.center, 1)
        self.setCentralWidget(corps)
        self.tabs.setCurrentIndex(VUE_CHARGEMENT)

    def _build_vue_stabilite(self):
        """La vue « Stabilité » : tout ce qui est résultat et calcul.

        Le panneau de résultats (flottaison, courbe GZ, critères) y respire en
        colonnes au lieu d'être comprimé dans un dock latéral."""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        titre = QLabel("STABILITÉ — résultats du point en cours")
        titre.setObjectName("viewHeader")
        lay.addWidget(titre)
        lay.addWidget(self._build_barre_stabilite())
        from . import AVERTISSEMENT
        avert = QLabel("⚠ " + AVERTISSEMENT)
        avert.setObjectName("avertissement")
        avert.setWordWrap(True)
        avert.setContentsMargins(10, 3, 10, 3)
        lay.addWidget(avert)
        self.results_panel.setMinimumWidth(0)
        # le bilan des poids à gauche (ce que le calcul additionne), les
        # résultats à droite (ce qu'il en sort)
        self.bilan_panel = BilanPanel(self)
        self.bilan_panel.setMinimumWidth(640)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.bilan_panel)
        split.addWidget(self.results_panel)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([760, 1000])
        # en tête, la situation en un coup d'œil : profil avec la flottaison
        # et les tirants d'eau, coupe au maître avec K, B, G, G′, M et la gîte
        from .profil_view import ProfilView
        self.profil = ProfilView(self)
        self.profil.setMinimumHeight(170)
        haut = QSplitter(Qt.Orientation.Vertical)
        haut.addWidget(self.profil)
        haut.addWidget(split)
        haut.setStretchFactor(0, 0)
        haut.setStretchFactor(1, 1)
        haut.setSizes([240, 700])
        lay.addWidget(haut, 1)
        return w

    def _build_barre_stabilite(self):
        """LA BARRE DE LA VUE STABILITÉ (D-66) : « dans Stabilité, on devrait
        avoir un bandeau, comme dans Chargement, avec tout ce qui touche au
        rapport de stab (tirant d'eau relevé, etc.) ».

        Même facture que la barre du plan : des groupes sous leur étiquette,
        rangés par question posée, qui passent à la ligne sur une fenêtre
        étroite. RELEVÉ (ce que la coque dit vraiment), CALCUL (ce qu'on lui
        demande), DOSSIER (ce qu'on en sort), et à droite l'ÉTAT : combien de
        critères tiennent. Tout ce qui est ici existe aussi au menu et au
        clavier ; la barre le met sous les yeux, au moment où l'on regarde
        les résultats."""
        from .flux import Rangee
        from .cargo_panel import _etiquette_groupe, _separateur_barre
        bar = QFrame()
        bar.setObjectName("stabBar")
        bar.setStyleSheet(
            f"QFrame#stabBar {{ background: {theme.SURFACE}; "
            f"border-bottom: 1px solid {theme.BORDER_SOFT}; }}")
        rangee = Rangee(bar)
        self.groupes_barre_stab = {}

        def groupe(nom, premier=False):
            lbl = _etiquette_groupe(nom)
            rangee.groupe(lbl, None if premier else _separateur_barre())
            self.groupes_barre_stab[nom] = lbl

        def bouton(texte, slot, aide, accent=False):
            b = QPushButton(texte)
            b.setProperty("accent" if accent else "ghost", "1")
            b.setToolTip(aide)
            b.clicked.connect(lambda *_a: slot())
            rangee.addWidget(b)
            return b

        # ---- RELEVÉ : ce que la coque dit, confronté au calcul (D-60)
        groupe("RELEVÉ", premier=True)
        self.btn_tirants = bouton(
            "Tirants d'eau relevés…", self.open_tirants,
            "Comparer les tirants d'eau lus aux marques au chargement déclaré, "
            "et en tirer le poids fictif qui manque — combien, et où (F7).",
            accent=True)
        self.lbl_tirants = QLabel("")
        self.lbl_tirants.setStyleSheet("background: transparent;")
        self.lbl_tirants.setToolTip(
            "Le poids fictif posé par le dernier relevé de tirants d'eau, s'il "
            "y en a un : il compte dans tout ce qui s'affiche ici et dans le "
            "dossier de stabilité, et il se retire d'un clic.")
        rangee.addWidget(self.lbl_tirants)
        self.btn_sans_fictif = bouton(
            "Retirer le poids fictif", self.retirer_poids_fictif,
            "Ôter le poids fictif du relevé de tirants d'eau : on revient au "
            "chargement déclaré seul (Ctrl+Z le remet).")
        self.btn_sans_fictif.setVisible(False)

        # ---- CALCUL : ce qu'on demande au calcul
        groupe("CALCUL")
        self.chk_lege_stab = QCheckBox("Navire lège inclus")
        self.chk_lege_stab.setStyleSheet("background: transparent;")
        self.chk_lege_stab.setToolTip(
            "Le poids et le centre de gravité du navire lège (expérience de "
            "stabilité du dossier) entrent dans le calcul. Décoché, on ne "
            "regarde que ce qui est embarqué — pour vérifier un bilan, jamais "
            "pour un verdict.")
        self.chk_lege_stab.toggled.connect(self._on_lege_stab)
        rangee.addWidget(self.chk_lege_stab)
        bouton("Recalculer", self.recompute,
               "Relancer le calcul d'équilibre et de stabilité (Ctrl+R).")
        bouton("Ballastage…", self.open_ballast,
               "Chercher la meilleure répartition dans les ballasts (F8).")

        # ---- DOSSIER : ce qu'on en sort
        groupe("DOSSIER")
        bouton("Exporter ou imprimer…", self.open_exports,
               "Le rapport de stabilité — douze sections, capacités, cargaison, "
               "hydrostatiques, GZ, toutes les voilures — et les autres "
               "documents : cocher, prévisualiser, imprimer, exporter (Ctrl+E).")

        # ---- ÉTAT : ce que ça vaut
        groupe("ÉTAT")
        self.lbl_criteres = QLabel("")
        self.lbl_criteres.setStyleSheet("font-weight: bold; background: transparent;")
        self.lbl_criteres.setToolTip(
            "Les critères tenus sur ceux du dossier, pour la voilure choisie. "
            "Le détail est dans le tableau des critères, plus bas.")
        rangee.addWidget(self.lbl_criteres)
        return bar

    def _on_lege_stab(self, coche):
        """La case « Navire lège inclus » de la barre Stabilité : c'est la
        même donnée que celle du récapitulatif — une seule valeur, deux
        endroits pour la voir."""
        if getattr(self, "_barre_stab_en_cours", False):
            return
        if self.condition.inclure_lege == bool(coche):
            return
        if not self._modification_permise("Inclure ou retirer le navire lège"):
            self._barre_stab_en_cours = True
            try:
                self.chk_lege_stab.setChecked(bool(self.condition.inclure_lege))
            finally:
                self._barre_stab_en_cours = False
            return
        self.condition.inclure_lege = bool(coche)
        self.on_condition_changed()

    def _poids_fictifs(self):
        """Les poids fictifs posés par le relevé de tirants d'eau (D-60)."""
        from .core.tirants_releves import NOM_POIDS
        return [e for e in self.condition.extras
                if str(getattr(e, "nom", "")).startswith(NOM_POIDS)]

    def retirer_poids_fictif(self):
        """Ôte le poids fictif du relevé : le chargement redevient le
        chargement déclaré. Ctrl+Z le remet (D-61)."""
        if not self._modification_permise("Retirer le poids fictif"):
            return 0
        fictifs = self._poids_fictifs()
        if not fictifs:
            return 0
        self.condition.extras = [e for e in self.condition.extras
                                 if e not in fictifs]
        self._refresh_saisies()
        self.on_condition_changed()
        self.statusBar().showMessage(
            f"Poids fictif retiré ({sum(e.poids_t for e in fictifs):+.1f} t) : "
            "le calcul repart du chargement déclaré. Ctrl+Z le remet.", 8000)
        return len(fictifs)

    def _refresh_barre_stabilite(self, rep=None):
        """Ce que la barre Stabilité rappelle : le poids fictif en place, le
        navire lège, et le compte des critères tenus."""
        if not hasattr(self, "lbl_tirants"):
            return
        self._barre_stab_en_cours = True
        try:
            self.chk_lege_stab.setChecked(bool(self.condition.inclure_lege))
        finally:
            self._barre_stab_en_cours = False
        fictifs = self._poids_fictifs() if self.condition is not None else []
        if fictifs:
            w = sum(e.poids_t for e in fictifs)
            x = (sum(e.poids_t * e.lcg_m for e in fictifs) / w) if abs(w) > 1e-9 else 0.0
            self.lbl_tirants.setText(
                f"<span style='color:{theme.WARN}'>poids fictif {w:+.1f} t "
                f"à x = {x:.2f} m</span>")
        else:
            self.lbl_tirants.setText(
                f"<span style='color:{theme.TEXT_DIM}'>aucun poids fictif</span>")
        self.btn_sans_fictif.setVisible(bool(fictifs))
        if rep is None or not getattr(rep, "criteres", None):
            self.lbl_criteres.setText("")
            return
        criteres = rep.criteres
        tenus = sum(1 for c in criteres if c.ok and c.evaluable)
        non_eval = sum(1 for c in criteres if not c.evaluable)
        couleur = theme.OK if tenus == len(criteres) else theme.WARN
        texte = f"{tenus} / {len(criteres)} critères tenus"
        if non_eval:
            texte += f" ({non_eval} non évaluable{'s' if non_eval > 1 else ''})"
        self.lbl_criteres.setText(f"<span style='color:{couleur}'>{texte}</span>")

    def _sync_boutons_vue(self, index):
        for vue, b in getattr(self, "boutons_vue", {}).items():
            b.blockSignals(True)
            b.setChecked(vue == index)
            b.blockSignals(False)

    def _build_entete(self):
        """L'EN-TÊTE : les gestes du jour, puis le bandeau, en groupes qui
        passent à la ligne quand la fenêtre est étroite (D-67).

        Chaque groupe est un bloc insécable — un chiffre ne se coupe pas de
        son intitulé, le verdict ne se sépare pas de la voilure qui le
        décide — et c'est entre les groupes que la ligne se rompt. Sur un
        grand écran, une seule ligne comme avant ; sur un portable, deux, et
        rien ne manque."""
        from .flux import FlowLayout
        ent = QFrame()
        ent.setObjectName("entete")
        ent.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        flux = FlowLayout(ent, marge=0, h_espace=10, v_espace=2)
        flux.setContentsMargins(8, 3, 8, 3)

        # ---- les gestes : des boutons AVEC LEUR NOM. « Les boutons du haut, on
        # ne sait pas trop ce qu'ils font » : une icône seule ne se lit pas,
        # et la place gagnée ne valait pas la question.
        gestes = self._groupe_entete()
        self.boutons_gestes = []
        for a in self._actions_entete:
            b = QToolButton()
            b.setDefaultAction(a)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            b.setAutoRaise(True)
            gestes.layout().addWidget(b)
            self.boutons_gestes.append(b)
        flux.addWidget(gestes)
        for groupe in self._build_banner():
            flux.addWidget(groupe)
        return ent

    @staticmethod
    def _groupe_entete(espace=6):
        """Un bloc insécable de l'en-tête."""
        g = QFrame()
        g.setObjectName("groupeEntete")
        g.setStyleSheet("QFrame#groupeEntete { background: transparent; }")
        lay = QHBoxLayout(g)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(espace)
        return g

    def _build_banner(self):
        """Les groupes du bandeau : [navire et point], [vues], [chiffres],
        [voilure et verdict]. Rendus dans l'ordre où ils se lisent."""
        groupes = []

        # ---- le navire et le point : LÀ où l'on choisit sur quoi on travaille
        g = self._groupe_entete(8)
        self.lbl_ship = QLabel("Aucun navire")
        self.lbl_ship.setStyleSheet(
            "font-size: 14px; font-weight: bold; background: transparent;")
        # le point sur lequel on travaille se choisit ici, sans passer par le
        # journal : c'est le geste le plus fréquent d'une escale. Changer de
        # point DEMANDE CONFIRMATION (D-68) : « on risque trop de changer de
        # point de chargement sans s'en rendre compte ». Et la liste finit par
        # « Nouveau point… », le geste qu'on cherche à côté du point courant.
        self.combo_point = QComboBox()
        self.combo_point.setMinimumWidth(240)
        self.combo_point.setMaximumWidth(300)
        self.combo_point.setToolTip("Le point du journal sur lequel on travaille. "
                                    "Changer de point demande confirmation ; "
                                    "F2 ouvre le journal complet.")
        self.combo_point.activated.connect(self._on_combo_point)
        g.layout().addWidget(self.lbl_ship)
        g.layout().addWidget(self.combo_point)
        groupes.append(g)

        # ---- les trois vues métier : des boutons plutôt que des onglets —
        # moins de hauteur perdue, et toujours visibles quel que soit le
        # contexte. Le JOURNAL n'y est plus (D-68) : ce n'est pas une vue du
        # travail mais l'endroit où l'on choisit sur quel point travailler ;
        # il s'ouvre par son menu, par F2, ou par le sélecteur de point.
        g = self._groupe_entete(2)
        # « Capacités » plutôt que « Liquides » : c'est le mot du bord — on y
        # relève soutes, ballasts et caisses, pas un liquide abstrait
        self.boutons_vue = {}
        for vue, texte, sc in ((VUE_CAPACITES, "Capacités", "F3"),
                               (VUE_CHARGEMENT, "Chargement", "F4"),
                               (VUE_STABILITE, "Stabilité", "F5")):
            b = QPushButton(texte)
            b.setCheckable(True)
            b.setProperty("ghost", "1")
            b.setToolTip(f"{texte}  ({sc})")
            b.clicked.connect(lambda _c, ix=vue: self.tabs.setCurrentIndex(ix))
            g.layout().addWidget(b)
            self.boutons_vue[vue] = b
        groupes.append(g)

        # ---- les chiffres. Le bandeau ne porte que les grandeurs qu'on doit
        # avoir sous les yeux en permanence pendant qu'on charge : ce qu'on lit
        # aux marques, ce qui décide de l'accostage, et ce qui dit si le cas
        # tient debout. Tout le détail (TE milieu, KG effectif, GM solide,
        # carènes liquides, LCB/LCF) est dans le panneau Résultats.
        g = self._groupe_entete(12)
        self.fig_depl = _Figure("DÉPLACEMENT")
        self.fig_te_ar = _Figure("TE ARRIÈRE")
        self.fig_te_av = _Figure("TE AVANT")
        self.fig_trim = _Figure("ASSIETTE")
        self.fig_gite = _Figure("GÎTE")
        self.fig_gm = _Figure("GM CORRIGÉ")
        self.figures = (self.fig_depl, self.fig_te_ar, self.fig_te_av,
                        self.fig_trim, self.fig_gite, self.fig_gm)
        for f in self.figures:
            g.layout().addWidget(f)
        groupes.append(g)

        # ---- la voilure et le verdict, ensemble : c'est elle qui décide du
        # critère de vent appliqué, donc du verdict lui-même (voir _ChoixVoilure)
        g = self._groupe_entete(12)
        self.choix_voilure = _ChoixVoilure()
        self.choix_voilure.combo.activated.connect(self._on_voilure_changee)
        g.layout().addWidget(self.choix_voilure)
        self.pill_verdict = _pill("—", "todo")
        g.layout().addWidget(self.pill_verdict)
        # un point figé se lit, il ne se modifie pas : on le dit là où l'œil
        # est en permanence, pas seulement dans la vue Journal
        self.pill_fige = _pill("POINT FIGÉ — lecture seule", "warn")
        self.pill_fige.setToolTip("Ce point est archivé : ses relevés et son chargement "
                                  "ne se modifient plus. Créez un nouveau point (Ctrl+N) "
                                  "pour continuer à partir de lui.")
        self.pill_fige.setVisible(False)
        g.layout().addWidget(self.pill_fige)
        # le navire est ouvert sur un AUTRE poste (verrou du navire, D-55) :
        # on regarde, on n'enregistre pas — et on dit où il est ouvert
        self.pill_lecture_seule = _pill("LECTURE SEULE", "bad")
        self.pill_lecture_seule.setVisible(False)
        g.layout().addWidget(self.pill_lecture_seule)
        groupes.append(g)
        return groupes

    def _build_docks(self):
        """Plus de docks permanents : la condition vit dans la vue Chargement,
        les résultats dans la vue Stabilité (voir _build_center). Le bandeau
        garde les chiffres qui décident, quel que soit l'endroit où l'on est."""

    # ------------------------------------------------------------------ navire
    def open_ship(self):
        """Charge l'unique navire de l'installation, s'il existe."""
        folder = app_paths.ship_folder()
        avis = app_paths.DERNIER_MESSAGE      # dossier configuré disparu, etc.
        self.nav = None
        self.nav_error = None
        self._dirty = False
        if not app_paths.ship_exists(folder):
            self._lacher_verrou_navire()
            self.project = Project(navire_virtuel_path=folder)
            self.journal = None
            self.point = Point()
            self.center.setCurrentIndex(0)
            injoignable = bool(app_paths.NAVIRE_INJOIGNABLE)
            self.btn_reessayer.setVisible(injoignable)
            self.btn_creer_navire.setVisible(not injoignable)
            self.btn_aide_vierge.setVisible(not injoignable)
            if injoignable:
                self.lbl_empty.setText(avis)
            else:
                self.lbl_empty.setText(
                    (avis + "\n\n" if avis else "")
                    + "Aucun navire n'est encore défini sur ce poste."
                    + (f"\n(emplacement attendu : {folder})" if avis else ""))
            self._refresh_banner()
            return
        self.btn_reessayer.setVisible(False)
        self.btn_creer_navire.setVisible(True)
        self.btn_aide_vierge.setVisible(True)
        # LE VERROU DU NAVIRE, avant de lire quoi que ce soit (D-55) : si un
        # autre poste l'a ouvert, on le saura — et on n'écrira pas
        self._prendre_verrou_navire(folder)
        if avis:
            self._signaler("Dossier du navire", avis)
        from .core.cargo_model import Catalogue
        # un geometrie.json ou un catalogue corrompu ne doit pas empêcher
        # l'application de démarrer : on ouvre sans, et on le dit
        try:
            self.project = Project.load_geometry(folder)
        except Exception as e:
            self.project = Project(navire_virtuel_path=folder)
            self._signaler("Plans du navire",
                           f"Les plans du navire ({app_paths.GEOMETRY}) sont illisibles : {e}\n\n"
                           "Le navire est ouvert sans ses plans — les cales tracées et "
                           "le plan de chargement sont indisponibles tant que le fichier "
                           "n'est pas réparé ou refait dans « Créer ou modifier le navire… ».")
        try:
            self.catalogue = Catalogue.load(folder)
        except Exception as e:
            self.catalogue = Catalogue()
            self._signaler("Catalogue des charges",
                           f"Le catalogue des charges est illisible : {e}\n\n"
                           "Un catalogue vide est employé à la place.")
        # les engins du bord (chariot, transpalette) : ils pèsent et occupent
        # la place, mais ne sont pas de la marchandise — ils appartiennent au
        # navire, pas au manifeste (D-18)
        try:
            from .core.cargo_model import InventaireBord
            self.inventaire_bord = InventaireBord.load(folder)
            for msg in getattr(self.inventaire_bord, "messages", []):
                self._signaler("Matériel du bord", msg)
        except Exception as e:
            from .core.cargo_model import InventaireBord
            self.inventaire_bord = InventaireBord()
            self._signaler("Matériel du bord",
                           f"L'inventaire du bord est illisible : {e}\n\n"
                           "Un inventaire vide est employé à la place.")
        if app_paths.has_tables(folder) and Navire is not None:
            try:
                self.nav = Navire.load(folder)
            except Exception as e:
                self.nav_error = str(e)
        self.table_couples = app_paths.table_couples(folder)
        try:
            self._proposer_navire_livre(folder)
        except _NavireBascule:
            return          # open_ship() a déjà été relancé sur le navire livré
        self.journal = Journal(folder)
        dernier = self.journal.dernier()
        # un point abîmé ne disparaît plus en silence (D-77) : relu dans sa
        # copie de secours, ou nommé s'il n'en a pas
        for probleme in self.journal.problemes():
            self._signaler("Journal du navire", probleme)
        if dernier is None:
            self._adopter_point(Point(numero=1))
        elif dernier.fige:
            # le dernier point est archivé : on prépare naturellement le suivant
            self._adopter_point(self.journal.nouveau(dernier))
        else:
            self._adopter_point(dernier)
        # les escales : la ligne du navire, plus tout ce qui a déjà été employé
        # au journal et au manifeste — sans jamais leur inventer de code.
        # APRÈS l'adoption du point : `self.condition` est celle du point
        # courant, et la construire avant revenait à apprendre les escales du
        # point PRÉCÉDENT — celles de l'ancien navire après un changement de
        # navire, et jamais celles du manifeste qu'on vient d'ouvrir.
        self.ports = ports.ports_du_navire(folder, self.condition, self.journal)
        self._ports_dossier = folder
        self.center.setCurrentIndex(1)
        self._refresh_saisies()
        self.recompute()

    @property
    def condition(self):
        """LA condition de chargement : celle du point courant du journal."""
        return self.point.condition

    @condition.setter
    def condition(self, cond):
        self.point.condition = cond

    def _proposer_navire_livre(self, folder):
        """Le dossier ouvert est le navire d'exemple d'une version précédente, sans
        géométrie, alors que le navire livré complet est à côté : on le dit,
        et on propose de basculer — sans le faire dans le dos de l'utilisateur."""
        livre = app_paths.navire_livre()
        if not livre or not app_paths.dossier_incomplet_face_a(folder, livre):
            return
        if getattr(self, "_livre_propose", None) == livre:
            return
        self._livre_propose = livre
        rep = QMessageBox.question(
            self, "Navire livré avec cette version",
            f"Le navire ouvert ({folder}) n'a pas de géométrie : ni cales tracées, ni plans "
            f"calés, ni catalogue du bord.\n\nLe dossier complet du navire d'exemple livré avec cette "
            f"version est ici :\n{livre}\n\nL'ouvrir à la place ? (« Navire → Ouvrir un "
            "autre dossier de navire… » permet d'y revenir à tout moment.)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if rep == QMessageBox.StandardButton.Yes:
            app_paths.set_ship_folder(livre)
            self.open_ship()
            raise _NavireBascule()

    # ------------------------------------------------------ annuler / refaire
    def _etat_du_chargement(self):
        """L'état complet du chargement, tel qu'il s'écrit sur le disque."""
        try:
            return self.condition.to_dict()
        except Exception:                  # pragma: no cover - jamais bloquant
            return None

    def _noter_pour_annulation(self):
        """Appelé après CHAQUE calcul : si le chargement a changé depuis le
        dernier passage, l'état d'avant entre dans la pile (D-61).

        Pourquoi ici et pas à chaque geste : toutes les modifications du point
        — pose, relevé de sonde, poids divers, épontilles, voilure, ballastage,
        répartiteur, brouillon chargé, correction par les tirants d'eau —
        finissent par un recalcul. Un seul point de passage vaut mieux que
        trente appels à ne pas oublier : un geste nouveau est annulable sans
        que personne ait à y penser."""
        etat = self._etat_du_chargement()
        if etat is None:
            return
        if self._gel_annulation or self._etat_annulation is None:
            self._etat_annulation = etat
            self._refresh_annulation()
            return
        if etat == self._etat_annulation:
            return
        self.annulation.pousser(self._etat_annulation,
                                annulation.decrire(self._etat_annulation, etat))
        self._etat_annulation = etat
        self._refresh_annulation()

    def _refresh_annulation(self):
        """Les deux entrées de menu disent ce qu'elles vont défaire."""
        act_a = getattr(self, "act_annuler", None)
        act_r = getattr(self, "act_refaire", None)
        if act_a is None or act_r is None:
            return
        fige = self.point is not None and bool(self.point.fige)
        lecture = bool(getattr(self, "lecture_seule", False))
        peut_a = self.annulation.peut_annuler and not fige and not lecture
        peut_r = self.annulation.peut_refaire and not fige and not lecture
        act_a.setEnabled(peut_a)
        act_r.setEnabled(peut_r)
        act_a.setText("Annuler " + self.annulation.libelle_annuler
                      if peut_a else "Annuler")
        act_r.setText("Refaire " + self.annulation.libelle_refaire
                      if peut_r else "Refaire")

    def annuler(self):
        """Ctrl+Z : revenir sur le dernier changement du chargement."""
        return self._rejouer("annuler")

    def refaire(self):
        """Ctrl+Shift+Z (ou Ctrl+Y) : rétablir ce qui vient d'être annulé."""
        return self._rejouer("refaire")

    def _rejouer(self, sens):
        if self.point is not None and self.point.fige:
            self.statusBar().showMessage(
                "Point figé : c'est une archive, elle ne se modifie pas. "
                "Créez un nouveau point pour reprendre ce chargement.", 8000)
            return None
        if not self._ecriture_permise("Annuler" if sens == "annuler" else "Refaire"):
            return None
        courant = self._etat_du_chargement()
        etat, libelle = (self.annulation.annuler(courant) if sens == "annuler"
                         else self.annulation.refaire(courant))
        if etat is None:
            self.statusBar().showMessage(
                "Rien à annuler." if sens == "annuler" else "Rien à refaire.", 4000)
            return None
        # on restaure SANS rien noter : l'aller-retour n'est pas un changement
        self._gel_annulation += 1
        try:
            self.condition = LoadingCondition.from_dict(etat)
            self.condition.synchroniser_capacites(self.nav)
            self._dirty = True
            self._refresh_saisies()
            self.recompute()
        finally:
            self._gel_annulation -= 1
        self._etat_annulation = self._etat_du_chargement()
        self._refresh_annulation()
        self.statusBar().showMessage(
            ("Annulé : " if sens == "annuler" else "Rétabli : ") + libelle
            + ("  (Ctrl+Shift+Z pour rétablir)" if sens == "annuler" else ""), 8000)
        return libelle

    def _adopter_point(self, point):
        """Le point devient le courant ; sa condition est LA condition."""
        self.point = point
        # UN POINT, UNE HISTOIRE : annuler d'un point à l'autre n'aurait aucun
        # sens (on reprendrait le chargement d'une autre escale). La pile
        # repart de zéro, et l'état de référence est celui qu'on vient d'ouvrir.
        self.annulation.raz()
        self._etat_annulation = None
        self._refresh_annulation()
        self.condition.synchroniser_capacites(self.nav)
        # un point d'avant la v2.10 portait ses engins du bord au milieu du
        # manifeste : ils rejoignent l'inventaire du navire, sans changer un
        # gramme au calcul (D-18)
        try:
            from .equipements_dialog import adopter_migration
            _n, msg = adopter_migration(self, self.condition)
            if msg:
                self.statusBar().showMessage(msg, 12000)
        except Exception:            # pragma: no cover - la reprise ne bloque rien
            pass
        # la fenêtre des brouillons, si elle est ouverte, montre ceux DU POINT :
        # laissée sur l'ancien, elle proposerait de charger le plan d'une autre
        # escale — et la date de modification affichée serait celle d'avant
        dlg = getattr(self, "_brouillons_dlg", None)
        try:
            if dlg is not None and dlg.isVisible():
                dlg.refresh()
        except (RuntimeError, AttributeError):
            pass
        self._dirty = False          # on repart de ce qui est sur le disque

    # ------------------------------------------------------- confirmations
    # ------------------------------------------------------ verrou du navire
    def _prendre_verrou_navire(self, folder):
        """Prend le verrou de CE dossier de navire ; lâche celui d'avant.

        Refusé (un autre poste tient le navire, battement récent) : la
        fenêtre passe en LECTURE SEULE — on regarde, on n'enregistre pas —
        et le bandeau dit où le navire est ouvert. C'est `main()` qui pose
        la question au lancement (quitter ou consulter) ; ici on ne bloque
        rien, `open_ship` est appelé de partout."""
        from . import __version__
        from .core import verrou_navire as VN
        courant = getattr(self, "verrou_navire", None)
        if courant is not None and os.path.normcase(os.path.abspath(courant.dossier)) \
                == os.path.normcase(os.path.abspath(folder)) and courant.tenu \
                and os.path.exists(courant.chemin):
            return True
        self._lacher_verrou_navire()
        v = VN.VerrouNavire(folder, version=__version__, installation=app_paths.DATA_DIR)
        v.prendre()
        self.verrou_navire = v
        self.lecture_seule = not v.tenu
        self._refresh_lecture_seule()
        if v.erreur and v.tenu:
            journal_technique.noter(f"Verrou du navire non écrit ({v.erreur}) : "
                                    "le navire est ouvert sans protection multi-postes.",
                                    "erreur")
        if not v.tenu:
            # un verrou périmé qu'on n'a pas pu effacer (droits, antivirus) n'a
            # pas de détenteur : `v.detenteur.phrase()` faisait tomber la
            # fenêtre à la construction, à chaque lancement (P-8)
            ou = (v.detenteur.phrase() if v.detenteur is not None
                  else f"(verrou inutilisable : {v.erreur or 'raison inconnue'})")
            journal_technique.noter(f"Navire déjà ouvert {ou} : lecture seule.",
                                    "navire")
        elif v.repris_de is not None and v.repris_de.lisible:
            # le poste d'avant n'a pas rendu le navire (plantage, coupure) :
            # on le dit, sans bloquer — c'est une information, pas une faute
            texte = (f"Le verrou du navire était resté {v.repris_de.phrase()} sans "
                     "signe de vie : ce poste l'a repris. Si Carène tournait vraiment "
                     "là-bas, fermez-le avant d'enregistrer ici.")
            journal_technique.noter(texte, "navire")
            self.statusBar().showMessage(texte, 20000)
        return v.tenu

    def _lacher_verrou_navire(self):
        v = getattr(self, "verrou_navire", None)
        if v is not None:
            v.liberer()
        self.verrou_navire = None
        self.lecture_seule = False
        self._refresh_lecture_seule()

    def _battre_verrou_navire(self):
        """Toutes les 30 s : on réécrit le battement. S'il ne s'écrit plus
        parce qu'un autre poste nous a cru mort et a repris le navire, c'est
        lui qui a la main : on passe en lecture seule, et on le dit."""
        v = getattr(self, "verrou_navire", None)
        if v is None or not v.tenu:
            return
        if not v.battre():
            self.lecture_seule = True
            self._refresh_lecture_seule()
            self._signaler("Navire repris par un autre poste",
                           f"Ce navire a été repris {v.detenteur.phrase()} — ce poste "
                           "avait été tenu pour disparu (veille prolongée, câble ?).\n\n"
                           "Carène passe en LECTURE SEULE ici : rien ne s'enregistrera "
                           "plus dans ce journal depuis ce poste. Fermez, puis rouvrez "
                           "quand l'autre poste aura fini.")

    def _refresh_lecture_seule(self):
        pill = getattr(self, "pill_lecture_seule", None)
        if pill is None:
            return
        v = getattr(self, "verrou_navire", None)
        if getattr(self, "lecture_seule", False) and v is not None and v.detenteur is not None:
            # court dans le bandeau (la place y est comptée), tout en infobulle
            d = v.detenteur
            pill.setText("LECTURE SEULE · " + (d.machine or "autre poste"))
            pill.setToolTip("Ce navire est ouvert " + d.phrase() + ".\n"
                            "Rien ne s'enregistre depuis ce poste tant qu'il l'est.")
            pill.setVisible(True)
        else:
            pill.setVisible(False)
        # en lecture seule, Annuler ne doit pas plus marcher que le reste
        self._refresh_annulation()

    def _ecriture_permise(self, quoi="Enregistrer"):
        """La porte par laquelle passe TOUT ce qui écrit dans le dossier du
        navire. En lecture seule, elle dit non — et pourquoi.

        Elle relit aussi le fichier de verrou (D-77) : si un autre poste a
        repris le navire depuis le dernier battement, ce poste passe en
        lecture seule TOUT DE SUITE, avant d'écrire."""
        v = getattr(self, "verrou_navire", None)
        if (not getattr(self, "lecture_seule", False) and v is not None
                and v.tenu and not v.encore_a_nous()):
            self.lecture_seule = True
            self._refresh_lecture_seule()
        if not getattr(self, "lecture_seule", False):
            return True
        v = getattr(self, "verrou_navire", None)
        ou = v.detenteur.phrase() if v is not None and v.detenteur is not None else "ailleurs"
        self._signaler(quoi,
                       f"{quoi} : impossible d'ici, ce navire est ouvert {ou}.\n\n"
                       "Deux Carène qui écrivent dans le même journal s'écrasent l'un "
                       "l'autre : ce poste est en LECTURE SEULE. Fermez Carène sur "
                       "l'autre poste, puis rouvrez celui-ci.")
        return False

    def _modification_permise(self, quoi="Modifier le point"):
        """La porte de TOUT ce qui modifie le chargement du point, où que ce
        soit — barre Stabilité, menus, répartiteur, ballastage, relevé de
        tirants d'eau. Un point FIGÉ est une archive (D-68) ; seuls les
        panneaux Capacités et Chargement le savaient, et la case « lège
        inclus », le poids fictif, F7, F8, F9 modifiaient encore l'archive —
        que le rapport imprimait alors sous la pastille « POINT FIGÉ » (P-7)."""
        if self.point is not None and bool(getattr(self.point, "fige", False)):
            self._signaler(quoi,
                           f"{quoi} : {self.point.titre} est figé — c'est une "
                           "archive, elle ne se modifie plus.\n\n"
                           "Créez un nouveau point (Ctrl+N) : il repart de "
                           "celui-ci, et il se modifie.")
            return False
        return self._ecriture_permise(quoi)

    def _confirmations_actives(self):
        """Peut-on poser une question bloquante ? Non dans les tests hors
        écran (propriété « carene_tests » de l'application) ni quand la
        fenêtre a été réglée pour se taire."""
        app = QApplication.instance()
        if app is not None and app.property("carene_tests"):
            return False
        return bool(self.demander_confirmations)

    def _signaler(self, titre, message):
        """Un avertissement qui ne doit pas bloquer : boîte de dialogue en
        usage normal, barre d'état sinon (tests, captures)."""
        self.statusBar().showMessage(message.split("\n")[0], 20000)
        if self._confirmations_actives():
            QMessageBox.warning(self, titre, message)

    def _confirmer_abandon(self):
        """Le point courant a des modifications non enregistrées : on propose
        de l'enregistrer avant de le quitter. Renvoie False si l'utilisateur
        renonce (Annuler, ou enregistrement échoué)."""
        if not self._dirty or self.journal is None or self.point is None or self.point.fige:
            return True
        if not self._confirmations_actives():
            return True
        rep = QMessageBox.question(
            self, "Modifications non enregistrées",
            f"{self.point.titre} a été modifié depuis son dernier enregistrement.\n\n"
            "L'enregistrer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Yes)
        if rep == QMessageBox.StandardButton.Cancel:
            return False
        if rep == QMessageBox.StandardButton.Yes:
            return self.save_point()
        return True

    # ------------------------------------------------------------- fermeture
    FERMER_ENREGISTRER, FERMER_SANS, FERMER_ANNULER = "enregistrer", "sans", "annuler"

    def _demander_fermeture(self, modifie):
        """La question posée avant de fermer Carène — TOUJOURS, pas seulement
        quand quelque chose n'est pas enregistré (demande du bord : « une
        confirmation lors de la fermeture »). Une croix cliquée par mégarde
        au milieu d'une escale coûtait le plan à l'écran, la vue, le pont, le
        lot en main. Rend l'une des trois constantes FERMER_*."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Fermer Carène")
        titre = self.point.titre if self.point is not None else "aucun point"
        if modifie:
            box.setText(f"Fermer Carène ?\n\n{titre} a été modifié depuis son "
                        "dernier enregistrement.")
            b_oui = box.addButton("Enregistrer et quitter",
                                  QMessageBox.ButtonRole.AcceptRole)
            b_sans = box.addButton("Quitter sans enregistrer",
                                   QMessageBox.ButtonRole.DestructiveRole)
        else:
            box.setText(f"Fermer Carène ?\n\n{titre} est enregistré.")
            b_oui = box.addButton("Quitter", QMessageBox.ButtonRole.AcceptRole)
            b_sans = None
        b_non = box.addButton("Annuler", QMessageBox.ButtonRole.RejectRole)
        # Annuler par défaut : Entrée ou Échap sur une question qu'on n'a
        # pas lue ne doit pas fermer le logiciel
        box.setDefaultButton(b_non)
        box.setEscapeButton(b_non)
        box.exec()
        clic = box.clickedButton()
        if clic is b_oui:
            return self.FERMER_ENREGISTRER
        if b_sans is not None and clic is b_sans:
            return self.FERMER_SANS
        return self.FERMER_ANNULER

    def peut_fermer(self):
        """Faut-il laisser la fenêtre se fermer ? Une seule question, qui
        porte à la fois la confirmation et, s'il y a lieu, l'enregistrement.
        Hors confirmations (tests, fenêtre réglée pour se taire) : l'ancienne
        règle, qui ne demandait que pour un point modifié."""
        if not self._confirmations_actives():
            return self._confirmer_abandon()
        modifie = bool(self._dirty and self.journal is not None
                       and self.point is not None and not self.point.fige)
        rep = self._demander_fermeture(modifie)
        if rep == self.FERMER_ANNULER:
            return False
        if rep == self.FERMER_ENREGISTRER and modifie:
            return bool(self.save_point())
        return True

    def closeEvent(self, event):
        # la mise à jour (D-70) a déjà posé la question avant de fermer
        deja = getattr(self, "_fermeture_deja_confirmee", False)
        self._fermeture_deja_confirmee = False
        if not deja and not self.peut_fermer():
            event.ignore()
            return
        # on rend le navire : le fichier « ouvert par » disparaît, et l'autre
        # poste peut ouvrir. Puis on quitte EXPLICITEMENT (voir main()).
        self._lacher_verrou_navire()
        super().closeEvent(event)
        if event.isAccepted():
            app = QApplication.instance()
            if app is not None and not app.property("carene_tests"):
                QTimer.singleShot(0, app.quit)

    def open_ship_editor(self):
        if not self._ecriture_permise("Créer ou modifier le navire"):
            return
        from .core.navire_draft import NavireDraft
        from .ship_editor import ShipEditorWindow
        folder = app_paths.ship_folder()
        if app_paths.has_tables(folder):
            try:
                draft = NavireDraft.load(folder)
            except Exception as e:
                QMessageBox.warning(self, "Navire", f"Dossier illisible : {e}")
                draft = NavireDraft()
        else:
            draft = NavireDraft()
        draft.source_path = folder
        self.ship_editor = ShipEditorWindow(
            self, draft=draft, project=self.project,
            on_open_plans=self.open_plan_editor)
        self.ship_editor.save_path = folder
        self.ship_editor.navire_saved.connect(self._on_navire_saved)
        self.ship_editor.show()
        self.ship_editor.raise_()
        return self.ship_editor

    def open_plan_editor(self):
        """Éditeur de plans, sur la géométrie du navire en place."""
        if not self._ecriture_permise("Éditeur de plans"):
            return None
        from .plan_editor import PlanEditorWindow
        # une seule fenêtre d'éditeur : la rouvrir la ramène au premier plan
        # au lieu d'en empiler une nouvelle à chaque clic
        ed = self.plan_editor
        vivant = False
        if ed is not None:
            try:
                ed.isVisible()
                vivant = True
            except RuntimeError:          # objet C++ déjà détruit
                vivant = False
        if not vivant:
            ed = self.plan_editor = PlanEditorWindow()
            ed.geometry_saved.connect(self._on_geometry_saved)
        # `charger_projet` et non `ed.project = …` : la fenêtre est unique et
        # réutilisée, il faut lui faire oublier la pile d'annulation et la
        # sélection du navire précédent, sinon Ctrl+Z réécrirait une cale qui
        # n'est plus dans le projet affiché.
        # UNE COPIE, pas le projet de la fenêtre (D-77) : l'éditeur modifiait
        # la géométrie en direct, et une cale déplacée mais pas enregistrée
        # entrait tout de suite dans le calcul — un point pouvait même être
        # figé sur une géométrie qui disparaissait au lancement suivant. La
        # fenêtre ne reprend la géométrie qu'à l'enregistrement
        # (`_on_geometry_saved`).
        import copy as _copy
        try:
            travail = _copy.deepcopy(self.project)
        except Exception:                   # noqa: BLE001 — jamais bloquant
            travail = self.project
        ed.charger_projet(travail)
        ed.ship_folder = app_paths.ship_folder()
        if self.project.decks:
            ed.set_current_deck(self.project.sorted_decks()[0])
        ed.refresh_all()
        ed.show()
        ed.raise_()
        return ed

    def _on_navire_saved(self, path):
        # Le navire est relu — mais le POINT en cours n'a pas à en pâtir :
        # rouvrir le navire rechargeait le dernier point du disque, et les
        # sondes et poses faites depuis le dernier Ctrl+S disparaissaient sans
        # question (P-4). On garde le point de la fenêtre, modifications
        # comprises.
        garde = self.point if (self._dirty and self.point is not None
                               and not getattr(self.point, "fige", False)) else None
        avant = os.path.normcase(os.path.abspath(self.journal.folder)) \
            if self.journal is not None else None
        self.open_ship()
        if (garde is not None and self.journal is not None
                and os.path.normcase(os.path.abspath(self.journal.folder)) == avant):
            self._adopter_point(garde)
            self._dirty = True
            self._refresh_saisies()
            self.recompute()
            self.statusBar().showMessage(
                f"Navire enregistré dans {path} — le point en cours et ses "
                "modifications non enregistrées sont gardés.", 10000)
        else:
            self.statusBar().showMessage(f"Navire enregistré dans {path}", 8000)

    def _on_geometry_saved(self):
        # le projet vient de l'éditeur qui a émis le signal, pas forcément de
        # `self.plan_editor` (celui-ci a pu être remplacé entre-temps)
        source = self.sender()
        proj = getattr(source, "project", None)
        if proj is not None:
            self.project = proj
        # une cale renommée dans l'éditeur : les colis du point ouvert passent
        # sous son nouveau code (les points figés, eux, sont lus par les
        # anciens codes — voir Capacity.anciens_codes)
        n = 0
        fige = self.point is not None and bool(getattr(self.point, "fige", False))
        if (not fige and not getattr(self, "lecture_seule", False)
                and getattr(self, "condition", None) is not None):
            n = self.condition.migrer_codes_cales(self.project)
            if n:
                self._dirty = True
        self._refresh_saisies()
        self.recompute()
        self.statusBar().showMessage(
            "Plans enregistrés." + (f" Colis de {n} cale(s) renommée(s) "
                                    "reportés sous leur nouveau code." if n else ""),
            8000)

    def change_ship_folder(self):
        # changer de navire, c'est quitter le point : on demande d'abord (P-4)
        if not self._confirmer_abandon():
            return
        path = QFileDialog.getExistingDirectory(
            self, "Choisir le dossier du navire à ouvrir", app_paths.ship_folder())
        if not path:
            return
        app_paths.set_ship_folder(path)
        self.open_ship()
        self.statusBar().showMessage(f"Navire ouvert depuis : {path}", 8000)

    def exporter_sauvegarde(self, chemin=None):
        """*Navire › Exporter une sauvegarde du navire…* — voir
        `sauvegarde_dialog.exporter`. Renvoie le chemin écrit, ou ""."""
        from . import sauvegarde_dialog
        return sauvegarde_dialog.exporter(self, chemin)

    def importer_sauvegarde(self, chemin=None, reprendre_config=None):
        """*Navire › Importer une sauvegarde…* — voir
        `sauvegarde_dialog.importer`. Renvoie le résultat, ou None."""
        if not self._ecriture_permise("Importer une sauvegarde"):
            return None
        from . import sauvegarde_dialog
        return sauvegarde_dialog.importer(self, chemin, reprendre_config)

    def delete_ship(self):
        folder = app_paths.ship_folder()
        if not self._ecriture_permise("Supprimer le navire"):
            return
        if not app_paths.ship_exists(folder):
            QMessageBox.information(self, "Supprimer le navire",
                                    "Aucun navire à supprimer.")
            return
        nom = app_paths.ship_name(folder) or "sans nom"
        rep = QMessageBox.warning(
            self, "Supprimer le navire",
            f"Supprimer « {nom} » de cette installation ?\n\n"
            "Cette application ne gère qu'un seul navire : supprimer celui-ci "
            "est le seul moyen d'en créer un autre. Le dossier ne sera pas "
            "effacé du disque, seulement mis de côté — vous pourrez le "
            "récupérer ou le jeter vous-même.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if rep != QMessageBox.StandardButton.Yes:
            return
        backup = app_paths.delete_ship(folder)
        self.condition = LoadingCondition()
        self._dirty = False
        self.open_ship()
        self.statusBar().showMessage(
            f"Navire supprimé. Ancien dossier conservé sous {backup}", 15000)

    # ------------------------------------------------------------- journal
    def resultats_courants(self):
        """Instantané de ce que le bandeau affiche : pour le journal."""
        last = getattr(self, "_last", None)
        if not last:
            return None
        from . import __version__
        poids, eq, gz, rep = last
        return {
            "deplacement": f"{poids:,.1f} t".replace(",", " "),
            # la cargaison seule (ni soutes, ni lège) : c'est elle qu'on lit
            # dans le journal d'un point figé, des mois plus tard
            "cargaison": f"{self.point.poids_cargaison_t:,.1f} t".replace(",", " "),
            "te_ar": _te(eq, "TE_AR_m"), "te_av": _te(eq, "TE_AV_m"),
            "assiette": f"{eq.trim_m:+.3f} m",
            "gite": "—" if self._gite is None else f"{self._gite:+.1f}°",
            "gm": f"{gz.gm_corrige_m:.3f} m",
            "verdict": self.pill_verdict.text(),
            "version": __version__,
        }

    def _refresh_combo_point(self):
        """Le sélecteur du bandeau : tous les points, le courant en tête de
        sélection. On y lit d'un coup d'œil où l'on travaille."""
        combo = getattr(self, "combo_point", None)
        if combo is None:
            return
        combo.blockSignals(True)
        try:
            combo.clear()
            points = self._points_a_choisir()
            courant = self.point
            index = 0
            for i, p in enumerate(points):
                etat = p.etat + ("" if p.path or p.fige else ", non enregistré")
                if p is courant and self._dirty and not p.fige:
                    etat += ", modifié"
                combo.addItem(f"{p.titre} · {p.date_lisible}"
                              + (f" · voyage {p.voyage}" if p.voyage else "")
                              + (f" · {p.lieu}" if p.lieu else "") + f" · {etat}", p.numero)
                if p is courant:
                    index = i
            if not points:
                combo.addItem("Aucun point", None)
            combo.setCurrentIndex(index)
            if not self.nav:
                combo.setItemText(index, combo.itemText(index) + "  ·  tables manquantes")
            # LE GESTE DE L'ESCALE, au bout de la liste des points (D-68) : on
            # y arrive naturellement quand on cherche « le suivant »
            if self.journal is not None:
                combo.insertSeparator(combo.count())
                combo.addItem("＋ Nouveau point (copie du courant)…", NOUVEAU_POINT)
        finally:
            combo.blockSignals(False)

    def _points_a_choisir(self):
        """Les points parmi lesquels on choisit, du plus récent au plus ancien.

        La liste vient du disque ; le courant y est remplacé par son état en
        mémoire (libellé tapé, non encore enregistré — ou point tout neuf,
        jamais écrit), sinon le bandeau montre un point qui n'est plus celui
        qu'on a sous les yeux."""
        points = list(reversed(self.journal.points())) if self.journal else []
        courant = self.point
        if courant is not None:
            points = [courant if p.numero == courant.numero else p for p in points]
            if not any(p is courant for p in points):
                points.insert(0, courant)
        return points

    def _garnir_menu_points(self):
        """Le sous-menu *Journal › Ouvrir le point* : tous les points, le
        courant coché. Refait à chaque ouverture : le journal a pu changer."""
        menu = self.menu_points
        menu.clear()
        points = self._points_a_choisir() if self.journal else []
        if not points:
            a = menu.addAction("Aucun point dans le journal")
            a.setEnabled(False)
            return
        for p in points:
            a = menu.addAction(f"{p.titre} · {p.date_lisible} · {p.etat}")
            a.setCheckable(True)
            a.setChecked(self.point is not None and p.numero == self.point.numero)
            a.triggered.connect(lambda *_a, n=p.numero: self._ouvrir_point_numero(n))

    def _ouvrir_point_numero(self, numero):
        """Ouvre le point `numero` du journal, après avoir demandé
        confirmation : « on risque trop de changer de point de chargement sans
        s'en rendre compte » (D-68). La question se pose AVANT celle des
        modifications non enregistrées — d'abord « veux-tu partir ? », ensuite
        « et ce que tu laisses ? »."""
        if self.journal is None or self.point is None or numero == self.point.numero:
            return False
        cible = next((p for p in self._points_a_choisir() if p.numero == numero), None)
        if cible is None:
            return False
        if self._confirmations_actives():
            rep = QMessageBox.question(
                self, "Changer de point",
                f"Quitter « {self.point.titre} » pour ouvrir « {cible.titre} » "
                f"({cible.date_lisible}, {cible.etat}) ?\n\n"
                "Capacités, chargement et verdict affichés seront ceux de "
                "l'autre point.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if rep != QMessageBox.StandardButton.Yes:
                return False
        if not self._confirmer_abandon():
            return False
        self.open_point(cible, confirmer=False)
        return True

    def _on_combo_point(self, index):
        """Changer de point depuis le bandeau — ou en ouvrir un nouveau."""
        numero = self.combo_point.itemData(index)
        if numero == NOUVEAU_POINT:
            self.new_point()
            self._refresh_combo_point()      # le nouveau point, ou le même
            return
        if numero is None or self.journal is None or numero == self.point.numero:
            return
        if not self._ouvrir_point_numero(numero):
            self._refresh_combo_point()      # on reste sur le point courant

    def _on_journal_edit(self):
        """Date, lieu, libellé ou note du point courant tapés dans la vue
        Journal : le point est modifié, le bandeau et la liste le disent."""
        self._dirty = True
        self._rebanner()
        self.journal_panel.refresh_liste()

    def _rebanner(self):
        """Redessine le bandeau avec les derniers résultats, sans recalculer."""
        last = getattr(self, "_last", None)
        if last:
            self._refresh_banner(*last, converged=getattr(self, "_fiable", True))
        else:
            self._refresh_banner()

    def new_point(self, depuis=None, demander=True):
        """Le point suivant : copie intégrale du courant (ou de `depuis`)."""
        if self.journal is None:
            return
        src = depuis if depuis is not None else self.point
        # ON DEMANDE (D-68) : un point de plus dans le journal n'est pas rien,
        # et l'icône de la barre en a créé plus d'un par mégarde
        if demander and self._confirmations_actives():
            rep = QMessageBox.question(
                self, "Nouveau point",
                f"Ouvrir un nouveau point du journal, copie de « {src.titre} » ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
            if rep != QMessageBox.StandardButton.Yes:
                return
        # le point courant a peut-être des modifications non enregistrées :
        # on les propose à l'enregistrement avant de le quitter
        if demander and not self._confirmer_abandon():
            return
        if src.fige and src.path:
            # un point figé se lit sur le disque : l'exemplaire en mémoire a
            # pu être retouché (le tableau restait modifiable) — l'archive,
            # elle, est ce qui a été figé
            try:
                src = Point.load(src.path)
            except Exception as e:
                self.statusBar().showMessage(
                    f"{src.titre} : archive illisible ({e}), copie de l'état en mémoire.", 9000)
        self._adopter_point(self.journal.nouveau(src))
        self._refresh_saisies()
        self.recompute()
        self.tabs.setCurrentIndex(VUE_JOURNAL)
        self.statusBar().showMessage(
            f"Point {self.point.numero} ouvert, copie du point {src.numero}. "
            "Donnez-lui sa date, son lieu, son libellé.", 8000)

    def demander_point_de_travail(self):
        """Au lancement : sur quel point travailler ?

        Appelée par `main()`, jamais par la fenêtre elle-même — une question
        posée pendant la construction bloquerait les tests hors écran et les
        captures. Ne se pose pas si le journal est vide : il n'y a rien à
        choisir."""
        if self.journal is None or not self.journal.points():
            return
        if not app_paths.demander_point_au_lancement():
            return
        from .point_chooser import PointChooser
        dlg = PointChooser(self)
        accepte = dlg.exec()
        if dlg.ne_plus_demander():
            app_paths.set_demander_point(False)
        if not accepte:
            return
        quoi, point = dlg.resultat
        if quoi == "ouvrir" and point is not None:
            self.open_point(point)
        elif quoi == "nouveau":
            self.new_point(depuis=point, demander=False)

    def open_point(self, point, confirmer=True):
        if self.journal is None:
            return
        if confirmer and not self._confirmer_abandon():
            return
        try:
            p = Point.load(point.path) if point.path else point
        except Exception as e:
            QMessageBox.critical(self, "Ouvrir un point", f"Échec : {e}")
            return
        self._adopter_point(p)
        self._refresh_saisies()
        self.recompute()
        self.statusBar().showMessage(
            f"{p.titre} ({p.etat}) — tout est recalculé."
            + (" Point figé : lecture seule, créez un nouveau point pour modifier."
               if p.fige else ""), 8000)

    def save_point(self):
        """Enregistre le point courant. Un point figé ne se réécrit pas."""
        if self.journal is None or not app_paths.ship_exists(app_paths.ship_folder()):
            return False
        if not self._ecriture_permise("Enregistrer le point"):
            return False
        if self.point.fige:
            QMessageBox.information(
                self, "Point figé",
                f"{self.point.titre} est figé : il ne se réécrit pas.\n\n"
                "Pour continuer à partir de lui, ouvrez un nouveau point (Ctrl+N).")
            return False
        try:
            path = self.journal.enregistrer(self.point)
        except PointFige as e:
            QMessageBox.information(self, "Point figé", str(e))
            return False
        except Exception as e:
            QMessageBox.critical(self, "Enregistrer", f"Échec : {e}")
            return False
        self._dirty = False
        self.journal_panel.refresh()
        self._rebanner()
        # la date de modification vient d'être posée par le journal : on la
        # dit, parce que c'est la réponse à « je l'ai enregistré quand ? »
        self.statusBar().showMessage(
            f"Point enregistré le {self.point.modifie_lisible} : {path}", 8000)
        return True

    def freeze_point(self):
        """Fige le point courant : dernier enregistrement, avec l'instantané
        des résultats. Après cela, plus aucune écriture."""
        if self.journal is None or self.point.fige:
            return
        if not self._ecriture_permise("Figer ce point"):
            return
        p = self.point
        manque = [n for n, v in (("date", p.horodatage), ("lieu", p.lieu),
                                 ("libellé", p.libelle)) if not v]
        if manque:
            QMessageBox.information(
                self, "Figer ce point",
                "Un point figé doit être daté, situé et nommé — il manque : "
                + ", ".join(manque) + ". Complétez-les dans la vue Journal.")
            self.tabs.setCurrentIndex(VUE_JOURNAL)
            return
        res = self.resultats_courants()
        verdict = (res or {}).get("verdict", "—")
        rep = QMessageBox.question(
            self, "Figer ce point",
            f"Figer {p.titre} ({p.date_lisible}, {p.lieu}) ?\n\n"
            f"Verdict affiché : {verdict}.\n"
            "Il ne pourra plus être modifié ni réécrit. La suite se prépare "
            "dans un nouveau point, copie intégrale de celui-ci.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if rep != QMessageBox.StandardButton.Yes:
            return
        try:
            self.journal.figer(p, res)
        except (PointFige, OSError) as e:
            QMessageBox.critical(self, "Figer", f"Échec : {e}")
            return
        self._dirty = False
        # figé : les saisies passent en lecture seule (voir _refresh_saisies)
        self._refresh_saisies()
        self._rebanner()
        self.statusBar().showMessage(
            f"{p.titre} (point du {p.date_lisible}) figé le {p.modifie_lisible} — "
            "lecture seule ; créez un nouveau point (Ctrl+N) pour continuer à "
            "partir de lui.", 10000)

    def delete_point(self, point):
        if self.journal is None:
            return
        # supprimer, c'est écrire dans le journal : pas d'ici si un autre
        # poste le tient (P-10)
        if not self._ecriture_permise("Supprimer un point"):
            return
        rep = QMessageBox.question(
            self, "Supprimer un point",
            f"Supprimer {point.titre} ({point.date_lisible}, {point.etat}) ?\n\n"
            "Il part dans la corbeille du journal (journal\\.supprimes\\), "
            "d'où il se récupère à la main."
            + ("\n\nC'est un point figé : c'est une archive." if point.fige else ""),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if rep != QMessageBox.StandardButton.Yes:
            return
        self.journal.supprimer(point)
        if point.path and point.path == self.point.path:
            self.point.path = ""
            self._dirty = True        # il n'existe plus que dans la fenêtre
        self.journal_panel.refresh()
        self._rebanner()              # le sélecteur du bandeau suit la liste

    def import_case(self):
        """Un cas de chargement des versions précédentes devient un point."""
        folder = app_paths.ship_folder()
        cases = list_conditions(folder)
        if not cases:
            QMessageBox.information(self, "Importer un ancien cas",
                                    "Aucun cas de chargement enregistré pour ce navire.")
            return
        # le cas importé devient le point courant : on ne quitte pas le point
        # en cours sans demander (P-4)
        if not self._confirmer_abandon():
            return
        noms = [n for n, _ in cases]
        nom, ok = QInputDialog.getItem(self, "Importer un ancien cas",
                                       "Cas enregistrés :", noms, 0, False)
        if not ok:
            return
        try:
            cond = LoadingCondition.load(dict(cases)[nom])
        except Exception as e:
            QMessageBox.critical(self, "Importer", f"Échec : {e}")
            return
        self._adopter_point(self.journal.importer_cas(cond, nom))
        self._refresh_saisies()
        self.recompute()
        self.tabs.setCurrentIndex(VUE_JOURNAL)
        self.statusBar().showMessage(f"Cas « {nom} » importé comme point {self.point.numero}.", 6000)

    # compatibilité : les anciens noms restent appelables
    new_condition = new_point
    save_condition = save_point

    def open_solver(self, cales=None):
        """Propose un plan de chargement à partir du manifeste.

        `cales` : les codes des seules cales à garnir — le menu du clic droit
        d'une cale ouvre ainsi le répartiteur « déjà paramétré que pour la
        cale-là » (D-65)."""
        from .solver_dialog import SolverDialog
        if self.nav is None and not self.project.decks:
            QMessageBox.information(self, "Répartir",
                                    "Le navire n'a ni tables ni cales.")
            return
        if not self._modification_permise("Répartir le chargement"):
            return
        dlg = SolverDialog(self, cales=cales)
        ok = bool(dlg.exec())
        rap = dlg.values() if ok else None
        # la boîte a la fenêtre principale pour parent : sans cela elle reste
        # vivante jusqu'à la fermeture du logiciel, et une session d'escale en
        # empile une par « Répartir… ». On la détruit APRÈS avoir lu son
        # résultat — jamais avant.
        dlg.deleteLater()
        if ok and rap is not None:
            for code, lst in rap.places.items():
                self.condition.placements[code] = list(lst)
            # le point est MODIFIÉ : sans cela, fermer disait « enregistré »
            # et changer de point ne demandait rien — le plan était perdu (P-5)
            self._dirty = True
            self.tabs.setCurrentIndex(VUE_CHARGEMENT)
            self._refresh_saisies()
            self.recompute()
            self.statusBar().showMessage(
                f"Plan appliqué : {rap.nb_places} charge(s) placée(s).", 8000)

    def open_exports(self, action=None):
        """La fenêtre « Exporter… » (Ctrl+E). `action` : « apercu » ou
        « imprimer » ouvre directement l'aperçu ou l'impression du rapport."""
        from .export_dialog import ExportDialog
        if self.journal is None:
            QMessageBox.information(self, "Exporter",
                                    "Aucun navire ouvert : rien à exporter.")
            return None
        # une SEULE fenêtre, comme le catalogue : trois Ctrl+E donnaient trois
        # fenêtres, chacune figée sur le contexte de sa construction — trois
        # en-têtes de point différents pour un même navire. On rouvre la même,
        # et on lui refait son contexte.
        dlg = getattr(self, "_export_dlg", None)
        try:
            if dlg is not None:
                dlg.isVisible()
        except RuntimeError:          # la fenêtre a été détruite côté C++
            dlg = None
        if dlg is None:
            dlg = self._export_dlg = ExportDialog(self)
        else:
            dlg.rafraichir()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        if action == "apercu":
            dlg.apercu()
        elif action == "imprimer":
            dlg.imprimer()
        return dlg

    def open_plan_dockers(self):
        """La fenêtre « Exporter… » ouverte sur la seule planche du quai.

        Le bord ne tire pas ce document au même moment que le reste : il le
        tire une fois le chargement calé, pour aller le donner aux dockers.
        L'entrée de menu le nomme, la fenêtre s'ouvre avec cette case-là
        cochée et elle seule (voir `ExportDialog.viser`)."""
        from . import rapports
        dlg = self.open_exports()
        if dlg is not None:
            dlg.viser(rapports.EXPORT_DOCKERS[0])
        return dlg

    def open_catalogue(self, vers_manifeste=True):
        """Le catalogue des charges du bord, dans sa fenêtre — accessible de
        partout (menu Navire, vue Chargement, manifeste). Une seule fenêtre,
        non modale : on la garde ouverte pendant qu'on compose le manifeste."""
        if not self._ecriture_permise("Catalogue des charges"):
            return None
        from .catalogue_dialog import CatalogueDialog
        from .core.cargo_model import Catalogue
        if self.catalogue is None:
            self.catalogue = Catalogue()
        dlg = getattr(self, "_catalogue_dlg", None)
        try:
            if dlg is not None:
                dlg.isVisible()
        except RuntimeError:
            dlg = None
        if dlg is None:
            dlg = self._catalogue_dlg = CatalogueDialog(
                self.catalogue, self, vers_manifeste=vers_manifeste)
            dlg.changed.connect(self._catalogue_modifie)
            dlg.code_renomme.connect(self._catalogue_code_renomme)
            dlg.ajouter_au_manifeste.connect(self._catalogue_vers_manifeste)
        else:
            dlg.catalogue = self.catalogue
            dlg._recharger()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        return dlg

    def _catalogue_code_renomme(self, ancien, nouveau):
        """Un code de type a changé au catalogue (D-69) : le manifeste, les
        colis posés et les brouillons du POINT OUVERT suivent, pour que rien
        ne se retrouve orphelin de son type. Les points archivés ne sont pas
        touchés — ils sont figés, et un manifeste porte ses propres
        dimensions."""
        fige = self.point is not None and bool(getattr(self.point, "fige", False))
        # un point figé est une archive : il garde l'ancien code, comme les
        # autres points archivés (D-69)
        n = 0 if (fige or getattr(self, "lecture_seule", False)) \
            else renommer_type_code(self.condition, ancien, nouveau)
        if n:
            self._refresh_saisies()
            self.on_loading_changed()
        self.statusBar().showMessage(
            f"Type « {ancien} » renommé « {nouveau} »"
            + (f" — {n} ligne(s) et colis du point suivent." if n
               else " — rien ne s'y référait dans ce point.")
            + " Les points archivés gardent l'ancien code.", 10000)
        return n

    def open_equipements(self):
        """Le matériel du bord, dans sa fenêtre — menu Navire et vue Chargement."""
        if not self._ecriture_permise("Matériel du bord"):
            return None
        return self.cargo_panel.open_materiel()

    def open_ports(self):
        """Les escales du navire, dans leur fenêtre — menu Navire et manifeste.

        Une seule fenêtre, non modale : on la garde ouverte pendant qu'on
        compose le manifeste."""
        if not self._ecriture_permise("Escales du navire"):
            return None
        from .port_picker import PortsDialog
        dlg = getattr(self, "_ports_dlg", None)
        try:
            if dlg is not None:
                dlg.isVisible()
        except RuntimeError:
            dlg = None
        if dlg is None:
            dlg = self._ports_dlg = PortsDialog(self, self)
            dlg.changed.connect(self._escales_modifiees)
        else:
            dlg.refresh()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        return dlg

    def open_brouillons(self):
        """Les brouillons du plan de chargement de ce point, dans leur fenêtre.

        Une seule fenêtre, non modale, comme le catalogue et les escales : on
        la garde ouverte à côté du plan pendant qu'on compare deux versions.
        Elle est rafraîchie à chaque ouverture — le point a pu changer entre
        deux clics, et une fenêtre figée sur le point d'avant montrerait les
        brouillons d'un autre chargement."""
        from .brouillons_dialog import BrouillonsDialog
        if self.journal is None or self.point is None:
            QMessageBox.information(self, "Brouillons du plan de chargement",
                                    "Aucun navire ouvert : il n'y a pas de plan.")
            return None
        dlg = getattr(self, "_brouillons_dlg", None)
        try:
            if dlg is not None:
                dlg.isVisible()
        except RuntimeError:          # la fenêtre a été détruite côté C++
            dlg = None
        if dlg is None:
            dlg = self._brouillons_dlg = BrouillonsDialog(self)
        else:
            dlg.refresh()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        return dlg

    def _escales_modifiees(self):
        """La liste appartient au navire et sa fenêtre l'a déjà enregistrée :
        il reste à rafraîchir tout ce qui affiche un port."""
        self._refresh_saisies()
        self.journal_panel.refresh()
        d = getattr(self.cargo_panel, "_manif", None)
        try:
            if d is not None and d.isVisible():
                d.refresh()
        except (RuntimeError, AttributeError):
            pass

    def _catalogue_modifie(self):
        """Le catalogue appartient au navire : il s'enregistre dans son dossier,
        et tout ce qui le lit (manifeste, lot courant) se rafraîchit."""
        try:
            self.catalogue.save(app_paths.ship_folder())
        except OSError as e:
            self._signaler("Catalogue des charges",
                           f"Le catalogue n'a pas pu être enregistré : {e}")
        self.cargo_panel.refresh()
        d = getattr(self.cargo_panel, "_manif", None)
        try:
            if d is not None and d.isVisible():
                d.refresh()
        except (RuntimeError, AttributeError):
            pass
        # la fenêtre de composition d'un lot porte la liste des colis
        # standards : elle suit le catalogue sur-le-champ (D-90), le type
        # choisi et ce qu'on a déjà tapé restent en place
        lot = getattr(self, "_ajout_lot_dlg", None)
        try:
            if lot is not None and lot.isVisible():
                lot._recharger()
        except (RuntimeError, AttributeError):
            pass

    def _catalogue_vers_manifeste(self, t, quantite):
        """Depuis le catalogue : on passe par la fenêtre de composition, avec
        le type déjà choisi — le nom du lot, sa couleur et ses ports se règlent
        là plutôt qu'après coup, ligne par ligne, dans le tableau."""
        dlg = self.ajouter_un_lot(t)
        if dlg is not None and quantite:
            dlg.qte.setValue(int(quantite))

    def ajouter_un_lot(self, type_choisi=None):
        """Composer un lot du manifeste : catalogue à gauche, lot à droite.

        Une seule fenêtre, non modale et qui reste ouverte : on enchaîne les
        lots d'une escale sans revenir au tableau entre chaque."""
        from .ajout_lot_dialog import AjoutLotDialog, C_CODE
        dlg = getattr(self, "_ajout_lot_dlg", None)
        try:
            if dlg is not None:
                dlg.isVisible()
        except RuntimeError:
            dlg = None
        if dlg is None:
            dlg = self._ajout_lot_dlg = AjoutLotDialog(self, self)
            dlg.ajoute.connect(self._lot_ajoute)
            dlg.ouvrir_catalogue.connect(lambda: self.open_catalogue())
        dlg.refresh()
        if type_choisi is not None:
            for r in range(dlg.table.rowCount()):
                it = dlg.table.item(r, C_CODE)
                if it is not None and it.data(Qt.ItemDataRole.UserRole) == type_choisi.code:
                    dlg.table.selectRow(r)
                    break
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        return dlg

    def _lot_ajoute(self, m):
        self.tabs.setCurrentIndex(VUE_CHARGEMENT)
        self.on_loading_changed()
        d = getattr(self.cargo_panel, "_manif", None)
        try:
            if d is not None and d.isVisible():
                d.refresh()
        except (RuntimeError, AttributeError):
            pass
        self.statusBar().showMessage(
            f"« {m.nom} » : {m.quantite} × {m.poids_t:g} t au manifeste.", 6000)

    def open_ballast(self):
        """Cherche une répartition de ballast et l'applique si elle convient."""
        from .ballast_dialog import BallastDialog
        if self.nav is None:
            QMessageBox.information(
                self, "Ballastage",
                "Le navire n'a pas ses tables hydrostatiques : le ballastage "
                "ne peut pas être calculé.")
            return
        if not self._modification_permise("Ballastage"):
            return
        dlg = BallastDialog(self)
        ok = bool(dlg.exec())
        # `appliquer()` lit la répartition trouvée : on ne détruit la boîte
        # qu'après, sinon on lirait un objet Qt déjà supprimé
        n = dlg.appliquer() if ok else 0
        dlg.deleteLater()
        if ok:
            self._dirty = True        # voir open_solver (P-5)
            self.tabs.setCurrentIndex(VUE_CAPACITES)
            self._refresh_saisies()
            self.recompute()
            self.statusBar().showMessage(
                f"Ballastage appliqué : {n} capacité(s) mises à jour. "
                "Relevez les sondes après la manœuvre pour confirmer.", 12000)

    def open_tirants(self):
        """Le relevé de tirants d'eau du bord, confronté au calcul (D-60).

        La fenêtre ne touche à rien tant qu'on n'a pas demandé le poids
        fictif ; c'est elle qui l'ajoute aux poids divers, et c'est ici qu'on
        refuse le geste en lecture seule — comme toute écriture du point."""
        from .tirants_dialog import TirantsDialog
        if self.nav is None:
            QMessageBox.information(
                self, "Tirants d'eau relevés",
                "Le navire n'a pas ses tables hydrostatiques : un relevé de "
                "tirants d'eau ne peut pas être exploité.")
            return None
        if not self._modification_permise("Relever les tirants d'eau"):
            return None
        dlg = TirantsDialog(self)
        ok = bool(dlg.exec())
        ecart = dlg.ecart
        dlg.deleteLater()
        if ok and ecart is not None:
            self.statusBar().showMessage(
                "Poids fictif ajouté aux poids divers : "
                f"{ecart.masse_t:+.1f} t à x = {ecart.position_m:.2f} m. "
                "Il s'efface comme n'importe quel poids.", 12000)
        return dlg

    # ------------------------------------------------------------- calcul
    def _refresh_saisies(self):
        """Un seul point de rafraîchissement pour les deux onglets et le
        récapitulatif : ils repartent tous de la même condition."""
        self.liquids_panel.refresh()
        self.cargo_panel.refresh()
        self.condition_panel.refresh()
        self.bilan_panel.refresh()
        # un point figé est une archive : ses saisies passent en lecture seule
        # (le bandeau porte la pastille « POINT FIGÉ », voir _refresh_banner)
        fige = self.point is not None and bool(self.point.fige)
        self.liquids_panel.setEnabled(not fige)
        self.cargo_panel.setEnabled(not fige)
        self._refresh_annulation()
        # la vue Journal, elle, est rafraîchie à la fin de recompute() : sa
        # ligne du point courant lit les chiffres du bandeau, qui n'existent
        # qu'après le calcul — ici elle aurait un calcul de retard

    def on_condition_changed(self):
        self._dirty = True
        self._refresh_saisies()
        self.recompute()

    def on_loading_changed(self):
        """Une cale vient d'être chargée ou vidée dans la vue centrale.

        La fenêtre est le seul point de rafraîchissement : la vue, le panneau
        de condition et les résultats repartent tous de la même donnée, ce qui
        évite de les voir diverger."""
        self._dirty = True
        self._refresh_saisies()
        self.recompute()

    def open_hold(self, cap):
        """Ouvre le plan détaillé d'une cale depuis le récapitulatif."""
        self.tabs.setCurrentIndex(VUE_CHARGEMENT)
        self.cargo_panel.zoom_in(cap)
        self.cargo_panel.open_hold_editor()

    def recadrer_vue(self):
        """« Recadrer » agit sur ce qu'on a sous les yeux, pas toujours sur
        l'iso des capacités : le bouton ne faisait rien depuis les autres vues."""
        vue = self.tabs.currentIndex()
        if vue == VUE_CAPACITES:
            self.liquids_panel.iso.fit()
        elif vue == VUE_CHARGEMENT:
            self.cargo_panel.zoom_out()
            self.cargo_panel.iso.fit()
        else:
            self.statusBar().showMessage(
                "Rien à recadrer ici : F3 (capacités) ou F4 (chargement).", 4000)

    def recompute(self):
        """Relance le calcul complet et met à jour bandeau et résultats."""
        try:
            self._calculer()
        finally:
            # après le calcul, jamais avant : la ligne du point courant dans
            # la liste du journal montre les chiffres qu'on vient d'obtenir
            self.journal_panel.refresh()
            # …et c'est ici que le chargement d'avant entre dans la pile
            # d'annulation, s'il a changé (D-61)
            self._noter_pour_annulation()

    def _calculer(self):
        self._gite = None
        self._last = None          # pas de résultat tant qu'il n'est pas recalculé
        if hasattr(self, "profil"):
            self.profil.update()
        self.results_panel.lbl_none.setVisible(True)
        if self.nav is None:
            msg = (f"Tables du navire illisibles : {self.nav_error}"
                   if self.nav_error else
                   "Le navire n'a pas encore ses tables hydrostatiques : "
                   "complétez-le dans « Créer ou modifier le navire… ».")
            self.results_panel.clear(msg)
            self._refresh_banner()
            return

        # tout le calcul est protégé, y compris l'agrégation des poids : une
        # exception ici laissait au bandeau le verdict PRÉCÉDENT — celui d'un
        # autre point, parfois « CONFORME » (P-13)
        try:
            cond = self.condition.to_core(self.nav, self.project)
            poids, lcg, tcg, vcg, fsm = cond.totals()
        except Exception as e:
            self.results_panel.clear(f"Erreur de calcul : {e}")
            self._refresh_banner()
            journal_technique.noter(f"Calcul impossible : {e!r}", "erreur")
            return
        if poids <= 0:
            self.results_panel.clear(
                "Rien n'est embarqué : incluez le navire lège, chargez une "
                "cale ou ajoutez un poids.")
            self._refresh_banner()
            return
        try:
            eq = hydrostatics.solve_equilibrium(self.nav, poids, lcg)
            gz = stability.gz_curve(self.nav, eq, vcg, tcg, fsm)
            # la gîte d'équilibre est cherchée par gz_curve sur tout le domaine
            # des pantocarènes, et sert d'origine aux aires réglementaires
            self._gite = gz.origine_deg
            self._theta_f = stability.downflooding_angle(
                self.nav, _te_val(eq, "TE_AR_m", eq.draft_m),
                _te_val(eq, "TE_AV_m", eq.draft_m))[0]
            # LES RÉGLEMENTATIONS RETENUES PAR LE NAVIRE (D-79) : celles qui
            # valent toujours d'abord — critères généraux, GM des voiliers,
            # ligne de charge… —, puis celle du vent, qui dépend de la voilure
            # portée (voir _criteres_de_vent). Un seul tableau, un seul verdict.
            rep = reglements.evaluer_navire(self._retenues(), self._contexte_regl(eq, gz),
                                            "toujours")
            self._criteres_de_vent(rep, eq, gz)
        except Exception as e:
            self.results_panel.clear(f"Erreur de calcul : {e}")
            self._refresh_banner()
            return

        self._last = (poids, eq, gz, rep)
        self.results_panel.show_result(gz, rep)
        self.results_panel.show_flottaison(
            self._details_flottaison(poids, lcg, tcg, vcg, fsm, eq, gz))
        self.results_panel.set_avertissement(self._reserves(gz, rep))
        # Deux domaines à respecter, pas un : la table hydrostatique et la
        # table des pantocarènes n'ont pas les mêmes bornes en déplacement
        # (sur le navire de référence 1129→2689 t contre 1300→2700 t). Un
        # équilibre peut être
        # parfaitement tabulé alors que la courbe GZ repose sur des KN lus en
        # bord de table.
        fiable = eq.converged and eq.dans_domaine and gz.dans_domaine_kn
        self._fiable = fiable
        if not fiable:
            (t0, t1), (d0, d1) = self.nav.hydro.bounds()
            self.results_panel.lbl_none.setVisible(True)
            if not (eq.converged and eq.dans_domaine):
                self.results_panel.lbl_none.setText(
                    "Équilibre hors du domaine des tables hydrostatiques "
                    f"(assiette {t0:+.2f} à {t1:+.2f} m, tirant d'eau "
                    f"{d0:.2f} à {d1:.2f} m). Les valeurs ci-dessus sont "
                    "extrapolées : elles n'ont aucune valeur réglementaire. "
                    "Vérifiez la répartition des poids.")
            else:
                (k0, k1), (w0, w1) = self.nav.bornes_kn()
                self.results_panel.lbl_none.setText(
                    f"Assiette {eq.trim_m:+.2f} m / déplacement {poids:.0f} t "
                    f"hors du domaine des pantocarènes (assiette {k0:+.2f} à "
                    f"{k1:+.2f} m, déplacement {w0:.0f} à {w1:.0f} t) — "
                    "l'équilibre, lui, est bien tabulé. Les KN sont lus en "
                    "bord de table : la courbe GZ et les critères qui en "
                    "découlent n'ont aucune valeur réglementaire.")
        self._refresh_banner(poids, eq, gz, rep, fiable)
        self.cargo_panel.coupe.update()
        self.profil.update()

    # ------------------------------------------------------- critères de vent
    def _criteres_de_vent(self, rep, eq, gz):
        """Ajoute au rapport le critère de vent de la voilure portée au point.

        Le bord l'a demandé en ces termes : « le dossier fourni semble faire
        question de conditions full sails et reduced sails : qu'en est-il de
        Carène ? » Le moteur savait déjà les calculer, mais rien ne les
        appelait, faute de savoir quelle surface le navire oppose au vent. Le
        dossier la donne, configuration par configuration et tirant d'eau par
        tirant d'eau (`profils_vent.csv`) : c'est ce qui manquait.

        Deux critères, et c'est la VOILURE qui décide lequel :

        - voiles enroulées, le navire est un cargo au vent de travers :
          critère météo IS2008 §2.3 (`weather.evaluate`) ;
        - voilure déployée : critère NR500 « Sailing Yachts »
          (`criteria.evaluate_nr500_voilier`), celui que le recueil du bord
          imprime pour ses cas 01d-f / 02d-f.

        Les lignes rejoignent le rapport général : un seul tableau, un seul
        verdict. Un critère de vent non conforme rend donc le point NON
        CONFORME — c'est bien ce qu'on veut, un navire qui ne tient pas le
        vent dans la voilure qu'il porte n'est pas conforme.

        Un navire dont le dossier ne décrit aucune configuration ne reçoit
        RIEN de plus : ni ligne, ni message, ni changement de verdict.
        """
        profils = getattr(self.nav, "profils_vent", None)
        pid = profils.resoudre(getattr(self.condition, "voilure", None)) if profils else None
        if pid is None:
            # le navire a CHOISI le critère météo (étape « Critères ») mais ne
            # décrit aucune surface au vent : on ne peut pas l'évaluer, et le
            # taire rendait le point CONFORME (D-78)
            if any(x.reglement.situation == "sans_voile" for x in self._retenues()):
                rep.add("METEO_ABSENT",
                        "Critère météo IS 2008 §2.3 — surface au vent non décrite au dossier",
                        float("nan"), float("nan"), ">=",
                        groupe="Critère météo IS2008 §2.3")
                rep.messages.append(
                    "Le critère météo est retenu pour ce navire, mais le dossier ne "
                    "décrit pas sa surface au vent (profils_vent.csv) : il n'est pas "
                    "évalué, et le verdict est INCOMPLET.")
            return
        _titre, partiel = self.rapport_de_vent(pid, eq, gz)
        if partiel is not None:
            rep.fusionner(partiel)

    def rapport_de_vent(self, pid, eq, gz):
        """(titre, rapport) du critère de vent pour UNE configuration de
        voilure, sur CE chargement — sans rien changer à l'écran.

        Extrait de `_criteres_de_vent` pour que le rapport de stabilité puisse
        demander la même chose de chaque configuration du dossier (D-59) : le
        bord lit ainsi, sur une page, ce que le navire tiendrait sous chaque
        voilure avec le chargement du point, au lieu du seul cas qu'il porte.
        C'est exactement ce que l'écran afficherait si l'on changeait le
        sélecteur : même équilibre, même courbe GZ, même code.

        Rend (titre, None) si le navire ne décrit aucune voilure."""
        profils = getattr(self.nav, "profils_vent", None)
        if not profils or pid is None:
            return "", None
        nom = profils.nom(pid)
        meteo = profils.critere(pid) == CRITERE_METEO
        titre = (f"Critère météo IS2008 §2.3 — {nom}" if meteo
                 else f"NR500 voilier — {nom}")
        rep = criteria.CriteriaReport()
        vent, note = profils.surface_au_vent(pid, eq.draft_m)

        def indisponible(motif):
            # UN CRITÈRE QUI N'A PAS PU ÊTRE ÉVALUÉ (D-78) : il comptait comme
            # une simple information, et le point sortait CONFORME sans
            # critère de vent — alors que le Code IS l'impose à tout navire de
            # charge. Il pèse désormais : le verdict devient INCOMPLET.
            rep.add("VENT_ABSENT", "Critère de vent — non évaluable : " + motif,
                    float("nan"), float("nan"), ">=", groupe=titre)
            rep.messages.append(
                f"Voilure « {nom} » : {motif}. Le critère de vent n'est pas "
                "évalué pour ce point : le verdict est INCOMPLET.")

        if vent is None:
            indisponible(note or "surface au vent indisponible")
            return titre, rep
        if note:
            rep.messages.append(f"Voilure « {nom} » : {note}.")
        # la réglementation de CETTE situation : retenue par le navire, sinon
        # celle de la bibliothèque avec les conventions du dossier (D-79)
        situation = "sans_voile" if meteo else "sous_voile"
        retenue = self._retenue_de_situation(situation)
        if retenue is None:
            indisponible("aucune réglementation de vent dans la bibliothèque")
            return titre, rep
        ctx = self._contexte_regl(eq, gz, vent=vent, groupe=titre)
        if meteo:
            motifs = []

            def meteo_calc(critere, tables):
                wres, motif = self._resultat_meteo(eq, gz, vent, critere, tables)
                if motif:
                    motifs.append(motif)
                return wres, motif
            ctx.meteo = meteo_calc
        rep.fusionner(reglements.evaluer(retenue, ctx, groupe=titre))
        if not meteo:
            phrase = profils.phrase_du_plan(pid)
            if phrase:
                rep.messages.append(phrase)
        return titre, rep

    # ------------------------------------------------ les réglementations
    def _retenues(self):
        """Les réglementations retenues par le navire ouvert (D-79), lues une
        fois à l'ouverture ; un navire rechargé les relit."""
        cle = id(self.nav)
        if getattr(self, "_retenues_cle", None) != cle:
            self._retenues_cle = cle
            if self.nav is None:
                self._retenues_liste, msgs = [], []
            else:
                self._retenues_liste, msgs = reglements.reglements_du_navire(self.nav)
            for m in msgs:
                journal_technique.noter(m, "navire")
            self._retenues_messages = msgs
        return self._retenues_liste

    def _retenue_de_situation(self, situation):
        for x in self._retenues():
            if x.reglement.situation == situation:
                return x
        # le navire n'en a pas retenu : celle de la bibliothèque, avec les
        # conventions du dossier (le chemin d'avant la 3.0, à l'identique)
        regs, _m = reglements.bibliotheque()
        rid = "IMO_IS2008_A_2_3" if situation == "sans_voile" else "BV_NR500_SOUS_VOILE"
        cle = "critere_meteo" if situation == "sans_voile" else "nr500_voile_sous_voile"
        r = regs.get(rid)
        if r is None:
            return None
        bloc = (getattr(self.nav, "criteres", None) or {}).get(cle) or {}
        params = {k: v for k, v in bloc.items()
                  if k != "reference" and not str(k).startswith("note")}
        return reglements.Retenue(r, {}, params)

    def _contexte_regl(self, eq, gz, vent=None, groupe=""):
        return reglements.Contexte(
            navire=self.nav, eq=eq, gz=gz,
            theta_f_deg=getattr(self, "_theta_f", None), vent=vent,
            profil=reglements.profil_du_navire(self.nav), groupe=groupe)

    def _resultat_meteo(self, eq, gz, vent, critere=None, tables=None):
        """(WeatherResult, None) ou (None, motif) : le critère météo demande
        des dimensions principales (longueur de franc-bord, largeur) et un
        volume de carène que tout dossier ne porte pas. Sans elles, on le dit
        plutôt que de leur donner une valeur de remplissage."""
        dims = (getattr(self.nav, "manifest", None) or {}).get("dimensions", {})
        lwl = (dims.get("longueur_de_franc_bord_m")
               or dims.get("longueur_entre_pp_hydro_m") or 0.0)
        beam = dims.get("largeur_hors_membres_m") or 0.0
        if not lwl or not beam or eq.draft_m <= 0:
            return None, ("le dossier ne donne pas la longueur de franc-bord "
                          "ou la largeur hors membres, que demande le critère "
                          "météo")
        # LA LONGUEUR À LA FLOTTAISON du critère (période de roulis, Cb, k)
        # est celle de CETTE flottaison : le recueil du navire de référence
        # l'imprime cas par cas, de 64,6 à 66,4 m. Une table qui la porte (colonne LWL_m) la
        # donne ; sinon la longueur de franc-bord la remplace, et on le dit
        # (R-10, D-78).
        h = eq.hydro or {}
        lwl_table = next((h[c] for c in ("LWL_m", "Lwl_m", "L_flottaison_m")
                          if h.get(c)), None)
        approche_l = lwl_table is None
        if lwl_table:
            lwl = float(lwl_table)
        ak = dims.get("aire_quilles_anti_roulis_m2") or 0.0
        ak_pct = 100.0 * ak / (lwl * beam) if ak else 0.0
        volume = h.get("Volume_m3")
        cb = (hydrostatics.block_coefficient(float(volume), lwl, beam,
                                             eq.draft_m) if volume else 0.0)
        wres = weather.evaluate(
            self.nav, gz, eq, eq.displacement_t,
            vent["Windage_area_m2"], vent["Windage_V_m"],
            vent["Lateral_plane_V_m"], cb=cb, beam_m=beam, lwl_m=lwl,
            ak_pct_lb=ak_pct,
            theta_f_deg=getattr(self, "_theta_f", None),
            critere=critere, tables=tables)
        if approche_l:
            wres.messages.append(
                f"Critère météo : la longueur à la flottaison n'est pas tabulée — "
                f"la longueur de franc-bord ({lwl:.2f} m) la remplace dans la "
                "période de roulis et le coefficient de bloc (approché).")
        return wres, None

    def _refresh_voilure(self):
        """Remet la liste des voilures d'accord avec le navire et le point."""
        choix = getattr(self, "choix_voilure", None)
        if choix is None:
            return
        profils = getattr(self.nav, "profils_vent", None)
        condition = getattr(self, "condition", None)
        courant = getattr(condition, "voilure", None)
        choix.peupler(profils, courant)
        # une voilure que ce navire ne connaît pas (point venu d'un autre
        # bord) est ramenée sur celle qui sera réellement calculée : l'écran
        # ne doit pas montrer autre chose que ce qui a servi au verdict
        if profils and condition is not None:
            reel = profils.resoudre(courant)
            if reel and reel != courant:
                condition.voilure = reel
                choix.peupler(profils, reel)
        # un point figé est une archive : sa voilure ne se change plus
        fige = self.point is not None and bool(self.point.fige)
        choix.combo.setEnabled(not fige)

    def _on_voilure_changee(self, _index=0):
        """Le bord change de voilure : tout est recalculé, critère de vent
        compris, et le point est modifié — c'est une décision d'exploitation
        qui s'archive avec lui."""
        choix = self.choix_voilure
        pid = choix.courant()
        if not pid or pid == getattr(self.condition, "voilure", None):
            return
        if self.point is not None and self.point.fige:
            self._refresh_voilure()          # archive : rien ne change
            self.statusBar().showMessage(
                "Point figé : sa voilure ne se modifie plus. Créez un "
                "nouveau point (Ctrl+N) pour en changer.", 8000)
            return
        self.condition.voilure = pid
        self._dirty = True
        self.recompute()
        profils = getattr(self.nav, "profils_vent", None)
        nom = profils.nom(pid) if profils else pid
        self.statusBar().showMessage(
            f"Voilure « {nom} » : critères de vent recalculés avec la "
            "surface exposée de cette configuration.", 8000)

    def _reserves(self, gz, rep):
        """Ce qui limite la portée du verdict, dit en toutes lettres.

        Les aires sont désormais mesurées **depuis la gîte d'équilibre** : une
        bande permanente ne fausse plus le calcul, mais elle reste une
        information d'exploitation, et le reste des réserves (domaine des
        pantocarènes, θf, troncature de la courbe) vient du moteur lui-même."""
        lignes = list(rep.messages)
        # de la cargaison dans une cale que le plan ne connaît plus : elle est
        # comptée au plancher le plus haut (prudent), mais le bord doit le
        # savoir, et la reposer
        cond = getattr(self, "condition", None)
        proj = getattr(self, "project", None)
        if cond is not None and proj is not None:
            inconnues = cond.cales_inconnues(proj)
            if inconnues:
                lignes.insert(0,
                    "<b>Cargaison dans une cale que le plan ne connaît plus</b> "
                    f"({', '.join(inconnues)}) : son poids est compté au "
                    "plancher le plus haut du navire, faute de savoir où elle "
                    "est. Reposez-la dans une cale du plan.")
        if gz.origine_deg is not None and abs(gz.origine_deg) > 0.5:
            lignes.insert(0,
                f"Le navire flotte à {gz.origine_deg:+.1f}° de gîte "
                "permanente. Les aires ci-dessous sont mesurées depuis cette "
                "position et du côté où il est couché — c'est la stabilité "
                "qu'il lui reste, pas celle d'un navire droit.")
        return "<br>".join("• " + m for m in lignes)

    def _details_flottaison(self, poids, lcg, tcg, vcg, fsm, eq, gz):
        """Le détail chassé du bandeau : tout ce qu'on consulte au moment de
        justifier un cas, mais qu'on n'a pas besoin de lire en permanence."""
        h = eq.hydro or {}

        def val(col, fmt="{:.3f}", unite=""):
            v = h.get(col)
            return "—" if v is None else (fmt.format(float(v)) + unite)

        gite = ("aucun équilibre stable" if self._gite is None
                else f"{self._gite:+.2f}°")
        tf = getattr(self, "_theta_f", None)
        return [
            ("Tirant d'eau milieu", f"{eq.draft_m:.3f} m"),
            ("Tirant d'eau arrière", _te(eq, "TE_AR_m")),
            ("Tirant d'eau avant", _te(eq, "TE_AV_m")),
            ("Assiette", f"{eq.trim_m:+.3f} m"),
            ("Gîte d'équilibre", gite),
            ("Déplacement", f"{poids:,.2f} t".replace(",", " ")),
            # le port en lourd : ce qui est à bord en plus du navire lège
            ("Port en lourd",
             (f"{poids - float(self.nav.lege['masse_t']):,.2f} t".replace(",", " ")
              if (self.condition.inclure_lege and self.nav is not None
                  and self.nav.lege.get("masse_t")) else "— (lège non inclus)")),
            ("LCG / LCB", f"{lcg:.3f} m / {eq.lcb_m:.3f} m"),
            ("Centre de flottaison LCF", val("LCF_m", unite=" m")),
            ("TPC", val("TPC_t_cm", "{:.2f}", " t/cm")),
            ("MCT", val("MCT_tm_cm", "{:.2f}", " t.m/cm")),
            ("KG solide (VCG)", f"{vcg:.3f} m"),
            ("Carènes liquides ΣFSM", f"{fsm:.2f} t.m"),
            ("KG effectif", f"{gz.kg_effectif_m:.3f} m"),
            ("KMt", val("KMt_m", unite=" m")),
            ("GM solide", f"{gz.gm_solide_m:.3f} m"),
            ("GM corrigé", f"{gz.gm_corrige_m:.3f} m"),
            ("TCG", f"{tcg:+.3f} m"),
            # angles comptés depuis la gîte d'équilibre, comme les critères
            ("GZ max résiduel", f"{gz.gz_max_m:.3f} m"),
            ("Angle du GZ max / équilibre", f"{gz.angle_gz_max_deg:.1f}°"),
            ("Angle du GZ max / verticale",
             f"{gz.angle_gz_max_absolu_deg:+.1f}°"),
            ("Annulation / équilibre", "—" if gz.angle_annulation_deg is None
             else f"{gz.angle_annulation_deg:.1f}°"),
            ("Angle d'envahissement θf (approché : muraille verticale, ≈ 3° sous le calcul sur coque)",
             "—" if tf is None else f"{tf:.1f}°"),
            ("Itérations d'équilibre", str(eq.iterations)),
        ]

    def _refresh_banner(self, poids=None, eq=None, gz=None, rep=None,
                        converged=True):
        folder = app_paths.ship_folder()
        nom = app_paths.ship_name(folder) or self.project.ship_name
        self.lbl_ship.setText(nom or "Aucun navire")
        self._refresh_combo_point()
        self._refresh_voilure()
        self.pill_fige.setVisible(self.point is not None and bool(self.point.fige))
        if eq is None:
            for f in self.figures:
                f.set("—")
            self.pill_verdict.setText("—")
            self.pill_verdict.setProperty("tone", "todo")
        else:
            self.fig_depl.set(f"{poids:,.1f} t".replace(",", " "))
            self.fig_te_ar.set(_te(eq, "TE_AR_m"))
            self.fig_te_av.set(_te(eq, "TE_AV_m"))
            self.fig_trim.set(f"{eq.trim_m:+.3f} m")
            # None = aucune gîte d'équilibre stable : on ne l'arrondit pas à 0°
            self.fig_gite.set("—" if self._gite is None
                              else f"{self._gite:+.1f}°")
            self.fig_gite.value.setStyleSheet(
                "font-size: 14px; font-weight: bold; background: transparent;"
                + ("" if self._gite is None or abs(self._gite) < 5
                   else f" color: {theme.DANGER};"))
            self.fig_gm.set(f"{gz.gm_corrige_m:.3f} m")
            if not converged:      # « fiable » : convergé ET dans le domaine
                self.pill_verdict.setText("HORS DOMAINE")
                self.pill_verdict.setProperty("tone", "warn")
            else:
                # CONFORME / NON CONFORME / INCOMPLET / NON ÉVALUABLE : le mot
                # vient du rapport de critères, le même pour le rapport imprimé
                # (D-78). « INCOMPLET » : tout ce qui a pu être évalué passe,
                # mais un critère manque — ce n'est pas un « CONFORME ».
                verdict = rep.verdict
                self.pill_verdict.setText(verdict)
                self.pill_verdict.setProperty("tone", "ok" if verdict == "CONFORME" else "warn")
        self.pill_verdict.style().unpolish(self.pill_verdict)
        self.pill_verdict.style().polish(self.pill_verdict)
        self._refresh_barre_stabilite(rep if eq is not None else None)

    # ------------------------------------------------------------------ divers
    def regler_infobulles(self, visibles):
        """*Affichage › Infobulles d'aide* : retenu dans la configuration."""
        app_paths.set_infobulles(bool(visibles))
        FiltreInfobulles.installer(bool(visibles))
        self.statusBar().showMessage(
            "Infobulles d'aide " + ("affichées." if visibles else
                                    "éteintes — celles du plan restent."), 5000)

    def retheme_tout(self):
        """Redessine ce qui porte une couleur du thème — après un changement
        de palette. Il n'y a plus qu'une palette (D-72) ; la méthode reste
        pour les outils de capture qui repeignent tout d'un coup."""
        app = QApplication.instance()
        if app is None:
            return
        theme.apply_theme(app)
        for a, nom in self._actions_icones:
            a.setIcon(theme.icon(nom))
        for f in self.figures:
            f.retheme()
        self.choix_voilure.retheme()
        self.lbl_sous_titre.setStyleSheet(f"color: {theme.TEXT_DIM}; font-size: 13px;")
        dirty = self._dirty
        self._refresh_saisies()
        self.recompute()
        self._dirty = dirty
        self.results_panel.chart.update()
        aide = getattr(self, "_aide", None)
        if aide is not None:
            try:
                aide.retheme()
            except RuntimeError:                # fenêtre déjà fermée
                self._aide = None

    def ouvrir_aide(self, page="index.md"):
        """*Aide › Aide de Carène…* (`F1`) : le mode d'emploi, dans le
        logiciel.

        Fenêtre non modale : les plans restent cliquables pendant qu'on lit.
        `page` permet d'arriver droit sur un sujet — c'est ce que font les
        boutons « ? » du répartiteur et de l'éditeur de plans, et le bouton
        « Lire d'abord l'aide… » de l'écran sans navire (D-74)."""
        from .aide_dialog import ouvrir_aide
        return ouvrir_aide(self, page)

    def montrer_journal(self):
        """*Aide › Journal technique…* : ce que Carène a noté, à l'écran.

        Le bord n'a pas de console sous les yeux : sans cette fenêtre, la
        seule façon de rapporter un incident serait d'aller chercher un
        fichier dans un dossier dont personne ne connaît le chemin. On montre
        donc le chemin, la fin du journal, et un bouton qui copie le tout."""
        from . import journal_technique
        dlg = QDialog(self)
        dlg.setWindowTitle("Journal technique")
        dlg.resize(900, 560)
        lay = QVBoxLayout(dlg)
        chemin = journal_technique.chemin()
        entete = QLabel(
            ("Fichier : <code>%s</code>" % chemin) if chemin else
            "Le journal n'a pas pu être ouvert (dossier non inscriptible).")
        entete.setObjectName("hint")
        entete.setWordWrap(True)
        entete.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction)
        lay.addWidget(entete)
        texte = QPlainTextEdit(journal_technique.dernieres_lignes())
        texte.setReadOnly(True)
        texte.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        police = texte.font()
        police.setFamily("Consolas" if sys.platform == "win32" else "monospace")
        police.setPointSize(9)
        texte.setFont(police)
        texte.moveCursor(QTextCursor.MoveOperation.End)
        lay.addWidget(texte, 1)
        aide = QLabel(
            "Le journal note la version lancée, ce que Qt signale et toute "
            "erreur non rattrapée — jamais le contenu d'un chargement. "
            "Un fichier par jour, les dix derniers gardés.")
        aide.setObjectName("hint")
        aide.setWordWrap(True)
        lay.addWidget(aide)
        ligne = QHBoxLayout()
        b_copier = QPushButton("Copier tout")
        b_copier.clicked.connect(
            lambda: QApplication.clipboard().setText(texte.toPlainText()))
        b_dossier = QPushButton("Ouvrir le dossier")
        b_dossier.setProperty("ghost", "1")
        b_dossier.setEnabled(bool(chemin))
        b_dossier.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(journal_technique.dossier())))
        b_fermer = QPushButton("Fermer")
        b_fermer.setProperty("accent", "1")
        b_fermer.clicked.connect(dlg.accept)
        ligne.addWidget(b_copier)
        ligne.addWidget(b_dossier)
        ligne.addStretch(1)
        ligne.addWidget(b_fermer)
        lay.addLayout(ligne)
        dlg.exec()

    # ------------------------------------------------------- mises à jour
    def regler_maj_lancement(self, coche):
        app_paths.set_verifier_maj_au_lancement(bool(coche))
        self.statusBar().showMessage(
            "Les mises à jour seront vérifiées au lancement." if coche
            else "Plus de vérification au lancement — Aide › Vérifier les "
                 "mises à jour… reste disponible.", 6000)

    def regler_serveur_maj(self):
        """*Aide › Serveur des mises à jour…* (D-85)."""
        from .mise_a_jour_dialog import ServeurMajDialog
        dlg = self._serveur_maj_dlg = ServeurMajDialog(self)
        dlg.show()
        dlg.raise_()
        return dlg

    def verifier_mises_a_jour(self, au_lancement=False, ouvrir=None):
        """*Aide › Vérifier les mises à jour…* (D-70), et le lancement.

        La vérification tourne dans un fil ; la suite (`_apres_verification`)
        revient sur le fil de l'interface. Rend la tâche, pour les tests.
        Hors écran sans accès injecté (`ouvrir`), on ne parle pas au vrai
        GitHub : la vérification est dite « hors ligne »."""
        from .mise_a_jour_dialog import verifier_en_arriere_plan
        from .core import mise_a_jour as MAJ
        app = QApplication.instance()
        if ouvrir is None and app is not None and app.property("carene_tests"):
            def ouvrir(_url, _delai):
                raise OSError("pas de réseau dans les tests")
        self._maj_au_lancement = bool(au_lancement)
        if not au_lancement:
            self.statusBar().showMessage(
                f"Vérification des mises à jour sur {app_paths.source_maj()}…")
        self._tache_maj = verifier_en_arriere_plan(self, self._apres_verification,
                                                   ouvrir=ouvrir)
        self._ouvrir_maj = ouvrir
        return self._tache_maj

    def _apres_verification(self, v):
        """Ce qu'on fait du résultat : une ligne, ou la fenêtre."""
        self.derniere_verification_maj = v
        journal_technique.noter("mise à jour : " + v.phrase(),
                                "erreur" if v.erreur else "info")
        au_lancement = getattr(self, "_maj_au_lancement", False)
        if v.disponible:
            from .mise_a_jour_dialog import MiseAJourDialog
            dlg = getattr(self, "_maj_dlg", None)
            try:
                if dlg is not None:
                    dlg.isVisible()
            except RuntimeError:
                dlg = None
            if dlg is None:
                dlg = self._maj_dlg = MiseAJourDialog(self, v, ouvrir=self._ouvrir_maj)
            dlg.show()
            dlg.raise_()
            self.statusBar().showMessage(v.phrase(), 15000)
            return dlg
        # pas de mise à jour, ou pas moyen de le savoir : une ligne, jamais
        # une boîte — surtout au lancement
        duree = 15000 if not v.a_pu_avoir_lieu else 8000
        self.statusBar().showMessage(v.phrase(), duree)
        if not au_lancement and self._confirmations_actives():
            QMessageBox.information(self, "Mises à jour", v.phrase())
        return None

    def open_bug(self):
        """*Aide › Signaler un problème…* — le formulaire de signalement.

        Il s'ouvre aussi quand rien ne va plus : c'est pourquoi il ne demande
        rien à la fenêtre (le navire peut manquer, le calcul peut avoir
        échoué) et joint ce qu'il trouve."""
        from .bug_dialog import BugDialog
        dlg = BugDialog(self, self)
        dlg.exec()
        dlg.deleteLater()
        return dlg

    def about(self):
        from . import AVERTISSEMENT, __copyright__, __version__
        from .core.rapport_bug import CONTACT
        QMessageBox.about(
            self, "À propos de Carène",
            f"<b>Carène</b> {__version__}<br><br>"
            "Chargement et stabilité.<br>"
            "Une installation = un navire.<br><br>"
            "Les tables, capacités et plans se saisissent dans "
            "<i>Navire › Créer ou modifier le navire…</i><br><br>"
            "Un problème ? <i>Aide › Signaler un problème…</i> — sur GitHub : "
            f"<a href='{CONTACT}'>{CONTACT}</a><br><br>"
            f"<span style='color:#888'>{__copyright__} — tous droits réservés.<br><br>"
            f"{AVERTISSEMENT}</span>")


def avertir_au_lancement(win):
    """Le rappel de ce qu'est le logiciel, une fois par lancement — jamais
    dans les tests ni les captures (voir main())."""
    from . import AVERTISSEMENT, MENTION
    from .core.rapport_bug import CONTACT
    QMessageBox.information(
        win, "Carène — avertissement",
        f"<b>{AVERTISSEMENT}</b><br><br>"
        "Les résultats affichés dépendent des tables du dossier du navire et "
        "des relevés saisis à bord ; toute valeur extrapolée ou approchée est "
        "signalée comme telle à l'écran.<br><br>"
        # D-63 : l'invitation est ICI, dans le seul message que tout le monde
        # lit — un bogue qu'on ne signale pas ne se corrige pas.
        "<b>Un problème, un chiffre douteux, une fenêtre qui se ferme ?</b> "
        "Dites-le : <i>Aide › Signaler un problème…</i> prépare le message, "
        f"avec ce qui tournait et le journal technique, et l'ouvre sur GitHub : "
        f"<a href='{CONTACT}'>{CONTACT}</a>.<br><br>"
        f"<span style='color:#888'>{MENTION}</span>")


class FiltreInfobulles(QObject):
    """Éteint les infobulles d'aide de TOUTE l'application, sauf sur les vues
    graphiques.

    Le bord ne veut plus voir les bulles d'aide au survol des boutons et des
    champs. Un filtre sur l'application avale l'événement ToolTip avant qu'un
    bouton ne le voie. Les vues graphiques (plan de pose, vue navire, éditeur
    de plans) sont exemptées : leur bulle dit ce qui est SOUS la souris — un
    colis, une épontille, son état — et ce n'est pas de l'aide, c'est le
    chargement. Un interrupteur dans *Affichage* rend l'aide à qui la veut."""

    _instance = None

    def __init__(self):
        super().__init__()
        self.actif = False        # True : les infobulles d'aide sont ÉTEINTES

    def eventFilter(self, obj, event):
        if self.actif and event.type() == QEvent.Type.ToolTip \
                and not isinstance(obj, QGraphicsView):
            return True
        return False

    @classmethod
    def installer(cls, infobulles_visibles):
        app = QApplication.instance()
        if app is None:
            return None
        if cls._instance is None:
            cls._instance = cls()
            app.installEventFilter(cls._instance)
        cls._instance.actif = not bool(infobulles_visibles)
        return cls._instance


def franciser(app):
    """Charge la traduction française de Qt, si elle est là.

    Sans elle, les boutons standard des boîtes de dialogue (« Close »,
    « Cancel ») s'affichent en anglais au milieu d'une interface française.
    On n'échoue pas si le fichier manque — en exécutable gelé il peut ne pas
    avoir été embarqué, et une interface à moitié anglaise vaut mieux qu'un
    démarrage impossible. Le traducteur est gardé sur l'application : un
    QTranslator détruit par le ramasse-miettes ne traduit plus rien.
    """
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
    tr = QTranslator(app)
    dossier = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if tr.load(QLocale("fr"), "qtbase", "_", dossier):
        app.installTranslator(tr)
        app._traducteur_qt = tr
        return True
    return False


def main():
    # Le journal technique s'ouvre AVANT tout le reste : un plantage à
    # l'ouverture de la fenêtre doit être noté lui aussi, et la première
    # ligne du journal dit quelle copie du code tourne (deux fois déjà, un
    # message d'erreur du bord venait d'une version précédente restée sur le
    # bureau).
    journal_technique.installer()
    # Installation vierge : le navire d'exemple livré (`navires/*.exemple`)
    # devient le navire de l'installation, une fois pour toutes. Un navire
    # déjà là n'est jamais touché — c'est ce qui permet de décompresser une
    # mise à jour par-dessus l'ancienne sans perdre le dossier du bord.
    if app_paths.installer_navire_exemple():
        journal_technique.noter(app_paths.DERNIER_MESSAGE_EXEMPLE, "navire")
    elif app_paths.DERNIER_MESSAGE_EXEMPLE:
        journal_technique.noter(app_paths.DERNIER_MESSAGE_EXEMPLE, "erreur")
    app = QApplication(sys.argv)
    franciser(app)
    theme.apply_theme(app, "light")
    # UN SEUL CARÈNE PAR POSTE, et on le vérifie AVANT de construire la
    # fenêtre : deux instances lisent le même journal au lancement et
    # s'écrasent l'une l'autre en enregistrant — le travail d'une escale
    # disparaîtrait sans un mot. Le second lance le premier au premier plan
    # (c'est ce qu'on voulait en double-cliquant sur l'icône) et se retire.
    verrou = app_paths.verrou_instance()
    if not verrou.obtenu:
        leve = app_paths.reveiller_linstance_ouverte()
        journal_technique.noter(
            "Deuxième instance refusée : le verrou est tenu"
            + (f" ({verrou.detenteur})" if verrou.detenteur else "")
            + (" ; la fenêtre ouverte a été ramenée au premier plan."
               if leve else " ; l'autre fenêtre n'a pas répondu."),
            # c'est le comportement VOULU, pas une panne : le ranger en
            # « erreur » faisait chercher un problème là où il n'y en a pas
            "info")
        QMessageBox.information(
            None, "Carène est déjà ouvert",
            "Carène est déjà ouvert sur ce poste"
            + (" (fenêtre ramenée au premier plan)." if leve else
               ".\n\nSi vous ne la voyez pas, cherchez-la dans la barre des tâches.")
            + "\n\nDeux instances écriraient dans le même journal.")
        sys.exit(0)
    regler_la_fermeture(app)
    win = MainWindow()
    win.show()
    # le guichet n'existe qu'une fois la fenêtre là : c'est elle qu'on lève
    verrou.ecouter(win)
    app._verrou_carene = verrou      # gardé vivant tant que l'application tourne
    # le navire est tenu par un autre poste (D-55) : on le dit AVANT tout,
    # et on laisse le choix — consulter sans écrire, ou s'en aller
    if win.lecture_seule and not demander_lecture_seule(win):
        win.close()
        sys.exit(0)
    # les questions du lancement se posent DANS la boucle d'événements, pas
    # avant elle : une boîte modale fermée avant `app.exec()` est un cas
    # limite que chaque système traite à sa façon
    QTimer.singleShot(0, lambda: (avertir_au_lancement(win),
                                  win.demander_point_de_travail(),
                                  verifier_au_lancement(win)))
    sys.exit(app.exec())


def verifier_au_lancement(win):
    """La vérification de mise à jour du lancement (D-70), si elle est
    voulue : après les questions du lancement, jamais avant, et dans un fil —
    sans réseau, la barre d'état dira qu'elle n'a pas pu avoir lieu."""
    if app_paths.verifier_maj_au_lancement():
        win.verifier_mises_a_jour(au_lancement=True)


def regler_la_fermeture(app):
    """CARÈNE NE SE FERME QUE PAR SA FENÊTRE PRINCIPALE.

    Sans cela, Qt quitte de lui-même dès qu'il croit la dernière fenêtre
    fermée — et le bord a vu Carène se fermer entier en fermant la boîte du
    choix du point (« la fenêtre du journal »). Aucune fenêtre secondaire
    (choix du point, journal technique, éditeurs, sauvegarde) ne doit pouvoir
    emporter l'application : c'est `MainWindow.closeEvent`, et lui seul, qui
    quitte — après la confirmation."""
    app.setQuitOnLastWindowClosed(False)


def demander_lecture_seule(win):
    """Le navire est ouvert ailleurs : consulter en lecture seule, ou quitter ?
    Vrai pour continuer en lecture seule."""
    v = win.verrou_navire
    ou = v.detenteur.phrase() if v is not None and v.detenteur is not None else "ailleurs"
    boite = QMessageBox(win)
    boite.setIcon(QMessageBox.Icon.Warning)
    boite.setWindowTitle("Carène est déjà ouvert sur ce navire")
    boite.setText(
        f"Ce navire est déjà ouvert {ou}.\n\n"
        "Deux Carène qui écrivent dans le même journal s'écrasent l'un l'autre. "
        "Vous pouvez CONSULTER le navire d'ici (rien ne s'enregistrera), ou "
        "quitter et reprendre sur l'autre poste.\n\n"
        "Si plus personne n'y travaille (poste éteint, planté), le verrou sera "
        "tenu pour périmé au bout de trois minutes sans signe de vie : relancez "
        "Carène alors, il proposera de le reprendre.")
    reprendre = None
    if v is not None and getattr(v, "perime_ailleurs", False) and v.detenteur is not None:
        age = v.detenteur.age_s
        minutes = "" if age is None else f" depuis {age / 60:.0f} min"
        boite.setText(
            f"Ce navire est resté ouvert {ou}, mais ce poste ne donne plus "
            f"signe de vie{minutes} (mesuré sur l'horloge du disque partagé).\n\n"
            "Il a peut-être planté — ou il est seulement en veille, ou coupé du "
            "réseau. Ne le reprenez que si vous êtes sûr que personne n'y "
            "travaille : l'autre poste passera en lecture seule, et ce qu'il "
            "n'a pas enregistré sera perdu.")
        reprendre = boite.addButton("Reprendre le navire", QMessageBox.ButtonRole.DestructiveRole)
    consulter = boite.addButton("Consulter en lecture seule", QMessageBox.ButtonRole.AcceptRole)
    quitter = boite.addButton("Quitter", QMessageBox.ButtonRole.RejectRole)
    boite.setDefaultButton(quitter)
    boite.exec()
    if reprendre is not None and boite.clickedButton() is reprendre:
        v.repris_de = v.detenteur
        v.reprendre()
        win.lecture_seule = not v.tenu
        win._refresh_lecture_seule()
        if v.tenu:
            journal_technique.noter(
                f"Verrou du navire repris à la demande ({ou}).", "navire")
        return True
    return boite.clickedButton() is consulter
