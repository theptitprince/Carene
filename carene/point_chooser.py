# -*- coding: utf-8 -*-
"""Au lancement : sur quel point veut-on travailler ?

Un journal de bord ne s'ouvre pas au hasard. Si le navire a déjà des points,
on demande — en proposant d'emblée ce qu'on veut neuf fois sur dix : continuer
le point en cours, ou en ouvrir un nouveau si le dernier est figé.

**Ce qu'on lit pour choisir**, et rien d'autre : le numéro, la date du point,
le lieu, le libellé, la **note** — le texte, c'est lui qui dit « chargement
d'Alger, reste deux lots à quai » — le nombre de colis posés, l'état et la
date de dernière modification. Le déplacement, le GM et le verdict ont quitté
le tableau : ils ne servent à personne pour désigner un point (« ils ne nous
intéressent pas pour choisir le point », parole du bord), et ils tenaient la
place de la note. Ils restent en infobulle, sur la colonne de l'état.

La question ne se pose pas quand le journal est vide (il n'y a rien à choisir),
et se coupe d'une case à cocher pour qui la trouve inutile.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from . import app_paths

# Les colonnes du choix du point. La NOTE prend toute la place restante :
# c'est elle qu'on lit pour reconnaître un point, et elle seule gagne à
# s'allonger. Les deux dates sont distinctes, comme dans la vue Journal :
# « Date du point » est l'événement, « Modifié le » le dernier enregistrement.
(C_NUM, C_VOYAGE, C_DATE, C_LIEU, C_LIBELLE, C_NOTE, C_COLIS, C_ETAT,
 C_MODIF) = range(9)
COLS = ["N°", "Voyage", "Date du point", "Lieu", "Libellé", "Notes",
        "Colis posés", "État", "Modifié le"]

# Ce qu'on montre d'une note dans le tableau : de quoi reconnaître le point
# d'un coup d'œil. La note entière est en infobulle — on ne la tronque que
# pour l'affichage, jamais dans le fichier.
NOTE_CAR = 90


def _poids(t):
    return f"{float(t):,.1f} t".replace(",", " ")


def _debut_note(note):
    """Les premiers mots de la note, sur une ligne, élidés proprement.

    Élidé sur un mot entier plutôt qu'au milieu d'une syllabe : « reste deux
    lots à… » se lit, « reste deux lots à qu… » se déchiffre."""
    texte = " ".join((note or "").split())
    if not texte:
        return "—"
    if len(texte) <= NOTE_CAR:
        return texte
    coupe = texte[:NOTE_CAR]
    espace = coupe.rfind(" ")
    if espace > NOTE_CAR // 2:
        coupe = coupe[:espace]
    return coupe.rstrip(" ,;:.") + "…"


class PointChooser(QDialog):
    """Choix du point de travail au démarrage. `resultat` dit ce qu'on veut :
    ("ouvrir", point) · ("nouveau", point_source) · ("continuer", None)."""

    def __init__(self, win, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.resultat = ("continuer", None)
        self.setWindowTitle("Sur quel point travailler ?")
        self.resize(1000, 460)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(9)
        titre = QLabel(f"JOURNAL DE {app_paths.ship_name() or 'CE NAVIRE'}")
        titre.setObjectName("cardTitle")
        root.addWidget(titre)
        self.lbl = QLabel("")
        self.lbl.setObjectName("hint")
        self.lbl.setWordWrap(True)
        root.addWidget(self.lbl)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        head = self.table.horizontalHeader()
        for c in range(len(COLS)):
            head.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(C_NOTE, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemDoubleClicked.connect(lambda _i: self._ouvrir())
        root.addWidget(self.table, 1)

        self.chk = QCheckBox("Ne plus poser la question au lancement")
        root.addWidget(self.chk)

        row = QHBoxLayout()
        b_new = QPushButton("Nouveau point")
        b_new.setProperty("ghost", "1")
        b_new.setToolTip("Copie intégrale du point choisi (ou du dernier).")
        b_new.clicked.connect(self._nouveau)
        b_open = QPushButton("Ouvrir le point choisi")
        b_open.setProperty("accent", "1")
        b_open.clicked.connect(self._ouvrir)
        row.addWidget(b_new)
        row.addStretch(1)
        row.addWidget(b_open)
        root.addLayout(row)
        self._remplir()

    # ------------------------------------------------------------- rendu
    def _ordre(self):
        """Les points du plus récent au plus ancien, le point EN COURS en tête.

        C'est celui qu'on reprend neuf fois sur dix : il se présente le premier
        et présélectionné, pour que « Entrée » suffise. Un point figé n'a pas
        ce privilège — on n'y travaille pas."""
        points = list(reversed(self.win.journal.points())) if self.win.journal else []
        courant = self.win.point
        if courant is None:
            return points, None
        # le point courant est montré tel qu'il est EN MÉMOIRE (libellé tapé,
        # note écrite, colis posés non encore enregistrés) et non tel qu'il est
        # sur le disque : sinon la ligne décrit un point qui n'est plus celui
        # qu'on a sous les yeux
        points = [courant if p.numero == courant.numero else p for p in points]
        if not any(p is courant for p in points):
            points.insert(0, courant)
        elif not courant.fige:
            points.remove(courant)
            points.insert(0, courant)
        return points, courant

    def _remplir(self):
        self._points, courant = self._ordre()
        self.table.setRowCount(len(self._points))
        choisi = 0
        for r, p in enumerate(self._points):
            res = p.resultats or {}
            # la cargaison ne se calcule pas : c'est la somme des charges
            # posées, archivée dans le point lui-même (voir Point.poids_cargaison_t)
            cargo = res.get("cargaison") or _poids(p.poids_cargaison_t)
            colis = f"{p.nb_colis_poses} · {cargo}" if p.nb_colis_poses else "—"
            vals = [str(p.numero), p.voyage or "—", p.date_lisible,
                    p.lieu or "—", p.libelle or "—", _debut_note(p.note),
                    colis,
                    p.etat + ("" if p.path or p.fige else ", non enregistré"),
                    p.modifie_lisible]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if courant is not None and p.numero == courant.numero:
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                    choisi = r
                self.table.setItem(r, c, item)
            # la note ENTIÈRE en infobulle : la colonne n'en montre que le début
            if p.note:
                self.table.item(r, C_NOTE).setToolTip(p.note)
            # déplacement, GM et verdict : gardés, mais hors du tableau. On les
            # consulte quand on se demande comment ce point s'est terminé, pas
            # pour le désigner.
            self.table.item(r, C_ETAT).setToolTip(self._chiffres(p, res))
            self.table.item(r, C_COLIS).setToolTip(
                "Les colis posés dans les cales, empilement compris, et ce qu'ils pèsent.")
            self.table.item(r, C_MODIF).setToolTip(
                "Le dernier enregistrement de ce point. « — » : jamais enregistré, "
                "ou enregistré par une version antérieure.")
        self.table.selectRow(choisi)
        dernier = self.win.journal.dernier() if self.win.journal else None
        if dernier is not None and dernier.fige:
            self.lbl.setText(
                f"Le dernier point ({dernier.titre}) est <b>figé</b> : la suite se prépare "
                "dans un <b>nouveau point</b>, copie intégrale de celui-là. Vous pouvez aussi "
                "rouvrir un point pour le consulter — un point figé se lit, il ne se modifie pas.")
        else:
            self.lbl.setText("Choisissez le point sur lequel travailler, ou ouvrez-en un "
                             "nouveau. La note de chaque point est en entier en infobulle.")

    def _chiffres(self, p, res):
        """Ce qu'on a lu à l'écran à ce point — en infobulle, pas au tableau."""
        lignes = [f"{p.titre} — {p.etat}"]
        for libelle, cle in (("Déplacement", "deplacement"), ("GM corrigé", "gm"),
                             ("Verdict", "verdict")):
            v = res.get(cle)
            lignes.append(f"{libelle} : {v if v not in (None, '') else '—'}")
        if not p.fige:
            lignes.append("Point en cours : tout est recalculé à l'ouverture.")
        return "\n".join(lignes)

    # ------------------------------------------------------------- actions
    def _selection(self):
        r = self.table.currentRow()
        return self._points[r] if 0 <= r < len(self._points) else None

    def _ouvrir(self):
        p = self._selection()
        self.resultat = ("ouvrir", p) if p is not None else ("continuer", None)
        self.accept()

    def _nouveau(self):
        self.resultat = ("nouveau", self._selection())
        self.accept()

    # ------------------------------------------------------------- réglage
    def ne_plus_demander(self):
        return self.chk.isChecked()
