# -*- coding: utf-8 -*-
"""Le matériel du bord — l'inventaire des engins qui appartiennent au navire.

« Un transpalette ou un clark qui appartiennent au bateau et servent pour le
chargement n'ont pas leur place dans le manifeste, mais participent à la
stabilité quand même. » — c'est exactement ce que cette fenêtre tient.

Deux choses distinctes, et c'est tout le modèle :

- l'**engin** appartient au NAVIRE. Il est là à chaque voyage, il ne
  s'embarque ni ne se débarque à l'escale : il vit dans `equipements_bord.json`
  du dossier du navire, à côté du catalogue des charges. C'est ce tableau, et
  on y tape comme dans le catalogue ;
- sa **position** appartient au POINT. Où le chariot est arrimé change à
  chaque escale et doit s'archiver avec le point : c'est un `Placement` du
  chargement, posé et déplacé sur le plan comme n'importe quelle charge.

D'où la colonne « Où » : elle lit le plan, elle ne le commande pas. Retirer un
engin du plan ne le retire pas de l'inventaire — il est toujours à bord,
simplement pas encore arrimé.

Une fiche porte une **quantité** : un armement a rarement un seul transpalette,
et compter chaque exemplaire dans sa propre fiche ferait N lignes identiques
(D-37). Les N exemplaires se posent un par un sur le plan, comme un lot du
manifeste ; le poids « à bord » les compte tous, « arrimé(s) » ne compte que
ceux qui ont trouvé leur place. Deux engins qui n'ont PAS la même prescription
d'arrimage restent, eux, deux fiches : ce n'est pas la même donnée.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from . import theme
from .core.cargo_model import (COULEUR_MATERIEL_BORD, EquipementBord,
                               InventaireBord, couleur_hex)
from .manifest_panel import _pastille

# Pas de colonne « Catégorie » : elle ne sert qu'à teinter l'engin sur le plan,
# et la couleur est déjà là, à côté du nom. Les trois cotes, elles, ont chacune
# leur colonne — comme au catalogue et au manifeste (D-36).
COLS = ["À bord", "Coul.", "Désignation", "L (m)", "l (m)", "h (m)",
        "Poids t", "Qté", "Stack", "Où", "Note", "Source"]
(C_BORD, C_COUL, C_NOM, C_L, C_LARG, C_H, C_POIDS, C_QTE, C_GERB, C_OU,
 C_NOTE, C_SOURCE) = range(12)
EDITABLES = {C_NOM, C_L, C_LARG, C_H, C_POIDS, C_QTE, C_GERB, C_NOTE}
AIDES_COLONNES = {
    C_L: "Longueur de l'engin, le long de X quand la rotation vaut 0.",
    C_LARG: "Largeur de l'engin, le long de Y quand la rotation vaut 0.",
    C_H: "Hauteur de l'engin.",
    C_QTE: "Combien d'exemplaires identiques le navire en porte. On les pose "
           "un par un sur le plan, comme un lot ; le poids « à bord » les "
           "compte tous.",
    C_GERB: "Ce qui s'empile sur cet engin (stack) — 1 = rien. Le solveur, lui, n'y "
            "empile jamais rien : c'est un obstacle, pas une pile à garnir.",
}


def inventaire_du_bord(win):
    """L'inventaire du navire ouvert, chargé une fois et gardé sur la fenêtre.

    L'inventaire est une donnée du NAVIRE : il se lit dans son dossier, jamais
    dans le code. Tant que la fenêtre principale ne le porte pas elle-même, on
    le charge ici — et on le range au même endroit, pour que le plan, le
    manifeste et cette fenêtre parlent du même inventaire."""
    inv = getattr(win, "inventaire_bord", None)
    if inv is None:
        from . import app_paths
        inv = InventaireBord.load(app_paths.ship_folder())
        try:
            win.inventaire_bord = inv
        except AttributeError:          # pragma: no cover - fenêtre factice
            pass
    return inv


def enregistrer_inventaire(win, inventaire):
    """Écrit l'inventaire dans le dossier du navire. Retourne None ou l'erreur."""
    from . import app_paths
    try:
        inventaire.save(app_paths.ship_folder())
        return None
    except OSError as e:
        return str(e)


def adopter_migration(win, condition):
    """Verse dans l'inventaire le matériel repris d'un ancien fichier.

    Un point enregistré avant l'inventaire portait ses engins en lignes de
    manifeste « du bord » ; `LoadingCondition.from_dict` les en a sortis, il
    reste à les inscrire à l'inventaire du navire. On le fait une fois, en le
    disant — pas en douce, mais pas non plus en barrant la route."""
    if condition is None or not getattr(condition, "materiel_migre", None):
        return 0, ""
    inv = inventaire_du_bord(win)
    n = condition.adopter_materiel(inv)
    erreur = enregistrer_inventaire(win, inv) if n else None
    msg = " ".join(condition.dire_les_messages())
    if erreur:
        msg += f" (inventaire non enregistré : {erreur})"
    return n, msg


class EquipementsDialog(QDialog):
    """L'inventaire du matériel du bord, dans sa fenêtre."""

    changed = Signal()

    def __init__(self, win, parent=None):
        super().__init__(parent or win)
        self.win = win
        self._loading = False
        self._rows = []
        self.setWindowTitle("Matériel du bord — les engins du navire")
        self.resize(1040, 560)
        self.setModal(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        titre = QLabel("MATÉRIEL DU BORD — il appartient au navire, pas au voyage")
        titre.setObjectName("cardTitle")
        root.addWidget(titre)

        row = QHBoxLayout()
        b_add = QPushButton("+ un matériel")
        b_add.setProperty("accent", "1")
        b_add.setToolTip("Ajouter un engin à l'inventaire du navire : il sera là "
                         "à chaque voyage, sur chaque point.")
        b_add.clicked.connect(self.ajouter)
        b_del = QPushButton("Retirer de l'inventaire")
        b_del.setProperty("ghost", "1")
        b_del.setToolTip("L'engin quitte le navire pour de bon. S'il est posé "
                         "sur le plan, il en est retiré aussi.")
        b_del.clicked.connect(self.supprimer)
        b_off = QPushButton("Retirer du plan")
        b_off.setProperty("ghost", "1")
        b_off.setToolTip("Dépose l'engin — tous ses exemplaires : il reste à "
                         "l'inventaire et à bord, il n'est simplement plus "
                         "arrimé quelque part.")
        b_off.clicked.connect(self.retirer_du_plan)
        row.addWidget(b_add)
        row.addWidget(b_del)
        row.addWidget(b_off)
        row.addStretch(1)
        root.addLayout(row)

        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        head = self.table.horizontalHeader()
        for c in range(len(COLS)):
            head.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(C_NOM, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(C_NOTE, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setWordWrap(False)
        self.table.itemChanged.connect(self._on_edited)
        root.addWidget(self.table, 1)

        self.lbl_aide = QLabel(
            "L'<b>inventaire</b> est une donnée du navire : il ne change pas "
            "d'une escale à l'autre. La colonne <b>Où</b>, elle, appartient au "
            "point courant — on pose et on déplace un engin sur le plan de "
            "chargement, en le prenant dans le sélecteur de lots, groupe "
            "« Matériel du bord ». <b>Qté</b> dit combien le navire en porte : "
            "on en pose autant, un par clic, comme un lot. "
            "Il pèse dans le bilan et dans la stabilité "
            "comme n'importe quelle charge, mais il ne figure jamais au "
            "manifeste, et le solveur ne le déplace ni n'empile rien dessus.")
        self.lbl_aide.setObjectName("hint")
        self.lbl_aide.setWordWrap(True)
        root.addWidget(self.lbl_aide)

        bas = QHBoxLayout()
        self.lbl_total = QLabel("")
        self.lbl_total.setStyleSheet("font-weight: bold;")
        bas.addWidget(self.lbl_total)
        bas.addStretch(1)
        b_close = QPushButton("Fermer")
        b_close.setProperty("accent", "1")
        b_close.clicked.connect(self.accept)
        bas.addWidget(b_close)
        root.addLayout(bas)

    # ------------------------------------------------------------- lecture
    @property
    def inventaire(self):
        return inventaire_du_bord(self.win)

    @property
    def condition(self):
        return getattr(self.win, "condition", None)

    def _ou(self, e):
        """Où l'engin est arrimé, en clair : pont et cale, ou « non posé »."""
        cond = self.condition
        if cond is None:
            return "—", ""
        poses = cond.poses_du_materiel(e.id)
        n = max(1, int(e.quantite or 1))
        if not poses:
            return "non posé", ("À bord mais pas encore arrimé : posez-le sur "
                                "le plan de chargement."
                                + (f"\n{n} exemplaires à poser." if n > 1 else ""))
        noms = []
        for code, p in poses:
            pont = self._pont_de(code)
            noms.append(f"{code}" + (f" ({pont})" if pont else "")
                        + f" · x {p.x:.2f} y {p.y:.2f}")
        # avec plusieurs exemplaires, ce qui compte d'abord est COMBIEN sont
        # arrimés : la liste des positions passe en info-bulle
        texte = (" ; ".join(noms) if n == 1
                 else f"{len(poses)} / {n} posé(s) · " + " ; ".join(noms))
        return texte, "\n".join(noms)

    def _pont_de(self, code):
        proj = getattr(self.win, "project", None)
        if proj is None:
            return ""
        for deck in proj.sorted_decks():
            for cap in deck.capacities:
                if cap.code == code:
                    return deck.name
        return ""

    def refresh(self):
        self._loading = True
        try:
            inv = self.inventaire
            cond = self.condition
            self._rows = list(inv)
            self.table.setRowCount(len(self._rows))
            poids_bord = 0.0
            poids_pose = 0.0
            n_exemplaires = 0
            n_poses = 0
            for r, e in enumerate(self._rows):
                ou, aide_ou = self._ou(e)
                qte = max(1, int(e.quantite or 1))
                if e.a_bord:
                    # « à bord » compte TOUS les exemplaires : deux chariots
                    # pèsent deux fois, qu'ils soient arrimés ou non
                    poids_bord += e.poids_t * qte
                    n_exemplaires += qte
                poses = (cond.poses_du_materiel(e.id) if cond is not None else [])
                if poses:
                    poids_pose += sum(p.poids_total_t for _c, p in poses)
                    n_poses += len(poses)
                vals = ["", "", e.nom,
                        f"{e.longueur_m:g}", f"{e.largeur_m:g}", f"{e.hauteur_m:g}",
                        f"{e.poids_t:g}", str(qte), str(e.gerbable_max), ou,
                        e.note, e.source + ("  · à confirmer" if e.a_confirmer else "")]
                for c, v in enumerate(vals):
                    item = QTableWidgetItem(v)
                    if c not in EDITABLES:
                        item.setFlags(Qt.ItemFlag.ItemIsEnabled
                                      | Qt.ItemFlag.ItemIsSelectable)
                    if c in AIDES_COLONNES:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight
                                              | Qt.AlignmentFlag.AlignVCenter)
                        item.setToolTip(AIDES_COLONNES[c])
                    if c == C_BORD:
                        item.setFlags(Qt.ItemFlag.ItemIsEnabled
                                      | Qt.ItemFlag.ItemIsSelectable
                                      | Qt.ItemFlag.ItemIsUserCheckable)
                        item.setCheckState(Qt.CheckState.Checked if e.a_bord
                                           else Qt.CheckState.Unchecked)
                        item.setToolTip(
                            "Décoché : l'engin est resté à terre. Il reste à "
                            "l'inventaire du navire, il ne pèse plus.")
                    if c == C_COUL:
                        item.setIcon(_pastille(couleur_hex(e)))
                        item.setToolTip("Couleur de cet engin sur le plan "
                                        "(contour tireté : ce n'est pas de la "
                                        "marchandise).")
                    if c == C_OU:
                        item.setToolTip(aide_ou)
                        if ou == "non posé":
                            item.setForeground(QColor(theme.TEXT_DIM))
                    if c == C_SOURCE and e.a_confirmer:
                        item.setForeground(QColor(theme.WARN))
                        item.setToolTip(
                            "Chiffre non sourcé : à confirmer avec le bord "
                            "avant de s'en servir pour un calage.")
                    self.table.setItem(r, c, item)
            if not self._rows:
                self.lbl_total.setText(
                    "Aucun matériel du bord déclaré pour ce navire.")
            else:
                self.lbl_total.setText(
                    f"{len(self._rows)} matériel(s) · {n_exemplaires} "
                    f"exemplaire(s) · {poids_bord:.2f} t à bord · "
                    f"{n_poses} posé(s), {poids_pose:.2f} t arrimé(s) sur le plan")
        finally:
            self._loading = False

    # ------------------------------------------------------------- édition
    def _engin(self, r):
        return self._rows[r] if 0 <= r < len(self._rows) else None

    def _enregistrer(self):
        erreur = enregistrer_inventaire(self.win, self.inventaire)
        if erreur:
            self.lbl_total.setText(f"Inventaire non enregistré : {erreur}")
        return erreur

    def _suivre_les_poses(self, e):
        """Un engin modifié se retrouve sur le plan : dimensions, poids et
        nom suivent, sinon le plan montrerait un chariot d'hier."""
        cond = self.condition
        if cond is None:
            return
        for _code, p in cond.poses_du_materiel(e.id):
            p.nom = e.nom
            p.longueur_m, p.largeur_m = e.longueur_m, e.largeur_m
            p.hauteur_m, p.poids_t = e.hauteur_m, e.poids_t
            p.categorie = e.categorie
            p.couleur = e.couleur or COULEUR_MATERIEL_BORD
            p.gerbable_max = max(1, int(e.gerbable_max or 1))
            p.rotation_permise = e.rotation_permise

    def _on_edited(self, item):
        if self._loading:
            return
        e = self._engin(item.row())
        if e is None:
            return
        c = item.column()
        txt = item.text().strip()
        try:
            if c == C_BORD:
                e.a_bord = item.checkState() == Qt.CheckState.Checked
                if not e.a_bord:
                    self._deposer(e)
            elif c == C_NOM:
                e.nom = txt or e.nom
            elif c in (C_L, C_LARG, C_H):
                val = float(txt.replace(",", "."))
                if val > 0:
                    setattr(e, {C_L: "longueur_m", C_LARG: "largeur_m",
                                C_H: "hauteur_m"}[c], val)
                    # un chiffre retapé par le bord n'est plus « à confirmer »
                    e.a_confirmer = False
            elif c == C_POIDS:
                val = float(txt.replace(",", "."))
                if val >= 0:
                    e.poids_t = val
                    e.a_confirmer = False
            elif c == C_QTE:
                n = max(1, int(float(txt)))
                # baisser la quantité ne dépose pas les exemplaires en trop :
                # ils sont arrimés quelque part, c'est au bord de les retirer
                # du plan (« Retirer du plan »). On ne défait pas un arrimage
                # au détour d'une correction de chiffre.
                e.quantite = n
            elif c == C_GERB:
                e.gerbable_max = max(1, int(float(txt)))
            elif c == C_NOTE:
                e.note = txt
        except ValueError:
            pass
        self._suivre_les_poses(e)
        self._enregistrer()
        self.refresh()
        self.changed.emit()

    def ajouter(self):
        inv = self.inventaire
        e = EquipementBord(nom="Matériel du bord", categorie="Engin",
                           longueur_m=1.0, largeur_m=1.0, hauteur_m=1.0,
                           poids_t=0.0, couleur=COULEUR_MATERIEL_BORD,
                           a_bord=True, a_confirmer=True,
                           source="saisi à bord")
        e.id = inv.unique_id("MB")
        inv.add(e)
        self._enregistrer()
        self.refresh()
        r = next((i for i, q in enumerate(self._rows) if q is e), 0)
        self.table.setCurrentCell(r, C_NOM)
        self.changed.emit()
        return e

    def _deposer(self, e):
        """Retire cet engin du plan — il reste à l'inventaire."""
        cond = self.condition
        if cond is None:
            return 0
        n = 0
        for code, p in cond.poses_du_materiel(e.id):
            lst = cond.placements.get(code) or []
            if p in lst:
                lst.remove(p)
                n += 1
        return n

    def retirer_du_plan(self):
        e = self._engin(self.table.currentRow())
        if e is None:
            return 0
        n = self._deposer(e)
        self.refresh()
        if n:
            self.changed.emit()
            self.lbl_total.setText(
                f"« {e.nom} » déposé : toujours à bord, plus arrimé.")
        return n

    def supprimer(self):
        """Retirer un engin de l'inventaire du NAVIRE — et donc du plan.

        Ce n'est pas « déposer » : l'engin quitte `equipements_bord.json`, le
        fichier est réécrit dans la foulée et ses poses disparaissent du point.
        Un geste de cette portée se confirme, comme le retrait d'un type du
        catalogue, et se dit ensuite dans le bandeau."""
        e = self._engin(self.table.currentRow())
        if e is None:
            return None
        cond = self.condition
        poses = len(list(cond.poses_du_materiel(e.id))) if cond is not None else 0
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance()
        # hors écran, on ne pose pas la question : le comportement par défaut
        # est celui du bouton (retirer)
        if not (app is not None and app.property("carene_tests")):
            detail = (f"\n\n{poses} pose(s) de cet engin seront supprimées du "
                      "plan de chargement." if poses else "")
            rep = QMessageBox.question(
                self, "Retirer de l'inventaire",
                f"Retirer « {e.nom} » de l'inventaire du bord ?\n"
                f"Source : {e.source or 'saisi à bord'}." + detail,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if rep != QMessageBox.StandardButton.Yes:
                return None
        self._deposer(e)
        self.inventaire.remove(e.id)
        self._enregistrer()
        self.refresh()
        self.changed.emit()
        self.lbl_total.setText(
            f"« {e.nom} » retiré de l'inventaire du bord"
            + (f" ({poses} pose(s) supprimée(s) du plan)." if poses else "."))
        return e
