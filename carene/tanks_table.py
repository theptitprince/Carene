# -*- coding: utf-8 -*-
"""Le relevé des capacités, en tableau groupé — façon « weight list » LOCOPIAS.

Un seul tableau : celui de la vue Capacités, à côté de la vue de situation.

Trois colonnes de mesure — **sonde**, **volume**, **pourcentage** — et une
seule vérité : celle qu'on tape. Taper dans l'une des trois met les deux
autres à jour, en passant par la table de jaugeage du navire ; la colonne
saisie reste marquée comme étant le relevé, les deux autres sont affichées en
gris parce qu'elles en découlent. C'est ce que fait la colonne « Measured » de
LOCOPIAS, et c'est ce qui permet de retrouver plus tard ce que le bord a
réellement lu.

La **densité** se tape ici aussi, dans sa propre colonne. Elle n'est pas une
mesure de plus : c'est celle qui fait du volume relevé un poids. Le dossier
donne la densité du produit PRÉVU ; le bord embarque de l'eau saumâtre ou un
gazole à 0,84 selon la livraison, et il doit pouvoir le dire sans toucher au
dossier du navire. Une case vide veut dire « celle du dossier ».

Les lignes sont regroupées par nature (`core.groupes`), avec un sous-total par
groupe. Un clic suffit pour modifier une valeur.

Rien n'est calculé ici : poids, centres et carène liquide sont lus dans les
tables de jaugeage du dossier.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
)

from . import theme
from .saisie import DelegueSansTiret
from .bilan import densite_texte
from .condition_model import POURCENT, SONDE, VOLUME
from .core.groupes import grouper

# Bornes de saisie de la densité. Ce ne sont pas des seuils de calcul : le
# moteur pèse ce qu'on lui donne (voir `Capacity.avec_densite`). Elles
# n'arrêtent qu'une faute de frappe — une densité nulle ou négative n'a pas de
# sens, et au-delà de 3 t/m³ on n'est plus devant un liquide de bord (le
# mercure est à 13,5, mais personne n'en soute).
DENSITE_MINI = 0.0
DENSITE_MAXI = 3.0

# La densité est à côté du contenu, avant les mesures : c'est elle qui fait
# du volume relevé un poids — ce qui intéresse le bord, c'est le poids.
COLS = ["Capacité", "Contenu", "d", "Sonde m", "Volume m³", "%",
        "Poids t", "VCG m", "LCG m", "TCG m", "FSM t·m"]
C_NOM, C_CONTENU, C_D, C_SONDE, C_VOL, C_PC, C_POIDS, C_VCG, C_LCG, C_TCG, C_FSM = range(11)
MESURES = {C_SONDE: SONDE, C_VOL: VOLUME, C_PC: POURCENT}
UNITES = {C_SONDE: "m", C_VOL: "m³", C_PC: "%"}
COLONNE_JAUGE = {C_SONDE: "Sondage_m", C_VOL: "Volume_m3", C_PC: "Remplissage_pc"}

# Une teinte par groupe, comme LOCOPIAS colore ses « weight groups » : elle
# sert à retrouver un groupe d'un coup d'œil dans une liste de trente lignes.
# Posée en fond très clair, elle tient dans les deux thèmes.
TEINTES = {
    "Eau douce": (60, 160, 210),
    "Combustible": (215, 120, 40),
    "Ballast": (45, 110, 200),
    "Huiles": (150, 140, 40),
    "Eaux usées": (140, 90, 60),
    "Eaux de cale et boues": (120, 80, 130),
    "Urée": (190, 175, 40),
    "Boues": (120, 80, 130),
    "GNL": (60, 165, 150),
}
TEINTE_DEFAUT = (110, 120, 130)


def teinte(groupe):
    return TEINTES.get(groupe, TEINTE_DEFAUT)


def est_slack(pc):
    """Même borne que le moteur (`core.condition.totals`) et le bilan : une
    capacité est en carène liquide dès qu'elle n'est ni vide ni pleine."""
    return 0.0 < float(pc) < 100.0


def fsm_compte(ligne, cap, nav):
    """Le moment de carène liquide que le moteur COMPTE pour cette ligne de
    jauge — 0 si la capacité n'est pas slack, sinon selon la convention du
    dossier (« max » : FSM maximal ; « reel » : FSM tabulé au remplissage).
    C'est ce chiffre que le tableau doit totaliser, pas la colonne brute.

    `cap` doit être la capacité TELLE QUE CHARGÉE (`TankFill.capacite_chargee`)
    et non celle du dossier : le FSM suit la densité du point, le maximal comme
    le tabulé, et les deux branches ci-dessous doivent rester à la même
    échelle — sinon la convention « max » pèserait le produit du dossier."""
    if ligne is None or cap is None or not est_slack(ligne["Remplissage_pc"]):
        return 0.0
    if getattr(nav, "convention_fsm", "max") == "reel":
        return float(ligne.get("FSM_tm", cap.fsm_max_tm))
    return float(cap.fsm_max_tm)


class _UnClic(DelegueSansTiret):
    """Ouvre l'éditeur au premier clic, et sélectionne le contenu.

    Sans cela, Qt demande un double-clic (ou un clic sur une cellule déjà
    sélectionnée) : à trente capacités relevées d'affilée, cela double le
    nombre de clics de l'escale."""

    def setEditorData(self, editor, index):
        super().setEditorData(editor, index)      # « — » : champ vide (D-89)
        if hasattr(editor, "selectAll"):
            editor.selectAll()


