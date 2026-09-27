# -*- coding: utf-8 -*-
"""Saisie « Liquides » : le relevé des capacités existantes.

Les capacités (combustible, ballasts, huile, eau douce…) ont été définies une
fois pour toutes à la création du navire, avec leurs tables de jaugeage et leur
position. Ici, on ne fait que **relever une mesure** : une hauteur de sonde ou
un volume. Tout le reste — poids, centres de gravité, moment de carène liquide
— est lu dans la table de jaugeage du navire, jamais saisi.

La vue isométrique n'est là que pour situer et visualiser.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .isoview import IsoView
from .project import KIND_CONTOUR
from .tanks_table import TanksTable

class LiquidsPanel(QWidget):
    """Tableau des capacités liquides + vue de situation."""

    changed = Signal()

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        header = QLabel("CAPACITÉS — relevez la sonde, le volume ou le pourcentage")
        header.setObjectName("viewHeader")
        root.addWidget(header)

        # tableau à gauche, situation 3D à droite : l'iso a enfin la place de
        # se lire, et le remplissage s'y voit capacité par capacité
        split = QSplitter(Qt.Orientation.Horizontal)

        haut = QWidget()
        lay = QVBoxLayout(haut)
        lay.setContentsMargins(9, 8, 9, 6)
        lay.setSpacing(8)
        self.table = TanksTable(win)
        self.table.changed.connect(self._on_table_changed)
        self.table.message.connect(self._message)
        self.table.tank_selected.connect(self._on_tank_selected)
        lay.addWidget(self.table, 1)
        # l'iso est créée plus bas : son clic est branché après (D-87)

        row = QHBoxLayout()
        row.setSpacing(9)
        # Pas de bouton « ajouter » ni « retirer » : les capacités sont celles
        # du navire, toujours toutes présentes. On ne compose pas la liste, on
        # porte une mesure en face de chacune.
        b_zero = QPushButton("Tout à zéro")
        b_zero.setProperty("ghost", "1")
        b_zero.clicked.connect(self.zero_all)
        # le ballastage se règle devant le relevé des capacités : son bouton
        # est ici, pas dans la barre d'outils générale
        b_ball = QPushButton("Ballastage…")
        b_ball.setProperty("accent", "1")
        b_ball.setToolTip(
            "Chercher la meilleure répartition dans les ballasts (F8) : "
            "redresser la gîte, tenir l'assiette, garder le GM.")
        b_ball.clicked.connect(self._ballast)
        row.addWidget(b_ball)
        row.addWidget(b_zero)
        row.addStretch(1)
        self.lbl_total = QLabel("")
        self.lbl_total.setStyleSheet("font-weight: bold;")
        row.addWidget(self.lbl_total)
        lay.addLayout(row)
        self.lbl_note = QLabel("")
        self.lbl_note.setObjectName("hint")
        self.lbl_note.setWordWrap(True)
        lay.addWidget(self.lbl_note)
        split.addWidget(haut)

        bas = QWidget()
        lay2 = QVBoxLayout(bas)
        lay2.setContentsMargins(0, 0, 0, 0)
        lay2.setSpacing(0)
        t = QLabel("SITUATION — visualisation seule · molette : zoom · "
                   "glisser : tourner · milieu ou Espace + glisser : déplacer")
        t.setObjectName("viewHeader")
        lay2.addWidget(t)
        self.lbl_schema = QLabel("")
        self.lbl_schema.setObjectName("hint")
        self.lbl_schema.setWordWrap(True)
        self.lbl_schema.setContentsMargins(12, 6, 12, 0)
        self.lbl_schema.setVisible(False)
        lay2.addWidget(self.lbl_schema)
        self.iso = IsoView()
        # un clic sur une capacité dans la vue 3D la choisit AU TABLEAU, qui
        # l'allume en retour : un seul chemin, dans les deux sens (D-87)
        self.iso.boites_choisissables = True
        self.iso.capacity_clicked.connect(self._on_iso_clicked)
        lay2.addWidget(self.iso, 1)
        split.addWidget(bas)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 4)
        split.setSizes([880, 700])
        root.addWidget(split, 1)
        self.refresh()

    # ------------------------------------------------------------- données
    @property
    def condition(self):
        return self.win.condition

    def _nav(self):
        return getattr(self.win, "nav", None)

    def fill_ratio(self, cap):
        """Remplissage d'une capacité dessinée, si elle est au relevé."""
        nav = self._nav()
        for t in self.condition.tanks:
            if t.capacite == cap.code or t.capacite == cap.name:
                return max(0.0, min(1.0, t.fill_pc(nav) / 100.0))
        return 0.0

    def refresh(self):
        self._loading = True
        try:
            # la liste vient du navire, pas du chargement : on la complète
            # avant d'afficher, au cas où le navire aurait changé
            self.condition.synchroniser_capacites(self._nav())
            self._refresh_table()
        finally:
            self._loading = False
        proj = getattr(self.win, "project", None)
        c, boites = self._schematique(proj)
        self.iso.rebuild(proj, load_ratio=self.fill_ratio, coque=c,
                         boites=boites, filtre=self.est_capacite,
                         couleur=self.couleur_de)
        # On ne recadre qu'au PREMIER rendu : recadrer à chaque relevé annulait
        # le zoom, l'angle de vue et le déplacement qu'on venait de régler —
        # trente sondes à saisir, trente fois la vue qui se remet à zéro. Le
        # bouton « Recadrer » (et F3 puis Recadrer) reste là pour le demander.
        if not getattr(self, "_iso_cadree", False) and self.iso.scene().items():
            self.iso.fit()
            self._iso_cadree = True

    def couleur_de(self, cap):
        """La teinte du groupe de cette capacité (eau douce, combustible,
        ballast…), la même que dans le tableau — pour une forme tracée sur
        plan (`code`/`name`) comme pour une boîte schématique (`nom`)."""
        nav = self._nav()
        if nav is None:
            return None
        from .core.groupes import groupe_de
        from .tanks_table import teinte
        for cle in (getattr(cap, "code", None), getattr(cap, "name", None),
                    getattr(cap, "nom", None)):
            c = nav.capacities.get(cle) if cle else None
            if c is not None:
                r, g, b = teinte(groupe_de(c))
                return f"#{r:02x}{g:02x}{b:02x}"
        return None

    def est_capacite(self, cap):
        """Cette forme tracée est-elle une capacité liquide du dossier ?

        Ici on ne montre que les capacités : les cales tracées sur les mêmes
        ponts appartiennent à la vue de chargement."""
        nav = self._nav()
        if nav is None:
            return True
        return nav.est_capacite(cap.code) or nav.est_capacite(cap.name)

    def _schematique(self, proj):
        """Silhouette et capacités reconstituées depuis les tables.

        Deux décisions distinctes, pour que la vue ne soit jamais vide :

        - la **coque** schématique ne s'affiche que si aucun contour de pont
          n'est tracé — dès qu'un vrai plan existe, c'est lui qui prime ;
        - les **capacités** schématiques s'affichent pour toute capacité du
          navire qui n'est pas tracée sur plan — les 33 soutes et ballasts
          d'un navire ne disparaissent pas parce qu'on a tracé deux cales.

        Rien n'est enregistré ; mais la reconstitution ne dépend que du
        navire (tables) et des plans tracés, pas du chargement : elle est
        faite une fois par navire et gardée en mémoire — la refaire à chaque
        sonde relevée coûtait quinze secondes sur le navire de référence
        (33 capacités).
        Seul le remplissage est remis à jour à chaque passage.

        Le cache est maintenant **partagé** avec la vue Stabilité et les
        rapports (`core.coque.coque_du_navire`) : ce panneau n'en garde plus
        qu'une vue filtrée, dont il peut teindre le remplissage sans risquer
        de le faire lire ailleurs."""
        nav = self._nav()
        if nav is None:
            self.lbl_schema.setVisible(False)
            return None, None
        deja_trace = bool(proj) and any(
            c.kind == KIND_CONTOUR and len(c.points) >= 3
            for _, c in proj.all_capacities())
        try:
            from .core import coque as _coque
            traces = {cap.code for _, cap in proj.all_capacities()} if proj \
                else set()
            cle = (id(nav), id(proj), tuple(sorted(traces)))
            cache = getattr(self, "_cache_schema", None)
            if cache is None or cache[0] != cle:
                # la coque et l'emprise des capacités sont gardées par
                # `core.coque`, une fois par navire et pour tout le logiciel :
                # la vue Stabilité et les rapports s'en servent aussi
                c = _coque.coque_du_navire(nav)
                boites = [b for b in _coque.boites_du_navire(nav)
                          if b.nom not in traces]
                self._cache_schema = (cle, c, boites)
            _cle, c, boites = self._cache_schema
            # le remplissage relevé se voit dans la 3D : hauteur de liquide
            # dans chaque capacité, à l'échelle
            taux = {t.capacite: t.fill_pc(nav) / 100.0
                    for t in self.condition.tanks}
            for b in boites:
                b.fill = max(0.0, min(1.0, taux.get(b.nom, 0.0)))
        except Exception as e:                        # pragma: no cover
            self.lbl_schema.setText(f"Silhouette non reconstituée : {e}")
            self.lbl_schema.setVisible(True)
            return None, None
        coque_affichee = None if deja_trace else c
        notes = []
        if coque_affichee is not None:
            notes.append(
                "Silhouette <b>schématique</b>, reconstituée depuis les "
                "tables du navire — aucun plan n'est calé. Elle respecte, à "
                "chaque tirant d'eau tabulé, le volume, l'aire de flottaison "
                "et le centre de flottaison du dossier ; le reste est supposé. "
                + " ".join(c.messages if c else []))
        if boites:
            notes.append(
                f"{len(boites)} capacité(s) en position <b>schématique</b> "
                "(déduite des tables de jaugeage ; l'emprise au sol est "
                "supposée) — le remplissage relevé s'y lit à l'échelle.")
        self.lbl_schema.setText("<br>".join(notes))
        self.lbl_schema.setVisible(bool(notes))
        return coque_affichee, boites

    def _refresh_table(self):
        self.table.refresh()
        self.lbl_total.setText(self.table.resume())
        self.lbl_note.setText(self.table.notes())

    # ------------------------------------------------------------- édition
    def _on_table_changed(self):
        self.lbl_total.setText(self.table.resume())
        self.lbl_note.setText(self.table.notes())
        self.changed.emit()

    def _message(self, texte):
        barre = getattr(self.win, "statusBar", None)
        if callable(barre):
            barre().showMessage(texte, 9000)

    def _on_tank_selected(self, tank):
        """La ligne choisie s'éclaire dans la vue de situation."""
        if tank is None:
            return
        proj = getattr(self.win, "project", None)
        if proj is None:
            return
        for _, cap in proj.all_capacities():
            if cap.kind != KIND_CONTOUR and cap.code == tank.capacite:
                self.iso.select_capacity(cap)
                return
        # pas tracée sur plan : sa boîte schématique s'allume (D-87)
        self.iso.choisir(tank.capacite)

    def _on_iso_clicked(self, cap):
        if cap is None:
            return
        code = getattr(cap, "code", None) or getattr(cap, "nom", None)
        if not self.table.choisir_capacite(code):
            self.iso.choisir(code)

    def _ballast(self):
        ouvrir = getattr(self.win, "open_ballast", None)
        if callable(ouvrir):
            ouvrir()

    def zero_all(self):
        # le tableau émet déjà `changed` (relayé par _on_table_changed) : le
        # réémettre ici déclenchait deux recalculs complets pour un seul geste
        self.table.zero_all()