class TanksTable(QTableWidget):
    """Le relevé, groupé par nature, avec ses trois colonnes de mesure."""

    changed = Signal()
    message = Signal(str)
    tank_selected = Signal(object)          # TankFill, ou None

    def __init__(self, win, parent=None):
        super().__init__(0, len(COLS), parent)
        self.win = win
        self._loading = False
        self._lignes = []                    # par rangée : ("groupe"|"tank"|"total", …)
        # rangée -> nom du groupe (eau douce, combustible, ballast…) : le menu
        # contextuel en a besoin pour « appliquer à tout le groupe », et
        # `_lignes` garde ses triplets, sur lesquels d'autres vues comptent
        self._groupe_de_rangee = {}

        self.setHorizontalHeaderLabels(COLS)
        head = self.horizontalHeader()
        head.setSectionResizeMode(C_NOM, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(C_NOM, 122)
        # largeur fixe partout : la vue Capacités est étroite, et une colonne
        # étirée y mangeait le FSM. La fenêtre de relevé, elle, a la place.
        head.setSectionResizeMode(C_CONTENU, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(C_CONTENU, 128)
        head.setMinimumSectionSize(42)
        head.setStretchLastSection(True)
        LARGEURS = {C_SONDE: 78, C_VOL: 78, C_PC: 60, C_POIDS: 70,
                    C_VCG: 66, C_LCG: 66, C_TCG: 66, C_FSM: 70, C_D: 52}
        for c, w in LARGEURS.items():
            head.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
            self.setColumnWidth(c, w)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # un seul clic ouvre l'éditeur ; les colonnes non modifiables ne
        # réagissent pas, leurs cellules n'ayant pas le drapeau d'édition
        self.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        self.setItemDelegate(_UnClic(self))
        self.itemChanged.connect(self._on_edit)
        self.itemSelectionChanged.connect(self._on_select)
        # le clic droit sert les gestes de densité : revenir au dossier, ou
        # donner la même densité à tout un groupe (une livraison de gazole a
        # UNE densité, pas une par soute)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu_contextuel)

    # ------------------------------------------------------------- modèle
    @property
    def condition(self):
        return self.win.condition

    def _nav(self):
        return getattr(self.win, "nav", None)

    def choisir_capacite(self, code):
        """Sélectionne la ligne de cette capacité (clic dans la vue 3D, D-87).
        Rend True si elle est au relevé."""
        for r, (genre, objet, *_reste) in enumerate(self._lignes):
            if genre == "tank" and getattr(objet, "capacite", None) == code:
                self.setCurrentCell(r, 0)
                self.scrollToItem(self.item(r, 0))
                return True
        return False

    def tank_courant(self):
        r = self.currentRow()
        if 0 <= r < len(self._lignes) and self._lignes[r][0] == "tank":
            return self._lignes[r][1]
        return None

    # ------------------------------------------------------------- rendu
    def _item(self, texte, alignement_droite=True, editable=False):
        it = QTableWidgetItem(texte)
        if alignement_droite:
            it.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                | Qt.AlignmentFlag.AlignVCenter)
        if not editable:
            it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        return it

    def refresh(self):
        """Reconstruit le tableau depuis le relevé courant."""
        self._loading = True
        self.setUpdatesEnabled(False)
        try:
            self._construire()
        finally:
            self.setUpdatesEnabled(True)
            self._loading = False

    def _construire(self):
        nav = self._nav()
        caps = getattr(nav, "capacities", {}) if nav else {}
        tanks = {t.capacite: t for t in self.condition.tanks}
        groupes = grouper([t.capacite for t in self.condition.tanks], caps)

        lignes = []
        groupe_de_rangee = {}
        for nom_groupe, noms in groupes:
            groupe_de_rangee[len(lignes)] = nom_groupe
            lignes.append(("groupe", nom_groupe, noms))
            for nom in noms:
                groupe_de_rangee[len(lignes)] = nom_groupe
                lignes.append(("tank", tanks[nom], caps.get(nom)))
        if lignes:
            lignes.append(("total", None, None))
        self._lignes = lignes
        self._groupe_de_rangee = groupe_de_rangee
        self.clearSpans()
        self.setRowCount(len(lignes))

        # totaux, calculés d'abord pour pouvoir garnir les lignes de groupe
        agr = {}
        total = _Agregat()
        for nom_groupe, noms in groupes:
            a = _Agregat()
            for nom in noms:
                a.ajouter(tanks[nom], nav)
            agr[nom_groupe] = a
            total.fusionner(a)

        r = 0
        for genre, a, b in lignes:
            if genre == "groupe":
                self._poser_groupe(r, a, agr.get(a, _Agregat()))
            elif genre == "tank":
                self._poser_tank(r, a, b, nav)
            else:
                self._poser_total(r, total)
            r += 1
        self._total = total

    def _poser_groupe(self, r, nom, a):
        # le nom court sur les deux premières colonnes, comme LOCOPIAS fait
        # courir le sien sur la colonne « Name » : « — COMBUSTIBLE » ne doit
        # jamais s'abréger
        self.setSpan(r, C_NOM, 1, 2)
        coul = QColor(*teinte(nom))
        fond = QColor(coul)
        fond.setAlpha(46 if theme.MODE == "light" else 62)
        vals = {C_NOM: "— " + nom.upper(),     # la 2e cellule est absorbée par le span
                C_VOL: f"{a.volume:.2f}" if a.volume else "",
                C_PC: f"{a.pc_moyen:.1f}" if a.poids else "",
                C_POIDS: f"{a.poids:.2f}" if a.poids else "",
                C_VCG: f"{a.vcg:.2f}" if a.poids else "",
                C_LCG: f"{a.lcg:.2f}" if a.poids else "",
                C_TCG: f"{a.tcg:+.2f}" if a.poids else "",
                C_FSM: f"{a.fsm:.2f}" if a.fsm else ""}
        for c in range(len(COLS)):
            v = vals.get(c, "")
            it = self._item(v, alignement_droite=(c >= C_SONDE))
            f = QFont(it.font())
            f.setBold(True)
            it.setFont(f)
            it.setBackground(fond)
            if c == C_NOM:
                it.setForeground(coul.darker(140) if theme.MODE == "light"
                                 else coul.lighter(150))
            it.setToolTip(f"Sous-total du groupe « {nom} » "
                          f"({a.n} capacité(s), {a.n_slack} en carène liquide).")
            self.setItem(r, c, it)

    def _poser_tank(self, r, t, cap_dossier, nav):
        ligne = t.ligne(nav)
        # la capacité TELLE QUE CHARGÉE : poids, FSM tabulé et FSM maximal en
        # sortent à la densité du point. `cap_dossier` ne sert plus qu'à dire
        # de quelle densité on s'écarte.
        cap = t.capacite_chargee(nav) if cap_dossier is not None else None
        contenu = _contenu(cap) if cap is not None else "capacité inconnue du navire"
        self.setItem(r, C_NOM, self._item(t.capacite, alignement_droite=False))
        self.setItem(r, C_CONTENU, self._item(contenu, alignement_droite=False))

        # --- les trois colonnes de mesure ---------------------------------
        for c in (C_SONDE, C_VOL, C_PC):
            saisissable = cap is not None and (c != C_SONDE or cap.a_sondage)
            if ligne is None:
                txt = f"{t.valeur:g}" if MESURES[c] == t.mesure else "—"
            else:
                txt = _fmt(float(ligne[COLONNE_JAUGE[c]]), c)
            it = self._item(txt, editable=saisissable)
            releve = (MESURES[c] == t.mesure)
            if releve:
                f = QFont(it.font())
                f.setBold(True)
                it.setFont(f)
                it.setToolTip("C'est la valeur relevée à bord ; les deux autres "
                              "colonnes en découlent par la table de jaugeage.")
            else:
                it.setForeground(QColor(theme.TEXT_DIM))
                it.setToolTip("Déduit de la table de jaugeage. Tapez ici pour "
                              "relever cette grandeur à la place.")
            if not saisissable:
                it.setForeground(QColor(theme.TEXT_FAINT))
                it.setToolTip("Cette capacité n'a pas de colonne de sondage "
                              "dans le dossier : relevez le volume ou le "
                              "pourcentage.")
            self.setItem(r, c, it)

        # --- ce que le dossier en dit -------------------------------------
        if ligne is not None:
            pct = float(ligne["Remplissage_pc"])
            # la colonne FSM montre ce que le moteur compte (0 hors slack,
            # convention du dossier sinon) : le total du tableau est alors
            # celui du calcul, et non une somme de valeurs brutes de jauge
            fsm = fsm_compte(ligne, cap, nav)
            valeurs = [f"{float(ligne['Poids_t']):.2f}", f"{float(ligne['VCG_m']):.2f}",
                       f"{float(ligne['LCG_m']):.2f}", f"{float(ligne.get('TCG_m', 0.0)):+.2f}",
                       f"{fsm:.2f}", _d_cellule(cap)]
        else:
            pct, valeurs = 0.0, ["—"] * 5 + [_d_cellule(cap)]
        # la densité se tape comme les mesures, dès que la capacité existe :
        # elle est le quatrième chiffre du relevé, pas une donnée figée
        modifiee = t.densite_modifiee(nav)
        for c, v in zip((C_POIDS, C_VCG, C_LCG, C_TCG, C_FSM, C_D), valeurs):
            it = self._item(v, editable=(c == C_D and cap is not None))
            if c == C_D and cap is not None and modifiee:
                # même marque que la mesure relevée : gras, plus une teinte —
                # un chiffre qui s'écarte du dossier ne doit jamais se
                # confondre avec un chiffre du dossier
                f = QFont(it.font())
                f.setBold(True)
                it.setFont(f)
                it.setForeground(QColor(theme.ACCENT_DARK))
                it.setToolTip(
                    f"Densité de ce point : {densite_texte(cap.density)} "
                    f"(dossier : {densite_texte(cap.densite_dossier)}). "
                    "Effacez la case pour revenir à celle du dossier.")
            elif c == C_D and cap is not None:
                it.setToolTip(
                    f"Densité du contenu ({densite_texte(cap.density)} t/m³), "
                    "celle du dossier : poids = volume × densité. Tapez ici la "
                    "densité relevée au point de chargement — la livraison de "
                    "gazole, l'eau saumâtre — le dossier n'est pas touché.")
            elif c == C_D:
                it.setToolTip("Capacité inconnue du navire : sa densité ne se "
                              "relève pas, elle ne pèse rien dans le calcul.")
            elif c == C_POIDS and ligne is not None and cap is not None:
                it.setToolTip(f"{float(ligne['Volume_m3']):.2f} m³ × "
                              f"{densite_texte(cap.density)} = "
                              f"{float(ligne['Poids_t']):.2f} t"
                              + (f" (densité du point ; dossier : "
                                 f"{densite_texte(cap.densite_dossier)})"
                                 if modifiee else ""))
            if c == C_FSM and ligne is not None and est_slack(pct):
                it.setForeground(QColor(theme.WARN))
                it.setToolTip(
                    "Capacité partiellement remplie : le moment de carène liquide "
                    f"s'applique (convention « {getattr(nav, 'convention_fsm', 'max')} » "
                    f"du dossier ; valeur tabulée à ce remplissage : "
                    f"{float(ligne['FSM_tm']):.2f} t·m).")
            elif c == C_FSM and ligne is not None:
                it.setToolTip("Capacité vide ou pleine : pas de carène liquide "
                              f"(valeur tabulée : {float(ligne['FSM_tm']):.2f} t·m).")
            self.setItem(r, c, it)

        if cap is None and nav is not None:
            for c in range(len(COLS)):
                it = self.item(r, c)
                it.setForeground(QColor(theme.DANGER))
                it.setToolTip("Cette capacité n'existe plus dans le navire : "
                              "elle n'entre pas dans le calcul. Vérifiez le dossier.")
        elif ligne is None and cap is not None:
            # La capacité EXISTE, mais son relevé n'a pas donné de ligne de
            # jauge : pas de table de jaugeage, ou relevé hors table. Le
            # tableau affichait « — » partout avec l'info-bulle « Déduit de la
            # table de jaugeage » — un mensonge, puisqu'il n'y a rien à
            # déduire. On dit ce qui cloche, sur toute la rangée (D-23 : le
            # logiciel rappelle ses limites plutôt que de les laisser croire).
            motif = t.probleme or ("relevé inexploitable pour "
                                   f"« {t.capacite} »")
            for c in range(len(COLS)):
                it = self.item(r, c)
                if it is None:
                    continue
                it.setForeground(QColor(theme.WARN))
                it.setToolTip(f"Aucune ligne de jauge : {motif}. Cette "
                              "capacité pèse 0 dans tous les totaux tant que "
                              "le relevé n'est pas exploitable.")

    def _poser_total(self, r, a):
        fond = QColor(theme.SURFACE_2)
        self.setSpan(r, C_NOM, 1, 2)
        vals = {C_NOM: "TOTAL CAPACITÉS — " + f"{a.n} capacité(s), {a.n_slack} en carène liquide",
                C_VOL: f"{a.volume:.2f}", C_PC: f"{a.pc_moyen:.1f}" if a.poids else "",
                C_POIDS: f"{a.poids:.2f}", C_VCG: f"{a.vcg:.2f}" if a.poids else "",
                C_LCG: f"{a.lcg:.2f}" if a.poids else "",
                C_TCG: f"{a.tcg:+.2f}" if a.poids else "", C_FSM: f"{a.fsm:.2f}"}
        for c in range(len(COLS)):
            v = vals.get(c, "")
            it = self._item(v, alignement_droite=(c >= C_SONDE))
            f = QFont(it.font())
            f.setBold(True)
            it.setFont(f)
            it.setBackground(fond)
            it.setForeground(QColor(theme.ACCENT_DARK))
            self.setItem(r, c, it)

    # ------------------------------------------------------------- édition
    def _on_edit(self, item):
        if self._loading:
            return
        r, c = item.row(), item.column()
        if r >= len(self._lignes) or self._lignes[r][0] != "tank":
            return
        if c == C_D:
            self._editer_densite(r, item)
            return
        if c not in MESURES:
            return
        _genre, t, cap = self._lignes[r]
        txt = item.text().strip().replace(",", ".").replace("%", "").replace("m³", "").strip()
        try:
            v = float(txt)
        except ValueError:
            self.refresh()
            return
        v = max(0.0, v)
        # borner à ce que la table de jaugeage couvre : une sonde plus haute
        # que la capacité n'a pas de sens, et l'inventer serait pire
        if cap is not None:
            lo, hi = cap.plage(COLONNE_JAUGE[c]) if c != C_PC else (0.0, 100.0)
            if hi > 0 and v > hi + 1e-9:
                self.message.emit(
                    f"{t.capacite} : {v:g} {UNITES[c]} dépasse le maximum "
                    f"tabulé ({hi:g} {UNITES[c]}) — ramené à ce maximum.")
                v = hi
            elif v < lo - 1e-9:
                v = lo
        t.mesure, t.valeur = MESURES[c], v
        self.refresh()
        self.changed.emit()

    # ------------------------------------------------------------- densité
    def _editer_densite(self, r, item):
        """La densité tapée dans la colonne « d ».

        Trois gestes, un seul champ : taper une densité la relève pour CE
        point ; effacer la case, ou retaper celle du dossier, efface le relevé
        et rend la main au dossier (`densite = None` — et non la valeur
        recopiée, pour qu'une correction ultérieure du dossier suive).

        Une saisie hors de [0, 3] n'est pas silencieusement rabotée comme une
        sonde trop haute : une sonde de 9 m dans une soute de 2 m est une
        mesure hors table, une densité de 12 est une faute de frappe. On la
        refuse en le disant, et la ligne revient à ce qu'elle était."""
        _genre, t, cap = self._lignes[r]
        if cap is None:
            self.refresh()
            return
        txt = item.text().strip().replace(",", ".").replace("t/m³", "").strip()
        d0 = float(cap.density)
        if txt == "" or txt == "—":
            change = t.densite is not None
            t.densite = None
            if change:
                self.message.emit(
                    f"{t.capacite} : densité revenue à celle du dossier "
                    f"({densite_texte(d0)}).")
            self.refresh()
            if change:
                self.changed.emit()
            return
        try:
            d = float(txt)
        except ValueError:
            self.message.emit(f"{t.capacite} : « {item.text().strip()} » n'est "
                              "pas une densité — valeur inchangée.")
            self.refresh()
            return
        if d <= DENSITE_MINI or d > DENSITE_MAXI:
            self.message.emit(
                f"{t.capacite} : densité {densite_texte(d)} refusée — on "
                f"attend une valeur entre 0 et {DENSITE_MAXI:g} t/m³ "
                "(eau de mer 1,025 ; gazole 0,840). Valeur inchangée.")
            self.refresh()
            return
        ancienne = t.densite
        # retaper la densité du dossier, c'est revenir au dossier : le point
        # ne porte alors plus de relevé de densité, et il ne le prétend pas
        t.densite = None if abs(d - d0) <= 5e-4 else d
        if t.densite == ancienne or (t.densite is not None and ancienne is not None
                                     and abs(t.densite - ancienne) <= 1e-12):
            self.refresh()
            return
        self._dire_la_densite(t, d0)
        self.refresh()
        self.changed.emit()

    def _dire_la_densite(self, t, d0):
        """Ce qui a changé, dans la barre d'état : la densité employée, le
        poids qu'elle donne, et de quoi on s'écarte."""
        nav = self._nav()
        ligne = t.ligne(nav)
        poids = f" — {float(ligne['Poids_t']):.2f} t" if ligne else ""
        if t.densite is None:
            self.message.emit(
                f"{t.capacite} : densité revenue à celle du dossier "
                f"({densite_texte(d0)}){poids}.")
        else:
            self.message.emit(
                f"{t.capacite} : densité de ce point {densite_texte(t.densite)} "
                f"(dossier : {densite_texte(d0)}){poids}. Le dossier du navire "
                "n'est pas modifié.")

    def _menu_contextuel(self, pos):
        """Les deux gestes de densité qu'on ne veut pas taper à la main."""
        menu = self.menu_densite(self.rowAt(pos.y()))
        if menu is not None:
            menu.exec(self.viewport().mapToGlobal(pos))

    def menu_densite(self, r):
        """Le menu du clic droit sur une ligne de capacité, ou None.

        Séparé de l'affichage pour qu'on puisse le construire — et lire ses
        intitulés — sans ouvrir de fenêtre modale : un menu qui s'exécute ne
        se vérifie pas hors écran."""
        if r < 0 or r >= len(self._lignes) or self._lignes[r][0] != "tank":
            return None
        _genre, t, cap = self._lignes[r]
        if cap is None:
            return None
        d0 = float(cap.density)
        groupe = self._groupe_de_rangee.get(r, "")

        menu = QMenu(self)
        act_dossier = QAction(f"Densité du dossier ({densite_texte(d0)})", menu)
        act_dossier.setToolTip(
            "Efface la densité relevée à ce point : la capacité reprend celle "
            "du dossier du navire.")
        act_dossier.setEnabled(t.densite is not None)
        act_dossier.triggered.connect(lambda: self._revenir_au_dossier(t, d0))
        menu.addAction(act_dossier)

        act_groupe = QAction("Appliquer cette densité à tout le groupe", menu)
        act_groupe.setToolTip(
            f"Donne à toutes les capacités du groupe « {groupe} » la densité "
            "de cette ligne : une livraison de gazole a UNE densité, pas une "
            "par soute.")
        act_groupe.setEnabled(bool(groupe))
        act_groupe.triggered.connect(lambda: self._densite_au_groupe(t, groupe))
        menu.addAction(act_groupe)
        return menu

    def _revenir_au_dossier(self, t, d0):
        if t.densite is None:
            return
        t.densite = None
        self._dire_la_densite(t, d0)
        self.refresh()
        self.changed.emit()

    def _densite_au_groupe(self, source, groupe):
        """La densité de la ligne cliquée, donnée à tout son groupe.

        On recopie `densite` tel quel, None compris : si la ligne cliquée suit
        le dossier, tout le groupe y revient. C'est le geste réel du bord —
        « cette livraison-là », ou « tout le monde revient au dossier » — et il
        se lit dans les deux sens."""
        changes = []
        for _rr, t in self._tanks_du_groupe(groupe):
            if t is source or t.densite == source.densite:
                continue
            t.densite = source.densite
            changes.append(t.capacite)
        if not changes:
            self.message.emit(f"Groupe « {groupe} » : toutes les capacités "
                              "avaient déjà cette densité.")
            return
        if source.densite is None:
            self.message.emit(
                f"Groupe « {groupe} » : {len(changes)} capacité(s) revenue(s) à "
                "la densité de leur dossier (" + ", ".join(changes) + ").")
        else:
            self.message.emit(
                f"Groupe « {groupe} » : densité {densite_texte(source.densite)} "
                f"appliquée à {len(changes)} autre(s) capacité(s) ("
                + ", ".join(changes) + "). Le dossier du navire n'est pas "
                "modifié.")
        self.refresh()
        self.changed.emit()

    def _tanks_du_groupe(self, groupe):
        """[(rangée, TankFill)] des capacités affichées dans ce groupe."""
        return [(rr, self._lignes[rr][1]) for rr in range(len(self._lignes))
                if self._lignes[rr][0] == "tank"
                and self._groupe_de_rangee.get(rr) == groupe]

    def _on_select(self):
        self.tank_selected.emit(self.tank_courant())

    # ------------------------------------------------------------- actions
    def zero_all(self):
        for t in self.condition.tanks:
            t.valeur = 0.0
        self.refresh()
        self.changed.emit()

    def resume(self):
        """Le résumé du relevé — celui qu'on retrouve au point du journal.

        Une densité relevée hors dossier y est DITE : un tonnage sans la
        densité qui l'a produit ne se vérifie pas."""
        a = getattr(self, "_total", None) or _Agregat()
        if a.poids <= 0:
            return "Toutes les capacités à zéro."
        txt = (f"{a.volume:.1f} m³ · {a.poids:.1f} t · LCG {a.lcg:.2f} m · "
               f"VCG {a.vcg:.2f} m · FSM {a.fsm:.1f} t·m")
        if a.n_densite:
            txt += f" · {a.n_densite} densité(s) relevée(s) hors dossier"
        return txt

    def notes(self):
        a = getattr(self, "_total", None) or _Agregat()
        out = []
        if a.n_slack:
            convention = getattr(self._nav(), "convention_fsm", "max")
            out.append(
                f"{a.n_slack} capacité(s) partiellement remplie(s) : carène "
                f"liquide comptée selon la convention « {convention} » du dossier.")
        else:
            out.append("Tapez la sonde relevée, le volume ou le pourcentage — "
                       "les deux autres colonnes suivent.")
        if a.n_densite:
            out.append(f"{a.n_densite} densité(s) relevée(s) à ce point, "
                       "différente(s) du dossier : en gras dans la colonne "
                       "« d ». Clic droit sur la ligne pour revenir au dossier "
                       "ou appliquer la densité à tout le groupe.")
        if a.n_orphelines:
            out.append(f"{a.n_orphelines} ligne(s) en rouge : capacité absente "
                       "du navire actuel, sans effet sur le calcul.")
        if a.n_probleme:
            out.append(f"{a.n_probleme} ligne(s) en orange : relevé sans ligne "
                       "de jauge (table absente ou valeur hors table) — "
                       "l'info-bulle dit laquelle, et elles pèsent 0.")
        out.append("Groupes et contenu se règlent dans « Créer ou modifier le "
                   "navire… » ; la densité du dossier aussi — celle qu'on tape "
                   "ici n'appartient qu'à ce point.")
        return "  ".join(out)


class _Agregat:
    """Sous-total d'un groupe de capacités : poids, centres, carène liquide."""

    def __init__(self):
        self.poids = self.volume = self.fsm = 0.0
        self.capacite_m3 = 0.0
        self._lm = self._tm = self._vm = 0.0
        # `n_probleme` : capacités connues du navire dont le relevé n'a PAS
        # pu être converti (table de jaugeage absente, relevé hors table…).
        # Elles pèsent 0 dans tous les totaux, et il faut le dire.
        self.n = self.n_slack = self.n_orphelines = self.n_probleme = 0
        # capacités dont la densité relevée au point s'écarte du dossier : le
        # total qu'on lit n'est alors plus celui du dossier, et il faut le dire
        self.n_densite = 0

    def ajouter(self, tank, nav):
        # la capacité TELLE QUE CHARGÉE : le sous-total doit être le chiffre du
        # calcul, donc lu à la densité du point (poids ET FSM, maximal compris)
        cap = tank.capacite_chargee(nav)
        ligne = tank.ligne(nav)
        if cap is None:
            self.n_orphelines += 1
            return
        self.n += 1
        if tank.densite_modifiee(nav):
            self.n_densite += 1
        self.capacite_m3 += cap.volume_max_m3
        if ligne is None:
            self.n_probleme += 1
            return
        p = float(ligne["Poids_t"])
        self.poids += p
        self.volume += float(ligne["Volume_m3"])
        # même règle que le moteur : FSM compté seulement en slack, selon la
        # convention du dossier — sinon le total du tableau contredit le calcul
        self.fsm += fsm_compte(ligne, cap, nav)
        self._lm += p * float(ligne["LCG_m"])
        self._tm += p * float(ligne.get("TCG_m", 0.0))
        self._vm += p * float(ligne["VCG_m"])
        if est_slack(ligne["Remplissage_pc"]):
            self.n_slack += 1

    def fusionner(self, autre):
        self.poids += autre.poids
        self.volume += autre.volume
        self.fsm += autre.fsm
        self.capacite_m3 += autre.capacite_m3
        self._lm += autre._lm
        self._tm += autre._tm
        self._vm += autre._vm
        self.n += autre.n
        self.n_slack += autre.n_slack
        self.n_orphelines += autre.n_orphelines
        self.n_probleme += autre.n_probleme
        self.n_densite += autre.n_densite

    @property
    def lcg(self):
        return self._lm / self.poids if self.poids else 0.0

    @property
    def tcg(self):
        return self._tm / self.poids if self.poids else 0.0

    @property
    def vcg(self):
        return self._vm / self.poids if self.poids else 0.0

    @property
    def pc_moyen(self):
        """Remplissage du groupe : volume relevé sur volume net total."""
        return 100.0 * self.volume / self.capacite_m3 if self.capacite_m3 else 0.0


def _fmt(v, c):
    return f"{v:.3f}" if c == C_SONDE else (f"{v:.2f}" if c == C_VOL else f"{v:.1f}")


def _d_cellule(cap):
    """La densité dans sa cellule : trois décimales, point décimal comme les
    autres colonnes chiffrées du tableau. Les infobulles et les messages, eux,
    sont de la prose française et portent la virgule (`densite_texte`).

    Trois décimales, et pas `:.3g` comme avant : `f"{1.025:.3g}"` donne
    « 1.02 », et la colonne étant désormais saisissable, retaper ce qu'on lit
    aurait changé la valeur. Ce qui s'affiche doit pouvoir se retaper."""
    return "" if cap is None else f"{float(cap.density):.3f}"


# Intitulés lisibles des types usuels, comparés SANS casse : chaque chantier a
# son vocabulaire, un type inconnu est affiché tel quel.
CONTENUS = {
    "sea water": "Eau de mer", "seawater": "Eau de mer",
    "water ballast": "Eau de mer", "ballast": "Eau de mer",
    "eau de mer": "Eau de mer", "freshwater": "Eau douce",
    "fresh water": "Eau douce", "eau douce": "Eau douce",
    "gasoil": "Gasoil", "gas oil": "Gasoil", "mdo": "MDO",
    "diesel oil": "Diesel", "fuel oil": "Fuel", "hfo": "HFO",
    "oil": "Huile", "lub oil": "Huile", "huile": "Huile",
    "greywater": "Eaux grises", "grey water": "Eaux grises",
    "blackwater": "Eaux noires", "black water": "Eaux noires",
    "sewage": "Eaux noires", "urea": "Urée", "sludge": "Boues",
    "l.n.g.2": "GNL", "lng": "GNL",
}


def _contenu(cap):
    t = str(cap.meta.get("Type", "") or "").strip()
    return CONTENUS.get(t.lower(), t or "—")
